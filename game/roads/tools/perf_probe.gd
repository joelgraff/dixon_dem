extends Node
## Standalone FPS probe for the roads workstream (mirrors terrain's
## perf_probe.gd pattern). Loads the full composed world (atmosphere +
## terrain + buildings + roads) at a busy downtown street-level viewpoint.
## Must NOT run under --headless (needs real Vulkan rendering).
## Usage: flock .locks/gpu.lock godot --path game --resolution 1600x900 \
##   res://roads/tools/perf_probe.tscn

const WARMUP := 120
const MEASURE := 180

var _frame := 0
var _times: Array[float] = []
var _cam: Camera3D

func _ready() -> void:
	var world = (load("res://world/world.tscn") as PackedScene).instantiate()
	add_child(world)
	_cam = Camera3D.new()
	_cam.far = 4000.0
	add_child(_cam)
	_cam.global_position = Vector3(1580.0, 15.97, -1391.4)
	_cam.look_at(Vector3(1512.0, 12.0, -1650.0))
	_cam.make_current()
	Engine.max_fps = 0
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)

func _process(_delta: float) -> void:
	_frame += 1
	if _frame > WARMUP:
		_times.append(Time.get_ticks_usec() / 1000000.0)
		if _times.size() >= MEASURE:
			var total := _times[_times.size() - 1] - _times[0]
			var avg_fps := float(MEASURE - 1) / total
			print("PERF: avg_fps=%.1f  avg_frame_ms=%.2f  frames=%d" % [avg_fps, 1000.0 / avg_fps, MEASURE])
			get_tree().quit(0)
