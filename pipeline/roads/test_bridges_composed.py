"""A bridge from Bridge Composer builds where the generated deck would, facing the right way."""
import json
import math
import pathlib
import tempfile

import bridges_composed as bc

LINE = [[0.0, 0.0], [60.0, 0.0]]


def design(**over):
    data = {
        "format": "dixon-bridge", "version": 1, "id": "7",
        "centerline": LINE,
        "deck": {"width": 10.0, "thickness": 0.3, "elevation": [[0.0, 5.0], [60.0, 5.0]]},
        "supports": [
            {"kind": "abutment", "station": 0.0},
            {"kind": "pier", "station": 30.0, "length": 1.4, "width": 6.0, "shape": "bullnose"},
            {"kind": "abutment", "station": 60.0},
        ],
        "spans": [{"type": "girder", "depth": 0.9, "haunch": 0.4}, {"type": "girder", "depth": 0.9}],
        "cross_section": {"barrier_h": 0.9, "barrier_w": 0.4, "sidewalk_w": 2.0, "rail_h": 0.5},
        "lamps": {"spacing": 20.0},
    }
    data.update(over)
    return data


def built(data, ground=None):
    meshes, furniture = {}, {}
    result = bc.build(meshes, furniture, data, ground=ground)
    return meshes, furniture, result


def triangles(mb):
    for i in range(0, len(mb.indices), 3):
        yield [mb.verts[j] for j in mb.indices[i:i + 3]]


def test_every_triangle_is_wound_to_face_its_normal():
    # Godot's front face is the clockwise one: the right-handed normal of the triangle
    # points AWAY from the way the face looks. The old deck got this wrong.
    meshes, _f, _r = built(design(spans=[{"type": "arch", "rise": 4.0, "ring": 0.6}, {"type": "girder"}]),
                           ground=lambda x, z: 0.0)
    total = 0
    for name, mb in meshes.items():
        for a, b, c in triangles(mb):
            u = [b[k] - a[k] for k in range(3)]
            v = [c[k] - a[k] for k in range(3)]
            rh = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            n = a[3:6]
            assert rh[0] * n[0] + rh[1] * n[1] + rh[2] * n[2] < 1e-9, (name, a, b, c)
            total += 1
    assert total > 100


def test_deck_top_faces_up_and_sits_at_the_profile():
    meshes, _f, result = built(design())
    tops = [t for t in triangles(meshes["bridge_deck"])]
    assert tops and all(abs(a[1] - 5.0) < 1e-6 and a[4] == 1.0 for a, _b, _c in tops)
    assert result["profile"][0] == [0.0, 5.0] and result["profile"][-1] == [60.0, 5.0]


def test_deck_spans_the_declared_width_about_the_centreline():
    meshes, _f, _r = built(design())
    zs = [v[2] for v in meshes["bridge_deck"].verts]
    assert math.isclose(max(zs) - min(zs), 10.0, abs_tol=1e-6)


def test_a_pier_stands_on_the_ground_and_meets_the_soffit():
    meshes, _f, _r = built(design(), ground=lambda x, z: 0.0)
    structure = meshes["curb_concrete"].verts
    pier = [v for v in structure if 28.0 < v[0] < 32.0 and v[1] < 3.9]
    assert pier and abs(min(v[1] for v in pier) + 0.5) < 1e-6
    assert max(v[1] for v in pier) <= 5.0 - 0.9 - 0.4 + 0.05   # under the haunched soffit


def test_warns_when_the_deck_does_not_meet_the_ground_at_an_end():
    _m, _f, result = built(design(), ground=lambda x, z: 0.0 if x > 30 else 5.0)
    assert any("end" in w and "approach" in w for w in result["warnings"])
    assert not any("start" in w for w in result["warnings"])


def test_arch_intrados_rises_to_the_crown():
    meshes, _f, _r = built(design(spans=[{"type": "arch", "rise": 4.0, "ring": 0.6}, {"type": "arch", "rise": 4.0}]),
                           ground=lambda x, z: 0.0)
    arch = meshes["limestone"].verts
    low = [v[1] for v in arch if v[3:6] == (0.0, -1.0, 0.0) and (v[0] < 1.0 or abs(v[0] - 30.0) < 1.0)]
    crown = [v[1] for v in arch if v[3:6] == (0.0, -1.0, 0.0) and abs(v[0] - 15.0) < 0.1]
    assert crown and low and abs(max(crown) - min(low) - 4.0) < 0.35


def test_lamps_stand_on_both_edges():
    _m, furniture, _r = built(design())
    lamps = furniture["lamp_downtown"]
    assert {round(abs(z), 1) for _x, _y, z, _r in lamps} == {4.8}
    assert len(lamps) % 2 == 0


def test_a_bad_file_is_refused():
    changes = [
        {"format": "other"},
        {"version": 2},
        {"centerline": [[0, 0]]},
        {"spans": [{"type": "girder"}]},
        {"supports": [{"kind": "pier", "station": 0.0}, {"kind": "pier", "station": 60.0}],
         "spans": [{"type": "girder"}]},
        {"materials": {"deck": "unobtainium"}},
        {"deck": {"width": -1, "elevation": [[0, 5]]}},
    ]
    for change in changes:
        try:
            bc.validate(design(**change))
        except bc.BridgeError:
            continue
        raise AssertionError(f"accepted {change}")


def test_load_reads_only_a_composed_bridge():
    tmp = pathlib.Path(tempfile.mkdtemp())
    assert bc.load("7", str(tmp)) is None
    (tmp / "7.json").write_text(json.dumps(design()))
    assert bc.load("7", str(tmp))["id"] == "7"
    (tmp / "8.json").write_text("{nope")
    assert bc.load("8", str(tmp)) is None


def test_the_save_server_takes_only_a_design_for_that_way():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "game", "tools"))
    import composer_server
    tmp = tempfile.mkdtemp()
    body = json.dumps(design()).encode()
    composer_server.save_bridge("7", body, tmp)
    assert json.loads(open(os.path.join(tmp, "7.json")).read())["id"] == "7"
    for bid, payload in (("8", body), ("7", b"{nope"), ("../x", body)):
        try:
            composer_server.save_bridge(bid, payload, tmp)
        except ValueError:
            continue
        raise AssertionError(f"saved {bid}")


def test_the_server_reports_terrain_along_a_bridge():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "game", "tools"))
    import composer_server

    class Slope:
        def at(self, x, z):
            return 10.0 - abs(x - 30.0) * 0.1   # a valley's mirror: highest mid-span

    way = [{"x": 0.0, "z": 0.0}, {"x": 60.0, "z": 0.0}]
    profile = composer_server.ground_profile(way, Slope(), step=10.0)
    assert profile[0] == [0.0, 7.0] and profile[-1] == [60.0, 7.0]
    assert [row[0] for row in profile] == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    assert profile[3][1] == 10.0
    assert composer_server.ground_profile([{"x": 1.0, "z": 1.0}, {"x": 1.0, "z": 1.0}], Slope()) == []


if __name__ == "__main__":
    test_every_triangle_is_wound_to_face_its_normal()
    test_deck_top_faces_up_and_sits_at_the_profile()
    test_deck_spans_the_declared_width_about_the_centreline()
    test_a_pier_stands_on_the_ground_and_meets_the_soffit()
    test_warns_when_the_deck_does_not_meet_the_ground_at_an_end()
    test_arch_intrados_rises_to_the_crown()
    test_lamps_stand_on_both_edges()
    test_a_bad_file_is_refused()
    test_load_reads_only_a_composed_bridge()
    test_the_save_server_takes_only_a_design_for_that_way()
    test_the_server_reports_terrain_along_a_bridge()
    print("bridges_composed ok")
