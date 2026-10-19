"""Vertical control (vertical.py, build_profiles.py) and the conformed heightmap that reads it.

Run: ../../.venv/bin/python -m unittest test_profiles
"""
import json
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import build_profiles as bp  # noqa: E402
import road_metrics as rm  # noqa: E402
import vertical as vt  # noqa: E402

STANDARDS = rm.load_standards()


class Plane:
    """A ground surface y = f(x, z) standing in for the DEM sampler."""

    def __init__(self, f):
        self.f = f

    def sample(self, xs, zs):
        return self.f(np.asarray(xs, dtype=np.float64), np.asarray(zs, dtype=np.float64))


def route(rid, pis, cls="local", highway="residential", way_id=1, bridges=()):
    length = float(np.sum(np.hypot(*np.diff(np.array(pis, dtype=float), axis=0).T)))
    return {"id": rid, "name": rid, "class": cls, "highway": highway, "pis": pis,
            "radii": [0.0] * len(pis), "ways": [{"id": way_id, "sta": [0.0, length]}],
            "bridges": list(bridges)}


def way(wid, pts, highway="residential", width=8.0, bridge=False):
    return {"id": wid, "tags": {"highway": highway, "width_m": width, "bridge": bridge},
            "vertices": [{"x": x, "z": z} for x, z in pts]}


def solve(routes, ground, junctions=(), ways=(), rails=(), designs=None, overrides=None):
    return bp.solve(surface=ground, standards=STANDARDS,
                    alignments={"routes": list(routes), "junctions": list(junctions)},
                    roads={"ways": list(ways)}, rails={"ways": list(rails)},
                    designs=designs or {}, overrides=overrides or {})


def prof(doc, rid):
    return vt.Profile.from_json(doc["routes"][rid]["pvis"])


class ProfileGeometry(unittest.TestCase):
    def test_parabolic_curves_are_continuous_in_elevation_and_grade(self):
        S = [0.0, 20.0, 45.0, 60.0]
        p = vt.Profile(S, [0.0, 1.0, 0.2, 0.5], vt.curve_lengths(S))
        s = np.linspace(0.0, 60.0, 6001)
        y, g = p.elevation(s), p.grade(s)
        self.assertLess(np.max(np.abs(np.diff(y))), 0.01 * 0.1 + 1e-6)     # no jumps
        self.assertLess(np.max(np.abs(np.diff(g))), 1e-3)                  # no kinks: G1
        self.assertTrue(np.allclose(np.gradient(y, s)[10:-10], g[10:-10], atol=1e-4))

    def test_straights_pass_through_the_pvis_and_curves_have_the_textbook_middle_ordinate(self):
        S = np.array([0.0, 50.0, 100.0])
        L = np.array([0.0, 20.0, 0.0])
        p = vt.Profile(S, [0.0, 2.0, 0.0], L)
        self.assertAlmostEqual(float(p.elevation([20.0])[0]), 0.8)          # on the first straight
        A = p.grades()[1] - p.grades()[0]
        self.assertAlmostEqual(float(p.elevation([50.0])[0]), 2.0 + A * 20.0 / 8.0)   # e = A L / 8
        crest = p.curves()[0]
        self.assertEqual(crest["kind"], "crest")
        self.assertAlmostEqual(crest["K"], 20.0 / (abs(A) * 100))

    def test_pvi_stations_keep_controls_and_fill_long_gaps(self):
        S = vt.pvi_stations(100.0, hard=[37.0, 38.0, 99.0], spacing=20.0, min_gap=2.5)
        self.assertEqual(S[0], 0.0)
        self.assertEqual(S[-1], 100.0)
        self.assertIn(37.0, S)
        self.assertNotIn(38.0, S)       # too close to 37
        self.assertNotIn(99.0, S)       # too close to the end
        self.assertLessEqual(np.max(np.diff(S)), 20.0 + 1e-9)


class RobustFit(unittest.TestCase):
    def test_a_dem_spike_does_not_drag_the_grade(self):
        net = vt.Network()
        net.add("a", vt.pvi_stations(100.0, spacing=20.0))
        s = np.arange(0.0, 100.1, 1.0)
        y = 0.04 * s
        y[48:53] += 4.0                 # a bridge-removal pit or a building pixel, upside down
        net.rows("a", s, y, 1.0, huber=0.1)
        net.smoothing("a", bp.SMOOTH_W, huber=bp.SMOOTH_HUBER)
        p = net.solve()["a"]
        clean = np.r_[0:45, 56:101]
        self.assertLess(np.max(np.abs(p.elevation(s[clean]) - 0.04 * s[clean])), 0.03)

    def test_a_real_embankment_is_followed_not_cut_through(self):
        # 6 m up in 20 m and down again: robust smoothing lets the grade break where the ground does
        s = np.arange(0.0, 60.1, 1.0)
        y = np.interp(s, [0, 10, 30, 50, 60], [10, 10, 16, 10, 10])
        net = vt.Network()
        net.add("a", np.array([0, 10, 30, 50, 60.0]), np.array([0, 4, 4, 4, 0.0]))
        net.rows("a", s, y, 1.0, huber=0.1)
        net.smoothing("a", bp.SMOOTH_W, huber=bp.SMOOTH_HUBER)
        p = net.solve()["a"]
        self.assertLess(np.max(np.abs(p.elevation(s) - y)), 0.45)
        quadratic = vt.Network()
        quadratic.add("a", np.array([0, 10, 30, 50, 60.0]), np.array([0, 4, 4, 4, 0.0]))
        quadratic.rows("a", s, y, 1.0, huber=0.1)
        quadratic.smoothing("a", bp.SMOOTH_W)
        q = quadratic.solve()["a"]
        self.assertGreater(np.max(np.abs(q.elevation(s) - y)), 2.0)     # what it used to do


class NetworkSolve(unittest.TestCase):
    ground = Plane(lambda x, z: 10.0 + 0.02 * x + 0.06 * z)

    def t_junction(self):
        a = route("A", [[0.0, 0.0], [200.0, 0.0]], cls="arterial", highway="primary", way_id=1)
        b = route("B", [[100.0, 0.0], [100.0, 120.0]], way_id=2)
        j = {"node_id": 7, "x": 100.0, "z": 0.0, "legs": [
            {"route": "A", "sta": 100.0, "through": True, "heading_deg": 90.0},
            {"route": "B", "sta": 0.0, "through": False, "heading_deg": 180.0}]}
        ways = [way(1, [(0, 0), (200, 0)], "primary", 12.0), way(2, [(100, 0), (100, 120)])]
        return a, b, j, ways

    def test_junction_elevations_are_shared_and_the_senior_route_keeps_its_profile(self):
        a, b, j, ways = self.t_junction()
        doc, report = solve([a, b], self.ground, [j], ways)
        alone, _ = solve([a], self.ground, [], ways[:1])
        pa, pb = prof(doc, "A"), prof(doc, "B")
        self.assertAlmostEqual(float(pa.elevation([100.0])[0]), float(pb.elevation([0.0])[0]), places=3)
        s = np.linspace(0.0, 200.0, 41)
        self.assertLess(np.max(np.abs(pa.elevation(s) - prof(alone, "A").elevation(s))), 1e-6)
        self.assertEqual(report["conflicts"], [])
        # the ground plus the road surface, followed closely
        self.assertLess(report["fit_to_ground_m"]["p99"], 0.02)

    def test_a_composed_deck_holds_the_approach_profile_at_its_ends(self):
        river = Plane(lambda x, z: np.where((x > 60) & (x < 120), 5.0, 10.0))
        design = {"centerline": [[60.0, 0.0], [120.0, 0.0]],
                  "deck": {"elevation": [[0.0, 10.6], [30.0, 11.1], [60.0, 10.6]]}}
        a = route("A", [[0.0, 0.0], [200.0, 0.0]], way_id=1, bridges=[{"way_id": 5, "sta": [60.0, 120.0]}])
        ways = [way(1, [(0, 0), (60, 0)]), way(5, [(60, 0), (120, 0)], bridge=True)]
        doc, report = solve([a], river, ways=ways, designs={"5": design})
        p = prof(doc, "A")
        self.assertAlmostEqual(float(p.elevation([60.0])[0]), 10.6, delta=0.01)
        self.assertAlmostEqual(float(p.elevation([120.0])[0]), 10.6, delta=0.01)
        self.assertAlmostEqual(float(p.grade([60.0])[0]), 0.5 / 30.0, delta=0.002)
        self.assertGreater(float(p.elevation([90.0])[0]), 10.6)     # the river below is not data
        self.assertEqual(doc["routes"]["A"]["bridge_ends"][0]["sta"], 60.0)
        self.assertEqual(report["conflicts"], [])

    def test_a_route_ending_at_a_deck_it_does_not_carry_meets_its_height(self):
        # a track at the end of a path bridge
        design = {"centerline": [[100.0, 0.0], [160.0, 0.0]],
                  "deck": {"elevation": [[0.0, 12.6], [60.0, 12.6]]}}
        a = route("T", [[0.0, 0.0], [100.0, 0.0]], cls="service", highway="track", way_id=1)
        doc, report = solve([a], self.ground, ways=[way(1, [(0, 0), (100, 0)], "track")],
                            designs={"9": design})
        self.assertAlmostEqual(float(prof(doc, "T").elevation([100.0])[0]), 12.6, delta=0.01)
        self.assertEqual(doc["routes"]["T"]["bridge_ends"], [{"sta": 100.0, "side": -1, "bridge": "9"}])

    def test_a_deck_end_far_off_its_approach_ground_is_not_held(self):
        # set in Bridge Composer for another purpose: the approach keeps to its ground
        design = {"centerline": [[100.0, 0.0], [160.0, 0.0]],
                  "deck": {"elevation": [[0.0, 6.0], [60.0, 6.0]]}}
        a = route("T", [[0.0, 0.0], [100.0, 0.0]], cls="service", highway="track", way_id=1)
        doc, report = solve([a], self.ground, ways=[way(1, [(0, 0), (100, 0)], "track")],
                            designs={"9": design})
        self.assertAlmostEqual(float(prof(doc, "T").elevation([100.0])[0]), 12.0 + bp.ROAD_SURFACE_M, delta=0.02)
        self.assertNotIn("bridge_ends", doc["routes"]["T"])
        self.assertEqual(len(report["deck_ends_not_held"]), 1)

    def test_the_road_meets_the_top_of_rail_at_a_grade_crossing(self):
        flat = Plane(lambda x, z: 10.0 + 0.0 * x)
        a = route("A", [[0.0, 0.0], [200.0, 0.0]], way_id=1)
        rail = {"id": 9, "tags": {"bridge": False},
                "vertices": [{"x": 100.0, "z": -50.0, "y": 10.0}, {"x": 100.0, "z": 50.0, "y": 10.0}]}
        doc, report = solve([a], flat, ways=[way(1, [(0, 0), (200, 0)])], rails=[rail])
        self.assertAlmostEqual(float(prof(doc, "A").elevation([100.0])[0]), 10.0 + bp.RAIL_TOP_M, delta=0.01)
        self.assertEqual(report["rails_off_ground_at_crossings"], [])

    def test_a_rail_drawn_far_off_the_ground_is_not_trusted(self):
        flat = Plane(lambda x, z: 10.0 + 0.0 * x)
        a = route("A", [[0.0, 0.0], [200.0, 0.0]], way_id=1)
        rail = {"id": 9, "tags": {"bridge": False},
                "vertices": [{"x": 100.0, "z": -50.0, "y": 12.0}, {"x": 100.0, "z": 50.0, "y": 12.0}]}
        doc, report = solve([a], flat, ways=[way(1, [(0, 0), (200, 0)])], rails=[rail])
        self.assertAlmostEqual(float(prof(doc, "A").elevation([100.0])[0]), 10.0 + bp.RAIL_TOP_M, delta=0.01)
        self.assertEqual(len(report["rails_off_ground_at_crossings"]), 1)

    def test_class_limits_are_advisory(self):
        steep = Plane(lambda x, z: 10.0 + 0.20 * x)      # 20% on a local street, limit 12%
        a = route("A", [[0.0, 0.0], [100.0, 0.0]], way_id=1)
        doc, report = solve([a], steep, ways=[way(1, [(0, 0), (100, 0)])])
        self.assertAlmostEqual(float(prof(doc, "A").grade([50.0])[0]), 0.20, delta=0.002)
        self.assertGreater(report["advisory_totals"]["grade_over_class_max_m"], 90.0)
        self.assertEqual(report["conflicts"], [])

    def test_the_minimum_gutter_grade_only_where_the_ground_allows(self):
        nearly_flat = Plane(lambda x, z: 10.0 + 0.001 * x)
        short = route("S", [[0.0, 0.0], [30.0, 0.0]], way_id=1)
        doc, report = solve([short], nearly_flat, ways=[way(1, [(0, 0), (30, 0)])])
        gmin = STANDARDS["profile"]["min_gutter_grade"]
        self.assertGreaterEqual(float(np.min(np.abs(prof(doc, "S").grades()))), gmin - 1e-4)
        dead_flat = Plane(lambda x, z: 10.0 + 0.0 * x)
        long = route("L", [[0.0, 0.0], [300.0, 0.0]], way_id=1)
        doc, report = solve([long], dead_flat, ways=[way(1, [(0, 0), (300, 0)])])
        self.assertLess(float(np.max(np.abs(prof(doc, "L").elevation(np.arange(0, 300.0, 5)) - 10.085))), 0.02)
        self.assertGreater(report["advisory_totals"]["flat_curbed_m"], 250.0)

    def test_a_pinned_route_and_ignored_ground(self):
        cliff = Plane(lambda x, z: np.where(x < 8.0, 6.0, 10.0))     # the alley off the wall
        a = route("A", [[0.0, 0.0], [60.0, 0.0]], cls="service", highway="service", way_id=1)
        over = {"A": {"route": "A", "ignore_ground": [[0.0, 9.0]]}}
        doc, _ = solve([a], cliff, ways=[way(1, [(0, 0), (60, 0)], "service")], overrides=over)
        self.assertAlmostEqual(float(prof(doc, "A").elevation([0.0])[0]), 10.0 + bp.ROAD_SURFACE_M, delta=0.02)


class Conform(unittest.TestCase):
    """build_heightmap.road_conform: each centreline gets its own profile, junctions blend."""

    def test_junction_blend_keeps_each_centreline_and_has_no_crease(self):
        import build_heightmap as bh
        from affine import Affine
        from common import ORIGIN_EASTING, ORIGIN_NORTHING
        tf = Affine(1.0, 0.0, ORIGIN_EASTING - 40.0, 0.0, -1.0, ORIGIN_NORTHING + 40.0)
        ground = np.zeros((80, 80), dtype=np.float32)

        def strip(key, xz, y, order):
            n = len(xz)
            return {"key": key, "order": order, "xz": np.asarray(xz, dtype=float), "y": np.asarray(y, dtype=float),
                    "hw": np.full(n, 4.0), "extra": np.zeros(n), "camber": np.ones(n), "sta": np.arange(n) * 0.5}
        t = np.arange(-30.0, 30.01, 0.5)
        flat_major = strip("M", np.column_stack([t, 0 * t]), 5.0 + 0 * t, 2)
        side = t[t >= 0]
        steep_minor = strip("m", np.column_stack([0 * side, side]), 5.0 + 0.10 * side, 1)
        out = bh.road_conform(ground, tf, 80, 80, [steep_minor, flat_major],
                              [{"node": 1, "x": 0.0, "z": 0.0, "routes": ["M", "m"]}], 0.0)
        surf = rm.Surface.from_grid(out, tf)
        lift = bp.ROAD_SURFACE_M
        on_minor = surf.sample(np.zeros(8), np.arange(2.0, 10.0, 1.0))
        self.assertTrue(np.allclose(on_minor, 5.0 + 0.10 * np.arange(2.0, 10.0, 1.0) - lift, atol=0.02))
        on_major = surf.sample(np.arange(-10.0, 10.0, 2.0), np.zeros(10))
        self.assertTrue(np.allclose(on_major, 5.0 - lift, atol=0.02))
        # inside the junction (rows are z + 40, columns x + 40) the 10% side street warps into the
        # flat crown without the step the last-painted surface would leave
        def worst_step(a):
            box = a[37:49, 37:44]
            return max(np.abs(np.diff(box, axis=0)).max(), np.abs(np.diff(box, axis=1)).max())
        overwritten = bh.road_conform(ground, tf, 80, 80, [steep_minor, flat_major], [], 0.0)
        self.assertLess(worst_step(out), 0.25)
        self.assertGreater(worst_step(overwritten), 0.4)


GAME_PROFILES = os.path.join(rm.pc.GAME_DATA, "profiles.json")


@unittest.skipUnless(os.path.exists(GAME_PROFILES), "no profiles.json")
class BuiltNetwork(unittest.TestCase):
    """The committed design: composed decks and junctions are held."""

    def test_composed_deck_ends_and_junctions_are_held(self):
        with open(GAME_PROFILES) as handle:
            doc = json.load(handle)
        designs = bp.composed_designs()
        held = 0
        for rid, rd in doc["routes"].items():
            p = vt.Profile.from_json(rd["pvis"])
            for be in rd.get("bridge_ends", []):
                rows = sorted(designs[be["bridge"]]["deck"]["elevation"], key=lambda r: r[0])
                ends = {rows[0][1], rows[-1][1]}
                y = float(p.elevation([be["sta"]])[0])
                self.assertLess(min(abs(y - e) for e in ends), 0.02, f"{rid} at deck {be['bridge']}")
                held += 1
        self.assertGreaterEqual(held, 4)
        report_path = bp.REPORT_PATH
        if os.path.exists(report_path):
            with open(report_path) as handle:
                report = json.load(handle)
            self.assertLess(report["junction_tie_miss_m"]["max"], 0.005)
            self.assertEqual(report["conflicts"], [])


if __name__ == "__main__":
    unittest.main()
