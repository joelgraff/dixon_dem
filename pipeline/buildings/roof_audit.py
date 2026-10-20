#!/usr/bin/env python3
"""Footprints with no roof in the 2025 aerial, listed for review (nothing is deleted).

For each OSM, curated, and Microsoft outline (footprints.all_outlines), the corrected 2025
6-inch aerial (pipeline/roads/aerial_width.Aerial, placed by each tile's affine) is sampled
every 0.5 m inside the outline, 0.75 m in from its edge. `lawn` is the share of those
samples that look like lawn: excess green 2g - r - b above EXG_GREEN (the April lawn is olive,
redder than green but low in blue) and darker than MAX_LUMA, so white roofs do not count.
`bare` is the share (of the rest) that looks like bare ground: tan dirt, gravel and the
warm, weathered asphalt of a lot, between BARE_LUMA and warmer than BARE_WARM (red over blue).
Real roofs are rarely green: the median Microsoft footprint scores 0.11 lawn and nine in ten
stay under 0.35; nine in ten score under 0.06 bare. Retired procedural infill, placed with no
imagery, scored a median 0.65 lawn. An outline whose open ground (lawn + bare) is at least
GROUND_FLAG is listed, `why` naming the larger. Green metal roofs score lawn and gravel or tan
flat roofs score bare (about half the bare flags, 2026-10-19), so this is a list to look at,
worst first, with a contact sheet of the first ones (yellow: the outline; cyan: its
neighbours). Only the part of an outline that no other outline covers is sampled (when there
are at least 4 m2 of it): a Microsoft blob drawn over a dirt lot and the OSM building inside it
is judged by the lot, not by the other building's roof. Buildings on the street are listed by encroachment.py --review and the layout
report.

Run: cd pipeline/buildings && ../../.venv/bin/python roof_audit.py
Writes docs/footprint_aerial_audit/roofless_review.json and roofless_review.png.
"""
import json
import os
import sys

import numpy as np
from shapely import contains_xy
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "roads"))
import aerial_width  # noqa: E402
import footprints  # noqa: E402

ROOT = footprints.ROOT
OUT_DIR = os.path.join(ROOT, "docs", "footprint_aerial_audit")
GROUND_FLAG = 0.6
EXG_GREEN = 0.04         # excess green 2g - r - b: April lawn here is olive (r > g), but low in blue
MAX_LUMA = 0.45          # brighter than this is a white roof or bare dirt, not lawn
BARE_LUMA = (0.40, 0.72)  # tan dirt, gravel, a weathered lot: lighter than shingle or tar, darker than white
BARE_WARM = 0.06         # ... and warm: red over blue above this (grey and white roofs are neutral)
STEP_M = 0.5
INSET_M = 0.75
SHEET = 24


def ground_shares(aerial, poly):
    """(lawn, bare) shares of the samples inside `poly`, or None where too few were seen."""
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
    luma = (r + g + b) / 3
    lawn = (2 * g - r - b > EXG_GREEN) & (luma < MAX_LUMA)
    bare = ~lawn & (luma > BARE_LUMA[0]) & (luma < BARE_LUMA[1]) & (r - b > BARE_WARM)
    return float(lawn.mean()), float(bare.mean())


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
        draw.text((4, 4), f"{row['source']} {row['id']} lawn {row['lawn']:.2f} bare {row['bare']:.2f}",
                  fill=(255, 255, 0))
        sheet.paste(img.resize((cell, cell)), ((k % cols) * cell, (k // cols) * cell))
    sheet.save(path)


def main():
    aerial = aerial_width.Aerial()
    outlines = footprints.all_outlines()
    rows, unseen = [], 0
    polys = []
    for rec in outlines:
        poly = Polygon(rec["footprint"])
        polys.append(poly if poly.is_valid else poly.buffer(0))
    tree = STRtree(polys)
    for i, (rec, poly) in enumerate(zip(outlines, polys)):
        others = [polys[j] for j in tree.query(poly, predicate="intersects") if j != i]
        own = poly.difference(unary_union(others)) if others else poly
        shares = ground_shares(aerial, own if own.area >= 4.0 else poly)
        if shares is None:
            unseen += 1
            continue
        lawn, bare = shares
        if lawn + bare >= GROUND_FLAG:
            c = poly.centroid
            rows.append({"id": rec["id"], "source": rec["source"], "lawn": round(lawn, 2), "bare": round(bare, 2),
                         "ground": round(lawn + bare, 2), "why": "lawn" if lawn >= bare else "bare",
                         "area_m2": round(poly.area, 1), "at": [round(c.x, 1), round(c.y, 1)]})
    rows.sort(key=lambda r: (-r["ground"], -r["area_m2"]))
    by_source, by_why = {}, {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        by_why[r["why"]] = by_why.get(r["why"], 0) + 1
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "roofless_review.json"), "w") as handle:
        json.dump({"note": "Footprints whose inside is mostly open ground (lawn, or bare dirt, gravel "
                           "or lot) in the 2025 aerial: review, do not delete blindly (a tree crown or "
                           "a green roof scores lawn, a gravel or tan flat roof scores bare). "
                           "Made by pipeline/buildings/roof_audit.py.",
                   "ground_flag": GROUND_FLAG, "outlines": len(outlines), "outside_aerial": unseen,
                   "flagged_by_source": by_source, "flagged_by_why": by_why, "flagged": rows}, handle, indent=1)
    contact_sheet(aerial, rows[:SHEET], outlines, os.path.join(OUT_DIR, "roofless_review.png"))
    print(f"{len(outlines)} outlines, {unseen} outside the aerial, {len(rows)} flagged: {by_source} {by_why}")


if __name__ == "__main__":
    main()
