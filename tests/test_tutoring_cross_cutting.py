"""Whole-feature checks over all 70 tutoring routes (PLAN T25, P12, P25; SPEC §b.2, §b.5, §c.1).

* **The route set.** The routes are read from the application itself,
  ``tests.tutoring_app.flatten_routes(app_with_routers(<T25's two routers>).router)`` (FastAPI
  keeps an included router as a wrapper, so ``app.routes`` alone finds none of them), and
  compared both ways with the 70 ``EXPECTED`` rows parsed from SPEC §c.1: filtered to the parsed
  pairs, and enumerated independently by the tutoring path prefixes. The guard counts are
  checked against SPEC §b.2's "Route count" line.
* **Cache headers (SPEC §b.2 legend as amended by PLAN P12, §b.5, SC-18, SC-26).** Only P1-P3
  are cacheable (``PublicTutoringRoute``: ``public, max-age=60``). Every other tutoring route
  is ``private, no-store`` on every status through ``TutoringRoute``, so one unauthenticated
  request per route proves the header on the guard's own 401. S16 and S17 live on two older
  routers (PLAN §1.4 #1) and set the header in their handlers: SPEC §i.6 records that they send
  it on 200/204/404 while their framework 401/403/422 carry no data and no header, so they are
  proved on success here and their 401 is shown to carry no data.
* **No tutor profile (ADR-T01 action 3, P25).** Each of the 20 TEACHER routes other than
  ``POST /api/tutor/profile`` answers a verified teacher without a profile 404
  ``no_tutor_profile``.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from lemely.db.class_repo import ClassService
from lemely.db.models.enums import Role
from lemely.db.tutor_directory_repo import TutorDirectoryRepository
from lemely.db.tutor_profile_repo import TutorProfileRepository
from lemely.runtime.config import Settings
from lemely.web.deps import get_class_service, get_settings, get_user_mirror
from lemely.web.deps_tutoring import get_tutor_directory_repo, get_tutor_profile_repo
from lemely.web.routers import admin_tutoring_reports, tutoring_reports
from lemely.web.tutoring_http import NO_STORE, PUBLIC_CACHE, PublicTutoringRoute, TutoringRoute
from tests.test_tutoring_sweeps import add_class, enrol
from tests.tutoring_app import app_with_routers, flatten_routes
from tests.tutoring_db import (
    DbMirror,
    act_as,
    add_subject,
    add_tutor,
    add_user,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from sqlalchemy.orm import Session, sessionmaker

SPEC = Path(__file__).resolve().parents[1] / "docs" / "tutoring" / "SPEC.md"
_HIDDEN_METHODS = frozenset({"HEAD", "OPTIONS"})
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})

S16 = ("GET", "/api/student/tutor-access/classes")
S17 = ("DELETE", "/api/student/classes/{class_id}")
T2 = ("POST", "/api/tutor/profile")

#: The path prefixes of the tutoring surface (SPEC §b.1, PLAN §1.4 #1), plus S17 by its pair:
#: an independent way to find the tutoring routes, so a route outside SPEC §c.1 is caught.
TUTORING_PREFIXES = (
    "/api/public/tutor",
    "/api/tutors",
    "/api/bookings",
    "/api/student/bookings",
    "/api/student/reviews/",
    "/api/student/tutor-",
    "/api/student/tutoring-",
    "/api/tutor/",
    "/api/parent/children/{child_id}/bookings",
    "/api/parent/children/{child_id}/tutor-",
    "/api/tutoring/",
    "/api/admin/tutor",
)


def _spec_section(heading: str, following: str) -> str:
    text = SPEC.read_text(encoding="utf-8")
    start = text.index(heading)
    return text[start : text.index(following, start)]


def _spec_c1_rows() -> dict[tuple[str, str], str]:
    """``{(method, path): guard}`` from the ``EXPECTED`` rows of SPEC §c.1."""
    section = _spec_section("### c.1", "### c.2")
    rows = re.findall(r'\("(GET|POST|PUT|PATCH|DELETE)", "([^"]+)"\): ([A-Z_]+),', section)
    return {(method, path): guard for method, path, guard in rows}


def _spec_route_count() -> tuple[int, Counter[str]]:
    """SPEC §b.2's "Route count: 70 (PUBLIC 3, ...)" line, as a total and per guard."""
    section = _spec_section("### b.2", "### b.3")
    found = re.search(r"\*\*Route count: (\d+)\*\* \(([^)]*)\)", section)
    assert found is not None, "SPEC §b.2 no longer states the route count"
    per_guard = Counter(
        {name: int(count) for name, count in re.findall(r"([A-Z_]+) (\d+)", found.group(2))}
    )
    return int(found.group(1)), per_guard


SPEC_ROUTES = _spec_c1_rows()


def _app() -> FastAPI:
    return app_with_routers(tutoring_reports.router, admin_tutoring_reports.router)


def _pairs(app: FastAPI) -> dict[tuple[str, str], APIRoute]:
    return {
        (method, route.path): route
        for route in flatten_routes(app.router)
        for method in route.methods
        if method not in _HIDDEN_METHODS
    }


def _concrete(path: str) -> str:
    out = path
    while "{" in out:
        name = out[out.index("{") + 1 : out.index("}")]
        out = out.replace(f"{{{name}}}", str(uuid.uuid4()), 1)
    return out


def _guarded(guard: str) -> list[tuple[str, str]]:
    return sorted(pair for pair, wanted in SPEC_ROUTES.items() if wanted == guard)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = Settings().model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    return Settings.model_validate(data)


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def db_client(sm: sessionmaker[Session], settings: Settings) -> Iterator[TestClient]:
    app = _app()
    app.dependency_overrides.update(
        {
            get_settings: lambda: settings,
            get_tutor_profile_repo: lambda: TutorProfileRepository(sm),
            get_tutor_directory_repo: lambda: TutorDirectoryRepository(sm),
            get_class_service: lambda: ClassService(sm),
            get_user_mirror: lambda: DbMirror(sm),
        }
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# The route set
# ---------------------------------------------------------------------------


def test_tutoring_routes_enumerated_equal_spec_c1() -> None:
    total, per_guard = _spec_route_count()
    assert total == len(SPEC_ROUTES) == 70
    assert Counter(SPEC_ROUTES.values()) == per_guard
    assert sum(per_guard.values()) == 70

    served = _pairs(_app())
    by_spec = set(served) & set(SPEC_ROUTES)
    assert len(by_spec) == 70
    assert by_spec == set(SPEC_ROUTES)

    by_prefix = {pair for pair in served if pair == S17 or pair[1].startswith(TUTORING_PREFIXES)}
    assert len(by_prefix) == 70, sorted(by_prefix ^ set(SPEC_ROUTES))
    assert by_prefix == set(SPEC_ROUTES)


# ---------------------------------------------------------------------------
# Cache headers
# ---------------------------------------------------------------------------


def test_public_routes_only_p1_p3_cacheable(
    sm: sessionmaker[Session], db_client: TestClient
) -> None:
    served = _pairs(_app())
    public = {pair for pair in SPEC_ROUTES if isinstance(served[pair], PublicTutoringRoute)}
    private = {pair for pair in SPEC_ROUTES if isinstance(served[pair], TutoringRoute)}
    plain = set(SPEC_ROUTES) - public - private
    assert public == set(_guarded("PUBLIC"))
    assert len(public) == 3
    assert plain == {S16, S17}
    assert len(private) == 65

    tutor = add_tutor(sm, subjects=(add_subject(sm),))
    for path in (
        "/api/public/tutors",
        f"/api/public/tutors/{tutor.profile_id}",
        "/api/public/tutoring-areas",
    ):
        response = db_client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert response.headers["Cache-Control"] == PUBLIC_CACHE == "public, max-age=60"
        assert response.headers["X-Robots-Tag"] == "noindex"


def test_every_non_public_tutoring_route_sends_no_store_unauthenticated(
    settings: Settings,
) -> None:
    """One unauthenticated request per route, UUIDs for the path, no body: the 401 the token
    check raises inside the route still carries ``private, no-store``."""
    app = _app()
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    non_public = sorted(pair for pair, guard in SPEC_ROUTES.items() if guard != "PUBLIC")
    assert len(non_public) == 67
    through_route_class = [pair for pair in non_public if pair not in {S16, S17}]
    assert len(through_route_class) == 65

    wrong = {}
    for method, path in through_route_class:
        response = client.request(method, _concrete(path))
        if response.status_code != 401 or response.headers.get("Cache-Control") != NO_STORE:
            wrong[(method, path)] = (response.status_code, response.headers.get("Cache-Control"))
    assert wrong == {}

    # SPEC §i.6: S16's and S17's framework 401 carries no data (and no header).
    for method, path in (S16, S17):
        response = client.request(method, _concrete(path))
        assert response.status_code == 401
        assert set(response.json()) == {"detail"}


def test_s16_s17_send_no_store_on_success(sm: sessionmaker[Session], db_client: TestClient) -> None:
    student = add_user(sm, Role.student)
    teacher = add_user(sm, Role.teacher)
    class_id = add_class(sm, teacher)
    enrol(sm, class_id, student)
    act_as(db_client, student, Role.student)

    listed = db_client.get(S16[1])
    assert listed.status_code == 200, listed.text
    assert listed.headers["Cache-Control"] == NO_STORE
    assert [item["classId"] for item in listed.json()["items"]] == [str(class_id)]

    left = db_client.delete(f"/api/student/classes/{class_id}")
    assert left.status_code == 204, left.text
    assert left.headers["Cache-Control"] == NO_STORE

    again = db_client.delete(f"/api/student/classes/{class_id}")
    assert again.status_code == 404
    assert again.headers["Cache-Control"] == NO_STORE


# ---------------------------------------------------------------------------
# No tutor profile (ADR-T01 action 3)
# ---------------------------------------------------------------------------


def test_every_tutor_route_404_no_tutor_profile(
    sm: sessionmaker[Session], db_client: TestClient
) -> None:
    tutor_routes = [pair for pair in _guarded("TEACHER") if pair != T2]
    assert len(tutor_routes) == 20
    assert all(path.startswith("/api/tutor/") for _, path in tutor_routes)
    teacher = add_user(sm, Role.teacher, verified=True)
    act_as(db_client, teacher, Role.teacher)

    wrong = {}
    for method, path in tutor_routes:
        kwargs = {"json": {}} if method in _BODY_METHODS else {}
        response = db_client.request(method, _concrete(path), **kwargs)
        detail = response.json().get("detail") if response.status_code == 404 else None
        code = detail.get("code") if isinstance(detail, dict) else None
        if code != "no_tutor_profile" or response.headers.get("Cache-Control") != NO_STORE:
            wrong[(method, path)] = (response.status_code, response.text[:120])
    assert wrong == {}
