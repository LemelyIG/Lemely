"""Whether the label binder's first read gives a reason to read the script a second time.

With ``BindingSettings.second_read_mode = "on_trigger"`` the second read is made only
when one of these fires on the first read alone. Each is computed from what the first
read is, never from a guess about what a second read would say:

- ``unaligned_leaves``: a leaf of the paper was not bound (its label was not seen, or
  the writing after it could not be told from a neighbour's).
- ``blank_leaf``: a leaf's label was seen and nothing is bound under it. On one read a
  block the reader missed is exactly this, and published it is an unflagged zero; the
  second read is what finds such a block (``binding_gate.presence_disagreements``).
- ``unplaced_labels``: the reader listed a label the paper has no place for (one the
  scheme does not ask, one seen twice, or one out of order).
- ``number_inferred``: a question number was not seen and was inferred.
- ``next_label_missing``: a leaf carries a doubt that a later label is missing (the next
  question's number, or a whole question). The doubt "next question number not seen"
  is the one a second read can clear (``orchestrate._next_number_seen_elsewhere``).
- ``listing_suspect``: a group shows the trace of writing listed before its label.
- ``duplicate_label``: a label that names a question number was listed twice.
- ``labels_out_of_order``: the bound leaves' writing is not listed in paper order.
- ``items_lost``: a reply item that may have been writing was left out on the way in.
- ``gate_check_failed``: a gate check (G1, G2, G5, G6, G7) failed on the first read
  alone, at either scope.

None of them fires on a read in which every leaf of the paper was bound, with writing,
in order, under labels the paper has, with no label missing. On such a read a second
read that agrees changes nothing. What none of them can see is a second read that
disagrees with a first read that looks whole: one that puts the same writing under
other labels (G9), or finds a second block for a leaf that already has one.

Pure: nothing here calls a model or reads a file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, get_args

from lemely.core.binding import SeenLabel, SeenWriting
from lemely.core.label_sequence import (
    DOUBT_NEXT_NUMBER_NOT_SEEN,
    DOUBT_QUESTION_UNSEEN,
    parse_label,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from lemely.core.binding import BindingCheck, StreamItem
    from lemely.core.label_sequence import BoundStream, LabelStep

SecondReadTrigger = Literal[
    "unaligned_leaves",
    "blank_leaf",
    "unplaced_labels",
    "number_inferred",
    "next_label_missing",
    "listing_suspect",
    "duplicate_label",
    "labels_out_of_order",
    "items_lost",
    "gate_check_failed",
]
#: Every trigger, in the order ``second_read_triggers`` lists them.
SECOND_READ_TRIGGERS: tuple[SecondReadTrigger, ...] = get_args(SecondReadTrigger)

_MISSING_LABEL_DOUBTS = (DOUBT_NEXT_NUMBER_NOT_SEEN, DOUBT_QUESTION_UNSEEN)


def _numbered_label_seen_twice(items: Sequence[StreamItem]) -> bool:
    """Two label items name the same question number and the same parts below it.

    Only labels that open with a number count: ``(a)`` is printed under every question,
    so a bare letter or roman numeral seen twice says nothing.
    """
    seen: set[tuple[LabelStep, ...]] = set()
    for item in items:
        if not isinstance(item, SeenLabel):
            continue
        steps = tuple(parse_label(item.text))
        if not steps or steps[0].level != "number":
            continue
        if steps in seen:
            return True
        seen.add(steps)
    return False


def _out_of_paper_order(items: Sequence[StreamItem], stream: BoundStream) -> bool:
    """The first block of each answered leaf, taken in paper order, is not listed in order.

    ``stream.leaves`` are in paper order. A block is found in ``items`` by identity:
    ``bind_stream`` hands on the reader's own blocks.
    """
    position = {
        id(item): index for index, item in enumerate(items) if isinstance(item, SeenWriting)
    }
    last = -1
    for leaf in stream.leaves:
        if not leaf.writings:
            continue
        at = position.get(id(leaf.writings[0]))
        if at is None:
            continue
        if at < last:
            return True
        last = at
    return False


def second_read_triggers(
    items: Sequence[StreamItem],
    stream: BoundStream,
    *,
    lost_items: int,
    checks: Iterable[BindingCheck],
) -> tuple[SecondReadTrigger, ...]:
    """The triggers that fire on one read, each once, in ``SECOND_READ_TRIGGERS`` order.

    ``items`` is the read's list as parsed, ``stream`` what ``bind_stream`` made of it,
    ``lost_items`` the count of reply items left out that may have been writing
    (``orchestrate.LOST_ITEM_REASONS``), and ``checks`` the gate's checks of this read
    alone. An empty tuple: nothing about the read calls for a second one.
    """
    fired: set[SecondReadTrigger] = set()
    if stream.unaligned_ids:
        fired.add("unaligned_leaves")
    if any(not leaf.writings for leaf in stream.leaves):
        fired.add("blank_leaf")
    if stream.unplaced_labels:
        fired.add("unplaced_labels")
    if stream.inferred_numbers:
        fired.add("number_inferred")
    if any(d in _MISSING_LABEL_DOUBTS for leaf in stream.leaves for d in leaf.doubts):
        fired.add("next_label_missing")
    if stream.listing_suspects:
        fired.add("listing_suspect")
    if _numbered_label_seen_twice(items):
        fired.add("duplicate_label")
    if _out_of_paper_order(items, stream):
        fired.add("labels_out_of_order")
    if lost_items > 0:
        fired.add("items_lost")
    if any(not check.passed for check in checks):
        fired.add("gate_check_failed")
    return tuple(t for t in SECOND_READ_TRIGGERS if t in fired)
