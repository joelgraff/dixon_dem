extends SceneTree
## Pack landmarks.tscn into the binary scene world.tscn instances.
## The baker writes the text scene; the game loads res://landmarks/landmarks.scn.
func _init() -> void:
	var packed: PackedScene = load("res://landmarks/landmarks.tscn")
	if packed == null:
		push_error("failed to load landmarks.tscn")
		quit(1)
		return
	var err := ResourceSaver.save(packed, "res://landmarks/landmarks.scn")
	print("packed landmarks.scn err=", err)
	quit(0 if err == OK else 1)
