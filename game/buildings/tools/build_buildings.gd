extends SceneTree
## Buildings workstream bake tool. Reads the chunked triangle-soup build plan
## written by pipeline/buildings/build_building_plan.py (game/buildings/_build/
## manifest.json + chunk_<cx>_<cz>.json) and bakes game/buildings/buildings.tscn:
## one merged multi-surface ArrayMesh per chunk (near LOD, real facades) + a
## second flat-shaded HLOD box mesh per chunk (far LOD), plus per-building
## convex collision shapes grouped under one StaticBody3D per chunk.
##
## Run headless (no GPU needed, this only builds/saves resources):
##   godot --headless --path game --script res://buildings/tools/build_buildings.gd
##
## See docs/buildings_notes.md.

const BUILD_DIR := "res://buildings/_build/"
const MANIFEST := BUILD_DIR + "manifest.json"
const OUT_SCENE := "res://buildings/buildings.tscn"

## Real facade detail (storefront/window/cornice rhythm) stays visible out to
## ~700m so a 200-400m street/across-the-river view still reads as a real
## building, not a flat HLOD box (coordinator composed-frame review,
## 2026-09-19). The near mesh is cheap (whole-town near LOD is ~300k tris
## merged into ~10 materials/chunk), so this costs little on the RX 580.
const NEAR_END := 700.0
const NEAR_FADE_MARGIN := 60.0
const FAR_BEGIN := 640.0
const FAR_END := 2600.0
const FAR_FADE_MARGIN := 60.0


func _init() -> void:
	var manifest: Variant = _read_json(MANIFEST)
	if manifest == null:
		push_error("buildings: could not read manifest at %s" % MANIFEST)
		quit(1)
		return

	var materials := {}
	for key in manifest["materials"].keys():
		var mat := load(manifest["materials"][key])
		if mat == null:
			push_error("buildings: failed to load material %s -> %s" % [key, manifest["materials"][key]])
		materials[key] = mat
	var far_material := load(manifest["far_material"])

	var root := Node3D.new()
	root.name = "Buildings"
	var near_container := Node3D.new()
	near_container.name = "Near"
	var far_container := Node3D.new()
	far_container.name = "Far"
	var collision_container := Node3D.new()
	collision_container.name = "Collision"
	root.add_child(near_container)
	root.add_child(far_container)
	root.add_child(collision_container)

	var total_collisions := 0
	var total_near_surfaces := 0
	var total_far_surfaces := 0
	var chunks: Array = manifest["chunks"]

	for chunk_info in chunks:
		var data: Variant = _read_json(BUILD_DIR + String(chunk_info["file"]))
		if data == null:
			push_error("buildings: could not read chunk %s" % chunk_info["file"])
			continue
		var cx: int = chunk_info["cx"]
		var cz: int = chunk_info["cz"]
		var chunk_name := "chunk_%d_%d" % [cx, cz]
		# Vertices/hulls in the chunk JSON are already relative to this chunk
		# center (pipeline/buildings/build_building_plan.py) -- give each
		# chunk node a REAL transform here instead of leaving it at identity.
		# A node sitting at the scene origin with world-space vertices baked
		# thousands of meters away breaks Godot's visibility_range (measured
		# from the node's transform origin, not the mesh AABB) and is fragile
		# for any origin-keyed broad-phase culling. Root-caused 2026-09-19
		# (buildings invisible from most camera positions) -- see
		# docs/buildings_notes.md.
		var origin: float = 0.0
		var chunk_origin := Vector3(float(chunk_info.get("origin_x", origin)), 0.0, float(chunk_info.get("origin_z", origin)))

		var near_groups: Dictionary = data.get("near", {})
		if near_groups.size() > 0:
			var mesh := _build_array_mesh(near_groups, materials)
			var mi := MeshInstance3D.new()
			mi.name = chunk_name + "_near"
			mi.mesh = mesh
			mi.position = chunk_origin
			mi.visibility_range_end = NEAR_END
			mi.visibility_range_end_margin = NEAR_FADE_MARGIN
			mi.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF
			near_container.add_child(mi)
			total_near_surfaces += mesh.get_surface_count()

		var far_groups: Dictionary = data.get("far", {})
		if far_groups.size() > 0:
			var far_mat_map := {"building_far": far_material}
			var far_mesh := _build_array_mesh(far_groups, far_mat_map)
			var fi := MeshInstance3D.new()
			fi.name = chunk_name + "_far"
			fi.mesh = far_mesh
			fi.position = chunk_origin
			fi.visibility_range_begin = FAR_BEGIN
			fi.visibility_range_begin_margin = FAR_FADE_MARGIN
			fi.visibility_range_end = FAR_END
			fi.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF
			far_container.add_child(fi)
			total_far_surfaces += far_mesh.get_surface_count()

		var collisions: Array = data.get("collisions", [])
		if collisions.size() > 0:
			var body := StaticBody3D.new()
			body.name = chunk_name + "_collision"
			body.position = chunk_origin
			for col in collisions:
				var hull: Array = col["hull"]
				if hull.size() < 3:
					continue
				var y0: float = col["y0"]
				var y1: float = col["y1"]
				var pts := PackedVector3Array()
				for p in hull:
					pts.append(Vector3(p[0], y0, p[1]))
					pts.append(Vector3(p[0], y1, p[1]))
				var shape := ConvexPolygonShape3D.new()
				shape.points = pts
				var cs := CollisionShape3D.new()
				cs.shape = shape
				body.add_child(cs)
				total_collisions += 1
			collision_container.add_child(body)

	_set_owner_recursive(root, root)

	var packed := PackedScene.new()
	var pack_err := packed.pack(root)
	if pack_err != OK:
		push_error("buildings: PackedScene.pack failed: %d" % pack_err)
		quit(1)
		return

	var save_err := ResourceSaver.save(packed, OUT_SCENE)
	if save_err != OK:
		push_error("buildings: ResourceSaver.save failed: %d" % save_err)
		quit(1)
		return

	print("buildings: saved ", OUT_SCENE)
	print("buildings: chunks=", chunks.size(), " near_surfaces=", total_near_surfaces,
			" far_surfaces=", total_far_surfaces, " collision_shapes=", total_collisions)
	quit(0)


func _read_json(path: String):
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return null
	var text := f.get_as_text()
	var result: Variant = JSON.parse_string(text)
	return result


func _build_array_mesh(groups: Dictionary, materials: Dictionary) -> ArrayMesh:
	var mesh := ArrayMesh.new()
	for mat_key in groups.keys():
		var g: Dictionary = groups[mat_key]
		var verts: Array = g["verts"]
		var indices: Array = g["indices"]
		if verts.is_empty() or indices.is_empty():
			continue
		var st := SurfaceTool.new()
		st.begin(Mesh.PRIMITIVE_TRIANGLES)
		for v in verts:
			var vv: Array = v
			st.set_normal(Vector3(vv[3], vv[4], vv[5]))
			st.set_uv(Vector2(vv[6], vv[7]))
			st.set_color(Color(vv[8], vv[9], vv[10], vv[11]))
			st.add_vertex(Vector3(vv[0], vv[1], vv[2]))
		for idx in indices:
			st.add_index(int(idx))
		st.generate_tangents()
		mesh = st.commit(mesh)
		var mat = materials.get(mat_key)
		if mat != null:
			mesh.surface_set_material(mesh.get_surface_count() - 1, mat)
	return mesh


func _set_owner_recursive(node: Node, owner: Node) -> void:
	for child in node.get_children():
		child.owner = owner
		_set_owner_recursive(child, owner)
