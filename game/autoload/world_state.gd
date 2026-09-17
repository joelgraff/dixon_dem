extends Node
## Global world conditions. Every visual system reads from here and listens to `changed`.
## Contract owned by the atmosphere workstream; other systems must only READ these values
## (and the shader globals snow_cover / wetness / season_foliage / wind_strength).

signal changed

enum Season { SPRING, SUMMER, AUTUMN, WINTER }
enum Weather { CLEAR, OVERCAST, RAIN, SNOW, BLIZZARD, FOG }

var season: Season = Season.SUMMER
var weather: Weather = Weather.CLEAR
var hour: float = 12.0 # 0..24 local solar time
var day_of_year: int = 172

func apply(p_season: Season, p_weather: Weather, p_hour: float) -> void:
	season = p_season
	weather = p_weather
	hour = p_hour
	_update_shader_globals()
	changed.emit()

func apply_named(p_season: String, p_weather: String, p_hour: float) -> void:
	apply(Season[p_season.to_upper()], Weather[p_weather.to_upper()], p_hour)

func _update_shader_globals() -> void:
	# Placeholder mapping; atmosphere workstream refines (accumulation over time, melt, etc.)
	var snow := 0.0
	if season == Season.WINTER:
		snow = 0.85 if weather in [Weather.SNOW, Weather.BLIZZARD] else 0.6
	var wet := 1.0 if weather == Weather.RAIN else (0.35 if weather == Weather.FOG else 0.0)
	var foliage: float = {Season.SPRING: 0.25, Season.SUMMER: 0.0, Season.AUTUMN: 0.75, Season.WINTER: 1.0}[season]
	var wind: float = {Weather.CLEAR: 0.2, Weather.OVERCAST: 0.35, Weather.RAIN: 0.5, Weather.SNOW: 0.4, Weather.BLIZZARD: 1.0, Weather.FOG: 0.05}[weather]
	RenderingServer.global_shader_parameter_set("snow_cover", snow)
	RenderingServer.global_shader_parameter_set("wetness", wet)
	RenderingServer.global_shader_parameter_set("season_foliage", foliage)
	RenderingServer.global_shader_parameter_set("wind_strength", wind)
