# Vegetation workstream notes

Owns `game/vegetation/` (+ Python helpers in `pipeline/vegetation/`). Procedurally
generates every tree/shrub/grass blade in the game — no imported models, no
baked Image/ImageTexture assets (see "Known limitations" for why that matters).

## Pipeline (regenerate after any data-pipeline or buildings/roads re-export)

```
bash pipeline/roads/rebuild_transportation.sh
```

Reads `game/data/{landuse,trees,roads,buildings,water,rails,world_origin}.json`
+ the road-conformed heightmap and the authoritative
`game/roads/_build/transport_layout.json` (missing/stale plans fail), **and**
(read-only, cross-workstream)
`game/buildings/_build/chunk_*.json` for the buildings team's baked collision
hulls — these include the ~900 procedurally-infilled houses/garages that
`game/data/buildings.json` doesn't have (only the original 707 OSM
footprints), so yard-tree/foundation-shrub placement and the general
building exclusion buffer see the *real* as-built town, not just the OSM
subset. Falls back to `buildings.json` alone if the bake hasn't run yet.
Writes into `game/vegetation/data/` (this workstream's own folder, never
`game/data/`): `trees.json`, `shrubs.json`, `grass_mask.png` + `.json`.
Deterministic (`SEED = 20260917`), ~10s to run.

**Important gotcha fixed early on**: every `game/data/*.json` layer is
Overpass-fetched with only a 500m *bbox* margin, but a way/relation that
touches that box comes back with its **full, unclipped** real-world geometry
— `rails.json` contains a mainline way ~66km long, `roads.json` spans x down
to -10756. Left unclipped, line-walk placement (street trees, rail-side
shrubs) scattered vegetation far outside the play square. Fixed by clipping
every line/point layer to the play area (+20m margin) before placing
anything (`PLAY_BOX`/`clip_line_parts`/`clip_poly_parts` in
`place_vegetation.py`) — the same class of bug as roads' own `rails.json`
clipping (`clip_ways_to_bounds`), hit independently here.

**Second gotcha**: OSM tags almost none of Dixon's actual residential fabric
as `landuse=residential` (2 tiny polygons in the whole dataset) — real yards
simply have no polygon. The grass mask does **not** build up from landuse
polygons; it starts as grass *everywhere* in the play area and subtracts
roads/buildings/water/rails/downtown-commercial-pavement/dense-wood-floor,
then re-adds the parkway ribbon the road-ROW subtraction removes. Building
it the "additive" way first (paint only tagged polygons) left almost the
entire town black — see the fix's comment block in `place_vegetation.py`.

Transportation exclusions now include the authoritative asphalt, curb,
sidewalk, lots and paths. Parkway/verge grass is re-added from those exact
polygons, not independently offset centerlines. Painting preserves the
underlying mask inside polygon holes, so a connected road perimeter does
not erase grass throughout its enclosed blocks. Runtime grass stamps
recheck their jittered position before placement to avoid spilling onto
pavement. A short downward ray uses graded parkway/verge collision for their
raised ground height and rejects transportation pavement hits, so coarse
mask texels cannot put blades across the actual pavement boundary. Grass
collision is separate from hard-surface collision, with explicit surface
metadata rather than relying on renderer/physics triangle ordering.
Residential street-tree candidates must fall inside the authoritative
parkway; a downtown override no longer leaves residential trees on its sidewalk.

## Placement rules (what goes where)

- **Street trees**: walked along `residential`/`tertiary`/`secondary`/
  `unclassified` road centerlines, offset into the parkway strip using the
  *same* geometry constants roads uses (`CURB_WIDTH=0.12`,
  `PARKWAY_GAP=2.0`, `SIDEWALK_W_RESIDENTIAL=1.7`,
  `SIDEWALK_W_DOWNTOWN=3.6`, `DOWNTOWN_BOUNDS`/`DOWNTOWN_STREET_WORDS`
  copied from `pipeline/roads/build_road_plan.py` so the two workstreams'
  independently-reconstructed ROW geometry lines up) — ~12.5m spacing,
  gaps within 7.5m of a junction node, American elm/hackberry/honey locust
  mix. Downtown-flagged segments get sparse (~30% keep, 22m spacing) small
  honey locust/hackberry instead, per "mostly treeless except planters."
- **Yard trees + foundation shrubs**: one per qualifying building (area
  ≤550m², centroid outside commercial/retail/industrial landuse) from the
  baked hull set described above; 0-3 trees biased by distance from the
  courthouse (a proxy for "older, more established neighborhood" absent any
  real platting-date data — documented limitation, not a real historic-GIS
  lookup); ~60% of houses get foundation shrubs (arborvitae or
  `shrub_foundation`) hugging the street-facing wall.
- **Park/cemetery trees**: Poisson-ish rejection scatter inside every
  `leisure=park/nature_reserve/recreation_ground` and `landuse=cemetery`
  polygon (Page Park included by name via this generic rule — no special
  case needed), denser for `nature_reserve` (Van Arnam Island, Willow Park).
  `leisure=pitch` gets a sparse edge-only ring, field stays open. Courthouse
  lawn + Lincoln statue get small hand-anchored accent clusters
  (`LANDMARK_ACCENTS`) since neither has a landuse polygon covering it.
- **Wood/riparian**: dense scatter (5.5m spacing) inside every
  `natural=wood` polygon, riparian species mix (cottonwood/silver maple/
  willow/elm) within 35m of a water polygon, general mix otherwise, ~18%
  `shrub_wild` understory.
- **Wetland/grassland, riverbank ring, cattails**: `natural=grassland`/
  `wetland` get sparse willow/shrub_wild; a 10m ring outward from every
  water polygon is marked tall/unmown and gets dense cattail clumps.
- **Rail-side weeds**: `shrub_wild` scatter 3-8m off every rail centerline.
- **OSM `trees.json`** (13 real points): kept as-is, species inferred from
  context if untagged (all were).

Global exclusion (`hard_excl`): buildings (0.8m buffer) + full road ROW +
water (+0.5m) + streams (+2m) + rails (+2.5m), unioned once and tested with
a `shapely.prepared` geometry for speed. Street-tree/downtown-planter
candidates are exempted from the road-ROW part of this test (they're
*supposed* to sit inside the ROW's parkway sub-strip) but still checked
against buildings/water.

## Godot side

- `tree_builder.gd` (`class_name VegTreeBuilder`) — procedural mesh
  generation, all in `_ready()`-time GDScript (no offline bake step; ~1-2s
  total for every species/variation combo, under BUILDER_PROTOCOL's "runtime
  generation OK if fast and cached" allowance). Two-level branch recursion
  (trunk → primary limbs → secondary twigs → leaf clusters) via tapered
  cylinders (`_add_cyl`, proper mesh-UV0 V=height/U=angle for
  `materials/lib/bark.tres`), leaf canopy built from crossed-double-quad
  "cards" (`_add_card`/`_add_leaf_cluster`) clumped around branch tips —
  keeps real branch structure visible for the winter bare-silhouette
  requirement while staying at ~150-300 tris/tree. Five deciduous shape
  families (round_broad, oval_tall, spreading_open, vase_elm,
  weeping_willow) + two conifer families (whorled-branch central-leader,
  pine vs. narrow spruce) + shrub/hedge + a dedicated cattail-clump builder
  + a cross-card billboard impostor for far LOD.
- `shaders/foliage.gdshader` — shared by every tree/shrub/hedge surface.
  Per-vertex baked `COLOR` = summer color + cluster AO, `CUSTOM0` = autumn
  color + wind weight (baked once at mesh-build time so near-LOD keeps exact
  per-species color identity while still sharing meshes across every
  instance of that species/variation via MultiMesh). Season blend is a
  piecewise 4-keyframe function matching `WorldState`'s actual
  `season_foliage` targets exactly (0 summer / 0.25 spring / 0.75 autumn /
  1.0 winter — pulled from `world_state.gd`, not guessed): spring is a paler
  yellow-green at reduced canopy density (partial leaf-out), autumn
  cross-fades to the baked per-species autumn color, winter fades canopy
  alpha to 0 (leaving the twig/bark surface as the bare silhouette) with
  snow accumulating on both the residual leaf mask and the twigs via
  `snow.gdshaderinc`. Wind sway is a per-vertex sine offset seeded from
  world-space position (so instances desync) and weighted by the baked
  wind-weight (branch tips sway more than trunk-adjacent cards), scaled by
  the `wind_strength` global. No baked alpha texture — leaf-cluster
  silhouette is analytic (`fbm`-warped radial falloff in `leaf_mask()`),
  deliberately avoiding the runtime-`ImageTexture` pitfall
  `docs/atmosphere_notes.md` already hit ("went invisible for reasons not
  fully diagnosed").
- `shaders/grass.gdshader` — near-camera blade cards, same wind/season
  pattern, geometric tip taper (no alpha cutout needed), dormant tan blend
  through autumn→winter, buried under `snow_cover` (short mown grass buries
  faster than tall/unmown).
- `vegetation.gd` — loads `trees.json`/`shrubs.json`, builds the mesh cache
  (one `ArrayMesh` per species×variation, 3 variations/species), chunks
  instances into `MultiMeshInstance3D` nodes: **near LOD** (120m chunks,
  real branch mesh, `visibility_range` 0-115m, 20m fade), **far LOD** (300m
  chunks, billboard impostor grouped by deciduous/conifer form only — color
  fidelity matters less at range, so this tier doesn't need per-species
  meshes — 95-850m, both fades overlapping 90-115m for a soft crossfade),
  **shrubs** (120m chunks, 0-55m, no far tier — too small to matter at
  range). Materials built once: a duplicate of `materials/lib/bark.tres`
  (grime disabled — MultiMesh shares one material across instances at very
  different elevations, and grime's `ground_level` is a single scalar; see
  materials_notes.md's own documented limitation for exactly this
  situation) plus one shared `ShaderMaterial` each for foliage/grass.
- `grass_spawner.gd` — runtime-only, not part of the static placement plan.
  Loads the imported `grass_mask.png` as a `Texture2D` (export-safe) and reads
  its image plus `grass_mask.json` (R=mown density, G=tall/unmown density), and
  `TerrainHeight.get_height()` (`res://terrain/terrain_height.gd`, per
  `docs/terrain_notes.md` — no separate height source to drift out of sync
  with the rendered ground). Cell-based cache (10m cells, 42m radius around
  the active camera, rebuilt every 0.35s): missing cells in range get a
  `MultiMeshInstance3D` stamp of a shared blade-clump mesh at jittered
  positions, cells that fall out of range are freed. Skips cells below a
  density threshold (pavement/water/buildings/wood read as 0 in the mask).

## Species

Deciduous: bur oak, white oak, silver maple, sugar maple, honey locust,
cottonwood, American elm, hackberry, willow. Conifers: white pine, blue
spruce. Evergreen hedge: arborvitae. Shrubs: `shrub_foundation` (rounded,
near houses), `shrub_wild` (scruffier, wood-edge/rail-side), cattail
(riverbank ring). 3 procedural variations per species per BUILDER_PROTOCOL's
"3-4 variations."

## Known limitations (for the critic)

- **Foliage/grass linear-albedo values needed a large empirical correction**
  (roughly 2.5-3x darker than a naive hex-picker guess off
  `dixon_vernacular.md`'s palette table) to read as natural saturated green
  rather than pale/washed under this pipeline's AgX tonemap + SDFGI bounce —
  the same lesson roads (`asphalt_road_plowed`: 0.72→0.17) and terrain
  independently documented for their own materials. Tuned by
  capture→look→adjust against `captures/vegetation/iter1/`, not measured
  pixel-by-pixel the way roads did (see roads_notes.md's `Pillow` mean
  technique) — a future pass could cross-check the same way if a critic
  wants tighter numbers.
- Tree instances use the placement plan's `canopy_r_m` for horizontal scale
  and `height_m` for vertical scale; street/downtown trees retain the
  existing 0.6 size factor. This allows crown width to vary independently of
  height. The procedural near meshes' crown envelope is approximate, so
  inspect eye-level captures for LOD silhouette changes.
- **Season-transition color path is a 4-keyframe piecewise function** tuned
  for the four *static* keyframe looks (matching every capture in this
  brief), not for what a live multi-second transition passes through
  mid-tween — e.g. a summer→autumn transition numerically crosses the
  spring keyframe's pale-green territory partway through, which is visually
  slightly wrong for that one live-transition case (never happens in a
  static capture). Documented in `foliage.gdshader`'s own comment; not worth
  a more complex time-of-year-aware ramp given the WorldState contract only
  exposes the single `season_foliage` scalar.
- **Canopy "mature old neighborhood" sizing uses distance-from-courthouse as
  an age proxy** (no real historic-platting data exists in the pipeline) —
  reasonable for a town that grew outward from its river-bend downtown, but
  not verified against any actual old-plat map.
- **Cattails are grass-blade clumps, not a distinct brown seed-head asset** —
  simplified to keep the shrub pipeline from needing a third baked-color
  channel; reads as extra-tall reedy grass rather than a true cattail
  silhouette at close range.
- **`ground_level` grime on the shared bark material is disabled entirely**
  (see above) rather than solved per-instance — an acceptable trade named in
  materials_notes.md's own known-weaknesses list for exactly this situation
  (many instances, wildly different elevations, one shared material).
- Streams (minor waterway lines) don't get their own riparian tree bias
  beyond the generic "within 35m of a water polygon" test, since
  `water.json`'s stream lines are thin/seasonal per terrain_notes.md's own
  treatment of them.
- Grass mask resolution is 2m/px (1350x1350) — fine for cell-level
  density/type lookups, not for a crisp lawn/sidewalk edge; the parkway
  ribbon in particular is only ~2m wide so it can alias at that resolution
  (visible as a slightly patchy parkway strip in the mask PNG, not
  especially visible in-game since grass_spawner samples it at 10m cell
  granularity anyway).

## Performance / captures

`game/vegetation/perf_probe.tscn` (same pattern as buildings/roads/terrain's
own probes — 120-frame warmup, 180-frame measurement, real Vulkan renderer):
```
flock .locks/gpu.lock godot --path game --resolution 1600x900 \
  res://vegetation/perf_probe.tscn -- --season=summer --weather=clear --hour=12
```
Viewpoint: S Hennepin Ave mature residential canopy (dense near-LOD trees +
foundation shrubs + near-camera grass all in view at once — this
workstream's worst case). **See final report for the measured number.**

Captures: `captures/vegetation/iter1/` and `captures/vegetation/iter2/` — all
in the composed `res://world/world.tscn` (atmosphere + terrain + buildings +
roads + vegetation + player) at 1.7m eye height per BUILDER_PROTOCOL:
`residential_street` (S Hennepin, summer/winter/autumn), `page_park`
(summer), `riverbank` (near Van Arnam Island, summer), `downtown` (looking
toward the courthouse/Galena Ave core, summer), and `vista_oblique` (~490m
NE of the courthouse, summer/winter/autumn) — coordinates found by sampling
the real heightmap/landuse/water/trees data in Python rather than guessed
(camera vantage points are specifically checked for clearance from the
nearest placed tree instance — iter1 put three of the five cameras inside a
canopy, see iter2 below).

## iter2: composed-frame critique fixes

An independent review of `captures/vegetation/iter1/` (in the real composed
world, not an isolated test scene) found five real problems, all fixed and
re-captured to `captures/vegetation/iter2/`:

1. **Canopy read as flat-shaded low-poly blobs, no sky holes, no branch
   structure through the leaves.** `foliage.gdshader`'s `leaf_mask()` was a
   single UV-space distance falloff — solid through most of each card's
   interior. Added a second, **world-space** (not UV-space, so it doesn't
   repeat identically on every card) hole-punch noise layer that multiplies
   into the mask, so the canopy is broken up with visible gaps letting sky
   and the branch skeleton show through, closer to the brief's "clumped
   foliage cards, not lollipops."
2. **Street trees far too large/dense, forming a hedge wall that hid the
   houses and even the street itself.** Root cause: street-tree instances
   were generated from the *same* per-species height table as yard/park
   trees (mature 13-22m), when real parkway street trees run smaller
   (~8-18m). Fixed in `vegetation.gd` (`_place_trees`), not the Python
   pipeline: instances tagged `category == "street"/"downtown"` get their
   `height_m` compressed to `clamp(height*0.6, 7, 15)` before building the
   transform (yard/park trees keep the brief's full "mature old
   neighborhood" range), plus an extra ~15% deterministic thinning for more
   driveway-scale gaps. The residential-street camera was also repositioned
   onto the real road centerline (pulled from `roads.json`, not guessed) so
   the shot actually frames pavement + sidewalk + parkway trees + house
   facades together instead of standing on lawn well back from the street.
3. **Grass read as oversaturated "acid green."** Retuned
   `grass.gdshader`'s `color_summer_mown`/`color_summer_tall` uniforms to
   the exact linear-albedo value implied by the reviewer's measured terrain
   target (sRGB 91,123,63 -> linear ~0.105,0.197,0.050), and cut the
   per-blade hue-jitter amplitude that could locally push it brighter.
   Measured after the fix (`Pillow` mean over a clean lit-grass patch,
   `residential_street_summer.png`): ~sRGB(84,135,62) — same hue family and
   close in value to the target, though the *dominant* ground plane filling
   most of the frame in every capture is terrain's own baked lawn splat
   (`game/terrain/`, frozen/another workstream), not this workstream's
   sparse near-camera blade `MultiMesh` — flagging so the number isn't
   misread as this system's sole contribution.
4. **Autumn was a flat, uniform brown/tan mass** (`vista_oblique_autumn.png`).
   The season-color blend used one baked-per-species autumn color with no
   per-tree variation, so every tree of a species (which dominates a given
   view, e.g. a street's elm/hackberry run) turned in perfect lockstep.
   Added a per-cluster (world-space-cell-hashed, not per-species) autumn
   "turn timing" jitter in `foliage.gdshader` — biased so a good fraction of
   clusters read less-turned/greener than the global `season_foliage` value
   and a few read more-advanced — while keeping the *density*/bare-out
   timing on the real unjittered value so winter leaf-drop still happens in
   sync. Combined with the existing per-species hue table (oak russet, maple
   orange-red, locust/elm yellow), the same vista now shows genuine dappled
   variation instead of one flat tan mass.
5. **Vista camera was inside/under the canopy.** The original point (found
   via a "highest nearby elevation" search) happened to sit within a
   tree's actual rendered canopy extent, which reaches further from the
   trunk than the placement radius alone suggested. Fixed by both querying
   real tree-instance clearance before choosing a camera point (see above)
   and, for this specific shot, moving the camera to ground+120m — clearly
   above any canopy — for a true oblique vista over the town.

Net effect on counts: the street-tree height/thinning change is
render-time-only (`vegetation.gd`), not a data regeneration, so
`game/vegetation/data/trees.json` is unchanged; ~15% of `category=="street"`
instances are simply skipped at MultiMesh-build time and the rest render
smaller.

## iter2b/c: grass re-measurement, performance, and an open framing bug

**Grass color, round 2.** Setting `grass.gdshader`'s uniforms to the exact
reviewer-provided linear target (0.105,0.197,0.050) still measured ~1.5-2x
too bright in a sunlit composed capture (`residential_street_summer.png`:
sRGB ~111,148,91). Re-tuned per-channel by the measured ratio (blue was off
further than red/green) to `color_summer_mown = (0.070, 0.132, 0.024)`
(`color_summer_tall` and `color_dormant` scaled the same way), cut
`BACKLIGHT` 0.12->0.05, halved the per-blade hue-jitter amplitude. Re-measured
on a fresh `page_park_summer.png` (sunlit patches, `Pillow` mean over several
clean crops, `srgb_to_lin` conversion): **sRGB ≈ (78-108, 81-109, 54-74),
linear ≈ (0.08-0.15, 0.08-0.15, 0.04-0.07), saturation ≈ 0.33-0.35** against
the target sRGB(91,123,63)/linear(0.105,0.197,0.050)/sat 0.49. This is much
closer than the pre-fix measurement (linear ~0.16,0.30,0.11) but **not an
exact match**: R now reads slightly high and G slightly low relative to the
target (R≈G rather than G clearly leading), so it reads a touch more
olive/muted than the target's cleaner green, and saturation is still ~30%
below the 0.49 target. Shaded patches vary widely (linear 0.015-0.13)
reflecting real dappled-light variation rather than one flat shade value,
which is expected. Honest status: **improved substantially, not fully
converged** — a further round would nudge G up and R down slightly and
probably needs 1-2 more measure/adjust passes to close the saturation gap,
same iterative process roads used for asphalt. Not attempted further per
explicit direction to stop chasing this with more capture cycles while
several other agents' capture jobs were queued on the shared GPU.

**Performance.** Two measurements, both `perf_probe.tscn` at the S Hennepin
worst-case vantage (real Vulkan, 120 warmup + 180 measured frames):
- Before the perf pass (canopy hole-punch shader active, 115m near-LOD
  range, fbm-based masks): **37.5 fps / 26.68 ms**.
- After swapping `fbm()`->single-octave `value_noise()` in both shaders,
  adding uniform (whole-draw-call) early-outs around `snow_mask()`/
  `apply_wetness_darkening()` when `snow_cover`/`wetness` are ~0, and pulling
  the near-LOD range in from 115m to 90m (shrubs 55m->42m): **33.0 fps /
  30.30 ms** — worse, not better. This composed-world scene was also under
  active GPU contention from other agents' queued capture jobs at
  measurement time (per the orchestrator's own note), so the second number
  is not trustworthy as an isolated measurement of the code change; I did
  not get a clean re-measurement before being told to stop launching
  captures. **Both numbers are below the 60fps/RX-580 target** — report this
  honestly rather than the more flattering of the two. Next step for
  whoever picks this up: re-run `perf_probe.tscn` alone (no other agents'
  GPU work queued) to get a trustworthy number, then if still under target,
  the highest-leverage remaining cut is almost certainly reducing
  leaf-cluster/card count per tree in `tree_builder.gd` (geometry-side,
  addresses both fill-rate and vertex cost directly) rather than further
  shader-math micro-optimization.

**Open item: an unexplained bad frame, not re-characterized further per
explicit instruction.** A `residential_street_summer.png` recapture (same
camera position that produced the good, reviewer-approved iter2 shot)
came back with a completely different, wrong framing — an open-lawn/
tree-cluster view with a hard bright/dark diagonal seam, nothing like the
expected street-corridor shot — and that capture run took ~90s/shot instead
of the normal 2-7s/shot, suggesting heavy contention or some other anomaly
at capture time (this was during a window with several other agents'
capture jobs queued on the shared GPU lock, per the orchestrator). Camera
position and placement data were unchanged from the good capture, so this
is not a data/placement regression as far as I can tell from static
inspection. While investigating by code review (not by re-capturing), I
found and fixed one real, independently-justified bug that *could*
contribute to exactly this kind of artifact at an LOD crossfade boundary:
`VegTreeBuilder.build_billboard()` (far-LOD impostor mesh) had its quad
positioned from `y=0.55*height_frac` to `y=1.55*height_frac` instead of
`y=0` to `y=height_frac` — the billboard was floating half a tree-height
above the ground and was 55% taller than the near-LOD mesh it's supposed to
crossfade with at the same world position/scale. Fixed to span `y=0` to
`y=height_frac` from the trunk-base origin, matching the near mesh. **This
fix is unverified by a fresh capture** (explicitly told not to launch one) —
whoever next captures vegetation shots should confirm both that the bad
frame doesn't reproduce and that far-LOD trees now sit correctly on the
ground with the right silhouette height at the near/far crossfade distance
(~80-95m from camera).
