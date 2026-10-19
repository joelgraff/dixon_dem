#!/usr/bin/env python3
"""Footprints with no roof in the 2025 aerial, listed for review (nothing is deleted).

For each OSM, curated, and Microsoft outline (footprints.all_outlines), the corrected 2025
6-inch aerial (pipeline/roads/aerial_width.Aerial, placed by each tile's affine) is sampled
every 0.5 m inside the outline, 0.75 m in from its edge. `lawn` is the share of those
samples that look like lawn: excess green 2g - r - b above EXG_GREEN (the April lawn is olive,
redder than green but low in blue) and darker than MAX_LUMA, so white roofs and bare tan
dirt do not count. Real roofs are rarely green:
the median Microsoft footprint scores 0.11 and nine in ten stay under 0.35. Retired
procedural infill, placed with no imagery, scored a median 0.65. An outline scoring at
least LAWN_FLAG is listed. Green metal roofs score high too, so this is a list to look at, worst first, with a contact sheet of the first ones (yellow: the
outline; cyan: its neighbours). A demolished building on a paved lot is not green and is
not caught; buildings on the street are listed by encroachment.py and the layout report.

Run: cd pipeline/buildings && ../../.venv/bin/python roof_audit.py
Writes docs/footprint_aerial_audit/roofless_review.json and roofless_review.png.
"""
import json
import os
import sys

import numpy as np
from shapely import contains_xy
from shapely.geometry import Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "roads"))
import aerial_width  # noqa: E402
import footprints  # noqa: E402

ROOT = footprints.ROOT
OUT_DIR = os.path.join(ROOT, "docs", "footprint_aerial_audit")
LAWN_FLAG = 0.6
EXG_GREEN = 0.04         # excess green 2g - r - b: April lawn here is olive (r > g), but low in blue
MAX_LUMA = 0.45          # brighter than this is a white roof or bare dirt, not lawn
STEP_M = 0.5
INSET_M = 0.75
SHEET = 24


def lawn_share(aerial, poly):
    inner = poly.buffer(-INSET_M)
    if inner.is_empty or inner.area < 4.0:
        inner = poly
    x0, z0, x1, z1 = inner.bounds
    xs, zs = np.meshgrid(np.arange(x0, x1, STEP_M), np.arange(z0, z1, STEP_M))
    inside = contains_xy(inner, xs, zs)
    if inside.sum() < 4:
        return None
    rgb = aerial.sample(xs[inside], zs[inside])
    rgb = rgb[~np.isnan(rgb[:, 0])]
    if len(rgb) < 4:
        return None
    r, g, b = rgb.T
    return float(np.mean((2 * g - r - b > EXG_GREEN) & ((r + g + b) / 3 < MAX_LUMA)))


def contact_sheet(aerial, rows, outlines, path, half=30.0, mpp=0.25, cell=240):
    from PIL import Image, ImageDraw
    sys.path.insert(0, os.path.join(HERE, "..", "roads"))
    import alignment_overlay
    cols = 4
    sheet = Image.new("RGB", (cell * cols, cell * ((len(rows) + cols - 1) // cols)))
    for k, row in enumerate(rows):
        x, z = row["at"]
        x0, z0 = x - half, z - half
        img = alignment_overlay.aerial(x0, z0, x + half, z + half, mpp)
        draw = ImageDraw.Draw(img)
        for rec in footprints.in_box(outlines, x0, z0, x + half, z + half):
            ring = [((px - x0) / mpp, (pz - z0) / mpp) for px, pz in rec["footprint"]]
            draw.line(ring + ring[:1], fill=(255, 230, 0) if rec["id"] == row["id"] else (0, 230, 255), width=2)
        draw.text((4, 4), f"{row['source']} {row['id']} lawn {row['lawn']:.2f}", fill=(255, 255, 0))
        sheet.paste(img.resize((cell, cell)), ((k % cols) * cell, (k // cols) * cell))
    sheet.save(path)


def main():
    aerial = aerial_width.Aerial()
    outlines = footprints.all_outlines()
    rows, unseen = [], 0
    for rec in outlines:
        poly = Polygon(rec["footprint"])
        if not poly.is_valid:
            poly = poly.buffer(0)
        share = lawn_share(aerial, poly)
        if share is None:
            unseen += 1
            continue
        if share >= LAWN_FLAG:
            c = poly.centroid
            rows.append({"id": rec["id"], "source": rec["source"], "lawn": round(share, 2),
                         "area_m2": round(poly.area, 1), "at": [round(c.x, 1), round(c.y, 1)]})
    rows.sort(key=lambda r: (-r["lawn"], -r["area_m2"]))
    by_source = {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "roofless_review.json"), "w") as handle:
        json.dump({"note": "Footprints whose inside is mostly lawn in the 2025 aerial: review, "
                           "do not delete blindly (a tree crown or a green roof also scores high). "
                           "Made by pipeline/buildings/roof_audit.py.",
                   "lawn_flag": LAWN_FLAG, "outlines": len(outlines), "outside_aerial": unseen,
                   "flagged_by_source": by_source, "flagged": rows}, handle, indent=1)
    contact_sheet(aerial, rows[:SHEET], outlines, os.path.join(OUT_DIR, "roofless_review.png"))
    print(f"{len(outlines)} outlines, {unseen} outside the aerial, {len(rows)} flagged: {by_source}")


if __name__ == "__main__":
    main()
