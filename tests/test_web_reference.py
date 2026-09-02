"""Route tests for ``GET /api/reference``.

Self-contained, mirroring ``tests/test_web_me.py``: a throwaway Postgres DB per
test, skipped cleanly when unreachable. Reachable by every authenticated role —
onboarding is a student flow, but seven other screens resolve subject names
through the same payload.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.catalogue_repo import CatalogueService
from lemely.db.models.academic import Subject
from lemely.db.models.catalogue import SubjectTopic, SyllabusPaper
from lemely.db.models.enums import ExamBoard, PaperTier, QualificationLevel, Role
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_catalogue_service

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _server_reachable(url: str) -> bool:
    engine = create_engine(make_url(url).set(database="postgres"))
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


def _seed_catalogue(sm: sessionmaker[Session]) -> None:
    with sm.begin() as s:
        s.add(
            Subject(
                code="0625",
                name="Physics",
                board=ExamBoard.caie,
                active=True,
                qualification_level=QualificationLevel.igcse,
                syllabus_version="2023-2025",
                source_url="https://example.invalid/0625.pdf",
            )
        )
        s.add(
            Subject(
                code="0580",
                name="Mathematics",
                board=ExamBoard.caie,
                active=True,
                qualification_level=QualificationLevel.igcse,
                syllabus_version="2025-2027",
                source_url="https://example.invalid/0580.pdf",
            )
        )
        s.add(Subject(code="9999", name="Retired", board=ExamBoard.caie, active=False))
        s.add(
            SyllabusPaper(
                subject_code="0625",
                paper_number=2,
                name="Multiple Choice (Extended)",
                tier=PaperTier.extended,
                duration_minutes=45,
                total_marks=40,
                practical=False,
                source_document="d.pdf",
                source_url="https://example.invalid/0625.pdf",
                syllabus_version="2023-2025",
            )
        )
        s.add(
            SyllabusPaper(
                subject_code="0625",
                paper_number=1,
                name="Multiple Choice (Core)",
                tier=PaperTier.core,
                duration_minutes=45,
                total_marks=40,
                practical=False,
                source_document="d.pdf",
                source_url="https://example.invalid/0625.pdf",
                syllabus_version="2023-2025",
            )
        )
        s.add(
            SubjectTopic(
                subject_code="0625", code="2", name="Thermal physics", strong=[], keywords=["heat"]
            )
        )
        s.add(
            SubjectTopic(
                subject_code="0625",
                code="1",
                name="Motion, forces and energy",
                strong=[],
                keywords=["force"],
            )
        )


def _authenticate(client: TestClient, role: Role) -> None:
    ctx = AuthContext(user_id=uuid.uuid4(), role=role.value)
    client.app.dependency_overrides[get_auth_context] = lambda: ctx  # type: ignore[union-attr]


def _use_catalogue(client: TestClient, sm: sessionmaker[Session]) -> None:
    service = CatalogueService(sm)
    client.app.dependency_overrides[get_catalogue_service] = lambda: service  # type: ignore[union-attr]


def test_unauthenticated_call_is_401(client: TestClient) -> None:
    assert client.get("/api/reference").status_code == 401


@pytest.mark.parametrize("role", list(Role))
def test_every_authenticated_role_can_read_the_catalogue(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], role: Role
) -> None:
    _seed_catalogue(pg_sessionmaker)
    _authenticate(client, role)
    _use_catalogue(client, pg_sessionmaker)
    assert client.get("/api/reference").status_code == 200


def test_subjects_are_ordered_by_code_and_exclude_inactive(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_catalogue(pg_sessionmaker)
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    body = client.get("/api/reference").json()
    assert [s["code"] for s in body["subjects"]] == ["0580", "0625"]


def test_papers_are_ordered_by_number_and_carry_their_tier(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_catalogue(pg_sessionmaker)
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    physics = next(
        s for s in client.get("/api/reference").json()["subjects"] if s["code"] == "0625"
    )
    assert [(p["number"], p["tier"]) for p in physics["papers"]] == [(1, "core"), (2, "extended")]


def test_topics_are_code_prefixed_strings_in_syllabus_order(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """The `"<code> <name>"` vocabulary `ConfidenceRating.topic` already speaks."""
    _seed_catalogue(pg_sessionmaker)
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    physics = next(
        s for s in client.get("/api/reference").json()["subjects"] if s["code"] == "0625"
    )
    assert physics["topics"] == ["1 Motion, forces and energy", "2 Thermal physics"]


def test_topics_past_ten_stay_in_syllabus_order(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """0606 really has fourteen top-level topics. A text sort returns 1, 10, 11
    before 2 — and S-02 asks about the first three, so text order asks the
    student the wrong questions."""
    with pg_sessionmaker.begin() as s:
        s.add(
            Subject(
                code="0606",
                name="Additional Mathematics",
                board=ExamBoard.caie,
                active=True,
                qualification_level=QualificationLevel.igcse,
            )
        )
        for n in range(1, 15):
            s.add(
                SubjectTopic(
                    subject_code="0606", code=str(n), name=f"Topic {n}", strong=[], keywords=[]
                )
            )
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    subject = next(
        s for s in client.get("/api/reference").json()["subjects"] if s["code"] == "0606"
    )
    assert subject["topics"][:3] == ["1 Topic 1", "2 Topic 2", "3 Topic 3"]
    assert subject["topics"][-1] == "14 Topic 14"


def test_classifier_vocabulary_is_never_served(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """`strong`/`keywords` are Lemely's authored matching terms, not syllabus content."""
    _seed_catalogue(pg_sessionmaker)
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    raw = client.get("/api/reference").text
    assert "keywords" not in raw
    assert "strong" not in raw


def test_an_empty_catalogue_is_an_empty_list_not_an_error(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    response = client.get("/api/reference")
    assert response.status_code == 200
    assert response.json()["subjects"] == []


def test_enumerations_mirror_the_backend_enums(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    _authenticate(client, Role.student)
    _use_catalogue(client, pg_sessionmaker)
    body = client.get("/api/reference").json()
    assert [q["value"] for q in body["qualificationLevels"]] == [
        "igcse",
        "o_level",
        "as_level",
        "a_level",
    ]
    assert [m["value"] for m in body["sessionMonths"]] == [
        "may_june",
        "oct_nov",
        "feb_mar",
        "specimen",
    ]
    assert body["difficultyBands"] == ["foundation", "standard", "challenge"]
