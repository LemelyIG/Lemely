"""The label binder's model call, and what is done with its reply.

The reader is asked for one list, in reading order, of the question labels it sees and
the blocks of student writing (``LabelBinder.read``). It is never asked for a question
id, and nothing here gives one out: ``lemely.core.label_sequence.bind_stream`` decides
which question each block belongs to, and ``to_bound_read`` only turns what it decided
into the records the rest of the pipeline uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import ConfigDict, ValidationError, create_model

from lemely.core.binding import SeenLabel, SeenWriting, StreamItem, UnboundWriting
from lemely.core.label_sequence import INFERENCE_DOUBTS, BoundLeaf, BoundStream
from lemely.core.schemas import ExtractedAnswer, SourceBox
from lemely.io.answer_extraction import (
    _coerce_answer_text,
    _coerce_box,
    _coerce_confidence,
    _coerce_page,
)
from lemely.io.prompts.label_binding import (
    LABEL_BINDING_SYSTEM_PROMPT,
    VERSION,
    build_label_binding_user_prompt,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic.json_schema import JsonSchemaValue

    from lemely.core.binding import BindingStatus
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.gemini import GeminiClient, ImageUploads
    from lemely.io.rasterise import RasterisedPage

_KINDS = ("printed", "handwritten")
_PLACEMENTS = ("position", "arrow", "uncertain")
_JOIN_ANSWERS = "; "
_JOIN_WORKINGS = "\n"


def _nullable(schema: JsonSchemaValue) -> JsonSchemaValue:
    return {"anyOf": [schema, {"type": "null"}]}


# One item of the reply, as the model is told to write it. This is the strict half of the
# split ``lemely.io.answer_extraction`` uses for ``_RawExtractedAnswer``: the schema that
# is sent states every type, and the reply is read leniently (``_parse_item`` takes each
# item as a plain mapping), so one deviant value in one item costs that item and not the
# reply. The item is a mapping and not a pydantic class because nothing validates it as a
# whole. The descriptions are literals, so ``-OO`` cannot strip them.
_ITEM_SCHEMA: JsonSchemaValue = {
    "type": "object",
    "description": (
        "One thing on the script. A label item fills text and kind. An answer item fills "
        "answer, working_out, confidence and placed_by."
    ),
    "properties": {
        "type": {"type": "string", "enum": ["label", "answer"]},
        "page": {"type": "integer"},
        "box": {"type": "array", "items": {"type": "integer"}},
        "text": _nullable({"type": "string"}),
        "kind": _nullable({"type": "string", "enum": list(_KINDS)}),
        "answer": _nullable({"type": "string"}),
        "working_out": _nullable({"type": "string"}),
        "confidence": _nullable({"type": "number", "minimum": 0.0, "maximum": 1.0}),
        "placed_by": _nullable({"type": "string", "enum": list(_PLACEMENTS)}),
    },
    "required": ["type", "page", "box"],
}


def _wire_schema(schema: JsonSchemaValue) -> None:
    """Replace the schema pydantic derives for the reply with the one the model is sent."""
    schema["properties"] = {"items": {"type": "array", "items": _ITEM_SCHEMA}}
    schema["required"] = ["items"]
    schema["description"] = (
        "Question labels and student writing as one list in reading order. No question ids."
    )


# The reply: one field, ``items``. It is ``list[object]`` so that each element is
# validated on its own in ``parse_stream_items``: a bare string or a ``null`` in the list
# costs that one item and not the reply. A reply whose ``items`` is not a list at all
# still fails the parse; there is nothing to salvage from it.
#
# Built with ``create_model`` and not a class statement: pydantic's mypy plugin gives
# every model class an ``Any``-typed initialiser, which this project's type gate allows
# only in modules listed for it in ``pyproject.toml``.
_StreamOutput = create_model(
    "_StreamOutput",
    __config__=ConfigDict(json_schema_extra=_wire_schema),
    items=(list[object], ...),
)


@dataclass(frozen=True, slots=True)
class StreamRead:
    """The reader's list as stream items, in the order it gave them.

    ``drops`` counts the reply items that were left out, by reason: ``malformed_item``
    (not an object), ``unknown_type``, ``empty_label``, ``empty_answer`` (no answer text
    and no working), ``bad_page`` (not the index of a page that was sent).
    """

    items: list[StreamItem]
    drops: dict[str, int]


@dataclass(frozen=True, slots=True)
class BoundRead:
    """A bound stream as the records the rest of the pipeline uses.

    ``answers`` holds one answer per aligned leaf that has writing, in paper order.
    ``review_ids`` are the ids of the answers that may hold someone else's writing.
    ``unplaced_labels`` is a count. The other fields are ``BoundStream``'s, unchanged.
    """

    answers: list[ExtractedAnswer]
    unbound: list[UnboundWriting]
    unaligned_ids: list[str]
    unplaced_labels: int
    inferred_numbers: list[str]
    listing_suspects: list[str]
    review_ids: list[str]


def _usable_box(box: object, page: int | None, page_count: int) -> SourceBox | None:
    """``box`` on ``page`` as a ``SourceBox``, or ``None`` when either is unusable."""
    coords = _coerce_box(box)
    if coords is None or page is None or not 0 <= page < page_count:
        return None
    try:
        return SourceBox(page=page, box=coords)
    except ValidationError:
        return None


def _text(value: object) -> str | None:
    """``value`` as text, or ``None`` when it is blank or not text at all."""
    text, _ = _coerce_answer_text(value)
    return text if text is not None and text.strip() else None


def _parse_item(raw: object, page_count: int) -> tuple[StreamItem | None, str | None]:
    """One reply item as a stream item, or ``None`` and the reason it was dropped.

    The item is read by its ``type``. Fields of the other type, and any field the reader
    added, are not read.
    """
    if not isinstance(raw, dict):
        return None, "malformed_item"
    item_type = raw.get("type")
    kind = item_type.strip().lower() if isinstance(item_type, str) else None
    if kind not in ("label", "answer"):
        return None, "unknown_type"

    text = answer = working_out = None
    if kind == "label":
        text = _text(raw.get("text"))
        if text is None:
            return None, "empty_label"
    else:
        answer = _text(raw.get("answer"))
        working_out = _text(raw.get("working_out"))
        if answer is None and working_out is None:
            return None, "empty_answer"

    page = _coerce_page(raw.get("page"), page_count)
    if page is None:
        return None, "bad_page"
    # Boxes take no part in binding, so a bad one never costs the item.
    usable = _usable_box(raw.get("box"), page, page_count)
    box = usable.box if usable is not None else None

    if text is not None:
        seen_as: Literal["printed", "handwritten"] = (
            "handwritten" if raw.get("kind") == "handwritten" else "printed"
        )
        return SeenLabel(page=page, text=text, kind=seen_as, box=box), None
    placement = raw.get("placed_by")
    placed_by: Literal["position", "arrow", "uncertain"] = "uncertain"
    if placement == "position":
        placed_by = "position"
    elif placement == "arrow":
        placed_by = "arrow"
    confidence, _ = _coerce_confidence(raw.get("confidence"))
    return (
        SeenWriting(
            page=page,
            answer=answer or "",
            working_out=working_out,
            confidence=confidence,
            box=box,
            placed_by=placed_by,
        ),
        None,
    )


def parse_stream_items(raw_items: Sequence[object], *, page_count: int) -> StreamRead:
    """Turn the reply's ``items`` into stream items, one at a time and in order.

    A malformed item is dropped and counted; the rest of the list survives. Dropping a
    label is the same as the reader missing it, which the binding is built to survive.
    Dropping an answer loses that writing: ``drops`` is the only record of it.
    """
    items: list[StreamItem] = []
    drops: dict[str, int] = {}
    for raw in raw_items:
        item, reason = _parse_item(raw, page_count)
        if item is not None:
            items.append(item)
        elif reason is not None:
            drops[reason] = drops.get(reason, 0) + 1
    return StreamRead(items=items, drops=drops)


class LabelBinder:
    """Asks the model for the reading-order list of labels and writing on a script."""

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

    def read(
        self,
        pages: list[RasterisedPage],
        mark_scheme: MarkScheme,
        *,
        uploads: ImageUploads,
        model: str | None = None,
        media_resolution: str = "high",
        extra_cache_key: str,
    ) -> StreamRead:
        """Read every page in one call and return the list the model gave.

        ``model`` overrides the configured extraction model. A cost-ceiling or service
        error from the call is not caught here.
        """
        raw = self._client.generate_structured(
            system_prompt=LABEL_BINDING_SYSTEM_PROMPT,
            user_prompt=build_label_binding_user_prompt(mark_scheme, page_count=len(pages)),
            image_parts=[page.png_bytes for page in pages],
            image_uploads=uploads,
            media_resolution=media_resolution,
            response_schema=_StreamOutput,
            prompt_version=VERSION,
            model=model,
            extra_cache_key=extra_cache_key,
            task_tag="extraction",
        )
        return parse_stream_items(raw.model_dump()["items"], page_count=len(pages))


def _source_box(writings: list[SeenWriting], page_count: int) -> SourceBox | None:
    """The union of the usable boxes on the first writing's page, or ``None``."""
    page = writings[0].page
    boxes = [
        usable.box
        for writing in writings
        if writing.page == page
        and (usable := _usable_box(writing.box, page, page_count)) is not None
    ]
    if not boxes:
        return None
    return SourceBox(
        page=page,
        box=[
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ],
    )


def _status(leaf: BoundLeaf) -> BindingStatus:
    """``"unverified"`` when the leaf may hold someone else's writing.

    That is any doubt but an inference doubt (the leaf's question number was not seen
    and was inferred from strong evidence, which says nothing against what the leaf
    holds). A doubt of neither class counts against the leaf: an unknown doubt must
    not pass.
    """
    if all(doubt in INFERENCE_DOUBTS for doubt in leaf.doubts):
        return "verified"
    return "unverified"


def _to_answer(leaf: BoundLeaf, page_count: int) -> ExtractedAnswer:
    answers = [w.answer for w in leaf.writings if w.answer.strip()]
    workings = [w.working_out for w in leaf.writings if w.working_out and w.working_out.strip()]
    return ExtractedAnswer(
        question_id=leaf.question_id,
        answer=_JOIN_ANSWERS.join(answers),
        confidence=min(_coerce_confidence(w.confidence)[0] for w in leaf.writings),
        source_box=_source_box(leaf.writings, page_count),
        working_out=_JOIN_WORKINGS.join(workings) if workings else None,
        binding_source="label",
        binding_status=_status(leaf),
        label_seen=leaf.label_seen,
    )


def to_bound_read(bound: BoundStream, *, page_count: int) -> BoundRead:
    """Turn a bound stream into answers. It only converts: no id is assigned here.

    An aligned leaf with writing becomes one answer, with the id ``bind_stream`` gave
    the leaf. An aligned leaf with no writing is a blank answer and becomes nothing.
    Unbound writing stays unbound.
    """
    answers = [_to_answer(leaf, page_count) for leaf in bound.leaves if leaf.writings]
    return BoundRead(
        answers=answers,
        unbound=list(bound.unbound),
        unaligned_ids=list(bound.unaligned_ids),
        unplaced_labels=len(bound.unplaced_labels),
        inferred_numbers=list(bound.inferred_numbers),
        listing_suspects=list(bound.listing_suspects),
        review_ids=[a.question_id for a in answers if a.binding_status == "unverified"],
    )
