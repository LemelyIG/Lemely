"""The label binder's model call: the prompt, the reply schema, the parsing, the conversion.

The reader is asked for one list, in reading order, of the question labels it sees and
the blocks of student writing. It is never asked for a question id. ``bind_stream``
(``lemely.core.label_sequence``) decides the ids; these tests cover what sits either
side of it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lemely.core.binding import SeenLabel, SeenWriting, UnboundWriting
from lemely.core.label_sequence import (
    CONTENT_DOUBTS,
    DOUBT_ARROW,
    DOUBT_NEXT_NUMBER_NOT_SEEN,
    DOUBT_NUMBER_NOT_SEEN,
    DOUBT_PREVIOUS_PAGE,
    DOUBTS,
    INFERENCE_DOUBTS,
    BoundLeaf,
    BoundStream,
    bind_stream,
    parse_label,
)
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import SourceBox
from lemely.io.binding import (
    BoundRead,
    LabelBinder,
    StreamRead,
    parse_stream_items,
    to_bound_read,
)
from lemely.io.gemini import GeminiClient, _strip_schema
from lemely.io.prompts import (
    LABEL_BINDING_PROMPT_VERSION,
    LABEL_BINDING_SYSTEM_PROMPT,
    build_label_binding_user_prompt,
)
from lemely.io.rasterise import RasterisedPage
from lemely.runtime.config import PathsSettings, load_settings
from lemely.runtime.errors import CostCeilingError, ExternalServiceError, ParseError
from tests.gemini_fakes import fake_genai_client

_ROOT = Path(__file__).resolve().parent.parent
_SCHEMES = _ROOT / "corpus" / "mark-schemes"
_FIXTURES = _ROOT / "tests" / "fixtures" / "binding" / "0625_w24_41"
_RUNS = (1, 2, 3, 4, 5)
# The prompt the measurement ran (task-2b, variant A, version "il1"), as sha256: the
# system prompt, and the user prompt for 0625_w24_ms_41 with 19 pages.
_MEASURED_SYSTEM_SHA = "c1eb1c910710e7bb96cd6f9b3eeb312c402e7be6265b27eb489ac945b4154408"
_MEASURED_USER_SHA = "778e5b17b1deaccf5925858f48db23c1e311b71d1b01f8a3c209970b570a7dc5"
# What this prompt adds to the measured one. Nothing else differs.
_ADDED_TO_SYSTEM = (
    "Always list a question label BEFORE the student's writing that sits under it, never after\n"
    "it: the label first, then the writing in that part's space, then the next label. The same\n"
    "holds for writing the student tied to a part with an arrow or a note: it goes after that\n"
    "part's label, never before it.\n\n"
)
_ADDED_TO_USER = "A label is always listed before the writing that sits under it, never after it. "
# The one rule of the measured prompt that this prompt replaces: what to write for a drawing.
_MEASURED_DRAWING_RULE = (
    "  - For a drawing, or for marks added to a printed diagram or graph, describe briefly what\n"
    '    the student drew: "curved line through (2,4) and (5,10)".\n'
)
_DRAWING_RULE_START = "  - For a drawing, or for marks added to a printed diagram or graph,"
_DRAWING_RULE_END = "  - For a ringed or ticked option"


def _scheme(name: str = "0625_w24_ms_41") -> MarkScheme:
    return MarkScheme.model_validate(json.loads((_SCHEMES / f"{name}.json").read_text()))


def _leaves(scheme: MarkScheme) -> list[tuple[str, int]]:
    return [(q.id, q.marks) for q in scheme.all_questions_flat() if not q.parts]


def _pages(count: int) -> list[RasterisedPage]:
    return [
        RasterisedPage(index=i, width=10, height=14, png_bytes=f"page-{i}".encode(), dpi=72.0)
        for i in range(count)
    ]


class _IsolatedEnv:
    def __enter__(self) -> _IsolatedEnv:
        self._snap = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("LEMELY_"):
                del os.environ[k]
        return self

    def __exit__(self, *_: object) -> None:
        os.environ.clear()
        os.environ.update(self._snap)


def _client(tmp: Path, body: dict[str, Any]) -> tuple[GeminiClient, MagicMock]:
    """A real ``GeminiClient`` over a fake SDK client that replies with ``body``."""
    genai = fake_genai_client()
    genai.models.generate_content.return_value = MagicMock(
        text=json.dumps(body),
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(prompt_token_count=5, candidates_token_count=30),
    )
    with _IsolatedEnv():
        settings = load_settings(toml_path=None, cwd=tmp)
    settings = settings.model_copy(
        update={"paths": PathsSettings(cache_dir=tmp / ".cache", output_dir=tmp / "outputs")}
    )
    return GeminiClient(settings, _genai_client=genai), genai


def _read(
    tmp: Path,
    items: list[Any],
    *,
    page_count: int = 4,
    scheme: MarkScheme | None = None,
    model: str | None = None,
    **read_kwargs: Any,
) -> tuple[StreamRead, MagicMock, MagicMock]:
    """Run ``LabelBinder.read`` on a reply; also return the SDK fake and the call spy."""
    client, genai = _client(tmp, {"items": items})
    pages = _pages(page_count)
    with (
        client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
        patch.object(client, "generate_structured", wraps=client.generate_structured) as spy,
    ):
        read = LabelBinder(client).read(
            pages,
            scheme or _scheme(),
            uploads=uploads,
            model=model,
            extra_cache_key="scan-1",
            **read_kwargs,
        )
    return read, genai, spy


def _label(text: str, page: int = 0, **extra: Any) -> dict[str, Any]:
    return {
        "type": "label",
        "page": page,
        "box": [10, 10, 30, 40],
        "text": text,
        "kind": "printed",
        **extra,
    }


def _answer(answer: Any, page: int = 0, **extra: Any) -> dict[str, Any]:
    return {
        "type": "answer",
        "page": page,
        "box": [100, 100, 200, 600],
        "answer": answer,
        "working_out": None,
        "confidence": 0.9,
        "placed_by": "position",
        **extra,
    }


def _writing(answer: str, page: int = 0, **extra: Any) -> SeenWriting:
    return SeenWriting(page=page, answer=answer, **{"confidence": 0.9, **extra})


def _leaf(question_id: str, *writings: SeenWriting, doubts: tuple[str, ...] = ()) -> BoundLeaf:
    return BoundLeaf(
        question_id=question_id,
        label_seen=f"({question_id[-1]})",
        number_inferred=DOUBT_NUMBER_NOT_SEEN in doubts,
        writings=list(writings),
        doubts=list(doubts),
    )


def _bound(*leaves: BoundLeaf, **extra: Any) -> BoundStream:
    fields: dict[str, Any] = {
        "leaves": list(leaves),
        "unbound": [],
        "unaligned_ids": [],
        "unplaced_labels": [],
        "inferred_numbers": [],
        "listing_suspects": [],
    }
    return BoundStream(**{**fields, **extra})


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# --------------------------------------------------------------------------------------
# The reply schema
# --------------------------------------------------------------------------------------
def _property_names(schema: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(schema, dict):
        names |= set(schema.get("properties", {}))
        for value in schema.values():
            names |= _property_names(value)
    elif isinstance(schema, list):
        for value in schema:
            names |= _property_names(value)
    return names


def test_reply_schema_has_no_question_id_property(tmp_path: Path) -> None:
    _, _, spy = _read(tmp_path, [_label("1")])
    for is_3x in (True, False):
        sent = _strip_schema(
            spy.call_args.kwargs["response_schema"].model_json_schema(), is_3x=is_3x
        )
        names = _property_names(sent)
        assert names == {
            "items",
            "type",
            "page",
            "box",
            "text",
            "kind",
            "answer",
            "working_out",
            "confidence",
            "placed_by",
        }
        assert not [n for n in names if "question" in n or n == "id" or n.endswith("_id")]
        assert "question_id" not in json.dumps(sent)


def test_reply_schema_sent_to_the_model_is_typed(tmp_path: Path) -> None:
    """The Python side is lenient; what the model is sent still states the strict shape."""
    _, _, spy = _read(tmp_path, [_label("1")])
    sent = _strip_schema(spy.call_args.kwargs["response_schema"].model_json_schema(), is_3x=True)
    assert sent["required"] == ["items"]
    item = sent["properties"]["items"]["items"]
    assert sent["properties"]["items"]["type"] == "array"
    assert item["required"] == ["type", "page", "box"]
    props = item["properties"]
    assert props["type"] == {"type": "string", "enum": ["label", "answer"]}
    assert props["page"] == {"type": "integer"}
    assert props["box"] == {"type": "array", "items": {"type": "integer"}}
    assert {"type": "string", "enum": ["printed", "handwritten"]} in props["kind"]["anyOf"]
    assert {"type": "string", "enum": ["position", "arrow", "uncertain"]} in props["placed_by"][
        "anyOf"
    ]
    assert {"type": "number", "minimum": 0.0, "maximum": 1.0} in props["confidence"]["anyOf"]


def test_reply_schema_descriptions_survive_dash_oo() -> None:
    """``-OO`` strips docstrings; the descriptions the model is sent must not depend on them."""
    script = (
        "import json, sys\n"
        "assert sys.flags.optimize == 2, sys.flags.optimize\n"
        "from lemely.io.binding.label_binder import _StreamOutput\n"
        "from lemely.io.gemini import _strip_schema\n"
        "sent = _strip_schema(_StreamOutput.model_json_schema(), is_3x=True)\n"
        "print(json.dumps({\n"
        "    'top': sent.get('description'),\n"
        "    'item': sent['properties']['items']['items'].get('description'),\n"
        "}))\n"
    )
    result = subprocess.run(  # noqa: S603 (this module's own fixed script, no shell)
        [sys.executable, "-OO", "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(_ROOT)},
    )
    assert json.loads(result.stdout) == {
        "top": "Question labels and student writing as one list in reading order. No question ids.",
        "item": "One thing on the script. A label item fills text and kind. An answer item "
        "fills answer, working_out, confidence and placed_by.",
    }


# --------------------------------------------------------------------------------------
# The prompts
# --------------------------------------------------------------------------------------
def test_user_prompt_contains_no_mark_scheme_point_text() -> None:
    scheme = _scheme()
    prompt = build_label_binding_user_prompt(scheme, page_count=19)
    points = [p.point for q in scheme.all_questions_flat() for p in q.answer_points]
    assert len(points) > 40
    assert [p for p in points if p in prompt] == []
    assert [p for p in points if p in LABEL_BINDING_SYSTEM_PROMPT] == []


def test_prompts_contain_no_text_from_the_recorded_script() -> None:
    reference = json.loads((_FIXTURES / "aligned.json").read_text())
    answers = [a["answer"] for a in reference["answers"] if a["answer"] and len(a["answer"]) > 6]
    assert len(answers) > 30
    user = build_label_binding_user_prompt(_scheme(), page_count=19)
    for prompt in (LABEL_BINDING_SYSTEM_PROMPT, user):
        assert [a for a in answers if a in prompt or _squash(a) in _squash(prompt)] == []


def test_system_prompt_says_a_label_precedes_its_writing() -> None:
    system = _squash(LABEL_BINDING_SYSTEM_PROMPT)
    assert (
        "Always list a question label BEFORE the student's writing that sits under it, never "
        "after it: the label first, then the writing in that part's space, then the next label."
    ) in system
    # Arrow-tied writing is no exception to it: it follows the label it is tied to.
    assert (
        "The same holds for writing the student tied to a part with an arrow or a note: it "
        "goes after that part's label, never before it."
    ) in system
    # The rule comes before any detail, straight after the paragraph on why order matters.
    assert system.index("Always list a question label BEFORE") < system.index("## label items")
    # The user prompt, the last thing read before the pages, repeats the rule.
    user = build_label_binding_user_prompt(_scheme(), page_count=19)
    assert "A label is always listed before the writing that sits under it, never after it." in user
    # Nothing in either prompt allows the opposite order.
    for prompt in (system, _squash(user)):
        assert "before its label" not in prompt
        assert "before the label" not in prompt


def test_prompts_are_the_measured_prompts_plus_the_listed_additions() -> None:
    """Every difference from the prompt that was measured is named here.

    Two additions, and one rule replaced: the rule for a drawing (version "3", pinned in
    ``tests/test_label_binding_prompt.py``). With the additions taken out and the measured
    drawing rule put back, the prompt is the measured one to the byte.
    """
    assert LABEL_BINDING_SYSTEM_PROMPT.count(_ADDED_TO_SYSTEM) == 1
    assert LABEL_BINDING_SYSTEM_PROMPT.count(_DRAWING_RULE_START) == 1
    without_additions = LABEL_BINDING_SYSTEM_PROMPT.replace(_ADDED_TO_SYSTEM, "")
    start = without_additions.index(_DRAWING_RULE_START)
    end = without_additions.index(_DRAWING_RULE_END, start)
    assert without_additions[start:end] != _MEASURED_DRAWING_RULE
    measured_system = without_additions[:start] + _MEASURED_DRAWING_RULE + without_additions[end:]
    assert hashlib.sha256(measured_system.encode()).hexdigest() == _MEASURED_SYSTEM_SHA

    user = build_label_binding_user_prompt(_scheme(), page_count=19)
    assert user.count(_ADDED_TO_USER) == 1
    measured_user = user.replace(_ADDED_TO_USER, "")
    assert hashlib.sha256(measured_user.encode()).hexdigest() == _MEASURED_USER_SHA


def test_prompts_keep_the_rules_the_measurement_depended_on() -> None:
    system = _squash(LABEL_BINDING_SYSTEM_PROMPT)
    for rule in (
        # No question ids in the reply.
        "You do NOT name the question an answer belongs to.",
        "never add a question id field of any kind",
        # Numbered lines inside one part are not labels.
        "Numbered lines inside one part.",
        # A marked printed label is still a label.
        "A printed label is still a printed label when someone has ringed it, underlined it, "
        "ticked it or written over it.",
        # A bare question number is a label, even beside a stem or figure only.
        "even when its page holds only the introduction to the question or a figure",
        # Several printed prompt lines in one part.
        "keep each printed prompt with what the student wrote on it",
        # Unclear writing is placed by position and flagged.
        'Put the item where it is on the page, as for "position", and mark it "uncertain".',
        # Writing is never dropped.
        "Never drop writing.",
    ):
        assert rule in system, rule
    user = build_label_binding_user_prompt(_scheme(), page_count=19)
    assert "For orientation only" in user
    assert "never copy an entry of this list into your reply" in user
    assert "No item contains a question id." in user


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("0625_w24_ms_41", ["- 1(a)(i) [1 mark]", "- 1(b) [2 marks]", "- 9(c)(iv) [2 marks]"]),
        (
            "0606_s19_ms_23",
            ["- 1 [3 marks]", "- 3(ii) [2 marks]", "- 5(a)(i) [1 mark]", "- 10(iii) [4 marks]"],
        ),
        ("0580_s21_ms_31", ["- 1(a) [3 marks]", "- 7(a)(ii)(a) [3 marks]", "- 9(b) [1 mark]"]),
    ],
)
def test_user_prompt_lists_printed_labels_for_every_id_shape(
    name: str, expected: list[str]
) -> None:
    scheme = _scheme(name)
    leaves = _leaves(scheme)
    prompt = build_label_binding_user_prompt(scheme, page_count=12)
    lines = [line for line in prompt.splitlines() if line.startswith("- ")]

    assert len(lines) == len(leaves)
    for line, (_, marks) in zip(lines, leaves, strict=True):
        assert re.fullmatch(r"- [1-9][0-9]*(\([a-z]+\))* \[[0-9]+ marks?\]", line), line
        assert line.endswith(f"[{marks} mark{'' if marks == 1 else 's'}]")
    for line in expected:
        assert line in lines
    # No raw id: not "1a_i", not "3ii", not "7a_ii_a".
    for leaf_id, _ in leaves:
        if not leaf_id.isdigit():
            assert re.search(rf"(?<![\w(]){re.escape(leaf_id)}(?![\w)])", prompt) is None, leaf_id
    assert "_" not in "".join(lines)


def test_user_prompt_states_the_page_indices() -> None:
    prompt = build_label_binding_user_prompt(_scheme(), page_count=19)
    assert "You are given 19 page images, indexed 0 to 18 in the order attached." in prompt
    assert "Paper: 0625/41 Oct/Nov 2024." in prompt


def test_user_prompt_for_a_single_page_reads_as_english() -> None:
    prompt = build_label_binding_user_prompt(_scheme(), page_count=1)
    assert "You are given 1 page image, index 0. Every `page` value MUST be 0." in prompt
    assert "1 page images" not in prompt
    assert "0 to 0" not in prompt


@pytest.mark.parametrize("page_count", [0, -1])
def test_user_prompt_refuses_a_scan_with_no_pages(page_count: int) -> None:
    with pytest.raises(ValueError, match="page_count"):
        build_label_binding_user_prompt(_scheme(), page_count=page_count)


def test_user_prompt_names_a_specimen_paper() -> None:
    scheme = _scheme()
    specimen = scheme.model_copy(
        update={"metadata": scheme.metadata.model_copy(update={"session_year": None})}
    )
    prompt = build_label_binding_user_prompt(specimen, page_count=19)
    assert "Paper: 0625/41 Oct/Nov Specimen." in prompt
    assert "None" not in prompt


def _label_lines(scheme: MarkScheme) -> list[str]:
    prompt = build_label_binding_user_prompt(scheme, page_count=19)
    return [line for line in prompt.splitlines() if line.startswith("- ")]


@pytest.mark.parametrize(
    ("name", "path", "new_id", "lost"),
    [
        # A part whose id does not extend its parent's: "2a" under "1".
        ("0625_w24_ms_41", (0, 1), "2a", ["- 1(b) [2 marks]"]),
        # A part whose id adds nothing to its parent's.
        ("0625_w24_ms_41", (0, 1), "1", ["- 1(b) [2 marks]"]),
        # A part named by something a paper does not print in brackets.
        ("0625_w24_ms_41", (0, 1), "1B", ["- 1(b) [2 marks]"]),
        ("0625_w24_ms_41", (0, 1), "1_2", ["- 1(b) [2 marks]"]),
        # A container whose label cannot be told takes its parts with it.
        ("0625_w24_ms_41", (0, 0), "1_A", ["- 1(a)(i) [1 mark]", "- 1(a)(ii) [1 mark]"]),
        ("0625_w24_ms_41", (8,), "Q9", ["- 9(a) [1 mark]", "- 9(c)(iv) [2 marks]"]),
        # A question with no parts whose id is not a bare number.
        ("0606_s19_ms_23", (0,), "Q1", ["- 1 [3 marks]"]),
        ("0606_s19_ms_23", (0,), "01", ["- 1 [3 marks]"]),
        ("0606_s19_ms_23", (0,), "1a", ["- 1 [3 marks]"]),
    ],
)
def test_a_leaf_whose_printed_label_cannot_be_told_gets_no_line(
    name: str, path: tuple[int, ...], new_id: str, lost: list[str]
) -> None:
    """A wrong label is worse than a missing line: the list is there to say what to look for."""
    scheme = _scheme(name).model_copy(deep=True)
    before = _label_lines(scheme)
    question = scheme.questions[path[0]]
    for index in path[1:]:
        question = question.parts[index]
    question.id = new_id

    after = _label_lines(scheme)
    assert set(lost) <= set(before)
    assert not set(lost) & set(after)
    assert set(after) < set(before)  # nothing new is printed, and nothing is renamed
    lost_leaves = [q for q in (question, *_under(question)) if not q.parts]
    assert len(after) == len(before) - len(lost_leaves)
    for line in after:
        assert re.fullmatch(r"- [1-9][0-9]*(\([a-z]+\))* \[[0-9]+ marks?\]", line), line


def _under(question: Any) -> list[Any]:
    found = []
    for part in question.parts:
        found.append(part)
        found.extend(_under(part))
    return found


def test_every_printed_label_in_the_corpus_is_one_the_binding_can_read() -> None:
    """The prompt and ``label_sequence`` split ids by their own rules; this ties them."""
    schemes = sorted(_SCHEMES.glob("*.json"))
    assert len(schemes) > 250
    labels = 0
    for path in schemes:
        scheme = MarkScheme.model_validate(json.loads(path.read_text()))
        lines = _label_lines(scheme)
        assert len(lines) == len(_leaves(scheme)), path.stem
        for line in lines:
            label = line[2 : line.index(" [")]
            pieces = re.findall(r"[0-9]+|[a-z]+", label)
            assert [step.token for step in parse_label(label)] == pieces, (path.stem, label)
            labels += 1
    assert labels > 10_000


# --------------------------------------------------------------------------------------
# Parsing the reply
# --------------------------------------------------------------------------------------
def test_a_malformed_item_is_dropped_and_counted_and_order_is_kept(tmp_path: Path) -> None:
    items = [
        _label("1"),
        "1: B",  # malformed_item
        _label("(a)", kind="printed"),
        None,  # malformed_item
        _answer("first"),
        ["label", 0, "(b)"],  # malformed_item
        {"type": "note", "page": 0, "box": [1, 2, 3, 4], "text": "x"},  # unknown_type
        {"page": 0, "box": [1, 2, 3, 4], "text": "(b)"},  # unknown_type
        _label("   "),  # empty_label
        _label(None),  # empty_label
        _label(["(b)"]),  # empty_label
        _answer(None),  # empty_answer: the reader reported no writing
        _answer("  ", working_out=" "),  # empty_answer
        _answer("", working_out=None),  # empty_answer
        _label("(b)", page=1),
        _answer("second", page=1),
        _answer(42, page=2),
    ]
    read, _, _ = _read(tmp_path, items, page_count=4)

    assert [
        (type(i).__name__, getattr(i, "text", None) or getattr(i, "answer", None))
        for i in read.items
    ] == [
        ("SeenLabel", "1"),
        ("SeenLabel", "(a)"),
        ("SeenWriting", "first"),
        ("SeenLabel", "(b)"),
        ("SeenWriting", "second"),
        ("SeenWriting", "42"),
    ]
    assert read.drops == {
        "malformed_item": 3,
        "unknown_type": 2,
        "empty_label": 3,
        "empty_answer": 3,
    }
    assert [i.page for i in read.items] == [0, 0, 0, 1, 1, 2]


# A paper whose first question is read cleanly but for one item, which each test spoils.
def _question_one(**spoil: Any) -> list[dict[str, Any]]:
    second = {**_answer("20 cm", page=2), **spoil.get("answer", {})}
    for missing in spoil.get("answer_without", ()):
        del second[missing]
    return [
        _label("1", page=1),
        _label("(a)", page=2),
        _label("(i)", page=2),
        _answer("43 cm and 63 cm", page=2),
        {**_label("(ii)", page=2), **spoil.get("label", {})},
        second,
        _label("(b)", page=3),
        _answer("because of the spring", page=3),
        _label("(c)", page=3),
        _label("(i)", page=3),
        _answer("moment", page=3),
        _label("(ii)", page=3),
        _answer("12 N", page=3),
        # The opening of question 2, so that the list shows where question 1 ends.
        _label("2", page=4),
        _label("(a)", page=4),
        _label("(i)", page=4),
    ]


def read_item_keys(spoil: dict[str, Any]) -> set[str]:
    """The fields the spoiled answer item of ``_question_one`` is sent with."""
    return set(_question_one(**spoil)[5])


def _bind(read: StreamRead) -> tuple[BoundStream, BoundRead]:
    bound = bind_stream(read.items, _scheme())
    return bound, to_bound_read(bound, page_count=19, drops=read.drops)


def _blank_leaves(bound: BoundStream) -> list[str]:
    return [leaf.question_id for leaf in bound.leaves if not leaf.writings]


def _under_text(writing: Any, **extra: Any) -> dict[str, Any]:
    """What spoils 1(a)(ii)'s answer item the way the reader sometimes returns one.

    The shape is that of the stored replies: every field of an answer but ``answer``,
    and ``text``, the field a label uses, holding what the student wrote.
    """
    return {"answer": {"text": writing, **extra}, "answer_without": ("answer",)}


@pytest.mark.parametrize("answer", ["absent", None, "", "   "])
def test_an_answer_item_with_its_writing_under_text_is_read_as_that_answer(
    tmp_path: Path, answer: Any
) -> None:
    # The reply schema is flat, so ``text`` is a valid field on an answer item, and the
    # reader now and then fills it and leaves ``answer`` empty. That is writing it saw.
    slipped = _under_text("20 cm")
    if answer != "absent":
        slipped = {"answer": {"text": "20 cm", "answer": answer}}
    read, _, _ = _read(tmp_path, _question_one(**slipped), page_count=19)
    assert ("answer" in read_item_keys(slipped)) == (answer != "absent")

    assert read.drops == {"answer_under_text": 1}  # counted, so the rate stays visible
    assert len(read.items) == 16
    assert read.items[5] == SeenWriting(
        page=2,
        answer="20 cm",
        working_out=None,
        confidence=0.9,
        box=[100, 100, 200, 600],
        placed_by="position",  # as the reader placed it: the repair costs it nothing
    )
    bound, bound_read = _bind(read)
    assert {a.question_id: a.answer for a in bound_read.answers}["1a_ii"] == "20 cm"
    assert bound_read.unbound == [] and bound_read.unaligned_ids[:1] != ["1a_ii"]
    assert bound_read.drops == {"answer_under_text": 1}


def test_writing_under_text_keeps_the_working_and_the_placement_beside_it(tmp_path: Path) -> None:
    slipped = _under_text("20 cm", working_out="63 - 43", placed_by="arrow", confidence=0.7)
    read, _, _ = _read(tmp_path, _question_one(**slipped), page_count=19)
    assert read.drops == {"answer_under_text": 1}
    assert read.items[5] == SeenWriting(
        page=2,
        answer="20 cm",
        working_out="63 - 43",
        confidence=0.7,
        box=[100, 100, 200, 600],
        placed_by="arrow",
    )


def test_text_on_an_answer_item_that_has_an_answer_is_not_read(tmp_path: Path) -> None:
    # Some replies carry the other type's fields on every item. ``answer`` is the
    # answer; ``text`` beside it is not added to it and nothing is counted.
    both = {**_answer("20 cm", page=2), "text": "(ii)", "kind": "printed"}
    read, _, _ = _read(tmp_path, _question_one(answer=both), page_count=19)
    assert read.drops == {}
    assert read.items[5] == _writing("20 cm", page=2, box=[100, 100, 200, 600])
    # Working alone is writing too: ``text`` is read only when there is no answer, and
    # then it is the answer and the working stays the working.
    working_only = {**_answer(None, page=2, working_out="63 - 43"), "text": "  "}
    read, _, _ = _read(tmp_path / "working", _question_one(answer=working_only), page_count=19)
    assert read.drops == {}
    assert (read.items[5].answer, read.items[5].working_out) == ("", "63 - 43")


def test_text_that_is_not_text_on_an_empty_answer_item_is_kept_as_uncertain(
    tmp_path: Path,
) -> None:
    # The reader reported something there. It cannot be read, so it is trusted to no
    # leaf, and the leaf is not taken for one left blank.
    read, _, _ = _read(tmp_path, _question_one(**_under_text(["20", "cm"])), page_count=19)
    assert read.drops == {"unreadable_answer": 1}
    assert read.items[5].placed_by == "uncertain" and read.items[5].answer == ""
    _bound, bound_read = _bind(read)
    assert "1a_ii" not in {a.question_id for a in bound_read.answers}
    assert "1a_ii" in bound_read.unaligned_ids


def test_a_label_item_is_read_as_before_whatever_else_it_carries(tmp_path: Path) -> None:
    # A label with an ``answer`` beside its ``text`` is still that label, and a label
    # with no ``text`` is still dropped: its ``answer`` is not taken for its text.
    with_answer = {"label": {"answer": "20 cm", "working_out": "x", "placed_by": "position"}}
    read, _, _ = _read(tmp_path, _question_one(**with_answer), page_count=19)
    assert read.drops == {}
    assert read.items[4] == SeenLabel(page=2, text="(ii)", kind="printed", box=[10, 10, 30, 40])
    no_text = {"label": {"text": None, "answer": "(ii)"}}
    read, _, _ = _read(tmp_path / "no-text", _question_one(**no_text), page_count=19)
    assert read.drops == {"empty_label": 1}
    assert len(read.items) == 15


def test_the_clean_first_question_binds_whole(tmp_path: Path) -> None:
    """The control for the three tests below: unspoiled, every part holds its own answer."""
    read, _, _ = _read(tmp_path, _question_one(), page_count=19)
    bound, bound_read = _bind(read)
    assert read.drops == {}
    assert {a.question_id: a.answer for a in bound_read.answers} == {
        "1a_i": "43 cm and 63 cm",
        "1a_ii": "20 cm",
        "1b": "because of the spring",
        "1c_i": "moment",
        "1c_ii": "12 N",
    }
    assert bound_read.unbound == []
    assert [leaf for leaf in _blank_leaves(bound) if leaf.startswith("1")] == []


@pytest.mark.parametrize("page", [454, 19, -1, 1.5, None, "two", True, "absent"])
def test_an_answer_with_a_bad_page_is_kept_as_uncertain_and_its_leaf_is_not_blank(
    tmp_path: Path, page: Any
) -> None:
    """Writing the reader reported must never come out as an answer left blank."""
    spoil: dict[str, Any] = (
        {"answer_without": ("page",)} if page == "absent" else {"answer": {"page": page}}
    )
    read, _, _ = _read(tmp_path, _question_one(**spoil), page_count=19)

    assert read.drops == {"repaired_page": 1}
    assert len(read.items) == 16
    kept = read.items[5]
    assert kept == SeenWriting(
        page=2,  # the page of the item before it
        answer="20 cm",
        working_out=None,
        confidence=0.9,
        box=None,  # a box means nothing on a guessed page
        placed_by="uncertain",
    )

    bound, bound_read = _bind(read)
    assert [u.writing.answer for u in bound_read.unbound] == ["20 cm"]
    assert "1a_ii" not in _blank_leaves(bound)
    assert "1a_ii" not in {a.question_id for a in bound_read.answers}
    assert "1a_ii" in bound_read.unaligned_ids
    assert bound_read.drops == {"repaired_page": 1}


@pytest.mark.parametrize(
    ("answer", "working_out", "kept_answer", "kept_working"),
    [
        (["20 cm"], None, "", None),
        ({"value": "20 cm"}, None, "", None),
        (True, None, "", None),
        (float("inf"), None, "", None),
        (["20 cm"], ["s = d / t"], "", None),
        (None, ["s = d / t"], "", None),
        # What can be read is kept; the item is still not trusted to a leaf.
        (["20 cm"], "s = d / t", "", "s = d / t"),
        ("20 cm", {"step": 1}, "20 cm", None),
    ],
)
def test_an_answer_with_unreadable_text_is_kept_as_uncertain(
    tmp_path: Path, answer: Any, working_out: Any, kept_answer: str, kept_working: str | None
) -> None:
    spoil = {"answer": {"answer": answer, "working_out": working_out}}
    read, _, _ = _read(tmp_path, _question_one(**spoil), page_count=19)

    assert read.drops == {"unreadable_answer": 1}
    assert len(read.items) == 16
    assert read.items[5] == SeenWriting(
        page=2,
        answer=kept_answer,
        working_out=kept_working,
        confidence=0.9,
        box=[100, 100, 200, 600],
        placed_by="uncertain",
    )

    bound, bound_read = _bind(read)
    assert "1a_ii" not in _blank_leaves(bound)
    assert "1a_ii" not in {a.question_id for a in bound_read.answers}
    assert "1a_ii" in bound_read.unaligned_ids
    assert [u.writing for u in bound_read.unbound] == [read.items[5]]
    assert bound_read.drops == {"unreadable_answer": 1}


def test_an_answer_with_a_bad_page_and_unreadable_text_is_counted_twice(tmp_path: Path) -> None:
    spoil = {"answer": {"answer": ["20 cm"], "page": 454}}
    read, _, _ = _read(tmp_path, _question_one(**spoil), page_count=19)
    assert read.drops == {"repaired_page": 1, "unreadable_answer": 1}
    assert read.items[5] == SeenWriting(
        page=2, answer="", box=None, confidence=0.9, placed_by="uncertain"
    )


@pytest.mark.parametrize("page", [454, None, "two", 1.5])
def test_a_label_with_a_bad_page_is_kept_in_order(tmp_path: Path, page: Any) -> None:
    """Order is the binding evidence, not the page: dropping the label would be a missed label."""
    read, _, _ = _read(tmp_path, _question_one(label={"page": page}), page_count=19)

    assert read.drops == {"repaired_page": 1}
    assert len(read.items) == 16
    assert read.items[4] == SeenLabel(page=2, text="(ii)", kind="printed", box=None)

    bound, bound_read = _bind(read)
    answers = {a.question_id: a.answer for a in bound_read.answers}
    assert answers["1a_i"] == "43 cm and 63 cm"
    assert answers["1a_ii"] == "20 cm"
    assert len(answers) == 5
    assert [leaf for leaf in _blank_leaves(bound) if leaf.startswith("1")] == []
    assert bound_read.unbound == []


def test_a_bad_page_on_the_first_item_becomes_page_zero(tmp_path: Path) -> None:
    read, _, _ = _read(tmp_path, [_label("1", page=99), _answer("x", page=None)], page_count=4)
    assert read.drops == {"repaired_page": 2}
    assert [(type(i), i.page, i.box) for i in read.items] == [
        (SeenLabel, 0, None),
        (SeenWriting, 0, None),
    ]


def test_a_repaired_page_follows_the_last_kept_item_not_a_dropped_one(tmp_path: Path) -> None:
    items = [_label("1", page=1), _label("  ", page=3), _answer("x", page=77)]
    read, _, _ = _read(tmp_path, items, page_count=4)
    assert read.drops == {"empty_label": 1, "repaired_page": 1}
    assert [i.page for i in read.items] == [1, 1]


def test_a_number_too_large_to_handle_costs_no_exception(tmp_path: Path) -> None:
    read, _, _ = _read(tmp_path, [_label("1"), _answer("x", confidence=10**400)])
    assert read.drops == {}
    assert read.items[1] == SeenWriting(
        page=0, answer="x", confidence=0.0, box=[100, 100, 200, 600], placed_by="position"
    )
    # Too many digits for Python to turn into text: unreadable, not an exception.
    read = parse_stream_items([_label("1"), _answer(10**5000)], page_count=4)
    assert read.drops == {"unreadable_answer": 1}
    assert read.items[1] == SeenWriting(
        page=0, answer="", confidence=0.9, box=[100, 100, 200, 600], placed_by="uncertain"
    )


@pytest.mark.parametrize("not_a_list", [None, "label", {"type": "label"}, 3])
def test_parse_stream_items_refuses_what_is_not_a_list(not_a_list: Any) -> None:
    with pytest.raises(TypeError):
        parse_stream_items(not_a_list, page_count=4)


@pytest.mark.parametrize("items", ["none", None, {"type": "label"}, 7])
def test_a_reply_whose_items_is_not_a_list_is_a_parse_error(tmp_path: Path, items: Any) -> None:
    """There is nothing to salvage item by item when the list itself is missing."""
    client, _ = _client(tmp_path, {"items": items})
    pages = _pages(2)
    with (
        client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
        pytest.raises(ParseError),
    ):
        LabelBinder(client).read(pages, _scheme(), uploads=uploads, extra_cache_key="k")


def test_label_text_loses_its_padding_and_answer_text_does_not(tmp_path: Path) -> None:
    read, _, _ = _read(tmp_path, [_label("  (a) \n"), _answer(" 12 V\n", working_out=" F = m a ")])
    assert read.drops == {}
    assert isinstance(read.items[0], SeenLabel)
    assert read.items[0].text == "(a)"
    assert isinstance(read.items[1], SeenWriting)
    assert read.items[1].answer == " 12 V\n"
    assert read.items[1].working_out == " F = m a "


def test_a_clean_reply_has_no_drops(tmp_path: Path) -> None:
    read, _, _ = _read(tmp_path, [_label("1"), _answer("x")])
    assert read.drops == {}
    assert read.items == [
        SeenLabel(page=0, text="1", kind="printed", box=[10, 10, 30, 40]),
        SeenWriting(
            page=0,
            answer="x",
            working_out=None,
            confidence=0.9,
            box=[100, 100, 200, 600],
            placed_by="position",
        ),
    ]


def test_a_key_beside_items_in_the_reply_is_not_an_error(tmp_path: Path) -> None:
    client, genai = _client(tmp_path, {"items": [_label("1")], "notes": "nothing else to add"})
    pages = _pages(2)
    with client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads:
        read = LabelBinder(client).read(pages, _scheme(), uploads=uploads, extra_cache_key="k")
    assert [type(i) for i in read.items] == [SeenLabel]
    assert genai.models.generate_content.call_count == 1  # no corrective second call


def test_a_near_miss_item_is_read_and_not_dropped(tmp_path: Path) -> None:
    """A value that is off the schema but plain in meaning costs nothing."""
    items = [
        _label(4, type="Label", page="1"),
        _answer(9.5, type=" ANSWER ", page=2.0),
    ]
    read, _, _ = _read(tmp_path, items)
    assert read.drops == {}
    assert [(type(i), i.page) for i in read.items] == [(SeenLabel, 1), (SeenWriting, 2)]
    assert isinstance(read.items[0], SeenLabel)
    assert read.items[0].text == "4"
    assert isinstance(read.items[1], SeenWriting)
    assert read.items[1].answer == "9.5"


def test_writing_whose_text_is_all_in_the_working_is_kept(tmp_path: Path) -> None:
    """The reader sometimes puts a note in ``working_out`` and leaves ``answer`` null.

    That is still student writing; dropping it would hide it from the binding.
    """
    read, _, _ = _read(tmp_path, [_label("1"), _answer(None, working_out="V = I R")])
    assert read.drops == {}
    assert read.items[1] == SeenWriting(
        page=0,
        answer="",
        working_out="V = I R",
        confidence=0.9,
        box=[100, 100, 200, 600],
        placed_by="position",
    )


def test_an_item_is_read_by_its_type_and_other_fields_are_ignored(tmp_path: Path) -> None:
    """A reply item never carries an id into the stream, whatever the reader adds to it."""
    items = [
        _label("(a)", answer="stray", placed_by="arrow", confidence=0.2, question_id="1a"),
        _answer("x", text="(b)", kind="handwritten", question_id="1b"),
    ]
    read, _, _ = _read(tmp_path, items)
    assert read.drops == {}
    assert read.items == [
        SeenLabel(page=0, text="(a)", kind="printed", box=[10, 10, 30, 40]),
        SeenWriting(
            page=0, answer="x", confidence=0.9, box=[100, 100, 200, 600], placed_by="position"
        ),
    ]
    assert "question_id" not in json.dumps([i.model_dump() for i in read.items])


@pytest.mark.parametrize(
    "box",
    [
        None,
        "top right of the page",
        [10, 20, 30],
        [10, 20, 30, 40, 50],
        [300, 100, 200, 600],  # ymax above ymin
        [100, 600, 200, 100],  # xmax left of xmin
        [100, 100, 200, 1200],  # off the page
        [-5, 100, 200, 600],
        [100, "x", 200, 600],
        [float("nan"), 100, 200, 600],
        {"ymin": 1},
        True,
    ],
)
def test_a_bad_box_never_drops_an_item(tmp_path: Path, box: Any) -> None:
    items = [{**_label("1"), "box": box}, {**_answer("x"), "box": box}]
    read, _, _ = _read(tmp_path, items)
    assert read.drops == {}
    assert [type(i) for i in read.items] == [SeenLabel, SeenWriting]
    assert [i.box for i in read.items] == [None, None]


def test_a_missing_box_never_drops_an_item(tmp_path: Path) -> None:
    label, answer = _label("1"), _answer("x")
    del label["box"], answer["box"]
    read, _, _ = _read(tmp_path, [label, answer])
    assert read.drops == {}
    assert [i.box for i in read.items] == [None, None]


def test_a_usable_box_is_kept_as_four_integers(tmp_path: Path) -> None:
    items = [
        {**_label("1"), "box": [10.4, "20", 30.6, 40]},
        {**_answer("x"), "box": [0, 0, 1000, 1000]},
    ]
    read, _, _ = _read(tmp_path, items)
    assert [i.box for i in read.items] == [[10, 20, 31, 40], [0, 0, 1000, 1000]]


def test_unknown_placed_by_becomes_uncertain(tmp_path: Path) -> None:
    missing = _answer("e")
    del missing["placed_by"]
    items = [
        _label("1"),
        _answer("a", placed_by="margin"),
        _answer("b", placed_by=None),
        _answer("c", placed_by=3),
        _answer("d", placed_by="ARROW"),
        missing,
        _answer("f", placed_by="position"),
        _answer("g", placed_by="arrow"),
        _answer("h", placed_by="uncertain"),
    ]
    read, _, _ = _read(tmp_path, items)
    assert read.drops == {}
    assert [i.placed_by for i in read.items if isinstance(i, SeenWriting)] == [
        "uncertain",
        "uncertain",
        "uncertain",
        "uncertain",
        "uncertain",
        "position",
        "arrow",
        "uncertain",
    ]


def test_unknown_kind_becomes_printed(tmp_path: Path) -> None:
    missing = _label("(c)")
    del missing["kind"]
    items = [
        _label("1", kind="typed"),
        _label("(a)", kind=None),
        _label("(b)", kind="handwritten"),
        missing,
        _label("(d)", kind="printed"),
        _label("(e)", kind=" Handwritten "),
        _label("(f)", kind=["handwritten"]),
    ]
    read, _, _ = _read(tmp_path, items)
    assert read.drops == {}
    assert [i.kind for i in read.items if isinstance(i, SeenLabel)] == [
        "printed",
        "printed",
        "handwritten",
        "printed",
        "printed",
        "handwritten",
        "printed",
    ]


@pytest.mark.parametrize("confidence", [None, "high", float("nan"), 1.7, -0.1, True])
def test_missing_or_unusable_confidence_becomes_zero(tmp_path: Path, confidence: Any) -> None:
    missing = _answer("b")
    del missing["confidence"]
    read, _, _ = _read(tmp_path, [_label("1"), _answer("a", confidence=confidence), missing])
    assert read.drops == {}
    assert [i.confidence for i in read.items if isinstance(i, SeenWriting)] == [0.0, 0.0]


def test_model_override_reaches_the_client(tmp_path: Path) -> None:
    _, genai, spy = _read(tmp_path / "a", [_label("1")], model="gemini-override")
    assert genai.models.generate_content.call_args.kwargs["model"] == "gemini-override"
    assert spy.call_args.kwargs["model"] == "gemini-override"

    with _IsolatedEnv():
        configured = load_settings(toml_path=None, cwd=tmp_path).gemini.model_for("extraction")
    _, genai, spy = _read(tmp_path / "b", [_label("1")])
    assert spy.call_args.kwargs["model"] is None
    assert genai.models.generate_content.call_args.kwargs["model"] == configured


def test_the_call_is_an_extraction_call_carrying_every_page(tmp_path: Path) -> None:
    scheme = _scheme()
    _, genai, spy = _read(tmp_path, [_label("1")], page_count=3, scheme=scheme)
    sent = spy.call_args.kwargs
    assert sent["task_tag"] == "extraction"
    assert sent["prompt_version"] == LABEL_BINDING_PROMPT_VERSION == "3"
    assert sent["system_prompt"] == LABEL_BINDING_SYSTEM_PROMPT
    assert sent["user_prompt"] == build_label_binding_user_prompt(scheme, page_count=3)
    assert sent["image_parts"] == [b"page-0", b"page-1", b"page-2"]
    assert sent["image_uploads"] is not None
    assert sent["media_resolution"] == "high"
    assert sent["extra_cache_key"] == "scan-1"
    assert genai.models.generate_content.call_count == 1


def test_media_resolution_reaches_the_client(tmp_path: Path) -> None:
    _, _, spy = _read(tmp_path, [_label("1")], media_resolution="medium")
    assert spy.call_args.kwargs["media_resolution"] == "medium"


def test_cost_ceiling_error_propagates() -> None:
    error = CostCeilingError("USD ceiling exceeded")
    client = MagicMock(spec=GeminiClient)
    client.generate_structured.side_effect = error
    with pytest.raises(CostCeilingError) as caught:
        LabelBinder(client).read(_pages(2), _scheme(), uploads=MagicMock(), extra_cache_key="k")
    assert caught.value is error


def test_service_error_propagates() -> None:
    error = ExternalServiceError("Gemini unavailable")
    client = MagicMock(spec=GeminiClient)
    client.generate_structured.side_effect = error
    with pytest.raises(ExternalServiceError) as caught:
        LabelBinder(client).read(_pages(2), _scheme(), uploads=MagicMock(), extra_cache_key="k")
    assert caught.value is error


# --------------------------------------------------------------------------------------
# The recorded streams, end to end
# --------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> dict[int, tuple[StreamRead, BoundRead]]:
    """Each recorded reply through the binder's own parsing, ``bind_stream``, the conversion."""
    scheme = _scheme()
    out = {}
    for run in _RUNS:
        record = json.loads((_FIXTURES / "streams" / f"A_run{run}.json").read_text())
        read, _, _ = _read(
            tmp_path_factory.mktemp(f"run{run}"),
            record["items"],
            page_count=record["page_count"],
            scheme=scheme,
        )
        bound = bind_stream(read.items, scheme)
        out[run] = (
            read,
            to_bound_read(bound, page_count=record["page_count"], drops=read.drops),
        )
    return out


@pytest.mark.parametrize("run", _RUNS)
def test_recorded_streams_convert_to_the_expected_answers(
    recorded: dict[int, tuple[StreamRead, BoundRead]], run: int
) -> None:
    read, bound_read = recorded[run]
    answers = {a.question_id: a for a in bound_read.answers}

    assert read.drops == {}, "a recorded item was dropped or repaired"
    assert bound_read.drops == {}
    assert len(bound_read.answers) == len(answers) == 42
    assert "7c" not in answers  # left blank by the student
    assert set(answers) == {leaf_id for leaf_id, _ in _leaves(_scheme())} - {"7c"}
    assert "43" in answers["1a_i"].answer
    assert "63" in answers["1a_i"].answer
    assert "20" in answers["1a_ii"].answer
    assert "43" not in answers["1a_ii"].answer
    assert {a.binding_source for a in bound_read.answers} == {"label"}
    assert {a.binding_status for a in bound_read.answers} <= {"verified", "unverified"}
    assert all(a.label_seen for a in bound_read.answers)
    assert bound_read.unaligned_ids == []
    assert bound_read.unplaced_labels == 0
    assert bound_read.listing_suspects == []
    assert bound_read.review_ids == [
        a.question_id for a in bound_read.answers if a.binding_status == "unverified"
    ]


def test_recorded_streams_keep_every_item(
    recorded: dict[int, tuple[StreamRead, BoundRead]],
) -> None:
    kept = {run: len(read.items) for run, (read, _) in recorded.items()}
    assert kept == {1: 110, 2: 116, 3: 112, 4: 107, 5: 112}


def test_recorded_review_ids(recorded: dict[int, tuple[StreamRead, BoundRead]]) -> None:
    assert {run: bound_read.review_ids for run, (_, bound_read) in recorded.items()} == {
        1: ["7b_i"],
        # Replies 2 and 5 flag the notes at the top of pages 13, 15 and 18 as uncertain,
        # so they are set aside; the leaves they were listed under (6b, 7b_i, 8d) carry
        # the doubt "some writing under this label was set aside".
        2: ["2c", "6b", "7b_i", "8d"],
        3: ["4b_i", "6b", "7b_i", "8d"],
        4: ["3c", "4b_i"],
        5: ["3c", "4b_i", "6b", "7b_i", "8d"],
    }


@pytest.mark.parametrize("run", [4, 5])
def test_inferred_number_doubt_does_not_make_a_leaf_unverified(
    recorded: dict[int, tuple[StreamRead, BoundRead]], run: int
) -> None:
    """The ringed ``4`` was not listed. Question 4's parts were all seen, so its number is
    inferred: that is not a doubt about what the leaves hold. The leaf before it, 3(c), may
    hold what was written beside the unseen number, and is.
    """
    _, bound_read = recorded[run]
    answers = {a.question_id: a for a in bound_read.answers}

    assert bound_read.inferred_numbers == ["4"]
    for leaf_id in ("4a", "4b_ii", "4b_iii"):
        assert answers[leaf_id].binding_status == "verified", leaf_id
        assert leaf_id not in bound_read.review_ids
    assert answers["3c"].binding_status == "unverified"
    # 4(b)(i) is unverified for its own reason: the arrow-tied sentence.
    assert answers["4b_i"].binding_status == "unverified"
    # In questions 3 and 4 nothing else is doubted. (Reply 5 doubts three leaves further
    # on for a reason of their own: writing set aside under them.)
    assert [qid for qid in bound_read.review_ids if qid[0] in "34"] == ["3c", "4b_i"]


# --------------------------------------------------------------------------------------
# Converting a bound stream
# --------------------------------------------------------------------------------------
def test_two_writings_on_one_leaf_join_in_order() -> None:
    bound = _bound(
        _leaf(
            "1a",
            _writing("first line", working_out="F = m a", confidence=0.95),
            _writing("second line", confidence=0.6),
            _writing("third line", working_out="= 2.0 x 3.0", confidence=0.8),
        )
    )
    (answer,) = to_bound_read(bound, page_count=2, drops={}).answers

    assert answer.question_id == "1a"
    assert answer.answer == "first line; second line; third line"
    assert answer.working_out == "F = m a\n= 2.0 x 3.0"
    assert answer.confidence == 0.6
    assert answer.binding_source == "label"
    assert answer.binding_status == "verified"
    assert answer.label_seen == "(a)"


def test_one_writing_is_carried_over_unchanged() -> None:
    bound = _bound(_leaf("1a", _writing("1. copper\n2. zinc", confidence=0.85)))
    (answer,) = to_bound_read(bound, page_count=2, drops={}).answers
    assert answer.answer == "1. copper\n2. zinc"
    assert answer.working_out is None
    assert answer.confidence == 0.85


def test_a_writing_with_no_answer_text_adds_only_its_working() -> None:
    bound = _bound(_leaf("1a", _writing("", working_out="V = I R"), _writing("12 V")))
    (answer,) = to_bound_read(bound, page_count=2, drops={}).answers
    assert answer.answer == "12 V"
    assert answer.working_out == "V = I R"


@pytest.mark.parametrize("doubt", [DOUBT_PREVIOUS_PAGE, DOUBT_ARROW, DOUBT_NEXT_NUMBER_NOT_SEEN])
def test_content_doubt_makes_a_leaf_unverified_and_lists_it_for_review(doubt: str) -> None:
    bound = _bound(
        _leaf("1a", _writing("x")),
        _leaf("1b", _writing("y"), doubts=(doubt,)),
        _leaf("1c", _writing("z")),
        _leaf("2a", _writing("w"), doubts=(DOUBT_NUMBER_NOT_SEEN, doubt)),
    )
    bound_read = to_bound_read(bound, page_count=2, drops={})

    assert [(a.question_id, a.binding_status) for a in bound_read.answers] == [
        ("1a", "verified"),
        ("1b", "unverified"),
        ("1c", "verified"),
        ("2a", "unverified"),
    ]
    assert bound_read.review_ids == ["1b", "2a"]


def test_an_inferred_number_alone_leaves_a_hand_built_leaf_verified() -> None:
    bound = _bound(_leaf("4a", _writing("x"), doubts=(DOUBT_NUMBER_NOT_SEEN,)))
    bound_read = to_bound_read(bound, page_count=2, drops={})
    assert [a.binding_status for a in bound_read.answers] == ["verified"]
    assert bound_read.review_ids == []


def test_a_doubt_of_neither_class_makes_a_leaf_unverified() -> None:
    """A doubt this module has not been told about must not pass as verified."""
    bound = _bound(_leaf("1a", _writing("x"), doubts=("a doubt added later",)))
    bound_read = to_bound_read(bound, page_count=2, drops={})
    assert [a.binding_status for a in bound_read.answers] == ["unverified"]
    assert bound_read.review_ids == ["1a"]


def test_the_two_doubt_classes_cover_every_doubt_the_binding_can_raise() -> None:
    """The conversion reads the classes from ``label_sequence`` and keeps no list of its own.

    This pins only what it relies on: every doubt is in exactly one class. Which doubts
    exist, and which class each is in, is ``label_sequence``'s to say.
    """
    assert set(DOUBTS) == set(CONTENT_DOUBTS) | set(INFERENCE_DOUBTS)
    assert not set(CONTENT_DOUBTS) & set(INFERENCE_DOUBTS)
    assert CONTENT_DOUBTS and INFERENCE_DOUBTS


@pytest.mark.parametrize("doubt", CONTENT_DOUBTS)
def test_every_content_doubt_makes_an_answer_unverified(doubt: str) -> None:
    read = to_bound_read(
        _bound(_leaf("1a", _writing("x"), doubts=(doubt,)), _leaf("1b", _writing("y"))),
        page_count=2,
        drops={},
    )
    assert [a.binding_status for a in read.answers] == ["unverified", "verified"]
    assert read.review_ids == ["1a"]


@pytest.mark.parametrize("doubt", INFERENCE_DOUBTS)
def test_an_inference_doubt_alone_leaves_an_answer_verified(doubt: str) -> None:
    read = to_bound_read(
        _bound(_leaf("1a", _writing("x"), doubts=(doubt,))), page_count=2, drops={}
    )
    assert [a.binding_status for a in read.answers] == ["verified"]
    # With a content doubt beside it, the content doubt decides.
    both = to_bound_read(
        _bound(_leaf("1a", _writing("x"), doubts=(doubt, CONTENT_DOUBTS[0]))),
        page_count=2,
        drops={},
    )
    assert [a.binding_status for a in both.answers] == ["unverified"]


def test_a_doubt_of_neither_class_does_not_pass() -> None:
    read = to_bound_read(
        _bound(_leaf("1a", _writing("x"), doubts=("a doubt nobody has classified",))),
        page_count=2,
        drops={},
    )
    assert [a.binding_status for a in read.answers] == ["unverified"]


def test_blank_aligned_leaf_produces_no_answer() -> None:
    bound = _bound(
        _leaf("1a", _writing("x")),
        _leaf("1b"),
        _leaf("1c", doubts=(DOUBT_NEXT_NUMBER_NOT_SEEN,)),
        _leaf("2a", _writing("y")),
    )
    bound_read = to_bound_read(bound, page_count=2, drops={})
    assert [a.question_id for a in bound_read.answers] == ["1a", "2a"]
    # Nothing was written on 1c, so there is nothing of anyone's to review.
    assert bound_read.review_ids == []


def test_source_box_is_the_union_on_the_first_page_or_none() -> None:
    bound = _bound(
        # Two boxes on the first writing's page, one on a later page.
        _leaf(
            "1a",
            _writing("a", page=1, box=[100, 200, 150, 600]),
            _writing("b", page=1, box=[160, 150, 220, 500]),
            _writing("c", page=2, box=[10, 10, 900, 900]),
        ),
        # No box at all.
        _leaf("1b", _writing("d", page=1)),
        # The first writing has no usable box; another on its page has.
        _leaf(
            "1c",
            _writing("e", page=1, box=[300, 100, 200, 600]),
            _writing("f", page=1, box=[400, 100, 450, 600]),
        ),
        # Only a later page has a box: the answer's page is the first writing's.
        _leaf("1d", _writing("g", page=1), _writing("h", page=2, box=[10, 10, 90, 90])),
        # Off the page, and a page that was never sent.
        _leaf("1e", _writing("i", page=1, box=[100, 100, 200, 1200])),
        _leaf("1f", _writing("j", page=7, box=[100, 100, 200, 600])),
        _leaf("1g", _writing("k", page=0, box=[1, 2, 3])),
    )
    boxes = {
        a.question_id: a.source_box for a in to_bound_read(bound, page_count=3, drops={}).answers
    }

    assert boxes == {
        "1a": SourceBox(page=1, box=[100, 150, 220, 600]),
        "1b": None,
        "1c": SourceBox(page=1, box=[400, 100, 450, 600]),
        "1d": None,
        "1e": None,
        "1f": None,
        "1g": None,
    }


@pytest.mark.parametrize("confidence", [1.7, -0.2, float("nan"), float("inf")])
def test_a_confidence_out_of_range_on_a_hand_built_writing_becomes_zero(confidence: float) -> None:
    """``SeenWriting`` does not bound its confidence; an answer's must lie in 0 to 1."""
    bound = _bound(_leaf("1a", _writing("x", confidence=0.8), _writing("y", confidence=confidence)))
    (answer,) = to_bound_read(bound, page_count=2, drops={}).answers
    assert answer.confidence == 0.0


def test_drops_travel_with_the_bound_read() -> None:
    drops = {"repaired_page": 2, "empty_answer": 1}
    bound_read = to_bound_read(_bound(_leaf("1a", _writing("x"))), page_count=2, drops=drops)
    assert bound_read.drops == {"repaired_page": 2, "empty_answer": 1}
    # A copy: the read's own record cannot be changed through the bound read.
    bound_read.drops["repaired_page"] = 0
    assert drops == {"repaired_page": 2, "empty_answer": 1}


def test_what_was_not_bound_passes_through() -> None:
    stray = UnboundWriting(writing=_writing("stray"), reason="uncertain")
    unplaced = [
        SeenLabel(page=0, text="(z)", kind="printed"),
        SeenLabel(page=1, text="Q9", kind="handwritten"),
    ]
    bound = _bound(
        _leaf("1a", _writing("x")),
        unbound=[stray],
        unaligned_ids=["1b", "2"],
        unplaced_labels=unplaced,
        inferred_numbers=["4"],
        listing_suspects=["1a", "3"],
    )
    bound_read = to_bound_read(bound, page_count=2, drops={})

    assert bound_read.unbound == [stray]
    assert bound_read.unaligned_ids == ["1b", "2"]
    assert bound_read.unplaced_labels == 2
    assert bound_read.inferred_numbers == ["4"]
    assert bound_read.listing_suspects == ["1a", "3"]
    # Unbound writing is given to no question, and no id is made up for it.
    assert [a.question_id for a in bound_read.answers] == ["1a"]


def test_conversion_assigns_no_id_of_its_own() -> None:
    """Every answer's id is the id of the leaf it came from: the list is not renumbered."""
    bound = _bound(
        _leaf("9c_iv", _writing("x")),
        _leaf("2a_i"),
        _leaf("7a_ii_a", _writing("y")),
        _leaf("3ii", _writing("z")),
    )
    assert [a.question_id for a in to_bound_read(bound, page_count=2, drops={}).answers] == [
        "9c_iv",
        "7a_ii_a",
        "3ii",
    ]


def test_bound_read_carries_why_each_leaf_was_not_bound() -> None:
    # Reply 4 lacks the label `4`; without the `(i)` of 4(b) as well, leaf 4b_i has no
    # label in the list. `bind_stream` says why for each unaligned leaf, and the record
    # the rest of the pipeline uses keeps it.
    data = json.loads((_FIXTURES / "streams" / "A_run4.json").read_text())
    kept = [
        item
        for item in data["items"]
        if not (item.get("type") == "label" and item.get("text") == "(i)" and item.get("page") == 9)
    ]
    stream = parse_stream_items(kept, page_count=data["page_count"])
    bound = bind_stream(stream.items, _scheme())
    read = to_bound_read(bound, page_count=data["page_count"], drops=stream.drops)
    assert read.unaligned_ids == ["4b_i"]
    assert read.unaligned_reasons == bound.unaligned_reasons == {"4b_i": "label_not_seen"}
    assert read.unaligned_reasons is not bound.unaligned_reasons  # a copy, like the other fields
