"""One building, composed from shared parts.

A compose record is volumes, storeys, opening arrays, and anchors. Style is
only which preset fills that record in. The mesh is boxes, wall panels, and
the window primitive already used by the rest of the city. Openings are drawn
on the wall. They are not cut out of it.

Coordinates are Godot local metres: x east, z south, y up.
"""
import math

from common_buildings import MeshBuild, ensure_ccw, min_rotated_rect
from facade import (
    WHITE, build_gable_roof, door_unit, edge_dir_normal, far_box, flat_roof_cap,
    foundation_band, offset2, perimeter_band, pt3, wall_backdrop, window_unit,
)

COLORS = (
    "brick_red", "brick_buff", "brick_rose", "brick_dark", "brick_cream",
    "limestone", "stone_foundation",
)
ROOFS = ("gable", "flat", "shed")
SHAPES = ("rect", "arch")
FRONTS = ("windows", "blind", "door")
FACES = ("v0", "v1", "u0", "u1")
KNOBS = (
    "preset", "face", "roof", "storeys", "shape", "bays", "per_bay",
    "window_h", "window_w", "upper_h", "front", "color", "volumes",
    "rear", "towers", "belfry",
)


def _rect_frame(coords):
    ext, _center, _width, _length, _yaw = min_rotated_rect(coords)
    ext = ensure_ccw(ext)
    e0 = math.hypot(ext[1][0] - ext[0][0], ext[1][1] - ext[0][1])
    e1 = math.hypot(ext[2][0] - ext[1][0], ext[2][1] - ext[1][1])
    # u runs across the narrow end (the street front). v runs down the long side.
    if e0 >= e1:
        origin = ext[0]
        facade_end, depth_end = ext[3], ext[1]
        short_m, long_m = e1, e0
    else:
        origin = ext[1]
        facade_end, depth_end = ext[0], ext[2]
        short_m, long_m = e0, e1
    u = ((facade_end[0] - origin[0]) / short_m, (facade_end[1] - origin[1]) / short_m)
    v = ((depth_end[0] - origin[0]) / long_m, (depth_end[1] - origin[1]) / long_m)
    return origin, u, v, long_m, short_m  # depth along v, facade along u


def _pt(origin, u, v, su, sv):
    return (origin[0] + u[0] * su + v[0] * sv, origin[1] + u[1] * su + v[1] * sv)


def _corners(origin, u, v, u0, u1, v0, v1):
    return [
        _pt(origin, u, v, u0, v0),
        _pt(origin, u, v, u1, v0),
        _pt(origin, u, v, u1, v1),
        _pt(origin, u, v, u0, v1),
    ]


def _storey(window_h, shape, bays, per_bay, width, front, color, upper=False):
    height = window_h * (0.55 if upper else 1.0)
    return {
        "sill": 0.55 if upper else 0.9,
        "window_h": round(height, 2),
        "headroom": 0.7 if upper else 1.05,
        "shape": shape,
        "width": width,
        "bays": bays,
        "per_bay": per_bay,
        "front": front,
        "color": color,
    }


def preset(name):
    """Starting compose record. Knobs edit this. They do not invent a new schema."""
    name = name if name in ("church", "powerhouse", "block") else "block"
    if name == "church":
        # 111 E 2nd: red nave, tall round arches, two pyramidal towers, low rear wing.
        nave = _storey(3.8, "arch", 6, 1, 0.95, "windows", "brick_red")
        nave["sill"] = 0.35
        nave["headroom"] = 1.15
        wing = _storey(1.7, "rect", 3, 1, 0.85, "windows", "brick_red")
        return {
            "preset": "church",
            "face": "v0",
            "foundation_h": 1.35,
            "foundation": "limestone",
            "trim": "limestone",
            "roof_mat": "shingles_dark",
            "oculus": True,
            "volumes": [
                {"roof": "gable", "pitch": 42, "u0": 0.0, "u1": 1.0, "v0": 0.0, "v1": 0.66, "storeys": [nave]},
                {"roof": "shed", "pitch": 18, "u0": 0.02, "u1": 0.98, "v0": 0.66, "v1": 1.0, "storeys": [wing]},
            ],
            "towers": "pair",
            "belfry": "right",
            "tower_w": 4.0,
        }
    if name == "powerhouse":
        # 201 E River: one dark brick block, arches in threes, blind arches and a door on the street end.
        bay = _storey(4.4, "arch", 5, 3, 1.35, "door", "brick_red")
        bay["sill"] = 1.5
        bay["headroom"] = 1.35
        return {
            "preset": "powerhouse",
            "face": "v0",
            "foundation_h": 1.6,
            "foundation": "stone_foundation",
            "trim": "limestone",
            "roof_mat": "roof_membrane",
            "oculus": False,
            "volumes": [
                {"roof": "flat", "pitch": 0, "u0": 0.0, "u1": 1.0, "v0": 0.0, "v1": 1.0, "storeys": [bay]},
            ],
            "towers": "none",
            "belfry": "off",
            "tower_w": 3.2,
        }
    lower = _storey(2.6, "rect", 4, 1, 1.15, "windows", "brick_buff")
    upper = _storey(2.6, "rect", 4, 1, 1.05, "windows", "brick_buff", upper=True)
    return {
        "preset": "block",
        "face": "v0",
        "foundation_h": 0.6,
        "foundation": "stone_foundation",
        "trim": "limestone",
        "roof_mat": "roof_membrane",
        "oculus": False,
        "volumes": [
            {"roof": "flat", "pitch": 0, "u0": 0.0, "u1": 1.0, "v0": 0.0, "v1": 1.0, "storeys": [lower, upper]},
        ],
        "towers": "none",
        "belfry": "off",
        "tower_w": 3.2,
    }


def _main(compose):
    return compose["volumes"][0]


def _story(compose, upper=False):
    stories = _main(compose)["storeys"]
    if upper and len(stories) > 1:
        return stories[1]
    return stories[0]


def _cycle(value, choices, direction):
    if value not in choices:
        return choices[0]
    return choices[(choices.index(value) + direction) % len(choices)]


def _bump(value, step, lo, hi, direction):
    return round(min(hi, max(lo, float(value) + step * direction)), 2)


def mutate(compose, key, direction):
    """Move one knob. Returns the same record, edited in place and returned."""
    direction = 1 if direction >= 0 else -1
    compose = compose or preset("block")
    if key == "preset":
        return preset(_cycle(compose.get("preset", "block"), ("church", "powerhouse", "block"), direction))
    if key == "face":
        compose["face"] = _cycle(compose.get("face", "v0"), FACES, direction)
    elif key == "roof":
        _main(compose)["roof"] = _cycle(_main(compose).get("roof", "gable"), ROOFS, direction)
    elif key == "storeys":
        stories = _main(compose)["storeys"]
        if direction > 0 and len(stories) == 1:
            stories.append(_storey(stories[0]["window_h"], stories[0]["shape"], stories[0]["bays"],
                                    stories[0]["per_bay"], stories[0]["width"], stories[0]["front"],
                                    stories[0]["color"], upper=True))
        elif direction < 0 and len(stories) > 1:
            del stories[1:]
    elif key == "shape":
        shape = _cycle(_story(compose).get("shape", "rect"), SHAPES, direction)
        for story in _main(compose)["storeys"]:
            story["shape"] = shape
    elif key == "bays":
        _story(compose)["bays"] = int(_bump(_story(compose).get("bays", 4), 1, 1, 8, direction))
    elif key == "per_bay":
        _story(compose)["per_bay"] = int(_bump(_story(compose).get("per_bay", 1), 1, 1, 4, direction))
    elif key == "window_h":
        _story(compose)["window_h"] = _bump(_story(compose).get("window_h", 2.4), 0.2, 0.8, 6.0, direction)
    elif key == "window_w":
        _story(compose)["width"] = _bump(_story(compose).get("width", 1.0), 0.1, 0.4, 2.4, direction)
    elif key == "upper_h" and len(_main(compose)["storeys"]) > 1:
        _story(compose, upper=True)["window_h"] = _bump(
            _story(compose, upper=True).get("window_h", 1.6), 0.2, 0.6, 4.0, direction)
    elif key == "front":
        _story(compose)["front"] = _cycle(_story(compose).get("front", "windows"), FRONTS, direction)
    elif key == "color":
        color = _cycle(_story(compose).get("color", "brick_red"), COLORS, direction)
        for story in _main(compose)["storeys"]:
            story["color"] = color
    elif key == "volumes":
        vols = compose["volumes"]
        if direction > 0 and len(vols) == 1:
            main = vols[0]
            cut = 0.66
            main["v1"] = cut
            wing_story = _storey(1.6, "rect", 3, 1, 0.8, "windows", _story(compose)["color"])
            vols.append({"roof": "shed", "pitch": 18, "u0": 0.02, "u1": 0.98, "v0": cut, "v1": 1.0, "storeys": [wing_story]})
        elif direction < 0 and len(vols) > 1:
            vols[0]["v1"] = 1.0
            del vols[1:]
    elif key == "rear" and len(compose["volumes"]) > 1:
        compose["volumes"][1]["roof"] = _cycle(compose["volumes"][1].get("roof", "shed"), ("shed", "flat", "gable"), direction)
    elif key == "towers":
        compose["towers"] = _cycle(compose.get("towers", "none"), ("none", "pair"), direction)
    elif key == "belfry":
        compose["belfry"] = _cycle(compose.get("belfry", "off"), ("off", "right", "left"), direction)
    return compose


def summary(compose):
    main = _main(compose)
    story = _story(compose)
    upper = _story(compose, upper=True) if len(main["storeys"]) > 1 else None
    rear = compose["volumes"][1]["roof"] if len(compose["volumes"]) > 1 else "none"
    return [
        ("preset", compose.get("preset", "block")),
        ("face", compose.get("face", "v0")),
        ("roof", main.get("roof", "gable")),
        ("storeys", len(main["storeys"])),
        ("shape", story.get("shape", "rect")),
        ("bays", story.get("bays", 1)),
        ("per_bay", story.get("per_bay", 1)),
        ("window_h", story.get("window_h", 0)),
        ("window_w", story.get("width", 0)),
        ("upper_h", upper.get("window_h") if upper else "-"),
        ("front", story.get("front", "windows")),
        ("color", story.get("color", "brick_red")),
        ("volumes", len(compose["volumes"])),
        ("rear", rear),
        ("towers", compose.get("towers", "none")),
        ("belfry", compose.get("belfry", "off")),
    ]


def _orient(origin, u, v, depth_m, facade_m, face):
    """Turn the frame so the named side sits at v=0, the street end.

    u spans the facade (facade_m). v runs back into the lot (depth_m).
    """
    if face == "v1":
        origin = _pt(origin, u, v, 0.0, depth_m)
        v = (-v[0], -v[1])
    elif face == "u0":
        origin = _pt(origin, u, v, 0.0, 0.0)
        u, v = v, (-u[0], -u[1])
        depth_m, facade_m = facade_m, depth_m
    elif face == "u1":
        origin = _pt(origin, u, v, facade_m, 0.0)
        u, v = (-v[0], -v[1]), u
        depth_m, facade_m = facade_m, depth_m
    return origin, u, v, depth_m, facade_m


def _inside(point, corners, margin=0.25):
    """True when point is in the rectangle, inset so a shared wall is not 'inside'."""
    # corners CCW. Use the edge normals.
    for i in range(4):
        p0, p1 = corners[i], corners[(i + 1) % 4]
        _d, n, _l = edge_dir_normal(p0, p1)
        if (point[0] - p0[0]) * n[0] + (point[1] - p0[1]) * n[1] > -margin:
            return False
    return True


def _fit_width(length, bays, per, width, gap, pier, margin):
    bays = max(1, int(bays))
    per = max(1, int(per))
    usable = max(0.5, length - margin * 2.0)
    gaps = bays * max(0, per - 1) * gap + max(0, bays - 1) * pier
    room = usable - gaps
    fitted = min(width, room / (bays * per))
    return bays, per, max(0.35, fitted)


def _slots(length, bays, per, width, gap, pier, margin):
    bays, per, width = _fit_width(length, bays, per, width, gap, pier, margin)
    bay_w = per * width + max(0, per - 1) * gap
    total = bays * bay_w + max(0, bays - 1) * pier
    cursor = (length - total) * 0.5
    centers = []
    for _b in range(bays):
        x = cursor
        for i in range(per):
            centers.append(x + width * 0.5 + i * (width + gap))
        cursor += bay_w + pier
    return centers, width


def _arch(mb, mat, p0, p1, center, y_spring, radius, color, segments=7):
    d, n, _length = edge_dir_normal(p0, p1)
    cx = p0[0] + d[0] * center
    cz = p0[1] + d[1] * center
    cx, cz = offset2((cx, cz), n, 0.05)
    spring = (cx, y_spring, cz)
    pts = []
    for i in range(segments + 1):
        a = math.pi * i / segments
        px = cx - d[0] * math.cos(a) * radius
        pz = cz - d[1] * math.cos(a) * radius
        py = y_spring + math.sin(a) * radius
        pts.append((px, py, pz))
    normal = (n[0], 0.0, n[1])
    for i in range(segments):
        mb.add_tri_face(mat, spring, pts[i], pts[i + 1], normal=normal, color=color)


def _opening(mb, p0, p1, center, y0, width, height, kind, wall):
    if kind == "door":
        door_unit(mb, p0, p1, center, y0, min(width, 1.4), min(height, 2.6), mat="trim_dark", glass_top=True)
        return
    if kind == "rect":
        window_unit(mb, p0, p1, center, y0, width, height, _Quiet(), lit_prob=0.0, sill_mat="limestone")
        return
    radius = width * 0.5
    body = max(0.45, height - radius)
    if kind == "blind":
        wall_backdrop(mb, wall, *_segment(p0, p1, center, width), y0, y0 + body, offset=0.04)
        _arch(mb, wall, p0, p1, center, y0 + body, radius, WHITE)
        return
    window_unit(mb, p0, p1, center, y0, width, body, _Quiet(), lit_prob=0.0, sill_mat="limestone")
    _arch(mb, "window_lit", p0, p1, center, y0 + body, radius * 0.92, (0.0, 0.2, 0.0, 0.0))
    _arch(mb, "limestone", p0, p1, center, y0 + body, radius, WHITE)


def _segment(p0, p1, center, width):
    d, _n, _l = edge_dir_normal(p0, p1)
    a = (p0[0] + d[0] * (center - width * 0.5), p0[1] + d[1] * (center - width * 0.5))
    b = (p0[0] + d[0] * (center + width * 0.5), p0[1] + d[1] * (center + width * 0.5))
    return a, b


class _Quiet:
    def random(self):
        return 1.0

    def uniform(self, _a, _b):
        return 0.0

    def choice(self, seq):
        return seq[0]


def _role(edge_index, is_main):
    # corners are v0, u1, v1, u0 after _corners(). Edge 0 is the street end (v0).
    if edge_index == 0 and is_main:
        return "front"
    if edge_index == 2:
        return "back"
    return "side"


def _openings_for(role, story, length):
    shape = story.get("shape", "rect")
    front = story.get("front", "windows")
    if role == "front":
        count = max(1, int(story.get("per_bay", 1)))
        kind = shape if front == "windows" else "blind"
        centers, width = _slots(length, 1, count, story.get("width", 1.0), 0.35, 0.8, 0.7)
        kinds = [kind] * len(centers)
        if front == "door" and kinds:
            kinds[-1] = "door"
        return centers, width, kinds
    if role == "back":
        centers, width = _slots(length, max(1, int(story.get("bays", 1)) // 2 or 1), 1,
                                story.get("width", 1.0) * 0.8, 0.4, 0.8, 0.8)
        return centers, width, [shape] * len(centers)
    centers, width = _slots(length, story.get("bays", 4), story.get("per_bay", 1),
                            story.get("width", 1.0), 0.32, 0.9, 0.8)
    return centers, width, [shape] * len(centers)


def _tower(mb, corner, inward_u, inward_v, ground, eave, width, belfry, wall, roof_mat):
    half = width * 0.5
    # Sit on the corner, growing back into the building.
    center = (corner[0] + inward_u[0] * half + inward_v[0] * half,
              corner[1] + inward_u[1] * half + inward_v[1] * half)
    yaw = math.atan2(inward_u[1], inward_u[0])
    shaft_top = eave + (1.2 if not belfry else 2.4)
    mb.add_box(wall, center[0], center[1], ground, shaft_top, width, width, yaw=yaw)
    cap_y = shaft_top
    if belfry:
        cap_y = shaft_top + 3.2
        post = width * 0.18
        for su in (-1, 1):
            for sv in (-1, 1):
                px = center[0] + inward_u[0] * su * (half - post) + inward_v[0] * sv * (half - post)
                pz = center[1] + inward_u[1] * su * (half - post) + inward_v[1] * sv * (half - post)
                mb.add_box("limestone", px, pz, shaft_top, cap_y, post * 2.0, post * 2.0, yaw=yaw)
        mb.add_box(wall, center[0], center[1], cap_y, cap_y + 0.4, width * 1.05, width * 1.05, yaw=yaw)
        cap_y += 0.4
    foot = [
        (center[0] - inward_u[0] * half - inward_v[0] * half, center[1] - inward_u[1] * half - inward_v[1] * half),
        (center[0] + inward_u[0] * half - inward_v[0] * half, center[1] + inward_u[1] * half - inward_v[1] * half),
        (center[0] + inward_u[0] * half + inward_v[0] * half, center[1] + inward_u[1] * half + inward_v[1] * half),
        (center[0] - inward_u[0] * half + inward_v[0] * half, center[1] - inward_u[1] * half + inward_v[1] * half),
    ]
    rise = width * 0.95
    apex = ((foot[0][0] + foot[2][0]) * 0.5, cap_y + rise, (foot[0][1] + foot[2][1]) * 0.5)
    for i in range(4):
        a = pt3(foot[i], cap_y)
        b = pt3(foot[(i + 1) % 4], cap_y)
        mb.add_tri_face(roof_mat, a, b, apex)
    return cap_y + rise


def build(mb, mb_far, coords, ground_y, compose):
    coords = ensure_ccw([(p[0], p[1]) if not isinstance(p, dict) else (p["x"], p["z"]) for p in coords])
    origin, u, v, depth_m, facade_m = _rect_frame(coords)
    origin, u, v, depth_m, facade_m = _orient(origin, u, v, depth_m, facade_m, compose.get("face", "v0"))
    cx = origin[0] + u[0] * facade_m * 0.5 + v[0] * depth_m * 0.5
    cz = origin[1] + u[1] * facade_m * 0.5 + v[1] * depth_m * 0.5
    mb.set_outward_ref(cx, cz)
    wall_default = _story(compose).get("color", "brick_red")
    foundation = compose.get("foundation", "stone_foundation")
    trim = compose.get("trim", "limestone")
    roof_mat = compose.get("roof_mat", "shingles_dark")
    foundation_h = float(compose.get("foundation_h") or 0.8)

    placed = []
    for index, volume in enumerate(compose["volumes"]):
        u0, u1 = volume["u0"] * facade_m, volume["u1"] * facade_m
        v0, v1 = volume["v0"] * depth_m, volume["v1"] * depth_m
        corners = _corners(origin, u, v, u0, u1, v0, v1)
        stories = volume["storeys"]
        y = ground_y
        bands = []
        for story in stories:
            h = float(story["sill"]) + float(story["window_h"]) + float(story["headroom"])
            bands.append((y, y + h, story))
            y += h
        eave = y
        placed.append({"corners": corners, "eave": eave, "index": index})
        foundation_band(mb, corners, ground_y, min(foundation_h, eave - ground_y), foundation)
        for edge in range(4):
            p0, p1 = corners[edge], corners[(edge + 1) % 4]
            mid = ((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5)
            _d, normal, length = edge_dir_normal(p0, p1)
            probe = offset2(mid, normal, 0.4)
            hidden = False
            for other in placed:
                if other["index"] == index:
                    continue
                if _inside(probe, other["corners"]) and other["eave"] >= eave - 0.3:
                    hidden = True
            if hidden:
                continue
            for y0, y1, story in bands:
                wall_backdrop(mb, story.get("color", wall_default), p0, p1, y0, y1)
                role = _role(edge, index == 0)
                centers, width, kinds = _openings_for(role, story, length)
                for center, kind in zip(centers, kinds):
                    _opening(mb, p0, p1, center, y0 + float(story["sill"]), width, float(story["window_h"]), kind, story.get("color", wall_default))
        perimeter_band(mb, corners, eave - 0.15, eave + 0.25, 0.18, trim)
        roof = volume.get("roof", "flat")
        if roof == "gable":
            # c0-c1 is the street end. The ridge runs back along the long side.
            build_gable_roof(
                mb, corners[0], corners[1], corners[2], corners[3],
                eave, math.radians(float(volume.get("pitch") or 40)), 0.35, True,
                roof_mat, wall_default,
            )
            if compose.get("oculus") and index == 0:
                span = math.hypot(corners[1][0] - corners[0][0], corners[1][1] - corners[0][1])
                rise = (span * 0.5) * math.tan(math.radians(float(volume.get("pitch") or 40)))
                window_unit(mb, corners[0], corners[1], span * 0.5, eave + rise * 0.35, 1.15, 1.15,
                            _Quiet(), lit_prob=0.0, sill_mat="limestone")
        elif roof == "shed":
            drop = max(0.6, (v1 - v0) * math.tan(math.radians(float(volume.get("pitch") or 18))))
            high, low = eave, eave - drop
            mb.add_quad(roof_mat, pt3(corners[0], high), pt3(corners[1], high), pt3(corners[2], low), pt3(corners[3], low))
        else:
            flat_roof_cap(mb, corners, eave, roof_mat)
            perimeter_band(mb, corners, eave, eave + 0.7, 0.12, wall_default)

    if compose.get("towers") == "pair":
        main = placed[0]
        street_left, street_right = main["corners"][0], main["corners"][1]
        inward_u = u
        inward_v = v
        belfry = compose.get("belfry", "off")
        width = float(compose.get("tower_w") or 4.0)
        _tower(mb, street_left, inward_u, inward_v, ground_y, main["eave"], width, belfry == "left", wall_default, roof_mat)
        _tower(mb, street_right, (-u[0], -u[1]), inward_v, ground_y, main["eave"], width, belfry == "right", wall_default, roof_mat)

    top = max(item["eave"] for item in placed) + 8.0
    far_box(mb_far, coords, ground_y, top, (0.45, 0.32, 0.28), window_glow=0.12)
    return {"hull": [{"x": p[0], "z": p[1]} for p in coords], "y0": ground_y, "y1": top}
