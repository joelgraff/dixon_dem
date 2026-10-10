class_name SpawnPoints
extends RefCounted
## Named spawn locations across downtown Dixon. `player.gd` reads
## `--spawn=<name>` from the OS command line at startup (via
## `spawn_from_cmdline()`); unknown/absent names fall back to DEFAULT_SPAWN.
##
## x/z are Godot local-space meters (see docs/pipeline_notes.md "Coordinates").
## y is omitted for every ground-level spawn -- `get_position()` samples
## `TerrainHeight.get_height(x, z)` at call time so spawns always sit exactly
## on the current terrain (road-conformed), instead of a baked-in y going
## stale if the heightmap is ever re-exported. The one exception is "bridge",
## which hardcodes the deck's y since it's elevated above the river/terrain
## surface the heightmap describes underneath it.

const DEFAULT_SPAWN := "downtown"

# preload (not the bare class_name) so this still works from a fresh headless
# run before the global class list has been scanned -- see
# docs/terrain_notes.md "How other systems sample terrain height".
const _TerrainHeight = preload("res://terrain/terrain_height.gd")

const SPAWNS := {
	"downtown": {
		"x": 1631.3, "z": -1214.2, "yaw_deg": 0.0,
		"desc": "Galena Ave downtown core, at the Dixon Memorial Arch -- the exact Galena & 1st intersection isn't in docs/pipeline_notes.md's landmark table, so the nearest downtown landmark on Galena Ave is used as the proxy.",
	},
	"lincoln_statue": {
		"x": 1387.8, "z": -1726.6, "yaw_deg": 90.0,
		"desc": "Lincoln statue, riverfront (pois.json).",
	},
	"page_park": {
		"x": 647.0, "z": -1633.4, "yaw_deg": 0.0,
		"desc": "Page Park -- polygon centroid from game/data/landuse.json (not in the pipeline_notes landmark table, no single named point for it either).",
	},
	"reagan_home": {
		"x": 1723.1, "z": -590.0, "yaw_deg": 180.0,
		"desc": "Reagan Boyhood Home street, 816 S Hennepin Ave.",
	},
	"bridge": {
		"x": 1512.0, "y": 10.4, "z": -1626.0, "yaw_deg": 90.0,
		"desc": "Galena Ave bridge deck (US-52/IL-26) over the Rock River -- y hardcoded to the deck height since it's above the terrain heightmap's surface at this x/z, not on it.",
	},
	"bluff_vista": {
		"x": 1764.0, "z": -179.0, "yaw_deg": 200.0,
		"desc": "Highest point in the play-area heightmap (~41m local Y, north bluff), facing back south over downtown/the river.",
	},
}

static func has_spawn(spawn_name: String) -> bool:
	return SPAWNS.has(spawn_name)

static func spawn_names() -> Array:
	return SPAWNS.keys()

static func get_spawn(spawn_name: String) -> Dictionary:
	return SPAWNS.get(spawn_name, SPAWNS[DEFAULT_SPAWN])

## Reads `--spawn=<name>` from the OS command line (e.g. `-- --spawn=bridge`);
## falls back to DEFAULT_SPAWN if absent or unrecognized.
static func spawn_from_cmdline() -> String:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--spawn="):
			var n := a.trim_prefix("--spawn=")
			if SPAWNS.has(n):
				return n
			push_warning("SpawnPoints: unknown spawn '%s' (known: %s), using default '%s'" % [n, ", ".join(PackedStringArray(spawn_names())), DEFAULT_SPAWN])
			return DEFAULT_SPAWN
	return DEFAULT_SPAWN

## World-space foot position (feet on the ground, not eye height) for a spawn.
static func get_position(spawn_name: String) -> Vector3:
	var s := get_spawn(spawn_name)
	var x: float = s["x"]
	var z: float = s["z"]
	var y: float = s["y"] if s.has("y") else _TerrainHeight.get_height(x, z)
	return Vector3(x, y, z)

static func get_yaw_rad(spawn_name: String) -> float:
	return deg_to_rad(float(get_spawn(spawn_name).get("yaw_deg", 0.0)))
