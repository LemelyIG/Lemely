"""Per-field coercion of values a model returned, shared by the extraction readers.

Each helper takes one untrusted value off a model's reply and returns a usable value
or ``None``, never raising for a shape a model might plausibly emit. They live here,
apart from ``lemely.io.answer_extraction`` (which re-exports them under the same
names), so that the label binder can use them without importing the extractor that
calls it. Their parameters are typed ``object`` here: every branch narrows by
``isinstance``, so nothing needs the ``Any`` the wire schemas use.
"""

from __future__ import annotations

import math


def _coerce_page(page: object, num_pages: int) -> int | None:
    """Coerce a wire-schema ``page`` value to a real, in-range page index.

    Accepts anything a model might plausibly emit for an integer page index
    (a whole-numbered float, a numeric string) without raising -- ``page``
    on ``_RawSourceBox`` is ``Any`` precisely so a value this function
    cannot make sense of (``None``, a fractional float, "top-right") reaches
    here instead of failing the wire-schema parse. Returns ``None`` for
    anything that is not, or cannot be turned into, an in-range integer
    index (I1 review round 2, MUST-FIX 2).
    """
    if isinstance(page, bool):  # bool is an int subclass; not a page index
        return None
    p: int | None = None
    if isinstance(page, int):
        p = page
    elif isinstance(page, float):
        # I1 review round 4, MUST-FIX B: `Infinity`/`NaN`/an overflowing
        # exponent are valid JSON-extension literals that pydantic's own
        # JSON parser accepts, and `page` is `Any` so nothing rejects them
        # before this function sees them. `float.is_integer()` is already
        # False for `inf`/`nan` (round 4 review, correction: an earlier
        # comment here claimed the opposite), so `not page.is_integer()`
        # alone already rejects them and `int(page)` below is unreachable
        # with a non-finite value -- the explicit `math.isfinite` check is
        # not load-bearing today. Kept anyway as defence in depth: it makes
        # the "never hand a non-finite value to int()" invariant explicit
        # rather than resting on `is_integer()`'s non-finite behaviour,
        # which is easy to get backwards (as this comment did) and easy to
        # break by accident in a future edit.
        if not math.isfinite(page) or not page.is_integer():
            return None
        p = int(page)
    elif isinstance(page, str):
        try:
            p = int(page)
        except ValueError:
            try:
                f = float(page)
            except ValueError:
                return None
            # Same defence-in-depth note as the float branch above:
            # `f.is_integer()` is already False for non-finite `f`.
            if not math.isfinite(f) or not f.is_integer():
                return None
            p = int(f)
    if p is None or not (0 <= p < num_pages):
        return None
    return p


def _coerce_box(box: object) -> list[int] | None:
    """Coerce a wire-schema ``box`` value to four ``int`` coordinates.

    ``box`` on ``_RawSourceBox`` is ``Any`` so a shape a model might
    plausibly emit -- a fractional normalised coordinate, a numeric string,
    or the whole field returned as a prose string instead of four numbers --
    reaches here instead of failing the wire-schema parse and paying for a
    second full-paper corrective call (I1 review round 2, MUST-FIX 2).
    Returns ``None`` for anything that is not four coercible numbers;
    range/positive-area validation still happens afterwards, in
    ``SourceBox`` itself.
    """
    if not isinstance(box, list) or len(box) != 4:
        return None
    coerced: list[int] = []
    for value in box:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            coerced.append(value)
        elif isinstance(value, float):
            # I1 review round 4, MUST-FIX B: `round()` on a non-finite float
            # raises a bare OverflowError (`inf`) or ValueError (`nan`), not
            # a LemelyError -- and `Infinity`/`NaN` are valid JSON-extension
            # literals pydantic's own JSON parser accepts into this `Any`
            # field. Treat non-finite the same as any other unparseable
            # coordinate: drop to malformed_coordinates instead of raising.
            if not math.isfinite(value):
                return None
            coerced.append(round(value))
        elif isinstance(value, str):
            try:
                f = float(value)
            except ValueError:
                return None
            if not math.isfinite(f):
                return None
            coerced.append(round(f))
        else:
            return None
    return coerced


def _coerce_answer_text(value: object) -> tuple[str | None, str | None]:
    """Coerce a wire-schema ``answer`` value to a real string.

    Same rationale as :func:`_coerce_question_id`: ``answer`` is ``Any`` so a
    numeric answer (``42`` instead of ``"42"``) reaches here instead of
    failing the wire-schema parse. A numeric answer is salvaged by
    stringifying it; anything with no usable text at all drops the whole
    answer.
    """
    if isinstance(value, str):
        return value, None
    if isinstance(value, bool):
        return None, "malformed_answer"
    if isinstance(value, int):
        return str(value), None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None, "malformed_answer"
        return (str(int(value)) if value.is_integer() else str(value)), None
    if value is None:
        return None, "missing_answer"
    return None, "malformed_answer"


#: Confidence substituted in when the model's own value cannot be trusted at
#: all (missing, non-finite, out-of-range, or some other unparseable shape)
#: -- deliberately the lowest possible value rather than a mid-range guess,
#: so a fabricated confidence never reads as MORE trustworthy than a genuine
#: low one.
#:
#: Review SHOULD-FIX A: this is bookkeeping only, not (currently) a live
#: gate. ``should_reread`` (:mod:`lemely.io.reread`) returns ``False``
#: outright whenever ``source_box is None`` -- which is exactly the two
#: source_box-malformed shapes ``lemely.io.answer_extraction`` salvages --
#: so "becomes reread-eligible" does not actually hold for every caller of
#: this fallback. Downstream, ``extraction_confidence`` is not one of
#: ``correction_ai._build_ai_corrected``'s review gates either. The
#: repair is still recorded (:data:`ExtractedAnswers.confidence_repairs`,
#: :data:`EventType.ANSWER_DROPPED`) so a future gate can consume it; none
#: does yet.
_FALLBACK_CONFIDENCE = 0.0


def _coerce_confidence(value: object) -> tuple[float, str | None]:
    """Coerce a wire-schema ``confidence`` value to an in-range ``float``.

    ``confidence`` is ``Any`` on ``_RawExtractedAnswer`` (US-031) so NaN,
    Infinity, an out-of-range value, or a missing value all reach here
    instead of failing pydantic's ``Field(..., ge=0.0, le=1.0)`` constraint
    and losing the whole paper. Unlike ``source_box``, ``confidence`` cannot
    be dropped to ``None`` -- ``ExtractedAnswer.confidence`` is required --
    so every unusable value, including an out-of-range one, is replaced with
    :data:`_FALLBACK_CONFIDENCE`, returning a reason so the caller can count
    and surface the repair rather than silently reporting a value the model
    never actually gave.

    Out-of-range is NOT clamped toward the bound it overshot (review fix:
    an earlier version clamped ``f > 1.0`` up to ``1.0``, the *most*
    confident value in range). ``should_reread``
    (:mod:`lemely.io.reread`, ``confidence < threshold``) and
    ``correction_ai``'s low-confidence review flag
    (``confidence < REVIEW_CONFIDENCE_THRESHOLD``) both gate on LOW
    confidence -- clamping a contract violation up to ``1.0`` would suppress
    both the local re-read and the human review flag for the one shape that
    demonstrably violated the model's own output contract. Only ``f < 0.0``
    already clamped to the safe (``0.0``, high-scrutiny) side; the fix here
    makes the whole function agree that a value outside ``[0, 1]`` is
    untrusted, never trusted, regardless of which side it overshot.
    """
    if isinstance(value, bool):
        return _FALLBACK_CONFIDENCE, "malformed"
    if isinstance(value, (int, float)):
        f = float(value)
    elif isinstance(value, str):
        try:
            f = float(value)
        except ValueError:
            return _FALLBACK_CONFIDENCE, "malformed"
    elif value is None:
        return _FALLBACK_CONFIDENCE, "missing"
    else:
        return _FALLBACK_CONFIDENCE, "malformed"
    if not math.isfinite(f):
        return _FALLBACK_CONFIDENCE, "non_finite"
    if f < 0.0 or f > 1.0:
        return _FALLBACK_CONFIDENCE, "out_of_range"
    return f, None
