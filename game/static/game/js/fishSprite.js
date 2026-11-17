/**
 * Client-side fish state and drawing (Phases 3-4, species/accessories Phase 9).
 *
 * Fish swim on a stepped 8 Hz movement loop and are painted from a 32x32
 * composite of the species sheet plus equipped accessories. When sheets are
 * unavailable the Phase 3 placeholder rectangles are drawn instead.
 */

import { bboxFor, drawComposite } from "./fishRenderer.js";
import {
  CELL,
  FRAMES,
  drawSilhouette,
  getImage,
  getSilhouette,
  speciesFile,
} from "./sprites.js";

// Placeholder [width, height] per stage, kept for the fallback renderer.
const PLACEHOLDER_SIZES = [
  [8, 5],
  [11, 6],
  [14, 8],
  [17, 9],
  [20, 11],
  [24, 13],
];

const PLACEHOLDER_COLORS = [
  "#f2c14e",
  "#e08a3c",
  "#d0616a",
  "#6cae4e",
  "#3a8496",
  "#7b5ea7",
];

// 32x32 cells, kept above the sand strip and clear of the canvas edges.
const WATER = { left: 2, right: 320 - CELL - 2, top: 12, bottom: 150 - CELL - 2 };
const STEP_MS = 125; // movement updates 8 times per second
const FRAME_MS = 130; // ~7.7 swim frames per second
const SPEED = 0.6; // pixels per movement step
const IDLE_MIN_MS = 900;
const IDLE_MAX_MS = 2600;
const LABEL_FONT = "6px 'Press Start 2P', monospace";
const LABEL_LIGHT = "#f6f2e6";
const LABEL_DARK = "#0b1020";
const OUTLINE_COLOR = "#f6f2e6";
const FLASH_COLOR = "#ffffff";
// Hoisted so the 1px outline never allocates inside the render loop.
const OUTLINE_OFFSETS = [
  [-1, 0],
  [1, 0],
  [0, -1],
  [0, 1],
];

/** Small deterministic PRNG (mulberry32) so spawn points don't sync up. */
export function mulberry32(seed) {
  let value = seed >>> 0;
  return function random() {
    value = (value + 0x6d2b79f5) >>> 0;
    let t = value;
    t = Math.imul(t ^ (t >>> 15), 1 | t);
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function clampStage(stage) {
  return Math.max(0, Math.min(5, Number(stage) || 0));
}

export class FishSprite {
  constructor(data, isMine) {
    this.id = data.id;
    this.isMine = Boolean(isMine);
    this.random = mulberry32((Number(data.id) + 1) * 2654435761);
    this.phase = Math.floor(this.random() * 1000);

    this.stage = 0;
    this.name = "";
    this.species = "goldfish";
    this.equipped = {};
    this.stageName = "";
    this.xp = 0;
    this.xpNeeded = 0;
    this.hunger = 0;
    this.level = 1;
    this.bounds = { ...WATER };

    this.x = WATER.left;
    this.y = WATER.top;

    this.setStats(data);

    // Seeded spawn point so fish don't all pile into the same corner.
    this.x = this.bounds.left + this.random() * (this.bounds.right - this.bounds.left);
    this.y = this.bounds.top + this.random() * (this.bounds.bottom - this.bounds.top);
    this.facing = this.random() < 0.5 ? -1 : 1;
    this.target = { x: this.x, y: this.y };
    this.waitUntil = 0;
    this.nextStepAt = 0;
    this.pickTarget(0);
  }

  /** Copy server stats in; deliberately never touches x/y/facing. */
  setStats(data) {
    this.name = String(data.name ?? "");
    this.stage = clampStage(data.stage);
    this.level = data.level ?? 1;
    this.xp = data.xp ?? 0;
    this.xpNeeded = data.xp_needed ?? 0;
    this.hunger = data.hunger ?? 0;
    this.stageName = String(data.stage_name ?? "");
    this.species = String(data.species ?? "goldfish");
    this.equipped = data.equipped || {};
    this.bounds = this.computeBounds();
    this.x = Math.max(this.bounds.left, Math.min(this.x, this.bounds.right));
    this.y = Math.max(this.bounds.top, Math.min(this.y, this.bounds.bottom));
  }

  /** Keep tall fish (seahorse) inside the water using the art bbox. */
  computeBounds() {
    const [, height] = bboxFor(this.species, this.stage);
    const padY = Math.max(0, Math.round((CELL - height) / 2));
    return {
      left: WATER.left,
      right: WATER.right,
      top: WATER.top + padY,
      bottom: WATER.bottom - padY,
    };
  }

  pickTarget(now) {
    const bounds = this.bounds;
    this.target = {
      x: bounds.left + this.random() * (bounds.right - bounds.left),
      y: bounds.top + this.random() * (bounds.bottom - bounds.top),
    };
    this.facing = this.target.x >= this.x ? 1 : -1;
    this.waitUntil = now + IDLE_MIN_MS + this.random() * (IDLE_MAX_MS - IDLE_MIN_MS);
  }

  /** Stepped movement: called every rendered frame, acts 8 times a second. */
  update(now) {
    if (now < this.nextStepAt) {
      return;
    }
    this.nextStepAt = now + STEP_MS;

    const dx = this.target.x - this.x;
    const dy = this.target.y - this.y;
    const distance = Math.hypot(dx, dy);

    if (distance <= SPEED) {
      this.x = this.target.x;
      this.y = this.target.y;
      if (now >= this.waitUntil) {
        this.pickTarget(now);
      }
      return;
    }

    this.facing = dx >= 0 ? 1 : -1;
    this.x += (dx / distance) * SPEED;
    this.y += (dy / distance) * SPEED;
  }

  swimFrame(now) {
    return Math.floor((now + this.phase) / FRAME_MS) % FRAMES;
  }

  draw(ctx, now, options = {}) {
    const { fontReady = false, flash = false, stageOverride = null } = options;
    const row =
      stageOverride === null || stageOverride === undefined
        ? this.stage
        : clampStage(stageOverride);
    const x = Math.round(this.x);
    const y = Math.round(this.y);
    const sheetFile = speciesFile(this.species);
    const sheet = getImage(sheetFile);

    if (sheet) {
      const frame = this.swimFrame(now);
      if (this.isMine) {
        // Cached silhouette, offset in four directions, for a 1px outline.
        const outline = getSilhouette(sheetFile, row, OUTLINE_COLOR);
        for (const [dx, dy] of OUTLINE_OFFSETS) {
          drawSilhouette(ctx, outline, x + dx, y + dy, this.facing);
        }
      }
      drawComposite(ctx, this.species, row, frame, this.equipped, x, y, this.facing);

      if (flash) {
        drawSilhouette(
          ctx,
          getSilhouette(sheetFile, row, FLASH_COLOR),
          x,
          y,
          this.facing
        );
      }
    } else {
      this.drawPlaceholder(ctx, row, x, y);
    }

    if (fontReady) {
      this.drawLabel(ctx, x, y);
    }
  }

  /** Phase 3 rectangle fallback, centred inside the 32x32 cell. */
  drawPlaceholder(ctx, row, cellX, cellY) {
    const [width, height] = PLACEHOLDER_SIZES[row] ?? PLACEHOLDER_SIZES[0];
    const x = cellX + Math.floor((CELL - width) / 2);
    const y = cellY + Math.floor((CELL - height) / 2);
    const tailX = this.facing === 1 ? x - 3 : x + width + 1;
    const eyeX = this.facing === 1 ? x + width - 2 : x + 1;

    if (this.isMine) {
      ctx.fillStyle = LABEL_LIGHT;
      ctx.fillRect(x - 1, y - 1, width + 2, height + 2);
    }

    ctx.fillStyle = PLACEHOLDER_COLORS[row] ?? PLACEHOLDER_COLORS[0];
    ctx.fillRect(x, y, width, height);
    ctx.fillRect(tailX, y + 1, 2, Math.max(1, height - 2));
    ctx.fillStyle = LABEL_DARK;
    ctx.fillRect(this.facing === 1 ? x : x + width - 1, y + 1, 1, height - 2);
    ctx.fillRect(eyeX, y + 1, 1, 1);
  }

  drawLabel(ctx, cellX, cellY) {
    ctx.font = LABEL_FONT;
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";

    const [, height] = bboxFor(this.species, this.stage);
    const top = Math.round(
      Math.max(7, cellY + Math.round((CELL - height) / 2) - 3)
    );

    const text = this.truncate(ctx, this.name, 120);
    const labelWidth = ctx.measureText(text).width;
    const left = Math.round(
      Math.max(1, Math.min(cellX + CELL / 2 - labelWidth / 2, 320 - labelWidth - 1))
    );

    ctx.fillStyle = LABEL_DARK;
    ctx.fillText(text, left - 1, top);
    ctx.fillText(text, left + 1, top);
    ctx.fillText(text, left, top - 1);
    ctx.fillText(text, left, top + 1);
    ctx.fillStyle = LABEL_LIGHT;
    ctx.fillText(text, left, top);
  }

  /** Trim a label to *maxWidth*, ending it with ".." when shortened. */
  truncate(ctx, text, maxWidth) {
    if (ctx.measureText(text).width <= maxWidth) {
      return text;
    }
    let shortened = text;
    while (shortened.length > 0 && ctx.measureText(`${shortened}..`).width > maxWidth) {
      shortened = shortened.slice(0, -1);
    }
    return `${shortened}..`;
  }
}
