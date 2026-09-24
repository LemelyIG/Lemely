"""ORM models for uploads, attempts, question results, and weakness records."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import (
    AttemptOrigin,
    BoundarySource,
    ConfidenceBand,
    EvidenceVerdict,
    MarkerSource,
    RevisionSource,
    SessionMonth,
    TimestampMixin,
    UploadStatus,
)


class Upload(TimestampMixin, Base):
    """A student's raw scan/upload stored in object storage.

    The deployed backend is Google Cloud Storage
    (:mod:`lemely.io.storage_gcs`); dev and CI use the local filesystem
    backend behind the same seam. The public "How Lemely handles your data"
    page cites this model for what an upload row keeps, so a change to that
    list is a change to a disclosure — see :mod:`lemely.io.storage`.
    """

    __tablename__ = "uploads"
    __table_args__ = (
        # Enforces the Idempotency-Key dedupe (migration 0036); see
        # StudentUploadRepository.create_upload for the race it closes.
        sa.Index(
            "ux_uploads_user_idempotency",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    storage_path: Mapped[str] = mapped_column(sa.String, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    content_type: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    status: Mapped[UploadStatus] = mapped_column(
        sa.Enum(UploadStatus, name="uploadstatus"),
        nullable=False,
        server_default=sa.text("'pending'::uploadstatus"),
    )
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    """When the student deleted this row; NULL means live (design 2026-09-22 §3).

    **Readers do not filter on this themselves.** A session-level loader
    criterion registered in :mod:`lemely.db.session` excludes deleted rows from
    every ORM select, so a query that does not opt in with
    ``execution_options(include_deleted=True)`` never sees one. Adding a
    belt-and-braces ``WHERE`` at a call site is actively harmful: it makes that
    site's tests pass even when the criterion is dead.
    """

    attempts: Mapped[list[Attempt]] = relationship("Attempt", back_populates="upload")


class Attempt(TimestampMixin, Base):
    """A marked attempt at a specific exam paper by a student."""

    __tablename__ = "attempts"
    __table_args__ = (
        sa.Index("ix_attempts_user_id_recorded_at", "user_id", "recorded_at"),
        sa.Index("ix_attempts_user_id_origin", "user_id", "origin"),
        # Migration 0039's purge-candidate and recently-deleted queries: both
        # look only at the small deleted minority, so a partial index avoids
        # indexing every live row's NULL.
        sa.Index(
            "ix_attempts_deleted_at",
            "deleted_at",
            postgresql_where=sa.text("deleted_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("uploads.id"),
        nullable=True,
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("papers.id"),
        nullable=True,
    )
    subject_code: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    session_month: Mapped[SessionMonth | None] = mapped_column(
        sa.Enum(SessionMonth, name="sessionmonth"),
        nullable=True,
    )
    session_year: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    paper_number: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    paper_variant: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    awarded_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    maximum_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    percentage: Mapped[float] = mapped_column(sa.Float, nullable=False)
    grade: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    predicted_grade: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    boundary_source: Mapped[BoundarySource | None] = mapped_column(
        sa.Enum(BoundarySource, name="boundarysource"),
        nullable=True,
    )
    confidence_band: Mapped[ConfidenceBand | None] = mapped_column(
        sa.Enum(ConfidenceBand, name="confidenceband"),
        nullable=True,
    )
    needs_teacher_review: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    recorded_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    origin: Mapped[AttemptOrigin] = mapped_column(
        sa.Enum(AttemptOrigin, name="attemptorigin"),
        nullable=False,
        server_default=sa.text("'past_paper'::attemptorigin"),
    )
    """What kind of assessment produced this attempt (P3.5, migration
    ``0007_quiz_model``). Every pre-existing row is a past-paper attempt, so
    the default needs no backfill. For ``origin = quiz``, ``grade``,
    ``predicted_grade``, ``boundary_source``, ``paper_id``, ``paper_number``,
    ``paper_variant``, ``session_month`` and ``session_year`` are all NULL —
    a ten-question quiz has no grade boundaries, and giving it one would
    invent precision and silently corrupt every grade-bearing consumer of
    student history (``docs/quiz-model.md`` §1.2). This column is schema
    only in chunk A; nothing here yet reads it (chunk G wires it up).
    """
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    """When the student deleted this row; NULL means live (design 2026-09-22 §3).

    **Readers do not filter on this themselves.** A session-level loader
    criterion registered in :mod:`lemely.db.session` excludes deleted rows from
    every ORM select, so a query that does not opt in with
    ``execution_options(include_deleted=True)`` never sees one. Adding a
    belt-and-braces ``WHERE`` at a call site is actively harmful: it makes that
    site's tests pass even when the criterion is dead.
    """

    upload: Mapped[Upload | None] = relationship("Upload", back_populates="attempts")
    question_results: Mapped[list[QuestionResult]] = relationship(
        "QuestionResult", back_populates="attempt", cascade="all, delete-orphan"
    )
    weakness_records: Mapped[list[WeaknessRecord]] = relationship(
        "WeaknessRecord", back_populates="attempt"
    )


class QuestionResult(TimestampMixin, Base):
    """Per-question marking outcome within an :class:`Attempt`.

    ``teacher_awarded_marks``/``teacher_note``/``teacher_breakdown``/
    ``overridden_by``/``overridden_at`` are P3.4's teacher-override columns
    (migration ``0005_review_overrides``). They are additive and all
    nullable: ``awarded_marks`` (the AI's mark) is never mutated or erased by
    an override — "the teacher has final authority" (UI-spec §1.4) means the
    teacher's mark wins on every read, not that the machine's mark is
    destroyed. It stays queryable for accuracy measurement (MISSION §4:
    "overrides feed back as recorded corrections") and so a teacher can always
    see what Lemely originally produced. See :attr:`effective_marks`.
    """

    __tablename__ = "question_results"
    __table_args__ = (sa.Index("ix_question_results_attempt_id", "attempt_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[str] = mapped_column(sa.String, nullable=False)
    awarded_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    maximum_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    confidence_band: Mapped[ConfidenceBand] = mapped_column(
        sa.Enum(ConfidenceBand, name="confidenceband"),
        nullable=False,
    )
    confidence_score: Mapped[float] = mapped_column(sa.Float, nullable=False)
    needs_teacher_review: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    marker_source: Mapped[MarkerSource] = mapped_column(
        sa.Enum(MarkerSource, name="markersource"),
        nullable=False,
    )
    topic: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    student_answer: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    expected_answer: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    review_reason: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    feedback: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    matched_point_ids: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    teacher_awarded_marks: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    teacher_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    teacher_breakdown: Mapped[dict | None] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=True
    )
    """Teacher-supplied method/accuracy breakdown for an override, verbatim.

    Deliberately NOT computed: a mark scheme's M/A/B point types
    (``lemely.core.loose_schemas.MathMarkType``) live in the parsed mark
    scheme, not on this row — only ``matched_point_ids`` (bare point ids) is
    persisted here, with no join back to per-point mark types. There is
    nothing here honest to derive a breakdown from (UI-spec §1.4: never invent
    precision), so this column stores exactly what the teacher typed — free-form
    keys the API layer validates loosely (e.g. ``methodMarks``/``accuracyMarks``),
    nothing more.
    """
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=True,
    )
    overridden_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    extraction_confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    """Extraction-stage confidence, distinct from ``confidence_score``.

    Computed by the pipeline (``CorrectedQuestion.extraction_confidence``) and,
    before spec 2026-09-17, discarded at persist time.
    """
    plagiarism_flagged: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )
    ai_detection_flagged: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )
    """Integrity flags, persisted rather than only fanned out to the review queue.

    Teacher-only on every surface (QUALITY-BAR.md): these must never be
    rendered on a student-facing screen, where they would read as an
    accusation. They are, however, present in the ``/api/student/correct``
    complete frame (``lemely/web/schemas.py``) and typed on the frontend
    (``web/src/lib/studentTypes.ts``) — the UI simply does not render them.
    """
    rationale: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    student_selfmark_marks: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    student_selfmarked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """Written by the student self-review spec. Created here per its D5."""

    attempt: Mapped[Attempt] = relationship("Attempt", back_populates="question_results")
    review_queue_items: Mapped[list] = relationship(  # type: ignore[type-arg]
        "ReviewQueueItem", back_populates="question_result"
    )
    points: Mapped[list[QuestionResultPoint]] = relationship(
        "QuestionResultPoint",
        back_populates="question_result",
        cascade="all, delete-orphan",
        order_by="QuestionResultPoint.ordinal",
    )
    revisions: Mapped[list[QuestionResultRevision]] = relationship(
        "QuestionResultRevision",
        back_populates="question_result",
        cascade="all, delete-orphan",
        order_by="QuestionResultRevision.revision",
    )

    @property
    def effective_marks(self) -> int:
        """The mark that must reach every student-facing surface.

        Precedence: the teacher's override, else the student's self-mark, else
        the AI's ``awarded_marks`` unchanged. **The single accessor** — anything
        (a route, a DTO converter, a report) that needs "this question's mark"
        reads this, never ``awarded_marks`` directly, so a correction can never
        be shown on one screen and silently missing on another (P3.4).

        The student tier (spec 2026-09-17 self-review, D5) is an accepted
        trade-off, not an oversight: self-reported marks reach teacher class
        analytics (``quiz_results_repo``), placement (``placement_repo``) and
        the student's own grade. The alternative — a second accessor for
        teacher-facing surfaces — was rejected as two numbers for one question.
        ``student_selfmark_marks`` is only ever set where the marker was
        low-confidence or a lenient judge accepted the student's evidence;
        a self-mark that moved marks *down* (D6) is honoured on the same terms.
        """
        if self.teacher_awarded_marks is not None:
            return self.teacher_awarded_marks
        if self.student_selfmark_marks is not None:
            return self.student_selfmark_marks
        return self.awarded_marks

    @property
    def is_self_marked(self) -> bool:
        """Whether the student has completed their one self-review pass.

        Reads the timestamp, not the marks: a pass that agreed with the marker
        on every point sets ``student_selfmarked_at`` and leaves
        ``student_selfmark_marks`` NULL, and it still counts as the pass.
        """
        return self.student_selfmarked_at is not None

    @property
    def is_overridden(self) -> bool:
        """Whether a teacher has recorded a correction for this question."""
        return self.teacher_awarded_marks is not None


class QuestionResultPoint(TimestampMixin, Base):
    """One mark point of one marked question.

    Derived at attempt-write time from the parsed mark scheme
    (:func:`lemely.db.question_points.derive_point_rows`). ``tariff``,
    ``point_text`` and ``mark_type`` are **snapshotted**, not joined live: mark
    schemes get re-parsed and corrected, and a student's marked paper must not
    change meaning underneath them months later (spec 2026-09-17 D3).

    ``mark_type`` is text, not an enum. ``MathMarkType`` has fifteen members
    and a narrower DB enum would silently drop most of them.

    Not re-derived on a teacher override: :meth:`ReviewRepository.resolve`
    (``lemely/db/review_repo.py``) sets ``QuestionResult.teacher_awarded_marks``
    directly and never touches this table. After an override,
    ``QuestionResult.effective_marks`` returns the teacher's mark while every
    row here (``awarded``, and the sum of ``tariff`` where ``awarded``) still
    describes the AI's original marking. A reader that wants "why this many
    marks" must check ``is_overridden`` first.
    """

    __tablename__ = "question_result_points"
    __table_args__ = (
        sa.UniqueConstraint(
            "question_result_id", "mark_point_id", name="uq_question_result_points_point"
        ),
        sa.Index("ix_question_result_points_question_result_id", "question_result_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    question_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("question_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    mark_point_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    mark_type: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    tariff: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    tariff_defaulted: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )
    """True when ``tariff`` was minted (``AnswerPoint.marks_defaulted``), not read

    from the source — the marks cell was absent or unparseable. Provenance
    only: without this, a minted tariff and one CAIE actually printed are
    indistinguishable on this row (spec 2026-09-17 fix).
    """
    point_text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    awarded: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    is_alternative: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )
    is_optional: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )
    """``is_alternative``/``is_optional`` (from ``AnswerPoint``) mark a point as

    part of a non-additive OR/optional group (``correction_ai._check_coherence``):
    summing every ``awarded`` point's ``tariff`` on this table does NOT
    generally equal ``QuestionResult.awarded_marks`` when either flag is set on
    a matched point, because the mark scheme allows at most the group's own
    cap, not the sum of its members. A consumer that sums ticked tariffs
    without checking these flags will show a breakdown that disagrees with the
    student's own mark.
    """

    group_key: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """The scheme group this point belongs to; see ``group_max_marks`` below,
    which documents the pair."""
    group_max_marks: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    """``group_key``/``group_max_marks``: the scheme group this point belongs

    to, recorded at derivation time
    (:func:`lemely.db.question_points.derive_point_rows`): ``alt:n`` for an
    either/or run, ``pool:n`` for an "any N from" pool, ``NULL`` for an
    independent point. ``group_max_marks`` is the most the whole group can
    contribute. ``is_alternative`` alone cannot say where a group starts or
    ends (it means "alternative to the previous point"), which is why the
    group is stored rather than re-derived — the self-review write path caps
    granted marks at ``group_max_marks`` (self-review spec, D6), and the panel
    renders the group as one unit. Rows written before migration
    ``0038_point_group_key`` keep ``NULL`` (no backfill, spec 1 D7).
    """
    rationale: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    student_selfmark: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    student_selfmark_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    student_evidence: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    evidence_verdict: Mapped[EvidenceVerdict | None] = mapped_column(
        sa.Enum(EvidenceVerdict, name="evidenceverdict"), nullable=True
    )

    question_result: Mapped[QuestionResult] = relationship(
        "QuestionResult", back_populates="points"
    )


class QuestionResultRevision(TimestampMixin, Base):
    """One recorded state of a question's marks. Append-only.

    Revision 1 is written at correction time with ``source=ai``. The existing
    ``question_results`` row stays the current projection, so no read surface
    has to change to keep working (spec 2026-09-17 D4).
    """

    __tablename__ = "question_result_revisions"
    __table_args__ = (
        sa.UniqueConstraint(
            "question_result_id", "revision", name="uq_question_result_revisions_revision"
        ),
        sa.Index("ix_question_result_revisions_question_result_id", "question_result_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    question_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("question_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    source: Mapped[RevisionSource] = mapped_column(
        sa.Enum(RevisionSource, name="revisionsource"), nullable=False
    )
    awarded_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    points_snapshot: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    question_result: Mapped[QuestionResult] = relationship(
        "QuestionResult", back_populates="revisions"
    )


class WeaknessRecord(TimestampMixin, Base):
    """Aggregated topic-level weakness for a user, optionally tied to an attempt."""

    __tablename__ = "weakness_records"
    __table_args__ = (sa.Index("ix_weakness_records_user_id_topic", "user_id", "topic"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=True,
    )
    topic: Mapped[str] = mapped_column(sa.String, nullable=False)
    lost_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    maximum_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    accuracy: Mapped[float] = mapped_column(sa.Float, nullable=False)
    question_ids: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )

    attempt: Mapped[Attempt | None] = relationship("Attempt", back_populates="weakness_records")


__all__ = [
    "Attempt",
    "QuestionResult",
    "QuestionResultPoint",
    "QuestionResultRevision",
    "Upload",
    "WeaknessRecord",
]
