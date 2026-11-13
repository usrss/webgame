/**
 * Pixel-style confirmations and copy buttons (Phase 5).
 *
 * Any form with `data-confirm="message"` is intercepted and confirmed in the
 * in-page <dialog> instead of the browser's native confirm(). The message is
 * written with textContent, so server-provided names are never parsed as HTML.
 */

const dialog = document.getElementById("pixel-dialog");
const dialogMessage = document.getElementById("pixel-dialog-message");
const dialogConfirm = document.getElementById("pixel-dialog-confirm");

function copyText(text, onDone) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(onDone, () => fallbackCopy(text, onDone));
    return;
  }
  fallbackCopy(text, onDone);
}

function fallbackCopy(text, onDone) {
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  try {
    document.execCommand("copy");
    onDone(true);
  } catch {
    onDone(false);
  }
  area.remove();
}

if (dialog && dialogMessage) {
  document.addEventListener("submit", (event) => {
    const form = event.target.closest("form[data-confirm]");
    if (!form || form.dataset.confirmed === "true") {
      return;
    }
    event.preventDefault();
    dialogMessage.textContent = form.dataset.confirm;
    if (dialogConfirm) {
      dialogConfirm.textContent = form.dataset.confirmLabel || "Confirm";
    }
    dialog.returnValue = "";
    dialog.showModal();

    dialog.addEventListener(
      "close",
      () => {
        if (dialog.returnValue === "confirm") {
          form.dataset.confirmed = "true";
          form.submit();
        }
      },
      { once: true }
    );
  });
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) {
    return;
  }
  const source = document.querySelector(button.dataset.copy);
  const text = source ? source.textContent.trim() : "";
  if (!text) {
    return;
  }
  const original = button.textContent;
  copyText(text, (ok) => {
    button.textContent = ok ? "Copied!" : "Copy failed";
    window.setTimeout(() => {
      button.textContent = original;
    }, 1500);
  });
});
