"""Residential infill: OSM only mapped 707 footprints across the 2.7 km^2
play area, so most residential blocks have no buildings at all. This module
places plausible houses (+ occasional detached rear garages) along mapped
residential streets, on ground not already covered by a real footprint,
water, rails, parks/non-residential landuse, or downtown. Deterministic
(seeded by rounded world position).

Output records have the same shape build_building_plan.py uses for real
OSM footprints: {"id", "footprint": [{"x","z"}...], "ground_y_min",
"height_m", "tags": {...}} so classify()+archetypes.py need no special-casing.
"""
import math

from common_buildings import (
    rng_for, dist_point_to_segment, nearest_point_on_segment, rect_from_center,
)
from classify import in_downtown, in_aerial

RESIDENTIAL_HIGHWAYS = {"residential", "unclassified", "tertiary"}
LOT_SPACING_M = 17.0
SETBACK_MIN, SETBACK_MAX = 6.0, 9.0
MIN_BUILDING_CLEARANCE = 3.0
MIN_INFILL_SPACING = 13.0
MAX_INFILL_HOUSES = 900


def _road_candidates(roads_data):
    """(ax,az,bx,bz,width_m) segments for residential-ish, non-bridge ways."""
    segs = []
    for way in roads_data["ways"]:
        tags = way.get("tags", {})
        if tags.get("highway") not in RESIDENTIAL_HIGHWAYS:
            continue
        if tags.get("bridge"):
            continue
        width = tags.get("width_m") or 6.0
        verts = way["vertices"]
        for i in range(len(verts) - 1):
            a, b = verts[i], verts[i + 1]
            segs.append((a["x"], a["z"], b["x"], b["z"], width))
    return segs


class Sampler:
    """Bilinear height sampler for the road-conformed play heightmap,
    mirroring game/terrain/terrain_height.gd's Grid.sample()."""

    def __init__(self, origin_json, r32_path):
        import numpy as np
        play = origin_json["heightmaps"]["play"]
        self.width = play["width"]
        self.height = play["height"]
        self.spacing = play["spacing_m"]
        self.origin_x = play["origin_easting"] - origin_json["origin_easting"]
        self.origin_z = -(play["origin_northing_top"] - origin_json["origin_northing"])
        self.heights = np.fromfile(r32_path, dtype="<f4").reshape(self.height, self.width)

    def sample(self, x, z):
        col = min(max((x - self.origin_x) / self.spacing, 0.0), self.width - 1)
        row = min(max((z - self.origin_z) / self.spacing, 0.0), self.height - 1)
        c0, r0 = int(col), int(row)
        c1, r1 = min(c0 + 1, self.width - 1), min(r0 + 1, self.height - 1)
        fx, fz = col - c0, row - r0
        h00 = self.heights[r0, c0]
        h10 = self.heights[r0, c1]
        h01 = self.heights[r1, c0]
        h11 = self.heights[r1, c1]
        return float((h00 * (1 - fx) + h10 * fx) * (1 - fz) + (h01 * (1 - fx) + h11 * fx) * fz)


def generate_infill(roads_data, exclude_index, height_sampler, max_houses=MAX_INFILL_HOUSES):
    records = []
    placed_centers = []  # (x,z) of accepted infill lots (front houses only)
    segs = _road_candidates(roads_data)

    def too_close_to_placed(x, z, min_d):
        for (px, pz) in placed_centers:
            if (px - x) ** 2 + (pz - z) ** 2 < min_d * min_d:
                return True
        return False

    next_id = 900000000  # well above real OSM ids

    for (ax, az, bx, bz, width) in segs:
        length = math.hypot(bx - ax, bz - az)
        if length < 3.0:
            continue
        n_steps = max(1, int(length // LOT_SPACING_M))
        dx, dz = (bx - ax) / length, (bz - az) / length
        nx, nz = dz, -dx  # perpendicular
        for i in range(n_steps):
            if len(records) >= max_houses:
                break
            t = (i + 0.5) / n_steps * length
            rx, rz = ax + dx * t, az + dz * t
            if in_downtown(rx, rz) or in_aerial(rx, rz):
                # Inside the aerial reference area (screenshots/dixon_downtown_aerial.png) the buildings
                # come from OSM, which matches the aerial to ~1-2 m, plus buildings_curated.json.
                # Random infill there put houses on Galena Ave, in parking lots, etc. (tried and
                # rejected 2026-09-20), so it is off inside the aerial.
                continue
            rng = rng_for("infill", round(rx * 4), round(rz * 4))
            for side in (1, -1):
                if len(records) >= max_houses:
                    break
                setback = width / 2.0 + rng.uniform(SETBACK_MIN, SETBACK_MAX)
                cx = rx + nx * side * setback
                cz = rz + nz * side * setback
                if in_downtown(cx, cz) or in_aerial(cx, cz):
                    continue
                if exclude_index.contains_or_near(cx, cz, margin=MIN_BUILDING_CLEARANCE):
                    continue
                if too_close_to_placed(cx, cz, MIN_INFILL_SPACING):
                    continue
                # keep a modest distance from the road centerline itself too
                if dist_point_to_segment(cx, cz, ax, az, bx, bz) < width / 2.0 + 3.0:
                    continue
                lot_w = rng.uniform(9.0, 13.0)
                lot_d = rng.uniform(10.0, 16.0)
                yaw = math.atan2(dz, dx) + (math.pi / 2.0 if side > 0 else -math.pi / 2.0)
                # orient rectangle so its short axis faces the street: rotate 90
                corners = rect_from_center(cx, cz, lot_d, lot_w, yaw + math.pi / 2.0)
                ground_y = height_sampler.sample(cx, cz)
                records.append({
                    "id": next_id,
                    "footprint": [{"x": p[0], "z": p[1]} for p in corners] + [{"x": corners[0][0], "z": corners[0][1]}],
                    "ground_y_min": round(ground_y, 2),
                    "ground_y_max": round(ground_y, 2),
                    "height_m": round(rng.uniform(5.5, 8.5), 1),
                    "tags": {"name": None, "building": "house", "amenity": None},
                    "infill": True,
                })
                next_id += 1
                placed_centers.append((cx, cz))
                # occasional detached rear garage
                if rng.random() < 0.22 and len(records) < max_houses:
                    gset = setback + lot_d * 0.5 + rng.uniform(3.0, 6.0)
                    gx = rx + nx * side * gset
                    gz = rz + nz * side * gset
                    if not exclude_index.contains_or_near(gx, gz, margin=MIN_BUILDING_CLEARANCE) and \
                       not too_close_to_placed(gx, gz, 8.0):
                        gw, gd = rng.uniform(4.0, 6.0), rng.uniform(5.0, 7.0)
                        gcorners = rect_from_center(gx, gz, gd, gw, yaw + math.pi / 2.0)
                        ggy = height_sampler.sample(gx, gz)
                        records.append({
                            "id": next_id,
                            "footprint": [{"x": p[0], "z": p[1]} for p in gcorners] + [{"x": gcorners[0][0], "z": gcorners[0][1]}],
                            "ground_y_min": round(ggy, 2),
                            "ground_y_max": round(ggy, 2),
                            "height_m": 3.2,
                            "tags": {"name": None, "building": "garage", "amenity": None},
                            "infill": True,
                        })
                        next_id += 1
                        placed_centers.append((gx, gz))
        if len(records) >= max_houses:
            break
    return records
