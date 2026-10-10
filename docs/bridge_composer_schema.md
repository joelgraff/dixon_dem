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
    "width": 16.4,                 // out to out, metres
    "thickness": 0.3,              // slab thickness; girder/slab spans use their own depth
    "elevation": [[station, y], ...]   // deck top, absolute game Y, increasing stations;
                                       // linear between rows, held flat beyond the ends
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

  "cross_section": {
    "barrier_h": 0.9,              // concrete barrier at each edge
    "barrier_w": 0.4,
    "sidewalk_w": 2.5,             // each side; 0 = none. Raised 0.15 m with a kerb
    "rail_h": 0.9                  // steel rail above the barrier; 0 = none
  },

  "lamps": { "spacing": 25.0 },    // optional: lamp_downtown furniture on both edges

  "materials": { "deck": "bridge_deck" }   // optional role -> road material name
}
```

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
- `GET /game-bridges` — `{"bridges": [{id, name, highway, width_m, centerline, deck_y, ground, ground_profile, composed}]}`; `ground` is the terrain height at the two ends, `ground_profile` is `[[station, y], ...]` about every 5 m
- `GET /game-bridge/<id>` — the saved design, 404 if none
- `POST /game-save-bridge/<id>` — body is the file; same-origin + `X-Composer: 1`, validated, written atomically

Reused from Building Composer's endpoints: `/game-materials`, `/game-aerial`.

## Not yet in version 1
Wing walls, spandrel openings, pier caps, girder cross-bracing, a bridge over another road's
carriageway (terrain/road carving), rail bridges (built by the rails pass), per-span materials.
