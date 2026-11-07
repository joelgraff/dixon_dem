from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from lighthouse_art.palette import EGA_COLORS, PALETTES, TARGET_SIZE
from lighthouse_art.process import process_background
from lighthouse_art.prompts import NEGATIVE_PROMPT, build_prompt
from lighthouse_art.sprites import process_sprite_sheet
from lighthouse_parser.scene_card import load_scene_card

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCENE = load_scene_card(PROJECT_DIR / "scene-card.md")


class PromptTests(unittest.TestCase):
    def test_prompt_uses_concrete_pixel_art_constraints_and_scene_layout(self) -> None:
        prompt = build_prompt(SCENE)
        self.assertIn("320x200 (16:10)", prompt)
        self.assertIn("16-color IBM EGA palette", prompt)
        self.assertIn("checkerboard and cluster dithering", prompt)
        self.assertIn("door and brass telescope on the left", prompt)
        self.assertIn("lantern on a wall shelf to the right", prompt)
        self.assertIn(NEGATIVE_PROMPT, prompt)

    def test_prompt_lists_all_sixteen_rgb_colors(self) -> None:
        prompt = build_prompt(SCENE)
        for _, (red, green, blue) in EGA_COLORS:
            self.assertIn(f"#{red:02X}{green:02X}{blue:02X}", prompt)


class BackgroundProcessingTests(unittest.TestCase):
    def test_processing_outputs_320_by_200_indexed_ega_png_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "generated.png"
            output = Path(directory) / "plate.png"
            image = Image.new("RGB", (640, 400))
            for x in range(image.width):
                for y in range(image.height):
                    image.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
            image.save(source)

            report = process_background(source, output, dither="floyd-steinberg")
            with Image.open(output) as processed:
                self.assertEqual(processed.size, TARGET_SIZE)
                self.assertEqual(processed.mode, "P")
                self.assertEqual(set(processed.getdata()), set(range(16)))
                actual_colors = set(processed.convert("RGB").getdata())

            ega_colors = {rgb for _, rgb in EGA_COLORS}
            self.assertLessEqual(actual_colors, ega_colors)
            self.assertEqual(report["off_palette_pixels"], 0)
            self.assertEqual(report["used_color_count"], 16)
            report_path = output.with_name("plate-palette-report.json")
            self.assertEqual(
                json.loads(report_path.read_text(encoding="utf-8")),
                report,
            )

    def test_on_palette_source_is_unchanged_without_dithering(self) -> None:
        colors = [rgb for _, rgb in EGA_COLORS]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pixel-art.png"
            output = Path(directory) / "plate.png"
            image = Image.new("RGB", TARGET_SIZE)
            for x in range(TARGET_SIZE[0]):
                for y in range(TARGET_SIZE[1]):
                    image.putpixel((x, y), colors[(x // 8 + y // 8) % 16])
            image.save(source)

            process_background(source, output)
            with Image.open(output) as processed:
                self.assertEqual(
                    list(processed.convert("RGB").getdata()),
                    list(image.getdata()),
                )

    def test_source_image_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "generated.png"
            Image.new("RGB", (320, 200), (255, 255, 255)).save(source)

            with self.assertRaisesRegex(ValueError, "must be different"):
                process_background(source, source)


class Ega32Tests(unittest.TestCase):
    def test_extended_palette_has_32_unique_colors_on_the_ega_master_grid(self) -> None:
        colors = [rgb for _, rgb in PALETTES["ega32"].colors]
        self.assertEqual(len(colors), 32)
        self.assertEqual(len(set(colors)), 32)
        for rgb in colors:
            self.assertTrue(all(channel in (0, 85, 170, 255) for channel in rgb))

    def test_32_color_prompt_lists_all_colors_and_differs_from_16(self) -> None:
        prompt = build_prompt(SCENE, "ega32")
        self.assertIn("32 exact target colors", prompt)
        self.assertIn("32-color extended EGA", prompt)
        for _, (red, green, blue) in PALETTES["ega32"].colors:
            self.assertIn(f"#{red:02X}{green:02X}{blue:02X}", prompt)
        self.assertNotEqual(prompt, build_prompt(SCENE))

    def test_processing_with_32_colors_enforces_that_palette(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "generated.png"
            output = Path(directory) / "plate32.png"
            image = Image.new("RGB", (640, 400))
            for x in range(image.width):
                for y in range(image.height):
                    image.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
            image.save(source)

            report = process_background(source, output, "ega32", dither="floyd-steinberg")
            with Image.open(output) as processed:
                actual = set(processed.convert("RGB").getdata())

        self.assertLessEqual(actual, {rgb for _, rgb in PALETTES["ega32"].colors})
        self.assertGreater(report["used_color_count"], 16)
        self.assertEqual(report["palette_key"], "ega32")
        self.assertEqual(report["off_palette_pixels"], 0)


def _figure_sheet(path: Path, heights: list[list[int]], touching: bool = False) -> None:
    """Blurry-edged figures on a navy backdrop: gray body, brown boots, a detached lamp."""
    gap = 0 if touching else 30
    cell_width, cell_height = 80, max(max(row) for row in heights) + gap
    image = Image.new("RGB", (cell_width * max(map(len, heights)), cell_height * len(heights)), (8, 12, 140))
    for row, row_heights in enumerate(heights):
        for column, height in enumerate(row_heights):
            left = column * cell_width + 25
            bottom = (row + 1) * cell_height - gap // 2 - 1
            for y in range(bottom - height + 1, bottom + 1):
                for x in range(left, left + 30):
                    boots = y > bottom - height // 6
                    image.putpixel((x, y), (165, 90, 10) if boots else (88, 84, 86))
            for y in range(bottom - height // 2, bottom - height // 2 + 6):
                for x in range(left + 33, left + 38):
                    image.putpixel((x, y), (250, 250, 90))
    image.save(path)


class SpriteSheetTests(unittest.TestCase):
    def test_frames_are_scaled_together_anchored_and_palette_locked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sheet.png"
            _figure_sheet(source, [[96, 96, 96], [96, 60]])
            report = process_sprite_sheet(source, Path(directory) / "out", contrast=0)

            self.assertEqual(report["frames_per_row"], [3, 2])
            self.assertAlmostEqual(report["scale"], 0.5)
            sizes = {frame["name"]: frame["size"] for frame in report["frames"]}
            self.assertEqual(sizes["r00_c00"][1], 48)
            # A crouch keeps its proportion to the standing frames.
            self.assertEqual(sizes["r01_c01"][1], 30)
            # The detached lamp joins its figure instead of becoming a frame.
            self.assertGreater(sizes["r00_c00"][0], 15)

            with Image.open(Path(directory) / "out" / "frames" / "r00_c00.png") as frame:
                self.assertEqual(frame.size, (32, 52))
                pixels = list(frame.getdata())
            opaque = {pixel[:3] for pixel in pixels if pixel[3] == 255}
            self.assertTrue(all(pixel[3] in (0, 255) for pixel in pixels))
            self.assertLessEqual(opaque, {rgb for _, rgb in EGA_COLORS})
            self.assertEqual({(85, 85, 85), (170, 85, 0), (255, 255, 85)}, opaque)
            # Feet rest on the anchor row, one pixel above the cell bottom.
            bottom = max(index // 32 for index, pixel in enumerate(pixels) if pixel[3])
            self.assertEqual(bottom, 50)

            with Image.open(Path(directory) / "out" / "sheet.png") as sheet:
                self.assertEqual(sheet.size, (96, 104))

    def test_grid_hint_separates_figures_that_touch_between_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sheet.png"
            _figure_sheet(source, [[96, 96], [96, 96], [96, 96]], touching=True)
            merged = process_sprite_sheet(source, Path(directory) / "auto", contrast=0)
            self.assertTrue(any("--grid" in warning for warning in merged["warnings"]))

            report = process_sprite_sheet(
                source, Path(directory) / "grid", grid=(2, 3), contrast=0
            )
            self.assertEqual(report["frames_per_row"], [2, 2, 2])
            self.assertEqual(report["warnings"], [])


if __name__ == "__main__":
    unittest.main()
