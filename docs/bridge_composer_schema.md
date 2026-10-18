# Bridge Composer file format (`dixon-bridge`, version 1)

A bridge designed in Bridge Composer is one JSON file, `game/data/bridges_composed/<way id>.json`,
keyed by the OSM way id of the bridge in `game/data/bridges.json`. `pipeline/roads/bridges_composed.py`
builds it in place of the flat deck the road plan generates for that way, and
`pipeline/roads/seed_bridge.py <way id>` writes a starting design from the way as it is today.

Unlike a composed building (`dixon-composed`, which ships a baked mesh), a bridge file carries the
**design**: the pipeline generates the mesh. Composer's preview mirrors the rules below; the geometry
the game shows is whatever `bridges_composed.build` makes, so there is one source of truth.

Units are Godot metres: x east, z south, y up (the same as `bridges.json`, `roads.json`). A **station**
is metres along the centreline from its first point. The first station is 0, the last is the
centreline's length.

## Fields

```jsonc
{
  "format": "dixon-bridge",
  "version": 1,
  "id": "114082270",               // the OSM way id, as a string; must match the file name
  "name": "Galena Avenue Bridge",  // optional, for the editor

  "centerline": [[x, z], ...],     // 2..500 points, game metres, in travel order

  "deck": {
    "width": 16.4,                 // the ROADWAY, between the barriers, metres; walkways and parapets are outside it
    "thickness": 0.3,              // slab thickness; girder/slab spans use their own depth
    "elevation": [[station, y], ...],  // deck top, absolute game Y, increasing stations;
                                       // linear between rows, held flat beyond the ends
    "profile": { "kind": "crest", "start": 8.51, "end": 8.0, "crest": 0.5 }
        // optional, editor-only: how the rows were made, so the crest can be changed later.
        // The reader uses only `elevation`. See "Vertical profile" below.
  },

  "supports": [                    // at least two, increasing station;
    { "kind": "abutment", "station": 0.0, "length": 1.5 },        // first and last
    { "kind": "pier", "station": 41.4, "length": 1.4,             // must be abutments
      "width": 6.0, "shape": "bullnose", "bottom": 2.1 },
    { "kind": "abutment", "station": 207.1 }
  ],

  "spans": [                       // exactly one per gap between supports
    { "type": "girder", "depth": 0.9, "haunch": 0.5 },
    { "type": "arch", "rise": 4.0, "ring": 0.6, "springing": 8.2 }
  ],

  "cross_section": {              // outward from the roadway, each side: barrier, walkway, parapet
    "barrier_h": 0.9,              // concrete safety barrier between roadway and walkway
    "barrier_w": 0.4,              //   (the edge element where there is no walkway)
    "barrier_rail_h": 0.35,        // steel rail on the barrier when there is a walkway; 0 = none
    "barrier_rail_style": "pipe",  // railing styles: "ribbon" | "panel" | "pipe" | "picket" (see Railings)
    "walkway_w": 2.5,              // each side; 0 = no walkways
    "walkway_sides": "both",       // "both" | "left" | "right" (left of travel is +)
    "walkway_rise": -0.035,        // surface above the deck top; -0.035 is level with the approach sidewalk
    "outer_type": "metal",         // outer edge: "parapet" (concrete wall, rail on top) | "metal" (low curb, all-metal railing)
    "parapet_w": 0.3,              // width of the parapet wall or the curb
    "parapet_h": 0.6,              // parapet wall height above the walkway surface ("parapet" only)
    "curb_h": 0.2,                 // curb height under the railing ("metal" only)
    "rail_h": 1.05,                // railing height above the parapet/curb (above the barrier with no walkway)
    "rail_style": "picket"         // style of the outer railing
  },

  "lamps": { "spacing": 25.0 },    // optional: lamp_downtown furniture on both edges

  "materials": { "deck": "bridge_deck" }   // optional role -> road material name
}
```

### Cross-section
From the centreline out, each side: roadway (`deck.width / 2`), a barrier (`barrier_w`), a walkway
(`walkway_w`, when enabled for that side) and a parapet (`parapet_w`) carrying the outer railing.
The overall width is the roadway plus those, so the girders, soffit, fascia and abutments span all of
it. The roadway surface is `deck` material, the walkways `sidewalk`, the barriers and parapets
`barrier`, the structure underneath `structure` (or `arch`), the rails `rail`. Lamps stand on the
walkway 0.35 m inside the parapet (on the barrier with no walkway).

A walkway has to meet the sidewalks the road plan lays up to each end. `GET /game-bridges` reports
them as `approach_sidewalks` -- `[start, end]`, each `{"left": [inner, outer], "right": [...]}` as
lateral offsets from the centreline, measured by cutting the transportation layout's sidewalk polygons
4, 8 and 12 m beyond the abutment -- and Bridge Composer's **Match approach sidewalks** sets the barrier
gap and walkway width from them. The two ends of a bridge can differ (downtown 3.6 m, residential
1.7 m behind a 2 m parkway); a bridge has one cross-section, so the match is a compromise.

### Railings
Each railing is `rail_h` (or `barrier_rail_h`) tall above its base and has a style:

| style | what is built |
| --- | --- |
| `ribbon` | one thin steel band at the top (the cheap default for files without a style) |
| `panel` | a solid steel fence, full height |
| `pipe` | posts every 2.4 m, a top rail and a mid rail |
| `picket` | posts every 2.4 m, top and bottom rails, and 25 mm pickets every 0.25 m |

The Galena Ave Bridge (photos): a concrete safety barrier with a `pipe` rail on it between roadway and
walkway, and an all-metal `picket` railing on a low curb at the outer edge (`outer_type: "metal"`), not a
concrete parapet. Railings are `rail` material, not collidable.

### Vertical profile
Highway practice prefers a long, smooth vertical curve to a short steep ramp. Bridge Composer's
**Match approaches** sets the two end heights to the street heights 50 ft out from each abutment
(`approach_y` from `GET /game-bridges`, the road surface heights read before roads are conformed) and builds the rows as
the straight line between them plus a parabola `crest` high at midspan
(`bridges_composed.crest_profile`, mirrored by `crestProfile` in the editor). The grade eases
continuously end to end: on Galena (207 m, ends 8.51 / 8.0, 0.5 m crest) the steepest run is 1.2%,
where ramping to a flat design height used 8% over 6 m. The crest is the deck's camber; the
default 0.5 m is an estimate (the real rise at the Galena Ave Bridge is not documented) and is
meant to be adjusted. `pipeline/build_heightmap.py` raises the approach roads that end at a
composed bridge to the deck's end heights (the terrain under them is `ROAD_SURFACE_M` = 0.085 m lower,
as roads sit above terrain), blending back to the ground over 40 m, so the roads meet the deck.

### Supports
| field | meaning | default |
| --- | --- | --- |
| `kind` | `abutment` or `pier` | required |
| `station` | where it stands | required |
| `length` | thickness along the bridge | 1.5 |
| `width` | across the bridge | abutment: deck width; pier: 70% of it |
| `shape` | `rect` or `bullnose` (half-round ends, piers only) | `rect` |
| `bottom` | Y of its foot | terrain height at the support, minus 0.5 |

An abutment is a back wall that sits just past the end of the deck and carries it. A pier rises to the
underside of the span(s) it carries.

### Spans
| `type` | fields | what is built |
| --- | --- | --- |
| `girder` | `depth` (0.9), `haunch` (0) | a fascia and soffit `depth` under the deck; `haunch` adds depth that tapers away from each support (cosine), for the scalloped look |
| `slab` | `depth` (0.9) | the same, for a plain concrete slab |
| `arch` | `rise`, `ring` (0.6), `springing` (optional) | a circular-segment barrel; the sides are closed spandrel walls from the intrados up to the deck. The crown sits `ring` + 0.3 m under the deck |

### Materials
Roles: `deck`, `sidewalk`, `barrier`, `structure` (girders, piers, abutments), `rail`, `arch`.
Names must be in `bridges_composed.MATERIALS`, the road bake's set: `bridge_deck`, `curb_concrete`,
`sidewalk_concrete`, `asphalt_road`, `steel_rusted`, `stone_foundation`, `limestone`, `gravel_ballast`.
(There is no painted-green steel in the road bake yet; railings use `steel_rusted`.)

## Rules the reader enforces
- `format` and `version` must match; a file that fails validation is ignored (the generated deck is used).
- The first and last supports are abutments; spans count is supports − 1.
- A support with no height (its foot is at or above the deck's underside) is skipped with a warning.
- Warnings are printed by the road plan: deck elevation at either end differs from the ground by more
  than 0.6 m (**the approach road will not meet the deck** — road approaches are built at terrain
  height; adjust the elevation rows so the deck ramps to the ground, as `seed_bridge.py` does).

## Winding
Every surface is emitted single-sided, wound for Godot (front face clockwise) with its vertex normal the
way it looks. The deck top, soffit, and each side face are separate surfaces. `test_bridges_composed.py`
asserts this for every triangle, because the old generated deck was single-sided with the wrong winding
and read as invisible from above.

## Server (`game/tools/composer_server.py`)
- `GET /game-bridges` — `{"bridges": [{id, name, highway, width_m, centerline, deck_y, ground, ground_profile, composed}]}`; `ground` is the terrain height at the two ends, `ground_profile` is `[[station, y], ...]` about every 5 m, from -`approach_m` to length + `approach_m` (50 ft either side)
- `GET /game-bridge/<id>` — the saved design, 404 if none
- `POST /game-save-bridge/<id>` — body is the file; same-origin + `X-Composer: 1`, validated, written atomically

Reused from Building Composer's endpoints: `/game-materials`, `/game-aerial`.

## Not yet in version 1
Wing walls, spandrel openings, pier caps, girder cross-bracing, a bridge over another road's
carriageway (terrain/road carving), rail bridges (built by the rails pass), per-span materials.
