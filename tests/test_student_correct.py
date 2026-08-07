"""End-to-end tests for the student self-mark flow (P2.1).

Real Postgres through the TestClient, Gemini fully mocked. The mark scheme is a
deterministic MCQ scheme and answer extraction is monkeypatched to a canned
:class:`ExtractedAnswers`, so marking is 100% offline — no network, no key. The
tests drive the SSE ``/correct`` stream, then assert the persisted attempt +
per-question results + review-queue rows in Postgres, plus the ownership 404s and
role 403s.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult
from lemely.db.models.enums import Role, UploadStatus
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.upload_repo import StudentUploadRepository
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import DatabaseSettings, Settings, load_settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_attempt_repo,
    get_auth_context,
    get_gemini_client,
    get_settings,
    get_storage_backend,
    get_student_upload_repo,
)
from lemely.web.routers import student
from lemely.web.upload_utils import check_upload_cap
from tests.storage_fakes import FakeStorageBackend

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# ---------------------------------------------------------------------------
# Postgres fixture (throwaway DB; skips when unreachable).
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


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> str:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return str(uid)


# ---------------------------------------------------------------------------
# Settings / app fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings with an isolated output_dir and NO gemini key (metadata=None path)."""
    base = load_settings()
    data = base.model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    # Force the no-key branch so ScanMetadataExtractor is never invoked.
    data["gemini_api_key"] = None
    return Settings.model_validate(data)


def _mcq_scheme() -> MarkScheme:
    """A two-question MCQ scheme; answer 'A' for q1, 'B' for q2."""
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": 2,
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
                {"id": "2", "marks": 1, "type": "mcq", "mcq_answer": "B"},
            ],
        }
    )


def _extracted() -> ExtractedAnswers:
    """One correct answer (q1='A') and one blank (q2=''), so q2 is LOW confidence."""
    return ExtractedAnswers(
        paper_id="paper",
        source_scan="scan.pdf",
        answers=[
            ExtractedAnswer(question_id="1", answer="A", confidence=0.99),
            ExtractedAnswer(question_id="2", answer="", confidence=0.0),
        ],
    )


@pytest.fixture
def client(
    settings: Settings,
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str, StudentUploadRepository]]:
    """A TestClient wired to real repos over a throwaway DB, Gemini mocked.

    Yields the client, the seeded student's user id (the auth caller), and the
    upload repo so tests can seed / inspect uploads directly.
    """
    student_id = _seed_user(pg_sessionmaker, Role.student)
    upload_repo = StudentUploadRepository(pg_sessionmaker)
    attempt_repo = AttemptRepository(pg_sessionmaker)
    storage_backend = FakeStorageBackend()

    # Deterministic, offline marking: fixed MCQ scheme + canned extraction.
    monkeypatch.setattr(student, "resolve_mark_scheme", lambda *a, **k: _mcq_scheme())
    monkeypatch.setattr(student, "extract_answers", lambda *a, **k: _extracted())

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock(spec=GeminiClient)
    app.dependency_overrides[get_attempt_repo] = lambda: attempt_repo
    app.dependency_overrides[get_student_upload_repo] = lambda: upload_repo
    app.dependency_overrides[get_storage_backend] = lambda: storage_backend
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=student_id, role="student"
    )
    yield TestClient(app), student_id, upload_repo
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_upload_then_correct_persists_attempt(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, student_id, _ = client

    # 1. Upload a scan (real endpoint) → paperId.
    up = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert up.status_code == 200, up.text
    paper_id = up.json()["paperId"]

    # 2. Correct it → SSE stream.
    resp = api.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert "marking_progress" in body
    assert '"phase": "complete"' in body
    assert '"grade"' in body
    assert "[DONE]" in body

    # 3. Persistence: one attempt, two question results, one review row (the blank).
    with pg_sessionmaker() as session:
        attempts = session.scalars(select(Attempt)).all()
        assert len(attempts) == 1
        attempt = attempts[0]
        assert str(attempt.user_id) == student_id
        assert attempt.confidence_band is not None

        results = session.scalars(select(QuestionResult).order_by(QuestionResult.question_id)).all()
        assert len(results) == 2

        items = session.scalars(select(ReviewQueueItem)).all()
        # The blank q2 is LOW confidence → one row, and that is the only row.
        #
        # This assertion used to be 2, with a `plagiarism_flag` row alongside:
        # q1's deterministic MCQ answer ("A") is verbatim-identical to the
        # expected answer ("A"), so the advisory plagiarism checker scored it
        # 1.0 and flagged it. That was B3 (D3.19) — a *correct* MCQ answer is
        # always character-identical to the expected one, so the flag fired on
        # every right answer and never on a wrong one. The old expectation
        # pinned the defect, not the behaviour. `apply_integrity_checks` now
        # skips both integrity checks for MCQ questions, so the false row is
        # gone. Neither check ever touched awarded/maximum marks.
        assert len(items) == 1
        assert {item.reason.value for item in items} == {"low_confidence"}


def test_correct_complete_frame_includes_full_questions(
    client: tuple[TestClient, str, StudentUploadRepository],
) -> None:
    """The `complete` frame's `questions` key mirrors report.correction.questions.

    D2.7 (2): the SSE closure discards the full per-question CorrectionResult
    after computing scalar totals unless it is forwarded explicitly — this is
    the regression test for that forwarding.
    """
    api, _, _ = client
    up = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    paper_id = up.json()["paperId"]

    resp = api.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 200

    complete_frame = next(
        json.loads(frame.removeprefix("data: "))
        for frame in resp.text.split("\n\n")
        if frame.startswith("data:") and '"phase": "complete"' in frame
    )
    questions = complete_frame["questions"]
    assert {q["questionId"] for q in questions} == {"1", "2"}
    assert len(questions) == len(_mcq_scheme().questions)

    by_id = {q["questionId"]: q for q in questions}
    # q1: MCQ answer 'A' matches the extracted 'A' exactly.
    assert by_id["1"]["awardedMarks"] == 1
    assert by_id["1"]["maxMarks"] == 1
    assert "plagiarismFlagged" in by_id["1"]
    assert "matchedPointIds" in by_id["1"]
    assert "confidence" in by_id["1"]
    # q2: extracted answer is blank, so no marks are awarded.
    assert by_id["2"]["awardedMarks"] == 0
    assert "reviewReason" in by_id["2"]


def test_correct_complete_frame_includes_result_header_fields(
    client: tuple[TestClient, str, StudentUploadRepository],
) -> None:
    """The `complete` frame carries the same header fields GET /result computes.

    P2.7 step 5: `_result_header_fields` is shared by both paths, so the SSE
    completion frame should carry code/paper/session/boundaryYear/railLeft/
    railFoot/pct computed from the resolved scheme's own metadata
    (0625 paper 1 variant 2, May/June 2020) and the awarded/maximum marks
    (1/2 from the canned extraction: q1 correct, q2 blank).
    """
    api, _, _ = client
    up = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    paper_id = up.json()["paperId"]

    resp = api.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 200

    complete_frame = next(
        json.loads(frame.removeprefix("data: "))
        for frame in resp.text.split("\n\n")
        if frame.startswith("data:") and '"phase": "complete"' in frame
    )

    assert complete_frame["code"] == "0625"
    assert complete_frame["paper"] == "Paper 1 - Variant 2"
    assert complete_frame["session"] == "May/June 2020"
    assert complete_frame["boundary_year"] == "2020"
    # awarded=1, maximum=2 (q1 correct, q2 blank) -> 50%.
    assert complete_frame["rail_left"] == 50
    assert complete_frame["pct"] == 50
    assert complete_frame["rail_foot"].startswith("A boundary sat at")


def test_upload_sets_status_and_writes_file(
    client: tuple[TestClient, str, StudentUploadRepository],
    settings: Settings,
) -> None:
    api, student_id, upload_repo = client
    up = api.post(
        "/api/student/uploads",
        files={"scan": ("mine.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert up.status_code == 200
    paper_id = up.json()["paperId"]

    owned = upload_repo.get_owned_upload(user_id=student_id, upload_id=paper_id)
    assert owned is not None
    assert owned.original_filename == "mine.pdf"
    assert owned.storage_path == f"uploads/{student_id}/{owned.id.hex}/mine.pdf"

    storage_backend = cast("FastAPI", api.app).dependency_overrides[get_storage_backend]()
    assert storage_backend.download(settings.storage.bucket, owned.storage_path) == (
        b"%PDF-1.4 fake"
    )


def test_upload_over_size_cap_is_413(
    client: tuple[TestClient, str, StudentUploadRepository],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scan larger than the cap is rejected with 413, never reaching Storage."""
    monkeypatch.setattr(
        student, "check_upload_cap", lambda data, **_: check_upload_cap(data, max_bytes=8)
    )
    api, _, _ = client
    resp = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"way too many bytes here", "application/pdf")},
    )
    assert resp.status_code == 413


def test_correct_marks_upload_complete(
    client: tuple[TestClient, str, StudentUploadRepository],
) -> None:
    api, student_id, upload_repo = client
    up = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    paper_id = up.json()["paperId"]
    api.post("/api/student/correct", json={"paperId": paper_id})

    owned = upload_repo.get_owned_upload(user_id=student_id, upload_id=paper_id)
    assert owned is not None
    # Re-query status directly (get_owned_upload does not carry status).
    with upload_repo._sm() as session:
        from lemely.db.models.attempts import Upload

        row = session.get(Upload, owned.id)
        assert row is not None
        assert row.status == UploadStatus.complete


def test_unknown_paper_id_is_404(
    client: tuple[TestClient, str, StudentUploadRepository],
) -> None:
    api, _, _ = client
    resp = api.post("/api/student/correct", json={"paperId": str(uuid.uuid4())})
    assert resp.status_code == 404


def test_malformed_paper_id_is_404(
    client: tuple[TestClient, str, StudentUploadRepository],
) -> None:
    api, _, _ = client
    resp = api.post("/api/student/correct", json={"paperId": "not-a-uuid"})
    assert resp.status_code == 404


def test_foreign_paper_id_is_404(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    api, _, upload_repo = client
    # An upload owned by a DIFFERENT student.
    other_id = _seed_user(pg_sessionmaker, Role.student)
    foreign = upload_repo.create_upload(
        user_id=other_id,
        storage_path=str(tmp_path / "other.pdf"),
        original_filename="other.pdf",
        content_type="application/pdf",
        byte_size=10,
    )
    resp = api.post("/api/student/correct", json={"paperId": str(foreign)})
    assert resp.status_code == 404


def test_teacher_role_forbidden(
    settings: Settings,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock(spec=GeminiClient)
    app.dependency_overrides[get_attempt_repo] = lambda: AttemptRepository(pg_sessionmaker)
    app.dependency_overrides[get_student_upload_repo] = lambda: StudentUploadRepository(
        pg_sessionmaker
    )
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(uuid.uuid4()), role="teacher"
    )
    api = TestClient(app)

    correct = api.post("/api/student/correct", json={"paperId": str(uuid.uuid4())})
    assert correct.status_code == 403
    upload = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert upload.status_code == 403
    app.dependency_overrides.clear()
