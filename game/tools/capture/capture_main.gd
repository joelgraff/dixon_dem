extends Node
## Screenshot harness. Usage (via tools/capture.sh):
##   --scene=res://path.tscn --shots=/abs/shots.json --out=/abs/dir [--warmup=90]
## shots.json: [{"name":"x","pos":[x,y,z],"look_at":[x,y,z],"fov":70,
##               "season":"summer","weather":"clear","hour":12.0,
##               "wetness_override":0.5,"snow_cover_override":0.0}]
## wetness_override/snow_cover_override are optional and applied AFTER
## WorldState.apply_named() for that shot, so season/weather/hour can stay fixed
## (same sun/exposure) while isolating just the wetness or snow_cover global — needed to
## prove a weather-reactive shader response without confounding it with a lighting
## change. Omit them to use whatever the weather preset implies (unchanged behavior).
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
	# Timing instrumentation: world build/load dominates capture cost, so report it separately
	# from per-shot warmup cost. Use these numbers before tuning warmup or the capture.sh timeout.
	var t_start := Time.get_ticks_msec()
	var root: Node = load(scene_path).instantiate()
	# Let scenes know they are being captured (e.g. player controller should not grab the camera/mouse).
	root.set_meta("capture_mode", true)
	add_child(root)
	# Wait for deferred world build (terrain chunks, road/building bakes) to settle before timing shots.
	await get_tree().process_frame
	await get_tree().process_frame
	print("capture: scene load+instantiate %.1f s" % ((Time.get_ticks_msec() - t_start) / 1000.0))
	# --hide=NodeA,NodeB : hide top-level systems (Terrain, Roads, Buildings, ...) for diagnosis,
	# e.g. to tell "this surface is terrain" from "the road mesh is missing here".
	if _args.has("hide"):
		for n in str(_args["hide"]).split(","):
			var node := root.find_child(n, true, false)
			if node and node is Node3D:
				(node as Node3D).visible = false
				print("capture: hid node ", n)
			else:
				push_warning("capture: --hide node not found: " + n)
	# --no-lod : clear visibility_range on every GeometryInstance3D. Diagnostic for "geometry
	# exists but doesn't render" bugs: chunk meshes are baked with world-space vertices and NO
	# node transform, so if LOD distance is evaluated from the node origin rather than the mesh
	# bounds, whole chunks cull by their distance from (0,0,0) instead of from the camera.
	if _args.has("no-lod"):
		var cleared := 0
		for n in _all_nodes(root):
			if n is GeometryInstance3D:
				var g := n as GeometryInstance3D
				if g.visibility_range_end > 0.0 or g.visibility_range_begin > 0.0:
					g.visibility_range_begin = 0.0
					g.visibility_range_end = 0.0
					cleared += 1
		print("capture: cleared visibility_range on ", cleared, " instances")
	# --override=<Node>[:double] : replace every material under <Node> with a plain
	# white StandardMaterial3D (optionally cull_disabled). Diagnostic for
	# "is this geometry missing, or present but not rendering?" -- if a facade
	# appears under a double-sided override, the wall exists and the problem is
	# culling/material, not generation.
	if _args.has("override"):
		var spec: PackedStringArray = str(_args["override"]).split(":")
		var target := root.find_child(spec[0], true, false)
		var dbl := spec.size() > 1 and spec[1] == "double"
		var m := StandardMaterial3D.new()
		m.albedo_color = Color(0.8, 0.8, 0.82)
		m.roughness = 0.9
		if dbl:
			m.cull_mode = BaseMaterial3D.CULL_DISABLED
		var n_over := 0
		if target:
			for nd in _all_nodes(target):
				if nd is MeshInstance3D:
					(nd as MeshInstance3D).material_override = m
					n_over += 1
		print("capture: material_override on %d MeshInstance3D under %s (double=%s)" % [n_over, spec[0], dbl])
	var cam := Camera3D.new()
	add_child(cam)
	for s in shots:
		var t_shot := Time.get_ticks_msec()
		WorldState.apply_named(s.get("season", "summer"), s.get("weather", "clear"), float(s.get("hour", 12.0)))
		if s.has("wetness_override"):
			RenderingServer.global_shader_parameter_set("wetness", float(s["wetness_override"]))
		if s.has("snow_cover_override"):
			RenderingServer.global_shader_parameter_set("snow_cover", float(s["snow_cover_override"]))
		var p: Array = s["pos"]; var t: Array = s["look_at"]
		# "eye": true -> put the camera at ground + eye_height (default 1.7 m) at
		# this x/z, and aim at ground + eye height too. Hand-guessed Y values put
		# several diagnostic shots BELOW the terrain, which renders the ground from
		# underneath as a flat pale sheet and looks exactly like a giant misplaced
		# plane -- two wrong diagnoses came from that before this existed.
		if bool(s.get("eye", false)):
			var eye_h := float(s.get("eye_height", 1.7))
			p = [p[0], _ground_y(float(p[0]), float(p[2])) + eye_h, p[2]]
			t = [t[0], _ground_y(float(t[0]), float(t[2])) + eye_h, t[2]]
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
		print("capture: saved %s (%.1f s)" % [path, (Time.get_ticks_msec() - t_shot) / 1000.0])
	print("capture: total %.1f s for %d shot(s)" % [(Time.get_ticks_msec() - t_start) / 1000.0, shots.size()])
	get_tree().quit(0)

func _all_nodes(n: Node, acc: Array = []) -> Array:
	acc.append(n)
	for c in n.get_children():
		_all_nodes(c, acc)
	return acc


## Raycasts down onto world collision to find the ground at (x, z).
## Falls back to 0 if nothing is hit (caller is then outside the collidable world).
func _ground_y(x: float, z: float) -> float:
	var space := get_viewport().world_3d.direct_space_state
	var q := PhysicsRayQueryParameters3D.create(Vector3(x, 400.0, z), Vector3(x, -100.0, z))
	var hit := space.intersect_ray(q)
	if hit.is_empty():
		push_warning("capture: no ground under (%f, %f)" % [x, z])
		return 0.0
	return hit.position.y
