// shingles.gdshader — procedural 3-tab asphalt shingle (no CC0 photo texture of this
// found on Poly Haven or ambientCG — their "roofing tiles" are all clay/slate, wrong
// for a Midwest house; see docs/materials_notes.md). Real courses: ~0.33 m tab width,
// ~0.14 m weather exposure per course, with a half-tab stagger every other course
// (standard roofing practice) so tab-cutout joints don't line up vertically.
//
// Mesh UV is the intended input: **UV.y must increase down-slope, UV.x across the
// roof** (standard for any procedurally-unwrapped roof plane). `face_size_m` converts
// this instance's 0..1 UV range to real meters — set it to the roof face's actual
// width/height. A world-projected fallback is provided for quick testing without a
// proper UV unwrap, but it only looks right on a roof whose slope direction lines up
// with world Z (rotate the mesh, not the UV, to fix orientation).

shader_type spatial;
render_mode world_vertex_coords, diffuse_burley, specular_schlick_ggx;

#include "res://materials/shaders/includes/noise.gdshaderinc"
#include "res://materials/shaders/includes/snow.gdshaderinc"
#include "res://materials/shaders/includes/wetness.gdshaderinc"

global uniform float snow_cover;
global uniform float wetness;

group_uniforms ShingleColor;
uniform vec4 shingle_color_dark : source_color = vec4(0.085, 0.078, 0.072, 1.0);
uniform vec4 shingle_color_light : source_color = vec4(0.135, 0.122, 0.110, 1.0);
uniform float roughness_base : hint_range(0.4, 1.0) = 0.88;

group_uniforms Courses;
uniform float course_exposure_m : hint_range(0.05, 0.3) = 0.14;
uniform float tab_width_m : hint_range(0.15, 0.6) = 0.33;
uniform bool use_world_uv = false;
uniform vec2 face_size_m = vec2(4.0, 3.0); // this instance's UV(0..1) range in meters
// Which mesh-UV axis runs down-slope. iter2 shipped with this assumed to be UV.y and
// the critic found courses running down the slope instead of across it — i.e. the
// mesh's actual down-slope axis was UV.x, not UV.y. Rather than guess again, this is
// an explicit toggle: true = UV.y is down-slope (courses = bands of constant UV.y),
// false = UV.x is down-slope (courses = bands of constant UV.x).
uniform bool v_is_downslope = false;
// world_uv mode's down-slope distance is computed exactly (no mesh-UV guessing) as the
// distance from this panel's ridge line: for ANY point on a flat tilted plane, the
// straight-line distance in the plane containing the pitch direction (world XY here,
// since the ridge runs along world Z in this project's gable convention) IS the true
// surface distance down the slope — robust regardless of how the mesh's own UV0 is
// laid out. iter3 twice mis-guessed the UV convention (courses came out ~0.5m instead
// of 0.14m); this sidesteps that class of bug entirely for the common case.
uniform vec2 ridge_xy = vec2(0.0, 1.55); // world (X,Y) of the ridge line this instance meets

group_uniforms Fascia;
// Anything close to a near-vertical edge/rake/end-cap face of the same mesh (not the
// up-facing roof slope) renders as a plain dark fascia board instead of the shingle
// pattern, since the course/tab coordinate doesn't mean anything there. iter3 used
// wn.y<0.3 without abs(), which also caught legitimate shallow-but-still-slope angles
// and made close eave shots render as a featureless fascia block — tightened to only
// trigger on genuinely near-vertical faces.
uniform vec4 fascia_color : source_color = vec4(0.10, 0.09, 0.085, 1.0);
uniform float fascia_roughness : hint_range(0.3, 1.0) = 0.7;

group_uniforms SnowSet;
uniform sampler2D snow_albedo_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_normal_tex : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_roughness_tex : filter_linear_mipmap, repeat_enable;
uniform float snow_albedo_multiplier : hint_range(0.5, 3.0) = 1.75;
uniform float snow_slope_bias : hint_range(-1.0, 1.0) = -0.15;
uniform float snow_noise_scale : hint_range(0.02, 1.0) = 0.15;

group_uniforms WetResponse;
uniform float porosity : hint_range(0.0, 1.0) = 0.2;

varying vec3 v_world_pos;
varying vec3 v_world_normal;

void vertex() {
	v_world_pos = VERTEX;
	v_world_normal = NORMAL;
}

void fragment() {
	vec3 wn = normalize(v_world_normal);
	vec2 uv_m;
	float v_down;
	float u_across;
	if (use_world_uv) {
		v_down = length(v_world_pos.xy - ridge_xy); // exact surface distance from the ridge
		u_across = v_world_pos.z;
		uv_m = vec2(u_across, v_down);
	} else {
		uv_m = UV * face_size_m;
		v_down = v_is_downslope ? uv_m.y : uv_m.x;
		u_across = v_is_downslope ? uv_m.x : uv_m.y;
	}

	float course_row = floor(v_down / course_exposure_m);
	float v_local = fract(v_down / course_exposure_m);
	// Half-tab stagger every other course so tab joints don't line up vertically.
	float stagger = mod(course_row, 2.0) * (tab_width_m * 0.5);
	float u_shifted = u_across + stagger;
	float tab_col = floor(u_shifted / tab_width_m);
	float u_local = fract(u_shifted / tab_width_m);

	float tab_hash = hash21(vec2(tab_col, course_row) + 3.0);
	float tone = mix(0.72, 1.28, tab_hash);

	// Lower frequency than iter2 (was 55.0): that aliased badly at grazing roof-slope
	// viewing angles (long streaky artifacts easy to mistake for wrong course
	// orientation). 22 still reads as fine granule speckle at the 2-8m ranges this
	// material is meant for.
	float granule = fbm(uv_m * 22.0);
	float granule_tone = mix(0.82, 1.18, granule);

	vec3 albedo = mix(shingle_color_dark.rgb, shingle_color_light.rgb, clamp(granule * 0.6 + 0.2, 0.0, 1.0));
	albedo *= tone * granule_tone;

	// Shadow line under each course's exposed edge (the cutout reveal).
	float course_shadow = smoothstep(0.0, 0.12, v_local);
	albedo *= mix(0.50, 1.0, course_shadow);
	// Tab-to-tab gap lines (vertical joints between tabs).
	float tab_gap = smoothstep(0.0, 0.08, u_local) * smoothstep(0.0, 0.08, 1.0 - u_local);
	albedo *= mix(0.68, 1.0, tab_gap);

	float bump_v = (course_shadow - 0.5) * 0.7;
	float bump_u = (tab_gap - 0.5) * 0.35 + (granule - 0.5) * 0.15;
	vec3 normal_ts = normalize(vec3(bump_u, -bump_v, 1.0));

	float rough = clamp(roughness_base + (granule - 0.5) * 0.15, 0.5, 1.0);
	float ao = clamp(mix(0.75, 1.0, tab_gap) * mix(0.8, 1.0, course_shadow), 0.0, 1.0);

	float smask = snow_mask(wn, v_world_pos, snow_cover, snow_slope_bias, snow_noise_scale);
	if (smask > 0.0) {
		vec2 suv = uv_m * 0.6;
		vec3 s_alb = texture(snow_albedo_tex, suv).rgb;
		float s_rough = texture(snow_roughness_tex, suv).r;
		vec3 s_norm = texture(snow_normal_tex, suv).rgb * 2.0 - 1.0;
		apply_snow(albedo, rough, normal_ts, s_alb, s_rough, s_norm, smask, snow_albedo_multiplier);
		ao = mix(ao, 1.0, smask * 0.5);
	}

	float wet_eff = wetness * (1.0 - smask * 0.9);
	if (wet_eff > 0.0) {
		apply_wetness_darkening(albedo, rough, wet_eff, porosity);
	}

	// Edge/rake/gable-end faces of the same mesh aren't the up-facing roof slope —
	// the procedural course/tab UV doesn't mean anything there, so give them a plain
	// fascia board instead (was rendering stretched tab cutouts in iter2).
	if (abs(wn.y) < 0.15) {
		albedo = fascia_color.rgb;
		rough = fascia_roughness;
		normal_ts = vec3(0.0, 0.0, 1.0);
		ao = 1.0;
	}

	ALBEDO = albedo;
	ROUGHNESS = rough;
	METALLIC = 0.0;
	AO = ao;
	AO_LIGHT_AFFECT = 0.6;
	NORMAL_MAP = normal_ts * 0.5 + 0.5;
	NORMAL_MAP_DEPTH = 1.0;
}
