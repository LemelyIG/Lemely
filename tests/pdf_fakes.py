"""Deliberately-malformed and encrypted PDF builders, for scan-geometry tests.

Shared by ``tests/test_scan_limits.py``, ``tests/test_web_teacher.py`` and
``tests/test_student_correct.py`` (mirroring the role ``tests/storage_fakes.py``
plays for :class:`~lemely.io.storage.StorageBackend`): the regression these
back is that a scan whose bytes open but whose page tree does not fully
parse must pass ``lemely.io.scan_limits.check_scan_bytes`` and both upload
routes exactly like a document that fails to open at all -- see spec
2026-09-26 §6 and task-11-report.md's "Fix round 1". Also the Task 11b bomb
builders: small files whose page content or declared image size is far
larger than any scan's -- generated in-test, nothing committed.
"""

from __future__ import annotations

import io
import re
import zlib

import pymupdf


def _hand_rolled_pdf(kids: str, count: int, xref_size: int) -> bytes:
    """A minimal, hand-written PDF whose page tree can be deliberately broken.

    ``pypdfium2``/Pillow can only *write* well-formed documents, so a
    malformed page tree -- one real ``/Type /Page`` object (object 3) plus a
    ``/Pages`` node whose ``kids``/``count`` a caller controls -- has to be
    built as raw bytes. The offsets in the ``xref`` table are computed from
    the actual object positions, so the document opens cleanly; only the
    page tree itself is broken.
    """
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        + f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {count} >>\nendobj\n".encode()
        + b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << >> >>\nendobj\n"
    )
    offsets = {int(m.group(1)): m.start() for m in re.finditer(rb"(\d+) 0 obj", body)}
    xref_lines = [b"0000000000 65535 f \n"]
    for n in range(1, xref_size):
        xref_lines.append(f"{offsets.get(n, 0):010d} 00000 n \n".encode())
    xref = f"xref\n0 {xref_size}\n".encode() + b"".join(xref_lines)
    trailer = (
        f"trailer\n<< /Size {xref_size} /Root 1 0 R >>\nstartxref\n".encode()
        + str(len(body)).encode()
        + b"\n%%EOF"
    )
    return body + xref + trailer


def pdf_with_missing_kid_object() -> bytes:
    """A page tree whose second ``/Kids`` entry (object 4) is never defined.

    Opens fine (``/Count`` says 2 pages); reading page index 1's size fails
    inside pypdfium2 with a ``PdfiumError`` ("Failed to get page size by
    index."), reproduced against the real library before writing tests
    against it.
    """
    return _hand_rolled_pdf(kids="3 0 R 4 0 R", count=2, xref_size=5)


def pdf_with_inflated_count() -> bytes:
    """A page tree whose ``/Count`` (2) overstates its real ``/Kids`` array (1).

    Same failure as :func:`pdf_with_missing_kid_object`, reached a different
    way: reading page index 1's size fails because there is no second kid at
    all, not because a specific object is missing.
    """
    return _hand_rolled_pdf(kids="3 0 R", count=2, xref_size=4)


def encrypted_pdf_bytes() -> bytes:
    """A genuinely password-protected PDF.

    pypdfium2 has no API to *write* an encrypted PDF, but pymupdf (already a
    dependency, used by ``lemely.web.routers.review``) does. Opening this
    without the password fails at ``PdfDocument(data)`` itself (PDFium:
    "Incorrect password"), before ``plan_pdf_pages`` is ever reached.
    """
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    buf = io.BytesIO()
    doc.save(buf, encryption=pymupdf.PDF_ENCRYPT_RC4_128, user_pw="secret")
    doc.close()
    return buf.getvalue()


def assemble_pdf(objects: list[bytes]) -> bytes:
    """A PDF from 1-based numbered object bodies, with a correct xref table.

    Unlike :func:`_hand_rolled_pdf` every object is supplied by the caller,
    so a test can attach arbitrary streams, XObjects and resources.
    """
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def pdf_stream(dict_entries: bytes, data: bytes) -> bytes:
    """A stream object body with ``dict_entries`` plus the correct ``/Length``."""
    return (
        b"<< " + dict_entries + f" /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"
    )


def flate_bomb_ops(inflated_bytes: int) -> bytes:
    """``inflated_bytes`` of path operators, Flate-compressed (~500:1)."""
    op = b"0 0 m 1 1 l S\n"
    return zlib.compress(op * (inflated_bytes // len(op)), 9)


_A4_PAGE = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
_CATALOG_AND_PAGES = [
    b"<< /Type /Catalog /Pages 2 0 R >>",
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
]


def page_bomb_pdf(inflated_bytes: int) -> bytes:
    """One A4 page whose only content stream inflates to ``inflated_bytes``.

    112,000,000 is the reviewer's reproduction: ~218 KB on the wire, and a
    2.2 GB / 4 s parse under pypdfium2.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" >>",
            pdf_stream(b"/Filter /FlateDecode", flate_bomb_ops(inflated_bytes)),
        ]
    )


def xobject_bomb_pdf(inflated_bytes: int) -> bytes:
    """A tiny page stream (``q /Fm1 Do Q``) whose Form XObject carries the bomb
    and references itself again under a second name, so the same xref is
    reachable twice and must be counted once."""
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /XObject << /Fm1 5 0 R >> >> >>",
            pdf_stream(b"", b"q /Fm1 Do Q"),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 595 842] /Filter /FlateDecode "
                b"/Resources << /XObject << /Fm2 5 0 R >> >>",
                flate_bomb_ops(inflated_bytes),
            ),
        ]
    )


def filtered_page_pdf(filter_entry: bytes, data: bytes) -> bytes:
    """One A4 page whose content stream carries ``filter_entry`` verbatim."""
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" >>",
            pdf_stream(filter_entry, data),
        ]
    )


def image_bomb_pdf(width: int, height: int, *, nested: bool = False) -> bytes:
    """A one-pixel Flate image XObject whose dictionary DECLARES ``width x height``.

    The stream is a single grey byte; only the header lies, which is exactly
    what a decoder allocates against. ``nested=True`` draws the image from
    inside a Form XObject instead of the page, so the check must look through
    XObject resources (``page.get_images(full=True)`` does).
    """
    image = pdf_stream(
        f"/Type /XObject /Subtype /Image /Width {width} /Height {height} "
        "/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode".encode(),
        zlib.compress(b"\x00"),
    )
    if not nested:
        return assemble_pdf(
            [
                *_CATALOG_AND_PAGES,
                _A4_PAGE + b" /Resources << /XObject << /Im0 5 0 R >> >> >>",
                pdf_stream(b"", b"q 595 0 0 842 0 0 cm /Im0 Do Q"),
                image,
            ]
        )
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /XObject << /Fm1 5 0 R >> >> >>",
            pdf_stream(b"", b"q /Fm1 Do Q"),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 595 842] "
                b"/Resources << /XObject << /Im0 6 0 R >> >>",
                b"q 595 0 0 842 0 0 cm /Im0 Do Q",
            ),
            image,
        ]
    )


__all__ = [
    "assemble_pdf",
    "encrypted_pdf_bytes",
    "filtered_page_pdf",
    "flate_bomb_ops",
    "image_bomb_pdf",
    "page_bomb_pdf",
    "pdf_stream",
    "pdf_with_inflated_count",
    "pdf_with_missing_kid_object",
    "xobject_bomb_pdf",
]
