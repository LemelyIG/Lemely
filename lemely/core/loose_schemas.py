from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Shared enumerations
# ---------------------------------------------------------------------------


class PaperType(StrEnum):
    """Maps to the document header wording (Part 1 of the prompt)."""

    MCQ = "mcq"
    THEORY_CORE = "theory_core"
    THEORY_EXTENDED = "theory_extended"
    ALTERNATIVE_PRACTICAL = "alternative_practical"
    PRACTICAL = "practical"
    READING_WRITING = "reading_writing"
    LITERATURE_ESSAY = "literature_essay"
    FIELDWORK = "fieldwork"
    STRUCTURED_ESSAY = "structured_essay"
    COURSEWORK = "coursework"
    LISTENING = "listening"
    SPEAKING = "speaking"


class Tier(StrEnum):
    CORE = "core"
    EXTENDED = "extended"


class SchemeFormat(StrEnum):
    """Overall format of the mark scheme, detected from content."""

    POINT_BASED = "point_based"
    LEVELS_BASED = "levels_based"
    INDICATIVE_CONTENT = "indicative_content"
    MCQ = "mcq"
    MIXED = "mixed"


class SessionMonth(StrEnum):
    MAY_JUNE = "May/June"
    OCT_NOV = "Oct/Nov"
    FEB_MAR = "Feb/Mar"
    SPECIMEN = "Specimen"


class QuestionType(StrEnum):
    """Part 3A of the prompt: question type taxonomy."""

    MCQ = "mcq"
    RECALL = "recall"
    EXPLANATION = "explanation"
    CALCULATION = "calculation"
    EQUATION = "equation"
    GRAPH_DRAW = "graph_draw"
    GRAPH_READ = "graph_read"
    DIAGRAM = "diagram"
    TABLE = "table"
    LIST = "list"
    COMPARISON = "comparison"
    MULTI_STEP = "multi_step"
    LEVELS_BASED = "levels_based"
    INDICATIVE_CONTENT = "indicative_content"
    FIELDWORK = "fieldwork"
    TICKBOX = "tickbox"


class MathMarkType(StrEnum):
    """Part 3B of the prompt: mathematics mark code system."""

    M = "M"  # Method mark
    A = "A"  # Accuracy mark (dependent on preceding M)
    B = "B"  # Independent mark
    DEP = "dep"  # Explicitly dependent
    FT = "ft"  # Follow-through
    ISW = "isw"  # Ignore subsequent working
    CAO = "cao"  # Correct answer only
    OE = "oe"  # Or equivalent
    SC = "SC"  # Special case
    NFWW = "nfww"  # Not from wrong working
    SOI = "soi"  # Seen or implied
    ORA = "ora"  # Or reverse argument
    BO = "bo"  # Benefit of the doubt
    ALLOW = "allow"  # Acceptable phrasing variant
    AW = "AW"  # Alternative wording
    MP = "MP"  # Mark point  # Seen or implied


class MCQAnswer(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class IndicativeContentStrand(StrEnum):
    READING = "reading"
    WRITING = "writing"
    GENERAL = "general"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class CalculatedAnswer(BaseModel):
    """Part 4B — embedded in an AnswerPoint when a mark requires a
    specific numerical result. Also used for toleranced measurements
    (Part 4C).
    """

    model_config = ConfigDict(populate_by_name=True)

    value: float | None = Field(
        None,
        description="Numerical value of the answer (exact, not rounded).",
    )
    unit: str | None = Field(
        None,
        description="Unit string as written in the mark scheme, e.g. 'N', 'kg m/s', '°C'.",
    )
    standard_form: str | None = Field(
        None,
        description="Standard form representation exactly as written, e.g. '1.6 × 10⁵'. "
        "Null if the mark scheme does not express it in standard form.",
    )
    sig_figs: int | None = Field(
        None,
        ge=1,
        description="Number of significant figures required by the mark scheme. "
        "Null if not specified.",
    )
    dp: int | None = Field(
        None,
        ge=0,
        description="Decimal places required. Null if not specified.",
    )
    unit_required: bool = Field(
        False,
        description="True if the mark is withheld when the unit is absent.",
    )
    unit_penalised: bool = Field(
        False,
        description="True if the mark is lost when the unit is wrong "
        "(common in structured theory papers).",
    )
    accept_equivalent_forms: bool = Field(
        False,
        description="True when mark scheme says 'oe' — fractions, decimals, and "
        "standard form are all accepted.",
    )
    tolerance: str | None = Field(
        None,
        description="Measurement tolerance as a string, e.g. '± 0.2'. "
        "Used in Biology ATP and Geography fieldwork questions.",
    )


class AnswerPoint(BaseModel):
    """Part 4A — a single discrete marking point within a point-based question.
    Also used for individual items in list (4D), tickbox (4E), and
    special-case (4G) questions.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(
        ...,
        description="Sequential ID within the question, e.g. 'p1', 'p2', 'p_sc'.",
    )
    point: str = Field(
        ...,
        description="Exact text of the mark point, preserved from the source. "
        "Abbreviations are kept here; expansions go in `notes`.",
    )
    marks: int = Field(
        ...,
        ge=0,
        description="Marks awarded for this point. Zero for tickbox distractors.",
    )
    math_mark_type: MathMarkType | None = Field(
        None,
        description="Mathematics mark code (Part 3B). Null for non-maths questions.",
    )
    is_alternative: bool = Field(
        False,
        description="True if this point is an OR/EITHER…OR alternative to the previous "
        "point — marks are not additive.",
    )
    is_optional: bool = Field(
        False,
        description="True if this point is one of a pool ('any N from') — "
        "candidates earn marks for selecting any N of these.",
    )
    owtte: bool = Field(
        False,
        description="True if the mark scheme says 'owtte' (or words to that effect) "
        "or 'AW' (alternative wording) for this point.",
    )
    avp: bool = Field(
        False,
        description="True if the mark scheme says 'AVP' (alternative valid point) — "
        "used in Biology mark schemes.",
    )
    accept: list[str] = Field(
        default_factory=list,
        description="Explicitly stated alternative phrasings that earn this mark.",
    )
    required_with: str | None = Field(
        None,
        description="ID of the AnswerPoint this point depends on. Used for A marks in "
        "Maths (dep on M mark) and chained science marks.",
    )
    underlined_required: list[str] = Field(
        default_factory=list,
        description="Words that must appear verbatim for credit — these appear "
        "underlined in the original mark scheme.",
    )
    tolerance: str | None = Field(
        None,
        description="Point-level tolerance string for non-numerical marks, "
        "e.g. '± half a small square'.",
    )
    condition: str | None = Field(
        None,
        description="Conditional note for special-case marks, e.g. "
        "'Only if candidate has not earned M1'.",
    )
    is_correct: bool | None = Field(
        None,
        description="Tickbox questions only: True = correct option, False = distractor. "
        "Null for all other question types.",
    )
    calculated_answer: CalculatedAnswer | None = Field(
        None,
        description="Present when this mark point carries a specific numerical result.",
    )

    @model_validator(mode="after")
    def validate_tickbox_correctness(self) -> AnswerPoint:
        """Distractor points in tickbox questions should have marks=0."""
        if self.is_correct is False and self.marks != 0:
            raise ValueError(
                f"AnswerPoint '{self.id}': distractor items (is_correct=False) must have marks=0."
            )
        return self


class DrawingCriterion(BaseModel):
    """Part 7 — a single assessable criterion within a diagram/drawing question."""

    id: str = Field(..., description="Sequential ID, e.g. 'd1', 'd2'.")
    criterion: str = Field(
        ...,
        description="Category of the criterion, e.g. 'outline', 'size', 'detail_1'.",
    )
    requirement: str = Field(
        ...,
        description="Full text of what the candidate must produce, "
        "e.g. 'Single clear line, no shading'.",
    )
    marks: int = Field(..., ge=1, description="Marks available for this criterion.")


class PlotRequirement(BaseModel):
    """Part 8 — a single required data point for graph_draw questions."""

    x_value: float | None = Field(None, description="X-axis value to be plotted.")
    y_value: float | None = Field(None, description="Y-axis value to be plotted.")
    unit: str | None = Field(
        None,
        description="Combined units description, e.g. 'm / cm'.",
    )
    tolerance: str | None = Field(
        None,
        description="Acceptable plotting tolerance, e.g. '± half a small square'.",
    )
    ecf: bool = Field(
        False,
        description="True if error-carried-forward applies to this plot point.",
    )
    notes: str | None = Field(None, description="Additional guidance for this plot.")


class PenaltyRule(BaseModel):
    """Part 4E — graduated penalty for over-ticking in tickbox questions."""

    n_selected: int = Field(
        ...,
        ge=1,
        description="Number of options the candidate selected.",
    )
    max_marks_awarded: int = Field(
        ...,
        ge=0,
        description="Maximum marks that can be awarded when n_selected options are ticked.",
    )
    description: str | None = Field(
        None,
        description="Human-readable summary, e.g. '4 ticked → max 2 marks'.",
    )


class DescriptorText(BaseModel):
    """One labelled descriptor entry within a levels-based mark band."""

    label: str = Field(
        ...,
        description="Descriptor label, e.g. 'AO1', 'AO2', or 'general'.",
    )
    text: str = Field(
        ...,
        description="Full descriptor text for this label.",
    )


class LevelDescriptor(BaseModel):
    """Part 5 — one level within a levels-based or levels-of-response mark scheme.
    Used for Literature, History, extended Geography, and English Language extended
    writing questions.
    """

    model_config = ConfigDict(populate_by_name=True)

    level: int = Field(
        ...,
        ge=0,
        description="Level number. 0 = no creditable response. Literature uses 0–8; "
        "History typically uses 0–4.",
    )
    mark_range: list[int] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="Inclusive (min, max) mark range for this level.",
    )
    descriptors: list[DescriptorText] = Field(
        ...,
        description="Descriptor entries labelled by AO label (e.g. 'AO1', 'AO2') "
        "or 'general' for non-AO-split descriptors.",
    )
    one_sided_threshold: bool | None = Field(
        None,
        description="History only: True if this level requires a one-sided argument, "
        "False if two-sided is needed. Null for non-History schemes.",
    )
    min_explanations: int | None = Field(
        None,
        ge=0,
        description="History only: minimum number of explanations required at this level.",
    )

    @field_validator("mark_range")
    @classmethod
    def validate_mark_range(cls, v: list[int]) -> list[int]:
        lo, hi = v
        if lo > hi:
            raise ValueError(f"mark_range lower bound ({lo}) must be ≤ upper bound ({hi}).")
        return v


class ReservedMark(BaseModel):
    """History / Geography fieldwork only — marks that are reserved for a
    specific conclusion or hypothesis answer (HA, XHA, ^HA pattern).
    """

    annotation: str = Field(
        ...,
        description="Annotation symbol used in the mark scheme, e.g. 'HA', 'XHA', '^HA'.",
    )
    condition: str = Field(
        ...,
        description="The condition under which this reserved mark is awarded or withheld.",
    )
    marks_reserved: int = Field(
        ...,
        ge=0,
        description="Number of marks held in reserve for this condition.",
    )


class IndicativeContentPoint(BaseModel):
    """Part 6 — one item from an indicative content list (English Language)."""

    id: str = Field(..., description="Sequential ID, e.g. 'ic1', 'ic2'.")
    point: str = Field(
        ...,
        description="The content point the candidate may include for credit.",
    )
    strand: IndicativeContentStrand = Field(
        IndicativeContentStrand.READING,
        description="Whether this point earns reading or writing marks.",
    )


class BandedCriterion(BaseModel):
    """Part 6 — one level within a reading_criteria or writing_criteria banded table
    (English Language), or a Table A evaluation rubric (Geography).
    """

    level: int = Field(..., ge=0, description="Level number within the table.")
    mark_range: list[int] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="Inclusive (min, max) mark range for this level.",
    )
    description: str = Field(
        ...,
        description="Full text of the level descriptor as written in the mark scheme.",
    )

    @field_validator("mark_range")
    @classmethod
    def validate_mark_range(cls, v: list[int]) -> list[int]:
        lo, hi = v
        if lo > hi:
            raise ValueError(f"mark_range lower bound ({lo}) must be ≤ upper bound ({hi}).")
        return v


# ---------------------------------------------------------------------------
# The AbbreviationLegend shipped with every mark scheme
# ---------------------------------------------------------------------------


class PaperSpecificAbbreviation(BaseModel):
    """A paper-specific abbreviation not covered by the standard legend."""

    abbreviation: str = Field(..., description="Abbreviation exactly as printed.")
    expansion: str = Field(..., description="Expanded meaning of the abbreviation.")


class AbbreviationLegend(BaseModel):
    """Standard CAIE abbreviations decoded. Populated from Part 3C of the prompt."""

    ecf: str = "Error carried forward"
    owtte: str = "Or words to that effect"
    AVP: str = "Alternative valid point"
    AW: str = "Alternative wording"
    isw: str = "Ignore subsequent working"
    cao: str = "Correct answer only"
    oe: str = "Or equivalent"
    dep: str = "Dependent"
    nfww: str = "Not from wrong working"
    soi: str = "Seen or implied"
    ora: str = "Or reverse argument"
    SC: str = "Special case"
    bo: str = "Benefit of the doubt"
    allow: str = "Acceptable phrasing variant"
    MP: str = "Mark point"
    FT: str = "Follow-through after error"
    A: str = "Acceptable alternative answer"
    I: str = "Ignore this - neither credited nor penalised"
    R: str = "Do not accept this answer"
    paper_specific: list[PaperSpecificAbbreviation] = Field(
        default_factory=list,
        description="Subject- or paper-specific abbreviations not covered by the standard fields.",
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class MarkSchemeMetadata(BaseModel):
    """Part 1 — header metadata extracted from the first page of the mark scheme.
    All fields map directly to attributes described in the prompt.
    """

    model_config = ConfigDict(populate_by_name=True)

    subject: str = Field(
        ...,
        description="Full subject name as printed on the mark scheme, "
        "e.g. 'Physics', 'First Language English'.",
    )
    subject_code: Annotated[str, Field(pattern=r"^\d{4}$")] = Field(
        ...,
        description="Four-digit CAIE syllabus code, e.g. '0625', '0580', '0500'.",
    )
    paper_number: int = Field(
        ...,
        ge=1,
        le=9,
        description="Paper number extracted from the paper code suffix "
        "(digit immediately after '/'). E.g. '0580/42' → 4.",
    )
    paper_variant: int = Field(
        ...,
        ge=1,
        le=9,
        description="Paper variant extracted from the final digit of the paper code. "
        "E.g. '0580/42' → 2.",
    )
    session_month: SessionMonth = Field(
        ...,
        description="Examination session as a standardised string.",
    )
    session_year: int | None = Field(
        None,
        ge=2000,
        le=2100,
        description="Four-digit year. Null for Specimen papers.",
    )
    paper_type: PaperType = Field(
        ...,
        description="Standardised paper type derived from the document title.",
    )
    tier: Tier | None = Field(
        None,
        description="Core or Extended tier. Null when not determinable from the header.",
    )
    maximum_mark: int = Field(
        ...,
        ge=1,
        description="Maximum mark for the paper, as stated on the cover page.",
    )
    scheme_format: SchemeFormat = Field(
        ...,
        description="Predominant mark scheme format detected from the document content.",
    )
    assessment_objectives: list[str] = Field(
        default_factory=list,
        description="Assessment objective labels tested in this paper, "
        "e.g. ['AO1', 'AO2', 'R1', 'R2', 'W2'].",
    )
    assessment_objectives_weighting: dict[str, str] = Field(
        default_factory=dict,
        description="AO code → weighting or description as printed in the mark scheme, "
        "e.g. {'AO1': '30%', 'AO2': '50%'}. Empty when not stated.",
    )
    subject_specific_principles: list[str] = Field(
        default_factory=list,
        description="Subject-specific marking principles printed in the mark scheme "
        "(e.g. science semicolon-separator rule, maths misread rule). "
        "Captured verbatim as a list of strings.",
    )
    generic_marking_principles: list[str] = Field(
        default_factory=list,
        description="Generic Marking Principles from the cover pages, captured verbatim "
        "in order (e.g. GMP 1–6). These apply to all CAIE papers and govern general "
        "award decisions such as marking contradictory responses.",
    )
    examiner_instructions: str | None = Field(
        None,
        description="Verbatim assessor/examiner instruction block from the cover page, "
        "if present (e.g. 'Examiners should mark according to the mark scheme…').",
    )
    notation_key_text: str | None = Field(
        None,
        description="Verbatim text of the mark-scheme abbreviations/key page, "
        "if a dedicated key page is present in the PDF.",
    )
    paper_structure_summary: str | None = Field(
        None,
        description="Brief prose description of the paper structure as stated on the cover "
        "or introductory pages (e.g. 'Section A: 40 marks MCQ; Section B: 60 marks structured').",
    )
    published: bool = Field(
        True,
        description="True if the mark scheme is marked 'Published'. "
        "False for pre-standardisation or confidential versions.",
    )
    source_document: str | None = Field(
        None,
        description="Filename or URL of the source PDF, if known.",
    )

    @model_validator(mode="after")
    def specimen_year_is_null(self) -> MarkSchemeMetadata:
        if self.session_month == SessionMonth.SPECIMEN and self.session_year is not None:
            raise ValueError("Specimen mark schemes do not have a session_year — set it to null.")
        return self


# ---------------------------------------------------------------------------
# The Question model (recursive)
# ---------------------------------------------------------------------------


class Question(BaseModel):
    """The central model. One Question object is created per numbered item
    (or sub-part) in the mark scheme. The `parts` field allows arbitrary
    nesting to mirror the source hierarchy.

    Mandatory fields depend on `type`:
      • MCQ           → mcq_answer required
      • levels_based  → level_descriptors required, answer_points empty
      • indicative_content → indicative_content list required
      • diagram       → drawing_criteria or answer_points required
      • graph_draw    → plot_requirements required
      • tickbox       → penalty_rules required, select_count required
      • list          → select_count required
    """

    model_config = ConfigDict(populate_by_name=True)

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    id: str = Field(
        ...,
        description="Unique hierarchical ID following Part 2 notation: "
        "'1', '2a', '1a_i', '1a_i_A'.",
    )
    parent_id: str | None = Field(
        None,
        description="ID of the parent question. Null for top-level questions.",
    )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    marks: int = Field(
        ...,
        ge=0,
        description="Total marks available for this question/part. "
        "Set to 0 for container questions that only group sub-parts.",
    )
    type: QuestionType = Field(
        ...,
        description="Question type from the Part 3A taxonomy.",
    )
    question_command: str | None = Field(
        None,
        description="The command word(s) as they appear in the question, "
        "e.g. 'explain why', 'calculate', 'describe', 'tick three'.",
    )
    assessment_objectives: list[str] = Field(
        default_factory=list,
        description="AO labels tested by this specific question/part, "
        "e.g. ['AO1', 'AO2'] or ['R1', 'R5'].",
    )
    topic_hint: str | None = Field(
        None,
        description="Inferred syllabus topic. Set only when unambiguous from context. "
        "Null otherwise.",
    )
    scheme_format: SchemeFormat | None = Field(
        None,
        description="Format of this specific question's marking. May differ from the "
        "paper-level format in mixed papers.",
    )

    # ------------------------------------------------------------------
    # Point-based fields (most questions)
    # ------------------------------------------------------------------

    answer_points: list[AnswerPoint] = Field(
        default_factory=list,
        description="Ordered list of mark points. Empty for levels_based and "
        "pure indicative_content questions.",
    )
    select_count: int | None = Field(
        None,
        ge=1,
        description="For 'list' and 'tickbox' types: how many options the "
        "candidate must select / how many can be credited.",
    )
    penalty_rules: list[PenaltyRule] | None = Field(
        None,
        description="Tickbox only: graduated penalty rules for over-ticking.",
    )

    # ------------------------------------------------------------------
    # MCQ
    # ------------------------------------------------------------------

    mcq_answer: MCQAnswer | None = Field(
        None,
        description="Correct answer letter for MCQ questions. Null for all others.",
    )

    # ------------------------------------------------------------------
    # Levels-based fields
    # ------------------------------------------------------------------

    level_descriptors: list[LevelDescriptor] | None = Field(
        None,
        description="Ordered list of level descriptors (highest level first is "
        "conventional but not enforced). Required for levels_based type.",
    )
    reserved_marks: list[ReservedMark] | None = Field(
        None,
        description="History/Geography only: reserved marks for specific conclusions "
        "(HA, XHA, ^HA annotations).",
    )
    marking_guidance: str | None = Field(
        None,
        description="Prose guidance printed in the mark scheme for holistic judgement, "
        "e.g. 'Award the highest mark if the response convincingly meets "
        "the level descriptor.'",
    )

    # ------------------------------------------------------------------
    # Indicative content fields (English Language)
    # ------------------------------------------------------------------

    indicative_content: list[IndicativeContentPoint] | None = Field(
        None,
        description="Numbered content points from which candidates draw credit. "
        "Not exhaustive — examiners credit valid alternatives.",
    )
    reading_criteria: list[BandedCriterion] | None = Field(
        None,
        description="Table A (Reading): banded criteria used to mark reading quality.",
    )
    writing_criteria: list[BandedCriterion] | None = Field(
        None,
        description="Table B (Writing): banded criteria used to mark writing quality.",
    )
    content_marks: int | None = Field(
        None,
        ge=0,
        description="Indicative content questions: marks available for content/reading.",
    )
    writing_marks: int | None = Field(
        None,
        ge=0,
        description="Indicative content questions: marks available for writing quality.",
    )
    word_limit: int | None = Field(
        None,
        ge=1,
        description="Maximum word count the candidate's response must not exceed. "
        "Null if no limit is stated.",
    )
    own_words_required: bool | None = Field(
        None,
        description="True if the mark scheme explicitly requires candidates to use "
        "their own words (common in English Language summary tasks).",
    )
    verbatim_lift_policy: str | None = Field(
        None,
        description="The mark scheme's stated policy on verbatim copying from the "
        "source text, e.g. 'Answers entirely in the words of the text "
        "should not be credited'.",
    )

    # ------------------------------------------------------------------
    # Diagram / drawing fields
    # ------------------------------------------------------------------

    drawing_criteria: list[DrawingCriterion] | None = Field(
        None,
        description="Ordered list of assessable drawing criteria for diagram questions.",
    )

    # ------------------------------------------------------------------
    # Graph / data plotting fields
    # ------------------------------------------------------------------

    plot_requirements: list[PlotRequirement] | None = Field(
        None,
        description="Required data points/trends for graph_draw questions.",
    )

    # ------------------------------------------------------------------
    # Reject / ignore lists
    # ------------------------------------------------------------------

    rejected_answers: list[str] = Field(
        default_factory=list,
        description="Answers the mark scheme explicitly states must NOT be accepted "
        "(marked 'R' or 'not' in the source).",
    )
    ignored_answers: list[str] = Field(
        default_factory=list,
        description="Answers that must be ignored — neither credited nor penalised "
        "(marked 'I' or 'ignore' in the source).",
    )

    # ------------------------------------------------------------------
    # Examiner notes / special rules
    # ------------------------------------------------------------------

    notes: str | None = Field(
        None,
        description="Expanded examiner guidance: includes ecf conditions, guidance "
        "column content (Biology ATP), misread rules (Mathematics), and "
        "any other special conditions. Abbreviations expanded here.",
    )

    # ------------------------------------------------------------------
    # Sub-parts (recursive)
    # ------------------------------------------------------------------

    parts: list[Question] = Field(
        default_factory=list,
        description="Nested sub-part questions in source order. Mirrors the "
        "hierarchical numbering from the mark scheme.",
    )

    # ------------------------------------------------------------------
    # Cross-field validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def validate_type_constraints(self) -> Question:
        t = self.type
        has_marking_content = bool(
            self.answer_points
            or self.drawing_criteria
            or self.plot_requirements
            or self.notes
            or self.marking_guidance
            or self.parts
        )

        # MCQ must have an answer letter
        if t == QuestionType.MCQ and self.mcq_answer is None:
            raise ValueError(f"Question '{self.id}': MCQ questions must set mcq_answer.")

        # Non-MCQ must NOT have an mcq_answer
        if t != QuestionType.MCQ and self.mcq_answer is not None:
            raise ValueError(f"Question '{self.id}': mcq_answer is only valid for MCQ questions.")

        # levels_based must have descriptors, not answer_points
        if t == QuestionType.LEVELS_BASED:
            if not self.level_descriptors:
                raise ValueError(
                    f"Question '{self.id}': levels_based questions require level_descriptors."
                )
            if self.answer_points:
                raise ValueError(
                    f"Question '{self.id}': levels_based questions must have an "
                    "empty answer_points list."
                )

        # indicative_content questions must carry content
        if t == QuestionType.INDICATIVE_CONTENT:
            if self.indicative_content is None:
                raise ValueError(
                    f"Question '{self.id}': indicative_content questions require "
                    "an indicative_content list."
                )
            if self.content_marks is None or self.writing_marks is None:
                raise ValueError(
                    f"Question '{self.id}': indicative_content questions require "
                    "content_marks and writing_marks."
                )
            expected_total = self.content_marks + self.writing_marks
            if expected_total != self.marks:
                raise ValueError(
                    f"Question '{self.id}': content_marks ({self.content_marks}) + "
                    f"writing_marks ({self.writing_marks}) = {expected_total}, "
                    f"but marks = {self.marks}."
                )

        # Diagram questions may be marked either with structured drawing criteria
        # or ordinary answer points, depending on how the source mark scheme is written.
        if t == QuestionType.DIAGRAM and not has_marking_content:
            raise ValueError(
                f"Question '{self.id}': diagram questions require drawing_criteria "
                "or other marking content."
            )

        # Graph drawing questions may be marked with explicit plot requirements,
        # ordinary mark points, or source guidance preserved in notes.
        if t == QuestionType.GRAPH_DRAW and not has_marking_content:
            raise ValueError(
                f"Question '{self.id}': graph_draw questions require plot_requirements "
                "or other marking content."
            )

        # list and tickbox questions usually need select_count; allow notes-only
        # fallback when the source text has not been decomposed into answer_points.
        if (
            t in (QuestionType.LIST, QuestionType.TICKBOX)
            and self.select_count is None
            and self.answer_points
        ):
            raise ValueError(
                f"Question '{self.id}': list and tickbox questions require select_count."
            )

        # tickbox questions must have penalty_rules
        if t == QuestionType.TICKBOX and not self.penalty_rules:
            raise ValueError(f"Question '{self.id}': tickbox questions require penalty_rules.")

        return self

    @model_validator(mode="after")
    def validate_mark_point_sum(self) -> Question:
        """For point-based questions: the sum of non-alternative, non-optional
        points must not exceed the question's total marks. Optional (list)
        and alternative points are excluded because only N are credited.
        """
        if self.type in (
            QuestionType.LEVELS_BASED,
            QuestionType.INDICATIVE_CONTENT,
            QuestionType.MCQ,
        ):
            return self

        primary_points = [
            p for p in self.answer_points if not p.is_alternative and not p.is_optional
        ]
        total = sum(p.marks for p in primary_points)
        if self.marks > 0 and total > self.marks:
            raise ValueError(
                f"Question '{self.id}': sum of primary mark points ({total}) "
                f"exceeds total marks ({self.marks})."
            )
        return self

    @model_validator(mode="after")
    def validate_drawing_criteria_sum(self) -> Question:
        """Drawing criteria marks must sum to the question's total marks."""
        if self.type == QuestionType.DIAGRAM and self.drawing_criteria:
            total = sum(c.marks for c in self.drawing_criteria)
            if total != self.marks:
                raise ValueError(
                    f"Question '{self.id}': drawing_criteria marks sum to {total}, "
                    f"but marks = {self.marks}."
                )
        return self


# Allow the recursive self-reference to resolve
Question.model_rebuild()


# ---------------------------------------------------------------------------
# Root document model
# ---------------------------------------------------------------------------


class MarkScheme(BaseModel):
    """Root model. Represents a single complete IGCSE mark scheme document.
    Deserialise the JSON output of the LLM prompt directly into this model.
    """

    model_config = ConfigDict(populate_by_name=True)

    metadata: MarkSchemeMetadata = Field(
        ...,
        description="Header metadata extracted from the mark scheme cover page.",
    )
    abbreviation_legend: AbbreviationLegend = Field(
        default_factory=AbbreviationLegend,
        description="Standard CAIE abbreviations with their expanded meanings. "
        "Includes any paper-specific additions.",
    )
    questions: list[Question] = Field(
        ...,
        min_length=1,
        description="All questions in source order. Top-level questions only — "
        "sub-parts are nested inside each question's `parts` list.",
    )

    @model_validator(mode="after")
    def validate_maximum_mark(self) -> MarkScheme:
        """For MCQ papers: the total marks across all top-level questions
        should equal the maximum_mark on the metadata.
        """
        if self.metadata.paper_type == PaperType.MCQ:
            total = sum(q.marks for q in self.questions)
            if total != self.metadata.maximum_mark:
                raise ValueError(
                    f"MCQ paper: sum of question marks ({total}) does not equal "
                    f"metadata.maximum_mark ({self.metadata.maximum_mark})."
                )
        return self

    def get_question_by_id(self, question_id: str) -> Question | None:
        """Depth-first search for a question by its ID across the entire hierarchy.
        Returns the first match or None if not found.
        """

        def _search(questions: list[Question]) -> Question | None:
            for q in questions:
                if q.id == question_id:
                    return q
                found = _search(q.parts)
                if found:
                    return found
            return None

        return _search(self.questions)

    def all_questions_flat(self) -> list[Question]:
        """Returns every question in the document as a flat list (depth-first),
        including all sub-parts at every level of nesting.
        """
        result: list[Question] = []

        def _collect(questions: list[Question]) -> None:
            for q in questions:
                result.append(q)
                _collect(q.parts)

        _collect(self.questions)
        return result

    def total_marks_by_type(self) -> dict[str, int]:
        """Returns a dict of question type → total marks available across
        the entire paper (useful for paper-level analytics).
        """
        totals: dict[str, int] = {}
        for q in self.all_questions_flat():
            key = q.type.value
            totals[key] = totals.get(key, 0) + q.marks
        return totals

    @property
    def json_schema(self) -> dict[str, Any]:
        """Convenience accessor for the full JSON schema of this model."""
        return self.model_json_schema()
