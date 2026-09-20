# Buildings workstream notes

Owns `game/buildings/` (+ Python helpers in `pipeline/buildings/`). Procedurally
generates every non-landmark building in `game/data/buildings.json` (707
footprints minus 17 landmark-tagged ones) plus ~900 infill houses/garages on
residential blocks OSM left empty, bakes them into one chunked scene.

## 2026-09-19 "buildings invisible" bug -- root cause + fix

User report via the Godot editor: "buildings and roads do not align, and the
riverfront area is entirely unpopulated" -- investigation found it was worse:
**no buildings rendered from almost any camera position.** Two real, separate
bugs were involved, found by instrumenting rather than guessing:

1. **Stray transform on the `Buildings` node in `world/world.tscn`** (the
   actual root cause of total invisibility). Someone/something had saved a
   rotated + translated `transform = Transform3D(0.888, 0.110, -0.446, ...,
   -1149.9, -77.3, 795.5)` on the shared composition root's `Buildings`
   instance -- almost certainly an accidental editor-gizmo drag, since every
   other child (Atmosphere/Terrain/Vegetation/Player) has none. That shoved
   the entire building system ~1400m away and tilted it, so every diagnostic
   camera (even ones aimed straight at known chunk coordinates) saw nothing.
   A standalone load of `buildings.tscn` (bypassing `world.tscn`) looked
   completely correct in CPU-side inspection (right positions, AABBs,
   surface counts, `visible=true`) -- which is what made this easy to miss at
   first: the bug wasn't in the baked scene at all, it was in how the shared
   scene *instanced* it. **Fix: deleted that `transform` line** so `Buildings`
   sits at identity like its siblings. `Roads` still has an identical
   `-1149.8868, -77.292175, 795.5365` translation (no rotation) in the same
   file as of this writing -- not this workstream's node to edit, but very
   likely related to the reported "roads and buildings don't align" and
   worth the roads owner double-checking.
2. **A real triangle-winding bug in `common_buildings.MeshBuild`**, found
   while investigating: this module builds 3D geometry from 2D `(x, z)`
   footprint polygons using the standard shoelace formula to define "CCW".
   Embedding a flat `(x, z)` polygon into Godot's actual right-handed 3D
   space as `(x, 0, z)` is an *odd* axis permutation relative to the
   standard `(x, y, *)` -> `+Z`-normal convention the cross-product-based
   face normal assumes -- it flips handedness. A "CCW-in-(x,z)" triangle
   therefore has a real `(B-A)x(C-A)` normal pointing the *opposite* way
   from the 2D convention's intent (a flat roof cap facing down, a wall's
   outward face pointing into the building) -- with every building material
   on default `cull_back`, this would have back-face-culled the whole
   system from outside regardless of the transform bug above. Fixed by
   mirroring the submitted index order in `MeshBuild.add_quad`/
   `add_tri_face` (`(0,2,1)`/`(0,3,2)` instead of `(0,1,2)`/`(0,2,3)`) --
   same vertices/UVs/normals/colors, flipped winding. This bug was masked by
   bug #1 during the initial fix attempt (fixing only the winding produced
   no visible change, since the transform bug was still hiding everything);
   both had to be fixed together.

Also gave every chunk node a **real transform at its chunk's world-space
center** (`origin_x`/`origin_z` in the manifest, subtracted from every
vertex/hull position in `build_building_plan.py`, applied as
`mi.position`/`fi.position`/`body.position` in `build_buildings.gd`) instead
of leaving chunk nodes at identity with raw world-space vertices baked in --
better floating-point precision at this play area's scale (up to ~3000m from
origin) and just correct practice, even though it turned out not to be the
proximate cause here.

**Verification**: re-ran both of the exact repro cameras from the bug report
(`--hide=Vegetation` top-down from 160m, `--hide=Terrain,Vegetation` at eye
level) -- both now show a populated downtown block with correct facade
rhythm; also re-shot the full `captures/buildings/iter1` set into
`captures/buildings/iter2/` and confirmed the riverfront blocks are populated
(`07_riverfront_galena_bridge_area.png`). `perf_probe.tscn` from a dense
downtown vantage: **78.3 fps avg / 12.77 ms/frame** (winter/snow/dusk,
1600x900, RX 580) -- comfortably over the 60fps budget.

**Known follow-up (not yet root-caused)**: a subset of walls closest to the
camera in some shots (`captures/buildings/iter2/01_...`, `08_...`) render
much darker than neighboring buildings at the same distance/material --
plausibly dense tree-canopy shadow + low ambient at a grazing angle rather
than a lighting bug, but not confirmed; worth a follow-up pass with
`--hide=Vegetation` at the same camera to isolate tree shadow from a real
material/normal issue.

## Regenerating after either fix above

Both fixes above are already applied in the committed source; if you need to
rebuild from scratch after further changes, use the two-step pipeline below,
then re-check `world/world.tscn`'s `Buildings` node has no stray `transform`.

## Pipeline (regenerate with these two steps, in order)

1. **Python build-plan** (geometry + collision, no Godot needed):
   ```
   cd pipeline/buildings && ../../.venv/bin/python build_building_plan.py
   ```
   Reads `game/data/{buildings,roads,water,landuse,rails,world_origin}.json`.
   Writes `game/buildings/_build/manifest.json` + one `chunk_<cx>_<cz>.json`
   per populated 200m chunk (indexed triangle soups per material, near-LOD +
   far-LOD, plus per-building convex collision hulls). ~91MB, ~12s to run.

2. **Godot bake** (headless, no GPU needed — just resource construction):
   ```
   flock .locks/gpu.lock ~/AppImage/Godot_v4.6-stable_linux.x86_64 --headless \
     --path game --script res://buildings/tools/build_buildings.gd
   ```
   Reads the `_build/` JSON and writes `game/buildings/buildings.tscn`
   (~30MB): one `Node3D` with `Near/` (per-chunk merged multi-surface
   `ArrayMesh`, real facades), `Far/` (per-chunk single-material HLOD box
   mesh), and `Collision/` (one `StaticBody3D` per chunk holding one
   `ConvexPolygonShape3D` per building).

Source modules (`pipeline/buildings/`): `common_buildings.py` (indexed
triangle-soup `MeshBuild` + polygon/grid-index helpers, mirrors
`pipeline/roads/common_roads.py`'s convention), `facade.py` (wall/window/door/
awning/cornice/roof primitives), `archetypes.py` (per-archetype building
generators), `classify.py` (tag+location → archetype), `infill.py` (residential
block filling), `palette.py` (material catalog + tint weights).

## Archetypes

`classify.classify()` picks one of: `downtown_commercial`, `strip_commercial`
(same generator, plainer), `residential_house`, `institutional`, `church`,
`industrial`, `bigbox_retail`, `garage` — from OSM tags first, then whether the
footprint centroid falls in the downtown core bounding box
(`classify.DOWNTOWN_BOUNDS`, independently derived from the landmark
coordinates in `docs/pipeline_notes.md`).

- **Downtown commercial** (`archetypes.build_downtown_commercial`): walls each
  footprint edge, split into 6-8m bays (`common_buildings.split_edge_bays`).
  Each bay gets a storefront ground floor (kick plate, large display glass or
  a door with a glass transom, ~35% get a striped/solid canvas awning),
  2-3 upper floors with 1-over-1 windows + limestone sills, a projecting
  limestone cornice, a brick parapet, a recessed `roof_membrane` flat roof cap
  (triangulated via Delaunay + centroid-inside filter, `facade.flat_roof_cap`),
  and 1-4 rooftop HVAC/vent boxes.
- **Residential house** (`build_residential_house`): footprint simplified to
  its minimum-rotated-rectangle (`common_buildings.min_rotated_rect`) so
  roofs stay clean rectangles even where OSM's polygon is messy. Front wall
  picked by nearest-road direction (`SegmentIndex.nearest` over all of
  `roads.json`) so porches/doors face the street. Gable-front (50%),
  side-gable (30%), or hip (20%) roof (`facade.build_gable_roof` /
  `build_hip_roof`), stone foundation band, ~60% get a porch (deck + columns +
  steps), ~50% a brick chimney.
- **Institutional/church/industrial/bigbox** (`build_boxy_building`): flat
  roof, plainer window rhythm (sparser + no sills for industrial), churches
  get a small brick tower + pyramidal cap near one corner; bigbox gets a
  single tall storey with wide glazed bands.
- **Garage** (`build_garage`): small rectangle, flat-fronted door quad, gable
  roof.

## Infill (`infill.py`)

OSM only mapped 707 footprints across the 2.7km² play area — most residential
blocks are empty. `generate_infill()` walks every `residential`/`unclassified`
/`tertiary` road segment (skipping bridges and the downtown core), drops a
candidate house every ~17m on both sides at a randomized 6-9m setback, and
keeps it only if it doesn't overlap an existing footprint, non-residential
landuse (parks/commercial/industrial/cemetery/etc., via
`common_buildings.PolyIndex`), water/streams (5m buffer), rails (7m buffer),
or another already-placed infill lot. ~22% of houses also get a small
detached rear garage. Deterministic: every random choice is seeded from
`rng_for(...)` keyed on rounded world position or building id, so reruns are
stable. Result: 707 → 690 real buildings (17 landmarks skipped) + ~900 infill
records = **1590 buildings built**, counts by archetype printed at the end of
`build_building_plan.py`.

Ground level for every building (real and infill) is resampled from
`heightmap_play_1m_road_conformed.r32` (the same file `terrain.gd` renders
from, per `docs/terrain_notes.md`) rather than trusted from
`buildings.json`'s own `ground_y_min`, so buildings sit flush with the live
terrain mesh.

## Landmarks

Any `buildings.json` entry with a `landmark_id` (courthouse, Dixon Theatre,
Reagan home + outbuildings, Nachusa House, Dixon Arch — 17 footprints, 5
unique ids) is skipped entirely and left for the landmarks team.

## Materials / windows / weather

Reuses `game/materials/lib/*.tres` directly (brick_red, brick_buff, limestone,
stone_foundation, roof_metal, roof_membrane, shingles_dark, steel_rusted,
siding_white, siding_sage) and adds a small set of **tinted duplicates** under
`game/buildings/materials/` following materials_notes.md's documented
"duplicate the .tres, edit `albedo_tint`" pattern (`brick_rose`, `brick_dark`,
`brick_cream`, `siding_blue`, `siding_butter`, `siding_gray`,
`shingles_brown`, `trim_dark`) — all still `surface.gdshader`, so they inherit
snow/wet/grime response automatically. `palette.BRICK_KEYS`/`SIDING_KEYS` are
weighted toward the real vernacular (mostly red-brown/buff brick, mostly
white/muted-gray siding; blue/butter/sage stay rare accents) per
`docs/references/dixon_vernacular.md` and a 2026-09-19 composed-frame review
that flagged an earlier, too-even palette as reading as a random pastel
rainbow.

Three small custom shaders (own shader budget, materials/atmosphere are
frozen — nothing in `game/materials/` or `game/atmosphere/` was touched):

- **`shaders/window_lit.gdshader`** (`materials/window_lit.tres`) — one
  material for every window in the scene. Per-window variation rides entirely
  on baked vertex color (no per-instance materials): `COLOR.r` = lit flag
  (~30-40% of upper-floor windows, ~45% of storefronts, randomized per
  window), `COLOR.g` = warmth (2700-3500K blend), `COLOR.b` = curtain/blind
  style (open/sheer/blinds, visible as a faint daytime tint + a night dimming
  factor), `COLOR.a` = storefront flag (brighter glow). Day look is the same
  cheap procedural approach as `materials/glass.gdshader` (frost in winter,
  rain streaks in wet weather) since a true interior-mapping parallax shader
  was out of scope this pass — see Known weaknesses.
- **`shaders/building_far.gdshader`** (`materials/building_far.tres`) — the
  HLOD far-mesh material: flat-shaded, vertex-color tinted (baked from
  `palette.APPROX_COLOR` of the building's real material), a cheap snow cap
  on upward faces, and a faint warm night tint so far silhouettes aren't dead
  black.
- **`shaders/awning.gdshader`** (`materials/awning.tres`) — cheap
  vertex-colored canvas (solid or striped), also snow/wet reactive.

## Chunking / LOD / collision (performance)

200m chunks (matches `pipeline/roads`' convention). Per chunk: one merged
multi-surface `ArrayMesh` for the near LOD (one surface per material actually
used in that chunk, ~8-12 typically) and one single-material merged mesh for
the far LOD box. `visibility_range` crossfades near→far at **640-700m**
(`GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF`, 60m fade margins) — pushed
out from an initial 340-380m after the 2026-09-19 composed-frame review found
real streets read as flat HLOD boxes at 200-400m; the near mesh is cheap
enough (whole town is ~300k triangles across ~1550 chunk-material surfaces)
that this costs little. Far mesh extends to 2600m so the skyline still reads
from the north-bluff vista. Collision is one `ConvexPolygonShape3D` per
building (convex hull of the real footprint, or of the simplified rectangle
for houses/garages), grouped under one `StaticBody3D` per chunk — 1590 shapes
total.

## Scenes

- `game/buildings/buildings.tscn` — generated, don't hand-edit (rerun the
  bake instead). Instanced in `res://world/world.tscn` (shared composition
  root — added as a 4th child alongside the existing Atmosphere/Terrain,
  minimal diff) and in `game/buildings/test_buildings.tscn` (Atmosphere +
  Terrain + Buildings only, for isolated review).
- `game/buildings/perf_probe.tscn` — loads real `world/world.tscn` from a
  dense downtown vantage (North Galena Ave looking south into the core) and
  prints avg FPS over 180 frames after 120 warmup:
  ```
  flock .locks/gpu.lock ~/AppImage/Godot_v4.6-stable_linux.x86_64 --path game \
    --resolution 1600x900 res://buildings/perf_probe.tscn -- --season=winter --weather=snow --hour=21
  ```

## Captures

`captures/buildings/iter1/` — six shots at 1.7m eye height (real
`TerrainHeight`-consistent ground + 1.7m, computed via the same
road-conformed heightmap in Python): W 1st St downtown (summer/clear/noon),
North Galena Ave looking south into downtown (autumn/overcast), S Hennepin
residential near (1723,-590) (winter/snow), a residential street north of the
river near (1450,-2000) (spring/rain), an elevated north-bluff vista near
(900,-2600) looking south over downtown (summer/clear), and W 1st St again at
night (summer/clear/21:30) to show `night_factor` lit windows.

## Known weaknesses (for the critic)

- **Window depth is faked**: no true recess/reveal geometry — glass + a
  slightly-proud frame quad sit just in front of the flat wall backdrop
  (a common cheap trick) rather than a real punched opening. Reads fine at
  the target low/mid-poly quality but is visibly flat in an extreme close-up.
- **`window_lit` has no interior-mapping parallax** — day windows are hazy
  reflective glass (same technique as `materials/glass.gdshader`), not a fake
  room. Acceptable per the brief's explicit "dark glass + curtain/blind
  variation" fallback option.
- **Large real OSM footprints (school/hospital/Walmart/industrial complexes,
  up to ~240m across, 9-49 vertices)** get walled/roofed edge-by-edge as-is;
  they read correctly as sprawling single masses but haven't been visually
  spot-checked as closely as the downtown/residential archetypes — flag if a
  critic spots a bad triangulation on one of these (`facade.flat_roof_cap`'s
  Delaunay+centroid-inside filter is a constrained-triangulation
  approximation, not a robust general polygon triangulator).
- **No true party-wall detection** — every footprint edge gets its own wall,
  including edges shared with a touching neighbor footprint; invisible in
  practice (the neighbor occludes it) but is wasted geometry.
- **Hip roofs** use a standard-construction 2-trapezoid + 2-triangle
  derivation that hasn't been visually stress-tested across every aspect
  ratio; gable roofs (80% of pitched roofs) got the bulk of visual QA.
- **`buildings.tscn` is a large text `.tscn`** (~30MB, embedded mesh arrays)
  per the brief's explicit filename; fine to load (one-time scene parse) but
  not diff-friendly if hand-inspected.
- Sky/cloud-dome horizon artifact (bright magenta/orange streak at the
  horizon in some captures) reproduces identically in `terrain`-only test
  scenes with zero buildings geometry — confirmed pre-existing in the
  atmosphere sky shader, not a buildings-workstream issue; a haze/fog retune
  was reported landing separately.

## 2026-09-20 orchestrator pass — winding/normals fixed, but the black walls are a MATERIAL bug
Two mesh-level correctness fixes were made (both kept, both verified harmless):
1. `common_buildings.MeshBuild._orient()` — vertical faces are now oriented by geometry (normal must
   point away from the building centroid, set per building via `set_outward_ref`) instead of relying on
   a blanket index mirror. The mirror is correct for horizontal caps but not for walls, whose submitted
   order depends on the footprint ring direction — the "missing sides / awnings over nothing" class.
2. `_outward_normal()` — a caller-supplied shading normal (walls pass one from
   `facade.wall_backdrop`, derived from the edge direction) is flipped if it points into the building.
   Winding alone cannot fix shading, because lighting uses the stored normal.

**Measured result: no visible change.** Facade band mean sRGB before -> after: first_st 106.6 -> 106.6,
downtown_block 170.3 -> 170.2, residential_house 121.2 -> 121.5. So the normals were already outward and
these were latent-correctness fixes, not the cause of the dark facades.

**Actual cause of the near-black walls, found by tallying triangles per material across all chunks:**
| material | tris | share |
|---|---|---|
| trim_dark | 81,226 | 27.2% |
| window_lit | 73,392 | 24.6% |
| limestone | 48,000 | 16.1% |
| siding_white | 38,950 | 13.1% |
| stone_foundation | 12,240 | 4.1% |
| brick_red | 11,280 | 3.8% |
| **all brick combined** | ~17,300 | **~5.8%** |

Over half of all building surface area is `trim_dark` + `window_lit`. The facade generator is covering
the bulk of each wall with dark trim and window/glass material instead of brick or siding — which is
exactly why downtown blocks read as black slabs and the residential house reads as a glass curtain wall.
**Next step:** fix the facade area budget so brick/siding dominates (a real commercial block is ~60-75%
masonry, ~20-30% glazing, the rest trim), and check the window-band UV/scale that lets glazing span whole
walls. This is a facade-composition bug, not a winding, normal, lighting or material-library bug.
