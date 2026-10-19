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
STREET_CLASSES = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential")
SPAN_M = 20.0


def street_section():
    """The Galena Ave Bridge's cross-section from the photographs: a concrete safety barrier with a
    steel rail on it, a walkway outside it, and an all-metal railing (pickets between top and bottom
    rails) on a low curb at the outer edge.
    The walkway is as wide as the approach sidewalk it continues."""
    return {"barrier_h": 0.9, "barrier_w": 0.4, "barrier_rail_h": 0.35, "barrier_rail_style": "pipe",
            "walkway_w": 2.5, "walkway_sides": "both", "walkway_rise": bc.WALKWAY_RISE_M,
            "outer_type": "metal", "parapet_w": 0.3, "parapet_h": 0.6, "curb_h": 0.2,
            "rail_h": 1.05, "rail_style": "picket"}


def approach_ends(vertices, approach=15.24):
    """Road heights `approach` m out from each end, read from the play heightmap before roads
    are conformed to it (the same numbers GET /game-bridges sends as approach_y)."""
    import numpy as np
    wo = pc.load_world_origin()["heightmaps"]["play"]
    raw = Heightmap(os.path.join(pc.GAME_DATA, wo["file"]))
    pts = [(v["x"], v["z"]) for v in vertices]
    out = []
    for a, b in ((pts[1], pts[0]), (pts[-2], pts[-1])):
        d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        out.append(round(raw.sample(b[0] + (b[0] - a[0]) / d * approach, b[1] + (b[1] - a[1]) / d * approach) + bc.ROAD_SURFACE_M, 2))
    return out


def seed(way_id, match_approaches=False, crest=0.5):
    with open(os.path.join(pc.ROOT, "game", "data", "bridges.json")) as handle:
        ways = json.load(handle)["bridges"]
    way = next((w for w in ways if str(w["id"]) == str(way_id)), None)
    if way is None:
        raise SystemExit(f"no bridge way {way_id} in game/data/bridges.json")
    pts = [[round(v["x"], 2), round(v["z"], 2)] for v in way["vertices"]]
    length = bc.centerline_length(pts)
    hm = Heightmap()
    deck_y = sum(v["y"] for v in way["vertices"]) / len(way["vertices"])
    g0, g1 = hm.sample(*pts[0]) + bc.ROAD_SURFACE_M, hm.sample(*pts[-1]) + bc.ROAD_SURFACE_M
    if match_approaches:
        # the deck meets the street 50 ft out; the route's vertical profile (build_profiles.py) then
        # holds these heights and the deck's end grades, so the approach and the deck are one surface
        g0, g1 = approach_ends(way["vertices"])
    if match_approaches:
        # a long smooth vertical curve between the street heights, cambered by `crest` at midspan
        elevation = bc.crest_profile(length, g0, g1, crest)
    else:
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
        "deck": dict({"width": float(tags.get("width_m") or 8.0), "thickness": 0.3, "elevation": elevation},
                     **({"profile": {"kind": "crest", "start": g0, "end": g1, "crest": crest}} if match_approaches else {})),
        "supports": supports,
        "spans": [{"type": "girder", "depth": 0.9, "haunch": 0.5} for _ in range(len(supports) - 1)],
        # roadway | barrier | walkway | parapet and rail, from the centreline out (docs/bridge_composer_schema.md);
        # a street bridge gets walkways on both sides, a path bridge none
        "cross_section": street_section() if tags.get("highway") in STREET_CLASSES else {
            "barrier_h": 0.9, "barrier_w": 0.4, "walkway_w": 0.0, "rail_h": 0.0},
        "lamps": {"spacing": 25.0},
        "materials": {},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("way_id")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--match-approaches", action="store_true",
                    help="set the deck ends from the road heights 50 ft out, not the terrain at the abutment")
    ap.add_argument("--crest", type=float, default=0.5, help="midspan rise above the line between the ends, metres")
    args = ap.parse_args()
    data = seed(args.way_id, args.match_approaches, args.crest)
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
