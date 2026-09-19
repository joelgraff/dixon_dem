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

	// clouds: intersect the view ray with a cloud shell at a fixed world
	// height (standard sky-dome technique). iter2's dir.xz/(up+0.25) divide
	// made cells shrink toward a point at the zenith (near-zenith dir.xz is
	// ~0 for every direction there, so the whole upper sky sampled almost
	// one noise value — "one continuous cloud mass"). t = height/up keeps
	// world-space cell size constant and cells get *smaller* toward the
	// horizon, which is the correct perspective.
	float cloud_alpha = 0.0;
	vec3 cloud_col = cloud_light_color;
	if (up > -0.05) {
		float t = 1500.0 / max(up, 0.06);
		vec2 cuv = dir.xz * t * 0.0016 + wind_dir * cloud_time * 0.02;
		float density = fbm(cuv);
		// fbm's value-noise octaves sum to a mean around ~0.48 with limited
		// spread, so a threshold near that mean (iter2's edge0 = 0.5-cov*0.5)
		// let most of the sky exceed it once the old hard floor() quantizer
		// (which incidentally snapped low-density fringes to 0) was removed
		// for the posterization fix — the whole sky read as one cloud mass.
		// Anchoring near the noise's bright tail instead makes `cloud_coverage`
		// track the actual visible fraction.
		float edge0 = 1.0 - cloud_coverage;
		density = smoothstep(edge0 - 0.06, edge0 + 0.14, density);
		float sun_up = clamp(sun_dir.y, 0.0, 1.0);
		cloud_col = mix(cloud_shadow_color, cloud_light_color, 0.35 + 0.65 * sun_up);
		cloud_col = mix(cloud_col, cloud_col * 0.55, cloud_darkness);
		// Lit relative to the sky's OWN radiance, not a hardcoded floor —
		// iter2 clouds sat at ~0.27 minimum brightness against a ~0.02 night
		// sky (>10x too bright, "clouds glow at night"). Under a full moon
		// clouds should be a silvery grey modestly brighter than the sky
		// (~1.3x), not a near-white disc.
		vec3 sky_here = mix(horizon_color, zenith_color, sky_t);
		float sky_lum = dot(sky_here, vec3(0.2126, 0.7152, 0.0722));
		// A thick deck should hide the moon, not relay it: moon_energy here is
		// computed independent of weather, so a 95%-coverage OVERCAST night
		// was getting its clouds lit almost as brightly as a CLEAR night's
		// (measured: overcast night sky 82.6 vs clear night 49.4 — backwards).
		float moon_through_cloud = moon_energy * 0.35 * (1.0 - cloud_coverage * 0.95);
		float night_light = clamp(max(sun_up, moon_through_cloud), sky_lum * 0.9, 1.0);
		cloud_col *= night_light;
		// faint warm town light-pollution glow on the underside of the deck
		cloud_col += vec3(0.05, 0.035, 0.02) * cloud_coverage * (1.0 - sun_up) * star_visibility * 0.6;
		float fade = smoothstep(-0.05, 0.15, up);
		cloud_alpha = clamp(density, 0.0, 1.0) * fade;
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
