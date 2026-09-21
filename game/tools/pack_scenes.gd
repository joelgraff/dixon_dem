extends SceneTree
## Converts the big generated .tscn scenes to binary .scn.
##
## The bakers write text scenes, which are human-diffable but enormous: roads.tscn is
## 242 MB and buildings.tscn 101 MB, and every load parses that text and base64-decodes
## every vertex array. Binary PackedScene skips both. Geometry is generated, not authored,
## so there is nothing to lose by storing it binary -- the .tscn stays on disk as the
## readable artefact and the .scn is what the game loads.
##
## Run: godot --headless --path game --script res://tools/pack_scenes.gd
func _init() -> void:
	var targets := [
		"res://roads/roads",
		"res://buildings/buildings",
		"res://landmarks/landmarks",
		"res://vegetation/vegetation",
	]
	for base in targets:
		var src: String = base + ".tscn"
		if not ResourceLoader.exists(src):
			print("skip (missing): ", src)
			continue
		var t0 := Time.get_ticks_msec()
		var packed: PackedScene = load(src)
		if packed == null:
			print("FAILED to load ", src)
			continue
		var load_ms := Time.get_ticks_msec() - t0
		var dst: String = base + ".scn"
		var err := ResourceSaver.save(packed, dst)
		var a := FileAccess.open(src, FileAccess.READ)
		var b := FileAccess.open(dst, FileAccess.READ)
		var sa := (a.get_length() if a else 0) / 1048576.0
		var sb := (b.get_length() if b else 0) / 1048576.0
		print("%-34s text %7.1f MB (parsed in %5.1f s)  ->  binary %7.1f MB   err=%d"
			% [src, sa, load_ms / 1000.0, sb, err])
	quit()
