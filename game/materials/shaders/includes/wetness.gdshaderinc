// wetness.gdshaderinc — shared "rain wetness" response: darkens porous albedo, lowers
// roughness, and (optionally) places puddles in flat low spots. Reusable by
// terrain/roads/vegetation so wet asphalt, wet dirt, wet grass all read consistently.

#include "res://materials/shaders/includes/noise.gdshaderinc"

// porosity: 0 = non-absorbent (metal, glass, ice — still darkens: a thin water film
//           darkens ANY surface via changed Fresnel balance, sealed asphalt/painted
//           wood included) .. 1 = very porous (dirt, unsealed concrete — darkens most).
void apply_wetness_darkening(inout vec3 albedo, inout float roughness, float wetness, float porosity) {
	// iter3 measured only ~12% darkening on asphalt (porosity 0.15) at full wetness —
	// too weak (real wet asphalt darkens 35-50%). Steeper curve: asphalt now lands at
	// mix(0.35,0.15,0.15) = 0.32 (a 68% reduction) at wetness=1.
	albedo *= mix(1.0, mix(0.35, 0.15, porosity), wetness);
	// Only a MILD, proportional roughness drop away from puddles. Pulling roughness all
	// the way to ~0.1 across the whole surface turns it into a broad soft mirror that
	// picks up as much ambient/sky light as the albedo lost — in a full-frame average
	// the two cancel out and the "wet" look measures as no darkening at all (iter2's
	// bug). The strong near-mirror sheen belongs in apply_puddle() only, gated by the
	// puddle mask, not spread over the whole wet surface.
	roughness = mix(roughness, roughness * 0.7, wetness);
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
	// Tighter band (was ±0.12): a bimodal wet/dry split reads as actual puddles: iter3's
	// wet/dry ratio image measured a flat 0.89 with std 0.039 (no readable shape) —
	// too broad a transition band blurs the mask into a near-uniform haze instead of
	// discrete puddle outlines. mix(0.85,0.45,wetness) puts ~30-40% of a flat road
	// under the mask at wetness=1, given noise centered ~0.5.
	float threshold = mix(0.85, 0.45, wetness);
	return smoothstep(threshold - 0.06, threshold + 0.06, n) * flatness * smoothstep(0.05, 0.35, wetness);
}

// Applies the near-mirror puddle look on top of already-wet-darkened albedo/roughness.
// spec_out receives a Fresnel-friendly SPECULAR boost the caller should assign to the
// material's SPECULAR output — Godot's grazing-angle Fresnel term scales with this, and
// iter3's grazing shot showed a pale haze rather than a real reflection because
// SPECULAR was left at its ~0.5 default even inside puddles.
void apply_puddle(inout vec3 albedo, inout float roughness, inout vec3 normal_ts, float mask, out float spec_out) {
	roughness = mix(roughness, 0.035, mask);
	albedo = mix(albedo, albedo * 0.5, mask);
	normal_ts = normalize(mix(normal_ts, vec3(0.0, 0.0, 1.0), mask * 0.75));
	spec_out = mix(0.5, 1.0, mask);
}
