// glass.gdshader — procedural window glass (no textures). Slight tint, near-mirror
// specular, weather-reactive: frosts over at the edges in winter (snow_cover) and
// gets streaky rain droplets when wet (wetness). Cheap: a couple of noise taps, no
// screen-texture refraction (keeps it usable on many windows at once on the RX 580
// budget — buildings/landmarks can swap in a refractive variant later if needed).

shader_type spatial;
render_mode blend_mix, cull_back, diffuse_burley, specular_schlick_ggx, depth_prepass_alpha;

#include "res://materials/shaders/includes/noise.gdshaderinc"

global uniform float snow_cover;
global uniform float wetness;

uniform vec4 glass_tint : source_color = vec4(0.78, 0.85, 0.86, 0.35);
uniform float glass_roughness : hint_range(0.0, 0.3) = 0.04;
uniform float frost_amount_mult : hint_range(0.0, 1.0) = 1.0; // per-instance sensitivity
uniform vec2 pane_scale = vec2(1.0, 1.0); // tiles the droplet/frost noise to the pane

varying vec3 v_world_pos;
varying vec3 v_world_normal;

void vertex() {
	v_world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	v_world_normal = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

void fragment() {
	vec2 uv = UV * pane_scale;
	vec3 tint = glass_tint.rgb;
	float alpha = glass_tint.a;
	float rough = glass_roughness;
	vec3 n = vec3(0.0, 0.0, 1.0);

	float frost = clamp(snow_cover * frost_amount_mult, 0.0, 1.0);
	if (frost > 0.01) {
		// frost creeps in from the pane edges (corner/edge noise), not a flat wash
		vec2 c = uv - vec2(0.5);
		float edge = length(c) * 1.4;
		float fn = fbm(uv * 9.0);
		float frost_mask = clamp((edge + fn * 0.5 - 1.0) + frost * 1.6, 0.0, 1.0);
		tint = mix(tint, vec3(0.92, 0.95, 0.97), frost_mask);
		alpha = mix(alpha, 0.88, frost_mask);
		rough = mix(rough, 0.5, frost_mask);
		n = normalize(mix(n, vec3(fn - 0.5, fbm(uv * 9.0 + 5.0) - 0.5, 1.0), frost_mask * 0.6));
	}

	float wet = clamp(wetness * (1.0 - frost), 0.0, 1.0);
	if (wet > 0.01) {
		float drop = fbm(uv * 14.0 + vec2(0.0, -TIME * 0.02));
		float streak = smoothstep(0.55, 0.75, drop) * wet;
		n = normalize(mix(n, vec3((drop - 0.5) * 0.6, -0.8, 1.0), streak));
		rough = mix(rough, 0.08, streak);
	}

	ALBEDO = tint;
	ALPHA = alpha;
	ROUGHNESS = rough;
	METALLIC = 0.05;
	SPECULAR = 0.9;
	NORMAL_MAP = n * 0.5 + 0.5;
	NORMAL_MAP_DEPTH = 0.6;
}
