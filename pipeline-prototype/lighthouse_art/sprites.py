"""Slice AI-generated character sheets into clean, palette-locked sprite cells.

Generated sheets are blurry, compressed, unevenly spaced, and drawn at an
arbitrary scale. This module finds each figure by its silhouette against the
flat backdrop, scales the whole sheet by one shared factor (so a crouch stays
shorter than a stand), and downsamples with a per-block majority vote over
palette indexes instead of averaging, which keeps flat color areas clean.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, deque
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps

from .palette import DEFAULT_PALETTE, PALETTES
from .process import _palette_image

DEFAULT_FIGURE_HEIGHT = 48
DEFAULT_CELL_SIZE = (32, 52)
PREVIEW_SCALE = 4
TRANSPARENT = -1


def _border_color(image: Image.Image) -> tuple[int, int, int]:
    """Most common color along the image edge, coarsened to absorb JPEG noise."""
    width, height = image.size
    pixels = image.load()
    edge = [(x, 0) for x in range(width)] + [(x, height - 1) for x in range(width)]
    edge += [(0, y) for y in range(height)] + [(width - 1, y) for y in range(height)]
    coarse = Counter(tuple(channel // 8 for channel in pixels[point]) for point in edge)
    bucket = coarse.most_common(1)[0][0]
    matches = [pixels[point] for point in edge if tuple(c // 8 for c in pixels[point]) == bucket]
    return tuple(round(statistics.fmean(rgb[i] for rgb in matches)) for i in range(3))


def _foreground_mask(
    image: Image.Image, background: tuple[int, int, int], tolerance: int
) -> Image.Image:
    """255 where a pixel differs from the backdrop by more than `tolerance` on any channel."""
    channels = [
        band.point(lambda value, ref=ref: 255 if abs(value - ref) > tolerance else 0)
        for band, ref in zip(image.split(), background)
    ]
    mask = channels[0]
    for channel in channels[1:]:
        mask = Image.composite(channel, mask, channel)
    return mask


def _components(mask: Image.Image, join: int) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of figures; `join` pixels of dilation keep props attached."""
    grown = mask.filter(ImageFilter.MaxFilter(join * 2 + 1)) if join else mask
    width, height = grown.size
    data = grown.load()
    seen = bytearray(width * height)
    boxes = []
    for start_y in range(height):
        for start_x in range(width):
            if seen[start_y * width + start_x] or not data[start_x, start_y]:
                continue
            seen[start_y * width + start_x] = 1
            queue = deque([(start_x, start_y)])
            left, top, right, bottom = start_x, start_y, start_x, start_y
            while queue:
                x, y = queue.popleft()
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < width and 0 <= ny < height:
                        index = ny * width + nx
                        if not seen[index] and data[nx, ny]:
                            seen[index] = 1
                            queue.append((nx, ny))
            boxes.append((left, top, right + 1, bottom + 1))
    # Shrink each box back to the undilated silhouette.
    tight = []
    for box in boxes:
        inner = mask.crop(box).getbbox()
        if inner:
            tight.append((box[0] + inner[0], box[1] + inner[1], box[0] + inner[2], box[1] + inner[3]))
    return tight


def _union(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    return (
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    )


def _attach_fragments(
    boxes: list[tuple[int, int, int, int]],
) -> tuple[list[tuple[int, int, int, int]], float]:
    """Merge detached props and specks into the figure they sit beside.

    Returns the figure boxes and the typical figure height. A fragment joins the
    figure whose box, padded by 15% of a figure height, contains its center;
    fragments near no figure are dropped as noise.
    """
    heights = sorted(box[3] - box[1] for box in boxes)
    tallest = heights[int(len(heights) * 0.9)]
    figures = [box for box in boxes if box[3] - box[1] >= tallest * 0.4]
    typical = statistics.median(box[3] - box[1] for box in figures)
    pad = typical * 0.15
    members = {index: [box] for index, box in enumerate(figures)}
    for box in boxes:
        if box in figures:
            continue
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        for index, figure in enumerate(figures):
            if figure[0] - pad <= cx <= figure[2] + pad and figure[1] - pad <= cy <= figure[3] + pad:
                members[index].append(box)
                break
    return [_union(group) for group in members.values()], typical


def _valleys(profile: list[int], count: int) -> list[int]:
    """`count + 1` cut positions: the emptiest line near each even grid division."""
    length = len(profile)
    step = length / count
    cuts = [0]
    for division in range(1, count):
        center = round(division * step)
        window = range(max(cuts[-1] + 1, round(center - step * 0.3)), min(length, round(center + step * 0.3)))
        cuts.append(min(window, key=lambda position: (profile[position], abs(position - center))))
    cuts.append(length)
    return cuts


def _grid_boxes(mask: Image.Image, columns: int, rows: int) -> list[list[tuple[int, int, int, int]]]:
    """Split on the emptiest lines near an expected grid, then box each cell's figure."""
    width, height = mask.size
    data = mask.load()
    row_profile = [sum(1 for x in range(width) if data[x, y]) for y in range(height)]
    row_cuts = _valleys(row_profile, rows)
    grid = []
    for top, bottom in zip(row_cuts, row_cuts[1:]):
        band = mask.crop((0, top, width, bottom))
        band_data = band.load()
        column_profile = [sum(1 for y in range(bottom - top) if band_data[x, y]) for x in range(width)]
        column_cuts = _valleys(column_profile, columns)
        row = []
        for left, right in zip(column_cuts, column_cuts[1:]):
            cell = mask.crop((left, top, right, bottom))
            pieces = _components(cell, 1)
            if not pieces:
                continue
            largest = max(pieces, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            figure, _ = _attach_fragments([largest] + [p for p in pieces if p != largest])
            box = figure[0]
            row.append((left + box[0], top + box[1], left + box[2], top + box[3]))
        grid.append(row)
    return grid


def _rows(boxes: list[tuple[int, int, int, int]]) -> list[list[tuple[int, int, int, int]]]:
    """Group boxes into reading-order rows by their bottom edge (the feet)."""
    if not boxes:
        return []
    typical = statistics.median(box[3] - box[1] for box in boxes)
    rows: list[list[tuple[int, int, int, int]]] = []
    for box in sorted(boxes, key=lambda b: b[3]):
        if rows and abs(box[3] - rows[-1][-1][3]) <= typical / 2:
            rows[-1].append(box)
        else:
            rows.append([box])
    return [sorted(row, key=lambda b: b[0]) for row in rows]


def _majority_downsample(
    indexes: list[int], size: tuple[int, int], target: tuple[int, int]
) -> list[int]:
    """Each output pixel takes the most common palette index in its source block."""
    width, height = size
    out_width, out_height = target
    result = []
    for out_y in range(out_height):
        y0 = int(out_y * height / out_height)
        y1 = max(y0 + 1, int((out_y + 1) * height / out_height))
        for out_x in range(out_width):
            x0 = int(out_x * width / out_width)
            x1 = max(x0 + 1, int((out_x + 1) * width / out_width))
            votes = Counter(
                indexes[y * width + x] for y in range(y0, y1) for x in range(x0, x1)
            )
            transparent = votes.pop(TRANSPARENT, 0)
            total = transparent + sum(votes.values())
            if not votes or transparent * 2 > total:
                result.append(TRANSPARENT)
            else:
                result.append(votes.most_common(1)[0][0])
    return result


def _despeckle(pixels: list[int], size: tuple[int, int]) -> list[int]:
    """Drop opaque pixels with no opaque neighbor; they read as noise at native size."""
    width, height = size
    cleaned = list(pixels)
    for y in range(height):
        for x in range(width):
            if pixels[y * width + x] == TRANSPARENT:
                continue
            neighbors = [
                pixels[ny * width + nx]
                for nx in (x - 1, x, x + 1)
                for ny in (y - 1, y, y + 1)
                if (nx, ny) != (x, y) and 0 <= nx < width and 0 <= ny < height
            ]
            if all(value == TRANSPARENT for value in neighbors):
                cleaned[y * width + x] = TRANSPARENT
    return cleaned


def process_sprite_sheet(
    source: str | Path,
    destination: str | Path,
    figure_height: int = DEFAULT_FIGURE_HEIGHT,
    cell_size: tuple[int, int] = DEFAULT_CELL_SIZE,
    palette_key: str = DEFAULT_PALETTE,
    tolerance: int = 40,
    background: tuple[int, int, int] | None = None,
    grid: tuple[int, int] | None = None,
    contrast: float = 1.0,
) -> dict[str, Any]:
    """Write per-frame RGBA PNGs, an assembled sheet, a 4x preview, and a JSON report.

    Figures are found as connected silhouettes. Sheets whose figures touch
    across rows need `grid` (columns, rows) as a hint; cuts then snap to the
    emptiest line near each expected division.
    `contrast` is the percent of figure pixels clipped at each end of an
    autocontrast stretch before palette snapping; generated sheets crowd their
    darks between EGA black and dark gray, which otherwise merges coat and trousers.
    The scale factor maps the sheet's median figure height to `figure_height`.
    Frames are bottom-centered on the anchor one pixel above the cell's lower edge.
    """
    colors = PALETTES[palette_key].colors
    output_dir = Path(destination)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    cell_width, cell_height = cell_size

    with Image.open(source) as opened:
        image = opened.convert("RGB")
    backdrop = background or _border_color(image)
    mask = _foreground_mask(image, backdrop, tolerance)
    colored = (
        ImageOps.autocontrast(image, cutoff=contrast, mask=mask, preserve_tone=True)
        if contrast else image
    )
    warnings: list[str] = []
    if grid:
        rows = [row for row in _grid_boxes(mask, *grid) if row]
        typical_height = statistics.median(b[3] - b[1] for row in rows for b in row)
    else:
        pieces = _components(mask, 1)
        if not pieces:
            raise ValueError("No figures found; try a lower --tolerance or pass --background.")
        boxes, typical_height = _attach_fragments(pieces)
        # A column of touching figures is far taller than the rest, or, when every
        # column touches, far taller than any single standing figure is wide.
        merged = [
            box for box in boxes
            if box[3] - box[1] > max(typical_height * 1.6, (box[2] - box[0]) * 4)
            or box[3] - box[1] > (box[2] - box[0]) * 6
        ]
        if merged:
            warnings.append(
                f"{len(merged)} silhouettes look like several touching figures; "
                "rerun with --grid COLUMNS ROWS"
            )
        rows = _rows(boxes)
    if not rows:
        raise ValueError("No figures found; try a lower --tolerance or pass --background.")
    scale = figure_height / typical_height

    palette_image = _palette_image(colors)
    anchor = (cell_width // 2, cell_height - 2)
    columns = max(len(row) for row in rows)
    sheet = Image.new("RGBA", (columns * cell_width, len(rows) * cell_height))
    frames: list[dict[str, Any]] = []

    for row_number, row in enumerate(rows):
        for column_number, box in enumerate(row):
            crop = colored.crop(box)
            crop_mask = mask.crop(box)
            quantized = list(crop.quantize(palette=palette_image, dither=Image.Dither.NONE).getdata())
            opaque = list(crop_mask.getdata())
            indexes = [index if alpha else TRANSPARENT for index, alpha in zip(quantized, opaque)]
            target = (
                max(1, round(crop.width * scale)),
                max(1, round(crop.height * scale)),
            )
            small = _despeckle(_majority_downsample(indexes, crop.size, target), target)

            frame = Image.new("RGBA", target)
            frame.putdata([
                (0, 0, 0, 0) if value == TRANSPARENT else (*colors[value][1], 255)
                for value in small
            ])
            name = f"r{row_number:02d}_c{column_number:02d}"
            if target[0] > cell_width or target[1] > anchor[1] + 1:
                warnings.append(f"{name} is {target[0]}x{target[1]} and was clipped to the cell")
            cell = Image.new("RGBA", cell_size)
            cell.paste(frame, (anchor[0] - target[0] // 2, anchor[1] + 1 - target[1]))
            cell.save(frames_dir / f"{name}.png")
            sheet.paste(cell, (column_number * cell_width, row_number * cell_height))
            frames.append({
                "name": name,
                "row": row_number,
                "column": column_number,
                "source_box": list(box),
                "size": list(target),
            })

    sheet.save(output_dir / "sheet.png")
    preview = Image.new("RGBA", sheet.size, (*colors[1][1], 255))
    preview.alpha_composite(sheet)
    preview.resize(
        (sheet.width * PREVIEW_SCALE, sheet.height * PREVIEW_SCALE), Image.Resampling.NEAREST
    ).save(output_dir / "preview.png")

    report: dict[str, Any] = {
        "source": str(Path(source).resolve()),
        "output": str(output_dir.resolve()),
        "palette_key": palette_key,
        "background": list(backdrop),
        "contrast_cutoff": contrast,
        "median_source_height": typical_height,
        "scale": round(scale, 4),
        "figure_height": figure_height,
        "cell_size": list(cell_size),
        "anchor": list(anchor),
        "rows": len(rows),
        "frames_per_row": [len(row) for row in rows],
        "frame_count": len(frames),
        "warnings": warnings,
        "frames": frames,
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
