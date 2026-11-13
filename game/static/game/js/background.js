/**
 * Tank ambience (Phase 4): water bands, light rays, plants, sand and bubbles.
 *
 * The static layers (water, rays, back plants) are pre-rendered once to an
 * offscreen canvas; per frame we only redraw that bitmap, the swaying front
 * plants and the bubbles. Nothing here allocates per frame.
 */

import { getImage } from "./sprites.js";

const WIDTH = 320;
const HEIGHT = 180;
const WATER_BOTTOM = 150; // sand starts here
const PLANT_SWAY_MS = 600;
const BUBBLE_MAX = 12;
const BUBBLE_STEP_MS = 90;

const COLORS = {
  water0: "#1d3b5c",
  water1: "#2a5d7e",
  water2: "#3a8496",
  sandDark: "#8a6f34",
};

export class Background {
  constructor() {
    this.staticLayer = null;
    this.bubbles = [];
    this.nextBubbleAt = 0;
    this.lastBubbleStep = 0;
    this.swayFrame = 0;
    this.lastSwayAt = 0;
  }

  /** Pre-render the static layers. Call once the images are loaded. */
  prepare() {
    const layer = document.createElement("canvas");
    layer.width = WIDTH;
    layer.height = HEIGHT;
    const ctx = layer.getContext("2d");
    ctx.imageSmoothingEnabled = false;

    // Water bands.
    ctx.fillStyle = COLORS.water0;
    ctx.fillRect(0, 0, WIDTH, 60);
    ctx.fillStyle = COLORS.water1;
    ctx.fillRect(0, 60, WIDTH, 52);
    ctx.fillStyle = COLORS.water2;
    ctx.fillRect(0, 112, WIDTH, WATER_BOTTOM - 112);

    // Faint light rays.
    const ray = getImage("light_ray.png");
    if (ray) {
      for (const [x, y] of [[34, 0], [148, 0], [252, 0]]) {
        ctx.drawImage(ray, x, y);
      }
    }

    // Small rock, behind everything else on the floor.
    const rock = getImage("rock.png");
    if (rock) {
      ctx.drawImage(rock, 232, WATER_BOTTOM - rock.height);
    }

    // Back plants.
    const backPlant = getImage("plant_b_0.png");
    if (backPlant) {
      for (const x of [54, 118, 196, 296]) {
        ctx.drawImage(backPlant, x, WATER_BOTTOM - backPlant.height);
      }
    }

    this.staticLayer = layer;
  }

  /** Everything behind the fish. */
  drawBack(ctx) {
    if (this.staticLayer) {
      ctx.drawImage(this.staticLayer, 0, 0);
      return;
    }
    // Image loading failed: keep a readable flat background.
    ctx.fillStyle = COLORS.water0;
    ctx.fillRect(0, 0, WIDTH, 60);
    ctx.fillStyle = COLORS.water1;
    ctx.fillRect(0, 60, WIDTH, 52);
    ctx.fillStyle = COLORS.water2;
    ctx.fillRect(0, 112, WIDTH, WATER_BOTTOM - 112);
  }

  /** Front plants, sand strip and bubbles - drawn above the fish. */
  drawFront(ctx, now) {
    if (now - this.lastSwayAt >= PLANT_SWAY_MS) {
      this.lastSwayAt = now;
      this.swayFrame = this.swayFrame === 0 ? 1 : 0;
    }

    const plantA = getImage(`plant_a_${this.swayFrame}.png`);
    const plantB = getImage(`plant_b_${this.swayFrame}.png`);
    if (plantA) {
      for (const x of [8, 208, 276]) {
        ctx.drawImage(plantA, x, WATER_BOTTOM - plantA.height);
      }
    }
    if (plantB) {
      for (const x of [96, 168]) {
        ctx.drawImage(plantB, x, WATER_BOTTOM - plantB.height);
      }
    }

    this.drawSand(ctx);
    this.updateBubbles(now);
    this.drawBubbles(ctx, now);
  }

  drawSand(ctx) {
    const tile = getImage("sand_tile.png");
    if (tile) {
      for (let y = WATER_BOTTOM; y < HEIGHT; y += tile.height) {
        for (let x = 0; x < WIDTH; x += tile.width) {
          ctx.drawImage(tile, x, y);
        }
      }
    } else {
      ctx.fillStyle = "#c2a25a";
      ctx.fillRect(0, WATER_BOTTOM, WIDTH, HEIGHT - WATER_BOTTOM);
    }
    ctx.fillStyle = COLORS.sandDark;
    ctx.fillRect(0, WATER_BOTTOM, WIDTH, 2);
  }

  spawnBubble() {
    const size = 8;
    this.bubbles.push({
      x: 8 + Math.random() * (WIDTH - 16 - size),
      y: WATER_BOTTOM - size,
      speed: 0.7 + Math.random() * 0.9,
      wobble: Math.random() * Math.PI * 2,
      frame: Math.floor(Math.random() * 3),
    });
  }

  updateBubbles(now) {
    if (now < this.nextBubbleAt) {
      return;
    }
    this.nextBubbleAt = now + 500 + Math.random() * 900;
    if (this.bubbles.length < BUBBLE_MAX) {
      this.spawnBubble();
    }
  }

  drawBubbles(ctx, now) {
    if (this.lastBubbleStep === 0) {
      this.lastBubbleStep = now;
    }
    const steps = Math.floor((now - this.lastBubbleStep) / BUBBLE_STEP_MS);
    if (steps > 0) {
      this.lastBubbleStep += steps * BUBBLE_STEP_MS;
      for (const bubble of this.bubbles) {
        bubble.y -= bubble.speed * steps;
        bubble.wobble += 0.4 * steps;
        bubble.frame = (bubble.frame + (steps % 3)) % 3;
      }
      this.bubbles = this.bubbles.filter((bubble) => bubble.y >= 16);
    }

    for (const bubble of this.bubbles) {
      const image = getImage(`bubble_${bubble.frame}.png`);
      if (!image) {
        continue;
      }
      const x = Math.round(bubble.x + Math.sin(bubble.wobble) * 3);
      const y = Math.round(bubble.y);
      if (y >= 16 && y < WATER_BOTTOM) {
        ctx.drawImage(image, x, y);
      }
    }
  }
}
