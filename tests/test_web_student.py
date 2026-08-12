"""Tests for the Student portal endpoints (lemely.web.routers.student).

Every assertion checks *data-backed* behaviour: responses are computed from a
seeded :class:`~lemely.io.history_store.HistoryStore` and the pure-core analytics
(no live Gemini). Structurally-empty fields (leaderboard peers, per-question
theory/integrity for history-sourced papers, subject ranks) are asserted to be
their typed-neutral defaults rather than mock demo numbers.

No Gemini client is exercised anywhere in this module — the one path that did
(``POST /plan``'s ``narrate`` flag) was retired with the route in P4.10 chunk D
(D4.22). Study plans now live on ``/api/student/study-plan`` and onboarding on
``/api/me/student-profile*``, each tested in its own module.
"""

from __future__ import annotations

import uuid
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
from lemely.db.models.enums import Role
from lemely.db.parent_repo import ParentLinkService
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_history_store,
    get_parent_link_service,
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
def client(seeded_store: HistoryStore) -> TestClient:
    """A TestClient whose store + auth resolve to the seeded student."""
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: seeded_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    return TestClient(app)


# ── Overview ──────────────────────────────────────────────────────────────────


def test_overview_subjects_are_aggregated_from_history(client: TestClient) -> None:
    """Overview subject rows aggregate marks per subject with a weighted mean."""
    body = client.get("/api/student/overview").json()

    assert body["studentName"] == STUDENT_ID
    by_code = {row["code"]: row for row in body["subjects"]}
    assert set(by_code) == {"0625", "0620"}

    physics = by_code["0625"]
    # (33 + 38) / (40 + 40) = 88.75 → 89
    assert physics["pct"] == 89
    assert physics["papers"] == 2
    assert physics["grade"] == "A"
    assert physics["barColor"] == "ok"
    # trend = round(95.0 - 82.5) = round(12.5) = 12 (banker's rounding) → improving
    assert physics["trend"] == "+12"
    assert physics["trendUp"] is True

    chem = by_code["0620"]
    assert chem["papers"] == 1
    assert chem["trend"] == "+0"


def test_overview_weak_threads_and_momentum(client: TestClient) -> None:
    """Weak threads fold across papers; momentum has a real 3-point polyline."""
    body = client.get("/api/student/overview").json()

    weak_topics = {t["topic"] for t in body["weakGlobal"]}
    assert "Thermal physics" in weak_topics
    assert "Moles" in weak_topics

    momentum = body["momentum"]
    # Three records → a polyline with M then two L commands.
    assert momentum["path"].startswith("M")
    assert momentum["path"].count("L") == 2
    assert momentum["area"].endswith("Z")
    assert len(momentum["labels"]) == 3


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
    assert body["momentum"]["path"] == ""
    assert body["momentum"]["labels"] == []


# ── Subject ───────────────────────────────────────────────────────────────────


def test_subject_breakdown_and_history(client: TestClient) -> None:
    """Subject endpoint returns per-paper bars, topic map, and paper history."""
    body = client.get("/api/student/subject/0625").json()

    assert body["header"]["title"] == "0625"
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


def test_result_is_data_backed_with_empty_theory(client: TestClient) -> None:
    """Result totals/grade/rail are data-backed; theory is structurally empty."""
    body = client.get("/api/student/result/1").json()  # 2nd record: 38/40

    assert body["awarded"] == 38
    assert body["max"] == 40
    assert body["pct"] == 95
    assert body["grade"] == "A"
    assert body["railLeft"] == 95
    # The A boundary resolves to a real mark line (subject-default for 0625).
    assert body["railFoot"].startswith("A boundary sat at")
    assert body["boundaryYear"] == "2020"
    assert body["provenance"] == "0625_m20_qp_12.pdf"

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


def test_correct_requires_a_body(client: TestClient) -> None:
    """POST /correct now takes a JSON ``{paperId}`` body; a body-less call is 422."""
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
        user_id=STUDENT_ID, role="student"
    )
    api = TestClient(app)
    resp = api.post("/api/student/correct", json={"paperId": "missing"})
    assert resp.status_code == 404
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
