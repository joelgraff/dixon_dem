# Footprints traced on the shifted aerial: audit (2026-10-18)

Until 244755b, `pipeline/aerial/georef_affine.py` ignored the image server widening non-square
requests, so Composer's footprint backdrop (`/game-aerial`, live since 75dc243 on 2026-09-30)
drew the 2025 aerial off by:

| tiles | old backdrop error (median / 90th pct / max) |
|---|---|
| 25 full 512 m tiles (the town) | 7.8 / 13.8 / 14.5 m, almost all north-south |
| 11 edge strips, 140 m wide (x or z beyond 2560 / -140) | 85 / 176 / 236 m: unusable for tracing |

## Result: no footprint data was traced on it

- **No footprint overrides exist.** The footprint editor's write-back (`POST /game-footprint/<id>`,
  `game/data/footprint_overrides/`, step 5 of building-composer's `docs/FOOTPRINT_EDITING_PLAN.md`)
  was never built. `composer_server.py` has no such route, the directory does not exist, and no
  downloaded `dixon-footprint-override` file was found in ~/Downloads, ~/Desktop or ~/Documents.
- **No composed buildings exist** (`game/data/composed/` is absent).
- `game/data/building_overrides.json` holds style hints only, no geometry.
- `exports/composer/115768678.json` and `800001099.json` are game exports, identical to the OSM
  and Microsoft footprints with those ids. They were not traced.
- `game/data/buildings_curated.json` (`990000001`) was traced on 2026-09-20 from a Google Earth
  screenshot through `classify.aerial_px_to_world`, not from the il2025 tiles, so this bug did not
  affect it.

Nothing needs moving because of the georef bug.

## The three footprints against the corrected aerial

Yellow is the footprint, cyan the neighbouring OSM/MS/curated outlines. Left is the old backdrop,
right the corrected one.

| id | old backdrop error here | fit on the corrected aerial |
|---|---|---|
| 115768678 (OSM) | 11.3 m N-S | on the roof |
| 800001099 (MS) | 11.4 m N-S | on the house, within ~1-2 m (tree cover) |
| 990000001 (curated) | 2.2 m | **covers a parking lot, not a building**; overlaps the white-roofed building to its east by ~2 m |

![115768678](footprint_115768678.png)
![800001099](footprint_800001099.png)
![990000001](footprint_990000001.png)

**990000001 is the one to decide on.** The 2025 aerial has no building there. Either the Google
Earth image was older and the building is gone, or the trace landed in the wrong place. Options:
delete it, or retrace it if it exists in other imagery.

## Composer server restart: yes

`aerial_crop.Aerial` reads `data/raw/il2025/index.json` once and keeps it in `_index`. The running
server (`composer_server.py --port 8001`, started 2026-10-18 08:04) predates the regenerated
georefs (17:47), so it still serves the old, shifted placement until it is restarted. (The
`/game-footprints` cache reloads on its own when the source files change.)

# Buildings on the street: what is left (2026-10-19)

`street_overlaps.{json,png}` are written by `pipeline/buildings/encroachment.py --review` (run it
after `rebuild_transportation.sh`). Of the 45 baked buildings that stood on the carriageway,
12 remain; `manual_review` in the JSON lists the 9 worth a look, each with what to check:

| id | where | why it is listed |
|---|---|---|
| 800000171 (MS) | Madison Ave, 1170,-1332 | blob over a dirt lot (and the OSM building in it): no roof |
| 444853744 (OSM) | Madison Ave, 1156,-1287 | bare dirt lot: demolished? |
| 800000460 (MS) | W 9th St, 1376,-413 | lawn/trees, on a paper street |
| 800000699 (MS) | Upham Pl, 919,-2034 | mostly lawn (tree cover?) |
| 800001874 (MS) | Harrison Ave, 516,-462 | green metal roof (real); Harrison's alignment is ~1.5 m off the pavement |
| 800002396 (MS) | Shady Lane, 467,-2335 | real house; Shady Lane's west leg runs ~3 m south of the pavement |
| 800001014 (MS) | parking lot, 1500,-1316 | flagged bare; a drive was cut for it |
| 1013602982 (OSM) | 1768,-626 | flagged lawn; a drive was cut for it |
| 800001590 (MS) | W 9th St, 1973,-581 | flagged lawn (a driveway tail); the curb was trimmed round it |

Deleting a footprint that is not there brings the drive or curb back on the next rebuild. The
other 5 rows are `hull`: concave OSM/MS buildings whose convex collision hull (not the
footprint) reaches a drive (444853753, 554476797, 444853723, 800001402, 554473435), and one
0.6 m2 `eave`.
