# Player workstream notes

Owns `game/player/`. Reads `TerrainHeight` (`res://terrain/terrain_height.gd`,
read-only) for ground-level spawn placement. Adds `Player` as a child of
`world/world.tscn` (shared file -- minimal edit: one `ext_resource` + one
`[node]` line, appended after the existing `Roads` node).

## What exists

```
game/player/
  player.tscn / player.gd     CharacterBody3D first-person controller
  spawn_points.gd             named spawn locations + --spawn=<name> cmdline
  test_player.tscn / .gd      standalone test scene (atmosphere + terrain + player)
```

## Controls

| input | action |
|---|---|
| Mouse | look (captured by default outside capture mode) |
| W A S D | walk |
| Shift (held) | run |
| Ctrl (held) | crouch |
| Space | jump (coyote time + jump buffering, ~0.12s each) |
| Esc | release mouse; click to recapture |
| F1 | key-command help |
| F5 | cycle season |
| Shift+F5 | toggle noclip/free-fly |
| F2 | cycle weather |
| F3 / F4 | hour back / forward |
| F6 | toggle on-screen debug readout (position, FPS, season/weather/hour) |

Plain F1 is the help overlay (`game/player/help_overlay.gd`). Season is F5.
Free-fly is Shift+F5. F2–F4 are still atmosphere's weather and hour keys.

## Movement feel

- Speeds: walk 1.4 m/s, run 3.5 m/s, crouch 0.9 m/s (brief's targets).
- Capsule collision: radius 0.3m, stand height 1.8m, crouch height 1.1m
  (lerped, `CROUCH_LERP_SPEED=8`), eye height 1.7m stand / 1.0m crouch. The
  `CharacterBody3D`'s own origin is the **feet** (capsule bottom is always at
  local y=0 regardless of current height); `Head` (camera parent) sits at the
  current eye height plus head-bob/landing-dip offsets.
- Gravity/jump: custom gravity (9.8 m/s^2, applied manually -- not the
  project's physics gravity, so it self-contained regardless of
  `[physics]` settings) + `JUMP_HEIGHT=1.0m` -> `v = sqrt(2*g*h)`.
- Slope limit ~45 deg (`floor_max_angle`); steeper counts as a wall, not
  floor, so the character free-falls/slides off rather than standing on it.
  On walkable slopes there's no scripted downhill slide -- horizontal
  velocity only changes from input, so the player stands still on any <=45
  deg slope once decelerated to zero.
- Step-up (curbs): before `move_and_slide()`, `_try_step_up()` uses
  `test_move()` to detect a low obstacle directly ahead, confirms there's
  headroom to lift by `STEP_HEIGHT=0.3m` and that the lifted position is
  clear, then nudges the body up; `floor_snap_length=0.4` (set in `_ready()`)
  pulls it back down onto the stepped surface within the same
  `move_and_slide()` call. `safe_margin=0.05` to avoid jitter on terrain
  chunk seams / stairs.
- Smooth accel/decel (`move_toward` on horizontal velocity, ground
  12/14 m/s^2 accel/decel, air 4 m/s^2) plus a subtle head bob (sine, ~3.5cm
  vertical / 2cm lateral, scales with speed, fades out when not moving) and
  a landing dip (camera dips up to 14cm on hard landings, recovers in
  ~0.15s) -- tuned to stay well short of "seasick."

## Footstep surface hook

`player.gd::_detect_surface_type()` raycasts straight down from the feet
each stride (~1.5m) and classifies the collider, in priority order:

1. `collider.get_meta("surface_type")` -- a `String` a mesh/body's owner
   can set directly for exact control.
2. Any group on the collider named `surface_<type>` (e.g. `surface_wood`).
3. A sibling `MeshInstance3D` named `Surf_<material_name>` under the same
   parent -- **this already works today** against
   `game/roads/roads.tscn`'s existing `Surf_asphalt_patched` /
   `Surf_curb_concrete` / `Surf_sidewalk_concrete` mesh naming, matched by
   nearest AABB-center to the ray hit (multiple `Surf_*` siblings share one
   collision body per road chunk, so this picks whichever visual surface is
   nearest the hit point) and mapped to a short key
   (`concrete`/`asphalt`/`gravel`/`wood`/`grass`/`dirt`/`stone`).
4. A substring match against the collider node's own name (`bridge`,
   `sidewalk`, `curb`, `asphalt`, `road`, `water`, `wood`, `gravel`,
   `stone`, `grass`).
5. `"generic"` if nothing matched (e.g. plain terrain chunks, which are one
   undifferentiated `HeightMapShape3D` per chunk and don't currently expose
   which splat layer is underfoot).

Each stride emits `footstep(surface_type: String, global_pos: Vector3)` and
plays a placeholder procedurally-generated ~45ms noise-burst click through
`Head/Footsteps` (`AudioStreamPlayer3D`), quiet by default
(`footstep_volume_db=-20`, `@export`-able) with small per-surface
pitch variation. No audio assets required. **For future workstreams**:
setting `set_meta("surface_type", "gravel")` or `add_to_group("surface_gravel")`
on a StaticBody3D (or its MeshInstance3D children under the collider's
parent, per the `Surf_` convention) is all that's needed to get precise
footstep classification without touching player code; connect to the
`footstep` signal (or swap `Footsteps.stream` per `surface_type` in
`_play_footstep_sound()`) to add real foley later.

## Spawn points (`spawn_points.gd`)

`--spawn=<name>` on the Godot command line picks one (default `downtown`);
unknown names warn and fall back to default. Y is sampled from
`TerrainHeight.get_height(x,z)` at spawn time (not baked in) except
`bridge`, which is elevated above the terrain/river surface.

| name | where | notes |
|---|---|---|
| `downtown` (default) | Galena Ave / Dixon Memorial Arch | proxy for "Galena & 1st" -- that exact intersection isn't in `docs/pipeline_notes.md`'s landmark table, so the nearest downtown Galena Ave landmark was used |
| `lincoln_statue` | riverfront | from `pois.json` |
| `page_park` | west side of play area | polygon centroid from `landuse.json` (no single named point exists for it) |
| `reagan_home` | 816 S Hennepin Ave | Reagan Boyhood Home street |
| `bridge` | Galena Ave bridge deck | y hardcoded to deck height (13.4), not terrain-sampled |
| `bluff_vista` | north bluff | highest point in the play-area heightmap (~41m local Y), facing south over downtown/river |

Example: `godot --path game -- --spawn=bridge`.

## Capture-mode contract

Mirrors `atmosphere.gd`'s own pattern exactly: the capture harness
(`game/tools/capture/capture_main.gd`) calls
`root.set_meta("capture_mode", true)` on the scene root it instances,
**before** adding it to the tree. `player.gd::_find_capture_mode()` walks up
from itself through parents at `_ready()` looking for that meta (since
`Player` is a descendant of `World`, not the instanced root itself). When
found:

- mouse is never captured (`Input.mouse_mode` untouched),
- `Head/Camera3D.current` is left `false` so the harness's own
  `Camera3D.make_current()` wins,
- `_process`/`_physics_process`/`_unhandled_input` all early-return (no
  movement, no F5/F6, no debug label built) -- the player body just sits at
  its spawn point while the harness camera flies around it.

Verified against `res://world/world.tscn` via `game/tools/capture.sh`
(see Verification below): captures came out framed purely by the harness
camera with no debug UI visible.

## Integration

`world/world.tscn` instances `res://player/player.tscn` as a new `Player`
node (after `Atmosphere`/`Terrain`/`Buildings`/`Roads`). No other part of
`world.tscn` was touched. Default collision layer/mask (1/1, engine
default) -- every other workstream's `StaticBody3D` collision is also on
the default layer, so no custom physics layers were needed.

## Verification

`game/tools/capture.sh res://world/world.tscn <shots.json> captures/player/iter1`
with shots at downtown (summer/clear), the Lincoln statue riverfront
(autumn/overcast), and the bluff vista (winter/snow) -- eye-height framing
via the harness camera, 90-frame warmup. Godot log checked for
`SCRIPT ERROR`/`ERROR`: none. All three images show the player's capsule
absent from frame (capture camera only) and no player debug UI overlay,
confirming the capture_mode contract holds end-to-end through
`world.tscn`.

## Known weaknesses / next-iteration TODO

- Surface detection falls back to `"generic"` on plain terrain (grass vs.
  dirt vs. mud aren't distinguished) since terrain chunks are one
  undifferentiated collision shape without per-splat metadata; a real fix
  needs terrain to expose its splat weight at a given x/z, which is out of
  this workstream's ownership.
- Step-up is a `test_move()` heuristic, not a full swept-shape sweep -- it
  handles the ~0.3m curb case (`FLOOR_MAX_ANGLE_DEG`, `STEP_HEIGHT` brief
  targets) but hasn't been stress-tested against irregular building
  foundations/stairs, since buildings interiors aren't walkable content yet.
- Footstep audio is a single generic click (no per-surface waveforms yet),
  by design per the brief ("no audio assets required now").

## Exploration HUD (game/player/hud.gd) — toggleable, hidden during captures
Instanced as the `HUD` CanvasLayer in `world/world.tscn`.

| Key | Does |
|---|---|
| **F7** | location + structure readout on/off |
| **F8** | minimap on/off |
| **F9** | minimap zoom: 120 / 250 / 600 m |
| **F10** | coordinates + look vector on/off |
| **F12** | screenshot to `<project>/screenshots/` |
| **Shift+F12** | screenshot with the HUD hidden |

Readout (bottom-left, deliberately clear of atmosphere's top-left line at (12,8) and player.gd's
debug readout at (12,40) — they used to overlap):
- nearest named street, or "A & B" within 35 m of a second named street;
- **what you are looking at**: a ray from the camera is matched against named OSM building footprints
  and the landmark list, so structures identify themselves (◆ = landmark, • = named building, with a
  distance when it is not the thing directly under the crosshair);
- season / weather / clock;
- `x y z` and `look <compass> <deg> pitch <deg> (fwd vector)` for correlating a position with the model.

Minimap: north-up vector map, arterials thicker/yellow, landmark markers, player position + heading,
scale label. Segments are Liang-Barsky clipped to the map rect — without that, long streets whose
endpoints both fell outside the box vanished and short ones drew outside it.

Screenshot filenames carry timestamp, x_y_z, compass + heading, season, weather and hour, so a shot is
self-describing when sent back as a bug report. `screenshots/` is gitignored.

## Bug tickets from inside the game (game/player/ticket_tool.gd)
**F11** freezes the frame, frees the mouse and pauses the world. Click anything that is wrong,
type a note, **Enter** saves; right-click removes the last tag, **Esc** cancels.

Each ticket lands in `tickets/<timestamp>/`:
- `shot.png` - the frame with numbered markers burned in, readable on its own
- `ticket.md` - a table of the tags plus a ready-to-run capture shot list

A tag is not just a screen position. The tool raycasts and records **what was actually hit**:
the owning system (Buildings / Roads / Terrain / Vegetation / Landmarks), the node path, the
world coordinates, the distance, and the nearest named street and structure. That is what makes
a ticket actionable - "the wall is black" is a guess, "Buildings/chunk_12_-9 at (1629,-1337),
S Galena Ave, The Dixon: Historic Theatre" is a lead.

The `ticket.md` ends with a shots JSON so the exact view can be re-rendered offline:
`game/tools/capture.sh res://world/world.tscn <that json> <outdir> 80`

Verified end-to-end by `game/tools/ticket_selftest.tscn`, which drives the whole path. The help overlay and the building editor are checked without loading the city by `game/tools/tools_selftest.tscn`. Both, plus the template resolver, run from `game/tools/run_checks.sh`.
(enter -> tag by raycast -> note -> save) with no human input. The tool is inert in capture_mode.

## Building Composer export (building editor, X)

X in the building editor (`game/player/building_edit.gd`) writes the selected building's footprint to `exports/composer/<id>.json` (`format: "dixon-footprint"`: the traced outline in game meters, ground height, height, OSM tags, and `front`) and opens it in Building Composer (`#import=` in the page address; `game/tools/composer_server.py` is started for Composer if none answers at `BUILDING_COMPOSER_URL`).

The structure the game generated is **not** exported (no `hints`): only a building designed in Composer carries its own design. `front` is a unit vector `[x, z]` (x east, z south) from the footprint's middle toward the nearest street (`street_front`; alleys, paths and footways only count when no street is within 250 m). Composer turns it into the side of the squared footprint it faces, using the saved rotation, and names the walls from it.

### Bringing a Composer design back (Send to game, I, R)

In Composer, **Send to game** (only for a building opened with X) POSTs the model to the server, which writes `game/data/composed/<id>.json` (`format: "dixon-composed"`: triangles grouped by the game's material names, already in game space and Godot's winding, heights relative to the ground, a collision hull, and the Composer project under `project`). Without the server it downloads the file instead; put it in `game/data/composed/`.

`pipeline/buildings/composed.py` uses that file in place of the generated building whenever the chunk is built, so later full builds keep it. In the building editor:

- **I** uses the Composer design (removes `composed: false` from the override) and rebuilds the chunk;
- **R** reverts to the generated building (`composed: false` in `building_overrides.json`); the design file stays, and I brings it back;
- **X** again opens the outline in Composer; if a design was sent, it is carried along (`project`) and Composer reopens it. If the outline was changed in the game since, Composer says so and opens the fresh outline instead.

Buildings that never went through Composer are untouched: the game keeps generating them from the footprint.
