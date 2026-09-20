"""Low-level facade/roof geometry primitives shared by every archetype
builder in generate.py. All positions are (x,z) 2D + separate y, Godot local
space (meters). See docs/buildings_notes.md for the overall approach.
"""
import math

from common_buildings import MeshBuild, tri_normal  # noqa: F401 (re-export convenience)

WHITE = (1.0, 1.0, 1.0, 1.0)


def lerp2(p0, p1, t):
    return (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)


def edge_dir_normal(p0, p1):
    dx, dz = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dz) or 1.0
    d = (dx / length, dz / length)
    n = (d[1], -d[0])  # outward for a CCW polygon
    return d, n, length


def pt3(p2, y):
    return (p2[0], y, p2[1])


def offset2(p2, n2, dist):
    return (p2[0] + n2[0] * dist, p2[1] + n2[1] * dist)


# ---------------------------------------------------------------------------
# Walls
# ---------------------------------------------------------------------------
def wall_backdrop(mb, mat, p0, p1, y0, y1, color=WHITE, offset=0.0, normal=None):
    """Flat wall quad along edge p0->p1 (2D), from y0 to y1."""
    d, n, length = edge_dir_normal(p0, p1)
    if normal is None:
        normal = n
    a = offset2(p0, normal, offset)
    b = offset2(p1, normal, offset)
    h = y1 - y0
    mb.add_quad(mat, pt3(a, y0), pt3(b, y0), pt3(b, y1), pt3(a, y1),
                normal=(normal[0], 0.0, normal[1]),
                uvs=((0, 0), (length, 0), (length, h), (0, h)), color=color)


def perimeter_band(mb, coords, y0, y1, out_dist, mat, color=WHITE):
    """A projecting ledge/cornice ring around a CCW polygon: a vertical outward
    face + a top cap connecting the wall plane to the projected edge. Cheap
    approximation (no mitred corners / soffit)."""
    n = len(coords)
    for i in range(n):
        p0 = coords[i]
        p1 = coords[(i + 1) % n]
        d, nrm, length = edge_dir_normal(p0, p1)
        a_out = offset2(p0, nrm, out_dist)
        b_out = offset2(p1, nrm, out_dist)
        # projecting front face
        mb.add_quad(mat, pt3(a_out, y0), pt3(b_out, y0), pt3(b_out, y1), pt3(a_out, y1),
                    normal=(nrm[0], 0.0, nrm[1]),
                    uvs=((0, 0), (length, 0), (length, y1 - y0), (0, y1 - y0)), color=color)
        # top cap (from wall plane at y1 out to the projected edge at y1)
        mb.add_quad(mat, pt3(p0, y1), pt3(p1, y1), pt3(b_out, y1), pt3(a_out, y1),
                    normal=(0.0, 1.0, 0.0), color=color)


def foundation_band(mb, coords, ground_y, height, mat, color=WHITE):
    n = len(coords)
    for i in range(n):
        wall_backdrop(mb, mat, coords[i], coords[(i + 1) % n], ground_y, ground_y + height, color=color, offset=0.01)


def flat_roof_cap(mb, coords, y, mat, color=WHITE, uv_scale=1.0):
    from common_buildings import triangulate_flat
    tris = triangulate_flat(coords)
    for t in tris:
        p0, p1, p2 = t
        mb.add_tri_face(mat, pt3(p0, y), pt3(p1, y), pt3(p2, y), normal=(0.0, 1.0, 0.0),
                         uvs=((p0[0] * uv_scale, p0[1] * uv_scale),
                              (p1[0] * uv_scale, p1[1] * uv_scale),
                              (p2[0] * uv_scale, p2[1] * uv_scale)),
                         color=color)


def far_box(mb_far, coords, y0, y1, color_rgb, window_glow=0.15):
    """One flat-shaded HLOD box (walls + flat cap) tinted by an approximate
    average color of the building's real materials, for the far-chunk mesh."""
    col = (color_rgb[0], color_rgb[1], color_rgb[2], window_glow)
    n = len(coords)
    for i in range(n):
        wall_backdrop(mb_far, "building_far", coords[i], coords[(i + 1) % n], y0, y1, color=col)
    flat_roof_cap(mb_far, coords, y1, "building_far",
                  color=(color_rgb[0] * 0.75, color_rgb[1] * 0.75, color_rgb[2] * 0.75, 0.0))


def rooftop_clutter(mb, coords, y, rng, mat="steel_rusted", count_range=(1, 4)):
    from common_buildings import offset_polygon_inward, polygon_area_2d
    inset = offset_polygon_inward(coords, 1.4)
    if not inset or abs(polygon_area_2d(inset)) < 4.0:
        return
    xs = [p[0] for p in inset]
    zs = [p[1] for p in inset]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    n = rng.randint(*count_range)
    from common_buildings import point_in_poly
    placed = 0
    tries = 0
    while placed < n and tries < n * 6:
        tries += 1
        x = rng.uniform(x0, x1)
        z = rng.uniform(z0, z1)
        if not point_in_poly((x, z), inset):
            continue
        sx = rng.uniform(0.8, 2.2)
        sz = rng.uniform(0.8, 2.2)
        sh = rng.uniform(0.5, 1.3)
        color = (0.5 + rng.uniform(-0.05, 0.05),) * 3 + (1.0,)
        mb.add_box(mat, x, z, y, y + sh, sx, sz, color=color, yaw=rng.uniform(0, math.pi / 2))
        placed += 1


# ---------------------------------------------------------------------------
# Windows / doors
# ---------------------------------------------------------------------------
def window_unit(mb, p0, p1, center_dist, y0, w, h, rng, storefront=False,
                 lit_prob=0.35, frame_mat="trim_dark", glass_mat="window_lit",
                 sill_mat=None):
    d, n, length = edge_dir_normal(p0, p1)
    cx, cz = p0[0] + d[0] * center_dist, p0[1] + d[1] * center_dist
    lit = 1.0 if rng.random() < lit_prob else 0.0
    warm_t = rng.uniform(0.0, 1.0)
    curtain = rng.choice([0.0, 0.0, 0.35, 0.65, 0.9])
    sf = 1.0 if storefront else 0.0
    color = (lit, warm_t, curtain, sf)

    half_w = w / 2.0
    a = (cx - d[0] * half_w, cz - d[1] * half_w)
    b = (cx + d[0] * half_w, cz + d[1] * half_w)

    def q(mat, off, extra_w, extra_h, col, uvs=None):
        aa = offset2(a, n, off)
        bb = offset2(b, n, off)
        aa = (aa[0] - d[0] * extra_w, aa[1] - d[1] * extra_w)
        bb = (bb[0] + d[0] * extra_w, bb[1] + d[1] * extra_w)
        y_lo, y_hi = y0 - extra_h, y0 + h + extra_h
        mb.add_quad(mat, pt3(aa, y_lo), pt3(bb, y_lo), pt3(bb, y_hi), pt3(aa, y_hi),
                    normal=(n[0], 0.0, n[1]), uvs=uvs, color=col)

    q(frame_mat, 0.03, 0.09, 0.09, WHITE)
    q(glass_mat, 0.05, 0.0, 0.0, color, uvs=((0, 0), (1, 0), (1, 1), (0, 1)))
    if sill_mat:
        aa = offset2(a, n, 0.06)
        bb = offset2(b, n, 0.06)
        aa = (aa[0] - d[0] * 0.15, aa[1] - d[1] * 0.15)
        bb = (bb[0] + d[0] * 0.15, bb[1] + d[1] * 0.15)
        mb.add_quad(sill_mat, pt3(aa, y0 - 0.14), pt3(bb, y0 - 0.14), pt3(bb, y0 - 0.02), pt3(aa, y0 - 0.02),
                    normal=(n[0], 0.0, n[1]), color=WHITE)
        mb.add_quad(sill_mat, pt3(aa, y0 + h + 0.02), pt3(bb, y0 + h + 0.02), pt3(bb, y0 + h + 0.16), pt3(aa, y0 + h + 0.16),
                    normal=(n[0], 0.0, n[1]), color=WHITE)


def door_unit(mb, p0, p1, center_dist, y0, w, h, mat="trim_dark", glass_top=False):
    d, n, length = edge_dir_normal(p0, p1)
    cx, cz = p0[0] + d[0] * center_dist, p0[1] + d[1] * center_dist
    half_w = w / 2.0
    a = (cx - d[0] * half_w, cz - d[1] * half_w)
    b = (cx + d[0] * half_w, cz + d[1] * half_w)
    aa = offset2(a, n, 0.04)
    bb = offset2(b, n, 0.04)
    top_h = h * 0.72 if glass_top else h
    mb.add_quad(mat, pt3(aa, y0), pt3(bb, y0), pt3(bb, y0 + top_h), pt3(aa, y0 + top_h),
                normal=(n[0], 0.0, n[1]), color=WHITE)
    if glass_top:
        mb.add_quad("window_lit", pt3(aa, y0 + top_h), pt3(bb, y0 + top_h), pt3(bb, y0 + h), pt3(aa, y0 + h),
                    normal=(n[0], 0.0, n[1]), color=(0.0, 0.5, 0.0, 0.0))


def awning_unit(mb, p0, p1, center_dist, y0, w, depth, rng, color_rgb):
    d, n, length = edge_dir_normal(p0, p1)
    cx, cz = p0[0] + d[0] * center_dist, p0[1] + d[1] * center_dist
    half_w = w / 2.0
    a = (cx - d[0] * half_w, cz - d[1] * half_w)
    b = (cx + d[0] * half_w, cz + d[1] * half_w)
    a_out = offset2(a, n, depth)
    b_out = offset2(b, n, depth)
    y_out = y0 - depth * 0.35
    stripe = rng.choice([0.0, 1.0, 1.0])
    col = (color_rgb[0], color_rgb[1], color_rgb[2], stripe)
    # top surface
    mb.add_quad("awning", pt3(a, y0), pt3(b, y0), pt3(b_out, y_out), pt3(a_out, y_out),
                normal=(n[0], 0.4, n[1]), uvs=((0, 0), (1, 0), (1, 1), (0, 1)), color=col)
    # front valance
    mb.add_quad("awning", pt3(a_out, y_out), pt3(b_out, y_out), pt3(b_out, y_out - 0.35), pt3(a_out, y_out - 0.35),
                normal=(n[0], 0.0, n[1]), uvs=((0, 0), (1, 0), (1, 1), (0, 1)), color=col)


# ---------------------------------------------------------------------------
# Pitched roofs (rectangle-based)
# ---------------------------------------------------------------------------
def build_gable_roof(mb, c0, c1, c2, c3, eave_y, pitch_rad, overhang, gable_front,
                      roof_mat, wall_mat, wall_color=WHITE, roof_color=WHITE):
    """corners CCW: c0-c1 = 'front' edge. gable_front=True -> ridge runs
    front-to-back (gable triangles at front & back). gable_front=False ->
    ridge runs side-to-side (gable triangles at the two side walls)."""
    Lf = math.hypot(c1[0] - c0[0], c1[1] - c0[1])
    Ls = math.hypot(c2[0] - c1[0], c2[1] - c1[1])
    front_mid = lerp2(c0, c1, 0.5)
    back_mid = lerp2(c3, c2, 0.5)
    right_mid = lerp2(c1, c2, 0.5)
    left_mid = lerp2(c3, c0, 0.5)

    if gable_front:
        half_span = Lf / 2.0
        rise = half_span * math.tan(pitch_rad)
        ridge_y = eave_y + rise
        ridge_a, ridge_b = front_mid, back_mid
        eave_edges = [(c1, c2), (c3, c0)]
        gable_edges = [(c0, c1), (c3, c2)]
    else:
        half_span = Ls / 2.0
        rise = half_span * math.tan(pitch_rad)
        ridge_y = eave_y + rise
        ridge_a, ridge_b = right_mid, left_mid
        eave_edges = [(c0, c1), (c3, c2)]
        gable_edges = [(c1, c2), (c3, c0)]

    for (ea, eb) in eave_edges:
        d, n, length = edge_dir_normal(ea, eb)
        ea_o = offset2(ea, n, overhang)
        eb_o = offset2(eb, n, overhang)
        mb.add_quad(roof_mat, pt3(ea_o, eave_y), pt3(eb_o, eave_y), pt3(ridge_b, ridge_y), pt3(ridge_a, ridge_y),
                    uvs=((0, 0), (length, 0), (length, half_span), (0, half_span)), color=roof_color)
        # eave fascia (thin vertical strip under the overhang)
        mb.add_quad(wall_mat, pt3(ea, eave_y - 0.02), pt3(eb, eave_y - 0.02), pt3(eb_o, eave_y - 0.18), pt3(ea_o, eave_y - 0.18),
                    color=(0.5, 0.5, 0.5, 1.0))

    for (ga, gb) in gable_edges:
        mid = lerp2(ga, gb, 0.5)
        apex = ridge_a if math.hypot(mid[0] - ridge_a[0], mid[1] - ridge_a[1]) < math.hypot(mid[0] - ridge_b[0], mid[1] - ridge_b[1]) else ridge_b
        mb.add_tri_face(wall_mat, pt3(ga, eave_y), pt3(gb, eave_y), pt3(apex, ridge_y), color=wall_color)

    return ridge_y


def build_hip_roof(mb, c0, c1, c2, c3, eave_y, pitch_rad, overhang, roof_mat, roof_color=WHITE):
    Lf = math.hypot(c1[0] - c0[0], c1[1] - c0[1])
    Ls = math.hypot(c2[0] - c1[0], c2[1] - c1[1])
    front_mid = lerp2(c0, c1, 0.5)
    back_mid = lerp2(c3, c2, 0.5)
    right_mid = lerp2(c1, c2, 0.5)
    left_mid = lerp2(c3, c0, 0.5)
    corners = [c0, c1, c2, c3]

    # overhang all 4 edges
    oc = []
    for i in range(4):
        p0, p1 = corners[i], corners[(i + 1) % 4]
        _, n, _ = edge_dir_normal(p0, p1)
        oc.append((n, p0, p1))

    def outward(i, pt):
        n = oc[i][0]
        return offset2(pt, n, overhang)

    o0f = outward(0, c0); o1f = outward(0, c1)
    o1s = outward(1, c1); o2s = outward(1, c2)
    o2b = outward(2, c2); o3b = outward(2, c3)
    o3l = outward(3, c3); o0l = outward(3, c0)

    if Lf >= Ls:
        half_span = Ls / 2.0
        rise = half_span * math.tan(pitch_rad)
        ridge_y = eave_y + rise
        ridge_half = max(0.2, (Lf - Ls) / 2.0)
        cx = (c0[0] + c1[0] + c2[0] + c3[0]) / 4.0
        cz = (c0[1] + c1[1] + c2[1] + c3[1]) / 4.0
        ux = (c1[0] - c0[0]) / Lf
        uz = (c1[1] - c0[1]) / Lf
        ridge1 = (cx - ux * ridge_half, cz - uz * ridge_half)
        ridge2 = (cx + ux * ridge_half, cz + uz * ridge_half)
        # long trapezoid planes (front & back eaves)
        mb.add_quad(roof_mat, pt3(o0f, eave_y), pt3(o1f, eave_y), pt3(ridge2, ridge_y), pt3(ridge1, ridge_y), color=roof_color)
        mb.add_quad(roof_mat, pt3(o3b, eave_y), pt3(o2b, eave_y), pt3(ridge1, ridge_y), pt3(ridge2, ridge_y), color=roof_color)
        # short triangle planes (side eaves)
        mb.add_tri_face(roof_mat, pt3(o1s, eave_y), pt3(o2s, eave_y), pt3(ridge2, ridge_y), color=roof_color)
        mb.add_tri_face(roof_mat, pt3(o3l, eave_y), pt3(o0l, eave_y), pt3(ridge1, ridge_y), color=roof_color)
    else:
        half_span = Lf / 2.0
        rise = half_span * math.tan(pitch_rad)
        ridge_y = eave_y + rise
        ridge_half = max(0.2, (Ls - Lf) / 2.0)
        cx = (c0[0] + c1[0] + c2[0] + c3[0]) / 4.0
        cz = (c0[1] + c1[1] + c2[1] + c3[1]) / 4.0
        vx = (c2[0] - c1[0]) / Ls
        vz = (c2[1] - c1[1]) / Ls
        ridge1 = (cx - vx * ridge_half, cz - vz * ridge_half)
        ridge2 = (cx + vx * ridge_half, cz + vz * ridge_half)
        mb.add_quad(roof_mat, pt3(o1s, eave_y), pt3(o2s, eave_y), pt3(ridge2, ridge_y), pt3(ridge1, ridge_y), color=roof_color)
        mb.add_quad(roof_mat, pt3(o3l, eave_y), pt3(o0l, eave_y), pt3(ridge1, ridge_y), pt3(ridge2, ridge_y), color=roof_color)
        mb.add_tri_face(roof_mat, pt3(o0f, eave_y), pt3(o1f, eave_y), pt3(ridge1, ridge_y), color=roof_color)
        mb.add_tri_face(roof_mat, pt3(o3b, eave_y), pt3(o2b, eave_y), pt3(ridge2, ridge_y), color=roof_color)
    return ridge_y


# ---------------------------------------------------------------------------
# Foundations on sloping ground
# ---------------------------------------------------------------------------
def terrain_skirt(mb, coords, ground_y, sampler, mat="stone_foundation", step=3.0, bury=0.25):
    """Foundation/retaining skirt that closes the gap between a level building base at
    `ground_y` and terrain that falls away below it (downtown Dixon drops several metres
    toward the river; without this the low side of every building floats in the air).

    Adds nothing where the terrain is at/above the base. Returns the lowest skirt bottom Y so
    the caller can extend the building's collision hull down to it.
    """
    from common_buildings import ensure_ccw, dedupe_ring
    ring = ensure_ccw(dedupe_ring(list(coords)))
    n = len(ring)
    lowest = ground_y
    for i in range(n):
        p0, p1 = ring[i], ring[(i + 1) % n]
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if length < 0.5:
            continue
        k = max(1, int(math.ceil(length / step)))
        for j in range(k):
            a = lerp2(p0, p1, j / k)
            b = lerp2(p0, p1, (j + 1) / k)
            ha = min(sampler.sample(a[0], a[1]), ground_y)
            hb = min(sampler.sample(b[0], b[1]), ground_y)
            if ha >= ground_y - 0.02 and hb >= ground_y - 0.02:
                continue
            ya, yb = ha - bury, hb - bury
            lowest = min(lowest, ya, yb)
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            top = ground_y + 0.05
            mb.add_quad(mat, pt3(a, ya), pt3(b, yb), pt3(b, top), pt3(a, top),
                        uvs=((0, 0), (seg, 0), (seg, top - yb), (0, top - ya)))
    return lowest


def pick_ground(coords, sampler, centroid, pct=0.7):
    """Building base height: a high-ish percentile of the terrain under the footprint (its
    corners + centroid) so the UPHILL side is not buried and the downhill side gets a skirt."""
    hs = sorted(sampler.sample(p[0], p[1]) for p in list(coords) + [centroid])
    idx = min(len(hs) - 1, int(round(pct * (len(hs) - 1))))
    return hs[idx]
