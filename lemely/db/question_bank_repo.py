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
4. :func:`survey_past_paper_questions` — **a reporting function, not a
   writer**. ``BUILD/DECISIONS.md`` D3.7 records the measurement: across the
   entire parsed corpus, 0 of 122 leaf questions carry prompt text, because
   :class:`~lemely.core.loose_schemas.Question` has no question-stem field
   at all — a CAIE mark scheme contains marking points, not the question
   text (the stem lives in the question paper, which this codebase never
   parses into structure). Since ``question_bank.prompt`` is ``NOT NULL``,
   there is no row to construct from a mark scheme today, and there never
   will be until a question-paper stem extractor exists (out of Phase-3
   scope). Persisting is therefore not merely deferred here; it is
   structurally impossible from this input, so this function only counts
   and reports — it does not gate a persist branch on a field the source
   schema does not have.
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
from lemely.db.models.academic import MarkScheme as MarkSchemeRecord
from lemely.db.models.enums import DifficultySource, ExamBoard, QuestionDifficulty, QuestionSource
from lemely.db.models.quizzes import QuestionBank

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

    **A survey, not a writer** — see module docstring / ``docs/quiz-model.md``
    §2 / ``BUILD/DECISIONS.md`` D3.7. ``produced`` is always ``0`` against
    today's corpus because :class:`~lemely.core.loose_schemas.Question` has
    no question-stem field to read a prompt from; ``skipped_no_prompt``
    therefore equals ``leaf_questions_seen`` in full, not partially.
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
            # report a conclusion it did not reach. The structural blocker is
            # still named, as the standing reason no writer exists — but as
            # prior knowledge (D3.7), not as this scan's result.
            return (
                "0 past-paper questions produced: no parsed mark schemes are "
                "indexed, so nothing was examined. Independently of that, "
                "persisting past-paper questions is blocked on a "
                "question-paper stem extractor that does not exist yet "
                "(BUILD/DECISIONS.md D3.7) — indexing mark schemes alone "
                "would not change this count. Use generated questions instead."
            )
        return (
            "0 past-paper questions produced: loose_schemas.Question carries "
            "marking points, not question-stem text, so no leaf question in "
            f"{self.mark_schemes_scanned} scanned mark scheme(s) carries the "
            "prompt question_bank.prompt requires. This is structural "
            "(BUILD/DECISIONS.md D3.7), not a parsing gap — persisting "
            "past-paper questions needs a question-paper stem extractor, "
            "which does not exist yet. Use generated questions instead."
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


__all__ = [
    "GeneratedImportResult",
    "GeneratedImportSkip",
    "NewBankQuestion",
    "PastPaperSurveyReport",
    "QuestionBankRow",
    "QuestionBankService",
    "generated_questions_to_bank_rows",
    "import_generated_quiz_files",
    "survey_past_paper_questions",
    "visible_bank_filter",
]
