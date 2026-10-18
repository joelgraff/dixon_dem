#!/usr/bin/env python3
"""Writes the parity fixtures Bridge Composer's preview is tested against.

  ../../.venv/bin/python dump_bridge_counts.py ../../../bridge-composer/tests/fixtures/parity.json

Each fixture is a design plus a ground rule and what bridges_composed.build makes of it
(triangles per material, bounds, supports skipped, lamps, profile length). The preview's
js/geometry.js must produce the same; tests/parity.test.js asserts it. Run this again,
and commit both, whenever bridges_composed.py's geometry changes.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bridges_composed as bc  # noqa: E402


def straight(**over):
    data = {
        "format": "dixon-bridge", "version": 1, "id": "1",
        "centerline": [[0.0, 0.0], [90.0, 0.0]],
        "deck": {"width": 12.0, "thickness": 0.3, "elevation": [[0.0, 6.0], [20.0, 8.0], [70.0, 8.0], [90.0, 6.0]]},
        "supports": [
            {"kind": "abutment", "station": 0.0, "length": 1.5},
            {"kind": "pier", "station": 30.0, "length": 1.4, "width": 6.0, "shape": "bullnose"},
            {"kind": "pier", "station": 60.0, "length": 1.2, "width": 5.0, "shape": "rect"},
            {"kind": "abutment", "station": 90.0, "length": 2.0},
        ],
        "spans": [{"type": "girder", "depth": 0.9, "haunch": 0.5}, {"type": "arch", "rise": 5.0, "ring": 0.6},
                  {"type": "slab", "depth": 0.5}],
        "cross_section": {"barrier_h": 0.9, "barrier_w": 0.4, "barrier_rail_h": 0.35, "walkway_w": 2.4,
                          "walkway_sides": "both", "parapet_w": 0.35, "parapet_h": 0.6, "rail_h": 1.05,
                          "barrier_rail_style": "pipe", "outer_type": "metal", "curb_h": 0.2, "rail_style": "picket"},
        "lamps": {"spacing": 22.0},
        "materials": {"arch": "stone_foundation"},
    }
    data.update(over)
    return data


FIXTURES = [
    ("straight, mixed spans, valley ground", straight(), {"kind": "vee", "y0": 9.0, "slope": 0.12, "center": 45.0}),
    ("straight, no sidewalk or rail, flat ground", straight(
        cross_section={"barrier_h": 0.9, "barrier_w": 0.4, "rail_h": 0.5, "rail_style": "panel"}, lamps=None), {"kind": "flat", "y": 0.0}),
    ("bent centreline, girders", straight(
        centerline=[[0.0, 0.0], [40.0, 0.0], [70.0, 30.0], [70.0, 80.0]],
        deck={"width": 9.0, "thickness": 0.3, "elevation": [[0.0, 5.0], [120.0, 5.0]]},
        supports=[{"kind": "abutment", "station": 0.0}, {"kind": "pier", "station": 55.0, "width": 5.0},
                  {"kind": "pier", "station": 95.0, "length": 1.6, "width": 5.0, "shape": "bullnose"},
                  {"kind": "abutment", "station": 120.0}],
        spans=[{"type": "girder"}, {"type": "girder", "depth": 1.2}, {"type": "slab"}],
        cross_section={"barrier_h": 1.0, "barrier_w": 0.5, "walkway_w": 3.0, "walkway_sides": "left",
                       "walkway_rise": 0.12, "parapet_w": 0.4, "parapet_h": 0.5, "rail_h": 0.4, "rail_style": "pipe",
                       "barrier_rail_h": 0.3, "barrier_rail_style": "picket"},
        lamps={"spacing": 30.0}), {"kind": "flat", "y": -1.0}),
    ("a pier that is skipped (ground above the deck)", straight(), {"kind": "flat", "y": 20.0}),
]


def ground_fn(rule):
    if rule["kind"] == "flat":
        return lambda x, z: rule["y"]
    return lambda x, z: rule["y0"] - abs(x - rule["center"]) * rule["slope"]


def main():
    out_path = sys.argv[1]
    fixtures = []
    for name, design, rule in FIXTURES:
        data = {k: v for k, v in design.items() if v is not None}
        bc.validate(data)
        meshes, furniture = {}, {}
        # the bent fixture's ground is flat, so x is as good as the station
        result = bc.build(meshes, furniture, data, ground=ground_fn(rule))
        lo = [math.inf] * 3
        hi = [-math.inf] * 3
        for mb in meshes.values():
            for v in mb.verts:
                for k in range(3):
                    lo[k], hi[k] = min(lo[k], v[k]), max(hi[k], v[k])
        fixtures.append({
            "name": name, "design": data, "ground": rule,
            "expected": {
                "triangles": {m: len(mb.indices) // 3 for m, mb in sorted(meshes.items())},
                "vertices": {m: len(mb.verts) for m, mb in sorted(meshes.items())},
                "bounds": {"lo": [round(v, 4) for v in lo], "hi": [round(v, 4) for v in hi]},
                "lamps": len(furniture.get("lamp_downtown", [])),
                "profile_length": len(result["profile"]),
                "warnings": len(result["warnings"]),
            },
        })
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w") as handle:
        json.dump({"fixtures": fixtures}, handle, indent=1)
    print(f"wrote {len(fixtures)} fixtures to {out_path}")


if __name__ == "__main__":
    main()
