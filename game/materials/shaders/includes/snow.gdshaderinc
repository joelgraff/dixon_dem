// snow.gdshaderinc — shared "snow accumulation" mask so terrain/roads/vegetation
// blend toward a snow layer the same way the core surface shader does.
// Reads the global `snow_cover` uniform (declared by whichever shader includes this,
// see surface.gdshader) — pass it in explicitly here to keep this include reusable
// even in shaders that alias/clamp it differently.

#include "res://materials/shaders/includes/noise.gdshaderinc"

// world_normal: world-space normal (upward-facing surfaces accumulate first).
// world_pos: world-space position, used to seed noise so the edge isn't a clean ring.
// snow_cover: 0..1 global amount.
// slope_bias: per-material offset; positive = accumulates more readily (e.g. flat
//             roofs/lawns), negative = resists snow (e.g. steep roof, vertical wall).
// noise_scale: world-units frequency of the patchy edge noise (bigger = larger patches).
// Returns 0..1 blend factor toward the snow texture set.
float snow_mask(vec3 world_normal, vec3 world_pos, float snow_cover, float slope_bias, float noise_scale) {
	float up = clamp(world_normal.y * 0.5 + 0.5, 0.0, 1.0); // 0 = straight down, 1 = straight up
	// How readily this surface catches snow at all: ~0 for walls (up=0.5, negative
	// bias), ~1 for flat ground/roofs. This must gate accumulation even at
	// snow_cover=1, or steep/vertical surfaces would still end up fully snowed.
	float eligibility = clamp(up + slope_bias, 0.0, 1.2);
	float coverage = snow_cover * eligibility;
	float n = fbm(world_pos.xz * noise_scale + world_pos.y * 0.05);
	// As coverage rises, the noise threshold drops so more of the noise field
	// "wins" — a patchy, non-uniform accumulate/melt edge instead of a hard ring.
	float threshold = mix(1.3, -0.3, coverage);
	float patch = smoothstep(threshold - 0.3, threshold + 0.3, n);
	return clamp(patch, 0.0, 1.0) * step(0.001, snow_cover);
}

// Blend albedo/roughness/normal toward a snow set using the mask. Kept as a plain
// function (not overloaded) so call sites stay explicit about what's blending.
void apply_snow(inout vec3 albedo, inout float roughness, inout vec3 normal_ts,
		vec3 snow_albedo, float snow_roughness, vec3 snow_normal_ts, float mask) {
	albedo = mix(albedo, snow_albedo, mask);
	roughness = mix(roughness, snow_roughness, mask);
	normal_ts = normalize(mix(normal_ts, snow_normal_ts, mask));
}
