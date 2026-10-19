#!/usr/bin/env python3
"""Buildings standing on the street: baked building hulls against the transportation layout.

Measures every collision hull in game/buildings/_build/chunk_*.json (chunk-local, shifted back
to world) against the layout surfaces in game/roads/_build/transport_layout.json, by footprint
source (OSM, curated, Microsoft, procedural infill). "Carriageway" is asphalt + curb; "roadside"
is sidewalk + parkway. Prints a table and writes the per-building rows as JSON for review.

Run: cd pipeline/buildings && ../../.venv/bin/python encroachment.py [--out report.json]
"""
import argparse
import glob
import json
import os

from shapely.geometry import Polygon, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUILD = os.path.join(ROOT, "game", "buildings", "_build")
LAYOUT = os.path.join(ROOT, "game", "roads", "_build", "transport_layout.json")
CHUNK = 200.0
MIN_M2 = 0.5
GROUPS = {"carriageway": ("asphalt", "curb"), "roadside": ("sidewalk", "parkway")}


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
    out = []
    for path in glob.glob(os.path.join(build, "chunk_*.json")):
        cx, cz = (int(v) for v in os.path.basename(path)[6:-5].split("_"))
        ox, oz = (cx + 0.5) * CHUNK, (cz + 0.5) * CHUNK
        for col in json.load(open(path)).get("collisions", []):
            pts = [(p[0] + ox, p[1] + oz) for p in col["hull"]]
            if len(pts) >= 3:
                out.append((col["id"], Polygon(pts)))
    return out


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--build", default=BUILD)
    ap.add_argument("--layout", default=LAYOUT)
    args = ap.parse_args()
    hulls = load_hulls(args.build)
    rows = measure(hulls, load_surfaces(args.layout))
    table = summary(hulls, rows)
    print(f"{'source':8} {'bldgs':>6} {'carriageway':>18} {'roadside':>18}")
    for s, line in table.items():
        c, r = line["carriageway"], line["roadside"]
        print(f"{s:8} {line['buildings']:6d} {c['count']:6d} {c['area_m2']:9.0f} m2 {r['count']:6d} {r['area_m2']:9.0f} m2")
    if args.out:
        rows.sort(key=lambda r: -r["area_m2"])
        json.dump({"summary": table, "rows": rows}, open(args.out, "w"), indent=1)


if __name__ == "__main__":
    main()
