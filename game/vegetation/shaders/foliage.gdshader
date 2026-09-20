// foliage.gdshader — leaf-card canopy shader shared by every deciduous/conifer
// tree and shrub mesh this workstream builds. Cards are crossed double-quads
// (two-sided) with an analytic, texture-free blobby alpha mask (no baked
// Image/ImageTexture — see atmosphere_notes.md's "runtime-built ImageTexture
// went invisible" pitfall, avoided here on purpose).
//
// Per-vertex data baked once at mesh-build time (game/vegetation/tree_builder.gd):
//   COLOR      = (summer_r, summer_g, summer_b, cluster_ao)
//   CUSTOM0    = (autumn_r, autumn_g, autumn_b, wind_weight)
//   UV         = card-local 0..1, used for the analytic leaf-blob mask
//
// Season blend uses WorldState's season_foliage global directly (0 summer,
// 0.25 spring partial leaf-out, 0.75 autumn, 1.0 bare/winter — see
// docs/atmosphere_notes.md). Wind sway reads wind_strength. Snow/wetness
// reuse the shared materials includes per docs/materials_notes.md.
shader_type spatial;
render_mode world_vertex_coords, cull_disabled, diffuse_burley, specular_schlick_ggx;

#include "res://materials/shaders/includes/noise.gdshaderinc"
#include "res://materials/shaders/includes/snow.gdshaderinc"
#include "res://materials/shaders/includes/wetness.gdshaderinc"

global uniform float snow_cover;
global uniform float wetness;
global uniform float season_foliage;
global uniform float wind_strength;

uniform float backlight_strength : hint_range(0.0, 1.0) = 0.10;
uniform float roughness_val : hint_range(0.0, 1.0) = 0.75;
uniform float sway_speed : hint_range(0.0, 4.0) = 1.6;
uniform float sway_amount : hint_range(0.0, 1.0) = 0.55;

varying vec4 v_custom0;
varying float v_ao;
varying vec3 v_summer;

void vertex() {
	v_custom0 = CUSTOM0;
	v_ao = COLOR.a;
	v_summer = COLOR.rgb;

	vec3 world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	float phase = dot(world_pos.xz, vec2(0.19, 0.11)) + world_pos.y * 0.05;
	float weight = CUSTOM0.a * sway_amount * wind_strength;
	float sx = sin(TIME * sway_speed + phase);
	float sz = cos(TIME * sway_speed * 0.7 + phase * 1.6);
	VERTEX.x += sx * weight * 0.55;
	VERTEX.z += sz * weight * 0.35;
	VERTEX.y += abs(sx) * weight * 0.12;
}

// Analytic leaf-cluster mask: a soft card silhouette (UV-space) combined
// with a world-space hole-punch layer so the canopy reads as broken/leafy
// (sky and branch structure visible through scattered gaps) rather than one
// smooth flat-shaded lobe per card -- iter1 critique: "no sky holes, no
// branch structure showing through." World-space (not UV-space) so the
// gaps don't repeat identically on every card.
// value_noise (single octave) instead of fbm (3 octaves) here -- this runs
// per-fragment across heavy leaf-card overdraw (many overlapping alpha-
// scissor cards per tree, many trees per frame in a dense street), and the
// 3x cheaper single-octave noise is visually indistinguishable at this
// small a feature size. See "Performance" in docs/vegetation_notes.md.
float leaf_mask(vec2 uv, vec3 world_pos) {
	vec2 c = uv - vec2(0.5);
	float d = length(c) * 2.0;
	float edge_n = value_noise(uv * 4.0 + 11.0);
	float edge = 0.60 + (edge_n - 0.5) * 0.5;
	float base = 1.0 - smoothstep(edge - 0.22, edge, d);
	float hole_n = value_noise(world_pos.xz * 2.6 + world_pos.y * 1.9 + 5.0);
	float holes = smoothstep(0.28, 0.58, hole_n);
	return base * holes;
}

void fragment() {
	float t = clamp(season_foliage, 0.0, 1.0);
	vec3 world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;

	// Per-cluster (not per-species-uniform) autumn timing jitter -- iter1
	// critique: "vary per instance... a good fraction still green", since a
	// baked-per-species color alone reads as one flat uniform tint across
	// every tree of that species. Coarse world-space cell so a whole card
	// (not per-pixel) shares one jitter value; biased so more clusters read
	// less-turned than the global season_foliage value, a few more advanced.
	float turn_seed = hash21(floor(world_pos.xz * 0.4) + floor(world_pos.y * 0.4) * 13.1);
	float turn_jitter = mix(-0.42, 0.16, turn_seed);
	float t_col = clamp(t + turn_jitter, 0.0, 1.0);

	// Piecewise 4-keyframe season blend: 0 summer, 0.25 spring, 0.75 autumn, 1 winter.
	// (Static per-season captures only, per BUILDER_PROTOCOL -- continuity across
	// keyframes matters more here than exactly which color a live transition
	// passes through mid-tween; see docs/vegetation_notes.md known limitations.)
	vec3 spring_col = vec3(0.66, 0.78, 0.40);
	vec3 col;
	float density; // canopy fullness (spring is sparser; winter fades to 0) -- uses
	                // the REAL (unjittered) season value so bare-out timing stays
	                // globally consistent even though color timing is jittered.
	if (t_col <= 0.25) {
		float k = smoothstep(0.0, 0.25, t_col);
		col = mix(v_summer, spring_col, k);
	} else if (t_col <= 0.75) {
		float k = smoothstep(0.25, 0.75, t_col);
		col = mix(spring_col, v_custom0.rgb, k);
	} else {
		col = v_custom0.rgb;
	}
	if (t <= 0.25) {
		density = mix(1.0, 0.6, smoothstep(0.0, 0.25, t));
	} else if (t <= 0.75) {
		density = mix(0.6, 1.0, smoothstep(0.25, 0.75, t));
	} else {
		density = mix(1.0, 0.0, smoothstep(0.75, 1.0, t));
	}

	float mask = leaf_mask(UV, world_pos) * density;
	ALPHA = mask;
	ALPHA_SCISSOR_THRESHOLD = 0.5;

	vec3 albedo = col * mix(0.32, 0.8, v_ao);
	float rough = roughness_val;

	// snow_cover/wetness are uniform globals (same value every fragment in
	// this draw), so these branches skip the fbm-heavy snow_mask() call
	// entirely outside winter/rain instead of paying for it on every pixel
	// of every summer-clear leaf card.
	if (snow_cover > 0.005) {
		vec3 world_normal = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
		float smask = snow_mask(world_normal, world_pos, snow_cover, 0.15, 0.35);
		// snow sits on top of leaf cards; winter (bare) canopy catches snow on
		// the twig/bark surface instead, so fade this out as leaves disappear.
		smask *= density;
		albedo = mix(albedo, vec3(0.85, 0.87, 0.9), smask * 0.85);
	}
	if (wetness > 0.005) {
		apply_wetness_darkening(albedo, rough, wetness, 0.3);
	}

	ALBEDO = albedo;
	ROUGHNESS = rough;
	METALLIC = 0.0;
	BACKLIGHT = albedo * backlight_strength * density;
	SPECULAR = 0.25;
}
