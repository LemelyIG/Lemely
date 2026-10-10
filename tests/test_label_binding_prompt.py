"""The reader's rule for a drawing: countable facts after ``Drawing:``, and no verdict.

The marker is never shown the page. For a drawing it has only what the reader wrote, and
it takes that on trust, so a reader that writes "correctly drawn" awards the marks itself.
These tests pin what the reader is asked for. They cannot show what a model then writes:
that needs a live read.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from lemely.core.loose_schemas import MarkScheme
from lemely.io.prompts.label_binding import (
    LABEL_BINDING_SYSTEM_PROMPT,
    VERSION,
    build_label_binding_user_prompt,
)

_ROOT = Path(__file__).resolve().parents[1]
_SCHEMES = _ROOT / "corpus" / "mark-schemes"
_FIXTURES = _ROOT / "tests" / "fixtures" / "binding" / "0625_w24_41"

_RULE_START = "  - For a drawing, or for marks added to a printed diagram or graph,"
_RULE_END = "  - For a ringed or ticked option"
# Words that say a drawing is right. The reader may name them only to forbid them.
_VERDICT_WORDS = (
    "correct",
    "accurate",
    "appropriate",
    "neat",
    "well drawn",
    "properly",
    "valid",
    "good",
    "right shape",
)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _rule() -> str:
    start = LABEL_BINDING_SYSTEM_PROMPT.index(_RULE_START)
    return LABEL_BINDING_SYSTEM_PROMPT[start : LABEL_BINDING_SYSTEM_PROMPT.index(_RULE_END, start)]


def _examples() -> list[str]:
    """The reply examples the rule shows: every quoted string that opens with ``Drawing:``."""
    return re.findall(r'"(Drawing: [^"]+)"', _squash(_rule()))


def _scheme(name: str = "0625_w24_ms_41") -> MarkScheme:
    return MarkScheme.model_validate(json.loads((_SCHEMES / f"{name}.json").read_text()))


def test_reader_prompt_version_is_2() -> None:
    assert VERSION == "2"


def test_the_whole_system_prompt_is_pinned_to_its_version() -> None:
    """The text at VERSION "2". No part of it is exempt.

    ``tests/test_label_binder.py`` pins the prompt against the measured one with the
    drawing rule cut out, so an edit inside that rule would pass there. When this goes
    red: bump ``VERSION`` in ``lemely/io/prompts/label_binding.py`` and re-pin both values.
    The drawing rule is unmeasured, so there is no measurement to redo yet.
    """
    assert (VERSION, hashlib.sha256(LABEL_BINDING_SYSTEM_PROMPT.encode()).hexdigest()) == (
        "2",
        "b7830e97c38da46eb998abad9eb9141d127970d59cd2c95a6db2ad6a2bcaa431",
    )


def test_a_drawing_is_reported_after_the_word_drawing() -> None:
    rule = _squash(_rule())
    assert '`answer` starts with "Drawing:"' in rule
    # The rule is one of the `answer` rules: after the calculation rule, before the option rule.
    system = LABEL_BINDING_SYSTEM_PROMPT
    assert system.count(_RULE_START) == 1
    assert (
        system.index("  - For a calculation, `answer` is")
        < system.index(_RULE_START)
        < system.index(_RULE_END)
    )
    assert system.index("## answer items") < system.index(_RULE_START)


def test_the_rule_asks_for_each_fact_a_marker_can_count_and_check() -> None:
    rule = _squash(_rule())
    for fact in (
        "what was drawn and how many of each thing",
        "where each line starts and where it ends",
        "whether any lines touch or cross",
        "the direction of every arrow",
        "where lines are closer together and where they are further apart",
        "every label, value and unit written on the drawing, copied exactly",
        "the points plotted",
        "the line drawn through them",
    ):
        assert fact in rule, fact


def test_the_rule_asks_only_for_what_is_visible() -> None:
    rule = _squash(_rule())
    assert "only what is visible on the page" in rule
    assert "do not claim a property the page does not show" in rule
    # Absence and doubt are stated, not left out: a silent description reads as "fine".
    assert "where something is absent or you cannot tell, say that" in rule


def test_the_rule_forbids_a_verdict() -> None:
    rule = _squash(_rule())
    assert "Report what is there, never whether it is right." in rule
    assert "Do not use a word that judges the drawing" in rule


def test_the_old_one_line_rule_is_gone() -> None:
    assert "describe briefly" not in LABEL_BINDING_SYSTEM_PROMPT


def test_the_examples_open_with_drawing_and_carry_no_verdict() -> None:
    examples = _examples()
    assert len(examples) == 2
    for example in examples:
        lowered = example.lower()
        assert [word for word in _VERDICT_WORDS if word in lowered] == [], example
        # A countable fact in each: at least one number.
        assert re.search(r"\d", example), example


def test_verdict_words_appear_in_the_rule_only_where_they_are_forbidden() -> None:
    rule = _squash(_rule())
    forbidden = re.search(r"Do not use a word that judges the drawing \(([^)]*)\)", rule)
    assert forbidden is not None
    outside = rule.replace(forbidden.group(0), "").lower()
    assert [word for word in _VERDICT_WORDS if word in outside] == []


def test_the_rule_is_not_about_the_recorded_script_or_its_mark_scheme() -> None:
    """The examples are invented: nothing of the acceptance paper's two drawing questions."""
    rule = _squash(_rule()).lower()
    for word in (
        "field",
        "magnet",
        "pole",
        "nucleus",
        "proton",
        "neutron",
        "electron",
        "orbit",
        "n to s",
    ):
        assert word not in rule, word
    scheme = _scheme()
    points = [p.point for q in scheme.all_questions_flat() for p in q.answer_points]
    assert len(points) > 40
    assert [p for p in points if p in LABEL_BINDING_SYSTEM_PROMPT or _squash(p) in rule] == []
    reference = json.loads((_FIXTURES / "aligned.json").read_text())
    written = [
        text
        for answer in reference["answers"]
        for text in (answer["answer"], answer.get("working_out"))
        if text and len(text) > 6
    ]
    assert len(written) > 40
    system = _squash(LABEL_BINDING_SYSTEM_PROMPT)
    assert [text for text in written if _squash(text) in system] == []


def test_the_reader_is_still_never_shown_a_mark_scheme_point() -> None:
    """Over every scheme in the corpus: the user prompt carries labels and marks only."""
    checked = 0
    for path in sorted(_SCHEMES.glob("*.json")):
        scheme = MarkScheme.model_validate(json.loads(path.read_text()))
        prompt = build_label_binding_user_prompt(scheme, page_count=4)
        lines = [line for line in prompt.splitlines() if line.startswith("- ")]
        for line in lines:
            assert re.fullmatch(r"- [1-9][0-9]*(\([a-z]+\))* \[[0-9]+ marks?\]", line), (
                path.name,
                line,
            )
        # Outside the label list the user prompt is the same for every paper but for its
        # page count and its name, so no scheme text can have reached it.
        meta = scheme.metadata
        year = meta.session_year if meta.session_year is not None else "Specimen"
        name = (
            f"Paper: {meta.subject_code}/{meta.paper_number}{meta.paper_variant} "
            f"{meta.session_month.value} {year}."
        )
        rest = "\n".join(line for line in prompt.splitlines() if not line.startswith("- "))
        assert rest.count(name) == 1
        frame = rest.replace(name, "Paper: X.")
        assert frame == _user_frame(), path.name
        checked += 1
    assert checked >= 289


def _user_frame() -> str:
    scheme = _scheme()
    prompt = build_label_binding_user_prompt(scheme, page_count=4)
    rest = "\n".join(line for line in prompt.splitlines() if not line.startswith("- "))
    return rest.replace("Paper: 0625/41 Oct/Nov 2024.", "Paper: X.")


def test_the_user_prompt_says_nothing_new() -> None:
    """The drawing rule lives in the system prompt alone."""
    user = build_label_binding_user_prompt(_scheme(), page_count=19)
    assert "Drawing" not in user
    assert "drawing" not in user
