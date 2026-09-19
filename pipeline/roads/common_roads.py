"""Shared geometry helpers for the roads workstream build.

All planar (x, z) math lives here: heightmap sampling, polyline resampling,
parallel-offset curves, and junction "ring" construction (curb-return
fillets). Coordinates are Godot-local meters (x east, z south-negative) as
produced by pipeline/common.py -- this module does NOT touch UTM/lon-lat.
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common as pc  # pipeline/common.py

EPS = 1e-6


# ---------------------------------------------------------------------------
# Heightmap sampling
# ---------------------------------------------------------------------------
class Heightmap:
    """Bilinear sampler over the road-conformed play heightmap (r32)."""

    def __init__(self, path=None):
        wo = pc.load_world_origin()
        hm = wo["heightmaps"]["play"]
        if path is None:
            path = os.path.join(pc.GAME_DATA, hm["road_conformed_file"])
        self.width = hm["width"]
        self.height = hm["height"]
        self.spacing = hm["spacing_m"]
        self.origin_e = hm["origin_easting"]
        self.origin_n_top = hm["origin_northing_top"]
        # Godot local x/z of the heightmap's top-left (row0/col0) sample.
        self.x0 = self.origin_e - pc.ORIGIN_EASTING
        self.z0 = -(self.origin_n_top - pc.ORIGIN_NORTHING)
        arr = np.fromfile(path, dtype="<f4")
        assert arr.size == self.width * self.height, (
            f"heightmap size mismatch: {arr.size} vs {self.width * self.height}"
        )
        self.grid = arr.reshape((self.height, self.width))

    def _uv(self, x, z):
        col = (x - self.x0) / self.spacing
        row = (z - self.z0) / self.spacing
        col = min(max(col, 0.0), self.width - 1.001)
        row = min(max(row, 0.0), self.height - 1.001)
        return col, row

    def sample(self, x, z):
        col, row = self._uv(x, z)
        c0 = int(math.floor(col))
        r0 = int(math.floor(row))
        c1 = min(c0 + 1, self.width - 1)
        r1 = min(r0 + 1, self.height - 1)
        fc = col - c0
        fr = row - r0
        g = self.grid
        h00 = g[r0, c0]
        h10 = g[r0, c1]
        h01 = g[r1, c0]
        h11 = g[r1, c1]
        h0 = h00 * (1 - fc) + h10 * fc
        h1 = h01 * (1 - fc) + h11 * fc
        return float(h0 * (1 - fr) + h1 * fr)

    def normal(self, x, z, step=0.5):
        """Approximate surface normal via central difference (Godot: +Y up, -Z north)."""
        hL = self.sample(x - step, z)
        hR = self.sample(x + step, z)
        hD = self.sample(x, z - step)
        hU = self.sample(x, z + step)
        # dY/dx and dY/dz
        dzdx = (hR - hL) / (2 * step)
        dzdz = (hU - hD) / (2 * step)
        n = np.array([-dzdx, 1.0, -dzdz])
        n /= (np.linalg.norm(n) + 1e-9)
        return n.tolist()


# ---------------------------------------------------------------------------
# 2D polyline helpers (operate on (x, z) tuples; y attached separately)
# ---------------------------------------------------------------------------
def polyline_length(pts):
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))


def resample_polyline(pts, spacing=3.0, smooth_iters=1):
    """Chaikin-smooth then resample a 2D polyline at ~even arc-length spacing.
    Preserves exact first/last point (junction anchors)."""
    if len(pts) < 2:
        return list(pts)
    work = [tuple(p) for p in pts]
    # Chaikin corner-cutting, keeping endpoints fixed, only if enough interior points.
    for _ in range(smooth_iters):
        if len(work) < 3:
            break
        new_pts = [work[0]]
        for i in range(len(work) - 1):
            p0 = work[i]
            p1 = work[i + 1]
            if i > 0:
                q = (0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1])
                new_pts.append(q)
            if i < len(work) - 2:
                r = (0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1])
                new_pts.append(r)
        new_pts.append(work[-1])
        work = new_pts
    # Even arc-length resample.
    total = polyline_length(work)
    if total < EPS:
        return [pts[0], pts[-1]]
    n = max(2, int(round(total / spacing)) + 1)
    targets = [total * i / (n - 1) for i in range(n)]
    out = []
    acc = 0.0
    seg_i = 0
    ti = 0
    seg_start = work[0]
    while ti < len(targets):
        t = targets[ti]
        while seg_i < len(work) - 1:
            seg_len = math.hypot(work[seg_i + 1][0] - work[seg_i][0], work[seg_i + 1][1] - work[seg_i][1])
            if acc + seg_len >= t - 1e-9 or seg_i == len(work) - 2:
                if seg_len < EPS:
                    out.append(work[seg_i])
                else:
                    f = max(0.0, min(1.0, (t - acc) / seg_len))
                    a = work[seg_i]
                    b = work[seg_i + 1]
                    out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
                break
            acc += seg_len
            seg_i += 1
        ti += 1
    out[0] = pts[0]
    out[-1] = pts[-1]
    return out


def trim_polyline(pts, start_trim, end_trim):
    """Cut `start_trim` / `end_trim` meters off each end of a 2D polyline (arc length)."""
    total = polyline_length(pts)
    if start_trim + end_trim >= total - 0.05:
        mid = total * 0.5
        start_trim = min(start_trim, mid - 0.01)
        end_trim = min(end_trim, mid - 0.01)
        start_trim = max(start_trim, 0.0)
        end_trim = max(end_trim, 0.0)

    def point_at(dist):
        acc = 0.0
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            if acc + seg >= dist or i == len(pts) - 2:
                f = 0.0 if seg < EPS else max(0.0, min(1.0, (dist - acc) / seg))
                return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), i
            acc += seg
        return pts[-1], len(pts) - 2

    p0, i0 = point_at(start_trim)
    p1, i1 = point_at(total - end_trim)
    out = [p0] + [p for j, p in enumerate(pts) if i0 < j <= i1] + [p1]
    # de-dup consecutive
    dedup = [out[0]]
    for p in out[1:]:
        if math.hypot(p[0] - dedup[-1][0], p[1] - dedup[-1][1]) > 1e-4:
            dedup.append(p)
    if len(dedup) < 2:
        dedup = [p0, p1]
    return dedup


def segment_normal(a, b):
    dx = b[0] - a[0]
    dz = b[1] - a[1]
    length = math.hypot(dx, dz)
    if length < EPS:
        return (0.0, 0.0)
    # left-hand perpendicular in (x,z) plane
    return (-dz / length, dx / length)


def offset_polyline(pts, distance, miter_limit=3.0):
    """Parallel offset curve to the LEFT of travel direction by `distance` (mitered joins)."""
    n = len(pts)
    if n < 2:
        return list(pts)
    seg_normals = [segment_normal(pts[i], pts[i + 1]) for i in range(n - 1)]
    out = []
    for i in range(n):
        if i == 0:
            nx, nz = seg_normals[0]
        elif i == n - 1:
            nx, nz = seg_normals[-1]
        else:
            n0 = seg_normals[i - 1]
            n1 = seg_normals[i]
            mx, mz = n0[0] + n1[0], n0[1] + n1[1]
            mlen = math.hypot(mx, mz)
            if mlen < 1e-5:
                nx, nz = n0
            else:
                mx, mz = mx / mlen, mz / mlen
                cos_half = mx * n0[0] + mz * n0[1]
                scale = 1.0 / max(cos_half, 1.0 / miter_limit)
                nx, nz = mx * scale, mz * scale
        out.append((pts[i][0] + nx * distance, pts[i][1] + nz * distance))
    return out


def direction_at(pts, index):
    """Unit tangent direction at a polyline vertex (average of adjacent segments)."""
    n = len(pts)
    if n < 2:
        return (1.0, 0.0)
    if index == 0:
        a, b = pts[0], pts[1]
    elif index == n - 1:
        a, b = pts[-2], pts[-1]
    else:
        a, b = pts[index - 1], pts[index + 1]
    dx, dz = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dz)
    if length < EPS:
        return (1.0, 0.0)
    return (dx / length, dz / length)


# ---------------------------------------------------------------------------
# Ribbon / mesh assembly (positions are (x, z) 2D; caller attaches y + normal)
# ---------------------------------------------------------------------------
class MeshBuild:
    """Accumulates a flat triangle soup: verts = [x,y,z,nx,ny,nz,u,v], indices."""

    def __init__(self):
        self.verts = []  # list of 8-tuples
        self.indices = []

    def add_vertex(self, x, y, z, n, u=0.0, v=0.0):
        self.verts.append((x, y, z, n[0], n[1], n[2], u, v))
        return len(self.verts) - 1

    def add_tri(self, a, b, c):
        # reject degenerate
        pa, pb, pc_ = self.verts[a], self.verts[b], self.verts[c]
        ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
        vx, vy, vz = pc_[0] - pa[0], pc_[1] - pa[1], pc_[2] - pa[2]
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        area2 = math.sqrt(cx * cx + cy * cy + cz * cz)
        if area2 < 1e-8:
            return
        self.indices.extend([a, b, c])

    def add_quad(self, a, b, c, d):
        """a,b,c,d in order around the quad (CCW as seen from above/outside)."""
        self.add_tri(a, b, c)
        self.add_tri(a, c, d)

    def extend(self, other):
        base = len(self.verts)
        self.verts.extend(other.verts)
        self.indices.extend(i + base for i in other.indices)

    def is_empty(self):
        return not self.indices


def add_ribbon(mb: MeshBuild, left_pts_xz, right_pts_xz, heightmap: Heightmap, y_bias=0.0,
               u_left=0.0, u_right=1.0, v_scale=1.0, flip=False):
    """Build a triangle strip between two parallel 2D polylines of equal length,
    sampling Y + normal from the heightmap. v runs along the strip length."""
    n = len(left_pts_xz)
    assert len(right_pts_xz) == n
    if n < 2:
        return
    left_idx = []
    right_idx = []
    v = 0.0
    for i in range(n):
        lx, lz = left_pts_xz[i]
        rx, rz = right_pts_xz[i]
        ly = heightmap.sample(lx, lz) + y_bias
        ry = heightmap.sample(rx, rz) + y_bias
        ln = heightmap.normal(lx, lz)
        rn = heightmap.normal(rx, rz)
        if i > 0:
            v += math.hypot(lx - left_pts_xz[i - 1][0], lz - left_pts_xz[i - 1][1]) * v_scale
        li = mb.add_vertex(lx, ly, lz, ln, u_left, v)
        ri = mb.add_vertex(rx, ry, rz, rn, u_right, v)
        left_idx.append(li)
        right_idx.append(ri)
    for i in range(n - 1):
        if flip:
            mb.add_quad(right_idx[i], right_idx[i + 1], left_idx[i + 1], left_idx[i])
        else:
            mb.add_quad(left_idx[i], left_idx[i + 1], right_idx[i + 1], right_idx[i])


def fan_fill(mb: MeshBuild, loop_xz, heightmap: Heightmap, y_bias=0.0):
    """Fill a (roughly star-convex) closed loop of 2D points via triangle fan from centroid."""
    n = len(loop_xz)
    if n < 3:
        return
    cx = sum(p[0] for p in loop_xz) / n
    cz = sum(p[1] for p in loop_xz) / n
    cy = heightmap.sample(cx, cz) + y_bias
    cn = heightmap.normal(cx, cz)
    ci = mb.add_vertex(cx, cy, cz, cn, 0.5, 0.5)
    ring_idx = []
    for (x, z) in loop_xz:
        y = heightmap.sample(x, z) + y_bias
        nrm = heightmap.normal(x, z)
        ring_idx.append(mb.add_vertex(x, y, z, nrm, 0.5, 0.5))
    # Junction fan winding sense varies with loop shape; double-sided is cheap
    # here (small patch count) and removes the risk of an inverted normal
    # leaving a hole-shaped intersection when viewed from above.
    for i in range(n):
        j = (i + 1) % n
        mb.add_tri(ci, ring_idx[i], ring_idx[j])
        mb.add_tri(ci, ring_idx[j], ring_idx[i])


def line_intersect(p1, p2, p3, p4):
    """2D line-line intersection (infinite lines through p1p2 and p3p4). Returns None if parallel."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
    return (px, py)


def angle_of(v):
    return math.atan2(v[1], v[0])


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def quadratic_bezier(a, c, b, t):
    mt = 1.0 - t
    x = mt * mt * a[0] + 2 * mt * t * c[0] + t * t * b[0]
    z = mt * mt * a[1] + 2 * mt * t * c[1] + t * t * b[1]
    return (x, z)


def point_and_dir_at(pts, target_dist):
    """Point + unit tangent at a given arc-length distance along a 2D polyline."""
    acc = 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if acc + seg >= target_dist or i == len(pts) - 2:
            f = 0.0 if seg < EPS else max(0.0, min(1.0, (target_dist - acc) / seg))
            x = a[0] + (b[0] - a[0]) * f
            z = a[1] + (b[1] - a[1]) * f
            dx, dz = (b[0] - a[0]), (b[1] - a[1])
            dlen = math.hypot(dx, dz)
            if dlen < EPS:
                return (x, z, 1.0, 0.0)
            return (x, z, dx / dlen, dz / dlen)
        acc += seg
    return (pts[-1][0], pts[-1][1], 1.0, 0.0)


def fillet_arc(a, dir_a, b, dir_b, center, n=5):
    """Rounded corner from a to b (n points incl. endpoints), using the
    intersection of the two edge-direction rays as the bezier control point;
    falls back to a straight line (via the midpoint control) if degenerate.
    The elbow's allowed distance from the chord scales with the chord length
    (`a`-to-`b`) itself, not a fixed absolute value -- a junction mixing a
    wide arterial with a narrow side street produces asymmetric fillets
    (e.g. sidewalk rings at very different offsets meeting at a sharp angle)
    whose "reasonable" elbow position is naturally further out than a fixed
    threshold would allow for a small residential corner, and conversely a
    fixed generous threshold let a bad elbow balloon a big loop into a wild,
    street-covering bulge at a real intersection -- this is what produced the
    visible pale gap/blob artifacts fixed in this pass."""
    elbow = line_intersect(a, (a[0] + dir_a[0], a[1] + dir_a[1]), b, (b[0] + dir_b[0], b[1] + dir_b[1]))
    mid = ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
    chord = dist(a, b)
    limit = max(10.0, chord * 1.2)
    if elbow is None or dist(elbow, mid) > limit:
        elbow = mid
    return [quadratic_bezier(a, elbow, b, i / (n - 1)) for i in range(n)]
