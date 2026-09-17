# Dixon data pipeline

Turns the USGS NED19 DEM tiles + OpenStreetMap into everything under
`game/data/` that the other workstreams (terrain, roads, buildings,
landmarks, vegetation) consume. Owned by the data-pipeline workstream; only
this workstream should write to `pipeline/`, `data/raw/`, `game/data/`.

## Rerunning

```
cd pipeline
../.venv/bin/python build_all.py            # regenerate everything
../.venv/bin/python build_all.py --force-fetch   # also re-download OSM data
```

`build_all.py` runs, in order:

1. `fetch_osm.py` -- downloads OSM data for the play area + 500m margin from
   the Overpass API into `data/raw/osm_*.json`. Idempotent: skips a category
   whose JSON already exists unless `--force` (or `build_all.py
   --force-fetch`) is passed. Polite: 4 requests total (roads+rails,
   buildings, water+landuse, points), retried with backoff on server-busy.
2. `build_heightmap.py` -- reads the two NED19 tiles that cover the AOI,
   reprojects to EPSG:26916 with `rasterio.vrt.WarpedVRT`, and writes:
   - `game/data/world_origin.json`
   - `game/data/heightmap_play_1m.r32` (resampled + hydro-flattened river)
   - `game/data/heightmap_play_1m_road_conformed.r32` (same + road corridors carved)
   - `game/data/heightmap_horizon_12.5m.r32` (coarse 10x10km surround)
   - `game/data/_water_reaches_utm.json` -- **internal** intermediate file
     (river/pond reach polygons in UTM + pool levels), consumed by
     `build_vectors.py`. Not part of the public data contract for other
     workstreams.
3. `build_vectors.py` -- reads `data/raw/osm_*.json` plus the heightmaps just
   built, and writes the per-layer JSON files: `roads.json`, `rails.json`,
   `buildings.json`, `water.json`, `landuse.json`, `pois.json`, `trees.json`,
   `lamps.json`, `bridges.json`.
4. `render_preview.py` -- hillshades the heightmaps and overlays the vector
   layers, writing PNGs to `captures/pipeline/` for visual QA.

Runtime: ~20s total on a warm cache (OSM fetch is the only slow/flaky step,
each Overpass query can take 10-60s including retries).

## Coordinate system

Everything in `game/data/*.json` is in **Godot local space**: `x` = east
(meters from `origin_easting`), `z` = `-(northing - origin_northing)`
(south is +Z... i.e. north is -Z), `y` = `elevation_m - base_elevation_m`.
The UTM zone is EPSG:26916 (NAD83 / UTM 16N), matching `docs/ARCHITECTURE.md`.
`game/data/world_origin.json` records the origin, base elevation, heightmap
dimensions/spacing, and the flat pool elevation of each river/pond reach.

The play area is **2700 x 2700 m** (brief said "~2.5 x 2.5km" -- widened
slightly so a clean, integer-meter UTM square comfortably contains every
required landmark with margin; see "Play-area sizing" below).

## Heightmap file format

`.r32`: raw, headerless, **float32 little-endian, row-major**, row 0 = the
**north** edge of the grid (max northing), column 0 = the **west** edge (min
easting). Value at each pixel = `elevation_m - base_elevation_m` (i.e.
already Godot-local Y). Dimensions/spacing/origin for each grid are recorded
in `world_origin.json["heightmaps"]["play"|"horizon"]`. To load in Godot:
read the buffer as a `PackedFloat32Array` (or straight bytes), reshape to
`(height, width)`, and note that increasing row index = increasing -Z
(moving north across the grid decreases row index).

- `heightmap_play_1m.r32` -- 2700x2700 @ 1m. Bicubic-resampled from the
  ~3m NED19 DEM, then **hydro-flattened** (see below). This is "the raw one"
  in the sense of not being road-conformed; it still has the river flattened.
- `heightmap_play_1m_road_conformed.r32` -- same grid, plus road corridors
  carved flat (~2% camber, smooth grades). Bridges are excluded (left as
  whatever the raw/hydro-flattened surface underneath is, since a bridge
  deck spans above the terrain rather than following it).
- `heightmap_horizon_12.5m.r32` -- 800x800 @ 12.5m, 10km x 10km, same
  origin/center as the play area, average-resampled, lightly hydro-flattened.
  For distant terrain only.

### Hydro-flattening

Rock River (and a few small ponds) polygons are assembled from OSM
`natural=water` / `waterway=riverbank` ways and relations. The Dixon Dam is
used to split the main river polygon into two reaches via a **raster
half-plane test** (fit the dam's dominant crossing direction with PCA over
all its vertices, then classify every pixel by which side of that line it's
on) -- `shapely.split()` on the vector polygon proved unreliable here because
the dam is mapped as two disjoint, zigzagging ways whose merged path's first
and last coordinates can coincide (degenerate direction vector). Each
resulting reach gets a flat pool elevation (15th percentile of raw DEM values
sampled >=6m inside the polygon, to dodge bank/vegetation noise), and a
riverbed carved 0-3m below that pool (via a distance-from-bank transform)
for the water shader to sit on top of. Reach pool elevations found for this
dataset:

| reach | pool elevation (m, NAVD88ish) | local Y |
|---|---|---|
| river_upstream (north of dam, may export as multiple ring pieces -- see below) | 197.92 | 5.92 |
| river_downstream (south of dam) | 195.54 | 3.54 |
| pond (near Page Park) | 198.46 | 6.46 |
| pond (Van Arnam Island's inner lagoon) | 197.93 | 5.93 |
| pond (retention pond, north edge of AOI) | 212.38 | 20.38 |

The ~2.4m upstream/downstream difference across the dam matches the brief's
expected 2-3m.

**Islands**: Van Arnam Island and the Willow Park islet (both OSM
`place=island`/`place=islet`) are explicitly subtracted from the river
polygon before hydro-flattening, so their terrain keeps raw DEM elevation
(natural bank slope down to the water) instead of being flattened/submerged.
The subtraction is applied only to the big national river *relation*
polygon (which lacks a proper inner-ring hole for the islands within our
AOI clip -- the actual bug), never to individually-mapped `natural=water`
*way* features such as Van Arnam's own inner lagoon/pond, which stays intact
as its own flat-pool reach. A reach whose polygon gets split into disjoint
pieces by an island (e.g. `river_upstream` splits into channel arms on
either side of Van Arnam Island) is exported as multiple ring entries
(`river_upstream_0`, `_1`, ...) sharing one pool level.

### Road-conforming

For every non-bridge `highway=*` way: sample raw elevation at 2m intervals,
smooth along arc-length with a 15m moving average (removes DEM noise/bumps
so grades read as smooth), then for every heightmap pixel within
`half_width + 1.5m` of the smoothed centerline, look up the nearest sample
(via a `scipy.spatial.cKDTree`) and apply a ~2% camber (drop proportional to
lateral distance from centerline, capped at the roadway edge) for drainage
crown. The last ~2m of the buffer is feathered (smoothstep) back to the raw
surface to avoid a hard seam at the shoulder.

### Bridge deck heights

Sampling the DEM right at a bridge way's OSM endpoint is unreliable: those
nodes are frequently placed right at the mapped waterline, and a bare-earth
LIDAR DEM reads near-water elevation there, not the true abutment height. So:
if a bridge crosses within 250m of a hydro-flattened water reach, its deck is
set to **that reach's pool elevation + a fixed design clearance** (7.5m for
motorway/trunk/primary, scaled down for lesser road classes -- see
`BRIDGE_CLEARANCE_M` in `build_vectors.py`), applied flat across the whole
span. Otherwise (e.g. a rail viaduct over a dry ravine, not water) it falls
back to sampling terrain 12m in from each true endpoint. The Galena Ave
bridge comes out at local Y 13.42, i.e. **7.5m above the adjacent pool** --
within the brief's 6-10m target.

## Vector JSON schemas (all in game/data/)

All files are `{"<key>": [...]}`. Coordinates are `{"x":.., "y":.., "z":..}`
(vertices) or `{"x":.., "z":..}` (2D footprint/polygon rings, CCW). Optional
`"landmark_id"` appears on the feature matching one of: `lee_county_courthouse`,
`dixon_theatre`, `reagan_boyhood_home`, `nachusa_house`, `lincoln_statue`,
`dixon_arch`, `galena_bridge`, `dixon_dam`.

- **roads.json**: `{"ways": [...], "junction_nodes": [...]}`. Each way has
  `id`, `vertices` (with per-vertex sampled Y from the road-conformed
  heightmap, or interpolated deck Y for bridges), and `tags` (`highway`,
  `name`, `lanes`, `width_m`, `oneway`, `bridge`, `layer`, `surface`,
  `sidewalk`). `junction_nodes` are OSM node ids referenced by >=2 highway
  ways (i.e. intersections) with their Godot position -- for the roads
  workstream to build junction geometry.
- **rails.json**: `{"ways": [...]}`, same vertex/tag shape, railway tags.
- **bridges.json**: `{"bridges": [...]}` -- every `bridge=yes` road or rail
  way (duplicated from roads.json/rails.json for convenience), each with a
  `"kind"` of `"railway"` when applicable.
- **buildings.json**: `{"buildings": [...]}`. Each has `footprint` (CCW
  polygon), `ground_y_min`/`ground_y_max` (raw terrain under the footprint),
  `height_m` (derived estimate, see below), `tags` (name/building/amenity/
  levels/height/roof/material), and `landmark_id` where applicable.
- **water.json**: `{"reaches": [...], "streams": [...], "dams": [...]}`.
  `reaches` are the flat hydro-flattened polygons with a single `surface_y`
  each. `streams` are minor waterway lines (not flattened) with per-vertex Y.
  `dams` are the dam way(s) with per-vertex Y and `landmark_id: dixon_dam`.
- **landuse.json**: `{"areas": [...]}` -- landuse/leisure/natural polygons
  (parks, grass, wood, etc.), tags passed through, no elevation (drape on
  terrain at render time).
- **pois.json**: `{"points": [...], "barrier_lines": [...]}`. `points` are
  amenity/historic/tourism nodes (and `man_made=bridge` structures, and
  point-like barrier nodes e.g. gates/bollards), with sampled ground Y.
  `lincoln_statue` and `dixon_arch`-adjacent points are tagged.
  `barrier_lines` are `barrier=*` **ways** (fences, walls, the one mapped
  riverbank `retaining_wall`) kept as full per-vertex polylines with sampled
  ground Y -- these used to be collapsed to a single centroid point, which
  loses the shape entirely for anything linear.
- **trees.json** / **lamps.json**: `{"points": [...]}`, `natural=tree` /
  `highway=street_lamp` nodes with sampled ground Y. **lamps.json is empty**
  for this AOI -- Dixon's street lamps simply aren't mapped in OSM (see Known
  issues).

### Building height_m estimate

`height`/`building:height` tag (parsed) > `building:levels`/`levels` tag
(x3.0m/level residential, x3.8m/level otherwise) > heuristic fallback by
`building` tag: garages/sheds 3m, houses 5.5m (~1.5-2 storeys), churches/
schools/courthouses/large footprints (>600m^2) `clip(6 + area/200, 8, 24)`,
generic commercial/retail/office/unlabeled 10m (~2.5 storeys), else 7m.

## Play-area sizing

Landmark coordinates were surveyed directly from OSM via Overpass (not
guessed) on 2026-09-17. The brief's suggested center (41.8445N, -89.4795W)
was a rough approximation; actual landmark positions cluster further west/
south of that. A clean square origin was chosen in UTM 16N such that every
required landmark sits inside with margin:

- `origin_easting = 292300`, `origin_northing = 4634000`, `size_m = 2700`,
  i.e. the play-area box is `[292300, 4634000]` to `[295000, 4636700]` in
  UTM 16N meters (a 2700 x 2700m square, slightly larger than the brief's
  "~2.5 x 2.5km" so it comfortably contains every required landmark).

(See `pipeline/common.py` for the exact numbers and the landmark survey
comment above `ORIGIN_EASTING`/`ORIGIN_NORTHING`.) Margins range from ~25m
(Van Arnam Island's NE tip) to several hundred meters (most other
landmarks); Page Park's far west tip (a golf/fairgrounds area away from the
school) falls slightly outside the play-area square but is still covered by
the OSM fetch margin and the horizon heightmap.

## Known issues / uncertainties

- **(Fixed 2026-09-17, orchestrator review)** Van Arnam Island and the
  Willow Park islet were initially missing -- the river polygon covered them
  solid, so their terrain got flattened/submerged and the reach polygons
  exported for `river_upstream`/`river_downstream` were the whole undivided
  river rather than each side's actual half. Both are fixed; see "Islands"
  above and the "Hydro-flattening" section for how the dam-side split now
  works (vector half-plane intersection instead of only a raster mask).
- **Nachusa House** is not address-tagged in OSM (only "Nachusa Avenue", an
  unrelated street, matched a name search). Its position was **interpolated**
  by linear-interpolating address numbers along S Galena Ave between the
  Dixon Theatre (114 S Galena) and a tagged building at 619 S Galena, which
  lands very close (~2m) to a real unnamed building footprint next to the
  Dixon Memorial Arch -- that footprint was assigned `landmark_id:
  nachusa_house`, but this is a best-effort guess, not a verified address
  match. Worth spot-checking against a real map/photo if precision matters.
- **lamps.json is empty** -- no `highway=street_lamp` nodes exist in OSM for
  this area. The landmarks/vegetation workstreams will need to place lamp
  posts procedurally along sidewalks if desired.
- **Van Arnam Island** and the **westernmost part of Page Park** extend
  slightly past the 2700m play-area square (by ~25m and ~300m respectively,
  in different directions); both are still present in the OSM vector data
  (fetched with a 500m margin) and the horizon heightmap, just outside the
  "core" 1m play heightmap.
- Bridge deck elevations for **non-water-crossing** bridges (e.g. the "Illinois
  Central Stone Arch Railroad Bridges" viaducts south of downtown, which
  cross a ravine/street, not the river) still use DEM-sampling with a 12m
  inset from each endpoint -- reasonable but not as robustly validated as the
  water-crossing case.
- The horizon heightmap's hydro-flattening reuses the same reach polygons
  computed for the play area; ponds/river segments further out (beyond
  ~1350m from center) are not flattened and will show raw DEM noise if the
  river continues into the horizon ring in a way the AOI-clipped polygon
  doesn't cover.
- DEM source is 2008-2009 USGS NED19 (bare-earth LIDAR, ~3m posts, vertical
  units confirmed meters, NAD83 horizontal / DEM's native vertical datum,
  presumed NAVD88 per USGS NED convention -- not independently re-verified).
  Any construction since 2009 (new buildings, regraded lots) is obviously not
  reflected in terrain, only in whatever OSM has mapped.
