"""Downloadable upload templates (Phase 8), generated in code.

Each template has the same three sample items so a teacher can see how the
four formats line up.
"""

from __future__ import annotations

import csv
import io

SAMPLE_ITEMS = [
    {
        "number": 1,
        "prompt": "What is 2 + 2?",
        "choices": ["3", "4", "5", "6"],
        "correct_index": 1,
        "explanation": "Add the two numbers.",
    },
    {
        "number": 2,
        "prompt": "Which planet do we live on?",
        "choices": ["Mars", "Earth", "Venus"],
        "correct_index": 1,
        "explanation": "Earth is our home planet.",
    },
    {
        "number": 3,
        "prompt": "What is the plural of 'box'?",
        "choices": ["boxs", "boxes", "boxen", "boxies"],
        "correct_index": 1,
        "explanation": "Words ending in x add -es.",
    },
]

CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _letter(index: int) -> str:
    return "ABCD"[index]


def csv_bytes() -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["no", "question", "a", "b", "c", "d", "answer", "explanation"])
    for item in SAMPLE_ITEMS:
        choices = item["choices"] + [""] * (4 - len(item["choices"]))
        writer.writerow(
            [
                item["number"],
                item["prompt"],
                *choices,
                _letter(item["correct_index"]),
                item["explanation"],
            ]
        )
    return buffer.getvalue().encode("utf-8")


def txt_bytes() -> bytes:
    lines = []
    for item in SAMPLE_ITEMS:
        lines.append(f"{item['number']}. {item['prompt']}")
        for position, choice in enumerate(item["choices"]):
            lines.append(f"{_letter(position)}. {choice}")
        lines.append(f"Answer: {_letter(item['correct_index'])}")
        if item["explanation"]:
            lines.append(f"Explanation: {item['explanation']}")
        lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")


def xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Quiz"
    sheet.append(["no", "question", "a", "b", "c", "d", "answer", "explanation"])
    for item in SAMPLE_ITEMS:
        choices = item["choices"] + [""] * (4 - len(item["choices"]))
        sheet.append(
            [
                item["number"],
                item["prompt"],
                *choices,
                _letter(item["correct_index"]),
                item["explanation"],
            ]
        )
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def docx_bytes() -> bytes:
    from docx import Document

    document = Document()
    document.add_heading("Quiz template", level=1)
    document.add_paragraph(
        "Type choices as A. B. C. D. Word automatic lists cannot be read."
    )
    for item in SAMPLE_ITEMS:
        document.add_paragraph(f"{item['number']}. {item['prompt']}")
        for position, choice in enumerate(item["choices"]):
            document.add_paragraph(f"{_letter(position)}. {choice}")
        document.add_paragraph(f"Answer: {_letter(item['correct_index'])}")
        if item["explanation"]:
            document.add_paragraph(f"Explanation: {item['explanation']}")
        document.add_paragraph("")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


_GENERATORS = {
    "csv": csv_bytes,
    "txt": txt_bytes,
    "xlsx": xlsx_bytes,
    "docx": docx_bytes,
}


def build_template(fmt: str) -> tuple[str, str, bytes]:
    """Return ``(filename, content_type, data)`` for one template format."""
    generator = _GENERATORS.get(fmt)
    if generator is None:
        raise KeyError(fmt)
    return f"quiz-template.{fmt}", CONTENT_TYPES[fmt], generator()


__all__ = ["build_template"]
