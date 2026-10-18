# Roadway horizontal and vertical control: plan

Status: proposal, 2026-10-18. Phase 0 is built (see Phase 0 results); the rest is not.

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
| 1 | Routes, stationing, horizontal fit, OSM-deviation report; aerial curb-to-curb width survey per route | none (data only); review deviations in a debug overlay |
| 2 | Network vertical solve with shared junction elevations and fixed controls; `road_conform` reads design profiles instead of per-way moving averages | junction steps gone, grades smooth; the biggest win for the smallest change |
| 3 | Cross-section templates on station ranges; crown warping at junctions; TIN-based conformed heightmap with daylighting | real lane, parking and gutter widths; clean curb lines |
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
