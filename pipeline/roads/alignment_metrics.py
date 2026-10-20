#!/usr/bin/env python3
"""How accurate the road alignments are, measured on the 2025 aerial, one snapshot per build.

build_alignments.py appends a snapshot to docs/review/alignment_metrics.json after every run, so
Bridge Composer's Alignments mode can show whether a batch of edits moved the whole model (not
just the places edited). The measure is the aerial width survey's: for each street block whose
pavement edges were found ("counted"), how far the pavement's centre lies from the alignment.
Plain Python (the server reads the file; no numpy).

  python3 alignment_metrics.py --baseline   adds a snapshot of the alignments.json on disk
"""
import datetime
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
METRICS_PATH = os.path.join(ROOT, "docs", "review", "alignment_metrics.json")
ALIGNMENTS_PATH = os.path.join(ROOT, "game", "data", "alignments.json")
OVERRIDES_PATH = os.path.join(HERE, "alignment_overrides.json")
OFF_CENTRE_M = 2.0       # build_alignments / aerial_width.RECENTRE_FLAG_M
KEEP = 60


def snapshot(doc, overrides=None, built=None):
    """The accuracy numbers of an alignments.json document (dict), or None without a width survey."""
    centres = []
    for r in doc["routes"]:
        for b in r.get("width", {}).get("block_detail", []):
            if b.get("counts"):
                centres.append(abs(b["centre"]))
    if not centres:
        return None
    centres.sort()
    n = len(centres)
    devs = sorted(r["deviation"]["max_m"] for r in doc["routes"])
    pins = (overrides or {}).get("horizontal", [])
    widths = [t for t in (overrides or {}).get("templates", []) if t.get("source") is None and "curb_to_curb_ft" in t]
    return {
        "built": built or datetime.datetime.now().isoformat(timespec="seconds"),
        "routes": len(doc["routes"]),
        "pinned_routes": len({p["route"] for p in pins}),
        "width_pins": len(widths),
        "blocks_counted": n,
        "centre_offset_m": {"median": round(statistics.median(centres), 3), "mean": round(sum(centres) / n, 3),
                            "p90": round(centres[min(n - 1, int(0.9 * n))], 3)},
        "within_1m_pct": round(100.0 * sum(1 for c in centres if c <= 1.0) / n, 1),
        "within_2m_pct": round(100.0 * sum(1 for c in centres if c <= 2.0) / n, 1),
        "off_centre_over_2m": sum(1 for c in centres if c > OFF_CENTRE_M),
        "off_centre_ids": ["offc:%s:%d" % (b["route"], round(b["sta"][0])) for b in doc.get("off_centre_blocks", [])],
        "deviation_max_m": {"median": round(devs[len(devs) // 2], 3), "max": round(devs[-1], 3)},
    }


def load(path=METRICS_PATH):
    try:
        with open(path) as handle:
            doc = json.load(handle)
        if doc.get("format") == "dixon-alignment-metrics":
            return doc
    except (OSError, ValueError):
        pass
    return {"format": "dixon-alignment-metrics", "version": 1, "history": []}


def append(snap, path=METRICS_PATH):
    if snap is None:
        return None
    doc = load(path)
    doc["history"] = (doc["history"] + [snap])[-KEEP:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(doc, handle, indent=1)
        handle.write("\n")
    return snap


def main(argv):
    if "--baseline" not in argv:
        print(__doc__)
        return 1
    with open(ALIGNMENTS_PATH) as handle:
        doc = json.load(handle)
    # the pins counted are those the build used, which the file on disk cannot say: a baseline has none
    snap = snapshot(doc)
    snap["label"] = "baseline: the alignments as last built, before any edits made in the editor"
    print(json.dumps(append(snap), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
