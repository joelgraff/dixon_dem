extends CanvasLayer
## In-game bug reporter: screenshot, tag the things that are wrong, write a note,
## save a triage-ready ticket.
##
##   F11          enter/leave ticket mode (freezes the frame, frees the mouse)
##   left click   tag whatever is under the cursor
##   right click  remove the last tag
##   type         write the note
##   Enter        save the ticket      Esc  cancel
##
## A tag is not just a screen position: the tool raycasts into the world and records what
## was actually hit -- the owning system (Buildings / Roads / Terrain / Vegetation /
## Landmarks), the node path, the world coordinates, and the nearest named street and
## structure. That is the part that makes a ticket actionable: "the wall is black" is a
## guess, "Buildings/chunk_12_-9 at (1629, -1337)" is a lead.
##
## Tickets land in <project>/tickets/<timestamp>/ as ticket.md + shot.png, so they can be
## triaged as a batch. Nothing here runs during capture_mode.

const TICKET_DIR := "res://../tickets"

var _active := false
var _tags: Array = []          # {screen: Vector2, world: Vector3, system, node, street, structure}
var _note := ""
var _frozen: TextureRect
var _markers: Control
var _panel: Label
var _note_label: Label
var _player: Node3D
var _cam: Camera3D
var _saved_mouse_mode := Input.MOUSE_MODE_CAPTURED
var _flash := 0.0
var _flash_msg := ""
var _saving := false

func _ready() -> void:
	layer = 20
	process_mode = Node.PROCESS_MODE_ALWAYS   # keeps working while the tree is paused
	_frozen = TextureRect.new()
	_frozen.visible = false
	_frozen.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_frozen.stretch_mode = TextureRect.STRETCH_SCALE
	add_child(_frozen)
	_markers = Control.new()
	_markers.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_markers.draw.connect(_draw_markers)
	add_child(_markers)
	_fit_markers()
	_panel = _mk_label(16, 0.95)
	_note_label = _mk_label(19, 1.0)
	set_process(true)

func _mk_label(size: int, alpha: float) -> Label:
	var l := Label.new()
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", Color(1, 1, 1, alpha))
	l.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.85))
	l.add_theme_constant_override("shadow_offset_x", 1)
	l.add_theme_constant_override("shadow_offset_y", 1)
	l.visible = false
	add_child(l)
	return l

func _is_capture_mode() -> bool:
	var n: Node = self
	while n:
		if n.has_meta("capture_mode"):
			return true
		n = n.get_parent()
	return false

func _find_player() -> void:
	var root := get_tree().current_scene
	if root:
		_player = root.find_child("Player", true, false) as Node3D
		if _player:
			_cam = _player.find_child("Camera3D", true, false) as Camera3D

func _unhandled_input(event: InputEvent) -> void:
	if _is_capture_mode():
		return
	# Capture awaits two frames with the chrome hidden. Input in that window
	# would cancel or nest another save before the shot is taken.
	if _saving:
		get_viewport().set_input_as_handled()
		return
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_F11:
				if _active:
					_cancel()
				else:
					_enter()
				get_viewport().set_input_as_handled()
				return
			KEY_ESCAPE:
				if _active:
					_cancel()
					get_viewport().set_input_as_handled()
					return
			KEY_ENTER, KEY_KP_ENTER:
				if _active:
					_save()
					get_viewport().set_input_as_handled()
					return
			KEY_BACKSPACE:
				if _active and _note.length() > 0:
					_note = _note.substr(0, _note.length() - 1)
					get_viewport().set_input_as_handled()
					return
		if _active and event.unicode >= 32:
			_note += String.chr(event.unicode)
			get_viewport().set_input_as_handled()
			return
	if _active and event is InputEventMouseButton and event.pressed:
		if event.button_index == MOUSE_BUTTON_LEFT:
			_add_tag(event.position)
		elif event.button_index == MOUSE_BUTTON_RIGHT and not _tags.is_empty():
			_tags.pop_back()
		get_viewport().set_input_as_handled()

func _enter() -> void:
	_find_player()
	if _cam == null:
		return
	var hidden := _hide_chrome()
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	_restore_chrome(hidden)
	var tex := ImageTexture.create_from_image(img)
	_frozen.texture = tex
	_frozen.size = get_viewport().get_visible_rect().size
	_frozen.visible = true
	_fit_markers()
	_markers.visible = true
	_active = true
	set_meta("ticket_open", true)
	get_tree().root.set_meta("ui_cover", "ticket")
	_tags.clear()
	_note = ""
	_saved_mouse_mode = Input.mouse_mode
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	get_tree().paused = true                   # world holds still while tagging

func _cancel() -> void:
	if _saving:
		return
	_active = false
	set_meta("ticket_open", false)
	if str(get_tree().root.get_meta("ui_cover", "")) == "ticket":
		get_tree().root.remove_meta("ui_cover")
	_frozen.visible = false
	# A Control keeps whatever it last drew until something repaints it, so the circles
	# and leader lines stayed on screen after saving. Clear the tags AND force one more
	# redraw so the overlay actually paints empty, then hide it.
	_tags.clear()
	_markers.queue_redraw()
	_markers.visible = false
	get_tree().paused = false
	Input.mouse_mode = _saved_mouse_mode

## Raycast the frozen view and record WHAT was hit, not just where the cursor was.
func _add_tag(screen_pos: Vector2) -> void:
	var tag := {"screen": screen_pos, "world": Vector3.ZERO,
				"system": "(sky/nothing)", "node": "-", "distance_m": 0.0}
	if _cam:
		var from := _cam.project_ray_origin(screen_pos)
		var dir := _cam.project_ray_normal(screen_pos)
		var space := _cam.get_world_3d().direct_space_state
		var q := PhysicsRayQueryParameters3D.create(from, from + dir * 2000.0)
		var hit := space.intersect_ray(q)
		if not hit.is_empty():
			tag["world"] = hit.position
			tag["distance_m"] = from.distance_to(hit.position)
			var collider: Node = hit.collider
			tag["node"] = str(collider.get_path()).replace("/root/", "")
			tag["system"] = _owning_system(collider)
			tag["street"] = _nearest_street(hit.position)
			tag["structure"] = _nearest_structure(hit.position)
	_tags.append(tag)

## Walk up to the top-level system node so a ticket says "Roads" or "Buildings".
func _owning_system(n: Node) -> String:
	var known := ["Terrain", "Roads", "Bridges", "Buildings", "Vegetation", "Landmarks", "Atmosphere", "Player"]
	var cur: Node = n
	while cur:
		if cur.name in known:
			return str(cur.name)
		cur = cur.get_parent()
	return "(unknown)"

func _hud() -> Node:
	var root := get_tree().current_scene
	return root.find_child("HUD", true, false) if root else null

## The frozen frame is a viewport grab, so anything on screen is baked into it.
## Hide the play HUD and the atmosphere debug line, then put them back.
func _hide_chrome() -> Array:
	var saved: Array = []
	var root := get_tree().current_scene
	var nodes: Array = []
	var hud := _hud()
	if hud != null:
		nodes.append(hud)
	if root:
		var debug := root.find_child("DebugUI", true, false)
		if debug != null:
			nodes.append(debug)
	for n in nodes:
		saved.append({"node": n, "visible": n.visible})
		n.visible = false
	return saved

func _restore_chrome(saved: Array) -> void:
	for s in saved:
		var n: Node = s["node"]
		if is_instance_valid(n):
			n.visible = bool(s["visible"])

func _nearest_street(p: Vector3) -> String:
	var hud := _hud()
	if hud and hud.has_method("nearest_street_name"):
		return str(hud.call("nearest_street_name", Vector2(p.x, p.z)))
	return ""

func _nearest_structure(p: Vector3) -> String:
	var hud := _hud()
	if hud and hud.has_method("nearest_structure_name"):
		return str(hud.call("nearest_structure_name", Vector2(p.x, p.z)))
	return ""

func _process(delta: float) -> void:
	if _flash > 0.0:
		_flash -= delta
	if _saving:
		return          # chrome is deliberately hidden for the capture frame
	if _is_capture_mode():
		_panel.visible = false
		_note_label.visible = false
		return
	if not _active:
		_panel.visible = _flash > 0.0
		_note_label.visible = false
		if _flash > 0.0:
			_panel.text = _flash_msg
			_panel.position = Vector2(16, 60)
		return
	var vp := get_viewport().get_visible_rect().size
	_fit_markers()
	# Only the instructions live in the corner now; each tag's detail is drawn next to its
	# own marker (user feedback: the stacked list overlapped the HUD labels and you could
	# not tell which line went with which point).
	_panel.text = "BUG TICKET  -  click to tag, right-click undo, Enter save, Esc cancel"
	_panel.position = Vector2(16, 16)
	_panel.visible = true
	_note_label.text = "note: " + _note + "_"
	_note_label.position = Vector2(16, vp.y - 44)
	_note_label.visible = true
	_markers.queue_redraw()

func _save() -> void:
	if _saving:
		return
	if _cam == null:
		_cancel(); return
	var stamp := Time.get_datetime_string_from_system().replace(":", "").replace("-", "").replace("T", "_")
	var dir_path := ProjectSettings.globalize_path("res://..").path_join("tickets").path_join(stamp)
	DirAccess.make_dir_recursive_absolute(dir_path)

	# Image has no draw_string, so the viewport has to be captured after the overlay redraws.
	# Snapshot first: this function awaits, and a cancel must not blank the ticket it writes.
	_saving = true
	var tags_snap: Array = _tags.duplicate(true)
	var note_snap := _note
	_panel.visible = false
	_note_label.visible = false
	var hidden := _hide_chrome()
	_fit_markers()
	_markers.queue_redraw()
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	img.save_png(dir_path.path_join("shot.png"))
	_restore_chrome(hidden)
	_saving = false

	var md := "# Ticket %s\n\n" % stamp
	md += "**Note:** %s\n\n" % (note_snap if note_snap != "" else "(none)")
	if _player:
		md += "Player at (%.1f, %.1f, %.1f), " % [_player.global_position.x, _player.global_position.y, _player.global_position.z]
	md += "%s / %s / %02d:%02d\n\n" % [_season(), _weather(), int(WorldState.hour), int(fposmod(WorldState.hour, 1.0) * 60.0)]
	md += "| # | system | what was hit | world (x,y,z) | dist | street | structure |\n"
	md += "|---|---|---|---|---|---|---|\n"
	for i in tags_snap.size():
		var t: Dictionary = tags_snap[i]
		md += "| %d | **%s** | `%s` | %.1f, %.1f, %.1f | %.0f m | %s | %s |\n" % [
			i + 1, t["system"], t["node"], t["world"].x, t["world"].y, t["world"].z,
			t["distance_m"], str(t.get("street", "")), str(t.get("structure", ""))]
	md += "\nRe-shoot this view offline:\n```json\n"
	md += "[{\"name\":\"ticket_%s\",\"pos\":[%.1f,%.1f,%.1f],\"look_at\":[%.1f,%.1f,%.1f],\"fov\":%.0f,\"season\":\"%s\",\"weather\":\"%s\",\"hour\":%.1f}]\n" % [
		stamp, _cam.global_position.x, _cam.global_position.y, _cam.global_position.z,
		_cam.global_position.x - _cam.global_transform.basis.z.x * 30.0,
		_cam.global_position.y - _cam.global_transform.basis.z.y * 30.0,
		_cam.global_position.z - _cam.global_transform.basis.z.z * 30.0,
		_cam.fov, _season().to_lower(), _weather().to_lower(), WorldState.hour]
	md += "```\n"
	var f := FileAccess.open(dir_path.path_join("ticket.md"), FileAccess.WRITE)
	if f:
		f.store_string(md)
		f.close()
	print("ticket saved: ", dir_path)
	_flash_msg = "ticket saved -> tickets/%s  (%d tags)" % [stamp, tags_snap.size()]
	_flash = 4.0
	_cancel()

func _stamp_marker(img: Image, pos: Vector2, n: int) -> void:
	var r := 14
	var col := Color(1.0, 0.25, 0.1)
	for dy in range(-r, r + 1):
		for dx in range(-r, r + 1):
			var d := sqrt(float(dx * dx + dy * dy))
			if d > r - 2.5 and d <= r:
				var px := int(pos.x) + dx
				var py := int(pos.y) + dy
				if px >= 0 and py >= 0 and px < img.get_width() and py < img.get_height():
					img.set_pixel(px, py, col)
	# a short tail so the marker reads even on a busy frame
	for k in range(r, r + 12):
		var px := int(pos.x) + k
		var py := int(pos.y) - k
		if px >= 0 and py >= 0 and px < img.get_width() and py < img.get_height():
			img.set_pixel(px, py, col)

func _season() -> String:
	return ["Spring", "Summer", "Autumn", "Winter"][WorldState.season]

func _weather() -> String:
	return ["Clear", "Overcast", "Rain", "Snow", "Blizzard", "Fog"][WorldState.weather]

## Default anchors leave this Control at size (0, 0). Leader placement used to
## read that and run every label off the left edge.
func _fit_markers() -> void:
	var rect := get_viewport().get_visible_rect()
	if _markers.position != rect.position or _markers.size != rect.size:
		_markers.position = rect.position
		_markers.size = rect.size

## Horizontal leader on the side with more room. The label sits above the line,
## and drops below it when the glyphs would cross the top of the viewport.
func _marker_layout(p: Vector2, text_width: float, vp: Vector2, ascent: float, descent: float) -> Dictionary:
	var margin := 10.0
	var lead := maxf(text_width + 12.0, 90.0)
	var gap := 16.0
	var space_right := vp.x - margin - (p.x + gap)
	var space_left := p.x - gap - margin
	var dir := 1.0 if space_right >= space_left else -1.0
	var room: float = space_right if dir > 0.0 else space_left
	var draw_lead := minf(lead, maxf(room, 0.0))
	var edge := maxf(margin, vp.x - margin)
	var x_near := clampf(p.x + gap * dir, margin, edge)
	var x_far := clampf(x_near + draw_lead * dir, margin, edge)
	var text_x := minf(x_near, x_far) + 6.0
	var max_text_x := vp.x - margin - text_width
	if max_text_x < margin:
		text_x = margin
	else:
		text_x = clampf(text_x, margin, max_text_x)
	var text_y := p.y - 7.0
	if text_y - ascent < margin:
		text_y = p.y + 7.0 + ascent
	var min_baseline := margin + ascent
	var max_baseline := vp.y - margin - descent
	if max_baseline < min_baseline:
		text_y = min_baseline
	else:
		text_y = clampf(text_y, min_baseline, max_baseline)
	return {"x0": x_near, "x1": x_far, "text_x": text_x, "text_y": text_y}

## Draws the numbered tag markers over the frozen frame while tagging.
func _draw_markers() -> void:
	if not _active:
		return
	var font := ThemeDB.fallback_font
	var rect := get_viewport().get_visible_rect()
	var vp := rect.size
	var font_size := 16
	var ascent := font.get_ascent(font_size)
	var descent := font.get_descent(font_size)
	for i in _tags.size():
		var t: Dictionary = _tags[i]
		var p: Vector2 = t["screen"] - rect.position
		var label := "[%d] %s" % [i + 1, t["system"]]
		var detail := str(t.get("structure", ""))
		if detail == "":
			detail = str(t.get("street", ""))
		if detail != "":
			label += "  -  " + detail
		var tw: float = font.get_string_size(label, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x
		var lay: Dictionary = _marker_layout(p, tw, vp, ascent, descent)
		var x0: float = lay["x0"]
		var x1: float = lay["x1"]
		var text_x: float = lay["text_x"]
		var text_y: float = lay["text_y"]
		_markers.draw_circle(p, 14.0, Color(1.0, 0.25, 0.1, 0.25))
		_markers.draw_arc(p, 14.0, 0.0, TAU, 32, Color(1.0, 0.35, 0.12), 2.5)
		_markers.draw_line(Vector2(x0, p.y), Vector2(x1, p.y), Color(1.0, 0.35, 0.12), 2.0)
		_markers.draw_string(font, Vector2(text_x + 1, text_y + 1), label,
			HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, Color(0, 0, 0, 0.85))
		_markers.draw_string(font, Vector2(text_x, text_y), label,
			HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, Color(1.0, 0.62, 0.35))
