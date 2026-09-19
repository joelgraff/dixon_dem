#!/usr/bin/env python3
"""Builds the Dixon road network build-plan: chunked JSON of triangle soups +
instance-transform lists, consumed by game/roads/tools/build_roads.gd to bake
game/roads/roads.tscn. See docs/roads_notes.md.

Run: cd pipeline/roads && ../../.venv/bin/python build_road_plan.py
"""
import json
import math
import os
import sys
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common_roads import (
    Heightmap, resample_polyline, trim_polyline, offset_polyline, direction_at,
    MeshBuild, add_ribbon, fan_fill, line_intersect, angle_of, polyline_length, EPS,
    fillet_arc, dist, point_and_dir_at,
)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common as pc

OUT_DIR = os.path.join(pc.ROOT, "game", "roads", "_build")
CHUNK_SIZE = 200.0
# Play area is x:[0,2700] z:[-2700,0] (see world_origin.json); some source ways
# (notably rails.json -- long real-world rail lines fetched without geometry
# clipping) extend far beyond it. Drop anything outside a generous margin
# rather than trust every input file to be pre-clipped.
VALID_BOUNDS = (-400.0, -3100.0, 3100.0, 400.0)  # x0,z0,x1,z1


def in_bounds(x, z):
    x0, z0, x1, z1 = VALID_BOUNDS
    return x0 <= x <= x1 and z0 <= z <= z1

DRIVABLE = {"residential", "service", "primary", "secondary", "tertiary",
            "unclassified", "primary_link", "tertiary_link", "track"}
CURBED = {"residential", "primary", "secondary", "tertiary", "unclassified",
          "primary_link", "tertiary_link"}  # service/track: no curb (flush apron)
PATHY = {"footway", "cycleway", "path", "pedestrian", "steps"}

DOWNTOWN_STREET_WORDS = ("galena", "1st", "first", "2nd", "second", "3rd", "third", "hennepin", "peoria")
DOWNTOWN_BOUNDS = (1330.0, -1780.0, 1920.0, -1030.0)  # x0,z0,x1,z1

CURB_HEIGHT = 0.15
CURB_WIDTH = 0.12
GUTTER_WIDTH = 0.35
PARKWAY_GAP = 2.0
SIDEWALK_W_RESIDENTIAL = 1.7
SIDEWALK_W_DOWNTOWN = 3.6
ROAD_Y_BIAS = 0.085  # was 0.025 (too tight against terrain's own +-20mm tolerance,
                    # risking z-fighting at large world coords). A diagnostic run at
                    # 0.5 m ruled out depth/z-fighting as the cause of the remaining
                    # mid-block coverage anomaly (see docs/roads_notes.md) -- reverted
                    # to this more modest, still-safe value rather than an obviously
                    # floating 0.5 m once that hypothesis was excluded.
                    # 8.5 cm clears terrain in 99.6% of samples and stays well under CURB_HEIGHT.


def clip_ways_to_bounds(ways):
    """Splits each way into contiguous in-bounds vertex runs (see VALID_BOUNDS);
    drops the out-of-bounds portions entirely (real OSM lines can run for
    many km past the play area, e.g. rails.json's mainline railways)."""
    out = []
    for w in ways:
        vs = w["vertices"]
        run = []
        piece_n = 0
        for v in vs:
            if in_bounds(v["x"], v["z"]):
                run.append(v)
            else:
                if len(run) >= 2:
                    piece = dict(w)
                    piece["vertices"] = run
                    piece["id"] = w["id"] * 100 + piece_n
                    piece_n += 1
                    out.append(piece)
                run = []
        if len(run) >= 2:
            piece = dict(w)
            piece["vertices"] = run
            piece["id"] = w["id"] * 100 + piece_n
            out.append(piece)
    return out


def load_json(name):
    with open(os.path.join(pc.GAME_DATA, name)) as f:
        return json.load(f)


def is_downtown_way(tags, sample_pt):
    name = (tags.get("name") or "").lower()
    if not any(w in name for w in DOWNTOWN_STREET_WORDS):
        return False
    x, z = sample_pt
    x0, z0, x1, z1 = DOWNTOWN_BOUNDS
    return x0 <= x <= x1 and z0 <= z <= z1


# ---------------------------------------------------------------------------
# 1. Split ways at interior junction hits so every segment's endpoints are
#    junction nodes or dead-ends (roads.json ways aren't always pre-split at
#    T-intersections where a minor way meets a major way's interior vertex).
# ---------------------------------------------------------------------------
def split_at_junctions(ways, junction_ids):
    out = []
    for w in ways:
        vs = w["vertices"]
        split_idx = [0]
        for i in range(1, len(vs) - 1):
            if vs[i]["node_id"] in junction_ids:
                split_idx.append(i)
        split_idx.append(len(vs) - 1)
        split_idx = sorted(set(split_idx))
        if len(split_idx) <= 2:
            out.append(dict(w))
            continue
        for k in range(len(split_idx) - 1):
            a, b = split_idx[k], split_idx[k + 1]
            if b <= a:
                continue
            piece = dict(w)
            piece["vertices"] = vs[a:b + 1]
            piece["id"] = w["id"] * 1000 + k
            piece["_orig_id"] = w["id"]
            out.append(piece)
    return out


def way_xz(w):
    return [(v["x"], v["z"]) for v in w["vertices"]]


# ---------------------------------------------------------------------------
# 2. Build per-node adjacency for the drivable network.
# ---------------------------------------------------------------------------
class Node:
    __slots__ = ("id", "x", "z", "legs")

    def __init__(self, id_, x, z):
        self.id = id_
        self.x = x
        self.z = z
        self.legs = []  # list of dict(way=way, end='start'/'end')


def build_graph(drivable_ways):
    nodes = {}
    for w in drivable_ways:
        vs = w["vertices"]
        for end, idx in (("start", 0), ("end", -1)):
            nid = vs[idx]["node_id"]
            if nid not in nodes:
                nodes[nid] = Node(nid, vs[idx]["x"], vs[idx]["z"])
            nodes[nid].legs.append({"way": w, "end": end})
    return nodes


def way_half_width(w):
    width = w["tags"].get("width_m") or 6.0
    return max(width, 2.0) / 2.0


def pullback_for_node(node, leg_half_width):
    """Curb-return pullback distance for one way-end at this junction node.
    Real (3+-way) intersections get the brief's 4-8 m curb-return radius;
    a degree-2 node (a pass-through split, not a real corner -- see the
    comment where this is called) only needs a small fixed pullback so its
    fillet join stays numerically clean without eating the whole segment."""
    if node is None:
        return 0.0
    if len(node.legs) <= 2:
        return 1.0
    return max(4.0, min(8.0, leg_half_width * 1.6))


# ---------------------------------------------------------------------------
# 3. Geometry plan per way: resampled centerline, trimmed at junction ends,
#    plus the offset "rings" (asphalt edge, curb outer, sidewalk inner/outer).
# ---------------------------------------------------------------------------
RING_NAMES = ["edge", "curb_out", "gutter_out", "sw_in", "sw_out"]


class WayPlan:
    __slots__ = ("way", "half_w", "has_curb", "has_sidewalk", "sw_width", "parkway",
                 "centerline", "full_centerline", "downtown", "rings",
                 "start_junction", "end_junction", "start_free", "end_free")


def plan_drivable_ways(drivable_ways, nodes):
    plans = []
    for w in drivable_ways:
        vs = way_xz(w)
        if len(vs) < 2 or polyline_length(vs) < 0.5:
            continue
        hw = way_half_width(w)
        cls = w["tags"].get("highway")
        curbed = cls in CURBED
        downtown = is_downtown_way(w["tags"], vs[len(vs) // 2])
        sw_width = SIDEWALK_W_DOWNTOWN if downtown else SIDEWALK_W_RESIDENTIAL
        parkway = 0.0 if downtown else PARKWAY_GAP
        has_sidewalk = curbed  # same eligibility as curb for now

        resampled = resample_polyline(vs, spacing=4.5, smooth_iters=1)
        length = polyline_length(resampled)

        start_id = w["vertices"][0]["node_id"]
        end_id = w["vertices"][-1]["node_id"]
        start_node = nodes.get(start_id)
        end_node = nodes.get(end_id)
        start_junction = start_node is not None and len(start_node.legs) >= 2
        end_junction = end_node is not None and len(end_node.legs) >= 2

        # Curb-return pullback only makes sense for a REAL intersection (3+
        # ways). A degree-2 "junction" is usually just an OSM way split at an
        # interior shaping/tag-change vertex with nothing crossing it -- most
        # of roads.json's ~1750 post-split junction nodes are this, not actual
        # corners. Treating every one of those like a full curb-return blew
        # 8 m off *each* end of already-short segments, leaving degenerate
        # slivers (and visible gaps in the asphalt) between them. Degree-2
        # gets a small fixed pullback (just enough for the fillet join to stay
        # numerically clean); only real 3+-way junctions get the 4-8 m radius.
        pb_start = pullback_for_node(start_node, hw) if start_junction else 0.0
        pb_end = pullback_for_node(end_node, hw) if end_junction else 0.0
        pb_start = min(pb_start, length * 0.35)
        pb_end = min(pb_end, length * 0.35)
        trimmed = trim_polyline(resampled, pb_start, pb_end)

        plan = WayPlan()
        plan.way = w
        plan.half_w = hw
        plan.has_curb = curbed
        plan.has_sidewalk = has_sidewalk
        plan.sw_width = sw_width
        plan.parkway = parkway
        plan.centerline = trimmed
        plan.full_centerline = resampled
        plan.downtown = downtown
        plan.start_junction = start_node if start_junction else None
        plan.end_junction = end_node if end_junction else None
        plan.start_free = not start_junction
        plan.end_free = not end_junction

        rings = {}
        rings["edge_L"] = offset_polyline(trimmed, hw)
        rings["edge_R"] = offset_polyline(trimmed, -hw)
        if curbed:
            rings["curb_out_L"] = offset_polyline(trimmed, hw + CURB_WIDTH)
            rings["curb_out_R"] = offset_polyline(trimmed, -(hw + CURB_WIDTH))
            rings["gutter_out_L"] = offset_polyline(trimmed, hw - GUTTER_WIDTH)
            rings["gutter_out_R"] = offset_polyline(trimmed, -(hw - GUTTER_WIDTH))
        if has_sidewalk:
            sw_in = hw + CURB_WIDTH + parkway
            sw_out = sw_in + sw_width
            rings["sw_in_L"] = offset_polyline(trimmed, sw_in)
            rings["sw_out_L"] = offset_polyline(trimmed, sw_out)
            rings["sw_in_R"] = offset_polyline(trimmed, -sw_in)
            rings["sw_out_R"] = offset_polyline(trimmed, -sw_out)
        plan.rings = rings
        plans.append(plan)
    return plans


def outward_dir(plan, end):
    if end == "start":
        return direction_at(plan.centerline, 0)
    d = direction_at(plan.centerline, len(plan.centerline) - 1)
    return (-d[0], -d[1])


def cut_point(plan, end):
    return plan.centerline[0] if end == "start" else plan.centerline[-1]


def ring_point(plan, key, side, end):
    idx = 0 if end == "start" else -1
    arr_side = side if end == "start" else ("R" if side == "L" else "L")
    arr = plan.rings.get(key + "_" + arr_side)
    if arr is None:
        return None
    return arr[idx]


ARC_N = 4  # points per curb-return fillet, incl. endpoints


def build_loop(sorted_legs, ring_key, center):
    """Ordered boundary loop [R0,L0, arc.., R1,L1, arc.., ...] at one ring level."""
    n = len(sorted_legs)
    pts = []
    for i in range(n):
        plan, end = sorted_legs[i]
        r_pt = ring_point(plan, ring_key, "R", end)
        l_pt = ring_point(plan, ring_key, "L", end)
        if r_pt is None or l_pt is None:
            return None
        pts.append(r_pt)
        pts.append(l_pt)
        nxt_plan, nxt_end = sorted_legs[(i + 1) % n]
        nxt_r = ring_point(nxt_plan, ring_key, "R", nxt_end)
        if nxt_r is None:
            return None
        arc = fillet_arc(l_pt, outward_dir(plan, end), nxt_r, outward_dir(nxt_plan, nxt_end), center, ARC_N)
        pts.extend(arc[1:-1])
    return pts


def ribbon_between_loops(mb_by_mat, loop_in, loop_out, hm, y_bias_in, y_bias_out, material_tag,
                          flip=False, double_sided=False, close_loop=True):
    if loop_in is None or loop_out is None or len(loop_in) != len(loop_out) or len(loop_in) < 2:
        return
    n = len(loop_in)
    sub = MeshBuild()
    li = []
    ri = []
    for k in range(n):
        lx, lz = loop_in[k]
        rx, rz = loop_out[k]
        ly = hm.sample(lx, lz) + y_bias_in
        ry = hm.sample(rx, rz) + y_bias_out
        ln = hm.normal(lx, lz)
        rn = hm.normal(rx, rz)
        li.append(sub.add_vertex(lx, ly, lz, ln))
        ri.append(sub.add_vertex(rx, ry, rz, rn))
    count = n if close_loop else n - 1
    for k in range(count):
        k2 = (k + 1) % n
        if flip:
            sub.add_quad(ri[k], ri[k2], li[k2], li[k])
        else:
            sub.add_quad(li[k], li[k2], ri[k2], ri[k])
        if double_sided:
            if flip:
                sub.add_quad(li[k], li[k2], ri[k2], ri[k])
            else:
                sub.add_quad(ri[k], ri[k2], li[k2], li[k])
    if not sub.is_empty():
        mb_by_mat.setdefault(material_tag, MeshBuild()).extend(sub)


def add_quad_both(mb, a, b, c, d):
    mb.add_quad(a, b, c, d)
    mb.add_quad(d, c, b, a)


def close_loop_fill(mb_by_mat, loop, hm, y_bias, material_tag):
    if loop is None or len(loop) < 3:
        return
    sub = MeshBuild()
    fan_fill(sub, loop, hm, y_bias)
    if not sub.is_empty():
        mb_by_mat.setdefault(material_tag, MeshBuild()).extend(sub)


def asphalt_material_for(w):
    # "_plowed" variants (game/roads/materials/) reuse the frozen shared
    # asphalt textures/shader but resist snow accumulation (very negative
    # snow_slope_bias) so winter driving lanes read as plowed/wet-dark against
    # full-coverage snow on curbs/sidewalks -- see docs/roads_notes.md.
    cls = w["tags"].get("highway")
    if cls in ("residential", "service", "track"):
        return "asphalt_patched_plowed"
    return "asphalt_road_plowed"


def build_way_surfaces(plans, hm, mb_by_mat):
    # Single-sided ribbons: for any ribbon confined to one offset side (L or R)
    # progressing outward (whether "outward" means increasing horizontal offset
    # at constant height, or increasing height at constant offset), flip=True
    # on the L side / flip=False on the R side gives an outward-facing normal
    # for gutter/top-lip surfaces and (since bottom->top uses the SAME ring
    # twice, which cancels the side's own offset out of the edge vectors and
    # leaves only the *ring identity* determining sign) an inward, road-facing
    # normal on the vertical faces -- verified by direct cross-product algebra
    # for both cases, so no double-siding is needed on the straight runs.
    for plan in plans:
        mat = asphalt_material_for(plan.way)
        sub = MeshBuild()
        add_ribbon(sub, plan.rings["edge_L"], plan.rings["edge_R"], hm, y_bias=ROAD_Y_BIAS)
        if not sub.is_empty():
            mb_by_mat.setdefault(mat, MeshBuild()).extend(sub)

        if plan.has_curb:
            for side in ("L", "R"):
                flip = side == "L"
                edge_ring = plan.rings[f"edge_{side}"]
                curb_out_ring = plan.rings[f"curb_out_{side}"]
                ribbon_between_loops(mb_by_mat, edge_ring, edge_ring, hm, ROAD_Y_BIAS, CURB_HEIGHT,
                                      "curb_concrete", flip=flip, close_loop=False)
                ribbon_between_loops(mb_by_mat, edge_ring, curb_out_ring, hm, CURB_HEIGHT, CURB_HEIGHT,
                                      "curb_concrete", flip=flip, close_loop=False)
                ribbon_between_loops(mb_by_mat, curb_out_ring, curb_out_ring, hm, CURB_HEIGHT, -0.05,
                                      "curb_concrete", flip=flip, close_loop=False)

        if plan.has_sidewalk:
            for side in ("L", "R"):
                flip = side == "L"
                sw_in = plan.rings[f"sw_in_{side}"]
                sw_out = plan.rings[f"sw_out_{side}"]
                ribbon_between_loops(mb_by_mat, sw_in, sw_out, hm, 0.05, 0.05, "sidewalk_concrete",
                                      flip=flip, close_loop=False)
                ribbon_between_loops(mb_by_mat, sw_in, sw_in, hm, 0.05, -0.05, "sidewalk_concrete",
                                      flip=flip, close_loop=False)
                ribbon_between_loops(mb_by_mat, sw_out, sw_out, hm, 0.05, -0.05, "sidewalk_concrete",
                                      flip=flip, close_loop=False)


def build_junction_geometry(nodes, plan_by_way_id, hm, mb_by_mat):
    for node in nodes.values():
        legs = []
        for leg in node.legs:
            plan = plan_by_way_id.get(id(leg["way"]))
            if plan is not None:
                legs.append((plan, leg["end"]))
        if len(legs) < 2:
            continue
        legs_sorted = sorted(legs, key=lambda item: angle_of(outward_dir(item[0], item[1])))
        center = (node.x, node.z)

        try:
            asphalt_loop = build_loop(legs_sorted, "edge", center)
        except Exception:
            asphalt_loop = None
        if asphalt_loop and len(asphalt_loop) >= 3:
            mats = [asphalt_material_for(p.way) for p, _ in legs_sorted]
            # Prefer the neutral-grey "_road" surface over the warmer "_patched"
            # one whenever any connecting leg is a through-class road -- a big
            # junction fan rendered in "_patched" reads as a blotchy pale-tan
            # patch against its neighbors; a mixed intersection realistically
            # gets through-street pavement anyway, not residential patching.
            mat = "asphalt_road_plowed" if "asphalt_road_plowed" in mats else max(set(mats), key=mats.count)
            close_loop_fill(mb_by_mat, asphalt_loop, hm, ROAD_Y_BIAS, mat)

        if all(p.has_curb for p, _ in legs_sorted):
            try:
                curb_out_loop = build_loop(legs_sorted, "curb_out", center)
                gutter_loop = build_loop(legs_sorted, "gutter_out", center)
            except Exception:
                curb_out_loop = gutter_loop = None
            if asphalt_loop and curb_out_loop:
                ribbon_between_loops(mb_by_mat, asphalt_loop, asphalt_loop, hm, ROAD_Y_BIAS, CURB_HEIGHT,
                                      "curb_concrete", double_sided=True, close_loop=True)
                ribbon_between_loops(mb_by_mat, asphalt_loop, curb_out_loop, hm, CURB_HEIGHT, CURB_HEIGHT,
                                      "curb_concrete", double_sided=True, close_loop=True)
                ribbon_between_loops(mb_by_mat, curb_out_loop, curb_out_loop, hm, CURB_HEIGHT, -0.05,
                                      "curb_concrete", double_sided=True, close_loop=True)
            if asphalt_loop and gutter_loop:
                ribbon_between_loops(mb_by_mat, gutter_loop, asphalt_loop, hm, ROAD_Y_BIAS + 0.005,
                                      ROAD_Y_BIAS + 0.01, "sidewalk_concrete", double_sided=True, close_loop=True)

        if all(p.has_sidewalk for p, _ in legs_sorted):
            try:
                sw_in_loop = build_loop(legs_sorted, "sw_in", center)
                sw_out_loop = build_loop(legs_sorted, "sw_out", center)
            except Exception:
                sw_in_loop = sw_out_loop = None
            if sw_in_loop and sw_out_loop:
                ribbon_between_loops(mb_by_mat, sw_in_loop, sw_out_loop, hm, 0.05, 0.05,
                                      "sidewalk_concrete", double_sided=True, close_loop=True)
                ribbon_between_loops(mb_by_mat, sw_in_loop, sw_in_loop, hm, 0.05, -0.05,
                                      "sidewalk_concrete", double_sided=True, close_loop=True)
                ribbon_between_loops(mb_by_mat, sw_out_loop, sw_out_loop, hm, 0.05, -0.05,
                                      "sidewalk_concrete", double_sided=True, close_loop=True)


# ---------------------------------------------------------------------------
# Pavement markings
# ---------------------------------------------------------------------------
def _paint_ribbon(mb_by_mat, line_pts, width, mat, hm, y_bias=0.045):
    if len(line_pts) < 2:
        return
    left = offset_polyline(line_pts, width * 0.5)
    right = offset_polyline(line_pts, -width * 0.5)
    sub = MeshBuild()
    add_ribbon(sub, left, right, hm, y_bias=y_bias)
    if not sub.is_empty():
        mb_by_mat.setdefault(mat, MeshBuild()).extend(sub)


def _dash_segments(total_len, dash_on, dash_off, phase=0.0):
    segs = []
    pos = -phase
    while pos < total_len:
        s = max(pos, 0.0)
        e = min(pos + dash_on, total_len)
        if e > s:
            segs.append((s, e))
        pos += dash_on + dash_off
    return segs


def _sub_polyline(pts, s, e):
    total = polyline_length(pts)
    return trim_polyline(pts, s, max(0.0, total - e))


def build_markings(plans, hm, mb_by_mat):
    for plan in plans:
        w = plan.way
        cls = w["tags"].get("highway")
        lanes = w["tags"].get("lanes") or 2
        line = plan.centerline
        total = polyline_length(line)
        if total < 6.0:
            continue
        if cls in ("primary", "secondary", "primary_link"):
            for off in (0.09, -0.09):
                offline = offset_polyline(line, off)
                _paint_ribbon(mb_by_mat, offline, 0.12, "marking_yellow", hm)
            if lanes >= 4:
                for off in (plan.half_w * 0.5, -plan.half_w * 0.5):
                    offline = offset_polyline(line, off)
                    for s, e in _dash_segments(total, 3.0, 5.0):
                        seg = _sub_polyline(offline, s, e)
                        _paint_ribbon(mb_by_mat, seg, 0.10, "marking_white", hm)
        elif cls in ("tertiary", "tertiary_link", "unclassified") and lanes >= 2:
            for s, e in _dash_segments(total, 3.0, 5.0):
                seg = _sub_polyline(line, s, e)
                _paint_ribbon(mb_by_mat, seg, 0.10, "marking_yellow", hm)


CROSSWALK_CROSS_NAMES = ("1st", "first", "2nd", "second", "3rd", "third", "peoria", "hennepin", "court")


def find_downtown_intersections(nodes, plan_by_way_id):
    """Junctions where a Galena Ave leg meets a named cross street, inside downtown bounds."""
    out = []
    for node in nodes.values():
        legs = []
        for leg in node.legs:
            plan = plan_by_way_id.get(id(leg["way"]))
            if plan is not None:
                legs.append((plan, leg["end"]))
        if len(legs) < 3:
            continue
        x0, z0, x1, z1 = DOWNTOWN_BOUNDS
        if not (x0 <= node.x <= x1 and z0 <= node.z <= z1):
            continue
        names = [(p.way["tags"].get("name") or "").lower() for p, _ in legs]
        has_galena = any("galena" in n for n in names)
        has_cross = any(any(cw in n for cw in CROSSWALK_CROSS_NAMES) for n in names)
        if has_galena and has_cross:
            out.append((node, legs))
    return out


def build_intersection_markings(nodes, plan_by_way_id, hm, mb_by_mat, furniture):
    for node, legs in find_downtown_intersections(nodes, plan_by_way_id):
        legs_sorted = sorted(legs, key=lambda item: angle_of(outward_dir(item[0], item[1])))
        center = (node.x, node.z)
        for plan, end in legs_sorted:
            cut = cut_point(plan, end)
            out_dir = outward_dir(plan, end)
            perp = (-out_dir[1], out_dir[0])
            hw = plan.half_w
            # stop bar: ~1m back from the cut, spanning this leg's lane half.
            bar_center = (cut[0] - out_dir[0] * 1.0, cut[1] - out_dir[1] * 1.0)
            a = (bar_center[0] + perp[0] * hw, bar_center[1] + perp[1] * hw)
            b = (bar_center[0] - perp[0] * hw, bar_center[1] - perp[1] * hw)
            _paint_ribbon(mb_by_mat, [a, b], 0.45, "marking_white", hm)
            # continental crosswalk: ladder stripes ~2m outside the pullback cut.
            cw_center = (cut[0] + out_dir[0] * 2.0, cut[1] + out_dir[1] * 2.0)
            n_stripes = 6
            span = hw * 2.0 - 0.6
            for i in range(n_stripes):
                t = (i / (n_stripes - 1) - 0.5) * span
                p0 = (cw_center[0] + perp[0] * t - out_dir[0] * 1.0, cw_center[1] + perp[1] * t - out_dir[1] * 1.0)
                p1 = (cw_center[0] + perp[0] * t + out_dir[0] * 1.0, cw_center[1] + perp[1] * t + out_dir[1] * 1.0)
                _paint_ribbon(mb_by_mat, [p0, p1], 0.45, "marking_white", hm)
            signal_pos = (cut[0] + perp[0] * (hw + 1.2), cut[1] + perp[1] * (hw + 1.2))
            ry = math.atan2(out_dir[1], out_dir[0])
            y = hm.sample(*signal_pos)
            furniture.setdefault("signal_mast", []).append([signal_pos[0], y, signal_pos[1], ry])
            sign_pos = (cut[0] + perp[0] * (hw + 0.6), cut[1] + perp[1] * (hw + 0.6))
            y2 = hm.sample(*sign_pos)
            furniture.setdefault("sign_street", []).append([sign_pos[0], y2, sign_pos[1], ry])


# ---------------------------------------------------------------------------
# Street furniture (multimesh instance placement)
# ---------------------------------------------------------------------------
def build_furniture(plans, hm, furniture):
    manhole_phase = 0.0
    for plan in plans:
        if not plan.has_curb:
            continue
        full = plan.full_centerline
        total = polyline_length(full)
        if total < 10.0:
            continue
        lamp_kind = "lamp_downtown" if plan.downtown else "lamp_residential"
        lamp_spacing = 27.0 if plan.downtown else 46.0
        offset_dist = (plan.sw_width + plan.half_w + CURB_WIDTH + plan.parkway + 0.5) if plan.has_sidewalk else (plan.half_w + 1.0)

        n_lamps = max(0, int(total // lamp_spacing))
        for i in range(n_lamps):
            d = lamp_spacing * 0.5 + i * lamp_spacing
            x, z, dx, dz = point_and_dir_at(full, d)
            px, pz = x - dz * offset_dist, z + dx * offset_dist
            y = hm.sample(px, pz)
            ry = math.atan2(dz, dx) + math.pi / 2
            furniture.setdefault(lamp_kind, []).append([px, y, pz, ry])

        n_hyd = max(0, int(total // 130.0))
        for i in range(n_hyd):
            d = 130.0 * 0.5 + i * 130.0
            x, z, dx, dz = point_and_dir_at(full, d)
            hd = offset_dist * 0.55
            px, pz = x + dz * hd, z - dx * hd
            y = hm.sample(px, pz)
            ry = math.atan2(dz, dx)
            furniture.setdefault("hydrant", []).append([px, y, pz, ry])

        n_man = max(0, int(total // 150.0))
        for i in range(n_man):
            d = 150.0 * 0.5 + i * 150.0 + manhole_phase
            if d >= total:
                continue
            x, z, dx, dz = point_and_dir_at(full, d)
            y = hm.sample(x, z) + ROAD_Y_BIAS + 0.003
            ry = math.atan2(dz, dx)
            furniture.setdefault("manhole", []).append([x, y, z, ry])
        manhole_phase = (manhole_phase + 53.0) % 150.0

        # Windrows (plowed-snow piles) run both sides, right at the curb's
        # outer face; leaf litter drifts along the gutter, inside the curb.
        # Both are static geometry -- roads.gd toggles visibility by season.
        windrow_off = plan.half_w + CURB_WIDTH + 0.18
        gutter_off = plan.half_w - GUTTER_WIDTH * 0.6
        n_wind = max(0, int(total // 1.8))
        n_leaf = max(0, int(total // 7.0))
        for side in (1.0, -1.0):
            for i in range(n_wind):
                d = 1.8 * 0.5 + i * 1.8
                x, z, dx, dz = point_and_dir_at(full, d)
                px, pz = x - dz * windrow_off * side, z + dx * windrow_off * side
                y = hm.sample(px, pz)
                ry = math.atan2(dz, dx)
                furniture.setdefault("windrow", []).append([px, y, pz, ry])
            for i in range(n_leaf):
                d = 7.0 * 0.5 + i * 7.0 + side * 2.0
                if d < 0 or d >= total:
                    continue
                x, z, dx, dz = point_and_dir_at(full, d)
                px, pz = x - dz * gutter_off * side, z + dx * gutter_off * side
                y = hm.sample(px, pz) + ROAD_Y_BIAS + 0.002
                ry = math.atan2(dz, dx)
                furniture.setdefault("leaf_litter", []).append([px, y, pz, ry])


def build_stop_signs(nodes, plan_by_way_id, downtown_node_ids, hm, furniture):
    for node in nodes.values():
        if node.id in downtown_node_ids:
            continue
        legs = []
        for leg in node.legs:
            plan = plan_by_way_id.get(id(leg["way"]))
            if plan is not None and plan.has_curb:
                legs.append((plan, leg["end"]))
        if len(legs) < 3:
            continue
        # one sign, on the right side of the first leg (angularly), simple & bounded in count
        plan, end = min(legs, key=lambda item: angle_of(outward_dir(item[0], item[1])))
        cut = cut_point(plan, end)
        out_dir = outward_dir(plan, end)
        perp = (-out_dir[1], out_dir[0])
        pos = (cut[0] - perp[0] * (plan.half_w + 0.8) + out_dir[0] * 1.5,
               cut[1] - perp[1] * (plan.half_w + 0.8) + out_dir[1] * 1.5)
        y = hm.sample(*pos)
        ry = math.atan2(out_dir[1], out_dir[0])
        furniture.setdefault("stopsign", []).append([pos[0], y, pos[1], ry])


# ---------------------------------------------------------------------------
# Non-drivable paths (footway/cycleway/path/pedestrian/steps)
# ---------------------------------------------------------------------------
PATH_MATERIAL = {
    "footway": "sidewalk_concrete", "pedestrian": "sidewalk_concrete", "steps": "sidewalk_concrete",
    "cycleway": "asphalt_road", "path": "gravel_ballast", "track": "gravel_ballast",
}


def build_pathy(ways, hm, mb_by_mat):
    for w in ways:
        cls = w["tags"].get("highway")
        if cls not in PATHY or w["tags"].get("bridge"):
            continue
        vs = way_xz(w)
        if len(vs) < 2 or polyline_length(vs) < 1.0:
            continue
        resampled = resample_polyline(vs, spacing=2.5, smooth_iters=1)
        width = max(w["tags"].get("width_m") or 1.8, 1.0)
        left = offset_polyline(resampled, width * 0.5)
        right = offset_polyline(resampled, -width * 0.5)
        sub = MeshBuild()
        add_ribbon(sub, left, right, hm, y_bias=0.03)
        mat = PATH_MATERIAL.get(cls, "sidewalk_concrete")
        if not sub.is_empty():
            mb_by_mat.setdefault(mat, MeshBuild()).extend(sub)


# ---------------------------------------------------------------------------
# Bridges (deck + parapets), Y from bridges.json (pre-computed, not heightmap).
# ---------------------------------------------------------------------------
def build_bridges(bridges, hm, mb_by_mat, furniture):
    for b in bridges:
        tags = b["tags"]
        if tags.get("kind") == "railway":
            continue  # handled with rails
        vs = b["vertices"]
        if len(vs) < 2:
            continue
        pts2d = [(v["x"], v["z"]) for v in vs]
        ys = [v["y"] for v in vs]
        width = max(tags.get("width_m") or 8.0, 3.0)
        hw = width * 0.5
        left = offset_polyline(pts2d, hw)
        right = offset_polyline(pts2d, -hw)

        def deck_ribbon(l, r, ybase, mat, ybias=0.0):
            sub = MeshBuild()
            n = len(l)
            li, ri = [], []
            vlen = 0.0
            for i in range(n):
                ly = ybase[i] + ybias
                ry = ybase[i] + ybias
                ln = [0.0, 1.0, 0.0]
                li.append(sub.add_vertex(l[i][0], ly, l[i][1], ln))
                ri.append(sub.add_vertex(r[i][0], ry, r[i][1], ln))
            for i in range(n - 1):
                sub.add_quad(li[i], li[i + 1], ri[i + 1], ri[i])
            if not sub.is_empty():
                mb_by_mat.setdefault(mat, MeshBuild()).extend(sub)

        deck_ribbon(left, right, ys, "bridge_deck", 0.0)

        # Parapets: simple raised wall + pipe-rail look along both edges.
        parapet_h = 0.9
        for side_pts in (left, right):
            sub = MeshBuild()
            n = len(side_pts)
            bi, ti = [], []
            for i in range(n):
                by = ys[i]
                ty = ys[i] + parapet_h
                nrm = [0.0, 1.0, 0.0]
                bi.append(sub.add_vertex(side_pts[i][0], by, side_pts[i][1], nrm))
                ti.append(sub.add_vertex(side_pts[i][0], ty, side_pts[i][1], nrm))
            for i in range(n - 1):
                sub.add_quad(bi[i], bi[i + 1], ti[i + 1], ti[i])
                sub.add_quad(ti[i], ti[i + 1], bi[i + 1], bi[i])
            if not sub.is_empty():
                mb_by_mat.setdefault("steel_rusted", MeshBuild()).extend(sub)

        # A couple of ornate lamp posts per bridge end (galena_bridge.md: cobra/acorn lights).
        for pt in (pts2d[0], pts2d[-1]):
            furniture.setdefault("lamp_downtown", []).append([pt[0], hm.sample(*pt), pt[1], 0.0])


# ---------------------------------------------------------------------------
# Rails: ballast + ties (multimesh) + rails, grade crossings with roads.
# ---------------------------------------------------------------------------
RAIL_GAUGE = 1.435
TIE_SPACING = 0.6
BALLAST_WIDTH = 3.0
BALLAST_TOP = 0.20
TIE_TOP = 0.35
RAIL_TOP = 0.50


def build_rails(rail_ways, all_road_ways, hm, mb_by_mat, furniture):
    # crossing detection: sample points where a rail polyline passes within
    # gutter distance of a road polyline (brute force -- both sets are small).
    road_lines = []
    for w in all_road_ways:
        if w["tags"].get("bridge"):
            continue
        cls = w["tags"].get("highway")
        if cls not in DRIVABLE:
            continue
        road_lines.append((way_xz(w), way_half_width(w)))

    for rw in rail_ways:
        pts = [(v["x"], v["z"]) for v in rw["vertices"]]
        ys = [v["y"] for v in rw["vertices"]]
        if len(pts) < 2:
            continue
        left = offset_polyline(pts, BALLAST_WIDTH * 0.5)
        right = offset_polyline(pts, -BALLAST_WIDTH * 0.5)
        sub = MeshBuild()
        li, ri = [], []
        for i in range(len(pts)):
            nrm = [0.0, 1.0, 0.0]
            li.append(sub.add_vertex(left[i][0], ys[i] + BALLAST_TOP, left[i][1], nrm))
            ri.append(sub.add_vertex(right[i][0], ys[i] + BALLAST_TOP, right[i][1], nrm))
        for i in range(len(pts) - 1):
            sub.add_quad(li[i], li[i + 1], ri[i + 1], ri[i])
        if not sub.is_empty():
            mb_by_mat.setdefault("gravel_ballast", MeshBuild()).extend(sub)

        for off in (RAIL_GAUGE * 0.5, -RAIL_GAUGE * 0.5):
            rail_line = offset_polyline(pts, off)
            rsub = MeshBuild()
            rl = offset_polyline(rail_line, 0.035)
            rr = offset_polyline(rail_line, -0.035)
            rli, rri = [], []
            for i in range(len(pts)):
                nrm = [0.0, 1.0, 0.0]
                rli.append(rsub.add_vertex(rl[i][0], ys[i] + RAIL_TOP, rl[i][1], nrm))
                rri.append(rsub.add_vertex(rr[i][0], ys[i] + RAIL_TOP, rr[i][1], nrm))
            for i in range(len(pts) - 1):
                rsub.add_quad(rli[i], rli[i + 1], rri[i + 1], rri[i])
            if not rsub.is_empty():
                mb_by_mat.setdefault("steel_rusted", MeshBuild()).extend(rsub)

        total = polyline_length(pts)
        n_ties = max(1, int(total // TIE_SPACING))
        for i in range(n_ties):
            d = TIE_SPACING * 0.5 + i * TIE_SPACING
            x, z, dx, dz = point_and_dir_at(pts, d)
            yi = min(int(d / max(total, EPS) * (len(ys) - 1)), len(ys) - 1)
            y = ys[yi] + TIE_TOP * 0.5
            ry = math.atan2(dz, dx)
            furniture.setdefault("tie", []).append([x, y, z, ry])

        # grade crossings
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            for road_pts, hw in road_lines:
                for j in range(len(road_pts) - 1):
                    c, d = road_pts[j], road_pts[j + 1]
                    p = line_seg_intersect(a, b, c, d)
                    if p is None:
                        continue
                    ry = ys[min(i, len(ys) - 1)]
                    dirx, dirz = (b[0] - a[0], b[1] - a[1])
                    dl = math.hypot(dirx, dirz) or 1.0
                    dirx, dirz = dirx / dl, dirz / dl
                    perp = (-dirz, dirx)
                    csub = MeshBuild()
                    half_len = BALLAST_WIDTH * 0.6
                    corners = [
                        (p[0] + dirx * half_len + perp[0] * hw, p[1] + dirz * half_len + perp[1] * hw),
                        (p[0] - dirx * half_len + perp[0] * hw, p[1] - dirz * half_len + perp[1] * hw),
                        (p[0] - dirx * half_len - perp[0] * hw, p[1] - dirz * half_len - perp[1] * hw),
                        (p[0] + dirx * half_len - perp[0] * hw, p[1] + dirz * half_len - perp[1] * hw),
                    ]
                    nrm = [0.0, 1.0, 0.0]
                    idx = [csub.add_vertex(c[0], ry + RAIL_TOP + 0.01, c[1], nrm) for c in corners]
                    csub.add_quad(idx[0], idx[1], idx[2], idx[3])
                    if not csub.is_empty():
                        mb_by_mat.setdefault("asphalt_patched", MeshBuild()).extend(csub)
                    furniture.setdefault("crossbuck", []).append([p[0] + perp[0] * (hw + 1.0),
                                                                   hm.sample(p[0], p[1]),
                                                                   p[1] + perp[1] * (hw + 1.0),
                                                                   math.atan2(dirz, dirx)])


def line_seg_intersect(p1, p2, p3, p4):
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / denom
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def end_cap(mb_by_mat, plan, end, hm, material_tag):
    """Flat closure quad at a dead-end (no junction) way end."""
    a = ring_point(plan, "edge", "R", end)
    b = ring_point(plan, "edge", "L", end)
    if a is None or b is None:
        return
    sub = MeshBuild()
    ay = hm.sample(*a) + ROAD_Y_BIAS
    by = hm.sample(*b) + ROAD_Y_BIAS
    an = hm.normal(*a)
    bn = hm.normal(*b)
    ai = sub.add_vertex(a[0], ay, a[1], an)
    bi = sub.add_vertex(b[0], by, b[1], bn)
    # degenerate (zero-area) sliver is fine to skip; a 2-point "cap" has no fill,
    # real closure comes from the ribbon's own end edge already being watertight
    # against the terrain (curb layer below adds the visible stop-edge).
    mb_by_mat.setdefault(material_tag, MeshBuild())


# ---------------------------------------------------------------------------
# Chunking + JSON output
# ---------------------------------------------------------------------------
def chunk_key(x, z):
    return (int(math.floor(x / CHUNK_SIZE)), int(math.floor(z / CHUNK_SIZE)))


def split_mesh_by_chunk(mb: MeshBuild):
    """Splits a triangle soup into per-chunk sub-meshes keyed by triangle centroid."""
    buckets = {}
    for t in range(0, len(mb.indices), 3):
        a, b, c = mb.indices[t], mb.indices[t + 1], mb.indices[t + 2]
        va, vb, vc = mb.verts[a], mb.verts[b], mb.verts[c]
        cx = (va[0] + vb[0] + vc[0]) / 3.0
        cz = (va[2] + vb[2] + vc[2]) / 3.0
        if not in_bounds(cx, cz):
            continue
        key = chunk_key(cx, cz)
        bucket = buckets.setdefault(key, MeshBuild())
        ia = bucket.add_vertex(va[0], va[1], va[2], (va[3], va[4], va[5]), va[6], va[7])
        ib = bucket.add_vertex(vb[0], vb[1], vb[2], (vb[3], vb[4], vb[5]), vb[6], vb[7])
        ic = bucket.add_vertex(vc[0], vc[1], vc[2], (vc[3], vc[4], vc[5]), vc[6], vc[7])
        bucket.indices.extend([ia, ib, ic])
    return buckets


def write_output(mb_by_mat, furniture):
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        if f.endswith(".json"):
            os.remove(os.path.join(OUT_DIR, f))

    chunk_meshes = collections.defaultdict(dict)  # key -> {material: MeshBuild}
    for mat, mb in mb_by_mat.items():
        if mb.is_empty():
            continue
        buckets = split_mesh_by_chunk(mb)
        for key, bucket in buckets.items():
            chunk_meshes[key][mat] = bucket

    chunk_furniture = collections.defaultdict(lambda: collections.defaultdict(list))
    for kind, transforms in furniture.items():
        for t in transforms:
            if not in_bounds(t[0], t[2]):
                continue
            key = chunk_key(t[0], t[2])
            chunk_furniture[key][kind].append(t)

    keys = set(chunk_meshes.keys()) | set(chunk_furniture.keys())
    manifest = []
    total_tris = 0
    for key in sorted(keys):
        cx, cz = key
        meshes_out = []
        for mat, bucket in chunk_meshes.get(key, {}).items():
            if bucket.is_empty():
                continue
            meshes_out.append({
                "material": mat,
                "verts": bucket.verts,
                "indices": bucket.indices,
            })
            total_tris += len(bucket.indices) // 3
        furn_out = {k: v for k, v in chunk_furniture.get(key, {}).items()}
        if not meshes_out and not furn_out:
            continue
        fname = f"chunk_{cx}_{cz}.json"
        with open(os.path.join(OUT_DIR, fname), "w") as f:
            json.dump({"cx": cx, "cz": cz, "meshes": meshes_out, "furniture": furn_out}, f)
        bounds = [cx * CHUNK_SIZE, cz * CHUNK_SIZE, (cx + 1) * CHUNK_SIZE, (cz + 1) * CHUNK_SIZE]
        manifest.append({"cx": cx, "cz": cz, "file": fname, "bounds": bounds})

    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump({"chunk_size": CHUNK_SIZE, "chunks": manifest}, f, indent=0)

    print(f"Wrote {len(manifest)} chunks, {total_tris} triangles total, to {OUT_DIR}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("Loading data...")
    roads = load_json("roads.json")
    bridges = load_json("bridges.json")["bridges"]
    rails = clip_ways_to_bounds(load_json("rails.json")["ways"])
    hm = Heightmap()

    ways = roads["ways"]
    junction_ids = set(j["node_id"] for j in roads["junction_nodes"])
    split_ways = split_at_junctions(ways, junction_ids)
    print(f"  {len(ways)} ways -> {len(split_ways)} after junction split")

    drivable_ways = [w for w in split_ways if w["tags"].get("highway") in DRIVABLE and not w["tags"].get("bridge")]
    print(f"  {len(drivable_ways)} drivable way-segments")

    nodes = build_graph(drivable_ways)
    plans = plan_drivable_ways(drivable_ways, nodes)
    print(f"  {len(plans)} way plans")
    plan_by_way_id = {id(p.way): p for p in plans}

    mb_by_mat = {}
    furniture = {}

    print("Building way surfaces (asphalt/curb/sidewalk)...")
    build_way_surfaces(plans, hm, mb_by_mat)

    print("Building junction geometry...")
    build_junction_geometry(nodes, plan_by_way_id, hm, mb_by_mat)

    print("Building markings...")
    build_markings(plans, hm, mb_by_mat)

    downtown_intersections = find_downtown_intersections(nodes, plan_by_way_id)
    downtown_node_ids = set(n.id for n, _ in downtown_intersections)
    print(f"  {len(downtown_node_ids)} curated downtown intersections")
    build_intersection_markings(nodes, plan_by_way_id, hm, mb_by_mat, furniture)

    print("Building furniture...")
    build_furniture(plans, hm, furniture)
    build_stop_signs(nodes, plan_by_way_id, downtown_node_ids, hm, furniture)

    print("Building paths (footway/cycleway/etc)...")
    build_pathy(split_ways, hm, mb_by_mat)

    print("Building bridges...")
    build_bridges(bridges, hm, mb_by_mat, furniture)

    print("Building rails...")
    build_rails(rails, split_ways, hm, mb_by_mat, furniture)

    print("Chunking + writing output...")
    write_output(mb_by_mat, furniture)


if __name__ == "__main__":
    main()
