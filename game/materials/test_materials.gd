extends Node3D
## Material library test/swatch scene. Builds simple architectural pieces (wall chunks
## with a ledge, a road+curb+sidewalk slab, pitched/flat roof pieces, ground patches,
## a trunk, a glazed wall) for every .tres in game/materials/lib/, under a neutral
## outdoor light rig. Captured via game/tools/capture.sh — see docs/materials_notes.md.

const LIB := "res://materials/lib/"

func _ready() -> void:
	_build_light_rig()
	_build_ground_row()
	_build_road_assembly()
	_build_wall_row()
	_build_roof_row()
	_build_bark()

func _mat(name: String) -> ShaderMaterial:
	return load(LIB + name + ".tres")

func _label(text: String, pos: Vector3) -> void:
	var l := Label3D.new()
	l.text = text
	l.position = pos
	l.font_size = 34
	l.outline_size = 10
	l.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	l.no_depth_test = false
	add_child(l)

func _box(size: Vector3, pos: Vector3, mat: Material) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var m := BoxMesh.new()
	m.size = size
	mi.mesh = m
	mi.position = pos
	mi.set_surface_override_material(0, mat)
	add_child(mi)
	return mi

# Flat ground swatches use PlaneMesh (no thin side faces) to avoid grazing-angle
# texture aliasing on a paper-thin box edge.
func _plane(size: Vector2, pos: Vector3, mat: Material) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var m := PlaneMesh.new()
	m.size = size
	mi.mesh = m
	mi.position = pos
	mi.set_surface_override_material(0, mat)
	add_child(mi)
	return mi

func _build_light_rig() -> void:
	if ResourceLoader.exists("res://atmosphere/atmosphere.tscn"):
		var atmo_scene: PackedScene = load("res://atmosphere/atmosphere.tscn")
		var atmo: Node = atmo_scene.instantiate()
		add_child(atmo)
		return
	# Fallback rig: matches ARCHITECTURE.md's spec (AgX, physical-ish sky).
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-55, -35, 0)
	sun.light_energy = 1.2
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 120.0
	add_child(sun)

	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_SKY
	var sky := Sky.new()
	var proc := ProceduralSkyMaterial.new()
	proc.sky_top_color = Color(0.30, 0.45, 0.75)
	proc.sky_horizon_color = Color(0.75, 0.80, 0.85)
	proc.ground_bottom_color = Color(0.25, 0.24, 0.22)
	proc.ground_horizon_color = Color(0.75, 0.80, 0.85)
	sky.sky_material = proc
	e.sky = sky
	e.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	e.tonemap_mode = Environment.TONE_MAPPER_AGX
	e.ssao_enabled = true
	e.glow_enabled = true
	env.environment = e
	add_child(env)

func _build_ground_row() -> void:
	var names := ["grass_lawn", "dry_grass", "forest_floor", "gravel_ballast", "mud", "snow_fresh", "snow_dirty", "ice"]
	var x := 0.0
	for n in names:
		_plane(Vector2(2.2, 2.2), Vector3(x, 0.0, 0.0), _mat(n))
		_label(n, Vector3(x, 0.7, 0.0))
		x += 2.6

func _build_road_assembly() -> void:
	var z := 5.0
	# asphalt road slab
	_plane(Vector2(5.0, 3.0), Vector3(2.0, 0.0, z), _mat("asphalt_road"))
	_label("asphalt_road", Vector3(0.5, 0.7, z))
	# patched section
	_plane(Vector2(2.0, 3.0), Vector3(5.5, 0.005, z), _mat("asphalt_patched"))
	_label("asphalt_patched", Vector3(5.5, 0.7, z))
	# curb (15cm reveal, per ART_DIRECTION real-world dims)
	_box(Vector3(0.25, 0.15, 3.0), Vector3(7.05, 0.075, z), _mat("curb_concrete"))
	_label("curb_concrete", Vector3(7.05, 0.9, z))
	# sidewalk slab, top flush with curb top
	_box(Vector3(2.2, 0.15, 3.0), Vector3(8.4, 0.075, z), _mat("sidewalk_concrete"))
	_label("sidewalk_concrete", Vector3(8.4, 0.9, z))

func _wall_chunk(x: float, z: float, mat: Material, name: String, with_glass: bool = false) -> void:
	# Main wall panel with a ledge/beltcourse near the top for silhouette interest.
	_box(Vector3(2.0, 2.6, 0.3), Vector3(x, 1.3, z), mat)
	_box(Vector3(2.3, 0.15, 0.45), Vector3(x, 2.675, z), mat)
	if with_glass:
		_box(Vector3(1.0, 1.3, 0.05), Vector3(x, 1.3, z + 0.18), _mat("window_glass"))
	_label(name, Vector3(x, 3.1, z))

func _build_wall_row() -> void:
	var z := 10.0
	var x := 0.0
	_wall_chunk(x, z, _mat("brick_red"), "brick_red"); x += 3.0
	_wall_chunk(x, z, _mat("brick_buff"), "brick_buff"); x += 3.0
	_wall_chunk(x, z, _mat("limestone"), "limestone"); x += 3.0
	_wall_chunk(x, z, _mat("stone_foundation"), "stone_foundation"); x += 3.0
	_wall_chunk(x, z, _mat("siding_white"), "siding_white", true); x += 3.0
	_wall_chunk(x, z, _mat("siding_sage"), "siding_sage"); x += 3.0
	_wall_chunk(x, z, _mat("steel_rusted"), "steel_rusted"); x += 3.0

func _gable(x: float, z: float, mat: Material, name: String) -> void:
	var left := MeshInstance3D.new()
	var lm := BoxMesh.new(); lm.size = Vector3(2.6, 0.08, 1.7)
	left.mesh = lm
	left.position = Vector3(x - 0.62, 1.55, z)
	left.rotation_degrees = Vector3(0, 0, 22)
	left.set_surface_override_material(0, mat)
	add_child(left)

	var right := MeshInstance3D.new()
	var rm := BoxMesh.new(); rm.size = Vector3(2.6, 0.08, 1.7)
	right.mesh = rm
	right.position = Vector3(x + 0.62, 1.55, z)
	right.rotation_degrees = Vector3(0, 0, -22)
	right.set_surface_override_material(0, mat)
	add_child(right)
	_label(name, Vector3(x, 2.4, z))

func _build_roof_row() -> void:
	var z := 15.0
	_gable(0.0, z, _mat("shingles_dark"), "shingles_dark")
	_gable(3.5, z, _mat("roof_metal"), "roof_metal")
	# flat membrane roof w/ a short parapet lip
	_box(Vector3(2.4, 0.15, 1.8), Vector3(7.5, 0.85, z), _mat("roof_membrane"))
	_box(Vector3(2.4, 0.3, 0.12), Vector3(7.5, 1.0, z - 0.84), _mat("roof_membrane"))
	_box(Vector3(2.4, 0.3, 0.12), Vector3(7.5, 1.0, z + 0.84), _mat("roof_membrane"))
	_label("roof_membrane", Vector3(7.5, 1.6, z))

func _build_bark() -> void:
	var mi := MeshInstance3D.new()
	var cm := CylinderMesh.new()
	cm.top_radius = 0.18
	cm.bottom_radius = 0.22
	cm.height = 3.0
	mi.mesh = cm
	mi.position = Vector3(10.5, 1.5, 0.0)
	mi.set_surface_override_material(0, _mat("bark"))
	add_child(mi)
	_label("bark", Vector3(10.5, 3.3, 0.0))
