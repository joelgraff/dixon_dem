"""Road profile metrics: the measures themselves, and the ratchet against road_metrics_baseline.json.

Run with: ../../.venv/bin/python test_road_metrics.py
The ratchet fails when the road-conformed heightmap gets worse than the baseline on any held
metric (docs/roadway_control_plan.md, phase 0). When a change improves them, regenerate the
baseline with `road_metrics.py --update-baseline` and commit it with the change.
"""
import json
import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import road_metrics as rm  # noqa: E402


class Analytic:
    """A surface y = f(x, z), NaN where `inside` says there is no data."""

    def __init__(self, f, inside=None):
        self.f, self.inside = f, inside

    def sample(self, xs, zs):
        xs, zs = np.asarray(xs, dtype=float), np.asarray(zs, dtype=float)
        y = self.f(xs, zs).astype(float) + 0 * xs
        return y if self.inside is None else np.where(self.inside(xs, zs), y, np.nan)


LINE = [(0.0, 0.0), (100.0, 0.0)]


class Measures(unittest.TestCase):
    def test_grade_on_a_plane(self):
        ds, xs, zs, g, a = rm.grade_profile(LINE, Analytic(lambda x, z: 0.05 * x))
        self.assertAlmostEqual(float(np.nanmin(g)), 0.05, places=9)
        self.assertAlmostEqual(float(np.nanmax(g)), 0.05, places=9)
        self.assertLess(float(np.nanmax(np.abs(a))), 1e-9)
        self.assertEqual(ds[0], rm.CHORD_M / 2)            # grade reaches half a chord from the ends
        self.assertTrue(np.isnan(a[0]))                    # the change needs a full chord each side

    def test_grade_change_matches_a_vertical_curve(self):
        # y = x^2 / (2 * 100 * K): the grade changes 1% every K metres
        k = 5.0
        _, _, _, _, a = rm.grade_profile(LINE, Analytic(lambda x, z: x * x / (200.0 * k)))
        self.assertAlmostEqual(float(np.nanmedian(a)) * 100.0, rm.CHORD_M / k, places=6)

    def test_crown(self):
        crowned = Analytic(lambda x, z: -0.02 * np.abs(z))
        slopes = rm.cross_slopes(LINE, 3.25, crowned)
        self.assertTrue(np.allclose(slopes, 0.02))
        tilted = rm.cross_slopes(LINE, 3.25, Analytic(lambda x, z: 0.03 * z))
        self.assertTrue((tilted < rm.ADVERSE_CROSS_SLOPE).any())   # one side drains to the centre

    def test_junction_step(self):
        node = {"x": 0.0, "z": 0.0}
        legs = [[(0, 0), (30, 0)], [(0, 0), (-30, 0)], [(0, 0), (0, 30)]]
        plane = Analytic(lambda x, z: 0.04 * x + 0.02 * z)
        self.assertLess(rm.junction_step(node, legs, plane), 1e-9)
        # a 0.3 m step down along one leg, starting a metre from the node
        stepped = Analytic(lambda x, z: np.where(z > 1.0, -0.3, 0.0))
        self.assertAlmostEqual(rm.junction_step(node, legs, stepped), 0.3, places=6)
        # a junction with only one leg long enough is not measured
        self.assertIsNone(rm.junction_step(node, [[(0, 0), (5, 0)], [(0, 0), (30, 0)]], plane))

    def test_leg_paths(self):
        verts = [{"x": 0, "z": 0, "node_id": 1}, {"x": 10, "z": 0, "node_id": 2}, {"x": 20, "z": 0, "node_id": 3}]
        self.assertEqual(rm.leg_paths(verts, 1), [[(0, 0), (10, 0), (20, 0)]])
        self.assertEqual(rm.leg_paths(verts, 2), [[(10, 0), (20, 0)], [(10, 0), (0, 0)]])

    def test_off_the_heightmap_is_not_measured(self):
        half = Analytic(lambda x, z: 0.05 * x, inside=lambda x, z: x <= 50.0)
        _, _, _, g, _ = rm.grade_profile(LINE, half)
        self.assertTrue(np.isnan(g[-1]))
        self.assertAlmostEqual(float(np.nanmax(g)), 0.05, places=9)
        way = {"vertices": [{"x": 0, "z": 0}, {"x": 100, "z": 0}]}
        self.assertAlmostEqual(rm.length_beyond_heightmap([way], half, (-400, -400, 400, 400)), 50.0, delta=2.0)
        self.assertEqual(rm.length_beyond_heightmap([way], half, (-1, -1, 40, 1)), 0.0)

    def test_runs(self):
        self.assertEqual(rm.runs(np.array([0, 1, 1, 0, 1], dtype=bool)), [(1, 3), (4, 5)])

    def test_regressions(self):
        base = {"a": {"p50": 1.0, "max": 10.0}, "b": 100}
        self.assertEqual(rm.regressions(base, base), [])
        self.assertEqual(rm.regressions({"a": {"p50": 0.5, "max": 10.1}, "b": 101}, base), [])  # within tolerance
        worse = rm.regressions({"a": {"p50": 1.2, "max": 9.0}, "b": 100}, base)
        self.assertEqual([w[0] for w in worse], ["a.p50"])
        self.assertEqual(rm.regressions({"a": {"p50": 1.0}, "b": 100}, base), [("a.max", 10.0, None)])

    def test_standards(self):
        std = rm.load_standards()
        self.assertEqual(rm.class_of("residential", std), "local")
        self.assertEqual(rm.class_of("primary", std), "arterial")
        self.assertIsNone(rm.class_of("footway", std))
        seen = [h for c in std["classes"].values() for h in c["osm_highway"]]
        self.assertEqual(len(seen), len(set(seen)), "an OSM class is in two design classes")


HEIGHTMAP = os.path.join(rm.pc.GAME_DATA, "heightmap_play_1m_road_conformed.r32")


@unittest.skipUnless(os.path.exists(HEIGHTMAP) and os.path.exists(rm.BASELINE_PATH), "no heightmap or baseline")
class Ratchet(unittest.TestCase):
    def test_no_metric_worse_than_baseline(self):
        with open(rm.BASELINE_PATH) as handle:
            baseline = json.load(handle)["metrics"]
        current = rm.measure()["metrics"]
        worse = rm.regressions(current, baseline)
        self.assertEqual(worse, [], "road profile got worse than road_metrics_baseline.json: " +
                         "; ".join(f"{k} {b} -> {c}" for k, b, c in worse))


if __name__ == "__main__":
    unittest.main()
