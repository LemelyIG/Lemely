"""Spec 2026-10-19 §4 B2 (fallback): evidence quotes checked against the mark scheme."""

from __future__ import annotations

import json
import tempfile
import unittest

from lemely.core.cited_marks import UNCITED_MARK, flag_uncited, scheme_text, uncited
from lemely.core.schemas import (
    AIMarkResponse,
    AIMarkResponseCited,
    ExtractedAnswer,
    ExtractedAnswers,
    marker_response_schema,
)
from lemely.io.correction_ai import correct_paper
from tests.gemini_fakes import mock_response
from tests.test_correction_ai import _client_with_seq, _hybrid_paper_mark_scheme


def _leaf():
    return next(q for q in _hybrid_paper_mark_scheme().all_questions_flat() if q.id == "2")


def _quote() -> str:
    return max(scheme_text(_leaf()).split("\n"), key=len)


def _mark(
    quotes: list[str], *, awarded: int = 1, matched: list[str] | None = None
) -> AIMarkResponseCited:
    return AIMarkResponseCited(
        awarded_marks=awarded,
        confidence=0.95,
        matched_point_ids=matched or [],
        feedback="f",
        addresses_question="yes",
        evidence_quotes=quotes,
    )


class CheckTests(unittest.TestCase):
    def test_a_verbatim_quote_cites(self) -> None:
        self.assertFalse(uncited(_leaf(), _mark([_quote()])))

    def test_case_and_spacing_do_not_matter(self) -> None:
        self.assertFalse(
            uncited(_leaf(), _mark(["  " + _quote().upper().replace(" ", "   ") + " "]))
        )

    def test_no_quote_is_uncited(self) -> None:
        self.assertTrue(uncited(_leaf(), _mark([])))

    def test_a_quote_not_in_the_scheme_is_uncited(self) -> None:
        self.assertTrue(uncited(_leaf(), _mark([_quote(), "the student wrote this"])))

    def test_one_quote_per_matched_point(self) -> None:
        self.assertTrue(uncited(_leaf(), _mark([_quote()], awarded=2, matched=["M1", "A1"])))
        self.assertFalse(
            uncited(_leaf(), _mark([_quote(), _quote()], awarded=2, matched=["M1", "A1"]))
        )

    def test_zero_marks_need_no_quote(self) -> None:
        self.assertFalse(uncited(_leaf(), _mark([], awarded=0)))

    def test_a_plain_response_has_no_quotes(self) -> None:
        plain = AIMarkResponse(awarded_marks=1, confidence=0.9, feedback="f")
        self.assertTrue(uncited(_leaf(), plain))

    def test_flag_appends_to_an_existing_reason(self) -> None:
        from lemely.core.schemas import CorrectedQuestion

        cq = CorrectedQuestion.model_construct(
            needs_teacher_review=False, review_reason="low confidence"
        )
        flagged = flag_uncited(cq)
        self.assertTrue(flagged.needs_teacher_review)
        self.assertEqual(flagged.review_reason, f"low confidence | {UNCITED_MARK}")
        self.assertEqual(
            flag_uncited(cq.model_copy(update={"review_reason": None})).review_reason, UNCITED_MARK
        )


class SchemaTests(unittest.TestCase):
    def test_schema_choice(self) -> None:
        self.assertIs(marker_response_schema(cited=False), AIMarkResponse)
        self.assertIs(marker_response_schema(cited=True), AIMarkResponseCited)
        schema = AIMarkResponseCited.model_json_schema()
        self.assertIn("evidence_quotes", schema["properties"])
        self.assertIn("addresses_question", schema["required"])


class PipelineTests(unittest.TestCase):
    def _run(self, quotes: list[str], *, on: bool) -> object:
        tmp = tempfile.mkdtemp()
        reply: dict[str, object] = {
            "awarded_marks": 1,
            "confidence": 0.97,
            "matched_point_ids": [],
            "feedback": "ok",
            "addresses_question": "yes",
        }
        if on:
            # With the flag off the schema has no such field (and forbids extras).
            reply["evidence_quotes"] = quotes
        client = _client_with_seq(tmp, [mock_response(json.dumps(reply))])
        client._settings = client._settings.model_copy(
            update={
                "gemini": client._settings.gemini.model_copy(update={"correction_citations": on})
            }
        )
        extracted = ExtractedAnswers(
            paper_id="t",
            source_scan="s.png",
            answers=[ExtractedAnswer(question_id="2", answer="an answer", confidence=0.99)],
        )
        result = correct_paper(
            mark_scheme=_hybrid_paper_mark_scheme(),
            extracted_answers=extracted,
            gemini_client=client,
        )
        return next(q for q in result.questions if q.question_id == "2")

    def test_an_uncited_mark_goes_to_review(self) -> None:
        q2 = self._run(["not in the scheme"], on=True)
        self.assertTrue(q2.needs_teacher_review)
        self.assertIn(UNCITED_MARK, q2.review_reason or "")

    def test_a_cited_mark_is_not_flagged(self) -> None:
        q2 = self._run([_quote()], on=True)
        self.assertNotIn(UNCITED_MARK, q2.review_reason or "")

    def test_flag_off_checks_nothing(self) -> None:
        q2 = self._run([], on=False)
        self.assertNotIn(UNCITED_MARK, q2.review_reason or "")
