extends Node3D
## Dixon terrain: chunked/LOD'd play-area ground mesh + collision, a low-poly
## horizon ring, and river/pond water surfaces. Reads only from game/data/
## (heightmaps + water/landuse/rails JSON) and game/terrain/textures/ (the
## baked splat masks from pipeline/terrain/bake_splat.py) plus the shared
## materials texture library. See docs/terrain_notes.md.
##
## Chunk meshes + collision are generated once in GDScript and cached to
## game/terrain/cache/ (ArrayMesh + HeightMapShape3D .res files) keyed off
## the road-conformed heightmap's mtime, so a data-pipeline re-export is
## picked up automatically (cache invalidates) while repeat runs against
## unchanged data load straight from cache -- fast, and avoids a separate
## offline bake step per BUILDER_PROTOCOL's "generate at build time" guidance.

const TerrainHeightScript = preload("res://terrain/terrain_height.gd")
const TERRAIN_SHADER := preload("res://terrain/shaders/terrain.gdshader")
const HORIZON_SHADER := preload("res://terrain/shaders/horizon.gdshader")
const WATER_SHADER := preload("res://terrain/shaders/water.gdshader")

const TEX_DIR := "res://materials/textures/"
const DATA_DIR := "res://data/"
const MY_TEX_DIR := "res://terrain/textures/"
const CACHE_DIR := "res://terrain/cache/"
const MAT_DIR := "res://terrain/materials/"

const PLAY_SIZE := 2700.0
const CHUNK_SIZE := 150.0 # 2700 / 150 = 18 chunks per axis
const CHUNKS_PER_AXIS := 18
const LOD0_STRIDE := 2.0  # near: 76x76 verts/chunk
const LOD1_STRIDE := 10.0 # far: 16x16 verts/chunk
const LOD0_VISIBLE_END := 240.0
const LOD_FADE := 40.0
const SKIRT_DEPTH := 5.0
const COLLISION_STRIDE := 1.0 # brief: HeightMapShape3D per chunk at 1m

const HORIZON_STRIDE := 50.0
const HORIZON_HOLE_MARGIN := 30.0 # inset from the play square where the horizon mesh is omitted

var perf := {} # build timings, read by test_terrain.gd for an on-screen readout

func _ready() -> void:
	var t0 := Time.get_ticks_msec()
	DirAccess.make_dir_recursive_absolute(CACHE_DIR)
	DirAccess.make_dir_recursive_absolute(MAT_DIR)

	var terrain_mat := _build_terrain_material()
	var t_mat := Time.get_ticks_msec()

	var chunks_node := Node3D.new()
	chunks_node.name = "Chunks"
	add_child(chunks_node)
	_build_chunks(chunks_node, terrain_mat)
	var t_chunks := Time.get_ticks_msec()

	var water_node := Node3D.new()
	water_node.name = "Water"
	add_child(water_node)
	_build_water(water_node)
	var t_water := Time.get_ticks_msec()

	var horizon_node := Node3D.new()
	horizon_node.name = "Horizon"
	add_child(horizon_node)
	_build_horizon(horizon_node)
	var t_horizon := Time.get_ticks_msec()

	perf = {
		"material_ms": t_mat - t0,
		"chunks_ms": t_chunks - t_mat,
		"water_ms": t_water - t_chunks,
		"horizon_ms": t_horizon - t_water,
		"total_ms": t_horizon - t0,
	}
	print("terrain: build perf ", perf)

# ---------------------------------------------------------------------------
# Terrain material (splat masks + 7 ground layers + snow set)
# ---------------------------------------------------------------------------
func _tex(name: String, kind: String) -> Texture2D:
	return load(TEX_DIR + name + "/" + kind) as Texture2D

func _build_terrain_material() -> ShaderMaterial:
	var mat := ShaderMaterial.new()
	mat.shader = TERRAIN_SHADER
	mat.set_shader_parameter("splat_a", load(MY_TEX_DIR + "terrain_splat_a.png"))
	mat.set_shader_parameter("splat_b", load(MY_TEX_DIR + "terrain_splat_b.png"))

	var layers := {
		"lawn": "grass_lawn",
		"wild": "dry_grass",
		"wood": "forest_floor",
		"gravel": "gravel_ballast",
		"mud": "mud",
		"paved": "asphalt_patched",
		"rock": "stone_rough",
	}
	for prefix in layers:
		var tex_name: String = layers[prefix]
		mat.set_shader_parameter(prefix + "_albedo", _tex(tex_name, "albedo.jpg"))
		mat.set_shader_parameter(prefix + "_normal", _tex(tex_name, "normal.png"))
		mat.set_shader_parameter(prefix + "_rough", _tex(tex_name, "roughness.jpg"))

	# Raw JPGs read too bright for ART_DIRECTION's linear-albedo ranges;
	# mirrors materials/lib/*.tres's albedo_tint/albedo_multiplier correction
	# (see materials_notes.md) -- re-sync these if that workstream retunes.
	# stone_rough has no lib/*.tres (materials didn't build one); estimated.
	var correction := {
		"lawn": [Color(0.55, 0.95, 0.12), 0.44],
		"wild": [Color(0.75, 0.68, 0.45), 0.75],
		"wood": [Color(1, 1, 1), 0.79],
		"gravel": [Color(1, 1, 1), 1.4],
		"mud": [Color(1, 1, 1), 1.326],
		"paved": [Color(1, 1, 1), 1.31],
		"rock": [Color(0.85, 0.85, 0.82), 1.0],
	}
	for prefix in correction:
		mat.set_shader_parameter(prefix + "_tint", correction[prefix][0])
		mat.set_shader_parameter(prefix + "_albedo_mult", correction[prefix][1])

	mat.set_shader_parameter("snow_albedo_tex", _tex("snow_fresh", "albedo.jpg"))
	mat.set_shader_parameter("snow_normal_tex", _tex("snow_fresh", "normal.png"))
	mat.set_shader_parameter("snow_roughness_tex", _tex("snow_fresh", "roughness.jpg"))
	mat.set_shader_parameter("snow_albedo_multiplier", 1.778)

	var path := MAT_DIR + "terrain_material.tres"
	ResourceSaver.save(mat, path)
	return mat # saved above; keep the in-memory instance (resource_path is now set for ext_resource reuse by mesh caching)

func _build_horizon_material() -> ShaderMaterial:
	var mat := ShaderMaterial.new()
	mat.shader = HORIZON_SHADER
	mat.set_shader_parameter("wild_albedo", _tex("dry_grass", "albedo.jpg"))
	mat.set_shader_parameter("wild_normal", _tex("dry_grass", "normal.png"))
	mat.set_shader_parameter("wood_albedo", _tex("forest_floor", "albedo.jpg"))
	mat.set_shader_parameter("wood_normal", _tex("forest_floor", "normal.png"))
	mat.set_shader_parameter("rock_albedo", _tex("stone_rough", "albedo.jpg"))
	mat.set_shader_parameter("rock_normal", _tex("stone_rough", "normal.png"))
	mat.set_shader_parameter("snow_albedo_tex", _tex("snow_fresh", "albedo.jpg"))
	mat.set_shader_parameter("snow_normal_tex", _tex("snow_fresh", "normal.png"))
	mat.set_shader_parameter("snow_roughness_tex", _tex("snow_fresh", "roughness.jpg"))
	mat.set_shader_parameter("snow_albedo_multiplier", 1.778)
	mat.set_shader_parameter("wild_tint", Color(0.75, 0.68, 0.45))
	mat.set_shader_parameter("wild_albedo_mult", 0.75)
	mat.set_shader_parameter("wood_tint", Color(1, 1, 1))
	mat.set_shader_parameter("wood_albedo_mult", 0.79)
	mat.set_shader_parameter("rock_tint", Color(0.85, 0.85, 0.82))
	mat.set_shader_parameter("rock_albedo_mult", 1.0)
	var path := MAT_DIR + "horizon_material.tres"
	ResourceSaver.save(mat, path)
	return mat

func _build_water_material() -> ShaderMaterial:
	var mat := ShaderMaterial.new()
	mat.shader = WATER_SHADER
	mat.set_shader_parameter("ice_albedo", _tex("ice", "albedo.jpg"))
	mat.set_shader_parameter("ice_normal", _tex("ice", "normal.png"))
	mat.set_shader_parameter("snow_albedo_tex", _tex("snow_fresh", "albedo.jpg"))
	mat.set_shader_parameter("snow_normal_tex", _tex("snow_fresh", "normal.png"))
	mat.set_shader_parameter("snow_roughness_tex", _tex("snow_fresh", "roughness.jpg"))
	var path := MAT_DIR + "water_material.tres"
	ResourceSaver.save(mat, path)
	return mat

# ---------------------------------------------------------------------------
# Play-area chunks (LOD0/LOD1 render meshes + 1m collision), cached to disk
# ---------------------------------------------------------------------------
func _cache_is_valid() -> bool:
	var meta_path := CACHE_DIR + "_meta.json"
	var src := DATA_DIR + "heightmap_play_1m_road_conformed.r32"
	var mtime := FileAccess.get_modified_time(ProjectSettings.globalize_path(src))
	var sig := "%d|%d|%d|%d|%d" % [mtime, int(CHUNK_SIZE), int(LOD0_STRIDE * 10), int(LOD1_STRIDE * 10), int(SKIRT_DEPTH)]
	if FileAccess.file_exists(meta_path):
		var f := FileAccess.open(meta_path, FileAccess.READ)
		if f.get_as_text() == sig:
			return true
	var f := FileAccess.open(meta_path, FileAccess.WRITE)
	f.store_string(sig)
	return false

func _build_chunks(parent: Node3D, mat: ShaderMaterial) -> void:
	var cache_valid := _cache_is_valid()
	var built := 0
	var loaded := 0
	for cz in CHUNKS_PER_AXIS:
		for cx in CHUNKS_PER_AXIS:
			var x0 := cx * CHUNK_SIZE
			var z0 := -PLAY_SIZE + cz * CHUNK_SIZE
			var key := "chunk_%02d_%02d" % [cx, cz]
			var p0 := CACHE_DIR + key + "_lod0.res"
			var p1 := CACHE_DIR + key + "_lod1.res"
			var pc := CACHE_DIR + key + "_col.res"
			var lod0: ArrayMesh
			var lod1: ArrayMesh
			var col_shape: HeightMapShape3D
			if cache_valid and FileAccess.file_exists(p0) and FileAccess.file_exists(p1) and FileAccess.file_exists(pc):
				lod0 = load(p0)
				lod1 = load(p1)
				col_shape = load(pc)
				loaded += 1
			else:
				lod0 = _build_grid_mesh(x0, z0, CHUNK_SIZE, LOD0_STRIDE, SKIRT_DEPTH)
				lod1 = _build_grid_mesh(x0, z0, CHUNK_SIZE, LOD1_STRIDE, SKIRT_DEPTH)
				col_shape = _build_collision(x0, z0)
				ResourceSaver.save(lod0, p0)
				ResourceSaver.save(lod1, p1)
				ResourceSaver.save(col_shape, pc)
				built += 1

			var chunk := Node3D.new()
			chunk.name = key
			# Chunk mesh vertices are baked chunk-local (see _build_grid_mesh);
			# position the node at the chunk's actual world location so
			# visibility_range (measured from this transform's origin, not the
			# mesh's baked AABB) and frustum culling use the real distance to
			# the camera instead of the distance to world (0,0,0) for every
			# chunk alike.
			chunk.position = Vector3(x0, 0.0, z0)
			parent.add_child(chunk)

			var mi0 := MeshInstance3D.new()
			mi0.name = "LOD0"
			mi0.mesh = lod0
			mi0.set_surface_override_material(0, mat)
			mi0.visibility_range_end = LOD0_VISIBLE_END
			mi0.visibility_range_end_margin = LOD_FADE
			mi0.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF
			chunk.add_child(mi0)

			var mi1 := MeshInstance3D.new()
			mi1.name = "LOD1"
			mi1.mesh = lod1
			mi1.set_surface_override_material(0, mat)
			mi1.visibility_range_begin = LOD0_VISIBLE_END
			mi1.visibility_range_begin_margin = LOD_FADE
			mi1.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF
			chunk.add_child(mi1)

			var body := StaticBody3D.new()
			body.name = "Collision"
			body.position = Vector3(CHUNK_SIZE * 0.5, 0.0, CHUNK_SIZE * 0.5) # relative to chunk's own origin now
			var cshape := CollisionShape3D.new()
			cshape.shape = col_shape
			body.add_child(cshape)
			chunk.add_child(body)
	print("terrain: chunks built=%d loaded_from_cache=%d" % [built, loaded])

## Grid mesh for one square chunk. `stride` meters/vertex, world_vertex_coords
## shader convention (VERTEX is world-space once the parent chunk Node3D's
## transform -- positioned at (x0,0,z0) by _build_chunks -- is applied).
## Vertices are baked CHUNK-LOCAL (0..size), not world-absolute: Godot's
## visibility_range/frustum culling measure distance from this node's own
## transform origin, so baking world-absolute positions under an identity
## transform would make every chunk (near or far) report the same distance
## (to world (0,0,0)) instead of its true distance to the camera. Height
## lookups still use true world (x0+local, z0+local) coordinates. A skirt
## ring (extra verts dropped by skirt_depth) hides cracks against
## neighboring chunks at a different LOD tier.
func _build_grid_mesh(x0: float, z0: float, size: float, stride: float, skirt_depth: float) -> ArrayMesh:
	var n := int(round(size / stride)) + 1
	var verts := PackedVector3Array()
	var uvs := PackedVector2Array()
	verts.resize(n * n)
	uvs.resize(n * n)
	for row in n:
		var z_local := row * stride
		var z_world := z0 + z_local
		for col in n:
			var x_local := col * stride
			var x_world := x0 + x_local
			var h: float = TerrainHeightScript.get_height(x_world, z_world)
			var idx := row * n + col
			verts[idx] = Vector3(x_local, h, z_local)
			uvs[idx] = Vector2(float(col) / float(n - 1), float(row) / float(n - 1))

	var normals := PackedVector3Array()
	normals.resize(n * n)
	for row in n:
		var z_world := z0 + row * stride
		for col in n:
			var idx := row * n + col
			var x_world := x0 + col * stride
			var h_l: float = verts[idx - 1].y if col > 0 else TerrainHeightScript.get_height(x_world - stride, z_world)
			var h_r: float = verts[idx + 1].y if col < n - 1 else TerrainHeightScript.get_height(x_world + stride, z_world)
			var h_d: float = verts[idx - n].y if row > 0 else TerrainHeightScript.get_height(x_world, z_world - stride)
			var h_u: float = verts[idx + n].y if row < n - 1 else TerrainHeightScript.get_height(x_world, z_world + stride)
			var dx := (h_r - h_l) / (2.0 * stride)
			var dz := (h_u - h_d) / (2.0 * stride)
			normals[idx] = Vector3(-dx, 1.0, -dz).normalized()

	var indices := PackedInt32Array()
	indices.resize((n - 1) * (n - 1) * 6)
	var ii := 0
	for row in n - 1:
		for col in n - 1:
			var i0 := row * n + col
			var i1 := i0 + 1
			var i2 := i0 + n
			var i3 := i2 + 1
			indices[ii] = i0; indices[ii + 1] = i1; indices[ii + 2] = i2
			indices[ii + 3] = i1; indices[ii + 4] = i3; indices[ii + 5] = i2
			ii += 6

	if skirt_depth > 0.0:
		_append_skirt(verts, normals, uvs, indices, n)

	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = verts
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_INDEX] = indices
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh

## Adds a downward-facing skirt around the 4 edges of an n x n grid so gaps
## against a neighboring chunk at a different LOD (different stride, so
## vertices don't line up 1:1) are hidden rather than showing daylight.
func _append_skirt(verts: PackedVector3Array, normals: PackedVector3Array, uvs: PackedVector2Array, indices: PackedInt32Array, n: int) -> void:
	var top := PackedInt32Array(); var bottom := PackedInt32Array()
	var left := PackedInt32Array(); var right := PackedInt32Array()
	for col in n:
		top.append(col) # row 0
		bottom.append((n - 1) * n + col) # row n-1
	for row in n:
		left.append(row * n) # col 0
		right.append(row * n + (n - 1)) # col n-1
	var edges: Array[PackedInt32Array] = [top, bottom, left, right]
	for border in edges:
		var base := verts.size()
		for i in border.size():
			var src: int = border[i]
			verts.append(verts[src] - Vector3(0, 5.0, 0))
			normals.append(normals[src])
			uvs.append(uvs[src])
		for i in border.size() - 1:
			var a: int = border[i]
			var b: int = border[i + 1]
			var a2 := base + i
			var b2 := base + i + 1
			# Two triangles forming the vertical skirt quad; winding matches
			# the top surface's CCW-from-above convention on the adjoining edge.
			indices.append(a); indices.append(a2); indices.append(b)
			indices.append(b); indices.append(a2); indices.append(b2)

func _build_collision(x0: float, z0: float) -> HeightMapShape3D:
	var n := int(round(CHUNK_SIZE / COLLISION_STRIDE)) + 1
	var heights := PackedFloat32Array()
	heights.resize(n * n)
	for row in n:
		var z := z0 + row * COLLISION_STRIDE
		for col in n:
			var x := x0 + col * COLLISION_STRIDE
			heights[row * n + col] = TerrainHeightScript.get_height(x, z)
	var shape := HeightMapShape3D.new()
	shape.map_width = n
	shape.map_depth = n
	shape.map_data = heights
	return shape

# ---------------------------------------------------------------------------
# Water (river reaches + ponds), from game/data/water.json
# ---------------------------------------------------------------------------
func _principal_axis(points: PackedVector2Array) -> Vector2:
	if points.size() < 2:
		return Vector2(1, 0)
	var mean := Vector2.ZERO
	for p in points:
		mean += p
	mean /= points.size()
	var sxx := 0.0; var sxy := 0.0; var syy := 0.0
	for p in points:
		var d := p - mean
		sxx += d.x * d.x; sxy += d.x * d.y; syy += d.y * d.y
	var angle := 0.5 * atan2(2.0 * sxy, sxx - syy)
	return Vector2(cos(angle), sin(angle))

func _build_water(parent: Node3D) -> void:
	var path := DATA_DIR + "water.json"
	if not FileAccess.file_exists(path):
		push_warning("terrain: water.json missing")
		return
	var water: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
	var base_mat := _build_water_material()

	var dam_point := Vector2(1.0e6, 1.0e6)
	var dam_dir := Vector2(0, 1)
	var dam_pts := PackedVector2Array()
	for dam in water.get("dams", []):
		for v in dam.get("vertices", []):
			dam_pts.append(Vector2(v.x, v.z))
	if dam_pts.size() > 0:
		var mean := Vector2.ZERO
		for p in dam_pts:
			mean += p
		dam_point = mean / dam_pts.size()
		dam_dir = _principal_axis(dam_pts)

	for reach in water.get("reaches", []):
		var ring: Array = reach.get("polygon", [])
		if ring.size() < 3:
			continue
		var poly := PackedVector2Array()
		for p in ring:
			poly.append(Vector2(p.x, p.z))
		var tris := Geometry2D.triangulate_polygon(poly)
		if tris.is_empty():
			continue
		var y: float = reach.get("surface_y", 0.0)
		var verts := PackedVector3Array()
		var normals := PackedVector3Array()
		var uvs := PackedVector2Array()
		for p in poly:
			verts.append(Vector3(p.x, y, p.y))
			normals.append(Vector3.UP)
			uvs.append(p / 50.0)
		var arrays := []
		arrays.resize(Mesh.ARRAY_MAX)
		arrays[Mesh.ARRAY_VERTEX] = verts
		arrays[Mesh.ARRAY_NORMAL] = normals
		arrays[Mesh.ARRAY_TEX_UV] = uvs
		arrays[Mesh.ARRAY_INDEX] = tris
		var mesh := ArrayMesh.new()
		mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)

		var mat: ShaderMaterial = base_mat.duplicate()
		var id: String = reach.get("id", "")
		var is_pond: bool = id.contains("pond")
		mat.set_shader_parameter("is_pond", is_pond)
		mat.set_shader_parameter("flow_dir", _principal_axis(poly))
		if id.contains("downstream"):
			mat.set_shader_parameter("dam_point", dam_point)
			mat.set_shader_parameter("dam_dir", dam_dir)

		var mi := MeshInstance3D.new()
		mi.name = "Reach_" + id
		mi.mesh = mesh
		mi.set_surface_override_material(0, mat)
		mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		parent.add_child(mi)

# ---------------------------------------------------------------------------
# Horizon ring: low-poly distant terrain from the 12.5m/10km heightmap, with
# a hole (plus safety margin) where the higher-detail play terrain covers.
# ---------------------------------------------------------------------------
func _build_horizon(parent: Node3D) -> void:
	var grid: TerrainHeightScript.Grid = TerrainHeightScript.get_horizon_grid()
	if grid == null:
		return
	var x_min: float = grid.origin_x
	var x_max: float = grid.origin_x + (grid.width - 1) * grid.spacing
	var z_min: float = grid.origin_z
	var z_max: float = grid.origin_z + (grid.height - 1) * grid.spacing
	var nx := int(floor((x_max - x_min) / HORIZON_STRIDE)) + 1
	var nz := int(floor((z_max - z_min) / HORIZON_STRIDE)) + 1

	var verts := PackedVector3Array()
	var uvs := PackedVector2Array()
	verts.resize(nx * nz)
	uvs.resize(nx * nz)
	for row in nz:
		var z: float = z_min + row * HORIZON_STRIDE
		for col in nx:
			var x: float = x_min + col * HORIZON_STRIDE
			var h: float = TerrainHeightScript.get_height(x, z)
			var idx := row * nx + col
			verts[idx] = Vector3(x, h, z)
			uvs[idx] = Vector2(float(col) / float(nx - 1), float(row) / float(nz - 1))

	var normals := PackedVector3Array()
	normals.resize(nx * nz)
	for row in nz:
		for col in nx:
			var idx := row * nx + col
			var x: float = verts[idx].x
			var z: float = verts[idx].z
			var h_l: float = verts[idx - 1].y if col > 0 else TerrainHeightScript.get_height(x - HORIZON_STRIDE, z)
			var h_r: float = verts[idx + 1].y if col < nx - 1 else TerrainHeightScript.get_height(x + HORIZON_STRIDE, z)
			var h_d: float = verts[idx - nx].y if row > 0 else TerrainHeightScript.get_height(x, z - HORIZON_STRIDE)
			var h_u: float = verts[idx + nx].y if row < nz - 1 else TerrainHeightScript.get_height(x, z + HORIZON_STRIDE)
			var dx := (h_r - h_l) / (2.0 * HORIZON_STRIDE)
			var dz := (h_u - h_d) / (2.0 * HORIZON_STRIDE)
			normals[idx] = Vector3(-dx, 1.0, -dz).normalized()

	var lo := HORIZON_HOLE_MARGIN
	var hi := PLAY_SIZE - HORIZON_HOLE_MARGIN
	var indices := PackedInt32Array()
	for row in nz - 1:
		for col in nx - 1:
			var i0 := row * nx + col
			var i1 := i0 + 1
			var i2 := i0 + nx
			var i3 := i2 + 1
			var inside := true
			for vi in [i0, i1, i2, i3]:
				var vx: float = verts[vi].x
				var vz: float = verts[vi].z
				if not (vx > lo and vx < hi and vz > -hi and vz < -lo):
					inside = false
					break
			if inside:
				continue # covered by the play-area chunks
			indices.append(i0); indices.append(i2); indices.append(i1)
			indices.append(i1); indices.append(i2); indices.append(i3)

	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = verts
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_INDEX] = indices
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)

	var mat := _build_horizon_material()
	var mi := MeshInstance3D.new()
	mi.name = "HorizonRing"
	mi.mesh = mesh
	mi.set_surface_override_material(0, mat)
	mi.extra_cull_margin = 16384.0
	parent.add_child(mi)
