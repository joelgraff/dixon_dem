# Roadway horizontal and vertical control: plan

Status: proposal, 2026-10-18. Phases 0, 1, 2 and 3a are built (see their results sections); the rest is not.

## The problem

Every road surface today is **sampled, not designed**. Heights come from a DEM with roughly 3 m
resolution. Centrelines come from OSM nodes. Each consumer then repairs the result locally:

- `build_heightmap.road_conform` samples the DEM every 2 m along each OSM way and takes a 15 m
  moving average **per way**. It then writes those heights into the raster by nearest sample, adds
  a radial 2% "camber" and feathers the result back to raw ground over 2 m.
- Intersections have no elevation of their own. Where several ways meet, the nearest sample wins.
- Bridge approaches are patched on: `anchor_profile` blends a smoothstep over 40 m, a second pass
  levels the ground out to the sidewalks, and `bridge_profile` has a ramp fallback. Each patch fixes
  one symptom and adds a special case.
- Widths come from OSM tag defaults (`HIGHWAY_DEFAULTS`). Residential streets are 6.5 m everywhere,
  with no lanes, parking or crown modelled.

Measured by `pipeline/roads/road_metrics.py` (phase 0, below) on drivable non-bridge ways inside
the 1 m play heightmap:

| metric | p50 | p90 | p99 | max |
| --- | --- | --- | --- | --- |
| step across a junction (legs extended to the node) | 0.06 m | 0.15 m | 0.37 m | 0.86 m |
| per-way smoothed elevation disagreement at a shared node (today's `road_conform` input) | 0.05 m | 0.19 m | 0.45 m | 0.71 m |
| centreline grade, 10 m chords | 1.6% | 5.9% | 10.6% | 34% |
| grade change in 10 m | 0.41% | 1.8% | 4.5% | 48% |
| cross slope, deviation from a 2% crown | 0.8% | 1.8% | 5.0% | 29% |

133 junctions step more than 10 cm, and 22 more than 25 cm. Those steps turn into the warped curb
returns and sidewalk ledges that keep coming back as tickets. 786 pavement sides slope toward the
centreline instead of the gutter. 8.2 km of centreline curves more sharply than the class's minimum
K allows.

An earlier version of this table showed 104% grades. Those came from sampling outside the play
heightmap and are not part of the surface. They led to a real defect, though; see phase 0 results.

## Principle

Treat OSM, the DEM and the aerial as **observations**. Fit a **design** to them: an alignment, a
profile and a cross-section. Every consumer then reads the design: the road mesh, the conformed
heightmap, sidewalks, bridges, vegetation masks and furniture. That gives one source of truth with
explicit tolerances, rather than each stage smoothing the DEM in its own way.

This is the order a civil designer works in: horizontal control, then vertical control, then the
typical section, then grading to existing ground.

## 1. Routes and stationing

- Merge OSM ways into **routes**: chains through degree-2 nodes, and through junctions where the
  name and class continue (Galena Ave stays one route from end to end, including the bridge).
  Today the network is 650 ways, split into 1539 segments. Routes are the unit of design.
- Each route gets **stationing** in metres (shown in feet too), with station 0+00 at a stable end.
- Every feature hangs off a station and offset, not an xz point. This covers a bridge (a station
  range), a crosswalk, a lamp, a driveway or a lane-width change.

## 2. Horizontal control

- Fit each route as **tangents plus circular curves**. Spirals are unnecessary below about 45 mph.
  - Fit to the OSM nodes, weighted by the aerial pavement edges where `aerial_paved.json` or the
    6-inch imagery shows them.
  - Use a robust fit: tangent detection by RANSAC or Douglas-Peucker, then a least-squares PI
    adjustment. Snap a curve radius to a catalogue value when the snap costs less than the
    tolerance.
- **Tolerance**: the fitted centreline may move up to about 1.0 m from OSM, or 0.5 m downtown, where
  the building fronts constrain it. A larger deviation is reported, not silently applied.
- **Grid discipline**: near-parallel and near-orthogonal streets snap to a shared bearing when they
  are within about 1.5°. Dixon's platted grid is regular, so OSM jitter is noise, not geometry.
- **Intersection control points**: each junction gets one PI point, where the route centrelines
  intersect, plus its skew angle. This replaces centroid fans.

## 3. Vertical control

- **Fixed controls** that the solve must honour, as hard or heavily weighted constraints:
  - bridge bearing and abutment seats
  - railroad top of rail at crossings (rail profiles are their own alignments)
  - minimum freeboard over river pool levels
  - user-pinned elevations
  - eventually, finished-floor elevations of landmark buildings at their entrances
- **Profile per route**: PVIs joined by symmetric parabolic vertical curves (one per route, not one
  per OSM way).
  - Fit to DEM samples along the alignment by robust least squares (Huber loss, so the DEM's bridge
    removal and river-bank artefacts do not drag the grade).
  - Guided by: maximum grade by class, minimum K (curvature) for crest and sag curves, minimum
    curve length, and a minimum 0.3–0.5% grade on curbed streets so gutters drain. Flat stretches
    get a sawtooth gutter profile instead.
  - These class limits are **advisory** (decision 2). They are values for new designs and cannot
    account for existing conditions. A fit reports where a street exceeds them, but the limits
    never pull a profile off the ground or fail a build. The hard constraints are the fixed
    controls and continuity at junctions.
- **The network is solved together**: junction elevations are shared unknowns. The higher-class
  route at a junction keeps its profile and crown through it. The lower-class route takes the
  higher route's edge-of-pavement elevation at its curb-return points.
  - This is the IDOT/AASHTO convention: the major street's cross-slope is carried, and the minor
    street's crown is warped to it over a transition.
  - It removes the junction disagreement by construction (target: 0.00 m).
- **Starting limits** (advisory), to be confirmed against the IDOT BLRS Manual's urban tables:

  | class | design speed | max grade | crest K | sag K |
  | --- | --- | --- | --- | --- |
  | primary / IL-26, US-52 | 35 mph | 6–8% | 29 | 49 |
  | collector / tertiary | 30 mph | 8–9% | 19 | 37 |
  | residential / local | 25 mph | 10–12% (terrain-limited) | 12 | 26 |
  | alley / service | 15 mph | 12–15% | — | — |

  The K values are AASHTO Green Book stopping-sight-distance values. In urban low-speed areas, sag
  K often relaxes to the comfort criterion where streets are lit. Treat the table as a
  configuration file (`pipeline/roads/design_standards.json`), not as constants.

## 4. Cross-section templates (typical sections)

A template is an ordered list of components outward from the centreline, each with a width and a
cross-slope.

| component | default | notes |
| --- | --- | --- |
| travel lane | 3.66 m (12 ft) arterial, 3.35 m (11 ft) collector, 3.05 m (10 ft) local | urban local streets are usually narrower, and parking makes up the difference |
| parking lane | 2.44 m (8 ft) | downtown and many residential streets |
| crown | 2.0% (1.5–2.5%) | normal crown, with the lanes draining to the gutter |
| gutter flag | 0.61 m (24 in) | IDOT combination curb and gutter B-6.24 (6 in curb, 24 in gutter), old and new alike. Many flags have been overlaid with asphalt and show no gutter: an `overlaid` flag per route gives a visible width of 0. Today's code uses 0.3048 m. |
| curb | 0.152 m (6 in) reveal for new curb, 0.102 m (4 in) for older curb | barrier curb; mountable at alleys and drives; older curb is chosen per route |
| parkway | 0–3 m | residential, holds street trees |
| sidewalk | 1.52 m (5 ft) residential, 1.83 m (6 ft) typical, to building face downtown | at most 2% cross-slope toward the curb (ADA/PROWAG) |
| back slope / daylight | 1:4 (fill), 1:3 (cut), steeper only behind walls | ties into existing ground |

- Templates attach to station ranges of a route, so the width changes where the street does: the
  downtown section starts at a station, not at a polygon boundary.
- Width transitions use tapers (for example L = WS²/60 at low speed), not polygon unions.
- Real curb-to-curb widths for Dixon should be **measured from the 6-inch aerial** per route, then
  rounded to the template catalogue. The 6.5 m OSM default looks narrow for the residential grid,
  and needs checking.
- IDOT is the starting point, not the rule. Each route's template is data that can be overridden,
  and downtown can have zero parkway, wide walks, angle parking or bump-outs.

## 5. Modular construction: a kit of parts

Your suggestion fits this model well, with one change. The modules should be **placed along
stations and at intersection control points, not on a world grid**.

- Fixed-size world tiles would fight curves, skewed junctions and the slight rotation between OSM
  and the platted grid.
- Modules keyed to the alignment get the same benefit: a small set of standard pieces, each
  verified once.

**Linear modules**, swept along a route between nodes:

- The cross-section template from §4, built in fixed **station increments**. For example:
  - sidewalk panels on a 1.52 m (5 ft) module, which also gives control joints for free
  - curb in matching segments
  - lamp, hydrant and tree spacing snapped to whole modules
- The mesh is a generated strip per template and per station range. It is regular, has quads only,
  needs no polygon booleans, and has a known winding.

**Node modules**, a parametric library instanced at each junction:

- Junction types: T, 4-leg, offset T, Y/skewed, plus a cul-de-sac and a dead-end.
- Each type is parameterised by:
  - the leg templates
  - the skew angle
  - a curb-return radius from a fixed set (3, 4.5, 6, 7.5, 9 m; about 10, 15, 20, 25, 30 ft)
- Each module is built in its own local frame:
  - the asphalt plateau with the warped crowns from §3
  - curb returns
  - curb ramps (8.33% maximum running slope, landings)
  - crosswalk and stop-bar positions
- Each module is then placed at the junction's PI and elevation. Identical junctions (most of the
  residential grid) produce identical geometry, which also makes them a natural place for
  instancing or LOD.
- Mid-block modules: driveway aprons (standard widths), alley returns, bump-outs, bus pads.
- **Structure modules**: abutment, pier, standard span types and depths, and approach slab. Bridge
  Composer already works this way. The change is that its stations and elevations come from the
  route instead of being authored separately.

What this replaces:

- In `transport_layout.py`: most of the polygon union, offset and boolean pipeline, and the
  circular-closing junction solve.
- In `build_road_plan.py`: the centroid-fan junction fill, which assumes star-convexity.

Many current problems have a single cause: polygons are inferred from noisy centrelines, then
offsets of those polygons define everything else. Junction modules give each corner a design.
Their geometry can be unit-tested per type: winding, watertightness, ADA slopes, and agreement
with neighbouring strips.

**Escape hatch**: a junction the library cannot express gets a curated module, which is a hand-built
or Composer-authored node in the same local-frame format. This is the same idea as
`layout_overrides.json`, at a higher level.

## 6. Bridges on the alignment

- A bridge is a **station range on its route**. The deck profile is the route's vertical alignment
  across that range, so the approach roads and the deck share one profile. That removes:
  - `anchor_profile`, `BRIDGE_ANCHOR_*` and the sidewalk-levelling second pass in
    `build_heightmap.py`
  - `bridge_profile`'s ramp fallback in `build_road_plan.py`
- Bridge Composer edits the route's PVIs within and next to the bridge (crest, end grades) instead
  of free `elevation` rows. The file keeps `elevation` as a derived cache, so the reader does not
  change in v1.
- Checks:
  - vertical clearance over water (pool level plus freeboard)
  - clearance over other routes or rails: about 4.4–4.9 m (14.5–16 ft) over roads, and about 7 m
    (23 ft) over railroads (AREMA)
  - maximum grade and K across the bridge
  - deck cross-slope continuous with the approach crown
- Cross-section continuity: the bridge's walkway and barrier come from a **bridge template** that
  transitions from the approach template over a set station length. That replaces "Match approach
  sidewalks" measuring polygons 4, 8 and 12 m out.

## 7. The design surface and grading

- Build a **design TIN** from the templates and node modules: pavement, curb tops, walks and
  parkways. At the template's outer edge, project daylight slopes (1:4 or 1:3) until they meet
  existing ground. Where daylighting runs into a building or water, emit a retaining-wall station
  range instead.
- Burn the TIN into `heightmap_play_1m_road_conformed.r32`. This replaces nearest-sample radial
  camber and the 2 m feather. Terrain, vegetation and road meshes then read heights that agree
  exactly, because the road mesh takes its Y from the TIN itself, not by re-sampling the raster.
  That removes the bias and skirt hacks (`ROAD_Y_BIAS`, edge skirts down into terrain).

## 8. Data and files

- `game/data/alignments.json` (generated, tracked) holds per route:
  - horizontal elements (tangent, arc), station equations and node references
  - PVIs and vertical curves
  - template assignments by station range
  - fixed controls and their source
- `pipeline/roads/design_standards.json` holds class limits and the template and module catalogues.
- `pipeline/roads/alignment_overrides.json` holds pins, forced radii and PVIs, template overrides
  and curated node modules. It takes over most of `layout_overrides.json`.
- A **design-check report**, written next to `transport_layout.json`'s quality report:
  - grade and K violations
  - junction elevation mismatch
  - horizontal deviation from OSM
  - ADA ramp and walk slopes
  - clearances
  - daylight conflicts with buildings or water

  Fixed controls and junction continuity fail the build. Class limits are advisory and only
  listed. The table in "The problem" is the
  baseline to beat.

## 9. Phasing

Each phase ships on its own and shows improvement against the baseline metrics.

| phase | delivers | visible change |
| --- | --- | --- |
| 0 (done) | `design_standards.json`; `road_metrics.py` with a ratchet test; breaklines located | none |
| 1 (done) | Routes, stationing, horizontal fit, OSM-deviation report; aerial curb-to-curb width survey per route | none (data only); review images over the aerial |
| 2 (done) | Network vertical solve with shared junction elevations and fixed controls; `road_conform` reads design profiles instead of per-way moving averages | junction steps gone, grades smooth; the biggest win for the smallest change |
| 3a (done) | Cross-section templates on station ranges; the transportation layout and the conformed heightmap built on the route alignments at template widths | real curb-to-curb widths; curb lines on the designed tangents and curves |
| 3b | Crown warping at junctions (with the edge-of-pavement junction tie, see phase 2 results); sawtooth gutters on flat streets; TIN-based conformed heightmap with daylighting | clean junction surfaces and curb returns |
| 4 | Linear and node module library replacing the polygon pipeline and fan fills; curated-module escape hatch | regular sidewalk panels and joints, consistent curb returns and ramps |
| 5 | Bridges as station ranges; Composer edits PVIs; anchor and ramp code retired; clearance checks | approaches and decks share one profile |
| 6 | Editor support: drag PIs, PVIs and template breaks in-game or in Composer, rebuilding per route | — |

Phase 2 can run on today's OSM centrelines, before phase 1's horizontal fit lands, if a quick win is
wanted first.

## Phase 0 results

- `pipeline/roads/design_standards.json` holds the class limits, cross-section defaults, module
  catalogue and clearances from this plan. Each value notes its source, and all are provisional.
- `pipeline/roads/road_metrics.py` measures the road-conformed heightmap along every drivable,
  non-bridge way. It covers grade, grade change and implied K, cross slope, junction steps and
  breaklines. It writes `game/roads/_build/road_metrics.json` and runs in about 2 s.
- `pipeline/roads/test_road_metrics.py` tests the measures on analytic surfaces. It also fails the
  build when any defect metric gets worse than `road_metrics_baseline.json`. Plain grade is
  reported but not held, because a design that follows the terrain can be steeper in places.
  When a phase improves the numbers, run `road_metrics.py --update-baseline` and commit the
  baseline with the change.

**The 104% breaklines** were not in the play area's surface.

- They lie on roads past the edge of the 1 m play heightmap: Fieldstone Lane, Great Oaks Way and
  Fox Trot Lane east of x = 2700, and East River Road.
- `build_road_plan.VALID_BOUNDS` keeps roads out to 400 m beyond the heightmap: **38.6 km of drivable
  centreline**, about a quarter of all asphalt vertices.
- `Heightmap.sample` clamps to the edge row there, so those roads take the edge's heights instead of
  the ground's. Compared with the horizon heightmap that the terrain shows out there:
  - asphalt sits a median 1.9 m below it
  - 69% of those vertices are more than 1 m off, and 39,000 are more than 3 m off
  - some are as much as 17.8 m below it

  Inside the play area, 3% of vertices are more than 1 m off, which is the 12.5 m horizon grid's own
  coarseness.
- **Fixed (2026-10-18).** `VALID_BOUNDS` is now the play heightmap's sample extent, x 0–2699 and
  z −2700 to −1. `clip_ways_to_bounds` cuts each way exactly at that edge, adding an interpolated
  vertex there, instead of dropping it at its last vertex inside.
  - Road chunks went from 283 to 184.
  - Built road vertices past the heightmap went from about 98,600 to 0. No ratcheted surface
    metric changed.
  - `drivable_length_beyond_play_heightmap_m` is now held at 0.
  - In a capture at the east edge (`captures/roads/clip_edge/`), East River Road ends at the edge.
  - Past the edge, that capture shows open sky-blue ground below the play terrain. That is the
    horizon ring, a terrain question, and it is not caused by roads.

**The three remaining breaklines inside the play area** are steeper in the ground itself (conform
already eases them):

| location | grade | ground grade | what is there |
| --- | --- | --- | --- |
| service drive, way 1068020153, (854, -1855) | +31% | +38% | 5.5 m from the railroad: the drive climbs the rail embankment |
| West 9th Street, way 21833257, station 67–71, (1356, -408) | +28% | +35% | 66 m from a mapped stream: a ravine or culvert crossing, possibly a hydro-enforcement breach in the DEM |
| service alley, way 1020578833, (1824, -1428), downtown | +26% | +42% | 15 m from a building: a pad edge, wall or ramp in the DEM |

Each is a case for a fixed vertical control in phase 2: the top of rail at the crossing, a culvert
or embankment profile on West 9th, and a pinned alley grade downtown.

## Phase 1 results

`pipeline/roads/build_alignments.py` (about 3 minutes; `--overlay` also draws the review
images, `--no-width` skips the aerial survey) writes `game/data/alignments.json` and
`game/roads/_build/alignment_report.json`. Nothing in the game reads them yet.

**Routes** (`routes.py`):
- The 537 drivable OSM ways inside the play area chain into **281 routes**, 94 km in all.
- A route follows a street through OSM's splits, and across a junction where the same street
  carries on. Names are matched without the direction word, so West and East 1st Street are one
  route.
- Stationing runs west to east, or south to north.
- Galena Avenue is one route except where it is a one-way pair, whose second carriageway is a
  route of its own.
- Every route records the station range of each of its OSM ways and bridges.

**Horizontal fit** (`alignment.py`):
- Each route is tangents and circular curves through PIs. The two street grids, at 343.5° and
  1.8° (mod 90°), are found from the data, and 192 of 697 tangents snap to them.
- That gives 546 curves and 251 angle points. The angle points are mostly parking-aisle
  corners and short stubs at route ends.
- Merging straight runs, removing OSM's sub-metre jogs, snapping to the grid and rounding radii
  are each allowed only within the deviation tolerance.
- Lateral deviation from OSM per route: median 0.51 m, 90th percentile 0.91 m, worst 1.00 m.
  One route is over tolerance: a 0.55 m stretch of West 1st Street downtown, left for review.

**Junctions:**
- 562 junction control points, each where the route alignments actually meet. A control point
  sits a median 0.39 m from its OSM node, at most 3.7 m.
- 319 route ends that stop on another street were moved onto that street's alignment.
- Each junction records its legs, their stations and headings, and its skew.

**Width survey** (`aerial_width.py`):
- Measured a block at a time on the 2025 aerial. 361 of 503 blocks give a confident edge pair.
- **88 routes have a measured width.** The other 84 surveyed routes fall back to the OSM
  width tag, because too few blocks counted or the counted blocks disagreed by more than 2 m.
  Downtown mostly falls back: cars along whole blocks and sidewalks running straight to the
  curb defeat the edge finder.
- Medians: local streets 10.2 m of asphalt (about 33 ft), collectors 12.5 m, arterials 17.9 m.
  Widths are rounded to the foot.
- The concrete gutter flag was not seen on any route, so the gutter is recorded as `not_seen`
  and curb-to-curb is the asphalt width. The detector cannot tell an overlaid gutter from one
  it missed.
- Block centres sit a median 1.0 m from the alignment. Sixty blocks are more than 2 m off;
  they are listed for review in `off_centre_blocks`. Nothing is recentred automatically.
- The review images in `captures/roads/alignments/` are 0.25 m per pixel. They show:
  - OSM in red
  - tangents in cyan and curves in magenta
  - PIs as yellow dots and angle points as orange crosses
  - junction control points as white rings
  - each counted block's edges in green

**Aerial georeferencing fix.** `pipeline/aerial/georef_affine.py` was misplacing the 2025 imagery
north–south by up to about 14 m near tile edges:
- The tiles are requested as a non-square Web Mercator box but a square image. The image
  server widens the short side about its centre (checked against its returned extent), and the
  affine assumed it did not.
- Fixed, with `test_georef_affine.py`; the tiles' `pixel_from_world` were regenerated. Building
  footprints now land on their roofs and OSM centrelines down the middle of the streets.
- Two consumers worked from the bad placement:
  - Building Composer's aerial backdrop (`aerial_crop.py`), so footprints traced or nudged
    against it may be off north–south.
  - `extract_paved_il.py`, which ignores the affine entirely and places tiles by their requested
    boxes, so the parking lots in `aerial_paved.json` may be off by up to 15 m.

  Both followed up:
  - The footprint audit (`docs/footprint_aerial_audit/`) found no footprint traced on the shifted
    backdrop.
  - `extract_paved_il.py` now samples each tile through its affine. Lots went from 736 to 408
    (469,000 to 321,000 m²). The old run had shifted street pavement and roof edges out from
    under the road and footprint masks, and they leaked out as lots. Lots found by both runs
    moved a median 3.5 m (p90 8.7 m). The colour test itself still takes gravel yards for
    pavement and misses dark fresh asphalt, so lot classification needs its own pass.

## Phase 2 results

`pipeline/roads/build_profiles.py` solves the network's vertical control; `vertical.py` holds the
profile maths. `pipeline/build_heightmap.py` runs the solve on the hydro-flattened ground and then
burns the profiles into `heightmap_play_1m_road_conformed.r32`, about 3 s of its 16 s. It writes
`game/data/profiles.json` and the design-check report `game/roads/_build/profile_report.json`.
`build_profiles.py` also runs alone. Tests: `test_profiles.py`.

**Profiles:**
- Each of the 281 routes is PVIs joined by symmetric parabolic vertical curves, 5,464 PVIs in all.
  The straights are at most 20 m. Each curve is as long as the shorter straight beside it, so the
  profile is smooth (G1) everywhere.
- Elevations are the top of pavement at the centreline. The conformed terrain is 0.085 m below
  (`ROAD_SURFACE_M`), as before.
- The 101 ways on no route (footways, cycleways, steps) get their own profile along their OSM
  line.

**Fit to the ground:**
- Robust least squares (Huber, 0.10 m) on DEM samples every metre along the alignment.
- Grade changes are smoothed with a robust penalty too: up to 0.5% is penalised quadratically, a
  larger change linearly. A real embankment or bluff is followed rather than cut through. With
  plain quadratic smoothing, a 6 m berm was cut by 4 m in testing.
- Where the fit misses the ground by more than 0.25 m for 4 m or more, the vertical curve there is
  halved, or a PVI is added, and the tier is re-solved.
- Result: the profile is a median 0.016 m from the ground and 0.167 m at the 99th percentile. Only
  317 m of the 94 km is more than 0.3 m off.
- The largest misses are at the Galena deck ends, where the DEM dives into the river bank (3.3 m).
  This is the artefact the old `anchor_profile` existed to hide.

**Network:**
- The solve runs a class at a time: arterials, then collectors, locals and service roads.
- The senior route at each junction keeps the profile it was fitted with. That is the higher
  class, then the through route, then the longer.
- Routes of one class are solved together, so the heights at their junctions are shared unknowns.
- All 588 junction ties are held to within 0.1 mm.

**Junction tie:**
- The plan's rule, the junior route taking the senior one's edge-of-pavement height at its curb
  returns, was built and measured first. It made the junction steps worse: 261 over 0.10 m and
  53 over 0.25 m.
- On Dixon's hills, a side street at 7–15% crossing a flat street needs a level senior crown
  through the junction. The tie leaves that as a 0.3–0.4 m table: the junior street climbs to the
  curb return, runs level across, and climbs again.
- Real junctions there are tilted planes. That is crown warping, which is phase 3.
- So the tie is now centreline to centreline at the junction's control point. In the conformed
  heightmap, the surfaces of the routes that meet are blended by inverse-square distance to each
  centreline, so each centreline keeps its own grade and there is no crease.
- The edge-of-pavement tie stays in the code (`JUNCTION_TIE = "curb_return"`) for phase 3.

**Fixed controls** (hard rows, 1 mm-level):
- Composed bridge decks (Galena and Peoria): the elevation and the grade at each deck end, so an
  approach meets the deck level and without a kink. The deck's interior rows are softer shape
  rows. No ground data is used inside a deck's station range.
- A path, or a route that does not carry the bridge, ending at a composed deck has its end held
  at the deck's height.
- A deck end is held only within 1 m (`DECK_TRUST_M`) of its approach's own ground 5–15 m back.
  The user said some composed decks were set for another purpose, so one further off is not a
  control: the approach keeps to the ground and the end is listed in `deck_ends_not_held`. Today
  that is only the IC railbed track (R1502908856) at the north end of the cycleway bridge
  1502908855, whose flat deck (10.04) is 5.65 m below it. Galena and Peoria are held.
- Top of rail at the 19 grade crossings.
  - 11 crossings have an OSM node shared with the rail. There, the rail as drawn is exactly 0.5 m
    above the ground, and the road rises to meet it.
  - At the other 8, all on the abandoned IC line (way 367355676), `rails.json` interpolates the
    rail's height between vertices up to about 120 m apart, so the drawn rail is 0.24 to 1.49 m
    off the ground.
  - Holding the drawn rail there would lift streets by up to 2 m (West Everett Street).
    Instead, top of rail is taken as ground + 0.5 m and each crossing is listed in the report
    (`rails_off_ground_at_crossings`). The rail itself needs its own profile.
- Pins and overrides in `pipeline/roads/alignment_overrides.json`: `ignore_ground`, `pins` and
  `pvi_stations`. Two routes use them today: the alley and the rail-embankment drive (below).

**Class limits (advisory)** are reported and never applied:
- 500 m of centreline is over its class's maximum grade.
- 466 vertical curves are under the class's K, and 162 are shorter than 50 ft.
- The minimum gutter grade (0.3%) was given to flat straights on 99 curbed routes (7.8 km of
  centreline), each only where the profile moved 5 cm or less to get it.
- One route kept 76 m of flat street: the ground does not allow a grade there, so it needs a
  sawtooth gutter (phase 3).

**`road_conform`:**
- The per-way 15 m moving average, `anchor_profile`, `BRIDGE_ANCHOR_*` and their sidewalk
  second pass are gone.
- Roads are painted along their OSM centrelines with heights from the profile, lowest class first,
  then the junctions are blended.
- Within 40 m of a composed deck's end, the section eases to level and widens 6 m past the
  pavement, so sidewalks still meet the deck's walkways. This replaces the sidewalk-levelling pass
  until phase 3's templates.
- A half-cell offset is fixed: the conform placed raster cells at pixel centres, but every
  consumer reads sample (r, c) at the cell corner. That shifted the crown 0.5 m diagonally off the
  road mesh. The fix is most of the cross-slope improvement below: the same profiles painted
  at pixel centres give a 0.70% median deviation from the crown and 469 adverse sides, against
  0.32% and 209 painted at corners (measured on the same profiles).

**Metrics** (`road_metrics.py`, baseline updated):

| metric | before | after |
| --- | --- | --- |
| junction steps over 0.25 m | 22 | 0 |
| junction steps over 0.10 m | 133 | 20 |
| junction step p50 / p90 / p99 / max | 0.055 / 0.153 / 0.365 / 0.858 m | 0.020 / 0.062 / 0.149 / 0.246 m |
| grade change in 10 m p50 / p90 / p99 / max | 0.41 / 1.77 / 4.57 / 44% | 0.28 / 1.61 / 4.57 / 36% |
| cross slope deviation from crown p50 / p99 | 0.81 / 4.96% | 0.32 / 3.13% |
| adverse cross-slope sides | 786 | 212 |
| breaklines | 5 | 2 |

**The three breaklines:**
- **Service drive over the rail embankment** (way 1068020153, route R1068020153). The ground
  climbs 6.5 m in 20 m and falls 6 m in 15 m. The OSM rail crosses 12 m east of the DEM's crest,
  and the drawn rail there is 0.9 m off the ground (ground + 0.5 m is used as top of rail).
  Fixed PVIs in `alignment_overrides.json` grade it the way a drive over a berm is graded: one
  crest curve, and a sag that runs out before Chuck Vail Drive. The worst grade change is now
  29% in 10 m, not 49%, and the junction it meets has no step. It still counts as one breakline,
  because the ground leaves no profile under 25% grade.
- **West 9th Street, stations 60–80.** There is no culvert or hydro-enforcement notch: the ground
  has no dip there. It is a 4.4 m pitch up a bluff edge in 14 m, and the designed profile spreads
  it to 22%. A profile under the 12% class limit would cut and fill about 1.5 m over 40 m of
  frontage, which the class limits' advisory status rules out. It is left as reported.
- **Downtown alley** (way 1020578833). Its mapped west end runs 6 m past the top of a 4 m wall in
  the DEM. `ignore_ground` holds the alley at its terrace grade to its mapped end, and the
  breakline is gone.

**Follow-ups:**
- Rails need their own profiles. `rails.json` heights are linear between far-apart vertices, so
  the abandoned IC line floats and sinks by up to 1.5 m.
- `build_rails`'s crossing pad uses the segment's first vertex height, and is oriented along the
  rail rather than the road.
- Phase 3's crown warping, which would let the edge-of-pavement junction tie come back.
- Composed cycleway bridge 1502908855: its flat deck (10.04) is 5.65 m below the railbed track at
  its north end, which is left on its ground.

## Phase 3a results

`pipeline/roads/templates.py` (about 10 s) writes `game/data/templates.json` and
`game/roads/_build/templates_report.json`. `rebuild_transportation.sh` now runs it, then
`build_heightmap.py`, then the road plan and the rest. Tests: `test_templates.py`.

**Templates** (§4), one or more per route, each over a station range:
- Curb-to-curb width, in this order:
  1. the aerial survey's width, where it measured the route (41 km)
  2. a real OSM `width` or `lanes` tag (7 km, mostly the arterials)
  3. the median measured width of the way's class: local 9.75 m (32 ft, 83 routes), collector
     12.19 m (40 ft, 4 routes) (31 km)
  4. the importer's default, for service roads and alleys, which were not surveyed (15 km)
- Nearly every OSM width in roads.json is the importer's class default
  (`osm_common.HIGHWAY_DEFAULTS`: 6.5 m for every residential street). Only a width different
  from that default counts as a tag.
- Lanes and parking: parking lanes (8 ft) go in, both sides and then one, while the travel lanes
  stay at least `lane_width_min` (local 2.6 m). The lane count follows a real `lanes` tag, or
  else the nearest even number. Result: 27 km of residential street parks both sides, 46 km one
  side, and 4 km none. Link ramps never park.
- Gutter: the 2 ft flag (B-6.24) is always in the template. It shows only where the aerial saw
  concrete on a clear majority of a route's blocks; otherwise it is `overlaid`, with a visible
  width of 0. No route met that bar, so the concrete gutter strip is gone from the game. An
  override brings it back per route.
- Curb: `new` (6 in) by default (`curb_default`), or `older` (4 in) per route by override. The
  layout and mesh carry the lower curb, parkway and walk wherever a template says so. No route
  uses `older` yet.
- Roadside: the residential (2.0 m parkway, 1.7 m walk) and downtown (3.6 m walk) profiles the
  layout already built, now in `design_standards.json` `roadside` and overridable per route.
- Where the width changes along a route, it tapers over L = WS²/60 (12 tapers).
- Overrides: `alignment_overrides.json` `templates`, by route and optional station range. They
  set width (ft or m), lanes, parking, gutter, curb, section, parkway and sidewalk. None are set
  yet.

**Design roads.** `templates.design_roads()` is what the layout, the conform and the metrics
read: roads.json with every drivable way on a route re-drawn along its alignment.
- Each way is cut at its junction nodes. Each run is matched to a route and a station stretch by
  a two-way fit, so a run cannot follow a route around a loop or on past its own end.
- Arcs are densified to stay within 2 cm of the curve.
- 93.9 km of drivable centreline is on the alignments, and nothing inside the play area keeps
  its OSM line.
- Run ends meet at one point per node: the routes through the node set it, and routes ending
  there snap onto it. The snap is a median 0.11 m, at most 1.8 m, blended back along the run
  over at least 6 m. The junction control point itself is not used: where two routes meet
  nearly end to end it is an ill-conditioned line intersection, up to 4 m off both.
- Approaches end exactly on the OSM bridge ends, since the decks are built from OSM.
- Past the play edge, the line runs straight on, and consumers clip it.

**Layout** (`transport_layout.py`, `build_road_plan.py`):
- The carriageway follows the design lines at template widths. A corridor's half-width can
  change along it, for the tapers.
- Gutter, curb, parkway and walk come from each plan's template. The junction solve, lots,
  overrides and validation are unchanged.
- Design ways are no longer Chaikin-smoothed again.
- Asphalt went from 612,000 to 875,000 m² (+43%), the real widths.
- The roadside now stops at a building face, and every conflict is listed in the layout's
  quality report (`roadside_conflicts`): walk or parkway against 64 building groups (2,250 m², mostly the blocks
  around downtown, where fronts stand close to wider streets), and pavement or curb under 18
  buildings (282 m², 13 and 215 m² before). The pavement cases say a width or an alignment is
  wrong there; they are for review and for template overrides.

**Conformed heightmap.** `build_profiles.conform_strips` samples the design ways, at the
template half-width per sample. So the painted crown, the road mesh and the layout share one
centreline. Route samples past the play edge are dropped: the route ends there, and one sample
took a clamped end station 8 m above the ground and feathered it over the edge rows.

**Vegetation** (`place_vegetation.py`) reads the design roads too. On OSM lines at OSM widths,
its street-tree slots fell on the wider pavement, and only 315 street trees survived. Now there
are 2,888 street trees, and 5,813 trees in all (the committed set has 5,696).

**Found and fixed on the way:**
- `clip_ways_to_bounds` dropped every closed way, because it read "starts where it ends" as
  zero length. Since phase 0, the Shady Lane loop, two service loops and 11 footway and
  pedestrian loops were missing from routes, the conform and the mesh. `build_alignments.py`
  was re-run: 282 routes, 565 junctions.

**Metrics.** `road_metrics.py` now measures along the design lines at template widths, the
surface every consumer builds on. `--osm` measures the old way, and `--surface` measures another
heightmap. Comparing old and new on the same instrument:

| metric | baseline: phase 2 surface, OSM lines and tag widths | phase 2 surface, design lines and template widths | phase 3a surface, design lines and template widths |
| --- | --- | --- | --- |
| junction step p50 / p90 / p99 / max | 0.020 / 0.062 / 0.149 / 0.246 m | 0.021 / 0.062 / 0.148 / 0.234 m | 0.020 / 0.064 / 0.147 / 0.269 m |
| junction steps over 0.10 / 0.25 m | 20 / 0 | 17 / 0 | 21 / 1 |
| grade change in 10 m p50 / p90 / p99 / max | 0.28 / 1.61 / 4.57 / 35.7% | 0.28 / 1.62 / 4.60 / 35.8% | 0.28 / 1.61 / 4.56 / 36.2% |
| cross slope deviation from crown p50 / p90 / p99 / max | 0.32 / 1.05 / 3.13 / 17.7% | 1.44 / 4.57 / 12.8 / 45.2% | 0.24 / 1.19 / 3.66 / 19.8% |
| adverse cross-slope sides | 212 | 4,337 | 309 |
| breaklines | 2 | 3 | 3 |

- The middle column is why the instrument had to change: the phase 2 surface, measured at the
  new curb lines, falls outside its own painted pavement.
- **The ratchet (`test_road_metrics.py`) fails against the phase 2 baseline**. By decision
  (2026-10-18) the baseline stays as it is, and the regressions below are open items for 3b.
  Where the numbers are worse:
  - **Cross slope.** Split at the junctions (a box of the widest leg's half-width plus 1 m):
    - Outside the junctions, the deviation is better or level: p50 0.31 → 0.23%, p90 0.80 →
      0.77%, p99 2.09 → 2.07%. Adverse sides are 36 → 51 of about 16,300 samples. Some are on
      roads that were not built before (the loops). One is a 15.85 m Chuck Vail Drive measured
      from a single block with its centre 1.9 m off the alignment.
    - Inside the junctions, the adverse rate is unchanged at about 15% (173 of 1,192 samples,
      then 261 of 1,694). But the wider templates put 42% more stations inside junction boxes,
      where the crown is undefined until 3b warps it.
  - **Breaklines.** The extra one is the rail-berm drive's designed +32% climb (its phase 2
    PVI override). Measured along the OSM line, 0.5 m off the alignment, it was missed. The
    phase 2 surface shows the same three breaklines on the design lines.
  - **Junction step max.** The step is at a service-road crest at (2381, −1230), which is
    0.25–0.26 m on either surface and either instrument.

**Captures** (`captures/roads/phase3a_templates/`, the phase 2 shots plus a measured residential
block, downtown Galena and a curve): 
- Residential streets are visibly wider, about 32–35 ft. Their curb lines run straight down the
  designed tangents and round the arcs cleanly (Eustace Drive, Upham Place), with asphalt to the
  curb and no gutter strip.
- Downtown Galena's walks run to the building faces.
- At the phase 2 junctions (Carroll, W 8th, Dixon Ave), the returns come off the wider streets,
  and the grass island inside Carroll's junction is down to a few flecks. Street trees are back
  in the parkways.
- **Upham Place** shows the risk of the class-median fallback. At 32 ft, the houses on the
  outside of the curve have their porches at the curb, and the walk is cut away at the building
  faces. Unmeasured streets where houses stand close need a narrower override, or a
  survey that counts more blocks.

**Found, not fixed:**
- Yard trees and foundation shrubs were 0: the baked building hulls in
  `game/buildings/_build/chunk_*.json` are chunk-local, but `place_vegetation.py` read them as
  world coordinates. That was fixed in a separate session, which places them through the bake's
  chunk origins: 6,632 yard trees and 38,686 foundation shrubs. This was unrelated to roads.
- Chuck Vail Drive (R21836045) is 15.85 m wide, from a single counted block whose centre is
  1.9 m off the alignment. It needs a look on the aerial, or an override.

**Left for 3b:**
- Crown warping at junctions, sawtooth gutters, and the TIN surface with daylighting.
- Bring the ratchet back to green against the unchanged phase 2 baseline, on the design-line
  instrument:
  - cross slope: p90 1.19% (baseline 1.05%), p99 3.66% (3.13%), max 19.8% (17.7%), adverse
    sides 309 (212). Mostly inside junctions, where crown warping applies.
  - junction steps: max 0.269 m (0.246 m), 21 over 0.10 m (20), 1 over 0.25 m (0). The one
    over 0.25 m is the service-road crest at (2381, −1230).
  - breaklines: 3 (2). The extra one is the rail-berm drive's designed +32% climb; it needs a
    profile decision there, not a surface fix.

## Decisions (answered 2026-10-18, recorded in `design_standards.json`)

0. **Roads beyond the play heightmap**: clip them to the 2.7 km square, or keep them and give them
   heights from the horizon heightmap.
  ANSWER: Clip.  (Done: roads and rails are cut at the heightmap edge.)
1. **Horizontal tolerance**: how far the design may move a centreline from OSM before a human must
   approve it. The proposal is 1.0 m, or 0.5 m downtown.
   ANSWER: Use these defaults for now.
2. **Design speeds and limits per class**: confirm or adjust the table in §3. Should IDOT BLRS values
   be the hard limits, or only advisory for local streets?
   ANSWER: Advisory only.  Design values are for new designs and cannot account for exsting conditions
3. **Width source**: measure curb-to-curb from the aerial per route (recommended), or adopt
   template defaults by class.
   ANSWER: Measure curb to curb, but defaulting or rounding to a specific precision (e.g. nearest foot) seems like a good idea
4. **Gutter and curb standard**: should the code move from today's 1 ft gutter to IDOT B-6.24 (24 in)
   everywhere, or keep narrower gutters on residential streets?
   ANSWER: In many cases, gutter flags have been overlaid with asphalt and are not visible.  New CC&G is built with 2' flag.  Older gutter is probably 2' as well.  Older curb, however, may oly be 4".
5. **Module granularity**: build the full parametric node library, or start with T and 4-leg
   orthogonal junctions (most of Dixon) and leave the rest curated?
  ANSWER: Start with T and 4-leg
