extends Node3D
## Near-camera GPU MultiMesh grass, per BUILDER_PROTOCOL's "grass only near
## camera" guidance. Reads the grass density/tallness raster baked by
## pipeline/vegetation/place_vegetation.py (game/vegetation/data/grass_mask.png
## + .json) and TerrainHeight (res://terrain/terrain_height.gd) for ground Y.
##
## Cell-based cache: the play area is divided into GRASS_CELL squares; cells
## within RADIUS of the camera get a MultiMeshInstance3D of blade-stamp
## instances (built once, positions cached), cells that fall out of range are
## freed. Runs a cheap rebuild pass a few times a second, not every frame.

const VegTreeBuilder = preload("res://vegetation/tree_builder.gd")

const GRASS_CELL := 10.0
const RADIUS := 42.0
const REBUILD_INTERVAL := 0.35
const STAMPS_PER_CELL := 10 # each stamp = build_grass_blades() clump of several blades

var _mask_img: Image
var _mask_w: int
var _mask_h: int
var _px_per_m: float
var _mask_origin_x: float
var _mask_origin_z_top: float

var _mown_mesh: ArrayMesh
var _tall_mesh: ArrayMesh
var _grass_mat: ShaderMaterial

var _active_cells: Dictionary = {} # Vector2i -> MultiMeshInstance3D
var _timer := 0.0
var _terrain_height_script


func _ready() -> void:
	_grass_mat = ShaderMaterial.new()
	_grass_mat.shader = load("res://vegetation/shaders/grass.gdshader")
	_mown_mesh = VegTreeBuilder.build_grass_blades(1, 5, 0.0)
	_mown_mesh.surface_set_material(0, _grass_mat)
	_tall_mesh = VegTreeBuilder.build_grass_blades(2, 6, 1.0)
	_tall_mesh.surface_set_material(0, _grass_mat)

	var meta_f := FileAccess.open("res://vegetation/data/grass_mask.json", FileAccess.READ)
	if meta_f:
		var meta = JSON.parse_string(meta_f.get_as_text())
		_px_per_m = meta.get("px_per_m", 0.5)
		_mask_origin_x = meta.get("origin_x", 0.0)
		_mask_origin_z_top = meta.get("origin_z_top", 0.0)
	else:
		_px_per_m = 0.5

	_mask_img = Image.new()
	var err := _mask_img.load("res://vegetation/data/grass_mask.png")
	if err != OK:
		push_warning("[grass_spawner] could not load grass_mask.png (%d)" % err)
		_mask_img = null
	else:
		_mask_w = _mask_img.get_width()
		_mask_h = _mask_img.get_height()

	if ResourceLoader.exists("res://terrain/terrain_height.gd"):
		_terrain_height_script = load("res://terrain/terrain_height.gd")


func _process(delta: float) -> void:
	_timer -= delta
	if _timer > 0.0:
		return
	_timer = REBUILD_INTERVAL
	if _mask_img == null:
		return
	var cam := get_viewport().get_camera_3d()
	if cam == null:
		return
	_update_cells(cam.global_position)


func _sample_mask(x: float, z: float) -> Vector2:
	# returns (mown_density, tall_density) 0..1
	var px := int((x - _mask_origin_x) * _px_per_m)
	var py := int((-(z - _mask_origin_z_top)) * _px_per_m)
	if px < 0 or py < 0 or px >= _mask_w or py >= _mask_h:
		return Vector2.ZERO
	var c := _mask_img.get_pixel(px, py)
	return Vector2(clampf(c.r / 0.78, 0.0, 1.0), clampf(c.g / 0.82, 0.0, 1.0))


func _ground_y(x: float, z: float) -> float:
	if _terrain_height_script:
		return _terrain_height_script.get_height(x, z)
	return 0.0


func _update_cells(cam_pos: Vector3) -> void:
	var ccx := int(floor(cam_pos.x / GRASS_CELL))
	var ccz := int(floor(cam_pos.z / GRASS_CELL))
	var span := int(ceil(RADIUS / GRASS_CELL))
	var wanted: Dictionary = {}

	for dx in range(-span, span + 1):
		for dz in range(-span, span + 1):
			var cx := ccx + dx
			var cz := ccz + dz
			var wx := (cx + 0.5) * GRASS_CELL
			var wz := (cz + 0.5) * GRASS_CELL
			if Vector2(wx - cam_pos.x, wz - cam_pos.z).length() > RADIUS:
				continue
			var key := Vector2i(cx, cz)
			wanted[key] = true
			if _active_cells.has(key):
				continue
			_build_cell(key, wx, wz)

	for key in _active_cells.keys():
		if not wanted.has(key):
			var node = _active_cells[key]
			if node:
				node.queue_free()
			_active_cells.erase(key)


func _build_cell(key: Vector2i, wx: float, wz: float) -> void:
	var d := _sample_mask(wx, wz)
	var mown: float = d.x
	var tall: float = d.y
	if mown < 0.05 and tall < 0.05:
		_active_cells[key] = null
		return
	var use_tall := tall > mown
	var density: float = max(mown, tall)
	var count := int(round(STAMPS_PER_CELL * clampf(density, 0.15, 1.0)))
	if count <= 0:
		_active_cells[key] = null
		return

	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = _tall_mesh if use_tall else _mown_mesh
	mm.instance_count = count
	var rng := RandomNumberGenerator.new()
	rng.seed = key.x * 92821 + key.y * 68917
	for i in range(count):
		var lx := rng.randf_range(-GRASS_CELL * 0.5, GRASS_CELL * 0.5)
		var lz := rng.randf_range(-GRASS_CELL * 0.5, GRASS_CELL * 0.5)
		var x := wx + lx
		var z := wz + lz
		var y := _ground_y(x, z)
		var s := rng.randf_range(0.8, 1.3)
		var basis := Basis(Vector3.UP, rng.randf() * TAU).scaled(Vector3.ONE * s)
		mm.set_instance_transform(i, Transform3D(basis, Vector3(x, y, z)))

	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	mmi.visibility_range_end = RADIUS + 8.0
	mmi.visibility_range_end_margin = 8.0
	mmi.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF
	add_child(mmi)
	_active_cells[key] = mmi
