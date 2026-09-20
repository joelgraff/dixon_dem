// grass.gdshader — near-camera GPU MultiMesh grass blades (game/vegetation/grass_spawner.gd).
// Crossed double-quad blades, analytic taper (no texture), wind sway, season color
// (mown green summer -> dormant tan winter, hidden under snow_cover), and a
// per-instance "tallness" (mown lawn vs unmown riverbank/park) baked as vertex color.
//
// Per-vertex data:
//   COLOR.a = tallness (0 = mown lawn, 1 = unmown/riverbank — taller, more sway)
//   UV.y    = 0 at blade base, 1 at tip (used for taper + bend + snow burial)
shader_type spatial;
render_mode world_vertex_coords, cull_disabled, diffuse_burley, specular_schlick_ggx;

#include "res://materials/shaders/includes/noise.gdshaderinc"

global uniform float snow_cover;
global uniform float wetness;
global uniform float season_foliage;
global uniform float wind_strength;

// Linear albedo matched to terrain's measured lawn target (sRGB 91,123,63,
// sat ~0.49 -> linear ~0.105,0.197,0.050) per the 2026-09-19 composed-frame
// review, so near-field grass agrees with terrain's baked lawn splat instead
// of reading as a seam.
uniform vec3 color_summer_mown : source_color = vec3(0.105, 0.197, 0.050);
uniform vec3 color_summer_tall : source_color = vec3(0.085, 0.165, 0.045);
uniform vec3 color_dormant : source_color = vec3(0.26, 0.21, 0.12);

varying float v_tall;
varying float v_tip;

void vertex() {
	v_tall = COLOR.a;
	v_tip = UV.y;

	vec3 world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	float phase = dot(world_pos.xz, vec2(0.7, 0.5));
	float bend = sin(TIME * 2.2 + phase) * (0.15 + 0.35 * v_tall) * wind_strength;
	// only the tip sways (base stays pinned to the ground)
	VERTEX.x += bend * v_tip * v_tip;

	// winter: bury short mown grass under snow_cover, tall grass pokes through longer
	float bury_at = mix(0.35, 0.85, v_tall);
	float buried = clamp(snow_cover / max(bury_at, 0.001), 0.0, 1.0);
	VERTEX.y *= mix(1.0, 1.0 - 0.9 * buried, 1.0 - v_tip * 0.3);
}

void fragment() {
	float t = clamp(season_foliage, 0.0, 1.0);
	vec3 green = mix(color_summer_mown, color_summer_tall, v_tall);
	// dormant (tan/straw) sets in through autumn->winter; spring greens back up fast
	float dormancy = smoothstep(0.3, 0.85, t);
	vec3 base = mix(green, color_dormant, dormancy);
	// slight per-blade hue jitter so a lawn isn't a flat color
	float jitter = value_noise(FRAGCOORD.xy * 0.3) * 0.05 - 0.025;
	base += jitter;

	// blade tip taper is geometric (tree_builder.gd narrows the tip verts),
	// not alpha-cutout, so blades stay fully opaque -- no scissor needed.
	ALPHA = 1.0;

	vec3 world_normal = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
	float snow_on_tip = smoothstep(0.2, 0.9, v_tip) * snow_cover * 0.6;
	vec3 albedo = mix(base, vec3(0.88, 0.9, 0.92), snow_on_tip);
	albedo *= mix(1.0, 0.75, wetness * 0.5);

	ALBEDO = albedo;
	ROUGHNESS = 0.85;
	METALLIC = 0.0;
	BACKLIGHT = base * 0.12;
}
