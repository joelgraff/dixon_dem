# Roads module: phase 4 of the roadway control plan, absorbing phase 3b

Status: agreed 2026-10-19; nothing built yet. This is phase 4 of the phasing table in
[roadway_control_plan.md](roadway_control_plan.md), which took in what was planned as phase 3b.

## Why a new module

After phase 3a the design data is complete and authoritative:

- `alignments.json`: 282 routes of tangents and curves, and 565 junction control points
- `profiles.json`: vertical alignments with shared junction elevations and fixed controls
- `templates.json`: the cross-section of every route over each station range

The code that turns that data into a road is still the old pipeline, now re-pointed at the
design lines:

- `transport_layout.py` (546 lines): polygon unions and offsets, a circular-closing junction
  solve, and constrained triangulation
- `build_road_plan.py` (1,805 lines): furniture, markings, rails, bridges, mesh emission
- `common_roads.py` (465 lines): ribbons and fillets
- `build_profiles.conform_strips` and `build_heightmap.road_conform`: paint the heightmap from
  sampled centrelines

What is left to fix is the surface itself, and the old pipeline has no place to put it:

- **Crowns inside junctions are undefined.** About 15% of cross-slope samples inside a junction
  slope the wrong way, and phase 3a's wider templates put 42% more stations inside junctions.
  The metrics check (`test_road_metrics.py`) has failed on this since 3a, by decision, as an
  open item for this phase.
- **Flat streets cannot drain.** 76 m of street keeps a flat profile and needs a sawtooth gutter.
- **Nothing ties the roadside back to the ground.** The conformed heightmap feathers 1.5 m back
  to whatever lies beneath. There are no designed side slopes and no walls.
- **The road mesh and the heightmap are two approximations of one surface.** They are kept
  apart by offsets and skirts instead of sharing vertices: `ROAD_SURFACE_M` (0.085 m),
  `ROAD_Y_BIAS`, curb-face skirts into the terrain, and double-sided ribbons.

Building 3b into `transport_layout.py` and `build_heightmap.py` would put the most important
geometry in the code that is due to be replaced. So 3b becomes the core of the new module.

## The rule: one surface, many readers

Every road surface is defined once, as a function of a route's station and offset:

- **station**: the profile height at that station
- **offset**: the template's cross-section (crown, gutter, curb, parkway, walk)
- **junctions**: the warped plateau of a node module

Everything else is generated from that one surface, and nothing re-samples a raster to find a
road's height:

- the meshes
- the collision shapes
- the layout polygons
- the conformed heightmap

Each piece of ground belongs to exactly one producer. A straight or curved stretch of street
(a *strip*) ends where its junction module begins, at a station on each leg. So there are no
boolean operations between road pieces. Booleans remain only against things that are not road
(buildings, water, lots), and their conflicts are reported, as phase 3a's `roadside_conflicts`
already does.

## Inputs

All of these are current files:

- `game/data/alignments.json`, `profiles.json`, `templates.json`
- `pipeline/roads/design_standards.json` and `alignment_overrides.json`
- `game/data/bridges_composed/*.json` and `bridges.json`: the decks, which stay as they are
- `game/data/rails.json`
- `game/data/aerial_paved.json`: lots, after the classification work under way
- building footprints: obstacles for the roadside
- `heightmap_play_1m.r32`: the hydro-flattened ground, which daylighting ties into

## Outputs: the contract the switch must keep

The new module writes the files the game already reads, in the same formats, so no consumer
changes at the switch.

| output | read by |
| --- | --- |
| `game/roads/_build/chunk_*.json` + `manifest.json`: meshes by material, furniture transforms | `game/roads/tools/build_roads.gd`, the bake |
| `game/roads/_build/transport_layout.json`: named surface polygons (asphalt, gutter, curb, parkway, sidewalk, verge, lots, paths) | `pipeline/terrain/bake_splat.py`, `pipeline/vegetation/place_vegetation.py`, `game/tools/composer_server.py` (approach sidewalks for Bridge Composer) |
| `game/data/heightmap_play_1m_road_conformed.r32` | terrain, vegetation, the road bake, `road_metrics.py`, Composer's ground profiles |
| `game/data/bridge_profiles.json` | `game/landmarks/tools/build_landmarks.gd` (Galena bridge dressing) |
| collision: hard pavement in a `Collision` body, graded grass in `GrassCollision` | `game/vegetation/grass_spawner.gd`, `roads/tools/test_transportation.tscn` |

The furniture kinds stay the same:

- lamps: `lamp_downtown`, `lamp_residential`
- street furniture: `hydrant`, `manhole`, `stopsign`, `sign_street`, `signal_mast`
- seasonal: `windrow`, `leaf_litter`
- rail: `crossbuck`, `tie`
- markings and crosswalks

## Architecture

### 1. The design surface (phase 3b)

`surface.py` evaluates a route's height at (station, offset):

```
y = profile(sta) + section(sta, offset)
```

- **`section`** comes from the template at that station. It covers:
  - the crown: 2% to the gutter, tapering where widths change
  - the gutter flag, visible or overlaid
  - the curb reveal: 6 in new, 4 in older
  - the parkway and walk: at most 2% toward the curb
- **Junction plateaus.** Each node module carries its own surface (§3). The minor street's crown
  warps to the major street's cross-slope over a run-out length. Phase 2's edge-of-pavement tie
  (`JUNCTION_TIE = "curb_return"`) becomes the active tie here, since the warp is what makes it
  work.
- **Sawtooth gutters.** Where the profile grade is under `min_gutter_grade`, the gutter line
  alternates between high points and inlet low points at a spacing the standards give. The
  crown absorbs the difference.
- **Daylight.** From the outer edge of the template, a side slope runs down at 1:4 in fill or
  up at 1:3 in cut until it meets the ground. Where it reaches a building footprint or water
  first, the module emits a wall station range instead and reports it.

The surface is materialised as a triangulated mesh per strip and per node module. The mesh is
regular along stations: 2 m on tangents, and arcs within 2 cm. Breaklines fall at every
template edge.

**Conformed heightmap.** The surface mesh is rasterised exactly at each pixel corner (the
convention phase 2 found), along with the daylight slopes, onto the hydro-flattened ground.
Under pavement, the terrain sits a fixed clearance below the road mesh: one documented constant,
replacing `ROAD_SURFACE_M`, `ROAD_Y_BIAS` and the skirts. That is needed because a 1 m raster
cannot hold a 6 in curb. Curbs and walks are drawn by meshes, and the terrain only has to stay
under them.

### 2. Linear modules: strips

Each template station range is swept along its alignment as a row of quads per component:

- lanes and parking (asphalt)
- gutter flag, or none
- curb top and face
- parkway (graded lawn, in grass collision)
- walk

The walk is laid as 1.524 m (5 ft) panels with joints. Each quad is single-sided and wound
correctly by construction, with a test per component as `test_bridges_composed.py` does for
decks.

Furniture is placed by station on the same module grid:

- lamps every N panels
- hydrants and manholes at catalogue spacing
- windrows and leaf litter along the gutter line

Markings are swept along the lane lines from the template's lane split. The lane split is now
known, so markings no longer guess from `lanes` tags.

### 3. Node modules: junctions

Each junction is built from its legs: their templates, headings and the station where each
strip stops.

| type (today's counts) | module |
| --- | --- |
| T, skew ≤ 15° (186) | parametric T |
| 4-leg, skew ≤ 15° (193) | parametric 4-leg |
| service-only: driveways, aisles (95) | flush apron: no curb return, the service road's surface meets the street's gutter line |
| skewed 3- and 4-leg (64), 5-leg (2), 2-leg bends and name changes (25) | curated module, or the interim fallback (below) |

So 379 of the 470 street junctions (81%) are covered by the two parametric modules.

A parametric module is built in its own frame:

- **Plateau:** warped crowns, the major street's cross-slope carried through.
- **Curb returns:** radii from the catalogue (3, 4.5, 6, 7.5 and 9 m) by the legs' classes, with
  overrides.
- **Curb ramps:** 8.33% maximum running slope, with landings, where walks meet.
- **Paint:** crosswalk and stop-bar positions, where the template or data says.

The module is then placed at the junction control point.

Geometry is regenerated per junction, since leg grades differ. A module's code and tests are
shared by every junction of its type: watertight, winding, ramp slopes, no step to its strips.

**Interim fallback** for junctions no module covers yet: a plateau fitted as a plane through the
legs' edge heights, with the outline from today's junction solve, emitted as a node patch. That
lets the module switch over before every junction type has a module. The report counts these,
and they shrink as curated modules arrive.

### 4. Everything else

These keep their current builders, moved behind the new module's interfaces:

- **Lots:** `aerial_paved.json`, clipped to what the roads own, with flush edges.
- **Paths:** footways and steps on their own profiles (phase 2 already gives the 101 off-route
  ways one), as narrow strips with flush or kerbed edges.
- **Rails:** the current ballast, tie and rail builder, unchanged for now. The rail's own
  profile is a separate item (phase 2 found the IC line's drawn heights 0.24–1.49 m off the
  ground).
- **Bridges:** `bridges_composed.py`, unchanged. Approaches already meet the decks through the
  profiles.

## Building it alongside, then switching

- **Location:** the new code lives in `pipeline/roads/kit/`. It writes to `game/roads/_build_v2/`,
  `transport_layout_v2.json` and `heightmap_play_1m_road_conformed_v2.r32`.
- **Default stays on the old pipeline:** `rebuild_transportation.sh --v2` runs the new module
  and feeds its outputs to the same consumers, writing to the v2 paths. Without the flag,
  nothing changes.
- **Comparison:** `compare_roads.py` runs `road_metrics.py` on both surfaces, diffs the layout
  areas by surface, and renders paired captures at a fixed set of viewpoints:
  - a residential block and a residential T
  - downtown Galena & 1st
  - a curve
  - a steep street (West 9th)
  - a bridge approach (Galena north)
  - a skewed junction
  - a flat street with a sawtooth gutter

Switch gates. All must pass before v2 becomes the default:

1. **`test_road_metrics.py` passes against the phase 2 baseline**, which 3a broke inside
   junctions:
   - adverse cross-slope sides ≤ 212
   - junction steps over 0.10 m ≤ 20, and none over 0.25 m
   - cross-slope deviation from crown no worse than phase 2 at p50 and p99
   - breaklines ≤ 3: the designed rail-berm drive and the reported West 9th bluff are known
2. The layout validates: no overlaps between road pieces, no invalid polygons, every strip and
   module watertight.
3. The consumers run unchanged: the splat bake, vegetation, the road bake, Bridge Composer's
   approach sidewalks, and `test_transportation.tscn` (grass on graded collision, never on
   asphalt).
4. The triangle count is within 10% of the current road layer, and `perf_probe.tscn` stays at
   60 fps or better at the downtown viewpoint.
5. The paired captures are reviewed. No viewpoint is worse.

**Switch:**

- Make v2 the default and keep `--v1` for one rebuild cycle.
- Then delete:
  - `transport_layout.py`'s polygon pipeline and junction solve
  - the mesh code in `build_road_plan.py`: ribbons, fan fills, fillets, double-sided asphalt,
    edge skirts
  - `common_roads.py`'s ribbon helpers
  - `build_heightmap.road_conform`'s painting
- Furniture, markings, rails and bridges move into the kit, or stay as thin callers.

## Steps

Each step lands on its own, with tests, and can be compared using v2.

| step | delivers | done when |
| --- | --- | --- |
| 4.0 | Output contract written down (formats above, with a validator); v2 paths and `--v2`; `compare_roads.py` | the old pipeline's outputs pass the validator; the comparison runs (v1 against itself) |
| 4.1 | `surface.py` for strips (profile + template section, tapers); strip meshes; heightmap rasterisation from the surface mesh, with junction areas left to the old conform | strip metrics outside junction boxes beat phase 2's; the road mesh and the raster agree to within the clearance constant at every strip vertex |
| 4.2 | Linear modules: curb, gutter, parkway, walk panels, collision split; layout polygons from strips; furniture and markings on the module grid | the consumers run on v2 strips plus old junctions; `test_transportation` passes |
| 4.3 | Node modules: T and 4-leg with crown warping, curb returns, ramps and crosswalks; service aprons; the interim fallback for the rest | gate 1 passes |
| 4.4 | Sawtooth gutters; daylight slopes and walls in the raster and the layout | no flat run without drainage; daylight conflicts are reported; gates 2–4 pass |
| 4.5 | Captures reviewed; switch; old code deleted | gate 5; v1 removed after one cycle |

Curated modules for the remaining 91 junctions, and editor support (phase 6), come after the
switch.

## Open questions

1. **Terrain under pavement.** Keep a clearance constant (simple, as today), or cut the terrain
   mesh out under the road layer? A cut-out would remove the overlap entirely, but changes the
   terrain workstream's chunk builder.
2. **Driveways.** Today there are none except where OSM maps a service way. Should driveway
   aprons from the aerial, which shows them as concrete cuts across the parkway, be a module in
   4.2, or later?
3. **Older curbs.** No route uses the 4 in `older` curb yet. Is there a way to tell them, by
   neighbourhood or street age, or do they stay a per-route override?
4. **Where to work.** The working tree has been shared by several sessions rebuilding the same
   generated files. Build phase 4 on its own branch in its own worktree, and run one
   transportation rebuild at a time.
