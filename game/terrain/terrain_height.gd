class_name TerrainHeight
extends RefCounted
## Static height/normal sampling utility for the Dixon play-area + horizon
## heightmaps, reading directly from game/data/ (world_origin.json +
## heightmap_play_1m_road_conformed.r32 + heightmap_horizon_12.5m.r32) --
## the SAME files terrain.gd builds the visible mesh from, so any other
## workstream calling TerrainHeight.get_height(x, z) gets ground level that
## exactly matches the rendered terrain (road-conformed, so roads/buildings/
## vegetation placement lines up with the carved road camber too).
##
## No autoload needed -- this is a plain RefCounted with static state, so
## just `TerrainHeight.get_height(x, z)` from anywhere. First call lazily
## loads and caches both heightmaps (~30MB total) for the process lifetime.
## See docs/terrain_notes.md "How other systems sample terrain height".

const DATA_DIR := "res://data/"
const ORIGIN_FILE := DATA_DIR + "world_origin.json"

class Grid:
	var width: int
	var height: int
	var spacing: float
	var origin_x: float # local-space x of column 0
	var origin_z: float # local-space z of row 0
	var heights: PackedFloat32Array

	func in_bounds(x: float, z: float) -> bool:
		var col := (x - origin_x) / spacing
		var row := (z - origin_z) / spacing
		return col >= 0.0 and col <= float(width - 1) and row >= 0.0 and row <= float(height - 1)

	func sample(x: float, z: float) -> float:
		var col := clampf((x - origin_x) / spacing, 0.0, float(width - 1))
		var row := clampf((z - origin_z) / spacing, 0.0, float(height - 1))
		var c0 := int(floor(col))
		var r0 := int(floor(row))
		var c1 := mini(c0 + 1, width - 1)
		var r1 := mini(r0 + 1, height - 1)
		var fx := col - c0
		var fz := row - r0
		var h00 := heights[r0 * width + c0]
		var h10 := heights[r0 * width + c1]
		var h01 := heights[r1 * width + c0]
		var h11 := heights[r1 * width + c1]
		return lerpf(lerpf(h00, h10, fx), lerpf(h01, h11, fx), fz)

	func sample_index(col: int, row: int) -> float:
		col = clampi(col, 0, width - 1)
		row = clampi(row, 0, height - 1)
		return heights[row * width + col]

static var _play: Grid
static var _horizon: Grid
static var _loaded := false

static func _ensure_loaded() -> void:
	if _loaded:
		return
	_loaded = true
	var origin := _read_json(ORIGIN_FILE)
	if origin.is_empty():
		push_error("TerrainHeight: could not read " + ORIGIN_FILE)
		return
	var base_e: float = origin["origin_easting"]
	var base_n: float = origin["origin_northing"]
	_play = _load_grid(origin["heightmaps"]["play"], base_e, base_n, true)
	_horizon = _load_grid(origin["heightmaps"]["horizon"], base_e, base_n, false)

static func _read_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var f := FileAccess.open(path, FileAccess.READ)
	var parsed = JSON.parse_string(f.get_as_text())
	return parsed if parsed is Dictionary else {}

static func _load_grid(g: Dictionary, base_e: float, base_n: float, road_conformed: bool) -> Grid:
	var grid := Grid.new()
	grid.width = int(g["width"])
	grid.height = int(g["height"])
	grid.spacing = float(g["spacing_m"])
	grid.origin_x = float(g["origin_easting"]) - base_e
	grid.origin_z = -(float(g["origin_northing_top"]) - base_n)
	var fname: String = (g["road_conformed_file"] if (road_conformed and g.has("road_conformed_file")) else g["file"])
	var path := DATA_DIR + fname
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		push_error("TerrainHeight: could not open " + path)
		grid.heights = PackedFloat32Array()
		return grid
	var bytes := f.get_buffer(f.get_length())
	grid.heights = bytes.to_float32_array()
	return grid

## Ground elevation (local Y, meters) at local-space (x, z). Uses the 1m
## road-conformed play heightmap inside the 2700x2700 play square, falls
## back to the coarse 12.5m horizon heightmap beyond it (clamped at its
## edges). Bilinearly interpolated.
static func get_height(x: float, z: float) -> float:
	_ensure_loaded()
	if _play and _play.in_bounds(x, z):
		return _play.sample(x, z)
	if _horizon:
		return _horizon.sample(x, z)
	return 0.0

## Surface normal at local-space (x, z) via central differences, sample
## spacing `eps` meters (default matches play-grid resolution).
static func get_normal(x: float, z: float, eps: float = 1.0) -> Vector3:
	var h_l := get_height(x - eps, z)
	var h_r := get_height(x + eps, z)
	var h_d := get_height(x, z - eps)
	var h_u := get_height(x, z + eps)
	var dx := (h_r - h_l) / (2.0 * eps)
	var dz := (h_u - h_d) / (2.0 * eps)
	return Vector3(-dx, 1.0, -dz).normalized()

## True if (x,z) falls inside the 1m play heightmap's coverage (vs. the
## coarser horizon-only fallback ring).
static func is_in_play_area(x: float, z: float) -> bool:
	_ensure_loaded()
	return _play != null and _play.in_bounds(x, z)

# ---------------------------------------------------------------------------
# Bulk/raw accessors -- used by terrain.gd's chunk mesh builder to avoid
# per-vertex function-call overhead of get_height(); other systems should
# use get_height()/get_normal() above instead.
# ---------------------------------------------------------------------------
static func get_play_grid() -> Grid:
	_ensure_loaded()
	return _play

static func get_horizon_grid() -> Grid:
	_ensure_loaded()
	return _horizon
