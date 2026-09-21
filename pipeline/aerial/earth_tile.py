#!/usr/bin/env python3
"""Georeferences a Google Earth capture from its URL. Exact, no image matching.

A Google Earth web URL carries everything needed:
    @LAT,LON,ALTa,DISTd,FOVy,HEADINGh,TILTt,ROLLr
  LAT/LON  centre of view          DIST  camera-to-target distance (m)
  FOV      vertical field of view  HEADING  compass bearing that points UP in the image
  TILT     must be 0 (straight down) or the ground is not a plane in the image

Ground height covered = 2 * DIST * tan(FOV/2); scale = image_height_px / that.
HEADING matters: Dixon's street grid runs ~344 deg, and Google Earth snaps to it, so
captures that look "north up" are usually rotated ~17 deg. Assuming north-up puts every
extracted footprint in the wrong place, which is exactly what happened on the first tile.

Usage:
  earth_tile.py --image references/aerial/1_crawford_2nd.jpg \\
                --url "https://earth.google.com/web/@41.844,-89.481,207a,464d,35y,342.37h,0t,0r/..."
Writes <image>_georef.json and an overlay <image>_fit.png for eyeball verification.
"""
import argparse
import json
import math
import os
import re
import sys

import numpy as np
from scipy import ndimage, signal

from PIL import Image, ImageDraw
from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

URL_RE = re.compile(
    r"@(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)a,(-?[\d.]+)d,(-?[\d.]+)y,(-?[\d.]+)h,(-?[\d.]+)t,(-?[\d.]+)r")


def parse_url(url):
    m = URL_RE.search(url)
    if not m:
        raise SystemExit("could not find the @lat,lon,...a,...d,...y,...h,...t,...r block in that URL")
    lat, lon, alt, dist, fov, head, tilt, roll = (float(g) for g in m.groups())
    if abs(tilt) > 0.5:
        print(f"WARNING: tilt is {tilt} deg, not 0 - the capture is oblique and the "
              f"pixel->ground mapping will be wrong. Re-capture looking straight down.")
    return dict(lat=lat, lon=lon, alt=alt, dist=dist, fov=fov, heading=head, tilt=tilt, roll=roll)


def georef(image_path, url):
    p = parse_url(url)
    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    ground_h = 2.0 * p["dist"] * math.tan(math.radians(p["fov"] / 2.0))
    px_per_m = h / ground_h

    origin = json.load(open(os.path.join(ROOT, "game", "data", "world_origin.json")))
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:26916", always_xy=True)
    E, N = to_utm.transform(p["lon"], p["lat"])
    cx = E - origin["origin_easting"]
    cz = -(N - origin["origin_northing"])

    # Image "up" points along HEADING; "right" is heading + 90 deg.
    up = math.radians(p["heading"])
    right = up + math.pi / 2.0
    # unit vectors in world (x = east, z = -north)
    rx, rz = math.sin(right), -math.cos(right)
    dx, dz = -math.sin(up), math.cos(up)      # image +y (down) = opposite of up

    meta = {
        "image": os.path.relpath(image_path, ROOT),
        "source": "google_earth_url",
        "centre_latlon": [p["lat"], p["lon"]],
        "centre_world": [round(cx, 2), round(cz, 2)],
        "heading_deg": p["heading"], "tilt_deg": p["tilt"],
        "px_per_m": round(px_per_m, 4),
        "size_px": [w, h],
        "covers_m": [round(w / px_per_m, 1), round(h / px_per_m, 1)],
        "right_vec": [rx, rz], "down_vec": [dx, dz],
        "note": ("world = centre_world + right_vec*((px-w/2)/px_per_m) "
                 "+ down_vec*((py-h/2)/px_per_m)"),
    }
    return img, meta


def px_to_world(meta, px, py):
    w, h = meta["size_px"]
    cx, cz = meta["centre_world"]
    rx, rz = meta["right_vec"]
    dx, dz = meta["down_vec"]
    a = (px - w / 2.0) / meta["px_per_m"]
    b = (py - h / 2.0) / meta["px_per_m"]
    return (cx + rx * a + dx * b, cz + rz * a + dz * b)


def world_to_px(meta, wx, wz):
    w, h = meta["size_px"]
    cx, cz = meta["centre_world"]
    rx, rz = meta["right_vec"]
    dx, dz = meta["down_vec"]
    ex, ez = wx - cx, wz - cz
    # invert the 2x2 [right down] basis
    det = rx * dz - rz * dx
    a = (ex * dz - ez * dx) / det
    b = (rx * ez - rz * ex) / det
    return (w / 2.0 + a * meta["px_per_m"], h / 2.0 + b * meta["px_per_m"])


def refine_offset(img, meta, search_m=140.0):
    """Solve the translation only, keeping the URL's scale and heading.

    Captures are usually CROPPED out of the Earth window, so the image centre is not the
    URL's view centre -- but scale and rotation still are. Correlating a road raster drawn
    in the tile's own frame against the photo's pavement mask recovers the missing shift,
    and it is a well-conditioned search because only 2 unknowns remain.
    """
    w, h = meta["size_px"]
    rgb = np.asarray(img, dtype=np.float32)
    mx, mn = rgb.max(-1), rgb.min(-1)
    val = mx / 255.0
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    g, r, b = rgb[..., 1], rgb[..., 0], rgb[..., 2]
    veg = (g > r * 1.04) & (g > b * 1.02)
    photo = ((val > 0.18) & (val < 0.82) & (sat < 0.38) & ~veg).astype(np.float32)
    photo = ndimage.gaussian_filter(photo, 2.0)

    pad = int(search_m * meta["px_per_m"])
    big = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
    d = ImageDraw.Draw(big)
    ways = json.load(open(os.path.join(ROOT, "game", "data", "roads.json")))["ways"]
    for way in ways:
        cls = (way.get("tags") or {}).get("highway")
        if cls in (None, "footway", "path", "steps", "cycleway"):
            continue
        width = max(2, int(2 * {"primary": 9, "secondary": 8, "tertiary": 7, "residential": 5.5,
                                "unclassified": 5.5, "service": 3.4}.get(cls, 5.0) * meta["px_per_m"]))
        vs = way["vertices"]
        for i in range(len(vs) - 1):
            a = world_to_px(meta, vs[i]["x"], vs[i]["z"])
            bb = world_to_px(meta, vs[i + 1]["x"], vs[i + 1]["z"])
            d.line([(a[0] + pad, a[1] + pad), (bb[0] + pad, bb[1] + pad)], fill=255, width=width)
    road = np.asarray(big, dtype=np.float32) / 255.0
    road = ndimage.gaussian_filter(road, 2.0)

    ph = photo - photo.mean()
    rd = road - road.mean()
    corr = signal.fftconvolve(rd, ph[::-1, ::-1], mode="valid")
    iy, ix = np.unravel_index(int(np.argmax(corr)), corr.shape)
    # (ix, iy) is where the photo's top-left sits in the padded road raster
    shift_px_x = ix - pad
    shift_px_y = iy - pad
    denom = math.sqrt((ph ** 2).sum() * (rd ** 2).sum()) or 1.0
    return shift_px_x, shift_px_y, float(corr.max() / denom)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--url", required=True)
    # Refinement is OPT-IN: on the first tile it made the fit worse (shifted 69.6 m,
    # ncc 0.108) because parking lots dominate the correlation. The URL alone is exact
    # when the screenshot is the full Earth viewport; only use --refine for cropped ones,
    # and always check the overlay afterwards.
    ap.add_argument("--refine", action="store_true")
    args = ap.parse_args()
    path = args.image if os.path.isabs(args.image) else os.path.join(ROOT, args.image)
    img, meta = georef(path, args.url)

    if args.refine:
        sx, sy, score = refine_offset(img, meta)
        rx, rz = meta["right_vec"]
        dx, dz = meta["down_vec"]
        a = sx / meta["px_per_m"]
        b = sy / meta["px_per_m"]
        meta["centre_world"] = [round(meta["centre_world"][0] - (rx * a + dx * b), 2),
                                round(meta["centre_world"][1] - (rz * a + dz * b), 2)]
        meta["refined"] = {"shift_px": [int(sx), int(sy)],
                           "shift_m": [round(a, 1), round(b, 1)],
                           "ncc": round(score, 4)}
        print("refined offset: %.1f, %.1f m (ncc %.3f)" % (a, b, score))

    out = os.path.splitext(path)[0] + "_georef.json"
    json.dump(meta, open(out, "w"), indent=1)
    print(json.dumps(meta, indent=1))

    ov = img.copy()
    d = ImageDraw.Draw(ov)
    w, h = meta["size_px"]
    ways = json.load(open(os.path.join(ROOT, "game", "data", "roads.json")))["ways"]
    for way in ways:
        vs = way["vertices"]
        for i in range(len(vs) - 1):
            a = world_to_px(meta, vs[i]["x"], vs[i]["z"])
            b = world_to_px(meta, vs[i + 1]["x"], vs[i + 1]["z"])
            if max(a[0], b[0]) < -40 or min(a[0], b[0]) > w + 40:
                continue
            if max(a[1], b[1]) < -40 or min(a[1], b[1]) > h + 40:
                continue
            d.line([a, b], fill=(255, 0, 255), width=2)
    for bl in json.load(open(os.path.join(ROOT, "game", "data", "buildings.json")))["buildings"]:
        pts = [world_to_px(meta, p["x"], p["z"]) for p in bl["footprint"]]
        if not any(-40 <= x <= w + 40 and -40 <= y <= h + 40 for x, y in pts):
            continue
        d.polygon([tuple(p) for p in pts], outline=(0, 255, 255))
    prev = os.path.splitext(path)[0] + "_fit.png"
    ov.save(prev)
    print("overlay:", prev)


if __name__ == "__main__":
    main()
