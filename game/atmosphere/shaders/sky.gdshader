shader_type sky;
// Dixon — stylized procedural sky (custom, no external textures).
// Owned by the atmosphere workstream. All tunable state is fed in from
// atmosphere.gd every frame (colors already blended for day/twilight/night
// and season/weather there) so this shader stays cheap and simple.

uniform vec3 zenith_color : source_color = vec3(0.25, 0.45, 0.75);
uniform vec3 horizon_color : source_color = vec3(0.65, 0.75, 0.85);
uniform vec3 ground_color : source_color = vec3(0.05, 0.05, 0.06);

uniform vec3 sun_dir = vec3(0.0, 1.0, 0.0);
uniform vec3 sun_color : source_color = vec3(1.0, 0.95, 0.85);
uniform float sun_energy = 1.0;

uniform vec3 moon_dir = vec3(0.0, -1.0, 0.0);
uniform vec3 moon_color : source_color = vec3(0.65, 0.72, 0.85);
uniform float moon_energy = 0.0;

uniform float cloud_coverage : hint_range(0.0, 1.0) = 0.3;
uniform float cloud_darkness : hint_range(0.0, 1.0) = 0.1;
uniform vec3 cloud_light_color : source_color = vec3(1.0, 1.0, 1.0);
uniform vec3 cloud_shadow_color : source_color = vec3(0.35, 0.37, 0.42);
uniform float cloud_time = 0.0;
uniform vec2 wind_dir = vec2(1.0, 0.3);

uniform float star_visibility : hint_range(0.0, 1.0) = 0.0;
uniform float horizon_haze : hint_range(0.0, 1.0) = 0.3;

// ---- hash / noise helpers -------------------------------------------------
float hash13(vec3 p) {
	p = fract(p * 0.3183099 + 0.1);
	p *= 17.0;
	return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float hash21(vec2 p) {
	vec3 p3 = fract(vec3(p.xyx) * 0.1031);
	p3 += dot(p3, p3.yzx + 33.33);
	return fract((p3.x + p3.y) * p3.z);
}

float noise2(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	float a = hash21(i);
	float b = hash21(i + vec2(1.0, 0.0));
	float c = hash21(i + vec2(0.0, 1.0));
	float d = hash21(i + vec2(1.0, 1.0));
	vec2 u = f * f * (3.0 - 2.0 * f);
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float fbm(vec2 p) {
	float v = 0.0;
	float amp = 0.5;
	for (int i = 0; i < 5; i++) {
		v += amp * noise2(p);
		p = p * 2.02 + 17.0;
		amp *= 0.5;
	}
	return v;
}

void sky() {
	vec3 dir = EYEDIR;
	float up = dir.y;

	// base gradient: ground / horizon / zenith
	float sky_t = pow(clamp(up, 0.0, 1.0), 0.45);
	vec3 col = mix(horizon_color, zenith_color, sky_t);
	float ground_t = pow(clamp(-up, 0.0, 1.0), 0.6);
	col = mix(col, ground_color, ground_t);

	// horizon haze (aerial-perspective-ish softening near the skyline)
	float haze_t = 1.0 - clamp(abs(up) * 4.0, 0.0, 1.0);
	col = mix(col, horizon_color, haze_t * horizon_haze * 0.6);

	// stars (only well above horizon, faded by cloud cover and horizon haze)
	if (up > 0.02) {
		vec3 sp = floor(dir * 340.0);
		float sh = hash13(sp);
		float star = step(0.9975, sh) * smoothstep(0.02, 0.25, up);
		col += vec3(0.9, 0.93, 1.0) * star * star_visibility * (1.0 - cloud_coverage * 0.8);
	}

	// clouds: project the view ray onto a plane above the camera
	float cloud_alpha = 0.0;
	vec3 cloud_col = cloud_light_color;
	if (up > 0.015) {
		vec2 cuv = dir.xz / up * 0.35 + wind_dir * cloud_time * 0.015;
		float density = fbm(cuv * 1.6);
		density = smoothstep(1.0 - cloud_coverage, 1.0, density);
		float sun_up = clamp(sun_dir.y, 0.0, 1.0);
		cloud_col = mix(cloud_shadow_color, cloud_light_color, 0.35 + 0.65 * sun_up);
		cloud_col = mix(cloud_col, cloud_col * 0.55, cloud_darkness);
		float fade = smoothstep(0.0, 0.12, up);
		cloud_alpha = density * fade;
	}
	col = mix(col, cloud_col, clamp(cloud_alpha, 0.0, 1.0));

	// sun disc + glow
	float sun_dot = dot(dir, normalize(sun_dir));
	float sun_disc = smoothstep(0.9994, 0.9998, sun_dot);
	float sun_glow = pow(clamp(sun_dot, 0.0, 1.0), 340.0);
	float sun_haze = pow(clamp(sun_dot, 0.0, 1.0), 6.0) * 0.15;
	col += sun_color * sun_energy * (sun_disc * 3.0 + sun_glow * 6.0 + sun_haze) * (1.0 - cloud_alpha * 0.85);

	// moon disc + glow
	float moon_dot = dot(dir, normalize(moon_dir));
	float moon_disc = smoothstep(0.9990, 0.9997, moon_dot);
	float moon_glow = pow(clamp(moon_dot, 0.0, 1.0), 500.0);
	col += moon_color * moon_energy * (moon_disc * 2.0 + moon_glow * 4.0) * (1.0 - cloud_alpha * 0.9);

	COLOR = col;
}
