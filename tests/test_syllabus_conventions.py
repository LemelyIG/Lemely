"""Sub-project C lever H2c: printed 0625 Paper 4 marking conventions in the marking prompt."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import AIMarkResponse, AIMarkResponseReasoned, PointVerdictReasoned
from lemely.io.correction_ai import AICorrector
from lemely.io.gemini import GeminiClient, SharedPrefix
from lemely.io.prompts.correction_ai import (
    PHYSICS_0625_CONVENTIONS,
    SCIENCE_DEFAULT_RULES,
    VERSION,
    build_marker_user_prompt,
    build_shared_prefix,
    default_marking_rules,
    printed_principles,
    render_paper_mark_scheme,
    shared_prefix_instructions,
    syllabus_conventions,
)
from tests.gemini_fakes import fake_genai_client, make_settings


def _scheme(
    *, code: str = "0625", paper: int = 4, principles: list[str] | None = None
) -> MarkScheme:
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": code,
                "paper_number": paper,
                "paper_variant": 1,
                "session_month": "Oct/Nov",
                "session_year": 2024,
                "paper_type": "theory_extended",
                "maximum_mark": 4,
                "scheme_format": "point_based",
                "generic_marking_principles": principles or [],
            },
            "questions": [
                {
                    "id": "1a",
                    "marks": 2,
                    "type": "calculation",
                    "answer_points": [
                        {"id": "A1", "point": "6 N", "marks": 2, "math_mark_type": "A"},
                        {
                            "id": "C1",
                            "point": "F = ma",
                            "marks": 1,
                            "math_mark_type": "C",
                            "is_alternative": True,
                        },
                    ],
                },
                {"id": "1b", "marks": 2, "type": "calculation"},
            ],
        }
    )


def _client(**gemini: object) -> GeminiClient:
    settings = make_settings(tempfile.mkdtemp())
    g = settings.gemini.model_copy(update={"escalation_model": None, **gemini})
    return GeminiClient(
        settings.model_copy(update={"gemini": g}), _genai_client=fake_genai_client(), ledger=None
    )


def _reply() -> AIMarkResponse:
    return AIMarkResponse(awarded_marks=1, confidence=0.95, matched_point_ids=[], feedback="f")


def _mark(client: Any, scheme: MarkScheme) -> MagicMock:
    """Mark leaf 1a the way ``correct_paper`` does: with the paper's rules passed in."""
    ai = AICorrector(client, mark_scheme=scheme)
    meta = scheme.metadata
    with patch.object(client, "generate_structured", return_value=_reply()) as call:
        ai.mark_question(
            scheme.questions[0],
            "6 N",
            principles=printed_principles(meta),
            default_rules=default_marking_rules(meta),
        )
    return call


def _sent(call: MagicMock) -> str:
    kwargs = call.call_args.kwargs
    return f"{kwargs['system_prompt']}\n{kwargs['user_prompt']}"


def test_conventions_only_for_0625_paper_4() -> None:
    assert syllabus_conventions(_scheme().metadata) == PHYSICS_0625_CONVENTIONS
    assert syllabus_conventions(_scheme(paper=2).metadata) is None
    assert syllabus_conventions(_scheme(code="0610").metadata) is None


def test_constant_names_each_printed_rule() -> None:
    for needle in ("compensatory", "any form", "crossed out", "Brackets", "N/m²"):
        assert needle in PHYSICS_0625_CONVENTIONS
    assert "Q = mc" not in PHYSICS_0625_CONVENTIONS
    assert "missing" not in PHYSICS_0625_CONVENTIONS


def test_user_prompt_unchanged_without_conventions() -> None:
    q = _scheme().questions[0]
    base = build_marker_user_prompt(q, "a", default_rules=SCIENCE_DEFAULT_RULES)
    assert base == build_marker_user_prompt(
        q, "a", default_rules=SCIENCE_DEFAULT_RULES, conventions=None
    )
    with_conv = build_marker_user_prompt(
        q,
        "a",
        prior_results={"1a": 1},
        default_rules=SCIENCE_DEFAULT_RULES,
        conventions=PHYSICS_0625_CONVENTIONS,
    )
    assert with_conv.count(PHYSICS_0625_CONVENTIONS) == 1
    assert with_conv.index(SCIENCE_DEFAULT_RULES) < with_conv.index(PHYSICS_0625_CONVENTIONS)
    assert with_conv.index(PHYSICS_0625_CONVENTIONS) < with_conv.index("PRIOR PART RESULTS")


def test_prefix_unchanged_without_conventions() -> None:
    s = _scheme()
    assert render_paper_mark_scheme(s, conventions=None) == render_paper_mark_scheme(s)
    assert build_shared_prefix(
        s, reader_describes_drawings=False, conventions=None
    ) == build_shared_prefix(s, reader_describes_drawings=False)


def test_prefix_carries_conventions() -> None:
    s = _scheme()
    paper = render_paper_mark_scheme(s, conventions=PHYSICS_0625_CONVENTIONS)
    text = build_shared_prefix(
        s, reader_describes_drawings=False, conventions=PHYSICS_0625_CONVENTIONS
    )
    assert paper.count(PHYSICS_0625_CONVENTIONS) == 1
    assert text.count(PHYSICS_0625_CONVENTIONS) == 1
    SharedPrefix(
        instructions=shared_prefix_instructions(reader_describes_drawings=False),
        paper=paper,
        text=text,
        cache=True,
        version=VERSION,
    )


def test_corrector_off_by_default() -> None:
    assert PHYSICS_0625_CONVENTIONS not in _sent(_mark(_client(), _scheme()))
    assert PHYSICS_0625_CONVENTIONS not in _sent(
        _mark(
            _client(correction_syllabus_conventions=False, correction_shared_prefix=True), _scheme()
        )
    )
    # A stand-in settings object whose attributes are all truthy must not switch it on.
    assert AICorrector(MagicMock(), mark_scheme=_scheme())._conventions() is None


def test_corrector_on_without_prefix_puts_them_in_the_user_prompt() -> None:
    call = _mark(_client(correction_syllabus_conventions=True), _scheme())
    assert call.call_args.kwargs["user_prompt"].count(PHYSICS_0625_CONVENTIONS) == 1
    assert _sent(call).count(PHYSICS_0625_CONVENTIONS) == 1


def test_corrector_on_with_prefix_puts_them_in_the_prefix_only() -> None:
    call = _mark(
        _client(correction_syllabus_conventions=True, correction_shared_prefix=True), _scheme()
    )
    assert PHYSICS_0625_CONVENTIONS not in call.call_args.kwargs["user_prompt"]
    assert call.call_args.kwargs["system_prompt"].count(PHYSICS_0625_CONVENTIONS) == 1
    assert _sent(call).count(PHYSICS_0625_CONVENTIONS) == 1


def test_corrector_on_for_another_paper_sends_nothing() -> None:
    call = _mark(_client(correction_syllabus_conventions=True), _scheme(paper=2))
    assert PHYSICS_0625_CONVENTIONS not in _sent(call)


def test_printed_principles_still_sent_with_conventions() -> None:
    principle = "GMP 1 Marks are awarded for what the candidate has written."
    call = _mark(_client(correction_syllabus_conventions=True), _scheme(principles=[principle]))
    user = call.call_args.kwargs["user_prompt"]
    assert principle in user
    assert SCIENCE_DEFAULT_RULES not in user
    assert user.index(principle) < user.index(PHYSICS_0625_CONVENTIONS)
    prefixed = _mark(
        _client(correction_syllabus_conventions=True, correction_shared_prefix=True),
        _scheme(principles=[principle]),
    )
    system = prefixed.call_args.kwargs["system_prompt"]
    assert system.index(principle) < system.index(PHYSICS_0625_CONVENTIONS)


def test_a2_c1_entry_with_a_awarded_and_c_withheld_still_sums_to_two() -> None:
    """With H2b on, a fully correct answer earns the A2 even though its C1 is withheld."""
    reply = AIMarkResponseReasoned(
        awarded_marks=2,
        confidence=0.95,
        matched_point_ids=[],
        feedback="f",
        point_verdicts=[
            PointVerdictReasoned(point_id="A1", verdict="awarded"),
            PointVerdictReasoned(point_id="C1", verdict="withheld"),
        ],
    )
    client = _client(correction_syllabus_conventions=True, correction_reason_first=True)
    scheme = _scheme()
    ai = AICorrector(client, mark_scheme=scheme)
    with patch.object(client, "generate_structured", return_value=reply):
        out = ai.mark_question(scheme.questions[0], "6 N")
    assert out.awarded_marks == 2
    assert out.matched_point_ids == ["A1"]
    assert {p.id for p in scheme.questions[0].answer_points} == {"A1", "C1"}


# The lever-off request for one leaf of the stored 0625/41 Oct/Nov 2024 scheme, as it was at
# b80ff30b (before H2c), hashed with sha256. Pins the default correction path of 0625 Paper 4
# (H2a, H2b and H2c off), with the shared prefix off and on.
_PINNED_OFF = (
    "f3c3b9df5d0c756b26335a02a86cbd66a13fb2a71b50cf3733690a3b0e2d2977",
    "f4521c73c23722fcf12a52778936e79066ee323b57e019565f15c864f380814a",
)
_PINNED_PREFIX_ON = (
    "bd59bd559dab00d7098dc0b8d9868b064e3f9b22ed3a701e272252ed31d41ff7",
    "cb5b42ca93c94fa63428945b61992414bc227743576a2b326f0b86c994289adb",
)


def _request(*, prefix: bool) -> dict[str, Any]:
    scheme = MarkScheme.model_validate(
        json.loads(Path("corpus/mark-schemes/0625_w24_ms_41.json").read_text())
    )
    leaf = scheme.questions[0]
    while leaf.parts:
        leaf = leaf.parts[0]
    client = _client(correction_shared_prefix=prefix)
    meta = scheme.metadata
    with patch.object(client, "generate_structured", return_value=_reply()) as call:
        AICorrector(client, mark_scheme=scheme).mark_question(
            leaf,
            "6 N",
            principles=printed_principles(meta),
            default_rules=default_marking_rules(meta),
        )
    return dict(call.call_args.kwargs)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_default_request_for_0625_paper_4_is_pinned() -> None:
    for prefix, pinned in ((False, _PINNED_OFF), (True, _PINNED_PREFIX_ON)):
        kw = _request(prefix=prefix)
        assert (_sha(kw["system_prompt"]), _sha(kw["user_prompt"])) == pinned
        assert kw["response_schema"] is AIMarkResponse
        assert (kw["prompt_version"], kw["extra_cache_key"], kw["task_tag"], kw["attempt"]) == (
            VERSION,
            "q=1a_i",
            "correction",
            "first",
        )
        assert ("shared_prefix" in kw) is prefix
