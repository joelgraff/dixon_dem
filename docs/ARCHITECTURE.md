# Dixon — Architecture & Conventions (all agents MUST follow)

Engine: **Godot 4.6 stable**, Forward+ (Vulkan), Jolt physics. Binary: `~/AppImage/Godot_v4.6-stable_linux.x86_64`.
Target HW: AMD RX 580 8GB, 16GB RAM (often only ~3GB free) — budget: 60 fps @1080p on "high". Keep textures ≤2K, prefer 1K; use MultiMesh/instancing; merge static meshes per chunk; use visibility ranges (HLOD).

## Layout
```
dixon_dem/
  dems/            USGS NED 1/9" (ned19_*) source DEMs (read-only). Other files in dems/ are legacy, reference only.
  dixon_topo_v2.png  OSM-style reference render of Dixon (not georeferenced) — visual reference for road layout.
  data/raw/        downloads (OSM extracts, texture zips) — gitignored
  pipeline/        Python data processing. Use ../.venv/bin/python (numpy, rasterio, pyproj, shapely, scipy, pillow, requests)
  docs/            this file, ART_DIRECTION.md, references/*.md, workstream notes
  game/            Godot project (res://)
    autoload/      WorldState (season/weather/time contract)
    world/         world.tscn composition root
    terrain/ roads/ buildings/ landmarks/ vegetation/ atmosphere/ player/   one folder per workstream
    materials/     shared PBR material library (+ textures under materials/textures/<name>/)
    data/          generated game data (heightmaps, geojson/json from pipeline)
    tools/         capture.sh, import.sh, capture harness
```
**Ownership:** a workstream only writes inside its own folder (plus `docs/<workstream>_notes.md`). Shared files (`project.godot`, `autoload/`, `world/world.tscn`, `materials/`) — change only if your brief says you own them; otherwise request the change in your final report.
Do **not** run git commands; the orchestrator commits.

## World coordinates
- Local tangent plane in **meters**, projection **EPSG:26916 (NAD83 / UTM 16N)**.
- Origin: defined in `game/data/world_origin.json` (produced by the data pipeline): UTM easting/northing of origin + `base_elevation_m`.
- Godot axes: **+X = east, +Y = up, −Z = north** (i.e. z = −(northing − origin_n)). Y = elevation_m − base_elevation_m.
- Play area: ~2.5 × 2.5 km centered on downtown Dixon (Galena Ave bridge / Rock River). Beyond: low-detail horizon terrain.

## World conditions contract (`WorldState` autoload)
- `season` (SPRING/SUMMER/AUTUMN/WINTER), `weather` (CLEAR/OVERCAST/RAIN/SNOW/BLIZZARD/FOG), `hour` (0–24), `day_of_year` (int, auto-set per season, latitude 41.84N solar position), signal `changed`.
- `apply(season, weather, hour, transition:=0.0, day_of_year:=-1)` / `apply_named(season, weather, hour, transition:=0.0)`: `transition > 0` smoothly blends the continuous shader globals below over that many seconds instead of snapping (use for in-game changes; leave 0 for debug/instant cuts — the atmosphere rig also uses `WorldState.last_transition_duration` to match its own sky/fog blending to the same duration).
- Global shader uniforms (declare with `global uniform float snow_cover;` etc.): `snow_cover` 0–1, `wetness` 0–1, `season_foliage` (0 summer green → 0.75 autumn → 1 bare/winter), `wind_strength` 0–1, `night_factor` 0–1 (0 = daylight, 1 = full night; ramps over civil twilight — drive emissive windows/streetlights with this, e.g. `EMISSION = light_color * night_factor`; see `game/atmosphere/shaders/window_demo.gdshader` for a worked example).
- Prefer `WorldState.get_snow_cover()` / `get_wetness()` / `get_foliage()` / `get_wind_strength()` over `RenderingServer.global_shader_parameter_get()` when reading these from a script — the latter is an editor-only debug call and errors at runtime in exported/running games.
- Every material that is outdoors must respond to `snow_cover` (snow on upward-facing surfaces) and `wetness` (darker albedo, lower roughness, puddles on flat ground where appropriate).
- Instance `res://atmosphere/atmosphere.tscn` once per scene for the full lighting/sky/weather rig (sun+moon positioned by real solar geometry, procedural sky, SDFGI/volumetric+depth fog, weather particles). It reacts to `WorldState` automatically — see `docs/atmosphere_notes.md`.

## Visual verification
`game/tools/capture.sh <res://scene.tscn> <abs shots.json> <abs out_dir> [warmup_frames]`
- shots.json: `[{"name":"x","pos":[x,y,z],"look_at":[x,y,z],"fov":70,"season":"winter","weather":"snow","hour":9.5}]`
- GPU is serialized with a lock (other agents may hold it — waits are normal). Output 1600×900 PNGs. Use warmup ≥60 when SDFGI/volumetric fog is on.
- Godot does NOT exit on script errors — always check the log for `SCRIPT ERROR`/`ERROR` (`> log 2>&1; grep -E "ERROR" log`).
- After adding textures/models run `game/tools/import.sh`.
- Put captures in `~/Projects/dixon_dem/captures/<workstream>/iterN/` (gitignored). Look at your own screenshots with the Read tool before claiming anything.
- Every workstream provides a standalone test scene `res://<folder>/test_<folder>.tscn` that includes a minimal lighting rig by instancing `res://atmosphere/atmosphere.tscn` if it exists (else a temporary DirectionalLight3D + WorldEnvironment with AgX tonemap).
