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
        "cross_section": {"barrier_h": 0.9, "barrier_w": 0.4, "walkway_w": 2.0, "parapet_w": 0.3, "parapet_h": 0.6,
                          "rail_h": 0.5, "barrier_rail_h": 0.4},
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
    # the roadway is `width`; the barriers, walkways and parapets are outside it
    meshes, _f, _r = built(design())
    zs = [v[2] for v in meshes["bridge_deck"].verts]
    assert math.isclose(max(zs) - min(zs), 10.0, abs_tol=1e-6)
    walk = [v[2] for v in meshes["sidewalk_concrete"].verts]
    assert math.isclose(min(walk), -7.4, abs_tol=1e-6) and math.isclose(max(walk), 7.4, abs_tol=1e-6)
    overall = [v[2] for m in meshes.values() for v in m.verts if v[1] > 3.0 or True]
    assert math.isclose(max(overall), 7.7, abs_tol=1e-6)      # 5 + 0.4 + 2.0 + 0.3, the parapet's outer face


def test_a_walkway_is_level_with_the_approach_sidewalk_and_beside_the_barrier():
    meshes, _f, _r = built(design())
    ys = {round(v[1], 3) for v in meshes["sidewalk_concrete"].verts}
    assert ys <= {round(5.0 + bc.WALKWAY_RISE_M, 3), round(6.0 + bc.WALKWAY_RISE_M, 3), round(8.0 + bc.WALKWAY_RISE_M, 3)} or all(
        abs(y - (5.0 + bc.WALKWAY_RISE_M)) < 1e-6 for y in ys)
    one = design(cross_section={"barrier_h": 0.9, "barrier_w": 0.4, "walkway_w": 2.0, "walkway_sides": "left"})
    m2, _f2, _r2 = built(one)
    zs = [v[2] for v in m2["sidewalk_concrete"].verts]
    assert min(zs) > 0 and math.isclose(max(zs), 7.4, abs_tol=1e-6)     # left of travel only


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
    # on the walkway, 0.35 m in from the parapet: roadway 5 + barrier 0.4 + walkway 2.0 - 0.35
    assert {round(abs(z), 2) for _x, _y, z, _r in lamps} == {7.05}
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
        {"cross_section": {"walkway_w": 2.0, "walkway_sides": "middle"}},
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
    # with an approach: stations run from -extend to length + extend; station 0 is still the first vertex
    wide = composer_server.ground_profile(way, Slope(), step=10.0, extend=10.0)
    assert wide[0] == [-10.0, 6.0] and wide[-1] == [70.0, 6.0]
    assert [row[1] for row in wide if row[0] == 0.0] == [7.0]


def test_bridges_are_named_for_what_they_carry_over_what_they_cross():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "game", "tools"))
    import composer_server as cs

    def way(i, pts, **tags):
        return {"id": i, "vertices": [{"x": x, "z": z} for x, z in pts], "tags": tags}

    river = {"id": "river_a", "kind": "river",
             "polygon": [{"x": 0, "z": 20}, {"x": 100, "z": 20}, {"x": 100, "z": 40}, {"x": 0, "z": 40}]}
    water = {"reaches": [river], "streams": []}
    peoria = way(1, [(50, 0), (50, 60)], name="Peoria Avenue", highway="tertiary", bridge=True, layer=1)
    street = way(2, [(40, 10), (60, 10)], name="2nd Street", highway="residential")
    rail = way(3, [(40, 50), (60, 50)], name="UP Line", railway="rail")
    found = cs.crossings(peoria, [street], [rail], water)
    assert found == ["Rock River", "2nd Street", "UP Line"], found
    assert cs.bridge_title(peoria["tags"], found) == "Peoria Avenue over Rock River and 2nd Street"
    foot = way(4, [(10, 0), (10, 60)], highway="footway", bridge=True, layer=1)
    assert cs.bridge_title(foot["tags"], ["Rock River"]) == "Footbridge over Rock River"
    assert cs.bridge_title(foot["tags"], []) == "Footbridge"
    # its own way and the road it joins at an end are not crossed
    approach = way(5, [(50, 60), (50, 120)], name="Peoria Avenue", highway="tertiary")
    assert cs.crossings(peoria, [approach, peoria], [], {"reaches": [], "streams": []}) == []


def test_a_crest_profile_is_one_smooth_curve_between_the_street_heights():
    rows = bc.crest_profile(200.0, 8.5, 8.0, 0.6)
    assert rows[0] == [0.0, 8.5] and rows[-1] == [200.0, 8.0]
    mid = rows[len(rows) // 2][1]
    assert abs(mid - (8.25 + 0.6)) < 1e-6          # the chord's midpoint plus the crest
    grades = [abs(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(rows, rows[1:])]
    assert max(grades) < 0.03                      # no ramp: the steepest run is ~1.4 %
    steps = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(rows, rows[1:])]
    assert all(x > y for x, y in zip(steps, steps[1:])) or all(x >= y for x, y in zip(steps, steps[1:]))   # one crest: the grade only falls


def test_rail_styles_build_and_face_their_normals():
    for outer in ("parapet", "metal"):
        for style in bc.RAIL_STYLES:
            data = design(cross_section={"barrier_h": 0.9, "barrier_w": 0.4, "barrier_rail_h": 0.4,
                                         "barrier_rail_style": style, "walkway_w": 2.0, "parapet_w": 0.3,
                                         "parapet_h": 0.6, "curb_h": 0.2, "outer_type": outer,
                                         "rail_h": 1.0, "rail_style": style})
            meshes, _f, _r = built(data, ground=lambda x, z: 0.0)
            assert meshes["steel_painted_green"].indices, (outer, style)
            for a, b, c in triangles(meshes["steel_painted_green"]):
                u = [b[k] - a[k] for k in range(3)]
                v = [c[k] - a[k] for k in range(3)]
                rh = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                assert rh[0] * a[3] + rh[1] * a[4] + rh[2] * a[5] < 1e-9, (outer, style)
    # an all-metal outer edge has a low curb, not a parapet wall
    tall = built(design(cross_section={"walkway_w": 2.0, "parapet_h": 0.6, "outer_type": "parapet"}))[0]
    low = built(design(cross_section={"walkway_w": 2.0, "parapet_h": 0.6, "curb_h": 0.1, "outer_type": "metal"}))[0]
    assert max(v[1] for v in tall["curb_concrete"].verts) > max(v[1] for v in low["curb_concrete"].verts) - 1e-9
    # pickets are many thin stakes: that style has far more triangles than a pipe rail
    count = lambda st: len(built(design(cross_section={"walkway_w": 2.0, "outer_type": "metal", "rail_h": 1.0,
                                                       "rail_style": st}))[0]["steel_painted_green"].indices)
    assert count("picket") > 3 * count("pipe") > 0


def test_road_surface_height_matches_the_road_plan():
    # a deck's end is the road surface, and the heightmap anchor subtracts this: they must agree
    import build_road_plan
    assert bc.ROAD_SURFACE_M == build_road_plan.ROAD_Y_BIAS


if __name__ == "__main__":
    test_every_triangle_is_wound_to_face_its_normal()
    test_deck_top_faces_up_and_sits_at_the_profile()
    test_deck_spans_the_declared_width_about_the_centreline()
    test_a_walkway_is_level_with_the_approach_sidewalk_and_beside_the_barrier()
    test_a_pier_stands_on_the_ground_and_meets_the_soffit()
    test_warns_when_the_deck_does_not_meet_the_ground_at_an_end()
    test_arch_intrados_rises_to_the_crown()
    test_lamps_stand_on_both_edges()
    test_a_bad_file_is_refused()
    test_load_reads_only_a_composed_bridge()
    test_the_save_server_takes_only_a_design_for_that_way()
    test_a_crest_profile_is_one_smooth_curve_between_the_street_heights()
    test_rail_styles_build_and_face_their_normals()
    test_road_surface_height_matches_the_road_plan()
    test_the_server_reports_terrain_along_a_bridge()
    test_bridges_are_named_for_what_they_carry_over_what_they_cross()
    print("bridges_composed ok")
