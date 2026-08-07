"""Unit tests for the deterministic question-paper extractor (P4.1).

Mirrors ``tests/test_parsers_det.py``'s technique: synthetic pdfplumber
Page/PDF fakes built with ``MagicMock`` (no real PDFs, no network). One test
runs the real extractor over a genuine 0625 corpus paper and asserts a
measured, honest yield — skipped with a clear reason if the corpus is not
present in this environment.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lemely.core.question_papers import QuestionPaper
from lemely.io.det.question_papers import DeterministicQuestionPaperExtractor
from lemely.runtime.errors import ParseError

_REAL_CORPUS_MCQ = Path(
    "/home/sico/PaperScraper/papers/CAIE/igcse/physics-0625/2023/s23/0625_s23_qp_11.pdf"
)
_REAL_CORPUS_THEORY = Path(
    "/home/sico/PaperScraper/papers/CAIE/igcse/physics-0625/2023/s23/0625_s23_qp_41.pdf"
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _line(text: str, top: float, height: float = 10.0) -> dict[str, object]:
    return {"text": text, "top": top, "bottom": top + height, "x0": 0.0, "x1": 400.0}


def _vline(top: float, bottom: float | None = None) -> dict[str, object]:
    return {"top": top, "bottom": bottom if bottom is not None else top}


def _image(top: float, bottom: float) -> dict[str, object]:
    return {"top": top, "bottom": bottom}


def _fake_page(
    lines: list[dict[str, object]],
    *,
    cover_text: str = "",
    images: list[dict[str, object]] | None = None,
    vlines: list[dict[str, object]] | None = None,
    rects: list[dict[str, object]] | None = None,
    curves: list[dict[str, object]] | None = None,
) -> MagicMock:
    page = MagicMock()
    page.extract_text_lines.return_value = lines
    page.extract_text.return_value = cover_text
    page.images = images or []
    page.lines = vlines or []
    page.rects = rects or []
    page.curves = curves or []
    return page


def _fake_pdf(pages: list[MagicMock]) -> MagicMock:
    pdf = MagicMock()
    pdf.pages = pages
    pdf.__enter__ = MagicMock(return_value=pdf)
    pdf.__exit__ = MagicMock(return_value=None)
    return pdf


def _cover(total_marks: int) -> str:
    return f"PHYSICS 0625/11\nThe total mark for this paper is {total_marks}."


_EXTRACTOR = DeterministicQuestionPaperExtractor()


def _run(pages: list[MagicMock], filename: str) -> QuestionPaper:
    with patch("pdfplumber.open", return_value=_fake_pdf(pages)):
        return _EXTRACTOR(Path(filename))


# ---------------------------------------------------------------------------
# MCQ extraction
# ---------------------------------------------------------------------------


def test_extract_mcq_one_option_per_line() -> None:
    cover = _fake_page([], cover_text=_cover(2))
    content = _fake_page(
        [
            _line("1 Which unit is a unit of weight?", 0),
            _line("A kilogram", 12),
            _line("B kilojoule", 24),
            _line("C kilometre", 36),
            _line("D kilonewton", 48),
            _line("2 What is 2 + 2?", 60),
            _line("A 1", 72),
            _line("B 2", 84),
            _line("C 3", 96),
            _line("D 4", 108),
        ]
    )
    qp = _run([cover, content], "0625_s24_qp_11.pdf")

    assert qp.metadata.is_mcq is True
    assert qp.metadata.stated_total_marks == 2
    assert [q.ref for q in qp.questions] == ["1", "2"]
    q1 = qp.questions[0]
    assert q1.stem == "Which unit is a unit of weight?"
    assert q1.options == {"A": "kilogram", "B": "kilojoule", "C": "kilometre", "D": "kilonewton"}
    assert q1.marks == 1
    assert q1.has_figure is False
    assert qp.extracted_marks_total == qp.metadata.stated_total_marks == 2


def test_extract_mcq_inline_options_on_one_line() -> None:
    cover = _fake_page([], cover_text=_cover(1))
    content = _fake_page(
        [
            _line("1 What is the total distance?", 0),
            _line("A 20m B 400m C 4000m D 8000m", 12),
        ]
    )
    qp = _run([cover, content], "0625_s24_qp_11.pdf")

    assert len(qp.questions) == 1
    assert qp.questions[0].options == {"A": "20m", "B": "400m", "C": "4000m", "D": "8000m"}


def test_extract_mcq_stem_line_starting_with_a_is_not_mistaken_for_option() -> None:
    """A body line like "A customer buys..." must not be read as option A —
    only the last A→B→C→D run in the block is the real options block."""
    cover = _fake_page([], cover_text=_cover(1))
    content = _fake_page(
        [
            _line("1 A shopkeeper weighs rice on a spring balance.", 0),
            _line("A customer buys some pasta and notices the same reading.", 12),
            _line("Which quantity must be the same for both?", 24),
            _line("A density", 36),
            _line("B temperature", 48),
            _line("C volume", 60),
            _line("D weight", 72),
        ]
    )
    qp = _run([cover, content], "0625_s24_qp_11.pdf")

    assert len(qp.questions) == 1
    q = qp.questions[0]
    assert q.options == {"A": "density", "B": "temperature", "C": "volume", "D": "weight"}
    assert "A customer buys" in q.stem


def test_extract_mcq_figure_detection_is_per_question() -> None:
    cover = _fake_page([], cover_text=_cover(2))
    content = _fake_page(
        [
            _line("1 Plain text question, no diagram.", 0),
            _line("A one", 12),
            _line("B two", 24),
            _line("C three", 36),
            _line("D four", 48),
            _line("2 The graph shows motion.", 60),
            _line("A one", 72),
            _line("B two", 84),
            _line("C three", 96),
            _line("D four", 108),
        ],
        vlines=[_vline(60, 65), _vline(70, 75), _vline(80, 85)],  # overlap Q2's band only
    )
    qp = _run([cover, content], "0625_s24_qp_11.pdf")

    by_ref = {q.ref: q for q in qp.questions}
    assert by_ref["1"].has_figure is False
    assert by_ref["2"].has_figure is True
    assert by_ref["2"].figure_evidence[0].kind == "vector_drawing"


def test_extract_mcq_image_evidence_flags_figure() -> None:
    cover = _fake_page([], cover_text=_cover(1))
    content = _fake_page(
        [
            _line("1 Identify the component in the photo.", 0),
            _line("A one", 12),
            _line("B two", 24),
            _line("C three", 36),
            _line("D four", 48),
        ],
        images=[_image(0, 10)],
    )
    qp = _run([cover, content], "0625_s24_qp_11.pdf")

    assert qp.questions[0].has_figure is True
    assert qp.questions[0].figure_evidence[0].kind == "image"


def test_extract_mcq_missing_stated_total_is_left_null() -> None:
    """Cover text without the 'total mark' sentence: stated_total_marks
    stays None rather than a guessed value — never invent precision."""
    cover = _fake_page([], cover_text="PHYSICS 0625/11\nNo total-mark sentence here.")
    content = _fake_page(
        [
            _line("", 0),  # blank line — must be skipped, not misparsed
            _line("1 Which unit is a unit of weight?", 12),
            _line("A kilogram", 24),
            _line("B kilojoule", 36),
            _line("C kilometre", 48),
            _line("D kilonewton", 60),
        ]
    )
    qp = _run([cover, content], "0625_s24_qp_11.pdf")

    assert qp.metadata.stated_total_marks is None
    assert len(qp.questions) == 1


def test_extract_mcq_no_questions_raises_parse_error() -> None:
    cover = _fake_page([], cover_text=_cover(1))
    content = _fake_page([_line("Nothing resembling a question here.", 0)])
    with pytest.raises(ParseError):
        _run([cover, content], "0625_s24_qp_11.pdf")


def test_extract_bad_filename_raises_parse_error() -> None:
    cover = _fake_page([], cover_text=_cover(1))
    with pytest.raises(ParseError):
        _run([cover, _fake_page([])], "not-a-caie-filename.pdf")


# ---------------------------------------------------------------------------
# Theory extraction
# ---------------------------------------------------------------------------


def test_extract_theory_numbering_tree() -> None:
    cover = _fake_page([], cover_text=_cover(14))
    content = _fake_page(
        [
            _line("1 Fig. 1.1 shows a river.", 0),
            _line("(a) (i) State the speed.", 12),
            _line("speed = ......... [2]", 24),
            _line("(ii) Calculate the time.", 36),
            _line("time = ......... [3]", 48),
            _line("(b) Explain your answer. [4]", 60),
            _line("2 Calculate the density of the block. [5]", 72),
        ]
    )
    qp = _run([cover, content], "0625_s24_qp_41.pdf")

    by_ref = {q.ref: q for q in qp.questions}
    assert set(by_ref) == {"1a_i", "1a_ii", "1b", "2"}
    assert by_ref["1a_i"].marks == 2
    assert by_ref["1a_ii"].marks == 3
    assert by_ref["1b"].marks == 4
    assert by_ref["2"].marks == 5
    # Fig. 1.1's intro line is prepended to every sub-part under "1".
    assert "Fig. 1.1" in by_ref["1a_i"].stem
    assert "Fig. 1.1" in by_ref["1b"].stem
    # A single-part top-level question has no lettered ref of its own.
    assert by_ref["2"].stem.startswith("Calculate the density")
    assert qp.extracted_marks_total == 2 + 3 + 4 + 5 == qp.metadata.stated_total_marks


def test_extract_theory_figure_context_propagates_to_every_subpart() -> None:
    cover = _fake_page([], cover_text=_cover(5))
    content = _fake_page(
        [
            _line("1 Fig. 1.1 shows a circuit.", 0),
            _line("(a) State the current. [2]", 12),
            _line("(b) Calculate the voltage. [3]", 24),
        ],
        vlines=[_vline(0, 5), _vline(2, 6)],  # overlaps only the intro line's band
    )
    qp = _run([cover, content], "0625_s24_qp_41.pdf")

    by_ref = {q.ref: q for q in qp.questions}
    assert by_ref["1a"].has_figure is True
    assert by_ref["1b"].has_figure is True


def test_extract_theory_no_questions_raises_parse_error() -> None:
    cover = _fake_page([], cover_text=_cover(1))
    content = _fake_page([_line("No numbering markers on this page at all.", 0)])
    with pytest.raises(ParseError):
        _run([cover, content], "0625_s24_qp_41.pdf")


# ---------------------------------------------------------------------------
# Real corpus (honest measured yield — skips cleanly if unavailable)
# ---------------------------------------------------------------------------


def test_real_corpus_mcq_paper_measured_yield() -> None:
    if not _REAL_CORPUS_MCQ.exists():
        pytest.skip(f"real corpus paper not available at {_REAL_CORPUS_MCQ}")

    qp = DeterministicQuestionPaperExtractor()(_REAL_CORPUS_MCQ)

    assert qp.metadata.is_mcq is True
    assert qp.metadata.stated_total_marks == 40
    # Honest measured yield: not every question is cleanly extracted (see
    # lemely/io/det/question_papers.py docstring) — assert the real floor
    # rather than a hoped-for 40/40.
    assert 30 <= len(qp.questions) <= 40
    for q in qp.questions:
        assert q.options is not None
        assert len(q.options) == 4
        assert q.marks == 1


def test_real_corpus_theory_paper_measured_yield() -> None:
    if not _REAL_CORPUS_THEORY.exists():
        pytest.skip(f"real corpus paper not available at {_REAL_CORPUS_THEORY}")

    qp = DeterministicQuestionPaperExtractor()(_REAL_CORPUS_THEORY)

    assert qp.metadata.is_mcq is False
    assert qp.metadata.stated_total_marks == 80
    assert qp.extracted_marks_total == 80
    assert len(qp.questions) >= 40
