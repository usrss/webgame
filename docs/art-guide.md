# Art guide

Everything in the tank is pixel art drawn with hard edges. No anti-aliasing, no
semi-transparent pixels, no smooth scaling.

## Canvas and cells

- Tank canvas: **320 x 180** internal pixels, displayed at 3x (960x540), 2x
  (640x360) or 1x (320x180) - always a whole-number multiple.
- Displayed with `image-rendering: pixelated` and
  `ctx.imageSmoothingEnabled = false`.
- Fish cell size: **32 x 32** for every species and stage.

## Fish sprite sheet

Each species ships one PNG at `game/static/game/sprites/fish_<species>.png`:

- Size **128 x 128** - a 4 x 4 grid of 32x32 cells.
- **Columns = animation frames** (4-frame swim cycle).
- **Rows = evolution stages**: row 0 Fry, row 1 Juvenile, row 2 Adult,
  row 3 Elder.
- Fish face **right**; the game flips them horizontally for left movement.
- Draw early stages smaller inside the cell, anchored at the cell center:
  Fry ~10 px wide, Juvenile ~16, Adult ~22, Elder ~28.
- Transparent background, fully opaque pixels only.

The game maps `EvolutionStage.sprite_key` to `(sheet file, row)` in
`game/static/game/js/sprites.js` (`SPRITE_MAP`). Current keys:
`goldie_fry`, `goldie_juvenile`, `goldie_adult`, `goldie_elder`.

To add a species: draw the sheet, add its four keys to `SPRITE_MAP`, and seed
matching `EvolutionStage` rows (one per stage) with that species' keys.

## Palette

One shared palette of 16 colours lives in `game/static/game/palette.json` and is
mirrored as CSS variables in `game/static/game/css/pixel.css`. Sprites,
background pieces and UI may only use those colours. The placeholder generator
fails if it produces an off-palette or semi-transparent pixel.

| # | Colour |
|---|---|
| 00 | `#0b1020` ink |
| 01 | `#14213d` deep |
| 02 | `#1d3b5c` water 0 |
| 03 | `#2a5d7e` water 1 |
| 04 | `#3a8496` water 2 |
| 05 | `#6cb8b0` bubble |
| 06 | `#9fb3c8` muted |
| 07 | `#f6f2e6` cream |
| 08 | `#ffffff` white |
| 09 | `#c2a25a` sand |
| 10 | `#8a6f34` sand dark |
| 11 | `#3f7d3a` plant |
| 12 | `#6cae4e` plant light |
| 13 | `#d0616a` coral |
| 14 | `#e08a3c` orange |
| 15 | `#f2c14e` gold |

## Background pieces

All live in `game/static/game/sprites/` and are optional per layer - the game
falls back to flat rectangles if an image fails to load.

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
python tools/make_placeholder_sheet.py
```

The script is deterministic and validates that every pixel is palette-only.
Replacing `fish_goldie.png` with hand-drawn art of the same layout requires
**no code changes**.

## Exporting hand-drawn art

### Aseprite

1. New file 128x128, sprite mode RGB with alpha.
2. Draw each stage in its row of 32x32 cells, 4 frames across.
3. Palette: load `palette.json` as a palette (Aseprite accepts hex lists) and
   enable indexed mode to keep colours locked.
4. Disable anti-aliasing; use the Pencil tool with 1px sizes.
5. Export: **File > Export As > PNG**, scale 100%, no `Scale`/`Trim`.

### Piskel

1. Create a 128x128 sprite with a 32x32 grid.
2. Draw the 16 cells; Piskel frames must not exceed 4 columns - use one layer
   per stage or a single 128x128 frame.
3. Import the palette via **Palette > Import** using the hex list.
4. Export as PNG at 1x and rename it to `fish_<species>.png`.

## Rules of thumb

- Keep the silhouette readable at 1x (the game is playable at 320x180).
- Leave the cell edges transparent so neighbouring fish never touch.
- The game draws its own 1px outline around your fish and name labels, so
  don't bake outlines into the sheet.
- Never use gradients or more than the palette's colours; it will look out of
  place next to the UI.
