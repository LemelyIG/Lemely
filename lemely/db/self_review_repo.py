"""Student self-review of marked questions (spec 2026-09-17 self-review).

The one writer of ``question_result_points.student_selfmark*`` /
``evidence_verdict`` and ``question_results.student_selfmark_marks`` /
``student_selfmarked_at``, and the one reader that **withholds the marker's
verdict** until the student has committed to their own.

**The reveal is server-enforced.** :meth:`SelfReviewService.get` returns a
:class:`PendingSelfReview` before submission, whose point type
(:class:`PendingPoint`) has no ``awarded`` attribute at all — not a nulled one.
The verdict exists only on :class:`RevealedPoint`, which is only ever built
after ``student_selfmarked_at`` is set. A client cannot read a field the
payload does not contain.

**Authority** is :func:`lemely.core.self_review.decide_point`, fed by
:func:`lemely.db.attempt_repo.is_marking_low_confidence` — the same function
that opened the ``low_confidence`` review-queue row at correction time, so
"the marker was unsure" means one thing across both paths. Integrity flags
never reach the rule.

**One transaction — but not the judge.** ``submit`` is three phases (Task
11a): a read-only plan, the judge round-trips themselves with no session or
lock held at all, then a single locked apply. Point rows,
``student_selfmark_marks``, the ``student_selfmark`` revision, the
totals/weakness recompute (the module-level functions in
:mod:`lemely.db.review_repo` — the same code the teacher-override path runs,
so identical marks can never round differently) and the ``low_confidence``
queue auto-resolve all commit together in that last phase, or not at all. The
``QuestionResult`` row is locked ``FOR UPDATE`` only for the apply, which is
what turns a racing second POST into a 409 rather than a second self-mark —
not the read in the planning phase, which is unlocked precisely so an LLM
call never holds a row lock or a pooled connection.

**Judge failure is never a decision.** ``judge=None`` (no Gemini key), an
exception, or a malformed answer all leave ``evidence_verdict`` NULL, move no
marks, and open a ``student_evidence_unjudged`` queue row so a teacher looks.

**A revision is appended on every pass**, not only when marks moved: the
judge's reason for a *rejected* claim has no column of its own and the
student must be able to read it again, so it lives in the revision's
``points_snapshot``. An unchanged-marks revision is honest history.

**Marks move by delta, settled per scheme group**, not by re-summing ticked
tariffs: for each group (an independent point is its own group with cap
``tariff``), the credit is ``min(group_max_marks, sum of tariffs counted as
earned)`` before and after the granted verdicts are applied, and the question
moves by the sum of those differences from ``awarded_marks``, clamped to
``[0, maximum_marks]``. So a grant can never lift an either/or or "any N
from" group above what the scheme says it is worth (D6's grade-inflation
guard), a downward grant that another member still covers removes nothing,
and the marker's own total is never contradicted. ``awarded_marks`` itself is
never written — ``lemely/eval`` reads it.

**A grant the cap absorbs is recorded, not hidden and not escalated.** The
claim was accepted (``evidence_verdict`` says so); the mark did not follow
(``mark_changed`` is false, ``absorbed_by_group`` is true, both in the
revision's snapshot and on :class:`RevealedPoint`). Nothing is uncertain, so
no teacher row is opened.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol

import structlog
from sqlalchemy import func, select

from lemely.core.self_review import (
    JudgeRequest,
    JudgeVerdict,
    PointDecision,
    decide_point,
)
from lemely.db.attempt_repo import is_marking_low_confidence
from lemely.db.models.attempts import (
    Attempt,
    QuestionResult,
    QuestionResultPoint,
    QuestionResultRevision,
)
from lemely.db.models.enums import EvidenceVerdict, ReviewReason, ReviewStatus, RevisionSource
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.review_repo import (
    _narrow_point_verdict,
    recompute_attempt_totals,
    recompute_weakness_records,
)
from lemely.io.grade_boundaries import GradeBoundaryStore
from lemely.io.prompts.self_review_judge import evidence_was_tampered

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.schemas import PointVerdictWire
    from lemely.core.self_review import EvidenceJudge

log = structlog.get_logger(__name__)

#: Written to ``review_queue.resolution_note`` when a self-mark closes a
#: ``low_confidence`` row (D4). Provenance proper lives in the revision's
#: ``source``; this is the human-readable trace on the queue row.
SELFMARK_RESOLUTION_NOTE = "Resolved by student self-mark"
#: Upper bound on stored evidence; the DTO layer enforces the same figure.
MAX_EVIDENCE_CHARS = 2000
#: Upper bound on a judge's stored reason (LLM output: bounded before it
#: reaches JSONB).
MAX_JUDGE_REASON_CHARS = 500


class SelfReviewError(Exception):
    """Base class for self-review failures."""


class SelfReviewNotFoundError(SelfReviewError):
    """The attempt/question is not the caller's, does not exist, or has no point rows (→ 404)."""


class SelfReviewAlreadySubmittedError(SelfReviewError):
    """The student has already completed their one pass on this question (→ 409)."""


class SelfReviewValidationError(SelfReviewError):
    """The submission is not a complete, well-formed set of verdicts (→ 422)."""


@dataclass(frozen=True, slots=True)
class PointVerdict:
    """One point of a student's submission."""

    mark_point_id: str
    earned: bool
    evidence: str | None = None


@dataclass(frozen=True, slots=True)
class PendingPoint:
    """A mark point before the reveal.

    Deliberately has no ``awarded``; ``group_key`` / ``group_max_marks`` are
    scheme-derived and verdict-free.
    """

    mark_point_id: str
    ordinal: int
    mark_type: str | None
    tariff: int
    point_text: str
    is_alternative: bool
    is_optional: bool
    group_key: str | None
    group_max_marks: int | None


@dataclass(frozen=True, slots=True)
class RevealedPoint:
    """A mark point after the reveal: the marker's verdict beside the student's.

    ``verdict``/``evidence_span``/``ecf_applied`` are I6/I7's marker verdict
    (US-013) -- the same three fields ``lemely.db.review_repo.ReviewItemPoint``
    carries for the teacher screen, read here off the same
    ``QuestionResultPoint`` columns so ``withheld`` and ``unverifiable`` (both
    ``awarded=False``) do not collapse into one value on the student's own
    result either.
    """

    mark_point_id: str
    ordinal: int
    mark_type: str | None
    tariff: int
    point_text: str
    is_alternative: bool
    is_optional: bool
    group_key: str | None
    group_max_marks: int | None
    awarded: bool
    student_selfmark: bool
    student_evidence: str | None
    evidence_verdict: str | None
    mark_changed: bool
    absorbed_by_group: bool
    judge_reason: str | None
    verdict: PointVerdictWire | None
    evidence_span: str
    ecf_applied: bool


@dataclass(frozen=True, slots=True)
class PendingSelfReview:
    """``GET`` before submission. No verdict anywhere in it."""

    state: Literal["not_started"]
    attempt_id: uuid.UUID
    question_result_id: uuid.UUID
    question_id: str
    maximum_marks: int
    evidence_required: bool
    points: list[PendingPoint]


@dataclass(frozen=True, slots=True)
class RevealedSelfReview:
    """``GET`` after submission, and the ``POST`` response.

    ``revealed`` means a teacher still has to look (a judge failure opened a
    ``student_evidence_unjudged`` row that is still open); ``settled`` means
    nothing is pending. ``teacher_settled`` says a teacher override already
    decides this question's mark, so the self-mark was recorded without
    moving anything.
    """

    state: Literal["revealed", "settled"]
    attempt_id: uuid.UUID
    question_result_id: uuid.UUID
    question_id: str
    maximum_marks: int
    evidence_required: bool
    ai_marks: int
    effective_marks: int
    student_marks: int | None
    teacher_settled: bool
    pending_teacher: bool
    submitted_at: datetime
    points: list[RevealedPoint]


@dataclass(frozen=True, slots=True)
class AttemptQuestion:
    """One question of the caller's attempt, as the result screen lists it.

    ``effective_marks`` (teacher > student > AI), never ``awarded_marks``.
    ``self_reviewable`` is derived from the presence of point rows — the same
    fact :meth:`SelfReviewService.get` 404s on — so the screen and the route
    can never disagree about which rows offer the panel.

    ``pending_teacher`` is the truthful, current answer to "is a teacher
    still going to look at this question": whether an open
    :class:`ReviewQueueItem` exists for it right now, of any reason. Unlike
    ``review_reason`` — the marker's own record of *why* the question was
    flagged, fixed at marking time and never ours to rewrite — this reflects
    the queue as it stands, so it drops to ``False`` the moment a self-mark
    (or anything else) resolves the row, even though ``review_reason`` still
    reads exactly as it did.

    ``needs_teacher_review`` is the OTHER one, and the pair is not redundant:
    it is the marker's flag frozen at marking time, which ``pending_teacher``
    is deliberately allowed to outrank. Both reach the screen because
    ``markingConfidence.ts``'s ``confidenceTierFor`` needs both — US-039's
    unflagged blank is identified by ``needs_teacher_review is False`` plus a
    ``missing``/``dropped`` marker source, and no amount of queue state
    substitutes for it (a blank opens no queue row, so ``pending_teacher`` is
    ``False`` for it too, and reading that alone renders a blank as
    "confident": the marker confident about a question no marker read).
    """

    question_result_id: uuid.UUID
    question_id: str
    effective_marks: int
    maximum_marks: int
    marker_source: str
    confidence_score: float
    feedback: str | None
    review_reason: str | None
    needs_teacher_review: bool
    topic: str | None
    matched_point_ids: list[str]
    self_reviewable: bool
    pending_teacher: bool


def question_sort_key(question_id: str) -> tuple[tuple[int, int, str], ...]:
    """Sort key putting question ids in paper order: 1, 1a, 1b, 2, 9, 10.

    Digit runs compare numerically so ``"10"`` follows ``"9"`` instead of
    preceding ``"2"``; every other run compares as lowercased text, after the
    numbers at that position rather than raising on a mixed comparison.
    """
    parts: list[tuple[int, int, str]] = []
    for run in re.findall(r"\d+|\D+", question_id):
        if run.isdigit():
            parts.append((0, int(run), ""))
        else:
            parts.append((1, 0, run.lower()))
    return tuple(parts)


class SelfReviewService:
    """Get and submit a student's self-review of one marked question."""

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        judge: EvidenceJudge | None,
        boundary_store: GradeBoundaryStore | None = None,
    ) -> None:
        """``judge=None`` means every judged claim is a judge *failure* (see module docstring)."""
        self._sessionmaker = sessionmaker
        self._judge = judge
        self._boundaries = boundary_store or GradeBoundaryStore()

    def get(
        self,
        student_id: uuid.UUID | str,
        attempt_id: uuid.UUID | str,
        question_result_id: uuid.UUID | str,
    ) -> PendingSelfReview | RevealedSelfReview:
        """The self-review state of one question, for its owner only.

        Raises:
            SelfReviewNotFoundError: not the caller's attempt, no such question
                on that attempt, malformed ids, or no point rows (404 — never
                a 403, matching the other student routes).
        """
        student_uuid = _as_uuid(student_id)
        attempt_uuid = _as_uuid(attempt_id)
        qr_uuid = _as_uuid(question_result_id)
        with self._sessionmaker() as session:
            _attempt, qr = _owned_question(
                session, student_uuid, attempt_uuid, qr_uuid, for_update=False
            )
            return _to_view(session, qr)

    def submit(
        self,
        student_id: uuid.UUID | str,
        attempt_id: uuid.UUID | str,
        question_result_id: uuid.UUID | str,
        verdicts: Sequence[PointVerdict],
    ) -> RevealedSelfReview:
        """Record the student's one self-mark pass and reveal the marker's verdict.

        Three phases, none of which shares a session with another (Task 11a):
        a read-only plan (no lock), the judge round-trips themselves (no
        session at all — an LLM call can take seconds and must never hold a
        row lock or a pooled connection while it does), then the locked apply
        that writes. See the module docstring for what moves and why.

        Raises:
            SelfReviewNotFoundError: as :meth:`get` (404).
            SelfReviewAlreadySubmittedError: the pass already happened (409).
            SelfReviewValidationError: not exactly one verdict per point of
                the question — a partial pass would let a student reveal
                three points and calibrate the other two (422).
        """
        student_uuid = _as_uuid(student_id)
        attempt_uuid = _as_uuid(attempt_id)
        qr_uuid = _as_uuid(question_result_id)

        # Phase A — plan, read-only, no lock. A submission that fails
        # validation here, or arrives after the question was already
        # self-marked, leaves the question untouched and re-submittable,
        # exactly as `_verdicts_by_point`'s docstring promises. Nothing below
        # this block writes.
        with self._sessionmaker() as session:
            attempt, qr = _owned_question(
                session, student_uuid, attempt_uuid, qr_uuid, for_update=False
            )
            if qr.is_self_marked:
                raise SelfReviewAlreadySubmittedError(
                    f"Question {qr.id} has already been self-marked"
                )
            by_point = _verdicts_by_point(verdicts, qr.points)
            low_confidence = is_marking_low_confidence(qr)
            teacher_settled = qr.is_overridden
            judge_requests: dict[str, JudgeRequest] = {}
            for point in qr.points:
                verdict = by_point[point.mark_point_id]
                evidence = _clean_text(verdict.evidence, MAX_EVIDENCE_CHARS)
                decision = _decide_with_precedence(
                    ai_awarded=point.awarded,
                    student_earned=verdict.earned,
                    low_confidence=low_confidence,
                    has_evidence=evidence is not None,
                    teacher_settled=teacher_settled,
                )
                if decision is PointDecision.JUDGE:
                    judge_requests[point.mark_point_id] = JudgeRequest(
                        subject_code=attempt.subject_code or "",
                        question_id=qr.question_id,
                        point_text=point.point_text,
                        mark_type=point.mark_type,
                        tariff=point.tariff,
                        student_answer=qr.student_answer,
                        marker_rationale=point.rationale or qr.rationale or qr.feedback,
                        student_claims_earned=verdict.earned,
                        student_evidence=evidence or "",
                    )

        # Phase B — judge, holding nothing: no session, no transaction, no
        # row lock, no pooled connection. Phase A's `with` block above has
        # already exited by the time this runs, so its session is closed and
        # its connection returned to the pool before the first judge call —
        # not merely unlocked, but off the pool entirely. `qr` is detached
        # here, but every attribute `_judge_safely` reads off it (`qr.id`,
        # for logging) was already loaded while the session above was open.
        judge_results: dict[str, JudgeVerdict | None] = {
            mark_point_id: self._judge_safely(request, qr)
            for mark_point_id, request in judge_requests.items()
        }

        # Phase C — apply, locked.
        with self._sessionmaker() as session, session.begin():
            attempt, qr = _owned_question(
                session, student_uuid, attempt_uuid, qr_uuid, for_update=True
            )
            # Phase A's check above ran against an unlocked read and is only a
            # fast reject for the common case — a second POST could pass it
            # concurrently, or land while this one was off judging. This
            # re-check runs against the row now locked FOR UPDATE, so it is
            # the one that actually turns a racing second submission into a
            # 409 rather than a second self-mark: the one-pass guarantee.
            if qr.is_self_marked:
                raise SelfReviewAlreadySubmittedError(
                    f"Question {qr.id} has already been self-marked"
                )
            by_point = _verdicts_by_point(verdicts, qr.points)

            now = datetime.now(UTC)
            low_confidence = is_marking_low_confidence(qr)
            teacher_settled = qr.is_overridden
            unjudged = False
            passes: list[_PointPass] = []

            for point in qr.points:
                verdict = by_point[point.mark_point_id]
                evidence = _clean_text(verdict.evidence, MAX_EVIDENCE_CHARS)
                point.student_selfmark = verdict.earned
                point.student_selfmark_at = now
                point.student_evidence = evidence
                point.evidence_verdict = None
                judge_reason: str | None = None
                granted = False

                # Recomputed from the state this locked pass actually sees —
                # never from Phase A's plan, which may now be stale (a
                # teacher override, say, landed while Phase B was judging).
                decision = _decide_with_precedence(
                    ai_awarded=point.awarded,
                    student_earned=verdict.earned,
                    low_confidence=low_confidence,
                    has_evidence=evidence is not None,
                    teacher_settled=teacher_settled,
                )

                if decision is PointDecision.GRANT:
                    point.evidence_verdict = EvidenceVerdict.not_required
                    granted = True
                elif decision is PointDecision.JUDGE:
                    # `judge_results` holds Phase B's verdicts, keyed by the
                    # points Phase A planned to judge. A point absent here
                    # means the state drifted inside the window and this
                    # point now needs a judge that was never asked — the same
                    # honest "unjudged" path as a judge failure, not a silent
                    # verdict.
                    outcome = judge_results.get(point.mark_point_id)
                    if outcome is None:
                        unjudged = True
                    else:
                        point.evidence_verdict = (
                            EvidenceVerdict.accepted
                            if outcome.accepted
                            else EvidenceVerdict.rejected
                        )
                        judge_reason = outcome.reason
                        granted = outcome.accepted

                passes.append(
                    _PointPass(
                        point=point,
                        earned=verdict.earned,
                        granted=granted,
                        judge_reason=judge_reason,
                    )
                )

            delta = _settle_groups(passes)
            changed = any(item.mark_changed for item in passes)
            snapshot: list[dict[str, object]] = [
                {
                    "mark_point_id": item.point.mark_point_id,
                    "ai_awarded": item.point.awarded,
                    "student_selfmark": item.earned,
                    "evidence_verdict": (
                        item.point.evidence_verdict.value if item.point.evidence_verdict else None
                    ),
                    "mark_changed": item.mark_changed,
                    "absorbed_by_group": item.absorbed_by_group,
                    "judge_reason": item.judge_reason,
                }
                for item in passes
            ]

            qr.student_selfmarked_at = now
            if changed:
                unclamped = qr.awarded_marks + delta
                clamped = max(0, min(qr.maximum_marks, unclamped))
                if clamped != unclamped:
                    # The clamp is load-bearing but otherwise invisible: on a
                    # 1-mark either/or question it silently turns a
                    # double-credit bug into the right answer, and on a
                    # larger question the same bug would leak through
                    # unnoticed. Surface every time it actually binds.
                    log.warning(
                        "self_review_delta_clamped",
                        question_result_id=str(qr.id),
                        unclamped_marks=unclamped,
                        clamped_marks=clamped,
                    )
                qr.student_selfmark_marks = clamped
            session.flush()
            _append_revision(session, qr, actor=student_uuid, snapshot=snapshot, changed=changed)

            if changed:
                results = session.scalars(
                    select(QuestionResult).where(QuestionResult.attempt_id == attempt.id)
                ).all()
                recompute_attempt_totals(session, attempt, results, boundary_store=self._boundaries)
                recompute_weakness_records(session, attempt, results)
            # Every completed pass closes the row, not only one that moved
            # marks. D4's reason for auto-resolving is that a teacher no longer
            # has to look, and full agreement — the student reaching the
            # marker's own verdict independently — is the strongest evidence of
            # that, not the weakest. Gating this on `changed` left the
            # commonest outcome open forever, with the student unable to submit
            # again (409). A grant the group cap absorbed was stranded the same
            # way. Where a teacher *is* still needed, it is because the judge
            # failed, and that opens its own `student_evidence_unjudged` row
            # below.
            _resolve_low_confidence_rows(session, qr, resolver=student_uuid, now=now)
            if unjudged:
                session.add(
                    ReviewQueueItem(
                        attempt_id=attempt.id,
                        question_result_id=qr.id,
                        reason=ReviewReason.student_evidence_unjudged,
                    )
                )
            session.flush()
            log.info(
                "self_review_submitted",
                attempt_id=str(attempt.id),
                question_result_id=str(qr.id),
                low_confidence=low_confidence,
                marks_changed=changed,
                unjudged=unjudged,
                teacher_settled=teacher_settled,
            )
            return _revealed_view(session, qr, evidence_required=not low_confidence)

    def list_questions(
        self, student_id: uuid.UUID | str, attempt_id: uuid.UUID | str
    ) -> list[AttemptQuestion]:
        """Every question of one of the caller's attempts, in paper order.

        Paper order is reconstructed from the question id (see
        :func:`question_sort_key`) rather than read off the row. ``ORDER BY
        created_at, id`` looks like persist order and is not: ``now()`` in
        Postgres is the *transaction* timestamp, so every ``question_results``
        row of one attempt shares it, and the sort falls through to a random
        uuid. Measured on an eight-question attempt: ``5, 1, 4, ...``. There is
        no ordinal column to order by, and a student reading a scrambled paper
        would have no way to tell it from a marking fault.

        Raises:
            SelfReviewNotFoundError: not the caller's attempt, or no such attempt (404).
        """
        student_uuid = _as_uuid(student_id)
        attempt_uuid = _as_uuid(attempt_id)
        with self._sessionmaker() as session:
            attempt = session.get(Attempt, attempt_uuid)
            if attempt is None or attempt.user_id != student_uuid:
                raise SelfReviewNotFoundError(f"No attempt {attempt_uuid}")
            results = sorted(
                session.scalars(
                    select(QuestionResult).where(QuestionResult.attempt_id == attempt.id)
                ).all(),
                key=lambda qr: question_sort_key(qr.question_id),
            )
            # One query for the whole attempt rather than lazy-loading every
            # question's points to compute a boolean: a 40-question paper was
            # 42 round trips, each materialising point rows nothing else reads.
            # It reads the three group columns as well, because self-reviewable
            # means settleable, not merely "has points" — see
            # :func:`points_are_settleable`, and the same predicate gates the
            # route in ``_owned_question``, so the panel is never offered on a
            # question whose ``GET`` would 404.
            group_flags: dict[uuid.UUID, list[_HasGroupFlags]] = {}
            flag_rows = session.execute(
                select(
                    QuestionResultPoint.question_result_id,
                    QuestionResultPoint.is_alternative,
                    QuestionResultPoint.is_optional,
                    QuestionResultPoint.group_key,
                    QuestionResultPoint.group_max_marks,
                ).where(QuestionResultPoint.question_result_id.in_([qr.id for qr in results]))
            ).all()
            for qr_id, is_alternative, is_optional, group_key, group_max_marks in flag_rows:
                group_flags.setdefault(qr_id, []).append(
                    _PointFlags(
                        is_alternative=is_alternative,
                        is_optional=is_optional,
                        group_key=group_key,
                        group_max_marks=group_max_marks,
                    )
                )
            # Same one-query-for-the-whole-attempt shape as `group_flags`
            # above, and for the same reason: a per-question `EXISTS` here
            # would be another 40-question paper turned into 40 round trips.
            open_review_ids: set[uuid.UUID] = {
                qr_id
                for qr_id in session.scalars(
                    select(ReviewQueueItem.question_result_id).where(
                        ReviewQueueItem.question_result_id.in_([qr.id for qr in results]),
                        ReviewQueueItem.status == ReviewStatus.open,
                    )
                ).all()
                if qr_id is not None
            }
            return [
                AttemptQuestion(
                    question_result_id=qr.id,
                    question_id=qr.question_id,
                    effective_marks=qr.effective_marks,
                    maximum_marks=qr.maximum_marks,
                    marker_source=qr.marker_source.value,
                    confidence_score=qr.confidence_score,
                    feedback=qr.feedback,
                    review_reason=qr.review_reason,
                    needs_teacher_review=qr.needs_teacher_review,
                    topic=qr.topic,
                    matched_point_ids=list(qr.matched_point_ids),
                    self_reviewable=bool(group_flags.get(qr.id))
                    and points_are_settleable(group_flags[qr.id]),
                    pending_teacher=qr.id in open_review_ids,
                )
                for qr in results
            ]

    def _judge_safely(self, request: JudgeRequest, qr: QuestionResult) -> JudgeVerdict | None:
        """Ask the judge; ``None`` on any failure (no judge, exception, junk).

        A failure is never a decision — the caller opens a
        ``student_evidence_unjudged`` queue row. The verdict's reason is an
        LLM string bound for JSONB, so it is NUL-stripped and truncated here.

        Whether the fence marker had to be stripped from ``request`` is
        checked here, in both failure branches, not only inside
        :class:`GeminiEvidenceJudge`: an attempted forgery is exactly the
        thing worth recording, and on a deployment with no judge (or one
        that just failed) it would otherwise go unlogged — the near-zero-
        false-positive signal the module docstring on
        :mod:`lemely.io.evidence_judge` describes would silently not apply in
        the state most of this branch is actually developed and run in
        (S2 part2+3 final review, m-3).
        """
        sanitised = evidence_was_tampered(request)
        if self._judge is None:
            log.warning(
                "self_review_judge_unavailable",
                question_result_id=str(qr.id),
                evidence_sanitised=sanitised,
            )
            return None
        try:
            verdict = self._judge.judge(request)
            return JudgeVerdict(
                accepted=bool(verdict.accepted),
                reason=_clean_text(verdict.reason, MAX_JUDGE_REASON_CHARS) or "",
            )
        except Exception as exc:
            # A malformed verdict (None, a dict, anything missing .accepted /
            # .reason) is caught here too, not just a raised exception from
            # the judge call itself — junk from a judge must never abort the
            # student's whole self-mark (finding 1).
            log.warning(
                "self_review_judge_failed",
                question_result_id=str(qr.id),
                error=str(exc),
                evidence_sanitised=sanitised,
            )
            return None


# ── Internals ────────────────────────────────────────────────────────────────


def _decide_with_precedence(
    *,
    ai_awarded: bool,
    student_earned: bool,
    low_confidence: bool,
    has_evidence: bool,
    teacher_settled: bool,
) -> PointDecision:
    """:func:`decide_point` plus the teacher-override downgrade.

    Pulled out so Phase A's plan and Phase C's apply (:meth:`SelfReviewService.submit`)
    compute this identically, from whatever state each actually reads.
    """
    decision = decide_point(
        ai_awarded=ai_awarded,
        student_earned=student_earned,
        low_confidence=low_confidence,
        has_evidence=has_evidence,
    )
    if teacher_settled and decision is not PointDecision.AGREE:
        # Precedence already settles this question; the self-mark is recorded
        # for its learning signal and nothing moves, so a judge call could
        # not change any outcome.
        return PointDecision.NO_CHANGE
    return decision


@dataclass(slots=True)
class _PointPass:
    """One point's passage through ``submit``.

    The student's verdict, whether authority granted it, and — once
    :func:`_settle_groups` has run — whether it moved a mark or was absorbed
    by its group.
    """

    point: QuestionResultPoint
    earned: bool
    granted: bool
    judge_reason: str | None
    mark_changed: bool = False
    absorbed_by_group: bool = False


def _settle_groups(passes: list[_PointPass]) -> int:
    """Turn granted verdicts into a marks delta, one scheme group at a time.

    A point without ``group_key`` is its own group with cap ``tariff``, for
    which this is exactly the per-point rule: +tariff for a granted upward
    verdict, -tariff for a granted downward one. For an either/or or any-N
    group the credit is ``min(group_max_marks, sum of tariffs of the members
    that count as earned)`` — before, the marker's ``awarded`` flags; after,
    the same flags with every *granted* verdict applied — and the group moves
    by the difference. A grant therefore never lifts a group above what the
    scheme says it is worth, and a downward grant on a member another earned
    member still covers removes nothing; in both directions the result is
    never further from the marker's total than the per-point rule was.

    Per point: when every granted member of a group agrees on direction, the
    granted members are ``mark_changed`` and every other granted member is
    ``absorbed_by_group`` — recorded, never silent (module docstring). When a
    group has granted members in *both* directions, that same-sign rule
    mis-describes what happened (S2 part2+3 final review, m-5): it can flag a
    downward grant ``absorbed_by_group`` when it in fact removed a mark, and
    flag an upward grant ``mark_changed`` twice for one net mark. In that
    case each granted member's own flag instead follows whether *its own*
    verdict actually moved the group's capped running total, walked in list
    order — order-dependent only when the group is at capacity, which is an
    inherent ambiguity of a shared cap, not a property this method invents.
    """
    # A synthetic key for an independent point must never collide with a real
    # ``group_key`` — a scheme whose key were literally ``"point:0"`` would
    # otherwise silently merge two unrelated groups. A tuple key is disjoint
    # from every ``str`` group_key by type, not by convention.
    by_group: dict[str | tuple[str, int], list[_PointPass]] = {}
    for index, item in enumerate(passes):
        by_group.setdefault(item.point.group_key or ("point", index), []).append(item)

    delta = 0
    for members in by_group.values():
        cap = members[0].point.group_max_marks
        if cap is None:
            cap = sum(m.point.tariff for m in members)
        before = min(cap, sum(m.point.tariff for m in members if m.point.awarded))
        after = min(
            cap,
            sum(m.point.tariff for m in members if (m.earned if m.granted else m.point.awarded)),
        )
        group_delta = after - before
        delta += group_delta

        granted = [m for m in members if m.granted]
        directions = {m.earned for m in granted}
        if len(directions) <= 1:
            # Every granted member (if any) agrees on direction: the naive
            # same-sign rule is unambiguous — a group that moved credits all
            # of them, a group that didn't absorbs all of them.
            for m in granted:
                m.mark_changed = group_delta != 0 and (group_delta > 0) == m.earned
                m.absorbed_by_group = not m.mark_changed
        else:
            # Mixed-direction grants: walk the group in list order, tracking
            # each member's own marginal contribution to the capped running
            # total, before and after. A member's flag is `mark_changed`
            # only if flipping *its own* verdict actually moved that running
            # total; the rest are `absorbed_by_group`.
            running_before = running_after = 0
            capped_before_prev = capped_after_prev = 0
            for m in members:
                running_before += m.point.tariff if m.point.awarded else 0
                capped_before = min(cap, running_before)
                after_flag = m.earned if m.granted else m.point.awarded
                running_after += m.point.tariff if after_flag else 0
                capped_after = min(cap, running_after)
                if m.granted:
                    m.mark_changed = (capped_after - capped_after_prev) != (
                        capped_before - capped_before_prev
                    )
                    m.absorbed_by_group = not m.mark_changed
                capped_before_prev = capped_before
                capped_after_prev = capped_after
    return delta


class _HasGroupFlags(Protocol):
    """The three group columns :func:`points_are_settleable` reads.

    A protocol rather than :class:`QuestionResultPoint` so the same predicate
    serves ``list_questions``, which reads those columns without loading whole
    rows.
    """

    @property
    def is_alternative(self) -> bool: ...
    @property
    def is_optional(self) -> bool: ...
    @property
    def group_key(self) -> str | None: ...
    @property
    def group_max_marks(self) -> int | None: ...


@dataclass(frozen=True, slots=True)
class _PointFlags:
    """The four group columns, read without loading whole point rows."""

    is_alternative: bool
    is_optional: bool
    group_key: str | None
    group_max_marks: int | None


def points_are_settleable(points: Iterable[_HasGroupFlags]) -> bool:
    """Can this question's points be capped by the scheme groups they belong to?

    ``_settle_groups`` caps a grant by ``group_key`` / ``group_max_marks``.
    Migration 0038 added those columns with **no data migration**, and 0037 --
    which writes the point rows -- is already deployed, so rows exist that are
    self-reviewable (they have points) yet carry no group data. On those, every
    point looks independent and an either/or pair pays out twice: measured on a
    2-mark question whose alternatives are worth 1, a student self-marking both
    halves scored 2. That is the exact exploit ``_settle_groups`` exists to
    close.

    The group data cannot be reconstructed here -- it comes from the parsed
    mark scheme at correction time -- so such a question is not offered for
    self-review at all, the same absence a quiz gets. Withholding the feature
    on the papers marked in that window is the honest outcome; capping them by
    guesswork is not.

    Conservative by design: a point that is genuinely alone in its group (a
    first-point alternative, a pool of one) also carries a NULL ``group_key``
    and is refused here even though capping it by its own tariff would be
    correct. That costs a rarely-shaped question its panel; the other error
    direction hands out marks the scheme never had.
    """
    return not any(
        ((point.is_alternative or point.is_optional) and point.group_key is None)
        # A named group with no cap is the same hole from the other side:
        # _settle_groups falls back to the sum of the members' tariffs, which
        # is exactly the uncapped arithmetic the group data exists to prevent.
        or (point.group_key is not None and point.group_max_marks is None)
        for point in points
    )


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce to UUID; a malformed id is a 404, like every other student route."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise SelfReviewNotFoundError(f"No such question: {value!r}") from exc


def _owned_question(
    session: Session,
    student_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    qr_uuid: uuid.UUID,
    *,
    for_update: bool,
) -> tuple[Attempt, QuestionResult]:
    """Load the caller's question or raise 404. Every failure is the same 404."""
    # Locked before the QuestionResult (attempt-then-question is already the
    # access order elsewhere in this module and in review_repo, so this
    # introduces no new deadlock risk). Without this lock, two submissions on
    # different questions of the same attempt each read a stale Attempt,
    # recompute totals from it, and the second overwrites the first's write —
    # silently losing one question's contribution to awarded_marks (finding 3).
    attempt = session.get(Attempt, attempt_uuid, with_for_update=for_update)
    if attempt is None or attempt.user_id != student_uuid:
        raise SelfReviewNotFoundError(f"No question {qr_uuid} on attempt {attempt_uuid}")
    qr = session.get(QuestionResult, qr_uuid, with_for_update=for_update)
    if qr is None or qr.attempt_id != attempt.id:
        raise SelfReviewNotFoundError(f"No question {qr_uuid} on attempt {attempt_uuid}")
    if not qr.points:
        # A quiz, or a paper corrected before the per-point ledger existed
        # (spec 1 D7, no backfill): there is nothing to self-mark against, so
        # the surface is absent — derived from the rows, not a flag.
        raise SelfReviewNotFoundError(f"Question {qr_uuid} has no mark points to self-review")
    if not points_are_settleable(qr.points):
        raise SelfReviewNotFoundError(
            f"Question {qr_uuid} has mark points written before the group columns existed"
        )
    return attempt, qr


def _to_view(session: Session, qr: QuestionResult) -> PendingSelfReview | RevealedSelfReview:
    evidence_required = not is_marking_low_confidence(qr)
    if not qr.is_self_marked:
        return PendingSelfReview(
            state="not_started",
            attempt_id=qr.attempt_id,
            question_result_id=qr.id,
            question_id=qr.question_id,
            maximum_marks=qr.maximum_marks,
            evidence_required=evidence_required,
            points=[
                PendingPoint(
                    mark_point_id=p.mark_point_id,
                    ordinal=p.ordinal,
                    mark_type=p.mark_type,
                    tariff=p.tariff,
                    point_text=p.point_text,
                    is_alternative=p.is_alternative,
                    is_optional=p.is_optional,
                    group_key=p.group_key,
                    group_max_marks=p.group_max_marks,
                )
                for p in qr.points
            ],
        )
    return _revealed_view(session, qr, evidence_required=evidence_required)


def _revealed_view(
    session: Session, qr: QuestionResult, *, evidence_required: bool
) -> RevealedSelfReview:
    entries = _selfmark_snapshot(session, qr)
    pending_teacher = _has_open_unjudged_row(session, qr)
    # Defensive and unreachable today: the only caller (_to_view) enters this
    # branch when qr.is_self_marked is true, which is precisely
    # student_selfmarked_at is not None.
    submitted_at = qr.student_selfmarked_at
    if submitted_at is None:
        raise ValueError(f"Question {qr.id} is not self-marked")
    return RevealedSelfReview(
        state="revealed" if pending_teacher else "settled",
        attempt_id=qr.attempt_id,
        question_result_id=qr.id,
        question_id=qr.question_id,
        maximum_marks=qr.maximum_marks,
        evidence_required=evidence_required,
        ai_marks=qr.awarded_marks,
        effective_marks=qr.effective_marks,
        student_marks=qr.student_selfmark_marks,
        teacher_settled=qr.is_overridden,
        pending_teacher=pending_teacher,
        submitted_at=submitted_at,
        points=[
            RevealedPoint(
                mark_point_id=p.mark_point_id,
                ordinal=p.ordinal,
                mark_type=p.mark_type,
                tariff=p.tariff,
                point_text=p.point_text,
                is_alternative=p.is_alternative,
                is_optional=p.is_optional,
                group_key=p.group_key,
                group_max_marks=p.group_max_marks,
                awarded=p.awarded,
                student_selfmark=bool(p.student_selfmark),
                student_evidence=p.student_evidence,
                evidence_verdict=p.evidence_verdict.value if p.evidence_verdict else None,
                mark_changed=_snapshot_bool(entries, p, "mark_changed", default=_mark_changed(p)),
                absorbed_by_group=_snapshot_bool(entries, p, "absorbed_by_group", default=False),
                judge_reason=_snapshot_str(entries, p, "judge_reason"),
                verdict=_narrow_point_verdict(p.verdict, mark_point_id=p.mark_point_id),
                evidence_span=p.evidence_span,
                ecf_applied=p.ecf_applied,
            )
            for p in qr.points
        ],
    )


def _mark_changed(point: QuestionResultPoint) -> bool:
    """Column-derived fallback when the snapshot has no ``mark_changed``.

    A disagreement that was granted.
    """
    if point.student_selfmark is None or point.student_selfmark == point.awarded:
        return False
    return point.evidence_verdict in (EvidenceVerdict.not_required, EvidenceVerdict.accepted)


def _selfmark_snapshot(session: Session, qr: QuestionResult) -> dict[str, dict[str, object]]:
    """``mark_point_id -> entry`` from the latest ``student_selfmark`` revision's snapshot.

    The snapshot is where ``submit`` records what the columns cannot: the
    judge's reason, and whether a granted verdict actually moved a mark or was
    absorbed by its group — ``evidence_verdict`` says the claim was accepted;
    only the snapshot says whether marks followed.
    """
    revision = session.scalars(
        select(QuestionResultRevision)
        .where(
            QuestionResultRevision.question_result_id == qr.id,
            QuestionResultRevision.source == RevisionSource.student_selfmark,
        )
        .order_by(QuestionResultRevision.revision.desc())
    ).first()
    if revision is None:
        return {}
    return {
        entry["mark_point_id"]: entry
        for entry in revision.points_snapshot
        if isinstance(entry, dict) and isinstance(entry.get("mark_point_id"), str)
    }


def _snapshot_bool(
    entries: dict[str, dict[str, object]], point: QuestionResultPoint, key: str, *, default: bool
) -> bool:
    value = entries.get(point.mark_point_id, {}).get(key)
    return value if isinstance(value, bool) else default


def _snapshot_str(
    entries: dict[str, dict[str, object]], point: QuestionResultPoint, key: str
) -> str | None:
    value = entries.get(point.mark_point_id, {}).get(key)
    return value if isinstance(value, str) else None


def _has_open_unjudged_row(session: Session, qr: QuestionResult) -> bool:
    count = session.scalar(
        select(func.count())
        .select_from(ReviewQueueItem)
        .where(
            ReviewQueueItem.question_result_id == qr.id,
            ReviewQueueItem.reason == ReviewReason.student_evidence_unjudged,
            ReviewQueueItem.status == ReviewStatus.open,
        )
    )
    return (count or 0) > 0


def _verdicts_by_point(
    verdicts: Sequence[PointVerdict], points: Sequence[QuestionResultPoint]
) -> dict[str, PointVerdict]:
    """Exactly one verdict per point of the question, or a validation error.

    Checked before anything is written, so a rejected submission leaves the
    question exactly as it was — a second, complete POST is still allowed.
    """
    expected = {p.mark_point_id for p in points}
    seen: dict[str, PointVerdict] = {}
    for verdict in verdicts:
        if verdict.mark_point_id in seen:
            raise SelfReviewValidationError(f"Duplicate verdict for point {verdict.mark_point_id}")
        if verdict.mark_point_id not in expected:
            raise SelfReviewValidationError(f"Unknown point {verdict.mark_point_id}")
        seen[verdict.mark_point_id] = verdict
    missing = expected - seen.keys()
    if missing:
        raise SelfReviewValidationError(f"Every point needs a verdict; missing {sorted(missing)}")
    return seen


def _clean_text(text: str | None, limit: int) -> str | None:
    """Strip NUL bytes and unencodable characters, trim, bound, blank→None.

    Postgres text/JSONB reject both — a lone surrogate survives
    ``json.loads`` of a student's evidence string but cannot be encoded as
    UTF-8, and aborts the transaction on flush if it reaches the database
    unchanged.
    """
    if text is None:
        return None
    cleaned = text.encode("utf-8", "ignore").decode("utf-8").replace("\x00", "").strip()
    if not cleaned:
        return None
    return cleaned[:limit]


def _append_revision(
    session: Session,
    qr: QuestionResult,
    *,
    actor: uuid.UUID,
    snapshot: list[dict[str, object]],
    changed: bool,
) -> None:
    """Append the ``student_selfmark`` revision — on every pass (module docstring)."""
    latest = session.scalar(
        select(func.max(QuestionResultRevision.revision)).where(
            QuestionResultRevision.question_result_id == qr.id
        )
    )
    session.add(
        QuestionResultRevision(
            question_result_id=qr.id,
            revision=(latest or 0) + 1,
            source=RevisionSource.student_selfmark,
            awarded_marks=qr.effective_marks,
            points_snapshot=snapshot,
            actor_user_id=actor,
            reason=(
                "Student self-mark: marks changed" if changed else "Student self-mark: no change"
            ),
        )
    )
    session.flush()


def _resolve_low_confidence_rows(
    session: Session, qr: QuestionResult, *, resolver: uuid.UUID, now: datetime
) -> None:
    """D4: close the open ``low_confidence`` row(s) with the student as resolver.

    Only that reason. An integrity row on the same question is a teacher's
    to dismiss and is never touched here.
    """
    rows = session.scalars(
        select(ReviewQueueItem).where(
            ReviewQueueItem.question_result_id == qr.id,
            ReviewQueueItem.reason == ReviewReason.low_confidence,
            ReviewQueueItem.status == ReviewStatus.open,
        )
    ).all()
    for row in rows:
        row.status = ReviewStatus.resolved
        row.resolved_by = resolver
        row.resolved_at = now
        row.resolution_note = SELFMARK_RESOLUTION_NOTE


__all__ = [
    "MAX_EVIDENCE_CHARS",
    "MAX_JUDGE_REASON_CHARS",
    "SELFMARK_RESOLUTION_NOTE",
    "AttemptQuestion",
    "PendingPoint",
    "PendingSelfReview",
    "PointVerdict",
    "RevealedPoint",
    "RevealedSelfReview",
    "SelfReviewAlreadySubmittedError",
    "SelfReviewError",
    "SelfReviewNotFoundError",
    "SelfReviewService",
    "SelfReviewValidationError",
]
