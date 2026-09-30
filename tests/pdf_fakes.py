"""Deliberately-malformed and encrypted PDF builders, for scan-geometry tests.

Shared by ``tests/test_scan_limits.py``, ``tests/test_web_teacher.py`` and
``tests/test_student_correct.py`` (mirroring the role ``tests/storage_fakes.py``
plays for :class:`~lemely.io.storage.StorageBackend`): the regression these
back is that a scan whose bytes open but whose page tree does not fully
parse must pass ``lemely.io.scan_limits.check_scan_bytes`` and both upload
routes exactly like a document that fails to open at all -- see spec
2026-09-26 §6 and task-11-report.md's "Fix round 1". Also the Task 11b bomb
builders: small files whose page content or declared image size is far
larger than any scan's -- generated in-test, nothing committed. And (#256)
two raster-image builders, :func:`declared_image` and :func:`bilevel_png`,
for the per-mode image ceiling, used by the rasterise and crop-route tests.
"""

from __future__ import annotations

import io
import random
import re
import struct
import zlib

import pymupdf
from PIL import Image


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


def tiling_pattern_bomb_pdf(inflated_bytes: int, *, type_name: str = "Pattern") -> bytes:
    """A page painted with a tiling pattern whose own stream carries the bomb.

    Fix round 1, Important 2(b). ``type_name`` is the pattern's ``/Type``:
    a renderer finds a pattern by its ``/PatternType`` and ignores ``/Type``,
    so a pattern that calls itself ``/Font`` is drawn all the same.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /Pattern << /P1 5 0 R >> >> >>",
            pdf_stream(b"", b"/Pattern cs /P1 scn 0 0 595 842 re f"),
            pdf_stream(
                f"/Type /{type_name} /PatternType 1 /PaintType 1 /TilingType 1 ".encode()
                + b"/BBox [0 0 10 10] /XStep 10 /YStep 10 /Filter /FlateDecode",
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


def indirect_xobject_dict_bomb_pdf(
    inflated_bytes: int, *, name: str = "Fm1", map_entries: bytes = b""
) -> bytes:
    """A page whose ``/Resources /XObject`` is itself an indirect reference.

    Fix round 2, Important 1: ``/Resources << /XObject 6 0 R >>`` where
    object 6 -- not the page's ``/Resources`` object, the ``/XObject`` name
    map *inside* it -- is its own object (``<< /Fm1 5 0 R >>``). Round 1's
    ``page.get_xobjects()`` resolved this level of indirection for us;
    ``_collection_refs`` alone, called once on ``/Resources``, does not.

    ``name`` is the author-chosen resource name the form is
    filed (and drawn) under -- ``/P``, ``/Contents``, ``/Parent`` and the
    rest are all legal names, so a walk that skips keys by name misses the
    form. ``map_entries`` is written into the name map verbatim (e.g. a
    ``/Type /Font`` label the renderer ignores).
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /XObject 6 0 R >> >>",
            pdf_stream(b"", f"q /{name} Do Q".encode()),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Filter /FlateDecode",
                flate_bomb_ops(inflated_bytes),
            ),
            b"<< " + map_entries + f" /{name} 5 0 R >>".encode(),
        ]
    )


def indirect_ap_state_bomb_pdf(inflated_bytes: int, *, state: str = "On") -> bytes:
    """An annotation whose ``/AP /N`` appearance-state dict is its own object.

    Fix round 2, Important 1: ``/AP << /N 6 0 R >>`` where object 6 is the
    ``/Off``/``/On`` appearance-state dict (``<< /Off 7 0 R /On 8 0 R >>``),
    not the appearance stream directly. Object 8 carries the bomb and is the
    selected state (``/AS``). ``state`` is that state's
    author-chosen name -- ``/Contents`` is as legal as ``/On``.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Annots [5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Annot /Subtype /Stamp /Rect [0 0 10 10] /AP << /N 6 0 R >> "
            + f"/AS /{state} >>".encode(),
            f"<< /Off 7 0 R /{state} 8 0 R >>".encode(),
            pdf_stream(b"/Type /XObject /Subtype /Form /BBox [0 0 10 10]", b"q Q"),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Filter /FlateDecode",
                flate_bomb_ops(inflated_bytes),
            ),
        ]
    )


def extgstate_smask_bomb_pdf(
    inflated_bytes: int, *, gs_type: str = "ExtGState", also_as_font: bool = False
) -> bytes:
    """A page whose graphics state's ``/SMask`` -> ``/G`` transparency-group
    form carries the bomb.

    Fix round 2, minor 1. The soft mask itself (object 6) is a plain
    ``/Type /Mask`` dict, not a stream -- only its ``/G`` (a Form XObject,
    object 7) is content.

    ``gs_type`` is the graphics state's ``/Type``, which a
    renderer ignores (``/Font`` is drawn the same as ``/ExtGState``);
    ``also_as_font`` files the same object under ``/Font`` too, so a walk
    that visits an object once, in whichever role it meets first, can meet
    it as a font and never as the graphics state it also is.
    """
    font_map = b" /Font << /F1 5 0 R >>" if also_as_font else b""
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /ExtGState << /GS1 5 0 R >>" + font_map + b" >> >>",
            pdf_stream(b"", b"/GS1 gs q Q"),
            f"<< /Type /{gs_type} /SMask 6 0 R >>".encode(),
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


def deep_plain_dict_chain_bomb_pdf(*, depth: int, inflated_bytes: int) -> bytes:
    """A page's ``/Resources /XObject`` starts a chain of ``depth`` indirect
    plain dicts (``<< /Next N 0 R >>``), the last one naming the Form
    XObject bomb.

    Fix round 3, Important 1. Round 2's fallback in ``_visit_resource``
    recursed into each next-level plain dict via a direct Python call;
    above roughly 1,000 levels (well below ``depth=2000``) that exceeded
    ``sys.getrecursionlimit()`` before the bomb was ever reached, and the
    resulting ``RecursionError`` used to be swallowed by
    ``check_pdf_content_bytes``'s ``except Exception: return``, letting the
    file -- and its bomb -- through silently.
    """
    chain_start = 5  # 1 catalog, 2 pages, 3 page, 4 content stream
    bomb_obj = chain_start + depth
    objects = [
        *_CATALOG_AND_PAGES,
        _A4_PAGE + f" /Resources << /XObject {chain_start} 0 R >> >>".encode(),
        pdf_stream(b"", b"q Q"),
    ]
    for i in range(depth):
        objects.append(f"<< /Next {chain_start + i + 1} 0 R >>".encode())
    objects.append(
        pdf_stream(
            b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Filter /FlateDecode",
            flate_bomb_ops(inflated_bytes),
        )
    )
    assert len(objects) == bomb_obj  # sanity: object numbering lines up
    return assemble_pdf(objects)


def deep_xobject_chain_bomb_pdf(*, depth: int, inflated_bytes: int) -> bytes:
    """A chain of ``depth`` nested, otherwise-harmless Form XObjects, each
    naming the next in its own ``/Resources``, the last one naming the bomb.

    Fix round 3, Important 1. Distinct from
    :func:`deep_plain_dict_chain_bomb_pdf`: every intermediate object here
    IS a legitimate Form XObject, so the depth comes from ordinary form
    nesting, not from generic containers -- a recursive walk would hit
    Python's recursion limit on this path too.
    """
    chain_start = 5
    bomb_obj = chain_start + depth
    objects = [
        *_CATALOG_AND_PAGES,
        _A4_PAGE + f" /Resources << /XObject << /Fm0 {chain_start} 0 R >> >> >>".encode(),
        pdf_stream(b"", b"q /Fm0 Do Q"),
    ]
    for i in range(depth):
        next_obj = chain_start + i + 1
        objects.append(
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] "
                + f"/Resources << /XObject << /Fm1 {next_obj} 0 R >> >>".encode(),
                b"q /Fm1 Do Q",
            )
        )
    objects.append(
        pdf_stream(
            b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Filter /FlateDecode",
            flate_bomb_ops(inflated_bytes),
        )
    )
    assert len(objects) == bomb_obj
    return assemble_pdf(objects)


def resources_entry_pointing_at_pages_node_pdf() -> bytes:
    """A 3-page PDF whose page 0 ``/Resources`` has an entry pointing
    directly at the shared ``/Pages`` node (object 2).

    Fix round 3, Important 2. Not a legitimate resource -- exactly the
    shape the round-2 fallback's blind, key-blind object-text scan would
    have followed straight into the page tree, from there visiting every
    other page's own dict and content along with it. A normal multi-page
    file with this back-pointer must still pass, and the walk starting
    from page 0 must not count page 1's or page 2's own objects.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 5 0 R 6 0 R] /Count 3 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Contents 4 0 R /Resources << /Poison 2 0 R >> >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 7 0 R >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 8 0 R >>",
            pdf_stream(b"", b"q Q"),
            pdf_stream(b"", b"q Q"),
        ]
    )


def real_smask_dimension_bomb_pdf(width: float, height: int) -> bytes:
    """A small image whose ``/SMask``'s ``/Width`` is written as a PDF
    *real* number (``40000.0``), not an integer -- legal PDF syntax.

    Fix round 3, minor: ``_resolve_int`` used to accept only ``kind ==
    "int"``, so a real-number declared width/height silently passed.
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


def typed_form_xobject_bomb_pdf(inflated_bytes: int, *, type_name: str) -> bytes:
    """A page drawing one Form XObject bomb whose ``/Type`` is ``type_name``.

    A renderer draws an XObject by its ``/Subtype``
    and ignores ``/Type``, so a ``/Subtype /Form`` stream calling itself
    ``/Page``, ``/Pages`` or ``/Catalog`` is drawn like any other form.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /XObject << /Fm1 5 0 R >> >> >>",
            pdf_stream(b"", b"q /Fm1 Do Q"),
            pdf_stream(
                f"/Type /{type_name} /Subtype /Form /BBox [0 0 10 10] ".encode()
                + b"/Filter /FlateDecode",
                flate_bomb_ops(inflated_bytes),
            ),
        ]
    )


def _declared_image(width: int, height: int) -> bytes:
    """A one-grey-pixel Flate image whose dictionary DECLARES ``width x height``."""
    return pdf_stream(
        f"/Type /XObject /Subtype /Image /Width {width} /Height {height} "
        "/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode".encode(),
        zlib.compress(b"\x00"),
    )


def annot_ap_image_bomb_pdf(width: int, height: int) -> bytes:
    """An annotation appearance form that draws an image DECLARING ``width x height``.

    ``page.get_images(full=True)`` lists images
    in the page's resources and its Form XObjects', not those inside an
    annotation's appearance stream -- which the renderer draws all the same.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Annots [5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Annot /Subtype /Stamp /Rect [0 0 10 10] /AP << /N 6 0 R >> >>",
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] "
                b"/Resources << /XObject << /Im0 7 0 R >> >>",
                b"q 10 0 0 10 0 0 cm /Im0 Do Q",
            ),
            _declared_image(width, height),
        ]
    )


def tiling_pattern_image_bomb_pdf(width: int, height: int) -> bytes:
    """A tiling pattern whose cell draws an image DECLARING ``width x height``.

    As :func:`annot_ap_image_bomb_pdf`, but the
    image sits in a tiling pattern's own ``/Resources``, which
    ``page.get_images(full=True)`` does not list either.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /Pattern << /P1 5 0 R >> >> >>",
            pdf_stream(b"", b"/Pattern cs /P1 scn 0 0 595 842 re f"),
            pdf_stream(
                b"/Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 "
                b"/BBox [0 0 10 10] /XStep 10 /YStep 10 "
                b"/Resources << /XObject << /Im0 6 0 R >> >>",
                b"q 10 0 0 10 0 0 cm /Im0 Do Q",
            ),
            _declared_image(width, height),
        ]
    )


def inherited_resources_bomb_pdf(inflated_bytes: int) -> bytes:
    """A page with no ``/Resources`` of its own, drawing a Form XObject bomb
    filed in its ``/Pages`` parent's ``/Resources``.

    ``/Resources`` is inheritable (ISO 32000-1 Table 30) and
    both renderers resolve it from the nearest ancestor; common producers
    write shared resources on the ``/Pages`` node.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 /Resources << /XObject << /Fm1 5 0 R >> >> >>",
            _A4_PAGE + b" >>",
            pdf_stream(b"", b"q /Fm1 Do Q"),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Filter /FlateDecode",
                flate_bomb_ops(inflated_bytes),
            ),
        ]
    )


def page_tree_poison_pdf(
    *, form_bytes: int, poison: bytes = b"/Cat 1 0 R /Root 2 0 R /Sib 5 0 R"
) -> bytes:
    """A 3-page PDF whose page 0 ``/XObject`` map (an indirect object) also
    carries the ``poison`` entries -- by default the catalog (1), a
    ``/Type``-less ``/Pages`` root (2) and a ``/Type``-less sibling page (5).

    Every page draws its own ``form_bytes`` Form XObject (page 0's is 12,
    the siblings' 10 and 11). Neither the root nor the sibling carries a
    ``/Type`` a walk could key on: only object identity identifies them.
    """
    form = b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Filter /FlateDecode"
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Kids [3 0 R 5 0 R 6 0 R] /Count 3 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /XObject 9 0 R >> >>",
            pdf_stream(b"", b"q /Fm1 Do Q"),
            b"<< /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 7 0 R "
            b"/Resources << /XObject << /Fm1 10 0 R >> >> >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 8 0 R "
            b"/Resources << /XObject << /Fm1 11 0 R >> >> >>",
            pdf_stream(b"", b"q /Fm1 Do Q"),
            pdf_stream(b"", b"q /Fm1 Do Q"),
            b"<< /Fm1 12 0 R " + poison + b" >>",
            pdf_stream(form, flate_bomb_ops(form_bytes)),
            pdf_stream(form, flate_bomb_ops(form_bytes)),
            pdf_stream(form, flate_bomb_ops(form_bytes)),
        ]
    )


def tree_node_ap_state_bomb_pdf(inflated_bytes: int, *, node: str) -> bytes:
    """Page 0's annotation uses a page-tree node as its ``/AP /N`` state dict.

    ``node`` is ``"root"`` (the ``/Pages`` root, object 2) or ``"sibling"``
    (page 1, object 6). The node carries an extra ``/On 7 0 R`` entry; the
    annotation's ``/AS /On`` selects it, and object 7 is a Form XObject
    bomb. Both renderers draw it: an appearance state dict is looked up by
    the state name, whatever else the dict is.
    """
    root_extra = b" /On 7 0 R" if node == "root" else b""
    sibling_extra = b" /On 7 0 R" if node == "sibling" else b""
    state_dict = b"2 0 R" if node == "root" else b"6 0 R"
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 2" + root_extra + b" >>",
            _A4_PAGE + b" /Annots [5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Annot /Subtype /Stamp /Rect [0 0 10 10] /AP << /N "
            + state_dict
            + b" >> /AS /On >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
            + sibling_extra
            + b" >>",
            _bomb_form(inflated_bytes),
        ]
    )


def sibling_page_as_soft_mask_bomb_pdf(inflated_bytes: int) -> bytes:
    """Page 0's graphics state (an ordinary ExtGState dict, object 5) uses
    the sibling page (object 6) as its soft mask.

    The sibling page also carries ``/S /Luminosity /G 7 0 R``, and object
    7 is a Form XObject bomb. The first hop is not a page-tree node, so the
    walk only meets the tree while expanding an ordinary container.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 >>",
            _A4_PAGE + b" /Resources << /ExtGState << /GS1 5 0 R >> >> >>",
            pdf_stream(b"", b"/GS1 gs q Q"),
            b"<< /Type /ExtGState /SMask 6 0 R >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/S /Luminosity /G 7 0 R >>",
            _bomb_form(inflated_bytes),
        ]
    )


def seeded_page_tree_bomb_pdf(inflated_bytes: int, *, seed: str) -> bytes:
    """Page 0's annotation uses the sibling page (object 6) as its ``/AP /N``
    state dict, and page 0 also lists the sibling page elsewhere first.

    ``seed`` is ``"annots"`` (``/Annots [6 0 R 5 0 R]``: the sibling page
    listed as an annotation) or ``"contents"`` (``/Contents [4 0 R 6 0 R]``:
    a non-stream listed as page content). Either one puts object 6 among
    the objects the walk has already handled, so a walk that skips handled
    objects before checking the page tree never rejects it.
    """
    annots = b"[6 0 R 5 0 R]" if seed == "annots" else b"[5 0 R]"
    contents = b"[4 0 R 6 0 R]" if seed == "contents" else b"4 0 R"
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents "
            + contents
            + b" /Annots "
            + annots
            + b" >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Annot /Subtype /Stamp /Rect [0 0 200 200] /AP << /N 6 0 R >> /AS /On >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /On 7 0 R >>",
            _bomb_form(inflated_bytes),
        ]
    )


def non_stream_contents_pdf() -> bytes:
    """A page whose ``/Contents`` array names a dictionary (object 5), not a stream."""
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents [4 0 R 5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Foo 1 >>",
        ]
    )


def type3_stream_font_bomb_pdf(inflated_bytes: int) -> bytes:
    """A Type3 font that is itself a stream object; its one glyph procedure
    (object 6) decodes to ``inflated_bytes`` of drawing operators.

    MuPDF loads a font dictionary whether or not it carries a stream, so the
    glyph is drawn all the same.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /Font << /F1 5 0 R >> >> >>",
            pdf_stream(b"", b"BT /F1 100 Tf 0 0 Td (a) Tj ET"),
            pdf_stream(
                b"/Type /Font /Subtype /Type3 /FontBBox [0 0 1000 1000] "
                b"/FontMatrix [0.001 0 0 0.001 0 0] /CharProcs << /a 6 0 R >> "
                b"/Encoding << /Type /Encoding /Differences [97 /a] >> "
                b"/FirstChar 97 /LastChar 97 /Widths [1000]",
                b"",
            ),
            pdf_stream(b"/Filter /FlateDecode", flate_bomb_ops(inflated_bytes)),
        ]
    )


def stream_extgstate_smask_bomb_pdf(inflated_bytes: int) -> bytes:
    """A graphics state written as a stream object, whose inline ``/SMask``
    dict's ``/G`` group (object 6) is a Form XObject bomb.

    MuPDF reads a graphics state's keys whether or not it carries a stream.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /ExtGState << /GS0 5 0 R >> >> >>",
            pdf_stream(b"", b"/GS0 gs 0 g 0 0 200 200 re f"),
            pdf_stream(b"/Type /ExtGState /SMask << /S /Luminosity /G 6 0 R >>", b""),
            _bomb_form(inflated_bytes),
        ]
    )


def stamp_with_jpeg_appearance_pdf() -> bytes:
    """A stamp whose appearance form draws a JPEG image through an indirect
    ``/Resources`` (object 8), as stamp tools write them.

    The appearance form is walked in the ``"any"`` role, where every other
    reference in its dictionary is walked too; its image must still be met
    under ``/XObject`` and size-checked, not counted as page content (a
    JPEG stream cannot be measured and would be refused).
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Annots [5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Annot /Subtype /Stamp /Rect [0 0 100 100] /AP << /N 6 0 R >> >>",
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 100 100] /Resources 8 0 R "
                b"/Group << /S /Transparency >>",
                b"q 100 0 0 100 0 0 cm /Im0 Do Q",
            ),
            pdf_stream(
                b"/Type /XObject /Subtype /Image /Width 2000 /Height 2000 "
                b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode",
                b"\xff\xd8\xff\xd9",
            ),
            b"<< /XObject << /Im0 7 0 R >> >>",
        ]
    )


def type3_dict_font_with_jpeg_pdf() -> bytes:
    """A legitimate (non-stream) Type3 font whose glyph draws a JPEG from the
    font's own ``/Resources``.

    The font is a plain dict container reached in the ``"font"`` role; its
    ``/Resources`` must be read by category, so the JPEG is met under
    ``/XObject`` and size-checked -- not counted as content, where a JPEG
    stream cannot be measured and would be refused.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /Font << /F1 5 0 R >> >> >>",
            pdf_stream(b"", b"BT /F1 50 Tf 100 100 Td (a) Tj ET"),
            b"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 1000 1000] "
            b"/FontMatrix [0.001 0 0 0.001 0 0] /CharProcs << /a 6 0 R >> "
            b"/Encoding << /Type /Encoding /Differences [97 /a] >> /FirstChar 97 /LastChar 97 "
            b"/Widths [1000] /Resources << /XObject << /Im0 7 0 R >> >> >>",
            pdf_stream(b"", b"1000 0 0 0 1000 1000 d1 q 1000 0 0 1000 0 0 cm /Im0 Do Q"),
            pdf_stream(
                b"/Type /XObject /Subtype /Image /Width 64 /Height 64 /ColorSpace /DeviceGray "
                b"/BitsPerComponent 8 /Filter /DCTDecode",
                b"\xff\xd8\xff\xd9",
            ),
        ]
    )


def image_labelled_appearance_pdf(width: int, height: int) -> bytes:
    """An annotation whose ``/AP /N`` is itself an image-labelled stream
    DECLARING ``width x height``.

    Reached only in the ``"any"`` role (never under ``/XObject``), so only
    an image check that runs in every role sees its declared size.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Annots [5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Annot /Subtype /Stamp /Rect [0 0 200 200] /AP << /N 6 0 R >> >>",
            pdf_stream(
                f"/Type /XObject /Subtype /Image /Width {width} /Height {height} "
                "/ColorSpace /DeviceGray /BitsPerComponent 8 /BBox [0 0 200 200] "
                "/Filter /FlateDecode".encode(),
                zlib.compress(b"\x00"),
            ),
        ]
    )


def form_also_graphics_state_bomb_pdf(inflated_bytes: int, *, xobject_first: bool) -> bytes:
    """One Form XObject (object 5) used both as an ``/XObject`` and as a
    graphics state, whose ``/SMask`` group (object 7) is a Form bomb.

    With ``xobject_first`` the page files 5 under ``/XObject`` and an
    annotation's appearance form (object 6) files it under ``/ExtGState``;
    otherwise the two uses swap places, so the walk meets the same object
    in the opposite order. MuPDF applies the graphics state's soft mask
    either way.
    """
    page_use, ap_use = (b"/XObject << /X0", b"/ExtGState << /GS0")
    page_ops, ap_ops = (b"q /X0 Do Q", b"/GS0 gs 0 g 0 0 200 200 re f")
    if not xobject_first:
        page_use, ap_use = ap_use, page_use
        page_ops, ap_ops = ap_ops.replace(b"0 0 200 200", b"0 0 10 10"), page_ops
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << " + page_use + b" 5 0 R >> >> /Annots [8 0 R] >>",
            pdf_stream(b"", page_ops),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 1 1] "
                b"/SMask << /S /Luminosity /G 7 0 R >>",
                b"",
            ),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 200 200] /Resources << "
                + ap_use
                + b" 5 0 R >> >>",
                ap_ops,
            ),
            _bomb_form(inflated_bytes),
            b"<< /Type /Annot /Subtype /Stamp /Rect [0 0 200 200] /AP << /N 6 0 R >> >>",
        ]
    )


def contents_also_appearance_bomb_pdf(inflated_bytes: int) -> bytes:
    """The page's own content stream (object 4) is also its annotation's
    ``/AP /N`` form, and only as a form does it use its own ``/Resources``,
    which name a Form bomb (object 6).

    MuPDF draws the appearance with those resources; as page content the
    same stream draws nothing, since the page has no ``/Resources``.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Annots [5 0 R] >>",
            pdf_stream(
                b"/Subtype /Form /BBox [0 0 200 200] /Resources << /XObject << /B 6 0 R >> >>",
                b"q /B Do Q",
            ),
            b"<< /Type /Annot /Subtype /Stamp /Rect [0 0 200 200] /AP << /N 4 0 R >> >>",
            _bomb_form(inflated_bytes),
        ]
    )


def sibling_page_listed_as_annotation_pdf() -> bytes:
    """Page 0's ``/Annots`` lists the sibling page (object 5), and nothing
    else of page 0 reaches the page tree. Otherwise harmless."""
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
            _A4_PAGE + b" /Annots [5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
        ]
    )


def xobject_also_listed_as_annotation_bomb_pdf(inflated_bytes: int) -> bytes:
    """One stream (object 5) filed under page 0's ``/XObject`` and also
    listed in its ``/Annots``, whose ``/AP /N`` (object 6) is a Form bomb.

    Walked first as an XObject (its own stream is harmless), the object
    must still have its ``/AP`` read as an annotation.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /XObject << /X0 5 0 R >> >> /Annots [5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            pdf_stream(
                b"/Subtype /Stamp /Rect [0 0 200 200] /BBox [0 0 1 1] /AP << /N 6 0 R >>", b""
            ),
            _bomb_form(inflated_bytes),
        ]
    )


def links_to_sibling_pages_pdf() -> bytes:
    """A 2-page PDF whose page 0 has two internal links to page 1 and a
    stamp with an ordinary appearance stream.

    One link uses ``/Dest [5 0 R /XYZ ...]``, the other ``/A << /S /GoTo /D
    [5 0 R /Fit] >>``; every annotation also has ``/P 3 0 R``, and the
    stamp a ``/Popup``. None of these names a page to draw, so the walk
    must not follow them: this file must pass.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
            _A4_PAGE + b" /Annots [6 0 R 7 0 R 8 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
            b"<< /Type /Annot /Subtype /Link /Rect [0 0 10 10] /P 3 0 R "
            b"/Dest [5 0 R /XYZ 0 842 0] >>",
            b"<< /Type /Annot /Subtype /Link /Rect [0 20 10 30] /P 3 0 R "
            b"/A << /S /GoTo /D [5 0 R /Fit] >> >>",
            b"<< /Type /Annot /Subtype /Stamp /Rect [0 40 10 50] /P 3 0 R "
            b"/AP << /N 9 0 R >> /Popup 10 0 R >>",
            pdf_stream(b"/Type /XObject /Subtype /Form /BBox [0 0 10 10]", b"0 g 0 0 10 10 re f"),
            b"<< /Type /Annot /Subtype /Popup /Rect [0 60 10 70] /Parent 8 0 R /P 5 0 R >>",
        ]
    )


def embedded_font_pdf(font_program_bytes: int) -> bytes:
    """A page using one TrueType font whose embedded program (``/FontFile2``)
    decodes to ``font_program_bytes``.

    A font program is parsed by the font engine, not executed
    as drawing operators, so it is not page content -- a large embedded
    font must not count against the content caps. Only the ``/Font`` map
    makes it a font; its own ``/Type`` is not trusted for that.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /Font << /F1 5 0 R >> >> >>",
            pdf_stream(b"", b"BT /F1 12 Tf (A) Tj ET"),
            b"<< /Type /Font /Subtype /TrueType /BaseFont /Synthetic "
            b"/FirstChar 65 /LastChar 65 /Widths [600] /FontDescriptor 6 0 R >>",
            b"<< /Type /FontDescriptor /FontName /Synthetic /Flags 32 "
            b"/FontBBox [0 0 1000 1000] /ItalicAngle 0 /Ascent 800 /Descent -200 "
            b"/CapHeight 700 /StemV 80 /FontFile2 7 0 R >>",
            pdf_stream(
                b"/Filter /FlateDecode",
                zlib.compress(b"\x00" * font_program_bytes, 9),
            ),
        ]
    )


def _bomb_form(inflated_bytes: int) -> bytes:
    """A Form XObject whose Flate content decodes to ``inflated_bytes``."""
    return pdf_stream(
        b"/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Filter /FlateDecode",
        flate_bomb_ops(inflated_bytes),
    )


def annot_ap_nested_bomb_pdf(inflated_bytes: int, *, ap_dict: bytes) -> bytes:
    """An annotation appearance stream (object 6, dictionary ``ap_dict``)
    whose own ``/Resources`` names a Form XObject bomb (object 7).

    A renderer runs an appearance stream as a form whatever its
    ``/Subtype`` says -- none at all, or ``/Image`` -- so a walk that only
    expands streams labelled ``/Form`` never reaches the bomb.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Annots [5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Annot /Subtype /Stamp /Rect [0 0 10 10] /AP << /N 6 0 R >> >>",
            pdf_stream(
                ap_dict + b" /BBox [0 0 10 10] /Resources << /XObject << /Fm1 7 0 R >> >>",
                b"/Fm1 Do",
            ),
            _bomb_form(inflated_bytes),
        ]
    )


def indirect_subtype_form_bomb_pdf(inflated_bytes: int) -> bytes:
    """A page form whose ``/Subtype`` is an indirect name (object 6 is
    ``/Form``) and whose own ``/Resources`` names a Form XObject bomb.

    A renderer resolves the reference and draws the form; a walk comparing
    the unresolved ``6 0 R`` against ``/Form`` never expands it.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" /Resources << /XObject << /Fm0 5 0 R >> >> >>",
            pdf_stream(b"", b"/Fm0 Do"),
            pdf_stream(
                b"/Type /XObject /Subtype 6 0 R /BBox [0 0 10 10] "
                b"/Resources << /XObject << /Fm1 7 0 R >> >>",
                b"/Fm1 Do",
            ),
            b"/Form",
            _bomb_form(inflated_bytes),
        ]
    )


def parent_poisoned_ap_state_bomb_pdf(inflated_bytes: int) -> bytes:
    """A page whose ``/Parent`` names its own annotation's appearance-state
    dict (object 6), whose selected state (object 7) is a Form XObject bomb.

    Both renderers find the page through ``/Kids``, so the bogus
    ``/Parent`` does not stop it rendering; a page-tree set built by
    climbing ``/Parent`` would count object 6 as a tree node and never
    expand it.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 6 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Annots [5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Annot /Subtype /Stamp /Rect [0 0 10 10] /AP << /N 6 0 R >> /AS /On >>",
            b"<< /On 7 0 R >>",
            _bomb_form(inflated_bytes),
        ]
    )


def born_digital_text_pdf(*, pages: int) -> bytes:
    """A ``pages``-page PDF with real text (``pymupdf``'s ``insert_text``,
    one shared font across every page), for Task 11b's measurements: a page
    whose content and resources are genuinely non-trivial, not a synthetic
    bomb -- the corpus's counterpart of the scanned-image page the
    committed fixture already measures.
    """
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), "The quick brown fox jumps over the lazy dog.", fontname="helv")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


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


def bomb_on_second_page_pdf(inflated_bytes: int) -> bytes:
    """Two A4 pages: page 1 draws one small red rectangle; page 2's only
    content stream inflates to ``inflated_bytes`` (a content bomb).

    Triage F8: the crop route used to walk EVERY page before rendering one,
    so a request for page 1 paid for, and was refused by, page 2.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
            pdf_stream(b"", b"q 1 0 0 rg 60 500 120 250 re f Q"),
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 6 0 R >>",
            pdf_stream(b"/Filter /FlateDecode", flate_bomb_ops(inflated_bytes)),
        ]
    )


def wide_page_tree_pdf(kids: int, *, count: int, shared_kid: bool = False) -> bytes:
    """A ``/Pages`` root with ``kids`` entries in its ``/Kids`` that declares ``/Count count``.

    Each kid is a blank A4 ``/Page``. With ``shared_kid``, every kid also
    carries its own ``/Kids`` naming ONE shared page, so the tree has
    ``kids + 1`` nodes and only one of them names no ``/Kids``; each kid is
    still a ``/Type /Page``, which MuPDF counts as a page.

    Review round 1 on triage F8: the crop route's page bound must count the
    tree a reader descends, not the ``/Count`` it declares, and must stop
    descending once it is over the bound.
    """
    shared = 3 + kids
    kid_body = (
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Kids [{shared} 0 R] >>".encode()
        if shared_kid
        else b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>"
    )
    kid_refs = " ".join(f"{3 + i} 0 R" for i in range(kids))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kid_refs}] /Count {count} >>".encode(),
        *([kid_body] * kids),
    ]
    if shared_kid:
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>")
    return assemble_pdf(objects)


def wrapped_page_tree_pdf(pages: int, *, wrap: int = 0, fanout: int | None = None) -> bytes:
    """A spec-valid page tree of ``pages`` pages, each drawing a red rectangle.

    Every page sits under ``wrap`` single-kid ``/Pages`` nodes (the spec does
    not require an inner node to have two or more kids), or, with
    ``fanout``, pages are grouped under intermediate ``/Pages`` nodes of up to
    ``fanout`` kids each. Every ``/Count`` is correct; MuPDF and pdfium both
    count and render these files.

    Review round 2 on triage F8 (adapted from the reviewer's probe): the
    page-tree bounds must not refuse such a tree at the page cap.
    """
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]

    def new(body: bytes = b"") -> int:
        objects.append(body)
        return len(objects)

    def page(parent: int) -> int:
        number = new()
        content = new(pdf_stream(b"", b"q 1 0 0 rg 60 500 120 250 re f Q"))
        objects[number - 1] = (
            f"<< /Type /Page /Parent {parent} 0 R /MediaBox [0 0 595 842] "
            f"/Contents {content} 0 R >>"
        ).encode()
        return number

    def wrapped_page(parent: int) -> int:
        """The object ``parent`` names for one page: the page or its outermost wrapper."""
        wrappers: list[tuple[int, int]] = []
        for _ in range(wrap):
            wrapper = new()
            wrappers.append((wrapper, parent))
            parent = wrapper
        kid = page(parent)
        for wrapper, wrapper_parent in reversed(wrappers):
            objects[wrapper - 1] = (
                f"<< /Type /Pages /Parent {wrapper_parent} 0 R /Kids [{kid} 0 R] /Count 1 >>"
            ).encode()
            kid = wrapper
        return kid

    root_kids: list[int] = []
    if fanout:
        for start in range(0, pages, fanout):
            chunk = min(fanout, pages - start)
            node = new()
            kids = [wrapped_page(node) for _ in range(chunk)]
            kid_refs = " ".join(f"{k} 0 R" for k in kids)
            objects[node - 1] = (
                f"<< /Type /Pages /Parent 2 0 R /Kids [{kid_refs}] /Count {chunk} >>"
            ).encode()
            root_kids.append(node)
    else:
        root_kids = [wrapped_page(2) for _ in range(pages)]
    root_refs = " ".join(f"{k} 0 R" for k in root_kids)
    objects[1] = f"<< /Type /Pages /Kids [{root_refs}] /Count {pages} >>".encode()
    return assemble_pdf(objects)


def pages_carrying_kids_pdf(pages: int) -> bytes:
    """``pages`` A4 ``/Type /Page`` kids under ``/Count 1``, each also
    carrying a ``/Kids`` that names only an object past the file's end.

    MuPDF takes a ``/Type /Page`` as a page whatever else it carries, so it
    counts ``pages`` of them; a count that only knows "a node with no
    ``/Kids`` is a page" sees none (review round 2 on triage F8, minor 1).
    """
    dangling = 3 + pages + 1_000
    kid_refs = " ".join(f"{3 + i} 0 R" for i in range(pages))
    page = (
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Kids [{dangling} 0 R] >>"
    ).encode()
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{kid_refs}] /Count 1 >>".encode(),
            *([page] * pages),
        ]
    )


def empty_pages_nodes_pdf(pages: int, empties: int) -> bytes:
    """``pages`` A4 pages plus ``empties`` empty ``/Type /Pages`` nodes
    (``/Kids [] /Count 0``), all kids of the root, under ``/Count pages``.

    Review round 3 on triage F8 (adapted from the reviewer's probe): MuPDF
    and pdfium both count and render ``pages`` pages -- an empty ``/Pages``
    node is not a page, although it names no ``/Kids``.
    """
    page_body = pdf_stream(b"", b"q 1 0 0 rg 60 500 120 250 re f Q")
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids: list[int] = []
    for _ in range(pages):
        objects.append(page_body)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Contents {len(objects)} 0 R >>".encode()
        )
        kids.append(len(objects))
    for _ in range(empties):
        objects.append(b"<< /Type /Pages /Parent 2 0 R /Kids [] /Count 0 >>")
        kids.append(len(objects))
    kid_refs = " ".join(f"{k} 0 R" for k in kids)
    objects[1] = f"<< /Type /Pages /Kids [{kid_refs}] /Count {pages} >>".encode()
    return assemble_pdf(objects)


def repeated_subtree_pdf(inner: int, *, times: int, count: int) -> bytes:
    """A root whose ``/Kids`` names one ``/Pages`` subtree of ``inner`` pages
    ``times`` times, declaring ``/Count count``.

    Adapted from the reviewer's round-3 probe on triage F8: at
    ``inner=40, times=8, count=320`` pymupdf's own ``page_count`` raises
    (``Invalid number of pages``) while pdfium counts 320.
    """
    page_body = pdf_stream(b"", b"q 1 0 0 rg 60 500 120 250 re f Q")
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b""]
    pages: list[int] = []
    for _ in range(inner):
        objects.append(page_body)
        objects.append(
            f"<< /Type /Page /Parent 3 0 R /MediaBox [0 0 595 842] "
            f"/Contents {len(objects)} 0 R >>".encode()
        )
        pages.append(len(objects))
    page_refs = " ".join(f"{p} 0 R" for p in pages)
    objects[2] = f"<< /Type /Pages /Parent 2 0 R /Kids [{page_refs}] /Count {inner} >>".encode()
    subtree_refs = " ".join(["3 0 R"] * times)
    objects[1] = f"<< /Type /Pages /Kids [{subtree_refs}] /Count {count} >>".encode()
    return assemble_pdf(objects)


def page_kids_bomb_pdf(inflated_bytes: int) -> bytes:
    """A root under ``/Count 2`` naming one ``/Type /Page`` node that has its
    own clean content AND a ``/Kids`` naming a clean page and a content bomb.

    Task 9b (the reviewer's round-4 reproduction): MuPDF resolves page 0 to
    the typed node and cannot resolve page 1 at all; pdfium descends the
    ``/Kids`` and renders the bomb as its page 1.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Kids [5 0 R 7 0 R] /Count 2 >>",
            pdf_stream(b"", b"q 1 0 0 rg 60 500 120 250 re f Q"),
            b"<< /Type /Page /Parent 3 0 R /MediaBox [0 0 595 842] /Contents 6 0 R >>",
            pdf_stream(b"", b"q 0 0 1 rg 60 500 120 250 re f Q"),
            b"<< /Type /Page /Parent 3 0 R /MediaBox [0 0 595 842] /Contents 8 0 R >>",
            pdf_stream(b"/Filter /FlateDecode", flate_bomb_ops(inflated_bytes)),
        ]
    )


def page_kids_equal_count_bomb_pdf(inflated_bytes: int) -> bytes:
    """Root ``/Kids [P C] /Count 2``: P is a ``/Type /Page`` with clean content
    that ALSO names ``/Kids [B]``, B a content-bomb page; C is clean.

    Task 9b review round 1 (the reviewer's equal-count variant): both readers
    count 2 pages, but MuPDF numbers them [P, C] and measures both, while
    pdfium descends P's ``/Kids`` and renders B as its page 1.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 7 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Kids [5 0 R] /Count 1 >>",
            pdf_stream(b"", b"q 1 0 0 rg 60 500 120 250 re f Q"),
            b"<< /Type /Page /Parent 3 0 R /MediaBox [0 0 595 842] /Contents 6 0 R >>",
            pdf_stream(b"/Filter /FlateDecode", flate_bomb_ops(inflated_bytes)),
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 8 0 R >>",
            pdf_stream(b"", b"q 0 0 1 rg 60 500 120 250 re f Q"),
        ]
    )


def shared_container_broken_xref_pdf(
    elements: int,
    *,
    type_entry: bytes = b"/Type /ObjStm",
    filter_entry: bytes = b"/Filter /FlateDecode",
    length_delta: int = 0,
    break_xref: bool = True,
    stream_separator: bytes = b"\n",
    corrupt_header: bool = False,
    encrypt_entry: bytes = b"",
) -> bytes:
    """One page whose page dict sits in a Flate object stream beside an
    array of ``elements`` zeros no page draws from; ``startxref`` is off by
    7, so MuPDF repairs the xref at open -- and repair loads every object
    stream it finds, container-mates and all, before anything can bound it.

    ``type_entry``, ``filter_entry`` and ``length_delta`` vary how the
    container's dictionary is spelled (``/Type/ObjStm``, a name escape, a
    one-element ``/Filter`` array, a ``/Length`` that is wrong by
    ``length_delta``). ``stream_separator`` is what sits between the
    ``stream`` keyword and the data (the spec's is an EOL; MuPDF also skips
    spaces before it), and ``corrupt_header`` replaces the zlib header so
    nothing inflates. ``encrypt_entry`` (e.g. ``b"/Encrypt 99 0 R"``) is added
    to the xref stream's dictionary, which is the file's trailer, declaring
    the file encrypted. Adapted from the reviewer's ``c2_amp.py`` case
    ``junk_shares_page_container_broken_xref`` (Task 9c review round 2).
    """
    junk = b"[" + b"0 " * elements + b"]"
    content = b"q 1 0 0 rg 60 500 120 250 re f Q"
    page = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>"
    header = b"3 0 9 %d " % (len(page) + 1)
    packed = zlib.compress(header + page + b" " + junk, 9)
    if corrupt_header:
        packed = b"\x00\x00" + packed[2:]
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        4: pdf_stream(b"", content),
        5: b"<< "
        + type_entry
        + b" /N 2 /First %d " % len(header)
        + filter_entry
        + b" /Length %d >>\nstream" % (len(packed) + length_delta)
        + stream_separator
        + packed
        + b"\nendstream",
    }
    out = bytearray(b"%PDF-1.7\n")
    offsets: dict[int, int] = {}
    for number, body in objects.items():
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    rows = [bytes([0, 0, 0, 0, 0, 0xFF])]
    for number in range(1, 11):
        if number in (3, 9):
            rows.append(bytes([2]) + (5).to_bytes(4, "big") + bytes([0 if number == 3 else 1]))
        elif number == 10:
            rows.append(bytes([1]) + xref_at.to_bytes(4, "big") + b"\x00")
        elif number in offsets:
            rows.append(bytes([1]) + offsets[number].to_bytes(4, "big") + b"\x00")
        else:
            rows.append(bytes(6))
    table = zlib.compress(b"".join(rows))
    out += (
        b"10 0 obj\n"
        + pdf_stream(
            b"/Type /XRef /Size 11 /W [1 4 1] /Root 1 0 R /Filter /FlateDecode " + encrypt_entry,
            table,
        )
        + b"\nendobj\n"
    )
    out += f"startxref\n{xref_at + (7 if break_xref else 0)}\n%%EOF\n".encode()
    return bytes(out)


def bare_encrypt_dict_pdf(*, prefix: bytes = b"", encrypt_key: bytes = b"/Encrypt") -> bytes:
    """One page plus a harmless ~20 KB Flate object stream (seeded random
    bytes, so it barely compresses), then -- with no xref -- a bare
    trailer-like dictionary carrying ``encrypt_key`` (``b""`` for none),
    introduced by ``prefix`` rather than the ``trailer`` keyword.

    Encrypt parity (verifier's ``gap.py``): MuPDF's xref repair reads
    ``/Encrypt`` from any top-level dictionary like this one, so the
    object-stream pre-scan must count the file as encrypted too. Counted
    as encrypted, the stream's ~20 KB counts at Flate's ceiling (~20 MB) and
    is refused; counted as plain, it inflates to ~20 KB and passes.
    """
    payload = random.Random(9).randbytes(20_000)
    packed = zlib.compress(payload, 1)
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>",
        4: pdf_stream(b"/Type /ObjStm /N 0 /First 0 /Filter /FlateDecode", packed),
    }
    out = bytearray(b"%PDF-1.7\n")
    for number, body in objects.items():
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    encrypt = (
        encrypt_key + b" <</Filter /Standard /V 1 /R 2 /O <00> /U <00> /P -4>>"
        if encrypt_key
        else b""
    )
    out += prefix + b"<</Root 1 0 R /Size 5 " + encrypt + b">>\nstartxref\n0\n%%EOF\n"
    return bytes(out)


def hidden_layer_pdf(*, variant: str = "text") -> bytes:
    """One A4 page with content on an optional-content layer that is OFF by
    default, beside content on a layer that is ON.

    ``variant``: ``"text"`` -- hidden text and a filled rectangle; or
    ``"image"`` -- a hidden image XObject and a hidden square annotation.
    Built with pymupdf's own layer API (the reviewer's fidelity probe).

    Task 9c review round 2: a renderer shows the hidden content only if the
    catalog's ``/OCProperties`` is lost, so the rewrite must keep it.
    """
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=595, height=842)
        hidden = doc.add_ocg("hidden-by-default", on=False)
        shown = doc.add_ocg("visible", on=True)
        page.insert_text((50, 100), "VISIBLE LAYER TEXT", fontsize=30, oc=shown)
        if variant == "text":
            page.insert_text((50, 300), "HIDDEN LAYER TEXT", fontsize=30, oc=hidden)
            page.draw_rect(
                pymupdf.Rect(50, 400, 400, 600), color=(0, 0, 0), fill=(0, 0, 0), oc=hidden
            )
        else:
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), 0)
            pixmap.clear_with(0)
            page.insert_image(pymupdf.Rect(50, 150, 300, 400), pixmap=pixmap, oc=hidden)
            annot = page.add_rect_annot(pymupdf.Rect(300, 450, 550, 750))
            annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
            annot.set_oc(hidden)
            annot.update()
        data: bytes = doc.tobytes()
    finally:
        doc.close()
    return data


def off_page_object_pdf(
    elements: int, *, shape: str = "array", compressed: bool = True, holder: str = "catalog"
) -> bytes:
    """One A4 page, plus one big object (object 6) no page draws from.

    ``shape``: ``"array"`` (``elements`` zeros), ``"dict"`` (``elements``
    keys) or ``"string"`` (``elements`` hex bytes). ``holder``: the catalog
    (``/Junk``) or the page dict (``/Junk``, a key no renderer reads). With
    ``compressed`` object 6 sits in a Flate object stream (object 5), so a
    few KB on disk parse into hundreds of MB; without, it is a plain object.
    Written with an xref stream (object 10), which object streams need.

    Task 9c review round 1 (the reviewer's amplification probe): the
    content check never walks object 6, so nothing that renders extraction
    input may parse it either.
    """
    if shape == "array":
        body = b"[" + b"0 " * elements + b"]"
    elif shape == "dict":
        body = b"<<" + b"".join(b"/K%d 0 " % i for i in range(elements)) + b">>"
    else:
        body = b"<" + b"00" * elements + b">"
    catalog_junk = b" /Junk 6 0 R" if holder == "catalog" else b""
    page_junk = b" /Junk 6 0 R" if holder == "page" else b""
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R" + catalog_junk + b" >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
        + page_junk
        + b" >>",
        4: pdf_stream(b"", b"q 1 0 0 rg 60 500 120 250 re f Q"),
    }
    out = bytearray(b"%PDF-1.7\n")
    offsets: dict[int, int] = {}
    for number, obj in objects.items():
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    if compressed:
        header = b"6 0 "
        offsets[5] = len(out)
        packed = zlib.compress(header + body, 9)
        out += (
            b"5 0 obj\n"
            + pdf_stream(b"/Type /ObjStm /N 1 /First %d /Filter /FlateDecode" % len(header), packed)
            + b"\nendobj\n"
        )
    else:
        offsets[6] = len(out)
        out += b"6 0 obj\n" + body + b"\nendobj\n"
    xref_at = len(out)
    rows = [bytes([0, 0, 0, 0, 0, 0xFF])]
    for number in range(1, 11):
        if number == 6 and compressed:
            rows.append(bytes([2]) + (5).to_bytes(4, "big") + b"\x00")
        elif number == 10:
            rows.append(bytes([1]) + xref_at.to_bytes(4, "big") + b"\x00")
        elif number in offsets:
            rows.append(bytes([1]) + offsets[number].to_bytes(4, "big") + b"\x00")
        else:
            rows.append(bytes(6))
    table = zlib.compress(b"".join(rows))
    out += (
        b"10 0 obj\n"
        + pdf_stream(b"/Type /XRef /Size 11 /W [1 4 1] /Root 1 0 R /Filter /FlateDecode", table)
        + b"\nendobj\n"
    )
    out += f"startxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def xref_repair_bomb_pdf(inflated_bytes: int, *, entry_eol: bytes = b"\n") -> bytes:
    """One page whose content, object 4, is defined twice: a clean red
    rectangle first (the xref points at it), then a content bomb. Each xref
    entry ends in ``entry_eol``; the spec's is two bytes (``b" \\n"``), so
    ``b"\\n"`` or ``b"\\r"`` leaves every entry 19 bytes long.

    Task 9c (the reviewer's xref-repair probe): with 19-byte entries MuPDF
    still reads the xref and measures the clean object, while pdfium
    rebuilds the xref by scanning, takes the later definition and renders
    the bomb. Page counts and page sets agree.
    """
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}

    def obj(number: int, body: bytes) -> None:
        offsets.setdefault(number, len(out))
        out.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")

    obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    obj(3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>")
    obj(4, pdf_stream(b"", b"q 1 0 0 rg 60 500 120 250 re f Q"))
    obj(4, pdf_stream(b"/Filter /FlateDecode", flate_bomb_ops(inflated_bytes)))
    xref_at = len(out)
    out.extend(b"xref\n0 5\n0000000000 65535 f" + entry_eol)
    for number in (1, 2, 3, 4):
        out.extend(f"{offsets[number]:010d} 00000 n".encode() + entry_eol)
    out.extend(f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode())
    return bytes(out)


def empty_page_tree_pdf() -> bytes:
    """A catalog and a ``/Pages`` root with no kids: neither reader finds a page.

    Task 9c: extraction's contract for an empty PDF is a ``ValueError``.
    """
    return assemble_pdf(
        [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [] /Count 0 >>"]
    )


def many_objects_pdf(objects: int) -> bytes:
    """One blank A4 page plus ``objects`` small dicts nothing references.

    Task 9c: MuPDF's rewrite costs time per object in the file, referenced
    or not, so the object count is bounded before the rewrite.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            _A4_PAGE + b" >>",
            pdf_stream(b"", b"q Q"),
            *([b"<< /A 1 >>"] * objects),
        ]
    )


def uncounted_bomb_pdf(inflated_bytes: int, *, count_entry: bytes) -> bytes:
    """Two pages, the second a content bomb, under a root whose ``/Count``
    entry is ``count_entry`` (``b"/Count 0"``, ``b"/Count -1"`` or ``b""``).

    Task 9b: MuPDF believes the missing or zero ``/Count`` and sees no
    pages (or cannot count them), so its content walk measures nothing;
    pdfium walks the ``/Kids`` and renders both pages, bomb included.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 5 0 R] " + count_entry + b" >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
            pdf_stream(b"", b"q 1 0 0 rg 60 500 120 250 re f Q"),
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 6 0 R >>",
            pdf_stream(b"/Filter /FlateDecode", flate_bomb_ops(inflated_bytes)),
        ]
    )


def overstated_count_pdf(pages: int, *, count: int) -> bytes:
    """``pages`` blank A4 pages under a root declaring ``/Count count``.

    Task 9b (the reviewer's guard probe, ``/Count 5`` over 3 real pages):
    both readers believe the ``/Count`` and fail to find the pages past the
    real ones.
    """
    kid_refs = " ".join(f"{3 + i} 0 R" for i in range(pages))
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{kid_refs}] /Count {count} >>".encode(),
            *([b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>"] * pages),
        ]
    )


def deep_page_chain_pdf(depth: int) -> bytes:
    """One page under ``depth`` nested single-kid ``/Pages`` nodes.

    Spec-valid and harmless, but a page tree that costs ``depth`` reads to
    find one page: past the work bound it is refused as too complex to
    check, never as "more than N pages".
    """
    return wrapped_page_tree_pdf(1, wrap=depth)


def repeated_kid_pdf(times: int) -> bytes:
    """A ``/Pages`` root under ``/Count 1`` whose ``/Kids`` names ONE page
    ``times`` times: three objects in the tree, ``times`` pages to a reader.

    Review round 1 on triage F8: the crop bound must not be dodged by
    repeating a kid, nor pay to read every repetition.
    """
    refs = " ".join(["3 0 R"] * times)
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{refs}] /Count 1 >>".encode(),
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>",
        ]
    )


def long_parent_chain_pdf(length: int) -> bytes:
    """One A4 page whose ``/Parent`` starts a chain of ``length`` plain dicts,
    each naming the next as its ``/Parent``; none of them is in the page tree.

    Review round 1 on triage F8: the ``/Parent`` climb for resource holders
    must stay bounded too, not only the ``/Kids`` descent.
    """
    chain = [f"<< /Parent {5 + i} 0 R >>".encode() for i in range(length - 1)]
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 4 0 R /MediaBox [0 0 595 842] >>",
            *chain,
            b"<< >>",
        ]
    )


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = struct.pack(">I", zlib.crc32(tag + data))
    return struct.pack(">I", len(data)) + tag + data + crc


#: PNG (bit depth, colour type) for each Pillow mode :func:`declared_image` writes as PNG.
_PNG_MODES = {"1": (1, 0), "L": (8, 0), "P": (8, 3), "LA": (8, 4), "RGB": (8, 2), "RGBA": (8, 6)}


def declared_image(mode: str, width: int, height: int) -> bytes:
    """An image file that DECLARES ``width`` x ``height`` in ``mode`` and holds no pixels.

    #256: every image check refuses from the header, before a pixel is
    decoded, so a refusal test needs only a header -- a few dozen bytes
    rather than the hundreds of MB a real 41.6 Mpx colour or 161 Mpx grey
    image costs to build. PNG for every mode but ``"CMYK"``, which PNG
    cannot carry: that one is a 1x1 CMYK TIFF from Pillow with its
    ``ImageWidth``/``ImageLength`` tags rewritten. Decoding either fails;
    use it only where the code under test must refuse before decoding.
    """
    if mode == "CMYK":
        buf = io.BytesIO()
        Image.new("CMYK", (1, 1)).save(buf, "TIFF")
        data = bytearray(buf.getvalue())
        (ifd,) = struct.unpack_from("<I", data, 4)
        (entries,) = struct.unpack_from("<H", data, ifd)
        for index in range(entries):
            at = ifd + 2 + 12 * index
            (tag,) = struct.unpack_from("<H", data, at)
            if tag in (256, 257):  # ImageWidth, ImageLength: rewritten as one LONG
                struct.pack_into("<HHII", data, at, tag, 4, 1, width if tag == 256 else height)
        return bytes(data)
    depth, colour_type = _PNG_MODES[mode]
    header = struct.pack(">IIBBBBB", width, height, depth, colour_type, 0, 0, 0)
    palette = _png_chunk(b"PLTE", b"\xff\xff\xff") if mode == "P" else b""
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + palette
        + _png_chunk(b"IDAT", zlib.compress(b""))
        + _png_chunk(b"IEND", b"")
    )


def bilevel_png(width: int, height: int, *, mark: tuple[int, int, int, int] | None = None) -> bytes:
    """A real 1-bit PNG, white with an optional black ``mark`` (left, top, right, bottom).

    #256: built row by row, so the test never holds the image -- a 1200 dpi
    A4 office scan (9921 x 14031, 139 Mpx) is ~40 KB of file and well under
    1 MB to build, where ``Image.new("1", ...)`` would allocate 139 MB
    (Pillow keeps mode ``"1"`` at one byte per pixel).
    """
    stride = -(-width // 8)
    white = b"\x00" + b"\xff" * stride  # filter byte 0, then set bits = white
    marked = white
    if mark is not None:
        bits = bytearray(b"\xff" * stride)
        for x in range(mark[0], mark[2]):
            bits[x >> 3] &= ~(0x80 >> (x & 7)) & 0xFF
        marked = b"\x00" + bytes(bits)
    compressor = zlib.compressobj(9)
    idat = bytearray()
    for y in range(height):
        in_mark = mark is not None and mark[1] <= y < mark[3]
        idat += compressor.compress(marked if in_mark else white)
    idat += compressor.flush()
    header = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", bytes(idat))
        + _png_chunk(b"IEND", b"")
    )


def plain_webp(width: int, height: int) -> bytes:
    """A real, white, lossless WebP -- a few dozen bytes at any size.

    #256 review round 2: WebP decodes at about three times a PNG's cost, so
    it has its own lower pixel cap; this builds files either side of it.
    """
    buf = io.BytesIO()
    Image.new("L", (width, height), 255).save(buf, "WEBP", lossless=True, method=0)
    return buf.getvalue()


def ico_wrapping(payload: bytes) -> bytes:
    """An ICO whose one entry declares 16x16 and holds ``payload`` (e.g. a big PNG).

    #256 review: Pillow's ICO plugin decodes the embedded image inside
    ``Image.open``, before any pixel cap can run -- the file is as small as
    its payload, and the decode as large as the payload declares.
    """
    directory = struct.pack("<HHH", 0, 1, 1)  # reserved, type 1 (icon), one entry
    entry = struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 32, len(payload), 6 + 16)
    return directory + entry + payload


__all__ = [
    "annot_ap_bomb_pdf",
    "annot_ap_image_bomb_pdf",
    "annot_ap_nested_bomb_pdf",
    "assemble_pdf",
    "bare_encrypt_dict_pdf",
    "bilevel_png",
    "bomb_on_second_page_pdf",
    "born_digital_text_pdf",
    "contents_also_appearance_bomb_pdf",
    "declared_image",
    "deep_page_chain_pdf",
    "deep_plain_dict_chain_bomb_pdf",
    "deep_xobject_chain_bomb_pdf",
    "embedded_font_pdf",
    "empty_page_tree_pdf",
    "empty_pages_nodes_pdf",
    "encrypted_pdf_bytes",
    "extgstate_smask_bomb_pdf",
    "filtered_page_pdf",
    "flate_bomb_ops",
    "form_also_graphics_state_bomb_pdf",
    "form_xobject_cycle_pdf",
    "hidden_layer_pdf",
    "ico_wrapping",
    "image_bomb_pdf",
    "indirect_ap_state_bomb_pdf",
    "indirect_filter_page_pdf",
    "indirect_smask_dimension_bomb_pdf",
    "indirect_subtype_form_bomb_pdf",
    "indirect_xobject_dict_bomb_pdf",
    "inherited_resources_bomb_pdf",
    "links_to_sibling_pages_pdf",
    "long_parent_chain_pdf",
    "many_form_xobjects_pdf",
    "many_objects_pdf",
    "non_stream_contents_pdf",
    "off_page_object_pdf",
    "overstated_count_pdf",
    "page_bomb_pdf",
    "page_kids_bomb_pdf",
    "page_kids_equal_count_bomb_pdf",
    "page_tree_poison_pdf",
    "pages_carrying_kids_pdf",
    "parent_poisoned_ap_state_bomb_pdf",
    "pdf_stream",
    "pdf_with_inflated_count",
    "pdf_with_missing_kid_object",
    "plain_webp",
    "real_smask_dimension_bomb_pdf",
    "repeated_kid_pdf",
    "repeated_subtree_pdf",
    "repeated_xobject_pdf",
    "resources_entry_pointing_at_pages_node_pdf",
    "seeded_page_tree_bomb_pdf",
    "shared_container_broken_xref_pdf",
    "sibling_page_as_soft_mask_bomb_pdf",
    "sibling_page_listed_as_annotation_pdf",
    "smask_bomb_pdf",
    "stamp_with_jpeg_appearance_pdf",
    "stream_extgstate_smask_bomb_pdf",
    "tiling_pattern_bomb_pdf",
    "tiling_pattern_image_bomb_pdf",
    "tree_node_ap_state_bomb_pdf",
    "type3_charproc_bomb_pdf",
    "type3_stream_font_bomb_pdf",
    "typed_form_xobject_bomb_pdf",
    "uncounted_bomb_pdf",
    "wide_page_tree_pdf",
    "wrapped_page_tree_pdf",
    "xobject_also_listed_as_annotation_bomb_pdf",
    "xobject_bomb_pdf",
    "xref_repair_bomb_pdf",
]
