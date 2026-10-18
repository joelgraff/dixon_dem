"""Roads and rails are built only over the 1 m play heightmap, cut exactly at its edge.

Run with: ../../.venv/bin/python test_play_bounds.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_road_plan import VALID_BOUNDS, clip_ways_to_bounds, in_bounds  # noqa: E402


class ClipToPlayHeightmapTests(unittest.TestCase):
    @staticmethod
    def vert(x, z, node=None):
        return {"x": float(x), "y": x / 10.0, "z": float(z), "node_id": node}

    def test_bounds_are_the_play_heightmap(self):
        self.assertEqual(VALID_BOUNDS, (0.0, -2700.0, 2699.0, -1.0))

    def test_way_leaving_and_reentering_is_cut_at_the_edge(self):
        v = self.vert
        way = {"id": 7, "tags": {}, "vertices": [v(-100, -10, 1), v(50, -10, 2), v(2800, -10, 3),
                                                 v(2800, -50, 4), v(100, -50, 5)]}
        pieces = clip_ways_to_bounds([way])
        self.assertEqual([p["id"] for p in pieces], [700, 701])
        first, second = pieces[0]["vertices"], pieces[1]["vertices"]
        self.assertEqual((first[0]["x"], first[0]["node_id"]), (0.0, None))
        self.assertAlmostEqual(first[0]["y"], 0.0)                 # height interpolated at the cut
        self.assertEqual(first[1]["node_id"], 2)
        self.assertEqual(first[-1]["x"], 2699.0)
        self.assertEqual((second[0]["x"], second[-1]["node_id"]), (2699.0, 5))

    def test_diagonal_corner_cut_stays_inside(self):
        v = self.vert
        pieces = clip_ways_to_bounds([{"id": 1, "tags": {}, "vertices": [v(2650, -50), v(2750, 50)]}])
        self.assertEqual(len(pieces), 1)
        end = pieces[0]["vertices"][-1]
        self.assertTrue(in_bounds(end["x"], end["z"]))
        self.assertAlmostEqual(end["x"], 2699.0)
        self.assertAlmostEqual(end["z"], -1.0)

    def test_outside_way_dropped_and_inside_way_kept(self):
        v = self.vert
        out = {"id": 2, "tags": {}, "vertices": [v(-50, 10), v(-10, 20)]}   # north of the play area
        inside = {"id": 3, "tags": {}, "vertices": [v(10, -10, 1), v(20, -20, 2)]}
        pieces = clip_ways_to_bounds([out, inside])
        self.assertEqual([p["id"] for p in pieces], [300])
        self.assertEqual(pieces[0]["vertices"], inside["vertices"])



if __name__ == "__main__":
    unittest.main()
