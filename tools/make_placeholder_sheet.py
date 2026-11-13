"""Generate placeholder pixel art for the aquarium (Phase 4).

Everything is drawn procedurally with Pillow using only the colours in
``game/static/game/palette.json``, with hard edges and no anti-aliasing.

Outputs (into ``game/static/game/sprites/``):

* ``fish_goldie.png`` - 128x128 sheet, 4 columns (swim frames) x 4 rows
  (evolution stages: Fry, Juvenile, Adult, Elder). Fish face right.
* ``sand_tile.png``, ``rock.png``, ``light_ray.png``
* ``plant_a_0.png`` / ``plant_a_1.png``, ``plant_b_0.png`` / ``plant_b_1.png``
* ``bubble_0.png`` .. ``bubble_2.png``

Replace ``fish_goldie.png`` with hand-drawn art in the same layout and no code
changes are needed. See ``docs/art-guide.md``.

Usage:
    python tools/make_placeholder_sheet.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
PALETTE_PATH = ROOT / "game" / "static" / "game" / "palette.json"
OUT_DIR = ROOT / "game" / "static" / "game" / "sprites"

CELL = 32
FRAMES = 4
STAGES = 4

# Body width per stage: Fry is small, Elder nearly fills the cell.
STAGE_BODY_WIDTHS = [10, 16, 22, 28]


def load_palette() -> dict[str, str]:
    data = json.loads(PALETTE_PATH.read_text(encoding="utf-8"))
    colors = data["colors"]
    if not 16 <= len(colors) <= 32:
        raise SystemExit(f"palette must hold 16-32 colours, found {len(colors)}")
    return {f"c{index:02d}": value for index, value in enumerate(colors)}


def new_tile(width: int, height: int) -> Image.Image:
    return Image.new("RGBA", (width, height), (0, 0, 0, 0))


def draw_fish(tile: Image.Image, body_width: int, frame: int, palette: dict[str, str]) -> None:
    """Draw one fish into a 32x32 transparent tile, facing right."""
    draw = ImageDraw.Draw(tile)
    body_height = max(5, round(body_width * 0.62))
    x0 = (CELL - body_width) // 2
    y0 = (CELL - body_height) // 2
    x1 = x0 + body_width - 1
    y1 = y0 + body_height - 1
    center_y = (y0 + y1) // 2

    body = palette["c15"]  # gold
    shade = palette["c14"]  # orange
    belly = palette["c07"]  # cream
    fin = palette["c13"]  # coral
    ink = palette["c00"]  # ink

    # Tail: a triangle behind the body, wiggling by one pixel per frame.
    wiggle = (0, 1, 0, -1)[frame % FRAMES]
    tail_length = max(2, body_width // 5)
    tail_x = x0 - tail_length + wiggle
    tail_top = y0 + body_height // 3
    tail_bottom = y1 - body_height // 3
    draw.polygon(
        [(x0, tail_top), (tail_x, center_y + wiggle), (x0, tail_bottom)],
        fill=fin,
    )

    # Body with clipped corners so it reads as rounded at this size.
    draw.rectangle([x0 + 1, y0, x1 - 1, y1], fill=body)
    draw.rectangle([x0, y0 + 1, x1, y1 - 1], fill=body)

    # Belly highlight along the bottom.
    if body_height >= 7:
        draw.rectangle([x0 + 2, y1 - 1, x1 - 2, y1 - 1], fill=belly)

    # Dorsal fin.
    if body_width >= 12:
        fin_height = max(1, body_height // 4)
        draw.polygon(
            [
                (x0 + body_width // 3, y0),
                (x0 + body_width // 2, y0 - fin_height),
                (x0 + (2 * body_width) // 3, y0),
            ],
            fill=fin,
        )

    # A single shade stripe for the bigger stages.
    if body_width >= 16:
        stripe_x = x0 + body_width // 2
        draw.rectangle([stripe_x, y0 + 1, stripe_x, y1 - 2], fill=shade)

    # Eye and mouth on the leading (right) edge.
    eye_size = 2 if body_width >= 22 else 1
    eye_x = x1 - 2 - (eye_size - 1)
    eye_y = y0 + max(1, body_height // 3)
    draw.rectangle([eye_x, eye_y, eye_x + eye_size - 1, eye_y + eye_size - 1], fill=ink)
    draw.point((x1, center_y), fill=ink)


def build_fish_sheet(palette: dict[str, str]) -> Image.Image:
    sheet = new_tile(CELL * FRAMES, CELL * STAGES)
    for stage, body_width in enumerate(STAGE_BODY_WIDTHS):
        for frame in range(FRAMES):
            tile = new_tile(CELL, CELL)
            draw_fish(tile, body_width, frame, palette)
            sheet.paste(tile, (frame * CELL, stage * CELL), tile)
    return sheet


def build_sand_tile(palette: dict[str, str]) -> Image.Image:
    tile = new_tile(16, 16)
    draw = ImageDraw.Draw(tile)
    draw.rectangle([0, 0, 15, 15], fill=palette["c09"])
    for x, y in [(2, 3), (7, 1), (11, 5), (4, 9), (13, 11), (8, 13), (1, 14)]:
        draw.point((x, y), fill=palette["c10"])
    return tile


def build_rock(palette: dict[str, str]) -> Image.Image:
    tile = new_tile(16, 12)
    draw = ImageDraw.Draw(tile)
    draw.polygon([(1, 11), (3, 4), (7, 1), (12, 3), (15, 11)], fill=palette["c03"])
    draw.polygon([(3, 4), (7, 1), (12, 3), (9, 5), (5, 6)], fill=palette["c04"])
    draw.point((4, 9), fill=palette["c01"])
    draw.point((11, 8), fill=palette["c01"])
    return tile


def build_plant(palette: dict[str, str], height: int, frame: int, wide: bool) -> Image.Image:
    width = 16 if wide else 12
    tile = new_tile(width, height)
    draw = ImageDraw.Draw(tile)
    sway = 1 if frame else -1
    stem_x = width // 2
    draw.rectangle([stem_x, 2, stem_x, height - 1], fill=palette["c11"])

    leaf_rows = range(4, height - 2, 5)
    for index, y in enumerate(leaf_rows):
        direction = 1 if index % 2 == 0 else -1
        length = 4 if wide else 3
        start = stem_x
        end = stem_x + direction * length + (sway if index % 2 == 0 else 0)
        draw.line([(start, y), (end, y - 1)], fill=palette["c12"])
        draw.point((end, y - 1), fill=palette["c12"])

    # A couple of lighter tips so the plant reads at 1x.
    draw.point((stem_x, 1), fill=palette["c12"])
    return tile


def build_bubble(palette: dict[str, str], frame: int) -> Image.Image:
    tile = new_tile(8, 8)
    draw = ImageDraw.Draw(tile)
    size = 3 + frame
    left = (8 - size) // 2
    top = (8 - size) // 2
    draw.ellipse([left, top, left + size - 1, top + size - 1], outline=palette["c05"])
    draw.point((left + 1, top + 1), fill=palette["c07"])
    return tile


def build_light_ray(palette: dict[str, str]) -> Image.Image:
    tile = new_tile(16, 96)
    draw = ImageDraw.Draw(tile)
    for y in range(96):
        for x in range(16):
            # Sparse dither so the ray reads as light without alpha blending.
            if (x + y) % 4 == 0 and 2 <= x <= 13:
                draw.point((x, y), fill=palette["c04"])
    return tile


def validate_palette(image: Image.Image, allowed: set[tuple[int, int, int]], name: str) -> None:
    """Fail loudly if any pixel is off-palette or semi-transparent."""
    for pixel in image.getdata():
        red, green, blue, alpha = pixel
        if alpha not in (0, 255):
            raise SystemExit(f"{name}: semi-transparent pixel {pixel}")
        if alpha == 255 and (red, green, blue) not in allowed:
            raise SystemExit(f"{name}: off-palette colour {(red, green, blue)}")


def main() -> None:
    palette = load_palette()
    allowed = {
        tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))
        for value in palette.values()
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    assets: dict[str, Image.Image] = {
        "fish_goldie.png": build_fish_sheet(palette),
        "sand_tile.png": build_sand_tile(palette),
        "rock.png": build_rock(palette),
        "light_ray.png": build_light_ray(palette),
        "plant_a_0.png": build_plant(palette, 32, 0, wide=True),
        "plant_a_1.png": build_plant(palette, 32, 1, wide=True),
        "plant_b_0.png": build_plant(palette, 24, 0, wide=False),
        "plant_b_1.png": build_plant(palette, 24, 1, wide=False),
        "bubble_0.png": build_bubble(palette, 0),
        "bubble_1.png": build_bubble(palette, 1),
        "bubble_2.png": build_bubble(palette, 2),
    }

    for name, image in assets.items():
        validate_palette(image, allowed, name)
        image.save(OUT_DIR / name)
        print(f"wrote {OUT_DIR / name} ({image.width}x{image.height})")


if __name__ == "__main__":
    main()
