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

    def __init__(self):
        import array
        import common as pc
        hm = pc.load_world_origin()["heightmaps"]["play"]
        self.w, self.h, self.spacing = hm["width"], hm["height"], hm["spacing_m"]
        self.x0 = hm["origin_easting"] - pc.ORIGIN_EASTING
        self.z0 = -(hm["origin_northing_top"] - pc.ORIGIN_NORTHING)
        values = array.array("f")
        with open(os.path.join(pc.GAME_DATA, hm["road_conformed_file"]), "rb") as handle:
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


def ground():
    """The sampler, loaded on first use; None where the heightmap is not on disk."""
    if not _GROUND:
        try:
            _GROUND.append(Ground())
        except (OSError, ValueError, KeyError, ImportError):
            _GROUND.append(None)
    return _GROUND[0]


def ground_profile(vertices, sampler, step=5.0, limit=400):
    """[[station, terrain y], ...] along a way's vertices, about every `step` metres."""
    pts = [(v["x"], v["z"]) for v in vertices]
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = cum[-1]
    if total <= 0.0:
        return []
    n = max(1, min(limit, int(math.ceil(total / step))))
    out = []
    i = 0
    for k in range(n + 1):
        d = total * k / n
        while i < len(pts) - 2 and cum[i + 1] < d:
            i += 1
        seg = cum[i + 1] - cum[i]
        t = (d - cum[i]) / seg if seg > 1e-9 else 0.0
        x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t
        z = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t
        out.append([round(d, 2), round(sampler.at(x, z), 2)])
    return out


def bridge_list(bridges_json=BRIDGES_JSON, directory=BRIDGES_DIR, sampler=None):
    """Every road/path bridge way the game has, with whether it has a composed design."""
    sampler = sampler or ground()
    with open(bridges_json) as handle:
        ways = json.load(handle)["bridges"]
    out = []
    for way in ways:
        tags = way["tags"]
        if tags.get("kind") == "railway":
            continue
        out.append({
            "id": str(way["id"]), "name": tags.get("name"), "highway": tags.get("highway"),
            "width_m": tags.get("width_m"),
            "centerline": [[round(v["x"], 2), round(v["z"], 2)] for v in way["vertices"]],
            "deck_y": [v["y"] for v in way["vertices"]],
            # terrain along the centreline (station, y) every few metres: where the approach
            # roads are at the ends, and what a pier stands on between them
            "ground_profile": ground_profile(way["vertices"], sampler) if sampler else None,
            # the same at just the two ends
            "ground": ([round(sampler.at(way["vertices"][0]["x"], way["vertices"][0]["z"]), 2),
                        round(sampler.at(way["vertices"][-1]["x"], way["vertices"][-1]["z"]), 2)]
                       if sampler else None),
            "composed": os.path.exists(os.path.join(directory, f"{way['id']}.json")),
        })
    return out


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
            prefix = "/game-save/"
            saver, target = save, composed_dir
            if self.path.startswith("/game-save-bridge/"):
                prefix, saver, target = "/game-save-bridge/", save_bridge, bridges_dir
            if not self.path.startswith(prefix):
                return self._reply(404, "not found")
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            if self.headers.get("X-Composer") != "1" or (origin and origin.split("://", 1)[-1] != host):
                return self._reply(403, "not from Composer")
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._reply(411, "length required")
            if length <= 0 or length > MAX_BYTES:
                return self._reply(413, "too large")
            try:
                saver(self.path[len(prefix):], self.rfile.read(length), target)
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
