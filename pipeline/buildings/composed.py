"""A building designed in Building Composer, dropped in place of the one the
pipeline would generate. Composer's "Send to game" writes
game/data/composed/<id>.json (see docs/buildings_notes.md); this reads it into
the chunk's meshes. The mesh is already in game space, in Godot's winding and
with outward normals, so nothing is oriented here.
"""
import json
import os

import facade
import palette

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COMPOSED_DIR = os.path.join(ROOT, "game", "data", "composed")

WALL_MATERIALS = ("brick_red", "brick_buff", "brick_rose", "brick_dark", "brick_cream", "siding_white",
                  "siding_sage", "siding_blue", "siding_butter", "siding_gray", "limestone", "roof_metal")


def path_for(bid, directory=None):
    return os.path.join(directory or COMPOSED_DIR, f"{bid}.json")


def load(bid, directory=None):
    """The composed building for this id, or None if there is none (or it is unreadable)."""
    path = path_for(bid, directory)
    if bid is None or not os.path.exists(path):
        return None
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if data.get("format") != "dixon-composed" or not isinstance(data.get("near"), dict):
        return None
    return data


def wanted(template):
    """Composed buildings are used unless the building's override turns them off (the game's revert)."""
    return (template or {}).get("composed") is not False


def build(mb, mb_far, coords, ground_y, data):
    """Adds the composed mesh to `mb` (heights relative to `ground_y`) and a far box to `mb_far`."""
    shown = None
    for material, group in data["near"].items():
        base = len(mb._grp(material)["verts"])
        for v in group["verts"]:
            mb.add_vertex(material, (v[0], v[1] + ground_y, v[2]), (v[3], v[4], v[5]), (v[6], v[7]), (v[8], v[9], v[10], v[11]))
        indices = group["indices"]
        for i in range(0, len(indices) - 2, 3):
            mb.add_tri(material, base + indices[i], base + indices[i + 1], base + indices[i + 2])
        if shown is None or (material in WALL_MATERIALS and len(indices) > shown[1]):
            shown = (material, len(indices))
    y0 = ground_y + float(data["y0"])
    y1 = ground_y + float(data["y1"])
    hull = [tuple(p) for p in data["hull"]]
    color = palette.APPROX_COLOR.get(shown[0] if shown else "", (0.8, 0.8, 0.8))
    facade.far_box(mb_far, hull, y0, y1, color, window_glow=0.12)
    return {"hull": hull, "y0": y0, "y1": y1}
