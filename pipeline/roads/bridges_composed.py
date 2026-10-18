"""A bridge designed in Bridge Composer, built in place of the generated flat deck.

Bridge Composer's "Send to game" writes game/data/bridges_composed/<way id>.json
(schema: docs/bridge_composer_schema.md). Unlike a composed building, the file
carries the *design* -- centreline, deck profile, supports, spans -- not a mesh, so
it stays editable and this module is the one place the geometry is generated.
Composer's preview mirrors these rules; tests/fixtures keep the two honest.

Coordinates are Godot metres: x east, z south, y up. Stations are metres along
the centreline from its first point. Triangles are wound for Godot (front face
clockwise) with the vertex normal pointing the way the face looks.
"""
import bisect
import json
import math
import os


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COMPOSED_DIR = os.path.join(ROOT, "game", "data", "bridges_composed")
FORMAT = "dixon-bridge"
VERSION = 1

# Materials the road bake knows (game/roads/tools/build_roads.gd MATERIAL_PATHS).
MATERIALS = (
    "bridge_deck", "curb_concrete", "sidewalk_concrete", "asphalt_road", "steel_rusted",
    "stone_foundation", "limestone", "gravel_ballast",
)
DEFAULT_MATERIALS = {
    "deck": "bridge_deck", "sidewalk": "sidewalk_concrete", "barrier": "curb_concrete",
    "structure": "curb_concrete", "rail": "steel_rusted", "arch": "limestone",
}
SPAN_TYPES = ("girder", "slab", "arch")
SUPPORT_KINDS = ("abutment", "pier")
PIER_SHAPES = ("rect", "bullnose")
# Roads sit this far above the terrain they are built on (build_road_plan.ROAD_Y_BIAS; the road plan's
# tests keep the two equal). A deck's end heights are the road surface, so the terrain under the
# approach is conformed this far below them.
ROAD_SURFACE_M = 0.085
# The approach sidewalk is laid this far below the road surface beside it (the road plan puts roads at
# +0.085 and sidewalks at +0.05), so a walkway on the bridge is this far below the deck top to be level
# with the sidewalk it continues.
WALKWAY_RISE_M = -0.035
WALKWAY_SIDES = ("both", "left", "right")
STEP_M = 3.0          # longest deck/edge sample interval along the centreline
ARCH_STEP_M = 1.5
EPS = 1e-6


class BridgeError(ValueError):
    pass


def MeshBuild():  # noqa: N802 -- stands in for the class, imported when first used
    """common_roads pulls in numpy; loading and validating a design (the save server)
    should not need it, so it is imported only when a mesh is built."""
    from common_roads import MeshBuild as real
    return real()


def path_for(bid, directory=None):
    return os.path.join(directory or COMPOSED_DIR, f"{bid}.json")


def load(bid, directory=None):
    """The composed bridge for this way id, or None if there is none (or it is unusable)."""
    path = path_for(bid, directory)
    if bid is None or not os.path.exists(path):
        return None
    try:
        with open(path) as handle:
            data = json.load(handle)
        validate(data)
    except (OSError, ValueError):
        return None
    return data


def _num(value, what, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BridgeError(f"{what} must be a number")
    if low is not None and value < low:
        raise BridgeError(f"{what} must be at least {low}")
    if high is not None and value > high:
        raise BridgeError(f"{what} must be at most {high}")
    return float(value)


def centerline_length(centerline):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(centerline, centerline[1:]))


def validate(data):
    """Raises BridgeError unless `data` is a bridge this module can build. Returns `data`."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BridgeError("not a composed bridge")
    if data.get("version") != VERSION:
        raise BridgeError(f"unsupported version {data.get('version')!r}")
    if not isinstance(data.get("id"), str) or not data["id"]:
        raise BridgeError("id must be a string")
    line = data.get("centerline")
    if not isinstance(line, list) or not 2 <= len(line) <= 500:
        raise BridgeError("centerline needs 2 to 500 points")
    for p in line:
        if not isinstance(p, list) or len(p) != 2:
            raise BridgeError("centerline points are [x, z]")
        _num(p[0], "centerline x")
        _num(p[1], "centerline z")
    length = centerline_length(line)
    if length < 3.0:
        raise BridgeError("centerline is shorter than 3 m")

    deck = data.get("deck")
    if not isinstance(deck, dict):
        raise BridgeError("deck is required")
    _num(deck.get("width"), "deck.width", 1.0, 60.0)
    _num(deck.get("thickness", 0.3), "deck.thickness", 0.05, 3.0)
    elev = deck.get("elevation")
    if not isinstance(elev, list) or not elev:
        raise BridgeError("deck.elevation needs at least one [station, y]")
    last = -1.0
    for row in elev:
        if not isinstance(row, list) or len(row) != 2:
            raise BridgeError("deck.elevation rows are [station, y]")
        s = _num(row[0], "deck.elevation station", -EPS, length + 0.5)
        _num(row[1], "deck.elevation y", -50.0, 500.0)
        if s <= last:
            raise BridgeError("deck.elevation stations must increase")
        last = s

    supports = data.get("supports")
    if not isinstance(supports, list) or len(supports) < 2:
        raise BridgeError("supports needs at least two (the two abutments)")
    last = -1.0
    for sup in supports:
        if not isinstance(sup, dict) or sup.get("kind") not in SUPPORT_KINDS:
            raise BridgeError(f"support kind must be one of {SUPPORT_KINDS}")
        s = _num(sup.get("station"), "support.station", -EPS, length + 0.5)
        if s <= last:
            raise BridgeError("supports must be in increasing station order")
        last = s
        _num(sup.get("length", 1.5), "support.length", 0.2, 30.0)
        if sup.get("width") is not None:
            _num(sup["width"], "support.width", 0.2, 80.0)
        if sup.get("bottom") is not None:
            _num(sup["bottom"], "support.bottom", -50.0, 500.0)
        if sup.get("shape", "rect") not in PIER_SHAPES:
            raise BridgeError(f"support shape must be one of {PIER_SHAPES}")
    if supports[0]["kind"] != "abutment" or supports[-1]["kind"] != "abutment":
        raise BridgeError("the first and last supports must be abutments")

    spans = data.get("spans")
    if not isinstance(spans, list) or len(spans) != len(supports) - 1:
        raise BridgeError("spans needs one entry between each pair of supports")
    for span in spans:
        if not isinstance(span, dict) or span.get("type") not in SPAN_TYPES:
            raise BridgeError(f"span type must be one of {SPAN_TYPES}")
        _num(span.get("depth", 0.9), "span.depth", 0.05, 8.0)
        _num(span.get("haunch", 0.0), "span.haunch", 0.0, 6.0)
        if span["type"] == "arch":
            _num(span.get("rise"), "span.rise", 0.3, 40.0)
            _num(span.get("ring", 0.6), "span.ring", 0.1, 4.0)
            if span.get("springing") is not None:
                _num(span["springing"], "span.springing", -50.0, 500.0)

    section = data.get("cross_section", {})
    if not isinstance(section, dict):
        raise BridgeError("cross_section must be an object")
    _num(section.get("barrier_h", 0.9), "cross_section.barrier_h", 0.0, 3.0)
    _num(section.get("barrier_w", 0.4), "cross_section.barrier_w", 0.05, 4.0)
    _num(section.get("barrier_rail_h", 0.0), "cross_section.barrier_rail_h", 0.0, 3.0)
    _num(section.get("walkway_w", 0.0), "cross_section.walkway_w", 0.0, 10.0)
    _num(section.get("walkway_rise", WALKWAY_RISE_M), "cross_section.walkway_rise", -0.5, 1.0)
    if section.get("walkway_sides", "both") not in WALKWAY_SIDES:
        raise BridgeError(f"cross_section.walkway_sides must be one of {WALKWAY_SIDES}")
    _num(section.get("parapet_w", 0.35), "cross_section.parapet_w", 0.05, 2.0)
    _num(section.get("parapet_h", 0.6), "cross_section.parapet_h", 0.0, 3.0)
    _num(section.get("rail_h", 0.0), "cross_section.rail_h", 0.0, 3.0)
    lamps = data.get("lamps")
    if lamps is not None:
        if not isinstance(lamps, dict):
            raise BridgeError("lamps must be an object")
        _num(lamps.get("spacing"), "lamps.spacing", 5.0, 200.0)

    names = data.get("materials", {})
    if not isinstance(names, dict):
        raise BridgeError("materials must be an object")
    for role, name in names.items():
        if role not in DEFAULT_MATERIALS:
            raise BridgeError(f"unknown material role {role!r}")
        if name not in MATERIALS:
            raise BridgeError(f"no road material {name!r}; known: {', '.join(MATERIALS)}")
    return data


def crest_profile(length, start_y, end_y, crest, step=5.0):
    """Deck elevation rows [[station, y], ...] for a smooth vertical curve: the straight line
    between the two end heights plus a parabola `crest` metres high at midspan.

    One long parabolic crest is how a bridge deck is cambered: the grade eases continuously
    from end to end (steepest, 4 * crest / length plus the line's own slope, at the abutments)
    instead of ramping up quickly and running flat. The same rows come from Bridge
    Composer's js/model.js crestProfile, which the editor shows."""
    n = max(2, int(math.ceil(length / step)))
    rows = []
    for k in range(n + 1):
        t = k / n
        y = start_y + (end_y - start_y) * t + 4.0 * crest * t * (1.0 - t)
        rows.append([round(length * t, 2), round(y, 3)])
    return rows


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
class _Line:
    """The centreline with arclength stations: position, tangent, and left normal."""

    def __init__(self, pts):
        self.pts = [(float(p[0]), float(p[1])) for p in pts]
        self.cum = [0.0]
        for a, b in zip(self.pts, self.pts[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.length = self.cum[-1]

    def at(self, s):
        s = max(0.0, min(self.length, s))
        i = min(max(bisect.bisect_right(self.cum, s) - 1, 0), len(self.pts) - 2)
        a, b = self.pts[i], self.pts[i + 1]
        seg = self.cum[i + 1] - self.cum[i]
        t = (s - self.cum[i]) / seg if seg > EPS else 0.0
        dx, dz = (b[0] - a[0]) / max(seg, EPS), (b[1] - a[1]) / max(seg, EPS)
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), (dx, dz), (-dz, dx)

    def stations(self, a, b, step):
        n = max(1, int(math.ceil((b - a) / step)))
        out = [a + (b - a) * k / n for k in range(n + 1)]
        # keep the polyline's vertices so a bend isn't cut across
        inner = [c for c in self.cum if a + EPS < c < b - EPS]
        return sorted(set(round(v, 4) for v in out + inner))


class _Elevation:
    def __init__(self, rows):
        self.s = [r[0] for r in rows]
        self.y = [r[1] for r in rows]

    def at(self, s):
        if s <= self.s[0]:
            return self.y[0]
        if s >= self.s[-1]:
            return self.y[-1]
        i = bisect.bisect_right(self.s, s) - 1
        t = (s - self.s[i]) / (self.s[i + 1] - self.s[i])
        return self.y[i] + (self.y[i + 1] - self.y[i]) * t


class _Out:
    """Emits correctly wound, correctly lit quads into the per-material meshes."""

    def __init__(self, mb_by_mat):
        self.mb = mb_by_mat

    def quad(self, material, a, b, c, d, normal):
        """a..d are (x, y, z, u, v) around the quad; the face looks along `normal`."""
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = a[:3], b[:3], c[:3]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        rh = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        if rh[0] * normal[0] + rh[1] * normal[1] + rh[2] * normal[2] > 0.0:
            a, b, c, d = a, d, c, b      # Godot's front face is the clockwise one
        sub = MeshBuild()
        ids = [sub.add_vertex(p[0], p[1], p[2], normal, p[3], p[4]) for p in (a, b, c, d)]
        sub.add_quad(*ids)
        if not sub.is_empty():
            self.mb.setdefault(material, MeshBuild()).extend(sub)

    def strip(self, material, left, right, normal):
        """A strip between two polylines of (x, y, z, u, v) of equal length."""
        for i in range(len(left) - 1):
            self.quad(material, left[i], left[i + 1], right[i + 1], right[i], normal)

    def box(self, material, corners, faces=None):
        """corners: 8 (x,y,z) with 0-3 the bottom ring and 4-7 the top ring, in order around."""
        cx = sum(p[0] for p in corners) / 8.0
        cy = sum(p[1] for p in corners) / 8.0
        cz = sum(p[2] for p in corners) / 8.0
        quads = ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
        for q in quads:
            p = [corners[i] for i in q]
            e1 = (p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2])
            e2 = (p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2])
            n = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
            ln = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
            if ln < EPS:
                continue
            n = (n[0] / ln, n[1] / ln, n[2] / ln)
            mx = sum(v[0] for v in p) / 4.0 - cx
            my = sum(v[1] for v in p) / 4.0 - cy
            mz = sum(v[2] for v in p) / 4.0 - cz
            if n[0] * mx + n[1] * my + n[2] * mz < 0.0:
                n = (-n[0], -n[1], -n[2])
            self.quad(material, (*p[0], 0.0, 0.0), (*p[1], 1.0, 0.0), (*p[2], 1.0, 1.0), (*p[3], 0.0, 1.0), n)


def _oriented_box(center, t, n, half_along, half_across, y0, y1):
    """Corners of a box: `half_along` of it lies along tangent t, `half_across` along normal n."""
    ring = []
    for sa, sc in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        ring.append((center[0] + t[0] * half_along * sa + n[0] * half_across * sc,
                     center[1] + t[1] * half_along * sa + n[1] * half_across * sc))
    return [(x, y0, z) for x, z in ring] + [(x, y1, z) for x, z in ring]


def _arch_profile(span_a, span_b, crown_y, rise, steps=None):
    """Intrados height along a circular-segment arch from station span_a to span_b."""
    chord = span_b - span_a
    rise = min(rise, chord * 0.5)
    radius = (chord * chord / 4.0 + rise * rise) / (2.0 * rise)
    cy = crown_y - radius
    mid = (span_a + span_b) * 0.5

    def y(s):
        d = min(abs(s - mid), chord * 0.5)
        return cy + math.sqrt(max(radius * radius - d * d, 0.0))
    return y


def build(mb_by_mat, furniture, data, ground=None):
    """Adds the bridge to `mb_by_mat` / `furniture`.

    `ground(x, z)` is the terrain height, used for where a support meets the ground
    and for warning when the deck ends don't meet the approach roads.
    Returns {"profile": [[station, y], ...], "warnings": [str, ...]} -- the profile
    is the deck height by station, written to bridge_profiles.json for dressing built
    outside the road plan.
    """
    validate(data)
    out = _Out(mb_by_mat)
    line = _Line(data["centerline"])
    deck = data["deck"]
    elev = _Elevation(deck["elevation"])
    road_half = deck["width"] / 2.0
    thick = deck.get("thickness", 0.3)
    mats = dict(DEFAULT_MATERIALS)
    mats.update(data.get("materials", {}))
    section = data.get("cross_section", {})
    barrier_h = section.get("barrier_h", 0.9)
    barrier_w = section.get("barrier_w", 0.4)
    barrier_rail_h = section.get("barrier_rail_h", 0.0)
    walk_w = section.get("walkway_w", 0.0)
    walk_sides = section.get("walkway_sides", "both")
    walk_rise = section.get("walkway_rise", WALKWAY_RISE_M)
    parapet_w = section.get("parapet_w", 0.35)
    parapet_h = section.get("parapet_h", 0.6)
    rail_h = section.get("rail_h", 0.0)

    def side_info(side):
        """Across the deck, outward from the roadway: barrier, then (with a walkway) the walkway and
        a parapet. Offsets are from the centreline, positive to the left of travel."""
        walk = walk_w > 0.0 and walk_sides in ("both", "left" if side > 0 else "right")
        b_out = road_half + barrier_w
        w_out = b_out + walk_w if walk else b_out
        return {"walk": walk, "b_out": b_out, "w_out": w_out, "edge": w_out + parapet_w if walk else b_out}

    left, right = side_info(1), side_info(-1)
    overall = left["edge"] + right["edge"]

    def edge_top(info):
        """Where the structure's fascia ends at an outer edge: the walkway surface, or the deck."""
        return walk_rise if info["walk"] else 0.0
    supports = data["supports"]
    spans = data["spans"]
    warnings = []

    def pt(s, off, y, u=None, v=None):
        (x, z), _t, n = line.at(s)
        return (x + n[0] * off, y, z + n[1] * off, s if u is None else u, off if v is None else v)

    def vstrip(material, s_list, off, y_top_fn, y_bot_fn, face):
        """A wall face at lateral offset `off`, looking left (+1) or right (-1)."""
        top = [pt(s, off, y_top_fn(s), s, y_top_fn(s)) for s in s_list]
        bot = [pt(s, off, y_bot_fn(s), s, y_bot_fn(s)) for s in s_list]
        for i in range(len(s_list) - 1):
            (_x, _z), _t, n = line.at((s_list[i] + s_list[i + 1]) * 0.5)
            out.quad(material, bot[i], bot[i + 1], top[i + 1], top[i], (n[0] * face, 0.0, n[1] * face))

    # --- supports, then what hangs between them ---------------------------
    soffit = {}   # span index -> underside height function (for the supports' tops)
    for i, span in enumerate(spans):
        a, b = supports[i]["station"], supports[i + 1]["station"]
        kind = span["type"]
        ss = line.stations(a, b, ARCH_STEP_M if kind == "arch" else STEP_M)
        if kind in ("girder", "slab"):
            depth = span.get("depth", 0.9 if kind == "girder" else thick)
            haunch = span.get("haunch", 0.0)

            def under(s, a=a, b=b, depth=depth, haunch=haunch):
                t = (s - a) / max(b - a, EPS)
                return elev.at(s) - depth - haunch * math.cos(math.pi * t) ** 2
            soffit[i] = under
            out.strip(mats["structure"], [pt(s, -right["edge"], under(s)) for s in ss],
                      [pt(s, left["edge"], under(s)) for s in ss], (0.0, -1.0, 0.0))
            vstrip(mats["structure"], ss, left["edge"], lambda s: elev.at(s) + edge_top(left), under, 1)
            vstrip(mats["structure"], ss, -right["edge"], lambda s: elev.at(s) + edge_top(right), under, -1)
        else:
            crown = elev.at((a + b) * 0.5) - span.get("ring", 0.6) - 0.3
            intrados = _arch_profile(a, b, crown, span["rise"])
            soffit[i] = intrados
            out.strip(mats["arch"], [pt(s, -right["edge"], intrados(s)) for s in ss],
                      [pt(s, left["edge"], intrados(s)) for s in ss], (0.0, -1.0, 0.0))
            vstrip(mats["arch"], ss, left["edge"], lambda s: elev.at(s) + edge_top(left), intrados, 1)
            vstrip(mats["arch"], ss, -right["edge"], lambda s: elev.at(s) + edge_top(right), intrados, -1)

    for k, sup in enumerate(supports):
        s = sup["station"]
        (x, z), t, n = line.at(s)
        length = sup.get("length", 1.5)
        width = sup.get("width") or (overall if sup["kind"] == "abutment" else overall * 0.7)
        # top of the support meets the underside of the span(s) it carries
        tops = []
        if k > 0 and (k - 1) in soffit:
            tops.append(soffit[k - 1](s))
        if k < len(spans) and k in soffit:
            tops.append(soffit[k](s))
        top = min(tops) + 0.02 if tops else elev.at(s) - thick
        if sup["kind"] == "abutment":
            top = elev.at(s) - 0.02   # the back wall carries the deck's end and the approach fill
        if sup.get("bottom") is not None:
            bottom = sup["bottom"]
        elif ground is not None:
            bottom = ground(x, z) - 0.5
        else:
            bottom = top - 6.0
        if bottom >= top - 0.1:
            warnings.append(f"support {k} (station {s:.1f}) has no height: ground {bottom:.2f} meets the deck at {top:.2f}")
            continue
        centre = (x, z)
        if sup["kind"] == "abutment":
            # a back wall that steps outward, away from the span, to hold the approach
            outward = -1.0 if k == 0 else 1.0
            centre = (x + t[0] * outward * length * 0.5, z + t[1] * outward * length * 0.5)
        if sup.get("shape", "rect") == "bullnose" and sup["kind"] == "pier":
            _bullnose(out, mats["structure"], centre, t, n, length, width, bottom, top)
        else:
            out.box(mats["structure"], _oriented_box(centre, t, n, length / 2.0, width / 2.0, bottom, top))
        if ground is not None and sup["kind"] == "abutment":
            gy = ground(x, z)
            if abs(gy - elev.at(s)) > 0.6:
                warnings.append(
                    f"deck is {elev.at(s):.2f} at the {'start' if k == 0 else 'end'} but the ground "
                    f"there is {gy:.2f}: the approach road will not meet it")

    # --- deck surface, barriers, walkways, parapets, rails ---------------
    ss = line.stations(0.0, line.length, STEP_M)
    ss = sorted(set(ss + [round(sup["station"], 4) for sup in supports]))
    out.strip(mats["deck"], [pt(s, -road_half, elev.at(s)) for s in ss],
              [pt(s, road_half, elev.at(s)) for s in ss], (0.0, 1.0, 0.0))

    def band(material, side, o_a, o_b, y_fn):
        out.strip(material, [pt(s, side * o_a, y_fn(s)) for s in ss], [pt(s, side * o_b, y_fn(s)) for s in ss],
                  (0.0, 1.0, 0.0))

    def rail(side, offset, y_fn, height):
        """A thin steel rail `height` above y_fn, drawn as a ribbon facing both ways."""
        low = lambda s: y_fn(s) + height  # noqa: E731
        high = lambda s: low(s) + 0.08  # noqa: E731
        vstrip(mats["rail"], ss, side * offset, high, low, side)
        vstrip(mats["rail"], ss, side * offset, high, low, -side)

    for side, info in ((1, left), (-1, right)):
        base = elev.at
        barrier_top = lambda s: elev.at(s) + barrier_h  # noqa: E731
        walk_y = lambda s: elev.at(s) + walk_rise  # noqa: E731
        if barrier_h > 0.0:
            vstrip(mats["barrier"], ss, side * road_half, barrier_top, base, -side)          # faces the roadway
            vstrip(mats["barrier"], ss, side * info["b_out"], barrier_top, walk_y if info["walk"] else base, side)
            band(mats["barrier"], side, road_half, info["b_out"], barrier_top)
            if info["walk"] and barrier_rail_h > 0.0:
                rail(side, road_half + barrier_w / 2.0, barrier_top, barrier_rail_h)
        if info["walk"]:
            band(mats["sidewalk"], side, info["b_out"], info["w_out"], walk_y)
            if parapet_h > 0.0:
                parapet_top = lambda s: walk_y(s) + parapet_h  # noqa: E731
                vstrip(mats["barrier"], ss, side * info["w_out"], parapet_top, walk_y, -side)   # faces the walkway
                vstrip(mats["barrier"], ss, side * info["edge"], parapet_top, walk_y, side)     # the outer face
                band(mats["barrier"], side, info["w_out"], info["edge"], parapet_top)
                if rail_h > 0.0:
                    rail(side, info["w_out"] + parapet_w / 2.0, parapet_top, rail_h)
        elif rail_h > 0.0 and barrier_h > 0.0:
            rail(side, road_half + barrier_w / 2.0, barrier_top, rail_h)

    lamps = data.get("lamps")
    if lamps:
        spacing = lamps["spacing"]
        count = max(1, int(line.length // spacing))
        for k in range(count + 1):
            s = min(line.length, k * line.length / count)
            (x, z), _t, n = line.at(s)
            for side, info in ((-1, right), (1, left)):
                if info["walk"]:
                    off, y = (info["w_out"] - 0.35) * side, elev.at(s) + walk_rise
                else:
                    off, y = (road_half + barrier_w * 0.5) * side, elev.at(s) + barrier_h
                furniture.setdefault("lamp_downtown", []).append([x + n[0] * off, y, z + n[1] * off, 0.0])

    profile = [[round(s, 2), round(elev.at(s), 3)] for s in ss]
    return {"profile": profile, "warnings": warnings}


def _bullnose(out, material, centre, t, n, length, width, y0, y1, segs=6):
    """A pier whose two ends (left and right of the deck) are half-round."""
    r = length / 2.0
    straight = max(width / 2.0 - r, 0.0)
    ring = []
    for end in (1, -1):
        for k in range(segs + 1):
            ang = math.pi * k / segs
            # sweeps from one flank, round the end, to the other
            along = math.cos(ang) * r * end
            across = (straight + math.sin(ang) * r) * end
            ring.append((centre[0] + t[0] * along + n[0] * across, centre[1] + t[1] * along + n[1] * across))
    m = len(ring)
    cx = sum(p[0] for p in ring) / m
    cz = sum(p[1] for p in ring) / m
    for i in range(m):
        a, b = ring[i], ring[(i + 1) % m]
        nx, nz = (b[1] - a[1]), -(b[0] - a[0])
        ln = math.hypot(nx, nz)
        if ln < EPS:
            continue
        nx, nz = nx / ln, nz / ln
        if nx * ((a[0] + b[0]) / 2 - cx) + nz * ((a[1] + b[1]) / 2 - cz) < 0.0:
            nx, nz = -nx, -nz
        out.quad(material, (a[0], y0, a[1], 0.0, y0), (b[0], y0, b[1], 1.0, y0),
                 (b[0], y1, b[1], 1.0, y1), (a[0], y1, a[1], 0.0, y1), (nx, 0.0, nz))
    # top cap as a fan
    for i in range(m):
        a, b = ring[i], ring[(i + 1) % m]
        sub = MeshBuild()
        up = (0.0, 1.0, 0.0)
        ids = [sub.add_vertex(cx, y1, cz, up), sub.add_vertex(a[0], y1, a[1], up), sub.add_vertex(b[0], y1, b[1], up)]
        rh_y = (a[1] - cz) * (b[0] - cx) - (a[0] - cx) * (b[1] - cz)  # y of (a-c)x(b-c)
        if rh_y > 0.0:
            ids = [ids[0], ids[2], ids[1]]
        sub.add_tri(*ids)
        if not sub.is_empty():
            out.mb.setdefault(material, MeshBuild()).extend(sub)
