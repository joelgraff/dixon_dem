// surface.gdshader — Dixon shared PBR surface shader.
// Used by most world materials (terrain/roads/buildings/landmarks/props) via ready-made
// ShaderMaterial .tres files in game/materials/lib/. See docs/materials_notes.md.
//
// Features: tintable albedo, world-space or mesh-UV mapping with optional triplanar,
// cheap per-tile anti-tiling (random rotate+offset) + macro color variation, ground-
// proximity grime, optional vertex-painted edge wear, and weather response driven by
// the global uniforms snow_cover / wetness (declared in project.godot, set by
// autoload/world_state.gd): snow accumulates on upward faces with a noisy edge and
// blends to a separate snow texture set; wetness darkens porous albedo, lowers
// roughness, and (opt-in) forms near-mirror puddles on flat surfaces.
//
// terrain/roads/vegetation should reuse materials/shaders/includes/*.gdshaderinc
// directly rather than duplicating this logic.

shader_type spatial;
render_mode world_vertex_coords, diffuse_burley, specular_schlick_ggx;

#include "res://materials/shaders/includes/noise.gdshaderinc"
#include "res://materials/shaders/includes/anti_tiling.gdshaderinc"
#include "res://materials/shaders/includes/snow.gdshaderinc"
#include "res://materials/shaders/includes/wetness.gdshaderinc"

// ---- World conditions (declared globally in project.godot, driven by WorldState) ----
global uniform float snow_cover;
global uniform float wetness;

group_uniforms TextureSet;
uniform sampler2D albedo_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D roughness_tex : filter_linear_mipmap, repeat_enable;
uniform sampler2D ao_tex : filter_linear_mipmap, repeat_enable;

group_uniforms SnowSet;
uniform sampler2D snow_albedo_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_normal_tex : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_roughness_tex : filter_linear_mipmap, repeat_enable;

group_uniforms TintAndMacro;
uniform vec4 albedo_tint : source_color = vec4(1.0, 1.0, 1.0, 1.0);
uniform float albedo_multiplier : hint_range(0.0, 3.0) = 1.0;
uniform float roughness_multiplier : hint_range(0.0, 3.0) = 1.0;
uniform float roughness_bias : hint_range(-1.0, 1.0) = 0.0;
uniform float metallic : hint_range(0.0, 1.0) = 0.0;
uniform float macro_variation_strength : hint_range(0.0, 0.5) = 0.12;
uniform float macro_variation_scale : hint_range(0.005, 1.0) = 0.08;

group_uniforms Mapping;
uniform vec2 uv_scale = vec2(1.0, 1.0); // tiles per meter (= 1 / meters-per-tile)
uniform bool use_world_uv = true; // false = use mesh UV0 (for hand-unwrapped props/buildings)
uniform bool triplanar = false;
uniform bool anti_tiling_enabled = true;
uniform bool anti_tiling_rotation = true; // disable for strongly directional grain (brick, siding, shingles, corrugated metal)

group_uniforms GrimeAndWear;
uniform float ground_level = 0.0; // world-space Y of local ground for this instance
uniform float grime_height : hint_range(0.0, 5.0) = 1.2; // meters above ground_level grime fades out
uniform float grime_strength : hint_range(0.0, 1.0) = 0.3;
uniform float edge_wear_amount : hint_range(0.0, 1.0) = 0.0; // needs vertex-painted COLOR.r mask

group_uniforms SnowResponse;
uniform float snow_slope_bias : hint_range(-1.0, 1.0) = 0.0; // + accumulates easier, - resists (walls)
uniform float snow_noise_scale : hint_range(0.02, 1.0) = 0.15;

group_uniforms WetResponse;
uniform float porosity : hint_range(0.0, 1.0) = 0.4;
uniform bool allow_puddles = false;
uniform float puddle_scale : hint_range(0.01, 1.0) = 0.06;

varying vec3 v_world_pos;
varying vec3 v_world_normal;

void vertex() {
	// world_vertex_coords render mode puts VERTEX/NORMAL in world space already.
	v_world_pos = VERTEX;
	v_world_normal = NORMAL;
}

struct SurfaceSample {
	vec3 albedo;
	vec3 normal_ts;
	float rough;
	float ao;
};

SurfaceSample sample_material(vec2 uv) {
	SurfaceSample s;
	vec2 t_uv = uv;
	float rot_id = 0.0;
	if (anti_tiling_enabled) {
		t_uv = anti_tile_uv(uv, anti_tiling_rotation, rot_id);
	}
	vec3 n = texture(normal_tex, t_uv).rgb * 2.0 - 1.0;
	if (anti_tiling_enabled) {
		n = rotate_tiled_normal(n, rot_id);
	}
	s.albedo = texture(albedo_tex, t_uv).rgb;
	s.normal_ts = n;
	s.rough = texture(roughness_tex, t_uv).r;
	s.ao = texture(ao_tex, t_uv).r;
	return s;
}

void fragment() {
	vec3 wn = normalize(v_world_normal);
	SurfaceSample surf;

	if (triplanar) {
		vec3 bw = pow(abs(wn), vec3(4.0));
		bw /= max(bw.x + bw.y + bw.z, 0.0001);
		SurfaceSample sx = sample_material(v_world_pos.zy * uv_scale);
		SurfaceSample sy = sample_material(v_world_pos.xz * uv_scale);
		SurfaceSample sz = sample_material(v_world_pos.xy * uv_scale);
		surf.albedo = sx.albedo * bw.x + sy.albedo * bw.y + sz.albedo * bw.z;
		surf.rough = sx.rough * bw.x + sy.rough * bw.y + sz.rough * bw.z;
		surf.ao = sx.ao * bw.x + sy.ao * bw.y + sz.ao * bw.z;
		// Simplified triplanar normal blend: weighted tangent-space sum + renormalize.
		// Not axis-reoriented like a full Whiteout blend, but adequate for the
		// near-planar ground patches this mode is meant for; walls/props should use
		// use_world_uv=false with a real UV unwrap instead.
		surf.normal_ts = normalize(sx.normal_ts * bw.x + sy.normal_ts * bw.y + sz.normal_ts * bw.z);
	} else {
		vec2 uv = use_world_uv ? (v_world_pos.xz * uv_scale) : (UV * uv_scale);
		surf = sample_material(uv);
	}

	vec3 albedo = surf.albedo * albedo_tint.rgb * albedo_multiplier;
	float rough = clamp(surf.rough * roughness_multiplier + roughness_bias, 0.02, 1.0);
	vec3 normal_ts = surf.normal_ts;
	float ao = surf.ao;

	// Macro color variation to break up large flat expanses beyond per-tile rotation.
	if (macro_variation_strength > 0.0) {
		albedo = macro_variation(albedo, v_world_pos.xz, macro_variation_scale, macro_variation_strength);
	}

	// Grime/dirt accumulation near the ground.
	if (grime_strength > 0.0) {
		float height_above = v_world_pos.y - ground_level;
		float grime_t = 1.0 - smoothstep(0.0, max(grime_height, 0.001), height_above);
		float grime_n = fbm(v_world_pos.xz * 0.5 + v_world_pos.y * 0.3);
		float grime = clamp(grime_t * mix(0.55, 1.0, grime_n) * grime_strength, 0.0, 1.0);
		albedo = mix(albedo, albedo * vec3(0.5, 0.46, 0.4), grime);
		rough = clamp(rough + 0.2 * grime, 0.02, 1.0);
		ao = mix(ao, ao * 0.7, grime);
	}

	// Optional vertex-painted edge wear (COLOR.r authored by the mesh, 0 = untouched).
	if (edge_wear_amount > 0.0) {
		float wear = COLOR.r * edge_wear_amount;
		albedo = mix(albedo, clamp(albedo * 1.6 + 0.05, 0.0, 1.0), wear);
		rough = mix(rough, max(rough - 0.25, 0.05), wear);
	}

	// --- Weather: snow ---
	float smask = snow_mask(wn, v_world_pos, snow_cover, snow_slope_bias, snow_noise_scale);
	if (smask > 0.0) {
		vec2 suv = use_world_uv ? (v_world_pos.xz * uv_scale * 0.6) : (UV * uv_scale * 0.6);
		vec3 s_alb = texture(snow_albedo_tex, suv).rgb;
		float s_rough = texture(snow_roughness_tex, suv).r;
		vec3 s_norm = texture(snow_normal_tex, suv).rgb * 2.0 - 1.0;
		apply_snow(albedo, rough, normal_ts, s_alb, s_rough, s_norm, smask);
		ao = mix(ao, 1.0, smask * 0.5);
	}

	// --- Weather: wetness (suppressed under snow) ---
	float wet_eff = wetness * (1.0 - smask * 0.9);
	if (wet_eff > 0.0) {
		apply_wetness_darkening(albedo, rough, wet_eff, porosity);
		if (allow_puddles) {
			float pmask = puddle_mask(wn, v_world_pos, wet_eff, puddle_scale);
			apply_puddle(albedo, rough, normal_ts, pmask);
		}
	}

	ALBEDO = albedo;
	ROUGHNESS = rough;
	METALLIC = metallic;
	AO = ao;
	AO_LIGHT_AFFECT = 0.6;
	NORMAL_MAP = normal_ts * 0.5 + 0.5;
	NORMAL_MAP_DEPTH = 1.0;
}
