"""Shared per-paper prompt prefix for caching (cost-ladder lever A3)."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from lemely.core.loose_schemas import MarkScheme, Question
from lemely.core.schemas import AIMarkResponse
from lemely.io.correction_ai import AICorrector
from lemely.io.gemini import (
    PREFIX_CACHE_TASK_TAG,
    PREFIX_CACHE_TTL_SECONDS,
    PRICE_DATE_2027,
    GeminiClient,
    SharedPrefix,
    UnpricedModelError,
    prefix_cache_storage_usd,
    price_call,
    process_call_records,
    record_calls,
    reset_process_counters,
)
from lemely.io.prompts.correction_ai import (
    SCIENCE_DEFAULT_RULES,
    VERSION,
    build_marker_user_prompt,
    build_shared_prefix,
    default_marking_rules,
    marker_system_prompt,
    printed_principles,
    shared_prefix_instructions,
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


@pytest.fixture
def recording() -> Iterator[None]:
    """Keep call records for the test (they are kept only while a recorder is open)."""
    with record_calls():
        yield


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
    assert prefix.startswith(shared_prefix_instructions(reader_describes_drawings=False))
    positions = [prefix.index(f'"id": "{q.id}"') for q in scheme.questions]
    assert positions == sorted(positions)
    reader = build_shared_prefix(scheme, reader_describes_drawings=True)
    assert reader.startswith(shared_prefix_instructions(reader_describes_drawings=True))


@pytest.mark.parametrize("reader", [False, True])
def test_prefix_instructions_differ_only_in_where_principles_are(reader: bool) -> None:
    system = marker_system_prompt(reader_describes_drawings=reader)
    instructions = shared_prefix_instructions(reader_describes_drawings=reader)
    assert "supplied in the user prompt" in system
    assert "supplied in the user prompt" not in instructions
    assert instructions == system.replace(
        "which are supplied in the user prompt when the paper prints them",
        "which are supplied after this paper's full mark scheme, below, when the paper prints them",
    )


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


def _with_principles(scheme: MarkScheme, principles: list[str]) -> MarkScheme:
    meta = scheme.metadata.model_copy(
        update={"generic_marking_principles": principles, "subject_specific_principles": []}
    )
    return scheme.model_copy(update={"metadata": meta})


def _mark_one(
    scheme: MarkScheme, *, principles: list[str] | None, default_rules: str | None
) -> dict[str, Any]:
    leaf = _leaves(scheme)[1]
    fake = _FakeClient(_settings(correction_shared_prefix=True), [_mark(1, 0.95)])
    AICorrector(cast("GeminiClient", fake), mark_scheme=scheme).mark_question(
        leaf,
        "STUDENT-ANSWER-SENTINEL resistance rises",
        "WORKING-SENTINEL 3 x 4 = 12",
        prior_results={"1a": 1},
        principles=principles,
        default_rules=default_rules,
    )
    (call,) = fake.calls
    for leaf_text in ("STUDENT-ANSWER-SENTINEL", "WORKING-SENTINEL", "PRIOR PART RESULTS"):
        assert leaf_text in call["user_prompt"]
        assert leaf_text not in call["system_prompt"]
    return call


def test_paper_principles_move_from_user_prompt_to_prefix() -> None:
    scheme = _with_principles(
        _scheme("0625_s20_qp_31"), ["PRINCIPLE-SENTINEL-1 A marks depend on M marks"]
    )
    principles = printed_principles(scheme.metadata)
    call = _mark_one(scheme, principles=principles, default_rules=None)
    assert "PRINCIPLE-SENTINEL-1" not in call["user_prompt"]
    assert "GENERIC MARKING PRINCIPLES" not in call["user_prompt"]
    assert "PRINCIPLE-SENTINEL-1" in call["system_prompt"]
    # Restated for its new position: the guidance it overrides is earlier, not elsewhere.
    assert (
        "TAKE PRECEDENCE over the general guidance at the start of these instructions"
        in (call["system_prompt"])
    )
    # What is left is the leaf-specific prompt with no paper rules in it.
    leaf = _leaves(scheme)[1]
    assert call["user_prompt"] == build_marker_user_prompt(
        leaf,
        "STUDENT-ANSWER-SENTINEL resistance rises",
        "WORKING-SENTINEL 3 x 4 = 12",
        {"1a": 1},
    )


def test_science_default_rules_move_from_user_prompt_to_prefix() -> None:
    scheme = _with_principles(_scheme("0625_s20_qp_31"), [])
    default_rules = default_marking_rules(scheme.metadata)
    assert default_rules == SCIENCE_DEFAULT_RULES
    call = _mark_one(scheme, principles=None, default_rules=default_rules)
    assert "GENERAL MARKING RULES FOR CAMBRIDGE SCIENCE PAPERS" not in call["user_prompt"]
    assert "GENERAL MARKING RULES FOR CAMBRIDGE SCIENCE PAPERS" in call["system_prompt"]
    # Every sentence that named a position now names a true one.
    for stale in (
        "The MARK SCHEME SUBTREE above always wins",
        "an earlier-part value supplied below",
        "guidance in the system prompt",
        "the system prompt's fallback",
    ):
        assert stale not in call["system_prompt"]
    assert "The MARK SCHEME SUBTREE of the question being marked" in call["system_prompt"]


def test_rules_that_differ_from_the_schemes_stay_in_user_prompt() -> None:
    scheme = _with_principles(_scheme("0625_s20_qp_31"), ["PRINCIPLE-SENTINEL-1"])
    call = _mark_one(scheme, principles=["CALLER-SENTINEL"], default_rules=None)
    assert "CALLER-SENTINEL" in call["user_prompt"]


def test_reports_prefix_sizes_and_lists_papers_at_the_caching_floor(
    record_property: Callable[[str, object], None],
) -> None:
    """Compute each cost-201 paper's prefix size (``len(text) // 4`` tokens) and report it.

    The golden schemes are excerpts that another lane is editing, so the sizes and
    which papers reach Gemini's 4,096-token implicit-caching floor are reported,
    not pinned. Every paper's prefix is larger than the instructions alone.
    """
    sizes = {
        code: len(build_shared_prefix(scheme, reader_describes_drawings=False)) // 4
        for code, scheme in _paper_schemes().items()
    }
    reaching = sorted(code for code, tokens in sizes.items() if tokens >= _IMPLICIT_MIN_TOKENS)
    record_property("shared_prefix_tokens", sizes)
    record_property("papers_at_implicit_floor", reaching)
    assert len(sizes) == 5, sizes
    instructions_only = len(shared_prefix_instructions(reader_describes_drawings=False)) // 4
    assert all(tokens > instructions_only for tokens in sizes.values()), sizes
    assert all(sizes[code] >= _IMPLICIT_MIN_TOKENS for code in reaching), sizes


# ---------------------------------------------------------------------------
# Provider caching
# ---------------------------------------------------------------------------


def test_explicit_cache_created_once_per_paper(
    tmp_path: Path, isolated_env: None, recording: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_process_counters()
    monkeypatch.setattr("lemely.io.gemini._today", lambda: date(2026, 10, 19))
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
    # Storage for 600 s of 5,000 tokens: $0.50 per 1M per hour now, $1.00 from 2027.
    tokens_now = price_call(
        "gemini-3.8-flash",
        settings,
        input_tokens=5000,
        cached_tokens=0,
        output_tokens=0,
        on=date(2026, 10, 19),
    )
    tokens_2027 = price_call(
        "gemini-3.8-flash",
        settings,
        input_tokens=5000,
        cached_tokens=0,
        output_tokens=0,
        on=PRICE_DATE_2027,
    )
    for r in cache_records:
        assert r.input_tokens == 5000
        assert r.usd_now == pytest.approx(tokens_now + 5000 / 1e6 * 0.50 / 6)
        assert r.usd_2027 == pytest.approx(tokens_2027 + 5000 / 1e6 * 1.00 / 6)
        assert r.attempt is None and r.question_id is None


def _explicit_client(
    tmp_path: Path, genai: MagicMock, model: str = "gemini-3.8-flash"
) -> GeminiClient:
    settings = _real_settings(
        tmp_path,
        correction_shared_prefix=True,
        correction_prefix_cache="explicit",
        correction_model=model,
    )
    genai.models.generate_content.side_effect = lambda **_: _genai_response()
    return GeminiClient(settings, _genai_client=genai, default_cache_mode="bypass")


def _cache(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, usage_metadata=SimpleNamespace(total_token_count=5000))


def test_transient_creation_failure_is_retried_next_call(
    tmp_path: Path, isolated_env: None
) -> None:
    genai = MagicMock()
    genai.caches.create.side_effect = [RuntimeError("503 unavailable"), _cache("cachedContents/a")]
    client = _explicit_client(tmp_path, genai)
    scheme = _scheme("0625_s20_qp_31")
    corrector = AICorrector(client, mark_scheme=scheme)
    first, second = _leaves(scheme)[:2]
    corrector.mark_question(first, "x")
    corrector.mark_question(second, "x")
    assert genai.caches.create.call_count == 2
    configs = [c.kwargs["config"] for c in genai.models.generate_content.call_args_list]
    assert [c.cached_content for c in configs] == [None, "cachedContents/a"]


def test_expired_caches_are_pruned_and_recreated(tmp_path: Path, isolated_env: None) -> None:
    genai = MagicMock()
    genai.caches.create.side_effect = [_cache("cachedContents/a"), _cache("cachedContents/b")]
    client = _explicit_client(tmp_path, genai)
    scheme = _scheme("0625_s20_qp_31")
    corrector = AICorrector(client, mark_scheme=scheme)
    leaves = _leaves(scheme)
    corrector.mark_question(leaves[0], "x")
    (key,) = client._prefix_caches
    # Another paper's cache that has already run out.
    client._prefix_caches[("gemini-3.8-flash", VERSION, "stale")] = ("cachedContents/old", 0.0)
    with patch(
        "lemely.io.gemini.time.monotonic",
        return_value=time.monotonic() + PREFIX_CACHE_TTL_SECONDS,
    ):
        corrector.mark_question(leaves[1], "x")
    assert genai.caches.create.call_count == 2
    assert list(client._prefix_caches) == [key]
    assert client._prefix_caches[key] is not None
    assert client._prefix_caches[key][0] == "cachedContents/b"


def test_unpriced_storage_makes_no_explicit_cache(tmp_path: Path, isolated_env: None) -> None:
    """No storage price, no cache: its cost could not be recorded."""
    genai = MagicMock()
    client = _explicit_client(tmp_path, genai, model="gemini-3.5-flash")
    scheme = _scheme("0625_s20_qp_31")
    AICorrector(client, mark_scheme=scheme).mark_question(_leaves(scheme)[0], "x")
    genai.caches.create.assert_not_called()
    config = genai.models.generate_content.call_args.kwargs["config"]
    assert config.system_instruction == build_shared_prefix(scheme, reader_describes_drawings=False)


def test_storage_rows() -> None:
    assert prefix_cache_storage_usd(
        "gemini-3.6-flash", 1_000_000, 3600, on=date(2026, 12, 31)
    ) == pytest.approx(0.50)
    assert prefix_cache_storage_usd(
        "gemini-3.8-flash", 1_000_000, 3600, on=PRICE_DATE_2027
    ) == pytest.approx(1.00)
    for on in (date(2026, 10, 19), PRICE_DATE_2027):
        assert prefix_cache_storage_usd(
            "gemini-3.5-flash-lite", 1_000_000, 3600, on=on
        ) == pytest.approx(1.00)
    with pytest.raises(UnpricedModelError):
        prefix_cache_storage_usd("gemini-3.9-pro", 1, 600, on=PRICE_DATE_2027)


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
    assert kwargs["system_prompt"] == shared_prefix_instructions(reader_describes_drawings=False)
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
