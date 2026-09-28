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


def tiling_pattern_bomb_pdf(inflated_bytes: int, *, type_name: str = "Pattern") -> bytes:
    """A page painted with a tiling pattern whose own stream carries the bomb.

    Fix round 1, Important 2(b). ``type_name`` is the pattern's ``/Type``:
    a renderer finds a pattern by its ``/PatternType`` and ignores ``/Type``,
    so a pattern that calls itself ``/Font`` is drawn all the same (fix
    round 4).
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

    Fix round 4: ``name`` is the author-chosen resource name the form is
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
    selected state (``/AS``). Fix round 4: ``state`` is that state's
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

    Fix round 4: ``gs_type`` is the graphics state's ``/Type``, which a
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

    Fix round 4, Critical 2: a renderer draws an XObject by its ``/Subtype``
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

    Fix round 4, Important 1: ``page.get_images(full=True)`` lists images
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

    Fix round 4, Important 1: as :func:`annot_ap_image_bomb_pdf`, but the
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

    Fix round 4: ``/Resources`` is inheritable (ISO 32000-1 Table 30) and
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


def page_chain_smask_bomb_pdf(inflated_bytes: int) -> bytes:
    """Two sibling pages chained as page 0's graphics state and soft mask.

    Page 0's ``/ExtGState /GS1`` is page 1 (object 5), which also carries
    ``/SMask 6 0 R``; page 2 (object 6) also carries ``/S /Luminosity
    /G 7 0 R``, and object 7 is a Form XObject bomb. A walk that expands a
    tree node one level but not the tree nodes it names misses the bomb.
    """
    page = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 5 0 R 6 0 R] /Count 3 >>",
            page + b" /Resources << /ExtGState << /GS1 5 0 R >> >> >>",
            pdf_stream(b"", b"/GS1 gs q Q"),
            page + b" /SMask 6 0 R >>",
            page + b" /S /Luminosity /G 7 0 R >>",
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

    Fix round 4: a font program is parsed by the font engine, not executed
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


__all__ = [
    "annot_ap_bomb_pdf",
    "annot_ap_image_bomb_pdf",
    "annot_ap_nested_bomb_pdf",
    "assemble_pdf",
    "born_digital_text_pdf",
    "deep_plain_dict_chain_bomb_pdf",
    "deep_xobject_chain_bomb_pdf",
    "embedded_font_pdf",
    "encrypted_pdf_bytes",
    "extgstate_smask_bomb_pdf",
    "filtered_page_pdf",
    "flate_bomb_ops",
    "form_xobject_cycle_pdf",
    "image_bomb_pdf",
    "indirect_ap_state_bomb_pdf",
    "indirect_filter_page_pdf",
    "indirect_smask_dimension_bomb_pdf",
    "indirect_subtype_form_bomb_pdf",
    "indirect_xobject_dict_bomb_pdf",
    "inherited_resources_bomb_pdf",
    "links_to_sibling_pages_pdf",
    "many_form_xobjects_pdf",
    "page_bomb_pdf",
    "page_chain_smask_bomb_pdf",
    "page_tree_poison_pdf",
    "parent_poisoned_ap_state_bomb_pdf",
    "pdf_stream",
    "pdf_with_inflated_count",
    "pdf_with_missing_kid_object",
    "real_smask_dimension_bomb_pdf",
    "repeated_xobject_pdf",
    "resources_entry_pointing_at_pages_node_pdf",
    "smask_bomb_pdf",
    "tiling_pattern_bomb_pdf",
    "tiling_pattern_image_bomb_pdf",
    "tree_node_ap_state_bomb_pdf",
    "type3_charproc_bomb_pdf",
    "typed_form_xobject_bomb_pdf",
    "xobject_bomb_pdf",
]
