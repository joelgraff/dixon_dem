#!/usr/bin/env python3
"""Converts Microsoft's open ML building footprints into game/data/buildings_ms.json.

Why: OSM has 707 footprints inside the play area; this dataset has 4,722 for the same
ground, with per-building heights. That difference is every empty residential block in
the model -- the NE grid, Chicago Ave, the north-west, and the houses west of
Peoria/Hennepin that OSM never mapped.

Source: https://minedbuildings.z5.web.core.windows.net/global-buildings/ (ODbL), quadkey
030222220 covers Dixon. Download once into data/raw/msbuildings/ (see docs/STATUS.md).

Precedence, highest first:
  1. landmark-owned footprints  - the landmarks workstream builds those itself
  2. curated (aerial-traced)    - hand-checked against the user's photo
  3. OSM                        - carries names/tags/levels, and its geometry is surveyed
  4. Microsoft                  - fills everything else
A Microsoft footprint is dropped when it overlaps any higher-precedence footprint, so this
only ever ADDS buildings.

Run: cd pipeline/buildings && ../../.venv/bin/python ms_footprints.py
"""
import gzip
import json
import os
import sys

from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "data", "raw", "msbuildings", "dixon_030222220.csv.gz")
OUT = os.path.join(ROOT, "game", "data", "buildings_ms.json")

MIN_AREA_M2 = 12.0        # sheds smaller than this are noise
MAX_AREA_M2 = 20000.0     # a merged blob, not a building
SIMPLIFY_M = 0.35         # ML rings are jagged; keep corners, drop wobble
OVERLAP_FRAC = 0.25       # drop if this much of the MS footprint is already covered


def load_existing():
    polys, why = [], []
    bpath = os.path.join(ROOT, "game", "data", "buildings.json")
    for b in json.load(open(bpath))["buildings"]:
        fp = b.get("footprint") or []
        if len(fp) >= 3:
            polys.append(Polygon([(p["x"], p["z"]) for p in fp]))
            why.append("landmark" if b.get("landmark_id") else "osm")
    cpath = os.path.join(ROOT, "game", "data", "buildings_curated.json")
    if os.path.exists(cpath):
        data = json.load(open(cpath))
        recs = data.get("buildings", data if isinstance(data, list) else [])
        for b in recs:
            fp = b.get("footprint") or []
            if len(fp) >= 3:
                polys.append(Polygon([(p["x"], p["z"]) for p in fp]))
                why.append("curated")
    return polys, why


def main():
    if not os.path.exists(SRC):
        raise SystemExit(f"missing {SRC} - see the module docstring for the download URL")
    origin = json.load(open(os.path.join(ROOT, "game", "data", "world_origin.json")))
    E0, N0, SIZE = origin["origin_easting"], origin["origin_northing"], origin["size_m"]
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:26916", always_xy=True)

    existing, _ = load_existing()
    tree = STRtree(existing) if existing else None

    kept, dropped_overlap, dropped_size, scanned = [], 0, 0, 0
    with gzip.open(SRC, "rt") as f:
        for line in f:
            try:
                feat = json.loads(line)
            except Exception:
                continue
            scanned += 1
            ring = feat["geometry"]["coordinates"][0]
            lon0, lat0 = ring[0]
            if not (-89.56 < lon0 < -89.41 and 41.79 < lat0 < 41.91):
                continue
            pts = []
            for lon, lat in ring:
                E, N = to_utm.transform(lon, lat)
                pts.append((E - E0, -(N - N0)))
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
                if poly.is_empty or poly.geom_type != "Polygon":
                    continue
            cx, cz = poly.centroid.x, poly.centroid.y
            if not (0 <= cx <= SIZE and -SIZE <= cz <= 0):
                continue
            if not (MIN_AREA_M2 <= poly.area <= MAX_AREA_M2):
                dropped_size += 1
                continue
            poly = poly.simplify(SIMPLIFY_M, preserve_topology=True)
            if poly.is_empty or len(poly.exterior.coords) < 4:
                continue
            if tree is not None:
                hit = False
                # shapely 2's STRtree.query returns numpy integer INDICES, not geometries.
                # Treating them as geometries made every intersection test throw and get
                # swallowed, so the first run reported 0 overlaps against 707 OSM buildings.
                for idx in tree.query(poly):
                    other = existing[int(idx)]
                    try:
                        inter = poly.intersection(other).area
                    except Exception:
                        continue
                    if inter / max(poly.area, 1e-6) > OVERLAP_FRAC:
                        hit = True
                        break
                if hit:
                    dropped_overlap += 1
                    continue
            coords = list(poly.exterior.coords)[:-1]
            # CCW in (x, z) to match the rest of the buildings pipeline
            area2 = sum(coords[i][0] * coords[(i + 1) % len(coords)][1]
                        - coords[(i + 1) % len(coords)][0] * coords[i][1]
                        for i in range(len(coords)))
            if area2 < 0:
                coords.reverse()
            h = feat["properties"].get("height")
            kept.append({
                "id": 800000000 + len(kept),
                "source": "ms",
                "footprint": [{"x": round(x, 2), "z": round(z, 2)} for x, z in coords],
                "height_m": round(float(h), 1) if h and float(h) > 2.0 else None,
                "tags": {"building": "yes"},
            })

    json.dump({"note": "Microsoft ML building footprints (ODbL), clipped to the play area "
                       "and de-duplicated against OSM/curated/landmark footprints.",
               "buildings": kept}, open(OUT, "w"))
    with_h = sum(1 for b in kept if b["height_m"])
    print(f"scanned {scanned} features")
    print(f"kept {len(kept)}  (dropped {dropped_overlap} overlapping existing, {dropped_size} bad size)")
    print(f"heights on {with_h} of them")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
