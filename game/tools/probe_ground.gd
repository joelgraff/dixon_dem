extends Node
## Ground-profile probe: raycasts straight down along a line and prints the
## collision height + collider the player's feet would meet. Used to find steps
## the player has to jump (crosswalks, curbs, crossings) without eyeballing.
## Usage: godot --path game res://tools/probe_ground.tscn -- --from=x,z --to=x,z [--step=0.5]
func _ready() -> void:
	_run.call_deferred()

func _parse(a: String) -> Vector2:
	var p := a.split(",")
	return Vector2(float(p[0]), float(p[1]))

func _run() -> void:
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else "true"
	var root: Node = load("res://world/world.tscn").instantiate()
	root.set_meta("capture_mode", true)
	add_child(root)
	for i in 8:
		await get_tree().physics_frame
	var a := _parse(args.get("from", "1631,-1230"))
	var b := _parse(args.get("to", "1631,-1198"))
	var step := float(args.get("step", "0.5"))
	var space := get_viewport().world_3d.direct_space_state
	var n := int(a.distance_to(b) / step)
	var prev_y := INF
	print("probe: from ", a, " to ", b, " step ", step)
	for i in n + 1:
		var p := a.lerp(b, float(i) / maxf(n, 1))
		var q := PhysicsRayQueryParameters3D.create(Vector3(p.x, 200.0, p.y), Vector3(p.x, -50.0, p.y))
		var hit := space.intersect_ray(q)
		if hit.is_empty():
			print("  %6.1f  (no hit)" % [a.distance_to(p)])
			prev_y = INF
			continue
		var y: float = hit.position.y
		var who: String = str(hit.collider.get_parent().name) + "/" + str(hit.collider.name)
		var jump := "" if prev_y == INF else ("   STEP %+.3f m" % (y - prev_y))
		if prev_y != INF and absf(y - prev_y) >= 0.30:
			jump += "   <-- exceeds player step-up (0.30 m)"
		print("  %6.1f m   y=%7.3f   %-34s%s" % [a.distance_to(p), y, who, jump])
		prev_y = y
	get_tree().quit(0)
