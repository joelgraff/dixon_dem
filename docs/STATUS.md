# Dixon — Project Status & Resume Guide

Reconstructed 2026-09-20 from the project's docs, git log, and file timestamps after the original design chat was lost
(app froze, forced reboot). Nothing here comes from the chat transcript itself; where the code could not confirm something,
it is marked **unverified**.

**Last commit:** 2026-09-20 15:31 CDT, "Landmarks: fix triangle winding". The last screenshot in `screenshots/` is
`dixon_downtown_aerial.png` (15:59 CDT).
**Uncommitted work exists:** `game/player/player.gd` and `game/world/world.tscn` were modified after the last commit
(15:36 CDT), and `game/project.godot` at 15:33. Run `git status` / `git diff` to see them before doing anything else.
The player spawn in `world.tscn` is currently `(1631.3, 24.2, -1214.2)`, near the Dixon arch.
The player speeds are intact (`WALK 10.4, RUN 30.5, CROUCH 9.9, JUMP 4.0`) and must stay that way.

## What the project is

First-person walkable model of real downtown Dixon, IL, in **Godot 4.6** (Forward+, Jolt), built from USGS 1/9" NED DEMs
and OSM data by a Python pipeline. Art target: The Long Dark crossed with real Midwest urban imagery. Target hardware is an
RX 580 at 60 fps / 1080p. Work was run by an orchestrator plus builder subagents, one per system, each owning one folder.
Docs to read first: `docs/ARCHITECTURE.md`, `docs/BUILDER_PROTOCOL.md`, `docs/ART_DIRECTION.md`, `docs/PLAN_v2.md`.

Play area is about 2.5 x 2.5 km, in a local tangent plane (EPSG:26916). +X is east, +Y is up, -Z is north. Dixon's street
grid is rotated about 16 degrees off true north.

## Timeline (from git)

| When | What |
|---|---|
| Sep 17 | Foundation, WorldState contract, capture harness; data pipeline (DEM + OSM); reference research; materials iter1 |
| Sep 18 | Materials, atmosphere, terrain, roads, buildings, vegetation, player (subagents; one run was cut off by a spend limit) |
| Sep 19 | Terrain iter3, roads iter2/3, vegetation iter2, "buildings invisible" bug fixed |
| Sep 20 AM | You reviewed the model; `PLAN_v2.md` written; tree density cut 2.9x; airborne-depth atmosphere pass, then environment work stopped by your direction |
| Sep 20 PM | Player step-up fix, sidewalk fix, building winding/normals, HUD + minimap + F12 screenshots, Dixon Theatre placement fix, landmark winding fix |

## System-by-system state

**Environment (terrain, atmosphere, water): DONE / frozen.** You called it "more than sufficient." Terrain flatness (PLAN_v2 item 3)
is **deferred indefinitely. Do not spend time on it.** Do not touch `atmosphere` further unless asked.

**Player: DONE.** First-person controller, curb step-up made speed-independent, walk-test and ground-profile tools.
Spawns: `downtown, lincoln_statue, page_park, reagan_home, bridge, bluff_vista`.

**Tooling: DONE (toggleable, hidden during captures).** F7 location/structure readout, F8 minimap, F9 minimap zoom, F10
coords + look vector, F12 screenshot (Shift+F12 hides the HUD) into `screenshots/`. The capture harness supports
`"eye": true` (camera auto-placed at ground + 1.7 m) and `--hide`, `--no-lod`, `--override`. Do NOT hand-guess camera Y: an
underground camera caused two wrong diagnoses on Sep 20.

**Roads: mostly fixed.**
- Sidewalks rendering (was outlines only): FIXED (double-sided slabs, non-collidable skirts). Max step at the arch crossing 0.18 m.
- Pedestrian crosswalk "ledges": FIXED. OSM footway slabs across carriageways are dropped; crossings are paint only.
- Rail grade crossings: **NOT fixed.** `BALLAST_TOP 0.20 / RAIL_TOP 0.50` still run continuously across roads, and the
  crossing patch is placed at `RAIL_TOP + 0.01`, so the track still stands about 0.5 m proud of the pavement (PLAN_v2 6b).
- Bridge continuity (Galena Ave bridge): **appears not fixed (unverified).** Bridge ways are still excluded from the
  road-surface build and decks still use pre-computed Y, with nothing reconciling the abutments (PLAN_v2 item 4).
- Arch junction oddities (sidewalk wedges, grass slivers, huge fan-triangulated junction fill in screenshot 153802): the junction and
  sidewalk fills in `build_road_plan.py` use `fan_fill()` (centroid fan, "roughly star-convex"); about 200 of 919 loops are not
  star-convex and 100 are self-intersecting. An ear-clip fallback did not change that view, so the cause is upstream (loop
  construction). Open.
- Paint: still built as raised ribbons (`y_bias` 0.045). PLAN_v2 item 6 asked for flush paint; not confirmed done.

**Buildings: root causes found and fixed in the pipeline (2026-09-20 evening) - NEEDS REBAKE + EYE-HEIGHT CHECK.**
The earlier "facade area budget" diagnosis in this file was **wrong** (it came from triangle counts, not surface area). What
was really wrong, all fixed in Python/shader source and checked with an offline software rasterizer against your screenshots:
- **Inside-out geometry.** `MeshBuild._orient` emitted walls and roof caps with the wrong winding for Godot (front = clockwise),
  so buildings rendered hollow and flat roofs looked like pyramids. Replaced by `_resolve()`: decide the outward normal, then emit the
  index order whose cross product opposes it. Verified: 0 wrongly wound vertical or upward faces.
- **Half-culled gable roofs.** `build_gable_roof` produced bow-tie quads; `add_quad` now repairs them.
- **Empty lot north of the theatre / missing First Baptist Church and Reagan outbuildings.** `build_building_plan.py` skipped every
  OSM footprint near any landmark. It now skips only the ids in `LANDMARK_OWNED_IDS`.
- **Vertical brick striping.** `surface.gdshader` derived module phase from world x/z, so walls ran through the module grid at
  glancing angles. Vertical faces now use distance along the wall plus world y.
- **Floating buildings on slopes.** New `facade.terrain_skirt()` and `pick_ground()` bury foundations into the terrain.
- **Houses vs commercial in the fringe.** `classify.py`: 350 m2+ generic footprints become `strip_commercial`.
- **Positions.** OSM footprints already match your Earth aerial to about 1-2 m, so "positioning" was mostly the bugs above. One
  missing building was added by tracing (`aerial_trace.py` -> `game/data/buildings_curated.json`, south of the theatre tower).
  The houses west of Peoria/Hennepin (aerial x < 690 px) are NOT in OSM; infill is disabled inside the aerial so the fringe is empty
  rather than wrong. They need tracing from a sharper aerial or a footprint file.
- **Aerial georeference** (in `classify.py`): 3.0 px/m, arch centroid world (1631.3, -1214.2) at px (758, 450), bearing 344 deg,
  north is to the right and east is down in the image.
- **Rebake** (generated chunks are not committed): `cd pipeline/buildings && ../../.venv/bin/python aerial_trace.py && ../../.venv/bin/python build_building_plan.py`,
  then `~/AppImage/Godot_v4.6-stable_linux.x86_64 --headless --path game --script res://buildings/tools/build_buildings.gd`.
- Not verified inside Godot (the cloud session cannot run it). Facades reading dark may partly remain; re-screenshot after the
  rebake before doing any facade design work.

**Landmarks: winding fixed (last commit), still first-pass.** Courthouse, Dixon arch complex, Lincoln statue, theatre, Reagan
boyhood home, Nachusa House. Known open items:
- `signage()` hardcodes `CULL_DISABLED`, giving mirrored ghost text on back-to-back signs (arch crown, marquee).
- The theatre landmark scene is placed at (1629.2, -1336.9); `docs/pipeline_notes.md` lists a different, wrong position.
- Reagan/Nachusa roof shingle/slate UV scale is 3-4x too fine (`face_size_m` needs `Vector2(1,1)`; Nachusa should use
  `use_world_uv=false`).
- Re-base everything on your 17 photos in `references/`; they override the agent-gathered set, especially courthouse and
  Reagan home.
- Lincoln statue figure is thin and cone-like; dam massing is low-confidence (no close reference photo).
- No proper capture pass has been done yet from `world.tscn` (earlier cameras clipped into the geometry).

**Vegetation: needs one more pass.**
- Trees cut from 16,987 to 5,914 (`TREE_DENSITY_SCALE 0.28`), but the courthouse lawn is still about 60% screened.
  Next lever is **crown radius**: cut 25-30% for park/lawn/yard trees and thin park/cemetery scatter, then re-measure at the
  same three cameras.
- Better tree shaders (leaf-card atlas, back-lit translucency, bent normals, wind, impostors) still to do.
- Performance: measured 33-37 fps at the worst vantage (S Hennepin), **below the 60 fps target**, under GPU contention. Needs a
  clean re-measure via `perf_probe.tscn`. If still low, cut leaf clusters per tree.
- Unverified: the far-LOD billboard height fix, and an unexplained bad residential-street frame.
- Grass colour improved but not converged (about 30% low on saturation).

## Suggested next steps, in order

1. `git status` / `git diff` and commit or discard the uncommitted `player.gd` / `world.tscn` / `project.godot` changes.
2. **Rebake buildings and re-shoot the same screenshots** (see the Buildings section), then decide what is left.
3. **Rail grade crossings** flush with pavement, then **bridge deck/approach continuity**, then flush paint markings.
4. Landmarks: fix cull_mode and roof UVs, do a proper eye-height capture pass from `world.tscn`, re-base on `references/`.
5. Vegetation: crown radius cut, re-measure canopy coverage, clean perf measurement.
6. Building facade design pass, then tree shader upgrade.

## Process rules that came out of the bugs

- Winding/orientation was the single most common failure (roads, building meshes, landmark meshes all hit it separately). Any
  new mesh generator needs a "renders from eye height from both approaches" check before it is called done.
- Every workstream verifies in `res://world/world.tscn` at 1.7 m eye height with a `--hide=<own system>` control, never only
  in its own test scene.
- Only the orchestrator edits `world/world.tscn` node transforms.
- Captures are serialised by a GPU lock; launch detached with a marker file (see `BUILDER_PROTOCOL.md`).

## Recovering the chat itself

If this was a Claude Code session, run `claude --resume` from `~/Projects/dixon_dem` and pick it from the list. Session logs
live under `~/.claude/projects/`, which cannot be read from a cloud session because that location is protected.
