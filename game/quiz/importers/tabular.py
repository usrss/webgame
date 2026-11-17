"""CSV and XLSX parsing (Phase 8).

Both formats use the same header row and the same column rules::

    no,question,a,b,c,d,answer,explanation
    1,What is 2 + 2?,3,4,5,6,B,Add the two numbers

``no``, ``d`` and ``explanation`` are optional.  Header names are
case-insensitive and extra columns are ignored.
"""

from __future__ import annotations

import csv
import io

from .base import RawItem, clean_text
from .safety import UploadRejected

REQUIRED_COLUMNS = ("question", "a", "b", "c", "answer")
OPTIONAL_COLUMNS = ("no", "d", "explanation")
HEADER_HINT = (
    "The first row must be a header: no,question,a,b,c,d,answer,explanation "
    "(no, d and explanation are optional)."
)


def _header_error() -> list[str]:
    return [
        f"Row 1: {HEADER_HINT} Download the template to get the exact layout."
    ]


def _index_map(header: list[str]) -> dict[str, int] | None:
    names = [clean_text(name).casefold() for name in header]
    mapping: dict[str, int] = {}
    for column in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS):
        if column in names:
            mapping[column] = names.index(column)
    if any(column not in mapping for column in REQUIRED_COLUMNS):
        return None
    return mapping


def _cell(row: list[str], mapping: dict[str, int], column: str) -> str:
    index = mapping.get(column)
    if index is None or index >= len(row):
        return ""
    return clean_text(row[index])


def _raw_from_cells(row: list[str], mapping: dict[str, int], ref: str) -> RawItem:
    number_text = _cell(row, mapping, "no")
    number = int(number_text) if number_text.isdigit() else None
    # ``d`` is optional: an empty fourth cell means a 3-choice question rather
    # than an empty choice.
    choices = [_cell(row, mapping, name) for name in ("a", "b", "c")]
    fourth = _cell(row, mapping, "d")
    if fourth:
        choices.append(fourth)
    return RawItem(
        prompt=_cell(row, mapping, "question"),
        choices=choices,
        answer=_cell(row, mapping, "answer"),
        explanation=_cell(row, mapping, "explanation"),
        number=number,
        source_ref=ref,
    )


def _row_is_empty(row) -> bool:
    return not any(clean_text(cell) for cell in row)


# ------------------------------------------------------------------------- CSV


def decode_text(data: bytes) -> tuple[str, str]:
    """Decode UTF-8 (with BOM) and fall back to Windows cp1252."""
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        raise UploadRejected(
            "That text file is not readable. Save it as UTF-8 and upload it again."
        )


def parse_csv(data: bytes) -> tuple[list[RawItem], list[str], str]:
    """Parse a CSV upload.  Returns ``(items, errors, encoding_used)``."""
    text, encoding = decode_text(data)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text, newline=""), dialect)
    try:
        rows = [row for row in reader]
    except csv.Error as exc:
        return (
            [],
            [
                f"Row {reader.line_num}: this row could not be read ({exc}). "
                "Check the quoting and save the file again."
            ],
            encoding,
        )
    # Ignore leading blank rows so Excel exports with a spacer still work.
    while rows and _row_is_empty(rows[0]):
        rows.pop(0)
    if not rows:
        return [], ["The file is empty. Add a header row and at least one item."], encoding

    mapping = _index_map(rows[0])
    if mapping is None:
        return [], _header_error(), encoding

    items: list[RawItem] = []
    errors: list[str] = []
    for offset, row in enumerate(rows[1:], start=2):
        if _row_is_empty(row):
            continue
        items.append(_raw_from_cells(row, mapping, f"Row {offset}"))
    return items, errors, encoding


# ------------------------------------------------------------------------ XLSX


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return clean_text(value)


def parse_xlsx(data: bytes) -> tuple[list[RawItem], list[str], str]:
    """Parse the first sheet of an xlsx upload (read-only, values only)."""
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(
            io.BytesIO(data), read_only=True, data_only=True, keep_links=False
        )
    except Exception:
        raise UploadRejected(
            "That workbook could not be opened. Re-save it as .xlsx and try again."
        )

    try:
        sheet = workbook.worksheets[0]
        rows = [
            [_as_text(value) for value in row]
            for row in sheet.iter_rows(values_only=True)
        ]
    except Exception:
        raise UploadRejected(
            "The first sheet could not be read. Re-save the workbook and try again."
        )
    finally:
        workbook.close()

    while rows and _row_is_empty(rows[0]):
        rows.pop(0)
    if not rows:
        return [], ["The workbook is empty. Add a header row and at least one item."], ""

    mapping = _index_map(rows[0])
    if mapping is None:
        return [], _header_error(), ""

    items: list[RawItem] = []
    errors: list[str] = []
    for offset, row in enumerate(rows[1:], start=2):
        if _row_is_empty(row):
            continue
        items.append(_raw_from_cells(row, mapping, f"Row {offset}"))
    return items, errors, ""


__all__ = ["decode_text", "parse_csv", "parse_xlsx"]
