extends Node3D
## Material library test/swatch scene. Builds simple architectural pieces (wall chunks
## with a ledge, a road+curb+sidewalk slab, pitched/flat roof pieces, ground patches,
## a trunk, a glazed wall) for every .tres in game/materials/lib/, under a neutral
## outdoor light rig. Captured via game/tools/capture.sh — see docs/materials_notes.md.

const LIB := "res://materials/lib/"

func _ready() -> void:
	_build_light_rig()
	_build_ground_plane()
	_build_ground_row()
	_build_road_assembly()
	_build_wall_row()
	_build_roof_row()
	_build_bark()
	_build_wide_brick_wall()
	_build_reference_chart()

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

func _build_ground_plane() -> void:
	# A single lot-sized ground plane so every swatch reads as sitting IN a place
	# rather than floating disconnected panels in empty sky.
	_plane(Vector2(30.0, 26.0), Vector3(9.0, -0.08, 8.5), _mat("dry_grass"))

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

## Builds a gable (two roof pitches meeting cleanly at a ridge line along Z).
## Each panel is positioned so its ridge-side edge lands exactly on ridge_point —
## get this wrong (e.g. rotate a centered box without correcting its offset) and the
## two panels cross into an X instead of meeting, which is what iter1 shipped.
func _gable(ridge_point: Vector3, mat: Material, name: String, half_span: float = 1.3, pitch_deg: float = 22.0, depth: float = 1.7) -> void:
	var pitch_rad := deg_to_rad(pitch_deg)
	var slope_len := half_span / cos(pitch_rad)
	var dx := (slope_len * 0.5) * cos(pitch_rad)
	var dy := (slope_len * 0.5) * sin(pitch_rad)

	var right := MeshInstance3D.new()
	var rm := BoxMesh.new(); rm.size = Vector3(slope_len, 0.08, depth)
	right.mesh = rm
	right.position = ridge_point + Vector3(dx, -dy, 0.0)
	right.rotation_degrees = Vector3(0, 0, -pitch_deg)
	right.set_surface_override_material(0, mat)
	add_child(right)

	var left := MeshInstance3D.new()
	var lm := BoxMesh.new(); lm.size = Vector3(slope_len, 0.08, depth)
	left.mesh = lm
	left.position = ridge_point + Vector3(-dx, -dy, 0.0)
	left.rotation_degrees = Vector3(0, 0, pitch_deg)
	left.set_surface_override_material(0, mat)
	add_child(left)

	_label(name, ridge_point + Vector3(0, 0.85, 0))

func _build_roof_row() -> void:
	var z := 15.0
	var ridge_h := 1.55
	# A short support wall under each gable so the roof reads as sitting on a
	# structure rather than floating.
	_box(Vector3(2.2, ridge_h - 0.9, 1.5), Vector3(0.0, (ridge_h - 0.9) * 0.5, z), _mat("siding_white"))
	_gable(Vector3(0.0, ridge_h, z), _mat("shingles_dark"), "shingles_dark")
	_box(Vector3(2.2, ridge_h - 0.9, 1.5), Vector3(3.5, (ridge_h - 0.9) * 0.5, z), _mat("siding_white"))
	_gable(Vector3(3.5, ridge_h, z), _mat("roof_metal"), "roof_metal")
	# flat membrane roof w/ a short parapet lip, on its own support wall
	_box(Vector3(2.4, ridge_h - 0.7, 1.8), Vector3(7.5, (ridge_h - 0.7) * 0.5, z), _mat("siding_white"))
	_box(Vector3(2.4, 0.15, 1.8), Vector3(7.5, ridge_h - 0.7 + 0.075, z), _mat("roof_membrane"))
	_box(Vector3(2.4, 0.3, 0.12), Vector3(7.5, ridge_h - 0.7 + 0.22, z - 0.84), _mat("roof_membrane"))
	_box(Vector3(2.4, 0.3, 0.12), Vector3(7.5, ridge_h - 0.7 + 0.22, z + 0.84), _mat("roof_membrane"))
	_label("roof_membrane", Vector3(7.5, ridge_h + 0.6, z))

## A 20m-wide, unbroken brick_red wall for critic-requested scale/tiling checks
## (head-on at 3m close-up and 25m distant).
func _build_wide_brick_wall() -> void:
	var z := 22.0
	_box(Vector3(20.0, 3.5, 0.3), Vector3(10.0, 1.75, z), _mat("brick_red"))
	_label("brick_red_20m", Vector3(10.0, 3.9, z))

func _chip(hex: String, pos: Vector3, label_text: String) -> void:
	var mi := MeshInstance3D.new()
	var m := PlaneMesh.new()
	m.size = Vector2(0.4, 0.4)
	mi.mesh = m
	mi.position = pos
	mi.rotation_degrees = Vector3(90, 0, 0) # stand the card up, normal facing +Z (toward cameras placed at larger Z looking back at -Z, as used throughout this scene)
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color.html(hex)
	mi.set_surface_override_material(0, mat)
	add_child(mi)
	_label(label_text, pos + Vector3(0, 0.35, 0))

## Flat, unlit reference chips at the real target hex values (from ART_DIRECTION /
## critic feedback) next to the materials they correspond to, for direct numeric
## comparison in captures — see docs/materials_notes.md's iter2 measurement notes.
func _build_reference_chart() -> void:
	var z := 3.0
	var x := 13.0
	_chip("#9A5B45", Vector3(x, 0.6, z), "ref_brick_red"); x += 0.7
	_chip("#C4A876", Vector3(x, 0.6, z), "ref_brick_buff"); x += 0.7
	_chip("#5B7B3F", Vector3(x, 0.6, z), "ref_grass_lawn"); x += 0.7
	_chip("#F1EFE8", Vector3(x, 0.6, z), "ref_siding_white")

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
