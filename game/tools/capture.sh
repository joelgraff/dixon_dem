#!/usr/bin/env bash
# Serialized GPU capture. Only one Godot render at a time across all agents.
# Usage: tools/capture.sh <res://scene.tscn> <abs shots.json> <abs out dir> [warmup_frames] [extra capture_main args...]
# extra args pass straight through, e.g. --hide=Terrain,Roads for a diagnostic control shot.
#
# Timeout is scaled to the workload instead of a flat 600 s, because loading world.tscn
# (terrain chunks + road/building bakes) costs minutes before the first shot renders, and a
# healthy multi-shot run was getting killed. Budget = WORLD_BUDGET + per-shot allowance,
# clamped to CAPTURE_TIMEOUT_MAX. Override with CAPTURE_TIMEOUT=<seconds> for a one-off.
# The harness prints "scene load+instantiate N s" and per-shot seconds — use those numbers
# when tuning warmup or these budgets rather than guessing.
set -euo pipefail
GODOT="${GODOT:-$HOME/AppImage/Godot_v4.6-stable_linux.x86_64}"
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="$PROJ/../.locks/gpu.lock"
mkdir -p "$(dirname "$LOCK")" "$3"

WARMUP="${4:-90}"
if [[ -n "${CAPTURE_TIMEOUT:-}" ]]; then
  BUDGET="$CAPTURE_TIMEOUT"
else
  WORLD_BUDGET="${CAPTURE_WORLD_BUDGET:-420}"          # scene load/build headroom
  PER_SHOT="${CAPTURE_PER_SHOT:-45}"                    # generous per-shot allowance
  MAXT="${CAPTURE_TIMEOUT_MAX:-2700}"
  NSHOTS="$(grep -o '"name"' "$2" 2>/dev/null | wc -l)"
  [[ "$NSHOTS" -lt 1 ]] && NSHOTS=1
  BUDGET=$(( WORLD_BUDGET + NSHOTS * PER_SHOT + NSHOTS * WARMUP / 10 ))
  [[ "$BUDGET" -gt "$MAXT" ]] && BUDGET="$MAXT"
fi

# flock wait must exceed the run budget so a queued capture isn't dropped while waiting its turn.
exec flock -w $(( BUDGET * 3 )) "$LOCK" timeout "$BUDGET" "$GODOT" --path "$PROJ" --resolution 1600x900 \
  res://tools/capture/capture_main.tscn -- --scene="$1" --shots="$2" --out="$3" --warmup="$WARMUP" "${@:5}"
