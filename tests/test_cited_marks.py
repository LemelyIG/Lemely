"""Spec 2026-10-19 §4 B2 (fallback): evidence quotes checked against the mark scheme."""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from lemely.core.cited_marks import UNCITED_MARK, flag_uncited, scheme_text, uncited
from lemely.core.loose_schemas import Question
from lemely.core.schemas import (
    AIMarkResponse,
    AIMarkResponseCited,
    ExtractedAnswer,
    ExtractedAnswers,
    PointVerdict,
    marker_response_schema,
)
from lemely.io import correction_ai
from lemely.io.correction_ai import correct_paper
from lemely.runtime.config import MarkingOptions
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
        both = _mark(["gravity acts on it"], awarded=2, matched=["p1", "p2"])
        self.assertTrue(uncited(_leaf(), both))
        # Distinct quotes, each from its own point's text.
        ok = _mark(["gravity acts on it", "no air resistance"], awarded=2, matched=["p1", "p2"])
        self.assertFalse(uncited(_leaf(), ok))
        # The same quote twice, or a quote from the wrong point, does not cover both.
        twice = _mark(["gravity acts on it"] * 2, awarded=2, matched=["p1", "p2"])
        self.assertTrue(uncited(_leaf(), twice))
        # Two different quotes that both come from p2 leave p1 uncovered.
        wrong_point = _mark(
            ["no air resistance", "air resistance"], awarded=2, matched=["p1", "p2"]
        )
        self.assertTrue(uncited(_leaf(), wrong_point))

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


def _question(*points: dict[str, object]) -> Question:
    return Question.model_validate(
        {"id": "1", "marks": len(points), "type": "calculation", "answer_points": list(points)}
    )


class NormalisationTests(unittest.TestCase):
    """The prompt shows the scheme as JSON, so quotes copied from it must still match."""

    def test_a_quote_copied_with_json_escapes_cites(self) -> None:
        q = _question({"id": "p1", "point": "F = ma\nso a = F / m", "marks": 1})
        rendered = json.dumps("F = ma\nso a = F / m")[1:-1]
        self.assertIn("\\n", rendered)
        self.assertFalse(uncited(q, _mark([rendered], matched=["p1"])))
        self.assertFalse(uncited(q, _mark(["F = ma\nso a = F / m"], matched=["p1"])))

    def test_escaped_quotes_and_backslashes_cite(self) -> None:
        q = _question({"id": "p1", "point": 'says "stop" and \\neq', "marks": 1})
        rendered = json.dumps('says "stop" and \\neq')[1:-1]
        self.assertFalse(uncited(q, _mark([rendered], matched=["p1"])))

    def test_a_single_character_answer_cites_only_as_a_whole_value(self) -> None:
        q = _question(
            {"id": "p1", "point": "C", "marks": 1},
            {"id": "p2", "point": "answer is B or C", "marks": 1},
        )
        self.assertFalse(uncited(q, _mark(["C"], matched=["p1"])))
        # A one-letter slice of a longer value is not a citation.
        self.assertTrue(uncited(q, _mark(["B"], matched=["p2"])))
        self.assertTrue(uncited(q, _mark(["Z"], matched=["p1"])))

    def test_unicode_minus_and_curly_quotes_match_their_ascii_forms(self) -> None:
        q = _question({"id": "p1", "point": "v \u2212 u = 5\u00b0 \u201cdown\u201d", "marks": 1})
        self.assertFalse(uncited(q, _mark(['v - u = 5\u00b0 "down"'], matched=["p1"])))
        q2 = _question({"id": "p1", "point": "x - y \u00d7 2\u00b2", "marks": 1})
        self.assertFalse(uncited(q2, _mark(["x \u2212 y \u00d7 22"], matched=["p1"])))

    def test_invented_quotes_are_still_rejected(self) -> None:
        q = _question({"id": "p1", "point": "F = ma\nso a = F / m", "marks": 1})
        self.assertTrue(uncited(q, _mark(["the student wrote F = mb"], matched=["p1"])))

    def test_the_old_comparison_would_reject_the_rendered_quote(self) -> None:
        """Proof the new cases are red against the previous raw-string comparison."""
        raw = "F = ma\nso a = F / m"
        rendered = json.dumps(raw)[1:-1]
        old_norm = lambda t: " ".join(t.casefold().split())  # noqa: E731
        self.assertNotIn(old_norm(rendered), old_norm(raw))
        self.assertNotIn(old_norm("v \u2212 u"), old_norm("v - u"))
        self.assertLess(len(old_norm("C")), 3)


class LabelTests(unittest.TestCase):
    """Ids and the question type are labels, not mark-scheme wording."""

    def test_quoting_a_label_alone_is_uncited(self) -> None:
        q = _question({"id": "p_sc", "point": "v = d / t", "marks": 1})
        for label in ("calculation", "p_sc"):
            self.assertTrue(uncited(q, _mark([label], matched=[])), label)
            self.assertTrue(uncited(q, _mark([label], matched=["p_sc"])), label)
        self.assertNotIn("calculation", scheme_text(q))
        self.assertNotIn("p_sc", scheme_text(q))
        self.assertFalse(uncited(q, _mark(["v = d / t"], matched=["p_sc"])))

    def test_the_label_joined_to_a_point_is_uncited(self) -> None:
        q = _question({"id": "p1", "point": "v = d / t", "marks": 1})
        self.assertTrue(uncited(q, _mark(["p1\nv = d / t"], matched=["p1"])))

    def test_guidance_and_accept_text_still_cite(self) -> None:
        q = Question.model_validate(
            {
                "id": "1",
                "marks": 1,
                "type": "recall",
                "marking_guidance": "credit any unit conversion shown",
                "answer_points": [{"id": "p1", "point": "9.8", "marks": 1, "accept": ["g = 9.81"]}],
            }
        )
        self.assertFalse(uncited(q, _mark(["credit any unit conversion shown"], matched=[])))
        self.assertFalse(uncited(q, _mark(["g = 9.81"], matched=["p1"])))


class TerseTests(unittest.TestCase):
    def test_schema_choice(self) -> None:
        from lemely.core.schemas import AIMarkResponseCitedTerse, AIMarkResponseTerse

        self.assertIs(marker_response_schema(cited=False, terse=True), AIMarkResponseTerse)
        self.assertIs(marker_response_schema(cited=True, terse=True), AIMarkResponseCitedTerse)
        self.assertIs(marker_response_schema(cited=True, terse=False), AIMarkResponseCited)
        self.assertIs(marker_response_schema(cited=False), AIMarkResponse)

    def test_long_feedback_is_cut_not_refused(self) -> None:
        from lemely.core.schemas import TERSE_FEEDBACK_MAX_CHARS, AIMarkResponseTerse

        reply = AIMarkResponseTerse(awarded_marks=1, confidence=0.9, feedback="w " * 400)
        self.assertEqual(len(reply.feedback), TERSE_FEEDBACK_MAX_CHARS)

    def test_the_cap_is_asked_for_in_the_schema(self) -> None:
        from lemely.core.schemas import AIMarkResponseCitedTerse

        schema = AIMarkResponseCitedTerse.model_json_schema()
        self.assertIn("25 words", schema["properties"]["feedback"]["description"])
        self.assertIn("evidence_quotes", schema["properties"])
        self.assertNotIn("maxLength", schema["properties"]["feedback"])

    def test_the_corrector_picks_the_schema_from_the_flags(self) -> None:
        from lemely.core.schemas import AIMarkResponseCitedTerse, AIMarkResponseTerse
        from lemely.io.correction_ai import AICorrector

        def schema_for(*, cited: bool, terse: bool) -> type[AIMarkResponse]:
            client = MagicMock()
            gemini = client._settings.gemini
            gemini.correction_citations = cited
            gemini.correction_terse_rationale = terse
            return AICorrector(client)._mark_schema()

        self.assertIs(schema_for(cited=False, terse=False), AIMarkResponse)
        self.assertIs(schema_for(cited=False, terse=True), AIMarkResponseTerse)
        self.assertIs(schema_for(cited=True, terse=True), AIMarkResponseCitedTerse)


class SchemaTests(unittest.TestCase):
    def test_schema_choice(self) -> None:
        self.assertIs(marker_response_schema(cited=False), AIMarkResponse)
        self.assertIs(marker_response_schema(cited=True), AIMarkResponseCited)
        schema = AIMarkResponseCited.model_json_schema()
        self.assertIn("evidence_quotes", schema["properties"])
        self.assertIn("addresses_question", schema["required"])
        self.assertIn("evidence_quotes", schema["required"])


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


class EcfRemarkTests(unittest.TestCase):
    """An ECF re-mark keeps the citation check, judged on the mark that was kept."""

    def _run(self, remark_quotes: list[str]) -> object:
        from tests.test_correction_ai import ECFSubstitutionTests

        helper = ECFSubstitutionTests()

        def cited(
            verdicts: list[PointVerdict], quotes: list[str], marks: int
        ) -> AIMarkResponseCited:
            return AIMarkResponseCited(
                awarded_marks=marks,
                confidence=0.95,
                matched_point_ids=["p1"] if marks else [],
                feedback="fb",
                addresses_question="yes",
                evidence_quotes=quotes,
                point_verdicts=verdicts,
            )

        withheld = [helper._pv("p1", "withheld")]
        sequence = [
            cited(withheld, [], 0),
            cited(withheld, [], 0),
            cited([helper._pv("p1", "awarded")], remark_quotes, 1),
        ]
        with (
            patch.object(correction_ai.AICorrector, "mark_question", side_effect=sequence),
            patch.object(correction_ai.AICorrector, "citations_on", return_value=True),
        ):
            result = correct_paper(
                mark_scheme=helper._scheme(),
                extracted_answers=helper._extracted("wrong value", "consistent working"),
                gemini_client=MagicMock(),
                options=MarkingOptions(equivalence_gate=True, ecf_substitution=True),
            )
        return next(q for q in result.questions if q.question_id == "1a_ii")

    def test_an_uncited_remark_is_still_flagged(self) -> None:
        row = self._run(["nothing from the scheme"])
        self.assertEqual(row.awarded_marks, 1)
        self.assertTrue(row.needs_teacher_review)
        self.assertIn(UNCITED_MARK, row.review_reason or "")

    def test_a_cited_remark_is_not_flagged(self) -> None:
        row = self._run(["final numeric value"])
        self.assertEqual(row.awarded_marks, 1)
        self.assertNotIn(UNCITED_MARK, row.review_reason or "")
