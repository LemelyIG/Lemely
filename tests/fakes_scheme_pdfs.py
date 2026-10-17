"""Synthetic CAIE-style mark-scheme PDFs, and a pdfplumber bomb, for the scheme worker (#260).

Built in-test with PyMuPDF; nothing committed, no real paper's content. The
scheme is laid out as the deterministic parser expects of a 0625 theory
scheme: a cover page naming the paper, its session and ``Maximum Mark``, a
Generic Marking Principles page, then ruled ``Question | Answer | Marks``
tables, every point ``B1``, so the parsed total reconciles with the cover.
"""

from __future__ import annotations

import zlib

import pymupdf

from tests.pdf_fakes import assemble_pdf, pdf_stream

_A4 = (595, 842)
#: x of the table's four rules: question, answer and marks columns.
_COLUMNS = (40, 120, 470, 555)
_ROW_HEIGHT = 24
_ROWS_PER_PAGE = 12
_RUNNING_HEADER = "0625/41 Cambridge IGCSE - Mark Scheme May/June 2023"


def synthetic_theory_scheme_pdf(
    questions: int = 3, parts: int = 3, *, maximum_mark_on_cover: bool = True
) -> bytes:
    """A 0625/41 May/June 2023 theory scheme: ``questions`` x ``parts`` leaves, two B1 each.

    Its maximum mark is ``questions * parts * 2``. Without
    ``maximum_mark_on_cover`` the cover omits that line, which the parser
    refuses with a ``ParseError`` ("Cannot extract maximum_mark ...").
    """
    doc = pymupdf.open()
    cover = doc.new_page(width=_A4[0], height=_A4[1])
    lines = [
        "Cambridge IGCSE",
        "PHYSICS 0625/41",
        "Paper 4 Extended Theory May/June 2023",
        "MARK SCHEME",
    ]
    if maximum_mark_on_cover:
        lines.append(f"Maximum Mark: {questions * parts * 2}")
    lines.append("Published")
    for i, line in enumerate(lines):
        cover.insert_text((72, 80 + 20 * i), line, fontsize=12)
    principles = doc.new_page(width=_A4[0], height=_A4[1])
    principles.insert_text((72, 80), "Generic Marking Principles", fontsize=12)
    rows: list[tuple[str, str, str]] = []
    for q in range(1, questions + 1):
        for p in range(parts):
            rows.append((f"{q}({chr(ord('a') + p)})", f"synthetic point {q}.{p} first", "B1"))
            rows.append(("", f"synthetic point {q}.{p} second", "B1"))
    for start in range(0, len(rows), _ROWS_PER_PAGE):
        page = doc.new_page(width=_A4[0], height=_A4[1])
        page.insert_text((72, 40), _RUNNING_HEADER, fontsize=9)
        table = [("Question", "Answer", "Marks"), *rows[start : start + _ROWS_PER_PAGE]]
        top = 60
        bottom = top + _ROW_HEIGHT * len(table)
        for x in _COLUMNS:
            page.draw_line((x, top), (x, bottom), width=0.8)
        for i in range(len(table) + 1):
            y = top + i * _ROW_HEIGHT
            page.draw_line((_COLUMNS[0], y), (_COLUMNS[-1], y), width=0.8)
        for i, cells in enumerate(table):
            y = top + i * _ROW_HEIGHT + 16
            for x, text in zip(_COLUMNS, cells, strict=False):
                page.insert_text((x + 4, y), text, fontsize=9)
    data: bytes = doc.tobytes()
    doc.close()
    return data


def whitespace_bomb_pdf(inflated_bytes: int) -> bytes:
    """One A4 page whose content stream inflates to ``inflated_bytes`` of spaces.

    The reviewer's ``plumber_bomb.py`` shape (final review R3, I3): pdfminer
    holds the whole inflated stream, and more, while it parses the page. At
    200 MiB the file is about 204 KB and an in-process parse grew by 416
    MiB; at 1 GiB about 1 MB, and the parse needs about 2.1 GiB. Compressed
    in 1 MiB chunks, so building it never holds the inflated data.
    """
    chunk = b" " * 1_048_576
    compressor = zlib.compressobj(9)
    parts: list[bytes] = []
    done = 0
    while done < inflated_bytes:
        parts.append(compressor.compress(chunk))
        done += len(chunk)
    parts.append(compressor.flush())
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << >> >>",
            pdf_stream(b"/Filter /FlateDecode", b"".join(parts)),
        ]
    )


__all__ = ["synthetic_theory_scheme_pdf", "whitespace_bomb_pdf"]
