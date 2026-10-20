"""convex_parts: a concave outline's collision is several convex pieces that cover it and not its notch."""
import unittest

from shapely.geometry import Polygon, box

from build_building_plan import convex_parts

L_SHAPE = [(0, 0), (20, 0), (20, 6), (6, 6), (6, 20), (0, 20)]
U_SHAPE = [(0, 0), (30, 0), (30, 20), (22, 20), (22, 6), (8, 6), (8, 20), (0, 20)]


class Parts(unittest.TestCase):
    def test_convex_outline_is_one_part_as_given(self):
        ring = [(0, 0), (10, 0), (10, 8), (0, 8)]
        self.assertEqual(convex_parts(ring), [ring])

    def check(self, ring):
        outline = Polygon(ring)
        parts = [Polygon(p) for p in convex_parts(ring)]
        self.assertGreater(len(parts), 1)
        for p in parts:
            self.assertAlmostEqual(p.convex_hull.area, p.area, places=4)
        union = parts[0]
        for p in parts[1:]:
            union = union.union(p)
        self.assertAlmostEqual(union.area, outline.area, places=3)
        self.assertLess(union.symmetric_difference(outline).area, 1e-3)
        return union

    def test_l_shape_leaves_its_notch_open(self):
        union = self.check(L_SHAPE)
        self.assertEqual(union.intersection(box(8, 8, 18, 18)).area, 0.0)

    def test_u_shape_leaves_its_court_open(self):
        union = self.check(U_SHAPE)
        self.assertEqual(union.intersection(box(10, 8, 20, 19)).area, 0.0)


if __name__ == "__main__":
    unittest.main()
