extends Node
## Renders world.tscn WITH the HUD visible (no capture_mode meta) and saves a
## frame, so HUD layout/minimap can be checked without a human at the keyboard.
func _ready() -> void: _run.call_deferred()
func _run() -> void:
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else "true"
	var root: Node = load("res://world/world.tscn").instantiate()
	add_child(root)          # deliberately NO capture_mode meta
	for i in 30:
		await get_tree().physics_frame
	var pl: Node3D = root.find_child("Player", true, false)
	if pl:
		pl.global_position = Vector3(float(args.get("x", "1631.3")), 0.0, float(args.get("z", "-1214.2")))
		var space := get_viewport().world_3d.direct_space_state
		var q := PhysicsRayQueryParameters3D.create(pl.global_position + Vector3(0, 300, 0), pl.global_position - Vector3(0, 100, 0))
		var hit := space.intersect_ray(q)
		if not hit.is_empty():
			pl.global_position.y = hit.position.y + 1.7
	for i in int(args.get("warmup", "120")):
		await get_tree().process_frame
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	img.save_png(args.get("out", "/tmp/hud.png"))
	print("hud_preview saved ", args.get("out", "/tmp/hud.png"))
	get_tree().quit(0)
