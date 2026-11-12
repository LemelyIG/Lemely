"""The reader's rule for a drawing: countable facts after ``Drawing:``, and no verdict.

The marker is never shown the page. For a drawing it has only what the reader wrote, and
it takes that on trust, so a reader that writes "correctly drawn" awards the marks itself.
So does one that writes "evenly spaced, none crossing" without having looked: the rule
asks for what can be seen and counted, a fault as plainly as anything else, and no word
that sums the drawing up.

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
# Words that sum up how regular a drawing is. The same holds for them.
_REGULARITY_WORDS = (
    "evenly",
    "even spac",
    "equally",
    "regular",
    "symmetr",
    "smooth",
    "to scale",
    "uniform",
    "consistent",
    "parallel",
)
_FORBIDDEN_LISTS = re.compile(
    r"a word that judges it \(([^)]*)\) or a word that sums up how regular it is \(([^)]*)\)"
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


def _outside_the_forbidden_lists() -> str:
    """The rule, lower-cased, without the clause that names the words it forbids."""
    rule = _squash(_rule())
    forbidden = _FORBIDDEN_LISTS.search(rule)
    assert forbidden is not None
    return rule.replace(forbidden.group(0), "").lower()


def test_reader_prompt_version_is_3() -> None:
    assert VERSION == "3"


def test_the_whole_system_prompt_is_pinned_to_its_version() -> None:
    """The text at VERSION "3". No part of it is exempt.

    ``tests/test_label_binder.py`` pins the prompt against the measured one with the
    drawing rule cut out, so an edit inside that rule would pass there. When this goes
    red: bump ``VERSION`` in ``lemely/io/prompts/label_binding.py`` and re-pin both values.
    The drawing rule is unmeasured, so there is no measurement to redo yet.
    """
    assert (VERSION, hashlib.sha256(LABEL_BINDING_SYSTEM_PROMPT.encode()).hexdigest()) == (
        "3",
        "7d8287d789083a78b38e8b7bdfd5cb712548b349689f051b6c4587021cf400cc",
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


def test_the_rule_asks_for_what_any_drawing_is_made_of() -> None:
    """The facts are of lines, arrowheads, meetings, points and labels, not of one question."""
    rule = _squash(_rule())
    for fact in (
        "What was drawn, by kind, and how many of each",
        "For each line or curve: where it starts, where it ends and what it passes through",
        "placed against the printed diagram, grid or scale where there is one",
        "whether it is straight or curved",
        "For each arrowhead: the line it is on and the way it points.",
        "Where a line has no arrowhead, say so of that line.",
        "Where things meet: which lines touch, cross or join, and where",
        "which stop short of what they run towards, leaving a gap",
        "For each plotted point: where it is actually plotted, read against the printed scales.",
        "For a line or curve drawn through points: each point it misses, and on which side",
        "Every label, symbol, value and unit the student wrote on the drawing, copied exactly",
    ):
        assert fact in rule, fact


def test_the_rule_holds_for_every_kind_of_drawing() -> None:
    rule = _squash(_rule())
    assert (
        "This holds for every kind of drawing: a graph, a diagram of rays, a circuit, lines "
        "that show a direction, a labelled sketch."
    ) in rule
    # The reader is shown no mark scheme, so it cannot pick the details that earn marks.
    assert (
        "You are not told what the question asks for, so you cannot know which details matter"
    ) in rule


def test_the_rule_asks_only_for_what_can_be_seen_and_counted() -> None:
    rule = _squash(_rule())
    assert "State only what you can see and count." in rule
    assert "Do not claim a property the page does not show" in rule
    assert 'where you cannot tell, say that ("cannot tell whether the two curves touch")' in rule


def test_a_fault_is_stated_as_plainly_as_anything_else() -> None:
    """A description that tidies the drawing up awards marks the drawing did not earn."""
    rule = _squash(_rule())
    assert "Leave nothing out because it looks like a slip." in rule
    for fault in (
        "Lines that cross or touch",
        "an arrowhead that is missing or points the other way from the others",
        "a point that sits away from the line or from the run of the other points",
        "a line that misses points or stops short",
    ):
        assert fault in rule, fault
    assert "state each as plainly as everything else" in rule


def test_none_is_written_only_of_things_counted() -> None:
    """A claim about all of several things is the easiest to make without looking."""
    rule = _squash(_rule())
    assert "Say of each thing what you see of it." in rule
    assert (
        "Write that none of several things has a property only after looking at every one of "
        'them, and give the number you looked at ("none of the 3 lines has an arrowhead").'
    ) in rule


def test_the_rule_forbids_a_verdict_and_a_summing_up() -> None:
    rule = _squash(_rule())
    assert "Report what is there, never whether it is right, and do not sum the drawing up." in rule
    forbidden = _FORBIDDEN_LISTS.search(rule)
    assert forbidden is not None
    assert forbidden.group(1) == '"correct", "accurate", "appropriate", "neat", "well drawn"'
    assert forbidden.group(2) == '"evenly spaced", "symmetrical", "smooth", "to scale"'
    assert "give the places and the counts" in rule


def test_the_old_rules_are_gone() -> None:
    system = _squash(LABEL_BINDING_SYSTEM_PROMPT)
    assert "describe briefly" not in system
    # The phrasing of VERSION "2" that a reader could copy without looking.
    assert "none touching or crossing" not in system
    assert "evenly spaced," not in system
    assert "ruled" not in system
    # The fact that was one question's mark point with the noun taken out.
    assert "closer together" not in system
    assert "further apart" not in system


def test_the_examples_open_with_drawing_and_carry_no_verdict_or_summing_up() -> None:
    examples = _examples()
    assert len(examples) == 2
    for example in examples:
        lowered = example.lower()
        assert [word for word in _VERDICT_WORDS if word in lowered] == [], example
        assert [word for word in _REGULARITY_WORDS if word in lowered] == [], example
        # A countable fact in each: at least one number.
        assert re.search(r"\d", example), example
        # Nothing is said of all of several things at once.
        assert not re.search(r"\b(none|no|all|every|each of)\b", lowered), example


def test_each_example_states_a_fault_and_one_admits_doubt() -> None:
    graph, circuit = _examples()
    assert "the cross at (3, 8) is below the line" in graph
    assert "stops short of the circle, leaving a gap" in circuit
    assert "cannot tell which end of the cell has the longer stroke" in circuit


def test_the_examples_are_of_other_kinds_of_drawing_than_the_measured_papers() -> None:
    """A plotted graph and a circuit. The measured paper's drawing is lines with arrows."""
    graph, circuit = _examples()
    assert "crosses plotted at" in graph
    assert "loop of wire" in circuit
    for example in (graph, circuit):
        assert "arrow" not in example.lower()


def test_judging_words_appear_in_the_rule_only_where_they_are_forbidden() -> None:
    outside = _outside_the_forbidden_lists()
    assert [word for word in _VERDICT_WORDS if word in outside] == []
    assert [word for word in _REGULARITY_WORDS if word in outside] == []


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
        "closer",
        "further apart",
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
