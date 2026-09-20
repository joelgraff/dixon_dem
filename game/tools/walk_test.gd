extends Node
## Drives the player into an obstacle at a given speed and reports whether it
## climbed or got stuck. Used to verify curb/crossing step-up at the user's
## tuned inspection speeds (walk 10.4 / run 30.5 m/s), where a per-frame-motion
## step probe fails but a short fixed probe succeeds.
## Usage: --from=x,z --to=x,z --speed=10.4
func _ready() -> void: _run.call_deferred()

func _v2(a: String) -> Vector2:
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
	for i in 10:
		await get_tree().physics_frame
	var player: CharacterBody3D = root.find_child("Player", true, false)
	if player == null:
		print("walk_test: no Player node"); get_tree().quit(1); return
	var a := _v2(args.get("from", "1631,-1232"))
	var b := _v2(args.get("to", "1631,-1210"))
	var speed := float(args.get("speed", "10.4"))
	var space := get_viewport().world_3d.direct_space_state
	var q := PhysicsRayQueryParameters3D.create(Vector3(a.x, 200.0, a.y), Vector3(a.x, -50.0, a.y))
	var hit := space.intersect_ray(q)
	var y0: float = (hit.position.y if not hit.is_empty() else 25.0) + 1.0
	player.global_position = Vector3(a.x, y0, a.y)
	player.velocity = Vector3.ZERO
	for i in 20:
		await get_tree().physics_frame
	var dir3 := Vector3(b.x - a.x, 0.0, b.y - a.y).normalized()
	var start := player.global_position
	var max_climb := 0.0
	var stuck_frames := 0
	var prev := player.global_position
	print("walk_test: speed %.1f m/s from %s toward %s" % [speed, a, b])
	var frames := int(ceil(a.distance_to(b) / maxf(speed, 0.1) / get_physics_process_delta_time())) + 60
	for i in frames:
		player.velocity.x = dir3.x * speed
		player.velocity.z = dir3.z * speed
		if not player.is_on_floor():
			player.velocity.y -= 9.8 * get_physics_process_delta_time()
		player.call("_try_step_up", get_physics_process_delta_time(), Vector3(player.velocity.x, 0, player.velocity.z))
		player.move_and_slide()
		var moved := player.global_position.distance_to(prev)
		max_climb = maxf(max_climb, player.global_position.y - start.y)
		if moved < speed * get_physics_process_delta_time() * 0.25:
			stuck_frames += 1
		prev = player.global_position
	var travelled := Vector2(player.global_position.x, player.global_position.z).distance_to(a)
	var target := a.distance_to(b)
	print("  travelled %.2f m of %.2f m   climbed %+.3f m   stuck frames %d/%d" % [travelled, target, max_climb, stuck_frames, frames])
	print("  RESULT: %s" % ("PASSED (crossed without jumping)" if travelled > target * 0.9 else "BLOCKED"))
	get_tree().quit(0)
