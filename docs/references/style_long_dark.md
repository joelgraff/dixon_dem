# The Long Dark — Visual Language & Godot 4.6 Translation

Purpose: give builders a concise checklist of what makes *The Long Dark* (TLD) read as painterly-but-grounded, and concrete Godot 4.6 settings to approximate it **without** pushing Dixon toward TLD's desaturated Canadian-wilderness palette — Dixon needs **normal, natural Midwest urban saturation** per `ART_DIRECTION.md`.

## What TLD actually does (visual analysis)

1. **Painterly, low-frequency textures.** TLD's surfaces use soft, hand-painted-looking albedo maps with visible brush-like variation rather than photoreal high-frequency detail or PBR micro-noise. Large flat color regions with gentle gradients, not busy tiling patterns.
2. **Posterized/quantized shading.** Gradients (sky, snow, distant terrain) often look subtly stepped/banded rather than perfectly smooth — a semi-toon quality without hard cel outlines. It's most visible in skies and large snow planes.
3. **Restrained, cohesive palette per scene.** Each weather/time-of-day state commits to 3–5 dominant hues; nothing fights for attention. Warm firelight interiors vs. cool blue exteriors is the core contrast engine.
4. **Strong, legible silhouettes.** Buildings, trees, and props are simplified in mid-to-long range so shapes read instantly at a glance — detail is concentrated near the camera, not spread evenly.
5. **Atmospheric depth via fog/haze layering**, not just distance fog — near/mid/far bands get progressively flatter and cooler, pushing depth perception even under overcast light.
6. **Directional, "big-shape" lighting.** Few, large soft light sources (sun through overcast, sky dome) rather than many small point lights; shadows are soft-edged and low-contrast in overcast conditions, hard and long in clear low-sun conditions.
7. **Sky does a lot of work.** Large gradient sky domes with painted-looking cloud masses carry most of the mood; weather transitions are sky/fog-driven more than particle-driven.
8. **No HUD/UI clutter in the environment art itself** — TLD's world-space readability (its "UI-less" composition) comes from color-coding materials and lighting, not icons: a landmark should be identifiable purely from its silhouette + material read, exactly as this reference-doc set is trying to capture per landmark.
9. **Weather as a character.** Blizzards reduce visibility to near-white, wind-blown snow streaks across the screen, aurora/night skies are a distinct cool-teal/green event layer.

## Translating to Godot 4.6 — concrete settings

### Tonemapping & color
- Use **AgX** (`ProjectSettings > rendering/color_management/tonemapper` or the Environment resource's Tonemap mode = AgX). Godot 4.6 exposes `agx_white` and `agx_contrast` on the Environment — use these to dial contrast **down slightly** from default for overcast/foggy states (flatter, more TLD-like) and **up slightly** for clear low-sun states (more punch), instead of only adjusting exposure.
- Keep **natural saturation**: do not globally desaturate via the tonemap or a post grade the way TLD's Canadian-wilderness palette does. Instead, get the palette-restraint effect **per weather/time state** through the sun/ambient color and fog color (see below), while keeping material albedo colors close to their real-world values from `dixon_vernacular.md` and the landmark docs.
- Godot 4.6 changed **glow to blend before tonemapping** (Screen mode default) — use a modest glow (threshold ~1.0–1.2, intensity low) for window/streetlight bloom at dusk/night rather than a heavy uniform bloom.

### Lighting & GI
- **SDFGI** for the open-world exterior (dynamic time-of-day, large scale) — enable with a moderate cascade count (3–4) sized to cover the playable downtown+riverfront area at ~1–2 m/voxel in the near cascade; SDFGI's inherent softness/low-frequency bounce light naturally supports the "big soft light" TLD look.
- Use **one dominant DirectionalLight3D** (the sun) with correct angle for **41.84°N** latitude and the current season/time — this is a free source of TLD-style long dramatic shadows in morning/evening and flat top light at midday.
- Keep secondary/fill lights minimal and large-radius (sky ambient does most fill work); avoid many small point lights fighting the big-shape read.
- Contact shadows + SSAO on for grounding (per ART_DIRECTION's own rubric item 1), but keep AO subtle — TLD grounds objects with lighting/color more than heavy occlusion darkening.

### Fog & atmosphere
- Use **FogVolume/VolumetricFog** (Godot 4.6, with the new blending behavior — verify `rendering/environment/volumetric_fog` blend setting matches intended look; a project setting exists to opt out of the new blending if it causes banding issues) for near-camera atmosphere (river mist, morning fog) plus a simpler **Environment fog** (height fog) for the depth-layering effect item 5 above.
- Push fog **density and color per weather state**, not a single fixed value — see weather table below.
- Layer a **subtle desaturation + cool shift with distance** via the height/depth fog color rather than a post-process global desaturation, so foreground materials keep natural saturation while distant silhouettes flatten and cool — this is the actual mechanism behind TLD's atmospheric depth.

### Painterly texture tricks
- **Triplanar-projected noise** on large flat surfaces (roads, grass, snowfields, big brick walls) blended into the albedo/roughness at a **low frequency, large world-space scale** (think meter-to-several-meter noise cells, not centimeter tiling detail) to break up repetition without adding photoreal grime — a `TriplanarMap`-style shader with 2 octaves of noise multiplied softly into albedo variation gets most of the effect.
- **Posterize normal/roughness detail** subtly on hero surfaces (a `step()`/quantize pass on a detail-normal blend, or simply baking fewer, flatter normal-map gradients) to avoid a hyper-PBR "video game plastic" look while keeping the base PBR albedo ranges from ART_DIRECTION.md correct.
- Soft, painted-looking cloud noise on the sky shader (layered FBM/Perlin, gently posterized alpha steps) rather than a photoreal procedural sky — this is one of the highest-leverage, lowest-cost TLD-style wins since the sky dominates the frame outdoors.
- Snow/ground albedo should stay inside the ART_DIRECTION PBR ranges (snow ~0.8–0.9, grass ~0.1–0.25, asphalt ~0.05–0.12, concrete ~0.3–0.45) even while using painterly texture *variation* — painterly ≠ physically wrong.

### Weather/time state cheatsheet (fog density is illustrative, tune in-engine)

| State | Sun/ambient tint | Fog color | Fog density | Notes |
|---|---|---|---|---|
| Summer clear (haze) | warm-neutral `#FFF3DE` | pale warm-gray `#D8CFBE` | low, hazy at horizon | Illinois summer haze — humidity softens distant contrast even under a clear sky; AgX contrast slightly reduced at distance |
| Autumn overcast | neutral-cool `#E4E2DD` | cool gray `#B9BCC0` | low-medium | Let foliage color (oranges/reds) carry saturation against a desaturated sky — classic TLD-style contrast engine |
| Winter overcast/snow | cool blue-white `#DCE6EE` | blue-gray `#AEB9C4` | medium, rising in blizzard | Push ambient cool, keep snow albedo bright (0.8–0.9) so it doesn't read muddy; blizzard = near-white fog + screen-space snow streak shader |
| Spring rain/fog | cool-neutral, low contrast `#D6DCDC` | mid gray-green `#9FA9A2` | medium-high, ground-hugging | Wet-surface roughness drop (per ART_DIRECTION weather response), puddle reflections via SSR or a simple planar-reflection trick on flat wet asphalt |
| Night (all seasons) | cool moonlight `#8CA0C4` ambient + warm practical lights (windows, streetlamps ~`#FFC98A`) | dark blue-gray, thin unless foggy | low unless weather active | Strong warm/cool contrast is the single best "TLD at night" cue — lit windows and the arch's neon read as warm beacons against cool ambient |

### What NOT to copy from TLD
- Do **not** adopt TLD's overall desaturated/muted wilderness grade — Dixon is a real Midwest town, not backcountry Canada; keep red-brick, green lawns, and pastel house siding reading at natural saturation per ART_DIRECTION.
- Do not push toward a hard-edged cel/toon shader — TLD is painterly-soft, not outlined.
- Keep human-made materials (brick, painted wood, concrete, asphalt) closer to real photographic values (see `dixon_vernacular.md` palette table) than TLD's more stylized rock/snow/wood palette — the brief for Dixon is "TLD-level art direction quality," not "TLD's specific hue choices."

## Sources
- General knowledge of *The Long Dark*'s art direction (Hinterland Studio) — no single citable source; consistent with widely-observed painterly/atmospheric style across its five seasonal biomes.
- [Godot 4.6 Release notes — godotengine.org](https://godotengine.org/releases/4.6/)
- [Volumetric fog and fog volumes — Godot 4.6 docs](https://docs.godotengine.org/en/4.6/tutorials/3d/volumetric_fog.html)
- [Godot 4.6 Arrives With Major CG-Friendly Updates — Digital Production](https://digitalproduction.com/2026/01/28/godot-4-6-arrives-with-major-cg-friendly-updates/)
- Illinois seasonal/climate figures: [Dixon, IL average weather — WeatherSpark](https://weatherspark.com/y/12728/Average-Weather-in-Dixon-Illinois-United-States-Year-Round) (summer highs ~80°F/26.7°C with humidity/haze, winter lows ~14°F/-10°C, ~16 in/406 mm annual snowfall, wettest month June)
- Latitude/sun-angle requirement per `ART_DIRECTION.md` (41.84°N).

No images accompany this document — it is a technique/settings reference, not a place reference.
