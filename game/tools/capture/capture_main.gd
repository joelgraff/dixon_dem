extends Node
## Screenshot harness. Usage (via tools/capture.sh):
##   --scene=res://path.tscn --shots=/abs/shots.json --out=/abs/dir [--warmup=90]
## shots.json: [{"name":"x","pos":[x,y,z],"look_at":[x,y,z],"fov":70,
##               "season":"summer","weather":"clear","hour":12.0}]
## Saves <out>/<name>.png. Any cameras in the target scene are overridden.

var _args := {}

func _ready() -> void:
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		_args[kv[0]] = kv[1] if kv.size() > 1 else "true"
	_run.call_deferred()

func _run() -> void:
	var scene_path: String = _args.get("scene", "res://world/world.tscn")
	var out_dir: String = _args.get("out", "/tmp/dixon_capture")
	var warmup := int(_args.get("warmup", "90"))
	DirAccess.make_dir_recursive_absolute(out_dir)
	var shots: Array = JSON.parse_string(FileAccess.get_file_as_string(_args.get("shots", "")))
	if shots == null:
		push_error("capture: could not read shots json"); get_tree().quit(1); return
	var root: Node = load(scene_path).instantiate()
	# Let scenes know they are being captured (e.g. player controller should not grab the camera/mouse).
	root.set_meta("capture_mode", true)
	add_child(root)
	var cam := Camera3D.new()
	add_child(cam)
	for s in shots:
		WorldState.apply_named(s.get("season", "summer"), s.get("weather", "clear"), float(s.get("hour", 12.0)))
		var p: Array = s["pos"]; var t: Array = s["look_at"]
		cam.fov = float(s.get("fov", 70.0))
		cam.far = float(s.get("far", 4000.0))
		cam.global_position = Vector3(p[0], p[1], p[2])
		cam.look_at(Vector3(t[0], t[1], t[2]))
		cam.make_current()
		for i in warmup:
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		var img := get_viewport().get_texture().get_image()
		var path := out_dir.path_join(str(s["name"]) + ".png")
		img.save_png(path)
		print("capture: saved ", path)
	get_tree().quit(0)
