#!/usr/bin/env python3
"""Cross-section templates on route station ranges, and the design roads built from them
(docs/roadway_control_plan.md §4, phase 3a).

A template is the typical section of a route over a station range: curb-to-curb width, its
lane and parking split, the gutter flag and curb, and the parkway and sidewalk behind the curb.
Widths come from each route's width record in alignments.json (the aerial survey's curb-to-curb,
rounded to the foot, or the OSM width tag where the survey fell back to it), the roadside from
design_standards.json's `roadside` profiles, and anything can be overridden per route and
station range in alignment_overrides.json's `templates`.

`design_roads(roads)` is what the consumers read: roads.json with every drivable way that lies on
a route re-drawn along the route's alignment (tangents and arcs, densified) instead of its OSM
nodes, ending at the junction control points, and with each vertex's template half-width
(`hw`, tapered where the width changes) and the way's design width in `tags.width_m`.

Writes:
  game/data/templates.json                 template ranges per route
  game/roads/_build/templates_report.json  width sources, sections, tapers, design-road fit

Run: ../../.venv/bin/python templates.py
"""
import hashlib
import json
import math
import os
import sys

import numpy as np
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import common as pc  # noqa: E402
from osm_common import HIGHWAY_DEFAULTS  # noqa: E402
import alignment as al  # noqa: E402

OUT_PATH = os.path.join(pc.GAME_DATA, "templates.json")
REPORT_PATH = os.path.join(pc.ROOT, "game", "roads", "_build", "templates_report.json")
ALIGNMENTS_PATH = os.path.join(pc.GAME_DATA, "alignments.json")
ROADS_PATH = os.path.join(pc.GAME_DATA, "roads.json")
STANDARDS_PATH = os.path.join(HERE, "design_standards.json")
OVERRIDES_PATH = os.path.join(HERE, "alignment_overrides.json")

CURBED = {"residential", "primary", "secondary", "tertiary", "unclassified",
          "primary_link", "tertiary_link"}     # service, alley, track: no curb (flush apron)
DOWNTOWN_STREET_WORDS = ("galena", "1st", "first", "2nd", "second", "3rd", "third", "hennepin", "peoria")
DOWNTOWN_BOUNDS = (1330.0, -1780.0, 1920.0, -1030.0)  # x0,z0,x1,z1
OVERRIDE_KEYS = {"route", "sta", "note", "curb_to_curb_m", "curb_to_curb_ft", "lanes", "parking",
                 "gutter", "curb", "section", "parkway_m", "sidewalk_m"}

TANGENT_STEP_M = 2.0       # design vertices along a tangent
ARC_CHORD_ERR_M = 0.02     # ... and along an arc, as close as this to the true curve
SEGMENT_MAX_DEV_M = 3.0    # an OSM run further than this from its route keeps its OSM line
KEPT_SNAP_MAX_M = 3.0      # a run kept on its OSM line moves its end onto a shared node only this far
SNAP_BLEND_MIN_M = 6.0     # a run end moved onto a shared node bends back over at least this ...
SNAP_BLEND_PER_M = 8.0     # ... or this many times the move


def load_json(path):
    with open(path) as handle:
        return json.load(handle)


def fingerprint(paths):
    h = hashlib.sha256()
    for p in paths:
        with open(p, "rb") as handle:
            h.update(handle.read())
    return h.hexdigest()[:16]


def is_downtown(name, x, z):
    name = (name or "").lower()
    if not any(w in name for w in DOWNTOWN_STREET_WORDS):
        return False
    x0, z0, x1, z1 = DOWNTOWN_BOUNDS
    return x0 <= x <= x1 and z0 <= z <= z1


def load_overrides(path=OVERRIDES_PATH):
    """alignment_overrides.json's `templates`, by route: [{sta?, fields...}, ...]."""
    if not os.path.exists(path):
        return {}
    data = load_json(path)
    out = {}
    for o in data.get("templates", []):
        unknown = set(o) - OVERRIDE_KEYS
        if unknown:
            raise ValueError(f"template override for {o.get('route')}: unknown keys {sorted(unknown)}")
        if o.get("gutter") not in (None, "overlaid", "visible"):
            raise ValueError(f"template override for {o['route']}: gutter is 'overlaid' or 'visible'")
        if o.get("curb") not in (None, "new", "older"):
            raise ValueError(f"template override for {o['route']}: curb is 'new' or 'older'")
        if o.get("section") not in (None, "downtown", "residential", "uncurbed"):
            raise ValueError(f"template override for {o['route']}: section is downtown, residential or uncurbed")
        out.setdefault(o["route"], []).append(o)
    return out


# ---------------------------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------------------------
def round_width(w, step):
    return round(max(1, int(round(w / step))) * step, 3)


def lane_split(c2c, cls, oneway, curbed, cs, lanes=None, parking=None):
    """Travel lanes and parking for a curb-to-curb width: (lanes, lane_m, parking sides).

    Parking goes in (both sides, then one) while the travel lanes stay at least the class's
    lane_width_min; the lane count is the even number (one-way: any number) nearest to what the
    remaining width holds at the class lane width."""
    lane_w = cs["lane_width"][cls]
    lane_min = cs["lane_width_min"][cls]
    park_w = cs["parking_lane_width"]
    base = 1 if oneway else 2

    def count(rest):
        n = max(base, int(round(rest / lane_w)))
        if not oneway and n % 2:
            n = n + 1 if rest / (n + 1) >= lane_min else max(base, n - 1)
        return n

    sides = [2, 1, 0] if curbed and parking is None else [parking or 0]
    for p in sides:
        rest = c2c - p * park_w
        n = lanes or count(rest)
        if rest / n >= lane_min or p == sides[-1]:
            return n, round(rest / n, 3), p
    raise AssertionError("unreachable")


def gutter_state(width_rec, cs):
    """'visible' when the aerial saw the flag on a clear majority of the route's blocks."""
    if not width_rec:
        return cs["gutter_default"], "default"
    votes = [g for b in width_rec.get("block_detail", []) for g in b["gutter"] if g]
    if not votes:
        return cs["gutter_default"], "default"
    visible = votes.count("visible")
    return ("visible" if visible > 0.6 * len(votes) else "overlaid"), "aerial"


def taper_length(shift_m, speed_mph, cs):
    """AASHTO lane-shift taper L = W S^2 / 60 (feet, mph) for a curb line shifting `shift_m`."""
    ft = 0.3048
    return max(cs["taper"]["min_m"], abs(shift_m) / ft * speed_mph ** 2 / 60.0 * ft)


CLASS_WIDTH_MIN_ROUTES = 3   # a class median needs at least this many measured routes


def class_widths(alignments, standards):
    """Curb-to-curb width per class where the aerial could not measure a route: the median of the
    class's measured routes, rounded to the foot (two class lanes where too few were measured)."""
    cs = standards["cross_section"]
    step = cs.get("width_rounding", 0.3048)
    out = {}
    for cls in standards["classes"]:
        ws = [r["width"]["curb_to_curb_m"] for r in alignments["routes"]
              if r["class"] == cls and (r.get("width") or {}).get("source") == "aerial"]
        if len(ws) >= CLASS_WIDTH_MIN_ROUTES:
            out[cls] = {"curb_to_curb_m": round_width(float(np.median(ws)), step), "measured_routes": len(ws)}
        else:
            out[cls] = {"curb_to_curb_m": None, "measured_routes": len(ws)}
    return out


def _class_of(highway, standards):
    for name, spec in standards["classes"].items():
        if highway in spec["osm_highway"]:
            return name
    return None


def osm_width(tags):
    """The way's width from a real OSM width or lanes tag, or None where roads.json only has the
    importer's class default (osm_common.HIGHWAY_DEFAULTS)."""
    w = tags.get("width_m")
    default = HIGHWAY_DEFAULTS.get(tags.get("highway"), (None, None))[1]
    if not w or (default is not None and abs(w - default) < 0.05):
        return None
    return w


def route_templates(rec, ways_by_id, standards, overrides=(), widths=None):
    """The route's template ranges, in station order, each covering one or more of its ways."""
    cs = standards["cross_section"]
    step = cs.get("width_rounding", 0.3048)
    cls = rec["class"]
    width = rec.get("width")
    gutter, gutter_source = gutter_state(width, cs)
    a = None
    ranges = []
    for wref in sorted(rec["ways"], key=lambda w: w["sta"][0]):
        w = ways_by_id.get(wref["id"])
        if w is None:
            continue
        tags = w["tags"]
        s0, s1 = wref["sta"]
        if a is None:
            a = al.Alignment(rec["pis"], rec["radii"])
        mx, mz, _ = a.point_at((s0 + s1) / 2)
        curbed = tags.get("highway") in CURBED
        bridge = bool(tags.get("bridge"))
        way_cls = _class_of(tags.get("highway"), standards) or cls
        class_w = (widths or {}).get(way_cls, {}).get("curb_to_curb_m")
        tagged = osm_width(tags)
        if width and width.get("source") == "aerial" and not bridge:
            c2c, source = width["curb_to_curb_m"], "aerial"
        elif bridge or tagged:
            c2c, source = round_width(tags.get("width_m") or 2 * cs["lane_width"][cls], step), "osm_tag"
        elif class_w:
            c2c, source = class_w, "class_median"
        elif way_cls == "service" and tags.get("width_m"):
            c2c, source = round_width(tags["width_m"], step), "osm_default"
        else:
            park = 2 * cs["parking_lane_width"] if curbed else 0.0
            c2c, source = round_width(2 * cs["lane_width"][way_cls] + park, step), "class_lanes"
        section = ("downtown" if is_downtown(tags.get("name"), mx, mz) else "residential") if curbed else "uncurbed"
        ranges.append({"sta": [s0, s1], "ways": [wref["id"]], "bridge": bridge, "section": section,
                       "curb_to_curb_m": c2c, "width_source": source,
                       "gutter": gutter if curbed else None, "gutter_source": gutter_source if curbed else None,
                       "curb": cs["curb_default"] if curbed else None, "override": None,
                       "oneway": bool(tags.get("oneway")),
                       "lanes_tag": int(tags["lanes"]) if tagged and tags.get("lanes") else None,
                       "no_parking": str(tags.get("highway", "")).endswith("_link")})
    # the ways' station ranges abut at the junctions between them; overlaps (a way listed twice
    # on a looping route) keep the first
    for r in overrides:
        ranges = _apply_override(ranges, r, step)
    out = []
    for r in ranges:
        if out and _same(out[-1], r) and abs(out[-1]["sta"][1] - r["sta"][0]) < 0.05:
            out[-1]["sta"][1] = r["sta"][1]
            out[-1]["ways"] += [w for w in r["ways"] if w not in out[-1]["ways"]]
            continue
        out.append(dict(r, sta=list(r["sta"]), ways=list(r["ways"])))
    speed = standards["classes"][cls]["design_speed_mph"]
    for prev, r in zip(out, out[1:]):
        shift = (r["curb_to_curb_m"] - prev["curb_to_curb_m"]) / 2
        r["taper_m"] = round(taper_length(shift, speed, cs), 2) if abs(shift) > 1e-3 else 0.0
    for r in out:
        r.setdefault("taper_m", 0.0)
        _complete(r, cls, cs)
    return out


def _same(a, b):
    keys = ("bridge", "section", "curb_to_curb_m", "gutter", "curb", "override", "oneway", "lanes_tag", "no_parking",
            "lanes", "parking", "parkway_m", "sidewalk_m")
    return all(a.get(k) == b.get(k) for k in keys)


def _apply_override(ranges, o, step):
    lo, hi = o.get("sta", [-math.inf, math.inf])
    out = []
    for r in ranges:
        s0, s1 = r["sta"]
        cuts = sorted({s0, s1} | {s for s in (lo, hi) if s0 < s < s1})
        for a, b in zip(cuts, cuts[1:]):
            piece = dict(r, sta=[a, b], ways=list(r["ways"]))
            if a >= lo - 1e-6 and b <= hi + 1e-6:
                if "curb_to_curb_ft" in o:
                    piece["curb_to_curb_m"], piece["width_source"] = round(o["curb_to_curb_ft"] * 0.3048, 3), "override"
                if "curb_to_curb_m" in o:
                    piece["curb_to_curb_m"], piece["width_source"] = round_width(o["curb_to_curb_m"], step), "override"
                for key in ("lanes", "parking", "parkway_m", "sidewalk_m", "section", "curb"):
                    if key in o:
                        piece[key] = o[key]
                if "gutter" in o:
                    piece["gutter"], piece["gutter_source"] = o["gutter"], "override"
                piece["override"] = o.get("note") or "override"
            out.append(piece)
    return out


def _complete(r, cls, cs):
    """Fills in the derived components of a template range."""
    curbed = r["section"] != "uncurbed"
    lanes, lane_m, parking = lane_split(r["curb_to_curb_m"], cls, r["oneway"],
                                        curbed and not r["bridge"] and not r.pop("no_parking", False), cs,
                                        r.get("lanes") or r.pop("lanes_tag", None), r.get("parking"))
    r.pop("lanes_tag", None)
    r.update({"lanes": lanes, "lane_m": lane_m, "parking": parking,
              "parking_m": cs["parking_lane_width"] if parking else 0.0, "crown": cs["crown"]})
    if curbed:
        side = cs["roadside"][r["section"]]
        r["gutter_m"] = cs["gutter_width"]
        r["gutter_visible_m"] = cs["gutter_overlaid_visible_width"] if r["gutter"] == "overlaid" else cs["gutter_width"]
        r["curb_reveal_m"] = cs["curb_reveal_older"] if r["curb"] == "older" else cs["curb_reveal"]
        r["curb_width_m"] = cs["curb_width"]
        r.setdefault("parkway_m", side["parkway"])
        r.setdefault("sidewalk_m", side["sidewalk"])
    else:
        r.update({"gutter_m": 0.0, "gutter_visible_m": 0.0, "curb_reveal_m": 0.0, "curb_width_m": 0.0})
        r.setdefault("parkway_m", 0.0)
        r.setdefault("sidewalk_m", 0.0)


def build(alignments=None, roads=None, standards=None, overrides=None):
    alignments = alignments or load_json(ALIGNMENTS_PATH)
    roads = roads or load_json(ROADS_PATH)
    standards = standards or load_json(STANDARDS_PATH)
    overrides = load_overrides() if overrides is None else overrides
    ways_by_id = {w["id"]: w for w in roads["ways"]}
    known = {r["id"] for r in alignments["routes"]}
    missing = sorted(set(overrides) - known)
    if missing:
        raise ValueError(f"template overrides for unknown routes: {missing}")
    widths = class_widths(alignments, standards)
    routes = {rec["id"]: route_templates(rec, ways_by_id, standards, overrides.get(rec["id"], ()), widths)
              for rec in alignments["routes"]}
    return {"format": "dixon-templates", "version": 1,
            "inputs": {"alignments.json+roads.json+design_standards.json+alignment_overrides.json":
                       fingerprint([ALIGNMENTS_PATH, ROADS_PATH, STANDARDS_PATH, OVERRIDES_PATH])},
            "class_widths": widths, "routes": routes}


def load(path=OUT_PATH):
    doc = load_json(path)
    if doc.get("format") != "dixon-templates":
        raise ValueError(f"{path}: not a dixon-templates file")
    return doc


def template_at(ranges, sta):
    """The template range holding `sta` (the nearest one past the ends)."""
    for r in ranges:
        if sta <= r["sta"][1] + 1e-6:
            return r
    return ranges[-1]


def half_width_at(ranges, sta):
    """Half the curb-to-curb width at `sta`, tapered linearly across each width change (the
    taper is centred on the range break)."""
    hw = None
    for i, r in enumerate(ranges):
        if sta <= r["sta"][1] + 1e-6 or i == len(ranges) - 1:
            hw = r["curb_to_curb_m"] / 2
            break
    for prev, r in zip(ranges, ranges[1:]):
        L = r.get("taper_m") or 0.0
        if L <= 0 or prev["bridge"] or r["bridge"]:
            continue
        b = r["sta"][0]
        if b - L / 2 <= sta <= b + L / 2:
            t = (sta - (b - L / 2)) / L
            return prev["curb_to_curb_m"] / 2 * (1 - t) + r["curb_to_curb_m"] / 2 * t
    return hw


# ---------------------------------------------------------------------------------------------
# Design roads
# ---------------------------------------------------------------------------------------------
def densify_stations(a, s0, s1):
    """Stations from s0 to s1 (either way round) at which to place design vertices: element
    boundaries, tangents every TANGENT_STEP_M and arcs close enough to stay within
    ARC_CHORD_ERR_M of the curve."""
    lo, hi = min(s0, s1), max(s0, s1)
    out = [lo, hi]
    for e in a.elements:
        e0, e1 = e["sta"]
        if e1 <= lo or e0 >= hi:
            continue
        x0, x1 = max(e0, lo), min(e1, hi)
        out += [x0, x1]
        step = TANGENT_STEP_M if e["type"] == "tangent" else min(
            TANGENT_STEP_M, math.sqrt(8.0 * e["radius"] * ARC_CHORD_ERR_M))
        n = int(math.ceil((x1 - x0) / step))
        out += list(np.linspace(x0, x1, n + 1)[1:-1])
    out = np.unique(np.round(out, 6))
    keep = [out[0]]
    for s in out[1:]:
        if s - keep[-1] > 0.05:
            keep.append(s)
    keep[-1] = hi
    return keep if s0 <= s1 else keep[::-1]


class _RouteGeom:
    def __init__(self, rec, ranges):
        self.rec = rec
        self.ranges = ranges
        self.a = al.Alignment(rec["pis"], rec["radii"])
        self.stas, self.pts, _ = self.a.sample(0.25)
        self.way_ranges = {}
        for w in rec["ways"]:
            self.way_ranges.setdefault(w["id"], []).append(w["sta"])

    def end_candidates(self, xy, leg_stations=(), past_edge=False):
        """Stations a run's end may take on this route: each place the route passes nearest to it
        (a route can pass a point twice, around a loop), a junction's leg stations, and for an end
        past the play edge the route's own ends."""
        d = np.hypot(self.pts[:, 0] - xy[0], self.pts[:, 1] - xy[1])
        lo = np.r_[True, d[1:] <= d[:-1]] & np.r_[d[:-1] <= d[1:], True]
        keep = lo & (d <= min(d.min() + 2.0, 8.0))
        out = list(self.stas[keep]) + list(leg_stations)
        if past_edge:
            out += [0.0, self.a.length]
        merged = []
        for s in sorted(out):
            if not merged or s - merged[-1] > 1.0:
                merged.append(s)
        return merged

    def stretch_fit(self, s0, s1, probe):
        """How well the alignment from s0 to s1 matches the run's points: the mean distance both
        ways (run to stretch and stretch to run), so a stretch that runs past the run (around a
        loop, or on to the next street) scores as badly as one off to the side."""
        lo, hi = min(s0, s1), max(s0, s1)
        m = (self.stas >= lo) & (self.stas <= hi)
        if m.sum() < 2:
            return None
        stretch = self.pts[m]
        d1, _ = cKDTree(stretch).query(probe)
        d2, _ = cKDTree(probe).query(stretch)
        return 0.5 * (float(d1.mean()) + float(d2.mean()))

    def project(self, way_id, points):
        """Stations and distances of `points` on this route, held to the way's station ranges."""
        m = np.zeros(len(self.stas), dtype=bool)
        for s0, s1 in self.way_ranges.get(way_id, ()):
            m |= (self.stas >= s0 - 10.0) & (self.stas <= s1 + 10.0)
        if not m.any():
            return None, None
        stas, pts = self.stas[m], self.pts[m]
        q = np.asarray(points, dtype=np.float64)
        d2 = ((q[:, None, :] - pts[None, :, :]) ** 2).sum(axis=2)
        i = d2.argmin(axis=1)
        return stas[i], np.sqrt(d2[np.arange(len(q)), i])


def _extend(end, before, osm_vertices, far):
    """A vertex continuing the line from `before` through `end` by the OSM vertices' length;
    `far` is the OSM vertex it stands in for (its height and node are kept)."""
    length = sum(math.hypot(b["x"] - a["x"], b["z"] - a["z"]) for a, b in zip(osm_vertices, osm_vertices[1:]))
    dx, dz = end["x"] - before["x"], end["z"] - before["z"]
    d = math.hypot(dx, dz) or 1.0
    return {"x": end["x"] + dx / d * length, "y": far["y"], "z": end["z"] + dz / d * length,
            "node_id": far.get("node_id"), "hw": end["hw"]}


def _snap_end(part, end, xz):
    """Moves the run's end onto `xz`, spreading the move back along the run over
    SNAP_BLEND_PER_M times its size (at least SNAP_BLEND_MIN_M) so it bends instead of kinking."""
    v = part[end]
    dx, dz = xz[0] - v["x"], xz[1] - v["z"]
    v["snap"] = (dx, dz)
    length = max(SNAP_BLEND_MIN_M, SNAP_BLEND_PER_M * math.hypot(dx, dz))
    order = part if end == 0 else part[::-1]
    acc = np.r_[0.0, np.cumsum([math.hypot(q["x"] - p["x"], q["z"] - p["z"]) for p, q in zip(order, order[1:])])]
    for q, d in zip(order, acc):
        if d >= length:
            break
        t = d / length
        f = 1.0 - t * t * (3.0 - 2.0 * t)
        q["x"] += dx * f
        q["z"] += dz * f


def design_roads(roads=None, alignments=None, templates=None, bounds=None):
    """roads.json with the drivable ways that lie on routes re-drawn along their alignments.

    Each way is cut at its ends and at its junction nodes; each run between them is matched to
    the route (of those that list the way) it lies closest to, and replaced by that route's
    alignment between the run's end stations. Run ends at a junction sit on the junction's
    control point; other shared ends are averaged. A run further than SEGMENT_MAX_DEV_M from
    every route, or with a vertex outside `bounds` (the play heightmap), keeps its OSM vertices.
    Every vertex gets `hw`, half the template's curb-to-curb width (OSM width tag on runs that
    kept their OSM line), and the way's `tags.width_m` becomes twice the median of those.

    Returns (roads, report)."""
    roads = roads or load_json(ROADS_PATH)
    alignments = alignments or load_json(ALIGNMENTS_PATH)
    templates = templates or load()
    if bounds is None:
        from build_road_plan import VALID_BOUNDS as bounds
    x0b, z0b, x1b, z1b = bounds
    geoms = {rec["id"]: _RouteGeom(rec, templates["routes"][rec["id"]])
             for rec in alignments["routes"] if templates["routes"].get(rec["id"])}
    by_way = {}
    for rid, g in geoms.items():
        for wid in g.way_ranges:
            by_way.setdefault(wid, []).append(rid)
    junction_nodes = {j["node_id"] for j in roads["junction_nodes"]}
    cps = {}
    for j in alignments["junctions"]:
        cps[j["node_id"]] = {"xz": (j["x"], j["z"]), "legs": {}, "through": {}}
        for leg in j["legs"]:
            cps[j["node_id"]]["legs"].setdefault(leg["route"], []).append(leg["sta"])
            cps[j["node_id"]]["through"].setdefault(leg["route"], []).append(leg["through"])

    # pass 1: each run's route and end stations
    runs = []
    for w in roads["ways"]:
        if w["id"] not in by_way or w["tags"].get("bridge"):
            continue
        vs = w["vertices"]
        cut = [0] + [i for i in range(1, len(vs) - 1)
                     if vs[i].get("node_id") in junction_nodes or vs[i].get("node_id") in cps] + [len(vs) - 1]
        for i0, i1 in zip(cut, cut[1:]):
            pts = np.array([(v["x"], v["z"]) for v in vs[i0:i1 + 1]])
            inside = (pts[:, 0] >= x0b) & (pts[:, 0] <= x1b) & (pts[:, 1] >= z0b) & (pts[:, 1] <= z1b)
            # a run crossing the play edge: the route stops at the edge, so only the part inside
            # is matched, and the OSM vertices past the edge stay on (consumers clip them)
            head = int(np.argmax(inside)) if inside.any() else 0
            tail = int(np.argmax(inside[::-1])) if inside.any() else 0
            dense = al.densify(pts, 1.0)
            dense_in = (dense[:, 0] >= x0b) & (dense[:, 0] <= x1b) & (dense[:, 1] >= z0b) & (dense[:, 1] <= z1b)
            first, last = (int(np.argmax(dense_in)), len(dense) - int(np.argmax(dense_in[::-1]))) if dense_in.any() else (0, 0)
            contiguous = dense_in.sum() >= 2 and dense_in[first:last].all()
            run = {"way": w, "i0": i0, "i1": i1, "route": None, "head": head, "tail": tail}
            if contiguous:
                probe = dense[first:last]
                ends = (vs[i0], vs[i1])
                best = None
                for rid in by_way[w["id"]]:
                    g = geoms[rid]
                    cands = []
                    for k, v in enumerate(ends):
                        legs = cps.get(v.get("node_id"), {}).get("legs", {}).get(rid, [])
                        past = head if k == 0 else tail
                        cands.append(g.end_candidates((v["x"], v["z"]), legs, past))
                    for s0 in cands[0]:
                        for s1 in cands[1]:
                            if abs(s1 - s0) <= 0.05:
                                continue
                            fit = g.stretch_fit(s0, s1, probe)
                            if fit is not None and (best is None or fit < best[0]):
                                best = (fit, rid, s0, s1)
                if best is not None and best[0] <= SEGMENT_MAX_DEV_M:
                    run.update(route=best[1], s0=best[2], s1=best[3])
            runs.append(run)

    # shared end positions: where the routes through the node have it (their mean), and the
    # routes that end there snap onto it. The control point itself is not used: where two routes
    # meet nearly end to end it is an ill-conditioned line intersection metres off both.
    occ = {}
    for run in runs:
        if run["route"] is None:
            continue
        g = geoms[run["route"]]
        for k, s, past in ((run["i0"], run["s0"], run["head"]), (run["i1"], run["s1"], run["tail"])):
            nid = run["way"]["vertices"][k].get("node_id")
            if nid is not None and not past:
                x, z, _ = g.a.point_at(s)
                legs = [l for l in cps.get(nid, {}).get("through", {}).get(run["route"], [])]
                through = nid not in cps or any(legs)
                occ.setdefault(nid, []).append((x, z, through))
    node_xz = {}
    for nid, pts in occ.items():
        held = [(x, z) for x, z, t in pts if t] or [(x, z) for x, z, _ in pts]
        node_xz[nid] = tuple(np.mean(held, axis=0))
    # bridge decks are built from their OSM ways, so an approach ends exactly on the deck's end
    for w in roads["ways"]:
        if w["tags"].get("bridge"):
            for v in (w["vertices"][0], w["vertices"][-1]):
                if v.get("node_id") in node_xz:
                    node_xz[v["node_id"]] = (v["x"], v["z"])

    # pass 2: rebuild each way's vertices
    by_id = {}
    for run in runs:
        by_id.setdefault(run["way"]["id"], []).append(run)
    out_ways = []
    snaps = []
    replaced_m = kept_m = 0.0
    for w in roads["ways"]:
        if w["id"] not in by_id:
            out_ways.append(w)
            continue
        vs = w["vertices"]
        osm_hw = (w["tags"].get("width_m") or 6.0) / 2
        new = []
        for run in by_id[w["id"]]:
            seg = vs[run["i0"]:run["i1"] + 1]
            if run["route"] is None:
                part = [dict(v, hw=osm_hw) for v in seg]
                for end in (0, -1):        # its ends still meet the design runs at shared nodes
                    xz = node_xz.get(part[end].get("node_id"))
                    if xz and math.hypot(xz[0] - part[end]["x"], xz[1] - part[end]["z"]) <= KEPT_SNAP_MAX_M:
                        _snap_end(part, end, xz)
                kept_m += sum(math.hypot(b["x"] - a["x"], b["z"] - a["z"]) for a, b in zip(seg, seg[1:])
                              if x0b <= a["x"] <= x1b and z0b <= a["z"] <= z1b)
            else:
                g = geoms[run["route"]]
                stas = densify_stations(g.a, run["s0"], run["s1"])
                ys = np.interp(np.linspace(0, 1, len(stas)), np.linspace(0, 1, len(seg)), [v["y"] for v in seg])
                part = []
                for n, (s, y) in enumerate(zip(stas, ys)):
                    x, z, _ = g.a.point_at(s)
                    part.append({"x": x, "y": float(y), "z": z, "node_id": None, "sta": round(float(s), 3),
                                 "route": run["route"], "hw": half_width_at(g.ranges, s)})
                for end, v, past in ((0, seg[0], run["head"]), (-1, seg[-1], run["tail"])):
                    if past:
                        continue
                    nid = v.get("node_id")
                    part[end]["node_id"] = nid
                    if nid in node_xz:
                        _snap_end(part, end, node_xz[nid])
                        moved = math.hypot(*part[end]["snap"])
                        snaps.append({"way": w["id"], "node": nid, "route": run["route"], "m": round(moved, 3)})
                replaced_m += abs(run["s1"] - run["s0"])
                # past the play edge the line runs straight on along the route's end tangent for as
                # far as the OSM way did (nothing is built there; consumers clip at the edge)
                if run["head"]:
                    part.insert(0, _extend(part[0], part[1], seg[:run["head"] + 1], seg[0]))
                if run["tail"]:
                    part.append(_extend(part[-1], part[-2], seg[len(seg) - run["tail"] - 1:], seg[-1]))
            new.extend(part if not new else part[1:])
        if len(new) < 2:
            out_ways.append(w)
            continue
        tags = dict(w["tags"])
        tags["osm_width_m"] = tags.get("width_m")
        tags["width_m"] = round(2 * float(np.median([v["hw"] for v in new])), 3)
        on_route = [v for v in new if "sta" in v]
        template = None
        if on_route:
            mid = on_route[len(on_route) // 2]
            template = template_at(geoms[mid["route"]].ranges, mid["sta"])
        else:                      # e.g. a way riding the play edge, whose runs kept their ends
            template = geoms[by_way[w["id"]][0]].ranges[0]
        out_ways.append(dict(w, vertices=new, tags=tags, design=True, template=template))
    report = {"design_centreline_km": round(replaced_m / 1000, 2),
              "osm_centreline_kept_in_play_km": round(kept_m / 1000, 3),
              "end_snap_m": {k: round(float(np.percentile([s["m"] for s in snaps], p)), 3)
                             for k, p in (("p50", 50), ("p90", 90), ("p99", 99), ("max", 100))} if snaps else {},
              "ends_snapped_over_0.5m": sum(1 for s in snaps if s["m"] > 0.5),
              "worst_end_snaps": sorted({(s["way"], s["node"]): s for s in snaps}.values(), key=lambda s: -s["m"])[:10]}
    return dict(roads, ways=out_ways), report


def summarize(doc, design_report, route_class):
    ranges = [(rid, r) for rid, rs in doc["routes"].items() for r in rs if not r["bridge"]]
    by = lambda key: {str(k): sum(1 for _, r in ranges if r[key] == k)
                      for k in sorted({r[key] for _, r in ranges}, key=str)}
    length = lambda pred: round(sum(r["sta"][1] - r["sta"][0] for _, r in ranges if pred(r)) / 1000, 2)
    widths = {}
    for cls in ("arterial", "collector", "local", "service"):
        ws = [r["curb_to_curb_m"] for rid, r in ranges if route_class.get(rid) == cls]
        if ws:
            widths[cls] = {k: round(float(np.percentile(ws, p)), 2) for k, p in (("p10", 10), ("p50", 50), ("p90", 90))}
    return {"routes": len(doc["routes"]), "ranges": len(ranges),
            "km_by_section": {s: length(lambda r, s=s: r["section"] == s) for s in ("residential", "downtown", "uncurbed")},
            "km_by_width_source": {s: length(lambda r, s=s: r["width_source"] == s)
                                   for s in ("aerial", "osm_tag", "class_median", "osm_default", "class_lanes", "override")},
            "curb_to_curb_m_by_class": widths,
            "parking_sides": by("parking"), "lanes": by("lanes"), "gutter": by("gutter"), "curb": by("curb"),
            "tapers": sum(1 for _, r in ranges if r["taper_m"] > 0),
            "overrides": sum(1 for _, r in ranges if r["override"]),
            "design_roads": design_report}


def main(argv):
    alignments = load_json(ALIGNMENTS_PATH)
    doc = build(alignments=alignments)
    with open(OUT_PATH, "w") as handle:
        json.dump(doc, handle, separators=(",", ":"))
    _, design_report = design_roads(alignments=alignments, templates=doc)
    report = summarize(doc, design_report, {r["id"]: r["class"] for r in alignments["routes"]})
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as handle:
        json.dump(report, handle, indent=1)
    print(json.dumps(report, indent=1))
    print(f"wrote {OUT_PATH}\nreport {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
