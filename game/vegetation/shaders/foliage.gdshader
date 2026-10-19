// foliage.gdshader — leaf-card canopy shader shared by every deciduous/conifer
// tree and shrub mesh this workstream builds. Cards are crossed double-quads
// (two-sided) with an analytic, texture-free leaf-clump alpha mask (no baked
// Image/ImageTexture — see atmosphere_notes.md's "runtime-built ImageTexture
// went invisible" pitfall, avoided here on purpose).
//
// Per-vertex data baked once at mesh-build time (game/vegetation/tree_builder.gd):
//   COLOR      = (summer_r, summer_g, summer_b, cluster_ao)
//   CUSTOM0    = (autumn_r, autumn_g, autumn_b, wind_weight)
//   UV         = card-local 0..1, used for the analytic leaf mask
//   NORMAL     = crown-volume normal (outward from the crown centre), not the
//                card plane's normal, so the canopy shades as one lit volume
//                instead of a scatter of differently-lit flat cards.
//
// Season blend uses WorldState's season_foliage global (0 summer, 0.25 spring
// partial leaf-out, 0.75 autumn, 1.0 bare/winter — see docs/atmosphere_notes.md).
// Evergreen materials (conifers, arborvitae) keep their needles all year.
// Per-tree LOD fade, tint and turn timing come from tree_common.gdshaderinc,
// shared with the far impostor so the two agree across the crossfade.
shader_type spatial;
render_mode world_vertex_coords, cull_disabled, diffuse_burley, specular_schlick_ggx;

#include "res://materials/shaders/includes/noise.gdshaderinc"
#include "res://materials/shaders/includes/snow.gdshaderinc"
#include "res://materials/shaders/includes/wetness.gdshaderinc"
#include "res://vegetation/shaders/tree_common.gdshaderinc"

global uniform float snow_cover;
global uniform float wetness;
global uniform float season_foliage;
global uniform float wind_strength;

uniform float backlight_strength : hint_range(0.0, 1.0) = 0.14;
uniform float roughness_val : hint_range(0.0, 1.0) = 0.75;
uniform float sway_speed : hint_range(0.0, 4.0) = 1.6;
uniform float sway_amount : hint_range(0.0, 1.0) = 0.55;
uniform bool evergreen = false;
// Bare-twig haze on leafless cards. Off by default: with TAA it read as
// pale blue fog round near crowns and cost ~3 fps in winter; the near mesh's
// third branch level carries the bare silhouette instead.
uniform float twig_haze : hint_range(0.0, 1.0) = 0.0;

varying float v_ao;
varying vec3 v_col; // season colour, resolved per vertex (per-tree/per-cluster inputs only)
varying float v_density;
varying vec3 v_world_pos;
varying vec3 v_world_normal;
varying flat vec3 v_origin;
varying flat float v_fade;
varying flat float v_card_seed;

void vertex() {
	v_ao = COLOR.a;
	v_origin = MODEL_MATRIX[3].xyz;
	// Per-card seed: every vertex of a card shares its jittered AO value
	// (tree_builder.gd), so this is constant across the card.
	v_card_seed = fract(COLOR.a * 91.731 + veg_hash(v_origin.xz));
	v_fade = veg_lod_fade(v_origin);

	// Season colour depends only on the tree, the cluster and the species
	// colours baked per vertex, so resolve it here rather than per fragment
	// (foliage is fill-rate bound: every card pixel runs the fragment shader
	// in the depth prepass, the colour pass and each shadow cascade).
	// Autumn timing: per-tree jitter (shared with the impostor) plus a small
	// per-cluster spread inside one crown.
	float t = evergreen ? 0.0 : clamp(season_foliage, 0.0, 1.0);
	float cluster_jitter = (hash21(floor(VERTEX.xz * 0.4) + floor(VERTEX.y * 0.4) * 13.1) - 0.5) * 0.16;
	float t_col = clamp(t + veg_tree_turn_jitter(v_origin) + cluster_jitter, 0.0, 1.0);
	vec3 summer = veg_instance_tint(COLOR.rgb, v_origin);
	vec3 autumn = veg_instance_tint(CUSTOM0.rgb, v_origin);
	v_col = veg_season_color(summer, autumn, t_col);
	v_density = evergreen ? 1.0 : veg_leaf_density(t);

	// world_vertex_coords: VERTEX/NORMAL are already world space here.
	vec3 world_pos = VERTEX;
	float phase = dot(world_pos.xz, vec2(0.19, 0.11)) + world_pos.y * 0.05;
	float weight = CUSTOM0.a * sway_amount * wind_strength;
	float sx = sin(TIME * sway_speed + phase);
	float sz = cos(TIME * sway_speed * 0.7 + phase * 1.6);
	VERTEX.x += sx * weight * 0.55;
	VERTEX.z += sz * weight * 0.35;
	VERTEX.y += abs(sx) * weight * 0.12;
	v_world_pos = VERTEX;
	v_world_normal = NORMAL;

	// Fully handed over to the impostor: collapse to a degenerate point so
	// the (still chunk-visible) instance costs no fragments.
	if (v_fade >= 1.0) {
		VERTEX = v_origin;
	}
}

// Leaf-clump mask: a soft card silhouette broken into leaf-sized lobes by two
// octaves of UV noise (seeded per card from its world position, so cards
// don't repeat); the gaps between lobes are the sky holes. The fine octave fades out
// once it gets close to pixel size, so distant crowns don't sparkle.
float leaf_mask(vec2 uv, vec3 world_pos, float card_seed) {
	vec2 c = uv - vec2(0.5);
	float d = length(c) * 2.0;
	float edge_n = value_noise(uv * 3.0 + card_seed * 17.0);
	float edge = 0.80 + (edge_n - 0.5) * 0.45;
	float base = 1.0 - smoothstep(edge - 0.30, edge, d);
	vec2 luv = uv + card_seed * 31.0;
	vec2 fine_uv = luv * 30.0;
	float fine_w = 1.0 - smoothstep(0.35, 0.9, length(fwidth(fine_uv)));
	float fine = mix(0.5, value_noise(fine_uv), fine_w);
	float lobes = value_noise(luv * 11.0) * 0.6 + fine * 0.4;
	return base * smoothstep(0.34, 0.54, lobes) * 1.6;
}

void fragment() {
	// LOD crossfade with the impostor (same dither, inverted there).
	if (v_fade > 0.0 && veg_dither(FRAGCOORD.xy, TIME) < v_fade) {
		discard;
	}

	float t = evergreen ? 0.0 : clamp(season_foliage, 0.0, 1.0);
	float card_seed = v_card_seed;
	vec3 col = v_col;
	float density = v_density;

	float leaf = leaf_mask(UV, v_world_pos, card_seed) * density;
	// Cards seen edge-on smear into long streaks; fade them out (geometric
	// card normal from screen derivatives, since NORMAL is the crown normal).
	vec3 card_n = normalize(cross(dFdx(VERTEX), dFdy(VERTEX)));
	leaf *= smoothstep(0.12, 0.35, abs(dot(card_n, normalize(VERTEX))));
	vec3 albedo = col * mix(0.32, 0.8, v_ao);

	// Bare crowns: twig haze, faded in with distance (close up the real
	// branch cylinders carry the silhouette and haze cards would read as
	// scribbles).
	float twig_w = evergreen ? 0.0 : veg_twig_weight(t) * twig_haze;
	if (twig_w > 0.0) {
		float cam_d = distance(v_world_pos, veg_camera_pos);
		twig_w *= smoothstep(10.0, 28.0, cam_d);
		// ~45 % stochastic coverage inside the card's soft disc: with TAA
		// it reads as the grey-brown haze of a bare crown's fine twigs
		// (an analytic line pattern aliased into blocky scribbles).
		float disc = 1.0 - smoothstep(0.3, 0.75, length(UV - vec2(0.5)) * 2.0);
		float twig = step(veg_dither(FRAGCOORD.yx * 1.37 + 17.0, TIME * 1.7), disc * twig_w * 0.45);
		if (twig > leaf) {
			albedo = VEG_TWIG_COLOR * mix(0.6, 1.0, v_ao);
			leaf = twig;
		}
	}
	ALPHA = leaf;
	ALPHA_SCISSOR_THRESHOLD = 0.5;

	// Godot flips NORMAL on back faces of cull_disabled geometry; the baked
	// crown-volume normal is already correct for both sides.
	if (!FRONT_FACING) {
		NORMAL = -NORMAL;
	}

	float rough = roughness_val;
	// snow_cover/wetness are uniform globals (same value every fragment in
	// this draw), so these branches skip the noise-heavy snow_mask() call
	// entirely outside winter/rain.
	if (snow_cover > 0.005) {
		float smask = snow_mask(normalize(v_world_normal), v_world_pos, snow_cover, 0.15, 0.35);
		// Snow sits on needles/leaves; a bare crown's twig haze stays dark
		// (the bark shader whitens the real branch tops).
		// (crown-volume normals point mostly up, so scale back or whole
		// conifers read as white cones)
		smask *= density;
		albedo = mix(albedo, vec3(0.85, 0.87, 0.9), smask * 0.5);
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
