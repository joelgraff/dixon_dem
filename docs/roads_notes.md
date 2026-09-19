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

## Material fixes (confirmed, measured) — iter2

Three issues were reported against iter1/terrain's own captures, with
measured evidence. All three material/shader-facing ones are fixed and
verified by direct pixel measurement; the coverage gap is real but not
fully root-caused (see next section).

1. **Asphalt too light/warm.** Root cause: this render pipeline (AgX
   tonemap + fairly high ambient/SDFGI bounce, both frozen/atmosphere-owned)
   amplifies a "physically reasonable" material albedo far beyond what a
   naive texture-mean × multiplier calculation predicts — my original
   `asphalt_road_plowed` (`albedo_multiplier=0.72`) measured **sRGB
   (158,155,150), linear≈0.32-0.34** in a close-up shot, ~3x the 0.05-0.12
   target despite the underlying calc looking fine on paper. Fixed
   empirically (capture → measure → adjust, twice) down to
   `albedo_multiplier=0.17`: now measures **sRGB (95-97, 92-94, 88-90),
   linear≈0.10-0.12** — solidly in target range, neutral-to-slightly-warm
   grey (see `captures/roads/iter2/downtown_street_summer_clear.png`).
   `asphalt_patched_plowed` dropped proportionally (0.95→0.2) plus a slight
   cool tint, same logic.
2. **Roughness too low (mirror-like at grazing angles).** Confirmed via
   `--hide=Terrain`: the bare road surface showed a near-mirror sky
   reflection (SSR is enabled globally by atmosphere for wet-road specular,
   and even the base ~0.77 roughness texture wasn't enough to suppress it at
   grazing viewing angles). Fixed with `roughness_bias=0.5` (clamps effective
   roughness to 1.0, fully matte) on both `_plowed` variants. Confirmed via
   the `hide_terrain_control` capture: dry asphalt is now correctly matte
   with no sky sheen, and `downtown_street_rain_wet.png` shows the sheen
   correctly localized to the puddle mask only, not smeared across the whole
   wet surface.
3. **Coverage gap on large/mid-block paved areas — CONFIRMED REAL,
   ROOT CAUSE NOT FULLY IDENTIFIED.** See next section; this is the one
   item still open.

## Open issue: mid-block coverage gap (terrain shows through)

This is real and reproducible, but after an unusually thorough investigation
I could not pin down the mechanism in the time available. What's confirmed:

- **Not a depth/z-fight issue.** Raised `ROAD_Y_BIAS` from 0.025 → 0.085 →
  (diagnostically) 0.5 m. Even a blatant half-metre offset did not reveal
  the road at a confirmed-gap test point — ruling out z-fighting/depth
  precision entirely. Reverted to 0.085 (a still-reasonable, modest-safety-
  margin value; no evidence it needs to be higher).
- **Not terrain occlusion.** Capturing the exact same gap point with
  `--hide=Terrain` shows *empty sky*, not my asphalt — if terrain were simply
  rendering on top of a correctly-covered road, hiding terrain would reveal
  the road. It doesn't. (An earlier hypothesis in this doc, that terrain's
  own "heightmap-vs-mesh scale" bug was occluding correct road geometry, is
  **wrong** — terrain's team independently confirmed mesh-vs-heightmap
  agreement within ±20mm, and this test confirms it from the roads side too.)
- **The mesh data itself is verified correct and present**, checked two
  independent ways: (a) a Python point-in-triangle test against the baked
  chunk JSON found a real `asphalt_road_plowed` triangle containing the exact
  gap-point coordinates `(1594.97, -1338.5)` (mid-block on South Galena
  Ave, way `116908690`) with Y matching the heightmap; (b) a one-off runtime
  GDScript (loaded `res://roads/roads.tscn`, walked to
  `Chunk_7_-7/Surf_asphalt_road_plowed`, read `mesh.surface_get_arrays()`
  directly) confirmed the *actual loaded Godot ArrayMesh* has a vertex only
  8.3 m from that same point, well within the road's 8.2 m half-width, with
  786 vertices in that chunk's surface and a sane XZ bounding box. So the
  data reaches Godot intact.
- Despite both of those, the composed (and `--hide=Terrain`) render at that
  exact camera position shows no road geometry — the same node/mesh renders
  correctly in some views (e.g. standing at a junction, or aimed at nearby
  geometry) and not in others (aimed at this confirmed-present mid-block
  point). I do not have an explanation that survives all of the above
  evidence — candidates I could not test further without in-editor frame-
  debugger access: an incorrect auto-computed AABB on this specific
  MeshInstance3D causing frustum-culling to reject it from some camera
  angles despite `visibility_range` being generous (0-900m), or something
  about how `capture_main.gd`'s single shared `Camera3D` interacts with a
  chunk this size at this world-coordinate range.
- **This affects real screen area** in composed shots — visible in
  `captures/roads/iter2/downtown_street_summer_clear.png` and
  `residential_street_summer_clear.png`: the ~15-20 m immediately around the
  camera/junction renders correctly (dark, cracked, matte asphalt per the
  fixes above), but the mid-distance road surface is terrain grass/dirt, not
  mine. Whoever picks this up next: start from the two verification methods
  above (they're fast — a few seconds each) rather than re-deriving them;
  the `game/roads/tools/diag_check.gd`-style runtime mesh inspection (not
  currently checked in — recreate from the description above, it's ~35
  lines) is the more authoritative of the two since it checks what Godot
  actually loaded, not just what Python wrote to JSON.

One more, separate, rendering oddity noticed while investigating: the
`galena_bridge_deck` capture shows the camera as if submerged (murky green,
blurred) even positioned 3.5 m above the bridge deck's actual Y (11.04, from
`bridges.json`, well above the ~5.9 river pool level) — points at the water
system rendering some effect (a tall fog/volume, not just a thin pool plane)
reaching higher than the nominal water surface near the bridge. Not a
roads-owned file; flagging for the water/terrain owner.

## Other fixes made this session (real geometry bugs, independently justified)

- **`pipeline/roads/build_road_plan.py` pullback bug**: pullback (the 4-8 m
  curb-return trim at junction ends) was being applied to *every*
  `junction_nodes` entry, including simple degree-2 "pass-through" points
  where OSM just split a way at an interior shaping vertex with nothing
  actually crossing it — most of the ~1750 post-split junction nodes are
  this, not real corners. On short segments, 8 m off *each* end left
  near-degenerate slivers. Fixed: only real (3+-way) junctions get the full
  curb-return radius; degree-2 nodes get a small fixed 1 m pullback
  (`pullback_for_node()`).
- **`fillet_arc`'s elbow-sanity threshold was a fixed 40-60 m**, too loose
  for a junction mixing very different widths (Galena's 8.2 m half-width vs.
  1st St's 3.3 m) — a bad elbow point could pass and balloon a sidewalk/curb
  loop into a wide, wrongly-shaped bulge. Changed to scale with the fillet's
  own chord length (`max(10.0, chord * 1.2)`).
- Junction asphalt-fan material selection now prefers the neutral
  `asphalt_road(_plowed)` over the warmer `asphalt_patched(_plowed)` whenever
  any connecting leg is a through-class road, rather than a plain majority
  vote.

Triangle count barely moved across all of the above (843k → 847k), as
expected for coordinate/material fixes rather than topology changes.

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

### Orchestrator addendum to the coverage-gap investigation (do not re-litigate cheaply)
Ruled out so far, each with evidence: depth/z-fighting (ROAD_Y_BIAS raised to a diagnostic 0.5 m,
no change), terrain occlusion (`--hide=Terrain` shows sky, not asphalt), missing geometry (point-in-triangle
against baked JSON + runtime `surface_get_arrays()` both find real vertices at the point), and — added here —
**frustum culling via bad AABBs**: scanning every `"aabb"` in `roads/roads.tscn` finds **7 surfaces whose
bounding boxes contain the gap point (1594.97, -1338.5)**, with sane Y ranges. Chunk nodes carry no transform
(vertices are world-space) and there is no `visibility_parent`; all instances use
`visibility_range_end` 480/900 with no `begin`, so near-range culling is not it either.
Remaining untested hypotheses for whoever picks this up: (a) the "gap" may not be a road gap at all but
terrain's own paved/bare splat class rendering in a mid-block area, i.e. a terrain-splat question, not a roads
one; (b) `visibility_range_fade_mode = 1` (FADE_SELF) interacting badly with the opaque custom
`surface.gdshader` (fade writes instance alpha, which a shader that forces ALPHA may mishandle);
(c) an in-editor frame-debugger session, which no agent had access to.
**Status: parked deliberately** — visible impact is one mid-ground patch of wrong-coloured ground, not a
broken street, and it has already consumed two agents plus an orchestrator investigation.
