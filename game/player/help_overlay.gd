extends CanvasLayer
## F1 toggles this list. F5 cycles the season. Shift+F5 is noclip.

const BODY := """Move
  W A S D          walk
  Shift            run
  Ctrl             crouch
  Space            jump
  Mouse            look
  Esc              release the mouse    click to capture it again

World
  F1               this help
  F5               season
  F2               weather
  F3 / F4          hour back / forward
  Shift+F5         noclip
  F6               debug readout (position, FPS, season)
  F7               street and building names
  F8               minimap
  F9               minimap zoom
  F10              coordinates and look direction
  F12              screenshot
  Shift+F12        screenshot with the HUD hidden

Fixes
  F11              bug ticket (click what's wrong, type a note, Enter)
  B                building editor
                   click a wall, Tab changes field, arrows change the value
                   storeys go to 6; ground double is a tall first floor; awnings none removes them
                   color picks the brick or siding, including brick_red
                   C composes that one building (arches, bays, a second roof, towers) and rebuilds it as you edit
                   N flips inside-out walls, Enter saves the chunk, Esc closes

F11 is for a fault that shows up on every surface of one material.
B is for one building: wrong form, storeys, roof, dressing, or flipped walls."""

var _open := false
var _panel: Label

func _ready() -> void:
	layer = 40
	process_mode = Node.PROCESS_MODE_ALWAYS
	var dim := ColorRect.new()
	dim.color = Color(0.04, 0.05, 0.06, 0.94)
	dim.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(dim)
	dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	_panel = Label.new()
	_panel.text = "Keys\n\n" + BODY + "\n\nF1 or Esc closes this."
	add_child(_panel)
	_panel.set_anchors_preset(Control.PRESET_FULL_RECT)
	_panel.offset_left = 48
	_panel.offset_top = 36
	_panel.offset_right = -48
	_panel.offset_bottom = -36
	_panel.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_panel.add_theme_font_size_override("font_size", 18)
	_panel.add_theme_color_override("font_color", Color(0.95, 0.95, 0.93))
	_panel.add_theme_constant_override("line_spacing", 4)
	visible = false

func _unhandled_input(event: InputEvent) -> void:
	if _is_capture_mode():
		return
	if not (event is InputEventKey) or not event.pressed or event.echo:
		return
	if event.keycode == KEY_F1 and not event.shift_pressed:
		if _open:
			_set_open(false)
		else:
			var edit := get_parent().get_node_or_null("BuildingEdit") if get_parent() else null
			if edit != null and edit._open:
				edit._close()
			_set_open(true)
		get_viewport().set_input_as_handled()
		return
	if _open and event.keycode == KEY_ESCAPE:
		_set_open(false)
		get_viewport().set_input_as_handled()

func _set_open(open: bool) -> void:
	_open = open
	visible = open
	if open:
		get_tree().root.set_meta("ui_cover", "help")
	elif str(get_tree().root.get_meta("ui_cover", "")) == "help":
		get_tree().root.remove_meta("ui_cover")

func close() -> void:
	_set_open(false)

func _is_capture_mode() -> bool:
	var n: Node = self
	while n:
		if n.has_meta("capture_mode"):
			return true
		n = n.get_parent()
	return false
