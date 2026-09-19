extends Node
## Offline build tool: reads pipeline/roads' chunked JSON build-plan from
## res://roads/_build/ (Python: pipeline/roads/build_road_plan.py) and bakes
## res://roads/roads.tscn -- ArrayMesh chunks (one MeshInstance3D per material
## per chunk, sharing the existing game/materials/lib/*.tres library so
## snow/wetness response comes for free), MultiMeshInstance3D street furniture,
## and per-chunk StaticBody3D collision for walkable surfaces.
##
## Run headless (see game/roads/tools/build_roads.sh):
##   godot --headless --path game res://roads/tools/build_roads.tscn
## Re-run any time pipeline/roads/build_road_plan.py's output changes.

const BUILD_DIR := "res://roads/_build/"
const OUT_SCENE := "res://roads/roads.tscn"
const CHUNK_VIS_END := 900.0
const CHUNK_VIS_MARGIN := 60.0
const FURN_VIS_END := 480.0
const FURN_VIS_MARGIN := 40.0

const MATERIAL_PATHS := {
	"asphalt_road": "res://materials/lib/asphalt_road.tres",
	"asphalt_patched": "res://materials/lib/asphalt_patched.tres",
	"asphalt_road_plowed": "res://roads/materials/asphalt_road_plowed.tres",
	"asphalt_patched_plowed": "res://roads/materials/asphalt_patched_plowed.tres",
	"curb_concrete": "res://materials/lib/curb_concrete.tres",
	"sidewalk_concrete": "res://materials/lib/sidewalk_concrete.tres",
	"gravel_ballast": "res://materials/lib/gravel_ballast.tres",
	"steel_rusted": "res://materials/lib/steel_rusted.tres",
	"marking_yellow": "res://roads/materials/marking_yellow.tres",
	"marking_white": "res://roads/materials/marking_white.tres",
	"bridge_deck": "res://roads/materials/bridge_deck.tres",
}
const WALKABLE := ["asphalt_road", "asphalt_patched", "asphalt_road_plowed", "asphalt_patched_plowed",
	"curb_concrete", "sidewalk_concrete", "bridge_deck", "gravel_ballast"]

var _material_cache := {}
var _prop_mesh_cache := {}

func _ready() -> void:
	_run.call_deferred()

func _load_json(path: String):
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		push_error("build_roads: cannot open " + path)
		return null
	var txt := f.get_as_text()
	f.close()
	return JSON.parse_string(txt)

func _get_material(name: String) -> Material:
	if _material_cache.has(name):
		return _material_cache[name]
	var path: String = MATERIAL_PATHS.get(name, "")
	var mat: Material
	if path != "" and ResourceLoader.exists(path):
		mat = load(path)
	else:
		var sm := StandardMaterial3D.new()
		sm.albedo_color = Color(0.6, 0.6, 0.6)
		mat = sm
	_material_cache[name] = mat
	return mat

func _run() -> void:
	print("build_roads: loading manifest...")
	var manifest = _load_json(BUILD_DIR + "manifest.json")
	if manifest == null:
		push_error("build_roads: no manifest -- run pipeline/roads/build_road_plan.py first")
		get_tree().quit(1)
		return

	var root := Node3D.new()
	root.name = "Roads"

	var chunks: Array = manifest["chunks"]
	var n := 0
	for info in chunks:
		var data = _load_json(BUILD_DIR + str(info["file"]))
		if data == null:
			continue
		var chunk := _build_chunk(data)
		if chunk:
			root.add_child(chunk)
		n += 1
		if n % 50 == 0:
			print("build_roads: %d / %d chunks" % [n, chunks.size()])

	print("build_roads: setting owners...")
	_set_owner_recursive(root, root)

	print("build_roads: packing scene...")
	var packed := PackedScene.new()
	var err := packed.pack(root)
	if err != OK:
		push_error("build_roads: pack() failed: %d" % err)
		get_tree().quit(1)
		return
	err = ResourceSaver.save(packed, OUT_SCENE)
	print("build_roads: saved %s (err=%d)" % [OUT_SCENE, err])
	get_tree().quit(0 if err == OK else 1)

func _set_owner_recursive(node: Node, root: Node) -> void:
	for child in node.get_children():
		child.owner = root
		_set_owner_recursive(child, root)

func _build_chunk(data: Dictionary) -> Node3D:
	var cx: int = data["cx"]
	var cz: int = data["cz"]
	var chunk := Node3D.new()
	chunk.name = "Chunk_%d_%d" % [cx, cz]

	var collision_faces := PackedVector3Array()
	var mesh_list: Array = data.get("meshes", [])
	for entry in mesh_list:
		var mat_name: String = entry["material"]
		var verts: Array = entry["verts"]
		var indices: Array = entry["indices"]
		if verts.is_empty() or indices.is_empty():
			continue
		var n: int = verts.size()
		var positions := PackedVector3Array()
		positions.resize(n)
		var normals := PackedVector3Array()
		normals.resize(n)
		var uvs := PackedVector2Array()
		uvs.resize(n)
		for i in n:
			var v: Array = verts[i]
			positions[i] = Vector3(v[0], v[1], v[2])
			normals[i] = Vector3(v[3], v[4], v[5])
			uvs[i] = Vector2(v[6], v[7])
		var idx := PackedInt32Array()
		idx.resize(indices.size())
		for i in indices.size():
			idx[i] = int(indices[i])

		var arrays := []
		arrays.resize(Mesh.ARRAY_MAX)
		arrays[Mesh.ARRAY_VERTEX] = positions
		arrays[Mesh.ARRAY_NORMAL] = normals
		arrays[Mesh.ARRAY_TEX_UV] = uvs
		arrays[Mesh.ARRAY_INDEX] = idx

		var arr_mesh := ArrayMesh.new()
		arr_mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
		arr_mesh.surface_set_material(0, _get_material(mat_name))

		var mi := MeshInstance3D.new()
		mi.name = "Surf_" + mat_name
		mi.mesh = arr_mesh
		mi.gi_mode = GeometryInstance3D.GI_MODE_STATIC
		mi.visibility_range_begin = 0.0
		mi.visibility_range_end = CHUNK_VIS_END
		mi.visibility_range_end_margin = CHUNK_VIS_MARGIN
		mi.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF
		chunk.add_child(mi)

		if mat_name in WALKABLE:
			for i in range(0, idx.size(), 3):
				collision_faces.push_back(positions[idx[i]])
				collision_faces.push_back(positions[idx[i + 1]])
				collision_faces.push_back(positions[idx[i + 2]])

	if collision_faces.size() >= 3:
		var body := StaticBody3D.new()
		body.name = "Collision"
		var shape := ConcavePolygonShape3D.new()
		shape.set_faces(collision_faces)
		var cs := CollisionShape3D.new()
		cs.shape = shape
		body.add_child(cs)
		chunk.add_child(body)

	var furniture: Dictionary = data.get("furniture", {})
	for kind in furniture.keys():
		var transforms: Array = furniture[kind]
		if transforms.is_empty():
			continue
		var mesh := _get_prop_mesh(kind)
		if mesh == null:
			continue
		var mm := MultiMesh.new()
		mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.mesh = mesh
		mm.instance_count = transforms.size()
		for i in transforms.size():
			var t: Array = transforms[i]
			var pos := Vector3(t[0], t[1], t[2])
			var ry: float = t[3]
			var basis := Basis(Vector3.UP, ry)
			mm.set_instance_transform(i, Transform3D(basis, pos))
		var mmi := MultiMeshInstance3D.new()
		mmi.name = "MM_" + kind
		mmi.multimesh = mm
		mmi.gi_mode = GeometryInstance3D.GI_MODE_STATIC
		mmi.visibility_range_begin = 0.0
		mmi.visibility_range_end = FURN_VIS_END
		mmi.visibility_range_end_margin = FURN_VIS_MARGIN
		mmi.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF
		chunk.add_child(mmi)

	return chunk

# ---------------------------------------------------------------------------
# Simple primitive prop meshes (MultiMesh-friendly: one ArrayMesh per kind,
# multiple surfaces so a prop can combine e.g. a grey pole + a colored head
# without per-instance material overrides).
# ---------------------------------------------------------------------------
func _get_prop_mesh(kind: String) -> ArrayMesh:
	if _prop_mesh_cache.has(kind):
		return _prop_mesh_cache[kind]
	var mesh: ArrayMesh = _build_prop_mesh(kind)
	_prop_mesh_cache[kind] = mesh
	return mesh

func _flat_mat(color: Color, rough: float = 0.6, metal: float = 0.0) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = color
	m.roughness = rough
	m.metallic = metal
	return m

## Lamp light-head material: cheap "fake pool" night glow (no real lights per
## instance -- MultiMesh has none anyway). roads.gd finds these by name at
## runtime and drives emission_energy_multiplier from the night_factor global.
func _lamp_head_mat(color: Color, resource_name: String) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = color
	m.roughness = 0.4
	m.emission_enabled = true
	m.emission = color
	m.emission_energy_multiplier = 0.0
	m.resource_name = resource_name
	return m

func _append_box(st: SurfaceTool, size: Vector3, center: Vector3) -> void:
	var bm := BoxMesh.new()
	bm.size = size
	var t := Transform3D(Basis(), center)
	st.append_from(bm, 0, t)

func _append_cyl(st: SurfaceTool, top_r: float, bottom_r: float, height: float, center: Vector3, sides: int = 8) -> void:
	var cm := CylinderMesh.new()
	cm.top_radius = top_r
	cm.bottom_radius = bottom_r
	cm.height = height
	cm.radial_segments = sides
	var t := Transform3D(Basis(), center)
	st.append_from(cm, 0, t)

func _surface_from(st: SurfaceTool, mat: Material, existing: ArrayMesh) -> ArrayMesh:
	st.index()
	st.generate_normals()
	var out: ArrayMesh = existing if existing else ArrayMesh.new()
	out = st.commit(out)
	out.surface_set_material(out.get_surface_count() - 1, mat)
	return out

func _build_prop_mesh(kind: String) -> ArrayMesh:
	var mesh: ArrayMesh = null
	match kind:
		"lamp_downtown":
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_cyl(st, 0.05, 0.07, 4.2, Vector3(0, 2.1, 0))
			_append_box(st, Vector3(0.9, 0.05, 0.05), Vector3(0, 4.1, 0))
			mesh = _surface_from(st, _flat_mat(Color(0.09, 0.08, 0.08), 0.4, 0.3), mesh)
			var st2 := SurfaceTool.new()
			st2.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_cyl(st2, 0.09, 0.09, 0.16, Vector3(0.35, 4.05, 0))
			_append_cyl(st2, 0.09, 0.09, 0.16, Vector3(-0.35, 4.05, 0))
			mesh = _surface_from(st2, _lamp_head_mat(Color(0.98, 0.92, 0.72), "lamp_head_downtown"), mesh)
		"lamp_residential":
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_cyl(st, 0.08, 0.12, 6.0, Vector3(0, 3.0, 0), 6)
			_append_box(st, Vector3(0.7, 0.06, 0.06), Vector3(0.35, 5.9, 0))
			mesh = _surface_from(st, _flat_mat(Color(0.42, 0.35, 0.27), 0.85, 0.0), mesh)
			var st2 := SurfaceTool.new()
			st2.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_box(st2, Vector3(0.18, 0.12, 0.14), Vector3(0.68, 5.82, 0))
			mesh = _surface_from(st2, _lamp_head_mat(Color(0.92, 0.85, 0.65), "lamp_head_residential"), mesh)
		"hydrant":
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_cyl(st, 0.13, 0.16, 0.55, Vector3(0, 0.275, 0), 8)
			_append_cyl(st, 0.06, 0.13, 0.12, Vector3(0, 0.61, 0), 8)
			_append_box(st, Vector3(0.30, 0.08, 0.08), Vector3(0, 0.38, 0))
			mesh = _surface_from(st, _flat_mat(Color(0.62, 0.08, 0.06), 0.55, 0.1), mesh)
			var st2 := SurfaceTool.new()
			st2.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_cyl(st2, 0.07, 0.07, 0.06, Vector3(0, 0.68, 0), 8)
			mesh = _surface_from(st2, _flat_mat(Color(0.85, 0.7, 0.15), 0.5, 0.1), mesh)
		"stopsign":
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_cyl(st, 0.045, 0.045, 2.2, Vector3(0, 1.1, 0), 8)
			mesh = _surface_from(st, _flat_mat(Color(0.72, 0.72, 0.74), 0.4, 0.5), mesh)
			var st2 := SurfaceTool.new()
			st2.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_cyl(st2, 0.32, 0.32, 0.04, Vector3(0, 2.15, 0), 8)
			mesh = _surface_from(st2, _flat_mat(Color(0.75, 0.08, 0.08), 0.45, 0.0), mesh)
		"sign_street":
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_cyl(st, 0.04, 0.04, 2.6, Vector3(0, 1.3, 0), 8)
			mesh = _surface_from(st, _flat_mat(Color(0.72, 0.72, 0.74), 0.4, 0.5), mesh)
			var st2 := SurfaceTool.new()
			st2.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_box(st2, Vector3(0.9, 0.22, 0.02), Vector3(0, 2.55, 0))
			mesh = _surface_from(st2, _flat_mat(Color(0.06, 0.35, 0.18), 0.5, 0.0), mesh)
		"signal_mast":
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_cyl(st, 0.11, 0.16, 5.5, Vector3(0, 2.75, 0), 8)
			_append_box(st, Vector3(6.0, 0.12, 0.12), Vector3(3.0, 5.4, 0))
			mesh = _surface_from(st, _flat_mat(Color(0.15, 0.15, 0.16), 0.5, 0.3), mesh)
			var st2 := SurfaceTool.new()
			st2.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_box(st2, Vector3(0.3, 0.75, 0.3), Vector3(2.0, 4.9, 0))
			_append_box(st2, Vector3(0.3, 0.75, 0.3), Vector3(4.0, 4.9, 0))
			mesh = _surface_from(st2, _flat_mat(Color(0.05, 0.05, 0.05), 0.5, 0.1), mesh)
		"manhole":
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_cyl(st, 0.36, 0.36, 0.03, Vector3(0, 0.0, 0), 12)
			mesh = _surface_from(st, _flat_mat(Color(0.16, 0.15, 0.14), 0.75, 0.15), mesh)
		"bench":
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_box(st, Vector3(1.4, 0.06, 0.4), Vector3(0, 0.46, 0))
			_append_box(st, Vector3(1.4, 0.5, 0.06), Vector3(0, 0.7, -0.17))
			_append_box(st, Vector3(0.06, 0.46, 0.4), Vector3(0.65, 0.23, 0))
			_append_box(st, Vector3(0.06, 0.46, 0.4), Vector3(-0.65, 0.23, 0))
			mesh = _surface_from(st, _flat_mat(Color(0.10, 0.22, 0.13), 0.7, 0.1), mesh)
		"trashcan":
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_cyl(st, 0.28, 0.24, 0.75, Vector3(0, 0.375, 0), 10)
			mesh = _surface_from(st, _flat_mat(Color(0.08, 0.2, 0.12), 0.7, 0.1), mesh)
		"tie":
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_box(st, Vector3(0.22, 0.15, 2.5), Vector3(0, 0, 0))
			mesh = _surface_from(st, _flat_mat(Color(0.10, 0.07, 0.05), 0.9, 0.0), mesh)
		"windrow":
			# Plowed-snow pile along the curb -- roads.gd toggles/scales this
			# by WorldState snow_cover (invisible outside winter).
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_box(st, Vector3(0.9, 0.22, 1.0), Vector3(0, 0.11, 0))
			_append_cyl(st, 0.0, 0.4, 0.3, Vector3(0, 0.32, 0), 6)
			mesh = _surface_from(st, _flat_mat(Color(0.82, 0.85, 0.88), 0.75, 0.0), mesh)
		"leaf_litter":
			# Autumn leaf drift in the gutter -- roads.gd toggles by season.
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			var colors := [Color(0.72, 0.36, 0.10), Color(0.62, 0.22, 0.08), Color(0.78, 0.55, 0.12)]
			for i in 5:
				var ang := i * 1.256
				var r := 0.12 + (i % 3) * 0.08
				var pos := Vector3(cos(ang) * r, 0.01, sin(ang) * r)
				var pm := PlaneMesh.new()
				pm.size = Vector2(0.35, 0.35)
				st.append_from(pm, 0, Transform3D(Basis(Vector3.UP, ang * 1.7), pos))
			mesh = _surface_from(st, _flat_mat(Color(0.66, 0.34, 0.10), 0.85, 0.0), mesh)
		"crossbuck":
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			_append_cyl(st, 0.07, 0.09, 3.0, Vector3(0, 1.5, 0), 8)
			mesh = _surface_from(st, _flat_mat(Color(0.65, 0.65, 0.66), 0.5, 0.3), mesh)
			var st2 := SurfaceTool.new()
			st2.begin(Mesh.PRIMITIVE_TRIANGLES)
			var b1 := BoxMesh.new()
			b1.size = Vector3(1.5, 0.16, 0.03)
			st2.append_from(b1, 0, Transform3D(Basis(Vector3.FORWARD, deg_to_rad(28.0)), Vector3(0, 2.75, 0)))
			st2.append_from(b1, 0, Transform3D(Basis(Vector3.FORWARD, deg_to_rad(-28.0)), Vector3(0, 2.75, 0)))
			mesh = _surface_from(st2, _flat_mat(Color(0.9, 0.87, 0.8), 0.5, 0.0), mesh)
		_:
			mesh = null
	return mesh
