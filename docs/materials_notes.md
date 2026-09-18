# Materials workstream notes

Owns `game/materials/` and texture downloads in `data/raw/textures/`. Everything here is
CC0 (Poly Haven + ambientCG), 1K except four "hero" surfaces at 2K (asphalt_road,
brick_red, grass_lawn, snow_fresh). Total `game/materials/` size: **~100 MB** (budget 400 MB).

## iter2 (critic-fix pass, avg 4.0 → addressed all 10 findings)

Captures in `captures/materials/iter2/`; iter1's harsh-critic FAIL findings and fixes:

1. **Snow rendered too dark.** `apply_snow()` in `snow.gdshaderinc` blended in the raw
   snow texture without the multiplier snow_fresh.tres itself uses — fixed by adding a
   `snow_albedo_multiplier` param to `apply_snow()` (clamped ≤0.9) and a matching
   `snow_albedo_multiplier` uniform (default 1.75) on `surface.gdshader`/`shingles.gdshader`.
   Also swapped snow_fresh's source from Poly Haven `snow_01` (had visible footprints) to
   ambientCG `Snow014` (footprint-free, crusty/natural).
2. **Anti-tiling broke brick coursing/siding boards at every tile edge.** The per-cell
   offset varied in both axes even with rotation off; a non-integer vertical offset
   desyncs mortar/lap lines across the boundary. Fixed in `anti_tiling.gdshaderinc`:
   non-rotating materials now get **zero vertical offset** (courses stay continuous) and
   a horizontal-only offset that's constant per column and quantized to a coarse module.
3. `stone_foundation` (visibly vertically-grained rubble) is now in the no-rotate set.
4. **World-XZ projection stretched on vertical faces** (curbs, roof edges/parapets).
   `surface.gdshader` now auto-switches to triplanar whenever `use_world_uv` is set and
   the surface normal isn't near-horizontal (`abs(normal.y) < 0.7`), on top of the
   explicit `triplanar` toggle. Triplanar's normal blend was also upgraded from a naive
   weighted average to a proper Whiteout blend (world-space reorientation per axis,
   re-projected into this fragment's own tangent frame via TANGENT/BINORMAL varyings).
5. **Wetness/puddles barely visible.** `wetness.gdshaderinc` values were too conservative
   (asphalt's low porosity made the darkening nearly a no-op). New curve: base wet
   darkening now ranges albedo ×0.42–0.6 at full wetness (was ×0.55–1.0); puddle coverage
   threshold `mix(0.75, 0.40, wetness)`; puddle roughness floor 0.05 (was 0.09). Verified:
   asphalt_road mean sRGB drops 159→114→100 across clear/fog/rain in identical framing
   (`road_wetness_0/0p35/1.png`).
6. **grass_lawn read as straw** (hue 72°, source Poly Haven `leafy_grass`). Replaced with
   ambientCG `Grass004` (natural suburban lawn) + tint `(0.70,1.15,0.90)`. Rendered result
   now hue≈90-94° (target #5B7B3F is 92°), matching closely.
7. **brick_red washed pink-tan** (sat 0.24, over-bright ×1.878 multiplier on a heavily
   weathered/spalled source). Replaced ambientCG `Bricks097` with cleaner running-bond
   `Bricks005`, tint `(1.20,0.62,0.46)`, multiplier dropped to 0.80.
8. **brick_buff read as grey** (source `Bricks053` is inherently pale, sat 0.17 even
   unprocessed). Added tint `(1.15,0.88,0.55)` per critic's suggestion, multiplier 0.95.
9. **siding_white was unpainted plank wood with visible nail holes**, and glass was too
   milky/transparent. Replaced source with ambientCG `WoodSiding009` (no nail-hole
   normal detail), reprocessed with lighter desaturation (75% toward grey, renormalized
   to ~0.86 sRGB mean) to read as painted clapboard. `glass.gdshader`'s tint darkened to
   `(0.16,0.19,0.21)` at alpha 0.8 (was 0.32) and roughness dropped to 0.055 for a
   crisper sky reflection instead of a pale see-through haze.
10. **shingles_dark was a flat tinted gravel texture** — no CC0 3-tab asphalt shingle
    texture exists on Poly Haven/ambientCG (their "roofing tiles" are all clay/slate).
    Replaced with a **dedicated procedural shader**, `shaders/shingles.gdshader`
    (`lib/shingles_dark.tres`): real course exposure (0.14 m) and tab width (0.33 m),
    half-tab stagger every other course, granule noise, per-tab tone variation, and a
    shadow line under each course's cutout edge — see the shader header for the mesh-UV
    convention it expects (V down-slope, `face_size_m` converts UV(0..1) to meters).

Also fixed: `curb_concrete`/`stone_foundation` multipliers checked for clipping (0% of
pixels exceed linear 1.0 at either multiplier — not a texture-level clipping issue).
Test scene: the two gable roof pieces crossed into an "X" instead of meeting at a ridge
(wrong offset math for a rotated-and-translated box) — `_gable()` in `test_materials.gd`
now derives the offset from the actual slope trig so panels meet exactly at
`ridge_point`. Added a lot-sized ground plane (`dry_grass`) under the whole scene so
swatches read as sitting in a place rather than floating panels. Added a 20 m unbroken
`brick_red` wall and four unlit reference-hex color chips (`_chip()`/
`_build_reference_chart()`) for critic-style numeric verification.

## What exists

```
game/materials/
  shaders/
    surface.gdshader        core PBR shader used by almost every .tres below
    glass.gdshader           procedural (textureless) window glass
    includes/
      noise.gdshaderinc      hash/value-noise/fbm — shared by everything below
      anti_tiling.gdshaderinc  per-tile random offset(+rotation) + macro variation
      snow.gdshaderinc        snow_mask() + apply_snow()
      wetness.gdshaderinc     apply_wetness_darkening() + puddle_mask() + apply_puddle()
  textures/<name>/albedo.jpg, normal.png, roughness.jpg, ao.jpg   (21 texture sets)
  lib/*.tres                24 ready ShaderMaterial resources (catalog below)
  test_materials.tscn / .gd  swatch test scene (wall+ledge chunks, road+curb+sidewalk,
                              pitched/flat roof pieces, ground patches, a trunk)
```

Terrain/roads/buildings/landmarks/props should **use the `.tres` files in `lib/` directly**
(`load("res://materials/lib/asphalt_road.tres")` or drag onto a mesh's surface override)
rather than rebuild shaders. If you need a variant (different tint, different tile scale,
snow/wet behavior), duplicate the `.tres` and edit `shader_parameter/*` — see "Tinted
variants" below. Don't edit `surface.gdshader` itself without checking with this
workstream; roads/terrain/vegetation should instead pull in the `.gdshaderinc` files
directly if they need snow/wet/anti-tiling logic in their own shaders.

## Catalog

All tile sizes are **meters per texture repeat** at `uv_scale = (1,1)`; the `.tres`
`uv_scale` is `1 / tile_size`. Real-world tile sizes came from ambientCG's
`dimensionX/Y` metadata where available (brick, limestone, sidewalk concrete, the
shared gravel source); everything else is a visual estimate — nudge `uv_scale` per
instance if it reads wrong at final building/terrain scale.

| `.tres` | source (site, asset) | tile size (m) | mapping | notes |
|---|---|---|---|---|
| `asphalt_road` | Poly Haven `asphalt_02` (2K) | 4.0 | world planar | hero; worn road, hairline cracks; `allow_puddles` |
| `asphalt_patched` | Poly Haven `asphalt_07` | 3.0 | world planar | rougher chip-seal patch tone; `allow_puddles` |
| `sidewalk_concrete` | ambientCG `Concrete034` | 1.1 × 0.55 (real) | world planar | broom-finish; `allow_puddles` |
| `curb_concrete` | ambientCG `Concrete030` | 1.0 (est.) | triplanar | darker/dirtier than sidewalk; grime near ground |
| `brick_red` | ambientCG `Bricks005` (2K) | 1.0 (est.) | triplanar, no rotation | hero; clean running-bond red-brown brick, tinted `(1.20,0.62,0.46)`×0.80 to hit hue≈15-19°/sat≈0.5-0.65 (target #9A5B45) |
| `brick_buff` | ambientCG `Bricks053` | 1.3 (real) | triplanar, no rotation | tan brick; source is inherently pale (sat 0.17 raw) so tint `(1.15,0.88,0.55)` carries the warmth |
| `limestone` | ambientCG `Tiles143` | 2.0 (real) | triplanar, no rotation | tan ashlar block, for trim/lintels |
| `stone_foundation` | Poly Haven `rustic_stone_wall_02` | 2.0 (est.) | triplanar, no rotation | coursed rubble stone — source has a strong vertical grain, rotation stays off |
| `siding_white` | ambientCG `WoodSiding009`, desaturated 75%→renormalized ~0.86 sRGB | 1.2 (est.) | triplanar, no rotation | painted lap clapboard, tinted near-white; switched from WoodSiding008 (had visible nail-hole normal detail) |
| `siding_sage` | same texture as `siding_white` | 1.2 | triplanar, no rotation | same board texture, sage-green tint — see "Tinted variants" |
| `shingles_dark` | **procedural**, `shaders/shingles.gdshader` (no photo texture) | 0.33 m tab / 0.14 m course (real) | mesh UV (V=down-slope) | 3-tab asphalt shingle: coursing, granule noise, per-tab tone variation — see shader header for UV convention |
| `roof_metal` | ambientCG `CorrugatedSteel009` | 1.0 (est.) | world planar (auto-triplanar off-flat) | weathered corrugated/standing-seam steel; slight metallic |
| `roof_membrane` | ambientCG `Gravel043` (shared), coarse scale, tan tint | 1.6 (real) | world planar (auto-triplanar off-flat) | flat gravel-ballast/membrane roof; `allow_puddles` |
| `grass_lawn` | ambientCG `Grass004` (2K) | 1.4 (real) | world planar | hero; natural suburban lawn, tinted `(0.70,1.15,0.90)` for hue≈90-94° (target #5B7B3F is 92°) |
| `dry_grass` | Poly Haven `withered_grass` | 2.0 (est.) | world planar | dead/dry lawn patches |
| `forest_floor` | Poly Haven `forest_leaves_02` | 2.0 (est.) | world planar | leaf litter, mossy patches |
| `gravel_ballast` | Poly Haven `bicolour_gravel` | 1.5 (est.) | world planar | driveway/rail ballast gravel |
| `mud` | Poly Haven `brown_mud_02` | 2.0 (est.) | world planar | wet dark dirt; `allow_puddles` |
| `snow_fresh` | ambientCG `Snow014` (2K) | 2.5 (est.) | world planar | hero; footprint-free crusty snow (replaced Poly Haven `snow_01`, which had visible footprints); also the default SnowSet blended into every other material |
| `snow_dirty` | Poly Haven `snow_03` | 3.0 (est.) | world planar | trampled/greyed snow |
| `ice` | ambientCG `Ice003` | 1.5 (est.) | world planar | low roughness, low albedo (reflectance carries the look) |
| `steel_rusted` | Poly Haven `rusty_metal_02` | 1.0 (est.) | triplanar | painted steel with rust bloom; props (dumpsters, fire escapes, utility boxes) |
| `bark` | Poly Haven `bark_brown_02` | 1.0 (est.) | mesh UV0 | trunk cylinders — vegetation should UV-unwrap (V=height, U=angle), not rely on projection |
| `window_glass` | procedural (`glass.gdshader`, no textures) | n/a | mesh UV0, `pane_scale` | translucent, frosts in winter, streaks when wet |

Albedo brightness was measured with `python3 + Pillow` on the raw downloaded textures
(mean pixel converted sRGB→linear) and corrected with `shader_parameter/albedo_multiplier`
(and `albedo_tint` for hue) to land in the ranges ART_DIRECTION.md specifies: asphalt
~0.05–0.12, concrete ~0.30–0.45, grass ~0.10–0.25, snow ~0.80–0.90 (all *linear*
reflectance — the render adds specular/ambient/tonemap on top, so on-screen pixels read
brighter, especially concrete under an overcast sky). See
`data/raw/textures/gen_materials.py` for the full per-material multiplier table and
`data/raw/textures/tint_multipliers.json` / `albedo_stats.json` for the raw measurements.

## Using `surface.gdshader`

Every `.tres` sets these `shader_parameter/*` (grouped in the inspector):

- **TextureSet / SnowSet**: `albedo_tex`, `normal_tex` (GL/+Y, matches Godot), `roughness_tex`,
  `ao_tex`; `snow_albedo_tex`/`snow_normal_tex`/`snow_roughness_tex` (all point at
  `snow_fresh` by default — override if a material should melt into something else).
- **TintAndMacro**: `albedo_tint` (Color, multiplies albedo — this is how you recolor),
  `albedo_multiplier`/`roughness_multiplier`/`roughness_bias`/`metallic`,
  `macro_variation_strength`/`scale` (large-scale noise breaking up big flat expanses).
- **Mapping**: `uv_scale` (tiles per meter = 1/tile_size), `use_world_uv` (true = auto
  planar from world XZ, good for ground/roofs with no UV work; false = mesh UV0, use for
  hand-unwrapped walls/props), `triplanar` (blends 3 planar projections by world
  normal — turn on for anything that isn't a flat horizontal/vertical surface with a
  clean UV unwrap, e.g. procedurally-massed building walls), `anti_tiling_enabled`,
  `anti_tiling_rotation` (**turn OFF for anything with strong directional grain** — brick
  coursing, lapped siding, shingle/corrugated ridges — a 90° per-tile rotation flips the
  grain sideways in alternating cells and reads as an obvious quilt; leave ON for
  non-directional stone/gravel/asphalt/grass/dirt/snow).
- **GrimeAndWear**: `ground_level` (world Y of this instance's local ground — **you must
  set this per placement**, it defaults to 0 which is only right for objects sitting at
  world Y=0), `grime_height`/`grime_strength` (splash-up dirt near the ground),
  `edge_wear_amount` (0 by default; painting vertex color red on a mesh and raising this
  lightens/smooths worn edges — opt-in, most primitive meshes have no vertex colors).
- **SnowResponse**: `snow_slope_bias` (positive = catches snow easily — flat ground/roofs;
  negative = resists — walls, bark), `snow_noise_scale`.
- **WetResponse**: `porosity` (0 = metal/ice/glass barely darkens, 1 = dirt/mud darkens
  hard), `allow_puddles` (only set true for materials that plausibly pool water — flat
  roads/sidewalks/flat roofs/mud, not walls/grass/gravel), `puddle_scale`.

Weather comes from the **global uniforms** `snow_cover` and `wetness` (declared in
`project.godot`, driven by `WorldState`/atmosphere) — you never set these per-material;
every `surface.gdshader` material reacts automatically.

### Reusing the includes elsewhere (terrain/roads/vegetation)

Don't reimplement snow/wet/anti-tiling — `#include` these directly in your own shader:

```glsl
#include "res://materials/shaders/includes/anti_tiling.gdshaderinc"
#include "res://materials/shaders/includes/snow.gdshaderinc"
#include "res://materials/shaders/includes/wetness.gdshaderinc"

float rot_id;
vec2 t_uv = anti_tile_uv(uv, true /*allow_rotation*/, rot_id); // false for directional grain

float smask = snow_mask(world_normal, world_pos, snow_cover, slope_bias, noise_scale);
// mix albedo/roughness/normal toward your snow set with apply_snow(...)

apply_wetness_darkening(albedo, roughness, wetness, porosity);
float pmask = puddle_mask(world_normal, world_pos, wetness, puddle_scale); // flat surfaces only
apply_puddle(albedo, roughness, normal_ts, pmask);
```

`terrain_blend` (splatting multiple ground materials together) is the terrain
workstream's own job — these includes just give it the same snow/wet/anti-tile math so a
blended terrain material and a `lib/grass_lawn.tres` prop patch respond identically.

## Tinted variants

`siding_white.tres` and `siding_sage.tres` both point at the same
`textures/siding_clapboard/` files — the only difference is `shader_parameter/albedo_tint`
(and there's no `albedo_multiplier` fighting it, since the source texture was
pre-desaturated to a neutral mid-grey with `data/raw/textures/process_textures.py`'s
siding step specifically so it tints cleanly). To make a new painted-siding color:

1. Duplicate `siding_white.tres` (Godot: right-click → Duplicate, or copy the file).
2. Edit `resource_name` and `shader_parameter/albedo_tint` to the new paint color
   (multiply, so keep components ≤ ~1.0; a pastel needs low saturation, e.g.
   `Color(0.7, 0.62, 0.55, 1)` for a dusty tan).
3. Leave `albedo_multiplier` alone unless the new tint reads too dark/bright.

The same pattern works for any material where you want a color variant without a new
texture download — just don't do it for materials whose *texture* carries the color
identity (brick, stone, asphalt): those should get a new source texture instead, since
multiplying a strongly-colored photo just makes it a darker/lighter version of the same
hue, not a believable recolor.

## Test scene / captures

`game/materials/test_materials.tscn` builds all 24 materials as simple architectural
pieces (wall+ledge chunks, a road/curb/sidewalk assembly, two gable roof pieces + one
flat membrane roof, 8 ground patches, a bark trunk, one embedded glass pane) under
`res://atmosphere/atmosphere.tscn` if present (it is, as of this writing) else a
DirectionalLight3D + WorldEnvironment(AgX) fallback. Ground/road patches use `PlaneMesh`
rather than thin `BoxMesh` — a thin box's side faces alias badly at grazing angles
(showed up as a "barcode" artifact during iteration; keep this in mind for other
workstreams' flat ground geometry too).

Captures: `captures/materials/iter1/` — close-ups (2–5 m) and mid shots (15–30 m) across
summer/clear, autumn/overcast, autumn/rain, and winter/snow. Regenerate with:

```
game/tools/import.sh
game/tools/capture.sh res://materials/test_materials.tscn <shots.json> captures/materials/iterN
```

## Known weaknesses (for the critic)

- **`shingles_dark`'s procedural courses are a straight sawtooth pattern** (uniform
  course exposure/stagger) — real shingle courses have more organic wear variation
  (curling, algae streaking, occasional missing granules). Reads well at the 2m/mid
  ranges tested; a critic pushing extreme close-ups may still find it a bit clean/regular.
- **Triplanar normal blending** now does a proper per-axis Whiteout reorientation (fixed
  in iter2), but is still evaluated per-fragment against the flat face normal rather than
  a true derivative-based tangent basis — correct for the box/plane primitives in the
  test scene, unverified on organic/curved meshes.
- **`ground_level` defaults to 0** on every `.tres` — grime only lands correctly on
  instances actually sitting at world Y≈0. Any workstream placing objects at other
  elevations (hillside terrain, upper stories) should override this per-instance
  (`material.set_shader_parameter("ground_level", y)`), or grime will sit at the wrong
  height or not show at all.
- **Meters-per-tile values are mostly estimates**, not measured — only brick_buff/
  limestone/sidewalk-concrete/grass_lawn/the shared gravel texture have real
  `dimensionX/Y` metadata from ambientCG. Sanity-check scale once real building/road
  geometry exists.
- **`window_glass` is intentionally simple** (no screen-space refraction, per the brief's
  "procedural ok") — now reads as a darker reflective pane (iter2: alpha 0.8, roughness
  0.055) rather than showing anything behind it. Fine for exterior read-only windows;
  buildings/landmarks wanting an interior-visible window should write their own variant.
- **Reference-hex color chips (`_build_reference_chart()`) are tonemapped like everything
  else** — AgX shifts an unshaded flat color's on-screen saturation/value noticeably
  versus its raw hex, so compare materials to the chips *as rendered in the same shot*,
  not to the raw hex numbers directly (see iter2 measurements in this file's git history
  / the critic response for the actual numbers).
- Exposure/brightness of light-colored materials (concrete, gravel, snow) depends heavily
  on the atmosphere workstream's WorldEnvironment/tonemap, which was still being iterated
  on concurrently — re-check materials once atmosphere settles.
