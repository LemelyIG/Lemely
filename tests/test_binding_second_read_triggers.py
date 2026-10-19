"""The label binder's second read, made only when the first read gives a reason for it.

``BindingSettings.second_read_mode = "on_trigger"`` reads the script once, works out
from that read alone whether anything about it is open to doubt
(``lemely.io.binding.second_read_triggers``), and makes the second read only then.
With no trigger the paper goes on exactly as it does with the second read switched
off, which is what a second read that agreed with the first leaves behind.
``"always"`` (the default) is the binder as it was: both reads, at the same time.

The model is a fake throughout. The realistic replies are the five recorded ones under
``tests/fixtures/binding/0625_w24_41/streams/``.
"""

from __future__ import annotations

import itertools
import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from lemely.core.binding import BindingCheck, SeenLabel, SeenWriting, StreamItem
from lemely.core.binding_gate import GateThresholds
from lemely.core.label_sequence import (
    DOUBT_ARROW,
    DOUBT_NEXT_NUMBER_NOT_SEEN,
    DOUBT_NUMBER_NOT_SEEN,
    DOUBT_QUESTION_UNSEEN,
    BoundLeaf,
    BoundStream,
    bind_stream,
)
from lemely.core.loose_schemas import MarkScheme
from lemely.io.binding import orchestrate
from lemely.io.binding.label_binder import parse_stream_items, to_bound_read
from lemely.io.binding.orchestrate import BindingOutcome, run_binding
from lemely.io.binding.second_read_triggers import (
    SECOND_READ_TRIGGERS,
    second_read_triggers,
)
from lemely.runtime.config import BindingSettings
from lemely.runtime.errors import CostCeilingError, ExternalServiceError, ParseError
from lemely.runtime.events import EventType
from lemely.runtime.example_toml import render_example_toml
from tests.test_extraction_binding import (
    _bind,
    _client,
    _events,
    _items,
    _listed_before_labels,
    _Model,
    _pages,
    _question_4_unanchored,
    _run,
    _with_a_block_after,
    _without_items,
)

_ROOT = Path(__file__).resolve().parent.parent
_PAGE_COUNT = 19
_ON_TRIGGER = {"second_read_mode": "on_trigger"}


@pytest.fixture(scope="module")
def scheme() -> MarkScheme:
    path = _ROOT / "corpus" / "mark-schemes" / "0625_w24_ms_41.json"
    return MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _whole(run: int) -> list[Any]:
    """Recorded reply ``run`` with writing under ``7(c)``, the one part the student left blank.

    Every leaf of the paper then holds writing, so a read with all its labels in order
    gives no reason for a second read.
    """
    items = _run(run)
    at = next(
        index
        for index, item in enumerate(items)
        if item.get("type") == "label" and item.get("text") == "(c)" and item.get("page") == 15
    )
    return _with_a_block_after(items, at, "the current in the coil reverses")


def _triggers_of(items: list[Any], scheme: MarkScheme) -> list[str]:
    """The triggers ``run_binding`` would find on ``items`` as the first read."""
    stream = parse_stream_items(items, page_count=_PAGE_COUNT)
    bound = bind_stream(stream.items, scheme)
    read = to_bound_read(bound, page_count=_PAGE_COUNT, drops=stream.drops)
    checks = orchestrate._label_checks(read, scheme, GateThresholds())
    return list(
        second_read_triggers(
            stream.items,
            bound,
            lost_items=orchestrate._lost_items(stream.drops),
            checks=checks,
        )
    )


def _view(outcome: BindingOutcome) -> tuple[Any, ...]:
    """Everything a binding outcome hands on, except the cache keys of the reads made."""
    return (
        outcome.report.verdict,
        outcome.report.retried,
        [c.model_dump() for c in outcome.report.checks],
        [a.model_dump() for a in outcome.answers],
        outcome.review_only_ids,
        [w.model_dump() for w in outcome.unbound],
        outcome.review_reasons,
        outcome.drops,
        outcome.marked_from_other_read,
    )


def _decided(outcome: BindingOutcome) -> tuple[Any, ...]:
    """What the paper goes on with: ``_view`` without the checks and ``retried``.

    Those two always differ between one read and two (two add G9), so they are not
    what a second read changing the outcome means.
    """
    view = _view(outcome)
    return (view[0], *view[3:])


# --------------------------------------------------------------------------------------
# The setting
# --------------------------------------------------------------------------------------
def test_the_default_mode_is_always() -> None:
    assert BindingSettings().second_read_mode == "always"
    assert BindingSettings(second_read_mode="on_trigger").second_read_mode == "on_trigger"
    with pytest.raises(ValidationError):
        BindingSettings(second_read_mode="sometimes")


def test_the_example_toml_lists_the_mode_with_its_default() -> None:
    text = render_example_toml()
    assert 'second_read_mode = "always"' in text
    assert (_ROOT / "lemely.toml.example").read_text(encoding="utf-8") == text


# --------------------------------------------------------------------------------------
# The triggers, one at a time, on a hand-built bound stream
# --------------------------------------------------------------------------------------
def _w(text: str) -> SeenWriting:
    return SeenWriting(page=0, answer=text, confidence=0.9)


def _label(text: str) -> SeenLabel:
    return SeenLabel(page=0, text=text, kind="printed")


def _leaf(qid: str, *writings: SeenWriting, doubts: tuple[str, ...] = ()) -> BoundLeaf:
    return BoundLeaf(
        question_id=qid,
        label_seen=qid,
        number_inferred=DOUBT_NUMBER_NOT_SEEN in doubts,
        writings=list(writings),
        doubts=list(doubts),
    )


def _stream(*leaves: BoundLeaf, **extra: Any) -> BoundStream:
    fields: dict[str, Any] = {
        "leaves": list(leaves),
        "unbound": [],
        "unaligned_ids": [],
        "unplaced_labels": [],
        "inferred_numbers": [],
        "listing_suspects": [],
    }
    return BoundStream(**{**fields, **extra})


def _check(passed: bool, scope: str = "paper") -> BindingCheck:
    return BindingCheck(id="G5", passed=passed, scope=scope, detail="")


_A, _B = _w("first answer"), _w("second answer")
_CLEAN_ITEMS: list[StreamItem] = [_label("1"), _label("(a)"), _A, _label("(b)"), _B]
_CLEAN = _stream(_leaf("1a", _A), _leaf("1b", _B))


def _fired(
    items: list[StreamItem] = _CLEAN_ITEMS,
    stream: BoundStream = _CLEAN,
    *,
    lost_items: int = 0,
    checks: list[BindingCheck] | None = None,
) -> list[str]:
    return list(
        second_read_triggers(
            items, stream, lost_items=lost_items, checks=checks or [_check(passed=True)]
        )
    )


def test_a_clean_read_fires_nothing() -> None:
    assert _fired() == []


def test_a_leaf_with_nothing_under_its_label_fires() -> None:
    stream = _stream(_leaf("1a", _A), _leaf("1b"))
    assert _fired(stream=stream) == ["blank_leaf"]


def test_an_unaligned_leaf_fires() -> None:
    stream = _stream(_leaf("1a", _A), unaligned_ids=["1b"])
    assert _fired(stream=stream) == ["unaligned_leaves"]


def test_a_label_the_scheme_has_no_place_for_fires() -> None:
    stream = _stream(_leaf("1a", _A), _leaf("1b", _B), unplaced_labels=[_label("(z)")])
    assert _fired(stream=stream) == ["unplaced_labels"]


def test_a_question_number_that_was_not_seen_fires() -> None:
    stream = _stream(
        _leaf("1a", _A, doubts=(DOUBT_NUMBER_NOT_SEEN,)),
        _leaf("1b", _B, doubts=(DOUBT_NUMBER_NOT_SEEN,)),
        inferred_numbers=["1"],
    )
    assert _fired(stream=stream) == ["number_inferred"]


@pytest.mark.parametrize("doubt", [DOUBT_NEXT_NUMBER_NOT_SEEN, DOUBT_QUESTION_UNSEEN])
def test_a_doubt_that_a_later_label_is_missing_fires(doubt: str) -> None:
    stream = _stream(_leaf("1a", _A), _leaf("1b", _B, doubts=(doubt,)))
    assert _fired(stream=stream) == ["next_label_missing"]


def test_a_doubt_that_no_label_is_missing_fires_nothing() -> None:
    # An arrow, a block from the previous page, writing set aside: the leaf's own label
    # and the next one were both seen. These doubts make the answer unverified on one
    # read and on two alike; a second read is never what clears them.
    stream = _stream(_leaf("1a", _A, doubts=(DOUBT_ARROW,)), _leaf("1b", _B))
    assert _fired(stream=stream) == []


def test_writing_listed_before_its_label_fires() -> None:
    stream = _stream(_leaf("1a", _A), _leaf("1b", _B), listing_suspects=["1"])
    assert _fired(stream=stream) == ["listing_suspect"]


def test_a_numbered_label_seen_twice_fires() -> None:
    items: list[StreamItem] = [*_CLEAN_ITEMS, _label("1(b)"), _label("Q1 (b)")]
    assert _fired(items=items) == ["duplicate_label"]


def test_the_same_letter_under_two_questions_is_not_a_duplicate() -> None:
    c, d = _w("third"), _w("fourth")
    items: list[StreamItem] = [*_CLEAN_ITEMS, _label("2"), _label("(a)"), c, _label("(b)"), d]
    stream = _stream(_leaf("1a", _A), _leaf("1b", _B), _leaf("2a", c), _leaf("2b", d))
    assert _fired(items=items, stream=stream) == []


def test_answers_listed_out_of_paper_order_fire() -> None:
    items: list[StreamItem] = [_label("1"), _label("(b)"), _B, _label("(a)"), _A]
    assert _fired(items=items) == ["labels_out_of_order"]


def test_a_reply_item_lost_on_the_way_in_fires() -> None:
    assert _fired(lost_items=1) == ["items_lost"]


@pytest.mark.parametrize("scope", ["paper", "question"])
def test_a_failed_gate_check_fires(scope: str) -> None:
    assert _fired(checks=[_check(passed=True), _check(passed=False, scope=scope)]) == [
        "gate_check_failed"
    ]


def test_triggers_are_listed_once_each_in_a_fixed_order() -> None:
    stream = _stream(
        _leaf("1a", _A, doubts=(DOUBT_NEXT_NUMBER_NOT_SEEN,)),
        unaligned_ids=["1b"],
        unplaced_labels=[_label("(z)"), _label("(y)")],
        listing_suspects=["1"],
    )
    fired = _fired(stream=stream, lost_items=2, checks=[_check(False), _check(False)])
    assert fired == [t for t in SECOND_READ_TRIGGERS if t in fired]
    assert len(fired) == len(set(fired)) == 6
    assert "blank_leaf" not in fired  # 1a holds writing; 1b is unaligned, not blank


def test_the_recorded_reads_fire_on_the_blank_part_and_the_missing_label(
    scheme: MarkScheme,
) -> None:
    # Runs 1 to 3 hold all 63 labels; runs 4 and 5 lack the ringed number 4. The
    # student left 7(c) blank, and on one read a blank is what a missed block is.
    missing = ["number_inferred", "next_label_missing"]
    fired = {run: _triggers_of(_run(run), scheme) for run in range(1, 6)}
    assert fired == {
        1: ["blank_leaf"],
        2: ["blank_leaf"],
        3: ["blank_leaf"],
        4: ["blank_leaf", *missing],
        5: ["blank_leaf", *missing],
    }
    whole = {run: _triggers_of(_whole(run), scheme) for run in range(1, 6)}
    assert whole == {1: [], 2: [], 3: [], 4: missing, 5: missing}


def test_writing_listed_before_labels_and_unanchored_questions_fire(scheme: MarkScheme) -> None:
    assert "listing_suspect" in _triggers_of(_listed_before_labels(_run(1)), scheme)
    unanchored = _triggers_of(_question_4_unanchored(4), scheme)
    assert {"unaligned_leaves", "gate_check_failed"} <= set(unanchored)


# --------------------------------------------------------------------------------------
# run_binding with second_read_mode = "on_trigger"
# --------------------------------------------------------------------------------------
def test_with_no_trigger_one_read_is_made_and_goes_on_as_with_one_read(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    model = _Model(first=_items(_whole(1)))  # a second read would find no reply and fail
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        outcome = _bind(tmp_path / "a", scheme, model, **_ON_TRIGGER)
    assert model.made() == ["first"]
    one_read = _bind(tmp_path / "b", scheme, _Model(first=_items(_whole(1))), second_read=False)
    assert _view(outcome) == _view(one_read)
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", False)
    assert len(outcome.read_cache_keys) == 1
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert event["second_read"] is False
    assert event["second_read_mode"] == "on_trigger"
    assert event["second_read_triggers"] == []


def test_with_a_trigger_the_second_read_is_made_and_the_pair_decides_as_always(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    first, second = _question_4_unanchored(4), _run(1)
    model = _Model(first=_items(first), second=_items(second))
    with _events(EventType.BINDING_GATE_RESULT) as seen:
        outcome = _bind(tmp_path / "a", scheme, model, **_ON_TRIGGER)
    assert model.made() == ["first", "second"]
    always = _bind(tmp_path / "b", scheme, _Model(first=_items(first), second=_items(second)))
    assert _view(outcome) == _view(always)
    assert outcome.read_cache_keys == always.read_cache_keys
    assert (outcome.report.verdict, outcome.report.retried) == ("pass", True)
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert event["second_read"] is True
    assert event["second_read_triggers"] == _triggers_of(first, scheme)
    assert "unaligned_leaves" in event["second_read_triggers"]


def test_a_triggered_second_read_is_made_after_the_first(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    order: list[str] = []
    model = _Model(first=_items(_run(4)), second=_items(_run(1)))

    def recorded(**kwargs: Any) -> Any:
        order.append(f"{_Model.key(kwargs)} starts")
        reply = model(**kwargs)
        order.append(f"{_Model.key(kwargs)} ends")
        return reply

    client, _genai = _client(tmp_path, **_ON_TRIGGER)
    pages = _pages()
    with (
        client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
        patch.object(client, "generate_structured", side_effect=recorded),
    ):
        run_binding(
            client, pages, scheme, uploads=uploads, settings=client._settings, manifest_key="k"
        )
    assert order == ["first starts", "first ends", "second starts", "second ends"]


def test_both_modes_make_the_same_calls_under_the_same_keys(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    first, second = _run(4), _run(1)
    always = _Model(first=_items(first), second=_items(second))
    on_trigger = _Model(first=_items(first), second=_items(second))
    _bind(tmp_path / "a", scheme, always)
    _bind(tmp_path / "b", scheme, on_trigger, **_ON_TRIGGER)

    def calls(model: _Model) -> list[tuple[str, str, str]]:
        return sorted((c["task_tag"], c["extra_cache_key"], c["user_prompt"]) for c in model.calls)

    assert calls(always) == calls(on_trigger)


def test_a_triggered_second_read_that_fails_once_is_read_again(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    model = _Model(
        first=_items(_run(4)),
        second=[ExternalServiceError("503 from the service"), _items(_run(1))],
    )
    with _events(EventType.SECOND_READ_FAILED) as seen:
        outcome = _bind(tmp_path, scheme, model, **_ON_TRIGGER)
    assert model.made() == ["first", "second", "second"]
    assert [c.id for c in outcome.report.checks][-1] == "G9"
    (failure,) = seen[EventType.SECOND_READ_FAILED]
    assert failure["stage"] == "binding_second_read"


def test_a_triggered_second_read_that_fails_twice_fails_the_job(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    again = ParseError("and again")
    model = _Model(first=_items(_run(4)), second=[ParseError("did not parse"), again])
    with pytest.raises(ParseError) as raised:
        _bind(tmp_path, scheme, model, **_ON_TRIGGER)
    assert raised.value is again
    assert model.made() == ["first", "second", "second"]


def test_a_second_read_that_crashes_twice_fails_with_the_fixed_sentence(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    model = _Model(first=_items(_run(4)), second=[RuntimeError("bug"), RuntimeError("bug")])
    with pytest.raises(ExternalServiceError, match=orchestrate.SECOND_READ_CRASH_MESSAGE):
        _bind(tmp_path, scheme, model, **_ON_TRIGGER)


def test_a_failed_first_read_fails_the_paper_and_no_second_read_is_made(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    model = _Model(first=ParseError("the reply did not parse"), second=_items(_run(1)))
    with pytest.raises(ParseError):
        _bind(tmp_path, scheme, model, **_ON_TRIGGER)
    assert model.made() == ["first"]


@pytest.mark.parametrize("which", ["first", "second"])
def test_a_cost_ceiling_in_either_read_propagates(
    tmp_path: Path, scheme: MarkScheme, which: str
) -> None:
    replies: dict[str, Any] = {"first": _items(_run(4)), "second": _items(_run(1))}
    replies[which] = CostCeilingError("ceiling")
    with pytest.raises(CostCeilingError):
        _bind(tmp_path, scheme, _Model(**replies), **_ON_TRIGGER)


def test_always_still_reads_twice_at_once_and_publishes_no_trigger_fields(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    together = threading.Barrier(2, timeout=10)
    model = _Model(first=_items(_run(1)), second=_items(_run(2)))

    def both_must_arrive(**kwargs: Any) -> Any:
        together.wait()
        return model(**kwargs)

    client, _genai = _client(tmp_path)
    pages = _pages()
    with (
        _events(EventType.BINDING_GATE_RESULT) as seen,
        client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
        patch.object(client, "generate_structured", side_effect=both_must_arrive),
    ):
        run_binding(
            client, pages, scheme, uploads=uploads, settings=client._settings, manifest_key="k"
        )
    assert model.made() == ["first", "second"]
    (event,) = seen[EventType.BINDING_GATE_RESULT]
    assert "second_read_mode" not in event
    assert "second_read_triggers" not in event


def test_the_mode_is_read_only_with_the_second_read_on(tmp_path: Path, scheme: MarkScheme) -> None:
    model = _Model(first=_items(_run(4)))
    _bind(tmp_path, scheme, model, second_read=False, **_ON_TRIGGER)
    assert model.made() == ["first"]


# --------------------------------------------------------------------------------------
# Recall, by replay: wherever the second read changed the outcome, a trigger fired
# --------------------------------------------------------------------------------------
def test_every_recorded_pair_the_second_read_changed_fired_a_trigger(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    changed: list[tuple[int, int]] = []
    missed: list[tuple[int, int]] = []
    for n, (a, b) in enumerate(itertools.product(range(1, 6), repeat=2)):
        both = _bind(
            tmp_path / f"{n}a", scheme, _Model(first=_items(_run(a)), second=_items(_run(b)))
        )
        alone = _bind(tmp_path / f"{n}b", scheme, _Model(first=_items(_run(a))), second_read=False)
        if _decided(both) != _decided(alone):
            changed.append((a, b))
            if not _triggers_of(_run(a), scheme):
                missed.append((a, b))
    # Not vacuous: reads 4 then 1, 2 or 3 clear the doubt on 3c that read 4 alone keeps.
    assert changed == [(4, 1), (4, 2), (4, 3)]
    assert missed == []


def test_every_block_the_first_reader_missed_fires_a_trigger(
    tmp_path: Path, scheme: MarkScheme
) -> None:
    # Constructed, not recorded: each block of a whole read taken out in turn, with the
    # whole read as the second. The second read is what finds such a block; on the
    # first read alone its leaf is blank. Every one must call for the second read.
    whole = _whole(1)
    blocks = [i for i, item in enumerate(whole) if item.get("type") == "answer"]
    changed: list[int] = []
    missed: list[int] = []
    for index in blocks:
        first = _without_items(whole, index)
        both = _bind(
            tmp_path / f"{index}a", scheme, _Model(first=_items(first), second=_items(whole))
        )
        alone = _bind(
            tmp_path / f"{index}b", scheme, _Model(first=_items(first)), second_read=False
        )
        if _decided(both) != _decided(alone):
            changed.append(index)
            if not _triggers_of(first, scheme):
                missed.append(index)
    assert len(changed) >= len(blocks) * 3 // 4
    assert missed == []
