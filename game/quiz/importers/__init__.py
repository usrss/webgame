"""Quiz file importers (Phase 8).

``parse_upload(uploaded_file)`` performs every safety check and returns a
:class:`ParseResult`; it never raises for bad question content, only
:class:`UploadRejected` for a file that cannot be used at all.
"""

from __future__ import annotations

from .base import ParseResult, ParsedItem, RawItem, validate_items
from .safety import UploadRejected, format_from_name, read_upload
from .tabular import parse_csv, parse_xlsx
from .text_layout import parse_docx, parse_txt

__all__ = [
    "ParseResult",
    "ParsedItem",
    "RawItem",
    "UploadRejected",
    "parse_bytes",
    "parse_upload",
    "read_upload",
]

_PARSERS = {
    "csv": parse_csv,
    "xlsx": parse_xlsx,
    "txt": parse_txt,
    "docx": parse_docx,
}


def parse_bytes(fmt: str, data: bytes) -> ParseResult:
    """Parse already safety-checked bytes in the given format."""
    parser = _PARSERS.get(fmt)
    if parser is None:
        raise UploadRejected("Unsupported file type.")
    result = ParseResult(format=fmt)
    raws, errors, encoding = parser(data)
    result.errors.extend(errors)
    result.encoding = encoding
    return validate_items(raws, result)


def parse_upload(uploaded_file) -> ParseResult:
    """Check and parse an uploaded file; the bytes are never stored."""
    data, fmt, _filename = read_upload(uploaded_file)
    return parse_bytes(fmt, data)
