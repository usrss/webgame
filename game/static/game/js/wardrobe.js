/**
 * Wardrobe dialog (Phase 9).
 *
 * Pearls, prices, stages and ownership all come from the server. The client
 * only sends a slot and an accessory key. All text is written with textContent.
 */

import { drawPreview } from "./fishRenderer.js";

const SLOT_LABELS = { head: "Head", face: "Face", body: "Body", tail: "Tail" };

function friendlyError(code) {
  switch (code) {
    case "not_enough_pearls":
      return "You need more pearls for that item.";
    case "already_owned":
      return "You already own that item.";
    case "not_for_sale":
      return "That item cannot be bought with pearls.";
    case "not_owned":
      return "Equip only items you own.";
    case "invalid_slot":
      return "That item does not go in this slot.";
    case "not_found":
      return "That item does not exist.";
    default:
      return "Something went wrong. Try again.";
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
  });
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }
  if (!response.ok) {
    const error = new Error(data.error || "request_failed");
    error.code = data.error;
    error.data = data;
    throw error;
  }
  return data;
}

export function initWardrobe({ stateUrl, equipUrl, buyUrl }) {
  const dialog = document.getElementById("wardrobe-dialog");
  if (!dialog || !stateUrl || !equipUrl || !buyUrl) {
    return { open() {}, refresh() {} };
  }

  const pearlsEl = document.getElementById("wardrobe-pearls");
  const tabsEl = document.getElementById("wardrobe-tabs");
  const listEl = document.getElementById("wardrobe-list");
  const statusEl = document.getElementById("wardrobe-status");
  const preview = document.getElementById("wardrobe-preview");
  const previewCtx = preview.getContext("2d");
  const closeButton = document.getElementById("wardrobe-close");

  let state = null;
  let activeSlot = "head";
  let pendingBuy = null;
  let animation = null;
  let lastFocused = null;

  function announce(message) {
    statusEl.textContent = message;
  }

  function drawFrame(time) {
    if (!state) {
      return;
    }
    const frame = Math.floor(time / 130) % 4;
    drawPreview(previewCtx, state.species, state.stage, frame, state.equipped, 2);
    animation = window.requestAnimationFrame(drawFrame);
  }

  function setState(next) {
    state = next;
    if (!SLOT_LABELS[activeSlot]) {
      activeSlot = "head";
    }
    render();
  }

  function renderTabs() {
    tabsEl.replaceChildren();
    for (const slot of Object.keys(SLOT_LABELS)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-small wardrobe-tab";
      button.textContent = SLOT_LABELS[slot];
      button.setAttribute("role", "tab");
      const selected = slot === activeSlot;
      button.setAttribute("aria-selected", selected ? "true" : "false");
      if (selected) {
        button.classList.add("is-active");
      }
      button.addEventListener("click", () => {
        activeSlot = slot;
        pendingBuy = null;
        render();
      });
      tabsEl.append(button);
    }
  }

  function itemRow(item) {
    const row = document.createElement("div");
    row.className = "wardrobe-item";

    const name = document.createElement("span");
    name.className = "wardrobe-item-name";
    name.textContent = item.name;
    row.append(name);

    const meta = document.createElement("span");
    meta.className = "muted";
    meta.textContent = item.rarity;
    row.append(meta);

    const action = document.createElement("span");
    action.className = "wardrobe-item-action";

    if (item.owned) {
      const equipped = state.equipped[item.slot] === item.key;
      const button = document.createElement("button");
      button.type = "button";
      button.className = equipped ? "btn btn-small btn-secondary" : "btn btn-small";
      button.textContent = equipped ? "Unequip" : "Equip";
      button.addEventListener("click", () => equip(item, equipped ? null : item.key));
      action.append(button);
    } else if (item.unlock_type === "shop") {
      const price = document.createElement("span");
      price.className = "wardrobe-price";
      price.textContent = `${item.price} pearls`;
      action.append(price);

      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-small";
      const affordable = state.pearls >= item.price;
      if (!affordable) {
        button.disabled = true;
        button.textContent = "Buy";
        const missing = document.createElement("span");
        missing.className = "field-error";
        missing.textContent = `Need ${item.price - state.pearls} more`;
        action.append(missing);
      } else if (pendingBuy === item.key) {
        button.textContent = `Confirm — ${item.price} pearls`;
        button.classList.add("btn-danger");
        button.addEventListener("click", () => buy(item));
        action.append(button);
      } else {
        button.textContent = "Buy";
        button.addEventListener("click", () => {
          pendingBuy = item.key;
          announce(`Press confirm to buy ${item.name} for ${item.price} pearls.`);
          render();
        });
        action.append(button);
      }
    } else if (item.unlock_type === "evolution") {
      const stageName =
        (state.stage_names && state.stage_names[item.unlock_stage]) || "";
      const label = document.createElement("span");
      label.className = "muted";
      label.textContent =
        state.stage < item.unlock_stage
          ? `Reach stage ${item.unlock_stage}${stageName ? `: ${stageName}` : ""}`
          : "Evolution gift";
      action.append(label);
    } else {
      const label = document.createElement("span");
      label.className = "muted";
      label.textContent = "Starter item";
      action.append(label);
    }

    row.append(action);
    return row;
  }

  function render() {
    pearlsEl.textContent = `${state.pearls} pearls`;
    renderTabs();
    listEl.replaceChildren();
    const items = state.catalog.filter((item) => item.slot === activeSlot);
    for (const item of items) {
      listEl.append(itemRow(item));
    }
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "No items in this slot yet.";
      listEl.append(empty);
    }
  }

  async function refresh() {
    try {
      setState(await requestJson(stateUrl));
    } catch (error) {
      announce("Could not load your wardrobe.");
    }
  }

  async function equip(item, key) {
    try {
      const data = await requestJson(equipUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content || "",
        },
        body: JSON.stringify({ slot: item.slot, accessory_key: key }),
      });
      state.equipped = data.equipped;
      announce(key ? `${item.name} equipped.` : `${item.name} removed.`);
      pendingBuy = null;
      render();
    } catch (error) {
      announce(friendlyError(error.code));
    }
  }

  async function buy(item) {
    try {
      const data = await requestJson(buyUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content || "",
        },
        body: JSON.stringify({ accessory_key: item.key }),
      });
      announce(`You bought ${item.name}. ${data.pearls} pearls left.`);
      pendingBuy = null;
      await refresh();
      activeSlot = item.slot;
      render();
    } catch (error) {
      announce(friendlyError(error.code));
      pendingBuy = null;
      render();
    }
  }

  function open(slot, itemKey) {
    if (SLOT_LABELS[slot]) {
      activeSlot = slot;
    }
    pendingBuy = itemKey || null;
    lastFocused = document.activeElement;
    announce("");
    if (typeof dialog.showModal === "function") {
      if (!dialog.open) {
        dialog.showModal();
      }
    } else {
      dialog.setAttribute("open", "");
    }
    refresh().then(() => {
      if (itemKey) {
        announce(`Looking at ${itemKey.replaceAll("_", " ")}.`);
      }
    });
    if (animation === null) {
      animation = window.requestAnimationFrame(drawFrame);
    }
  }

  function close() {
    if (animation !== null) {
      window.cancelAnimationFrame(animation);
      animation = null;
    }
    if (typeof dialog.close === "function") {
      dialog.close();
    } else {
      dialog.removeAttribute("open");
    }
    if (lastFocused && typeof lastFocused.focus === "function") {
      lastFocused.focus();
    }
  }

  closeButton.addEventListener("click", close);
  dialog.addEventListener("close", () => {
    if (animation !== null) {
      window.cancelAnimationFrame(animation);
      animation = null;
    }
  });

  return { open, refresh, close };
}
