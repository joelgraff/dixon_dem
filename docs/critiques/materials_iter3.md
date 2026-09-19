# Materials critique — iteration 3

Critic: independent art director. Scope: the 17 captures in `captures/materials/iter3/`, plus
`data/raw/textures/shots_iter3.json` and the iter3 section of `docs/materials_notes.md`. Every claim below
was re-measured with PIL on the captures; builder numbers were not taken on trust.

## Scores (materials context)

| # | Category | iter1 | iter2 | iter3 | Why |
|---|---|---|---|---|---|
| 1 | Lighting & atmosphere (surface response) | 5 | 5 | 6 | The wetness sweep is finally a valid experiment (sky pixels identical across the three shots). The response is still weak: the road only darkens 12%, and the grazing sheen is a broad haze rather than a wet-road reflection. |
| 2 | Materials & surfaces | 4 | 5 | 6 | Brick, siding and mortar are much better. Shingles regressed to wide plain bands, and snow's measured albedo is still about half of spec. |
| 3 | Color & palette | 4 | 4 | 7 | brick_red 16.4°/0.568, brick_buff 36.8°/0.345, lawn 95.8° all land on the vernacular targets. |
| 4 | Form, scale & proportion | 5 | 5 | 5 | Shingle courses read at roughly 0.5 m instead of the 0.14 m the shader claims, and there are no tab cutouts. |
| 5 | Composition & believability | 3 | 4 | 6 | The lawn-lot scene reads as a place. The lawn is a flat glossy carpet at mid distance, and windows are black holes at 8 m. |
| 6 | Technical artifacts | 3 | 4 | 5 | A vertical seam remains down the center of every siding pier, snow shows rectangular patch edges, and the brick left/right correlation I measure is 0.77, not 0.46. |

**Average 5.8. FAIL** (bar: every category ≥7, average ≥8). Real progress — this is the first iteration where
the color work and the wet proof hold up — but four of the ten claims don't survive measurement.

## Claim-by-claim verification

| Claim | Measured | Verdict |
|---|---|---|
| Wetness sweep varies only wetness | Sky region is byte-identical across the three shots (mean abs diff 0.005–0.01). Same camera, weather, hour. | **Valid method** |
| Asphalt 81.3 → 75.8 → 70.1 | I measure 82.1 → 77.0 → 72.3 on the road region. Monotonic, about −12%. | **Confirmed but weak** (real wet asphalt darkens 35–50%) |
| Visible puddle and grazing sheen | The wet/dry ratio image is nearly uniform (mean 0.89, std 0.039) with a few patches down to 0.52 — some localized structure, but no readable puddle shape. `wet_grazing_sky` shows a pale haze band, not a sky reflection. | **Partial** |
| brick_red sat 0.555 / hue 16.7° | 16.4° / 0.568 / val 0.555 head-on, 16.4° / 0.600 oblique. Target #9A5B45 = 16° / 0.55 / 0.60. | **Confirmed** |
| brick_buff hue 37.0° sat 0.354 | 36.8° / 0.345 / val 0.712. Target 38° / 0.40 / 0.77 — slightly flat and dark, but close. | **Confirmed** |
| lawn sRGB (93,132,71) sat 0.463 | Under clear light I measure (126,152,109), hue 95.8°, sat 0.285; under overcast (80,90,75). The quoted number isn't reproducible in either capture, though the hue is right and it no longer reads as lime. | **Hue fixed, number not reproducible** |
| Brick correlation 0.74 → 0.46 | On the wall face of `brick_red_flat_4tiles` I measure **0.768**; brick_buff measures 0.495. Also, neither "4tiles" shot shows four tiles: the pier is about 1.2 tiles wide, so the repeat is never actually put on trial. | **Not reproduced (red), shot doesn't test the claim** |
| Snow 157–165, above a 0.8 card | The numbers are right (snow 157, card 152, dry concrete 127) but the test is invalid: **both reference cards are vertical, the snow is horizontal.** Under an overcast dome a vertical surface receives roughly half the irradiance of a horizontal one, so snow matching a vertical 0.8 card implies snow albedo ≈ **0.4–0.5**, still far under the 0.8–0.9 spec. | **Claim invalid; snow still too dark** |
| Shingle courses horizontal | Orientation is fixed, but the pattern now reads as 3–4 wide plain bands per slope (roughly 0.5 m each) with no tab cutouts and no granule texture. `shingles_eave_close` is a featureless black face (mean 40, no pattern) — the fascia guard appears to be swallowing the whole slope at that angle. | **Regression** |
| Painted lap siding | (204,198,185), sat 0.095, hue 42° with lap shadow lines and no knots. Reads as painted clapboard. | **Fixed** |
| Opaque sky-reflective glass | At 2 m the pane shows a blurred reflection, though the muddy brown band reads as smeared rather than a window. At 8 m the same pane is pure black with no frame. | **Partial / inconsistent** |
| Mortar separated from tint | Confirmed on both bricks; mortar is neutral. It is now uniformly bright and clean, which reads as new mortar rather than an 1880s–1920s block. | **Fixed, slight overcorrection** |

## Prioritized must-fix list

1. **`snow_vs_concrete_card.png` → snow is still about half the target albedo, and the proof shot can't show it.** Lay the reference cards flat, coplanar with the snow (0.2, 0.5, 0.8), plus one vertical 0.8 card for comparison. Then raise `snow_albedo_multiplier` until flat snow measures within about 5% of the flat 0.8 card and clamp so that it doesn't go over 0.9.
2. **`shingles_gable_front.png`, `shingles_eave_close.png` → shingle detail is gone.** The bands measure about 0.5 m, not 0.14 m — `face_size_m` on the gable instance doesn't match the actual panel size, so UV(0..1) is being stretched. Derive `face_size_m` from the mesh size in `_gable()`, restore the vertical tab joints (0.33 m, staggered every other course), and restrict the fascia guard to `abs(wn.y) < 0.15` so it can't consume the slope.
3. **`siding_window_close_8m.png` → a vertical seam runs down the center of every siding pier** (measured step 199 → 105 → 198 across the column). Directional materials no longer offset UVs, so this is a triplanar blend boundary at the pier's corner or a `module_variation` column edge. Widen the triplanar blend exponent from 4 to about 8, and key `module_variation` off world position rather than UV cell.
4. **`wet_sweep_100.png` → the wet response is readable but weak.** Take the base wet darkening to about ×0.32 for asphalt at full wetness, and lift the puddle mask threshold so 25–40% of a flat road is covered with an actual outline (the wet/dry ratio should show a bimodal histogram, not a flat 0.89). Add a Fresnel-boosted specular on the puddle mask so the grazing shot picks up the sky.
5. **`brick_red_flat_4tiles.png` → repetition is untested and my measurement is 0.77.** Recapture head-on at a distance that spans at least 4×3 tiles of wall (the 20 m wall, not the pier). Target a half/half correlation below 0.5. If `module_variation` isn't enough, add a low-frequency stain and lightness layer at 3–8 m scale.
6. **`lot_ground_mid.png`, `siding_window_close_8m.png` → the lawn is a flat carpet with a glossy sheen** at mid distance and grazing angles. Raise grass roughness to 0.85–0.95 and drop specular, then add macro variation at about 0.12 strength with a 4–8 m scale (mow stripes, wear paths, a little clover discoloration).
7. **`siding_window_close_2m.png` / `_8m.png` → windows read inconsistently** (blurred brown smear at 2 m, black void at 8 m). Add a dark interior color floor of about sRGB 25–35, a constant Fresnel sky term that survives distance, and a 60–80 mm frame so the pane isn't a hole cut in the wall.
8. **`brick_red_flat_4tiles.png`, `brick_buff_flat_4tiles.png` → mortar is uniformly bright and clean.** Vary the mortar by about ±8% per joint and darken it to roughly 0.75 of its current value near the ground via the existing grime path, so the wall reads as aged rather than newly pointed.
9. **`snow_vs_concrete_card.png` → rectangular patch edges are visible in the snowfield** where one swatch plane meets another (measured step at x≈1130). Snow coverage should be driven by world position alone, so any two materials at the same height blend identically. Check that `snow_noise_scale` and `snow_slope_bias` are the same across all ground materials.
10. **`brick_buff_flat_4tiles.png` → buff brick is slightly flat** (val 0.712 vs 0.77 target, sat 0.345 vs 0.40). Raise `albedo_multiplier` by about 8% and the tint's red by about 3%.

## Required shots for iter4

- `snow_cards_flat.png`: flat 0.2/0.5/0.8 cards coplanar with the snow, plus one vertical 0.8 card, overcast winter.
- `shingles_slope_1m.png` and `shingles_ridge_2m.png`: a tape-measure-equivalent scale marker in frame (a 1 m stick), courses and tabs clearly visible.
- `brick_red_wall_4x3_tiles.png`: the 20 m wall head-on, filling the frame, no pier.
- `siding_pier_corner.png`: the pier corner at 1.5 m to show whether the center seam is gone.
- `wet_puddle_topdown.png`: the road from 3 m up at wetness 1, so puddle outlines are readable, plus the same at wetness 0 from the same camera.
- `window_2m_8m_pair.png`: the same pane at both distances in one capture session, with the sky visible in the reflection.
- `lawn_mid_25m.png`: lawn at 25 m, grazing, to check the gloss and macro variation.
- Keep `wet_sweep_*` exactly as is — that harness change (`wetness_override`) is the right tool and should stay.

## Not materials' fault (lighting rig / test harness)

- The 0.18 and 0.8 reference cards are mounted vertically, so every albedo comparison against them is off by the horizontal-to-vertical irradiance ratio. This is a harness issue but it invalidated two of this iteration's proofs.
- `lot_ground_mid` shows a blown-out white card and a sky/ground horizon that cuts the frame in half.
- Label3D text still overlaps swatches in the wide shots.
- Exposure differs noticeably between the clear and overcast presets, so only compare materials within one lighting state.
