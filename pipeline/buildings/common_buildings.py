"""Shared geometry helpers for the Dixon buildings workstream.

Mirrors the triangle-soup convention used by pipeline/roads/common_roads.py
(MeshBuild: indexed verts as flat tuples) but adds a vertex-color channel
(RGBA) since building facades use per-vertex data for material tint-free
variation (window lit-state / warmth / curtain style, HLOD box tint).

All coordinates here are already Godot local space (meters): x=east, z=-north,
y=up. See docs/pipeline_notes.md.
"""
import math
import random

from shapely.geometry import Polygon, Point
from shapely.ops import triangulate as _shapely_triangulate


# ---------------------------------------------------------------------------
# Triangle soup builder (indexed), with vertex color.
# ---------------------------------------------------------------------------
class MeshBuild:
    """Accumulates one indexed triangle soup per named material.

    self.groups[material_name] = {"verts": [(x,y,z,nx,ny,nz,u,v,r,g,b,a), ...],
                                   "indices": [i0,i1,i2, ...]}
    """

    def __init__(self):
        self.groups = {}

    def _grp(self, material):
        g = self.groups.get(material)
        if g is None:
            g = {"verts": [], "indices": []}
            self.groups[material] = g
        return g

    def add_vertex(self, material, pos, normal, uv=(0.0, 0.0), color=(1.0, 1.0, 1.0, 1.0)):
        g = self._grp(material)
        g["verts"].append((pos[0], pos[1], pos[2], normal[0], normal[1], normal[2],
                            uv[0], uv[1], color[0], color[1], color[2], color[3]))
        return len(g["verts"]) - 1

    def add_tri(self, material, a, b, c):
        g = self._grp(material)
        va, vb, vc = g["verts"][a], g["verts"][b], g["verts"][c]
        ux, uy, uz = vb[0] - va[0], vb[1] - va[1], vb[2] - va[2]
        wx, wy, wz = vc[0] - va[0], vc[1] - va[1], vc[2] - va[2]
        cx, cy, cz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
        if math.sqrt(cx * cx + cy * cy + cz * cz) < 1e-9:
            return
        g["indices"].extend([a, b, c])

    # --- outward orientation ------------------------------------------------
    # RULE (verified against Godot screenshots + a software re-render of the baked chunks,
    # 2026-09-20): Godot treats a triangle as FRONT-facing when it is CLOCKWISE as seen from
    # the front. In a right-handed frame that means the right-hand-rule normal
    # cross(b-a, c-a) of a front-facing triangle points AWAY from the viewer, i.e. INTO the
    # solid. So for every face we (1) decide which way is OUTWARD (N), then (2) emit the
    # index order whose cross normal is OPPOSITE to N.
    #
    # History: the earlier code emitted a blanket mirror for caps and a "geometric" choice
    # for walls that had the sign inverted, so every wall/roof rendered from the INSIDE
    # (hollow boxes, roof cap visible only from below = the giant "pyramid roofs", black
    # interiors). See docs/STATUS.md / docs/buildings_notes.md.
    def set_outward_ref(self, cx, cz):
        self._out_ref = (cx, cz)

    @staticmethod
    def _cross(a, b, c):
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        ln = math.sqrt(nx * nx + ny * ny + nz * nz)
        if ln < 1e-9:
            return None
        return (nx / ln, ny / ln, nz / ln)

    def _resolve(self, pts, normal):
        """Return (mode, outward_normal). mode is 'default' (emit 0,1,2) or 'mirror' (0,2,1)."""
        n = self._cross(pts[0], pts[1], pts[2])
        if n is None:
            return "mirror", (normal if normal is not None else (0.0, 1.0, 0.0))
        ref = getattr(self, "_out_ref", None)
        fx = sum(q[0] for q in pts) / len(pts)
        fz = sum(q[2] for q in pts) / len(pts)

        def away_from_ref(v):
            # True if horizontal part of v points away from the building reference point.
            return v[0] * (fx - ref[0]) + v[2] * (fz - ref[1]) >= 0.0

        if normal is not None:
            # A supplied normal is AUTHORITATIVE. It comes from the footprint edge
            # (facade.edge_dir_normal on a CCW ring), which knows which side is outside
            # even where the building centroid does not -- L-plans, U-plans, courtyards,
            # and any offset sub-mass (tower, wing, steeple, dormer) whose faces can point
            # back toward the building centroid while still facing outdoors.
            # Overriding it with the centroid test flipped 18% of wall faces inward
            # (audit_normals.py, user ticket 20260920_235929: "lots of buildings have
            # walls with flipped normals" -- the Christian Science church sits in one of
            # the worst chunks, and it is exactly this shape of building).
            nl = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2) or 1.0
            N = (normal[0] / nl, normal[1] / nl, normal[2] / nl)
        else:
            if abs(n[1]) < 0.35:                    # (near-)vertical face
                if ref is None or away_from_ref(n):
                    N = n
                else:
                    N = (-n[0], -n[1], -n[2])
            else:                                   # roofs / caps: face upward
                N = n if n[1] >= 0.0 else (-n[0], -n[1], -n[2])
        dot = n[0] * N[0] + n[1] * N[1] + n[2] * N[2]
        return ("mirror" if dot > 0.0 else "default"), N

    def add_quad(self, material, p0, p1, p2, p3, normal=None, uvs=None, color=(1.0, 1.0, 1.0, 1.0)):
        """Any vertex order is accepted; winding is derived from geometry (see RULE above).
        `normal`, if given, is the intended OUTWARD/shading normal (flipped if it points into
        the building for vertical faces)."""
        if uvs is None:
            uvs = ((0, 0), (1, 0), (1, 1), (0, 1))
        colors = color if isinstance(color, (list, tuple)) and isinstance(color[0], (list, tuple)) else (color,) * 4
        # Repair "bow-tie" quads (vertex order p0,p1,p2,p3 that visits a corner out of sequence,
        # e.g. the second slope of facade.build_gable_roof): the two triangles then face opposite
        # ways and half of that roof plane was being culled. Swapping p2/p3 restores a proper loop.
        _n1 = self._cross(p0, p1, p2)
        _n2 = self._cross(p0, p2, p3)
        if _n1 is not None and _n2 is not None and (_n1[0] * _n2[0] + _n1[1] * _n2[1] + _n1[2] * _n2[2]) < 0.0:
            p2, p3 = p3, p2
            uvs = (uvs[0], uvs[1], uvs[3], uvs[2])
            colors = (colors[0], colors[1], colors[3], colors[2])
        _mode, normal = self._resolve((p0, p1, p2, p3), normal)
        g = self._grp(material)
        base = len(g["verts"])
        for p, uv, c in zip((p0, p1, p2, p3), uvs, colors):
            self.add_vertex(material, p, normal, uv, c)
        if _mode == "default":
            self.add_tri(material, base, base + 1, base + 2)
            self.add_tri(material, base, base + 2, base + 3)
        else:
            self.add_tri(material, base, base + 2, base + 1)
            self.add_tri(material, base, base + 3, base + 2)

    def add_tri_face(self, material, p0, p1, p2, normal=None, uvs=None, color=(1.0, 1.0, 1.0, 1.0)):
        _mode, normal = self._resolve((p0, p1, p2), normal)
        if uvs is None:
            uvs = ((0, 0), (1, 0), (0.5, 1))
        colors = color if isinstance(color, (list, tuple)) and isinstance(color[0], (list, tuple)) else (color,) * 3
        base = len(self._grp(material)["verts"])
        for p, uv, c in zip((p0, p1, p2), uvs, colors):
            self.add_vertex(material, p, normal, uv, c)
        if _mode == "default":
            self.add_tri(material, base, base + 1, base + 2)
        else:
            self.add_tri(material, base, base + 2, base + 1)

    def add_box(self, material, cx, cz, y0, y1, sx, sz, color=(1.0, 1.0, 1.0, 1.0), yaw=0.0, uv_scale=1.0):
        """Axis-ish aligned box (optionally yawed around Y), sx/sz = full extents."""
        hx, hz = sx / 2.0, sz / 2.0
        ca, sa = math.cos(yaw), math.sin(yaw)
        _saved_ref = getattr(self, "_out_ref", None)
        self._out_ref = (cx, cz)   # a chimney/HVAC box is "outward" relative to ITSELF

        def rot(x, z):
            return (cx + x * ca - z * sa, cz + x * sa + z * ca)

        corners = {}
        for sxn in (-1, 1):
            for szn in (-1, 1):
                x, z = rot(sxn * hx, szn * hz)
                corners[(sxn, szn)] = (x, z)
        # 4 side walls
        order = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        for i in range(4):
            ax, az = corners[order[i]]
            bx, bz = corners[order[(i + 1) % 4]]
            p0 = (ax, y0, az)
            p1 = (bx, y0, bz)
            p2 = (bx, y1, bz)
            p3 = (ax, y1, az)
            w = math.hypot(bx - ax, bz - az)
            self.add_quad(material, p0, p1, p2, p3,
                          uvs=((0, 0), (w * uv_scale, 0), (w * uv_scale, (y1 - y0) * uv_scale), (0, (y1 - y0) * uv_scale)),
                          color=color)
        # top cap
        tl = [( *corners[o], y1) for o in order]
        top_pts = [(p[0], y1, p[1]) for p in [corners[o] for o in order]]
        n_top = (0, 1, 0)
        self.add_quad(material, top_pts[0], top_pts[1], top_pts[2], top_pts[3], normal=n_top, color=color)
        self._out_ref = _saved_ref
        if _saved_ref is None:
            del self._out_ref

    def merged_stats(self):
        return {m: (len(g["verts"]), len(g["indices"]) // 3) for m, g in self.groups.items()}

    def to_json(self):
        out = {}
        for m, g in self.groups.items():
            if not g["indices"]:
                continue
            out[m] = {"verts": g["verts"], "indices": g["indices"]}
        return out


def tri_normal(p0, p1, p2):
    ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return (nx / length, ny / length, nz / length)


# ---------------------------------------------------------------------------
# 2D polygon helpers (x,z plane). Coordinates are plain (x,z) tuples.
# ---------------------------------------------------------------------------
def polygon_area_2d(coords):
    """Signed area (positive = CCW)."""
    a = 0.0
    n = len(coords)
    for i in range(n):
        x0, z0 = coords[i]
        x1, z1 = coords[(i + 1) % n]
        a += x0 * z1 - x1 * z0
    return a * 0.5


def ensure_ccw(coords):
    if polygon_area_2d(coords) < 0:
        return list(reversed(coords))
    return list(coords)


def polygon_centroid_2d(coords):
    x = sum(p[0] for p in coords) / len(coords)
    z = sum(p[1] for p in coords) / len(coords)
    return (x, z)


def dedupe_ring(coords, eps=0.01):
    out = []
    for p in coords:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > eps:
            out.append(p)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < eps:
        out.pop()
    return out


def min_rotated_rect(coords):
    """Returns (corners_ccw[4], center, width, length, yaw_rad) of the minimum-area
    oriented bounding rectangle, width = short side, length = long side."""
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    mrr = poly.minimum_rotated_rectangle
    ext = list(mrr.exterior.coords)[:-1]
    if len(ext) != 4:
        # degenerate (near-collinear) -- fall back to axis-aligned bbox
        xs = [p[0] for p in coords]
        zs = [p[1] for p in coords]
        x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
        ext = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
    ext = ensure_ccw(ext)
    # side lengths
    e0 = math.hypot(ext[1][0] - ext[0][0], ext[1][1] - ext[0][1])
    e1 = math.hypot(ext[2][0] - ext[1][0], ext[2][1] - ext[1][1])
    length = max(e0, e1)
    width = min(e0, e1)
    cx = sum(p[0] for p in ext) / 4.0
    cz = sum(p[1] for p in ext) / 4.0
    if e0 >= e1:
        yaw = math.atan2(ext[1][1] - ext[0][1], ext[1][0] - ext[0][0])
    else:
        yaw = math.atan2(ext[2][1] - ext[1][1], ext[2][0] - ext[1][0])
    return ext, (cx, cz), width, length, yaw


def rect_from_center(cx, cz, width, length, yaw):
    """4 CCW corners of a rectangle: 'length' along local +X (rotated by yaw), 'width' along local +Z."""
    hl, hw = length / 2.0, width / 2.0
    ca, sa = math.cos(yaw), math.sin(yaw)
    local = [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)]
    return [(cx + x * ca - z * sa, cz + x * sa + z * ca) for x, z in local]


def offset_polygon_inward(coords, dist):
    """Inward buffer by dist (meters). Returns None if it collapses."""
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    shr = poly.buffer(-dist, join_style=2)
    if shr.is_empty:
        return None
    if shr.geom_type == "MultiPolygon":
        shr = max(shr.geoms, key=lambda g: g.area)
    return list(shr.exterior.coords)[:-1]


def triangulate_flat(coords):
    """Constrained-ish triangulation (Delaunay + centroid-inside filter) for a
    simple (possibly slightly concave) polygon's flat cap. Returns list of
    ((x0,z0),(x1,z1),(x2,z2)) triangles, CCW."""
    if len(coords) < 3:
        return []
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return []
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    tris = _shapely_triangulate(poly)
    out = []
    for t in tris:
        if not poly.contains(t.centroid) and poly.exterior.distance(t.centroid) > 0.05:
            continue
        pts = list(t.exterior.coords)[:-1]
        if len(pts) != 3:
            continue
        if polygon_area_2d(pts) < 0:
            pts = list(reversed(pts))
        out.append(tuple(pts))
    return out


def split_edge_bays(p0, p1, bay_min=6.0, bay_max=8.0):
    """Split a straight edge into N sub-points so each bay is within
    [bay_min, bay_max] where possible. Returns list of (x,z) points including
    both endpoints (N+1 points for N bays)."""
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if length < bay_min * 1.4:
        return [p0, p1]
    n = max(1, round(length / ((bay_min + bay_max) / 2.0)))
    pts = []
    for i in range(n + 1):
        t = i / n
        pts.append((p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t))
    return pts


def point_in_poly(pt, coords):
    return Polygon(coords).contains(Point(pt))


def nearest_point_on_segment(px, pz, ax, az, bx, bz):
    dx, dz = bx - ax, bz - az
    len2 = dx * dx + dz * dz
    if len2 < 1e-9:
        return ax, az, 0.0
    t = ((px - ax) * dx + (pz - az) * dz) / len2
    t = max(0.0, min(1.0, t))
    return ax + t * dx, az + t * dz, t


def dist_point_to_segment(px, pz, ax, az, bx, bz):
    nx, nz, _ = nearest_point_on_segment(px, pz, ax, az, bx, bz)
    return math.hypot(px - nx, pz - nz)


def rng_for(*parts):
    seed = "|".join(str(p) for p in parts)
    return random.Random(seed)


def chunk_key(x, z, chunk_size):
    return (math.floor(x / chunk_size), math.floor(z / chunk_size))


# ---------------------------------------------------------------------------
# Simple grid-bucketed spatial indices (avoid O(N*M) scans over thousands of
# road segments / polygons for nearest/contains queries).
# ---------------------------------------------------------------------------
class SegmentIndex:
    """Buckets 2D line segments by grid cell for fast nearest-segment queries."""

    def __init__(self, cell=100.0):
        self.cell = cell
        self.buckets = {}
        self.segments = []  # (ax,az,bx,bz, meta)

    def add(self, ax, az, bx, bz, meta=None):
        idx = len(self.segments)
        self.segments.append((ax, az, bx, bz, meta))
        x0, x1 = min(ax, bx), max(ax, bx)
        z0, z1 = min(az, bz), max(az, bz)
        c0x, c1x = math.floor(x0 / self.cell), math.floor(x1 / self.cell)
        c0z, c1z = math.floor(z0 / self.cell), math.floor(z1 / self.cell)
        for cx in range(c0x, c1x + 1):
            for cz in range(c0z, c1z + 1):
                self.buckets.setdefault((cx, cz), []).append(idx)

    def nearest(self, x, z, max_radius=300.0):
        best = None
        best_d = 1e18
        c0 = math.floor(x / self.cell)
        c1 = math.floor(z / self.cell)
        r = 0
        found_any = False
        max_r = int(max_radius / self.cell) + 1
        while r <= max_r:
            for cx in range(c0 - r, c0 + r + 1):
                for cz in range(c1 - r, c1 + r + 1):
                    if r > 0 and c0 - r < cx < c0 + r and c1 - r < cz < c1 + r:
                        continue  # interior already scanned in a previous ring
                    for idx in self.buckets.get((cx, cz), []):
                        ax, az, bx, bz, meta = self.segments[idx]
                        d = dist_point_to_segment(x, z, ax, az, bx, bz)
                        if d < best_d:
                            best_d = d
                            best = (ax, az, bx, bz, meta)
                            found_any = True
            if found_any and best_d <= r * self.cell:
                break
            r += 1
        return best, best_d

    def min_dist(self, x, z, max_radius=60.0):
        _, d = self.nearest(x, z, max_radius)
        return d


class PolyIndex:
    """Buckets polygons (list of (x,z) rings) by bounding box for fast
    point-in-any-polygon / distance-to-nearest tests."""

    def __init__(self, cell=100.0):
        self.cell = cell
        self.buckets = {}
        self.polys = []  # shapely Polygon

    def add(self, coords):
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            return
        idx = len(self.polys)
        self.polys.append(poly)
        x0, z0, x1, z1 = poly.bounds
        for cx in range(math.floor(x0 / self.cell), math.floor(x1 / self.cell) + 1):
            for cz in range(math.floor(z0 / self.cell), math.floor(z1 / self.cell) + 1):
                self.buckets.setdefault((cx, cz), []).append(idx)

    def contains_or_near(self, x, z, margin=0.0):
        cx, cz = math.floor(x / self.cell), math.floor(z / self.cell)
        pt = Point(x, z)
        for dcx in (-1, 0, 1):
            for dcz in (-1, 0, 1):
                for idx in self.buckets.get((cx + dcx, cz + dcz), []):
                    poly = self.polys[idx]
                    if margin > 0:
                        if poly.distance(pt) < margin:
                            return True
                    elif poly.contains(pt):
                        return True
        return False
