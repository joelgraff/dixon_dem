extends Node
## Standalone FPS/perf check for the atmosphere rig. Must run with the real
## Vulkan renderer (NOT --headless, which swaps in a null renderer and would
## make the numbers meaningless) — same GPU-lock pattern as tools/capture.sh:
##   flock .locks/gpu.lock godot --path game --resolution 1600x900 \
##     res://atmosphere/perf_probe.tscn -- --season=winter --weather=blizzard --hour=13
## (blizzard is the worst case: SDFGI + volumetric fog + max particle counts.)
## Warms up, then measures over MEASURE_FRAMES and prints avg FPS / frame time.

const WARMUP_FRAMES := 120
const MEASURE_FRAMES := 180

var _frame_i := 0
var _t_start_usec := 0
var _cam: Camera3D

func _ready() -> void:
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else "true"
	var diorama: Node = preload("res://atmosphere/test_diorama.tscn").instantiate()
	diorama.set_meta("capture_mode", true) # suppress debug UI/keys, matches capture.sh runs
	add_child(diorama)
	_cam = Camera3D.new()
	_cam.position = Vector3(0, 1.7, 10)
	_cam.look_at(Vector3(0, 1.5, -200), Vector3.UP)
	_cam.far = 4000.0
	add_child(_cam)
	_cam.make_current()
	WorldState.apply_named(args.get("season", "winter"), args.get("weather", "blizzard"), float(args.get("hour", "13.0")))
	print("perf_probe: warming up ", WARMUP_FRAMES, " frames...")

func _process(_delta: float) -> void:
	_frame_i += 1
	if _frame_i == WARMUP_FRAMES:
		_t_start_usec = Time.get_ticks_usec()
		print("perf_probe: measuring ", MEASURE_FRAMES, " frames...")
	elif _frame_i == WARMUP_FRAMES + MEASURE_FRAMES:
		var elapsed_sec := float(Time.get_ticks_usec() - _t_start_usec) / 1_000_000.0
		var avg_fps := float(MEASURE_FRAMES) / elapsed_sec
		var avg_ms := elapsed_sec * 1000.0 / float(MEASURE_FRAMES)
		print("perf_probe: RESULT avg_fps=%.1f avg_frame_ms=%.2f (over %d frames, %.2fs)" % [avg_fps, avg_ms, MEASURE_FRAMES, elapsed_sec])
		get_tree().quit(0)
