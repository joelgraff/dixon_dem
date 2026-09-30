#!/bin/sh
# Template resolver plus the in-game help and building-editor functions.
set -e
root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
godot=${GODOT:-$HOME/AppImage/Godot_v4.6-stable_linux.x86_64}
"$root/.venv/bin/python" "$root/pipeline/buildings/test_templates.py"
"$root/.venv/bin/python" "$root/pipeline/buildings/test_composer.py"
"$root/.venv/bin/python" "$root/pipeline/buildings/test_composed.py"
"$godot" --headless --path "$root/game" res://tools/tools_selftest.tscn
