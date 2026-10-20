"""Quality gates for the authoritative transportation layout."""
import math
import sys
import tempfile
import unittest

import numpy as np
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_road_plan as roads
import transport_layout as layout
from PIL import Image
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union


class Flat:
    @staticmethod
    def sample(_x, _z):
        return 0.0

    @staticmethod
    def normal(_x, _z):
        return [0.0, 1.0, 0.0]

    @staticmethod
    def sample_many(x, _z):
        return np.zeros(len(x))

    @staticmethod
    def normal_many(x, _z):
        return np.tile([0.0, 1.0, 0.0], (len(x), 1))


def straight_plan(downtown=False):
    return SimpleNamespace(full_centerline=[(0.0, 0.0), (80.0, 0.0)],
                           half_w=3.0, has_curb=True, downtown=downtown)


EMPTY_OVERRIDES = {"version": 1, "junctions": [], "lots": [], "exclude_paving": []}


class TransportLayoutTests(unittest.TestCase):
    def test_parkway_and_sidewalk_are_flush_with_curb_and_do_not_overlap(self):
        surfaces, report = layout.build_layout(
            [straight_plan()], {}, Polygon(), Polygon(), EMPTY_OVERRIDES)
        self.assertEqual(report["invalid_surfaces"], 0)
        for name, z in (("curb", 3.06), ("parkway", 4.0), ("sidewalk", 5.8)):
            self.assertTrue(surfaces[name].contains(Point(40, z)), name)
        meshes = {}
        layout.emit_layout(surfaces, Flat(), meshes)
        grass = meshes["grass_lawn"].verts
        parkway_vertices = [v for v in grass if 10 < v[0] < 70 and
                            3.12 - 1e-6 <= abs(v[2]) <= 5.12 + 1e-6]
        self.assertTrue(parkway_vertices)
        self.assertTrue(all(abs(v[1] - layout.TOP_BIAS) < 1e-8 for v in parkway_vertices))
        self.assertAlmostEqual(layout.TOP_BIAS - layout.ROAD_BIAS, 0.1524)
        gutter = surfaces["gutter"].intersection(LineString([(40, 0), (40, 8)]))
        self.assertAlmostEqual(gutter.length, 0.3048)
        for mesh in meshes.values():
            for i in range(0, len(mesh.indices), 3):
                a, b, c = (mesh.verts[index] for index in mesh.indices[i:i + 3])
                if a[1] == b[1] == c[1]:
                    upward = (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2])
                    self.assertLessEqual(upward, 1e-8)

    def test_lot_noise_is_rejected_and_small_holes_are_filled(self):
        lot = Polygon([(0, 0), (30, 0), (30, 30), (0, 30)],
                      [[(10, 10), (12, 10), (12, 12), (10, 12)]])
        noise = box(40, 0, 70, 1).union(box(80, 0, 85, 5))
        accepted, rejected = layout.clean_lots(lot.union(noise), Polygon(), EMPTY_OVERRIDES)
        self.assertTrue(accepted.contains(Point(11, 11)))
        self.assertFalse(accepted.intersects(noise))
        self.assertEqual(len(list(layout.polygon_parts(accepted))), 1)
        self.assertEqual(len(rejected), 2)

    def test_lots_clip_against_finished_infrastructure_and_keep_large_islands(self):
        lot = Polygon([(0, 0), (40, 0), (40, 40), (0, 40)],
                      [[(15, 15), (25, 15), (25, 25), (15, 25)]])
        protected = box(0, 0, 5, 40)
        accepted, _ = layout.clean_lots(lot, protected, EMPTY_OVERRIDES)
        self.assertLess(accepted.intersection(protected).area, 1e-8)
        self.assertFalse(accepted.contains(Point(20, 20)))

    def test_automatic_lot_boundaries_do_not_follow_classification_notches(self):
        noisy = Polygon([(0, 0), (30, 0), (30, 10), (28, 10),
                         (28, 12), (30, 12), (30, 30), (0, 30)])
        accepted, _ = layout.clean_lots(noisy, Polygon(), EMPTY_OVERRIDES)
        self.assertEqual(len(accepted.exterior.coords), 5)
        self.assertTrue(accepted.contains(Point(29, 11)))

    def test_explicit_lot_cannot_overlap_road_and_exclusions_remove_candidates(self):
        override = {**EMPTY_OVERRIDES, "lots": [
            {"id": "bad", "polygon": [(0, 0), (20, 0), (20, 20), (0, 20)]}]}
        with self.assertRaisesRegex(ValueError, "overlap protected"):
            layout.clean_lots(Polygon(), box(0, 0, 5, 5), override)
        override = {**EMPTY_OVERRIDES, "exclude_paving": [
            {"id": "lawn", "polygon": [(0, 0), (20, 0), (20, 20), (0, 20)]}]}
        accepted, _ = layout.clean_lots(box(0, 0, 20, 20), Polygon(), override)
        self.assertTrue(accepted.is_empty)

    def test_constrained_mesh_covers_holes_exactly_and_bounds_triangle_spans(self):
        surface = Polygon([(0, 0), (30, 0), (30, 30), (0, 30)],
                          [[(8, 8), (20, 8), (20, 20), (8, 20)]])
        triangles = list(layout.surface_triangles(surface))
        combined = unary_union([Polygon(triangle) for triangle in triangles])
        self.assertLess(combined.symmetric_difference(surface).area, 1e-7)
        self.assertTrue(all(math.dist(a, b) <= layout.MESH_CELL_M * math.sqrt(2) + 1e-8
                            for triangle in triangles for a in triangle for b in triangle))

    def test_mask_does_not_erase_grass_in_block_interiors(self):
        image = Image.new("RGB", (20, 20), (200, 0, 0))
        road = box(0, 0, 19, 19).difference(box(4, 4, 15, 15))
        layout.paint_geometry(image, road, (0, 0, 0), lambda x, z: (x, z))
        self.assertEqual(image.getpixel((10, 10)), (200, 0, 0))
        self.assertEqual(image.getpixel((2, 2)), (0, 0, 0))

    def test_quality_gate_rejects_invalid_and_overlapping_surfaces(self):
        invalid = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])
        with self.assertRaisesRegex(ValueError, "invalid"):
            layout.validate_layout({"asphalt": invalid, "gutter": Polygon()})
        with self.assertRaisesRegex(ValueError, "overlapping"):
            layout.validate_layout({"asphalt": box(0, 0, 3, 3), "gutter": Polygon(),
                                    "sidewalk": box(1, 1, 4, 4)})

    def test_actual_river_and_first_galena_layouts_are_valid_and_connected(self):
        source = roads.load_json("roads.json")
        ways = roads.split_at_junctions(source["ways"],
                                       {j["node_id"] for j in source["junction_nodes"]})
        ways = [w for w in ways if w["tags"].get("highway") in roads.DRIVABLE
                and not w["tags"].get("bridge")]
        nodes = roads.build_graph(ways)
        for node_id in (235322239, 235351970):
            with self.subTest(node=node_id):
                node = nodes[node_id]
                plans = roads.plan_drivable_ways([leg["way"] for leg in node.legs], nodes)
                overrides = layout.read_overrides() if node_id == 235322239 else EMPTY_OVERRIDES
                surfaces, report = layout.build_layout(
                    plans, {node_id: node}, Polygon(), Polygon(), overrides)
                self.assertEqual(report["unintended_overlap_m2"], 0)
                self.assertEqual(len(list(layout.polygon_parts(surfaces["asphalt"]))), 1)
                self.assertTrue(surfaces["asphalt"].contains(Point(node.x, node.z)))
                self.assertTrue(all(p.is_valid for p in layout.polygon_parts(surfaces["sidewalk"])))
                for plan in plans:
                    line = LineString(plan.full_centerline)
                    self.assertLess(line.difference(surfaces["asphalt"]).length, 1e-5)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "layout.json"
                    layout.save_layout(surfaces, report, path)
                    loaded = layout.load_layout(path)
                    self.assertLess(loaded["asphalt"].symmetric_difference(surfaces["asphalt"]).area, 1e-8)

    def test_citywide_partition_does_not_resnap_edges_into_neighboring_surfaces(self):
        source = roads.load_json("roads.json")
        ways = roads.split_at_junctions(roads.clip_ways_to_bounds(source["ways"]),
                                       {j["node_id"] for j in source["junction_nodes"]})
        drivable = [w for w in ways if w["tags"].get("highway") in roads.DRIVABLE
                    and not w["tags"].get("bridge")]
        nodes = roads.build_graph(drivable)
        plans = roads.plan_drivable_ways(drivable, nodes)
        surfaces, report = layout.build_layout(
            plans, nodes, Polygon(), Polygon(), layout.read_overrides(), ways)
        self.assertEqual(report["unintended_overlap_m2"], 0.0)
        self.assertEqual(layout.validate_layout(surfaces)["invalid_surfaces"], 0)

    def test_building_conflicts_are_counted_by_source_before_the_walk_is_cut(self):
        groups = {"carriageway": box(0, 0, 10, 100), "roadside": box(10, 0, 13, 100)}
        houses = [box(11, 10, 20, 20),   # front 2 m into the walk
                  box(8, 40, 20, 50),    # front on the pavement and across the walk
                  box(14, 70, 20, 80)]   # behind the back of walk
        report = layout.building_conflicts(groups, (houses, [("1", "ms"), ("2", "osm"), ("3", "ms")]))
        self.assertEqual(report["by_source"]["ms"]["roadside"], {"count": 1, "area_m2": 20.0})
        self.assertEqual(report["by_source"]["ms"]["carriageway"]["count"], 0)
        self.assertEqual(report["by_source"]["osm"]["carriageway"], {"count": 1, "area_m2": 20.0})
        self.assertEqual(report["by_source"]["osm"]["roadside"]["area_m2"], 30.0)
        self.assertNotIn("3", {row["id"] for rows in report["largest"].values() for row in rows})
        self.assertEqual([row["id"] for row in report["largest"]["carriageway"]], ["2"])

    def _yielded(self, plan, houses):
        ids = [(str(i), "ms") for i in range(len(houses))]
        return layout.build_layout([plan], {}, Polygon(), unary_union(houses), EMPTY_OVERRIDES,
                                   buildings=(houses, ids))

    def test_a_service_drive_stops_at_every_footprint(self):
        drive = SimpleNamespace(full_centerline=[(0.0, 0.0), (60.0, 0.0)], half_w=2.0, has_curb=False,
                                downtown=False, way={"id": 7})
        garage = box(20, -5, 30, 5)
        surfaces, report = self._yielded(drive, [garage])
        self.assertLess(surfaces["asphalt"].intersection(garage).area, 1e-6)
        self.assertTrue(surfaces["asphalt"].contains(Point(10, 0)) and surfaces["asphalt"].contains(Point(40, 0)))
        (row,) = report["building_yield"]["service"]
        self.assertEqual((row["id"], row["ways"], row["area_m2"]), ("0", ["7"], 40.0))
        self.assertEqual(report["building_conflicts"]["by_source"], {})

    def test_a_curb_runs_round_a_shallow_front_and_a_deep_bite_is_left(self):
        front = box(30, 4.2, 40, 15)      # 0.9 m into a 10 m street (5.12 m to the back of curb)
        corner = box(50, 3.0, 53, 9)      # a 6 m2 corner, 2.1 m in
        deep = box(65, 1.0, 75, 15)       # 4.1 m in: the footprint or the street is wrong
        surfaces, report = self._yielded(SimpleNamespace(full_centerline=[(0.0, 0.0), (90.0, 0.0)], half_w=5.0,
                                                         has_curb=True, downtown=False), [front, corner, deep])
        yielded = report["building_yield"]
        self.assertEqual(sorted(r["id"] for r in yielded["curb_trims"]), ["0", "1"])
        self.assertEqual([r["id"] for r in yielded["left_for_review"]], ["2"])
        for house in (front, corner):
            self.assertLess(surfaces["asphalt"].intersection(house).area, 1e-6)
            self.assertLess(surfaces["curb"].intersection(house).area, 1e-6)
        self.assertTrue(surfaces["curb"].contains(Point(35, 4.2 - layout.CURB_WIDTH / 2)))   # at the face
        self.assertAlmostEqual(surfaces["asphalt"].intersection(deep).area, 10 * 4.0, places=3)
        self.assertEqual([r["id"] for r in report["building_conflicts"]["largest"]["carriageway"]], ["2"])

    def test_every_building_footprint_is_a_valid_obstacle(self):
        polygons, ids = roads.building_obstacles()
        self.assertEqual(len(polygons), len(ids))
        self.assertTrue({"osm", "ms"} <= {source for _, source in ids})
        self.assertTrue(all(p.is_valid and p.area >= 1.0 for p in polygons))
        self.assertNotIn("800002411", {bid for bid, _ in ids})   # MS false detection on the river


if __name__ == "__main__":
    unittest.main()
