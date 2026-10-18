extends Node

const GrassScript = preload("res://vegetation/grass_spawner.gd")

func _ready() -> void:
	var scene := load("res://roads/roads.scn") as PackedScene
	if scene == null:
		push_error("transportation test: bake roads first")
		get_tree().quit(1)
		return
	var roads := scene.instantiate()
	add_child(roads)
	var grass := Node3D.new()
	grass.set_script(GrassScript)
	add_child(grass)
	grass.set_physics_process(false)
	await get_tree().physics_frame
	await get_tree().physics_frame
	for material in ["grass_lawn", "asphalt_road_plowed"]:
		var found := false
		for chunk in roads.get_children():
			var surface := chunk.get_node_or_null("Surf_" + material) as MeshInstance3D
			if surface == null:
				continue
			var arrays := surface.mesh.surface_get_arrays(0)
			var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
			var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
			for i in range(0, indices.size(), 3):
				var a := vertices[indices[i]]
				var b := vertices[indices[i + 1]]
				var c := vertices[indices[i + 2]]
				var center := (a + b + c) / 3.0
				if center.x < 10 or center.x > 2690 or center.z < -2690 or center.z > -10:
					continue
				if (b - a).cross(c - a).length() < 0.4:
					continue
				var sampled: Variant = grass.call("_ground_y", center.x, center.z)
				if material == "grass_lawn":
					if sampled == null or absf(float(sampled) - center.y) > 0.02:
						push_error("transportation test: grass does not meet its graded collision")
						get_tree().quit(1)
						return
				elif sampled != null:
					push_error("transportation test: grass permitted on asphalt")
					get_tree().quit(1)
					return
				found = true
				break
			if found:
				break
		if not found:
			push_error("transportation test: no testable " + material + " triangle")
			get_tree().quit(1)
			return
	print("transportation collision and grass placement tests passed")
	roads.free()
	grass.free()
	get_tree().quit(0)
