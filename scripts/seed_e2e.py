#!/usr/bin/env python3
"""Shared multi-role seed fixture for E2E/audit harnesses (P3.10 chunk a).

Seeds the **live local Supabase stack** (real GoTrue + real Postgres, wired
through the exact same singletons ``lemely.web.deps`` hands the FastAPI app —
:class:`~lemely.auth.service.AuthService`, :class:`~lemely.db.class_repo.ClassService`,
:class:`~lemely.db.attempt_repo.AttemptRepository`,
:class:`~lemely.db.parent_repo.ParentLinkService`) with every account and
scenario the Playwright/Puppeteer harnesses need across all 5 roles:

* a **teacher** owning one class,
* a **roster** of 3 students in that class covering the two at-risk rules
  that can fire in Phase 3 plus a healthy control:
    - ``declining``  — 3 past-paper attempts, strictly decreasing, >=5pp drop
      (D3.3 rule 1). All 3 are the **same subject** deliberately: rule 1 reads
      the last 3 grade-bearing records across ALL subjects, so a second
      subject interleaved into this run would stop the flag firing.
    - ``inactive``   — 1 past-paper attempt recorded >=14 days ago (rule 2).
    - ``control``    — 3 past-paper attempts, not declining, all recent.
      Must NOT be flagged by any rule.
  Rule 2 ("predicted >= 2 grades below target", D3.3) cannot fire in Phase 3:
  there is no target-grade column until Phase 4's onboarding questionnaire
  (decision D3.3/D3.9 note in ``lemely.core.at_risk``), so it is never
  exercised here — not faked, not worked around.
* a standalone **student** (``correctedPaper``, not enrolled in the class)
  with one persisted past-paper attempt, so grade/percentage surfaces on the
  student portal are non-empty without entangling the at-risk assertions.
* a **parent**, OTP-verified and linked to the ``declining`` student. Linking
  is student-initiated by phone (D3.11): the parent OTP-logs-in first (which
  auto-creates their ``role=parent`` user, per
  :meth:`~lemely.auth.service.AuthService.verify_otp`), then
  :meth:`~lemely.db.parent_repo.ParentLinkService.link` is called exactly as
  the student-facing router calls it.
* a **school_admin**, minted directly via :meth:`AuthService.signup` (self-
  service signup is student-only; teacher/school_admin only ever come from a
  direct service call — this is what P3.7 chunk d did).

Every attempt is persisted as ``origin=past_paper`` (D3.9): every grade/
percentage/paper claim in this codebase filters on grade-bearing origin, so a
quiz attempt would silently fail to back any of these scenarios.

Idempotent-friendly: every email and the parent phone number are namespaced
under a per-run ``runTag`` (default: 12 random hex chars), so repeated runs
never collide. Reruns do not delete previous runs' rows — there is no
teardown here, by design (this is a seed script, not a fixture cleaner).

The OTP resend cooldown (``otp_min_resend_seconds``, default 30s) is
per-phone. This script requests exactly one challenge for the parent's phone
and returns the access token that verifying it already produced — a
consumer (Playwright, ``audit.mjs``) must reuse that token rather than
starting a second OTP challenge for the same phone, or it will hit the
cooldown.

Output contract
----------------
A single JSON object, written to stdout (nothing else touches stdout — all
progress goes to stderr) and, when ``--json-out`` is given, also to that
path::

    {
      "runTag": "a1b2c3d4e5f6",
      "generatedAt": "2026-08-07T12:00:00+00:00",
      "teacher": {"userId": "...", "email": "...", "password": "...",
                  "accessToken": "..."},
      "schoolAdmin": {"userId": "...", "email": "...", "password": "...",
                      "accessToken": "..."},
      "class": {"classId": "...", "name": "...", "joinCode": "ABC123"},
      "students": {
        "declining": {"userId": "...", "email": "...", "password": "...",
                      "displayName": "...", "accessToken": "...",
                      "expectedAtRiskReasons": ["declining_trend"]},
        "inactive":  {..., "expectedAtRiskReasons": ["inactive"]},
        "control":   {..., "expectedAtRiskReasons": []},
        "correctedPaper": {..., "expectedAtRiskReasons": [],
                            "correctedPaperId": "<attempt uuid>"}
      },
      "parent": {"userId": "...", "phone": "+20...", "accessToken": "...",
                 "linkedStudent": "declining"}
    }

``expectedAtRiskReasons`` values are :class:`~lemely.core.at_risk.AtRiskReason`
string values — later chunks assert ``GET /api/teacher/at-risk`` (or
``assess_at_risk`` directly) reproduces exactly these reasons per student, and
nothing for ``control``/``correctedPaper``.

Usage::

    python scripts/seed_e2e.py [--json-out PATH] [--run-tag TAG]

Requires the local Supabase stack up (``supabase status``) and
``lemely.toml``/env configured exactly as the real app needs (no Gemini key
required — nothing here touches Gemini). The two per-stack secrets
(``LEMELY_SUPABASE__SERVICE_ROLE_KEY``/``__ANON_KEY``) do NOT need exporting:
:func:`ensure_supabase_env` reads them from ``supabase status -o json`` when
absent, so this runs bare from any shell. An exported value still wins.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from lemely.core.at_risk import AtRiskReason
from lemely.core.history import PaperRecord
from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
    WeaknessReport,
)
from lemely.db.models.enums import Role
from lemely.web import deps

if TYPE_CHECKING:
    from lemely.auth.service import AuthResult

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for both the real seed and
# the pure unit tests that prove each scenario fires without touching
# Postgres (see tests/test_seed_e2e.py). Do not fork these.
# ---------------------------------------------------------------------------

#: Deliberately one subject for the whole module: rule 1 (declining trend)
#: reads the last 3 grade-bearing records across ALL subjects, so a second
#: subject's paper interleaved into the declining run would stop it firing.
SUBJECT_CODE = "0625"

#: (percentage, grade) pairs, oldest attempt first. Strictly decreasing with
#: a 27pp total drop — comfortably clears the 5pp floor (D3.3 rule 1).
DECLINING_SCORES: list[tuple[float, str]] = [(82.0, "A"), (68.0, "C"), (55.0, "D")]
#: Days before "now" each declining attempt was recorded, oldest first.
DECLINING_DAYS_AGO: list[int] = [6, 3, 1]

#: Improving, not declining — must never fire rule 1.
CONTROL_SCORES: list[tuple[float, str]] = [(55.0, "D"), (65.0, "C"), (78.0, "B")]
CONTROL_DAYS_AGO: list[int] = [6, 3, 1]

#: A single attempt, recorded well past the 14-day inactivity threshold.
INACTIVE_SCORE: tuple[float, str] = (75.0, "B")
INACTIVE_DAYS_AGO = 20

#: The standalone student's one corrected paper (grade/percentage surfaces).
CORRECTED_SCORE: tuple[float, str] = (88.0, "A")
CORRECTED_DAYS_AGO = 1

EMAIL_DOMAIN = "e2e.lemely.local"


# ---------------------------------------------------------------------------
# Pure helpers — no I/O, no clock of their own except an injected ``now``.
# ---------------------------------------------------------------------------


def default_run_tag() -> str:
    """A fresh 12-hex-char tag, unique enough per process run to never collide."""
    return uuid.uuid4().hex[:12]


def build_email(role_label: str, run_tag: str) -> str:
    """A deterministic, per-run-unique synthetic email for ``role_label``."""
    return f"{role_label}-{run_tag}@{EMAIL_DOMAIN}"


def build_password(run_tag: str) -> str:
    """A deterministic, per-run-unique password (not a literal secret)."""
    return f"Seed-{run_tag}-Aa1!"


def build_phone(run_tag: str) -> str:
    """Derive a per-run-unique phone number from ``run_tag``.

    Pure function of ``run_tag`` (no randomness of its own) so it is
    trivially unit-testable: every character's ordinal maps to one decimal
    digit (mod 10), giving a stable 10-digit national number behind a ``+20``
    country code — shape only, never validated by the backend (``OtpRequestDTO
    .phone`` is an unconstrained ``str``). Works for any ``run_tag`` string,
    not just the default hex tag — ``--run-tag`` accepts arbitrary text.
    """
    digits = "".join(str(ord(ch) % 10) for ch in run_tag)
    return "+20" + digits[:10].ljust(10, "0")


def declining_recorded_ats(now: datetime) -> list[datetime]:
    """Oldest-first timestamps for the declining student's 3 attempts."""
    return [now - timedelta(days=d) for d in DECLINING_DAYS_AGO]


def control_recorded_ats(now: datetime) -> list[datetime]:
    """Oldest-first timestamps for the control student's 3 attempts."""
    return [now - timedelta(days=d) for d in CONTROL_DAYS_AGO]


def inactive_recorded_at(now: datetime) -> datetime:
    """The single, >=14-day-old timestamp for the inactive student."""
    return now - timedelta(days=INACTIVE_DAYS_AGO)


def corrected_recorded_at(now: datetime) -> datetime:
    """The timestamp for the standalone corrected-paper student's attempt."""
    return now - timedelta(days=CORRECTED_DAYS_AGO)


def paper_record_for_scenario(
    student_id: str, score: tuple[float, str], recorded_at: datetime, *, paper_number: int
) -> PaperRecord:
    """Build a :class:`~lemely.core.history.PaperRecord` for the given score/date.

    Never used for persistence — only so unit tests can feed a scenario
    straight into :func:`~lemely.core.at_risk.assess_at_risk` and prove it
    fires (or doesn't) without a live Postgres, using exactly the same
    scores/dates the real seed persists via :func:`accuracy_report_for_score`.
    """
    percentage, grade = score
    return PaperRecord(
        student_id=student_id,
        metadata=_exam_metadata(paper_number),
        awarded_marks=round(percentage),
        maximum_marks=100,
        percentage=percentage,
        grade=grade,
        weak_areas=[],
        recorded_at=recorded_at.isoformat(),
        origin="past_paper",
    )


def _exam_metadata(paper_number: int) -> ExamMetadata:
    return ExamMetadata(
        subject_code=SUBJECT_CODE,
        paper_number=paper_number,
        paper_variant=1,
        session_month="May/June",
        session_year=2024,
    )


def accuracy_report_for_score(score: tuple[float, str], *, paper_number: int) -> AccuracyReport:
    """Build a minimal, valid :class:`AccuracyReport` carrying ``score``.

    One HIGH-confidence question whose marks approximate the target
    percentage, wrapped in a :class:`GradePrediction` that carries the exact
    ``(percentage, grade)`` pair — :meth:`AttemptRepository.persist_correction`
    stores ``prediction.percentage``/``prediction.grade`` verbatim onto the
    ``Attempt`` row, so this is the only pair that actually matters for
    at-risk assessment.
    """
    percentage, grade = score
    awarded = round(percentage)
    maximum = 100
    question = CorrectedQuestion(
        question_id="1",
        awarded_marks=awarded,
        maximum_marks=maximum,
        confidence=ConfidenceBand.HIGH,
        confidence_score=0.95,
        needs_teacher_review=False,
        student_answer="seeded",
        expected_answer="seeded",
        topic="Seed topic",
        marker_source="deterministic",
    )
    correction = CorrectionResult(metadata=_exam_metadata(paper_number), questions=[question])
    weaknesses = WeaknessReport(weak_areas=[])
    prediction = GradePrediction(
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=percentage,
        grade=grade,
        confidence=ConfidenceBand.HIGH,
        needs_teacher_review=False,
        boundary_source="subject_default",
    )
    return AccuracyReport(correction=correction, weaknesses=weaknesses, grade_prediction=prediction)


def build_result_payload(
    *,
    run_tag: str,
    generated_at: datetime,
    teacher: dict[str, Any],
    school_admin: dict[str, Any],
    class_row: dict[str, Any],
    students: dict[str, dict[str, Any]],
    parent: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the documented output contract from already-computed pieces.

    Pure — no I/O, so the exact JSON shape is pinned by a unit test that
    feeds fake ids/tokens and asserts the nesting, independent of ever
    touching Postgres or GoTrue.
    """
    return {
        "runTag": run_tag,
        "generatedAt": generated_at.isoformat(),
        "teacher": teacher,
        "schoolAdmin": school_admin,
        "class": class_row,
        "students": students,
        "parent": parent,
    }


# ---------------------------------------------------------------------------
# Impure orchestration — real GoTrue/Postgres I/O through lemely.web.deps'
# process-wide singletons, the exact seams the real app uses.
# ---------------------------------------------------------------------------


def _log(message: str) -> None:
    print(message, file=sys.stderr)


#: The two settings the seed needs that live only in the running stack, never
#: in ``lemely.toml`` (they are per-stack secrets). Same pair
#: ``web/scripts/audit.mjs::resolveSupabaseEnv`` resolves.
_STACK_ENV_KEYS = ("LEMELY_SUPABASE__SERVICE_ROLE_KEY", "LEMELY_SUPABASE__ANON_KEY")


def ensure_supabase_env() -> None:
    """Fill the stack's service-role/anon keys from ``supabase status`` if unset.

    Without this the script dies on the first signup with a bare
    ``AuthError: Supabase service-role key is not configured`` — which reads
    like a broken script rather than "you forgot to export two variables".
    Both harnesses already resolve these the same way
    (``web/scripts/audit.mjs::resolveSupabaseEnv``, mirroring
    ``web/playwright.config.ts``); doing it here too is what lets this be the
    *one* seeding path, runnable bare from any shell.

    An already-exported value always wins, so a caller can point the seed at a
    different stack. ``supabase`` lives at ``~/.local/bin`` and is absent from
    this sandbox's non-interactive ``PATH`` (P3.7), hence the explicit prefix.
    Must be called BEFORE the first ``deps.get_*`` call, which is what reads
    settings into the process-wide singletons.
    """
    if all(os.environ.get(key) for key in _STACK_ENV_KEYS):
        return
    search_path = f"{os.path.expanduser('~/.local/bin')}:{os.environ['PATH']}"
    binary = shutil.which("supabase", path=search_path)
    if binary is None:
        raise SystemExit(
            "`supabase` is not on PATH (checked ~/.local/bin too), so the stack keys "
            f"cannot be resolved. Export {' and '.join(_STACK_ENV_KEYS)} yourself, "
            "or install the Supabase CLI."
        )
    try:
        # S603 is suppressed deliberately: no untrusted input reaches this
        # call — `binary` is a `shutil.which` result and every argument below
        # is a literal. (Do not open this comment with the four letters ruff
        # reads as a blanket directive, or it becomes one.)
        raw = subprocess.run(  # noqa: S603
            [binary, "status", "-o", "json"],
            capture_output=True,
            check=True,
            text=True,
            env={**os.environ, "PATH": search_path},
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover - env-dependent
        raise SystemExit(
            "Could not read `supabase status -o json` to resolve the stack keys. "
            "Start the local stack (`supabase start`), or export "
            f"{' and '.join(_STACK_ENV_KEYS)} yourself."
        ) from exc
    status = json.loads(raw)
    for key, field in zip(_STACK_ENV_KEYS, ("SERVICE_ROLE_KEY", "ANON_KEY"), strict=True):
        if not os.environ.get(key):
            os.environ[key] = status[field]


def _signup_account(role_label: str, role: Role, run_tag: str) -> dict[str, Any]:
    auth_service = deps.get_auth_service()
    email = build_email(role_label, run_tag)
    password = build_password(run_tag)
    _log(f"Signing up {role.value} account: {email}")
    result: AuthResult = auth_service.signup(
        email, password, role, display_name=f"Seed {role_label.replace('-', ' ').title()}"
    )
    return {
        "userId": str(result.user_id),
        "email": email,
        "password": password,
        "displayName": f"Seed {role_label.replace('-', ' ').title()}",
        "accessToken": result.access_token,
    }


def _persist_attempts(
    student_user_id: str,
    scores: list[tuple[float, str]],
    recorded_ats: list[datetime],
) -> list[uuid.UUID]:
    attempt_repo = deps.get_attempt_repo()
    attempt_ids: list[uuid.UUID] = []
    for paper_number, (score, recorded_at) in enumerate(
        zip(scores, recorded_ats, strict=True), start=1
    ):
        report = accuracy_report_for_score(score, paper_number=paper_number)
        attempt_id = attempt_repo.persist_correction(
            user_id=student_user_id,
            report=report,
            recorded_at=recorded_at.isoformat(),
        )
        attempt_ids.append(attempt_id)
    return attempt_ids


def seed(*, run_tag: str | None = None) -> dict[str, Any]:
    """Seed the live stack end to end and return the output-contract payload.

    Requires a reachable local Supabase stack (GoTrue + Postgres) configured
    exactly as ``lemely.web.deps`` expects it for the real app.
    """
    run_tag = run_tag or default_run_tag()
    now = datetime.now(UTC)
    _log(f"Seeding run {run_tag} at {now.isoformat()}")

    class_service = deps.get_class_service()
    parent_link_service = deps.get_parent_link_service()
    auth_service = deps.get_auth_service()

    teacher = _signup_account("teacher", Role.teacher, run_tag)
    school_admin = _signup_account("admin", Role.school_admin, run_tag)

    declining = _signup_account("declining", Role.student, run_tag)
    inactive = _signup_account("inactive", Role.student, run_tag)
    control = _signup_account("control", Role.student, run_tag)
    corrected = _signup_account("corrected", Role.student, run_tag)

    _log("Creating class and enrolling the at-risk roster")
    class_row = class_service.create_class(
        uuid.UUID(teacher["userId"]), f"P3.10 Seed Class {run_tag}"
    )
    assert class_row.join_code is not None  # noqa: S101 - always generated, see create_class
    for student in (declining, inactive, control):
        class_service.join_by_code(uuid.UUID(student["userId"]), class_row.join_code)

    _log("Persisting the declining-trend run (single subject, 3 papers)")
    _persist_attempts(declining["userId"], DECLINING_SCORES, declining_recorded_ats(now))

    _log("Persisting the >=14-day-inactive attempt")
    _persist_attempts(inactive["userId"], [INACTIVE_SCORE], [inactive_recorded_at(now)])

    _log("Persisting the healthy control's improving run")
    _persist_attempts(control["userId"], CONTROL_SCORES, control_recorded_ats(now))

    _log("Persisting the standalone corrected paper")
    corrected_attempt_ids = _persist_attempts(
        corrected["userId"], [CORRECTED_SCORE], [corrected_recorded_at(now)]
    )

    parent_phone = build_phone(run_tag)
    _log(f"Requesting one OTP challenge for parent phone {parent_phone}")
    dev_code = auth_service.request_otp(parent_phone)
    if dev_code is None:
        raise RuntimeError(
            "AuthService.request_otp returned no code — the configured SMS provider "
            "delivers out of band, so this script cannot recover it to verify."
        )
    parent_result = auth_service.verify_otp(parent_phone, dev_code)
    _log(f"Linking parent {parent_result.user_id} to the declining student")
    parent_link_service.link(student_id=uuid.UUID(declining["userId"]), phone=parent_phone)

    students = {
        "declining": {
            **declining,
            "expectedAtRiskReasons": [AtRiskReason.DECLINING_TREND.value],
        },
        "inactive": {
            **inactive,
            "expectedAtRiskReasons": [AtRiskReason.INACTIVE.value],
        },
        "control": {
            **control,
            "expectedAtRiskReasons": [],
        },
        "correctedPaper": {
            **corrected,
            "expectedAtRiskReasons": [],
            "correctedPaperId": str(corrected_attempt_ids[0]),
        },
    }
    parent = {
        "userId": str(parent_result.user_id),
        "phone": parent_phone,
        "accessToken": parent_result.access_token,
        "linkedStudent": "declining",
    }
    class_dict = {
        "classId": str(class_row.class_id),
        "name": class_row.name,
        "joinCode": class_row.join_code,
    }

    _log("Seeding complete")
    return build_result_payload(
        run_tag=run_tag,
        generated_at=now,
        teacher=teacher,
        school_admin=school_admin,
        class_row=class_dict,
        students=students,
        parent=parent,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: seed the stack, print JSON to stdout (only)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-out", type=str, default=None, help="Also write the JSON payload to this path."
    )
    parser.add_argument(
        "--run-tag",
        type=str,
        default=None,
        help="Override the per-run unique tag (default: random 12 hex chars).",
    )
    args = parser.parse_args(argv)

    ensure_supabase_env()
    payload = seed(run_tag=args.run_tag)
    rendered = json.dumps(payload, indent=2)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(rendered)
        _log(f"Wrote JSON payload to {args.json_out}")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
