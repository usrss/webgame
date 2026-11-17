"""Upload safety checks (Phase 8).

Everything runs on the in-memory bytes: the uploaded file is never written to
disk, to a model field, or to the logs.  These checks run *before* any parser
sees the data.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import PurePosixPath

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException
from django.conf import settings

TEXT_FORMATS = ("csv", "txt")
ZIP_FORMATS = ("xlsx", "docx")
ALLOWED_FORMATS = TEXT_FORMATS + ZIP_FORMATS

FORMAT_LABELS = {
    "csv": "CSV",
    "txt": "Text",
    "xlsx": "Excel workbook",
    "docx": "Word document",
}

# A compression ratio this extreme is not a real workbook: reject it.
_MAX_RATIO = 200
_RATIO_MIN_BYTES = 1_000_000


class UploadRejected(Exception):
    """The file cannot be used at all (wrong type, too big, unsafe archive)."""


def sanitize_filename(name: str) -> str:
    """Return a display-only base name, never a path."""
    base = PurePosixPath((name or "").replace("\\", "/")).name
    base = "".join(character for character in base if character.isprintable())
    return base.strip()[:100]


def format_from_name(filename: str) -> str:
    suffix = PurePosixPath(filename or "").suffix.lower().lstrip(".")
    if suffix == "xlsm":
        raise UploadRejected(
            "Macro-enabled workbooks (.xlsm) can't be used. Save it as .xlsx "
            "first."
        )
    if suffix not in ALLOWED_FORMATS:
        raise UploadRejected(
            "Unsupported file type. Upload a .csv, .xlsx, .txt or .docx file."
        )
    return suffix


def read_upload(uploaded_file) -> tuple[bytes, str, str]:
    """Read and check an ``UploadedFile``; return ``(data, format, filename)``.

    Raises :class:`UploadRejected` with a teacher-friendly message.
    """
    filename = sanitize_filename(getattr(uploaded_file, "name", ""))
    fmt = format_from_name(filename)

    if fmt in TEXT_FORMATS:
        limit = int(settings.GAME_SETTINGS["QUIZ_UPLOAD_MAX_BYTES_TEXT"])
    else:
        limit = int(settings.GAME_SETTINGS["QUIZ_UPLOAD_MAX_BYTES_ZIP"])
    data = uploaded_file.read(limit + 1)
    if len(data) > limit:
        raise UploadRejected(
            f"That file is too big. The limit for {FORMAT_LABELS[fmt]} is "
            f"{limit // 1000} KB."
        )
    if not data:
        raise UploadRejected("That file is empty.")

    if fmt in TEXT_FORMATS:
        check_text_bytes(data)
    else:
        check_zip_bytes(data)

    return data, fmt, filename


def check_text_bytes(data: bytes) -> None:
    """Reject binary-looking CSV/TXT and anything with NUL bytes."""
    if b"\x00" in data:
        raise UploadRejected(
            "That file contains binary data. Save it as plain text/CSV and "
            "upload it again."
        )
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            data.decode(encoding)
            return
        except UnicodeDecodeError:
            continue
    raise UploadRejected(
        "That file is not readable text. Save it as UTF-8 or CSV and try again."
    )


def _unsafe_entry_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized:
        return True
    parts = PurePosixPath(normalized).parts
    return any(part == ".." for part in parts)


def check_zip_bytes(data: bytes) -> None:
    """Guard xlsx/docx: real zip, entry count, size, traversal, safe XML."""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise UploadRejected(
            "That file is not a valid Office document. Download the template "
            "and fill that in instead."
        )

    max_entries = int(settings.GAME_SETTINGS["QUIZ_ZIP_MAX_ENTRIES"])
    max_uncompressed = int(settings.GAME_SETTINGS["QUIZ_ZIP_MAX_UNCOMPRESSED_BYTES"])

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > max_entries:
                raise UploadRejected(
                    "That document has too many internal parts. Use the plain "
                    "template instead."
                )
            total = sum(entry.file_size for entry in entries)
            if total > max_uncompressed:
                raise UploadRejected(
                    "That document unpacks to more than "
                    f"{max_uncompressed // 1_000_000} MB. Use a smaller file."
                )
            for entry in entries:
                if _unsafe_entry_name(entry.filename):
                    raise UploadRejected(
                        "That document contains an unsafe file path and was "
                        "rejected."
                    )
                if entry.filename.lower().endswith("vbaproject.bin"):
                    raise UploadRejected(
                        "That document contains macros, which are not allowed. "
                        "Save it without macros and upload it again."
                    )
                if (
                    entry.file_size > _RATIO_MIN_BYTES
                    and entry.compress_size > 0
                    and entry.file_size > _MAX_RATIO * entry.compress_size
                ):
                    raise UploadRejected(
                        "That document looks like a compressed archive bomb and "
                        "was rejected."
                    )
                if entry.filename.lower().endswith((".xml", ".rels")):
                    _check_xml(archive.read(entry))
    except zipfile.BadZipFile:
        raise UploadRejected(
            "That document is damaged. Re-save it and upload it again."
        )


def _check_xml(data: bytes) -> None:
    """Parse every XML part with defusedxml: DTDs/entities are refused."""
    try:
        SafeElementTree.fromstring(data)
    except DefusedXmlException:
        raise UploadRejected(
            "That document contains unsafe XML (external entities) and was "
            "rejected."
        )
    except Exception:
        raise UploadRejected(
            "That document contains broken XML. Re-save it and upload it again."
        )


__all__ = [
    "ALLOWED_FORMATS",
    "FORMAT_LABELS",
    "UploadRejected",
    "check_text_bytes",
    "check_zip_bytes",
    "format_from_name",
    "read_upload",
    "sanitize_filename",
]
