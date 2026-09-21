"""Unit tests for GeminiAnswerExtractor (GeminiClient mocked)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image, ImageDraw

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from lemely.io.answer_extraction import GeminiAnswerExtractor, _calibrate_confidence
from lemely.io.gemini import GeminiClient
from lemely.io.reread import DEFAULT_CONFIDENCE_THRESHOLD
from lemely.runtime.config import PathsSettings, load_settings
from lemely.runtime.errors import CostCeilingError, ExternalServiceError, ParseError
from lemely.runtime.events import EventType, bus


def _write_minimal_pdf(path: Path, *, pages: int = 1) -> None:
    """Write a real, tiny single/multi-page PDF pypdfium2 can rasterise.

    I1: GeminiAnswerExtractor now rasterises ``scan_path`` (pypdfium2) before
    calling Gemini, so tests need an actual openable PDF rather than the
    fake-PNG-bytes-named-scan.png stand-in the pre-I1 (whole-file-upload)
    extractor accepted.
    """
    images = [Image.new("RGB", (100, 140), color="white") for _ in range(pages)]
    images[0].save(path, "PDF", save_all=True, append_images=images[1:])


def _write_content_pdf(path: Path) -> None:
    """A single-page PDF with real, sharp content -- unlike
    ``_write_minimal_pdf``'s blank white page, this must NOT trip the T2.6
    scan-hygiene gate (blank or blurred), used to prove
    SCAN_QUALITY_WARNING is published only when hygiene actually finds
    something (I1 review should-fix 7)."""
    img = Image.new("RGB", (1654, 2339), color="white")
    draw = ImageDraw.Draw(img)
    for y in range(40, 2339 - 40, 24):
        for x in range(40, 1654 - 40, 140):
            draw.rectangle([x, y, x + 90, y + 14], outline=(0, 0, 0), width=2)
    img.save(path, "PDF")


def _minimal_mcq_mark_scheme() -> MarkScheme:
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": 3,
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
                {"id": "2", "marks": 1, "type": "mcq", "mcq_answer": "B"},
                {"id": "3", "marks": 1, "type": "mcq", "mcq_answer": "C"},
            ],
        }
    )


def _theory_mark_scheme() -> MarkScheme:
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 4,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "theory_extended",
                "maximum_mark": 5,
                "scheme_format": "point_based",
            },
            "questions": [
                {
                    "id": "1(a)",
                    "marks": 2,
                    "type": "explanation",
                    "question_command": "explain why",
                    "answer_points": [
                        {"id": "p1", "point": "due to gravity", "marks": 1},
                        {"id": "p2", "point": "acting downward", "marks": 1},
                    ],
                },
                {
                    "id": "1(b)",
                    "marks": 3,
                    "type": "calculation",
                    "question_command": "calculate the speed",
                    "answer_points": [
                        {"id": "p1", "point": "v = d/t", "marks": 1, "math_mark_type": "M"},
                        {"id": "p2", "point": "v = 100/5", "marks": 1, "math_mark_type": "M"},
                        {"id": "p3", "point": "20 m/s", "marks": 1, "math_mark_type": "A"},
                    ],
                },
            ],
        }
    )


class _IsolatedEnv:
    def __enter__(self) -> _IsolatedEnv:
        self._snap = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("LEMELY_"):
                del os.environ[k]
        return self

    def __exit__(self, *_: object) -> None:
        os.environ.clear()
        os.environ.update(self._snap)


def _client_with_response(tmp: str, body: dict) -> GeminiClient:
    mock_genai = MagicMock()
    resp = MagicMock(
        text=json.dumps(body),
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(prompt_token_count=5, candidates_token_count=30),
    )
    mock_genai.models.generate_content.return_value = resp
    mock_genai.files.upload.return_value = MagicMock()
    with _IsolatedEnv():
        settings = load_settings(toml_path=None, cwd=Path(tmp))
    settings = settings.model_copy(
        update={
            "paths": PathsSettings(
                cache_dir=Path(tmp) / ".cache",
                output_dir=Path(tmp) / "outputs",
            )
        }
    )
    return GeminiClient(settings, _genai_client=mock_genai)


class AnswerExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.scan = Path(self.tmp) / "scan.pdf"
        _write_minimal_pdf(self.scan)

    def test_mcq_extraction(self) -> None:
        body = {
            "answers": [
                {"question_id": "1", "answer": "A", "confidence": 0.99, "source_region": None},
                {"question_id": "2", "answer": "B", "confidence": 0.95, "source_region": None},
                {"question_id": "3", "answer": "C", "confidence": 0.85, "source_region": None},
            ]
        }
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        self.assertIsInstance(result, ExtractedAnswers)
        self.assertEqual(len(result.answers), 3)
        self.assertEqual(result.answers[0].answer, "A")
        self.assertIn("0625", result.paper_id)

    def test_theory_extraction_handles_freetext(self) -> None:
        body = {
            "answers": [
                {
                    "question_id": "1(a)",
                    "answer": "because gravity pulls it down",
                    "confidence": 0.8,
                    "source_region": None,
                },
                {
                    "question_id": "1(b)",
                    "answer": "20 m/s using v=d/t",
                    "confidence": 0.9,
                    "source_region": None,
                },
            ]
        }
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self.scan, mark_scheme=_theory_mark_scheme())
        self.assertEqual(len(result.answers), 2)
        self.assertIn("gravity", result.answers[0].answer)
        self.assertIn("20 m/s", result.answers[1].answer)

    def test_working_out_round_trips_through_extractor(self) -> None:
        body = {
            "answers": [
                {
                    "question_id": "1(b)",
                    "answer": "20 m/s",
                    "confidence": 0.9,
                    "source_region": "page 1, q1b",
                    "working_out": "v = d/t\nv = 100/5\nv = 20 m/s",
                },
            ]
        }
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self.scan, mark_scheme=_theory_mark_scheme())
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].working_out, "v = d/t\nv = 100/5\nv = 20 m/s")

    def test_mcq_working_out_is_none(self) -> None:
        body = {
            "answers": [
                {
                    "question_id": "1",
                    "answer": "A",
                    "confidence": 0.99,
                    "source_region": None,
                    "working_out": None,
                },
            ]
        }
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        self.assertIsNone(result.answers[0].working_out)


class IDNormalizationTests(unittest.TestCase):
    def test_canonical_id_strips_spaces_and_brackets(self):
        from lemely.io.answer_extraction import _canonical_id

        self.assertEqual(_canonical_id("1 a i"), _canonical_id("1(a)(i)"))

    def test_canonical_id_strips_brackets_only(self):
        from lemely.io.answer_extraction import _canonical_id

        self.assertEqual(_canonical_id("1(a)"), _canonical_id("1a"))

    def test_canonical_id_case_insensitive(self):
        from lemely.io.answer_extraction import _canonical_id

        self.assertEqual(_canonical_id("1(A)"), _canonical_id("1(a)"))

    def test_normalize_matches_exact_id(self):
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.io.answer_extraction import normalize_extracted_answers

        manifest_ids = ["1", "1(a)", "1(b)"]
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.pdf",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),
                ExtractedAnswer(question_id="1(a)", answer="B", confidence=0.9),
                ExtractedAnswer(question_id="1(b)", answer="C", confidence=0.9),
            ],
        )
        normalized = normalize_extracted_answers(extracted, manifest_ids)
        ids = {a.question_id for a in normalized.answers}
        self.assertEqual(ids, {"1", "1(a)", "1(b)"})

    def test_normalize_corrects_space_drift(self):
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.io.answer_extraction import normalize_extracted_answers

        manifest_ids = ["1(a)(i)"]
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.pdf",
            answers=[ExtractedAnswer(question_id="1 a i", answer="X", confidence=0.7)],
        )
        normalized = normalize_extracted_answers(extracted, manifest_ids)
        self.assertEqual(normalized.answers[0].question_id, "1(a)(i)")

    def test_unrecognised_id_is_left_unmatched_not_guessed(self):
        """#37: the positional fallback is DELETED. An unmatched id stays unmatched.

        This test previously asserted the opposite — that
        "completely_unrecognised" was silently rewritten to the first leftover
        manifest id. That rewrite is the defect: it stamps a guess with a
        genuine id, so every downstream consumer (and `id_match_rate`) treats a
        guessed answer as a matched one. A gap is honest; a silent realignment
        is not.
        """
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.io.answer_extraction import normalize_extracted_answers

        manifest_ids = ["1(a)(i)"]
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.pdf",
            answers=[
                ExtractedAnswer(question_id="completely_unrecognised", answer="Y", confidence=0.6),
            ],
        )
        normalized = normalize_extracted_answers(extracted, manifest_ids)
        self.assertEqual(normalized.answers[0].question_id, "completely_unrecognised")
        self.assertNotIn(
            "1(a)(i)",
            {a.question_id for a in normalized.answers},
            "an unmatched answer must not be handed a manifest id it never matched",
        )

    def test_one_missing_answer_does_not_shift_every_later_one(self):
        """The concrete harm the fallback caused, pinned as a regression test.

        With the fallback in place, a single unrecognised answer consumed the
        first leftover manifest id and pushed every subsequent unmatched answer
        one slot along. Here 1(b) and 1(c) match by canonical form and must be
        untouched, while the junk id must not be allowed to claim 1(a).
        """
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.io.answer_extraction import normalize_extracted_answers

        manifest_ids = ["1(a)", "1(b)", "1(c)"]
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.pdf",
            answers=[
                ExtractedAnswer(question_id="???", answer="junk", confidence=0.3),
                ExtractedAnswer(question_id="1 b", answer="B", confidence=0.9),
                ExtractedAnswer(question_id="1 c", answer="C", confidence=0.9),
            ],
        )
        normalized = normalize_extracted_answers(extracted, manifest_ids)
        by_id = {a.question_id: a.answer for a in normalized.answers}
        self.assertEqual(by_id.get("1(b)"), "B")
        self.assertEqual(by_id.get("1(c)"), "C")
        self.assertNotIn("1(a)", by_id, "1(a) was never extracted and must stay absent")
        self.assertEqual(by_id.get("???"), "junk")


class ExtractionProgressCounterTests(unittest.TestCase):
    """EXTRACTION_PROGRESS carries the same per-question counter as marking.

    ``index`` is the 1-based position inside the answer list being reported and
    ``total`` is that list's length, so the extraction phase drives the UI's
    "Question N of M" from the work actually in hand rather than an estimate.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.scan = Path(self.tmp) / "scan.pdf"
        _write_minimal_pdf(self.scan)

    def _run_capturing(self, body: dict, mark_scheme: MarkScheme) -> tuple[ExtractedAnswers, list]:
        """Extract ``body`` and return the result plus every progress frame it published.

        Subscribe/unsubscribe in try/finally: ``bus`` is a process-wide
        singleton, so a spy left attached would keep collecting events from
        every later test in the session.
        """
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        frames: list[dict] = []

        def _spy(**payload: object) -> None:
            frames.append(payload)

        bus.subscribe(EventType.EXTRACTION_PROGRESS, _spy)
        try:
            result = extractor(scan_path=self.scan, mark_scheme=mark_scheme)
        finally:
            bus.unsubscribe(EventType.EXTRACTION_PROGRESS, _spy)
        return result, frames

    def test_indices_run_1_to_n_against_a_constant_total(self) -> None:
        body = {
            "answers": [
                {"question_id": "1", "answer": "A", "confidence": 0.99, "source_region": None},
                {"question_id": "2", "answer": "B", "confidence": 0.95, "source_region": None},
                {"question_id": "3", "answer": "C", "confidence": 0.85, "source_region": None},
            ]
        }
        _, frames = self._run_capturing(body, _minimal_mcq_mark_scheme())

        self.assertEqual([f["question_id"] for f in frames], ["1", "2", "3"])
        # 1-based and inclusive of the last question: the counter has to be able
        # to reach its own total, or the UI ends a completed extraction at 2 of 3.
        self.assertEqual([f["index"] for f in frames], [1, 2, 3])
        self.assertEqual({f["total"] for f in frames}, {3})

    def test_total_counts_the_answers_actually_extracted(self) -> None:
        """The denominator is the answer list, not the mark scheme's question count.

        Gemini returned two answers for a three-question paper. Both frames say
        "of 2" because two answers are all the extractor has to report on — a
        total of 3 would be a promise of a third frame that never arrives, and
        the UI would sit at 2 of 3 forever. ``index`` is likewise the position in
        that list, so the answer for question "3" is the *second* frame.
        """
        body = {
            "answers": [
                {"question_id": "1", "answer": "A", "confidence": 0.99, "source_region": None},
                {"question_id": "3", "answer": "C", "confidence": 0.85, "source_region": None},
            ]
        }
        _, frames = self._run_capturing(body, _minimal_mcq_mark_scheme())

        self.assertEqual([f["question_id"] for f in frames], ["1", "3"])
        self.assertEqual([f["index"] for f in frames], [1, 2])
        self.assertEqual({f["total"] for f in frames}, {2})

    def test_nothing_extracted_publishes_no_frames(self) -> None:
        """An empty extraction reports nothing rather than a "1 of 0" frame."""
        result, frames = self._run_capturing({"answers": []}, _minimal_mcq_mark_scheme())

        self.assertEqual(result.answers, [])
        self.assertEqual(frames, [])


class CalibrateConfidenceTests(unittest.TestCase):
    """Regression tests for the rebuilt ``_calibrate_confidence`` (#36/M1.1).

    D14/D19 (spec §2.1): the old heuristic added an unconditional +0.1 bonus
    to any single-letter (A/B/C/D) answer and applied the MCQ/short-answer
    caps BEFORE the source_region/working_out bonuses, in the same branch
    chain — so a raw 0.90 could leak all the way to 1.00 (0.90 + 0.1 = 1.00,
    never capped), or an MCQ-hinted answer with source_region set could leak
    to 0.20 + 0.03 = 0.23, or a short non-MCQ answer with both working_out
    and source_region set could leak to 0.30 + 0.05 + 0.03 = 0.38. The
    rebuilt version deletes the +0.1 single-letter bonus entirely and applies
    every cap as the LAST step, after all additive bonuses, so none of these
    three leaks can recur.
    """

    def test_raw_high_confidence_single_letter_answer_is_not_boosted_toward_one(self) -> None:
        """A raw 0.90 clean single-letter answer keeps its raw confidence.

        Not boosted to 1.00 by the deleted +0.1 bonus, and -- #36 bullet 2
        (amended) -- NOT slammed to <=0.20 either: the 0.2 cap only applies
        to the mcq-hint-with-a-non-letter-answer case (a bad extraction), and
        a clean A/B/C/D letter is a good extraction.
        """
        answer = ExtractedAnswer(
            question_id="1", answer="A", confidence=0.90, source_region=None, working_out=None
        )
        result = _calibrate_confidence(answer)
        self.assertEqual(result, 0.90)

    def test_clean_single_letter_with_source_region_keeps_raw_confidence(self) -> None:
        """A clean single-letter answer is a GOOD extraction and must not be capped.

        #36 bullet 2 (amended): the old bullet conflated two different
        inputs under one "MCQ-shaped" cap -- on develop a clean single
        letter produced 1.00 (via the deleted +0.1 bonus) while an
        mcq-hint-non-letter produced 0.23 (via the cap leak). The rebuilt
        heuristic scopes the 0.2 cap to the mcq-hint-non-letter case only, so
        a clean letter with source_region set gets just the +0.03 bonus:
        0.90 + 0.03 = 0.93, never capped to 0.20.
        """
        answer = ExtractedAnswer(
            question_id="1",
            answer="A",
            confidence=0.90,
            source_region="top-right",
            working_out=None,
        )
        result = _calibrate_confidence(answer)
        self.assertEqual(result, 0.93)

    def test_mcq_hint_with_non_single_letter_answer_and_source_region_caps_at_point_two(
        self,
    ) -> None:
        """MCQ hint (not the single-letter heuristic) + source_region set must
        land at exactly 0.200, not leak to 0.230 (0.20 + 0.03) via a bonus
        applied after the cap.
        """
        answer = ExtractedAnswer(
            question_id="1",
            answer="42",  # not single-letter -- exercises question_type_hint, not answer text
            confidence=0.90,
            source_region="top-right",
            working_out=None,
        )
        result = _calibrate_confidence(answer, question_type_hint="mcq")
        self.assertEqual(result, 0.200)

    def test_short_non_mcq_with_working_out_and_source_region_caps_at_point_three(
        self,
    ) -> None:
        """Short non-MCQ answer + working_out + source_region must land at
        exactly 0.300, not leak to 0.380 (0.30 + 0.05 + 0.03) via bonuses
        applied after the short-answer cap.
        """
        answer = ExtractedAnswer(
            question_id="1",
            answer="5",  # len < 2 -> short-answer cap, not the MCQ cap
            confidence=0.90,
            source_region="top-right",
            working_out="carried the 1",
        )
        result = _calibrate_confidence(answer, question_type_hint="theory")
        self.assertEqual(result, 0.300)


class SourceBoxAndRequestRecorderTests(unittest.TestCase):
    """I1 acceptance criteria (1) and (5), against the real handwritten-59
    fixture (16 pages, 0 text chars) rather than only a synthetic PDF —
    GeminiClient itself is mocked throughout; no live Gemini call is made."""

    _FIXTURE = Path(__file__).parent / "fixtures" / "handwritten-59" / "0625_w24_qp_42.pdf"

    def setUp(self) -> None:
        if not self._FIXTURE.is_file():
            self.skipTest("handwritten-59 fixture not present")
        self.tmp = tempfile.mkdtemp()

    def test_every_answer_carries_a_source_box_with_a_real_page_and_positive_area(
        self,
    ) -> None:
        """Acceptance (1): on the 16-page, 0-text-char fixture, every
        extracted answer carries a source_box whose page index exists (0-15)
        and whose box has positive area.

        STATUS (I1 review round 4, finding I): this demonstrates the
        sanitisation/parsing path only — GeminiClient is mocked (see the
        class docstring) and the ``source_box`` values above are hand-written
        fixture data, not a real model response. Criterion (1) as stated in
        ``docs/plans/ai-improvements-plan.md`` I1 requires this to hold on
        Gemini's *actual* output for the fixture, which needs a live, paid
        call this no-spend branch does not make. That live demonstration
        remains BLOCKED; do not read a green run of this test as having
        satisfied criterion (1) end to end."""
        body = {
            "answers": [
                {
                    "question_id": "1(a)",
                    "answer": "because gravity pulls it down",
                    "confidence": 0.8,
                    "source_region": "page 1",
                    "source_box": {"page": 0, "box": [100, 100, 200, 400]},
                },
                {
                    "question_id": "1(b)",
                    "answer": "20 m/s",
                    "confidence": 0.9,
                    "source_region": "page 16",
                    "source_box": {"page": 15, "box": [700, 60, 780, 340]},
                },
            ]
        }
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self._FIXTURE, mark_scheme=_theory_mark_scheme())

        self.assertEqual(len(result.answers), 2)
        for answer in result.answers:
            self.assertIsNotNone(answer.source_box, answer.question_id)
            assert answer.source_box is not None
            self.assertTrue(0 <= answer.source_box.page < 16)
            ymin, xmin, ymax, xmax = answer.source_box.box
            self.assertGreater((ymax - ymin) * (xmax - xmin), 0)

    def test_out_of_range_page_is_dropped_not_trusted(self) -> None:
        """A hallucinated page index outside the 16 pages actually sent must
        not be passed through -- criterion (1) is a promise about what a
        caller receives, not just what the model said."""
        body = {
            "answers": [
                {
                    "question_id": "1(a)",
                    "answer": "x",
                    "confidence": 0.8,
                    "source_box": {"page": 99, "box": [100, 100, 200, 400]},
                },
            ]
        }
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self._FIXTURE, mark_scheme=_theory_mark_scheme())
        self.assertIsNone(result.answers[0].source_box)

    def test_request_carries_one_image_part_per_page_at_medium_resolution(self) -> None:
        """Acceptance (5): the request recorder shows media_resolution set
        per part -- every one of the 16 page images, not a global config
        knob."""
        mock_genai = MagicMock()
        resp = MagicMock(
            text=json.dumps({"answers": []}),
            candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
            usage_metadata=MagicMock(prompt_token_count=5, candidates_token_count=5),
        )
        mock_genai.models.generate_content.return_value = resp
        with _IsolatedEnv():
            settings = load_settings(toml_path=None, cwd=Path(self.tmp))
        settings = settings.model_copy(
            update={
                "paths": PathsSettings(
                    cache_dir=Path(self.tmp) / ".cache",
                    output_dir=Path(self.tmp) / "outputs",
                )
            }
        )
        client = GeminiClient(settings, _genai_client=mock_genai)
        extractor = GeminiAnswerExtractor(client)

        extractor(scan_path=self._FIXTURE, mark_scheme=_theory_mark_scheme())

        contents = mock_genai.models.generate_content.call_args.kwargs["contents"]
        image_parts = [p for p in contents if getattr(p, "inline_data", None) is not None]
        self.assertEqual(len(image_parts), 16)
        for part in image_parts:
            self.assertIsNotNone(part.media_resolution)
            self.assertEqual(
                str(part.media_resolution.level).upper().rsplit(".", 1)[-1],
                "MEDIA_RESOLUTION_MEDIUM",
            )
        mock_genai.files.upload.assert_not_called()


class ExtractorWireSchemaTests(unittest.TestCase):
    """I1 review round 4, MUST-FIX A: pin the actual JSON schema Gemini is
    sent for ``source_box`` -- nothing tested its *content* before this
    (only ``_strip_schema``'s recursion/pattern-stripping behaviour on toy
    models, in ``tests/test_gemini_client.py``). Round 3's fix to
    round 2's MUST-FIX 2 made ``_RawSourceBox.page``/``.box`` plain ``Any``
    so ``_coerce_page``/``_coerce_box`` could salvage a deviant model
    output, but that also erased ``page``/``box``'s types and
    ``required``-ness from the wire schema itself -- the only
    machine-readable instruction Gemini is given for this field's shape.
    ``__get_pydantic_json_schema__`` on ``_RawSourceBox`` must restore the
    round-2 shape (typed, required) in what is actually emitted, while the
    Python-side type stays ``Any`` for parsing (see
    ``MalformedSourceBoxCoordinateTests`` / ``NonFiniteSourceBoxCoordinateTests``
    below, which must keep passing unchanged)."""

    def test_sent_schema_declares_page_and_box_types_and_marks_them_required(self) -> None:
        from lemely.io.answer_extraction import _ExtractorOutput, _RawSourceBox
        from lemely.io.gemini import _strip_schema

        sent = _strip_schema(_ExtractorOutput.model_json_schema(), is_3x=True)
        source_box_ref = sent["properties"]["answers"]["items"]["properties"]["source_box"]
        # Optional (``| None``) -> emitted as anyOf[object, null].
        (box_schema,) = (
            option for option in source_box_ref["anyOf"] if option.get("type") == "object"
        )
        # I1 review round 4 (post-approval item 3): __get_pydantic_json_schema__
        # hard-codes the two properties it emits ("page", "box"). Pin that the
        # emitted set matches _RawSourceBox's own fields, not just the two
        # names we expect today -- a field added to _RawSourceBox later
        # without a matching update to the override would otherwise pass
        # silently and simply never reach Gemini.
        self.assertEqual(set(box_schema["properties"]), set(_RawSourceBox.model_fields))
        self.assertEqual(box_schema["properties"]["page"], {"type": "integer"})
        self.assertEqual(
            box_schema["properties"]["box"],
            {"type": "array", "items": {"type": "integer"}},
        )
        self.assertEqual(set(box_schema["required"]), {"page", "box"})

    def test_raw_source_box_stays_any_typed_for_parsing(self) -> None:
        """The schema fix must not narrow what ``_RawSourceBox`` itself
        accepts when *parsing* a real (possibly deviant) response -- only
        what is declared in the schema sent to Gemini."""
        from lemely.io.answer_extraction import _RawSourceBox

        # A fractional float and a null page are exactly the shapes round
        # 2's MUST-FIX 2 needed Any for; both must still parse without
        # raising, deferring validity entirely to _coerce_page/_coerce_box.
        _RawSourceBox.model_validate({"page": None, "box": "not a box"})
        _RawSourceBox.model_validate({"page": 1.5, "box": [1, 2, 3, 4]})


class RawExtractedAnswerWireSchemaTests(unittest.TestCase):
    """US-031 review MUST-FIX 4: the existing ``ExtractorWireSchemaTests``
    pins ONLY ``source_box``'s inner ``page``/``box`` types -- it does not
    guard ``_RawExtractedAnswer.__get_pydantic_json_schema__`` itself, the
    second, larger override US-031 added with the same failure mode as
    ``_RawSourceBox``'s. That gap is exactly why MUST-FIX 1 (a silently
    dropped ``source_box`` ``description``) shipped undetected: nothing
    asserted the FULL emitted schema for any field made ``Any`` here.

    Run this file at ``PYTHONOPTIMIZE=`` (0): under ``-O``/``-OO`` Python
    strips class docstrings, so ``_RawSourceBox.__doc__`` (and therefore its
    schema's ``description``) is gone from BOTH sides of the comparison
    below regardless of whether the production code is correct -- these
    assertions compare against ``_RawSourceBox.model_json_schema()``
    computed live in the SAME process, specifically so they self-verify
    under whatever optimize level actually runs, rather than hard-coding
    docstring text that would silently stop meaning anything under
    ``-OO``."""

    def _sent_answer_item_schema(self) -> dict:
        from lemely.io.answer_extraction import _ExtractorOutput
        from lemely.io.gemini import _strip_schema

        sent = _strip_schema(_ExtractorOutput.model_json_schema(), is_3x=True)
        return sent["properties"]["answers"]["items"]

    def test_emitted_property_set_matches_raw_extracted_answer_fields(self) -> None:
        """Drift guard: mirrors ExtractorWireSchemaTests's
        ``set(box_schema["properties"]) == set(_RawSourceBox.model_fields)``
        -- a field added to ``_RawExtractedAnswer`` later without a matching
        update to the override would otherwise pass silently and simply
        never reach Gemini."""
        from lemely.io.answer_extraction import _RawExtractedAnswer

        item_schema = self._sent_answer_item_schema()
        self.assertEqual(set(item_schema["properties"]), set(_RawExtractedAnswer.model_fields))

    def test_emitted_scalar_field_types_and_required_set(self) -> None:
        item_schema = self._sent_answer_item_schema()
        self.assertEqual(item_schema["properties"]["question_id"], {"type": "string"})
        self.assertEqual(item_schema["properties"]["answer"], {"type": "string"})
        self.assertEqual(
            item_schema["properties"]["confidence"],
            {"type": "number", "minimum": 0.0, "maximum": 1.0},
        )
        self.assertEqual(
            item_schema["properties"]["source_region"],
            {"anyOf": [{"type": "string"}, {"type": "null"}]},
        )
        self.assertEqual(
            item_schema["properties"]["working_out"],
            {"anyOf": [{"type": "string"}, {"type": "null"}]},
        )
        self.assertEqual(set(item_schema["required"]), {"question_id", "answer", "confidence"})

    def test_emitted_source_box_object_equals_raw_source_box_schema_wholesale(self) -> None:
        """The MUST-FIX 1 regression guard: the object variant of
        ``source_box``'s ``anyOf`` must equal ``_RawSourceBox.model_json_schema()``
        (after ``_strip_schema``, which only removes ``title``) EXACTLY --
        including ``description`` -- not a hand-picked subset of its keys.
        This is the assertion that would have caught the dropped
        description; a properties/required-only check (as
        ``ExtractorWireSchemaTests`` above deliberately keeps, for
        ``_RawSourceBox``'s OWN direct fields) would not have."""
        from lemely.io.answer_extraction import _RawSourceBox
        from lemely.io.gemini import _strip_schema

        item_schema = self._sent_answer_item_schema()
        source_box_field = item_schema["properties"]["source_box"]
        (box_schema,) = (
            option for option in source_box_field["anyOf"] if option.get("type") == "object"
        )
        expected = _strip_schema(_RawSourceBox.model_json_schema(), is_3x=True)
        expected.pop("title", None)
        actual = dict(box_schema)
        actual.pop("title", None)
        self.assertEqual(actual, expected)


class WireSchemaSurvivesPythonOptimizeTests(unittest.TestCase):
    """US-036: CPython's ``-O``/``-OO`` strips class docstrings, and pydantic
    derives a schema's ``description`` from ``__doc__`` when nothing
    overrides it. ``RawExtractedAnswerWireSchemaTests`` above compares the
    sent schema against a schema computed live IN THE SAME PROCESS, so under
    ``-OO`` both sides lose their descriptions together and the comparison
    is vacuously equal -- it cannot catch this regression, by its own
    docstring's admission. This class hard-codes the expected description
    text instead, and actually runs under ``-OO`` (via a subprocess, since
    the optimize level is fixed for the whole interpreter and cannot be
    toggled mid-run) to prove the wire schema's ``description`` keys do not
    depend on ``__doc__`` at all.

    Run as a subprocess with the ``-OO`` flag directly (not via the
    ``PYTHONOPTIMIZE`` env var) so the assertion holds regardless of what the
    ambient environment happens to have set. Deliberately does NOT also set
    ``PYTHONDONTWRITEBYTECODE`` -- that combination forces a sympy recompile
    per subprocess and has already broken a timeout-bounded test on this
    branch (test_equivalence.py).
    """

    _SCRIPT = (
        "import json, sys\n"
        "assert sys.flags.optimize == 2, sys.flags.optimize\n"
        "from lemely.io.answer_extraction import _ExtractorOutput\n"
        "from lemely.io.gemini import _strip_schema\n"
        "sent = _strip_schema(_ExtractorOutput.model_json_schema(), is_3x=True)\n"
        "item = sent['properties']['answers']['items']\n"
        "box_opts = item['properties']['source_box']['anyOf']\n"
        "(box,) = (o for o in box_opts if o.get('type') == 'object')\n"
        "print(json.dumps({\n"
        "    'top': sent.get('description'),\n"
        "    'item': item.get('description'),\n"
        "    'box': box.get('description'),\n"
        "}))\n"
    )

    def test_description_keys_survive_dash_oo(self) -> None:
        import subprocess
        import sys

        # this module's own hard-coded _SCRIPT), no shell, no untrusted
        # input -- same pattern as test_equivalence.py's subprocess calls.
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-OO", "-c", self._SCRIPT],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["top"],
            "Inner schema we ask Gemini to return — just the answers list.",
        )
        self.assertEqual(
            payload["item"],
            "One extracted answer, as returned by the primary extraction call.",
        )
        self.assertEqual(
            payload["box"],
            "A bounding box on one page image, before validation.",
        )


class MalformedSourceBoxCoordinateTests(unittest.TestCase):
    """I1 review MUST-FIX 3, coordinate case specifically: the only existing
    bad-box test (``test_out_of_range_page_is_dropped_not_trusted``) feeds a
    bad *page*, which the wire schema always allowed. A malformed
    *coordinate* (page in-range, but a box value outside 0-1000) exercises a
    different path -- ``SourceBox``'s own validator -- and must salvage the
    same way: drop to ``source_box=None``, keep the answer, and never pay
    for a second corrective call."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.scan = Path(self.tmp) / "scan.pdf"
        _write_minimal_pdf(self.scan, pages=2)

    def _run_with_source_box(self, source_box: object) -> tuple[ExtractedAnswers, MagicMock]:
        mock_genai = MagicMock()
        resp = MagicMock(
            text=json.dumps(
                {
                    "answers": [
                        {
                            "question_id": "1",
                            # A clean MCQ letter: _calibrate_confidence does
                            # not cap this, so confidence stays 0.8 (above
                            # the 0.6 reread threshold) and these tests only
                            # exercise source_box sanitisation, not a reread
                            # this fixed single-response mock cannot serve
                            # correctly.
                            "answer": "B",
                            "confidence": 0.8,
                            "source_box": source_box,
                        },
                    ]
                }
            ),
            candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
            usage_metadata=MagicMock(prompt_token_count=5, candidates_token_count=5),
        )
        mock_genai.models.generate_content.return_value = resp
        with _IsolatedEnv():
            settings = load_settings(toml_path=None, cwd=Path(self.tmp))
        settings = settings.model_copy(
            update={
                "paths": PathsSettings(
                    cache_dir=Path(self.tmp) / ".cache",
                    output_dir=Path(self.tmp) / "outputs",
                )
            }
        )
        client = GeminiClient(settings, _genai_client=mock_genai)
        extractor = GeminiAnswerExtractor(client)
        result = extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        return result, mock_genai

    def test_malformed_coordinate_is_dropped_without_a_corrective_retry(self) -> None:
        # page 0 is in range (2 pages sent); the box coordinate 1500 is
        # outside the 0-1000 scale -- a malformed COORDINATE, not a bad page
        # index.
        result, mock_genai = self._run_with_source_box({"page": 0, "box": [100, 100, 200, 1500]})
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].source_box)
        # No schema-correction retry: the wire schema (_RawSourceBox) never
        # validates the box, so this never fails GeminiClient's parse in the
        # first place -- only the local sanitize step drops it.
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_fractional_coordinate_is_dropped_without_a_corrective_retry(self) -> None:
        """I1 review round 2, MUST-FIX 2: a normalised 0-1000 coordinate is
        naturally fractional, and round 1's fix left ``box: list[int]`` on
        the wire schema, which pydantic rejects outright for a float with a
        fractional part -- losing the whole paper and paying for a second
        16-page corrective call. ``_RawSourceBox.box`` is now ``Any``,
        coerced (rounded) per-answer instead."""
        result, mock_genai = self._run_with_source_box(
            {"page": 0, "box": [100.5, 100.2, 200.9, 400.1]}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertIsNotNone(result.answers[0].source_box)
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_null_page_is_dropped_without_a_corrective_retry(self) -> None:
        """I1 review round 2, MUST-FIX 2: round 1's fix left ``page: int`` on
        the wire schema, which pydantic rejects for ``null`` -- losing the
        whole paper. ``_RawSourceBox.page`` is now ``Any``."""
        result, mock_genai = self._run_with_source_box({"page": None, "box": [100, 100, 200, 400]})
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].source_box)
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_box_given_as_prose_is_dropped_without_a_corrective_retry(self) -> None:
        """I1 review round 2, MUST-FIX 2: ``box`` returned as a prose string
        instead of four numbers, another shape round 1's ``list[int]`` wire
        type still rejected outright."""
        result, mock_genai = self._run_with_source_box(
            {"page": 0, "box": "top-right corner of the page"}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].source_box)
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def _run_with_raw_source_box_json(
        self, source_box_json: str
    ) -> tuple[ExtractedAnswers, MagicMock]:
        """Like :meth:`_run_with_source_box`, but takes the ``source_box``
        payload as a raw JSON fragment rather than a Python object, so a
        bare non-standard-JSON literal (``Infinity``/``NaN``/an overflowing
        exponent) can be embedded exactly as pydantic's own JSON parser
        would receive it from a real response body -- ``json.dumps`` cannot
        produce these for us (a Python ``float`` already collapses ``1e400``
        to ``inf`` at parse time, so there is no way to round-trip the
        literal text through it)."""
        mock_genai = MagicMock()
        raw_text = (
            '{"answers": [{"question_id": "1", "answer": "B", "confidence": 0.8, '
            f'"source_box": {source_box_json}}}]}}'
        )
        resp = MagicMock(
            text=raw_text,
            candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
            usage_metadata=MagicMock(prompt_token_count=5, candidates_token_count=5),
        )
        mock_genai.models.generate_content.return_value = resp
        with _IsolatedEnv():
            settings = load_settings(toml_path=None, cwd=Path(self.tmp))
        settings = settings.model_copy(
            update={
                "paths": PathsSettings(
                    cache_dir=Path(self.tmp) / ".cache",
                    output_dir=Path(self.tmp) / "outputs",
                )
            }
        )
        client = GeminiClient(settings, _genai_client=mock_genai)
        extractor = GeminiAnswerExtractor(client)
        result = extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        return result, mock_genai


class NonFiniteSourceBoxCoordinateTests(unittest.TestCase):
    """I1 review round 4, MUST-FIX B: pydantic's JSON parser accepts the
    ``Infinity``/``NaN`` JSON-extension literals and an overflowing exponent
    (``1e400`` parses to ``inf``), and ``_RawSourceBox.box`` is ``Any`` so
    nothing rejects them before ``_coerce_box`` sees them. Before this fix,
    ``round()`` on a non-finite float raised a bare ``OverflowError`` /
    ``ValueError`` -- not a :class:`~lemely.runtime.errors.LemelyError`,
    losing the whole paper *and* escaping the classified-error hierarchy
    ``cli.py`` relies on. All six reachable non-finite shapes (bare JSON
    literal and string form, for each of Infinity/NaN/overflow) must drop to
    ``source_box=None`` (the existing ``malformed_coordinates`` bucket)
    exactly like any other unparseable coordinate, without raising and
    without paying for a second corrective call."""

    setUp = MalformedSourceBoxCoordinateTests.setUp
    _run_with_source_box = MalformedSourceBoxCoordinateTests._run_with_source_box
    _run_with_raw_source_box_json = MalformedSourceBoxCoordinateTests._run_with_raw_source_box_json

    def test_infinity_literal_coordinate_is_dropped_not_raised(self) -> None:
        result, mock_genai = self._run_with_raw_source_box_json(
            '{"page": 0, "box": [Infinity, 100, 300, 400]}'
        )
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].source_box)
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_nan_literal_coordinate_is_dropped_not_raised(self) -> None:
        result, mock_genai = self._run_with_raw_source_box_json(
            '{"page": 0, "box": [NaN, 100, 300, 400]}'
        )
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].source_box)
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_overflowing_exponent_literal_coordinate_is_dropped_not_raised(self) -> None:
        result, mock_genai = self._run_with_raw_source_box_json(
            '{"page": 0, "box": [1e400, 100, 300, 400]}'
        )
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].source_box)
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_infinity_string_coordinate_is_dropped_not_raised(self) -> None:
        result, mock_genai = self._run_with_source_box(
            {"page": 0, "box": ["Infinity", 100, 300, 400]}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].source_box)
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_inf_string_coordinate_is_dropped_not_raised(self) -> None:
        result, mock_genai = self._run_with_source_box({"page": 0, "box": ["inf", 100, 300, 400]})
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].source_box)
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_overflowing_exponent_string_coordinate_is_dropped_not_raised(self) -> None:
        result, mock_genai = self._run_with_source_box({"page": 0, "box": ["1e400", 100, 300, 400]})
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].source_box)
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)


class AnswerLevelParseResilienceTests(unittest.TestCase):
    """US-031: eleven malformed-response shapes ABOVE the source_box level
    (on _RawExtractedAnswer's own question_id/answer/confidence/source_box
    fields) used to fail _ExtractorOutput's pydantic validation for the
    *whole* answers list -- triggering GeminiClient's schema-correction
    retry (a second full-paper call, ``generate_content.call_count == 2``,
    see the ``ParseError``/``call_count == 2`` demonstration in this class's
    module docstring below) before raising ``ParseError`` and losing every
    answer in the paper for one bad field on one answer. Each shape must now
    be salvaged or dropped *per answer*, with a recorded reason, and without
    a second corrective call -- exactly the treatment
    ``MalformedSourceBoxCoordinateTests`` / ``NonFiniteSourceBoxCoordinateTests``
    already prove one level down, at source_box's own page/box fields.

    Review correction: eleven is the count of FIELD-level shapes fixed here.
    It is not the total count of malformed shapes this module now handles.
    Three more -- a malformed *list element* rather than a malformed field
    on an otherwise-dict element -- are fixed separately in
    ``AnswerLevelParseResilienceTests`` tests (13)-(15) below (review
    MUST-FIX 6), and four more -- ``answers`` itself not being a list at all
    -- are accepted as a legitimate whole-paper loss and pinned in
    ``ContainerLevelMalformedResponseTests`` rather than silently left
    uncounted.

    Before this fix, feeding any one of the eleven shapes below into the
    pre-fix ``_RawExtractedAnswer`` (``question_id: str``, ``answer: str``,
    ``confidence: float = Field(..., ge=0.0, le=1.0)``, ``source_box:
    _RawSourceBox | None``) raised::

        1 validation error for _ExtractorOutput
        answers.0.confidence
          Input should be less than or equal to 1 [type=less_than_equal, ...]

    from ``response_schema.model_validate_json(raw_text)`` in
    ``GeminiClient.generate_structured`` -- confirmed directly against the
    pre-fix module during this fix's development: the same mocked response
    that now parses in one call raised ``ParseError`` after exactly 2
    ``generate_content`` calls (the original plus the schema-correction
    retry, since the retry is fed the identical malformed text and fails
    identically)."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.scan = Path(self.tmp) / "scan.pdf"
        _write_minimal_pdf(self.scan, pages=2)

    def _run_with_answers(self, answers: list[dict]) -> tuple[ExtractedAnswers, MagicMock]:
        body = {"answers": answers}
        client = _client_with_response(self.tmp, body)
        extractor = GeminiAnswerExtractor(client)
        result = extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        return result, client._client

    def _run_with_answer(self, answer: dict) -> tuple[ExtractedAnswers, MagicMock]:
        return self._run_with_answers([answer])

    # (1) source_box as a prose string, not an object.
    def test_scalar_source_box_prose_string_does_not_lose_the_answer(self) -> None:
        result, mock_genai = self._run_with_answer(
            {
                "question_id": "1",
                "answer": "B",
                "confidence": 0.8,
                "source_box": "top-right corner of the page",
            }
        )
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].source_box)
        self.assertEqual(result.source_box_drops, {"invalid_source_box_shape": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    # (2) source_box as a bare 4-element list, not {"page":.., "box":..}.
    def test_scalar_source_box_bare_list_does_not_lose_the_answer(self) -> None:
        result, mock_genai = self._run_with_answer(
            {
                "question_id": "1",
                "answer": "B",
                "confidence": 0.8,
                "source_box": [100, 100, 200, 400],
            }
        )
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].source_box)
        self.assertEqual(result.source_box_drops, {"invalid_source_box_shape": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    # (3) confidence = NaN.
    def test_confidence_nan_does_not_lose_the_answer(self) -> None:
        result, mock_genai = self._run_with_answer(
            {"question_id": "1", "answer": "B", "confidence": float("nan")}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].confidence, 0.0)
        self.assertEqual(result.confidence_repairs, {"non_finite": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    # (4) confidence = Infinity.
    def test_confidence_infinity_does_not_lose_the_answer(self) -> None:
        result, mock_genai = self._run_with_answer(
            {"question_id": "1", "answer": "B", "confidence": float("inf")}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].confidence, 0.0)
        self.assertEqual(result.confidence_repairs, {"non_finite": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    # (5) confidence out of the required [0, 1] range.
    def test_confidence_out_of_range_does_not_lose_the_answer(self) -> None:
        """Review fix: an out-of-range confidence must fall back to
        _FALLBACK_CONFIDENCE (untrusted), NOT clamp up to 1.0 -- clamping the
        one shape that demonstrably violated the model's own [0, 1] contract
        to the *most* confident value in range would suppress both
        should_reread's re-read gate and correction_ai's low-confidence
        review flag, both of which trigger on LOW confidence. Asserting the
        exact value (not just that the answer survives) is deliberate: a
        survival-only assertion passes whether this clamps to 1.0 or falls
        back to 0.0, which is exactly how the clamp-up bug slipped through
        review once already."""
        result, mock_genai = self._run_with_answer(
            {"question_id": "1", "answer": "B", "confidence": 1.5}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].confidence, 0.0)
        self.assertEqual(result.confidence_repairs, {"out_of_range": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_confidence_negative_out_of_range_falls_back_not_clamped(self) -> None:
        """The negative side already happened to fall back safely (clamping
        toward 0.0 and clamping to the fallback both land on 0.0), but pin it
        explicitly now that the positive side no longer clamps -- both sides
        of the [0, 1] contract violation must be treated identically."""
        result, mock_genai = self._run_with_answer(
            {"question_id": "1", "answer": "B", "confidence": -0.5}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].confidence, 0.0)
        self.assertEqual(result.confidence_repairs, {"out_of_range": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    # (6) confidence missing entirely.
    def test_confidence_missing_does_not_lose_the_answer(self) -> None:
        result, mock_genai = self._run_with_answer({"question_id": "1", "answer": "B"})
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].confidence, 0.0)
        self.assertEqual(result.confidence_repairs, {"missing": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    # (7) confidence given as a non-numeric string.
    def test_confidence_malformed_string_does_not_lose_the_answer(self) -> None:
        result, mock_genai = self._run_with_answer(
            {"question_id": "1", "answer": "B", "confidence": "high"}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].confidence, 0.0)
        self.assertEqual(result.confidence_repairs, {"malformed": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    # (8) answer given as a number instead of a string.
    def test_numeric_answer_is_salvaged_by_stringifying(self) -> None:
        result, mock_genai = self._run_with_answer(
            {"question_id": "2", "answer": 42, "confidence": 0.8}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].answer, "42")
        self.assertEqual(result.answer_drops, {})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    # (9) question_id given as a number instead of a string.
    def test_numeric_question_id_is_salvaged_by_stringifying(self) -> None:
        result, mock_genai = self._run_with_answer(
            {"question_id": 1, "answer": "B", "confidence": 0.8}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].question_id, "1")
        self.assertEqual(result.answer_drops, {})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    # (10) question_id missing entirely -- unlike source_box/confidence,
    # there is nothing to key this answer by, so the ANSWER drops (never the
    # rest of the paper with it).
    def test_missing_question_id_drops_the_answer_not_the_paper(self) -> None:
        result, mock_genai = self._run_with_answers(
            [
                {"question_id": "1", "answer": "B", "confidence": 0.8},
                {"question_id": None, "answer": "C", "confidence": 0.8},
            ]
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].question_id, "1")
        self.assertEqual(result.answer_drops, {"missing_question_id": 1})
        # Review MUST-FIX 7 (stronger fix): no question_id was salvageable
        # here, so there is nothing to attribute this drop to -- it must
        # NOT appear in dropped_question_ids.
        self.assertEqual(result.dropped_question_ids, [])
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    # (11) answer text missing entirely -- an answer with no text at all is
    # not gradable, so the ANSWER drops (never the rest of the paper).
    def test_missing_answer_drops_the_answer_not_the_paper(self) -> None:
        result, mock_genai = self._run_with_answers(
            [
                {"question_id": "1", "answer": "B", "confidence": 0.8},
                {"question_id": "2", "answer": None, "confidence": 0.8},
            ]
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].question_id, "1")
        self.assertEqual(result.answer_drops, {"missing_answer": 1})
        # Review MUST-FIX 7 (stronger fix): question_id "2" WAS salvageable
        # even though the answer text was not -- correct_paper needs this to
        # tell "extracted and dropped" apart from "never extracted".
        self.assertEqual(result.dropped_question_ids, ["2"])
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_dropped_question_ids_are_canonicalised_like_surviving_answer_ids(self) -> None:
        """dropped_question_ids must go through the same canonical-id remap
        normalize_extracted_answers already applies to answers' own ids --
        a dropped answer's id came from the same untrusted wire response and
        correct_paper needs it to match the SAME real manifest id
        (Question.id) that a surviving answer would have matched."""
        body = {
            "answers": [
                {"question_id": "1 a", "answer": "correct answer", "confidence": 0.9},
                {"question_id": "1 b", "answer": None, "confidence": 0.9},
            ]
        }
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self.scan, mark_scheme=_theory_mark_scheme())
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].question_id, "1(a)")
        self.assertEqual(result.dropped_question_ids, ["1(b)"])

    # (12) question_id as a FRACTIONAL float -- review MUST-FIX 5.
    def test_fractional_question_id_is_rejected_not_mis_attached(self) -> None:
        """``str(1.1) == "1.1"``, and ``_canonical_id`` strips dots when
        matching against the mark scheme's manifest ids -- so stringifying
        this the way a whole-numbered float is stringified would silently
        canonicalise to ``"11"`` and attach the answer to a DIFFERENT real
        question on an ordinary 1..15 paper, stamped an exact match with no
        drop, no repair, and no event. A fractional float must be rejected
        (the whole answer dropped) instead."""
        result, mock_genai = self._run_with_answer(
            {"question_id": 1.1, "answer": "ANSWER-FOR-Q1-PART-1", "confidence": 0.9}
        )
        self.assertEqual(len(result.answers), 0)
        self.assertEqual(result.answer_drops, {"malformed_question_id": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_fractional_question_id_does_not_overwrite_the_real_question(self) -> None:
        """The destructive two-answer case from the review findings: a
        fractional-float id used to canonicalise onto question 11's id and,
        because ``_flatten_answers`` is last-wins, silently REPLACE the real
        Q11 answer when the model returned it first. Confirm the real
        answer for question 11 survives untouched and the bad element is
        dropped instead of attached to it."""
        result, mock_genai = self._run_with_answers(
            [
                {
                    "question_id": 1.1,
                    "answer": "WRONG-ANSWER-FROM-Q1a",
                    "confidence": 0.9,
                },
                {
                    "question_id": "11",
                    "answer": "REAL-ANSWER-FOR-Q11",
                    "confidence": 0.9,
                },
            ]
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].question_id, "11")
        self.assertEqual(result.answers[0].answer, "REAL-ANSWER-FOR-Q11")
        self.assertEqual(result.answer_drops, {"malformed_question_id": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_whole_numbered_float_question_id_still_salvaged(self) -> None:
        """A whole-numbered float (``5.0``) has no collision risk (it
        stringifies to ``"5"``, not to a different question's id) and must
        still be salvaged, not rejected alongside the fractional case."""
        result, mock_genai = self._run_with_answer(
            {"question_id": 5.0, "answer": "B", "confidence": 0.8}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].question_id, "5")
        self.assertEqual(result.answer_drops, {})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    # (13)-(15) a malformed ELEMENT inside the answers list -- review
    # MUST-FIX 6. Unlike shapes (1)-(11), which malform a FIELD on an
    # otherwise-dict answer, these malform the LIST ELEMENT itself, which
    # previously failed pydantic validation for the *whole* answers list
    # (every element, including any good ones) rather than just this one.
    def test_bare_string_list_element_does_not_lose_the_paper(self) -> None:
        result, mock_genai = self._run_with_answers(
            [
                {"question_id": "1", "answer": "B", "confidence": 0.8},
                "1: B",
            ]
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].question_id, "1")
        self.assertEqual(result.answer_drops, {"malformed_answer_shape": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_positional_list_element_does_not_lose_the_paper(self) -> None:
        result, mock_genai = self._run_with_answers(
            [
                {"question_id": "1", "answer": "B", "confidence": 0.8},
                ["1", "B", 0.8],
            ]
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].question_id, "1")
        self.assertEqual(result.answer_drops, {"malformed_answer_shape": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_null_list_element_does_not_lose_the_paper(self) -> None:
        """The review's headline example: ``{"answers": [{...39 good...},
        null]}`` used to lose all 39 for one bad element and pay for a
        corrective retry that failed identically -- verbatim the defect
        this story exists to fix, one structural level up."""
        result, mock_genai = self._run_with_answers(
            [
                {"question_id": "1", "answer": "B", "confidence": 0.8},
                None,
            ]
        )
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].question_id, "1")
        self.assertEqual(result.answer_drops, {"malformed_answer_shape": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    # Review MUST-FIX 7: answer_drops/confidence_repairs must actually be
    # published, not just persisted, so a live consumer can flag the loss.
    def test_answer_drops_and_confidence_repairs_are_published(self) -> None:
        frames: list[dict] = []

        def _spy(**payload: object) -> None:
            frames.append(payload)

        bus.subscribe(EventType.ANSWER_DROPPED, _spy)
        try:
            result, mock_genai = self._run_with_answers(
                [
                    {"question_id": "1", "answer": "B", "confidence": 0.8},
                    {"question_id": None, "answer": "C", "confidence": 0.8},
                    {"question_id": "3", "answer": "D", "confidence": float("nan")},
                ]
            )
        finally:
            bus.unsubscribe(EventType.ANSWER_DROPPED, _spy)

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["answer_drops"], {"missing_question_id": 1})
        self.assertEqual(frames[0]["confidence_repairs"], {"non_finite": 1})
        self.assertEqual(frames[0]["total_answers"], 3)
        self.assertEqual(result.answer_drops, {"missing_question_id": 1})
        self.assertEqual(result.confidence_repairs, {"non_finite": 1})

    def test_no_answer_drop_event_when_nothing_was_dropped_or_repaired(self) -> None:
        frames: list[dict] = []

        def _spy(**payload: object) -> None:
            frames.append(payload)

        bus.subscribe(EventType.ANSWER_DROPPED, _spy)
        try:
            self._run_with_answer({"question_id": "1", "answer": "B", "confidence": 0.8})
        finally:
            bus.unsubscribe(EventType.ANSWER_DROPPED, _spy)

        self.assertEqual(frames, [])

    # Review NIT A: a non-string source_region/working_out must not be
    # silently discarded with no recorded reason -- the answer survives
    # (this is cosmetic, never grading-relevant), but the repair is counted
    # like every other field's is.
    def test_numeric_source_region_is_dropped_with_a_recorded_reason(self) -> None:
        result, mock_genai = self._run_with_answer(
            {"question_id": "1", "answer": "B", "confidence": 0.8, "source_region": 7}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].source_region)
        self.assertEqual(result.field_repairs, {"malformed_source_region": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_numeric_working_out_is_dropped_with_a_recorded_reason(self) -> None:
        result, mock_genai = self._run_with_answer(
            {"question_id": "1", "answer": "B", "confidence": 0.8, "working_out": 42}
        )
        self.assertEqual(len(result.answers), 1)
        self.assertIsNone(result.answers[0].working_out)
        self.assertEqual(result.field_repairs, {"malformed_working_out": 1})
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_field_repairs_are_published_on_the_answer_dropped_event(self) -> None:
        frames: list[dict] = []

        def _spy(**payload: object) -> None:
            frames.append(payload)

        bus.subscribe(EventType.ANSWER_DROPPED, _spy)
        try:
            self._run_with_answer(
                {"question_id": "1", "answer": "B", "confidence": 0.8, "source_region": 7}
            )
        finally:
            bus.unsubscribe(EventType.ANSWER_DROPPED, _spy)

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["field_repairs"], {"malformed_source_region": 1})


class ContainerLevelMalformedResponseTests(unittest.TestCase):
    """US-031 review MUST-FIX 6 (accepted remainder): when ``answers``
    ITSELF is not a list at all -- absent, ``null``, or some other JSON
    type -- there is nothing to salvage per answer, since there is no list
    to walk. This is accepted, and pinned here deliberately, as a
    legitimate whole-paper loss rather than silently left uncounted or
    conflated with the eleven (now fifteen) shapes that ARE salvaged/dropped
    per answer. If this ever starts silently swallowing a real accuracy
    regression instead of raising, these tests will fail loudly."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.scan = Path(self.tmp) / "scan.pdf"
        _write_minimal_pdf(self.scan, pages=2)

    def _run_with_body(self, body: dict) -> MagicMock:
        client = _client_with_response(self.tmp, body)
        extractor = GeminiAnswerExtractor(client)
        with self.assertRaises(ParseError):
            extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        return client._client

    def test_answers_as_a_string_loses_the_paper(self) -> None:
        mock_genai = self._run_with_body({"answers": "no answers found on this paper"})
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_answers_as_a_dict_loses_the_paper(self) -> None:
        mock_genai = self._run_with_body({"answers": {"1": "B"}})
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_answers_key_absent_loses_the_paper(self) -> None:
        mock_genai = self._run_with_body({"results": []})
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_answers_as_null_loses_the_paper(self) -> None:
        mock_genai = self._run_with_body({"answers": None})
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)


class SourceBoxDropCountTests(unittest.TestCase):
    """I1 review should-fix 5: a dropped source_box (bad page or bad
    coordinate) must be counted and surfaced, not silently applied -- an
    extractor that hallucinates page indices must not look cleaner than one
    that returns wrong-but-in-range boxes on a later box-hit-rate metric."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.scan = Path(self.tmp) / "scan.pdf"
        _write_minimal_pdf(self.scan, pages=1)

    def test_drop_counts_are_published(self) -> None:
        body = {
            "answers": [
                {
                    "question_id": "1",
                    "answer": "a",
                    "confidence": 0.9,
                    "source_box": {"page": 99, "box": [100, 100, 200, 400]},  # bad page
                },
                {
                    "question_id": "2",
                    "answer": "b",
                    "confidence": 0.9,
                    "source_box": {"page": 0, "box": [100, 100, 200, 1500]},  # bad coord
                },
                {
                    "question_id": "3",
                    "answer": "c",
                    "confidence": 0.9,
                    "source_box": {"page": 0, "box": [100, 100, 200, 400]},  # fine
                },
            ]
        }
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        frames: list[dict] = []

        def _spy(**payload: object) -> None:
            frames.append(payload)

        bus.subscribe(EventType.SOURCE_BOX_DROPPED, _spy)
        try:
            result = extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        finally:
            bus.unsubscribe(EventType.SOURCE_BOX_DROPPED, _spy)

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["counts"], {"out_of_range_page": 1, "malformed_coordinates": 1})
        self.assertEqual(frames[0]["total_answers"], 3)
        # I1 review round 2, should-fix 4: the count must also be PERSISTED
        # on the result, not only published to a transient bus event -- a
        # box-hit-rate metric computed later, offline, from stored
        # ExtractedAnswers has no other way to tell "the model gave no box"
        # apart from "the model's box was dropped as unusable".
        self.assertEqual(
            result.source_box_drops, {"out_of_range_page": 1, "malformed_coordinates": 1}
        )

    def test_no_drops_publishes_nothing(self) -> None:
        body = {
            "answers": [
                {
                    "question_id": "1",
                    "answer": "a",
                    "confidence": 0.9,
                    "source_box": {"page": 0, "box": [100, 100, 200, 400]},
                },
            ]
        }
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        frames: list[dict] = []

        def _spy(**payload: object) -> None:
            frames.append(payload)

        bus.subscribe(EventType.SOURCE_BOX_DROPPED, _spy)
        try:
            result = extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        finally:
            bus.unsubscribe(EventType.SOURCE_BOX_DROPPED, _spy)

        self.assertEqual(frames, [])
        self.assertEqual(result.source_box_drops, {})


class RereadFailureTests(unittest.TestCase):
    """I1 review MUST-FIX 2: a failed re-read must degrade to the primary
    answer, never take the whole paper's extraction down with it."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.scan = Path(self.tmp) / "scan.pdf"
        _write_minimal_pdf(self.scan, pages=1)

    def test_a_failed_reread_keeps_the_primary_answer_and_the_rest_of_the_paper(self) -> None:
        body = {
            "answers": [
                {
                    "question_id": "1",
                    "answer": "low-confidence-primary-answer",
                    "confidence": 0.10,
                    "source_box": {"page": 0, "box": [100, 100, 200, 400]},
                },
                {
                    "question_id": "2",
                    "answer": "high-confidence-answer",
                    "confidence": 0.99,
                },
            ]
        }
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        extractor._rereader.reread = MagicMock(  # type: ignore[method-assign]
            side_effect=ExternalServiceError("503 INTERNAL")
        )

        failures: list[dict] = []

        def _spy(**payload: object) -> None:
            failures.append(payload)

        bus.subscribe(EventType.REREAD_FAILED, _spy)
        try:
            result = extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        finally:
            bus.unsubscribe(EventType.REREAD_FAILED, _spy)

        self.assertEqual(len(result.answers), 2)
        q1 = next(a for a in result.answers if a.question_id == "1")
        self.assertEqual(q1.answer, "low-confidence-primary-answer")
        self.assertIsNone(q1.answer_reread)
        self.assertIsNone(q1.reread_agreement)
        q2 = next(a for a in result.answers if a.question_id == "2")
        self.assertEqual(q2.answer, "high-confidence-answer")

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["question_id"], "1")
        extractor._rereader.reread.assert_called_once()

    def test_a_cost_ceiling_breach_propagates_and_stops_the_run(self) -> None:
        """I1 review round 2, MUST-FIX 1: the round 1 fix used
        ``except LemelyError``, which also catches ``CostCeilingError``
        (a subclass, raised by ``GeminiClient._check_cost_ceiling``) --
        turning a $14 USD / per-run token ceiling breach into an
        informational ``REREAD_FAILED`` event and letting the run continue
        past the guard the whole programme's budget depends on. A ceiling
        breach must propagate out of ``__call__`` instead, and must not
        trigger a second re-read attempt."""
        body = {
            "answers": [
                {
                    "question_id": "1",
                    "answer": "low-confidence-primary-answer",
                    "confidence": 0.10,
                    "source_box": {"page": 0, "box": [100, 100, 200, 400]},
                },
                {
                    "question_id": "2",
                    "answer": "also-low-confidence",
                    "confidence": 0.05,
                    "source_box": {"page": 0, "box": [100, 100, 200, 400]},
                },
            ]
        }
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        extractor._rereader.reread = MagicMock(  # type: ignore[method-assign]
            side_effect=CostCeilingError(
                "USD ceiling ($14.0000) exceeded; persistent cumulative spend is $14.00..."
            )
        )
        failures: list[dict] = []

        def _spy(**payload: object) -> None:
            failures.append(payload)

        bus.subscribe(EventType.REREAD_FAILED, _spy)
        try:
            with self.assertRaises(CostCeilingError):
                extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        finally:
            bus.unsubscribe(EventType.REREAD_FAILED, _spy)
        # No REREAD_FAILED frame -- a ceiling breach is not a per-answer
        # failure to report and move past.
        self.assertEqual(failures, [])
        # The breach on question "1" (processed first) must stop the run --
        # no second re-read attempt for question "2".
        extractor._rereader.reread.assert_called_once()


class RereadCapTests(unittest.TestCase):
    """I1 review should-fix 9: re-reads were uncapped -- 30 low-confidence
    answers on one paper meant 31 paid calls. The cap must actually bind,
    spend on the lowest-confidence answers first, and record when it
    binds."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.scan = Path(self.tmp) / "scan.pdf"
        _write_minimal_pdf(self.scan, pages=1)

    def test_cap_limits_rereads_to_the_lowest_confidence_answers_and_reports_it(self) -> None:
        n_answers = 20
        cap = 5
        # I1 review round 2, MUST-FIX 3: confidence = 0.01*i made document
        # order and ascending-confidence order identical, so reverting the
        # "lowest confidence first" sort to plain document order broke
        # nothing here. confidence = 0.01*((i*7) % 20) is a permutation of
        # the same 20 values, so document order and confidence order
        # deliberately differ -- the 5 lowest-confidence question_ids are
        # "0","3","6","9","12" (solving i*7 % 20 == k for k in 0..4), not
        # "0".."4".
        body = {
            "answers": [
                {
                    "question_id": str(i),
                    "answer": f"answer-{i}",
                    # every answer is low-confidence and has a box, so all
                    # 20 are individually eligible for a re-read; distinct
                    # confidences make "lowest first" checkable.
                    "confidence": round(0.01 * ((i * 7) % n_answers), 3),
                    "source_box": {"page": 0, "box": [10, 10, 20, 20]},
                }
                for i in range(n_answers)
            ]
        }
        expected_ids = {
            str(i) for i in sorted(range(n_answers), key=lambda i: (i * 7) % n_answers)[:cap]
        }
        self.assertEqual(expected_ids, {"0", "3", "6", "9", "12"})  # sanity-check the fixture

        extractor = GeminiAnswerExtractor(
            _client_with_response(self.tmp, body), max_rereads_per_paper=cap
        )
        seen_ids: list[str] = []

        def _fake_reread(answer, pages, *, extra_cache_key):  # type: ignore[no-untyped-def]
            seen_ids.append(answer.question_id)
            return answer.model_copy(
                update={"answer_reread": answer.answer, "reread_agreement": 1.0}
            )

        extractor._rereader.reread = MagicMock(side_effect=_fake_reread)  # type: ignore[method-assign]

        events: list[dict] = []

        def _spy(**payload: object) -> None:
            events.append(payload)

        bus.subscribe(EventType.REREAD_CAP_REACHED, _spy)
        try:
            result = extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        finally:
            bus.unsubscribe(EventType.REREAD_CAP_REACHED, _spy)

        self.assertEqual(extractor._rereader.reread.call_count, cap)
        # The cap is spent on the lowest-confidence answers first, not on
        # document order.
        self.assertEqual(set(seen_ids), expected_ids)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["eligible"], n_answers)
        self.assertEqual(events[0]["cap"], cap)
        self.assertEqual(events[0]["skipped"], n_answers - cap)

        # I1 review round 2, should-fix 4 (round 4: renamed rereads_run ->
        # reread_attempts and added rereads_eligible, SHOULD-FIX E): both
        # the number of re-reads attempted (post-cap) and the number that
        # were eligible (pre-cap), plus the threshold that gated them, are
        # persisted on the result for cost attribution -- not left only in
        # the transient REREAD_CAP_REACHED event above, and the cap's effect
        # (eligible vs. attempted) is reconstructible from the record alone.
        self.assertEqual(result.rereads_eligible, n_answers)
        self.assertEqual(result.reread_attempts, cap)
        self.assertEqual(result.reread_threshold, DEFAULT_CONFIDENCE_THRESHOLD)

    def test_default_cap_is_the_shipped_constant(self) -> None:
        """I1 review round 2, should-fix 5: both cap tests previously passed
        ``max_rereads_per_paper=`` explicitly, so the shipped
        ``DEFAULT_MAX_REREADS_PER_PAPER`` itself was unpinned (mutating 15 to
        999 broke zero tests). Construct the extractor with no override, on
        a FIXED 16-answer fixture (not sized off the constant under test --
        an earlier version of this test derived the fixture size from
        ``DEFAULT_MAX_REREADS_PER_PAPER``, which broke for the wrong reason
        under a 999 mutation: 1000 answers with confidence 0.01*i overflowed
        the [0, 1] confidence range and failed schema validation instead of
        exercising the cap), and pin the expected call count as a literal
        15, not the constant, so a mutation is caught by a mismatch rather
        than by the fixture blowing up."""
        n_answers = 16
        body = {
            "answers": [
                {
                    "question_id": str(i),
                    "answer": f"answer-{i}",
                    "confidence": round(0.01 * i, 3),
                    "source_box": {"page": 0, "box": [10, 10, 20, 20]},
                }
                for i in range(n_answers)
            ]
        }
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        extractor._rereader.reread = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda answer, pages, *, extra_cache_key: answer.model_copy(
                update={"answer_reread": answer.answer, "reread_agreement": 1.0}
            )
        )
        events: list[dict] = []

        def _spy(**payload: object) -> None:
            events.append(payload)

        bus.subscribe(EventType.REREAD_CAP_REACHED, _spy)
        try:
            extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        finally:
            bus.unsubscribe(EventType.REREAD_CAP_REACHED, _spy)

        self.assertEqual(extractor._rereader.reread.call_count, 15)
        self.assertEqual(events[0]["skipped"], 1)

    def test_no_cap_event_when_eligible_count_is_within_the_cap(self) -> None:
        body = {
            "answers": [
                {
                    "question_id": "1",
                    "answer": "x",
                    "confidence": 0.1,
                    "source_box": {"page": 0, "box": [10, 10, 20, 20]},
                },
            ]
        }
        extractor = GeminiAnswerExtractor(
            _client_with_response(self.tmp, body), max_rereads_per_paper=5
        )
        extractor._rereader.reread = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda answer, pages, *, extra_cache_key: answer.model_copy(
                update={"answer_reread": answer.answer, "reread_agreement": 1.0}
            )
        )
        events: list[dict] = []

        def _spy(**payload: object) -> None:
            events.append(payload)

        bus.subscribe(EventType.REREAD_CAP_REACHED, _spy)
        try:
            extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        finally:
            bus.unsubscribe(EventType.REREAD_CAP_REACHED, _spy)
        self.assertEqual(events, [])


class ScanQualityWarningPublishTests(unittest.TestCase):
    """I1 review should-fix 7: nothing in the suite drives
    SCAN_QUALITY_WARNING to actually fire -- deleting the publish block
    would fail nothing. Pin both directions: it fires on a bad scan and
    stays silent on a clean one."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _run_capturing(self, scan: Path) -> list[dict]:
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, {"answers": []}))
        frames: list[dict] = []

        def _spy(**payload: object) -> None:
            frames.append(payload)

        bus.subscribe(EventType.SCAN_QUALITY_WARNING, _spy)
        try:
            extractor(scan_path=scan, mark_scheme=_minimal_mcq_mark_scheme())
        finally:
            bus.unsubscribe(EventType.SCAN_QUALITY_WARNING, _spy)
        return frames

    def test_a_blank_scan_publishes_the_warning(self) -> None:
        scan = Path(self.tmp) / "blank.pdf"
        _write_minimal_pdf(scan)  # blank white page -> hygiene flags it as blank
        frames = self._run_capturing(scan)
        self.assertEqual(len(frames), 1)
        self.assertTrue(any("blank" in w for w in frames[0]["warnings"]))

    def test_a_clean_scan_publishes_nothing(self) -> None:
        scan = Path(self.tmp) / "clean.pdf"
        _write_content_pdf(scan)
        frames = self._run_capturing(scan)
        self.assertEqual(frames, [])
