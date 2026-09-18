// building_far.gdshader — HLOD "box" material for distant building chunks.
// One flat-shaded, texture-free material for a whole chunk's worth of far
// buildings merged into a single mesh/draw call: per-building color rides on
// vertex COLOR (baked as an approximate average of that building's real
// materials in pipeline/buildings), with a cheap snow cap on upward faces and
// a coarse night-window glow hint so the far LOD doesn't go flat black at
// night. See docs/buildings_notes.md.

shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

global uniform float snow_cover;
global uniform float wetness;
global uniform float night_factor;

varying vec3 v_world_normal;

void vertex() {
	v_world_normal = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

void fragment() {
	vec3 base = COLOR.rgb;
	float snow_mask = clamp(v_world_normal.y * 1.3 - 0.25, 0.0, 1.0) * snow_cover;
	base = mix(base, vec3(0.85, 0.87, 0.9), snow_mask);
	base = mix(base, base * 0.75, wetness * (1.0 - snow_mask) * 0.5);

	// COLOR.a carries a baked "window glow amount" (0..~0.5) for this face;
	// blend a faint warm tint at night so far silhouettes aren't dead.
	vec3 warm = vec3(1.0, 0.7, 0.4);
	ALBEDO = mix(base, warm, COLOR.a * night_factor * 0.5);
	EMISSION = warm * COLOR.a * night_factor * 0.8;
	ROUGHNESS = 0.85;
	METALLIC = 0.0;
}
