# Materials critique — iteration 2

Critic: independent art director. Scope: `captures/materials/iter2/` (19 shots), with sources checked in
`game/materials/` and `data/raw/textures/shots_iter2.json`. The numbers below were measured with PIL on
the captures. I did not take the builder's claims in `materials_notes.md` at face value.

## Scores (materials context)

| # | Category | iter1 | iter2 | Why |
|---|---|---|---|---|
| 1 | Lighting & atmosphere (surface response) | 5 | 5 | Wet surfaces show no sheen or puddles, even at a grazing angle. Snow still renders as mid-grey (sRGB ~135–140). |
| 2 | Materials & surfaces | 4 | 5 | Stretched edges, rotated stone and footprint snow are fixed. New problems: brick repeats exactly, mortar is tinted the same as the brick, and the shingle courses run the wrong way. |
| 3 | Color & palette | 4 | 4 | Hues are now right but overshoot: red brick is oversaturated orange, buff brick is orange, lawn is a pale lime, siding still reads as bare wood. |
| 4 | Form, scale & proportion | 5 | 5 | Shingle course and tab sizes are plausible, but the courses run down the slope. The brick scale looks slightly small (unverified). |
| 5 | Composition & believability | 3 | 4 | The new sand-colored lot reads as a beach, not a Midwest lot. The brick looks like molded plastic. |
| 6 | Technical artifacts | 3 | 4 | Vertical tile seams remain in brick and snow. The glass is a grey veil you can see the siding through. |

**Average 4.5. FAIL** (bar: every category ≥7 and average ≥8).

## Were the iter1 fixes really made?

| # | iter1 finding | Claimed | Measured / observed | Verdict |
|---|---|---|---|---|
| 1 | Snow too dark, has footprints | multiplier added, Snow014 | No footprints now. Snow reads sRGB 134–140 (`snow_fresh_vs_sidewalk`, `overview_winter_snow`). The shot meant to compare snow with the sidewalk can't: the sidewalk is buried in snow, so snow is never measured against a known concrete value. Snow also has a tile seam at x≈800 (138→145 step). | **Partial / unproven** |
| 2 | Brick/siding seams at tile edges | zero Y offset, X offset per column | `brick_red_flat`: vertical seam at x=800 cuts bricks mid-length. The left and right halves correlate at r=0.74, so the texture repeats exactly side by side. `siding_white_flat` has the same seam at x≈805. | **Not fixed (regressed to exact repeat)** |
| 3 | stone_foundation rotated | rotation off | `stone_foundation_headon`: courses run horizontal and read correctly. | **Fixed** |
| 4 | World-XZ stretching on vertical faces | auto-triplanar | `grazing_curb_edge`, `grazing_roof_membrane_edge`: no streaks. | **Fixed** |
| 5 | Wetness invisible | stronger curve, puddles | The capture changes weather, not just wetness: wetness_0 = clear, 0p35 = **fog** (wetness 0.3), 1 = **rain** (wetness 0.85, not 1). The claimed "159→114→100" drop is mostly lighting. Asphalt ÷ lot brightness stays at 0.83 / 0.81 / 0.82, so wetness adds no visible darkening. No puddles in any shot, and no reflection in `road_rain_grazing`. | **Not fixed; claim invalid** |
| 6 | Lawn read as straw | Grass004 + tint | Hue is fixed (94° vs 92° target), but the value is far too high: sRGB 152,189,124 vs target 91,123,63; saturation 0.34 vs 0.49. It reads as a pastel golf-course lime (`grass_lawn_flat`, `overview_summer`). | **Overshot** |
| 7 | brick_red pink/washed out | Bricks005 + tint | sRGB 169,83,56, saturation **0.67** vs target 0.55. The tint multiplies the whole texture, so the **mortar is the same orange-red** and the wall looks like one molded plastic slab. There is no per-brick color variation (std at 25 m = 5.8). | **Overshot, new defect** |
| 8 | brick_buff grey | tint (1.15,0.88,0.55) | sRGB 200,158,106, hue 33°, saturation 0.47 vs target 38° / 0.40. Reads as orange cardboard, and the mortar is tinted too. | **Overshot** |
| 9 | Siding was bare plank; glass milky | WoodSiding009, darker glass | Siding measures sRGB 205,197,184 (saturation 0.10) with strong grain and knots, so it still reads as stained wood, not painted clapboard (#F1EFE8, saturation 0.04). Glass is now a 50%-grey veil (137) with the siding fully visible through it, which reads as a tinted film, not a window. | **Partial** |
| 10 | Shingles were gravel | procedural shader | `shingles_close_2m`: the course lines on the roof run **down the slope** (rotated 90°). Tab cutouts only show on the slab's edge faces. The shader header says it assumes the slope runs along world Z, and the test gable doesn't. Granules and per-tab tone are barely visible. | **Partial / wrong orientation** |

Extra checks: the "unlit" reference chips go through tonemapping (the #9A5B45 chip renders as 181,117,89), so the chart is not a valid hex reference. The chip labels also overlap and can't be read.

## Prioritized must-fix list

1. **`road_wetness_*.png`, `road_rain_grazing.png` → wet response is invisible, and the test is confounded.** Capture wetness 0 / 0.5 / 1.0 under **identical** overcast weather and hour, forcing the `wetness` global directly. In `lib/asphalt_road.tres` and `sidewalk_concrete`, raise `puddle_scale` from 0.05 to about 0.35: 0.05 gives 20 m noise cells, so a 5×3 m patch lands entirely inside or outside one. Aim for puddles covering about 30–50% at wetness 1, with puddle roughness ≤0.05 and a visible sky reflection at grazing angles.
2. **`brick_red_flat.png`, `brick_wide_3m.png` → exact repetition, seam at tile edges, mortar same color as brick.** Separate mortar from brick with a mask (derive it from AO/height or luminance of the source) and tint only the brick. Keep mortar a neutral grey-cream around #B8B0A0 so joints read darker. Add per-brick color variation: hash each brick's cell using the texture's real course height and brick length, and vary brightness ±12% and hue ±4°. Replace the column offset with an offset quantized to exactly half a brick length (measure it in texels), or turn anti-tiling off for brick and rely on the per-brick variation.
3. **`brick_red_flat.png`, `brick_buff_flat.png`, `grass_lawn_flat.png` → colors overshoot.** red: bring saturation to about 0.50–0.55 (tint around (1.05,0.70,0.58), multiplier 0.75). buff: tint around (1.02,0.92,0.72). grass: tint around (0.55,0.80,0.50) with multiplier ≤0.6 to land near #5B7B3F in value, not just hue. Verify against a **lit** grey card of known albedo (0.18 and 0.8), not unlit chips.
4. **`snow_fresh_vs_sidewalk.png` → tile seam at x≈800; snow brightness unproven.** Snow is non-directional, so use a real stochastic blend (a 3-tap hex-tiling blend or 2-sample offset blend) instead of hard per-cell offsets. Add a snow-free concrete slab and a lit 0.8 albedo reference beside the snow. Snow should come out ≥ that card and clearly brighter than concrete.
5. **`shingles_close_2m.png` → courses run down the slope; tabs only on edges.** Put a `course_axis` / rotation uniform in `shingles.gdshader`, or fix the UVs in `_gable()` in `test_materials.gd` so V follows the slope. Only put the pattern on faces with `normal.y > 0.3`, and give the eave and rake edges a plain dark fascia material.
6. **`siding_white_flat.png` → wood grain and knots read as bare wood; glass is a see-through veil.** Flatten the albedo grain (blur or high-pass remove, keeping the lap shadow line). Take roughness to about 0.55–0.65 and cut normal intensity on the grain by about 60% so it reads as painted. For glass, turn transparency off for exterior panes: opaque dark interior (sRGB about 30–45), Fresnel sky reflection, and a thin frame.
7. **`overview_summer.png`, `color_chart.png` → the lot ground (`dry_grass`) is beach sand (213,196,180).** Midwest dry turf is darker and more olive-brown (about #8C7A55). Retint `dry_grass.tres` and don't use it as the default lot ground. Use `grass_lawn` or a mixed turf instead.
8. **`snow_fresh_vs_sidewalk.png` → dark rock/grass flecks repeat in a visible grid over large areas** (`overview_winter_snow`). Cut the fleck contrast in `snow_fresh` albedo, or mask the flecks with low-frequency noise so they cluster.
9. **`brick_wide_25m.png` → the 20 m wall is a single flat orange field (std 5.8) with no macro variation, staining or grime.** On `brick_red`, raise `macro_variation_strength` to about 0.15 at scale about 0.1, and set `grime_strength` to about 0.25 with `ground_level` set correctly per instance.
10. **`color_chart.png` → the reference chart is invalid.** Chips are tonemapped and the labels overlap. Replace them with lit, surface-shaded chips of known linear albedo (0.04, 0.18, 0.5, 0.8) placed next to each swatch, with labels offset vertically.

## Required shots for iter3

- `wet_sweep_{0,050,100}.png`: same overcast weather, hour and camera, with only the wetness global changing. Include the asphalt road, sidewalk and the 0.18 grey card.
- `wet_grazing_sky.png`: camera at 0.3 m, looking along the wet road toward bright sky, to show reflections.
- `brick_red_flat_4tiles.png`: head-on, framed so at least 2×2 tile boundaries are visible, plus a 45° oblique view.
- `brick_buff_flat_4tiles.png`: same framing as above.
- `snow_vs_concrete_card.png`: snow next to snow-free concrete and a 0.8 card, overcast winter.
- `snow_wide_40m.png`: large snow field from 1.7 m eye height, to check repetition.
- `shingles_gable_front.png` and `shingles_eave_close.png`: courses parallel to the eave, tabs visible.
- `siding_window_close.png`: painted siding with an opaque window pane at 2 m and 8 m.
- `lawn_vs_card.png`: lawn next to the 0.18 card under clear and overcast light.
- `lot_ground_mid.png`: whatever the lot ground material is, at 15 m.

## Not materials' fault (lighting rig / harness)

- The clear, fog and rain presets change exposure a lot (the sky alone moves by about 5–15 sRGB between them). That undermines any cross-weather material comparison.
- Label3D text overlaps and blocks swatches (`color_chart`, `grazing_curb_edge`). Hide the labels in close-up shots.
- The sidewalk slab floats with a visible gap under it (`grazing_curb_edge`), a test-geometry issue.
- The sun disc blooms heavily in the winter overview.
