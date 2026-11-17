# Art guide

Everything in the tank is pixel art drawn with hard edges. No anti-aliasing, no
semi-transparent pixels, no smooth scaling.

## Canvas and cells

- Tank canvas: **320 x 180** internal pixels, displayed at 3x (960x540), 2x
  (640x360) or 1x (320x180) - always a whole-number multiple.
- Displayed with `image-rendering: pixelated` and
  `ctx.imageSmoothingEnabled = false`.
- Fish cell size: **32 x 32** for every species and stage.

## Fish sprite sheets (15 species, 6 stages)

Each species ships one PNG at `game/static/game/sprites/fish_<species>.png`:

- Size **128 x 192** - a 4 x 6 grid of 32x32 cells.
- **Columns = animation frames** (4-frame swim cycle).
- **Rows = evolution stages**: row 0 Hatchling (Lv 1), row 1 (Lv 10),
  row 2 (Lv 25), row 3 (Lv 40), row 4 (Lv 55), row 5 Legendary (Lv 70).
- Fish face **right**; the game flips them horizontally for left movement.
- Sizes per stage (body width): **10, 14, 18, 22, 26, 30 px**. Keep the whole
  silhouette inside the cell, including fins and tails.
- Transparent background, fully opaque pixels only.
- Stage look: bigger body, second fin colour, complete pattern by stage 2,
  crest/frill by stage 3, shimmer pixels by stage 4, glow outline and sparkles
  by stage 5.

The game chooses the sheet from `Fish.species` and the row from
`Fish.stage`; there is no per-stage sprite key any more. Adding a species is
purely: sheet + a row in `game/data/species.json` (and anchors, below).

Replace a sheet with hand-drawn art in the same layout and **no code changes**
are needed.

## Palette

One shared palette of **32 colours** lives in `game/static/game/palette.json` and
is mirrored as CSS variables in `game/static/game/css/pixel.css`. Sprites,
background pieces and UI may only use those colours. The placeholder generator
fails if it produces an off-palette or semi-transparent pixel.

| # | Colour | # | Colour |
|---|---|---|---|
| 00 | `#0b1020` ink | 16 | `#4a5fc1` cobalt |
| 01 | `#14213d` deep | 17 | `#7b5ea7` violet |
| 02 | `#1d3b5c` water 0 | 18 | `#b05fa0` plum |
| 03 | `#2a5d7e` water 1 | 19 | `#e0607a` rose |
| 04 | `#3a8496` water 2 | 20 | `#f08a5d` peach |
| 05 | `#6cb8b0` bubble | 21 | `#ffd166` lemon |
| 06 | `#9fb3c8` muted | 22 | `#7fd1b9` mint |
| 07 | `#f6f2e6` cream | 23 | `#2f9e8f` teal |
| 08 | `#ffffff` white | 24 | `#1d6b7a` deep teal |
| 09 | `#c2a25a` sand | 25 | `#a8e06a` lime |
| 10 | `#8a6f34` sand dark | 26 | `#55883b` moss |
| 11 | `#3f7d3a` plant | 27 | `#d9c7a7` tan |
| 12 | `#6cae4e` plant light | 28 | `#a67c52` brown |
| 13 | `#d0616a` coral | 29 | `#6e5a4b` bark |
| 14 | `#e08a3c` orange | 30 | `#cfd8e3` ice |
| 15 | `#f2c14e` gold | 31 | `#8796a8` stone |

## Anchors (`game/static/game/data/anchors.json`)

For every species and stage:

```json
"goldfish": {
  "0": {
    "head": [17, 11], "face": [22, 14], "body": [16, 18], "tail": [6, 18],
    "bbox": [18, 12]
  }
}
```

- `head`, `face`, `body`, `tail` are **cell coordinates** (0-31) on the
  right-facing sprite where the matching accessory is placed.
- `bbox` is the drawn fish's `[width, height]` in pixels. The game uses it for
  name-label placement and to keep tall fish (the seahorse) out of the sand.

The placeholder generator writes this file from its own body geometry. For a
hand-drawn replacement, measure the pixel position on the 32x32 cell in Aseprite
(hover the pixel, read the coordinates) and edit the JSON. `head` sits at the
top/front of the head, `face` at the eye, `body` at the centre of the belly,
`tail` just behind the tail.

## Accessory atlases

All accessories face right and are drawn as overlays:

| File | Cell | Layout | Used for |
|---|---|---|---|
| `accessories.png` | 16x16 | 6 columns x 5 rows | stages 2-5 |
| `accessories_small.png` | 8x8 | 6 columns x 5 rows | stages 0-1 |

The small atlas is a separate drawing, never a fractional scale of the big one;
an 8x8 hat on a 10 px fry reads correctly, a scaled 16x16 one does not.

`game/static/game/data/accessories.json` maps each key to its atlas position and
pivot:

```json
"party_hat": {
  "slot": "head", "layer": "front", "frames": 1,
  "col": 0, "row": 0, "pivot": [8, 15],
  "small": {"col": 0, "row": 0, "pivot": [4, 7]}
}
```

- `pivot` is the pixel inside the accessory cell that lands on the anchor.
- `layer` is `front` or `behind` (only the Superhero Cape is `behind`).
- `frames` is 1 or 4 (only Sparkle Trail animates); animated items read
  consecutive columns starting at `col`.
- Draw order: behind-layer -> fish -> tail -> body -> face -> head.

## Background pieces

| File | Size | Purpose |
|---|---|---|
| `sand_tile.png` | 16x16 | tiled across the sand strip |
| `rock.png` | 16x12 | floor decoration |
| `plant_a_0/1.png` | 16x32 | front plants, two sway frames |
| `plant_b_0/1.png` | 12x24 | back plants, two sway frames |
| `bubble_0/1/2.png` | 8x8 | bubble animation frames |
| `light_ray.png` | 16x96 | dithered surface light |

## Placeholder art

Generate the current placeholder set (requires Pillow, see
`requirements-dev.txt`):

```powershell
.\.venv\Scripts\Activate.ps1
python tools/make_placeholder_art.py
```

This writes all 15 fish sheets, both accessory atlases and both JSON mapping
files, and validates that every pixel is palette-only and fully opaque. Re-run
it any time; it is deterministic.

The legacy `tools/make_placeholder_sheet.py` still generates the background
pieces and the old `fish_goldie.png`; the game no longer loads that sheet.

## Exporting hand-drawn art

### Aseprite

1. New file 128x192, sprite mode RGB with alpha.
2. Draw each stage in its row of 32x32 cells, 4 frames across.
3. Palette: load `palette.json` as a palette (Aseprite accepts hex lists) and
   enable indexed mode to keep colours locked.
4. Disable anti-aliasing; use the Pencil tool with 1px sizes.
5. Export: **File > Export As > PNG**, scale 100%, no `Scale`/`Trim`.

### Piskel

1. Create a 128x192 sprite with a 32x32 grid.
2. Draw the 24 cells; export as PNG at 1x and rename it to
   `fish_<species>.png`.

## Production checklist

| Asset | Count |
|---|---|
| Fish frames (15 species x 6 stages x 4 frames) | **360** |
| Head accessories x 2 atlases | 12 |
| Face accessories x 2 atlases | 12 |
| Body accessories x 2 atlases | 12 |
| Tail accessories x 2 atlases (Sparkle Trail has 4 frames) | 13 + 12 |

Suggested order for hand-drawn art:

1. **Goldfish** (oval body, split tail) - the baseline silhouette.
2. **Clownfish** (bands) - proves the pattern pipeline.
3. **Seahorse** (vertical, curled tail) - proves custom anchors and bbox.
4. **Anglerfish** (round, lure, friendly face) - proves special flags.
5. Then the remaining eleven in `order` from `species.json`.

Draw one full species (24 frames) before starting the next, and inspect it on
`/debug/art/` (staff only). That page renders every species x stage x accessory
combination with both facings using the real renderer.

## Rules of thumb

- Keep the silhouette readable at 1x (the game is playable at 320x180).
- Leave the cell edges transparent so neighbouring fish never touch.
- The game draws its own 1px outline around your fish and name labels, so
  don't bake outlines into the sheet.
- Never use gradients or more than the palette's colours; it will look out of
  place next to the UI.
