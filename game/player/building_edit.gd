extends CanvasLayer
## Point at a building and correct its template, then rebuild just that chunk.
##
##   B            open / close
##   left click   select the building under the cursor
##   Tab          next field
##   Left / Right change the field
##   C            compose this building, then rebuild just it as the knobs change
##   N            flip inside-out walls on this building
##   X            open this building's footprint in Building Composer (and save it to exports/composer)
##   I            use the design Composer sent back for this building (Send to game)
##   R            revert this building to the one the game generates (I brings the design back)
##   O            put back the outline the game traced, in place of one corrected in Composer
##   Enter        write the override and rebuild the chunk
##   Esc          close
##
## Wrong brick, siding, storeys, roof, or a single building whose walls face
## inward are fixed here. A bug that affects every wall of one material (a
## shader, a missing texture) is not a property of one footprint — use F11
## and file a ticket.

const INDEX_PATH := "res://buildings/_build/template_index.json"
const OVERRIDE_PATH := "res://data/building_overrides.json"
const BUILD_DIR := "res://buildings/_build/"
const CHUNK_M := 200.0
## Where each building's footprint is (OSM, then Microsoft), and where X writes it for Building Composer.
const FOOTPRINT_PATHS := ["res://data/buildings.json", "res://data/buildings_ms.json"]
const COMPOSER_EXPORT_DIR := "res://../exports/composer"
## Where Building Composer's "Send to game" leaves each building (pipeline/buildings/composed.py reads it).
const COMPOSED_DIR := "res://data/composed"
## Outlines corrected in Composer's footprint editor (its "Save footprint to game";
## pipeline/buildings/footprints.py applies them). O turns one off by renaming it <id>.json.off.
const FOOTPRINT_OVERRIDES_DIR := "res://data/footprint_overrides"
## Streets a building can face. Alleys, paths and the like only count when no street is near.
const ROADS_PATH := "res://data/roads.json"
const STREET_CLASSES := ["primary", "primary_link", "secondary", "tertiary", "tertiary_link", "residential", "unclassified", "pedestrian"]
const FRONT_SEARCH_M := 250.0
## Building Composer: the page X opens (override with BUILDING_COMPOSER_URL), and
## the checkout it serves from when nothing answers there (BUILDING_COMPOSER_DIR;
## by default the building-composer folder beside this project).
const COMPOSER_URL := "http://localhost:8000/index.html"
const COMPOSER_DIR := "res://../../building-composer"
const COMPOSER_SERVER := "res://tools/composer_server.py"

const FIELDS := ["form", "storeys", "ground", "awnings", "roof", "roof_axis", "dressing", "color", "material"]
const CHOICES := {
	"form": ["side_gable", "front_gable", "gabled_ell", "foursquare", "bungalow", "cross_gable", "ranch",
		"party_wall_commercial", "one_story_store", "civic_block", "church_nave", "industrial", "garage"],
	"storeys": [1, 1.5, 2, 2.5, 3, 4, 5, 6],
	"ground": ["normal", "double"],
	"awnings": ["none", "some", "row"],
	"color": ["auto", "brick_red", "brick_buff", "brick_rose", "brick_dark", "brick_cream",
		"limestone", "siding_white", "siding_gray", "siding_sage", "siding_blue", "siding_butter"],
	"roof": ["gable", "hip", "pyramidal", "flat_parapet", "gambrel"],
	"roof_axis": ["front", "side"],
	"dressing": ["plain", "italianate", "folk_victorian", "craftsman", "commercial_1900", "midcentury"],
	"material": ["clapboard", "brick", "limestone"],
}

## Overridable so the self-test can write a throwaway file instead of the real overrides.
var override_path: String = OVERRIDE_PATH
var composed_dir: String = COMPOSED_DIR
var footprint_overrides_dir: String = FOOTPRINT_OVERRIDES_DIR
var _open := false
var _index: Dictionary = {}
var _record: Dictionary = {}
var _field := 0
var _busy := false
var _status := ""
var _compose_mode := false
var _knob := 0
var _summary: Array = []
const KNOBS := ["preset", "face", "roof", "storeys", "shape", "bays", "per_bay",
	"window_h", "window_w", "upper_h", "front", "color", "volumes", "rear", "towers", "belfry"]
var _plate: ColorRect
var _panel: Label
var _cam: Camera3D
var _footprints: Dictionary = {}
var _streets: Array = []
var _lanes: Array = []

func _ready() -> void:
	layer = 21
	process_mode = Node.PROCESS_MODE_ALWAYS
	_plate = ColorRect.new()
	_plate.color = Color(0.05, 0.06, 0.07, 0.94)
	_plate.position = Vector2(16, 16)
	_plate.visible = false
	_plate.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_plate)
	_panel = Label.new()
	_panel.position = Vector2(14, 12)
	_panel.add_theme_font_size_override("font_size", 16)
	_panel.add_theme_color_override("font_color", Color(1, 1, 1))
	_panel.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.85))
	_plate.add_child(_panel)
	_load_index()

func _unhandled_input(event: InputEvent) -> void:
	if _ticket_open():
		return
	if not (event is InputEventKey) or not event.pressed or event.echo:
		if _open and event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
			_select_at(event.position)
			get_viewport().set_input_as_handled()
		return
	if event.keycode == KEY_B and not _open and not _busy:
		_enter()
		get_viewport().set_input_as_handled()
		return
	if not _open:
		return
	get_viewport().set_input_as_handled()
	if _busy:
		return
	match event.keycode:
		KEY_ESCAPE:
			_close()
		KEY_C:
			_compose_mode = true
			_knob = 0
			_compose_call("", 0)
		KEY_TAB:
			if _compose_mode:
				_knob = (_knob + 1) % KNOBS.size()
			else:
				_field = (_field + 1) % FIELDS.size()
			_refresh()
		KEY_LEFT, KEY_BRACKETLEFT:
			if _compose_mode:
				_compose_call(KNOBS[_knob], -1)
			else:
				_step(-1)
		KEY_RIGHT, KEY_BRACKETRIGHT:
			if _compose_mode:
				_compose_call(KNOBS[_knob], 1)
			else:
				_step(1)
		KEY_N:
			_record["flip_normals"] = not bool(_record.get("flip_normals", false))
			_refresh()
		KEY_X:
			_export_composer()
		KEY_I:
			_use_composed(true)
		KEY_R:
			_use_composed(false)
		KEY_O:
			_revert_footprint()
		KEY_ENTER, KEY_KP_ENTER:
			_apply()

func _ticket_open() -> bool:
	var ticket := get_parent().get_node_or_null("TicketTool") if get_parent() else null
	return ticket != null and bool(ticket.get_meta("ticket_open", false))

func _enter() -> void:
	_load_index()
	var root := get_tree().current_scene
	var player := root.find_child("Player", true, false) if root else null
	_cam = player.find_child("Camera3D", true, false) if player else null
	var help := get_parent().get_node_or_null("HelpOverlay") if get_parent() else null
	if help != null and help.has_method("close"):
		help.close()
	_open = true
	_compose_mode = false
	_summary = []
	_status = "Click a building. C composes it."
	_record = {}
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	get_tree().paused = true
	get_tree().root.set_meta("ui_cover", "edit")
	_plate.visible = true
	_refresh()

func _close() -> void:
	_open = false
	_compose_mode = false
	_drop_preview()
	_plate.visible = false
	if str(get_tree().root.get_meta("ui_cover", "")) == "edit":
		get_tree().root.remove_meta("ui_cover")
	get_tree().paused = false
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _load_index() -> void:
	_index = _read_json(INDEX_PATH)
	if _index == null:
		_index = {}

func _select_at(screen_pos: Vector2) -> void:
	if _cam == null:
		_status = "No camera."
		_refresh()
		return
	var space := _cam.get_world_3d().direct_space_state
	var origin := _cam.project_ray_origin(screen_pos)
	var end := origin + _cam.project_ray_normal(screen_pos) * 500.0
	var hit := space.intersect_ray(PhysicsRayQueryParameters3D.create(origin, end))
	if hit.is_empty():
		_status = "Nothing under the cursor."
		_refresh()
		return
	var body: Object = hit.get("collider")
	if body == null or not body.has_meta("building_ids"):
		_status = "That is not a tagged building. Restart so the new scene loads, then try again."
		_refresh()
		return
	var ids: Array = body.get_meta("building_ids")
	var shape_i := int(hit.get("shape", -1))
	if shape_i < 0 or shape_i >= ids.size():
		_status = "Hit a building chunk but not a single footprint."
		_refresh()
		return
	var bid := str(int(ids[shape_i]))
	if not _index.has(bid):
		_status = "Building %s is not in the template index." % bid
		_refresh()
		return
	_compose_mode = false
	_summary = []
	_record = (_index[bid] as Dictionary).duplicate()
	_record["id"] = bid
	var saved: Variant = _read_json(override_path)
	if saved is Dictionary:
		var prior_buildings: Variant = saved.get("buildings", {})
		if prior_buildings is Dictionary:
			var prior: Variant = prior_buildings.get(bid, {})
			if prior is Dictionary and prior.get("compose") is Dictionary:
				_record["compose"] = prior["compose"]
			if prior is Dictionary and prior.get("composed") == false:
				_record["composed"] = false
	if not _record.has("ground"):
		_record["ground"] = "normal"
	if not _record.has("awnings"):
		_record["awnings"] = "some"
	if not _record.has("color"):
		_record["color"] = "auto"
	_field = 0
	_status = "Selected."
	_refresh()

func _step(direction: int) -> void:
	if _record.is_empty():
		return
	var key: String = FIELDS[_field]
	var choices: Array = CHOICES[key]
	var current = _record.get(key)
	var at := 0
	for i in choices.size():
		if str(choices[i]) == str(current):
			at = i
			break
	_record[key] = choices[(at + direction) % choices.size()]
	_refresh()

func _refresh() -> void:
	if _record.is_empty():
		_panel.text = "Building editor\n%s\nClick a wall. Esc closes.\nA shader bug on every wall of one material is an F11 ticket, not this tool." % _status
		_fit_plate()
		return
	var lines := ["Building %s   chunk %s,%s" % [_record.get("id"), _record.get("cx"), _record.get("cz")]]
	if _compose_mode and not _summary.is_empty():
		lines.append("Compose")
		for i in _summary.size():
			var row: Array = _summary[i]
			var mark := ">" if i == _knob else " "
			lines.append("%s %s: %s" % [mark, row[0], row[1]])
		lines.append(_status)
		lines.append("Arrows change this building now. Enter saves it. Esc closes.")
	else:
		for i in FIELDS.size():
			var mark := ">" if i == _field else " "
			lines.append("%s %s: %s" % [mark, FIELDS[i], _record.get(FIELDS[i])])
		lines.append("  flip normals: %s" % ("yes" if _record.get("flip_normals") else "no"))
		match composed_state(str(_record["id"])):
			"in_use":
				lines.append("  Composer design in use (R reverts to the generated building)")
			"reverted":
				lines.append("  Composer design available, generated building in use (I brings it back)")
		if not footprint_override(str(_record["id"])).is_empty():
			lines.append("  Outline corrected in Composer (O puts back the traced one)")
		lines.append(_status)
		lines.append("C composes. Tab field, arrows change, N flip walls, X opens in Composer, I / R use / revert its design, O traced outline, Enter saves, Esc closes")
	_panel.text = "\n".join(lines)
	_fit_plate()

func _fit_plate() -> void:
	_panel.reset_size()
	_plate.size = _panel.size + Vector2(28, 24)

func _apply() -> void:
	if _record.is_empty() or _busy:
		return
	_busy = true
	_status = "Rebuilding this chunk…"
	_refresh()
	await get_tree().process_frame
	if not _write_override():
		_status = "Could not save the override. Esc still closes."
		_busy = false
		_refresh()
		return
	var cx := int(_record.get("cx", floor(float(_record.get("x", 0.0)) / CHUNK_M)))
	var cz := int(_record.get("cz", floor(float(_record.get("z", 0.0)) / CHUNK_M)))
	var code := _run_plan(cx, cz)
	if code != 0:
		_status = "Rebuild failed (exit %d). The override is saved." % code
		_busy = false
		_refresh()
		return
	_reload_chunk(cx, cz)
	_drop_preview()
	_status = "Saving the scene so this survives a restart…"
	_refresh()
	await get_tree().process_frame
	var saved := _persist_scene()
	if saved:
		_status = "Chunk %d,%d updated. It will still be changed after a restart." % [cx, cz]
	else:
		_status = "Chunk %d,%d looks right now, but a restart will show the old scene." % [cx, cz]
	_busy = false
	_refresh()

## What Composer has done for a building: "none" (nothing sent), "in_use" (its
## design is what the pipeline builds), or "reverted" (sent, but the override
## turns it off).
func composed_state(bid: String) -> String:
	var data: Variant = _read_json(composed_dir.path_join("%s.json" % bid))
	if not (data is Dictionary) or data.get("format") != "dixon-composed":
		return "none"
	if _record.get("composed") == false:
		return "reverted"
	return "in_use"

## I takes the design Composer sent, R goes back to the generated building; either
## way the override is saved and the chunk rebuilt, so it also survives a restart.
func _use_composed(wanted: bool) -> void:
	if _record.is_empty():
		_status = "Click a building first."
		_refresh()
		return
	var state := composed_state(str(_record["id"]))
	if state == "none":
		_status = "Composer has not sent a design for this building (X opens it there; Send to game there)."
		_refresh()
		return
	if wanted == (state == "in_use"):
		_status = "Already %s." % ("using the Composer design" if wanted else "using the generated building")
		_refresh()
		return
	if wanted:
		_record.erase("composed")
	else:
		_record["composed"] = false
	_apply()

func _preset_name() -> String:
	var form := str(_record.get("form", ""))
	if form == "church_nave":
		return "church"
	if form == "industrial":
		return "powerhouse"
	return "block"

func _ground_y() -> float:
	if not (_record.has("x") and _record.has("z")):
		return 0.0
	return TerrainHeight.get_height(float(_record["x"]), float(_record["z"]))

## Rebuild only this footprint. The city pack still waits for Enter.
func _compose_call(op_key: String, direction: int) -> void:
	if _record.is_empty() or not _record.has("id"):
		_status = "Click a building first."
		_refresh()
		return
	var spec := {
		"id": str(_record["id"]),
		"ground_y": _ground_y(),
		"preset": _preset_name(),
		"flip_normals": bool(_record.get("flip_normals", false)),
	}
	if _record.get("compose") is Dictionary:
		spec["compose"] = _record["compose"]
	if op_key != "":
		spec["op"] = {"key": op_key, "dir": direction}
	var spec_path := ProjectSettings.globalize_path("user://compose_spec.json")
	var out_path := ProjectSettings.globalize_path("user://compose_mesh.json")
	var spec_file := FileAccess.open(spec_path, FileAccess.WRITE)
	if spec_file == null:
		_status = "Could not write the compose request."
		_refresh()
		return
	spec_file.store_string(JSON.stringify(spec))
	spec_file.close()
	var root := ProjectSettings.globalize_path("res://..")
	var python := root.path_join(".venv/bin/python")
	var script := root.path_join("pipeline/buildings/compose_one.py")
	var output: Array = []
	var code := OS.execute(python, [script, spec_path, out_path], output, true)
	if code != 0:
		_status = "Compose failed (exit %d)." % code
		push_warning("compose: %s" % "\n".join(output))
		_refresh()
		return
	var result: Variant = _read_json(out_path)
	if not (result is Dictionary) or not (result.get("compose") is Dictionary):
		_status = "Compose returned nothing."
		_refresh()
		return
	_record["compose"] = result["compose"]
	_summary = result.get("summary", [])
	_show_preview(result.get("near", {}))
	_status = "Preview updated. Enter saves it into the city."
	_refresh()

func _show_preview(groups: Dictionary) -> void:
	var scene := get_tree().current_scene
	if scene == null or groups.is_empty():
		return
	var manifest: Variant = _read_json(BUILD_DIR + "manifest.json")
	var materials := {}
	if manifest is Dictionary:
		for key in manifest["materials"].keys():
			materials[key] = load(manifest["materials"][key])
	var node := scene.get_node_or_null("ComposePreview") as MeshInstance3D
	if node == null:
		node = MeshInstance3D.new()
		node.name = "ComposePreview"
		scene.add_child(node)
	node.mesh = _build_array_mesh(groups, materials)

func _drop_preview() -> void:
	var scene := get_tree().current_scene
	if scene == null:
		return
	var node := scene.get_node_or_null("ComposePreview")
	if node != null:
		node.queue_free()

func _write_override() -> bool:
	# The file is missing until the first edit. A typed Dictionary cannot hold that null.
	var parsed: Variant = _read_json(override_path)
	var all: Dictionary = parsed if parsed is Dictionary else {}
	var raw: Variant = all.get("buildings", {})
	var buildings: Dictionary = raw if raw is Dictionary else {}
	buildings[str(_record["id"])] = {
		"form": _record["form"],
		"storeys": _record["storeys"],
		"roof": _record["roof"],
		"roof_axis": _record["roof_axis"],
		"dressing": _record["dressing"],
		"material": _record["material"],
		"ground": _record.get("ground", "normal"),
		"awnings": _record.get("awnings", "some"),
		"color": _record.get("color", "auto"),
		"porch": _record.get("porch", "none"),
		"flip_normals": bool(_record.get("flip_normals", false)),
	}
	if _record.get("compose") is Dictionary:
		buildings[str(_record["id"])]["compose"] = _record["compose"]
	if _record.get("composed") == false:
		buildings[str(_record["id"])]["composed"] = false
	all["buildings"] = buildings
	var file := FileAccess.open(override_path, FileAccess.WRITE)
	if file == null:
		push_error("building edit: cannot write %s" % override_path)
		return false
	file.store_string(JSON.stringify(all, "\t"))
	return true

func _persist_scene() -> bool:
	# Packing the live Buildings node would save an instance of the old .scn,
	# not the new meshes. Rebuild the text scene from the chunk files, then
	# pack the binary the world actually loads.
	var godot := OS.get_executable_path()
	var game := ProjectSettings.globalize_path("res://")
	var output: Array = []
	var bake := OS.execute(godot, ["--headless", "--path", game, "--script", "res://buildings/tools/build_buildings.gd"], output, true)
	if bake != 0:
		push_warning("building edit: scene bake failed\n%s" % "\n".join(output))
		return false
	output.clear()
	var packed := OS.execute(godot, ["--headless", "--path", game, "--script", "res://buildings/tools/pack_buildings.gd"], output, true)
	if packed != 0:
		push_warning("building edit: scene pack failed\n%s" % "\n".join(output))
		return false
	return true

func _run_plan(cx: int, cz: int) -> int:
	var root := ProjectSettings.globalize_path("res://..")
	var python := root.path_join(".venv/bin/python")
	var script := root.path_join("pipeline/buildings/build_building_plan.py")
	var output: Array = []
	return OS.execute(python, [script, "--chunk", "%d,%d" % [cx, cz]], output, true)

func _reload_chunk(cx: int, cz: int) -> void:
	var manifest: Variant = _read_json(BUILD_DIR + "manifest.json")
	if manifest == null:
		return
	var info: Dictionary = {}
	for entry in manifest["chunks"]:
		if int(entry["cx"]) == cx and int(entry["cz"]) == cz:
			info = entry
			break
	if info.is_empty():
		return
	var data: Variant = _read_json(BUILD_DIR + String(info["file"]))
	if data == null:
		return
	var buildings := get_tree().current_scene.find_child("Buildings", true, false)
	if buildings == null:
		return
	var materials := {}
	for key in manifest["materials"].keys():
		materials[key] = load(manifest["materials"][key])
	var origin := Vector3(float(info.get("origin_x", 0.0)), 0.0, float(info.get("origin_z", 0.0)))
	var chunk_name := "chunk_%d_%d" % [cx, cz]
	_swap_mesh(buildings, "Near", chunk_name + "_near", data.get("near", {}), materials, origin, false)
	var far_map := {"building_far": load(manifest["far_material"])}
	_swap_mesh(buildings, "Far", chunk_name + "_far", data.get("far", {}), far_map, origin, true)
	_swap_collision(buildings, chunk_name + "_collision", data.get("collisions", []), origin)

func _swap_mesh(buildings: Node, container_name: String, node_name: String, groups: Dictionary, materials: Dictionary, origin: Vector3, far: bool) -> void:
	var container := buildings.find_child(container_name, true, false)
	if container == null or groups.is_empty():
		return
	var mesh := _build_array_mesh(groups, materials)
	var mi := container.find_child(node_name, true, false) as MeshInstance3D
	if mi == null:
		mi = MeshInstance3D.new()
		mi.name = node_name
		mi.position = origin
		container.add_child(mi)
	mi.mesh = mesh

func _swap_collision(buildings: Node, node_name: String, collisions: Array, origin: Vector3) -> void:
	var container := buildings.find_child("Collision", true, false)
	if container == null:
		return
	var body := container.find_child(node_name, true, false) as StaticBody3D
	if body == null:
		body = StaticBody3D.new()
		body.name = node_name
		body.position = origin
		container.add_child(body)
	for child in body.get_children():
		child.free()
	var ids: Array[int] = []
	for col in collisions:
		var hull: Array = col["hull"]
		if hull.size() < 3:
			continue
		var pts := PackedVector3Array()
		for p in hull:
			pts.append(Vector3(p[0], float(col["y0"]), p[1]))
			pts.append(Vector3(p[0], float(col["y1"]), p[1]))
		var shape := ConvexPolygonShape3D.new()
		shape.points = pts
		var cs := CollisionShape3D.new()
		cs.shape = shape
		var building_id := int(col.get("id", -1))
		cs.set_meta("building_id", building_id)
		body.add_child(cs)
		ids.append(building_id)
	body.set_meta("building_ids", ids)

func _build_array_mesh(groups: Dictionary, materials: Dictionary) -> ArrayMesh:
	var mesh := ArrayMesh.new()
	for mat_key in groups.keys():
		var g: Dictionary = groups[mat_key]
		var verts: Array = g.get("verts", [])
		var indices: Array = g.get("indices", [])
		if verts.is_empty() or indices.is_empty():
			continue
		var st := SurfaceTool.new()
		st.begin(Mesh.PRIMITIVE_TRIANGLES)
		for v in verts:
			var vv: Array = v
			st.set_normal(Vector3(vv[3], vv[4], vv[5]))
			st.set_uv(Vector2(vv[6], vv[7]))
			st.set_color(Color(vv[8], vv[9], vv[10], vv[11]))
			st.add_vertex(Vector3(vv[0], vv[1], vv[2]))
		for idx in indices:
			st.add_index(int(idx))
		mesh = st.commit(mesh)
		var mat = materials.get(mat_key)
		if mat != null:
			mesh.surface_set_material(mesh.get_surface_count() - 1, mat)
	return mesh

## Writes the selected building's footprint for Building Composer, to
## exports/composer/<id>.json beside the project: its outline in local space
## (x east, z south, meters, as in data/buildings.json), its id, ground and
## roof heights, and the direction of its front (toward the street). The
## structure the game generated on the footprint is not exported; only a
## building made in Composer carries its own design. Composer squares the
## outline up and keeps where it came from, so the composed building can be
## placed back here.
func _export_composer() -> void:
	if _record.is_empty():
		_status = "Click a building first."
		_refresh()
		return
	var bid := str(_record["id"])
	var building := _footprint(bid)
	if building.is_empty():
		_status = "No footprint for building %s." % bid
		_refresh()
		return
	var points: Array = []
	for p in building.get("footprint", []):
		points.append([float(p["x"]), float(p["z"])])
	var payload := {
		"format": "dixon-footprint",
		"version": 1,
		"source": "dixon_dem",
		"id": bid,
		"footprint": points,
		"ground_y_min": building.get("ground_y_min"),
		"ground_y_max": building.get("ground_y_max"),
		"height_m": building.get("height_m"),
		"tags": building.get("tags", {}),
	}
	if building.get("override") == true:
		# the outline corrected in Composer, what it replaced, and the outline it was drawn over
		payload["override"] = true
		payload["based_on"] = building.get("based_on", {})
		payload["source_footprint"] = building.get("source_footprint", [])
	var front := street_front(points)
	if not front.is_empty():
		payload["front"] = front
	payload["hints"] = composer_hints(_record)
	var sent: Variant = _read_json(composed_dir.path_join("%s.json" % bid))
	if sent is Dictionary and sent.get("project") is Dictionary:
		payload["project"] = sent["project"]
	var dir := ProjectSettings.globalize_path(COMPOSER_EXPORT_DIR).simplify_path()
	DirAccess.make_dir_recursive_absolute(dir)
	var path := dir.path_join("%s.json" % bid)
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_status = "Could not write %s." % path
		_refresh()
		return
	file.store_string(JSON.stringify(payload, "\t"))
	file.close()
	_status = "Opening building %s in Composer…" % bid
	_refresh()
	_status = await _open_in_composer(JSON.stringify(payload))
	_refresh()

## The building editor's choices for this building, for Composer to start
## from (its settingsFromHints): the resolved template with this session's
## edits, so the form, storeys, roof and its axis, wall material and color,
## dressing, porch, ground floor, and awnings. `color` "auto" is left out.
static func composer_hints(record: Dictionary) -> Dictionary:
	var hints := {}
	for key in ["form", "storeys", "roof", "roof_axis", "material", "color", "dressing", "porch", "ground", "awnings"]:
		if record.has(key) and record[key] != null and str(record[key]) != "auto":
			hints[key] = record[key]
	return hints

## Opens Composer in the browser with this footprint in the page address
## (`#import=`, base64url; the fragment never goes to the server), starting a
## local server for it first if nothing answers. Returns the status to show.
func _open_in_composer(json_text: String) -> String:
	var page := OS.get_environment("BUILDING_COMPOSER_URL")
	if page.is_empty():
		page = COMPOSER_URL
	if not await _answers(page):
		var dir := OS.get_environment("BUILDING_COMPOSER_DIR")
		if dir.is_empty():
			dir = ProjectSettings.globalize_path(COMPOSER_DIR).simplify_path()
		if not FileAccess.file_exists(dir.path_join("index.html")):
			return "Saved to exports/composer. Composer isn't running at %s and isn't at %s (set BUILDING_COMPOSER_DIR)." % [page, dir]
		var port := page.get_slice("://", 1).get_slice("/", 0).get_slice(":", 1)
		if port.is_empty():
			port = "80"
		var server := ProjectSettings.globalize_path(COMPOSER_SERVER)
		if OS.create_process("python3", [server, "--port", port, "--dir", dir]) <= 0:
			return "Saved to exports/composer. Could not start a server for Composer (python3)."
		var up := false
		for i in 20:
			await get_tree().create_timer(0.25).timeout
			if await _answers(page):
				up = true
				break
		if not up:
			return "Saved to exports/composer. Started Composer's server, but %s doesn't answer." % page
	var encoded := Marshalls.utf8_to_base64(json_text).replace("+", "-").replace("/", "_").replace("=", "")
	OS.shell_open("%s#import=%s" % [page, encoded])
	return "Opened in Composer (also saved to exports/composer)."

## Whether a page answers (within a second).
func _answers(url: String) -> bool:
	var request := HTTPRequest.new()
	request.timeout = 1.0
	add_child(request)
	if request.request(url, [], HTTPClient.METHOD_HEAD) != OK:
		request.queue_free()
		return false
	var result: Array = await request.request_completed
	request.queue_free()
	return result[0] == HTTPRequest.RESULT_SUCCESS and int(result[1]) == 200

## The direction a building faces, as a unit vector [x, z] (x east, z south)
## from its middle toward the nearest street, or [] when no road is near.
## Streets win over alleys and paths, so a house on a corner of an alley still
## faces the street. Not the same rule as the generator's (which takes any road):
## this one is what a person would call the front.
func street_front(points: Array) -> Array:
	if points.size() < 3:
		return []
	_load_roads()
	var center := Vector2.ZERO
	var count := 0
	for i in points.size():
		if i == points.size() - 1 and points[i] == points[0]:
			continue
		center += Vector2(float(points[i][0]), float(points[i][1]))
		count += 1
	center /= float(count)
	var toward := _toward_nearest(_streets, center)
	if toward == Vector2.ZERO:
		toward = _toward_nearest(_lanes, center)
	if toward == Vector2.ZERO:
		return []
	toward = toward.normalized()
	return [snappedf(toward.x, 0.0001), snappedf(toward.y, 0.0001)]

func _toward_nearest(segments: Array, from: Vector2) -> Vector2:
	var best := Vector2.ZERO
	var best_distance := FRONT_SEARCH_M
	for segment in segments:
		var a: Vector2 = segment[0]
		var b: Vector2 = segment[1]
		var along := b - a
		var length2 := along.length_squared()
		var t := 0.0 if length2 < 1e-9 else clampf((from - a).dot(along) / length2, 0.0, 1.0)
		var offset := a + along * t - from
		var distance := offset.length()
		if distance < best_distance and distance > 1e-6:
			best_distance = distance
			best = offset
	return best

func _load_roads() -> void:
	if not _streets.is_empty() or not _lanes.is_empty():
		return
	var data: Variant = _read_json(ROADS_PATH)
	if not (data is Dictionary):
		return
	for way in data.get("ways", []):
		var vertices: Array = way.get("vertices", [])
		var kind := str((way.get("tags", {}) as Dictionary).get("highway", ""))
		if kind in ["footway", "cycleway", "path", "steps", "track"]:
			continue
		var into := _streets if kind in STREET_CLASSES else _lanes
		for i in vertices.size() - 1:
			into.append([
				Vector2(float(vertices[i]["x"]), float(vertices[i]["z"])),
				Vector2(float(vertices[i + 1]["x"]), float(vertices[i + 1]["z"])),
			])

## A building's record from the footprint files, by id (loaded once), with
## the outline corrected in Composer in place of the traced one when there is
## one (marked `override`, with its `based_on` and the traced `source_footprint`).
func _footprint(bid: String) -> Dictionary:
	if _footprints.is_empty():
		for path in FOOTPRINT_PATHS:
			var data: Variant = _read_json(path)
			if data is Dictionary and data.get("buildings") is Array:
				for building in data["buildings"]:
					if building is Dictionary and building.has("id"):
						_footprints[str(int(building["id"]))] = building
	var found: Variant = _footprints.get(bid, {})
	if not (found is Dictionary) or found.is_empty():
		return {}
	var override := footprint_override(bid)
	if override.is_empty():
		return found
	var corrected: Dictionary = found.duplicate()
	var ring: Array = []
	for p in override["footprint"]:
		ring.append({"x": float(p[0]), "z": float(p[1])})
	var traced: Array = []
	for p in found.get("footprint", []):
		traced.append([float(p["x"]), float(p["z"])])
	corrected["footprint"] = ring
	corrected["override"] = true
	corrected["based_on"] = override.get("based_on", {})
	corrected["source_footprint"] = traced
	return corrected

## The footprint override Composer saved for a building (read fresh: Composer
## writes them while the game runs), or {} when there is none.
func footprint_override(bid: String) -> Dictionary:
	var data: Variant = _read_json(footprint_overrides_dir.path_join("%s.json" % bid))
	if data is Dictionary and data.get("format") == "dixon-footprint-override" and data.get("footprint") is Array and data["footprint"].size() >= 3:
		return data
	return {}

## O: back to the outline the game traced. The override is renamed
## <id>.json.off (kept, not deleted; rename it back to use it again) and the
## chunk rebuilt, which also drops the porches it brought.
func _revert_footprint() -> void:
	if _record.is_empty():
		_status = "Click a building first."
		_refresh()
		return
	var bid := str(_record["id"])
	if footprint_override(bid).is_empty():
		_status = "Building %s has no outline corrected in Composer." % bid
		_refresh()
		return
	var path := ProjectSettings.globalize_path(footprint_overrides_dir.path_join("%s.json" % bid))
	if DirAccess.rename_absolute(path, path + ".off") != OK:
		_status = "Could not set aside %s." % path
		_refresh()
		return
	_apply()

func _read_json(path: String):
	if path.begins_with("res://"):
		path = ProjectSettings.globalize_path(path)
	if not FileAccess.file_exists(path):
		return null
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return null
	return JSON.parse_string(file.get_as_text())
