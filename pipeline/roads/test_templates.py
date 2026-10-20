"""Cross-section templates and design roads (phase 3a).

Run with: ../../.venv/bin/python test_templates.py
"""
import json
import math
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import alignment as al  # noqa: E402
import templates as tp  # noqa: E402
import transport_layout as layout  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402

STANDARDS = tp.load_json(tp.STANDARDS_PATH)
CS = STANDARDS["cross_section"]
BOUNDS = (0.0, -2700.0, 2699.0, -1.0)


def vert(x, z, node=None):
    return {"x": float(x), "y": 10.0, "z": float(z), "node_id": node}


def way(id_, verts, highway="residential", width=6.5, **tags):
    return {"id": id_, "vertices": verts, "tags": dict(highway=highway, width_m=width, name="Test Street", **tags)}


def route(id_, pis, ways, width=None, cls="local"):
    a = al.Alignment(pis)
    rec = {"id": id_, "class": cls, "ways": ways, "bridges": []}
    rec.update(a.to_json())
    if width:
        rec["width"] = width
    return rec


class LaneSplit(unittest.TestCase):
    def test_parking_goes_in_while_the_lanes_stay_wide_enough(self):
        lanes, lane_m, parking = tp.lane_split(10.363, "local", False, True, CS)       # 34 ft
        self.assertEqual((lanes, parking), (2, 2))
        self.assertGreaterEqual(lane_m, CS["lane_width_min"]["local"])
        self.assertAlmostEqual(2 * lane_m + 2 * CS["parking_lane_width"], 10.363, places=2)
        self.assertEqual(tp.lane_split(9.754, "local", False, True, CS)[2], 1)         # 32 ft: one side

    def test_narrow_street_has_no_parking(self):
        self.assertEqual(tp.lane_split(6.096, "local", False, True, CS)[2], 0)

    def test_tagged_lanes_are_kept_and_parking_gives_way(self):
        lanes, lane_m, parking = tp.lane_split(16.459, "arterial", False, True, CS, lanes=4)
        self.assertEqual((lanes, parking), (4, 1))
        self.assertGreaterEqual(lane_m, CS["lane_width_min"]["arterial"])

    def test_uncurbed_never_parks(self):
        self.assertEqual(tp.lane_split(12.0, "service", False, False, CS)[2], 0)


class Templates(unittest.TestCase):
    def setUp(self):
        self.ways = {1: way(1, [vert(0, -100), vert(100, -100)]),
                     2: way(2, [vert(100, -100), vert(200, -100)], width=9.2, highway="primary")}

    def test_aerial_width_and_overlaid_gutter(self):
        block = {"gutter": ["overlaid", "overlaid"]}
        rec = route("R1", [(0, -100), (100, -100)], [{"id": 1, "sta": [0.0, 100.0]}],
                    {"source": "aerial", "curb_to_curb_m": 10.363, "block_detail": [block, block]})
        (t,) = tp.route_templates(rec, self.ways, STANDARDS)
        self.assertEqual((t["curb_to_curb_m"], t["width_source"]), (10.363, "aerial"))
        self.assertEqual((t["gutter"], t["gutter_visible_m"], t["gutter_m"]), ("overlaid", 0.0, CS["gutter_width"]))
        self.assertEqual((t["curb"], t["curb_reveal_m"]), ("new", CS["curb_reveal"]))
        self.assertEqual((t["section"], t["parkway_m"], t["sidewalk_m"]), ("residential", 2.0, 1.7))

    def test_visible_gutter_needs_a_clear_majority(self):
        seen = {"block_detail": [{"gutter": ["visible", "visible"]}, {"gutter": ["visible", None]}]}
        self.assertEqual(tp.gutter_state(seen, CS), ("visible", "aerial"))
        split = {"block_detail": [{"gutter": ["visible", "overlaid"]}]}
        self.assertEqual(tp.gutter_state(split, CS)[0], "overlaid")
        self.assertEqual(tp.gutter_state(None, CS), (CS["gutter_default"], "default"))

    def test_importer_default_falls_back_to_the_class_median(self):
        rec = route("R1", [(0, -100), (100, -100)], [{"id": 1, "sta": [0.0, 100.0]}])
        widths = {"local": {"curb_to_curb_m": 9.754}}
        (t,) = tp.route_templates(rec, self.ways, STANDARDS, widths=widths)
        self.assertEqual((t["curb_to_curb_m"], t["width_source"]), (9.754, "class_median"))
        self.assertIsNone(tp.osm_width({"highway": "residential", "width_m": 6.5}))
        self.assertEqual(tp.osm_width({"highway": "primary", "width_m": 16.4}), 16.4)

    def test_width_change_tapers_across_the_break(self):
        rec = route("R1", [(0, -100), (200, -100)], [{"id": 1, "sta": [0.0, 100.0]},
                                                       {"id": 2, "sta": [100.0, 200.0]}])
        ranges = tp.route_templates(rec, self.ways, STANDARDS, widths={"local": {"curb_to_curb_m": 9.754}})
        self.assertEqual(len(ranges), 2)
        L = ranges[1]["taper_m"]
        self.assertGreater(L, 0)
        self.assertAlmostEqual(tp.half_width_at(ranges, 100.0 - L / 2), 9.754 / 2, places=6)
        self.assertAlmostEqual(tp.half_width_at(ranges, 100.0 + L / 2), ranges[1]["curb_to_curb_m"] / 2, places=6)
        mid = tp.half_width_at(ranges, 100.0)
        self.assertAlmostEqual(mid, (9.754 + ranges[1]["curb_to_curb_m"]) / 4, places=6)

    def test_override_splits_a_range(self):
        rec = route("R1", [(0, -100), (100, -100)], [{"id": 1, "sta": [0.0, 100.0]}])
        o = {"route": "R1", "sta": [40.0, 60.0], "curb_to_curb_ft": 40, "curb": "older", "gutter": "visible"}
        ranges = tp.route_templates(rec, self.ways, STANDARDS, [o], widths={"local": {"curb_to_curb_m": 9.754}})
        self.assertEqual([r["sta"] for r in ranges], [[0.0, 40.0], [40.0, 60.0], [60.0, 100.0]])
        self.assertEqual(ranges[1]["width_source"], "override")
        self.assertAlmostEqual(ranges[1]["curb_to_curb_m"], 12.192)
        self.assertEqual((ranges[1]["curb_reveal_m"], ranges[1]["gutter_visible_m"]),
                         (CS["curb_reveal_older"], CS["gutter_width"]))

    def test_unknown_override_keys_are_refused(self):
        path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "test_templates_overrides.json")
        with open(path, "w") as handle:
            json.dump({"templates": [{"route": "R1", "width": 3}]}, handle)
        with self.assertRaises(ValueError):
            tp.load_overrides(path)
        os.remove(path)


class DesignRoads(unittest.TestCase):
    def test_arc_stations_stay_on_the_curve(self):
        a = al.Alignment([(0, 0), (50, 0), (50, 50)], [0, 12, 0])
        stas = tp.densify_stations(a, 0.0, a.length)
        self.assertEqual((stas[0], stas[-1]), (0.0, a.length))
        arc = a.elements[1]
        for s0, s1 in zip(stas, stas[1:]):
            if arc["sta"][0] <= s0 and s1 <= arc["sta"][1]:
                half = (s1 - s0) / 2 / 12
                self.assertLessEqual(12 * (1 - math.cos(half)), tp.ARC_CHORD_ERR_M + 1e-9)
        self.assertEqual(tp.densify_stations(a, a.length, 0.0)[0], a.length)

    def test_ways_follow_the_alignment_and_meet_at_the_junction(self):
        # a straight street drawn with OSM jitter, crossed by a side street ending on it
        main = way(1, [vert(0, -100.4, 10), vert(50, -99.6), vert(100, -100.3, 11), vert(200, -99.8, 12)])
        side = way(2, [vert(100.5, -100.0, 11), vert(100.2, -150, 13)])
        roads = {"ways": [main, side], "junction_nodes": [{"node_id": 11, "x": 100.0, "z": -100.0, "way_ids": [1, 2]}]}
        r1 = route("R1", [(0, -100), (200, -100)], [{"id": 1, "sta": [0.0, 200.0]}])
        r2 = route("R2", [(100, -150), (100, -100)], [{"id": 2, "sta": [0.0, 50.0]}])
        alignments = {"routes": [r1, r2], "junctions": [
            {"node_id": 11, "x": 100.0, "z": -100.0,
             "legs": [{"route": "R1", "sta": 100.0, "through": True}, {"route": "R2", "sta": 50.0, "through": False}]}]}
        templates = tp.build(alignments, roads, STANDARDS, {})
        out, report = tp.design_roads(roads, alignments, templates, BOUNDS)
        a, b = out["ways"]
        self.assertTrue(a["design"] and b["design"])
        self.assertTrue(all(abs(v["z"] + 100.0) < 1e-9 for v in a["vertices"]))     # on the alignment
        node_a = next(v for v in a["vertices"] if v["node_id"] == 11)
        node_b = next(v for v in b["vertices"] if v["node_id"] == 11)
        self.assertEqual((node_a["x"], node_a["z"]), (node_b["x"], node_b["z"]))   # one junction point
        self.assertAlmostEqual(node_a["x"], 100.0)
        self.assertAlmostEqual(b["vertices"][0]["x"], 100.0, places=6)            # moved onto R1, blended
        self.assertEqual(a["tags"]["osm_width_m"], 6.5)
        self.assertAlmostEqual(a["tags"]["width_m"], 2 * a["vertices"][0]["hw"])
        self.assertEqual(a["template"]["section"], "residential")
        self.assertEqual(report["osm_centreline_kept_in_play_km"], 0.0)

    def test_run_on_a_loop_takes_the_stretch_matching_its_length(self):
        # a lollipop route: a stem, then a loop back to the stem's end; the stem's end node is
        # passed twice, and the stem must not run around the loop
        stem = way(1, [vert(0, -100, 1), vert(50, -100, 2)])
        loop = way(2, [vert(50, -100, 2), vert(100, -100), vert(100, -150), vert(50, -150), vert(50, -100, 2)])
        roads = {"ways": [stem, loop], "junction_nodes": [{"node_id": 2, "x": 50, "z": -100, "way_ids": [1, 2]}]}
        pis = [(0, -100), (100, -100), (100, -150), (50, -150), (50, -100)]
        r = route("R1", pis, [{"id": 1, "sta": [0.0, 200.0]}, {"id": 2, "sta": [50.0, 200.0]}])
        alignments = {"routes": [r], "junctions": []}
        out, _ = tp.design_roads(roads, alignments, tp.build(alignments, roads, STANDARDS, {}), BOUNDS)
        stem_out = out["ways"][0]["vertices"]
        length = sum(math.hypot(q["x"] - p["x"], q["z"] - p["z"]) for p, q in zip(stem_out, stem_out[1:]))
        self.assertAlmostEqual(length, 50.0, places=6)


def plan(points, hw, **kw):
    base = dict(full_centerline=points, half_w=hw, has_curb=True, downtown=False)
    base.update(kw)
    return SimpleNamespace(**base)


class BuildingFaces(unittest.TestCase):
    def test_estimated_widths_narrow_to_the_faces_and_measured_ones_do_not(self):
        overrides, rows = tp.face_overrides(exclude=tp.roofless_ids())
        self.assertEqual(len(overrides), len(rows))
        for o, row in zip(overrides, rows):
            self.assertEqual(o["source"], tp.FACE_SOURCE)
            self.assertIn("Building faces", o["note"])
            self.assertIn(row["width_source"], tp.FACE_ESTIMATES)       # never an aerial survey width
            self.assertLess(row["to_m"], row["from_m"])
            self.assertLessEqual(o["sta"][0], row["faces_sta"][0])
            self.assertGreaterEqual(o["sta"][1], row["faces_sta"][1])
        # downtown Galena at First: 16.46 m (54 ft OSM tag) between fronts 13.3 m apart; four
        # lanes at the 3.05 m minimum hold it at 41 ft
        galena = [o for o in overrides if o["route"] == "R51389016" and o["sta"][0] < 1470 < o["sta"][1]]
        self.assertEqual([o["curb_to_curb_ft"] for o in galena], [41])


class Layout(unittest.TestCase):
    EMPTY = {"version": 1, "junctions": [], "lots": [], "exclude_paving": []}

    def test_tapered_corridor(self):
        points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0)]
        p = plan(points, 4.0, half_ws=[3.0, 3.0, 5.0, 5.0])
        corridor = layout.plan_corridor(p)
        self.assertAlmostEqual(corridor.intersection(LineString([(5, -9), (5, 9)])).length, 6.0, places=6)
        self.assertAlmostEqual(corridor.intersection(LineString([(15, -9), (15, 9)])).length, 8.0, places=6)
        self.assertAlmostEqual(corridor.intersection(LineString([(25, -9), (25, 9)])).length, 10.0, places=6)

    def test_overlaid_gutter_is_not_built_and_template_roadside_is(self):
        p = plan([(0.0, 0.0), (80.0, 0.0)], 5.0, gutter_w=0.0, parkway=1.0, sw_width=2.0)
        surfaces, _ = layout.build_layout([p], {}, Polygon(), Polygon(), self.EMPTY)
        self.assertTrue(surfaces["gutter"].is_empty)
        for name, z in (("curb", 5.06), ("parkway", 5.6), ("sidewalk", 7.0)):
            self.assertTrue(surfaces[name].contains(Point(40, z)), name)
        self.assertFalse(surfaces["sidewalk"].contains(Point(40, 8.3)))

    def test_walk_stops_at_a_building_face_and_the_conflict_is_listed(self):
        p = plan([(0.0, 0.0), (80.0, 0.0)], 5.0, gutter_w=0.0, parkway=2.0, sw_width=1.7)
        building = Polygon([(30, 7.5), (50, 7.5), (50, 20), (30, 20)])
        surfaces, report = layout.build_layout([p], {}, Polygon(), building, self.EMPTY)
        self.assertLess(surfaces["sidewalk"].intersection(building).area, 1e-6)
        self.assertTrue(surfaces["sidewalk"].contains(Point(20, 8.0)))
        conflict = report["roadside_conflicts"]["sidewalk"]
        self.assertEqual(conflict["count"], 1)
        self.assertAlmostEqual(conflict["area_m2"], 20 * (8.82 - 7.5), places=0)
        self.assertEqual(report["roadside_conflicts"]["asphalt"]["count"], 0)

    def test_visible_gutter_takes_the_template_width(self):
        p = plan([(0.0, 0.0), (80.0, 0.0)], 5.0, gutter_w=0.61, parkway=2.0, sw_width=1.7)
        surfaces, _ = layout.build_layout([p], {}, Polygon(), Polygon(), self.EMPTY)
        self.assertAlmostEqual(surfaces["gutter"].intersection(LineString([(40, 0), (40, 8)])).length, 0.61, places=6)

    def test_older_curb_is_lower(self):
        import numpy as np

        class Flat:
            sample = staticmethod(lambda x, z: 0.0)
            normal = staticmethod(lambda x, z: [0.0, 1.0, 0.0])
            sample_many = staticmethod(lambda x, z: np.zeros(len(x)))
            normal_many = staticmethod(lambda x, z: np.tile([0.0, 1.0, 0.0], (len(x), 1)))
        p = plan([(0.0, 0.0), (80.0, 0.0)], 5.0, gutter_w=0.0, parkway=2.0, sw_width=1.7, curb_reveal=0.102)
        surfaces, _ = layout.build_layout([p], {}, Polygon(), Polygon(), self.EMPTY)
        meshes = {}
        layout.emit_layout(surfaces, Flat(), meshes, layout.older_curb_region([p]))
        tops = {round(v[1], 4) for v in meshes["sidewalk_concrete"].verts}
        self.assertEqual(tops, {round(layout.ROAD_BIAS + layout.CURB_REVEAL_OLDER, 4)})


if __name__ == "__main__":
    unittest.main()
