#!/usr/bin/env python3
"""Draws what imagery we hold for the play area, and at what resolution.

The project now has three kinds of reference imagery with very different quality and
georeference reliability, and it is easy to lose track of which ground is covered by
which. This renders one overview PNG plus a manifest so coverage is checkable at a glance
before anyone traces anything.

Layers drawn, best resolution last so it sits on top:
  * play-area boundary and the road network, for orientation
  * Illinois 2025 6-inch tiles      (exact georeference, north-up)
  * the original downtown aerial    (fitted, rotated ~344 deg, +-1-2 m)
  * user Google Earth captures      (georeferenced from their URL, rotated)

Run: cd pipeline/aerial && ../../.venv/bin/python coverage_map.py
"""
import glob
import json
import math
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "pipeline", "buildings"))
import classify  # noqa: E402

OUT_PNG = os.path.join(ROOT, "captures", "aerial", "coverage.png")
OUT_JSON = os.path.join(ROOT, "docs", "imagery_coverage.json")
MPP = 2.0   # metres per pixel of the overview itself


def main():
    origin = json.load(open(os.path.join(ROOT, "game", "data", "world_origin.json")))
    size_m = origin["size_m"]
    W = H = int(size_m / MPP)

    img = Image.new("RGB", (W, H), (26, 28, 30))
    d = ImageDraw.Draw(img, "RGBA")

    def w2p(x, z):
        return (x / MPP, (z + size_m) / MPP)   # world z in -size..0 -> 0..H

    # --- context: water, then roads
    water = json.load(open(os.path.join(ROOT, "game", "data", "water.json")))
    for reach in water.get("reaches", []):
        poly = [w2p(p["x"], p["z"]) for p in reach.get("polygon", [])]
        if len(poly) >= 3:
            d.polygon(poly, fill=(38, 62, 84, 255))
    for way in json.load(open(os.path.join(ROOT, "game", "data", "roads.json")))["ways"]:
        vs = way["vertices"]
        cls = (way.get("tags") or {}).get("highway")
        wdt = 2 if cls in ("primary", "secondary", "trunk") else 1
        for i in range(len(vs) - 1):
            d.line([w2p(vs[i]["x"], vs[i]["z"]), w2p(vs[i + 1]["x"], vs[i + 1]["z"])],
                   fill=(90, 94, 100, 255), width=wdt)

    manifest = {"play_area_m": size_m, "sources": []}

    # --- Illinois 2025 tiles (exact, axis-aligned)
    tiles = sorted(glob.glob(os.path.join(ROOT, "data", "raw", "il2025", "*_georef.json")))
    il_area = 0.0
    for t in tiles:
        m = json.load(open(t))
        if not os.path.exists(os.path.join(os.path.dirname(t), m["tile"] + ".png")):
            continue
        p0 = w2p(m["world_x0"], m["world_z0"])
        p1 = w2p(m["world_x1"], m["world_z1"])
        d.rectangle([p0, p1], fill=(60, 200, 110, 46), outline=(80, 230, 130, 190))
        il_area += (m["world_x1"] - m["world_x0"]) * (m["world_z1"] - m["world_z0"])
    if tiles:
        manifest["sources"].append({
            "name": "Illinois 2025 orthoimagery",
            "native_mpp": 0.1524, "fetched_mpp": json.load(open(tiles[0]))["mpp"],
            "tiles": len(tiles), "georeference": "exact (bbox request, north-up)",
            "covers_m2": round(il_area), "path": "data/raw/il2025/",
        })

    # --- the original downtown aerial (rotated, fitted)
    aer = os.path.join(ROOT, "screenshots", "dixon_downtown_aerial.png")
    if os.path.exists(aer):
        w, h = classify.AERIAL_SIZE
        quad = [w2p(*classify.aerial_px_to_world(px, py))
                for px, py in ((0, 0), (w, 0), (w, h), (0, h))]
        d.polygon(quad, fill=(235, 170, 40, 40), outline=(245, 185, 60, 230))
        manifest["sources"].append({
            "name": "Google Earth downtown aerial (user)",
            "native_mpp": round(1.0 / classify.AERIAL_SCALE, 3),
            "georeference": "fitted to OSM, +-1-2 m, rotated ~344 deg",
            "path": "screenshots/dixon_downtown_aerial.png",
        })

    # --- user Earth tiles registered from their URL
    n_tiles = 0
    for g in sorted(glob.glob(os.path.join(ROOT, "references", "aerial", "*_georef.json"))):
        m = json.load(open(g))
        if m.get("source") != "google_earth_url":
            continue
        w, h = m["size_px"]
        cx, cz = m["centre_world"]
        rx, rz = m["right_vec"]
        dx, dz = m["down_vec"]
        s = m["px_per_m"]
        pts = []
        for px, py in ((0, 0), (w, 0), (w, h), (0, h)):
            a = (px - w / 2.0) / s
            b = (py - h / 2.0) / s
            pts.append(w2p(cx + rx * a + dx * b, cz + rz * a + dz * b))
        d.polygon(pts, fill=(250, 90, 190, 46), outline=(255, 110, 205, 230))
        n_tiles += 1
        manifest["sources"].append({
            "name": os.path.basename(m["image"]),
            "native_mpp": round(1.0 / m["px_per_m"], 3),
            "georeference": f"from Earth URL, heading {m.get('heading_deg')} deg",
            "path": m["image"],
        })

    # --- legend
    d.rectangle([8, 8, 470, 118], fill=(0, 0, 0, 170))
    d.text((18, 16), "DIXON IMAGERY COVERAGE   (play area %.1f x %.1f km)"
           % (size_m / 1000, size_m / 1000), fill=(235, 235, 235))
    rows = [((80, 230, 130), f"Illinois 2025 6-inch - exact georef - {len(tiles)} tiles"),
            ((245, 185, 60), "Google Earth downtown aerial - fitted, rotated"),
            ((255, 110, 205), f"Earth captures from URL - {n_tiles}"),
            ((90, 94, 100), "roads / river (context only)")]
    for i, (col, label) in enumerate(rows):
        y = 40 + i * 19
        d.rectangle([18, y, 34, y + 12], fill=col + (200,), outline=(240, 240, 240, 120))
        d.text((42, y), label, fill=(225, 225, 225))

    os.makedirs(os.path.dirname(OUT_PNG), exist_ok=True)
    img.save(OUT_PNG)
    manifest["generated_by"] = "pipeline/aerial/coverage_map.py"
    json.dump(manifest, open(OUT_JSON, "w"), indent=1)
    pct = 100.0 * il_area / (size_m * size_m)
    print(f"Illinois 6-inch covers {il_area/1e6:.2f} km2 of the {size_m*size_m/1e6:.2f} km2 "
          f"play area ({pct:.0f}%)")
    print("wrote", OUT_PNG)
    print("wrote", OUT_JSON)


if __name__ == "__main__":
    main()
