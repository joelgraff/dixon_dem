"""OSM road corrections: applied in place, idempotent, heights kept.

Run with: ../.venv/bin/python test_osm_corrections.py
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import osm_corrections  # noqa: E402


def roads():
    return {"ways": [
        {"id": 1, "vertices": [{"x": 0.0, "y": 1.0, "z": 0.0, "node_id": 10},
                               {"x": 100.0, "y": 3.0, "z": 0.0, "node_id": 11},
                               {"x": 200.0, "y": 5.0, "z": 0.0, "node_id": 12}], "tags": {}},
        {"id": 2, "vertices": [{"x": 100.0, "y": 3.0, "z": 0.0, "node_id": 11},
                               {"x": 100.0, "y": 4.0, "z": 100.0, "node_id": 13}], "tags": {}}],
        "junction_nodes": [{"node_id": 11, "x": 100.0, "y": 3.0, "z": 0.0, "way_ids": [1, 2]}]}


CORRECTIONS = {"format": "dixon-osm-corrections", "version": 1,
               "nodes": {"11": {"x": 96.0, "z": 0.0, "note": ""}},
               "ways": {"1": {"between": [12, 11], "points": [[180.0, 2.0], [150.0, 3.0]], "note": ""}}}


class Corrections(unittest.TestCase):
    def test_moves_a_node_in_every_way_and_junction(self):
        data = roads()
        osm_corrections.apply(data, CORRECTIONS)
        self.assertEqual((data["ways"][1]["vertices"][0]["x"], data["ways"][1]["vertices"][0]["y"]), (96.0, 3.0))
        self.assertEqual(data["junction_nodes"][0]["x"], 96.0)

    def test_replaces_the_run_between_two_nodes_in_way_order(self):
        data = roads()
        osm_corrections.apply(data, CORRECTIONS)
        vs = data["ways"][0]["vertices"]
        self.assertEqual([(v["x"], v["z"]) for v in vs],
                         [(0.0, 0.0), (96.0, 0.0), (150.0, 3.0), (180.0, 2.0), (200.0, 0.0)])
        self.assertTrue(3.0 < vs[2]["y"] < vs[3]["y"] < 5.0)        # interpolated between the nodes

    def test_idempotent(self):
        once = roads()
        osm_corrections.apply(once, CORRECTIONS)
        twice = copy.deepcopy(once)
        osm_corrections.apply(twice, CORRECTIONS)
        self.assertEqual(once, twice)

    def test_the_committed_file_loads(self):
        data = osm_corrections.load()
        self.assertEqual(data["format"], "dixon-osm-corrections")
        for rule in data["ways"].values():
            self.assertEqual(len(rule["between"]), 2)


if __name__ == "__main__":
    unittest.main()
