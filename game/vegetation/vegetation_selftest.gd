extends SceneTree
## Small transform regression test; run with:
## godot --headless --path game --script res://vegetation/vegetation_selftest.gd

const VegetationScript = preload("res://vegetation/vegetation.gd")

func _initialize() -> void:
	var vegetation: Node3D = VegetationScript.new()
	var near_transform: Transform3D = vegetation._tree_xform(0.0, 0.0, 0.0, 0.0, 20.0, 8.0)
	var wide_transform: Transform3D = vegetation._tree_xform(0.0, 0.0, 0.0, 0.0, 20.0, 10.0)
	var tall_transform: Transform3D = vegetation._tree_xform(0.0, 0.0, 0.0, 0.0, 24.0, 8.0)
	var billboard_transform: Transform3D = vegetation._tree_xform(
		0.0, 0.0, 0.0, 0.0, 20.0, 8.0, true)
	vegetation.free()

	if not is_equal_approx(near_transform.basis.x.length(), 8.0):
		push_error("tree crown radius was not applied to near LOD")
		quit(1)
		return
	if not is_equal_approx(near_transform.basis.y.length(), 20.0):
		push_error("tree height was not applied independently")
		quit(1)
		return
	if not is_equal_approx(wide_transform.basis.x.length(), 10.0):
		push_error("changing crown radius did not change tree width")
		quit(1)
		return
	if not is_equal_approx(tall_transform.basis.x.length(), 8.0):
		push_error("changing tree height also changed crown width")
		quit(1)
		return
	if not is_equal_approx(billboard_transform.basis.x.length(), 16.0):
		push_error("far billboard width does not match requested crown diameter")
		quit(1)
		return

	print("VEGETATION SELFTEST OK")
	quit(0)
