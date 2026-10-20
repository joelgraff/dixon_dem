"""Pinned horizontal geometry: alignment_geom, horizontal_overrides and build_alignments' pins.

Run with: ../../.venv/bin/python test_horizontal.py
"""
import json
import math
import os
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import alignment as al  # noqa: E402
import alignment_geom as geom  # noqa: E402
import build_alignments as ba  # noqa: E402
import horizontal_overrides as ho  # noqa: E402

PIS = [(0, 0), (100, 0), (100, 100), (200, 100)]


class Geometry(unittest.TestCase):
    def test_numpy_free_build_is_the_one_alignment_uses(self):
        radii = [0, 30, 20, 0]
        elements, overlaps, length, pi_sta = geom.build([tuple(map(float, p)) for p in PIS], [float(r) for r in radii])
        a = al.Alignment(PIS, radii)
        self.assertEqual(a.length, length)
        self.assertEqual(a.pi_sta, pi_sta)
        self.assertEqual(overlaps, [])
        self.assertEqual([e["type"] for e in elements], ["tangent", "arc", "tangent", "arc", "tangent"])
        # PI 1's curve: R = 30, delta = 90 degrees
        self.assertAlmostEqual(pi_sta[1][1] - pi_sta[1][0], 30 * math.pi / 2)
        c = geom.curve_data([tuple(map(float, p)) for p in PIS], [0.0, 30.0, 20.0, 0.0], 1)
        self.assertAlmostEqual(c["T"], 30.0)
        self.assertAlmostEqual(c["L"], 30 * math.pi / 2)

    def test_validation_agrees_with_alignment_on_random_chains(self):
        rng = random.Random(4)
        for _ in range(200):
            n = rng.randint(3, 6)
            pts = [[rng.uniform(0, 200), rng.uniform(0, 200)] for _ in range(n)]
            radii = [0.0] + [rng.choice([0, 5, 20, 60, 150]) for _ in range(n - 2)] + [0.0]
            a = al.Alignment(pts, radii)
            try:
                geom.validate(pts, radii)
                ok = True
            except ValueError:
                ok = False
            near_dup = any(math.dist(p, q) < 0.05 for p, q in zip(pts, pts[1:]))
            self.assertEqual(ok, a.valid and not near_dup, (pts, radii))

    def test_validation_refuses_bad_input(self):
        for pis, radii in [([[0, 0]], [0]), ([[0, 0], [1, 1]], [0]), ([[0, 0], [1, 1], [2, 0]], [0, -1, 0]),
                           ([[0, 0], ["a", 1]], [0, 0]), ([[0, 0], [0, 0.01]], [0, 0]),
                           ([[0, 0], [10, 0], [10, 10]], [0, 100, 0]), ([[0, 0], [float("nan"), 1]], [0, 0])]:
            with self.assertRaises(ValueError, msg=str((pis, radii))):
                geom.validate(pis, radii)

    def test_point_at_matches_sampling(self):
        a = al.Alignment(PIS, [0, 30, 20, 0])
        stas, pts, _ = a.sample(1.0)
        for s, p in list(zip(stas, pts))[::17]:
            x, z, _ = geom.point_at(a.elements, a.length, a.pis[-1], s)
            self.assertAlmostEqual(x, p[0], places=6)
            self.assertAlmostEqual(z, p[1], places=6)


    def test_elements_from_json_evaluate_the_same(self):
        a = al.Alignment(PIS, [0, 30, 20, 0])
        els = geom.load_elements(a.to_json()["elements"])
        for s in range(0, int(a.length), 7):
            p, q = a.point_at(s), geom.point_at(els, a.length, a.pis[-1], s)
            self.assertAlmostEqual(p[0], q[0], places=2)
            self.assertAlmostEqual(p[1], q[1], places=2)


class Breaks(unittest.TestCase):
    PIS = [(0, 0), (100, 0), (100.3, 1.4), (200, 1.4)]

    def test_a_break_flags_its_link_and_nothing_else(self):
        a = al.Alignment(self.PIS, [0, 0, 0, 0], breaks=[1])
        flagged = [e for e in a.elements if e.get("break")]
        self.assertEqual(len(flagged), 1)
        self.assertEqual((flagged[0]["start"], flagged[0]["end"]), ((100.0, 0.0), (100.3, 1.4)))
        doc = a.to_json()
        self.assertEqual(doc["breaks"], [1])
        self.assertEqual([e.get("break", False) for e in doc["elements"]], [False, True, False])
        self.assertNotIn("breaks", al.Alignment(self.PIS).to_json())

    def test_breaks_are_validated(self):
        self.assertEqual(geom.validate_breaks([2, 1, 1], [0, 0, 0, 0]), [1, 2])
        for bad in ([3], [-1], ["a"], [True], "x", [1]):
            radii = [0, 20, 0, 0] if bad == [1] else [0, 0, 0, 0]
            with self.assertRaises(ValueError, msg=str(bad)):
                geom.validate_breaks(bad, radii)

    def test_a_pinned_entry_keeps_its_breaks_through_the_build(self):
        e = ho.clean_entry({"route": "R1", "pis": [list(p) for p in self.PIS], "radii": [0, 0, 0, 0], "breaks": [1], "note": "n"})
        self.assertEqual(e["breaks"], [1])
        rec = rec_for([(0, 0), (200, 0)], [(0, 0), (200, 0)], [0, 0])
        ba.apply_pins(rec, [e])
        self.assertEqual(rec["alignment"].breaks, [1])
        # a partial pin among fitted PIs: the break index follows the combined chain
        pts = [(-100, 0), (0, 0), (200, 1.4), (300, 1.4)]
        rec = rec_for(pts, pts, [0, 0, 0, 0])
        e2 = dict(e, sta=[-1, 201], radii=[0, 0, 0, 0])
        ba.apply_pins(rec, [e2])
        a = rec["alignment"]
        i = a.breaks[0]
        self.assertEqual((a.pis[i], a.pis[i + 1]), ((100.0, 0.0), (100.3, 1.4)))


class Overrides(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "o.json")
        with open(self.path, "w") as handle:
            json.dump({"format": "dixon-alignment-overrides", "version": 1, "_about": "x", "profile": [{"route": "R1", "note": "n"}], "templates": []}, handle, indent=2)
            handle.write("\n")
        with open(self.path) as handle:
            self.before = handle.read()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def body(self, **kw):
        base = {"route": "R21838771", "pis": [[0, 0], [50, 0], [50, 40]], "radii": [0, 10, 0], "note": "traced"}
        base.update(kw)
        return base

    def test_the_file_round_trips_unchanged(self):
        ho.save(self.body(), self.path)
        ho.remove("R21838771", self.path)
        with open(self.path) as handle:
            self.assertEqual(handle.read().replace('"horizontal": [],\n  ', ""), self.before)

    def test_save_replaces_the_routes_entry_and_keeps_the_rest(self):
        ho.save(self.body(), self.path)
        ho.save(self.body(radii=[0, 12, 0]), self.path)
        doc = ho.load(self.path)
        self.assertEqual([e["radii"] for e in doc["horizontal"]], [[0, 12, 0]])
        self.assertEqual(list(doc)[:5], ["format", "version", "_about", "horizontal", "profile"])
        self.assertEqual(doc["profile"], [{"route": "R1", "note": "n"}])
        self.assertEqual(ho.remove("R21838771", self.path), 1)
        self.assertEqual(ho.remove("R21838771", self.path), 0)

    def test_bad_requests_are_refused(self):
        for kw in ({"route": "../x"}, {"note": ""}, {"note": 3}, {"radii": [0, -4, 0]}, {"radii": [0, 10]},
                   {"radii": [0, 400, 0]}, {"sta": [5, 1]}, {"sta": "all"}, {"pis": [[0, 0], [0, 0], [3, 3]]}):
            with self.assertRaises(ValueError, msg=str(kw)):
                ho.save(self.body(**kw), self.path)
        with open(self.path) as handle:
            self.assertEqual(handle.read(), self.before)

    def test_end_radii_are_forced_to_zero_on_a_whole_route_only(self):
        e = ho.save(self.body(radii=[7, 10, 7]), self.path)
        self.assertEqual(e["radii"], [0, 10, 0])
        e = ho.save(self.body(radii=[7, 10, 7], sta=[10, 90]), self.path)
        self.assertEqual(e["radii"], [7, 10, 7])


def rec_for(points, fitted_pis, fitted_radii, rid="R1"):
    return {"id": rid, "points": np.array(points, dtype=float), "alignment": al.Alignment(fitted_pis, fitted_radii),
            "names": [], "fit": {}}


class Pins(unittest.TestCase):
    def test_whole_route_pin_replaces_the_fit(self):
        rec = rec_for([(0, 0), (100, 0)], [(0, 0), (100, 0)], [0, 0])
        ba.apply_pins(rec, [{"route": "R1", "pis": [[0, 5], [60, 5], [100, 40]], "radii": [0, 25, 0], "note": "n"}])
        self.assertEqual(rec["alignment"].pis, [(0, 5), (60, 5), (100, 40)])
        self.assertEqual(rec["pinned_ends"], (True, True))
        self.assertEqual(ba.pinned_stretches(rec)[0]["whole"], True)
        self.assertEqual(rec["fit"]["curves"], 1)

    def test_partial_pin_joins_the_fit_tangentially(self):
        # an OSM line along x, 300 m; the fit has a PI at 100 and one at 200 (both angle points)
        pts = [(0, 0), (100, 0), (200, 0), (300, 0)]
        rec = rec_for(pts, pts, [0, 0, 0, 0])
        ba.apply_pins(rec, [{"route": "R1", "sta": [90, 210], "pis": [[100, 0], [150, 20], [200, 0]],
                             "radii": [40, 80, 40], "note": "n"}])
        a = rec["alignment"]
        self.assertEqual(a.pis[0], (0, 0))
        self.assertEqual(a.pis[-1], (300, 0))
        self.assertIn((150, 20), a.pis)
        self.assertTrue(a.valid)
        self.assertEqual(rec["pinned_ends"], (False, False))
        # G1: heading is continuous along the whole line
        _, _, dirs = a.sample(0.25)
        self.assertLess(np.abs(np.diff(dirs, axis=0)).max(), 0.02)
        st = ba.pinned_stretches(rec)[0]
        self.assertFalse(st["whole"])
        self.assertAlmostEqual(st["sta"][0], 100.0 - 40 * math.tan(math.atan2(20, 50) / 2), delta=0.01)
        self.assertEqual(rec["joint_kinks"], [])

    def test_an_angle_point_at_a_joint_is_reported(self):
        pts = [(0, 0), (100, 0), (200, 0), (300, 0)]
        rec = rec_for(pts, pts, [0, 0, 0, 0])
        ba.apply_pins(rec, [{"route": "R1", "sta": [90, 210], "pis": [[100, 0], [150, 20], [200, 0]],
                             "radii": [0, 80, 0], "note": "n"}])
        self.assertEqual([k["pi"] for k in rec["joint_kinks"]], [1, 3])

    def test_partial_pin_shrinks_fitted_neighbours_never_the_pinned_radius(self):
        pts = [(0, 0), (100, 0), (150, 0), (300, 0)]
        rec = rec_for(pts, pts, [0, 60, 0, 0])
        ba.apply_pins(rec, [{"route": "R1", "sta": [120, 300], "pis": [[150, 0], [220, 30], [300, 0]],
                             "radii": [0, 70, 0], "note": "n"}])
        a = rec["alignment"]
        self.assertTrue(a.valid)
        self.assertIn(70.0, a.radii)
        self.assertEqual(rec["pinned_ends"], (False, True))

    def test_pinned_curves_that_overlap_are_an_error(self):
        pts = [(0, 0), (300, 0)]
        rec = rec_for(pts, pts, [0, 0])
        with self.assertRaises(ValueError):
            ba.apply_pins(rec, [{"route": "R1", "sta": [0, 300], "pis": [[0, 0], [100, 0], [100, 10], [200, 10]],
                                 "radii": [0, 90, 90, 0], "note": "n"}])


if __name__ == "__main__":
    unittest.main()
