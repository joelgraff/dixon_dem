#!/usr/bin/env python3
"""Audits EVERY baked building triangle for outward orientation.

User ticket 20260920_235929: "lots of buildings have walls with flipped normals".
Spot checks are not enough for that -- this walks the whole baked chunk set and reports,
per material and per archetype, how many faces are wound/shaded inward.

Method: a face is compared against the footprint it belongs to (nearest footprint centroid
from the full building set). For a VERTICAL face the outward direction is away from that
centroid in plan; for an UPWARD face it is +Y. Two things are checked independently:
  * winding  -- the cross product of the emitted index order (this is what Godot culls on;
                front faces are CLOCKWISE seen from the front, so the right-hand-rule normal
                of a front-facing triangle points AWAY from the viewer, i.e. into the solid)
  * normal   -- the stored shading normal (this is what lighting uses)
Both must agree with outward, or the wall renders invisible or black.

Run: cd pipeline/buildings && ../../.venv/bin/python audit_normals.py [--limit N]
"""
import argparse
import glob
import json
import math
import os
from collections import defaultdict

import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
BUILD_DIR = os.path.join(ROOT, "game", "buildings", "_build")

VERTICAL_MAX_NY = 0.55     # |ny| below this counts as a wall
UPWARD_MIN_NY = 0.75       # above this counts as a roof/cap


def footprint_polys():
    """Footprint polygons, for a point-in-polygon outward test.

    "Away from the centroid" is NOT a valid ground truth: on an L-plan, a U-plan, a
    courtyard or an offset wing, a genuinely outward-facing wall can point back toward the
    building centroid. Testing whether a small step along the normal leaves the polygon is
    correct for any shape, which matters because the centroid version and the generator
    disagreeing is what produced an unreliable 18-19% either way.
    """
    polys = []
    for name in ("buildings.json", "buildings_ms.json", "buildings_curated.json"):
        p = os.path.join(ROOT, "game", "data", name)
        if not os.path.exists(p):
            continue
        data = json.load(open(p))
        for b in (data.get("buildings") or []):
            fp = b.get("footprint") or []
            if len(fp) >= 3:
                try:
                    poly = Polygon([(q["x"], q["z"]) for q in fp])
                    if poly.is_valid and poly.area > 1.0:
                        polys.append(poly)
                except Exception:
                    pass
    return polys, STRtree(polys)


def footprint_index():
    pts, meta = [], []
    for name in ("buildings.json", "buildings_ms.json", "buildings_curated.json"):
        p = os.path.join(ROOT, "game", "data", name)
        if not os.path.exists(p):
            continue
        data = json.load(open(p))
        recs = data.get("buildings", data if isinstance(data, list) else [])
        for b in recs:
            fp = b.get("footprint") or []
            if len(fp) < 3:
                continue
            cx = sum(q["x"] for q in fp) / len(fp)
            cz = sum(q["z"] for q in fp) / len(fp)
            pts.append((cx, cz))
            meta.append(b.get("landmark_id") or b.get("source") or "osm")
    return cKDTree(np.array(pts)), meta


def chunk_origin(path):
    """Chunk meshes are stored CHUNK-LOCAL; the manifest gives each chunk's world origin.

    The first version of this audit compared chunk-local vertices against world footprint
    centroids and reported a meaningless 49% failure rate. Always resolve to world first.
    """
    manifest = json.load(open(os.path.join(BUILD_DIR, "manifest.json")))
    size = manifest.get("chunk_size", 200.0)
    by_file = {}
    for ci in manifest["chunks"]:
        by_file[os.path.basename(ci["file"])] = (ci["origin_x"], ci["origin_z"])
    return by_file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    polys, ptree = footprint_polys()
    origins = chunk_origin(BUILD_DIR)
    files = sorted(glob.glob(os.path.join(BUILD_DIR, "*.json")))
    if args.limit:
        files = files[:args.limit]

    stats = defaultdict(lambda: {"wall": 0, "wall_bad_wind": 0, "wall_bad_norm": 0,
                                 "up": 0, "up_bad_wind": 0, "up_bad_norm": 0})
    worst = []

    for f in files:
        if os.path.basename(f) == "manifest.json":
            continue
        ox, oz = origins.get(os.path.basename(f), (0.0, 0.0))
        d = json.load(open(f))
        for group in ("near",):
            for mat, g in (d.get(group) or {}).items():
                V = g.get("verts") or []
                I = g.get("indices") or []
                if not V or not I:
                    continue
                arr = np.array([v[:6] for v in V], dtype=float)   # x,y,z,nx,ny,nz
                arr[:, 0] += ox                                   # chunk-local -> world
                arr[:, 2] += oz
                s = stats[mat]
                bad_here = 0
                for k in range(0, len(I) - 2, 3):
                    a, b, c = arr[I[k]], arr[I[k + 1]], arr[I[k + 2]]
                    u = b[:3] - a[:3]
                    v = c[:3] - a[:3]
                    n = np.cross(u, v)
                    ln = np.linalg.norm(n)
                    if ln < 1e-9:
                        continue
                    n = n / ln
                    fc = (a[:3] + b[:3] + c[:3]) / 3.0
                    shading = (a[3:6] + b[3:6] + c[3:6]) / 3.0
                    sl = np.linalg.norm(shading)
                    shading = shading / sl if sl > 1e-9 else np.array([0.0, 1.0, 0.0])

                    if abs(n[1]) <= VERTICAL_MAX_NY:
                        # ground truth: stepping along the shading normal must LEAVE the
                        # footprint, and stepping against it must stay inside
                        sh2 = np.array([shading[0], shading[2]])
                        shl = np.linalg.norm(sh2)
                        if shl < 1e-6:
                            continue
                        sh2 = sh2 / shl
                        out_pt = Point(fc[0] + sh2[0] * 0.45, fc[2] + sh2[1] * 0.45)
                        in_pt = Point(fc[0] - sh2[0] * 0.45, fc[2] - sh2[1] * 0.45)
                        owner = None
                        for qi in ptree.query(in_pt):
                            cand = polys[int(qi)]
                            if cand.contains(in_pt):
                                owner = cand
                                break
                        if owner is None or owner.contains(out_pt):
                            continue          # not a footprint wall (trim, sub-mass, insets)
                        outward = np.array([shading[0], 0.0, shading[2]])
                        ol = np.linalg.norm(outward)
                        if ol < 1e-6:
                            continue
                        outward /= ol
                        s["wall"] += 1
                        # front-facing (clockwise) => right-hand normal points INTO the solid
                        if np.dot(n, outward) > 0.0:
                            s["wall_bad_wind"] += 1
                            bad_here += 1
                        if np.dot(shading, outward) < 0.0:
                            s["wall_bad_norm"] += 1
                    elif n[1] >= UPWARD_MIN_NY or n[1] <= -UPWARD_MIN_NY:
                        s["up"] += 1
                        up = np.array([0.0, 1.0, 0.0])
                        if np.dot(n, up) > 0.0:
                            s["up_bad_wind"] += 1
                        if np.dot(shading, up) < 0.0:
                            s["up_bad_norm"] += 1
                if bad_here:
                    worst.append((bad_here, os.path.basename(f), mat))

    print(f"{'material':<24} {'walls':>8} {'wind bad':>10} {'norm bad':>10} "
          f"{'roofs':>8} {'wind bad':>10} {'norm bad':>10}")
    tot = defaultdict(int)
    for mat, s in sorted(stats.items(), key=lambda kv: -kv[1]["wall_bad_wind"]):
        for k, v in s.items():
            tot[k] += v
        if s["wall"] + s["up"] == 0:
            continue
        print(f"{mat:<24} {s['wall']:>8} {s['wall_bad_wind']:>9} "
              f"{100.0*s['wall_bad_wind']/max(s['wall'],1):>4.0f}% {s['wall_bad_norm']:>9} "
              f"{s['up']:>8} {s['up_bad_wind']:>9} {s['up_bad_norm']:>9}")
    print("-" * 86)
    print(f"{'TOTAL':<24} {tot['wall']:>8} {tot['wall_bad_wind']:>9} "
          f"{100.0*tot['wall_bad_wind']/max(tot['wall'],1):>4.0f}% {tot['wall_bad_norm']:>9} "
          f"{tot['up']:>8} {tot['up_bad_wind']:>9} {tot['up_bad_norm']:>9}")
    worst.sort(reverse=True)
    if worst[:8]:
        print("\nworst chunks:")
        for n, f, mat in worst[:8]:
            print(f"  {n:>6} bad faces   {f}   {mat}")


if __name__ == "__main__":
    main()
