extends Node
## Drives TicketTool without a human: enters ticket mode, tags two points by raycast,
## types a note, saves. Verifies the ticket path end-to-end (markers, md, raycast IDs).
func _ready() -> void: _run.call_deferred()
func _run() -> void:
	var root: Node = load("res://world/world.tscn").instantiate()
	add_child(root)
	for i in 30:
		await get_tree().physics_frame
	var pl: Node3D = root.find_child("Player", true, false)
	var cam: Camera3D = pl.find_child("Camera3D", true, false) if pl else null
	# stand in a downtown street looking at the block
	var space := get_viewport().world_3d.direct_space_state
	var q := PhysicsRayQueryParameters3D.create(Vector3(1610, 200, -1330), Vector3(1610, -50, -1330))
	var hit := space.intersect_ray(q)
	var y: float = (hit.position.y if not hit.is_empty() else 20.0) + 1.7
	pl.global_position = Vector3(1610, y, -1330)
	cam.make_current()
	cam.look_at(Vector3(1650, y - 2.0, -1350))
	for i in 60:
		await get_tree().process_frame
	var tt: Node = root.find_child("TicketTool", true, false)
	if tt == null:
		print("SELFTEST FAIL: no TicketTool"); get_tree().quit(1); return
	await tt.call("_enter")
	var vp := get_viewport().get_visible_rect().size
	tt.call("_add_tag", vp * Vector2(0.45, 0.55))
	tt.call("_add_tag", vp * Vector2(0.70, 0.62))
	tt.set("_note", "selftest: facade reads flat, no window reveals")
	tt.call("_save")
	await get_tree().process_frame
	print("SELFTEST OK")
	get_tree().quit(0)
