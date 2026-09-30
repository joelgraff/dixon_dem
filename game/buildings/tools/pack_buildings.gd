extends SceneTree
## Pack buildings.tscn into the binary scene the world actually instances.
func _init() -> void:
	var packed: PackedScene = load("res://buildings/buildings.tscn")
	if packed == null:
		push_error("failed to load buildings.tscn")
		quit(1)
		return
	var err := ResourceSaver.save(packed, "res://buildings/buildings.scn")
	print("packed buildings.scn err=", err)
	quit(0 if err == OK else 1)
