/**
 * Band editor helper (Phase 8).
 *
 * Reads the item numbers embedded by the preview page and updates each band's
 * question count, overlap warnings and "not used" totals as the teacher types.
 * The server re-validates everything on save; this is only live feedback.
 */

const KEYS = ["easy", "medium", "hard"];

function readNumbers() {
  const script = document.getElementById("quiz-item-numbers");
  if (!script) {
    return [];
  }
  try {
    const parsed = JSON.parse(script.textContent || "[]");
    return Array.isArray(parsed) ? parsed.map(Number).filter(Number.isFinite) : [];
  } catch (error) {
    return [];
  }
}

function value(id) {
  const input = document.getElementById(id);
  if (!input || input.value.trim() === "") {
    return null;
  }
  const number = Number(input.value);
  return Number.isInteger(number) ? number : null;
}

function update() {
  const numbers = readNumbers();
  const form = document.querySelector("form[data-warn-size]");
  const warnSize = Number(form?.dataset.warnSize) || 0;
  const bands = [];
  const notes = [];

  for (const key of KEYS) {
    const start = value(`${key}-start`);
    const end = value(`${key}-end`);
    const countEl = document.getElementById(`${key}-count`);
    const label = document.getElementById(`${key}-start`)?.closest("tr")?.querySelector("th")?.textContent?.trim() || key;

    if (start === null && end === null) {
      if (countEl) {
        countEl.textContent = "0";
      }
      continue;
    }
    if (start === null || end === null || end < start) {
      if (countEl) {
        countEl.textContent = "?";
      }
      notes.push(`${label}: set both numbers (last must be the same or larger).`);
      continue;
    }

    const count = numbers.filter((number) => number >= start && number <= end).length;
    if (countEl) {
      countEl.textContent = String(count);
    }
    if (count === 0) {
      notes.push(`${label}: no questions in items ${start}-${end}.`);
    } else if (warnSize && count < warnSize) {
      notes.push(`${label}: only ${count} question(s); ${warnSize} or more gives players variety.`);
    }
    bands.push({ label, start, end });
  }

  for (let i = 0; i < bands.length; i += 1) {
    for (let j = i + 1; j < bands.length; j += 1) {
      if (bands[i].start <= bands[j].end && bands[i].end >= bands[j].start) {
        notes.push(`${bands[i].label} and ${bands[j].label} overlap.`);
      }
    }
  }

  const covered = numbers.filter((number) =>
    bands.some((band) => number >= band.start && number <= band.end)
  ).length;
  if (numbers.length && covered < numbers.length) {
    notes.push(`${numbers.length - covered} item(s) are not in any band and will not be used.`);
  }

  const warning = document.getElementById("band-warning");
  if (warning) {
    warning.textContent = notes.join(" ");
  }
}

for (const key of KEYS) {
  document.getElementById(`${key}-start`)?.addEventListener("input", update);
  document.getElementById(`${key}-end`)?.addEventListener("input", update);
}
update();
