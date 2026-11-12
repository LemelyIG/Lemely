"""The web gates that need an API key read the key of the provider their task tag's model uses."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from lemely.io.evidence_judge import GeminiEvidenceJudge
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import Settings, llm_key_configured
from lemely.web.deps import build_self_review_judge
from lemely.web.routers import teacher

_TAGS = ("scan_metadata", "generation", "self_review_judge", "extraction")


def _keys(*, anthropic: bool, gemini: bool) -> Settings:
    return Settings().model_copy(
        update={
            "anthropic_api_key": SecretStr("k") if anthropic else None,
            "gemini_api_key": SecretStr("k") if gemini else None,
        }
    )


@pytest.mark.parametrize("tag", _TAGS)
def test_a_claude_only_deployment_has_every_gate_enabled(tag: str) -> None:
    assert llm_key_configured(_keys(anthropic=True, gemini=False), tag) is True


@pytest.mark.parametrize("tag", _TAGS)
def test_a_gemini_key_alone_does_not_enable_a_claude_tag(tag: str) -> None:
    assert llm_key_configured(_keys(anthropic=False, gemini=True), tag) is False


def test_a_gemini_tag_needs_the_gemini_key() -> None:
    s = _keys(anthropic=True, gemini=False)
    s = s.model_copy(
        update={
            "gemini": s.gemini.model_copy(update={"scan_metadata_model": "gemini-3.5-flash-lite"})
        }
    )
    assert llm_key_configured(s, "scan_metadata") is False
    assert llm_key_configured(
        s.model_copy(update={"gemini_api_key": SecretStr("k")}), "scan_metadata"
    )


def test_an_empty_key_is_not_a_key() -> None:
    s = Settings().model_copy(update={"anthropic_api_key": SecretStr("")})
    assert llm_key_configured(s, "scan_metadata") is False


def test_detection_gate_follows_the_scan_metadata_provider() -> None:
    assert teacher._detection_available(_keys(anthropic=True, gemini=False)) is True
    assert teacher._detection_available(_keys(anthropic=False, gemini=True)) is False


def test_self_review_judge_gate_follows_its_provider() -> None:
    client = MagicMock(spec=GeminiClient)
    judge = build_self_review_judge(_keys(anthropic=True, gemini=False), client)
    assert isinstance(judge, GeminiEvidenceJudge)
    assert build_self_review_judge(_keys(anthropic=False, gemini=True), client) is None


@pytest.mark.parametrize(
    ("anthropic", "gemini", "expected"), [(True, False, True), (False, True, False)]
)
def test_health_reports_whether_marking_can_run(
    monkeypatch: pytest.MonkeyPatch, anthropic: bool, gemini: bool, expected: bool
) -> None:
    from fastapi.testclient import TestClient

    from lemely.web import create_app
    from lemely.web.deps import get_settings

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _keys(anthropic=anthropic, gemini=gemini)
    assert TestClient(app).get("/api/health").json()["apiKeyConfigured"] is expected


@pytest.mark.parametrize(
    ("anthropic", "gemini", "generates"), [(True, False, True), (False, True, False)]
)
def test_quiz_generation_gate_follows_the_generation_provider(
    monkeypatch: pytest.MonkeyPatch, anthropic: bool, gemini: bool, generates: bool
) -> None:
    import uuid

    sentinel = MagicMock(name="aggregate")
    builder = MagicMock()
    builder.build.return_value = []
    monkeypatch.setattr(teacher, "_aggregate_history_weaknesses", lambda store: sentinel)
    monkeypatch.setattr(teacher, "_existing_questions", lambda *a, **k: [])
    monkeypatch.setattr(teacher, "TeacherQuizBuilder", lambda *a, **k: builder)
    monkeypatch.setattr(teacher, "QuestionGenerator", lambda client: MagicMock())
    teacher._build_quiz(
        _keys(anthropic=anthropic, gemini=gemini),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        uuid.uuid4(),
        [],
        subject_code="0625",
        count=1,
        topics=[],
    )
    assert (builder.build.call_args.args[1] is sentinel) is generates
