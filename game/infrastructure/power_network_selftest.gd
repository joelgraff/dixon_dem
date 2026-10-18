extends SceneTree
## Run with: godot --headless --path game --script res://infrastructure/power_network_selftest.gd

const PowerNetworkScript = preload("res://infrastructure/power_network.gd")

func _initialize() -> void:
	var network = PowerNetworkScript.new()
	var sagged: Vector3 = network._sagged_point(Vector3.ZERO, Vector3(40.0, 0.0, 0.0), 0.5, 1.1)
	if not is_equal_approx(sagged.y, -1.1):
		push_error("wire span midpoint does not have the configured sag")
		network.free()
		quit(1)
		return

	var geometry := SurfaceTool.new()
	geometry.begin(Mesh.PRIMITIVE_TRIANGLES)
	network._add_utility_support(geometry, Vector3.ZERO, "tower")
	var supports := geometry.commit()
	if supports == null or supports.get_surface_count() == 0:
		push_error("utility pole geometry was not generated")
		network.free()
		quit(1)
		return

	root.add_child(network)
	await process_frame
	if network.get_node_or_null("UtilitySupports") == null:
		push_error("power-network scene did not build support meshes from power.json")
		network.free()
		quit(1)
		return
	if network.get_node_or_null("OverheadConductors") == null:
		push_error("power-network scene did not build conductor meshes from power.json")
		network.free()
		quit(1)
		return
	root.remove_child(network)
	network.free()
	print("POWER NETWORK SELFTEST OK")
	quit(0)
