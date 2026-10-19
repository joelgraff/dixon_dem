"""Per-archetype building generators. Each function appends geometry into a
near-LOD MeshBuild (mb) and a far-LOD HLOD MeshBuild (mb_far), and returns a
collision descriptor {"hull": [[x,z]...], "y0": float, "y1": float} or None
if the footprint was too degenerate to build.
"""
import math

from shapely.geometry import MultiPoint, Point, Polygon

from common_buildings import (
    ensure_ccw, dedupe_ring, min_rotated_rect, rect_from_center,
    offset_polygon_inward, nearest_point_on_segment, split_edge_bays,
)
from facade import (
    WHITE, wall_backdrop, perimeter_band, foundation_band, flat_roof_cap,
    rooftop_clutter, window_unit, door_unit, awning_unit, build_gable_roof,
    build_hip_roof, far_box, edge_dir_normal, lerp2, offset2, pt3,
)
import palette


# ---------------------------------------------------------------------------
def _edge_is_party(p0, p1, edges):
    if not edges:
        return False
    mid = ((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5)
    for a, b in edges:
        other = ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
        if math.hypot(mid[0] - other[0], mid[1] - other[1]) < 1.8:
            return True
    return False


WALL_COLORS = (
    "brick_red", "brick_buff", "brick_rose", "brick_dark", "brick_cream",
    "limestone", "siding_white", "siding_gray", "siding_sage", "siding_blue", "siding_butter",
)


def _wall_color(template, rng, civic=False):
    """An explicit color wins. Otherwise the material family is still a random draw."""
    color = template.get("color")
    if color in WALL_COLORS:
        return color
    if template.get("material") == "limestone":
        return "limestone"
    if civic or template.get("material") == "brick":
        keys = palette.CIVIC_BRICK_KEYS if civic else palette.BRICK_KEYS
        return rng.choice(keys)
    return rng.choice(palette.SIDING_KEYS)


def _commercial_brick(template, rng, civic=False):
    return _wall_color(template, rng, civic)


def build_downtown_commercial(mb, mb_far, coords, ground_y, height_m, tags, rng, bid, template=None):
    coords = ensure_ccw(dedupe_ring(coords))
    if len(coords) < 3:
        return None
    template = template or {}
    # Storeys come from the template. A missing record stays two, which is the
    # ordinary Dixon commercial block. Nothing here rolls a third or fourth floor.
    if template.get("form") == "one_story_store":
        storeys = 1
    else:
        storeys = int(round(float(template.get("storeys") or 2)))
    storeys = max(1, min(6, storeys))
    brick = _commercial_brick(template, rng, civic=False)
    dressing = template.get("dressing") or "commercial_1900"
    italianate = dressing == "italianate"
    upper_h = 3.5
    # Early downtown blocks keep a storefront floor about twice an upper floor.
    double_ground = template.get("ground") == "double"
    ground_h = upper_h * 2.0 if double_ground else (4.6 if storeys == 1 else 4.3)
    roof_y = ground_y + ground_h + upper_h * (storeys - 1)
    parapet_h = 1.05 if italianate else 0.45
    cornice = 0.34 if italianate else 0.16
    awnings = template.get("awnings") or "some"
    awning_p = 0.0 if awnings == "none" else (1.0 if awnings == "row" else (0.12 if italianate else 0.38))
    storefront_h = max(2.2, ground_h - 1.6)
    party = template.get("party_edges") or []

    n = len(coords)
    for i in range(n):
        p0, p1 = coords[i], coords[(i + 1) % n]
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if length < 1.5:
            continue
        if _edge_is_party(p0, p1, party):
            wall_backdrop(mb, brick, p0, p1, ground_y, roof_y + cornice + parapet_h)
            continue
        bay_pts = split_edge_bays(p0, p1, 6.0, 8.0)
        for bi in range(len(bay_pts) - 1):
            b0, b1 = bay_pts[bi], bay_pts[bi + 1]
            bw = math.hypot(b1[0] - b0[0], b1[1] - b0[1])
            wall_backdrop(mb, brick, b0, b1, ground_y, ground_y + ground_h)
            has_door = rng.random() < 0.4
            if has_door and bw > 1.6:
                door_unit(mb, b0, b1, bw * 0.5, ground_y, 1.1, 2.4, mat="trim_dark", glass_top=True)
                if bw > 3.2:
                    off = bw * 0.27
                    w = min(bw * 0.4, 2.0)
                    window_unit(mb, b0, b1, bw * 0.5 - off, ground_y + 0.45, w, storefront_h, rng,
                                storefront=True, lit_prob=0.45)
            elif bw > 1.2:
                w = min(bw - 0.6, 2.8)
                window_unit(mb, b0, b1, bw * 0.5, ground_y + 0.45, w, storefront_h, rng,
                            storefront=True, lit_prob=0.45)
            # kick plate + sign band accents
            wall_backdrop(mb, "trim_dark", b0, b1, ground_y, ground_y + 0.32, offset=0.02)
            if rng.random() < awning_p:
                awning_unit(mb, b0, b1, bw * 0.5, ground_y + ground_h - 0.1, bw * 0.82, 1.1,
                            rng, rng.choice(palette.AWNING_COLORS))
            upper_window_h = 2.15 if italianate else 1.85
            for s in range(1, storeys):
                y0 = ground_y + ground_h + upper_h * (s - 1)
                wall_backdrop(mb, brick, b0, b1, y0, y0 + upper_h)
                if bw >= 3.0:
                    window_unit(mb, b0, b1, bw * 0.32, y0 + 1.0, min(bw * 0.32, 1.3), upper_window_h, rng,
                                lit_prob=0.3, sill_mat="limestone")
                    window_unit(mb, b0, b1, bw * 0.68, y0 + 1.0, min(bw * 0.32, 1.3), upper_window_h, rng,
                                lit_prob=0.3, sill_mat="limestone")
                elif bw >= 1.6:
                    window_unit(mb, b0, b1, bw * 0.5, y0 + 1.0, min(bw * 0.6, 1.2), upper_window_h, rng,
                                lit_prob=0.3, sill_mat="limestone")

    cornice_y = roof_y
    perimeter_band(mb, coords, cornice_y, cornice_y + cornice, 0.18, "limestone")
    for i in range(n):
        if _edge_is_party(coords[i], coords[(i + 1) % n], party):
            continue
        wall_backdrop(mb, brick, coords[i], coords[(i + 1) % n],
                      cornice_y + cornice, cornice_y + cornice + parapet_h)
        if italianate:
            _cornice_brackets(mb, coords[i], coords[(i + 1) % n], cornice_y + cornice)
    cap_y = cornice_y + cornice + parapet_h
    perimeter_band(mb, coords, cap_y, cap_y + 0.1, 0.06, "limestone")
    inset = offset_polygon_inward(coords, 0.25) or coords
    flat_roof_cap(mb, inset, cap_y, "roof_membrane")
    rooftop_clutter(mb, coords, cap_y, rng)

    far_box(mb_far, coords, ground_y, cap_y, palette.APPROX_COLOR[brick], window_glow=0.22)
    return {"hull": coords, "y0": ground_y, "y1": cap_y}


# ---------------------------------------------------------------------------
def build_boxy_building(mb, mb_far, coords, ground_y, height_m, tags, rng, bid,
                         is_church=False, is_industrial=False, is_bigbox=False):
    coords = ensure_ccw(dedupe_ring(coords))
    if len(coords) < 3:
        return None
    if is_industrial or is_bigbox:
        brick = rng.choice(["brick_dark", "brick_red", "steel_rusted"]) if not is_bigbox else "brick_cream"
        if brick == "steel_rusted":
            brick = "brick_dark"
    else:
        brick = rng.choice(palette.CIVIC_BRICK_KEYS)
    default_h = 5.0 if is_bigbox else 6.0
    storeys = max(1, min(3, round((height_m or default_h) / 4.2)))
    story_h = 4.2 if not is_bigbox else max(height_m or 6.0, 5.0)
    if is_bigbox:
        storeys = 1
    total_h = story_h * storeys
    roof_y = ground_y + total_h

    n = len(coords)
    for i in range(n):
        p0, p1 = coords[i], coords[(i + 1) % n]
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if length < 1.2:
            continue
        wall_backdrop(mb, brick, p0, p1, ground_y, roof_y)
        if is_bigbox:
            if rng.random() < 0.6 and length > 6:
                window_unit(mb, p0, p1, length * 0.5, ground_y + 1.8, min(length * 0.7, 8.0), 2.4,
                            rng, storefront=True, lit_prob=0.5)
            continue
        win_w = 1.6 if is_industrial else 1.3
        nwin = max(1, int(length // 4.0))
        for s in range(storeys):
            y0 = ground_y + story_h * s + 1.1
            for wi in range(nwin):
                t = (wi + 0.5) / nwin * length
                window_unit(mb, p0, p1, t, y0, win_w, 1.8, rng,
                            lit_prob=0.12 if is_industrial else 0.28,
                            sill_mat=None if is_industrial else "limestone")

    perimeter_band(mb, coords, roof_y, roof_y + 0.25, 0.15, "limestone" if not is_industrial else "trim_dark")
    inset = offset_polygon_inward(coords, 0.2) or coords
    roof_mat = "roof_metal" if is_industrial else "roof_membrane"
    flat_roof_cap(mb, inset, roof_y + 0.25, roof_mat)
    rooftop_clutter(mb, coords, roof_y + 0.25, rng, count_range=(1, 3) if not is_bigbox else (2, 5))

    top_y = roof_y + 0.25
    if is_church:
        cx, cz = coords[0]
        cap_y = roof_y + 0.6
        top_y = cap_y + rng.uniform(6.0, 10.0)
        mb.add_box(brick, cx, cz, ground_y, cap_y, 2.6, 2.6, color=WHITE)
        corners3 = [(cx - 1.4, cz - 1.4), (cx + 1.4, cz - 1.4), (cx + 1.4, cz + 1.4), (cx - 1.4, cz + 1.4)]
        apex = (cx, top_y, cz)
        for i4 in range(4):
            a = pt3(corners3[i4], cap_y)
            b = pt3(corners3[(i4 + 1) % 4], cap_y)
            mb.add_tri_face("shingles_dark", a, b, apex)

    far_box(mb_far, coords, ground_y, roof_y + 0.25, palette.APPROX_COLOR[brick],
            window_glow=0.28 if is_bigbox else 0.1)
    return {"hull": coords, "y0": ground_y, "y1": top_y}


def _street_edge_index(coords, road_vec):
    best_i, best = 0, -1e18
    hint = road_vec or (0.0, 1.0)
    for i in range(len(coords)):
        p0, p1 = coords[i], coords[(i + 1) % len(coords)]
        _d, normal, length = edge_dir_normal(p0, p1)
        if length < 2.0:
            continue
        dot = normal[0] * hint[0] + normal[1] * hint[1]
        if dot > best:
            best, best_i = dot, i
    return best_i


def build_church(mb, mb_far, coords, ground_y, rng, road_index, template=None):
    """A nave: the real footprint's bounding rectangle, steep front gable,
    tall windows, door on the street. A tower is built only when the template
    asks for one."""
    coords = ensure_ccw(dedupe_ring(coords))
    if len(coords) < 3:
        return None
    template = template or {}
    from templates import front_from_road
    ext, center, _w, _l, _yaw = min_rotated_rect(coords)
    road_vec = front_from_road(center, road_index)
    corners = _face_street(ext, road_vec)
    brick = _commercial_brick(template, rng, civic=True)
    shingle = rng.choice(palette.SHINGLE_KEYS)
    storeys = max(1, min(2, int(round(float(template.get("storeys") or 1)))))
    wall_h = 7.4 if storeys == 1 else 4.6 * storeys
    eave_y = ground_y + wall_h
    foundation_band(mb, corners, ground_y, 0.6, "stone_foundation")
    for i in range(4):
        p0, p1 = corners[i], corners[(i + 1) % 4]
        wall_backdrop(mb, brick, p0, p1, ground_y + 0.6, eave_y)
        _d, _n, length = edge_dir_normal(p0, p1)
        count = max(1, int(length // 3.4))
        for wi in range(count):
            t = (wi + 0.5) / count * length
            if i == 0 and abs(t - length * 0.5) < 1.3:
                continue
            window_unit(mb, p0, p1, t, ground_y + 2.2, 0.85, 3.2, rng,
                        lit_prob=0.15, sill_mat="limestone")
        if i == 0:
            door_unit(mb, p0, p1, length * 0.5, ground_y + 0.6, 1.4, 2.8,
                      mat="trim_dark", glass_top=True)
    pitch = math.radians(46)
    ridge_y = build_gable_roof(mb, corners[0], corners[1], corners[2], corners[3],
                                eave_y, pitch, 0.4, True, shingle, brick)
    top_y = ridge_y
    if template.get("tower"):
        c0 = corners[0]
        cap_y = ridge_y
        top_y = ridge_y + 6.5
        mb.add_box(brick, c0[0], c0[1], ground_y, cap_y, 2.4, 2.4, color=WHITE)
        base = [(c0[0] - 1.3, c0[1] - 1.3), (c0[0] + 1.3, c0[1] - 1.3),
                (c0[0] + 1.3, c0[1] + 1.3), (c0[0] - 1.3, c0[1] + 1.3)]
        apex = (c0[0], top_y, c0[1])
        for i4 in range(4):
            a = pt3(base[i4], cap_y)
            b = pt3(base[(i4 + 1) % 4], cap_y)
            mb.add_tri_face(shingle, a, b, apex)
    far_box(mb_far, corners, ground_y, eave_y, palette.APPROX_COLOR[brick], window_glow=0.08)
    return {"hull": coords, "y0": ground_y, "y1": top_y}


def build_industrial(mb, mb_far, coords, ground_y, rng, road_index, template=None):
    """Brick mill volume. A near-rectangle gets a shallow gable; anything else
    keeps its outline and a low metal roof."""
    coords = ensure_ccw(dedupe_ring(coords))
    if len(coords) < 3:
        return None
    template = template or {}
    from templates import front_from_road
    brick = _wall_color(template, rng, civic=False)
    if template.get("color") not in WALL_COLORS:
        brick = rng.choice(["brick_dark", "brick_dark", "brick_red"])
    storeys = max(1, min(6, int(round(float(template.get("storeys") or 1)))))
    story_h = 4.0
    roof_y = ground_y + story_h * storeys
    ext, center, _w, _l, _yaw = min_rotated_rect(coords)
    poly = Polygon(coords)
    rect = Polygon(ext)
    rectangular = rect.area > 1.0 and poly.area / rect.area >= 0.82
    road_vec = front_from_road(center, road_index)
    outline = _face_street(ext, road_vec) if rectangular else coords
    party = template.get("party_edges") or []
    for i in range(len(outline)):
        p0, p1 = outline[i], outline[(i + 1) % len(outline)]
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if length < 1.2:
            continue
        wall_backdrop(mb, brick, p0, p1, ground_y, roof_y)
        if _edge_is_party(p0, p1, party):
            continue
        count = max(1, int(length // 6.0))
        for storey in range(storeys):
            y0 = ground_y + story_h * storey + 1.4
            for wi in range(count):
                t = (wi + 0.5) / count * length
                window_unit(mb, p0, p1, t, y0, 1.05, 1.15, rng, lit_prob=0.08)
    if rectangular and (template.get("roof") or "gable") == "gable":
        ridge_y = build_gable_roof(
            mb, outline[0], outline[1], outline[2], outline[3],
            roof_y, math.radians(14), 0.25, False, "roof_metal", brick)
    else:
        perimeter_band(mb, outline, roof_y, roof_y + 0.35, 0.1, "trim_dark")
        inset = offset_polygon_inward(outline, 0.2) or outline
        flat_roof_cap(mb, inset, roof_y + 0.35, "roof_metal")
        ridge_y = roof_y + 0.35
    rooftop_clutter(mb, outline, ridge_y, rng, count_range=(0, 2))
    far_box(mb_far, outline, ground_y, roof_y, palette.APPROX_COLOR[brick], window_glow=0.06)
    return {"hull": coords, "y0": ground_y, "y1": ridge_y}


def build_civic(mb, mb_far, coords, ground_y, rng, road_index, template=None):
    """School, hall, or bank: the real outline, regular tall windows, no awnings."""
    coords = ensure_ccw(dedupe_ring(coords))
    if len(coords) < 3:
        return None
    template = template or {}
    from templates import front_from_road
    brick = _commercial_brick(template, rng, civic=True)
    storeys = max(1, min(6, int(round(float(template.get("storeys") or 2)))))
    story_h = 4.1
    roof_y = ground_y + story_h * storeys
    center = (sum(p[0] for p in coords) / len(coords), sum(p[1] for p in coords) / len(coords))
    road_vec = front_from_road(center, road_index)
    door_edge = _street_edge_index(coords, road_vec)
    party = template.get("party_edges") or []
    for i in range(len(coords)):
        p0, p1 = coords[i], coords[(i + 1) % len(coords)]
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if length < 1.2:
            continue
        wall_backdrop(mb, brick, p0, p1, ground_y, roof_y)
        if _edge_is_party(p0, p1, party):
            continue
        count = max(1, int(length // 3.6))
        for storey in range(storeys):
            y0 = ground_y + story_h * storey + 1.15
            for wi in range(count):
                t = (wi + 0.5) / count * length
                if i == door_edge and storey == 0 and abs(t - length * 0.5) < 1.4:
                    continue
                window_unit(mb, p0, p1, t, y0, 1.15, 2.15, rng,
                            lit_prob=0.22, sill_mat="limestone")
        if i == door_edge:
            door_unit(mb, p0, p1, length * 0.5, ground_y, 1.5, 2.7, mat="trim_dark", glass_top=True)
    perimeter_band(mb, coords, roof_y, roof_y + 0.45, 0.16, "limestone")
    cap_y = roof_y + 0.45
    inset = offset_polygon_inward(coords, 0.25) or coords
    flat_roof_cap(mb, inset, cap_y, "roof_membrane")
    far_box(mb_far, coords, ground_y, cap_y, palette.APPROX_COLOR[brick], window_glow=0.12)
    return {"hull": coords, "y0": ground_y, "y1": cap_y}


# ---------------------------------------------------------------------------
def _front_edge_index(corners, front_dir_hint):
    best_i, best_dot = 0, -1e9
    for i in range(4):
        p0, p1 = corners[i], corners[(i + 1) % 4]
        _, n, _ = edge_dir_normal(p0, p1)
        dot = n[0] * front_dir_hint[0] + n[1] * front_dir_hint[1]
        if dot > best_dot:
            best_dot, best_i = dot, i
    return best_i


def _dress(template):
    """Detail kit. It does not change the mass, only windows, posts, and eaves."""
    name = (template or {}).get("dressing") or "plain"
    if name == "folk_victorian":
        return {"window": (0.72, 1.85), "group": "single", "posts": "turned", "eave": "plain", "chimney": True}
    if name == "craftsman":
        return {"window": (1.15, 1.25), "group": "pair", "posts": "pier", "eave": "knee", "chimney": True}
    if name == "midcentury":
        return {"window": (1.7, 0.85), "group": "single", "posts": "plain", "eave": "plain", "chimney": False}
    if name == "italianate":
        return {"window": (0.8, 1.9), "group": "single", "posts": "plain", "eave": "bracket", "chimney": True}
    if name == "commercial_1900":
        return {"window": (1.0, 1.55), "group": "single", "posts": "plain", "eave": "plain", "chimney": False}
    return {"window": (0.95, 1.5), "group": "single", "posts": "plain", "eave": "plain", "chimney": True}


def build_porch(mb, c0, c1, ground_y, rng, width_frac=0.7, max_width=5.0, depth=None, post_style="plain"):
    d, n, l = edge_dir_normal(c0, c1)
    pw = min(l * width_frac, max_width)
    if pw < 0.8:
        return
    if depth is None:
        depth = rng.uniform(1.8, 2.6)
    mid = lerp2(c0, c1, 0.5)
    a = (mid[0] - d[0] * pw / 2, mid[1] - d[1] * pw / 2)
    b = (mid[0] + d[0] * pw / 2, mid[1] + d[1] * pw / 2)
    a_out = offset2(a, n, depth)
    b_out = offset2(b, n, depth)
    floor_y = ground_y + 0.35
    roof_y = ground_y + 2.6
    mb.add_quad("stone_foundation", pt3(a, floor_y), pt3(b, floor_y), pt3(b_out, floor_y), pt3(a_out, floor_y),
                normal=(0.0, 1.0, 0.0))
    mb.add_quad("siding_white", pt3(a, roof_y), pt3(b, roof_y), pt3(b_out, roof_y), pt3(a_out, roof_y),
                normal=(0.0, 1.0, 0.0))
    mb.add_quad("trim_dark", pt3(a_out, roof_y - 0.05), pt3(b_out, roof_y - 0.05),
                pt3(b_out, roof_y + 0.15), pt3(a_out, roof_y + 0.15))
    col_ts = (0.08, 0.92) if pw < 3.2 else (0.06, 0.37, 0.63, 0.94)
    for t in col_ts:
        cx = a[0] + (b[0] - a[0]) * t
        cz = a[1] + (b[1] - a[1]) * t
        cx_o = cx + n[0] * depth * 0.85
        cz_o = cz + n[1] * depth * 0.85
        if post_style == "pier":
            mb.add_box("stone_foundation", cx_o, cz_o, floor_y, floor_y + 0.7, 0.34, 0.34, color=WHITE)
            mb.add_box("trim_dark", cx_o, cz_o, floor_y + 0.7, roof_y - 0.05, 0.14, 0.14, color=WHITE)
        elif post_style == "turned":
            mb.add_box("siding_white", cx_o, cz_o, floor_y, roof_y - 0.05, 0.11, 0.11, color=WHITE)
            mb.add_box("siding_white", cx_o, cz_o, floor_y + 0.65, floor_y + 0.92, 0.2, 0.2, color=WHITE)
        else:
            mb.add_box("siding_white", cx_o, cz_o, floor_y, roof_y - 0.05, 0.18, 0.18, color=WHITE)
    step_w = min(pw * 0.4, 1.6)
    s0 = (mid[0] - d[0] * step_w / 2, mid[1] - d[1] * step_w / 2)
    s1 = (mid[0] + d[0] * step_w / 2, mid[1] + d[1] * step_w / 2)
    s0o = offset2(s0, n, 0.4)
    s1o = offset2(s1, n, 0.4)
    mb.add_quad("stone_foundation", pt3(s0, floor_y), pt3(s1, floor_y), pt3(s1o, ground_y + 0.1), pt3(s0o, ground_y + 0.1))


def _unit_pair(vx, vz):
    length = math.hypot(vx, vz) or 1.0
    return (vx / length, vz / length), length


def _frame(corners):
    c0, c1, _c2, c3 = corners
    u, width = _unit_pair(c1[0] - c0[0], c1[1] - c0[1])
    v, depth = _unit_pair(c3[0] - c0[0], c3[1] - c0[1])
    return c0, u, v, width, depth


def _world(origin, u, v, uu, vv):
    return (origin[0] + u[0] * uu + v[0] * vv, origin[1] + u[1] * uu + v[1] * vv)


def _box_uv(origin, u, v, u0, v0, u1, v1):
    """CCW rectangle. The u0->u1 edge at v0 is the street edge."""
    return [
        _world(origin, u, v, u0, v0),
        _world(origin, u, v, u1, v0),
        _world(origin, u, v, u1, v1),
        _world(origin, u, v, u0, v1),
    ]


def _face_street(corners, road_vec):
    index = _front_edge_index(corners, road_vec)
    return corners[index:] + corners[:index]


def ell_bars(coords, road_vec):
    """Split an L into a main bar and a wing. Each rectangle's first edge faces
    the street. A plain rectangle comes back as (corners, None)."""
    coords = ensure_ccw(dedupe_ring(list(coords)))
    if len(coords) < 3:
        return None, None
    ext, _center, _width, _length, _yaw = min_rotated_rect(coords)
    corners = _face_street(ext, road_vec)
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    rect = Polygon(corners)
    if rect.is_empty or rect.area < 1.0 or poly.area / max(rect.area, 1e-6) >= 0.82:
        return corners, None
    diff = rect.difference(poly)
    if diff.is_empty:
        return corners, None
    parts = list(diff.geoms) if diff.geom_type == "MultiPolygon" else [diff]
    parts = [geom for geom in parts if geom.geom_type == "Polygon" and geom.area > rect.area * 0.05]
    if len(parts) != 1:
        return corners, None
    # A bite out of the middle of one side is a court, not an ell. The notch of
    # an ell meets two sides of the bounding rectangle.
    from templates import _notch_is_corner
    if not _notch_is_corner(rect, parts[0]):
        return corners, None
    origin, u, v, width, depth = _frame(corners)
    us, vs = [], []
    for point in parts[0].exterior.coords:
        dx, dz = point[0] - origin[0], point[1] - origin[1]
        us.append(dx * u[0] + dz * u[1])
        vs.append(dx * v[0] + dz * v[1])
    nu0, nu1 = max(0.0, min(us)), min(width, max(us))
    nv0, nv1 = max(0.0, min(vs)), min(depth, max(vs))
    if nu1 - nu0 < 1.5 or nv1 - nv0 < 1.5:
        return corners, None
    front_free = nv0
    back_free = depth - nv1
    if front_free >= back_free and front_free > 1.8:
        main = _box_uv(origin, u, v, 0.0, 0.0, width, nv0)
        wing_v = (nv0, min(depth, nv1))
    elif back_free > 1.8:
        main = _box_uv(origin, u, v, 0.0, nv1, width, depth)
        wing_v = (max(0.0, nv0), nv1)
    else:
        return corners, None
    if nu0 >= width - nu1:
        wing_u = (0.0, nu0)
    else:
        wing_u = (nu1, width)
    if wing_u[1] - wing_u[0] < 2.2 or wing_v[1] - wing_v[0] < 2.2:
        return _face_street(main, road_vec), None
    wing = _box_uv(origin, u, v, wing_u[0], wing_v[0], wing_u[1], wing_v[1])
    return _face_street(main, road_vec), _face_street(wing, road_vec)


def _eave_and_floors(ground_y, template):
    form = template.get("form") or "side_gable"
    storeys = float(template.get("storeys") or 1.5)
    story = 2.55 if form in ("bungalow", "ranch") else 2.8
    full = int(math.floor(storeys + 1e-6))
    half = (storeys - full) >= 0.4
    if full < 1:
        full = 1
        half = False
    eave = ground_y + 0.45 + story * full + (1.05 if half else 0.0)
    return eave, full, story


def _pitch_overhang(template):
    form = template.get("form")
    roof = template.get("roof") or "gable"
    if form == "bungalow":
        return math.radians(22), 0.7
    if form == "ranch":
        return math.radians(18), 0.5
    if roof in ("hip", "pyramidal") or form == "foursquare":
        return math.radians(30), 0.45
    if form == "cross_gable":
        return math.radians(40), 0.4
    if roof == "gambrel":
        return math.radians(48), 0.4
    return math.radians(34), 0.42


def _siding_for(template, rng):
    return _wall_color(template, rng, civic=False)


def _nearest_edge(corners, point):
    best_i, best_d = 0, 1e18
    for i in range(4):
        p0, p1 = corners[i], corners[(i + 1) % 4]
        mid = lerp2(p0, p1, 0.5)
        dist = math.hypot(mid[0] - point[0], mid[1] - point[1])
        if dist < best_d:
            best_d, best_i = dist, i
    return best_i


def _window_spots(length, ww, group, door, is_front):
    """Distances along an edge where a window is centered."""
    spots = []
    if group == "pair" and length >= 4.2:
        count = max(1, int(length // 3.6))
        half = ww * 0.42 + 0.12
        for index in range(count):
            center = (index + 0.5) / count * length
            for sign in (-1.0, 1.0):
                t = center + sign * half
                if door and is_front and abs(t - length * 0.5) < 1.15:
                    continue
                if 0.4 < t < length - 0.4:
                    spots.append((t, ww * 0.78))
        return spots
    count = max(1, int(length // 3.2))
    for index in range(count):
        t = (index + 0.5) / count * length
        if door and is_front and abs(t - length * 0.5) < 1.2:
            continue
        spots.append((t, ww))
    return spots


def _mass(mb, corners, ground_y, eave_y, floors, story, siding, rng, door=True,
          skip_windows=None, window=(1.0, 1.35), group="single"):
    foundation_band(mb, corners, ground_y, 0.45, "stone_foundation")
    ww, wh = window
    for i in range(4):
        p0, p1 = corners[i], corners[(i + 1) % 4]
        wall_backdrop(mb, siding, p0, p1, ground_y + 0.45, eave_y)
        if skip_windows is not None and i == skip_windows:
            continue
        _d, _n, length = edge_dir_normal(p0, p1)
        spots = _window_spots(length, ww, group, door, i == 0)
        for storey in range(floors):
            y0 = ground_y + 0.45 + story * storey + 0.85
            for t, width in spots:
                window_unit(mb, p0, p1, t, y0, width, wh, rng, lit_prob=0.35)
        if door and i == 0:
            door_unit(mb, p0, p1, length * 0.5, ground_y + 0.45, 1.0, 2.1,
                      mat=rng.choice(["trim_dark", "siding_white"]))


def _knee_braces(mb, c0, c1, eave_y):
    """Small timbers under the front eave. Craftsman bungalows read by these."""
    d, n, length = edge_dir_normal(c0, c1)
    count = max(2, int(length // 2.4))
    for index in range(count):
        t = (index + 0.5) / count
        px = c0[0] + (c1[0] - c0[0]) * t
        pz = c0[1] + (c1[1] - c0[1]) * t
        outer = offset2((px, pz), n, 0.5)
        mb.add_tri_face("trim_dark",
                        pt3((px, pz), eave_y - 0.55),
                        pt3(outer, eave_y - 0.06),
                        pt3((px, pz), eave_y - 0.06))
    del d


def _cornice_brackets(mb, p0, p1, y):
    _d, n, length = edge_dir_normal(p0, p1)
    count = max(2, int(length // 1.5))
    for index in range(count):
        t = (index + 0.5) / count
        px = p0[0] + (p1[0] - p0[0]) * t
        pz = p0[1] + (p1[1] - p0[1]) * t
        mb.add_box("trim_dark", px + n[0] * 0.14, pz + n[1] * 0.14, y - 0.38, y + 0.02, 0.12, 0.16, color=WHITE)


def _raise_roof(mb, corners, eave_y, template, siding, shingle, pitch, overhang, gable_front=None):
    c0, c1, c2, c3 = corners
    roof = template.get("roof") or "gable"
    if roof == "flat_parapet":
        flat_roof_cap(mb, corners, eave_y, "roof_membrane")
        return eave_y + 0.3
    if roof in ("hip", "pyramidal"):
        return build_hip_roof(mb, c0, c1, c2, c3, eave_y, pitch, overhang, shingle)
    if gable_front is None:
        gable_front = template.get("roof_axis") == "front" or template.get("form") == "front_gable"
    return build_gable_roof(mb, c0, c1, c2, c3, eave_y, pitch, overhang, gable_front, shingle, siding)


def _cross_bar(corners):
    c0, c1 = corners[0], corners[1]
    d, n, length = edge_dir_normal(c0, c1)
    span = max(3.2, min(length * 0.42, 6.5))
    mid = lerp2(c0, c1, 0.5)
    a = (mid[0] - d[0] * span / 2.0, mid[1] - d[1] * span / 2.0)
    b = (mid[0] + d[0] * span / 2.0, mid[1] + d[1] * span / 2.0)
    depth = 2.4
    return [offset2(a, n, depth), offset2(b, n, depth), b, a]


def _inner_porch_edge(main, wing):
    """A short stretch of the main street edge, at the end nearest the wing."""
    c0, c1 = main[0], main[1]
    center = (
        sum(p[0] for p in wing) / 4.0,
        sum(p[1] for p in wing) / 4.0,
    )
    d, _n, length = edge_dir_normal(c0, c1)
    span = min(3.8, max(2.2, length * 0.45))
    if math.hypot(c0[0] - center[0], c0[1] - center[1]) <= math.hypot(c1[0] - center[0], c1[1] - center[1]):
        return c0, (c0[0] + d[0] * span, c0[1] + d[1] * span)
    return (c1[0] - d[0] * span, c1[1] - d[1] * span), c1


def _add_chimney(mb, corners, eave_y, ridge_y, rng):
    c0, c2 = corners[0], corners[2]
    t = rng.uniform(0.35, 0.65)
    cx = c0[0] + (c2[0] - c0[0]) * t
    cz = c0[1] + (c2[1] - c0[1]) * t
    mb.add_box("brick_red", cx, cz, eave_y - 0.4, ridge_y + rng.uniform(0.6, 1.1), 0.55, 0.5, color=WHITE)


def build_residential_house(mb, mb_far, coords, ground_y, height_m, tags, rng, bid, road_index,
                            scale=1.0, template=None):
    """A house from its template. `height_m` and `scale` remain in the signature
    so older callers still run; the template decides storeys and roof."""
    del height_m, scale
    coords = ensure_ccw(dedupe_ring(coords))
    if len(coords) < 3:
        return None
    if template is None:
        template = {
            "form": "side_gable", "storeys": 1.5, "roof": "gable", "roof_axis": "side",
            "wing": "none", "porch": "stoop", "material": "clapboard", "dressing": "plain",
        }
    elif template.get("form") not in (
        "side_gable", "front_gable", "gabled_ell", "foursquare", "bungalow", "cross_gable", "ranch",
    ):
        # Classified as a house, but the template says commercial. Keep the
        # measured storeys and build a side-gable until the commercial pass.
        template = dict(template)
        template["form"] = "side_gable"
        template["roof"] = "gable"
        template["roof_axis"] = "side"
    ext, center, _width, _length, _yaw = min_rotated_rect(coords)
    from templates import front_from_road
    road_vec = front_from_road(center, road_index)
    extras = []
    main, wing = corners_of(coords, road_vec, template, extras)
    if main is None:
        return None
    siding = _siding_for(template, rng)
    shingle = rng.choice(palette.SHINGLE_KEYS)
    eave_y, floors, story = _eave_and_floors(ground_y, template)
    pitch, overhang = _pitch_overhang(template)
    dress = _dress(template)
    window = dress["window"]
    skip = None
    if wing is not None:
        skip = _nearest_edge(main, (sum(p[0] for p in wing) / 4.0, sum(p[1] for p in wing) / 4.0))
        if skip == 0:
            skip = None
    _mass(mb, main, ground_y, eave_y, floors, story, siding, rng, door=True, skip_windows=skip,
          window=window, group=dress["group"])
    ridge_y = _raise_roof(mb, main, eave_y, template, siding, shingle, pitch, overhang)
    if wing is not None:
        wing_skip = _nearest_edge(wing, (sum(p[0] for p in main) / 4.0, sum(p[1] for p in main) / 4.0))
        if wing_skip == 0:
            wing_skip = None
        _mass(mb, wing, ground_y, eave_y, floors, story, siding, rng, door=False,
              skip_windows=wing_skip, window=window, group=dress["group"])
        wing_template = dict(template)
        wing_template["roof"] = "gable"
        # A wing that runs away from the street shows its gable to the side;
        # one that reaches the street shows the gable to the street.
        deeper = _edge_len(wing[1], wing[2]) > _edge_len(wing[0], wing[1])
        ridge_y = max(ridge_y, _raise_roof(
            mb, wing, eave_y, wing_template, siding, shingle, pitch, overhang, gable_front=deeper))
    for bar in extras:
        # further boxes of an irregular footprint (fit_bars): plain gabled masses, no door
        _mass(mb, bar, ground_y, eave_y, floors, story, siding, rng, door=False, window=window, group=dress["group"])
        bar_template = dict(template)
        bar_template["roof"] = "gable"
        ridge_y = max(ridge_y, _raise_roof(mb, bar, eave_y, bar_template, siding, shingle, pitch, overhang,
                                           gable_front=_edge_len(bar[1], bar[2]) > _edge_len(bar[0], bar[1])))
        far_box(mb_far, bar, ground_y, eave_y, palette.APPROX_COLOR.get(siding, (0.8, 0.8, 0.8)), window_glow=0.08)
    if template["form"] == "cross_gable" and wing is None:
        bar = _cross_bar(main)
        _mass(mb, bar, ground_y, eave_y, floors, story, siding, rng, door=False, window=window, group=dress["group"])
        cross = dict(template)
        cross["roof"] = "gable"
        ridge_y = max(ridge_y, _raise_roof(
            mb, bar, eave_y, cross, siding, shingle, pitch + math.radians(6), overhang, gable_front=True))
        porch_edge = (bar[0], bar[1])
    else:
        porch_edge = (main[0], main[1])
    _place_porch(mb, template, main, wing, porch_edge, ground_y, rng, dress["posts"], coords=coords)
    if dress["eave"] == "knee":
        _knee_braces(mb, main[0], main[1], eave_y)
    if dress["chimney"] and template["form"] != "ranch":
        _add_chimney(mb, main, eave_y, ridge_y, rng)
    far_box(mb_far, main, ground_y, eave_y, palette.APPROX_COLOR.get(siding, (0.8, 0.8, 0.8)), window_glow=0.12)
    if wing is not None:
        far_box(mb_far, wing, ground_y, eave_y, palette.APPROX_COLOR.get(siding, (0.8, 0.8, 0.8)), window_glow=0.08)
    return {"hull": built_outline(main, wing, extras), "y0": ground_y, "y1": ridge_y}


def _edge_len(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


# A house is built as gabled boxes. Where the footprint's bounding rectangle (or an ell's two
# bars) would stand more than this far outside the footprint, the boxes are fitted inside it
# instead (fit_bars): an odd-shaped footprint's rectangle reached into the walk, the street
# and the next building (1013252878 at 932,-1696 stood on the parkway and in the curb lane).
SPILL_TOL_M2 = 4.0
SPILL_TOL_FRAC = 0.06
FIT_CELL_M = 0.5
MIN_BAR_M = 2.2


def corners_of(coords, road_vec, template, extras=None):
    """(main, wing) boxes for a house; a list passed as `extras` gets any further boxes
    fit_bars needed to cover an irregular footprint."""
    coords = ensure_ccw(dedupe_ring(list(coords)))
    if template.get("form") == "gabled_ell":
        main, wing = ell_bars(coords, road_vec)
    else:
        ext, _center, _w, _l, _yaw = min_rotated_rect(coords)
        main, wing = _face_street(ext, road_vec), None
    if main is None:
        return main, wing
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if spill_area(poly, main, wing) > max(SPILL_TOL_M2, SPILL_TOL_FRAC * poly.area):
        fitted_main, fitted_wing, more = fit_bars(poly, road_vec)
        if fitted_main is not None:
            if extras is not None:
                extras.extend(more)
            return fitted_main, fitted_wing
    return main, wing


def spill_area(poly, main, wing=None):
    """How much of the boxes stands outside the footprint."""
    built = Polygon(main)
    if wing is not None:
        built = built.union(Polygon(wing))
    return built.difference(poly).area


def built_outline(main, wing=None, extras=()):
    """The ground outline of the boxes, for the collision hull."""
    points = list(main) + (list(wing) if wing is not None else []) + [p for bar in extras for p in bar]
    return list(MultiPoint(points).convex_hull.exterior.coords)[:-1]


def _largest_rect(mask):
    """(row0, col0, row1, col1) exclusive of the largest all-True rectangle in a 2D bool array."""
    best, best_area = None, 0
    heights = [0] * mask.shape[1]
    for r in range(mask.shape[0]):
        row = mask[r]
        for c in range(mask.shape[1]):
            heights[c] = heights[c] + 1 if row[c] else 0
        stack = []
        for c in range(mask.shape[1] + 1):
            h = heights[c] if c < mask.shape[1] else 0
            start = c
            while stack and stack[-1][1] >= h:
                start, sh = stack.pop()
                if sh * (c - start) > best_area:
                    best_area = sh * (c - start)
                    best = (r - sh + 1, start, r + 1, c)
            stack.append((start, h))
    return best


MAX_EXTRA_BARS = 3


def fit_bars(poly, road_vec, cell=FIT_CELL_M):
    """Boxes inside the footprint: the main bar is the largest rectangle inside it, the wing the
    largest in what is left that touches it, and up to MAX_EXTRA_BARS more the same way (each
    sharing a wall with one already placed). The boxes are aligned with the footprint's bounding
    rectangle or with one of its longest walls, whichever covers most of it (a skewed footprint's
    walls are not square to its bounding rectangle). Each box's first edge faces the street, as
    corners_of's. Returns (main, wing, extras); (None, None, []) when nothing MIN_BAR_M wide fits."""
    ring = list(poly.exterior.coords)[:-1]
    frames = [min_rotated_rect(ring)[0]]
    edges = sorted(((math.hypot(b[0] - a[0], b[1] - a[1]), math.atan2(b[1] - a[1], b[0] - a[0]))
                    for a, b in zip(ring, ring[1:] + ring[:1])), reverse=True)
    for _length, angle in edges[:3]:
        frames.append(_bounding_rect_at(ring, angle))
    best, best_cover = (None, None, []), 0.0
    for corners in frames:
        main, wing, extras = _fit_in_frame(poly, corners, road_vec, cell)
        if main is None:
            continue
        cover = sum(Polygon(bar).area for bar in [main] + ([wing] if wing else []) + extras)
        if cover > best_cover * 1.02:
            best, best_cover = (main, wing, extras), cover
    return best


def _bounding_rect_at(ring, angle):
    """The CCW rectangle around `ring` with its sides along `angle`."""
    ca, sa = math.cos(angle), math.sin(angle)
    us = [x * ca + z * sa for x, z in ring]
    vs = [-x * sa + z * ca for x, z in ring]
    u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
    world = [(u * ca - v * sa, u * sa + v * ca) for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))]
    return ensure_ccw(world)


def _fit_in_frame(poly, corners, road_vec, cell):
    import numpy as np
    from shapely import contains_xy
    origin, u, v, width, depth = _frame(corners)
    nu, nv = max(1, int(width / cell)), max(1, int(depth / cell))
    su, sv = width / nu, depth / nv
    uu, vv = np.meshgrid((np.arange(nu) + 0.5) * su, (np.arange(nv) + 0.5) * sv)
    xs = origin[0] + u[0] * uu + v[0] * vv
    zs = origin[1] + u[1] * uu + v[1] * vv
    mask = contains_xy(poly, xs, zs)   # rows: v, columns: u

    def box(found):
        if found is None:
            return None
        r0, c0, r1, c1 = found
        if (c1 - c0) * su < MIN_BAR_M or (r1 - r0) * sv < MIN_BAR_M:
            return None
        return _box_uv(origin, u, v, c0 * su, r0 * sv, c1 * su, r1 * sv), found

    first = box(_largest_rect(mask))
    if first is None:
        return None, None, []
    main, (r0, c0, r1, c1) = first
    rest = mask.copy()
    rest[r0:r1, c0:c1] = False
    placed = [Polygon(main)]
    bars = []
    min_area = max(12.0, 0.05 * poly.area)
    for _ in range(12):
        if len(bars) >= 1 + MAX_EXTRA_BARS:
            break
        found = box(_largest_rect(rest))
        if found is None or Polygon(found[0]).area < min_area:
            break
        candidate, (r0, c0, r1, c1) = found
        rest[r0:r1, c0:c1] = False
        shape_ = Polygon(candidate)
        # a box must share a wall (not a corner) with one already placed
        if any(shape_.intersection(other.buffer(cell * 0.5)).area > MIN_BAR_M * cell * 0.5 for other in placed):
            placed.append(shape_)
            bars.append(_face_street(candidate, road_vec))
    wing = bars[0] if bars else None
    return _face_street(main, road_vec), wing, bars[1:]


def _place_porch(mb, template, main, wing, porch_edge, ground_y, rng, post_style="plain", coords=None):
    porch = template.get("porch") or "none"
    if porch == "none":
        return
    legs = template.get("porch_legs")
    if legs:
        # where a footprint override puts them: along each leg's edge, its whole length, its depth out
        for leg in legs:
            a, b = (float(leg["a"][0]), float(leg["a"][1])), (float(leg["b"][0]), float(leg["b"][1]))
            if coords and _faces_inward(a, b, coords):
                a, b = b, a
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            build_porch(mb, a, b, ground_y, rng, width_frac=1.0, max_width=length, depth=float(leg["depth"]),
                        post_style=post_style)
        return
    if porch == "ell_corner" and wing is not None:
        edge = _inner_porch_edge(main, wing)
        build_porch(mb, edge[0], edge[1], ground_y, rng, width_frac=1.0, max_width=4.2, depth=2.0, post_style=post_style)
        return
    c0, c1 = porch_edge
    if porch == "stoop":
        build_porch(mb, c0, c1, ground_y, rng, width_frac=0.36, max_width=2.4, depth=1.25, post_style=post_style)
    elif porch == "gable_full":
        build_porch(mb, c0, c1, ground_y, rng, width_frac=0.96, max_width=16.0, depth=2.6, post_style=post_style)
    elif porch == "wrap":
        build_porch(mb, c0, c1, ground_y, rng, width_frac=0.94, max_width=14.0, depth=2.1, post_style=post_style)
        build_porch(mb, main[1], main[2], ground_y, rng, width_frac=0.7, max_width=6.0, depth=1.8, post_style=post_style)
    elif porch == "shed_full":
        build_porch(mb, c0, c1, ground_y, rng, width_frac=0.94, max_width=14.0, depth=2.2, post_style=post_style)
    else:
        build_porch(mb, c0, c1, ground_y, rng, post_style=post_style)


def _faces_inward(a, b, coords):
    """Whether build_porch would build a leg from a to b into the building
    (its edge_dir_normal points inside): a leg is written counter-clockwise,
    but a ring wound the other way is put right rather than built inside."""
    _d, n, _length = edge_dir_normal(a, b)
    mid = ((a[0] + b[0]) / 2 + n[0] * 0.3, (a[1] + b[1]) / 2 + n[1] * 0.3)
    return Polygon(coords).contains(Point(mid))


def build_garage(mb, mb_far, coords, ground_y, rng, bid, road_index=None):
    coords = ensure_ccw(dedupe_ring(coords))
    if len(coords) < 3:
        return None
    ext, center, width, length, yaw = min_rotated_rect(coords)
    width = max(2.6, min(width, 7.0))
    length = max(2.6, min(length, 9.0))
    corners = rect_from_center(center[0], center[1], width, length, yaw)
    c0, c1, c2, c3 = corners
    eave_y = ground_y + 2.5
    siding = rng.choice(["trim_dark", "siding_gray", "siding_white"])
    for i in range(4):
        wall_backdrop(mb, siding, corners[i], corners[(i + 1) % 4], ground_y, eave_y)
    d, n, l = edge_dir_normal(c0, c1)
    door_w = min(l * 0.75, 2.6)
    a = (center[0] - d[0] * door_w / 2 - n[0] * width / 2, center[1] - d[1] * door_w / 2 - n[1] * width / 2)
    b = (center[0] + d[0] * door_w / 2 - n[0] * width / 2, center[1] + d[1] * door_w / 2 - n[1] * width / 2)
    mb.add_quad("trim_dark", pt3(a, ground_y), pt3(b, ground_y), pt3(b, ground_y + 2.1), pt3(a, ground_y + 2.1),
                normal=(-n[0], 0.0, -n[1]), color=WHITE)
    gable_front = rng.random() < 0.5
    ridge_y = build_gable_roof(mb, c0, c1, c2, c3, eave_y, math.radians(24), 0.3, gable_front,
                                rng.choice(palette.SHINGLE_KEYS), siding)
    far_box(mb_far, corners, ground_y, eave_y, palette.APPROX_COLOR[siding], window_glow=0.02)
    return {"hull": corners, "y0": ground_y, "y1": ridge_y}
