"""Generate placeholder pixel art for Phase 9.

Everything is procedural, palette-only, hard-edged and deterministic:

* ``fish_<species>.png`` - 128x192 (4 swim frames x 6 stages, 32x32 cells)
* ``accessories.png`` - 96x80 (16x16 cells, stages 2-5)
* ``accessories_small.png`` - 48x40 (8x8 cells, stages 0-1)
* ``data/anchors.json`` - species -> stage -> accessory anchors + bbox
* ``data/accessories.json`` - atlas columns/rows/pivots/layers/frames

Replace a sheet with hand-drawn art of the same layout and no code changes are
needed; replace the atlases and update the JSON mappings.

Usage:
    python tools/make_placeholder_art.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
PALETTE_PATH = ROOT / "game" / "static" / "game" / "palette.json"
SPRITE_DIR = ROOT / "game" / "static" / "game" / "sprites"
DATA_DIR = ROOT / "game" / "static" / "game" / "data"

CELL = 32
FRAMES = 4
STAGES = 6
STAGE_WIDTHS = [10, 14, 18, 22, 26, 30]

# key, shape, body, accent, fin, belly, pattern, tail, flags
SPECIES = {
    "goldfish": ("oval", 15, 14, 13, 7, "none", "split", []),
    "clownfish": ("oval", 14, 7, 14, 7, "bands", "fan", []),
    "bluetang": ("disc", 16, 0, 15, 30, "marking", "fan", []),
    "pufferfish": ("round", 27, 28, 21, 7, "dots", "fan", ["spikes"]),
    "angelfish": ("tall", 30, 6, 31, 7, "stripes", "fan", ["tallfins"]),
    "betta": ("slim", 19, 17, 17, 7, "none", "long", ["bigfins"]),
    "guppy": ("slim", 22, 16, 18, 7, "spots", "fan", []),
    "koi": ("long", 7, 14, 7, 27, "patches", "split", ["whiskers"]),
    "seahorse": ("vertical", 15, 18, 20, 22, "stripes", "curl", ["snout"]),
    "lionfish": ("oval", 19, 7, 20, 21, "stripes", "fan", ["spikesfan"]),
    "neontetra": ("slim", 30, 16, 19, 7, "neon", "fan", []),
    "boxfish": ("box", 15, 0, 21, 27, "dots", "fan", []),
    "mandarinfish": ("stocky", 16, 14, 22, 22, "swirls", "fan", []),
    "sailfish": ("long", 16, 30, 17, 30, "none", "split", ["sail", "bill"]),
    "anglerfish": ("round", 1, 15, 2, 2, "none", "fan", ["lure"]),
}

ACCESSORY_ORDER = [
    "party_hat", "flower", "sailor_cap", "top_hat", "wizard_hat", "golden_crown",
    "round_glasses", "heart_glasses", "star_shades", "snorkel_mask",
    "fancy_moustache", "rainbow_goggles",
    "red_bow_tie", "striped_scarf", "pearl_necklace", "gold_medal",
    "superhero_cape", "life_ring",
    "tail_ribbon", "jingle_bell", "rainbow_fin_stripe", "mini_flag",
    "seashell_clip",
]
SPARKLE = "sparkle_trail"
TAIL_STATIC = [key for key in ACCESSORY_ORDER if key.startswith("tail_")] + [
    "jingle_bell", "rainbow_fin_stripe", "mini_flag", "seashell_clip"
]
# Tail items are laid out on the fourth row; Sparkle Trail gets four frames on
# the fifth row so it never overlaps another item.
TAIL_ROW_KEYS = ["tail_ribbon", "jingle_bell", "rainbow_fin_stripe", "mini_flag", "seashell_clip"]


def load_palette() -> dict[str, str]:
    data = json.loads(PALETTE_PATH.read_text(encoding="utf-8"))
    colors = data["colors"]
    if not 16 <= len(colors) <= 32:
        raise SystemExit(f"palette must hold 16-32 colours, found {len(colors)}")
    return {f"c{index:02d}": value for index, value in enumerate(colors)}


def rgb(palette, index):
    value = palette[f"c{index:02d}"]
    return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))


def new_tile(width=CELL, height=CELL) -> Image.Image:
    return Image.new("RGBA", (width, height), (0, 0, 0, 0))


def body_geometry(shape, stage, frame):
    """Return (x0, y0, x1, y1, width, height, center_x, center_y)."""
    width = STAGE_WIDTHS[stage]
    if shape == "vertical":
        height = min(30, width + 4)
        width = max(6, int(width * 0.55))
    elif shape == "tall":
        height = min(30, int(width * 1.1))
    elif shape == "disc":
        height = min(30, int(width * 0.95))
    elif shape == "round":
        height = min(30, int(width * 0.9))
    elif shape == "box":
        height = max(6, int(width * 0.8))
    elif shape == "stocky":
        height = max(6, int(width * 0.72))
    elif shape == "slim":
        height = max(5, int(width * 0.45))
    elif shape == "long":
        height = max(5, int(width * 0.4))
    else:
        height = max(5, int(width * 0.62))

    # One pixel of bob per swim frame keeps the animation alive.
    bob = (0, 0, 1, 0)[frame % FRAMES] if shape != "vertical" else 0
    x0 = (CELL - width) // 2
    # Extra right room for the bill/snout, extra left room for long tails.
    x0 = max(1, x0 - 1)
    x1 = min(CELL - 2, x0 + width - 1)
    y0 = (CELL - height) // 2 + bob
    y1 = min(CELL - 2, y0 + height - 1)
    return x0, y0, x1, y1, x1 - x0 + 1, y1 - y0 + 1, (x0 + x1) // 2, (y0 + y1) // 2


def draw_tail(draw, palette, tail, x0, x1, y0, y1, cx, cy, frame, main, fin):
    wiggle = (0, 1, 0, -1)[frame % FRAMES]
    tail_len = max(3, (x1 - x0) // 3)
    if tail == "split":
        draw.polygon(
            [(x0, cy - 1), (x0 - tail_len + wiggle, cy - tail_len // 2), (x0 - 1, cy)],
            fill=rgb(palette, fin),
        )
        draw.polygon(
            [(x0, cy + 1), (x0 - tail_len + wiggle, cy + tail_len // 2), (x0 - 1, cy)],
            fill=rgb(palette, fin),
        )
    elif tail == "long":
        length = max(7, (x1 - x0))
        draw.polygon(
            [(x0, cy - 2), (x0 - length + wiggle, cy - length), (x0 - 2, cy)],
            fill=rgb(palette, fin),
        )
        draw.polygon(
            [(x0, cy + 2), (x0 - length + wiggle, cy + length), (x0 - 2, cy)],
            fill=rgb(palette, fin),
        )
    elif tail == "curl":
        # Seahorse tail curling down below the body.
        for step in range(4):
            draw.point((cx - 1 + step, y1 + 1 - step), fill=rgb(palette, fin))
        draw.point((cx + 3, y1 - 1), fill=rgb(palette, fin))
        return
    else:  # fan
        draw.ellipse(
            [x0 - tail_len + wiggle, cy - max(2, (y1 - y0) // 2), x0 + 1, cy + max(2, (y1 - y0) // 2)],
            fill=rgb(palette, fin),
        )


def draw_fins(draw, palette, shape, flags, x0, y0, x1, y1, cx, cy, frame, stage, accent, fin):
    wiggle = (0, 1, 0, -1)[frame % FRAMES]
    if shape == "tall" or "tallfins" in flags:
        draw.polygon(
            [(cx - 2, y0 + 1), (cx + wiggle, max(0, y0 - 5)), (cx + 3, y0 + 1)],
            fill=rgb(palette, fin),
        )
        draw.polygon(
            [(cx - 2, y1 - 1), (cx + wiggle, min(31, y1 + 5)), (cx + 3, y1 - 1)],
            fill=rgb(palette, fin),
        )
    elif stage >= 1:
        draw.polygon(
            [(cx - 1, y0), (cx + 1 + wiggle, max(0, y0 - 3)), (cx + 4, y0)],
            fill=rgb(palette, accent),
        )

    if "bigfins" in flags or stage >= 3:
        draw.polygon(
            [(cx, y0 + 1), (cx - 4 + wiggle, max(0, y0 - 4)), (cx + 2, y0 + 2)],
            fill=rgb(palette, accent),
        )
        draw.polygon(
            [(cx, y1 - 1), (cx - 4 + wiggle, min(31, y1 + 4)), (cx + 2, y1 - 2)],
            fill=rgb(palette, accent),
        )

    if "spikes" in flags:
        for offset in range(-2, 3):
            draw.point((cx + offset * 3, y0 - 1), fill=rgb(palette, accent))
            draw.point((cx + offset * 3, y1 + 1), fill=rgb(palette, accent))

    if "spikesfan" in flags:
        for offset in range(0, 5):
            draw.line(
                [(x0 + 2 + offset, y1 - 1), (x0 + 4 + offset + wiggle, y1 + 5)],
                fill=rgb(palette, fin),
            )
            draw.line(
                [(x0 + 2 + offset, y0 + 1), (x0 + 4 + offset + wiggle, max(0, y0 - 5))],
                fill=rgb(palette, fin),
            )

    if "sail" in flags:
        draw.polygon(
            [(cx - 3, y0 + 2), (cx + wiggle, max(0, y0 - 8)), (cx + 5, y0 + 1)],
            fill=rgb(palette, fin),
        )

    if "bill" in flags:
        draw.rectangle([x1, cy - 1, min(31, x1 + 5), cy], fill=rgb(palette, accent))

    if "lure" in flags:
        lure_x = min(31, x1 + 2)
        draw.line([(x1 - 2, y0 + 1), (lure_x, y0 - 2)], fill=rgb(palette, accent))
        draw.rectangle([lure_x - 1, max(0, y0 - 3), lure_x + 1, y0 - 1], fill=rgb(palette, 21))

    if stage >= 4 and "shimmer" not in flags:
        px = x0 + 2 + (frame * 3) % max(1, x1 - x0 - 4)
        draw.point((px, y0 + 3), fill=rgb(palette, 8))


def paint_body(draw, palette, shape, x0, y0, x1, y1, main, belly):
    base = rgb(palette, main)
    if shape == "box":
        draw.rectangle([x0, y0, x1, y1], fill=base)
        draw.rectangle([x0 + 1, y0, x1 - 1, y1], fill=base)
    elif shape == "long":
        draw.ellipse([x0, y0, x1, y1], fill=base)
        draw.rectangle([x0 + 2, y0 + 1, x1 - 1, y1 - 1], fill=base)
    else:
        draw.ellipse([x0, y0, x1, y1], fill=base)

    if y1 - y0 >= 6:
        draw.rectangle([x0 + 2, y1 - 1, x1 - 2, y1 - 1], fill=rgb(palette, belly))


def build_mask(shape, x0, y0, x1, y1):
    mask = Image.new("L", (CELL, CELL), 0)
    draw = ImageDraw.Draw(mask)
    if shape == "box":
        draw.rectangle([x0, y0, x1, y1], fill=255)
    else:
        draw.ellipse([x0, y0, x1, y1], fill=255)
    return mask


def apply_pattern(image, mask, palette, pattern, stage, frame, x0, y0, x1, y1, accent, main, fin):
    if pattern == "none" or stage == 0:
        return
    pixels = image.load()
    mask_pixels = mask.load()
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    strength = 1 if stage == 1 else 2

    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            if not mask_pixels[x, y]:
                continue
            rel_x = (x - x0) / width
            rel_y = (y - y0) / height
            paint = None
            if pattern == "bands":
                if abs(rel_x - 0.35) < 0.08 or (strength == 2 and abs(rel_x - 0.7) < 0.06):
                    paint = accent
            elif pattern == "stripes":
                if (y + x // 2) % 4 == 0:
                    paint = accent
            elif pattern == "spots":
                if (x * 7 + y * 13 + stage * 5) % 17 == 0:
                    paint = accent
            elif pattern == "patches":
                if (
                    ((x - x0 - 2) ** 2 + (y - y0 - 2) ** 2) % 41 < 9
                    or ((x - x0 - width // 2) ** 2 + (y - y0 - height + 2) ** 2) % 53 < 7
                ):
                    paint = accent
            elif pattern == "dots":
                if x % 4 == 0 and y % 4 == 1:
                    paint = accent
            elif pattern == "swirls":
                if int((math.sin((rel_x * 4 + rel_y * 3) * math.pi) + 1) * 2) == int(
                    (rel_x + rel_y) * 6
                ) % 4:
                    paint = accent
            elif pattern == "neon":
                if abs(rel_y - 0.4) < 0.12:
                    paint = accent
                elif rel_y > 0.6:
                    paint = 19 if main != 19 else accent
            elif pattern == "marking":
                cx, cy = 0.45, 0.45
                if ((rel_x - cx) ** 2) / 0.04 + ((rel_y - cy) ** 2) / 0.06 < 1:
                    paint = accent
            if paint is not None:
                pixels[x, y] = (*rgb(palette, paint), 255)


def draw_eyes(draw, palette, x1, y0, y1, stage, shape):
    eye_size = 2 if stage >= 2 else 1
    eye_x = max(0, x1 - 2 - (eye_size - 1))
    eye_y = y0 + max(1, (y1 - y0) // 3)
    draw.rectangle([eye_x, eye_y, eye_x + eye_size - 1, eye_y + eye_size - 1], fill=rgb(palette, 0))
    if eye_size == 2:
        draw.point((eye_x, eye_y), fill=rgb(palette, 8))
    draw.point((x1, (y0 + y1) // 2), fill=rgb(palette, 0))


def draw_species_extra(draw, palette, key, flags, x0, y0, x1, y1, cx, cy, stage, frame):
    if "whiskers" in flags:
        draw.line([(x1, cy + 1), (min(31, x1 + 3), cy + 3)], fill=rgb(palette, 29))
    if "snout" in flags:
        draw.rectangle([x1, cy - 1, min(31, x1 + 3), cy], fill=rgb(palette, 14))
    if stage >= 5:
        # Legendary glow sparkles around the body (palette-only).
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            draw.point((max(0, min(31, cx + dx)), max(0, min(31, y0 + dy))), fill=rgb(palette, 21))
        for index in range(3):
            sx = x0 + 2 + (frame * 5 + index * 7) % max(1, x1 - x0 - 3)
            sy = max(0, y0 - 2 - index)
            draw.point((sx, sy), fill=rgb(palette, 8))


def build_fish_tile(palette, key, stage, frame):
    shape, main, accent, fin, belly, pattern, tail, flags = SPECIES[key]
    tile = new_tile()
    draw = ImageDraw.Draw(tile)
    x0, y0, x1, y1, width, height, cx, cy = body_geometry(shape, stage, frame)

    draw_tail(draw, palette, tail, x0, x1, y0, y1, cx, cy, frame, main, fin)
    draw_fins(draw, palette, shape, flags, x0, y0, x1, y1, cx, cy, frame, stage, accent, fin)
    paint_body(draw, palette, shape, x0, y0, x1, y1, main, belly)

    mask = build_mask(shape, x0, y0, x1, y1)
    apply_pattern(tile, mask, palette, pattern, stage, frame, x0, y0, x1, y1, accent, main, fin)
    draw = ImageDraw.Draw(tile)
    draw_eyes(draw, palette, x1, y0, y1, stage, shape)
    draw_species_extra(draw, palette, key, flags, x0, y0, x1, y1, cx, cy, stage, frame)

    anchors = {
        "head": [cx + 1, max(0, y0)],
        "face": [max(0, x1 - 2), y0 + max(1, (y1 - y0) // 3)],
        "body": [cx, min(31, y1 - 2)],
        "tail": [max(1, x0 - 3), cy],
        "bbox": [min(32, max(x1 - x0 + 1, width + 4)), min(32, max(y1 - y0 + 1, height + 4))],
    }
    return tile, anchors


def build_fish_sheet(palette, key):
    sheet = new_tile(CELL * FRAMES, CELL * STAGES)
    anchors = {}
    for stage in range(STAGES):
        anchors[str(stage)] = None
        for frame in range(FRAMES):
            tile, geometry = build_fish_tile(palette, key, stage, frame)
            sheet.paste(tile, (frame * CELL, stage * CELL), tile)
            if frame == 0:
                anchors[str(stage)] = geometry
    return sheet, anchors


# ------------------------------------------------------------------ accessories


def draw_accessory(palette, key, size=16):
    tile = new_tile(size, size)
    draw = ImageDraw.Draw(tile)
    scale = size / 16.0
    def s(value):
        return max(0, min(size - 1, int(round(value * scale))))
    def rect(x0, y0, x1, y1, color):
        draw.rectangle([s(x0), s(y0), s(x1), s(y1)], fill=rgb(palette, color))
    def poly(points, color):
        draw.polygon([(s(x), s(y)) for x, y in points], fill=rgb(palette, color))

    if key == "party_hat":
        poly([(4, 14), (8, 2), (12, 14)], 15)
        rect(4, 12, 12, 14, 13)
        rect(7, 2, 8, 3, 8)
    elif key == "flower":
        rect(6, 5, 9, 8, 13)
        rect(5, 6, 10, 7, 13)
        rect(7, 7, 8, 8, 15)
    elif key == "sailor_cap":
        rect(4, 5, 11, 9, 16)
        rect(2, 10, 13, 12, 7)
        rect(6, 3, 9, 4, 8)
    elif key == "top_hat":
        rect(5, 4, 10, 12, 0)
        rect(3, 12, 12, 14, 0)
        rect(5, 8, 10, 9, 19)
    elif key == "wizard_hat":
        poly([(3, 14), (8, 2), (13, 14)], 17)
        rect(7, 6, 8, 7, 21)
        rect(4, 13, 12, 14, 17)
    elif key == "golden_crown":
        poly([(3, 14), (3, 7), (6, 10), (8, 5), (10, 10), (13, 7), (13, 14)], 15)
        rect(4, 11, 12, 13, 21)
        draw.point((s(8), s(9)), fill=rgb(palette, 19))
    elif key == "round_glasses":
        draw.ellipse([s(3), s(6), s(7), s(10)], outline=rgb(palette, 0), width=max(1, s(1)))
        draw.ellipse([s(9), s(6), s(13), s(10)], outline=rgb(palette, 0), width=max(1, s(1)))
        rect(7, 8, 9, 8, 0)
    elif key == "heart_glasses":
        rect(4, 6, 6, 8, 19)
        rect(3, 5, 7, 6, 19)
        rect(10, 6, 12, 8, 19)
        rect(9, 5, 13, 6, 19)
        rect(7, 7, 9, 7, 0)
    elif key == "star_shades":
        rect(3, 7, 7, 9, 15)
        rect(4, 5, 6, 6, 15)
        rect(9, 7, 13, 9, 15)
        rect(10, 5, 12, 6, 15)
    elif key == "snorkel_mask":
        rect(3, 6, 12, 10, 16)
        rect(4, 7, 11, 8, 30)
        rect(12, 5, 14, 12, 16)
        rect(13, 3, 14, 5, 16)
    elif key == "fancy_moustache":
        rect(4, 8, 12, 9, 29)
        rect(3, 9, 5, 10, 29)
        rect(11, 9, 13, 10, 29)
        rect(2, 10, 3, 11, 29)
    elif key == "rainbow_goggles":
        rect(3, 7, 13, 9, 8)
        rect(3, 7, 13, 7, 19)
        rect(3, 8, 13, 8, 15)
        rect(3, 9, 13, 9, 22)
    elif key == "red_bow_tie":
        poly([(3, 6), (8, 9), (3, 12)], 19)
        poly([(13, 6), (8, 9), (13, 12)], 19)
        rect(7, 8, 9, 9, 13)
    elif key == "striped_scarf":
        rect(3, 8, 13, 11, 19)
        rect(3, 9, 13, 9, 7)
        rect(3, 11, 13, 11, 7)
        rect(10, 11, 12, 14, 19)
    elif key == "pearl_necklace":
        for x in (4, 7, 10, 12):
            rect(x, 9 + abs(8 - x) // 2, x + 1, 10 + abs(8 - x) // 2, 7)
    elif key == "gold_medal":
        rect(4, 5, 5, 8, 19)
        rect(10, 5, 11, 8, 16)
        draw.ellipse([s(5), s(7), s(10), s(12)], fill=rgb(palette, 15))
        rect(7, 8, 8, 10, 21)
    elif key == "superhero_cape":
        poly([(4, 4), (12, 4), (14, 15), (2, 15)], 19)
        rect(6, 4, 10, 5, 13)
    elif key == "life_ring":
        draw.ellipse([s(2), s(6), s(13), s(13)], fill=rgb(palette, 7))
        draw.ellipse([s(5), s(8), s(10), s(11)], fill=rgb(palette, 4))
        rect(2, 9, 3, 10, 19)
        rect(12, 9, 13, 10, 19)
    elif key == "tail_ribbon":
        poly([(4, 6), (8, 9), (4, 12)], 19)
        poly([(12, 6), (8, 9), (12, 12)], 19)
        rect(7, 8, 9, 10, 15)
    elif key == "jingle_bell":
        draw.ellipse([s(5), s(6), s(10), s(12)], fill=rgb(palette, 15))
        rect(5, 11, 10, 12, 21)
        rect(7, 13, 8, 13, 15)
    elif key == "rainbow_fin_stripe":
        for index, color in enumerate((19, 20, 15, 22, 16)):
            rect(4 + index * 2, 5, 5 + index * 2, 12, color)
    elif key == "mini_flag":
        rect(4, 3, 5, 14, 29)
        poly([(5, 3), (12, 6), (5, 9)], 19)
    elif key == "seashell_clip":
        draw.ellipse([s(3), s(6), s(12), s(13)], fill=rgb(palette, 19))
        for x in (5, 7, 9, 11):
            rect(x, 7, x, 12, 21)
    elif key == "sparkle_trail":
        # Frame 0 is drawn here; other frames differ slightly below.
        rect(7, 3, 8, 5, 8)
        rect(5, 5, 6, 6, 21)
        rect(9, 6, 10, 7, 21)
        rect(3, 9, 4, 10, 8)
    return tile


def accessory_atlas(palette, size):
    cols, rows = 6, 5
    atlas = new_tile(cols * size, rows * size)
    layout = {}
    groups = [
        (ACCESSORY_ORDER[0:6], 0),
        (ACCESSORY_ORDER[6:12], 1),
        (ACCESSORY_ORDER[12:18], 2),
        (TAIL_ROW_KEYS, 3),
    ]
    for keys, row in groups:
        for col, key in enumerate(keys):
            tile = draw_accessory(palette, key, size)
            atlas.paste(tile, (col * size, row * size), tile)
            layout[key] = {
                "col": col,
                "row": row,
                "pivot": [size // 2, size - 1 if key.endswith("_hat") or key in ("sailor_cap", "top_hat", "wizard_hat", "golden_crown", "flower") else size // 2],
                "layer": "behind" if key == "superhero_cape" else "front",
                "frames": 1,
            }
    # Sparkle Trail: four animated frames on the fifth row.
    for frame in range(4):
        tile = draw_accessory(palette, "sparkle_trail", size)
        draw = ImageDraw.Draw(tile)
        if frame:
            draw.rectangle([0, 0, size - 1, size - 1], fill=(0, 0, 0, 0))
            points = [
                (size // 4, size // 5),
                (size * 3 // 4, size // 3),
                (size // 3, size * 3 // 5),
                (size * 3 // 4, size * 3 // 4),
            ]
            px, py = points[frame]
            x0 = max(0, px - 1)
            y0 = max(0, py - 1)
            x1 = max(x0, min(size - 1, px))
            y1 = max(y0, min(size - 1, py))
            draw.rectangle([x0, y0, x1, y1], fill=rgb(palette, 8))
            draw.point((min(size - 1, px + 2), min(size - 1, py + 2)), fill=rgb(palette, 21))
        atlas.paste(tile, (frame * size, 4 * size), tile)
    layout[SPARKLE] = {
        "col": 0,
        "row": 4,
        "pivot": [size // 2, size // 2],
        "layer": "front",
        "frames": 4,
    }
    return atlas, layout


def validate_palette(image, allowed, name):
    for pixel in image.getdata():
        red, green, blue, alpha = pixel
        if alpha not in (0, 255):
            raise SystemExit(f"{name}: semi-transparent pixel {pixel}")
        if alpha == 255 and (red, green, blue) not in allowed:
            raise SystemExit(f"{name}: off-palette colour {(red, green, blue)}")


def main():
    palette = load_palette()
    allowed = {rgb(palette, index) for index in range(len(palette))}
    SPRITE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    anchors_all = {}
    for key in SPECIES:
        sheet, anchors = build_fish_sheet(palette, key)
        validate_palette(sheet, allowed, f"fish_{key}")
        sheet.save(SPRITE_DIR / f"fish_{key}.png")
        anchors_all[key] = anchors
        print(f"wrote fish_{key}.png ({sheet.width}x{sheet.height})")

    normal, normal_layout = accessory_atlas(palette, 16)
    small, small_layout = accessory_atlas(palette, 8)
    validate_palette(normal, allowed, "accessories")
    validate_palette(small, allowed, "accessories_small")
    normal.save(SPRITE_DIR / "accessories.png")
    small.save(SPRITE_DIR / "accessories_small.png")

    art = {}
    for key, entry in normal_layout.items():
        small_entry = small_layout[key]
        art[key] = {
            "slot": next(
                slot
                for slot, names in {
                    "head": ACCESSORY_ORDER[0:6],
                    "face": ACCESSORY_ORDER[6:12],
                    "body": ACCESSORY_ORDER[12:18],
                    "tail": TAIL_ROW_KEYS + [SPARKLE],
                }.items()
                if key in names
            ),
            "layer": entry["layer"],
            "frames": entry["frames"],
            "col": entry["col"],
            "row": entry["row"],
            "pivot": entry["pivot"],
            "small": {
                "col": small_entry["col"],
                "row": small_entry["row"],
                "pivot": small_entry["pivot"],
            },
        }

    (DATA_DIR / "anchors.json").write_text(json.dumps(anchors_all, indent=2) + "\n", encoding="utf-8")
    (DATA_DIR / "accessories.json").write_text(json.dumps(art, indent=2) + "\n", encoding="utf-8")
    print(f"wrote anchors.json ({len(anchors_all)} species)")
    print(f"wrote accessories.json ({len(art)} items)")


if __name__ == "__main__":
    main()
