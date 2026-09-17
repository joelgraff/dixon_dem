// noise.gdshaderinc — shared hash/value-noise/fbm helpers.
// Cheap, deterministic, no textures. Used by anti_tiling / snow / wetness includes
// and by surface.gdshader for macro color variation and grime masking.

float hash21(vec2 p) {
	p = fract(p * vec2(123.34, 456.21));
	p += dot(p, p + 45.32);
	return fract(p.x * p.y);
}

vec2 hash22(vec2 p) {
	float n = hash21(p);
	float n2 = hash21(p + vec2(17.13, 91.7));
	return vec2(n, n2);
}

// Value noise, smooth, range ~[0,1].
float value_noise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	float a = hash21(i);
	float b = hash21(i + vec2(1.0, 0.0));
	float c = hash21(i + vec2(0.0, 1.0));
	float d = hash21(i + vec2(1.0, 1.0));
	vec2 u = f * f * (3.0 - 2.0 * f);
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

// 3-octave fractal value noise, range ~[0,1].
float fbm(vec2 p) {
	float v = 0.0;
	float amp = 0.5;
	float freq = 1.0;
	for (int i = 0; i < 3; i++) {
		v += amp * value_noise(p * freq);
		freq *= 2.03;
		amp *= 0.5;
	}
	return v;
}

vec2 rotate2(vec2 v, float a) {
	float s = sin(a);
	float c = cos(a);
	return vec2(v.x * c - v.y * s, v.x * s + v.y * c);
}
