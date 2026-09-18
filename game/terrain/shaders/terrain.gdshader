// terrain.gdshader -- Dixon play-area terrain: 7-layer splat blend
// (baked landuse mask + dynamic slope/height/curvature rock) with seasonal
// grass response, snow accumulation, and rain wetness. Reuses the shared
// materials/shaders/includes/*.gdshaderinc helpers (noise, anti-tiling,
// snow, wetness) the same way materials/shaders/surface.gdshader does, but
// implements its own multi-layer blend since surface.gdshader only carries
// one texture set. See docs/terrain_notes.md.
//
// Layers (weights come from two baked RGBA8 masks -- see
// pipeline/terrain/bake_splat.py -- plus a slope/height/curvature-driven
// exposed-rock term computed here, no baking needed for that one):
//   0 grass_lawn   -- splat_a.r  (mowed: parks/residential/cemetery)
//   1 dry_grass    -- implicit fallback (1 - sum of all other weights)
//   2 forest_floor -- splat_a.g  (wooded ground / leaf litter)
//   3 gravel_ballast-- splat_a.b (rail corridors, quarries)
//   4 mud          -- splat_a.a + splat_b.g (riverbank + bare farmland/brownfield dirt)
//   5 asphalt_patched-- splat_b.r (parking/retail/industrial placeholder paving)
//   6 stone_rough  -- dynamic: steep slopes + high curvature (exposed rock/dirt on banks & bluffs)

shader_type spatial;
render_mode world_vertex_coords, diffuse_burley, specular_schlick_ggx;

#include "res://materials/shaders/includes/noise.gdshaderinc"
#include "res://materials/shaders/includes/anti_tiling.gdshaderinc"
#include "res://materials/shaders/includes/snow.gdshaderinc"
#include "res://materials/shaders/includes/wetness.gdshaderinc"

global uniform float snow_cover;
global uniform float wetness;
global uniform float season_foliage; // 0 summer green -> 0.75 autumn -> 1 bare/winter

group_uniforms SplatMasks;
uniform sampler2D splat_a : filter_linear, repeat_disable; // R lawn, G wood, B gravel, A riverbank mud
uniform sampler2D splat_b : filter_linear, repeat_disable; // R paved placeholder, G bare dirt
uniform vec2 splat_origin_m = vec2(0.0, -2700.0); // world (x,z) at splat uv (0,0)
uniform vec2 splat_size_m = vec2(2700.0, 2700.0);

group_uniforms Layer0_GrassLawn;
uniform sampler2D lawn_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D lawn_normal : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D lawn_rough : filter_linear_mipmap, repeat_enable;

group_uniforms Layer1_DryGrass;
uniform sampler2D wild_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D wild_normal : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D wild_rough : filter_linear_mipmap, repeat_enable;

group_uniforms Layer2_ForestFloor;
uniform sampler2D wood_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D wood_normal : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D wood_rough : filter_linear_mipmap, repeat_enable;

group_uniforms Layer3_Gravel;
uniform sampler2D gravel_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D gravel_normal : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D gravel_rough : filter_linear_mipmap, repeat_enable;

group_uniforms Layer4_Mud;
uniform sampler2D mud_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D mud_normal : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D mud_rough : filter_linear_mipmap, repeat_enable;

group_uniforms Layer5_Paved;
uniform sampler2D paved_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D paved_normal : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D paved_rough : filter_linear_mipmap, repeat_enable;

group_uniforms Layer6_Rock;
uniform sampler2D rock_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D rock_normal : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D rock_rough : filter_linear_mipmap, repeat_enable;

group_uniforms SnowSet;
uniform sampler2D snow_albedo_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_normal_tex : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_roughness_tex : filter_linear_mipmap, repeat_enable;

group_uniforms Tiling;
uniform float uv_scale : hint_range(0.05, 2.0) = 0.35; // tiles per meter, shared base
// Default OFF: anti_tile_uv's per-cell hashed UV rotation/offset introduces
// a UV discontinuity at every tile boundary, which defeats the GPU's mip
// selection (huge/garbage screen-space UV derivatives at those seams) and
// reads as chaotic static once a tile is more than ~1-2 screen pixels wide
// minified (any elevated/distant/grazing terrain view -- i.e. most of them).
// It works fine for materials.gd's close-up wall/prop swatches; terrain
// instead leans on macro_variation() + the multi-layer splat blend itself
// to break up repetition. Left as a toggle in case a future close-range
// detail pass wants it locally.
uniform bool anti_tiling_enabled = false;

group_uniforms MacroAndSlope;
uniform float macro_variation_strength : hint_range(0.0, 0.5) = 0.16;
uniform float macro_variation_scale : hint_range(0.001, 0.5) = 0.015; // low freq: whole play area
uniform float rock_slope_lo : hint_range(0.0, 1.0) = 0.55; // slope factor where rock starts blending in
uniform float rock_slope_hi : hint_range(0.0, 1.0) = 0.82;
uniform float rock_height_low_m : hint_range(0.0, 60.0) = 8.0; // above this local Y, bluffs favor rock at lower slope
uniform float rock_height_high_m : hint_range(0.0, 60.0) = 30.0;
uniform float curvature_strength : hint_range(0.0, 4.0) = 1.2;

group_uniforms SnowResponse;
uniform float snow_noise_scale : hint_range(0.02, 1.0) = 0.1;
// snow_fresh's raw texture sample needs this correction to land in the
// ART_DIRECTION ~0.8-0.9 linear albedo range -- see materials_notes.md and
// snow.gdshaderinc's apply_snow() doc comment. Matches lib/snow_fresh.tres.
uniform float snow_albedo_multiplier : hint_range(0.5, 3.0) = 1.767;

group_uniforms WetResponse;
uniform float puddle_scale : hint_range(0.01, 1.0) = 0.04;

varying vec3 v_world_pos;
varying vec3 v_world_normal;

void vertex() {
	v_world_pos = VERTEX;
	v_world_normal = NORMAL;
}

struct SurfaceSample {
	vec3 albedo;
	vec3 normal_ts;
	float rough;
};

SurfaceSample sample_layer(sampler2D albedo_tex, sampler2D normal_tex, sampler2D rough_tex, vec2 uv, bool allow_rotation) {
	SurfaceSample s;
	vec2 t_uv = uv;
	float rot_id = 0.0;
	if (anti_tiling_enabled) {
		t_uv = anti_tile_uv(uv, allow_rotation, rot_id);
	}
	vec3 n = texture(normal_tex, t_uv).rgb * 2.0 - 1.0;
	if (anti_tiling_enabled) {
		n = rotate_tiled_normal(n, rot_id);
	}
	s.albedo = texture(albedo_tex, t_uv).rgb;
	s.normal_ts = n;
	s.rough = texture(rough_tex, t_uv).r;
	return s;
}

void fragment() {
	vec3 wn = normalize(v_world_normal);
	vec2 uv = v_world_pos.xz * uv_scale;

	// --- baked splat weights ---
	vec2 suv = (v_world_pos.xz - splat_origin_m) / splat_size_m;
	vec4 sa = texture(splat_a, suv);
	vec4 sb = texture(splat_b, suv);
	float w_lawn = sa.r;
	float w_wood = sa.g;
	float w_gravel = sa.b;
	float w_mud = clamp(sa.a + sb.g, 0.0, 1.0);
	float w_paved = sb.r;
	float baked_sum = w_lawn + w_wood + w_gravel + w_mud + w_paved;
	float w_wild = clamp(1.0 - baked_sum, 0.0, 1.0);
	float total = max(w_lawn + w_wild + w_wood + w_gravel + w_mud + w_paved, 0.0001);
	w_lawn /= total; w_wild /= total; w_wood /= total; w_gravel /= total; w_mud /= total; w_paved /= total;

	// --- dynamic slope/height/curvature exposed-rock term ---
	float slope = 1.0 - clamp(wn.y, 0.0, 1.0); // 0 flat .. 1 vertical
	float height_t = smoothstep(rock_height_low_m, rock_height_high_m, v_world_pos.y);
	float slope_hi = mix(rock_slope_hi, rock_slope_lo, height_t); // bluffs expose rock more readily
	// Curvature proxy: how fast the world normal changes across the pixel footprint
	// (screen-space derivative) -- high at ridgelines, creek cuts, road-carved edges.
	float curvature = (length(dFdx(wn)) + length(dFdy(wn))) * curvature_strength;
	float rock_t = 0.0; // DEBUG: temporarily disabled
	//float rock_t = clamp(smoothstep(rock_slope_lo, slope_hi, slope) + curvature * 0.35, 0.0, 0.92);
	rock_t *= (1.0 - w_paved) * (1.0 - w_gravel); // never sprout rock through pavement/ballast

	float keep = 1.0 - rock_t;
	w_lawn *= keep; w_wild *= keep; w_wood *= keep; w_gravel *= keep; w_mud *= keep; w_paved *= keep;

	SurfaceSample l_lawn = sample_layer(lawn_albedo, lawn_normal, lawn_rough, uv, true);
	SurfaceSample l_wild = sample_layer(wild_albedo, wild_normal, wild_rough, uv, true);
	SurfaceSample l_wood = sample_layer(wood_albedo, wood_normal, wood_rough, uv * 0.8, true);
	SurfaceSample l_gravel = sample_layer(gravel_albedo, gravel_normal, gravel_rough, uv * 1.4, true);
	SurfaceSample l_mud = sample_layer(mud_albedo, mud_normal, mud_rough, uv * 1.1, true);
	SurfaceSample l_paved = sample_layer(paved_albedo, paved_normal, paved_rough, uv * 0.9, false);
	SurfaceSample l_rock = sample_layer(rock_albedo, rock_normal, rock_rough, uv * 0.7, true);

	vec3 albedo = l_lawn.albedo * w_lawn + l_wild.albedo * w_wild + l_wood.albedo * w_wood
			+ l_gravel.albedo * w_gravel + l_mud.albedo * w_mud + l_paved.albedo * w_paved
			+ l_rock.albedo * rock_t;
	float rough = l_lawn.rough * w_lawn + l_wild.rough * w_wild + l_wood.rough * w_wood
			+ l_gravel.rough * w_gravel + l_mud.rough * w_mud + l_paved.rough * w_paved
			+ l_rock.rough * rock_t;
	vec3 normal_ts = normalize(l_lawn.normal_ts * w_lawn + l_wild.normal_ts * w_wild + l_wood.normal_ts * w_wood
			+ l_gravel.normal_ts * w_gravel + l_mud.normal_ts * w_mud + l_paved.normal_ts * w_paved
			+ l_rock.normal_ts * rock_t);

	// --- seasonal grass response (summer green -> autumn yellow-brown -> winter dormant tan) ---
	float grassy = clamp(w_lawn + w_wild, 0.0, 1.0);
	vec3 autumn_tint = vec3(1.05, 0.86, 0.52);
	vec3 seasonal = mix(vec3(1.0), autumn_tint, smoothstep(0.0, 0.8, season_foliage));
	albedo = mix(albedo, albedo * seasonal, grassy);
	// Spring: wet, slightly more saturated green (low foliage + high wetness = spring rain).
	float spring_t = wetness * (1.0 - season_foliage) * 0.4;
	albedo = mix(albedo, albedo * vec3(0.92, 1.05, 0.86), grassy * spring_t);

	// Macro color variation across the whole play area so the bluff vista doesn't tile.
	if (macro_variation_strength > 0.0) {
		albedo = macro_variation(albedo, v_world_pos.xz, macro_variation_scale, macro_variation_strength);
	}

	float ao = 1.0;

	// --- weather: snow (deep/soft, less on slopes, grass tufts poking through via noise mask) ---
	float snow_slope_bias = mix(0.35, -0.4, slope); // flat ground catches snow; steep banks resist
	float smask = snow_mask(wn, v_world_pos, snow_cover, snow_slope_bias, snow_noise_scale);
	if (smask > 0.0) {
		vec2 suv2 = v_world_pos.xz * uv_scale * 0.5;
		vec3 s_alb = texture(snow_albedo_tex, suv2).rgb;
		float s_rough = texture(snow_roughness_tex, suv2).r;
		vec3 s_norm = texture(snow_normal_tex, suv2).rgb * 2.0 - 1.0;
		apply_snow(albedo, rough, normal_ts, s_alb, s_rough, s_norm, smask, snow_albedo_multiplier);
		ao = mix(ao, 1.0, smask * 0.5);
	}

	// --- weather: wetness (rain darkening + puddles in flat low ground) ---
	float wet_eff = wetness * (1.0 - smask * 0.9);
	if (wet_eff > 0.0) {
		float porosity = mix(0.55, 0.15, w_paved + rock_t); // paving/rock barely darkens vs. soil
		apply_wetness_darkening(albedo, rough, wet_eff, porosity);
		float pmask = puddle_mask(wn, v_world_pos, wet_eff, puddle_scale) * (w_mud * 0.6 + w_paved + w_wild * 0.2);
		if (pmask > 0.0) {
			apply_puddle(albedo, rough, normal_ts, clamp(pmask, 0.0, 1.0));
		}
	}

	ALBEDO = vec3(1.0, 0.0, 0.0); // DEBUG
	//ALBEDO = albedo;
	ROUGHNESS = clamp(rough, 0.03, 1.0);
	METALLIC = 0.0;
	AO = ao;
	AO_LIGHT_AFFECT = 0.5;
	NORMAL_MAP = normal_ts * 0.5 + 0.5;
	NORMAL_MAP_DEPTH = 1.0;
}
