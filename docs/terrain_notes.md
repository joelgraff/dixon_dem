# Terrain workstream notes

Owns `game/terrain/` (+ `pipeline/terrain/` helper scripts). Reads only from
`game/data/` (data-pipeline output, read-only) and `game/materials/` (shared
texture library + shader includes, read-only). Builds the play-area ground
mesh + collision, the horizon ring, and the river/pond water surfaces.

## What exists

```
game/terrain/
  terrain.tscn / terrain.gd     composition root: builds chunks, water, horizon in _ready()
  test_terrain.tscn / .gd       standalone test scene (atmosphere + terrain + free-fly cam)
  terrain_height.gd             TerrainHeight -- static height/normal sampling API (see below)
  shaders/
    terrain.gdshader            play-area ground: 7-layer splat blend + snow/wetness/season
    horizon.gdshader            cheap distant-terrain shader for the 10km ring
    water.gdshader              river reaches + ponds
  materials/                    generated ShaderMaterial .tres (terrain/horizon/water) -- rebuilt every run
  textures/                     terrain_splat_a.png / terrain_splat_b.png -- baked by pipeline/terrain/bake_splat.py
  cache/                        generated chunk meshes + collision (.res), gitignore-able, auto-rebuilds
pipeline/terrain/
  bake_splat.py                 reads game/data/{landuse,rails,water}.json, writes game/terrain/textures/*.png
```

## How other systems sample terrain height

`TerrainHeight` (`res://terrain/terrain_height.gd`, `class_name TerrainHeight`) is a
plain `RefCounted` with static state -- no autoload needed, just call it:

```gdscript
var y := TerrainHeight.get_height(x, z)        # local-space Y (meters), bilinear
var n := TerrainHeight.get_normal(x, z)         # surface normal, central differences
var in_play := TerrainHeight.is_in_play_area(x, z)
```

- Reads `heightmap_play_1m_road_conformed.r32` (so placement lines up with the
  carved road camber) inside the 2700x2700 play square, falls back to the
  coarse 12.5m horizon heightmap beyond it. First call lazily loads and caches
  both grids (~30MB total) for the process lifetime.
- This is the **same data** `terrain.gd`'s chunk mesh builder reads from, so
  anything placed via `TerrainHeight.get_height()` sits exactly on the
  rendered ground -- no separate/approximate height source to drift out of
  sync.
- `game/terrain/tools`-style throwaway scripts aren't needed; buildings/roads/
  vegetation/landmarks workstreams should just `TerrainHeight.get_height(x, z)`
  (or `preload("res://terrain/terrain_height.gd")` if the global class name
  hasn't been scanned yet in a fresh headless run).

## Terrain mesh: chunking, LOD, collision

- 2700x2700m play area split into **150m chunks** (18x18 = 324), each a
  `Node3D` positioned at the chunk's world origin with **chunk-local**
  vertices baked (0..150) -- not world-absolute under an identity transform.
  This matters: Godot's `visibility_range_begin/end` measures distance from
  the *instance's own transform origin*, not its mesh AABB, so an
  identity-transform chunk with world-absolute vertices computes LOD distance
  to world `(0,0,0)` for every chunk alike (silently wrong for every chunk
  except ones near the origin). See "Known issues" below -- this bit us hard.
- Two render LODs per chunk, both reusing the one shared `terrain_material`:
  - LOD0: 2m stride (76x76 verts), visible 0-240m (fades out 240-280m).
  - LOD1: 10m stride (16x16 verts), visible from 240m out (fades in 200-240m).
  - `visibility_range_fade_mode = VISIBILITY_RANGE_FADE_SELF` cross-fades them.
  - A 5m-deep skirt ring around every chunk edge hides any crack between
    neighboring chunks at a different LOD (or future re-tessellation).
- Collision: one `HeightMapShape3D` per chunk at the brief's **1m** resolution
  (cheap -- it's just a flat float array, ~128KB/chunk, no vertex/index
  overhead), positioned to match the chunk's render geometry exactly.
- **Caching**: chunk meshes + collision are generated once in GDScript (no
  offline bake step) and saved to `game/terrain/cache/*.res`, keyed by a
  signature of the road-conformed heightmap's mtime + chunk/LOD constants.
  A data-pipeline re-export changes the mtime -> cache auto-invalidates and
  regenerates; unchanged data loads straight from cache. Cold build ~25s for
  all 324 chunks (headless, single-threaded GDScript); warm load ~1s. Delete
  `game/terrain/cache/` to force a full rebuild.

## Terrain shader (splat blend)

`terrain.gdshader` blends 7 texture sets from `materials/textures/` (reusing
`materials/shaders/includes/{noise,anti_tiling,snow,wetness}.gdshaderinc` the
same way `materials/shaders/surface.gdshader` does, but with its own
multi-layer blend since `surface.gdshader` only carries one texture set):

| layer | texture | driven by |
|---|---|---|
| lawn | `grass_lawn` | baked splat: parks/residential/cemetery/playgrounds |
| wild/dry grass | `dry_grass` | implicit fallback (1 - sum of all other weights) |
| wood | `forest_floor` | baked splat: `natural=wood`, nature reserves |
| gravel | `gravel_ballast` | baked splat: rail corridors (buffered), quarries |
| mud | `mud` | baked splat: riverbank buffer + farmland/brownfield dirt |
| paved | `asphalt_patched` | baked splat: `landuse=retail/commercial/industrial` (placeholder until roads/buildings cover it) |
| rock | `stone_rough` | **dynamic**, not baked: slope + a screen-space-derivative curvature proxy + elevation (bluffs expose rock at a lower slope threshold than riverbank cuts) |

The two splat masks (`terrain_splat_a.png` R=lawn/G=wood/B=gravel/A=mud,
`terrain_splat_b.png` R=paved/G=bare-dirt-folded-into-mud) are baked by
`pipeline/terrain/bake_splat.py` at 2m/texel (1350x1350) from
`landuse.json`/`rails.json`/`water.json` polygon and line data (shapely
buffers + a Gaussian blur for soft transitions), reading `game/data/*.json`
only -- outputs go to `game/terrain/textures/` (this workstream's own
folder), never into `game/data/`. Re-run after any data-pipeline re-export:

```
cd pipeline/terrain && ../../.venv/bin/python bake_splat.py
```

Seasonal response: a global tint (`season_foliage`) shifts grass toward
autumn yellow-brown, spring adds a wetness-gated saturated-green nudge, and
winter is mostly the shared `snow_mask()`/`apply_snow()` (deep on flat
ground, resisted on slopes, patchy noise edge so grass tufts show through
thin cover) -- consistent with every other outdoor material in the project.
`anti_tiling_enabled` defaults **off** for terrain (see Known issues).

## Horizon ring

`horizon.gdshader` + a single low-poly mesh (50m stride) sampling the
12.5m/10km horizon heightmap, with a height/slope-driven 3-way blend
(wild grass / forest / rock, no baked splat data out there) plus snow. A
30m-margin "hole" is cut where the play-area chunks already cover, so the
two meshes overlap slightly at the play-area boundary rather than leaving a
gap -- avoids relying on the two independently-resampled heightmaps
(1m road-conformed vs. 12.5m average) matching exactly to the millimeter.

## Water

`water.gdshader` on flat per-reach meshes triangulated from
`water.json["reaches"]` (`Geometry2D.triangulate_polygon`, one draw per
reach, `surface_y` from the data). Depth-based color/absorption reconstructs
the terrain-bed depth from the scene depth buffer (`hint_depth_texture` +
`INV_PROJECTION_MATRIX`/`INV_VIEW_MATRIX`) -- murky green-brown when deep,
lighter/foamier in the shallows. Flow-direction ripples use two scrolling
`value_noise` taps (direction = each reach polygon's principal axis via a 2x2
covariance/PCA, computed once in `terrain.gd`) plus a slow low-frequency
swell; rain adds a higher-frequency scroll layer when `wetness>0`. A
foam/turbulence band is placed immediately downstream of the dam (dam
position + crest direction, also PCA'd from `water.json["dams"]` vertices,
passed only to the reach whose id contains `"downstream"`). Winter: shelf ice
grows from the banks inward with `snow_cover`, reduced sharply in the dam's
turbulence band so **the channel below the dam stays open** per the brief;
snow sits on top of ice via the shared snow mask. Reflection is fresnel +
Godot's own sky/SDFGI reflection probe (low roughness) rather than a custom
SSR pass, since this workstream doesn't own the `WorldEnvironment`.

Streams (minor waterway lines in `water.json`) are not rendered as geometry
-- only reaches (river/pond polygons) and dams. Known limitation, not a
blocker: streams are thin/seasonal and are already represented in the
terrain splat as riverbank-style mud buffers.

## Performance

Measured on RX 580 8GB, 1600x900, real Vulkan renderer (not `--headless`),
vsync disabled, `res://terrain/perf_probe.tscn` (mirrors atmosphere's own
`perf_probe.tscn` pattern -- 120-frame warmup, 180-frame measurement window):

```
flock .locks/gpu.lock godot --path game --resolution 1600x900 res://terrain/perf_probe.tscn
```

- Riverfront (south bank, looking across the water toward downtown): **102.4 fps** (9.77 ms/frame)
- Bluff vista (elevated, widest terrain draw distance/chunk count in view): **105.8 fps** (9.46 ms/frame)

Both comfortably clear the 60fps/1080p-high budget with headroom for
buildings/roads/vegetation to add cost on top. Mesh build: first-run chunk
generation ~25s one-time (cached to `game/terrain/cache/` after, see above);
warm scene load ~1-1.4s.

## Known issues / lessons for future workstreams

- **Backface culling + `visibility_range` interaction bit us hard.** Chunk
  mesh triangle winding was inverted (an off-by-one in reasoning about
  Godot's CCW-from-above convention when generating a grid via
  `(row,col)` indices) -- with default `cull_mode` (CULL_BACK), the entire
  interior of every chunk was invisible, leaving only the (coincidentally
  correctly-wound) skirt ring visible. This is **very easy to misdiagnose**:
  it looked like a shader/material/atmosphere bug (uniform "sky-colored"
  gradient with only thin lines rendering) because a custom `ShaderMaterial`
  on the affected mesh renders *nothing* for backface-culled triangles, while
  Godot's own reflection/SDFGI ambient still lights the *scene*, producing a
  smooth gradient that looks exactly like "something else is wrong" rather
  than "half the triangles aren't being drawn." If a mesh renders as mostly
  background with a few edge lines: check winding with `cull_disabled`
  before suspecting materials or lighting.
- Bridge/road/building cutouts aren't punched into the terrain mesh or splat
  yet (those workstreams weren't built at authoring time) -- expect minor
  overlap once roads/buildings land; the "paved" splat category is an
  explicit low-confidence placeholder for exactly this reason.
- `nachusa_house`/other landmark-adjacent terrain hasn't been spot-checked
  against building footprints for the same reason.
- Stream lines (minor waterways) aren't rendered as water geometry (see
  above).
- Van Arnam Island / Willow Park: rendered as ordinary high-ground terrain
  (raw DEM heights outside the water cutout) with the wooded splat category
  from their `nature_reserve` landuse tag -- no special-casing needed once
  the data pipeline carried the island geometry correctly.
- **iter2 fixes (critic pass on `captures/terrain/iter1/`):** raw texture
  albedo wasn't corrected (materials/lib/*.tres apply a per-material
  `albedo_tint`/`albedo_multiplier` to land in ART_DIRECTION's linear-albedo
  ranges; terrain.gdshader now mirrors those same values -- see
  `LayerCorrection` group in the shader and `correction` dict in
  `_build_terrain_material()`); water's fresnel reflection term was a
  hardcoded bright daytime blue applied at full strength regardless of time
  of day, making it the brightest thing in frame at dusk/night -- now damped
  by the shared `night_factor` global and cut from 0.35 to 0.16 strength,
  plus a higher roughness floor (0.045->0.1) so a high noon sun doesn't blow
  the whole surface out to a flat glare; macro variation strengthened
  (0.16->0.3 strength, ~67m->~125m patch scale) and the riverbank mud splat
  buffer widened (9m/5m -> 16m/8m) since both were too subtle to read at
  normal viewing distances. The vertical "picket fence" artifact along the
  horizon in iter1 captures is **not** terrain/horizon geometry -- confirmed
  by pixel-cropping an iter1 capture: the bars sit entirely above the land/
  sky boundary, inside the sky dome's cloud layer (atmosphere's
  `sky.gdshader`), consistent with a dome-projection streaking artifact at
  grazing/near-horizon angles. Flagged to atmosphere, not fixed here.
- The dynamic slope/curvature rock-exposure term (steep banks, bluffs) also
  fires on the flattened-then-feathered edge of road-conformed corridors
  (see pipeline_notes.md "Road-conforming") since that feather creates a
  real slope discontinuity -- reads as a faint pale streak of exposed rock
  along a road's future alignment before the roads workstream covers it with
  real pavement (visible in Page Park, where "Page Drive" crosses). Toned
  down (curvature weight 0.35->0.12) but not eliminated; expect it to
  disappear once roads geometry sits on top.
- `stone_rough` has no `materials/lib/*.tres` (materials workstream never
  built one), so its albedo correction (`rock_tint`/`rock_albedo_mult` in
  both terrain.gdshader and horizon.gdshader) is this workstream's own
  conservative estimate, not a cross-checked measurement like the other six
  layers -- revisit if materials ever adds a real stone_rough material.

## iter3: splat coverage, water seam gap, and the road-occlusion investigation

**Splat fallback painted the whole map tan (fixed).** `w_wild` -- the
"no baked landuse data here" weight -- covers most of the play area (OSM
landuse polygons are sparse; ordinary yards/fields/lots mostly have no
polygon at all) and was rendered as the permanently-tan `dry_grass` texture
regardless of season. Real fixes, two parts:
1. `terrain.gd` had hardcoded a stale duplicate of materials' `dry_grass.tres`
   tint/multiplier. Replaced with `_lib_param()`, which reads the *live*
   `materials/lib/*.tres` shader parameters at build time -- terrain can no
   longer drift out of sync with a materials retune. Applied to every layer
   (lawn/wild/wood/gravel/mud/paved/snow), not just wild.
2. The actual color bug: `w_wild`'s texture set is now a `mix(grass_lawn,
   dry_grass, dryness)` blend where `dryness = smoothstep(0, 0.55,
   season_foliage)` -- green in summer/spring, transitioning to dry_grass's
   tan-brown by autumn/winter, instead of always sampling dry_grass. Same fix
   mirrored in `horizon.gdshader` (added a `lawn_albedo/lawn_normal` sampler
   pair + the same blend). This is a **texture-set swap for the fallback
   weight**, not a change to the baked splat weights themselves -- explicit
   lawn/wood/gravel/mud/paved areas are unaffected and still use their own
   baked category.

**River reading bright green (fixed).** Not a material bug -- a real
coverage gap. `river_upstream_0/1/2` (split around Van Arnam Island) and
`river_downstream` are independently-generated polygons that don't align to
sub-meter precision at their shared seams; pixel-diffing the reach-polygon
union against a low-elevation mask of the heightmap found a literal hairline
crack cutting across the channel right at the seam near downtown -- bare
terrain (with whatever splat category applies there) rendered through the
gap. Fixed in `_build_water()` by outward-offsetting every reach polygon
`WATER_SEAM_BRIDGE_M` (4m) via `Geometry2D.offset_polygon()` before
triangulating, so neighboring pieces overlap at the seam instead of leaving
a crack. Small enough not to visibly widen the river against its real banks.

**Terrain occluding the road surface -- investigated at length, root cause
is NOT terrain height.** Sampled the actual built mesh (not just
`TerrainHeightScript`) at three downtown points, comparing LOD0 (2m stride)
against the road-conformed heightmap directly:

| point (world x,z) | heightmap | LOD0 mesh | delta |
|---|---|---|---|
| (1693.9,-1221.6) | 26.987 | 27.003 | +0.016 m |
| (1690.1,-1245.4) | 27.110 | 27.090 | -0.020 m |
| (1686.4,-1249.4) | 26.679 | 26.671 | -0.008 m |

Sub-2cm, matching the coordinator's own independent measurement (18,166
points, median 0.000m, p90 12mm) almost exactly -- no row/col swap, no
Z-sign flip, no Y offset/scale on chunks. Separately sampled 4 real road
vertices straight out of `game/roads/_build/chunk_*.json` against the same
heightmap: deltas were a consistent **+0.071 to +0.093m**, matching roads'
own `ROAD_Y_BIAS` (~0.085) -- roads' own data is correctly offset *above*
raw terrain, as intended.

Given that, added `TERRAIN_RENDER_BIAS` (render-mesh-only recede, collision
unaffected) as insurance against a genuine near-tie, and tested it at 0.05m,
0.12m, and **1.0m** -- rebuilding the chunk cache fresh each time (confirmed
via the `chunks built=324` build log) and recapturing the identical shot.
Zero visible change at any value, including 1.0m. A full-meter recede that
still doesn't reveal a road surface cannot be a depth-fight; if it were
height, 1m would have made it obvious. Left at 0.12m (still under the 15cm
curb reveal from ART_DIRECTION.md) as reasonable general insurance, not as
the fix for this bug.

What actually explains the render: **coverage is location-dependent, not
uniform.** A street-level (1.7m eye height) shot at real road vertices
pulled from `roads/_build/*.json` (e.g. world (1596.5,-1399.7)) renders full
correct pavement with no grass bleed-through at all. Re-shooting the
*original* problem location (a large plaza/lot-like open area near
(1691.9,-1300), not a narrow mapped street) at proper eye level instead of
an elevated look-down angle shows grass close to the camera but correct dark
pavement visible ~200m+ away at the same location -- i.e. real pavement
geometry exists nearby and further out, just not in this specific open
area close-up. This is the same shape of bug as the water seam gap above:
a coverage hole in generated geometry for a specific area (here, a
plaza/lot rather than a narrow street corridor), not a systematic height or
depth-test problem. Recommend roads/buildings check generation coverage for
large paved lots/plazas specifically, not just linear street corridors.
`captures/terrain/iter3/downtown_street_summer_clear.png` is the corrected
street-level shot (real pavement, no grass); the plaza-area shot is not
included since it would misleadingly look like a regression when it's the
same pre-existing coverage gap, now just correctly colored instead of tan.
