"""Tests for the Student portal endpoints (lemely.web.routers.student).

Every assertion checks *data-backed* behaviour: responses are computed from a
seeded :class:`~lemely.io.history_store.HistoryStore` and the pure-core analytics
(no live Gemini). Structurally-empty fields (leaderboard peers, per-question
theory/integrity for history-sourced papers, subject ranks) are asserted to be
their typed-neutral defaults rather than mock demo numbers.

The Gemini client is only exercised on the ``narrate`` path of ``POST /plan``,
where it is mocked — no network calls anywhere in this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import SecretStr

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.core.study import StudyPlan, StudySession
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import Settings, load_settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_history_store,
    get_settings,
)

STUDENT_ID = "maya"


def _settings_with_key() -> Settings:
    """A Settings copy carrying a dummy API key (enables the narrate path)."""
    data = load_settings().model_dump()
    data["gemini_api_key"] = SecretStr("test-key")
    return Settings.model_validate(data)


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


# ── Study plan ────────────────────────────────────────────────────────────────


def test_plan_get_is_deterministic_without_narrative(client: TestClient) -> None:
    """GET /plan schedules sessions from weaknesses with no AI narrative."""
    body = client.get("/api/student/plan").json()

    assert body["studentId"] == STUDENT_ID
    assert body["weeklyHours"] == 11.0
    assert body["narrative"] is None
    topics = {s["topic"] for s in body["sessions"]}
    # Weak topics across all papers become sessions.
    assert "Thermal physics" in topics
    assert "Moles" in topics


def test_plan_post_narrate_uses_mocked_gemini(
    seeded_store: HistoryStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /plan with narrate=true runs the narrator (mocked) and returns text."""
    narrated = StudyPlan(
        student_id=STUDENT_ID,
        weekly_hours=8.0,
        sessions=[
            StudySession(
                week=1,
                topic="Thermal physics",
                subject_code="0625",
                hours=8.0,
                focus="Practice and review: Thermal physics",
            )
        ],
        narrative="Focus on thermal physics this week.",
    )
    fake_client = MagicMock()
    fake_client.generate_structured.return_value = narrated

    # The router calls get_gemini_client() directly (not via Depends), so patch
    # the module-level reference; monkeypatch restores it after the test.
    import lemely.web.routers.student as student_router

    monkeypatch.setattr(student_router, "get_gemini_client", lambda: fake_client)

    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: seeded_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    # Narration only runs when an API key is configured, so present one.
    app.dependency_overrides[get_settings] = lambda: _settings_with_key()

    body = (
        TestClient(app)
        .post(
            "/api/student/plan",
            json={"weeklyHours": 8.0, "narrate": True},
        )
        .json()
    )

    assert body["narrative"] == "Focus on thermal physics this week."
    fake_client.generate_structured.assert_called_once()


def test_plan_post_narrate_without_key_is_503_not_500(
    seeded_store: HistoryStore,
) -> None:
    """narrate=true with no API key returns a clean 503, never an unhandled 500.

    Regression for the Gemini-absent HIGH item: on the default no-key state the
    narrate path must degrade to 503 instead of raising through to a 500.
    """
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: seeded_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    # Default settings carry no API key.
    resp = TestClient(app).post(
        "/api/student/plan",
        json={"weeklyHours": 8.0, "narrate": True},
    )
    assert resp.status_code == 503


def test_plan_post_without_narrate_returns_plan_without_key(
    seeded_store: HistoryStore,
) -> None:
    """Without narrate the deterministic plan still returns even with no key."""
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: seeded_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    resp = TestClient(app).post(
        "/api/student/plan",
        json={"weeklyHours": 8.0, "narrate": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["narrative"] is None
    assert body["sessions"]


def test_plan_post_without_narrate_skips_gemini(seeded_store: HistoryStore) -> None:
    """POST /plan without narrate never touches Gemini."""
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: seeded_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    body = (
        TestClient(app)
        .post(
            "/api/student/plan",
            json={"weeklyHours": 6.0},
        )
        .json()
    )

    assert body["weeklyHours"] == 6.0
    assert body["narrative"] is None


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


# ── Onboarding ────────────────────────────────────────────────────────────────


def test_onboarding_builds_profile_from_sliders() -> None:
    """Onboarding maps subject sliders into a StudentProfile with confidences.

    The profile id is the authenticated student (auth.user_id), never a
    caller-supplied studentId (former IDOR removed).
    """
    app = create_app()
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id="maya", role="student")
    client = TestClient(app)
    body = client.post(
        "/api/student/onboarding",
        json={
            "gradeLevel": "Year 11",
            "school": "Helwan Science Centre",
            "weeklyHours": 11.0,
            "sliders": [
                {"label": "Physics", "code": "0625", "pct": 72},
                {"label": "Chemistry", "code": "0620", "pct": 34},
                {"label": "Hours per week", "code": "", "pct": 46},
            ],
        },
    ).json()

    assert body["studentId"] == "maya"
    assert body["weeklyStudyHours"] == 11.0
    # Only subject sliders (with a code) become subjects / confidences.
    assert body["subjects"] == ["0625", "0620"]
    assert body["confidenceBySubject"] == {"0625": 0.72, "0620": 0.34}
