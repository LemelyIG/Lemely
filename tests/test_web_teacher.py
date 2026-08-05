"""Tests for the Teacher portal FastAPI endpoints (``lemely.web.routers.teacher``).

No live Gemini: the client is mocked where a route would call it, and the
:class:`HistoryStore` is seeded in a tmp directory. Grading is exercised by
attaching a pre-built :class:`AccuracyReport` to the in-process paper store (the
report-replay path), so no extraction/marking network calls occur. Every
assertion checks a *data-backed* field; structurally-empty fields (retention,
national benchmarks) are asserted empty/None.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from lemely.core.history import PaperRecord, now_iso
from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
    WeakArea,
    WeaknessReport,
)
from lemely.io.gemini import GeminiClient
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import Settings, load_settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_gemini_client,
    get_history_store,
    get_settings,
)
from lemely.web.routers import teacher
from lemely.web.routers.teacher import _PaperEntry, papers_store

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# Every teacher route is staff-gated (P1.6); tests inject a teacher caller.
_TEACHER_AUTH = AuthContext(user_id="teacher-1", role="teacher")

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A Settings instance whose output_dir points at an isolated tmp directory."""
    base = load_settings()
    data = base.model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    return Settings.model_validate(data)


@pytest.fixture
def history_store(settings: Settings) -> HistoryStore:
    """A HistoryStore rooted under the tmp output_dir."""
    return HistoryStore(settings.paths.output_dir / "history")


@pytest.fixture
def gemini_client() -> MagicMock:
    """A mocked GeminiClient — never makes network calls."""
    return MagicMock(spec=GeminiClient)


@pytest.fixture
def client(
    settings: Settings,
    history_store: HistoryStore,
    gemini_client: MagicMock,
) -> Iterator[TestClient]:
    """A TestClient with the shared singletons overridden and the paper store reset."""
    papers_store.clear()
    teacher.registry.clear()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_history_store] = lambda: history_store
    app.dependency_overrides[get_gemini_client] = lambda: gemini_client
    app.dependency_overrides[get_auth_context] = lambda: _TEACHER_AUTH
    yield TestClient(app)
    app.dependency_overrides.clear()
    papers_store.clear()


# ---------------------------------------------------------------------------
# Builders (real core objects — nothing fabricated).
# ---------------------------------------------------------------------------


def _metadata(subject_code: str = "0625", paper_number: int = 3) -> ExamMetadata:
    return ExamMetadata(
        subject_code=subject_code,
        paper_number=paper_number,
        paper_variant=1,
        session_month="May/June",
        session_year=2020,
    )


def _report(
    *,
    awarded: int = 2,
    maximum: int = 4,
    confidence_score: float = 0.6,
    needs_review: bool = True,
    topic: str = "Moments",
    grade: str = "D",
) -> AccuracyReport:
    """Build a real AccuracyReport with one non-MCQ question."""
    question = CorrectedQuestion(
        question_id="5b",
        awarded_marks=awarded,
        maximum_marks=maximum,
        confidence=ConfidenceBand.LOW if needs_review else ConfidenceBand.HIGH,
        confidence_score=confidence_score,
        needs_teacher_review=needs_review,
        marker_source="ai",
        topic=topic,
    )
    correction = CorrectionResult(metadata=_metadata(), questions=[question])
    weaknesses = WeaknessReport(
        weak_areas=[
            WeakArea(
                topic=topic,
                lost_marks=maximum - awarded,
                maximum_marks=maximum,
                accuracy=awarded / maximum,
                question_ids=["5b"],
            )
        ],
        needs_teacher_review=needs_review,
    )
    prediction = GradePrediction(
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=round(awarded / maximum * 100, 2),
        grade=grade,
        confidence=ConfidenceBand.LOW,
        needs_teacher_review=needs_review,
    )
    return AccuracyReport(correction=correction, weaknesses=weaknesses, grade_prediction=prediction)


def _seed_paper(paper_id: str, student_id: str, report: AccuracyReport) -> None:
    papers_store.put(
        _PaperEntry(
            paper_id=paper_id,
            student_id=student_id,
            kind="review" if report.correction.needs_teacher_review else "graded",
            metadata=report.correction.metadata,
            report=report,
        )
    )


def _seed_history_record(
    store: HistoryStore,
    student_id: str,
    *,
    percentage: float,
    grade: str,
    topic: str = "Thermal physics",
    recorded_at: str | None = None,
) -> None:
    """Append one PaperRecord. ``recorded_at`` defaults to *now* (not stale).

    A fixed past date used to be the default here, but the D3.3 at-risk engine
    treats >=14-days-since-last-paper as its own inactivity rule — a hardcoded
    old date would silently make every seeded student inactive under real
    wall-clock time. Callers testing that rule pass ``recorded_at`` explicitly.
    """
    store.append(
        student_id,
        PaperRecord(
            student_id=student_id,
            metadata=_metadata(),
            awarded_marks=int(percentage / 100 * 80),
            maximum_marks=80,
            percentage=percentage,
            grade=grade,
            weak_areas=[
                WeakArea(
                    topic=topic,
                    lost_marks=10,
                    maximum_marks=40,
                    accuracy=0.75,
                    question_ids=["3a"],
                )
            ],
            recorded_at=recorded_at if recorded_at is not None else now_iso(),
        ),
    )


# ---------------------------------------------------------------------------
# Uploads (path traversal / size cap / detection failure).
# ---------------------------------------------------------------------------


def _key_settings(settings: Settings) -> Settings:
    """Return a copy of ``settings`` carrying a dummy API key."""
    from pydantic import SecretStr

    data = settings.model_dump()
    data["gemini_api_key"] = SecretStr("test-key")
    return Settings.model_validate(data)


def test_upload_filename_cannot_escape_sandbox(client: TestClient, settings: Settings) -> None:
    """A traversal filename is sanitised to a basename inside the paper dir."""
    resp = client.post(
        "/api/papers/upload",
        files={"scan": ("../../../../etc/evil.pdf", b"%PDF-1.4 data", "application/pdf")},
        data={"student_id": "jonas"},
    )
    assert resp.status_code == 200
    paper_id = resp.json()["paperId"]

    uploads_root = settings.paths.output_dir / "uploads"
    paper_dir = uploads_root / paper_id
    # The written file is the sanitised basename, inside the paper directory.
    written = list(paper_dir.iterdir())
    assert [p.name for p in written] == ["evil.pdf"]
    # Nothing escaped the uploads sandbox onto disk.
    assert written[0].resolve().parent == paper_dir.resolve()
    assert not (settings.paths.output_dir.parent / "etc" / "evil.pdf").exists()


def test_upload_over_size_cap_is_413(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A scan larger than the module cap is rejected with 413, not written whole."""
    monkeypatch.setattr(teacher, "_MAX_UPLOAD_BYTES", 8)
    resp = client.post(
        "/api/papers/upload",
        files={"scan": ("scan.pdf", b"way too many bytes here", "application/pdf")},
        data={"student_id": "jonas"},
    )
    assert resp.status_code == 413


def test_upload_sets_error_status_on_detection_failure(
    settings: Settings,
    history_store: HistoryStore,
    gemini_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When metadata detection raises, the job status is 'error', not 'done'."""

    def _boom(_client: object) -> object:
        raise RuntimeError("detection exploded")

    monkeypatch.setattr(teacher, "ScanMetadataExtractor", _boom)

    papers_store.clear()
    teacher.registry.clear()
    app = create_app()
    key_settings = _key_settings(settings)
    app.dependency_overrides[get_settings] = lambda: key_settings
    app.dependency_overrides[get_history_store] = lambda: history_store
    app.dependency_overrides[get_gemini_client] = lambda: gemini_client
    app.dependency_overrides[get_auth_context] = lambda: _TEACHER_AUTH
    local = TestClient(app)

    resp = local.post(
        "/api/papers/upload",
        files={"scan": ("scan.pdf", b"%PDF-1.4", "application/pdf")},
        data={"student_id": "jonas"},
    )
    assert resp.status_code == 200
    job_id = resp.json()["jobId"]
    assert teacher.registry.get(job_id).status == "error"

    app.dependency_overrides.clear()
    papers_store.clear()


# ---------------------------------------------------------------------------
# Grading console.
# ---------------------------------------------------------------------------


def test_list_papers_empty(client: TestClient) -> None:
    """With no papers, the grid is empty and every tab count is zero."""
    body = client.get("/api/papers").json()
    assert body["papers"] == []
    counts = {tab["id"]: tab["count"] for tab in body["tabs"]}
    assert counts == {"all": "0", "review": "0", "graded": "0", "processing": "0"}


def test_list_papers_reports_counts(client: TestClient) -> None:
    """Graded/review papers are summarised with data-backed marks and tab counts."""
    _seed_paper("p1", "amelia", _report(needs_review=False, grade="A"))
    _seed_paper("p2", "jonas", _report(needs_review=True, grade="D"))

    body = client.get("/api/papers").json()
    assert len(body["papers"]) == 2
    by_id = {p["id"]: p for p in body["papers"]}
    assert by_id["p1"]["kind"] == "graded"
    assert by_id["p1"]["awardedMarks"] == 2
    assert by_id["p1"]["maxMarks"] == 4
    assert by_id["p2"]["kind"] == "review"
    assert by_id["p2"]["needsReview"] is True

    counts = {tab["id"]: tab["count"] for tab in body["tabs"]}
    assert counts == {"all": "2", "review": "1", "graded": "1", "processing": "0"}


def test_get_paper_detail(client: TestClient) -> None:
    """Paper detail exposes questions, weak areas, pipeline, and detected metadata."""
    _seed_paper("p1", "jonas", _report())
    body = client.get("/api/papers/p1").json()

    assert body["awardedMarks"] == 2
    assert body["maxMarks"] == 4
    assert body["needsReview"] is True
    assert body["questions"][0]["questionId"] == "5b"
    assert body["questions"][0]["markerSource"] == "ai"
    assert body["weakAreas"][0]["topic"] == "Moments"
    # Pipeline is five data-backed steps derived from question counts.
    labels = [s["label"] for s in body["pipeline"]]
    assert labels[0] == "Scan ingested"
    assert len(body["pipeline"]) == 5
    # Detected metadata is derived from the real ExamMetadata.
    detected = {f["key"]: f["value"] for f in body["metadata"]}
    assert detected["Subject code"] == "0625"
    assert detected["Paper"] == "Paper 3"


def test_get_paper_unknown_404(client: TestClient) -> None:
    """An unknown paper id yields 404."""
    assert client.get("/api/papers/nope").status_code == 404


def test_get_paper_ungraded_409(client: TestClient) -> None:
    """A paper without a graded report yields 409 rather than fabricating a grade."""
    papers_store.put(_PaperEntry(paper_id="p9", student_id="lina", kind="queued"))
    assert client.get("/api/papers/p9").status_code == 409


def test_grading_queue_flags_low_confidence(client: TestClient) -> None:
    """The queue surfaces low-confidence questions, sorted ascending by confidence."""
    _seed_paper("p1", "jonas", _report(confidence_score=0.78, needs_review=True))
    _seed_paper("p2", "daniel", _report(confidence_score=0.61, needs_review=True))
    # A high-confidence, no-review paper must NOT appear.
    _seed_paper("p3", "amelia", _report(confidence_score=0.99, needs_review=False))

    rows = client.get("/api/grading/queue").json()["rows"]
    assert [r["name"] for r in rows] == ["daniel", "jonas"]
    assert rows[0]["confidence"] == 0.61
    assert rows[0]["questionId"] == "5b"
    assert rows[0]["topic"] == "Moments"


def test_grade_replays_and_persists(client: TestClient, history_store: HistoryStore) -> None:
    """POST /grade replays MARKING_PROGRESS and appends a PaperRecord to history."""
    _seed_paper("p1", "jonas", _report(grade="D"))

    with client.stream("POST", "/api/papers/p1/grade") as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())

    frames = [f for f in text.split("\n\n") if f.strip()]
    assert frames[-1] == "data: [DONE]"
    assert any('"type": "marking_progress"' in f for f in frames)

    records = history_store.load("jonas").records
    assert len(records) == 1
    assert records[0].grade == "D"
    assert records[0].student_id == "jonas"


def test_grade_unknown_paper_404(client: TestClient) -> None:
    """Grading an unknown paper is a 404 before any streaming begins."""
    assert client.post("/api/papers/nope/grade").status_code == 404


def test_extract_without_scheme_warns(client: TestClient) -> None:
    """Extract on a paper lacking a mark scheme emits a WARNING, never invents data."""
    papers_store.put(_PaperEntry(paper_id="p1", student_id="lina", kind="queued"))
    with client.stream("POST", "/api/papers/p1/extract") as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())
    assert '"type": "warning"' in text
    assert text.rstrip().endswith("data: [DONE]")


# ---------------------------------------------------------------------------
# Mark schemes.
# ---------------------------------------------------------------------------


def test_schemes_empty(client: TestClient) -> None:
    """No parsed schemes on disk → empty list with zeroed parsed/failed stats."""
    body = client.get("/api/schemes").json()
    assert body["schemes"] == []
    stats = {s["key"]: s["value"] for s in body["stats"]}
    assert stats["Parsed"] == "0"
    assert stats["Failed"] == "0"


def test_schemes_lists_parsed(client: TestClient, settings: Settings) -> None:
    """A parsed MarkScheme JSON on disk is surfaced with data-backed row fields."""
    from lemely.core.loose_schemas import (
        AnswerPoint,
        MarkScheme,
        MarkSchemeMetadata,
        PaperType,
        Question,
        QuestionType,
        SchemeFormat,
        SessionMonth,
    )

    scheme = MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code="0625",
            paper_number=3,
            paper_variant=1,
            session_month=SessionMonth.MAY_JUNE,
            session_year=2020,
            paper_type=PaperType.THEORY_CORE,
            maximum_mark=80,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            Question(
                id="1",
                marks=2,
                type=QuestionType.RECALL,
                answer_points=[AnswerPoint(id="p1", point="correct", marks=2)],
            )
        ],
    )
    schemes_dir = settings.paths.output_dir / "schemes"
    schemes_dir.mkdir(parents=True, exist_ok=True)
    (schemes_dir / "0625_s20_ms_31.json").write_text(
        scheme.model_dump_json(indent=2), encoding="utf-8"
    )

    body = client.get("/api/schemes").json()
    assert len(body["schemes"]) == 1
    row = body["schemes"][0]
    assert row["doc"] == "0625_s20_ms_31.json"
    assert row["paper"] == "Paper 3 V1"
    assert row["session"] == "May/June 2020"
    assert row["maxMarks"] == 80
    assert row["questionCount"] == 1
    assert row["status"] == "parsed"
    stats = {s["key"]: s["value"] for s in body["stats"]}
    assert stats["Parsed"] == "1"


# ---------------------------------------------------------------------------
# AI quizzes.
# ---------------------------------------------------------------------------


def test_quiz_pools_counts_from_disk(client: TestClient, settings: Settings) -> None:
    """Pool counts reflect real question files on disk (past vs. mine vs. ai)."""
    from lemely.core.generation import GeneratedQuestion, GeneratedQuiz

    pool_dir = settings.paths.output_dir / "questions"
    pool_dir.mkdir(parents=True, exist_ok=True)
    quiz = GeneratedQuiz(
        subject_code="0625",
        questions=[
            GeneratedQuestion(
                topic="Thermal",
                difficulty="standard",
                prompt="Q with source",
                model_answer="a",
                mark_scheme_points=["p"],
                total_marks=2,
                source_question_ids=["0625/41 Q3"],
            ),
            GeneratedQuestion(
                topic="Waves",
                difficulty="standard",
                prompt="Q without source",
                model_answer="b",
                mark_scheme_points=["p"],
                total_marks=1,
                source_question_ids=[],
            ),
        ],
    )
    (pool_dir / "pool.json").write_text(quiz.model_dump_json(), encoding="utf-8")

    pools = {p["key"]: p for p in client.get("/api/quizzes/pools").json()["pools"]}
    assert pools["past"]["count"] == 1
    assert pools["mine"]["count"] == 1
    assert pools["ai"]["count"] == 0


def test_quiz_topics_from_history(client: TestClient, history_store: HistoryStore) -> None:
    """Quiz topics are derived from aggregate history weaknesses; none pre-selected."""
    _seed_history_record(
        history_store, "amelia", percentage=60.0, grade="C", topic="Thermal physics"
    )
    topics = client.get("/api/quizzes/topics").json()["topics"]
    assert topics
    assert topics[0]["topic"] == "Thermal physics"
    assert topics[0]["marksLost"] == 10
    assert all(t["selected"] is False for t in topics)


def test_quiz_preview_selects_existing_without_gemini(
    client: TestClient, settings: Settings, gemini_client: MagicMock
) -> None:
    """Preview selects existing questions and never calls Gemini when count is met."""
    from lemely.core.generation import GeneratedQuestion, GeneratedQuiz

    pool_dir = settings.paths.output_dir / "questions"
    pool_dir.mkdir(parents=True, exist_ok=True)
    quiz = GeneratedQuiz(
        subject_code="0625",
        questions=[
            GeneratedQuestion(
                topic="Thermal",
                difficulty="standard",
                prompt="Existing Q",
                model_answer="a",
                mark_scheme_points=["p"],
                total_marks=2,
                source_question_ids=["src1"],
            ),
        ],
    )
    (pool_dir / "pool.json").write_text(quiz.model_dump_json(), encoding="utf-8")

    body = client.post("/api/quizzes/preview?subject_code=0625&count=1").json()
    assert body["subjectCode"] == "0625"
    assert len(body["questions"]) == 1
    assert body["questions"][0]["source"] == "existing"
    assert body["estMinutes"] == round(1 * 2.5)  # 2 marks, ~2.5 min/question
    gemini_client.generate_structured.assert_not_called()


def test_quiz_preview_without_key_returns_pool_not_500(
    client: TestClient, settings: Settings, gemini_client: MagicMock
) -> None:
    """With no API key and a shortfall, preview returns pool questions, never 500.

    Regression for the Gemini-absent HIGH item: the default no-key state must not
    attempt generation (which would raise → 500). The one existing question is
    still returned; the AI top-up is silently skipped.
    """
    from lemely.core.generation import GeneratedQuestion, GeneratedQuiz

    pool_dir = settings.paths.output_dir / "questions"
    pool_dir.mkdir(parents=True, exist_ok=True)
    quiz = GeneratedQuiz(
        subject_code="0625",
        questions=[
            GeneratedQuestion(
                topic="Thermal",
                difficulty="standard",
                prompt="Existing Q",
                model_answer="a",
                mark_scheme_points=["p"],
                total_marks=2,
                source_question_ids=["src1"],
            ),
        ],
    )
    (pool_dir / "pool.json").write_text(quiz.model_dump_json(), encoding="utf-8")

    # count=5 > 1 existing → a shortfall that would normally trigger generation.
    resp = client.post("/api/quizzes/preview?subject_code=0625&count=5")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["questions"]) == 1
    assert body["questions"][0]["source"] == "existing"
    gemini_client.generate_structured.assert_not_called()


def test_quiz_generate_without_key_returns_pool_not_500(
    client: TestClient, settings: Settings, gemini_client: MagicMock
) -> None:
    """generate with no key + shortfall returns pool questions (non-500)."""
    from lemely.core.generation import GeneratedQuestion, GeneratedQuiz

    pool_dir = settings.paths.output_dir / "questions"
    pool_dir.mkdir(parents=True, exist_ok=True)
    quiz = GeneratedQuiz(
        subject_code="0625",
        questions=[
            GeneratedQuestion(
                topic="Thermal",
                difficulty="standard",
                prompt="Existing Q",
                model_answer="a",
                mark_scheme_points=["p"],
                total_marks=2,
                source_question_ids=["src1"],
            ),
        ],
    )
    (pool_dir / "pool.json").write_text(quiz.model_dump_json(), encoding="utf-8")

    resp = client.post("/api/quizzes/generate?subject_code=0625&count=5")
    assert resp.status_code == 200
    assert len(resp.json()["questions"]) == 1
    gemini_client.generate_structured.assert_not_called()


# ---------------------------------------------------------------------------
# Classes.
#
# P3.1/D3.1 replaced the implicit ``"all"`` cohort these two endpoints used to
# serve (every student with *any* history, treated as one fake class) with the
# real DB-backed class model. The three tests that lived here
# (``test_classes_empty``, ``test_classes_summary_from_history``,
# ``test_class_detail_distribution_and_roster``) asserted exactly that
# implicit behaviour — an empty store meaning "no classes" and *every* student
# with history appearing in a single synthetic "All students" class — which is
# now the cross-tenant leak D1.6 flagged as the outstanding gap. That
# behaviour no longer exists (a class is only ever the teacher's *real*,
# explicitly-enrolled roster), so those three assertions are obsolete rather
# than something to rewrite in place; they are superseded by:
#   * tests/test_class_repo.py — ClassService ownership/roster/enrolment
#     logic against real Postgres.
#   * tests/test_web_classes.py — the same GET /api/teacher/classes and
#     GET /api/classes/{id} HTTP paths this file used to cover, now exercised
#     against a real teacher-owned class with a real enrolled roster,
#     including the regression that matters most here: a student with history
#     but NOT enrolled in the class must not appear in it.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Overview.
# ---------------------------------------------------------------------------


def test_overview_empty(client: TestClient) -> None:
    """Empty history yields zeroed stats, no at-risk students, and empty retention."""
    body = client.get("/api/teacher/overview").json()
    assert body["atRisk"] == []
    assert body["retention"] == []  # structurally-empty: no backend source
    stats = {s["key"]: s["value"] for s in body["stats"]}
    assert stats["Papers graded"] == "0"


def test_overview_flags_at_risk(client: TestClient, history_store: HistoryStore) -> None:
    """A student on a declining trend (D3.3 rule 1) appears in at-risk; a stable one does not."""
    _seed_history_record(history_store, "ziad", percentage=72.0, grade="B")
    _seed_history_record(history_store, "ziad", percentage=65.0, grade="C")
    _seed_history_record(history_store, "ziad", percentage=58.0, grade="D")
    _seed_history_record(history_store, "amelia", percentage=90.0, grade="A")

    body = client.get("/api/teacher/overview").json()
    at_risk_names = {s["name"] for s in body["atRisk"]}
    assert "ziad" in at_risk_names
    assert "amelia" not in at_risk_names
    stats = {s["key"]: s["value"] for s in body["stats"]}
    assert stats["Papers graded"] == "4"
    assert stats["Group mean"] == "74"  # round((58 + 90) / 2), latest paper per student
    assert body["retention"] == []


def test_overview_at_risk_carries_reason_and_evidence(
    client: TestClient, history_store: HistoryStore
) -> None:
    """The at-risk DTO surfaces the D3.3 reason label and structured evidence, not a bare badge."""
    _seed_history_record(history_store, "ziad", percentage=72.0, grade="B")
    _seed_history_record(history_store, "ziad", percentage=65.0, grade="C")
    _seed_history_record(history_store, "ziad", percentage=58.0, grade="D")

    body = client.get("/api/teacher/overview").json()
    ziad = next(s for s in body["atRisk"] if s["name"] == "ziad")
    assert len(ziad["flags"]) == 1
    flag = ziad["flags"][0]
    assert flag["reason"] == "declining_trend"
    assert flag["summary"]  # human-readable, not an unexplained badge (spec 1.4)
    assert flag["evidence"]["percentages"] == [72.0, 65.0, 58.0]


def test_overview_flags_inactive_student(client: TestClient, history_store: HistoryStore) -> None:
    """A student inactive >=14 days (D3.3 rule 3) is flagged even with a strong last grade."""
    from datetime import UTC, datetime, timedelta

    stale = (datetime.now(UTC) - timedelta(days=20)).isoformat()
    _seed_history_record(history_store, "priya", percentage=95.0, grade="A*", recorded_at=stale)

    body = client.get("/api/teacher/overview").json()
    priya = next(s for s in body["atRisk"] if s["name"] == "priya")
    assert priya["flags"][0]["reason"] == "inactive"
    assert priya["flags"][0]["evidence"]["daysInactive"] >= 20
