"""HTTP surface of student self-review (``/api/student/attempts/.../self-review``).

Reuses ``tests/test_student_correct.py``'s ``client`` fixture (real repos over
a throwaway database, Gemini mocked) and adds exactly one override: the
self-review service bound to the same throwaway sessionmaker, with no judge.
The attempt is seeded straight through ``AttemptRepository`` with the shared
``_scheme()`` so it has point rows — the fixture's own MCQ marking path has
none, by design (spec 1: no answer points, no ledger).
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, cast

from fastapi import FastAPI
from sqlalchemy import select

from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
    WeaknessReport,
)
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.models.attempts import QuestionResult, QuestionResultPoint
from lemely.db.self_review_repo import SelfReviewService
from lemely.web.deps import get_self_review_service
from lemely.web.schemas_student_self_review import SelfReviewPendingDTO, SelfReviewPendingPointDTO
from tests import test_student_correct as _student_correct
from tests.conftest import _scheme
from tests.test_student_correct import _seed_user

# Fixtures are re-exported by attribute, not imported by name: a plain ``from
# ... import client`` makes every test parameter named ``client`` an F811
# redefinition, and the only way to silence that per file is to switch F811 off
# for the whole module — which is also what catches two tests sharing a name,
# one of which then never runs. Assignment binds the same fixture objects and
# keeps the rule live.
client = _student_correct.client
corpus_repo = _student_correct.corpus_repo
gemini_client = _student_correct.gemini_client
pg_sessionmaker = _student_correct.pg_sessionmaker
settings = _student_correct.settings

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.upload_repo import StudentUploadRepository


def _low_confidence_report() -> AccuracyReport:
    """One question ("1a", 3 marks, p1 matched) at confidence 0.55 — low."""
    question = CorrectedQuestion(
        question_id="1a",
        awarded_marks=1,
        maximum_marks=3,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.55,
        needs_teacher_review=True,
        student_answer="F = ma so F = 12",
        marker_source="ai",
        feedback="Answer not given to 3 s.f.",
        matched_point_ids=["p1"],
        # Seeded so the route's pass-through of these two is provable: with
        # both null, an assertion on them holds under any implementation that
        # drops the field.
        review_reason="low confidence",
        topic="Forces",
    )
    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0580",
            session_month="May/June",
            session_year=2024,
            paper_number=2,
            paper_variant=1,
        ),
        questions=[question],
    )
    return AccuracyReport(
        correction=correction,
        weaknesses=WeaknessReport(weak_areas=[]),
        grade_prediction=GradePrediction(
            awarded_marks=1,
            maximum_marks=3,
            percentage=33.33,
            grade="E",
            confidence=ConfidenceBand.LOW,
        ),
    )


def _seed_attempt(
    sm: sessionmaker[Session], student_id: str, *, with_scheme: bool = True
) -> tuple[str, str]:
    attempt_id = AttemptRepository(sm).persist_correction(
        user_id=student_id,
        report=_low_confidence_report(),
        mark_scheme=_scheme() if with_scheme else None,
    )
    with sm() as session:
        qr_id = session.scalars(
            select(QuestionResult.id).where(QuestionResult.attempt_id == attempt_id)
        ).one()
    return str(attempt_id), str(qr_id)


def _wire(
    client: tuple[TestClient, str, StudentUploadRepository],
    sm: sessionmaker[Session],
) -> tuple[TestClient, str]:
    api, student_id, _ = client
    app = cast("FastAPI", api.app)
    app.dependency_overrides[get_self_review_service] = lambda: SelfReviewService(sm, judge=None)
    return api, student_id


def _path(attempt_id: str, qr_id: str) -> str:
    return f"/api/student/attempts/{attempt_id}/questions/{qr_id}/self-review"


def _assert_no_key_containing(
    payload: object, needle: str, *, except_keys: frozenset[str] = frozenset()
) -> None:
    """Recursive: no dict key at any depth contains ``needle`` (case-insensitive).

    ``except_keys`` names keys that legitimately contain the needle without
    leaking anything — e.g. ``maxMarks`` on the pending DTO is the question's
    fixed maximum, known and asserted before self-review even starts; it is
    not one of the verdict-bearing ``aiMarks``/``effectiveMarks``/
    ``studentMarks`` fields this check exists to catch.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key not in except_keys:
                assert needle not in str(key).lower(), f"key {key!r} leaks the verdict"
            _assert_no_key_containing(value, needle, except_keys=except_keys)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_key_containing(value, needle, except_keys=except_keys)


def _full_pass(evidence: str | None = None) -> dict[str, object]:
    return {
        "points": [
            {"markPointId": pid, "earned": True, "evidence": evidence} for pid in ("p1", "p2", "p3")
        ]
    }


def test_pending_point_dto_has_exactly_the_allowlisted_fields() -> None:
    """Allowlist, not denylist (review of the service layer, S2 task 8).

    A denylist ("must not have a field called `awarded`") passes for a field
    called ``hint``, ``marker_note`` or ``rationale`` just as easily — any of
    those would leak the marker's reasoning before the reveal without ever
    matching ``"awarded"``/``"selfmark"``/``"verdict"``/``"marks"``. This
    pins the complete field set so *any* new field on the pending point DTO
    fails this test and forces a deliberate decision about whether it leaks
    the verdict, rather than sailing through unnoticed.
    """
    assert set(SelfReviewPendingPointDTO.model_fields) == {
        "markPointId",
        "ordinal",
        "markType",
        "tariff",
        "pointText",
        "isAlternative",
        "isOptional",
        "groupKey",
        "groupMaxMarks",
    }


def test_pending_dto_has_exactly_the_allowlisted_fields() -> None:
    """Container-level allowlist companion to the point-level one above.

    The point-level test alone doesn't stop a verdict-bearing field being
    added to the *container* DTO itself (``markerFeedback``, ``hint``,
    ``rationale``, ``confidence``, ``reviewReason``, ``judgeReason``, ...) —
    none of those would be caught by asserting only the points' shape.
    """
    assert set(SelfReviewPendingDTO.model_fields) == {
        "state",
        "attemptId",
        "questionResultId",
        "questionId",
        "maxMarks",
        "evidenceRequired",
        "points",
    }


def test_get_before_submission_withholds_the_verdict_entirely(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """THE test. If this payload ever carried the verdict under any key, the
    feature would be defeated by opening devtools while every other test
    still passed."""
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)

    resp = api.get(_path(attempt_id, qr_id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {
        "state",
        "attemptId",
        "questionResultId",
        "questionId",
        "maxMarks",
        "evidenceRequired",
        "points",
    }
    assert body["state"] == "not_started"
    assert body["attemptId"] == attempt_id
    assert body["questionResultId"] == qr_id
    assert body["questionId"] == "1a"
    assert body["maxMarks"] == 3
    assert body["evidenceRequired"] is False
    assert [p["markPointId"] for p in body["points"]] == ["p1", "p2", "p3"]
    assert body["points"][0] == {
        "markPointId": "p1",
        "ordinal": 0,
        "markType": "M",
        "tariff": 1,
        "pointText": "Correct method",
        # Scheme-derived, verdict-free (Task 6a) — p1 is an independent
        # point, so all four are their non-group defaults.
        "isAlternative": False,
        "isOptional": False,
        "groupKey": None,
        "groupMaxMarks": None,
    }
    _assert_no_key_containing(body, "awarded")
    _assert_no_key_containing(body, "selfmark")
    _assert_no_key_containing(body, "verdict")
    # no aiMarks / effectiveMarks / studentMarks; maxMarks and groupMaxMarks
    # (Task 6a) are scheme-derived and verdict-free, already asserted above
    # via the exact points[0] dict.
    _assert_no_key_containing(body, "marks", except_keys=frozenset({"maxMarks", "groupMaxMarks"}))


def test_post_reveals_and_applies_a_low_confidence_self_mark(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)

    resp = api.post(_path(attempt_id, qr_id), json=_full_pass())

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "settled"
    assert body["aiMarks"] == 1
    assert body["studentMarks"] == 3
    assert body["effectiveMarks"] == 3
    assert body["teacherSettled"] is False
    assert body["pendingTeacher"] is False
    assert body["submittedAt"]
    assert [p["awarded"] for p in body["points"]] == [True, False, False]
    assert [p["studentSelfmark"] for p in body["points"]] == [True, True, True]
    assert [p["markChanged"] for p in body["points"]] == [False, True, True]
    assert [p["evidenceVerdict"] for p in body["points"]] == [None, "not_required", "not_required"]

    # And a GET now reveals the same.
    again = api.get(_path(attempt_id, qr_id)).json()
    assert again["state"] == "settled"
    assert [p["awarded"] for p in again["points"]] == [True, False, False]


def test_second_post_is_409(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)
    assert api.post(_path(attempt_id, qr_id), json=_full_pass()).status_code == 200

    assert api.post(_path(attempt_id, qr_id), json=_full_pass()).status_code == 409


def test_partial_submission_is_422(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)

    resp = api.post(
        _path(attempt_id, qr_id),
        json={"points": [{"markPointId": "p1", "earned": True}]},
    )

    assert resp.status_code == 422
    assert "missing" in resp.json()["detail"]
    # Nothing was revealed by the refused pass — and the request underneath
    # actually succeeded and returned the pending shape, so the absence of
    # "awarded" below isn't just an error body passing the check trivially.
    after = api.get(_path(attempt_id, qr_id))
    assert after.json()["state"] == "not_started"
    _assert_no_key_containing(after.json(), "awarded")


def test_another_students_attempt_is_404_on_both_verbs(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, _ = _wire(client, pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, other)

    assert api.get(_path(attempt_id, qr_id)).status_code == 404
    assert api.post(_path(attempt_id, qr_id), json=_full_pass()).status_code == 404


def test_mismatched_attempt_and_question_is_404_on_both_verbs(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The IDOR shape an actual probe takes: both attempts owned by the
    caller, but the question_result_id in the URL belongs to a *different*
    attempt than the attempt_id in the URL. This exercises the mismatch
    branch (``qr.attempt_id != attempt.id``) in ``_owned_question``, distinct
    from the other-student ownership branch covered above."""
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_a_id, _ = _seed_attempt(pg_sessionmaker, student_id)
    _, qr_b_id = _seed_attempt(pg_sessionmaker, student_id)

    assert api.get(_path(attempt_a_id, qr_b_id)).status_code == 404
    assert api.post(_path(attempt_a_id, qr_b_id), json=_full_pass()).status_code == 404


def test_malformed_ids_are_404(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, _ = _wire(client, pg_sessionmaker)
    assert api.get(_path("not-a-uuid", "nope")).status_code == 404
    assert api.post(_path("not-a-uuid", "nope"), json=_full_pass()).status_code == 404


def test_evidence_input_is_bounded_at_the_edge(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Loose input meets a strict constraint at the DTO, not in the transaction."""
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)

    assert api.post(_path(attempt_id, qr_id), json=_full_pass("ok\x00")).status_code == 422
    assert api.post(_path(attempt_id, qr_id), json=_full_pass("x" * 2001)).status_code == 422
    assert api.post(_path(attempt_id, qr_id), json={"points": []}).status_code == 422
    assert api.post(_path(attempt_id, qr_id), json={}).status_code == 422
    # None of those touched the row.
    assert api.get(_path(attempt_id, qr_id)).json()["state"] == "not_started"


def test_attempt_questions_route_lists_rows_with_ids_and_no_integrity_flags(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Every field of the row, against the seeded values it is built from.

    The free-text-ish fields were asserted by nothing: replacing
    ``feedback``/``reviewReason``/``topic`` with literals in the route left all
    12 tests green, which is how the integrity leak in ``reviewReason`` reached
    the screen in the first place. The two integrity booleans are exercised
    against a *flagged* row in the sibling test below; here they only witness
    the default.

    ``matchedPointIds`` is pinned ``None`` on purpose: the seeded question
    matched ``p1``, so the pre-fix value here was ``["p1"]`` — the marker's
    per-point verdict, on the same screen as the panel that asks the student to
    commit against it. See
    ``test_no_student_payload_but_the_panels_own_names_a_mark_point``.
    """
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)

    resp = api.get(f"/api/student/attempts/{attempt_id}/questions")

    assert resp.status_code == 200, resp.text
    [row] = resp.json()
    assert row["questionId"] == "1a"
    assert row["questionResultId"] == qr_id
    assert row["awardedMarks"] == 1 and row["maxMarks"] == 3
    assert row["markerSource"] == "ai"
    assert row["confidence"] == 0.55
    assert row["feedback"] == "Answer not given to 3 s.f."
    assert row["matchedPointIds"] is None
    assert row["reviewReason"] == "low confidence"
    assert row["topic"] == "Forces"
    assert row["plagiarismFlagged"] is False and row["aiDetectionFlagged"] is False
    # Low-confidence at persist opens a `low_confidence` queue row, and no
    # self-mark has happened yet to close it.
    assert row["pendingTeacher"] is True

    # After a self-mark the list shows the effective mark.
    assert api.post(_path(attempt_id, qr_id), json=_full_pass()).status_code == 200
    assert api.get(f"/api/student/attempts/{attempt_id}/questions").json()[0]["awardedMarks"] == 3


def test_attempt_questions_route_pending_teacher_settles_but_review_reason_stays(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The stale-flag defect (S2 review), on the wire.

    A settled self-mark closes the `low_confidence` queue row (D4), and this
    route's `pendingTeacher` must say so -- otherwise the result screen keeps
    a "Needs review" chip and a "waiting for your teacher" banner on a
    question the panel right above them just reported as marked and closed.
    `reviewReason` is asserted unchanged alongside it: this is a second,
    current-truth signal, not a rewrite of the marker's own record.
    """
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)

    assert api.post(_path(attempt_id, qr_id), json=_full_pass()).status_code == 200

    [row] = api.get(f"/api/student/attempts/{attempt_id}/questions").json()
    assert row["pendingTeacher"] is False
    assert row["reviewReason"] == "low confidence"


def test_attempt_questions_route_never_shows_a_student_an_integrity_finding(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """``review_reason`` carries the plagiarism/AI verdict as free text.

    ``lemely/io/integrity.py`` appends "plagiarism (score 0.94)" to the same
    ``" | "``-joined reason that holds ordinary marking reasons, and
    ``PaperResult`` renders it verbatim as "Needs review: ...". Forcing the two
    booleans to ``False`` while forwarding the sentence tells the student
    anyway, with a score on it -- QUALITY-BAR.md makes integrity flags
    teacher-only. The ordinary reason must still come through.
    """
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)
    with pg_sessionmaker.begin() as session:
        row = session.get(QuestionResult, uuid.UUID(qr_id))
        assert row is not None
        row.review_reason = "plagiarism (score 0.94) | low confidence | ai_detection (score 0.88)"
        row.plagiarism_flagged = True
        row.ai_detection_flagged = True

    [wire_row] = api.get(f"/api/student/attempts/{attempt_id}/questions").json()

    assert wire_row["reviewReason"] == "low confidence"
    assert wire_row["plagiarismFlagged"] is False and wire_row["aiDetectionFlagged"] is False
    # Values only -- the field *names* are plagiarismFlagged/aiDetectionFlagged,
    # so a whole-payload substring check would pass on the key alone.
    values = json.dumps([v for v in wire_row.values() if isinstance(v, str)])
    assert "plagiarism" not in values
    assert "ai_detection" not in values


def test_attempt_questions_route_sends_no_question_result_id_without_point_rows(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A question with no point rows is not self-reviewable, on the wire.

    ``questionResultId`` is what the frontend gates the panel on. Sending it
    for a quiz or a paper marked before spec 1 shipped offers a student a
    panel whose ``GET .../self-review`` then 404s. The sibling test above only
    ever sees the point-bearing case, where an unconditional id passes.
    """
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, _ = _seed_attempt(pg_sessionmaker, student_id, with_scheme=False)

    [row] = api.get(f"/api/student/attempts/{attempt_id}/questions").json()

    assert row["questionId"] == "1a"
    assert row["questionResultId"] is None


def test_attempt_questions_route_is_404_for_another_student(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    api, _ = _wire(client, pg_sessionmaker)
    attempt_id, _ = _seed_attempt(pg_sessionmaker, _seed_user(pg_sessionmaker))
    assert api.get(f"/api/student/attempts/{attempt_id}/questions").status_code == 404
    assert api.get("/api/student/attempts/nope/questions").status_code == 404


def _string_values(payload: object) -> set[str]:
    """Every string *value* at any depth; keys excluded.

    Keys are excluded deliberately: a point id can only leak as a value, and
    folding keys in would fire on any field whose *name* happened to collide.
    Exact values, not substrings — ``"p1"`` is two characters, and a substring
    sweep over a JSON body matches too much to mean anything.
    """
    if isinstance(payload, dict):
        return {found for value in payload.values() for found in _string_values(value)}
    if isinstance(payload, list):
        return {found for value in payload for found in _string_values(value)}
    return {payload} if isinstance(payload, str) else set()


def test_no_student_payload_but_the_panels_own_names_a_mark_point(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The cross-payload reveal gate. Withholding the verdict from one payload is not enough.

    ``QuestionResultPoint.awarded`` is ``point.id in matched_point_ids``
    (``lemely/db/question_points.py``), so ``matchedPointIds`` on the *sibling*
    row payload **is** the per-point verdict, spelled as a subset of the ids the
    panel is about to ask the student to commit against. Both payloads render on
    the same screen, so a student mid-review could read the answer out of the
    Network tab while every reveal test stayed green — each of those checks the
    panel's own payload, and none looked next door.

    The panel's own pending payload is the one place point ids legitimately
    appear: it lists *every* point of the question, awarded or not, which is
    precisely what makes it verdict-free. Any other student-reachable payload
    naming a subset of them is a reveal, so this asserts the complement —
    nowhere else on the attempt, at any depth.
    """
    api, student_id = _wire(client, pg_sessionmaker)
    attempt_id, qr_id = _seed_attempt(pg_sessionmaker, student_id)

    with pg_sessionmaker() as session:
        point_ids = set(
            session.scalars(
                select(QuestionResultPoint.mark_point_id).where(
                    QuestionResultPoint.question_result_id == uuid.UUID(qr_id)
                )
            )
        )
    # The seeded question matches p1 only, so an unfiltered ``matchedPointIds``
    # names exactly the awarded point and nothing else — the leak, verbatim.
    assert point_ids == {"p1", "p2", "p3"}

    pending = api.get(_path(attempt_id, qr_id))
    assert pending.status_code == 200, pending.text
    assert pending.json()["state"] == "not_started"
    # The panel's own payload is allowed the ids and must carry *all* of them;
    # a subset here would be the same leak wearing the other payload's name.
    assert point_ids <= _string_values(pending.json())

    elsewhere = {
        "attempt questions": api.get(f"/api/student/attempts/{attempt_id}/questions"),
        "overview": api.get("/api/student/overview"),
        "subject": api.get("/api/student/subject/0580"),
        "result": api.get("/api/student/result/0"),
    }
    # Statuses are pinned rather than tolerated: a route that quietly starts
    # 404ing would turn its sweep below into a vacuous pass. ``subject``/
    # ``result`` read the history store, which this fixture seeds attempts
    # around rather than through, so their 404 is this fixture's shape — but
    # it has to be *stated* to count as a reason.
    assert {name: resp.status_code for name, resp in elsewhere.items()} == {
        "attempt questions": 200,
        "overview": 200,
        "subject": 404,
        "result": 404,
    }
    for name, resp in elsewhere.items():
        leaked = sorted(point_ids & _string_values(resp.json()))
        assert not leaked, f"{name} names mark points {leaked} before the reveal"
