"""The label binder's model call, and what is done with its reply.

The reader is asked for one list, in reading order, of the question labels it sees and
the blocks of student writing (``LabelBinder.read``). It is never asked for a question
id, and nothing here gives one out: ``lemely.core.label_sequence.bind_stream`` decides
which question each block belongs to, and ``to_bound_read`` only turns what it decided
into the records the rest of the pipeline uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from pydantic import ConfigDict, ValidationError, create_model

from lemely.core.binding import SeenLabel, SeenWriting, StreamItem, UnboundWriting
from lemely.core.label_sequence import (
    CONTENT_DOUBTS,
    INFERENCE_DOUBTS,
    BoundLeaf,
    BoundStream,
)
from lemely.core.schemas import ExtractedAnswer, SourceBox
from lemely.io.extraction_coerce import (
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

    ``drops`` counts, by reason, every reply item that was left out or changed on the
    way in. Left out: ``malformed_item`` (not an object), ``unknown_type``,
    ``empty_label``, ``empty_answer`` (the reader reported no writing). Kept and
    repaired: ``repaired_page``, ``unreadable_answer``.
    """

    items: list[StreamItem]
    drops: dict[str, int]


@dataclass(frozen=True, slots=True)
class BoundRead:
    """A bound stream as the records the rest of the pipeline uses.

    ``answers`` holds one answer per aligned leaf that has writing, in paper order.
    ``review_ids`` are the ids of the answers that may hold someone else's writing.
    ``unplaced_labels`` is a count. ``drops`` is the ``StreamRead``'s. The other fields
    are ``BoundStream``'s, unchanged: among them ``unaligned_reasons``, why each
    unaligned leaf was not bound (one of ``label_sequence.UNALIGNED_REASONS`` per id),
    which is what lets a log line or a review reason tell a fault of the mark scheme
    from a label the reader missed.
    """

    answers: list[ExtractedAnswer]
    unbound: list[UnboundWriting]
    unaligned_ids: list[str]
    unplaced_labels: int
    inferred_numbers: list[str]
    listing_suspects: list[str]
    review_ids: list[str]
    drops: dict[str, int]
    unaligned_reasons: dict[str, str] = field(default_factory=dict)


def _usable_box(box: object, page: int | None, page_count: int) -> SourceBox | None:
    """``box`` on ``page`` as a ``SourceBox``, or ``None`` when either is unusable."""
    coords = _coerce_box(box)
    if coords is None or page is None or not 0 <= page < page_count:
        return None
    try:
        return SourceBox(page=page, box=coords)
    except ValidationError:
        return None


def _read_text(value: object) -> tuple[str | None, bool]:
    """``value`` as text, and whether it was there but could not be read as text.

    ``None`` and a blank string are no text and nothing lost. A list, an object, a
    boolean, or a number with no finite text is something the reader reported and this
    code cannot read.
    """
    if value is None:
        return None, False
    try:
        text, _ = _coerce_answer_text(value)
    except ValueError:  # an integer with more digits than Python will print
        text = None
    if text is None:
        return None, True
    return (text if text.strip() else None), False


def _confidence(value: object) -> float:
    """``value`` as a legibility score from 0 to 1; 0.0 for anything that is not one."""
    try:
        return _coerce_confidence(value)[0]
    except OverflowError:  # an integer too large to be a float
        return 0.0


def _parse_label(
    raw: dict[object, object], page: int, box: list[int] | None
) -> tuple[SeenLabel | None, list[str]]:
    text, _ = _read_text(raw.get("text"))
    if text is None:
        return None, ["empty_label"]
    kind = raw.get("kind")
    handwritten = isinstance(kind, str) and kind.strip().lower() == "handwritten"
    return (
        SeenLabel(
            page=page,
            text=text.strip(),
            kind="handwritten" if handwritten else "printed",
            box=box,
        ),
        [],
    )


def _parse_answer(
    raw: dict[object, object], page: int, box: list[int] | None, *, page_repaired: bool
) -> tuple[SeenWriting | None, list[str]]:
    answer, answer_unread = _read_text(raw.get("answer"))
    working_out, working_unread = _read_text(raw.get("working_out"))
    unreadable = answer_unread or working_unread
    if answer is None and working_out is None and not unreadable:
        return None, ["empty_answer"]  # the reader reported no writing here

    placement = raw.get("placed_by")
    placed_by: Literal["position", "arrow", "uncertain"] = "uncertain"
    # Writing that was reported but cannot be read, or whose page is a guess, is kept so
    # that its part is never taken for one left blank. It is not trusted to a leaf.
    if not (unreadable or page_repaired):
        if placement == "position":
            placed_by = "position"
        elif placement == "arrow":
            placed_by = "arrow"
    return (
        SeenWriting(
            page=page,
            answer=answer or "",
            working_out=working_out,
            confidence=_confidence(raw.get("confidence")),
            box=box,
            placed_by=placed_by,
        ),
        ["unreadable_answer"] if unreadable else [],
    )


def _parse_item(
    raw: object, page_count: int, last_page: int
) -> tuple[StreamItem | None, list[str]]:
    """One reply item as a stream item, and every reason it was dropped or repaired.

    The item is read by its ``type``. Fields of the other type, and any field the reader
    added, are not read. An item that is recognisably a label or an answer is kept
    whatever its ``page``: order is the binding evidence, so a bad page takes
    ``last_page`` and loses its box, which means nothing on a guessed page.
    """
    if not isinstance(raw, dict):
        return None, ["malformed_item"]
    item_type = raw.get("type")
    item_type = item_type.strip().lower() if isinstance(item_type, str) else None
    if item_type not in ("label", "answer"):
        return None, ["unknown_type"]

    page = _coerce_page(raw.get("page"), page_count)
    page_repaired = page is None
    if page is None:
        page = last_page
    # Boxes take no part in binding, so a bad one never costs the item.
    usable = None if page_repaired else _usable_box(raw.get("box"), page, page_count)
    box = usable.box if usable is not None else None

    item: StreamItem | None
    if item_type == "label":
        item, reasons = _parse_label(raw, page, box)
    else:
        item, reasons = _parse_answer(raw, page, box, page_repaired=page_repaired)
    if item is not None and page_repaired:
        reasons = ["repaired_page", *reasons]
    return item, reasons


def parse_stream_items(raw_items: list[object], *, page_count: int) -> StreamRead:
    """Turn the reply's ``items`` into stream items, one at a time and in order.

    Writing the reader reported is never left out: an answer item is dropped only when
    it holds no writing at all. An item that had to be repaired to be kept is counted
    in ``drops`` like one that was dropped, so nothing is changed silently. Dropping a
    label is the same as the reader missing it, which the binding is built to survive.
    """
    if not isinstance(raw_items, list):
        raise TypeError(f"the reply's items must be a list, not {type(raw_items).__name__}")
    items: list[StreamItem] = []
    drops: dict[str, int] = {}
    last_page = 0
    for raw in raw_items:
        item, reasons = _parse_item(raw, page_count, last_page)
        if item is not None:
            items.append(item)
            last_page = item.page
        for reason in reasons:
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
        task_tag: str = "extraction",
    ) -> StreamRead:
        """Read every page in one call and return the list the model gave.

        ``model`` overrides the configured extraction model. ``task_tag`` picks the
        call's thinking level and the cost bucket it is counted in. A cost-ceiling or
        service error from the call is not caught here.
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
            task_tag=task_tag,
        )
        return parse_stream_items(raw.model_dump()["items"], page_count=len(pages))

    def forget(
        self,
        pages: list[RasterisedPage],
        mark_scheme: MarkScheme,
        *,
        model: str | None = None,
        media_resolution: str = "high",
        extra_cache_key: str,
        task_tag: str = "extraction",
    ) -> bool:
        """Remove the cached reply of the ``read`` these arguments make; say if one was there.

        For a read whose paper was held or whose job failed: the next run on the same
        script must look at it again, not be handed the same list. The arguments that
        decide the cache key are the same as ``read``'s, in the same form.
        """
        return self._client.forget_structured(
            system_prompt=LABEL_BINDING_SYSTEM_PROMPT,
            user_prompt=build_label_binding_user_prompt(mark_scheme, page_count=len(pages)),
            image_parts=[page.png_bytes for page in pages],
            media_resolution=media_resolution,
            response_schema=_StreamOutput,
            prompt_version=VERSION,
            model=model,
            extra_cache_key=extra_cache_key,
            task_tag=task_tag,
        )


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

    The two classes of doubt are ``label_sequence``'s, read from there and copied
    nowhere. A content doubt (``CONTENT_DOUBTS``) says the leaf may hold writing that
    is not its own, or lack some that is: unverified. An inference doubt
    (``INFERENCE_DOUBTS``: the leaf's question number was not seen and was inferred
    from strong evidence) says nothing against what the leaf holds. A doubt of neither
    class counts against the leaf: an unknown doubt must not pass.
    """
    if any(doubt in CONTENT_DOUBTS for doubt in leaf.doubts):
        return "unverified"
    if all(doubt in INFERENCE_DOUBTS for doubt in leaf.doubts):
        return "verified"
    return "unverified"


def _to_answer(leaf: BoundLeaf, page_count: int) -> ExtractedAnswer:
    answers = [w.answer for w in leaf.writings if w.answer.strip()]
    workings = [w.working_out for w in leaf.writings if w.working_out and w.working_out.strip()]
    return ExtractedAnswer(
        question_id=leaf.question_id,
        answer=_JOIN_ANSWERS.join(answers),
        confidence=min(_confidence(w.confidence) for w in leaf.writings),
        source_box=_source_box(leaf.writings, page_count),
        working_out=_JOIN_WORKINGS.join(workings) if workings else None,
        binding_source="label",
        binding_status=_status(leaf),
        label_seen=leaf.label_seen,
    )


def to_bound_read(bound: BoundStream, *, page_count: int, drops: dict[str, int]) -> BoundRead:
    """Turn a bound stream into answers. It only converts: no id is assigned here.

    An aligned leaf with writing becomes one answer, with the id ``bind_stream`` gave
    the leaf. An aligned leaf with no writing is a blank answer and becomes nothing.
    Unbound writing stays unbound. ``drops`` is the ``StreamRead.drops`` of the read the
    stream was bound from, carried along so that it can be reported with the answers.
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
        drops=dict(drops),
        unaligned_reasons=dict(bound.unaligned_reasons),
    )
