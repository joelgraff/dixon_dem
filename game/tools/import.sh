#!/usr/bin/env bash
# Re-import assets (run after adding textures/models). Serialized with captures.
set -euo pipefail
GODOT="${GODOT:-$HOME/AppImage/Godot_v4.6-stable_linux.x86_64}"
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
exec flock -w 1800 "$PROJ/../.locks/gpu.lock" timeout 900 "$GODOT" --headless --path "$PROJ" --import
