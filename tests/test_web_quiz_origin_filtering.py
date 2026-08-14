"""The grade-bearing / topic-bearing split, pinned at the web layer (P3.5 chunk F1).

``docs/quiz-model.md`` §5 tabulates which ``lemely/core/`` consumer filters on
:func:`~lemely.core.history.is_grade_bearing` and which takes every record.
Chunk G wired that table up in core and handed the *web layer* to chunk F,
because a router that derives a grade or a percentage straight off
``history.records`` is behaviourally fine right up until the first quiz attempt
exists — and becomes live corruption the moment quiz marking starts writing
them, which is exactly what chunk F1 does.

Every test here seeds a history that mixes a real past paper with a
quiz-origin record and asserts the split holds:

* grade / percentage / paper-comparison surfaces see **papers only**;
* topic and activity surfaces see **everything**, because a weakness is a
  weakness whatever revealed it and a quiz is a day the student showed up;
* counts that call themselves *papers* use :func:`~lemely.core.history.is_paper`
  (origin only) — a past paper whose grade came back unreadable is still a
  paper that was sat, but a quiz never is.

The teacher-surface tests call the module-level DTO helpers directly rather
than going through HTTP: those helpers are pure functions of a
:class:`~lemely.core.history.StudentHistory`, and reaching them over the wire
would drag in the whole class-tenancy stack (Postgres, rosters, auth) without
testing one extra line of the filtering this module exists to protect. The
student-surface tests *do* go through HTTP, because there the filter sits
inside the route function itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.core.at_risk import AtRiskReason, assess_at_risk, flag_fingerprint
from lemely.core.history import PaperRecord, StudentHistory
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db.at_risk_repo import AtRiskAcknowledgementRow
from lemely.db.class_repo import RosterEntry
from lemely.io.history_store import HistoryStore
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_history_store
from lemely.web.routers.classes import _average_for
from lemely.web.routers.teacher import (
    _at_risk,
    _student_delta,
    _student_detail_dto,
    _student_engagement_dto,
    _student_row,
    _subject_predictions,
)

if TYPE_CHECKING:
    from pathlib import Path

STUDENT_ID = "3f6c1b0e-6f5e-4b0a-9f3e-2c1d0a7b8e91"

# Fixed clock: every seeded record is stamped relative to this, so the D3.3
# at-risk inactivity rule fires (or does not) deterministically rather than
# against wall-clock time.
NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def _record(
    *,
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
    """One history record; ``origin="quiz"`` builds the quiz shape the DB writes.

    A quiz attempt reaches the history store with ``grade=""`` (the marking
    path deliberately never writes a grade — a quiz has no boundaries) and the
    synthetic ``paper_number``/``paper_variant`` of 1/1 that
    :class:`~lemely.core.schemas.ExamMetadata`'s validators forced on the
    in-memory marking call. Both are reproduced here, because both are what a
    missing filter would surface to a user.
    """
    return PaperRecord(
        student_id=STUDENT_ID,
        metadata=ExamMetadata(
            subject_code=subject_code,
            paper_number=paper_number,
            paper_variant=paper_variant,
            session_month="May/June" if origin == "past_paper" else "Specimen",
            session_year=2025 if origin == "past_paper" else None,
        ),
        awarded_marks=awarded if awarded is not None else int(percentage / 100 * maximum),
        maximum_marks=maximum,
        percentage=percentage,
        grade=grade,
        weak_areas=[
            WeakArea(
                topic=topic,
                lost_marks=4,
                maximum_marks=10,
                accuracy=0.6,
                question_ids=["3a"],
            )
        ],
        recorded_at=recorded_at,
        origin=origin,  # type: ignore[arg-type]
    )


def _paper(**kwargs: object) -> PaperRecord:
    """A past-paper record: 80% / grade B on 0625 Paper 1 Variant 2 unless overridden."""
    defaults: dict[str, object] = {
        "percentage": 80.0,
        "grade": "B",
        "recorded_at": "2026-08-04T10:00:00+00:00",
    }
    defaults.update(kwargs)
    return _record(**defaults)  # type: ignore[arg-type]


def _quiz(**kwargs: object) -> PaperRecord:
    """A quiz record: 40% on a hard topic, no grade, synthetic Paper 1/1.

    Deliberately *lower* than :func:`_paper`'s 80% and *later* in append order,
    so any surface that fails to filter it moves visibly in the wrong
    direction rather than coincidentally agreeing.
    """
    defaults: dict[str, object] = {
        "percentage": 40.0,
        "grade": "",
        "origin": "quiz",
        "paper_number": 1,
        "paper_variant": 1,
        "maximum": 10,
        "recorded_at": "2026-08-05T10:00:00+00:00",
    }
    defaults.update(kwargs)
    return _record(**defaults)  # type: ignore[arg-type]


def _history(*records: PaperRecord) -> StudentHistory:
    return StudentHistory(student_id=STUDENT_ID, records=list(records))


# ---------------------------------------------------------------------------
# Teacher surfaces (pure DTO helpers).
# ---------------------------------------------------------------------------


def test_student_row_grade_and_mark_come_from_the_latest_paper_not_the_latest_quiz() -> None:
    """A quiz appended after a paper must not become the roster row's grade."""
    row = _student_row(
        _history(_paper(), _quiz()),
        display_name="Maya",
        student_id=STUDENT_ID,
        now=NOW,
        acks={},
    )

    assert row is not None
    assert row.grade == "B"
    assert row.mark == "64/80"
    assert row.gradeAtRisk is False


def test_student_row_survives_a_quiz_only_history_with_an_empty_grade() -> None:
    """Quiz-only activity keeps the roster row, honestly reporting no grade.

    Dropping the student from the roster would be worse than an empty grade:
    they *are* enrolled and they *have* done work. ``grade=""`` is the same
    "no grade" value ``DbHistoryStore`` already produces for an attempt whose
    grade column is NULL, so this is not a new state for the frontend.
    """
    row = _student_row(
        _history(_quiz()), display_name="Maya", student_id=STUDENT_ID, now=NOW, acks={}
    )

    assert row is not None
    assert row.grade == ""
    assert row.mark == ""
    assert row.weakTopic is None
    assert row.gradeAtRisk is False
    # The quiz is not a paper (D3.9's ``is_paper``), but it IS activity.
    assert row.paperCount == 0
    assert row.lastActiveAt == _quiz().recorded_at


def test_student_row_is_still_none_for_a_student_with_no_records_at_all() -> None:
    """The pre-existing empty-history contract is unchanged by the filter."""
    assert (
        _student_row(_history(), display_name="Maya", student_id=STUDENT_ID, now=NOW, acks={})
        is None
    )


def test_student_row_paper_count_uses_is_paper_not_is_grade_bearing() -> None:
    """``paperCount`` counts papers (origin only), not grade-bearing records (D3.9).

    A past paper whose grade came back unreadable is still a paper the
    student sat; filtering on ``is_grade_bearing`` instead would make
    ``paperCount`` silently disagree with the paper the roster row's own
    ``grade``/``mark`` fields are built from. Two real papers plus one quiz:
    ``paperCount`` must read 2, not 1 (which is what an
    ``is_grade_bearing``-filtered count would report once the unreadable
    grade is dropped) and not 3 (which is what an unfiltered count, counting
    the quiz too, would report).
    """
    unreadable = _record(
        origin="past_paper",
        grade="",  # came back unreadable — still a paper that was sat
        percentage=50.0,
        recorded_at="2026-08-03T10:00:00+00:00",
    )
    history = _history(_paper(), unreadable, _quiz())

    row = _student_row(history, display_name="Maya", student_id=STUDENT_ID, now=NOW, acks={})

    assert row is not None
    assert row.paperCount == 2


def test_student_row_last_active_at_is_unfiltered_by_origin() -> None:
    """``lastActiveAt`` sees the quiz too — a quiz is activity (D3.9)."""
    history = _history(_paper(), _quiz())

    row = _student_row(history, display_name="Maya", student_id=STUDENT_ID, now=NOW, acks={})

    assert row is not None
    assert row.lastActiveAt == _quiz().recorded_at


def test_student_row_flags_carry_reason_and_acknowledgement_state() -> None:
    """``flags`` is populated through the shared ``_at_risk_flag_dto`` (D3.5/D3.3).

    A declining trend over three papers must appear as a flag with its
    reason, and an acknowledgement recorded against the same evidence
    fingerprint must be reflected here exactly as it would be on the
    overview/at-risk list (never a second, independently-computed flag
    conversion).
    """
    history = _history(
        _paper(percentage=72.0, grade="B", recorded_at="2026-08-01T10:00:00+00:00"),
        _paper(percentage=65.0, grade="C", recorded_at="2026-08-02T10:00:00+00:00"),
        _paper(percentage=58.0, grade="D", recorded_at="2026-08-03T10:00:00+00:00"),
    )

    row = _student_row(history, display_name="Maya", student_id=STUDENT_ID, now=NOW, acks={})
    assert row is not None
    assert len(row.flags) == 1
    assert row.flags[0].reason == "declining_trend"
    assert row.flags[0].acknowledged is None

    flag = assess_at_risk(history, now=NOW).flags[0]
    acks = {
        (STUDENT_ID, AtRiskReason.DECLINING_TREND): AtRiskAcknowledgementRow(
            student_id=uuid.UUID(STUDENT_ID),
            reason=AtRiskReason.DECLINING_TREND,
            evidence_fingerprint=flag_fingerprint(flag),
            note="Spoke to student",
            acknowledged_by=uuid.uuid4(),
            acknowledged_at=NOW,
        )
    }
    acked_row = _student_row(
        history, display_name="Maya", student_id=STUDENT_ID, now=NOW, acks=acks
    )
    assert acked_row is not None
    assert acked_row.flags[0].acknowledged is not None
    assert acked_row.flags[0].acknowledged.note == "Spoke to student"


def test_student_delta_ignores_a_quiz_masquerading_as_paper_one_variant_one() -> None:
    """A quiz's synthetic 1/1 identity must not be matched as a prior attempt.

    Two real 0625 Paper 1/2 attempts (70% then 80%) give a +10 delta. The quiz
    sits between them carrying paper 1/1 — unfiltered it would both stand in as
    "the latest paper" and offer itself as a same-paper prior.
    """
    history = _history(
        _paper(percentage=70.0, grade="C", recorded_at="2026-08-01T10:00:00+00:00"),
        _quiz(recorded_at="2026-08-02T10:00:00+00:00"),
        _paper(percentage=80.0, grade="B", recorded_at="2026-08-04T10:00:00+00:00"),
    )

    assert _student_delta(history) == pytest.approx(10.0)


def test_student_delta_is_none_when_every_record_is_a_quiz() -> None:
    assert _student_delta(_history(_quiz(), _quiz())) is None


def test_subject_predictions_omit_a_subject_the_student_has_only_quizzed() -> None:
    """A quiz-only subject yields no prediction row rather than a row grading ``""``."""
    history = _history(_paper(subject_code="0625"), _quiz(subject_code="0580"))

    rows = _subject_predictions(history)

    assert [row.subjectCode for row in rows] == ["0625"]
    assert rows[0].predictedGrade == "B"
    assert rows[0].latestPercentage == pytest.approx(80.0)
    assert rows[0].paperCount == 1


def test_engagement_counts_papers_as_papers_but_dates_activity_from_any_record() -> None:
    """``totalPapers`` excludes the quiz; ``lastActiveAt`` is the quiz's own date.

    The two halves genuinely disagree, and that is the point: the at-risk
    engine's inactivity rule counts a quiz as activity, so a screen reporting
    "20 days silent" beside a badge that saw the student yesterday would be
    describing a different student than the badge next to it.
    """
    engagement = _student_engagement_dto(_history(_paper(), _quiz()), now=NOW)

    assert engagement.totalPapers == 1
    assert engagement.lastActiveAt == "2026-08-05T10:00:00+00:00"
    assert engagement.daysSinceLastSubmission == 1


def test_at_risk_row_grade_comes_from_the_latest_paper() -> None:
    """A flagged student's reported grade is their latest *paper* grade."""
    history = _history(
        _paper(percentage=60.0, grade="D", recorded_at="2026-07-20T10:00:00+00:00"),
        _paper(percentage=50.0, grade="E", recorded_at="2026-07-25T10:00:00+00:00"),
        _paper(percentage=40.0, grade="U", recorded_at="2026-07-30T10:00:00+00:00"),
        _quiz(percentage=90.0, recorded_at="2026-08-05T10:00:00+00:00"),
    )

    rows = _at_risk([(history, "Maya")], now=NOW, acks={})

    assert len(rows) == 1
    assert rows[0].grade == "U"


def test_student_detail_attempts_and_trend_exclude_quizzes_but_weaknesses_do_not() -> None:
    """T-05: the paper table and sparkline are papers; the weakness list is everything.

    The quiz carries a topic (``Momentum``) the student's paper does not, so a
    filtered weakness list would silently lose the only evidence for it.
    """
    history = _history(_paper(topic="Thermal physics"), _quiz(topic="Momentum"))
    entry = RosterEntry(student_id=uuid.UUID(STUDENT_ID), display_name="Maya")

    detail = _student_detail_dto(entry, history, now=NOW, acks={})

    assert [a.percentage for a in detail.attempts] == [pytest.approx(80.0)]
    assert [a.paperId for a in detail.attempts] == ["0625/12"]
    assert [p.percentage for p in detail.trend] == [pytest.approx(80.0)]
    assert {w.topic for w in detail.weaknesses} == {"Thermal physics", "Momentum"}
    assert detail.engagement.totalPapers == 1


# ---------------------------------------------------------------------------
# Class surfaces.
# ---------------------------------------------------------------------------


def test_class_average_uses_each_student_latest_paper_never_their_latest_quiz(
    tmp_path: Path,
) -> None:
    """A quiz appended after a paper must not drag the class mean down."""
    store = HistoryStore(tmp_path / "history")
    store.append(STUDENT_ID, _paper(percentage=80.0, grade="B"))
    store.append(STUDENT_ID, _quiz(percentage=40.0))

    assert _average_for([store.load(STUDENT_ID)]) == pytest.approx(80.0)


def test_class_average_skips_a_quiz_only_student_rather_than_scoring_them(
    tmp_path: Path,
) -> None:
    """Quiz-only students contribute nothing — not a 40% that means something else."""
    other = "9a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d"
    store = HistoryStore(tmp_path / "history")
    store.append(STUDENT_ID, _paper(percentage=80.0, grade="B"))
    store.append(other, _quiz(percentage=40.0))

    assert _average_for([store.load(STUDENT_ID), store.load(other)]) == pytest.approx(80.0)


def test_class_average_is_none_when_nobody_has_sat_a_paper(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history")
    store.append(STUDENT_ID, _quiz())

    assert _average_for([store.load(STUDENT_ID)]) is None


# ---------------------------------------------------------------------------
# Student surfaces (over HTTP — the filter lives inside the route functions).
# ---------------------------------------------------------------------------


@pytest.fixture
def mixed_store(tmp_path: Path) -> HistoryStore:
    """One 0625 paper (80%, grade B) followed by one 0625 quiz (40%, no grade)."""
    store = HistoryStore(tmp_path / "history")
    store.append(STUDENT_ID, _paper(percentage=80.0, grade="B", topic="Thermal physics"))
    store.append(STUDENT_ID, _quiz(percentage=40.0, topic="Momentum"))
    return store


@pytest.fixture
def client(mixed_store: HistoryStore) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: mixed_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    return TestClient(app)


def test_overview_subject_row_reports_the_paper_only(client: TestClient) -> None:
    """``pct``/``papers`` on the Overview subject row exclude the quiz.

    Unfiltered, the mark-weighted mean would fold 4/10 into 64/80 and report
    76% instead of 80% — a forecast grade moved by marks no CAIE boundary was
    ever drawn for.
    """
    body = client.get("/api/student/overview").json()

    rows = {row["code"]: row for row in body["subjects"]}
    assert set(rows) == {"0625"}
    assert rows["0625"]["pct"] == 80
    assert rows["0625"]["papers"] == 1


def test_overview_momentum_line_is_drawn_from_papers_only(client: TestClient) -> None:
    """One paper + one quiz is one *point*, so the sparkline stays empty.

    A polyline needs two points. Unfiltered, the quiz would supply a second
    one and draw a dive the student reads as "my papers are getting worse".
    """
    body = client.get("/api/student/overview").json()

    assert body["momentum"]["points"] == []


def test_overview_weak_threads_still_see_the_quiz_topic(client: TestClient) -> None:
    """Topic aggregation is deliberately unfiltered — the quiz's topic survives."""
    body = client.get("/api/student/overview").json()

    assert "Momentum" in {thread["topic"] for thread in body["weakGlobal"]}


def test_subject_detail_papers_exclude_the_quiz_but_the_topic_map_includes_it(
    client: TestClient,
) -> None:
    """S-subject: one breakdown card and one history row; both topics on the map.

    Unfiltered, the quiz's synthetic 1/1 identity would open a second "Paper 1"
    breakdown card sourced from an assessment the student never sat as a paper.
    """
    body = client.get("/api/student/subject/0625").json()

    assert [b["title"] for b in body["papersBreakdown"]] == ["Paper 1"]
    assert [bar["value"] for bar in body["papersBreakdown"][0]["bars"]] == [80]
    assert [row["pct"] for row in body["paperHistory"]] == ["80%"]
    assert body["header"]["weightedMean"] == "80"
    assert {tile["name"] for tile in body["topicMap"]} == {"Thermal physics", "Momentum"}


def test_subject_detail_404s_for_a_subject_the_student_has_only_quizzed(
    client: TestClient, mixed_store: HistoryStore
) -> None:
    """A quiz-only subject has no paper standing, so the paper screen is a 404.

    Not a silent empty page: the screen's entire content is paper-derived, and
    an empty one would read as "you have no data" when the quiz data exists and
    is shown elsewhere (Overview weak threads, the topic map of any subject the
    student has also papered).
    """
    mixed_store.append(STUDENT_ID, _quiz(subject_code="0580"))

    response = client.get("/api/student/subject/0580")

    assert response.status_code == 404
    assert "0580" in response.json()["detail"]


def test_standings_counts_papers_as_papers_and_quizzes_as_activity(client: TestClient) -> None:
    """``paperCount``/per-subject ``papers`` exclude the quiz; ``streakDays`` does not.

    The seeded records fall on two distinct calendar days, one of which is only
    the quiz — filtering the streak would erase a day the student turned up.
    """
    body = client.get("/api/student/standings").json()

    assert body["paperCount"] == 1
    assert [row["papers"] for row in body["subjectRanks"]] == [1]
    assert body["streakDays"] == 2
