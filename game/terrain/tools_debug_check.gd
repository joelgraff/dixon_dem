extends Node

func _ready() -> void:
	var terrain = (load("res://terrain/terrain.tscn") as PackedScene).instantiate()
	add_child(terrain)
	await get_tree().process_frame
	var chunks := terrain.get_node("Chunks")
	var target_name := "chunk_10_11"
	var found := false
	for chunk in chunks.get_children():
		if chunk.name == target_name:
			found = true
			var mi0 := chunk.get_node("LOD0") as MeshInstance3D
			var mi1 := chunk.get_node("LOD1") as MeshInstance3D
			print("chunk ", chunk.name, " pos ", chunk.position)
			print("  LOD0 mesh verts(surf0 arrays vertex count)=", mi0.mesh.get_faces().size(), " aabb=", mi0.get_aabb(), " visible_end=", mi0.visibility_range_end, " visible_begin=", mi0.visibility_range_begin)
			print("  LOD1 aabb=", mi1.get_aabb(), " visible_begin=", mi1.visibility_range_begin)
			print("  LOD0 global aabb origin+size sample check")
			var arrs = mi0.mesh.surface_get_arrays(0)
			var verts: PackedVector3Array = arrs[Mesh.ARRAY_VERTEX]
			print("  vertex count=", verts.size(), " first5=", verts.slice(0,5), " last5=", verts.slice(verts.size()-5,verts.size()))
			var minv := Vector3(1e9,1e9,1e9)
			var maxv := Vector3(-1e9,-1e9,-1e9)
			for v in verts:
				minv = minv.min(v); maxv = maxv.max(v)
			print("  min=",minv," max=",maxv)
	print("found target chunk: ", found)
	print("chunk count total=", chunks.get_child_count())
	get_tree().quit(0)
