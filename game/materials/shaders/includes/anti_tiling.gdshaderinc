// anti_tiling.gdshaderinc — tiling-break helpers.
//
// Two different strategies, because one trick doesn't serve both kinds of material:
//
// - Non-directional materials (stone, gravel, asphalt, grass, dirt, snow): a genuine
//   2-grid stochastic blend (anti_tile_blend). A single hard per-cell offset/rotation
//   still leaves a visible seam at every cell boundary (iter2's bug — confirmed by the
//   critic measuring a brightness step at a tile edge in brick AND snow). Blending two
//   independently-offset/rotated grids, weighted so each grid's seam falls inside the
//   other grid's cell interior, removes the seam entirely at the cost of a second
//   texture sample.
//
// - Directional/coursed materials (brick, siding, shingles, corrugated metal): NEITHER
//   rotation NOR translation can hide the repeat without breaking coursing (rotating
//   flips mortar lines sideways; offsetting desyncs courses at the boundary — both
//   confirmed broken in iter1/iter2). For these, anti_tile_uv() with allow_rotation=false
//   now returns the UV **unchanged** — the repeat is instead hidden by per-module color
//   variation (see module_variation() below) applied by the calling shader, which breaks
//   the "obviously repeating" read without touching the geometry of the coursing at all.

#include "res://materials/shaders/includes/noise.gdshaderinc"

// Single-grid transform used internally by anti_tile_blend's two taps.
vec2 _tile_tap(vec2 uv, vec2 hash_seed_a, vec2 hash_seed_b, out float rot_id) {
	vec2 cell = floor(uv);
	vec2 f = fract(uv);
	float h = hash21(cell + hash_seed_a);
	rot_id = floor(h * 4.0);
	vec2 centered = f - 0.5;
	float ang = rot_id * 1.5707963268;
	vec2 rotated = rotate2(centered, ang) + 0.5;
	vec2 off = hash22(cell + hash_seed_b) * 1.7;
	return rotated + off;
}

// Legacy single-tap entry point, kept for callers that only need one UV. Directional
// materials (allow_rotation=false) get the UV back untouched — see file header.
vec2 anti_tile_uv(vec2 uv, bool allow_rotation, out float rot_id) {
	if (!allow_rotation) {
		rot_id = 0.0;
		return uv;
	}
	return _tile_tap(uv, vec2(0.0), vec2(11.0, 71.0), rot_id);
}

// Two-grid stochastic blend: call once per surface point, sample every map (albedo/
// normal/rough/AO) at BOTH uv_a and uv_b, unpack+rotate normals with rot_a/rot_b
// respectively, then mix the two fully-assembled samples by `weight` (weight=1 means
// "use sample B"). Only meaningful when allow_rotation is true; for directional
// materials just sample uv_a once and ignore uv_b/weight (weight will be 0).
void anti_tile_blend(vec2 uv, bool allow_rotation, out vec2 uv_a, out vec2 uv_b,
		out float rot_a, out float rot_b, out float weight) {
	if (!allow_rotation) {
		uv_a = uv;
		uv_b = uv;
		rot_a = 0.0;
		rot_b = 0.0;
		weight = 0.0;
		return;
	}
	vec2 gb = uv + vec2(0.5, 0.5); // second grid, offset half a cell from the first
	uv_a = _tile_tap(uv, vec2(0.0), vec2(11.0, 71.0), rot_a);
	uv_b = _tile_tap(gb, vec2(91.0), vec2(37.0, 53.0), rot_b);

	vec2 fa = fract(uv);
	vec2 fb = fract(gb);
	// Distance-to-this-grid's-own-cell-edge: whichever grid we're deepest inside of
	// contributes least of the OTHER grid's edge, so blending toward the shallower one
	// hides each grid's seam inside the other's interior.
	float wa = min(fa.x, 1.0 - fa.x) * min(fa.y, 1.0 - fa.y);
	float wb = min(fb.x, 1.0 - fb.x) * min(fb.y, 1.0 - fb.y);
	weight = wb / max(wa + wb, 0.0001);
}

// Rotate an already-unpacked tangent-space normal (xy in [-1,1], z up) to match
// anti_tile_uv's rotation so lighting stays consistent with the rotated sample.
vec3 rotate_tiled_normal(vec3 n, float rot_id) {
	if (rot_id < 0.5) {
		return n;
	} else if (rot_id < 1.5) {
		return vec3(-n.y, n.x, n.z);
	} else if (rot_id < 2.5) {
		return vec3(-n.x, -n.y, n.z);
	} else {
		return vec3(n.y, -n.x, n.z);
	}
}

// Large-scale multiplicative + slight hue-shift color variation to break up big flat
// expanses (fields, roads) beyond what per-tile rotation alone hides.
vec3 macro_variation(vec3 albedo, vec2 world_xz, float scale, float strength) {
	float n = fbm(world_xz * scale);
	float shade = mix(1.0 - strength, 1.0 + strength * 0.6, n);
	float n2 = fbm(world_xz * scale * 0.37 + 91.0);
	vec3 hue_shift = mix(vec3(0.98, 1.0, 1.03), vec3(1.03, 1.0, 0.96), n2);
	return albedo * shade * mix(vec3(1.0), hue_shift, strength);
}

// Per-module color variation for directional/coursed materials (brick, siding) — this
// is what actually hides their repeat, since neither rotation nor offset is usable on
// them (see file header). module_uv is the tiled UV divided by the real module size in
// the same UV units, e.g. for a 1x1 UV tile holding a 1m x 1m brick photo with ~5
// bricks across and ~15 courses tall, module_uv = uv * vec2(5.0, 15.0). Returns a
// multiplier close to 1.0 (brightness ± amount, slight hue drift) — apply ONLY to brick
// pixels, never mortar (callers separate the two with a mask).
vec3 module_variation(vec2 module_uv, float amount) {
	vec2 cell = floor(module_uv);
	float h1 = hash21(cell + 5.0);
	float h2 = hash21(cell + 47.0);
	float shade = 1.0 + (h1 - 0.5) * 2.0 * amount;
	vec3 hue = mix(vec3(1.0 - 0.4 * amount, 1.0, 1.0 + 0.25 * amount),
			vec3(1.0 + 0.3 * amount, 1.0, 1.0 - 0.3 * amount), h2);
	return shade * hue;
}
