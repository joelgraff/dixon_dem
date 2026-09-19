# Atmosphere critique — iteration 2

Reviewer: independent lighting/art director (evaluation only; no project files edited except this critique)
Inputs: 26 captures in `captures/atmosphere/iter2/`, `game/atmosphere/atmosphere.gd` (mtime 18:59, captures 19:00–19:01, so the captures do match this code), `shaders/sky.gdshader`, `game/autoload/world_state.gd`, `docs/atmosphere_notes.md`.
Method: every claim below is measured with PIL/scipy (sRGB 8-bit values, named regions), not eyeballed. Solar positions are recomputed independently with a NOAA-style algorithm and compared against the rig's own formula.

---

## 1. Scores

| # | Category | iter1 | iter2 | Why |
|---|---|---|---|---|
| 1 | Lighting & atmosphere | 3 | **4** | Daylight is genuinely fixed (overcast wall 74 vs clear 91, correct direction). But night is exposed like dusk (overcast night sky 138/255), winter sunset crushes 27 % of the ground to ≤5 luma, golden hour isn't warm, and the blizzard is less fogged than the snow shower. |
| 2 | Materials & surfaces (weather response) | 3 | **5** | Wet road reads wet (SSR + roughness), snow cover whitens the ground. Still: no snow on roofs or building tops, autumn canopy is salmon pink, and winter CLEAR sunset shows no snow at all despite `snow_cover = 0.6`. |
| 3 | Color & palette | 3 | **5** | Midday is believable Illinois (green grass, red-brown brick, blue zenith). Golden hour is white, not golden (sky beside the sun: sat 0.07). Blue hour is salmon in every direction. Night is a grey wash. |
| 4 | Form, scale & proportion (atmospheric) | 4 | **3** | Regression. Rain streaks are 76–574 px long (5–8 m in world scale). Clouds are single blobs covering a third of the sky, collapsing to giant shapes near the zenith. Mist billboards read as 1.2 m cotton balls, up to 4.9 % of the frame. Snowflakes are still round dots indistinguishable from stars. |
| 5 | Composition & believability | 3 | **4** | `bluehour_summer_2100` and `matrix_summer_clear_1200` almost read as real. The blizzard reads as flat fog, the night shots as dusk, and the "clear" sky carries a cartoon cloud that belongs in a different game. |
| 6 | Technical artifacts | 3 | **4** | Fixed: particle carry-over, peter-panning, most 8-bit banding. New: hard posterized cloud contours (1.34 % of clear sky pixels at \|∇L\| > 6, max 58), clouds glowing at night (cloud 133 vs sky 57), 27 % crushed blacks, faint 12 px ground striping. |

**Average 4.17 — FAIL** (bar: all ≥ 7, average ≥ 8). Real progress — roughly half the iter1 root causes are genuinely fixed — but three of the fixes overshot into new regressions, and the two biggest weather states (blizzard, snow) still don't read.

---

## 2. Verification of every iter1 must-fix

| # | iter1 must-fix | Verdict | Evidence |
|---|---|---|---|
| 1 | Direct sun at full strength under cloud | **FIXED** | Same-framing matrix at 12:00: wall luma clear 91.1 → overcast 73.7 → rain 82.4, wall/side ratio 0.87/0.82/0.86. Direction is now correct and `direct_scale` is a real knob. Caveat: the overcast sky (196) is now *brighter* than the clear sky (153), so overcast reads as the higher-key frame. |
| 2 | Fog painted over the whole sky | **MOSTLY FIXED** | `fog_sky_affect` 0.1–0.35 for CLEAR/OVERCAST/SNOW; clear zenith rgb(127,151,182) with a real gradient. But it swung too far for FOG/BLIZZARD: at 70 m visibility the blizzard sky is never whited out (`sky_affect = 0.0`, `vol_sky_affect = 0.3`), which is exactly why there's no whiteout (see fix 2 below). |
| 3 | Crushed, over-saturated twilight | **PARTLY — new regression** | Golden hour is no longer over-saturated (sky/ground gap 1.2–1.7 stops, was > 5). But `winter_sunset_1630_away` now has **27.3 %** of the lower frame at ≤ 5 luma, foreground rgb(4,5,11) — worse crush than iter1 (0.11 %). |
| 4 | Clock time vs solar time | **FIXED, verified** | Independent NOAA recomputation: max error across 12 shots is **1.1°** elevation / 0.8° azimuth (autumn 16:00); most are < 0.2°. Summer 19:30 CDT now gives 10.0° elevation, matching reality exactly. |
| 5 | Rain/snow unreadable | **RAIN OVERSHOT, SNOW STILL BROKEN** | Rain: 74–94 streaks over 20 px, median 76–108 px, max 574 px, 3 px wide, covering 5.9 % of pixels — reads as scratches on the lens, not rain. Snow: `matrix_winter_snow_1200` has ~21 discernible flakes in a 1600×900 frame; `matrix_winter_blizzard_1200` has 48 dots of 2–3 px. Blizzard has no visible precipitation at all. |
| 6 | Particle carry-over / hard quads | **CARRY-OVER FIXED; QUADS WORSE** | `regression_b_clear_immediately_after` is clean — zero particles. But the now-visible mist billboards are giant soft discs: largest single blob 71 049 px = **4.9 %** of the fog frame, 3.4 % in `blizzard_wide_horizon`, 8 blobs > 2000 px in `spring_fog_0700_toward_sun`. |
| 7 | Fog volume seam / wrong density scaling | **SEAM FIXED, DENSITY INVERTED** | No seam is measurable in the blizzard column profile. But the spec table is now upside down: SNOW (1200 m visibility) hides a ~300 m treeline at **0 %** contrast, while BLIZZARD (70 m visibility) still shows a far ridge at **22.4 %** contrast and a 30 m building at only 9.6 % (should be ~27 %). |
| 8 | Mauve fog, no height structure | **HALF DONE** | Fog hue is now neutral (fog wall hue 187, sat 0.03) instead of magenta. But `fog_height_density` is still `0.0` — no ground-hugging layer, no rooftops above the fog, and the requested proof shot doesn't contain a building. |
| 9 | Flat, grey clear days | **FIXED** | `matrix_summer_clear_1200` p1/p50/p99 = 60/145/**214** (target was p99 ≥ 220, p1 ≤ 35 — highlights now land, shadows still lifted). `elevated_clear_1000` shows real aerial perspective: 66.8 % desaturation from near to far ground. |
| 10 | Night unreadable, stars, glowing clouds | **OVERCORRECTED; CLOUD GLOW REMAINS** | Ground is readable (moonless 21 vs iter1's 7), and windows now spill onto the wall (wall 20 px below a window 50 vs 29 far from windows). But `night_overcast_2200` sky is 138/255 and ground 46 — that's dusk, not 22:00. On a *clear* night the clouds sit at 133 against a 57 sky — still glowing, now with hard edges. |
| 11 | Cloud streaks, no cumulus, banding | **STREAKS+BANDING FIXED, SHAPE REGRESSED** | The radial streaking is gone and dither works (longest flat sky run 39 px on clear, 8 px at blue hour, was 59). But `density = floor(density*5)/5` plus `cuv = dir.xz/(up+0.25)` gives hard 5-step contours and cloud cells that blow up near the zenith: `night_clear_moon_in_frame_2300` is one continuous posterized cloud mass across the whole frame at `cloud_coverage = 0.28`. |
| 12 | Seasons/transitions pop, diorama ignores globals | **PARTLY** | Profiles (including Colors) now go through `_blend`, and the diorama responds to `wetness`/`season_foliage`. `season_profiles` values (`saturation`, `haze`, `tint`) are still read straight from `sp` each frame, so a season change still snaps. **No transition strip was captured at all**, so the smooth-blend claim is unproven. |

### Invalid or unusable proof shots (flagged as requested)
- `rain_closeup_wall` — contains no wall; it's an open hillside. The shot can't show rain against a dark background.
- `snow_closeup_brick` — contains no brick; it's an empty snowfield. Flakes are 8 white dots in the sky, i.e. exactly the "reads like stars" failure it was meant to disprove.
- `night_moonless_0200` — **not moonless**. With the anti-sun moon model, at 02:00 on day 172 the moon sits at 67.7° elevation with `phase = 0.89` → `light_energy = 0.407`, the brightest the moon ever gets in this rig. This frame proves the opposite of its label.
- `blizzard_near_30m` / `blizzard_wide_horizon` — both refute their own purpose (see fix 2).
- `elevated_clear_1000` vs `elevated_overcast_1500` — two variables changed (weather *and* hour, 48.6° vs 58.9° sun). Usable as mood shots, not as an A/B.
- Missing entirely from the iter1 request: the transition strip, the hour sweep, the streetlight/night-prop shot, and the per-capture histogram sidecars.

---

## 3. Must-fix list (priority order)

### 1. Rain streaks are 5–8 m long — `TRANSFORM_ALIGN_Z_BILLBOARD_Y_TO_VELOCITY` scales the quad by velocity
- **Screenshots:** `matrix_summer_rain_1200`, `rain_wet_road`, `rain_closeup_wall`. Median streak 76–108 px, longest 574 px (38° of the frame), 5.9 % of all pixels.
- **Root cause:** `atmosphere.gd:_build_rig` gives `RainStreaks` a 0.02 × **0.9 m** quad and Y_TO_VELOCITY alignment. That alignment multiplies the mesh's Y extent by the velocity magnitude (~6–9 m/s here), so each drop renders 5–8 m long.
- **Fix:** base quad `Vector2(0.015, 0.12)`; keep Y_TO_VELOCITY but expect the ×6–9 stretch to give ~0.7–1.1 m streaks (about 12–25 px at 3 m), which is what a 1/50 s exposure of rain actually looks like. Drop `albedo alpha` from 0.55 to ~0.35 and let colour come from the sky (`Color(0.70,0.75,0.82)` is fine). Then re-tune `amount`: with short streaks you need ~3500–4500, not 2200.
- **Verify:** median streak height 10–25 px, bright-pixel coverage 1.5–3 %.

### 2. The blizzard is not a whiteout, and the snow shower is fogged harder than the blizzard
- **Screenshots:** `matrix_winter_blizzard_1200` (far treeline at 12.4 % contrast), `blizzard_wide_horizon` (ridge at **22.4 %**), `blizzard_near_30m` (30 m building at only 9.6 %), versus `matrix_winter_snow_1200` (a ~300 m treeline at **0 %** contrast).
- **Root cause:** two separate errors.
  - BLIZZARD sets `sky_affect = 0.0` and `aerial = 0.0` (an over-literal reading of iter1's fix #7), so the *sky* is never fogged. A horizon line survives, and any silhouette against the sky stays visible no matter how dense the ground fog is.
  - The near-field volumetric density is doing most of the work in every weather, so SNOW's 0.0018 + `vol_length 90` kills 300 m of visibility while BLIZZARD's depth fog can't finish the job on the sky.
- **Fix:** BLIZZARD `sky_affect = 1.0`, `vol_sky_affect = 1.0`, `aerial = 0.0`, `fog_color` ≈ (0.80,0.82,0.85); FOG `sky_affect = 1.0`, `vol_sky_affect = 0.8`. SNOW: `fog_density` 0.0018 → 0.0006, `visibility` 1200 → 1800, `vol_length` 90 → 70. Add an assert-style dev check: render a 1 m² white card at 0.5×, 1×, 2× the stated visibility and confirm contrast ≈ 61 %, 5 %, 0.2 %.
- **Verify:** blizzard — nothing beyond 70 m at > 3 % contrast, 30 m building at 20–30 %; snow — treeline at 300 m still at 25–40 %.

### 3. Snow is still invisible, and what shows reads as stars
- **Screenshots:** `matrix_winter_snow_1200` (~21 flakes in frame), `snow_closeup_sky` (41 round dots, all the same size and brightness), `snow_closeup_brick` (invalid framing), blizzard frames (48 dots, 2–3 px).
- **Root cause:** a 6 cm round sprite spread through a 12 × 2 × 12 m box is a sub-pixel dot beyond ~8 m, and `amount_ratio = precip` (0.6) throws away 40 % of the 1800 particles. In blizzard, the streak mesh (0.03 × 0.25 m) is aligned Y_TO_VELOCITY at ~14 m/s → thin 3 m smears that are near-invisible against white fog, which the notes already admit.
- **Fix:** two layers, as in iter1's fix #5 (still not implemented).
  - Near: box extents 4 × 3 × 4 m, offset 4 m along camera forward, `amount` 1200 (SNOW) / 2500 (BLIZZARD), flake 0.10–0.14 m with per-particle `scale_min/max` 0.6–1.5 and a slow `angular_velocity` so flakes tumble.
  - Far/blizzard: a screen-space snow-streak overlay (a panning noise texture on a full-screen quad, alpha driven by `precip * wind_strength`). Against a whiteout, blowing snow must read as *dark-and-light motion*, not as white dots on white.
  - Give flakes a slight grey tint (0.88,0.90,0.94) so they stay visible against a white sky, and vary alpha 0.5–0.95 by depth.
- **Verify:** 250–600 distinct flake blobs per frame in SNOW; in BLIZZARD, visible horizontal motion streaking across ≥ 30 % of the frame.

### 4. Night is exposed as dusk
- **Screenshots:** `night_overcast_2200` (sky 138/255, ground 46, p50 72), `night_clear_moon_in_frame_2300` (p50 132), `night_moonless_0200` (sky 72, ground 21).
- **Root cause:** `tonemap_exposure = lerp(2.6, 1.6, day_t)` peaks at night *and* `ambient_light_energy` was flattened to 1.0–1.6 *and* moon energy went 0.16 → 0.45. Three compensations stacked.
- **Fix:** night exposure back to ~1.9–2.1 (`lerp(2.0, 1.6, day_t)`), moon peak 0.45 → 0.25, and add an explicit night ambient scale: multiply `ambient_light_energy` by `lerp(1.0, 0.45, night_factor)`. Overcast night must be *darker* than clear night, not brighter — scale the sky's own night colour by `lerp(1.0, 0.35, overcast_t)` instead of letting the grey-flattening lift it.
- **Targets:** moonlit clear night — ground 18–28, sky 25–40; moonless — ground 8–14; overcast night — sky 15–25 (windows and streetlights should then be the brightest thing in frame by 4–5 stops, which is the whole TLD night read).

### 5. Winter sunset crushes a quarter of the frame to black, and the snow disappears
- **Screenshot:** `winter_sunset_1630_away` — 27.3 % of pixels below y=500 are ≤ 5 luma; foreground rgb(4,5,11); midground rgb(30,33,46); and no snow is visible anywhere although `snow_cover = 0.6` for winter CLEAR.
- **Root cause:** the sun's falloff was tightened to `inverse_lerp(-1.0, 15.0, elev)` so at −0.7° direct light is ~0, while ambient now comes only from a dim sky (`ambient_light_energy = 1.0` at `direct_scale = 1`). Nothing replaces the lost sun. The sky shader's `ground_color` floor (0.15) is applied to the radiance map, but with `snow_cover` at 0.6 the ground lerps to 0.33 — far below what a snowfield bounces.
- **Fix:** hold ambient up through twilight — `ambient_light_energy *= lerp(1.0, 1.9, twilight_strength)`; raise the snow ground-radiance stop to `Color(0.62,0.64,0.68)` at `snow_cover = 1`; and add a small sky-coloured fill (a second, shadowless DirectionalLight3D pointing down at 0.05–0.1 energy tinted from the zenith) for elevations between −6° and +3°.
- **Target:** ≤ 2 % of pixels at ≤ 5 luma in any shot; sunlit-less snow at sunset should read 45–70 luma with B > R.

### 6. Clouds: posterized contour map, wrong scale, collapsing at the zenith
- **Screenshots:** `night_clear_moon_in_frame_2300` (one cloud mass across the entire frame at coverage 0.28), `matrix_summer_fog_1200` and `golden_away_from_sun_1930` (topographic-map contours), `matrix_summer_clear_1200` (13 luma levels hold > 2 % of sky pixels each; 1.34 % of sky pixels at \|∇L\| > 6; max gradient 58).
- **Root cause:** `density = floor(density * 5.0) / 5.0` quantises alpha into 5 hard steps, and `cuv = dir.xz / (up_c + 0.25) * 0.35` makes the projected UV shrink toward the zenith, so one noise cell covers the whole upper sky.
- **Fix:**
  - Replace the hard `floor()` with a soft quantiser: `density = mix(density, floor(density*6.0)/6.0, 0.35)` and then `smoothstep` the alpha edge over ~0.06.
  - Fix the projection: intersect the view ray with a cloud shell — `float t = (CLOUD_H) / max(up, 0.06); vec2 cuv = dir.xz * t * 0.004;` with `CLOUD_H ≈ 1500.0`. Cells then stay a constant world size and get *smaller* toward the horizon, which is the correct perspective.
  - Add a second, domain-warped octave for billow, and shade tops/bases with a two-tap density difference toward the sun so clouds have a light side.
- **Verify:** on `cloud_coverage = 0.28` the sky should be 20–35 % covered with several separate cumulus, no single blob wider than ~40 % of the frame, and < 0.2 % of sky pixels at \|∇L\| > 6.

### 7. Clouds still glow at night
- **Screenshot:** `night_clear_moon_in_frame_2300` — cloud 133 vs clear sky patch 57 (sky p90 − p10 = 75.8). `night_moonless_0200` and `night_overcast_2200` show the same lift.
- **Root cause:** `night_light = max(sun_up, moon_energy*0.6 + 0.03)` → 0.27 with a full moon, multiplied into a near-white `cloud_light_color`. The night sky itself is ~0.02, so clouds land an order of magnitude brighter.
- **Fix:** tie clouds to sky radiance, not to a floor — `float sky_lum = dot(mix(horizon_color, zenith_color, sky_t), vec3(0.2126,0.7152,0.0722)); cloud_col *= clamp(max(sun_up, moon_energy*0.35) , sky_lum*0.9, 1.0);`. Under a full moon, clouds should be a *silvery grey slightly brighter* than the sky (ratio ≈ 1.3), not 2.3×. Keep the town-glow term but cap it at `0.02 * cloud_coverage`.

### 8. Golden hour isn't golden; blue hour is warm in every direction
- **Screenshots:** `golden_toward_sun_1930` — sky beside the sun rgb(224,212,208), hue 14 but **sat 0.07**; ground hue 20 sat 0.40 (warm only from the sun's own light colour). `bluehour_summer_2100` — the horizon band measures hue 15 / sat 0.32 at frame left (NW, correct), hue 11 at centre (N), and hue 352 at frame right (NE) — warm all the way round, though the sun is at azimuth 307°.
- **Root cause:** `twilight_strength = 1 - |elev|/12` is only 0.17 at 10° elevation, and the warm mix is `pow(sun_side, 2.2) * near_horizon * twilight_strength` → max 0.15 at golden hour. At blue hour the same exponent leaves 22 % warmth at 90° from the sun, and the Belt-of-Venus colour (0.72,0.56,0.62) is itself pink, so the anti-sun side never goes cool.
- **Fix:** separate the two effects.
  - Warm band: drive it from `clamp(1.0 - elev/18.0, 0, 1)` (so it's still 0.45 at 10°) and sharpen the azimuth term to `pow(sun_side, 5.0)`. Boost saturation as well as hue — mix toward `horizon_twilight_color` in linear space and add `+0.12 * warm_amount` to the red channel.
  - Anti-sun: make it genuinely cool — earth shadow `vec3(0.28,0.31,0.42)` below `up ≈ 0.06` with a narrow pink Belt of Venus (0.80,0.62,0.66) only in `up ∈ [0.06, 0.16]`, both gated by `pow(1.0 - sun_side, 3.0)`.
  - Warm the *light* too: at 10° elevation `sun.light_color` should be ≈ (1.0, 0.78, 0.55), not the current lerp result near (1.0, 0.86, 0.72).
- **Verify:** at 19:30 the sky within 30° of the sun azimuth should measure sat ≥ 0.25 with hue 20–35; at 90° away, sat ≤ 0.12 with hue > 200.

### 9. Mist billboards now read as cotton balls
- **Screenshots:** `matrix_summer_fog_1200` (largest soft blob 71 049 px = 4.9 % of frame), `spring_fog_0700_toward_sun` (8 blobs > 2000 px, one obvious white disc mid-frame), `blizzard_wide_horizon` (one 49 k-px disc).
- **Root cause:** the fix for invisibility (GradientTexture2D + MIX + `TEXTURE_FILTER_LINEAR`) applied equally to the 1.2 m mist quads, which sit 2–6 m from the camera and are now clearly visible discs. `proximity_fade_distance = 1.5` and `distance_fade_max_distance = 3.0` only hide the ones practically touching the lens.
- **Fix:** drop the mist billboards and use `FogVolume` boxes with a `FogMaterial` whose `density_texture` is a `NoiseTexture3D` (seamless, 3–4 octaves), scrolled by `wind_strength`. That gives genuinely volumetric wisps that can't show an edge. If billboards must stay as a stopgap: quad 4–6 m, `amount` 12, albedo alpha ≤ 0.06, `distance_fade_min/max` 4/12 m, and randomised rotation.

### 10. FOG has no vertical structure, and the fog states are over-dense near the camera
- **Screenshots:** `matrix_summer_fog_1200` — the 40 m building is at 24.8 % contrast where 200 m visibility predicts ~55 %, and the wall is fully desaturated (hue 187, sat 0.03). `spring_fog_0700_toward_sun` — no rooftops or tree crowns emerge above a fog layer; everything is uniformly veiled.
- **Root cause:** `fog_height_density = 0.0` (iter1 fix #8 was only half applied) and `volumetric_fog_density = 0.02` over a 160 m volume, on top of depth fog at `3/200`.
- **Fix:** FOG — `fog_height = 9.0`, `fog_height_density = 0.14`, `volumetric_fog_density = 0.008`, `fog_sun_scatter = 0.5`, `volumetric_fog_anisotropy = 0.6`. Add one `FogVolume` slab (60 × 12 × 60 m, camera-following) with a vertical density ramp so the top edge of the layer is visible against sunlit rooftops.
- **Verify:** at 07:00 the tops of the 12 m buildings and the tree crowns should sit clear of the fog while their bases are lost.

### 11. Overcast reads higher-key than clear, and the clear sky washes out near the horizon
- **Screenshots:** `matrix_summer_overcast_1200` — sky 196 vs clear's 153, sky/ground 2.28 vs 1.20. `matrix_summer_clear_1200` — the sky 30° above the horizon is rgb(175,173,177), **sat 0.02**, a white band; zenith sat is only 0.30.
- **Root cause:** overcast lifts `ambient_light_energy` to 1.6 while the grey sky is painted at high value, and `tonemap_exposure` only drops 4 % (`lerp(1.0,0.92,overcast_t*0.5)`). Separately, `horizon_haze = 0.45` for summer mixes 27 % pure `horizon_color` into everything within ~14° of the horizon.
- **Fix:** overcast exposure multiplier → 0.78, grey sky value → ~0.45 of clear-sky luminance, and keep the ground/sky ratio near 2.8–3.5 (an overcast sky really is that much brighter than the ground; what's wrong is that the *ground* got darker instead of the sky getting flatter). Reduce `horizon_haze` to 0.22 (summer) / 0.12 (winter) and apply it with `pow(haze_t, 2.0)` so it hugs the last 5° instead of the last 14°. Deepen `zenith_day` toward (0.08, 0.20, 0.52).
- **Verify:** clear noon — zenith sat ≥ 0.40, sky 15° above horizon sat ≥ 0.12; overcast sky 150–175 with ground 85–95.

### 12. Season grade and transitions are still unproven, and the docs are now misleading
- **Screenshots:** `autumn_clear_1600_foliage` — canopy is salmon pink (a colour that doesn't exist in an Illinois October; reference is `#C8622A` orange-red over green-brown grass) while the grass stays summer green. No transition capture exists at all.
- **Root cause:** `season_profiles` values are still read directly (`sp.saturation`, `sp.haze`, `sp.tint`) rather than through `_blend`, so a season change snaps; the diorama's `_CANOPY_AUTUMN` is too pink and too bright; nothing drives grass colour by season.
- **Fix:** route the three season values through `_blend` per channel; set the autumn canopy to `#C8622A` with a 25 % per-instance hue jitter and desaturate the grass toward `#6E7048` at `season_foliage ≥ 0.6`; give autumn a slightly lower sun colour temperature.
- Also: `docs/atmosphere_notes.md` still carries the **iter1** weather table (CLEAR fog 0.0015 / shadow opacity 1.0 … BLIZZARD 0.055) and an entirely stale "Known weaknesses" section claiming hard-edged quads, an undiagnosed texture bug, and that `world/world.tscn` doesn't instance the rig — all contradicted by the iter2 section at the top of the same file. Rewrite the body so a reader doesn't act on obsolete numbers.

---

## 4. Shots required for iteration 3

Same framing within each pair, one variable at a time, and label each with clock time and DST.

1. **Rain scale proof:** camera 2.5 m from the *dark brick wall* (wall filling ≥ 60 % of frame), RAIN at 12:00 — streaks must read 10–25 px. Plus a matching CLEAR frame from the identical camera for the no-precip baseline.
2. **Snow scale proof:** camera 2.5 m from the same dark wall, SNOW at 12:00 and BLIZZARD at 12:00 — flake count and motion must differ visibly between the two.
3. **Blizzard visibility ladder:** one camera, the same building at 15 m / 30 m / 60 m / 120 m in four frames — contrast must fall off monotonically and be ≈ 0 by 70 m, with no horizon line anywhere in frame.
4. **Snow-shower visibility control:** the elevated vista in SNOW at 12:00 — the treeline at ~300 m must still be readable (25–40 % contrast).
5. **Cloud shape set (same weather, four look directions):** CLEAR summer 12:00 facing N / E / S / W, plus one frame pitched to the zenith. Proves cell scale is constant and nothing blows up overhead.
6. **Night ladder, one camera, one framing:** CLEAR 21:00 (blue hour) → 22:00 → 23:00 (moon up) → 02:00 with the moon forced below the horizon (pass an explicit `day_of_year` that makes `phase` ≈ 0, or add a `moon_energy_override` for the shot) → OVERCAST 23:00. Each step must be visibly darker than the one before, and the moonless frame must actually be moonless.
7. **Night with practicals:** the same night framing with a streetlight prop (sodium `#FFC98A`, 6 m, one omni) so the warm/cool contrast can be judged.
8. **Golden hour pair, corrected:** summer 19:30 CDT toward the sun and away from it, from the *same* camera position (one rotation only). Repeat at 20:15 CDT. Sky saturation on the sun side must be ≥ 0.25.
9. **Winter sunset over snow:** 16:30 CST, away from the sun, camera showing a large snowfield — shaded snow must read 45–70 luma and blue, with ≤ 2 % crushed pixels.
10. **Fog height proof:** spring 07:00 with the two buildings and the treeline in frame, camera at 1.7 m — rooftops and crowns above the fog layer, bases lost.
11. **Overcast/clear exposure pair:** identical camera, identical hour (12:00), CLEAR and OVERCAST only — the only change being weather.
12. **Transition strip (still owed):** 8 frames at 2 s intervals through `WorldState.apply(summer, CLEAR→RAIN, 15:00, transition=20)`, and 8 frames of an 18:00→22:00 CDT hour sweep. No pops in saturation, tint, fog or particle density.
13. **Histogram sidecars (still owed):** a JSON beside each PNG with p1/p50/p99 luma, % ≤ 5, % ≥ 250, median saturation, and the shot's sun elevation/azimuth. Without these, every claim in the next round has to be re-measured from scratch.
