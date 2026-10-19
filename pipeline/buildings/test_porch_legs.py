"""Porches from a footprint override (Composer's Turn into a porch) are built
along their legs: the whole edge, the given depth, out from the building."""
import random

import archetypes
from common_buildings import MeshBuild

# a 10 x 8 house, counter-clockwise; its front is z = 8
HOUSE = [(0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0)]


def _porch_floor(legs):
    mb = MeshBuild()
    template = {"porch": "shed_full", "porch_legs": legs}
    archetypes._place_porch(mb, template, None, None, ((0.0, 0.0), (1.0, 0.0)), 0.0, random.Random(1), coords=HOUSE)
    return [v for v in mb.groups["stone_foundation"]["verts"]]


def test_a_leg_is_built_along_its_edge_out_from_the_house():
    verts = _porch_floor([{"a": [10, 8], "b": [0, 8], "depth": 2.4, "kind": "shed_full"}])
    xs = [v[0] for v in verts]
    zs = [v[2] for v in verts]
    # the floor spans the whole leg and reaches 2.4 m out past the front
    assert min(xs) <= 0.01 and max(xs) >= 9.99
    assert abs(max(zs) - 10.4) < 0.01
    assert min(zs) >= 8.0 - 0.01


def test_a_leg_written_the_other_way_is_still_built_outside():
    verts = _porch_floor([{"a": [0, 8], "b": [10, 8], "depth": 2.4, "kind": "shed_full"}])
    zs = [v[2] for v in verts]
    assert abs(max(zs) - 10.4) < 0.01
    assert min(zs) >= 8.0 - 0.01


def test_a_wraparound_builds_a_porch_per_leg():
    verts = _porch_floor([
        {"a": [12.4, 8], "b": [0, 8], "depth": 2.4, "kind": "wrap"},
        {"a": [10, 4], "b": [10, 8], "depth": 2.4, "kind": "wrap"},
    ])
    assert max(v[0] for v in verts) >= 12.39
    assert any(abs(v[0] - 12.4) < 0.01 and v[2] < 8.0 for v in verts)


if __name__ == "__main__":
    test_a_leg_is_built_along_its_edge_out_from_the_house()
    test_a_leg_written_the_other_way_is_still_built_outside()
    test_a_wraparound_builds_a_porch_per_leg()
    print("porch legs ok")
