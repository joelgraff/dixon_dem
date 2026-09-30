"""Resolver cases from the template plan. Run from pipeline/buildings:

    ../../.venv/bin/python test_templates.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import templates


def rect(x0, z0, x1, z1):
    return [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]


def check(name, condition, detail=""):
    if condition:
        print(f"  ok  {name}")
        return
    print(f"FAIL  {name}  {detail}")
    raise SystemExit(1)


def main():
    # Nearly square, on the residential edge, no measured height: a foursquare,
    # not a one-storey guess from the 5.5 m OSM fallback.
    square = templates.resolve_template(
        rect(0, 0, 12, 12),
        tags={"building": "yes"},
        bid=1,
        height_m=5.5,
        residential_edge=True,
        front_hint=(0, 1),
    )
    check("square is foursquare", square["form"] == "foursquare", square)
    check("square default is two storeys", square["storeys"] == 2, square)
    check("square ignores invented height", square["height_reason"] is None, square)
    check("square porch is full width", square["porch"] == "shed_full", square)

    # Long street frontage, measured one storey: a ranch, ridge along the street.
    ranch = templates.resolve_template(
        rect(0, 0, 22, 8),
        tags={"building": "yes"},
        bid=2,
        height_m=4.2,
        source="ms",
        front_hint=(0, 1),
    )
    check("long bar is a ranch", ranch["form"] == "ranch", ranch)
    check("ranch is one storey", ranch["storeys"] == 1, ranch)
    check("ranch used the microsoft height", ranch["height_reason"] == "ms_height", ranch)

    # Narrow lot, short side to the street. Depth runs away from the road.
    narrow = templates.resolve_template(
        rect(0, 0, 8, 16),
        tags={"building": "yes", "levels": "2"},
        bid=3,
        front_hint=(0, 1),
    )
    check("deep lot is front-gable", narrow["form"] == "front_gable", narrow)
    check("levels tag is two storeys", narrow["storeys"] == 2, narrow)
    check("levels are evidence", narrow["height_reason"] == "levels", narrow)
    check("front-gable ridge faces the street", narrow["roof_axis"] == "front", narrow)

    # Same footprint with only the invented OSM height must not become one storey.
    invented = templates.resolve_template(
        rect(0, 0, 8, 16),
        tags={"building": "yes"},
        bid=4,
        height_m=5.5,
        front_hint=(0, 1),
    )
    check("invented height is not evidence", invented["height_reason"] is None, invented)
    check("missing height keeps the form default", invented["storeys"] == 1.5, invented)
    check("missing height is still front-gable", invented["form"] == "front_gable", invented)

    # Half a metre of extra depth is still a square cottage, not a front-gable.
    almost = templates.resolve_template(
        rect(0, 0, 8.71, 9.18),
        tags={"building": "yes"},
        bid=41,
        front_hint=(0, 1),
    )
    check("near-square is not a front-gable", almost["form"] != "front_gable", almost)

    # L opening toward the south-east. Street is south of the lot (front_hint +z).
    # The missing corner is the north-east, so from the street the wing is on the left.
    ell_ring = [(0, 0), (12, 0), (12, 5), (5, 5), (5, 12), (0, 12)]
    ell = templates.resolve_template(ell_ring, tags={"building": "house"}, bid=5, front_hint=(0, 1))
    check("L is a gabled ell", ell["form"] == "gabled_ell", ell)
    check("ell wing is on the viewer's left", ell["wing"] == "left", ell)
    check("ell confidence is high", ell["form_confidence"] == "high", ell)
    check("ell porch sits in the corner", ell["porch"] == "ell_corner", ell)

    # Street-facing ell: the missing corner is the front yard, and the wing
    # is still the other side, not the rear.
    front_ell = [(0, 0), (16, 0), (16, 8), (6, 8), (6, 16), (0, 16)]
    faced = templates.resolve_template(front_ell, tags={"building": "house"}, bid=51, front_hint=(0, 1))
    check("front-corner ell wing stays on the left", faced["form"] == "gabled_ell" and faced["wing"] == "left", faced)

    court = [(0, 0), (20, 0), (20, 16), (14, 16), (14, 8), (6, 8), (6, 16), (0, 16)]
    cupped = templates.resolve_template(court, tags={"building": "yes"}, bid=52, front_hint=(0, 1))
    check("front court is not an ell", cupped["form"] != "gabled_ell", cupped)

    # Two storefronts 0.3 m apart along a 14 m party wall.
    left = rect(0, 0, 10, 14)
    right = rect(10.3, 0, 20, 14)
    party = templates.resolve_template(
        left, tags={"building": "yes"}, bid=6, neighbors=[right], front_hint=(0, 1),
    )
    check("shared wall is party-wall commercial", party["form"] == "party_wall_commercial", party)
    check("party wall defaults to two storeys", party["storeys"] == 2, party)
    check("party wall is brick", party["material"] == "brick", party)

    # A garage touching a house along 5 m is not a commercial block.
    shed = rect(0, 0, 5, 6)
    house = rect(5.2, 0, 15, 12)
    small = templates.resolve_template(shed, tags={"building": "yes"}, bid=7, neighbors=[house])
    check("short contact stays an outbuilding", small["form"] == "garage", small)

    # 5 m of wall across a 0.4 m gap must not become a party-wall store.
    grazed = templates.resolve_template(
        rect(0, 0, 12, 10),
        tags={"building": "yes"},
        bid=71,
        neighbors=[rect(12.4, 0, 22, 5)],
        front_hint=(0, 1),
    )
    check("a 5 m contact stays a house", grazed["form"] != "party_wall_commercial", grazed)

    # Detached house-sized footprint inside the downtown box stays a house.
    in_town = templates.resolve_template(
        rect(0, 0, 10, 12),
        tags={"building": "yes"},
        bid=8,
        in_downtown=True,
        front_hint=(0, 1),
    )
    check("small downtown footprint stays a house", in_town["form"] in (
        "front_gable", "side_gable", "foursquare", "bungalow", "gabled_ell",
    ), in_town)

    # A large downtown footprint with no house shape is commercial even when detached.
    block = templates.resolve_template(
        rect(0, 0, 10, 40),
        tags={"building": "yes"},
        bid=9,
        in_downtown=True,
        front_hint=(1, 0),
    )
    check("large downtown footprint is commercial", block["form"] == "party_wall_commercial", block)

    big_ell = [(0, 0), (30, 0), (30, 10), (12, 10), (12, 28), (0, 28)]
    kept = templates.resolve_template(
        big_ell, tags={"building": "house"}, bid=91, in_downtown=True, front_hint=(0, 1),
    )
    check("a downtown ell stays a house", kept["form"] == "gabled_ell", kept)

    tall = templates.resolve_template(
        rect(0, 0, 8, 16),
        tags={"building": "yes"},
        bid=92,
        height_m=15.0,
        source="ms",
        front_hint=(0, 1),
    )
    check("a 15 m house is not a cottage", tall["form"] == "civic_block", tall)

    downtown_house = templates.resolve_template(
        rect(0, 0, 8, 16),
        tags={"building": "yes"},
        bid=93,
        height_m=11.0,
        source="ms",
        in_downtown=True,
        front_hint=(0, 1),
    )
    check("downtown house height stays 2.5 storeys", downtown_house["storeys"] == 2.5, downtown_house)
    check("downtown house is still a house", downtown_house["form"] == "front_gable", downtown_house)

    church = templates.resolve_template(
        rect(0, 0, 16, 30),
        tags={"building": "church"},
        bid=10,
        in_downtown=True,
    )
    check("church tag wins over the downtown prior", church["form"] == "church_nave", church)
    check("church ridge faces the street", church["roof_axis"] == "front", church)

    overridden = templates.resolve_template(
        rect(0, 0, 12, 12),
        tags={"building": "yes"},
        bid=11,
        residential_edge=True,
        override={"form": "ranch"},
    )
    check("override replaces the form", overridden["form"] == "ranch", overridden)
    check("override is marked as the user", overridden["source"] == "override" and overridden["reason"] == "user", overridden)
    check("override form brings its own storeys", overridden["storeys"] == 1, overridden)
    flipped = templates.resolve_template(
        rect(0, 0, 12, 12), tags={"building": "yes"}, bid=12,
        override={"flip_normals": True},
    )
    check("flip normals is an override flag", flipped["flip_normals"] is True, flipped)

    print("templates: all checks passed")
    _check_houses()


def _check_houses():
    import archetypes
    from common_buildings import MeshBuild, rng_for

    road = (0.0, 1.0)
    ell = [(0, 0), (12, 0), (12, 5), (5, 5), (5, 12), (0, 12)]
    main, wing = archetypes.ell_bars(ell, road)
    check("ell splits into two bars", main is not None and wing is not None, (main, wing))
    # The wing is the narrow bar. Its street edge should be shorter than the main's.
    def edge(corners):
        return ((corners[1][0] - corners[0][0]) ** 2 + (corners[1][1] - corners[0][1]) ** 2) ** 0.5
    check("ell wing is the narrow bar", edge(wing) < edge(main) - 1.0, (edge(main), edge(wing)))

    court = [(0, 0), (20, 0), (20, 16), (14, 16), (14, 8), (6, 8), (6, 16), (0, 16)]
    _cmain, cwing = archetypes.ell_bars(court, road)
    check("front court stays one bar", cwing is None, cwing)

    forms = [
        ("side_gable", 1.5, "gable", "side", "stoop"),
        ("front_gable", 2, "gable", "front", "stoop"),
        ("foursquare", 2, "pyramidal", "side", "shed_full"),
        ("bungalow", 1.5, "gable", "side", "gable_full"),
        ("ranch", 1, "hip", "side", "stoop"),
        ("gabled_ell", 1.5, "gable", "side", "ell_corner"),
        ("cross_gable", 2, "gable", "front", "wrap"),
    ]
    for form, storeys, roof, axis, porch in forms:
        mb, far = MeshBuild(), MeshBuild()
        tmpl = {
            "form": form, "storeys": storeys, "roof": roof, "roof_axis": axis,
            "porch": porch, "material": "clapboard", "dressing": "plain", "wing": "none",
        }
        ring = ell if form == "gabled_ell" else [(0, 0), (12, 0), (12, 10), (0, 10)]
        if form == "ranch":
            ring = [(0, 0), (22, 0), (22, 8), (0, 8)]
        res = archetypes.build_residential_house(
            mb, far, ring, 20.0, None, {}, rng_for("house", form), 1, None, template=tmpl)
        tris = sum(len(g["indices"]) for g in mb.groups.values())
        check(f"{form} builds", res is not None and tris > 24 and res["y1"] > res["y0"] + 2.0,
              (res, tris))
        if form == "front_gable":
            check("two storeys are taller than a ranch", res["y1"] > 20.0 + 6.0, res)
    print("houses: all checks passed")
    _check_commercial()


def _window_tris(mb):
    group = mb.groups.get("window_lit")
    if not group:
        return 0
    return len(group["indices"])


def _check_commercial():
    import archetypes
    from common_buildings import MeshBuild, rng_for

    def build(fn, **kwargs):
        mb, far = MeshBuild(), MeshBuild()
        res = fn(mb, far, **kwargs)
        return mb, res

    block = [(0, 0), (24, 0), (24, 12), (0, 12)]
    two = {
        "form": "party_wall_commercial", "storeys": 2, "material": "brick",
        "dressing": "italianate", "roof": "flat_parapet", "party_edges": [],
    }
    mb, res = build(
        lambda mb, far, **_k: archetypes.build_downtown_commercial(
            mb, far, block, 20.0, None, {}, rng_for("shop", 2), 2, template=two))
    check("two-storey commercial stays under a third floor",
          res and 20.0 + 8.0 < res["y1"] < 20.0 + 11.0, res)
    five = dict(two)
    five["storeys"] = 5
    five["ground"] = "double"
    five["awnings"] = "none"
    mb5, res5 = build(
        lambda mb, far, **_k: archetypes.build_downtown_commercial(
            mb, far, block, 20.0, None, {}, rng_for("shop", 5), 5, template=five))
    # Double ground (7 m) plus four upper floors (3.5 m) plus a parapet.
    check("five storeys with a tall first floor",
          res5 and res5["y1"] > 20.0 + 7.0 + 3.5 * 4, res5)
    check("awnings none leaves the storefront bare", "awning" not in mb5.groups, mb5.groups.keys())
    red = dict(two)
    red["color"] = "brick_red"
    mb_red, _res_red = build(
        lambda mb, far, **_k: archetypes.build_downtown_commercial(
            mb, far, block, 20.0, None, {}, rng_for("shop", "red"), 51, template=red))
    check("an explicit color is red brick, not a random pale brick",
          "brick_red" in mb_red.groups and "brick_cream" not in mb_red.groups, mb_red.groups.keys())
    open_windows = _window_tris(mb)

    closed = dict(two)
    closed["party_edges"] = [((0, 0), (24, 0))]
    mb2, res2 = build(
        lambda mb, far, **_k: archetypes.build_downtown_commercial(
            mb, far, block, 20.0, None, {}, rng_for("shop", 2), 2, template=closed))
    check("party wall drops the storefronts on that edge",
          res2 and _window_tris(mb2) < open_windows, (_window_tris(mb2), open_windows))

    one = dict(two)
    one["form"] = "one_story_store"
    one["storeys"] = 1
    one["party_edges"] = []
    _mb3, res3 = build(
        lambda mb, far, **_k: archetypes.build_downtown_commercial(
            mb, far, block, 20.0, None, {}, rng_for("shop", 1), 3, template=one))
    check("one-storey store is shorter than two", res3 and res3["y1"] < res["y1"] - 2.0, (res3, res))

    nave = [(0, 0), (16, 0), (16, 30), (0, 30)]
    church = {"form": "church_nave", "storeys": 1, "material": "brick", "roof": "gable", "roof_axis": "front"}
    _mb4, res4 = build(
        lambda mb, far, **_k: archetypes.build_church(
            mb, far, nave, 20.0, rng_for("church"), None, template=church))
    check("church nave builds without a tower",
          res4 and 20.0 + 8.0 < res4["y1"] < 20.0 + 20.0, res4)
    tower = dict(church)
    tower["tower"] = True
    _mb5, res5 = build(
        lambda mb, far, **_k: archetypes.build_church(
            mb, far, nave, 20.0, rng_for("church"), None, template=tower))
    check("a requested tower rises above the nave", res5 and res5["y1"] > res4["y1"] + 4.0, (res5, res4))

    shed = [(0, 0), (30, 0), (30, 14), (0, 14)]
    mill = {"form": "industrial", "storeys": 1, "material": "brick", "roof": "gable", "party_edges": []}
    _mb6, res6 = build(
        lambda mb, far, **_k: archetypes.build_industrial(
            mb, far, shed, 20.0, rng_for("mill"), None, template=mill))
    check("industrial shed builds", res6 and res6["y1"] > 20.0 + 3.0, res6)

    hall = [(0, 0), (28, 0), (28, 16), (0, 16)]
    civic = {"form": "civic_block", "storeys": 2, "material": "limestone", "party_edges": []}
    _mb7, res7 = build(
        lambda mb, far, **_k: archetypes.build_civic(
            mb, far, hall, 20.0, rng_for("hall"), None, template=civic))
    check("civic block is two storeys and has no awning",
          res7 and res7["y1"] > 20.0 + 7.0 and "awning" not in _mb7.groups, res7)

    italianate = dict(two)
    italianate["dressing"] = "italianate"
    plain_shop = dict(two)
    plain_shop["dressing"] = "commercial_1900"
    mb_i, _ri = build(
        lambda mb, far, **_k: archetypes.build_downtown_commercial(
            mb, far, block, 20.0, None, {}, rng_for("shop", "ita"), 8, template=italianate))
    mb_p, _rp = build(
        lambda mb, far, **_k: archetypes.build_downtown_commercial(
            mb, far, block, 20.0, None, {}, rng_for("shop", "c19"), 9, template=plain_shop))
    trim_i = len(mb_i.groups.get("trim_dark", {}).get("indices", []))
    trim_p = len(mb_p.groups.get("trim_dark", {}).get("indices", []))
    check("italianate cornice has brackets", trim_i > trim_p + 20, (trim_i, trim_p))

    house = [(0, 0), (12, 0), (12, 10), (0, 10)]
    def house_mesh(dressing):
        mb, far = MeshBuild(), MeshBuild()
        tmpl = {
            "form": "bungalow", "storeys": 1.5, "roof": "gable", "roof_axis": "side",
            "porch": "shed_full", "material": "clapboard", "dressing": dressing,
        }
        archetypes.build_residential_house(
            mb, far, house, 20.0, None, {}, rng_for("dress", dressing), 4, None, template=tmpl)
        return mb
    stone_c = len(house_mesh("craftsman").groups.get("stone_foundation", {}).get("indices", []))
    stone_p = len(house_mesh("plain").groups.get("stone_foundation", {}).get("indices", []))
    check("craftsman porch posts stand on piers", stone_c > stone_p, (stone_c, stone_p))
    print("commercial: all checks passed")


if __name__ == "__main__":
    main()
