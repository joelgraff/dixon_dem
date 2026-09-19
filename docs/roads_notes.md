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
