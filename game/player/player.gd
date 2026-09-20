extends CharacterBody3D
## First-person player controller. See docs/player_notes.md for controls,
## the spawn list, and the capture_mode contract.
##
## Capture-mode contract (mirrors game/atmosphere/atmosphere.gd's
## `_is_capture_mode()`): the capture harness (game/tools/capture/capture_main.gd)
## instances a scene and calls `root.set_meta("capture_mode", true)` on that
## root BEFORE adding it to the tree, so by the time this node's `_ready()`
## runs (as a descendant of that root), walking up the parent chain finds the
## meta already set. When found: no mouse capture, camera never made current,
## no debug/noclip input handled -- the harness supplies its own camera and
## the player must not fight it for `get_viewport().get_camera_3d()`.

signal footstep(surface_type: String, global_pos: Vector3)

# preload (not the bare class_name) so this still resolves in a fresh
# headless run before the global class list has been scanned -- see
# docs/terrain_notes.md "How other systems sample terrain height".
const SpawnPoints = preload("res://player/spawn_points.gd")

const WALK_SPEED := 10.4
const RUN_SPEED := 30.5
const CROUCH_SPEED := 9.9
const JUMP_HEIGHT := 4.0
const GRAVITY := 9.8

const STAND_HEIGHT := 1.8
const CROUCH_HEIGHT := 1.1
const CAPSULE_RADIUS := 0.3
const EYE_HEIGHT_STAND := 1.7
const EYE_HEIGHT_CROUCH := 1.0
const CROUCH_LERP_SPEED := 8.0

const STEP_HEIGHT := 0.3
const FLOOR_MAX_ANGLE_DEG := 45.0

const GROUND_ACCEL := 12.0
const GROUND_DECEL := 14.0
const AIR_ACCEL := 4.0

const COYOTE_TIME := 0.12
const JUMP_BUFFER_TIME := 0.12

const BOB_WALK_FREQ := 1.8 # cycles per second-of-stride at walk speed
const BOB_AMPLITUDE := 0.035
const BOB_SIDE_AMPLITUDE := 0.02
const LANDING_DIP_MAX := 0.14
const LANDING_DIP_RECOVER := 9.0

const STRIDE_LENGTH := 1.5 # meters between footstep events

@export var mouse_sensitivity := 0.0025
@export var pitch_limit_deg := 89.0
@export var footstep_audio_enabled := true
@export_range(-40.0, 0.0) var footstep_volume_db := -20.0
@export var noclip_speed := 8.0

@onready var _collision: CollisionShape3D = $Collision
@onready var _head: Node3D = $Head
@onready var _camera: Camera3D = $Head/Camera3D
@onready var _footstep_player: AudioStreamPlayer3D = $Head/Footsteps

var _capture_mode := false
var _mouse_captured := false
var _noclip := false

var _yaw := 0.0
var _pitch := 0.0

var _crouching := false
var _current_height := STAND_HEIGHT
var _current_eye_height := EYE_HEIGHT_STAND

var _coyote_timer := 0.0
var _jump_buffer_timer := 0.0
var _space_was_pressed := false
var _f5_was_pressed := false
var _f6_was_pressed := false
var _was_on_floor := true
var _fall_speed_on_landing := 0.0

var _bob_phase := 0.0
var _landing_dip := 0.0
var _step_distance_accum := 0.0

var _debug_readout_visible := false
var _debug_label: Label

var _footstep_wave: AudioStreamWAV


func _ready() -> void:
	_capture_mode = _find_capture_mode()

	var shape := CapsuleShape3D.new()
	shape.radius = CAPSULE_RADIUS
	shape.height = STAND_HEIGHT
	_collision.shape = shape
	_collision.position = Vector3(0, STAND_HEIGHT * 0.5, 0)

	floor_max_angle = deg_to_rad(FLOOR_MAX_ANGLE_DEG)
	floor_stop_on_slope = true
	floor_block_on_wall = true
	floor_snap_length = 0.4
	safe_margin = 0.05

	_spawn_from_cmdline()

	_footstep_wave = _build_footstep_wave()
	_footstep_player.stream = _footstep_wave
	_footstep_player.volume_db = footstep_volume_db
	_footstep_player.unit_size = 2.0
	_footstep_player.max_distance = 15.0

	if not _capture_mode:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		_mouse_captured = true
		_camera.current = true
		_build_debug_label()
	else:
		_camera.current = false


func _find_capture_mode() -> bool:
	var n: Node = self
	while n:
		if n.has_meta("capture_mode"):
			return true
		n = n.get_parent()
	return false


func _spawn_from_cmdline() -> void:
	var spawn_name := SpawnPoints.spawn_from_cmdline()
	global_position = SpawnPoints.get_position(spawn_name)
	_yaw = SpawnPoints.get_yaw_rad(spawn_name)
	rotation.y = _yaw


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

func _unhandled_input(event: InputEvent) -> void:
	if _capture_mode:
		return
	if event is InputEventMouseButton and event.pressed and not _mouse_captured:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		_mouse_captured = true
	if event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
		_mouse_captured = false
	if event is InputEventMouseMotion and _mouse_captured:
		_yaw -= event.relative.x * mouse_sensitivity
		_pitch = clampf(_pitch - event.relative.y * mouse_sensitivity, deg_to_rad(-pitch_limit_deg), deg_to_rad(pitch_limit_deg))
		rotation.y = _yaw
		_head.rotation.x = _pitch


func _process(_delta: float) -> void:
	if _capture_mode:
		return
	# Debug toggles use F5/F6 -- NOT F1-F4, which are WorldState's season/
	# weather/hour debug keys owned by the atmosphere workstream (see
	# docs/atmosphere_notes.md and docs/player_notes.md "Debug keys").
	var f5 := Input.is_physical_key_pressed(KEY_F5)
	if f5 and not _f5_was_pressed:
		_noclip = not _noclip
		if _noclip:
			velocity = Vector3.ZERO
	_f5_was_pressed = f5

	var f6 := Input.is_physical_key_pressed(KEY_F6)
	if f6 and not _f6_was_pressed:
		_debug_readout_visible = not _debug_readout_visible
		if _debug_label:
			_debug_label.visible = _debug_readout_visible
	_f6_was_pressed = f6

	if _debug_readout_visible and _debug_label:
		_update_debug_label()


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------

func _physics_process(delta: float) -> void:
	if _capture_mode:
		return
	if _noclip:
		_physics_noclip(delta)
		return

	var crouch_held := Input.is_physical_key_pressed(KEY_CTRL)
	var run_held := Input.is_physical_key_pressed(KEY_SHIFT)
	_crouching = crouch_held
	_update_crouch(delta)

	var input_dir := Vector2.ZERO
	if Input.is_physical_key_pressed(KEY_W):
		input_dir.y -= 1.0
	if Input.is_physical_key_pressed(KEY_S):
		input_dir.y += 1.0
	if Input.is_physical_key_pressed(KEY_A):
		input_dir.x -= 1.0
	if Input.is_physical_key_pressed(KEY_D):
		input_dir.x += 1.0
	input_dir = input_dir.normalized()

	var speed := WALK_SPEED
	if _crouching:
		speed = CROUCH_SPEED
	elif run_held:
		speed = RUN_SPEED

	var basis := Basis(Vector3.UP, _yaw)
	var wish_dir := (basis * Vector3(input_dir.x, 0.0, input_dir.y))
	var wish_velocity := wish_dir * speed

	# Gravity.
	if not is_on_floor():
		velocity.y -= GRAVITY * delta

	# Coyote time + jump buffering.
	if is_on_floor():
		_coyote_timer = COYOTE_TIME
	else:
		_coyote_timer = maxf(_coyote_timer - delta, 0.0)

	var space := Input.is_physical_key_pressed(KEY_SPACE)
	if space and not _space_was_pressed:
		_jump_buffer_timer = JUMP_BUFFER_TIME
	_space_was_pressed = space
	_jump_buffer_timer = maxf(_jump_buffer_timer - delta, 0.0)

	if _jump_buffer_timer > 0.0 and _coyote_timer > 0.0 and not _crouching:
		var jump_velocity := sqrt(2.0 * GRAVITY * JUMP_HEIGHT)
		velocity.y = jump_velocity
		_jump_buffer_timer = 0.0
		_coyote_timer = 0.0

	# Horizontal accel/decel (smooth, a little more responsive in air).
	var accel := GROUND_ACCEL if is_on_floor() else AIR_ACCEL
	var decel := GROUND_DECEL if is_on_floor() else AIR_ACCEL
	var horizontal := Vector3(velocity.x, 0.0, velocity.z)
	if wish_velocity.length() > 0.01:
		horizontal = horizontal.move_toward(wish_velocity, accel * delta)
	else:
		horizontal = horizontal.move_toward(Vector3.ZERO, decel * delta)
	velocity.x = horizontal.x
	velocity.z = horizontal.z

	_try_step_up(delta, horizontal)

	if not _was_on_floor:
		_fall_speed_on_landing = maxf(_fall_speed_on_landing, -velocity.y)

	move_and_slide()

	if is_on_floor() and not _was_on_floor:
		_landing_dip = clampf(_fall_speed_on_landing * 0.018, 0.0, LANDING_DIP_MAX)
		_fall_speed_on_landing = 0.0
	_was_on_floor = is_on_floor()

	_update_head_bob(delta, horizontal.length())
	_maybe_footstep(delta, horizontal.length())


func _update_crouch(delta: float) -> void:
	var target_height := CROUCH_HEIGHT if _crouching else STAND_HEIGHT
	var target_eye := EYE_HEIGHT_CROUCH if _crouching else EYE_HEIGHT_STAND
	_current_height = move_toward(_current_height, target_height, CROUCH_LERP_SPEED * delta)
	_current_eye_height = move_toward(_current_eye_height, target_eye, CROUCH_LERP_SPEED * delta)
	if _collision.shape is CapsuleShape3D:
		(_collision.shape as CapsuleShape3D).height = _current_height
	_collision.position.y = _current_height * 0.5


## Pre-lifts the body over a low obstacle (curbs, small steps) directly ahead
## so move_and_slide() walks up it instead of colliding with its vertical
## face; the generous floor_snap_length set in _ready() then pulls the body
## back down onto the stepped-up surface within the same move_and_slide call.
func _try_step_up(delta: float, horizontal_velocity: Vector3) -> void:
	if not is_on_floor() or horizontal_velocity.length() < 0.05:
		return
	# Probe a SHORT fixed distance ahead, not the full per-frame motion.
	# Bug this fixes (user report: "crossing edges are elevated, I have to jump
	# over them"): the probe used to be velocity * delta. At the user's tuned
	# inspection speeds (walk 10.4, run 30.5 m/s) that is 0.17-0.51 m per tick,
	# so the "still blocked once lifted?" sweep reached geometry *past* the curb
	# and concluded "real wall, not a step" — every 15 cm curb and crossing edge
	# became unclimbable, while at the original 1.4 m/s (0.023 m probe) it worked.
	# A fixed probe makes curb stepping behave identically at any speed.
	var dir := horizontal_velocity.normalized()
	var probe_len: float = clampf(horizontal_velocity.length() * delta, 0.12, CAPSULE_RADIUS + 0.15)
	var probe := dir * probe_len
	if not test_move(global_transform, probe):
		return # nothing in the way; ordinary move handles it
	var lifted := global_transform
	lifted.origin.y += STEP_HEIGHT
	if test_move(lifted, Vector3.ZERO):
		return # can't even lift straight up (low ceiling) -- not a step
	if test_move(lifted, probe):
		return # still blocked once lifted -- a real wall, not a step
	global_position.y += STEP_HEIGHT


func _physics_noclip(delta: float) -> void:
	var input_dir := Vector2.ZERO
	if Input.is_physical_key_pressed(KEY_W):
		input_dir.y -= 1.0
	if Input.is_physical_key_pressed(KEY_S):
		input_dir.y += 1.0
	if Input.is_physical_key_pressed(KEY_A):
		input_dir.x -= 1.0
	if Input.is_physical_key_pressed(KEY_D):
		input_dir.x += 1.0
	var vertical := 0.0
	if Input.is_physical_key_pressed(KEY_SPACE):
		vertical += 1.0
	if Input.is_physical_key_pressed(KEY_CTRL):
		vertical -= 1.0
	input_dir = input_dir.normalized()
	var speed := noclip_speed * (2.5 if Input.is_physical_key_pressed(KEY_SHIFT) else 1.0)
	var basis := Basis(Vector3.UP, _yaw)
	var wish := (basis * Vector3(input_dir.x, 0.0, input_dir.y)) + Vector3.UP * vertical
	global_position += wish * speed * delta


# ---------------------------------------------------------------------------
# Head bob / landing dip (subtle -- purely cosmetic offsets on the Head node)
# ---------------------------------------------------------------------------

func _update_head_bob(delta: float, horizontal_speed: float) -> void:
	var moving := horizontal_speed > 0.1 and is_on_floor()
	if moving:
		_bob_phase += delta * BOB_WALK_FREQ * (horizontal_speed / WALK_SPEED)
	else:
		_bob_phase = lerp_angle(_bob_phase, 0.0, delta * 4.0)

	var bob_y := sin(_bob_phase * TAU) * BOB_AMPLITUDE * (1.0 if moving else 0.0)
	var bob_x := cos(_bob_phase * TAU * 0.5) * BOB_SIDE_AMPLITUDE * (1.0 if moving else 0.0)

	_landing_dip = move_toward(_landing_dip, 0.0, LANDING_DIP_RECOVER * delta)

	_head.position = Vector3(bob_x, _current_eye_height + bob_y - _landing_dip, 0.0)


# ---------------------------------------------------------------------------
# Footsteps: ground surface detection + placeholder procedural audio
# ---------------------------------------------------------------------------

func _maybe_footstep(delta: float, horizontal_speed: float) -> void:
	if not is_on_floor() or horizontal_speed < 0.1:
		_step_distance_accum = 0.0
		return
	_step_distance_accum += horizontal_speed * delta
	if _step_distance_accum < STRIDE_LENGTH:
		return
	_step_distance_accum = 0.0
	var surface_type := _detect_surface_type()
	footstep.emit(surface_type, global_position)
	_play_footstep_sound(surface_type)


## Casts straight down from the feet and classifies what's underneath.
## Priority: explicit `surface_type` metadata > `surface_<type>` group >
## sibling `Surf_<material_name>` MeshInstance3D (the naming convention
## game/roads/roads.tscn already uses) > a substring match on the collider's
## own node name > "generic". See docs/player_notes.md "Footstep surface
## convention" for how other workstreams can hook into this precisely.
func _detect_surface_type() -> String:
	var space_state := get_world_3d().direct_space_state
	var from := global_position + Vector3(0, 0.1, 0)
	var to := global_position + Vector3(0, -1.0, 0)
	var query := PhysicsRayQueryParameters3D.create(from, to)
	query.exclude = [self]
	var hit := space_state.intersect_ray(query)
	if hit.is_empty():
		return "generic"
	var collider: Object = hit.get("collider")
	if collider == null:
		return "generic"

	if collider is Node and (collider as Node).has_meta("surface_type"):
		return str((collider as Node).get_meta("surface_type"))

	if collider is Node:
		for g in (collider as Node).get_groups():
			var group_name := String(g)
			if group_name.begins_with("surface_"):
				return group_name.trim_prefix("surface_")

	if collider is Node:
		var parent := (collider as Node).get_parent()
		if parent:
			var hit_pos: Vector3 = hit.get("position", global_position)
			var best_name := ""
			var best_dist := INF
			for child in parent.get_children():
				if child is MeshInstance3D and String(child.name).begins_with("Surf_"):
					var mesh_aabb := (child as MeshInstance3D).get_aabb()
					var center := (child as MeshInstance3D).global_transform * mesh_aabb.get_center()
					var d := Vector2(center.x, center.z).distance_to(Vector2(hit_pos.x, hit_pos.z))
					if d < best_dist:
						best_dist = d
						best_name = String(child.name).trim_prefix("Surf_")
			if best_name != "":
				return _surface_key_from_material_name(best_name)

	if collider is Node:
		var n := String((collider as Node).name).to_lower()
		for key in ["bridge", "sidewalk", "curb", "asphalt", "road", "water", "wood", "gravel", "stone", "grass"]:
			if n.find(key) != -1:
				return key
	return "generic"


static func _surface_key_from_material_name(mat_name: String) -> String:
	var n := mat_name.to_lower()
	if n.find("concrete") != -1:
		return "concrete"
	if n.find("asphalt") != -1:
		return "asphalt"
	if n.find("gravel") != -1:
		return "gravel"
	if n.find("wood") != -1:
		return "wood"
	if n.find("grass") != -1:
		return "grass"
	if n.find("dirt") != -1 or n.find("mud") != -1:
		return "dirt"
	if n.find("stone") != -1 or n.find("rock") != -1:
		return "stone"
	return n


## Placeholder step sound -- a short procedurally generated noise click, not
## a real footstep foley set. Quiet by default (footstep_volume_db=-20) and
## can be disabled entirely via footstep_audio_enabled. Real per-surface
## audio can replace this by connecting to the `footstep` signal or swapping
## `_footstep_player.stream` per surface_type.
func _play_footstep_sound(surface_type: String) -> void:
	if not footstep_audio_enabled or _footstep_player == null:
		return
	# Slight per-surface + per-step variation so it doesn't read as a metronome.
	var pitch := randf_range(0.92, 1.08)
	match surface_type:
		"concrete", "asphalt", "stone", "bridge":
			pitch *= 1.1
		"grass", "dirt", "gravel":
			pitch *= 0.9
	_footstep_player.pitch_scale = pitch
	_footstep_player.volume_db = footstep_volume_db
	_footstep_player.play()


## Builds a ~45ms noise burst with a fast exponential decay envelope -- a
## generic "click/step" placeholder, no audio assets required. 16-bit mono
## PCM at 22.05kHz is plenty for something this short and quiet.
func _build_footstep_wave() -> AudioStreamWAV:
	var sample_rate := 22050
	var length_s := 0.045
	var sample_count := int(sample_rate * length_s)
	var data := PackedByteArray()
	data.resize(sample_count * 2)
	var rng := RandomNumberGenerator.new()
	rng.seed = 1337
	for i in sample_count:
		var t := float(i) / float(sample_count)
		var envelope := exp(-t * 14.0)
		var sample := rng.randf_range(-1.0, 1.0) * envelope
		var v := int(clampf(sample, -1.0, 1.0) * 32767.0)
		data.encode_s16(i * 2, v)
	var wav := AudioStreamWAV.new()
	wav.format = AudioStreamWAV.FORMAT_16_BITS
	wav.mix_rate = sample_rate
	wav.stereo = false
	wav.data = data
	return wav


# ---------------------------------------------------------------------------
# Debug readout (F6) -- position, FPS, season/weather/hour. Off by default,
# never shown in capture mode.
# ---------------------------------------------------------------------------

func _build_debug_label() -> void:
	var ui := CanvasLayer.new()
	_debug_label = Label.new()
	_debug_label.position = Vector2(12, 40)
	_debug_label.visible = false
	_debug_label.add_theme_color_override("font_color", Color(1, 1, 1))
	_debug_label.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.85))
	_debug_label.add_theme_constant_override("shadow_offset_x", 1)
	_debug_label.add_theme_constant_override("shadow_offset_y", 1)
	ui.add_child(_debug_label)
	add_child(ui)


func _update_debug_label() -> void:
	# WorldState is an autoload, always available at runtime.
	var season_name: String = WorldState.Season.keys()[WorldState.season]
	var weather_name: String = WorldState.Weather.keys()[WorldState.weather]
	_debug_label.text = "pos %.1f, %.1f, %.1f  |  %d fps  |  %s / %s / %02d:%02d  (F5 noclip%s · F6 hide)" % [
		global_position.x, global_position.y, global_position.z,
		Engine.get_frames_per_second(),
		season_name, weather_name,
		int(WorldState.hour), int(fmod(WorldState.hour, 1.0) * 60.0),
		" [ON]" if _noclip else "",
	]
