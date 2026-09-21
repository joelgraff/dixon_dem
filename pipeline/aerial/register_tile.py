#!/usr/bin/env python3
"""Georeferences a north-up aerial tile by matching it to the road network.

The user supplies Google Maps screenshots of individual blocks. Rather than trusting a
hand-entered anchor, this fits the tile: it rasterises roads.json into a world-aligned
image at a candidate scale, builds a comparable "paved" mask from the photo, and finds
the (scale, offset) whose normalised cross-correlation peaks. North-up is assumed
(the user frames them that way), so there is no rotation to solve.

Outputs a small JSON next to the tile with px->world parameters, plus an overlay PNG so
the fit can be eyeballed the same way the downtown aerial was checked.

Run: cd pipeline/aerial && ../../.venv/bin/python register_tile.py <tile.jpg> [--cx X --cz Z]
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage, signal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

HALF_W = {
    "motorway": 11.0, "trunk": 9.0, "primary": 9.0, "secondary": 8.0, "tertiary": 7.0,
    "residential": 5.5, "unclassified": 5.5, "living_street": 5.0, "service": 3.4,
    "track": 2.5, "pedestrian": 3.0,
}


def road_mask_world(cx, cz, half_extent, mpp=1.0):
    """Binary road raster in world metres, north-up: +x right, -z up."""
    size = int(2 * half_extent / mpp)
    img = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(img)
    ways = json.load(open(os.path.join(ROOT, "game", "data", "roads.json")))["ways"]
    for w in ways:
        cls = (w.get("tags") or {}).get("highway")
        if cls not in HALF_W:
            continue
        hw = HALF_W[cls]
        pts = []
        for v in w["vertices"]:
            px = (v["x"] - (cx - half_extent)) / mpp
            py = (v["z"] - (cz - half_extent)) / mpp   # -z is north => image y grows south
            pts.append((px, py))
        for i in range(len(pts) - 1):
            d.line([pts[i], pts[i + 1]], fill=255, width=max(1, int(2 * hw / mpp)))
    return (np.asarray(img, dtype=np.float32) / 255.0)


def paved_mask_photo(path):
    img = Image.open(path).convert("RGB")
    rgb = np.asarray(img, dtype=np.float32)
    mx, mn = rgb.max(-1), rgb.min(-1)
    val = mx / 255.0
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    g, r, b = rgb[..., 1], rgb[..., 0], rgb[..., 2]
    veg = (g > r * 1.04) & (g > b * 1.02)
    paved = (val > 0.16) & (val < 0.80) & (sat < 0.40) & ~veg
    return paved.astype(np.float32), img


def ncc_peak(big, small):
    """Best normalised cross-correlation offset of `small` inside `big`."""
    b = big - big.mean()
    s = small - small.mean()
    corr = signal.fftconvolve(b, s[::-1, ::-1], mode="valid")
    denom = np.sqrt((s ** 2).sum() * (b ** 2).sum()) or 1.0
    idx = int(np.argmax(corr))
    y, x = np.unravel_index(idx, corr.shape)
    return float(corr.max() / denom), int(x), int(y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tile")
    ap.add_argument("--cx", type=float, default=1860.0, help="expected world x of tile centre")
    ap.add_argument("--cz", type=float, default=-1380.0, help="expected world z of tile centre")
    ap.add_argument("--search", type=float, default=420.0, help="half-extent of search window (m)")
    args = ap.parse_args()

    tile_path = args.tile if os.path.isabs(args.tile) else os.path.join(ROOT, args.tile)
    photo_mask, photo = paved_mask_photo(tile_path)
    ph, pw = photo_mask.shape

    big = road_mask_world(args.cx, args.cz, args.search, mpp=1.0)
    best = None
    for px_per_m in np.arange(1.8, 6.01, 0.1):
        # resample the photo mask to 1 m/px so it can be compared against the world raster
        tw, th = int(pw / px_per_m), int(ph / px_per_m)
        if tw < 20 or th < 20 or tw >= big.shape[1] or th >= big.shape[0]:
            continue
        small = np.asarray(Image.fromarray((photo_mask * 255).astype(np.uint8)).resize((tw, th)),
                           dtype=np.float32) / 255.0
        small = ndimage.gaussian_filter(small, 1.2)
        score, x, y = ncc_peak(ndimage.gaussian_filter(big, 1.2), small)
        if best is None or score > best[0]:
            best = (score, px_per_m, x, y, tw, th)

    score, px_per_m, x, y, tw, th = best
    # world coords of the tile's top-left pixel
    world_x0 = (args.cx - args.search) + x
    world_z0 = (args.cz - args.search) + y
    out = {
        "tile": os.path.relpath(tile_path, ROOT),
        "north_up": True,
        "px_per_m": round(float(px_per_m), 3),
        "world_x0": round(float(world_x0), 2),
        "world_z0": round(float(world_z0), 2),
        "size_px": [pw, ph],
        "covers_m": [round(pw / px_per_m, 1), round(ph / px_per_m, 1)],
        "ncc_score": round(float(score), 4),
        "note": "px->world: x = world_x0 + px/px_per_m ; z = world_z0 + py/px_per_m",
    }
    meta = os.path.splitext(tile_path)[0] + "_georef.json"
    json.dump(out, open(meta, "w"), indent=1)
    print(json.dumps(out, indent=1))

    # overlay: draw road centrelines + known footprints onto the tile using the fit
    ov = photo.convert("RGB").copy()
    d = ImageDraw.Draw(ov)

    def w2p(wx, wz):
        return ((wx - world_x0) * px_per_m, (wz - world_z0) * px_per_m)

    ways = json.load(open(os.path.join(ROOT, "game", "data", "roads.json")))["ways"]
    for w in ways:
        vs = w["vertices"]
        for i in range(len(vs) - 1):
            a, b = w2p(vs[i]["x"], vs[i]["z"]), w2p(vs[i + 1]["x"], vs[i + 1]["z"])
            if max(a[0], b[0]) < -50 or min(a[0], b[0]) > pw + 50:
                continue
            if max(a[1], b[1]) < -50 or min(a[1], b[1]) > ph + 50:
                continue
            d.line([a, b], fill=(255, 0, 255), width=2)
    bs = json.load(open(os.path.join(ROOT, "game", "data", "buildings.json")))["buildings"]
    for bl in bs:
        pts = [w2p(p["x"], p["z"]) for p in bl["footprint"]]
        if not any(-50 <= px <= pw + 50 and -50 <= py <= ph + 50 for px, py in pts):
            continue
        d.polygon([tuple(p) for p in pts], outline=(0, 255, 255))
    prev = os.path.splitext(tile_path)[0] + "_fit.png"
    ov.save(prev)
    print("overlay:", prev)


if __name__ == "__main__":
    main()
