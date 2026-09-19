extends Node
## Standalone FPS/perf check for the buildings workstream, loading the real
## res://world/world.tscn (atmosphere + terrain + buildings, whole play area)
## from a dense downtown vantage point -- the worst case for building draw
## calls/materials (many chunks, storefront windows, cornices in view at once).
## Must run with the real Vulkan renderer (NOT --headless):
##   flock .locks/gpu.lock godot --path game --resolution 1600x900 \
##     res://buildings/perf_probe.tscn -- --season=winter --weather=snow --hour=21
## (winter dusk/night exercises SDFGI + snow response + lit windows together.)

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
	# North Galena Ave looking south into downtown -- long sightline down a
	# dense row of storefronts, the heaviest near-LOD case in the scene.
	_cam.position = Vector3(1541.4, 8.35, -1526.8)
	_cam.look_at(Vector3(1610.3, 21.94, -1284.4), Vector3.UP)
	_cam.make_current()
	WorldState.apply_named(args.get("season", "winter"), args.get("weather", "snow"), float(args.get("hour", "21.0")))
	print("perf_probe(buildings): warming up ", WARMUP_FRAMES, " frames...")

func _process(_delta: float) -> void:
	_frame_i += 1
	if _frame_i == WARMUP_FRAMES:
		_t_start_usec = Time.get_ticks_usec()
		print("perf_probe(buildings): measuring ", MEASURE_FRAMES, " frames...")
	elif _frame_i == WARMUP_FRAMES + MEASURE_FRAMES:
		var elapsed_sec := float(Time.get_ticks_usec() - _t_start_usec) / 1_000_000.0
		var avg_fps := float(MEASURE_FRAMES) / elapsed_sec
		var avg_ms := elapsed_sec * 1000.0 / float(MEASURE_FRAMES)
		print("perf_probe(buildings): RESULT avg_fps=%.1f avg_frame_ms=%.2f (over %d frames, %.2fs)" % [avg_fps, avg_ms, MEASURE_FRAMES, elapsed_sec])
		get_tree().quit(0)
