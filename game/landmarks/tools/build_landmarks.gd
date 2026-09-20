extends SceneTree
## Landmarks workstream bake tool. Builds the six hero landmarks (courthouse,
## Dixon Arch + Galena Ave bridge dressing + dam, Lincoln statue, Dixon
## Theatre, Reagan Boyhood Home, Nachusa House) as individual scenes under
## game/landmarks/, then composes game/landmarks/landmarks.tscn instancing
## all of them at their real-world positions/orientations.
##
## Run headless (no GPU needed, pure resource construction):
##   ~/AppImage/Godot_v4.6-stable_linux.x86_64 --headless --path game \
##     --script res://landmarks/tools/build_landmarks.gd
##
## Positions: docs/pipeline_notes.md "Landmark Godot coordinates" (sourced
## from a live OSM/Overpass survey). Orientations (which way each building's
## front wall faces) are NOT guessed -- they're derived from the real OSM
## footprint polygons in game/data/buildings.json: this session computed each
## footprint's minimum-rotated-bounding-rectangle (shapely) and its edge
## bearings, which showed every downtown-grid landmark (courthouse, theatre,
## Nachusa House, Dixon Arch) shares the same ~254deg/74deg long-edge and
## ~344deg/164deg short-edge bearing pair (Dixon's street grid is rotated
## ~16deg off true north), and Reagan Boyhood Home (different block, same
## citywide grid) matches within 1deg. Bearings used below (outward front-
## wall normal, compass degrees clockwise from north):
##   courthouse 344.1 (north/northwest, matches the reference doc's "faces
##     north/northwest across the square"), theatre 73.9 / reagan 73.1 /
##     nachusa 72.3 (all "faces east onto Galena/Hennepin Ave" per their
##     docs), dixon_arch spans across Galena Ave at bearing 72.9 (its long
##     footprint axis -- the arch's clear-span direction).
## Godot-space rotation formula used throughout (derived and documented
## alongside `facing_rotation`/`span_rotation` below): for a local model
## authored with its "front" wall facing local -Z, rotation_y = -bearing
## (radians) makes that front face the given compass bearing; for a model
## authored with its span axis along local +X (the arch), rotation_y =
## radians(90 - bearing).

const MB = preload("res://landmarks/tools/mesh_builder.gd")
const LM = preload("res://landmarks/tools/landmark_materials.gd")
const TerrainHeight = preload("res://terrain/terrain_height.gd")

const OUT_DIR := "res://landmarks/"

static func facing_rotation(bearing_deg: float) -> float:
	return deg_to_rad(-bearing_deg)

static func span_rotation(bearing_deg: float) -> float:
	return deg_to_rad(90.0 - bearing_deg)

var _placements: Array = [] # {id, scene, pos:Vector3, rot_y:float}


func _init() -> void:
	DirAccess.make_dir_recursive_absolute(OUT_DIR.replace("res://", "res://").path_join(""))
	_placements.append(_place("lee_county_courthouse", _build_courthouse(), Vector2(1691.9, -1233.5), 344.1, true))
	_placements.append(_place("dixon_arch_complex", _build_dixon_arch_complex(), Vector2.ZERO, 0.0, false, true))
	_placements.append(_place("lincoln_statue", _build_lincoln_statue(), Vector2(1387.8, -1726.6), 74.0, true))
	_placements.append(_place("dixon_theatre", _build_dixon_theatre(), Vector2(1610.5, -1381.2), 73.9, true))
	_placements.append(_place("reagan_boyhood_home", _build_reagan_home(), Vector2(1723.1, -590.0), 73.1, true))
	_placements.append(_place("nachusa_house", _build_nachusa_house(), Vector2(1601.5, -1219.8), 72.3, true))
	_build_landmarks_tscn()
	print("landmarks build complete: %d scenes" % _placements.size())
	quit()


func _place(id: String, root: Node3D, xz: Vector2, bearing_deg: float, use_terrain_height: bool, is_world_space: bool = false) -> Dictionary:
	var path := OUT_DIR + id + ".tscn"
	_save(root, path)
	var pos := Vector3.ZERO
	var rot := 0.0
	if not is_world_space:
		var gy := TerrainHeight.get_height(xz.x, xz.y) if use_terrain_height else 0.0
		pos = Vector3(xz.x, gy, xz.y)
		rot = facing_rotation(bearing_deg)
	return {"id": id, "path": path, "pos": pos, "rot_y": rot}


func _save(node: Node3D, path: String) -> void:
	_set_owner_recursive(node, node)
	var packed := PackedScene.new()
	packed.pack(node)
	var err := ResourceSaver.save(packed, path)
	if err != OK:
		push_error("landmarks: failed saving %s (err %d)" % [path, err])
	else:
		print("wrote", path)


func _set_owner_recursive(n: Node, owner: Node) -> void:
	for c in n.get_children():
		c.owner = owner
		_set_owner_recursive(c, owner)


func _build_landmarks_tscn() -> void:
	var root := Node3D.new()
	root.name = "Landmarks"
	for p in _placements:
		var ps: PackedScene = load(p["path"])
		var inst := ps.instantiate()
		inst.name = p["id"]
		inst.transform = Transform3D(Basis(Vector3.UP, p["rot_y"]), p["pos"])
		root.add_child(inst)
	_save(root, OUT_DIR + "landmarks.tscn")


## ===========================================================================
## Shared composition helpers
## ===========================================================================

static func add_window(mb: MB, glass_mat: Material, center: Vector3, width: float, height: float, normal: Vector3) -> void:
	mb.add_panel(glass_mat, center + normal * 0.03, normal, width, height)


## Evenly spaces `count` windows along the segment p_start..p_end (any axis --
## works for a wall running in X or Z), all facing `normal`.
static func add_window_row(mb: MB, glass_mat: Material, p_start: Vector3, p_end: Vector3, count: int, win_w: float, win_h: float, normal: Vector3) -> void:
	if count <= 0:
		return
	for i in range(count):
		var t := float(i + 1) / float(count + 1)
		add_window(mb, glass_mat, p_start.lerp(p_end, t), win_w, win_h, normal)


## Simple double-globe ornate cast-iron lamp post (per dixon_vernacular.md).
static func add_lamp_post(mb: MB, iron_mat: Material, glow_mat: Material, base: Vector3, height: float = 4.2) -> void:
	mb.add_cylinder(iron_mat, base, height, 0.09, 0.06, 8, true, false)
	var arm_y := base.y + height
	mb.add_cylinder(iron_mat, base + Vector3(0, arm_y - base.y - 0.05, 0), 0.1, 0.11, 0.02, 8, true, true)
	for side: float in [-1.0, 1.0]:
		var globe_c := base + Vector3(side * 0.35, arm_y - base.y + 0.15, 0.0)
		mb.add_dome(glow_mat, globe_c - Vector3(0, 0.12, 0), 0.12, 8, 4)
		mb.add_cylinder(iron_mat, base + Vector3(side * 0.35, arm_y - base.y - 0.05, 0), 0.2, 0.03, 0.03, 6, false, false)


## Small urn-shaped corner finial (cone + ball approximation).
static func add_urn_finial(mb: MB, mat: Material, base: Vector3, h: float = 0.9) -> void:
	mb.add_cylinder(mat, base, h * 0.35, 0.16, 0.1, 10, true, true)
	mb.add_dome(mat, base + Vector3(0, h * 0.35, 0), 0.16, 10, 5)
	mb.add_cone(mat, base + Vector3(0, h * 0.35 + 0.16, 0), h * 0.3, 0.08, 8)


## ===========================================================================
## 1. Lee County Courthouse
## ===========================================================================

func _build_courthouse() -> Node3D:
	var root := Node3D.new()
	root.name = "LeeCountyCourthouse"
	var mb := MB.new()
	var gy := 0.0 # local ground

	var limestone := LM.tinted("limestone", 26.6, {"albedo_tint": Color(1.06, 1.0, 0.86), "albedo_multiplier": 0.92, "uv_scale": Vector2(0.35, 0.35)})
	var limestone_trim := LM.tinted("limestone", 26.6, {"albedo_tint": Color(1.1, 1.04, 0.9), "albedo_multiplier": 0.98, "uv_scale": Vector2(0.5, 0.5)})
	var dome_mat := LM.tinted("roof_metal", 26.6, {"albedo_tint": Color(0.62, 0.86, 0.76), "albedo_multiplier": 0.55, "roughness_multiplier": 1.3, "metallic": 0.15, "uv_scale": Vector2(0.3, 0.3)})
	var glass := LM.window_glass(26.6)
	var dark_trim := LM.flat_color("stone_foundation", Color(0.12, 0.11, 0.1), 26.6, 0.5)
	var lamp_iron := LM.flat_color("stone_foundation", Color(0.08, 0.08, 0.08), 26.6, 0.4)
	var lamp_glow := LM.flat_unshaded(Color(0.95, 0.92, 0.8), 0.3)
	var sign_mat := LM.signage("courthouse_entablature.png")

	var width := 36.0
	var depth := 25.3

	# podium (rusticated base)
	mb.add_box(limestone, Vector3(0, 2.25, 0), Vector3(width, 4.5, depth))
	# main block (upper storeys)
	mb.add_box(limestone, Vector3(0, 4.5 + 4.5, 0), Vector3(width, 9.0, depth))
	# cornice/parapet band
	mb.add_box(limestone_trim, Vector3(0, 14.25, 0), Vector3(width + 1.0, 1.5, depth + 1.0))
	# flat roof deck behind parapet
	mb.add_box(limestone, Vector3(0, 15.5, 0), Vector3(width - 2.0, 0.5, depth - 2.0))

	# entrance pavilion projecting toward -Z (front)
	var pav_w := 15.0
	var pav_d := 2.6
	var pav_z := -depth * 0.5 - pav_d * 0.5
	mb.add_box(limestone, Vector3(0, 4.5 + 4.5, pav_z), Vector3(pav_w, 9.0, pav_d))
	mb.add_box(limestone_trim, Vector3(0, 14.3, pav_z), Vector3(pav_w + 0.6, 1.2, pav_d + 0.6))

	# 6-column giant-order colonnade across the pavilion front
	var col_z := pav_z - pav_d * 0.5 - 0.35
	for i in range(6):
		var cx := lerpf(-pav_w * 0.5 + 1.3, pav_w * 0.5 - 1.3, float(i) / 5.0)
		mb.add_cylinder(limestone_trim, Vector3(cx, 4.5, col_z), 8.2, 0.42, 0.38, 12, true, true)
		mb.add_cylinder(limestone_trim, Vector3(cx, 4.5, col_z), 0.15, 0.5, 0.44, 12, true, false) # base
	# entablature sign above columns
	mb.add_panel(sign_mat, Vector3(0, 13.2, col_z - 0.1), Vector3(0, 0, -1), 13.5, 1.3)

	# stairs
	for s in range(4):
		var sy := float(s) * 0.18
		var sd := 1.6 - float(s) * 0.35
		mb.add_box(limestone, Vector3(0, sy * 0.5, col_z - 1.0 - sd * 0.5), Vector3(pav_w * 0.55, sy + 0.18, sd))
	# paired globe lamps flanking stairs
	add_lamp_post(mb, lamp_iron, lamp_glow, Vector3(-pav_w * 0.4, 0.0, col_z - 1.6), 3.6)
	add_lamp_post(mb, lamp_iron, lamp_glow, Vector3(pav_w * 0.4, 0.0, col_z - 1.6), 3.6)

	# dome drum + hemispherical verdigris dome + lantern
	mb.add_cylinder(limestone, Vector3(0, 15.5, -2.0), 3.0, 5.0, 4.8, 20, false, true)
	mb.add_dome(dome_mat, Vector3(0, 18.5, -2.0), 5.3, 20, 8)
	mb.add_cylinder(dome_mat, Vector3(0, 23.6, -2.0), 1.4, 0.55, 0.5, 10, true, true)
	mb.add_cone(dome_mat, Vector3(0, 25.0, -2.0), 1.1, 0.5, 10, true)

	# flanking small cupola turrets at outer corners of the pavilion roofline
	for side: float in [-1.0, 1.0]:
		var tx := side * 6.0
		mb.add_cylinder(limestone, Vector3(tx, 15.5, -9.5), 1.6, 1.0, 0.95, 12, false, true)
		mb.add_dome(dome_mat, Vector3(tx, 17.1, -9.5), 1.0, 12, 5)

	# corner urn finials on the parapet
	for cx2: float in [-width * 0.5 + 1.0, width * 0.5 - 1.0]:
		for cz2: float in [-depth * 0.5 + 1.0, depth * 0.5 - 1.0]:
			add_urn_finial(mb, limestone_trim, Vector3(cx2, 15.0, cz2), 0.9)

	# windows: wings either side of the pavilion, 3 bays x 2 floors, front (-Z) wall
	for wing_sign: float in [-1.0, 1.0]:
		var x0 := wing_sign * (pav_w * 0.5 + 1.5)
		var x1 := wing_sign * (width * 0.5 - 1.2)
		for floor_y: float in [6.3, 10.3]:
			add_window_row(mb, glass, Vector3(x0, floor_y, -depth * 0.5 - 0.02), Vector3(x1, floor_y, -depth * 0.5 - 0.02), 3, 1.1, 1.8, Vector3(0, 0, -1))
	# side walls: a few windows for the approach-from-the-side read
	for side: float in [-1.0, 1.0]:
		var sx := side * (width * 0.5 - 0.02)
		for floor_y2: float in [6.3, 10.3]:
			add_window_row(mb, glass, Vector3(sx, floor_y2, -depth * 0.5 + 3.0), Vector3(sx, floor_y2, depth * 0.5 - 3.0), 4, 1.1, 1.8, Vector3(side, 0, 0))

	mb.add_box_collision(Vector3(0, 8.5, 0), Vector3(width, 17.0, depth))
	mb.add_box_collision(Vector3(0, 9.0, pav_z), Vector3(pav_w, 18.0, pav_d + 1.0))

	var mesh := mb.finalize()
	var mi := MeshInstance3D.new()
	mi.name = "Mesh"
	mi.mesh = mesh
	root.add_child(mi)
	root.add_child(mb.build_collision_body("Collision"))
	return root


## ===========================================================================
## 2. Dixon Arch + Galena Ave bridge dressing + Dixon Dam
## (built in WORLD-space directly -- see class header; the bridge/dam pieces
## are elongated multi-point structures that are simplest authored straight
## in real coordinates rather than local+rotate)
## ===========================================================================

func _build_dixon_arch_complex() -> Node3D:
	var root := Node3D.new()
	root.name = "DixonArchComplex"
	root.add_child(_build_dixon_arch())
	root.add_child(_build_galena_bridge_dressing())
	root.add_child(_build_dixon_dam())
	return root


func _build_dixon_arch() -> Node3D:
	var wrap := Node3D.new()
	wrap.name = "DixonArch"
	var wx := 1631.3
	var wz := -1214.2
	var gy := TerrainHeight.get_height(wx, wz)
	wrap.transform = Transform3D(Basis(Vector3.UP, span_rotation(72.9)), Vector3(wx, gy, wz))

	var mb := MB.new()
	var arch_mat := LM.flat_color("sidewalk_concrete", Color(1.35, 1.32, 1.22), gy, 1.05, {"uv_scale": Vector2(0.2, 0.2), "roughness_multiplier": 0.7})
	var pier_mat := LM.flat_color("limestone", Color(1.15, 1.1, 0.98), gy, 0.85, {"uv_scale": Vector2(0.3, 0.3)})
	var iron := LM.flat_color("stone_foundation", Color(0.08, 0.08, 0.08), gy, 0.4)
	var glow := LM.flat_unshaded(Color(0.95, 0.92, 0.8), 0.3)
	var sign_mat := LM.signage("dixon_arch_sign.png", true, Color(1.0, 0.2, 0.2), 1.1)

	var half_span := 9.8
	var pier_h := 2.3
	var tube_r := 0.5

	for side: float in [-1.0, 1.0]:
		var px := side * half_span
		mb.add_box(pier_mat, Vector3(px, pier_h * 0.5, 0), Vector3(1.2, pier_h, 1.2))
		mb.add_box_collision(Vector3(px, pier_h * 0.5, 0), Vector3(1.2, pier_h, 1.2))
		add_lamp_post(mb, iron, glow, Vector3(px, pier_h, -1.6), 4.0)
		add_lamp_post(mb, iron, glow, Vector3(px, pier_h, 1.6), 4.0)

	mb.add_arch_tube(arch_mat, Vector3(0, pier_h, 0), half_span, tube_r, 180.0, 0.0, 28, 10)

	var apex_y := pier_h + half_span
	mb.add_panel(sign_mat, Vector3(0, apex_y + 0.05, -tube_r - 0.05), Vector3(0, 0, -1), 6.5, 2.0)
	mb.add_panel(sign_mat, Vector3(0, apex_y + 0.05, tube_r + 0.05), Vector3(0, 0, 1), 6.5, 2.0)

	var mesh := mb.finalize()
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	wrap.add_child(mi)
	wrap.add_child(mb.build_collision_body("Collision"))
	return wrap


## Decorative dressing over roads' plain deck ribbon: haunch-look pier caps
## visible from the riverbank (the single most distinctive silhouette
## element per galena_bridge.md), a simple steel pipe railing, ornate lamp
## posts, and "Lincoln Highway" stamped into the sidewalk. Built directly in
## world space along the real deck centerline from game/data/bridges.json
## (way 114082270): (1541.4,-1526.8) -> (1518.5,-1600.7) -> (1483.0,-1725.5),
## deck Y=11.04, width_m=16.4 (half-width 8.2).
func _build_galena_bridge_dressing() -> Node3D:
	var wrap := Node3D.new()
	wrap.name = "GalenaBridgeDressing"
	var mb := MB.new()
	var deck_y := 11.04
	var half_w := 8.2
	var concrete := LM.flat_color("sidewalk_concrete", Color(1.05, 1.0, 0.9), deck_y, 0.9, {"uv_scale": Vector2(0.5, 0.5)})
	var pier_mat := LM.flat_color("curb_concrete", Color(1.0, 0.96, 0.86), deck_y - 5.0, 0.85, {"uv_scale": Vector2(0.4, 0.4)})
	var stain_mat := LM.flat_color("curb_concrete", Color(0.55, 0.6, 0.53), deck_y - 5.0, 0.55, {"uv_scale": Vector2(0.4, 0.4)})
	var steel := LM.flat_color("steel_rusted", Color(0.75, 0.76, 0.78), deck_y, 0.55, {"uv_scale": Vector2(0.6, 0.6)})
	var iron := LM.flat_color("stone_foundation", Color(0.08, 0.08, 0.08), deck_y, 0.4)
	var glow := LM.flat_unshaded(Color(0.95, 0.92, 0.8), 0.3)
	var stamp_mat := LM.signage("lincoln_highway_stamp.png")

	var pts: Array[Vector2] = [Vector2(1541.4, -1526.8), Vector2(1518.5, -1600.7), Vector2(1483.0, -1725.5)]
	# resample the polyline into ~20m steps for evenly spaced piers/lamps
	var samples: Array[Vector2] = []
	var seg_len := 0.0
	for i in range(pts.size() - 1):
		seg_len += pts[i].distance_to(pts[i + 1])
	var step: float = seg_len / round(seg_len / 20.0)
	var accum := 0.0
	samples.append(pts[0])
	while accum + step < seg_len - 0.01:
		accum += step
		# walk along pts to find point at arclength=accum
		var d := accum
		var i2 := 0
		while i2 < pts.size() - 1 and d > pts[i2].distance_to(pts[i2 + 1]):
			d -= pts[i2].distance_to(pts[i2 + 1])
			i2 += 1
		if i2 >= pts.size() - 1:
			break
		var segv: Vector2 = pts[i2 + 1] - pts[i2]
		var seglen2 := segv.length()
		var p: Vector2 = pts[i2] + segv * (d / max(seglen2, 0.001))
		samples.append(p)
	samples.append(pts[pts.size() - 1])

	for i in range(samples.size()):
		var p2: Vector2 = samples[i]
		var dir: Vector2
		if i < samples.size() - 1:
			dir = (samples[i + 1] - p2).normalized()
		else:
			dir = (p2 - samples[i - 1]).normalized()
		var perp := Vector2(-dir.y, dir.x) # points to one side of travel, used for pier width axis
		var wx := p2.x; var wz := p2.y
		# interior points only get pier haunches (skip the very ends, which sit on the bank)
		if i > 0 and i < samples.size() - 1:
			var pier_top_y := deck_y - 1.0
			var haunch_h := 2.0
			# wide-at-top, narrow-at-bottom flare (negative inset widens upward)
			mb.add_mansard(pier_mat, Vector3(wx, pier_top_y - haunch_h, wz), 3.0, 1.6, haunch_h, -2.6)
			mb.add_box(pier_mat, Vector3(wx, (pier_top_y - haunch_h) * 0.5 - 1.0, wz), Vector3(2.6, pier_top_y - haunch_h + 2.0, 1.4))
			mb.add_box(stain_mat, Vector3(wx, 4.2, wz), Vector3(2.8, 2.2, 1.6))
		# railing posts + top rails at both edges
		for side: float in [-1.0, 1.0]:
			var rx := wx + perp.x * half_w * side
			var rz := wz + perp.y * half_w * side
			if i % 2 == 0:
				mb.add_cylinder(steel, Vector3(rx, deck_y, rz), 1.0, 0.04, 0.04, 6, false, false)
			if i % 3 == 0:
				add_lamp_post(mb, iron, glow, Vector3(rx, deck_y, rz), 4.3)

	# continuous top/mid pipe rails along both edges (approximate as straight
	# segments between consecutive samples -- close enough for the gentle curve)
	for i in range(samples.size() - 1):
		var a2: Vector2 = samples[i]; var b2: Vector2 = samples[i + 1]
		var dir2 := (b2 - a2).normalized()
		var perp2 := Vector2(-dir2.y, dir2.x)
		for side: float in [-1.0, 1.0]:
			var a3 := Vector3(a2.x + perp2.x * half_w * side, deck_y + 0.75, a2.y + perp2.y * half_w * side)
			var b3 := Vector3(b2.x + perp2.x * half_w * side, deck_y + 0.75, b2.y + perp2.y * half_w * side)
			var mid := (a3 + b3) * 0.5
			var len3 := a3.distance_to(b3)
			var ang := atan2(b3.x - a3.x, b3.z - a3.z)
			mb.add_box(steel, mid, Vector3(0.05, 0.05, len3), ang)
			mb.add_box(steel, mid + Vector3(0, 0.35, 0), Vector3(0.05, 0.05, len3), ang)

	# "Lincoln Highway" stamps on the sidewalk, flat, a few along the span
	for frac: float in [0.25, 0.5, 0.75]:
		var idx := int(frac * float(samples.size() - 1))
		var sp: Vector2 = samples[idx]
		mb.add_panel(stamp_mat, Vector3(sp.x, deck_y + 0.02, sp.y), Vector3(0, 1, 0), 3.0, 0.8, Vector3(1, 0, 0))

	var mesh := mb.finalize()
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	wrap.add_child(mi)
	return wrap


## Rock River Dam / Dixon Dam per docs/references/dixon_dam.md (explicitly
## lower-confidence -- no close-up reference photo exists; massing is a
## plausible 1920s hydro estimate). Spillway crest from the "Dixon Dam"
## water.json polygon's long axis (~114.5m, bearing ~104deg, matching the
## doc's 90-120m estimate); powerhouse placed near the "Rock River Dam"
## polygon (the canal/headworks run) per the doc's 3-part structure.
func _build_dixon_dam() -> Node3D:
	var wrap := Node3D.new()
	wrap.name = "DixonDam"
	var mb := MB.new()
	var crest_y := 5.3
	var base_y := 3.0
	var concrete := LM.flat_color("curb_concrete", Color(1.0, 0.97, 0.88), base_y, 0.85, {"uv_scale": Vector2(0.3, 0.3)})
	var brick := LM.flat_color("brick_red", Color(0.72, 0.42, 0.35), base_y, 0.65, {"uv_scale": Vector2(0.9, 0.9)})
	var glass := LM.window_glass(base_y)
	var buoy_mat := LM.flat_unshaded(Color(0.91, 0.35, 0.05), 0.5)

	# spillway wall (Dixon Dam polygon long axis, ~114.5m, bearing 103.8deg)
	var sp0 := Vector2(1714.6, -1630.4)
	var sp1 := Vector2(1825.9, -1603.1)
	var mid := (sp0 + sp1) * 0.5
	var span := sp0.distance_to(sp1)
	var ang := atan2(sp1.x - sp0.x, sp1.y - sp0.y)
	mb.add_box(concrete, Vector3(mid.x, (crest_y + base_y) * 0.5, mid.y), Vector3(3.0, crest_y - base_y, span), ang)
	# white-water foam curtain, just downstream (south) face of the crest
	var foam_mat := LM.foam()
	var perp := Vector2(cos(ang), -sin(ang))
	var foam_c := Vector3(mid.x + perp.x * 1.6, (crest_y + base_y) * 0.5, mid.y + perp.y * 1.6)
	mb.add_panel(foam_mat, foam_c, Vector3(perp.x, 0, perp.y), span * 0.98, (crest_y - base_y) * 1.4, Vector3(0, 1, 0))

	# headworks/canal retaining walls (Rock River Dam polygon, ~82m, bearing 13deg)
	var hw0 := Vector2(1697.6, -1553.6)
	var hw1 := Vector2(1670.8, -1557.7)
	var hmid := (hw0 + hw1) * 0.5
	var hspan := hw0.distance_to(hw1)
	var hang := atan2(hw1.x - hw0.x, hw1.y - hw0.y)
	mb.add_box(concrete, Vector3(hmid.x, (crest_y + base_y) * 0.5, hmid.y), Vector3(2.2, crest_y - base_y, hspan), hang)

	# powerhouse: 1920s brick industrial block near the canal's downstream end
	var ph_c := Vector3(1685.0, 0.0, -1600.0)
	var ph_gy := TerrainHeight.get_height(ph_c.x, ph_c.z)
	var ph_w := 20.0; var ph_d := 12.0; var ph_h := 8.5
	mb.add_box(brick, Vector3(ph_c.x, ph_gy + ph_h * 0.5, ph_c.z), Vector3(ph_w, ph_h, ph_d), hang)
	mb.add_box(concrete, Vector3(ph_c.x, ph_gy + ph_h + 0.2, ph_c.z), Vector3(ph_w + 0.4, 0.4, ph_d + 0.4), hang)
	# tall window band on the long face
	var basis2 := Basis(Vector3.UP, hang)
	var wall_normal := basis2 * Vector3(1, 0, 0)
	for i in range(5):
		var t2 := lerpf(-ph_w * 0.5 + 2.0, ph_w * 0.5 - 2.0, float(i) / 4.0)
		var wp := Vector3(ph_c.x, ph_gy + ph_h * 0.55, ph_c.z) + (basis2 * Vector3(0, 0, t2))
		mb.add_panel(glass, wp + wall_normal * 0.02, wall_normal, 1.6, 3.6)

	# orange safety buoy line upstream of the dam
	var b0 := Vector2(1650.0, -1520.0)
	var b1 := Vector2(1730.0, -1500.0)
	for i in range(9):
		var bt := float(i) / 8.0
		var bp := b0.lerp(b1, bt)
		mb.add_dome(buoy_mat, Vector3(bp.x, 5.92, bp.y), 0.22, 8, 4) # river_upstream pool level (world_origin.json)

	var mesh := mb.finalize()
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	wrap.add_child(mi)
	return wrap


## ===========================================================================
## 3. Lincoln Statue (Lincoln Monument State Memorial)
## ===========================================================================

func _build_lincoln_statue() -> Node3D:
	var root := Node3D.new()
	root.name = "LincolnStatue"
	var mb := MB.new()
	var gy := 0.0

	var granite := LM.flat_color("stone_foundation", Color(0.62, 0.62, 0.6), gy, 0.55, {"uv_scale": Vector2(0.25, 0.25)})
	var bronze := LM.flat_color("limestone", Color(0.5, 0.72, 0.64), gy, 0.55, {"uv_scale": Vector2(0.1, 0.1), "roughness_multiplier": 1.2})
	var picket := LM.tinted("siding_white", gy, {"albedo_tint": Color(0.85, 0.83, 0.76), "uv_scale": Vector2(1.2, 1.2)})
	var sign_mat := LM.signage("lincoln_text.png")

	# stepped granite base (3 tiers) + pedestal die
	mb.add_box(granite, Vector3(0, 0.15, 0), Vector3(3.2, 0.3, 3.2))
	mb.add_box(granite, Vector3(0, 0.45, 0), Vector3(2.6, 0.3, 2.6))
	mb.add_box(granite, Vector3(0, 0.75, 0), Vector3(2.2, 0.3, 2.2))
	mb.add_box(granite, Vector3(0, 0.9 + 1.1, 0), Vector3(1.8, 2.2, 1.4))
	mb.add_panel(sign_mat, Vector3(0, 1.9, -0.71), Vector3(0, 0, -1), 1.5, 0.7)

	# simplified standing bronze figure on the pedestal (die top at y=3.1)
	var fy := 3.1
	for side: float in [-1.0, 1.0]:
		mb.add_cylinder(bronze, Vector3(side * 0.16, fy, 0), 1.25, 0.16, 0.13, 8, true, true)
	mb.add_cylinder(bronze, Vector3(0, fy + 1.2, 0), 1.35, 0.5, 0.3, 10, true, true) # long coat, flares at bottom
	mb.add_cylinder(bronze, Vector3(0, fy + 2.5, 0), 0.28, 0.16, 0.14, 8, false, true) # neck
	mb.add_dome(bronze, Vector3(0, fy + 2.75, 0), 0.2, 10, 6) # head
	for side2: float in [-1.0, 1.0]:
		mb.add_cylinder(bronze, Vector3(side2 * 0.42, fy + 1.75, 0), 0.9, 0.08, 0.07, 6, true, true)
	mb.add_cylinder(bronze, Vector3(0.5, fy + 1.35, 0.05), 0.06, 0.2, 0.2, 10, true, true) # hat, held at side

	# picket-fence backdrop behind the monument
	for i in range(9):
		var px := lerpf(-2.2, 2.2, float(i) / 8.0)
		mb.add_box(picket, Vector3(px, 0.55, 1.6), Vector3(0.08, 1.1, 0.03))
	mb.add_box(picket, Vector3(0, 0.95, 1.6), Vector3(4.6, 0.06, 0.03))
	mb.add_box(picket, Vector3(0, 0.35, 1.6), Vector3(4.6, 0.06, 0.03))

	mb.add_box_collision(Vector3(0, 1.0, 0), Vector3(2.0, 2.0, 2.0))

	var mesh := mb.finalize()
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	root.add_child(mi)
	root.add_child(mb.build_collision_body("Collision"))
	return root


## ===========================================================================
## 4. Dixon Theatre
## ===========================================================================

func _build_dixon_theatre() -> Node3D:
	var root := Node3D.new()
	root.name = "DixonTheatre"
	var mb := MB.new()
	var gy := 0.0

	var brick_front := LM.tinted("brick_buff", 14.9, {"uv_scale": Vector2(0.8, 0.8)})
	var brick_side := LM.tinted("brick_buff", 14.9, {"albedo_tint": Color(0.82, 0.72, 0.58), "uv_scale": Vector2(0.8, 0.8)})
	var brick_chimney := LM.tinted("brick_red", 14.9, {"uv_scale": Vector2(0.8, 0.8)})
	var trim := LM.flat_color("limestone", Color(1.05, 1.0, 0.9), 14.9, 0.9, {"uv_scale": Vector2(0.5, 0.5)})
	var glass := LM.window_glass(14.9)
	var marquee_mat := LM.signage("theatre_marquee.png")
	var dark := LM.flat_color("stone_foundation", Color(0.1, 0.1, 0.1), 14.9, 0.4)

	var front_w := 16.5
	var front_d := 12.0
	var front_h := 11.0

	# front-of-house block, front wall at -Z
	mb.add_box(brick_front, Vector3(0, front_h * 0.5, front_d * 0.5), Vector3(front_w, front_h, front_d))
	mb.add_box(trim, Vector3(0, front_h + 0.4, front_d * 0.5), Vector3(front_w + 0.6, 0.8, front_d + 0.6))
	# pediment/cartouche above the corner entrance
	mb.add_box(trim, Vector3(0, front_h + 1.3, 0.5), Vector3(3.2, 1.2, 0.4))

	# upper-facade window rhythm, 2 floors
	add_window_row(mb, glass, Vector3(-front_w * 0.5 + 1.6, 5.0, 0.0), Vector3(front_w * 0.5 - 1.6, 5.0, 0.0), 6, 1.0, 1.9, Vector3(0, 0, -1))
	add_window_row(mb, glass, Vector3(-front_w * 0.5 + 1.6, 8.0, 0.0), Vector3(front_w * 0.5 - 1.6, 8.0, 0.0), 6, 1.0, 1.9, Vector3(0, 0, -1))
	# ground floor storefront glazing
	add_window_row(mb, glass, Vector3(-front_w * 0.5 + 2.0, 1.8, 0.0), Vector3(front_w * 0.5 - 2.0, 1.8, 0.0), 3, 2.4, 2.4, Vector3(0, 0, -1))

	# marquee/blade sign projecting from the corner, facing along X (readable
	# by pedestrians walking the sidewalk)
	var marq_c := Vector3(front_w * 0.5 - 1.0, 6.3, -1.2)
	mb.add_box(dark, marq_c, Vector3(0.15, 1.6, 2.4))
	mb.add_panel(marquee_mat, marq_c + Vector3(0.08, 0, 0), Vector3(1, 0, 0), 2.2, 1.4)
	mb.add_panel(marquee_mat, marq_c + Vector3(-0.08, 0, 0), Vector3(-1, 0, 0), 2.2, 1.4)

	# tall blank auditorium block behind (deeper into the block, +Z)
	var aud_w := 20.0; var aud_d := 26.0; var aud_h := 14.0
	var aud_z := front_d + aud_d * 0.5
	mb.add_box(brick_side, Vector3(1.0, aud_h * 0.5, aud_z), Vector3(aud_w, aud_h, aud_d))
	# chimney at the rear corner
	mb.add_box(brick_chimney, Vector3(aud_w * 0.5 - 0.8, 10.0, aud_z + aud_d * 0.5 - 1.0), Vector3(1.6, 20.0, 1.6))

	mb.add_box_collision(Vector3(0, front_h * 0.5, front_d * 0.5), Vector3(front_w, front_h, front_d))
	mb.add_box_collision(Vector3(1.0, aud_h * 0.5, aud_z), Vector3(aud_w, aud_h, aud_d))

	var mesh := mb.finalize()
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	root.add_child(mi)
	root.add_child(mb.build_collision_body("Collision"))
	return root


## ===========================================================================
## 5. Ronald Reagan Boyhood Home + Visitor Center
## ===========================================================================

func _build_reagan_home() -> Node3D:
	var root := Node3D.new()
	root.name = "ReaganBoyhoodHome"
	var mb := MB.new()
	var gy := 0.0

	var siding := LM.tinted("siding_white", 29.7, {"uv_scale": Vector2(0.9, 0.9)})
	var foundation := LM.flat_color("stone_foundation", Color(0.85, 0.76, 0.58), 29.7, 0.75, {"uv_scale": Vector2(0.5, 0.5)})
	var shingles := LM.tinted("shingles_dark", 29.7, {"shingle_color_dark": Color(0.5, 0.46, 0.42), "shingle_color_light": Color(0.62, 0.58, 0.53), "use_world_uv": false, "v_is_downslope": true})
	var glass := LM.window_glass(29.7)
	var white_col := LM.flat_color("siding_white", Color(0.95, 0.94, 0.9), 29.7, 1.0, {"uv_scale": Vector2(0.4, 0.4)})
	var brick := LM.tinted("brick_red", 29.7, {"uv_scale": Vector2(0.9, 0.9)})
	var siding_gray := LM.tinted("siding_white", 29.7, {"albedo_tint": Color(0.72, 0.72, 0.7), "uv_scale": Vector2(0.9, 0.9)})

	var w := 9.0; var d := 11.0; var h := 6.0
	mb.add_box(siding, Vector3(0, h * 0.5, 0), Vector3(w, h, d))
	mb.add_box(foundation, Vector3(0, 0.3, 0), Vector3(w + 0.1, 0.6, d + 0.1))
	# cross-gable: front gable (ridge along X, matches front=-Z convention) +
	# a longer side ridge (along Z) intersecting it
	mb.add_gable_roof(shingles, Vector3(0, h, 0), w, d, 3.2, 0.4, white_col, true)
	mb.add_gable_roof(shingles, Vector3(1.5, h, 0), 4.5, d + 3.0, 2.6, 0.4, white_col, false)

	# projecting front-corner bay with its own small gable
	var bay_c := Vector3(-w * 0.5 - 1.1, 0, -d * 0.5 + 1.5)
	mb.add_box(siding, Vector3(bay_c.x, h * 0.55, bay_c.z), Vector3(2.2, h * 1.1, 2.2))
	mb.add_gable_roof(shingles, Vector3(bay_c.x, h * 1.1, bay_c.z), 2.2, 2.2, 1.4, 0.3, white_col, true)

	# wraparound porch: front + partial side, single storey
	var porch_d := 1.8
	var porch_h := 2.6
	mb.add_box(white_col, Vector3(0.5, 0.15, -d * 0.5 - porch_d * 0.5), Vector3(w + 1.5, 0.3, porch_d)) # deck
	mb.add_box(white_col, Vector3(0.5, porch_h, -d * 0.5 - porch_d * 0.5), Vector3(w + 1.5, 0.15, porch_d)) # roof slab (flat/shed, simplified)
	mb.add_box(white_col, Vector3(0.5, porch_h * 0.5, -d * 0.5 - porch_d * 0.9), Vector3(w + 1.5, 0.5, 0.1)) # rail band
	for i in range(5):
		var px2 := lerpf(-w * 0.5 + 0.5, w * 0.5 + 1.0, float(i) / 4.0)
		mb.add_cylinder(white_col, Vector3(px2, 0.3, -d * 0.5 - porch_d + 0.15), porch_h - 0.3, 0.1, 0.1, 8, false, false)
	# side wrap of the porch
	mb.add_box(white_col, Vector3(-w * 0.5 - porch_d * 0.5, 0.15, -d * 0.5 + 1.5), Vector3(porch_d, 0.3, 3.5))
	mb.add_box(white_col, Vector3(-w * 0.5 - porch_d * 0.5, porch_h, -d * 0.5 + 1.5), Vector3(porch_d, 0.15, 3.5))
	for i2 in range(3):
		var pz := lerpf(-d * 0.5, -d * 0.5 + 3.0, float(i2) / 2.0)
		mb.add_cylinder(white_col, Vector3(-w * 0.5 - porch_d + 0.15, 0.3, pz), porch_h - 0.3, 0.1, 0.1, 8, false, false)

	# chimney through the ridge
	mb.add_box(brick, Vector3(-1.5, h + 4.0, 1.5), Vector3(0.9, 8.0, 0.9))

	# windows on front + one side
	add_window_row(mb, glass, Vector3(0.5, 3.6, -d * 0.5 - 0.02), Vector3(w * 0.4, 3.6, -d * 0.5 - 0.02), 2, 0.9, 1.5, Vector3(0, 0, -1))
	add_window_row(mb, glass, Vector3(0.5, 3.6, -d * 0.5 - 0.02), Vector3(w * 0.4, 3.6, -d * 0.5 - 0.02), 2, 0.9, 1.5, Vector3(0, 0, -1))
	add_window_row(mb, glass, Vector3(-w * 0.5 - 0.02, 2.0, -d * 0.5 + 4.0), Vector3(-w * 0.5 - 0.02, 2.0, d * 0.5 - 1.0), 3, 0.9, 1.5, Vector3(-1, 0, 0))
	add_window_row(mb, glass, Vector3(-w * 0.5 - 0.02, 4.7, -d * 0.5 + 4.0), Vector3(-w * 0.5 - 0.02, 4.7, d * 0.5 - 1.0), 3, 0.9, 1.5, Vector3(-1, 0, 0))

	# subordinate visitor center, plain box + flat roof, off to one side
	var vc_c := Vector3(w * 0.5 + 6.0, 0, 1.0)
	mb.add_box(siding_gray, Vector3(vc_c.x, 2.2, vc_c.z), Vector3(7.0, 4.4, 8.0))
	mb.add_box(white_col, Vector3(vc_c.x, 4.5, vc_c.z), Vector3(7.4, 0.3, 8.4))

	mb.add_box_collision(Vector3(0, h * 0.5, 0), Vector3(w, h, d))
	mb.add_box_collision(Vector3(0.5, porch_h * 0.5, -d * 0.5 - porch_d * 0.5), Vector3(w + 1.5, porch_h, porch_d))
	mb.add_box_collision(Vector3(vc_c.x, 2.2, vc_c.z), Vector3(7.0, 4.4, 8.0))

	var mesh := mb.finalize()
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	root.add_child(mi)
	root.add_child(mb.build_collision_body("Collision"))
	return root


## ===========================================================================
## 6. Nachusa House
## ===========================================================================

func _build_nachusa_house() -> Node3D:
	var root := Node3D.new()
	root.name = "NachusaHouse"
	var mb := MB.new()
	var gy := 0.0

	var stucco := LM.flat_color("limestone", Color(0.92, 0.72, 0.36), 21.6, 0.72, {"uv_scale": Vector2(0.1, 0.1)})
	var base_brick := LM.flat_color("curb_concrete", Color(0.42, 0.42, 0.4), 21.6, 0.5, {"uv_scale": Vector2(0.4, 0.4)})
	var slate := LM.tinted("shingles_dark", 21.6, {"shingle_color_dark": Color(0.24, 0.2, 0.17), "shingle_color_light": Color(0.32, 0.27, 0.23), "use_world_uv": true})
	var trim_white := LM.flat_color("siding_white", Color(0.95, 0.94, 0.9), 21.6, 1.0, {"uv_scale": Vector2(0.4, 0.4)})
	var maroon := LM.flat_color("brick_red", Color(0.55, 0.2, 0.24), 21.6, 0.55, {"uv_scale": Vector2(0.3, 0.3)})
	var cornice_dark := LM.flat_color("stone_foundation", Color(0.13, 0.11, 0.09), 21.6, 0.4)
	var glass := LM.window_glass(21.6)

	var w := 25.0; var d := 14.0
	mb.add_box(base_brick, Vector3(0, 1.0, 0), Vector3(w, 2.0, d))
	mb.add_box(stucco, Vector3(0, 2.0 + 7.0, 0), Vector3(w, 14.0, d))
	mb.add_box(cornice_dark, Vector3(0, 16.8, 0), Vector3(w + 0.5, 0.8, d + 0.5))

	# regular window rhythm across the stucco floors (3rd/4th per the doc --
	# simplified to two representative bands across the whole stucco height)
	for fy: float in [7.0, 11.5]:
		add_window_row(mb, glass, Vector3(-w * 0.5 + 2.0, fy, -d * 0.5 - 0.02), Vector3(w * 0.5 - 2.0, fy, -d * 0.5 - 0.02), 6, 1.1, 2.0, Vector3(0, 0, -1))

	# two-tier porch/balcony across the front
	var porch_d := 2.0
	mb.add_box(maroon, Vector3(0, 3.6, -d * 0.5 - porch_d * 0.5), Vector3(w - 2.0, 0.25, porch_d)) # lower deck/roof slab
	mb.add_box(maroon, Vector3(0, 7.4, -d * 0.5 - porch_d * 0.5), Vector3(w - 3.0, 0.25, porch_d * 0.9)) # upper balcony slab
	mb.add_box(trim_white, Vector3(0, 5.5, -d * 0.5 - porch_d + 0.1), Vector3(w - 3.0, 0.5, 0.08)) # balustrade band
	for i in range(9):
		var px := lerpf(-w * 0.5 + 2.0, w * 0.5 - 2.0, float(i) / 8.0)
		mb.add_cylinder(maroon, Vector3(px, 0.0, -d * 0.5 - porch_d + 0.15), 7.4, 0.13, 0.11, 8, true, false)

	# cornice brackets (repeated small boxes under the eave)
	for i2 in range(14):
		var bx := lerpf(-w * 0.5 + 1.0, w * 0.5 - 1.0, float(i2) / 13.0)
		mb.add_box(cornice_dark, Vector3(bx, 16.3, -d * 0.5 + 0.3), Vector3(0.25, 0.5, 0.6))

	# mansard roof + pedimented dormers
	mb.add_mansard(slate, Vector3(0, 17.2, 0), w, d, 5.0, 4.0)
	for i3 in range(6):
		var dx := lerpf(-w * 0.5 + 3.0, w * 0.5 - 3.0, float(i3) / 5.0)
		var dz := -d * 0.5 + 0.6
		mb.add_box(trim_white, Vector3(dx, 19.0, dz), Vector3(1.5, 1.3, 0.7))
		mb.add_gable_roof(trim_white, Vector3(dx, 19.65, dz), 1.5, 0.7, 0.55, 0.15, trim_white, true)
		mb.add_panel(glass, Vector3(dx, 18.9, dz - 0.36), Vector3(0, 0, -1), 0.8, 0.9)

	mb.add_box_collision(Vector3(0, 9.0, 0), Vector3(w, 18.0, d))

	var mesh := mb.finalize()
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	root.add_child(mi)
	root.add_child(mb.build_collision_body("Collision"))
	return root
