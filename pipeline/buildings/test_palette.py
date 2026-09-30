"""The material manifest Building Composer reads matches the palette, and the
Composer server hands it out."""
import json
import os
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import composed
import palette

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "game", "tools"))
import composer_server  # noqa: E402


def test_manifest_lists_every_material_once():
    entries = palette.manifest()["materials"]
    assert [m["name"] for m in entries] == list(palette.MATERIALS)
    for m in entries:
        assert m["label"], m
        assert m["categories"] and all(isinstance(c, str) for c in m["categories"]), m
        assert m["color"].startswith("#") and len(m["color"]) == 7, m
        assert m["resource"] == palette.MATERIALS[m["name"]]
    assert set(palette.CATEGORIES) == set(palette.MATERIALS)
    assert set(palette.LABELS) == set(palette.MATERIALS)


def test_hash_follows_the_vocabulary():
    before = palette.manifest()["hash"]
    palette.CATEGORIES["awning"] = ["accent", "wall"]
    try:
        assert palette.manifest()["hash"] != before
    finally:
        palette.CATEGORIES["awning"] = ["accent"]
    assert palette.manifest()["hash"] == before


def test_committed_manifest_is_current():
    with open(palette.MANIFEST_PATH) as handle:
        assert json.load(handle) == palette.manifest(), "run pipeline/buildings/palette.py"


def test_far_tint_uses_wall_materials():
    assert "brick_buff" in composed.WALL_MATERIALS
    assert "roof_metal" in composed.WALL_MATERIALS
    assert "shingles_dark" not in composed.WALL_MATERIALS
    assert "window_lit" not in composed.WALL_MATERIALS


def test_server_serves_the_manifest():
    handler = composer_server.make_handler(os.path.dirname(__file__), os.devnull, palette.MANIFEST_PATH)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    handler.log_message = lambda *args: None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/game-materials"
        with urllib.request.urlopen(url) as reply:
            assert reply.headers["Content-Type"] == "application/json"
            assert reply.headers["Cache-Control"] == "no-cache"
            assert json.load(reply) == palette.manifest()
        with urllib.request.urlopen(url.replace("/game-materials", "/test_palette.py")) as reply:
            assert reply.headers["Cache-Control"] == "no-cache", "Composer's own files are revalidated too"
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    test_manifest_lists_every_material_once()
    test_hash_follows_the_vocabulary()
    test_committed_manifest_is_current()
    test_far_tint_uses_wall_materials()
    test_server_serves_the_manifest()
    print("palette ok")
