"""TXT and DOCX parsing using the strict written layout (Phase 8).

::

    1. What is 2 + 2?
    A. 3
    B. 4
    C. 5
    D. 6
    Answer: B
    Explanation: Add the two numbers.

An item ends at its ``Answer:`` line.  The item number and the explanation are
optional; choice letters must be typed in the text.  Word's automatic lists do
not put their numbers/letters in the file, so those raise a specific error.
"""

from __future__ import annotations

import io
import re

from .base import RawItem, clean_text
from .safety import UploadRejected

NUMBER_RE = re.compile(r"^(\d{1,4})[.)]\s*(.*)$")
CHOICE_RE = re.compile(r"^\(?([A-Da-d])[.)]\s+(.+)$")
ANSWER_RE = re.compile(r"^answer\s*[:\uff1a]\s*(.*)$", re.IGNORECASE)
EXPLANATION_RE = re.compile(r"^explanation\s*[:\uff1a]\s*(.*)$", re.IGNORECASE)

AUTO_LIST_HINT = (
    "Choices must be typed as A. B. C. D. (Word automatic lists can't be read). "
    "Use the template or the CSV/XLSX format."
)


def parse_text(text: str) -> tuple[list[RawItem], list[str]]:
    """Parse the line layout above.  Returns ``(items, errors)``."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    raws: list[RawItem] = []
    errors: list[str] = []

    prompt_lines: list[str] = []
    choices: list[tuple[str, str]] = []
    number: int | None = None
    start_line = 0
    previous: RawItem | None = None

    def reset() -> None:
        nonlocal prompt_lines, choices, number, start_line
        prompt_lines, choices, number, start_line = [], [], None, 0

    def discard_unanswered() -> None:
        if prompt_lines or choices:
            errors.append(
                f"Line {start_line}: this item has no Answer: line. Add a line "
                "like ``Answer: B`` after its choices."
            )
            reset()

    def finish(answer: str, answer_line: int) -> None:
        nonlocal previous
        if not prompt_lines and not choices:
            errors.append(
                f"Line {answer_line}: Answer: appears before any question."
            )
            return
        if not choices:
            errors.append(
                f"Line {answer_line}, item {number if number is not None else '?'}: "
                f"no choices were found. {AUTO_LIST_HINT}"
            )
            reset()
            return

        letters = "".join(letter.upper() for letter, _text in choices)
        expected = "ABCD"[: len(choices)]
        if letters != expected:
            errors.append(
                f"Line {start_line}: choices must be labelled A, B, C (and "
                f"optionally D) in order. Found {', '.join(letters)}."
            )
            reset()
            return

        item = RawItem(
            prompt=" ".join(prompt_lines),
            choices=[text for _letter, text in choices],
            answer=answer,
            number=number,
            source_ref=f"Line {start_line}",
        )
        raws.append(item)
        previous = item
        reset()

    for line_number, raw_line in enumerate(lines, start=1):
        line = clean_text(raw_line)
        if not line:
            continue

        explanation = EXPLANATION_RE.match(line)
        if explanation:
            if previous is not None and not prompt_lines and not choices:
                previous.explanation = explanation.group(1)
            else:
                errors.append(
                    f"Line {line_number}: put ``Explanation:`` directly after its "
                    "``Answer:`` line."
                )
            continue

        answer = ANSWER_RE.match(line)
        if answer:
            finish(answer.group(1), line_number)
            continue

        choice = CHOICE_RE.match(line)
        if choice:
            if not prompt_lines and not choices:
                start_line = line_number
            if start_line == 0:
                start_line = line_number
            choices.append((choice.group(1), choice.group(2)))
            continue

        numbered = NUMBER_RE.match(line)
        if numbered:
            discard_unanswered()
            start_line = line_number
            number = int(numbered.group(1))
            prompt_lines = [numbered.group(2)]
            continue

        if not prompt_lines and not choices:
            start_line = line_number
        prompt_lines.append(line)

    discard_unanswered()
    return raws, errors


def parse_txt(data: bytes) -> tuple[list[RawItem], list[str], str]:
    from .tabular import decode_text

    text, encoding = decode_text(data)
    raws, errors = parse_text(text)
    return raws, errors, encoding


def parse_docx(data: bytes) -> tuple[list[RawItem], list[str], str]:
    """Read paragraphs only: tables, images, headers and footers are ignored."""
    from docx import Document

    try:
        document = Document(io.BytesIO(data))
    except Exception:
        raise UploadRejected(
            "That Word document could not be opened. Re-save it as .docx and try "
            "again."
        )

    try:
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    except Exception:
        raise UploadRejected(
            "That Word document's text could not be read. Re-save it and try again."
        )
    if not text.strip():
        return [], [
            "No text was found in that document. Put the questions in normal "
            "paragraphs, not in a table or an image."
        ], ""
    raws, errors = parse_text(text)
    return raws, errors, ""


__all__ = ["parse_docx", "parse_text", "parse_txt"]
