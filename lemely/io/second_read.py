"""SecondReader protocol (I3) -- second-read agreement seam, US-010 label-free half.

Produces `ExtractedAnswer.extraction_agreement`: a cross-read agreement score
between the primary paper-level extraction and an INDEPENDENT second read of
the same paper, matched by `question_id`. This is NOT `reread_agreement`
(`lemely.io.reread`) -- I1's crop-and-re-read similarity between ONE answer
and its own zoomed-in re-extraction from `source_box`. The two are separate
measurements with separate triggers; see both fields' docstrings on
`ExtractedAnswer` (`lemely.core.schemas`).

Two implementations of the `SecondReader` protocol, selected by
`GeminiSettings.second_reader`:

- `cross_model`: the second read runs the SAME extraction prompt on a
  DIFFERENT model (`GeminiSettings.second_read_model`, default
  "gemini-3.8-flash", against a "gemini-3.5-flash-lite" primary) --
  cross-model agreement beats same-model self-consistency (Consensus
  Entropy v4, cited by the plan).
- `structural`: the second read runs the SAME model as the primary but a
  DIFFERENT (field-guided, one-question-at-a-time) prompt
  (`FIELD_GUIDED_SYSTEM_PROMPT`) against the primary's document-guided one
  -- distinguished from the primary purely by `extra_cache_key` plus its
  own prompt text, so it can never return the primary's cached reply
  (SD21).

`none` is the default until an AUROC selection (I3 acceptance 2/3 in the
plan) picks a winner against Phase-A transcription labels that do not exist
yet (US-008, a human labelling gate). THIS MODULE BUILDS AND TESTS ONLY THE
LABEL-FREE HALF: both variants producing a bounded `extraction_agreement`,
and the SD21 cache-key guarantee. It does not run either variant over the
Phase-A gold set, publish an AUROC, or choose a variant -- see this story's
report (US-010) for what remains open.

Agreement itself is `1 - normalised edit distance` per answer, computed via
`difflib.SequenceMatcher` -- the SAME stand-in `lemely.io.reread._text_agreement`
already uses for `reread_agreement`, because `rapidfuzz` (the plan's specified
implementation) is not a project dependency, and adding one is outside this
story's file ownership (`pyproject.toml`/`uv.lock` belong to other lanes
running concurrently in this session). Swapping to rapidfuzz later needs no
protocol or field change -- only `text_agreement`'s body.

The plan also asks for agreement to be computed "after the I2 normaliser"
(I2's CER normalisation: whitespace collapse, unicode NFKC, "x" vs. the
multiplication sign, superscript unfold). I2 has not landed either -- there
is no `jiwer` dependency and no `cer()`/normalisation function anywhere
under `lemely/eval`. `text_agreement`
below normalises only by `.strip()` + `.casefold()`, which is NOT the I2
normaliser -- it is a much weaker placeholder, named honestly as one rather
than silently passed off as raw string comparison.
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING, Protocol

from lemely.core.schemas import SecondReadOutput
from lemely.io.prompts.answer_extraction import (
    EXTRACTOR_SYSTEM_PROMPT,
    FIELD_GUIDED_SYSTEM_PROMPT,
    VERSION,
    build_extractor_user_prompt,
)

if TYPE_CHECKING:
    from lemely.core.loose_schemas import MarkScheme
    from lemely.core.schemas import ExtractedAnswer
    from lemely.io.gemini import GeminiClient
    from lemely.runtime.config import GeminiSettings

# Plan (I3): "Re-read (I1) fires on agreement < 0.8." Consumed by
# lemely.io.answer_extraction to decide whether a low-agreement answer joins
# the crop-and-re-read eligibility set -- see that module for whether/how
# this is wired (kept out of lemely.io.reread deliberately; see its own
# comment).
#
# 0.8 is the plan's threshold for a rapidfuzz normalised-Levenshtein score;
# applied here unmodified to a difflib Ratcliff/Obershelp score instead --
# not revalidated for this metric. The two algorithms score the same string
# pair differently (Ratcliff/Obershelp weights the longest common contiguous
# run more heavily; normalised Levenshtein counts raw edit operations), so
# "0.8" is not known to mean the same thing under both. Re-derive when
# rapidfuzz lands (US-013 needs it anyway for I6's coherence gate) rather
# than assuming 0.8 still means the same thing.
REREAD_AGREEMENT_THRESHOLD = 0.8

# Matches EXTRACTION_MEDIA_RESOLUTION (lemely.io.answer_extraction) -- the
# second read is a whole-paper call shaped like the primary's, not a
# zoomed-in single-answer crop like lemely.io.reread's "high" resolution.
SECOND_READ_MEDIA_RESOLUTION = "medium"


def text_agreement(a: str, b: str) -> float:
    """Similarity in [0, 1] between two answer strings, after normalisation.

    See the module docstring: this is a difflib-based stand-in for the
    plan's rapidfuzz normalised-Levenshtein metric, computed after only
    `.strip()` + `.casefold()` -- NOT the I2 normaliser, which does not
    exist yet.
    """
    return difflib.SequenceMatcher(None, a.strip().casefold(), b.strip().casefold()).ratio()


class SecondReader(Protocol):
    """A second, independent read of the same paper's answers."""

    def read(
        self,
        mark_scheme: MarkScheme,
        image_parts: list[bytes],
        *,
        extra_cache_key: str,
    ) -> dict[str, str]:
        """Return ``{question_id: answer_text}`` for the second read.

        A question_id the second read could not find is simply absent from
        the result -- callers must treat a missing key as "no second
        opinion for this question", not implicitly agree or disagree.
        """
        ...


class CrossModelSecondReader:
    """Same prompt as the primary extraction, a different model."""

    def __init__(self, client: GeminiClient, *, model: str) -> None:
        self._client = client
        self._model = model

    def read(
        self,
        mark_scheme: MarkScheme,
        image_parts: list[bytes],
        *,
        extra_cache_key: str,
    ) -> dict[str, str]:
        result = self._client.generate_structured(
            system_prompt=EXTRACTOR_SYSTEM_PROMPT,
            user_prompt=build_extractor_user_prompt(mark_scheme, page_count=len(image_parts)),
            image_parts=image_parts,
            media_resolution=SECOND_READ_MEDIA_RESOLUTION,
            response_schema=SecondReadOutput,
            prompt_version=VERSION,
            model=self._model,
            # SD21: literally distinct from the primary's extra_cache_key
            # (the manifest hash alone), on top of the model already
            # differing -- so this variant's cache entry can never collide
            # with the primary's even if a future primary call ever passed
            # the same model by coincidence.
            extra_cache_key=f"{extra_cache_key}:second_read:cross_model",
            task_tag="second_read",
        )
        return {a.question_id: a.answer for a in result.answers}


class StructuralSecondReader:
    """Same model as the primary extraction, a different (field-guided) prompt."""

    def __init__(self, client: GeminiClient, *, model: str) -> None:
        self._client = client
        self._model = model

    def read(
        self,
        mark_scheme: MarkScheme,
        image_parts: list[bytes],
        *,
        extra_cache_key: str,
    ) -> dict[str, str]:
        result = self._client.generate_structured(
            system_prompt=FIELD_GUIDED_SYSTEM_PROMPT,
            user_prompt=build_extractor_user_prompt(mark_scheme, page_count=len(image_parts)),
            image_parts=image_parts,
            media_resolution=SECOND_READ_MEDIA_RESOLUTION,
            response_schema=SecondReadOutput,
            prompt_version=VERSION,
            model=self._model,
            # SD21: the model here is deliberately the SAME as the primary's
            # -- FIELD_GUIDED_SYSTEM_PROMPT's different text already changes
            # the cache key, but extra_cache_key is distinguished explicitly
            # too so this variant never depends on prompt text alone to stay
            # out of the primary's cache entry.
            extra_cache_key=f"{extra_cache_key}:second_read:structural",
            task_tag="second_read",
        )
        return {a.question_id: a.answer for a in result.answers}


def build_second_reader(client: GeminiClient, settings: GeminiSettings) -> SecondReader | None:
    """Construct the configured `SecondReader`, or `None` for `"none"` (the default).

    `GeminiSettings.second_reader` is a closed `Literal` that pydantic
    already validates at config load time (see
    `TestSecondReaderSettings.test_second_reader_rejects_unknown_variant`),
    so this is exhaustive over every value that can reach here -- no
    fallback branch to raise from.
    """
    if settings.second_reader == "none":
        return None
    if settings.second_reader == "cross_model":
        model = settings.second_read_model or settings.model
        return CrossModelSecondReader(client, model=model)
    model = settings.extraction_model or settings.model
    return StructuralSecondReader(client, model=model)


def compute_agreement(
    primary_answers: list[ExtractedAnswer], second_read: dict[str, str]
) -> dict[str, float]:
    """``{question_id: agreement}`` for every primary answer with a matching second read.

    A `question_id` absent from `second_read` (the second call dropped it or
    never returned it) is left out of the result entirely -- callers must
    treat a missing key as "no second-read agreement available", not
    conflate it with 0.0 (total disagreement IS a valid measured value, and
    collapsing "not measured" into it would make a missing second opinion
    look like strong evidence of a wrong extraction).
    """
    return {
        a.question_id: text_agreement(a.answer, second_read[a.question_id])
        for a in primary_answers
        if a.question_id in second_read
    }
