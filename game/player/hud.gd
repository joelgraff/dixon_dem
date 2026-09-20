extends CanvasLayer
## Toggleable exploration HUD: location readout (nearest street / intersection)
## and a minimap built from the same vector data the world is generated from.
##
## Toggles (also listed on screen at first run):
##   F7  location readout      F8  minimap      F9  cycle minimap zoom
##   F12 screenshot            Shift+F12  screenshot without HUD
## Everything here is OFF during capture_mode so it never pollutes renders.

const ROADS_PATH := "res://data/roads.json"
const POIS_PATH := "res://data/pois.json"
const SHOT_DIR := "user://../captures/manual"   # resolves next to the project

@export var show_location := true
@export var show_minimap := true

var _zooms: Array[float] = [120.0, 250.0, 600.0]
var _zoom_idx := 1

var _label: Label
var _hint: Label
var _map: Control
var _player: Node3D

# name -> array of PackedVector2Array segments, prebuilt once from roads.json
var _street_segments: Array = []    # {name, a: Vector2, b: Vector2, cls: String}
var _pois: Array = []               # {name, pos: Vector2}
var _hint_timer := 8.0

func _ready() -> void:
	layer = 10
	_build_ui()
	_load_vectors()
	set_process(true)

func _is_capture_mode() -> bool:
	var n: Node = self
	while n:
		if n.has_meta("capture_mode"):
			return true
		n = n.get_parent()
	return false

func _build_ui() -> void:
	_label = Label.new()
	_label.position = Vector2(18, 14)
	_label.add_theme_font_size_override("font_size", 18)
	_label.add_theme_color_override("font_color", Color(1, 1, 1, 0.92))
	_label.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.75))
	_label.add_theme_constant_override("shadow_offset_x", 1)
	_label.add_theme_constant_override("shadow_offset_y", 1)
	add_child(_label)

	_hint = Label.new()
	_hint.position = Vector2(18, 40)
	_hint.add_theme_font_size_override("font_size", 13)
	_hint.add_theme_color_override("font_color", Color(1, 1, 1, 0.6))
	_hint.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.7))
	_hint.text = "F7 location   F8 minimap   F9 zoom   F12 screenshot (Shift+F12 = no HUD)"
	add_child(_hint)

	_map = Control.new()
	_map.size = Vector2(230, 230)
	_map.draw.connect(_draw_map)
	add_child(_map)

func _load_vectors() -> void:
	var f := FileAccess.open(ROADS_PATH, FileAccess.READ)
	if f:
		var d = JSON.parse_string(f.get_as_text())
		for w in (d.get("ways", []) if d else []):
			var tags: Dictionary = w.get("tags", {})
			var nm: String = str(tags.get("name", ""))
			var cls: String = str(tags.get("highway", ""))
			var vs: Array = w.get("vertices", [])
			for i in range(vs.size() - 1):
				_street_segments.append({
					"name": nm, "cls": cls,
					"a": Vector2(vs[i]["x"], vs[i]["z"]),
					"b": Vector2(vs[i + 1]["x"], vs[i + 1]["z"]),
				})
	var pf := FileAccess.open(POIS_PATH, FileAccess.READ)
	if pf:
		var pd = JSON.parse_string(pf.get_as_text())
		for key in ["points", "pois"]:
			for p in (pd.get(key, []) if pd else []):
				var nm := str(p.get("name", ""))
				if nm != "" and p.has("x") and p.has("z"):
					_pois.append({"name": nm, "pos": Vector2(p["x"], p["z"])})

func _find_player() -> Node3D:
	if is_instance_valid(_player):
		return _player
	var root := get_tree().current_scene
	if root:
		_player = root.find_child("Player", true, false) as Node3D
	return _player

## Nearest street, and the crossing street if we are near an intersection.
func _location_text(p: Vector2) -> String:
	var best := {"d": 1e20, "name": ""}
	var second := {"d": 1e20, "name": ""}
	for s in _street_segments:
		var nm: String = s["name"]
		if nm == "":
			continue
		var a: Vector2 = s["a"]
		var b: Vector2 = s["b"]
		var ab := b - a
		var t: float = 0.0 if ab.length_squared() == 0.0 else clampf((p - a).dot(ab) / ab.length_squared(), 0.0, 1.0)
		var d := p.distance_to(a + ab * t)
		if d < best["d"]:
			if nm != best["name"]:
				second = best.duplicate()
			best = {"d": d, "name": nm}
		elif d < second["d"] and nm != best["name"]:
			second = {"d": d, "name": nm}
	if best["name"] == "":
		return "—"
	# Near two named streets => call it an intersection.
	if second["name"] != "" and second["d"] < 35.0:
		return "%s & %s" % [best["name"], second["name"]]
	var near := ""
	for poi in _pois:
		var pd: float = p.distance_to(poi["pos"])
		if pd < 60.0:
			near = "   · near %s" % poi["name"]
			break
	return "%s%s" % [best["name"], near]

func _process(delta: float) -> void:
	var capture := _is_capture_mode()
	var pl := _find_player()
	_label.visible = show_location and not capture and pl != null
	_map.visible = show_minimap and not capture and pl != null
	if _hint_timer > 0.0:
		_hint_timer -= delta
	_hint.visible = _hint_timer > 0.0 and not capture
	if capture or pl == null:
		return
	var p := Vector2(pl.global_position.x, pl.global_position.z)
	if _label.visible:
		_label.text = "%s\n%s  ·  %s" % [
			_location_text(p),
			_season_name(), _weather_name()]
	if _map.visible:
		var vp := get_viewport().get_visible_rect().size
		_map.position = Vector2(vp.x - _map.size.x - 18, 18)
		_map.queue_redraw()

func _season_name() -> String:
	return ["Spring", "Summer", "Autumn", "Winter"][WorldState.season]

func _weather_name() -> String:
	return ["Clear", "Overcast", "Rain", "Snow", "Blizzard", "Fog"][WorldState.weather]

func _draw_map() -> void:
	var pl := _find_player()
	if pl == null:
		return
	var span: float = _zooms[_zoom_idx]
	var c := _map.size * 0.5
	var p := Vector2(pl.global_position.x, pl.global_position.z)
	var scale := _map.size.x / span
	_map.draw_rect(Rect2(Vector2.ZERO, _map.size), Color(0.07, 0.08, 0.09, 0.72))
	for s in _street_segments:
		var a: Vector2 = (s["a"] - p) * scale + c
		var b: Vector2 = (s["b"] - p) * scale + c
		if not _seg_visible(a, b):
			continue
		var cls: String = s["cls"]
		var w := 3.0 if cls in ["primary", "secondary", "trunk"] else (2.0 if cls == "tertiary" else 1.0)
		var col := Color(0.95, 0.85, 0.55, 0.95) if w >= 3.0 else Color(0.85, 0.87, 0.9, 0.7)
		_map.draw_line(a, b, col, w)
	# player marker + heading
	var fwd := -pl.global_transform.basis.z
	var head := Vector2(fwd.x, fwd.z).normalized()
	_map.draw_circle(c, 4.0, Color(0.3, 0.8, 1.0))
	_map.draw_line(c, c + head * 13.0, Color(0.3, 0.8, 1.0), 2.0)
	_map.draw_string(ThemeDB.fallback_font, Vector2(8, _map.size.y - 8),
		"%d m   N↑" % int(span), HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color(1, 1, 1, 0.65))

func _seg_visible(a: Vector2, b: Vector2) -> bool:
	var r := Rect2(Vector2(-20, -20), _map.size + Vector2(40, 40))
	return r.has_point(a) or r.has_point(b)

func _unhandled_key_input(event: InputEvent) -> void:
	if _is_capture_mode():
		return
	if not (event is InputEventKey) or not event.pressed or event.echo:
		return
	match event.keycode:
		KEY_F7: show_location = not show_location
		KEY_F8: show_minimap = not show_minimap
		KEY_F9: _zoom_idx = (_zoom_idx + 1) % _zooms.size()
		KEY_F12: _screenshot(event.shift_pressed)

## Saves a timestamped PNG with position/heading/conditions in the name, so a
## screenshot is self-describing when it comes back as a bug report.
func _screenshot(hide_hud: bool) -> void:
	var pl := _find_player()
	var was_loc := _label.visible
	var was_map := _map.visible
	if hide_hud:
		_label.visible = false
		_map.visible = false
		_hint.visible = false
		await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var dir := ProjectSettings.globalize_path("res://../captures/manual")
	DirAccess.make_dir_recursive_absolute(dir)
	var pos := "0_0_0"
	if pl:
		pos = "%d_%d_%d" % [int(pl.global_position.x), int(pl.global_position.y), int(pl.global_position.z)]
	var name := "%s_%s_%s_%s_h%04.1f.png" % [
		Time.get_datetime_string_from_system().replace(":", "").replace("-", ""),
		pos, _season_name().to_lower(), _weather_name().to_lower(), WorldState.hour]
	var path := dir.path_join(name)
	img.save_png(path)
	print("screenshot: ", path)
	if hide_hud:
		_label.visible = was_loc
		_map.visible = was_map
