"""A pdfTeX-shaped PDF: an included figure carrying Illustrator's private data (#261).

pdfTeX copies a figure's page into a Form XObject along with the page's
``/PieceInfo``, where Illustrator files its round-trip data as two large
Flate streams. No renderer draws a page-piece dictionary, so the content
walk must not count it.
"""

from __future__ import annotations

from tests.pdf_fakes import assemble_pdf, flate_bomb_ops, pdf_stream

_FORM_CONTENT = b"q 0 0 1 rg 10 10 100 100 re f Q"


def pdftex_included_figure_pdf(
    private_bytes: int,
    pages: int,
    *,
    draw_private: bool = False,
    private_names_page_tree: bool = False,
) -> bytes:
    """``pages`` pages that each draw one Form XObject (``/Fig Do``).

    The form's dictionary carries an Illustrator-shaped ``/PieceInfo`` whose
    ``/Private`` names two Flate streams (objects 4 and 5) that each inflate
    to ``private_bytes``. ``draw_private`` also lists the first one under
    the form's ``/Resources /XObject``, so it is reachable through a drawn
    key. ``private_names_page_tree`` adds a reference from ``/Private`` to
    the ``/Pages`` root (object 2).
    """
    private_entries = b"/AIPrivateData1 4 0 R /AIPrivateData2 5 0 R"
    if private_names_page_tree:
        private_entries += b" /PageTree 2 0 R"
    resources = b" /Resources << /XObject << /AIPrivateData1 4 0 R >> >>" if draw_private else b""
    form = pdf_stream(
        b"/Type /XObject /Subtype /Form /BBox [0 0 200 200] "
        b"/PieceInfo << /Illustrator << /Private << " + private_entries + b" >> "
        b"/LastModified (D:20260101000000) >> >>" + resources,
        _FORM_CONTENT,
    )
    private = pdf_stream(b"/Filter /FlateDecode", flate_bomb_ops(private_bytes))
    first_page = 7
    kids = b" ".join(f"{first_page + index} 0 R".encode() for index in range(pages))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids + f"] /Count {pages} >>".encode(),
        form,
        private,
        private,
        pdf_stream(b"", b"q /Fig Do Q"),
    ]
    objects.extend(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 6 0 R "
        b"/Resources << /XObject << /Fig 3 0 R >> >> >>"
        for _ in range(pages)
    )
    return assemble_pdf(objects)
