"""Bridge Composer's Alignments mode on the server: routes, saving a pin, the review queue.

Run with: ../../.venv/bin/python test_alignment_editor.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "game" / "tools"))
import alignment as al  # noqa: E402
import alignment_editor as ae  # noqa: E402
import composer_server  # noqa: E402
import horizontal_overrides as ho  # noqa: E402
from aerial_crop import Aerial  # noqa: E402  (pipeline/aerial is on composer_server's path)


def route(rid, pis, radii, name, blocks=()):
    a = al.Alignment(pis, radii)
    rec = {"id": rid, "name": name, "names": [name], "highway": "residential", "class": "local", "oneway": False,
           "closed": False, "ways": [], "bridges": [], "deviation": {"max_m": 0.4, "p95_m": 0.3, "over_tol": False},
           "fit": {}, "osm": [[x + 0.5, z] for x, z in pis]}
    rec.update(a.to_json())
    if blocks:
        rec["width"] = {"blocks": len(blocks), "block_detail": [{"sta": b, "counts": True, "centre": 0.1} for b in blocks]}
    return rec


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        d = self.dir
        doc = {"format": "dixon-alignments", "version": 1, "junctions": [], "routes": [
            route("R1", [(0, 0), (100, 0), (100, 100)], [0, 20, 0], "First Street", [[0, 60], [60, 120]]),
            route("R2", [(500, 500), (600, 500)], [0, 0], "Far Street", [[0, 100]]),
        ]}
        doc["junctions"] = [{"node_id": 1, "legs": [{"route": "R1", "sta": 60.0, "through": True}, {"route": "R2", "sta": 0.0, "through": False}]}]
        (d / "alignments.json").write_text(json.dumps(doc))
        (d / "templates.json").write_text(json.dumps({"routes": {"R1": [
            {"sta": [0, 120], "curb_to_curb_m": 9.1, "section": "residential", "bridge": False}]}}))
        (d / "overrides.json").write_text(json.dumps({"format": "dixon-alignment-overrides", "version": 1, "profile": [], "templates": []}))
        (d / "report.json").write_text(json.dumps({"off_centre_blocks": [
            {"route": "R1", "name": "First Street", "sta": [0, 60], "centre_m": -3.4, "at": [30.0, 0.0]}]}))
        audit = d / "audit"
        audit.mkdir()
        (audit / "roofless_review.json").write_text(json.dumps({"flagged": [
            {"id": "800002406", "source": "ms", "why": "bare", "area_m2": 161.3, "at": [10.0, 5.0]}]}))
        (audit / "street_overlaps.json").write_text(json.dumps({"manual_review": [
            {"id": "800001014", "source": "ms", "at": [1500.4, -1316.0], "street": None, "look_at": "check it"}],
            "buildings": []}))
        self.review = d / "review" / "alignment_review.json"
        self.routes = ae.Routes(str(d / "alignments.json"), str(d / "templates.json"), str(d / "overrides.json"))
        handler = composer_server.make_handler(
            str(d), os.devnull, aerial=Aerial(str(d)), outlines=composer_server.Outlines(str(d), str(d / "none")),
            routes=self.routes, overrides_path=str(d / "overrides.json"), review_path=str(self.review),
            report_path=str(d / "report.json"), audit_dir=str(audit), metrics_path=str(d / "metrics.json"))
        handler.log_message = lambda *a: None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.dir)

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as reply:
            return json.load(reply)

    def post(self, path, body, headers=None, raw=False):
        h = {"X-Composer": "1", "Content-Type": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=body if raw else json.dumps(body).encode(), headers=h)
        try:
            with urllib.request.urlopen(req) as reply:
                return reply.status, reply.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode()


class Routes(Fixture):
    def test_summaries_and_the_box(self):
        rows = self.get("/game-alignments")["routes"]
        self.assertEqual([r["id"] for r in rows], ["R1", "R2"])
        os.utime(self.dir / "alignments.json", (3e9, 3e9))
        self.assertFalse(self.get("/game-alignments")["unpublished"])
        os.utime(self.dir / "overrides.json", (4e9, 4e9))
        self.assertTrue(self.get("/game-alignments")["unpublished"])
        self.assertEqual(rows[0]["bbox"], [0.0, 0.0, 100.5, 100.0])
        self.assertNotIn("pis", rows[0])
        near = self.get("/game-alignments?x0=-10&z0=-10&x1=50&z1=50")["routes"]
        self.assertEqual([r["id"] for r in near], ["R1"])
        r = near[0]
        self.assertEqual(r["radii"], [0.0, 20.0, 0.0])
        self.assertEqual([e["type"] for e in r["elements"]], ["tangent", "arc", "tangent"])
        self.assertEqual(r["ranges"][0]["curb_to_curb_m"], 9.1)
        self.assertEqual(len(r["osm"]), 3)
        self.assertNotIn("block_detail", r["width"])
        self.assertEqual(self.get("/game-alignment/R2")["name"], "Far Street")
        self.assertEqual(r["junctions"], [60.0])
        for bad, code in (("/game-alignment/R9", 404), ("/game-alignment/..x", 400), ("/game-alignments?x0=1", 400)):
            with self.assertRaises(urllib.error.HTTPError, msg=bad) as ctx:
                self.get(bad)
            self.assertEqual(ctx.exception.code, code, bad)

    def test_nearest_route(self):
        self.assertEqual(self.routes.nearest(50, 3), "R1")
        self.assertEqual(self.routes.nearest(550, 505), "R2")
        self.assertIsNone(self.routes.nearest(300, 300))

    def test_saving_pins_the_route_and_shows_as_an_override(self):
        body = {"pis": [[0, 0], [100, 0], [100, 100]], "radii": [0, 25, 0], "note": "traced on the aerial"}
        code, _ = self.post("/game-save-alignment/R1", body)
        self.assertEqual(code, 200)
        doc = ho.load(str(self.dir / "overrides.json"))
        self.assertEqual(doc["horizontal"][0]["route"], "R1")
        self.assertEqual(doc["horizontal"][0]["radii"], [0, 25, 0])
        self.assertEqual(self.get("/game-alignment/R1")["override"]["radii"], [0, 25, 0])
        self.assertEqual(self.get("/game-alignments")["routes"][0]["override"], True)
        self.assertEqual(self.post("/game-delete-alignment/R1", {})[0], 200)
        self.assertNotIn("override", self.get("/game-alignment/R1"))

    def test_width_pins_are_saved_with_a_note_and_shown(self):
        body = {"sta": [0, 60], "curb_to_curb_ft": 34, "note": "measured on the aerial"}
        self.assertEqual(self.post("/game-save-width/R1", body)[0], 200)
        self.assertEqual(self.post("/game-save-width/R1", dict(body, curb_to_curb_ft=30))[0], 200)   # same range: replaced
        doc = ho.load(str(self.dir / "overrides.json"))
        self.assertEqual([(t["sta"], t["curb_to_curb_ft"]) for t in doc["templates"]], [([0.0, 60.0], 30.0)])
        self.assertEqual(self.get("/game-alignment/R1")["width_pins"][0]["note"], "measured on the aerial")
        for bad in (dict(body, note=""), dict(body, curb_to_curb_ft=3), dict(body, curb_to_curb_ft=500),
                    dict(body, sta=[60, 0]), dict(body, sta=[-1, 5])):
            self.assertEqual(self.post("/game-save-width/R1", bad)[0], 400, bad)
        self.assertEqual(self.post("/game-save-width/R9", body)[0], 400)

    def test_saves_are_checked(self):
        ok = {"pis": [[0, 0], [100, 0], [100, 100]], "radii": [0, 25, 0], "note": "n"}
        for body, headers in ((dict(ok, radii=[0, -1, 0]), None), (dict(ok, radii=[0, 500, 0]), None),
                              (dict(ok, note=""), None), (dict(ok, route="R2"), None), (dict(ok, pis=[[0, 0]]), None),
                              (ok, {"X-Composer": "0"}), (ok, {"Origin": "http://evil.example"})):
            code, text = self.post("/game-save-alignment/R1", body, headers)
            self.assertIn(code, (400, 403), (body, text))
        self.assertEqual(self.post("/game-save-alignment/R9", ok)[0], 400)           # not a route
        self.assertEqual(self.post("/game-save-alignment/R1", b"nope", raw=True)[0], 400)
        self.assertNotIn("R1", [e["route"] for e in ho.entries(ho.load(str(self.dir / "overrides.json")))])


class Metrics(Fixture):
    def test_snapshot_counts_the_aerial_survey_and_history_is_served(self):
        import alignment_metrics as am
        doc = json.loads((self.dir / "alignments.json").read_text())
        doc["off_centre_blocks"] = [{"route": "R1", "sta": [0, 60], "centre_m": 3.0}]
        doc["routes"][0]["width"]["block_detail"][0]["centre"] = 3.0
        doc["routes"][0]["width"]["block_detail"][1]["centre"] = -0.4
        snap = am.snapshot(doc, {"horizontal": [{"route": "R1"}], "templates": [{"route": "R1", "curb_to_curb_ft": 30}, {"route": "R1", "source": "building_faces"}]})
        self.assertEqual((snap["pinned_routes"], snap["width_pins"], snap["blocks_counted"]), (1, 1, 3))
        self.assertEqual(snap["off_centre_over_2m"], 1)
        self.assertEqual(snap["off_centre_ids"], ["offc:R1:0"])
        self.assertAlmostEqual(snap["within_1m_pct"], 66.7, places=1)
        self.assertEqual(self.get("/game-metrics")["history"], [])
        am.append(snap, str(self.dir / "metrics.json"))
        self.assertEqual(self.get("/game-metrics")["history"][0]["blocks_counted"], 3)
        no_survey = {"routes": [route("R9", [(0, 0), (1, 1)], [0, 0], "x")]}
        self.assertIsNone(am.snapshot(no_survey))


class Review(Fixture):
    def queue(self, query=""):
        return self.get("/game-review-queue" + query)

    def test_sample_is_seeded_and_flagged_places_follow(self):
        q = self.queue("?sample=2&seed=3")
        kinds = [i["kind"] for i in q["items"]]
        self.assertEqual(kinds, ["sample", "sample", "off_centre", "roofless", "street_overlap"])
        again = self.queue("?sample=2&seed=3")["items"]
        self.assertEqual([i["id"] for i in again], [i["id"] for i in q["items"]])
        a = self.queue("?sample=1&seed=1")["items"][0]
        self.assertEqual(a["kind"], "sample")
        x, z = a["at"]
        self.assertTrue(-1 < x < 700 and -1 < z < 600)
        self.assertEqual(self.queue("?sample=0&kinds=roofless")["items"][0]["id"], "roofless:800002406")
        self.assertEqual(self.queue("?sample=0&kinds=off_centre")["items"][0]["why"], "pavement centre -3.4 m off the alignment")

    def test_a_sample_larger_than_the_blocks_returns_them_all(self):
        self.assertEqual(len(self.queue("?sample=99&kinds=sample")["items"]), 3)

    def test_verdicts_are_stored_and_come_back_with_the_queue(self):
        item = {"id": "offc:R1:0", "status": "wrong", "note": "OSM 3 m south of the pavement", "kind": "off_centre",
                "route": "R1", "sta": [0, 60], "at": [30, 0]}
        code, _ = self.post("/game-review", item)
        self.assertEqual(code, 200)
        doc = json.loads(self.review.read_text())
        self.assertEqual(doc["format"], "dixon-alignment-review")
        self.assertEqual(doc["items"]["offc:R1:0"]["status"], "wrong")
        self.assertEqual(doc["items"]["offc:R1:0"]["at"], [30.0, 0.0])
        self.assertRegex(doc["items"]["offc:R1:0"]["reviewed"], r"^\d{4}-\d\d-\d\d$")
        q = self.queue("?sample=0&kinds=off_centre")
        self.assertEqual(q["items"][0]["result"]["note"], "OSM 3 m south of the pavement")
        self.assertEqual(q["reviewed_total"], 1)
        self.post("/game-review", {"id": "offc:R1:0", "status": "fixed", "note": "pinned"})
        self.assertEqual(json.loads(self.review.read_text())["items"]["offc:R1:0"]["status"], "fixed")
        self.post("/game-review", {"id": "offc:R1:0", "status": ""})
        self.assertEqual(json.loads(self.review.read_text())["items"], {})

    def test_bad_verdicts_are_refused(self):
        for body in ({"id": "x y", "status": "ok"}, {"id": "a", "status": "maybe"}, {"id": "a", "status": "ok", "note": 5},
                     {"id": "a", "status": "ok", "kind": "other"}, {"id": "a", "status": "ok", "at": [1]}, []):
            self.assertEqual(self.post("/game-review", body)[0], 400, body)
        self.assertFalse(self.review.exists())

    def test_missing_report_is_noted_not_fatal(self):
        os.remove(self.dir / "report.json")
        q = self.queue("?sample=0&kinds=off_centre")
        self.assertEqual(q["items"], [])
        self.assertTrue(q["notes"])


if __name__ == "__main__":
    unittest.main()
