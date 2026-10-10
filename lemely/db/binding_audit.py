"""Read-only audit of stored attempts for answers that were bound to the wrong question.

An exam script was once read with every answer one question late, and a paper a
teacher marked 66/80 was stored and published as 2/80. Attempts stored since the
fault may be misbound too. This module runs the two checks that need only the
stored rows (G6, the wrong kind of answer, and G7, a run of answers holding the
value of a neighbouring question) over each attempt and reports what looks wrong.

Functions take the ORM types in their signatures; they read only ``question_id``
and ``student_answer`` of a result and the plain columns of an attempt, so tests
pass stand-ins with those attributes.

It changes nothing: it opens a session, queries, and closes it. A person decides
what to do with the list.

What the checks can see is limited. G7 only sees questions with numeric expected
answers, and short shifts are mostly invisible, so an attempt that is not listed
is not thereby correctly bound. ``AuditReport.not_judgeable`` counts the audited
attempts whose scheme had too few such questions for G7 to ever fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import selectinload

from lemely.core.binding_expect import expected_numeric_values
from lemely.core.binding_gate import GateThresholds, check_shape, check_shift
from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import ExamMetadata, ExtractedAnswer, ExtractedAnswers
from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import SESSION_MONTH_LABELS, AttemptOrigin

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session

    from lemely.core.binding import BindingCheck
    from lemely.core.loose_schemas import MarkScheme, Question
    from lemely.db.models.attempts import QuestionResult

log = structlog.get_logger(__name__)

_THRESHOLDS = GateThresholds()
_MISMATCH_SHARE = 0.25
_AUDIT_PAPER = "audit"
_AUDIT_SOURCE = "stored-attempt"


@dataclass(frozen=True)
class Suspect:
    """An attempt on which a paper-scope check failed."""

    attempt_id: str
    user_id: str
    paper: str
    recorded_at: str
    awarded_marks: int
    maximum_marks: int
    failed_checks: list[str]
    details: list[str]

    def as_json(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "user_id": self.user_id,
            "paper": self.paper,
            "recorded_at": self.recorded_at,
            "awarded_marks": self.awarded_marks,
            "maximum_marks": self.maximum_marks,
            "failed_checks": self.failed_checks,
            "details": self.details,
        }


@dataclass
class AuditReport:
    """What an audit found.

    ``selected`` is every attempt looked at. It equals ``audited`` plus the
    counters of attempts that were not judged, each for its own reason
    (``scheme_not_found``, ``unreadable_identity``, ``no_paper_identity``,
    ``scheme_mismatch``, ``no_answers``). ``not_judgeable``, ``year_assumed`` and
    ``question_scope_only`` are counted within ``audited``.
    """

    suspects: list[Suspect] = field(default_factory=list)
    question_scope_only: int = 0
    audited: int = 0
    not_judgeable: int = 0
    scheme_not_found: int = 0
    unreadable_identity: int = 0
    no_paper_identity: int = 0
    scheme_mismatch: int = 0
    no_answers: int = 0
    year_assumed: int = 0
    selected: int = 0

    def as_json(self) -> dict[str, object]:
        return {
            "suspects": [s.as_json() for s in self.suspects],
            "question_scope_only": self.question_scope_only,
            "audited": self.audited,
            "not_judgeable": self.not_judgeable,
            "scheme_not_found": self.scheme_not_found,
            "unreadable_identity": self.unreadable_identity,
            "no_paper_identity": self.no_paper_identity,
            "scheme_mismatch": self.scheme_mismatch,
            "no_answers": self.no_answers,
            "year_assumed": self.year_assumed,
            "selected": self.selected,
        }


def audit_attempt(
    question_results: Sequence[QuestionResult], mark_scheme: MarkScheme
) -> list[BindingCheck]:
    """Every G6 and G7 check on one attempt's stored answers, passed and failed.

    Stored rows are already keyed by manifest id, so the id checks (G1, G2) cannot
    fire on them and are not run. A row with no answer text is not an answer.
    """
    extracted = ExtractedAnswers(
        paper_id=_AUDIT_PAPER,
        source_scan=_AUDIT_SOURCE,
        answers=[
            ExtractedAnswer(question_id=row.question_id, answer=row.student_answer, confidence=1.0)
            for row in question_results
            if row.student_answer and row.student_answer.strip()
        ],
    )
    return [
        check_shape(extracted, mark_scheme, _THRESHOLDS),
        *check_shift(extracted, mark_scheme, _THRESHOLDS),
    ]


def is_suspect(checks: Iterable[BindingCheck]) -> bool:
    """True when any check failed at paper scope."""
    return any(c.scope == "paper" and not c.passed for c in checks)


def _has_question_scope_failure(checks: Iterable[BindingCheck]) -> bool:
    return any(c.scope == "question" and not c.passed for c in checks)


def is_judgeable(mark_scheme: MarkScheme) -> bool:
    """False when G7 can never fail on this scheme.

    G7 needs at least ``shift_min_matches`` non-multiple-choice questions with an
    expected numeric value to build a run of that length.
    """
    leaves: list[Question] = [
        q for q in mark_scheme.all_questions_flat() if not q.parts and q.marks > 0
    ]
    with_values = sum(
        1
        for q in leaves
        if q.type != QuestionType.MCQ and q.mcq_answer is None and expected_numeric_values(q)
    )
    return with_values >= _THRESHOLDS.shift_min_matches


def exam_metadata(attempt: Attempt) -> ExamMetadata | None:
    """The paper identity stored on an attempt, or ``None`` when it is incomplete."""
    if (
        attempt.subject_code is None
        or attempt.paper_number is None
        or attempt.paper_variant is None
        or attempt.session_month is None
    ):
        return None
    return ExamMetadata(
        subject_code=attempt.subject_code,
        paper_number=attempt.paper_number,
        paper_variant=attempt.paper_variant,
        session_month=SESSION_MONTH_LABELS[attempt.session_month],
        session_year=attempt.session_year,
    )


def _paper_label(attempt: Attempt) -> str:
    parts = [f"{attempt.subject_code}/{attempt.paper_number}{attempt.paper_variant}"]
    if attempt.session_month is not None:
        parts.append(SESSION_MONTH_LABELS[attempt.session_month])
    if attempt.session_year is not None:
        parts.append(str(attempt.session_year))
    return " ".join(parts)


def _leaf_ids(mark_scheme: MarkScheme) -> set[str]:
    return {q.id for q in mark_scheme.all_questions_flat() if not q.parts and q.marks > 0}


def _ids_do_not_match(attempt: Attempt, mark_scheme: MarkScheme) -> bool:
    """True when over a quarter of the answered rows carry an id the scheme lacks."""
    known = _leaf_ids(mark_scheme)
    answered = [r.question_id for r in attempt.question_results if (r.student_answer or "").strip()]
    unknown = sum(1 for qid in answered if qid not in known)
    return bool(answered) and unknown / len(answered) > _MISMATCH_SHARE


def audit_attempts(
    attempts: Iterable[Attempt],
    find_scheme: Callable[[ExamMetadata], MarkScheme | None],
) -> AuditReport:
    """Audit each attempt; one that cannot be judged is counted under its own reason.

    A database that cannot be reached still raises: only a row or a stored scheme
    that is itself unreadable is counted and skipped.
    """
    report = AuditReport()
    schemes: dict[str, MarkScheme | None] = {}
    for attempt in attempts:
        report.selected += 1
        try:
            metadata = exam_metadata(attempt)
        except ValidationError as exc:
            log.warning("audit_unreadable_identity", attempt_id=str(attempt.id), error=str(exc))
            report.unreadable_identity += 1
            continue
        if metadata is None:
            report.no_paper_identity += 1
            continue
        key = metadata.model_dump_json()
        if key not in schemes:
            try:
                schemes[key] = find_scheme(metadata)
            except (OperationalError, InterfaceError):
                raise
            except Exception as exc:
                log.warning("audit_scheme_lookup_failed", paper=key, error=str(exc))
                schemes[key] = None
        scheme = schemes[key]
        if scheme is None:
            report.scheme_not_found += 1
            continue
        if _ids_do_not_match(attempt, scheme):
            report.scheme_mismatch += 1
            continue
        if not any((r.student_answer or "").strip() for r in attempt.question_results):
            report.no_answers += 1
            continue
        report.audited += 1
        if metadata.session_year is None:
            report.year_assumed += 1
        if not is_judgeable(scheme):
            report.not_judgeable += 1
        checks = audit_attempt(attempt.question_results, scheme)
        if is_suspect(checks):
            failed = [c for c in checks if not c.passed]
            report.suspects.append(
                Suspect(
                    attempt_id=str(attempt.id),
                    user_id=str(attempt.user_id),
                    paper=_paper_label(attempt),
                    recorded_at=attempt.recorded_at.isoformat(),
                    awarded_marks=attempt.awarded_marks,
                    maximum_marks=attempt.maximum_marks,
                    failed_checks=list(dict.fromkeys(c.id for c in failed)),
                    details=[c.detail for c in failed],
                )
            )
        elif _has_question_scope_failure(checks):
            report.question_scope_only += 1
    return report


def load_attempts(
    session: Session,
    *,
    since: datetime | None = None,
    limit: int | None = None,
    uploaded_only: bool = True,
) -> list[Attempt]:
    """Stored attempts, newest first, with their question results.

    ``uploaded_only`` keeps past-paper attempts that came from an uploaded scan:
    quizzes are typed answers and cannot be misbound. Rows the student deleted
    are hidden by the session's own loader criterion.
    """
    stmt = (
        select(Attempt)
        .options(selectinload(Attempt.question_results))
        .order_by(Attempt.recorded_at.desc())
    )
    if uploaded_only:
        stmt = stmt.where(
            Attempt.origin == AttemptOrigin.past_paper, Attempt.upload_id.is_not(None)
        )
    if since is not None:
        stmt = stmt.where(Attempt.recorded_at >= since)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


__all__ = [
    "AuditReport",
    "Suspect",
    "audit_attempt",
    "audit_attempts",
    "exam_metadata",
    "is_judgeable",
    "is_suspect",
    "load_attempts",
]
