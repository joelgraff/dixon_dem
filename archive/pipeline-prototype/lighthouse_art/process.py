"""Resize generated backgrounds and enforce exact indexed EGA colors."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .palette import DEFAULT_PALETTE, PALETTES, TARGET_SIZE, Color, hex_color


def _palette_image(colors: tuple[Color, ...]) -> Image.Image:
    palette = Image.new("P", (1, 1))
    values = [channel for _, rgb in colors for channel in rgb]
    palette.putpalette(values + [0] * (768 - len(values)))
    return palette


RESAMPLE_FILTERS = {
    "nearest": Image.Resampling.NEAREST,
    "box": Image.Resampling.BOX,
    "lanczos": Image.Resampling.LANCZOS,
}
DITHER_MODES = {
    "none": Image.Dither.NONE,
    "floyd-steinberg": Image.Dither.FLOYDSTEINBERG,
}


def process_background(
    source: str | Path,
    destination: str | Path,
    palette_key: str = DEFAULT_PALETTE,
    dither: str = "none",
    resample: str = "box",
) -> dict[str, Any]:
    """Write a 320x200 paletted PNG and a JSON report; crop to the target aspect.

    Dithering is off by default: error diffusion on a downscaled image turns
    blended in-between colors into noise, which is wrong for sources that are
    already pixel art with a limited palette.
    """
    selected = PALETTES[palette_key]
    colors = selected.colors
    source_path = Path(source).resolve()
    output_path = Path(destination).resolve()
    if source_path == output_path:
        raise ValueError("Input and output paths must be different.")

    with Image.open(source_path) as original:
        fitted = ImageOps.fit(
            original.convert("RGB"),
            TARGET_SIZE,
            method=RESAMPLE_FILTERS[resample],
            centering=(0.5, 0.5),
        )
        indexed = fitted.quantize(
            palette=_palette_image(colors),
            dither=DITHER_MODES[dither],
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts = Counter(indexed.getdata())
    off_palette_pixels = sum(
        count for index, count in counts.items() if index >= len(colors)
    )
    if off_palette_pixels:
        raise RuntimeError(
            f"Palette quantization produced {off_palette_pixels} off-palette pixels."
        )

    indexed.save(output_path, format="PNG", optimize=False)
    used_colors = [
        {
            "index": index,
            "name": colors[index][0],
            "rgb": list(colors[index][1]),
            "hex": hex_color(colors[index][1]),
            "pixels": count,
        }
        for index, count in sorted(counts.items())
    ]
    report: dict[str, Any] = {
        "source": str(source_path),
        "output": str(output_path),
        "size": list(TARGET_SIZE),
        "mode": "P",
        "palette": selected.label,
        "palette_key": selected.key,
        "dithering": dither,
        "resample": resample,
        "used_color_count": len(used_colors),
        "off_palette_pixels": off_palette_pixels,
        "used_colors": used_colors,
    }
    report_path = output_path.with_name(f"{output_path.stem}-palette-report.json")
    report_path.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
