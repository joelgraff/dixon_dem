"""Regression checks for OSM power-network vector export."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_vectors  # noqa: E402
from common import ORIGIN_EASTING, ORIGIN_NORTHING  # noqa: E402


class PowerExportTests(unittest.TestCase):
    def test_clips_overhead_lines_and_excludes_underground_lines(self):
        to_lonlat = Transformer.from_crs("EPSG:26916", "EPSG:4326", always_xy=True)

        def location(easting, northing):
            lon, lat = to_lonlat.transform(easting, northing)
            return {"lon": lon, "lat": lat}

        y = ORIGIN_NORTHING + 50.0
        elements = [
            {
                "type": "way",
                "id": 1,
                "tags": {"power": "line", "cables": "3"},
                "geometry": [location(ORIGIN_EASTING - 10.0, y), location(ORIGIN_EASTING + 110.0, y)],
            },
            {
                "type": "way",
                "id": 2,
                "tags": {"power": "line", "location": "underground"},
                "geometry": [location(ORIGIN_EASTING + 20.0, y), location(ORIGIN_EASTING + 80.0, y)],
            },
            {
                "type": "node",
                "id": 3,
                "tags": {"power": "pole"},
                **location(ORIGIN_EASTING + 50.0, y),
            },
            {
                "type": "node",
                "id": 4,
                "tags": {"power": "tower"},
                **location(ORIGIN_EASTING - 50.0, y),
            },
        ]

        with tempfile.TemporaryDirectory() as output_dir:
            with (
                patch.object(build_vectors, "load_osm", return_value=elements),
                patch.object(build_vectors, "sample_y", return_value=7.0),
                patch.object(build_vectors, "GAME_DATA", output_dir),
            ):
                build_vectors.WORLD_ORIGIN = {"size_m": 100.0}
                build_vectors.build_power(None, None)
            output = json.loads((Path(output_dir) / "power.json").read_text())

        self.assertEqual(len(output["lines"]), 1)
        line = output["lines"][0]
        self.assertEqual(line["cables"], "3")
        self.assertEqual([vertex["x"] for vertex in line["vertices"]], [0.0, 100.0])
        self.assertEqual(len(output["supports"]), 1)
        self.assertEqual(output["supports"][0]["kind"], "pole")


if __name__ == "__main__":
    unittest.main()
