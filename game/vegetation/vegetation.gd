extends Node3D
## Vegetation composition root: loads the deterministic placement plan baked
## by pipeline/vegetation/place_vegetation.py (game/vegetation/data/*.json),
## builds procedural tree/shrub meshes once (tree_builder.gd), and chunks
## everything into MultiMeshInstance3D nodes with near/far visibility_range
## LOD. Also instances GrassSpawner for near-camera dynamic grass. See
## docs/vegetation_notes.md.
##
## Runs entirely in _ready() (~1-2s for ~17k trees + ~10k shrubs — mesh
## building dominates, MultiMesh instancing itself is fast) per
## BUILDER_PROTOCOL's "runtime generation OK if fast and cached" allowance;
## nothing here is re-computed after the first frame.

const VegTreeBuilder = preload("res://vegetation/tree_builder.gd")

## Per-tree LOD (see docs/vegetation_notes.md "LOD"). Chunk visibility_range
## is only a coarse cull: Godot tests it against each chunk's AABB centre, so
## with 120 m chunks a tree 10 m away could vanish because its chunk's centre
## was 110 m off. Each tree now fades itself between the near mesh and the
## far impostor in the shaders (tree_common.gdshaderinc) by its own distance,
## and the chunk ranges only need to be loose enough never to cut a tree
## that should still be drawing.
const NEAR_CHUNK := 64.0
const FAR_CHUNK := 256.0
const SHRUB_CHUNK := 64.0

## Near mesh -> impostor crossfade over [LOD_NEAR_END - LOD_BAND, LOD_NEAR_END]
## measured per tree. Impostors have no far limit: the whole town is ~2.8 km
## across and one quad per tree is cheap.
const LOD_NEAR_END := 130.0
const LOD_BAND := 25.0
## Leafless crowns hand over sooner: the impostor's twig haze looks the same
## as the near cards' haze past ~60 m and costs one quad instead of a crown
## of cards.
const LOD_NEAR_END_BARE := 75.0
const SHRUB_LOD_END := 70.0
const SHRUB_LOD_BAND := 15.0
## Chunk cull slack: chunk AABB half-diagonal (horizontal + height spread)
## plus a crown radius, so a chunk is never culled while a tree in it is
## inside its per-tree LOD range.
const NEAR_CHUNK_SLACK := NEAR_CHUNK * 0.75 + 25.0
const SHRUB_VIS_END := SHRUB_LOD_END + SHRUB_CHUNK * 0.75 + 10.0
const CATTAIL_VIS_END := 60.0

## Percent of yard/park/wood trees skipped at build time (see _place_trees).
const DENSITY_THIN_PCT := 15

## Allowed crown width / height aspect distortion when fitting the shared
## variation meshes to each tree's planned canopy_r_m and height_m.
const MAX_CROWN_STRETCH := 1.5

const N_VARIATIONS := 3

# species -> {family, form, summer:Color, autumn:Color}
# NOTE: these are LINEAR albedo values fed straight to ALBEDO, tuned down
# significantly from a naive hex-picker guess -- this render pipeline's AgX
# tonemap + SDFGI bounce reads foliage much brighter than the raw numbers
# suggest (same lesson roads/terrain hit with asphalt/grass albedo; see
# docs/roads_notes.md "Material fixes"). Measured/adjusted empirically
# against ART_DIRECTION's implied ~0.08-0.18 linear range for a sunlit
# summer canopy (#4f6b32-#6d8a45) -- see docs/vegetation_notes.md.
const SPECIES := {
	"bur_oak": {"family": "round_broad", "form": "deciduous",
		"summer": Color(0.13, 0.18, 0.075), "autumn": Color(0.30, 0.20, 0.11)},
	"white_oak": {"family": "round_broad", "form": "deciduous",
		"summer": Color(0.12, 0.17, 0.085), "autumn": Color(0.32, 0.22, 0.12)},
	"silver_maple": {"family": "oval_tall", "form": "deciduous",
		"summer": Color(0.15, 0.20, 0.095), "autumn": Color(0.52, 0.22, 0.06)},
	"sugar_maple": {"family": "round_broad", "form": "deciduous",
		"summer": Color(0.14, 0.195, 0.085), "autumn": Color(0.56, 0.16, 0.05)},
	"honey_locust": {"family": "spreading_open", "form": "deciduous",
		"summer": Color(0.18, 0.23, 0.11), "autumn": Color(0.50, 0.42, 0.10)},
	"cottonwood": {"family": "oval_tall", "form": "deciduous",
		"summer": Color(0.17, 0.215, 0.12), "autumn": Color(0.48, 0.40, 0.12)},
	"american_elm": {"family": "vase_elm", "form": "deciduous",
		"summer": Color(0.135, 0.185, 0.09), "autumn": Color(0.42, 0.34, 0.09)},
	"hackberry": {"family": "round_broad", "form": "deciduous",
		"summer": Color(0.115, 0.165, 0.08), "autumn": Color(0.36, 0.30, 0.12)},
	"willow": {"family": "weeping_willow", "form": "deciduous",
		"summer": Color(0.18, 0.23, 0.135), "autumn": Color(0.44, 0.38, 0.14)},
	"white_pine": {"family": "conifer_pine", "form": "conifer",
		"summer": Color(0.06, 0.11, 0.065), "autumn": Color(0.06, 0.11, 0.065)},
	"blue_spruce": {"family": "conifer_spruce_narrow", "form": "conifer",
		"summer": Color(0.08, 0.12, 0.14), "autumn": Color(0.08, 0.12, 0.14)},
	"arborvitae": {"family": "hedge", "form": "hedge",
		"summer": Color(0.075, 0.135, 0.08), "autumn": Color(0.075, 0.135, 0.08)},
	"shrub_foundation": {"family": "shrub", "form": "shrub",
		"summer": Color(0.105, 0.155, 0.075), "autumn": Color(0.32, 0.25, 0.11)},
	"shrub_wild": {"family": "shrub", "form": "shrub",
		"summer": Color(0.115, 0.155, 0.065), "autumn": Color(0.34, 0.27, 0.10)},
}

var _bark_mat: ShaderMaterial
var _foliage_mat: ShaderMaterial
var _evergreen_mat: ShaderMaterial
var _shrub_mat: ShaderMaterial
var _hedge_mat: ShaderMaterial
var _impostor_mat: ShaderMaterial
var _impostor_shadow_mat: ShaderMaterial
var _grass_mat: ShaderMaterial
var _mesh_cache: Dictionary = {} # species -> [mesh_var0, mesh_var1, mesh_var2]
var _impostor_mesh: ArrayMesh
var _cattail_mesh: ArrayMesh
var _lod_mats: Array[ShaderMaterial] = []
var _near_end := LOD_NEAR_END

var _near_root: Node3D
var _far_root: Node3D
var _shrub_root: Node3D


func _ready() -> void:
	var t0 := Time.get_ticks_msec()
	_build_materials()
	_near_root = Node3D.new(); _near_root.name = "TreesNear"; add_child(_near_root)
	_far_root = Node3D.new(); _far_root.name = "TreesFar"; add_child(_far_root)
	_shrub_root = Node3D.new(); _shrub_root.name = "Shrubs"; add_child(_shrub_root)

	var trees := _load_json("res://vegetation/data/trees.json")
	var shrubs := _load_json("res://vegetation/data/shrubs.json")
	if trees:
		_place_trees(trees.get("instances", []))
	if shrubs:
		_place_shrubs(shrubs.get("instances", []))

	var spawner_script = load("res://vegetation/grass_spawner.gd")
	var spawner = Node3D.new()
	spawner.name = "GrassSpawner"
	spawner.set_script(spawner_script)
	add_child(spawner)

	print("[vegetation] ready in %d ms (%d trees, %d shrubs)" % [
		Time.get_ticks_msec() - t0, trees.get("count", 0) if trees else 0,
		shrubs.get("count", 0) if shrubs else 0])


func _load_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		push_warning("[vegetation] missing %s (run pipeline/vegetation/place_vegetation.py)" % path)
		return {}
	var f := FileAccess.open(path, FileAccess.READ)
	var text := f.get_as_text()
	var parsed = JSON.parse_string(text)
	if parsed == null:
		push_warning("[vegetation] failed to parse %s" % path)
		return {}
	return parsed


## Keeps the per-tree LOD centred on the active camera. Shadow passes see
## the light as their camera, so the shaders read this instead of
## CAMERA_POSITION_WORLD.
func _process(_delta: float) -> void:
	var cam := get_viewport().get_camera_3d()
	if cam == null:
		return
	var p := cam.global_position
	for m in _lod_mats:
		m.set_shader_parameter("veg_camera_pos", p)
	# Looked up rather than named, so the script still compiles where the
	# autoload isn't registered (vegetation_selftest.gd runs via --script).
	var ws := get_node_or_null("/root/WorldState")
	var bare := smoothstep(0.8, 1.0, ws.get_foliage()) if ws else 0.0
	var near_end := lerpf(LOD_NEAR_END, LOD_NEAR_END_BARE, bare)
	if not is_equal_approx(near_end, _near_end):
		_near_end = near_end
		for m in [_bark_mat, _foliage_mat, _evergreen_mat, _impostor_mat]:
			m.set_shader_parameter("lod_near_end", near_end)


func _build_materials() -> void:
	# Bark: same texture set as materials/lib/bark.tres, in a lean shader that
	# fades per tree with the crown (tree_bark.gdshader).
	var base_bark: ShaderMaterial = load("res://materials/lib/bark.tres")
	_bark_mat = ShaderMaterial.new()
	_bark_mat.shader = load("res://vegetation/shaders/tree_bark.gdshader")
	_bark_mat.set_shader_parameter("albedo_tex", base_bark.get_shader_parameter("albedo_tex"))
	_bark_mat.set_shader_parameter("normal_tex", base_bark.get_shader_parameter("normal_tex"))
	_bark_mat.set_shader_parameter("albedo_multiplier", base_bark.get_shader_parameter("albedo_multiplier"))
	_bark_mat.set_shader_parameter("uv_scale", Vector2(3.0, 3.0))

	var foliage_shader: Shader = load("res://vegetation/shaders/foliage.gdshader")
	_foliage_mat = ShaderMaterial.new()
	_foliage_mat.shader = foliage_shader
	_evergreen_mat = ShaderMaterial.new()
	_evergreen_mat.shader = foliage_shader
	_evergreen_mat.set_shader_parameter("evergreen", true)
	_shrub_mat = ShaderMaterial.new()
	_shrub_mat.shader = foliage_shader
	_hedge_mat = ShaderMaterial.new()
	_hedge_mat.shader = foliage_shader
	_hedge_mat.set_shader_parameter("evergreen", true)
	_impostor_mat = ShaderMaterial.new()
	_impostor_mat.shader = load("res://vegetation/shaders/tree_impostor.gdshader")
	_impostor_shadow_mat = _impostor_mat.duplicate()
	_impostor_shadow_mat.set_shader_parameter("shadow_proxy", true)

	for m in [_bark_mat, _foliage_mat, _evergreen_mat, _impostor_mat, _impostor_shadow_mat]:
		m.set_shader_parameter("lod_near_end", LOD_NEAR_END)
		m.set_shader_parameter("lod_band", LOD_BAND)
	for m in [_shrub_mat, _hedge_mat]:
		m.set_shader_parameter("lod_near_end", SHRUB_LOD_END)
		m.set_shader_parameter("lod_band", SHRUB_LOD_BAND)
	_lod_mats = [_bark_mat, _foliage_mat, _evergreen_mat, _impostor_mat, _impostor_shadow_mat, _shrub_mat, _hedge_mat]

	_grass_mat = ShaderMaterial.new()
	_grass_mat.shader = load("res://vegetation/shaders/grass.gdshader")


func _get_mesh(species: String, variation: int) -> ArrayMesh:
	if not _mesh_cache.has(species):
		_mesh_cache[species] = [null, null, null]
	var arr: Array = _mesh_cache[species]
	if arr[variation] == null:
		var info: Dictionary = SPECIES[species]
		var seed := hash(species) + variation * 977
		var mesh: ArrayMesh
		match info["form"]:
			"deciduous":
				mesh = VegTreeBuilder.build_deciduous(info["family"], seed, info["summer"], info["autumn"])
				mesh.surface_set_material(0, _bark_mat)
				mesh.surface_set_material(1, _foliage_mat)
			"conifer":
				mesh = VegTreeBuilder.build_conifer(info["family"], seed, info["summer"])
				mesh.surface_set_material(0, _bark_mat)
				mesh.surface_set_material(1, _evergreen_mat)
			"hedge":
				mesh = VegTreeBuilder.build_shrub(seed, info["summer"], info["autumn"], true)
				mesh.surface_set_material(0, _hedge_mat)
			_:
				mesh = VegTreeBuilder.build_shrub(seed, info["summer"], info["autumn"], false)
				mesh.surface_set_material(0, _shrub_mat)
		arr[variation] = mesh
	return arr[variation]


func _get_impostor_mesh() -> ArrayMesh:
	if _impostor_mesh == null:
		_impostor_mesh = VegTreeBuilder.build_impostor_quad()
		_impostor_mesh.surface_set_material(0, _impostor_mat)
	return _impostor_mesh


static func _pack_rgb(c: Color) -> float:
	# 8:8:8 into one float (exact below 2^24); unpacked in tree_impostor.gdshader.
	var r := clampi(int(round(c.r * 255.0)), 0, 255)
	var g := clampi(int(round(c.g * 255.0)), 0, 255)
	var b := clampi(int(round(c.b * 255.0)), 0, 255)
	return float(r + g * 256 + b * 65536)


func _get_cattail_mesh() -> ArrayMesh:
	if _cattail_mesh == null:
		_cattail_mesh = VegTreeBuilder.build_cattail_clump(42)
		_cattail_mesh.surface_set_material(0, _grass_mat)
	return _cattail_mesh


func _xform(x: float, y: float, z: float, rot_deg: float, scale: float) -> Transform3D:
	var basis := Basis(Vector3.UP, deg_to_rad(rot_deg)).scaled(Vector3.ONE * scale)
	return Transform3D(basis, Vector3(x, y, z))

## Fits a shared unit-height variation mesh to one tree's planned size:
## vertical scale = height_m, horizontal scale chosen so the mesh's measured
## crown radius (mesh meta "crown_r") becomes canopy_r_m, limited to
## MAX_CROWN_STRETCH of uniform so the leaf cards don't smear.
func _tree_basis(rot_deg: float, height: float, canopy_r: float, crown_r: float) -> Basis:
	var xz := canopy_r / maxf(crown_r, 0.05)
	xz = clampf(xz, height / MAX_CROWN_STRETCH, height * MAX_CROWN_STRETCH)
	return Basis(Vector3.UP, deg_to_rad(rot_deg)).scaled(Vector3(xz, height, xz))


func _place_trees(instances: Array) -> void:
	# near LOD: (chunk, species, variation) -> Array[Transform3D]
	var near_groups: Dictionary = {}
	# far LOD: chunk -> {xforms, customs}
	var far_groups: Dictionary = {}

	for inst in instances:
		var x: float = inst["x"]; var y: float = inst["y"]; var z: float = inst["z"]
		var species: String = inst["species"]
		if not SPECIES.has(species):
			continue
		var info: Dictionary = SPECIES[species]
		var height: float = inst["height_m"]
		var canopy_radius: float = float(inst.get("canopy_r_m", height * 0.45))
		var seed: int = inst["seed"]
		var category: String = inst.get("category", "")
		# iter1 critique: street trees (from the general species height table,
		# same range as yard/park trees) formed a continuous canopy wall that
		# hid the houses/street. Real mature street trees run ~8-18m with
		# proportionally smaller crowns -- compress just this category and thin
		# ~15% more for driveway-scale gaps. (Factor was 0.6 while the meshes
		# still rendered 1.5x their nominal height; 0.8 on the corrected meshes
		# keeps street trees at a similar on-screen size.)
		if category == "street" or category == "downtown":
			height = clamp(height * 0.80, 6.0, 16.0)
			canopy_radius *= 0.75
			if seed % 100 < 15:
				continue
		elif category != "osm" and (seed / 100) % 100 < DENSITY_THIN_PCT:
			# Render-time thinning of yard/park/wood trees (perf budget,
			# agreed 2026-10-19): dense park/wood stands were the worst
			# fill-rate case. Independent digits of the seed from the
			# street-tree thinning above.
			continue
		var variation: int = seed % N_VARIATIONS
		var rot: float = inst["rot_deg"]
		var mesh := _get_mesh(species, variation)
		var crown_r: float = mesh.get_meta("crown_r", 0.5)
		var crown_base: float = mesh.get_meta("crown_base", 0.3)
		var basis := _tree_basis(rot, height, canopy_radius, crown_r)
		var origin := Vector3(x, y, z)

		var ncx := int(floor(x / NEAR_CHUNK)); var ncz := int(floor(z / NEAR_CHUNK))
		var nkey := "%d_%d_%s_%d" % [ncx, ncz, species, variation]
		if not near_groups.has(nkey):
			near_groups[nkey] = {"species": species, "variation": variation, "xforms": []}
		near_groups[nkey]["xforms"].append(Transform3D(basis, origin))

		# Impostor: width = rendered crown diameter, height = tree height.
		var crown_w := basis.x.length() * crown_r * 2.0
		var far_xf := Transform3D(Basis().scaled(Vector3(crown_w, height, crown_w)), origin)
		var conifer := 1.0 if info["form"] == "conifer" else 0.0
		var custom := Color(_pack_rgb(info["summer"]), _pack_rgb(info["autumn"]), conifer, crown_base)
		var fcx := int(floor(x / FAR_CHUNK)); var fcz := int(floor(z / FAR_CHUNK))
		var fkey := "%d_%d" % [fcx, fcz]
		if not far_groups.has(fkey):
			far_groups[fkey] = {"xforms": [], "customs": []}
		far_groups[fkey]["xforms"].append(far_xf)
		far_groups[fkey]["customs"].append(custom)

	for key in near_groups:
		var g: Dictionary = near_groups[key]
		var mesh := _get_mesh(g["species"], g["variation"])
		var near_mmi := _add_multimesh(_near_root, mesh, g["xforms"], LOD_NEAR_END + NEAR_CHUNK_SLACK, 0.0, 0.0, 0.0)
		near_mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF # see shadow proxy below

	var imp := _get_impostor_mesh()
	for key in far_groups:
		var g: Dictionary = far_groups[key]
		var mmi := _add_multimesh(_far_root, imp, g["xforms"], 0.0, 0.0, 0.0, 0.0, g["customs"])
		mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		# Shadow proxy: every tree's shadow comes from its impostor, drawn
		# facing the light and ignoring the LOD fade. Near crowns are
		# fill-rate bound and cast into 4 cascades, which cost ~3 ms at
		# street level; one quad per tree is nearly free, and the shadow no
		# longer changes shape when a tree crosses the LOD band.
		var shadow_mmi := _add_multimesh(_far_root, imp, g["xforms"], 0.0, 0.0, 0.0, 0.0, g["customs"])
		shadow_mmi.material_override = _impostor_shadow_mat
		shadow_mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_SHADOWS_ONLY


func _place_shrubs(instances: Array) -> void:
	var groups: Dictionary = {}
	var cattail_groups: Dictionary = {}

	for inst in instances:
		var x: float = inst["x"]; var y: float = inst["y"]; var z: float = inst["z"]
		var species: String = inst["species"]
		var height: float = inst["height_m"]
		var seed: int = inst["seed"]
		var rot: float = inst["rot_deg"]
		var xf := _xform(x, y, z, rot, height)
		var cx := int(floor(x / SHRUB_CHUNK)); var cz := int(floor(z / SHRUB_CHUNK))

		if species == "cattail":
			var ckey := "%d_%d" % [cx, cz]
			if not cattail_groups.has(ckey):
				cattail_groups[ckey] = []
			cattail_groups[ckey].append(xf)
			continue
		if not SPECIES.has(species):
			continue
		var variation: int = seed % N_VARIATIONS
		var key := "%d_%d_%s_%d" % [cx, cz, species, variation]
		if not groups.has(key):
			groups[key] = {"species": species, "variation": variation, "xforms": []}
		groups[key]["xforms"].append(xf)

	for key in groups:
		var g: Dictionary = groups[key]
		var mesh := _get_mesh(g["species"], g["variation"])
		_add_multimesh(_shrub_root, mesh, g["xforms"], SHRUB_VIS_END, 0.0, 0.0, 0.0)

	var cmesh := _get_cattail_mesh()
	for key in cattail_groups:
		_add_multimesh(_shrub_root, cmesh, cattail_groups[key], CATTAIL_VIS_END, 10.0, 0.0, 0.0)


## Chunk-level visibility_range (Godot measures it from the camera to the
## chunk's AABB centre). end/end_margin: hidden beyond end + end_margin, a
## self-fade over end +- end_margin when end_margin > 0. begin likewise.
## Pass 0 to skip either range. Tree and shrub chunks pass margin 0: their
## real fade is per tree in the shaders and the chunk range is only a cull.
## customs: optional per-instance INSTANCE_CUSTOM values.
func _add_multimesh(parent: Node3D, mesh: ArrayMesh, xforms: Array,
		end: float, end_margin: float, begin: float, begin_margin: float,
		customs: Array = []) -> MultiMeshInstance3D:
	if xforms.is_empty():
		return null
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_custom_data = not customs.is_empty()
	mm.mesh = mesh
	mm.instance_count = xforms.size()
	for i in range(xforms.size()):
		mm.set_instance_transform(i, xforms[i])
		if mm.use_custom_data:
			mm.set_instance_custom_data(i, customs[i])
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	if end > 0.0:
		mmi.visibility_range_end = end
		mmi.visibility_range_end_margin = end_margin
	if begin > 0.0:
		mmi.visibility_range_begin = begin
		mmi.visibility_range_begin_margin = begin_margin
	mmi.visibility_range_fade_mode = (GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF
		if end_margin > 0.0 or begin_margin > 0.0 else GeometryInstance3D.VISIBILITY_RANGE_FADE_DISABLED)
	parent.add_child(mmi)
	return mmi
