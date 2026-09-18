"""Per-archetype building generators. Each function appends geometry into a
near-LOD MeshBuild (mb) and a far-LOD HLOD MeshBuild (mb_far), and returns a
collision descriptor {"hull": [[x,z]...], "y0": float, "y1": float} or None
if the footprint was too degenerate to build.
"""
import math

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
def build_downtown_commercial(mb, mb_far, coords, ground_y, height_m, tags, rng, bid):
    coords = ensure_ccw(dedupe_ring(coords))
    if len(coords) < 3:
        return None
    named = bool(tags.get("name"))
    civic = named or rng.random() < 0.15
    brick = rng.choice(palette.CIVIC_BRICK_KEYS if civic else palette.BRICK_KEYS)
    storeys = max(2, min(4, round(height_m / 3.9))) if height_m else rng.choice([2, 2, 3])
    ground_h = 4.3
    upper_h = 3.5
    total_h = ground_h + upper_h * (storeys - 1)
    roof_y = ground_y + total_h

    n = len(coords)
    for i in range(n):
        p0, p1 = coords[i], coords[(i + 1) % n]
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if length < 1.5:
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
                    window_unit(mb, b0, b1, bw * 0.5 - off, ground_y + 0.45, w, 2.6, rng,
                                storefront=True, lit_prob=0.45)
            elif bw > 1.2:
                w = min(bw - 0.6, 2.8)
                window_unit(mb, b0, b1, bw * 0.5, ground_y + 0.45, w, 2.6, rng,
                            storefront=True, lit_prob=0.45)
            # kick plate + sign band accents
            wall_backdrop(mb, "trim_dark", b0, b1, ground_y, ground_y + 0.32, offset=0.02)
            if rng.random() < 0.35:
                awning_unit(mb, b0, b1, bw * 0.5, ground_y + ground_h - 0.1, bw * 0.82, 1.1,
                            rng, rng.choice(palette.AWNING_COLORS))
            for s in range(1, storeys):
                y0 = ground_y + ground_h + upper_h * (s - 1)
                wall_backdrop(mb, brick, b0, b1, y0, y0 + upper_h)
                if bw >= 3.0:
                    window_unit(mb, b0, b1, bw * 0.32, y0 + 1.0, min(bw * 0.32, 1.3), 2.0, rng,
                                lit_prob=0.3, sill_mat="limestone")
                    window_unit(mb, b0, b1, bw * 0.68, y0 + 1.0, min(bw * 0.32, 1.3), 2.0, rng,
                                lit_prob=0.3, sill_mat="limestone")
                elif bw >= 1.6:
                    window_unit(mb, b0, b1, bw * 0.5, y0 + 1.0, min(bw * 0.6, 1.2), 1.9, rng,
                                lit_prob=0.3, sill_mat="limestone")

    cornice_y = roof_y
    perimeter_band(mb, coords, cornice_y, cornice_y + 0.3, 0.18, "limestone")
    parapet_h = rng.uniform(0.5, 0.9)
    for i in range(n):
        wall_backdrop(mb, brick, coords[i], coords[(i + 1) % n], cornice_y + 0.3, cornice_y + 0.3 + parapet_h)
    cap_y = cornice_y + 0.3 + parapet_h
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


def build_porch(mb, c0, c1, ground_y, rng):
    d, n, l = edge_dir_normal(c0, c1)
    pw = min(l * 0.7, 5.0)
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
        mb.add_box("siding_white", cx_o, cz_o, floor_y, roof_y - 0.05, 0.18, 0.18, color=WHITE)
    step_w = min(pw * 0.4, 1.6)
    s0 = (mid[0] - d[0] * step_w / 2, mid[1] - d[1] * step_w / 2)
    s1 = (mid[0] + d[0] * step_w / 2, mid[1] + d[1] * step_w / 2)
    s0o = offset2(s0, n, 0.4)
    s1o = offset2(s1, n, 0.4)
    mb.add_quad("stone_foundation", pt3(s0, floor_y), pt3(s1, floor_y), pt3(s1o, ground_y + 0.1), pt3(s0o, ground_y + 0.1))


def build_residential_house(mb, mb_far, coords, ground_y, height_m, tags, rng, bid, road_index, scale=1.0):
    coords = ensure_ccw(dedupe_ring(coords))
    if len(coords) < 3:
        return None
    ext, center, width, length, yaw = min_rotated_rect(coords)
    width = max(5.0, min(width, 14.0)) * scale
    length = max(6.0, min(length, 22.0)) * scale
    corners = rect_from_center(center[0], center[1], width, length, yaw)

    seg, _d = road_index.nearest(center[0], center[1], 250.0) if road_index else (None, 1e9)
    if seg:
        rx, rz, _ = nearest_point_on_segment(center[0], center[1], seg[0], seg[1], seg[2], seg[3])
        road_vec = (rx - center[0], rz - center[1])
        rl = math.hypot(*road_vec) or 1.0
        road_vec = (road_vec[0] / rl, road_vec[1] / rl)
    else:
        road_vec = (0.0, 1.0)
    fi = _front_edge_index(corners, road_vec)
    corners = corners[fi:] + corners[:fi]
    c0, c1, c2, c3 = corners

    storeys = 1 if (height_m and height_m < 6.0) else (1 if rng.random() < 0.3 else 2)
    story_h = 2.85
    eave_y = ground_y + 0.5 + story_h * storeys
    siding = rng.choice(palette.SIDING_KEYS)
    shingle = rng.choice(palette.SHINGLE_KEYS)
    pitch_rad = math.radians(rng.uniform(24, 40))
    roof_style = rng.choices(["gable_front", "side_gable", "hip"], weights=[0.5, 0.3, 0.2])[0]
    overhang = rng.uniform(0.35, 0.55)

    foundation_band(mb, corners, ground_y, 0.5, "stone_foundation")
    for i in range(4):
        p0, p1 = corners[i], corners[(i + 1) % 4]
        wall_backdrop(mb, siding, p0, p1, ground_y + 0.5, eave_y)
        d, n, l = edge_dir_normal(p0, p1)
        is_front = (i == 0)
        for s in range(storeys):
            y0 = ground_y + 0.5 + story_h * s + 0.85
            nwin = max(1, int(l // 3.2))
            for wi in range(nwin):
                t = (wi + 0.5) / nwin * l
                if is_front and s == 0 and abs(t - l * 0.5) < 1.3:
                    continue
                window_unit(mb, p0, p1, t, y0, 1.0, 1.3, rng, lit_prob=0.35)
        if is_front:
            door_unit(mb, p0, p1, l * 0.5, ground_y + 0.5, 1.0, 2.1,
                      mat=rng.choice(["trim_dark", "siding_white"]))

    has_porch = rng.random() < 0.6
    if has_porch:
        build_porch(mb, c0, c1, ground_y, rng)

    if roof_style == "hip":
        ridge_y = build_hip_roof(mb, c0, c1, c2, c3, eave_y, pitch_rad, overhang, shingle)
    else:
        gable_front = (roof_style == "gable_front")
        ridge_y = build_gable_roof(mb, c0, c1, c2, c3, eave_y, pitch_rad, overhang, gable_front, shingle, siding)

    if rng.random() < 0.5:
        t = rng.uniform(0.3, 0.7)
        cx = c0[0] + (c2[0] - c0[0]) * t
        cz = c0[1] + (c2[1] - c0[1]) * t
        top = ridge_y + rng.uniform(0.7, 1.2)
        base = eave_y - rng.uniform(0.3, 1.0)
        mb.add_box("brick_red", cx, cz, base, top, 0.55, 0.5, color=WHITE)

    far_box(mb_far, corners, ground_y, eave_y, palette.APPROX_COLOR[siding], window_glow=0.12)
    return {"hull": corners, "y0": ground_y, "y1": ridge_y}


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
