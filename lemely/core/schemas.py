from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

# F1 (Gemini 3.x migration): 3.x models reject the JSON-Schema `pattern`
# keyword outright (brief #15/B7), so the subject_code shape check that used
# to live in `Field(pattern=...)` — and therefore in the schema Gemini's
# structured-output call sends — moves to a plain Pydantic validator, which
# enforces the same shape without emitting a `pattern` keyword anywhere in
# `model_json_schema()`. See lemely.core.loose_schemas.MarkSchemeMetadata and
# lemely.core.question_papers.QuestionPaperMetadata for the other two sites.
#
# F1 review FIX 7 (2026-09-17): the regex itself is defined in
# lemely.core.loose_schemas, not here, and re-exported by this import.
# loose_schemas is the LOWER module in the import-linter layering — it
# imports nothing from lemely — while lemely.labelling (which is
# contract-forbidden from depending on this module, the correction
# pipeline's schemas) already imports loose_schemas directly. Defining the
# constant here and importing it into loose_schemas (the shape this module
# shipped with originally) made loose_schemas transitively depend on
# schemas.py and broke that contract; importing it the other way round does
# not, since question_papers.py already imports StrictModel from here with
# no cycle either way.
from lemely.core.loose_schemas import _SUBJECT_CODE_RE as _SUBJECT_CODE_RE


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def confidence_band_for_score(score: float) -> ConfidenceBand:
    if score >= 0.90:
        return ConfidenceBand.HIGH
    if score >= 0.70:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


# The ONE review threshold (D2.2). A marked question is auto-graded only when its
# marker confidence is at or above this value; below it the question is flagged
# (``CorrectedQuestion.needs_teacher_review``) and routed to the human review
# queue on persist (``lemely.db.attempt_repo``) and in the teacher console.
#
# Deliberately a module constant, not a ``lemely.toml`` field: it is a calibrated
# accuracy-gate invariant that must be identical in the marking layer (io), the
# persistence layer (db) and the web layer, none of which share a Settings
# injection path — and a per-machine TOML override would silently invalidate the
# accuracy-harness numbers that justify it. Promoting it to config later is
# additive. Distinct from ``GeminiSettings.escalation_confidence_threshold``
# (0.80), which decides whether to spend more budget re-marking BEFORE a mark is
# final; this one decides whether a FINAL mark may reach a student unreviewed.
#
# Value: 0.90, coinciding with the ``ConfidenceBand.HIGH`` cut-off above, so the
# invariant reads "only HIGH-confidence marks are auto-graded". Provisional —
# calibrated on 0625 Physics only (n=29, 2026-08-04 batch); see BUILD/DECISIONS.md
# D2.2 for the step-function evidence and the mandatory revisit once 0580/0606
# golden fixtures exist.
REVIEW_CONFIDENCE_THRESHOLD = 0.90


#: The ONE statement of "no marker ever formed an opinion about this question",
#: as a set of ``CorrectedQuestion.marker_source`` values. Read it through
#: :func:`marker_scored`, never by re-spelling the membership test.
#:
#: Before this existed the same question was asked eight different ways across
#: the tree, three of them genuinely different -- ``not in ("missing",
#: "dropped")`` in five places, ``!= "missing"`` in one (which counted a
#: dropped answer as marked), and a ``review_reason`` substring match for the
#: US-039 blank in a ninth. That happened because US-039 made a blank an
#: UNFLAGGED zero without giving it a value of its own: ``confidence_score =
#: 0.0`` stopped meaning "the marker looked and was unsure" and started also
#: meaning "nothing looked", with no change to its representation, so every
#: consumer that read it the old way silently changed behaviour on unchanged
#: input. Nine consumers had to be found by hand, in three waves; the last was
#: a grading-AUTHORITY gate (``attempt_repo.is_marking_low_confidence``).
#:
#: ``"blank"`` is the member that closes it (migration
#: ``0040_marker_source_blank``, following US-038's ``0038_marker_source_dropped``
#: precedent): a genuine student blank is now a value, so the blank exemption is
#: a column comparison instead of prose parsing, and widening the set is the one
#: edit a tenth consumer needs.
UNSCORED_MARKER_SOURCES: Final[frozenset[str]] = frozenset({"missing", "dropped", "blank"})

#: The full ``marker_source`` vocabulary, as a named type.
#:
#: Named so a caller can annotate against it instead of writing ``str``. That is
#: not cosmetic: the pydantic mypy plugin checks a ``BaseModel(...)`` call's
#: keyword arity but NOT each value against its field's declared type, so mypy
#: silently accepts ``str`` where this ``Literal`` is declared and only pyright
#: catches it. A helper that types its parameter ``str`` and forwards it into
#: :class:`CorrectedQuestion` is therefore an unchecked hole, and a test helper
#: is where one hides longest.
#:
#: :data:`UNSCORED_MARKER_SOURCES` is the subset of these values meaning "no
#: marker formed an opinion" — see :func:`marker_scored`. The two are kept
#: adjacent deliberately: widening one without the other is the mistake.
MarkerSourceValue = Literal["deterministic", "ai", "missing", "dropped", "blank"]


def marker_scored(marker_source: str) -> bool:
    """Did a marker (deterministic or AI) actually form an opinion about this question?

    The single formulation. ``False`` for every ``marker_source`` in
    :data:`UNSCORED_MARKER_SOURCES`: nothing was attempted (``"missing"``), the
    model answered and extraction discarded it (``"dropped"``), or the student
    left the question empty and no call was made (``"blank"``).

    A ``False`` question's ``confidence_score`` and ``confidence`` band are
    placeholders, not signals -- they must not enter a confidence minimum, a
    calibration bucket, a "needs a human look" count, or a student-facing
    confidence tier. The frontend mirror is ``markerScored`` in
    ``web/src/lib/markingConfidence.ts``, pinned against this set by
    ``tests/test_web_shared_constants.py``.

    Takes the raw string rather than a record so the one function serves both
    spellings: the ``Literal`` on :class:`CorrectedQuestion` and
    ``lemely.db.models.enums.MarkerSource``'s ``.value``.
    """
    return marker_source not in UNSCORED_MARKER_SOURCES


class ExamMetadata(StrictModel):
    subject_code: str = Field(...)
    paper_number: int = Field(..., ge=1, le=9)
    paper_variant: int = Field(..., ge=1, le=9)
    session_month: Literal["May/June", "Oct/Nov", "Feb/Mar", "Specimen"]
    session_year: int | None = Field(default=None, ge=2000, le=2100)
    source_document: str | None = None

    @field_validator("subject_code")
    @classmethod
    def validate_subject_code(cls, v: str) -> str:
        if not _SUBJECT_CODE_RE.fullmatch(v):
            raise ValueError(f"subject_code must be a four-digit CAIE syllabus code, got {v!r}.")
        return v


class SourceLibraryEntry(StrictModel):
    source_path: Path
    metadata: ExamMetadata


class BatchParseItem(StrictModel):
    source_path: str
    output_path: str | None = None
    status: Literal[
        "skipped_existing",
        "parsed",
        "needs_parser",
        "invalid_existing",
        "failed",
        "transient_failed",
    ]
    message: str | None = None


class BatchParseResult(StrictModel):
    items: list[BatchParseItem]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        return len(self.items)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def parsed(self) -> int:
        return sum(1 for item in self.items if item.status == "parsed")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def skipped(self) -> int:
        return sum(1 for item in self.items if item.status == "skipped_existing")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failed(self) -> int:
        return sum(1 for item in self.items if item.status in {"failed", "invalid_existing"})

    @computed_field  # type: ignore[prop-decorator]
    @property
    def transient_failed(self) -> int:
        """Papers that failed on a recoverable Gemini error (e.g. 503). Re-run to retry."""
        return sum(1 for item in self.items if item.status == "transient_failed")


class CostEstimate(StrictModel):
    source_root: str
    mark_scheme_pdfs: int = Field(..., ge=0)
    cached_json: int = Field(..., ge=0)
    needs_parsing: int = Field(..., ge=0)
    estimated_pdf_pages: int | None = Field(default=None, ge=0)
    token_policy: str


# I6 (#11, D19, US-013): one AnswerPoint's per-point marking decision.
#
# ``point_id`` must resolve against ``Question.answer_points`` — dangling
# ids are a coherence violation, same as the legacy
# ``AIMarkResponse.matched_point_ids`` (``_check_coherence``).
#
# ``evidence_span`` is the exact quoted substring from the student's
# transcribed answer/working that justifies ``verdict`` — the whole point of
# I6 is that an ``awarded`` verdict with no evidence can now be caught
# (``correction_ai._check_point_evidence``). Empty for a fresh ``withheld``
# verdict, where there is nothing to quote. NOT reliably empty for
# ``unverifiable`` since ``8b47b123``: when ``_verify_calculated_answers``
# overrules an ``awarded`` point and rewrites its verdict to
# ``unverifiable``, the rewrite preserves the marker's original
# ``evidence_span`` via ``model_copy``, so an overruled point routinely
# carries a non-empty span alongside ``unverifiable``.
#
# `PointVerdict` carries no bounding box. Marking is text-only -- `_mark_question`
# sends the transcription, never the page image -- so the model cannot produce
# one. Question-level boxes come from `ExtractedAnswer.source_box` on the
# extraction side instead (see the 2026-09-24 production-readiness spec).
#
# Post-I6-review Critical B fix: this used to be the class's DOCSTRING, not
# a comment. Pydantic derives a model's JSON-Schema ``description`` from
# ``__doc__`` when nothing overrides it, and this class's schema is nested
# inside ``AIMarkResponse`` — the ``response_schema`` for EVERY marking call,
# regardless of ``equivalence_gate`` — so the full text above was sent to
# Gemini, verbatim, on every single call. Worse: CPython's ``-O``/``-OO``
# strips docstrings, so ``GeminiClient._params_fingerprint`` (which hashes
# the UNSTRIPPED ``model_json_schema()`` for the on-disk cache key) computed
# a DIFFERENT hash depending on the ambient ``PYTHONOPTIMIZE`` setting —
# US-036's exact defect (``fix(io): stop PYTHONOPTIMIZE from stripping
# wire-schema description text``), reintroduced on the marking path this
# story added. US-036's own fix (hard-coding ``description`` via a
# ``__get_pydantic_json_schema__`` override, independent of ``__doc__``) was
# considered and rejected here: it would still send this whole block to
# Gemini on every call, merely stabilising which text gets sent rather than
# stopping the waste. A plain module comment (this block) documents the
# design exactly as before, for exactly the same readers (git blame, IDE
# navigation to the class), while carrying no doc text into
# ``model_json_schema()`` under EITHER interpreter mode, so the fingerprint
# cannot depend on ``PYTHONOPTIMIZE`` again by construction.
#: The three verdicts a marker can reach on one mark-scheme point (I6,
#: US-013). Exported so every wire boundary that narrows a looser
#: ``str | None`` back to these members (``lemely.db.review_repo``,
#: ``lemely.web.schemas_review``) imports one ``Literal`` instead of
#: hand-typing its own copy — migration ``0040`` already spent effort curing
#: eight formulations of one concept; this keeps it at one.
PointVerdictWire = Literal["awarded", "withheld", "unverifiable"]


class PointVerdict(StrictModel):
    point_id: str
    verdict: PointVerdictWire
    evidence_span: str = ""
    note: str = ""
    ecf_applied: bool = False
    """I7 (US-013): True when this verdict was reached only after
    re-marking the point with a substituted prior value (error carried
    forward). Always False when ``ecf_substitution`` is off or the point's
    scheme carries no ``ecf``/``ft``/``dep`` marker."""


def dedupe_point_verdicts(
    point_verdicts: Sequence[PointVerdict],
) -> tuple[list[PointVerdict], list[PointVerdict]]:
    """Split ``point_verdicts`` into ``(kept, dropped)`` by first-seen ``point_id``.

    Nothing in ``AIMarkResponse`` stops a marker from reporting the same
    ``point_id`` twice, and its two consumers used to disagree about what a
    repeat means: ``lemely.io.correction_ai._awarded_from_verdicts`` summed
    every awarded entry (inflating marks), while
    ``lemely.db.question_points.derive_point_rows`` kept the LAST entry
    (silently overwriting an earlier one) -- so an awarded-then-withheld pair
    for one id produced an awarded total alongside a persisted
    ``verdict='withheld'`` row for the same point. This is the single rule
    both now call, so they can no longer disagree: first occurrence of a
    ``point_id`` wins, every later one is reported back in ``dropped`` for
    the caller to log (naming the question id and the verdict that was
    dropped is a caller concern -- this function has neither).

    Pure, like the rest of this module: no logging, no I/O. A caller that
    must stay side-effect-free (``lemely.db.question_points``, "Pure: no
    session, no I/O") can call this and simply ignore ``dropped``; a caller
    that can log (``lemely.io.correction_ai``) uses it to warn.
    """
    kept: list[PointVerdict] = []
    dropped: list[PointVerdict] = []
    seen: set[str] = set()
    for pv in point_verdicts:
        if pv.point_id in seen:
            dropped.append(pv)
            continue
        seen.add(pv.point_id)
        kept.append(pv)
    return kept, dropped


class CorrectedQuestion(StrictModel):
    question_id: str
    awarded_marks: int = Field(..., ge=0)
    maximum_marks: int = Field(..., ge=0)
    confidence: ConfidenceBand
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    needs_teacher_review: bool
    student_answer: str | None = None
    expected_answer: str | None = None
    topic: str | None = None
    review_reason: str | None = None
    marker_source: MarkerSourceValue = "deterministic"
    """``"blank"`` (task #36, migration ``0040_marker_source_blank``): the
    student left this non-MCQ question EMPTY and no marking call was made --
    US-039's unflagged zero (``_build_blank_corrected``). It used to reuse
    ``"missing"`` and carry the distinction in ``review_reason`` prose, which
    made "did a marker score this?" un-answerable from the columns alone and
    cost nine hand-found consumers; see :data:`UNSCORED_MARKER_SOURCES`. Ask
    that question through :func:`marker_scored`, and ask "was this a student
    blank?" with ``marker_source == "blank"`` -- never off ``confidence_score``,
    ``confidence`` or ``review_reason``, all three of which a blank shares with
    a marker that looked and was unsure.

    ``"dropped"`` (US-031 review MUST-FIX 7): the model DID return an
    answer for this question, but extraction discarded it as malformed
    (unrecoverable ``question_id``/``answer`` shape) -- see
    ``ExtractedAnswers.dropped_question_ids``. Distinct from ``"missing"``,
    which covers ``--mcq-only``/no AI client (nothing was ever attempted),
    so the review queue does not conflate "we chose not to mark this" with
    "the model's response for this question could not be used at all".

    COVERAGE LIMIT (review MUST-FIX F1) -- this protection is PARTIAL. It
    reaches only the two drop reasons that leave a usable ``question_id``:
    ``missing_answer`` and ``malformed_answer``. Three do not, because there
    is no id to attribute the flag to:

    * ``missing_question_id``
    * ``malformed_question_id`` -- where MF5 routes a fractional-float id.
      Correct in itself (a silent zero beats mis-attributing an answer to a
      different question) but still a silent zero.
    * ``malformed_answer_shape`` -- the MF6 case, one bad element in the
      ``answers`` list. The paper survives where it previously did not.

    What those three actually cost depends on the leaf, and an earlier version
    of this note (transcribed from review prose carrying the same imprecision)
    claimed a single outcome for all of them. It does not hold:

    * non-MCQ leaf with an AI marker configured -- since US-039's blank
      short-circuit (``correct_paper``, checked after the ``ai is None``
      branch and before ``ai.mark_question``), this leaf no longer reaches
      the paid call MF7 was written against: with no surviving ``answers``
      entry, ``student_answer`` AND ``student_working`` both read as blank,
      so it is awarded 0 unflagged with no AI call, exactly like a genuine
      student blank. That removes the HIGH-confidence-zero defect this
      bullet used to describe, but does not make the outcome correct: this
      is the accepted FALSE-blank residual risk US-039 documents on
      ``_build_blank_corrected`` -- the model may have returned an answer
      extraction discarded, and it is now indistinguishable from a student
      who genuinely wrote nothing, silently.
    * MCQ leaf, or non-MCQ under ``--mcq-only``/no AI client -- already LOW,
      0.0, ``needs_teacher_review=True``, and no AI call at all, via
      ``_build_mcq_corrected``'s ``answer is None`` branch or
      ``_build_missing_corrected``. Safe by accident, not by design: the
      absent id makes the question indistinguishable from a genuine blank, so
      the mark is still a zero for a student whose answer the model DID
      return, under whichever blank message that path owns ("missing answer"
      on the MCQ path, "non-MCQ question not marked (--mcq-only or no AI
      client)" on the other) -- so the queue tells the teacher the wrong
      thing about why the question is in it.

    DB ROUND-TRIP (US-038, migration ``0038_marker_source_dropped``) --
    ``"dropped"`` DOES survive persistence. ``lemely.db.models.enums.MarkerSource``
    is a native Postgres enum rebuilt to add a ``dropped`` member alongside
    ``deterministic``/``ai``/``missing``, and ``attempt_repo.py`` no longer maps
    ``"dropped"`` onto ``missing`` on write -- the value round-trips unmapped.
    That removed the split this note used to describe: ``review_repo.py:440``
    (reading the DB enum) and ``review_repo.py:1042`` (reading ``report_json``)
    now agree, both yielding ``"dropped"`` for the identical situation."""
    feedback: str | None = None
    matched_point_ids: list[str] = Field(default_factory=list)
    point_verdicts: list[PointVerdict] = Field(default_factory=list)
    """I6 (US-013, defaults empty): the per-point verdicts + evidence spans
    ``_build_ai_corrected`` derived ``awarded_marks``/``matched_point_ids``
    from, when ``equivalence_gate`` was on and the marker returned any.
    Empty on every question marked with the flag off (today's default) and
    on every non-AI ``marker_source``. Carried on the record so a reviewer
    (or ``ReviewItem.tsx``, once wired end to end -- out of this story's
    file ownership: that needs ``lemely/web/schemas.py`` and
    ``lemely/db/review_repo.py``, neither owned here) can see WHICH quoted
    span justified an awarded mark, not just that one was awarded."""
    plagiarism_flagged: bool = False
    extraction_confidence: float | None = None
    """Extraction-side confidence (``ExtractedAnswer.confidence``) for the answer
    this question was built from, distinct from ``confidence_score`` which is the
    marking-stage confidence. ``None`` when no *surviving* answer was extracted
    for this question -- which, since US-031, has two distinct causes that this
    field alone cannot separate: the model genuinely returned nothing for this
    question, OR it returned something that was discarded as malformed before
    reaching ``ExtractedAnswers.answers`` (review SHOULD-FIX C). Check
    ``marker_source == "dropped"`` to tell the two apart -- since US-038
    (migration ``0038_marker_source_dropped``) this works identically on an
    in-memory ``CorrectedQuestion`` and on a row read back from the
    ``QuestionResult`` table, because the enum now carries ``"dropped"``
    without being narrowed to ``"missing"`` on write (see ``marker_source``
    above). Every dropped row also carries the fixed
    ``_DROPPED_ANSWER_REVIEW_REASON`` literal
    (``lemely/io/correction_ai.py``), so the same distinction is recoverable
    from ``review_reason`` too."""
    rationale: str | None = None
    """The marker's own reasoning for this question's mark, verbatim.

    Distinct from ``feedback``, which is written for the student. This is the
    marker explaining itself. ``None`` until a marker emits one — never
    synthesised from the mark scheme text, per spec 2026-09-17 D2.
    """
    source_box: SourceBox | None = None
    """Where on the rasterised page this question's answer was read from
    (E, 2026-09-24 production-readiness spec). QUESTION-level, not per mark
    point: marking is text-only -- ``lemely/io/correction_ai.py`` references
    no ``image``, ``RasterisedPage`` or ``media_resolution`` -- so the marker
    never sees the page and cannot attribute a region to one point. It
    answers "where did this answer come from", never "which pixels justify
    this mark". ``None`` is the common case rather than an error: the
    extractor may return no box, and a box it returned may have been dropped
    as unusable (``ExtractedAnswers.source_box_drops``), and those two are
    deliberately indistinguishable here. Absence must render as absence,
    never as a failed crop."""
    point_notes: dict[str, str] | None = None
    """Per-mark-point reasoning, keyed by ``AnswerPoint.id``.

    ``None`` until a marker emits it. Keys that do not correspond to a point in
    the mark scheme are ignored by the derivation rather than written as rows
    for points that do not exist.
    """

    @model_validator(mode="after")
    def validate_awarded_marks(self) -> CorrectedQuestion:
        if self.awarded_marks > self.maximum_marks:
            raise ValueError("awarded_marks cannot exceed maximum_marks")
        return self


class CorrectionResult(StrictModel):
    metadata: ExamMetadata
    questions: list[CorrectedQuestion]
    awarded_marks: int = 0
    maximum_marks: int = 0
    needs_teacher_review: bool = False

    @model_validator(mode="after")
    def calculate_totals(self) -> CorrectionResult:
        object.__setattr__(self, "awarded_marks", sum(q.awarded_marks for q in self.questions))
        object.__setattr__(self, "maximum_marks", sum(q.maximum_marks for q in self.questions))
        object.__setattr__(
            self,
            "needs_teacher_review",
            any(q.needs_teacher_review for q in self.questions),
        )
        return self


class WeakArea(StrictModel):
    topic: str
    lost_marks: int = Field(..., ge=0)
    maximum_marks: int = Field(..., ge=0)
    accuracy: float = Field(..., ge=0.0, le=1.0)
    question_ids: list[str]


class WeaknessReport(StrictModel):
    weak_areas: list[WeakArea]
    needs_teacher_review: bool = False


class GradePrediction(StrictModel):
    awarded_marks: int = Field(..., ge=0)
    maximum_marks: int = Field(..., ge=0)
    percentage: float = Field(..., ge=0.0, le=100.0)
    grade: str
    confidence: ConfidenceBand
    needs_teacher_review: bool = False
    boundary_source: Literal["exact", "subject_default", "global_default"] = "global_default"


class QuizQuestion(StrictModel):
    topic: str
    prompt: str
    source_question_ids: list[str]


class QuizPayload(StrictModel):
    questions: list[QuizQuestion]


class AccuracyReport(StrictModel):
    correction: CorrectionResult
    weaknesses: WeaknessReport
    grade_prediction: GradePrediction


class SourceBox(StrictModel):
    """A bounding box on one rasterised page, 0-1000 scale (I1).

    ``page`` is the 0-based index of the image part sent to Gemini (see
    ``lemely.io.rasterise.RasterisedPage.index``); ``box`` is
    ``[ymin, xmin, ymax, xmax]`` normalised to 0-1000 regardless of the
    page's actual pixel dimensions, matching Gemini's documented bounding-box
    convention for image inputs. Kept beside the prose ``source_region`` on
    :class:`ExtractedAnswer` rather than replacing it -- the box is what the
    crop-and-re-read step needs; the prose is what a human reviewer reads.
    """

    page: int = Field(..., ge=0)
    box: list[int] = Field(..., min_length=4, max_length=4)

    @field_validator("box")
    @classmethod
    def validate_box_coords(cls, v: list[int]) -> list[int]:
        for coord in v:
            if not 0 <= coord <= 1000:
                raise ValueError(f"box coordinates must be in [0, 1000], got {v!r}")
        ymin, xmin, ymax, xmax = v
        if ymax <= ymin or xmax <= xmin:
            raise ValueError(
                f"box must have positive area (ymax > ymin and xmax > xmin), got {v!r}"
            )
        return v


class ExtractedAnswer(StrictModel):
    question_id: str
    answer: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    source_region: str | None = None
    source_box: SourceBox | None = None
    working_out: str | None = None
    """Working steps, intermediate values, and annotations the student wrote in
    allowed areas (e.g. rough-work boxes, show-your-working space). Populated for
    calculation, equation, levels-based, and indicative-content questions; null for
    MCQ and simple-recall questions where no working is expected."""
    answer_reread: str | None = None
    """Set by the crop-and-re-read step (I1) when triggered by low confidence
    or by low cross-read agreement (I3, once wired -- see
    ``extraction_agreement`` below): a single-answer re-extraction from an
    upscaled crop of ``source_box``, at ``media_resolution="high"``. ``None``
    when no re-read was triggered."""
    reread_agreement: float | None = Field(default=None, ge=0.0, le=1.0)
    """I1's crop-and-re-read agreement: similarity between ``answer`` and
    ``answer_reread`` (0-1), i.e. this ONE answer against its own zoomed-in
    re-extraction. ``None`` when no re-read was triggered. This is NOT
    ``extraction_agreement`` below -- that is I3's cross-read second-opinion
    score, a different measurement with a different trigger. The two fields
    are deliberately kept separate; do not rename, merge, or conflate them."""
    extraction_agreement: float | None = Field(default=None, ge=0.0, le=1.0)
    """I3's cross-read agreement score (0-1, ``lemely.io.second_read``):
    similarity between this answer's ``answer`` text and an INDEPENDENT
    second read of the whole paper, matched by ``question_id``. This is NOT
    ``reread_agreement`` above -- that is I1's similarity between one answer
    and its own crop-and-re-read, not a second independent read of the whole
    paper. ``None`` when no second reader is configured
    (``GeminiSettings.second_reader == "none"``, the default) or when the
    second read did not return this ``question_id``."""


class ExtractedAnswers(StrictModel):
    paper_id: str
    source_scan: str
    answers: list[ExtractedAnswer]
    source_box_drops: dict[str, int] = Field(default_factory=dict)
    """Count of ``source_box`` values dropped during extraction, by reason
    (``"out_of_range_page"`` / ``"malformed_coordinates"``). Persisted here
    (I1 review round 2, should-fix 4) rather than only published as a
    transient bus event, so a later box-hit-rate metric's denominator shape
    is reconstructible from the record itself: without this, a
    ``source_box=None`` answer is indistinguishable from "the model gave no
    box at all" and "the model's box was dropped as unusable", and an
    extractor that hallucinates page indices would score better than one
    returning wrong-but-in-range boxes. Empty when nothing was dropped."""
    answer_drops: dict[str, int] = Field(default_factory=dict)
    """Count of whole ANSWERS dropped during extraction (US-031), by reason
    (``"missing_question_id"`` / ``"malformed_question_id"`` /
    ``"missing_answer"`` / ``"malformed_answer"`` / ``"malformed_answer_shape"``
    -- the last one when the list ELEMENT itself, not a field on it, could
    not be shaped into an answer at all). Unlike ``source_box``,
    ``question_id``/``answer`` have no safe fallback -- an answer that
    cannot be identified or has no text at all is dropped in full, never the
    rest of the paper with it. Empty when nothing was dropped."""
    confidence_repairs: dict[str, int] = Field(default_factory=dict)
    """Count of ``confidence`` values repaired during extraction (US-031),
    by reason (``"missing"`` / ``"non_finite"`` / ``"out_of_range"`` /
    ``"malformed"``). ``confidence`` is required on ``ExtractedAnswer`` and
    so cannot be dropped to ``None`` like ``source_box`` -- an unusable
    value -- including an out-of-range one, which is replaced rather than
    clamped toward the bound it overshot -- is replaced with a low
    fallback, counted here so a value the model never actually gave is
    distinguishable from a genuine one. Empty when nothing was repaired."""
    field_repairs: dict[str, int] = Field(default_factory=dict)
    """Count of optional cosmetic fields (US-031 review NIT A) silently
    coerced to ``None`` during extraction, by reason
    (``"malformed_source_region"`` / ``"malformed_working_out"``) -- a
    non-string ``source_region``/``working_out`` used to be discarded with
    no entry in any count dict anywhere, breaking the
    ``(value, drop_reason)`` idiom every other field in this module follows.
    The direction is safe (only a calibration bonus is forfeited), but the
    silence was not. Empty when nothing was repaired."""
    dropped_question_ids: list[str] = Field(default_factory=list)
    """Question ids (US-031 review MUST-FIX 7, stronger fix) whose answer
    was RETURNED by the model but DROPPED as malformed -- only populated
    when a question_id was itself salvageable (an ``"missing_answer"`` /
    ``"malformed_answer"`` drop reason in :data:`answer_drops`); an answer
    dropped because the question_id itself was unrecoverable
    (``"missing_question_id"`` / ``"malformed_question_id"`` /
    ``"malformed_answer_shape"``) cannot be attributed to any question and
    never appears here. ``correct_paper`` (:mod:`lemely.io.correction_ai`)
    reads this to distinguish "this question's answer was extracted and
    discarded as malformed" from "no answer was extracted for this question
    at all" -- both otherwise collapse to the SAME observable state
    (``student_answer=None``, ``extraction_confidence=None``) once the
    dropped answer never reaches :attr:`answers`, and correcting a paper
    with this ambiguity meant a malformed-JSON drop and a genuine student
    blank were indistinguishable to every downstream consumer. Remapped to
    real manifest ids by :func:`normalize_extracted_answers`, the same as
    ``answers``' own ids. Empty when nothing was dropped with a known id."""
    rereads_eligible: int = 0
    """How many answers were low-confidence enough (below
    ``reread_threshold``) to be eligible for a crop-and-re-read, before the
    per-paper cap was applied. Together with ``reread_attempts`` this makes
    the cap's effect reconstructible from the record: without it,
    ``reread_attempts`` alone cannot distinguish "only N answers were
    low-confidence" from "the cap truncated far more than N down to it" (I1
    review round 4, SHOULD-FIX E)."""
    reread_attempts: int = 0
    """How many crop-and-re-read calls this extraction *attempted*, after
    the per-paper cap. Renamed from ``rereads_run`` (I1 review round 4,
    SHOULD-FIX E): the old name and docstring claimed this counted calls
    actually *issued* to Gemini, but it is the size of the capped re-read
    set computed before the loop runs -- on a fully cache-hit re-run it
    reports N attempts for zero calls actually issued, and a re-read that
    raised and was absorbed (see the ``LemelyError`` handler in
    ``GeminiAnswerExtractor.__call__``) still counts here as one attempt.
    Useful for sizing the loop and the cap's effect, not as a paid-call
    count -- ``lemely.io.gemini``'s ``GEMINI_CALL_START``/
    ``GEMINI_CACHE_HIT`` bus events are the source of truth for actual API
    calls issued."""
    reread_threshold: float | None = None
    """The confidence threshold that gated which answers were eligible for
    a re-read on this run. ``None`` only when this ``ExtractedAnswers`` was
    not produced by the crop-and-re-read-aware extraction path at all."""


class SecondReadAnswer(BaseModel):
    """One answer as reported by I3's second read (``lemely.io.second_read``).

    Text only -- no box/confidence/working_out. Agreement is a
    text-similarity concern; the primary extraction already owns those other
    fields, so the second read is not asked to reproduce them.
    """

    question_id: str
    answer: str


class SecondReadOutput(BaseModel):
    """Wire schema (``response_schema``) for I3's second-read Gemini call.

    Defined here, alongside ``ExtractedAnswer``/``ExtractedAnswers``, rather
    than in ``lemely.io.second_read`` itself, because this module already
    carries the project's ``disallow_any_explicit = false`` mypy override for
    exactly this class of pydantic wire-schema definition (see
    ``pyproject.toml``); adding a second override entry for a brand-new
    module was outside this story's file ownership (``pyproject.toml``
    belongs to other lanes running concurrently in this session).
    """

    answers: list[SecondReadAnswer]


class AIMarkResponse(StrictModel):
    awarded_marks: int = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    matched_point_ids: list[str] = Field(default_factory=list)
    feedback: str
    point_verdicts: list[PointVerdict] = Field(default_factory=list)
    """I6 (US-013, defaults empty): per-point verdicts with quoted evidence
    spans. Additive field on the SAME wire schema used for every marking
    call, so a marker not yet asked for verdicts (the ``equivalence_gate``
    default-OFF path, unchanged prompt, no ``VERSION`` bump this story)
    simply never populates it. ``_build_ai_corrected`` in
    ``lemely.io.correction_ai`` only reads it, and only computes
    ``awarded_marks``/``matched_point_ids`` from it, when
    ``equivalence_gate=True`` AND this list is non-empty — see that
    function's docstring for the flag-off/empty-list fallback to the legacy
    ``awarded_marks``/``matched_point_ids`` fields above, which remain the
    source of truth until I6 is enabled (US-018)."""


class SubjectResult(StrictModel):
    subject_code: str = Field(...)
    session_month: Literal["May/June", "Oct/Nov", "Feb/Mar", "Specimen"]
    session_year: int | None = Field(default=None, ge=2000, le=2100)
    paper_results: list[CorrectionResult] = Field(..., min_length=1)
    awarded_marks: int = 0
    maximum_marks: int = 0
    percentage: float = 0.0
    grade: str = "U"
    weaknesses: WeaknessReport
    needs_teacher_review: bool = False

    @field_validator("subject_code")
    @classmethod
    def validate_subject_code(cls, v: str) -> str:
        if not _SUBJECT_CODE_RE.fullmatch(v):
            raise ValueError(f"subject_code must be a four-digit CAIE syllabus code, got {v!r}.")
        return v

    @model_validator(mode="after")
    def validate_and_compute(self) -> SubjectResult:
        for paper in self.paper_results:
            m = paper.metadata
            if m.subject_code != self.subject_code:
                raise ValueError(
                    f"paper subject_code {m.subject_code} != subject {self.subject_code}"
                )
            if m.session_month != self.session_month:
                raise ValueError(
                    f"paper session_month {m.session_month} != subject {self.session_month}"
                )
            if m.session_year != self.session_year:
                raise ValueError(
                    f"paper session_year {m.session_year} != subject {self.session_year}"
                )

        awarded = sum(p.awarded_marks for p in self.paper_results)
        maximum = sum(p.maximum_marks for p in self.paper_results)
        pct = (awarded / maximum * 100.0) if maximum else 0.0
        grade = "U"
        for cand, threshold in [("A", 80.0), ("B", 70.0), ("C", 60.0), ("D", 50.0), ("E", 40.0)]:
            if pct >= threshold:
                grade = cand
                break
        needs_review = any(p.needs_teacher_review for p in self.paper_results)

        object.__setattr__(self, "awarded_marks", awarded)
        object.__setattr__(self, "maximum_marks", maximum)
        object.__setattr__(self, "percentage", round(pct, 2))
        object.__setattr__(self, "grade", grade)
        object.__setattr__(self, "needs_teacher_review", needs_review)
        return self
