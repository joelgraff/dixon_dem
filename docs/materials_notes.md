# Materials workstream notes

Owns `game/materials/` and texture downloads in `data/raw/textures/`. Everything here is
CC0 (Poly Haven + ambientCG), 1K except four "hero" surfaces at 2K (asphalt_road,
brick_red, grass_lawn, snow_fresh). Total `game/materials/` size: **~96 MB** (budget 400 MB).

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
| `brick_red` | ambientCG `Bricks097` (2K) | 1.0 (est.) | triplanar, no rotation | hero; weathered red-brown common bond, matches downtown Dixon commercial blocks |
| `brick_buff` | ambientCG `Bricks053` | 1.3 (real) | triplanar, no rotation | clean tan/yellow brick |
| `limestone` | ambientCG `Tiles143` | 2.0 (real) | triplanar, no rotation | tan ashlar block, for trim/lintels |
| `stone_foundation` | Poly Haven `rustic_stone_wall_02` | 2.0 (est.) | triplanar | coursed rubble stone |
| `siding_white` | ambientCG `WoodSiding008`, desaturated+renormalized | 1.2 (est.) | triplanar, no rotation | lapped clapboard, tinted near-white |
| `siding_sage` | same texture as `siding_white` | 1.2 | triplanar, no rotation | same board texture, sage-green tint — see "Tinted variants" |
| `shingles_dark` | ambientCG `Gravel043` (shared), fine scale | 0.4 (est.) | world planar | granular dark-grey stand-in for 3-tab asphalt shingle (no true shingle-course CC0 texture found — see Known weaknesses) |
| `roof_metal` | ambientCG `CorrugatedSteel009` | 1.0 (est.) | world planar | weathered corrugated/standing-seam steel; slight metallic |
| `roof_membrane` | ambientCG `Gravel043` (shared), coarse scale, tan tint | 1.6 (real) | world planar | flat gravel-ballast/membrane roof; `allow_puddles` |
| `grass_lawn` | Poly Haven `leafy_grass` (2K) | 2.0 (est.) | world planar | hero; mowed lawn, natural (not neon) green |
| `dry_grass` | Poly Haven `withered_grass` | 2.0 (est.) | world planar | dead/dry lawn patches |
| `forest_floor` | Poly Haven `forest_leaves_02` | 2.0 (est.) | world planar | leaf litter, mossy patches |
| `gravel_ballast` | Poly Haven `bicolour_gravel` | 1.5 (est.) | world planar | driveway/rail ballast gravel |
| `mud` | Poly Haven `brown_mud_02` | 2.0 (est.) | world planar | wet dark dirt; `allow_puddles` |
| `snow_fresh` | Poly Haven `snow_01` (2K) | 3.0 (est.) | world planar | hero; also the default SnowSet blended into every other material |
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

- **No true asphalt-shingle CC0 texture found** on Poly Haven or ambientCG (their
  "roofing tiles" are all clay/slate, wrong for a Midwest house). `shingles_dark` is a
  fine-scale tint of the same granular gravel texture used for `roof_membrane` — passable
  at mid/long range, weak in close-up (no visible shingle tabs/courses). Worth another
  source pass (CGBookcase, Textures.com) if a critic flags it.
  bicolour_gravel and mud also come from a small pool of "granular ground" sources so
  they share a family resemblance up close.
- **Triplanar normal blending is simplified** (weighted tangent-space sum + renormalize,
  not a full per-axis Whiteout blend) — correct enough for the near-planar walls/props
  this is meant for, but will look slightly off on a steeply curved or oblique surface.
- **`ground_level` defaults to 0** on every `.tres` — grime only lands correctly on
  instances actually sitting at world Y≈0. Any workstream placing objects at other
  elevations (hillside terrain, upper stories) should override this per-instance
  (`material.set_shader_parameter("ground_level", y)`), or grime will sit at the wrong
  height or not show at all.
- **Meters-per-tile values are mostly estimates**, not measured — only brick/limestone/
  sidewalk-concrete/the shared gravel texture have real `dimensionX/Y` metadata from
  ambientCG. Sanity-check scale once real building/road geometry exists.
- **Wetness/puddle tuning is a compromise**: an earlier pass made puddles cover ~100% of
  a wet flat surface, which blew out to a flat glare under the overcast sky dome; current
  values cap puddle coverage and roughness floor to stay readable. It may still read as
  slightly under-wet up close — a fast tuning knob if the critic wants more visible rain
  response (`wetness.gdshaderinc`, `puddle_mask()`/`apply_puddle()`).
- **`window_glass` is intentionally simple** (no screen-space refraction, per the brief's
  "procedural ok") — reads as a hazy pale reflective pane rather than showing anything
  behind it. Fine for exterior read-only windows; buildings/landmarks wanting an
  interior-visible window should write their own variant.
- Exposure/brightness of light-colored materials (concrete, gravel, snow) depends heavily
  on the atmosphere workstream's WorldEnvironment/tonemap, which was still being iterated
  on concurrently — re-check materials once atmosphere settles.
