"""Tutor evidence files: what may be stored, and in what form (SPEC §a.2, THREAT-MODEL SC-22).

A tutor uploads qualification documents that only a platform admin ever opens
(O17). The bytes are untrusted, so nothing about them is taken on the client's
word:

* **The type comes from the bytes.** :func:`sniff_content_type` reads the magic
  number at offset 0 (``%PDF-``, the PNG signature, the JPEG SOI marker) and
  that alone decides the stored ``content_type`` and extension. The declared
  multipart type is only compared with it, and a mismatch is logged
  (``evidence_declared_type_mismatch``) without changing anything. A file with
  no allowed signature at offset 0 is refused with 415.
* **Polyglots are refused, not cleaned.** A file that is also another format
  where that format's reader looks for it is refused with 415: an image that
  carries ``%PDF-`` in its first KiB (a PDF reader accepts a header anywhere in
  the first 1024 bytes, so it would open as a PDF), or any file whose first KiB
  carries an HTML, script or SVG start tag (what a content sniffer renders as
  markup). XMP packets (``<?xpacket``, ``<x:xmpmeta``, ``<rdf:RDF``), which
  cameras write near the start of a JPEG, are none of those tags.
* **Images are re-encoded.** A PNG or JPEG is decoded with Pillow and written
  again from its pixels alone, so EXIF (camera, owner, GPS), comments, text
  chunks, XMP and ICC profiles are dropped. The EXIF orientation is applied
  first, so dropping it does not turn the page. Dimensions over
  :data:`~lemely.io.scan_limits.MAX_DECODE_PX` (the app's one decode ceiling)
  are refused from the header, before any pixel is decoded. A PDF is stored
  byte for byte: it is never parsed here, only sniffed, because nothing renders
  it (the admin downloads it as an attachment).
* **Sizes.** Both the upload and the stored bytes must fit
  :data:`MAX_EVIDENCE_BYTES` (10 MiB, the column CHECK), else 413.
* **Filenames are display text, never a path.** :func:`sanitise_filename` keeps
  the last path component, drops control and format characters (bidi overrides
  included), replaces characters a filesystem or a header treats specially,
  forces the sniffed type's extension and fits the 200-character column.
  :func:`attachment_disposition` turns it into a header value that is ASCII
  only, with the full name in RFC 5987 ``filename*``.

Pure apart from logging: bytes in, bytes out. The repository and the routes
decide where the result goes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, ClassVar, Final
from urllib.parse import quote

import structlog
from PIL import Image, ImageOps

from lemely.io.scan_limits import MAX_DECODE_PX, PDF_MAGIC

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

log = structlog.get_logger(__name__)

PDF: Final = "application/pdf"
JPEG: Final = "image/jpeg"
PNG: Final = "image/png"

#: ``ck_tutor_evidence_files_content_type_allowed``.
ALLOWED_CONTENT_TYPES: Final = frozenset({PDF, JPEG, PNG})

#: ``ck_tutor_evidence_files_size_bytes_range``: 1 to 10 MiB (SC-22: 5 files x 10 MiB).
MAX_EVIDENCE_BYTES: Final = 10 * 1024 * 1024

#: ``tutor_evidence_files.original_filename`` is varchar(200).
MAX_FILENAME_LENGTH: Final = 200

#: The stored extension of each type; the first entry of :data:`_SUFFIXES` per type.
EXTENSIONS: Final[Mapping[str, str]] = {PDF: "pdf", JPEG: "jpg", PNG: "png"}

#: Suffixes a client's filename may keep for each type (compared lowercased).
_SUFFIXES: Final[Mapping[str, tuple[str, ...]]] = {
    PDF: ("pdf",),
    JPEG: ("jpg", "jpeg"),
    PNG: ("png",),
}

_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_JPEG_SOI: Final = b"\xff\xd8\xff"
_SIGNATURES: Final[tuple[tuple[bytes, str], ...]] = (
    (PDF_MAGIC, PDF),
    (_PNG_SIGNATURE, PNG),
    (_JPEG_SOI, JPEG),
)
#: The Pillow formats each sniffed type may open as. Many phone cameras write a
#: JPEG with a multi-picture extension, which Pillow reports as MPO; its first
#: frame is the photo, and only that frame is re-encoded.
_PIL_FORMATS: Final[Mapping[str, frozenset[str]]] = {
    PNG: frozenset({"PNG"}),
    JPEG: frozenset({"JPEG", "MPO"}),
}

#: A PDF reader accepts its header anywhere in the first KiB of a file.
_PDF_HEADER_WINDOW: Final = 1024
#: The leading bytes a content sniffer inspects for markup.
_MARKUP_WINDOW: Final = 1024
_MARKUP: Final = re.compile(
    rb"<(?:!doctype\s+html|html|head|body|script|iframe|object|embed|svg)[\s>/]",
    re.IGNORECASE,
)

_JPEG_QUALITY: Final = 90
#: Characters a filesystem or a ``Content-Disposition`` value treats specially.
_RESERVED: Final = frozenset('"<>|:*?\\/')
_FALLBACK_STEM: Final = "evidence"


class EvidenceFileError(Exception):
    """An upload this module refuses; ``status`` and ``code`` are what the route sends."""

    status: ClassVar[int] = 422
    code: ClassVar[str] = "invalid_evidence"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EvidenceTooLargeError(EvidenceFileError):
    """Over 10 MiB, uploaded or stored, or more pixels than the decode ceiling."""

    status: ClassVar[int] = 413
    code: ClassVar[str] = "evidence_too_large"


class UnsupportedEvidenceError(EvidenceFileError):
    """Not a PDF, JPEG or PNG by its bytes, a polyglot, or an image that will not decode."""

    status: ClassVar[int] = 415
    code: ClassVar[str] = "unsupported_evidence_type"


@dataclass(frozen=True, slots=True)
class PreparedEvidence:
    """What is stored for one upload: the bytes, their sniffed type and a display name."""

    data: bytes
    content_type: str
    extension: str
    filename: str

    @property
    def size_bytes(self) -> int:
        """Size of the stored bytes (after any re-encode)."""
        return len(self.data)


def _unsupported() -> UnsupportedEvidenceError:
    return UnsupportedEvidenceError("Upload a PDF, JPEG or PNG file.")


def _too_large() -> EvidenceTooLargeError:
    return EvidenceTooLargeError("Each file can be at most 10 MB.")


def sniff_content_type(data: bytes) -> str:
    """The type whose magic number starts ``data``.

    Raises:
        UnsupportedEvidenceError: no allowed signature at offset 0.
    """
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    raise _unsupported()


def _reject_polyglot(data: bytes, content_type: str) -> None:
    if content_type != PDF and PDF_MAGIC in data[:_PDF_HEADER_WINDOW]:
        raise _unsupported()
    if _MARKUP.search(data[:_MARKUP_WINDOW]) is not None:
        raise _unsupported()


def _pixels_only(img: Image.Image, content_type: str) -> Image.Image:
    """``img`` (oriented) in a mode its format writes, with no metadata left in ``info``.

    Transparency is the one piece of ``info`` that is image content, so an image
    carrying it is converted to an alpha mode first, which keeps it in the pixels.
    """
    ImageOps.exif_transpose(img, in_place=True)
    clean = img
    if content_type == PNG and "transparency" in img.info:
        clean = img.convert("LA" if img.mode in ("1", "L") else "RGBA")
    elif content_type == JPEG and img.mode not in ("L", "RGB"):
        clean = img.convert("RGB")
    # ``save`` falls back to ``info`` for the ICC profile, the JPEG comment, XMP
    # and PNG transparency; an empty ``info`` leaves it nothing to copy. EXIF is
    # written only when passed to ``save``, which it never is here.
    clean.info = {}
    return clean


def _reencode(data: bytes, content_type: str) -> bytes:
    out = BytesIO()
    try:
        with Image.open(BytesIO(data)) as img:
            if img.format not in _PIL_FORMATS[content_type]:
                raise _unsupported()
            width, height = img.size
            if width * height > MAX_DECODE_PX:
                raise _too_large()
            img.load()
            clean = _pixels_only(img, content_type)
            if content_type == JPEG:
                clean.save(out, format="JPEG", quality=_JPEG_QUALITY)
            else:
                clean.save(out, format="PNG")
    except Image.DecompressionBombError as exc:
        raise _too_large() from exc
    except (OSError, ValueError, SyntaxError) as exc:
        raise _unsupported() from exc
    return out.getvalue()


def prepare_evidence(
    data: bytes, *, filename: str | None, declared_type: str | None
) -> PreparedEvidence:
    """Check, sniff and (for images) re-encode one upload.

    ``declared_type`` is the client's multipart content type: logged when it
    disagrees with the sniffed type, never used.

    Raises:
        EvidenceTooLargeError: the upload or the re-encoded image is over
            :data:`MAX_EVIDENCE_BYTES`, or the image has too many pixels.
        UnsupportedEvidenceError: no allowed signature, a polyglot, or an image
            that does not decode.
    """
    if len(data) > MAX_EVIDENCE_BYTES:
        raise _too_large()
    content_type = sniff_content_type(data)
    _reject_polyglot(data, content_type)
    if declared_type is not None and declared_type != content_type:
        log.info("evidence_declared_type_mismatch", declared=declared_type, sniffed=content_type)
    stored = data if content_type == PDF else _reencode(data, content_type)
    if not 1 <= len(stored) <= MAX_EVIDENCE_BYTES:
        raise _too_large()
    return PreparedEvidence(
        data=stored,
        content_type=content_type,
        extension=EXTENSIONS[content_type],
        filename=sanitise_filename(filename, content_type),
    )


def _display_chars(text: str) -> str:
    kept: list[str] = []
    for char in unicodedata.normalize("NFC", text):
        category = unicodedata.category(char)
        if category in ("Cc", "Cf", "Cs", "Co", "Cn"):
            continue  # control, format (bidi overrides, zero-width), surrogate, private, unassigned
        kept.append("_" if char in _RESERVED else (" " if category.startswith("Z") else char))
    return " ".join("".join(kept).split())


def sanitise_filename(filename: str | None, content_type: str) -> str:
    """A display name for an upload: one component, printable, the sniffed extension, <= 200."""
    extension = EXTENSIONS[content_type]
    raw = filename or ""
    base = re.split(r"[\\/]", raw)[-1]
    cleaned = _display_chars(base).strip(" .")
    stem, dot, suffix = cleaned.rpartition(".")
    if dot and suffix.lower() in _SUFFIXES[content_type]:
        stem, extension = stem, suffix.lower()
    elif not dot:
        stem = cleaned
    stem = stem.strip(" .") or _FALLBACK_STEM
    limit = MAX_FILENAME_LENGTH - len(extension) - 1
    return f"{stem[:limit].rstrip(' .') or _FALLBACK_STEM}.{extension}"


def attachment_disposition(filename: str) -> str:
    """``Content-Disposition: attachment`` for ``filename``, safe to put in a header.

    ``filename`` is an ASCII fallback (non-ASCII, quotes, backslashes and
    controls removed); ``filename*`` carries the whole name, percent-encoded
    UTF-8 (RFC 5987/6266), which every current browser prefers.
    """
    stem, dot, suffix = filename.rpartition(".")
    if not dot:
        stem, suffix = filename, ""
    ascii_stem = _ascii(stem) or _FALLBACK_STEM
    ascii_suffix = _ascii(suffix)
    fallback = f"{ascii_stem}.{ascii_suffix}" if ascii_suffix else ascii_stem
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _ascii(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    kept = "".join(
        char
        for char in decomposed
        if char.isascii() and char.isprintable() and char not in _RESERVED
    )
    return " ".join(kept.split()).strip(" .")


def evidence_object_path(
    tutor_profile_id: uuid.UUID, evidence_id: uuid.UUID, content_type: str
) -> str:
    """``tutor-evidence/{tutor_profile_id}/{evidence_id}.{ext}`` (SPEC §a.2): a path, not a URL."""
    return f"tutor-evidence/{tutor_profile_id}/{evidence_id}.{EXTENSIONS[content_type]}"


__all__ = [
    "ALLOWED_CONTENT_TYPES",
    "EXTENSIONS",
    "JPEG",
    "MAX_EVIDENCE_BYTES",
    "MAX_FILENAME_LENGTH",
    "PDF",
    "PNG",
    "EvidenceFileError",
    "EvidenceTooLargeError",
    "PreparedEvidence",
    "UnsupportedEvidenceError",
    "attachment_disposition",
    "evidence_object_path",
    "prepare_evidence",
    "sanitise_filename",
    "sniff_content_type",
]
