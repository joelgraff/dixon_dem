// glass.gdshader — procedural window glass (no textures). iter2 shipped this
// transparent (ALPHA<1) with a pale tint, which the critic correctly called a "grey
// veil you can see the siding through" rather than a window. Real exterior windows in
// daylight read as opaque dark panes dominated by sky/environment reflection (you very
// rarely actually see "through" a window from outside) — so this is now fully OPAQUE:
// a dark "interior" albedo plus a crisp low-roughness specular/Fresnel response does
// the visual work, no alpha blending or screen-texture refraction needed. Includes a
// thin inset frame (darker, rougher band at the pane edges) since there's no separate
// frame mesh in the test scene.

shader_type spatial;
render_mode cull_back, diffuse_burley, specular_schlick_ggx;

#include "res://materials/shaders/includes/noise.gdshaderinc"

global uniform float snow_cover;
global uniform float wetness;

uniform vec4 interior_color : source_color = vec4(0.035, 0.038, 0.042, 1.0); // dark "can't see in" interior, sRGB ~30-45
uniform vec4 frame_color : source_color = vec4(0.85, 0.85, 0.82, 1.0); // painted trim
uniform float frame_width : hint_range(0.0, 0.2) = 0.06; // fraction of pane UV
uniform float glass_roughness : hint_range(0.0, 0.3) = 0.045;
uniform float frost_amount_mult : hint_range(0.0, 1.0) = 1.0;
uniform vec2 pane_scale = vec2(1.0, 1.0);

varying vec3 v_world_pos;
varying vec3 v_world_normal;

void vertex() {
	v_world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	v_world_normal = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

void fragment() {
	vec2 uv = UV;
	vec3 albedo = interior_color.rgb;
	float rough = glass_roughness;
	float metallic = 0.0;
	float spec = 0.9; // drives the Fresnel/specular sky reflection strength
	vec3 n = vec3(0.0, 0.0, 1.0);

	// Thin frame inset from the pane edge.
	vec2 d = min(uv, vec2(1.0) - uv);
	float frame_mask = 1.0 - smoothstep(frame_width * 0.7, frame_width, min(d.x, d.y));
	albedo = mix(albedo, frame_color.rgb, frame_mask);
	rough = mix(rough, 0.55, frame_mask);
	spec = mix(spec, 0.3, frame_mask);

	vec2 puv = uv * pane_scale;
	float frost = clamp(snow_cover * frost_amount_mult, 0.0, 1.0) * (1.0 - frame_mask);
	if (frost > 0.01) {
		vec2 c = puv - vec2(0.5);
		float edge = length(c) * 1.4;
		float fn = fbm(puv * 9.0);
		float frost_mask = clamp((edge + fn * 0.5 - 1.0) + frost * 1.6, 0.0, 1.0);
		albedo = mix(albedo, vec3(0.85, 0.88, 0.90), frost_mask);
		rough = mix(rough, 0.55, frost_mask);
		n = normalize(mix(n, vec3(fn - 0.5, fbm(puv * 9.0 + 5.0) - 0.5, 1.0), frost_mask * 0.6));
	}

	float wet = clamp(wetness * (1.0 - frost), 0.0, 1.0) * (1.0 - frame_mask);
	if (wet > 0.01) {
		float drop = fbm(puv * 14.0 + vec2(0.0, -TIME * 0.02));
		float streak = smoothstep(0.55, 0.75, drop) * wet;
		n = normalize(mix(n, vec3((drop - 0.5) * 0.6, -0.8, 1.0), streak));
		rough = mix(rough, 0.08, streak);
	}

	ALBEDO = albedo;
	ROUGHNESS = rough;
	METALLIC = metallic;
	SPECULAR = spec;
	NORMAL_MAP = n * 0.5 + 0.5;
	NORMAL_MAP_DEPTH = 0.6;
}
