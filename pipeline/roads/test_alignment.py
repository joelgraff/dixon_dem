"""Horizontal control (phase 1): alignment geometry and fitting, routes, the aerial band fit.

Run with: ../../.venv/bin/python test_alignment.py
"""
import json
import math
import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aerial_width as aw  # noqa: E402
import alignment as al  # noqa: E402
import routes as rt  # noqa: E402


def arc_polyline(radius=60.0, turn_deg=70.0, lead=100.0, tail=120.0, vertices=10):
    """A tangent, a circular curve drawn with `vertices` chords, and a tangent: OSM style."""
    pts = [(-lead, 0.0)]
    for k in range(vertices + 1):
        t = math.radians(turn_deg) * k / vertices
        pts.append((radius * math.sin(t), radius - radius * math.cos(t)))
    a = math.radians(turn_deg)
    pts.append((pts[-1][0] + math.cos(a) * tail, pts[-1][1] + math.sin(a) * tail))
    return pts


class Geometry(unittest.TestCase):
    def test_tangent_curve_tangent(self):
        a = al.Alignment([(0, 0), (50, 0), (50, 50)], [0, 10, 0])
        self.assertTrue(a.valid)
        self.assertAlmostEqual(a.length, 40 + 40 + 10 * math.pi / 2, places=9)
        self.assertEqual([e["type"] for e in a.elements], ["tangent", "arc", "tangent"])
        x, z, _ = a.point_at(40 + 10 * math.pi / 4)                      # middle of the curve
        self.assertAlmostEqual(x, 40 + 10 * math.sin(math.pi / 4), places=9)
        self.assertAlmostEqual(z, 10 - 10 * math.cos(math.pi / 4), places=9)
        self.assertEqual(a.elements[1]["delta"] > 0, True)                # east to south: right turn
        self.assertEqual(a.to_json()["elements"][1]["turn"], "R")

    def test_sample_matches_point_at(self):
        a = al.Alignment([(0, 0), (50, 0), (80, 40), (80, 90)], [0, 20, 15, 0])
        stas, pts, dirs = a.sample(0.5)
        for k in range(0, len(stas), 17):
            x, z, d = a.point_at(stas[k])
            self.assertAlmostEqual(pts[k, 0], x, places=6)
            self.assertAlmostEqual(pts[k, 1], z, places=6)
            self.assertAlmostEqual(dirs[k, 0], d[0], places=6)

    def test_projection_left_is_positive(self):
        project = al.Alignment([(0, 0), (100, 0)]).projector()
        sta, left, dist = project([(20, -3), (20, 3)])                    # -z is north: left of eastbound
        self.assertTrue(np.allclose(sta, 20))
        self.assertTrue(np.allclose(left, [3, -3]))

    def test_overlapping_curves_are_invalid(self):
        self.assertFalse(al.Alignment([(0, 0), (20, 0), (20, 20), (40, 20)], [0, 50, 50, 0]).valid)

    def test_bearing(self):
        self.assertAlmostEqual(al.bearing_deg((0, -1)), 0.0)             # north
        self.assertAlmostEqual(al.bearing_deg((1, 0)), 90.0)             # east


class Fitting(unittest.TestCase):
    def test_recovers_a_curve_drawn_with_chords(self):
        a, info = al.fit(arc_polyline())
        self.assertEqual(info["curves"], 1)
        self.assertEqual(a.radii[1], 60.0)                                # rounded to 5 m
        self.assertAlmostEqual(a.pis[1][0], 60 * math.tan(math.radians(35)), delta=0.5)
        self.assertLessEqual(info["max_dev"], 0.5)

    def test_jog_becomes_one_tangent(self):
        a, info = al.fit([(0, 0), (80, 0), (80, 0.7), (200, 0.7)], tol=1.0)
        self.assertEqual(len(a.pis), 2)
        self.assertLessEqual(info["max_dev"], 1.0)

    def test_route_that_loops_past_itself(self):
        # a parking aisle around a lot, back through its own start
        pts = [(0, 0), (60, 0), (60, 30), (0, 30), (0, 0), (0, -30), (60, -30), (60, 0)]
        a, info = al.fit(pts, tol=0.5)
        self.assertLessEqual(info["max_dev"], 0.5)

    def test_snaps_near_grid_tangents(self):
        d = (math.sin(math.radians(91.0)), -math.cos(math.radians(91.0)))   # bearing 91 deg
        pts = [(0, 0), (200 * d[0], 200 * d[1])]
        a, info = al.fit(pts, tol=5.0, grid=[0.0], snap_deg=1.5)
        self.assertEqual(info["snapped_tangents"], 1)
        e = a.elements[0]
        self.assertAlmostEqual(al.bearing_deg((e["end"][0] - e["start"][0], e["end"][1] - e["start"][1])), 90.0, places=6)
        a, info = al.fit(pts, tol=0.5, grid=[0.0], snap_deg=1.5)        # 200 m at 1 deg is 1.7 m off
        self.assertEqual(info["snapped_tangents"], 0)

    def test_grid_bearings(self):
        tangents = [((math.sin(math.radians(b)), -math.cos(math.radians(b))), 100.0)
                    for b in (343.5, 73.5, 163.4, 1.8, 91.8, 343.6)]
        grid = al.grid_bearings(tangents)
        self.assertEqual(len(grid), 2)
        self.assertTrue(any(abs(g - 73.5) < 0.3 for g in grid))
        self.assertTrue(any(abs(g - 1.8) < 0.3 for g in grid))

    def test_round_radius(self):
        rounding = ((100, 5), (300, 10), (1e9, 25))
        self.assertEqual(al.round_radius(62.4, rounding), 60)
        self.assertEqual(al.round_radius(147, rounding), 150)
        self.assertEqual(al.round_radius(1012, rounding), 1000)


def way(wid, name, highway, nodes):
    return {"id": wid, "tags": {"name": name, "highway": highway},
            "vertices": [{"x": float(x), "z": float(z), "node_id": n} for n, (x, z) in nodes]}


RANK = {"primary": 4, "residential": 2, "service": 1}.get


class Routes(unittest.TestCase):
    def test_street_name(self):
        self.assertEqual(rt.street_name("West 1st Street"), "1st street")
        self.assertEqual(rt.street_name("East 1st Street"), "1st street")
        self.assertEqual(rt.street_name("North Galena Avenue"), "galena avenue")
        self.assertEqual(rt.street_name("Northgate Road"), "northgate road")
        self.assertIsNone(rt.street_name(None))

    def test_a_street_continues_across_a_junction(self):
        ways = [way(1, "West 1st Street", "residential", [(10, (0, 0)), (11, (100, 0))]),
                way(2, "East 1st Street", "residential", [(11, (100, 0)), (12, (200, 0))]),
                way(3, "Galena Avenue", "primary", [(20, (100, -100)), (11, (100, 0)), (21, (100, 100))])]
        routes = rt.build_routes(ways, RANK)
        names = sorted(tuple(sorted({w["tags"]["name"] for w, *_ in r["pieces"]})) for r in routes)
        self.assertEqual(names, [("East 1st Street", "West 1st Street"), ("Galena Avenue",)])
        first = [r for r in routes if r["pieces"][0][0]["id"] in (1, 2)][0]
        poly = rt.route_polyline(first)
        self.assertEqual(len(poly), 3)

    def test_unnamed_ways_join_only_straight_through_a_plain_node(self):
        ways = [way(1, None, "service", [(1, (0, 0)), (2, (50, 0))]),
                way(2, None, "service", [(2, (50, 0)), (3, (100, 5))]),
                way(3, None, "service", [(3, (100, 5)), (4, (100, 60))])]       # a 90 degree turn
        routes = rt.build_routes(ways, RANK)
        self.assertEqual(sorted(len(r["pieces"]) for r in routes), [1, 2])

    def test_orientation_west_to_east_south_to_north(self):
        self.assertTrue(rt.orient([(100, 0), (0, 5)]))         # runs west: reverse
        self.assertFalse(rt.orient([(0, 0), (100, 5)]))
        self.assertTrue(rt.orient([(0, -100), (3, 0)]))        # runs south (z grows): reverse
        self.assertFalse(rt.orient([(0, 0), (3, -100)]))


class AerialBand(unittest.TestCase):
    def profile(self, left, right):
        offs = np.arange(-15, 15.001, aw.RES_M)
        grass = np.array([0.30, 0.33, 0.20])
        asphalt = np.array([0.37, 0.35, 0.31])
        prof = np.where(((offs >= right) & (offs <= left))[:, None], asphalt, grass)
        return offs, prof + np.random.default_rng(1).normal(0, 0.01, prof.shape)

    def test_finds_the_asphalt_band(self):
        offs, prof = self.profile(left=4.0, right=-6.0)
        right, left, score = aw.band_fit(prof, offs)
        self.assertAlmostEqual(right, -6.0, delta=0.3)
        self.assertAlmostEqual(left, 4.0, delta=0.3)
        self.assertGreater(score, aw.MIN_SCORE)

    def test_blocks_skip_junctions(self):
        stas = np.arange(0, 400.001, aw.STEP_M)
        out = aw.blocks(stas, [(200.0, 200.0)])
        for i0, i1 in out:
            self.assertTrue(stas[i1 - 1] < 200 - aw.JUNCTION_CLEAR_M or stas[i0] > 200 + aw.JUNCTION_CLEAR_M)
            self.assertLessEqual(stas[i1 - 1] - stas[i0], aw.BLOCK_MAX_M)


ALIGNMENTS = os.path.join(al.__file__.rsplit("/pipeline/", 1)[0], "game", "data", "alignments.json")


@unittest.skipUnless(os.path.exists(ALIGNMENTS), "no alignments.json")
class Built(unittest.TestCase):
    def test_every_route_is_a_valid_alignment(self):
        with open(ALIGNMENTS) as handle:
            data = json.load(handle)
        self.assertEqual(data["format"], "dixon-alignments")
        for r in data["routes"]:
            a = al.Alignment(r["pis"], r["radii"])
            self.assertTrue(a.valid, r["id"])
            self.assertAlmostEqual(a.length, r["length"], delta=0.01)
            for w in r["ways"]:
                self.assertLessEqual(w["sta"][0], w["sta"][1])


if __name__ == "__main__":
    unittest.main()
