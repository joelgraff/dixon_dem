"""Review images: fitted alignments over the 2025 aerial (build_alignments.py --overlay).

Red: the OSM centreline. Cyan: tangents. Magenta: curves. Yellow dots: PIs; orange crosses:
angle points (PIs with no curve). White rings: junction control points. Green ticks: the
edges of the blocks the width survey counted. One image per 300 m square of the play area, at
0.25 m per pixel, in captures/roads/alignments/ (gitignored).

    ../../.venv/bin/python alignment_overlay.py X Z [HALF_M]   one window centred on X, Z
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import alignment as al  # noqa: E402
import common_roads  # noqa: E402,F401  (puts pipeline/ on the path)
import common as pc  # noqa: E402

OUT_DIR = os.path.join(pc.ROOT, "captures", "roads", "alignments")
MPP = 0.25

_aerial = None


def aerial(x0, z0, x1, z1, mpp=MPP):
    """The aerial over a world window (pixels placed by each tile's affine), as a PIL image."""
    global _aerial
    if _aerial is None:
        import aerial_width
        _aerial = aerial_width.Aerial()
    w, h = int(round((x1 - x0) / mpp)), int(round((z1 - z0) / mpp))
    gx, gz = np.meshgrid(x0 + (np.arange(w) + 0.5) * mpp, z0 + (np.arange(h) + 0.5) * mpp)
    rgb = np.nan_to_num(_aerial.sample(gx, gz), nan=0.16)
    return Image.fromarray((rgb * 255).astype(np.uint8))


def render(data, x0, z0, x1, z1, path, osm=None, edges=None, mpp=MPP):
    img = aerial(x0, z0, x1, z1, mpp)
    d = ImageDraw.Draw(img)

    def px(p):
        return ((p[0] - x0) / mpp, (p[1] - z0) / mpp)

    def visible(pts):
        a = np.asarray(pts)
        return (a[:, 0].max() >= x0 and a[:, 0].min() <= x1 and a[:, 1].max() >= z0 and a[:, 1].min() <= z1)

    for line in (osm or []):
        if visible(line):
            d.line([px(p) for p in line], fill=(255, 40, 40), width=1)
    for r in data["routes"]:
        if not visible(r["pis"]):
            continue
        a = al.Alignment(r["pis"], r["radii"])
        for e in a.elements:
            n = max(2, int((e["sta"][1] - e["sta"][0]) / 0.5))
            pts = [a.point_at(s)[:2] for s in np.linspace(e["sta"][0], e["sta"][1], n)]
            d.line([px(p) for p in pts], fill=(0, 230, 255) if e["type"] == "tangent" else (255, 0, 255), width=2)
        for i, (p, rad) in enumerate(zip(r["pis"], r["radii"])):
            x, y = px(p)
            if 0 < i < len(r["pis"]) - 1 and rad <= 0:
                d.line([(x - 5, y - 5), (x + 5, y + 5)], fill=(255, 140, 0), width=2)
                d.line([(x - 5, y + 5), (x + 5, y - 5)], fill=(255, 140, 0), width=2)
            else:
                d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 230, 0))
    for j in data["junctions"]:
        x, y = px((j["x"], j["z"]))
        if 0 <= x < img.width and 0 <= y < img.height:
            d.ellipse([x - 6, y - 6, x + 6, y + 6], outline=(255, 255, 255), width=2)
    for line in (edges or []):
        if visible(line):
            d.line([px(p) for p in line], fill=(60, 255, 60), width=2)
    img.save(path)
    return path


def _osm_lines():
    with open(os.path.join(pc.GAME_DATA, "roads.json")) as handle:
        return [[(v["x"], v["z"]) for v in w["vertices"]] for w in json.load(handle)["ways"]]


def draw(data, edges=(), size=300.0):
    """One image per `size` square of the play area that holds a route."""
    os.makedirs(OUT_DIR, exist_ok=True)
    osm = _osm_lines()
    n = int(math.ceil(2700.0 / size))
    written = 0
    for i in range(n):
        for k in range(n):
            x0, z0 = i * size, -2700.0 + k * size
            x1, z1 = x0 + size, z0 + size
            if not any(x0 <= p[0] <= x1 and z0 <= p[1] <= z1 for r in data["routes"] for p in r["pis"]):
                continue
            render(data, x0, z0, x1, z1, os.path.join(OUT_DIR, f"align_{i:02d}_{k:02d}.png"), osm, edges)
            written += 1
    print(f"overlay: {written} images in {OUT_DIR}")


if __name__ == "__main__":
    with open(os.path.join(pc.GAME_DATA, "alignments.json")) as handle:
        data = json.load(handle)
    x, z = float(sys.argv[1]), float(sys.argv[2])
    half = float(sys.argv[3]) if len(sys.argv) > 3 else 75.0
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"window_{int(x)}_{int(z)}.png")
    print(render(data, x - half, z - half, x + half, z + half, out, _osm_lines()))
