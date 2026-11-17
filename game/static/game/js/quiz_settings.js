/**
 * Quiz source form helper (Phase 8).
 *
 * Shows the quiz picker only for the custom source and the band picker only for
 * fixed mode. The server validates the same rules, so this is only clarity.
 */

const source = document.getElementById("quiz-source");
const quizSetField = document.getElementById("quiz-set-field");
const mode = document.getElementById("quiz-mode");
const fixedField = document.getElementById("quiz-fixed-field");

function sync() {
  if (quizSetField) {
    quizSetField.hidden = !source || source.value !== "custom";
  }
  if (fixedField) {
    fixedField.hidden = !mode || mode.value !== "fixed";
  }
}

source?.addEventListener("change", sync);
mode?.addEventListener("change", sync);
sync();
