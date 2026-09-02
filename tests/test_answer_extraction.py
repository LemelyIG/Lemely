"""Unit tests for GeminiAnswerExtractor (GeminiClient mocked)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from lemely.io.answer_extraction import GeminiAnswerExtractor, _calibrate_confidence
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import PathsSettings, load_settings
from lemely.runtime.events import EventType, bus


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
        self.scan = Path(self.tmp) / "scan.png"
        self.scan.write_bytes(b"\x89PNG\r\n\x1a\n")

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
        self.scan = Path(self.tmp) / "scan.png"
        self.scan.write_bytes(b"\x89PNG\r\n\x1a\n")

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
