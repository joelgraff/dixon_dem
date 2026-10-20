#!/usr/bin/env python3
"""Buildings standing on the street: baked building hulls against the transportation layout.

Measures every collision hull in game/buildings/_build/chunk_*.json (chunk-local, shifted back
to world) against the layout surfaces in game/roads/_build/transport_layout.json, by footprint
source (OSM, curated, Microsoft, procedural infill). "Carriageway" is asphalt + curb; "roadside"
is sidewalk + parkway. Prints a table and writes the per-building rows as JSON for review.

--review writes docs/footprint_aerial_audit/street_overlaps.{json,png}: every building on the
carriageway, largest first, with the street it stands on (the route nearest the overlap, its
template at that station: class, section, width source, curb-to-curb), its roofless_review.json
flags, and a cause sorted from those (`cause`): eave (under EAVE_M2: accepted), hull (the footprint itself is clear of the street:
only the convex collision hull of a concave building reaches it), footprint (flagged roofless:
lawn or bare ground inside), service (an uncurbed drive), downtown (a downtown front), nick (under
NICK_M2), street (a curbed street whose alignment or width is off the pavement). Everything but
`hull` and `eave` is also listed under `manual_review` with what to look at, as is every roofless-flagged
footprint the pavement gave way to (the layout report's building_yield: cause `yielded`), since
the drive or curb was cut for a building that may not be there.

Run: cd pipeline/buildings && ../../.venv/bin/python encroachment.py [--out report.json] [--review]
"""
import argparse
import glob
import json
import math
import os
import sys

from shapely.geometry import Polygon, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUILD = os.path.join(ROOT, "game", "buildings", "_build")
LAYOUT = os.path.join(ROOT, "game", "roads", "_build", "transport_layout.json")
CHUNK = 200.0
MIN_M2 = 0.5
GROUPS = {"carriageway": ("asphalt", "curb"), "roadside": ("sidewalk", "parkway")}
REVIEW_DIR = os.path.join(ROOT, "docs", "footprint_aerial_audit")
NICK_M2 = 10.0
EAVE_M2 = 1.0      # less than this on the carriageway is an eave over the curb: accepted, not listed


def _ids(name):
    path = os.path.join(ROOT, "game", "data", name)
    if not os.path.exists(path):
        return set()
    return {b["id"] for b in json.load(open(path)).get("buildings", [])}


_SOURCES = None


def source_of(bid):
    """OSM ids span 800M-1.1G too, so the source is looked up, not read off the id."""
    global _SOURCES
    if _SOURCES is None:
        _SOURCES = [("curated", _ids("buildings_curated.json")), ("osm", _ids("buildings.json")),
                    ("ms", _ids("buildings_ms.json"))]
    for name, ids in _SOURCES:
        if bid in ids:
            return name
    return "infill" if 900000000 <= int(bid) < 900100000 else "other"


def load_hulls(build=BUILD):
    """(id, outline) per building: a concave one is baked as several convex parts, joined here."""
    parts = {}
    for path in glob.glob(os.path.join(build, "chunk_*.json")):
        cx, cz = (int(v) for v in os.path.basename(path)[6:-5].split("_"))
        ox, oz = (cx + 0.5) * CHUNK, (cz + 0.5) * CHUNK
        for col in json.load(open(path)).get("collisions", []):
            pts = [(p[0] + ox, p[1] + oz) for p in col["hull"]]
            if len(pts) >= 3:
                parts.setdefault(col["id"], []).append(Polygon(pts).buffer(0))
    return [(bid, polys[0] if len(polys) == 1 else unary_union(polys)) for bid, polys in parts.items()]


def load_surfaces(layout=LAYOUT):
    surf = json.load(open(layout))["surfaces"]
    return {g: unary_union([shape(surf[n]) for n in names if n in surf])
            for g, names in GROUPS.items()}


def measure(hulls, surfaces):
    rows = []
    for group, geom in surfaces.items():
        parts = list(getattr(geom, "geoms", [geom]))
        tree = STRtree(parts)
        for bid, poly in hulls:
            area = sum(parts[i].intersection(poly).area for i in tree.query(poly, predicate="intersects"))
            if area > MIN_M2:
                c = poly.centroid
                rows.append({"id": bid, "source": source_of(bid), "surface": group,
                             "area_m2": round(area, 1), "at": [round(c.x, 1), round(c.y, 1)],
                             "footprint_m2": round(poly.area, 1)})
    return rows


def summary(hulls, rows):
    totals = {}
    for bid, _ in hulls:
        s = source_of(bid)
        totals[s] = totals.get(s, 0) + 1
    table = {}
    for s in sorted(totals):
        line = {"buildings": totals[s]}
        for g in GROUPS:
            sel = [r for r in rows if r["source"] == s and r["surface"] == g]
            line[g] = {"count": len(sel), "area_m2": round(sum(r["area_m2"] for r in sel), 1)}
        table[s] = line
    return table


def _routes():
    """(record, projector, template ranges) per route of alignments.json."""
    sys.path.insert(0, os.path.join(ROOT, "pipeline", "roads"))
    import alignment as al
    routes = json.load(open(os.path.join(ROOT, "game", "data", "alignments.json")))["routes"]
    ranges = json.load(open(os.path.join(ROOT, "game", "data", "templates.json")))["routes"]
    return [(r, al.Alignment(r["pis"], r["radii"]).projector(0.5), ranges.get(r["id"], []))
            for r in routes]


def _street_at(routes, x, z):
    """The route nearest (x, z) and its template range there."""
    best = None
    for rec, project, ranges in routes:
        sta, left, dist = project([(x, z)])
        if best is None or dist[0] < best[0]:
            best = (dist[0], rec, float(sta[0]), float(left[0]), ranges)
    dist, rec, sta, left, ranges = best
    tpl = next((t for t in ranges if t["sta"][0] - 1 <= sta <= t["sta"][1] + 1), None)
    return {"route": rec["id"], "name": rec["name"], "class": rec["class"], "sta": round(sta, 1),
            "section": tpl["section"] if tpl else None,
            "width_source": tpl["width_source"] if tpl else None,
            "curb_to_curb_m": tpl["curb_to_curb_m"] if tpl else None,
            "override": tpl.get("override") if tpl else None,
            "distance_to_centreline_m": round(dist, 1)}


def _roof_flags():
    path = os.path.join(REVIEW_DIR, "roofless_review.json")
    if not os.path.exists(path):
        return {}
    return {str(f["id"]): f for f in json.load(open(path))["flagged"]}


def cause_of(row):
    s = row["street"]
    if row.get("footprint_on_carriageway_m2", row["on_carriageway_m2"]) <= MIN_M2:
        return "hull"
    if row["roofless"]:
        return "footprint"
    if row["on_carriageway_m2"] < EAVE_M2:
        return "eave"
    if s["section"] == "uncurbed":
        return "service"
    if s["section"] == "downtown":
        return "downtown"
    if row["on_carriageway_m2"] < NICK_M2:
        return "nick"
    return "street"


LOOK_AT = {
    "footprint": "the outline is mostly {why} in the 2025 aerial: a demolished building or a false "
                 "detection? Delete it (or retrace it) if no building stands there.",
    "service": "a drive still under the building: check the drive and the outline.",
    "downtown": "a downtown front still in the street: check the outline against the aerial.",
    "nick": "a corner on the curb: check the alignment against the pavement.",
    "yielded": "the pavement was cut for it ({how}), but the outline is mostly {why} in the 2025 "
               "aerial. If no building stands there, delete it and the pavement comes back.",
    "street": "a real building the street runs into: the alignment (or its width) is off the "
              "pavement here; refit the route or set its width.",
}


def review(hulls, surfaces, rows, out_dir=REVIEW_DIR):
    """Writes street_overlaps.json and .png (see the module docstring); returns the rows."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import footprints
    outlines = {str(rec["id"]): Polygon(rec["footprint"]).buffer(0) for rec in footprints.all_outlines()}
    hull_of = dict(hulls)
    carriageway = surfaces["carriageway"]
    routes = _routes()
    flags = _roof_flags()
    out = []
    for r in sorted((r for r in rows if r["surface"] == "carriageway"), key=lambda r: -r["area_m2"]):
        on = hull_of[r["id"]].intersection(carriageway)
        p = on.representative_point()
        flag = flags.get(str(r["id"]))
        outline = outlines.get(str(r["id"]))
        row = {"id": str(r["id"]), "source": r["source"], "on_carriageway_m2": r["area_m2"],
               "footprint_on_carriageway_m2": round(outline.intersection(carriageway).area, 1) if outline else None,
               "footprint_m2": r["footprint_m2"], "at": r["at"], "overlap_at": [round(p.x, 1), round(p.y, 1)],
               "roofless": ({k: flag[k] for k in ("lawn", "bare", "why") if k in flag} if flag else None),
               "street": _street_at(routes, p.x, p.y)}
        row["cause"] = cause_of(row)
        out.append(row)
    causes = {}
    for row in out:
        causes[row["cause"]] = causes.get(row["cause"], 0) + 1
    manual = [{"id": row["id"], "source": row["source"], "at": row["at"], "cause": row["cause"],
               "street": row["street"]["name"] or row["street"]["route"],
               "on_carriageway_m2": row["on_carriageway_m2"],
               "look_at": LOOK_AT[row["cause"]].format(why=(row["roofless"] or {}).get("why", "open ground"))}
              for row in out if row["cause"] not in ("hull", "eave")]
    yielded = json.load(open(LAYOUT))["quality"].get("building_yield", {})
    for key, how in (("service", "a drive stops at it"), ("curb_trims", "the curb runs round it")):
        for y in yielded.get(key, []):
            flag = flags.get(str(y["id"]))
            if flag:
                manual.append({"id": str(y["id"]), "source": y["source"], "at": y["at"], "cause": "yielded",
                               "street": None, "on_carriageway_m2": 0.0, "yielded_m2": y["area_m2"],
                               "look_at": LOOK_AT["yielded"].format(how=how, why=flag.get("why", "lawn"))})
    os.makedirs(out_dir, exist_ok=True)
    json.dump({"note": "Baked buildings standing on the carriageway (asphalt + curb) of the transportation "
                       "layout, largest first. street: the route nearest the overlap and its template "
                       "there (width_source class_median/osm_default is an estimate, not a measurement). "
                       "roofless: the roofless_review.json flag (lawn or bare ground inside the outline). "
                       "Made by pipeline/buildings/encroachment.py --review.",
               "count": len(out), "by_cause": causes, "manual_review": manual, "buildings": out},
              open(os.path.join(out_dir, "street_overlaps.json"), "w"), indent=1)
    contact_sheet(out, os.path.join(out_dir, "street_overlaps.png"))
    return out


def contact_sheet(rows, path, cols=9, cell=220, half=30.0, mpp=0.25):
    """Each building (magenta: its footprint) on the aerial with the asphalt (white) and curb (orange)."""
    from PIL import Image, ImageDraw
    from shapely.geometry import box
    sys.path.insert(0, os.path.join(ROOT, "pipeline"))
    sys.path.insert(0, os.path.join(ROOT, "pipeline", "roads"))
    import alignment_overlay
    from roads import transport_layout
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import footprints
    layout = transport_layout.load_layout(LAYOUT)
    outlines = {str(rec["id"]): rec["footprint"] for rec in footprints.all_outlines()}
    sheet = Image.new("RGB", (cols * cell, max(1, math.ceil(len(rows) / cols)) * cell), (30, 30, 30))
    for k, b in enumerate(rows):
        x, z = b["at"]
        x0, z0 = x - half, z - half
        img = alignment_overlay.aerial(x0, z0, x + half, z + half, mpp)
        draw = ImageDraw.Draw(img)

        def px(p):
            return ((p[0] - x0) / mpp, (p[1] - z0) / mpp)
        window = box(x0, z0, x + half, z + half)
        for name, colour in (("asphalt", (255, 255, 255)), ("curb", (255, 140, 0))):
            for part in transport_layout.polygon_parts(layout[name].intersection(window)):
                for ring in [part.exterior, *part.interiors]:
                    draw.line([px(p) for p in ring.coords], fill=colour, width=2)
        ring = outlines.get(b["id"])
        if ring:
            draw.line([px(p) for p in ring + ring[:1]], fill=(255, 0, 255), width=2)
        img = img.resize((cell, cell))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, cell, 14], fill=(0, 0, 0))
        draw.text((3, 2), f"{k + 1}. {b['id']} {b['source']} {b['on_carriageway_m2']:.0f}m2 {b['cause']}",
                  fill=(255, 255, 255))
        if b["roofless"]:
            draw.rectangle([0, cell - 14, cell, cell], fill=(120, 0, 0))
            draw.text((3, cell - 12), "roofless? " + b["roofless"].get("why", "lawn"), fill=(255, 255, 255))
        sheet.paste(img, ((k % cols) * cell, (k // cols) * cell))
    sheet.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--review", action="store_true",
                    help="write docs/footprint_aerial_audit/street_overlaps.{json,png}")
    ap.add_argument("--build", default=BUILD)
    ap.add_argument("--layout", default=LAYOUT)
    args = ap.parse_args()
    hulls = load_hulls(args.build)
    surfaces = load_surfaces(args.layout)
    rows = measure(hulls, surfaces)
    table = summary(hulls, rows)
    print(f"{'source':8} {'bldgs':>6} {'carriageway':>18} {'roadside':>18}")
    for s, line in table.items():
        c, r = line["carriageway"], line["roadside"]
        print(f"{s:8} {line['buildings']:6d} {c['count']:6d} {c['area_m2']:9.0f} m2 {r['count']:6d} {r['area_m2']:9.0f} m2")
    if args.out:
        rows.sort(key=lambda r: -r["area_m2"])
        json.dump({"summary": table, "rows": rows}, open(args.out, "w"), indent=1)
    if args.review:
        listed = review(hulls, surfaces, rows)
        causes = {}
        for row in listed:
            causes[row["cause"]] = causes.get(row["cause"], 0) + 1
        print(f"street_overlaps: {len(listed)} on the carriageway, by cause {causes}")


if __name__ == "__main__":
    main()
