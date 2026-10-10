"""Extraction binds answers by labels, checks the binding, and reports how far to trust it.

``lemely.io.binding.orchestrate.run_binding`` reads the script (twice, by default), binds
each read with ``bind_stream``, runs the gate checks, and chooses a read or holds the
paper. ``GeminiAnswerExtractor`` puts the outcome on the ``ExtractedAnswers`` it returns.

The model is a fake throughout. Where a realistic reply is needed it is one of the five
recorded replies under ``tests/fixtures/binding/0625_w24_41/streams/``.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import structlog
from PIL import Image

from lemely.core.binding import SeenWriting
from lemely.core.label_sequence import bind_stream
from lemely.core.loose_schemas import MarkScheme, Question
from lemely.core.schemas import AIMarkResponse, ConfidenceBand, ExtractedAnswers
from lemely.io import correction_ai
from lemely.io.answer_extraction import GeminiAnswerExtractor
from lemely.io.binding import parse_stream_items, to_bound_read
from lemely.io.binding.orchestrate import LOST_ITEM_REASONS, BindingOutcome, run_binding
from lemely.io.correction_ai import correct_paper
from lemely.io.gemini import GeminiClient
from lemely.io.rasterise import RasterisedPage
from lemely.runtime.config import BindingSettings, PathsSettings, Settings, load_settings
from lemely.runtime.errors import CostCeilingError, ExternalServiceError, ParseError
from lemely.runtime.events import EventType, bus
from tests.gemini_fakes import fake_genai_client

_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES = _ROOT / "tests" / "fixtures" / "binding" / "0625_w24_41"
_PAGE_COUNT = 19
_READ_MODEL = "gemini-3.8-flash"


# --------------------------------------------------------------------------------------
# Fixtures and fakes
# --------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def scheme() -> MarkScheme:
    path = _ROOT / "corpus" / "mark-schemes" / "0625_w24_ms_41.json"
    return MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _run(number: int) -> list[Any]:
    """The items of recorded reply ``number``, exactly as the model returned them."""
    path = _FIXTURES / "streams" / f"A_run{number}.json"
    items: list[Any] = json.loads(path.read_text(encoding="utf-8"))["items"]
    return items


def _without_label(items: list[Any], text: str, page: int) -> list[Any]:
    """``items`` without the first label ``text`` on ``page``: a label the reader missed."""
    out: list[Any] = []
    removed = False
    for item in items:
        if (
            not removed
            and item.get("type") == "label"
            and item.get("text") == text
            and item.get("page") == page
        ):
            removed = True
            continue
        out.append(item)
    assert removed, f"no label {text!r} on page {page}"
    return out


def _question_4_unanchored(number: int) -> list[Any]:
    """Recorded reply 4 or 5, which lack the label ``4``, with question 4's ``(b)`` gone too.

    With ``(b)`` there, ``bind_stream`` infers the missing ``4`` from the parts around it.
    Without it nothing anchors question 4: its four leaves and ``3c`` (whose writing can
    no longer be told from question 4's) come out unaligned, five of 43.
    """
    return _without_label(_run(number), "(b)", 8)


def _prose_answers(items: list[Any]) -> list[int]:
    """Indexes of answer items holding a sentence with no digit in it, placed by position."""
    return [
        index
        for index, item in enumerate(items)
        if item.get("type") == "answer"
        and len(item.get("answer") or "") >= 30
        and not any(ch.isdigit() for ch in item["answer"])
        and item.get("placed_by") == "position"
    ]


def _with_texts_rotated(items: list[Any], count: int) -> list[Any]:
    """``items`` with the text of ``count`` prose answers each moved to the next of them.

    Every label stays where it is, so the list binds exactly as before; ``count`` leaves
    simply hold another leaf's sentence. That is what a second read looks like when it
    disagrees with the first about where answers belong.
    """
    chosen = _prose_answers(items)[2 : 2 + count]
    assert len(chosen) == count
    out = copy.deepcopy(items)
    for position, index in enumerate(chosen):
        source = items[chosen[(position + 1) % count]]
        out[index]["answer"] = source["answer"]
        out[index]["working_out"] = source.get("working_out")
    return out


def _listed_before_labels(items: list[Any]) -> list[Any]:
    """Recorded reply 1 with the writing of ``1(c)`` and ``9(c)`` listed before its label.

    In both groups each part's block now precedes that part's label: the first block
    falls straight after the ``(c)`` label and the last part is left with nothing.
    """
    out = list(items)
    for label_at in (10, 12, 102, 104, 106, 108):
        assert out[label_at]["type"] == "label" and out[label_at + 1]["type"] == "answer"
        out[label_at], out[label_at + 1] = out[label_at + 1], out[label_at]
    return out


def _legacy_reply(fixture: str) -> dict[str, Any]:
    """A recorded legacy extraction as the reply the legacy extractor is given."""
    recorded = json.loads((_FIXTURES / f"{fixture}.json").read_text(encoding="utf-8"))
    return {
        "answers": [
            {
                "question_id": answer["question_id"],
                "answer": answer["answer"],
                "confidence": answer["confidence"],
                "source_region": answer.get("source_region"),
                "source_box": answer.get("source_box"),
                "working_out": answer.get("working_out"),
            }
            for answer in recorded["answers"]
        ]
    }


class _IsolatedEnv:
    def __enter__(self) -> _IsolatedEnv:
        self._snap = dict(os.environ)
        for key in list(os.environ):
            if key.startswith("LEMELY_"):
                del os.environ[key]
        return self

    def __exit__(self, *_: object) -> None:
        os.environ.clear()
        os.environ.update(self._snap)


def _settings(tmp: Path, **binding: Any) -> Settings:
    with _IsolatedEnv():
        settings = load_settings(toml_path=None, cwd=tmp)
    return settings.model_copy(
        update={
            "paths": PathsSettings(cache_dir=tmp / ".cache", output_dir=tmp / "outputs"),
            "binding": BindingSettings(**binding),
        }
    )


def _client(tmp: Path, **binding: Any) -> tuple[GeminiClient, MagicMock]:
    """A real ``GeminiClient`` over a fake SDK client, with ``binding`` settings."""
    genai = fake_genai_client()
    return GeminiClient(_settings(tmp, **binding), _genai_client=genai), genai


class _Model:
    """Stands in for ``GeminiClient.generate_structured``.

    ``replies`` is keyed by which call it is: ``"first"`` and ``"second"`` for the label
    binder's two reads, ``"legacy"`` and ``"retry"`` for the legacy extractor's call and
    its repeat. A reply is the body the model returned, or an exception to raise, or a
    list of those to be given one per call of that kind. The two reads run on separate
    threads, so the key comes from the call and not its order.
    """

    def __init__(self, **replies: Any) -> None:
        self.replies = replies
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    @staticmethod
    def key(kwargs: dict[str, Any]) -> str:
        if kwargs["response_schema"].__name__ == "_ExtractorOutput":
            return "retry" if kwargs.get("model") else "legacy"
        return "second" if kwargs.get("task_tag") == "binding_second_read" else "first"

    def __call__(self, **kwargs: Any) -> Any:
        with self._lock:
            self.calls.append(kwargs)
            reply = self.replies[self.key(kwargs)]
            if isinstance(reply, list):
                reply = reply.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return kwargs["response_schema"].model_validate(reply)

    def made(self) -> list[str]:
        return sorted(self.key(call) for call in self.calls)

    def call(self, key: str) -> dict[str, Any]:
        (found,) = [call for call in self.calls if self.key(call) == key]
        return found


def _items(items: list[Any]) -> dict[str, Any]:
    return {"items": items}


def _pages(count: int = _PAGE_COUNT) -> list[RasterisedPage]:
    return [
        RasterisedPage(index=i, width=10, height=14, png_bytes=f"page-{i}".encode(), dpi=72.0)
        for i in range(count)
    ]


@contextmanager
def _events(*types: EventType) -> Iterator[dict[EventType, list[dict[str, Any]]]]:
    """Every payload published for ``types`` while the block runs."""
    seen: dict[EventType, list[dict[str, Any]]] = {t: [] for t in types}
    callbacks = {t: (lambda t=t, **payload: seen[t].append(payload)) for t in types}
    for event_type, callback in callbacks.items():
        bus.subscribe(event_type, callback)
    try:
        yield seen
    finally:
        for event_type, callback in callbacks.items():
            bus.unsubscribe(event_type, callback)


def _bind(tmp: Path, scheme: MarkScheme, model: _Model, **binding: Any) -> BindingOutcome:
    """``run_binding`` on a 19-page script with ``model`` answering every call."""
    client, _genai = _client(tmp, **binding)
    pages = _pages()
    with (
        client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
        patch.object(client, "generate_structured", side_effect=model),
    ):
        return run_binding(
            client,
            pages,
            scheme,
            uploads=uploads,
            settings=client._settings,
            manifest_key="scan-1",
        )


@pytest.fixture
def scan(tmp_path: Path) -> Path:
    """A real 19-page PDF: the recorded replies name pages 0 to 18."""
    path = tmp_path / "scan.pdf"
    images = [Image.new("RGB", (100, 140), color="white") for _ in range(_PAGE_COUNT)]
    images[0].save(path, "PDF", save_all=True, append_images=images[1:])
    return path


def _extract(
    tmp: Path, scan: Path, scheme: MarkScheme, model: _Model, **binding: Any
) -> ExtractedAnswers:
    """The whole extraction, crop re-reads off, with ``model`` answering every call."""
    client, _genai = _client(tmp, **binding)
    with patch.object(client, "generate_structured", side_effect=model):
        return GeminiAnswerExtractor(client, max_rereads_per_paper=0)(
            scan_path=scan, mark_scheme=scheme
        )


def _bound_alone(items: list[Any], scheme: MarkScheme) -> list[tuple[str, str]]:
    """``(question id, answer)`` for ``items`` bound with no orchestration around it."""
    stream = parse_stream_items(items, page_count=_PAGE_COUNT)
    read = to_bound_read(
        bind_stream(stream.items, scheme), page_count=_PAGE_COUNT, drops=stream.drops
    )
    return [(a.question_id, a.answer) for a in read.answers]


def _pairs(outcome: BindingOutcome | ExtractedAnswers) -> list[tuple[str, str]]:
    return [(a.question_id, a.answer) for a in outcome.answers]


def _failed(outcome: BindingOutcome) -> list[tuple[str, str]]:
    assert outcome.report is not None
    return [(c.id, c.scope) for c in outcome.report.checks if not c.passed]


# --------------------------------------------------------------------------------------
# The two reads
# --------------------------------------------------------------------------------------
def test_clean_first_read_passes_and_carries_a_report(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    model = _Model(first=_items(_run(1)), second=_items(_run(2)))
    extracted = _extract(tmp_path, scan, scheme, model)

    assert model.made() == ["first", "second"]  # the legacy extraction call is not made
    report = extracted.binding
    assert report is not None
    assert (report.binder, report.verdict, report.retried) == ("label", "pass", False)
    assert report.model == _READ_MODEL
    assert [c.id for c in report.checks] == ["G1", "G2", "G5", "G6", "G7", "G9"]
    assert all(c.passed for c in report.checks)

    # The answers are the first read's, each on the question the reference has it on.
    assert _pairs(extracted) == _bound_alone(_run(1), scheme)
    reference = json.loads((_FIXTURES / "aligned.json").read_text(encoding="utf-8"))
    assert {a.question_id for a in extracted.answers} == {
        a["question_id"] for a in reference["answers"]
    }
    assert len(extracted.answers) == 42
    assert all(a.binding_source == "label" for a in extracted.answers)
    assert all(a.label_seen for a in extracted.answers)
    assert extracted.dropped_question_ids == []
    assert extracted.unbound_question_ids == []


def test_binder_calls_use_the_configured_read_model_not_the_extraction_default(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    assert BindingSettings().read_model == _READ_MODEL
    model = _Model(first=_items(_run(1)), second=_items(_run(1)))
    outcome = _bind(tmp_path, scheme, model, read_model="gemini-read-under-test")

    extraction_default = _settings(tmp_path).gemini.model_for("extraction")
    assert extraction_default != "gemini-read-under-test"
    assert [call["model"] for call in model.calls] == ["gemini-read-under-test"] * 2
    assert outcome.report is not None
    assert outcome.report.model == "gemini-read-under-test"


def test_second_read_uses_its_own_task_tag_and_cache_key(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    client, genai = _client(tmp_path)
    genai.models.generate_content.return_value = MagicMock(
        text=json.dumps(_items(_run(1))),
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(prompt_token_count=5, candidates_token_count=30),
    )
    pages = _pages()
    with (
        client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
        patch.object(client, "generate_structured", wraps=client.generate_structured) as spy,
    ):
        outcome = run_binding(
            client, pages, scheme, uploads=uploads, settings=client._settings, manifest_key="k"
        )

    calls = {call.kwargs["task_tag"]: call.kwargs for call in spy.call_args_list}
    assert sorted(calls) == ["binding_second_read", "extraction"]
    assert calls["extraction"]["extra_cache_key"] == "k|bind1"
    assert calls["binding_second_read"]["extra_cache_key"] == "k|bind2"
    assert calls["extraction"]["model"] == calls["binding_second_read"]["model"] == _READ_MODEL
    assert all(call["image_uploads"] is uploads for call in calls.values())

    # Same model, different thinking level: the second read is not the first one again.
    assert client._settings.gemini.thinking_level_for["binding_second_read"] == "medium"
    assert client.resolved_thinking("extraction", _READ_MODEL) == "low"
    assert client.resolved_thinking("binding_second_read", _READ_MODEL) == "medium"
    # Two paid calls (neither served from the other's cache entry), one upload of the pages.
    assert genai.models.generate_content.call_count == 2
    assert len(genai.files.uploads) == _PAGE_COUNT
    assert outcome.report is not None and outcome.report.verdict == "pass"


def test_the_two_reads_are_in_flight_together(tmp_path: Path, scheme: MarkScheme) -> None:
    # Each read waits inside its call for the other to arrive. Run one after the other,
    # the first would wait alone until the barrier gave up.
    together = threading.Barrier(2, timeout=10)
    model = _Model(first=_items(_run(1)), second=_items(_run(2)))

    def both_must_arrive(**kwargs: Any) -> Any:
        together.wait()
        return model(**kwargs)

    client, _genai = _client(tmp_path)
    pages = _pages()
    with (
        client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
        patch.object(client, "generate_structured", side_effect=both_must_arrive),
    ):
        outcome = run_binding(
            client, pages, scheme, uploads=uploads, settings=client._settings, manifest_key="k"
        )
    assert model.made() == ["first", "second"]
    assert outcome.report is not None and outcome.report.verdict == "pass"


def test_second_read_can_be_switched_off(tmp_path: Path, scheme: MarkScheme) -> None:
    model = _Model(first=_items(_run(1)))
    outcome = _bind(tmp_path, scheme, model, second_read=False)
    assert model.made() == ["first"]
    assert outcome.report is not None
    assert [c.id for c in outcome.report.checks] == ["G1", "G2", "G5", "G6", "G7"]
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", False)


def test_first_read_missing_a_question_number_and_complete_second_read_uses_the_second(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    first = _question_4_unanchored(4)
    model = _Model(first=_items(first), second=_items(_run(1)))
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        outcome = _bind(tmp_path, scheme, model)

    assert outcome.report is not None
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", True)
    assert _pairs(outcome) == _bound_alone(_run(1), scheme)
    assert len(outcome.answers) == 42
    assert outcome.review_only_ids == []
    # Everything that goes on is the second read's, its unbound writing included.
    second_alone = _bind(tmp_path, scheme, _Model(first=_items(_run(1))), second_read=False)
    first_alone = _bind(tmp_path, scheme, _Model(first=_items(first)), second_read=False)
    assert outcome.unbound == second_alone.unbound
    assert outcome.unbound != first_alone.unbound
    assert outcome.drops == second_alone.drops
    # The report is about the read that was used: the second read's checks, and G9.
    assert _failed(outcome) == []
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert (event["verdict"], event["retried"], event["second_read"]) == ("pass", True, True)
    # The report is the second read's and is clean; why the first was set aside is
    # recorded beside it.
    assert event["failed_checks"] == []
    (set_aside,) = event["first_read_failed_checks"]
    assert (set_aside["id"], set_aside["scope"], set_aside["passed"]) == ("G5", "paper", False)
    assert set_aside["question_ids"] == ["3c", "4a", "4b_i", "4b_ii", "4b_iii"]

    # Alone, the first read is a paper nobody should publish: five leaves have no label.
    alone = _bind(tmp_path, scheme, _Model(first=_items(first)), second_read=False)
    assert alone.review_only_ids == ["3c", "4a", "4b_i", "4b_ii", "4b_iii"]
    assert _failed(alone) == [("G5", "paper")]
    assert alone.report is not None
    assert (alone.report.verdict, alone.report.retried) == ("hold", False)


def _without_items(items: list[Any], *indexes: int) -> list[Any]:
    """``items`` without the blocks at ``indexes``: writing this read did not report."""
    for index in indexes:
        assert items[index]["type"] == "answer"
    return [item for index, item in enumerate(items) if index not in indexes]


def _blocks_under(items: list[Any], text: str, page: int) -> list[int]:
    """Indexes of the writing listed after the label ``text`` on ``page``, up to the next label."""
    start = next(
        index
        for index, item in enumerate(items)
        if item.get("type") == "label" and item.get("text") == text and item.get("page") == page
    )
    found: list[int] = []
    for index in range(start + 1, len(items)):
        if items[index].get("type") == "label":
            break
        found.append(index)
    assert found, f"nothing is listed under {text!r} on page {page}"
    return found


@pytest.mark.parametrize("returned", ["the read that saw the label", "the read that missed it"])
def test_a_leaf_blank_in_one_read_and_unbound_in_the_other_goes_to_review(
    tmp_path: Path, scan: Path, scheme: MarkScheme, returned: str
) -> None:
    # Two different misses on 4(b)(i). One read lists its label and reports nothing
    # under it. The other reports the writing and misses the label, so it can bind the
    # writing to no leaf. Neither read has an answer for it, and it is not a blank.
    base = _run(4)
    label_seen_nothing_under = _without_items(base, *_blocks_under(base, "(i)", 9))
    writing_seen_label_missed = _without_label(base, "(i)", 9)
    reads = [label_seen_nothing_under, writing_seen_label_missed]
    if returned == "the read that missed it":
        reads.reverse()
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        extracted = _extract(
            tmp_path, scan, scheme, _Model(first=_items(reads[0]), second=_items(reads[1]))
        )

    report = extracted.binding
    assert report is not None and (report.verdict, report.retried) == ("pass", False)
    assert "4b_i" not in {a.question_id for a in extracted.answers}
    assert extracted.unbound_question_ids == ["4b_i"]
    # Why it was sent is on the report: G9 names it, whichever read is the one used.
    g9 = report.checks[-1]
    assert (g9.id, g9.passed, g9.scope) == ("G9", False, "question")
    assert "4b_i" in g9.question_ids
    assert "no writing in one reading of the scan and no label lined up in the other" in g9.detail
    # What the student wrote there is kept, as writing with no question.
    assert any("thermal" in w.answer for w in extracted.unbound_answers)
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert event["unaligned"] == 1 and event["unbound"] == len(extracted.unbound_answers)

    marker = _Marker()
    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=marker
    ):
        result = correct_paper(scheme, extracted, gemini_client=MagicMock())
    row = next(q for q in result.questions if q.question_id == "4b_i")
    assert row.marker_source == "dropped" and row.needs_teacher_review  # not "blank"
    assert "4b_i" not in marker.asked


def test_an_answer_whose_label_the_other_read_missed_stays_as_bound(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The read that is used has 5(a) answered under its label. The other read missed
    # that label: it could bind nothing to 5(a), which says nothing against the answer.
    second = _without_label(_run(1), "(a)", 10)
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        outcome = _bind(tmp_path, scheme, _Model(first=_items(_run(1)), second=_items(second)))
    alone = _bind(tmp_path, scheme, _Model(first=_items(_run(1))), second_read=False)
    assert outcome.report.verdict == "pass" and outcome.report.checks[-1].passed
    assert outcome.answers == alone.answers
    assert next(a for a in outcome.answers if a.question_id == "5a").binding_status == "verified"
    assert outcome.review_only_ids == [] and outcome.unbound == alone.unbound
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert (event["unaligned"], event["failed_checks"]) == (0, [])


def test_a_leaf_only_the_other_read_answered_goes_to_review_never_blank(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # The first read did not report the block under 5(a) ("0.2 m"); the second did. The
    # first read passes its own checks and is the one used, and in it 5(a) is a label
    # with nothing after it: a blank. It is not one.
    first = _without_items(_run(1), 53)
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        extracted = _extract(
            tmp_path, scan, scheme, _Model(first=_items(first), second=_items(_run(1)))
        )
    report = extracted.binding
    assert report is not None
    assert (report.verdict, report.retried) == ("pass", False)
    # The event counts the leaves sent to a teacher, not only those with no label, and
    # the writing kept with no question, the other read's block included.
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert (event["unaligned"], event["unbound"]) == (1, 4)
    g9 = report.checks[-1]
    assert (g9.id, g9.passed, g9.scope, g9.question_ids) == ("G9", False, "question", ["5a"])
    assert "answered in one reading of the scan and left blank in the other: 5a" in g9.detail
    assert "5a" not in {a.question_id for a in extracted.answers}
    assert extracted.unbound_question_ids == ["5a"]
    # What the other read saw there is kept, as writing with no question.
    assert "0.2 m" in [w.answer for w in extracted.unbound_answers]

    marker = _Marker()
    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=marker
    ):
        result = correct_paper(scheme, extracted, gemini_client=MagicMock())
    row = next(q for q in result.questions if q.question_id == "5a")
    assert row.marker_source == "dropped" and row.needs_teacher_review  # not "blank"
    assert "5a" not in marker.asked


def test_a_leaf_only_the_returned_read_answered_is_kept_and_doubted(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # The mirror: the read that is used has "0.2 m" under 5(a), the other saw nothing.
    second = _without_items(_run(1), 53)
    extracted = _extract(
        tmp_path, scan, scheme, _Model(first=_items(_run(1)), second=_items(second))
    )
    assert extracted.binding is not None and extracted.binding.verdict == "pass"
    answer = next(a for a in extracted.answers if a.question_id == "5a")
    assert (answer.answer, answer.binding_status) == ("0.2 m", "unverified")
    assert extracted.unbound_question_ids == []
    assert _pairs(extracted) == _bound_alone(_run(1), scheme)

    marker = _Marker()
    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=marker
    ):
        result = correct_paper(scheme, extracted, gemini_client=MagicMock())
    row = next(q for q in result.questions if q.question_id == "5a")
    assert "5a" in marker.asked and row.awarded_marks == row.maximum_marks  # marked, marks kept
    assert row.needs_teacher_review
    assert "may include writing that belongs to another question" in (row.review_reason or "")


def test_too_many_leaves_answered_in_one_read_only_hold_the_paper(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # Five single-block leaves of 42 answered (11.9%) are above the 10% limit; four
    # (9.5%) are not.
    five = _without_items(_run(1), 8, 18, 22, 29, 53)
    held = _bind(tmp_path, scheme, _Model(first=_items(_run(1)), second=_items(five)))
    assert held.report is not None
    assert (held.report.verdict, held.report.retried) == ("hold", True)
    assert _failed(held) == [("G9", "paper")]
    assert held.report.checks[-1].question_ids == ["1b", "2a_i", "2a_iii", "2c", "5a"]
    # Held or not, the five are not trusted where they are.
    status = {a.question_id: a.binding_status for a in held.answers}
    assert all(status[qid] == "unverified" for qid in ("1b", "2a_i", "2a_iii", "2c", "5a"))

    # The same five with the reads the other way round: the read that is returned has
    # nothing under them. Held as the paper is, none of the five is left as a blank, and
    # what the other read saw under each is kept.
    mirror = _bind(tmp_path, scheme, _Model(first=_items(five), second=_items(_run(1))))
    assert (mirror.report.verdict, _failed(mirror)) == ("hold", [("G9", "paper")])
    assert mirror.review_only_ids == ["1b", "2a_i", "2a_iii", "2c", "5a"]
    kept = [w.answer for w in mirror.unbound]
    assert all(_run(1)[index]["answer"] in kept for index in (8, 18, 22, 29, 53))

    four = _without_items(_run(1), 8, 18, 22, 29)
    passed = _bind(tmp_path, scheme, _Model(first=_items(_run(1)), second=_items(four)))
    assert passed.report is not None and passed.report.verdict == "pass"
    assert _failed(passed) == [("G9", "question")]


def test_identical_reads_change_nothing(tmp_path: Path, scheme: MarkScheme) -> None:
    alone = _bind(tmp_path, scheme, _Model(first=_items(_run(1))), second_read=False)
    both = _bind(tmp_path, scheme, _Model(first=_items(_run(1)), second=_items(_run(1))))
    assert both.report is not None and all(c.passed for c in both.report.checks)
    assert both.answers == alone.answers
    assert both.unbound == alone.unbound
    assert both.review_only_ids == alone.review_only_ids == []


def test_reads_that_disagree_at_paper_scope_hold(tmp_path: Path, scheme: MarkScheme) -> None:
    second = _with_texts_rotated(_run(1), 6)
    # Each read is clean taken alone: only setting them side by side shows the problem.
    for items in (_run(1), second):
        alone = _bind(tmp_path, scheme, _Model(first=_items(items)), second_read=False)
        assert alone.report is not None and alone.report.verdict == "pass"

    outcome = _bind(tmp_path, scheme, _Model(first=_items(_run(1)), second=_items(second)))
    assert outcome.report is not None
    assert (outcome.report.verdict, outcome.report.retried) == ("hold", True)
    assert _failed(outcome) == [("G9", "paper")]
    assert len(outcome.report.checks[-1].question_ids) == 6
    assert _pairs(outcome) == _bound_alone(_run(1), scheme)  # the first read's answers
    # The paper is held as a whole; the six answers are not singled out on top of that.
    alone = _bind(tmp_path, scheme, _Model(first=_items(_run(1))), second_read=False)
    assert outcome.answers == alone.answers


def test_two_bad_reads_hold(tmp_path: Path, scheme: MarkScheme) -> None:
    first, second = _question_4_unanchored(4), _question_4_unanchored(5)
    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(second)))

    assert outcome.report is not None
    assert (outcome.report.verdict, outcome.report.retried) == ("hold", True)
    assert _failed(outcome) == [("G5", "paper")]
    assert [c.id for c in outcome.report.checks][-1] == "G9"
    assert _pairs(outcome) == _bound_alone(first, scheme)
    assert outcome.review_only_ids == ["3c", "4a", "4b_i", "4b_ii", "4b_iii"]


def test_question_scope_doubts_are_marked_on_a_held_paper_too(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # Both reads fail at paper scope (question 4 unanchored), and the second also holds
    # two sentences under each other's leaf: a hold, with what G9 names doubted.
    first = _question_4_unanchored(4)
    second = _with_texts_rotated(_question_4_unanchored(5), 2)
    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(second)))
    assert outcome.report.verdict == "hold"
    g9 = outcome.report.checks[-1]
    assert (g9.id, g9.passed, g9.scope) == ("G9", False, "question")
    assert g9.question_ids  # at least one of the two moved sentences is under an aligned leaf
    status = {a.question_id: a.binding_status for a in outcome.answers}
    assert all(status[qid] == "unverified" for qid in g9.question_ids)
    # The paper-scope check's own ids are the leaves with no label: they have no answer
    # to mark, and no other answer is doubted for the paper's being held.
    alone = _bind(tmp_path, scheme, _Model(first=_items(first)), second_read=False)
    doubted_alone = {a.question_id for a in alone.answers if a.binding_status == "unverified"}
    doubted = {qid for qid, s in status.items() if s == "unverified"}
    assert doubted == doubted_alone | set(g9.question_ids)


def test_a_second_read_that_fails_once_is_read_again(tmp_path: Path, scheme: MarkScheme) -> None:
    model = _Model(
        first=_items(_run(1)),
        second=[ExternalServiceError("503 from the service"), _items(_run(2))],
    )
    with _events(EventType.SECOND_READ_FAILED, EventType.BINDING_GATE_RESULT) as seen:
        outcome = _bind(tmp_path, scheme, model)

    assert model.made() == ["first", "second", "second"]
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", False)
    # The two reads were compared after all: the paper did not go on with one.
    assert [c.id for c in outcome.report.checks] == ["G1", "G2", "G5", "G6", "G7", "G9"]
    (failure,) = seen[EventType.SECOND_READ_FAILED]
    assert failure["error"] == "503 from the service"
    assert failure["error_type"] == "ExternalServiceError"
    assert failure["stage"] == "binding_second_read"
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert event["second_read"] is True


@pytest.mark.parametrize(
    "failure",
    [ExternalServiceError("503 from the service"), ParseError("the reply did not parse")],
    ids=["service error", "parse error"],
)
def test_a_second_read_that_fails_twice_fails_the_job(
    tmp_path: Path, scheme: MarkScheme, failure: Exception
) -> None:
    # Was `test_failed_second_read_does_not_fail_the_paper`, which pinned the opposite:
    # the paper went on with the first read alone. On one read a block the reader missed
    # is a blank, and a blank is an unflagged zero; with the second read asked for, a
    # paper is never published on one.
    again = type(failure)("and again")
    model = _Model(first=_items(_without_items(_run(1), 53)), second=[failure, again])
    with (
        _events(EventType.SECOND_READ_FAILED, EventType.BINDING_GATE_RESULT) as seen,
        pytest.raises(type(failure)) as raised,
    ):
        _bind(tmp_path, scheme, model)
    # The job fails as it does when the first read fails: with the service's own error,
    # not with a verdict. Nothing is known about the binding.
    assert raised.value is again
    assert model.made() == ["first", "second", "second"]
    assert seen[EventType.BINDING_GATE_RESULT] == []
    assert len(seen[EventType.SECOND_READ_FAILED]) == 1  # the first failure; the second is raised


def test_with_the_second_read_switched_off_one_read_is_used_as_before(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    model = _Model(first=_items(_run(1)))  # a second read would find no reply and fail
    outcome = _bind(tmp_path, scheme, model, second_read=False)
    assert model.made() == ["first"]
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", False)
    held = _bind(
        tmp_path, scheme, _Model(first=_items(_question_4_unanchored(4))), second_read=False
    )
    assert (held.report.verdict, held.report.retried) == ("hold", False)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("ceiling", "reply"),
        ("reply", "ceiling"),
        ("ceiling", "ceiling"),
        # The ceiling stops the run whatever else went wrong beside it.
        ("service error", "ceiling"),
        # And when it is reached on the second attempt at the second read.
        ("reply", "service error, then ceiling"),
    ],
)
def test_cost_ceiling_in_either_read_propagates(
    tmp_path: Path, scheme: MarkScheme, first: str, second: str
) -> None:
    ceiling = CostCeilingError("USD ceiling reached")
    replies: dict[str, Any] = {
        "ceiling": ceiling,
        "reply": _items(_run(1)),
        "service error": ExternalServiceError("503"),
        "service error, then ceiling": [ExternalServiceError("503"), ceiling],
    }
    model = _Model(first=replies[first], second=replies[second])
    with (
        _events(EventType.SECOND_READ_FAILED, EventType.BINDING_GATE_RESULT) as seen,
        pytest.raises(CostCeilingError) as raised,
    ):
        _bind(tmp_path, scheme, model)
    assert raised.value is ceiling  # unchanged, not wrapped
    # A breach is not a failed second read: only the service error before it is one.
    assert len(seen[EventType.SECOND_READ_FAILED]) == (1 if "then" in second else 0)
    assert seen[EventType.BINDING_GATE_RESULT] == []


def test_a_second_read_that_crashes_twice_fails_the_job_with_a_fixed_sentence(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # Was `test_a_second_read_that_crashes_does_not_fail_a_good_paper`: a bug in reading
    # or binding the second reply let the paper out on the first read alone. It is tried
    # once more, and then the job fails. What reaches the student's stream is a fixed
    # sentence: the text of an arbitrary exception is internal.
    crash, again = RuntimeError("a bug in the second read"), RuntimeError("the same bug")
    model = _Model(first=_items(_run(1)), second=[crash, again])
    with (
        _events(EventType.SECOND_READ_FAILED, EventType.BINDING_GATE_RESULT) as seen,
        structlog.testing.capture_logs() as logs,
        pytest.raises(ExternalServiceError) as raised,
    ):
        _bind(tmp_path, scheme, model)
    assert str(raised.value) == "the second read of the script failed unexpectedly"
    assert raised.value.__cause__ is again  # the crash itself is kept for the server
    assert "bug" not in str(raised.value)
    assert seen[EventType.BINDING_GATE_RESULT] == []
    (failure,) = seen[EventType.SECOND_READ_FAILED]
    assert failure["error_type"] == "RuntimeError"
    assert failure["stage"] == "binding_second_read"
    assert failure["error"] == "the second read of the script failed unexpectedly"
    assert "a bug in the second read" not in str(failure)
    # Both crashes are logged with their tracebacks.
    logged = [entry for entry in logs if entry["event"] == "binding_second_read_crashed"]
    assert [entry["exc_info"] for entry in logged] == [crash, again]
    assert all(entry["log_level"] == "error" for entry in logged)

    # A crash that does not come back on the second attempt costs nothing.
    model = _Model(first=_items(_run(1)), second=[RuntimeError("once"), _items(_run(1))])
    outcome = _bind(tmp_path, scheme, model)
    assert outcome.report.verdict == "pass" and outcome.report.checks[-1].id == "G9"

    # A crash in the first read is still a crash: there is no paper without it.
    crash = RuntimeError("a bug in the first read")
    with pytest.raises(RuntimeError) as raised_first:
        _bind(tmp_path, scheme, _Model(first=crash, second=_items(_run(1))))
    assert raised_first.value is crash


def test_an_interrupt_during_the_second_read_is_not_swallowed(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    model = _Model(first=_items(_run(1)), second=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        _bind(tmp_path, scheme, model)


def test_a_failed_first_read_fails_the_paper_as_extraction_always_has(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    error = ExternalServiceError("503")
    with pytest.raises(ExternalServiceError) as raised:
        _bind(tmp_path, scheme, _Model(first=error, second=_items(_run(1))))
    assert raised.value is error


# --------------------------------------------------------------------------------------
# Nothing is lost
# --------------------------------------------------------------------------------------
class _Marker:
    """Stands in for ``AICorrector.mark_question``: full marks, and a note of who was asked."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def __call__(self, _self: object, question: Question, *_a: object, **_k: object) -> Any:
        self.asked.append(question.id)
        return AIMarkResponse.model_validate(
            {
                "awarded_marks": question.marks,
                "confidence": 0.95,
                "matched_point_ids": [],
                "feedback": "fb",
                "addresses_question": "yes",
            }
        )


def test_unaligned_leaves_go_to_review_and_are_never_marked_blank(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # The reader missed the label (i) of 4(b): leaf 4b_i has no label to bind to.
    first = _without_label(_run(4), "(i)", 9)
    model = _Model(first=_items(first), second=_items(_run(1)))
    extracted = _extract(tmp_path, scan, scheme, model)

    assert extracted.binding is not None and extracted.binding.verdict == "pass"
    assert extracted.unbound_question_ids == ["4b_i"]
    assert extracted.dropped_question_ids == []  # nothing was dropped as malformed
    assert "4b_i" not in {a.question_id for a in extracted.answers}
    # What the student wrote there was read, and is kept as writing with no question.
    assert any("thermal" in w.answer for w in extracted.unbound_answers)

    marker = _Marker()
    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=marker
    ):
        result = correct_paper(scheme, extracted, gemini_client=MagicMock())

    row = next(q for q in result.questions if q.question_id == "4b_i")
    assert "4b_i" not in marker.asked  # no marking call for it
    assert len(marker.asked) > 30  # the marker was asked about the others
    assert row.needs_teacher_review is True
    assert row.review_reason == (
        "binding unverified: this question's label was not found on the scan, or the "
        "writing by it could not be tied to it, so its answer could not be read"
    )
    assert row.marker_source == "dropped"  # not "blank": a blank is an unflagged zero
    assert row.confidence == ConfidenceBand.LOW and row.confidence_score == 0.0
    assert row.awarded_marks == 0 and row.student_answer is None
    assert result.needs_teacher_review is True

    # A leaf the student really left blank (7c) is still an ordinary, unflagged blank.
    blank = next(q for q in result.questions if q.question_id == "7c")
    assert blank.marker_source == "blank" and blank.needs_teacher_review is False


@pytest.mark.parametrize("number", [1, 2, 3, 4, 5])
def test_unbound_writing_travels_on_the_extraction(
    tmp_path: Path, scan: Path, scheme: MarkScheme, number: int
) -> None:
    items = _run(number)
    extracted = _extract(tmp_path, scan, scheme, _Model(first=_items(items)), second_read=False)

    stream = parse_stream_items(items, page_count=_PAGE_COUNT)
    writings = [item for item in stream.items if isinstance(item, SeenWriting)]
    unbound = list(extracted.unbound_answers)
    assert unbound, "every recorded reply has writing that no leaf could be given"
    bound_answers = "\n".join(a.answer for a in extracted.answers)
    bound_working = "\n".join(a.working_out or "" for a in extracted.answers)
    # Every block the reader reported is either inside a bound answer or kept unbound.
    for writing in writings:
        if writing in unbound:
            unbound.remove(writing)
            continue
        assert writing.answer.strip() == "" or writing.answer in bound_answers
        working = writing.working_out or ""
        assert working.strip() == "" or working in bound_working
    assert unbound == []  # and nothing is unbound that the reader did not report
    assert stream.drops.get("empty_answer", 0) + len(writings) == sum(
        1 for item in items if item.get("type") == "answer"
    )


def test_run_three_unbound_blocks_are_the_three_drawn_on_notes(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    extracted = _extract(tmp_path, scan, scheme, _Model(first=_items(_run(3))), second_read=False)
    assert [(w.page, w.answer[:22]) for w in extracted.unbound_answers] == [
        (2, "straight reading-weigh"),
        (4, "130 marked on speed ax"),
        (6, "rough diagram of block"),
    ]
    assert [a.question_id for a in extracted.answers if a.binding_status == "unverified"] == [
        "4b_i",
        "6b",
        "7b_i",
        "8d",
    ]


@pytest.mark.parametrize(
    ("number", "doubted"),
    [
        (1, ["7b_i"]),
        (2, ["2c", "6b", "7b_i", "8d"]),
        (3, ["4b_i", "6b", "7b_i", "8d"]),
        (4, ["3c", "4b_i"]),
        (5, ["3c", "4b_i", "6b", "7b_i", "8d"]),
    ],
)
def test_answers_the_binder_doubts_reach_a_teacher(
    tmp_path: Path, scan: Path, scheme: MarkScheme, number: int, doubted: list[str]
) -> None:
    extracted = _extract(
        tmp_path, scan, scheme, _Model(first=_items(_run(number))), second_read=False
    )
    assert [a.question_id for a in extracted.answers if a.binding_status == "unverified"] == doubted

    marker = _Marker()
    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=marker
    ):
        result = correct_paper(scheme, extracted, gemini_client=MagicMock())
    reason = "binding unverified: this answer may include writing that belongs to another question"
    flagged = [q for q in result.questions if reason in (q.review_reason or "")]
    assert [q.question_id for q in flagged] == doubted
    assert all(q.needs_teacher_review for q in flagged)
    assert all(q.marker_source == "ai" and q.awarded_marks == q.maximum_marks for q in flagged)
    assert set(doubted) <= set(marker.asked)  # marked as usual, then flagged


def test_question_scope_failures_mark_answers_unverified(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # G9 at question scope: the second read holds two sentences under each other's leaf.
    second = _with_texts_rotated(_run(1), 2)
    outcome = _bind(tmp_path, scheme, _Model(first=_items(_run(1)), second=_items(second)))
    assert outcome.report is not None and outcome.report.verdict == "pass"
    assert _failed(outcome) == [("G9", "question")]
    disagreeing = outcome.report.checks[-1].question_ids
    assert disagreeing == ["2c", "3a"]
    status = {a.question_id: a.binding_status for a in outcome.answers}
    # 7b_i was already doubted by the binder; that is kept, not overwritten.
    assert {qid for qid, s in status.items() if s == "unverified"} == {"2c", "3a", "7b_i"}
    assert all(s == "verified" for qid, s in status.items() if qid not in {"2c", "3a", "7b_i"})

    # G5 at question scope: 4b_i has no label, so the answer before it (4a) may hold its text.
    first = _without_label(_run(4), "(i)", 9)
    outcome = _bind(tmp_path, scheme, _Model(first=_items(first)), second_read=False)
    assert _failed(outcome) == [("G5", "question")]
    status = {a.question_id: a.binding_status for a in outcome.answers}
    assert status["4a"] == "unverified"
    assert outcome.review_only_ids == ["4b_i"]


@pytest.mark.parametrize(
    ("spoiled", "reason"),
    [("a bare string where an item should be", "malformed_item"), (None, "unknown_type")],
)
def test_lost_items_fail_the_paper(
    tmp_path: Path, scan: Path, scheme: MarkScheme, spoiled: str | None, reason: str
) -> None:
    # One block of the reply cannot be read as an item: the answer to 5(a).
    first = copy.deepcopy(_run(1))
    assert first[53]["type"] == "answer"
    first[53] = spoiled if spoiled is not None else {**first[53], "type": "note"}

    held = _bind(tmp_path, scheme, _Model(first=_items(first)), second_read=False)
    assert held.report is not None
    assert (held.report.verdict, held.report.retried) == ("hold", False)
    assert _failed(held) == [("G5", "paper")]
    g5 = next(c for c in held.report.checks if c.id == "G5")
    assert "1 item of the reader's reply could not be read" in g5.detail
    assert held.drops == {reason: 1}
    # 5a looks blank in this read. It is not: the paper is held, not published as one.
    assert "5a" not in {a.question_id for a in held.answers}

    # A second read that lost nothing is used in its place.
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        extracted = _extract(
            tmp_path, scan, scheme, _Model(first=_items(first), second=_items(_run(1)))
        )
    assert extracted.binding is not None
    assert (extracted.binding.verdict, extracted.binding.retried) == ("pass", True)
    assert "5a" in {a.question_id for a in extracted.answers}
    assert extracted.answer_drops == {}
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert event["drops"] == {}


def test_what_the_reader_s_reply_lost_or_had_repaired_stays_on_the_record(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # The answer to 5(a) comes back with a page that is not a page. The block is kept,
    # as writing with no question, and the repair is counted on the extraction itself.
    first = copy.deepcopy(_run(1))
    assert first[53]["type"] == "answer"
    first[53]["page"] = "nowhere"
    extracted = _extract(tmp_path, scan, scheme, _Model(first=_items(first)), second_read=False)
    # Under its own prefix: the legacy extractor's reasons live in the same field.
    assert extracted.answer_drops == {"stream_repaired_page": 1}
    assert first[53]["answer"] in [w.answer for w in extracted.unbound_answers]
    assert "5a" not in {a.question_id for a in extracted.answers}
    assert extracted.unbound_question_ids == ["5a"]  # to a teacher, not a blank zero


def test_one_group_listed_before_its_labels_is_never_trusted(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # Both reads list the two blocks of 1(c) before their labels. The list then binds
    # "13 m/s^2", the answer to 1(c)(ii), to 1(c)(i), leaves 1(c)(ii) with nothing, and
    # "4.9 N" with no leaf. One such group is under the limit that holds a paper.
    items = list(_run(1))
    for label_at in (10, 12):
        items[label_at], items[label_at + 1] = items[label_at + 1], items[label_at]
    extracted = _extract(tmp_path, scan, scheme, _Model(first=_items(items), second=_items(items)))

    report = extracted.binding
    assert report is not None and report.verdict == "pass"
    g5 = next(c for c in report.checks if c.id == "G5")
    assert (g5.passed, g5.scope) == (False, "question")
    assert g5.question_ids == ["1c_i", "1c_ii"]
    by_id = {a.question_id: a for a in extracted.answers}
    assert by_id["1c_i"].answer == "13 m/s^2" and by_id["1c_i"].binding_status == "unverified"
    assert "1c_ii" not in by_id
    assert extracted.unbound_question_ids == ["1c_ii"]
    assert "4.9 N" in [w.answer for w in extracted.unbound_answers]
    assert by_id["1b"].binding_status == "verified"  # the part before the group is untouched

    marker = _Marker()
    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=marker
    ):
        result = correct_paper(scheme, extracted, gemini_client=MagicMock())
    rows = {q.question_id: q for q in result.questions}
    assert rows["1c_i"].needs_teacher_review
    assert "may include writing that belongs to another question" in (
        rows["1c_i"].review_reason or ""
    )
    assert rows["1c_ii"].needs_teacher_review and rows["1c_ii"].marker_source == "dropped"
    assert "1c_ii" not in marker.asked  # not marked as a blank, not marked at all


@pytest.mark.parametrize("number", [1, 2, 3, 4, 5])
def test_the_recorded_replies_show_no_suspect_group(scheme: MarkScheme, number: int) -> None:
    stream = parse_stream_items(_run(number), page_count=_PAGE_COUNT)
    read = to_bound_read(
        bind_stream(stream.items, scheme), page_count=_PAGE_COUNT, drops=stream.drops
    )
    assert read.listing_suspects == []


def _stray_label(text: str) -> dict[str, Any]:
    return {"type": "label", "page": 0, "box": [10, 10, 30, 40], "text": text, "kind": "printed"}


def test_stray_labels_reach_the_coverage_check(tmp_path: Path, scheme: MarkScheme) -> None:
    # Labels on the cover page that name no question of this paper.
    strays = [_stray_label(text) for text in ("97", "98", "99")]
    two = _bind(tmp_path, scheme, _Model(first=_items([*strays[:2], *_run(1)])), second_read=False)
    assert two.report.verdict == "pass"
    g5 = next(c for c in two.report.checks if c.id == "G5")
    assert g5.passed and "2 labels on the page matched no question" in g5.detail

    three = _bind(tmp_path, scheme, _Model(first=_items([*strays, *_run(1)])), second_read=False)
    assert three.report.verdict == "hold"
    assert _failed(three) == [("G5", "paper")]
    g5 = next(c for c in three.report.checks if c.id == "G5")
    assert "3 labels on the page matched no question" in g5.detail


def test_only_items_that_may_have_been_writing_count_as_lost(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    assert LOST_ITEM_REASONS == ("malformed_item", "unknown_type")
    # Four other things the reader's reply can need: none of them loses writing. An
    # answer item with no writing in it and a label with no text are dropped; an answer
    # on a page that is not a page, and one whose text is not text, are kept unbound.
    last_page = _PAGE_COUNT - 1
    extras = [
        {"type": "answer", "page": last_page, "box": [1, 1, 5, 5], "answer": None},
        {"type": "label", "page": last_page, "box": [1, 1, 5, 5], "text": "  ", "kind": "printed"},
        {"type": "answer", "page": "nowhere", "box": [1, 1, 5, 5], "answer": "a late note"},
        {"type": "answer", "page": last_page, "box": [1, 1, 5, 5], "answer": ["not", "text"]},
    ]
    outcome = _bind(tmp_path, scheme, _Model(first=_items([*_run(1), *extras])), second_read=False)
    assert outcome.drops == {
        "empty_answer": 1,
        "empty_label": 1,
        "repaired_page": 1,
        "unreadable_answer": 1,
    }
    g5 = next(c for c in outcome.report.checks if c.id == "G5")
    assert "could not be read" not in g5.detail
    assert not any(c.scope == "paper" and not c.passed for c in outcome.report.checks)
    assert outcome.report.verdict == "pass"
    assert "a late note" in [w.answer for w in outcome.unbound]


def _with_1c_listed_first(items: list[Any]) -> list[Any]:
    """Recorded reply 1 with the two blocks of 1(c) listed before their labels."""
    out = list(items)
    for label_at in (10, 12):
        assert out[label_at]["type"] == "label" and out[label_at + 1]["type"] == "answer"
        out[label_at], out[label_at + 1] = out[label_at + 1], out[label_at]
    return out


def _with_an_item_lost(items: list[Any], index: int) -> list[Any]:
    assert items[index]["type"] == "answer"
    return [*items[:index], "not an item", *items[index + 1 :]]


def test_only_the_returned_read_s_suspect_groups_are_doubted(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The first read lists 1(c) out of order and also loses an item, which fails it; the
    # clean second read is used. Its 1(c) is in order and is trusted.
    first = _with_an_item_lost(_with_1c_listed_first(_run(1)), 60)
    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(_run(1))))
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", True)
    doubted = {a.question_id for a in outcome.answers if a.binding_status == "unverified"}
    # 1c_i is answered in both reads and is not in a suspect group of the read used.
    # 1c_ii and 5c_ii are doubted for another reason: the first read had nothing under
    # them (the group's last part, and the lost item). 7b_i is the binder's own doubt.
    assert doubted == {"1c_ii", "5c_ii", "7b_i"}
    assert outcome.review_only_ids == []

    # The other way round: the read that is used is the one with the group out of order.
    first = _with_an_item_lost(_run(1), 60)
    second = _with_1c_listed_first(_run(1))
    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(second)))
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", True)
    status = {a.question_id: a.binding_status for a in outcome.answers}
    assert status["1c_i"] == "unverified"
    assert "1c_ii" in outcome.review_only_ids


def test_only_the_first_read_s_paper_scope_failures_are_recorded_as_why_it_was_set_aside(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The first read fails the paper (an item lost) and also has two answers under each
    # other's part, which G7 names at question scope. Only the first is why it was
    # replaced.
    first = copy.deepcopy(_run(1))
    assert (first[8]["answer"], first[11]["answer"]) == ("0.28 N/cm", "4.9 N")
    first[8]["answer"], first[11]["answer"] = first[11]["answer"], first[8]["answer"]
    first = _with_an_item_lost(first, 60)
    alone = _bind(tmp_path, scheme, _Model(first=_items(first)), second_read=False)
    assert sorted(_failed(alone)) == [("G5", "paper"), ("G7", "question")]

    with (
        _events(EventType.BINDING_GATE_RESULT) as seen,
        structlog.testing.capture_logs() as logs,
    ):
        outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(_run(1))))
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", True)
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert [(c["id"], c["scope"]) for c in event["first_read_failed_checks"]] == [("G5", "paper")]
    (line,) = [entry for entry in logs if entry["event"] == "binding_gate_result"]
    assert line["first_read_failed_checks"] == ["G5"]


def _flat_reply(leaves: list[str], *, name: str | None, blank: set[str]) -> list[Any]:
    """A reply for a paper of top-level questions: each label, then a letter under it."""
    items: list[Any] = []
    if name is not None:
        items.append(
            {
                "type": "answer",
                "page": 0,
                "box": [1, 1, 5, 5],
                "answer": name,
                "working_out": None,
                "confidence": 0.9,
                "placed_by": "position",
            }
        )
    for position, leaf in enumerate(leaves):
        page = 1 + position // 10
        items.append(
            {
                "type": "label",
                "page": page,
                "box": [10, 10, 20, 20],
                "text": leaf,
                "kind": "printed",
            }
        )
        if leaf not in blank:
            items.append(
                {
                    "type": "answer",
                    "page": page,
                    "box": [10, 30, 20, 40],
                    "answer": "ABCD"[position % 4],
                    "working_out": None,
                    "confidence": 0.9,
                    "placed_by": "position",
                }
            )
    return items


def test_one_suspect_trace_on_a_flat_paper_sends_every_answer_to_review(tmp_path: Path) -> None:
    # A paper of forty multiple-choice questions and no parts. The student wrote a name
    # above question 1 and left question 40 blank; both reads list everything in order
    # and every answer is on its own question. But a block before the first label and
    # the last question blank is exactly what the whole paper listed one out looks
    # like, and on a paper with no parts the group that trace names is the whole paper.
    # The cost is accepted: every answer is marked, keeps its marks and is flagged, and
    # question 40 goes to a teacher. No flat paper has a recorded reply, so how often a
    # reader reports writing above the first label is not known.
    flat = MarkScheme.model_validate(
        json.loads((_ROOT / "corpus" / "mark-schemes" / "0625_m19_ms_12.json").read_text())
    )
    leaves = [q.id for q in flat.all_questions_flat() if not q.parts and q.marks > 0]
    assert len(leaves) == 40 and all(q.parent_id is None for q in flat.all_questions_flat())

    def bind(*, name: str | None, blank: set[str]) -> BindingOutcome:
        reply = _flat_reply(leaves, name=name, blank=blank)
        client, _genai = _client(tmp_path)
        pages = _pages(6)
        with (
            client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
            patch.object(
                client,
                "generate_structured",
                side_effect=_Model(first=_items(reply), second=_items(reply)),
            ),
        ):
            return run_binding(
                client, pages, flat, uploads=uploads, settings=client._settings, manifest_key="m"
            )

    both = bind(name="Aisha Khan 0123", blank={"40"})
    assert both.report.verdict == "pass"
    assert _failed(both) == [("G5", "question")]
    g5 = next(c for c in both.report.checks if c.id == "G5")
    assert g5.question_ids == leaves  # all forty
    assert len(both.answers) == 39
    assert all(a.binding_status == "unverified" for a in both.answers)
    assert both.review_only_ids == ["40"]

    # Either half alone is ordinary and flags nothing.
    for name, blank in (("Aisha Khan 0123", set()), (None, {"40"})):
        alone = bind(name=name, blank=blank)
        assert alone.report.verdict == "pass" and _failed(alone) == []
        assert all(a.binding_status == "verified" for a in alone.answers)
        assert alone.review_only_ids == []


def _reply_for(scheme: MarkScheme, *, writing_first_under: str) -> list[Any]:
    """A reader's list for ``scheme``: every label, each leaf's writing after its label.

    Under the question ``writing_first_under`` each part's writing is listed before the
    part's label instead. A leaf's writing is the text ``answer to <id>``.
    """

    def label(text: str) -> dict[str, Any]:
        return {
            "type": "label",
            "page": 1,
            "box": [10, 10, 20, 20],
            "text": text,
            "kind": "printed",
        }

    def writing(qid: str) -> dict[str, Any]:
        return {
            "type": "answer",
            "page": 1,
            "box": [10, 30, 20, 40],
            "answer": f"answer to {qid}",
            "working_out": None,
            "confidence": 0.9,
            "placed_by": "position",
        }

    items: list[Any] = []

    def walk(question: Question, parent: Question | None, first: bool) -> None:
        if parent is None:
            token = question.id
        else:
            token = "(" + question.id[len(parent.id) :].removeprefix("_") + ")"
        own = [label(token)]
        if not question.parts:
            own = [writing(question.id), *own] if first else [*own, writing(question.id)]
        items.extend(own)
        for part in question.parts:
            walk(part, question, first or question.id == writing_first_under)

    for top in scheme.questions:
        walk(top, None, False)
    return items


def test_a_suspect_group_is_doubted_on_a_scheme_whose_parent_ids_are_missing(
    tmp_path: Path,
) -> None:
    # Question 2 of 0625/42 (three parts) with each part's writing listed before its
    # label: 2(a) holds 2(b)'s writing, 2(b) holds 2(c)'s, 2(c) has nothing. The scheme's
    # `parent_id` fields are all null, as an AI-parsed scheme's can be.
    path = _ROOT / "corpus" / "mark-schemes" / "0625_s23_ms_42.json"
    as_parsed = MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def strip(node: dict[str, Any]) -> dict[str, Any]:
        return {**node, "parent_id": None, "parts": [strip(part) for part in node["parts"]]}

    data = as_parsed.model_dump()
    data["questions"] = [strip(question) for question in data["questions"]]
    orphaned = MarkScheme.model_validate(data)
    assert {q.parent_id for q in orphaned.all_questions_flat()} == {None}

    reply = _reply_for(as_parsed, writing_first_under="2")
    client, _genai = _client(tmp_path)
    pages = _pages(6)
    with (
        client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
        patch.object(
            client,
            "generate_structured",
            side_effect=_Model(first=_items(reply), second=_items(reply)),
        ),
    ):
        outcome = run_binding(
            client, pages, orphaned, uploads=uploads, settings=client._settings, manifest_key="m"
        )

    assert outcome.report.verdict == "pass"
    g5 = next(c for c in outcome.report.checks if c.id == "G5")
    assert (g5.passed, g5.scope, g5.question_ids) == (False, "question", ["2a", "2b", "2c"])
    by_id = {a.question_id: a for a in outcome.answers}
    # The two answers are the next part's, and neither goes on as verified.
    assert (by_id["2a"].answer, by_id["2a"].binding_status) == ("answer to 2b", "unverified")
    assert (by_id["2b"].answer, by_id["2b"].binding_status) == ("answer to 2c", "unverified")
    assert "2c" not in by_id and outcome.review_only_ids == ["2c"]
    others = [a for qid, a in by_id.items() if qid not in {"2a", "2b"}]
    assert len(others) > 20 and all(a.binding_status == "verified" for a in others)


def test_listing_suspects_fail_the_paper(tmp_path: Path, scheme: MarkScheme) -> None:
    first = _listed_before_labels(_run(1))
    held = _bind(tmp_path, scheme, _Model(first=_items(first)), second_read=False)
    assert held.report is not None and held.report.verdict == "hold"
    assert ("G5", "paper") in _failed(held)
    g5 = next(c for c in held.report.checks if c.id == "G5")
    assert "2 groups of parts" in g5.detail and "listed before its label" in g5.detail
    # Held or not, no leaf of either group is taken at face value.
    status = {a.question_id: a.binding_status for a in held.answers}
    assert status["1c_i"] == status["9c_i"] == status["9c_ii"] == status["9c_iii"] == "unverified"
    assert {"1c_ii", "9c_iv"} <= set(held.review_only_ids)

    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(_run(2))))
    assert outcome.report is not None
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", True)
    assert _pairs(outcome) == _bound_alone(_run(2), scheme)


# --------------------------------------------------------------------------------------
# Gate modes
# --------------------------------------------------------------------------------------
def test_observe_mode_never_holds_but_reports(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # Observe is for watching the gate on the old path: the legacy binder's answers go
    # on exactly as with the gate off, and the event says what enforcing would have done.
    shifted = _legacy_reply("full_shift_lite")
    model = _Model(legacy=shifted)
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        extracted = _extract(tmp_path, scan, scheme, model, binder="legacy", gate="observe")

    assert extracted.binding is None and "binding" not in extracted.model_fields_set
    assert _pairs(extracted) == [(a["question_id"], a["answer"]) for a in shifted["answers"]]
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert (event["gate"], event["verdict"], event["retried"]) == ("observe", "retry", False)
    assert "G7" in event["failed_checks"]
    # The whole report enforcing would have returned, every check with its sentence.
    assert event["report"]["binder"] == "legacy" and event["report"]["verdict"] == "retry"
    assert all(check["detail"] for check in event["report"]["checks"])

    # Nothing downstream has a verdict to act on, before or after marking.
    marker = _Marker()
    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=marker
    ):
        result = correct_paper(scheme, extracted, gemini_client=MagicMock())
    assert result.binding is None


@pytest.mark.parametrize("gate", ["observe", "off"])
def test_the_label_binder_cannot_be_run_without_the_gate(
    tmp_path: Path, scheme: MarkScheme, gate: str
) -> None:
    # Deleted with this: `test_observe_mode_leaves_nothing_on_the_extraction_to_hold_on`
    # and `test_an_unaligned_leaf_reaches_a_teacher_whatever_the_gate`, which ran the
    # label binder under observe and off. Those settings no longer exist: under them the
    # binder's own doubts and its lost items were published with no check over them.
    with pytest.raises(ValueError, match="binder"):
        _settings(tmp_path, gate=gate)
    # And a settings object that reached `run_binding` some other way is refused there.
    client, _genai = _client(tmp_path)
    forced = client._settings.model_copy(
        update={"binding": client._settings.binding.model_copy(update={"gate": gate})}
    )
    pages = _pages()
    with (
        client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
        patch.object(client, "generate_structured", side_effect=_Model(first=_items(_run(1)))),
        pytest.raises(ValueError, match="enforce"),
    ):
        run_binding(client, pages, scheme, uploads=uploads, settings=forced, manifest_key="k")


def test_gate_off_leaves_binding_none(tmp_path: Path, scan: Path, scheme: MarkScheme) -> None:
    # The gate can be off for the legacy binder only (the label binder requires it).
    shifted = _legacy_reply("full_shift_lite")
    model = _Model(legacy=shifted)
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        extracted = _extract(tmp_path, scan, scheme, model, binder="legacy", gate="off")

    assert model.made() == ["legacy"]  # no retry, whatever the answers look like
    assert extracted.binding is None
    assert seen[EventType.BINDING_GATE_RESULT] == []
    assert _pairs(extracted) == [(a["question_id"], a["answer"]) for a in shifted["answers"]]
    assert all(a.binding_source is None for a in extracted.answers)
    assert extracted.unbound_question_ids == [] and extracted.unbound_answers == []


def test_legacy_binder_output_is_gated_and_retried(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    shifted = _legacy_reply("full_shift_lite")
    binding = {"binder": "legacy", "retry_model": "gemini-retry-under-test"}

    # Retry, then hold: the repeat call is shifted as well.
    model = _Model(legacy=shifted, retry=_legacy_reply("full_shift_38_a"))
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        extracted = _extract(tmp_path, scan, scheme, model, **binding)
    assert model.made() == ["legacy", "retry"]
    first_call, retry_call = model.call("legacy"), model.call("retry")
    assert "model" not in first_call
    assert retry_call["model"] == "gemini-retry-under-test"
    assert retry_call["extra_cache_key"] == first_call["extra_cache_key"] + "|retry"
    assert retry_call["extra_cache_key"] != first_call["extra_cache_key"]
    for key in ("system_prompt", "user_prompt", "response_schema", "prompt_version", "task_tag"):
        assert retry_call[key] == first_call[key]  # the same call, repeated
    report = extracted.binding
    assert report is not None
    assert (report.binder, report.verdict, report.retried) == ("legacy", "hold", True)
    assert {c.id for c in report.checks} == {"G1", "G2", "G6", "G7"}  # no G5, no G9
    assert ("G7", "paper") in [(c.id, c.scope) for c in report.checks if not c.passed]
    assert _pairs(extracted) == [(a["question_id"], a["answer"]) for a in shifted["answers"]]
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert (event["binder"], event["verdict"], event["retried"]) == ("legacy", "hold", True)
    assert (event["unbound"], event["unaligned"], event["inferred_numbers"]) == (0, 0, [])

    # Retry, then pass: the repeat call is right, and is the one used.
    aligned = _legacy_reply("aligned")
    model = _Model(legacy=shifted, retry=aligned)
    extracted = _extract(tmp_path, scan, scheme, model, **binding)
    report = extracted.binding
    assert report is not None
    assert (report.verdict, report.retried) == ("pass", True)
    assert report.model == "gemini-retry-under-test"
    assert _pairs(extracted) == [(a["question_id"], a["answer"]) for a in aligned["answers"]]
    assert extracted.unbound_answers == []

    # A first call that passes is used as it is, with no repeat.
    model = _Model(legacy=aligned)
    extracted = _extract(tmp_path, scan, scheme, model, **binding)
    assert model.made() == ["legacy"]
    report = extracted.binding
    assert report is not None
    assert (report.verdict, report.retried) == ("pass", False)
    assert report.model == _settings(tmp_path).gemini.model_for("extraction")


def test_gated_legacy_answers_are_stamped_and_the_doubted_ones_marked(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # The model spelt two ids its own way and put each of the two answers under the
    # other's question. Two is too few to doubt the paper: G7 names them at question
    # scope, by the mark scheme's spelling.
    reply = _legacy_reply("aligned")
    by_id = {answer["question_id"]: answer for answer in reply["answers"]}
    by_id["1b"]["answer"], by_id["1c_i"]["answer"] = by_id["1c_i"]["answer"], by_id["1b"]["answer"]
    by_id["1b"]["question_id"], by_id["1c_i"]["question_id"] = "1B", "1C_I"
    model = _Model(legacy=reply)  # a retry call would find no reply and fail the test
    extracted = _extract(tmp_path, scan, scheme, model, binder="legacy")

    report = extracted.binding
    assert report is not None
    assert (report.binder, report.verdict, report.retried) == ("legacy", "pass", False)
    assert [(c.id, c.scope, c.question_ids) for c in report.checks if not c.passed] == [
        ("G7", "question", ["1b", "1c_i"])
    ]
    # Every answer says where its id came from; only the two named ones are doubted.
    assert all(a.binding_source == "legacy" for a in extracted.answers)
    status = {a.question_id: a.binding_status for a in extracted.answers}
    assert {qid for qid, s in status.items() if s == "unverified"} == {"1b", "1c_i"}
    assert all(s is None for qid, s in status.items() if qid not in {"1b", "1c_i"})
    assert all(a.label_seen is None for a in extracted.answers)

    marker = _Marker()
    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=marker
    ):
        result = correct_paper(scheme, extracted, gemini_client=MagicMock())
    flagged = [
        q.question_id
        for q in result.questions
        if "may include writing that belongs to another question" in (q.review_reason or "")
    ]
    assert flagged == ["1b", "1c_i"]


def test_legacy_retry_cost_ceiling_propagates_and_other_failures_hold(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    shifted = _legacy_reply("full_shift_lite")
    ceiling = CostCeilingError("USD ceiling reached")
    with pytest.raises(CostCeilingError) as raised:
        _extract(tmp_path, scan, scheme, _Model(legacy=shifted, retry=ceiling), binder="legacy")
    assert raised.value is ceiling

    with _events(EventType.SECOND_READ_FAILED) as seen:
        extracted = _extract(
            tmp_path,
            scan,
            scheme,
            _Model(legacy=shifted, retry=ExternalServiceError("503")),
            binder="legacy",
        )
    assert extracted.binding is not None
    # The one retry was spent, though it brought nothing back.
    assert (extracted.binding.verdict, extracted.binding.retried) == ("hold", True)
    (failure,) = seen[EventType.SECOND_READ_FAILED]
    assert failure["stage"] == "binding_retry"
    assert _pairs(extracted) == [(a["question_id"], a["answer"]) for a in shifted["answers"]]


def test_legacy_binder_under_observe_makes_no_retry_call(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    shifted = _legacy_reply("full_shift_lite")
    model = _Model(legacy=shifted)  # a retry call would find no reply and fail the test
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        extracted = _extract(tmp_path, scan, scheme, model, binder="legacy", gate="observe")

    assert model.made() == ["legacy"]  # observe spends nothing that only enforce spends
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    # "retry" is what enforce would have done next.
    assert (event["binder"], event["gate"]) == ("legacy", "observe")
    assert (event["verdict"], event["retried"], event["second_read"]) == ("retry", False, False)
    assert "G7" in event["failed_checks"]
    assert event["report"]["verdict"] == "retry"
    # And the extraction is what it is with the gate off.
    assert extracted.binding is None and "binding" not in extracted.model_fields_set
    assert _pairs(extracted) == [(a["question_id"], a["answer"]) for a in shifted["answers"]]
    assert all(a.binding_source is None for a in extracted.answers)
    assert all(a.binding_status is None for a in extracted.answers)

    # A first call that passes is reported as a pass.
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        _extract(
            tmp_path,
            scan,
            scheme,
            _Model(legacy=_legacy_reply("aligned")),
            binder="legacy",
            gate="observe",
        )
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert (event["verdict"], event["retried"]) == ("pass", False)


def test_binding_gate_result_event_fields(tmp_path: Path, scan: Path, scheme: MarkScheme) -> None:
    # Recorded reply 4 lacks the label `4`; the binder infers it.
    model = _Model(first=_items(_run(4)), second=_items(_run(1)))
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        extracted = _extract(tmp_path, scan, scheme, model)
    (event,) = seen[EventType.BINDING_GATE_RESULT]  # once per extraction
    assert event == {
        "binder": "label",
        "gate": "enforce",
        "verdict": "pass",
        "retried": False,
        "failed_checks": [],
        "unbound": 2,
        "unaligned": 0,
        "inferred_numbers": ["4"],
        "drops": {},
        "model": _READ_MODEL,
        "second_read": True,
        "unaligned_reasons": {},
        "first_read_failed_checks": [],
        "report": extracted.binding.model_dump() if extracted.binding else None,
    }
    assert extracted.binding is not None
    assert len(extracted.unbound_answers) == event["unbound"]

    # A read with a repaired item and a missing label: the counts say so.
    first = copy.deepcopy(_without_label(_run(4), "(i)", 9))
    first[60]["page"] = "nowhere"
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        outcome = _bind(tmp_path, scheme, _Model(first=_items(first)), second_read=False)
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert event["failed_checks"] == ["G5"]
    assert event["unaligned"] == len(outcome.review_only_ids) >= 1
    assert event["unbound"] == len(outcome.unbound)
    assert event["drops"] == outcome.drops == {"repaired_page": 1}
    assert event["second_read"] is False


def test_why_each_leaf_went_to_review_is_kept_and_counted(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # Four ways a leaf ends up with a teacher and no answer, in one extraction each.
    base = _run(1)
    cases: dict[str, tuple[list[Any], list[Any], dict[str, str]]] = {
        # The reader missed the label (i) of 4(b) in the read that is used.
        "label missed": (
            _without_label(_run(4), "(i)", 9),
            _run(1),
            {"4b_i": "label_not_seen"},
        ),
        # The read that is used has nothing under 5(a); the other read has "0.2 m".
        "answered in the other read only": (
            _without_items(base, 53),
            base,
            {"5a": "answered_in_one_read_only"},
        ),
        # Both reads list the writing of 1(c) before its labels: 1(c)(ii) is left with none.
        "listed out of order": (
            _with_1c_listed_first(base),
            _with_1c_listed_first(base),
            {"1c_ii": "listing_suspect"},
        ),
        # Nothing under 4(b)(i) in the read that is used; the other read missed its label.
        "no label in the other read": (
            _without_items(_run(4), *_blocks_under(_run(4), "(i)", 9)),
            _without_label(_run(4), "(i)", 9),
            {"4b_i": "unaligned_in_other_read"},
        ),
    }
    for name, (first, second, expected) in cases.items():
        with (
            _events(EventType.BINDING_GATE_RESULT) as seen,
            structlog.testing.capture_logs() as logs,
        ):
            extracted = _extract(
                tmp_path, scan, scheme, _Model(first=_items(first), second=_items(second))
            )
        assert extracted.unbound_question_ids == list(expected), name
        assert extracted.unbound_question_reasons == expected, name
        counts = {reason: 1 for reason in expected.values()}
        (event,) = seen[EventType.BINDING_GATE_RESULT]
        assert event["unaligned_reasons"] == counts, name
        (line,) = [entry for entry in logs if entry["event"] == "binding_gate_result"]
        assert line["unaligned_reasons"] == counts, name


def test_a_question_the_mark_scheme_lists_twice_is_said_to_be_the_scheme_s_fault(
    tmp_path: Path,
) -> None:
    # 0625/61 June 2020 has the id 3b_iii twice in the corpus scheme. No label can be
    # matched to an id that is there twice, however clean the read: the question always
    # goes to a teacher. The reason must say what is wrong, and it is not the scan.
    path = _ROOT / "corpus" / "mark-schemes" / "0625_s20_ms_61.json"
    doubled = MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))
    leaf_ids = [q.id for q in doubled.all_questions_flat() if not q.parts]
    assert leaf_ids.count("3b_iii") == 2

    reply = _reply_for(doubled, writing_first_under="no question")
    client, _genai = _client(tmp_path)
    pages = _pages(6)
    with (
        client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
        patch.object(
            client,
            "generate_structured",
            side_effect=_Model(first=_items(reply), second=_items(reply)),
        ),
        structlog.testing.capture_logs() as logs,
    ):
        outcome = run_binding(
            client, pages, doubled, uploads=uploads, settings=client._settings, manifest_key="m"
        )
    assert outcome.review_reasons["3b_iii"] == "duplicate_id"
    assert outcome.review_only_ids.count("3b_iii") == 1
    (line,) = [entry for entry in logs if entry["event"] == "binding_gate_result"]
    assert line["unaligned_reasons"]["duplicate_id"] == 1
    # G5 counts and lists the question once.
    g5 = next(c for c in outcome.report.checks if c.id == "G5")
    assert g5.question_ids.count("3b_iii") == 1
    assert "3b_iii, 3b_iii" not in g5.detail


def test_the_gate_result_is_logged_on_the_server_without_any_answer_text(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The event has no subscriber of its own; the log line is the server's record.
    first = _question_4_unanchored(4)
    with structlog.testing.capture_logs() as logs:
        outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(_run(1))))
    (line,) = [entry for entry in logs if entry["event"] == "binding_gate_result"]
    assert line == {
        "event": "binding_gate_result",
        "log_level": "info",
        "component": "binding_gate",
        "binder": "label",
        "gate": "enforce",
        "verdict": "pass",
        "retried": True,
        "failed_checks": [],
        "first_read_failed_checks": ["G5"],
        "unbound": len(outcome.unbound),
        "unaligned": 0,
        "inferred_numbers": [],
        "drops": {},
        "model": _READ_MODEL,
        "second_read": True,
        "unaligned_reasons": {},
    }
    assert not any(answer.answer in str(line) for answer in outcome.answers if answer.answer)

    # The legacy binder's gate is logged the same way, held or observed.
    with structlog.testing.capture_logs() as logs:
        _extract_legacy_observed(tmp_path, scheme)
    (line,) = [entry for entry in logs if entry["event"] == "binding_gate_result"]
    assert (line["binder"], line["gate"], line["verdict"]) == ("legacy", "observe", "retry")
    assert line["first_read_failed_checks"] == []


def _extract_legacy_observed(tmp: Path, scheme: MarkScheme) -> None:
    """Gate the shifted legacy reply under observe, with no extraction around it."""
    from lemely.io.binding.orchestrate import LegacyRead, gate_legacy

    shifted = ExtractedAnswers.model_validate(
        json.loads((_FIXTURES / "full_shift_lite.json").read_text(encoding="utf-8"))
    )
    gate_legacy(
        LegacyRead(answers=shifted.answers, drops={}),
        scheme,
        settings=_settings(tmp, binder="legacy", gate="observe"),
        model="gemini-legacy-under-test",
        retry=lambda: pytest.fail("observe must not make the retry call"),
    )


# --------------------------------------------------------------------------------------
# The response cache
# --------------------------------------------------------------------------------------
def _sdk_reply(body: dict[str, Any]) -> MagicMock:
    return MagicMock(
        text=json.dumps(body),
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(prompt_token_count=5, candidates_token_count=30),
    )


def _bind_for_real(client: GeminiClient, scheme: MarkScheme) -> BindingOutcome:
    """``run_binding`` through the real ``generate_structured`` and its response cache."""
    pages = _pages()
    with client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads:
        return run_binding(
            client, pages, scheme, uploads=uploads, settings=client._settings, manifest_key="k"
        )


def test_a_held_paper_does_not_pin_its_reads_in_the_cache(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # Both reads miss the same labels: a hold. The cache keys of the two reads are fixed
    # by the page bytes, the scheme and the prompt, so if the replies stayed cached, the
    # student's "try again" and the teacher's re-run would get the same hold back
    # without the scan being read at all.
    client, genai = _client(tmp_path)
    genai.models.generate_content.return_value = _sdk_reply(_items(_question_4_unanchored(4)))
    held = _bind_for_real(client, scheme)
    assert held.report.verdict == "hold"
    assert genai.models.generate_content.call_count == 2

    # Run again on the same file and scheme: both reads are made afresh. This time the
    # reader sees every label, and the paper passes.
    genai.models.generate_content.return_value = _sdk_reply(_items(_run(1)))
    again = _bind_for_real(client, scheme)
    assert genai.models.generate_content.call_count == 4
    assert again.report.verdict == "pass"


def test_a_paper_that_passed_is_served_from_the_cache_on_a_re_run(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    client, genai = _client(tmp_path)
    genai.models.generate_content.return_value = _sdk_reply(_items(_run(1)))
    first = _bind_for_real(client, scheme)
    assert first.report.verdict == "pass"
    assert genai.models.generate_content.call_count == 2

    again = _bind_for_real(client, scheme)
    assert genai.models.generate_content.call_count == 2  # no model call
    assert again.answers == first.answers and again.report == first.report


def test_a_job_that_failed_on_the_second_read_does_not_pin_the_first(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    client, genai = _client(tmp_path)
    genai.models.generate_content.return_value = _sdk_reply(_items(_run(1)))
    real = client.generate_structured

    def second_read_is_down(**kwargs: Any) -> Any:
        if kwargs.get("task_tag") == "binding_second_read":
            raise ExternalServiceError("503 from the service")
        return real(**kwargs)

    with (
        patch.object(client, "generate_structured", side_effect=second_read_is_down),
        pytest.raises(ExternalServiceError),
    ):
        _bind_for_real(client, scheme)
    assert genai.models.generate_content.call_count == 1  # the first read was made, and cached

    # The service is back. Nothing of the failed job is reused: both reads are made.
    outcome = _bind_for_real(client, scheme)
    assert genai.models.generate_content.call_count == 3
    assert outcome.report.verdict == "pass"


def test_a_held_legacy_paper_does_not_pin_its_call_or_its_retry(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    client, genai = _client(tmp_path, binder="legacy")
    extractor = GeminiAnswerExtractor(client, max_rereads_per_paper=0)
    genai.models.generate_content.return_value = _sdk_reply(_legacy_reply("full_shift_lite"))
    held = extractor(scan_path=scan, mark_scheme=scheme)
    assert held.binding is not None and held.binding.verdict == "hold"
    assert genai.models.generate_content.call_count == 2  # the call and its retry

    genai.models.generate_content.return_value = _sdk_reply(_legacy_reply("aligned"))
    again = extractor(scan_path=scan, mark_scheme=scheme)
    assert genai.models.generate_content.call_count == 3  # read afresh; it passes, no retry
    assert again.binding is not None and again.binding.verdict == "pass"

    # And a legacy paper that passed stays cached.
    extractor(scan_path=scan, mark_scheme=scheme)
    assert genai.models.generate_content.call_count == 3


def test_legacy_binder_with_gate_off_is_unchanged(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    aligned = _legacy_reply("aligned")
    client, genai = _client(tmp_path, binder="legacy", gate="off")
    genai.models.generate_content.return_value = MagicMock(
        text=json.dumps(aligned),
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(prompt_token_count=5, candidates_token_count=30),
    )
    with (
        _events(EventType.BINDING_GATE_RESULT) as seen,
        patch.object(client, "generate_structured", wraps=client.generate_structured) as spy,
    ):
        extracted = GeminiAnswerExtractor(client, max_rereads_per_paper=0)(
            scan_path=scan, mark_scheme=scheme
        )

    # One call, with exactly the arguments the extraction call has always had.
    assert genai.models.generate_content.call_count == 1
    (call,) = spy.call_args_list
    assert sorted(call.kwargs) == [
        "extra_cache_key",
        "image_parts",
        "image_uploads",
        "media_resolution",
        "prompt_version",
        "response_schema",
        "system_prompt",
        "task_tag",
        "user_prompt",
    ]
    assert call.kwargs["task_tag"] == "extraction"
    assert call.kwargs["media_resolution"] == "medium"
    assert call.kwargs["response_schema"].__name__ == "_ExtractorOutput"
    # Nothing of the binding work is on the result, set or unset.
    assert seen[EventType.BINDING_GATE_RESULT] == []
    assert extracted.binding is None and extracted.unbound_answers == []
    assert not {"binding", "unbound_answers"} & extracted.model_fields_set
    for answer in extracted.answers:
        assert answer.binding_source is None
        assert answer.binding_status is None
        assert answer.label_seen is None
        assert not {"binding_source", "binding_status", "label_seen"} & answer.model_fields_set
    assert _pairs(extracted) == [(a["question_id"], a["answer"]) for a in aligned["answers"]]
    assert extracted.dropped_question_ids == []
    assert extracted.unbound_question_ids == []
