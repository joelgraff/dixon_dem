extends Node3D
## Stand-in diorama for atmosphere testing — the real town isn't built yet.
## Gently rolling terrain, a couple of brick boxes with window insets, a road
## strip, scattered sphere/cylinder "trees", a dark river plane, and far hills.
## Instances the atmosphere rig. Everything here is throwaway geometry; swap
## for real assets once terrain/buildings/vegetation workstreams land.

const TERRAIN_SIZE := 600.0
const TERRAIN_SEGMENTS := 72
const WINDOW_SHADER := preload("res://atmosphere/shaders/window_demo.gdshader")

var _terrain_mat: StandardMaterial3D
var _road_mat: StandardMaterial3D
var _canopy_mat: StandardMaterial3D
const _TERRAIN_BASE := Color(0.16, 0.22, 0.11)
const _ROAD_BASE := Color(0.07, 0.07, 0.075)
const _CANOPY_BASE := Color(0.16, 0.28, 0.1)
const _SNOW_WHITE := Color(0.85, 0.87, 0.9)

func _ready() -> void:
	add_child(preload("res://atmosphere/atmosphere.tscn").instantiate())
	_build_terrain()
	_build_road()
	_build_building(Vector3(-14, 0, -30), Vector3(16, 11, 12), 3)
	_build_building(Vector3(12, 0, -34), Vector3(14, 8, 11), 2)
	_build_trees()
	_build_river()
	_build_hills()
	_build_preview_camera()
	WorldState.changed.connect(_update_snow_response)
	_update_snow_response()

## Placeholder snow response for this throwaway diorama only — the real
## materials workstream will wire snow_cover into the shared material shaders
## per docs/ARCHITECTURE.md's contract. Just blends toward white here so
## winter captures are legible.
func _update_snow_response() -> void:
	var s := WorldState.get_snow_cover()
	if _terrain_mat:
		_terrain_mat.albedo_color = _TERRAIN_BASE.lerp(_SNOW_WHITE, s)
	if _road_mat:
		_road_mat.albedo_color = _ROAD_BASE.lerp(_SNOW_WHITE * 0.6, s * 0.6)
	if _canopy_mat:
		_canopy_mat.albedo_color = _CANOPY_BASE.lerp(_SNOW_WHITE, s * 0.7)

func _ground_height(x: float, z: float) -> float:
	var d := Vector2(x, z).length()
	var flat: float = clamp(1.0 - d / 90.0, 0.0, 1.0)
	var h := sin(x * 0.02) * cos(z * 0.017) * 4.5 * (1.0 - flat)
	h += sin(x * 0.07 + z * 0.05) * 1.2 * (1.0 - flat)
	return h

func _build_terrain() -> void:
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var n := TERRAIN_SEGMENTS
	var half := TERRAIN_SIZE * 0.5
	var verts: Array[Vector3] = []
	for j in range(n + 1):
		for i in range(n + 1):
			var x: float = -half + TERRAIN_SIZE * float(i) / float(n)
			var z: float = -half + TERRAIN_SIZE * float(j) / float(n)
			verts.append(Vector3(x, _ground_height(x, z), z))
	for j in range(n):
		for i in range(n):
			var a := j * (n + 1) + i
			var b := a + 1
			var c := a + (n + 1)
			var d2 := c + 1
			var uv_a := Vector2(float(i) / n, float(j) / n) * 40.0
			var uv_b := Vector2(float(i + 1) / n, float(j) / n) * 40.0
			var uv_c := Vector2(float(i) / n, float(j + 1) / n) * 40.0
			var uv_d := Vector2(float(i + 1) / n, float(j + 1) / n) * 40.0
			st.set_uv(uv_a); st.add_vertex(verts[a])
			st.set_uv(uv_b); st.add_vertex(verts[b])
			st.set_uv(uv_c); st.add_vertex(verts[c])
			st.set_uv(uv_b); st.add_vertex(verts[b])
			st.set_uv(uv_d); st.add_vertex(verts[d2])
			st.set_uv(uv_c); st.add_vertex(verts[c])
	st.generate_normals()
	st.generate_tangents()
	var mi := MeshInstance3D.new()
	mi.name = "Terrain"
	mi.mesh = st.commit()
	_terrain_mat = StandardMaterial3D.new()
	_terrain_mat.albedo_color = _TERRAIN_BASE
	_terrain_mat.roughness = 0.95
	mi.material_override = _terrain_mat
	add_child(mi)

func _build_road() -> void:
	var mi := MeshInstance3D.new()
	mi.name = "Road"
	var box := BoxMesh.new()
	box.size = Vector3(9.0, 0.15, 240.0)
	mi.mesh = box
	mi.position = Vector3(0, 0.08, -30)
	_road_mat = StandardMaterial3D.new()
	_road_mat.albedo_color = _ROAD_BASE
	_road_mat.roughness = 0.9
	mi.material_override = _road_mat
	add_child(mi)

func _build_building(pos: Vector3, size: Vector3, floors: int) -> void:
	var root := Node3D.new()
	root.position = pos + Vector3(0, size.y * 0.5, 0)
	add_child(root)

	var body := MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = size
	body.mesh = box
	var brick := StandardMaterial3D.new()
	brick.albedo_color = Color(0.42, 0.24, 0.19)
	brick.roughness = 0.85
	body.material_override = brick
	root.add_child(body)

	var win_mat := ShaderMaterial.new()
	win_mat.shader = WINDOW_SHADER
	var win_mesh := QuadMesh.new()
	win_mesh.size = Vector2(1.1, 1.5)
	win_mesh.material = win_mat

	var cols := maxi(2, int(size.x / 3.0))
	var floor_h := size.y / float(floors)
	for f in range(floors):
		for c in range(cols):
			var local_x: float = -size.x * 0.5 + (float(c) + 0.5) * (size.x / float(cols))
			var local_y: float = -size.y * 0.5 + (float(f) + 0.5) * floor_h
			for face_z in [size.z * 0.5 + 0.02, -size.z * 0.5 - 0.02]:
				var w := MeshInstance3D.new()
				w.mesh = win_mesh
				w.position = Vector3(local_x, local_y, face_z)
				if face_z < 0.0:
					w.rotate_y(PI)
				root.add_child(w)

func _build_trees() -> void:
	var trunk_mesh := CylinderMesh.new()
	trunk_mesh.top_radius = 0.18
	trunk_mesh.bottom_radius = 0.24
	trunk_mesh.height = 3.0
	var trunk_mat := StandardMaterial3D.new()
	trunk_mat.albedo_color = Color(0.28, 0.2, 0.14)
	trunk_mat.roughness = 0.95
	trunk_mesh.material = trunk_mat

	var canopy_mesh := SphereMesh.new()
	canopy_mesh.radius = 2.2
	canopy_mesh.height = 4.2
	_canopy_mat = StandardMaterial3D.new()
	_canopy_mat.albedo_color = _CANOPY_BASE
	_canopy_mat.roughness = 0.9
	canopy_mesh.material = _canopy_mat

	var trunk_mm := MultiMesh.new()
	trunk_mm.transform_format = MultiMesh.TRANSFORM_3D
	var canopy_mm := MultiMesh.new()
	canopy_mm.transform_format = MultiMesh.TRANSFORM_3D

	var rng := RandomNumberGenerator.new()
	rng.seed = 42
	var count := 48
	trunk_mm.instance_count = count
	canopy_mm.instance_count = count
	trunk_mm.mesh = trunk_mesh
	canopy_mm.mesh = canopy_mesh

	for i in range(count):
		var ang := rng.randf() * TAU
		var rad: float = lerp(40.0, 260.0, rng.randf())
		var x := cos(ang) * rad
		var z := sin(ang) * rad - 30.0
		# keep clear of the road strip
		if absf(x) < 8.0:
			x += sign(x) * 10.0 if x != 0.0 else 10.0
		var scale_v: float = lerp(0.7, 1.4, rng.randf())
		var y := _ground_height(x, z)
		var t := Transform3D(Basis().scaled(Vector3(scale_v, scale_v, scale_v)).rotated(Vector3.UP, rng.randf() * TAU), Vector3(x, y + 1.5 * scale_v, z))
		trunk_mm.set_instance_transform(i, t)
		var ct := Transform3D(Basis().scaled(Vector3(scale_v, scale_v, scale_v)), Vector3(x, y + 3.6 * scale_v, z))
		canopy_mm.set_instance_transform(i, ct)

	var trunk_inst := MultiMeshInstance3D.new()
	trunk_inst.name = "TreeTrunks"
	trunk_inst.multimesh = trunk_mm
	add_child(trunk_inst)
	var canopy_inst := MultiMeshInstance3D.new()
	canopy_inst.name = "TreeCanopies"
	canopy_inst.multimesh = canopy_mm
	add_child(canopy_inst)

func _build_river() -> void:
	var mi := MeshInstance3D.new()
	mi.name = "River"
	var plane := PlaneMesh.new()
	plane.size = Vector2(50.0, 700.0)
	mi.mesh = plane
	mi.position = Vector3(220.0, -1.0, -30.0)
	mi.rotate_y(deg_to_rad(12.0))
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.05, 0.09, 0.09)
	mat.roughness = 0.12
	mat.metallic = 0.05
	mi.material_override = mat
	add_child(mi)

func _build_hills() -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	for i in range(10):
		var ang: float = lerp(-0.9, 0.9, float(i) / 9.0) - PI * 0.5 # centered toward -Z (north), ahead of the road
		var dist: float = lerp(1400.0, 2400.0, rng.randf())
		var x := cos(ang) * dist
		var z := sin(ang) * dist - 30.0
		var mi := MeshInstance3D.new()
		var sphere := SphereMesh.new()
		sphere.radius = lerp(300.0, 700.0, rng.randf())
		sphere.height = sphere.radius * lerp(0.6, 1.0, rng.randf())
		mi.mesh = sphere
		mi.position = Vector3(x, -sphere.height * 0.55, z)
		var mat := StandardMaterial3D.new()
		mat.albedo_color = Color(0.32, 0.38, 0.42)
		mat.roughness = 1.0
		mi.material_override = mat
		add_child(mi)

func _build_preview_camera() -> void:
	if has_meta("capture_mode"):
		return
	var cam := Camera3D.new()
	cam.name = "PreviewCamera"
	cam.current = true
	cam.position = Vector3(0, 1.7, 10)
	cam.look_at(Vector3(0, 1.6, -30), Vector3.UP)
	cam.fov = 70.0
	cam.far = 4000.0
	add_child(cam)
