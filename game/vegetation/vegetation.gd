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

const NEAR_CHUNK := 120.0
const FAR_CHUNK := 300.0
const SHRUB_CHUNK := 120.0

## Perf pass (iter2): composed-world worst case (dense residential canopy,
## S Hennepin) measured 37.5fps/26.7ms with foliage.gdshader's original
## 3-octave-fbm-per-fragment cost + a 115m near-LOD range -- see
## docs/vegetation_notes.md "Performance". Cut the fbm cost (value_noise
## instead, see the shader) and pulled these ranges in so fewer full-detail
## trees are on screen at once (more of the view falls into the much
## cheaper billboard tier).
const NEAR_VIS_END := 90.0
const NEAR_VIS_BEGIN_FADE := 72.0
const FAR_VIS_BEGIN := 78.0
const FAR_VIS_END := 850.0
const SHRUB_VIS_END := 42.0

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

const FORM_BILLBOARD_COLOR := {
	"deciduous": {"summer": Color(0.14, 0.185, 0.09), "autumn": Color(0.42, 0.28, 0.10)},
	"conifer": {"summer": Color(0.07, 0.115, 0.09), "autumn": Color(0.07, 0.115, 0.09)},
}

var _bark_mat: ShaderMaterial
var _foliage_mat: ShaderMaterial
var _grass_mat: ShaderMaterial
var _mesh_cache: Dictionary = {} # species -> [mesh_var0, mesh_var1, mesh_var2]
var _billboard_cache: Dictionary = {} # form -> mesh
var _cattail_mesh: ArrayMesh

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


func _build_materials() -> void:
	var base_bark := load("res://materials/lib/bark.tres")
	_bark_mat = base_bark.duplicate()
	_bark_mat.set_shader_parameter("grime_strength", 0.0)
	_bark_mat.set_shader_parameter("uv_scale", Vector2(3.0, 3.0))

	_foliage_mat = ShaderMaterial.new()
	_foliage_mat.shader = load("res://vegetation/shaders/foliage.gdshader")

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
				mesh.surface_set_material(1, _foliage_mat)
			"hedge":
				mesh = VegTreeBuilder.build_shrub(seed, info["summer"], info["autumn"], true)
				mesh.surface_set_material(0, _foliage_mat)
			"shrub":
				mesh = VegTreeBuilder.build_shrub(seed, info["summer"], info["autumn"], false)
				mesh.surface_set_material(0, _foliage_mat)
			_:
				mesh = VegTreeBuilder.build_shrub(seed, info["summer"], info["autumn"], false)
				mesh.surface_set_material(0, _foliage_mat)
		arr[variation] = mesh
	return arr[variation]


func _get_billboard(form: String) -> ArrayMesh:
	if not _billboard_cache.has(form):
		var c: Dictionary = FORM_BILLBOARD_COLOR.get(form, FORM_BILLBOARD_COLOR["deciduous"])
		var mesh := VegTreeBuilder.build_billboard(c["summer"], c["autumn"])
		mesh.surface_set_material(0, _foliage_mat)
		_billboard_cache[form] = mesh
	return _billboard_cache[form]


func _get_cattail_mesh() -> ArrayMesh:
	if _cattail_mesh == null:
		_cattail_mesh = VegTreeBuilder.build_cattail_clump(42)
		_cattail_mesh.surface_set_material(0, _grass_mat)
	return _cattail_mesh


func _xform(x: float, y: float, z: float, rot_deg: float, scale: float) -> Transform3D:
	var basis := Basis(Vector3.UP, deg_to_rad(rot_deg)).scaled(Vector3.ONE * scale)
	return Transform3D(basis, Vector3(x, y, z))


func _place_trees(instances: Array) -> void:
	# near LOD: (chunk, species, variation) -> Array[Transform3D]
	var near_groups: Dictionary = {}
	# far LOD: (chunk, form) -> Array[Transform3D]
	var far_groups: Dictionary = {}

	for inst in instances:
		var x: float = inst["x"]; var y: float = inst["y"]; var z: float = inst["z"]
		var species: String = inst["species"]
		if not SPECIES.has(species):
			continue
		var info: Dictionary = SPECIES[species]
		var height: float = inst["height_m"]
		var seed: int = inst["seed"]
		var category: String = inst.get("category", "")
		# iter1 critique: street trees (from the general species height table,
		# same range as yard/park trees) formed a continuous ~15-22m canopy
		# wall that hid the houses/street entirely. Real mature street trees
		# run ~8-18m with proportionally smaller crowns -- compress just this
		# category (yard/park keep the full "old neighborhood" range the
		# brief asked for) and thin ~15% more for driveway-scale gaps.
		if category == "street" or category == "downtown":
			height = clamp(height * 0.60, 7.0, 15.0)
			if seed % 100 < 15:
				continue
		var variation: int = seed % N_VARIATIONS
		var rot: float = inst["rot_deg"]
		var xf := _xform(x, y, z, rot, height)

		var ncx := int(floor(x / NEAR_CHUNK)); var ncz := int(floor(z / NEAR_CHUNK))
		var nkey := "%d_%d_%s_%d" % [ncx, ncz, species, variation]
		if not near_groups.has(nkey):
			near_groups[nkey] = {"species": species, "variation": variation, "xforms": []}
		near_groups[nkey]["xforms"].append(xf)

		var fcx := int(floor(x / FAR_CHUNK)); var fcz := int(floor(z / FAR_CHUNK))
		var fkey := "%d_%d_%s" % [fcx, fcz, info["form"]]
		if not far_groups.has(fkey):
			far_groups[fkey] = {"form": info["form"], "xforms": []}
		far_groups[fkey]["xforms"].append(xf)

	for key in near_groups:
		var g: Dictionary = near_groups[key]
		var mesh := _get_mesh(g["species"], g["variation"])
		_add_multimesh(_near_root, mesh, g["xforms"], NEAR_VIS_END, NEAR_VIS_END - NEAR_VIS_BEGIN_FADE, 0.0, 0.0)

	for key in far_groups:
		var g: Dictionary = far_groups[key]
		var mesh := _get_billboard(g["form"])
		_add_multimesh(_far_root, mesh, g["xforms"], 0.0, 0.0, FAR_VIS_BEGIN, 25.0)


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
		_add_multimesh(_shrub_root, mesh, g["xforms"], SHRUB_VIS_END, 15.0, 0.0, 0.0)

	var cmesh := _get_cattail_mesh()
	for key in cattail_groups:
		_add_multimesh(_shrub_root, cmesh, cattail_groups[key], SHRUB_VIS_END, 15.0, 0.0, 0.0)


## end/end_margin: instances fade out approaching `end`, fully hidden beyond
## it (fade zone = [end-end_margin, end]). begin/begin_margin: instances fade
## in approaching `begin` from below, fully visible at/above it (fade zone =
## [begin-begin_margin, begin]). Pass 0 to skip either range.
func _add_multimesh(parent: Node3D, mesh: ArrayMesh, xforms: Array,
		end: float, end_margin: float, begin: float, begin_margin: float) -> void:
	if xforms.is_empty():
		return
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = mesh
	mm.instance_count = xforms.size()
	for i in range(xforms.size()):
		mm.set_instance_transform(i, xforms[i])
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	if end > 0.0:
		mmi.visibility_range_end = end
		mmi.visibility_range_end_margin = end_margin
	if begin > 0.0:
		mmi.visibility_range_begin = begin
		mmi.visibility_range_begin_margin = begin_margin
	mmi.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF
	parent.add_child(mmi)
