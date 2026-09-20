// foam.gdshader — cheap scrolling-noise white-water curtain for the Dixon Dam
// spillway crest (docs/references/dixon_dam.md: "use a scrolling/foam shader
// rather than complex geometry" for the continuous sheeting water). Own small
// shader budget in landmarks/ (materials/atmosphere are frozen, per buildings'
// precedent of a few own shaders). Reuses materials' shared noise include.
shader_type spatial;
render_mode cull_disabled, unshaded, blend_mix;

#include "res://materials/shaders/includes/noise.gdshaderinc"

uniform vec4 foam_color : source_color = vec4(0.91, 0.93, 0.92, 1.0);
uniform vec4 water_color : source_color = vec4(0.35, 0.4, 0.37, 1.0);
uniform float scroll_speed : hint_range(0.0, 3.0) = 1.2;
uniform float noise_scale : hint_range(1.0, 20.0) = 6.0;

void fragment() {
	vec2 uv = UV;
	float t = TIME * scroll_speed;
	float n1 = fbm(vec2(uv.x * noise_scale, uv.y * noise_scale * 2.0 - t));
	float n2 = fbm(vec2(uv.x * noise_scale * 1.7 + 3.0, uv.y * noise_scale * 3.0 - t * 1.6));
	float foam_mask = smoothstep(0.35, 0.85, mix(n1, n2, 0.5));
	vec3 col = mix(water_color.rgb, foam_color.rgb, foam_mask);
	ALBEDO = col;
	ALPHA = 1.0;
	ROUGHNESS = 0.35;
}
