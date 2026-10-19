// tree_impostor.gdshader — far-LOD tree: one camera-facing quad per tree,
// drawn by MultiMesh (vegetation.gd). The crown silhouette, trunk, shading
// and season response are analytic so no texture bake is needed.
//
// Per instance:
//   basis column 0 length = crown width (m), column 1 length = tree height (m)
//   INSTANCE_CUSTOM = (summer rgb packed 8:8:8, autumn rgb packed 8:8:8,
//                      form 0 deciduous / 1 conifer, crown base 0..1 of height)
// The species colours, per-tree tint and autumn timing come from the same
// functions the near mesh uses (tree_common.gdshaderinc), and the LOD fade
// is the near layer's fade inverted with the same screen dither, so a tree
// crossfades between the two without a colour or coverage jump.
shader_type spatial;
render_mode world_vertex_coords, cull_disabled, diffuse_burley, specular_schlick_ggx;

#include "res://materials/shaders/includes/noise.gdshaderinc"
#include "res://materials/shaders/includes/snow.gdshaderinc"
#include "res://vegetation/shaders/tree_common.gdshaderinc"

global uniform float snow_cover;
global uniform float season_foliage;

uniform float backlight_strength : hint_range(0.0, 1.0) = 0.22;
// Shadow-only copy (vegetation.gd): draws every tree regardless of LOD, so
// all tree shadows come from these light-facing quads.
uniform bool shadow_proxy = false;

varying flat vec3 v_origin;
varying flat float v_fade;
varying flat vec4 v_custom;
varying flat float v_aspect;

vec3 unpack_rgb(float p) {
	float v = floor(p + 0.5);
	float r = mod(v, 256.0);
	float g = mod(floor(v / 256.0), 256.0);
	float b = floor(v / 65536.0);
	return vec3(r, g, b) / 255.0;
}

void vertex() {
	v_origin = MODEL_MATRIX[3].xyz;
	v_custom = INSTANCE_CUSTOM;
	v_fade = veg_lod_fade(v_origin);
	float w = length(MODEL_MATRIX[0].xyz);
	float h = length(MODEL_MATRIX[1].xyz);
	v_aspect = h / max(w, 0.01);

	// Camera-facing quad pivoted at the crown centre, so the crown reads as
	// a round volume from any elevation (a world-up quad seen from above
	// foreshortens to a sliver).
	float cb = INSTANCE_CUSTOM.w;
	float pivot = mix(cb, 1.0, 0.5);
	vec3 cam_right = normalize(INV_VIEW_MATRIX[0].xyz);
	vec3 cam_up = normalize(INV_VIEW_MATRIX[1].xyz);
	vec3 centre = v_origin + vec3(0.0, pivot * h, 0.0);
	vec3 world = centre + cam_right * (UV.x - 0.5) * w + cam_up * (UV.y - pivot) * h;
	if (v_fade <= 0.0 && !shadow_proxy) {
		world = v_origin; // fully near-LOD: degenerate, no fragments
	}
	// world_vertex_coords: VERTEX/NORMAL are world space here.
	VERTEX = world;
	NORMAL = INV_VIEW_MATRIX[2].xyz;
}

void fragment() {
	if (!shadow_proxy && veg_dither(FRAGCOORD.xy, TIME) >= v_fade) {
		discard;
	}
	float seed = veg_hash(v_origin.xz * 0.917 + 1.3);
	bool conifer = v_custom.z > 0.5;
	float cb = v_custom.w;
	vec2 uv = UV;
	// Leaf-clump noise in roughly metre-proportional UV (crown is w wide, h tall).
	vec2 nuv = vec2(uv.x, uv.y * v_aspect);
	float lobes = value_noise(nuv * 7.0 + seed * 41.0) * 0.6 + value_noise(nuv * 16.0 + seed * 7.0) * 0.4;

	float crown;
	vec2 q; // crown-local coords (-1..1), for shading
	if (conifer) {
		float k = clamp((uv.y - cb) / (1.0 - cb), 0.0, 1.0);
		// Tiered outline: whorls of branches, slightly ragged.
		float tiers = 0.86 + 0.14 * sin(k * 34.0 + seed * 6.0);
		float half_w = 0.5 * pow(1.0 - k, 0.9) * tiers * (0.9 + 0.2 * value_noise(nuv * 5.0 + seed * 9.0));
		float x = abs(uv.x - 0.5);
		crown = (uv.y >= cb) ? 1.0 - smoothstep(half_w - 0.04, half_w, x) : 0.0;
		crown *= smoothstep(0.22, 0.40, lobes + 0.15);
		q = vec2((uv.x - 0.5) * 2.0, k * 2.0 - 1.0);
	} else {
		q = vec2((uv.x - 0.5) * 2.0, (uv.y - (cb + 1.0) * 0.5) / ((1.0 - cb) * 0.5));
		float r = length(q);
		// Lumpy outline from two noise octaves; the underside is pulled in
		// more so crowns don't sit on a flat, mushroom-like base.
		float edge = 1.0 - 0.22 * value_noise(q * 2.1 + seed * 37.0) - 0.14 * value_noise(q * 5.3 + seed * 11.0);
		edge -= 0.12 * smoothstep(0.0, -1.0, q.y);
		crown = 1.0 - smoothstep(edge - 0.10, edge, r);
		// Ragged clumps towards the edge, solid in the middle.
		crown *= smoothstep(0.30, 0.48, lobes + (1.0 - r) * 0.40);
	}

	// Trunk below the crown.
	float tw = 0.022 + 0.018 * (1.0 - uv.y);
	float trunk = (abs(uv.x - 0.5) < tw && uv.y < cb + 0.12) ? 1.0 : 0.0;

	float t = conifer ? 0.0 : clamp(season_foliage, 0.0, 1.0);
	float t_col = clamp(t + veg_tree_turn_jitter(v_origin), 0.0, 1.0);
	vec3 summer = veg_instance_tint(unpack_rgb(v_custom.x), v_origin);
	vec3 autumn = veg_instance_tint(unpack_rgb(v_custom.y), v_origin);
	vec3 col = veg_season_color(summer, autumn, t_col);
	float density = conifer ? 1.0 : veg_leaf_density(t);

	// Crown AO: darker low and inside the clumps, lit top.
	// Clump interiors lit, gaps between clumps dark, as in the near mesh.
	float ao = clamp(mix(0.48, 0.95, q.y * 0.5 + 0.5) * mix(0.55, 1.25, smoothstep(0.3, 0.75, lobes)), 0.3, 1.0);
	vec3 albedo = col * mix(0.32, 0.8, ao);
	float leaf = crown * (density > 0.999 ? 1.0 : step(1.0 - density, lobes));

	// Bare deciduous crown: a few main limbs fanning up from the trunk top
	// (so a distant bare tree isn't a post under a cloud) plus a light,
	// dark twig haze concentrated in the inner crown. The shadow proxy keeps
	// only trunk and limbs: dithered haze cast solid-looking disc shadows.
	float twig_w = conifer ? 0.0 : veg_twig_weight(t);
	float limb = 0.0;
	if (twig_w > 0.0 && leaf < 0.5) {
		vec2 base = vec2(0.5, cb + 0.04);
		for (int k = 0; k < 5; k++) {
			float a = (float(k) - 2.0) * 0.36 + (veg_hash(vec2(seed * 13.0, float(k))) - 0.5) * 0.3;
			vec2 tip = base + vec2(sin(a) * 0.46, cos(a) * (0.92 - cb));
			vec2 pa = uv - base;
			vec2 ba = tip - base;
			float hk = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
			float lw = mix(0.016, 0.004, hk);
			limb = max(limb, step(length(pa - ba * hk), lw));
		}
		float inner = 1.0 - smoothstep(0.35, 0.95, length(q));
		float haze = shadow_proxy ? 0.0 : inner * twig_w * 0.28;
		if (limb > 0.5 || veg_dither(FRAGCOORD.yx * 1.37 + 17.0, TIME * 1.7) < haze) {
			leaf = 1.0;
			albedo = VEG_TWIG_COLOR * mix(0.7, 1.0, ao);
		}
	}
	float bark = trunk * (1.0 - step(0.5, leaf));
	if (bark > 0.5) {
		albedo = vec3(0.075, 0.062, 0.05);
	}
	ALPHA = max(leaf, bark);
	ALPHA_SCISSOR_THRESHOLD = 0.5;

	// Pseudo-volume normal (view space; the quad faces the camera).
	vec2 nq = clamp(q, vec2(-1.0), vec2(1.0)) * 0.8;
	vec3 n = normalize(vec3(nq.x, nq.y + 0.25, sqrt(max(0.05, 1.0 - dot(nq, nq)))));
	if (bark > 0.5) {
		n = normalize(vec3((uv.x - 0.5) / tw * 0.8, 0.0, 1.0));
	}
	NORMAL = n;

	if (snow_cover > 0.005 && leaf > 0.5) {
		vec3 wn = (INV_VIEW_MATRIX * vec4(n, 0.0)).xyz;
		float smask = snow_mask(wn, v_origin + vec3(uv.x, uv.y, 0.0) * 4.0, snow_cover, 0.15, 0.35);
		albedo = mix(albedo, vec3(0.85, 0.87, 0.9), smask * 0.85 * density);
	}

	ALBEDO = albedo;
	ROUGHNESS = 0.8;
	METALLIC = 0.0;
	SPECULAR = 0.2;
	BACKLIGHT = albedo * backlight_strength * density;
}
