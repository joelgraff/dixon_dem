#!/usr/bin/env python3
"""Serves Building Composer and takes the buildings it sends back to the game.

  python3 game/tools/composer_server.py [--port 8000] [--dir ../building-composer]

Composer's "Send to game" POSTs to /game-save/<id>; the body is written to
game/data/composed/<id>.json, which pipeline/buildings/composed.py reads. The
server listens on 127.0.0.1 only, and a save must be same-origin (the page
sends a custom header, which a foreign page cannot add without a preflight this
server never answers), have a plain id, and be a composed building of
reasonable size.

Bridge Composer (docs/bridge_composer_schema.md) uses the same server:
  GET  /game-bridges            every bridge way with its centreline, width and
                                whether a design exists
  GET  /game-bridge/<way id>    that design (404 if none)
  POST /game-new-bridge         {centerline, width, kind, name}: a bridge drawn in the editor, written as
                                bridges_composed/custom-<n>.json and returned
  POST /game-suppress-bridge/<id>  {suppressed, reason}: records an OSM bridge way as a duplicate
                                (game/data/bridge_registry.json) that the road plan leaves out
  POST /game-delete-bridge/<id>    removes a design: a drawn bridge disappears, an OSM bridge goes
                                back to the generated deck
  POST /game-rebuild            {"mode": "fast" | "full"}: runs pipeline/roads/rebuild_bridges.sh in the
                                background -- fast: the bridge layer only, seconds; full: heightmap, road
                                plan and both bakes, minutes. GET /game-rebuild-status reports progress
  POST /game-save-bridge/<id>   writes game/data/bridges_composed/<id>.json, which
                                pipeline/roads/bridges_composed.py builds in place
                                of the generated deck; same checks as /game-save

GET /game-materials serves game/data/materials_manifest.json, the game's
material names (pipeline/buildings/palette.py manifest()), so Composer offers
only finishes the game has.

For Composer's footprint editor (both read-only, boxes in game meters):
  GET /game-aerial?x0=&z0=&x1=&z1=&mpp=  a PNG of the box from the 2025
      orthoimagery (pipeline/aerial/aerial_crop.py; 404 where it isn't fetched)
  GET /game-footprints?x0=&z0=&x1=&z1=   {"buildings": [{id, source,
      footprint, override?}]}, every outline meeting the box, corrections
      applied (pipeline/buildings/footprints.py)

Its "Save footprint to game" POSTs a footprint override to
/game-footprint/<id>, written to game/data/footprint_overrides/<id>.json
(format `dixon-footprint-override`, see footprints.py), with the same
same-origin checks as a save.
"""
import argparse
import json
import math
import os
import re
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COMPOSED_DIR = os.path.join(ROOT, "game", "data", "composed")
MATERIALS_MANIFEST = os.path.join(ROOT, "game", "data", "materials_manifest.json")
BRIDGES_DIR = os.path.join(ROOT, "game", "data", "bridges_composed")
BRIDGES_JSON = os.path.join(ROOT, "game", "data", "bridges.json")
sys.path[:0] = [os.path.join(ROOT, "pipeline", "buildings"), os.path.join(ROOT, "pipeline", "aerial"),
                os.path.join(ROOT, "pipeline", "roads"), os.path.join(ROOT, "pipeline")]
import footprints  # noqa: E402
import bridges_composed  # noqa: E402
from aerial_crop import Aerial  # noqa: E402
ID = re.compile(r"^[0-9A-Za-z_-]{1,40}$")
MAX_BYTES = 32 * 1024 * 1024
# a footprint override is an outline and a few porches
MAX_FOOTPRINT_BYTES = 1024 * 1024
MAX_CORNERS = 2000
PORCH_KINDS = {"stoop", "shed_full", "gable_full", "wrap"}


def validate(bid, body):
    """The parsed file if `body` is a composed building for `bid`, else raises ValueError."""
    if not ID.match(bid or ""):
        raise ValueError("bad id")
    try:
        data = json.loads(body)
    except ValueError:
        raise ValueError("not JSON")
    if not isinstance(data, dict) or data.get("format") != "dixon-composed" or not isinstance(data.get("near"), dict):
        raise ValueError("not a composed building")
    if str(data.get("id")) != bid:
        raise ValueError("the file is for another building")
    return data


def save(bid, body, directory=COMPOSED_DIR):
    validate(bid, body)
    _write(bid, body, directory)


def _write(bid, body, directory):
    """Writes `body` as <directory>/<bid>.json, whole or not at all."""
    os.makedirs(directory, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    with os.fdopen(handle, "wb") as out:
        out.write(body)
    os.chmod(temp, 0o644)
    os.replace(temp, os.path.join(directory, f"{bid}.json"))


def save_bridge(bid, body, directory=BRIDGES_DIR):
    """Writes a composed bridge for way `bid`; raises ValueError if it isn't one for that way."""
    if not ID.match(bid or ""):
        raise ValueError("bad id")
    try:
        data = json.loads(body)
    except ValueError:
        raise ValueError("not JSON")
    try:
        bridges_composed.validate(data)
    except bridges_composed.BridgeError as error:
        raise ValueError(str(error))
    if data["id"] != bid:
        raise ValueError("the file is for another bridge")
    os.makedirs(directory, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    with os.fdopen(handle, "wb") as out:
        out.write(body)
    os.chmod(temp, 0o644)
    os.replace(temp, os.path.join(directory, f"{bid}.json"))


class Ground:
    """Terrain height from the road-conformed play heightmap (raw float32), without numpy.

    The same bilinear sample as pipeline/roads/common_roads.Heightmap; the server's Python
    need not have numpy, so it is not imported from there."""

    def __init__(self, raw=False):
        import array
        import common as pc
        hm = pc.load_world_origin()["heightmaps"]["play"]
        # raw: the play heightmap before roads are conformed to it, which is where the deck
        # heights are read from -- the conformed one is what a composed bridge changes
        self.w, self.h, self.spacing = hm["width"], hm["height"], hm["spacing_m"]
        self.x0 = hm["origin_easting"] - pc.ORIGIN_EASTING
        self.z0 = -(hm["origin_northing_top"] - pc.ORIGIN_NORTHING)
        values = array.array("f")
        with open(os.path.join(pc.GAME_DATA, hm["file"] if raw else hm["road_conformed_file"]), "rb") as handle:
            values.frombytes(handle.read())
        if sys.byteorder == "big":
            values.byteswap()
        if len(values) != self.w * self.h:
            raise ValueError("heightmap size mismatch")
        self.values = values

    def at(self, x, z):
        col = min(max((x - self.x0) / self.spacing, 0.0), self.w - 1.001)
        row = min(max((z - self.z0) / self.spacing, 0.0), self.h - 1.001)
        c0, r0 = int(col), int(row)
        fc, fr = col - c0, row - r0
        v, w = self.values, self.w
        top = v[r0 * w + c0] * (1 - fc) + v[r0 * w + c0 + 1] * fc
        bot = v[(r0 + 1) * w + c0] * (1 - fc) + v[(r0 + 1) * w + c0 + 1] * fc
        return top * (1 - fr) + bot * fr


_GROUND = []
_RAW = []


def ground():
    """The sampler, loaded on first use; None where the heightmap is not on disk."""
    if not _GROUND:
        try:
            _GROUND.append(Ground())
        except (OSError, ValueError, KeyError, ImportError):
            _GROUND.append(None)
    return _GROUND[0]


APPROACH_M = 15.24    # 50 ft of approach shown either side of a bridge in Bridge Composer


def ground_profile(vertices, sampler, step=5.0, limit=400, extend=0.0):
    """[[station, terrain y], ...] along a way's vertices, about every `step` metres.

    With `extend`, the line continues that far past each end along its end tangent, and the
    stations run from -extend to length + extend (station 0 is still the first vertex)."""
    pts = [(v["x"], v["z"]) for v in vertices]
    if len(pts) < 2:
        return []
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = cum[-1]
    if total <= 0.0:
        return []
    if extend > 0.0:
        def tangent(a, b):
            d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
            return (b[0] - a[0]) / d, (b[1] - a[1]) / d
        t0, t1 = tangent(pts[0], pts[1]), tangent(pts[-2], pts[-1])
        pts = [(pts[0][0] - t0[0] * extend, pts[0][1] - t0[1] * extend)] + pts + \
              [(pts[-1][0] + t1[0] * extend, pts[-1][1] + t1[1] * extend)]
        cum = [0.0] + [c + extend for c in cum] + [total + 2 * extend]
    whole = cum[-1]
    n = max(1, min(limit, int(math.ceil(whole / step))))
    out = []
    i = 0
    for k in range(n + 1):
        d = whole * k / n
        while i < len(pts) - 2 and cum[i + 1] < d:
            i += 1
        seg = cum[i + 1] - cum[i]
        t = (d - cum[i]) / seg if seg > 1e-9 else 0.0
        x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t
        z = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t
        out.append([round(d - (extend if extend > 0.0 else 0.0), 2), round(sampler.at(x, z), 2)])
    return out


# ---------------------------------------------------------------------------
# Naming: "what the bridge carries over what it crosses"
# ---------------------------------------------------------------------------
# The water reaches carry no names in the data; the only river in the play area is the Rock.
WATER_NAMES = {"river": "Rock River", "pond": "pond", "stream": "creek"}
# Short OSM names that read badly as a place (docs/references).
FEATURE_NAMES = {"IC (abnd)": "former Illinois Central line"}
CARRIES = {"footway": "Footbridge", "pedestrian": "Footbridge", "steps": "Footbridge",
           "cycleway": "Bike path", "path": "Trail", "track": "Track"}
CLASS_NAMES = {"motorway": "highway", "trunk": "highway", "primary": "street", "secondary": "street",
               "tertiary": "street", "residential": "street", "service": "service road",
               "unclassified": "street", "footway": "footpath", "cycleway": "bike path",
               "path": "trail", "pedestrian": "footpath"}


def _in_polygon(x, z, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, zi, xj, zj = poly[i]["x"], poly[i]["z"], poly[j]["x"], poly[j]["z"]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi) + xi:
            inside = not inside
        j = i
    return inside


def _segments_cross(a, b, c, d):
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def _point_segment(p, a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dz * dz
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / length2))
    return math.hypot(p[0] - (a[0] + dx * t), p[1] - (a[1] + dz * t))


def feature_name(tags, fallback):
    name = tags.get("name")
    if name:
        return FEATURE_NAMES.get(name, name)
    return fallback


def crossings(way, roads, rails, water):
    """What a bridge goes over, in order along it: water first, then roads and railways.

    `roads` and `rails` are lists of ways ({id, vertices, tags}); `water` is water.json.
    A way with a layer above the bridge's, the bridge's own way, and ways that only touch
    its ends (the roads it connects to) are not crossed."""
    pts = [(v["x"], v["z"]) for v in way["vertices"]]
    if len(pts) < 2:
        return []
    samples = []
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) // 2.0))
        samples += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    samples.append(pts[-1])
    found = []

    def add(name):
        if name and name not in found:
            found.append(name)

    for reach in water.get("reaches", []):
        poly = reach["polygon"]
        xs = [p["x"] for p in poly]
        zs = [p["z"] for p in poly]
        if any(min(xs) <= x <= max(xs) and min(zs) <= z <= max(zs) and _in_polygon(x, z, poly) for x, z in samples):
            add(WATER_NAMES.get(reach.get("kind"), "water"))
    for stream in water.get("streams", []):
        sv = [(v["x"], v["z"]) for v in stream["vertices"]]
        if any(_point_segment(p, a, b) < 4.0 for p in samples for a, b in zip(sv, sv[1:])):
            add(stream.get("name") or WATER_NAMES["stream"])
    mine = way["id"]
    my_layer = way["tags"].get("layer") or 0
    box = (min(p[0] for p in pts) - 5, min(p[1] for p in pts) - 5, max(p[0] for p in pts) + 5, max(p[1] for p in pts) + 5)
    for other, kind in [(w, "road") for w in roads] + [(w, "rail") for w in rails]:
        if other["id"] == mine:
            continue
        tags = other["tags"]
        if (tags.get("layer") or 0) >= max(my_layer, 1) and tags.get("bridge"):
            continue
        ov = [(v["x"], v["z"]) for v in other["vertices"]]
        if (max(p[0] for p in ov) < box[0] or min(p[0] for p in ov) > box[2]
                or max(p[1] for p in ov) < box[1] or min(p[1] for p in ov) > box[3]):
            continue   # its extent misses the bridge's
        hit = False
        for a, b in zip(pts, pts[1:]):
            for c, d in zip(ov, ov[1:]):
                if _segments_cross(a, b, c, d):
                    hit = True
        if hit:
            if kind == "road":
                add(feature_name(tags, CLASS_NAMES.get(tags.get("highway"), "road")))
            else:
                add(feature_name(tags, "railroad"))
    if found:
        return found
    # Nothing crossed outright. A bridge can span something its centreline only runs beside
    # (the deck is wide; the data is a line), so look for water or ways close to its middle.
    # The ends are skipped: the roads it joins touch there.
    ends = (pts[0], pts[-1])
    middle = [p for p in samples if min(math.hypot(p[0] - e[0], p[1] - e[1]) for e in ends) > 10.0]
    for reach in water.get("reaches", []):
        poly = reach["polygon"]
        edge = [(v["x"], v["z"]) for v in poly]
        if any(_point_segment(p, a, b) < 8.0 for p in middle for a, b in zip(edge, edge[1:] + edge[:1])):
            add(WATER_NAMES.get(reach.get("kind"), "water"))
    for other, kind in [(w, "road") for w in roads] + [(w, "rail") for w in rails]:
        if other["id"] == mine:
            continue
        ov = [(v["x"], v["z"]) for v in other["vertices"]]
        if len(ov) > 1 and not (max(p[0] for p in ov) < box[0] or min(p[0] for p in ov) > box[2]
                                or max(p[1] for p in ov) < box[1] or min(p[1] for p in ov) > box[3]) and any(
                _point_segment(p, a, b) < 6.0 for p in middle for a, b in zip(ov, ov[1:])):
            tags = other["tags"]
            add(feature_name(tags, CLASS_NAMES.get(tags.get("highway"), "road") if kind == "road" else "railroad"))
    return found


def carries(tags):
    name = tags.get("name")
    if tags.get("kind") == "railway":
        return FEATURE_NAMES.get(name, name) or "Railroad"
    return name or CARRIES.get(tags.get("highway"), "Bridge")


def bridge_title(tags, crosses):
    """"Peoria Ave over Rock River": what it carries over what it crosses (two at most)."""
    base = carries(tags)
    if not crosses:
        return base
    return f"{base} over {' and '.join(crosses[:2])}"


_NAMING = {}


def _naming_data():
    """roads, rails and water, reloaded when a file changes."""
    paths = [os.path.join(os.path.dirname(BRIDGES_JSON), n) for n in ("roads.json", "rails.json", "water.json")]
    stamp = tuple(os.path.getmtime(p) if os.path.exists(p) else None for p in paths)
    if _NAMING.get("stamp") != stamp:
        def load(path, key=None):
            try:
                with open(path) as handle:
                    data = json.load(handle)
                return data[key] if key else data
            except (OSError, ValueError, KeyError):
                return [] if key else {}
        _NAMING.update(stamp=stamp, roads=load(paths[0], "ways"), rails=load(paths[1], "ways"), water=load(paths[2]))
    return _NAMING["roads"], _NAMING["rails"], _NAMING["water"]


LAYOUT_JSON = os.path.join(ROOT, "game", "roads", "_build", "transport_layout.json")
_LAYOUT = {}


def _sidewalk_rings():
    """The sidewalk polygons' rings (lists of (x, z)) from the road plan's transportation layout,
    reloaded when the file changes; [] when it has not been built."""
    try:
        stamp = os.path.getmtime(LAYOUT_JSON)
    except OSError:
        return []
    if _LAYOUT.get("stamp") != stamp:
        try:
            with open(LAYOUT_JSON) as handle:
                geometry = json.load(handle)["surfaces"]["sidewalk"]
        except (OSError, ValueError, KeyError):
            return []
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        _LAYOUT.update(stamp=stamp, rings=[[(p[0], p[1]) for p in ring] for poly in polygons for ring in poly])
    return _LAYOUT["rings"]


def _intervals_along(rings, a, b):
    """Parts of the segment a-b (as fractions 0..1) that lie inside the rings (even-odd)."""
    hits = []
    ax, az, bx, bz = a[0], a[1], b[0], b[1]
    for ring in rings:
        if (max(p[0] for p in ring) < min(ax, bx) or min(p[0] for p in ring) > max(ax, bx)
                or max(p[1] for p in ring) < min(az, bz) or min(p[1] for p in ring) > max(az, bz)):
            continue
        for (cx, cz), (dx, dz) in zip(ring, ring[1:]):
            den = (bx - ax) * (dz - cz) - (bz - az) * (dx - cx)
            if abs(den) < 1e-12:
                continue
            t = ((cx - ax) * (dz - cz) - (cz - az) * (dx - cx)) / den
            u = ((cx - ax) * (bz - az) - (cz - az) * (bx - ax)) / den
            if 0.0 <= t <= 1.0 and 0.0 <= u < 1.0:
                hits.append(t)
    hits.sort()
    return [(hits[i], hits[i + 1]) for i in range(0, len(hits) - 1, 2)]


def approach_sidewalks(vertices, half_width):
    """Where the approach roads' sidewalks lie, measured from the road plan's layout, at each end.

    Returns [start, end]; each is {"left": [inner, outer], "right": [inner, outer]} -- lateral
    offsets from the bridge's centreline, as magnitudes, left and right of the bridge's own travel
    direction -- or None where no sidewalk reaches the end. Transects across the approach 4, 8
    and 12 m beyond the abutment are crossed with the layout's sidewalk polygons, so what a
    walkway has to meet is what the game builds, whatever rules produced it."""
    rings = _sidewalk_rings()
    pts = [(v["x"], v["z"]) for v in vertices]
    if len(pts) < 2 or not rings:
        return [None, None]
    reach = half_width + 9.0
    out = []
    for k, (a, b) in enumerate(((pts[1], pts[0]), (pts[-2], pts[-1]))):
        d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        tx, tz = (b[0] - a[0]) / d, (b[1] - a[1]) / d       # out of the bridge
        nx, nz = -tz, tx
        found = {}
        for side in (1, -1):
            samples = []
            for along in (4.0, 8.0, 12.0):
                o = (b[0] + tx * along, b[1] + tz * along)
                p0 = (o[0] + nx * side * (half_width + 0.05), o[1] + nz * side * (half_width + 0.05))
                p1 = (o[0] + nx * side * reach, o[1] + nz * side * reach)
                span = reach - (half_width + 0.05)
                for t0, t1 in _intervals_along(rings, p0, p1):
                    inner, outer = half_width + 0.05 + t0 * span, half_width + 0.05 + t1 * span
                    if inner <= half_width + 3.0 and 0.8 <= outer - inner <= 5.0:
                        samples.append((inner, outer))
                        break
            if len(samples) >= 2:
                samples.sort()
                mid = samples[len(samples) // 2]
                # `side` is relative to the way's direction out of the bridge; at the far end that
                # is the bridge's own right, at the near end its left reversed
                key = ("left" if side > 0 else "right") if k == 1 else ("right" if side > 0 else "left")
                found[key] = [round(mid[0], 2), round(mid[1], 2)]
        out.append(found or None)
    return out


REBUILD_SCRIPT = os.path.join(ROOT, "pipeline", "roads", "rebuild_bridges.sh")
_REBUILD = {"proc": None, "log": None, "started": None, "finished": None}


def rebuild_start(script=REBUILD_SCRIPT, log_path=None, mode="full"):
    """Starts pipeline/roads/rebuild_bridges.sh in the background, `fast` (bridges only, seconds) or
    `full` (heightmap, road plan, bakes; minutes). Raises ValueError if one is running."""
    import subprocess
    import time
    if mode not in ("fast", "full"):
        raise ValueError("mode is fast or full")
    proc = _REBUILD["proc"]
    if proc is not None and proc.poll() is None:
        raise ValueError("a rebuild is already running")
    log_path = log_path or os.path.join(tempfile.gettempdir(), "bridge-composer-rebuild.log")
    log = open(log_path, "w")
    _REBUILD.update(proc=subprocess.Popen(["bash", script, mode], stdout=log, stderr=subprocess.STDOUT,
                                          cwd=os.path.dirname(script)),
                    log=log_path, started=time.time(), finished=None)


def rebuild_status():
    """{state: idle|running|done|failed, stage, seconds, tail} for the editor's Rebuild game button."""
    import time
    proc = _REBUILD["proc"]
    if proc is None:
        return {"state": "idle"}
    code = proc.poll()
    if code is not None and _REBUILD["finished"] is None:
        _REBUILD["finished"] = time.time()
    try:
        with open(_REBUILD["log"]) as handle:
            lines = handle.read().splitlines()
    except OSError:
        lines = []
    stages = [line for line in lines if line.startswith("== ")]
    end = _REBUILD["finished"] or time.time()
    return {"state": "running" if code is None else ("done" if code == 0 else "failed"),
            "stage": stages[-1][3:] if stages else "starting", "seconds": round(end - _REBUILD["started"]),
            "tail": [line for line in lines[-6:] if line.strip()]}


def raw_ground():
    """Terrain before road-conforming (stable under a composed bridge's own changes), or None."""
    if not _RAW:
        try:
            _RAW.append(Ground(raw=True))
        except (OSError, ValueError, KeyError, ImportError):
            _RAW.append(None)
    return _RAW[0]


def approach_heights(vertices, sampler, approach=APPROACH_M):
    """[start, end] road heights `approach` metres out from a way's ends, along its end tangents,
    plus the height roads sit above terrain: what a deck's ends should meet."""
    pts = [(v["x"], v["z"]) for v in vertices]
    if len(pts) < 2 or sampler is None:
        return None
    out = []
    for a, b in ((pts[1], pts[0]), (pts[-2], pts[-1])):
        d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        out.append(round(sampler.at(b[0] + (b[0] - a[0]) / d * approach, b[1] + (b[1] - a[1]) / d * approach) + bridges_composed.ROAD_SURFACE_M, 2))
    return out


def new_bridge(body, directory=BRIDGES_DIR, bridges_json=BRIDGES_JSON, sampler=None):
    """Creates a design for a bridge drawn in the editor. `body` is JSON:
    {"centerline": [[x, z], ...], "width": metres, "kind": "street" | "path", "name": str | null}.
    Returns the design written to bridges_composed/custom-<n>.json."""
    try:
        request = json.loads(body)
        line = [[float(p[0]), float(p[1])] for p in request["centerline"]]
        width = float(request.get("width") or (16.0 if request.get("kind") == "street" else 3.0))
        kind = request.get("kind", "path")
    except (ValueError, KeyError, TypeError, IndexError):
        raise ValueError("needs centerline [[x, z], ...], width, kind")
    if kind not in ("street", "path"):
        raise ValueError("kind is street or path")
    if len(line) < 2 or len(line) > 500 or bridges_composed.centerline_length(line) < 3.0:
        raise ValueError("a bridge needs a centreline at least 3 m long")
    sampler = sampler or raw_ground()
    vertices = [{"x": p[0], "z": p[1]} for p in line]
    ends = approach_heights(vertices, sampler) if sampler else None
    if not ends:
        ends = [round(sampler.at(*line[0]) if sampler else 0.0, 2), round(sampler.at(*line[-1]) if sampler else 0.0, 2)]
    taken = {n[:-5] for n in os.listdir(directory)} if os.path.isdir(directory) else set()
    k = 1
    while f"custom-{k}" in taken:
        k += 1
    name = request.get("name")
    design = bridges_composed.new_design(f"custom-{k}", line, width, kind, name if isinstance(name, str) and name.strip() else None, ends)
    design = {key: value for key, value in design.items() if value is not None}
    bridges_composed.validate(design)
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, f"{design['id']}.json"), "w") as handle:
        json.dump(design, handle, indent=1)
        handle.write("\n")
    return design


def delete_bridge(bid, directory=BRIDGES_DIR):
    """Deletes a composed design: a custom bridge disappears; an OSM bridge goes back to the generated deck."""
    if not ID.match(bid or ""):
        raise ValueError("bad id")
    path = os.path.join(directory, f"{bid}.json")
    if not os.path.exists(path):
        raise ValueError("no design for this bridge")
    os.remove(path)


def suppress_bridge(bid, body, registry=None, bridges_json=BRIDGES_JSON):
    """Records (or clears) an OSM bridge way as a duplicate the game leaves out.
    `body` is JSON {"suppressed": true | false, "reason": "..."}."""
    if not ID.match(bid or ""):
        raise ValueError("bad id")
    try:
        request = json.loads(body)
    except ValueError:
        raise ValueError("not JSON")
    with open(bridges_json) as handle:
        ways = {str(w["id"]) for w in json.load(handle)["bridges"]}
    if bid not in ways:
        raise ValueError("only OSM bridge ways can be removed; delete a drawn bridge instead")
    entries = bridges_composed.suppressed(registry)
    if request.get("suppressed", True):
        entries[bid] = str(request.get("reason") or "removed in Bridge Composer")
    else:
        entries.pop(bid, None)
    bridges_composed.save_suppressed(entries, registry)


def bridge_list(bridges_json=BRIDGES_JSON, directory=BRIDGES_DIR, sampler=None):
    """Every road/path bridge way the game has, with whether it has a composed design."""
    sampler = sampler or ground()
    with open(bridges_json) as handle:
        ways = json.load(handle)["bridges"]
    out = []
    roads, rails, water = _naming_data()
    removed = bridges_composed.suppressed()
    for way in ways:
        tags = way["tags"]
        if tags.get("kind") == "railway":
            continue
        crosses = crossings(way, roads, rails, water)
        title = bridge_title(tags, crosses)
        derived = title
        design = os.path.join(directory, f"{way['id']}.json")
        if os.path.exists(design):
            try:
                with open(design) as handle:
                    title = json.load(handle).get("name") or title   # a name given in the editor wins
            except (OSError, ValueError):
                pass
        out.append({
            "id": str(way["id"]), "name": tags.get("name"), "highway": tags.get("highway"),
            "title": title, "carries": carries(tags), "crosses": crosses, "derived_title": derived,
            "width_m": tags.get("width_m"),
            "centerline": [[round(v["x"], 2), round(v["z"], 2)] for v in way["vertices"]],
            "deck_y": [v["y"] for v in way["vertices"]],
            # terrain along the centreline (station, y) every few metres: where the approach
            # roads are at the ends, and what a pier stands on between them
            "ground_profile": ground_profile(way["vertices"], sampler, extend=APPROACH_M) if sampler else None,
            "approach_m": APPROACH_M,
            # road heights 50 ft out from each end, read before conforming (so stable): the
            # heights a deck's ends should meet
            "approach_y": approach_heights(way["vertices"], raw_ground()),
            # the sidewalks the road plan lays up to each end, as lateral offsets from the centreline
            "approach_sidewalks": approach_sidewalks(way["vertices"], (tags.get("width_m") or 8.0) / 2.0),
            # the same at just the two ends
            "ground": ([round(sampler.at(way["vertices"][0]["x"], way["vertices"][0]["z"]), 2),
                        round(sampler.at(way["vertices"][-1]["x"], way["vertices"][-1]["z"]), 2)]
                       if sampler else None),
            "composed": os.path.exists(os.path.join(directory, f"{way['id']}.json")),
            # recorded as a duplicate (Remove in Bridge Composer): the road plan leaves it out
            "suppressed": removed.get(str(way["id"])),
            "custom": False,
        })
    # Bridges drawn in the editor, which are not OSM ways: one per composed file with no way behind it.
    known = {str(w["id"]) for w in ways}
    for design in bridges_composed.custom_designs(known, directory):
        vertices = [{"x": p[0], "z": p[1]} for p in design["centerline"]]
        width = design["deck"]["width"]
        way = {"id": design["id"], "vertices": vertices, "tags": {"name": design.get("name"), "layer": 1}}
        crosses = crossings(way, roads, rails, water)
        derived = bridge_title({"name": design.get("name")}, crosses)
        rows = design["deck"]["elevation"]
        out.append({
            "id": design["id"], "name": design.get("name"), "highway": None,
            "title": design.get("name") or derived, "carries": carries({"name": design.get("name")}),
            "crosses": crosses, "derived_title": derived, "width_m": width,
            "centerline": design["centerline"], "deck_y": [rows[0][1], rows[-1][1]],
            "ground_profile": ground_profile(vertices, sampler, extend=APPROACH_M) if sampler else None,
            "approach_m": APPROACH_M,
            "approach_y": approach_heights(vertices, raw_ground()),
            "approach_sidewalks": approach_sidewalks(vertices, width / 2.0),
            "ground": ([round(sampler.at(*design["centerline"][0]), 2), round(sampler.at(*design["centerline"][-1]), 2)]
                       if sampler else None),
            "composed": True, "suppressed": None, "custom": True,
        })
    # The two carriageways of a divided road are one structure: a deck whose own centreline
    # crosses nothing in the data takes what its twin crosses.
    def middle(b):
        c = b["centerline"]
        return ((c[0][0] + c[-1][0]) / 2.0, (c[0][1] + c[-1][1]) / 2.0)

    for b in out:
        if b["crosses"]:
            continue
        for twin in out:
            if (not b["custom"] and twin is not b and twin["crosses"] and twin["name"] and twin["name"] == b["name"]
                    and twin["highway"] == b["highway"]
                    and math.hypot(middle(twin)[0] - middle(b)[0], middle(twin)[1] - middle(b)[1]) < 60.0):
                b["crosses"] = list(twin["crosses"])
                if b["derived_title"] == b["carries"]:
                    b["derived_title"] = bridge_title({"name": b["name"], "highway": b["highway"]}, b["crosses"])
                    if b["title"] == b["carries"]:
                        b["title"] = b["derived_title"]
                break
    return out


def _point(value):
    """A finite [x, z], or raises ValueError."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("a point is [x, z]")
    try:
        x, z = (float(v) for v in value)
    except (TypeError, ValueError):
        raise ValueError("a point is [x, z]")
    if not all(map(math.isfinite, (x, z))):
        raise ValueError("a point is [x, z]")
    return [x, z]


def validate_footprint(bid, body):
    """The parsed override if `body` is a footprint override for `bid` (see
    footprints.py: an outline of at least three corners enclosing some area,
    and porches whose legs are an edge and a depth), else raises ValueError."""
    if not ID.match(bid or ""):
        raise ValueError("bad id")
    try:
        data = json.loads(body)
    except ValueError:
        raise ValueError("not JSON")
    if not isinstance(data, dict) or data.get("format") != "dixon-footprint-override":
        raise ValueError("not a footprint override")
    if str(data.get("id")) != bid:
        raise ValueError("the file is for another building")
    corners = data.get("footprint")
    if not isinstance(corners, list) or not 3 <= len(corners) <= MAX_CORNERS:
        raise ValueError("the footprint needs 3 to %d corners" % MAX_CORNERS)
    ring = [_point(p) for p in corners]
    area = sum(x * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * z for i, (x, z) in enumerate(ring)) / 2
    if abs(area) < 1.0:
        raise ValueError("the footprint encloses no area")
    porches = data.get("porches", [])
    if not isinstance(porches, list):
        raise ValueError("porches is a list")
    for porch in porches:
        if not isinstance(porch, dict) or porch.get("kind") not in PORCH_KINDS:
            raise ValueError("a porch's kind is one of " + ", ".join(sorted(PORCH_KINDS)))
        legs = porch.get("legs")
        if not isinstance(legs, list) or not 1 <= len(legs) <= 4:
            raise ValueError("a porch has 1 to 4 legs")
        for leg in legs:
            if not isinstance(leg, dict):
                raise ValueError("a leg is {a, b, depth}")
            a, b = _point(leg.get("a")), _point(leg.get("b"))
            depth = leg.get("depth")
            if a == b or not isinstance(depth, (int, float)) or not math.isfinite(depth) or not 0 < depth <= 20:
                raise ValueError("a leg is an edge and a depth (0 to 20 m)")
    return data


def save_footprint(bid, body, directory=footprints.OVERRIDES_DIR):
    validate_footprint(bid, body)
    _write(bid, body, directory)


class Outlines:
    """Every building outline, loaded once and again when a source or an override changes."""

    def __init__(self, game_data=footprints.GAME_DATA, overrides_dir=footprints.OVERRIDES_DIR):
        self.game_data = game_data
        self.overrides_dir = overrides_dir
        self._stamp = None
        self._records = []

    def _changed(self):
        paths = [os.path.join(self.game_data, name) for name in ("buildings.json", "buildings_curated.json", "buildings_ms.json")]
        if os.path.isdir(self.overrides_dir):
            paths += sorted(os.path.join(self.overrides_dir, name) for name in os.listdir(self.overrides_dir))
        return tuple((path, os.path.getmtime(path)) for path in paths if os.path.exists(path))

    def in_box(self, x0, z0, x1, z1):
        stamp = self._changed()
        if stamp != self._stamp:
            self._records = footprints.all_outlines(self.game_data, self.overrides_dir)
            self._stamp = stamp
        return footprints.in_box(self._records, x0, z0, x1, z1)


def _box(query, keys=("x0", "z0", "x1", "z1")):
    """The numbers `keys` from a query string, or raises ValueError."""
    values = parse_qs(query)
    try:
        return [float(values[key][0]) for key in keys]
    except (KeyError, IndexError, ValueError):
        raise ValueError(f"needs {', '.join(keys)}")


def make_handler(directory, composed_dir, materials_manifest=MATERIALS_MANIFEST, aerial=None, outlines=None,
                 bridges_dir=BRIDGES_DIR):
    aerial = aerial or Aerial()
    outlines = outlines or Outlines()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def end_headers(self):
            # revalidate every file, so an updated Composer is never run from a stale cache
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def _reply(self, code, text):
            body = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send(self, body, content_type):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path, query = urlsplit(self.path)[2:4]
            if path == "/game-materials":
                try:
                    with open(materials_manifest, "rb") as handle:
                        return self._send(handle.read(), "application/json")
                except OSError:
                    return self._reply(404, "no materials manifest")
            if path == "/game-aerial":
                if not aerial.available():
                    return self._reply(404, "no aerial imagery here (run pipeline/aerial/fetch_illinois.py)")
                try:
                    x0, z0, x1, z1 = _box(query)
                    mpp = float(parse_qs(query).get("mpp", ["0.25"])[0])
                    body, approximate = aerial.png(x0, z0, x1, z1, mpp)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    # placed by the tiles' recorded boxes alone: up to ~15 m off (pipeline/aerial/georef_affine.py)
                    self.send_header("X-Aerial-Approximate", "1" if approximate else "0")
                    self.end_headers()
                    self.wfile.write(body)
                    return None
                except ValueError as error:
                    return self._reply(400, str(error))
                except ImportError:
                    return self._reply(503, "the server's Python has no Pillow")
            if path == "/game-rebuild-status":
                return self._send(json.dumps(rebuild_status()).encode(), "application/json")
            if path == "/game-bridges":
                try:
                    return self._send(json.dumps({"bridges": bridge_list(directory=bridges_dir)}).encode(),
                                      "application/json")
                except (OSError, ValueError, KeyError):
                    return self._reply(404, "no bridges.json (run pipeline/build_vectors.py)")
            if path.startswith("/game-bridge/"):
                bid = path[len("/game-bridge/"):]
                if not ID.match(bid):
                    return self._reply(400, "bad id")
                file = os.path.join(bridges_dir, f"{bid}.json")
                if not os.path.exists(file):
                    return self._reply(404, "no composed design for this bridge")
                with open(file, "rb") as handle:
                    return self._send(handle.read(), "application/json")
            if path == "/game-footprints":
                try:
                    box = _box(query)
                except ValueError as error:
                    return self._reply(400, str(error))
                body = json.dumps({"buildings": outlines.in_box(*box)}).encode()
                return self._send(body, "application/json")
            return super().do_GET()

        def do_POST(self):
            routes = {
                "/game-save/": (lambda bid, body: save(bid, body, composed_dir)),
                # a corrected footprint, into the directory the outlines are read from
                "/game-footprint/": (lambda bid, body: save_footprint(bid, body, outlines.overrides_dir)),
                "/game-save-bridge/": (lambda bid, body: save_bridge(bid, body, bridges_dir)),
                "/game-suppress-bridge/": (lambda bid, body: suppress_bridge(bid, body)),
                "/game-delete-bridge/": (lambda bid, body: delete_bridge(bid, bridges_dir)),
                "/game-new-bridge": None,
                "/game-rebuild": None,
            }
            route = next((r for r in routes if self.path == r or (r.endswith("/") and self.path.startswith(r))), None)
            if route is None:
                return self._reply(404, "not found")
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            if self.headers.get("X-Composer") != "1" or (origin and origin.split("://", 1)[-1] != host):
                return self._reply(403, "not from Composer")
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._reply(411, "length required")
            limit = MAX_FOOTPRINT_BYTES if route == "/game-footprint/" else MAX_BYTES
            if length < 0 or length > limit:
                return self._reply(413, "too large")
            body = self.rfile.read(length) if length else b""
            try:
                if route == "/game-rebuild":
                    try:
                        mode = json.loads(body or b"{}").get("mode", "full")
                    except (ValueError, AttributeError):
                        mode = "full"
                    rebuild_start(mode=mode)
                    return self._reply(200, "started")
                if route == "/game-new-bridge":
                    design = new_bridge(body, bridges_dir)
                    return self._send(json.dumps(design).encode(), "application/json")
                routes[route](self.path[len(route):], body)
            except ValueError as error:
                return self._reply(400, str(error))
            return self._reply(200, "saved")

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dir", default=os.path.join(ROOT, "..", "building-composer"))
    args = parser.parse_args()
    directory = os.path.abspath(args.dir)
    if not os.path.exists(os.path.join(directory, "index.html")):
        raise SystemExit(f"No Building Composer at {directory}")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(directory, COMPOSED_DIR))
    print(f"Building Composer at http://localhost:{args.port}/index.html (saves to {COMPOSED_DIR})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
