extends Node3D
## Dixon — atmosphere / lighting / sky / weather rig.
## Instance res://atmosphere/atmosphere.tscn once per scene. Everything (sun/moon
## position, sky, fog, clouds, weather particles, night_factor) is driven from
## WorldState every frame — no per-scene setup required beyond instancing this.
##
## Built procedurally in _ready() rather than hand-authored as scene resources,
## so the whole rig lives in one reviewable, tunable file. See docs/atmosphere_notes.md.
##
## iter2: rewritten after a harsh critic pass (docs/critiques/atmosphere_iter1.md).
## Public surface (WorldState API, this file's class name/instancing contract)
## is unchanged — other workstreams already instance this rig in world.tscn.

const LATITUDE_DEG := 41.84
const LONGITUDE_DEG := -89.48
const SKY_SHADER := preload("res://atmosphere/shaders/sky.gdshader")

# -- weather profiles: sky/fog/light targets the rig blends towards ----------
# cloud_coverage/darkness feed the sky shader; fog_density/visibility drive
# volumetric + depth fog; direct_scale dims the sun under cloud (the iter1 bug:
# overcast/rain/snow kept full sun energy and only faded shadow opacity, which
# made overcast walls brighter than clear-sky ones); fog_color anchors the fog
# hue per weather instead of only inheriting the (twilight-tinted) sky horizon.
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

var snow_flake_mesh: QuadMesh
var snow_streak_mesh: QuadMesh

var _env: Environment
var _sky_material: ShaderMaterial
var _time_accum := 0.0
var _blend := {}          # smoothed weather-profile values (float/int/Color)
var _cur := {}             # this-frame computed sun/moon state
var _prev_weather := -1    # detects weather changes to clear stale particles

func _ready() -> void:
	_build_profiles()
	_build_rig()
	_env = world_env.environment
	_sky_material = _env.sky.sky_material as ShaderMaterial
	WorldState.changed.connect(_on_world_state_changed)
	_prev_weather = WorldState.weather
	_on_world_state_changed()
	# First frame: snap instead of smoothing in from zero.
	_update_blend(1000.0)
	_update_sun_moon()
	_update_environment()
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
	_update_blend(delta)
	_update_sun_moon()
	_update_environment()
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
# Solar / lunar position.
# ---------------------------------------------------------------------------

## WorldState.hour is documented and used elsewhere as **clock time** (the
## public contract other workstreams rely on), but the solar-position formula
## needs **local solar time**. iter1 fed clock time straight in, putting the
## sun up to ~10 deg off for 8 months of the year (DST + equation of time +
## longitude vs. the Central meridian). Converting only here keeps the public
## API stable.
func _clock_to_solar_hour(clock_hour: float, day_of_year: int) -> float:
	var dst := 1.0 if (day_of_year >= 70 and day_of_year <= 307) else 0.0
	var b := TAU * float(day_of_year - 81) / 364.0
	var eot_minutes := 9.87 * sin(2.0 * b) - 7.53 * cos(b) - 1.5 * sin(b)
	var longitude_correction_hours := (LONGITUDE_DEG - (-90.0)) / 15.0 # Central meridian = -90
	return clock_hour - dst + longitude_correction_hours + eot_minutes / 60.0

## Real formula for latitude 41.84N. `p_hour` here is already solar time.
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
	var solar_hour := _clock_to_solar_hour(WorldState.hour, WorldState.day_of_year)
	var s := _solar_position(WorldState.day_of_year, solar_hour)
	var sun_dir := _dir_from_elev_az(s.elevation, s.azimuth)
	_point_light_along(sun, sun_dir)

	var elev_deg := rad_to_deg(s.elevation)
	# Was inverse_lerp(-6,...): gave the sun ~30% strength even 0.7 deg below
	# the horizon, warming "shaded" ground that should already be pure skylight
	# by actual sunset. Real atmospheric extinction is near-total by -1 deg.
	var sun_energy_base: float = clamp(inverse_lerp(-1.0, 15.0, elev_deg), 0.0, 1.0)
	sun_energy_base = ease(sun_energy_base, 1.6) * 2.6
	# direct_scale dims direct light under cloud (see weather_profiles) — this
	# is the #1 must-fix from the critique: overcast/rain/snow used to keep
	# full sun energy and only fade shadow opacity, making an overcast wall
	# brighter than the same wall in full clear sun.
	var direct_scale: float = _blend.get("direct_scale", 1.0)
	var sun_energy := sun_energy_base * direct_scale
	sun.light_energy = sun_energy

	var warm := Color(1.0, 0.62, 0.38) # was (1.0,0.55,0.28) — less saturated per critique #3
	var neutral := Color(1.0, 0.97, 0.92)
	var color_t: float = clamp(inverse_lerp(-2.0, 25.0, elev_deg), 0.0, 1.0)
	sun.light_color = warm.lerp(neutral, color_t)

	# Moon: simplified as anti-sun (opposite side of sky) with a slow pseudo-phase
	# for brightness variation. Good enough for readable night ambience; not a
	# real ephemeris.
	var moon_s := _solar_position(WorldState.day_of_year, fposmod(solar_hour + 12.0, 24.0))
	var moon_dir := _dir_from_elev_az(moon_s.elevation, moon_s.azimuth)
	_point_light_along(moon, moon_dir)
	var moon_elev_deg := rad_to_deg(moon_s.elevation)
	var phase: float = absf(sin(TAU * float(WorldState.day_of_year) / 29.53))
	var moon_vis: float = clamp(inverse_lerp(-4.0, 8.0, moon_elev_deg), 0.0, 1.0)
	# Full-phase peak raised 0.16 -> 0.45 and colour cooled per critique #10 so
	# night ground is actually readable instead of crushing to black.
	# Peak lowered 0.45 -> 0.25 (iter2 pushed night too bright stacked with
	# other compensations). moon_vis (elevation-gated) is still the primary
	# on/off switch — a "moonless" shot should be authored at an hour/season
	# where the anti-sun position is actually below the horizon, not relied
	# on phase alone, since this rig's phase is a coarse day-of-year proxy,
	# not a real ephemeris.
	moon.light_energy = moon_vis * lerp(0.05, 0.25, phase) * (1.0 - sun_energy_base * 0.9)
	moon.light_color = Color(0.62, 0.70, 0.88)

	var night_factor: float = clamp(inverse_lerp(-2.0, -10.0, elev_deg), 0.0, 1.0)
	RenderingServer.global_shader_parameter_set("night_factor", night_factor)

	_cur["sun_dir"] = sun_dir
	_cur["moon_dir"] = moon_dir
	_cur["sun_energy"] = sun_energy
	_cur["moon_energy"] = moon.light_energy
	_cur["night_factor"] = night_factor
	_cur["elev_deg"] = elev_deg
	_cur["day_t"] = clamp(inverse_lerp(-8.0, 8.0, elev_deg), 0.0, 1.0)
	# Peaks at 1 right at the horizon, tapers off within ~12 deg either side —
	# drives the sky shader's azimuth-dependent twilight glow / Belt of Venus.
	_cur["twilight_strength"] = clamp(1.0 - absf(elev_deg) / 12.0, 0.0, 1.0)

func _build_profiles() -> void:
	# direct_scale: how much of the sun's direct energy reaches the ground.
	# fog_color: weather-appropriate fog hue (blended a little toward sky/sun
	# colour at render time) so fog doesn't just inherit a twilight-orange sky.
	# depth_begin: distance (m) before depth/aerial-perspective fog starts —
	# keeps CLEAR days crisp up close, hazy only toward the real horizon.
	# vol_length / vol_sky_affect / aerial / sky_affect: fog shape tuning.
	weather_profiles = {
		WorldState.Weather.CLEAR: {
			# Retuned with the real town in view: "visibility" feeds
			# _env.fog_density = 3.0/visibility (95% extinction at that
			# range). 5000m gave 59% opacity by 1500m and 21% by 400m —
			# "washed to near-white" from the 1500m-altitude town overview,
			# milky at 200-400m street level. A real Midwest clear day sees
			# 20-40km; 30000m (mid-range) gives ~14% haze at 1500m and ~4%
			# at 400m — legible town, subtle near-field aerial perspective.
			"cloud_coverage": 0.28, "cloud_darkness": 0.05, "direct_scale": 1.0,
			"fog_density": 0.0003, "visibility": 30000.0, "depth_begin": 500.0,
			"vol_length": 64.0, "vol_sky_affect": 0.0,
			"aerial": 0.15, "sky_affect": 0.08, "shadow_opacity": 1.0, "precip": 0.0,
			"fog_color": Color(0.68, 0.76, 0.86),
			"fog_h": 60.0, "height_density": 0.0, "sun_scatter": 0.25, "anisotropy": 0.2,
		},
		WorldState.Weather.OVERCAST: {
			# Proportionally the same fix as CLEAR: overcast (no rain/fog)
			# still sees 10-20km in reality. 16000m keeps it visibly hazier
			# than CLEAR's 30000m (haze is part of the overcast mood) without
			# the old 2600m's near-white wash at range.
			"cloud_coverage": 0.95, "cloud_darkness": 0.55, "direct_scale": 0.12,
			"fog_density": 0.0013, "visibility": 16000.0, "depth_begin": 350.0,
			"vol_length": 80.0, "vol_sky_affect": 0.0,
			"aerial": 0.14, "sky_affect": 0.12, "shadow_opacity": 1.0, "precip": 0.0,
			"fog_color": Color(0.58, 0.60, 0.63),
			"fog_h": 60.0, "height_density": 0.0, "sun_scatter": 0.25, "anisotropy": 0.2,
		},
		WorldState.Weather.RAIN: {
			"cloud_coverage": 0.98, "cloud_darkness": 0.72, "direct_scale": 0.06,
			"fog_density": 0.0021, "visibility": 1400.0, "depth_begin": 60.0,
			"vol_length": 90.0, "vol_sky_affect": 0.0,
			"aerial": 0.25, "sky_affect": 0.35, "shadow_opacity": 1.0, "precip": 1.0,
			"fog_color": Color(0.55, 0.58, 0.60),
			"fog_h": 60.0, "height_density": 0.0, "sun_scatter": 0.25, "anisotropy": 0.2,
		},
		WorldState.Weather.SNOW: {
			# iter3: visibility/density were inverted vs BLIZZARD (a 1200m-
			# visibility snow shower was hiding a 300m treeline completely).
			# Lower near-field density + longer stated visibility so distant
			# silhouettes actually survive.
			"cloud_coverage": 0.9, "cloud_darkness": 0.35, "direct_scale": 0.10,
			"fog_density": 0.0006, "visibility": 1800.0, "depth_begin": 80.0,
			"vol_length": 70.0, "vol_sky_affect": 0.0,
			"aerial": 0.2, "sky_affect": 0.15, "shadow_opacity": 1.0, "precip": 0.6,
			"fog_color": Color(0.68, 0.72, 0.78),
			"fog_h": 60.0, "height_density": 0.0, "sun_scatter": 0.25, "anisotropy": 0.2,
		},
		WorldState.Weather.BLIZZARD: {
			# iter3: sky_affect/vol_sky_affect were 0 (an over-literal fix of
			# iter1's "fog painted the whole sky") — with the sky untouched, a
			# horizon line and any silhouette against it survived no matter
			# how dense the ground fog got, so it never read as a whiteout.
			# BLIZZARD is the one weather that SHOULD fog the sky too.
			"cloud_coverage": 1.0, "cloud_darkness": 0.6, "direct_scale": 0.03,
			"fog_density": 0.0233, "visibility": 70.0, "depth_begin": 5.0,
			"vol_length": 96.0, "vol_sky_affect": 1.0,
			"aerial": 0.0, "sky_affect": 1.0, "shadow_opacity": 1.0, "precip": 1.0,
			"fog_color": Color(0.8, 0.82, 0.85),
			"fog_h": 60.0, "height_density": 0.0, "sun_scatter": 0.25, "anisotropy": 0.2,
		},
		WorldState.Weather.FOG: {
			"cloud_coverage": 0.6, "cloud_darkness": 0.2, "direct_scale": 0.25,
			"fog_density": 0.008, "visibility": 200.0, "depth_begin": 5.0,
			"vol_length": 160.0, "vol_sky_affect": 0.8,
			"aerial": 0.0, "sky_affect": 1.0, "shadow_opacity": 1.0, "precip": 0.0,
			"fog_color": Color(0.62, 0.66, 0.64),
			# ground-hugging layer: rooftops/tree crowns should clear it.
			"fog_h": 9.0, "height_density": 0.14, "sun_scatter": 0.5, "anisotropy": 0.6,
		},
	}
	# haze values lowered (was 0.15-0.45) and applied with pow(t,2) in the
	# shader-facing calc below — iter2's horizon_haze hugged 14 deg of sky
	# above the horizon and washed it out (clear-sky band at 15 deg had
	# saturation 0.02, should be >= 0.12).
	season_profiles = {
		WorldState.Season.SPRING: {"saturation": 0.95, "haze": 0.15, "tint": Color(0.94, 0.98, 0.99)},
		WorldState.Season.SUMMER: {"saturation": 1.0, "haze": 0.22, "tint": Color(1.0, 0.98, 0.9)},
		WorldState.Season.AUTUMN: {"saturation": 0.92, "haze": 0.18, "tint": Color(0.98, 0.9, 0.78)},
		WorldState.Season.WINTER: {"saturation": 0.82, "haze": 0.12, "tint": Color(0.86, 0.91, 1.0)},
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
	sun.shadow_bias = 0.05
	sun.shadow_normal_bias = 1.0 # was default 2.0 — iter1 had shadows detach from building bases
	sun.sky_mode = DirectionalLight3D.SKY_MODE_LIGHT_ONLY
	add_child(sun)

	moon = DirectionalLight3D.new()
	moon.name = "Moon"
	moon.shadow_enabled = true
	moon.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_2_SPLITS
	moon.directional_shadow_max_distance = 250.0
	moon.shadow_blur = 2.5
	moon.shadow_bias = 0.05
	moon.shadow_normal_bias = 1.0
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
	env.sdfgi_energy = 1.25 # lifts bounce into shaded facades (see ambient fill note)
	env.sdfgi_bounce_feedback = 0.4
	env.sdfgi_read_sky_light = true
	env.ssao_enabled = true
	env.ssao_intensity = 2.0
	env.ssao_power = 1.4
	env.ssao_radius = 1.5
	env.ssil_enabled = true
	env.ssil_intensity = 1.0 # 0.8 left shaded facades black; 1.4 had over-lifted
	env.ssil_radius = 4.0
	env.ssr_enabled = true # wet-road specular per critique #12
	env.ssr_max_steps = 32
	env.ssr_fade_in = 0.15
	env.ssr_fade_out = 2.5
	env.ssr_depth_tolerance = 0.3
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

	# Splashes-on-collision kept disabled (see notes) — RainSplashes node exists
	# as an unused hook only.
	rain_splashes = _make_particles("RainSplashes", 96, 0.25, _make_soft_material(Color(0.75, 0.82, 0.9, 0.6)), Vector2(0.05, 0.05))
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

	# Real rain-streak size (~2cm x 90cm, stretched further by velocity), a
	# MUCH tighter near-camera box (was 36x2x36m — at that spread, almost every
	# drop was 10-25m away and sub-pixel) and a lot more of them since the box
	# is small. Lit colour (not additive glow-white) via BLEND_MODE_MIX.
	# Base quad was 0.9m tall — Y_TO_VELOCITY scales the mesh's Y extent BY
	# the velocity magnitude (~6-9 m/s here), so every drop rendered 5-8m
	# long (76-574px, 5.9% of frame pixels — "scratches on the lens", not
	# rain). 0.12m * 6-9 m/s velocity -> ~0.7-1.1m streaks, which is what a
	# fast-shutter photo of rain actually looks like. More, fainter drops to
	# compensate for the much smaller footprint.
	# Measured at 0.12m base: median streak 42px (target 10-25px) — still ~2x
	# too long, so the empirical Y_TO_VELOCITY multiplier is milder than the
	# naive "size * m/s" estimate. Halved again.
	rain_streaks = _make_particles("RainStreaks", 5500, 1.0, _make_mix_material(Color(0.72, 0.78, 0.85, 0.4)), Vector2(0.015, 0.06))
	rain_streaks.transform_align = GPUParticles3D.TRANSFORM_ALIGN_Z_BILLBOARD_Y_TO_VELOCITY
	rain_streaks.visibility_aabb = AABB(Vector3(-25, -25, -25), Vector3(50, 50, 50))
	var rain_mat: ParticleProcessMaterial = rain_streaks.process_material
	rain_mat.direction = Vector3(0, -1, 0)
	rain_mat.spread = 4.0
	rain_mat.gravity = Vector3(0, -9.0, 0)
	rain_mat.initial_velocity_min = 2.5
	rain_mat.initial_velocity_max = 3.5
	rain_mat.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	rain_mat.emission_box_extents = Vector3(6.0, 1.0, 6.0)
	rain_streaks.position = Vector3(0, 6.0, 0)
	weather_rig.add_child(rain_streaks)

	# Snow: a round soft sprite that swaps to an elongated streak mesh in
	# blizzard, where high horizontal wind velocity + Y_TO_VELOCITY alignment
	# reads as motion blur. iter2's 6cm flake in a 6x1x6m box gave ~21 visible
	# flakes/frame; bigger flakes (10-14cm, randomised per-particle), a
	# taller/tighter box, and a grey tint (pure white was invisible against a
	# white overcast/fog sky) all push toward actually reading as snowfall.
	snow_flake_mesh = QuadMesh.new()
	snow_flake_mesh.size = Vector2(0.12, 0.12)
	snow_streak_mesh = QuadMesh.new()
	snow_streak_mesh.size = Vector2(0.03, 0.25)
	var snow_material := _make_soft_material(Color(0.86, 0.88, 0.93, 0.85))
	snow_flake_mesh.material = snow_material
	snow_streak_mesh.material = snow_material
	snow_particles = GPUParticles3D.new()
	snow_particles.name = "Snow"
	snow_particles.amount = 2500
	snow_particles.lifetime = 4.5
	snow_particles.local_coords = false
	snow_particles.draw_order = GPUParticles3D.DRAW_ORDER_LIFETIME
	snow_particles.draw_pass_1 = snow_flake_mesh
	snow_particles.transform_align = GPUParticles3D.TRANSFORM_ALIGN_Z_BILLBOARD # calm default; swapped to Y_TO_VELOCITY only for blizzard, see _update_particles
	snow_particles.visibility_aabb = AABB(Vector3(-30, -30, -30), Vector3(60, 60, 60))
	var snow_mat := ParticleProcessMaterial.new()
	snow_mat.direction = Vector3(0, -1, 0)
	snow_mat.spread = 20.0
	snow_mat.gravity = Vector3(0, -2.2, 0)
	snow_mat.scale_min = 0.6
	snow_mat.scale_max = 1.5
	snow_mat.angular_velocity_min = -30.0
	snow_mat.angular_velocity_max = 30.0
	snow_mat.initial_velocity_min = 0.6
	snow_mat.initial_velocity_max = 1.2
	snow_mat.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	snow_mat.emission_box_extents = Vector3(4.0, 3.0, 4.0)
	snow_particles.process_material = snow_mat
	snow_particles.position = Vector3(0, 4.0, 0)
	weather_rig.add_child(snow_particles)

	# iter2's 1.2m quads (post soft-texture fix) turned out to read as
	# obvious "cotton ball" discs up close (largest single blob measured 4.9%
	# of frame). The environment's volumetric/depth fog already does the real
	# visibility work; this is only meant to be barely-there texture. Bigger
	# quads but far fewer, much lower alpha, and pushed into a distance band
	# (4-12m) via distance-fade so none ever sits large and sharp near the lens.
	var mist_material := _make_mix_material(Color(0.85, 0.87, 0.9, 0.05))
	mist_material.distance_fade_mode = BaseMaterial3D.DISTANCE_FADE_PIXEL_ALPHA
	mist_material.distance_fade_min_distance = 4.0
	mist_material.distance_fade_max_distance = 12.0
	mist_particles = _make_particles("Mist", 10, 14.0, mist_material, Vector2(4.5, 4.5))
	mist_particles.transform_align = GPUParticles3D.TRANSFORM_ALIGN_Z_BILLBOARD
	mist_particles.visibility_aabb = AABB(Vector3(-45, -45, -45), Vector3(90, 90, 90))
	var mist_mat: ParticleProcessMaterial = mist_particles.process_material
	mist_mat.direction = Vector3(1, 0, 0)
	mist_mat.spread = 180.0
	mist_mat.gravity = Vector3(0, 0, 0)
	mist_mat.initial_velocity_min = 0.1
	mist_mat.initial_velocity_max = 0.3
	mist_mat.scale_min = 0.7
	mist_mat.scale_max = 1.3
	mist_mat.angular_velocity_min = -10.0
	mist_mat.angular_velocity_max = 10.0
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

var _soft_dot_texture: GradientTexture2D

## Soft radial-gradient dot built from a GradientTexture2D resource — iter1
## built this by hand with Image.create()+set_pixel() and it silently came out
## fully transparent (root cause undiagnosed), which combined with ADD blend
## made rain/snow/mist invisible. GradientTexture2D is a standard, tested
## engine resource and reliably produces a soft white-to-transparent falloff.
func _get_soft_dot_texture() -> GradientTexture2D:
	if _soft_dot_texture:
		return _soft_dot_texture
	var grad := Gradient.new()
	grad.set_color(0, Color(1.0, 1.0, 1.0, 1.0))
	grad.set_color(1, Color(1.0, 1.0, 1.0, 0.0))
	var tex := GradientTexture2D.new()
	tex.gradient = grad
	tex.width = 32
	tex.height = 32
	tex.fill = GradientTexture2D.FILL_RADIAL
	tex.fill_from = Vector2(0.5, 0.5)
	tex.fill_to = Vector2(0.5, 0.0)
	_soft_dot_texture = tex
	return _soft_dot_texture

func _make_soft_material(color: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	m.albedo_color = color
	m.albedo_texture = _get_soft_dot_texture()
	# Mipmapped minification was the real "snow invisible" bug: a small quad
	# (real snowflake scale, a few cm) covers only a handful of screen pixels,
	# so the GPU samples a heavily-blurred low mip of the radial gradient —
	# averaging most of its alpha down to near zero. LINEAR (no mipmaps) keeps
	# sampling the full-res texture so the bright centre always shows.
	m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	m.blend_mode = BaseMaterial3D.BLEND_MODE_MIX
	return m

## MIX-blended (not ADD — ADD was why the alpha=0.035 mist read as ~zero: with
## additive blending, low alpha barely lightens the background at all) soft
## sprite, optionally with proximity/distance fade so nothing reads as a flat
## card when it spawns close to the camera.
func _make_mix_material(color: Color, p_fade_close: bool = false) -> StandardMaterial3D:
	var m := _make_soft_material(color)
	if p_fade_close:
		m.proximity_fade_enabled = true
		m.proximity_fade_distance = 1.5
		m.distance_fade_mode = BaseMaterial3D.DISTANCE_FADE_PIXEL_ALPHA
		m.distance_fade_min_distance = 0.5
		m.distance_fade_max_distance = 3.0
	return m

# ---------------------------------------------------------------------------
# Weather-profile blend — smoothed each frame so both debug-key cuts and
# WorldState.apply(..., transition:=N) read reasonably.
# ---------------------------------------------------------------------------
func _update_blend(delta: float) -> void:
	var wp: Dictionary = weather_profiles[WorldState.weather]
	# last_transition_duration > 0 means WorldState.apply() asked for a smooth
	# in-game blend over that many seconds; 0 (debug keys, capture tool, scene
	# load) should converge in a handful of frames, not linger.
	var smooth_time: float = WorldState.last_transition_duration if WorldState.last_transition_duration > 0.0 else 0.15
	var alpha: float = 1.0 - exp(-delta / maxf(smooth_time, 0.01))
	for k in wp.keys():
		var target = wp[k]
		if typeof(target) == TYPE_COLOR:
			if not (_blend.get(k) is Color):
				_blend[k] = target
			_blend[k] = (_blend[k] as Color).lerp(target, alpha)
		elif typeof(target) == TYPE_FLOAT or typeof(target) == TYPE_INT:
			if not _blend.has(k):
				_blend[k] = float(target)
			_blend[k] = lerpf(float(_blend[k]), float(target), alpha)

# ---------------------------------------------------------------------------
# Environment / sky.
# ---------------------------------------------------------------------------
func _update_environment() -> void:
	var sp: Dictionary = season_profiles[WorldState.season]
	var day_t: float = _cur.get("day_t", 1.0)
	var night_factor: float = _cur.get("night_factor", 0.0)
	var direct_scale: float = _blend.get("direct_scale", 1.0)

	# --- sky palette -----------------------------------------------------
	# Zenith stays blue right up to the horizon and only turns toward
	# night-purple once the sun is well below it — iter1 blended a warm
	# twilight tint into the zenith across a wide elevation band, which is
	# what produced the "whole dome salmon" complaint.
	var zenith_day := Color(0.08, 0.20, 0.52) # deep blue, not washed pastel
	var zenith_night := Color(0.015, 0.02, 0.045)
	var zenith_dusk_accent := Color(0.16, 0.14, 0.28)
	var horizon_day := Color(0.62, 0.74, 0.88)
	# horizon_twi is NOT blended into the azimuth-neutral `horizon` uniform
	# below anymore — that was the bug behind "the whole dome (and the ground
	# lit by its ambient) goes salmon at twilight, even facing away from the
	# sun". It's passed to the shader separately, which applies it only in a
	# band around the sun's actual azimuth (see sky.gdshader's warm_glow).
	var horizon_twi := Color(0.95, 0.5, 0.3)
	var horizon_night := Color(0.035, 0.04, 0.07)
	var elev_deg: float = _cur.get("elev_deg", 45.0)

	var zenith_t: float = clamp(inverse_lerp(-4.0, 6.0, elev_deg), 0.0, 1.0)
	var zenith: Color = zenith_night.lerp(zenith_day, zenith_t)
	var dusk_accent_t: float = clamp(1.0 - absf(elev_deg - 1.0) / 10.0, 0.0, 1.0) * 0.22
	zenith = zenith.lerp(zenith_dusk_accent, dusk_accent_t)

	var horizon_t: float = clamp(inverse_lerp(-6.0, 8.0, elev_deg), 0.0, 1.0)
	var horizon: Color = horizon_night.lerp(horizon_day, horizon_t)

	# Overcast/rain/fog flatten and grey the sky — tied to the same
	# direct_scale knob as the sun dimming so they move together.
	var overcast_t: float = clamp(1.0 - direct_scale, 0.0, 1.0)
	var grey := Color(0.5, 0.52, 0.55)
	zenith = zenith.lerp(grey * zenith.get_luminance() * 1.4 + grey * 0.15, overcast_t * 0.65)
	horizon = horizon.lerp(grey, overcast_t * 0.55)
	# Season tint — subtle, and now also reaches the sun/fog below (not sky-only).
	var season_tint: Color = sp.tint
	zenith = zenith.lerp(zenith * season_tint, 0.2)
	horizon = horizon.lerp(horizon * season_tint, 0.2)
	sun.light_color = sun.light_color.lerp(sun.light_color * season_tint, 0.15)

	# iter3: overcast NIGHT was reading brighter than clear night (138/255 —
	# dusk, not 22:00) because the grey-flattening blend above brightens dim
	# night colors the same way it flattens bright day ones. Overcast should
	# make a night sky *darker* (city glow blocked, no moon/starlight through
	# cloud), not lighter — dim explicitly by the overcast*night combination.
	var night_overcast_dim: float = lerp(1.0, 0.35, overcast_t * night_factor)
	zenith = zenith * night_overcast_dim
	horizon = horizon * night_overcast_dim

	var twilight_strength: float = _cur.get("twilight_strength", 0.0)

	_sky_material.set_shader_parameter("zenith_color", zenith)
	_sky_material.set_shader_parameter("horizon_color", horizon)
	_sky_material.set_shader_parameter("horizon_twilight_color", horizon_twi.lerp(horizon_twi * sp.tint, 0.2))
	# Ground radiance floor raised well off black (was 0.05) so shaded/skylit
	# surfaces at twilight get some bounce instead of crushing to zero.
	var ground_base := Color(0.15, 0.15, 0.16)
	var ground_snow := Color(0.45, 0.45, 0.47)
	_sky_material.set_shader_parameter("ground_color", ground_base.lerp(ground_snow, _read_snow_cover()))
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
	_sky_material.set_shader_parameter("twilight_strength", twilight_strength)

	# --- fog: one colour drives both systems, per weather (not just the sky's
	# twilight-tinted horizon), blended a little toward sun colour for time-of-
	# day variation ------------------------------------------------------
	var fog_color: Color = _blend.get("fog_color", horizon)
	fog_color = fog_color.lerp(horizon, 0.3).lerp(sun.light_color, clamp(_cur.get("sun_energy", 0.0) * direct_scale * 0.2, 0.0, 0.3))

	_env.volumetric_fog_enabled = true
	_env.volumetric_fog_density = _blend.get("fog_density", 0.0005)
	_env.volumetric_fog_albedo = fog_color
	_env.volumetric_fog_emission = Color(0, 0, 0)
	_env.volumetric_fog_gi_inject = 0.25
	_env.volumetric_fog_ambient_inject = 0.15
	_env.volumetric_fog_anisotropy = _blend.get("anisotropy", 0.2)
	_env.volumetric_fog_length = _blend.get("vol_length", 90.0)
	_env.volumetric_fog_sky_affect = _blend.get("vol_sky_affect", 0.0)
	_env.volumetric_fog_detail_spread = 2.0

	_env.fog_enabled = true
	_env.fog_light_color = fog_color
	_env.fog_light_energy = 1.0
	_env.fog_sun_scatter = _blend.get("sun_scatter", 0.25)
	# 95% extinction at ~3/density, not 1/density (iter1 under-fogged by 3x).
	_env.fog_density = 3.0 / maxf(_blend.get("visibility", 3000.0), 30.0)
	_env.fog_depth_begin = _blend.get("depth_begin", 60.0)
	_env.fog_depth_curve = 1.2
	_env.fog_aerial_perspective = _blend.get("aerial", 0.3)
	_env.fog_sky_affect = _blend.get("sky_affect", 0.5)
	# ground-hugging layer (FOG only, others keep height_density=0 — see
	# weather_profiles): rooftops/tree crowns should clear a shallow fog deck.
	_env.fog_height = _blend.get("fog_h", 60.0)
	_env.fog_height_density = _blend.get("height_density", 0.0)

	_apply_airborne_depth()

	# --- shadows -----------------------------------------------------------
	# Full opacity always now that direct_scale actually dims the light — a
	# weak sun already gives a weak-contrast shadow; opacity<1 on top of that
	# was leaking light and washing overcast contrast out further.
	sun.shadow_opacity = 1.0
	moon.shadow_opacity = 1.0

	# --- tonemap / exposure / color grading ---------------------------------
	_env.tonemap_mode = Environment.TONE_MAPPER_AGX
	# Night was overexposed to compensate for a since-fixed ambient bug,
	# stacking with the ambient/moon boosts below into "night reads as dusk"
	# (overcast night sky measured 138/255). Pulled back toward a sane night
	# floor; overcast now genuinely darkens exposure instead of a token 4%.
	_env.tonemap_exposure = lerp(2.0, 1.6, day_t) * lerp(1.0, 0.78, overcast_t)
	_env.tonemap_agx_contrast = lerp(0.95, 1.3, direct_scale)
	_env.tonemap_agx_white = lerp(9.0, 6.5, direct_scale)
	_env.adjustment_enabled = true
	var sat: float = sp.saturation * lerp(1.0, 0.85, overcast_t * 0.4)
	# Clamp saturation harder right around twilight — this is what was
	# producing the over-saturated salmon golden-hour ground.
	sat = minf(sat, lerp(1.0, 0.95, twilight_strength))
	_env.adjustment_saturation = sat
	_env.adjustment_contrast = 1.02
	_env.adjustment_brightness = 1.0

	# --- ambient / GI --------------------------------------------------------
	# Ambient energy is now a flat-ish multiplier (brightness itself comes from
	# the sky COLOR, which already varies with time of day) instead of a second
	# independent elevation curve fighting the sky gradient — that mismatch is
	# what let twilight ground crush to black under a bright sky. Overcast/
	# rain/snow get an explicit boost so a heavily-clouded sky's larger share
	# of ambient still reads as adequately lit.
	_env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	_env.ambient_light_sky_contribution = 1.0
	# Multipliers, each answering a different complaint:
	# - DAYTIME overcast/rain/snow ground needs MORE ambient (sky carries the
	#   light, the ground shouldn't go dark). Gated out by night_factor below
	#   — iter3 bug: this boost was keyed only on direct_scale, so it was
	#   still fully active at night too, making overcast NIGHT ~2x brighter
	#   than clear night (measured sky 82.6 vs 49.7) — backwards.
	# - true night needs LESS ambient than the daytime floor, and the SAME
	#   less regardless of weather (the overcast day-boost fades to a neutral
	#   1.0 by full night, then the flat night dimming applies equally), or
	#   "moonlit night" and "overcast noon" end up similarly lit.
	# - twilight (sun right at the horizon) needs MORE, since direct light
	#   has almost vanished there but skylight hasn't yet — this is what was
	#   crushing winter sunset to 27% black pixels.
	var overcast_day_boost: float = lerp(2.0, 1.0, direct_scale)
	var ambient_energy: float = lerp(overcast_day_boost, 1.0, night_factor)
	# 0.45 crushed a moonless night to ~65% of the lower frame at <=5 luma —
	# "dark but readable" per ART_DIRECTION, not pitch black.
	ambient_energy *= lerp(1.0, 0.6, night_factor)
	ambient_energy *= lerp(1.0, 1.9, twilight_strength)
	# Sunny-day skylight fill. On a clear day a SHADED facade is still lit by blue
	# skylight plus bounce -- roughly 10-20% of the sunlit side. With ambient at 1.0
	# every shadowed wall crushed to near-black, which is what made downtown read as
	# black slabs (user screenshots 2026-09-20): the geometry and materials were fine,
	# the shaded side simply had no fill. Strongest under clear sun (where the
	# sun/shade ratio is widest); overcast already lifts shade via overcast_day_boost.
	ambient_energy *= lerp(1.0, 1.25, direct_scale * (1.0 - night_factor))
	_env.ambient_light_energy = ambient_energy

	# --- glow (windows/streetlights at night, sun/moon glints) --------------
	_env.glow_enabled = true
	_env.glow_intensity = 0.3
	_env.glow_strength = 1.0
	_env.glow_bloom = 0.03
	_env.glow_hdr_threshold = 1.0
	_env.glow_hdr_luminance_cap = 16.0
	_env.glow_blend_mode = Environment.GLOW_BLEND_MODE_ADDITIVE

func _read_snow_cover() -> float:
	return WorldState.get_snow_cover()

# ---------------------------------------------------------------------------
# Weather particles — one rig follows the active camera; only the relevant
# systems emit for the current weather.
# ---------------------------------------------------------------------------
func _update_particles(_delta: float) -> void:
	var cam := get_viewport().get_camera_3d()
	if cam:
		weather_rig.global_position = cam.global_position

	# Hard restart on every weather change so a particle system that's turning
	# off can't leave live particles hanging around into the next shot/frame
	# (iter1 bug: emitting=false stops NEW spawns but does nothing to already-
	# alive particles, which stayed visible for their full remaining lifetime
	# — up to 14s for mist — bleeding a previous weather's quads into captures
	# taken well after the change).
	if WorldState.weather != _prev_weather:
		rain_streaks.restart()
		snow_particles.restart()
		mist_particles.restart()
		_prev_weather = WorldState.weather

	var is_rain: bool = WorldState.weather == WorldState.Weather.RAIN
	var is_snow: bool = WorldState.weather in [WorldState.Weather.SNOW, WorldState.Weather.BLIZZARD]
	var is_blizzard: bool = WorldState.weather == WorldState.Weather.BLIZZARD
	var is_hazy: bool = WorldState.weather in [WorldState.Weather.FOG, WorldState.Weather.BLIZZARD]

	rain_streaks.emitting = is_rain
	snow_particles.emitting = is_snow
	mist_particles.emitting = is_hazy

	var wind: float = WorldState.get_wind_strength()
	var precip: float = _blend.get("precip", 0.0)

	if is_rain:
		var rmat: ParticleProcessMaterial = rain_streaks.process_material
		rmat.gravity = Vector3(wind * 3.0, -9.0, wind * 1.0)
		rain_streaks.amount_ratio = clamp(precip, 0.15, 1.0)

	if is_snow:
		var smat: ParticleProcessMaterial = snow_particles.process_material
		if is_blizzard:
			# Strong horizontal wind + Y_TO_VELOCITY streaks the flakes into
			# visible motion blur; swap to the elongated streak mesh. NOTE:
			# Y_TO_VELOCITY scales the mesh by velocity magnitude, which is
			# why calm snow (below, ~1 m/s) must NOT use it — at that speed
			# the stretch scale collapses the flake to sub-pixel and it
			# vanishes entirely (this was iter2's "no snow visible" bug).
			snow_particles.transform_align = GPUParticles3D.TRANSFORM_ALIGN_Z_BILLBOARD_Y_TO_VELOCITY
			smat.gravity = Vector3(wind * 14.0, -3.5, wind * 5.0)
			snow_particles.draw_pass_1 = snow_streak_mesh
		else:
			snow_particles.transform_align = GPUParticles3D.TRANSFORM_ALIGN_Z_BILLBOARD
			smat.gravity = Vector3(wind * 2.0, -2.2, wind * 0.8)
			snow_particles.draw_pass_1 = snow_flake_mesh
		# precip is 0.6 for SNOW / 1.0 for BLIZZARD in weather_profiles, so this
		# both drives the intended density split and actually uses the
		# previously-unused `precip` key, ramped smoothly through transitions.
		snow_particles.amount_ratio = clamp(precip, 0.1, 1.0)

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


# ---------------------------------------------------------------------------
# Airborne depth pass (user review 2026-09-20: "flat ... airborne effects —
# weather, seasons, time of day").
#
# Before this, every preset except FOG ran height_density = 0, anisotropy 0.2,
# sun_scatter 0.25 and vol_sky_affect 0 — i.e. a uniform fog slab with almost no
# forward scattering. Distance then reads as a flat wash instead of layered air,
# and time of day barely changes the air at all.
#
# This layers three physically-motivated modulations ON TOP of the weather
# presets (it never replaces them, so the measured visibility ladders per
# weather still hold):
#   1. Valley fog deck — Dixon sits in the Rock River valley (river surface
#      local Y ~4-8, downtown rim ~27, bluffs ~41). A shallow deck that pools
#      in the valley and lets rooftops/canopy stand clear of it is the strongest
#      available depth cue, and it is free: two Environment properties.
#   2. Forward scattering — anisotropy + fog_sun_scatter rise sharply when the
#      sun is low, so haze glows toward the sun at dawn/dusk and stays neutral
#      at noon. This is what makes air read as a medium rather than a tint.
#   3. Season/time character — summer afternoon haze, crisp dry winter air,
#      humid spring/autumn dawn mist that burns off by mid-morning.
func _apply_airborne_depth() -> void:
	var elev_deg: float = _cur.get("elev_deg", 45.0)
	var night_factor: float = _cur.get("night_factor", 0.0)
	var weather: int = WorldState.weather
	var season: int = WorldState.season
	var hour: float = WorldState.hour

	# --- 1. valley fog deck ------------------------------------------------
	# Deck top sits a little above the downtown rim so the valley fills and the
	# bluffs/rooftops emerge. FOG/BLIZZARD keep their own (already tuned) decks.
	var deck_density := 0.0
	var deck_top := 26.0
	match weather:
		WorldState.Weather.CLEAR:    deck_density = 0.005
		WorldState.Weather.OVERCAST: deck_density = 0.022
		WorldState.Weather.RAIN:     deck_density = 0.040
		WorldState.Weather.SNOW:     deck_density = 0.030
		_:                           deck_density = -1.0  # FOG / BLIZZARD: leave preset alone

	# --- 3. season + time character ---------------------------------------
	# Dawn mist: humid seasons pool fog in the valley overnight; it burns off as
	# the sun climbs. Strongest spring/autumn, weakest winter.
	var dawn := clampf(inverse_lerp(9.5, 5.0, hour), 0.0, 1.0)
	var season_humidity := 1.0
	match season:
		WorldState.Season.SPRING: season_humidity = 1.35
		WorldState.Season.SUMMER: season_humidity = 1.10
		WorldState.Season.AUTUMN: season_humidity = 1.30
		WorldState.Season.WINTER: season_humidity = 0.55
	var mist := dawn * season_humidity * clampf(1.0 - night_factor * 0.5, 0.35, 1.0)

	# Summer afternoon haze thickens the general air a little; winter air is crisp.
	var afternoon := clampf(inverse_lerp(12.0, 17.0, hour), 0.0, 1.0)
	var haze := 1.0
	match season:
		WorldState.Season.SUMMER: haze = lerp(1.0, 1.18, afternoon)
		WorldState.Season.WINTER: haze = 0.80
		_:                        haze = lerp(1.0, 1.08, afternoon)

	if deck_density >= 0.0:
		_env.fog_height = deck_top + lerp(6.0, -8.0, mist)   # deck sinks/tightens with mist
		# Mist multiplies the valley deck, not whole-scene fog: dawn should pool in
		# the valley, never lay a uniform film over the far bluffs.
		_env.fog_height_density = deck_density * (1.0 + mist * 3.0)
		_env.fog_density *= lerp(1.0, haze, 0.5)
		_env.volumetric_fog_density *= haze

	# --- 2. forward scattering --------------------------------------------
	# Low sun -> strongly forward-scattering, glowing air; high sun -> neutral.
	var low_sun := clampf(inverse_lerp(25.0, 0.0, elev_deg), 0.0, 1.0)
	var base_aniso: float = _blend.get("anisotropy", 0.2)
	var base_scatter: float = _blend.get("sun_scatter", 0.25)
	if weather != WorldState.Weather.FOG and weather != WorldState.Weather.BLIZZARD:
		_env.volumetric_fog_anisotropy = clampf(maxf(base_aniso, 0.45) + low_sun * 0.35, 0.0, 0.9)
		_env.fog_sun_scatter = clampf(maxf(base_scatter, 0.35) + low_sun * 0.45, 0.0, 1.0)
		# A touch of sky influence so distant air is part of the sky, not a decal
		# over it — kept small for CLEAR so the 30 km visibility target holds.
		var sky_add := 0.04 if weather == WorldState.Weather.CLEAR else 0.10
		_env.volumetric_fog_sky_affect = clampf(_blend.get("vol_sky_affect", 0.0) + sky_add, 0.0, 1.0)
