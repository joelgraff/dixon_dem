// tree_common.gdshaderinc — shared by foliage.gdshader, tree_bark.gdshader and
// tree_impostor.gdshader so the near tree mesh and its far impostor agree on
// the per-tree LOD fade, colour variation and season response. If they
// disagreed, the crossfade band would show a colour or timing jump.
//
// Per-tree LOD: MultiMesh chunks share one visibility_range, which Godot tests
// against the chunk's AABB centre, not each tree. So each tree fades itself
// by its own distance (instance origin = MODEL_MATRIX[3] in vertex()). The
// near layer uses lod_fade 0 -> 1 across [lod_near_end - lod_band,
// lod_near_end]; the impostor layer uses the same value and the same screen
// dither, inverted, so at any pixel exactly one of the two layers draws.
// veg_camera_pos is set every frame by vegetation.gd to the main camera, so
// shadow passes (whose CAMERA_POSITION_WORLD is the light) pick the same LOD
// as the visible pass.

uniform vec3 veg_camera_pos = vec3(0.0);
uniform float lod_near_end = 130.0;
uniform float lod_band = 25.0;

// 0 = full near detail, 1 = fully handed over to the impostor.
float veg_lod_fade(vec3 origin) {
	float d = distance(origin, veg_camera_pos);
	return smoothstep(lod_near_end - lod_band, lod_near_end, d);
}

// Interleaved gradient noise, shifted every frame so TAA averages the
// crossfade into a smooth blend instead of a fixed screen-door pattern.
float veg_dither(vec2 frag, float time) {
	frag += 5.588238 * floor(fract(time * 7.31) * 64.0);
	return fract(52.9829189 * fract(dot(frag, vec2(0.06711056, 0.00583715))));
}

float veg_hash(vec2 p) {
	p = fract(p * vec2(123.34, 456.21));
	p += dot(p, p + 45.32);
	return fract(p.x * p.y);
}

// Per-tree colour variation, keyed by the tree's world origin so the near
// mesh and the impostor of the same tree get the same tint.
vec3 veg_instance_tint(vec3 col, vec3 origin) {
	float h1 = veg_hash(origin.xz * 0.731 + 3.1);
	float h2 = veg_hash(origin.xz * 1.177 + 7.9);
	float value = mix(0.80, 1.16, h1);
	vec3 warm = col * vec3(1.10, 1.04, 0.80);
	vec3 cool = col * vec3(0.90, 1.00, 1.12);
	return mix(cool, warm, h2) * value;
}

// Per-tree autumn turn timing (some trees still green, some already turned).
float veg_tree_turn_jitter(vec3 origin) {
	return mix(-0.40, 0.14, veg_hash(origin.xz * 0.413 + 11.7));
}

// Piecewise 4-keyframe season blend: 0 summer, 0.25 spring, 0.75 autumn, 1 winter.
vec3 veg_season_color(vec3 summer, vec3 autumn, float t_col) {
	// Fresh yellow-green derived from the species' own summer colour (the
	// old fixed vec3(0.66, 0.78, 0.40) was ~4x brighter than any tuned
	// summer albedo and read as pastel).
	vec3 spring_col = summer * vec3(1.45, 1.35, 0.85) + vec3(0.02, 0.03, 0.0);
	if (t_col <= 0.25) {
		return mix(summer, spring_col, smoothstep(0.0, 0.25, t_col));
	} else if (t_col <= 0.75) {
		return mix(spring_col, autumn, smoothstep(0.25, 0.75, t_col));
	}
	return autumn;
}

// Canopy fullness from the real (unjittered) season so leaf-drop stays in step.
float veg_leaf_density(float t) {
	if (t <= 0.25) {
		return mix(1.0, 0.6, smoothstep(0.0, 0.25, t));
	} else if (t <= 0.75) {
		return mix(0.6, 1.0, smoothstep(0.25, 0.75, t));
	}
	return mix(1.0, 0.0, smoothstep(0.75, 1.0, t));
}

// Bare-twig haze weight: how strongly a leafless crown shows as a fine mass of
// twigs (what a bare tree looks like beyond ~20 m, where the real branch
// cylinders are sub-pixel).
float veg_twig_weight(float t) {
	return smoothstep(0.80, 1.0, t);
}

const vec3 VEG_TWIG_COLOR = vec3(0.085, 0.072, 0.060);
