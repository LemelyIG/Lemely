"""Tutor evidence file handling (SPEC §a.2 ``tutor_evidence_files``, THREAT-MODEL SC-22, PP-8).

Pure: bytes in, bytes out, no database and no storage. The route tests in
``tests/test_tutor_evidence.py`` cover the HTTP mapping of each refusal.
"""

from __future__ import annotations

import uuid
from io import BytesIO
from urllib.parse import unquote

import pytest
import structlog.testing
from PIL import Image, PngImagePlugin

import lemely.io.evidence_files as evidence_files
from lemely.io.evidence_files import (
    ALLOWED_CONTENT_TYPES,
    MAX_EVIDENCE_BYTES,
    EvidenceTooLargeError,
    UnsupportedEvidenceError,
    attachment_disposition,
    evidence_object_path,
    prepare_evidence,
    sanitise_filename,
    sniff_content_type,
)

PDF_TYPE = "application/pdf"
JPEG_TYPE = "image/jpeg"
PNG_TYPE = "image/png"

PDF = (
    b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
)

_MAKE, _ARTIST, _ORIENTATION = 0x010F, 0x013B, 0x0112


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
def test_sniffed_type_overrides_declared(
    data: bytes, declared: str, sniffed: str, extension: str
) -> None:
    with structlog.testing.capture_logs() as logs:
        prepared = prepare_evidence(data, filename="certificate.pdf", declared_type=declared)

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


def test_matching_declared_type_logs_nothing() -> None:
    with structlog.testing.capture_logs() as logs:
        prepared = prepare_evidence(PDF, filename="a.pdf", declared_type=PDF_TYPE)
    assert prepared.content_type == PDF_TYPE
    assert prepared.data == PDF  # a PDF is stored as uploaded
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
        prepare_evidence(data, filename="x.pdf", declared_type=PDF_TYPE)
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
        prepare_evidence(data, filename="x", declared_type=None)
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

    prepared = prepare_evidence(data, filename="photo.jpg", declared_type=JPEG_TYPE)

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

    stored_jpeg = prepare_evidence(jpeg, filename="a.jpg", declared_type=JPEG_TYPE)
    stored_png = prepare_evidence(png, filename="a.png", declared_type=PNG_TYPE)

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
    prepared = prepare_evidence(jpeg, filename="a.jpg", declared_type=JPEG_TYPE)
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

    prepared = prepare_evidence(data, filename="phone.jpg", declared_type=JPEG_TYPE)

    assert prepared.content_type == JPEG_TYPE
    assert _open(prepared.data).format == "JPEG"


def test_reencode_keeps_png_transparency() -> None:
    """A palette PNG's transparency lives in its info, which the re-encode clears."""
    data = _png(mode="P", transparency=0)
    prepared = prepare_evidence(data, filename="seal.png", declared_type=PNG_TYPE)
    img = _open(prepared.data)
    assert img.mode == "RGBA"
    assert img.getpixel((5, 5))[3] == 0


def test_pdf_is_stored_byte_for_byte() -> None:
    prepared = prepare_evidence(PDF, filename="degree.pdf", declared_type=PDF_TYPE)
    assert prepared.data == PDF
    assert prepared.size_bytes == len(PDF)


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
        prepare_evidence(data, filename="x", declared_type=None)


def test_truncated_image_rejected_415() -> None:
    jpeg = _jpeg(size=(400, 300))
    with pytest.raises(UnsupportedEvidenceError):
        prepare_evidence(jpeg[: len(jpeg) // 2], filename="x.jpg", declared_type=JPEG_TYPE)


# ---------------------------------------------------------------------------
# Size (SPEC §a.2: 1 to 10 MiB; SC-22: 5 files x 10 MiB)
# ---------------------------------------------------------------------------


def test_max_evidence_bytes_is_ten_mib() -> None:
    assert MAX_EVIDENCE_BYTES == 10 * 1024 * 1024 == 10485760


def test_oversize_rejected_413() -> None:
    data = PDF + b"\x00" * (MAX_EVIDENCE_BYTES + 1 - len(PDF))
    assert len(data) == MAX_EVIDENCE_BYTES + 1
    with pytest.raises(EvidenceTooLargeError) as excinfo:
        prepare_evidence(data, filename="big.pdf", declared_type=PDF_TYPE)
    assert excinfo.value.status == 413
    assert excinfo.value.code == "evidence_too_large"


def test_exactly_max_bytes_accepted() -> None:
    data = PDF + b"\x00" * (MAX_EVIDENCE_BYTES - len(PDF))
    assert prepare_evidence(data, filename="big.pdf", declared_type=PDF_TYPE).size_bytes == (
        MAX_EVIDENCE_BYTES
    )


def test_pixel_bomb_rejected_413_before_decoding() -> None:
    """Dimensions over the app's one decode ceiling are refused from the header alone."""
    from lemely.io.scan_limits import MAX_DECODE_PX

    width, height = 8000, 6000
    assert width * height > MAX_DECODE_PX
    data = _png(mode="1", size=(width, height))
    assert len(data) < MAX_EVIDENCE_BYTES
    with pytest.raises(EvidenceTooLargeError):
        prepare_evidence(data, filename="huge.png", declared_type=PNG_TYPE)


def test_reencoded_image_over_the_cap_rejected_413(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stored bytes, not the uploaded ones, must fit the cap (the DB CHECK reads them)."""
    noisy = Image.effect_noise((300, 300), 90).convert("RGB")
    buf = BytesIO()
    noisy.save(buf, "JPEG", quality=20)
    small = buf.getvalue()
    monkeypatch.setattr(evidence_files, "MAX_EVIDENCE_BYTES", len(small))
    with pytest.raises(EvidenceTooLargeError):
        prepare_evidence(small, filename="noise.jpg", declared_type=JPEG_TYPE)


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
    prepared = prepare_evidence(PDF, filename="../a\u202e/cert.exe", declared_type=PDF_TYPE)
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
