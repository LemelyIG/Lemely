"""Per-model human-review threshold (``GeminiSettings.review_confidence_threshold_for``).

A correction model whose verbalised confidence runs on a different scale from
Gemini's gets its own review threshold. The threshold applies to the model whose
mark is final: a leaf escalated to another model is judged by that model's.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from lemely.core.loose_schemas import MarkScheme, Question
from lemely.core.schemas import (
    REVIEW_CONFIDENCE_THRESHOLD,
    AIMarkResponse,
    ExtractedAnswers,
    PointVerdict,
)
from lemely.io.correction_ai import (
    AICorrector,
    _build_ai_corrected,
    correct_paper,
    review_threshold_for,
)
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import GeminiSettings, PathsSettings, load_settings


@pytest.fixture
def isolated_env() -> Iterator[None]:
    snap = dict(os.environ)
    for k in list(os.environ):
        if k.startswith("LEMELY_"):
            del os.environ[k]
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snap)


def _question() -> Question:
    return Question.model_validate(
        {
            "id": "1",
            "marks": 2,
            "type": "explanation",
            "answer_points": [
                {"id": "p1", "point": "gravity", "marks": 1},
                {"id": "p2", "point": "speed", "marks": 1},
            ],
        }
    )


def _scheme() -> MarkScheme:
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Biology",
                "subject_code": "0610",
                "paper_number": 4,
                "paper_variant": 1,
                "session_month": "May/June",
                "session_year": 2021,
                "paper_type": "theory_extended",
                "maximum_mark": 2,
                "scheme_format": "point_based",
            },
            "questions": [_question().model_dump()],
        }
    )


def _extracted() -> ExtractedAnswers:
    return ExtractedAnswers.model_validate(
        {
            "paper_id": "p",
            "source_scan": "x.pdf",
            "answers": [{"question_id": "1", "answer": "gravity", "confidence": 0.95}],
        }
    )


def _mark(confidence: float, *, awarded: int = 1) -> AIMarkResponse:
    return AIMarkResponse(
        awarded_marks=awarded,
        confidence=confidence,
        feedback="f",
        matched_point_ids=["p1"] if awarded else [],
    )


class _FakeClient:
    """Answers ``generate_structured`` from a queue; correction thinks low, others high."""

    def __init__(self, gemini: GeminiSettings, responses: list[AIMarkResponse]) -> None:
        self._settings = SimpleNamespace(gemini=gemini)
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_structured(self, **kwargs: Any) -> AIMarkResponse:
        self.calls.append(kwargs)
        return self._responses.pop(0)

    def resolved_thinking(self, task_tag: str, model: str) -> str:
        return "low" if task_tag == "correction" else "high"


def _gemini(**overrides: Any) -> GeminiSettings:
    base: dict[str, Any] = {
        "correction_model": "cheap-model",
        "escalation_model": "strong-model",
        "escalation_confidence_threshold": 0.80,
        "review_confidence_threshold_for": {"cheap-model": 0.85},
    }
    return GeminiSettings(**{**base, **overrides})


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_field_rejects_a_threshold_outside_unit_interval() -> None:
    with pytest.raises(ValidationError):
        GeminiSettings(review_confidence_threshold_for={"m": 1.5})
    with pytest.raises(ValidationError):
        GeminiSettings(review_confidence_threshold_for={"m": -0.1})


def test_threshold_lookup_falls_back_to_the_global_constant() -> None:
    g = GeminiSettings(review_confidence_threshold_for={"m": 0.7})
    assert review_threshold_for(g, "m") == 0.7
    assert review_threshold_for(g, "gemini-3.8-flash") == REVIEW_CONFIDENCE_THRESHOLD
    assert review_threshold_for(g, None) == REVIEW_CONFIDENCE_THRESHOLD
    empty = GeminiSettings(review_confidence_threshold_for={})
    assert review_threshold_for(empty, "m") == REVIEW_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# The review decision itself
# ---------------------------------------------------------------------------


def test_builder_default_threshold_is_unchanged() -> None:
    cq = _build_ai_corrected(_question(), "gravity", _mark(0.86))
    assert cq.needs_teacher_review is True
    assert cq.review_reason == "confidence 0.86 below review threshold 0.90"


def test_builder_uses_the_given_threshold_on_the_legacy_path() -> None:
    passed = _build_ai_corrected(_question(), "gravity", _mark(0.86), review_threshold=0.85)
    assert passed.needs_teacher_review is False
    assert passed.review_reason is None
    flagged = _build_ai_corrected(_question(), "gravity", _mark(0.84), review_threshold=0.85)
    assert flagged.needs_teacher_review is True
    assert flagged.review_reason == "confidence 0.84 below review threshold 0.85"


def test_builder_uses_the_given_threshold_on_the_verdicts_path() -> None:
    def verdict_mark(confidence: float) -> AIMarkResponse:
        return AIMarkResponse(
            awarded_marks=1,
            confidence=confidence,
            feedback="f",
            point_verdicts=[
                PointVerdict(point_id="p1", verdict="awarded", evidence_span="gravity"),
                PointVerdict(point_id="p2", verdict="withheld"),
            ],
        )

    passed = _build_ai_corrected(
        _question(), "gravity", verdict_mark(0.86), equivalence_gate=True, review_threshold=0.85
    )
    assert passed.needs_teacher_review is False
    flagged = _build_ai_corrected(
        _question(), "gravity", verdict_mark(0.84), equivalence_gate=True, review_threshold=0.85
    )
    assert flagged.needs_teacher_review is True
    assert flagged.review_reason == "confidence 0.84 below review threshold 0.85"
    default = _build_ai_corrected(_question(), "gravity", verdict_mark(0.86), equivalence_gate=True)
    assert default.needs_teacher_review is True


def test_structural_flags_ignore_the_override() -> None:
    # 3 marks on a 2-mark question: out of range, flagged at any confidence.
    cq = _build_ai_corrected(_question(), "gravity", _mark(0.99, awarded=3), review_threshold=0.0)
    assert cq.needs_teacher_review is True


# ---------------------------------------------------------------------------
# Which model's threshold: the model whose mark is final
# ---------------------------------------------------------------------------


def _mark_paper(gemini: GeminiSettings, responses: list[AIMarkResponse]) -> tuple[Any, _FakeClient]:
    fake = _FakeClient(gemini, responses)
    result = correct_paper(_scheme(), _extracted(), gemini_client=cast("GeminiClient", fake))
    return result.questions[0], fake


def test_override_applies_to_the_listed_correction_model() -> None:
    cq, fake = _mark_paper(_gemini(), [_mark(0.86)])
    assert len(fake.calls) == 1
    assert cq.needs_teacher_review is False
    assert cq.confidence_score == 0.86


def test_unlisted_correction_model_keeps_the_global_threshold() -> None:
    cq, _ = _mark_paper(_gemini(correction_model="gemini-3.8-flash"), [_mark(0.86)])
    assert cq.needs_teacher_review is True
    assert cq.review_reason == "confidence 0.86 below review threshold 0.90"


def test_empty_map_keeps_the_global_threshold() -> None:
    cq, _ = _mark_paper(_gemini(review_confidence_threshold_for={}), [_mark(0.86)])
    assert cq.needs_teacher_review is True
    assert cq.review_reason == "confidence 0.86 below review threshold 0.90"


def test_borderline_retry_stays_on_the_correction_models_threshold() -> None:
    # first pass 0.5 -> borderline retry (same model, thinking high) 0.86 -> no escalation
    gemini = _gemini(escalation_model=None)
    cq, fake = _mark_paper(gemini, [_mark(0.5), _mark(0.86)])
    assert [c["task_tag"] for c in fake.calls] == ["correction", "correction_borderline"]
    assert cq.needs_teacher_review is False


def test_escalated_mark_is_judged_by_the_escalation_models_threshold() -> None:
    # first 0.5 -> borderline 0.6 -> escalation (strong-model) 0.86: strong-model is unlisted
    cq, fake = _mark_paper(_gemini(), [_mark(0.5), _mark(0.6), _mark(0.86)])
    assert [c["task_tag"] for c in fake.calls] == [
        "correction",
        "correction_borderline",
        "escalation",
    ]
    assert cq.needs_teacher_review is True
    assert cq.review_reason == "confidence 0.86 below review threshold 0.90"


def test_cascade_strong_mark_is_judged_by_the_strong_models_threshold() -> None:
    gemini = _gemini(cascade_enabled=True, cascade_strong_model="strong-model")
    cq, fake = _mark_paper(gemini, [_mark(0.5), _mark(0.86)])
    assert [c["task_tag"] for c in fake.calls] == ["correction", "escalation"]
    assert cq.needs_teacher_review is True


def test_cascade_first_pass_kept_uses_the_cheap_models_threshold() -> None:
    gemini = _gemini(cascade_enabled=True, cascade_strong_model="strong-model")
    cq, fake = _mark_paper(gemini, [_mark(0.86)])
    assert len(fake.calls) == 1
    assert cq.needs_teacher_review is False


def test_marking_model_is_recorded_per_call() -> None:
    fake = _FakeClient(_gemini(), [_mark(0.5), _mark(0.6), _mark(0.95), _mark(0.95)])
    ai = AICorrector(cast("GeminiClient", fake))
    assert ai.last_mark_model is None
    ai.mark_question(_question(), "gravity")
    assert ai.last_mark_model == "strong-model"
    ai.mark_question(_question(), "gravity")
    assert ai.last_mark_model == "cheap-model"


# ---------------------------------------------------------------------------
# Post-processing only: TOML round-trip, and prompts/cache keys unchanged
# ---------------------------------------------------------------------------


def test_toml_table_loads(tmp_path: Path, isolated_env: None) -> None:
    toml = tmp_path / "lemely.toml"
    toml.write_text('[gemini]\nreview_confidence_threshold_for = { "m" = 0.7 }\n')
    s = load_settings(toml_path=toml, cwd=tmp_path)
    assert s.gemini.review_confidence_threshold_for == {"m": 0.7}


def _sdk_reply(confidence: float) -> MagicMock:
    body = json.dumps(
        {"awarded_marks": 1, "confidence": confidence, "matched_point_ids": [], "feedback": "f"}
    )
    return MagicMock(
        text=body,
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(
            prompt_token_count=10, candidates_token_count=20, cached_content_token_count=0
        ),
    )


def _call_fingerprints(tmp: Path, table: dict[str, float]) -> list[tuple[str, str, str, str]]:
    base = load_settings(toml_path=None, cwd=tmp)
    settings = base.model_copy(
        update={
            "paths": PathsSettings(cache_dir=tmp / ".cache", output_dir=tmp / "outputs"),
            "gemini": base.gemini.model_copy(
                update={
                    "correction_model": "gemini-3.8-flash",
                    "review_confidence_threshold_for": table,
                }
            ),
        }
    )
    genai = MagicMock()
    genai.models.generate_content.side_effect = [_sdk_reply(0.5), _sdk_reply(0.6), _sdk_reply(0.95)]
    client = GeminiClient(settings, _genai_client=genai)
    seen: list[tuple[str, str, str, str]] = []
    real = client._structured_cache_key

    def _spy(**kwargs: Any) -> tuple[str, str]:
        model, key = real(**kwargs)
        seen.append((kwargs["task_tag"], key, kwargs["system_prompt"], kwargs["user_prompt"]))
        return model, key

    with patch.object(client, "_structured_cache_key", side_effect=_spy):
        AICorrector(client).mark_question(_question(), "gravity")
    return seen


def test_threshold_is_in_no_prompt_or_cache_key(tmp_path: Path, isolated_env: None) -> None:
    empty = _call_fingerprints(tmp_path / "a", {})
    listed = _call_fingerprints(tmp_path / "b", {"gemini-3.8-flash": 0.5, "x": 0.99})
    assert empty
    assert listed == empty
