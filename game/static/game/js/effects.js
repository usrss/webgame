/**
 * Evolution and level-up effects (Phase 4).
 *
 * The layer owns transient visual state for sprites: a white flash, a stage
 * override (the old form stays on screen until the midpoint), pixel particles
 * and a floating label. It also respects `prefers-reduced-motion`: no flashing
 * sequence and no particles, just one brief highlight and the text.
 */

const EVOLUTION_MS = 1500;
const LEVEL_UP_MS = 900;
const FLASH_MS = 110;
const PARTICLE_STEP_MS = 70;

const PARTICLE_COLORS = [
  "#f2c14e",
  "#d0616a",
  "#6cae4e",
  "#6cb8b0",
  "#f6f2e6",
  "#e08a3c",
];

const LABEL_FONT = "6px 'Press Start 2P', monospace";
const NO_VISUAL_STATE = { flash: false, stageOverride: null };

function randomBetween(min, max) {
  return min + Math.random() * (max - min);
}

export class EffectLayer {
  constructor({ reducedMotion = false } = {}) {
    this.reducedMotion = reducedMotion;
    this.effects = [];
    this.visuals = new Map();
  }

  spawnParticles(count) {
    const particles = [];
    for (let index = 0; index < count; index += 1) {
      particles.push({
        dx: randomBetween(-8, 8),
        dy: randomBetween(-8, 8),
        vx: randomBetween(-0.45, 0.45),
        vy: randomBetween(-0.8, -0.25),
        life: Math.floor(randomBetween(8, 16)),
        size: Math.random() < 0.3 ? 2 : 1,
        color: PARTICLE_COLORS[index % PARTICLE_COLORS.length],
      });
    }
    return particles;
  }

  addEvolution(sprite, { fromStage, toStage, stageName }, now) {
    // Guard against a poll and a feed response reporting the same evolution.
    const alreadyPlaying = this.effects.some(
      (effect) =>
        effect.kind === "evolution" &&
        effect.spriteId === sprite.id &&
        effect.toStage === toStage
    );
    if (alreadyPlaying) {
      return;
    }
    // Five evolutions now: later stages get a longer, bigger celebration.
    const stage = Math.max(0, Math.min(5, Number(toStage) || 0));
    this.effects.push({
      kind: "evolution",
      spriteId: sprite.id,
      sprite,
      fromStage,
      toStage,
      stageName,
      start: now,
      duration: EVOLUTION_MS + stage * 120,
      lastStep: now,
      particles: this.reducedMotion ? [] : this.spawnParticles(10 + stage * 8),
      visual: { flash: false, stageOverride: fromStage },
    });
  }

  addLevelUp(sprite, now) {
    this.effects.push({
      kind: "levelup",
      spriteId: sprite.id,
      sprite,
      start: now,
      duration: LEVEL_UP_MS,
      lastStep: now,
      particles: this.reducedMotion ? [] : this.spawnParticles(7),
      visual: { flash: false, stageOverride: null },
    });
  }

  update(now) {
    this.visuals.clear();

    for (const effect of this.effects) {
      const elapsed = now - effect.start;
      const progress = Math.min(1, elapsed / effect.duration);

      if (effect.kind === "evolution") {
        const pastMidpoint = progress >= 0.5;
        effect.visual.stageOverride = pastMidpoint ? effect.toStage : effect.fromStage;
        if (this.reducedMotion) {
          effect.visual.flash = elapsed < 200;
        } else {
          effect.visual.flash =
            progress < 0.6 && Math.floor(elapsed / FLASH_MS) % 2 === 0;
        }
      }

      const steps = Math.floor((now - effect.lastStep) / PARTICLE_STEP_MS);
      if (steps > 0) {
        effect.lastStep += steps * PARTICLE_STEP_MS;
        for (const particle of effect.particles) {
          particle.dx += particle.vx * steps;
          particle.dy += particle.vy * steps;
          particle.vy -= 0.1 * steps; // gravity-up: the burst drifts toward the surface
          particle.life -= steps;
        }
        effect.particles = effect.particles.filter((particle) => particle.life > 0);
      }

      this.visuals.set(effect.spriteId, effect.visual);
    }

    this.effects = this.effects.filter(
      (effect) => now - effect.start < effect.duration
    );
  }

  visualFor(fishId) {
    return this.visuals.get(fishId) ?? NO_VISUAL_STATE;
  }

  draw(ctx, now) {
    for (const effect of this.effects) {
      const elapsed = now - effect.start;
      const progress = Math.min(1, elapsed / effect.duration);

      for (const particle of effect.particles) {
        const x = Math.round(effect.sprite.x + 16 + particle.dx);
        const y = Math.round(effect.sprite.y + 16 + particle.dy);
        ctx.fillStyle = particle.color;
        ctx.fillRect(x, y, particle.size, particle.size);
      }

      const rise = Math.round(progress * 14);
      const spriteTop = Math.round(effect.sprite.y);
      const text =
        effect.kind === "evolution"
          ? `${effect.sprite.name} evolved into ${effect.stageName}!`
          : "+LV";

      this.drawLabel(ctx, text, effect.sprite.x, spriteTop - 4 - rise);
    }
  }

  drawLabel(ctx, text, centerX, baselineY) {
    ctx.font = LABEL_FONT;
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";

    const width = ctx.measureText(text).width;
    const x = Math.round(Math.max(1, Math.min(centerX + 16 - width / 2, 320 - width - 1)));
    const y = Math.round(Math.max(8, baselineY));

    ctx.fillStyle = "#0b1020";
    ctx.fillText(text, x - 1, y);
    ctx.fillText(text, x + 1, y);
    ctx.fillText(text, x, y - 1);
    ctx.fillText(text, x, y + 1);
    ctx.fillStyle = "#f2c14e";
    ctx.fillText(text, x, y);
  }
}
