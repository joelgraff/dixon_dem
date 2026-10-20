"""Roadway profile metrics: how far the delivered road surface is from a designed one.

Measures the road-conformed heightmap (`heightmap_play_1m_road_conformed.r32`) along every
drivable, non-bridge way in `game/data/roads.json`, against the limits in
`design_standards.json` (docs/roadway_control_plan.md, phase 0). What it measures is the surface
every consumer builds on, so the numbers stay comparable when the way that surface is made changes.

- grade: centreline grade over 10 m chords, every 2 m.
- grade change: difference between the chords 10 m behind and 10 m ahead of a station; a
  vertical curve with that change in 10 m has K = 10 / change(%) m per %.
- cross slope: centreline minus the surface 0.3 m inside each pavement edge, every 10 m, as a
  slope toward the edge (a normal crown is +2% both sides).
- junction step: at each junction node, every incident leg's centreline profile from 2 to 10 m
  out is fitted with a line and extended to the node; the spread of those heights and the node's
  own is the step a driver feels crossing the junction.
- breaklines: runs where |grade| > 25% or the grade changes by more than 15% in 10 m, each with
  the ground's own grade there and the distance to the nearest bridge end, to say why.

Since phase 3a every drivable way on a route is measured along its design line (the route
alignment the road mesh and the conform are built on, templates.design_roads) at its template
width; `--osm` measures along the OSM lines at their tag widths instead, as before.

Run: ../../.venv/bin/python road_metrics.py [--update-baseline] [--osm] [--surface heightmap.r32]
Writes game/roads/_build/road_metrics.json (the full report, breakline list included).
`--update-baseline` rewrites road_metrics_baseline.json, the ratchet test_road_metrics.py holds
the build to; do that only when a change makes the numbers better.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common_roads import Heightmap  # noqa: E402
import common as pc  # noqa: E402  (pipeline/common.py, on the path via common_roads)

STANDARDS_PATH = os.path.join(HERE, "design_standards.json")
BASELINE_PATH = os.path.join(HERE, "road_metrics_baseline.json")
REPORT_PATH = os.path.join(pc.ROOT, "game", "roads", "_build", "road_metrics.json")

SAMPLE_M = 2.0              # profile sampling along a centreline
CHORD_M = 10.0              # grade chord, and the run the grade change is measured over
CROSS_STATION_M = 10.0      # cross-slope stations
CROSS_EDGE_INSET_M = 0.3    # cross slope is read this far inside the pavement edge
LEG_FIT_M = (2.0, 10.0)     # junction step: the stretch of each leg fitted and extended to the node
BREAK_GRADE = 0.25
BREAK_CHANGE = 0.15
ADVERSE_CROSS_SLOPE = -0.005   # a side sloping toward the centreline by more than this ponds water
FT = 0.3048
PERCENTILES = (50, 90, 99, 100)


def load_standards(path=STANDARDS_PATH):
    with open(path) as handle:
        data = json.load(handle)
    if data.get("format") != "dixon-design-standards":
        raise ValueError(f"{path}: not a dixon-design-standards file")
    return data


def class_of(highway, standards):
    for name, spec in standards["classes"].items():
        if highway in spec["osm_highway"]:
            return name
    return None


class Surface:
    """Vectorised bilinear sampler over a play heightmap; NaN outside it."""

    def __init__(self, path=None):
        hm = Heightmap(path)
        self.grid = hm.grid.astype(np.float64)
        self.x0, self.z0, self.spacing = hm.x0, hm.z0, hm.spacing
        self.h, self.w = self.grid.shape

    @classmethod
    def from_grid(cls, grid, transform):
        """A sampler over an in-memory play grid (game Y), `transform` its UTM affine (row 0 north)."""
        self = cls.__new__(cls)
        self.grid = np.asarray(grid, dtype=np.float64)
        self.spacing = abs(transform.a)
        self.x0 = transform.c - pc.ORIGIN_EASTING
        self.z0 = -(transform.f - pc.ORIGIN_NORTHING)
        self.h, self.w = self.grid.shape
        return self

    def sample(self, xs, zs):
        col = (np.asarray(xs, dtype=np.float64) - self.x0) / self.spacing
        row = (np.asarray(zs, dtype=np.float64) - self.z0) / self.spacing
        inside = (col >= 0) & (row >= 0) & (col <= self.w - 1) & (row <= self.h - 1)
        c = np.clip(col, 0, self.w - 1.001)
        r = np.clip(row, 0, self.h - 1.001)
        c0, r0 = np.floor(c).astype(int), np.floor(r).astype(int)
        fc, fr = c - c0, r - r0
        g = self.grid
        top = g[r0, c0] * (1 - fc) + g[r0, c0 + 1] * fc
        bot = g[r0 + 1, c0] * (1 - fc) + g[r0 + 1, c0 + 1] * fc
        out = top * (1 - fr) + bot * fr
        return np.where(inside, out, np.nan)


def stations(points):
    p = np.asarray(points, dtype=np.float64)
    return np.r_[0.0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]


def along(points, s_vertices, ds):
    """Positions and unit tangents at stations `ds` of a polyline."""
    p = np.asarray(points, dtype=np.float64)
    xs = np.interp(ds, s_vertices, p[:, 0])
    zs = np.interp(ds, s_vertices, p[:, 1])
    seg = np.clip(np.searchsorted(s_vertices, ds, side="right") - 1, 0, len(p) - 2)
    d = p[seg + 1] - p[seg]
    d /= np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-9)[:, None]
    return xs, zs, d


def grade_profile(points, surface, sample=SAMPLE_M, chord=CHORD_M):
    """(stations, positions, grade, grade change) along a centreline, chord-based.

    grade[i] is the slope of the chord centred on station i, from half a chord in from each end;
    change[i] is the grade of the chord ahead minus the one behind, NaN within a chord of an end."""
    s_v = stations(points)
    length = s_v[-1]
    half = chord / 2
    if length < chord + sample:
        return None
    ds = np.arange(half, length - half + 1e-9, sample)
    xs, zs, _ = along(points, s_v, ds)
    def y_at(offset):
        x, z, _ = along(points, s_v, ds + offset)
        return surface.sample(x, z)
    grade = (y_at(half) - y_at(-half)) / chord
    ahead = (y_at(chord) - y_at(0.0)) / chord
    behind = (y_at(0.0) - y_at(-chord)) / chord
    full = (ds >= chord) & (ds <= length - chord)
    return ds, xs, zs, grade, np.where(full, ahead - behind, np.nan)


def cross_slopes(points, half_width, surface, step=CROSS_STATION_M, inset=CROSS_EDGE_INSET_M):
    """Slopes from the centreline toward each pavement edge (positive drains outward), every `step`.
    `half_width` is one width, or one per point (a design way's template `hw`, which narrows and
    tapers along the way), interpolated to the stations."""
    s_v = stations(points)
    if s_v[-1] < 2 * step:
        return np.empty(0)
    ds = np.arange(step, s_v[-1] - step + 1e-9, step)
    offset = (np.interp(ds, s_v, half_width) if np.ndim(half_width) else np.full(len(ds), float(half_width))) - inset
    keep = offset >= 0.5
    if not keep.any():
        return np.empty(0)
    ds, offset = ds[keep], offset[keep]
    xs, zs, t = along(points, s_v, ds)
    nx, nz = -t[:, 1], t[:, 0]
    yc = surface.sample(xs, zs)
    out = []
    for side in (1.0, -1.0):
        ye = surface.sample(xs + side * nx * offset, zs + side * nz * offset)
        out.append((yc - ye) / offset)
    return np.concatenate(out)


def leg_paths(way_vertices, node_id):
    """The polylines leaving `node_id` along a way: one from an end node, two from an interior one."""
    ids = [v.get("node_id") for v in way_vertices]
    pts = [(v["x"], v["z"]) for v in way_vertices]
    out = []
    for i, nid in enumerate(ids):
        if nid != node_id:
            continue
        if i < len(pts) - 1:
            out.append(pts[i:])
        if i > 0:
            out.append(pts[i::-1])
    return out


def junction_step(node, legs, surface, fit=LEG_FIT_M):
    """Spread of the node's height and every leg's profile extended back to it (m), or None."""
    # the legs start at the node as the ways draw it (on a design way, the junction's point on
    # the route alignments, which can sit a little off the OSM node)
    x, z = legs[0][0] if legs else (node["x"], node["z"])
    heights = [float(surface.sample([x], [z])[0])]
    d = np.arange(fit[0], fit[1] + 1e-9, 1.0)
    for leg in legs:
        s_v = stations(leg)
        if s_v[-1] < fit[1]:
            continue
        xs, zs, _ = along(leg, s_v, d)
        ys = surface.sample(xs, zs)
        if np.isnan(ys).any():
            continue
        slope, intercept = np.polyfit(d, ys, 1)
        heights.append(float(intercept))
    if len(heights) < 3 or math.isnan(heights[0]):
        return None
    return max(heights) - min(heights)


def legacy_profile_disagreement(ways, ground, window=15.0, sample=2.0):
    """How much today's road_conform inputs disagree at shared nodes (diagnostic only).

    build_heightmap.road_conform averages the ground over a 15 m window along each way on its own;
    where ways share a node, those averages differ, and the nearest sample wins in the raster.
    This mirrors that on roads.json's ways. It describes the current algorithm, not the delivered
    surface, so it is reported but not held to a baseline."""
    vals = {}
    for w in ways:
        pts = [(v["x"], v["z"]) for v in w["vertices"]]
        s_v = stations(pts)
        if s_v[-1] < 4.0:
            continue
        ds = np.linspace(0.0, s_v[-1], max(2, int(s_v[-1] / sample)))
        xs, zs, _ = along(pts, s_v, ds)
        e = ground.sample(xs, zs)
        lo = np.searchsorted(ds, ds - window / 2, side="left")
        hi = np.searchsorted(ds, ds + window / 2, side="right")
        valid = ~np.isnan(e)
        if not valid.all():
            continue        # off the heightmap: road_conform never sees it
        csum = np.r_[0.0, np.cumsum(e)]
        sm = (csum[hi] - csum[lo]) / np.maximum(hi - lo, 1)
        for v, s in zip(w["vertices"], s_v):
            if v.get("node_id") is not None:
                vals.setdefault(v["node_id"], []).append(float(np.interp(s, ds, sm)))
    return np.array([max(v) - min(v) for v in vals.values() if len(v) > 1])


def length_beyond_heightmap(ways, surface, bounds, sample=SAMPLE_M):
    """Metres of centreline the road plan builds (inside `bounds`) where `surface` has no data.

    The road plan keeps ways out to build_road_plan.VALID_BOUNDS, 400 m past the play heightmap;
    its sampler clamps to the edge row there, so those roads take the edge's heights."""
    x0, z0, x1, z1 = bounds
    total = 0.0
    for w in ways:
        pts = [(v["x"], v["z"]) for v in w["vertices"]]
        s_v = stations(pts)
        if s_v[-1] < sample:
            continue
        xs, zs, _ = along(pts, s_v, np.arange(0.0, s_v[-1], sample))
        built = (xs >= x0) & (xs <= x1) & (zs >= z0) & (zs <= z1)
        total += sample * int((built & np.isnan(surface.sample(xs, zs))).sum())
    return total


def bridge_ends():
    """(x, z) of every bridge end: bridges.json ways and Bridge Composer designs."""
    out = []
    with open(os.path.join(pc.GAME_DATA, "bridges.json")) as handle:
        for b in json.load(handle)["bridges"]:
            for v in (b["vertices"][0], b["vertices"][-1]):
                out.append((v["x"], v["z"]))
    folder = os.path.join(pc.GAME_DATA, "bridges_composed")
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.endswith(".json"):
                with open(os.path.join(folder, name)) as handle:
                    line = json.load(handle).get("centerline") or []
                out.extend(tuple(p) for p in (line[:1] + line[-1:]))
    return np.array(out) if out else np.empty((0, 2))


def runs(mask):
    """[(start, end_exclusive), ...] of the True runs in a boolean array."""
    m = np.r_[False, mask, False].astype(int)
    edges = np.flatnonzero(np.diff(m))
    return list(zip(edges[::2], edges[1::2]))


def pct(values):
    v = np.asarray(values, dtype=np.float64)
    v = v[~np.isnan(v)]
    if v.size == 0:
        return {f"p{p}": None for p in PERCENTILES}
    return {("max" if p == 100 else f"p{p}"): round(float(np.percentile(v, p)), 4) for p in PERCENTILES}


def measure(standards=None, surface=None, ground=None, roads=None, ends=None, design=True):
    standards = standards or load_standards()
    surface = surface or Surface()
    if ground is None:
        ground = Surface(os.path.join(pc.GAME_DATA, "heightmap_play_1m.r32"))
    if roads is None:
        with open(os.path.join(pc.GAME_DATA, "roads.json")) as handle:
            roads = json.load(handle)
    ends = bridge_ends() if ends is None else ends
    osm_ways = roads["ways"]
    if design:
        # the surface is designed along the route alignments at template widths
        # (templates.design_roads), so it is measured there, not along the OSM lines
        import templates
        roads, _ = templates.design_roads(roads)

    ways = [w for w in roads["ways"]
            if class_of(w["tags"]["highway"], standards) and not w["tags"].get("bridge")]
    by_id = {w["id"]: w for w in ways}

    grades, changes, crosses = [], [], []
    over_grade_m = 0.0
    low_k_m = 0.0
    breaks = []
    for w in ways:
        cls = standards["classes"][class_of(w["tags"]["highway"], standards)]
        pts = [(v["x"], v["z"]) for v in w["vertices"]]
        prof = grade_profile(pts, surface)
        if prof is not None:
            ds, xs, zs, g, a = prof
            ok_g, ok_a = ~np.isnan(g), ~np.isnan(a)
            grades.append(np.abs(g[ok_g]))
            changes.append(np.abs(a[ok_a]))
            over_grade_m += SAMPLE_M * int((np.abs(g[ok_g]) > cls["max_grade"]).sum())
            # crest where the grade falls along the way, sag where it rises; K in m per %
            k_min = np.where(a < 0, cls["k_crest_ft"], cls["k_sag_ft"]) * FT
            with np.errstate(divide="ignore", invalid="ignore"):
                k_est = CHORD_M / (np.abs(a) * 100.0)
            low_k_m += SAMPLE_M * int((ok_a & (k_est < k_min)).sum())

            g0, a0 = np.nan_to_num(g), np.nan_to_num(a)
            flagged = (np.abs(g0) > BREAK_GRADE) | (np.abs(a0) > BREAK_CHANGE)
            for i0, i1 in runs(flagged):
                k = i0 + int(np.argmax(np.abs(g0[i0:i1]) + np.abs(a0[i0:i1])))
                gx, gz = xs[k], zs[k]
                t = np.array([xs[min(k + 1, len(xs) - 1)] - xs[max(k - 1, 0)],
                              zs[min(k + 1, len(zs) - 1)] - zs[max(k - 1, 0)]])
                t /= max(np.hypot(*t), 1e-9)
                yb, ya = ground.sample([gx - t[0] * CHORD_M / 2, gx + t[0] * CHORD_M / 2],
                                       [gz - t[1] * CHORD_M / 2, gz + t[1] * CHORD_M / 2])
                near = float(np.min(np.hypot(ends[:, 0] - gx, ends[:, 1] - gz))) if len(ends) else None
                breaks.append({
                    "way_id": w["id"], "name": w["tags"].get("name"), "highway": w["tags"]["highway"],
                    "station": round(float(ds[k]), 1), "length_m": round(float(ds[i1 - 1] - ds[i0]) + SAMPLE_M, 1),
                    "x": round(float(gx), 1), "z": round(float(gz), 1),
                    "grade": round(float(g0[k]), 3), "grade_change": round(float(a0[k]), 3),
                    "ground_grade": round(float((ya - yb) / CHORD_M), 3),
                    "nearest_bridge_end_m": None if near is None else round(near, 1),
                })
        hws = [v.get("hw") for v in w["vertices"]]
        half = hws if all(h is not None for h in hws) else w["tags"].get("width_m", 6.0) / 2.0
        crosses.append(cross_slopes(pts, half, surface))

    grades = np.concatenate(grades) if grades else np.empty(0)
    changes = np.concatenate(changes) if changes else np.empty(0)
    crosses = np.concatenate(crosses) if crosses else np.empty(0)
    crosses = crosses[~np.isnan(crosses)]
    crown = standards["cross_section"]["crown"]

    steps = []
    for node in roads["junction_nodes"]:
        legs = [leg for wid in node["way_ids"] if wid in by_id
                for leg in leg_paths(by_id[wid]["vertices"], node["node_id"])]
        step = junction_step(node, legs, surface)
        if step is not None:
            steps.append(step)
    steps = np.array(steps)
    legacy = legacy_profile_disagreement([w for w in osm_ways if class_of(w["tags"]["highway"], standards)
                                          and not w["tags"].get("bridge")], ground)
    from build_road_plan import VALID_BOUNDS
    beyond = length_beyond_heightmap(ways, surface, VALID_BOUNDS)

    breaks.sort(key=lambda b: -(abs(b["grade"]) + abs(b["grade_change"])))
    metrics = {
        "grade_pct": {k: (None if v is None else round(v * 100, 2)) for k, v in pct(grades).items()},
        "grade_change_pct_per_10m": {k: (None if v is None else round(v * 100, 2)) for k, v in pct(changes).items()},
        "grade_over_class_max_m": round(over_grade_m, 1),
        "k_below_class_min_m": round(low_k_m, 1),
        "cross_slope_dev_from_crown_pct": {k: (None if v is None else round(v * 100, 2))
                                           for k, v in pct(np.abs(crosses - crown)).items()},
        "cross_slope_adverse_sides": int((crosses < ADVERSE_CROSS_SLOPE).sum()),
        "junction_step_m": pct(steps),
        "junction_steps_over_0.10m": int((steps > 0.10).sum()),
        "junction_steps_over_0.25m": int((steps > 0.25).sum()),
        "breaklines": len(breaks),
        "drivable_length_beyond_play_heightmap_m": round(beyond, 1),
    }
    return {
        "metrics": metrics,
        "counts": {"ways": len(ways), "profile_samples": int(grades.size),
                   "cross_slope_samples": int(crosses.size), "junctions_measured": int(steps.size)},
        "diagnostic": {"legacy_profile_disagreement_m": pct(legacy),
                       "legacy_nodes_over_0.10m": int((legacy > 0.10).sum()),
                       "legacy_nodes_over_0.25m": int((legacy > 0.25).sum())},
        "breaklines": breaks,
    }


# The metrics held to the baseline: each measures a defect, so lower is better. Plain grade is
# reported but not held, since a design that follows the terrain may be steeper in places. Grade
# over the class limit and K under it are reported but not held either: the class limits are
# advisory, values for new designs that existing streets need not meet.
RATCHETED = ("grade_change_pct_per_10m", "cross_slope_dev_from_crown_pct",
             "cross_slope_adverse_sides", "junction_step_m", "junction_steps_over_0.10m",
             "junction_steps_over_0.25m", "breaklines", "drivable_length_beyond_play_heightmap_m")


def flatten(metrics, prefix=""):
    out = {}
    for k, v in metrics.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        elif v is not None:
            out[key] = float(v)
    return out


def regressions(current, baseline, rel=0.02, abs_tol=0.01):
    """[(metric, baseline, current), ...] for every metric now worse than its baseline."""
    cur = flatten(current)
    out = []
    for key, base in flatten(baseline).items():
        if key not in cur:
            out.append((key, base, None))
        elif cur[key] > base + max(abs(base) * rel, abs_tol):
            out.append((key, base, cur[key]))
    return out


def built_vertices_beyond_heightmap(build_dir=os.path.dirname(REPORT_PATH)):
    """Road-layer surface vertices the bake would place past the play heightmap's edge."""
    hm = pc.load_world_origin()["heightmaps"]["play"]
    x0 = hm["origin_easting"] - pc.ORIGIN_EASTING
    z0 = -(hm["origin_northing_top"] - pc.ORIGIN_NORTHING)
    x1, z1 = x0 + hm["width"] * hm["spacing_m"], z0 + hm["height"] * hm["spacing_m"]
    tol = 15.0   # a ribbon's corners reach half a road width past its centreline's end at the edge
    total = beyond = 0
    for name in sorted(os.listdir(build_dir)):
        if not (name.startswith("chunk_") and name.endswith(".json")):
            continue
        with open(os.path.join(build_dir, name)) as handle:
            for mesh in json.load(handle)["meshes"]:
                v = np.asarray(mesh["verts"], dtype=np.float64)
                if v.size == 0:
                    continue
                total += len(v)
                beyond += int(((v[:, 0] < x0 - tol) | (v[:, 0] > x1 + tol) |
                               (v[:, 2] < z0 - tol) | (v[:, 2] > z1 + tol)).sum())
    return total, beyond


def main(argv):
    surface = None
    if "--surface" in argv:          # measure another conformed heightmap (e.g. a saved earlier one)
        surface = Surface(argv[argv.index("--surface") + 1])
    report = measure(surface=surface, design="--osm" not in argv)
    if os.path.isdir(os.path.dirname(REPORT_PATH)):
        total, beyond = built_vertices_beyond_heightmap()
        report["diagnostic"]["built_vertices"] = total
        report["diagnostic"]["built_vertices_beyond_play_heightmap"] = beyond
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as handle:
        json.dump(report, handle, indent=1)
    print(json.dumps({"metrics": report["metrics"], "counts": report["counts"],
                      "diagnostic": report["diagnostic"]}, indent=1))
    print(f"{len(report['breaklines'])} breaklines; worst:")
    for b in report["breaklines"][:12]:
        print(f"  way {b['way_id']} {b['name'] or '-'} ({b['highway']}) sta {b['station']} at "
              f"({b['x']}, {b['z']}): grade {b['grade']:+.1%} change {b['grade_change']:+.1%} "
              f"ground {b['ground_grade']:+.1%}, bridge end {b['nearest_bridge_end_m']} m")
    print(f"report: {REPORT_PATH}")
    if "--update-baseline" in argv:
        with open(BASELINE_PATH, "w") as handle:
            json.dump({"_about": "Ratchet for test_road_metrics.py: lower is better for every metric. "
                                 "Regenerate with road_metrics.py --update-baseline only when the "
                                 "numbers improve.",
                       "metrics": {k: report["metrics"][k] for k in RATCHETED}}, handle, indent=1)
            handle.write("\n")
        print(f"baseline written: {BASELINE_PATH}")
    elif os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH) as handle:
            worse = regressions(report["metrics"], json.load(handle)["metrics"])
        for key, base, cur in worse:
            print(f"REGRESSION {key}: baseline {base}, now {cur}")
        return 1 if worse else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
