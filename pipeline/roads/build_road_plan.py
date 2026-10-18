#!/usr/bin/env python3
"""Builds the Dixon road network build-plan: chunked JSON of triangle soups +
instance-transform lists, consumed by game/roads/tools/build_roads.gd to bake
game/roads/roads.tscn. See docs/roads_notes.md.

Run: cd pipeline/roads && ../../.venv/bin/python build_road_plan.py
"""
import bisect
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
import bridges_composed

OUT_DIR = os.path.join(pc.ROOT, "game", "roads", "_build")
# Bridges are their own baked layer (res://roads/bridges.scn), so a bridge edit rebuilds in seconds
# (build_bridges_only.py) without redoing the road layout.
BRIDGE_OUT_DIR = os.path.join(pc.ROOT, "game", "roads", "_build_bridges")
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
        # double_sided: the analytically-derived single-sided winding for this
        # L/R pair was found (empirically, via --hide=Terrain + a bright
        # diagnostic tint) to backface-cull the entire straight-run asphalt
        # ribbon from normal eye-height viewing angles across the whole map --
        # only junction fans (already double-sided) were ever actually
        # visible. Rather than re-derive the winding under time pressure,
        # double-side this one call; it's the single largest mesh so the
        # perf cost is the most real of any double-siding in this file, but
        # correctness (the road being visible at all) wins here.
        add_ribbon(sub, plan.rings["edge_L"], plan.rings["edge_R"], hm, y_bias=ROAD_Y_BIAS,
                   double_sided=True)
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
                                      "curb_concrete", flip=flip, double_sided=True, close_loop=False)
                ribbon_between_loops(mb_by_mat, curb_out_ring, curb_out_ring, hm, CURB_HEIGHT, -0.05,
                                      "curb_concrete", flip=flip, close_loop=False)

        if plan.has_sidewalk:
            for side in ("L", "R"):
                flip = side == "L"
                sw_in = plan.rings[f"sw_in_{side}"]
                sw_out = plan.rings[f"sw_out_{side}"]
                # Walking surface: double-sided like the junction loops, which always
                # rendered correctly. The single-sided winding derivation here was wrong
                # (same class of bug as the asphalt ribbon), so straight-run sidewalks were
                # backface-culled and only their edge skirts remained visible -- the
                # "sidewalks are only outlined" report.
                ribbon_between_loops(mb_by_mat, sw_in, sw_out, hm, 0.05, 0.05, "sidewalk_concrete",
                                      flip=flip, double_sided=True, close_loop=False)
                # Edge skirts: cosmetic only. They are tagged "sidewalk_edge" so the Godot
                # baker keeps them out of collision -- as collidable geometry they were thin
                # ledges standing proud of the road that the player had to jump over
                # (user report: "outline ribbons projecting upward out of the road surface").
                # Also shortened to stop at terrain level instead of -0.05.
                ribbon_between_loops(mb_by_mat, sw_in, sw_in, hm, 0.05, 0.0, "sidewalk_edge",
                                      flip=flip, double_sided=True, close_loop=False)
                ribbon_between_loops(mb_by_mat, sw_out, sw_out, hm, 0.05, 0.0, "sidewalk_edge",
                                      flip=flip, double_sided=True, close_loop=False)



def split_loop_outside_carriageway(loop_in, loop_out, segs, margin=0.2):
    """Break a junction ring into the runs that lie OUTSIDE the carriageway.

    A junction's sidewalk rings are closed loops around the intersection, so they span the
    mouth of every leg -- laying a raised concrete slab straight across the roadway. The
    player walks into it as a 15-70 cm ledge (user ticket 20260920_232703 at the Dixon arch,
    tagged Roads/Chunk_8_-7 where sidewalk sat at y 22.95-23.77 over asphalt at 22.94-23.09).
    Pavement belongs on the corners; the street mouth is for paint, not kerbstone.
    """
    if loop_in is None or loop_out is None or len(loop_in) != len(loop_out):
        return []
    runs = []
    cur_in, cur_out = [], []
    prev_mid = None
    for a, b in zip(loop_in, loop_out):
        mx, mz = (a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5
        # Testing the ring's points alone is not enough: across a street mouth the ring
        # is often just two points, one on each footpath, both outside the carriageway,
        # joined by a straight span through it. That span rendered as two raised strips
        # across the road (tickets 20260921_002438, 20260921_003127, "supposed to be
        # fixed twice"), so the span between consecutive points is tested too.
        spans_road = (segs and prev_mid is not None and
                      any(_in_carriageway(prev_mid[0] + (mx - prev_mid[0]) * t,
                                          prev_mid[1] + (mz - prev_mid[1]) * t, segs, margin=margin)
                          for t in (0.2, 0.35, 0.5, 0.65, 0.8)))
        if segs and _in_carriageway(mx, mz, segs, margin=margin):
            if len(cur_in) >= 2:
                runs.append((cur_in, cur_out))
            cur_in, cur_out = [], []
        else:
            if spans_road:
                if len(cur_in) >= 2:
                    runs.append((cur_in, cur_out))
                cur_in, cur_out = [], []
            cur_in.append(a)
            cur_out.append(b)
        prev_mid = (mx, mz)
    if len(cur_in) >= 2:
        runs.append((cur_in, cur_out))
    return runs


def build_junction_geometry(nodes, plan_by_way_id, hm, mb_by_mat, carriageway_segs=None):
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
                # Same treatment for the kerb ring: a kerb across the street mouth is a wall.
                for run_a, run_c in split_loop_outside_carriageway(
                        asphalt_loop, curb_out_loop, carriageway_segs):
                    ribbon_between_loops(mb_by_mat, run_a, run_a, hm, ROAD_Y_BIAS, CURB_HEIGHT,
                                          "curb_concrete", double_sided=True, close_loop=False)
                    ribbon_between_loops(mb_by_mat, run_a, run_c, hm, CURB_HEIGHT, CURB_HEIGHT,
                                          "curb_concrete", double_sided=True, close_loop=False)
                    ribbon_between_loops(mb_by_mat, run_c, run_c, hm, CURB_HEIGHT, -0.05,
                                          "curb_concrete", double_sided=True, close_loop=False)
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
                # Only the corner runs; never across a leg's carriageway (see
                # split_loop_outside_carriageway).
                for run_in, run_out in split_loop_outside_carriageway(
                        sw_in_loop, sw_out_loop, carriageway_segs):
                    ribbon_between_loops(mb_by_mat, run_in, run_out, hm, 0.05, 0.05,
                                          "sidewalk_concrete", double_sided=True, close_loop=False)
                    ribbon_between_loops(mb_by_mat, run_in, run_in, hm, 0.05, 0.0,
                                          "sidewalk_edge", double_sided=True, close_loop=False)
                    ribbon_between_loops(mb_by_mat, run_out, run_out, hm, 0.05, 0.0,
                                          "sidewalk_edge", double_sided=True, close_loop=False)


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
# Aerial-traced paved surfaces (parking lots, aprons, service yards)
# ---------------------------------------------------------------------------
def build_aerial_paved(hm, mb_by_mat, carriageway_segs=None):
    """Lays the paved quads extracted from the Google Earth aerial.

    OSM has almost no parking data for downtown Dixon (2 landuse areas in the whole
    aerial) even though the lots are a large share of the visible ground plane, so
    they are traced from the photo instead -- see pipeline/aerial/extract_paved.py.
    Quads are axis-aligned in aerial pixel space and tile exactly, so they are laid
    as flat fills at terrain height. Quads whose centre falls inside a carriageway
    are skipped so a lot never paves over a street.
    """
    path = os.path.join(pc.ROOT, "game", "data", "aerial_paved.json")
    if not os.path.exists(path):
        return 0
    quads = json.load(open(path)).get("quads", [])
    laid = 0
    for q in quads:
        cx = sum(p[0] for p in q) / 4.0
        cz = sum(p[1] for p in q) / 4.0
        if carriageway_segs and _in_carriageway(cx, cz, carriageway_segs, margin=0.0):
            continue
        loop = [(p[0], p[1]) for p in q]
        close_loop_fill(mb_by_mat, loop, hm, ROAD_Y_BIAS, "asphalt_patched_plowed")
        laid += 1
    print(f"  {laid} aerial-traced paved quads ({len(quads) - laid} skipped inside carriageways)")
    return laid

# ---------------------------------------------------------------------------
# Non-drivable paths (footway/cycleway/path/pedestrian/steps)
# ---------------------------------------------------------------------------
PATH_MATERIAL = {
    "footway": "sidewalk_concrete", "pedestrian": "sidewalk_concrete", "steps": "sidewalk_concrete",
    "cycleway": "asphalt_road", "path": "gravel_ballast", "track": "gravel_ballast",
}


def _carriageway_index(drivable_plans):
    """Road centreline segments + their half-widths, for testing whether a point
    lies inside a carriageway."""
    segs = []
    for plan in drivable_plans:
        pts = plan.centerline
        hw = plan.half_w
        for i in range(len(pts) - 1):
            segs.append((pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], hw))
    return segs


_CARRIAGEWAY_GRID = {}
_GRID_CELL = 20.0


def _carriageway_grid(segs):
    """Bucket the carriageway segments into a coarse grid, once per segment list.

    _in_carriageway is called for every ring/path point against every segment in
    the map; the brute-force scan made the road plan take a quarter of an hour.
    """
    key = id(segs)
    entry = _CARRIAGEWAY_GRID.get(key)
    if entry is not None and entry[0] is segs:
        return entry[1]
    grid = {}
    for seg in segs:
        x1, z1, x2, z2, hw = seg
        reach = hw + 1.0  # covers any margin the callers use
        i0 = int(math.floor((min(x1, x2) - reach) / _GRID_CELL))
        i1 = int(math.floor((max(x1, x2) + reach) / _GRID_CELL))
        j0 = int(math.floor((min(z1, z2) - reach) / _GRID_CELL))
        j1 = int(math.floor((max(z1, z2) + reach) / _GRID_CELL))
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                grid.setdefault((i, j), []).append(seg)
    _CARRIAGEWAY_GRID[key] = (segs, grid)
    return grid


def _in_carriageway(px, pz, segs, margin=0.35):
    cell = _carriageway_grid(segs).get((int(math.floor(px / _GRID_CELL)), int(math.floor(pz / _GRID_CELL))))
    if not cell:
        return False
    for x1, z1, x2, z2, hw in cell:
        dx, dz = x2 - x1, z2 - z1
        L = dx * dx + dz * dz
        t = 0.0 if L == 0.0 else max(0.0, min(1.0, ((px - x1) * dx + (pz - z1) * dz) / L))
        if math.hypot(px - (x1 + dx * t), pz - (z1 + dz * t)) <= hw + margin:
            return True
    return False


def build_pathy(ways, hm, mb_by_mat, carriageway_segs=None):
    """Footways/cycleways/paths.

    Segments that fall INSIDE a road carriageway are dropped: OSM maps pedestrian
    crossings as footway ways straight across the street, and building them as
    concrete slabs put raised ribbons across the asphalt that the player had to
    step over (user screenshot at the Dixon arch, 2026-09-20). Real sidewalks stop
    at the curb; a crossing is paint, not a slab. Paint is drawn separately by the
    markings pass, and only where a crossing actually exists.
    """
    for w in ways:
        cls = w["tags"].get("highway")
        if cls not in PATHY or w["tags"].get("bridge"):
            continue
        vs = way_xz(w)
        if len(vs) < 2 or polyline_length(vs) < 1.0:
            continue
        resampled = resample_polyline(vs, spacing=2.5, smooth_iters=1)
        if carriageway_segs:
            kept = []
            runs = []
            for pt in resampled:
                if _in_carriageway(pt[0], pt[1], carriageway_segs):
                    if len(kept) >= 2:
                        runs.append(kept)
                    kept = []
                else:
                    kept.append(pt)
            if len(kept) >= 2:
                runs.append(kept)
            if not runs:
                continue
            # rebuild this way from the surviving runs
            for run in runs:
                _emit_path_ribbon(run, w, hm, mb_by_mat)
            continue
        _emit_path_ribbon(resampled, w, hm, mb_by_mat)


def _emit_path_ribbon(resampled, w, hm, mb_by_mat):
        cls = w["tags"].get("highway")
        width = max(w["tags"].get("width_m") or 1.8, 1.0)
        left = offset_polyline(resampled, width * 0.5)
        right = offset_polyline(resampled, -width * 0.5)
        sub = MeshBuild()
        add_ribbon(sub, left, right, hm, y_bias=0.03, double_sided=True)
        mat = PATH_MATERIAL.get(cls, "sidewalk_concrete")
        if not sub.is_empty():
            mb_by_mat.setdefault(mat, MeshBuild()).extend(sub)


# ---------------------------------------------------------------------------
# Bridges (deck + parapets), Y from bridges.json (pre-computed, not heightmap).
# ---------------------------------------------------------------------------
BRIDGE_MAX_GRADE = 0.08      # approach-ramp grade used to meet the terrain at each deck end
BRIDGE_RAMP_MAX_FRAC = 0.45  # a ramp never takes more than this share of the span
BRIDGE_STEP_M = 4.0


def _smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def bridge_profile(pts2d, ys, end_ground):
    """Resample a bridge centreline and ramp its deck down to the ground at both ends.

    bridges.json carries one flat deck height (pool level + clearance), but the
    approach roads on either bank are built at terrain height, so a flat deck left a
    several-metre step at each end ("deck sits above road and is unconnected",
    ticket 20260921_002558). The deck now blends from the ground height at each end
    to its design height over the shortest run that keeps the grade under
    BRIDGE_MAX_GRADE, never using more than BRIDGE_RAMP_MAX_FRAC of the span.

    Returns (points, ys, arclengths) for the resampled centreline.
    """
    seg = [math.hypot(pts2d[i + 1][0] - pts2d[i][0], pts2d[i + 1][1] - pts2d[i][1])
           for i in range(len(pts2d) - 1)]
    total = sum(seg)
    if total < 1e-6:
        return list(pts2d), list(ys), [0.0] * len(pts2d)
    cum = [0.0]
    for s_ in seg:
        cum.append(cum[-1] + s_)
    n = max(2, int(math.ceil(total / BRIDGE_STEP_M)) + 1)
    pts, out_y, arcs = [], [], []
    for k in range(n):
        d = total * k / (n - 1)
        i = min(bisect.bisect_right(cum, d) - 1, len(seg) - 1)
        t = (d - cum[i]) / seg[i] if seg[i] > 1e-9 else 0.0
        pts.append((pts2d[i][0] + (pts2d[i + 1][0] - pts2d[i][0]) * t,
                    pts2d[i][1] + (pts2d[i + 1][1] - pts2d[i][1]) * t))
        out_y.append(ys[i] + (ys[i + 1] - ys[i]) * t)
        arcs.append(d)
    for end, ground in ((0, end_ground[0]), (1, end_ground[1])):
        rise = out_y[0 if end == 0 else -1] - ground
        ramp = min(abs(rise) / BRIDGE_MAX_GRADE, total * BRIDGE_RAMP_MAX_FRAC)
        if ramp < 1e-6:
            continue
        for k in range(n):
            dist = arcs[k] if end == 0 else total - arcs[k]
            if dist >= ramp:
                continue
            w = _smoothstep(dist / ramp)  # 0 at the end (ground), 1 at the ramp's top
            out_y[k] = ground + (out_y[k] - ground) * w
    return pts, out_y, arcs


def build_bridges(bridges, hm, mb_by_mat, furniture):
    profiles = {}
    skipped = bridges_composed.suppressed()   # bridge ways recorded as duplicates (Bridge Composer's Remove)
    for b in bridges:
        if str(b["id"]) in skipped:
            print(f"  bridge {b['id']} left out: {skipped[str(b['id'])]}")
            continue
        tags = b["tags"]
        if tags.get("kind") == "railway":
            continue  # handled with rails
        vs = b["vertices"]
        if len(vs) < 2:
            continue
        composed = bridges_composed.load(str(b["id"]))
        if composed is not None:
            # Designed in Bridge Composer: its geometry replaces the generated deck.
            result = bridges_composed.build(mb_by_mat, furniture, composed, ground=hm.sample)
            profiles[str(b["id"])] = result["profile"]
            for message in result["warnings"]:
                print(f"  bridge {b['id']}: {message}")
            continue
        raw_pts = [(v["x"], v["z"]) for v in vs]
        ground = [hm.sample(*raw_pts[0]) + ROAD_Y_BIAS, hm.sample(*raw_pts[-1]) + ROAD_Y_BIAS]
        pts2d, ys, arcs = bridge_profile(raw_pts, [v["y"] for v in vs], ground)
        profiles[str(b["id"])] = [[round(a, 2), round(y, 3)] for a, y in zip(arcs, ys)]
        width = max(tags.get("width_m") or 8.0, 3.0)
        hw = width * 0.5
        left = offset_polyline(pts2d, hw)
        right = offset_polyline(pts2d, -hw)

        # The deck is walkable from above and seen from below, so both faces are
        # emitted: a single-sided ribbon from add_quad winds away from the sky
        # (see the note on the asphalt ribbon), which read as a deck with its
        # normal flipped (ticket 20260921_002533).
        sub = MeshBuild()
        li, ri = [], []
        for i in range(len(pts2d)):
            up = [0.0, 1.0, 0.0]
            li.append(sub.add_vertex(left[i][0], ys[i], left[i][1], up))
            ri.append(sub.add_vertex(right[i][0], ys[i], right[i][1], up))
        for i in range(len(pts2d) - 1):
            sub.add_quad(li[i], li[i + 1], ri[i + 1], ri[i])
            sub.add_quad(ri[i], ri[i + 1], li[i + 1], li[i])
        if not sub.is_empty():
            mb_by_mat.setdefault("bridge_deck", MeshBuild()).extend(sub)

        # Parapets: concrete barrier along both edges (the green steel rail on top is
        # landmark dressing; see docs/references/galena_bridge.md).
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
                mb_by_mat.setdefault("curb_concrete", MeshBuild()).extend(sub)

        # A couple of ornate lamp posts per bridge end (galena_bridge.md: cobra/acorn lights).
        for pt in (pts2d[0], pts2d[-1]):
            furniture.setdefault("lamp_downtown", []).append([pt[0], hm.sample(*pt), pt[1], 0.0])

    # Bridges drawn in Bridge Composer that are not OSM ways at all.
    for design in bridges_composed.custom_designs({str(b["id"]) for b in bridges}):
        result = bridges_composed.build(mb_by_mat, furniture, design, ground=hm.sample)
        profiles[str(design["id"])] = result["profile"]
        for message in result["warnings"]:
            print(f"  bridge {design['id']}: {message}")
        print(f"  bridge {design['id']} ({design.get('name') or 'unnamed'}) built from its design")

    # Deck height by distance along each bridge's centreline, for dressing that is
    # built outside this plan (landmarks' Galena Ave bridge piers and railings).
    with open(os.path.join(pc.ROOT, "game", "data", "bridge_profiles.json"), "w") as f:
        json.dump({"profiles": profiles}, f)


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


def write_output(mb_by_mat, furniture, out_dir=None):
    OUT_DIR = out_dir or globals()["OUT_DIR"]   # the road layer by default; the bridge layer when given
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
    build_junction_geometry(nodes, plan_by_way_id, hm, mb_by_mat, _carriageway_index(plans))

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
    # Pass the carriageway extents so footway slabs are clipped out of the street
    # (OSM maps crossings as footways straight across the road).
    build_pathy(split_ways, hm, mb_by_mat, _carriageway_index(plans))

    print("Building aerial-traced paved surfaces...")
    build_aerial_paved(hm, mb_by_mat, _carriageway_index(plans))

    print("Building bridges...")
    bridge_mb, bridge_furniture = {}, {}
    build_bridges(bridges, hm, bridge_mb, bridge_furniture)

    print("Building rails...")
    build_rails(rails, split_ways, hm, mb_by_mat, furniture)

    print("Chunking + writing output...")
    write_output(mb_by_mat, furniture)
    write_output(bridge_mb, bridge_furniture, BRIDGE_OUT_DIR)


if __name__ == "__main__":
    main()
