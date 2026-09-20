extends Node
## Casts a 3D ray and reports what it hits (distance, collider, surface normal).
## Used to tell "geometry exists but is backface-culled" from "geometry missing":
## a hit at the facade plane means the wall is there and simply not rendering.
func _ready() -> void: _run.call_deferred()
func _run() -> void:
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else "true"
	var root: Node = load("res://world/world.tscn").instantiate()
	root.set_meta("capture_mode", true)
	add_child(root)
	for i in 12:
		await get_tree().physics_frame
	var f: PackedStringArray = str(args.get("from", "1602.4,18.4,-1319.0")).split(",")
	var d: PackedStringArray = str(args.get("dir", "0.71,-0.06,-0.70")).split(",")
	var from := Vector3(float(f[0]), float(f[1]), float(f[2]))
	var dir := Vector3(float(d[0]), float(d[1]), float(d[2])).normalized()
	var space := get_viewport().world_3d.direct_space_state
	var origin := from
	print("ray from ", from, " dir ", dir)
	for hop in 6:
		var q := PhysicsRayQueryParameters3D.create(origin, origin + dir * 200.0)
		var hit := space.intersect_ray(q)
		if hit.is_empty():
			print("  hop %d: no hit" % hop)
			break
		var who: Node = hit.collider
		var path := str(who.get_parent().name) + "/" + str(who.name)
		print("  hop %d: %6.2f m  %-42s normal %s" % [hop, from.distance_to(hit.position), path, str(hit.normal).pad_decimals(2)])
		origin = hit.position + dir * 0.05
	get_tree().quit(0)
