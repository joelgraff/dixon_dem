extends SceneTree
## Small transform/mesh regression test; run with:
## godot --headless --path game --script res://vegetation/vegetation_selftest.gd

const VegetationScript = preload("res://vegetation/vegetation.gd")
const VegTreeBuilder = preload("res://vegetation/tree_builder.gd")

func _fail(msg: String) -> void:
	push_error(msg)
	quit(1)

func _initialize() -> void:
	var vegetation: Node3D = VegetationScript.new()
	# A unit-height mesh with a 0.5 crown radius fitted to a 20 m tree with an
	# 8 m crown: horizontal scale 16 puts the crown edge at 8 m.
	var near_basis: Basis = vegetation._tree_basis(0.0, 20.0, 8.0, 0.5)
	var wide_basis: Basis = vegetation._tree_basis(0.0, 20.0, 10.0, 0.5)
	var tall_basis: Basis = vegetation._tree_basis(0.0, 24.0, 8.0, 0.5)
	var squashed_basis: Basis = vegetation._tree_basis(0.0, 20.0, 1.0, 0.5)
	vegetation.free()

	if not is_equal_approx(near_basis.x.length() * 0.5, 8.0):
		return _fail("tree crown radius was not applied to near LOD")
	if not is_equal_approx(near_basis.y.length(), 20.0):
		return _fail("tree height was not applied independently")
	if not is_equal_approx(wide_basis.x.length() * 0.5, 10.0):
		return _fail("changing crown radius did not change tree width")
	if not is_equal_approx(tall_basis.x.length(), near_basis.x.length()):
		return _fail("changing tree height also changed crown width")
	if not is_equal_approx(squashed_basis.x.length(), 20.0 / VegetationScript.MAX_CROWN_STRETCH):
		return _fail("crown aspect stretch was not limited")

	# Generated tree meshes are normalised to unit height and carry crown metadata.
	var mesh: ArrayMesh = VegTreeBuilder.build_deciduous("round_broad", 7, Color.GREEN, Color.RED)
	var top := mesh.get_aabb().end.y
	if absf(top - 1.0) > 0.01:
		return _fail("deciduous mesh top is %.3f, expected 1.0" % top)
	var crown_r: float = mesh.get_meta("crown_r", -1.0)
	if crown_r < 0.2 or crown_r > 0.8:
		return _fail("implausible crown_r %.3f" % crown_r)

	print("VEGETATION SELFTEST OK")
	quit(0)
