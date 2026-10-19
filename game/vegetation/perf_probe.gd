extends Node
## Standalone FPS/perf check for the vegetation workstream, loading the real
## res://world/world.tscn (atmosphere + terrain + buildings + roads +
## vegetation) from a dense residential-canopy vantage -- lots of near-LOD
## trees, foundation shrubs, and near-camera grass all in view at once, the
## worst case for this workstream's draw calls. Must run with the real
## Vulkan renderer (NOT --headless):
##   flock .locks/gpu.lock godot --path game --resolution 1600x900 \
##     res://vegetation/perf_probe.tscn -- --season=summer --weather=clear --hour=12

const WARMUP_FRAMES := 120
const MEASURE_FRAMES := 180

var _frame_i := 0
var _t_start_usec := 0
var _cam: Camera3D


func _ready() -> void:
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else "true"
	var world: Node = preload("res://world/world.tscn").instantiate()
	world.set_meta("capture_mode", true)
	add_child(world)
	_cam = Camera3D.new()
	_cam.far = 4000.0
	add_child(_cam)
	# Default: residential street at eye height looking along a tree-lined
	# block (street trees, yard trees, foundation shrubs, near grass and the
	# impostor tier all in frame). The old S Hennepin vantage
	# (1723, 31.7, -585) ends up inside a house wall since the 2026-10 road
	# relayout. Override with --pos=x,y,z --look=x,y,z (e.g. the vantages in
	# captures/vegetation/lod/shots.json).
	var pos := _vec3_arg(args.get("pos", "2208,25.8,-876"))
	var look := _vec3_arg(args.get("look", "2277,22,-1064"))
	_cam.position = pos
	_cam.look_at(look, Vector3.UP)
	_cam.make_current()
	WorldState.apply_named(args.get("season", "summer"), args.get("weather", "clear"), float(args.get("hour", "12.0")))
	print("perf_probe(vegetation): warming up ", WARMUP_FRAMES, " frames...")


func _vec3_arg(v: String) -> Vector3:
	var p := v.split(",")
	return Vector3(float(p[0]), float(p[1]), float(p[2]))


func _process(_delta: float) -> void:
	_frame_i += 1
	if _frame_i == WARMUP_FRAMES:
		_t_start_usec = Time.get_ticks_usec()
		print("perf_probe(vegetation): measuring ", MEASURE_FRAMES, " frames...")
	elif _frame_i == WARMUP_FRAMES + MEASURE_FRAMES:
		var elapsed_sec := float(Time.get_ticks_usec() - _t_start_usec) / 1_000_000.0
		var avg_fps := float(MEASURE_FRAMES) / elapsed_sec
		var avg_ms := elapsed_sec * 1000.0 / float(MEASURE_FRAMES)
		print("perf_probe(vegetation): RESULT avg_fps=%.1f avg_frame_ms=%.2f (over %d frames, %.2fs)" % [avg_fps, avg_ms, MEASURE_FRAMES, elapsed_sec])
		get_tree().quit(0)
