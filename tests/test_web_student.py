"""Tests for the Student portal endpoints (lemely.web.routers.student).

Every assertion checks *data-backed* behaviour: responses are computed from a
seeded :class:`~lemely.io.history_store.HistoryStore` and the pure-core analytics
(no live Gemini). Structurally-empty fields (leaderboard peers, per-question
theory/integrity for history-sourced papers, subject ranks) are asserted to be
their typed-neutral defaults rather than mock demo numbers.

No Gemini client is exercised anywhere in this module except by
``test_correct_succeeds_once_verified``, which needs a genuine ``complete``
frame (not merely "not 403") to prove D7.5's verified-email gate — the one
path that did before it was retired with ``POST /plan`` in P4.10 chunk D
(D4.22) — and mocks it the same way ``tests/test_student_correct.py`` does
(never a live call; MISSION §8 / the suite-wide guard in ``conftest.py``
would raise if it tried). Study plans now live on ``/api/student/study-plan``
and onboarding on ``/api/me/student-profile*``, each tested in its own module.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db.base import Base
from lemely.db.models import User
from lemely.db.models.enums import QualificationLevel, Role
from lemely.db.parent_repo import ParentLinkService
from lemely.db.student_profile_repo import StudentProfileService
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_history_store,
    get_parent_link_service,
    get_student_profile_service,
    get_user_mirror,
)

STUDENT_ID = "maya"


def _record(
    *,
    subject_code: str = "0625",
    paper_number: int = 1,
    paper_variant: int = 2,
    session_year: int = 2020,
    awarded: int = 38,
    maximum: int = 40,
    percentage: float = 95.0,
    grade: str = "A",
    weak_areas: list[WeakArea] | None = None,
    recorded_at: str = "2020-06-01T10:00:00+00:00",
    source_document: str | None = None,
) -> PaperRecord:
    """Build a :class:`PaperRecord` with sensible defaults for seeding history."""
    return PaperRecord(
        student_id=STUDENT_ID,
        metadata=ExamMetadata(
            subject_code=subject_code,
            paper_number=paper_number,
            paper_variant=paper_variant,
            session_month="May/June",
            session_year=session_year,
            source_document=source_document,
        ),
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=percentage,
        grade=grade,
        weak_areas=weak_areas or [],
        recorded_at=recorded_at,
    )


def _weak(topic: str, lost: int, maximum: int) -> WeakArea:
    """Build a :class:`WeakArea` with accuracy derived from lost/maximum."""
    return WeakArea(
        topic=topic,
        lost_marks=lost,
        maximum_marks=maximum,
        accuracy=round(1.0 - lost / maximum, 4),
        question_ids=[f"{topic[:2]}1"],
    )


@pytest.fixture
def seeded_store(tmp_path: Path) -> HistoryStore:
    """A HistoryStore with a multi-subject, multi-paper history for STUDENT_ID."""
    store = HistoryStore(tmp_path / "history")
    store.append(
        STUDENT_ID,
        _record(
            paper_number=1,
            awarded=33,
            maximum=40,
            percentage=82.5,
            grade="A",
            recorded_at="2020-03-01T10:00:00+00:00",
            source_document="0625_m20_qp_11.pdf",
            weak_areas=[_weak("Thermal physics", 4, 10)],
        ),
    )
    store.append(
        STUDENT_ID,
        _record(
            paper_number=1,
            awarded=38,
            maximum=40,
            percentage=95.0,
            grade="A",
            recorded_at="2020-06-01T10:00:00+00:00",
            source_document="0625_m20_qp_12.pdf",
            weak_areas=[_weak("Thermal physics", 2, 10), _weak("Waves", 3, 12)],
        ),
    )
    store.append(
        STUDENT_ID,
        _record(
            subject_code="0620",
            paper_number=4,
            paper_variant=1,
            awarded=45,
            maximum=80,
            percentage=56.25,
            grade="D",
            recorded_at="2020-06-02T10:00:00+00:00",
            weak_areas=[_weak("Moles", 20, 40)],
        ),
    )
    return store


@pytest.fixture
def profile_service() -> MagicMock:
    mock = MagicMock()
    mock.list_enrolments.return_value = []
    return mock


@pytest.fixture
def client(seeded_store: HistoryStore, profile_service: MagicMock) -> TestClient:
    """A TestClient whose store + auth resolve to the seeded student."""
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: seeded_store
    app.dependency_overrides[get_student_profile_service] = lambda: profile_service
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    return TestClient(app)


# ── Overview ──────────────────────────────────────────────────────────────────


def test_overview_subjects_are_aggregated_from_history(client: TestClient) -> None:
    """Overview subject rows aggregate marks per subject with a weighted mean.

    `physics["grade"]` is resolved (`_grade_for`) against the most recent
    record's real, ingested CAIE boundaries for 0625 paper 1 -- "Multiple
    Choice (Core)" (`syllabus_papers.tier="core"`). Cambridge caps Core at
    grade C: its component thresholds publish C-G only, no A/B, because Core
    exists for candidates targeting C or below. So an 89% average on this
    paper is correctly awarded a C, not the A it would be worth on an
    Extended paper -- the old "A" expectation predated the reference-data
    migration and awarded a grade Cambridge's own Core-tier papers cannot
    give. See `test_result_is_data_backed_with_empty_theory` (seeds an
    Extended paper instead) for this same reference data's A-boundary path.
    """
    body = client.get("/api/student/overview").json()

    # `STUDENT_ID` ("maya") is this file's friendly string id for the
    # HistoryStore fixture, not a real auth UUID — no `public.users` row
    # exists to resolve a display name against, so `studentName` is the
    # router's typed-neutral default rather than echoing the id back
    # (regression test: this endpoint used to literally return the caller's
    # raw id/UUID as their "name").
    assert body["studentName"] == ""
    by_code = {row["code"]: row for row in body["subjects"]}
    assert set(by_code) == {"0625", "0620"}

    physics = by_code["0625"]
    # (33 + 38) / (40 + 40) = 88.75 → 89
    assert physics["pct"] == 89
    assert physics["papers"] == 2
    # Core-tier cap (see docstring): 89% clears every published boundary
    # (C:58.79 D:51.21 E:45.21 F:38.33 G:32.29) but Core publishes no A/B,
    # so the highest awardable grade on this paper is C.
    assert physics["grade"] == "C"
    assert physics["barColor"] == "ok"
    # trend = round(95.0 - 82.5) = round(12.5) = 12 (banker's rounding) → improving
    assert physics["trend"] == "+12"
    assert physics["trendUp"] is True

    chem = by_code["0620"]
    assert chem["papers"] == 1
    assert chem["trend"] == "+0"


def test_overview_subject_name_is_real_and_qualification_level_is_included(
    client: TestClient, profile_service: MagicMock
) -> None:
    """SubjectRowDTO.name is a real human name (not the code), and qualificationLevel
    is sourced from the student's enrolment when one exists."""
    profile_service.list_enrolments.return_value = [
        SimpleNamespace(subject_code="0625", qualification_level=QualificationLevel.igcse),
    ]

    body = client.get("/api/student/overview").json()

    by_code = {row["code"]: row for row in body["subjects"]}
    assert by_code["0625"]["name"] == "Physics"
    assert by_code["0625"]["qualificationLevel"] == "igcse"
    # "0620" has no matching enrolment in the fixture — no level, and the
    # unsupported code falls back to itself rather than an invented name.
    assert by_code["0620"]["name"] == "0620"
    assert by_code["0620"]["qualificationLevel"] is None


def test_overview_weak_threads_and_momentum(client: TestClient) -> None:
    """Weak threads fold across papers; momentum has a real 3-point series."""
    body = client.get("/api/student/overview").json()

    weak_topics = {t["topic"] for t in body["weakGlobal"]}
    assert "Thermal physics" in weak_topics
    assert "Moles" in weak_topics

    points = body["momentum"]["points"]
    assert len(points) == 3
    # Every point carries its own timestamp and its percentage as recorded.
    assert all(p["recordedAt"] and isinstance(p["percentage"], (int, float)) for p in points)
    # Oldest first: the frontend plots by position and never re-sorts.
    assert [p["recordedAt"] for p in points] == sorted(p["recordedAt"] for p in points)


class _PgUserMirror:
    """Minimal :class:`~lemely.auth.mirror.UserMirror` bound to a test sessionmaker."""

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

    def upsert(self, *args: object, **kwargs: object) -> None:  # pragma: no cover - unused here
        raise NotImplementedError


def _pg_overview_client(
    pg_sessionmaker: sessionmaker[Session], history_store: HistoryStore, user_id: uuid.UUID
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: history_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(user_id), role="student"
    )
    app.dependency_overrides[get_user_mirror] = lambda: _PgUserMirror(pg_sessionmaker)
    return TestClient(app)


def test_overview_student_name_is_the_real_display_name_not_the_raw_id(
    pg_sessionmaker: sessionmaker[Session], tmp_path: Path
) -> None:
    """``studentName`` resolves the caller's mirrored display name.

    Regression test: ``GET /student/overview`` used to set ``studentName`` to
    the bare ``auth.user_id`` (a UUID), so the dashboard greeted every student
    by their own id instead of their name.
    """
    uid = _seed_pg_user(pg_sessionmaker, Role.student, display_name="Maya Chen")
    client = _pg_overview_client(pg_sessionmaker, HistoryStore(tmp_path / "history"), uid)

    body = client.get("/api/student/overview").json()

    assert body["studentName"] == "Maya Chen"


def test_overview_student_name_falls_back_to_email_without_a_display_name(
    pg_sessionmaker: sessionmaker[Session], tmp_path: Path
) -> None:
    """No ``display_name`` set falls back to ``email``, never the raw user id."""
    uid = _seed_pg_user(pg_sessionmaker, Role.student, display_name=None)
    client = _pg_overview_client(pg_sessionmaker, HistoryStore(tmp_path / "history"), uid)

    body = client.get("/api/student/overview").json()

    assert body["studentName"] == f"{uid}@example.com"


def test_overview_momentum_percentages_are_never_rescaled(tmp_path: Path) -> None:
    """A percentage under 55 survives to the wire untouched.

    Regression test for the defect P5.3 removed: ``_momentum`` used to map
    55-100% onto an 88px viewbox, so 40% was emitted as y=114 — past the bottom
    of the box, in an element the frontend rendered ``overflow-visible``. The
    student whose line left the chart was, by construction, the one doing worst.
    The wire now carries percentages, so there is no band to fall out of.
    """
    store = HistoryStore(tmp_path / "low")
    for pct, grade, when in (
        (38.0, "U", "2020-06-01T10:00:00+00:00"),
        (44.0, "E", "2020-07-01T10:00:00+00:00"),
    ):
        store.append(STUDENT_ID, _record(percentage=pct, grade=grade, recorded_at=when))
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    body = TestClient(app).get("/api/student/overview").json()

    assert [p["percentage"] for p in body["momentum"]["points"]] == [38.0, 44.0]


def test_overview_empty_history_is_neutral(tmp_path: Path) -> None:
    """With no history, momentum is empty and there are no subject rows."""
    store = HistoryStore(tmp_path / "empty")
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id="nobody", role="student"
    )
    body = TestClient(app).get("/api/student/overview").json()

    assert body["subjects"] == []
    assert body["weakGlobal"] == []
    assert body["momentum"]["points"] == []


def test_overview_malformed_id_returns_200_not_500(
    pg_sessionmaker: sessionmaker[Session], tmp_path: Path
) -> None:
    """A non-UUID ``auth.user_id`` degrades to neutral defaults, not a 500.

    Regression test: ``StudentProfileService.list_enrolments`` calls
    ``_as_uuid()`` unconditionally and raises ``ValueError`` for a non-UUID
    string. The route must guard that call the same way it already guards
    the ``mirror.get_by_id`` lookup, so a friendly string id (what hermetic
    history-store tests use) never reaches the DB layer. Uses the real,
    unmocked :class:`StudentProfileService` bound to a live Postgres
    sessionmaker — a mock would not have caught this regression.
    """
    store = HistoryStore(tmp_path / "history")
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_student_profile_service] = lambda: StudentProfileService(
        pg_sessionmaker
    )
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id="not-a-uuid", role="student"
    )
    response = TestClient(app).get("/api/student/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["subjects"] == []
    assert body["studentName"] == ""


# ── Subject ───────────────────────────────────────────────────────────────────


def test_subject_breakdown_and_history(client: TestClient, profile_service: MagicMock) -> None:
    """Subject endpoint returns per-paper bars, topic map, and paper history."""
    profile_service.list_enrolments.return_value = [
        SimpleNamespace(subject_code="0625", qualification_level=QualificationLevel.o_level),
    ]

    body = client.get("/api/student/subject/0625").json()

    assert body["header"]["name"] == "Physics"
    assert body["header"]["code"] == "0625"
    assert body["header"]["qualificationLevel"] == "o_level"
    assert body["header"]["weightedMean"] == "89"

    breakdown = body["papersBreakdown"]
    assert len(breakdown) == 1  # both papers share paper_number 1
    bars = breakdown[0]["bars"]
    assert [b["value"] for b in bars] == [82, 95]  # rounded percentages, in order
    assert bars[-1]["highlight"] is True

    topics = {t["name"] for t in body["topicMap"]}
    assert "Thermal physics" in topics
    assert "Waves" in topics

    # Paper history is newest-first and shows the mark fraction.
    assert body["paperHistory"][0]["marks"] == "38/40"
    assert body["paperHistory"][0]["grade"] == "A"

    # `id` addresses the row's position in the FULL history (record 1 = the
    # 2nd-appended 38/40 paper; record 0 = the 1st-appended 33/40 paper), and
    # round-trips through GET /student/result/{id} to the same paper.
    assert body["paperHistory"][0]["id"] == "1"
    assert body["paperHistory"][1]["id"] == "0"
    result_0 = client.get(f"/api/student/result/{body['paperHistory'][0]['id']}").json()
    assert result_0["awarded"] == 38
    assert result_0["max"] == 40
    result_1 = client.get(f"/api/student/result/{body['paperHistory'][1]['id']}").json()
    assert result_1["awarded"] == 33
    assert result_1["max"] == 40


def test_subject_malformed_id_returns_200_not_500(
    pg_sessionmaker: sessionmaker[Session], tmp_path: Path
) -> None:
    """A non-UUID ``auth.user_id`` degrades to no enrolment, not a 500.

    Regression test: ``StudentProfileService.list_enrolments`` calls
    ``_as_uuid()`` unconditionally and raises ``ValueError`` for a non-UUID
    string. The route must guard that call the same way ``student_overview``
    does, so a friendly string id (what hermetic history-store tests use)
    never reaches the DB layer. Uses the real, unmocked
    :class:`StudentProfileService` bound to a live Postgres sessionmaker — a
    mock would not have caught this regression.
    """
    store = HistoryStore(tmp_path / "history")
    store.append("not-a-uuid", _record(subject_code="0625"))
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_student_profile_service] = lambda: StudentProfileService(
        pg_sessionmaker
    )
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id="not-a-uuid", role="student"
    )
    response = TestClient(app).get("/api/student/subject/0625")

    assert response.status_code == 200
    body = response.json()
    assert body["header"]["code"] == "0625"
    assert body["header"]["qualificationLevel"] is None


def test_subject_unknown_code_is_404(client: TestClient) -> None:
    """A subject with no recorded papers returns 404."""
    assert client.get("/api/student/subject/9999").status_code == 404


@pytest.fixture
def interleaved_store(tmp_path: Path) -> HistoryStore:
    """History with two subjects' papers INTERLEAVED in append order.

    Full-history indices: 0=0625, 1=0620, 2=0625, 3=0620. A per-subject-filtered
    index (e.g. enumerating only the subject's own records) would mislabel the
    newest 0625 paper (full index 2) as index "1" — this fixture is built so
    that bug would produce a *different, wrong* id and a broken round-trip to
    ``GET /student/result/{id}``, rather than accidentally matching by luck.
    """
    store = HistoryStore(tmp_path / "history")
    store.append(  # full index 0: 0625, oldest
        STUDENT_ID,
        _record(
            subject_code="0625",
            paper_number=1,
            awarded=10,
            maximum=20,
            percentage=50.0,
            grade="C",
            recorded_at="2020-01-01T10:00:00+00:00",
        ),
    )
    store.append(  # full index 1: 0620, oldest
        STUDENT_ID,
        _record(
            subject_code="0620",
            paper_number=1,
            awarded=15,
            maximum=20,
            percentage=75.0,
            grade="B",
            recorded_at="2020-02-01T10:00:00+00:00",
        ),
    )
    store.append(  # full index 2: 0625, newest — the row a naive bug mislabels
        STUDENT_ID,
        _record(
            subject_code="0625",
            paper_number=2,
            awarded=18,
            maximum=20,
            percentage=90.0,
            grade="A",
            recorded_at="2020-03-01T10:00:00+00:00",
        ),
    )
    store.append(  # full index 3: 0620, newest
        STUDENT_ID,
        _record(
            subject_code="0620",
            paper_number=2,
            awarded=19,
            maximum=20,
            percentage=95.0,
            grade="A",
            recorded_at="2020-04-01T10:00:00+00:00",
        ),
    )
    return store


@pytest.fixture
def interleaved_client(interleaved_store: HistoryStore) -> TestClient:
    """A TestClient whose store + auth resolve to the interleaved-history student."""
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: interleaved_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    return TestClient(app)


def test_subject_history_id_addresses_full_history_not_filtered_subset(
    interleaved_client: TestClient,
) -> None:
    """`paperHistory[i].id` is the FULL-history index, even with interleaved subjects.

    This is the D2.7 regression: a per-subject-filtered index would give the
    newest 0625 paper (full index 2) the wrong id "1" (its position within the
    2-item 0625-only subset) and round-trip to the wrong (0620) paper.
    """
    body = interleaved_client.get("/api/student/subject/0625").json()
    rows = body["paperHistory"]
    assert len(rows) == 2

    # Newest-first: full index 2 (18/20) then full index 0 (10/20).
    assert rows[0]["id"] == "2"
    assert rows[0]["marks"] == "18/20"
    assert rows[1]["id"] == "0"
    assert rows[1]["marks"] == "10/20"

    # Round-trip: each id must resolve, via the FULL-history-indexed result
    # endpoint, back to a 0625 paper with matching marks — not the 0620 paper
    # that a naive filtered-subset index would collide with.
    for row in rows:
        result = interleaved_client.get(f"/api/student/result/{row['id']}").json()
        assert result["code"] == "0625"
        assert f"{result['awarded']}/{result['max']}" == row["marks"]


# ── Paper result (flagship) ───────────────────────────────────────────────────


def test_result_is_data_backed_with_empty_theory(tmp_path: Path) -> None:
    """Result totals/grade/rail are data-backed; theory is structurally empty.

    Deliberately does NOT reuse the module's shared `client`/`seeded_store`
    fixtures: both of their 0625 records are paper 1 ("Multiple Choice
    (Core)", `syllabus_papers.tier="core"`), which `test_subject_breakdown_and_history`
    relies on ("both papers share paper_number 1"). Cambridge caps Core at
    grade C -- its real ingested thresholds carry no A boundary at all -- so
    a Core record can never exercise `railFoot`'s "A boundary sat at ..."
    line; see `test_overview_subjects_are_aggregated_from_history` for that
    same Core-cap consequence on the aggregation path. This test seeds its
    own one-record store on 0625 paper 2 ("Multiple Choice (Extended)",
    `tier="extended"`) instead, to keep the A-boundary rail-foot format under
    real, data-backed coverage rather than losing it to an empty-string
    assertion.
    """
    store = HistoryStore(tmp_path / "history")
    store.append(
        STUDENT_ID,
        _record(
            paper_number=2,
            awarded=38,
            maximum=40,
            percentage=95.0,
            grade="A",
            recorded_at="2020-06-01T10:00:00+00:00",
            source_document="0625_m20_qp_22.pdf",
        ),
    )
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    body = TestClient(app).get("/api/student/result/0").json()

    assert body["awarded"] == 38
    assert body["max"] == 40
    assert body["pct"] == 95
    assert body["grade"] == "A"
    assert body["railLeft"] == 95
    # 0625 paper 2 (Extended) publishes a real A boundary (subject-default,
    # no exact-variant data for this session).
    assert body["railFoot"].startswith("A boundary sat at")
    assert body["boundaryYear"] == "2020"
    assert body["provenance"] == "0625_m20_qp_22.pdf"

    # Structurally empty: history records persist no per-question detail.
    assert body["theory"] == []
    # Integrity has exactly the boundary-provenance row we *can* assert. This
    # variant has no exact-match boundary data, so the source is subject-default
    # and the row is a neutral "dash" rather than a fabricated "check".
    assert len(body["integrity"]) == 1
    assert body["integrity"][0]["label"] == "Grade boundary resolved"
    assert body["integrity"][0]["mark"] == "dash"


def test_result_unknown_id_is_404(client: TestClient) -> None:
    """An out-of-range or non-numeric paper id returns 404."""
    assert client.get("/api/student/result/99").status_code == 404
    assert client.get("/api/student/result/notanum").status_code == 404


def test_result_negative_index_is_404(client: TestClient) -> None:
    """A negative index must 404, not wrap around to a tail record (regression)."""
    # The store has 3 records; ``-1`` would be a valid Python index (the last
    # record) but is an invalid forward paper position and must be rejected.
    assert client.get("/api/student/result/-1").status_code == 404
    assert client.get("/api/student/result/-99").status_code == 404


# ── Correct a paper (SSE) ─────────────────────────────────────────────────────
#
# D7.5 gates this one route on a verified email (``lemely.web.deps.require_verified_email``,
# reading ``users.email_verified_at``), so every test below that reaches the
# handler body now needs a caller the mirror actually resolves as verified —
# `seeded_store`'s friendly string id ("maya") is not a UUID and cannot stand
# in here the way it does for the read-only Overview/Subject routes above,
# which never touch the mirror at all. `_verified_mirror` is the smallest
# double that satisfies the gate.


def _verified_mirror() -> MagicMock:
    """A ``UserMirror`` double whose ``get_by_id`` always reports verified."""
    mirror = MagicMock()
    mirror.get_by_id.return_value = SimpleNamespace(email_verified_at="2020-01-01T00:00:00+00:00")
    return mirror


def test_correct_requires_a_body(client: TestClient) -> None:
    """POST /correct now takes a JSON ``{paperId}`` body; a body-less call is 422."""
    student_id = uuid.uuid4()
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(student_id), role="student"
    )
    client.app.dependency_overrides[get_user_mirror] = _verified_mirror  # type: ignore[union-attr]

    assert client.post("/api/student/correct").status_code == 422


def test_correct_unknown_paper_is_404(seeded_store: HistoryStore) -> None:
    """POST /correct 404s for a paper the caller does not own (checked pre-stream).

    The upload-ownership lookup is stubbed to ``None`` (as it would be for an
    unknown or foreign paperId), so the endpoint returns a clean 404 before any
    SSE streaming begins — the full persist path is covered by
    ``tests/test_student_correct.py`` against a real database.
    """
    from lemely.web.deps import get_student_upload_repo

    upload_repo = MagicMock()
    upload_repo.get_owned_upload.return_value = None

    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: seeded_store
    app.dependency_overrides[get_student_upload_repo] = lambda: upload_repo
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(uuid.uuid4()), role="student"
    )
    app.dependency_overrides[get_user_mirror] = _verified_mirror
    api = TestClient(app)
    resp = api.post("/api/student/correct", json={"paperId": "missing"})
    assert resp.status_code == 404
    app.dependency_overrides.clear()


def test_correct_is_403_for_an_unverified_account(seeded_store: HistoryStore) -> None:
    """D7.5: the Gemini spend is the gated operation.

    ``require_verified_email`` (``lemely.web.deps``) runs as a dependency
    ahead of every other collaborator this route declares, so a rejection
    here never touches the upload repo, Gemini, or storage — this override
    map is deliberately as bare as ``test_correct_requires_a_body``'s,
    proving that nothing past the gate needs to be wired for the gate itself
    to fire correctly.
    """
    mirror = MagicMock()
    mirror.get_by_id.return_value = SimpleNamespace(email_verified_at=None)

    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: seeded_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(uuid.uuid4()), role="student"
    )
    app.dependency_overrides[get_user_mirror] = lambda: mirror
    api = TestClient(app)

    resp = api.post("/api/student/correct", json={"paperId": str(uuid.uuid4())})

    assert resp.status_code == 403, resp.text
    # A stable, machine-readable marker — never prose (spec §4.6) — the
    # frontend's `lib/authOutcome.ts`-family outcome modules match on.
    assert resp.json()["detail"] == {"code": "email_unverified"}
    app.dependency_overrides.clear()


def test_upload_is_not_gated_by_verification(seeded_store: HistoryStore) -> None:
    """Deliberate: a student who has already photographed a paper must not
    lose the capture to a verification wall. D7.5 gates marking, not upload.

    Same unverified mirror as ``test_correct_is_403_for_an_unverified_account``
    — the only variable that changes is the route. Upload's own collaborators
    (repo, storage) are mocked to succeed cleanly so a genuine 200 is the
    proof, rather than merely tolerating "any error that is not a 403" —
    which an unrelated 500 from an unmocked collaborator would also satisfy
    and so would prove nothing.
    """
    from lemely.web.deps import get_storage_backend, get_student_upload_repo

    mirror = MagicMock()
    mirror.get_by_id.return_value = SimpleNamespace(email_verified_at=None)
    upload_repo = MagicMock()

    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: seeded_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(uuid.uuid4()), role="student"
    )
    app.dependency_overrides[get_user_mirror] = lambda: mirror
    app.dependency_overrides[get_student_upload_repo] = lambda: upload_repo
    app.dependency_overrides[get_storage_backend] = lambda: MagicMock()
    api = TestClient(app)

    resp = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["paperId"]
    upload_repo.create_upload.assert_called_once()
    app.dependency_overrides.clear()


def test_correct_succeeds_once_verified(
    pg_sessionmaker: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other direction. A guard asserted one way could be permanently
    closed and still pass.

    Deliberately the *full* happy path — Gemini mocked, extraction
    monkeypatched, real Postgres-backed repos, exactly the recipe
    ``tests/test_student_correct.py`` uses — rather than merely asserting
    "not 403": a verified caller must reach a genuine ``complete`` SSE frame,
    not just some other failure that happens not to be the gate's.
    """
    from lemely.core.loose_schemas import MarkScheme
    from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
    from lemely.db.attempt_repo import AttemptRepository
    from lemely.db.upload_repo import StudentUploadRepository
    from lemely.io.gemini import GeminiClient
    from lemely.runtime.config import Settings, load_settings
    from lemely.web.deps import (
        get_attempt_repo,
        get_gemini_client,
        get_settings,
        get_storage_backend,
        get_student_upload_repo,
    )
    from lemely.web.routers import student as student_router_module
    from tests.storage_fakes import FakeStorageBackend

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
                    "maximum_mark": 1,
                    "scheme_format": "mcq",
                },
                "questions": [{"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"}],
            }
        )

    def _extracted() -> ExtractedAnswers:
        return ExtractedAnswers(
            paper_id="paper",
            source_scan="scan.pdf",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.99)],
        )

    verified_at = datetime.now(UTC)
    student_id = _seed_pg_user(pg_sessionmaker, Role.student, email_verified_at=verified_at)

    base = load_settings()
    data = base.model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    data["gemini_api_key"] = None  # forces the no-key branch; no ScanMetadataExtractor call
    settings = Settings.model_validate(data)

    monkeypatch.setattr(student_router_module, "resolve_mark_scheme", lambda *a, **k: _mcq_scheme())
    monkeypatch.setattr(student_router_module, "extract_answers", lambda *a, **k: _extracted())

    # ONE instance, captured by both overrides below: `get_storage_backend` is
    # re-resolved on every request, so a lambda that constructed a fresh
    # `FakeStorageBackend()` per call would silently read back from an empty
    # store on `/correct` — the upload it needs to grade would never have
    # been written to *this* instance.
    storage_backend = FakeStorageBackend()

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock(spec=GeminiClient)
    app.dependency_overrides[get_attempt_repo] = lambda: AttemptRepository(pg_sessionmaker)
    app.dependency_overrides[get_student_upload_repo] = lambda: StudentUploadRepository(
        pg_sessionmaker
    )
    app.dependency_overrides[get_storage_backend] = lambda: storage_backend
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(student_id), role="student"
    )
    app.dependency_overrides[get_user_mirror] = lambda: _PgUserMirror(pg_sessionmaker)
    api = TestClient(app)

    up = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert up.status_code == 200, up.text
    paper_id = up.json()["paperId"]

    resp = api.post("/api/student/correct", json={"paperId": paper_id})

    assert resp.status_code == 200, resp.text
    assert '"phase": "complete"' in resp.text
    assert "[DONE]" in resp.text
    app.dependency_overrides.clear()


# ── Standings ─────────────────────────────────────────────────────────────────


def test_standings_counts_are_data_backed_ranks_empty(client: TestClient) -> None:
    """Standings paper/streak counts are real; subject ranks are structurally empty."""
    body = client.get("/api/student/standings").json()

    assert body["paperCount"] == 3
    # Three distinct recorded-paper calendar days.
    assert body["streakDays"] == 3

    ranks = {r["code"]: r for r in body["subjectRanks"]}
    assert ranks["0625"]["papers"] == 2
    assert ranks["0620"]["papers"] == 1
    # No cohort → every rank string is empty (no fabricated leaderboard position).
    assert all(r["rank"] == "" for r in body["subjectRanks"])


# ── Parent links (invite/list/revoke, D3.11/P3.6a) ──────────────────────────
#
# Postgres-backed (mirrors ``tests/test_web_classes.py``'s ``student_join_by_code``
# tests): the parent-link routes need real ``users`` rows, so ``STUDENT_ID = "maya"``
# (the file's default, string-keyed history fixture) cannot stand in as the
# caller here. Self-contained rather than shared via conftest, matching every
# other ``test_web_*.py`` file's ``pg_sessionmaker`` duplication convention.


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
def parent_link_service(pg_sessionmaker: sessionmaker[Session]) -> ParentLinkService:
    return ParentLinkService(pg_sessionmaker)


@pytest.fixture
def parent_links_client(parent_link_service: ParentLinkService) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_parent_link_service] = lambda: parent_link_service
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_pg_user(
    sm: sessionmaker[Session],
    role: Role,
    *,
    display_name: str | None = None,
    phone: str | None = None,
    email_verified_at: datetime | None = None,
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(
                id=uid,
                email=f"{uid}@example.com",
                role=role,
                display_name=display_name,
                phone=phone,
                email_verified_at=email_verified_at,
            )
        )
    return uid


def _auth_as_pg(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def test_student_lists_no_parents_when_none_linked(
    parent_links_client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_pg_user(pg_sessionmaker, Role.student)
    _auth_as_pg(parent_links_client, student, Role.student)

    assert parent_links_client.get("/api/student/parent-links").json() == {"parents": []}


def test_student_links_a_parent_by_phone_then_lists_it(
    parent_links_client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_pg_user(pg_sessionmaker, Role.student)
    parent = _seed_pg_user(pg_sessionmaker, Role.parent, display_name="Mum", phone="+15551230000")
    _auth_as_pg(parent_links_client, student, Role.student)

    resp = parent_links_client.post("/api/student/parent-links", json={"phone": "+15551230000"})
    assert resp.status_code == 200
    assert resp.json() == {"parentId": str(parent), "displayName": "Mum", "phone": "+15551230000"}

    listing = parent_links_client.get("/api/student/parent-links").json()
    assert listing["parents"] == [
        {"parentId": str(parent), "displayName": "Mum", "phone": "+15551230000"}
    ]


def test_student_link_unknown_phone_is_a_clean_404(
    parent_links_client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """No existing ``role=parent`` account for this phone — never auto-created (D3.11)."""
    student = _seed_pg_user(pg_sessionmaker, Role.student)
    _auth_as_pg(parent_links_client, student, Role.student)

    resp = parent_links_client.post("/api/student/parent-links", json={"phone": "+15559999999"})
    assert resp.status_code == 404


def test_student_link_is_idempotent_over_http(
    parent_links_client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_pg_user(pg_sessionmaker, Role.student)
    _seed_pg_user(pg_sessionmaker, Role.parent, phone="+15550001234")
    _auth_as_pg(parent_links_client, student, Role.student)

    first = parent_links_client.post("/api/student/parent-links", json={"phone": "+15550001234"})
    second = parent_links_client.post("/api/student/parent-links", json={"phone": "+15550001234"})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(parent_links_client.get("/api/student/parent-links").json()["parents"]) == 1


def test_student_unlink_then_list_shows_the_parent_gone(
    parent_links_client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_pg_user(pg_sessionmaker, Role.student)
    parent = _seed_pg_user(pg_sessionmaker, Role.parent, phone="+15550005678")
    _auth_as_pg(parent_links_client, student, Role.student)
    parent_links_client.post("/api/student/parent-links", json={"phone": "+15550005678"})

    resp = parent_links_client.delete(f"/api/student/parent-links/{parent}")

    assert resp.status_code == 204
    assert parent_links_client.get("/api/student/parent-links").json() == {"parents": []}


def test_student_unlink_absent_link_is_a_silent_no_op(
    parent_links_client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_pg_user(pg_sessionmaker, Role.student)
    _auth_as_pg(parent_links_client, student, Role.student)

    resp = parent_links_client.delete(f"/api/student/parent-links/{uuid.uuid4()}")

    assert resp.status_code == 204


def test_student_unlink_malformed_parent_id_is_422(
    parent_links_client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_pg_user(pg_sessionmaker, Role.student)
    _auth_as_pg(parent_links_client, student, Role.student)

    resp = parent_links_client.delete("/api/student/parent-links/not-a-uuid")

    assert resp.status_code == 422
