"""HTTP-layer tests for the parent-portal endpoints (D3.11/P3.6 chunk A).

Exercises P-01..P-04 (``lemely.web.routers.parent``) against a real
:class:`~lemely.db.parent_repo.ParentLinkService` and
:class:`~lemely.db.class_repo.ClassService` bound to a throwaway Postgres
database (mirrors ``tests/test_web_teacher.py``'s Postgres-backed fixture
block) with a real :class:`~lemely.io.history_store.HistoryStore` for the
history side. Proves:

* A parent reaches every screen for a real linked child, and gets a clean 403
  for a real, *unlinked* student — including the two-parent/two-child
  disjoint-link regression (parent A must never see child B's data).
* Every non-parent role (student, teacher) is 403'd off every ``/api/parent/*``
  route.
* Malformed ``child_id`` is 422, never 500.
* ``target`` is always ``null`` on P-02's per-subject rows (``SubjectOverviewDTO``
  has no wired source for it — see its docstring; distinct from the real
  target-grade column that now drives at-risk rule 2's evidence).
* The grade-bearing filter (D3.9): a quiz-origin record must not move any
  grade/percentage/paper-count claim on P-01/P-02/P-03, but must still
  surface in every weakness list (P-02/P-03/P-04) — mirrors
  ``tests/test_web_quiz_origin_filtering.py``'s seeding pattern.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.at_risk import AtRiskFlag, AtRiskReason, BelowTargetEvidence
from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import ParentChildLink, Subject, User
from lemely.db.models.enums import Role
from lemely.db.parent_repo import ParentLinkService
from lemely.db.student_profile_repo import StudentProfileService
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import DatabaseSettings, Settings, load_settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_class_service,
    get_history_store,
    get_parent_link_service,
    get_settings,
    get_student_profile_service,
)
from lemely.web.routers.parent import _grade_boundary_distance, _parent_at_risk_flag_dto

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures.
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
def parent_link_service(pg_sessionmaker: sessionmaker[Session]) -> ParentLinkService:
    return ParentLinkService(pg_sessionmaker)


@pytest.fixture
def profile_service(pg_sessionmaker: sessionmaker[Session]) -> StudentProfileService:
    return StudentProfileService(pg_sessionmaker)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    base = load_settings()
    data = base.model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    return Settings.model_validate(data)


@pytest.fixture
def history_store(settings: Settings) -> HistoryStore:
    return HistoryStore(settings.paths.output_dir / "history")


@pytest.fixture
def client(
    settings: Settings,
    history_store: HistoryStore,
    class_service: ClassService,
    parent_link_service: ParentLinkService,
    profile_service: StudentProfileService,
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_history_store] = lambda: history_store
    app.dependency_overrides[get_class_service] = lambda: class_service
    app.dependency_overrides[get_parent_link_service] = lambda: parent_link_service
    app.dependency_overrides[get_student_profile_service] = lambda: profile_service
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seed helpers.
# ---------------------------------------------------------------------------


def _seed_user(
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


def _link(sm: sessionmaker[Session], *, parent_id: uuid.UUID, child_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent_id, child_id=child_id))


def _seed_subject(sm: sessionmaker[Session], code: str = "0625", name: str = "Physics") -> str:
    """Seed a ``subjects`` row (P4.3/D4.5): required for a real target-grade
    enrolment — :meth:`StudentProfileService.upsert_enrolment` validates
    ``subject_code`` against this table rather than trusting the caller."""
    with sm.begin() as session:
        session.add(Subject(code=code, name=name))
    return code


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _record(
    *,
    student_id: uuid.UUID,
    subject_code: str = "0625",
    paper_number: int = 1,
    paper_variant: int = 2,
    percentage: float,
    grade: str,
    origin: str = "past_paper",
    recorded_at: str,
    topic: str = "Thermal physics",
    awarded: int | None = None,
    maximum: int = 80,
) -> PaperRecord:
    """One history record — mirrors ``tests/test_web_quiz_origin_filtering.py``'s
    ``_record`` (same quiz shape: ``grade=""``, synthetic paper 1/1)."""
    return PaperRecord(
        student_id=str(student_id),
        metadata=ExamMetadata(
            subject_code=subject_code,
            paper_number=paper_number,
            paper_variant=paper_variant,
            session_month="May/June" if origin == "past_paper" else "Specimen",
            session_year=2020 if origin == "past_paper" else None,
        ),
        awarded_marks=awarded if awarded is not None else int(percentage / 100 * maximum),
        maximum_marks=maximum,
        percentage=percentage,
        grade=grade,
        weak_areas=[
            WeakArea(topic=topic, lost_marks=4, maximum_marks=10, accuracy=0.6, question_ids=["3a"])
        ],
        recorded_at=recorded_at,
        origin=origin,  # type: ignore[arg-type]
    )


def _recent(*, days_ago: int) -> str:
    """A ``recorded_at`` anchored to the wall clock, not a fixed date.

    At-risk rule 3 compares ``recorded_at`` against ``now`` with a 14-day
    window, so a hardcoded date silently ages into "inactive" and appends
    an at-risk clause to ``statusLine`` — breaking tests that never meant to
    exercise that rule. Tests that *do* want the inactivity flag pass their
    own long-past date explicitly.
    """
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _paper(**kwargs: object) -> PaperRecord:
    defaults: dict[str, object] = {
        "percentage": 80.0,
        "grade": "B",
        "recorded_at": _recent(days_ago=3),
    }
    defaults.update(kwargs)
    return _record(**defaults)  # type: ignore[arg-type]


def _quiz(**kwargs: object) -> PaperRecord:
    defaults: dict[str, object] = {
        "percentage": 40.0,
        "grade": "",
        "origin": "quiz",
        "paper_number": 1,
        "paper_variant": 1,
        "maximum": 10,
        "recorded_at": _recent(days_ago=2),
    }
    defaults.update(kwargs)
    return _record(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Authz: linked child reachable, unlinked/unknown rejected, cross-parent leak.
# ---------------------------------------------------------------------------


def test_parent_reaches_every_screen_for_a_linked_child(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    cls = class_service.create_class(teacher, "Physics 10A", subject_code="0625")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    history_store.append(str(student), _paper(student_id=student))

    _auth_as(client, parent, Role.parent)

    home = client.get("/api/parent/children")
    assert home.status_code == 200
    assert home.json()["children"][0]["childId"] == str(student)
    assert home.json()["children"][0]["classes"] == [
        {"name": "Physics 10A", "subjectCode": "0625", "schoolName": None}
    ]

    overview = client.get(f"/api/parent/children/{student}")
    assert overview.status_code == 200
    assert overview.json()["subjects"][0]["predictedGrade"] == "B"

    subject = client.get(f"/api/parent/children/{student}/subjects/0625")
    assert subject.status_code == 200
    assert subject.json()["predictedGrade"] == "B"

    weaknesses = client.get(f"/api/parent/children/{student}/weaknesses")
    assert weaknesses.status_code == 200
    assert weaknesses.json()["weakTopics"][0]["topic"] == "Thermal physics"


def test_parent_gets_403_on_a_real_unlinked_student(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    stranger = _seed_user(pg_sessionmaker, Role.student, display_name="Not Mine")

    _auth_as(client, parent, Role.parent)
    resp = client.get(f"/api/parent/children/{stranger}")

    assert resp.status_code == 403


def test_parent_gets_404_for_a_child_id_matching_no_user(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)

    _auth_as(client, parent, Role.parent)
    resp = client.get(f"/api/parent/children/{uuid.uuid4()}")

    assert resp.status_code == 404


def test_two_parent_two_child_disjoint_links_never_cross(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], history_store: HistoryStore
) -> None:
    """Parent A (linked only to child A) must never see child B's data, and vice versa."""
    parent_a = _seed_user(pg_sessionmaker, Role.parent, display_name="Parent A")
    parent_b = _seed_user(pg_sessionmaker, Role.parent, display_name="Parent B")
    child_a = _seed_user(pg_sessionmaker, Role.student, display_name="Child A")
    child_b = _seed_user(pg_sessionmaker, Role.student, display_name="Child B")
    _link(pg_sessionmaker, parent_id=parent_a, child_id=child_a)
    _link(pg_sessionmaker, parent_id=parent_b, child_id=child_b)
    history_store.append(str(child_a), _paper(student_id=child_a, grade="A", percentage=90.0))
    history_store.append(str(child_b), _paper(student_id=child_b, grade="E", percentage=42.0))

    _auth_as(client, parent_a, Role.parent)
    own_home = client.get("/api/parent/children").json()
    assert [c["childId"] for c in own_home["children"]] == [str(child_a)]
    assert client.get(f"/api/parent/children/{child_b}").status_code == 403
    assert client.get(f"/api/parent/children/{child_b}/subjects/0625").status_code == 403
    assert client.get(f"/api/parent/children/{child_b}/weaknesses").status_code == 403

    _auth_as(client, parent_b, Role.parent)
    other_home = client.get("/api/parent/children").json()
    assert [c["childId"] for c in other_home["children"]] == [str(child_b)]
    assert client.get(f"/api/parent/children/{child_a}").status_code == 403


@pytest.mark.parametrize("role", [Role.student, Role.teacher, Role.school_admin])
def test_non_parent_role_is_403_on_every_parent_route(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], role: Role
) -> None:
    caller = _seed_user(pg_sessionmaker, role)
    child_id = uuid.uuid4()
    _auth_as(client, caller, role)

    assert client.get("/api/parent/children").status_code == 403
    assert client.get(f"/api/parent/children/{child_id}").status_code == 403
    assert client.get(f"/api/parent/children/{child_id}/subjects/0625").status_code == 403
    assert client.get(f"/api/parent/children/{child_id}/weaknesses").status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/api/parent/children/not-a-uuid",
        "/api/parent/children/not-a-uuid/subjects/0625",
        "/api/parent/children/not-a-uuid/weaknesses",
    ],
)
def test_malformed_child_id_is_422_not_500(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], path: str
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    _auth_as(client, parent, Role.parent)

    assert client.get(path).status_code == 422


# ---------------------------------------------------------------------------
# Honesty: target grade, subject-not-found 404.
# ---------------------------------------------------------------------------


def test_target_grade_is_always_null(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], history_store: HistoryStore
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    history_store.append(str(student), _paper(student_id=student))

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{student}").json()

    assert body["subjects"][0]["target"] is None


def test_subject_detail_404s_when_the_child_has_no_papers_for_the_code(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], history_store: HistoryStore
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    history_store.append(str(student), _paper(student_id=student, subject_code="0625"))

    _auth_as(client, parent, Role.parent)
    resp = client.get(f"/api/parent/children/{student}/subjects/0580")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Grade-bearing filter (D3.9): quiz-origin records.
# ---------------------------------------------------------------------------


def test_quiz_activity_does_not_move_the_children_list_status_or_trend(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], history_store: HistoryStore
) -> None:
    """P-01: a quiz must not appear in ``statusLine``'s subject clauses.

    Inverted (P3.6a self-check): pointing ``_status_line``/``_overall_trend``
    at unfiltered ``history.records`` made this test fail — see the chunk
    report for the exact assertion that broke.
    """
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    history_store.append(str(student), _paper(student_id=student, percentage=80.0, grade="B"))
    history_store.append(str(student), _quiz(student_id=student, percentage=40.0))

    _auth_as(client, parent, Role.parent)
    body = client.get("/api/parent/children").json()
    row = body["children"][0]

    assert row["statusLine"] == "Physics: predicted B."
    assert row["trend"] is None


def test_quiz_activity_does_not_move_child_overview_grades_but_weaknesses_see_it(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], history_store: HistoryStore
) -> None:
    """P-02: quiz excluded from subjects/recentPapers, included in weakTopics.

    Inverted (P3.6a self-check): removing the ``grade_bearing`` filter from
    the subjects/recentPapers computation made this test fail — the quiz's
    ``grade=""`` became the subject's ``predictedGrade`` and ``paperCount``
    became 2. See the chunk report for the exact assertion that broke.
    """
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    history_store.append(
        str(student),
        _paper(student_id=student, percentage=80.0, grade="B", topic="Thermal physics"),
    )
    history_store.append(str(student), _quiz(student_id=student, percentage=40.0, topic="Momentum"))

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{student}").json()

    assert len(body["subjects"]) == 1
    assert body["subjects"][0]["subjectCode"] == "0625"
    assert body["subjects"][0]["predictedGrade"] == "B"
    assert body["subjects"][0]["paperCount"] == 1
    assert [p["grade"] for p in body["recentPapers"]] == ["B"]
    assert {w["topic"] for w in body["weakTopics"]} == {"Thermal physics", "Momentum"}


def test_quiz_activity_does_not_move_subject_detail_papers_but_weaknesses_see_it(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], history_store: HistoryStore
) -> None:
    """P-03: quiz excluded from ``papers``/``predictedGrade``, included in ``weakTopics``.

    Inverted (P3.6a self-check): removing the ``grade_bearing`` filter over
    the subject-scoped records made this test fail — the quiz's synthetic
    Paper 1/1 identity opened a second papers-table row and ``predictedGrade``
    read the quiz's empty grade. See the chunk report for the exact
    assertion that broke.
    """
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    history_store.append(
        str(student),
        _paper(student_id=student, percentage=80.0, grade="B", topic="Thermal physics"),
    )
    history_store.append(str(student), _quiz(student_id=student, percentage=40.0, topic="Momentum"))

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{student}/subjects/0625").json()

    assert [p["grade"] for p in body["papers"]] == ["B"]
    assert body["predictedGrade"] == "B"
    assert {w["topic"] for w in body["weakTopics"]} == {"Thermal physics", "Momentum"}


def test_quiz_only_subject_still_contributes_to_p04_weaknesses(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], history_store: HistoryStore
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    history_store.append(
        str(student),
        _quiz(student_id=student, subject_code="0580", percentage=40.0, topic="Algebra"),
    )

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{student}/weaknesses").json()

    assert {w["topic"] for w in body["weakTopics"]} == {"Algebra"}


# ---------------------------------------------------------------------------
# At-risk flags on P-02 (UI spec §4.8: "any at-risk flags with their reason").
#
# The clock is not injectable through the HTTP surface (the routes call
# ``datetime.now(UTC)``), so these fixtures date their records to 2020 — far
# enough in the past that the D3.3 inactivity rule fires on any future run
# date rather than on a window that quietly closes.
# ---------------------------------------------------------------------------


def test_child_overview_surfaces_at_risk_flags_with_reason_and_evidence(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], history_store: HistoryStore
) -> None:
    """Two of the three evidence types this fixture triggers reach the parent's wire DTO.

    Three declining papers (85 → 75 → 60, well past the 5pp floor) fire
    ``declining_trend``; their 2020 timestamps fire ``inactive``. No target
    grade is seeded for this student, so ``below_target`` stays *not
    evaluable* here by construction (D3.3/D4.5) — the case where it *does*
    fire end-to-end is covered separately by
    ``test_child_overview_surfaces_a_real_below_target_flag_when_a_target_is_set``
    below; this fixture's converter coverage for the evidence shape itself is
    the direct unit test further down.
    """
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    for pct, grade, day in ((85.0, "A", "01"), (75.0, "B", "02"), (60.0, "C", "03")):
        history_store.append(
            str(student),
            _paper(
                student_id=student,
                percentage=pct,
                grade=grade,
                recorded_at=f"2020-03-{day}T10:00:00+00:00",
            ),
        )

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{student}").json()

    flags = {flag["reason"]: flag for flag in body["atRiskFlags"]}
    assert set(flags) == {"declining_trend", "inactive"}
    assert flags["declining_trend"]["evidence"]["percentages"] == [85.0, 75.0, 60.0]
    assert flags["inactive"]["evidence"]["daysInactive"] > 14
    assert flags["inactive"]["evidence"]["lastActiveAt"] == "2020-03-03T10:00:00+00:00"
    assert all(flag["summary"] for flag in body["atRiskFlags"])
    # P-01's status line notes the signal without inventing a verdict.
    home = client.get("/api/parent/children").json()
    assert home["children"][0]["statusLine"].endswith("At least one at-risk signal is active.")


def test_child_overview_surfaces_a_real_below_target_flag_when_a_target_is_set(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    history_store: HistoryStore,
    profile_service: StudentProfileService,
) -> None:
    """Rule 2 fires end-to-end through the real HTTP surface (P4.3/D4.5).

    A real target grade — set via ``StudentProfileService.upsert_enrolment``,
    the same seam ``PUT /me/profile/enrolments`` writes through — is now
    resolvable by ``assess_at_risk`` for this student's subject, so
    ``below_target`` must appear in P-02's ``atRiskFlags`` alongside its
    evidence, not stay perpetually not-evaluable as it did before P4.3.
    """
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    _seed_subject(pg_sessionmaker, code="0625", name="Physics")
    profile_service.upsert_enrolment(student, "0625", target_grade="A")
    history_store.append(
        str(student),
        _paper(student_id=student, percentage=40.0, grade="D"),
    )

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{student}").json()

    flags = {flag["reason"]: flag for flag in body["atRiskFlags"]}
    assert "below_target" in flags
    assert flags["below_target"]["evidence"] == {
        "targetGrade": "A",
        "predictedGrade": "D",
        "positionsBelow": 3,
    }


def test_child_overview_includes_qualification_level_per_subject(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    history_store: HistoryStore,
    profile_service: StudentProfileService,
) -> None:
    """A subject's qualificationLevel comes from the child's own enrolment for it."""
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    _seed_subject(pg_sessionmaker, code="0625", name="Physics")
    profile_service.upsert_enrolment(student, "0625", qualification_level="igcse")
    history_store.append(
        str(student),
        _paper(student_id=student, percentage=80.0, grade="B"),
    )

    _auth_as(client, parent, Role.parent)
    overview = client.get(f"/api/parent/children/{student}").json()
    assert overview["subjects"][0]["qualificationLevel"] == "igcse"

    detail = client.get(f"/api/parent/children/{student}/subjects/0625").json()
    assert detail["qualificationLevel"] == "igcse"


def test_below_target_evidence_translates_through_the_converter() -> None:
    """Pin the ``below_target`` branch of the parent evidence converter directly.

    The end-to-end firing path is covered by
    ``test_child_overview_surfaces_a_real_below_target_flag_when_a_target_is_set``
    above; this unit-level test keeps the converter itself pinned against its
    own ``AtRiskFlag`` input without the Postgres/HTTP round trip.
    """
    dto = _parent_at_risk_flag_dto(
        AtRiskFlag(
            reason=AtRiskReason.BELOW_TARGET,
            summary="Predicted C against a target of A",
            evidence=BelowTargetEvidence(target_grade="A", predicted_grade="C", positions_below=2),
        )
    )

    assert dto.reason == "below_target"
    assert dto.evidence == {"targetGrade": "A", "predictedGrade": "C", "positionsBelow": 2}


def test_unknown_evidence_type_raises_rather_than_shipping_an_empty_payload() -> None:
    """An unhandled union member must fail loudly, never serialise as ``{}``."""

    class _NewEvidence:
        pass

    flag = AtRiskFlag.model_construct(
        reason=AtRiskReason.INACTIVE, summary="x", evidence=_NewEvidence()
    )
    with pytest.raises(TypeError, match="Unhandled AtRiskFlag evidence type"):
        _parent_at_risk_flag_dto(flag)


# ---------------------------------------------------------------------------
# Empty child (P-01's "no papers yet" state) and P-03 boundary distance.
# ---------------------------------------------------------------------------


def test_linked_child_with_no_history_reads_as_empty_not_as_a_fabricated_status(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], history_store: HistoryStore
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Newcomer")
    _link(pg_sessionmaker, parent_id=parent, child_id=student)

    _auth_as(client, parent, Role.parent)
    row = client.get("/api/parent/children").json()["children"][0]

    assert row["statusLine"] == "No papers recorded yet."
    assert row["trend"] is None
    assert row["lastActivityAt"] is None

    overview = client.get(f"/api/parent/children/{student}").json()
    assert overview["subjects"] == []
    assert overview["recentPapers"] == []
    assert overview["atRiskFlags"] == []
    assert overview["activity"] == {
        "totalPapers": 0,
        "lastActiveAt": None,
        "daysSinceLastActivity": None,
    }
    assert client.get(f"/api/parent/children/{student}/weaknesses").json()["weakTopics"] == []


def test_subject_detail_reports_the_distance_to_the_next_grade_up(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], history_store: HistoryStore
) -> None:
    """P-03's "3 marks from a B", computed from the resolved boundary table.

    This must be an Extended paper, not a Core one: 0625 paper 1 (Multiple
    Choice) is Core on every session in the corpus except 2014-2015, and Core
    publishes no B at all, so a Core paper's ``subject_default`` correctly
    omits "B" — there being no B for a Core candidate to move towards is not a
    missing feature, it's the point of P4's "only offer a grade the paper can
    award" rule. Paper 2 (Multiple Choice, Extended) is examined every year on
    record and its subject-default B boundary is 57.82%, so 47 of 80 marks is
    the B threshold; a 44/80 paper is exactly 3 marks short. The arithmetic is
    asserted rather than merely the shape, so a change to the rounding
    (``ceil``, not ``round`` — a parent must never be told they are closer to
    the grade than they are) fails here.
    """
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    history_store.append(
        str(student),
        _paper(
            student_id=student,
            paper_number=2,
            percentage=55.0,
            grade="C",
            awarded=44,
            maximum=80,
        ),
    )

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{student}/subjects/0625").json()

    assert body["boundaryDistance"] == {
        "nextGrade": "B",
        "marksNeeded": 3,
        "summary": "3 marks from a B",
    }


def test_a_core_paper_has_no_reachable_grade_above_its_own_ceiling(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], history_store: HistoryStore
) -> None:
    """0625 paper 1 (Multiple Choice, Core) publishes C-G on every recent
    session; its subject-default fallback carries no B. A Core candidate at C
    genuinely has no higher grade to be "N marks from" — reporting one would
    be exactly the fabrication P4's threshold-table rewrite exists to remove
    (Cambridge itself states A does not exist at Core component level), so
    the honest answer is the same ``null`` the "nothing to report" cases use,
    not a fabricated distance to a grade this paper cannot award.
    """
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    history_store.append(
        str(student),
        _paper(
            student_id=student, paper_number=1, percentage=50.0, grade="C", awarded=40, maximum=80
        ),
    )

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{student}/subjects/0625").json()

    assert body["boundaryDistance"] is None


@pytest.mark.parametrize(
    ("grade", "maximum", "why"),
    [
        ("A*", 80, "already on the top grade — there is no grade above it"),
        ("C", 0, "no maximum marks to convert a percentage threshold into marks"),
    ],
)
def test_boundary_distance_is_omitted_rather_than_guessed(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    history_store: HistoryStore,
    grade: str,
    maximum: int,
    why: str,
) -> None:
    """Each case has nothing honest to report, so it reports ``null``."""
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    history_store.append(
        str(student),
        _paper(student_id=student, percentage=50.0, grade=grade, awarded=0, maximum=maximum),
    )

    _auth_as(client, parent, Role.parent)
    body = client.get(f"/api/parent/children/{student}/subjects/0625").json()

    assert body["boundaryDistance"] is None, why


def test_boundary_distance_guards_a_grade_that_is_not_on_the_ladder() -> None:
    """Driven directly because no HTTP path can reach this branch today.

    :func:`~lemely.core.history.is_grade_bearing` is *defined* as
    "past-paper origin **and** ``grade in GRADE_ORDER``", and P-03 only ever
    passes it a ``grade_bearing`` record — so an off-ladder grade cannot
    arrive through the route. The guard stays as a precondition on the helper
    (without it ``GRADE_ORDER.index`` raises), and this test pins that it
    returns ``None`` rather than blowing up, so a future caller that skips the
    filter degrades to "no claim" instead of a 500.
    """
    assert _grade_boundary_distance(_paper(student_id=uuid.uuid4(), grade="Z")) is None
