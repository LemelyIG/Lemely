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
  first, so dropping it does not turn the page. An image over its pixel cap is
  refused from the header, before any pixel is decoded: the lower of
  :data:`MAX_EVIDENCE_PX` and the scan path's per-mode ceiling
  (:func:`~lemely.io.scan_limits.decode_pixel_cap`, T10 review R2).
* **PDFs are checked as scans are and stored flat** (T10 review R1, T30 F30-3).
  The admin downloads the stored file as an attachment and opens it in a local
  reader, which honours every action it finds: a button that submits the form
  or imports data, a link to a phishing URL, a ``/GoToR`` to a UNC path (an
  NTLM hash leak on Windows). So nothing interactive is stored:

  1. :func:`~lemely.io.scan_limits.canonical_pdf_bytes` runs the bounded
     pre-scan and content check, then writes MuPDF's pages-only rewrite: the
     catalog (``/OpenAction``, ``/Names`` with document JavaScript and embedded
     files, outlines), page actions and links are not carried over.
     Annotations and form widgets are, with what they hold.
  2. A rewrite that names an additional action (``/AA``), a script (``/JS``,
     ``/JavaScript``), a program launch (``/Launch``), an attached file
     (``/EF``, ``/EmbeddedFile``) or an XFA form (``/XFA``) is refused with
     415: a file built to run something is not cleaned and kept.
  3. Everything else interactive is flattened away (:func:`_flatten_pdf`):
     MuPDF draws each annotation's and widget's appearance into its page and
     removes it and the form, then any annotation it could not draw and every
     page's ``/AA`` are deleted and the catalog keeps only its page tree and
     optional-content configuration. Pages read and render as uploaded; a
     link's text stays, the link does not.
  4. The flattened bytes, which are what is stored, are scanned again
     (:data:`_INTERACTIVE`): any annotation list, form, widget, open or
     additional action, URI, name tree, outline or action dictionary left is
     refused with 415, an action's type named in it (``/S /ImportData``) or
     referenced (``/S 9 0 R``, object 9 the name), wherever it hangs (a
     layer's dictionary in the kept ``/OCProperties`` included).
* **Sizes.** Both the upload and the stored bytes must fit
  :data:`MAX_EVIDENCE_BYTES` (10 MiB, the column CHECK), else 413.
* **Filenames are display text, never a path.** :func:`sanitise_filename` keeps
  the last path component, drops control and format characters (bidi overrides
  included), replaces characters a filesystem or a header treats specially,
  forces the sniffed type's extension and fits the 200-character column.
  :func:`attachment_disposition` turns it into a header value that is ASCII
  only, with the full name in RFC 5987 ``filename*``.
* **The decode and the PDF work run in a worker** (T10 review R2).
  :func:`prepare_evidence` is pure (bytes in, bytes out, no logging) and is the
  target :func:`prepare_evidence_in_worker` runs in
  :data:`~lemely.runtime.sandbox.EXTRACTION_WORKER`, the memory-limited child
  the scan upload check uses (``SCAN_CHECK_TARGET`` in
  :mod:`lemely.web.upload_utils`): one call at a time, killed past its timeout,
  so a hostile file costs the child, not the web process. The re-encode holds
  up to three copies of an image (the decode, the EXIF turn, a mode change),
  which is why :data:`MAX_EVIDENCE_PX` sits below the scan ceilings.

The repository and the routes decide where the result goes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, ClassVar, Final
from urllib.parse import quote

import pymupdf.mupdf as _mupdf
import structlog
from PIL import Image, ImageOps

from lemely.io.scan_limits import (
    MAX_SCAN_PAGES,
    PDF_MAGIC,
    ScanRejectedError,
    ScanTooLargeError,
    canonical_pdf_bytes,
    decode_pixel_cap,
    open_checked_pdf,
)
from lemely.runtime import sandbox
from lemely.runtime.errors import LemelyError

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

    import pymupdf

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

#: The most pixels an evidence image may have (T10 review R2). Below the scan
#: ceilings (:data:`~lemely.io.scan_limits.MAX_DECODE_PX`, 40 Mpx colour), because
#: the re-encode holds more than one full copy of the image where the scan
#: upload check decodes none. Measured 2026-10-26 (Pillow 12.2, one process per
#: file): a 6000 x 4000 RGB, CMYK or RGBA image with EXIF orientation 6 grows the
#: process by 185 MiB (VmHWM 263 MiB from a 78 MiB baseline), inside the
#: extraction worker's 640 MiB; at the old flat 40 Mpx it is about 310 MiB. It
#: admits a phone camera's usual output (12 to 24 Mpx) and an A4 page at 500 dpi.
MAX_EVIDENCE_PX: Final = 24_000_000

#: The worker's name for :func:`prepare_evidence`. Read at each call, so a test
#: can point it at a stand-in target.
EVIDENCE_PREPARE_TARGET = "lemely.io.evidence_files.prepare_evidence"

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

#: Names are matched whole: the next character must end a PDF name (whitespace or
#: a delimiter), so ``/AAAAAA+Arial``, a subset font's name, is not ``/AA``.
_NAME_END: Final = r"(?![^\s()<>\[\]{}/%])"

#: Names that, in a dictionary of the pages-only rewrite, mean the file was built
#: to run or carry something: refused before anything is flattened (module
#: docstring, step 2).
_ACTIVE_CONTENT: Final = re.compile(rf"/(?:AA|JS|JavaScript|Launch|EF|EmbeddedFile|XFA){_NAME_END}")

#: ISO 32000-2 Table 201: every action type. An action dictionary must name its
#: type as ``/S``, so a reader acts on no dictionary without one of these.
_ACTION_TYPES: Final = (
    "GoTo",
    "GoToR",
    "GoToE",
    "GoToDp",
    "Launch",
    "Thread",
    "URI",
    "Sound",
    "Movie",
    "Hide",
    "Named",
    "SubmitForm",
    "ResetForm",
    "ImportData",
    "SetOCGState",
    "Rendition",
    "Trans",
    "GoTo3DView",
    "JavaScript",
    "RichMediaExecute",
)

#: What may not be left anywhere in the stored (flattened) PDF (module docstring,
#: step 4): the names of :data:`_ACTIVE_CONTENT`; an open action, a form, a page's
#: annotation list, a widget, a URI, a name tree, an outline, rich media; and any
#: action dictionary, by its ``/S``. ``/A``, the key that holds an annotation's
#: or an outline item's action, is not matched as a name: glyph and resource
#: names (``/Differences``, a Type 3 font's ``/CharProcs``, ``/Font << /A ...``)
#: use it too, and the dictionary it holds is matched by its ``/S`` instead.
#:
#: The ``/S`` may also be a reference (``/S 9 0 R``, object 9 the name
#: ``/ImportData``), which a reader resolves: so an object that is nothing but an
#: action type's name is refused wherever it hangs (the last alternative, matched
#: against one object as printed). Wave 8 review finding 4: ``/OCProperties`` is
#: kept so that a layer hidden by default stays hidden, and with it every key of
#: each layer's dictionary, which is how such an action reached the stored file.
_INTERACTIVE: Final = re.compile(
    r"/(?:AA|JS|JavaScript|Launch|EF|EmbeddedFile|XFA|OpenAction|AcroForm|Annots|Widget|URI"
    rf"|Names|Outlines|RichMedia){_NAME_END}"
    rf"|/S\s*/(?:{'|'.join(_ACTION_TYPES)}){_NAME_END}"
    rf"|\A\s*/(?:{'|'.join(_ACTION_TYPES)})\s*\Z"
)

#: The catalog entries a flattened PDF keeps: its page tree, and the
#: optional-content configuration the rewrite carries so that a layer hidden by
#: default stays hidden (:func:`~lemely.io.scan_limits.canonical_pdf_bytes`).
_CATALOG_KEPT: Final = frozenset({"Type", "Pages", "OCProperties"})

_JPEG_QUALITY: Final = 90
#: Characters a filesystem or a ``Content-Disposition`` value treats specially.
_RESERVED: Final = frozenset('"<>|:*?\\/')
_FALLBACK_STEM: Final = "evidence"


class EvidenceFileError(LemelyError):
    """An upload this module refuses; ``status`` and ``code`` are what the route sends.

    A :class:`~lemely.runtime.errors.LemelyError`, so a refusal raised in the
    worker crosses the pipe intact; it pickles from its ``args`` (the message).
    """

    status: ClassVar[int] = 422
    code: ClassVar[str] = "invalid_evidence"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EvidenceTooLargeError(EvidenceFileError):
    """Over 10 MiB, uploaded or stored; more pixels than the cap; a PDF past the size bounds."""

    status: ClassVar[int] = 413
    code: ClassVar[str] = "evidence_too_large"


class UnsupportedEvidenceError(EvidenceFileError):
    """Not a PDF, JPEG or PNG by its bytes, a polyglot, undecodable, or a PDF that acts."""

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


def _too_many_pixels() -> EvidenceTooLargeError:
    return EvidenceTooLargeError("This image is too large to process. Save it smaller and retry.")


def _pdf_too_large() -> EvidenceTooLargeError:
    return EvidenceTooLargeError(
        f"This PDF is too large to check. Upload one of at most {MAX_SCAN_PAGES} pages."
    )


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
            # Both caps are read per call, so a test can patch MAX_EVIDENCE_PX.
            if width * height > min(MAX_EVIDENCE_PX, decode_pixel_cap(img.mode, img.format)):
                raise _too_many_pixels()
            img.load()
            clean = _pixels_only(img, content_type)
            if content_type == JPEG:
                clean.save(out, format="JPEG", quality=_JPEG_QUALITY)
            else:
                clean.save(out, format="PNG")
    except Image.DecompressionBombError as exc:
        raise _too_many_pixels() from exc
    except (OSError, ValueError, SyntaxError) as exc:
        raise _unsupported() from exc
    return out.getvalue()


def _pages_only(data: bytes) -> bytes:
    """The PDF ``data`` as MuPDF's pages-only rewrite, after the scan checks bounded it.

    :func:`~lemely.io.scan_limits.canonical_pdf_bytes` runs the raw object-stream
    pre-scan and the whole-document content check (page cap, content and object
    bounds, optional-content bounds) on ``data`` before it copies anything, so
    nothing it refuses is ever parsed further: a size or complexity refusal is
    413, anything else it cannot check (garbage behind ``%PDF-``, a password, no
    pages) is 415.
    """
    try:
        return canonical_pdf_bytes(data)
    except ScanTooLargeError as exc:
        raise _pdf_too_large() from exc
    except (ScanRejectedError, ValueError) as exc:
        raise _unsupported() from exc


def _refuse_names(doc: pymupdf.Document, names: re.Pattern[str]) -> None:
    """415 when an object of ``doc`` matches ``names``.

    Each object's dictionary is read as MuPDF prints it: names decoded (``/J#53``
    is ``/JS``) and stream data left out, so an image's bytes cannot match by
    chance.
    """
    for xref in range(1, int(doc.xref_length())):  # type: ignore[no-untyped-call]
        printed: str = doc.xref_object(xref, compressed=True)  # type: ignore[no-untyped-call]
        if names.search(printed):
            raise _unsupported()


def _strip_interactive(doc: pymupdf.Document) -> None:
    """Draw ``doc``'s annotations and widgets into their pages and remove what could act.

    MuPDF's bake appends each annotation's and widget's appearance to its page's
    content and removes the annotation, and the form (``/AcroForm``) once its
    widgets are gone. An annotation it has no appearance for (a ``/Screen`` or
    ``/RichMedia`` one) stays, so every page's ``/Annots`` and ``/AA`` are deleted
    after it, and every catalog entry but :data:`_CATALOG_KEPT`.
    """
    doc.bake(annots=True, widgets=True)
    document = _mupdf.pdf_document_from_fz_document(doc.this)  # type: ignore[no-untyped-call]
    for index in range(int(doc.page_count)):
        page = _mupdf.pdf_lookup_page_obj(document, index)  # type: ignore[no-untyped-call]
        for key in ("Annots", "AA"):
            _mupdf.pdf_dict_dels(page, key)  # type: ignore[no-untyped-call]
    catalog = _mupdf.pdf_dict_gets(_mupdf.pdf_trailer(document), "Root")  # type: ignore[no-untyped-call]
    for entry in reversed(range(int(_mupdf.pdf_dict_len(catalog)))):  # type: ignore[no-untyped-call]
        key = _mupdf.pdf_to_name(_mupdf.pdf_dict_get_key(catalog, entry))  # type: ignore[no-untyped-call]
        if key not in _CATALOG_KEPT:
            _mupdf.pdf_dict_dels(catalog, key)  # type: ignore[no-untyped-call]


def _flatten_pdf(pdf: bytes) -> bytes:
    """The pages-only rewrite ``pdf`` with nothing interactive left: what is stored.

    Module docstring, steps 2 and 3: :data:`_ACTIVE_CONTENT` is refused first,
    then :func:`_strip_interactive` runs and the result is written with
    ``garbage=1``, so the removed dictionaries, and the actions they held, are
    not in the file. A file MuPDF cannot reopen, bake or write is refused too.
    """
    try:
        doc = open_checked_pdf(pdf)
    except Exception as exc:
        raise _unsupported() from exc
    try:
        _refuse_names(doc, _ACTIVE_CONTENT)
        _strip_interactive(doc)
        flat: bytes = doc.tobytes(garbage=1)  # type: ignore[no-untyped-call]
    except EvidenceFileError:
        raise
    except Exception as exc:
        raise _unsupported() from exc
    finally:
        doc.close()  # type: ignore[no-untyped-call]
    return flat


def _refuse_interactive(pdf: bytes) -> None:
    """415 when the stored PDF ``pdf`` still holds anything a reader acts on (:data:`_INTERACTIVE`).

    The last check before storing (module docstring, step 4), on the bytes as
    they will be stored. A file MuPDF cannot reopen is refused too.
    """
    try:
        doc = open_checked_pdf(pdf)
    except Exception as exc:
        raise _unsupported() from exc
    try:
        _refuse_names(doc, _INTERACTIVE)
    except EvidenceFileError:
        raise
    except Exception as exc:
        raise _unsupported() from exc
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def _check_stored_size(stored: bytes) -> None:
    if not 1 <= len(stored) <= MAX_EVIDENCE_BYTES:
        raise _too_large()


def _stored_pdf(data: bytes) -> bytes:
    """What is stored for the PDF upload ``data``: rewritten, flattened, checked again.

    The size is checked on the rewrite, which the flatten opens, and on the
    flattened file, which is stored.
    """
    rewrite = _pages_only(data)
    _check_stored_size(rewrite)
    flat = _flatten_pdf(rewrite)
    _check_stored_size(flat)
    _refuse_interactive(flat)
    return flat


def prepare_evidence(data: bytes, filename: str | None) -> PreparedEvidence:
    """Check, sniff and rewrite one upload: the worker's target (:data:`EVIDENCE_PREPARE_TARGET`).

    Pure and positional, as a sandbox target must be; it logs nothing, because the
    worker's log lines would not reach the app's. :func:`prepare_evidence_in_worker`
    is how the web process calls it.

    Raises:
        EvidenceTooLargeError: the upload, a PDF's rewrite or the stored bytes are
            over :data:`MAX_EVIDENCE_BYTES`, an image has more pixels than its cap,
            or a PDF is past the scan check's size bounds.
        UnsupportedEvidenceError: no allowed signature, a polyglot, an image that
            does not decode, a PDF that cannot be checked, rewritten or flattened,
            a PDF that names a script, a program launch, an attached file or an
            additional action, or a flattened PDF that still holds anything a
            reader acts on.
    """
    if len(data) > MAX_EVIDENCE_BYTES:
        raise _too_large()
    content_type = sniff_content_type(data)
    _reject_polyglot(data, content_type)
    if content_type == PDF:
        stored = _stored_pdf(data)
    else:
        stored = _reencode(data, content_type)
        _check_stored_size(stored)
    return PreparedEvidence(
        data=stored,
        content_type=content_type,
        extension=EXTENSIONS[content_type],
        filename=sanitise_filename(filename, content_type),
    )


def prepare_evidence_in_worker(
    data: bytes, *, filename: str | None, declared_type: str | None, timeout: float
) -> PreparedEvidence:
    """:func:`prepare_evidence` run in :data:`~lemely.runtime.sandbox.EXTRACTION_WORKER`.

    Blocks for up to ``timeout`` seconds, counting any wait for the worker (one
    call at a time: a scan extraction, an upload check or another evidence file
    may hold it); call it off the event loop. An upload over
    :data:`MAX_EVIDENCE_BYTES` is refused here, before it crosses the pipe.
    ``declared_type`` (the client's multipart type) is compared with the sniffed
    type here, in the web process, and a mismatch is logged
    (``evidence_declared_type_mismatch``); it is never used.

    Raises the worker's :class:`EvidenceFileError` as it was raised, or a
    :class:`~lemely.runtime.sandbox.SandboxFailure`. With the sandbox disabled
    the target runs in this process and its exceptions propagate unchanged.
    """
    if len(data) > MAX_EVIDENCE_BYTES:
        raise _too_large()
    prepared = sandbox.EXTRACTION_WORKER.call(
        EVIDENCE_PREPARE_TARGET,
        data,
        filename,
        timeout=timeout,
        result_type=PreparedEvidence,
    )
    if declared_type is not None and declared_type != prepared.content_type:
        log.info(
            "evidence_declared_type_mismatch",
            declared=declared_type,
            sniffed=prepared.content_type,
        )
    return prepared


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
    "EVIDENCE_PREPARE_TARGET",
    "EXTENSIONS",
    "JPEG",
    "MAX_EVIDENCE_BYTES",
    "MAX_EVIDENCE_PX",
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
    "prepare_evidence_in_worker",
    "sanitise_filename",
    "sniff_content_type",
]
