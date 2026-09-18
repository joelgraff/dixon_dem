"""Shared helpers for the vegetation workstream's placement pipeline.

Self-contained (does not import pipeline/roads/ — a different workstream's
owned folder); duplicates the small bits of geometry it needs (heightmap
sampling, in the same style as pipeline/roads/common_roads.py) to stay
decoupled. Coordinates are Godot-local meters (x east, z south-negative),
matching every other game/data/*.json file.
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common as pc  # pipeline/common.py

EPS = 1e-6


class Heightmap:
    """Bilinear sampler over the road-conformed play heightmap (r32)."""

    def __init__(self, path=None):
        wo = pc.load_world_origin()
        hm = wo["heightmaps"]["play"]
        if path is None:
            path = os.path.join(pc.GAME_DATA, hm["road_conformed_file"])
        self.width = hm["width"]
        self.height = hm["height"]
        self.spacing = hm["spacing_m"]
        self.x0 = hm["origin_easting"] - pc.ORIGIN_EASTING
        self.z0 = -(hm["origin_northing_top"] - pc.ORIGIN_NORTHING)
        arr = np.fromfile(path, dtype="<f4")
        assert arr.size == self.width * self.height, (
            f"heightmap size mismatch: {arr.size} vs {self.width * self.height}"
        )
        self.grid = arr.reshape((self.height, self.width))

    def sample(self, x, z):
        col = (x - self.x0) / self.spacing
        row = (z - self.z0) / self.spacing
        col = min(max(col, 0.0), self.width - 1.001)
        row = min(max(row, 0.0), self.height - 1.001)
        c0 = int(math.floor(col))
        r0 = int(math.floor(row))
        c1 = min(c0 + 1, self.width - 1)
        r1 = min(r0 + 1, self.height - 1)
        fc = col - c0
        fr = row - r0
        g = self.grid
        h00, h10 = g[r0, c0], g[r0, c1]
        h01, h11 = g[r1, c0], g[r1, c1]
        h0 = h00 + (h10 - h00) * fc
        h1 = h01 + (h11 - h01) * fc
        return float(h0 + (h1 - h0) * fr)


def load_json(name):
    with open(os.path.join(pc.GAME_DATA, name)) as f:
        return __import__("json").load(f)


class HashGrid:
    """Uniform spatial hash for fast 'nearest existing point' rejection
    during Poisson-ish scattering. Cell size should be >= the largest
    min-spacing you'll query with."""

    def __init__(self, cell_size):
        self.cell = cell_size
        self.buckets = {}

    def _key(self, x, z):
        return (int(math.floor(x / self.cell)), int(math.floor(z / self.cell)))

    def is_far_enough(self, x, z, min_dist):
        cx, cz = self._key(x, z)
        md2 = min_dist * min_dist
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for (px, pz) in self.buckets.get((cx + dx, cz + dz), ()):
                    ddx = px - x
                    ddz = pz - z
                    if ddx * ddx + ddz * ddz < md2:
                        return False
        return True

    def insert(self, x, z):
        k = self._key(x, z)
        self.buckets.setdefault(k, []).append((x, z))


def seeded_rng(*parts):
    """Deterministic per-feature RNG seeded from arbitrary hashables."""
    import random
    h = 1469598103934665603
    for p in parts:
        for b in str(p).encode("utf-8"):
            h = ((h ^ b) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return random.Random(h)


def polyline_length(pts):
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
               for i in range(len(pts) - 1))


def walk_polyline(pts, spacing, jitter_frac, rng):
    """Yields (x, z, tangent_x, tangent_z, dist_from_start) at ~`spacing`
    intervals along a 2D polyline, each nudged by up to jitter_frac*spacing."""
    total = polyline_length(pts)
    if total < 1.0:
        return
    d = spacing * (0.4 + rng.random() * 0.3)  # offset first sample so rows don't all start at 0
    while d < total:
        # find segment containing distance d
        acc = 0.0
        for i in range(len(pts) - 1):
            x0, z0 = pts[i]
            x1, z1 = pts[i + 1]
            seg = math.hypot(x1 - x0, z1 - z0)
            if seg < EPS:
                continue
            if acc + seg >= d:
                t = (d - acc) / seg
                x = x0 + (x1 - x0) * t
                z = z0 + (z1 - z0) * t
                tx = (x1 - x0) / seg
                tz = (z1 - z0) / seg
                yield x, z, tx, tz, d
                break
            acc += seg
        jitter = spacing * jitter_frac * (rng.random() * 2 - 1)
        d += spacing + jitter
