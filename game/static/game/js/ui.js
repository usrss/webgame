/**
 * HTML panel updates: my fish stats, bars, member list, toasts and the
 * reconnect / no-longer-a-member indicators.
 *
 * Everything server-provided is written with textContent - never innerHTML.
 */

let els = null;

function byId(id) {
  return document.getElementById(id);
}

export function initUI() {
  els = {
    myName: byId("my-fish-name"),
    myLevel: byId("my-fish-level"),
    xpBar: byId("xp-bar"),
    xpText: byId("xp-text"),
    hungerBar: byId("hunger-bar"),
    hungerText: byId("hunger-text"),
    feedButton: byId("feed-button"),
    feedHint: byId("feed-hint"),
    fishList: byId("fish-list"),
    pearls: byId("pearl-balance"),
    toasts: byId("toasts"),
    reconnect: byId("reconnect-indicator"),
    tankGone: byId("tank-gone"),
  };
  return els;
}

/** Fill a segmented bar: each segment is on or off, no gradients. */
export function setBar(bar, percent) {
  if (!bar) {
    return;
  }
  const segments = bar.children;
  const filled = Math.round(
    (Math.max(0, Math.min(100, percent)) / 100) * segments.length
  );
  for (let index = 0; index < segments.length; index += 1) {
    segments[index].classList.toggle("is-on", index < filled);
  }
}

export function renderMyFish(fish) {
  if (!els || !fish) {
    return;
  }
  els.myName.textContent = fish.name;
  els.myLevel.textContent = `Level ${fish.level} · ${
    fish.stage_name || `Stage ${fish.stage}`
  }`;

  const ratio = fish.xp_needed > 0 ? (fish.xp / fish.xp_needed) * 100 : 100;
  setBar(els.xpBar, ratio);
  els.xpText.textContent =
    fish.xp_needed > 0 ? `${fish.xp}/${fish.xp_needed}` : "MAX";

  setBar(els.hungerBar, fish.hunger);
  els.hungerText.textContent = `${fish.hunger}%`;
}

export function renderMembers(fishList, myFishId) {
  if (!els) {
    return;
  }

  // Reconcile in place: existing rows keep their server-rendered action forms
  // (report/rename), only the text is refreshed. Newly joined fish get a plain
  // row; their action buttons appear after the next page load.
  const seen = new Set();
  for (const fish of fishList) {
    seen.add(String(fish.id));
    let item = els.fishList.querySelector(`li[data-fish-id="${fish.id}"]`);
    if (!item) {
      item = document.createElement("li");
      item.dataset.fishId = fish.id;
      const name = document.createElement("span");
      name.className = "fish-name";
      const level = document.createElement("span");
      level.className = "fish-level";
      item.append(name, level);
      els.fishList.append(item);
    }
    const nameEl = item.querySelector(".fish-name");
    const levelEl = item.querySelector(".fish-level");
    if (nameEl) {
      nameEl.textContent = fish.id === myFishId ? `${fish.name} (you)` : fish.name;
    }
    if (levelEl) {
      levelEl.textContent = `Lv ${fish.level}`;
    }
  }

  const empty = els.fishList.querySelector('li[data-empty="true"]');
  if (empty && fishList.length > 0) {
    empty.remove();
  }
  for (const item of [...els.fishList.querySelectorAll("li[data-fish-id]")]) {
    if (!seen.has(item.dataset.fishId)) {
      item.remove();
    }
  }
}

export function setFeedState({ enabled, label, hint }) {
  if (!els) {
    return;
  }
  els.feedButton.disabled = !enabled;
  if (label !== undefined) {
    els.feedButton.textContent = label;
  }
  if (hint !== undefined) {
    els.feedHint.textContent = hint;
  }
}

export function toast(text, kind = "", onClick = null) {
  if (!els) {
    return;
  }
  const node = document.createElement("div");
  node.className = kind ? `toast ${kind}` : "toast";
  node.textContent = text;
  if (typeof onClick === "function") {
    node.classList.add("toast-action");
    node.setAttribute("role", "button");
    node.tabIndex = 0;
    const activate = () => {
      onClick();
      node.remove();
    };
    node.addEventListener("click", activate);
    node.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activate();
      }
    });
  }
  els.toasts.append(node);
  setTimeout(() => node.remove(), onClick ? 9000 : 3000);
}

export function setReconnect(isReconnecting) {
  if (els) {
    els.reconnect.hidden = !isReconnecting;
  }
}

export function showTankGone() {
  if (!els) {
    return;
  }
  els.tankGone.hidden = false;
  els.feedButton.disabled = true;
}
