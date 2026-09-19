extends Node3D
## Runtime companion to the baked res://roads/roads.tscn (see
## game/roads/tools/build_roads.gd + docs/roads_notes.md for how the static
## geometry is generated). Handles the few things that can't be pre-baked
## because they depend on WorldState at runtime:
##   - lamp night glow (cheap emissive "fake pool", no per-instance lights)
##   - winter plowed-snow windrows along curbs (visibility only, by season)
##   - autumn leaf litter in gutters (visibility only, by season/weather)
## All are driven by WorldState.changed; nothing here runs per-frame.

var _lamp_head_mats: Array[StandardMaterial3D] = []
var _windrow_nodes: Array[MultiMeshInstance3D] = []
var _leaf_nodes: Array[MultiMeshInstance3D] = []

func _ready() -> void:
	_collect_nodes(self)
	WorldState.changed.connect(_on_world_state_changed)
	_on_world_state_changed()

func _collect_nodes(node: Node) -> void:
	for child in node.get_children():
		if child is MultiMeshInstance3D:
			var name: String = child.name
			if name == "MM_windrow":
				_windrow_nodes.append(child)
			elif name == "MM_leaf_litter":
				_leaf_nodes.append(child)
			elif name == "MM_lamp_downtown" or name == "MM_lamp_residential":
				var mm: MultiMesh = child.multimesh
				if mm and mm.mesh and mm.mesh.get_surface_count() > 1:
					var mat := mm.mesh.surface_get_material(1)
					if mat is StandardMaterial3D and mat not in _lamp_head_mats:
						_lamp_head_mats.append(mat)
		if child.get_child_count() > 0:
			_collect_nodes(child)

## Simple photocell-style approximation (no dependence on RenderingServer's
## editor-only global_shader_parameter_get, or on atmosphere.gd internals):
## lamps ramp on ~90-60 min before sunset and off ~60-90 min after sunrise,
## using fixed clock hours rather than a real solar-elevation calc. Close
## enough for a street-lamp on/off cue; see docs/roads_notes.md.
func _night_amount(hour: float) -> float:
	var h := fposmod(hour, 24.0)
	if h < 5.5 or h > 19.5:
		return 1.0
	if h < 7.0:
		return 1.0 - smoothstep(5.5, 7.0, h)
	if h > 18.0:
		return smoothstep(18.0, 19.5, h)
	return 0.0

func _on_world_state_changed() -> void:
	var night := _night_amount(WorldState.hour)
	for mat in _lamp_head_mats:
		mat.emission_energy_multiplier = lerp(0.0, 3.2, night)

	var snowy := WorldState.get_snow_cover() > 0.05
	for n in _windrow_nodes:
		n.visible = snowy

	var is_autumn: bool = WorldState.season == WorldState.Season.AUTUMN
	var snow_weather: bool = WorldState.weather in [WorldState.Weather.SNOW, WorldState.Weather.BLIZZARD]
	var leafy := is_autumn and not snow_weather
	for n in _leaf_nodes:
		n.visible = leafy
