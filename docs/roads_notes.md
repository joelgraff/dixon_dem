# Roads workstream notes

## What exists

- `pipeline/roads/common_roads.py` — geometry helpers: heightmap bilinear sampler
  (reads `game/data/heightmap_play_1m_road_conformed.r32`), polyline resample/
  smooth/offset/trim, triangle-soup mesh builder, curb-return fillet (quadratic
  bezier through the two edge-lines' intersection).
- `pipeline/roads/build_road_plan.py` — the real generator. Reads
  `game/data/{roads,bridges,rails}.json` + the heightmap, builds the whole
  network as a triangle soup + furniture-transform lists, chunks everything
  into 200 m cells by triangle/instance centroid, writes JSON to
  `game/roads/_build/chunk_<cx>_<cz>.json` + `manifest.json`. **Not tracked
  in git** (gitignore it if not already) — regenerate, don't hand-edit.
  Run: `cd pipeline/roads && ../../.venv/bin/python build_road_plan.py`
  (~70s, prints a triangle count and known-downtown-intersection count).
- `game/roads/tools/build_roads.gd` + `.tscn` + `.sh` — headless Godot tool
  that reads that JSON and bakes `res://roads/roads.tscn`: one `MeshInstance3D`
  per material per chunk (ArrayMesh built directly from the JSON arrays), one
  `StaticBody3D`/`ConcavePolygonShape3D` per chunk for walkable surfaces, and
  `MultiMeshInstance3D` per furniture kind per chunk. Run after regenerating
  the JSON: `game/roads/tools/build_roads.sh` (~15s).
- `game/roads/roads.gd` — attached to the baked scene's root. Runtime-only
  logic that can't be pre-baked: lamp night glow (emissive material swap, no
  per-instance lights), windrow/leaf-litter visibility by season. Listens to
  `WorldState.changed`; nothing runs per-frame.
- `game/roads/materials/` — small material set of my own (shared library is
  frozen, I only *read* it): `marking_yellow.tres` / `marking_white.tres`
  (paint, reuses `concrete_sidewalk` textures under a heavy tint so it gets
  snow coverage + wet sheen for free from the shared shader), `bridge_deck.tres`
  (buff-tinted concrete per `galena_bridge.md`), and `asphalt_road_plowed.tres`
  / `asphalt_patched_plowed.tres` (see Weather below).
- `game/roads/roads.tscn` — baked output, instanced into `world/world.tscn`
  (additive edit, one `ext_resource` + one `[node]` line) and into
  `game/roads/test_roads.tscn` (roads + `atmosphere.tscn`, no player needed).

## Perf

`game/roads/tools/perf_probe.gd`/`.tscn` (same pattern as terrain's own
probe) measures composed-world FPS at a busy downtown street viewpoint
(Galena & 1st looking toward the bridge, world/world.tscn = atmosphere +
terrain + buildings + roads together). Run:
`flock .locks/gpu.lock godot --path game --resolution 1600x900 res://roads/tools/perf_probe.tscn`
(not headless — needs real rendering). Latest result: **89.7 fps / 11.15 ms**,
comfortably above the 60 fps target.

## Known issue: composed frames show terrain, not road, on straight runs

Iter1 captures (`captures/roads/iter1/`) show correctly-grey, correctly-
cracked asphalt right at junctions (where I'm standing exactly on an
original OSM node), but on the straight ribbon *between* junctions the
visible ground is the terrain's own material, not mine — confirmed by
direct inspection of the baked chunk JSON: `asphalt_road_plowed` triangles
genuinely exist there (verified vertex/triangle density along the camera's
view ray, correct XZ span, correct Y matching `heightmap_play_1m_road_conformed.r32`
via the exact same bilinear-sample code terrain's own `TerrainHeight.gd`
uses) — the geometry is present and positioned correctly against the
authoritative heightmap. I could not find a road-side explanation after
extensive triangle/vertex-level inspection (ruled out: material caching,
junction fillet degeneracy, pullback/gap bugs — fixed two real bugs of that
kind along the way, see below, neither changed this symptom).

Best-supported explanation, given the coordinator's own brief: terrain is
mid-fix on a **"heightmap-vs-mesh scale"** bug — if terrain's currently-
rendered surface doesn't sit exactly on the heightmap file (likely a coarser/
simplified mesh deviating from the raw heightmap between its own sample
points, especially on slopes — Galena drops ~3m over a few hundred meters
here), a road sitting only +2.5cm above the *heightmap* (per spec) would be
occluded by a terrain surface that's locally higher than the heightmap. This
would also explain why it's fine exactly at surveyed OSM nodes (junctions)
but not along my resampled in-between points. **This is a terrain-side,
already-flagged, in-progress issue, not something I could fix from the roads
side without either guessing at a much larger/riskier Y-bias (which would
float roads once terrain's fix lands) or duplicating terrain's own mesh
logic.** Action for whoever picks this up: after terrain's scale fix lands,
re-run `pipeline/roads/build_road_plan.py` + `build_roads.sh` (no road-side
change needed) and re-capture; if the mismatch persists, compare
`TerrainHeight.get_height(x,z)` against terrain's actual rendered vertex Y
at a few of these exact points (e.g. `(1594.97, -1338.5)`, mid-block on South
Galena Ave, confirmed by chunk inspection to have `asphalt_road_plowed`
coverage there) to quantify the divergence.

One more, separate, rendering oddity noticed while chasing the above: the
`galena_bridge_deck` capture shows the camera as if submerged (murky green,
blurred) even positioned 3.5m above the bridge deck's actual Y (11.04, from
`bridges.json`, well above the ~5.9 river pool level) — this points at the
water system rendering some effect (a tall fog/volume, not just a thin pool
plane) reaching higher than the nominal water surface near the bridge. Not a
roads-owned file; flagging for the water/terrain owner.

## Fixes made this session (materials + a real geometry bug)

- **Marking materials were badly over-driven**: `marking_yellow`/`marking_white`
  used `albedo_multiplier` 1.9–2.05 on top of an already-bright (0.72 mean)
  concrete texture, clipping toward white — reduced to 1.25–1.35 (tint is
  now the dominant color, texture/multiplier just add subtle variation) and
  removed an unnecessary roughness drop.
- **`_plowed` asphalt variants were glossier than the frozen originals**:
  `roughness_multiplier`/`roughness_bias` had been dropped to sell a "wet
  slushy" look, but that made the *driving surface specifically* catch more
  sky/GI highlight year-round (not just when actually wet), reading pale
  under the atmosphere haze-fix's brighter/clearer look — reverted to the
  frozen roughness. `asphalt_patched_plowed` (residential/service/alley
  surfaces — the majority of street area by way count) also got a modest
  darken + slight cool tint since its base texture is measurably warmer/
  lighter than `asphalt_road`'s.
- **Real geometry bug, `pipeline/roads/build_road_plan.py`**: pullback (the
  4–8 m curb-return trim at junction ends) was being applied to *every*
  `junction_nodes` entry, including simple degree-2 "pass-through" points
  where OSM just split a way at an interior shaping vertex with nothing
  actually crossing it — most of the ~1750 post-split junction nodes are
  this, not real corners. On short segments, 8 m off *each* end left
  near-degenerate slivers. Fixed: only real (3+-way) junctions get the full
  curb-return radius; degree-2 nodes get a small fixed 1 m pullback
  (`pullback_for_node()`). Triangle count barely moved (843k → 847k), as
  expected for a coordinate fix rather than a topology change.
- **`fillet_arc`'s elbow-sanity threshold was a fixed 40–60 m**, which is
  fine for a same-width residential 4-way but too loose for a junction
  mixing very different widths (Galena's 8.2 m half-width vs. 1st St's
  3.3 m) — a bad elbow point could still pass and balloon a sidewalk/curb
  loop into a wide, wrongly-shaped bulge. Changed to scale with the fillet's
  own chord length (`max(10.0, chord * 1.2)`) instead of a fixed value.
- Junction asphalt-fan material selection now prefers the neutral
  `asphalt_road(_plowed)` over the warmer `asphalt_patched(_plowed)` whenever
  any connecting leg is a through-class road, rather than a plain majority
  vote — a big mixed-class intersection fan rendered in the residential
  "patched" material read as a blotchy pale patch.

None of the above four fixes were confirmed (via re-capture) to be *the*
cause of the pale/missing-road look in composed frames — that turned out to
most likely be the terrain issue above — but all four are real, independently
justified correctness fixes I'd keep regardless.

## Regenerating (whenever roads/bridges/rails/heightmap data changes)

```
cd pipeline/roads && ../../.venv/bin/python build_road_plan.py
game/roads/tools/build_roads.sh
```
Both steps are idempotent and safe to re-run after terrain re-bakes its
heightmap or the data pipeline re-exports `game/data/*.json`.

## Geometry approach

`roads.json`'s 650 ways aren't split at every intersection (a minor street's
end can land on a *major* way's interior vertex, not a shared endpoint) — the
builder first splits every way at each interior `junction_nodes` hit so every
segment's endpoints are junction nodes or dead-ends (650 → 1539 drivable
segments). Each segment is resampled/smoothed (light Chaikin), then offset
into parallel curves (asphalt edge, curb outer, sidewalk inner/outer) using
per-vertex mitered normals. Each segment is pulled back from its junction
ends by a 4–8 m curb-return radius (clamped to the segment's own width/length);
at each junction, the incident segment-ends are sorted angularly and stitched
with a quadratic-bezier fillet (control point = the two edge-lines'
intersection) — this is what produces the curb-return "bulb" and keeps the
asphalt/curb/sidewalk rings watertight and non-overlapping through arbitrary
3/4-way and staggered intersections. Winding for the long straight runs was
derived analytically (documented in `build_way_surfaces`'s docstring) so
those don't need double-sided geometry; junction rings *are* double-sided
(small fraction of the budget, and I wasn't willing to bet curb visibility on
an angular-order argument I couldn't fully verify by hand).

Y comes from bilinear-sampling `heightmap_play_1m_road_conformed.r32` at
every offset vertex individually (not just the centerline), so curbs/
sidewalks follow the actual camber/cross-slope baked into that heightmap.
Asphalt sits +2.5 cm above it; curb faces skirt down −5 to −8 cm into the
terrain at their outer/bottom edges so there's no floating gap if terrain's
mesh doesn't land exactly on its own heightmap. **If terrain re-bakes its
heightmap, re-run both steps above** — nothing here caches stale heights.

Materials are 100% the shared library (`asphalt_road`/`asphalt_patched` for
through streets vs. residential/service/alleys per class, `curb_concrete`,
`sidewalk_concrete`, `gravel_ballast`, `steel_rusted`) — since every mesh
uses `use_world_uv=true` (or is triplanar), I never had to generate real UVs,
just placeholder ones.

Junction asphalt fill: the ordered boundary loop (asphalt-edge points +
fillet-arc points around the junction) is fan-triangulated from the centroid.
This assumes the loop is roughly star-convex around that centroid, which
holds for essentially every real intersection in Dixon's grid but could
misbehave at a very acute, oddly-staggered junction — I did not find one in
this network, but if a future data re-export introduces one, look for a
self-crossing fan triangle near that junction.

## Markings

Center lines only on `primary`/`secondary` (double yellow, +white lane
dividers when `lanes>=4`) and `tertiary`/`unclassified` 2-lane+ (single
dashed yellow); residential/service streets get none (matches reference
photos — small-town residential streets aren't striped). Stop bars +
continental crosswalks are built only at a curated set of downtown
Galena-Ave × named-cross-street junctions (found by tag-name matching inside
`DOWNTOWN_BOUNDS`, not hand-picked coordinates) — currently **3** junctions
(Galena & 1st/2nd/3rd). Traffic-signal masts and street-name signs are placed
at those same junctions.

## Bridges

`bridges.json`'s road-bridge entries (Galena Ave main span + approaches,
Peoria Ave, a couple of footways) get a flat deck ribbon at their
pre-computed `vertices[].y` (not heightmap-sampled — that data pipeline
already resolved deck height above the water) plus a simple steel-pipe-look
parapet on both edges (`steel_rusted`). **This is intentionally minimal** —
per the brief, the landmarks team owns the hero Galena Ave bridge structure
(the haunched-slab piers, "Lincoln Highway" sidewalk stamp, ornate lighting
from `galena_bridge.md`); they should treat my deck ribbon as the
walkable/collidable surface to build around/replace visually, not remove it
outright (removing it would drop collision + the road network's continuity).
I added two ornate downtown lamp posts at each bridge-way's endpoints as a
placeholder; landmarks should feel free to replace those with their own.

## Rails

`rails.json`'s 13 ways include several that are real OSM mainlines extending
tens of kilometers past the play area (unclipped in the export) — I clip
every rail way to a generous bounds box before processing (`clip_ways_to_bounds`
in `build_road_plan.py`); this is defensive at the *road* layer only, it
doesn't touch `game/data/rails.json` itself. Ballast is a flat
`gravel_ballast` ribbon; ties are `MultiMesh` boxes at 0.6 m spacing; rails
are two thin `steel_rusted` ribbons at the real 1.435 m gauge. Grade crossings
are found by brute-force 2D segment intersection against every drivable road
way and get a flush asphalt-patched deck panel + a crossbuck sign
(`MultiMesh`) — 56 crossbucks across the network.

## Weather / season response

- **Wet/puddles**: automatic — `asphalt_road`, `asphalt_patched`,
  `sidewalk_concrete` already have `allow_puddles=true` in the frozen shared
  library; I didn't need to touch anything.
- **Snow cover**: automatic on curb/sidewalk/gutter/gravel via the shared
  shader's `snow_mask`.
- **Plowed winter roads**: the shared asphalt materials would snow-cover
  uniformly like everything else, which doesn't read as "plowed." I added
  `asphalt_road_plowed.tres` / `asphalt_patched_plowed.tres` in my own folder
  — same frozen shader + same frozen textures, just `snow_slope_bias` pushed
  strongly negative (0.2 → −0.65 / −0.6) so the *driving surface specifically*
  resists snow accumulation while curbs/sidewalks around it still go fully
  white. That contrast is what actually sells "plowed" at a glance; I did not
  attempt true UV-space wheel-path masking (would need per-road UV, not
  world-projected) — noted as a possible follow-up.
- **Windrows**: `MultiMesh` snow-pile prop (`windrow` kind) run both sides of
  every curbed street at 1.8 m spacing, right at the curb's outer face.
  Static geometry, but `roads.gd` sets each chunk's `MM_windrow` node
  `.visible = WorldState.get_snow_cover() > 0.05`, so they're invisible
  outside winter.
- **Autumn leaf litter**: same idea — small flat leaf-cluster props in the
  gutter every 7 m, `roads.gd` shows them only when `season == AUTUMN` and
  weather isn't snow/blizzard.
- **Night lamp glow**: cheap "fake pool" per the brief (no per-instance
  `OmniLight3D`s) — the lamp-head surface material is a plain
  `StandardMaterial3D` with emission pre-enabled at 0 energy; `roads.gd`
  drives `emission_energy_multiplier` from a simple fixed-clock-hour
  day/night estimate (`_night_amount()` in `roads.gd`) rather than reading
  `night_factor` back from `RenderingServer` — `world_state.gd`'s own comment
  says that accessor is editor-only/errors at runtime, and `night_factor`
  isn't exposed through a `WorldState.get_*()` accessor the way
  snow/wetness/foliage/wind are, so I couldn't read atmosphere's real solar
  night factor safely. The clock-hour approximation is a reasonable stand-in
  for a photocell-controlled street lamp but won't track true sunset/sunrise
  drift across seasons — flag if this matters more precisely later.

## Street furniture

MultiMesh, one prop mesh per kind, cached and shared across chunks (see
`_build_prop_mesh` in `build_roads.gd`): `lamp_downtown` (ornate double-globe,
27 m spacing on downtown-named streets), `lamp_residential` (wood pole +
cobra head, 46 m spacing elsewhere), `hydrant` (130 m), `manhole` (150 m, flat
disc, essentially zero collision cost), `stopsign` (one per non-downtown
3+-way junction, on its lowest-angle approach — a simplification, not full
MUTCD-correct all-way/2-way logic), `sign_street` + `signal_mast` (curated
downtown junctions only), `bench`/`trashcan` kinds exist in the prop-mesh
builder but aren't placed anywhere yet (no clear "downtown plaza" data to
anchor a "few" of them to — left for a future pass or for whoever places
plaza/park furniture).

## Known weaknesses / not done

- No true tire-track darkening or manhole-cover normal detail beyond the
  shared shader's generic macro-variation (would need road-aligned UVs).
- No oil stains in parking lanes (didn't have a reliable way to identify
  parking-lane sub-areas from the data).
- Sidewalk control-joint scoring lines not modelled (geometry cost vs.
  payoff didn't seem worth it at this pass).
- Curb top is a flat lip, not rounded (spec says "rounded top" — this is a
  flat chamfer instead).
- Junction fan-fill assumes star-convexity around the centroid (see Geometry
  approach above) — no failures found in this dataset, but not proven robust
  in general.
- `roads.tscn` is a large **text** scene (~180 MB, mostly literal
  vertex/index arrays for ~840k triangles) because `ResourceSaver.save()`
  writes embedded `ArrayMesh` sub-resources as text when the target extension
  is `.tscn`. It loads and renders fine, but if load time ever becomes a
  problem, the fix is switching each chunk's meshes to external binary `.res`
  resources referenced by `ext_resource` rather than embedding them — I didn't
  do this since the brief asks for `roads.tscn` specifically and load time
  wasn't a demonstrated problem.
- `pois.json`'s new `barrier_lines` (retaining walls / guardrails from the
  latest data re-export) are not consumed here — plausibly relevant near the
  riverfront/bridge approaches per `dixon_vernacular.md`, but ownership felt
  more landmarks/terrain-side; flagging in case someone wants a fence/rail
  pass along them.

## Integration for other systems

- **Terrain**: roads read `heightmap_play_1m_road_conformed.r32` directly;
  if terrain changes that file's dimensions/origin (`world_origin.json`), I
  read those from there already, no hardcoded assumptions beyond the file
  layout documented in `pipeline_notes.md`.
- **Landmarks**: see Bridges above re: Galena Ave bridge — my deck+parapet is
  a placeholder to decorate/replace, not final art.
- **Buildings/vegetation**: sidewalks stop at a `parkway`-width gap from the
  curb on residential streets (2 m) and flush on curated downtown streets —
  that gap is where a grass parkway strip / street trees would go; I don't
  render the grass itself.
- **Collision**: every chunk has one `ConcavePolygonShape3D` covering
  asphalt+curb+sidewalk+bridge-deck+ballast triangles (not markings/rails/
  furniture) — thin furniture (lamp posts, signs, hydrants) has no collision,
  a player can walk through them.
