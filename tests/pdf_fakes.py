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
        b"<< "
        + dict_entries
        + f" /Length {len(data)} >>\nstream\n".encode()
        + data
        + b"\nendstream"
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


def annot_ap_bomb_pdf(inflated_bytes: int) -> bytes:
    """One annotation whose appearance stream (``/AP`` -> ``/N``) carries the bomb.

    Fix round 1, Important 2(a). An appearance stream is a Form XObject per
    spec, so the walk must find it via ``/Annots``, not just page resources.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Annots [5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Annot /Subtype /Widget /Rect [0 0 10 10] /AP << /N 6 0 R >> >>",
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Filter /FlateDecode",
                flate_bomb_ops(inflated_bytes),
            ),
        ]
    )


def tiling_pattern_bomb_pdf(inflated_bytes: int) -> bytes:
    """A page painted with a tiling pattern whose own stream carries the bomb.

    Fix round 1, Important 2(b).
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /Pattern << /P1 5 0 R >> >> >>",
            pdf_stream(b"", b"/Pattern cs /P1 scn 0 0 595 842 re f"),
            pdf_stream(
                b"/Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 "
                b"/BBox [0 0 10 10] /XStep 10 /YStep 10 /Filter /FlateDecode",
                flate_bomb_ops(inflated_bytes),
            ),
        ]
    )


def type3_charproc_bomb_pdf(inflated_bytes: int) -> bytes:
    """A Type3 font whose one glyph procedure (``/CharProcs``) carries the bomb.

    Fix round 1, Important 2(c).
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /Font << /F1 5 0 R >> >> >>",
            pdf_stream(b"", b"BT /F1 12 Tf (A) Tj ET"),
            b"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 1000 1000] "
            b"/FontMatrix [0.001 0 0 0.001 0 0] /CharProcs << /A 6 0 R >> "
            b"/Encoding << /Type /Encoding /Differences [65 /A] >> "
            b"/FirstChar 65 /LastChar 65 /Widths [1000] >>",
            pdf_stream(b"/Filter /FlateDecode", flate_bomb_ops(inflated_bytes)),
        ]
    )


def smask_bomb_pdf(width: int, height: int) -> bytes:
    """A one-pixel image whose ``/SMask`` declares ``width`` x ``height``.

    Fix round 1, Important 3. Only the mask's own header lies -- its stream
    is one grey byte, same trick as :func:`image_bomb_pdf`.
    """
    smask = pdf_stream(
        f"/Type /XObject /Subtype /Image /Width {width} /Height {height} "
        "/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode".encode(),
        zlib.compress(b"\x00"),
    )
    image = pdf_stream(
        b"/Type /XObject /Subtype /Image /Width 1 /Height 1 "
        b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode /SMask 6 0 R",
        zlib.compress(b"\x00"),
    )
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /XObject << /Im0 5 0 R >> >> >>",
            pdf_stream(b"", b"q 1 0 0 1 0 0 cm /Im0 Do Q"),
            image,
            smask,
        ]
    )


def form_xobject_cycle_pdf() -> bytes:
    """Two Form XObjects that reference each other; the walk must terminate.

    Fix round 1, Important 2(e). An annotation-appearance cycle would
    terminate the same way, through the same ``seen``-by-xref guard, once
    the AP stream is found -- it is handed to the identical Form-XObject
    walker (see :func:`~lemely.io.scan_limits._visit_resource`).
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /XObject << /Fm1 5 0 R >> >> >>",
            pdf_stream(b"", b"q /Fm1 Do Q"),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] "
                b"/Resources << /XObject << /Fm2 6 0 R >> >>",
                b"q /Fm2 Do Q",
            ),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] "
                b"/Resources << /XObject << /Fm1 5 0 R >> >>",
                b"q /Fm1 Do Q",
            ),
        ]
    )


def repeated_xobject_pdf(*, times: int, inflated_bytes: int) -> bytes:
    """A page whose content stream draws the same Form XObject ``times`` times.

    The walk visits ``/Resources`` once, not once per ``Do`` -- a page that
    fits under the cap despite drawing its (cheap) form many times proves
    the dedup is by object, not by draw. Repetition itself still costs real
    render time proportional to ``times``; not solved here, see the module
    docstring's inline-image note and the report's follow-up.
    """
    ops = b"q /Fm1 Do Q\n" * times
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /XObject << /Fm1 5 0 R >> >> >>",
            pdf_stream(b"", ops),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Filter /FlateDecode",
                flate_bomb_ops(inflated_bytes),
            ),
        ]
    )


def indirect_filter_page_pdf(data: bytes) -> bytes:
    """One page whose content stream's ``/Filter`` is an indirect reference
    to a bare name object -- unusual but legal PDF syntax (fix round 1)."""
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" >>",
            pdf_stream(b"/Filter 5 0 R", data),
            b"/FlateDecode",
        ]
    )


def indirect_xobject_dict_bomb_pdf(inflated_bytes: int) -> bytes:
    """A page whose ``/Resources /XObject`` is itself an indirect reference.

    Fix round 2, Important 1: ``/Resources << /XObject 6 0 R >>`` where
    object 6 -- not the page's ``/Resources`` object, the ``/XObject`` name
    map *inside* it -- is its own object (``<< /Fm1 5 0 R >>``). Round 1's
    ``page.get_xobjects()`` resolved this level of indirection for us;
    ``_collection_refs`` alone, called once on ``/Resources``, does not.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /XObject 6 0 R >> >>",
            pdf_stream(b"", b"q /Fm1 Do Q"),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Filter /FlateDecode",
                flate_bomb_ops(inflated_bytes),
            ),
            b"<< /Fm1 5 0 R >>",
        ]
    )


def indirect_ap_state_bomb_pdf(inflated_bytes: int) -> bytes:
    """An annotation whose ``/AP /N`` appearance-state dict is its own object.

    Fix round 2, Important 1: ``/AP << /N 6 0 R >>`` where object 6 is the
    ``/Off``/``/On`` appearance-state dict (``<< /Off 7 0 R /On 8 0 R >>``),
    not the appearance stream directly. Object 8 (``/On``) carries the bomb.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Annots [5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Annot /Subtype /Stamp /Rect [0 0 10 10] /AP << /N 6 0 R >> >>",
            b"<< /Off 7 0 R /On 8 0 R >>",
            pdf_stream(b"/Type /XObject /Subtype /Form /BBox [0 0 10 10]", b"q Q"),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Filter /FlateDecode",
                flate_bomb_ops(inflated_bytes),
            ),
        ]
    )


def extgstate_smask_bomb_pdf(inflated_bytes: int) -> bytes:
    """A page whose graphics state's ``/SMask`` -> ``/G`` transparency-group
    form carries the bomb.

    Fix round 2, minor 1. The soft mask itself (object 6) is a plain
    ``/Type /Mask`` dict, not a stream -- only its ``/G`` (a Form XObject,
    object 7) is content.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /ExtGState << /GS1 5 0 R >> >> >>",
            pdf_stream(b"", b"/GS1 gs q Q"),
            b"<< /Type /ExtGState /SMask 6 0 R >>",
            b"<< /Type /Mask /S /Luminosity /G 7 0 R >>",
            pdf_stream(
                b"/Type /XObject /Subtype /Form /Group 8 0 R /BBox [0 0 10 10] "
                b"/Filter /FlateDecode",
                flate_bomb_ops(inflated_bytes),
            ),
            b"<< /Type /Group /S /Transparency >>",
        ]
    )


def indirect_smask_dimension_bomb_pdf(width: int, height: int) -> bytes:
    """A small image whose ``/SMask``'s ``/Width`` is an indirect reference
    to a bare number object -- unusual but legal PDF syntax (fix round 2,
    Important 2)."""
    smask = pdf_stream(
        f"/Type /XObject /Subtype /Image /Width 7 0 R /Height {height} "
        "/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode".encode(),
        zlib.compress(b"\x00"),
    )
    image = pdf_stream(
        b"/Type /XObject /Subtype /Image /Width 1 /Height 1 "
        b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode /SMask 6 0 R",
        zlib.compress(b"\x00"),
    )
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /XObject << /Im0 5 0 R >> >> >>",
            pdf_stream(b"", b"q 1 0 0 1 0 0 cm /Im0 Do Q"),
            image,
            smask,
            str(width).encode(),
        ]
    )


def many_form_xobjects_pdf(count: int) -> bytes:
    """A page whose ``/Resources``/``/XObject`` dict lists ``count`` distinct,
    otherwise-harmless Form XObjects -- for the per-page object-visit cap."""
    forms = [
        pdf_stream(b"/Type /XObject /Subtype /Form /BBox [0 0 1 1]", b"") for _ in range(count)
    ]
    xobject_dict = " ".join(f"/Fm{i} {5 + i} 0 R" for i in range(count))
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + f" /Resources << /XObject << {xobject_dict} >> >> >>".encode(),
            pdf_stream(b"", b"q Q"),
            *forms,
        ]
    )


__all__ = [
    "annot_ap_bomb_pdf",
    "assemble_pdf",
    "encrypted_pdf_bytes",
    "extgstate_smask_bomb_pdf",
    "filtered_page_pdf",
    "flate_bomb_ops",
    "form_xobject_cycle_pdf",
    "image_bomb_pdf",
    "indirect_ap_state_bomb_pdf",
    "indirect_filter_page_pdf",
    "indirect_smask_dimension_bomb_pdf",
    "indirect_xobject_dict_bomb_pdf",
    "many_form_xobjects_pdf",
    "page_bomb_pdf",
    "pdf_stream",
    "pdf_with_inflated_count",
    "pdf_with_missing_kid_object",
    "repeated_xobject_pdf",
    "smask_bomb_pdf",
    "tiling_pattern_bomb_pdf",
    "type3_charproc_bomb_pdf",
    "xobject_bomb_pdf",
]
