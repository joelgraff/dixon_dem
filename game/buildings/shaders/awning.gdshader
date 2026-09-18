// awning.gdshader — cheap canvas storefront awning. One shared material;
// stripe vs solid and the two stripe colors ride on vertex COLOR so many
// awnings can share a single draw call:
//   COLOR.rgb = base canvas color
//   COLOR.a   = stripe amount (0 = solid, 1 = strong stripe toward white/cream)
// UV.x runs across the awning width so stripes read as vertical canvas bands.

shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx, cull_disabled;

global uniform float snow_cover;
global uniform float wetness;

void fragment() {
	float stripe = step(0.5, fract(UV.x * 6.0));
	vec3 stripe_color = mix(vec3(0.93, 0.90, 0.82), COLOR.rgb, 0.15);
	vec3 base = mix(COLOR.rgb, stripe_color, stripe * COLOR.a);
	base = mix(base, base * 0.7, wetness * 0.6);
	base = mix(base, vec3(0.9, 0.9, 0.92), snow_cover * 0.5);
	ALBEDO = base;
	ROUGHNESS = 0.85;
	METALLIC = 0.0;
}
