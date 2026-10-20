# Roads workstream notes

## What exists

- `pipeline/roads/common_roads.py` — geometry helpers: heightmap bilinear sampler
  (reads `game/data/heightmap_play_1m_road_conformed.r32`), polyline resample/
  smooth/offset/trim, triangle-soup mesh builder, curb-return fillet (quadratic
  bezier through the two edge-lines' intersection).
- `pipeline/roads/build_road_plan.py` — the real generator. Reads
  `game/data/{roads,bridges,rails,buildings,water,aerial_paved}.json` + the heightmap, builds the whole
  network as a triangle soup + furniture-transform lists, chunks everything
  into 200 m cells by triangle/instance centroid, writes JSON to
  `game/roads/_build/chunk_<cx>_<cz>.json` + `manifest.json`. **Not tracked
  in git** (gitignore it if not already) — regenerate, don't hand-edit.
  Run: `cd pipeline/roads && ../../.venv/bin/python build_road_plan.py`
  (prints surface areas, a triangle count and known-downtown-intersection count).
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

## Authoritative transportation layout

`pipeline/roads/transport_layout.py` now defines the visible infrastructure.
The older trimmed-ring helpers remain for furniture/marking planning and
regression coverage; they no longer emit the live road or sidewalk surfaces.

- Smoothed centerlines (two passes, 2.5 m sampling) produce connected
  carriageway polygons, clipped to the existing build bounds.
- Intersection returns are solved on that connected surface using circular
  closing, restricted to junction neighborhoods. The default radius is 4 m.
  Short approach segments no longer constrain individual sidewalk curves.
- Gutter, curb, sidewalk and parkway boundaries derive from the same asphalt
  perimeter. Curbs are 0.1524 m above asphalt, with a 0.3048 m gutter flag.
  Sidewalk and parkway surfaces share curb-top elevation. A 1.5 m grass verge
  blends the outer infrastructure edge back to the unchanged terrain.
- Downtown profiles omit the parkway and use 3.6 m sidewalks; residential
  profiles use a 2 m parkway and 1.7 m sidewalk. Profile regions are combined
  before meshing so their surfaces cannot overlap.
- Aerial paving is only a candidate source. Thin fingers are removed using
  a 3 m opening. Automatic lots use a minimum-area oriented rectangle only
  when its area is at most 1.6 times the classified footprint; ambiguous
  non-rectilinear candidates are rejected for curation. Holes under 36 m2
  are filled; larger holes survive only when supported by a regular outline
  (rectangular envelope at most 1.2 times their area). Fragments below 150 m2
  or without a 3 m-wide core are rejected. Surviving lots are clipped against
  finished infrastructure, building footprints, and water. These conservative
  rules can omit genuine narrow lots; explicit overrides provide the remedy.
- Disconnected parkway remnants under 16 m2 become sidewalk, avoiding tiny
  grass triangles at profile transitions.
- Footpaths are polygon-clipped against the same surfaces, not sampled
  centerline cells. They retain their concrete/asphalt/gravel materials.
- Constrained triangulation preserves polygon holes. Mesh cells are at most
  8 m across (triangle edges at most 8 * sqrt(2) m), limiting terrain spans.
  All boolean overlays use a shared 1 micrometre precision grid.
  Connected asphalt boundaries are simplified by at most 0.025 m before
  deriving the roadside offsets, avoiding excessive sub-visible tessellation.

The generated `game/roads/_build/transport_layout.json` contains named
surface geometries, input fingerprints, and a quality report. Invalid
polygons, unintended surface overlaps above 0.00001 m2, and incomplete
triangulation fail the build. Gutter is intentionally contained within the
asphalt footprint, but the mesh replaces that portion of asphalt rather than
stacking two faces. Rejected aerial fragments are listed in the report.
Terrain and vegetation read this same plan; stale inputs fail explicitly.

### Targeted overrides

Edit `pipeline/roads/layout_overrides.json`, not generated meshes:

- `junctions`: `node_id`, `return_radius_m` (2-20 m), optional `profile`
  (`downtown` or `residential`). River/Galena (`235322239`) uses a 6 m
  return and a continuous downtown roadside profile.
- `lots`: records with a stable `id`, a local `[x,z]` `polygon`, and optional
  `holes` rings. Explicit lots cannot overlap protected infrastructure,
  buildings, or water.
- `exclude_paving`: records with `id` and `polygon` remove false aerial
  candidates. Explicit exclusions also take precedence over explicit lots.

These controls are schematic layout controls, not surveyed roadway design.
Nearby junctions share the connected surface; complex real-world islands,
driveways and grade transitions may still need curated geometry.

Rebuild all consumers together:

```sh
bash pipeline/roads/rebuild_transportation.sh
```

This regenerates roads, terrain masks, vegetation, and finally the road bake.
Regression tests: `python -m unittest discover -s pipeline/roads -p 'test_*.py'`.
That suite includes `test_road_metrics.py`, a ratchet on the road-conformed surface. It covers
junction steps, grade change, implied K, cross slope and breaklines, checked against
`road_metrics_baseline.json` and the limits in `design_standards.json`. After changing the
heightmap or road conform, run `pipeline/roads/road_metrics.py` for the full report. Run it with
`--update-baseline` only when the numbers improve. See `docs/roadway_control_plan.md`.
Road heights come from designed vertical profiles: `pipeline/build_heightmap.py` runs
`pipeline/roads/build_profiles.py` (also runnable alone, about 3 s) and writes `game/data/profiles.json`
and `game/roads/_build/profile_report.json` (fit to ground, control conflicts, advisory class-limit
violations). Hand-set controls go in `pipeline/roads/alignment_overrides.json`; tests are
`test_profiles.py`.
After baking, `godot --headless --path game res://roads/tools/test_transportation.tscn`
checks that grass follows the graded collision and cannot spawn on asphalt.

The road baker writes both `roads.tscn` and the live world's `roads.scn`, so
rebuilding no longer leaves the world using a stale packed road scene.

## Horizontal control (alignments)

`pipeline/roads/build_alignments.py` chains roads.json's drivable ways into routes, fits each a
tangent-and-curve alignment, places junction control points, and measures widths from the 2025
aerial. It writes `game/data/alignments.json` and `game/roads/_build/alignment_report.json`.
`--overlay` draws review images into `captures/roads/alignments/`; `alignment_overlay.py X Z [half]`
draws one window. No game consumer reads alignments yet. Tests: `test_alignment.py`. See
`docs/roadway_control_plan.md`, phase 1.

## OSM corrections

Where OSM draws a street off its pavement by more than the alignment fit's tolerance, the fix goes
into the data every consumer reads: `pipeline/osm_corrections.json` moves nodes (in every way that
uses them) and replaces runs of vertices between two nodes with points traced on the 2025 aerial,
each with its note. `build_vectors.py` applies it when it writes `roads.json`; running
`pipeline/osm_corrections.py` applies it to the `roads.json` on disk (idempotent; existing heights
kept). Then rebuild alignments, templates and transportation. Tests: `pipeline/test_osm_corrections.py`.

## Build bounds

Roads and rails are built only over the 1 m play heightmap (`VALID_BOUNDS` in
`build_road_plan.py`, read from `world_origin.json`). Ways are cut exactly at its edge. Until
2026-10-18 the bounds ran 400 m past the heightmap, where `Heightmap.sample` clamps to the edge
row. 38.6 km of road there took the edge's heights, as much as 18 m under the horizon terrain.

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

## RESOLVED: "mid-block coverage gap" — real cause found, fixed

This was open for most of the session and got misdiagnosed twice before the
actual cause surfaced. For the record, in order:

1. **First hypothesis (wrong): terrain's heightmap-vs-mesh scale bug
   occluding correct road geometry.** Ruled out — terrain confirmed ±20mm
   agreement, and pushing `ROAD_Y_BIAS` to a blatant 0.5 m diagnostic value
   didn't reveal anything either.
2. **Real contributing bug #1: a stray `Transform3D` on the `Roads` node in
   the shared `world/world.tscn`** — `(-1149.8868, -77.292175, 795.5365)`
   translation, apparently saved accidentally by the buildings workstream
   (the `Buildings` node had the identical transform). This put my entire
   road network ~1.4 km away from where curbs/terrain/buildings actually
   were, in whatever real geometry happened to exist at the *offset*
   coordinates — which is exactly why some of my own test captures looked
   locally convincing (real asphalt, just the wrong asphalt) while composed
   `world.tscn` frames looked broken. **Fixed by the buildings agent**;
   verify the `Roads` node in `world/world.tscn` carries no `transform` line.
3. **Real contributing bug #2 (the actual remaining cause, mine): backface
   winding on the main asphalt ribbon.** Even after the transform was
   removed, straight-run asphalt still didn't render in composed frames —
   confirmed via `--hide=Terrain` (revealed empty sky, not occluded asphalt)
   and via an extreme bright-tint diagnostic material in both `test_roads.tscn`
   and `world.tscn`: the tint never appeared near the camera on straight
   runs, only glowing at extreme distance — while **junction fan geometry
   (always built double-sided) rendered correctly everywhere**. That contrast
   was the tell: the single-sided winding I derived early in this session for
   the straight-ribbon `edge_L`/`edge_R` pair (`build_way_surfaces`'s main
   `add_ribbon` call) was backface-culled from normal eye-height viewing
   angles across the *entire* map — curbs/sidewalks/markings use a different,
   apparently-correct flip convention, which is why only the asphalt itself
   was ever missing. **Fixed** by adding a `double_sided` option to
   `add_ribbon()` (`common_roads.py`) and using it for that one call
   (`pipeline/roads/build_road_plan.py`) rather than re-deriving the correct
   single-sided winding under time pressure — it's the single largest mesh
   in the scene so it's the most expensive double-siding in this file, but
   correctness (the road rendering at all) matters more than that margin.
   Triangle count: 847k → 902k (+6.5%).

Verified fixed in composed `world.tscn` at the coordinator's exact
verification viewpoint (`pos=[1515,14.32,-1372.4]`,
`look_at=[1796.1,14.5,-1453.8]`) — see `captures/roads/iter3/final/` (normal)
and `captures/roads/iter3/final_hideterrain/` (`--hide=Terrain`, confirms the
asphalt is self-sufficient, not terrain showing through). Measured asphalt
in that shot: **sRGB (98, 90, 83), linear ≈ 0.10** — within the 0.05-0.12
target.

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
The shallow concrete gutter pan runs continuously between the carriageway
edge and the gutter's inner edge, using the same material and slight grade as
the existing junction pan fill.

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

## Sidewalk fix (2026-09-20) — item 5 + the "crossing edges you must jump"
Two symptoms, one cause chain, both confirmed by the user:
- *Visual:* sidewalks rendered as outlines only.
- *Physical:* thin ribbons standing proud of the road that the player had to jump.

Cause: straight-run sidewalk slabs used the same wrong single-sided winding derivation already found
on the asphalt ribbon, so the **walking surface** was backface-culled, leaving only its edge skirts
(`sw_in -> sw_in` and `sw_out -> sw_out`, +0.05 down to -0.05) visible. Those skirts are tagged
`sidewalk_concrete`, which is in the baker's `WALKABLE` list, so they were also **collidable ledges**.

Fix: (a) sidewalk slabs and the curb top are now `double_sided=True`, matching the junction loops that
always rendered correctly; (b) edge skirts are emitted under a new `sidewalk_edge` material tag — same
appearance (mapped to sidewalk_concrete.tres in build_roads.gd) but deliberately **excluded from
WALKABLE**, so they can never be ledges again; (c) skirts now stop at terrain level (0.0) instead of
-0.05. Triangles 902k -> 1.26M (+40%), the cost of double-siding the walkways.

Verified with `game/tools/probe_ground.gd` across the arch crossing (1618,-1214)->(1652,-1214):
**max real step 0.180 m** (an ordinary curb, inside the player's 0.30 m step-up); the only >0.3 m hits
in the log are the player capsule itself standing on the probe line. Visually confirmed in
`world.tscn` at eye height: continuous sidewalk slabs both sides with the grass parkway between curb
and walk.

## Editing alignments and reviewing roads (Bridge Composer, 2026-10-19)

Phase 6 of [roadway_control_plan.md](roadway_control_plan.md), started early: an **Alignments** mode
in Bridge Composer (`../bridge-composer/alignments.html`, linked from the Bridges page) to set a
street's horizontal alignment the way curves are developed in practice, and a **Review** tab to
check the roads against the aerial.

**Run it.** `npm run serve` in `../bridge-composer` (composer_server.py on :8001), then open
`http://localhost:8001/alignments.html` (`?route=R21838771` opens a route). It needs
`game/data/alignments.json`, which carries each route's OSM line since 2026-10-19 (run
`pipeline/roads/build_alignments.py` once if yours is older).

**Editing a route.** Pick it in the list, or click its line on the aerial. Tangents are cyan, curves
magenta, the OSM line red, the template's curb lines green, PIs yellow dots, PC and PT triangles.
- Drag a **PI**. It holds its radius (T changes) or, with the *Drag PI* menu or the **T** key held,
  its tangent length (R = T / tan(Δ/2)); hold **R** to force the radius.
- Drag a **PC or PT** along its tangent: T becomes the distance from the PI, R = T / tan(Δ/2).
- Type **R** in the side panel (0 makes the PI an angle point).
- **Add break** (click the line where another street crosses it; it snaps to that street): the centrelines of a
  street either side of a cross street need not line up. This puts two PIs 0.5 m apart there and flags the segment
  between them as a *break* (orange): the corridor stops at the break and starts again on the far side, with no
  curb line joining them. Nothing moves yet. Slide the tangent on one side (it stays parallel) to offset it; a break
  PI dragged near the cross street's centreline snaps onto it, so both ends sit on the intersecting alignment. The
  line stays one continuous alignment (the break is a short link, flagged `"break"` in `alignments.json` and
  `"breaks": [PI index, ...]` in the pin), so profiles, templates and the road builder are unchanged. Break the two
  ends of a block to offset just that block. Remove a break by removing its two PIs.
- **Add PI** (click the dashed PI chain) and **Remove PI** (Delete). Undo is Ctrl+Z.
- The panel reads R, T, Δ, L, the PC/PT/PI stations and degree of curve, and the deviation of the
  OSM line from your alignment. Curves that need more tangent than there is are refused.
- The side panel is the sequence: **1 Adjust** (drag; drag a green curb line to set the width), **2 Why**
  (one line, optional), **3 Apply** (saves the alignment pin and/or the width pin to
  `pipeline/roads/alignment_overrides.json`; in Review it also records the place as *fixed*),
  **4 Publish** (runs `build_alignments.py`, then `rebuild_transportation.sh` and the bridge bake, about
  6 minutes; restart the game afterwards). Apply does not change the game; edit as many places as you
  like, then Publish once. The panel says when saved changes have not been published. *Unpin route*
  removes a route's pin; *Pin only a stretch* (under Apply) pins just PIs a to b, padded 0.5 m on the OSM line.
  The editor opens a route as it was last built, or as last saved if that has not been published.
- A dragged curb line sets the width of the **block between intersections** it is on (white diamonds mark the
  ends; drag them or type From/To, and they snap to intersections). Widths are per stretch, so one street can
  change width at an intersection; a later, narrower stretch overrides an earlier wider one.
- Units default to feet (stationing 3+46); the Units menu switches to metres.

**Whole-model check.** The *Whole model* card at the top of the side panel shows the aerial survey's
accuracy at the last publish and the change since the one before: blocks whose pavement centre is more than 2 m
off the alignment, the median and 90th-percentile offset, the share within 1 m, and how many hand pins exist.
`build_alignments.py` appends a snapshot (`alignment_metrics.py`) to `docs/review/alignment_metrics.json` at
every run, so a few edits followed by one Publish show whether the model improved and how many flagged places
cleared (press Load queue to drop them). Width pins do not show here: the survey measures centres, not widths.

**What a pin does.** `build_alignments.py` takes the pinned PIs and radii instead of the fit.
Everything after reads `alignments.json`, and pinned stretches are recorded in each route's
`pinned`: `templates.design_roads` follows a pinned stretch even where it is more than
`SEGMENT_MAX_DEV_M` from OSM (it used to leave such a run on the OSM line, which is why Harrison
Avenue needed a correction to OSM itself), and the ends of a pinned route at a junction stay where
the pin puts them (other routes' ends still move onto a pinned through route). A pin may cover
only a stretch (`"sta": [from, to]`, metres along the route's OSM line; in the editor tick *only PIs a to b*
before Save: the stretch is those PIs, padded 0.5 m on the OSM line, and the rest is fitted as before; the
first and last pinned PIs keep their radii so a curve joins the pinned stretch to the fitted line;
`alignment_report.json` lists `joint_kinks` where it does not). Pins are not checked against
OSM: `pinned_routes` in the alignment report lists how far each is. Station-keyed overrides of the
same route (`templates`, `profile`) are not moved when a pin changes its stations: re-check them.
`osm_corrections.json` is still the right place to fix OSM itself; the editor shows its result.

**Review.** The Review tab loads a queue: a seeded random sample of surveyed street blocks
(default 25; the same seed gives the same blocks until `alignments.json` is rebuilt) and the
flagged places the audits list (`alignment_report.json` off-centre blocks, the footprint audit's
`roofless_review.json` and `street_overlaps.json`). Each opens the view on the aerial at that spot
with a cross-hair and its route loaded: **Looks right** (ok) or **Wrong, leave it** record a verdict and
advance; fixing it and pressing Apply records *fixed*. The Why note is stored with the verdict. Verdicts go to
`docs/review/alignment_review.json` (tracked): `{id: {status, note, kind, route, sta, at,
reviewed}}`, to calibrate the aerial scorecard (paving precision) against a labelled sample later.

**Code.** `pipeline/roads/alignment_geom.py` (the construction, no numpy: `alignment.py` and the
server share it), `horizontal_overrides.py`, `game/tools/alignment_editor.py` (server side),
`../bridge-composer/js/alignment.js` (geometry port, parity fixture from
`dump_alignment_parity.py`) and `js/alignments.js`. Tests: `test_horizontal.py`,
`test_alignment_editor.py`, `test_templates.py`, and `npm test` in bridge-composer.
