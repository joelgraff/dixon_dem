"""A building from Building Composer goes into the chunk where the generated one would."""
import json
import pathlib
import tempfile

import composed
from common_buildings import MeshBuild

FILE = {
    "format": "dixon-composed", "version": 1, "id": "42", "y0": 0.0, "y1": 6.0,
    "hull": [[0, 0], [10, 0], [10, 8], [0, 8]],
    "near": {
        "siding_white": {
            "verts": [[0, 0, 0, 0, 0, -1, 0, 0, 1, 1, 1, 1], [10, 0, 0, 0, 0, -1, 10, 0, 1, 1, 1, 1], [10, 6, 0, 0, 0, -1, 10, 6, 1, 1, 1, 1]],
            "indices": [0, 1, 2],
        },
        "shingles_dark": {
            "verts": [[0, 6, 0, 0, 1, 0, 0, 0, 1, 1, 1, 1], [10, 6, 0, 0, 1, 0, 10, 0, 1, 1, 1, 1], [10, 6, 8, 0, 1, 0, 10, 8, 1, 1, 1, 1]],
            "indices": [0, 1, 2],
        },
    },
}


def test_load_reads_only_a_composed_file():
    tmp_path = pathlib.Path(tempfile.mkdtemp())
    assert composed.load("42", str(tmp_path)) is None
    (tmp_path / "42.json").write_text(json.dumps(FILE))
    assert composed.load("42", str(tmp_path))["id"] == "42"
    (tmp_path / "43.json").write_text(json.dumps({"format": "something-else"}))
    assert composed.load("43", str(tmp_path)) is None
    (tmp_path / "44.json").write_text("{not json")
    assert composed.load("44", str(tmp_path)) is None


def test_revert_is_an_override():
    assert composed.wanted({})
    assert composed.wanted(None)
    assert not composed.wanted({"composed": False})


def test_build_lifts_heights_to_the_ground_and_reports_the_hull():
    mb, far = MeshBuild(), MeshBuild()
    res = composed.build(mb, far, [(0, 0), (10, 0), (10, 8), (0, 8)], 17.0, FILE)
    assert res["y0"] == 17.0 and res["y1"] == 23.0
    assert len(res["hull"]) == 4
    assert len(mb.groups["siding_white"]["indices"]) == 3
    assert mb.groups["shingles_dark"]["verts"][0][1] == 23.0
    assert far.groups


if __name__ == "__main__":
    test_load_reads_only_a_composed_file()
    test_revert_is_an_override()
    test_build_lifts_heights_to_the_ground_and_reports_the_hull()
    print("composed ok")
