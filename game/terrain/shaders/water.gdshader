// water.gdshader -- Rock River reaches + ponds. Stylized-realistic: depth-based
// color/absorption via the scene depth buffer, fresnel sky-ish reflection +
// the engine's own sky/SDFGI reflection (kept glossy/low-roughness so Godot's
// built-in environment reflection does most of the work -- no SSR dependency
// since this workstream doesn't own the WorldEnvironment), procedural
// flow-direction ripples, foam/turbulence below the dam, shoreline foam/wet
// bank darkening, rain ripples, and winter shelf/partial ice with snow on top.
// See docs/terrain_notes.md.
//
// Per-reach uniforms (flow_dir, is_pond, dam_point/dam_dir, surface_y) are set
// per MeshInstance3D by terrain.gd on a duplicated ShaderMaterial instance --
// see _build_water().

shader_type spatial;
render_mode world_vertex_coords, blend_mix, diffuse_burley, specular_schlick_ggx, cull_disabled;

#include "res://materials/shaders/includes/noise.gdshaderinc"
#include "res://materials/shaders/includes/snow.gdshaderinc"

global uniform float snow_cover;
global uniform float wetness;

uniform sampler2D depth_tex : hint_depth_texture, filter_linear;
uniform sampler2D ice_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D ice_normal : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_albedo_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_normal_tex : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_roughness_tex : filter_linear_mipmap, repeat_enable;

group_uniforms ReachIdentity;
uniform vec2 flow_dir = vec2(1.0, 0.0); // normalized, world xz
uniform bool is_pond = false;
uniform vec2 dam_point = vec2(1.0e6, 1.0e6); // world xz; far away = no dam effect
uniform vec2 dam_dir = vec2(0.0, 1.0);       // dam crest line direction, world xz

group_uniforms Color;
uniform vec3 shallow_color : source_color = vec3(0.42, 0.5, 0.42);
uniform vec3 deep_color : source_color = vec3(0.29, 0.35, 0.28); // murky green-brown, ~#4a5a48
uniform float absorption_depth_m : hint_range(0.2, 8.0) = 2.2;

group_uniforms Ripples;
uniform float snow_albedo_multiplier : hint_range(0.5, 3.0) = 1.767;
uniform float ripple_scale : hint_range(0.01, 1.0) = 0.12;
uniform float ripple_speed : hint_range(0.0, 2.0) = 0.35;
uniform float swell_scale : hint_range(0.001, 0.2) = 0.02;
uniform float rain_ripple_scale : hint_range(0.05, 2.0) = 0.6;

varying vec3 v_world_pos;

void vertex() {
	v_world_pos = VERTEX;
}

// Cheap directional ripple normal: two scrolling value-noise taps along the
// flow direction (fine ripples) plus one slow low-frequency fbm swell.
vec3 ripple_normal(vec2 world_xz, vec2 dir, float time_s) {
	vec2 tangent = dir;
	vec2 bitangent = vec2(-dir.y, dir.x);
	vec2 flow_uv = world_xz * ripple_scale + tangent * time_s * ripple_speed;
	float eps = 0.08;
	float h = value_noise(flow_uv) * 0.7 + value_noise(flow_uv * 2.3 + 11.0) * 0.3;
	float hx = value_noise(flow_uv + vec2(eps, 0.0)) * 0.7 + value_noise(flow_uv * 2.3 + vec2(eps * 2.3, 0.0) + 11.0) * 0.3;
	float hz = value_noise(flow_uv + vec2(0.0, eps)) * 0.7 + value_noise(flow_uv * 2.3 + vec2(0.0, eps * 2.3) + 11.0) * 0.3;
	// Low-frequency swell nudges the fine-ripple normal slightly along the
	// bitangent so long, slow undulations read through the fine detail.
	float swell = fbm(world_xz * swell_scale + tangent * time_s * ripple_speed * 0.15) - 0.5;
	vec3 n = normalize(vec3(-(hx - h) / eps, 3.2, -(hz - h) / eps));
	n = normalize(n + vec3(bitangent * swell * 0.15, 0.0).xzy);
	return n;
}

void fragment() {
	vec2 world_xz = v_world_pos.xz;
	vec3 view_dir = normalize(VIEW);

	// --- reconstruct the scene (bed) depth beneath this water pixel ---
	float raw_depth = texture(depth_tex, SCREEN_UV).r;
	vec3 ndc = vec3(SCREEN_UV * 2.0 - 1.0, raw_depth);
	vec4 view_pos = INV_PROJECTION_MATRIX * vec4(ndc, 1.0);
	view_pos.xyz /= view_pos.w;
	vec4 bed_world = INV_VIEW_MATRIX * vec4(view_pos.xyz, 1.0);
	float bed_y = bed_world.y;
	float water_depth = clamp(v_world_pos.y - bed_y, 0.0, 40.0);

	// --- flow ripples (+ extra high-freq layer when raining) ---
	vec3 n_ts = ripple_normal(world_xz, normalize(flow_dir), TIME);
	if (wetness > 0.0) {
		vec2 rain_uv = world_xz * rain_ripple_scale + vec2(TIME * 0.05, TIME * 0.03);
		float rn = value_noise(rain_uv) - 0.5;
		vec3 rain_n = normalize(vec3(rn * 0.6, 3.0, (value_noise(rain_uv + 3.7) - 0.5) * 0.6));
		n_ts = normalize(mix(n_ts, rain_n, clamp(wetness * 0.5, 0.0, 0.5)));
	}
	vec3 wn = normalize(vec3(n_ts.x, n_ts.y, n_ts.z));

	// --- depth-based absorption color ---
	float absorb_t = 1.0 - exp(-water_depth / absorption_depth_m);
	vec3 albedo = mix(shallow_color, deep_color, absorb_t);

	// --- foam/turbulence line immediately downstream of the dam ---
	vec2 d = world_xz - dam_point;
	vec2 dn = normalize(dam_dir);
	float along = dot(d, dn);           // position along the dam crest
	vec2 perp = vec2(-dn.y, dn.x);
	float across = dot(d, perp);        // signed distance from the crest line
	float dam_band = (1.0 - smoothstep(0.0, 22.0, max(across, 0.0))) * step(0.0, across) * smoothstep(70.0, 0.0, abs(along) - 60.0);
	float turb_noise = fbm(world_xz * 0.15 + TIME * vec2(0.05, 0.08));
	float turbulence = clamp(dam_band * (0.55 + 0.45 * turb_noise), 0.0, 1.0);

	// --- shoreline foam / wet-bank darkening (shallow water near the bank) ---
	float shallow_t = 1.0 - smoothstep(0.0, 1.6, water_depth);
	float shore_noise = fbm(world_xz * 0.4 + 5.0);
	float shore_foam = shallow_t * smoothstep(0.35, 0.75, shore_noise) * 0.8;

	float foam = clamp(turbulence + shore_foam, 0.0, 1.0);
	vec3 foam_color = vec3(0.86, 0.9, 0.88);
	albedo = mix(albedo, foam_color, foam);

	float rough = mix(0.045, 0.35, clamp(foam + wetness * 0.1, 0.0, 1.0));
	float alpha = mix(0.88, 1.0, absorb_t) ; // slightly more transparent in the shallows
	alpha = clamp(mix(alpha, 1.0, foam), 0.0, 1.0);

	// --- winter ice: shelf ice from the banks inward, partial freeze on calm
	// water, open channel preserved where the dam keeps water turbulent. ---
	float freeze_base = smoothstep(0.28, 0.7, snow_cover) * (is_pond ? 1.15 : 0.75);
	float bank_t = 1.0 - smoothstep(0.0, 3.5, water_depth);
	float ice_noise = fbm(world_xz * 0.05 + 71.0);
	float ice_mask = clamp((freeze_base + bank_t * freeze_base * 1.4) * mix(0.7, 1.1, ice_noise), 0.0, 1.0);
	ice_mask *= (1.0 - turbulence * 0.95); // dam keeps an open channel below it

	if (ice_mask > 0.001) {
		vec2 iuv = world_xz * 0.15;
		vec3 ice_alb = texture(ice_albedo, iuv).rgb;
		vec3 ice_n = texture(ice_normal, iuv).rgb * 2.0 - 1.0;
		albedo = mix(albedo, ice_alb, ice_mask);
		wn = normalize(mix(wn, ice_n, ice_mask));
		rough = mix(rough, 0.18, ice_mask);
		alpha = mix(alpha, 1.0, ice_mask);

		// Snow sitting on top of the ice sheet, upward faces only.
		float smask = snow_mask(vec3(0.0, 1.0, 0.0), v_world_pos, snow_cover, 0.5, 0.15) * ice_mask;
		if (smask > 0.0) {
			vec2 suv = world_xz * 0.1;
			vec3 s_alb = clamp(texture(snow_albedo_tex, suv).rgb * snow_albedo_multiplier, 0.0, 0.9);
			float s_rough = texture(snow_roughness_tex, suv).r;
			vec3 s_norm = texture(snow_normal_tex, suv).rgb * 2.0 - 1.0;
			albedo = mix(albedo, s_alb, smask);
			rough = mix(rough, s_rough, smask);
			wn = normalize(mix(wn, s_norm, smask));
		}
	}

	// Fresnel: glancing angles brighten toward a sky-ish tone; the renderer's
	// own sky/SDFGI reflection (low roughness here) supplies the actual
	// reflected image, this just keeps the grazing-angle brightening plausible
	// even where the reflection probe is weak (e.g. under a bridge).
	float fres = pow(1.0 - clamp(dot(wn, view_dir), 0.0, 1.0), 4.0);
	vec3 sky_ish = vec3(0.62, 0.72, 0.82);
	albedo = mix(albedo, sky_ish, fres * 0.35 * (1.0 - ice_mask));

	ALBEDO = albedo;
	ROUGHNESS = clamp(rough, 0.03, 1.0);
	METALLIC = 0.0;
	SPECULAR = 0.6;
	ALPHA = alpha;
	NORMAL_MAP = wn * 0.5 + 0.5;
	NORMAL_MAP_DEPTH = 0.9;
}
