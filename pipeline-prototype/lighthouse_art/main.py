"""Command-line tools for prompts, EGA background plates, and sprite sheets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lighthouse_parser.scene_card import load_scene_card

from .palette import DEFAULT_PALETTE, PALETTES
from .process import DITHER_MODES, RESAMPLE_FILTERS, process_background
from .prompts import build_prompt
from .sprites import DEFAULT_CELL_SIZE, DEFAULT_FIGURE_HEIGHT, process_sprite_sheet

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SCENE_CARD = PROJECT_DIR / "scene-card.md"


def _default_prompt_path(palette_key: str) -> Path:
    suffix = "" if palette_key == DEFAULT_PALETTE else f"-{palette_key}"
    return PROJECT_DIR / "prompts" / f"lighthouse-cottage{suffix}.txt"


def _default_output_path(palette_key: str) -> Path:
    name = "ega" if palette_key == DEFAULT_PALETTE else palette_key
    return PROJECT_DIR / "artifacts" / f"lighthouse-cottage-{name}.png"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a prompt or process a generated Sierra-era background."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    prompt_command = commands.add_parser("prompt", help="write a scene-specific AI prompt")
    prompt_command.add_argument("--scene-card", type=Path, default=DEFAULT_SCENE_CARD)
    prompt_command.add_argument("--palette", choices=sorted(PALETTES), default=DEFAULT_PALETTE)
    prompt_command.add_argument("--output", type=Path)

    process_command = commands.add_parser(
        "process",
        help="resize an AI-generated plate and enforce an EGA palette",
    )
    process_command.add_argument("--input", type=Path, required=True)
    process_command.add_argument("--palette", choices=sorted(PALETTES), default=DEFAULT_PALETTE)
    process_command.add_argument(
        "--dither", choices=sorted(DITHER_MODES), default="none",
        help="error-diffusion dithering (default: none)",
    )
    process_command.add_argument(
        "--resample", choices=sorted(RESAMPLE_FILTERS), default="box",
        help="downscale filter (default: box)",
    )
    process_command.add_argument("--output", type=Path)

    sprites_command = commands.add_parser(
        "sprites",
        help="slice a generated character sheet into palette-locked sprite cells",
    )
    sprites_command.add_argument("--input", type=Path, required=True)
    sprites_command.add_argument(
        "--output", type=Path, required=True, help="directory for frames, sheet, and report",
    )
    sprites_command.add_argument("--palette", choices=sorted(PALETTES), default=DEFAULT_PALETTE)
    sprites_command.add_argument(
        "--height", type=int, default=DEFAULT_FIGURE_HEIGHT,
        help=f"standing figure height in pixels (default: {DEFAULT_FIGURE_HEIGHT})",
    )
    sprites_command.add_argument(
        "--cell", type=int, nargs=2, metavar=("WIDTH", "HEIGHT"), default=DEFAULT_CELL_SIZE,
    )
    sprites_command.add_argument(
        "--tolerance", type=int, default=40,
        help="per-channel difference from the backdrop that counts as figure (default: 40)",
    )
    sprites_command.add_argument(
        "--background", type=lambda value: tuple(int(value.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)),
        help="backdrop color as #RRGGBB (default: detected from the image edge)",
    )
    sprites_command.add_argument(
        "--grid", type=int, nargs=2, metavar=("COLUMNS", "ROWS"),
        help="expected layout, for sheets whose figures touch between rows",
    )
    sprites_command.add_argument(
        "--contrast", type=float, default=1.0,
        help="percent clipped at each end of a contrast stretch before palette snapping; 0 disables (default: 1)",
    )

    args = parser.parse_args()
    if args.command == "prompt":
        scene = load_scene_card(args.scene_card)
        output = args.output or _default_prompt_path(args.palette)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(build_prompt(scene, args.palette) + "\n", encoding="utf-8")
        print(f"Wrote prompt to {output}")
        return

    if args.command == "sprites":
        report = process_sprite_sheet(
            args.input, args.output, args.height, tuple(args.cell), args.palette,
            args.tolerance, background=args.background,
            grid=tuple(args.grid) if args.grid else None, contrast=args.contrast,
        )
        report.pop("frames")
        print(json.dumps(report, indent=2))
        return

    output = args.output or _default_output_path(args.palette)
    report = process_background(
        args.input, output, args.palette, args.dither, args.resample
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
