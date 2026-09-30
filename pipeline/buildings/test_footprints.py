"""Outlines for Composer's footprint editor: sources, corrections, the aerial
under them, and the server's read-only endpoints."""
import json
import os
import pathlib
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import footprints

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "aerial"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "game", "tools"))
from aerial_crop import Aerial  # noqa: E402
import composer_server  # noqa: E402


def _game_data():
    root = pathlib.Path(tempfile.mkdtemp())
    (root / "buildings.json").write_text(json.dumps({"buildings": [
        {"id": 1, "footprint": [{"x": 0, "z": 0}, {"x": 10, "z": 0}, {"x": 10, "z": 8}, {"x": 0, "z": 8}, {"x": 0, "z": 0}]},
        {"id": 2, "footprint": [{"x": 50, "z": 0}, {"x": 60, "z": 0}, {"x": 60, "z": 8}, {"x": 50, "z": 8}]},
    ]}))
    (root / "buildings_curated.json").write_text(json.dumps({"buildings": [
        {"id": 990000001, "replaces": [2], "footprint": [{"x": 49, "z": 0}, {"x": 61, "z": 0}, {"x": 61, "z": 9}, {"x": 49, "z": 9}]},
    ]}))
    (root / "buildings_ms.json").write_text(json.dumps({"buildings": [
        {"id": 800000000, "source": "ms", "footprint": [{"x": 200, "z": 200}, {"x": 208, "z": 200}, {"x": 208, "z": 207}]},
    ]}))
    overrides = root / "footprint_overrides"
    overrides.mkdir()
    return root, overrides


def _override(bid, ring, **extra):
    return {"format": "dixon-footprint-override", "version": 1, "id": str(bid), "footprint": ring, **extra}


def test_outline_hash_matches_composers():
    # values from Building Composer's outlineHash (js/import.js) for the same outlines
    assert footprints.outline_hash([[0, 0], [10, 0], [10, 8], [0, 8]]) == "4-441db1ba"
    assert footprints.outline_hash([[508.1084971963428, -212.66817373503], [523.0946372608887, -213.5550960432738],
                                    [524.5302, -190.25], [509.4, -189.0005]]) == "4-6d277d9c"
    assert footprints.outline_hash([[1.0005, 2.0015], [5, 2], [5, 7.2495], [1, 7]]) == "4-1e9fc340"
    assert footprints.outline_hash([{"x": 10, "z": 8}, {"x": 0, "z": 8}, {"x": 0, "z": 0}, {"x": 10, "z": 0}]) == "4-441db1ba"


def test_sources_with_curated_traces_in_place():
    root, _ = _game_data()
    records = {r["id"]: r for r in footprints.load_sources(str(root))}
    assert set(records) == {"1", "990000001", "800000000"}
    assert records["1"]["footprint"] == [[0, 0], [10, 0], [10, 8], [0, 8]], "open ring"
    assert records["990000001"]["source"] == "curated"


def test_an_override_replaces_its_outline():
    root, overrides = _game_data()
    wider = [[0, 0], [11, 0], [11, 8], [0, 8]]
    base = footprints.outline_hash([[0, 0], [10, 0], [10, 8], [0, 8]])
    (overrides / "1.json").write_text(json.dumps(_override(1, wider, based_on={"source": "osm", "hash": base}, porches=[{"kind": "stoop"}])))
    warnings = []
    records = {r["id"]: r for r in footprints.all_outlines(str(root), str(overrides), warnings.append)}
    assert records["1"]["footprint"] == wider and records["1"]["override"] is True
    assert records["1"]["porches"] == [{"kind": "stoop"}]
    assert warnings == []


def test_an_override_on_a_changed_outline_is_used_with_a_warning():
    root, overrides = _game_data()
    (overrides / "1.json").write_text(json.dumps(_override(1, [[0, 0], [11, 0], [11, 8], [0, 8]], based_on={"hash": "4-00000000"})))
    warnings = []
    records = {r["id"]: r for r in footprints.all_outlines(str(root), str(overrides), warnings.append)}
    assert records["1"].get("override")
    assert "changed" in warnings[0]


def test_an_override_far_from_its_building_is_skipped():
    root, overrides = _game_data()
    # a re-fetch gave Microsoft id 800000000 to another building
    (overrides / "800000000.json").write_text(json.dumps(_override(800000000, [[900, 900], [910, 900], [910, 910], [900, 910]])))
    warnings = []
    records = {r["id"]: r for r in footprints.all_outlines(str(root), str(overrides), warnings.append)}
    assert not records["800000000"].get("override")
    assert "skipped" in warnings[0]


def test_outlines_in_a_box():
    root, _ = _game_data()
    records = footprints.load_sources(str(root))
    assert [r["id"] for r in footprints.in_box(records, -5, -5, 5, 5)] == ["1"]
    assert {r["id"] for r in footprints.in_box(records, 5, 0, 55, 5)} == {"1", "990000001"}


def _tiles():
    """Two 8 x 8 px tiles at 1 m a pixel, side by side: red from x 0 to 8, blue from 8 to 16."""
    from PIL import Image

    root = pathlib.Path(tempfile.mkdtemp())
    tiles = []
    for i, color in enumerate([(255, 0, 0), (0, 0, 255)]):
        name = f"tile_{i}"
        Image.new("RGB", (8, 8), color).save(root / f"{name}.png")
        tiles.append({"tile": name, "world_x0": 8.0 * i, "world_z0": -8.0, "world_x1": 8.0 * (i + 1), "world_z1": 0.0,
                      "size_px": [8, 8], "mpp": 1.0})
    (root / "index.json").write_text(json.dumps({"tiles": tiles, "mpp": 1.0, "tile_m": 8.0}))
    return str(root)


def test_aerial_crop_stitches_tiles_and_leaves_the_rest_clear():
    aerial = Aerial(_tiles())
    image = aerial.crop(4, -6, 12, -2, mpp=0.5)
    assert image.size == (16, 8)
    assert image.getpixel((2, 4)) == (255, 0, 0, 255)
    assert image.getpixel((13, 4)) == (0, 0, 255, 255)
    assert image.info["approximate"], "placed by recorded boxes"
    edge = aerial.crop(14, -2, 20, 2, mpp=1.0)
    assert edge.getpixel((1, 1)) == (0, 0, 255, 255) and edge.getpixel((5, 3)) == (0, 0, 0, 0), "no tile past x 16"
    outside = aerial.crop(17, 1, 20, 4, mpp=1.0)
    assert not outside.info["approximate"], "no tile placed"
    try:
        aerial.crop(0, 0, 100000, 10, mpp=0.25)
        assert False, "a huge crop is refused"
    except ValueError:
        pass


def test_aerial_crop_places_a_tile_by_its_mapping():
    """A tile whose picture is turned 90 degrees and shifted against its recorded box."""
    from PIL import Image

    root = pathlib.Path(tempfile.mkdtemp())
    picture = Image.new("RGB", (8, 8), (0, 128, 0))
    picture.putpixel((6, 1), (255, 255, 255))
    picture.save(root / "t.png")
    # pixel (px, py) shows world (x, z) = (100 + py, 50 - px): px = 50 - z, py = x - 100
    tile = {"tile": "t", "world_x0": 0.0, "world_z0": 0.0, "world_x1": 8.0, "world_z1": 8.0, "size_px": [8, 8], "mpp": 1.0,
            "pixel_from_world": [0.0, -1.0, 50.0, 1.0, 0.0, -100.0]}
    (root / "index.json").write_text(json.dumps({"tiles": [tile]}))
    image = Aerial(str(root)).crop(100, 42, 108, 50, mpp=1.0)
    assert not image.info["approximate"]
    # the white pixel (6, 1) spans world x 101-102, z 43-44: crop pixel (1, 1)
    assert image.getpixel((1, 1))[:3] == (255, 255, 255)
    assert image.getpixel((1, 2))[:3] == (0, 128, 0)
    assert image.getpixel((5, 5))[:3] == (0, 128, 0)
    assert Aerial(str(root)).crop(0, 0, 8, 8, mpp=1.0).getpixel((4, 4)) == (0, 0, 0, 0), "the recorded box is not used"


def _serve(**kwargs):
    handler = composer_server.make_handler(os.path.dirname(__file__), os.devnull, **kwargs)
    handler.log_message = lambda *args: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_server_serves_the_aerial_and_outlines():
    root, overrides = _game_data()
    server, base = _serve(aerial=Aerial(_tiles()), outlines=composer_server.Outlines(str(root), str(overrides)))
    try:
        with urllib.request.urlopen(f"{base}/game-aerial?x0=0&z0=-8&x1=16&z1=0&mpp=1") as reply:
            assert reply.headers["Content-Type"] == "image/png"
            assert reply.headers["X-Aerial-Approximate"] == "1"
            assert reply.read()[:4] == b"\x89PNG"
        with urllib.request.urlopen(f"{base}/game-footprints?x0=-1&z0=-1&x1=1&z1=1") as reply:
            assert [b["id"] for b in json.load(reply)["buildings"]] == ["1"]
        # an override written while the server runs is picked up
        (overrides / "1.json").write_text(json.dumps(_override(1, [[0, 0], [12, 0], [12, 8], [0, 8]])))
        os.utime(overrides / "1.json", (1e9, 2e9))
        with urllib.request.urlopen(f"{base}/game-footprints?x0=-1&z0=-1&x1=1&z1=1") as reply:
            assert json.load(reply)["buildings"][0]["footprint"][1] == [12, 0]
        for bad in ("/game-footprints?x0=1", "/game-aerial?x0=0&z0=0&x1=0&z1=0"):
            try:
                urllib.request.urlopen(base + bad)
                assert False, bad
            except urllib.error.HTTPError as error:
                assert error.code == 400, (bad, error.code)
    finally:
        server.shutdown()
        server.server_close()


def test_server_without_imagery_says_so():
    server, base = _serve(aerial=Aerial(tempfile.mkdtemp()))
    try:
        urllib.request.urlopen(f"{base}/game-aerial?x0=0&z0=0&x1=1&z1=1")
        assert False
    except urllib.error.HTTPError as error:
        assert error.code == 404
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    test_outline_hash_matches_composers()
    test_sources_with_curated_traces_in_place()
    test_an_override_replaces_its_outline()
    test_an_override_on_a_changed_outline_is_used_with_a_warning()
    test_an_override_far_from_its_building_is_skipped()
    test_outlines_in_a_box()
    test_aerial_crop_stitches_tiles_and_leaves_the_rest_clear()
    test_aerial_crop_places_a_tile_by_its_mapping()
    test_server_serves_the_aerial_and_outlines()
    test_server_without_imagery_says_so()
    print("footprints ok")
