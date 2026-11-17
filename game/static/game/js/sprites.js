/**
 * Sprite sheet loading and drawing (Phases 4 and 9).
 *
 * One 128x192 sheet per species: 32x32 cells, 4 columns of swim frames and 6
 * rows of evolution stages. Fish are drawn facing right in the art; this module
 * flips them with an integer translate/scale for left-facing movement.
 *
 * Also caches white silhouettes per stage, used for the flash and the "my fish"
 * highlight without re-compositing every frame.
 */

export const CELL = 32;
export const FRAMES = 4;
export const STAGES = 6;

/** Every species sheet the game knows how to load. */
export const SPECIES_KEYS = [
  "goldfish",
  "clownfish",
  "bluetang",
  "pufferfish",
  "angelfish",
  "betta",
  "guppy",
  "koi",
  "seahorse",
  "lionfish",
  "neontetra",
  "boxfish",
  "mandarinfish",
  "sailfish",
  "anglerfish",
];

export function speciesFile(key) {
  return SPECIES_KEYS.includes(key) ? `fish_${key}.png` : "fish_goldfish.png";
}

const BACKGROUND_FILES = [
  "sand_tile.png",
  "rock.png",
  "light_ray.png",
  "plant_a_0.png",
  "plant_a_1.png",
  "plant_b_0.png",
  "plant_b_1.png",
  "bubble_0.png",
  "bubble_1.png",
  "bubble_2.png",
  "accessories.png",
  "accessories_small.png",
];

const images = new Map(); // file name -> HTMLImageElement | null
const silhouettes = new Map(); // sheet|row|color -> canvas

export function allFiles() {
  return [...SPECIES_KEYS.map(speciesFile), ...BACKGROUND_FILES];
}

function loadImage(url) {
  return new Promise((resolve) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = url;
  });
}

/**
 * Preload every sprite. Never rejects: a missing file is cached as `null` so
 * callers can fall back to placeholder rectangles and show a visible error.
 */
export async function preload(baseUrl) {
  const results = await Promise.all(
    allFiles().map(async (file) => [file, await loadImage(baseUrl + file)])
  );
  for (const [file, image] of results) {
    images.set(file, image);
  }
  return {
    files: allFiles(),
    failed: results.filter(([, image]) => !image).map(([file]) => file),
  };
}

export function getImage(file) {
  return images.get(file) ?? null;
}

export function withFacing(ctx, x, y, facing, paint) {
  if (facing < 0) {
    ctx.save();
    ctx.translate(x + CELL, y);
    ctx.scale(-1, 1);
    paint(0, 0);
    ctx.restore();
  } else {
    paint(x, y);
  }
}

/** Draw one 32x32 frame. Returns false when the sheet is unavailable. */
export function drawFish(ctx, sheetFile, row, frame, x, y, facing) {
  const sheet = getImage(sheetFile);
  if (!sheet) {
    return false;
  }
  const sourceX = (frame % FRAMES) * CELL;
  const sourceY = row * CELL;
  withFacing(ctx, x, y, facing, (dx, dy) => {
    ctx.drawImage(sheet, sourceX, sourceY, CELL, CELL, dx, dy, CELL, CELL);
  });
  return true;
}

/** Cached white/coloured silhouette for a stage, used for flash and highlight. */
export function getSilhouette(sheetFile, row, color) {
  const key = `${sheetFile}|${row}|${color}`;
  const cached = silhouettes.get(key);
  if (cached) {
    return cached;
  }
  const sheet = getImage(sheetFile);
  if (!sheet) {
    return null;
  }
  const canvas = document.createElement("canvas");
  canvas.width = CELL;
  canvas.height = CELL;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(sheet, 0, row * CELL, CELL, CELL, 0, 0, CELL, CELL);
  ctx.globalCompositeOperation = "source-in";
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, CELL, CELL);
  silhouettes.set(key, canvas);
  return canvas;
}

export function drawSilhouette(ctx, canvas, x, y, facing) {
  if (!canvas) {
    return;
  }
  withFacing(ctx, x, y, facing, (dx, dy) => {
    ctx.drawImage(canvas, dx, dy);
  });
}
