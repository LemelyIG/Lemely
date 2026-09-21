"""``get_self_review_service``'s judge wiring: a judge only when a key exists.

Without a Gemini key the service must run with ``judge=None`` — every
evidence-backed challenge then lands in the teacher queue as
``student_evidence_unjudged`` — rather than constructing a client that would
fail on first use and turn an infrastructure gap into a silent verdict.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from lemely.io.evidence_judge import GeminiEvidenceJudge
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import Settings
from lemely.web.deps import build_self_review_judge


def _settings(*, key: str | None) -> Settings:
    data = Settings().model_dump()
    data["gemini_api_key"] = key
    return Settings.model_validate(data)


def test_no_key_means_no_judge() -> None:
    assert build_self_review_judge(_settings(key=None), MagicMock(spec=GeminiClient)) is None


def test_a_key_means_the_gemini_judge() -> None:
    judge = build_self_review_judge(_settings(key="test-key"), MagicMock(spec=GeminiClient))
    assert isinstance(judge, GeminiEvidenceJudge)
