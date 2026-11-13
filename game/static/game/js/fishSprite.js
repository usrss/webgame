/**
 * Client-side fish state and drawing (Phases 3-4).
 *
 * Fish swim on a stepped 8 Hz movement loop and are painted from the species
 * sprite sheet. When sheets are unavailable (failed load, or an unknown
 * sprite_key) the Phase 3 placeholder rectangles are drawn instead.
 */

import {
  CELL,
  FRAMES,
  drawFish,
  drawSilhouette,
  getImage,
  getSilhouette,
  spriteConfigFor,
} from "./sprites.js";

// Placeholder [width, height] per stage, kept for the fallback renderer.
const PLACEHOLDER_SIZES = [
  [8, 5],
  [12, 7],
  [16, 9],
  [20, 11],
];

const PLACEHOLDER_COLORS = ["#f2c14e", "#d0616a", "#6cae4e", "#3a8496"];

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
    t ^= t + Math.imul(t ^ (t >>> 7), 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function clampStage(stage) {
  return Math.max(0, Math.min(3, Number(stage) || 0));
}

export class FishSprite {
  constructor(data, isMine) {
    this.id = data.id;
    this.isMine = Boolean(isMine);
    this.random = mulberry32((Number(data.id) + 1) * 2654435761);
    this.phase = Math.floor(this.random() * 1000);

    this.stage = 0;
    this.name = "";
    this.spriteKey = "";
    this.stageName = "";
    this.spriteConfig = spriteConfigFor(this.spriteKey);
    this.xp = 0;
    this.xpNeeded = 0;
    this.hunger = 0;
    this.level = 1;

    this.x = WATER.left;
    this.y = WATER.top;

    this.setStats(data);

    // Seeded spawn point so fish don't all pile into the same corner.
    this.x = WATER.left + this.random() * (WATER.right - WATER.left);
    this.y = WATER.top + this.random() * (WATER.bottom - WATER.top);
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
    this.spriteKey = String(data.sprite_key ?? "");
    this.spriteConfig = spriteConfigFor(this.spriteKey);
    this.x = Math.max(WATER.left, Math.min(this.x, WATER.right));
    this.y = Math.max(WATER.top, Math.min(this.y, WATER.bottom));
  }

  pickTarget(now) {
    this.target = {
      x: WATER.left + this.random() * (WATER.right - WATER.left),
      y: WATER.top + this.random() * (WATER.bottom - WATER.top),
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
    const row = stageOverride === null || stageOverride === undefined ? this.stage : stageOverride;
    const x = Math.round(this.x);
    const y = Math.round(this.y);
    const config = this.spriteConfig;
    const sheet = getImage(config.file);

    if (sheet) {
      if (this.isMine) {
        // Cached silhouette, offset in four directions, for a 1px outline.
        const outline = getSilhouette(config.file, row, OUTLINE_COLOR);
        for (const [dx, dy] of OUTLINE_OFFSETS) {
          drawSilhouette(ctx, outline, x + dx, y + dy, this.facing);
        }
      }
      drawFish(ctx, config.file, row, this.swimFrame(now), x, y, this.facing);

      if (flash) {
        drawSilhouette(
          ctx,
          getSilhouette(config.file, row, FLASH_COLOR),
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

    const text = this.truncate(ctx, this.name, 120);
    const labelWidth = ctx.measureText(text).width;
    const left = Math.round(
      Math.max(1, Math.min(cellX + CELL / 2 - labelWidth / 2, 320 - labelWidth - 1))
    );
    const top = Math.round(Math.max(7, cellY - 3));

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
