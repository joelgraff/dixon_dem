#!/usr/bin/env python3
"""Render hillshade + vector-overlay preview PNGs for visual QA.

Outputs to captures/pipeline/:
  hillshade_raw.png            play-area hillshade, raw+hydro-flattened heightmap
  hillshade_road_conformed.png play-area hillshade, road-conformed heightmap
  overlay_roads_buildings.png  hillshade + roads/buildings/water overlay
  hillshade_horizon.png        horizon heightmap hillshade
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
from common import CAPTURES_DIR, GAME_DATA

os.makedirs(CAPTURES_DIR, exist_ok=True)


def load_world_origin():
    with open(os.path.join(GAME_DATA, "world_origin.json")) as f:
        return json.load(f)


def load_r32(name, w, h):
    return np.fromfile(os.path.join(GAME_DATA, name), dtype="<f4").reshape(h, w)


def hillshade(elev, spacing, az=315.0, alt=45.0, z_exag=1.5):
    gy, gx = np.gradient(elev * z_exag, spacing)
    slope = np.pi / 2 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az_r = np.deg2rad(360.0 - az + 90.0)
    alt_r = np.deg2rad(alt)
    shaded = np.sin(alt_r) * np.sin(slope) + np.cos(alt_r) * np.cos(slope) * np.cos(az_r - aspect)
    shaded = np.clip(shaded, 0, 1)
    return (shaded * 255).astype(np.uint8)


def to_img(gray):
    return Image.fromarray(gray, mode="L").convert("RGB")


def world_to_px(x, z, w, h, size_m, spacing_m):
    # x,z already in Godot local coords (x east, z = -north), origin at play-area SW corner is (0, -size_m)
    px = x / spacing_m
    py = (size_m + z) / spacing_m  # z is negative going north; flip to image row (row0=north)
    return px, py


def main():
    wo = load_world_origin()
    play = wo["heightmaps"]["play"]
    pw, ph, ps = play["width"], play["height"], play["spacing_m"]

    raw = load_r32(play["file"], pw, ph)
    road = load_r32(play["road_conformed_file"], pw, ph)

    hs_raw = hillshade(raw, ps)
    hs_road = hillshade(road, ps)
    to_img(hs_raw).save(os.path.join(CAPTURES_DIR, "hillshade_raw.png"))
    to_img(hs_road).save(os.path.join(CAPTURES_DIR, "hillshade_road_conformed.png"))

    # overlay
    img = to_img(hs_road).convert("RGB")
    draw = ImageDraw.Draw(img)
    size_m = wo["size_m"]

    def xz_to_xy(x, z):
        return (x / ps, (size_m + z) / ps)

    # water
    try:
        water = json.load(open(os.path.join(GAME_DATA, "water.json")))
        for r in water["reaches"]:
            pts = [xz_to_xy(p["x"], p["z"]) for p in r["polygon"]]
            draw.polygon(pts, fill=(60, 110, 170))
    except FileNotFoundError:
        pass

    # buildings
    try:
        buildings = json.load(open(os.path.join(GAME_DATA, "buildings.json")))
        for b in buildings["buildings"]:
            pts = [xz_to_xy(p["x"], p["z"]) for p in b["footprint"]]
            color = (255, 140, 0) if "landmark_id" in b else (190, 90, 60)
            draw.polygon(pts, outline=color, fill=None)
    except FileNotFoundError:
        pass

    # roads
    try:
        roads = json.load(open(os.path.join(GAME_DATA, "roads.json")))
        for w in roads["ways"]:
            pts = [xz_to_xy(v["x"], v["z"]) for v in w["vertices"]]
            color = (255, 0, 0) if w["tags"]["bridge"] else (255, 255, 0)
            width = 3 if w["tags"]["highway"] in ("primary", "trunk", "motorway") else 1
            draw.line(pts, fill=color, width=width)
    except FileNotFoundError:
        pass

    # dam line(s)
    try:
        water = json.load(open(os.path.join(GAME_DATA, "water.json")))
        for d in water["dams"]:
            pts = [xz_to_xy(v["x"], v["z"]) for v in d["vertices"]]
            draw.line(pts, fill=(0, 200, 0), width=4)
    except FileNotFoundError:
        pass

    # landmark markers
    try:
        pois = json.load(open(os.path.join(GAME_DATA, "pois.json")))
        for p in pois["points"]:
            if "landmark_id" in p:
                x, y = xz_to_xy(p["x"], p["z"])
                draw.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(0, 255, 255), width=2)
    except FileNotFoundError:
        pass

    img.save(os.path.join(CAPTURES_DIR, "overlay_roads_buildings.png"))

    horizon = wo["heightmaps"]["horizon"]
    hw, hh, hs = horizon["width"], horizon["height"], horizon["spacing_m"]
    harr = load_r32(horizon["file"], hw, hh)
    to_img(hillshade(harr, hs)).save(os.path.join(CAPTURES_DIR, "hillshade_horizon.png"))

    print("Wrote preview PNGs to", CAPTURES_DIR)


if __name__ == "__main__":
    main()
