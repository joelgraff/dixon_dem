#!/usr/bin/env python3
"""Serves Building Composer and takes the buildings it sends back to the game.

  python3 game/tools/composer_server.py [--port 8000] [--dir ../building-composer]

Composer's "Send to game" POSTs to /game-save/<id>; the body is written to
game/data/composed/<id>.json, which pipeline/buildings/composed.py reads. The
server listens on 127.0.0.1 only, and a save must be same-origin (the page
sends a custom header, which a foreign page cannot add without a preflight this
server never answers), have a plain id, and be a composed building of
reasonable size.

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
import os
import re
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COMPOSED_DIR = os.path.join(ROOT, "game", "data", "composed")
MATERIALS_MANIFEST = os.path.join(ROOT, "game", "data", "materials_manifest.json")
sys.path[:0] = [os.path.join(ROOT, "pipeline", "buildings"), os.path.join(ROOT, "pipeline", "aerial")]
import footprints  # noqa: E402
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


def make_handler(directory, composed_dir, materials_manifest=MATERIALS_MANIFEST, aerial=None, outlines=None):
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
                save(self.path[len(prefix):], self.rfile.read(length), composed_dir)
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
