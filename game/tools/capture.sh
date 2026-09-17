#!/usr/bin/env bash
# Serialized GPU capture. Only one Godot render at a time across all agents.
# Usage: tools/capture.sh <res://scene.tscn> <abs shots.json> <abs out dir> [warmup_frames]
set -euo pipefail
GODOT="${GODOT:-$HOME/AppImage/Godot_v4.6-stable_linux.x86_64}"
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="$PROJ/../.locks/gpu.lock"
mkdir -p "$(dirname "$LOCK")" "$3"
exec flock -w 1800 "$LOCK" timeout 600 "$GODOT" --path "$PROJ" --resolution 1600x900 \
  res://tools/capture/capture_main.tscn -- --scene="$1" --shots="$2" --out="$3" --warmup="${4:-90}"
