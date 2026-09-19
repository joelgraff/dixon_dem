# Atmosphere workstream notes

Owns: `game/atmosphere/`, `game/autoload/world_state.gd`, the `[rendering]`/`[shader_globals]` sections of `game/project.godot`.

## iter2 (response to docs/critiques/atmosphere_iter1.md, FAIL avg 3.17)

Root causes found and fixed:
- **Sun kept full energy under cloud.** Added `direct_scale` per weather (CLEAR 1.0 down to BLIZZARD 0.03), multiplies `sun.light_energy`; `shadow_opacity` restored to 1.0 (it was previously faked-low, which leaked light on top of the still-full-power sun). Ambient compensates: `ambient_light_energy = lerp(1.6, 1.0, direct_scale)`. Measured: overcast wall luma now 74 vs clear's 91 (iter1 had this inverted, 0.54 vs 0.40).
- **Fog painted over the whole sky.** `volumetric_fog_sky_affect`/`fog_sky_affect`/`fog_aerial_perspective` are now near-zero for CLEAR/OVERCAST/SNOW and only meaningful for FOG/RAIN/BLIZZARD; one `fog_color` (weather-anchored, e.g. grey-green for FOG, not derived from the twilight-tinted sky) now drives both the volumetric and depth fog instead of two different colors fighting each other.
- **Salmon twilight dome / >5-stop dusk crush.** The horizon color used for ambient was blending toward orange across a wide elevation band regardless of which way you looked. `horizon` is now azimuth-neutral (day/night blend only); the actual sunset warmth lives entirely in the sky shader's new `horizon_twilight_color` uniform, applied only in a band around the sun's real azimuth (`warm_amount = pow(sun_side, 2.2) * near_horizon * twilight_strength`) plus a cool Belt-of-Venus band on the anti-sun side. Also tightened the sun's below-horizon falloff (`inverse_lerp(-1, 15, elev)`, was `-6`) so direct light actually reaches zero by sunset instead of still contributing ~30% energy at -0.7°. Result: winter-sunset snow looking away from the sun now reads blue (ground rgb ~(3,4,10), B>R) instead of mauve.
- **Weather particles invisible / carried over.** Two separate bugs: (1) the runtime-built `Image`+`set_pixel()` soft-alpha texture (iter1) produced near-zero visible alpha combined with `BLEND_MODE_ADD` — replaced with a `GradientTexture2D` (`FILL_RADIAL`), a real engine resource, and switched particle materials to `BLEND_MODE_MIX`. (2) Even with a correct texture, a small quad (real snowflake scale, a few cm) samples a heavily mip-blurred version of that texture at typical distances, averaging its alpha near zero — fixed by setting `texture_filter = TEXTURE_FILTER_LINEAR` (no mipmaps) so the bright centre always shows regardless of on-screen size. Rain is now a tight near-camera box (was 36×36m, mostly empty of visible drops; now 6×6m, 2200 streaks) with velocity-stretched `TRANSFORM_ALIGN_Z_BILLBOARD_Y_TO_VELOCITY` streaks; snow uses a plain `Z_BILLBOARD` (non-stretching) alignment for calm flakes and only switches to the velocity-stretched streak mesh in blizzard (Y_TO_VELOCITY at low velocity was collapsing calm snow to sub-pixel — a second, distinct cause of "snow invisible"). `rain_streaks`/`snow_particles`/`mist_particles` now call `.restart()` whenever `WorldState.weather` changes, clearing any still-alive particles instead of just stopping new spawns (iter1 left mist alive for up to 14s into the next shot).
- Also fixed: `WorldState.hour` (clock time, public API, unchanged) is now converted to *solar* time internally before computing sun position (DST + equation of time + longitude vs. the Central meridian) — iter1 fed clock time straight into a solar-time formula, misplacing the sun by up to 10° for 8 months of the year. Shadow acne (visible as fine diagonal moiré on large flat surfaces) from an over-aggressive `shadow_normal_bias` reduction was dialed back. `world/world.tscn` already instances `atmosphere.tscn` (added by another workstream — verified, not re-touched).

Captures: `captures/atmosphere/iter2/` — a same-framing weather matrix (CLEAR/OVERCAST/RAIN/FOG/SNOW/BLIZZARD at 12:00), golden-hour toward/away-from-sun pairs, winter-sunset-away, blue hour ×2, night ×3 (moon-in-frame/moonless/overcast), spring fog toward-sun, rain close-up + wet-road, blizzard near/wide, snow close-up ×2, elevated vista clear/overcast, autumn foliage, and a blizzard→clear back-to-back pair proving zero particle carryover. Numerically verified with a small PIL script (sky/ground luminance ratio, clipping %, median saturation) rather than eyeballing alone — see the measurements above for the specific before/after callouts.

Known remaining weaknesses: blizzard's motion-streak is hard to see against its own whiteout fog (low contrast, both near-white); snow flakes, while now visible, still read visually similar to stars in shape (only reliably distinguished from stars by weather/time-of-day, since star_visibility is 0 whenever it isn't night); the diorama's wetness/foliage response (added this pass) is a placeholder for the real materials/vegetation workstreams.

## What exists

- `res://atmosphere/atmosphere.tscn` (+ `atmosphere.gd`) — the single lighting/sky/weather rig. Instance it once in any scene (already done by `res://atmosphere/test_atmosphere.tscn`; `world/world.tscn` still needs it instanced by whoever owns that composition root). Everything is **built procedurally in `_ready()`** rather than hand-authored as scene sub-resources — Sun/Moon `DirectionalLight3D`s, a `WorldEnvironment` with a custom sky shader, and a `WeatherRig` with the particle systems — so the whole rig lives in one reviewable file instead of a large hand-edited `.tscn`.
- `res://atmosphere/shaders/sky.gdshader` — procedural sky: day/twilight/night gradient (fed pre-blended colors from `atmosphere.gd`, not physical scattering math), fbm-noise cloud layer projected onto a virtual dome (coverage/darkness driven by weather), sun/moon discs+glow, hashed pinpoint stars fading in at night and thinning under cloud cover. No external textures.
- `res://atmosphere/shaders/window_demo.gdshader` — tiny placeholder spatial shader used only by the test diorama's windows; demonstrates the `night_factor` global hook (day: dark pane, night: warm emissive glow). Real building/window materials belong to the materials/buildings workstreams — copy the two-line `night_factor` mix pattern into their emissive shaders.
- `res://atmosphere/test_atmosphere.tscn` (+ `test_diorama.gd`) — stand-in diorama (the real town isn't built yet): a ~600m rolling noise-displaced terrain plane, two brick box buildings with inset windows, a road strip, ~48 MultiMesh sphere/cylinder "trees", a dark river plane, and 10 low-poly far hills. Instances the atmosphere rig and listens for `snow_cover` to blend terrain/road/canopy toward white in winter (a placeholder for the real materials workstream's snow response).
- `res://atmosphere/perf_probe.tscn` (+ `perf_probe.gd`) — standalone FPS check (see Performance below).
- `game/autoload/world_state.gd` — season/weather/hour/day_of_year API, unchanged signatures plus additive `transition` support and `get_snow_cover()`/`get_wetness()`/`get_foliage()`/`get_wind_strength()` accessors.

## How the rig works

`atmosphere.gd`'s `_process()` every frame:
1. **Sun & moon position** — real solar-position formula (declination/hour-angle/elevation/azimuth) for latitude 41.84°N using `WorldState.day_of_year` + `WorldState.hour`. The moon is a simplified "anti-sun" (opposite side of the sky, `hour+12`) with a slow pseudo lunar-phase brightness cycle — not a real ephemeris, but gives correct qualitative behavior (moon up when sun is down, moves the opposite way) and a phase-varying night brightness.
2. Sun color/energy ramp warm-and-dim near the horizon to neutral-and-bright at elevation; `night_factor` global ramps 0→1 as the sun crosses roughly -2° to -10° elevation (civil twilight).
3. **Environment/sky** — per-weather `weather_profiles` and per-season `season_profiles` dictionaries define targets (cloud coverage/darkness, fog density/visibility, shadow opacity, aerial perspective, saturation, haze, tint); these are exponentially smoothed each frame (`_blend`) so both debug-key cuts and `WorldState.apply(..., transition:=N)` read reasonably. Feeds the sky shader's uniforms, `Environment` SDFGI/SSAO/SSIL (set once), volumetric + depth fog, AgX tonemap/exposure, and `sun.shadow_opacity`.
4. **Weather particles** — a `WeatherRig` Node3D copies the active camera's position every frame (`get_viewport().get_camera_3d()`); rain/snow/mist `GPUParticles3D` are children of it so they always surround whoever is looking. A `GPUParticlesCollisionHeightField3D` (`follow_camera_enabled = true`, `update_mode = WHEN_MOVED`) lets rain streaks collide with the ground cheaply.
5. Debug keys (only outside capture mode): **F1** cycle season, **F2** cycle weather, **F3/F4** step hour ±0.5h. A small `CanvasLayer` label shows current state.

### Transitions
`WorldState.apply(season, weather, hour, transition:=0.0)`: with `transition > 0` the four continuous shader globals (`snow_cover`, `wetness`, `season_foliage`, `wind_strength`) tween smoothly via `WorldState`'s own `Tween`. `atmosphere.gd` reads `WorldState.last_transition_duration` and uses it as its own environment-blend time constant, so weather changes read as one coherent fade rather than the globals and the sky/fog snapping at different rates. `transition = 0` (debug keys, capture tool, scene load) converges in ~0.15s — enough to avoid a single-frame pop without leaving stale weather visible into the next shot/frame.

### Capture-mode
Any ancestor with `set_meta("capture_mode", true)` (the capture harness sets this on the loaded scene root) suppresses the debug label and F1–F4 input, and the test diorama skips building its own preview camera.

## Settings per weather preset (`weather_profiles` in `atmosphere.gd`)

| Weather | Cloud cover | Fog density | Visibility | Shadow opacity | Notes |
|---|---|---|---|---|---|
| CLEAR | 0.28 | 0.0015 | 5000m | 1.0 | scattered cumulus, full shadows |
| OVERCAST | 0.95 | 0.004 | 2600m | 0.55 | flat soft light |
| RAIN | 0.98 | 0.007 | 1400m | 0.35 | rain streaks emit |
| SNOW | 0.9 | 0.006 | 1200m | 0.45 | snow emits at 35% density |
| BLIZZARD | 1.0 | 0.055 | 70m | 0.15 | snow at 100% density + strong horizontal wind, heaviest fog |
| FOG | 0.6 | 0.024 | 200m | 0.5 | mist wisps, no precipitation |

Season profiles (`season_profiles`) set `adjustment_saturation` (spring 0.95, summer 1.0, autumn 0.92, winter 0.82) and a subtle sky/haze tint — deliberately mild per ART_DIRECTION's "natural saturation, not oversaturated" rule.

## Performance (RX 580, 1600×900)

`perf_probe.tscn` warms up 120 frames then measures 180, real Vulkan renderer, vsync disabled for an uncapped reading:

- **Winter blizzard** (worst case — SDFGI + volumetric fog + max particle density): **140.4 fps avg (7.12 ms/frame)**
- **Summer clear noon**: **139.8 fps avg (7.16 ms/frame)**

Run it yourself (must NOT use `--headless` — that swaps in a null renderer):
```
flock .locks/gpu.lock godot --path game --resolution 1600x900 \
  res://atmosphere/perf_probe.tscn -- --season=winter --weather=blizzard --hour=13
```
This is the atmosphere rig + stand-in diorama only — real terrain/building/vegetation geometry from other workstreams will add cost on top, but confirms the rig itself (SDFGI, volumetric fog, sky shader, particles) is not the bottleneck at the 60fps/1080p-high budget, with large headroom to spare.

SDFGI is tuned conservatively for RX 580: `sdfgi_cascades=3`, `min_cell_size=0.3`, `max_distance=220m` (distant terrain relies on fog for aerial perspective, not GI). `project.godot` sets SSAO/SSIL quality=Low with half-size, volumetric fog volume 64×64, and directional shadow size 2048 with soft-shadow filtering.

## Globals reference

Declared in `project.godot` `[shader_globals]`, all owned by this workstream:

- `snow_cover` (float 0–1) — outdoor materials should lerp albedo toward white / add snow on upward-facing normals.
- `wetness` (float 0–1) — darker albedo, lower roughness, puddles on flat ground.
- `season_foliage` (float 0–1) — 0 summer green, 0.75 autumn, 1 bare/winter.
- `wind_strength` (float 0–1) — drives weather particle drift; vegetation sway should also read this.
- `night_factor` (float 0–1, **new this iteration**) — 0 full daylight, 1 full night, ramps over civil twilight (~sun elevation -2° to -10°). Hook for emissive windows/streetlights: `EMISSION = window_light_color * night_factor`. See `shaders/window_demo.gdshader`.

## Known weaknesses / next-iteration TODO

- **Mist/snow billboards are hard-edged quads.** A procedurally-generated soft radial-gradient `ImageTexture` (built at runtime via `Image.create` + `set_pixel`) rendered as fully transparent for reasons not fully diagnosed in this pass — using it made rain splashes, snow, and mist invisible entirely (removing it fixed visibility but brought back hard quad edges). Occasionally visible as small flat squares in blizzard/fog captures. Worth a proper look — likely something about `StandardMaterial3D.albedo_texture` + `TRANSPARENCY_ALPHA` + `BILLBOARD_PARTICLES` interaction, or the runtime-built `Image`/`ImageTexture` needing an explicit format/mipmap flag this pass didn't try.
- **Rain splashes are disabled.** `ParticleProcessMaterial` collision + `sub_emitter_mode = AT_COLLISION` worked mechanically but a raindrop landing within ~1-2m of a street-level camera reads as a jarring oversized flat square (inherent risk of camera-attached rain at eye height). Cut per ART_DIRECTION's own "with splashes if affordable" hedge — rain streaks alone read fine. The `RainSplashes` node is still built (just never emits) so collision/sub_emitter can be re-enabled by future work, ideally paired with a proper soft-alpha splash texture and/or a distance-to-camera fade.
- **Moon is a simplified anti-sun**, not a real ephemeris (documented above) — fine for gameplay-readable night lighting, not astronomically accurate.
- **No real terrain/buildings yet** — captures use the stand-in diorama described above; re-validate fog/exposure tuning once real geometry (with real materials responding to `snow_cover`/`wetness`) lands, since albedo values and scene depth will differ from the placeholder StandardMaterial3Ds used here.
- **`world/world.tscn` does not yet instance `atmosphere.tscn`** — out of this workstream's ownership (shared file); whoever owns world composition should add `res://atmosphere/atmosphere.tscn` as a child.
