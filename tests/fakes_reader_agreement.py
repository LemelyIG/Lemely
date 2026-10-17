"""Builders for the marker/teacher agreement tests, and the scan images #275 turns on.

The marker reads pdfium's render of the canonical rewrite
(:func:`lemely.io.pdf_canonical.canonical_pdf_bytes`); the teacher's preview
is MuPDF's render of the stored file. These builders make small synthetic
files on which the two could disagree -- optional content hidden by default
(#274), a filled form field -- and the helpers render a page with either
reader to one byte per pixel ("L"), so a test can count dark pixels or
compare two renders byte for byte. The image builders at the end (#275)
make TIFFs whose stored frame is turned by an orientation tag. Generated
in-test; nothing is committed.
"""

from __future__ import annotations

import io
import struct
from typing import Literal

import pymupdf
import pypdfium2 as pdfium
from PIL import Image, ImageOps

from tests.pdf_fakes import assemble_pdf, flate_bomb_ops, pdf_stream

#: A grey value below this counts as dark (ink) in :func:`dark_pixels`.
DARK_BELOW = 128

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def dark_pixels(png_or_grey: bytes, size: tuple[int, int]) -> int:
    """How many pixels of a ``size`` (width, height) image are dark.

    ``png_or_grey``: PNG bytes (converted to "L"; its size must be ``size``)
    or raw "L" bytes, one per pixel, as :func:`mupdf_grey` and
    :func:`pdfium_grey` return.
    """
    if png_or_grey.startswith(_PNG_MAGIC):
        with Image.open(io.BytesIO(png_or_grey)) as image:
            if image.size != size:
                raise ValueError(f"PNG is {image.size}, expected {size}")
            grey = image.convert("L").tobytes()
    else:
        grey = png_or_grey
    if len(grey) != size[0] * size[1]:
        raise ValueError(f"{len(grey)} grey bytes for a {size} image")
    return sum(1 for value in grey if value < DARK_BELOW)


def mupdf_grey(data: bytes, page: int, *, zoom: float) -> bytes:
    """MuPDF's render of page ``page`` of ``data`` at ``zoom``, as "L" bytes.

    The teacher's view: MuPDF draws the stored file. The size is
    :func:`mupdf_size` of the same arguments.
    """
    with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        pixmap = doc[page].get_pixmap(
            matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False
        )
        return bytes(pixmap.samples)


def mupdf_size(data: bytes, page: int, *, zoom: float) -> tuple[int, int]:
    """The (width, height) of :func:`mupdf_grey`'s render of the same page."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        pixmap = doc[page].get_pixmap(
            matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False
        )
        return (pixmap.width, pixmap.height)


def pdfium_grey(data: bytes, page: int, *, scale: float) -> bytes:
    """pdfium's render of page ``page`` of ``data`` at ``scale``, as "L" bytes.

    The marker's view when ``data`` is the canonical rewrite. The size is
    :func:`pdfium_size` of the same arguments.
    """
    pdf = pdfium.PdfDocument(data)
    try:
        loaded = pdf[page]
        try:
            bitmap = loaded.render(scale=scale)
            try:
                return bitmap.to_pil().convert("L").tobytes()
            finally:
                bitmap.close()
        finally:
            loaded.close()
    finally:
        pdf.close()


def pdfium_size(data: bytes, page: int, *, scale: float) -> tuple[int, int]:
    """The (width, height) of :func:`pdfium_grey`'s render of the same page."""
    pdf = pdfium.PdfDocument(data)
    try:
        loaded = pdf[page]
        try:
            bitmap = loaded.render(scale=scale)
            try:
                return (bitmap.width, bitmap.height)
            finally:
                bitmap.close()
        finally:
            loaded.close()
    finally:
        pdf.close()


def differing_bytes(first: bytes, second: bytes) -> int:
    """How many positions two equal-length grey renders differ at."""
    if len(first) != len(second):
        raise ValueError(f"renders differ in size: {len(first)} vs {len(second)} bytes")
    return sum(a != b for a, b in zip(first, second, strict=True))


def visible_layer_text_pdf() -> bytes:
    """:func:`tests.pdf_fakes.hidden_layer_pdf` with only its visible layer.

    The same A4 page and the same ``VISIBLE LAYER TEXT`` on an ON layer, and
    nothing hidden: what the marker should see of either variant.
    """
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=595, height=842)
        shown = doc.add_ocg("visible", on=True)
        page.insert_text((50, 100), "VISIBLE LAYER TEXT", fontsize=30, oc=shown)
        data: bytes = doc.tobytes()
    finally:
        doc.close()
    return data


def filled_text_field_pdf(value: str = "42") -> bytes:
    """One A4 page with a text form field whose value is ``value``.

    The widget's appearance draws the value (MuPDF: 1,578 dark pixels in the
    probe), so a student's typed answer is ink both readers must show.
    """
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=595, height=842)
        widget = pymupdf.Widget()  # type: ignore[no-untyped-call]
        widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        widget.field_name = "answer"
        widget.field_value = value
        widget.rect = pymupdf.Rect(100, 100, 300, 140)
        widget.text_fontsize = 24
        page.add_widget(widget)
        widget.update()
        data: bytes = doc.tobytes()
    finally:
        doc.close()
    return data


def oc_hidden_bomb_pdf(inflated_bytes: int) -> bytes:
    """:func:`tests.pdf_fakes.xobject_bomb_pdf`, with the bomb on a hidden layer.

    The page draws ``/Fm1``, a Form XObject whose content inflates to
    ``inflated_bytes`` and whose ``/OC`` (object 6) is an optional-content
    group listed in the catalog's ``/OCProperties /D /OFF``. Hidden is not
    harmless: pdfium parses what it may not draw, so the content walk must
    still refuse it, before the rewrite prunes anything.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R"
            b" /OCProperties << /OCGs [6 0 R] /D << /OFF [6 0 R] >> >> >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
            b" /Resources << /XObject << /Fm1 5 0 R >> >> >>",
            pdf_stream(b"", b"q /Fm1 Do Q"),
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 595 842] /Filter /FlateDecode "
                b"/OC 6 0 R /Resources << /XObject << /Fm2 5 0 R >> >>",
                flate_bomb_ops(inflated_bytes),
            ),
            b"<< /Type /OCG /Name (hidden) >>",
        ]
    )


#: Where :func:`optional_content_square_pdf` draws its black square, in
#: points from the top-left: a whole number of pixels at scale 0.5, so both
#: readers fill the same pixels.
OCMD_IMAGE_RECT = (100, 400, 300, 600)

#: The object number :func:`optional_content_square_pdf` gives the first of
#: the caller's ``objects``.
FIRST_EXTRA_OBJECT = 7


def refs(numbers: list[int]) -> bytes:
    """A PDF array of indirect references to ``numbers``."""
    return b"[" + b" ".join(b"%d 0 R" % n for n in numbers) + b"]"


def optional_content_square_pdf(
    oc: bytes, objects: list[bytes], *, properties: bytes, annotation: bool = False
) -> bytes:
    """One A4 page drawing one black square whose ``/OC`` value is ``oc``.

    The square is an image XObject (``/Im1``), or with ``annotation`` a
    Square annotation's appearance, and ``oc`` is that object's ``/OC``.
    ``properties`` is the catalog's ``/OCProperties`` value (empty bytes for
    none). ``objects`` are numbered from :data:`FIRST_EXTRA_OBJECT` up: the
    groups and membership dictionaries ``oc`` and ``properties`` refer to.
    Nothing else is drawn, so the page has dark pixels exactly when the
    reader shows the square.

    pdfium honours an image's ``/OC`` itself but draws an annotation
    whatever its ``/OC`` says, so the annotation is the case only the
    rewrite's prune can hide.
    """
    left, top, right, bottom = OCMD_IMAGE_RECT
    # PDF y runs up from the bottom of the 842-point page.
    x0, y0, x1, y1 = left, 842 - bottom, right, 842 - top
    if annotation:
        page = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
            b" /Annots [5 0 R] >>"
        )
        contents = pdf_stream(b"", b"")
        square = (
            b"<< /Type /Annot /Subtype /Square /Rect [%d %d %d %d] /F 4 /OC " % (x0, y0, x1, y1)
            + oc
            + b" /AP << /N 6 0 R >> >>"
        )
    else:
        page = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
            b" /Resources << /XObject << /Im1 5 0 R >> >> >>"
        )
        contents = pdf_stream(b"", b"q %d 0 0 %d %d %d cm /Im1 Do Q" % (x1 - x0, y1 - y0, x0, y0))
        square = pdf_stream(
            b"/Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceGray"
            b" /BitsPerComponent 8 /OC " + oc,
            b"\x00\x00\x00\x00",
        )
    catalog = b"<< /Type /Catalog /Pages 2 0 R"
    if properties:
        catalog += b" /OCProperties " + properties
    return assemble_pdf(
        [
            catalog + b" >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            page,
            contents,
            square,
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [%d %d %d %d]" % (x0, y0, x1, y1),
                b"0 g %d %d %d %d re f" % (x0, y0, x1 - x0, y1 - y0),
            ),
            *objects,
        ]
    )


def ocmd_image_pdf(
    policy: str,
    states: tuple[bool, ...],
    *,
    base_state_off: bool = False,
    annotation: bool = False,
    single: bool = False,
    visibility_expression: bool = False,
) -> bytes:
    """One A4 page drawing one black square governed by an ``/OCMD``.

    The square's ``/OC`` is an optional-content membership dictionary
    (object 7) with ``/P /<policy>`` (no ``/P`` when ``policy`` is empty)
    over ``len(states)`` groups; group ``i`` is ON by default when
    ``states[i]`` is true. The catalog lists the groups in ``/OCProperties
    /D /ON`` and ``/OFF``; with ``base_state_off`` it writes ``/BaseState
    /OFF`` and lists only the ON groups (in ``/ON``), so the OFF ones are off
    by the base state alone. With ``single`` the dictionary's ``/OCGs`` is a
    single reference to the one group rather than an array; with
    ``visibility_expression`` it also carries ``/VE [/Not <group 0>]``.
    ``annotation``: see :func:`optional_content_square_pdf`.
    """
    if single and len(states) != 1:
        raise ValueError("a single /OCGs reference names one group")
    groups = [FIRST_EXTRA_OBJECT + 1 + i for i in range(len(states))]
    on = [g for g, state in zip(groups, states, strict=True) if state]
    off = [g for g, state in zip(groups, states, strict=True) if not state]
    if base_state_off:
        default = b"<< /BaseState /OFF /ON " + refs(on) + b" >>"
    else:
        default = b"<< /ON " + refs(on) + b" /OFF " + refs(off) + b" >>"
    members = b"%d 0 R" % groups[0] if single else refs(groups)
    ocmd = b"<< /Type /OCMD /OCGs " + members
    if policy:
        ocmd += b" /P /" + policy.encode()
    if visibility_expression:
        ocmd += b" /VE [/Not %d 0 R]" % groups[0]
    return optional_content_square_pdf(
        b"%d 0 R" % FIRST_EXTRA_OBJECT,
        [ocmd + b" >>", *(b"<< /Type /OCG /Name (group %d) >>" % i for i in range(len(states)))],
        properties=b"<< /OCGs " + refs(groups) + b" /D " + default + b" >>",
        annotation=annotation,
    )


def oc_annotation_flood_pdf(annotations: int, groups: int) -> bytes:
    """One page whose ``/Annots`` names one annotation ``annotations`` times,
    governed by an ``/OCMD`` naming one ON group ``groups`` times.

    The reviewer's amplification probe (#274): 49 KB at 4,000 by 4,000, and
    judging each annotation by walking the whole membership array cost
    16 million steps.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R"
            b" /OCProperties << /OCGs [7 0 R] /D << /ON [7 0 R] >> >> >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Annots "
            + b"["
            + b"5 0 R " * annotations
            + b"] >>",
            pdf_stream(b"", b""),
            b"<< /Type /Annot /Subtype /Square /Rect [0 0 10 10] /OC 6 0 R >>",
            b"<< /Type /OCMD /OCGs [" + b"7 0 R " * groups + b"] /P /AnyOn >>",
            b"<< /Type /OCG /Name (g) >>",
        ]
    )


def with_all_on_optional_content(data: bytes) -> bytes:
    """``data`` with one ON optional-content group governing everything.

    Adds ``/OCProperties`` naming one group that is ON by default, and sets
    that group as the ``/OC`` of every XObject in each page's resources and
    of every annotation, so the rewrite's prune judges each of them -- and
    must keep them all.
    """
    with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        group = doc.add_ocg("everything", on=True)
        for page in doc:
            xobjects = {item[0] for item in page.get_images()}
            xobjects |= {item[0] for item in page.get_xobjects()}
            annotations = {annot.xref for annot in page.annots()}
            annotations |= {widget.xref for widget in page.widgets()}
            for xref in xobjects | annotations:
                doc.xref_set_key(xref, "OC", f"{group} 0 R")
        out: bytes = doc.tobytes()
    return out


def ocmd_cycle_pdf(*, governed_by_b_first: bool) -> bytes:
    """Two membership dictionaries that name each other (the reviewer's probe).

    A (object 6) is ``/AllOff [B]``; B (object 7) is ``/AnyOn [A g]``, with
    group g (object 8) OFF. Annotation X (object 5) has ``/OC A`` and Y
    (object 9) ``/OC B``; ``/Annots`` lists Y first when
    ``governed_by_b_first``, else X. The spec allows no membership
    dictionary inside another, and a cycle makes the answer depend on where
    the walk starts, so the file is refused either way.
    """

    def square(x0: int) -> bytes:
        return pdf_stream(
            b"/Type /XObject /Subtype /Form /BBox [%d 500 %d 600]" % (x0, x0 + 100),
            b"0 g %d 500 100 100 re f" % x0,
        )

    order = b"[9 0 R 5 0 R]" if governed_by_b_first else b"[5 0 R 9 0 R]"
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R"
            b" /OCProperties << /OCGs [8 0 R] /D << /OFF [8 0 R] >> >> >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Annots "
            + order
            + b" >>",
            pdf_stream(b"", b""),
            b"<< /Type /Annot /Subtype /Square /Rect [100 500 200 600] /F 4 /OC 6 0 R"
            b" /AP << /N 10 0 R >> >>",
            b"<< /Type /OCMD /OCGs [7 0 R] /P /AllOff >>",
            b"<< /Type /OCMD /OCGs [6 0 R 8 0 R] /P /AnyOn >>",
            b"<< /Type /OCG /Name (g) >>",
            b"<< /Type /Annot /Subtype /Square /Rect [300 500 400 600] /F 4 /OC 7 0 R"
            b" /AP << /N 11 0 R >> >>",
            square(100),
            square(300),
        ]
    )


def direct_ocmd_annotations_pdf(annotations: int, members: int) -> bytes:
    """One page with ``annotations`` distinct annotations, each governed by its
    own direct ``/OCMD`` naming the one listed (ON) group ``members`` times.

    A direct ``/OC`` has no object number to judge it once by, so each
    annotation's membership array is read again: the work is
    ``annotations * members`` member visits.
    """
    group = 5 + annotations
    ocmd = b"<< /Type /OCMD /OCGs [" + b"%d 0 R " % group * members + b"] >>"
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R"
            b" /OCProperties << /OCGs [%d 0 R] /D << /ON [%d 0 R] >> >> >>" % (group, group),
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Annots ["
            + b" ".join(b"%d 0 R" % (5 + i) for i in range(annotations))
            + b"] >>",
            pdf_stream(b"", b""),
            *[b"<< /Type /Annot /Subtype /Square /Rect [0 0 10 10] /OC " + ocmd + b" >>"]
            * annotations,
            b"<< /Type /OCG /Name (g) >>",
        ]
    )


def shared_resources_pdf(pages: int, xobjects: int) -> bytes:
    """``pages`` pages sharing one ``/Resources`` dictionary whose ``/XObject``
    dictionary names one image ``xobjects`` times, the image on an ON group.

    Judging the shared dictionary again on every page would cost
    ``pages * xobjects`` visits; once, ``xobjects``.
    """
    first_page = 7
    kids = b" ".join(b"%d 0 R" % (first_page + i) for i in range(pages))
    names = b" ".join(b"/Im%d 5 0 R" % i for i in range(xobjects))
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R"
            b" /OCProperties << /OCGs [6 0 R] /D << /ON [6 0 R] >> >> >>",
            b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % pages,
            b"<< /XObject << " + names + b" >> >>",
            pdf_stream(b"", b"q 10 0 0 10 0 0 cm /Im0 Do Q"),
            pdf_stream(
                b"/Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray"
                b" /BitsPerComponent 8 /OC 6 0 R",
                b"\x00",
            ),
            b"<< /Type /OCG /Name (g) >>",
            *[
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
                b" /Resources 3 0 R >>"
            ]
            * pages,
        ]
    )


#: The paper and ink samples :func:`oriented_tiff` writes, per mode: white
#: paper and black ink in "L" and "1"; for "I;16", the 16-bit values
#: ``tests.pdf_fakes.sixteen_bit_grey_scan`` uses.
_TIFF_PAPER_AND_INK = {"L": (255, 0), "1": (1, 0), "I;16": (60_000, 5_000)}

#: The TIFF tag that says how the stored frame is turned (EXIF's, 274).
_TIFF_ORIENTATION = 274

#: The TIFF tag for rows per strip (278): the height makes one strip.
_TIFF_ROWS_PER_STRIP = 278


def oriented_tiff(
    mode: Literal["L", "I;16", "1"],
    size: tuple[int, int],
    orientation: int,
    *,
    compression: Literal["raw", "tiff_lzw"],
    mark: tuple[int, int, int, int],
) -> bytes:
    """A TIFF whose stored frame is ``size`` with a dark ``mark`` box, tagged ``orientation``.

    ``mark`` is (left, top, right, bottom) in the STORED frame, in pixels.
    The ``Orientation`` tag (274) says how to turn that frame upright, as a
    scanner or phone writes it. ``raw`` is written as ONE strip (rows per
    strip = the height): the layout whose single tile Pillow memory-maps
    when it opens the file by name (#275). ``tiff_lzw`` goes through
    libtiff. The "I;16" image is built from raw little-endian samples,
    since Pillow's ``paste`` of an integer into an "I;16" image does not
    store the value given.
    """
    paper, ink = _TIFF_PAPER_AND_INK[mode]
    width, height = size
    left, top, right, bottom = mark
    if mode == "I;16":
        paper_sample, ink_sample = struct.pack("<H", paper), struct.pack("<H", ink)
        plain_row = paper_sample * width
        ink_row = paper_sample * left + ink_sample * (right - left) + paper_sample * (width - right)
        rows = (ink_row if top <= y < bottom else plain_row for y in range(height))
        image = Image.frombytes("I;16", size, b"".join(rows))
    else:
        image = Image.new(mode, size, paper)
        image.paste(ink, mark)
    buf = io.BytesIO()
    image.save(
        buf,
        format="TIFF",
        compression=compression,
        tiffinfo={_TIFF_ORIENTATION: orientation, _TIFF_ROWS_PER_STRIP: height},
    )
    return buf.getvalue()


#: Each mode's raw sample layout, as ``Image.frombytes`` reads it by default:
#: "I;16" is little-endian, "I" and "F" are native.
_WIDE_SAMPLE_FORMATS = {"I;16": "<H", "I": "=i", "F": "=f"}


def wide_grey_scan(
    mode: Literal["I;16", "I", "F"],
    size: tuple[int, int],
    paper: float,
    ink: float,
    box: tuple[int, int, int, int],
    *,
    image_format: Literal["PNG", "TIFF"],
    spot: tuple[tuple[int, int], float] | None = None,
) -> bytes:
    """A single-channel scan wider than a byte: ``paper`` samples with an ``ink`` box.

    ``spot``: ``((x, y), value)``, one sample overwritten after the box is
    drawn -- an overshoot past 1.0 or an infinity in a float page.

    Generalises ``tests.pdf_fakes.sixteen_bit_grey_scan`` to any sample
    values and to the 32-bit modes, so a test can put 8- or 12-bit samples
    in a 16-bit container (#275). ``box`` is (left, top, right, bottom) in
    pixels. Built from raw samples, since Pillow's ``paste``
    of a number into an "I;16" image does not store the value given. "F"
    is written only as TIFF: PNG has no floating-point samples.
    """
    if mode == "F" and image_format != "TIFF":
        raise ValueError("PNG has no floating-point samples; write 'F' as TIFF")
    sample = _WIDE_SAMPLE_FORMATS[mode]
    value = float if mode == "F" else int
    paper_sample = struct.pack(sample, value(paper))
    ink_sample = struct.pack(sample, value(ink))
    width, height = size
    left, top, right, bottom = box
    plain_row = paper_sample * width
    ink_row = paper_sample * left + ink_sample * (right - left) + paper_sample * (width - right)
    rows = (ink_row if top <= y < bottom else plain_row for y in range(height))
    samples = bytearray(b"".join(rows))
    if spot is not None:
        (x, y), spot_value = spot
        sample_bytes = len(paper_sample)
        at = (y * width + x) * sample_bytes
        samples[at : at + sample_bytes] = struct.pack(sample, value(spot_value))
    image = Image.frombytes(mode, size, bytes(samples))
    buf = io.BytesIO()
    image.save(buf, format=image_format)
    return buf.getvalue()


def expected_upright(stored: bytes) -> Image.Image:
    """The upright frame of an image file: Pillow's ``exif_transpose`` of an in-memory open.

    The reference the TIFF orientation tests compare against. Opened from a
    ``BytesIO``, so Pillow never memory-maps it (#275).
    """
    with Image.open(io.BytesIO(stored)) as opened:
        return ImageOps.exif_transpose(opened)
