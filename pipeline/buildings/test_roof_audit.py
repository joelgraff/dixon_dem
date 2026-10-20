"""Open-ground scores of roof_audit.py and the cause encroachment.py --review gives a building."""
import unittest

import numpy as np
from shapely.geometry import box

import encroachment
import roof_audit


class HalfAndHalf:
    """An aerial whose west half (x < 10) is tan dirt and east half olive lawn."""
    @staticmethod
    def sample(xs, zs):
        dirt, lawn = np.array([0.56, 0.52, 0.44]), np.array([0.30, 0.34, 0.20])
        return np.where((np.asarray(xs) < 10.0)[:, None], dirt, lawn)


class Roofs(unittest.TestCase):
    def test_dirt_counts_as_bare_and_lawn_as_lawn(self):
        lawn, bare = roof_audit.ground_shares(HalfAndHalf(), box(0, 0, 20, 10))
        self.assertAlmostEqual(lawn, 0.5, delta=0.05)
        self.assertAlmostEqual(bare, 0.5, delta=0.05)
        self.assertEqual(roof_audit.ground_shares(HalfAndHalf(), box(0, 0, 9, 10)), (0.0, 1.0))

    def test_neutral_grey_and_white_roofs_are_not_bare(self):
        class Roofs:
            sample = staticmethod(lambda xs, zs: np.tile([[0.50, 0.50, 0.49], [0.85, 0.85, 0.84]],
                                                        (len(xs) // 2 + 1, 1))[:len(xs)])
        self.assertEqual(roof_audit.ground_shares(Roofs(), box(0, 0, 20, 10)), (0.0, 0.0))


class Causes(unittest.TestCase):
    def row(self, section, area=20.0, roofless=None):
        return {"on_carriageway_m2": area, "roofless": roofless, "street": {"section": section}}

    def test_causes(self):
        self.assertEqual(encroachment.cause_of(self.row("uncurbed", roofless={"why": "bare"})), "footprint")
        self.assertEqual(encroachment.cause_of(self.row("uncurbed")), "service")
        self.assertEqual(encroachment.cause_of(self.row("residential", roofless={"why": "lawn"})), "footprint")
        self.assertEqual(encroachment.cause_of(self.row("downtown")), "downtown")
        self.assertEqual(encroachment.cause_of(self.row("residential", area=4.0)), "nick")
        self.assertEqual(encroachment.cause_of(self.row("residential", area=0.6)), "eave")
        self.assertEqual(encroachment.cause_of(self.row("residential")), "street")
        hull_only = dict(self.row("uncurbed"), footprint_on_carriageway_m2=0.0)
        self.assertEqual(encroachment.cause_of(hull_only), "hull")


if __name__ == "__main__":
    unittest.main()
