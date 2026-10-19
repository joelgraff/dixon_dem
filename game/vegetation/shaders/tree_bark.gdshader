// tree_bark.gdshader — trunk/limb surface for the near tree meshes.
// A lean version of materials/shaders/surface.gdshader's mesh-UV path (same
// bark texture set, passed in from materials/lib/bark.tres by vegetation.gd)
// plus the per-tree LOD fade from tree_common.gdshaderinc. The generic
// surface shader can't fade per MultiMesh instance, so with it the trunks
// stayed until their whole chunk was culled and stood without crowns.
shader_type spatial;
render_mode world_vertex_coords, diffuse_burley, specular_schlick_ggx;

#include "res://materials/shaders/includes/noise.gdshaderinc"
#include "res://materials/shaders/includes/snow.gdshaderinc"
#include "res://materials/shaders/includes/wetness.gdshaderinc"
#include "res://vegetation/shaders/tree_common.gdshaderinc"

global uniform float snow_cover;
global uniform float wetness;

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap, repeat_enable;
uniform float albedo_multiplier : hint_range(0.0, 3.0) = 1.27;
uniform vec2 uv_scale = vec2(3.0, 3.0);

varying vec3 v_world_pos;
varying vec3 v_world_normal;
varying flat vec3 v_origin;
varying flat float v_fade;

void vertex() {
	v_origin = MODEL_MATRIX[3].xyz;
	v_fade = veg_lod_fade(v_origin);
	v_world_pos = VERTEX;
	v_world_normal = NORMAL;
	if (v_fade >= 1.0) {
		VERTEX = v_origin;
	}
}

void fragment() {
	if (v_fade > 0.0 && veg_dither(FRAGCOORD.xy, TIME) < v_fade) {
		discard;
	}
	vec2 uv = UV * uv_scale;
	vec3 albedo = texture(albedo_tex, uv).rgb * albedo_multiplier;
	// bark.tres's multiplier is tuned for lit props; trunks read tan-beige
	// with it, so pull towards a darker grey-brown.
	albedo *= vec3(0.48, 0.45, 0.43) * mix(0.85, 1.12, veg_hash(v_origin.xz * 0.37));
	NORMAL_MAP = texture(normal_tex, uv).rgb;
	float rough = 0.9;
	if (snow_cover > 0.005) {
		float smask = snow_mask(normalize(v_world_normal), v_world_pos, snow_cover, 0.1, 0.35);
		albedo = mix(albedo, vec3(0.85, 0.87, 0.9), smask * 0.9);
	}
	if (wetness > 0.005) {
		apply_wetness_darkening(albedo, rough, wetness, 0.5);
	}
	ALBEDO = albedo;
	ROUGHNESS = rough;
	METALLIC = 0.0;
}
