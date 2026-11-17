/**
 * Quiz dialog (Phase 7).
 *
 * The server owns the question, the choices and the correct answer: this module
 * only renders whatever it is given and posts the chosen index back. Choices are
 * shuffled server-side, so nothing here can reveal the answer before submitting.
 *
 * Accessibility: real buttons (>= 44 px), keys 1-4 answer, Escape closes, the
 * result line is an aria-live status, and correctness is shown with text and a
 * glyph as well as colour.
 */

import { ApiError, postJson } from "./api.js";

const SUBJECT_LABELS = {
  math: "Math",
  spelling: "Spelling",
  reading: "Reading",
  science: "Science",
  general: "General knowledge",
};

const KEY_LABELS = ["1", "2", "3", "4", "5", "6"];

// Custom quizzes label the band instead of a school grade. Stars are a visual
// echo of the text label, never the only signal.
const DIFFICULTY_LABELS = { easy: "Easy", medium: "Medium", hard: "Hard" };
const DIFFICULTY_STARS = { easy: 1, medium: 2, hard: 3 };

function friendlyError(error) {
  if (error instanceof ApiError) {
    const code = error.data && error.data.error;
    if (code === "no_questions") {
      return "No questions are available right now. Tell the tank owner.";
    }
    if (code === "daily_cap") {
      return "That is every feed for today. Come back tomorrow!";
    }
    if (code === "too_fast") {
      return "One moment — the next question is almost ready.";
    }
  }
  return "Could not reach the tank. Check your connection and try again.";
}

export function initQuiz({ nextUrl, answerUrl, onFeed }) {
  const dialog = document.getElementById("quiz-dialog");
  if (!dialog || !nextUrl || !answerUrl) {
    return { setState() {}, open() {}, get onlyFeeding() { return false; } };
  }

  const subjectEl = document.getElementById("quiz-subject");
  const difficultyEl = document.getElementById("quiz-difficulty");
  const feedsEl = document.getElementById("quiz-feeds");
  const sourceEl = document.getElementById("quiz-source");
  const promptEl = document.getElementById("quiz-prompt");
  const choicesEl = document.getElementById("quiz-choices");
  const resultEl = document.getElementById("quiz-result");
  const anotherButton = document.getElementById("quiz-another");
  const closeButton = document.getElementById("quiz-close");

  let enabled = false;
  let onlyFeeding = false;
  let remaining = 0;
  let cap = 0;
  let attempt = null;
  let answered = false;
  let busy = false;
  let lastFocused = null;
  let retryTimer = null;
  let source = "builtin";
  let setName = "";

  const state = {
    setState(quiz) {
      if (!quiz) {
        return;
      }
      enabled = Boolean(quiz.enabled);
      onlyFeeding = Boolean(quiz.only_feeding);
      remaining = Number(quiz.remaining_today) || 0;
      cap = Number(quiz.cap) || 0;
      source = quiz.source === "custom" ? "custom" : "builtin";
      setName = quiz.set_name || "";
      updateSourceLabel();
    },
    open,
    get onlyFeeding() {
      return onlyFeeding;
    },
    get enabled() {
      return enabled;
    },
    get remaining() {
      return remaining;
    },
  };

  function updateSourceLabel() {
    if (!sourceEl) {
      return;
    }
    sourceEl.textContent =
      source === "custom"
        ? `Quiz: ${setName || "your uploaded quiz"}`
        : "Quiz: built-in questions";
  }

  function updateMeta() {
    const subject = attempt
      ? attempt.subject === "custom"
        ? "Your quiz"
        : SUBJECT_LABELS[attempt.subject] || "Question"
      : "";
    const grade = attempt && attempt.grade > 0 ? ` · Grade ${attempt.grade}` : "";
    subjectEl.textContent = attempt ? `${subject}${grade}` : "";

    if (difficultyEl) {
      const key = attempt && attempt.difficulty;
      const label = DIFFICULTY_LABELS[key];
      if (label) {
        difficultyEl.hidden = false;
        difficultyEl.textContent = `${label} ${"★".repeat(DIFFICULTY_STARS[key])}`;
        difficultyEl.dataset.difficulty = key;
      } else {
        difficultyEl.hidden = true;
        delete difficultyEl.dataset.difficulty;
      }
    }

    feedsEl.textContent = cap
      ? `${remaining} of ${cap} feeds left today`
      : `${remaining} feeds left today`;
  }

  function setChoicesDisabled(disabled) {
    for (const button of choicesEl.querySelectorAll("button")) {
      button.disabled = disabled;
    }
  }

  function clearResult() {
    resultEl.textContent = "";
    resultEl.classList.remove("is-correct", "is-wrong");
  }

  function renderQuestion(data) {
    attempt = data;
    answered = false;
    remaining = Number(data.remaining_today) || 0;
    cap = Number(data.cap) || cap;
    updateMeta();
    promptEl.textContent = data.prompt;
    choicesEl.replaceChildren();

    data.choices.forEach((choice, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "quiz-choice";
      button.dataset.index = String(index);

      const key = document.createElement("span");
      key.className = "quiz-key";
      key.textContent = KEY_LABELS[index] || String(index + 1);
      key.setAttribute("aria-hidden", "true");

      const label = document.createElement("span");
      label.className = "quiz-choice-text";
      label.textContent = choice;

      button.append(key, label);
      button.addEventListener("click", () => answer(index));
      choicesEl.append(button);
    });

    anotherButton.hidden = true;
    clearResult();
    const first = choicesEl.querySelector("button");
    if (first) {
      first.focus();
    }
  }

  async function fetchNext() {
    busy = true;
    anotherButton.hidden = true;
    promptEl.textContent = "Loading question…";
    choicesEl.replaceChildren();
    clearResult();
    try {
      const data = await postJson(nextUrl);
      renderQuestion(data);
    } catch (error) {
      handleError(error, true);
    } finally {
      busy = false;
    }
  }

  function handleError(error, allowRetry) {
    const code = error instanceof ApiError ? error.data && error.data.error : null;

    if (code === "too_fast") {
      const wait = Math.max(1, Number(error.data.retry_after) || 2);
      resultEl.textContent = friendlyError(error);
      retryTimer = window.setTimeout(() => {
        retryTimer = null;
        if (dialog.open) {
          fetchNext();
        }
      }, wait * 1000);
      return;
    }

    if (code === "expired" || code === "already_answered") {
      resultEl.textContent = "That question changed. Here is a fresh one.";
      if (dialog.open) {
        window.setTimeout(fetchNext, 0);
      }
      return;
    }

    if (code === "daily_cap") {
      remaining = 0;
      updateMeta();
      resultEl.textContent = friendlyError(error);
      resultEl.classList.remove("is-correct");
      resultEl.classList.add("is-wrong");
      choicesEl.replaceChildren();
      anotherButton.hidden = true;
      return;
    }

    resultEl.textContent = friendlyError(error);
    resultEl.classList.remove("is-correct");
    resultEl.classList.add("is-wrong");
    if (allowRetry) {
      anotherButton.hidden = false;
      anotherButton.textContent = "Try again";
    }
  }

  /** Mark only the button the player pressed; never reveal the right answer. */
  function markChosen(index, correct) {
    for (const button of choicesEl.querySelectorAll("button")) {
      button.disabled = true;
      if (Number(button.dataset.index) !== index) {
        continue;
      }
      button.classList.add(correct ? "is-correct" : "is-wrong");
      const glyph = document.createElement("span");
      glyph.className = "quiz-glyph";
      glyph.setAttribute("aria-hidden", "true");
      glyph.textContent = correct ? "✓" : "✗";
      button.append(glyph);
    }
  }

  async function answer(index) {
    if (busy || answered || !attempt) {
      return;
    }
    busy = true;
    answered = true;
    setChoicesDisabled(true);

    try {
      const data = await postJson(answerUrl, {
        attempt_id: attempt.attempt_id,
        selected_index: index,
      });

      markChosen(index, Boolean(data.correct));
      remaining = Number(data.remaining_today) || 0;
      updateMeta();

      if (data.correct) {
        resultEl.textContent = data.explanation
          ? `Correct! ${data.explanation}`
          : "Correct! Your fish ate.";
        resultEl.classList.add("is-correct");
        resultEl.classList.remove("is-wrong");
        if (data.feed && typeof onFeed === "function") {
          onFeed(data.feed, data.server_time);
        }
      } else {
        // Say only that it was wrong: no answer and no explanation here.
        resultEl.textContent = "That answer is wrong. Try another question when you are ready.";
        resultEl.classList.add("is-wrong");
        resultEl.classList.remove("is-correct");
      }

      anotherButton.textContent = remaining > 0 ? "Another question" : "";
      anotherButton.hidden = remaining <= 0;
      if (remaining > 0) {
        anotherButton.focus();
      } else {
        closeButton.focus();
      }
    } catch (error) {
      answered = false;
      setChoicesDisabled(false);
      handleError(error, false);
    } finally {
      busy = false;
    }
  }

  function open() {
    if (!enabled) {
      return;
    }
    lastFocused = document.activeElement;
    clearResult();
    if (remaining <= 0) {
      attempt = null;
      updateMeta();
      promptEl.textContent = "No feeds left today";
      resultEl.textContent =
        "You used all your feeds for today. A new day starts at midnight.";
      choicesEl.replaceChildren();
      anotherButton.hidden = true;
    }
    if (typeof dialog.showModal === "function") {
      if (!dialog.open) {
        dialog.showModal();
      }
    } else {
      dialog.setAttribute("open", "");
    }
    if (remaining > 0) {
      if (attempt && !answered) {
        const first = choicesEl.querySelector("button");
        if (first) {
          first.focus();
        }
      } else {
        fetchNext();
      }
    }
  }

  function close() {
    if (retryTimer !== null) {
      window.clearTimeout(retryTimer);
      retryTimer = null;
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

  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      // Native <dialog> closes on Escape too; just keep focus restoration.
      close();
      return;
    }
    if (busy || answered || !attempt) {
      return;
    }
    const position = ["1", "2", "3", "4"].indexOf(event.key);
    if (position !== -1) {
      event.preventDefault();
      answer(position);
    }
  });

  anotherButton.addEventListener("click", fetchNext);
  closeButton.addEventListener("click", close);
  dialog.addEventListener("close", () => {
    if (lastFocused && typeof lastFocused.focus === "function") {
      lastFocused.focus();
    }
  });

  return state;
}
