"""Question bank repository (P3.5 chunk B, ``docs/quiz-model.md`` §1.3/§2).

Four things, matching the chunk-B brief exactly:

1. :func:`visible_bank_filter` — the **single** three-tier visibility
   predicate (owner/school/shared) every :class:`QuestionBank` query must
   apply. §1.3 names the failure mode this exists to prevent: if the
   pool-count endpoint (chunk D) and the quiz builder's selection query ever
   expressed "visible" differently, a teacher would see a count of 40 and
   get a quiz of 12 with no explanation.
2. :class:`QuestionBankService` — bulk insert (:meth:`~QuestionBankService.add_questions`,
   used by the generated-file importer below and, later, by
   ``/quizzes/generate``) plus the two read helpers chunk D's pool-count
   endpoint and quiz builder both need: :meth:`~QuestionBankService.count_by_band`
   and :meth:`~QuestionBankService.select_questions`. Every read applies
   ``is_active`` and :func:`visible_bank_filter` — a helper that forgets
   either is the defect this chunk exists to prevent.
3. :func:`import_generated_quiz_files` — a one-shot importer for the
   on-disk ``GeneratedQuiz`` JSON files ``teacher.quiz_generate`` already
   writes to ``output_dir/questions``. Chunk D moves that route onto the
   bank directly; until then this backfills whatever already exists on disk
   (today: nothing — ``outputs/questions/`` does not exist, so this is a
   0-row import against the current repo state, and that is the correct,
   honest answer, not a bug).
4. :func:`survey_past_paper_questions` — **a reporting function over
   mark-scheme payloads, not a writer**. ``BUILD/DECISIONS.md`` D3.7 records
   the original measurement: across the Phase-3 parsed corpus, 0 of 122 leaf
   questions carried prompt text, because
   :class:`~lemely.core.loose_schemas.Question` (the mark-scheme model) has
   no question-stem field at all — a CAIE mark scheme contains marking
   points, not the question text; the stem lives in the paired question
   paper. **P4.1 closed that gap**: ``lemely.io.det.question_papers``
   deterministically extracts stems from question-paper PDFs, and
   ``lemely.io.question_papers.ingest_question_papers_dir`` pairs them with
   parsed mark schemes and writes real ``source=past_paper`` bank rows
   through :meth:`QuestionBankService.add_questions` — the same writer this
   module's other three pieces use. Persisting past-paper questions is no
   longer structurally impossible.

   What did *not* change: this specific function still walks
   ``mark_schemes.parsed_payload`` rows only, and a mark-scheme payload
   still never carries a stem — so :func:`survey_past_paper_questions`
   itself still reports 0 producible from that input, honestly, not because
   the feature is missing but because this function was never the writer
   for it. Use ``lemely ingest-question-papers`` (CLI) for real past-paper
   coverage; this survey remains useful as-is for auditing mark-scheme
   corpus shape (topic hints, inferred difficulty distribution) independent
   of stem availability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, cast

import structlog
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select

from lemely.core.difficulty import Band, infer_difficulty
from lemely.core.generation import GeneratedQuiz
from lemely.core.loose_schemas import MarkScheme as ParsedMarkScheme
from lemely.core.loose_schemas import QuestionType
from lemely.core.topics import classify, is_writable
from lemely.db.models.academic import MarkScheme as MarkSchemeRecord
from lemely.db.models.academic import Paper, Subject
from lemely.db.models.enums import (
    SESSION_MONTH_LABELS,
    DifficultySource,
    ExamBoard,
    QuestionDifficulty,
    QuestionSource,
    SessionMonth,
)
from lemely.db.models.quizzes import QuestionBank
from lemely.io.metadata import parse_caie_qp_filename_metadata
from lemely.io.syllabus_topics import get_taxonomy

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from pathlib import Path

    from sqlalchemy import ColumnElement
    from sqlalchemy.orm import Session, sessionmaker

log = structlog.get_logger(__name__)

#: :class:`~lemely.core.generation.GeneratedQuestion` carries no
#: ``question_type`` field — the generator only ever produces open-ended,
#: mark-scheme-based responses (never MCQ, diagram, graph, levels-based, or
#: indicative-content). ``docs/quiz-model.md`` §2 says "GeneratedQuestion
#: maps field-for-field [onto bank rows]", but the source schema has no
#: field to map for this column: a gap in the design doc, not in this
#: ingest. Every row :func:`import_generated_quiz_files` creates records
#: this documented default; if ``GeneratedQuestion`` ever grows a real
#: declared type, read it here instead of defaulting it.
_GENERATED_QUESTION_TYPE: Final = QuestionType.EXPLANATION.value


# ---------------------------------------------------------------------------
# 1. The visibility predicate
# ---------------------------------------------------------------------------


def visible_bank_filter(
    caller_id: uuid.UUID | None, school_ids: Sequence[uuid.UUID]
) -> ColumnElement[bool]:
    """The single §1.3 visibility predicate for :class:`QuestionBank` rows.

    Three tiers, OR'd together:

    * ``owner_id IS NULL AND school_id IS NULL`` — platform-shared (past
      papers, platform-generated questions): visible to everyone.
    * ``owner_id = caller_id`` — that caller's own generations/uploads only.
    * ``school_id IN school_ids`` — members of one of the caller's schools.

    This must be composed into **every** ``question_bank`` query — the
    count endpoint and the selection query calling this same function is
    what makes their agreement structural rather than a matter of two
    implementers happening to write the same ``WHERE`` twice (see module
    docstring).

    ``caller_id=None``/``school_ids=()`` still returns a valid predicate: it
    degrades to "platform-shared rows only", never to "everything" (a
    permissive bug) and never to a vacuous always-false clause (a
    denial-of-service bug) — an unauthenticated or school-less caller sees
    exactly the shared pool.
    """
    clauses: list[ColumnElement[bool]] = [
        and_(QuestionBank.owner_id.is_(None), QuestionBank.school_id.is_(None))
    ]
    if caller_id is not None:
        clauses.append(QuestionBank.owner_id == caller_id)
    if school_ids:
        clauses.append(QuestionBank.school_id.in_(school_ids))
    return or_(*clauses)


# ---------------------------------------------------------------------------
# 2. QuestionBankService — bulk insert + the pool-count/selection helpers
# ---------------------------------------------------------------------------


_SESSION_MONTH_BY_LABEL: Final[dict[str, SessionMonth]] = {
    label: member for member, label in SESSION_MONTH_LABELS.items()
}
"""Inverse of the display map. ``ExamMetadata.session_month`` is the *label*
(``"May/June"``); the ``papers`` column is the enum. Derived from the one
mapping rather than restated, so the two cannot drift apart."""


def _paper_identity(board: ExamBoard, source_question_id: str | None) -> _PaperIdentity | None:
    """Parse a bank row's paper identity out of its ``source_question_id``.

    P4.1 builds that value as ``f"{qp_stem}#{ref}"`` — e.g.
    ``"0625_s23_qp_11#22"`` — so the stem before the ``#`` is the source PDF's
    filename, and the same parser the ingest used reads it back. Returns
    ``None`` (never a partial guess) if the stem does not parse.
    """
    if not source_question_id or "#" not in source_question_id:
        return None
    stem = source_question_id.split("#", 1)[0]
    try:
        meta = parse_caie_qp_filename_metadata(f"{stem}.pdf")
    except ValueError:
        return None
    month = _SESSION_MONTH_BY_LABEL.get(meta.session_month)
    if month is None:
        return None
    return _PaperIdentity(
        board=board,
        subject_code=meta.subject_code,
        session_month=month,
        session_year=meta.session_year,
        paper_number=meta.paper_number,
        paper_variant=meta.paper_variant,
    )


def _resolve_paper(session: Session, identity: _PaperIdentity) -> tuple[uuid.UUID, bool] | None:
    """Get-or-create the ``papers`` row (and the ``subjects`` row it FKs to).

    Returns ``(paper_id, created)``, or ``None`` when the subject has no
    bundled syllabus taxonomy — ``subjects.name`` is NOT NULL and the only
    honest source for it is the transcribed ``subject_name`` D4.4 already
    loads. Inventing a display name to satisfy a foreign key would put a made-up
    string in front of a user.
    """
    existing = session.scalars(
        select(Paper).where(
            Paper.board == identity.board,
            Paper.subject_code == identity.subject_code,
            Paper.session_month == identity.session_month,
            Paper.session_year == identity.session_year,
            Paper.paper_number == identity.paper_number,
            Paper.paper_variant == identity.paper_variant,
        )
    ).first()
    if existing is not None:
        return existing.id, False

    # Looked up by `code`, not by primary key: `subjects.id` is a generated
    # uuid and `code` is the natural key the FK on `papers` actually points at.
    subject = session.scalars(select(Subject).where(Subject.code == identity.subject_code)).first()
    if subject is None:
        taxonomy = get_taxonomy(identity.subject_code, board=identity.board.value)
        if taxonomy is None:
            return None
        subject = Subject(
            code=identity.subject_code, name=taxonomy.subject_name, board=identity.board
        )
        session.add(subject)
        session.flush()

    paper = Paper(
        board=identity.board,
        subject_code=identity.subject_code,
        session_month=identity.session_month,
        session_year=identity.session_year,
        paper_number=identity.paper_number,
        paper_variant=identity.paper_variant,
    )
    session.add(paper)
    session.flush()
    return paper.id, True


@dataclass(slots=True)
class PaperLinkOutcome:
    """Counts from :meth:`QuestionBankService.link_past_paper_rows`.

    Every non-linked row lands in exactly one counter, so ``considered`` always
    equals ``linked + unparseable + no_subject_taxonomy`` — a backfill that
    quietly drops rows is the failure mode this shape prevents.
    """

    considered: int = 0
    linked: int = 0
    papers_created: int = 0
    unparseable: int = 0
    """``source_question_id`` did not carry a parseable CAIE paper stem. Left
    unlinked rather than attached to a guessed paper."""
    no_subject_taxonomy: int = 0
    """No bundled syllabus for the subject, so no transcribed subject name for
    the ``subjects`` row the FK needs. Skipped rather than given an invented
    display name."""


@dataclass(frozen=True, slots=True)
class _PaperIdentity:
    """The six columns of ``uq_papers_identity``, as a hashable cache key."""

    board: ExamBoard
    subject_code: str
    session_month: SessionMonth
    session_year: int | None
    paper_number: int
    paper_variant: int


@dataclass(frozen=True, slots=True)
class NewBankQuestion:
    """Everything :meth:`QuestionBankService.add_questions` needs for one row.

    Provenance-agnostic: today only the generated importer builds these, but
    the shape is exactly what a future past-paper writer or
    ``/quizzes/generate`` (chunk D) needs too, so one insert path serves all
    three sources rather than each growing its own.
    """

    subject_code: str
    source: QuestionSource
    difficulty: Band
    difficulty_source: DifficultySource
    question_type: str
    prompt: str
    total_marks: int
    board: ExamBoard = ExamBoard.caie
    owner_id: uuid.UUID | None = None
    school_id: uuid.UUID | None = None
    paper_id: uuid.UUID | None = None
    """The ``papers`` row this question came from.

    Left ``None`` by the P4.1 past-paper writer, which had no reason to create
    ``Paper`` rows; :meth:`QuestionBankService.link_past_paper_rows` fills it
    afterwards from ``source_question_id``. P4.4 made it load-bearing —
    placement duration estimates resolve through it (D4.6 §5) — so a row
    without it is placement-ineligible, not merely under-described.
    """
    source_question_id: str | None = None
    topic: str | None = None
    model_answer: str | None = None
    mark_scheme_points: list[str] = field(default_factory=list)
    mcq_options: list[str] | None = None
    mcq_answer: str | None = None
    source_question_ids: list[str] = field(default_factory=list)
    is_active: bool = True
    created_by: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class QuestionBankRow:
    """One selected bank row, read-shaped for a quiz builder (chunk D)."""

    id: uuid.UUID
    subject_code: str
    source: QuestionSource
    topic: str | None
    difficulty: Band
    difficulty_source: DifficultySource
    question_type: str
    prompt: str
    model_answer: str | None
    mark_scheme_points: list[str]
    mcq_options: list[str] | None
    mcq_answer: str | None
    total_marks: int
    source_question_ids: list[str]


class QuestionBankService:
    """Bulk insert plus the pool-count/selection helpers.

    Chunk D's pool-count endpoint and quiz builder both share these.
    Constructed with a ``sessionmaker`` (mirrors
    :class:`~lemely.db.class_repo.ClassService`). Deliberately narrow: no
    per-row CRUD, no update/deactivate — those belong to the teacher-upload
    (T-11) and quiz-generate (chunk D) writers, which do not exist yet
    (MISSION §8b: no speculative API surface).
    """

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the service to a session factory."""
        self._sessionmaker = sessionmaker

    def add_questions(self, rows: Sequence[NewBankQuestion]) -> list[uuid.UUID]:
        """Bulk-insert bank rows in one transaction, returning their ids in order.

        ``rows`` is empty-safe: an empty sequence returns ``[]`` without
        opening a session, so a caller whose upstream filtering removed
        everything (e.g. every file in an import directory was malformed)
        does not pay for a no-op transaction.
        """
        if not rows:
            return []
        with self._sessionmaker() as session, session.begin():
            objs = [
                QuestionBank(
                    board=row.board,
                    subject_code=row.subject_code,
                    source=row.source,
                    owner_id=row.owner_id,
                    school_id=row.school_id,
                    paper_id=row.paper_id,
                    source_question_id=row.source_question_id,
                    topic=row.topic,
                    difficulty=QuestionDifficulty(row.difficulty),
                    difficulty_source=row.difficulty_source,
                    question_type=row.question_type,
                    prompt=row.prompt,
                    model_answer=row.model_answer,
                    mark_scheme_points=list(row.mark_scheme_points),
                    mcq_options=list(row.mcq_options) if row.mcq_options is not None else None,
                    mcq_answer=row.mcq_answer,
                    total_marks=row.total_marks,
                    source_question_ids=list(row.source_question_ids),
                    is_active=row.is_active,
                    created_by=row.created_by,
                )
                for row in rows
            ]
            session.add_all(objs)
            session.flush()
            return [obj.id for obj in objs]

    def count_by_band(
        self,
        caller_id: uuid.UUID | None,
        school_ids: Sequence[uuid.UUID],
        *,
        subject_code: str,
        topics: Sequence[str] | None = None,
        source: QuestionSource | None = None,
    ) -> dict[Band, int]:
        """Visible, active row counts per difficulty band for a filter set.

        Always returns all three :data:`~lemely.core.difficulty.Band` keys
        (0 for a band with no matches), so a caller (the allocator in
        ``docs/quiz-model.md`` §3) can compute a per-band shortfall without a
        membership check first.
        """
        with self._sessionmaker() as session:
            stmt = (
                select(QuestionBank.difficulty, func.count())
                .where(*self._filters(caller_id, school_ids, subject_code, topics, source))
                .group_by(QuestionBank.difficulty)
            )
            rows = session.execute(stmt).all()
        counts: dict[Band, int] = {"foundation": 0, "standard": 0, "challenge": 0}
        for difficulty, n in rows:
            counts[cast("Band", difficulty.value)] = int(n)
        return counts

    def select_questions(
        self,
        caller_id: uuid.UUID | None,
        school_ids: Sequence[uuid.UUID],
        *,
        subject_code: str,
        band: Band,
        count: int,
        topics: Sequence[str] | None = None,
        source: QuestionSource | None = None,
    ) -> list[QuestionBankRow]:
        """Select up to ``count`` visible, active rows in one band.

        Uses exactly the same ``_filters`` call as :meth:`count_by_band`
        (plus the band itself), so a caller that checked the count first and
        then selects can never see the selection return fewer rows than the
        count promised for an identical filter set — the divergence §1.3
        warns about is structurally excluded by sharing the filter builder,
        not merely tested for after the fact.

        ``count <= 0`` returns ``[]`` without a query — a draft quiz with no
        requested count yet is a legitimate state (``docs/quiz-model.md``
        §1.4), not an error.
        """
        if count <= 0:
            return []
        with self._sessionmaker() as session:
            stmt = (
                select(QuestionBank)
                .where(
                    *self._filters(caller_id, school_ids, subject_code, topics, source),
                    QuestionBank.difficulty == QuestionDifficulty(band),
                )
                .order_by(func.random())
                .limit(count)
            )
            objs = session.scalars(stmt).all()
            return [_to_row(obj) for obj in objs]

    def existing_source_question_ids(self, *, source: QuestionSource) -> set[str]:
        """All non-null ``source_question_id`` values already banked for ``source``.

        Backs idempotent re-ingest (``lemely.io.question_papers``,
        P4.1): that writer keys on ``(subject_code, source_question_id)``
        rather than the DB's own partial unique index (which requires
        ``paper_id``, and P4.1 does not create ``Paper`` rows — see that
        module's docstring), so it needs the full existing set up front to
        skip rows it has already written on a prior run. Includes inactive
        rows (``is_active`` not filtered) — a row a teacher deactivated must
        still block a duplicate insert, not silently reappear on the next
        ingest.
        """
        with self._sessionmaker() as session:
            stmt = select(QuestionBank.source_question_id).where(
                QuestionBank.source == source,
                QuestionBank.source_question_id.is_not(None),
            )
            return {row for row in session.scalars(stmt).all() if row is not None}

    def link_past_paper_rows(self, *, dry_run: bool = False) -> PaperLinkOutcome:
        """Fill ``question_bank.paper_id`` for banked past-paper questions.

        **Why this exists.** P4.1 banked 273 real past-paper questions and left
        every one of them with ``paper_id IS NULL`` — that module's docstring
        says so plainly ("P4.1 does not create ``Paper`` rows"), and nothing
        needed the link until now. P4.4 does: a placement estimate is
        ``total_marks * (paper duration / paper total marks)``, and the only
        route from a bank row to its paper's number is this column (D4.6 §5).
        Without it *every* question is ineligible and placement is
        un-assemblable for 0625 too — which is what an orchestrator measurement
        against the real bank actually returned, before this method existed.

        The paper identity is not inferred: it is parsed from the
        ``source_question_id``, which P4.1 already builds as
        ``f"{qp_stem}#{ref}"`` from the source PDF's filename, by the same
        :func:`~lemely.io.metadata.parse_caie_qp_filename_metadata` the
        ingest used. A row whose stem does not parse is left unlinked and
        counted, never linked to a guessed paper.

        ``Paper`` rows are created on demand (``papers`` is empty today), and
        so is the ``subjects`` row its FK requires — with the subject *name*
        taken from the bundled syllabus taxonomy, the same transcribed source
        D4.4 used. A subject with no bundled taxonomy is skipped rather than
        given an invented display name; its questions stay unlinked, which the
        availability path already reports honestly.

        Idempotent: only rows with a NULL ``paper_id`` are considered.
        """
        outcome = PaperLinkOutcome()
        # Not `session.begin()`: a dry run must be able to create Paper rows in
        # the session (so the *second* row for the same paper takes the cache
        # path and the counts are the real ones) and then throw them away. The
        # commit is explicit and only happens on a live run.
        with self._sessionmaker() as session:
            rows = session.scalars(
                select(QuestionBank).where(
                    QuestionBank.source == QuestionSource.past_paper,
                    QuestionBank.paper_id.is_(None),
                    QuestionBank.source_question_id.is_not(None),
                )
            ).all()
            outcome.considered = len(rows)
            cache: dict[_PaperIdentity, uuid.UUID] = {}
            for row in rows:
                identity = _paper_identity(row.board, row.source_question_id)
                if identity is None:
                    outcome.unparseable += 1
                    continue
                paper_id = cache.get(identity)
                if paper_id is None:
                    resolved = _resolve_paper(session, identity)
                    if resolved is None:
                        outcome.no_subject_taxonomy += 1
                        continue
                    paper_id, created = resolved
                    cache[identity] = paper_id
                    outcome.papers_created += int(created)
                row.paper_id = paper_id
                outcome.linked += 1
            if dry_run:
                session.rollback()
            else:
                session.commit()
        return outcome

    def has_inferred_difficulty(
        self,
        caller_id: uuid.UUID | None,
        school_ids: Sequence[uuid.UUID],
        *,
        subject_code: str,
        topics: Sequence[str] | None = None,
        source: QuestionSource | None = None,
    ) -> bool:
        """Whether the visible, active matching set contains any ``inferred_from_marks`` row.

        Backs the pool-count endpoint's ``difficultyEstimated`` flag (chunk D,
        ``docs/quiz-model.md`` §2/§3.2): true whenever any past-paper question
        in the matching set carries an *estimated* (not declared or
        teacher-set) difficulty band, so the UI can label the count
        accordingly rather than presenting every band as equally precise.

        Reuses :meth:`_filters` — the exact predicate :meth:`count_by_band`
        and :meth:`select_questions` build from — so "matching" can never
        mean something different here than it does for the count itself
        (§1.3's shared-predicate discipline).
        """
        with self._sessionmaker() as session:
            stmt = (
                select(QuestionBank.id)
                .where(
                    *self._filters(caller_id, school_ids, subject_code, topics, source),
                    QuestionBank.difficulty_source == DifficultySource.inferred_from_marks,
                )
                .limit(1)
            )
            return session.scalars(stmt).first() is not None

    def _filters(
        self,
        caller_id: uuid.UUID | None,
        school_ids: Sequence[uuid.UUID],
        subject_code: str,
        topics: Sequence[str] | None,
        source: QuestionSource | None,
    ) -> list[ColumnElement[bool]]:
        """The filter set every read applies: ``is_active`` + visibility + subject.

        The single place :meth:`count_by_band` and :meth:`select_questions`
        both build their ``WHERE`` clause from — see module docstring.
        """
        clauses: list[ColumnElement[bool]] = [
            QuestionBank.is_active.is_(True),
            visible_bank_filter(caller_id, school_ids),
            QuestionBank.subject_code == subject_code,
        ]
        if source is not None:
            clauses.append(QuestionBank.source == source)
        if topics:
            clauses.append(QuestionBank.topic.in_(topics))
        return clauses


def _to_row(obj: QuestionBank) -> QuestionBankRow:
    return QuestionBankRow(
        id=obj.id,
        subject_code=obj.subject_code,
        source=obj.source,
        topic=obj.topic,
        difficulty=obj.difficulty.value,
        difficulty_source=obj.difficulty_source,
        question_type=obj.question_type,
        prompt=obj.prompt,
        model_answer=obj.model_answer,
        mark_scheme_points=list(obj.mark_scheme_points),
        mcq_options=list(obj.mcq_options) if obj.mcq_options is not None else None,
        mcq_answer=obj.mcq_answer,
        total_marks=obj.total_marks,
        source_question_ids=list(obj.source_question_ids),
    )


# ---------------------------------------------------------------------------
# 3. Generated-file importer
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GeneratedImportSkip:
    """One malformed ``GeneratedQuiz`` file the importer declined to read."""

    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class GeneratedImportResult:
    """Outcome of one :func:`import_generated_quiz_files` run."""

    files_read: int
    rows_created: int
    skipped: list[GeneratedImportSkip]


def generated_questions_to_bank_rows(
    quiz: GeneratedQuiz,
    *,
    owner_id: uuid.UUID | None = None,
    school_id: uuid.UUID | None = None,
) -> list[NewBankQuestion]:
    """Map a :class:`GeneratedQuiz`'s questions onto :class:`NewBankQuestion` rows.

    The single field-mapping shared by :func:`import_generated_quiz_files`
    (the one-shot on-disk backfill, ``owner_id=None`` — platform-shared) and
    ``POST /quizzes/generate`` (chunk D, ``owner_id=`` the generating
    teacher — ``docs/quiz-model.md`` §2: "their generation, their pool")
    so the mapping, including :data:`_GENERATED_QUESTION_TYPE`'s documented
    gap, is expressed exactly once rather than drifting between the two
    writers.
    """
    return [
        NewBankQuestion(
            subject_code=quiz.subject_code,
            source=QuestionSource.generated,
            difficulty=question.difficulty,
            difficulty_source=DifficultySource.declared_by_generator,
            question_type=_GENERATED_QUESTION_TYPE,
            prompt=question.prompt,
            total_marks=question.total_marks,
            topic=question.topic,
            model_answer=question.model_answer,
            mark_scheme_points=list(question.mark_scheme_points),
            source_question_ids=list(question.source_question_ids),
            owner_id=owner_id,
            school_id=school_id,
        )
        for question in quiz.questions
    ]


def import_generated_quiz_files(
    service: QuestionBankService, directory: Path
) -> GeneratedImportResult:
    """Import on-disk ``GeneratedQuiz`` JSON files into the question bank.

    Reads every ``*.json`` file in ``directory`` (``output_dir/questions``,
    where ``lemely.web.routers.teacher.quiz_generate`` wrote them **before**
    chunk D moved that route onto the bank directly — this importer now
    exists purely to backfill whatever such files already exist on disk from
    that earlier behaviour), each expected to deserialise as a
    :class:`~lemely.core.generation.GeneratedQuiz`, mapped onto bank rows by
    :func:`generated_questions_to_bank_rows` with ``owner_id = school_id =
    None`` (platform-shared — ``docs/quiz-model.md`` §2: "imported once ...
    with ``owner_id = NULL``").

    A file that is not valid JSON or fails :class:`GeneratedQuiz` validation
    is reported in :attr:`GeneratedImportResult.skipped` and the run
    continues — one bad file must never abort an import of the rest (the
    same tolerance ``teacher._existing_questions`` already applies when
    reading this directory for the live preview).

    This is a one-shot backfill for whatever already exists on disk today,
    not a route this ingest wires up itself; re-running it against the same
    directory re-imports the same files as fresh rows (no idempotency key —
    generated rows carry no ``paper_id``, so ``uq_question_bank_paper_question``
    does not apply here). ``docs/quiz-model.md`` §2 calls this "imported
    once by a one-shot CLI command", which is an operational discipline, not
    a guarantee this function itself enforces.

    Returns:
        A :class:`GeneratedImportResult` reporting files read, rows created,
        and every skipped file — including the honest zero when
        ``directory`` does not exist (``docs/quiz-model.md`` §2: "The
        on-disk ``GeneratedQuiz`` import is likewise 0 rows today").
    """
    if not directory.exists():
        return GeneratedImportResult(files_read=0, rows_created=0, skipped=[])

    files_read = 0
    skipped: list[GeneratedImportSkip] = []
    rows: list[NewBankQuestion] = []
    for path in sorted(directory.glob("*.json")):
        files_read += 1
        try:
            quiz = GeneratedQuiz.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, OSError) as exc:
            reason = str(exc)
            skipped.append(GeneratedImportSkip(path=path, reason=reason))
            log.warning("generated_quiz_import_skipped", path=str(path), reason=reason)
            continue
        rows.extend(generated_questions_to_bank_rows(quiz))

    ids = service.add_questions(rows)
    return GeneratedImportResult(files_read=files_read, rows_created=len(ids), skipped=skipped)


# ---------------------------------------------------------------------------
# 4. Past-paper survey (reporting only — see module docstring and D3.7)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PastPaperSurveyReport:
    """Counts from walking every parsed mark scheme's leaf questions.

    **A survey over mark-scheme payloads, not a writer** — see module
    docstring / ``docs/quiz-model.md`` §2 / ``BUILD/DECISIONS.md`` D3.7.
    ``produced`` is always ``0`` here because
    :class:`~lemely.core.loose_schemas.Question` (the mark-scheme model) has
    no question-stem field to read a prompt from; ``skipped_no_prompt``
    therefore equals ``leaf_questions_seen`` in full, not partially. This is
    a property of *this function's input* (mark schemes alone), not a
    statement that past-paper questions cannot be banked at all — P4.1's
    ``lemely.io.question_papers.ingest_question_papers_dir`` banks them from
    question-paper PDFs paired with these same mark schemes instead.
    """

    mark_schemes_scanned: int
    parse_failures: int
    leaf_questions_seen: int
    produced: int
    skipped_no_prompt: int
    topic_hints_present: int
    band_distribution: dict[Band, int]

    def explanation(self) -> str:
        """The §2-worded reason today's yield is what it is, for direct display."""
        if self.produced > 0:
            return (
                f"{self.produced} past-paper question(s) produced from "
                f"{self.mark_schemes_scanned} mark scheme(s)."
            )
        if self.mark_schemes_scanned == 0:
            # Distinct from the structural finding below: having examined
            # nothing, this run observed nothing, and saying otherwise would
            # report a conclusion it did not reach.
            return (
                "0 past-paper questions produced: no parsed mark schemes are "
                "indexed, so nothing was examined. A question-paper stem "
                "extractor now exists (lemely.io.det.question_papers) and "
                "banks real past-paper questions directly from question-paper "
                "PDFs paired with a mark scheme — run `lemely "
                "ingest-question-papers` for that. Indexing mark schemes here "
                "would not change this survey's own count: it only reads "
                "mark-scheme payloads, which never carry stem text."
            )
        return (
            "0 past-paper questions produced: loose_schemas.Question carries "
            "marking points, not question-stem text, so no leaf question in "
            f"{self.mark_schemes_scanned} scanned mark scheme(s) carries the "
            "prompt question_bank.prompt requires. This is structural to "
            "mark-scheme payloads, not a parsing gap — and not a dead end: a "
            "question-paper stem extractor now exists "
            "(lemely.io.det.question_papers) and banks past-paper questions "
            "directly from question-paper PDFs via `lemely "
            "ingest-question-papers`. This survey function only walks "
            "mark-scheme payloads, which never carry stems, so its own yield "
            "stays zero regardless."
        )


def survey_past_paper_questions(sessionmaker: sessionmaker[Session]) -> PastPaperSurveyReport:
    """Report how many bank-ready questions exist in the parsed mark-scheme corpus.

    Walks every ``mark_schemes.parsed_payload`` row, deserialises it as
    :class:`~lemely.core.loose_schemas.MarkScheme`, and flattens it with
    :meth:`~lemely.core.loose_schemas.MarkScheme.all_questions_flat`. A
    question with a non-empty ``parts`` list is a **container** (e.g. "3"
    wrapping "3a"/"3b") and is not counted as a markable leaf question —
    only leaves are, because ``all_questions_flat`` returns every node,
    container and leaf alike, and a container carries no marks of its own to
    infer a difficulty band from.

    This function never writes to ``question_bank`` — see the module and
    :class:`PastPaperSurveyReport` docstrings for why persisting from this
    input is structurally, not incidentally, impossible today. There is
    deliberately no ``if question.prompt is not None:`` branch anywhere in
    this function: ``Question`` has no ``prompt`` attribute to check, so
    such a branch would be dead code guarded by an attribute that does not
    exist, not a real conditional.

    A ``parsed_payload`` that fails to validate as :class:`MarkScheme` is
    counted in :attr:`PastPaperSurveyReport.parse_failures` and skipped —
    one malformed row must not abort the survey of the rest.
    """
    with sessionmaker() as session:
        payloads = session.scalars(select(MarkSchemeRecord.parsed_payload)).all()

    parse_failures = 0
    leaf_questions_seen = 0
    topic_hints_present = 0
    band_distribution: dict[Band, int] = {"foundation": 0, "standard": 0, "challenge": 0}

    for payload in payloads:
        try:
            parsed = ParsedMarkScheme.model_validate(payload)
        except ValidationError as exc:
            parse_failures += 1
            log.warning("past_paper_survey_parse_failed", error=str(exc))
            continue
        for question in parsed.all_questions_flat():
            if question.parts:
                continue  # container, not a markable leaf question
            leaf_questions_seen += 1
            if question.topic_hint:
                topic_hints_present += 1
            band_distribution[infer_difficulty(question.marks, question.type.value)] += 1

    return PastPaperSurveyReport(
        mark_schemes_scanned=len(payloads) - parse_failures,
        parse_failures=parse_failures,
        leaf_questions_seen=leaf_questions_seen,
        # Question (lemely.core.loose_schemas) has no question-stem field at
        # all (D3.7) — there is no attribute to check, so every leaf counted
        # above is structurally unproduceable. This 0 is what the schema
        # guarantees, not a placeholder computed by a dead conditional.
        produced=0,
        skipped_no_prompt=leaf_questions_seen,
        topic_hints_present=topic_hints_present,
        band_distribution=band_distribution,
    )


# ---------------------------------------------------------------------------
# 5. Topic classification (P4.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TopicClassificationReport:
    """Outcome of one ``classify-topics`` run, for the CLI and the phase report.

    Every counter is a real observation of this run. ``skipped_low_confidence``
    is deliberately its own bucket rather than being folded into
    ``unclassified``: they are different failures. An unclassified question had
    too little distinctive vocabulary to place at all; a low-confidence one was
    placed, but not well enough to write (``lemely.core.topics.WRITABLE_BANDS``).
    Collapsing them would hide the size of the band this policy is discarding,
    which is exactly the number a future ``topic_confidence`` column would
    reclaim.
    """

    rows_examined: int
    already_classified: int
    assigned: int
    skipped_low_confidence: int
    unclassified: int
    no_taxonomy: int
    band_distribution: dict[str, int] = field(default_factory=dict)
    label_distribution: dict[str, int] = field(default_factory=dict)

    @property
    def coverage(self) -> float:
        """Share of examined rows now carrying a topic, 0.0 when none examined."""
        if self.rows_examined == 0:
            return 0.0
        return (self.assigned + self.already_classified) / self.rows_examined


def classification_text(row: QuestionBank) -> str:
    """Everything known about a bank row that carries topic signal.

    The MCQ options matter and are not optional decoration: measured on the
    real 0625 bank, including them moved coverage from 78.8% to 89.4%. An MCQ
    stem is deliberately terse ("Which planet is classed as a rocky planet?")
    and the discriminating vocabulary often lives entirely in the four options.
    They are part of the question, so they are part of what gets classified.
    """
    parts: list[str] = [row.prompt or ""]
    if row.model_answer:
        parts.append(row.model_answer)
    parts.extend(str(option) for option in (row.mcq_options or []))
    for point in row.mark_scheme_points or []:
        if isinstance(point, dict):
            parts.extend(str(v) for v in point.values() if isinstance(v, str))
        else:
            parts.append(str(point))
    return "\n".join(p for p in parts if p)


def classify_bank_topics(
    sessionmaker: sessionmaker[Session],
    *,
    subject_code: str | None = None,
    reclassify: bool = False,
    dry_run: bool = False,
) -> TopicClassificationReport:
    """Backfill ``question_bank.topic`` from the bundled syllabus taxonomies.

    Idempotent by default: a row that already carries a topic is counted in
    ``already_classified`` and left alone, so re-running after a corpus
    expansion only touches new rows. ``reclassify=True`` re-derives every row,
    which is what to use after editing the taxonomy vocabulary.

    ``dry_run=True`` computes the identical report without writing — the
    intended way to see what a vocabulary change would do before committing to
    it.

    Rows whose subject has no bundled taxonomy are counted in ``no_taxonomy``
    and skipped rather than forced against another subject's tree.
    """
    report_bands: dict[str, int] = {}
    report_labels: dict[str, int] = {}
    examined = already = assigned = low_conf = unclassified = no_taxonomy = 0

    with sessionmaker() as session:
        statement = select(QuestionBank)
        if subject_code is not None:
            statement = statement.where(QuestionBank.subject_code == subject_code)
        rows = session.scalars(statement).all()

        for row in rows:
            examined += 1
            if row.topic and not reclassify:
                already += 1
                continue
            taxonomy = get_taxonomy(row.subject_code, board=row.board.value)
            if taxonomy is None:
                no_taxonomy += 1
                continue
            match = classify(classification_text(row), taxonomy)
            if match is None:
                unclassified += 1
                if reclassify:
                    row.topic = None
                continue
            if not is_writable(match):
                low_conf += 1
                if reclassify:
                    # A reclassify pass must be able to *remove* a label the
                    # previous vocabulary asserted and this one no longer
                    # supports. Leaving it would make the taxonomy edit look
                    # like it only ever adds.
                    row.topic = None
                continue
            row.topic = match.label
            assigned += 1
            band = match.confidence.value
            report_bands[band] = report_bands.get(band, 0) + 1
            report_labels[match.label] = report_labels.get(match.label, 0) + 1

        if dry_run:
            session.rollback()
        else:
            session.commit()

    return TopicClassificationReport(
        rows_examined=examined,
        already_classified=already,
        assigned=assigned,
        skipped_low_confidence=low_conf,
        unclassified=unclassified,
        no_taxonomy=no_taxonomy,
        band_distribution=report_bands,
        label_distribution=report_labels,
    )


__all__ = [
    "GeneratedImportResult",
    "GeneratedImportSkip",
    "NewBankQuestion",
    "PastPaperSurveyReport",
    "QuestionBankRow",
    "QuestionBankService",
    "TopicClassificationReport",
    "classification_text",
    "classify_bank_topics",
    "generated_questions_to_bank_rows",
    "import_generated_quiz_files",
    "survey_past_paper_questions",
    "visible_bank_filter",
]
