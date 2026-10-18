extends Node3D
## Builds lightweight utility poles/towers and sagged overhead conductors from
## pipeline output. Supports and wire spans are merged into static meshes.

const DATA_PATH := "res://data/power.json"
const POLE_SPACING := 55.0
const TOWER_SPACING := 220.0
const POLE_HEIGHT := 8.5
const TOWER_HEIGHT := 26.0

func _ready() -> void:
	if not FileAccess.file_exists(DATA_PATH):
		push_warning("PowerNetwork: missing %s; rerun pipeline/build_vectors.py after fetching power data" % DATA_PATH)
		return
	var file := FileAccess.open(DATA_PATH, FileAccess.READ)
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not (parsed is Dictionary) or not (parsed.get("lines", null) is Array):
		push_error("PowerNetwork: malformed %s" % DATA_PATH)
		return

	var support_positions: Dictionary = {}
	var mapped_supports: Array[Dictionary] = []
	var pole_geometry := SurfaceTool.new()
	pole_geometry.begin(Mesh.PRIMITIVE_TRIANGLES)
	var wire_geometry := SurfaceTool.new()
	wire_geometry.begin(Mesh.PRIMITIVE_TRIANGLES)

	for support in parsed.get("supports", []):
		if not (support is Dictionary):
			push_error("PowerNetwork: invalid support record")
			return
		var point := Vector3(float(support["x"]), 0.0, float(support["z"]))
		var key := Vector2i(roundi(point.x), roundi(point.z))
		var record := {"position": point, "kind": str(support.get("kind", "pole"))}
		mapped_supports.append(record)
		support_positions[key] = record

	for line in parsed["lines"]:
		if not (line is Dictionary) or not (line.get("vertices", null) is Array):
			push_error("PowerNetwork: line record has no vertex array")
			return
		var points: Array[Vector3] = []
		for vertex in line["vertices"]:
			points.append(Vector3(float(vertex["x"]), 0.0, float(vertex["z"])))
		if _polyline_length(points) < 2.0:
			continue
		var anchors := _line_anchors(points, line, mapped_supports)
		for anchor in anchors:
			var anchor_position: Vector3 = anchor["position"]
			var key := Vector2i(roundi(anchor_position.x), roundi(anchor_position.z))
			if not support_positions.has(key):
				support_positions[key] = anchor
		for i in range(anchors.size() - 1):
			_add_wire_span(wire_geometry, anchors[i], anchors[i + 1])

	for support in support_positions.values():
		var pos: Vector3 = support["position"]
		var ground_y := TerrainHeight.get_height(pos.x, pos.z)
		_add_utility_support(pole_geometry, Vector3(pos.x, ground_y, pos.z), support["kind"])

	_add_mesh_child(pole_geometry, _pole_material(), "UtilitySupports")
	_add_mesh_child(wire_geometry, _wire_material(), "OverheadConductors")
	print("[power] built %d supports from %d overhead line(s)" % [support_positions.size(), parsed["lines"].size()])


func _polyline_length(points: Array[Vector3]) -> float:
	var total := 0.0
	for i in range(points.size() - 1):
		total += Vector2(points[i].x, points[i].z).distance_to(Vector2(points[i + 1].x, points[i + 1].z))
	return total


func _point_at(points: Array[Vector3], distance: float) -> Vector3:
	var remaining := distance
	for i in range(points.size() - 1):
		var a := points[i]
		var b := points[i + 1]
		var segment_length := Vector2(a.x, a.z).distance_to(Vector2(b.x, b.z))
		if remaining <= segment_length or i == points.size() - 2:
			return a.lerp(b, clampf(remaining / maxf(segment_length, 0.001), 0.0, 1.0))
		remaining -= segment_length
	return points.back()


func _line_anchors(points: Array[Vector3], line: Dictionary, mapped_supports: Array[Dictionary]) -> Array[Dictionary]:
	var length := _polyline_length(points)
	var support_kind := _line_support_kind(line)
	var spacing := TOWER_SPACING if support_kind == "tower" else POLE_SPACING
	var anchors: Array[Dictionary] = []
	for support in mapped_supports:
		var projection := _project_to_polyline(points, support["position"])
		if projection["offset"] <= 12.0:
			anchors.append({
				"distance": projection["distance"],
				"position": support["position"],
				"kind": support["kind"],
			})
	anchors.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return a["distance"] < b["distance"])

	if anchors.is_empty() or float(anchors[0]["distance"]) > 10.0:
		anchors.push_front({"distance": 0.0, "position": _point_at(points, 0.0), "kind": support_kind})
	if length - float(anchors.back()["distance"]) > 10.0:
		anchors.append({"distance": length, "position": _point_at(points, length), "kind": support_kind})

	var result: Array[Dictionary] = []
	for i in range(anchors.size() - 1):
		var start: Dictionary = anchors[i]
		var finish: Dictionary = anchors[i + 1]
		if result.is_empty():
			result.append(start)
		var span_length := float(finish["distance"]) - float(start["distance"])
		var spans := maxi(1, int(ceil(span_length / spacing)))
		for span in range(1, spans):
			var distance := lerpf(float(start["distance"]), float(finish["distance"]), float(span) / float(spans))
			result.append({"position": _point_at(points, distance), "kind": support_kind})
		result.append(finish)
	return result


func _project_to_polyline(points: Array[Vector3], point: Vector3) -> Dictionary:
	var best_distance := 0.0
	var best_offset := INF
	var distance_at_segment_start := 0.0
	var target := Vector2(point.x, point.z)
	for i in range(points.size() - 1):
		var a := Vector2(points[i].x, points[i].z)
		var b := Vector2(points[i + 1].x, points[i + 1].z)
		var segment := b - a
		var segment_length := segment.length()
		var fraction := clampf((target - a).dot(segment) / maxf(segment.length_squared(), 0.001), 0.0, 1.0)
		var offset := target.distance_to(a + segment * fraction)
		if offset < best_offset:
			best_offset = offset
			best_distance = distance_at_segment_start + segment_length * fraction
		distance_at_segment_start += segment_length
	return {"distance": best_distance, "offset": best_offset}


func _line_support_kind(line: Dictionary) -> String:
	var voltage := str(line.get("voltage", "")).split(";")[0].to_int()
	return "tower" if voltage >= 60000 else "pole"


func _support_height(kind: String) -> float:
	if kind == "tower":
		return TOWER_HEIGHT
	if kind == "portal":
		return 16.0
	if kind == "terminal":
		return 12.0
	if kind == "transformer":
		return 10.0
	return POLE_HEIGHT


func _add_wire_span(st: SurfaceTool, start_support: Dictionary, end_support: Dictionary) -> void:
	var a: Vector3 = start_support["position"]
	var b: Vector3 = end_support["position"]
	var start_height := _support_height(start_support["kind"])
	var end_height := _support_height(end_support["kind"])
	var start := Vector3(a.x, TerrainHeight.get_height(a.x, a.z) + start_height - 0.65, a.z)
	var finish := Vector3(b.x, TerrainHeight.get_height(b.x, b.z) + end_height - 0.65, b.z)
	var direction := Vector2(finish.x - start.x, finish.z - start.z)
	var segments := maxi(3, int(ceil(direction.length() / 12.0)))
	var sag := clampf(direction.length() * 0.025, 0.8, 6.0)
	var cable := CylinderMesh.new()
	cable.top_radius = 0.025
	cable.bottom_radius = 0.025
	cable.radial_segments = 4
	for i in range(segments):
		var t0 := float(i) / float(segments)
		var t1 := float(i + 1) / float(segments)
		var p0 := _sagged_point(start, finish, t0, sag)
		var p1 := _sagged_point(start, finish, t1, sag)
		var delta := p1 - p0
		cable.height = delta.length()
		if cable.height > 0.01:
			var basis := Basis(Quaternion(Vector3.UP, delta.normalized()))
			st.append_from(cable, 0, Transform3D(basis, (p0 + p1) * 0.5))


func _sagged_point(a: Vector3, b: Vector3, t: float, sag: float) -> Vector3:
	var point := a.lerp(b, t)
	point.y -= 4.0 * sag * t * (1.0 - t)
	return point


func _add_utility_support(st: SurfaceTool, base: Vector3, kind: String) -> void:
	if kind == "tower":
		_add_tower(st, base)
		return
	var height := _support_height(kind)
	_add_beam(st, base, base + Vector3(0.0, height, 0.0), 0.18)
	for arm_y in [height - 1.0, height - 2.0]:
		_add_beam(st, base + Vector3(-1.0, arm_y, 0.0), base + Vector3(1.0, arm_y, 0.0), 0.12)
		for side in [-0.8, 0.0, 0.8]:
			_add_beam(st, base + Vector3(side, arm_y, 0.0), base + Vector3(side, arm_y + 0.3, 0.0), 0.055)


func _add_tower(st: SurfaceTool, base: Vector3) -> void:
	var top := TOWER_HEIGHT
	for x_sign in [-1.0, 1.0]:
		for z_sign in [-1.0, 1.0]:
			var foot := base + Vector3(x_sign * 2.5, 0.0, z_sign * 2.5)
			var peak := base + Vector3(x_sign * 0.8, top, z_sign * 0.8)
			_add_beam(st, foot, peak, 0.28)
			for level in [7.0, 14.0, 21.0]:
				var t: float = level / top
				var corner := foot.lerp(peak, t)
				var opposite := base + Vector3(-x_sign * (2.5 - 1.7 * t), level, -z_sign * (2.5 - 1.7 * t))
				_add_beam(st, corner, opposite, 0.12)
	for arm_y in [18.0, 24.0]:
		_add_beam(st, base + Vector3(-6.0, arm_y, 0.0), base + Vector3(6.0, arm_y, 0.0), 0.22)
		for x in [-5.0, -2.5, 0.0, 2.5, 5.0]:
			_add_beam(st, base + Vector3(x, arm_y, 0.0), base + Vector3(x, arm_y + 1.0, 0.0), 0.08)


func _add_beam(st: SurfaceTool, a: Vector3, b: Vector3, width: float) -> void:
	var delta := b - a
	if delta.length_squared() < 0.0001:
		return
	var beam := BoxMesh.new()
	beam.size = Vector3(width, delta.length(), width)
	st.append_from(beam, 0, Transform3D(Basis(Quaternion(Vector3.UP, delta.normalized())), (a + b) * 0.5))


func _add_mesh_child(st: SurfaceTool, material: Material, node_name: String) -> void:
	var mesh := ArrayMesh.new()
	st.generate_normals()
	st.commit(mesh)
	if mesh.get_surface_count() == 0:
		return
	mesh.surface_set_material(0, material)
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = mesh
	instance.gi_mode = GeometryInstance3D.GI_MODE_STATIC
	add_child(instance)


func _pole_material() -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(0.30, 0.24, 0.17)
	material.roughness = 0.9
	return material


func _wire_material() -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(0.16, 0.17, 0.16)
	material.metallic = 0.55
	material.roughness = 0.48
	return material
