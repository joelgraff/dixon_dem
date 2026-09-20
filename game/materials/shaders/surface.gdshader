// surface.gdshader — Dixon shared PBR surface shader.
// Used by most world materials (terrain/roads/buildings/landmarks/props) via ready-made
// ShaderMaterial .tres files in game/materials/lib/. See docs/materials_notes.md.
//
// Features: tintable albedo, world-space or mesh-UV mapping with optional triplanar,
// cheap per-tile anti-tiling (random rotate+offset) + macro color variation, ground-
// proximity grime, optional vertex-painted edge wear, and weather response driven by
// the global uniforms snow_cover / wetness (declared in project.godot, set by
// autoload/world_state.gd): snow accumulates on upward faces with a noisy edge and
// blends to a separate snow texture set; wetness darkens porous albedo, lowers
// roughness, and (opt-in) forms near-mirror puddles on flat surfaces.
//
// terrain/roads/vegetation should reuse materials/shaders/includes/*.gdshaderinc
// directly rather than duplicating this logic.

shader_type spatial;
render_mode world_vertex_coords, diffuse_burley, specular_schlick_ggx;

#include "res://materials/shaders/includes/noise.gdshaderinc"
#include "res://materials/shaders/includes/anti_tiling.gdshaderinc"
#include "res://materials/shaders/includes/snow.gdshaderinc"
#include "res://materials/shaders/includes/wetness.gdshaderinc"

// ---- World conditions (declared globally in project.godot, driven by WorldState) ----
global uniform float snow_cover;
global uniform float wetness;

group_uniforms TextureSet;
uniform sampler2D albedo_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D roughness_tex : filter_linear_mipmap, repeat_enable;
uniform sampler2D ao_tex : filter_linear_mipmap, repeat_enable;

group_uniforms SnowSet;
uniform sampler2D snow_albedo_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_normal_tex : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_roughness_tex : filter_linear_mipmap, repeat_enable;
// The raw snow texture sample gets this multiply (clamped to 0.9) before blending in —
// see apply_snow() in snow.gdshaderinc. Default matches snow_fresh.tres's own
// albedo_multiplier so snow always reads as bright regardless of which material it's
// layered onto.
uniform float snow_albedo_multiplier : hint_range(0.5, 3.0) = 1.75;

group_uniforms TintAndMacro;
uniform vec4 albedo_tint : source_color = vec4(1.0, 1.0, 1.0, 1.0);
uniform float albedo_multiplier : hint_range(0.0, 3.0) = 1.0;
uniform float roughness_multiplier : hint_range(0.0, 3.0) = 1.0;
uniform float roughness_bias : hint_range(-1.0, 1.0) = 0.0;
uniform float metallic : hint_range(0.0, 1.0) = 0.0;
uniform float normal_strength : hint_range(0.0, 2.0) = 1.0; // scales normal-map bump intensity (e.g. flatten strong wood grain to read as painted, not bare wood)
uniform float macro_variation_strength : hint_range(0.0, 0.8) = 0.12;
uniform float macro_variation_scale : hint_range(0.005, 1.0) = 0.08;

group_uniforms Mapping;
uniform vec2 uv_scale = vec2(1.0, 1.0); // tiles per meter (= 1 / meters-per-tile)
uniform bool use_world_uv = true; // false = use mesh UV0 (for hand-unwrapped props/buildings)
uniform bool triplanar = false; // also auto-enables when use_world_uv and this surface point isn't near-horizontal (see fragment())
uniform bool anti_tiling_enabled = true;
uniform bool anti_tiling_rotation = true; // false = directional grain (brick, siding, shingles, corrugated metal): no rotation/offset, repeat is hidden by module_variation instead

group_uniforms ModuleDetail;
// For directional/coursed materials only (anti_tiling_rotation=false): hides the
// obvious repeat with per-brick-ish color variation instead of rotating/offsetting
// (which breaks coursing — see anti_tiling.gdshaderinc). separate_mortar additionally
// keeps mortar/grout a fixed neutral color instead of getting tinted along with the
// brick (a straight albedo_tint multiply colors the WHOLE photo, mortar included,
// which reads as one molded plastic slab).
uniform bool separate_mortar = false;
uniform vec4 mortar_color : source_color = vec4(0.72, 0.68, 0.62, 1.0);
uniform float mortar_saturation_threshold : hint_range(0.0, 1.0) = 0.22;
uniform vec2 module_uv_scale = vec2(5.0, 15.0); // modules-across, modules-tall per 1x1 UV tile
uniform float module_variation_amount : hint_range(0.0, 0.8) = 0.12;

group_uniforms GrimeAndWear;
uniform float ground_level = 0.0; // world-space Y of local ground for this instance
uniform float grime_height : hint_range(0.0, 5.0) = 1.2; // meters above ground_level grime fades out
uniform float grime_strength : hint_range(0.0, 1.0) = 0.3;
uniform float edge_wear_amount : hint_range(0.0, 1.0) = 0.0; // needs vertex-painted COLOR.r mask

group_uniforms SnowResponse;
uniform float snow_slope_bias : hint_range(-1.0, 1.0) = 0.0; // + accumulates easier, - resists (walls)
uniform float snow_noise_scale : hint_range(0.02, 1.0) = 0.15;

group_uniforms WetResponse;
uniform float porosity : hint_range(0.0, 1.0) = 0.4;
uniform bool allow_puddles = false;
uniform float puddle_scale : hint_range(0.01, 1.0) = 0.06;

varying vec3 v_world_pos;
varying vec3 v_world_normal;
varying vec3 v_world_tangent;
varying vec3 v_world_binormal;

void vertex() {
	// world_vertex_coords render mode puts VERTEX/NORMAL/TANGENT/BINORMAL in world
	// space already.
	v_world_pos = VERTEX;
	v_world_normal = NORMAL;
	v_world_tangent = TANGENT;
	v_world_binormal = BINORMAL;
}

struct SurfaceSample {
	vec3 albedo;
	vec3 normal_ts;
	float rough;
	float ao;
};

SurfaceSample sample_at(vec2 uv, float rot_id) {
	SurfaceSample s;
	vec3 n = texture(normal_tex, uv).rgb * 2.0 - 1.0;
	s.normal_ts = rotate_tiled_normal(n, rot_id);
	s.albedo = texture(albedo_tex, uv).rgb;
	s.rough = texture(roughness_tex, uv).r;
	s.ao = texture(ao_tex, uv).r;
	return s;
}

// Non-directional materials get a real 2-grid stochastic blend (no seams). Directional
// materials (anti_tiling_rotation=false) get a single plain-UV sample — their repeat is
// hidden by module_variation in fragment(), not by transforming the UV.
SurfaceSample sample_material(vec2 uv) {
	if (!anti_tiling_enabled) {
		return sample_at(uv, 0.0);
	}
	vec2 uv_a, uv_b;
	float rot_a, rot_b, w;
	anti_tile_blend(uv, anti_tiling_rotation, uv_a, uv_b, rot_a, rot_b, w);
	if (!anti_tiling_rotation) {
		return sample_at(uv_a, rot_a);
	}
	SurfaceSample sa = sample_at(uv_a, rot_a);
	SurfaceSample sb = sample_at(uv_b, rot_b);
	SurfaceSample s;
	s.albedo = mix(sa.albedo, sb.albedo, w);
	s.normal_ts = normalize(mix(sa.normal_ts, sb.normal_ts, w));
	s.rough = mix(sa.rough, sb.rough, w);
	s.ao = mix(sa.ao, sb.ao, w);
	return s;
}

void fragment() {
	vec3 wn = normalize(v_world_normal);
	SurfaceSample surf;

	// Auto-triplanar: a pure top-down world_pos.xz projection is only correct on
	// near-horizontal faces. Any world-planar material used on a vertical or steeply
	// sloped face (curb faces, roof edges/parapets, slab sides) would otherwise smear
	// the texture along the "flat" axis — so fall back to triplanar automatically
	// whenever the surface isn't close to flat, in addition to the explicit toggle.
	bool use_triplanar = triplanar || (use_world_uv && abs(wn.y) < 0.7);
	vec3 bw = vec3(0.0);
	vec2 base_uv;
	// Continuous phase for module_variation, independent of which triplanar plane
	// dominates. iter3 derived this from whichever plane had the highest blend weight,
	// which FLIPS discontinuously right where two weights cross over (e.g. a box
	// corner) — that jump is exactly the vertical seam the iter3 critique measured
	// down the middle of every siding pier. World position has no such discontinuity.
	// On vertical faces the phase must run ALONG the wall and UP it. The old world-xz-only phase is
	// constant with height, so every brick/board column got one colour top to bottom = the vertical
	// "barcode" stripes visible on every facade (user screenshots, 2026-09-20).
	vec2 module_phase;
	if (abs(wn.y) < 0.7) {
		vec2 wall_dir = normalize(vec2(-wn.z, wn.x) + vec2(1e-5, 0.0));
		module_phase = vec2(dot(v_world_pos.xz, wall_dir), v_world_pos.y) * uv_scale * module_uv_scale;
	} else {
		module_phase = v_world_pos.xz * uv_scale * module_uv_scale;
	}

	if (use_triplanar) {
		// Sharper falloff (was 4.0): narrows the blend zone around edges/corners.
		bw = pow(abs(wn), vec3(8.0));
		bw /= max(bw.x + bw.y + bw.z, 0.0001);
		SurfaceSample sx = sample_material(v_world_pos.zy * uv_scale);
		SurfaceSample sy = sample_material(v_world_pos.xz * uv_scale);
		SurfaceSample sz = sample_material(v_world_pos.xy * uv_scale);
		surf.albedo = sx.albedo * bw.x + sy.albedo * bw.y + sz.albedo * bw.z;
		surf.rough = sx.rough * bw.x + sy.rough * bw.y + sz.rough * bw.z;
		surf.ao = sx.ao * bw.x + sy.ao * bw.y + sz.ao * bw.z;

		// Whiteout blend (Golus): reorient each plane's tangent-space normal into
		// world space before blending, instead of averaging raw tangent-space
		// vectors from three different projections (which is only valid if all three
		// happened to share a tangent frame, which they don't).
		vec3 axis_sign = sign(wn);
		vec3 nx = vec3(sx.normal_ts.xy + wn.zy, sx.normal_ts.z * axis_sign.x);
		vec3 ny = vec3(sy.normal_ts.xy + wn.xz, sy.normal_ts.z * axis_sign.y);
		vec3 nz = vec3(sz.normal_ts.xy + wn.xy, sz.normal_ts.z * axis_sign.z);
		vec3 world_n = normalize(nx.zyx * bw.x + ny.xzy * bw.y + nz.xyz * bw.z);
		// Re-express back in this fragment's own tangent frame so the rest of the
		// pipeline (grime/snow/wet, and Godot's NORMAL_MAP->lighting decode) can stay
		// uniformly tangent-space regardless of which path ran.
		vec3 T = normalize(v_world_tangent);
		vec3 B = normalize(v_world_binormal);
		surf.normal_ts = normalize(vec3(dot(world_n, T), dot(world_n, B), dot(world_n, wn)));
	} else {
		base_uv = use_world_uv ? (v_world_pos.xz * uv_scale) : (UV * uv_scale);
		surf = sample_material(base_uv);
	}

	vec3 albedo;
	if (separate_mortar) {
		// Mortar reads as much lower saturation than fired brick/clay in nearly every
		// CC0 brick photo — use that to mask it out so tint/module_variation only ever
		// touches actual brick pixels, keeping mortar a fixed neutral color instead of
		// inheriting the brick's hue (iter2's "one molded plastic slab" defect).
		float mx = max(max(surf.albedo.r, surf.albedo.g), surf.albedo.b);
		float mn = min(min(surf.albedo.r, surf.albedo.g), surf.albedo.b);
		float sat = mx > 0.0001 ? (mx - mn) / mx : 0.0;
		float mortar_mask = 1.0 - smoothstep(mortar_saturation_threshold * 0.75, mortar_saturation_threshold * 1.25, sat);
		vec3 brick_col = surf.albedo * albedo_tint.rgb * albedo_multiplier;
		brick_col *= module_variation(module_phase, module_variation_amount);
		// Per-joint mortar tone variation (±~8%) — a flat mortar_color everywhere reads
		// as freshly re-pointed brick rather than an aged 1880s-1920s block.
		float mortar_tone = mix(0.90, 1.06, hash21(floor(module_phase * 2.0) + 77.0));
		albedo = mix(brick_col, mortar_color.rgb * mortar_tone, mortar_mask);
	} else {
		albedo = surf.albedo * albedo_tint.rgb * albedo_multiplier;
		if (!anti_tiling_rotation && module_variation_amount > 0.0) {
			albedo *= module_variation(module_phase, module_variation_amount);
		}
	}
	float rough = clamp(surf.rough * roughness_multiplier + roughness_bias, 0.02, 1.0);
	vec3 normal_ts = normalize(vec3(surf.normal_ts.xy * normal_strength, surf.normal_ts.z));
	float ao = surf.ao;

	// Macro color variation to break up large flat expanses beyond per-tile rotation.
	// Folding height into the Z-like phase (a no-op on flat ground, where Y is ~const)
	// keeps a wide flat WALL's variation from reading as pure vertical stripes — each
	// row gets a different phase too, so it looks like organic blotchy staining
	// instead of a graphic barcode pattern.
	if (macro_variation_strength > 0.0) {
		vec2 macro_pos = vec2(v_world_pos.x, v_world_pos.z + v_world_pos.y * 0.8);
		albedo = macro_variation(albedo, macro_pos, macro_variation_scale, macro_variation_strength);
	}

	// Grime/dirt accumulation near the ground.
	if (grime_strength > 0.0) {
		float height_above = v_world_pos.y - ground_level;
		float grime_t = 1.0 - smoothstep(0.0, max(grime_height, 0.001), height_above);
		float grime_n = fbm(v_world_pos.xz * 0.5 + v_world_pos.y * 0.3);
		float grime = clamp(grime_t * mix(0.55, 1.0, grime_n) * grime_strength, 0.0, 1.0);
		albedo = mix(albedo, albedo * vec3(0.5, 0.46, 0.4), grime);
		rough = clamp(rough + 0.2 * grime, 0.02, 1.0);
		ao = mix(ao, ao * 0.7, grime);
	}

	// Optional vertex-painted edge wear (COLOR.r authored by the mesh, 0 = untouched).
	if (edge_wear_amount > 0.0) {
		float wear = COLOR.r * edge_wear_amount;
		albedo = mix(albedo, clamp(albedo * 1.6 + 0.05, 0.0, 1.0), wear);
		rough = mix(rough, max(rough - 0.25, 0.05), wear);
	}

	// --- Weather: snow ---
	float smask = snow_mask(wn, v_world_pos, snow_cover, snow_slope_bias, snow_noise_scale);
	if (smask > 0.0) {
		// Same 2-grid blend as sample_material() — a single hard-offset tap here was
		// the source of the visible snow tile seam the iter2 critique measured (this
		// path samples snow_albedo_tex directly, bypassing sample_material entirely).
		vec2 suv = use_world_uv ? (v_world_pos.xz * uv_scale * 0.6) : (UV * uv_scale * 0.6);
		vec2 suv_a, suv_b;
		float srot_a, srot_b, sw;
		anti_tile_blend(suv, true, suv_a, suv_b, srot_a, srot_b, sw);
		vec3 s_alb = mix(texture(snow_albedo_tex, suv_a).rgb, texture(snow_albedo_tex, suv_b).rgb, sw);
		float s_rough = mix(texture(snow_roughness_tex, suv_a).r, texture(snow_roughness_tex, suv_b).r, sw);
		vec3 sn_a = rotate_tiled_normal(texture(snow_normal_tex, suv_a).rgb * 2.0 - 1.0, srot_a);
		vec3 sn_b = rotate_tiled_normal(texture(snow_normal_tex, suv_b).rgb * 2.0 - 1.0, srot_b);
		vec3 s_norm = normalize(mix(sn_a, sn_b, sw));
		apply_snow(albedo, rough, normal_ts, s_alb, s_rough, s_norm, smask, snow_albedo_multiplier);
		ao = mix(ao, 1.0, smask * 0.5);
	}

	// --- Weather: wetness (suppressed under snow) ---
	float wet_eff = wetness * (1.0 - smask * 0.9);
	float spec = 0.5;
	if (wet_eff > 0.0) {
		apply_wetness_darkening(albedo, rough, wet_eff, porosity);
		if (allow_puddles) {
			float pmask = puddle_mask(wn, v_world_pos, wet_eff, puddle_scale);
			apply_puddle(albedo, rough, normal_ts, pmask, spec);
		}
	}

	ALBEDO = albedo;
	ROUGHNESS = rough;
	METALLIC = metallic;
	SPECULAR = spec;
	AO = ao;
	AO_LIGHT_AFFECT = 0.6;
	NORMAL_MAP = normal_ts * 0.5 + 0.5;
	NORMAL_MAP_DEPTH = 1.0;
}
