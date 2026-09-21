"""``get_self_review_service``'s judge wiring: a judge only when a key exists.

Without a Gemini key the service must run with ``judge=None`` — every
evidence-backed challenge then lands in the teacher queue as
``student_evidence_unjudged`` — rather than constructing a client that would
fail on first use and turn an infrastructure gap into a silent verdict.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lemely.io.evidence_judge import GeminiEvidenceJudge
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import Settings
from lemely.web.deps import build_self_review_judge, get_self_review_service, get_settings


def _settings(*, key: str | None) -> Settings:
    data = Settings().model_dump()
    data["gemini_api_key"] = key
    return Settings.model_validate(data)


def test_no_key_means_no_judge() -> None:
    assert build_self_review_judge(_settings(key=None), MagicMock(spec=GeminiClient)) is None


def test_a_key_means_the_gemini_judge() -> None:
    judge = build_self_review_judge(_settings(key="test-key"), MagicMock(spec=GeminiClient))
    assert isinstance(judge, GeminiEvidenceJudge)


def test_the_service_singleton_carries_the_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_self_review_service`` must actually use ``build_self_review_judge``.

    The two tests above exercise the helper in isolation; neither proves the
    singleton wires it in rather than, say, still passing ``judge=None``
    outright. Reverting ``get_self_review_service`` to ``judge=None`` must
    fail this test — a silent revert would otherwise route every
    evidence-backed challenge to the teacher queue with the whole suite
    green.
    """
    get_self_review_service.cache_clear()
    get_settings.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    try:
        assert isinstance(get_self_review_service()._judge, GeminiEvidenceJudge)
    finally:
        get_self_review_service.cache_clear()
        get_settings.cache_clear()


def test_the_service_singleton_carries_no_judge_without_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirror of the above: no key configured means the singleton's judge is ``None``."""
    get_self_review_service.cache_clear()
    get_settings.cache_clear()
    monkeypatch.delenv("LEMELY_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    try:
        assert get_self_review_service()._judge is None
    finally:
        get_self_review_service.cache_clear()
        get_settings.cache_clear()
