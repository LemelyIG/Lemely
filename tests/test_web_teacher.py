"""Tests for the Teacher portal FastAPI endpoints (``lemely.web.routers.teacher``).

No live Gemini: the client is mocked where a route would call it, and the
:class:`HistoryStore` is seeded in a tmp directory. Grading is exercised by
attaching a pre-built :class:`AccuracyReport` to the in-process paper store (the
report-replay path), so no extraction/marking network calls occur. Every
assertion checks a *data-backed* field; structurally-empty fields (retention,
national benchmarks) are asserted empty/None.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.history import PaperRecord, StudentHistory, now_iso
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
from lemely.db.at_risk_repo import AtRiskAckService
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import User
from lemely.db.models.enums import DifficultySource, QuestionDifficulty, QuestionSource, Role
from lemely.db.models.quizzes import QuestionBank
from lemely.db.question_bank_repo import QuestionBankService
from lemely.io.gemini import GeminiClient
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import DatabaseSettings, Settings, load_settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_at_risk_ack_service,
    get_auth_context,
    get_class_service,
    get_gemini_client,
    get_history_store,
    get_question_bank_service,
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
# Postgres-backed fixtures for routes needing the real class model (P3.3:
# overview scoping, student detail, at-risk list). Self-contained (mirrors
# ``tests/test_web_classes.py``/``tests/test_class_repo.py``) rather than
# shared via conftest, so only the tests that request these fixtures pay the
# Postgres-reachability cost — every other test in this file stays DB-free.
# ---------------------------------------------------------------------------


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    """A sessionmaker bound to a throwaway Postgres DB; skips if unreachable."""
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


@pytest.fixture
def bank_service(pg_sessionmaker: sessionmaker[Session]) -> QuestionBankService:
    return QuestionBankService(pg_sessionmaker)


@pytest.fixture
def ack_service(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> AtRiskAckService:
    return AtRiskAckService(pg_sessionmaker, class_service)


def _seed_user(sm: sessionmaker[Session], role: Role, display_name: str | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _seed_bank_row(
    sm: sessionmaker[Session],
    *,
    subject_code: str,
    difficulty: QuestionDifficulty = QuestionDifficulty.standard,
    owner_id: uuid.UUID | None = None,
    source: QuestionSource = QuestionSource.generated,
    difficulty_source: DifficultySource = DifficultySource.declared_by_generator,
    prompt: str = "A dummy prompt",
    source_question_ids: list[str] | None = None,
) -> uuid.UUID:
    from lemely.db.models.enums import ExamBoard

    row_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            QuestionBank(
                id=row_id,
                board=ExamBoard.caie,
                subject_code=subject_code,
                source=source,
                owner_id=owner_id,
                difficulty=difficulty,
                difficulty_source=difficulty_source,
                question_type="explanation",
                prompt=prompt,
                total_marks=2,
                source_question_ids=source_question_ids or [],
            )
        )
    return row_id


def _use_bank_service(client: TestClient, bank_service: QuestionBankService) -> None:
    """Override ``get_question_bank_service`` on ``client`` for a real-tenancy test."""
    client.app.dependency_overrides[get_question_bank_service] = lambda: bank_service  # type: ignore[union-attr]


def _use_class_service(client: TestClient, class_service: ClassService) -> None:
    """Override ``get_class_service`` on ``client`` for a real-tenancy test.

    Also wires ``get_at_risk_ack_service`` to an :class:`AtRiskAckService`
    bound to the *same* throwaway Postgres database/``ClassService`` (P3.4b) —
    every at-risk-serving route (overview, student detail, at-risk list) now
    depends on it too, since D3.5 requires each to populate the acknowledged
    state. Reaching into ``class_service``'s private sessionmaker keeps every
    existing call site of this helper working unchanged rather than needing a
    second override call threaded through 15+ pre-existing tests.
    """
    client.app.dependency_overrides[get_class_service] = lambda: class_service  # type: ignore[union-attr]
    client.app.dependency_overrides[get_at_risk_ack_service] = lambda: AtRiskAckService(
        class_service._sessionmaker,
        class_service,
    )


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    """Override ``get_auth_context`` on ``client`` to authenticate as ``user_id``."""
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


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
    question_ids: tuple[str, ...] = ("5b",),
) -> AccuracyReport:
    """Build a real AccuracyReport with one non-MCQ question per id in ``question_ids``.

    ``awarded``/``maximum`` are per question; the report-level totals are scaled
    by the question count so a multi-question report stays internally consistent
    (a paper whose parts sum to more than its own total would be fabricated
    data, and the grading console reads both). The single-question default is
    unchanged — every scaling factor is 1 — so existing callers see the same
    object they always did.
    """
    questions = [
        CorrectedQuestion(
            question_id=question_id,
            awarded_marks=awarded,
            maximum_marks=maximum,
            confidence=ConfidenceBand.LOW if needs_review else ConfidenceBand.HIGH,
            confidence_score=confidence_score,
            needs_teacher_review=needs_review,
            marker_source="ai",
            topic=topic,
        )
        for question_id in question_ids
    ]
    count = len(question_ids)
    correction = CorrectionResult(metadata=_metadata(), questions=questions)
    weaknesses = WeaknessReport(
        weak_areas=[
            WeakArea(
                topic=topic,
                lost_marks=(maximum - awarded) * count,
                maximum_marks=maximum * count,
                accuracy=awarded / maximum,
                question_ids=list(question_ids),
            )
        ],
        needs_teacher_review=needs_review,
    )
    prediction = GradePrediction(
        awarded_marks=awarded * count,
        maximum_marks=maximum * count,
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
    origin: str = "past_paper",
) -> None:
    """Append one PaperRecord. ``recorded_at`` defaults to *now* (not stale).

    A fixed past date used to be the default here, but the D3.3 at-risk engine
    treats >=14-days-since-last-paper as its own inactivity rule — a hardcoded
    old date would silently make every seeded student inactive under real
    wall-clock time. Callers testing that rule pass ``recorded_at`` explicitly.

    ``origin`` (added P3.7 chunk a) lets a caller seed a ``quiz`` record —
    the marking path always writes ``grade=""`` for one (D3.9), so a caller
    testing the quiz-has-no-grade case should also pass ``grade=""``.
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
            origin=origin,  # type: ignore[arg-type]
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


def test_upload_with_mark_scheme_grades_instead_of_stalling_at_queued(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan uploaded *with* a mark scheme grades end to end.

    The regression this pins: ``upload_paper`` used to write the scheme PDF to
    disk under the teacher's own filename and then build the ``_PaperEntry``
    without a ``mark_scheme=``, so ``entry.mark_scheme`` was ``None`` for every
    uploaded paper. ``grade_paper_endpoint``'s marking branch was therefore
    unreachable, it fell through to the "No mark scheme or graded correction
    attached" warning, ``entry.kind`` was never reassigned, and the console sat
    on "Queued / 0 auto-graded / N processing" forever.

    Every pre-existing grade test seeded ``papers_store`` with a hand-built
    entry that already carried a ``report``, which is exactly why a green suite
    never noticed. This one goes through the HTTP upload route, as a teacher
    does.
    """
    from lemely.web.routers import student as student_router
    from lemely.web.services import grading as grading_service

    report = _report(needs_review=False, grade="A")
    scheme = object()
    marked_with: dict[str, object] = {}

    monkeypatch.setattr(student_router, "resolve_mark_scheme", lambda *_a, **_k: scheme)
    monkeypatch.setattr(grading_service, "extract_answers", lambda *_a, **_k: {"5b": "42"})

    def _grade(mark_scheme: object, _extracted: object, **_kwargs: object) -> AccuracyReport:
        marked_with["scheme"] = mark_scheme
        return report

    monkeypatch.setattr(grading_service, "grade_paper", _grade)

    resp = client.post(
        "/api/papers/upload",
        files={
            "scan": ("scan.pdf", b"%PDF-1.4 scan", "application/pdf"),
            # A realistic teacher filename: nothing like "mark_scheme.pdf".
            "mark_scheme": ("0625_s20_ms_31.pdf", b"%PDF-1.4 scheme", "application/pdf"),
        },
    )
    assert resp.status_code == 200
    paper_id = resp.json()["paperId"]

    # Saved under the fixed sibling name `resolve_mark_scheme` looks for, not
    # the client basename — otherwise the resolver could never find it.
    entry = papers_store.get(paper_id)
    assert entry is not None
    assert entry.scan_path is not None
    assert (entry.scan_path.parent / "mark_scheme.pdf").exists()

    with client.stream("POST", f"/api/papers/{paper_id}/grade") as stream:
        text = "".join(stream.iter_text())
    assert "No mark scheme or graded correction attached" not in text

    # The resolved scheme is what actually reached the marker.
    assert marked_with["scheme"] is scheme

    # The paper left the queue, and the console's counters move with it.
    graded = papers_store.get(paper_id)
    assert graded is not None
    assert graded.kind == "graded"
    assert graded.report is report
    counts = {tab["id"]: tab["count"] for tab in client.get("/api/papers").json()["tabs"]}
    assert counts == {"all": "1", "review": "0", "graded": "1", "processing": "0"}


def test_grade_reports_worker_failure_as_an_error_frame(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash inside the grading worker is named, not swallowed into silence.

    ``bus_event_stream`` runs ``run()`` on a bare thread it never inspects, and
    the ``finally`` publishes DONE regardless — so before this, an exception
    closed the stream cleanly with nothing said, which looks identical to the
    stuck-at-queued bug above but has a completely different cause.
    """
    from lemely.web.routers import student as student_router
    from lemely.web.services import grading as grading_service

    def _boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("gemini exploded")

    monkeypatch.setattr(student_router, "resolve_mark_scheme", lambda *_a, **_k: object())
    monkeypatch.setattr(grading_service, "extract_answers", _boom)

    resp = client.post(
        "/api/papers/upload",
        files={
            "scan": ("scan.pdf", b"%PDF-1.4 scan", "application/pdf"),
            "mark_scheme": ("ms.pdf", b"%PDF-1.4 scheme", "application/pdf"),
        },
    )
    paper_id = resp.json()["paperId"]

    with client.stream("POST", f"/api/papers/{paper_id}/grade") as stream:
        text = "".join(stream.iter_text())

    assert '"type": "error"' in text
    assert "gemini exploded" in text


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


def test_grade_replay_frames_carry_the_per_question_counter(client: TestClient) -> None:
    """Replayed MARKING_PROGRESS frames number questions 1..N against a constant N.

    The replay path is what the UI gets for an already-graded paper, so its
    counter has to read exactly like a live marking run's: same 1-based index,
    same constant total, same order. Otherwise the same paper appears to contain
    a different number of questions depending on which path happened to serve
    it. ``index`` is the enumerate position in the cached list — not a tally of
    frames sent — so a question skipped mid-replay would leave a gap rather than
    renumber the ones after it.
    """
    _seed_paper("p1", "jonas", _report(question_ids=("1", "2(a)", "2(b)")))

    with client.stream("POST", "/api/papers/p1/grade") as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())

    frames = [
        json.loads(f.removeprefix("data: "))
        for f in text.split("\n\n")
        if f.strip() and f != "data: [DONE]"
    ]
    marking = [f for f in frames if f["type"] == "marking_progress"]
    assert [f["question_id"] for f in marking] == ["1", "2(a)", "2(b)"]
    assert [f["index"] for f in marking] == [1, 2, 3]
    assert {f["total"] for f in marking} == {3}
    # The counter's total must match the questions the paper really has — the
    # number the grading console shows next to this same report.
    assert len(marking) == len(client.get("/api/papers/p1").json()["questions"])


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


def test_quiz_pools_counts_from_bank(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    bank_service: QuestionBankService,
) -> None:
    """Pool counts reflect the bank (past/mine/ai), not the on-disk scan.

    D3.6 §2: ``/quizzes/pools`` moved off ``output_dir/questions`` onto
    :class:`QuestionBankService` (chunk D). ``mine`` counts this teacher's
    own ``teacher_upload`` rows; ``ai`` counts visible ``generated`` rows
    (platform-shared here); ``past`` counts visible ``past_paper`` rows.
    """
    _use_class_service(client, class_service)
    _use_bank_service(client, bank_service)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _auth_as(client, teacher, Role.teacher)

    _seed_bank_row(pg_sessionmaker, subject_code="0625", source=QuestionSource.past_paper)
    _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625",
        source=QuestionSource.teacher_upload,
        owner_id=teacher,
    )
    _seed_bank_row(pg_sessionmaker, subject_code="0625", source=QuestionSource.generated)

    pools = {
        p["key"]: p for p in client.get("/api/quizzes/pools?subject_code=0625").json()["pools"]
    }
    assert pools["past"]["count"] == 1
    assert pools["mine"]["count"] == 1
    assert pools["ai"]["count"] == 1


def test_quiz_pools_past_paper_honest_zero_message(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    bank_service: QuestionBankService,
) -> None:
    """A subject with no indexed past-paper rows says so in D3.7's exact words."""
    _use_class_service(client, class_service)
    _use_bank_service(client, bank_service)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _auth_as(client, teacher, Role.teacher)

    pools = {
        p["key"]: p
        for p in client.get("/api/quizzes/pools?subject_code=0625-empty").json()["pools"]
    }
    assert pools["past"]["count"] == 0
    assert "no past-paper questions indexed for 0625-empty" in pools["past"]["detail"].lower()
    assert "use generated questions" in pools["past"]["detail"].lower()


def test_quiz_pools_two_teacher_isolation(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    bank_service: QuestionBankService,
) -> None:
    """Teacher A must never see teacher B's uploaded questions in ``mine`` (D3.6 §2).

    The pre-chunk-D behaviour scanned a process-global disk directory, so
    every teacher saw every other teacher's generated/uploaded questions —
    the leak this chunk closes. Pinned here with two real teachers.
    """
    _use_class_service(client, class_service)
    _use_bank_service(client, bank_service)
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625-iso",
        source=QuestionSource.teacher_upload,
        owner_id=teacher_b,
    )

    _auth_as(client, teacher_a, Role.teacher)
    pools_a = {
        p["key"]: p for p in client.get("/api/quizzes/pools?subject_code=0625-iso").json()["pools"]
    }
    assert pools_a["mine"]["count"] == 0

    _auth_as(client, teacher_b, Role.teacher)
    pools_b = {
        p["key"]: p for p in client.get("/api/quizzes/pools?subject_code=0625-iso").json()["pools"]
    }
    assert pools_b["mine"]["count"] == 1


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
    client: TestClient,
    gemini_client: MagicMock,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    bank_service: QuestionBankService,
) -> None:
    """Preview reuses bank questions and never calls Gemini when count is met.

    The reuse pool moved off ``output_dir/questions`` onto the bank in chunk
    D: nothing writes that directory any more, so a disk-seeded pool would
    make this test assert a path that can no longer fire in production.
    """
    _use_class_service(client, class_service)
    _use_bank_service(client, bank_service)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _auth_as(client, teacher, Role.teacher)

    _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625",
        source=QuestionSource.generated,
        owner_id=teacher,
        prompt="Existing Q",
        source_question_ids=["src1"],
    )

    body = client.post("/api/quizzes/preview?subject_code=0625&count=1").json()
    assert body["subjectCode"] == "0625"
    assert len(body["questions"]) == 1
    assert body["questions"][0]["source"] == "existing"
    assert body["questions"][0]["prompt"] == "Existing Q"
    gemini_client.generate_structured.assert_not_called()


def test_quiz_preview_reuse_pool_is_scoped_to_the_calling_teacher(
    client: TestClient,
    gemini_client: MagicMock,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    bank_service: QuestionBankService,
) -> None:
    """One teacher's generated questions never reach another's preview.

    The old ``output_dir/questions`` scan was process-global — every
    teacher's generated questions fed every other teacher's quiz. Reading
    the bank behind ``visible_bank_filter`` closes that in the
    preview/generate path, not just in ``/quizzes/pools``.
    """
    _use_class_service(client, class_service)
    _use_bank_service(client, bank_service)
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    intruder = _seed_user(pg_sessionmaker, Role.teacher)
    _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625",
        source=QuestionSource.generated,
        owner_id=owner,
        prompt="Owner's private Q",
        source_question_ids=["src1"],
    )

    _auth_as(client, intruder, Role.teacher)
    body = client.post("/api/quizzes/preview?subject_code=0625&count=1").json()
    prompts = [q["prompt"] for q in body["questions"]]
    assert "Owner's private Q" not in prompts

    _auth_as(client, owner, Role.teacher)
    body = client.post("/api/quizzes/preview?subject_code=0625&count=1").json()
    assert [q["prompt"] for q in body["questions"]] == ["Owner's private Q"]
    gemini_client.generate_structured.assert_not_called()


def test_quiz_preview_without_key_returns_pool_not_500(
    client: TestClient,
    gemini_client: MagicMock,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    bank_service: QuestionBankService,
) -> None:
    """With no API key and a shortfall, preview returns pool questions, never 500.

    Regression for the Gemini-absent HIGH item: the default no-key state must not
    attempt generation (which would raise → 500). The one existing question is
    still returned; the AI top-up is silently skipped.
    """
    _use_class_service(client, class_service)
    _use_bank_service(client, bank_service)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _auth_as(client, teacher, Role.teacher)

    _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625",
        source=QuestionSource.generated,
        owner_id=teacher,
        prompt="Existing Q",
        source_question_ids=["src1"],
    )

    # count=5 > 1 existing → a shortfall that would normally trigger generation.
    resp = client.post("/api/quizzes/preview?subject_code=0625&count=5")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["questions"]) == 1
    assert body["questions"][0]["source"] == "existing"
    gemini_client.generate_structured.assert_not_called()


def test_quiz_generate_without_key_returns_pool_not_500(
    client: TestClient,
    gemini_client: MagicMock,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    bank_service: QuestionBankService,
) -> None:
    """generate with no key + shortfall returns pool questions (non-500).

    Also asserts the D3.6/D3.7 write-side change: the resulting question(s)
    are now persisted to the question bank (``source=generated``,
    ``difficulty_source=declared_by_generator``, ``owner_id=`` the calling
    teacher) instead of a JSON file — chunk D moved this write off disk.
    """
    _use_class_service(client, class_service)
    _use_bank_service(client, bank_service)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _auth_as(client, teacher, Role.teacher)

    _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625",
        source=QuestionSource.generated,
        owner_id=teacher,
        prompt="Existing Q",
        source_question_ids=["src1"],
    )

    resp = client.post("/api/quizzes/generate?subject_code=0625&count=5")
    assert resp.status_code == 200
    assert len(resp.json()["questions"]) == 1
    gemini_client.generate_structured.assert_not_called()

    # Still exactly one row: the reused question is not written back into the
    # bank it was read from. An unfiltered write-back would inflate the live
    # pool count on every generate.
    with pg_sessionmaker() as session:
        rows = session.scalars(
            select(QuestionBank).where(QuestionBank.subject_code == "0625")
        ).all()
    assert len(rows) == 1
    assert rows[0].source == QuestionSource.generated
    assert rows[0].difficulty_source == DifficultySource.declared_by_generator
    assert rows[0].owner_id == teacher
    assert rows[0].prompt == "Existing Q"


def test_quiz_generate_repeated_does_not_duplicate_reused_bank_rows(
    client: TestClient,
    gemini_client: MagicMock,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    bank_service: QuestionBankService,
) -> None:
    """Generating twice must not grow the bank by re-inserting reused questions.

    Since the reuse pool now reads the bank, a naive "persist every question
    in the built quiz" would re-insert what it just read, doubling the pool
    on each call. Generated rows carry no ``paper_id``, so the partial
    unique index that makes the past-paper ingest idempotent does not cover
    them — this has to be enforced in the write path.
    """
    _use_class_service(client, class_service)
    _use_bank_service(client, bank_service)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _auth_as(client, teacher, Role.teacher)

    _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625",
        source=QuestionSource.generated,
        owner_id=teacher,
        prompt="Existing Q",
        source_question_ids=["src1"],
    )

    def _bank_count() -> int:
        with pg_sessionmaker() as session:
            return len(
                session.scalars(
                    select(QuestionBank).where(QuestionBank.subject_code == "0625")
                ).all()
            )

    for _ in range(3):
        assert client.post("/api/quizzes/generate?subject_code=0625&count=5").status_code == 200
        assert _bank_count() == 1
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
# Overview (P3.3: scoped to the caller's own classes, real display names —
# fixes the cross-tenant leak where this route called
# ``history_store.list_students()`` for *every* student in the store and named
# at-risk rows from the raw ``history.student_id`` uuid).
# ---------------------------------------------------------------------------


def _join_student(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    join_code: str,
    display_name: str,
) -> uuid.UUID:
    """Seed a student user and enrol them into a class via its join code."""
    student = _seed_user(pg_sessionmaker, Role.student, display_name=display_name)
    class_service.join_by_code(student, join_code)
    return student


def test_overview_empty_for_teacher_with_no_classes(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    """A teacher with no classes gets a coherent empty overview, never a 500."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)

    body = client.get("/api/teacher/overview").json()
    assert body["atRisk"] == []
    assert body["retention"] == []  # structurally-empty: no backend source
    stats = {s["key"]: s["value"] for s in body["stats"]}
    assert stats["Papers graded"] == "0"
    assert stats["At risk"] == "0"


def test_overview_flags_at_risk(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """A student on a declining trend (D3.3 rule 1) appears in at-risk; a stable one does not."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _join_student(pg_sessionmaker, class_service, cls.join_code, "Ziad")
    amelia = _join_student(pg_sessionmaker, class_service, cls.join_code, "Amelia")
    _seed_history_record(history_store, str(ziad), percentage=72.0, grade="B")
    _seed_history_record(history_store, str(ziad), percentage=65.0, grade="C")
    _seed_history_record(history_store, str(ziad), percentage=58.0, grade="D")
    _seed_history_record(history_store, str(amelia), percentage=90.0, grade="A")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    body = client.get("/api/teacher/overview").json()
    at_risk_names = {s["name"] for s in body["atRisk"]}
    # The real display name, never the raw uuid history key (the P3.3 fix).
    assert at_risk_names == {"Ziad"}
    assert "Amelia" not in at_risk_names
    stats = {s["key"]: s["value"] for s in body["stats"]}
    assert stats["Papers graded"] == "4"
    assert stats["Group mean"] == "74"  # round((58 + 90) / 2), latest paper per student
    assert body["retention"] == []


def test_overview_at_risk_carries_reason_and_evidence(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """The at-risk DTO surfaces the D3.3 reason label and structured evidence, not a bare badge."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _join_student(pg_sessionmaker, class_service, cls.join_code, "Ziad")
    _seed_history_record(history_store, str(ziad), percentage=72.0, grade="B")
    _seed_history_record(history_store, str(ziad), percentage=65.0, grade="C")
    _seed_history_record(history_store, str(ziad), percentage=58.0, grade="D")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    body = client.get("/api/teacher/overview").json()
    ziad_row = next(s for s in body["atRisk"] if s["name"] == "Ziad")
    assert len(ziad_row["flags"]) == 1
    flag = ziad_row["flags"][0]
    assert flag["reason"] == "declining_trend"
    assert flag["summary"]  # human-readable, not an unexplained badge (spec 1.4)
    assert flag["evidence"]["percentages"] == [72.0, 65.0, 58.0]


def test_overview_flags_inactive_student(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """A student inactive >=14 days (D3.3 rule 3) is flagged even with a strong last grade."""
    from datetime import UTC, datetime, timedelta

    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    priya = _join_student(pg_sessionmaker, class_service, cls.join_code, "Priya")
    stale = (datetime.now(UTC) - timedelta(days=20)).isoformat()
    _seed_history_record(history_store, str(priya), percentage=95.0, grade="A*", recorded_at=stale)

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    body = client.get("/api/teacher/overview").json()
    priya_row = next(s for s in body["atRisk"] if s["name"] == "Priya")
    assert priya_row["flags"][0]["reason"] == "inactive"
    assert priya_row["flags"][0]["evidence"]["daysInactive"] >= 20


def test_overview_scopes_to_each_teachers_own_classes(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """Two teachers with disjoint classes each see only their own students.

    This is the precise regression P3.3 fixes: the route used to call
    ``history_store.list_students()`` — every student in the store, regardless
    of who owns them — so teacher A would have seen teacher B's students (and
    their at-risk rows) too.
    """
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    class_a = class_service.create_class(teacher_a, "A's class")
    class_b = class_service.create_class(teacher_b, "B's class")
    assert class_a.join_code is not None
    assert class_b.join_code is not None

    student_a = _join_student(pg_sessionmaker, class_service, class_a.join_code, "Student A")
    student_b = _join_student(pg_sessionmaker, class_service, class_b.join_code, "Student B")
    # Student A is declining (at-risk); student B is not.
    _seed_history_record(history_store, str(student_a), percentage=72.0, grade="B")
    _seed_history_record(history_store, str(student_a), percentage=65.0, grade="C")
    _seed_history_record(history_store, str(student_a), percentage=58.0, grade="D")
    _seed_history_record(history_store, str(student_b), percentage=90.0, grade="A")

    _use_class_service(client, class_service)

    _auth_as(client, teacher_a, Role.teacher)
    body_a = client.get("/api/teacher/overview").json()
    stats_a = {s["key"]: s["value"] for s in body_a["stats"]}
    assert stats_a["Papers graded"] == "3"
    assert {s["name"] for s in body_a["atRisk"]} == {"Student A"}

    _auth_as(client, teacher_b, Role.teacher)
    body_b = client.get("/api/teacher/overview").json()
    stats_b = {s["key"]: s["value"] for s in body_b["stats"]}
    assert stats_b["Papers graded"] == "1"
    assert body_b["atRisk"] == []


def test_overview_malformed_caller_id_is_422(
    client: TestClient, class_service: ClassService
) -> None:
    """A token whose ``sub`` is not a UUID must not reach the DB as a 500."""
    _use_class_service(client, class_service)
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id="not-a-uuid", role=Role.teacher.value
    )
    assert client.get("/api/teacher/overview").status_code == 422


# ---------------------------------------------------------------------------
# Recent activity — T-01 item 4 (P3.7 chunk a, D3.12).
# ---------------------------------------------------------------------------

_STUDENT_ID = "3f6c1b0e-6f5e-4b0a-9f3e-2c1d0a7b8e91"


def test_overview_recent_activity_spans_papers_and_quizzes(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """``recentActivity`` includes both a past paper and a quiz, newest first."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _join_student(pg_sessionmaker, class_service, cls.join_code, "Ziad")
    _seed_history_record(
        history_store,
        str(ziad),
        percentage=80.0,
        grade="B",
        recorded_at="2026-08-01T10:00:00+00:00",
    )
    _seed_history_record(
        history_store,
        str(ziad),
        percentage=40.0,
        grade="",
        origin="quiz",
        recorded_at="2026-08-02T10:00:00+00:00",
    )

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    body = client.get("/api/teacher/overview").json()
    activity = body["recentActivity"]
    assert len(activity) == 2
    # Newest first: the quiz (Aug 2) before the paper (Aug 1).
    assert activity[0]["origin"] == "quiz"
    assert activity[0]["studentName"] == "Ziad"
    assert activity[0]["studentId"] == str(ziad)
    assert activity[0]["percentage"] == 40.0
    assert activity[1]["origin"] == "past_paper"
    assert activity[1]["grade"] == "B"


def test_overview_recent_activity_quiz_grade_is_null_not_last_paper_grade() -> None:
    """A quiz's ``grade`` must be ``None``, never the student's last *paper* grade.

    This is the exact mistake D3.9 exists to prevent: a quiz has no grade,
    and substituting the student's most recent paper grade would misattribute
    someone else's evidence (a different assessment, a different date) to
    this submission.
    """
    from lemely.web.routers.teacher import _recent_activity

    history = StudentHistory(
        student_id=_STUDENT_ID,
        records=[
            PaperRecord(
                student_id=_STUDENT_ID,
                metadata=_metadata(),
                awarded_marks=64,
                maximum_marks=80,
                percentage=80.0,
                grade="B",
                weak_areas=[],
                recorded_at="2026-08-01T10:00:00+00:00",
                origin="past_paper",
            ),
            PaperRecord(
                student_id=_STUDENT_ID,
                metadata=_metadata(),
                awarded_marks=4,
                maximum_marks=10,
                percentage=40.0,
                grade="",
                weak_areas=[],
                recorded_at="2026-08-02T10:00:00+00:00",
                origin="quiz",
            ),
        ],
    )

    activity = _recent_activity([(history, "Ziad")])

    assert len(activity) == 2
    quiz_entry = next(a for a in activity if a.origin == "quiz")
    assert quiz_entry.grade is None
    paper_entry = next(a for a in activity if a.origin == "past_paper")
    assert paper_entry.grade == "B"


def test_overview_recent_activity_is_capped_and_sorted_newest_first() -> None:
    """More than the cap: only the ``limit`` newest records survive, in order."""
    from lemely.web.routers.teacher import _recent_activity

    records = [
        PaperRecord(
            student_id=_STUDENT_ID,
            metadata=_metadata(),
            awarded_marks=i,
            maximum_marks=10,
            percentage=float(i * 10),
            grade="B",
            weak_areas=[],
            recorded_at=f"2026-08-{i:02d}T10:00:00+00:00",
            origin="past_paper",
        )
        for i in range(1, 11)
    ]
    history = StudentHistory(student_id=_STUDENT_ID, records=records)

    activity = _recent_activity([(history, "Ziad")], limit=8)

    assert len(activity) == 8
    assert [a.recordedAt for a in activity] == sorted(
        (r.recorded_at for r in records), reverse=True
    )[:8]


def test_overview_recent_activity_scopes_to_each_teachers_own_classes(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """Two teachers with disjoint classes: neither's recent activity leaks to the other."""
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    class_a = class_service.create_class(teacher_a, "A's class")
    class_b = class_service.create_class(teacher_b, "B's class")
    assert class_a.join_code is not None
    assert class_b.join_code is not None
    student_a = _join_student(pg_sessionmaker, class_service, class_a.join_code, "Student A")
    student_b = _join_student(pg_sessionmaker, class_service, class_b.join_code, "Student B")
    _seed_history_record(history_store, str(student_a), percentage=80.0, grade="B")
    _seed_history_record(history_store, str(student_b), percentage=90.0, grade="A")

    _use_class_service(client, class_service)

    _auth_as(client, teacher_a, Role.teacher)
    body_a = client.get("/api/teacher/overview").json()
    names_a = {a["studentName"] for a in body_a["recentActivity"]}
    assert names_a == {"Student A"}

    _auth_as(client, teacher_b, Role.teacher)
    body_b = client.get("/api/teacher/overview").json()
    names_b = {a["studentName"] for a in body_b["recentActivity"]}
    assert names_b == {"Student B"}


# ---------------------------------------------------------------------------
# Student detail (teacher view) — T-05 (P3.3).
# ---------------------------------------------------------------------------


def test_student_detail_happy_path_payload_shape(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    student = _join_student(pg_sessionmaker, class_service, cls.join_code, "Amelia")
    _seed_history_record(history_store, str(student), percentage=72.0, grade="B")
    _seed_history_record(history_store, str(student), percentage=90.0, grade="A")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    resp = client.get(f"/api/teacher/students/{student}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["studentId"] == str(student)
    assert body["displayName"] == "Amelia"
    assert len(body["attempts"]) == 2
    # Newest first.
    assert body["attempts"][0]["grade"] == "A"
    assert body["subjects"][0]["predictedGrade"] == "A"
    assert body["subjects"][0]["paperCount"] == 2
    assert len(body["trend"]) == 2
    assert body["engagement"]["totalPapers"] == 2
    assert body["engagement"]["daysSinceLastSubmission"] == 0
    assert "integrity" not in body  # deliberately omitted: no backend source (P3.3)


def test_student_detail_carries_at_risk_status(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    student = _join_student(pg_sessionmaker, class_service, cls.join_code, "Ziad")
    _seed_history_record(history_store, str(student), percentage=72.0, grade="B")
    _seed_history_record(history_store, str(student), percentage=65.0, grade="C")
    _seed_history_record(history_store, str(student), percentage=58.0, grade="D")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    body = client.get(f"/api/teacher/students/{student}").json()
    assert body["isAtRisk"] is True
    assert body["atRiskFlags"][0]["reason"] == "declining_trend"


def test_student_detail_unenrolled_student_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    """A real user who is simply not in any of the caller's classes -> 403."""
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    class_b = class_service.create_class(teacher_b, "B's class")
    assert class_b.join_code is not None
    other_teachers_student = _join_student(
        pg_sessionmaker, class_service, class_b.join_code, "Not Mine"
    )

    _use_class_service(client, class_service)
    _auth_as(client, teacher_a, Role.teacher)
    resp = client.get(f"/api/teacher/students/{other_teachers_student}")
    assert resp.status_code == 403
    assert "Not Mine" not in resp.text


def test_student_detail_unknown_id_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    """An id matching no user anywhere is a 404, distinct from "not my student"."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    resp = client.get(f"/api/teacher/students/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_student_detail_malformed_id_is_4xx_not_500(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    resp = client.get("/api/teacher/students/not-a-uuid")
    assert 400 <= resp.status_code < 500


def test_student_detail_platform_admin_gets_403_no_super_role_bypass(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    """platform_admin sees no classes (D1.6/D1.10), so every student is 403 for them."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    admin_id = _seed_user(pg_sessionmaker, Role.platform_admin)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    student = _join_student(pg_sessionmaker, class_service, cls.join_code, "Amelia")

    _use_class_service(client, class_service)
    _auth_as(client, admin_id, Role.platform_admin)
    resp = client.get(f"/api/teacher/students/{student}")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# At-risk list — T-06 (P3.3).
# ---------------------------------------------------------------------------


def test_at_risk_list_happy_path(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _join_student(pg_sessionmaker, class_service, cls.join_code, "Ziad")
    amelia = _join_student(pg_sessionmaker, class_service, cls.join_code, "Amelia")
    _seed_history_record(history_store, str(ziad), percentage=72.0, grade="B")
    _seed_history_record(history_store, str(ziad), percentage=65.0, grade="C")
    _seed_history_record(history_store, str(ziad), percentage=58.0, grade="D")
    _seed_history_record(history_store, str(amelia), percentage=90.0, grade="A")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    body = client.get("/api/teacher/at-risk").json()
    names = {s["displayName"] for s in body["students"]}
    assert names == {"Ziad"}
    row = next(s for s in body["students"] if s["displayName"] == "Ziad")
    assert row["classId"] == str(cls.class_id)
    assert row["className"] == "Physics 10A"
    assert row["flags"][0]["reason"] == "declining_trend"


def test_at_risk_list_filters_by_reason(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    from datetime import UTC, datetime, timedelta

    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    declining = _join_student(pg_sessionmaker, class_service, cls.join_code, "Declining")
    inactive = _join_student(pg_sessionmaker, class_service, cls.join_code, "Inactive")
    _seed_history_record(history_store, str(declining), percentage=72.0, grade="B")
    _seed_history_record(history_store, str(declining), percentage=65.0, grade="C")
    _seed_history_record(history_store, str(declining), percentage=58.0, grade="D")
    stale = (datetime.now(UTC) - timedelta(days=20)).isoformat()
    _seed_history_record(
        history_store, str(inactive), percentage=95.0, grade="A*", recorded_at=stale
    )

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    body = client.get("/api/teacher/at-risk?reason=inactive").json()
    assert {s["displayName"] for s in body["students"]} == {"Inactive"}


def test_at_risk_list_sorted_by_severity_flag_count_then_worst_grade(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """More flags first; among equally-flagged students, the worse grade first."""
    from datetime import UTC, datetime, timedelta

    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    # One flag only (declining trend), grade C.
    one_flag = _join_student(pg_sessionmaker, class_service, cls.join_code, "OneFlag")
    _seed_history_record(history_store, str(one_flag), percentage=72.0, grade="B")
    _seed_history_record(history_store, str(one_flag), percentage=65.0, grade="C")
    _seed_history_record(history_store, str(one_flag), percentage=59.0, grade="C")
    # Two flags (declining trend + inactive), grade D — must sort first.
    two_flags = _join_student(pg_sessionmaker, class_service, cls.join_code, "TwoFlags")
    stale = (datetime.now(UTC) - timedelta(days=20)).isoformat()
    _seed_history_record(history_store, str(two_flags), percentage=80.0, grade="B")
    _seed_history_record(history_store, str(two_flags), percentage=70.0, grade="C")
    _seed_history_record(
        history_store, str(two_flags), percentage=60.0, grade="D", recorded_at=stale
    )

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    body = client.get("/api/teacher/at-risk").json()
    names_in_order = [s["displayName"] for s in body["students"]]
    assert names_in_order == ["TwoFlags", "OneFlag"]


def test_at_risk_list_never_shows_another_teachers_students(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    class_a = class_service.create_class(teacher_a, "A's class")
    class_b = class_service.create_class(teacher_b, "B's class")
    assert class_a.join_code is not None
    assert class_b.join_code is not None
    student_b = _join_student(pg_sessionmaker, class_service, class_b.join_code, "B's Student")
    _seed_history_record(history_store, str(student_b), percentage=72.0, grade="B")
    _seed_history_record(history_store, str(student_b), percentage=65.0, grade="C")
    _seed_history_record(history_store, str(student_b), percentage=58.0, grade="D")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_a, Role.teacher)
    body = client.get("/api/teacher/at-risk").json()
    assert body["students"] == []


def test_at_risk_list_platform_admin_sees_none(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    admin_id = _seed_user(pg_sessionmaker, Role.platform_admin)
    _use_class_service(client, class_service)
    _auth_as(client, admin_id, Role.platform_admin)
    assert client.get("/api/teacher/at-risk").json()["students"] == []


# ---------------------------------------------------------------------------
# Acknowledge / un-acknowledge an at-risk flag — T-06 (P3.4b, D3.5).
# ---------------------------------------------------------------------------


def _declining_student(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
    join_code: str,
    display_name: str,
) -> uuid.UUID:
    """Seed a student enrolled via ``join_code`` with a firing declining-trend flag."""
    student = _join_student(pg_sessionmaker, class_service, join_code, display_name)
    _seed_history_record(history_store, str(student), percentage=72.0, grade="B")
    _seed_history_record(history_store, str(student), percentage=65.0, grade="C")
    _seed_history_record(history_store, str(student), percentage=58.0, grade="D")
    return student


def test_acknowledge_at_risk_flag_happy_path(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """Acknowledging a currently-firing flag tags it with who/when/note."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _declining_student(pg_sessionmaker, class_service, history_store, cls.join_code, "Ziad")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    resp = client.post(
        f"/api/teacher/at-risk/{ziad}/acknowledge",
        json={"reason": "declining_trend", "note": "spoke to parents"},
    )
    assert resp.status_code == 200
    flag = resp.json()
    assert flag["reason"] == "declining_trend"
    assert flag["acknowledged"] is not None
    assert flag["acknowledged"]["acknowledgedBy"] == str(teacher_id)
    assert flag["acknowledged"]["note"] == "spoke to parents"
    assert flag["acknowledged"]["acknowledgedAt"]

    # And it reads back acknowledged on the list too — never a second,
    # independently-derived acknowledged state (D3.5's "how to apply").
    body = client.get("/api/teacher/at-risk").json()
    ziad_row = next(s for s in body["students"] if s["displayName"] == "Ziad")
    ziad_flag = next(f for f in ziad_row["flags"] if f["reason"] == "declining_trend")
    assert ziad_flag["acknowledged"] is not None
    assert ziad_flag["acknowledged"]["note"] == "spoke to parents"


def test_acknowledge_flag_not_removed_from_response(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """D3.5: acknowledging tags a flag, it never disappears from the unfiltered list."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _declining_student(pg_sessionmaker, class_service, history_store, cls.join_code, "Ziad")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    client.post(f"/api/teacher/at-risk/{ziad}/acknowledge", json={"reason": "declining_trend"})

    body = client.get("/api/teacher/at-risk").json()
    assert any(s["displayName"] == "Ziad" for s in body["students"])
    body_overview = client.get("/api/teacher/overview").json()
    assert any(s["name"] == "Ziad" for s in body_overview["atRisk"])


def test_acknowledge_reason_not_firing_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """You cannot acknowledge a signal that was never raised (D3.5)."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    # Healthy, improving student: no flags fire at all.
    amelia = _join_student(pg_sessionmaker, class_service, cls.join_code, "Amelia")
    _seed_history_record(history_store, str(amelia), percentage=80.0, grade="A")
    _seed_history_record(history_store, str(amelia), percentage=90.0, grade="A")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    resp = client.post(
        f"/api/teacher/at-risk/{amelia}/acknowledge", json={"reason": "declining_trend"}
    )
    assert resp.status_code == 422


def test_acknowledge_unrecognised_reason_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _declining_student(pg_sessionmaker, class_service, history_store, cls.join_code, "Ziad")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    resp = client.post(
        f"/api/teacher/at-risk/{ziad}/acknowledge", json={"reason": "not_a_real_reason"}
    )
    assert resp.status_code == 422


def test_acknowledge_out_of_scope_student_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """Teacher A cannot acknowledge a flag for teacher B's student (D3.5 tenancy)."""
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    class_b = class_service.create_class(teacher_b, "B's class")
    assert class_b.join_code is not None
    student_b = _declining_student(
        pg_sessionmaker, class_service, history_store, class_b.join_code, "B's Student"
    )

    _use_class_service(client, class_service)
    _auth_as(client, teacher_a, Role.teacher)
    resp = client.post(
        f"/api/teacher/at-risk/{student_b}/acknowledge", json={"reason": "declining_trend"}
    )
    assert resp.status_code == 403

    # And teacher B's own view of the flag is untouched — still unacknowledged.
    _auth_as(client, teacher_b, Role.teacher)
    body = client.get("/api/teacher/at-risk").json()
    row = next(s for s in body["students"] if s["displayName"] == "B's Student")
    flag = next(f for f in row["flags"] if f["reason"] == "declining_trend")
    assert flag["acknowledged"] is None


def test_acknowledge_unknown_student_id_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    resp = client.post(
        f"/api/teacher/at-risk/{uuid.uuid4()}/acknowledge", json={"reason": "declining_trend"}
    )
    assert resp.status_code == 404


def test_unacknowledge_removes_tag(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _declining_student(pg_sessionmaker, class_service, history_store, cls.join_code, "Ziad")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    client.post(f"/api/teacher/at-risk/{ziad}/acknowledge", json={"reason": "declining_trend"})

    resp = client.delete(f"/api/teacher/at-risk/{ziad}/acknowledge/declining_trend")
    assert resp.status_code == 204

    body = client.get("/api/teacher/at-risk").json()
    row = next(s for s in body["students"] if s["displayName"] == "Ziad")
    flag = next(f for f in row["flags"] if f["reason"] == "declining_trend")
    assert flag["acknowledged"] is None


def test_unacknowledge_idempotent_when_never_acknowledged(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _declining_student(pg_sessionmaker, class_service, history_store, cls.join_code, "Ziad")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    resp = client.delete(f"/api/teacher/at-risk/{ziad}/acknowledge/declining_trend")
    assert resp.status_code == 204


def test_unacknowledge_out_of_scope_student_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    class_b = class_service.create_class(teacher_b, "B's class")
    assert class_b.join_code is not None
    student_b = _declining_student(
        pg_sessionmaker, class_service, history_store, class_b.join_code, "B's Student"
    )

    _use_class_service(client, class_service)
    _auth_as(client, teacher_a, Role.teacher)
    resp = client.delete(f"/api/teacher/at-risk/{student_b}/acknowledge/declining_trend")
    assert resp.status_code == 403


def test_at_risk_list_acknowledged_filter(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """``?acknowledged=true|false`` filters; omitted returns both (P3.4b)."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    acked = _declining_student(
        pg_sessionmaker, class_service, history_store, cls.join_code, "Acked"
    )
    _declining_student(pg_sessionmaker, class_service, history_store, cls.join_code, "Unacked")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    client.post(f"/api/teacher/at-risk/{acked}/acknowledge", json={"reason": "declining_trend"})

    both = client.get("/api/teacher/at-risk").json()
    assert {s["displayName"] for s in both["students"]} == {"Acked", "Unacked"}

    only_acked = client.get("/api/teacher/at-risk?acknowledged=true").json()
    assert {s["displayName"] for s in only_acked["students"]} == {"Acked"}

    only_unacked = client.get("/api/teacher/at-risk?acknowledged=false").json()
    assert {s["displayName"] for s in only_unacked["students"]} == {"Unacked"}


def test_acknowledgement_consistent_across_overview_detail_and_list(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """The same flag reports the same acknowledged state on T-01, T-05, T-06 (D3.5)."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _declining_student(pg_sessionmaker, class_service, history_store, cls.join_code, "Ziad")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    client.post(
        f"/api/teacher/at-risk/{ziad}/acknowledge",
        json={"reason": "declining_trend", "note": "watching closely"},
    )

    overview = client.get("/api/teacher/overview").json()
    overview_flag = next(
        f
        for s in overview["atRisk"]
        if s["name"] == "Ziad"
        for f in s["flags"]
        if f["reason"] == "declining_trend"
    )
    detail = client.get(f"/api/teacher/students/{ziad}").json()
    detail_flag = next(f for f in detail["atRiskFlags"] if f["reason"] == "declining_trend")
    at_risk_list = client.get("/api/teacher/at-risk").json()
    list_flag = next(
        f
        for s in at_risk_list["students"]
        if s["displayName"] == "Ziad"
        for f in s["flags"]
        if f["reason"] == "declining_trend"
    )

    for flag in (overview_flag, detail_flag, list_flag):
        assert flag["acknowledged"] is not None
        assert flag["acknowledged"]["note"] == "watching closely"
        assert flag["acknowledged"]["acknowledgedBy"] == str(teacher_id)


def test_acknowledged_flag_reraises_unacknowledged_on_further_decline(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """The key D3.5 regression: acknowledge a declining-trend flag, then add a
    further-declined paper — the flag must come back unacknowledged. This is
    the whole point of evidence-scoping: a student who declines *further*
    after being acknowledged is a genuinely new signal."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _declining_student(pg_sessionmaker, class_service, history_store, cls.join_code, "Ziad")

    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    resp = client.post(
        f"/api/teacher/at-risk/{ziad}/acknowledge", json={"reason": "declining_trend"}
    )
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] is not None

    # Confirm it reads acknowledged before the new evidence lands.
    before = client.get("/api/teacher/at-risk").json()
    before_flag = next(
        f
        for s in before["students"]
        if s["displayName"] == "Ziad"
        for f in s["flags"]
        if f["reason"] == "declining_trend"
    )
    assert before_flag["acknowledged"] is not None

    # A further decline: window shifts from 72->65->58 to 65->58->50.
    _seed_history_record(history_store, str(ziad), percentage=50.0, grade="D")

    after = client.get("/api/teacher/at-risk").json()
    after_flag = next(
        f
        for s in after["students"]
        if s["displayName"] == "Ziad"
        for f in s["flags"]
        if f["reason"] == "declining_trend"
    )
    assert after_flag["acknowledged"] is None
    # New evidence: the flag itself still fires (still at risk), just unacked.
    assert after_flag["evidence"]["percentages"] == [65.0, 58.0, 50.0]


def test_acknowledgement_is_per_teacher_not_global(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    """D3.5's per-teacher rule, pinned through the API and not just the service.

    Two teachers who *both* legitimately see the same student — so this is
    about acknowledgement scoping, not tenancy (which
    ``test_acknowledge_out_of_scope_student_is_403`` already covers). Teacher
    A acknowledging must not blind teacher B, who carries their own
    responsibility for that student; B must still see the flag, and see it as
    unacknowledged, with no trace of A's note.
    """
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    class_a = class_service.create_class(teacher_a, "Physics 10A")
    class_b = class_service.create_class(teacher_b, "Physics 10B")
    assert class_a.join_code is not None
    assert class_b.join_code is not None
    ziad = _declining_student(
        pg_sessionmaker, class_service, history_store, class_a.join_code, "Ziad"
    )
    # The same student also sits in teacher B's class.
    class_service.join_by_code(ziad, class_b.join_code)

    _use_class_service(client, class_service)
    _auth_as(client, teacher_a, Role.teacher)
    resp = client.post(
        f"/api/teacher/at-risk/{ziad}/acknowledge",
        json={"reason": "declining_trend", "note": "spoke to his mother"},
    )
    assert resp.status_code == 200

    def _flag(payload: dict) -> dict:  # type: ignore[type-arg]
        return next(
            f
            for s in payload["students"]
            if s["displayName"] == "Ziad"
            for f in s["flags"]
            if f["reason"] == "declining_trend"
        )

    a_flag = _flag(client.get("/api/teacher/at-risk").json())
    assert a_flag["acknowledged"] is not None
    assert a_flag["acknowledged"]["note"] == "spoke to his mother"

    _auth_as(client, teacher_b, Role.teacher)
    b_payload = client.get("/api/teacher/at-risk").json()
    b_flag = _flag(b_payload)
    # Still surfaced to B, and still unacknowledged for B.
    assert b_flag["acknowledged"] is None
    assert "spoke to his mother" not in json.dumps(b_payload)

    # B's own filter agrees: the flag is unacknowledged from where B stands.
    unacked = client.get("/api/teacher/at-risk?acknowledged=false").json()
    assert any(s["displayName"] == "Ziad" for s in unacked["students"])
    acked = client.get("/api/teacher/at-risk?acknowledged=true").json()
    assert all(s["displayName"] != "Ziad" for s in acked["students"])
