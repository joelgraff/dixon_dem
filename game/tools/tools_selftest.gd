extends Node
## Headless check for the in-game tools, without loading the city.
##
##   godot --headless --path game res://tools/tools_selftest.tscn
##
## Covers the building editor's first-save path (the missing override file
## used to freeze the paused game) and the help overlay's key list.

func _ready() -> void:
	_run.call_deferred()

func _run() -> void:
	var fails: PackedStringArray = []
	_test_help(fails)
	_test_editor(fails)
	_test_front(fails)
	_test_hints(fails)
	_test_composed(fails)
	_test_footprint_override(fails)
	if fails.is_empty():
		print("SELFTEST OK")
		get_tree().quit(0)
		return
	for item in fails:
		print("SELFTEST FAIL: ", item)
	get_tree().quit(1)

func _test_help(fails: PackedStringArray) -> void:
	var help: Node = load("res://player/help_overlay.gd").new()
	add_child(help)
	if help.get_child_count() != 2:
		fails.append("help overlay built %d children, expected the dimmer and one label" % help.get_child_count())
	var open_help := _key(KEY_F1, false)
	help._unhandled_input(open_help)
	if not help.visible:
		fails.append("F1 did not open help")
	if str(help.get_tree().root.get_meta("ui_cover", "")) != "help":
		fails.append("help did not cover the HUD")
	var season := _key(KEY_F1, true)
	help._unhandled_input(season)
	if not help.visible:
		fails.append("Shift+F1 closed help; that key is not the help toggle")
	help._unhandled_input(_key(KEY_ESCAPE, false))
	if help.visible:
		fails.append("Esc did not close help")
	if str(help.get_tree().root.get_meta("ui_cover", "")) != "":
		fails.append("closing help left the HUD covered")
	help.queue_free()

func _test_editor(fails: PackedStringArray) -> void:
	var edit: Node = load("res://player/building_edit.gd").new()
	add_child(edit)
	if edit.get_child_count() != 1:
		fails.append("building editor built %d children, expected one panel" % edit.get_child_count())
	var path := "user://tools_selftest_overrides.json"
	var abs_path := ProjectSettings.globalize_path(path)
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(abs_path)
	edit.override_path = path
	edit._record = {
		"id": "1010753803",
		"form": "party_wall_commercial",
		"storeys": 2,
		"roof": "flat_parapet",
		"roof_axis": "side",
		"dressing": "italianate",
		"material": "brick",
		"porch": "none",
		"flip_normals": false,
	}
	if not edit._write_override():
		fails.append("first override write failed when the file did not exist")
		return
	edit._record["id"] = "2"
	edit._record["form"] = "bungalow"
	edit._record["dressing"] = "craftsman"
	edit._record["flip_normals"] = true
	if not edit._write_override():
		fails.append("second override write failed")
		return
	var parsed: Variant = edit._read_json(path)
	if not (parsed is Dictionary):
		fails.append("override file was not a dictionary")
		return
	var buildings: Dictionary = parsed.get("buildings", {})
	var first: Variant = buildings.get("1010753803")
	var second: Variant = buildings.get("2")
	if not (first is Dictionary) or first.get("dressing") != "italianate":
		fails.append("first building was not kept when the second was saved: %s" % str(parsed))
	if not (second is Dictionary) or second.get("form") != "bungalow" or second.get("flip_normals") != true:
		fails.append("second building did not round-trip: %s" % str(second))
	edit._field = 0
	edit._step(1)
	if edit._record["form"] != "cross_gable":
		fails.append("form did not step from bungalow to cross_gable, got %s" % str(edit._record["form"]))
	edit._field = edit.FIELDS.size() - 1
	edit._record["material"] = "limestone"
	edit._step(1)
	if edit._record["material"] != "clapboard":
		fails.append("material did not wrap, got %s" % str(edit._record["material"]))
	DirAccess.remove_absolute(abs_path)
	edit.queue_free()

func _test_front(fails: PackedStringArray) -> void:
	var edit: Node = load("res://player/building_edit.gd").new()
	add_child(edit)
	var building: Dictionary = edit._footprint("115768678")
	if building.is_empty():
		fails.append("footprint 115768678 not found")
		return
	var points: Array = []
	for p in building["footprint"]:
		points.append([float(p["x"]), float(p["z"])])
	var front: Array = edit.street_front(points)
	if front.size() != 2 or absf(Vector2(front[0], front[1]).length() - 1.0) > 0.001:
		fails.append("front for 115768678 is not a unit vector: %s" % str(front))
	else:
		print("front of 115768678: ", front)
	if not edit.street_front([]).is_empty():
		fails.append("a footprint with no points has no front")
	if not edit.street_front([[9000000.0, 9000000.0], [9000010.0, 9000000.0], [9000010.0, 9000010.0]]).is_empty():
		fails.append("a footprint far from any road should have no front")
	edit.queue_free()

func _test_hints(fails: PackedStringArray) -> void:
	var script: GDScript = load("res://player/building_edit.gd")
	var hints: Dictionary = script.composer_hints({
		"id": "1", "form": "side_gable", "storeys": 1.5, "roof": "gable", "roof_axis": "side",
		"material": "brick", "color": "brick_buff", "dressing": "italianate", "x": 3.0,
	})
	if hints.get("color") != "brick_buff" or hints.get("roof_axis") != "side" or hints.get("storeys") != 1.5:
		fails.append("Composer hints lost fields: %s" % str(hints))
	if hints.has("id") or hints.has("x"):
		fails.append("Composer hints carry more than the editor's fields: %s" % str(hints))
	if script.composer_hints({"color": "auto"}).has("color"):
		fails.append("an automatic color is not a hint")
	var manifest: Variant = JSON.parse_string(FileAccess.get_file_as_string(ProjectSettings.globalize_path("res://data/materials_manifest.json")))
	if not (manifest is Dictionary) or script.materials_version() != str(manifest.get("hash")) or script.materials_version() == "":
		fails.append("X should send the material list's hash: got '%s'" % script.materials_version())

func _test_composed(fails: PackedStringArray) -> void:
	var edit: Node = load("res://player/building_edit.gd").new()
	add_child(edit)
	var dir := "user://selftest_composed"
	DirAccess.make_dir_recursive_absolute(dir)
	edit.composed_dir = dir
	var file := FileAccess.open(dir.path_join("7.json"), FileAccess.WRITE)
	file.store_string('{"format": "dixon-composed", "near": {}}')
	file.close()
	edit._record = {"id": "7"}
	if edit.composed_state("7") != "in_use":
		fails.append("a sent design should be in use")
	edit._record["composed"] = false
	if edit.composed_state("7") != "reverted":
		fails.append("composed=false should read as reverted")
	if edit.composed_state("8") != "none":
		fails.append("a building nothing was sent for has no design")
	DirAccess.remove_absolute(ProjectSettings.globalize_path(dir.path_join("7.json")))
	edit.queue_free()

func _test_footprint_override(fails: PackedStringArray) -> void:
	var edit: Node = load("res://player/building_edit.gd").new()
	add_child(edit)
	var dir := "user://selftest_footprints"
	DirAccess.make_dir_recursive_absolute(dir)
	edit.footprint_overrides_dir = dir
	edit._footprints = {"7": {"id": 7, "footprint": [{"x": 0, "z": 0}, {"x": 10, "z": 0}, {"x": 10, "z": 8}, {"x": 0, "z": 8}]}}
	if edit._footprint("7").get("override", false):
		fails.append("a building with no override should export its traced outline")
	var file := FileAccess.open(dir.path_join("7.json"), FileAccess.WRITE)
	file.store_string('{"format": "dixon-footprint-override", "id": "7", "footprint": [[0, 0], [10, 0], [10, 6], [0, 6]], "based_on": {"source": "osm", "hash": "4-441db1ba"}}')
	file.close()
	var corrected: Dictionary = edit._footprint("7")
	if not corrected.get("override", false) or corrected["footprint"][2]["x"] != 10.0 or corrected["footprint"][2]["z"] != 6.0:
		fails.append("the corrected outline should be exported: %s" % str(corrected))
	if corrected.get("based_on", {}).get("hash") != "4-441db1ba" or corrected.get("source_footprint", []).size() != 4:
		fails.append("the export should say what the correction replaced: %s" % str(corrected))
	if edit._footprints["7"]["footprint"][2]["z"] != 8:
		fails.append("the traced outline should be left as it was")
	DirAccess.rename_absolute(ProjectSettings.globalize_path(dir.path_join("7.json")), ProjectSettings.globalize_path(dir.path_join("7.json.off")))
	if not edit.footprint_override("7").is_empty():
		fails.append("a set-aside override should not be used")
	DirAccess.remove_absolute(ProjectSettings.globalize_path(dir.path_join("7.json.off")))
	edit.queue_free()

func _key(code: Key, shift: bool) -> InputEventKey:
	var event := InputEventKey.new()
	event.pressed = true
	event.keycode = code
	event.shift_pressed = shift
	return event
