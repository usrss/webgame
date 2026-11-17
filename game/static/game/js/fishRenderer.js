/**
 * Fish + accessory compositing (Phase 9).
 *
 * A composite is built once per (species, stage, frame, equipment) in a 32x32
 * offscreen canvas, then cached in a small LRU. Flipping for left movement
 * happens when the finished composite is blitted, so accessory anchors never
 * need mirroring.
 *
 * Draw order: behind-layer accessories -> fish -> tail -> body -> face -> head.
 */

import { CELL, FRAMES, STAGES, getImage, speciesFile, withFacing } from "./sprites.js";

const SLOT_ORDER = ["tail", "body", "face", "head"];
const STAGES_SMALL_ATLAS = 2;
const CACHE_LIMIT = 300;
const cache = new Map();

let anchors = {};
let art = {};

function safeStage(stage) {
  return Math.max(0, Math.min(STAGES - 1, Number(stage) || 0));
}

export async function loadArtData(baseUrl) {
  const base = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  async function read(name) {
    try {
      const response = await fetch(`${base}${name}`, { credentials: "same-origin" });
      if (!response.ok) {
        return {};
      }
      return await response.json();
    } catch (error) {
      return {};
    }
  }
  [anchors, art] = await Promise.all([read("anchors.json"), read("accessories.json")]);
  cache.clear();
  return { anchors, art };
}

export function bboxFor(species, stage) {
  const entry = anchors?.[species]?.[safeStage(stage)];
  const bbox = entry && entry.bbox;
  return Array.isArray(bbox) ? bbox : [32, 32];
}

function drawAccessory(ctx, key, species, stage, frame, slot) {
  const entry = art?.[key];
  if (!entry) {
    return;
  }
  const small = stage < STAGES_SMALL_ATLAS;
  const cell = small ? 8 : 16;
  const atlas = getImage(small ? "accessories_small.png" : "accessories.png");
  if (!atlas) {
    return;
  }
  const placement = small && entry.small ? entry.small : entry;
  const pivot = placement.pivot || [cell / 2, cell / 2];
  const anchor =
    anchors?.[species]?.[stage]?.[slot] || [CELL / 2, CELL / 2];
  const frameIndex = (entry.frames || 1) > 1 ? frame % (entry.frames || 1) : 0;
  const sx = (placement.col + frameIndex) * cell;
  const sy = placement.row * cell;
  const dx = Math.round(anchor[0] - pivot[0]);
  const dy = Math.round(anchor[1] - pivot[1]);
  ctx.drawImage(atlas, sx, sy, cell, cell, dx, dy, cell, cell);
}

function equipmentKey(equipped) {
  return SLOT_ORDER.map((slot) => {
    const key = equipped ? equipped[slot] : null;
    return key || "-";
  }).join("|");
}

function buildComposite(species, stage, frame, equipped) {
  const sheet = getImage(speciesFile(species));
  if (!sheet) {
    return null;
  }
  const canvas = document.createElement("canvas");
  canvas.width = CELL;
  canvas.height = CELL;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;

  // Behind-layer items (currently the cape) go under the fish.
  for (const slot of SLOT_ORDER) {
    const key = equipped?.[slot];
    if (key && art?.[key]?.layer === "behind") {
      drawAccessory(ctx, key, species, stage, frame, slot);
    }
  }

  ctx.drawImage(sheet, (frame % FRAMES) * CELL, stage * CELL, CELL, CELL, 0, 0, CELL, CELL);

  for (const slot of SLOT_ORDER) {
    const key = equipped?.[slot];
    if (key && art?.[key]?.layer !== "behind") {
      drawAccessory(ctx, key, species, stage, frame, slot);
    }
  }
  return canvas;
}

export function compositeFor(species, stage, frame, equipped) {
  const safe = safeStage(stage);
  const key = `${species}|${safe}|${frame % FRAMES}|${equipmentKey(equipped)}`;
  const cached = cache.get(key);
  if (cached) {
    // Refresh LRU position.
    cache.delete(key);
    cache.set(key, cached);
    return cached;
  }
  const canvas = buildComposite(species, safe, frame % FRAMES, equipped);
  if (!canvas) {
    return null;
  }
  cache.set(key, canvas);
  while (cache.size > CACHE_LIMIT) {
    cache.delete(cache.keys().next().value);
  }
  return canvas;
}

export function drawComposite(ctx, species, stage, frame, equipped, x, y, facing) {
  const canvas = compositeFor(species, stage, frame, equipped);
  if (!canvas) {
    return false;
  }
  withFacing(ctx, x, y, facing, (dx, dy) => {
    ctx.drawImage(canvas, dx, dy);
  });
  return true;
}

/** Draw a right-facing preview scaled by an integer factor (wardrobe). */
export function drawPreview(ctx, species, stage, frame, equipped, scale = 2) {
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, CELL * scale, CELL * scale);
  const canvas = compositeFor(species, stage, frame, equipped);
  if (!canvas) {
    return;
  }
  ctx.save();
  ctx.scale(scale, scale);
  ctx.drawImage(canvas, 0, 0);
  ctx.restore();
}
