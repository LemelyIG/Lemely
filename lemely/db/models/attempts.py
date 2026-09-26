"""ORM models for uploads, attempts, question results, and weakness records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    # Type-check only: `ops` maps `ReviewQueueItem.question_result` back onto
    # this module's `QuestionResult`, so a runtime import here would be a cycle.
    # SQLAlchemy resolves the relationship from its own class registry (the
    # `"ReviewQueueItem"` string below), not from this name.
    from lemely.db.models.ops import ReviewQueueItem


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

    attempts: Mapped[list[Attempt]] = relationship("Attempt", back_populates="upload")


class Attempt(TimestampMixin, Base):
    """A marked attempt at a specific exam paper by a student."""

    __tablename__ = "attempts"
    __table_args__ = (
        sa.Index("ix_attempts_user_id_recorded_at", "user_id", "recorded_at"),
        sa.Index("ix_attempts_user_id_origin", "user_id", "origin"),
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
    __table_args__ = (
        sa.Index("ix_question_results_attempt_id", "attempt_id"),
        # Mirrors migration `0042_question_result_source_box`'s four CHECK
        # constraints. Names are UNPREFIXED for the same reason as there:
        # `Base.metadata`'s naming convention (`ck_%(table_name)s_%(constraint_name)s`)
        # treats a `name=` you pass as the `constraint_name` token, so a name that
        # already starts with `ck_question_results_` comes out doubled. Passing
        # the bare suffix here lets the convention apply once, producing the
        # same names `0042` creates -- so a `create_all()` schema (tests only;
        # production always runs `alembic upgrade head`) carries the identical
        # constraints instead of silently omitting them.
        sa.CheckConstraint(
            "source_box_page IS NULL OR source_box_page >= 0",
            name="source_box_page_non_negative",
        ),
        sa.CheckConstraint(
            "(source_box_ymin IS NULL OR (source_box_ymin >= 0 AND source_box_ymin <= 1000)) "
            "AND (source_box_xmin IS NULL OR (source_box_xmin >= 0 AND source_box_xmin <= 1000)) "
            "AND (source_box_ymax IS NULL OR (source_box_ymax >= 0 AND source_box_ymax <= 1000)) "
            "AND (source_box_xmax IS NULL OR (source_box_xmax >= 0 AND source_box_xmax <= 1000))",
            name="source_box_range",
        ),
        # The leading `IS NULL` guards must stand alone: this constraint may
        # not assume `source_box_all_or_none` holds, and vice versa.
        sa.CheckConstraint(
            "source_box_ymax IS NULL OR source_box_xmax IS NULL "
            "OR (source_box_ymax > source_box_ymin AND source_box_xmax > source_box_xmin)",
            name="source_box_positive_area",
        ),
        sa.CheckConstraint(
            "(source_box_page IS NULL AND source_box_ymin IS NULL AND source_box_xmin IS NULL "
            "AND source_box_ymax IS NULL AND source_box_xmax IS NULL) "
            "OR (source_box_page IS NOT NULL AND source_box_ymin IS NOT NULL "
            "AND source_box_xmin IS NOT NULL AND source_box_ymax IS NOT NULL "
            "AND source_box_xmax IS NOT NULL)",
            name="source_box_all_or_none",
        ),
    )

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
    rationale: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source_box_page: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    """0-based rasterised-page index for `source_box_*` (migration `0042`).

    Question-level, not per mark point: marking is text-only, so the marker
    never sees the page. See `CorrectedQuestion.source_box`. All five
    `source_box_*` columns are all-or-nothing, enforced by
    `ck_question_results_source_box_all_or_none`.
    """
    source_box_ymin: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    source_box_xmin: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    source_box_ymax: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    source_box_xmax: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    student_selfmark_marks: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    student_selfmarked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """Written by the student self-review spec. Created here per its D5."""

    attempt: Mapped[Attempt] = relationship("Attempt", back_populates="question_results")
    review_queue_items: Mapped[list[ReviewQueueItem]] = relationship(
        "ReviewQueueItem", back_populates="question_result"
    )
    """The queue rows this question earned, and the ONLY persisted record of its
    integrity findings.

    The annotation was a bare ``Mapped[list]`` until task #36 made this the
    first reader. SQLAlchemy cannot see a collection in ``list`` with no
    element type, so it configured the relationship ``uselist=False`` — a
    ONETOMANY mapped as a scalar, returning ``None`` on a transient instance
    and a single row on a loaded one. Nothing read it, so nothing failed; the
    element type makes it the collection it was always declared to be.

    There is deliberately no ``plagiarism_flagged`` column (nor its
    ``ai_detection_flagged`` twin). ``0037_question_result_pts`` — develop's
    revision, written before F4 deleted the detector — added both;
    ``0039_merge_heads`` dropped the detector's and
    ``0040_marker_source_blank`` dropped this one, per the task #36 ruling: the
    plagiarism signal is dead end to end and a new persisted column on a signal
    nothing produces is the wrong direction. ``review_reasons_for`` opens a
    ``ReviewReason.plagiarism_flag`` row here from
    ``CorrectedQuestion.plagiarism_flagged`` (which still exists, in memory, in
    core), so the row IS the flag —
    ``attempt_repo._integrity_flagged`` is the one reader.
    """
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
    """The marker's own reasoning for this point, from whichever path scored

    it. Deliberately ONE column for two producers rather than a second
    ``note`` column beside it: I6's verdict path (``PointVerdict.note``) and
    the legacy path (``CorrectedQuestion.point_notes``) both describe "did a
    marker score this and why", and a second formulation would be the ninth
    version of that idea -- the exact defect ``0040_marker_source_blank``'s
    docstring describes curing for ``marker_source``, where eight
    formulations cost nine hand-found consumers. See
    :func:`lemely.db.question_points.derive_point_rows` for which producer
    wins when both are present.
    """
    verdict: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """I6 (US-013): the marker's own judgement on this point --

    ``"awarded"``, ``"withheld"`` or ``"unverifiable"`` (``PointVerdict``'s
    ``Literal``, stored loosely since this table predates a native enum for
    it and a fourth verdict must not require a migration). ``NULL`` when this
    point was scored by the legacy (non-verdict) path, which has no such
    distinction to record.

    ``awarded`` (above) is NOT re-derived from this column and keeps its own
    live consumers (``SelfReviewPoints``, ``points_are_settleable``,
    ``_settle_groups``); ``verdict`` is strictly richer beside it. A
    repeated ``point_id`` in the marker's own ``point_verdicts`` output used
    to make ``awarded`` and ``verdict`` disagree for that point --
    ``lemely.io.correction_ai._awarded_from_verdicts`` summed every awarded
    entry (inflating marks) while ``lemely.db.question_points.derive_point_rows``
    kept the LAST entry, so an awarded-then-withheld pair could persist
    ``awarded=True`` beside ``verdict="withheld"``. That specific
    disagreement is now closed structurally: both consumers dedupe the same
    list via the one shared ``lemely.core.schemas.dedupe_point_verdicts``
    helper (deterministic first-occurrence-wins), so they can no longer
    resolve a repeat differently -- see ``tests/test_question_points.py``.
    A repeat is also, in its own right, a structural inconsistency in the
    marker's raw output: on the verdict path,
    ``lemely.io.correction_ai._check_coherence`` flags it as a coherence
    violation, which routes the question to teacher review rather than
    reconciling it silently -- see ``tests/test_correction_ai.py``. This
    closes only the duplicate-``point_id`` case: ``awarded`` can still
    diverge from ``verdict`` when ``_verify_calculated_answers`` rejects a
    point's mark after its verdict was formed (the point's raw ``"awarded"``
    verdict is not revised), a separate gap this fix does not touch.
    ``verdict`` is what tells a teacher, that could not tell from
    ``awarded`` alone, that the marker judged the point absent
    (``withheld``) rather than unable to verify it (``unverifiable``) --
    both of which collapse to ``awarded=False``.
    """
    evidence_span: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("''")
    )
    """The verbatim substring of the student's answer/working the marker

    quoted as evidence for this point's verdict (``PointVerdict.evidence_span``).
    ``''`` (not ``NULL``) when this point carries no verdict, matching
    ``PointVerdict``'s own default so an absent verdict and an empty quote are
    not distinguished at this column either.
    """
    ecf_applied: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )
    """I7 (US-013): True when this point's verdict was reached only after

    re-marking with a substituted prior value (error carried forward) --
    mirrors ``PointVerdict.ecf_applied``. ``False`` for a legacy-path point,
    which never re-marks against a substituted prior.
    """
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
