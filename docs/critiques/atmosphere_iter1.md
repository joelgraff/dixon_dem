# Atmosphere critique — iteration 1

Reviewer: independent lighting/art director (evaluation only, no project edits)
Scope: sky, sun/moon, GI, fog, exposure/grading, seasons, weather particles, night, transitions. The diorama's modelling isn't judged. Each rubric category is scored only for what atmosphere contributes to it.
Evidence: all 10 captures in `captures/atmosphere/iter1/`, measured with PIL (sRGB 8-bit values, regions named below), plus a read of `game/atmosphere/atmosphere.gd`, `shaders/sky.gdshader`, `autoload/world_state.gd` and the `[rendering]` section of `project.godot`.

---

## 1. Scores

| # | Category | Score | One-line justification |
|---|---|---|---|
| 1 | Lighting & atmosphere | **3** | Overcast and rain keep full-strength direct sun. Twilight crushes the ground to black under a bright sky. Night can't be read. Fog shows a seam at 110 m. Every frame has low contrast and a grey veil. |
| 2 | Materials & surfaces (weather response) | **3** | Rain has no wet response: the road is 0.29 in rain vs 0.27 overcast. Snow comes out beige/pink (hue 9–17°), or mauve at sunset. Autumn foliage is still summer green. The diorama ignores `wetness` and `season_foliage`. |
| 3 | Color & palette | **3** | Morning fog is mauve (hue 258–330°, not grey-green). Twilight turns the whole dome and ground salmon (ground sat 0.58). Overcast winter snow is pinkish. Rain, overcast and autumn look almost identical. |
| 4 | Form, scale & proportion (atmospheric) | **4** | Snowflakes read as stars. Mist quads are 1.2 m hard squares. Cloud texture stretches into radial streaks at the horizon. With "70 m visibility" the blizzard still shows tree silhouettes about 300 m away. |
| 5 | Composition & believability | **3** | No frame reads as a real Illinois weather state. The blizzard looks like a grey hazy day, the rain like overcast with two scratches on the lens, and the clear sky like an empty gradient. |
| 6 | Technical artifacts | **3** | Hard-edged particle quads carry over into the next shot's weather. Volumetric-fog seam. 8-bit sky banding (runs up to 59 px). Blocky, aliased stars. Clouds glow at night. Shadows detach from building bases (peter-panning). |

**Average 3.17 — FAIL** (pass bar: all ≥ 7 and average ≥ 8).

### Key measurements
| Shot | p1 / median / p99 luma | Notes |
|---|---|---|
| summer_clear_1000 | 56 / 122 / 167 | No value above 167/255 on a clear July morning. Sunlit wall 0.57, sky 0.73. Flat and veiled. |
| elevated_vista_summer_clear_1400 | 108 / 129 / 170 | Only 62 levels of range. Near ground sat 0.12, far hills val 0.67 ≈ sky. Far too hazy for "CLEAR, 5000 m". |
| autumn_overcast_1500 | brick front **0.54** | Brighter than the same wall under clear sun (0.40), which is physically backwards. |
| spring_rain_1100 | sky mean 147 | Brighter than the overcast sky (143) even though `cloud_darkness` is 0.72 vs 0.55. |
| spring_fog_0700 | fog rgb(153,151,159), road rgb(60,55,59) | Mauve/magenta. Reference is grey-green `#9FA9A2`. |
| summer_clear_golden_1930 | ground rgb(30,15,13), sky 0.65–0.79 | More than 5 stops between sky and ground. P95 saturation 230/255. |
| winter_clear_sunset_1630 | snow rgb(75,52,57), hue 347° | Snow in skylight shade should be blue (hue ~210–225°). |
| winter_snow_0900 | snow rgb(181,169,164), sky rgb(127,125,132) | Warm pink snow under a violet overcast. |
| winter_blizzard_1300 | column x=150: 118 flat, then jumps to 132→151 at y≈492 | Hard fog seam where the 110 m volumetric fog ends. |
| summer_clear_night_2300 | ground 0.05–0.07, wall 0.08, windows 0.91 | Ground can't be read. Windows add zero light to the wall around them. 0.19 % of sky pixels are stars. |

### Sun position check (41.84° N, 89.48° W)
The formula in `_solar_position` is correct, but `WorldState.hour` is fed in as **local solar time** while shot names and gameplay use **clock time**. From March to November (DST), clock time runs about 1 h ahead of solar time in Dixon, so the sun is placed wrong:

| Shot | In-game elevation / azimuth | Real at that clock time | Error |
|---|---|---|---|
| summer 10:00 CDT | 59.0° / 117° | 48.6° / 102° | +10° |
| summer 14:00 CDT | 59.0° / 243° | 67.7° / 219° | −9° (sun past its peak when it should be near it) |
| summer "golden" 19:30 CDT | **0.2°** / 302° | **10.0°** / 293° | the "golden hour" shot is actually sunset |
| spring fog 07:00 CDT | **16.2°** / 94° | **5.1°** / 84° | the dawn-fog shot has a mid-morning sun |
| spring rain 11:00 CDT | 53.2° / 155° | 46.8° / 134° | +6°, 21° of azimuth |
| autumn 15:00 CDT | 23.5° / 229° | 30.3° / 220° | −7° |
| winter 09:00 / 13:00 / 16:30 CST | 12.6° / 23.3° / −0.2° | 13.1° / 23.1° / −0.9° | fine (≤1°) |

Seasonal day-of-year choices (100/172/290/355) are fine. The anti-sun moon is acceptable for now, but in the night shot it sits behind the camera, so no moon is visible and it contributes almost nothing.

---

## 2. Must-fix list (priority order)

### 1. Direct sun stays at full strength under overcast, rain, snow and blizzard
- **Screenshots:** autumn_overcast_1500, spring_rain_1100, winter_snow_0900 and winter_blizzard_1300. The building still casts a directional shadow in all of them, and the wall is *brighter* than under clear sun (0.54 vs 0.40).
- **Root cause:** `atmosphere.gd:_update_environment` only changes `sun.shadow_opacity`. `sun.light_energy` (up to 2.6) never looks at cloud cover, so heavy cloud just fills in the shadows while the whole direct light stays.
- **Fix:**
  - Add `direct_scale` to `weather_profiles`: CLEAR 1.0, OVERCAST 0.12, RAIN 0.06, SNOW 0.10, BLIZZARD 0.03, FOG 0.25.
  - Blend it through `_blend` and multiply `sun.light_energy` by it. Keep `shadow_opacity` at 1.0: a weak light already gives weak shadows, and opacity < 1 just leaks light.
  - Compensate with the sky: `ambient_light_energy` ×1.3–1.6 under overcast, and set `tonemap_exposure` from a target middle-grey. Either enable `CameraAttributesPhysical` / auto-exposure (`auto_exposure_enabled=true`, `auto_exposure_scale≈0.4`, speed 0.5), or keep a hand table where overcast is about 1.0–1.5 stops brighter than clear.
  - Pass cloud coverage to the sky shader so the sun disc/glow is hidden (it already is), and scale `sun_energy` in the sky the same way.

### 2. Fog colour is painted over the whole sky, so every sky is a flat, uniform wash
- **Screenshots:** summer_clear_golden_1930 and winter_clear_sunset_1630 (entire dome salmon, zenith hue 12–13°), spring_rain_1100 (rain sky brighter than overcast), elevated_vista.
- **Root cause:**
  - `fog_light_color = horizon` combined with `fog_sky_affect` 0.3–1.0, plus `volumetric_fog_sky_affect = 0.5` with albedo `horizon.lightened(0.1)`. Together they replace most of the gradient and cloud deck with the horizon colour.
  - `twi_t` blends `horizon_twi` (0.92, 0.5, 0.28) into the horizon colour everywhere, with no dependence on azimuth.
- **Fix:**
  - Set `volumetric_fog_sky_affect = 0.0` for every weather except FOG and BLIZZARD (0.3).
  - Set `fog_sky_affect` to 0.0–0.15 for CLEAR, OVERCAST and SNOW. Let the sky shader's own `horizon_haze` handle skyline softening.
  - In `sky.gdshader`, make twilight colour depend on azimuth. Use `float sun_side = dot(normalize(dir.xz), normalize(sun_dir.xz))*0.5+0.5;`, warm the horizon toward `horizon_twi` by `sun_side^2`, and give the anti-sun side a cool blue-grey with a faint pink "Belt of Venus" band at `up≈0.05–0.15`.
  - Keep the zenith blue (≈ 0.10, 0.20, 0.45) until the sun is below −4°.
  - Real clear sunsets in Illinois have a deep-blue zenith and warm colour only in a 10–20° band on the sun side.

### 3. Twilight and golden hour: crushed, over-saturated ground and a 5-stop sky/ground gap
- **Screenshots:**
  - summer_clear_golden_1930: grass rgb(30,15,13), sat 0.58; sky 0.65–0.79.
  - winter_clear_sunset_1630: road almost black; snow mauve rgb(75,52,57).
- **Root cause:**
  - The ambient comes from the salmon sky, so shadowed areas turn warm.
  - `ambient_light_energy` drops to 0.55 at `day_t≈0.5`.
  - The sky shader's `ground_color` is 0.05, so the lower hemisphere of radiance is black.
  - SDFGI only has a grazing sun to bounce.
- **Fix:**
  - Once #2 gives a blue zenith, the sky-lit shade turns blue on its own (the correct cue for sunset on snow).
  - Hold a floor of `ambient_light_energy ≥ 0.9` down to a sun elevation of −4°.
  - Raise `ground_color` in `sky.gdshader` to about 0.12–0.18 of the mean albedo, lerping to 0.45 with snow, so upward bounce exists.
  - Clamp `adjustment_saturation` to ≤ 0.95 when `twi_t` is between 0.3 and 1, and reduce `sun.light_color` warmth: warm = (1.0, 0.62, 0.38), not (1.0, 0.55, 0.28).
  - Target: ground in shade at sunset should sit about 2–3 stops under the horizon sky (luma ≈ 45–70/255, not 14).

### 4. Hour is solar time but scenarios are clock time, so the sun is wrong by ~10° for 8 months of the year
- **Screenshots:** summer_clear_golden_1930 (sunset instead of golden hour), spring_fog_0700 (sun at 16°, when dawn fog needs about 5°), plus the table above.
- **Fix:** in `atmosphere.gd:_update_sun_moon`, convert clock time to solar time before calling `_solar_position`:
  - `solar = hour − dst + (−89.48 − (−90.0))/15.0 + eot_minutes/60.0`
  - `dst = 1` for day-of-year ≈ 70–307 (second Sunday of March to first Sunday of November)
  - `eot_minutes = 9.87*sin(2B) − 7.53*cos(B) − 1.5*sin(B)`, with `B = TAU*(doy−81)/364`
  - Expose `WorldState.hour` as clock time in the docs. Add a unit check in `perf_probe` or a tiny test: day 172 at 19:30 must give 10° ± 1°.

### 5. Weather particles: rain and snow can't be read, and snow looks like stars
- **Screenshots:**
  - spring_rain_1100: two faint streaks in the whole frame.
  - winter_snow_0900: flakes are pinpoints against the sky, indistinguishable from stars.
  - winter_blizzard_1300: about 8 visible square flakes, nowhere near a whiteout.
- **Root cause:**
  - Rain: 500 particles of 0.012×0.3 m at alpha 0.4 additive, spread over a 36×36 m box.
  - Snow: 700 × 0.35 = 245 flakes of 7 cm over 36×36 m. Almost all of them are 10–25 m away, where 7 cm is under a pixel.
- **Fix:**
  - Use **two layers**:
    - A near layer: box extents 8×6×8 m, centred on the camera and offset along camera forward by 6 m. Rain 1500–3000, snow 1500, blizzard 4000.
    - A far layer as a **screen-aligned scrolling streak/sheet texture**, 2–3 camera-facing cylinders at 15/35/70 m with a panning rain or snow texture, alpha by density (the standard AAA approach, and cheap).
  - Rain streaks: 0.02×0.9 m, `TRANSPARENCY_ALPHA` with `BLEND_MODE_MIX`, colour taken from the sky radiance (not additive white-blue). Lit rain should read as brighter than the background only against dark backgrounds.
  - Blizzard: horizontal velocity 12–18 m/s, `TRANSFORM_ALIGN_Z_BILLBOARD_Y_TO_VELOCITY` with a quad about 0.03×0.25 m so flakes become streaks, plus a full-screen snow-streak overlay (the style guide asks for "screen-space snow streak shader").
  - Snow: a round soft sprite 2–4 cm, `amount_ratio` 0.6 for SNOW.
  - Tween `amount_ratio` from `_blend["precip"]` (a key that is defined but never used).

### 6. Hard-edged particle quads carry over from earlier shots
- **Screenshots:**
  - spring_rain_1100: rectangle at top centre (x730–810, y0–80) and on the road (x917–997, y530–550).
  - winter_clear_sunset_1630: square in the sky (x215–275, y115–175) and on the snow (x235–285, y517–538), plus snow dots in CLEAR weather.
  - winter_blizzard_1300: 130×130 px translucent panel on the road.
- **Root cause:**
  - `emitting=false` does not remove live particles. Mist lifetime is 14 s and snow 5 s, but capture warmup is 90 frames (~1.5 s). The mist from the fog/blizzard shot is still alive in the next shot.
  - `_make_flat_material` has no alpha texture, so each billboard is a hard square.
- **Fix:**
  - On a weather change where `last_transition_duration == 0`, call `restart()` then set `emitting=false`, or set `amount_ratio=0`.
  - For soft sprites, use a `GradientTexture2D` resource (`fill = FILL_RADIAL`, `fill_from=(0.5,0.5)`, `fill_to=(0.5,0.0)`, gradient white α1 → white α0) as `albedo_texture` instead of the runtime `Image`.
  - The likely reason the runtime texture looked invisible: with `BLEND_MODE_ADD` on an albedo alpha of 0.035 × texture alpha (squared falloff, mean ≈ 0.17), output is about 0.006, effectively zero. Use `BLEND_MODE_MIX` for mist, with albedo alpha about 0.15–0.25.
  - Also enable `proximity_fade_enabled=true` (fade distance 1.5 m) and `distance_fade_mode=PIXEL` with min 0.5 / max 3 m, so nothing near the camera shows as a flat card.
  - Better still, drop mist billboards entirely in favour of `FogVolume` boxes with a 3D noise `FogMaterial.density_texture` (`NoiseTexture3D`) that scroll with the wind.

### 7. The volumetric fog volume ends in a visible seam, and depth fog doesn't match it
- **Screenshot:** winter_blizzard_1300. Luma column at x=150 is a flat 118 above y≈492 and jumps to 132–151 below. The snowfield inside 110 m is lit white fog, while terrain beyond it is blue-grey depth fog (115,120,126). Tree silhouettes about 300 m away are still visible at "70 m visibility".
- **Root cause:**
  - `volumetric_fog_length = 110` for every weather.
  - `fog_density = 1/visibility`, but Godot's exponential fog reaches about 95 % extinction at 3/density, so the real visibility is 3× the intended value.
  - Volumetric albedo (`horizon.lightened(0.1)`) differs from depth `fog_light_color` (`horizon`) and the aerial-perspective sky sample.
- **Fix:**
  - Use `fog_density = 3.0/visibility` (blizzard 0.043, fog 0.015).
  - Tie `volumetric_fog_length` to weather: CLEAR 64, FOG 160, BLIZZARD 96. Set `volumetric_fog_detail_spread = 2.0` so froxels are spent near the camera.
  - Use one fog colour for both systems, and set `fog_aerial_perspective = 0` in FOG and BLIZZARD, so distant silhouettes fade into flat white-grey instead of the sky texture.
  - In a blizzard, whiteout colour should be close to the snow luminance, sRGB ≈ (200,205,210), not (118,…).

### 8. Morning fog is mauve and has no ground-hugging structure
- **Screenshot:** spring_fog_0700. Fog/sky rgb(153,151,159) hue 258°, road hue 310°, building hue 330°. Style reference: `#9FA9A2` grey-green, "ground-hugging".
- **Root cause:**
  - `horizon` still carries about 20 % of `horizon_twi` orange at 16° elevation, blended with blue-grey, which gives magenta.
  - Spring tint (0.94, 0.98, 0.99) removes red far too weakly.
  - `fog_height_density = 0`, so fog is uniform in height and the sky above is as foggy as the road.
- **Fix:**
  - Add a per-weather fog colour: FOG (0.62, 0.66, 0.64) linear-ish, RAIN (0.55, 0.58, 0.60), BLIZZARD (0.78, 0.80, 0.83). Blend it with sun colour by only `sun_energy*direct_scale*0.2`.
  - For FOG, set `fog_height = 8.0`, `fog_height_density = 0.12`, and add a large `FogVolume` (height 12 m, falloff at the top) so rooftops and trees poke out and the sky stays brighter.
  - With #4 fixed, the 07:00 sun is at 5°. Give it a sun-scatter glow through the fog: `fog_sun_scatter 0.5` and `volumetric_fog_anisotropy 0.6` for FOG.

### 9. Exposure and tonemap are flat and grey on clear days
- **Screenshots:**
  - summer_clear_1000: p99 luma 167; sunlit wall 0.57; nothing near white.
  - elevated_vista: p1–p99 only 108–170, near-ground sat 0.12.
- **Root cause:**
  - `tonemap_exposure 1.1` combined with `agx_white 13` compresses highlights.
  - SSIL intensity 1.4 and SDFGI lift the shadows.
  - Haze uses the combined volumetric density 0.0015 plus `horizon_haze 0.45`. At 110 m that is already about 15 % grey veil, and it starts at the camera.
- **Fix:**
  - `tonemap_agx_white ≈ 6–8`, `agx_contrast 1.15` for CLEAR (0.95 for OVERCAST/FOG, as the style guide itself says), exposure calibrated so a 0.35-albedo concrete in full sun lands around sRGB 185–200.
  - `ssil_intensity 0.8`.
  - CLEAR `volumetric_fog_density 0.0003`, with humidity haze carried by depth fog starting at 300 m (`fog_depth_begin`/`fog_depth_curve`, or height fog). Aerial perspective should start in the distance, not in front of the lens.
  - Add a histogram check to the capture harness: clear-day p99 should be ≥ 220 and p1 ≤ 35.

### 10. Night: ground can't be read, stars are blocky and too many, clouds glow, windows cast no light
- **Screenshot:** summer_clear_night_2300.
  - Ground 0.05–0.07, road rgb(7,10,14).
  - Stars are uniform square cells (`floor(dir*340)`), 0.19 % of sky pixels, far more than the Bortle 4–5 sky of a 15 k town.
  - Clouds render as light-grey streaks (crop at x0–140, y290–390).
  - Wall around the windows is 0.08 while the windows themselves are 0.91, with no spill and no bloom.
- **Root cause:**
  - Moon energy of at most 0.16 with the moon behind the camera.
  - In the sky shader, `cloud_col` floors at `mix(shadow, light, 0.35)` with no night term.
  - Stars use hard `step()` on a cell hash, with no size or brightness distribution.
- **Fix:**
  - Moon energy 0.35–0.5 at full phase, colour (0.62,0.70,0.88). Add a night ambient floor of about (0.020,0.026,0.040) × `ambient_light_energy` 1.0. Target road luma about 25–35/255 at 2.4 exposure.
  - Clouds: multiply `cloud_col` by `max(sun_up_luma, moon_energy*0.6 + 0.03)`, and add a warm sky-glow from town light pollution on the underside of the cloud deck (rgb 0.05,0.035,0.02 × cover).
  - Stars: brightness from `pow(hash, 40)`, a disc `smoothstep` inside each cell with a jittered centre, cell size ×2 finer, density ×0.4, and fade toward the horizon (`smoothstep(0.05,0.5,up)`) to fake light pollution.
  - Windows: a `glow_threshold` near 0.9 is fine, but switch to `GLOW_BLEND_MODE_ADDITIVE` with intensity 0.3, which actually produces halos. Add a cheap `OmniLight3D` or baked emissive spill per lit façade from the window workstream.
  - Add a streetlight test prop (sodium/LED `#FFC98A` spot at 6 m) to prove the warm/cool night contrast the style guide requires.

### 11. Cloud layer: radial horizon streaks, almost no cumulus on clear days, and 8-bit banding
- **Screenshots:**
  - autumn_overcast_1500, spring_rain_1100 and winter_snow_0900: streaks converge on the centre of the horizon.
  - summer_clear_1000: effectively cloudless, 2 slivers.
  - Summer sky column: 13 steps over 420 rows, runs up to 59 px.
- **Root cause:**
  - `cuv = dir.xz/up*0.35` is a flat-plane projection that goes singular at the horizon.
  - `smoothstep(1-coverage, 1, fbm)` with coverage 0.28 needs fbm > 0.72, which 5-octave value noise rarely reaches.
  - No dithering.
- **Fix:**
  - Project onto a curved dome: `cuv = dir.xz / (up + 0.25)`, or intersect a sphere of radius R_earth+2 km. Fade clouds with `smoothstep(0.0, 0.2, up)` into the horizon haze colour.
  - Remap density with `density = smoothstep(0.5 - coverage*0.5, 0.5 - coverage*0.5 + 0.25, fbm)`, which makes CLEAR 0.28 give about 20 % cumulus.
  - Add a domain-warped second fbm for billowy shapes, and cheap two-tap lighting toward the sun (`fbm(cuv + sun_dir.xz*0.05)` difference) for sunlit tops and grey bases. Posterize alpha into 4–6 soft steps to get the painted TLD look on purpose.
  - Overcast: a separate low-frequency stratus layer with darker undersides, not the same cumulus noise at 95 % cover.
  - Add `COLOR += (hash21(FRAGCOORD.xy) - 0.5)/255.0;` dither at the end of `sky()` to remove banding.

### 12. Seasons and transitions don't differ enough, and several values pop
- **Screenshots:**
  - autumn_overcast_1500 vs spring_rain_1100: brick 0.54 vs 0.52, sky 0.58 vs 0.57, both green grass. Autumn doesn't read as autumn.
  - winter_snow_0900: violet sky and pink snow instead of a cool blue-white.
- **Root cause:**
  - `season_profiles` tint only lerps 25 % into the sky colours and never reaches the sun, ambient or fog.
  - `sp.saturation`, `sp.tint`, `sp.haze`, `wp.aerial` and `wp.sky_affect` bypass `_blend`, so they snap on change.
  - Particle `emitting` booleans switch instantly.
  - The test diorama never consumes `season_foliage` or `wetness`.
- **Fix:**
  - Route every profile value, including colours (per channel), through `_blend`.
  - Apply the season tint to `sun.light_color` (autumn 1.0,0.94,0.85; winter 0.93,0.96,1.0) and to fog colour.
  - Winter overcast ambient should be cool (`#DCE6EE` per the style guide).
  - Drive precipitation `amount_ratio` from a blended `precip` over the transition time, and ramp clouds before precipitation starts (clouds lead by about 30 %).
  - In `test_diorama.gd`, respond to `wetness` (albedo ×0.6, roughness → 0.25 on road; enable SSR) and `season_foliage` (canopy lerp toward `#C8622A`/ochre at 0.75, trunk-only at 1.0), so the atmosphere grade can actually be judged against it.
  - Fix shadow detachment at building bases (summer_clear_1000 crop: lit grass gap between wall and shadow): `sun.shadow_normal_bias 0.6`, `shadow_bias 0.02`, and check SSAO radius 1.5 / intensity 2.0 so bases are grounded.

---

## 3. Shots required for next iteration

Use the same framing for the A/B shots so they can be compared directly. **Label every shot with clock time, and state DST.**

1. **Same-framing weather matrix at 12:00 clock time, summer:** CLEAR, OVERCAST, RAIN, FOG, and SNOW/BLIZZARD in winter. Proves direct-light scaling (#1) and weather separation.
2. **Golden hour, correct time:** summer 19:30 CDT (sun about 10°) *and* 20:25 CDT (sunset). Two framings each: toward the sun (WNW) and away from it (ESE), to check azimuthal sky colour and the Belt of Venus.
3. **Winter clear sunset 16:30 CST, looking away from the sun over snow:** shaded snow must read blue.
4. **Blue hour/civil twilight:** summer 21:00 CDT and winter 17:00 CST, with windows starting to glow.
5. **Night, three variants:**
   - Clear with the moon *in frame* (camera toward the moon's azimuth).
   - Moonless or new-moon phase.
   - Overcast night with warm town sky-glow.
   - Plus one shot with a streetlight prop.
6. **Spring fog at 06:45 CDT (sun about 3–5°), looking toward the sun:** shows fog sun-scatter and height layering (rooftops or tree tops above the fog).
7. **Rain close-up:** camera 3 m from a wall with dark background (to read the streaks) and a wet road shot looking toward a bright sky (to read specular response).
8. **Blizzard, two distances:** a building at 30 m (should be barely visible) and 80 m (gone), plus a wide shot with the horizon to prove there's no fog seam.
9. **Snow (non-blizzard), close:** flakes against dark brick and against the sky, to check flake size and that they don't read as stars.
10. **Elevated vista in CLEAR at 10:00 and OVERCAST at 15:00 CDT:** aerial perspective should start past 300 m, and contrast should differ between the two.
11. **Autumn clear 16:00 CDT with foliage colour on:** the autumn grade on its own.
12. **Transition proof:** a 6–10 frame strip (one frame every 2 s) of `WorldState.apply(summer, CLEAR→RAIN, 15:00, transition=20)`, and one of an hour sweep from 18:00 to 22:00 CDT at 30-minute steps. No pops in saturation, tint, fog aerial perspective, or particle density.
13. **Particle carry-over regression:** capture BLIZZARD, then CLEAR, back-to-back at the harness's default warmup. The CLEAR frame must show zero particles.
14. **Histogram sidecar:** for every capture, emit p1/p50/p99 luma, clipping % and median saturation (a JSON next to the PNG), so tuning can be checked against the targets in #3, #9 and #10.
