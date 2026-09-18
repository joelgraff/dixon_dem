// wetness.gdshaderinc — shared "rain wetness" response: darkens porous albedo, lowers
// roughness, and (optionally) places puddles in flat low spots. Reusable by
// terrain/roads/vegetation so wet asphalt, wet dirt, wet grass all read consistently.

#include "res://materials/shaders/includes/noise.gdshaderinc"

// porosity: 0 = non-absorbent (metal, glass, ice — still darkens: a thin water film
//           darkens ANY surface via changed Fresnel balance, sealed asphalt/painted
//           wood included) .. 1 = very porous (dirt, unsealed concrete — darkens most).
void apply_wetness_darkening(inout vec3 albedo, inout float roughness, float wetness, float porosity) {
	albedo *= mix(1.0, mix(0.6, 0.42, porosity), wetness);
	roughness = mix(roughness, mix(roughness, 0.1, 0.85), wetness * (1.0 - 0.3 * porosity));
}

// Flat-surface puddle mask: only forms on near-upward faces, patchy via noise, grows
// with wetness. Call only for materials that plausibly pool water (roads, sidewalks,
// flat roofs) — skip for walls/grass/etc.
float puddle_mask(vec3 world_normal, vec3 world_pos, float wetness, float puddle_scale) {
	float flatness = smoothstep(0.9, 0.995, world_normal.y);
	// Two noise octaves at different frequencies so puddle edges read as an organic
	// blobby outline rather than one broad, almost-straight gradient boundary.
	float n = fbm(world_pos.xz * puddle_scale) * 0.7 + fbm(world_pos.xz * puddle_scale * 3.3 + 19.0) * 0.3;
	// Cap max coverage well short of 100%: even a drenched street is puddled in low
	// spots, not a single continuous mirror (which blows out to a flat glare under
	// an overcast sky-dome and reads as broken rather than wet).
	float threshold = mix(0.75, 0.40, wetness);
	return smoothstep(threshold - 0.12, threshold + 0.12, n) * flatness * smoothstep(0.05, 0.35, wetness);
}

// Applies the near-mirror puddle look on top of already-wet-darkened albedo/roughness.
void apply_puddle(inout vec3 albedo, inout float roughness, inout vec3 normal_ts, float mask) {
	roughness = mix(roughness, 0.05, mask);
	albedo = mix(albedo, albedo * 0.5, mask);
	normal_ts = normalize(mix(normal_ts, vec3(0.0, 0.0, 1.0), mask * 0.75));
}
