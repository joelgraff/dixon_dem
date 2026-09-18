// window_lit.gdshader — buildings workstream window material.
// One shared material for every building window (storefront + upper-floor):
// dark reflective glass by day, warm emissive glow at night on a per-window
// subset baked at mesh-build time. All per-window variation rides on vertex
// COLOR (no per-instance materials, per ART/perf guidance):
//   COLOR.r = lit flag (0/1) -- is this window one of the ~30-40% lit at night
//   COLOR.g = warmth 0..1 -- maps to a 2700K..3500K emissive color
//   COLOR.b = curtain/blind style 0..1 -- 0 open/bright, ~0.5 sheer curtain
//             (dimmer, softer glow), ~1 blinds (horizontal stripe pattern)
//   COLOR.a = storefront flag (0/1) -- storefronts glow brighter & wider
//
// Day look reuses the cheap procedural-glass approach from materials/glass.gdshader
// (tint + frost in winter + wet streaks in rain) rather than a screen-space
// refraction / parallax interior -- see docs/buildings_notes.md "Known weaknesses".

shader_type spatial;
render_mode blend_mix, cull_back, diffuse_burley, specular_schlick_ggx, depth_prepass_alpha;

#include "res://materials/shaders/includes/noise.gdshaderinc"

global uniform float snow_cover;
global uniform float wetness;
global uniform float night_factor;

uniform vec4 glass_tint : source_color = vec4(0.60, 0.70, 0.72, 0.38);
uniform float glass_roughness : hint_range(0.0, 0.3) = 0.07;
uniform vec2 pane_scale = vec2(1.0, 1.0);
uniform float emission_strength : hint_range(0.0, 4.0) = 1.8;

varying vec3 v_world_pos;

void vertex() {
	v_world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	vec2 uv = UV * pane_scale;
	vec3 tint = glass_tint.rgb;
	float alpha = glass_tint.a;
	float rough = glass_roughness;
	vec3 n = vec3(0.0, 0.0, 1.0);

	// Winter frost creeping from the edges.
	float frost = clamp(snow_cover, 0.0, 1.0);
	if (frost > 0.01) {
		vec2 c = uv - vec2(0.5);
		float edge = length(c) * 1.4;
		float fn = fbm(uv * 9.0);
		float frost_mask = clamp((edge + fn * 0.5 - 1.0) + frost * 1.6, 0.0, 1.0);
		tint = mix(tint, vec3(0.92, 0.95, 0.97), frost_mask);
		alpha = mix(alpha, 0.88, frost_mask);
		rough = mix(rough, 0.5, frost_mask);
		n = normalize(mix(n, vec3(fn - 0.5, fbm(uv * 9.0 + 5.0) - 0.5, 1.0), frost_mask * 0.6));
	}

	// Rain streaks.
	float wet = clamp(wetness * (1.0 - frost), 0.0, 1.0);
	if (wet > 0.01) {
		float drop = fbm(uv * 14.0 + vec2(0.0, -TIME * 0.02));
		float streak = smoothstep(0.55, 0.75, drop) * wet;
		n = normalize(mix(n, vec3((drop - 0.5) * 0.6, -0.8, 1.0), streak));
		rough = mix(rough, 0.08, streak);
	}

	// Curtain/blind hint visible through the glass during the day: a soft
	// pale band (sheer curtain) or horizontal stripes (blinds), cheap and
	// geometry-free.
	float curtain = COLOR.b;
	if (curtain > 0.02) {
		float blind_stripe = smoothstep(0.4, 0.6, abs(fract(uv.y * 9.0) - 0.5) * 2.0);
		float sheer = 1.0 - blind_stripe; // sheer look when curtain is low-mid, blinds when high
		vec3 curtain_color = vec3(0.85, 0.82, 0.74);
		float mix_amt = clamp(curtain, 0.0, 1.0) * mix(0.22, 0.4, sheer) * (1.0 - night_factor * 0.6);
		tint = mix(tint, curtain_color, mix_amt);
	}

	float lit = COLOR.r;
	float warm_t = COLOR.g;
	float storefront = COLOR.a;
	vec3 warm_lo = vec3(1.0, 0.62, 0.30); // ~2700K
	vec3 warm_hi = vec3(1.0, 0.80, 0.52); // ~3500K
	vec3 night_color = mix(warm_lo, warm_hi, warm_t);
	float glow = lit * night_factor;
	float strength = mix(emission_strength, emission_strength * 1.6, storefront);

	ALBEDO = mix(tint, night_color * 0.6, glow * 0.5);
	ALPHA = mix(alpha, 0.95, glow);
	ROUGHNESS = rough;
	METALLIC = 0.05;
	SPECULAR = 0.9;
	EMISSION = night_color * glow * strength;
	NORMAL_MAP = n * 0.5 + 0.5;
	NORMAL_MAP_DEPTH = 0.6;
}
