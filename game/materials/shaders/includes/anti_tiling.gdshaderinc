// anti_tiling.gdshaderinc — per-tile random rotate+offset ("stochastic tiling lite").
// Cheap alternative to full hex/blend tiling: each 1x1 UV cell gets a hashed 90-degree
// rotation and sub-texel offset, so repeated tiles no longer line up into an obviously
// periodic pattern. Works with any seamless/tileable source texture. Costs one hash
// per sample, no extra texture fetches (unlike blend-based stochastic tiling).
//
// Usage: call anti_tile_uv() once per surface point to get the transformed UV and a
// rot_id (0..3), then sample color/rough/AO maps with that UV, and pass rot_id to
// rotate_tiled_normal() after sampling+unpacking the normal map.

#include "res://materials/shaders/includes/noise.gdshaderinc"

// allow_rotation: set false for materials with strong directional grain (brick
// coursing, lapped siding, corrugated metal, shingle courses) — a 90-degree rotation
// turns horizontal mortar/lap lines vertical in alternating cells, which reads as an
// obvious "quilt" rather than hidden tiling. Offset-only still desyncs the repeat for
// those; rotation is only worth it for non-directional materials (stone, gravel,
// asphalt, grass, dirt, snow).
vec2 anti_tile_uv(vec2 uv, bool allow_rotation, out float rot_id) {
	vec2 cell = floor(uv);
	vec2 f = fract(uv);
	rot_id = 0.0;
	vec2 rotated = f;
	vec2 off;
	if (allow_rotation) {
		float h = hash21(cell);
		rot_id = floor(h * 4.0);
		vec2 centered = f - 0.5;
		float ang = rot_id * 1.5707963268; // 0/90/180/270 deg
		rotated = rotate2(centered, ang) + 0.5;
		// Modest offset in both axes: fine for non-directional materials (stone,
		// gravel, asphalt, grass, dirt, snow) where there's no coursing to break.
		off = hash22(cell + vec2(11.0, 71.0)) * 1.3;
	} else {
		// Directional/coursed materials (brick, siding, shingles, corrugated metal):
		// a per-cell offset in Y breaks mortar/lap-line continuity at every tile
		// boundary, and an unquantized X offset misaligns vertical joints between
		// columns. So: zero vertical offset (courses stay continuous top-to-bottom),
		// and a horizontal offset that (a) depends only on cell.x, so it's constant
		// for an entire column and doesn't create seams within it, and (b) is
		// quantized to a coarse module so a column-to-column shift reads as an
		// intentional coursing offset between wall sections, not a random jump.
		float hx = hash21(vec2(cell.x, 0.0) + 11.0);
		float steps = 6.0;
		off = vec2(floor(hx * steps) / steps, 0.0);
	}
	return rotated + off;
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
