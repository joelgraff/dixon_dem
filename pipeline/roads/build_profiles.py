#!/usr/bin/env python3
"""Vertical control for the road network (docs/roadway_control_plan.md §3, phase 2).

Every route in game/data/alignments.json gets a profile: PVIs joined by symmetric parabolic
vertical curves (vertical.py), fitted by robust least squares (Huber) to the hydro-flattened
ground, heightmap_play_1m.r32, sampled along its alignment. The network is solved a class at a
time, highest first:

- At a junction the senior route (higher class; then the through route; then the longer) keeps its
  profile: it is solved before the routes of lower classes, which meet it. Routes of the same class
  are solved together, so the junction heights between them are shared unknowns. The tie is at the
  junction's control point, centreline to centreline (JUNCTION_TIE), and the conformed heightmap
  blends the two surfaces across the junction. The plan's edge-of-pavement tie, the senior crown
  carried level through the junction, is kept as an option for phase 3's crown warping: without
  it, on Dixon's hills it leaves a 0.3-0.4 m table where a steep side street crosses a flat one.
- Fixed controls are held: the composed bridge decks (game/data/bridges_composed, elevation and
  grade at each deck end, the deck's rows within it), the top of rail where a route crosses a
  railway at grade, and pins in alignment_overrides.json.
- The class limits in design_standards.json are advisory (decision 2): grades, K and curve lengths
  that exceed them are reported, never forced. A curbed street that comes out flatter than the
  minimum gutter grade is given that grade only where the ground allows it.

Ways that are on no route (footways, paths, steps) get a profile of their own along their OSM
polyline, with a composed bridge deck's height held where they end at one.

Elevations are the top of pavement at the centreline, in game Y. The conformed terrain under a road
is ROAD_SURFACE_M below it (build_heightmap.road_conform reads these profiles).

Writes game/data/profiles.json and game/roads/_build/profile_report.json.
Run: ../../.venv/bin/python build_profiles.py   (about 3 s; build_heightmap.py also runs it)
"""
import hashlib
import json
import math
import os
import sys

import numpy as np
from shapely.geometry import LineString, Point

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import alignment as al  # noqa: E402
import bridges_composed  # noqa: E402
import road_metrics as rm  # noqa: E402
import vertical as vt  # noqa: E402

pc = rm.pc
OUT_PATH = os.path.join(pc.GAME_DATA, "profiles.json")
REPORT_PATH = os.path.join(pc.ROOT, "game", "roads", "_build", "profile_report.json")
OVERRIDES_PATH = os.path.join(HERE, "alignment_overrides.json")

CLASS_RANK = {"service": 1, "local": 2, "collector": 3, "arterial": 4}
ROAD_SURFACE_M = bridges_composed.ROAD_SURFACE_M   # road mesh above the conformed terrain
RAIL_TOP_M = 0.50            # build_road_plan.RAIL_TOP: top of rail above the rail way's y
RAIL_TRUST_M = 0.15          # a drawn rail further than this from ground + RAIL_TOP_M at a crossing is
                             # not trusted (its height is interpolated between far-apart vertices)
CURBED = {"residential", "primary", "secondary", "tertiary", "unclassified",
          "primary_link", "tertiary_link", "living_street"}   # build_road_plan.CURBED

PVI_SPACING_M = 20.0         # longest straight between PVIs
PVI_MIN_GAP_M = 2.5          # control stations closer than this to the last PVI get none of their own
JUNCTION_TIE = "control_point"   # where a junior route meets the senior one: "control_point" (centreline
                             # to centreline at the junction's control point; the conformed heightmap
                             # blends the two surfaces across the junction) or "curb_return" (the
                             # senior's edge-of-pavement height where the junior's centreline crosses
                             # it, the senior crown carried through; needs phase 3's crown warping, as
                             # on Dixon's hills a level crown across a steep side street is a 0.3-0.4 m
                             # table)
CURB_RETURN_CURVE_M = 4.0    # with "curb_return": the vertical curve at a curb-return PVI
DATA_STEP_M = 1.0            # ground sampling along an alignment
HUBER_M = 0.10               # residuals beyond this count linearly, not squared
SMOOTH_W = 20.0              # weight on each grade change: resists fitting DEM noise
SMOOTH_HUBER = 0.005         # ...a change beyond 0.5% costs linearly, so real breaks (an embankment,
                             # a bluff) are followed rather than cut through
PRIOR_W = 1e-3               # keeps a PVI with no data near the ground's trend
HARD_W = 1000.0              # fixed controls and junction ties
GRADE_W = HARD_W * 10.0      # the same for a grade (a 0.1% miss weighs like 1 cm)
DECK_W = 5.0                 # a composed deck's interior rows: shape, not a hard control
CROSSING_GRADE_W = 2.0       # the road is level with the rail plane across a crossing, softly:
                             # the ground decides where the two disagree
REFINE_M = 0.25              # a run of ground misses beyond this...
REFINE_RUN_M = 4.0           # ...at least this long is refined: its curve shortened, or a PVI added
REFINE_CLEAR_M = 30.0        # but not this close to a composed deck end, where the DEM dives into the bank
REFINE_GAP_M = 5.0           # a PVI added on a straight is at least this far from the next
REFINE_ROUNDS = 4            # refine and re-solve at most this many times
MIN_CURVE_M = 4.0            # refinement shortens a vertical curve no further than this
GUTTER_W = 200.0             # pulls a flat curbed straight to the minimum gutter grade
GUTTER_TOL_M = 0.05          # ...but only if the profile moves no more than this to get it
CURB_RETURN_SEARCH_M = 25.0  # how far along a leg its curb-return point is looked for
BRIDGE_SNAP_M = 6.0          # a path ends 'at' a composed deck when its end is this close
DECK_TRUST_M = 1.0           # a composed deck end is a fixed control only within this of its approach's
                             # own ground 5-15 m back; one further off was set for another purpose
                             # (user, 2026-10-18), so the approach keeps to the ground and it is reported
HARD_TOL_M = 0.01            # a fixed control or junction tie missed by more is a conflict
FT = 0.3048


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def fingerprint(paths):
    h = hashlib.sha256()
    for p in paths:
        if os.path.exists(p):
            with open(p, "rb") as handle:
                h.update(handle.read())
    return h.hexdigest()[:16]


def load_json(path):
    with open(path) as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------
class Route:
    """A route from alignments.json, with what the vertical solve needs to know about it."""

    def __init__(self, rec, widths):
        self.id = rec["id"]
        self.rec = rec
        self.cls = rec["class"]
        self.rank = CLASS_RANK.get(self.cls, 0)
        self.highway = rec["highway"]
        self.curbed = self.highway in CURBED
        self.alignment = al.Alignment(rec["pis"], rec["radii"])
        self.length = self.alignment.length
        self.project = self.alignment.projector()
        self.ways = rec["ways"]
        self._widths = [(w["sta"][0], w["sta"][1], widths.get(w["id"], 6.0)) for w in self.ways]
        self.hard = []           # stations that get a PVI of their own
        self.breaks = []         # curb-return stations: a PVI with a short curve
        self.ignore = []         # station ranges with no ground data
        self.controls = []       # (kind, sta, value, weight, derivative, note)
        self.short_curves = []   # PVI stations whose vertical curve refinement has halved
        self.fixed_pvis = None   # alignment_overrides.json: the route's PVI stations, as given
        self.bridge_ends = []    # composed deck ends: {"sta", "side"} (side: where the approach is)
        self.notes = []
        self.rail_off = []       # crossings whose drawn rail is not where the ground says
        self.gutter_m = 0.0      # straights given the minimum gutter grade
        self.decks_not_held = [] # composed deck ends too far off the approach's ground to hold

    def half_width(self, s):
        best, gap = 3.0, float("inf")
        for a, b, w in self._widths:
            d = 0.0 if a <= s <= b else min(abs(s - a), abs(s - b))
            if d < gap:
                best, gap = w / 2.0, d
        return best

    def point(self, s):
        x, z, h = self.alignment.point_at(s)
        return np.array([x, z]), np.array(h)


def load_overrides(path=OVERRIDES_PATH):
    if not os.path.exists(path):
        return {}
    data = load_json(path)
    if data.get("format") != "dixon-alignment-overrides":
        raise ValueError(f"{path}: not a dixon-alignment-overrides file")
    return {o["route"]: o for o in data.get("profile", [])}


def composed_designs():
    """{bridge id: design} for every usable composed bridge that is not suppressed."""
    out = {}
    skipped = bridges_composed.suppressed()
    folder = bridges_composed.COMPOSED_DIR
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        bid = name[:-5]
        if bid in skipped:
            continue
        d = bridges_composed.load(bid)
        if d is not None:
            out[bid] = d
    return out


def deck_rows(design):
    """[(x, z, y), ...] along a composed deck: its elevation rows placed on its centreline."""
    line = LineString(design["centerline"])
    rows = sorted(design["deck"]["elevation"], key=lambda r: r[0])
    total = line.length
    out = []
    for t, y in rows:
        p = line.interpolate(min(max(t, 0.0), total))
        out.append((p.x, p.y, float(y)))
    return out


def rail_lines(rails):
    """(LineString, ys, cumulative arc) for every rail way at grade (bridges carry no crossings)."""
    out = []
    for w in rails["ways"]:
        if w["tags"].get("bridge"):
            continue
        pts = [(v["x"], v["z"]) for v in w["vertices"]]
        if len(pts) < 2:
            continue
        ys = np.array([v["y"] for v in w["vertices"]], dtype=np.float64)
        arc = rm.stations(pts)
        out.append((LineString(pts), ys, arc, w["id"]))
    return out


def approach_ground(r, sta, side, surface):
    """The road surface on the ground 5-15 m back along the approach from a deck end at `sta`
    (`side`: the approach lies at stations below it, -1, or above, +1)."""
    s = sta + side * np.arange(5.0, 15.1, 1.0)
    s = s[(s >= 0) & (s <= r.length)]
    if not s.size or surface is None:
        return float("nan")
    pts = np.array([r.alignment.point_at(v)[:2] for v in s])
    return float(np.nanmedian(surface.sample(pts[:, 0], pts[:, 1]))) + ROAD_SURFACE_M


def trust_deck_end(r, sta, side, y, bid, surface):
    """Whether a composed deck's end at `sta` is held as a fixed control (see DECK_TRUST_M)."""
    g = approach_ground(r, sta, side, surface)
    if np.isfinite(g) and abs(y - g) > DECK_TRUST_M:
        r.decks_not_held.append({"bridge": bid, "sta": round(sta, 2), "deck_y": round(y, 2),
                                 "deck_minus_approach_ground_m": round(y - g, 2)})
        return False
    return True


def attach_controls(routes, designs, rails, roads, overrides, surface=None):
    """Bridge decks, rail crossings and pins as each route's fixed controls and ignored ranges."""
    by_id = {r.id: r for r in routes}
    bridge_ways = {w["id"]: w for w in roads["ways"] if w["tags"].get("bridge")}
    used_designs = set()
    for r in routes:
        for b in r.rec["bridges"]:
            bid = str(b["way_id"])
            design = designs.get(bid)
            if design is None:
                # an OSM bridge with no composed design: its deck is built from the ground at its ends,
                # so the profile only spans it (no ground data from the river below)
                w = bridge_ways.get(b["way_id"])
                if w is not None:
                    st = r.project(np.array([(v["x"], v["z"]) for v in w["vertices"]]))[0]
                    r.ignore.append((float(st.min()), float(st.max())))
                else:
                    r.ignore.append(tuple(b["sta"]))
                continue
            used_designs.add(bid)
            rows = deck_rows(design)
            pts = np.array([(x, z) for x, z, _ in rows])
            st, _, dist = r.project(pts)
            ys = np.array([y for _, _, y in rows])
            order = np.argsort(st)
            st, ys, dist = st[order], ys[order], dist[order]
            if dist.max() > 5.0:
                r.notes.append(f"bridge {bid}: deck centreline up to {dist.max():.1f} m off the alignment")
            lo, hi = float(st[0]), float(st[-1])
            r.ignore.append((lo, hi))      # the river below a deck is not ground data
            held = []
            for s, y, k, side in ((lo, ys[0], 1, -1), (hi, ys[-1], -2, 1)):
                if not trust_deck_end(r, s, side, float(y), bid, surface):
                    continue
                held.append(side)
                r.hard.append(s)
                r.controls.append(("deck_end", s, float(y), HARD_W, False, f"bridge {bid} deck end"))
                # the deck's grade at its end, in the route's stationing
                i0, i1 = (0, 1) if k == 1 else (-2, -1)
                ds = st[i1] - st[i0]
                if ds > 0.5:
                    g = (ys[i1] - ys[i0]) / ds
                    r.controls.append(("deck_grade", s, float(g), GRADE_W, True, f"bridge {bid} deck end grade"))
                r.bridge_ends.append({"sta": round(s, 2), "side": side, "bridge": bid})
            if len(held) == 2:
                for s, y in zip(st[1:-1], ys[1:-1]):
                    r.controls.append(("deck", float(s), float(y), DECK_W, False, f"bridge {bid} deck"))

        # a route that ends at the end of a composed deck that is not on it (a track at a path
        # bridge) meets the deck's height there, as a path does
        for bid, design in designs.items():
            if any(str(b["way_id"]) == bid for b in r.rec["bridges"]):
                continue
            line, rows = design["centerline"], sorted(design["deck"]["elevation"], key=lambda q: q[0])
            for (dx, dz), dy in ((line[0], rows[0][1]), (line[-1], rows[-1][1])):
                for s_end, side in ((0.0, 1), (r.length, -1)):
                    p, _ = r.point(s_end)
                    if (p[0] - dx) ** 2 + (p[1] - dz) ** 2 > BRIDGE_SNAP_M ** 2:
                        continue
                    used_designs.add(bid)
                    if trust_deck_end(r, s_end, side, float(dy), bid, surface):
                        r.controls.append(("deck_end", s_end, float(dy), HARD_W, False, f"bridge {bid} deck end"))
                        r.bridge_ends.append({"sta": round(s_end, 2), "side": side, "bridge": bid})

        # railway crossings at grade: the road meets the top of rail, level with the rail plane
        stas, pts, dirs = r.alignment.sample(0.5)
        line = LineString(pts)
        for rline, rys, rarc, rid in rails:
            if not line.intersects(rline):
                continue
            hit = line.intersection(rline)
            for p in getattr(hit, "geoms", [hit]):
                if not isinstance(p, Point):
                    continue
                s = float(r.project(np.array([[p.x, p.y]]))[0][0])
                t = rline.project(p)
                y = float(np.interp(t, rarc, rys))
                note = f"rail {rid} grade crossing"
                if surface is not None:
                    ground = float(surface.sample([p.x], [p.y])[0])
                    if np.isfinite(ground) and abs(y - ground) > RAIL_TRUST_M:
                        r.notes.append(f"rail {rid} at sta {s:.1f}: drawn {y - ground:+.2f} m off the ground; "
                                       f"top of rail taken as ground + {RAIL_TOP_M} m")
                        r.rail_off.append({"rail": rid, "sta": round(s, 2), "drawn_off_ground_m": round(y - ground, 2),
                                           "at": [round(p.x, 1), round(p.y, 1)]})
                        y = ground
                k = int(np.clip(np.searchsorted(rarc, t) - 1, 0, len(rarc) - 2))
                c = np.array(rline.coords)
                seg = c[k + 1] - c[k]
                seg_len = max(float(np.hypot(*seg)), 1e-6)
                g_rail = (rys[k + 1] - rys[k]) / seg_len
                _, h = r.point(s)
                g = g_rail * float(np.dot(h, seg / seg_len))
                r.controls.append(("rail", s, y + RAIL_TOP_M, HARD_W, False, note))
                r.controls.append(("rail_grade", s, g, CROSSING_GRADE_W, True, note))
                r.hard.append(s)

        o = overrides.get(r.id)
        if o:
            if o.get("pvi_stations"):
                r.fixed_pvis = sorted({0.0, r.length} | {float(v) for v in o["pvi_stations"] if 0 < v < r.length})
            for a, b in o.get("ignore_ground", []):
                r.ignore.append((float(a), float(b)))
            for pin in o.get("pins", []):
                r.controls.append(("pin", float(pin["sta"]), float(pin["elevation"]), HARD_W, False,
                                   pin.get("note", "pinned")))
                if pin.get("grade") is not None:
                    r.controls.append(("pin_grade", float(pin["sta"]), float(pin["grade"]), GRADE_W, True,
                                       pin.get("note", "pinned grade")))
                r.hard.append(float(pin["sta"]))
    unknown = sorted(set(overrides) - set(by_id))
    return used_designs, unknown


def junction_ties(routes, junctions, crown, mode=None):
    """For each junction, the senior leg and a tie for every other leg (see JUNCTION_TIE).

    The senior leg is the higher class, then the through route, then the longer. Returns
    [{"node", "major", "major_sta", "ties": [(minor id, minor sta, major sta, drop)], "legs"}]:
    the minor route's top of pavement at `minor sta` equals the major's at `major sta` less
    `drop` (its crown fall to the pavement edge; 0 at the control point)."""
    mode = mode or JUNCTION_TIE
    by_id = {r.id: r for r in routes}
    out = []
    for j in junctions:
        legs = [(by_id[l["route"]], float(l["sta"]), l["through"], l["heading_deg"])
                for l in j["legs"] if l["route"] in by_id]
        if len({r.id for r, *_ in legs}) < 2:
            continue
        major = max(legs, key=lambda l: (l[0].rank, l[2], l[0].length, l[0].id))
        M, sM = major[0], major[1]
        hwM = M.half_width(sM)
        ties = []
        M.hard.append(sM)
        for r, s, through, heading in legs:
            if r is M:
                continue
            if mode == "control_point":
                ties.append((r.id, s, sM, 0.0))
                r.hard.append(s)
                continue
            dirs = (1, -1) if through else ((1,) if s < r.length / 2 else (-1,))
            for d in dirs:
                u = np.arange(0.0, CURB_RETURN_SEARCH_M + 1e-9, 0.25)
                ss = np.clip(s + d * u, 0.0, r.length)
                pts = np.array([r.alignment.point_at(v)[:2] for v in ss])
                sMp, _, dist = M.project(pts)
                k = np.flatnonzero(dist >= hwM)
                if k.size:
                    k = k[0]
                    ties.append((r.id, float(ss[k]), float(sMp[k]), crown * hwM))
                    r.breaks.append(float(ss[k]))
                else:            # never leaves the senior pavement (a merge): centreline to centreline
                    ties.append((r.id, s, sM, 0.0))
                    r.hard.append(s)
        out.append({"node": j["node_id"], "major": M.id, "major_sta": sM, "ties": ties,
                    "legs": [(r.id, s, h) for r, s, _, h in legs]})
    return out


# ---------------------------------------------------------------------------------------------
# Solve
# ---------------------------------------------------------------------------------------------
def _in_ranges(s, ranges):
    m = np.zeros(len(s), dtype=bool)
    for a, b in ranges:
        m |= (s >= min(a, b)) & (s <= max(a, b))
    return m


def ground_data(r, surface):
    stas, pts, _ = r.alignment.sample(DATA_STEP_M)
    y = surface.sample(pts[:, 0], pts[:, 1]) + ROAD_SURFACE_M
    ok = np.isfinite(y) & ~_in_ranges(stas, r.ignore)
    return stas, y, ok


def _prior(stations, s_data, y_data, controls):
    if len(s_data):
        return np.interp(stations, s_data, y_data)
    ys = [c[2] for c in controls if not c[4]]
    return np.full(len(stations), float(np.mean(ys)) if ys else 0.0)


def refine(tier, profiles, rows_data):
    """Lets a profile follow a sustained miss of the ground (a bluff, an embankment): in every run
    of REFINE_RUN_M or more beyond REFINE_M, the vertical curve the worst miss lies on is halved
    (to MIN_CURVE_M at the least), or, on a straight, a PVI is added there. Returns how many."""
    changed = 0
    for r in tier:
        if r.fixed_pvis:
            continue
        stas, y, ok = rows_data[r.id]
        p = profiles[r.id]
        res = np.where(ok, np.abs(p.elevation(stas) - y), 0.0)
        clear = np.ones(len(stas), dtype=bool)
        for be in r.bridge_ends:
            clear &= np.abs(stas - be["sta"]) > REFINE_CLEAR_M
        for i0, i1 in rm.runs((res > REFINE_M) & clear):
            if (stas[i1 - 1] - stas[i0]) < REFINE_RUN_M:
                continue
            s = float(stas[i0 + int(np.argmax(res[i0:i1]))])
            k = int(np.argmin(np.abs(p.s - s)))
            if 0 < k < len(p.s) - 1 and abs(p.s[k] - s) <= p.L[k] / 2 and p.L[k] > MIN_CURVE_M:
                r.short_curves.append(float(p.s[k]))
                changed += 1
            elif np.min(np.abs(p.s - s)) >= REFINE_GAP_M:
                r.hard.append(s)
                changed += 1
    return changed


def layout(r):
    """A route's PVI stations and curve lengths, refinements included."""
    if r.fixed_pvis:
        S = np.array(r.fixed_pvis)
        return S, vt.curve_lengths(S)
    S = vt.pvi_stations(r.length, r.hard + r.breaks, PVI_SPACING_M, PVI_MIN_GAP_M)
    L = vt.curve_lengths(S)
    for s in r.breaks:
        k = int(np.argmin(np.abs(S - s)))
        if abs(S[k] - s) < 0.5:
            L[k] = min(L[k], CURB_RETURN_CURVE_M)
    for s in r.short_curves:
        k = int(np.argmin(np.abs(S - s)))
        if abs(S[k] - s) < 0.5:
            L[k] = max(L[k] / 2.0, min(MIN_CURVE_M, L[k]))
    return S, L


def solve_tier(tier, solved, ties, surface, standards):
    """Solve one class's routes together, the higher classes already fixed in `solved`."""
    gmin = standards["profile"]["min_gutter_grade"]
    keys = {r.id for r in tier}
    rows_data = {}

    def build(gutter):
        """The tier's system; `gutter` {route: [(straight k, grade), ...]} pulls flat straights."""
        net = vt.Network()
        for r in tier:
            S, L = layout(r)
            net.add(r.id, S, L)
            stas, y, ok = rows_data[r.id]
            net.rows(r.id, stas[ok], y[ok], 1.0, huber=HUBER_M)
            net.smoothing(r.id, SMOOTH_W, huber=SMOOTH_HUBER)
            net.prior(r.id, _prior(S, stas[ok], y[ok], r.controls), PRIOR_W)
            for kind, s, v, w, deriv, _ in r.controls:
                net.rows(r.id, [s], [v], w, derivative=deriv)
            for k, g in gutter.get(r.id, []):
                # a straight's grade is constant between its PVIs: one row at its middle
                net.rows(r.id, [(S[k] + S[k + 1]) / 2], [g], GUTTER_W, derivative=True)
        for j in ties:
            for minor, s_m, s_M, drop in j["ties"]:
                if minor not in keys:
                    continue
                if j["major"] in keys:
                    net.tie([(minor, s_m, 1.0, False), (j["major"], s_M, -1.0, False)], -drop, HARD_W)
                elif j["major"] in solved:
                    yM = float(solved[j["major"]].elevation([s_M])[0])
                    net.rows(minor, [s_m], [yM - drop], HARD_W)
        return net

    for r in tier:
        rows_data[r.id] = ground_data(r, surface)
    profiles = build({}).solve()
    for _ in range(REFINE_ROUNDS):
        if not refine(tier, profiles, rows_data):
            break
        profiles = build({}).solve()

    # minimum gutter grade on curbed streets, where the ground allows it: each flat straight is
    # pulled to the minimum in the direction it already falls, and a route keeps the pull only if
    # its profile moves no more than GUTTER_TOL_M; otherwise it is reported as needing a sawtooth
    # gutter (phase 3's cross-section)
    gutter, flat = {}, {}
    for r in tier:
        if not r.curbed:
            continue
        p = profiles[r.id]
        g = p.grades()
        mid = (p.s[:-1] + p.s[1:]) / 2
        k = np.flatnonzero((np.abs(g) < gmin) & ~_in_ranges(mid, r.ignore))
        if k.size:
            gutter[r.id] = [(int(i), (1.0 if g[i] >= 0 else -1.0) * gmin) for i in k]
    if gutter:
        trial = build(gutter).solve()
        kept = {}
        for rid, items in gutter.items():
            stas = rows_data[rid][0]
            moved = np.max(np.abs(trial[rid].elevation(stas) - profiles[rid].elevation(stas)))
            (kept if moved <= GUTTER_TOL_M else flat)[rid] = items
        if kept:
            profiles = build(kept).solve()
        for rid, items in kept.items():
            by = {r.id: r for r in tier}[rid]
            by.gutter_m = float(sum(profiles[rid].s[k + 1] - profiles[rid].s[k] for k, _ in items))
    return profiles, rows_data, flat


def check(routes, profiles, ties, rows_data, flat, standards):
    """The design-check report: control and tie misses (hard), class limits (advisory)."""
    conflicts = []
    for r in routes:
        p = profiles.get(r.id)
        if p is None:
            continue
        for kind, s, v, w, deriv, note in r.controls:
            if w < HARD_W:
                continue
            got = float((p.grade if deriv else p.elevation)([s])[0])
            tol = 0.001 if deriv else HARD_TOL_M
            if abs(got - v) > tol:
                conflicts.append({"route": r.id, "kind": kind, "sta": round(s, 2), "want": round(v, 4),
                                  "got": round(got, 4), "note": note})
    tie_err = []
    for j in ties:
        pM = profiles.get(j["major"])
        for minor, s_m, s_M, drop in j["ties"]:
            pm = profiles.get(minor)
            if pM is None or pm is None:
                continue
            e = float(pm.elevation([s_m])[0] - (pM.elevation([s_M])[0] - drop))
            tie_err.append(abs(e))
            if abs(e) > HARD_TOL_M:
                conflicts.append({"route": minor, "kind": "junction", "node": j["node"], "sta": round(s_m, 2),
                                  "major": j["major"], "miss_m": round(e, 3)})

    advisory = []
    totals = {"grade_over_class_max_m": 0.0, "curves_below_min_k": 0, "curves_shorter_than_min": 0,
              "flat_curbed_m": 0.0}
    resid = []
    lmin = standards["profile"]["min_vertical_curve_ft"] * FT
    for r in routes:
        p = profiles.get(r.id)
        if p is None:
            continue
        spec = standards["classes"].get(r.cls, {})
        stas, y, ok = rows_data[r.id]
        res = p.elevation(stas) - y
        resid.append(res[ok])
        g = p.grade(stas)
        over = (np.abs(g) > spec.get("max_grade", 1.0)) & ~_in_ranges(stas, r.ignore)
        over_m = float(over.sum() * DATA_STEP_M)
        low_k, short = [], 0
        for c in p.curves():
            kmin = spec.get("k_crest_ft" if c["kind"] == "crest" else "k_sag_ft", 0) * FT
            if c["K"] < kmin and abs(c["A"]) > 0.005:
                low_k.append({"sta": round(c["sta"], 1), "kind": c["kind"], "K": round(c["K"], 2),
                              "K_min": round(kmin, 2), "A_pct": round(c["A"] * 100, 2)})
            if 0 < c["length"] < lmin and abs(c["A"]) > 0.005:
                short += 1
        flat_m = 0.0
        if r.id in flat:
            flat_m = float(sum(p.s[k + 1] - p.s[k] for k, _ in flat[r.id]))
        totals["grade_over_class_max_m"] += over_m
        totals["curves_below_min_k"] += len(low_k)
        totals["curves_shorter_than_min"] += short
        totals["flat_curbed_m"] += flat_m
        if over_m or low_k or flat_m:
            advisory.append({"route": r.id, "name": r.rec.get("name"), "class": r.cls,
                             "max_grade_pct": round(float(np.max(np.abs(g[~_in_ranges(stas, r.ignore)]),
                                                                 initial=0.0)) * 100, 1),
                             "grade_over_class_max_m": over_m, "low_k_curves": low_k[:10],
                             "flat_curbed_m (sawtooth gutter needed)": round(flat_m, 1)})
    resid = np.abs(np.concatenate(resid)) if resid else np.zeros(1)
    totals = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in totals.items()}
    return {
        "fit_to_ground_m": {"p50": round(float(np.percentile(resid, 50)), 3),
                            "p90": round(float(np.percentile(resid, 90)), 3),
                            "p99": round(float(np.percentile(resid, 99)), 3),
                            "max": round(float(resid.max()), 3),
                            "length_over_0.30m_m": round(float((resid > 0.30).sum() * DATA_STEP_M), 1)},
        "junction_tie_miss_m": {"max": round(max(tie_err, default=0.0), 4), "ties": len(tie_err)},
        "conflicts": conflicts,
        "advisory_totals": totals,
        "advisory": sorted(advisory, key=lambda a: -a["grade_over_class_max_m"]),
    }


def path_profiles(roads, route_way_ids, designs, surface):
    """Profiles of the ways that are on no route, each on its own along its OSM polyline."""
    anchors = []
    for bid, d in designs.items():
        line, rows = d["centerline"], sorted(d["deck"]["elevation"], key=lambda r: r[0])
        anchors += [(line[0][0], line[0][1], float(rows[0][1])), (line[-1][0], line[-1][1], float(rows[-1][1]))]
    net = vt.Network()
    meta, skipped = {}, []
    for w in roads["ways"]:
        t = w["tags"]
        if not t.get("highway") or t.get("bridge") or w["id"] in route_way_ids:
            continue
        pts = np.array([(v["x"], v["z"]) for v in w["vertices"]])
        arc = rm.stations(pts)
        L = float(arc[-1])
        if L < 2.0:
            continue
        ds = np.linspace(0.0, L, max(2, int(math.ceil(L / DATA_STEP_M)) + 1))
        xs, zs, _ = rm.along(pts, arc, ds)
        y = surface.sample(xs, zs) + ROAD_SURFACE_M
        ok = np.isfinite(y)
        ends = {}
        for key, (px, pz), s in (("start", pts[0], 0.0), ("end", pts[-1], L)):
            for ax, az, ay in anchors:
                if (px - ax) ** 2 + (pz - az) ** 2 <= BRIDGE_SNAP_M ** 2:
                    ends[key] = ay
        for k in list(ends):
            back = (ds >= 5.0) & (ds <= 15.0) if k == "start" else (ds >= L - 15.0) & (ds <= L - 5.0)
            g = float(np.nanmedian(y[back & ok])) if (back & ok).any() else float("nan")
            if np.isfinite(g) and abs(ends[k] - g) > DECK_TRUST_M:
                skipped.append((str(w["id"]), {"end": k, "deck_y": round(ends[k], 2),
                                               "deck_minus_approach_ground_m": round(ends[k] - g, 2)}))
                del ends[k]
        if not ok.any() and not ends:
            continue
        key = str(w["id"])
        S = vt.pvi_stations(L, (), PVI_SPACING_M, PVI_MIN_GAP_M)
        net.add(key, S)
        net.rows(key, ds[ok], y[ok], 1.0, huber=HUBER_M)
        net.smoothing(key, SMOOTH_W, huber=SMOOTH_HUBER)
        net.prior(key, np.interp(S, ds[ok], y[ok]) if ok.any() else np.full(len(S), np.mean(list(ends.values()))),
                  PRIOR_W)
        for k, ay in ends.items():
            net.rows(key, [0.0 if k == "start" else L], [ay], HARD_W)
        meta[key] = {"length": round(L, 2), "anchored_ends": sorted(ends)}
    profiles = net.solve() if meta else {}
    return profiles, meta, skipped


def solve(surface=None, standards=None, alignments=None, roads=None, rails=None, designs=None,
          overrides=None):
    standards = standards or rm.load_standards()
    alignments = alignments or load_json(os.path.join(pc.GAME_DATA, "alignments.json"))
    roads = roads or load_json(os.path.join(pc.GAME_DATA, "roads.json"))
    rails = rails or load_json(os.path.join(pc.GAME_DATA, "rails.json"))
    designs = composed_designs() if designs is None else designs
    overrides = load_overrides() if overrides is None else overrides
    if surface is None:
        surface = rm.Surface(os.path.join(pc.GAME_DATA, "heightmap_play_1m.r32"))
    crown = standards["cross_section"]["crown"]

    widths = {w["id"]: w["tags"].get("width_m") or 6.0 for w in roads["ways"]}
    routes = [Route(rec, widths) for rec in alignments["routes"]]
    used_designs, unknown = attach_controls(routes, designs, rail_lines(rails), roads, overrides, surface)
    ties = junction_ties(routes, alignments["junctions"], crown)

    profiles, rows_data, flat = {}, {}, {}
    for rank in sorted({r.rank for r in routes}, reverse=True):
        tier = [r for r in routes if r.rank == rank]
        p, d, f = solve_tier(tier, profiles, ties, surface, standards)
        profiles.update(p)
        rows_data.update(d)
        flat.update(f)

    route_way_ids = {w["id"] for r in routes for w in r.ways}
    paths, path_meta, path_skipped = path_profiles(roads, route_way_ids, designs, surface)
    report = check(routes, profiles, ties, rows_data, flat, standards)
    report["unknown_override_routes"] = unknown
    report["deck_ends_not_held"] = [dict(route=r.id, **d) for r in routes for d in r.decks_not_held] + [
        dict(path=k, **d) for k, d in path_skipped]
    report["composed_bridges_on_routes"] = sorted(used_designs)

    # painting order for the conformed heightmap: lowest first, so the senior route's crown is on top
    order = sorted(routes, key=lambda r: (r.rank, r.length, r.id))
    paint = {r.id: i for i, r in enumerate(order)}
    junctions = []
    cps = {jj["node_id"]: (jj["x"], jj["z"]) for jj in alignments["junctions"]}
    for j in ties:
        x, z = cps[j["node"]]
        junctions.append({"node": j["node"], "x": x, "z": z, "major": j["major"],
                          "routes": sorted({rid for rid, _, _ in j["legs"]})})

    doc = {
        "format": "dixon-profiles", "version": 1,
        "_about": "Vertical alignments (build_profiles.py, docs/roadway_control_plan.md §3). pvis: "
                  "[station m, elevation (game Y, top of pavement at the centreline), vertical curve "
                  "length m]. The conformed terrain is road_surface_m below the profile.",
        "inputs": {"alignments.json+bridges_composed+rails.json+alignment_overrides.json": fingerprint(
            [os.path.join(pc.GAME_DATA, "alignments.json"), os.path.join(pc.GAME_DATA, "rails.json"),
             OVERRIDES_PATH] + [bridges_composed.path_for(b) for b in sorted(designs)])},
        "road_surface_m": ROAD_SURFACE_M,
        "crown": crown,
        "routes": {r.id: {"pvis": profiles[r.id].to_json(), "paint": paint[r.id],
                          **({"bridge_ends": r.bridge_ends} if r.bridge_ends else {})}
                   for r in routes if r.id in profiles},
        "paths": {k: {"pvis": p.to_json(), **path_meta[k]} for k, p in paths.items()},
        "junctions": junctions,
    }
    report["routes"] = len(doc["routes"])
    report["paths"] = len(doc["paths"])
    report["pvis"] = sum(len(v["pvis"]) for v in doc["routes"].values())
    report["controls"] = {k: sum(1 for r in routes for c in r.controls if c[0] == k)
                          for k in ("deck_end", "deck_grade", "deck", "rail", "rail_grade", "pin")}
    report["notes"] = {r.id: r.notes for r in routes if r.notes}
    report["min_gutter_grade_given"] = {"routes": sum(1 for r in routes if r.gutter_m),
                                        "length_m": round(sum(r.gutter_m for r in routes), 1)}
    report["rails_off_ground_at_crossings"] = [dict(route=r.id, **c) for r in routes for c in r.rail_off]
    return doc, report


def write(doc, report):
    with open(OUT_PATH, "w") as handle:
        json.dump(doc, handle, separators=(",", ":"))
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as handle:
        json.dump(report, handle, indent=1)


def summary(report):
    return {k: v for k, v in report.items()
            if k not in ("advisory", "conflicts", "notes", "rails_off_ground_at_crossings")} | {
        "rails_off_ground_at_crossings": len(report["rails_off_ground_at_crossings"]),
        "conflicts": len(report["conflicts"])}


# ---------------------------------------------------------------------------------------------
# Conform samples: what build_heightmap.road_conform paints
# ---------------------------------------------------------------------------------------------
CONFORM_STEP_M = 0.5
BRIDGE_EXTEND_M = 3.0          # a conformed road runs this far onto a bridge, covering the abutment cells
BRIDGE_APPROACH_M = 40.0       # near a composed deck's end the section is level and wide...
BRIDGE_APPROACH_WIDE_M = 6.0   # ...reaching this far past the pavement edge, to the sidewalks


def _densify(pts, step):
    arc = rm.stations(pts)
    ds = np.linspace(0.0, arc[-1], max(2, int(math.ceil(arc[-1] / step)) + 1))
    xs, zs, _ = rm.along(pts, arc, ds)
    return np.column_stack([xs, zs]), ds


def _approach(d):
    """(camber scale, extra level width) at distance d from a composed deck's end along an approach."""
    f = smoothstep(np.asarray(d) / BRIDGE_APPROACH_M)
    return f, BRIDGE_APPROACH_WIDE_M * (1.0 - f)


def conform_strips(doc=None, alignments=None, roads=None):
    """The samples road_conform paints, in game x/z: one strip per route and per path.

    Each strip: {"key", "order", "xz" (m, 2), "y" (top of pavement), "hw", "extra", "camber",
    "sta"}. Routes are sampled along their design ways (templates.design_roads: the route
    alignments the road mesh is built on), half as wide as their templates, their heights read
    from the route's profile at the station each sample projects to. `roads` defaults to the
    design roads; bridges and paths keep their OSM lines."""
    doc = doc or load_json(OUT_PATH)
    alignments = alignments or load_json(os.path.join(pc.GAME_DATA, "alignments.json"))
    if roads is None:
        import templates
        roads, _ = templates.design_roads(load_json(os.path.join(pc.GAME_DATA, "roads.json")), alignments)
    ways = {w["id"]: w for w in roads["ways"]}
    recs = {r["id"]: r for r in alignments["routes"]}
    from build_road_plan import VALID_BOUNDS
    x0b, z0b, x1b, z1b = VALID_BOUNDS
    strips = []
    npaths = len(doc["paths"])

    cand = {}
    projectors, profiles = {}, {}
    for rid, rd in doc["routes"].items():
        rec = recs.get(rid)
        if rec is None:
            continue
        projectors[rid] = al.Alignment(rec["pis"], rec["radii"]).projector()
        profiles[rid] = vt.Profile.from_json(rd["pvis"])
        for w in rec["ways"]:
            cand.setdefault(w["id"], []).append((rid, w["sta"]))
    acc = {rid: {"xz": [], "sta": [], "hw": []} for rid in profiles}
    for wid, items in cand.items():
        w = ways.get(wid)
        if w is None or w["tags"].get("bridge"):
            continue
        pts = np.array([(v["x"], v["z"]) for v in w["vertices"]])
        if len(pts) < 2:
            continue
        xz, ds = _densify(pts, CONFORM_STEP_M)
        tag_hw = (w["tags"].get("width_m") or 6.0) / 2.0
        hw_at = np.interp(ds, rm.stations(pts), [v.get("hw", tag_hw) for v in w["vertices"]])
        # past the play heightmap there is no route (it ends at the edge): a sample there would
        # take the clamped end station's height and feather it back over the edge rows
        keep = (xz[:, 0] >= x0b) & (xz[:, 0] <= x1b) & (xz[:, 1] >= z0b) & (xz[:, 1] <= z1b)
        if keep.sum() < 2:
            continue
        xz, hw_at = xz[keep], hw_at[keep]
        best = np.full(len(xz), np.inf)
        pick = np.full(len(xz), -1)
        stas = np.zeros(len(xz))
        proj = [projectors[rid](xz) for rid, _ in items]
        # a sample belongs to the nearest route that has this way at about that station; the
        # recorded station range can be wrong on a looping route (its vertices project onto the
        # wrong lap), so a sample no route's range takes goes to the nearest route outright
        for n, ((rid, rng), (s, _, d)) in enumerate(zip(items, proj)):
            inside = (s >= rng[0] - 10.0) & (s <= rng[1] + 10.0)
            better = inside & (d < best)
            best[better], pick[better], stas[better] = d[better], n, s[better]
        free = pick < 0
        for n, (s, _, d) in enumerate(proj):
            better = free & (d < best) & (d < 3.0)
            best[better], pick[better], stas[better] = d[better], n, s[better]
        for n, (rid, _) in enumerate(items):
            m = pick == n
            if m.any():
                acc[rid]["xz"].append(xz[m])
                acc[rid]["sta"].append(stas[m])
                acc[rid]["hw"].append(hw_at[m])
    # each route runs BRIDGE_EXTEND_M onto its bridges, so the cells at the abutment are covered
    for rid, rd in doc["routes"].items():
        rec = recs.get(rid)
        if rec is None:
            continue
        for b in rec["bridges"]:
            w = ways.get(b["way_id"])
            if w is None:
                continue
            pts = np.array([(v["x"], v["z"]) for v in w["vertices"]])
            xz, ds = _densify(pts, CONFORM_STEP_M)
            m = (ds <= BRIDGE_EXTEND_M) | (ds >= ds[-1] - BRIDGE_EXTEND_M)
            s, _, _ = projectors[rid](xz[m])
            acc[rid]["xz"].append(xz[m])
            acc[rid]["sta"].append(s)
            acc[rid]["hw"].append(np.full(m.sum(), (w["tags"].get("width_m") or 8.0) / 2.0))

    for rid, a in acc.items():
        if not a["xz"]:
            continue
        xz, sta, hw = np.concatenate(a["xz"]), np.concatenate(a["sta"]), np.concatenate(a["hw"])
        camber, extra = np.ones(len(xz)), np.zeros(len(xz))
        for be in doc["routes"][rid].get("bridge_ends", []):
            # distance back along the approach from the deck's end; 0 on the deck itself
            d = np.maximum((be["sta"] - sta) * -be["side"], 0.0)
            c, e = _approach(d)
            near = d < BRIDGE_APPROACH_M
            camber[near] = np.minimum(camber[near], c[near])
            extra[near] = np.maximum(extra[near], e[near])
        strips.append({"key": rid, "order": npaths + doc["routes"][rid]["paint"], "xz": xz,
                       "y": profiles[rid].elevation(sta), "hw": hw, "extra": extra, "camber": camber,
                       "sta": sta})

    order = sorted(doc["paths"], key=lambda k: (doc["paths"][k]["length"], k))
    for i, key in enumerate(order):
        pd = doc["paths"][key]
        w = ways.get(int(key))
        if w is None:
            continue
        pts = [(v["x"], v["z"]) for v in w["vertices"]]
        # an end at a composed deck runs BRIDGE_EXTEND_M onto it
        lead = 0.0
        if "start" in pd["anchored_ends"]:
            pts.insert(0, _step_past(pts[1], pts[0], BRIDGE_EXTEND_M))
            lead = BRIDGE_EXTEND_M
        if "end" in pd["anchored_ends"]:
            pts.append(_step_past(pts[-2], pts[-1], BRIDGE_EXTEND_M))
        xz, ds = _densify(np.array(pts), CONFORM_STEP_M)
        s = np.clip(ds - lead, 0.0, pd["length"])
        prof = vt.Profile.from_json(pd["pvis"])
        camber, extra = np.ones(len(xz)), np.zeros(len(xz))
        for key_end in pd["anchored_ends"]:
            d = np.maximum(ds - lead, 0.0) if key_end == "start" else np.maximum(pd["length"] - (ds - lead), 0.0)
            c, e = _approach(d)
            camber, extra = np.minimum(camber, c), np.maximum(extra, e)
        strips.append({"key": key, "order": i, "xz": xz, "y": prof.elevation(s),
                       "hw": np.full(len(xz), (w["tags"].get("width_m") or 2.0) / 2.0),
                       "extra": extra, "camber": camber, "sta": s})
    strips.sort(key=lambda st: st["order"])
    return strips, doc["junctions"]


def _step_past(a, b, dist):
    d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    return (b[0] + (b[0] - a[0]) / d * dist, b[1] + (b[1] - a[1]) / d * dist)


def main(argv):
    doc, report = solve()
    write(doc, report)
    print(json.dumps(summary(report), indent=1))
    for c in report["conflicts"][:20]:
        print("  conflict:", c)
    print(f"wrote {OUT_PATH}\nreport {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
