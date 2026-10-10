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
)
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import SourceBox
from lemely.io.binding import BoundRead, LabelBinder, StreamRead, to_bound_read
from lemely.io.gemini import GeminiClient, _strip_schema
from lemely.io.prompts import (
    LABEL_BINDING_PROMPT_VERSION,
    LABEL_BINDING_SYSTEM_PROMPT,
    build_label_binding_user_prompt,
)
from lemely.io.rasterise import RasterisedPage
from lemely.runtime.config import PathsSettings, load_settings
from lemely.runtime.errors import CostCeilingError, ExternalServiceError
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
) -> tuple[StreamRead, MagicMock, MagicMock]:
    """Run ``LabelBinder.read`` on a reply; also return the SDK fake and the call spy."""
    client, genai = _client(tmp, {"items": items})
    pages = _pages(page_count)
    with (
        client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
        patch.object(client, "generate_structured", wraps=client.generate_structured) as spy,
    ):
        read = LabelBinder(client).read(
            pages, scheme or _scheme(), uploads=uploads, model=model, extra_cache_key="scan-1"
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
    """Every difference from the prompt that was measured is named here, and is an addition."""
    assert LABEL_BINDING_SYSTEM_PROMPT.count(_ADDED_TO_SYSTEM) == 1
    measured_system = LABEL_BINDING_SYSTEM_PROMPT.replace(_ADDED_TO_SYSTEM, "")
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
        _answer(None),  # empty_answer
        _answer("  ", working_out=" "),  # empty_answer
        _answer("lost", page=99),  # bad_page
        _label("(b)", page="top"),  # bad_page
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
        "empty_label": 2,
        "empty_answer": 2,
        "bad_page": 2,
    }
    assert [i.page for i in read.items] == [0, 0, 0, 1, 1, 2]


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
    ]
    read, _, _ = _read(tmp_path, items)
    assert read.drops == {}
    assert [i.kind for i in read.items if isinstance(i, SeenLabel)] == [
        "printed",
        "printed",
        "handwritten",
        "printed",
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
    assert sent["prompt_version"] == LABEL_BINDING_PROMPT_VERSION == "1"
    assert sent["system_prompt"] == LABEL_BINDING_SYSTEM_PROMPT
    assert sent["user_prompt"] == build_label_binding_user_prompt(scheme, page_count=3)
    assert sent["image_parts"] == [b"page-0", b"page-1", b"page-2"]
    assert sent["image_uploads"] is not None
    assert sent["media_resolution"] == "high"
    assert sent["extra_cache_key"] == "scan-1"
    assert genai.models.generate_content.call_count == 1


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
        out[run] = (read, to_bound_read(bound, page_count=record["page_count"]))
    return out


@pytest.mark.parametrize("run", _RUNS)
def test_recorded_streams_convert_to_the_expected_answers(
    recorded: dict[int, tuple[StreamRead, BoundRead]], run: int
) -> None:
    read, bound_read = recorded[run]
    answers = {a.question_id: a for a in bound_read.answers}

    assert read.drops == {}, "a recorded item was dropped"
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
        2: ["2c"],
        3: ["4b_i", "6b", "7b_i", "8d"],
        4: ["3c", "4b_i"],
        5: ["3c", "4b_i"],
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
    assert bound_read.review_ids == ["3c", "4b_i"]


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
    (answer,) = to_bound_read(bound, page_count=2).answers

    assert answer.question_id == "1a"
    assert answer.answer == "first line; second line; third line"
    assert answer.working_out == "F = m a\n= 2.0 x 3.0"
    assert answer.confidence == 0.6
    assert answer.binding_source == "label"
    assert answer.binding_status == "verified"
    assert answer.label_seen == "(a)"


def test_one_writing_is_carried_over_unchanged() -> None:
    bound = _bound(_leaf("1a", _writing("1. copper\n2. zinc", confidence=0.85)))
    (answer,) = to_bound_read(bound, page_count=2).answers
    assert answer.answer == "1. copper\n2. zinc"
    assert answer.working_out is None
    assert answer.confidence == 0.85


def test_a_writing_with_no_answer_text_adds_only_its_working() -> None:
    bound = _bound(_leaf("1a", _writing("", working_out="V = I R"), _writing("12 V")))
    (answer,) = to_bound_read(bound, page_count=2).answers
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
    bound_read = to_bound_read(bound, page_count=2)

    assert [(a.question_id, a.binding_status) for a in bound_read.answers] == [
        ("1a", "verified"),
        ("1b", "unverified"),
        ("1c", "verified"),
        ("2a", "unverified"),
    ]
    assert bound_read.review_ids == ["1b", "2a"]


def test_an_inferred_number_alone_leaves_a_hand_built_leaf_verified() -> None:
    bound = _bound(_leaf("4a", _writing("x"), doubts=(DOUBT_NUMBER_NOT_SEEN,)))
    bound_read = to_bound_read(bound, page_count=2)
    assert [a.binding_status for a in bound_read.answers] == ["verified"]
    assert bound_read.review_ids == []


def test_a_doubt_of_neither_class_makes_a_leaf_unverified() -> None:
    """A doubt this module has not been told about must not pass as verified."""
    bound = _bound(_leaf("1a", _writing("x"), doubts=("a doubt added later",)))
    bound_read = to_bound_read(bound, page_count=2)
    assert [a.binding_status for a in bound_read.answers] == ["unverified"]
    assert bound_read.review_ids == ["1a"]


def test_the_two_doubt_classes_cover_every_doubt_the_binding_can_raise() -> None:
    """The conversion reads the classes from ``label_sequence``; this pins what it relies on."""
    assert set(CONTENT_DOUBTS) == {DOUBT_PREVIOUS_PAGE, DOUBT_ARROW, DOUBT_NEXT_NUMBER_NOT_SEEN}
    assert set(INFERENCE_DOUBTS) == {DOUBT_NUMBER_NOT_SEEN}
    assert set(DOUBTS) == set(CONTENT_DOUBTS) | set(INFERENCE_DOUBTS)
    assert not set(CONTENT_DOUBTS) & set(INFERENCE_DOUBTS)


def test_blank_aligned_leaf_produces_no_answer() -> None:
    bound = _bound(
        _leaf("1a", _writing("x")),
        _leaf("1b"),
        _leaf("1c", doubts=(DOUBT_NEXT_NUMBER_NOT_SEEN,)),
        _leaf("2a", _writing("y")),
    )
    bound_read = to_bound_read(bound, page_count=2)
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
    boxes = {a.question_id: a.source_box for a in to_bound_read(bound, page_count=3).answers}

    assert boxes == {
        "1a": SourceBox(page=1, box=[100, 150, 220, 600]),
        "1b": None,
        "1c": SourceBox(page=1, box=[400, 100, 450, 600]),
        "1d": None,
        "1e": None,
        "1f": None,
        "1g": None,
    }


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
    bound_read = to_bound_read(bound, page_count=2)

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
    assert [a.question_id for a in to_bound_read(bound, page_count=2).answers] == [
        "9c_iv",
        "7a_ii_a",
        "3ii",
    ]
