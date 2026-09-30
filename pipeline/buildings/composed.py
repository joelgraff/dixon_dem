"""A building designed in Building Composer, dropped in place of the one the
pipeline would generate. Composer's "Send to game" writes
game/data/composed/<id>.json (see docs/buildings_notes.md); this reads it into
the chunk's meshes. The mesh is already in game space, in Godot's winding and
with outward normals, so nothing is oriented here.

A walk-in building (version 2, `interior: true`) also carries
`collision.faces`, every triangle a character collides with (flat x, y, z
triples); those replace its hull as its collision (build_buildings.gd makes
them a double-sided ConcavePolygonShape3D), so its rooms can be walked into.
A file made against another version of the palette (`materials_version`, the
manifest hash) is still used, with a warning.
"""
import json
import os

import facade
import palette

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COMPOSED_DIR = os.path.join(ROOT, "game", "data", "composed")

# The far box takes the tint of the largest group in one of these.
WALL_MATERIALS = tuple(name for name, kinds in palette.CATEGORIES.items() if "wall" in kinds)


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


def unknown_materials(data):
    """The material names a composed file uses that the game doesn't have."""
    return sorted(name for name in data["near"] if name not in palette.MATERIALS)


def build(mb, mb_far, coords, ground_y, data):
    """Adds the composed mesh to `mb` (heights relative to `ground_y`) and a far box to `mb_far`."""
    unknown = unknown_materials(data)
    if unknown:
        print(f"composed building {data.get('id')}: no game material {', '.join(unknown)}; "
              "those surfaces will be untextured (resend it from Building Composer)")
    made_with = data.get("materials_version")
    if made_with and made_with != palette.manifest()["hash"]:
        print(f"composed building {data.get('id')}: made with materials {made_with}, the game has "
              f"{palette.manifest()['hash']}; resend it from Building Composer if it looks wrong")
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
    result = {"hull": hull, "y0": y0, "y1": y1}
    faces = collision_faces(data, ground_y)
    if faces:
        result["faces"] = faces
    return result


def collision_faces(data, ground_y):
    """A walk-in building's collision triangles, flat x, y, z with heights on
    the ground, or None for a solid one (or a file whose faces are unusable)."""
    faces = (data.get("collision") or {}).get("faces") if data.get("interior") else None
    if not isinstance(faces, list) or len(faces) < 9 or len(faces) % 9:
        return None
    try:
        values = [float(v) for v in faces]
    except (TypeError, ValueError):
        return None
    for i in range(1, len(values), 3):
        values[i] += ground_y
    return values
