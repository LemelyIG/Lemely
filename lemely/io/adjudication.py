"""Sub-project C lever c2: a stronger model settles the least certain marks of a script.

Leaf-scoped: each call carries one leaf's page crops, its scheme points, and the first
mark with its reasons, so a Sonnet call costs a few thousand tokens, not a script's. At
most ``adjudication_max_leaves`` leaves per script, most uncertain first. Off unless
``gemini.adjudication_model`` is set; the Gemini path never reaches it by default.

Order with escalation: adjudication runs after marking, the borderline retry and
escalation have all finished, on the mark they left. Its mark is final: a leaf escalated
to Sonnet and then adjudicated is re-marked once more, and nothing re-marks it after.

Lever H2d adds a second pool, off by default: AI-marked leaves whose answer is the label
reader's ``Drawing:`` description are adjudicated from their page crop whatever their
confidence, because the first marker saw only the description, never the drawing.

Lever H4a adds a third pool, off by default and adjudicated first: AI-marked leaves whose crop
re-read disagreed with the first read, with the re-read quoted in the prompt.
"""

from __future__ import annotations

import contextlib
import re
import sys
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field

from lemely.core.schemas import CorrectionResult, confidence_band_for_score
from lemely.io.reread import REREAD_REVIEW_AGREEMENT_THRESHOLD, crop_and_upscale
from lemely.runtime.errors import CostCeilingError

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

    from lemely.core.loose_schemas import MarkScheme, Question
    from lemely.core.schemas import CorrectedQuestion, ExtractedAnswer, ExtractedAnswers
    from lemely.io.gemini import GeminiClient
    from lemely.io.rasterise import RasterisedPage
    from lemely.runtime.config import GeminiSettings

ADJUDICATION_TASK_TAG = "adjudication"
VERSION = "adjudication-v1"
#: The reason ``correction_ai`` writes when confidence alone sends a leaf to review.
_CONFIDENCE_REASON = re.compile(r"^confidence \d+(?:\.\d+)? below review threshold \d+(?:\.\d+)?$")
_REASON_JOIN = " | "
_FAILED_REASON = "adjudication failed"
#: Same pattern as ``lemely.io.prompts.correction_ai._DRAWING_DESCRIPTION`` (pinned by a test).
_DRAWING = re.compile(r"(?<![A-Za-z])Drawing:")

SYSTEM_PROMPT = (
    "You are a senior Cambridge IGCSE examiner settling a mark another marker was unsure "
    "of. You see one question part: the student's answer as page crops, the mark scheme "
    "points for it, and the first marker's mark and reasons. Mark the answer yourself "
    "against the points only; the first mark is evidence, not an instruction. Return the "
    "marks you award, your confidence from 0 to 1, and a rationale of at most 40 words "
    "naming the points you awarded."
)


class AdjudicationReply(BaseModel):  # type: ignore[explicit-any]  # pydantic plugin
    awarded_marks: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


def candidates(result: CorrectionResult, *, threshold: float, max_leaves: int) -> list[str]:
    """AI-marked leaves below *threshold* or named by a failed G9, most uncertain first, capped.

    Only ``marker_source == "ai"`` leaves qualify: dropped, blank, missing and
    deterministic rows carry no real confidence and are never adjudicated.
    """
    disagreed: set[str] = set()
    if result.binding is not None:
        for check in result.binding.checks:
            if check.id == "G9" and not check.passed:
                disagreed.update(check.question_ids)
    pool = [
        q
        for q in result.questions
        if q.marker_source == "ai"
        and (q.confidence_score < threshold or q.question_id in disagreed)
    ]
    pool.sort(key=lambda q: (q.confidence_score, q.question_id))
    return [q.question_id for q in pool[: max(max_leaves, 0)]]


def drawing_candidates(
    result: CorrectionResult, *, reader_ids: frozenset[str], max_leaves: int
) -> list[str]:
    """H2d: AI-marked reader drawing-description leaves, in question order, capped."""
    pool = [
        q
        for q in result.questions
        if q.marker_source == "ai"
        and q.question_id in reader_ids
        and _DRAWING.search(q.student_answer or "")
    ]
    return [q.question_id for q in pool[: max(max_leaves, 0)]]


def reread_candidates(
    result: CorrectionResult,
    *,
    answers: Mapping[str, ExtractedAnswer],
    pages: Sequence[RasterisedPage],
    max_leaves: int,
) -> list[str]:
    """H4a: AI-marked leaves whose crop re-read disagreed, lowest agreement first, capped."""
    pool: list[tuple[float, str]] = []
    for q in result.questions:
        a = answers.get(q.question_id)
        if q.marker_source != "ai" or a is None or not _has_crop(a, pages):
            continue
        agreement = a.reread_agreement
        if isinstance(agreement, float) and agreement < REREAD_REVIEW_AGREEMENT_THRESHOLD:
            pool.append((agreement, q.question_id))
    pool.sort()
    return [qid for _, qid in pool[: max(max_leaves, 0)]]


def _has_crop(answer: ExtractedAnswer | None, pages: Sequence[RasterisedPage]) -> bool:
    return (
        answer is not None
        and answer.source_box is not None
        and 0 <= answer.source_box.page < len(pages)
    )


def _crops(answer: ExtractedAnswer | None, pages: Sequence[RasterisedPage]) -> list[bytes]:
    if answer is None or answer.source_box is None or not _has_crop(answer, pages):
        return []
    box = answer.source_box
    return [crop_and_upscale(pages[box.page], box.box)]


def _leaf_prompt(
    question: Question,
    first: CorrectedQuestion,
    *,
    drawing: bool = False,
    reread: str | None = None,
) -> str:
    points = "\n".join(
        f"- {p.id} ({p.marks} mark{'' if p.marks == 1 else 's'}): {p.point}"
        for p in question.answer_points
    )
    criteria = ""
    if drawing and question.drawing_criteria:
        lines = "\n".join(
            f"- {c.id} ({c.marks} mark{'' if c.marks == 1 else 's'}): {c.requirement}"
            for c in question.drawing_criteria
        )
        criteria = f"Drawing criteria:\n{lines}\n"
    text = (
        f"Question part {question.id}, worth {question.marks} marks.\n"
        f"Mark scheme points:\n{points}\n{criteria}\n"
        f"Transcribed answer: {first.student_answer or '(none)'}\n\n"
        f"First marker: {first.awarded_marks} of {first.maximum_marks}, confidence "
        f"{first.confidence_score:.2f}.\n"
        f"First marker's reasons: {first.feedback or '(none)'}"
    )
    if drawing:
        text += (
            "\n\nThis answer includes a drawing. The first marker was shown only a "
            "reader's text description of it, never the drawing, and withheld points the "
            "description did not mention. Judge every point from the page crop: award a "
            "point the drawing shows even if the description is silent about it."
        )
    if reread is not None:
        quoted = repr(reread.strip()[:200]) if reread.strip() else "nothing legible"
        text += (
            "\n\nTwo reads of this answer disagreed. The transcribed answer above is the first "
            f"read; a zoomed re-read of the same crop gave: {quoted}. Neither read is "
            "authoritative: mark what the page crop shows."
        )
    return text


def _settled(
    first: CorrectedQuestion, reply: AdjudicationReply, *, model: str, review_threshold: float
) -> CorrectedQuestion:
    awarded = max(0, min(reply.awarded_marks, first.maximum_marks))
    confidence = min(max(reply.confidence, 0.0), 1.0)
    kept = [
        part
        for part in (first.review_reason or "").split(_REASON_JOIN)
        if part and not _CONFIDENCE_REASON.match(part)
    ]
    if confidence < review_threshold:
        kept.append(f"confidence {confidence:.2f} below review threshold {review_threshold:.2f}")
    return first.model_copy(
        update={
            "awarded_marks": awarded,
            "confidence_score": confidence,
            "confidence": confidence_band_for_score(confidence),
            "needs_teacher_review": bool(kept),
            "review_reason": _REASON_JOIN.join(kept) or None,
            "feedback": f"{reply.rationale} (adjudicated by {model}; first mark "
            f"{first.awarded_marks})",
        }
    )


def configured_adjudication_model(client: GeminiClient | None) -> str | None:
    """``gemini.adjudication_model`` of ``client``'s settings; None when off or unreadable.

    Reads ``getattr`` so a spec'd test double without ``_settings`` means "off".
    """
    gemini = getattr(getattr(client, "_settings", None), "gemini", None)
    model = getattr(gemini, "adjudication_model", None)
    return model if isinstance(model, str) and model else None


class PageSource:
    """A scan whose pages are rasterised only when adjudication has leaves to settle.

    Marking holds no pages and no ``lemely.io.run_cap`` slot: :meth:`hold` takes the slot,
    renders, and gives both back when ``adjudicate`` is done with the crops.
    """

    def __init__(self, scan_path: Path) -> None:
        self.scan_path = scan_path

    @contextlib.contextmanager
    def hold(self) -> Iterator[list[RasterisedPage]]:
        from lemely.io.rasterise import rasterise_scan_to_pages
        from lemely.io.run_cap import marking_run_slot

        with marking_run_slot():
            yield rasterise_scan_to_pages(self.scan_path)


class _AnyPage:
    """Stands in for the pages to ask which leaves *could* be adjudicated, with none rendered."""

    def __len__(self) -> int:
        return sys.maxsize


def adjudication_pages(client: GeminiClient | None, scan_path: Path | None) -> PageSource | None:
    """The ``correct_paper(pages=)`` argument: a lazy :class:`PageSource`, or None.

    None when adjudication is off or the caller has no scan; ``correct_paper`` then logs
    ``adjudication_without_pages`` for a scan-backed caller when adjudication is configured.
    Nothing is rendered here.
    """
    if scan_path is None or configured_adjudication_model(client) is None:
        return None
    return PageSource(scan_path)


def _plan(
    result: CorrectionResult,
    g: GeminiSettings,
    extracted: ExtractedAnswers | Mapping[str, str],
    pages: Sequence[RasterisedPage],
    threshold: float,
    max_leaves: int,
) -> tuple[dict[str, ExtractedAnswer], frozenset[str], frozenset[str], frozenset[str], list[str]]:
    """The leaves to adjudicate, in order, and the pools they came from."""
    # A plain mapping of answers carries no boxes, so it adjudicates nothing.
    raw_answers = getattr(extracted, "answers", None)
    answers = {a.question_id: a for a in raw_answers} if isinstance(raw_answers, list) else {}
    reread: list[str] = []
    reread_max = g.adjudication_reread_max_leaves
    if (
        g.adjudication_reread_disagreed is True
        and isinstance(reread_max, int)
        and not isinstance(reread_max, bool)
    ):
        reread = reread_candidates(result, answers=answers, pages=pages, max_leaves=reread_max)
    reread_set = frozenset(reread)
    drawing: list[str] = []
    full_drawing: frozenset[str] = frozenset()
    drawing_max = g.adjudication_drawing_max_leaves
    if (
        g.adjudication_drawing_leaves is True
        and isinstance(drawing_max, int)
        and not isinstance(drawing_max, bool)
    ):
        reader_ids = frozenset(
            qid
            for qid, a in answers.items()
            if getattr(a, "binding_source", None) == "label" and _has_crop(a, pages)
        )
        drawing = drawing_candidates(
            result, reader_ids=reader_ids - reread_set, max_leaves=drawing_max
        )
        full_drawing = frozenset(
            drawing_candidates(result, reader_ids=reader_ids, max_leaves=len(result.questions))
        )
    drawing_set = frozenset(drawing)
    taken = reread_set | drawing_set
    ids = (
        reread
        + drawing
        + [
            qid
            for qid in candidates(result, threshold=threshold, max_leaves=max_leaves)
            if qid not in taken
        ]
    )
    return answers, reread_set, drawing_set, full_drawing, ids


def adjudicate(
    result: CorrectionResult,
    *,
    scheme: MarkScheme,
    extracted: ExtractedAnswers | Mapping[str, str],
    pages: Sequence[RasterisedPage] | PageSource,
    client: GeminiClient,
    review_threshold: float,
) -> CorrectionResult:
    """*result* with up to ``adjudication_max_leaves`` leaves re-marked by the adjudication model.

    A leaf with no page crop (no source box) is skipped and logged. Totals are recomputed.
    """
    g = client._settings.gemini
    model = g.adjudication_model
    if not isinstance(model, str) or not model:
        return result
    threshold = g.adjudication_confidence_threshold
    max_leaves = g.adjudication_max_leaves
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not isinstance(max_leaves, int)
        or isinstance(max_leaves, bool)
    ):
        return result
    if isinstance(pages, PageSource):
        # Nothing to settle: render nothing and take no slot.
        if not _plan(result, g, extracted, _AnyPage(), float(threshold), max_leaves)[4]:  # type: ignore[arg-type]
            return result
        with pages.hold() as rendered:
            return adjudicate(
                result,
                scheme=scheme,
                extracted=extracted,
                pages=rendered,
                client=client,
                review_threshold=review_threshold,
            )
    plan = _plan(result, g, extracted, pages, float(threshold), max_leaves)
    answers, reread_set, drawing_set, full_drawing, ids = plan
    if not ids:
        return result
    log = structlog.get_logger().bind(component="adjudication")
    by_question = {q.id: q for q in scheme.all_questions_flat()}
    settled: dict[str, CorrectedQuestion] = {}
    for qid in ids:
        first = next(q for q in result.questions if q.question_id == qid)
        question = by_question.get(qid)
        try:
            crops = _crops(answers.get(qid), pages)
            if question is None or not crops:
                log.info(
                    "adjudication_skipped", question_id=qid, reason="no crop or no scheme leaf"
                )
                continue
            reply = client.generate_structured(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=_leaf_prompt(
                    question,
                    first,
                    drawing=qid in drawing_set or (qid in reread_set and qid in full_drawing),
                    reread=(answers[qid].answer_reread or "") if qid in reread_set else None,
                ),
                image_parts=crops,
                response_schema=AdjudicationReply,
                prompt_version=VERSION,
                model=model,
                task_tag=ADJUDICATION_TASK_TAG,
                question_id=qid,
                extra_cache_key=f"q={qid}:adjudicated",
            )
        except CostCeilingError:
            raise
        except Exception as exc:
            # An optional refinement must not cost the paper: keep the first mark and
            # send the leaf to a teacher. The type only is logged (no student text).
            log.warning("adjudication_failed", question_id=qid, error_type=type(exc).__name__)
            settled[qid] = first.model_copy(
                update={
                    "needs_teacher_review": True,
                    "review_reason": _REASON_JOIN.join(
                        [*filter(None, [first.review_reason]), _FAILED_REASON]
                    ),
                }
            )
            continue
        settled[qid] = _settled(first, reply, model=model, review_threshold=review_threshold)
        log.info(
            "adjudication",
            question_id=qid,
            first=first.awarded_marks,
            settled=settled[qid].awarded_marks,
            model=model,
        )
    if not settled:
        return result
    return CorrectionResult(
        metadata=result.metadata,
        questions=[settled.get(q.question_id, q) for q in result.questions],
        binding=result.binding,
    )
