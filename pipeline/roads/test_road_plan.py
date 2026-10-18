"""Focused regression checks for straight-road curb/gutter geometry.

Run with: ../../.venv/bin/python test_road_plan.py
"""
import sys
import unittest
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_road_plan import (  # noqa: E402
    AERIAL_PAVED_SIMPLIFY_M,
    CURB_HEIGHT,
    CURB_TOP_Y_BIAS,
    GUTTER_WIDTH,
    ROAD_SAMPLE_SPACING,
    ROAD_SMOOTH_ITERS,
    ROAD_Y_BIAS,
    asphalt_material_for,
    angle_of,
    build_way_surfaces,
    build_junction_geometry,
    build_graph,
    plan_drivable_ways,
    load_json,
    split_at_junctions,
    prepare_junctions,
    DRIVABLE,
    dissolve_aerial_paved_quads,
    build_loop,
    build_corner_arcs,
    curb_return_arc,
    _in_junction_polygon,
    junction_polygon_grid,
    junction_corner_segment_counts,
    outward_dir,
    ribbon_cells_outside_junctions,
    ribbon_triangles_outside_junctions,
)
from common_roads import resample_polyline  # noqa: E402


class FlatHeightmap:
    @staticmethod
    def sample(_x, _z):
        return 0.0

    @staticmethod
    def normal(_x, _z):
        return [0.0, 1.0, 0.0]


class StraightRoadPlan:
    way = {"tags": {"highway": "residential"}}
    has_curb = True
    has_sidewalk = False
    rings = {
        "edge_L": [(0.0, 3.0), (10.0, 3.0)],
        "edge_R": [(0.0, -3.0), (10.0, -3.0)],
        "curb_out_L": [(0.0, 3.12), (10.0, 3.12)],
        "curb_out_R": [(0.0, -3.12), (10.0, -3.12)],
        "gutter_out_L": [(0.0, 3.0 - GUTTER_WIDTH), (10.0, 3.0 - GUTTER_WIDTH)],
        "gutter_out_R": [(0.0, -3.0 + GUTTER_WIDTH), (10.0, -3.0 + GUTTER_WIDTH)],
    }


class IntersectionRoadPlan:
    has_curb = True
    has_sidewalk = True

    def __init__(self, ray, half_width, end):
        self.half_w = half_width
        travel = ray if end == "start" else (-ray[0], -ray[1])
        points = [(ray[0] * 24.0, ray[1] * 24.0),
                  (ray[0] * 44.0, ray[1] * 44.0)]
        if end == "end":
            points.reverse()
        self.centerline = points

        offsets = {
            "edge": half_width,
            "curb_out": half_width + 0.12,
            "gutter_out": half_width - GUTTER_WIDTH,
            "sw_in": half_width + 0.12 + 2.0,
            "sw_out": half_width + 0.12 + 2.0 + 1.7,
        }
        normal = (-travel[1], travel[0])
        self.rings = {}
        for key, offset in offsets.items():
            left = [(x + normal[0] * offset, z + normal[1] * offset)
                    for x, z in self.centerline]
            right = [(x - normal[0] * offset, z - normal[1] * offset)
                     for x, z in self.centerline]
            self.rings[key + "_L"] = left
            self.rings[key + "_R"] = right


class RoadPlanTests(unittest.TestCase):
    def test_curb_and_gutter_use_standard_dimensions(self):
        self.assertAlmostEqual(CURB_HEIGHT, 0.1524)
        self.assertAlmostEqual(GUTTER_WIDTH, 0.3048)
        self.assertAlmostEqual(CURB_TOP_Y_BIAS - ROAD_Y_BIAS, CURB_HEIGHT)

        meshes = {}
        build_way_surfaces([StraightRoadPlan()], FlatHeightmap(), meshes)
        curb_heights = [vertex[1] for vertex in meshes["curb_concrete"].verts]
        self.assertIn(CURB_TOP_Y_BIAS, curb_heights)
        self.assertIn(ROAD_Y_BIAS, curb_heights)

    def test_road_centerlines_are_smooth_and_densely_sampled(self):
        self.assertEqual(ROAD_SAMPLE_SPACING, 2.5)
        self.assertEqual(ROAD_SMOOTH_ITERS, 2)
        source = [(0.0, 0.0), (5.0, 1.0), (10.0, -1.0), (15.0, 0.0)]
        lightly_smoothed = resample_polyline(source, spacing=ROAD_SAMPLE_SPACING, smooth_iters=1)
        road_plan_line = resample_polyline(
            source, spacing=ROAD_SAMPLE_SPACING, smooth_iters=ROAD_SMOOTH_ITERS,
        )

        self.assertEqual(road_plan_line[0], source[0])
        self.assertEqual(road_plan_line[-1], source[-1])
        def heading_variation(points):
            headings = [
                math.atan2(b[1] - a[1], b[0] - a[0])
                for a, b in zip(points, points[1:])
            ]
            return sum(
                abs((b - a + math.pi) % (2.0 * math.pi) - math.pi)
                for a, b in zip(headings, headings[1:])
            )

        self.assertLess(heading_variation(road_plan_line),
                        heading_variation(lightly_smoothed))

    def test_aerial_paving_quads_are_dissolved_and_simplified(self):
        quads = [
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            [(1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0)],
            [(2.0, 0.0), (3.0, 0.0), (3.0, 1.0), (2.0, 1.0)],
        ]
        polygons = dissolve_aerial_paved_quads(quads)

        self.assertEqual(AERIAL_PAVED_SIMPLIFY_M, 2.0)
        self.assertEqual(len(polygons), 1)
        self.assertAlmostEqual(polygons[0].area, 3.0)
        self.assertEqual(len(polygons[0].exterior.coords), 5)

    def test_aerial_paving_simplification_removes_pixel_scale_teeth(self):
        from shapely.geometry import Polygon
        from shapely.ops import unary_union

        quads = []
        for row in range(12):
            y0 = row * 0.5
            y1 = y0 + 0.5
            right = 4.0 if row % 2 else 4.5
            quads.append([(0.0, y0), (right, y0), (right, y1), (0.0, y1)])
        original = unary_union([Polygon(quad) for quad in quads])
        simplified = dissolve_aerial_paved_quads(quads)[0]

        self.assertLess(len(simplified.exterior.coords), len(original.exterior.coords))
        self.assertAlmostEqual(simplified.area, original.area, delta=3.0)

    def test_road_classes_share_one_asphalt_material(self):
        classes = ("residential", "service", "track", "primary", "secondary", "tertiary")
        materials = {
            asphalt_material_for({"tags": {"highway": highway}})
            for highway in classes
        }
        self.assertEqual(materials, {"asphalt_road_plowed"})

    def test_curb_return_arc_is_smooth_and_tangent_at_both_ends(self):
        start = (0.0, 2.0)
        end = (2.0, 0.0)
        arc = curb_return_arc(start, (1.0, 0.0), end, (0.0, -1.0), (0.0, 0.0))

        self.assertGreater(len(arc), 4)
        self.assertEqual(arc[0], start)
        self.assertEqual(arc[-1], end)
        segment_lengths = [
            ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            for a, b in zip(arc, arc[1:])
        ]
        self.assertLessEqual(max(segment_lengths), 4.0)
        first_direction = (arc[1][0] - start[0], arc[1][1] - start[1])
        last_direction = (end[0] - arc[-2][0], end[1] - arc[-2][1])
        self.assertGreater(first_direction[0], abs(first_direction[1]) * 5.0)
        self.assertGreater(-last_direction[1], abs(last_direction[0]) * 5.0)

    def test_junction_rings_share_corner_tessellation(self):
        legs = [
            (IntersectionRoadPlan((1.0, 0.0), 3.25, "start"), "start"),
            (IntersectionRoadPlan((0.0, 1.0), 13.0, "start"), "start"),
            (IntersectionRoadPlan((-1.0, 0.0), 3.25, "end"), "end"),
            (IntersectionRoadPlan((0.0, -1.0), 13.0, "end"), "end"),
        ]
        legs.sort(key=lambda item: angle_of(outward_dir(item[0], item[1])))
        segments = junction_corner_segment_counts(legs)

        loops = [
            build_loop(legs, ring_key, (0.0, 0.0), segments)
            for ring_key in ("edge", "curb_out", "gutter_out", "sw_in", "sw_out")
        ]
        self.assertTrue(all(loop is not None for loop in loops))
        self.assertEqual(len({len(loop) for loop in loops}), 1)

        corner_arcs = [
            build_corner_arcs(legs, ring_key, (0.0, 0.0), segments)
            for ring_key in ("edge", "curb_out", "gutter_out", "sw_in", "sw_out")
        ]
        self.assertTrue(all(arcs is not None for arcs in corner_arcs))
        for arcs in corner_arcs:
            self.assertEqual(
                [len(arc) for arc in arcs],
                [segment_count + 1 for segment_count in segments],
            )

        polygon_grid = junction_polygon_grid([{"asphalt_loop": loops[0]}])
        self.assertTrue(_in_junction_polygon(0.0, 0.0, polygon_grid))
        self.assertFalse(_in_junction_polygon(40.0, 40.0, polygon_grid))

        clipped_triangles = []
        for inner_arc, outer_arc in zip(corner_arcs[3], corner_arcs[4]):
            for i in range(len(inner_arc) - 1):
                clipped_triangles.extend(ribbon_triangles_outside_junctions(
                    inner_arc[i], inner_arc[i + 1],
                    outer_arc[i], outer_arc[i + 1], polygon_grid,
                ))
        self.assertTrue(clipped_triangles)
        for triangle in clipped_triangles:
            self.assertEqual(len(triangle), 3)
            centroid = (
                sum(point[0] for point in triangle) / 3.0,
                sum(point[1] for point in triangle) / 3.0,
            )
            self.assertFalse(_in_junction_polygon(*centroid, polygon_grid))

        kept_cells = clipped_quads = 0
        for inner_arc, outer_arc in zip(corner_arcs[3], corner_arcs[4]):
            for i in range(len(inner_arc) - 1):
                inner = inner_arc[i:i + 2]
                outer = outer_arc[i:i + 2]
                cells = ribbon_cells_outside_junctions(
                    inner[0], inner[1], outer[0], outer[1], polygon_grid,
                )
                if cells != [(inner, outer)]:
                    clipped_quads += 1
                kept_cells += len(cells)
                for cell_in, cell_out in cells:
                    for t_step in range(5):
                        t = t_step / 4
                        for across_step in range(5):
                            across = across_step / 4
                            x0 = cell_in[0][0] + (cell_in[1][0] - cell_in[0][0]) * t
                            z0 = cell_in[0][1] + (cell_in[1][1] - cell_in[0][1]) * t
                            x1 = cell_out[0][0] + (cell_out[1][0] - cell_out[0][0]) * t
                            z1 = cell_out[0][1] + (cell_out[1][1] - cell_out[0][1]) * t
                            self.assertFalse(_in_junction_polygon(
                                x0 + (x1 - x0) * across,
                                z0 + (z1 - z0) * across,
                                polygon_grid,
                            ))
        self.assertGreater(kept_cells, 0)
        self.assertEqual(clipped_quads, 0)

    def test_shared_junction_mouth_does_not_notch_curb(self):
        grid = junction_polygon_grid([{
            "asphalt_loop": [(0.0, -5.0), (5.0, -5.0), (5.0, 5.0), (0.0, 5.0)],
        }])
        inner = [(5.0, 3.0), (10.0, 3.0)]
        outer = [(5.0, 3.12), (10.0, 3.12)]
        self.assertEqual(ribbon_cells_outside_junctions(*inner, *outer, grid),
                         [(inner, outer)])
        self.assertEqual(ribbon_cells_outside_junctions(*inner, *inner, grid),
                         [(inner, inner)])

    def test_crossing_trims_curb_at_exact_station(self):
        grid = junction_polygon_grid([{
            "asphalt_loop": [(4.2, -5.0), (5.3, -5.0), (5.3, 5.0), (4.2, 5.0)],
        }])
        cells = ribbon_cells_outside_junctions(
            (0.0, 3.0), (10.0, 3.0), (0.0, 3.12), (10.0, 3.12), grid,
        )
        self.assertEqual(len(cells), 2)
        self.assertAlmostEqual(cells[0][0][1][0], 4.2, places=5)
        self.assertAlmostEqual(cells[1][0][0][0], 5.3, places=5)

    def test_folded_short_run_is_repaired_before_polygon_clipping(self):
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        from contextlib import redirect_stdout
        from io import StringIO

        grid = junction_polygon_grid([{
            "asphalt_loop": [(10.0, 10.0), (11.0, 10.0), (11.0, 11.0), (10.0, 11.0)],
        }])
        with redirect_stdout(StringIO()) as log:
            triangles = ribbon_triangles_outside_junctions(
                (0.0, 0.0), (2.0, 2.0), (2.0, 0.0), (0.0, 2.0), grid,
            )
        self.assertIn("repairing folded roadside surface", log.getvalue())
        surface = unary_union([Polygon(tri) for tri in triangles])
        self.assertTrue(surface.is_valid)
        self.assertAlmostEqual(surface.area, 2.0)
        self.assertTrue(ribbon_cells_outside_junctions(
            (0.0, 0.0), (2.0, 2.0), (2.0, 0.0), (0.0, 2.0), grid,
        ))

    def test_first_and_galena_sidewalk_returns_are_watertight(self):
        from shapely.geometry import Polygon
        from shapely.ops import unary_union

        roads = load_json("roads.json")
        ways = split_at_junctions(
            roads["ways"], {j["node_id"] for j in roads["junction_nodes"]},
        )
        ways = [w for w in ways
                if w["tags"].get("highway") in DRIVABLE and not w["tags"].get("bridge")]
        nodes = build_graph(ways)
        plans = plan_drivable_ways(ways, nodes)
        node = nodes[235351970]
        by_way = {id(p.way): p for p in plans}
        junction = prepare_junctions({node.id: node}, by_way)[0]
        legs = junction["legs"]
        counts = junction["corner_segments"]
        center = junction["center"]
        grid = junction_polygon_grid([junction])
        asphalt = Polygon(junction["asphalt_loop"])
        self.assertTrue(asphalt.is_valid)
        inner_arcs = build_corner_arcs(legs, "sw_in", center, counts)
        outer_arcs = build_corner_arcs(legs, "sw_out", center, counts)
        edge_arcs = build_corner_arcs(legs, "edge", center, counts)
        gutter_arcs = build_corner_arcs(legs, "gutter_out", center, counts)
        for inner, outer, edge, gutter in zip(inner_arcs, outer_arcs, edge_arcs, gutter_arcs):
            footprint = Polygon(inner + list(reversed(outer)))
            self.assertTrue(footprint.is_valid)
            self.assertLess(footprint.intersection(asphalt).area, 1e-6)
            triangles = []
            for i in range(len(inner) - 1):
                triangles.extend(ribbon_triangles_outside_junctions(
                    inner[i], inner[i + 1], outer[i], outer[i + 1], grid,
                ))
            mesh_area = unary_union([Polygon(tri) for tri in triangles])
            self.assertLess(mesh_area.symmetric_difference(footprint).area, 1e-6)
            for a, b in zip(edge[1:-1], gutter[1:-1]):
                self.assertAlmostEqual(math.dist(a, b), GUTTER_WIDTH, places=6)

        meshes = {}
        build_junction_geometry([junction], FlatHeightmap(), meshes, grid)
        # Gutter concrete remains below the walking surface; the sidewalk itself
        # must meet the curb top rather than sitting below the asphalt.
        sidewalk_heights = [v[1] for v in meshes["sidewalk_concrete"].verts
                            if v[1] > ROAD_Y_BIAS + 0.02]
        self.assertTrue(sidewalk_heights)
        self.assertTrue(all(y == CURB_TOP_Y_BIAS for y in sidewalk_heights))

    def test_gutter_pan_spans_both_straight_road_edges(self):
        meshes = {}
        build_way_surfaces([StraightRoadPlan()], FlatHeightmap(), meshes)

        gutter = meshes["sidewalk_concrete"]
        self.assertEqual(len(gutter.indices), 24)
        gutter_vertices = [gutter.verts[i] for i in gutter.indices]
        self.assertTrue(any(vertex[2] > 0.0 for vertex in gutter_vertices))
        self.assertTrue(any(vertex[2] < 0.0 for vertex in gutter_vertices))
        self.assertTrue(all(vertex[0] in (0.0, 10.0) for vertex in gutter_vertices))


if __name__ == "__main__":
    unittest.main()
