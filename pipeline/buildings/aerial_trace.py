#!/usr/bin/env python3
"""Turns footprints traced on the user's Google Earth aerial into game/data/buildings_curated.json.

Workflow (repeatable, no Godot needed):
  1. Open screenshots/dixon_downtown_aerial.png. Pixel (0,0) is top-left. In this aerial
     NORTH IS TO THE RIGHT (Galena Ave / the river run left->right).
  2. Add a line to RECTS (axis-aligned pixel rectangles: x0, y0, x1, y1) or POLYS (pixel
     vertex lists) below. Heights are metres; `replaces` optionally lists OSM ids to drop.
  3. cd pipeline/buildings && ../../.venv/bin/python aerial_trace.py
     then re-run build_building_plan.py and the Godot bake (see docs/STATUS.md).

Pixel -> world conversion is classify.aerial_px_to_world (3.0 px/m, fitted to OSM roads and
footprints; accurate to roughly +-2 m near the middle of the image, worse toward the edges).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classify

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "game", "data", "buildings_curated.json")

# name, (x0, y0, x1, y1), height_m, tags
RECTS = [
    ("south_of_theatre_tower", (1200, 580, 1283, 652), 8.5, {"building": "yes"}),
]
# name, [(px,py), ...], height_m, tags
POLYS = []
REPLACES = {}   # name -> [osm ids]


def main():
    recs = []
    next_id = 990000001
    for name, (x0, y0, x1, y1), h, tags in RECTS:
        POLYS.append((name, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], h, tags))
    for name, pts, h, tags in POLYS:
        world = [classify.aerial_px_to_world(px, py) for px, py in pts]
        # buildings.json footprints are CCW in (x,z); make ours the same
        area = sum(world[i][0] * world[(i + 1) % len(world)][1] - world[(i + 1) % len(world)][0] * world[i][1]
                   for i in range(len(world)))
        if area < 0:
            world.reverse()
        recs.append({
            "id": next_id, "name": name, "height_m": h, "tags": dict(tags),
            "footprint": [{"x": round(x, 2), "z": round(z, 2)} for x, z in world],
            "source": "aerial_trace", "replaces": REPLACES.get(name, []),
        })
        next_id += 1
    with open(OUT, "w") as f:
        json.dump({"buildings": recs}, f, indent=1)
    print(f"wrote {len(recs)} curated footprints -> {OUT}")


if __name__ == "__main__":
    main()
