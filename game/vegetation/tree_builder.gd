extends RefCounted
## Procedural vegetation mesh generation — branch skeletons (bark surface) +
## clumped leaf-card clusters (foliage surface), built once per (shape family,
## variation seed) at game start and shared by every instance of that
## combination via MultiMesh (see vegetation.gd). No external tree models;
## everything here is generated geometry per BUILDER_PROTOCOL's preference
## for build/import-time generation (this runs once in _ready(), <1s for the
## whole species/variation set — see docs/vegetation_notes.md perf numbers).
##
## Two-level branch recursion (trunk -> primary limbs -> secondary twigs ->
## leaf clusters) keeps geometry cheap (~150-300 tris/tree) while still
## showing real branch structure for winter's bare silhouette requirement.
class_name VegTreeBuilder

const TAU_F := 6.283185307

# ---------------------------------------------------------------------------
# Low-level geometry helpers
# ---------------------------------------------------------------------------

## Appends a tapered cylinder side surface (no caps) from base to top.
static func _add_cyl(st: SurfaceTool, base: Vector3, top: Vector3, r0: float, r1: float,
		sides: int, v0: float, v1: float) -> void:
	var axis := top - base
	var length := axis.length()
	if length < 0.001:
		return
	axis /= length
	var up := Vector3.UP
	if absf(axis.dot(up)) > 0.98:
		up = Vector3.RIGHT
	var right := axis.cross(up).normalized()
	up = right.cross(axis).normalized()

	var ring0: Array[Vector3] = []
	var ring1: Array[Vector3] = []
	var normals: Array[Vector3] = []
	for i in range(sides + 1):
		var a := (float(i) / float(sides)) * TAU_F
		var dir := (right * cos(a) + up * sin(a))
		normals.append(dir)
		ring0.append(base + dir * r0)
		ring1.append(top + dir * r1)

	for i in range(sides):
		var u0 := float(i) / float(sides)
		var u1 := float(i + 1) / float(sides)
		var n0 := normals[i]
		var n1 := normals[i + 1]
		var p00 := ring0[i]
		var p01 := ring0[i + 1]
		var p10 := ring1[i]
		var p11 := ring1[i + 1]
		# two tris, CCW winding viewed from outside
		st.set_normal(n0); st.set_uv(Vector2(u0, v0)); st.add_vertex(p00)
		st.set_normal(n1); st.set_uv(Vector2(u1, v0)); st.add_vertex(p01)
		st.set_normal(n1); st.set_uv(Vector2(u1, v1)); st.add_vertex(p11)

		st.set_normal(n0); st.set_uv(Vector2(u0, v0)); st.add_vertex(p00)
		st.set_normal(n1); st.set_uv(Vector2(u1, v1)); st.add_vertex(p11)
		st.set_normal(n0); st.set_uv(Vector2(u0, v1)); st.add_vertex(p10)


## Adds one crossed-double-quad leaf card centered at `center`, size `sz`,
## with the given baked season colors / AO / wind weight (foliage.gdshader
## reads COLOR = summer+ao, CUSTOM0 = autumn+wind_weight).
static func _add_card(st: SurfaceTool, center: Vector3, sz: float, rng: RandomNumberGenerator,
		summer: Color, autumn: Color, ao: float, wind_weight: float) -> void:
	var yaw := rng.randf() * TAU_F
	var tilt := rng.randf_range(-0.35, 0.35)
	var right := Vector3(cos(yaw), 0, sin(yaw))
	var up := Vector3(0, 1, 0).rotated(right, tilt) if right.length() > 0.01 else Vector3.UP
	var fwd := right.cross(up).normalized()
	var col := Color(summer.r, summer.g, summer.b, ao)
	var cus := Color(autumn.r, autumn.g, autumn.b, wind_weight)

	for pass_i in range(2):
		var r := right if pass_i == 0 else fwd
		var p00 := center - r * sz - up * sz
		var p10 := center + r * sz - up * sz
		var p11 := center + r * sz + up * sz
		var p01 := center - r * sz + up * sz
		var n := up.cross(r).normalized()
		st.set_color(col); st.set_custom(0, cus)
		st.set_normal(n); st.set_uv(Vector2(0, 0)); st.add_vertex(p00)
		st.set_normal(n); st.set_uv(Vector2(1, 0)); st.add_vertex(p10)
		st.set_normal(n); st.set_uv(Vector2(1, 1)); st.add_vertex(p11)
		st.set_color(col); st.set_custom(0, cus)
		st.set_normal(n); st.set_uv(Vector2(0, 0)); st.add_vertex(p00)
		st.set_normal(n); st.set_uv(Vector2(1, 1)); st.add_vertex(p11)
		st.set_normal(n); st.set_uv(Vector2(0, 1)); st.add_vertex(p01)


static func _add_leaf_cluster(st: SurfaceTool, center: Vector3, radius: float,
		rng: RandomNumberGenerator, summer: Color, autumn: Color, ao: float,
		wind_weight: float, n_cards: int) -> void:
	for i in range(n_cards):
		var off := Vector3(rng.randf_range(-1, 1), rng.randf_range(-0.6, 0.9), rng.randf_range(-1, 1)) * radius * 0.7
		var sz := radius * rng.randf_range(0.55, 0.95)
		var jitter_ao := clampf(ao + rng.randf_range(-0.15, 0.1), 0.35, 1.0)
		_add_card(st, center + off, sz, rng, summer, autumn, jitter_ao, wind_weight)


# ---------------------------------------------------------------------------
# Shape-family branch skeletons
# ---------------------------------------------------------------------------
## shape params: spread (0..1, wider = more horizontal branches), droop (-1..1,
## negative = branches sweep upward like elm, positive = droop like willow),
## leaf_density (cards per tip cluster), n_primary (major limbs off the trunk).
const SHAPE_PARAMS := {
	"round_broad": {"spread": 0.85, "droop": 0.0, "leaf_density": 6, "n_primary": 5, "cluster_r": 1.15},
	"oval_tall": {"spread": 0.55, "droop": -0.15, "leaf_density": 6, "n_primary": 4, "cluster_r": 1.05},
	"spreading_open": {"spread": 1.05, "droop": 0.15, "leaf_density": 4, "n_primary": 5, "cluster_r": 1.3},
	"vase_elm": {"spread": 0.35, "droop": -0.55, "leaf_density": 5, "n_primary": 5, "cluster_r": 1.1},
	"weeping_willow": {"spread": 0.55, "droop": 0.85, "leaf_density": 5, "n_primary": 6, "cluster_r": 0.95},
}


## Builds one deciduous tree at unit scale (trunk base at origin, ~1.0 total
## height) for the given shape family + seed. Returns an ArrayMesh with
## surface 0 = bark (mesh UV0, V=height/U=angle — compatible with
## materials/lib/bark.tres), surface 1 = foliage (foliage.gdshader).
static func build_deciduous(shape_family: String, seed: int, summer: Color, autumn: Color) -> ArrayMesh:
	var params: Dictionary = SHAPE_PARAMS.get(shape_family, SHAPE_PARAMS["round_broad"])
	var rng := RandomNumberGenerator.new()
	rng.seed = seed

	var st_bark := SurfaceTool.new()
	st_bark.begin(Mesh.PRIMITIVE_TRIANGLES)
	var st_leaf := SurfaceTool.new()
	st_leaf.begin(Mesh.PRIMITIVE_TRIANGLES)
	st_leaf.set_custom_format(0, SurfaceTool.CUSTOM_RGBA_FLOAT)

	var trunk_h := 0.42 + rng.randf_range(-0.04, 0.04)
	var trunk_top := Vector3(0, trunk_h, 0)
	_add_cyl(st_bark, Vector3.ZERO, trunk_top, 0.055, 0.032, 7, 0.0, trunk_h)

	var n_primary: int = params["n_primary"]
	var spread: float = params["spread"]
	var droop: float = params["droop"]
	var leaf_density: int = params["leaf_density"]
	var cluster_r: float = params["cluster_r"]

	for i in range(n_primary):
		var yaw := (float(i) / float(n_primary)) * TAU_F + rng.randf_range(-0.3, 0.3)
		var pitch := lerp(0.55, 1.15, rng.randf()) - droop * 0.3
		var dir := Vector3(cos(yaw) * spread, pitch, sin(yaw) * spread).normalized()
		var len1 := rng.randf_range(0.32, 0.46)
		var r0 := 0.030
		var mid := trunk_top + dir * len1
		_add_cyl(st_bark, trunk_top, mid, r0, r0 * 0.62, 6, trunk_h, trunk_h + len1)

		var n_sec := rng.randi_range(2, 3)
		for j in range(n_sec):
			var yaw2 := yaw + rng.randf_range(-0.9, 0.9)
			var pitch2 := pitch * 0.6 + rng.randf_range(-0.25, 0.45) + droop * 0.5
			var dir2 := Vector3(cos(yaw2) * (spread + 0.2), pitch2, sin(yaw2) * (spread + 0.2)).normalized()
			var len2 := rng.randf_range(0.16, 0.26)
			var tip := mid + dir2 * len2
			_add_cyl(st_bark, mid, tip, r0 * 0.6, r0 * 0.25, 5, 0.0, len2)
			var n_cards := leaf_density + rng.randi_range(-1, 2)
			_add_leaf_cluster(st_leaf, tip, cluster_r * 0.34, rng, summer, autumn, rng.randf_range(0.55, 0.95), rng.randf_range(0.6, 1.0), n_cards)
			# a mid-branch card for canopy fullness
			if rng.randf() < 0.6:
				_add_leaf_cluster(st_leaf, mid.lerp(tip, 0.45), cluster_r * 0.28, rng, summer, autumn, rng.randf_range(0.4, 0.7), rng.randf_range(0.4, 0.7), max(2, n_cards - 2))

	var bark_mesh := ArrayMesh.new()
	st_bark.commit(bark_mesh)
	var out := st_leaf.commit(bark_mesh)
	return out


const CONIFER_PARAMS := {
	"conifer_pine": {"taper": 0.55, "whorls": 7, "branch_droop": 0.35, "width": 1.0},
	"conifer_spruce_narrow": {"taper": 0.7, "whorls": 9, "branch_droop": 0.1, "width": 0.62},
}


static func build_conifer(shape_family: String, seed: int, color: Color) -> ArrayMesh:
	var params: Dictionary = CONIFER_PARAMS.get(shape_family, CONIFER_PARAMS["conifer_pine"])
	var rng := RandomNumberGenerator.new()
	rng.seed = seed

	var st_bark := SurfaceTool.new()
	st_bark.begin(Mesh.PRIMITIVE_TRIANGLES)
	var st_leaf := SurfaceTool.new()
	st_leaf.begin(Mesh.PRIMITIVE_TRIANGLES)
	st_leaf.set_custom_format(0, SurfaceTool.CUSTOM_RGBA_FLOAT)

	var total_h := 0.98
	var whorls: int = params["whorls"]
	var width: float = params["width"]
	var taper: float = params["taper"]
	var droop: float = params["branch_droop"]

	var prev := Vector3.ZERO
	var seg_h := total_h / float(whorls)
	for i in range(whorls):
		var y0 := float(i) * seg_h
		var y1 := y0 + seg_h
		var r0 := lerp(0.05, 0.008, float(i) / float(whorls))
		var r1 := lerp(0.05, 0.008, float(i + 1) / float(whorls))
		var top := Vector3(0, y1, 0)
		_add_cyl(st_bark, Vector3(0, y0, 0), top, r0, r1, 6, y0, y1)
		var level_t := float(i) / float(whorls) # 0 at base, 1 at tip
		var branch_len := width * (1.0 - level_t * taper) * 0.34
		var n_branches := 5 + (1 if i % 2 == 0 else 0)
		if branch_len > 0.05:
			for b in range(n_branches):
				var yaw := (float(b) / float(n_branches)) * TAU_F + rng.randf_range(-0.25, 0.25) + level_t * 2.0
				var pitch := -0.15 - droop * 0.5 + rng.randf_range(-0.08, 0.08)
				var dir := Vector3(cos(yaw), pitch, sin(yaw)).normalized()
				var tip := top + dir * branch_len
				_add_cyl(st_bark, top, tip, r1 * 0.9, r1 * 0.3, 4, 0.0, branch_len)
				var n_cards := 3
				_add_leaf_cluster(st_leaf, top.lerp(tip, 0.75), branch_len * 0.55, rng, color, color, rng.randf_range(0.5, 0.85), rng.randf_range(0.3, 0.6), n_cards)
		prev = top
	# treetop tuft
	_add_leaf_cluster(st_leaf, prev + Vector3(0, 0.03, 0), 0.09, rng, color, color, 0.9, 0.7, 3)

	var mesh := ArrayMesh.new()
	st_bark.commit(mesh)
	return st_leaf.commit(mesh)


## Squat rounded shrub or (columnar=true) a narrow hedge column. No bark
## surface (foundation plantings don't show trunk structure) — foliage only.
static func build_shrub(seed: int, summer: Color, autumn: Color, columnar: bool) -> ArrayMesh:
	var rng := RandomNumberGenerator.new()
	rng.seed = seed
	var st_leaf := SurfaceTool.new()
	st_leaf.begin(Mesh.PRIMITIVE_TRIANGLES)
	st_leaf.set_custom_format(0, SurfaceTool.CUSTOM_RGBA_FLOAT)

	if columnar:
		var levels := 5
		for i in range(levels):
			var t := float(i) / float(levels - 1)
			var y := lerp(0.15, 0.95, t)
			var r := lerp(0.30, 0.12, t)
			var n := 5
			for k in range(n):
				var a := (float(k) / float(n)) * TAU_F + rng.randf_range(-0.3, 0.3)
				var c := Vector3(cos(a) * r * 0.6, y, sin(a) * r * 0.6)
				_add_leaf_cluster(st_leaf, c, r * 0.55, rng, summer, autumn, rng.randf_range(0.5, 0.8), rng.randf_range(0.2, 0.4), 3)
	else:
		var n_clusters := 10
		for i in range(n_clusters):
			var a := rng.randf() * TAU_F
			var rad := rng.randf_range(0.25, 0.85)
			var y := rng.randf_range(0.15, 0.85)
			var c := Vector3(cos(a) * rad * 0.6, y, sin(a) * rad * 0.6)
			_add_leaf_cluster(st_leaf, c, 0.4 * rng.randf_range(0.7, 1.0), rng, summer, autumn, rng.randf_range(0.5, 0.9), rng.randf_range(0.4, 0.8), 3)

	var mesh := ArrayMesh.new()
	return st_leaf.commit(mesh)


## Small reedy clump for cattails: thin blade cards (grass.gdshader-compatible:
## surface 0 COLOR.a = tallness, UV.y = 0 base..1 tip).
static func build_cattail_clump(seed: int) -> ArrayMesh:
	var rng := RandomNumberGenerator.new()
	rng.seed = seed
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var n := rng.randi_range(5, 8)
	for i in range(n):
		var a := rng.randf() * TAU_F
		var base := Vector3(cos(a) * 0.08, 0, sin(a) * 0.08)
		var h := rng.randf_range(0.85, 1.0)
		var lean := Vector3(rng.randf_range(-0.12, 0.12), h, rng.randf_range(-0.12, 0.12))
		var right := Vector3(-sin(a), 0, cos(a)) * 0.035
		var col := Color(1, 1, 1, 1.0) # tallness=1 (unmown/riparian) — grass.gdshader ignores rgb, uses global season color
		st.set_color(col)
		st.set_normal(Vector3(sin(a), 0, -cos(a)))
		st.set_uv(Vector2(0, 0)); st.add_vertex(base - right)
		st.set_uv(Vector2(1, 0)); st.add_vertex(base + right)
		st.set_uv(Vector2(1, 1)); st.add_vertex(base + lean + right * 0.15)
		st.set_color(col)
		st.set_normal(Vector3(sin(a), 0, -cos(a)))
		st.set_uv(Vector2(0, 0)); st.add_vertex(base - right)
		st.set_uv(Vector2(1, 1)); st.add_vertex(base + lean + right * 0.15)
		st.set_uv(Vector2(0, 1)); st.add_vertex(base + lean - right * 0.15)
	var mesh := ArrayMesh.new()
	return st.commit(mesh)


## Simple cross-card billboard impostor for far LOD (2 crossed quads spanning
## the whole tree envelope). Reuses foliage.gdshader.
static func build_billboard(summer: Color, autumn: Color, height_frac: float = 1.0) -> ArrayMesh:
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	st.set_custom_format(0, SurfaceTool.CUSTOM_RGBA_FLOAT)
	var rng := RandomNumberGenerator.new()
	rng.seed = 1
	var center := Vector3(0, 0.55 * height_frac, 0)
	var col := Color(summer.r, summer.g, summer.b, 0.75)
	var cus := Color(autumn.r, autumn.g, autumn.b, 0.5)
	for pass_i in range(2):
		var right := Vector3(1, 0, 0) if pass_i == 0 else Vector3(0, 0, 1)
		var up := Vector3.UP
		var sz := 0.5
		var p00 := center - right * sz
		var p10 := center + right * sz
		var p11 := center + right * sz + up * sz * 2.0
		var p01 := center - right * sz + up * sz * 2.0
		var n := up.cross(right).normalized()
		st.set_color(col); st.set_custom(0, cus)
		st.set_normal(n); st.set_uv(Vector2(0, 0)); st.add_vertex(p00)
		st.set_normal(n); st.set_uv(Vector2(1, 0)); st.add_vertex(p10)
		st.set_normal(n); st.set_uv(Vector2(1, 1)); st.add_vertex(p11)
		st.set_color(col); st.set_custom(0, cus)
		st.set_normal(n); st.set_uv(Vector2(0, 0)); st.add_vertex(p00)
		st.set_normal(n); st.set_uv(Vector2(1, 1)); st.add_vertex(p11)
		st.set_normal(n); st.set_uv(Vector2(0, 1)); st.add_vertex(p01)
	var mesh := ArrayMesh.new()
	return st.commit(mesh)
