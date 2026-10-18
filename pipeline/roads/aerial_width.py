"""Pavement width and centre from the 2025 6-inch aerial (docs/roadway_control_plan.md, phase 1).

A street keeps one width along a block, so it is measured a block at a time. The route is cut
into blocks (the stretches between junctions, at most 150 m) and the aerial is sampled across
it every 2 m, 15 m to each side. Taking the median of every cross-section in a block, per
offset, washes out what is local: parked cars, tree crowns, shadows, driveways. The median
profile is then searched for the asphalt band: a run 4 to 22 m wide that is uniform inside,
pavement-coloured (grey, low saturation), and differs most from the metre outside each edge.
The OSM line is not always parallel to the street, so the block is also sheared by up to
±2.3 degrees and the best shear kept.

A block counts when its score (edge contrast minus the band's own variation) is at least
MIN_SCORE and its width is plausible for the class. A route's width is the median of its blocks
that count, when at least MIN_CONFIDENCE of its blocks do and they agree (interquartile range at
most MAX_SPREAD_M); otherwise it falls back to the OSM width tag. Where a concrete gutter flag
shows just outside the asphalt on most counted blocks, curb-to-curb adds two flags; otherwise
the gutter is "not_seen" (overlaid, or missed) and curb-to-curb is the asphalt width. The result
is rounded to the foot.

Nothing here moves an alignment. The pavement centre's offset from the alignment is reported per
block; counted blocks more than RECENTRE_FLAG_M off centre are listed for review
(off_centre_blocks in the alignment report), not recentred.

Automatic curb finding in leaf-off imagery is a best effort: trees over the curb, cars parked
along a whole block, and paving that runs on into lots all defeat it on some blocks. That is why
results carry their confidence and the review overlay draws every counted block's edges.
"""
import glob
import json
import os

import numpy as np

import common_roads  # noqa: F401  (puts pipeline/ on the path)
import common as pc

TILE_DIR = os.path.join(pc.ROOT, "data", "raw", "il2025")
STEP_M = 2.0            # cross-sections along the route
RES_M = 0.25            # samples across it
REACH_M = 15.0          # how far to each side
BLOCK_MAX_M = 150.0
BLOCK_MIN_M = 40.0
EDGE_M = 1.0            # the band outside each edge that must contrast
WIDTH_M = (4.0, 22.0)
SHEARS = np.linspace(-0.04, 0.04, 17)
MIN_SCORE = 0.12
MIN_CONFIDENCE = 0.5
MAX_SPREAD_M = 2.0
JUNCTION_CLEAR_M = 12.0
PLAUSIBLE_M = {"arterial": (10.0, 22.0), "collector": (7.0, 18.0), "local": (5.5, 16.0)}
RECENTRE_FLAG_M = 2.0
SURVEYED_CLASSES = tuple(PLAUSIBLE_M)


class Aerial:
    """The 2025 orthoimagery tiles, placed by each tile's `pixel_from_world` affine.

    A tile's world_x0..x1 box is only where it was requested: the imagery is Web Mercator,
    turned ~1.7 degrees from the game's UTM grid, so pixels sit up to ~15 m off that box at its
    corners (pipeline/aerial/georef_affine.py). Every lookup goes through the affine."""

    def __init__(self, tile_dir=TILE_DIR):
        self.tiles = []
        self.cache = {}
        self.tile_dir = tile_dir
        for path in sorted(glob.glob(os.path.join(tile_dir, "*_georef.json"))):
            with open(path) as handle:
                t = json.load(handle)
            if "pixel_from_world" in t:
                self.tiles.append(t)

    def _image(self, t):
        from PIL import Image
        if t["tile"] not in self.cache:
            img = Image.open(os.path.join(self.tile_dir, t["tile"] + ".png")).convert("RGB")
            self.cache[t["tile"]] = np.asarray(img, dtype=np.float32) / 255.0
        return self.cache[t["tile"]]

    def sample(self, xs, zs):
        """RGB in 0..1 at world points (any shape); NaN where there is no imagery."""
        xs, zs = np.asarray(xs, dtype=np.float64), np.asarray(zs, dtype=np.float64)
        out = np.full(xs.shape + (3,), np.nan)
        todo = np.ones(xs.shape, dtype=bool)
        x0, x1, z0, z1 = xs.min(), xs.max(), zs.min(), zs.max()
        margin = 32.0
        for t in self.tiles:
            if (t["world_x1"] + margin < x0 or t["world_x0"] - margin > x1 or
                    t["world_z1"] + margin < z0 or t["world_z0"] - margin > z1):
                continue
            a, b, c, d, e, f = t["pixel_from_world"]
            w, h = t["size_px"]
            px = a * xs + b * zs + c
            py = d * xs + e * zs + f
            m = todo & (px >= 0) & (px < w) & (py >= 0) & (py < h)
            if not m.any():
                continue
            arr = self._image(t)
            out[m] = arr[np.minimum(py[m].astype(int), arr.shape[0] - 1),
                         np.minimum(px[m].astype(int), arr.shape[1] - 1)]
            todo &= ~m
        return out


def cross_sections(alignment, aerial, step=STEP_M, reach=REACH_M):
    """Stations, offsets (left +) and the aerial's RGB across the route: (n_sta, n_off, 3)."""
    stas, pts, dirs = alignment.sample(step)
    offs = np.arange(-reach, reach + 1e-9, RES_M)
    # the left normal of heading (hx, hz) is (hz, -hx)
    xs = pts[:, 0:1] + dirs[:, 1:2] * offs[None, :]
    zs = pts[:, 1:2] - dirs[:, 0:1] * offs[None, :]
    return stas, offs, aerial.sample(xs, zs)


def band_fit(profile, offs, width=WIDTH_M):
    """The asphalt band in a median RGB profile (n_off, 3): (right edge, left edge, score).

    Score: the smaller colour difference between the band and the metre outside either edge,
    minus the band's own colour variation. Bands that are not pavement-coloured score -inf."""
    n = len(offs)
    c1 = np.vstack([np.zeros(3), np.cumsum(profile, axis=0)])
    c2 = np.vstack([np.zeros(3), np.cumsum(profile ** 2, axis=0)])
    e = int(round(EDGE_M / RES_M))
    w_lo, w_hi = int(round(width[0] / RES_M)), int(round(width[1] / RES_M))
    i0 = np.arange(e, n - e - w_lo + 1)[:, None]
    w = np.arange(w_lo, w_hi + 1)[None, :]
    i1 = i0 + w
    valid = i1 <= n - e
    i1 = np.minimum(i1, n - e)
    mu = (c1[i1] - c1[i0]) / w[..., None]
    sig = np.sqrt(np.clip((c2[i1] - c2[i0]) / w[..., None] - mu ** 2, 0.0, None).mean(-1))
    lam = (c1[i0] - c1[i0 - e]) / e
    rho = (c1[i1 + e] - c1[i1]) / e
    contrast = np.minimum(np.linalg.norm(mu - lam, axis=-1), np.linalg.norm(mu - rho, axis=-1))
    mx, mn = mu.max(-1), mu.min(-1)
    paved = ((mx - mn) / np.maximum(mx, 1e-6) < 0.25) & (mx > 0.2) & (mx < 0.7)
    score = np.where(valid & paved, contrast - sig, -np.inf)
    k = np.unravel_index(int(np.argmax(score)), score.shape)
    a, b = int(i0[k[0], 0]), int(i1[k])
    return offs[a] - RES_M / 2, offs[b - 1] + RES_M / 2, float(score[k])


def gutter_evidence(profile, offs, edge, side, inner):
    """'visible' when a concrete strip shows just outside an edge and the ground beyond is not
    concrete, 'overlaid' when the asphalt meets something that is not concrete, None when the
    concrete runs on (a sidewalk at the curb: cannot tell)."""
    def band(o0, o1):
        lo, hi = sorted((edge + side * o0, edge + side * o1))
        m = (offs >= lo) & (offs <= hi)
        return profile[m].mean(axis=0) if m.any() else None
    near, far = band(0.1, 0.6), band(1.0, 1.8)
    if near is None or far is None:
        return None

    def concrete(c):
        mx, mn = c.max(), c.min()
        return mx > inner.max() + 0.08 and (mx - mn) / max(mx, 1e-6) < 0.22
    if concrete(near) and concrete(far):
        return None
    return "visible" if concrete(near) else "overlaid"


def blocks(stas, skip, clear=JUNCTION_CLEAR_M):
    """Index ranges [(i0, i1), ...] of the stretches between skipped stations, cut to BLOCK_MAX_M."""
    ok = np.ones(len(stas), dtype=bool)
    for a, b in skip:
        ok &= ~((stas >= a - clear) & (stas <= b + clear))
    m = np.r_[False, ok, False].astype(int)
    e = np.flatnonzero(np.diff(m))
    per_block = int(BLOCK_MAX_M / STEP_M)
    min_n = int(BLOCK_MIN_M / STEP_M)
    out = []
    for i0, i1 in zip(e[::2], e[1::2]):
        n = i1 - i0
        if n < min_n:
            continue
        parts = max(1, int(np.ceil(n / per_block)))
        edges = np.linspace(i0, i1, parts + 1).round().astype(int)
        out.extend((int(a), int(b)) for a, b in zip(edges[:-1], edges[1:]))
    return out


def survey_route(alignment, aerial, skip, cls):
    """The route's blocks: [{sta: [s0, s1], right, left, width, centre, shear, score, counts,
    gutter}, ...]. Offsets are left-positive, at the block's middle; `shear` is the change in
    offset per metre of station."""
    stas, offs, rgb = cross_sections(alignment, aerial)
    plausible = PLAUSIBLE_M.get(cls, WIDTH_M)
    shift_idx = np.arange(len(offs))
    out = []
    for i0, i1 in blocks(stas, skip):
        sub = rgb[i0:i1]
        if np.isnan(sub).any(axis=-1).mean() > 0.2:
            continue
        s = stas[i0:i1]
        mid = float(s.mean())
        best = None
        for m in SHEARS:
            k = np.rint(m * (s - mid) / RES_M).astype(int)
            idx = np.clip(shift_idx[None, :] + k[:, None], 0, len(offs) - 1)
            sheared = np.take_along_axis(sub, idx[..., None], axis=1)
            prof = np.nanmedian(sheared, axis=0)
            if np.isnan(prof).any():
                continue
            right, left, score = band_fit(prof, offs)
            if best is None or score > best[0]:
                best = (score, right, left, float(m), prof)
        if best is None or not np.isfinite(best[0]):
            continue
        score, right, left, m, prof = best
        width = left - right
        inner = prof[(offs >= right + 0.5) & (offs <= left - 0.5)].mean(axis=0)
        counts = score >= MIN_SCORE and plausible[0] <= width <= plausible[1]
        out.append({"sta": [round(float(s[0]), 1), round(float(s[-1]), 1)],
                    "right": round(float(right), 2), "left": round(float(left), 2),
                    "width": round(float(width), 2), "centre": round(float((left + right) / 2), 2),
                    "shear": round(m, 4), "score": round(float(score), 3), "counts": bool(counts),
                    "gutter": [gutter_evidence(prof, offs, right, -1, inner),
                               gutter_evidence(prof, offs, left, 1, inner)]})
    return out


def summarize(blocks_, standards, osm_width):
    """The route's width record (see the module docstring)."""
    good = [b for b in blocks_ if b["counts"]]
    conf = len(good) / len(blocks_) if blocks_ else 0.0
    rec = {"blocks": len(blocks_), "blocks_counted": len(good), "confidence": round(conf, 2)}
    gutter_w = standards["cross_section"]["gutter_width"]
    widths = np.array([b["width"] for b in good])
    spread = float(np.subtract(*np.percentile(widths, [75, 25]))) if len(widths) >= 2 else None
    if good and conf >= MIN_CONFIDENCE and (spread is None or spread <= MAX_SPREAD_M):
        asphalt = float(np.median(widths))
        votes = [g for b in good for g in b["gutter"] if g]
        visible = votes.count("visible")
        # seeing no flag is weak evidence (an edge found half a metre out misses it), so a
        # gutter is only called visible on a clear majority, and otherwise "not_seen"
        gutter = "visible" if votes and visible > 0.6 * len(votes) else "not_seen"
        c2c = asphalt + (2 * gutter_w if gutter == "visible" else 0.0)
        rec.update({"source": "aerial", "asphalt_m": round(asphalt, 2),
                    "asphalt_spread_m": None if spread is None else round(spread, 2),
                    "gutter": gutter, "gutter_votes": {"visible": visible, "overlaid": len(votes) - visible}})
    else:
        c2c = float(osm_width)
        rec.update({"source": "osm_width_tag", "gutter": "not_seen"})
    step = standards["cross_section"].get("width_rounding", 0.3048)
    feet = int(round(c2c / step))
    rec["curb_to_curb_ft"] = feet
    rec["curb_to_curb_m"] = round(feet * step, 3)
    return rec


def block_edges(alignment, blocks_):
    """Each counted block's two edges as world polylines, for the review overlay."""
    out = []
    for b in blocks_:
        if not b["counts"]:
            continue
        mid = (b["sta"][0] + b["sta"][1]) / 2
        for edge in (b["right"], b["left"]):
            pts = []
            for s in np.linspace(b["sta"][0], b["sta"][1], 8):
                x, z, h = alignment.point_at(s)
                o = edge + b["shear"] * (s - mid)
                pts.append((x + h[1] * o, z - h[0] * o))
            out.append(pts)
    return out
