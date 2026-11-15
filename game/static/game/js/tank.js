/**
 * Tank page entry point (Phases 3-4).
 *
 * Owns the render loop, the 7 s state poll, the feed button, sprite loading and
 * the client-side reconciliation of fish state. Draw order per frame:
 * static background (water, rays, back plants) -> fish -> front plants, sand,
 * bubbles -> effects.
 */

import { ApiError, feed, fetchState } from "./api.js";
import { Background } from "./background.js";
import { EffectLayer } from "./effects.js";
import { FishSprite } from "./fishSprite.js";
import { initQuiz } from "./quiz.js";
import { initSprites, preload } from "./sprites.js";
import * as ui from "./ui.js";

const POLL_MS = 7000;
const BACKOFF_MS = 15000;
const TICK_MS = 250;

const canvas = document.getElementById("tank-canvas");
const context = canvas.getContext("2d");
context.imageSmoothingEnabled = false;

const stateUrl = canvas.dataset.stateUrl;
const feedUrl = canvas.dataset.feedUrl;
const quizNextUrl = canvas.dataset.quizNextUrl;
const quizAnswerUrl = canvas.dataset.quizAnswerUrl;
const myFishId = Number(canvas.dataset.me);
const spriteBase = canvas.dataset.spriteBase || "/static/game/sprites/";

const prefersReducedMotion =
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

initSprites(spriteBase);
const background = new Background();
const effects = new EffectLayer({ reducedMotion: prefersReducedMotion });

const sprites = new Map();
const knownStages = new Map();

let assetsReady = false;
let assetsFailed = false;
let pollTimer = null;
let polling = false;
let feeding = false;
let stopped = false;
let fontReady = false;
let serverOffsetMs = 0;
let cooldownEndsAt = 0;

ui.initUI();

const quiz = initQuiz({
  nextUrl: quizNextUrl,
  answerUrl: quizAnswerUrl,
  onFeed: (feedResult, serverTime) => {
    applyFeedResult(feedResult, serverTime);
    tick();
  },
});

/* ---------------------------------------------------------------- drawing */

function drawLoadingScreen(text) {
  context.fillStyle = "#0b1020";
  context.fillRect(0, 0, 320, 180);
  context.font = "8px 'Press Start 2P', monospace";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillStyle = "#f6f2e6";
  context.fillText(text, 160, 90);
  context.textAlign = "left";
  context.textBaseline = "alphabetic";
}

function drawAssetWarning() {
  context.font = "6px 'Press Start 2P', monospace";
  context.textAlign = "left";
  context.textBaseline = "alphabetic";
  context.fillStyle = "#0b1020";
  context.fillText("sprites unavailable - placeholders", 5, 11);
  context.fillStyle = "#d0616a";
  context.fillText("sprites unavailable - placeholders", 4, 10);
}

function frame(now) {
  if (!assetsReady) {
    drawLoadingScreen("loading...");
    requestAnimationFrame(frame);
    return;
  }

  effects.update(now);
  background.drawBack(context);

  for (const sprite of sprites.values()) {
    if (!document.hidden) {
      sprite.update(now);
    }
    sprite.draw(context, now, {
      fontReady,
      ...effects.visualFor(sprite.id),
    });
  }

  background.drawFront(context, now);
  effects.draw(context, now);

  if (assetsFailed) {
    drawAssetWarning();
  }

  requestAnimationFrame(frame);
}

/* ------------------------------------------------------------ server sync */

function triggerEvolution(sprite, fromStage, toStage) {
  effects.addEvolution(
    sprite,
    {
      fromStage,
      toStage,
      stageName: sprite.stageName || `stage ${toStage}`,
    },
    performance.now()
  );
  ui.toast(
    `${sprite.name} evolved into ${sprite.stageName || "a new form"}!`,
    "toast-success"
  );
}

function applyState(payload) {
  serverOffsetMs = Date.now() - Date.parse(payload.server_time);

  const alive = new Set();
  for (const data of payload.fish) {
    alive.add(data.id);
    let sprite = sprites.get(data.id);
    if (!sprite) {
      sprite = new FishSprite(data, data.id === myFishId);
      sprites.set(data.id, sprite);
    } else {
      // Update stats only: an existing fish keeps swimming where it is.
      sprite.setStats(data);
    }

    const previousStage = knownStages.get(data.id);
    if (previousStage !== undefined && data.stage > previousStage) {
      // Another player's fish evolved (or an admin changed it): play it once.
      triggerEvolution(sprite, previousStage, data.stage);
    }
    knownStages.set(data.id, data.stage);
  }

  for (const id of [...sprites.keys()]) {
    if (!alive.has(id)) {
      sprites.delete(id);
      knownStages.delete(id);
    }
  }

  const myFish = payload.fish.find((fish) => fish.id === payload.me.fish_id);
  if (myFish) {
    ui.renderMyFish(myFish);
    syncCooldown(myFish.cooldown_remaining, payload.server_time);
  }
  if (payload.quiz) {
    quiz.setState(payload.quiz);
  }
  ui.renderMembers(payload.fish, payload.me.fish_id);
}

/** Convert a server-relative cooldown into a local-clock deadline. */
function syncCooldown(secondsRemaining, serverTime) {
  const localNow = Date.parse(serverTime) + serverOffsetMs;
  cooldownEndsAt = localNow + Math.max(0, Number(secondsRemaining) || 0) * 1000;
  tick();
}

function schedulePoll(delay) {
  window.clearTimeout(pollTimer);
  if (stopped) {
    return;
  }
  pollTimer = window.setTimeout(poll, delay);
}

async function poll() {
  if (stopped) {
    return;
  }
  if (document.hidden) {
    schedulePoll(POLL_MS);
    return;
  }
  if (polling) {
    return;
  }
  polling = true;
  try {
    const payload = await fetchState(stateUrl);
    if (stopped) {
      return;
    }
    applyState(payload);
    ui.setReconnect(false);
    schedulePoll(POLL_MS);
  } catch (error) {
    if (isGone(error)) {
      stopForGoneTank();
      return;
    }
    ui.setReconnect(true);
    schedulePoll(BACKOFF_MS);
  } finally {
    polling = false;
  }
}

function isGone(error) {
  return error instanceof ApiError && (error.status === 404 || error.status === 403);
}

function stopForGoneTank() {
  stopped = true;
  window.clearTimeout(pollTimer);
  ui.showTankGone();
}

/* -------------------------------------------------------------------- feed */

function formatCountdown(totalSeconds) {
  const seconds = Math.max(0, Math.ceil(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

function tick() {
  if (stopped) {
    return;
  }
  if (quiz.enabled && quiz.onlyFeeding) {
    const left = quiz.remaining;
    ui.setFeedState({
      enabled: left > 0 && !feeding,
      label: left > 0 ? "Answer & feed" : "No feeds left",
      hint:
        left > 0
          ? `${left} ${left === 1 ? "feed" : "feeds"} left today`
          : "New feeds arrive after midnight",
    });
    return;
  }
  const secondsLeft = (cooldownEndsAt - Date.now()) / 1000;
  if (secondsLeft > 0) {
    ui.setFeedState({
      enabled: false,
      label: `Feed in ${formatCountdown(secondsLeft)}`,
      hint: "",
    });
    return;
  }
  ui.setFeedState({
    enabled: !feeding,
    label: feeding ? "Feeding…" : "Feed",
    hint: "",
  });
}

/** Apply a feed result from either endpoint (timed feed or quiz answer). */
function applyFeedResult(result, serverTime) {
  const fish = result.fish;
  const sprite = sprites.get(fish.id);
  const now = performance.now();

  if (sprite) {
    sprite.setStats(fish);
    if (result.evolved) {
      triggerEvolution(sprite, result.old_stage, result.new_stage);
    } else if (result.leveled_up) {
      effects.addLevelUp(sprite, now);
      ui.toast(`Level up! Level ${fish.level}`, "toast-success");
    }
  }
  knownStages.set(fish.id, fish.stage);

  ui.renderMyFish(fish);
  syncCooldown(fish.cooldown_remaining, serverTime || result.server_time);

  if (result.xp_gained > 0) {
    ui.toast(`+${result.xp_gained} XP`);
  } else if (!result.leveled_up) {
    ui.toast("Already at max level");
  }

  // Refresh immediately so other players' updates arrive without waiting.
  schedulePoll(0);
}

async function onFeed() {
  if (feeding || stopped) {
    return;
  }
  if (quiz.enabled && quiz.onlyFeeding) {
    quiz.open();
    return;
  }
  feeding = true;
  ui.setFeedState({ enabled: false, label: "Feeding…" });

  try {
    const result = await feed(feedUrl);
    applyFeedResult(result);
  } catch (error) {
    if (error instanceof ApiError && error.status === 429) {
      const remaining = Number(error.data?.seconds_remaining ?? 0);
      cooldownEndsAt = Date.now() + Math.max(0, remaining) * 1000;
      ui.toast(`Still full — ${formatCountdown(remaining)}`, "toast-error");
    } else if (isGone(error)) {
      stopForGoneTank();
    } else {
      ui.toast("Could not feed — try again", "toast-error");
    }
  } finally {
    feeding = false;
    tick();
  }
}

/* ------------------------------------------------------------------- start */

function waitForFont() {
  if (!document.fonts || !document.fonts.load) {
    fontReady = true;
    return;
  }
  Promise.all([
    document.fonts.load("6px 'Press Start 2P'"),
    document.fonts.load("8px 'Press Start 2P'"),
  ])
    .then(() => {
      fontReady = true;
    })
    .catch(() => {
      fontReady = true;
    });
  // Never block labels forever on a slow/blocked font.
  window.setTimeout(() => {
    fontReady = true;
  }, 3000);
}

async function bootstrap() {
  const result = await preload();
  assetsFailed = result.failed.length > 0;
  if (assetsFailed) {
    console.warn("Some sprites failed to load:", result.failed.join(", "));
  }
  background.prepare();
  assetsReady = true;
}

document.getElementById("feed-button").addEventListener("click", onFeed);

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    window.clearTimeout(pollTimer);
    return;
  }
  if (!stopped) {
    poll();
  }
});

waitForFont();
bootstrap();
ui.setFeedState({ enabled: false, label: "Feed", hint: "" });
requestAnimationFrame(frame);
window.setInterval(tick, TICK_MS);
poll();
