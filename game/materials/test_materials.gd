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
	_build_snow_field()

func _mat(name: String) -> ShaderMaterial:
	return load(LIB + name + ".tres")

func _label(text: String, pos: Vector3) -> void:
	var l := Label3D.new()
	l.text = text
	l.position = pos
	l.font_size = 26
	l.outline_size = 8
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
	# rather than floating disconnected panels in empty sky. iter2 used dry_grass here,
	# which the critic correctly read as beach sand (a Midwest lot isn't bare dirt) —
	# switched to grass_lawn. Also raised from y=-0.08 to y=-0.01: the previous gap
	# left curb/sidewalk boxes visibly floating with daylight showing underneath.
	_plane(Vector2(30.0, 26.0), Vector3(9.0, -0.01, 8.5), _mat("grass_lawn"))

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

## A LIT (normally shaded, not unshaded) grey card of known LINEAR albedo — Godot's
## Color values are used as linear by the renderer, so Color(v,v,v) directly gives
## linear reflectance v. iter2's unlit hex chips went through the same AgX tonemap as
## everything else and so didn't measure as their hex value at all; a lit grey card of
## known albedo is the standard photographic reference instead (a real light/dark
## calibration target, not a specific paint color).
func _card(albedo: float, pos: Vector3, label_text: String) -> void:
	var mi := MeshInstance3D.new()
	var m := PlaneMesh.new()
	m.size = Vector2(0.4, 0.4)
	mi.mesh = m
	mi.position = pos
	mi.rotation_degrees = Vector3(90, 0, 0) # stand the card up, normal facing +Z
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(albedo, albedo, albedo, 1.0)
	mat.roughness = 0.85
	mi.set_surface_override_material(0, mat)
	add_child(mi)
	_label(label_text, pos + Vector3(0, 0.45, 0))

## Same as _card() but lying FLAT (coplanar with the ground), not standing up. iter3's
## snow-vs-card proof used only vertical cards next to a horizontal snow surface — under
## an overcast sky dome a vertical surface receives roughly half the irradiance of a
## horizontal one, so "snow matches a vertical 0.8 card" actually implied an albedo of
## only ~0.4-0.5. A flat card removes that confound entirely.
func _card_flat(albedo: float, pos: Vector3, label_text: String) -> void:
	var mi := MeshInstance3D.new()
	var m := PlaneMesh.new()
	m.size = Vector2(0.5, 0.5)
	mi.mesh = m
	mi.position = pos
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(albedo, albedo, albedo, 1.0)
	mat.roughness = 0.85
	mi.set_surface_override_material(0, mat)
	add_child(mi)
	_label(label_text, pos + Vector3(0, 0.35, 0))

## Four lit grey reference cards (linear albedo 0.04/0.18/0.5/0.8) in the open, well
## clear of other geometry so nothing blocks them and their labels don't overlap. Plus
## extra copies of the 0.18/0.8 cards placed right next to specific swatches the iter3
## critique asked for in-frame comparisons against (lawn, wet asphalt, snow).
func _build_reference_chart() -> void:
	var z := 3.0
	var x := 13.0
	_card(0.04, Vector3(x, 0.6, z), "card_0.04"); x += 0.9
	_card(0.18, Vector3(x, 0.6, z), "card_0.18"); x += 0.9
	_card(0.50, Vector3(x, 0.6, z), "card_0.50"); x += 0.9
	_card(0.80, Vector3(x, 0.6, z), "card_0.80")

	# Next to grass_lawn ground swatch (x=0, z=0) for lawn_vs_card shots.
	_card(0.18, Vector3(-1.3, 0.3, 0.6), "card_0.18")
	# Next to the road assembly (asphalt at x~2, sidewalk at x~8.4, z=5) for the wet sweep.
	_card(0.18, Vector3(2.0, 0.3, 7.3), "card_0.18")
	# Next to snow_fresh ground swatch (x=13.0 in the ground row, z=0): FLAT cards at
	# 0.2/0.5/0.8 (matched orientation — see _card_flat) plus one vertical 0.8 for the
	# explicit vertical-vs-horizontal comparison, plus a plain (non-weather-reactive)
	# concrete-grey card as the "snow-free concrete" reference (a real concrete swatch
	# would itself pick up snow under snow_cover).
	_card_flat(0.20, Vector3(12.4, 0.001, -1.5), "flat_0.20")
	_card_flat(0.50, Vector3(13.0, 0.001, -1.5), "flat_0.50")
	_card_flat(0.80, Vector3(13.6, 0.001, -1.5), "flat_0.80")
	_card(0.80, Vector3(14.3, 0.3, -1.5), "vert_0.80")
	var concrete_ref := MeshInstance3D.new()
	var crm := PlaneMesh.new(); crm.size = Vector2(0.5, 0.5)
	concrete_ref.mesh = crm
	concrete_ref.position = Vector3(15.0, 0.001, -1.5)
	var cmat := StandardMaterial3D.new()
	cmat.albedo_color = Color(0.35, 0.35, 0.33, 1.0) # ~real sidewalk_concrete's dry linear albedo, snow-immune
	cmat.roughness = 0.85
	concrete_ref.set_surface_override_material(0, cmat)
	add_child(concrete_ref)
	_label("concrete_ref_dry", Vector3(15.0, 0.35, -1.5))

## A large (40x40m) snow_fresh field, well clear of other geometry, for a wide
## repetition check from eye height (critique's snow_wide_40m.png).
func _build_snow_field() -> void:
	_plane(Vector2(40.0, 40.0), Vector3(-40.0, 0.0, 20.0), _mat("snow_fresh"))
	_label("snow_field_40m", Vector3(-40.0, 0.6, 20.0))

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
