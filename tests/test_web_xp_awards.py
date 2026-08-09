"""Route tests for the four XP award seams (P5.2 chunk B, D5.1).

Self-contained (mirrors ``tests/test_web_study_plan.py``/``test_web_flashcards.py``/
``test_web_student_quiz.py``/``test_student_correct.py`` — the four seams this
chunk wires) — a throwaway Postgres DB per test, skipped cleanly when
unreachable, Gemini always mocked (never a real client; D4.3's suite-wide
guard would raise).

Covers, per seam (``paper_corrected`` via ``/student/correct``,
``quiz_completed`` via ``/student/quizzes/{id}/submit``,
``study_session_completed`` via ``/student/study-plan/sessions/{id}/complete``,
``flashcard_reviewed`` via ``/student/flashcards/cards/{id}/review``):

* The happy path: one ``xp_events`` row with the right source/amount/
  ``subject_code``/``dedupe_key``.
* Idempotency at the seam, proven by whichever mechanism actually reaches it
  through the real HTTP surface (**re-correcting the same upload** for a
  paper, the router's own re-submit rejection for a quiz, natural
  re-completion for a study session) — never just re-asserting
  ``XpService``'s own dedupe, which ``tests/test_xp_repo.py`` already owns.
  The paper case is D5.1 §8's opening sentence ("a paper can be re-marked")
  and is why that seam keys on the upload id rather than the per-run attempt
  id — see D5.3.
* The learning-wins rule (D5.1 §3): a real request against a *failing*
  ``XpService`` double still returns the endpoint's normal success response.
* The anti-farming cap (D5.1 §3) on the cheapest seam (flashcards, 60/day):
  a capped review still succeeds and writes no extra row.
* ``flashcard_reviewed`` is deliberately **not** deduped between two
  legitimate reviews of the same card (each review is its own act) — the one
  seam whose dedupe key is not "the thing being acted on".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.flashcard_repo import FlashcardService
from lemely.db.models import ClassEnrollment, User
from lemely.db.models.attempts import Attempt
from lemely.db.models.engagement import XpEvent
from lemely.db.models.enums import (
    DifficultySource,
    ExamBoard,
    QuestionDifficulty,
    QuestionSource,
    Role,
    XpSource,
)
from lemely.db.models.quizzes import QuestionBank
from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_repo import QuizService
from lemely.db.quiz_taking_repo import QuizTakingService
from lemely.db.study_plan_repo import StudyPlanService
from lemely.db.upload_repo import StudentUploadRepository
from lemely.db.xp_repo import DAILY_SOURCE_CAPS, XP_AMOUNTS, XpAwardResult, XpService
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import DatabaseSettings, Settings, load_settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_attempt_repo,
    get_auth_context,
    get_flashcard_service,
    get_gemini_client,
    get_quiz_marking_service,
    get_quiz_taking_service,
    get_settings,
    get_storage_backend,
    get_student_upload_repo,
    get_study_plan_service,
    get_xp_service,
)
from lemely.web.routers import student as student_router_module
from tests.storage_fakes import FakeStorageBackend

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# A fixed midday-UTC instant: midday Cairo (UTC+3 in August) too, so every
# award in these tests lands on the same civil streak-day regardless of when
# the suite actually runs.
_FIXED_NOW = datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Shared fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    yield TestClient(app)
    app.dependency_overrides.clear()


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


@pytest.fixture
def xp_service(pg_sessionmaker: sessionmaker[Session]) -> XpService:
    return XpService(pg_sessionmaker, now=lambda: _FIXED_NOW)


class _FailingXpService:
    """A double whose ``award`` always raises — proves D5.1 §3's "learning wins".

    Deliberately duck-typed rather than a real ``XpService`` subclass: the
    only contract ``award_xp_safely`` relies on is a callable ``award`` with
    this shape, and a raising stand-in is the simplest way to prove the
    *caller* survives it.
    """

    def award(
        self,
        user_id: uuid.UUID | str,
        source: XpSource,
        dedupe_key: str,
        *,
        subject_code: str | None = None,
        now: datetime | None = None,
    ) -> XpAwardResult:
        raise RuntimeError("simulated XP infrastructure failure")


def _use_xp_service(client: TestClient, service: object) -> None:
    client.app.dependency_overrides[get_xp_service] = lambda: service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID | str, role: Role = Role.student) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_subject(sm: sessionmaker[Session], code: str = "0625") -> None:
    """``xp_events.subject_code`` is a real FK to ``subjects.code`` (D5.2) —
    every seam test needs a matching row, mirroring ``tests/test_xp_repo.py``.
    """
    from lemely.db.models.academic import Subject

    with sm.begin() as session:
        existing = session.scalars(select(Subject).where(Subject.code == code)).first()
        if existing is None:
            session.add(Subject(code=code, name=code))


def _xp_events(sm: sessionmaker[Session], user_id: uuid.UUID, source: XpSource) -> list[XpEvent]:
    with sm() as session:
        return list(
            session.scalars(
                select(XpEvent).where(XpEvent.user_id == user_id, XpEvent.source == source)
            ).all()
        )


# ---------------------------------------------------------------------------
# Seam 1 — paper_corrected (``AttemptRepository.persist_correction``).
# ---------------------------------------------------------------------------


def _mcq_scheme() -> MarkScheme:
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
    return ExtractedAnswers(
        paper_id="paper",
        source_scan="scan.pdf",
        answers=[
            ExtractedAnswer(question_id="1", answer="A", confidence=0.99),
            ExtractedAnswer(question_id="2", answer="", confidence=0.0),
        ],
    )


@pytest.fixture
def correct_settings(tmp_path: Path) -> Settings:
    base = load_settings()
    data = base.model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    data["gemini_api_key"] = None
    return Settings.model_validate(data)


@pytest.fixture
def correct_client(
    correct_settings: Settings,
    pg_sessionmaker: sessionmaker[Session],
    xp_service: XpService,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, uuid.UUID]]:
    student_id = _seed_user(pg_sessionmaker, Role.student)
    _seed_subject(pg_sessionmaker, "0625")
    upload_repo = StudentUploadRepository(pg_sessionmaker)
    attempt_repo = AttemptRepository(pg_sessionmaker)
    storage_backend = FakeStorageBackend()

    monkeypatch.setattr(student_router_module, "resolve_mark_scheme", lambda *a, **k: _mcq_scheme())
    monkeypatch.setattr(student_router_module, "extract_answers", lambda *a, **k: _extracted())

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: correct_settings
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock(spec=GeminiClient)
    app.dependency_overrides[get_attempt_repo] = lambda: attempt_repo
    app.dependency_overrides[get_student_upload_repo] = lambda: upload_repo
    app.dependency_overrides[get_storage_backend] = lambda: storage_backend
    app.dependency_overrides[get_xp_service] = lambda: xp_service
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(student_id), role="student"
    )
    yield TestClient(app), student_id
    app.dependency_overrides.clear()


def _upload(client: TestClient) -> str:
    up = client.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert up.status_code == 200, up.text
    return str(up.json()["paperId"])


def _correct(client: TestClient, paper_id: str) -> None:
    resp = client.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.status_code == 200, resp.text
    assert "[DONE]" in resp.text


def _upload_and_correct(client: TestClient) -> str:
    paper_id = _upload(client)
    _correct(client, paper_id)
    return paper_id


def test_paper_corrected_awards_xp(
    correct_client: tuple[TestClient, uuid.UUID],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, student_id = correct_client
    paper_id = _upload_and_correct(api)

    events = _xp_events(pg_sessionmaker, student_id, XpSource.paper_corrected)
    assert len(events) == 1
    event = events[0]
    assert event.amount == XP_AMOUNTS[XpSource.paper_corrected] == 50
    assert event.subject_code == "0625"
    # The **upload** id, not the attempt id — see the seam comment in
    # ``student.py`` and D5.3. This assertion is what stops a future change
    # from quietly reverting the key to something re-mintable.
    assert event.dedupe_key == paper_id


def test_re_correcting_the_same_paper_does_not_re_award(
    correct_client: tuple[TestClient, uuid.UUID],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D5.1 §8's opening case, proven through the real HTTP surface.

    "A paper can be re-marked ... none of those may re-award XP." A student
    re-running ``/student/correct`` on the same upload is an ordinary,
    legitimate act: it succeeds, mints a *second* ``Attempt``, and must earn
    nothing new. This is the test that fails if the dedupe key is ever keyed
    on the attempt instead of the upload — which is exactly the defect it was
    written to catch (D5.3).
    """
    api, student_id = correct_client
    paper_id = _upload_and_correct(api)
    _correct(api, paper_id)

    # The re-correction genuinely happened — two attempts exist, so the second
    # award was suppressed by the dedupe constraint rather than by the
    # pipeline having refused to run.
    with pg_sessionmaker() as session:
        assert len(list(session.scalars(select(Attempt)))) == 2

    events = _xp_events(pg_sessionmaker, student_id, XpSource.paper_corrected)
    assert len(events) == 1
    assert events[0].dedupe_key == paper_id


def test_paper_corrected_xp_failure_does_not_fail_correction(
    correct_client: tuple[TestClient, uuid.UUID],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, student_id = correct_client
    _use_xp_service(api, _FailingXpService())

    _upload_and_correct(api)  # must not raise / must not surface an error frame

    with pg_sessionmaker() as session:
        attempts = session.scalars(select(Attempt)).all()
    assert len(attempts) == 1
    assert str(attempts[0].user_id) == str(student_id)
    # And, inversely: no XP row exists — the failure was real, just contained.
    assert _xp_events(pg_sessionmaker, student_id, XpSource.paper_corrected) == []


# ---------------------------------------------------------------------------
# Seam 2 — quiz_completed (``QuizTakingService.submit``).
# ---------------------------------------------------------------------------


@pytest.fixture
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


@pytest.fixture
def bank_service(pg_sessionmaker: sessionmaker[Session]) -> QuestionBankService:
    return QuestionBankService(pg_sessionmaker)


@pytest.fixture
def quiz_service(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    bank_service: QuestionBankService,
) -> QuizService:
    return QuizService(pg_sessionmaker, class_service, bank_service)


@pytest.fixture
def taking_service(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> QuizTakingService:
    return QuizTakingService(pg_sessionmaker, class_service)


class _NoOpMarkingService:
    """Stands in for ``QuizMarkingService`` — these tests care only about ``submit``."""

    def mark_submission(self, submission_id: uuid.UUID) -> None:
        return None


def _seed_bank_row(sm: sessionmaker[Session], *, subject_code: str = "0625") -> uuid.UUID:
    row_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            QuestionBank(
                id=row_id,
                board=ExamBoard.caie,
                subject_code=subject_code,
                source=QuestionSource.generated,
                difficulty=QuestionDifficulty.standard,
                difficulty_source=DifficultySource.declared_by_generator,
                question_type="explanation",
                prompt="Explain photosynthesis.",
                model_answer="model answer",
                mark_scheme_points=["a point"],
                total_marks=3,
            )
        )
    return row_id


def _assigned_quiz(
    quiz_service: QuizService,
    class_service: ClassService,
    sm: sessionmaker[Session],
    *,
    subject_code: str = "0625",
) -> tuple[str, str]:
    teacher = _seed_user(sm, Role.teacher)
    _seed_subject(sm, subject_code)
    _seed_bank_row(sm, subject_code=subject_code)
    created = quiz_service.create_quiz(teacher, subject_code, "Recap quiz")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )
    quiz_service.generate_questions(teacher, created.quiz_id)
    cls = class_service.create_class(teacher, "9A")
    assignment = quiz_service.create_assignment(
        teacher, Role.teacher, created.quiz_id, cls.class_id
    )
    student = _seed_user(sm, Role.student)
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=cls.class_id, student_id=student))
    return str(assignment.assignment_id), str(student)


@pytest.fixture
def quiz_client(
    pg_sessionmaker: sessionmaker[Session],
    taking_service: QuizTakingService,
    xp_service: XpService,
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_quiz_taking_service] = lambda: taking_service
    app.dependency_overrides[get_quiz_marking_service] = lambda: _NoOpMarkingService()
    app.dependency_overrides[get_xp_service] = lambda: xp_service
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_quiz_completed_awards_xp(
    quiz_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    assignment_id, student_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    _auth_as(quiz_client, student_id, Role.student)
    quiz_client.get(f"/api/student/quizzes/{assignment_id}")

    resp = quiz_client.post(f"/api/student/quizzes/{assignment_id}/submit")
    assert resp.status_code == 200, resp.text

    events = _xp_events(pg_sessionmaker, uuid.UUID(student_id), XpSource.quiz_completed)
    assert len(events) == 1
    event = events[0]
    assert event.amount == XP_AMOUNTS[XpSource.quiz_completed] == 30
    assert event.subject_code == "0625"
    assert event.dedupe_key == assignment_id


def test_quiz_completed_second_submit_is_rejected_and_does_not_double_award(
    quiz_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    assignment_id, student_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    _auth_as(quiz_client, student_id, Role.student)
    quiz_client.get(f"/api/student/quizzes/{assignment_id}")

    first = quiz_client.post(f"/api/student/quizzes/{assignment_id}/submit")
    second = quiz_client.post(f"/api/student/quizzes/{assignment_id}/submit")

    assert first.status_code == 200
    assert second.status_code == 422

    events = _xp_events(pg_sessionmaker, uuid.UUID(student_id), XpSource.quiz_completed)
    assert len(events) == 1


def test_quiz_completed_xp_failure_does_not_fail_submit(
    quiz_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> None:
    assignment_id, student_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    _use_xp_service(quiz_client, _FailingXpService())
    _auth_as(quiz_client, student_id, Role.student)
    quiz_client.get(f"/api/student/quizzes/{assignment_id}")

    resp = quiz_client.post(f"/api/student/quizzes/{assignment_id}/submit")

    assert resp.status_code == 200, resp.text
    assert resp.json()["submissionStatus"] == "submitted"
    assert _xp_events(pg_sessionmaker, uuid.UUID(student_id), XpSource.quiz_completed) == []


# ---------------------------------------------------------------------------
# Seam 3 — study_session_completed (``StudyPlanService.complete_session``).
# ---------------------------------------------------------------------------


@pytest.fixture
def study_plan_service(pg_sessionmaker: sessionmaker[Session]) -> StudyPlanService:
    return StudyPlanService(pg_sessionmaker, now=lambda: _FIXED_NOW)


def _seed_weakness_for_plan(
    sm: sessionmaker[Session], student_id: uuid.UUID, *, subject_code: str = "0625"
) -> None:
    from lemely.db.models.attempts import WeaknessRecord
    from lemely.db.models.enums import AttemptOrigin

    _seed_subject(sm, subject_code)
    with sm.begin() as session:
        attempt = Attempt(
            user_id=student_id,
            subject_code=subject_code,
            awarded_marks=2,
            maximum_marks=10,
            percentage=20.0,
            recorded_at=datetime.now(UTC),
            origin=AttemptOrigin.quiz,
        )
        session.add(attempt)
        session.flush()
        session.add(
            WeaknessRecord(
                user_id=student_id,
                attempt_id=attempt.id,
                topic="1 Motion",
                lost_marks=8,
                maximum_marks=10,
                accuracy=0.2,
            )
        )


@pytest.fixture
def study_plan_client(
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
    xp_service: XpService,
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_study_plan_service] = lambda: study_plan_service
    app.dependency_overrides[get_xp_service] = lambda: xp_service
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_study_session_completed_awards_xp(
    study_plan_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    student_id = _seed_user(pg_sessionmaker)
    _seed_weakness_for_plan(pg_sessionmaker, student_id)
    _auth_as(study_plan_client, student_id, Role.student)
    plan = study_plan_service.generate(student_id, "0625")
    session_id = plan.sessions[0].id

    resp = study_plan_client.post(f"/api/student/study-plan/sessions/{session_id}/complete")
    assert resp.status_code == 200, resp.text

    events = _xp_events(pg_sessionmaker, student_id, XpSource.study_session_completed)
    assert len(events) == 1
    event = events[0]
    assert event.amount == XP_AMOUNTS[XpSource.study_session_completed] == 20
    assert event.subject_code == "0625"
    assert event.dedupe_key == str(session_id)


def test_study_session_recompleting_does_not_double_award(
    study_plan_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    student_id = _seed_user(pg_sessionmaker)
    _seed_weakness_for_plan(pg_sessionmaker, student_id)
    _auth_as(study_plan_client, student_id, Role.student)
    plan = study_plan_service.generate(student_id, "0625")
    session_id = plan.sessions[0].id

    first = study_plan_client.post(f"/api/student/study-plan/sessions/{session_id}/complete")
    second = study_plan_client.post(f"/api/student/study-plan/sessions/{session_id}/complete")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["completedAt"] == second.json()["completedAt"]

    events = _xp_events(pg_sessionmaker, student_id, XpSource.study_session_completed)
    assert len(events) == 1


def test_study_session_completed_xp_failure_does_not_fail_completion(
    study_plan_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    student_id = _seed_user(pg_sessionmaker)
    _seed_weakness_for_plan(pg_sessionmaker, student_id)
    _use_xp_service(study_plan_client, _FailingXpService())
    _auth_as(study_plan_client, student_id, Role.student)
    plan = study_plan_service.generate(student_id, "0625")
    session_id = plan.sessions[0].id

    resp = study_plan_client.post(f"/api/student/study-plan/sessions/{session_id}/complete")

    assert resp.status_code == 200, resp.text
    assert resp.json()["completedAt"] is not None
    assert _xp_events(pg_sessionmaker, student_id, XpSource.study_session_completed) == []


# ---------------------------------------------------------------------------
# Seam 4 — flashcard_reviewed (``FlashcardService.record_review``).
# ---------------------------------------------------------------------------


@pytest.fixture
def flashcard_service(pg_sessionmaker: sessionmaker[Session]) -> FlashcardService:
    return FlashcardService(pg_sessionmaker, now=lambda: _FIXED_NOW)


@pytest.fixture
def flashcard_client(
    pg_sessionmaker: sessionmaker[Session],
    flashcard_service: FlashcardService,
    xp_service: XpService,
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_flashcard_service] = lambda: flashcard_service
    app.dependency_overrides[get_xp_service] = lambda: xp_service
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create_deck_and_card(
    client: TestClient, sm: sessionmaker[Session], *, subject_code: str = "0625"
) -> str:
    _seed_subject(sm, subject_code)
    deck_id = client.post(
        "/api/student/flashcards/decks", json={"subjectCode": subject_code, "title": "Deck"}
    ).json()["id"]
    card = client.post(
        f"/api/student/flashcards/decks/{deck_id}/cards", json={"front": "Q", "back": "A"}
    )
    return str(card.json()["id"])


def test_flashcard_reviewed_awards_xp(
    flashcard_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student_id = _seed_user(pg_sessionmaker)
    _auth_as(flashcard_client, student_id, Role.student)
    card_id = _create_deck_and_card(flashcard_client, pg_sessionmaker)

    resp = flashcard_client.post(
        f"/api/student/flashcards/cards/{card_id}/review", json={"grade": "good"}
    )
    assert resp.status_code == 200, resp.text
    review_id = resp.json()["reviewId"]

    events = _xp_events(pg_sessionmaker, student_id, XpSource.flashcard_reviewed)
    assert len(events) == 1
    event = events[0]
    assert event.amount == XP_AMOUNTS[XpSource.flashcard_reviewed] == 1
    assert event.subject_code == "0625"
    assert event.dedupe_key == review_id


def test_flashcard_reviewed_two_reviews_of_the_same_card_both_award(
    flashcard_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Unlike the other three seams, each review is a distinct act — not deduped."""
    student_id = _seed_user(pg_sessionmaker)
    _auth_as(flashcard_client, student_id, Role.student)
    card_id = _create_deck_and_card(flashcard_client, pg_sessionmaker)

    first = flashcard_client.post(
        f"/api/student/flashcards/cards/{card_id}/review", json={"grade": "good"}
    )
    second = flashcard_client.post(
        f"/api/student/flashcards/cards/{card_id}/review", json={"grade": "good"}
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["reviewId"] != second.json()["reviewId"]

    events = _xp_events(pg_sessionmaker, student_id, XpSource.flashcard_reviewed)
    assert len(events) == 2
    assert {e.dedupe_key for e in events} == {first.json()["reviewId"], second.json()["reviewId"]}


def test_flashcard_reviewed_xp_failure_does_not_fail_review(
    flashcard_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student_id = _seed_user(pg_sessionmaker)
    _use_xp_service(flashcard_client, _FailingXpService())
    _auth_as(flashcard_client, student_id, Role.student)
    card_id = _create_deck_and_card(flashcard_client, pg_sessionmaker)

    resp = flashcard_client.post(
        f"/api/student/flashcards/cards/{card_id}/review", json={"grade": "good"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["grade"] == "good"
    assert _xp_events(pg_sessionmaker, student_id, XpSource.flashcard_reviewed) == []


def test_flashcard_reviewed_cap_still_succeeds_and_writes_no_extra_row(
    flashcard_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D5.1 §3: hitting the daily cap never blocks the review itself."""
    student_id = _seed_user(pg_sessionmaker)
    _auth_as(flashcard_client, student_id, Role.student)
    card_id = _create_deck_and_card(flashcard_client, pg_sessionmaker)
    cap = DAILY_SOURCE_CAPS[XpSource.flashcard_reviewed]

    # "again" every time (not "good"): a repeated "good" grade compounds the
    # SM-2 interval exponentially and eventually overflows ``due_at`` well
    # before 61 reviews; "again" resets the interval to 0 on every pass, so
    # the loop below tests the XP cap without also fighting the scheduler.
    for _ in range(cap + 1):
        resp = flashcard_client.post(
            f"/api/student/flashcards/cards/{card_id}/review", json={"grade": "again"}
        )
        assert resp.status_code == 200, resp.text

    events = _xp_events(pg_sessionmaker, student_id, XpSource.flashcard_reviewed)
    assert len(events) == cap
