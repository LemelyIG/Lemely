"""API DTOs for the quiz-builder endpoints (``/api/teacher/quizzes/*``, P3.5 chunk D).

Field names are camelCase to match the frontend contract, mirroring the
other ``schemas_*.py`` modules. Converters live in
:mod:`lemely.web.routers.quiz`.
"""

from __future__ import annotations

from lemely.web.schemas import ApiModel


class QuizQuestionDTO(ApiModel):
    """One materialized quiz question — the frozen snapshot (§1.5).

    ``status`` is ``"included"`` or ``"removed"`` — removed rows are kept,
    not deleted, and still appear here (the curation audit trail).
    """

    id: str
    questionBankId: str | None
    questionRef: str
    position: int
    status: str
    replacedById: str | None
    topic: str | None
    difficulty: str
    questionType: str
    prompt: str
    modelAnswer: str | None
    markSchemePoints: list[str]
    mcqOptions: list[str] | None
    mcqAnswer: str | None
    totalMarks: int


class QuizSummaryDTO(ApiModel):
    """One quiz, draft or otherwise — the builder's resumable state (§1.4)."""

    id: str
    subjectCode: str
    title: str
    status: str
    targetGrade: str | None
    includedTopics: list[str]
    poolSource: str | None
    requestedCount: int | None
    timeLimitMinutes: int | None
    builderStep: int
    questionCount: int


class QuizListDTO(ApiModel):
    """Response for ``GET /api/teacher/quizzes``."""

    quizzes: list[QuizSummaryDTO]


class QuizDetailDTO(ApiModel):
    """Response for ``GET /api/teacher/quizzes/{quiz_id}``."""

    quiz: QuizSummaryDTO
    questions: list[QuizQuestionDTO]


class CreateQuizRequestDTO(ApiModel):
    """Create a draft quiz: entering step 1 of the builder (§1.4)."""

    subjectCode: str
    title: str


class UpdateQuizDraftRequestDTO(ApiModel):
    """Partial-update a draft quiz's step-2/3/4 fields.

    Every field omitted (``None``) leaves the stored value untouched — see
    ``QuizService.patch_draft``'s docstring. ``poolSource`` must be one of
    ``"past_paper"`` / ``"generated"`` / ``"teacher_upload"`` when supplied.
    """

    title: str | None = None
    targetGrade: str | None = None
    includedTopics: list[str] | None = None
    poolSource: str | None = None
    requestedCount: int | None = None
    timeLimitMinutes: int | None = None
    builderStep: int | None = None


class SetQuizStatusRequestDTO(ApiModel):
    """Transition a quiz's status — one of ``draft``/``assigned``/``closed``/``archived``."""

    status: str


class GenerateQuizQuestionsResponseDTO(ApiModel):
    """Response for ``POST /api/teacher/quizzes/{quiz_id}/questions/generate``."""

    created: list[QuizQuestionDTO]
    shortfall: dict[str, int] | None = None


class CreateQuizAssignmentRequestDTO(ApiModel):
    """Request body for ``POST /api/teacher/quizzes/{quiz_id}/assignments``.

    ``dueAt``/``closesAt`` are ISO-8601 datetime strings when supplied
    (parsed and validated tz-aware at the router boundary, matching the
    codebase's existing ``_parse_recorded_at``-style convention) or ``None``.
    """

    classId: str
    dueAt: str | None = None
    closesAt: str | None = None


class QuizAssignmentDTO(ApiModel):
    """One assignment of a quiz to a class (§1.6).

    ``rosterSize`` and ``submissionCounts`` are read live at request time —
    never a frozen snapshot (§1.7). ``submissionCounts`` always carries all
    four ``QuizSubmissionStatus`` keys, zero-filled.
    """

    id: str
    classId: str
    className: str
    assignedAt: str
    dueAt: str | None
    closesAt: str | None
    rosterSize: int
    submissionCounts: dict[str, int]


class QuizAssignmentListDTO(ApiModel):
    """Response for ``GET /api/teacher/quizzes/{quiz_id}/assignments``."""

    assignments: list[QuizAssignmentDTO]


class StudentQuizListItemDTO(ApiModel):
    """One row of ``GET /api/student/quizzes``."""

    assignmentId: str
    quizTitle: str
    subjectCode: str
    className: str
    teacherName: str
    assignedAt: str
    dueAt: str | None
    closesAt: str | None
    questionCount: int
    timeLimitMinutes: int | None
    submissionStatus: str
    isOpen: bool
    isOverdue: bool


class StudentQuizListDTO(ApiModel):
    """Response for ``GET /api/student/quizzes``."""

    quizzes: list[StudentQuizListItemDTO]


class StudentQuizQuestionDTO(ApiModel):
    """One question in the take payload (S-26).

    **Never** carries ``modelAnswer``, ``markSchemePoints``, or ``mcqAnswer``
    — there is no field for any of the three anywhere on this model, by
    construction (see ``lemely.db.quiz_taking_repo``'s module docstring).
    """

    id: str
    questionRef: str
    position: int
    topic: str | None
    difficulty: str
    questionType: str
    prompt: str
    totalMarks: int
    mcqOptions: list[str] | None
    answerText: str | None
    workingText: str | None
    answeredAt: str | None


class StudentQuizHeaderDTO(ApiModel):
    """The take payload's header block (S-26)."""

    quizTitle: str
    subjectCode: str
    className: str
    teacherName: str
    dueAt: str | None
    closesAt: str | None
    timeLimitMinutes: int | None
    submissionStatus: str
    isOpen: bool
    isOverdue: bool
    unansweredCount: int


class StudentQuizTakeDTO(ApiModel):
    """Response for ``GET /api/student/quizzes/{assignment_id}``."""

    header: StudentQuizHeaderDTO
    questions: list[StudentQuizQuestionDTO]


class SaveAnswerRequestDTO(ApiModel):
    """Request body for ``PUT /api/student/quizzes/{assignment_id}/answers/{question_ref}``.

    Both fields default to ``None`` (omitted -> the stored value is left
    untouched); pass ``""`` to explicitly clear a field.
    """

    answerText: str | None = None
    workingText: str | None = None


class SaveAnswerResponseDTO(ApiModel):
    """Response for a single answer auto-save."""

    questionRef: str
    answerText: str | None
    workingText: str | None
    answeredAt: str | None


class SubmitQuizResponseDTO(ApiModel):
    """Response for ``POST /api/student/quizzes/{assignment_id}/submit``.

    No marking has happened yet — ``submissionStatus`` is always
    ``"submitted"`` here, never ``"marked"`` (that transition is chunk F's).
    """

    submissionStatus: str
    answeredCount: int
    unansweredCount: int


class QuizPoolCountDTO(ApiModel):
    """Response for ``GET /api/teacher/quizzes/pool-count`` (§2).

    ``byBand`` is the same allocation the builder will use
    (:func:`~lemely.core.difficulty.allocate_difficulty`); ``shortfall`` is
    ``None`` when nothing is short, or a band -> deficit map naming which
    constraint to loosen. ``message`` carries the exact honest-degradation
    wording (D3.7/§2) when ``source=past_paper`` matches zero rows for the
    subject — never a plausible-looking number presented without it.
    """

    matching: int
    requested: int
    byBand: dict[str, int]
    shortfall: dict[str, int] | None = None
    difficultyEstimated: bool = False
    message: str | None = None


__all__ = [
    "CreateQuizAssignmentRequestDTO",
    "CreateQuizRequestDTO",
    "GenerateQuizQuestionsResponseDTO",
    "QuizAssignmentDTO",
    "QuizAssignmentListDTO",
    "QuizDetailDTO",
    "QuizListDTO",
    "QuizPoolCountDTO",
    "QuizQuestionDTO",
    "QuizSummaryDTO",
    "SaveAnswerRequestDTO",
    "SaveAnswerResponseDTO",
    "SetQuizStatusRequestDTO",
    "StudentQuizHeaderDTO",
    "StudentQuizListDTO",
    "StudentQuizListItemDTO",
    "StudentQuizQuestionDTO",
    "StudentQuizTakeDTO",
    "SubmitQuizResponseDTO",
    "UpdateQuizDraftRequestDTO",
]
