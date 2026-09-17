extends Node
## Global world conditions. Every visual system reads from here and listens to `changed`.
## Contract owned by the atmosphere workstream; other systems must only READ these values
## (and the shader globals snow_cover / wetness / season_foliage / wind_strength / night_factor,
## or the get_*() accessors below for the same values without touching RenderingServer).
## See docs/ARCHITECTURE.md "World conditions contract" and docs/atmosphere_notes.md.

signal changed

enum Season { SPRING, SUMMER, AUTUMN, WINTER }
enum Weather { CLEAR, OVERCAST, RAIN, SNOW, BLIZZARD, FOG }

## Representative day-of-year for each season, used for solar position (latitude 41.84N).
const SEASON_DAY_OF_YEAR := {
	Season.SPRING: 100,
	Season.SUMMER: 172,
	Season.AUTUMN: 290,
	Season.WINTER: 355,
}

var season: Season = Season.SUMMER
var weather: Weather = Weather.CLEAR
var hour: float = 12.0 # 0..24 local solar time
var day_of_year: int = 172

## Seconds the most recent apply() asked shader-global transitions to blend over.
## Read (not written) by the atmosphere rig so its own environment/sky blending
## can match; 0 means "snap immediately".
var last_transition_duration: float = 0.0

## Mirrors the current (possibly mid-tween) shader-global values. Other systems
## should prefer the get_*() accessors below over RenderingServer.global_shader_parameter_get,
## which is an editor-only debug call and errors when used at runtime.
var _current := {
	"snow_cover": 0.0,
	"wetness": 0.0,
	"season_foliage": 0.0,
	"wind_strength": 0.2,
}

var _tween: Tween

## p_day_of_year < 0 (default) picks the representative day for p_season.
## p_transition > 0 smoothly blends the continuous shader globals (snow_cover,
## wetness, season_foliage, wind_strength) over that many seconds instead of
## snapping — use this for in-game weather/time changes; leave at 0 for
## instant cuts (debug keys, capture tool, scene load).
func apply(p_season: Season, p_weather: Weather, p_hour: float, p_transition: float = 0.0, p_day_of_year: int = -1) -> void:
	season = p_season
	weather = p_weather
	hour = p_hour
	day_of_year = p_day_of_year if p_day_of_year >= 0 else SEASON_DAY_OF_YEAR[p_season]
	last_transition_duration = p_transition
	_apply_shader_globals(p_transition)
	changed.emit()

func apply_named(p_season: String, p_weather: String, p_hour: float, p_transition: float = 0.0) -> void:
	apply(Season[p_season.to_upper()], Weather[p_weather.to_upper()], p_hour, p_transition)

func get_snow_cover() -> float:
	return _current["snow_cover"]

func get_wetness() -> float:
	return _current["wetness"]

func get_foliage() -> float:
	return _current["season_foliage"]

func get_wind_strength() -> float:
	return _current["wind_strength"]

## snow_cover: 0 outside winter, except light snow possible in the late-autumn
## / early-spring shoulder windows (and only when weather is actually snowing).
func _target_snow_cover() -> float:
	if season == Season.WINTER:
		return 0.85 if weather in [Weather.SNOW, Weather.BLIZZARD] else 0.6
	if season == Season.AUTUMN and day_of_year >= 320 and weather in [Weather.SNOW, Weather.BLIZZARD]:
		return 0.22
	if season == Season.SPRING and day_of_year <= 95 and weather in [Weather.SNOW, Weather.BLIZZARD]:
		return 0.18
	return 0.0

func _target_wetness() -> float:
	match weather:
		Weather.RAIN:
			return 0.85
		Weather.FOG:
			return 0.3
		Weather.SNOW, Weather.BLIZZARD:
			return 0.06
		_:
			return 0.0

func _target_foliage() -> float:
	return {Season.SPRING: 0.25, Season.SUMMER: 0.0, Season.AUTUMN: 0.75, Season.WINTER: 1.0}[season]

func _target_wind() -> float:
	return {Weather.CLEAR: 0.2, Weather.OVERCAST: 0.35, Weather.RAIN: 0.5, Weather.SNOW: 0.4, Weather.BLIZZARD: 1.0, Weather.FOG: 0.05}[weather]

func _apply_shader_globals(p_transition: float) -> void:
	var targets := {
		"snow_cover": _target_snow_cover(),
		"wetness": _target_wetness(),
		"season_foliage": _target_foliage(),
		"wind_strength": _target_wind(),
	}
	if p_transition > 0.0 and is_inside_tree():
		if _tween:
			_tween.kill()
		_tween = create_tween().set_parallel(true)
		for key in targets:
			var cur: float = _current[key]
			_tween.tween_method(_set_global.bind(key), cur, float(targets[key]), p_transition)
	else:
		for key in targets:
			_set_global(float(targets[key]), key)

func _set_global(value: float, key: String) -> void:
	_current[key] = value
	RenderingServer.global_shader_parameter_set(key, value)
