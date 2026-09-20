class_name LandmarkMeshBuilder
extends RefCounted
## Shared low/mid-poly primitive builder for the six landmark generators
## (build_landmarks.gd). One SurfaceTool per Material, merged into a single
## multi-surface ArrayMesh by finalize(). All materials used here are either
## `use_world_uv`/triplanar (world-position projected, so mesh UV0 is a
## don't-care -- left at 0,0) or explicitly UV0-driven (window_glass,
## shingles_dark), for which callers pass real UV coordinates (in meters, see
## add_quad_uv) so orientation doesn't depend on any particular local-axis
## convention.
##
## Coordinate convention used by every generator: local space, +Y up, ground
## at local Y=0. Each landmark's own local axes are whatever's convenient for
## that generator; build_landmarks.gd's `place()` step applies a single
## Y-rotation + world translation per landmark (derived from real footprint
## bearings in docs/pipeline_notes.md / OSM data -- see header comment in
## build_landmarks.gd) so the result faces the correct real-world street.

var _surfaces: Dictionary = {} # Material -> SurfaceTool
var _colliders: Array = [] # Array of {shape:Shape3D, xform:Transform3D}

func _st(mat: Material) -> SurfaceTool:
	if not _surfaces.has(mat):
		var st := SurfaceTool.new()
		st.begin(Mesh.PRIMITIVE_TRIANGLES)
		_surfaces[mat] = st
	return _surfaces[mat]

## -- low-level ------------------------------------------------------------

func add_tri(mat: Material, a: Vector3, b: Vector3, c: Vector3, uv_a := Vector2.ZERO, uv_b := Vector2.ZERO, uv_c := Vector2.ZERO) -> void:
	var st := _st(mat)
	# Callers order corners CCW as seen from OUTSIDE (see add_quad's contract), but
	# Godot treats a clockwise-from-the-front triangle as front-facing. Submitting the
	# caller's order verbatim therefore made every wall a back face: from the street
	# you looked straight through the near wall into an unlit interior, which read as
	# a black void ("buildings have missing sides", user screenshots 2026-09-20).
	# Submit reversed (a, c, b) so the outward side is the FRONT face; the shading
	# normal stays the geometric outward normal.
	var n := (b - a).cross(c - a).normalized()
	st.set_normal(n); st.set_uv(uv_a); st.add_vertex(a)
	st.set_normal(n); st.set_uv(uv_c); st.add_vertex(c)
	st.set_normal(n); st.set_uv(uv_b); st.add_vertex(b)

## Quad a,b,c,d in CCW winding as seen from the visible (outward) side.
func add_quad(mat: Material, a: Vector3, b: Vector3, c: Vector3, d: Vector3) -> void:
	add_tri(mat, a, b, c)
	add_tri(mat, a, c, d)

## Quad with explicit per-corner UVs (meters, or 0..1 -- caller's convention
## matches whatever the material expects; see window_glass / shingles_dark).
func add_quad_uv(mat: Material, a: Vector3, b: Vector3, c: Vector3, d: Vector3, uva: Vector2, uvb: Vector2, uvc: Vector2, uvd: Vector2) -> void:
	add_tri(mat, a, b, c, uva, uvb, uvc)
	add_tri(mat, a, c, d, uva, uvc, uvd)

## Flat rectangular panel centered at `center`, facing outward along `normal`
## (any direction, need not be axis-aligned), `width`/`height` in meters. Use
## for windows, signage, and any other single flat quad -- the ordering is
## derived generically (right := up_hint.cross(normal), true_up :=
## normal.cross(right)) so cross(b-a,c-a) always comes out parallel to
## `normal` regardless of which way normal points; safer than hand-deriving
## per-quad vertex order (see the cylinder/dome/mansard/gable fixes above,
## all of which shipped backwards on the first pass).
func add_panel(mat: Material, center: Vector3, normal: Vector3, width: float, height: float, up_hint: Vector3 = Vector3(0, 1, 0), uv_min: Vector2 = Vector2.ZERO, uv_max: Vector2 = Vector2.ONE) -> void:
	var n := normal.normalized()
	var hint := up_hint.normalized()
	if absf(n.dot(hint)) > 0.99:
		hint = Vector3(0, 0, 1)
	var right := hint.cross(n).normalized()
	var true_up := n.cross(right).normalized()
	var r := right * (width * 0.5)
	var u := true_up * (height * 0.5)
	var a := center - r - u
	var b := center + r - u
	var c := center + r + u
	var d := center - r + u
	add_quad_uv(mat, a, b, c, d, Vector2(uv_min.x, uv_min.y), Vector2(uv_max.x, uv_min.y), Vector2(uv_max.x, uv_max.y), Vector2(uv_min.x, uv_max.y))

## -- boxes ------------------------------------------------------------------

## Axis-aligned box, optionally yawed about its own center by rot_y (radians).
func add_box(mat: Material, center: Vector3, size: Vector3, rot_y: float = 0.0) -> void:
	var hx := size.x * 0.5
	var hy := size.y * 0.5
	var hz := size.z * 0.5
	var corners_local: Array[Vector3] = [
		Vector3(-hx, -hy, -hz), Vector3(hx, -hy, -hz), Vector3(hx, hy, -hz), Vector3(-hx, hy, -hz),
		Vector3(-hx, -hy, hz), Vector3(hx, -hy, hz), Vector3(hx, hy, hz), Vector3(-hx, hy, hz),
	]
	var c := cos(rot_y); var s := sin(rot_y)
	var pts: Array[Vector3] = []
	for p in corners_local:
		var wx: float = p.x * c + p.z * s
		var wz: float = -p.x * s + p.z * c
		pts.append(center + Vector3(wx, p.y, wz))
	# faces: -Z, +Z, -X, +X, -Y, +Y (CCW outward)
	add_quad(mat, pts[0], pts[3], pts[2], pts[1]) # -Z (front)
	add_quad(mat, pts[5], pts[6], pts[7], pts[4]) # +Z (back)
	add_quad(mat, pts[4], pts[7], pts[3], pts[0]) # -X (left)
	add_quad(mat, pts[1], pts[2], pts[6], pts[5]) # +X (right)
	add_quad(mat, pts[4], pts[0], pts[1], pts[5]) # -Y (bottom)
	add_quad(mat, pts[3], pts[7], pts[6], pts[2]) # +Y (top)

func add_box_minmax(mat: Material, mn: Vector3, mx: Vector3) -> void:
	add_box(mat, (mn + mx) * 0.5, mx - mn, 0.0)

## Box collision helper (call alongside add_box for a matching hull).
func add_box_collision(center: Vector3, size: Vector3, rot_y: float = 0.0) -> void:
	var shape := BoxShape3D.new()
	shape.size = size
	var basis := Basis(Vector3.UP, rot_y)
	_colliders.append({"shape": shape, "xform": Transform3D(basis, center)})

func add_cylinder_collision(center: Vector3, radius: float, height: float) -> void:
	var shape := CylinderShape3D.new()
	shape.radius = radius
	shape.height = height
	_colliders.append({"shape": shape, "xform": Transform3D(Basis.IDENTITY, center)})

## -- cylinders / cones -------------------------------------------------------

## y_axis cylinder from base_center upward `height`, radius can taper (cone if
## radius_top=0). Side quads only unless cap flags set.
func add_cylinder(mat: Material, base_center: Vector3, height: float, radius_bottom: float, radius_top: float, segments: int = 16, cap_bottom: bool = true, cap_top: bool = true, uv_scale: float = 1.0) -> void:
	var bottom := []
	var top := []
	for i in range(segments):
		var a := TAU * float(i) / float(segments)
		var dx := cos(a); var dz := sin(a)
		bottom.append(base_center + Vector3(dx * radius_bottom, 0.0, dz * radius_bottom))
		top.append(base_center + Vector3(dx * radius_top, height, dz * radius_top))
	for i in range(segments):
		var j := (i + 1) % segments
		var u0 := float(i) / float(segments) * TAU * radius_bottom * uv_scale
		var u1 := float(j) / float(segments) * TAU * radius_bottom * uv_scale
		# outward-facing: (bottom_j, bottom_i, top_i, top_j) -- verified by direct
		# cross-product check (see mesh_builder header derivation notes in the
		# landmarks build log); the naive (i,j,j,i) order renders inside-out.
		add_quad_uv(mat, bottom[j], bottom[i], top[i], top[j],
			Vector2(u1, 0.0), Vector2(u0, 0.0), Vector2(u0, height * uv_scale), Vector2(u1, height * uv_scale))
	if cap_bottom:
		var c := base_center
		for i in range(segments):
			var j := (i + 1) % segments
			add_tri(mat, c, bottom[i], bottom[j])
	if cap_top:
		var c2 := base_center + Vector3(0, height, 0)
		for i in range(segments):
			var j := (i + 1) % segments
			add_tri(mat, c2, top[j], top[i])

## Simple pointed cone (spire cap / cupola cap).
func add_cone(mat: Material, base_center: Vector3, height: float, radius: float, segments: int = 16, cap_bottom: bool = true) -> void:
	add_cylinder(mat, base_center, height, radius, 0.001, segments, cap_bottom, false)

## Hemispherical dome (UV-sphere upper half), apex at base_center.y + radius.
func add_dome(mat: Material, base_center: Vector3, radius: float, segments: int = 16, rings: int = 6) -> void:
	for r in range(rings):
		var lat0 := (float(r) / float(rings)) * (PI * 0.5)
		var lat1 := (float(r + 1) / float(rings)) * (PI * 0.5)
		var y0 := sin(lat0) * radius
		var y1 := sin(lat1) * radius
		var rad0 := cos(lat0) * radius
		var rad1 := cos(lat1) * radius
		for i in range(segments):
			var a0 := TAU * float(i) / float(segments)
			var a1 := TAU * float(i + 1) / float(segments)
			var p00 := base_center + Vector3(cos(a0) * rad0, y0, sin(a0) * rad0)
			var p01 := base_center + Vector3(cos(a1) * rad0, y0, sin(a1) * rad0)
			var p10 := base_center + Vector3(cos(a0) * rad1, y1, sin(a0) * rad1)
			var p11 := base_center + Vector3(cos(a1) * rad1, y1, sin(a1) * rad1)
			add_quad(mat, p00, p10, p11, p01)

## -- roof shapes -------------------------------------------------------------

## Simple gable (ridge) roof over a rectangular plan. base_center is at the
## plan's ground-level center (eave height baseline); overhang extends the
## eaves. ridge_along_x=true: ridge runs along local X (gable-end triangular
## walls face +-Z -- a "front gable" when the building's front is -Z).
## ridge_along_x=false: ridge runs along local Z instead (gable ends face
## +-X -- a "side gable" whose long ridge is parallel to the depth axis).
func add_gable_roof(mat: Material, base_center: Vector3, width: float, depth: float, rise: float, overhang: float = 0.3, fascia_mat: Material = null, ridge_along_x: bool = true) -> void:
	var hw := width * 0.5 + overhang
	var hd := depth * 0.5 + overhang
	if not ridge_along_x:
		var tmp := hw; hw = hd; hd = tmp
	var ridge_y := base_center.y + rise
	var eave_y := base_center.y
	var gm := fascia_mat if fascia_mat != null else mat
	var slope_len := Vector2(hd, rise).length()
	var span_uv := hw * 2.0
	if ridge_along_x:
		# ridge along X (from -hw..+hw at z=base.z); slopes fall toward +-Z.
		var rA := Vector3(base_center.x - hw, ridge_y, base_center.z) # ridge, -X end
		var rB := Vector3(base_center.x + hw, ridge_y, base_center.z) # ridge, +X end
		var e00 := Vector3(base_center.x - hw, eave_y, base_center.z - hd) # -Z eave, -X end
		var e01 := Vector3(base_center.x - hw, eave_y, base_center.z + hd) # +Z eave, -X end
		var e10 := Vector3(base_center.x + hw, eave_y, base_center.z - hd) # -Z eave, +X end
		var e11 := Vector3(base_center.x + hw, eave_y, base_center.z + hd) # +Z eave, +X end
		# -Z-facing slope: outward normal (0,+Y,-Z) -> winding (e00,rA,rB,e10)
		add_quad_uv(mat, e00, rA, rB, e10, Vector2(0, 0), Vector2(0, slope_len), Vector2(span_uv, slope_len), Vector2(span_uv, 0))
		# +Z-facing slope: outward normal (0,+Y,+Z) -> winding (e11,rB,rA,e01)
		add_quad_uv(mat, e11, rB, rA, e01, Vector2(0, 0), Vector2(0, slope_len), Vector2(span_uv, slope_len), Vector2(span_uv, 0))
		var apex_neg := Vector3(base_center.x, ridge_y, base_center.z - hd)
		var apex_pos := Vector3(base_center.x, ridge_y, base_center.z + hd)
		add_tri(gm, e10, e00, apex_neg) # -Z gable end, outward normal (0,0,-1)
		add_tri(gm, e01, e11, apex_pos) # +Z gable end, outward normal (0,0,+1)
	else:
		# ridge along Z (from -hw..+hw at x=base.x); slopes fall toward +-X.
		var rNeg := Vector3(base_center.x, ridge_y, base_center.z - hw)
		var rPos := Vector3(base_center.x, ridge_y, base_center.z + hw)
		var e00b := Vector3(base_center.x - hd, eave_y, base_center.z - hw) # -X eave, -Z end
		var e01b := Vector3(base_center.x - hd, eave_y, base_center.z + hw) # -X eave, +Z end
		var e10b := Vector3(base_center.x + hd, eave_y, base_center.z - hw) # +X eave, -Z end
		var e11b := Vector3(base_center.x + hd, eave_y, base_center.z + hw) # +X eave, +Z end
		# -X-facing slope: outward normal (-X,+Y,0) -> winding (e00b,e01b,rPos,rNeg)
		add_quad_uv(mat, e00b, e01b, rPos, rNeg, Vector2(0, 0), Vector2(span_uv, 0), Vector2(span_uv, slope_len), Vector2(0, slope_len))
		# +X-facing slope: outward normal (+X,+Y,0) -> winding (e11b,e10b,rNeg,rPos)
		add_quad_uv(mat, e11b, e10b, rNeg, rPos, Vector2(0, 0), Vector2(span_uv, 0), Vector2(span_uv, slope_len), Vector2(0, slope_len))
		var apex_neg2 := Vector3(base_center.x, ridge_y, base_center.z - hw)
		var apex_pos2 := Vector3(base_center.x, ridge_y, base_center.z + hw)
		add_tri(gm, e10b, e00b, apex_neg2) # -Z gable end, outward normal (0,0,-1)
		add_tri(gm, e01b, e11b, apex_pos2) # +Z gable end, outward normal (0,0,+1)

## Hip roof over a rectangular plan (all 4 sides slope). ridge is a short
## segment along X centered on the plan (set ridge_len=0 for a full pyramid).
func add_hip_roof(mat: Material, base_center: Vector3, width: float, depth: float, rise: float, ridge_len: float, overhang: float = 0.3) -> void:
	var hw := width * 0.5 + overhang
	var hd := depth * 0.5 + overhang
	var hr := ridge_len * 0.5
	var ridge_y := base_center.y + rise
	var e00 := Vector3(base_center.x - hw, base_center.y, base_center.z - hd)
	var e01 := Vector3(base_center.x - hw, base_center.y, base_center.z + hd)
	var e10 := Vector3(base_center.x + hw, base_center.y, base_center.z - hd)
	var e11 := Vector3(base_center.x + hw, base_center.y, base_center.z + hd)
	var rA := Vector3(base_center.x - hr, ridge_y, base_center.z)
	var rB := Vector3(base_center.x + hr, ridge_y, base_center.z)
	if ridge_len <= 0.001:
		add_tri(mat, e00, e10, rA)
		add_tri(mat, e10, e11, rA)
		add_tri(mat, e11, e01, rA)
		add_tri(mat, e01, e00, rA)
	else:
		add_quad_uv(mat, e00, e10, rB, rA, Vector2(0, 0), Vector2(width, 0), Vector2(width, 4), Vector2(0, 4))
		add_quad_uv(mat, e11, e01, rA, rB, Vector2(0, 0), Vector2(width, 0), Vector2(width, 4), Vector2(0, 4))
		add_tri(mat, e10, e11, rB)
		add_tri(mat, e01, e00, rA)

## Concave mansard band: a steep truncated-pyramid wall (lower_height tall,
## from plan width/depth down at base down to a smaller inset top), capped by
## a flat deck. Ridge/eave not modelled separately -- dormers poke through
## via separate add_box calls from the landmark generator.
func add_mansard(mat: Material, base_center: Vector3, width: float, depth: float, lower_height: float, inset: float) -> void:
	var hw := width * 0.5
	var hd := depth * 0.5
	var hw2 := hw - inset
	var hd2 := hd - inset
	var y0 := base_center.y
	var y1 := base_center.y + lower_height
	var b := [Vector3(base_center.x - hw, y0, base_center.z - hd), Vector3(base_center.x + hw, y0, base_center.z - hd),
		Vector3(base_center.x + hw, y0, base_center.z + hd), Vector3(base_center.x - hw, y0, base_center.z + hd)]
	var t := [Vector3(base_center.x - hw2, y1, base_center.z - hd2), Vector3(base_center.x + hw2, y1, base_center.z - hd2),
		Vector3(base_center.x + hw2, y1, base_center.z + hd2), Vector3(base_center.x - hw2, y1, base_center.z + hd2)]
	for i in range(4):
		var j := (i + 1) % 4
		add_quad_uv(mat, b[j], b[i], t[i], t[j], Vector2(0, 0), Vector2(4, 0), Vector2(4, lower_height), Vector2(0, lower_height))
	# flat deck cap (facing +Y)
	add_quad(mat, t[0], t[3], t[2], t[1])

## -- arch (torus-segment tube) -----------------------------------------------

## Arch tube spanning local X from -half_span..+half_span, apex up +Y, lying
## in the local X-Y plane, thickness along Z. angle_deg_start/end measured
## from +X axis (0=east/right pier springing point, 180=west/left pier).
func add_arch_tube(mat: Material, center: Vector3, half_span: float, tube_radius: float, angle_start_deg: float = 180.0, angle_end_deg: float = 0.0, major_segments: int = 24, minor_segments: int = 10) -> void:
	var major_radius := half_span
	var rings: Array[Array] = []
	for i in range(major_segments + 1):
		var t := float(i) / float(major_segments)
		var ang := deg_to_rad(lerpf(angle_start_deg, angle_end_deg, t))
		var axis_x := cos(ang) * major_radius
		var axis_y := sin(ang) * major_radius
		# radial (in-plane) direction, used to offset the tube cross-section
		var normal2 := Vector2(cos(ang), sin(ang)).normalized()
		var ring: Array[Vector3] = []
		for k in range(minor_segments):
			var b := TAU * float(k) / float(minor_segments)
			# offset in the plane perpendicular to tangent: combination of radial (in XY plane) and Z
			var off := normal2 * (cos(b) * tube_radius)
			var offz := sin(b) * tube_radius
			ring.append(center + Vector3(axis_x + off.x, axis_y + off.y, offz))
		rings.append(ring)
	for i in range(major_segments):
		for k in range(minor_segments):
			var k2 := (k + 1) % minor_segments
			var ring_i: Array = rings[i]
			var ring_i1: Array = rings[i + 1]
			var a0: Vector3 = ring_i[k]; var a1: Vector3 = ring_i[k2]
			var b0: Vector3 = ring_i1[k]; var b1: Vector3 = ring_i1[k2]
			# Emitted both-winding (belt-and-suspenders): a swept-tube's outward
			# side flips depending on which side of the major-radius circle a
			# given minor-ring point sits on, which isn't worth hand-deriving
			# for a handful of tris -- doubling this one small shape is cheap.
			add_quad(mat, a0, a1, b1, b0)
			add_quad(mat, a0, b0, b1, a1)

## -- finalize -----------------------------------------------------------------

func finalize() -> ArrayMesh:
	var mesh := ArrayMesh.new()
	for mat in _surfaces.keys():
		var st: SurfaceTool = _surfaces[mat]
		st.index()
		st.set_material(mat)
		st.commit(mesh)
	return mesh

func build_collision_body(name: String) -> StaticBody3D:
	var body := StaticBody3D.new()
	body.name = name
	for c in _colliders:
		var cs := CollisionShape3D.new()
		cs.shape = c["shape"]
		cs.transform = c["xform"]
		body.add_child(cs)
	return body
