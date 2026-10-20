"""Tangent-and-curve geometry of a horizontal alignment, in plain Python (no numpy).

The construction behind alignment.Alignment (PIs + radii -> tangents and circular arcs), kept free
of numpy and scipy so composer_server.py, which runs under the system Python, can validate and
read alignments with the very same maths. Bridge Composer's js/alignment.js is a port of this
file, held to it by tests/fixtures/alignment_parity.json (dump_alignment_parity.py).

Coordinates are Godot metres (x east, z south). A positive deflection turns right in plan view
(north up); stations run along the line from its first PI.
"""
import math

EPS = 1e-9
SLACK_M = 0.005     # curves may overrun their tangent by this much (coordinates are stored to the mm)


def unit(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > EPS else (0.0, 0.0)


def deflection(din, dout):
    """Signed angle from din to dout, radians; positive turns right in plan view (z south)."""
    return math.atan2(din[0] * dout[1] - din[1] * dout[0], din[0] * dout[0] + din[1] * dout[1])


def right(d):
    """The right-hand normal of a heading, in plan view."""
    return (-d[1], d[0])


def build(pis, radii, breaks=()):
    """(elements, overlaps, length, pi_sta) of the alignment through `pis` with `radii`.

    elements: dicts {type: tangent|arc, sta: (s0, s1), start, end} plus, for an arc, center,
    radius, delta (signed radians) and pi (the PI's index). overlaps: indices of PIs whose curve
    needs more tangent than the neighbouring curves leave. `breaks` are PI indices i whose segment to PI i+1 is
    a break (a jog through an intersection): its tangent element carries "break": True. pi_sta[i]: (s0, s1), the stations of
    PI i's curve (PC, PT), or of the PI itself twice where it is an angle point or an end."""
    p = pis
    n = len(p)
    elements, overlaps = [], []
    pi_sta = [None] * n
    cur = p[0]
    sta = 0.0
    pi_sta[0] = (0.0, 0.0)

    def tangent(a, b, s):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length > 1e-9:
            elements.append({"type": "tangent", "sta": (s, s + length), "start": a, "end": b})
        return s + length

    for i in range(1, n - 1):
        din = unit((p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1]))
        dout = unit((p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1]))
        delta = deflection(din, dout)
        r = radii[i]
        if r > 0 and abs(delta) > 1e-6:
            t = r * math.tan(abs(delta) / 2.0)
            tc = (p[i][0] - din[0] * t, p[i][1] - din[1] * t)
            ct = (p[i][0] + dout[0] * t, p[i][1] + dout[1] * t)
            # the tangent before this curve must not run backwards
            along = (tc[0] - cur[0]) * din[0] + (tc[1] - cur[1]) * din[1]
            if along < -SLACK_M:
                overlaps.append(i)
            if along > 0:
                sta = tangent(cur, tc, sta)
            side = 1.0 if delta > 0 else -1.0
            rn = right(din)
            center = (tc[0] + rn[0] * r * side, tc[1] + rn[1] * r * side)
            length = r * abs(delta)
            elements.append({"type": "arc", "sta": (sta, sta + length), "start": tc, "end": ct,
                             "center": center, "radius": r, "delta": delta, "pi": i})
            pi_sta[i] = (sta, sta + length)
            sta += length
            cur = ct
        else:
            sta = tangent(cur, p[i], sta)
            cur = p[i]
            pi_sta[i] = (sta, sta)
    dl = unit((p[-1][0] - p[-2][0], p[-1][1] - p[-2][1]))
    last = (p[-1][0] - cur[0]) * dl[0] + (p[-1][1] - cur[1]) * dl[1]
    if n > 2 and last < -SLACK_M:
        overlaps.append(n - 2)
    if last > 0 or n == 2:
        sta = tangent(cur, p[-1], sta)
    pi_sta[-1] = (sta, sta)
    for i in breaks:
        for e in elements:
            if e["type"] == "tangent" and e["start"] == p[i] and e["end"] == p[i + 1]:
                e["break"] = True
    return elements, overlaps, sta, pi_sta


def arc_point(e, u):
    """(x, z, heading) at distance u along arc element e."""
    c, r, delta = e["center"], e["radius"], e["delta"]
    side = 1.0 if delta > 0 else -1.0
    a0 = math.atan2(e["start"][1] - c[1], e["start"][0] - c[0])
    a = a0 + side * u / r
    return c[0] + r * math.cos(a), c[1] + r * math.sin(a), (-math.sin(a) * side, math.cos(a) * side)


def point_at(elements, length, last_pi, sta):
    """(x, z, heading) at a station, clamped to [0, length]."""
    sta = min(max(sta, 0.0), length)
    for e in elements:
        if sta <= e["sta"][1] + 1e-9 or e is elements[-1]:
            u = sta - e["sta"][0]
            if e["type"] == "tangent":
                d = unit((e["end"][0] - e["start"][0], e["end"][1] - e["start"][1]))
                return e["start"][0] + d[0] * u, e["start"][1] + d[1] * u, d
            return arc_point(e, u)
    return last_pi[0], last_pi[1], (1.0, 0.0)


def curve_data(pis, radii, i):
    """R, T, delta, L of the curve at PI i (zeros where there is none)."""
    din = unit((pis[i][0] - pis[i - 1][0], pis[i][1] - pis[i - 1][1]))
    dout = unit((pis[i + 1][0] - pis[i][0], pis[i + 1][1] - pis[i][1]))
    delta = deflection(din, dout)
    r = radii[i]
    if r <= 0 or abs(delta) <= 1e-6:
        return {"R": 0.0, "T": 0.0, "delta": delta, "L": 0.0}
    return {"R": r, "T": r * math.tan(abs(delta) / 2.0), "delta": delta, "L": r * abs(delta)}


def validate_breaks(breaks, radii):
    """The sorted unique PI indices of `breaks` (segment i -> i+1 is a break), or ValueError. A break's two PIs
    are angle points (radius 0)."""
    if breaks is None:
        return []
    if not isinstance(breaks, list) or len(breaks) > 100:
        raise ValueError("breaks is a list of PI indices")
    out = []
    for i in breaks:
        if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(radii) - 1:
            raise ValueError("a break is the index of a PI that has a next PI")
        if radii[i] > 0 or radii[i + 1] > 0:
            raise ValueError("the PIs of a break must have radius 0")
        out.append(i)
    return sorted(set(out))


def validate(pis, radii, keep_ends=False):
    """(pis, radii) as floats, or ValueError unless pis [[x, z], ...] and radii describe a usable
    alignment. The end radii are zeroed (they mean nothing at an end) unless `keep_ends`: the PIs at
    the ends of a pinned stretch are interior PIs of their route and keep theirs."""
    if not isinstance(pis, list) or not isinstance(radii, list):
        raise ValueError("pis and radii must be lists")
    if not 2 <= len(pis) <= 500:
        raise ValueError("an alignment needs between 2 and 500 PIs")
    if len(radii) != len(pis):
        raise ValueError("one radius per PI")
    pts = []
    for p in pis:
        if not (isinstance(p, (list, tuple)) and len(p) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in p)):
            raise ValueError("a PI is [x, z]")
        if abs(p[0]) > 1e6 or abs(p[1]) > 1e6:
            raise ValueError("a PI is out of range")
        pts.append((float(p[0]), float(p[1])))
    rad = []
    for r in radii:
        if not (isinstance(r, (int, float)) and not isinstance(r, bool) and math.isfinite(r)) or r < 0:
            raise ValueError("radii must be numbers >= 0")
        rad.append(float(r))
    if not keep_ends:
        rad[0] = rad[-1] = 0.0
    for k, (a, b) in enumerate(zip(pts, pts[1:])):
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 0.05:
            raise ValueError(f"PIs {k} and {k + 1} are less than 5 cm apart")
    _, overlaps, _, _ = build(pts, rad)
    if overlaps:
        raise ValueError("the curves at PI " + ", ".join(str(i) for i in overlaps)
                         + " need more tangent than the neighbouring curves leave: reduce a radius")
    return pts, rad


def load_elements(rows):
    """Elements as build() makes them, from the `elements` of alignments.json (Alignment.to_json)."""
    out = []
    for e in rows:
        el = {"type": e["type"], "sta": tuple(e["sta"]), "start": tuple(e["start"]), "end": tuple(e["end"])}
        if e["type"] == "arc":
            el.update(center=tuple(e["center"]), radius=e["radius"],
                      delta=math.radians(e["delta_deg"]) * (1.0 if e["turn"] == "R" else -1.0))
        out.append(el)
    return out
