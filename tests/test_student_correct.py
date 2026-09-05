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
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
from lemely.core.schemas import ExamMetadata, ExtractedAnswer, ExtractedAnswers
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult
from lemely.db.models.enums import Role, UploadStatus
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.scheme_corpus_repo import SchemeCorpusRepository
from lemely.db.upload_repo import StudentUploadRepository
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import DatabaseSettings, Settings, load_settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_attempt_repo,
    get_auth_context,
    get_gemini_client,
    get_scheme_corpus_repo,
    get_settings,
    get_storage_backend,
    get_student_upload_repo,
    get_user_mirror,
)
from lemely.web.routers import student
from lemely.web.routers.student import resolve_mark_scheme
from lemely.web.upload_utils import check_upload_cap
from tests.storage_fakes import FakeStorageBackend

if TYPE_CHECKING:
    from collections.abc import Iterator


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
        # Issue #10 / D7.5: `POST /student/correct` now soft-gates on a
        # verified email (`lemely.web.deps.require_verified_email`). This
        # file's whole subject is the correction pipeline, not verification,
        # so every seeded user is pre-verified — the alternative would be
        # every test below failing on a 403 this file was never about.
        session.add(
            User(id=uid, email=f"{uid}@example.com", role=role, email_verified_at=datetime.now(UTC))
        )
    return str(uid)


class _PgUserMirror:
    """Minimal ``UserMirror`` bound to this file's throwaway sessionmaker.

    ``require_verified_email`` (new, issue #10) reads the mirror directly;
    without this override the route would fall back to the real,
    unoverridden ``DbUserMirror`` against the default configured database —
    not the throwaway one this file's ``student_id`` actually lives in — and
    see nothing, gating every request in this file at 403. Only ``get_by_id``
    is exercised by that dependency; the rest raise so an unexpected call
    surfaces immediately rather than returning a quietly-wrong answer.
    """

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self._sm = sm

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        with self._sm() as session:
            user = session.get(User, user_id)
            if user is not None:
                session.expunge(user)
            return user

    def get_by_phone(self, phone: str) -> User | None:  # pragma: no cover - unused here
        raise NotImplementedError

    def get_by_email(self, email: str) -> User | None:  # pragma: no cover - unused here
        raise NotImplementedError

    def upsert(self, *args: object, **kwargs: object) -> None:  # pragma: no cover - unused here
        raise NotImplementedError

    def mark_email_verified(
        self, user_id: uuid.UUID, *, verified_at: datetime
    ) -> None:  # pragma: no cover - unused here
        raise NotImplementedError


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


def _mcq_scheme_extended() -> MarkScheme:
    """Same two-question MCQ scheme as :func:`_mcq_scheme`, but 0625 paper 2
    ("Multiple Choice (Extended)", ``syllabus_papers.tier="extended"``)
    instead of paper 1 ("Multiple Choice (Core)", ``tier="core"``).

    Cambridge's Core tier is capped at grade C and its component thresholds
    publish no A/B boundary at all, so a Core paper's ``rail_foot`` is always
    ``""`` — see ``test_correct_complete_frame_includes_result_header_fields``.
    This variant exists solely to keep that assertion's "A boundary sat at
    ..." code path under real, data-backed test coverage.
    """
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 2,
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


def _scheme(
    *,
    subject: str = "0625",
    paper: int = 1,
    variant: int = 1,
    month: str = "May/June",
    year: int | None = 2023,
) -> MarkScheme:
    """A minimal, real two-question :class:`MarkScheme` for one paper identity.

    Mirrors ``tests/test_scheme_corpus_repo.py``'s ``_scheme()``, parameterised
    the same way, for the resolver tests below that need the corpus stocked
    with a real, storable scheme.
    """
    from lemely.core.loose_schemas import (
        AnswerPoint,
        MarkSchemeMetadata,
        PaperType,
        Question,
        QuestionType,
        SchemeFormat,
    )
    from lemely.core.loose_schemas import SessionMonth as SchemeSessionMonth

    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code=subject,
            paper_number=paper,
            paper_variant=variant,
            session_month=SchemeSessionMonth(month),
            session_year=year,
            paper_type=PaperType.THEORY_CORE,
            maximum_mark=4,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            Question(
                id="1",
                marks=2,
                type=QuestionType.RECALL,
                answer_points=[AnswerPoint(id="p1", point="correct", marks=2)],
            ),
            Question(
                id="2",
                marks=2,
                type=QuestionType.RECALL,
                answer_points=[AnswerPoint(id="p1", point="correct", marks=2)],
            ),
        ],
    )


@pytest.fixture
def gemini_client() -> MagicMock:
    """A mocked GeminiClient — never makes network calls."""
    return MagicMock(spec=GeminiClient)


@pytest.fixture
def corpus_repo(pg_sessionmaker: sessionmaker[Session]) -> SchemeCorpusRepository:
    """A :class:`SchemeCorpusRepository` bound to the same throwaway database (spec §4.3)."""
    return SchemeCorpusRepository(pg_sessionmaker)


@pytest.fixture
def client(
    settings: Settings,
    pg_sessionmaker: sessionmaker[Session],
    corpus_repo: SchemeCorpusRepository,
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
    app.dependency_overrides[get_scheme_corpus_repo] = lambda: corpus_repo
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=student_id, role="student"
    )
    # Issue #10 / D7.5: see `_PgUserMirror`'s own docstring above.
    app.dependency_overrides[get_user_mirror] = lambda: _PgUserMirror(pg_sessionmaker)
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `complete` frame carries the same header fields GET /result computes.

    P2.7 step 5: `_result_header_fields` is shared by both paths, so the SSE
    completion frame should carry code/paper/session/boundaryYear/railLeft/
    railFoot/pct computed from the resolved scheme's own metadata
    (0625 paper 2 variant 2, May/June 2020) and the awarded/maximum marks
    (1/2 from the canned extraction: q1 correct, q2 blank).

    Deliberately overrides the `client` fixture's paper-1 (Core) scheme with
    `_mcq_scheme_extended()` (paper 2, Extended): Core is capped at grade C
    and its real ingested thresholds carry no A boundary at all, so
    `rail_foot` would always be `""` on paper 1 -- see
    `lemely.io.grade_boundaries._load`'s docstring on why the fallback map is
    scoped per `(subject_code, paper_number)`. Paper 2 keeps this test's whole
    point -- a real, data-backed "A boundary sat at ..." line -- honest rather
    than replaced with an empty-string assertion.
    """
    monkeypatch.setattr(student, "resolve_mark_scheme", lambda *a, **k: _mcq_scheme_extended())
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
    assert complete_frame["paper"] == "Paper 2 - Variant 2"
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


# ---------------------------------------------------------------------------
# Recovering a run that outlived the browser tab (P6.2, audit M4).
#
# The marking work happens on a background thread that does not stop when the
# client disconnects, so a student who reloads has not lost the marking — only
# the thing reporting on it. These pin the state that makes it findable again.
# ---------------------------------------------------------------------------


def test_correct_writes_processing_before_it_finishes(
    client: tuple[TestClient, str, StudentUploadRepository],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run announces itself as `processing`, not just as a terminal status.

    `UploadStatus.processing` shipped in the first migration and no code path
    ever wrote it, so a paper being marked right now was indistinguishable in
    the database from a scan someone uploaded and abandoned. Asserting the
    terminal status alone (as `test_correct_marks_upload_complete` does) cannot
    see that, because the end state is the same either way.

    Observed from inside the run rather than after it: by the time the response
    is read, the status is `complete`, which is the whole reason the gap went
    unnoticed.
    """
    api, student_id, upload_repo = client
    up = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    paper_id = up.json()["paperId"]

    seen: list[UploadStatus] = []
    real_extract = student.extract_answers

    def spy(*args: object, **kwargs: object) -> ExtractedAnswers:
        run = upload_repo.get_run(user_id=student_id, upload_id=paper_id)
        assert run is not None
        seen.append(run.status)
        return cast("ExtractedAnswers", real_extract(*args, **kwargs))

    monkeypatch.setattr(student, "extract_answers", spy)
    api.post("/api/student/correct", json={"paperId": paper_id})

    assert seen == [UploadStatus.processing], (
        f"the run must record that it is in flight while it is in flight; saw {seen}"
    )


def test_active_upload_is_null_when_nothing_is_running(
    client: tuple[TestClient, str, StudentUploadRepository],
) -> None:
    """Nothing running is the ordinary answer, and it is `null`, not a 404."""
    api, _, _ = client
    api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    resp = api.get("/api/student/uploads/active")
    assert resp.status_code == 200
    assert resp.json() is None, (
        "an upload that was stored and never marked is not a run in flight. "
        "Counting `pending` here is what made the platform console's "
        "'uploads in flight' figure grow forever."
    )


def test_active_upload_finds_a_run_in_flight(
    client: tuple[TestClient, str, StudentUploadRepository],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reload during marking can find the paper it lost."""
    api, _, _ = client
    up = api.post(
        "/api/student/uploads",
        files={"scan": ("mine.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    paper_id = up.json()["paperId"]

    found: list[dict[str, object]] = []
    real_extract = student.extract_answers

    def spy(*args: object, **kwargs: object) -> ExtractedAnswers:
        # Mid-run: exactly the moment a student's reload would land.
        found.append(api.get("/api/student/uploads/active").json())
        return cast("ExtractedAnswers", real_extract(*args, **kwargs))

    monkeypatch.setattr(student, "extract_answers", spy)
    api.post("/api/student/correct", json={"paperId": paper_id})

    assert len(found) == 1
    active = found[0]
    assert active is not None
    assert active["paperId"] == paper_id
    assert active["status"] == "processing"
    assert active["filename"] == "mine.pdf"
    assert active["stale"] is False
    assert active["startedAt"] is not None

    # And it stops naming the paper the moment the run ends, which is why the
    # client polls the paper rather than this endpoint.
    assert api.get("/api/student/uploads/active").json() is None


def test_upload_run_reports_the_terminal_status_a_poller_needs(
    client: tuple[TestClient, str, StudentUploadRepository],
) -> None:
    """Polling the paper ends on a status that says which way it went."""
    api, _, _ = client
    up = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    paper_id = up.json()["paperId"]

    before = api.get(f"/api/student/uploads/{paper_id}")
    assert before.status_code == 200
    assert before.json()["status"] == "pending"
    # `startedAt` is the row's updated_at, which means "marking began" only
    # while processing. It must not be offered for any other status.
    assert before.json()["startedAt"] is None

    api.post("/api/student/correct", json={"paperId": paper_id})

    after = api.get(f"/api/student/uploads/{paper_id}")
    assert after.json()["status"] == "complete"
    assert after.json()["stale"] is False


def test_a_run_older_than_the_bound_reports_stale(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A `processing` row nobody will ever finish stops claiming to be marking.

    The only way a row stays `processing` is a process that died holding it, and
    no code will come back to correct it. Past the bound the screen must stop
    promising a result; `stale` is what tells it to.
    """
    from lemely.db.models.attempts import Upload

    api, student_id, upload_repo = client
    up = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    paper_id = up.json()["paperId"]

    stale_moment = datetime.now(UTC) - student.MARKING_RUN_STALE_AFTER - timedelta(minutes=1)
    with pg_sessionmaker.begin() as session:
        row = session.get(Upload, uuid.UUID(paper_id))
        assert row is not None
        row.status = UploadStatus.processing
        row.updated_at = stale_moment

    body = api.get(f"/api/student/uploads/{paper_id}").json()
    assert body["status"] == "processing"
    assert body["stale"] is True

    # Still the active run: stale means "stop promising", not "hide it". A
    # student whose paper died deserves to be told, not to find an empty screen.
    assert api.get("/api/student/uploads/active").json()["paperId"] == paper_id

    # And a failure is never stale — it is finished, with a reported reason.
    upload_repo.set_status(uuid.UUID(paper_id), UploadStatus.failed)
    failed = api.get(f"/api/student/uploads/{paper_id}").json()
    assert failed["status"] == "failed"
    assert failed["stale"] is False


def test_foreign_and_unknown_runs_are_404(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    """Same uniform 404 as `/correct`: no ownership oracle on the read path."""
    api, _, upload_repo = client
    other_id = _seed_user(pg_sessionmaker, Role.student)
    foreign = upload_repo.create_upload(
        user_id=other_id,
        storage_path=str(tmp_path / "other.pdf"),
        original_filename="other.pdf",
        content_type="application/pdf",
        byte_size=10,
    )
    assert api.get(f"/api/student/uploads/{foreign}").status_code == 404
    assert api.get(f"/api/student/uploads/{uuid.uuid4()}").status_code == 404
    assert api.get("/api/student/uploads/not-a-uuid").status_code == 404


def test_another_students_run_is_not_my_active_run(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    """`/uploads/active` is scoped to the caller, not to the platform."""
    from lemely.db.models.attempts import Upload

    api, _, upload_repo = client
    other_id = _seed_user(pg_sessionmaker, Role.student)
    foreign = upload_repo.create_upload(
        user_id=other_id,
        storage_path=str(tmp_path / "other.pdf"),
        original_filename="other.pdf",
        content_type="application/pdf",
        byte_size=10,
    )
    with pg_sessionmaker.begin() as session:
        row = session.get(Upload, foreign)
        assert row is not None
        row.status = UploadStatus.processing

    assert api.get("/api/student/uploads/active").json() is None


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


# ---------------------------------------------------------------------------
# resolve_mark_scheme (spec §4.3) — the shared resolver both portals call.
#
# These call the function directly (no HTTP client): the ``client`` fixture
# above monkeypatches ``resolve_mark_scheme`` away entirely so the SSE tests
# above stay deterministic and offline, which means those tests prove nothing
# about the resolver itself. These do.
# ---------------------------------------------------------------------------

_REAL_SCHEME_PDF = Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.pdf")
"""A real, deterministically-parseable CAIE scheme (0625 Physics, paper 1
variant 2, Feb/Mar 2020) — used below as the sibling PDF, deliberately a
*different* paper identity from the corpus row the same test seeds, so a
resolver that read from the wrong source would return the wrong paper."""


def test_resolver_prefers_sibling_then_corpus(
    tmp_path: Path,
    corpus_repo: SchemeCorpusRepository,
    settings: Settings,
    gemini_client: MagicMock,
) -> None:
    corpus_repo.store(_scheme(), provenance="t")
    meta = ExamMetadata(
        subject_code="0625",
        paper_number=1,
        paper_variant=1,
        session_month="May/June",
        session_year=2023,
    )
    resolved = resolve_mark_scheme(None, corpus_repo, settings, gemini_client, metadata=meta)
    assert resolved is not None
    assert resolve_mark_scheme(None, corpus_repo, settings, gemini_client, metadata=None) is None


def test_resolver_sibling_wins_over_a_matching_corpus_scheme(
    tmp_path: Path,
    corpus_repo: SchemeCorpusRepository,
    settings: Settings,
    gemini_client: MagicMock,
) -> None:
    """A sibling scheme always wins, even when the corpus holds one for the exact same paper.

    Getting the preference order backwards would silently grade a student's
    work against a different scheme than the one they (or their teacher)
    actually attached — the wrong-scheme risk the resolver exists to avoid.
    """
    corpus_repo.store(_scheme(paper=1, variant=1, month="May/June", year=2023), provenance="t")
    meta = ExamMetadata(
        subject_code="0625",
        paper_number=1,
        paper_variant=1,
        session_month="May/June",
        session_year=2023,
    )

    sibling = tmp_path / "mark_scheme.pdf"
    sibling.write_bytes(_REAL_SCHEME_PDF.read_bytes())

    resolved = resolve_mark_scheme(sibling, corpus_repo, settings, gemini_client, metadata=meta)
    assert resolved is not None
    # The sibling is a real, *different* paper (variant 2, 40 marks, 40
    # questions) from the corpus row stored above (variant 1, 4 marks, 2
    # questions). If the corpus had won instead of the sibling, these would
    # read the corpus row's numbers instead.
    assert resolved.metadata.paper_variant == 2
    assert resolved.metadata.maximum_mark == 40
    assert len(resolved.questions) == 40


def test_resolver_corpus_near_miss_returns_none_not_a_different_papers_scheme(
    corpus_repo: SchemeCorpusRepository,
    settings: Settings,
    gemini_client: MagicMock,
) -> None:
    """A detected paper the corpus does not hold must resolve to ``None``.

    The corpus has a scheme for paper 1; the caller detected paper 2. A
    resolver that fell back to "closest match" here would silently mark a
    student's paper-2 work against paper 1's scheme.
    """
    corpus_repo.store(_scheme(paper=1, variant=1), provenance="t")
    near_miss = ExamMetadata(
        subject_code="0625",
        paper_number=2,
        paper_variant=1,
        session_month="May/June",
        session_year=2023,
    )
    assert (
        resolve_mark_scheme(None, corpus_repo, settings, gemini_client, metadata=near_miss) is None
    )
