shader_type spatial;
render_mode unshaded;
// Placeholder window material for the atmosphere test diorama only — the real
// building/window materials belong to the materials & buildings workstreams.
// Demonstrates the night_factor global uniform hook: windows go from a dark
// unlit pane in daylight to a warm emissive glow at night.

global uniform float night_factor;

uniform vec3 day_color : source_color = vec3(0.07, 0.08, 0.1);
uniform vec3 night_color : source_color = vec3(1.0, 0.78, 0.42);

void fragment() {
	vec3 c = mix(day_color, night_color, night_factor);
	ALBEDO = c;
	EMISSION = night_color * night_factor * 1.6;
}
