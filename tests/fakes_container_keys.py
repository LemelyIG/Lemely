"""Containers whose keys are arbitrary names a renderer dereferences to draw.

A Type3 font's ``/CharProcs`` maps glyph names to glyph procedures, and an
annotation's appearance-state dict maps ``/AS`` names to appearance streams.
A renderer looks a glyph or a state up by name, so the name can be any key,
including ones the content walk treats specially (``/PieceInfo``,
``/Metadata``, ``/Resources``). Each builder here hides one Flate stream that
inflates to ``inflated_bytes`` behind such a key, where a renderer draws it.
"""

from __future__ import annotations

from tests.pdf_fakes import assemble_pdf, flate_bomb_ops, pdf_stream

_CATALOG_AND_PAGES = [
    b"<< /Type /Catalog /Pages 2 0 R >>",
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
]
_FORM = b"/Type /XObject /Subtype /Form /BBox [0 0 200 200]"


def _type3_font(glyph: bytes, charprocs_ref: bytes) -> bytes:
    """A Type3 font drawing character 65 with the glyph named ``glyph``."""
    return (
        b"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 1000 1000] "
        b"/FontMatrix [0.001 0 0 0.001 0 0] /CharProcs " + charprocs_ref + b" "
        b"/Encoding << /Type /Encoding /Differences [65 /" + glyph + b"] >> "
        b"/FirstChar 65 /LastChar 65 /Widths [1000] >>"
    )


def type3_glyph_named_pdf(glyph: bytes, inflated_bytes: int) -> bytes:
    """One page drawing ``A`` in a Type3 font whose only glyph is named ``glyph``.

    ``/CharProcs`` is its own plain dict (object 6), ``<< /<glyph> 7 0 R >>``;
    object 7 is the glyph procedure, a Flate stream inflating to
    ``inflated_bytes``.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            pdf_stream(b"", b"BT /F1 12 Tf 100 100 Td (A) Tj ET"),
            _type3_font(glyph, b"6 0 R"),
            b"<< /" + glyph + b" 7 0 R >>",
            pdf_stream(b"/Filter /FlateDecode", flate_bomb_ops(inflated_bytes)),
        ]
    )


def type3_charprocs_is_drawn_form_pdf(inflated_bytes: int, *, form_first: bool = False) -> bytes:
    """``/CharProcs`` is a Form XObject the page also draws (``/Fig Do``).

    The form's ``/PieceInfo`` key is the glyph named ``/PieceInfo``, which
    names object 7, a Flate stream inflating to ``inflated_bytes``. Drawn
    as a form, ``/PieceInfo`` is page-piece data; read as ``/CharProcs``, it
    is the glyph a renderer runs.

    By default the page's ``/Resources`` names the font, so the walk can
    meet the form as ``/CharProcs`` before it meets it under ``/XObject``.
    ``form_first=True`` moves the font into an annotation's appearance
    stream (object 8), which the walk reads after the page's resources, so
    the form is always met under ``/XObject`` first.
    """
    if form_first:
        page = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /XObject << /Fig 6 0 R >> >> /Annots [9 0 R] >>"
        )
        contents = b"q /Fig Do Q"
    else:
        page = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> /XObject << /Fig 6 0 R >> >> >>"
        )
        contents = b"q /Fig Do Q BT /F1 12 Tf 100 100 Td (A) Tj ET"
    objects = [
        *_CATALOG_AND_PAGES,
        page,
        pdf_stream(b"", contents),
        _type3_font(b"PieceInfo", b"6 0 R"),
        pdf_stream(_FORM + b" /PieceInfo 7 0 R", b"q 0 0 1 rg 10 10 100 100 re f Q"),
        pdf_stream(b"/Filter /FlateDecode", flate_bomb_ops(inflated_bytes)),
    ]
    if form_first:
        objects += [
            pdf_stream(
                b"/Type /XObject /Subtype /Form /BBox [0 0 300 300] "
                b"/Resources << /Font << /F1 5 0 R >> >>",
                b"BT /F1 12 Tf 100 100 Td (A) Tj ET",
            ),
            b"<< /Type /Annot /Subtype /Square /Rect [10 10 300 300] /F 4 /AP << /N 8 0 R >> >>",
        ]
    return assemble_pdf(objects)


def appearance_state_named_pdf(state: bytes, inflated_bytes: int) -> bytes:
    """A Square annotation whose selected appearance state is named ``state``.

    ``/AS /<state>``; ``/AP << /N 6 0 R >>``, object 6 being the state dict
    ``<< /<state> 7 0 R /Off 8 0 R >>``. Object 7 is a Form XObject whose
    content inflates to ``inflated_bytes``.
    """
    return assemble_pdf(
        [
            *_CATALOG_AND_PAGES,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Annots [5 0 R] >>",
            pdf_stream(b"", b"q Q"),
            b"<< /Type /Annot /Subtype /Square /Rect [10 10 300 300] /F 4 "
            b"/AS /" + state + b" /AP << /N 6 0 R >> >>",
            b"<< /" + state + b" 7 0 R /Off 8 0 R >>",
            pdf_stream(_FORM + b" /Filter /FlateDecode", flate_bomb_ops(inflated_bytes)),
            pdf_stream(_FORM, b"q Q"),
        ]
    )
