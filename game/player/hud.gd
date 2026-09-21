extends CanvasLayer
## Toggleable exploration HUD: where am I, what am I looking at, and screenshots.
##
##   F7   location / structure readout      F8   minimap
##   F9   cycle minimap zoom                F10  coordinates + look vector
##   F12  screenshot  ·  Shift+F12  screenshot with the HUD hidden
##
## Screenshots land in <project>/screenshots/ with position, heading, season,
## weather and hour in the filename, so a shot is self-describing as a bug report.
##
## Layout note: atmosphere.gd owns the top-left (12,8) and player.gd's debug
## readout sits at (12,40), so this HUD anchors to the BOTTOM-left instead --
## the two used to overlap.

const ROADS_PATH := "res://data/roads.json"
const POIS_PATH := "res://data/pois.json"
const BUILDINGS_PATH := "res://data/buildings.json"

## landmark_id -> display name (buildings.json carries ids, not pretty names)
const LANDMARK_NAMES := {
	"lee_county_courthouse": "Old Lee County Courthouse",
	"dixon_theatre": "The Dixon: Historic Theatre",
	"reagan_boyhood_home": "Reagan Boyhood Home",
	"nachusa_house": "Nachusa House",
	"lincoln_statue": "Lincoln Statue",
	"dixon_arch": "Dixon Memorial Arch",
	"galena_bridge": "Galena Avenue Bridge",
	"dixon_dam": "Dixon Dam",
}

@export var show_location := true
@export var show_minimap := true
@export var show_coords := true

var _zooms: Array[float] = [120.0, 250.0, 600.0]
var _zoom_idx := 1

var _panel: Label
var _hint: Label
var _map: Control
var _player: Node3D
var _cam: Camera3D

var _street_segments: Array = []
var _named: Array = []          # {name, pos: Vector2, radius: float, landmark: bool}
var _hint_timer := 12.0

func _ready() -> void:
	layer = 10
	_build_ui()
	_load_vectors()

func _is_capture_mode() -> bool:
	var n: Node = self
	while n:
		if n.has_meta("capture_mode"):
			return true
		n = n.get_parent()
	return false

func _mk_label(size: int, alpha: float) -> Label:
	var l := Label.new()
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", Color(1, 1, 1, alpha))
	l.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.8))
	l.add_theme_constant_override("shadow_offset_x", 1)
	l.add_theme_constant_override("shadow_offset_y", 1)
	add_child(l)
	return l

func _build_ui() -> void:
	_panel = _mk_label(17, 0.94)
	_hint = _mk_label(13, 0.6)
	_hint.text = "F7 location   F8 minimap   F9 map zoom   F10 coords   F11 BUG TICKET   F12 screenshot"
	_map = Control.new()
	_map.size = Vector2(240, 240)
	_map.draw.connect(_draw_map)
	add_child(_map)

func _load_vectors() -> void:
	var f := FileAccess.open(ROADS_PATH, FileAccess.READ)
	if f:
		var d = JSON.parse_string(f.get_as_text())
		for w in (d.get("ways", []) if d else []):
			var tags: Dictionary = w.get("tags", {})
			var vs: Array = w.get("vertices", [])
			for i in range(vs.size() - 1):
				var _nm = tags.get("name")
				var _cls = tags.get("highway")
				_street_segments.append({
					"name": "" if _nm == null else str(_nm), "cls": "" if _cls == null else str(_cls),
					"a": Vector2(vs[i]["x"], vs[i]["z"]), "b": Vector2(vs[i + 1]["x"], vs[i + 1]["z"]),
				})
	# Named structures: OSM-named buildings + landmarks, for "what am I looking at".
	var bf := FileAccess.open(BUILDINGS_PATH, FileAccess.READ)
	if bf:
		var bd = JSON.parse_string(bf.get_as_text())
		for b in (bd.get("buildings", []) if bd else []):
			var tags: Dictionary = b.get("tags", {}) if b.get("tags") != null else {}
			var lid := str(b.get("landmark_id", ""))
			var _bn = tags.get("name")
			var nm := "" if _bn == null else str(_bn)
			if lid != "" and LANDMARK_NAMES.has(lid):
				nm = LANDMARK_NAMES[lid]
			if nm == "":
				continue
			var fp: Array = b.get("footprint", [])
			if fp.is_empty():
				continue
			var cx := 0.0
			var cz := 0.0
			for p in fp:
				cx += p["x"]; cz += p["z"]
			cx /= fp.size(); cz /= fp.size()
			var r := 0.0
			for p in fp:
				r = maxf(r, Vector2(p["x"] - cx, p["z"] - cz).length())
			_named.append({"name": nm, "pos": Vector2(cx, cz), "radius": maxf(r, 6.0), "landmark": lid != ""})
	var pf := FileAccess.open(POIS_PATH, FileAccess.READ)
	if pf:
		var pd = JSON.parse_string(pf.get_as_text())
		for key in ["points", "pois"]:
			for p in (pd.get(key, []) if pd else []):
				var _pn = p.get("name")
				var nm := "" if _pn == null else str(_pn)
				if nm != "" and p.has("x") and p.has("z"):
					_named.append({"name": nm, "pos": Vector2(p["x"], p["z"]), "radius": 8.0, "landmark": false})

func _find_player() -> Node3D:
	if is_instance_valid(_player):
		return _player
	var root := get_tree().current_scene
	if root:
		_player = root.find_child("Player", true, false) as Node3D
		if _player:
			_cam = _player.find_child("Camera3D", true, false) as Camera3D
	return _player

# --- readouts ---------------------------------------------------------------

func _nearest_street(p: Vector2) -> Dictionary:
	var best := {"d": 1e20, "name": ""}
	var second := {"d": 1e20, "name": ""}
	for s in _street_segments:
		var nm: String = s["name"]
		if nm == "":
			continue
		var a: Vector2 = s["a"]
		var ab: Vector2 = s["b"] - a
		var t: float = 0.0 if ab.length_squared() == 0.0 else clampf((p - a).dot(ab) / ab.length_squared(), 0.0, 1.0)
		var d := p.distance_to(a + ab * t)
		if d < best["d"]:
			if nm != best["name"]:
				second = best.duplicate()
			best = {"d": d, "name": nm}
		elif d < second["d"] and nm != best["name"]:
			second = {"d": d, "name": nm}
	return {"best": best, "second": second}

## What the player is looking at: ray from the camera, then match the hit point
## to the nearest named footprint. Falls back to the nearest named structure.
func _structure_text(p: Vector2) -> String:
	var target := Vector2.INF
	if _cam:
		var space := _cam.get_world_3d().direct_space_state
		var from := _cam.global_position
		var to := from - _cam.global_transform.basis.z * 150.0
		var hit := space.intersect_ray(PhysicsRayQueryParameters3D.create(from, to))
		if not hit.is_empty():
			target = Vector2(hit.position.x, hit.position.z)
	var probe := target if target != Vector2.INF else p
	var best := ""
	var best_d := 1e20
	var landmark := false
	for n in _named:
		var d: float = probe.distance_to(n["pos"]) - float(n["radius"])
		if d < best_d:
			best_d = d
			best = n["name"]
			landmark = n["landmark"]
	if best == "" or best_d > 25.0:
		return ""
	var prefix := "◆ " if landmark else "• "
	if target != Vector2.INF and best_d <= 6.0:
		return "%s%s" % [prefix, best]
	return "%s%s  (%dm)" % [prefix, best, int(maxf(best_d, 0.0))]

func _compass(deg: float) -> String:
	var dirs := ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
	return dirs[int(round(fposmod(deg, 360.0) / 22.5)) % 16]

func _process(delta: float) -> void:
	var capture := _is_capture_mode()
	var pl := _find_player()
	var on := not capture and pl != null
	_panel.visible = on and (show_location or show_coords)
	_map.visible = on and show_minimap
	if _hint_timer > 0.0:
		_hint_timer -= delta
	_hint.visible = on and _hint_timer > 0.0
	if not on:
		return

	var vp := get_viewport().get_visible_rect().size
	var p := Vector2(pl.global_position.x, pl.global_position.z)
	var lines: Array[String] = []
	if show_location:
		var ns := _nearest_street(p)
		var street: String = ns["best"]["name"]
		if street != "" and ns["second"]["name"] != "" and float(ns["second"]["d"]) < 35.0:
			street = "%s & %s" % [street, ns["second"]["name"]]
		if street != "":
			lines.append(street)
		var st := _structure_text(p)
		if st != "":
			lines.append(st)
		lines.append("%s · %s · %02d:%02d" % [_season_name(), _weather_name(),
			int(WorldState.hour), int(fposmod(WorldState.hour, 1.0) * 60.0)])
	if show_coords:
		# -Z is north in this project, so heading is measured from -Z.
		var fwd := -pl.global_transform.basis.z
		if _cam:
			fwd = -_cam.global_transform.basis.z
		var head_deg := rad_to_deg(atan2(fwd.x, -fwd.z))
		var pitch_deg := rad_to_deg(asin(clampf(fwd.y, -1.0, 1.0)))
		lines.append("x %.1f  y %.1f  z %.1f" % [pl.global_position.x, pl.global_position.y, pl.global_position.z])
		lines.append("look %s %.0f°  pitch %+.0f°  (%.2f, %.2f, %.2f)" % [
			_compass(head_deg), fposmod(head_deg, 360.0), pitch_deg, fwd.x, fwd.y, fwd.z])
	_panel.text = "\n".join(lines)
	_panel.position = Vector2(16, vp.y - _panel.size.y - (34 if _hint.visible else 16))
	_hint.position = Vector2(16, vp.y - 26)
	if _map.visible:
		_map.position = Vector2(vp.x - _map.size.x - 16, 16)
		_map.queue_redraw()

func _season_name() -> String:
	return ["Spring", "Summer", "Autumn", "Winter"][WorldState.season]

func _weather_name() -> String:
	return ["Clear", "Overcast", "Rain", "Snow", "Blizzard", "Fog"][WorldState.weather]

# --- minimap ----------------------------------------------------------------

## Clip a segment to the map rect (Liang-Barsky). Without this, long streets whose
## endpoints both fall outside the map were skipped entirely (streets vanished)
## and shorter ones drew outside the map box.
func _clip(a: Vector2, b: Vector2, r: Rect2) -> Array:
	var d := b - a
	var t0 := 0.0
	var t1 := 1.0
	var p := [-d.x, d.x, -d.y, d.y]
	var q := [a.x - r.position.x, r.end.x - a.x, a.y - r.position.y, r.end.y - a.y]
	for i in 4:
		if absf(p[i]) < 1e-9:
			if q[i] < 0.0:
				return []
			continue
		var t: float = q[i] / p[i]
		if p[i] < 0.0:
			t0 = maxf(t0, t)
		else:
			t1 = minf(t1, t)
	if t0 > t1:
		return []
	return [a + d * t0, a + d * t1]

func _draw_map() -> void:
	var pl := _find_player()
	if pl == null:
		return
	var span: float = _zooms[_zoom_idx]
	var c := _map.size * 0.5
	var p := Vector2(pl.global_position.x, pl.global_position.z)
	var sc := _map.size.x / span
	var rect := Rect2(Vector2.ZERO, _map.size)
	_map.draw_rect(rect, Color(0.07, 0.08, 0.09, 0.74))
	for s in _street_segments:
		var a: Vector2 = (s["a"] - p) * sc + c
		var b: Vector2 = (s["b"] - p) * sc + c
		var seg := _clip(a, b, rect)
		if seg.is_empty():
			continue
		var cls: String = s["cls"]
		var w := 3.0 if cls in ["primary", "secondary", "trunk"] else (2.0 if cls == "tertiary" else 1.0)
		var col := Color(0.96, 0.86, 0.55, 0.95) if w >= 3.0 else Color(0.85, 0.87, 0.9, 0.65)
		_map.draw_line(seg[0], seg[1], col, w)
	# landmarks as small markers
	for n in _named:
		if not n["landmark"]:
			continue
		var q: Vector2 = (n["pos"] - p) * sc + c
		if rect.has_point(q):
			_map.draw_circle(q, 3.0, Color(1.0, 0.75, 0.3, 0.95))
	var fwd := -pl.global_transform.basis.z
	if _cam:
		fwd = -_cam.global_transform.basis.z
	var head := Vector2(fwd.x, fwd.z)
	if head.length() > 0.001:
		head = head.normalized()
	_map.draw_circle(c, 4.0, Color(0.35, 0.8, 1.0))
	_map.draw_line(c, c + head * 14.0, Color(0.35, 0.8, 1.0), 2.0)
	_map.draw_rect(rect, Color(1, 1, 1, 0.18), false, 1.0)
	_map.draw_string(ThemeDB.fallback_font, Vector2(8, _map.size.y - 8),
		"%d m across   N ↑" % int(span), HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color(1, 1, 1, 0.7))

# --- input / screenshots ----------------------------------------------------

func _unhandled_key_input(event: InputEvent) -> void:
	if _is_capture_mode():
		return
	if not (event is InputEventKey) or not event.pressed or event.echo:
		return
	match event.keycode:
		KEY_F7: show_location = not show_location
		KEY_F8: show_minimap = not show_minimap
		KEY_F9: _zoom_idx = (_zoom_idx + 1) % _zooms.size()
		KEY_F10: show_coords = not show_coords
		KEY_F12: _screenshot(event.shift_pressed)

func _screenshot(hide_hud: bool) -> void:
	var pl := _find_player()
	var was_panel := _panel.visible
	var was_map := _map.visible
	var was_hint := _hint.visible
	if hide_hud:
		_panel.visible = false
		_map.visible = false
		_hint.visible = false
		await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var dir := ProjectSettings.globalize_path("res://..").path_join("screenshots")
	DirAccess.make_dir_recursive_absolute(dir)
	var head_deg := 0.0
	var pos := "0_0_0"
	if pl:
		var fwd := -(_cam.global_transform.basis.z if _cam else pl.global_transform.basis.z)
		head_deg = fposmod(rad_to_deg(atan2(fwd.x, -fwd.z)), 360.0)
		pos = "%d_%d_%d" % [int(pl.global_position.x), int(pl.global_position.y), int(pl.global_position.z)]
	var fname := "%s_%s_%s%03d_%s_%s_h%04.1f.png" % [
		Time.get_datetime_string_from_system().replace(":", "").replace("-", "").replace("T", "_"),
		pos, _compass(head_deg).to_lower(), int(head_deg),
		_season_name().to_lower(), _weather_name().to_lower(), WorldState.hour]
	var path := dir.path_join(fname)
	var err := img.save_png(path)
	print("screenshot: ", path, " (err %d)" % err)
	_hint.text = "saved screenshots/%s" % fname
	_hint_timer = 4.0
	if hide_hud:
		_panel.visible = was_panel
		_map.visible = was_map
		_hint.visible = was_hint

## --- queried by ticket_tool.gd so a bug report can name the place -------------
func nearest_street_name(p: Vector2) -> String:
	var ns := _nearest_street(p)
	return str(ns["best"]["name"])

func nearest_structure_name(p: Vector2) -> String:
	var best := ""
	var best_d := 1e20
	for n in _named:
		var d: float = p.distance_to(n["pos"]) - float(n["radius"])
		if d < best_d:
			best_d = d
			best = n["name"]
	return best if best_d <= 40.0 else ""
