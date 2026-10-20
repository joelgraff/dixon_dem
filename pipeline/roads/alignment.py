"""Horizontal alignments: tangents and circular curves through PIs (docs/roadway_control_plan.md §2).

An alignment is the civil-design description of a centreline: a chain of points of intersection
(PIs), the first and last being the ends, with a radius at each interior PI (0 = an angle point,
no curve). Between curves the line is tangent; each curve is a circular arc tangent to both lines,
so the geometry is G1-continuous and is fully defined by the PIs and radii.

Coordinates are Godot metres (x east, z south). A positive deflection turns right in plan view
(north up), a negative one left; offsets are positive to the left of the direction of stationing.

`fit` builds an alignment from a noisy OSM polyline: long straight runs become tangents (total
least squares), the bends between them become one circular curve where one fits, and tangents
within a few degrees of the town's street grid can be snapped to its exact bearing.
"""
import math

import numpy as np
from scipy.spatial import cKDTree

import alignment_geom as geom  # noqa: E402  (the construction, shared with composer_server.py)

EPS = geom.EPS
SLACK_M = geom.SLACK_M
_unit, _deflection, _right = geom.unit, geom.deflection, geom.right


class Alignment:
    """Tangents and arcs through `pis` with `radii` (one per PI; the two ends are ignored)."""

    def __init__(self, pis, radii=None, breaks=()):
        self.pis = [tuple(map(float, p)) for p in pis]
        if len(self.pis) < 2:
            raise ValueError("an alignment needs at least two points")
        n = len(self.pis)
        self.radii = [0.0] * n if radii is None else [float(r) for r in radii]
        if len(self.radii) != n:
            raise ValueError("one radius per PI")
        self.radii[0] = self.radii[-1] = 0.0
        self.breaks = sorted(set(int(i) for i in breaks))
        self._build()

    # -- construction ------------------------------------------------------------------------
    def _build(self):
        self.elements, self.overlaps, self.length, self.pi_sta = geom.build(self.pis, self.radii, self.breaks)

    @property
    def valid(self):
        return not self.overlaps

    # -- evaluation --------------------------------------------------------------------------
    def point_at(self, sta):
        """(x, z, heading) at a station; clamped to the alignment."""
        return geom.point_at(self.elements, self.length, self.pis[-1], sta)

    @staticmethod
    def _arc_point(e, u):
        return geom.arc_point(e, u)

    def sample(self, step=0.25):
        """Stations, points (n, 2) and unit headings (n, 2) every `step`, ends included."""
        n = max(2, int(math.ceil(self.length / step)) + 1)
        stas = np.linspace(0.0, self.length, n)
        pts, dirs = np.empty((n, 2)), np.empty((n, 2))
        if not self.elements:
            pts[:] = self.pis[0]
            dirs[:] = (1.0, 0.0)
            return stas, pts, dirs
        bounds = np.array([e["sta"][1] for e in self.elements])
        which = np.minimum(np.searchsorted(bounds, stas - 1e-9), len(self.elements) - 1)
        for k, e in enumerate(self.elements):
            m = which == k
            if not m.any():
                continue
            u = stas[m] - e["sta"][0]
            if e["type"] == "tangent":
                d = _unit((e["end"][0] - e["start"][0], e["end"][1] - e["start"][1]))
                pts[m, 0] = e["start"][0] + d[0] * u
                pts[m, 1] = e["start"][1] + d[1] * u
                dirs[m] = d
            else:
                c, r = e["center"], e["radius"]
                side = 1.0 if e["delta"] > 0 else -1.0
                a = math.atan2(e["start"][1] - c[1], e["start"][0] - c[0]) + side * u / r
                pts[m, 0] = c[0] + r * np.cos(a)
                pts[m, 1] = c[1] + r * np.sin(a)
                dirs[m, 0] = -np.sin(a) * side
                dirs[m, 1] = np.cos(a) * side
        return stas, pts, dirs

    def projector(self, step=0.25):
        """A function mapping points (n, 2) to (station, left offset, distance) arrays."""
        stas, pts, dirs = self.sample(step)
        tree = cKDTree(pts)

        def project(points):
            q = np.atleast_2d(np.asarray(points, dtype=np.float64))
            dist, idx = tree.query(q)
            d = q - pts[idx]
            along = d[:, 0] * dirs[idx, 0] + d[:, 1] * dirs[idx, 1]
            left = d[:, 0] * dirs[idx, 1] - d[:, 1] * dirs[idx, 0]     # (z, -x) is the left normal
            return np.clip(stas[idx] + along, 0.0, self.length), left, dist

        return project

    def to_json(self):
        def r(v):
            return round(float(v), 3)
        out = []
        for e in self.elements:
            rec = {"type": e["type"], "sta": [r(e["sta"][0]), r(e["sta"][1])],
                   "start": [r(e["start"][0]), r(e["start"][1])], "end": [r(e["end"][0]), r(e["end"][1])]}
            if e.get("break"):
                rec["break"] = True
            if e["type"] == "tangent":
                rec["bearing_deg"] = r(bearing_deg((e["end"][0] - e["start"][0], e["end"][1] - e["start"][1])))
            else:
                rec.update({"radius": r(e["radius"]), "center": [r(e["center"][0]), r(e["center"][1])],
                            "turn": "R" if e["delta"] > 0 else "L",
                            "delta_deg": r(math.degrees(abs(e["delta"])))})
            out.append(rec)
        doc = {"pis": [[r(x), r(z)] for x, z in self.pis], "radii": [r(v) for v in self.radii],
               "length": r(self.length), "elements": out}
        if self.breaks:
            doc["breaks"] = list(self.breaks)
        return doc


def bearing_deg(d):
    """Compass bearing of a heading, degrees clockwise from north (z is south)."""
    return math.degrees(math.atan2(d[0], -d[1])) % 360.0


# ---------------------------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------------------------
def densify(points, step=1.0):
    """The polyline resampled every `step` (its vertices kept), as an (n, 2) array."""
    p = np.asarray(points, dtype=np.float64)
    out = [p[0]]
    for a, b in zip(p[:-1], p[1:]):
        n = max(1, int(math.ceil(np.hypot(*(b - a)) / step)))
        for k in range(1, n + 1):
            out.append(a + (b - a) * k / n)
    return np.array(out)


def douglas_peucker(points, tol):
    """Indices of the vertices Douglas-Peucker keeps at tolerance `tol`."""
    p = np.asarray(points, dtype=np.float64)
    keep = np.zeros(len(p), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(p) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = p[i], p[j]
        ab = b - a
        L = np.hypot(*ab)
        seg = p[i + 1:j] - a
        if L < EPS:
            d = np.hypot(seg[:, 0], seg[:, 1])
        else:
            d = np.abs(seg[:, 0] * ab[1] - seg[:, 1] * ab[0]) / L
        k = int(np.argmax(d))
        if d[k] > tol:
            m = i + 1 + k
            keep[m] = True
            stack.extend([(i, m), (m, j)])
    return np.flatnonzero(keep)


def fit_line(points):
    """Total-least-squares line through points: (centroid, unit direction)."""
    p = np.asarray(points, dtype=np.float64)
    c = p.mean(axis=0)
    if len(p) < 2:
        return c, np.array([1.0, 0.0])
    _, _, vt = np.linalg.svd(p - c)
    return c, vt[0]


def intersect_lines(c1, d1, c2, d2):
    """Intersection of two lines (point, direction), or None when (near) parallel."""
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-9:
        return None
    t = ((c2[0] - c1[0]) * d2[1] - (c2[1] - c1[1]) * d2[0]) / den
    return np.array([c1[0] + d1[0] * t, c1[1] + d1[1] * t])


def project_on_line(p, c, d):
    t = (p[0] - c[0]) * d[0] + (p[1] - c[1]) * d[1]
    return np.array([c[0] + d[0] * t, c[1] + d[1] * t])


def deviation(alignment, points):
    """Distances from points to the alignment."""
    return alignment.projector()(points)[2]


def _seg_dist(q, a, b):
    ab = np.array([b[0] - a[0], b[1] - a[1]])
    L2 = float(ab @ ab)
    if L2 < EPS:
        return np.hypot(q[:, 0] - a[0], q[:, 1] - a[1])
    t = np.clip(((q[:, 0] - a[0]) * ab[0] + (q[:, 1] - a[1]) * ab[1]) / L2, 0.0, 1.0)
    return np.hypot(q[:, 0] - a[0] - t * ab[0], q[:, 1] - a[1] - t * ab[1])


def _local_dev(a, pi, b, radius, points):
    """(rms, max) distance from points to tangent a->TC, the curve at pi, tangent CT->b."""
    q = np.asarray(points, dtype=np.float64)
    din = _unit((pi[0] - a[0], pi[1] - a[1]))
    dout = _unit((b[0] - pi[0], b[1] - pi[1]))
    delta = _deflection(din, dout)
    if radius <= 0 or abs(delta) < 1e-6:
        d = np.minimum(_seg_dist(q, a, pi), _seg_dist(q, pi, b))
    else:
        t = radius * math.tan(abs(delta) / 2.0)
        if t > math.hypot(pi[0] - a[0], pi[1] - a[1]) + 1e-6 or t > math.hypot(b[0] - pi[0], b[1] - pi[1]) + 1e-6:
            return math.inf, math.inf
        tc = (pi[0] - din[0] * t, pi[1] - din[1] * t)
        ct = (pi[0] + dout[0] * t, pi[1] + dout[1] * t)
        side = 1.0 if delta > 0 else -1.0
        rn = _right(din)
        c = (tc[0] + rn[0] * radius * side, tc[1] + rn[1] * radius * side)
        a0 = math.atan2(tc[1] - c[1], tc[0] - c[0])
        th = np.arctan2(q[:, 1] - c[1], q[:, 0] - c[0])
        u = np.mod(side * (th - a0), 2 * math.pi)
        on_arc = u <= abs(delta)
        d_arc = np.where(on_arc, np.abs(np.hypot(q[:, 0] - c[0], q[:, 1] - c[1]) - radius),
                         np.minimum(np.hypot(q[:, 0] - tc[0], q[:, 1] - tc[1]),
                                    np.hypot(q[:, 0] - ct[0], q[:, 1] - ct[1])))
        d = np.minimum(np.minimum(_seg_dist(q, a, tc), _seg_dist(q, ct, b)), d_arc)
    return float(np.sqrt(np.mean(d * d))), float(d.max())


def fit_radius(a, pi, b, points, max_tangent, max_dev=None, radii=None):
    """The radius at `pi` (between a and b) for `points`: (radius, rms, max).

    With `max_dev`, the largest radius whose curve stays within max_dev of every point (the
    smoothest design the data allows); without it, or when none does, the best-fitting radius.
    Radius 0 is an angle point. The curve's tangent length may not exceed `max_tangent`."""
    din = _unit((pi[0] - a[0], pi[1] - a[1]))
    dout = _unit((b[0] - pi[0], b[1] - pi[1]))
    delta = abs(_deflection(din, dout))
    best = (0.0,) + _local_dev(a, pi, b, 0.0, points)
    if delta < 1e-4 or max_tangent <= 0:
        return best
    r_max = max_tangent / math.tan(delta / 2.0)
    if radii is None:
        radii = np.geomspace(2.0, max(2.0, min(r_max, 5000.0)), 48)
    trials = [(float(r),) + _local_dev(a, pi, b, r, points) for r in radii if r <= r_max]
    if max_dev is not None:
        ok = [t for t in trials if t[2] <= max_dev]
        if ok:
            r0 = max(ok)[0]                      # refine upward toward the limit
            for r in np.linspace(r0, min(r0 * 1.15, r_max), 8)[1:]:
                t = (float(r),) + _local_dev(a, pi, b, r, points)
                if t[2] <= max_dev:
                    ok.append(t)
            return max(ok)
    for t in trials:
        if t[1] < best[1]:
            best = t
    if best[0] > 0:                              # refine around the best grid value
        for r in np.linspace(best[0] / 1.15, min(best[0] * 1.15, r_max), 12):
            t = (float(r),) + _local_dev(a, pi, b, r, points)
            if t[1] < best[1]:
                best = t
    return best


def round_radius(r, rounding):
    """`r` rounded to the increment its size calls for: rounding = [[up_to_m, step_m], ...]."""
    for limit, step in rounding:
        if r <= limit:
            return max(step, round(r / step) * step)
    return r


def grid_bearings(tangents, min_length=30.0, window_deg=1.5):
    """Dominant street-grid bearings (mod 90, degrees) from [(direction, length), ...]."""
    bins = np.zeros(360)                         # quarter-degree bins over 90 degrees
    for d, length in tangents:
        if length < min_length:
            continue
        b = bearing_deg(d) % 90.0
        bins[int(b * 4) % 360] += length
    if not bins.any():
        return []
    k = int(window_deg * 4)
    smooth = np.array([bins.take(range(i - k, i + k + 1), mode="wrap").sum() for i in range(360)])
    peaks = []
    total = smooth.sum() / (2 * k + 1)
    for i in np.argsort(-smooth):
        if smooth[i] < 0.08 * total:
            break
        if all(min(abs(i - j), 360 - abs(i - j)) > 4 * k for j in peaks):
            peaks.append(i)
    out = []
    for i in peaks:           # length-weighted mean bearing inside the peak window
        idx = np.arange(i - k, i + k + 1)
        w = bins.take(idx, mode="wrap")
        out.append(float((np.sum(w * idx) / max(w.sum(), EPS) / 4.0) % 90.0))
    return out


def snap_direction(d, grid, tol_deg):
    """`d` rotated onto the nearest grid bearing within tol_deg, or None."""
    b = bearing_deg(d)
    best = None
    for g in grid:
        diff = ((b - g + 45.0) % 90.0) - 45.0
        if abs(diff) <= tol_deg and (best is None or abs(diff) < abs(best)):
            best = diff
    if best is None:
        return None
    a = math.radians(b - best)
    return np.array([math.sin(a), -math.cos(a)])


def fit(points, tol=1.0, grid=(), snap_deg=1.5, rounding=((100, 5), (300, 10), (1e9, 25)),
        dp_tol=0.4, min_tangent=20.0, curve_tol=0.5):
    """Fits an Alignment to a polyline. Returns (alignment, info).

    `tol` is the deviation allowed from the input: merging straight runs, snapping a tangent to
    the grid and rounding a radius are each done only within it. `curve_tol` is how closely one
    curve must fit a bend before it replaces the bend's own vertices. When the simplifications
    together still end up over `tol`, the fit is repeated with tighter merging."""
    curve_tol = min(curve_tol, tol)
    best = None
    for k, merge_tol in enumerate((tol, 0.8 * tol, 0.6 * tol, 0.4 * tol)):
        result = _fit_once(points, tol, merge_tol, grid, snap_deg, rounding, dp_tol, min_tangent, curve_tol)
        result[1]["merge_tol"] = merge_tol
        if best is None or result[1]["max_dev"] < best[1]["max_dev"]:
            best = result
        if result[1]["max_dev"] <= tol:
            return result
    return best


def _fit_once(points, tol, merge_tol, grid, snap_deg, rounding, dp_tol, min_tangent, curve_tol):
    p = np.asarray(points, dtype=np.float64)
    keep = douglas_peucker(p, dp_tol)
    kp = p[keep]
    seg_len = np.hypot(*np.diff(kp, axis=0).T)
    info = {"snapped_tangents": 0, "tangents": 0, "curves": 0, "angle_points": 0}

    # 1. Tangents: the long Douglas-Peucker segments, as TLS lines through the input there;
    #    consecutive ones that one line fits are merged, then each is snapped to the grid
    tangents = []          # (first segment, centroid, direction, last segment)
    for s, L in enumerate(seg_len):
        if L < min_tangent:
            continue
        c, d = _tangent_line(p, keep, s, s)
        tangents.append((s, c, d, s))
    tangents = _merge_tangents(tangents, keep, p, merge_tol)
    if grid:
        for k, (s0, c, d, s1) in enumerate(tangents):
            sd = snap_direction(d, grid, snap_deg)
            if sd is None:
                continue
            pts = densify(p[keep[s0]:keep[s1 + 1] + 1], 1.0)
            dev = np.abs((pts[:, 0] - c[0]) * sd[1] - (pts[:, 1] - c[1]) * sd[0])
            if dev.max() <= tol:
                tangents[k] = (s0, c, sd, s1)
                info["snapped_tangents"] += 1
    info["tangents"] = len(tangents)

    # 2. PIs: the ends, the intersections of consecutive tangents (one curve between them when
    #    it fits), and the Douglas-Peucker vertices of any bend no single curve fits.
    pis, radii, bends = [], [], []
    if not tangents:
        pis = [tuple(v) for v in kp]
        radii = [0.0] * len(pis)
        bends = list(range(1, len(pis) - 1))
    else:
        s0, c0, d0, _ = tangents[0]
        start = project_on_line(p[0], c0, d0) if s0 == 0 else p[0]
        pis.append(tuple(start))
        radii.append(0.0)
        if s0 > 0:                      # leading short segments: keep their vertices
            for v in range(1, s0 + 1):
                pis.append(tuple(kp[v]))
                radii.append(0.0)
                bends.append(len(pis) - 1)
        for (_, ca, da, sa), (sb, cb, db, _) in zip(tangents, tangents[1:]):
            x = intersect_lines(ca, da, cb, db)
            lo, hi = keep[sa + 1], keep[sb]
            between = p[max(lo - 1, 0):hi + 2]
            single = None
            if x is not None:
                # the intersection must lie ahead of tangent a and behind tangent b
                ahead = np.dot(x - kp[sa], da) > 0 and np.dot(kp[sb + 1] - x, db) > 0
                if ahead:
                    a_pt = kp[sa] if sa == 0 else project_on_line(kp[sa], ca, da)
                    b_pt = project_on_line(kp[sb + 1], cb, db)
                    max_t = min(np.hypot(*(x - a_pt)), np.hypot(*(b_pt - x)))
                    seg = densify(between, 0.5)
                    r, rms, mx = fit_radius(a_pt, x, b_pt, seg, max_t, max_dev=curve_tol)
                    if mx <= curve_tol:
                        single = (x, r)
            if single is not None:
                pis.append(tuple(single[0]))
                radii.append(single[1])
                bends.append(len(pis) - 1)
            else:
                # no single PI: keep the bend's own vertices, starting from tangent a's end
                pa = project_on_line(kp[sa + 1], ca, da)
                pb = project_on_line(kp[sb], cb, db)
                inner = [tuple(pa)] + [tuple(kp[v]) for v in range(sa + 2, sb)] + [tuple(pb)]
                for v in inner:
                    if math.hypot(v[0] - pis[-1][0], v[1] - pis[-1][1]) > 0.05:
                        pis.append(v)
                        radii.append(0.0)
                        bends.append(len(pis) - 1)
        _, cl, dl, sl = tangents[-1]
        if sl < len(kp) - 2:            # trailing short segments
            pis.append(tuple(project_on_line(kp[sl + 1], cl, dl)))
            radii.append(0.0)
            bends.append(len(pis) - 1)
            for v in range(sl + 2, len(kp) - 1):
                pis.append(tuple(kp[v]))
                radii.append(0.0)
                bends.append(len(pis) - 1)
            pis.append(tuple(p[-1]))
        else:
            pis.append(tuple(project_on_line(p[-1], cl, dl)))
        radii.append(0.0)

    pis, radii = _drop_duplicate_pis(pis, radii)
    dense = densify(p, 0.5)
    pis, radii = _merge_short_bends(pis, radii, dense, curve_tol, jog_tol=merge_tol)

    # 3. Radii for the bends that are still angle points, each limited to its share of tangent
    idx = _pi_indices(pis, dense)
    for i in range(1, len(pis) - 1):
        if radii[i] > 0:
            continue
        a, pi, b = pis[i - 1], pis[i], pis[i + 1]
        la = math.hypot(pi[0] - a[0], pi[1] - a[1])
        lb = math.hypot(b[0] - pi[0], b[1] - pi[1])
        max_t = min(la * (1.0 if i == 1 else 0.5), lb * (1.0 if i == len(pis) - 2 else 0.5))
        local = _window(dense, idx, i - 1, i + 1)
        r, _, _ = fit_radius(a, pi, b, local, max_t, max_dev=curve_tol)
        radii[i] = r
    radii = _resolve_overlaps(pis, radii)

    # 4. Round radii where the rounding stays inside the tolerance
    al = Alignment(pis, radii)
    for i in range(1, len(pis) - 1):
        if radii[i] <= 0:
            continue
        trial = list(radii)
        trial[i] = round_radius(radii[i], rounding)
        cand = Alignment(pis, trial)
        if cand.valid and deviation(cand, dense).max() <= max(tol, deviation(al, dense).max()):
            radii, al = trial, cand
    info["curves"] = sum(1 for r in radii[1:-1] if r > 0)
    info["angle_points"] = sum(1 for r in radii[1:-1] if r <= 0)
    d = deviation(al, dense)
    info["max_dev"] = float(d.max())
    info["p95_dev"] = float(np.percentile(d, 95))
    return al, info


def _tangent_line(p, keep, s0, s1):
    """TLS line through the input over Douglas-Peucker segments s0..s1, directed along them."""
    pts = densify(p[keep[s0]:keep[s1 + 1] + 1], 1.0)
    m = int(0.15 * len(pts)) if s0 == s1 else 0
    core = pts[m:len(pts) - m] if len(pts) - 2 * m >= 2 else pts
    c, d = fit_line(core)
    if np.dot(d, p[keep[s1 + 1]] - p[keep[s0]]) < 0:
        d = -d
    return c, d


def _merge_tangents(tangents, keep, p, tol):
    """Consecutive tangents that one straight line fits within `tol` become one tangent."""
    out = list(tangents)
    merged = True
    while merged and len(out) > 1:
        merged = False
        for k in range(len(out) - 1):
            s0, s1 = out[k][0], out[k + 1][3]
            c, d = _tangent_line(p, keep, s0, s1)
            pts = densify(p[keep[s0]:keep[s1 + 1] + 1], 1.0)
            dev = np.abs((pts[:, 0] - c[0]) * d[1] - (pts[:, 1] - c[1]) * d[0])
            if dev.max() <= tol:
                out[k:k + 2] = [(s0, c, d, s1)]
                merged = True
                break
    return out


def _merge_short_bends(pis, radii, dense, tol, jog_tol=None, short=8.0):
    """Replaces two PIs a short segment apart by one PI with a curve where one fits within
    `tol`, or by nothing (a straight line) where they are a jog and one fits within `jog_tol`."""
    jog_tol = tol if jog_tol is None else jog_tol
    pis, radii = list(pis), list(radii)
    changed = True
    while changed:
        changed = False
        idx = _pi_indices(pis, dense)
        for i in range(1, len(pis) - 2):
            p0, p1, p2, p3 = (np.array(pis[k]) for k in (i - 1, i, i + 1, i + 2))
            if np.hypot(*(p2 - p1)) >= short:
                continue
            d1, d2 = _unit(p1 - p0), _unit(p3 - p2)
            x = intersect_lines(p0, d1, p2, d2)
            if x is None or abs(_deflection(d1, d2)) < math.radians(3.0):
                # parallel: a jog; one straight line through both, if it fits
                local = _window(dense, idx, i - 1, i + 2)
                c, d = fit_line(np.array([p0, p3]))
                dev = np.abs((local[:, 0] - c[0]) * d[1] - (local[:, 1] - c[1]) * d[0])
                if dev.max() <= jog_tol:
                    del pis[i:i + 2]
                    del radii[i:i + 2]
                    changed = True
                    break
                continue
            if np.dot(x - p0, d1) <= 0 or np.dot(p3 - x, d2) <= 0:
                continue
            local = _window(dense, idx, i - 1, i + 2)
            max_t = min(np.hypot(*(x - p0)), np.hypot(*(p3 - x)))
            r, _, mx = fit_radius(tuple(p0), tuple(x), tuple(p3), local, max_t, max_dev=tol)
            if mx <= tol:
                pis[i:i + 2] = [tuple(x)]
                radii[i:i + 2] = [r]
                changed = True
                break
    return pis, radii


def _drop_duplicate_pis(pis, radii, min_gap=0.05):
    out_p, out_r = [pis[0]], [radii[0]]
    for p, r in zip(pis[1:], radii[1:]):
        if math.hypot(p[0] - out_p[-1][0], p[1] - out_p[-1][1]) > min_gap:
            out_p.append(p)
            out_r.append(r)
    out_r[0] = out_r[-1] = 0.0
    # interior PIs with (near) zero deflection carry nothing
    i = 1
    while i < len(out_p) - 1:
        din = _unit((out_p[i][0] - out_p[i - 1][0], out_p[i][1] - out_p[i - 1][1]))
        dout = _unit((out_p[i + 1][0] - out_p[i][0], out_p[i + 1][1] - out_p[i][1]))
        if abs(_deflection(din, dout)) < 1e-4:
            del out_p[i]
            del out_r[i]
        else:
            i += 1
    return out_p, out_r


def _pi_indices(pis, dense):
    """For each PI, the index of the nearest input point, searched forward along the input.

    Each search starts where the previous PI's ended and looks ahead only as far as the PI
    could be, so a route that loops back past itself is not matched to its other pass."""
    cum = np.r_[0.0, np.cumsum(np.hypot(*np.diff(dense, axis=0).T))]
    out = [0]
    for k in range(1, len(pis)):
        lo = out[-1]
        reach = cum[lo] + 1.5 * math.hypot(pis[k][0] - pis[k - 1][0], pis[k][1] - pis[k - 1][1]) + 20.0
        hi = max(lo + 1, int(np.searchsorted(cum, reach)))
        seg = dense[lo:hi + 1]
        out.append(lo + int(np.argmin(np.hypot(seg[:, 0] - pis[k][0], seg[:, 1] - pis[k][1]))))
    out[-1] = len(dense) - 1
    return out


def _window(dense, idx, i, j):
    """The input points from PI i to PI j (by _pi_indices), at least two."""
    a, b = idx[i], idx[j]
    if b - a < 1:
        a, b = max(0, a - 1), min(len(dense) - 1, b + 1)
    return dense[a:b + 1]


def _resolve_overlaps(pis, radii, frozen=()):
    """Shrinks radii until no two curves claim the same tangent. PIs in `frozen` (pinned by hand)
    keep their radius; if their curves alone overlap, ValueError."""
    radii = list(radii)
    frozen = set(frozen)
    for _ in range(50):
        al = Alignment(pis, radii)
        if al.valid:
            return radii
        for i in al.overlaps:
            movable = [k for k in (i, i - 1) if 1 <= k <= len(pis) - 2 and k not in frozen]
            if frozen and not any(radii[k] > 0 for k in movable):
                raise ValueError("the pinned curves at PIs %d and %d overlap" % (i - 1, i))
            for k in movable:
                radii[k] *= 0.85
    if frozen:
        raise ValueError("could not resolve overlapping curves around the pinned PIs")
    return [0.0 if 0 < k < len(pis) - 1 else r for k, r in enumerate(radii)]
