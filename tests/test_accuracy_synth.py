"""Unit tests for the synthetic handwritten-scan generator."""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from itertools import pairwise
from pathlib import Path

import pdfplumber
from PIL import Image, ImageDraw, ImageFont

from lemely.accuracy.synth import (
    _BASE_ANSWER_FONT_SIZE,
    _FONT_DIR,
    _FONT_FILES,
    _JITTER_MAX,
    _MARGIN,
    AnswerBlock,
    RenderFidelityError,
    _draw_handwritten_line,
    _lay_out_pages,
    _max_horizontal_render_overhead,
    _max_rendered_line_height,
    _wrap_line,
    render_handwritten_scan,
    write_golden_case,
)

_PAGE_SIZE = (1240, 1754)


def _sample_answers() -> list[AnswerBlock]:
    return [
        AnswerBlock(
            question_id="1a_i",
            text="Photosynthesis converts light energy into\nchemical energy stored in glucose.",
        ),
        AnswerBlock(question_id="1a_ii", text="The mitochondria is the powerhouse of the cell."),
    ]


def _count_pages(pdf_path: Path) -> int:
    # Pillow's PDF plugin is save-only (it cannot re-open the PDFs it writes),
    # so we use pdfplumber — already a project dependency — to read it back.
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


class RenderHandwrittenScanTests(unittest.TestCase):
    def test_produces_valid_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_pdf = Path(tmp) / "scan.pdf"
            render_handwritten_scan(_sample_answers(), out_pdf, seed=0)
            self.assertTrue(out_pdf.exists())
            data = out_pdf.read_bytes()
            self.assertGreater(len(data), 0)
            self.assertTrue(data.startswith(b"%PDF"))

    def test_deterministic_for_same_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a.pdf"
            out_b = Path(tmp) / "b.pdf"
            render_handwritten_scan(_sample_answers(), out_a, seed=42)
            render_handwritten_scan(_sample_answers(), out_b, seed=42)
            self.assertEqual(out_a.read_bytes(), out_b.read_bytes())

    def test_different_seed_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a.pdf"
            out_b = Path(tmp) / "b.pdf"
            render_handwritten_scan(_sample_answers(), out_a, seed=1)
            render_handwritten_scan(_sample_answers(), out_b, seed=2)
            self.assertNotEqual(out_a.read_bytes(), out_b.read_bytes())

    def test_empty_answers_raises(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            render_handwritten_scan([], Path(tmp) / "scan.pdf")

    def test_invalid_font_name_raises(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            render_handwritten_scan(
                _sample_answers(), Path(tmp) / "scan.pdf", font_name="Comic Sans"
            )

    def test_long_text_produces_multiple_pages(self):
        long_answer = " ".join(f"word{i}" for i in range(2000))
        answers = [AnswerBlock(question_id="1", text=long_answer)]
        with tempfile.TemporaryDirectory() as tmp:
            out_pdf = Path(tmp) / "scan.pdf"
            render_handwritten_scan(answers, out_pdf, seed=0)
            self.assertGreaterEqual(_count_pages(out_pdf), 2)


class WriteGoldenCaseTests(unittest.TestCase):
    def test_writes_all_three_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "case_0001"
            mark_scheme_json = json.dumps({"metadata": {}, "questions": []})
            answers_json = {"1a_i": {"student_answer": "x", "awarded_marks": 1}}
            write_golden_case(
                case_dir,
                mark_scheme_json,
                answers_json,
                _sample_answers(),
                seed=0,
            )

            ms_path = case_dir / "mark_scheme.json"
            ans_path = case_dir / "answers.json"
            pdf_path = case_dir / "scan.pdf"

            self.assertTrue(ms_path.exists())
            self.assertTrue(ans_path.exists())
            self.assertTrue(pdf_path.exists())

            self.assertEqual(ms_path.read_text(encoding="utf-8"), mark_scheme_json)
            self.assertEqual(json.loads(ans_path.read_text(encoding="utf-8")), answers_json)
            self.assertGreater(pdf_path.stat().st_size, 0)


class LineLayoutOverlapTests(unittest.TestCase):
    """M0.0 invariant guard: consecutive lines must never overlap at max jitter.

    NOT a regression test, and deliberately not claimed as one. This scenario
    also passes on pre-fix code: the old renderer advanced the cursor by a fixed
    _LINE_SPACING of 46px, comfortably above the ~35px rendered line height, so
    no jitter draw could make two lines collide.

    It guards the fix rather than reproducing the bug. Advancing by the *actual*
    rendered line height is what makes overlap reachable at all, so this pins
    the invariant the new cursor logic must keep.

    A note on how the pre-fix evidence for M0.0 can and cannot be replayed: this
    module cannot be collected against pre-fix code at all, because it imports
    names this branch introduces (_JITTER_MAX, RenderFidelityError), so pytest
    aborts on an ImportError before any single test reports. No test in this file
    should be described as "failing on develop" — the reproducible evidence is
    the pre-fix API calls recorded in the commit message instead.
    """

    def test_continuation_line_does_not_overlap_previous_at_max_jitter(self):
        class _MaxJitterRandom(random.Random):
            """Force every jitter draw to its maximum magnitude."""

            def uniform(self, a: float, b: float) -> float:
                # Font-size jitter (_draw_handwritten_line) always uses (0.9, 1.1);
                # push it to the top of that range. Other uniform() calls (rotation
                # angle etc.) are left at their upper bound too, which only makes
                # overlap easier to trigger, never harder.
                return b

            def randint(self, a: int, b: int) -> int:
                # y_offset jitter is (-4, 4); pin it to the max so the second
                # line is nudged toward the first as hard as possible.
                return b

        font_path = _FONT_DIR / _FONT_FILES["Caveat"]
        page_size = (1240, 1754)
        answers = [
            AnswerBlock(
                question_id="1",
                text="first line of the answer\nsecond continuation line here",
            )
        ]
        pages = _lay_out_pages(answers, font_path, page_size, _MaxJitterRandom(0))
        self.assertGreaterEqual(len(pages), 1)

        boxes = _pasted_line_bboxes(pages[0])
        self.assertGreaterEqual(len(boxes), 2, "expected at least two rendered lines")
        for (top_a, bottom_a), (top_b, bottom_b) in pairwise(boxes):
            overlap = min(bottom_a, bottom_b) - max(top_a, top_b)
            self.assertLessEqual(
                overlap,
                0,
                f"consecutive rendered lines overlap: {(top_a, bottom_a)} vs {(top_b, bottom_b)}",
            )


def _pasted_line_bboxes(page: Image.Image) -> list[tuple[int, int]]:
    """Recover (top, bottom) y-ranges of each non-white ink blob, top to bottom."""
    arr = page.convert("L")
    width, height = arr.size
    pixels = arr.load()
    row_has_ink = []
    for y in range(height):
        ink = any(pixels[x, y] < 250 for x in range(0, width, 2))
        row_has_ink.append(ink)
    boxes: list[tuple[int, int]] = []
    in_run = False
    start = 0
    gap = 0
    for y, has_ink in enumerate(row_has_ink):
        if has_ink:
            if not in_run:
                in_run = True
                start = y
            gap = 0
        elif in_run:
            gap += 1
            if gap > 3:
                boxes.append((start, y - gap))
                in_run = False
    if in_run:
        boxes.append((start, height - 1))
    return boxes


class RenderOverheadBudgetTests(unittest.TestCase):
    """M0.0: the wrap budget and page-break decision must reserve exactly what
    `_draw_handwritten_line`'s padding and rotation add, so a line that just
    fits the layout pass's budget never trips the render-time fidelity check.

    Uses `_lay_out_pages` directly (skips scan-noise and PDF encoding) so
    sweeping many seeds stays fast; that is the same shortcut
    `LineLayoutOverlapTests` above takes.
    """

    def test_long_wrapped_line_never_exceeds_right_edge_across_seeds(self):
        # Many short unbreakable tokens wrap so the last word on each line
        # sits as close to the right text-box edge as the wrap budget
        # allows — the natural shape to expose a right-edge budget shortfall
        # once padding and rotation are added at render time.
        font_path = _FONT_DIR / _FONT_FILES["Caveat"]
        long_answer = " ".join(f"word{i}" for i in range(60))
        answers = [AnswerBlock(question_id="1", text=long_answer)]
        for seed in range(50):
            with self.subTest(seed=seed):
                try:
                    _lay_out_pages(answers, font_path, _PAGE_SIZE, random.Random(seed))
                except RenderFidelityError as exc:  # pragma: no cover - failure path
                    self.fail(f"seed={seed} raised RenderFidelityError: {exc}")

    def test_line_near_bottom_margin_never_exceeds_bottom_edge_across_seeds(self):
        # Many single-line blocks walk the cursor down the page one rendered
        # line at a time, so some seed is guaranteed to land a line with its
        # top just above the bottom margin — the natural shape to expose a
        # page-break budget that reserves less than a line can actually
        # render tall (jitter + padding + rotation).
        font_path = _FONT_DIR / _FONT_FILES["Caveat"]
        answers = [AnswerBlock(question_id=str(i), text="hi") for i in range(60)]
        for seed in range(50):
            with self.subTest(seed=seed):
                try:
                    _lay_out_pages(answers, font_path, _PAGE_SIZE, random.Random(seed))
                except RenderFidelityError as exc:  # pragma: no cover - failure path
                    self.fail(f"seed={seed} raised RenderFidelityError: {exc}")


class _ExtremeRandom(random.Random):
    """Deterministically forces jitter draws to a chosen extreme.

    `RenderOverheadBudgetTests` above sweeps seeds to make an edge case
    *likely*; this instead makes it *certain* by construction, so the tests
    below don't rely on hoping a swept seed happens to roll the extreme
    value. `uniform()` is always pinned to its upper bound (max font-size
    jitter, max rotation) since that is the shared worst case for every
    check in this module; `randint()` (used only for the vertical
    `y_offset`) is pinned per-instance via *randint_extreme*, since the two
    tests below need opposite extremes of that one draw.
    """

    def __init__(self, seed: int, *, randint_extreme: str) -> None:
        super().__init__(seed)
        assert randint_extreme in ("min", "max")
        self._randint_extreme = randint_extreme

    def uniform(self, a: float, b: float) -> float:
        return b

    def randint(self, a: int, b: int) -> int:
        return a if self._randint_extreme == "min" else b


class RenderYJitterAndEdgeCheckTests(unittest.TestCase):
    """M0.0 follow-up: the fidelity check must cover all four text-box edges,
    and the page-break reservation must account for every source of render
    overhead, including the +-`_Y_JITTER_PX` vertical nudge — not just
    padding and rotation.
    """

    def test_bottom_edge_reservation_accounts_for_positive_y_jitter(self):
        # Construct the exact tightest position the page-break decision in
        # `_lay_out_pages` would ever allow a line to be drawn at — rather
        # than sweeping seeds and hoping one happens to land there, which
        # `RenderOverheadBudgetTests` already showed is unreliable for a
        # sliver this narrow (a real-seed sweep over this same shape found
        # 0/300 failures even before this fix, because hitting the exact
        # boundary by chance is rare). `cursor_y = bottom_limit -
        # reservation` is the largest cursor position the page-break check
        # (`cursor_y + reservation > bottom_limit`) still lets through. Pair
        # that with the widest line the wrap budget would ever hand
        # `_draw_handwritten_line` (`usable_width`) and the most-positive
        # y_offset: if the reservation omits `_Y_JITTER_PX`, this exact,
        # reachable combination renders past `bottom_limit` and raises
        # instead of the caller having flowed it onto the next page.
        font_path = _FONT_DIR / _FONT_FILES["Caveat"]
        page_width, page_height = _PAGE_SIZE
        max_jitter_size = max(1, round(_BASE_ANSWER_FONT_SIZE * _JITTER_MAX))
        wrap_font = ImageFont.truetype(str(font_path), max_jitter_size)
        full_usable_width = page_width - 2 * _MARGIN
        horizontal_overhead = _max_horizontal_render_overhead(wrap_font)
        usable_width = full_usable_width - horizontal_overhead
        reservation = _max_rendered_line_height(wrap_font, full_usable_width)
        bottom_limit = page_height - _MARGIN
        cursor_y = bottom_limit - reservation

        probe = Image.new("RGBA", (1, 1))
        probe_draw = ImageDraw.Draw(probe)
        widest_line = _wrap_line(
            probe_draw, " ".join(f"word{i}" for i in range(300)), wrap_font, usable_width
        )[0]

        page = Image.new("RGB", _PAGE_SIZE, "white")
        try:
            _, bottom = _draw_handwritten_line(
                page,
                widest_line,
                font_path,
                _MARGIN,
                cursor_y,
                _ExtremeRandom(0, randint_extreme="max"),
                _PAGE_SIZE,
            )
        except RenderFidelityError as exc:  # pragma: no cover - failure path
            self.fail(
                f"raised RenderFidelityError at the tightest page-break-reserved position: {exc}"
            )
        else:
            self.assertLessEqual(bottom, bottom_limit)

    def test_top_edge_check_catches_negative_y_jitter(self):
        # At the top of any page the cursor sits at `_MARGIN`; the most
        # negative y_offset then pushes `top` above `_MARGIN` (a smaller y),
        # outside the declared usable text box. Only `_draw_handwritten_line`
        # is exercised here (not the full page layout) because this checks
        # the assertion's own coverage, independent of how the caller
        # chooses to position lines.
        page = Image.new("RGB", _PAGE_SIZE, "white")
        font_path = _FONT_DIR / _FONT_FILES["Caveat"]
        with self.assertRaises(RenderFidelityError):
            _draw_handwritten_line(
                page,
                "hi",
                font_path,
                _MARGIN,
                _MARGIN,
                _ExtremeRandom(0, randint_extreme="min"),
                _PAGE_SIZE,
            )

    def test_left_edge_check_catches_out_of_bounds_x(self):
        # No jitter touches the horizontal paste position (`x` is used
        # as-is), so any ordinary RNG reproduces this: a caller passing
        # x < _MARGIN must be caught, the same as the other three edges.
        page = Image.new("RGB", _PAGE_SIZE, "white")
        font_path = _FONT_DIR / _FONT_FILES["Caveat"]
        with self.assertRaises(RenderFidelityError):
            _draw_handwritten_line(
                page,
                "hi",
                font_path,
                _MARGIN - 5,
                _MARGIN,
                random.Random(0),
                _PAGE_SIZE,
            )


class GlyphFallbackTests(unittest.TestCase):
    """M0.0: Greek/math glyphs must resolve via the NotoSansMath-Subset fallback."""

    def test_theta_pi_omega_render_via_math_fallback(self):
        page = Image.new("RGB", (1240, 1754), "white")
        # theta and pi are absent from the handwriting fonts; capital omega
        # (U+03A9) is the omega codepoint actually embedded in the vendored
        # NotoSansMath-Subset fallback (lowercase omega, U+03C9, is present in
        # no vendored font, so it is intentionally not used here).
        text = "θ = πr² and Ω = 1"
        font_path = _FONT_DIR / _FONT_FILES["Caveat"]
        # Must not raise, and must not silently rasterize any glyph as .notdef.
        _draw_handwritten_line(page, text, font_path, 60, 60, random.Random(0), (1240, 1754))

    def test_missing_glyph_raises_at_generation_time(self):
        # A codepoint present in no vendored font (handwriting or math fallback)
        # must raise via the round-trip fidelity check, not rasterize as .notdef.
        answers = [AnswerBlock(question_id="1", text="unrenderable glyph: \U0001f600")]
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RenderFidelityError):
            render_handwritten_scan(answers, Path(tmp) / "scan.pdf", seed=0)


class RenderFidelityAssertionTests(unittest.TestCase):
    """M0.0: the round-trip check must catch out-of-bounds ink and overprint."""

    def test_render_fidelity_assertion_catches_out_of_bounds_ink(self):
        # A single unbreakable token far wider than the usable text box cannot
        # be wrapped, so it must be caught by the bounds check instead of
        # silently clipping past the margin.
        long_token = "x" * 400
        answers = [AnswerBlock(question_id="1", text=long_token)]
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RenderFidelityError):
            render_handwritten_scan(answers, Path(tmp) / "scan.pdf", seed=0)

    def test_well_formed_input_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_pdf = Path(tmp) / "scan.pdf"
            render_handwritten_scan(_sample_answers(), out_pdf, seed=0)
            self.assertTrue(out_pdf.exists())


_GOLDEN_DIR = Path(__file__).parent / "golden"


def _golden_case_dirs() -> list[Path]:
    if not _GOLDEN_DIR.is_dir():
        return []
    return sorted(p for p in _GOLDEN_DIR.iterdir() if p.is_dir() and (p / "answers.json").exists())


class GoldenCorpusRoundTripTests(unittest.TestCase):
    """M0.0: the real committed corpus must round-trip through the renderer.

    Distinct from the synthetic-input unit tests above (GlyphFallbackTests,
    LineLayoutOverlapTests, RenderOverheadBudgetTests): this walks the actual
    tests/golden/*/answers.json student_answer text — including the
    theta/pi-bearing 0606_s23_qp_12_theory_* families and the Q5b overprint
    text from 0625_s20_qp_31_theory_partial/wrong — so a future corpus edit
    that reintroduces a missing-glyph or overprint defect is caught by CI,
    not just by hand.
    """

    def test_no_golden_case_raises_render_fidelity_error(self):
        case_dirs = _golden_case_dirs()
        self.assertTrue(case_dirs, "expected at least one tests/golden/*/answers.json fixture")
        for case_dir in case_dirs:
            answers_data = json.loads((case_dir / "answers.json").read_text(encoding="utf-8"))
            answers = [
                AnswerBlock(question_id=qid, text=entry["student_answer"])
                for qid, entry in answers_data.items()
            ]
            with tempfile.TemporaryDirectory() as tmp:
                out_pdf = Path(tmp) / "scan.pdf"
                try:
                    render_handwritten_scan(answers, out_pdf, seed=0)
                except RenderFidelityError as exc:
                    self.fail(f"{case_dir.name}: render_handwritten_scan raised {exc!r}")


if __name__ == "__main__":
    unittest.main()
