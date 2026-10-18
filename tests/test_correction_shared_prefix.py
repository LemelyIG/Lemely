"""Shared per-paper prompt prefix for caching (cost-ladder lever A3)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from lemely.core.loose_schemas import MarkScheme, Question
from lemely.core.schemas import AIMarkResponse
from lemely.io.correction_ai import AICorrector
from lemely.io.gemini import (
    PREFIX_CACHE_TASK_TAG,
    GeminiClient,
    SharedPrefix,
    process_call_records,
    reset_process_counters,
)
from lemely.io.prompts.correction_ai import (
    VERSION,
    build_marker_user_prompt,
    build_shared_prefix,
    marker_system_prompt,
    printed_principles,
)
from lemely.io.providers.anthropic_adapter import AnthropicReply, Usage
from lemely.runtime.config import GeminiSettings, PathsSettings, Settings, load_settings

_GOLDEN = Path(__file__).parent / "golden"

#: Implicit caching on Gemini 3.x needs a shared prefix of at least this many tokens.
_IMPLICIT_MIN_TOKENS = 4096


def _scheme(case_prefix: str) -> MarkScheme:
    path = next(_GOLDEN.glob(f"{case_prefix}*/mark_scheme.json"))
    return MarkScheme.model_validate_json(path.read_text(encoding="utf-8"))


def _paper_schemes() -> dict[str, MarkScheme]:
    """One mark scheme per distinct cost-201 paper, keyed by paper code."""
    out: dict[str, MarkScheme] = {}
    for path in sorted(_GOLDEN.glob("*/mark_scheme.json")):
        code = "_".join(path.parent.name.split("_")[:4])
        out.setdefault(code, MarkScheme.model_validate_json(path.read_text(encoding="utf-8")))
    return out


def _leaves(scheme: MarkScheme) -> list[Question]:
    return [q for q in scheme.all_questions_flat() if q.marks > 0 and not q.parts]


def _mark(awarded: int, confidence: float) -> AIMarkResponse:
    return AIMarkResponse(awarded_marks=awarded, confidence=confidence, feedback="f")


class _FakeClient:
    """Records every ``generate_structured`` call and answers from a queue."""

    def __init__(self, gemini: GeminiSettings, responses: list[AIMarkResponse]) -> None:
        self._settings = SimpleNamespace(gemini=gemini)
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_structured(self, **kwargs: Any) -> AIMarkResponse:
        self.calls.append(kwargs)
        return self._responses.pop(0)

    def resolved_thinking(self, task_tag: str, model: str) -> str:
        return "low" if task_tag == "correction" else "high"


def _settings(**overrides: Any) -> GeminiSettings:
    base: dict[str, Any] = {
        "correction_model": "gemini-3.8-flash",
        "escalation_model": "gemini-3.8-flash",
        "escalation_confidence_threshold": 0.80,
    }
    return GeminiSettings(**{**base, **overrides})


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


def _real_settings(tmp: Path, **gemini: Any) -> Settings:
    s = load_settings(toml_path=None, cwd=tmp)
    return s.model_copy(
        update={
            "paths": PathsSettings(cache_dir=tmp / ".cache", output_dir=tmp / "outputs"),
            "gemini": s.gemini.model_copy(update=gemini),
        }
    )


def _genai_response(confidence: float = 0.95) -> MagicMock:
    body = json.dumps(
        {"awarded_marks": 1, "confidence": confidence, "matched_point_ids": [], "feedback": "f"}
    )
    return MagicMock(
        text=body,
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(
            prompt_token_count=6000,
            candidates_token_count=20,
            thoughts_token_count=0,
            cached_content_token_count=5000,
        ),
    )


# ---------------------------------------------------------------------------
# Flag off
# ---------------------------------------------------------------------------


def test_flag_off_prompts_unchanged() -> None:
    scheme = _scheme("0625_s20_qp_31")
    leaf = _leaves(scheme)[0]
    principles = printed_principles(scheme.metadata)
    for corrector_scheme in (None, scheme):
        fake = _FakeClient(_settings(), [_mark(1, 0.95)])
        corrector = AICorrector(cast("GeminiClient", fake), mark_scheme=corrector_scheme)
        corrector.mark_question(leaf, "the answer", "some working", principles=principles)
        (call,) = fake.calls
        assert call["system_prompt"] == marker_system_prompt()
        assert call["user_prompt"] == build_marker_user_prompt(
            leaf, "the answer", "some working", None, principles
        )
        # A fake with a fixed signature must keep working: nothing new is sent.
        assert "shared_prefix" not in call


def test_flag_on_without_scheme_prompts_unchanged() -> None:
    """A caller that never hands over the paper's scheme is marked as before."""
    scheme = _scheme("0625_s20_qp_31")
    leaf = _leaves(scheme)[0]
    fake = _FakeClient(_settings(correction_shared_prefix=True), [_mark(1, 0.95)])
    AICorrector(cast("GeminiClient", fake)).mark_question(leaf, "x")
    assert fake.calls[0]["system_prompt"] == marker_system_prompt()
    assert "shared_prefix" not in fake.calls[0]


# ---------------------------------------------------------------------------
# Flag on
# ---------------------------------------------------------------------------


def test_prefix_is_deterministic_and_in_source_order() -> None:
    scheme = _scheme("0625_s20_qp_31")
    again = MarkScheme.model_validate_json(scheme.model_dump_json())
    prefix = build_shared_prefix(scheme, reader_describes_drawings=False)
    assert prefix == build_shared_prefix(again, reader_describes_drawings=False)
    assert prefix.startswith(marker_system_prompt())
    positions = [prefix.index(f'"id": "{q.id}"') for q in scheme.questions]
    assert positions == sorted(positions)
    reader = build_shared_prefix(scheme, reader_describes_drawings=True)
    assert reader.startswith(marker_system_prompt(reader_describes_drawings=True))


def test_prefix_identical_across_leaves_and_scripts() -> None:
    scheme = _scheme("0625_s20_qp_31")
    leaves = _leaves(scheme)
    assert len(leaves) >= 2
    expected = build_shared_prefix(scheme, reader_describes_drawings=False)
    systems: list[str] = []
    # Two scripts of the same paper, each marking every leaf. The cascade is on
    # with a low-confidence first pass, so the strong re-mark runs too.
    for answer in ("first script answer", "second script answer"):
        responses = [r for _ in leaves for r in (_mark(0, 0.3), _mark(1, 0.95))]
        fake = _FakeClient(
            _settings(
                correction_shared_prefix=True,
                cascade_enabled=True,
                cascade_strong_model="strong-model",
            ),
            responses,
        )
        corrector = AICorrector(cast("GeminiClient", fake), mark_scheme=scheme)
        for leaf in leaves:
            corrector.mark_question(leaf, answer)
        assert {c["attempt"] for c in fake.calls} == {"first", "escalation"}
        systems.extend(c["system_prompt"] for c in fake.calls)
        for call in fake.calls:
            prefix = call["shared_prefix"]
            assert isinstance(prefix, SharedPrefix)
            assert prefix.text == call["system_prompt"]
            assert prefix.version == VERSION
    assert set(systems) == {expected}


def test_prefix_on_every_non_cascade_retry() -> None:
    """The borderline retry and the escalation share the first pass's prefix."""
    scheme = _scheme("0625_s20_qp_31")
    leaf = _leaves(scheme)[0]
    fake = _FakeClient(
        _settings(correction_shared_prefix=True, escalation_model="gemini-3.9-pro"),
        [_mark(0, 0.3), _mark(0, 0.4), _mark(1, 0.95)],
    )
    AICorrector(cast("GeminiClient", fake), mark_scheme=scheme).mark_question(leaf, "x")
    assert [c["attempt"] for c in fake.calls] == ["first", "borderline", "escalation"]
    expected = build_shared_prefix(scheme, reader_describes_drawings=False)
    assert {c["system_prompt"] for c in fake.calls} == {expected}


def test_leaf_text_only_in_user_prompt() -> None:
    scheme = _scheme("0625_s20_qp_31")
    leaf = _leaves(scheme)[1]
    principles = printed_principles(scheme.metadata)
    answer = "STUDENT-ANSWER-SENTINEL resistance rises"
    working = "WORKING-SENTINEL 3 x 4 = 12"
    fake = _FakeClient(_settings(correction_shared_prefix=True), [_mark(1, 0.95)])
    AICorrector(cast("GeminiClient", fake), mark_scheme=scheme).mark_question(
        leaf, answer, working, prior_results={"1a": 1}, principles=principles
    )
    (call,) = fake.calls
    for leaf_text in ("STUDENT-ANSWER-SENTINEL", "WORKING-SENTINEL", "PRIOR PART RESULTS"):
        assert leaf_text in call["user_prompt"]
        assert leaf_text not in call["system_prompt"]
    # The leaf-specific prompt is exactly what the flag-off path sends.
    assert call["user_prompt"] == build_marker_user_prompt(
        leaf, answer, working, {"1a": 1}, principles
    )


def test_prefix_at_least_4096_tokens_on_cost201_papers(
    record_property: Callable[[str, object], None],
) -> None:
    """Report each cost-201 paper's prefix size (``len(text) // 4`` tokens).

    The golden schemes are excerpts, so not every paper reaches Gemini's implicit
    caching floor. The papers that do are pinned: a change that shrinks one below
    the floor, or lifts another above it, fails here and must be looked at.
    """
    sizes = {
        code: len(build_shared_prefix(scheme, reader_describes_drawings=False)) // 4
        for code, scheme in _paper_schemes().items()
    }
    record_property("shared_prefix_tokens", sizes)
    assert len(sizes) == 5, sizes
    reaching = {code for code, tokens in sizes.items() if tokens >= _IMPLICIT_MIN_TOKENS}
    assert reaching == _PAPERS_REACHING_FLOOR, sizes
    system_only = len(marker_system_prompt()) // 4
    assert all(tokens > system_only for tokens in sizes.values()), sizes


#: The cost-201 papers whose prefix reaches the floor. Measured 2026-10-19 on the
#: golden excerpts: none does. The system prompt is ~1,762 tokens and the largest
#: excerpt scheme adds ~1,600, so the largest prefix is ~3,350 (0606_s23_qp_12).
_PAPERS_REACHING_FLOOR: set[str] = set()


# ---------------------------------------------------------------------------
# Provider caching
# ---------------------------------------------------------------------------


def test_explicit_cache_created_once_per_paper(tmp_path: Path, isolated_env: None) -> None:
    reset_process_counters()
    settings = _real_settings(
        tmp_path,
        correction_shared_prefix=True,
        correction_prefix_cache="explicit",
        correction_model="gemini-3.8-flash",
    )
    genai = MagicMock()
    genai.caches.create.side_effect = [
        SimpleNamespace(
            name=f"cachedContents/paper{i}",
            usage_metadata=SimpleNamespace(total_token_count=5000),
        )
        for i in range(2)
    ]
    genai.models.generate_content.side_effect = lambda **_: _genai_response()
    client = GeminiClient(settings, _genai_client=genai, default_cache_mode="bypass")

    scheme = _scheme("0625_s20_qp_31")
    leaves = _leaves(scheme)[:3]
    for _script in range(2):
        corrector = AICorrector(client, mark_scheme=scheme)
        for leaf in leaves:
            corrector.mark_question(leaf, "an answer")
    assert genai.caches.create.call_count == 1
    create_kwargs = genai.caches.create.call_args.kwargs
    assert create_kwargs["model"] == "gemini-3.8-flash"
    assert create_kwargs["config"].ttl == "600s"
    assert create_kwargs["config"].system_instruction == build_shared_prefix(
        scheme, reader_describes_drawings=False
    )
    configs = [c.kwargs["config"] for c in genai.models.generate_content.call_args_list]
    assert len(configs) == 6
    assert {c.cached_content for c in configs} == {"cachedContents/paper0"}
    assert all(c.system_instruction is None for c in configs)

    # A second paper gets its own cache.
    other = _scheme("0606_s23_qp_12")
    AICorrector(client, mark_scheme=other).mark_question(_leaves(other)[0], "x")
    assert genai.caches.create.call_count == 2

    # Creation and 10 minutes of storage are on the spend record, not omitted.
    cache_records = [r for r in process_call_records() if r.task_tag == PREFIX_CACHE_TASK_TAG]
    assert len(cache_records) == 2
    assert all(r.input_tokens == 5000 and r.usd_2027 > 0 for r in cache_records)


def test_explicit_cache_falls_back_on_creation_failure(tmp_path: Path, isolated_env: None) -> None:
    """A prefix the API will not cache (too short, say) is sent as a system instruction."""
    settings = _real_settings(
        tmp_path,
        correction_shared_prefix=True,
        correction_prefix_cache="explicit",
        correction_model="gemini-3.8-flash",
    )
    genai = MagicMock()
    genai.caches.create.side_effect = RuntimeError("400 cached content is too small")
    genai.models.generate_content.side_effect = lambda **_: _genai_response()
    client = GeminiClient(settings, _genai_client=genai, default_cache_mode="bypass")
    scheme = _scheme("0580_s23_qp_22")
    corrector = AICorrector(client, mark_scheme=scheme)
    for leaf in _leaves(scheme)[:2]:
        corrector.mark_question(leaf, "x")
    # Tried once per paper, not once per call.
    assert genai.caches.create.call_count == 1
    configs = [c.kwargs["config"] for c in genai.models.generate_content.call_args_list]
    expected = build_shared_prefix(scheme, reader_describes_drawings=False)
    assert all(c.cached_content is None and c.system_instruction == expected for c in configs)


@pytest.mark.parametrize("model", ["gemini-4.1-flash", "gemini-2.5-flash"])
def test_explicit_cache_only_on_gemini_3x(tmp_path: Path, isolated_env: None, model: str) -> None:
    settings = _real_settings(
        tmp_path,
        correction_shared_prefix=True,
        correction_prefix_cache="explicit",
        correction_model=model,
        pricing={model: [0.001, 0.002]},
    )
    genai = MagicMock()
    genai.models.generate_content.side_effect = lambda **_: _genai_response()
    client = GeminiClient(settings, _genai_client=genai, default_cache_mode="bypass")
    scheme = _scheme("0625_s20_qp_31")
    AICorrector(client, mark_scheme=scheme).mark_question(_leaves(scheme)[0], "x")
    genai.caches.create.assert_not_called()
    config = genai.models.generate_content.call_args.kwargs["config"]
    assert config.system_instruction == build_shared_prefix(scheme, reader_describes_drawings=False)


def test_implicit_mode_sends_prefix_as_system_instruction(
    tmp_path: Path, isolated_env: None
) -> None:
    settings = _real_settings(
        tmp_path, correction_shared_prefix=True, correction_model="gemini-3.8-flash"
    )
    assert settings.gemini.correction_prefix_cache == "implicit"
    genai = MagicMock()
    genai.models.generate_content.side_effect = lambda **_: _genai_response()
    client = GeminiClient(settings, _genai_client=genai, default_cache_mode="bypass")
    scheme = _scheme("0625_s20_qp_31")
    AICorrector(client, mark_scheme=scheme).mark_question(_leaves(scheme)[0], "x")
    genai.caches.create.assert_not_called()
    config = genai.models.generate_content.call_args.kwargs["config"]
    assert config.cached_content is None
    assert config.system_instruction == build_shared_prefix(scheme, reader_describes_drawings=False)


def test_claude_prefix_goes_through_cache_prefix(tmp_path: Path, isolated_env: None) -> None:
    settings = _real_settings(
        tmp_path, correction_shared_prefix=True, correction_model="claude-haiku-5-5"
    )
    client = GeminiClient(settings, _genai_client=MagicMock(), default_cache_mode="bypass")
    adapter = MagicMock()
    adapter.complete.return_value = AnthropicReply(
        text=json.dumps(
            {"awarded_marks": 1, "confidence": 0.95, "matched_point_ids": [], "feedback": "f"}
        ),
        usage=Usage(input_tokens=6000, cached_tokens=5000, output_tokens=30, thinking_tokens=0),
        stop_reason="end_turn",
    )
    client._anthropic_adapter = adapter
    scheme = _scheme("0625_s20_qp_31")
    leaf = _leaves(scheme)[0]
    AICorrector(client, mark_scheme=scheme).mark_question(leaf, "x")
    kwargs = adapter.complete.call_args.kwargs
    prefix = build_shared_prefix(scheme, reader_describes_drawings=False)
    assert kwargs["system_prompt"] == marker_system_prompt()
    assert kwargs["cache_prefix"] is not None
    assert prefix.startswith(kwargs["system_prompt"])
    assert prefix.endswith(kwargs["cache_prefix"])
    assert kwargs["user_prompt"] == build_marker_user_prompt(leaf, "x")


def test_shared_prefix_must_match_system_prompt(tmp_path: Path, isolated_env: None) -> None:
    client = GeminiClient(_real_settings(tmp_path), _genai_client=MagicMock())
    prefix = SharedPrefix(instructions="a", paper="b", text="a\n\nb", cache="implicit", version="v")
    with pytest.raises(ValueError, match="shared_prefix"):
        client.generate_structured(
            system_prompt="something else",
            user_prompt="u",
            response_schema=AIMarkResponse,
            prompt_version="v",
            shared_prefix=prefix,
        )
