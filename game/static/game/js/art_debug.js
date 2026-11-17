/**
 * Staff-only art grid (Phase 9): every species x stage x accessory.
 * Uses the same composite renderer as the tank, so what you see is what ships.
 */

import { compositeFor, loadArtData } from "./fishRenderer.js";

const SLOTS = ["head", "face", "body", "tail"];
const SLOT_LABELS = { head: "Head", face: "Face", body: "Body", tail: "Tail" };

const statusEl = document.getElementById("art-status");
const tabsEl = document.getElementById("art-slots");
const gridEl = document.getElementById("art-grid");
const facingEl = document.getElementById("art-facing");
const speciesData = JSON.parse(document.getElementById("art-species")?.textContent || "[]");

let art = {};
let activeSlot = "head";

function makeCanvas(species, stage, frame, equipped) {
  const composite = compositeFor(species, stage, frame, equipped);
  const canvas = document.createElement("canvas");
  canvas.width = 32;
  canvas.height = 32;
  canvas.className = "art-cell";
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  if (!composite) {
    return canvas;
  }
  if (facingEl.checked) {
    ctx.save();
    ctx.translate(32, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(composite, 0, 0);
    ctx.restore();
  } else {
    ctx.drawImage(composite, 0, 0);
  }
  return canvas;
}

function render() {
  gridEl.replaceChildren();
  const items = Object.entries(art).filter(([, entry]) => entry.slot === activeSlot);

  for (const species of speciesData) {
    const block = document.createElement("section");
    block.className = "art-species";
    const heading = document.createElement("h2");
    heading.textContent = species.name;
    block.append(heading);

    species.stages.forEach((stageName, stage) => {
      const row = document.createElement("div");
      row.className = "art-row";

      const label = document.createElement("span");
      label.className = "art-label";
      label.textContent = `${stage}: ${stageName}`;
      row.append(label);

      row.append(makeCanvas(species.key, stage, 0, {}));
      for (const [key, entry] of items) {
        const canvas = makeCanvas(species.key, stage, 0, {
          [entry.slot]: key,
        });
        canvas.title = key;
        canvas.setAttribute("aria-label", `${species.name} ${stageName} ${key}`);
        row.append(canvas);
      }
      block.append(row);
    });
    gridEl.append(block);
  }
  statusEl.textContent = `${speciesData.length} species · ${items.length} ${SLOT_LABELS[activeSlot]} items`;
}

function renderTabs() {
  tabsEl.replaceChildren();
  for (const slot of SLOTS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-small wardrobe-tab";
    button.textContent = SLOT_LABELS[slot];
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", slot === activeSlot ? "true" : "false");
    if (slot === activeSlot) {
      button.classList.add("is-active");
    }
    button.addEventListener("click", () => {
      activeSlot = slot;
      renderTabs();
      render();
    });
    tabsEl.append(button);
  }
}

async function start() {
  const base = gridEl.dataset.artBase || "/static/game/data/";
  ({ art } = await loadArtData(base));
  renderTabs();
  render();
}

facingEl.addEventListener("change", render);
document.getElementById("art-redraw").addEventListener("click", render);
start();
