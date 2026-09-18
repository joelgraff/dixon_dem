extends Node3D
## Standalone terrain/water test scene: instances atmosphere.tscn (lighting/sky/
## weather rig) + terrain.tscn, and adds a free-fly camera + on-screen debug
## readout (FPS, build perf, current WorldState) for interactive review.
## Captured via game/tools/capture.sh like any other scene -- the capture
## harness adds/overrides its own Camera3D, so this scene's own camera and
## input handling stay dormant (see _is_capture_mode()).

const MOVE_SPEED := 8.0
const SPRINT_MULT := 3.0
const LOOK_SENSITIVITY := 0.0025

var terrain: Node3D
var cam: Camera3D
var debug_label: Label
var _yaw := 0.0
var _pitch := 0.0
var _mouse_captured := false

func _is_capture_mode() -> bool:
	return has_meta("capture_mode")

func _ready() -> void:
	if ResourceLoader.exists("res://atmosphere/atmosphere.tscn"):
		add_child((load("res://atmosphere/atmosphere.tscn") as PackedScene).instantiate())

	terrain = (load("res://terrain/terrain.tscn") as PackedScene).instantiate()
	add_child(terrain)

	cam = Camera3D.new()
	cam.name = "FlyCam"
	# Riverfront near the Lincoln statue, eye height -- a reasonable default
	# interactive start; capture.sh overrides position/look_at per shot anyway.
	cam.position = Vector3(1387.8, 9.5, -1700.0)
	_yaw = deg_to_rad(200.0)
	cam.rotation = Vector3(0, _yaw, 0)
	cam.far = 12000.0
	add_child(cam)
	if not _is_capture_mode():
		cam.make_current()

	if not _is_capture_mode():
		var ui := CanvasLayer.new()
		debug_label = Label.new()
		debug_label.position = Vector2(12, 8)
		debug_label.add_theme_color_override("font_color", Color(1, 1, 1))
		debug_label.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.85))
		debug_label.add_theme_constant_override("shadow_offset_x", 1)
		debug_label.add_theme_constant_override("shadow_offset_y", 1)
		ui.add_child(debug_label)
		add_child(ui)
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		_mouse_captured = true

func _unhandled_input(event: InputEvent) -> void:
	if _is_capture_mode():
		return
	if event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		_mouse_captured = true
	if event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
		_mouse_captured = false
	if event is InputEventMouseMotion and _mouse_captured:
		_yaw -= event.relative.x * LOOK_SENSITIVITY
		_pitch = clamp(_pitch - event.relative.y * LOOK_SENSITIVITY, -1.5, 1.5)
		cam.rotation = Vector3(_pitch, _yaw, 0)

func _process(delta: float) -> void:
	if _is_capture_mode():
		return
	var dir := Vector3.ZERO
	if Input.is_key_pressed(KEY_W): dir -= cam.transform.basis.z
	if Input.is_key_pressed(KEY_S): dir += cam.transform.basis.z
	if Input.is_key_pressed(KEY_A): dir -= cam.transform.basis.x
	if Input.is_key_pressed(KEY_D): dir += cam.transform.basis.x
	if Input.is_key_pressed(KEY_Q): dir -= Vector3.UP
	if Input.is_key_pressed(KEY_E): dir += Vector3.UP
	var speed := MOVE_SPEED * (SPRINT_MULT if Input.is_key_pressed(KEY_SHIFT) else 1.0)
	if dir.length() > 0.0:
		cam.position += dir.normalized() * speed * delta

	if debug_label:
		var fps := Engine.get_frames_per_second()
		var season_name: String = WorldState.Season.keys()[WorldState.season]
		var weather_name: String = WorldState.Weather.keys()[WorldState.weather]
		debug_label.text = "FPS %d  |  %s/%s %02d:00  |  build: %s  |  WASD+mouse fly, Q/E up/down, Shift sprint, F1-F4 season/weather/hour (atmosphere), Esc release mouse" % [
			fps, season_name, weather_name, int(WorldState.hour), str(terrain.perf)
		]
