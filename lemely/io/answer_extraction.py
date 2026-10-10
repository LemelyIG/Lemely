"""GeminiAnswerExtractor — extracts student responses from scanned exam papers (any paper type)."""

from __future__ import annotations

import contextvars
import functools
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, GetJsonSchemaHandler, ValidationError
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema as pydantic_core_schema

from lemely.core.binding import BindingReport
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers, SourceBox
from lemely.io.binding.orchestrate import LegacyRead, gate_legacy, run_binding

# The per-field coercion helpers live in ``lemely.io.extraction_coerce`` (the label
# binder uses them too, and this module calls the binder). They are re-exported here
# under the names they have always had.
from lemely.io.extraction_coerce import (
    _FALLBACK_CONFIDENCE,  # noqa: F401 -- re-exported
    _coerce_answer_text,
    _coerce_box,
    _coerce_confidence,
    _coerce_page,
)
from lemely.io.gemini import GeminiClient, ImageUploads
from lemely.io.prompts.answer_extraction import (
    EXTRACTOR_SYSTEM_PROMPT,
    VERSION,
    build_extractor_user_prompt,
    build_question_manifest_hash_key,
)
from lemely.io.rasterise import RasterisedPage, rasterise_scan_to_pages
from lemely.io.reread import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    Rereader,
    should_reread,
)
from lemely.io.run_cap import marking_run_slot
from lemely.io.scan_hygiene import check_scan_hygiene
from lemely.io.second_read import REREAD_AGREEMENT_THRESHOLD, build_second_reader, compute_agreement
from lemely.runtime.errors import CostCeilingError, LemelyError
from lemely.runtime.events import EventType, bus

# I1: per-page image extraction call, medium tokenisation tier (Google's
# documented recommendation for image/PDF inputs, ~560 tokens/page) — the
# whole-paper extraction call carries every page at this resolution so
# question context stays cross-page in one call. Re-reads (lemely.io.reread)
# use "high" instead, on a single already-cropped-and-upscaled image.
# Referenced from lemely.accuracy.harness's RunManifest fingerprint too (a
# constant, not a per-run setting) so a run that now always sets this on
# every extraction call never archives the same params_fingerprint as a
# pre-I1 run that set no media resolution at all.
EXTRACTION_MEDIA_RESOLUTION = "medium"


# NOTE: these two wire-schema classes are what Gemini actually sees (via
# _ExtractorOutput's response_schema), so their docstrings are deliberately
# terse and model-facing rather than carrying the engineering rationale for
# why they exist — that rationale is recorded here in module comments
# instead (I1 review: docstring prose was leaking into the schema
# `description` field, which `_strip_schema` does not strip).
#
# `_RawSourceBox` (rather than the strict, self-constructed `SourceBox`)
# is the wire shape for `source_box` because putting `SourceBox`'s own
# type/range/positive-area validation directly on the wire schema meant one
# malformed coordinate anywhere in a ~40-answer response failed the
# *entire* `_ExtractorOutput` parse, triggering `GeminiClient`'s
# schema-correction retry (a second full 16-page call) before raising
# `ParseError` and losing every answer in the paper. `page`/`box` are typed
# `Any` here -- not just un-validated but un-typed -- because round 1's fix
# left `page: int` / `box: list[int]`, which pydantic still rejects outright
# for a fractional float coordinate (`100.5`, the single most likely
# malformation for a 0-1000 normalised value), a `null` page, or `box` given
# as a prose string instead of four numbers (I1 review round 2, MUST-FIX 2)
# -- any of those still lost the whole paper and paid for the retry. Every
# one of those shapes, and a well-formed box, is coerced or dropped
# per-answer by `_sanitize_source_box` (via `_coerce_page`/`_coerce_box`)
# instead, the same salvage treatment already given to an out-of-range page
# index. `SourceBox` itself stays strict for boxes the codebase constructs
# internally (e.g. `reread.py`).
#
# `_RawExtractedAnswer` mirrors `ExtractedAnswer` except for that box, and
# omits `answer_reread`/`reread_agreement` entirely: those two fields are
# outputs of a later *local* computation, never something the model is
# asked for, so they must not appear in the schema it is given.
class _RawSourceBox(BaseModel):
    """A bounding box on one page image, before validation."""

    page: Any = None
    box: Any = None

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: pydantic_core_schema.CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        # I1 review round 4, MUST-FIX A: `page`/`box` are typed `Any` above
        # purely so `_coerce_page`/`_coerce_box` can salvage a model output
        # that deviates from the schema (fractional float, numeric string,
        # `null`) without failing the wire-schema parse -- see the module
        # comment above this class. But that Python-side `Any` also flowed
        # straight into the *wire* schema (`model_json_schema()` ->
        # `_strip_schema` -> `response_json_schema`, `gemini.py`), erasing
        # `page`/`box`'s types and `required`-ness from the only
        # machine-readable instruction Gemini is given for this field's
        # shape. Override what pydantic emits here so the schema actually
        # sent stays the round-2 shape (typed, required) regardless of how
        # permissive the Python-side type stays for parsing.
        json_schema = handler(core_schema)
        json_schema["properties"] = {
            "page": {"type": "integer"},
            "box": {"type": "array", "items": {"type": "integer"}},
        }
        json_schema["required"] = ["page", "box"]
        # US-036: hard-code this class's docstring text here rather than
        # trust pydantic to pick it up from `__doc__` via `handler()` above.
        # CPython's `-O`/`-OO` strips docstrings, so `handler(core_schema)`
        # silently omits `description` entirely under those flags -- not a
        # validation risk (the strict types above are untouched either way),
        # but real model-facing instruction text lost from the schema Gemini
        # is sent. Keep this string identical to the class docstring; a
        # divergence here is only caught by
        # WireSchemaSurvivesPythonOptimizeTests in
        # tests/test_answer_extraction.py, which pins this literal.
        json_schema["description"] = "A bounding box on one page image, before validation."
        return json_schema


# US-031: `_RawExtractedAnswer`'s own scalar fields used to be strictly typed
# (`question_id: str`, `answer: str`, `confidence: float = Field(..., ge=0.0,
# le=1.0)`) -- one level ABOVE the `source_box` handling above, and the same
# failure the module comment on `_RawSourceBox` describes played out there
# too: a scalar `source_box` (a prose string, or a bare 4-element list where
# an object is expected), a NaN/Infinity/out-of-range/missing `confidence`,
# or a numeric `answer`/`question_id` all failed `_ExtractorOutput`'s
# pydantic validation for the *whole* answers list, triggering
# `GeminiClient`'s schema-correction retry (a second full-paper call) before
# raising `ParseError` and losing every answer in the paper for one bad
# field on one answer. Every field here is `Any` for the same reason
# `_RawSourceBox.page`/`.box` are: so a deviant shape reaches the
# `_coerce_*` functions below instead of failing the wire-schema parse, and
# is salvaged or dropped *per answer*, mirroring the `(value, drop_reason)`
# idiom `_sanitize_source_box` already uses. The wire schema Gemini actually
# sees still declares the strict, required shape via
# `__get_pydantic_json_schema__` below, same split as `_RawSourceBox`.
class _RawExtractedAnswer(BaseModel):
    """One extracted answer, as returned by the primary extraction call."""

    question_id: Any = None
    answer: Any = None
    confidence: Any = None
    source_region: Any = None
    source_box: Any = None
    working_out: Any = None

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: pydantic_core_schema.CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        # Same rationale as _RawSourceBox.__get_pydantic_json_schema__: the
        # Python-side `Any` typing above is for lenient parsing only. What
        # is actually sent to Gemini must keep stating the strict,
        # instructive shape -- otherwise the model loses the very
        # instruction that made it produce well-formed answers in the first
        # place (this file's module comment: an earlier attempt made
        # `_RawSourceBox` lenient WITHOUT this override and emptied its wire
        # schema, which is the same class of bug this override exists to
        # avoid here too). `source_box`'s object shape is built from
        # `_RawSourceBox.model_json_schema()` itself rather than duplicated
        # by hand, so the two overrides cannot drift apart.
        json_schema = handler(core_schema)
        # Review MUST-FIX 1: pass `_RawSourceBox`'s own schema through
        # WHOLESALE (`box_schema`, not `{"properties": box_schema[...],
        # "required": box_schema[...]}`) -- the earlier cherry-picked form
        # silently dropped `box_schema["description"]` (`_RawSourceBox`'s
        # class docstring, deliberately model-facing per this file's module
        # comment), degrading the sent schema exactly the way the module
        # comment above warns against. `_strip_schema` removes `title`, so
        # carrying the whole object adds nothing unwanted, and any key
        # `_RawSourceBox` gains later travels automatically instead of
        # needing a matching edit here.
        box_schema = _RawSourceBox.model_json_schema()
        json_schema["properties"] = {
            "question_id": {"type": "string"},
            "answer": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "source_region": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "source_box": {"anyOf": [box_schema, {"type": "null"}]},
            "working_out": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        }
        json_schema["required"] = ["question_id", "answer", "confidence"]
        # US-036: same rationale as _RawSourceBox.__get_pydantic_json_schema__
        # above -- hard-code this class's docstring text so it survives
        # `-O`/`-OO` stripping `__doc__` instead of relying on `handler()`.
        json_schema["description"] = (
            "One extracted answer, as returned by the primary extraction call."
        )
        return json_schema


class _ExtractorOutput(BaseModel):
    """Inner schema we ask Gemini to return — just the answers list."""

    # Review MUST-FIX 6: `list[Any]`, not `list[_RawExtractedAnswer]`. With
    # the strict element type, ONE malformed list element -- a bare string
    # (``"1: B"``), a positional list (``["1", "B", 0.8]``), or a ``null`` --
    # failed pydantic validation for the *whole* `answers` list (every
    # element, including 39 good ones), triggering the schema-correction
    # retry and then `ParseError`, losing the entire paper for one bad
    # element -- verbatim the defect this story exists to fix, one
    # structural level up from `_RawExtractedAnswer`'s own fields. Each
    # element is instead validated individually, in Python, by
    # `_parse_raw_answers` below: a malformed element is dropped into
    # `answer_drops["malformed_answer_shape"]` and the rest of the paper
    # survives. The wire schema Gemini is sent must still declare the
    # strict per-item object shape -- see `__get_pydantic_json_schema__`.
    #
    # A body where `answers` itself is not a list at all (a string, a dict,
    # `null`, or the key absent) still fails validation and still loses the
    # whole paper: there is nothing to salvage per-answer when the container
    # itself is not a list. That is accepted as a legitimate, honestly-named
    # loss, not silently left in the eleven-shape count.
    answers: list[Any]

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: pydantic_core_schema.CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        # Same split as _RawSourceBox/_RawExtractedAnswer: `list[Any]` above
        # is for lenient PARSING only. What Gemini is actually sent must
        # still declare `answers` as an array of the strict, instructive
        # per-answer object -- passed through WHOLESALE (review MUST-FIX 1:
        # cherry-picking sub-keys here previously dropped `source_box`'s
        # description; do not repeat that mistake for the answer item
        # schema).
        json_schema = handler(core_schema)
        json_schema["properties"]["answers"]["items"] = _RawExtractedAnswer.model_json_schema()
        # US-036: same rationale as _RawSourceBox/_RawExtractedAnswer above
        # -- hard-code this class's own top-level docstring text too, so it
        # survives `-O`/`-OO` stripping `__doc__` instead of relying on
        # `handler()`.
        json_schema["description"] = "Inner schema we ask Gemini to return — just the answers list."
        return json_schema


def _build_paper_id(mark_scheme: MarkScheme) -> str:
    m = mark_scheme.metadata
    session = m.session_month.value.replace("/", "")
    year = str(m.session_year) if m.session_year is not None else "specimen"
    return f"{m.subject_code}_{session}_{year}_p{m.paper_number}{m.paper_variant}"


def _canonical_id(q_id: str) -> str:
    """Strip whitespace, brackets, dots; lowercase — for fuzzy ID matching."""
    return re.sub(r"[\s()\[\].]", "", q_id).lower()


def normalize_extracted_answers(
    extracted: ExtractedAnswers,
    manifest_ids: list[str],
) -> ExtractedAnswers:
    """Re-map extracted answer IDs to canonical manifest IDs.

    One pass only: match by canonical form. An answer whose id matches nothing
    **keeps its original id** and is left unmatched.

    #37 (M1.2) deleted the second pass. It was a positional fallback: any
    answer that matched nothing was handed the next unclaimed manifest id, in
    order. That is a guess wearing a genuine id — and because every downstream
    consumer keys on ``question_id``, the guess became indistinguishable from a
    real match. Two concrete harms:

    * ``id_match_rate`` counted post-fallback coverage, not id agreement. A
      guessed answer was stamped ``id_match="exact"`` and the metric could not
      fall below its target no matter how badly extraction drifted.
    * One missing answer shifted every later unmatched one by a slot, so a
      single extraction gap silently re-aligned an entire paper against the
      wrong questions.

    A gap is honest and shows up as ``UNMATCHED``; a silent realignment is not.
    Unmatched answers are deliberately NOT dropped here — the caller needs to
    see them to count them.

    US-031 review MUST-FIX 7 (stronger fix): ``dropped_question_ids`` gets
    the exact same one-pass canonical remap, so ``correct_paper`` can match
    it against real manifest ids (``Question.id``) the same way it matches
    ``answers``' own ids -- a dropped answer's id came from the same
    untrusted wire response and needs the same treatment.
    """
    canonical_map: dict[str, str] = {_canonical_id(mid): mid for mid in manifest_ids}
    new_answers: list[ExtractedAnswer] = []

    for ans in extracted.answers:
        canon = _canonical_id(ans.question_id)
        if canon in canonical_map:
            new_answers.append(ans.model_copy(update={"question_id": canonical_map[canon]}))
        else:
            new_answers.append(ans)

    new_dropped_ids = [
        canonical_map.get(_canonical_id(qid), qid) for qid in extracted.dropped_question_ids
    ]
    update: dict[str, Any] = {"answers": new_answers, "dropped_question_ids": new_dropped_ids}
    # ``unbound_question_ids`` (leaves the label binder could bind nothing to) is
    # matched against manifest ids by ``correct_paper`` just as the dropped ids are,
    # so it gets the same remap. Left alone when empty, so that a record that never
    # had the field is not given it here.
    if extracted.unbound_question_ids:
        update["unbound_question_ids"] = [
            canonical_map.get(_canonical_id(qid), qid) for qid in extracted.unbound_question_ids
        ]

    return extracted.model_copy(update=update)


# Gemini's self-reported confidence is often miscalibrated — it tends to be
# overconfident on ambiguous handwriting and underconfident on clean MCQ answers.
# This heuristic layer adjusts confidence using structural signals from the
# extraction result itself, with zero extra API calls.
def _calibrate_confidence(
    answer: ExtractedAnswer,
    question_type_hint: str | None = None,
) -> float:
    """Adjust raw Gemini confidence using structural signals from the extraction result."""
    conf = answer.confidence
    is_mcq_hint = question_type_hint == "mcq"

    # Detect MCQ from answer content: single letter A/B/C/D
    answer_stripped = answer.answer.strip()
    looks_like_mcq_answer = answer_stripped.upper() in {"A", "B", "C", "D"}

    # D14/D19 (spec §2.1): the old heuristic added an unconditional +0.1 bonus
    # to any single-letter answer and applied the MCQ/short-answer caps BEFORE
    # the source_region/working_out bonuses, letting a capped value leak past
    # its cap -- e.g. an MCQ hint with source_region set could leak
    # 0.20 + 0.03 = 0.23, and a short non-MCQ answer with both working_out and
    # source_region set could leak 0.30 + 0.05 + 0.03 = 0.38. There is no MCQ
    # confidence bonus any more — Gemini's self-reported confidence on a clean
    # single-letter answer is not something this heuristic layer should
    # inflate. Every bonus is added first; any cap is computed and applied as
    # the LAST step, so a capped value can never leak past 0.2/0.3.
    #
    # #36 bullet 2 (amended): the 0.2 cap applies ONLY to the mcq-hint-with-
    # a-non-letter-answer case -- i.e. the question is MCQ but the extractor
    # did not return a clean A/B/C/D letter, which is a sign of a bad
    # extraction. A clean single letter (looks_like_mcq_answer) is a GOOD
    # extraction and keeps its raw (bonus-adjusted) confidence uncapped; this
    # is NOT a blanket ceiling on anything MCQ-shaped.
    cap: float | None = None
    if is_mcq_hint or looks_like_mcq_answer:
        # MCQ-shaped: only cap the bad-extraction case (mcq hint, non-letter
        # answer). A clean single letter is a good extraction — no cap, and
        # it does not fall through to the non-MCQ short-answer/working_out
        # logic below (a single letter would otherwise trip the len<2 cap).
        if is_mcq_hint and not looks_like_mcq_answer:
            cap = 0.2
    else:
        # Non-MCQ: check answer completeness
        if len(answer_stripped) < 2:
            cap = 0.3

        # Working out present → slight boost (extractor found method, more reliable)
        if answer.working_out:
            conf = min(1.0, conf + 0.05)

    # Source region present → slight boost (extractor located answer spatially)
    if answer.source_region:
        conf = min(1.0, conf + 0.03)

    if cap is not None:
        conf = min(conf, cap)

    return conf


def _sanitize_source_box(raw_box: Any, num_pages: int) -> tuple[SourceBox | None, str | None]:
    """Convert Gemini's untrusted ``source_box`` value into a real ``SourceBox``.

    ``raw_box`` is typed ``Any`` (not ``_RawSourceBox | None``) because
    ``_RawExtractedAnswer.source_box`` is itself ``Any`` now (US-031): a
    scalar ``source_box`` -- a prose string, or a bare 4-element list where
    an object (``{"page": ..., "box": ...}``) is expected -- reaches here as
    exactly that scalar, not a pre-shaped ``_RawSourceBox``. Anything that is
    not a dict is dropped straight to ``None`` with reason
    ``"invalid_source_box_shape"`` before even attempting to parse ``page``/
    ``box`` out of it.

    Never trust the model's ``page`` index blindly: a hallucinated page index
    outside what was actually sent would violate I1's own acceptance
    criterion (1) ("every extracted answer carries a source_box whose page
    index exists") the moment it reached a caller — so an out-of-range (or
    unparseable, e.g. ``null`` or non-numeric) page drops to ``None`` here
    rather than passed through, exactly like a low-quality extraction is
    reported rather than silently kept.

    A box whose page clears that check but whose coordinates cannot be
    coerced to four numbers (:func:`_coerce_box`), or that clears coercion
    but still fails ``SourceBox``'s own range/positive-area validation, also
    drops to ``None`` here rather than raising and losing every answer in
    the paper.

    Returns ``(box, drop_reason)``: ``drop_reason`` is ``None`` when nothing
    was dropped (including the "no box at all" case), and otherwise one of
    ``"invalid_source_box_shape"`` / ``"out_of_range_page"`` /
    ``"malformed_coordinates"`` (I1 review finding 5: a silent drop here
    would let an extractor that *hallucinates* page indices score better
    than one that returns in-range-but-wrong boxes on a later box-hit-rate
    metric, since the hallucination would leave the denominator entirely
    rather than counting against it — so the caller must count and surface
    these, never just apply them quietly).
    """
    if raw_box is None:
        return None, None
    if not isinstance(raw_box, dict):
        return None, "invalid_source_box_shape"
    try:
        parsed_box = _RawSourceBox.model_validate(raw_box)
    except ValidationError:
        return None, "invalid_source_box_shape"
    page = _coerce_page(parsed_box.page, num_pages)
    if page is None:
        return None, "out_of_range_page"
    box = _coerce_box(parsed_box.box)
    if box is None:
        return None, "malformed_coordinates"
    try:
        return SourceBox(page=page, box=box), None
    except ValidationError:
        return None, "malformed_coordinates"


def _coerce_question_id(value: Any) -> tuple[str | None, str | None]:
    """Coerce a wire-schema ``question_id`` value to a real string id.

    ``question_id`` is ``Any`` on ``_RawExtractedAnswer`` (US-031) so a
    numeric id (the model returning ``5`` instead of ``"5"``) reaches here
    instead of failing the wire-schema parse and losing the whole paper. A
    whole-numbered value is salvaged by stringifying it; anything that
    cannot identify an answer at all (``None``, a non-finite float, a
    dict/list) returns ``None`` with a reason -- the caller must drop the
    whole answer in that case, since there is nothing to key it by.

    Review MUST-FIX 5: a FRACTIONAL float (``1.1``) is rejected outright,
    never stringified, even though it superficially "salvages". ``str(1.1)
    == "1.1"``, and ``_canonical_id`` strips dots when matching against the
    mark scheme's manifest ids -- so ``"1.1"`` canonicalises to ``"11"`` and
    silently attaches this answer to a DIFFERENT real question (11) on an
    ordinary paper numbered 1..15, stamped ``id_match="exact"``
    downstream with no drop, no repair, and no event. A whole-numbered float
    (``5.0``) has no such collision risk and is still salvaged.
    """
    if isinstance(value, str):
        return value, None
    if isinstance(value, bool):
        return None, "malformed_question_id"
    if isinstance(value, int):
        return str(value), None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None, "malformed_question_id"
        return str(int(value)), None
    if value is None:
        return None, "missing_question_id"
    return None, "malformed_question_id"


def _parse_raw_answers(
    raw_answers: list[Any],
) -> list[tuple[_RawExtractedAnswer | None, str | None]]:
    """Validate each element of ``_ExtractorOutput.answers`` individually.

    ``_ExtractorOutput.answers`` is ``list[Any]`` (review MUST-FIX 6) so a
    malformed element -- a bare string, a positional list, ``null`` -- does
    not fail pydantic validation for the whole list and lose every other
    (possibly good) answer in the paper. ``BaseModel.model_validate`` always
    raises ``ValidationError`` (never a bare exception) for an input that is
    not a mapping, so catching only that is sufficient here -- verified
    empirically against a string, a list, ``None``, and an int element.
    Returns one ``(raw_answer, shape_reason)`` pair per element, in order;
    ``shape_reason`` is ``"malformed_answer_shape"`` when the element itself
    could not be shaped into a ``_RawExtractedAnswer`` at all (the caller
    drops the whole answer, same as an unrecoverable ``question_id``/
    ``answer``), and ``None`` otherwise.
    """
    parsed: list[tuple[_RawExtractedAnswer | None, str | None]] = []
    for element in raw_answers:
        try:
            parsed.append((_RawExtractedAnswer.model_validate(element), None))
        except ValidationError:
            parsed.append((None, "malformed_answer_shape"))
    return parsed


def _to_extracted_answer(
    raw: _RawExtractedAnswer, num_pages: int
) -> tuple[ExtractedAnswer | None, dict[str, str], str | None]:
    """Map the wire-only ``_RawExtractedAnswer`` onto the real ``ExtractedAnswer``.

    ``answer_reread`` / ``reread_agreement`` are left ``None`` here: they are
    not fields the model is asked for (see ``_RawExtractedAnswer``'s
    docstring) and are only ever set by the local crop-and-re-read step
    later in :meth:`GeminiAnswerExtractor.__call__`.

    US-031: every scalar field on ``raw`` is now untrusted ``Any`` (see the
    class docstring), so this function runs each one through its own
    ``_coerce_*``/``_sanitize_source_box`` salvage-or-drop step rather than
    assuming pydantic already validated it. ``question_id``/``answer`` are
    the two fields with no safe fallback -- an answer that cannot be
    identified, or that has no text at all, is not gradable -- so when
    either is unrecoverable this returns ``(None, reasons, dropped_question_id)``
    and the caller must drop the *whole answer* (never the whole paper).
    Every other field reason describes a same-answer salvage (a numeric
    id/text coerced to a string, a bad confidence replaced with
    :data:`_FALLBACK_CONFIDENCE` -- never clamped toward the model's
    out-of-range value, see ``_coerce_confidence`` -- a bad box dropped to
    ``None``) and the answer is still returned. ``reasons`` maps field name
    -> drop/repair reason for every field that needed one; a field absent
    from ``reasons`` needed no intervention.

    The third element, ``dropped_question_id`` (review MUST-FIX 7, stronger
    fix), is the coerced ``question_id`` when -- and ONLY when -- the answer
    is dropped *because its answer text was unusable*, i.e. ``question_id``
    itself salvaged fine. It lets the caller build
    ``ExtractedAnswers.dropped_question_ids`` so ``correct_paper`` can tell
    "this question's answer was extracted and discarded" from "no answer
    was extracted for this question at all" -- otherwise indistinguishable,
    since a dropped answer never reaches ``answers``. It is ``None`` in
    every other case (the answer was kept; or ``question_id`` itself was
    unrecoverable, in which case there is nothing to attribute the drop to).
    """
    reasons: dict[str, str] = {}

    question_id, qid_reason = _coerce_question_id(raw.question_id)
    if qid_reason is not None:
        reasons["question_id"] = qid_reason
    if question_id is None:
        return None, reasons, None

    answer_text, answer_reason = _coerce_answer_text(raw.answer)
    if answer_reason is not None:
        reasons["answer"] = answer_reason
    if answer_text is None:
        return None, reasons, question_id

    confidence, confidence_reason = _coerce_confidence(raw.confidence)
    if confidence_reason is not None:
        reasons["confidence"] = confidence_reason

    box, box_drop_reason = _sanitize_source_box(raw.source_box, num_pages)
    if box_drop_reason is not None:
        reasons["source_box"] = box_drop_reason

    # Review NIT A: these two optional fields used to be discarded silently
    # (a numeric `source_region`/`working_out` produced no entry in any
    # count dict anywhere), breaking the `(value, drop_reason)` idiom every
    # other field in this function follows. The direction was already safe
    # -- dropping `working_out` only forfeits its +0.05 calibration bonus --
    # but the silence itself was the defect: record the reason like every
    # other field does, even though there is no unsafe consequence to guard
    # against here.
    source_region = raw.source_region if isinstance(raw.source_region, str) else None
    if raw.source_region is not None and source_region is None:
        reasons["source_region"] = "malformed_source_region"
    working_out = raw.working_out if isinstance(raw.working_out, str) else None
    if raw.working_out is not None and working_out is None:
        reasons["working_out"] = "malformed_working_out"

    answer = ExtractedAnswer(
        question_id=question_id,
        answer=answer_text,
        confidence=confidence,
        source_region=source_region,
        source_box=box,
        working_out=working_out,
    )
    return answer, reasons, None


@dataclass(frozen=True, slots=True)
class _LegacyReply:
    """One reply of the legacy extraction call, converted, with what was dropped on the way.

    ``total`` counts every element of the reply, kept or dropped.
    """

    answers: list[ExtractedAnswer]
    total: int
    source_box_drops: dict[str, int]
    answer_drops: dict[str, int]
    confidence_repairs: dict[str, int]
    field_repairs: dict[str, int]
    dropped_question_ids: list[str]


def _convert_reply(raw_answers: list[Any], num_pages: int) -> _LegacyReply:
    """Turn the legacy call's ``answers`` into ``ExtractedAnswer``s, counting every drop."""
    # US-031 review MUST-FIX 6: validate each list element individually
    # -- a malformed element (a bare string, a positional list, `null`)
    # must not fail pydantic validation for the whole `answers` list and
    # lose every other, possibly good, answer with it. An element that
    # cannot be shaped into a _RawExtractedAnswer at all is folded into
    # the same "whole answer dropped" bucket _to_extracted_answer's own
    # unrecoverable question_id/answer case uses, under the
    # "malformed_answer_shape" reason.
    converted: list[tuple[ExtractedAnswer | None, dict[str, str], str | None]] = []
    for raw_answer, shape_reason in _parse_raw_answers(raw_answers):
        if raw_answer is None:
            converted.append((None, {"shape": shape_reason or "malformed_answer_shape"}, None))
            continue
        converted.append(_to_extracted_answer(raw_answer, num_pages))
    answers = [a for a, _reasons, _dropped_qid in converted if a is not None]

    # US-031: a bad question_id/answer/list-element shape drops the
    # whole *answer* here (there is nothing left to key or grade), never
    # the whole paper -- counted the same way I1 review finding 5
    # already counts source_box drops, so the loss is visible rather
    # than a paper silently coming back short.
    answer_drops: dict[str, int] = {}
    # I1 review finding 5: an out-of-range page index and a malformed
    # coordinate are both silently dropped to source_box=None inside
    # _to_extracted_answer -- surface the count so a later box-hit-rate
    # metric's denominator shape is visible rather than implicit. Kept
    # (not just published) below on ExtractedAnswers.source_box_drops
    # (I1 review round 2, should-fix 4) so the count travels with the
    # record a box-hit-rate metric actually reads, not only a live event.
    source_box_drops: dict[str, int] = {}
    # US-031: confidence can't be dropped to None like source_box (it is
    # required) -- an unusable value is instead replaced with
    # _FALLBACK_CONFIDENCE, and that repair is counted here the same
    # way, so a metric reading ExtractedAnswers can tell "the model gave
    # a real confidence" from "this run had to fabricate one".
    confidence_repairs: dict[str, int] = {}
    # Review NIT A: source_region/working_out are cosmetic (not part of
    # marking or matching), so a bad value here never drops the answer
    # -- but it must still be counted, not silently discarded, to keep
    # the same (value, drop_reason) idiom every other field follows.
    field_repairs: dict[str, int] = {}
    # US-031 review MUST-FIX 7 (stronger fix): the subset of dropped
    # answers whose question_id survived coercion -- i.e. the answer
    # itself, not its identity, was unusable. correct_paper needs this
    # to tell "extracted and dropped" apart from "never extracted at
    # all"; see ExtractedAnswers.dropped_question_ids.
    dropped_question_ids: list[str] = []
    for a, reasons, dropped_qid in converted:
        if a is None:
            reason = (
                reasons.get("shape")
                or reasons.get("question_id")
                or reasons.get("answer")
                or "unknown"
            )
            answer_drops[reason] = answer_drops.get(reason, 0) + 1
            if dropped_qid is not None:
                dropped_question_ids.append(dropped_qid)
            continue
        if "confidence" in reasons:
            reason = reasons["confidence"]
            confidence_repairs[reason] = confidence_repairs.get(reason, 0) + 1
        if "source_box" in reasons:
            reason = reasons["source_box"]
            source_box_drops[reason] = source_box_drops.get(reason, 0) + 1
        for field_name in ("source_region", "working_out"):
            if field_name in reasons:
                reason = reasons[field_name]
                field_repairs[reason] = field_repairs.get(reason, 0) + 1
    return _LegacyReply(
        answers=answers,
        total=len(converted),
        source_box_drops=source_box_drops,
        answer_drops=answer_drops,
        confidence_repairs=confidence_repairs,
        field_repairs=field_repairs,
        dropped_question_ids=dropped_question_ids,
    )


def _publish_reply_drops(reply: _LegacyReply) -> None:
    """Publish what converting ``reply`` dropped or repaired, when it did either."""
    source_box_drops = reply.source_box_drops
    answer_drops = reply.answer_drops
    confidence_repairs = reply.confidence_repairs
    field_repairs = reply.field_repairs
    if source_box_drops:
        bus.publish(
            EventType.SOURCE_BOX_DROPPED,
            counts=source_box_drops,
            total_answers=reply.total,
        )
    # US-031 review MUST-FIX 7: a comment here previously claimed this
    # loss was "visible… the same way source_box drops are" while
    # publishing nothing -- answer_drops/confidence_repairs had zero
    # consumers anywhere in the tree. Publish for real, the same way
    # SOURCE_BOX_DROPPED is published immediately above, so the claim is
    # true. This event is TELEMETRY, not the review gate: the flagging is
    # wired through `ExtractedAnswers.dropped_question_ids`, which
    # `correct_paper` short-circuits on before dispatching to the MCQ or
    # AI path (review MUST-FIX 7, stronger fix). So a dropped answer is
    # flagged and costs no marking call -- but only for the two reasons
    # that leave a usable question_id (`missing_answer`,
    # `malformed_answer`). The other three (`missing_question_id`,
    # `malformed_question_id`, `malformed_answer_shape`) have no id to
    # attribute a flag to, and what that costs depends on the leaf. On a
    # non-MCQ leaf with an AI marker configured the paid call is CERTAIN
    # (`ai.mark_question` is reached unconditionally) and the confident
    # unflagged mark is CONTINGENT -- it needs the model's response to
    # clear all four of `_build_ai_corrected`'s review gates, which it
    # CAN. An MCQ leaf (or `--mcq-only`/no client) is already flagged at
    # 0.0 with no call, but only because the absent id looks exactly like a
    # genuine blank, so review_reason carries that path's blank message
    # instead of the truth. See `CorrectedQuestion.marker_source`'s
    # coverage-limit note (review MUST-FIX F1) for the full split.
    # These counts are also KEPT, not only published: `answer_drops` is a
    # field on `ExtractedAnswers`, the same reasoning as `source_box_drops`
    # above, so the per-reason totals travel with the record and this event
    # is not the only trace of what was dropped.
    if answer_drops or confidence_repairs or field_repairs:
        bus.publish(
            EventType.ANSWER_DROPPED,
            answer_drops=answer_drops,
            confidence_repairs=confidence_repairs,
            field_repairs=field_repairs,
            total_answers=reply.total,
        )


#: What the label reader's drop reasons are stored under in
#: ``ExtractedAnswers.answer_drops`` (``stream_repaired_page``, ``stream_unknown_type``,
#: ...), beside the legacy extractor's own reasons.
STREAM_DROP_PREFIX = "stream_"

# Spec 2026-09-26 §5: the tag each `_run_rereads` worker reports for one
# answer -- "stopped"/"budget" never issue a call; "done"/"failed"/"ceiling"
# all count as started (see `_run_rereads`'s docstring).
_RereadOutcome = Literal["stopped", "budget", "done", "failed", "ceiling"]


class GeminiAnswerExtractor:
    def __init__(
        self,
        gemini_client: GeminiClient,
        *,
        reread_confidence_threshold: float | None = None,
        max_rereads_per_paper: int | None = None,
    ) -> None:
        self._client = gemini_client
        self._rereader = Rereader(gemini_client)
        self._reread_confidence_threshold = reread_confidence_threshold
        # Spec 2026-09-26 §4: the keyword is an explicit override (tests, the
        # harness); `None` -- what every production construction site passes
        # -- reads `gemini.max_rereads_per_paper`, so the cap is configured,
        # not hard-coded. 0 disables the stage.
        if max_rereads_per_paper is not None and max_rereads_per_paper < 0:
            # Fix round 1: unlike 0 (a genuine "disable the stage"), a
            # negative value has no such meaning and must not be accepted
            # silently -- `sorted(...)[:max_rereads_per_paper]` (the cap
            # slice in __call__) would otherwise treat a negative cap as
            # Python's "drop the last N" slicing instead of "keep none",
            # capping the WRONG end of the lowest-confidence-first list.
            raise ValueError(f"max_rereads_per_paper must be >= 0, got {max_rereads_per_paper}")
        settings = gemini_client._settings.gemini
        self._max_rereads_per_paper = (
            max_rereads_per_paper
            if max_rereads_per_paper is not None
            else settings.max_rereads_per_paper
        )

    def _run_rereads(
        self,
        answers: list[ExtractedAnswer],
        to_reread: list[int],
        pages: list[RasterisedPage],
        *,
        extra_cache_key: str,
    ) -> tuple[list[ExtractedAnswer], int, int]:
        """Run the crop re-reads for ``to_reread`` concurrently under a budget.

        Spec 2026-09-26 §5. ``to_reread`` is lowest-confidence first. Up to
        ``gemini.reread_concurrency`` workers run; each checks the deadline
        and the stop event BEFORE issuing its call, so no re-read starts
        after ``gemini.reread_budget_seconds`` or after a ceiling breach --
        calls already in flight finish (an HTTPS call cannot be aborted; the
        retry policy bounds it), so the per-run token/USD ceiling can still
        be overshot by up to ``reread_concurrency - 1`` calls already in
        flight when the breach is detected. Every worker runs under
        ``contextvars.copy_context().run`` so its bus events carry the run
        id.

        Fix round 1: ANY exception escaping a worker (not only
        ``CostCeilingError``) sets the stop event before propagating --
        without this, an unrelated crash (a bug, a bare ``ValueError``) left
        `stop` unset, so every already-queued worker still issued its
        (paid) re-read call before the exception could even be observed.
        The result loop drains every future to completion before deciding
        what to raise, so a ``CostCeilingError`` on one worker is never
        masked by an unrelated exception that another worker happened to
        raise (or that this loop observed) first -- the ceiling always
        wins. Any ``LemelyError`` short of a ceiling breach still degrades
        to a per-answer ``REREAD_FAILED`` event, as before. Results come
        back in the extractor's answer order whatever order they finished
        in; an answer not re-read keeps its first read.

        Returns ``(answers, started, skipped_by_budget)``.
        """
        g = self._client._settings.gemini
        deadline = time.monotonic() + g.reread_budget_seconds
        stop = threading.Event()

        def _one(index: int) -> tuple[int, _RereadOutcome, ExtractedAnswer | BaseException | None]:
            if stop.is_set():
                return index, "stopped", None
            if time.monotonic() >= deadline:
                return index, "budget", None
            answer = answers[index]
            try:
                return (
                    index,
                    "done",
                    self._rereader.reread(answer, pages, extra_cache_key=extra_cache_key),
                )
            except CostCeilingError as exc:
                # I1 review round 2, MUST-FIX 1: a ceiling breach is a stop
                # signal for the whole run, never a per-answer failure.
                stop.set()
                return index, "ceiling", exc
            except LemelyError as exc:
                # I1 review MUST-FIX 2: a re-read is an enhancement and must
                # never take the paper's extraction down with it.
                bus.publish(EventType.REREAD_FAILED, question_id=answer.question_id, error=str(exc))
                return index, "failed", exc
            except BaseException:
                # Fix round 1: an exception this method does not otherwise
                # know how to degrade (not a LemelyError) must still stop
                # every worker that has not yet started its own call --
                # re-raising alone, with `stop` left unset, let each
                # already-queued worker run to completion first.
                stop.set()
                raise

        results: dict[int, ExtractedAnswer] = {}
        started = 0
        skipped_by_budget = 0
        ceiling: BaseException | None = None
        unexpected: BaseException | None = None
        if to_reread:
            with ThreadPoolExecutor(max_workers=min(g.reread_concurrency, len(to_reread))) as pool:
                futures = [
                    pool.submit(contextvars.copy_context().run, _one, index) for index in to_reread
                ]
                # Fix round 1: drain EVERY future before deciding what to
                # raise -- a `future.result()` call that raises immediately
                # would abandon the rest of the loop, so a CostCeilingError
                # returned (not raised -- see `_one`) by a later future
                # could be lost behind an earlier, unrelated crash.
                for future in futures:
                    try:
                        index, outcome, value = future.result()
                    except BaseException as exc:
                        # Fix round 2: `future.result()` re-raises whatever
                        # `_one` raised in ITS worker thread (already
                        # covered by round 1's fix, which sets `stop`
                        # there) -- but it can ALSO raise a real
                        # KeyboardInterrupt/SystemExit delivered to THIS
                        # (main) thread while it was blocked waiting, which
                        # never touches `_one` or its own `stop.set()` at
                        # all. Set `stop` here unconditionally so that case
                        # is covered too, then treat a non-Exception
                        # BaseException (KeyboardInterrupt/SystemExit/
                        # GeneratorExit) as un-degradable: propagate it
                        # immediately rather than deferring it into
                        # `unexpected` and draining the rest of the futures
                        # first -- deferring it let an already-resolved
                        # CostCeilingError on a LATER future (round 1
                        # regression) win the ceiling-vs-unexpected
                        # precedence below and lose the interrupt entirely.
                        # The pool's `with` still only waits for whatever
                        # is already in flight (an HTTPS call can't be
                        # aborted); nothing not yet started issues a call,
                        # since `_one` checks `stop` before doing anything.
                        stop.set()
                        if not isinstance(exc, Exception):
                            raise
                        if unexpected is None:
                            unexpected = exc
                        continue
                    if outcome in ("done", "failed", "ceiling"):
                        started += 1
                    if outcome == "done":
                        results[index] = cast(ExtractedAnswer, value)
                    elif outcome == "ceiling":
                        if ceiling is None:
                            ceiling = cast(BaseException, value)
                    elif outcome == "budget":
                        skipped_by_budget += 1
        if ceiling is not None:
            raise ceiling
        if unexpected is not None:
            raise unexpected
        if skipped_by_budget:
            bus.publish(
                EventType.REREAD_BUDGET_EXHAUSTED,
                budget_seconds=g.reread_budget_seconds,
                started=started,
                skipped=skipped_by_budget,
            )
        return [results.get(i, a) for i, a in enumerate(answers)], started, skipped_by_budget

    def _legacy_reply(
        self,
        mark_scheme: MarkScheme,
        page_bytes: list[bytes],
        uploads: ImageUploads,
        *,
        extra_cache_key: str,
        model: str | None = None,
    ) -> _LegacyReply:
        """The legacy extraction call (the model hands out question ids), converted.

        With no ``model`` this is the call extraction has always made, argument for
        argument. ``model`` is passed only by the binding gate's one retry.
        """
        call = functools.partial(
            self._client.generate_structured,
            system_prompt=EXTRACTOR_SYSTEM_PROMPT,
            user_prompt=build_extractor_user_prompt(mark_scheme, page_count=len(page_bytes)),
            image_parts=page_bytes,
            image_uploads=uploads,
            media_resolution=EXTRACTION_MEDIA_RESOLUTION,
            response_schema=_ExtractorOutput,
            prompt_version=VERSION,
            extra_cache_key=extra_cache_key,
            task_tag="extraction",
        )
        raw = call() if model is None else call(model=model)
        return _convert_reply(raw.answers, len(page_bytes))

    def _gated_legacy(
        self,
        reply: _LegacyReply,
        mark_scheme: MarkScheme,
        page_bytes: list[bytes],
        uploads: ImageUploads,
        manifest_key: str,
        manifest_ids: list[str],
    ) -> tuple[_LegacyReply, BindingReport | None]:
        """Run the binding gate over the legacy call's answers; return the reply to go on with.

        The checks compare ids with the mark scheme's, so they see a copy of the
        answers with ids mapped the way ``normalize_extracted_answers`` maps them at
        the end; the answers that go on keep the ids the model gave until then, as
        they always have. The retry is the same call on ``binding.retry_model`` under
        its own cache key. The reply that goes on has ``binding_source="legacy"`` on
        every answer and ``binding_status="unverified"`` on those a question-scope
        check names; the checks passing verifies no single answer, so the rest are
        left unset. Under ``gate="observe"`` there is no report and the reply comes
        back untouched: the gate has published what it saw and changes nothing.
        """
        settings = self._client._settings
        canonical = {_canonical_id(mid): mid for mid in manifest_ids}
        retried: list[_LegacyReply] = []

        def _for_gate(converted: _LegacyReply) -> LegacyRead:
            mapped = normalize_extracted_answers(
                ExtractedAnswers(paper_id="", source_scan="", answers=converted.answers),
                manifest_ids,
            )
            return LegacyRead(answers=mapped.answers, drops=converted.answer_drops)

        def _retry() -> LegacyRead:
            again = self._legacy_reply(
                mark_scheme,
                page_bytes,
                uploads,
                extra_cache_key=manifest_key + "|retry",
                model=settings.binding.retry_model,
            )
            retried.append(again)
            return _for_gate(again)

        outcome = gate_legacy(
            _for_gate(reply),
            mark_scheme,
            settings=settings,
            model=settings.gemini.model_for("extraction"),
            retry=_retry,
        )
        if outcome.report is None:
            return reply, None
        used = retried[0] if outcome.used_retry else reply

        def _stamped(answer: ExtractedAnswer) -> ExtractedAnswer:
            mapped_id = canonical.get(_canonical_id(answer.question_id), answer.question_id)
            update: dict[str, str] = {"binding_source": "legacy"}
            if mapped_id in outcome.unverified_ids:
                update["binding_status"] = "unverified"
            return answer.model_copy(update=update)

        return replace(used, answers=[_stamped(a) for a in used.answers]), outcome.report

    def __call__(self, scan_path: Path, mark_scheme: MarkScheme) -> ExtractedAnswers:
        """Extract ``scan_path``'s answers against ``mark_scheme``, one run at a time.

        The rendered pages live in this process from the render to the
        return, so the whole extraction holds a run slot
        (:func:`~lemely.io.run_cap.marking_run_slot`, #260, #271): a second
        call waits for the first to finish, and never fails for waiting.
        """
        with marking_run_slot():
            return self._extract(scan_path, mark_scheme)

    def _extract(self, scan_path: Path, mark_scheme: MarkScheme) -> ExtractedAnswers:
        """:meth:`__call__`'s work, under its run slot.

        ``binding.binder`` decides where the answers come from: the label binder
        (:func:`~lemely.io.binding.orchestrate.run_binding`) or the legacy call.
        Either way they then go through the same steps: confidence calibration, the
        optional text second reader, crop re-reads, progress events, id
        normalisation. With the gate enforcing the result carries the binding report;
        with it off or observing (the legacy binder only) it carries none.
        """
        manifest_key = build_question_manifest_hash_key(mark_scheme)

        # I1: rasterise to per-page images rather than uploading the whole
        # PDF -- bounding boxes are documented for image inputs only, and one
        # call carrying every page keeps cross-page question context that a
        # per-page call would lose.
        pages: list[RasterisedPage] = rasterise_scan_to_pages(scan_path)

        # Carry-over from spec 2026-09-26 review: a page can be rendered
        # below EXTRACTION_DPI (lemely.io.scan_limits' downscale-on-oversize
        # path), so the hygiene check must be told the real DPI it was
        # rasterised at -- otherwise a downscaled scan's warning claims
        # "200 DPI" when the page was actually rendered lower.
        hygiene = check_scan_hygiene(pages, dpi=min(p.dpi for p in pages))
        if hygiene.warnings:
            # T2.6: never silent. Surfaced as a bus event regardless of
            # severity -- the UI/caller decides what to do with it, this
            # layer never drops a bad-scan finding on the floor.
            bus.publish(
                EventType.SCAN_QUALITY_WARNING,
                warnings=hygiene.warnings,
                page_count_actual=hygiene.page_count_actual,
                page_count_expected=hygiene.page_count_expected,
            )

        g = self._client._settings.gemini
        binding = self._client._settings.binding

        reread_kwargs = (
            {}
            if self._reread_confidence_threshold is None
            else {"confidence_threshold": self._reread_confidence_threshold}
        )
        # The threshold actually in effect (constructor override, else
        # should_reread's own default) -- persisted on the result below so a
        # later reader knows what gated re-read eligibility on this run.
        effective_reread_threshold = self._reread_confidence_threshold
        if effective_reread_threshold is None:
            effective_reread_threshold = DEFAULT_CONFIDENCE_THRESHOLD

        # Spec 2026-09-26 §7: page images go through the Files API, uploaded
        # lazily (only on a cache miss) and once per paper -- the second read
        # below reuses the same URIs -- and deleted on exit, whatever happens.
        page_bytes = [p.png_bytes for p in pages]
        with self._client.image_uploads(page_bytes, concurrency=g.upload_concurrency) as uploads:
            # Build a type-hint map from mark scheme for calibration
            type_hint_map: dict[str, str] = {}
            for q in mark_scheme.all_questions_flat():
                if not q.parts and q.marks > 0:
                    type_hint_map[q.id] = q.type.value
            manifest_ids = [
                q.id for q in mark_scheme.all_questions_flat() if q.marks > 0 and not q.parts
            ]

            # What only a bound, gated extraction carries. Left out of the result
            # altogether when there is none, so that a legacy extraction with the gate
            # off is the same record it has always been.
            bound_fields: dict[str, Any] = {}
            if binding.binder == "label":
                # The label binder replaces the primary call: the model lists labels
                # and writing with no question ids, `bind_stream` binds them, and the
                # gate says how far the binding can be trusted
                # (lemely.io.binding.orchestrate).
                outcome = run_binding(
                    self._client,
                    pages,
                    mark_scheme,
                    uploads=uploads,
                    settings=self._client._settings,
                    manifest_key=manifest_key,
                )
                answers = outcome.answers
                source_box_drops: dict[str, int] = {}
                # The label reader's reply items left out or repaired, by reason
                # (`StreamRead.drops`): kept on the record like the legacy counts
                # are, each under a `stream_` prefix so that none can be taken for
                # one of the legacy extractor's whole-answer reasons.
                answer_drops = {
                    f"{STREAM_DROP_PREFIX}{reason}": count
                    for reason, count in outcome.drops.items()
                }
                confidence_repairs: dict[str, int] = {}
                field_repairs: dict[str, int] = {}
                # The label reader's reply is never converted answer by answer, so
                # nothing is dropped as a malformed answer on this path.
                dropped_question_ids: list[str] = []
                # A leaf no label was lined up with has no answer here, and that is
                # not a blank: whatever the student wrote for it could not be bound
                # (it is in `unbound_answers`, or under the leaf before). Listing it
                # makes `correct_paper` send it to a teacher without attempting a
                # mark, where a missing answer alone would be an unflagged zero.
                bound_fields["unbound_question_ids"] = list(outcome.review_only_ids)
                bound_fields["unbound_answers"] = outcome.unbound
                bound_fields["binding"] = outcome.report
            else:
                reply = self._legacy_reply(
                    mark_scheme, page_bytes, uploads, extra_cache_key=manifest_key
                )
                if binding.gate != "off":
                    reply, legacy_report = self._gated_legacy(
                        reply, mark_scheme, page_bytes, uploads, manifest_key, manifest_ids
                    )
                    if legacy_report is not None:
                        bound_fields["binding"] = legacy_report
                _publish_reply_drops(reply)
                answers = reply.answers
                source_box_drops = reply.source_box_drops
                answer_drops = reply.answer_drops
                confidence_repairs = reply.confidence_repairs
                field_repairs = reply.field_repairs
                dropped_question_ids = reply.dropped_question_ids

            calibrated: list[ExtractedAnswer] = []
            for a in answers:
                hint = type_hint_map.get(a.question_id)
                new_conf = _calibrate_confidence(a, question_type_hint=hint)
                a = a.model_copy(update={"confidence": new_conf})
                calibrated.append(a)
            answers = calibrated

            # I3 (US-010, label-free half): an independent second read of the
            # whole paper, if configured (default "none" -- no second call, no
            # behaviour change). Populates extraction_agreement per answer,
            # matched by question_id; an answer the second read did not return
            # keeps extraction_agreement=None (see compute_agreement).
            second_reader = build_second_reader(self._client, g)
            if second_reader is not None:
                try:
                    second_read_texts: dict[str, str] | None = second_reader.read(
                        mark_scheme, page_bytes, extra_cache_key=manifest_key, image_uploads=uploads
                    )
                except CostCeilingError:
                    # A per-run ceiling breach is a stop signal for the whole
                    # run (I1 review round 2, MUST-FIX 1) -- re-raised first,
                    # exactly as the re-read block below does.
                    raise
                except LemelyError as exc:
                    # Spec 2026-09-26 §8 (#3): the second read is an
                    # enhancement on a paid primary extraction and must never
                    # take it down. Keep the primary answers (agreement stays
                    # None) and surface the failure.
                    bus.publish(
                        EventType.SECOND_READ_FAILED,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                    second_read_texts = None
                if second_read_texts is not None:
                    agreements = compute_agreement(answers, second_read_texts)
                    answers = [
                        a.model_copy(update={"extraction_agreement": agreements[a.question_id]})
                        if a.question_id in agreements
                        else a
                        for a in answers
                    ]

            # Crop-and-re-read: a second, zoomed-in look at exactly the pixels
            # each low-confidence answer's own box says the answer lives in.
            #
            # I1 review finding 9: uncapped, a paper with 30 low-confidence
            # answers issued 31 total API calls. Cap the number of re-reads
            # actually run per paper (gemini.max_rereads_per_paper, spec
            # 2026-09-26 §4 -- overridable via the constructor keyword of the
            # same name), spending the cap on the lowest-confidence answers
            # first since those are the ones re-reading helps most, and
            # record when the cap binds so the count is visible rather than
            # the re-read set silently truncating. The capped set then runs
            # through ``_run_rereads`` (spec 2026-09-26 §5: concurrent,
            # budgeted), not a plain sequential loop.
            #
            # I3: low cross-read agreement (< REREAD_AGREEMENT_THRESHOLD) also
            # makes an answer eligible, alongside should_reread's confidence-only
            # check -- wired HERE rather than inside should_reread
            # (lemely.io.reread) because reread.py is outside this story's file
            # ownership; should_reread's own contract is unchanged. With the
            # default second_reader="none", extraction_agreement is always None
            # and this condition can never fire, so behaviour is unchanged on
            # every existing path. The same cap/sort logic below stays generic
            # over why an answer became eligible.
            def _agreement_triggers_reread(a: ExtractedAnswer) -> bool:
                return (
                    a.source_box is not None
                    and a.extraction_agreement is not None
                    and a.extraction_agreement < REREAD_AGREEMENT_THRESHOLD
                )

            eligible_indices = [
                i
                for i, a in enumerate(answers)
                if should_reread(a, **reread_kwargs) or _agreement_triggers_reread(a)
            ]
            to_reread = sorted(eligible_indices, key=lambda i: answers[i].confidence)[
                : self._max_rereads_per_paper
            ]
            if len(eligible_indices) > len(to_reread):
                bus.publish(
                    EventType.REREAD_CAP_REACHED,
                    eligible=len(eligible_indices),
                    cap=self._max_rereads_per_paper,
                    skipped=len(eligible_indices) - len(to_reread),
                )
            answers, reread_started, reread_skipped_by_budget = self._run_rereads(
                answers, to_reread, pages, extra_cache_key=manifest_key
            )
            # `index` is the 1-based position inside `answers` (from enumerate), not a
            # tally of frames already emitted. Should a publish ever be skipped for one
            # answer, the later indices still match the real work list, so the UI's
            # "Question 7 of 21" keeps pointing at the question actually being reported.
            total_answers = len(answers)
            for index, a in enumerate(answers, start=1):
                bus.publish(
                    EventType.EXTRACTION_PROGRESS,
                    question_id=a.question_id,
                    confidence=a.confidence,
                    has_working=a.working_out is not None,
                    index=index,
                    total=total_answers,
                )
            normalized_result = normalize_extracted_answers(
                ExtractedAnswers(
                    paper_id=_build_paper_id(mark_scheme),
                    source_scan=str(scan_path),
                    answers=answers,
                    source_box_drops=source_box_drops,
                    answer_drops=answer_drops,
                    confidence_repairs=confidence_repairs,
                    field_repairs=field_repairs,
                    dropped_question_ids=dropped_question_ids,
                    rereads_eligible=len(eligible_indices),
                    reread_attempts=reread_started,
                    reread_skipped_by_budget=reread_skipped_by_budget,
                    reread_threshold=effective_reread_threshold,
                    **bound_fields,
                ),
                manifest_ids,
            )
        return normalized_result
