#!/usr/bin/env python3
"""Horizontal control for the road network (docs/roadway_control_plan.md, phase 1).

Chains roads.json's drivable ways into routes (routes.py), fits each a tangent-and-curve
alignment (alignment.py), stations its OSM ways and bridges, places a control point at every
junction, and measures each route's pavement width from the 2025 6-inch aerial
(aerial_width.py). Nothing in the game reads this yet: it is data for review and for the
vertical solve (phase 2).

Writes:
  game/data/alignments.json               routes, alignments, stations, junctions, widths
  game/roads/_build/alignment_report.json deviations from OSM, junction shifts, fit notes

Routes pinned in alignment_overrides.json's `horizontal` section take their hand-set PIs and
radii instead of the fit (horizontal_overrides.py); the editor in Bridge Composer writes them.
Each route record carries its OSM line (`osm`) for that editor and, where pinned, `pinned`.

Run: ../../.venv/bin/python build_alignments.py [--overlay]
`--overlay` also draws review images over the aerial into captures/roads/alignments/.
"""
import hashlib
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import alignment as al  # noqa: E402
import alignment_geom as geom  # noqa: E402
import horizontal_overrides as ho  # noqa: E402
import routes as rt  # noqa: E402
import road_metrics as rm  # noqa: E402
from build_road_plan import DOWNTOWN_BOUNDS, clip_ways_to_bounds  # noqa: E402

pc = rm.pc
OUT_PATH = os.path.join(pc.GAME_DATA, "alignments.json")
REPORT_PATH = os.path.join(pc.ROOT, "game", "roads", "_build", "alignment_report.json")
CLASS_RANK = {"service": 1, "local": 2, "collector": 3, "arterial": 4}
JUNCTION_SNAP_M = 6.0      # the most an ending route's end moves to meet the route it ends on


def in_downtown(x, z):
    x0, z0, x1, z1 = DOWNTOWN_BOUNDS
    return x0 <= x <= x1 and z0 <= z <= z1


def fingerprint(paths):
    h = hashlib.sha256()
    for p in paths:
        with open(p, "rb") as handle:
            h.update(handle.read())
    return h.hexdigest()[:16]


def load_routes(standards):
    with open(os.path.join(pc.GAME_DATA, "roads.json")) as handle:
        roads = json.load(handle)

    def rank(highway):
        cls = rm.class_of(highway, standards) if highway else None
        return CLASS_RANK.get(cls)

    ways = clip_ways_to_bounds(roads["ways"])
    for w in ways:                      # clip ids are way*100+piece; keep the OSM id for stationing
        w["osm_id"] = w["id"] // 100
    out = []
    for r in rt.build_routes(ways, rank):
        if rt.orient(rt.route_polyline(r)):
            r = rt.reverse_route(r)
        poly = rt.route_polyline(r)
        pts = np.array([(x, z) for x, z, _, _ in poly])
        seg = np.hypot(*np.diff(pts, axis=0).T)
        if seg.sum() < 2.0:
            continue
        highways = {}
        for w, a, b, _ in r["pieces"]:
            h = w["tags"].get("highway")
            vs = w["vertices"][a:b + 1]
            highways[h] = highways.get(h, 0.0) + sum(
                math.hypot(q["x"] - p["x"], q["z"] - p["z"]) for p, q in zip(vs, vs[1:]))
        highway = max(highways, key=highways.get)
        names = []
        for w, *_ in r["pieces"]:
            n = w["tags"].get("name")
            if n and n not in names:
                names.append(n)
        widths = [w["tags"].get("width_m") for w, *_ in r["pieces"] if w["tags"].get("width_m")]
        out.append({"route": r, "poly": poly, "points": pts, "highway": highway,
                    "osm_width": float(np.median(widths)) if widths else 6.0,
                    "class": rm.class_of(highway, standards), "names": names,
                    "oneway": all(w["tags"].get("oneway") for w, *_ in r["pieces"]),
                    "id": "R%d" % min(w["osm_id"] for w, *_ in r["pieces"])})
    # ids must be unique: a way split into several routes gets a suffix on the later ones
    seen = {}
    for rec in sorted(out, key=lambda r: (r["id"], -len(r["points"]))):
        n = seen.get(rec["id"], 0)
        seen[rec["id"]] = n + 1
        if n:
            rec["id"] = "%s_%d" % (rec["id"], n)
    return out


def fit_all(recs, standards, pins=None):
    hz = standards["horizontal"]
    pins = pins or {}
    # pass 1 without snapping finds the street grid; pass 2 snaps to it
    tangents = []
    for rec in recs:
        a, _ = al.fit(rec["points"], tol=hz["osm_deviation_max"])
        for e in a.elements:
            if e["type"] == "tangent":
                d = (e["end"][0] - e["start"][0], e["end"][1] - e["start"][1])
                tangents.append((d, e["sta"][1] - e["sta"][0]))
    grid = al.grid_bearings(tangents)
    for rec in recs:
        # a route that enters downtown is held to the downtown tolerance throughout
        down = any(in_downtown(x, z) for x, z in al.densify(rec["points"], 5.0))
        tol = hz["osm_deviation_max_downtown"] if down else hz["osm_deviation_max"]
        rec["tol"] = tol
        rec["alignment"], rec["fit"] = al.fit(rec["points"], tol=tol, grid=grid,
                                              snap_deg=hz["bearing_snap_deg"],
                                              rounding=[tuple(r) for r in hz["radius_rounding"]])
        if rec["id"] in pins:
            apply_pins(rec, pins[rec["id"]])
    return grid


def _counts(a):
    curves = sum(1 for r in a.radii[1:-1] if r > 0)
    return {"tangents": sum(1 for e in a.elements if e["type"] == "tangent"), "curves": curves,
            "angle_points": len(a.pis) - 2 - curves, "snapped_tangents": 0}


def apply_pins(rec, pins, dense_step=0.5):
    """Replaces the fitted geometry of `rec` with the pinned horizontal geometry in `pins`
    (alignment_overrides.json `horizontal` entries for the route; see horizontal_overrides.py).

    Sets rec["pin_idx"] ([(first PI, last PI, note)] in the new chain), rec["pinned_ends"] and
    refreshes rec["fit"]."""
    whole = [e for e in pins if "sta" not in e]
    if whole:
        e = whole[-1]
        a = al.Alignment(e["pis"], e["radii"], e.get("breaks", ()))
        if not a.valid:
            raise ValueError("%s: pinned curves overlap" % rec["id"])
        rec["alignment"] = a
        rec["pin_idx"] = [(0, len(a.pis) - 1, e["note"])]
        rec["pinned_ends"] = (True, True)
        rec["fit"] = dict(_counts(a), pinned=True)
        return
    partial = sorted(pins, key=lambda e: e["sta"][0])
    for e1, e2 in zip(partial, partial[1:]):
        if e2["sta"][0] < e1["sta"][1]:
            raise ValueError("%s: pinned stretches overlap" % rec["id"])
    fitted = rec["alignment"]
    dense = al.densify(rec["points"], dense_step)
    cum = np.r_[0.0, np.cumsum(np.hypot(*np.diff(dense, axis=0).T))]
    osm_sta = [float(cum[i]) for i in al._pi_indices(fitted.pis, dense)]
    items = []          # (osm station, order, pi, radius, pin index or None)
    for i, (p, r) in enumerate(zip(fitted.pis, fitted.radii)):
        if not any(e["sta"][0] - 1e-6 <= osm_sta[i] <= e["sta"][1] + 1e-6 for e in partial):
            items.append((osm_sta[i], 0, p, r, None, None))
    for k, e in enumerate(partial):
        for j, (p, r) in enumerate(zip(e["pis"], e["radii"])):
            items.append((e["sta"][0], 1 + j, tuple(p), r, k, j))
    items.sort(key=lambda t: (t[0], t[1]))
    pis = [t[2] for t in items]
    radii = [t[3] for t in items]
    frozen = [i for i, t in enumerate(items) if t[4] is not None]
    radii[0] = radii[-1] = 0.0
    # an end of the route that is not pinned stays its fitted end
    radii = al._resolve_overlaps(pis, radii, frozen)
    where = {(t[4], t[5]): i for i, t in enumerate(items) if t[4] is not None}
    breaks = [where[(k, b)] for k, e in enumerate(partial) for b in e.get("breaks", ())]
    a = al.Alignment(pis, radii, breaks)
    rec["alignment"] = a
    rec["pin_idx"] = []
    for k, e in enumerate(partial):
        idx = [i for i, t in enumerate(items) if t[4] == k]
        rec["pin_idx"].append((idx[0], idx[-1], e["note"]))
    rec["pinned_ends"] = (items[0][4] is not None, items[-1][4] is not None)
    rec["fit"] = dict(_counts(a), pinned=True)
    # a joint between pinned and fitted geometry should be a curve (tangent-continuous)
    rec["joint_kinks"] = []
    for first, last, _ in rec["pin_idx"]:
        for i in (first, last):
            if 0 < i < len(a.pis) - 1 and a.radii[i] <= 0:
                d = abs(math.degrees(geom.curve_data(a.pis, a.radii, i)["delta"]))
                if d > 0.5:
                    rec["joint_kinks"].append({"pi": i, "at": [round(v, 1) for v in a.pis[i]], "deg": round(d, 1)})


def pinned_stretches(rec):
    """[{sta: [from, to], whole, note}] of the route's pinned geometry, in alignment stations."""
    a = rec["alignment"]
    out = []
    for first, last, note in rec.get("pin_idx", ()):
        out.append({"sta": [round(a.pi_sta[first][0], 2), round(a.pi_sta[last][1], 2)],
                    "whole": first == 0 and last == len(a.pis) - 1, "note": note})
    return out


def station_features(rec):
    """Station ranges of the route's OSM ways and bridges, and its junction nodes' stations."""
    project = rec["alignment"].projector()
    poly = rec["poly"]
    sta = project(np.array([(x, z) for x, z, _, _ in poly]))[0]
    ways, bridges = [], []
    k = 0
    for w, a, b, _ in rec["route"]["pieces"]:
        n = b - a
        s0, s1 = float(sta[k]), float(sta[k + n])
        rng = [round(min(s0, s1), 2), round(max(s0, s1), 2)]
        if ways and ways[-1]["id"] == w["osm_id"]:
            ways[-1]["sta"][1] = rng[1]
        else:
            ways.append({"id": w["osm_id"], "sta": rng})
        if w["tags"].get("bridge"):
            if bridges and bridges[-1]["way_id"] == w["osm_id"]:
                bridges[-1]["sta"][1] = rng[1]
            else:
                bridges.append({"way_id": w["osm_id"], "sta": list(rng)})
        k += n
    nodes = {}
    for (x, z, node, _), s in zip(poly, sta):
        if node is not None:
            nodes[node] = float(s)
    return ways, bridges, nodes


def _line_hit(p, d, rec, s_guess):
    """Where the line p + t d meets the route's alignment near station s_guess: (point, station),
    or None when the search does not settle on a point of both."""
    a = rec["alignment"]
    s = s_guess
    for _ in range(12):
        x, z, h = a.point_at(s)
        q = al.intersect_lines(p, d, (x, z), h)
        if q is None:
            return None
        s_new = min(max(s + (q[0] - x) * h[0] + (q[1] - z) * h[1], 0.0), a.length)
        if abs(s_new - s) < 1e-4:
            break
        s = s_new
    x, z, _ = a.point_at(s)
    off_line = abs((x - p[0]) * d[1] - (z - p[1]) * d[0])
    if off_line > 0.05:
        return None
    return np.array([x, z]), s


def junctions(recs, node_xy):
    """A control point at every node shared by two or more routes, ending routes moved onto it."""
    at = {}
    for i, rec in enumerate(recs):
        for node, s in rec["node_sta"].items():
            at.setdefault(node, []).append((i, s))
    out = []
    for node, items in sorted(at.items()):
        if len(items) < 2 and not any(recs[i]["route"]["closed"] for i, _ in items):
            continue
        if len({i for i, _ in items}) < 2:
            continue
        through = [(i, s) for i, s in items if 1e-6 < s < recs[i]["alignment"].length - 1e-6]
        ending = [(i, s) for i, s in items if (i, s) not in through]
        through.sort(key=lambda t: -CLASS_RANK.get(recs[t[0]]["class"], 0))
        ox, oz = node_xy[node]
        if len(through) >= 2:
            (i, s), (j, sj) = through[0], through[1]
            x, z, h = recs[j]["alignment"].point_at(sj)
            hit = _line_hit((x, z), h, recs[i], s)
            if hit is not None and math.hypot(hit[0][0] - ox, hit[0][1] - oz) <= JUNCTION_SNAP_M:
                cp = hit[0]
            else:                       # near-parallel through routes: keep the senior route's point
                cp = np.array(recs[i]["alignment"].point_at(s)[:2])
        elif through:
            i, s = through[0]
            cp = np.array(recs[i]["alignment"].point_at(s)[:2])
        else:
            pts = [recs[i]["alignment"].point_at(s)[:2] for i, s in items]
            cp = np.mean(pts, axis=0)
        legs = []
        moved = []
        for i, s in items:
            rec = recs[i]
            a = rec["alignment"]
            is_end = (i, s) in ending
            start = s < a.length / 2
            # a pinned end is authoritative: the other routes' ends meet it, not the reverse
            pinned_end = rec.get("pinned_ends", (False, False))[0 if start else 1]
            if is_end and through and not pinned_end:
                x, z, h = a.point_at(0.0 if start else a.length)
                ti, ts = through[0]
                hit = _line_hit((x, z), h, recs[ti], ts)
                if hit is not None and math.hypot(hit[0][0] - x, hit[0][1] - z) <= JUNCTION_SNAP_M:
                    pis = list(a.pis)
                    pis[0 if start else -1] = (float(hit[0][0]), float(hit[0][1]))
                    cand = al.Alignment(pis, a.radii, a.breaks)
                    if cand.valid and cand.length > 1.0:
                        moved.append(round(math.hypot(hit[0][0] - x, hit[0][1] - z), 3))
                        rec["alignment"] = cand
                        a = cand
                        s = 0.0 if start else a.length
            _, _, h = a.point_at(s)
            legs.append({"route": rec["id"], "sta": round(float(s), 2), "through": not is_end,
                         "heading_deg": round(al.bearing_deg(h), 2)})
        skew = None
        if len(legs) >= 2:
            b0 = legs[0]["heading_deg"]
            angles = [abs(((l["heading_deg"] - b0 + 90.0) % 180.0) - 90.0) for l in legs[1:]]
            crossing = max(angles)
            skew = round(abs(90.0 - crossing), 2) if crossing > 1.0 else None
        out.append({"node_id": node, "x": round(float(cp[0]), 3), "z": round(float(cp[1]), 3),
                    "shift_m": round(math.hypot(cp[0] - ox, cp[1] - oz), 3),
                    "skew_deg": skew, "legs": legs, "ends_moved_m": moved})
    return out


def _shared_nodes(recs):
    """Nodes on more than one route: junctions."""
    count = {}
    for rec in recs:
        for node in rec["node_sta"]:
            count[node] = count.get(node, 0) + 1
    return {n for n, c in count.items() if c > 1}


def _skip_ranges(rec, shared):
    """Stations the width survey leaves out: junctions and bridges."""
    out = [(s, s) for node, s in rec["node_sta"].items() if node in shared]
    out += [tuple(b["sta"]) for b in rec["bridges"]]
    return out


def main(argv):
    standards = rm.load_standards()
    recs = load_routes(standards)
    pins = ho.pins_by_route(ho.load()) if os.path.exists(ho.OVERRIDES_PATH) else {}
    unknown = sorted(set(pins) - {r["id"] for r in recs})
    if unknown:
        print("  pinned routes that do not exist (ids change when OSM ways do): " + ", ".join(unknown))
    pins = {k: v for k, v in pins.items() if k not in unknown}
    grid = fit_all(recs, standards, pins)
    node_xy = {}
    with open(os.path.join(pc.GAME_DATA, "roads.json")) as handle:
        for w in json.load(handle)["ways"]:
            for v in w["vertices"]:
                if v.get("node_id") is not None:
                    node_xy[v["node_id"]] = (v["x"], v["z"])
    for rec in recs:
        rec["ways"], rec["bridges"], rec["node_sta"] = station_features(rec)

    survey = "--no-width" not in argv
    juncs = junctions(recs, node_xy)

    # deviation from OSM, after the junction moves
    flagged, pinned_dev = [], []
    hz = standards["horizontal"]
    for rec in recs:
        dense = al.densify(rec["points"], 0.5)
        sta, left, _ = rec["alignment"].projector()(dense)
        # lateral offset only: points past an end (trimmed to a junction) are the junction's
        # shift, reported with the junction
        inside = (sta > 1e-3) & (sta < rec["alignment"].length - 1e-3)
        d = np.abs(left[inside]) if inside.any() else np.zeros(1)
        pts = dense[inside] if inside.any() else dense[:1]
        tol = np.where([in_downtown(x, z) for x, z in pts],
                       hz["osm_deviation_max_downtown"], hz["osm_deviation_max"])
        over = d > tol + 1e-9
        if rec["id"] in pins:       # hand-pinned geometry is authoritative: reported, not flagged
            pinned_dev.append({"route": rec["id"], "name": rec["names"][0] if rec["names"] else None,
                               "max_m": round(float(d.max()), 2), "whole": rec["pin_idx"][0][0] == 0
                               and rec["pin_idx"][0][1] == len(rec["alignment"].pis) - 1,
                               "note": rec["pin_idx"][0][2], "joint_kinks": rec.get("joint_kinks", [])})
            over = np.zeros_like(over)
        rec["deviation"] = {"max_m": round(float(d.max()), 3), "p95_m": round(float(np.percentile(d, 95)), 3),
                            "over_tol": bool(over.any())}
        if over.any():
            k = int(np.argmax(np.where(over, d - tol, -np.inf)))
            flagged.append({"route": rec["id"], "name": rec["names"][0] if rec["names"] else None,
                            "max_m": round(float(d[k]), 2), "tol_m": float(tol[k]),
                            "at": [round(float(v), 1) for v in pts[k]]})

    widths, edges, recentre = {}, [], []
    if survey:
        import aerial_width as aw
        aerial = aw.Aerial()
        shared = _shared_nodes(recs)
        for rec in recs:
            if rec["class"] not in aw.SURVEYED_CLASSES:
                continue
            blocks = aw.survey_route(rec["alignment"], aerial, _skip_ranges(rec, shared), rec["class"])
            widths[rec["id"]] = aw.summarize(blocks, standards, rec["osm_width"])
            widths[rec["id"]]["block_detail"] = blocks
            edges.extend(aw.block_edges(rec["alignment"], blocks))
            for b in blocks:
                if b["counts"] and abs(b["centre"]) > aw.RECENTRE_FLAG_M:
                    x, z, _ = rec["alignment"].point_at((b["sta"][0] + b["sta"][1]) / 2)
                    recentre.append({"route": rec["id"], "name": rec["names"][0] if rec["names"] else None,
                                     "sta": b["sta"], "centre_m": b["centre"], "at": [round(x, 1), round(z, 1)]})

    routes_out = []
    for rec in sorted(recs, key=lambda r: r["id"]):
        rec_out = {"id": rec["id"], "name": rec["names"][0] if rec["names"] else None,
                   "names": rec["names"], "highway": rec["highway"], "class": rec["class"],
                   "oneway": rec["oneway"], "closed": rec["route"]["closed"],
                   "ways": rec["ways"], "bridges": rec["bridges"],
                   "deviation": rec["deviation"], "fit": {k: (round(v, 3) if isinstance(v, float) else v)
                                                          for k, v in rec["fit"].items()}}
        rec_out.update(rec["alignment"].to_json())
        rec_out["osm"] = [[round(float(x), 2), round(float(z), 2)] for x, z in rec["points"]]
        if rec.get("pin_idx"):
            rec_out["pinned"] = pinned_stretches(rec)
        if rec["id"] in widths:
            rec_out["width"] = widths[rec["id"]]
        routes_out.append(rec_out)

    inputs = [os.path.join(pc.GAME_DATA, "roads.json"), os.path.join(HERE, "design_standards.json")]
    data = {"format": "dixon-alignments", "version": 1,
            "inputs": {"roads.json+design_standards.json": fingerprint(inputs)},
            "grid_bearings_deg": [round(g, 3) for g in grid],
            "routes": routes_out, "junctions": juncs,
            # counted blocks whose pavement centre is off the alignment, for the review queue (the
            # report below lives in game/roads/_build, which build_road_plan.py clears)
            "off_centre_blocks": sorted(recentre, key=lambda r: -abs(r["centre_m"]))}
    with open(OUT_PATH, "w") as handle:
        json.dump(data, handle, separators=(",", ":"))

    if survey:
        import alignment_metrics
        alignment_metrics.append(alignment_metrics.snapshot(data, ho.load() if os.path.exists(ho.OVERRIDES_PATH) else None))

    shifts = np.array([j["shift_m"] for j in juncs]) if juncs else np.zeros(1)
    moved = [m for j in juncs for m in j["ends_moved_m"]]
    lengths = np.array([r["length"] for r in routes_out])
    report = {
        "routes": len(routes_out), "length_km": round(float(lengths.sum()) / 1000.0, 2),
        "grid_bearings_deg": data["grid_bearings_deg"],
        "tangents": sum(r["fit"]["tangents"] for r in routes_out),
        "tangents_snapped_to_grid": sum(r["fit"]["snapped_tangents"] for r in routes_out),
        "curves": sum(r["fit"]["curves"] for r in routes_out),
        "angle_points": sum(r["fit"]["angle_points"] for r in routes_out),
        "deviation_max_m": {k: round(float(np.percentile([r["deviation"]["max_m"] for r in routes_out], p)), 3)
                            for k, p in (("p50", 50), ("p90", 90), ("max", 100))},
        "routes_over_tolerance": len(flagged),
        "pinned_routes": sorted(pinned_dev, key=lambda r: r["route"]),
        "junctions": len(juncs),
        "junction_shift_m": {k: round(float(np.percentile(shifts, p)), 3)
                             for k, p in (("p50", 50), ("p90", 90), ("max", 100))},
        "route_ends_moved_onto_junctions": len(moved),
        "widths_from_aerial": sum(1 for w in widths.values() if w.get("source") == "aerial"),
        "widths_from_osm_tag": sum(1 for w in widths.values() if w.get("source") != "aerial"),
        "blocks_surveyed": sum(w["blocks"] for w in widths.values()),
        "blocks_counted": sum(w["blocks_counted"] for w in widths.values()),
        "off_centre_blocks": sorted(recentre, key=lambda r: -abs(r["centre_m"])),
        "over_tolerance": sorted(flagged, key=lambda f: -f["max_m"]),
    }
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as handle:
        json.dump(report, handle, indent=1)
    print(json.dumps({k: v for k, v in report.items() if k not in ("over_tolerance", "off_centre_blocks")}, indent=1))
    print(f"  {len(recentre)} counted blocks more than {aw.RECENTRE_FLAG_M if survey else '-'} m off the pavement centre"
          if survey else "")
    for f in report["over_tolerance"][:15]:
        print(f"  over tolerance: {f['route']} {f['name'] or '-'} {f['max_m']} m at {f['at']}")
    print(f"wrote {OUT_PATH}\nreport {REPORT_PATH}")

    if "--overlay" in argv:
        import alignment_overlay
        alignment_overlay.draw(data, edges)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
