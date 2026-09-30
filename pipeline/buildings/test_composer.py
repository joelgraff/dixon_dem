"""The composer builds a church and a powerhouse from the same parts."""
import math

from common_buildings import MeshBuild
from composer import build, mutate, preset, summary


def _rect(length, width):
    return [(0.0, 0.0), (length, 0.0), (length, width), (0.0, width)]


def _build(name, length=36.0, width=14.0):
    mb, far = MeshBuild(), MeshBuild()
    record = preset(name)
    build(mb, far, _rect(length, width), 18.0, record)
    return mb, record


def _tris(mb, mat):
    group = mb.groups.get(mat) or {"indices": []}
    return len(group["indices"]) // 3


def _tower_span(mb):
    """Distance between the two tower tops, which sit on the narrow end."""
    verts = [v for g in mb.groups.values() for v in g["verts"]]
    top = max(verts, key=lambda v: v[1])
    other = max(
        (v for v in verts if abs(v[0] - top[0]) < 8.0 and abs(v[2] - top[2]) > 6.0),
        key=lambda v: v[1],
    )
    return math.hypot(top[0] - other[0], top[2] - other[2])


def test_church_and_powerhouse_share_arches_and_differ_in_mass():
    church, _c = _build("church")
    plant, _p = _build("powerhouse")
    assert _tris(church, "window_lit") > 10
    assert _tris(plant, "window_lit") > _tris(church, "window_lit")
    assert "shingles_dark" in church.groups
    assert "roof_membrane" in plant.groups
    assert "shingles_dark" not in plant.groups


def test_towers_stand_on_the_narrow_end():
    church, _c = _build("church", length=40.0, width=14.0)
    gap = _tower_span(church)
    assert 8.0 < gap < 16.0, gap


def test_storey_height_follows_the_window():
    record = preset("powerhouse")
    story = record["volumes"][0]["storeys"][0]
    before = story["window_h"]
    assert before > 4.0
    record = mutate(record, "window_h", 1)
    assert record["volumes"][0]["storeys"][0]["window_h"] == round(before + 0.2, 2)


def test_second_volume_and_bay_count():
    record = mutate(preset("block"), "volumes", 1)
    assert len(record["volumes"]) == 2
    assert record["volumes"][1]["roof"] == "shed"
    record = mutate(record, "bays", 1)
    assert record["volumes"][0]["storeys"][0]["bays"] == 5
    labels = dict(summary(record))
    assert labels["volumes"] == 2
    assert labels["rear"] == "shed"


def test_too_many_windows_shrink_instead_of_overlapping():
    from composer import _slots
    _centers, width = _slots(12.0, 8, 3, 2.0, 0.3, 0.9, 0.8)
    assert width < 2.0
    assert width >= 0.35


if __name__ == "__main__":
    test_church_and_powerhouse_share_arches_and_differ_in_mass()
    test_towers_stand_on_the_narrow_end()
    test_storey_height_follows_the_window()
    test_second_volume_and_bay_count()
    test_too_many_windows_shrink_instead_of_overlapping()
    print("composer ok")
