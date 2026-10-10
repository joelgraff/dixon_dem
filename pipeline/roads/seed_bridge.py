#!/usr/bin/env python3
"""Writes a starting design for a bridge, for Bridge Composer to open and refine.

  ../../.venv/bin/python seed_bridge.py 114082270            # prints the file
  ../../.venv/bin/python seed_bridge.py 114082270 --write    # game/data/bridges_composed/<id>.json

The seed is what the road plan generates today, expressed as a design: the OSM
centreline and width, the deck at the way's design height with ramps down to the
ground at each end (at most 8% grade), abutments at the ends and a girder span
every ~20 m between them.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bridges_composed as bc  # noqa: E402
import common as pc  # noqa: E402
from common_roads import Heightmap  # noqa: E402

MAX_GRADE = 0.08
SPAN_M = 20.0


def seed(way_id):
    with open(os.path.join(pc.ROOT, "game", "data", "bridges.json")) as handle:
        ways = json.load(handle)["bridges"]
    way = next((w for w in ways if str(w["id"]) == str(way_id)), None)
    if way is None:
        raise SystemExit(f"no bridge way {way_id} in game/data/bridges.json")
    pts = [[round(v["x"], 2), round(v["z"], 2)] for v in way["vertices"]]
    length = bc.centerline_length(pts)
    hm = Heightmap()
    deck_y = sum(v["y"] for v in way["vertices"]) / len(way["vertices"])
    g0, g1 = hm.sample(*pts[0]) + 0.02, hm.sample(*pts[-1]) + 0.02
    ramp0 = min(abs(deck_y - g0) / MAX_GRADE, length * 0.45)
    ramp1 = min(abs(deck_y - g1) / MAX_GRADE, length * 0.45)
    elevation = [[0.0, round(g0, 3)]]
    if ramp0 > 0.5:
        elevation.append([round(ramp0, 2), round(deck_y, 3)])
    if length - ramp1 > elevation[-1][0] + 0.5:
        elevation.append([round(length - ramp1, 2), round(deck_y, 3)])
    elevation.append([round(length, 2), round(g1, 3)])
    n = max(1, round(length / SPAN_M))
    supports = [{"kind": "abutment", "station": 0.0, "length": 1.5}]
    for k in range(1, n):
        supports.append({"kind": "pier", "station": round(length * k / n, 2), "length": 1.4,
                         "width": 6.0, "shape": "bullnose"})
    supports.append({"kind": "abutment", "station": round(length, 2), "length": 1.5})
    tags = way["tags"]
    return {
        "format": bc.FORMAT, "version": bc.VERSION, "id": str(way_id),
        "name": None,   # a name given in Bridge Composer; otherwise the server derives one
        "centerline": pts,
        "deck": {"width": float(tags.get("width_m") or 8.0), "thickness": 0.3, "elevation": elevation},
        "supports": supports,
        "spans": [{"type": "girder", "depth": 0.9, "haunch": 0.5} for _ in range(len(supports) - 1)],
        "cross_section": {"barrier_h": 0.9, "barrier_w": 0.4, "sidewalk_w": 0.0, "rail_h": 0.0},
        "lamps": {"spacing": 25.0},
        "materials": {},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("way_id")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    data = seed(args.way_id)
    bc.validate(data)
    text = json.dumps(data, indent=1)
    if args.write:
        os.makedirs(bc.COMPOSED_DIR, exist_ok=True)
        path = bc.path_for(args.way_id)
        with open(path, "w") as handle:
            handle.write(text + "\n")
        print(f"wrote {path}")
    else:
        print(text)


if __name__ == "__main__":
    main()
