extends Node
## Standalone FPS probe for the terrain workstream, mirroring atmosphere's
## perf_probe.tscn pattern. Warms up, then measures N frames of real
## Vulkan rendering (must NOT run under --headless) and prints avg fps.
## Usage: flock .locks/gpu.lock godot --path game --resolution 1600x900 \
##   res://terrain/perf_probe.tscn -- --pos=1650,9.6,-1555 --look_at=1512,11,-1700

const WARMUP := 120
const MEASURE := 180

var _frame := 0
var _times: Array[float] = []
var _cam: Camera3D

func _ready() -> void:
	add_child((load("res://atmosphere/atmosphere.tscn") as PackedScene).instantiate())
	var terrain = (load("res://terrain/terrain.tscn") as PackedScene).instantiate()
	add_child(terrain)
	_cam = Camera3D.new()
	_cam.far = 4000.0
	add_child(_cam)
	_cam.global_position = Vector3(2180.0, 43.1, -1170.0)
	_cam.look_at(Vector3(1850.0, 5.0, -1350.0))
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
