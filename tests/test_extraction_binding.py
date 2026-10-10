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
from PIL import Image

from lemely.core.binding import SeenWriting
from lemely.core.label_sequence import bind_stream
from lemely.core.loose_schemas import MarkScheme, Question
from lemely.core.schemas import AIMarkResponse, ConfidenceBand, ExtractedAnswers
from lemely.io import correction_ai
from lemely.io.answer_extraction import GeminiAnswerExtractor
from lemely.io.binding import parse_stream_items, to_bound_read
from lemely.io.binding.orchestrate import BindingOutcome, run_binding
from lemely.io.correction_ai import correct_paper
from lemely.io.gemini import GeminiClient
from lemely.io.rasterise import RasterisedPage
from lemely.runtime.config import BindingSettings, PathsSettings, Settings, load_settings
from lemely.runtime.errors import CostCeilingError, ExternalServiceError
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
    its repeat. A reply is the body the model returned, or an exception to raise. The
    two reads run on separate threads, so the key comes from the call and not its order.
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
    # The report is about the read that was used: the second read's checks, and G9.
    assert _failed(outcome) == []
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert (event["verdict"], event["retried"], event["second_read"]) == ("pass", True, True)

    # Alone, the first read is a paper nobody should publish: five leaves have no label.
    alone = _bind(tmp_path, scheme, _Model(first=_items(first)), second_read=False)
    assert alone.review_only_ids == ["3c", "4a", "4b_i", "4b_ii", "4b_iii"]
    assert _failed(alone) == [("G5", "paper")]
    assert alone.report is not None
    assert (alone.report.verdict, alone.report.retried) == ("hold", False)


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


def test_two_bad_reads_hold(tmp_path: Path, scheme: MarkScheme) -> None:
    first, second = _question_4_unanchored(4), _question_4_unanchored(5)
    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(second)))

    assert outcome.report is not None
    assert (outcome.report.verdict, outcome.report.retried) == ("hold", True)
    assert _failed(outcome) == [("G5", "paper")]
    assert [c.id for c in outcome.report.checks][-1] == "G9"
    assert _pairs(outcome) == _bound_alone(first, scheme)
    assert outcome.review_only_ids == ["3c", "4a", "4b_i", "4b_ii", "4b_iii"]


def test_failed_second_read_does_not_fail_the_paper(tmp_path: Path, scheme: MarkScheme) -> None:
    model = _Model(first=_items(_run(1)), second=ExternalServiceError("503 from the service"))
    with _events(EventType.SECOND_READ_FAILED, EventType.BINDING_GATE_RESULT) as seen:
        outcome = _bind(tmp_path, scheme, model)

    assert model.made() == ["first", "second"]
    assert outcome.report is not None
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", False)
    assert [c.id for c in outcome.report.checks] == ["G1", "G2", "G5", "G6", "G7"]  # no G9
    assert _pairs(outcome) == _bound_alone(_run(1), scheme)
    (failure,) = seen[EventType.SECOND_READ_FAILED]
    assert failure["error"] == "503 from the service"
    assert failure["error_type"] == "ExternalServiceError"
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert event["second_read"] is False

    # With no second read to fall back on, a bad first read is a hold with nothing retried.
    bad = _Model(first=_items(_question_4_unanchored(4)), second=ExternalServiceError("503"))
    held = _bind(tmp_path, scheme, bad)
    assert held.report is not None
    assert (held.report.verdict, held.report.retried) == ("hold", False)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("ceiling", "reply"),
        ("reply", "ceiling"),
        ("ceiling", "ceiling"),
        # The ceiling stops the run whatever else went wrong beside it.
        ("service error", "ceiling"),
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
    }
    model = _Model(first=replies[first], second=replies[second])
    with (
        _events(EventType.SECOND_READ_FAILED, EventType.BINDING_GATE_RESULT) as seen,
        pytest.raises(CostCeilingError) as raised,
    ):
        _bind(tmp_path, scheme, model)
    assert raised.value is ceiling  # unchanged, not wrapped
    assert seen[EventType.SECOND_READ_FAILED] == []  # a breach is not a failed second read
    assert seen[EventType.BINDING_GATE_RESULT] == []


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
    assert extracted.dropped_question_ids == ["4b_i"]
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
    # as writing with no question, and the repair is counted on the extraction itself:
    # with the gate off there is no report and no event to carry it.
    first = copy.deepcopy(_run(1))
    assert first[53]["type"] == "answer"
    first[53]["page"] = "nowhere"
    for gate in ("off", "enforce"):
        extracted = _extract(
            tmp_path, scan, scheme, _Model(first=_items(first)), gate=gate, second_read=False
        )
        # Under its own prefix: the legacy extractor's reasons live in the same field.
        assert extracted.answer_drops == {"stream_repaired_page": 1}
        assert first[53]["answer"] in [w.answer for w in extracted.unbound_answers]
        assert "5a" not in {a.question_id for a in extracted.answers}
        assert extracted.dropped_question_ids == ["5a"]  # to a teacher, not a blank zero


def test_listing_suspects_fail_the_paper(tmp_path: Path, scheme: MarkScheme) -> None:
    first = _listed_before_labels(_run(1))
    held = _bind(tmp_path, scheme, _Model(first=_items(first)), second_read=False)
    assert held.report is not None and held.report.verdict == "hold"
    assert ("G5", "paper") in _failed(held)
    g5 = next(c for c in held.report.checks if c.id == "G5")
    assert "2 groups of parts" in g5.detail and "listed before its label" in g5.detail

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
    first, second = _question_4_unanchored(4), _question_4_unanchored(5)
    bad_pair = {"first": _items(first), "second": _items(second)}
    enforced = _bind(tmp_path, scheme, _Model(**bad_pair))
    assert enforced.report is not None and enforced.report.verdict == "hold"

    with _events(EventType.BINDING_GATE_RESULT) as seen:
        outcome = _bind(tmp_path, scheme, _Model(**bad_pair), gate="observe")
    # Watch, change nothing: no report is returned, so nothing downstream can hold.
    assert outcome.report is None
    assert _pairs(outcome) == _bound_alone(first, scheme)
    # The event carries all of it: the verdict enforce would have reached, and the
    # report it would have returned, every check with its sentence.
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert (event["gate"], event["verdict"], event["retried"]) == ("observe", "hold", True)
    assert event["failed_checks"] == ["G5"]
    assert event["report"] == enforced.report.model_dump()
    assert all(check["detail"] for check in event["report"]["checks"])

    # A clean second read is not swapped in: enforce would have used it, and says so.
    model = _Model(first=_items(first), second=_items(_run(1)))
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        outcome = _bind(tmp_path, scheme, model, gate="observe")
    assert outcome.report is None
    assert _pairs(outcome) == _bound_alone(first, scheme)
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert (event["verdict"], event["retried"]) == ("pass", True)
    assert event["failed_checks"] == ["G5"]  # of the read that was returned, the first
    assert all(check["passed"] for check in event["report"]["checks"])  # enforce's: the second

    # Two reads that disagree at paper scope: held under enforce, reported under observe.
    model = _Model(first=_items(_run(1)), second=_items(_with_texts_rotated(_run(1), 6)))
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        outcome = _bind(tmp_path, scheme, model, gate="observe")
    assert outcome.report is None
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert (event["verdict"], event["failed_checks"]) == ("hold", ["G9"])

    # What the binder itself decided still applies: its own doubt about 7b_i stays. What
    # only the gate would add does not: G9 names 2c and 3a, and they are left as bound.
    model = _Model(first=_items(_run(1)), second=_items(_with_texts_rotated(_run(1), 2)))
    outcome = _bind(tmp_path, scheme, model, gate="observe")
    assert [a.question_id for a in outcome.answers if a.binding_status == "unverified"] == ["7b_i"]


def test_observe_mode_leaves_nothing_on_the_extraction_to_hold_on(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    first, second = _question_4_unanchored(4), _question_4_unanchored(5)
    extracted = _extract(
        tmp_path,
        scan,
        scheme,
        _Model(first=_items(first), second=_items(second)),
        gate="observe",
    )
    assert extracted.binding is None
    assert "binding" not in extracted.model_fields_set
    # Leaves with no label still go to a teacher, and writing with no leaf is still kept:
    # those come from the binder, not from the gate.
    assert extracted.dropped_question_ids == ["3c", "4a", "4b_i", "4b_ii", "4b_iii"]
    assert extracted.unbound_answers

    marker = _Marker()
    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=marker
    ):
        result = correct_paper(scheme, extracted, gemini_client=MagicMock())
    assert result.binding is None  # so the post-marking check (G8) is not observed either
    dropped = [q.question_id for q in result.questions if q.marker_source == "dropped"]
    assert dropped == ["3c", "4a", "4b_i", "4b_ii", "4b_iii"]


def test_gate_off_leaves_binding_none(tmp_path: Path, scan: Path, scheme: MarkScheme) -> None:
    first = _without_label(_run(4), "(i)", 9)
    model = _Model(first=_items(first))
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        extracted = _extract(tmp_path, scan, scheme, model, gate="off")

    assert model.made() == ["first"]  # one read, whatever `second_read` says
    assert extracted.binding is None
    assert seen[EventType.BINDING_GATE_RESULT] == []
    assert _pairs(extracted) == _bound_alone(first, scheme)
    assert all(a.binding_source == "label" for a in extracted.answers)
    # Unchecked is not the same as lost: the leaf with no label and the writing with no
    # leaf are both still on the record.
    assert extracted.dropped_question_ids == ["4b_i"]
    assert extracted.unbound_answers


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
