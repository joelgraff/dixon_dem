#!/usr/bin/env python3
"""Serves Building Composer and takes the buildings it sends back to the game.

  python3 game/tools/composer_server.py [--port 8000] [--dir ../building-composer]

Composer's "Send to game" POSTs to /game-save/<id>; the body is written to
game/data/composed/<id>.json, which pipeline/buildings/composed.py reads. The
server listens on 127.0.0.1 only, and a save must be same-origin (the page
sends a custom header, which a foreign page cannot add without a preflight this
server never answers), have a plain id, and be a composed building of
reasonable size.
"""
import argparse
import json
import os
import re
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COMPOSED_DIR = os.path.join(ROOT, "game", "data", "composed")
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


def make_handler(directory, composed_dir):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def _reply(self, code, text):
            body = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
