#!/usr/bin/env python3
"""Regenerate all Dixon data-pipeline outputs from data/raw + dems/, in order.

Usage:
    ../.venv/bin/python build_all.py [--force-fetch]

Idempotent: fetch_osm.py skips categories already downloaded to data/raw/
unless --force-fetch is passed; build_heightmap.py / build_vectors.py /
render_preview.py always regenerate their outputs (cheap: ~10-20s total).
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent


def run(script, *args):
    print(f"\n=== {script} {' '.join(args)} ===", flush=True)
    t0 = time.time()
    result = subprocess.run([sys.executable, str(HERE / script), *args])
    if result.returncode != 0:
        print(f"FAILED: {script} (exit {result.returncode})")
        sys.exit(result.returncode)
    print(f"--- {script} done in {time.time() - t0:.1f}s ---")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-fetch", action="store_true", help="refetch OSM data even if data/raw/osm_*.json already exist")
    args = ap.parse_args()

    fetch_args = ["--force"] if args.force_fetch else []
    run("fetch_osm.py", *fetch_args)
    run("build_heightmap.py")
    run("build_vectors.py")
    run("render_preview.py")
    print("\nAll pipeline outputs regenerated.")


if __name__ == "__main__":
    main()
