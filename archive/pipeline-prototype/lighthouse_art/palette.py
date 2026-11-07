"""Named EGA-derived palettes used by the background pipeline."""

from __future__ import annotations

from dataclasses import dataclass

Color = tuple[str, tuple[int, int, int]]

EGA_COLORS: tuple[Color, ...] = (
    ("black", (0, 0, 0)),
    ("blue", (0, 0, 170)),
    ("green", (0, 170, 0)),
    ("cyan", (0, 170, 170)),
    ("red", (170, 0, 0)),
    ("magenta", (170, 0, 170)),
    ("brown", (170, 85, 0)),
    ("light gray", (170, 170, 170)),
    ("dark gray", (85, 85, 85)),
    ("bright blue", (85, 85, 255)),
    ("bright green", (85, 255, 85)),
    ("bright cyan", (85, 255, 255)),
    ("bright red", (255, 85, 85)),
    ("bright magenta", (255, 85, 255)),
    ("yellow", (255, 255, 85)),
    ("white", (255, 255, 255)),
)

# Sixteen more entries from the EGA 64-color master palette (each channel is
# 0, 85, 170, or 255). Weighted toward dark blues/teals for night scenes and
# warm mid-tones for lamplight and wood.
EGA_EXTRA_COLORS: tuple[Color, ...] = (
    ("navy", (0, 0, 85)),
    ("dark green", (0, 85, 0)),
    ("dark teal", (0, 85, 85)),
    ("maroon", (85, 0, 0)),
    ("dark purple", (85, 0, 85)),
    ("olive", (85, 85, 0)),
    ("steel blue", (0, 85, 170)),
    ("sea green", (0, 170, 85)),
    ("gray teal", (85, 170, 170)),
    ("sky blue", (85, 170, 255)),
    ("lavender", (170, 170, 255)),
    ("dusty rose", (170, 85, 85)),
    ("khaki", (170, 170, 85)),
    ("orange", (255, 170, 0)),
    ("peach", (255, 170, 85)),
    ("pale yellow", (255, 255, 170)),
)


@dataclass(frozen=True)
class Palette:
    key: str
    label: str
    colors: tuple[Color, ...]


PALETTES: dict[str, Palette] = {
    "ega16": Palette("ega16", "16-color IBM EGA", EGA_COLORS),
    "ega32": Palette(
        "ega32",
        "32-color extended EGA (16 standard + 16 from the 64-color master palette)",
        EGA_COLORS + EGA_EXTRA_COLORS,
    ),
}

DEFAULT_PALETTE = "ega16"
TARGET_SIZE = (320, 200)


def hex_color(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)
