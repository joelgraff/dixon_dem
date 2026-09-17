# Art Direction & Critic Rubric

## Target
First-person urban exploration in real-world **Dixon, Illinois** (small Midwestern river city, pop ~15k). Visual benchmark: **The Long Dark** (painterly-stylized but grounded lighting, strong atmosphere, readable silhouettes, restrained palette) crossed with realistic contemporary Midwest urban imagery.
- **Saturation: normal / natural.** Not desaturated-grim, and absolutely NOT the oversaturated candy palette of low-poly games. Reference real photos of Dixon: red-brown and buff brick 1880s–1920s commercial blocks, limestone trim, grey-green Rock River, weathered asphalt with tar-seal cracks, concrete sidewalks, mature oaks/maples, white/pastel clapboard houses.
- **Models may be simple** (low-to-mid poly is fine); quality comes from lighting, materials, proportions, scale, and composition.
- **Physically plausible shading:** PBR materials with correct albedo ranges (asphalt ~0.05–0.12, concrete ~0.3–0.45, fresh snow ~0.8–0.9, grass ~0.1–0.25), roughness variation, normal maps; AgX/filmic tonemapping; SDFGI or baked/probe GI; contact shadows/SSAO; volumetric fog for weather; correct sun angle for latitude 41.84°N.
- **Seasons/weather** are first-class: summer clear, autumn overcast, winter snow/blizzard, spring rain/fog, full day/night.

## Critic rubric (score each 1–10; the critic must be harsh — 10 = shipped AAA/AA indie art quality, 7 = competent indie, 5 = prototype, ≤3 = broken)
1. **Lighting & atmosphere** — GI/bounce, shadow quality, sky/fog cohesion, time-of-day believability, exposure.
2. **Materials & surfaces** — PBR plausibility, texture scale/tiling hidden, wear/variation, weather response (snow, wet).
3. **Color & palette** — natural saturation, harmony, matches real Dixon/Midwest; no oversaturation, no mud.
4. **Form, scale & proportion** — real-world dimensions (door 2.1 m, storey ~3.5–4.5 m commercial, lane 3.3–3.6 m, curb 15 cm), silhouettes, level of detail consistency.
5. **Composition & believability** — does the frame read as a real place / as Dixon? Clutter, props, edges, seams, floating/intersecting geometry, obvious repetition.
6. **Technical artifacts** — z-fighting, light leaks, shadow acne, aliasing/shimmer, LOD pops, stretched UVs, noise.
**Pass bar: every category ≥ 7 and average ≥ 8.** Critic output: scores, then a prioritized list of concrete, actionable fixes (what, where, how), each tied to a screenshot.
