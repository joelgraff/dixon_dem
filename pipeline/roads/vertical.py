"""Vertical alignments: PVIs joined by symmetric parabolic vertical curves (roadway_control_plan.md §3).

A profile is a chain of points of vertical intersection (PVIs), each a station and an elevation,
with a symmetric parabolic vertical curve of length L centred on every interior PVI (L = 0 is a
plain grade break). Between curves the profile is a straight grade. Elevations are game Y
(metres above world_origin.json's base elevation), stations metres along a route's alignment.

With the PVI stations and curve lengths fixed, the elevation and the grade at any station are
linear in the PVI elevations. A whole network of profiles is therefore a sparse linear
least-squares problem: ground samples, junction ties and fixed controls are all rows of one
system. `Network` builds that system and solves it robustly (Huber loss by iteratively
reweighted least squares), so DEM artefacts such as the bridge removal and river banks do not
drag the grade.
"""
import math

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


class Profile:
    """PVIs (stations ascending, elevations) and the vertical curve length at each PVI."""

    def __init__(self, stations, elevations, curves=None):
        self.s = np.asarray(stations, dtype=np.float64)
        self.e = np.asarray(elevations, dtype=np.float64)
        n = len(self.s)
        if n < 2 or len(self.e) != n:
            raise ValueError("a profile needs two or more PVIs, one elevation each")
        if np.any(np.diff(self.s) <= 0):
            raise ValueError("PVI stations must increase")
        self.L = np.zeros(n) if curves is None else np.asarray(curves, dtype=np.float64).copy()
        self.L[0] = self.L[-1] = 0.0
        h = np.diff(self.s)
        if n > 2 and np.any(self.L[1:-1] / 2 + self.L[2:] / 2 > h[1:] + 1e-6):
            raise ValueError("vertical curves overlap")
        if n > 2 and np.any(self.L[1:-1] / 2 > h[:-1] + 1e-6):
            raise ValueError("vertical curve runs past the previous PVI")

    @property
    def length(self):
        return float(self.s[-1] - self.s[0])

    def grades(self):
        """The grade of each straight between PVIs (n - 1)."""
        return np.diff(self.e) / np.diff(self.s)

    def elevation(self, s):
        idx, coef = basis(self.s, self.L, s)
        return (self.e[idx] * coef).sum(axis=1)

    def grade(self, s):
        idx, coef = basis(self.s, self.L, s, derivative=True)
        return (self.e[idx] * coef).sum(axis=1)

    def curves(self):
        """Every interior vertical curve: dict(sta, length, A (grade change, fraction), K (m per %),
        kind 'crest' or 'sag')."""
        g = self.grades()
        out = []
        for k in range(1, len(self.s) - 1):
            a = g[k] - g[k - 1]
            if abs(a) < 1e-9:
                continue
            L = self.L[k]
            out.append({"sta": float(self.s[k]), "length": float(L), "A": float(a),
                        "K": float(L / (abs(a) * 100.0)) if L > 0 else 0.0,
                        "kind": "crest" if a < 0 else "sag"})
        return out

    def to_json(self):
        return [[round(float(s), 2), round(float(e), 3), round(float(L), 2)]
                for s, e, L in zip(self.s, self.e, self.L)]

    @classmethod
    def from_json(cls, rows):
        rows = np.asarray(rows, dtype=np.float64)
        # stations are stored to the cm, so a curve may now overrun its neighbour by a hair
        return cls(rows[:, 0], rows[:, 1], np.minimum(rows[:, 2], curve_lengths(rows[:, 0])))


def curve_lengths(stations):
    """The longest symmetric curves that fit: each interior PVI's curve is as long as the shorter
    of its two straights, so neighbouring curves meet but never overlap."""
    s = np.asarray(stations, dtype=np.float64)
    L = np.zeros(len(s))
    if len(s) > 2:
        h = np.diff(s)
        L[1:-1] = np.minimum(h[:-1], h[1:])
    return L


def pvi_stations(length, hard=(), spacing=20.0, min_gap=2.5):
    """PVI stations for a route of `length`: both ends, every `hard` station (junctions, bridge
    ends) at least `min_gap` from the last kept one and from the far end, and the gaps between
    filled evenly so that no straight is longer than `spacing`."""
    keep = [0.0]
    for s in sorted(float(v) for v in hard):
        if min_gap <= s <= length - min_gap and s - keep[-1] >= min_gap:
            keep.append(s)
    keep.append(float(length))
    out = [keep[0]]
    for a, b in zip(keep, keep[1:]):
        n = max(1, int(math.ceil((b - a) / spacing - 1e-9)))
        out.extend(a + (b - a) * k / n for k in range(1, n + 1))
    return np.array(out)


def basis(S, L, s, derivative=False):
    """For stations `s`, the indices (m, 3) of the PVIs their elevation (or grade) depends on and
    the coefficients (m, 3): y(s) = sum(coef * e[idx])."""
    S = np.asarray(S, dtype=np.float64)
    L = np.asarray(L, dtype=np.float64)
    s = np.clip(np.atleast_1d(np.asarray(s, dtype=np.float64)), S[0], S[-1])
    n = len(S)
    h = np.diff(S)
    m = len(s)
    idx = np.zeros((m, 3), dtype=np.int64)
    coef = np.zeros((m, 3))
    k = np.clip(np.searchsorted(S, s, side="right") - 1, 0, n - 2)

    # which curve, if any, each station lies on: the PVI at the start of its straight, or the end
    j = np.full(m, -1)
    in_k = (k >= 1) & (s <= S[k] + L[k] / 2)
    j[in_k] = k[in_k]
    k1 = np.minimum(k + 1, n - 1)
    in_k1 = (~in_k) & (k1 <= n - 2) & (s >= S[k1] - L[k1] / 2) & (L[k1] > 0)
    j[in_k1] = k1[in_k1]
    on_curve = (j >= 1) & (L[np.maximum(j, 0)] > 0)

    # straights: linear between PVI k and k + 1
    t = ~on_curve
    kt = k[t]
    idx[t, 0], idx[t, 1], idx[t, 2] = kt, kt + 1, kt + 1
    if derivative:
        coef[t, 0] = -1.0 / h[kt]
        coef[t, 1] = 1.0 / h[kt]
    else:
        u = (s[t] - S[kt]) / h[kt]
        coef[t, 0] = 1.0 - u
        coef[t, 1] = u

    # curves: y = e_j + g_{j-1} (s - S_j) + (g_j - g_{j-1}) x^2 / (2 L), x from the curve's start
    c = on_curve
    jc = j[c]
    Lc = L[jc]
    hb, ha = h[jc - 1], h[jc]
    x = s[c] - (S[jc] - Lc / 2)
    idx[c, 0], idx[c, 1], idx[c, 2] = jc - 1, jc, jc + 1
    if derivative:
        r = x / Lc
        coef[c, 0] = (r - 1.0) / hb
        coef[c, 1] = 1.0 / hb - r * (1.0 / ha + 1.0 / hb)
        coef[c, 2] = r / ha
    else:
        a = s[c] - S[jc]
        q = x * x / (2.0 * Lc)
        coef[c, 0] = (q - a) / hb
        coef[c, 1] = 1.0 + a / hb - q / ha - q / hb
        coef[c, 2] = q / ha
    return idx, coef


def huber_weights(r, delta):
    """IRLS weights for the Huber loss: 1 inside delta, delta / |r| beyond."""
    a = np.abs(r)
    return np.where(a <= delta, 1.0, delta / np.maximum(a, 1e-12))


class Network:
    """A sparse least-squares system over the PVI elevations of many profiles.

    Every row is linear in the unknown elevations: weight * (sum of coef * y or grade - target).
    A row may be robust: given a Huber threshold (in the units of its residual, metres for an
    elevation, a fraction for a grade), solve() reweights it so a residual beyond the threshold
    counts linearly. Ground samples are robust, so DEM artefacts do not drag the grade; ties and
    controls are not."""

    def __init__(self):
        self.layouts = {}       # key -> (offset, stations, curve lengths)
        self.n = 0
        self._rows = []         # (cols, vals, target, weight, huber threshold or None)

    def add(self, key, stations, curves=None):
        stations = np.asarray(stations, dtype=np.float64)
        curves = curve_lengths(stations) if curves is None else np.asarray(curves, dtype=np.float64)
        self.layouts[key] = (self.n, stations, curves)
        self.n += len(stations)
        return self.layouts[key][0]

    def _terms(self, key, s, derivative):
        off, S, L = self.layouts[key]
        idx, coef = basis(S, L, s, derivative)
        return idx + off, coef

    def rows(self, key, s, target, weight, derivative=False, huber=None):
        """One row per station: weight * (y, or the grade, of `key` at s - target)."""
        s = np.atleast_1d(np.asarray(s, dtype=np.float64))
        if s.size == 0:
            return
        cols, vals = self._terms(key, s, derivative)
        target = np.broadcast_to(np.asarray(target, dtype=np.float64), s.shape)
        weight = np.broadcast_to(np.asarray(weight, dtype=np.float64), s.shape)
        self._rows.append((cols, vals, target.copy(), weight.copy(), huber))

    def tie(self, terms, target, weight):
        """One row: weight * (sum of coef * y_or_grade(key, s) - target). terms: [(key, s, coef, deriv)]."""
        cols, vals = [], []
        for key, s, c, deriv in terms:
            ci, cv = self._terms(key, [s], deriv)
            cols.append(ci[0])
            vals.append(cv[0] * c)
        self._rows.append((np.concatenate(cols)[None, :], np.concatenate(vals)[None, :],
                           np.array([float(target)]), np.array([float(weight)]), None))

    def smoothing(self, key, weight, huber=None):
        """Rows weight * (g_k - g_{k-1}) at every interior PVI: resists needless grade changes.

        With `huber` (a grade change) the rows are robust too: a change beyond it costs linearly,
        not quadratically, so a sharp break the ground really has (an embankment, a bluff) is
        cheaper to follow than to cut through, while small wiggles are still smoothed away."""
        off, S, _ = self.layouts[key]
        if len(S) < 3:
            return
        h = np.diff(S)
        k = np.arange(1, len(S) - 1)
        cols = np.column_stack([k - 1, k, k + 1]) + off
        vals = np.column_stack([1.0 / h[k - 1], -1.0 / h[k - 1] - 1.0 / h[k], 1.0 / h[k]])
        self._rows.append((cols, vals, np.zeros(len(k)), np.full(len(k), float(weight)), huber))

    def prior(self, key, elevations, weight):
        """Weak rows tying each PVI to an elevation, so a profile with little data stays defined."""
        off, S, _ = self.layouts[key]
        k = np.arange(len(S))
        cols = (k + off)[:, None]
        vals = np.ones((len(k), 1))
        self._rows.append((cols, vals, np.asarray(elevations, dtype=np.float64),
                           np.full(len(k), float(weight)), None))

    def solve(self, iterations=10, tol=1e-4):
        """PVI elevations for every profile: {key: Profile}. Residuals (unweighted, A x - target)
        are kept in `residuals`, with `robust` marking the rows that were reweighted."""
        ri, ci, vi = [], [], []
        m = 0
        for cols, vals, tgt, _, _ in self._rows:
            ri.append(np.repeat(np.arange(m, m + len(tgt)), cols.shape[1]))
            ci.append(cols.ravel())
            vi.append(vals.ravel())
            m += len(tgt)
        target = np.concatenate([r[2] for r in self._rows])
        weight = np.concatenate([r[3] for r in self._rows])
        delta = np.concatenate([np.full(len(r[2]), np.inf if r[4] is None else float(r[4]))
                                for r in self._rows])
        robust = np.isfinite(delta)
        A = coo_matrix((np.concatenate(vi), (np.concatenate(ri), np.concatenate(ci))),
                       shape=(m, self.n)).tocsr()   # duplicate entries are summed
        w = weight.copy()
        x = None
        for _ in range(max(1, iterations)):
            W2 = w * w
            AtW = A.T.multiply(W2[None, :]).tocsr()
            x_new = spsolve((AtW @ A).tocsc(), AtW @ target)
            done = x is not None and np.max(np.abs(x_new - x)) < tol
            x = x_new
            r = A @ x - target
            hw = np.ones(m)
            hw[robust] = huber_weights(r[robust], delta[robust])
            w = weight * np.sqrt(hw)
            if done:
                break
        self.residuals = A @ x - target
        self.robust = robust
        return {key: Profile(S, x[off:off + len(S)], L) for key, (off, S, L) in self.layouts.items()}
