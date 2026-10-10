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
from lemely.io.binding import orchestrate, parse_stream_items, to_bound_read
from lemely.io.binding.label_binder import LabelBinder
from lemely.io.binding.orchestrate import LOST_ITEM_REASONS, BindingOutcome, run_binding
from lemely.io.correction_ai import correct_paper
from lemely.io.gemini import GeminiClient
from lemely.io.rasterise import RasterisedPage
from lemely.runtime.config import BindingSettings, PathsSettings, Settings, load_settings
from lemely.runtime.errors import CostCeilingError, ExternalServiceError, ParseError
from lemely.runtime.events import EventType, bus
from lemely.web.services import grading
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


def test_a_leaf_only_the_other_read_answered_is_marked_from_that_read_and_flagged(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # The first read did not report the block under 5(a) ("0.2 m"); the second did, with
    # no doubt. The first read passes its own checks and is the one used, and in it
    # 5(a) is a label with nothing after it: a blank. It is not one, and it is not left
    # as a zero waiting for a teacher either: the answer one read bound is marked.
    first = _without_items(_run(1), 53)
    with (
        _events(EventType.BINDING_GATE_RESULT) as seen,
        structlog.testing.capture_logs() as logs,
    ):
        extracted = _extract(
            tmp_path, scan, scheme, _Model(first=_items(first), second=_items(_run(1)))
        )
    report = extracted.binding
    assert report is not None
    assert (report.verdict, report.retried) == ("pass", False)
    g9 = report.checks[-1]
    assert (g9.id, g9.passed, g9.scope, g9.question_ids) == ("G9", False, "question", ["5a"])
    assert "answered in one reading of the scan and left blank in the other: 5a" in g9.detail
    # Every leaf holds what the complete read binds, 5(a) among them, in paper order.
    assert _pairs(extracted) == _bound_alone(_run(1), scheme)
    answer = next(a for a in extracted.answers if a.question_id == "5a")
    assert (answer.answer, answer.binding_status) == ("0.2 m", "unverified")
    assert (answer.binding_source, answer.label_seen) == ("label", "(a)")
    # It is an answer now: not a leaf with none, and not writing with no question.
    assert extracted.unbound_question_ids == []
    assert "0.2 m" not in [w.answer for w in extracted.unbound_answers]
    assert extracted.unbound_question_reasons == {"5a": "marked_from_other_read"}
    # Counted on the event and the log line, apart from the leaves that have no answer.
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert (event["unaligned"], event["unbound"]) == (0, 3)
    assert event["marked_from_other_read"] == 1 and event["unaligned_reasons"] == {}
    (line,) = [entry for entry in logs if entry["event"] == "binding_gate_result"]
    assert line["marked_from_other_read"] == 1

    marker = _Marker()
    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=marker
    ):
        result = correct_paper(scheme, extracted, gemini_client=MagicMock())
    row = next(q for q in result.questions if q.question_id == "5a")
    assert "5a" in marker.asked and row.marker_source == "ai"
    assert row.awarded_marks == row.maximum_marks  # the mark is given, and kept
    assert row.needs_teacher_review
    # The reason is the true one, under the prefix other code keys on.
    (reason,) = [r for r in (row.review_reason or "").split(" | ") if "binding" in r]
    assert reason == (
        "binding unverified: this answer was found in only one of two readings of the "
        "scan and is marked from that reading"
    )


def test_a_leaf_unaligned_in_the_returned_read_is_marked_from_the_other_read(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The read that is used missed the label (iii) of 4(b), so 4(b)(iii) has no label
    # and 4(b)(ii), the leaf before the gap, cannot be closed: both are unaligned. The
    # other read has every label and binds both with no doubt.
    first = _without_label(_run(1), "(iii)", 9)
    alone = _bind(tmp_path / "alone", scheme, _Model(first=_items(first)), second_read=False)
    assert alone.review_only_ids == ["4b_ii", "4b_iii"]

    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(_run(1))))
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", False)
    assert outcome.review_only_ids == [] and outcome.review_reasons == {}
    assert outcome.marked_from_other_read == ["4b_ii", "4b_iii"]
    assert _pairs(outcome) == _bound_alone(_run(1), scheme)
    status = {a.question_id: a.binding_status for a in outcome.answers}
    assert status["4b_ii"] == status["4b_iii"] == "unverified"
    # The returned read's own writing under those labels is still kept with no
    # question: nothing says it is the same writing.
    assert len(outcome.unbound) == len(alone.unbound)


def test_a_leaf_the_other_read_doubts_is_not_marked_from_it(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # Recorded reply 3 binds 4(b)(i) with a block tied by an arrow, so its answer there
    # is doubted. The read that is used has nothing under 4(b)(i). A doubted answer from
    # the read that was not returned is not marked: the leaf goes to a teacher as before.
    blocks = _blocks_under(_run(3), "(i)", 9)
    first = _without_items(_run(3), *blocks)
    other = _bind(tmp_path / "other", scheme, _Model(first=_items(_run(3))), second_read=False)
    assert {a.question_id: a.binding_status for a in other.answers}["4b_i"] == "unverified"

    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(_run(3))))
    assert outcome.report.verdict == "pass"
    assert "4b_i" not in {a.question_id for a in outcome.answers}
    assert outcome.review_only_ids == ["4b_i"]
    assert outcome.review_reasons == {"4b_i": "answered_in_one_read_only"}
    assert outcome.marked_from_other_read == []
    kept = [w.answer for w in outcome.unbound]
    assert all(_run(3)[index]["answer"] in kept for index in blocks)


def _with_a_block_after(items: list[Any], index: int, text: str, **fields: Any) -> list[Any]:
    """``items`` with one more block of writing listed straight after the item at ``index``."""
    block = {
        "type": "answer",
        "page": items[index]["page"],
        "box": [1, 1, 5, 5],
        "answer": text,
        "working_out": None,
        "confidence": 0.9,
        "placed_by": "position",
        **fields,
    }
    return [*items[: index + 1], block, *items[index + 1 :]]


def _with_label_before_the_writing_above(items: list[Any], text: str, page: int) -> list[Any]:
    """``items`` with the label ``text`` on ``page`` listed one place early.

    The label then stands before the block of the leaf above it, so that block is read
    as the labelled leaf's, and the leaf above is left with nothing.
    """
    out = list(items)
    at = next(
        index
        for index, item in enumerate(out)
        if item.get("type") == "label" and item.get("text") == text and item.get("page") == page
    )
    assert out[at - 1]["type"] == "answer"
    out[at - 1], out[at] = out[at], out[at - 1]
    return out


def test_writing_the_returned_read_holds_on_another_leaf_is_not_marked_twice(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The student left 7(c) blank. The other read lists the label (c) before the block
    # of 7(b)(ii), so there 7(c) holds 7(b)(ii)'s answer, with no doubt, and 7(b)(ii) is
    # blank. The returned read has it right. Marking 7(c) from the other read would
    # mark 7(b)(ii)'s answer a second time, on a question the student did not answer.
    clean = _run(1)
    second = _with_label_before_the_writing_above(clean, "(c)", 15)
    other = _bound_alone(second, scheme)
    answer_7bii = dict(_bound_alone(clean, scheme))["7b_ii"]
    assert dict(other)["7c"] == answer_7bii and "7b_ii" not in dict(other)

    outcome = _bind(tmp_path, scheme, _Model(first=_items(clean), second=_items(second)))
    assert outcome.report.verdict == "pass"
    by_id = {a.question_id: a for a in outcome.answers}
    assert "7c" not in by_id and outcome.marked_from_other_read == []
    assert outcome.review_only_ids == ["7c"]
    assert outcome.review_reasons == {"7c": "answered_in_one_read_only"}
    assert by_id["7b_ii"].answer == answer_7bii  # where the returned read has it


def test_two_leaves_with_the_same_final_answer_are_told_apart_by_their_working(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # 1(b) and 5(a) end in the same value, by different working. The returned read has
    # nothing under 5(a). What the other read holds there is not the writing the
    # returned read has on 1(b): the whole of each is compared, not the last line.
    both = copy.deepcopy(_run(1))
    both[8].update(answer="0.2 m", working_out="extension = F / k = 2.8 / 14")
    both[53].update(answer="0.2 m", working_out="wavelength = v / f = 340 / 1700")
    first = _without_items(both, 53)
    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(both)))
    assert outcome.report.verdict == "pass"
    assert outcome.marked_from_other_read == ["5a"]
    taken = next(a for a in outcome.answers if a.question_id == "5a")
    assert (taken.answer, taken.working_out) == ("0.2 m", "wavelength = v / f = 340 / 1700")


def test_a_leaf_in_a_group_the_other_read_lists_out_of_order_is_not_marked_from_it(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The returned read has nothing under either part of 1(c). The other read lists the
    # two blocks of 1(c) before their labels, which binds 1(c)(ii)'s answer to 1(c)(i):
    # a group with that trace is never trusted, in whichever read it is.
    first = _without_items(_run(1), 11, 13)
    second = _with_1c_listed_first(_run(1))
    assert dict(_bound_alone(second, scheme))["1c_i"] == _run(1)[13]["answer"]

    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(second)))
    assert outcome.report.verdict == "pass"
    assert "1c_i" not in {a.question_id for a in outcome.answers}
    assert "1c_i" in outcome.review_only_ids and outcome.marked_from_other_read == []


def test_a_leaf_of_a_group_this_read_lists_out_of_order_is_not_marked_from_the_other(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The returned read has a block straight after the label (c) of question 1 and
    # nothing under 1(c)(ii): the trace of writing listed before its label. The other
    # read answers 1(c)(ii) with no doubt, and the returned read holds that writing on
    # no leaf. The group is trusted in neither direction all the same: 1(c)(ii) goes to
    # a teacher unmarked, as the leaf left with nothing in such a group always has.
    first = _with_a_block_after(_without_items(_run(1), 13), 9, "a line under the heading")
    assert first[9]["type"] == "label" and first[9]["text"] == "(c)"
    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(_run(1))))
    assert outcome.report.verdict == "pass"
    assert outcome.review_reasons == {"1c_ii": "listing_suspect"}
    assert "1c_ii" not in {a.question_id for a in outcome.answers}
    assert outcome.marked_from_other_read == []


def test_nothing_is_marked_from_a_read_that_failed_its_own_checks(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The first read lost an item of its reply and fails; the second read is returned.
    # It has nothing under 5(a), where the first read has "0.2 m". A read that failed at
    # paper scope is not a witness for any single leaf.
    first = _with_an_item_lost(_run(1), 60)
    second = _without_items(_run(1), 53)
    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(second)))
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", True)
    assert "5a" not in {a.question_id for a in outcome.answers}
    assert outcome.review_only_ids == ["5a"] and outcome.marked_from_other_read == []


# --------------------------------------------------------------------------------------
# A second read that saw the next question's number
# --------------------------------------------------------------------------------------
def _statuses(outcome: BindingOutcome | ExtractedAnswers) -> dict[str, str | None]:
    return {a.question_id: a.binding_status for a in outcome.answers}


def _with_arrow(items: list[Any], index: int) -> list[Any]:
    out = copy.deepcopy(items)
    assert out[index]["type"] == "answer"
    out[index]["placed_by"] = "arrow"
    return out


def _uncertain_blocks(items: list[Any]) -> list[int]:
    return [
        index
        for index, item in enumerate(items)
        if item.get("type") == "answer" and item.get("placed_by") == "uncertain"
    ]


def test_a_second_read_that_saw_the_next_number_clears_that_doubt(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # Recorded reply 4 lacks the label `4` (the student ringed the printed number), so
    # nothing in it closes 3(c), the last part of question 3: its answer is doubted.
    # Recorded reply 1 has the label and binds the same block to 3(c) with no doubt.
    alone = _bind(tmp_path / "alone", scheme, _Model(first=_items(_run(4))), second_read=False)
    assert _statuses(alone)["3c"] == "unverified"
    model = _Model(first=_items(_run(4)), second=_items(_run(1)))
    extracted = _extract(tmp_path, scan, scheme, model)
    assert extracted.binding is not None and extracted.binding.verdict == "pass"
    assert not extracted.binding.retried
    assert _pairs(extracted) == _pairs(alone)  # the answers are the returned read's
    after = _statuses(extracted)
    assert after["3c"] == "verified"
    # Nothing else moves: the arrow doubt on 4(b)(i) is not this doubt.
    assert after["4b_i"] == "unverified"
    assert {q for q in after if after[q] != _statuses(alone)[q]} == {"3c"}

    marker = _Marker()
    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=marker
    ):
        result = correct_paper(scheme, extracted, gemini_client=MagicMock())
    row = next(q for q in result.questions if q.question_id == "3c")
    assert "binding unverified" not in (row.review_reason or "")


def test_the_doubt_stays_when_neither_read_saw_the_next_number(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # Replies 4 and 5 both lack the label `4`. Two reads that hold the same block and
    # both lack the label agree on nothing that closes the leaf.
    plain = _without_items(_run(5), *_uncertain_blocks(_run(5)))
    outcome = _bind(tmp_path, scheme, _Model(first=_items(_run(4)), second=_items(plain)))
    assert outcome.report.verdict == "pass"
    assert _statuses(outcome)["3c"] == "unverified"


def test_the_doubt_stays_when_the_other_read_holds_other_blocks_on_the_leaf(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The student wrote a line under the heading of question 4. The read that missed
    # the label `4` lists it straight after 3(c)'s answer, so 3(c) holds it: the case
    # the doubt exists for. The read that saw the label lists the line after the label,
    # so there 3(c) holds its own answer alone. The two reads do not hold the same
    # blocks on 3(c), and the doubt is not cleared.
    line = "heat capacity is the energy needed to warm the whole object by one degree"
    first = _with_a_block_after(_run(4), 39, line)
    second = _with_a_block_after(_run(1), 40, line)
    assert first[39]["type"] == "answer" and second[40]["text"] == "4"
    outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(second)))
    assert outcome.report.verdict == "pass"
    held = next(a for a in outcome.answers if a.question_id == "3c")
    assert line in held.answer and held.binding_status == "unverified"

    # The same when it is the other read that holds more on the leaf than this one.
    mirror = _bind(
        tmp_path / "mirror",
        scheme,
        _Model(first=_items(_run(4)), second=_items(_with_a_block_after(_run(1), 39, line))),
    )
    assert _statuses(mirror)["3c"] == "unverified"


def test_the_doubt_stays_when_the_other_read_doubts_the_leaf_or_failed_its_checks(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The other read saw the label `4` and ties 3(c)'s block by an arrow: it doubts
    # what the leaf holds, so it clears nothing.
    arrow = _with_arrow(_run(1), 39)
    outcome = _bind(tmp_path, scheme, _Model(first=_items(_run(4)), second=_items(arrow)))
    assert _statuses(outcome)["3c"] == "unverified"

    # The other read lost an item of its reply and fails its own checks: it is not a
    # witness for a single leaf.
    lost = _with_an_item_lost(_run(1), 60)
    outcome = _bind(tmp_path / "lost", scheme, _Model(first=_items(_run(4)), second=_items(lost)))
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", False)
    assert _statuses(outcome)["3c"] == "unverified"


def test_only_the_next_number_doubt_is_cleared_by_the_other_read(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # A leaf that carries another content doubt beside it stays doubted: here 3(c)'s
    # block is tied by an arrow in the read that missed the label.
    both = _with_arrow(_run(4), 39)
    outcome = _bind(tmp_path, scheme, _Model(first=_items(both), second=_items(_run(1))))
    assert _statuses(outcome)["3c"] == "unverified"

    # And an arrow doubt alone is not cleared by a read that lists the same block
    # without the mark: that read has not seen more of the arrow, it has reported less.
    marked = _bind(
        tmp_path / "arrow-only",
        scheme,
        _Model(first=_items(_with_arrow(_run(1), 39)), second=_items(_run(1))),
    )
    assert _statuses(marked)["3c"] == "unverified"

    # A gate rule that names the leaf keeps it doubted whatever the other read saw:
    # here the other read has nothing under 3(c).
    lopsided = _bind(
        tmp_path / "one-read",
        scheme,
        _Model(first=_items(_run(4)), second=_items(_without_items(_run(1), 39))),
    )
    assert _statuses(lopsided)["3c"] == "unverified"


def test_a_block_is_found_in_a_text_by_the_runs_they_share() -> None:
    found = orchestrate._share_found
    assert found("total upward force", "total upward force is equal") == 1.0
    # What one reader words a little differently from another is still found.
    assert found("1. total upward forces equal to", "1 total upward force is equal to") >= 0.8
    # Letters two texts happen to share, one or two at a time, are not: a block of
    # other writing is not found in a text because both are made of the same alphabet.
    assert found("abcdefgh", "a b c d e f g h") == 0.0
    assert found("the current falls", "heat is lost to the air") < 0.5
    # A short block is found by a run of two, and a block of one by itself.
    assert found("63", "1. 43 cm 2. 63 cm") == 1.0
    assert found("63", "6 and 3") == 0.0
    assert found("B", "B") == 1.0 and found("", "anything") == 1.0


def test_a_gate_rule_that_names_a_leaf_wins_over_the_cleared_doubt(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The two never meet on the recorded replies, so the rule is pinned where it is
    # applied: an answer both cleared and named by a check stays doubted.
    alone = _bind(tmp_path, scheme, _Model(first=_items(_run(4))), second_read=False)
    answers = [a for a in alone.answers if a.question_id in ("3b_ii", "3c")]
    assert [a.binding_status for a in answers] == ["verified", "unverified"]
    both = orchestrate._with_statuses(answers, frozenset({"3c"}), frozenset({"3c"}))
    assert [a.binding_status for a in both] == ["verified", "unverified"]
    cleared = orchestrate._with_statuses(answers, frozenset(), frozenset({"3c"}))
    assert [a.binding_status for a in cleared] == ["verified", "verified"]
    named = orchestrate._with_statuses(answers, frozenset({"3b_ii"}), frozenset({"3c"}))
    assert [a.binding_status for a in named] == ["unverified", "verified"]


def test_the_gate_is_told_why_each_leaf_is_unaligned(tmp_path: Path, scheme: MarkScheme) -> None:
    # Two blocks under 7(b)(ii) and nothing under 7(c): the binder cannot tell whose the
    # second block is and binds neither leaf. Both labels have their place, so no label
    # was missed and 7(b)(i), the answer before the gap, ends at the label (ii): G5
    # does not name it, which it can do only when it is given the reasons.
    two_blocks = _with_a_block_after(_run(1), 82, "V = I R, so the current falls")
    for name, second in (("alone", None), ("both", two_blocks)):
        model = _Model(first=_items(two_blocks), second=_items(second or []))
        outcome = _bind(tmp_path / name, scheme, model, second_read=second is not None)
        assert outcome.report.verdict == "pass"
        assert outcome.review_reasons == {
            "7b_ii": "neighbour_left_blank",
            "7c": "neighbour_left_blank",
        }
        g5 = next(c for c in outcome.report.checks if c.id == "G5")
        assert (g5.passed, g5.scope, g5.question_ids) == (False, "question", ["7b_ii", "7c"])
        assert _statuses(outcome)["7b_i"] == _statuses_alone(_run(1), scheme)["7b_i"]

    # Where a label of the gap was missed, the answer before the gap is still named.
    missed = _without_label(_run(1), "(iii)", 9)
    outcome = _bind(tmp_path / "missed", scheme, _Model(first=_items(missed)), second_read=False)
    g5 = next(c for c in outcome.report.checks if c.id == "G5")
    assert g5.question_ids == ["4b_i", "4b_ii", "4b_iii"]
    assert _statuses(outcome)["4b_i"] == "unverified"


def _statuses_alone(items: list[Any], scheme: MarkScheme) -> dict[str, str | None]:
    stream = parse_stream_items(items, page_count=_PAGE_COUNT)
    read = to_bound_read(
        bind_stream(stream.items, scheme), page_count=_PAGE_COUNT, drops=stream.drops
    )
    return {a.question_id: a.binding_status for a in read.answers}


# --------------------------------------------------------------------------------------
# Parts a student skipped on a handwritten sheet
# --------------------------------------------------------------------------------------
def _as_a_sheet(
    items: list[Any], *skipped: tuple[str, int], kind: str = "handwritten"
) -> list[Any]:
    """``items`` as a sheet the student labelled by ``kind``, without the ``skipped`` parts.

    A skipped part is named by its label and page; its label and the writing under it
    are left out, as when the student did not attempt it and wrote no label for it.
    """
    out: list[Any] = []
    leaving_out = False
    for item in copy.deepcopy(items):
        if item["type"] == "label":
            item["kind"] = kind
            leaving_out = (item["text"], item["page"]) in skipped
        if not leaving_out:
            out.append(item)
    return out


_THREE_PARTS = (("(b)", 2), ("(b)", 10), ("(b)", 12))  # 1(b), 5(b), 6(b)
_SIX_LEAVES = {
    "1a_ii": "not_bracketed",
    "1b": "label_not_seen",
    "5a": "not_bracketed",
    "5b": "label_not_seen",
    "6a": "not_bracketed",
    "6b": "label_not_seen",
}


def test_parts_skipped_on_a_handwritten_sheet_do_not_hold_the_paper(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # Three parts with no label in either read, between labels written by hand. Each
    # costs its own leaf and the answered leaf before it: six of 43, over G5's limit of
    # a tenth, with nothing bound wrongly. The gate is given both reads, so it can tell
    # these from labels a reader missed, and leaves them out of the rate.
    sheet = _as_a_sheet(_run(1), *_THREE_PARTS)
    with (
        _events(EventType.BINDING_GATE_RESULT) as seen,
        structlog.testing.capture_logs() as logs,
    ):
        outcome = _bind(tmp_path, scheme, _Model(first=_items(sheet), second=_items(sheet)))
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", False)
    g5 = next(c for c in outcome.report.checks if c.id == "G5")
    assert (g5.passed, g5.scope) == (False, "question")
    # All six still go to a teacher, each with its reason, and none is marked.
    assert outcome.review_reasons == _SIX_LEAVES
    assert not set(_SIX_LEAVES) & {a.question_id for a in outcome.answers}
    assert outcome.marked_from_other_read == []
    # The count of parts left out of the rate is on the event and on the log line.
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    (line,) = [entry for entry in logs if entry["event"] == "binding_gate_result"]
    assert event["skipped_parts"] == line["skipped_parts"] == 3
    assert (event["unaligned"], line["unaligned"]) == (6, 6)


def test_with_one_read_or_printed_labels_the_same_gaps_hold_the_paper(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    sheet = _as_a_sheet(_run(1), *_THREE_PARTS)
    # One read cannot tell a skipped part from a missed label: nothing is left out.
    alone = _bind(tmp_path / "alone", scheme, _Model(first=_items(sheet)), second_read=False)
    assert alone.report.verdict == "hold" and _failed(alone) == [("G5", "paper")]
    # Between printed labels a label is missing because the reader missed it.
    printed = _as_a_sheet(_run(1), *_THREE_PARTS, kind="printed")
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        held = _bind(
            tmp_path / "printed", scheme, _Model(first=_items(printed), second=_items(printed))
        )
    assert held.report.verdict == "hold" and ("G5", "paper") in _failed(held)
    assert seen[EventType.BINDING_GATE_RESULT][0]["skipped_parts"] == 0


def test_the_second_read_is_excused_its_skipped_parts_too(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The first read lost an item of its reply and fails. The second read is the same
    # sheet with nothing lost: it passes only because its three skipped parts, which the
    # first read lacks too, are left out of its rate as well.
    sheet = _as_a_sheet(_run(1), *_THREE_PARTS)
    # The first read also lists a label no question accounts for: a list that shows
    # anything beside absent labels is excused nothing, so its own count is 0.
    stray = {"type": "label", "page": 18, "box": [1, 1, 5, 5], "text": "(q)", "kind": "handwritten"}
    lost = [*sheet[:40], "not an item", *sheet[40:], stray]
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        outcome = _bind(tmp_path, scheme, _Model(first=_items(lost), second=_items(sheet)))
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", True)
    assert outcome.review_reasons == _SIX_LEAVES
    # The count published is the returned read's.
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert event["skipped_parts"] == 3


def test_a_label_the_other_read_saw_is_not_a_skipped_part(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The first read has no label for four parts; the second read has every one of
    # them. They are labels the first reader missed, so the first read is over the
    # limit and fails, and the complete second read is the one returned.
    four = (*_THREE_PARTS, ("(b)", 18))
    first, second = _as_a_sheet(_run(1), *four), _as_a_sheet(_run(1))
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        outcome = _bind(tmp_path, scheme, _Model(first=_items(first), second=_items(second)))
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", True)
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert event["skipped_parts"] == 0
    assert [c["id"] for c in event["first_read_failed_checks"]] == ["G5"]
    assert _pairs(outcome) == _bound_alone(second, scheme)


def test_a_held_paper_takes_nothing_from_the_other_read(tmp_path: Path, scheme: MarkScheme) -> None:
    # Five leaves answered in one read only hold the paper. Held, its record is the
    # returned read's: nothing is marked on it, so nothing is taken from the other read.
    five = _without_items(_run(1), 8, 18, 22, 29, 53)
    held = _bind(tmp_path, scheme, _Model(first=_items(five), second=_items(_run(1))))
    assert held.report.verdict == "hold"
    assert held.review_only_ids == ["1b", "2a_i", "2a_iii", "2c", "5a"]
    assert held.marked_from_other_read == []


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


def _crashing_after_the_second_read(crashes: list[Exception]) -> Any:
    """``LabelBinder.read`` that, for the second read, gets the reply and then crashes.

    The reply is in the response cache by then: this is a bug in parsing or binding it.
    One crash is taken from ``crashes`` per second read, until there are none.
    """
    real = LabelBinder.read

    def _read(self: LabelBinder, *args: Any, **kwargs: Any) -> Any:
        stream = real(self, *args, **kwargs)
        if kwargs["task_tag"] == "binding_second_read" and crashes:
            raise crashes.pop(0)
        return stream

    return patch.object(LabelBinder, "read", _read)


def test_a_second_read_that_crashed_is_made_again_by_a_model_call(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # The reply the crash came from is cached. "Once more" from the cache would be the
    # same reply and the same crash: the second attempt has to ask the model.
    client, genai = _client(tmp_path)
    genai.models.generate_content.return_value = _sdk_reply(_items(_run(1)))
    with _crashing_after_the_second_read([RuntimeError("a bug in parsing the reply")]):
        outcome = _bind_for_real(client, scheme)
    assert outcome.report.verdict == "pass" and outcome.report.checks[-1].id == "G9"
    # First read, second read, second read again.
    assert genai.models.generate_content.call_count == 3
    cache_dir = client._settings.paths.cache_dir / "gemini"
    assert sorted(p.stem for p in cache_dir.glob("*.json")) == sorted(outcome.read_cache_keys)

    # The same when it crashes again: three calls, the job fails, nothing stays cached.
    other, other_genai = _client(tmp_path / "twice")
    other_genai.models.generate_content.return_value = _sdk_reply(_items(_run(1)))
    crashes: list[Exception] = [RuntimeError("a bug"), RuntimeError("the same bug")]
    with _crashing_after_the_second_read(crashes), pytest.raises(ExternalServiceError):
        _bind_for_real(other, scheme)
    assert other_genai.models.generate_content.call_count == 3
    assert list((other._settings.paths.cache_dir / "gemini").glob("*.json")) == []


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
    # The reader missed the label (i) of 4(b), in both reads: leaf 4b_i has no label to
    # bind to, and no read holds an answer for it.
    first = _without_label(_run(4), "(i)", 9)
    model = _Model(first=_items(first), second=_items(first))
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
    reason = (
        "binding unverified: this answer may include writing that belongs to another "
        "question, or may be missing some of its own"
    )
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


def _with_writing_under_text(items: list[Any], *indexes: int) -> list[Any]:
    """``items`` with the answer items at ``indexes`` returned the way the reader slips.

    The writing is under ``text`` and there is no ``answer``: the shape of 8 answer
    items in 6 of 18 stored readings of this script.
    """
    out = copy.deepcopy(items)
    for index in indexes:
        assert out[index]["type"] == "answer" and out[index]["answer"].strip()
        out[index]["text"] = out[index].pop("answer")
    return out


def test_writing_the_reader_put_under_text_binds_and_costs_the_paper_nothing(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # In the stored runs this slip cost 3(a) in one (the item was dropped, so the leaf
    # had writing in one read only and went to review unmarked) and the body of
    # 4(b)(i) in another (the leaf was marked on its last sentence alone).
    clean = _run(1)
    (at_3a,) = _blocks_under(clean, "(a)", 6)
    (body_4bi,) = _blocks_under(clean, "(i)", 9)
    slipped = _with_writing_under_text(clean, at_3a, body_4bi)
    model = _Model(first=_items(slipped), second=_items(clean))
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        extracted = _extract(tmp_path, scan, scheme, model)

    both_clean = _Model(first=_items(clean), second=_items(clean))
    reference = _extract(tmp_path / "ref", scan, scheme, both_clean)
    assert extracted.binding is not None and extracted.binding.verdict == "pass"
    assert not extracted.binding.retried  # the first read is the one returned
    # Every leaf holds what it holds when the reader makes no slip: 3(a) is bound and
    # marked, and 4(b)(i) is whole.
    assert _pairs(extracted) == _pairs(reference)
    by_id = {a.question_id: a for a in extracted.answers}
    assert by_id["3a"].answer == clean[at_3a]["answer"]
    assert clean[body_4bi]["answer"] in by_id["4b_i"].answer
    assert extracted.unbound_question_ids == reference.unbound_question_ids == []
    assert [a.question_id for a in extracted.answers if a.binding_status == "unverified"] == [
        a.question_id for a in reference.answers if a.binding_status == "unverified"
    ]
    # The repair is on the record and on the log line, and is not a lost item.
    assert extracted.answer_drops == {"stream_answer_under_text": 2}
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert event["drops"] == {"answer_under_text": 2}
    assert "answer_under_text" not in LOST_ITEM_REASONS
    g5 = next(c for c in extracted.binding.checks if c.id == "G5")
    assert g5.passed


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


def _flat_scheme(*, written: tuple[str, ...] = ()) -> MarkScheme:
    """0625/12 March 2019: forty multiple-choice questions, no parts.

    The ids in ``written`` are turned into written questions (not multiple choice).
    """
    data = json.loads(
        (_ROOT / "corpus" / "mark-schemes" / "0625_m19_ms_12.json").read_text(encoding="utf-8")
    )
    for question in data["questions"]:
        if question["id"] in written:
            question.update(type="recall", mcq_answer=None)
            question["answer_points"] = [{"id": "p1", "marks": 1, "point": "a written answer"}]
    return MarkScheme.model_validate(data)


def test_a_scheme_that_is_all_multiple_choice_keeps_the_legacy_binder(
    tmp_path: Path, scan: Path
) -> None:
    # The label binder has been read live on one theory paper. A paper shape it has never
    # read keeps the behaviour it had before the binder: the legacy call, gated as
    # configured. That is a rule in code, whatever `binding.binder` says.
    flat = _flat_scheme()
    leaves = [q.id for q in flat.all_questions_flat() if not q.parts]
    assert len(leaves) == 40
    letters = {
        "answers": [
            {"question_id": leaf, "answer": "ABCD"[i % 4], "confidence": 0.9}
            for i, leaf in enumerate(leaves)
        ]
    }
    model = _Model(legacy=letters)  # a label read would find no reply and fail the test
    with (
        _events(EventType.BINDING_GATE_RESULT) as seen,
        structlog.testing.capture_logs() as logs,
    ):
        extracted = _extract(tmp_path, scan, flat, model)  # default settings: label, enforce

    assert model.made() == ["legacy"]
    assert BindingSettings().binder == "label"
    report = extracted.binding
    assert report is not None
    assert (report.binder, report.verdict, report.retried) == ("legacy", "pass", False)
    assert {c.id for c in report.checks} == {"G1", "G2", "G6", "G7"}
    assert len(extracted.answers) == 40
    assert all(a.binding_source == "legacy" for a in extracted.answers)
    # The log line says the binder was chosen by the paper's shape, so that the hold
    # rate can be read per path.
    (line,) = [entry for entry in logs if entry["event"] == "binding_gate_result"]
    assert (line["binder"], line["binder_by_paper_shape"]) == ("legacy", True)
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert event["binder_by_paper_shape"] is True

    # Gated as configured: an id that is not in the scheme fails G1, the call is made
    # once more on the retry model, and the paper is held.
    wrong = {
        "answers": [*letters["answers"], {"question_id": "41", "answer": "A", "confidence": 0.9}]
    }
    model = _Model(legacy=wrong, retry=copy.deepcopy(wrong))
    held = _extract(tmp_path, scan, flat, model)
    assert model.made() == ["legacy", "retry"]
    assert held.binding is not None
    assert (held.binding.binder, held.binding.verdict, held.binding.retried) == (
        "legacy",
        "hold",
        True,
    )


def test_a_scheme_with_one_written_question_uses_the_label_binder(
    tmp_path: Path, scan: Path
) -> None:
    mixed = _flat_scheme(written=("17",))
    leaves = [q.id for q in mixed.all_questions_flat() if not q.parts]
    reply = _flat_reply(leaves, name=None, blank=set())
    model = _Model(first=_items(reply), second=_items(reply))
    with structlog.testing.capture_logs() as logs:
        extracted = _extract(tmp_path, scan, mixed, model)
    assert model.made() == ["first", "second"]
    assert extracted.binding is not None and extracted.binding.binder == "label"
    (line,) = [entry for entry in logs if entry["event"] == "binding_gate_result"]
    assert (line["binder"], line["binder_by_paper_shape"]) == ("label", False)


def test_the_label_binder_is_not_run_on_an_all_multiple_choice_scheme(tmp_path: Path) -> None:
    # `run_binding` is the label binder. Called for a paper shape the rule keeps on the
    # legacy path it refuses, so that nothing can take the rule's place by calling it.
    flat = _flat_scheme()
    reply = _flat_reply([q.id for q in flat.all_questions_flat()], name=None, blank=set())
    client, _genai = _client(tmp_path)
    pages = _pages(6)
    model = _Model(first=_items(reply), second=_items(reply))
    with (
        client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
        patch.object(client, "generate_structured", side_effect=model),
        pytest.raises(ValueError, match="multiple choice"),
    ):
        run_binding(
            client, pages, flat, uploads=uploads, settings=client._settings, manifest_key="m"
        )
    assert model.calls == []


def test_one_suspect_trace_on_a_flat_paper_sends_every_answer_to_review(tmp_path: Path) -> None:
    # A paper of forty questions and no parts. The student wrote a name above question 1
    # and left question 40 blank; both reads list everything in order and every answer
    # is on its own question. But a block before the first label and the last question
    # blank is exactly what the whole paper listed one out looks like, and on a paper
    # with no parts the group that trace names is the whole paper. The cost is accepted:
    # every answer is marked, keeps its marks and is flagged, and question 40 goes to a
    # teacher. No flat paper has a recorded reply, so how often a reader reports writing
    # above the first label is not known.
    #
    # One question (17) is a written one here: a scheme that is all multiple choice does
    # not reach the label binder at all (it keeps the legacy binder), so the same trace
    # on the real all-multiple-choice scheme is pinned on the gate functions, in
    # tests/test_binding_gate.py.
    flat = _flat_scheme(written=("17",))
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
    # The legacy binder is here because the settings ask for it, not by the paper's shape.
    assert event["binder_by_paper_shape"] is False

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
        "binder_by_paper_shape": False,
        "marked_from_other_read": 0,
        "skipped_parts": 0,
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
        # The reader missed the label (i) of 4(b), in both reads.
        "label missed": (
            _without_label(_run(4), "(i)", 9),
            _without_label(_run(4), "(i)", 9),
            {"4b_i": "label_not_seen"},
        ),
        # The read that is used has nothing under 4(b)(i); the other read has an answer
        # there that it doubts itself (a block tied by an arrow), so it is not marked.
        "answered in the other read only": (
            _without_items(_run(3), *_blocks_under(_run(3), "(i)", 9)),
            _run(3),
            {"4b_i": "answered_in_one_read_only"},
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
        "binder_by_paper_shape": False,
        "marked_from_other_read": 0,
        "skipped_parts": 0,
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


def test_a_held_paper_skips_the_later_extraction_steps(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # The paper is held: it will not be marked. The optional text second reader and
    # the crop re-reads would each be a paid call on answers nobody is going to use.
    from lemely.io.reread import should_reread

    held_reply = copy.deepcopy(_question_4_unanchored(4))
    for item in held_reply:
        if item.get("type") == "answer":
            item["confidence"] = 0.1  # every answer is one a re-read would be spent on
    settings = _settings(tmp_path)
    settings = settings.model_copy(
        update={"gemini": settings.gemini.model_copy(update={"second_reader": "cross_model"})}
    )
    client = GeminiClient(settings, _genai_client=fake_genai_client())
    model = _Model(first=_items(held_reply), second=_items(held_reply))
    with patch.object(client, "generate_structured", side_effect=model):
        extracted = GeminiAnswerExtractor(client)(scan_path=scan, mark_scheme=scheme)

    assert extracted.binding is not None and extracted.binding.verdict == "hold"
    # Nothing but the two reads was asked of the model.
    assert [(call["task_tag"], call["response_schema"].__name__) for call in model.calls] in (
        [("extraction", "_StreamOutput"), ("binding_second_read", "_StreamOutput")],
        [("binding_second_read", "_StreamOutput"), ("extraction", "_StreamOutput")],
    )
    assert any(should_reread(answer) for answer in extracted.answers)  # there was work to skip
    assert (extracted.rereads_eligible, extracted.reread_attempts) == (0, 0)
    assert all(
        a.answer_reread is None and a.extraction_agreement is None for a in extracted.answers
    )

    # The same for a paper the legacy binder's gate holds.
    shifted = _legacy_reply("full_shift_lite")
    for answer in shifted["answers"]:
        answer["confidence"] = 0.1
    settings = _settings(tmp_path, binder="legacy")
    settings = settings.model_copy(
        update={"gemini": settings.gemini.model_copy(update={"second_reader": "cross_model"})}
    )
    client = GeminiClient(settings, _genai_client=fake_genai_client())
    model = _Model(legacy=shifted, retry=copy.deepcopy(shifted))
    with patch.object(client, "generate_structured", side_effect=model):
        extracted = GeminiAnswerExtractor(client)(scan_path=scan, mark_scheme=scheme)
    assert extracted.binding is not None and extracted.binding.verdict == "hold"
    assert model.made() == ["legacy", "retry"]
    assert (extracted.rereads_eligible, extracted.reread_attempts) == (0, 0)


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

    # Run again while the reader still shifts the paper: the call AND its retry are made
    # afresh, neither is replayed.
    held_again = extractor(scan_path=scan, mark_scheme=scheme)
    assert held_again.binding is not None and held_again.binding.verdict == "hold"
    assert genai.models.generate_content.call_count == 4

    # Run once more, and this time the reader has it right: the first call is fresh, it
    # passes, and no retry is needed.
    genai.models.generate_content.return_value = _sdk_reply(_legacy_reply("aligned"))
    passed = extractor(scan_path=scan, mark_scheme=scheme)
    assert genai.models.generate_content.call_count == 5
    assert passed.binding is not None
    assert (passed.binding.verdict, passed.binding.retried) == ("pass", False)

    # And a legacy paper that passed stays cached.
    extractor(scan_path=scan, mark_scheme=scheme)
    assert genai.models.generate_content.call_count == 5


class _Judge:
    """Stands in for ``AICorrector.mark_question``: every answer judged with ``says``."""

    def __init__(self, says: str) -> None:
        self.says = says

    def __call__(self, _self: object, question: Question, *_a: object, **_k: object) -> Any:
        return AIMarkResponse.model_validate(
            {
                "awarded_marks": 0,
                "confidence": 0.95,
                "matched_point_ids": [],
                "feedback": "fb",
                "addresses_question": self.says,
            }
        )


def _marked(client: GeminiClient, scheme: MarkScheme, extracted: ExtractedAnswers, says: str):
    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=_Judge(says)
    ):
        return correct_paper(scheme, extracted, gemini_client=client)


@pytest.mark.parametrize("binder", ["label", "legacy"])
def test_a_paper_held_after_marking_does_not_pin_its_reads_in_the_cache(
    tmp_path: Path, scan: Path, scheme: MarkScheme, binder: str
) -> None:
    # The binding passes its checks before marking; then the marker says answer after
    # answer does not address its question, and G8 holds the paper. A re-run that got
    # the same reads back from the cache would get the same marking back too, and the
    # same hold, for as long as the instance lived.
    client, genai = _client(tmp_path, binder=binder)
    body = _items(_run(1)) if binder == "label" else _legacy_reply("aligned")
    reads = 2 if binder == "label" else 1
    genai.models.generate_content.return_value = _sdk_reply(body)
    extractor = GeminiAnswerExtractor(client, max_rereads_per_paper=0)

    extracted = extractor(scan_path=scan, mark_scheme=scheme)
    assert extracted.binding is not None and extracted.binding.verdict == "pass"
    assert genai.models.generate_content.call_count == reads

    held = _marked(client, scheme, extracted, "no")
    assert held.binding is not None and held.binding.verdict == "hold"
    assert genai.models.generate_content.call_count == reads  # the marker here is a fake

    # Run again on the same scan: it is read afresh.
    extractor(scan_path=scan, mark_scheme=scheme)
    assert genai.models.generate_content.call_count == 2 * reads


@pytest.mark.parametrize("binder", ["label", "legacy"])
def test_a_paper_that_passed_marking_too_is_served_from_the_cache_on_a_re_run(
    tmp_path: Path, scan: Path, scheme: MarkScheme, binder: str
) -> None:
    client, genai = _client(tmp_path, binder=binder)
    body = _items(_run(1)) if binder == "label" else _legacy_reply("aligned")
    reads = 2 if binder == "label" else 1
    genai.models.generate_content.return_value = _sdk_reply(body)
    extractor = GeminiAnswerExtractor(client, max_rereads_per_paper=0)

    extracted = extractor(scan_path=scan, mark_scheme=scheme)
    passed = _marked(client, scheme, extracted, "yes")
    assert passed.binding is not None and passed.binding.verdict == "pass"

    again = extractor(scan_path=scan, mark_scheme=scheme)
    assert genai.models.generate_content.call_count == reads  # no model call
    assert _pairs(again) == _pairs(extracted)


def test_the_keys_of_the_reads_travel_on_the_extraction_and_are_never_serialised(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    client, genai = _client(tmp_path)
    genai.models.generate_content.return_value = _sdk_reply(_items(_run(1)))
    extracted = GeminiAnswerExtractor(client, max_rereads_per_paper=0)(
        scan_path=scan, mark_scheme=scheme
    )
    keys = extracted.read_cache_keys()
    assert len(keys) == 2 and len(set(keys)) == 2
    cache_dir = client._settings.paths.cache_dir / "gemini"
    assert sorted(path.stem for path in cache_dir.glob("*.json")) == sorted(keys)
    # They are for this process only: nothing of them is in what is stored or sent.
    dumped = json.dumps(extracted.model_dump(mode="json")) + extracted.model_dump_json()
    assert not any(key in dumped for key in keys) and "cache" not in dumped
    assert ExtractedAnswers.model_validate(extracted.model_dump()).read_cache_keys() == ()
    # A copy keeps them; an extraction built by hand has none, and holding it forgets nothing.
    assert extracted.model_copy(update={"source_scan": "x"}).read_cache_keys() == keys
    by_hand = ExtractedAnswers.model_validate(extracted.model_dump())
    held = _marked(client, scheme, by_hand, "no")
    assert held.binding is not None and held.binding.verdict == "hold"
    assert len(list(cache_dir.glob("*.json"))) == 2
    # Forgetting says how many entries were there; a key with none is passed over.
    assert client.forget_cached([keys[0], "0" * 16]) == 1
    assert [path.stem for path in cache_dir.glob("*.json")] == [keys[1]]


@pytest.mark.parametrize(("mode", "left"), [("bypass", 2), ("refresh", 0), ("read_write", 0)])
def test_a_hold_after_marking_forgets_reads_only_through_a_client_that_writes_the_cache(
    tmp_path: Path, scan: Path, scheme: MarkScheme, mode: Any, left: int
) -> None:
    # A client in "bypass" mode leaves the shared cache as it found it: that is what
    # the mode is for (a churn measurement beside a baseline that another run wrote).
    # So a paper it holds must not cost the other run its two reads.
    writer, genai = _client(tmp_path)
    genai.models.generate_content.return_value = _sdk_reply(_items(_run(1)))
    GeminiAnswerExtractor(writer, max_rereads_per_paper=0)(scan_path=scan, mark_scheme=scheme)
    cache_dir = writer._settings.paths.cache_dir / "gemini"
    assert len(list(cache_dir.glob("*.json"))) == 2

    other = GeminiClient(writer._settings, _genai_client=genai, default_cache_mode=mode)
    extracted = GeminiAnswerExtractor(other, max_rereads_per_paper=0)(
        scan_path=scan, mark_scheme=scheme
    )
    assert len(extracted.read_cache_keys()) == 2
    assert len(list(cache_dir.glob("*.json"))) == 2
    held = _marked(other, scheme, extracted, "no")
    assert held.binding is not None and held.binding.verdict == "hold"
    assert len(list(cache_dir.glob("*.json"))) == left


@pytest.mark.parametrize(("mode", "left"), [("bypass", 2), ("refresh", 0)])
def test_a_hold_before_marking_forgets_reads_only_through_a_client_that_writes_the_cache(
    tmp_path: Path, scheme: MarkScheme, mode: Any, left: int
) -> None:
    writer, genai = _client(tmp_path)
    genai.models.generate_content.return_value = _sdk_reply(_items(_run(1)))
    passed = _bind_for_real(writer, scheme)
    cache_dir = writer._settings.paths.cache_dir / "gemini"
    assert sorted(p.stem for p in cache_dir.glob("*.json")) == sorted(passed.read_cache_keys)

    # The same paper through another client: this time the reader misses labels.
    other = GeminiClient(writer._settings, _genai_client=genai, default_cache_mode=mode)
    genai.models.generate_content.return_value = _sdk_reply(_items(_question_4_unanchored(4)))
    held = _bind_for_real(other, scheme)
    assert held.report.verdict == "hold"
    assert genai.models.generate_content.call_count == 4
    assert len(list(cache_dir.glob("*.json"))) == left
    # Asked directly, the bypassing client says it removed nothing.
    if mode == "bypass":
        assert other.forget_cached(passed.read_cache_keys) == 0
        assert len(list(cache_dir.glob("*.json"))) == 2
        # A job that fails through it leaves the entries too.
        genai.models.generate_content.side_effect = ExternalServiceError("down")
        with pytest.raises(ExternalServiceError):
            _bind_for_real(other, scheme)
        assert len(list(cache_dir.glob("*.json"))) == 2


def test_the_upload_jobs_read_a_paper_held_after_marking_afresh(
    tmp_path: Path, scan: Path, scheme: MarkScheme
) -> None:
    # The student's and the teacher's upload job make these three calls, in this
    # order, with one client: the extraction goes from the first to the last as the
    # object it is, so the keys of its reads are there when the marking holds it.
    client, genai = _client(tmp_path)
    genai.models.generate_content.return_value = _sdk_reply(_items(_run(1)))

    def _job() -> None:
        extracted = grading.extract_answers(scan, scheme, gemini_client=client)
        grading.ensure_binding_allows_marking(extracted)
        grading.grade_paper(
            scheme,
            extracted,
            gemini_client=client,
            integrity_settings=client._settings.integrity,
            options=client._settings.grading.marking_options(),
        )

    with patch.object(
        correction_ai.AICorrector, "mark_question", autospec=True, side_effect=_Judge("no")
    ):
        with pytest.raises(grading.BindingHeldError) as first:
            _job()
        assert first.value.stage == "after_marking"
        assert genai.models.generate_content.call_count == 2
        with pytest.raises(grading.BindingHeldError) as second:
            _job()
        assert second.value.stage == "after_marking"
        assert genai.models.generate_content.call_count == 4


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
