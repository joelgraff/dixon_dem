// horizon.gdshader -- cheap distant-terrain shader for the 10km horizon ring
// beyond the play area. No splat texture (outside the baked landuse
// coverage) -- just a height/slope blend of wild grass / forest / rock,
// plus snow. Kept simple since this geometry sits mostly behind volumetric/
// depth fog and aerial perspective (see atmosphere.gd) at typical view
// distances; the goal is "no visible edge of the world", not close-up detail.

shader_type spatial;
render_mode world_vertex_coords, diffuse_burley, specular_schlick_ggx;

#include "res://materials/shaders/includes/noise.gdshaderinc"
#include "res://materials/shaders/includes/snow.gdshaderinc"

global uniform float snow_cover;
global uniform float season_foliage;

uniform sampler2D wild_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D wild_normal : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D wood_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D wood_normal : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D rock_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D rock_normal : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_albedo_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_normal_tex : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_roughness_tex : filter_linear_mipmap, repeat_enable;

uniform float uv_scale : hint_range(0.001, 0.5) = 0.03;
uniform float macro_scale : hint_range(0.0005, 0.05) = 0.006;
uniform float snow_albedo_multiplier : hint_range(0.5, 3.0) = 1.767;

varying vec3 v_world_pos;
varying vec3 v_world_normal;

void vertex() {
	v_world_pos = VERTEX;
	v_world_normal = NORMAL;
}

void fragment() {
	vec3 wn = normalize(v_world_normal);
	vec2 uv = v_world_pos.xz * uv_scale;
	float slope = 1.0 - clamp(wn.y, 0.0, 1.0);
	// Low-frequency noise picks wooded vs. open patches across the horizon
	// (no real landuse data out here) so it doesn't read as a flat plane.
	float wood_n = fbm(v_world_pos.xz * macro_scale * 2.0);
	float w_wood = smoothstep(0.5, 0.7, wood_n) * (1.0 - smoothstep(0.35, 0.7, slope));
	float w_rock = smoothstep(0.45, 0.75, slope);
	float w_grass = clamp(1.0 - w_wood - w_rock, 0.0, 1.0);

	vec3 grass_alb = texture(wild_albedo, uv).rgb;
	vec3 wood_alb = texture(wood_albedo, uv * 0.8).rgb;
	vec3 rock_alb = texture(rock_albedo, uv * 0.6).rgb;
	vec3 grass_n = texture(wild_normal, uv).rgb * 2.0 - 1.0;
	vec3 wood_norm = texture(wood_normal, uv * 0.8).rgb * 2.0 - 1.0;
	vec3 rock_n = texture(rock_normal, uv * 0.6).rgb * 2.0 - 1.0;

	vec3 albedo = grass_alb * w_grass + wood_alb * w_wood + rock_alb * w_rock;
	vec3 normal_ts = normalize(grass_n * w_grass + wood_norm * w_wood + rock_n * w_rock);

	vec3 autumn_tint = vec3(1.05, 0.86, 0.52);
	albedo = mix(albedo, albedo * mix(vec3(1.0), autumn_tint, smoothstep(0.0, 0.8, season_foliage)), w_grass);

	float n = fbm(v_world_pos.xz * macro_scale);
	albedo *= mix(0.9, 1.08, n);

	float rough = mix(0.85, 0.95, w_rock);

	float smask = snow_mask(wn, v_world_pos, snow_cover, 0.1, 0.2);
	if (smask > 0.0) {
		vec2 suv = v_world_pos.xz * uv_scale * 0.5;
		vec3 s_alb = texture(snow_albedo_tex, suv).rgb;
		float s_rough = texture(snow_roughness_tex, suv).r;
		vec3 s_norm = texture(snow_normal_tex, suv).rgb * 2.0 - 1.0;
		apply_snow(albedo, rough, normal_ts, s_alb, s_rough, s_norm, smask, snow_albedo_multiplier);
	}

	ALBEDO = albedo;
	ROUGHNESS = clamp(rough, 0.05, 1.0);
	METALLIC = 0.0;
	NORMAL_MAP = normal_ts * 0.5 + 0.5;
	NORMAL_MAP_DEPTH = 0.6;
}
