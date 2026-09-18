shader_type sky;
// Dixon — stylized procedural sky (custom, no external textures).
// Owned by the atmosphere workstream. All tunable state is fed in from
// atmosphere.gd every frame (colors already blended for day/twilight/night
// and season/weather there) so this shader stays cheap and simple.
//
// iter2: azimuth-dependent twilight glow (Belt of Venus), curved-dome cloud
// projection (iter1's flat-plane projection streaked at the horizon), a
// density remap so low coverage actually shows cumulus, night-lit clouds,
// finer/dimmer stars, and dither to kill 8-bit sky banding.

uniform vec3 zenith_color : source_color = vec3(0.1, 0.22, 0.48);
uniform vec3 horizon_color : source_color = vec3(0.65, 0.75, 0.85);
uniform vec3 ground_color : source_color = vec3(0.15, 0.15, 0.16);

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
// Sunrise/sunset colour, applied only in a band around the sun's own azimuth
// (see warm_amount below) — NOT blended into the azimuth-neutral horizon_color.
uniform vec3 horizon_twilight_color : source_color = vec3(0.95, 0.5, 0.3);
// 0..1, peaks right at the horizon (sunrise/sunset), 0 well above/below it.
uniform float twilight_strength : hint_range(0.0, 1.0) = 0.0;

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

	// --- azimuth-dependent twilight: warm glow on the sun's side of the sky,
	// a cool "Belt of Venus" pink band on the anti-sun side, both only near
	// the horizon and only around sunrise/sunset (twilight_strength).
	vec2 dir_xz = length(dir.xz) > 0.0001 ? normalize(dir.xz) : vec2(1.0, 0.0);
	vec2 sun_xz = length(sun_dir.xz) > 0.0001 ? normalize(sun_dir.xz) : vec2(1.0, 0.0);
	float sun_side = dot(dir_xz, sun_xz) * 0.5 + 0.5; // 1 = facing sun, 0 = facing away
	float near_horizon = 1.0 - smoothstep(0.0, 0.35, abs(up));
	float warm_amount = pow(sun_side, 2.2) * near_horizon * twilight_strength;
	col = mix(col, horizon_twilight_color, clamp(warm_amount, 0.0, 0.9));
	float belt = smoothstep(0.01, 0.07, up) * (1.0 - smoothstep(0.1, 0.22, up)) * (1.0 - sun_side);
	col = mix(col, vec3(0.72, 0.56, 0.62), belt * twilight_strength * 0.55);

	// stars: finer cells, brightness from a steep hash power, faded near the
	// horizon (light-pollution style), thinned out under cloud cover.
	if (up > 0.02) {
		vec3 sp = floor(dir * 680.0);
		float sh = hash13(sp);
		float bright = pow(sh, 40.0);
		float star = step(0.9992, sh) * bright * 60.0;
		star *= smoothstep(0.05, 0.5, up);
		col += vec3(0.85, 0.9, 1.0) * star * star_visibility * (1.0 - cloud_coverage * 0.85);
	}

	// clouds: project onto a curved dome (iter1's flat dir.xz/up projection
	// went singular at the horizon and streaked radially — dividing by
	// (up + 0.25) instead keeps it well-behaved all the way down).
	float cloud_alpha = 0.0;
	vec3 cloud_col = cloud_light_color;
	if (up > -0.05) {
		float up_c = max(up, -0.05);
		vec2 cuv = dir.xz / (up_c + 0.25) * 0.35 + wind_dir * cloud_time * 0.015;
		float density = fbm(cuv * 1.6);
		float edge0 = 0.5 - cloud_coverage * 0.5;
		density = smoothstep(edge0, edge0 + 0.25, density);
		density = floor(density * 5.0) / 5.0; // posterize into soft painted steps
		float sun_up = clamp(sun_dir.y, 0.0, 1.0);
		float night_light = max(sun_up, moon_energy * 0.6 + 0.03);
		cloud_col = mix(cloud_shadow_color, cloud_light_color, 0.35 + 0.65 * sun_up);
		cloud_col = mix(cloud_col, cloud_col * 0.55, cloud_darkness);
		cloud_col *= night_light;
		// faint warm town light-pollution glow on the underside of the deck
		cloud_col += vec3(0.05, 0.035, 0.02) * cloud_coverage * (1.0 - sun_up) * star_visibility;
		float fade = smoothstep(-0.05, 0.15, up);
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

	// dither to break up 8-bit banding across the smooth gradient
	col += (hash21(SCREEN_UV * 1024.0) - 0.5) / 255.0;

	COLOR = col;
}
