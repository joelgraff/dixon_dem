extends Node3D
## Dixon — atmosphere / lighting / sky / weather rig.
## Instance res://atmosphere/atmosphere.tscn once per scene. Everything (sun/moon
## position, sky, fog, clouds, weather particles, night_factor) is driven from
## WorldState every frame — no per-scene setup required beyond instancing this.
##
## Built procedurally in _ready() rather than hand-authored as scene resources,
## so the whole rig lives in one reviewable, tunable file. See docs/atmosphere_notes.md.

const LATITUDE_DEG := 41.84
const SKY_SHADER := preload("res://atmosphere/shaders/sky.gdshader")

# -- weather profiles: sky/fog targets the rig blends towards -----------------
# cloud_coverage/darkness feed the sky shader; fog_density/visibility drive
# volumetric + depth fog; shadow_opacity softens shadows under heavy cloud;
# precip selects which particle systems run.
var weather_profiles := {}
var season_profiles := {}

var sun: DirectionalLight3D
var moon: DirectionalLight3D
var world_env: WorldEnvironment
var weather_rig: Node3D
var ground_collider: GPUParticlesCollisionHeightField3D
var rain_streaks: GPUParticles3D
var rain_splashes: GPUParticles3D
var snow_particles: GPUParticles3D
var mist_particles: GPUParticles3D
var debug_label: Label

var _env: Environment
var _sky_material: ShaderMaterial
var _time_accum := 0.0
var _blend := {} # smoothed weather-profile values
var _cur := {}   # this-frame computed sun/moon state, read by _update_environment

func _ready() -> void:
	_build_profiles()
	_build_rig()
	_env = world_env.environment
	_sky_material = _env.sky.sky_material as ShaderMaterial
	WorldState.changed.connect(_on_world_state_changed)
	_on_world_state_changed()
	# First frame: snap instead of smoothing in from zero.
	_update_sun_moon()
	_update_environment(1000.0)
	_update_particles(0.0)
	_update_debug_ui()

func _is_capture_mode() -> bool:
	var n: Node = self
	while n:
		if n.has_meta("capture_mode"):
			return true
		n = n.get_parent()
	return false

func _on_world_state_changed() -> void:
	_update_debug_ui()

func _process(delta: float) -> void:
	_time_accum += delta
	_update_sun_moon()
	_update_environment(delta)
	_update_particles(delta)
	if not _is_capture_mode():
		_update_debug_ui()

func _unhandled_key_input(event: InputEvent) -> void:
	if _is_capture_mode():
		return
	if not (event is InputEventKey) or not event.pressed or event.echo:
		return
	var key: int = event.keycode
	if key == KEY_F1:
		var next_season: int = (WorldState.season + 1) % 4
		WorldState.apply(next_season, WorldState.weather, WorldState.hour)
	elif key == KEY_F2:
		var next_weather: int = (WorldState.weather + 1) % 6
		WorldState.apply(WorldState.season, next_weather, WorldState.hour)
	elif key == KEY_F3:
		WorldState.apply(WorldState.season, WorldState.weather, fposmod(WorldState.hour - 0.5, 24.0))
	elif key == KEY_F4:
		WorldState.apply(WorldState.season, WorldState.weather, fposmod(WorldState.hour + 0.5, 24.0))

# ---------------------------------------------------------------------------
# Solar / lunar position — real formula for latitude 41.84N, ignores equation
# of time & longitude correction (a few minutes of error, invisible at game scale).
# ---------------------------------------------------------------------------
func _solar_position(p_day_of_year: int, p_hour: float) -> Dictionary:
	var lat := deg_to_rad(LATITUDE_DEG)
	var decl := deg_to_rad(23.44) * sin(TAU * float(p_day_of_year - 81) / 365.0)
	var hour_angle := deg_to_rad(15.0 * (p_hour - 12.0))
	var sin_alt := sin(lat) * sin(decl) + cos(lat) * cos(decl) * cos(hour_angle)
	sin_alt = clamp(sin_alt, -1.0, 1.0)
	var alt := asin(sin_alt)
	var cos_az := (sin(decl) - sin(alt) * sin(lat)) / maxf(cos(alt) * cos(lat), 0.0001)
	cos_az = clamp(cos_az, -1.0, 1.0)
	var az := acos(cos_az)
	if hour_angle > 0.0:
		az = TAU - az
	return {"elevation": alt, "azimuth": az}

## +X = east, +Y = up, -Z = north (project convention). az is compass bearing
## from north, clockwise through east.
func _dir_from_elev_az(elev: float, az: float) -> Vector3:
	return Vector3(cos(elev) * sin(az), sin(elev), -cos(elev) * cos(az)).normalized()

func _point_light_along(light: DirectionalLight3D, dir_to_source: Vector3) -> void:
	light.global_position = dir_to_source * 100.0
	var up := Vector3.UP if absf(dir_to_source.y) < 0.999 else Vector3.FORWARD
	light.look_at(Vector3.ZERO, up)

func _update_sun_moon() -> void:
	var s := _solar_position(WorldState.day_of_year, WorldState.hour)
	var sun_dir := _dir_from_elev_az(s.elevation, s.azimuth)
	_point_light_along(sun, sun_dir)

	var elev_deg := rad_to_deg(s.elevation)
	var sun_energy: float = clamp(inverse_lerp(-6.0, 15.0, elev_deg), 0.0, 1.0)
	sun_energy = ease(sun_energy, 1.6) * 2.6
	sun.light_energy = sun_energy

	var warm := Color(1.0, 0.55, 0.28)
	var neutral := Color(1.0, 0.97, 0.92)
	var color_t: float = clamp(inverse_lerp(-2.0, 25.0, elev_deg), 0.0, 1.0)
	sun.light_color = warm.lerp(neutral, color_t)

	# Moon: simplified as anti-sun (opposite side of sky) with a slow pseudo-phase
	# for brightness variation. Good enough for readable night ambience; not a
	# real ephemeris.
	var moon_s := _solar_position(WorldState.day_of_year, fposmod(WorldState.hour + 12.0, 24.0))
	var moon_dir := _dir_from_elev_az(moon_s.elevation, moon_s.azimuth)
	_point_light_along(moon, moon_dir)
	var moon_elev_deg := rad_to_deg(moon_s.elevation)
	var phase: float = absf(sin(TAU * float(WorldState.day_of_year) / 29.53))
	var moon_vis: float = clamp(inverse_lerp(-4.0, 8.0, moon_elev_deg), 0.0, 1.0)
	moon.light_energy = moon_vis * lerp(0.02, 0.16, phase) * (1.0 - sun_energy * 0.9)
	moon.light_color = Color(0.65, 0.72, 0.85)

	var night_factor: float = clamp(inverse_lerp(-2.0, -10.0, elev_deg), 0.0, 1.0)
	RenderingServer.global_shader_parameter_set("night_factor", night_factor)

	_cur["sun_dir"] = sun_dir
	_cur["moon_dir"] = moon_dir
	_cur["sun_energy"] = sun_energy
	_cur["moon_energy"] = moon.light_energy
	_cur["night_factor"] = night_factor
	_cur["elev_deg"] = elev_deg
	_cur["day_t"] = clamp(inverse_lerp(-8.0, 8.0, elev_deg), 0.0, 1.0)

func _build_profiles() -> void:
	weather_profiles = {
		WorldState.Weather.CLEAR: {"cloud_coverage": 0.28, "cloud_darkness": 0.05, "fog_density": 0.0015, "visibility": 5000.0, "shadow_opacity": 1.0, "precip": 0.0, "aerial": 0.2, "sky_affect": 0.3},
		WorldState.Weather.OVERCAST: {"cloud_coverage": 0.95, "cloud_darkness": 0.55, "fog_density": 0.004, "visibility": 2600.0, "shadow_opacity": 0.55, "precip": 0.0, "aerial": 0.35, "sky_affect": 0.6},
		WorldState.Weather.RAIN: {"cloud_coverage": 0.98, "cloud_darkness": 0.72, "fog_density": 0.007, "visibility": 1400.0, "shadow_opacity": 0.35, "precip": 1.0, "aerial": 0.45, "sky_affect": 0.75},
		WorldState.Weather.SNOW: {"cloud_coverage": 0.9, "cloud_darkness": 0.35, "fog_density": 0.006, "visibility": 1200.0, "shadow_opacity": 0.45, "precip": 0.55, "aerial": 0.45, "sky_affect": 0.7},
		WorldState.Weather.BLIZZARD: {"cloud_coverage": 1.0, "cloud_darkness": 0.6, "fog_density": 0.055, "visibility": 70.0, "shadow_opacity": 0.15, "precip": 1.0, "aerial": 0.75, "sky_affect": 1.0},
		WorldState.Weather.FOG: {"cloud_coverage": 0.6, "cloud_darkness": 0.2, "fog_density": 0.024, "visibility": 200.0, "shadow_opacity": 0.5, "precip": 0.0, "aerial": 0.65, "sky_affect": 1.0},
	}
	season_profiles = {
		WorldState.Season.SPRING: {"saturation": 0.95, "haze": 0.3, "tint": Color(0.94, 0.98, 0.99)},
		WorldState.Season.SUMMER: {"saturation": 1.0, "haze": 0.45, "tint": Color(1.0, 0.98, 0.9)},
		WorldState.Season.AUTUMN: {"saturation": 0.92, "haze": 0.28, "tint": Color(0.98, 0.9, 0.78)},
		WorldState.Season.WINTER: {"saturation": 0.82, "haze": 0.15, "tint": Color(0.86, 0.91, 1.0)},
	}

# ---------------------------------------------------------------------------
# Procedural rig construction — building this in code (rather than as .tscn
# sub-resources) keeps the whole rig reviewable/tunable in one file.
# ---------------------------------------------------------------------------
func _build_rig() -> void:
	sun = DirectionalLight3D.new()
	sun.name = "Sun"
	sun.shadow_enabled = true
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_4_SPLITS
	sun.directional_shadow_max_distance = 400.0
	sun.directional_shadow_split_1 = 0.05
	sun.directional_shadow_split_2 = 0.15
	sun.directional_shadow_split_3 = 0.35
	sun.directional_shadow_blend_splits = true
	sun.directional_shadow_fade_start = 0.85
	sun.shadow_blur = 1.4
	sun.sky_mode = DirectionalLight3D.SKY_MODE_LIGHT_ONLY
	add_child(sun)

	moon = DirectionalLight3D.new()
	moon.name = "Moon"
	moon.shadow_enabled = true
	moon.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_2_SPLITS
	moon.directional_shadow_max_distance = 250.0
	moon.shadow_blur = 2.5
	moon.sky_mode = DirectionalLight3D.SKY_MODE_LIGHT_ONLY
	add_child(moon)

	world_env = WorldEnvironment.new()
	world_env.name = "WorldEnvironment"
	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	var sky := Sky.new()
	var sky_mat := ShaderMaterial.new()
	sky_mat.shader = SKY_SHADER
	sky.sky_material = sky_mat
	sky.radiance_size = Sky.RADIANCE_SIZE_256
	env.sky = sky
	env.sdfgi_enabled = true
	env.sdfgi_cascades = 3
	env.sdfgi_min_cell_size = 0.3
	env.sdfgi_max_distance = 220.0
	env.sdfgi_use_occlusion = true
	env.sdfgi_energy = 1.0
	env.sdfgi_bounce_feedback = 0.4
	env.sdfgi_read_sky_light = true
	env.ssao_enabled = true
	env.ssao_intensity = 1.6
	env.ssao_power = 1.4
	env.ssao_radius = 1.0
	env.ssil_enabled = true
	env.ssil_intensity = 1.4
	env.ssil_radius = 4.0
	world_env.environment = env
	add_child(world_env)

	weather_rig = Node3D.new()
	weather_rig.name = "WeatherRig"
	add_child(weather_rig)

	ground_collider = GPUParticlesCollisionHeightField3D.new()
	ground_collider.name = "GroundCollider"
	ground_collider.size = Vector3(60.0, 40.0, 60.0)
	ground_collider.resolution = GPUParticlesCollisionHeightField3D.RESOLUTION_512
	ground_collider.update_mode = GPUParticlesCollisionHeightField3D.UPDATE_MODE_WHEN_MOVED
	ground_collider.follow_camera_enabled = true
	weather_rig.add_child(ground_collider)

	# Splashes-on-collision (via a sub_emitter + ParticleProcessMaterial
	# collision against GroundCollider) looked correct physically but reads as
	# a jarring flat square whenever a drop happens to land within a meter or
	# two of the camera — an inherent risk of camera-attached rain at street
	# level. Cut per ART_DIRECTION's own "with splashes if affordable" hedge;
	# streaks alone already read as rain. RainSplashes node kept (unused) so
	# it's easy to re-enable collision_mode/sub_emitter later if revisited.
	rain_splashes = _make_particles("RainSplashes", 96, 0.25, _make_flat_material(Color(0.75, 0.82, 0.9, 0.5)), Vector2(0.05, 0.05))
	rain_splashes.emitting = false
	rain_splashes.one_shot = false
	rain_splashes.local_coords = false
	var splash_mat: ParticleProcessMaterial = rain_splashes.process_material
	splash_mat.direction = Vector3(0, 1, 0)
	splash_mat.spread = 40.0
	splash_mat.gravity = Vector3(0, -4.0, 0)
	splash_mat.initial_velocity_min = 0.3
	splash_mat.initial_velocity_max = 0.9
	splash_mat.scale_min = 0.4
	splash_mat.scale_max = 0.8
	weather_rig.add_child(rain_splashes)

	# Spawn just above head height and fall through eye level well before the
	# particle's lifetime ends (moderate speed keeps the Y_TO_VELOCITY streak
	# stretch reasonable close to the camera).
	rain_streaks = _make_particles("RainStreaks", 500, 1.1, _make_streak_material(Color(0.75, 0.82, 0.92, 0.4)), Vector2(0.012, 0.3))
	rain_streaks.transform_align = GPUParticles3D.TRANSFORM_ALIGN_Z_BILLBOARD_Y_TO_VELOCITY
	rain_streaks.visibility_aabb = AABB(Vector3(-25, -25, -25), Vector3(50, 50, 50))
	var rain_mat: ParticleProcessMaterial = rain_streaks.process_material
	rain_mat.direction = Vector3(0, -1, 0)
	rain_mat.spread = 4.0
	rain_mat.gravity = Vector3(0, -9.0, 0)
	rain_mat.initial_velocity_min = 2.5
	rain_mat.initial_velocity_max = 3.5
	rain_mat.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	rain_mat.emission_box_extents = Vector3(18.0, 1.0, 18.0)
	rain_streaks.position = Vector3(0, 9.0, 0)
	weather_rig.add_child(rain_streaks)

	# Same recipe as rain (plain gravity + initial velocity, no damping/turbulence
	# — both proved unreliable here), just slower, so flakes drift rather than fall.
	snow_particles = _make_particles("Snow", 700, 5.0, _make_flat_material(Color(0.95, 0.96, 1.0, 0.9)), Vector2(0.07, 0.07))
	# Y_TO_VELOCITY stretches fast (blizzard) flakes into short streaks and
	# leaves slow calm-snow flakes close to their base dot size.
	snow_particles.transform_align = GPUParticles3D.TRANSFORM_ALIGN_Z_BILLBOARD_Y_TO_VELOCITY
	snow_particles.visibility_aabb = AABB(Vector3(-30, -30, -30), Vector3(60, 60, 60))
	var snow_mat: ParticleProcessMaterial = snow_particles.process_material
	snow_mat.direction = Vector3(0, -1, 0)
	snow_mat.spread = 20.0
	snow_mat.gravity = Vector3(0, -2.2, 0)
	snow_mat.initial_velocity_min = 0.6
	snow_mat.initial_velocity_max = 1.2
	snow_mat.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	snow_mat.emission_box_extents = Vector3(18.0, 1.0, 18.0)
	snow_particles.position = Vector3(0, 9.0, 0)
	weather_rig.add_child(snow_particles)

	# Subtle drifting wisps only — the environment's volumetric/depth fog does
	# the actual visibility reduction, this is just close-range atmosphere.
	mist_particles = _make_particles("Mist", 30, 14.0, _make_flat_material(Color(0.85, 0.87, 0.9, 0.035)), Vector2(1.2, 1.2))
	mist_particles.transform_align = GPUParticles3D.TRANSFORM_ALIGN_Z_BILLBOARD
	mist_particles.visibility_aabb = AABB(Vector3(-45, -45, -45), Vector3(90, 90, 90))
	var mist_mat: ParticleProcessMaterial = mist_particles.process_material
	mist_mat.direction = Vector3(1, 0, 0)
	mist_mat.spread = 180.0
	mist_mat.gravity = Vector3(0, 0, 0)
	mist_mat.initial_velocity_min = 0.1
	mist_mat.initial_velocity_max = 0.3
	mist_mat.scale_min = 0.5
	mist_mat.scale_max = 0.8
	mist_mat.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	mist_mat.emission_box_extents = Vector3(22.0, 6.0, 22.0)
	mist_particles.position = Vector3(0, 2.0, 0)
	weather_rig.add_child(mist_particles)

	var debug_ui := CanvasLayer.new()
	debug_ui.name = "DebugUI"
	debug_label = Label.new()
	debug_label.name = "Label"
	debug_label.position = Vector2(12, 8)
	debug_label.add_theme_color_override("font_color", Color(1, 1, 1))
	debug_label.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.8))
	debug_label.add_theme_constant_override("shadow_offset_x", 1)
	debug_label.add_theme_constant_override("shadow_offset_y", 1)
	debug_ui.add_child(debug_label)
	add_child(debug_ui)

func _make_particles(p_name: String, p_amount: int, p_lifetime: float, p_material: StandardMaterial3D, p_quad_size: Vector2) -> GPUParticles3D:
	var p := GPUParticles3D.new()
	p.name = p_name
	p.amount = p_amount
	p.lifetime = p_lifetime
	p.local_coords = false
	p.draw_order = GPUParticles3D.DRAW_ORDER_LIFETIME
	var quad := QuadMesh.new()
	quad.size = p_quad_size
	quad.material = p_material
	p.draw_pass_1 = quad
	var proc_mat := ParticleProcessMaterial.new()
	proc_mat.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	p.process_material = proc_mat
	return p

var _soft_dot_texture: ImageTexture

## A small radial-gradient dot, generated once — used so mist/snow/splash quads
## fade at their edges instead of rendering as hard-edged translucent panels.
func _get_soft_dot_texture() -> ImageTexture:
	if _soft_dot_texture:
		return _soft_dot_texture
	var size := 16
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var center := Vector2(size * 0.5, size * 0.5)
	for y in size:
		for x in size:
			var d := Vector2(x + 0.5, y + 0.5).distance_to(center) / (size * 0.5)
			var a: float = clampf(1.0 - d, 0.0, 1.0)
			a = a * a
			img.set_pixel(x, y, Color(1.0, 1.0, 1.0, a))
	_soft_dot_texture = ImageTexture.create_from_image(img)
	return _soft_dot_texture

func _make_flat_material(color: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	m.albedo_color = color
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	m.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	return m

func _make_streak_material(color: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	m.albedo_color = color
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	m.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	return m

# ---------------------------------------------------------------------------
# Environment / sky — everything here is target-driven and smoothed so both
# debug-key cuts and WorldState.apply(..., transition:=N) read reasonably.
# ---------------------------------------------------------------------------
func _update_environment(delta: float) -> void:
	var wp: Dictionary = weather_profiles[WorldState.weather]
	var sp: Dictionary = season_profiles[WorldState.season]
	# last_transition_duration > 0 means WorldState.apply() asked for a smooth
	# in-game blend over that many seconds; 0 (debug keys, capture tool, scene
	# load) should converge in a handful of frames, not linger — a forced
	# multi-second minimum here left stale weather bleeding into the next
	# capture shot before warmup finished.
	var smooth_time: float = WorldState.last_transition_duration if WorldState.last_transition_duration > 0.0 else 0.15
	var alpha: float = 1.0 - exp(-delta / maxf(smooth_time, 0.01))
	for k in wp.keys():
		var target = wp[k]
		if typeof(target) != TYPE_FLOAT and typeof(target) != TYPE_INT:
			continue
		if not _blend.has(k):
			_blend[k] = float(target)
		_blend[k] = lerpf(float(_blend[k]), float(target), alpha)

	var day_t: float = _cur.get("day_t", 1.0)
	var night_factor: float = _cur.get("night_factor", 0.0)

	# --- sky palette: day / twilight / night stops, blended by sun elevation.
	var zenith_day := Color(0.16, 0.4, 0.82)
	var horizon_day := Color(0.62, 0.74, 0.88)
	var zenith_twi := Color(0.16, 0.14, 0.28)
	var horizon_twi := Color(0.92, 0.5, 0.28)
	var zenith_night := Color(0.015, 0.02, 0.045)
	var horizon_night := Color(0.035, 0.04, 0.07)
	var elev_deg: float = _cur.get("elev_deg", 45.0)
	var twi_t: float = clamp(inverse_lerp(-14.0, 2.0, elev_deg), 0.0, 1.0)
	var day_from_twi_t: float = clamp(inverse_lerp(0.0, 20.0, elev_deg), 0.0, 1.0)
	var zenith: Color = zenith_night.lerp(zenith_twi, twi_t).lerp(zenith_day, day_from_twi_t)
	var horizon: Color = horizon_night.lerp(horizon_twi, twi_t).lerp(horizon_day, day_from_twi_t)
	# Overcast/rain/fog flatten and grey the sky — only kicks in well past scattered
	# clouds (CLEAR's ~0.3 coverage should stay blue; only heavy decks grey out).
	var overcast_t: float = clamp((_blend.get("cloud_coverage", 0.3) - 0.45) / 0.55, 0.0, 1.0)
	var grey := Color(0.5, 0.52, 0.55)
	zenith = zenith.lerp(grey * zenith.get_luminance() * 1.4 + grey * 0.15, overcast_t * 0.7)
	horizon = horizon.lerp(grey, overcast_t * 0.6)
	# Season tint (subtle — keep natural saturation).
	zenith = zenith.lerp(zenith * sp.tint, 0.25)
	horizon = horizon.lerp(horizon * sp.tint, 0.25)

	_sky_material.set_shader_parameter("zenith_color", zenith)
	_sky_material.set_shader_parameter("horizon_color", horizon)
	_sky_material.set_shader_parameter("ground_color", Color(0.05, 0.05, 0.055).lerp(Color(0.5, 0.5, 0.52), _read_snow_cover() * 0.5))
	_sky_material.set_shader_parameter("sun_dir", _cur.get("sun_dir", Vector3.UP))
	_sky_material.set_shader_parameter("sun_color", sun.light_color)
	_sky_material.set_shader_parameter("sun_energy", _cur.get("sun_energy", 0.0))
	_sky_material.set_shader_parameter("moon_dir", _cur.get("moon_dir", Vector3.DOWN))
	_sky_material.set_shader_parameter("moon_color", moon.light_color)
	_sky_material.set_shader_parameter("moon_energy", _cur.get("moon_energy", 0.0))
	_sky_material.set_shader_parameter("cloud_coverage", _blend.get("cloud_coverage", 0.3))
	_sky_material.set_shader_parameter("cloud_darkness", _blend.get("cloud_darkness", 0.1))
	_sky_material.set_shader_parameter("cloud_time", _time_accum)
	_sky_material.set_shader_parameter("wind_dir", Vector2(1.0, 0.35))
	_sky_material.set_shader_parameter("star_visibility", night_factor * (1.0 - overcast_t * 0.85))
	_sky_material.set_shader_parameter("horizon_haze", sp.haze)

	# --- volumetric fog (near-field, weather body) ---
	_env.volumetric_fog_enabled = true
	_env.volumetric_fog_density = _blend.get("fog_density", 0.002)
	_env.volumetric_fog_albedo = horizon.lightened(0.1)
	_env.volumetric_fog_emission = Color(0, 0, 0)
	_env.volumetric_fog_gi_inject = 0.25
	_env.volumetric_fog_ambient_inject = 0.15
	_env.volumetric_fog_anisotropy = 0.2
	_env.volumetric_fog_length = 110.0
	_env.volumetric_fog_sky_affect = 0.5

	# --- depth fog / aerial perspective (far-field, ~2.5-5km horizon) ---
	_env.fog_enabled = true
	_env.fog_light_color = horizon
	_env.fog_light_energy = 1.0
	_env.fog_sun_scatter = 0.25
	_env.fog_density = 1.0 / maxf(_blend.get("visibility", 3000.0), 30.0)
	_env.fog_aerial_perspective = wp.get("aerial", 0.3)
	_env.fog_sky_affect = wp.get("sky_affect", 0.5)
	_env.fog_height = 60.0
	_env.fog_height_density = 0.0

	# --- shadows ---
	sun.shadow_opacity = _blend.get("shadow_opacity", 1.0)

	# --- tonemap / exposure / color grading ---
	# Twilight/night need a generous exposure boost to stay readable (real lux
	# falls off far faster than a game camera should) — "dark but readable" per
	# ART_DIRECTION, not a black crush.
	_env.tonemap_mode = Environment.TONE_MAPPER_AGX
	_env.tonemap_exposure = lerp(2.4, 1.1, day_t) * lerp(1.0, 0.92, overcast_t * 0.5)
	_env.tonemap_agx_contrast = 1.05
	_env.tonemap_agx_white = 13.0
	_env.adjustment_enabled = true
	_env.adjustment_saturation = sp.saturation * lerp(1.0, 0.85, overcast_t * 0.4)
	_env.adjustment_contrast = 1.02
	_env.adjustment_brightness = 1.0

	# --- ambient / GI ---
	_env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	_env.ambient_light_sky_contribution = 1.0
	_env.ambient_light_energy = lerp(0.55, 1.15, day_t) + night_factor * 0.18

	# --- glow (subtle; mostly for the sun/moon discs and bright windows at night) ---
	_env.glow_enabled = true
	_env.glow_intensity = 0.55
	_env.glow_strength = 1.0
	_env.glow_bloom = 0.03
	_env.glow_hdr_threshold = 1.0
	_env.glow_hdr_luminance_cap = 16.0
	_env.glow_blend_mode = Environment.GLOW_BLEND_MODE_SOFTLIGHT

func _read_snow_cover() -> float:
	return WorldState.get_snow_cover()

# ---------------------------------------------------------------------------
# Weather particles — one rig follows the active camera; only the relevant
# systems emit for the current weather. Rain streaks collide with a
# camera-following heightfield and spawn splash sub-particles on contact.
# ---------------------------------------------------------------------------
func _update_particles(_delta: float) -> void:
	var cam := get_viewport().get_camera_3d()
	if cam:
		weather_rig.global_position = cam.global_position

	var is_rain: bool = WorldState.weather == WorldState.Weather.RAIN
	var is_snow: bool = WorldState.weather in [WorldState.Weather.SNOW, WorldState.Weather.BLIZZARD]
	var is_blizzard: bool = WorldState.weather == WorldState.Weather.BLIZZARD
	var is_hazy: bool = WorldState.weather in [WorldState.Weather.FOG, WorldState.Weather.BLIZZARD]

	rain_streaks.emitting = is_rain
	# rain_splashes stays non-emitting (see _build_rig) — it's an unused hook
	# for a future collision sub-emitter, not an independent emitter.
	snow_particles.emitting = is_snow
	mist_particles.emitting = is_hazy

	var wind: float = WorldState.get_wind_strength()

	# NOTE: these run every frame and are the single source of truth for
	# particle gravity — matches the tuning validated in _build_rig, scaled by
	# wind. Keep vertical fall dominant for non-blizzard snow so flakes still
	# drop into view instead of drifting sideways out of the emission box.
	if is_rain:
		var rmat: ParticleProcessMaterial = rain_streaks.process_material
		rmat.gravity = Vector3(wind * 3.0, -9.0, wind * 1.0)

	if is_snow:
		var smat: ParticleProcessMaterial = snow_particles.process_material
		var mul := 3.2 if is_blizzard else 1.0
		smat.gravity = Vector3(wind * 2.0 * mul, -2.2 * mul, wind * 0.8 * mul)
		snow_particles.amount_ratio = 1.0 if is_blizzard else 0.35

	if is_hazy:
		var mmat: ParticleProcessMaterial = mist_particles.process_material
		mist_particles.amount_ratio = 1.0 if is_blizzard else 0.4
		mmat.gravity = Vector3(wind * 3.0, 0.0, wind * 1.0)

func _update_debug_ui() -> void:
	if not debug_label:
		return
	debug_label.visible = not _is_capture_mode()
	if not debug_label.visible:
		return
	var season_name: String = WorldState.Season.keys()[WorldState.season]
	var weather_name: String = WorldState.Weather.keys()[WorldState.weather]
	debug_label.text = "%s / %s / %02d:%02d  (F1 season · F2 weather · F3/F4 hour)" % [
		season_name, weather_name, int(WorldState.hour), int(fmod(WorldState.hour, 1.0) * 60.0)
	]
