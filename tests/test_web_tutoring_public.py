"""Public tutoring routes P1-P3 (SPEC §b.2 "Public", §a.5 row 5b, row 17, §b.5, PP-6).

Every app here is built with ``tests.tutoring_app.app_with_routers`` (the lead
mounts the routers in ``lemely/web/app.py``; a lane never edits it), through the
shared helpers in ``tests/tutoring_db.py``.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from lemely.io.tutoring_areas import (
    AREAS_FILE,
    AreaCatalogueError,
    load_tutoring_areas,
    parse_tutoring_areas,
)
from tests.test_schemas_tutoring import ROW_5B_PUBLIC_FIELDS
from tests.tutoring_db import (
    add_subject,
    add_tutor,
    emptied_after,
    json_keys,
    tutoring_client,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = tutoring_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Headers (SPEC §b.5, SC-18 API half)
# ---------------------------------------------------------------------------


def test_p1_p3_public_cache_and_noindex_api_headers(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    listed = add_tutor(sm, subjects=(add_subject(sm),))
    for path, status in [
        ("/api/public/tutors", 200),
        (f"/api/public/tutors/{listed.profile_id}", 200),
        (f"/api/public/tutors/{uuid.uuid4()}", 404),
        ("/api/public/tutoring-areas", 200),
        ("/api/public/tutors?minRating=4.2", 422),
    ]:
        response = client.get(path)
        assert response.status_code == status, path
        assert response.headers["cache-control"] == "public, max-age=60", path
        assert response.headers["x-robots-tag"] == "noindex", path


# ---------------------------------------------------------------------------
# P2 and `indexable` (row 17, O31, PP-6)
# ---------------------------------------------------------------------------


def test_p2_carries_indexable_and_p1_does_not(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    subject = add_subject(sm)
    opted_in = add_tutor(sm, subjects=(subject,))
    opted_out = add_tutor(sm, subjects=(subject,), indexable=False)

    assert client.get(f"/api/public/tutors/{opted_in.profile_id}").json()["indexable"] is True
    assert client.get(f"/api/public/tutors/{opted_out.profile_id}").json()["indexable"] is False

    page = client.get("/api/public/tutors").json()
    assert {item["tutorId"] for item in page["items"]} == {
        str(opted_in.profile_id),
        str(opted_out.profile_id),
    }
    assert "indexable" not in json_keys(page)


@pytest.mark.parametrize(
    "hidden", ["draft", "pending_review", "rejected", "suspended", "closed", "paused", "unknown"]
)
def test_p2_404_identical_for_unlisted_paused_suspended_closed_unknown(
    client: TestClient, sm: sessionmaker[Session], hidden: str
) -> None:
    baseline = client.get(f"/api/public/tutors/{uuid.uuid4()}")
    if hidden == "unknown":
        target = uuid.uuid4()
    elif hidden == "paused":
        target = add_tutor(sm, paused=True).profile_id
    else:
        target = add_tutor(sm, state=hidden).profile_id

    response = client.get(f"/api/public/tutors/{target}")

    assert response.status_code == baseline.status_code == 404
    assert response.content == baseline.content
    assert response.json() == {"detail": {"code": "not_found", "message": "Tutor not found."}}
    assert set(response.headers) == set(baseline.headers)


def test_p2_returns_the_public_card(client: TestClient, sm: sessionmaker[Session]) -> None:
    subject = add_subject(sm, name="Physics")
    seeded = add_tutor(sm, subjects=(subject,), modes=("in_person",), area="giza", rating=(14, 3))
    body = client.get(f"/api/public/tutors/{seeded.profile_id}").json()
    assert body == {
        "tutorId": str(seeded.profile_id),
        "publicName": "Sara M.",
        "headline": "IGCSE Mathematics, patient and exam focused",
        "subjects": [{"code": subject, "name": "Physics"}],
        "modes": ["in_person"],
        "area": {"code": "giza", "name": "Giza"},
        "rating": {"state": "rated", "average": 4.7, "count": 3},
        "indexable": True,
    }
    assert body["tutorId"] != str(seeded.user_id)


def test_p2_malformed_id_is_422(client: TestClient) -> None:
    assert client.get("/api/public/tutors/not-a-uuid").status_code == 422


# ---------------------------------------------------------------------------
# P1 directory
# ---------------------------------------------------------------------------


def test_p1_pages_with_cursor_and_facets_on_the_first_page(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    subject = add_subject(sm, name="Chemistry")
    ids = [
        add_tutor(sm, subjects=(subject,), rank=Decimal(f"4.{n}00000")).profile_id for n in range(5)
    ]
    expected = [str(pid) for pid in reversed(ids)]  # higher rank first

    first = client.get("/api/public/tutors?limit=2").json()
    assert [item["tutorId"] for item in first["items"]] == expected[:2]
    assert first["facets"] == {
        "subjects": [{"code": subject, "name": "Chemistry"}],
        "areas": [{"code": "cairo", "name": "Cairo"}],
    }
    second = client.get(f"/api/public/tutors?limit=2&cursor={first['nextCursor']}").json()
    assert [item["tutorId"] for item in second["items"]] == expected[2:4]
    assert second["facets"] is None
    third = client.get(f"/api/public/tutors?limit=2&cursor={second['nextCursor']}").json()
    assert [item["tutorId"] for item in third["items"]] == expected[4:]
    assert third["nextCursor"] is None


def test_p1_filters(client: TestClient, sm: sessionmaker[Session]) -> None:
    maths = add_subject(sm)
    rated = add_tutor(sm, subjects=(maths,), rating=(89, 20), modes=("in_person",), area="giza")
    new = add_tutor(sm, subjects=(maths,), rating=(10, 2))

    def ids(query: str) -> set[str]:
        response = client.get(f"/api/public/tutors?{query}")
        assert response.status_code == 200, response.text
        return {item["tutorId"] for item in response.json()["items"]}

    assert ids("") == {str(rated.profile_id), str(new.profile_id)}
    assert ids("minRating=4.5") == {str(rated.profile_id)}
    assert ids(f"subject={maths}&mode=in_person&mode=other&area=giza") == {str(rated.profile_id)}
    assert ids("mode=virtual") == {str(new.profile_id)}


@pytest.mark.parametrize(
    "query",
    [
        "minRating=4.2",
        "minRating=0.5",
        "minRating=5.5",
        "minRating=abc",
        "mode=phone",
        "area=atlantis",
        "limit=0",
        "limit=51",
        "cursor=%21%21",
    ],
)
def test_p1_refuses_invalid_filters_with_422(client: TestClient, query: str) -> None:
    assert client.get(f"/api/public/tutors?{query}").status_code == 422


# ---------------------------------------------------------------------------
# P3 areas (F13)
# ---------------------------------------------------------------------------


def test_p3_lists_every_area(client: TestClient) -> None:
    on_disk = json.loads(AREAS_FILE.read_text(encoding="utf-8"))
    body = client.get("/api/public/tutoring-areas").json()
    assert body == {"items": [{"code": e["code"], "name": e["name"]} for e in on_disk]}
    # Non-vacuity: Egypt's governorates outside the large cities, plus the cities.
    assert len(body["items"]) >= 27
    assert {"cairo", "giza", "alexandria"} <= {item["code"] for item in body["items"]}


def test_area_file_entries_are_well_formed() -> None:
    on_disk = json.loads(AREAS_FILE.read_text(encoding="utf-8"))
    catalogue = load_tutoring_areas()
    assert [area.code for area in catalogue.areas] == [e["code"] for e in on_disk]
    assert all(area.country_code == "EG" for area in catalogue.areas)
    assert len({area.code for area in catalogue.areas}) == len(catalogue.areas)
    assert catalogue.get("cairo") is not None
    assert catalogue.get("atlantis") is None


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {"code": "cairo"},
        [{"code": "cairo", "name": "Cairo"}],
        [{"code": "cairo", "name": "Cairo", "country_code": "EG", "extra": 1}],
        [{"code": "Cairo", "name": "Cairo", "country_code": "EG"}],
        [{"code": "cairo", "name": " ", "country_code": "EG"}],
        [{"code": "cairo", "name": "Cairo", "country_code": "eg"}],
        [
            {"code": "cairo", "name": "Cairo", "country_code": "EG"},
            {"code": "cairo", "name": "Cairo again", "country_code": "EG"},
        ],
    ],
)
def test_area_catalogue_rejects_malformed_files(raw: object) -> None:
    with pytest.raises(AreaCatalogueError):
        parse_tutoring_areas(raw)


# ---------------------------------------------------------------------------
# Row 5b allowlist on real responses (P14)
# ---------------------------------------------------------------------------


def test_p1_p2_p3_json_keys_within_row_5b_allowlist(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    subject = add_subject(sm)
    seeded = add_tutor(
        sm,
        subjects=(subject,),
        rating=(14, 3),
        bio="Logged-in only",
        qualification_note="Logged-in only",
        modes=("virtual", "other"),
        other_mode_note="Logged-in only",
        documents_seen=True,
    )
    responses = {
        "P1": client.get("/api/public/tutors").json(),
        "P2": client.get(f"/api/public/tutors/{seeded.profile_id}").json(),
        "P3": client.get("/api/public/tutoring-areas").json(),
    }
    allowlist = set().union(*ROW_5B_PUBLIC_FIELDS.values())
    seen: set[str] = set()
    for name, body in responses.items():
        keys = json_keys(body)
        assert keys <= allowlist, (name, sorted(keys - allowlist))
        seen |= keys
    # Non-vacuity: the three responses together use every allowed key.
    assert seen == allowlist
    assert "Logged-in only" not in json.dumps(responses)
    assert str(seeded.user_id) not in json.dumps(responses)
