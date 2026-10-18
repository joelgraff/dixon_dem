"""pixel_from_world must match what the image server actually returns.

Run with: ../../.venv/bin/python test_georef_affine.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from georef_affine import pixel_mapping  # noqa: E402


class PixelMapping(unittest.TestCase):
    def tile(self):
        return {"world_x0": 0.0, "world_z0": 0.0, "world_x1": 100.0, "world_z1": 100.0,
                "size_px": [1000, 1000], "mpp": 0.1}

    def test_short_side_is_widened_about_its_centre(self):
        # Mercator box 100 wide by 90 high, asked for as a square image: the server returns
        # 100 x 100, centred, so z = 0 (my = 0) is 5 m below the top edge, not on it
        merc = lambda x, z: (x, -0.9 * z)
        (a, b, c, d, e, f), residual = pixel_mapping(self.tile(), merc)
        self.assertAlmostEqual(d * 0 + e * 0 + f, 50.0, places=6)        # 5 m of 100 m = 50 px
        self.assertAlmostEqual(d * 0 + e * 100 + f, 950.0, places=6)
        self.assertAlmostEqual(a * 50 + b * 50 + c, 500.0, places=6)     # the centre stays put
        self.assertLess(residual, 1e-9)

    def test_square_request_is_unchanged(self):
        merc = lambda x, z: (x, -z)
        (a, b, c, d, e, f), _ = pixel_mapping(self.tile(), merc)
        self.assertAlmostEqual(c, 0.0, places=6)
        self.assertAlmostEqual(f, 0.0, places=6)
        self.assertAlmostEqual(a, 10.0, places=6)


if __name__ == "__main__":
    unittest.main()
