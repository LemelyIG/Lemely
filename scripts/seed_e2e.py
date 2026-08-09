#!/usr/bin/env python3
"""Shared multi-role seed fixture for E2E/audit harnesses (P3.10 chunks a/e1).

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
* (P3.10 chunk e1) a **review-queue item** (T-08): the ``inactive`` student's
  own single attempt is persisted deliberately LOW-confidence instead of
  HIGH — same score/date/subject as always, so at-risk rule 2 and every
  Playwright-pinned roster number are untouched — which makes
  :meth:`~lemely.db.attempt_repo.AttemptRepository._persist`'s real fan-out
  queue it for review, through the same single writer every attempt in this
  script goes through. Never a hand-inserted ``review_queue`` row.
* (P3.10 chunk e1) a **quiz** (T-09/T-10): 5 MCQ ``question_bank`` rows
  (:func:`build_quiz_bank_questions`, D3.7's empty-bank workaround), built
  into a quiz, assigned to the seeded class, and submitted — every answer
  deliberately wrong (:func:`wrong_mcq_answer`; see its docstring for the
  plagiarism-false-positive defect this sidesteps) — by the ``control``
  student, then marked through :class:`~lemely.db.quiz_marking_repo.QuizMarkingService`'s
  real, unmodified path. All-MCQ means :func:`~lemely.core.correction.correct_paper`
  takes its deterministic branch and never touches Gemini — see "Zero Gemini
  calls" below.
* (P3.10 chunk e1) two **genuinely empty** accounts for the ``empty``-state
  screenshot captures: a second teacher with no classes at all, and a second
  parent (its own OTP challenge, on a phone namespaced to avoid the linked
  parent's own 30s cooldown — see :func:`build_empty_parent_phone`) never
  linked to any child.

Every scenario/corrected-paper attempt is persisted as ``origin=past_paper``
(D3.9): every grade/percentage/paper claim in this codebase filters on
grade-bearing origin, so a quiz attempt would silently fail to back any of
these scenarios. The seeded quiz submission is the one deliberate exception —
it is ``origin=quiz`` by construction (via ``persist_quiz_correction``) and is
excluded from those same claims, which is exactly why it is attached to the
``control`` student rather than a new roster entry: it cannot change a single
number ``teacher-journey.spec.ts`` already pins (3 students, 69% average
mark, 2 at-risk).

**Zero Gemini calls, by construction.** Every seeded question is MCQ, so
:func:`~lemely.core.correction.correct_paper` never builds an ``AICorrector``
call, and the default :class:`~lemely.runtime.config.IntegritySettings`
(``ai_detection_enabled=False``) means ``apply_integrity_checks`` never
constructs an ``AIContentDetector`` either — the Gemini client's lazy
``_client`` property is never touched, so no API key is required and no
request reaches the network. Verified against the live stack's real cost
ledger before/after a seed run, not merely asserted (see the P3.10 chunk e1
report).

Idempotent-friendly: every email and the parent phone number are namespaced
under a per-run ``runTag`` (default: 12 random hex chars), so repeated runs
never collide. Reruns do not delete previous runs' rows — there is no
teardown here, by design (this is a seed script, not a fixture cleaner).

The OTP resend cooldown (``otp_min_resend_seconds``, default 30s) is
per-phone. This script requests exactly one challenge per phone (the linked
parent's, and separately the empty parent's — see
:func:`build_empty_parent_phone`) and returns the access token that verifying
it already produced — a consumer (Playwright, ``audit.mjs``) must reuse that
token rather than starting a second OTP challenge for the same phone, or it
will hit the cooldown.

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
                 "linkedStudent": "declining"},
      "reviewItem": {"itemId": "<review_queue.id>", "attemptId": "<attempt uuid>",
                     "studentKey": "inactive"},
      "quiz": {"quizId": "...", "assignmentId": "...", "submissionId": "...",
               "submittedBy": "control", "status": "marked"},
      "emptyTeacher": {"userId": "...", "email": "...", "password": "...",
                        "displayName": "...", "accessToken": "..."},
      "emptyParent": {"userId": "...", "phone": "+20...", "accessToken": "..."},
      "placement": {
        "subjectCode": "0625",
        "paperNumber": 2,
        "bankQuestionCount": 24,
        "students": {
          "unonboarded": {"userId": "...", "email": "...", "password": "...",
                          "displayName": "...", "accessToken": "..."},
          "available":   {..., },
          "inProgress":  {..., "quizId": "...", "assignmentId": "...",
                          "questionCount": 7},
          "completed":   {..., "quizId": "...", "assignmentId": "...",
                          "submissionId": "...", "awardedMarks": 12,
                          "maximumMarks": 14}
        }
      },
      "practice": {
        "subjectCode": "0625",
        "students": {
          "active":  {..., "unsubmittedAssignmentId": "...",
                      "markingAssignmentId": "...", "markedAssignmentId": "...",
                      "deckId": "..."},
          "settled": {..., "deckId": "..."},
          "bare":    {...}
        }
      },
      "studyPlan": {
        "subjectCode": "0625",
        "activeSessionId": "...", "activeSessionTopic": "1.2 Motion",
        "activeSessionCount": 3, "completedSessionCount": 3
      }
    }

The four S-24/S-25 states are carried by accounts documented above rather than
by ``studyPlan`` keys: ``practice.students.active`` holds the populated week,
``practice.students.settled`` the persisted ``no_signal`` refusal,
``practice.students.bare`` the ungenerated week, and
``placement.students.completed`` the fully-completed one.
``activeSessionId`` exists because S-25's route needs a real session id and no
other key carries one.

``expectedAtRiskReasons`` values are :class:`~lemely.core.at_risk.AtRiskReason`
string values — later chunks assert ``GET /api/teacher/at-risk`` (or
``assess_at_risk`` directly) reproduces exactly these reasons per student, and
nothing for ``control``/``correctedPaper``.

``reviewItem``/``quiz``/``emptyTeacher``/``emptyParent`` (P3.10 chunk e1) are
purely additive — every key documented above them is unchanged since chunk a.
``quiz.status`` is ``"marked"`` on a successful run; see :func:`seed`'s
marking-failure branch for the (not expected, never faked) alternative.

``placement`` (P4.8 chunk C) is additive on top of those. Its four student
accounts are deliberately distinct (never one account reused across states)
because :meth:`~lemely.db.placement_repo.PlacementService.availability`
excludes a student's own prior placement questions for the same subject
(D4.6 §4) — reusing one would report the pool exhausted on the very screen
meant to show it available:

* ``unonboarded`` — signed up, no profile, no enrolment: S-01/S-02's genuine
  first-run state.
* ``available`` — onboarded and enrolled in 0625, no placement taken yet:
  S-03 renders ``available``. Calling
  ``PlacementService.availability(userId, "0580")`` or ``"0606"`` for this
  (or any placement) account still returns ``no_questions`` — those subjects
  have zero ingested questions, an honest refusal this seed does not paper
  over.
* ``inProgress`` — a placement created (``PlacementService.create``) but
  never submitted: S-04 has a real ``assignmentId`` with zero submitted
  answers.
* ``completed`` — a placement created, taken (first answer deliberately
  wrong so a real ``WeaknessRecord`` exists), submitted, and marked through
  the unmodified quiz-taking/marking repos: S-05 has a real
  ``awardedMarks``/``maximumMarks`` produced by the marking engine, never a
  hand-inserted mark.

All three onboarded accounts have their ``student_enrolment_papers`` pinned to
0625 **Paper 2**, which is what keeps the assembled placement drawn purely from
this seed's own 24 synthetic MCQ rows. That is load-bearing, not cosmetic: it
is what makes the run deterministic, keeps every question on the deterministic
MCQ marking path, and holds this script's Gemini spend at **$0.00**. See
:data:`PLACEMENT_PAPER_NUMBER` for the measured failure it fixes, and
:func:`placement_answer_key` for the per-run guard that re-checks it instead of
assuming it.

The ``questionCount``/``awardedMarks``/``maximumMarks`` figures shown above are
the measured result of a real run against the live stack (7 questions x 2 marks,
one deliberate mistake), not a target. Placement assembles **7** questions here
rather than the 9-10 the real 0625 corpus yields because Paper 2's transcribed
rate (45 min / 40 marks) is slower per mark than Paper 4's (75 / 80), so the
same ~15-minute target buys fewer 2-mark questions. That is above
``lemely.core.placement.MIN_QUESTIONS`` and spans all four
:data:`PLACEMENT_TOPICS`; a change that drops it below the floor should be
treated as a regression in this seed, not as a new baseline to write down.

``practice`` (P4.9 chunk C) is additive on top of all of the above, backing
S-20/S-21 (practice) and S-22/S-23 (flashcards). Unlike ``placement`` it
needs no new bank — it draws from the exact same hermetic 0625 Paper 2 pool
:data:`PLACEMENT_PAPER_NUMBER` already seeded. Three accounts, not four,
because the trap here is different from placement's: a student with
recorded weaknesses cannot also demonstrate the honest ``no_weaknesses``
refusal, and a student with cards due today cannot also demonstrate
flashcards' "nothing due today" — so no account wears two hats:

* ``active`` — onboarded, enrolled in 0625 (papers pinned to
  :data:`PLACEMENT_PAPER_NUMBER`), with three practice sets covering S-21's
  three submission states plus one manual flashcard deck due now:

  - a **marked** set (one deliberately wrong answer, then submitted and
    marked through the unmodified quiz-taking/marking repos) — S-21's
    ``marked`` capture, and the same trick :data:`PLACEMENT_MCQ_ANSWER`'s
    placement ``completed`` account uses to produce a real
    ``WeaknessRecord``, which is what S-20's weak-topic prefill needs.
  - an **unsubmitted** set (created, never touched) — S-21's working view
    and its ``not_submitted`` result.
  - a **submitted-but-unmarked** set (answered and submitted, but
    :meth:`~lemely.db.quiz_marking_repo.QuizMarkingService.mark_submission`
    deliberately never called) — S-21's ``marking`` state. Seedable at all
    only because :meth:`~lemely.db.quiz_taking_repo.QuizTakingService.submit`
    does not mark; the real HTTP route marks on a background thread, which
    is a race this direct service call sidesteps.
* ``settled`` — onboarded, enrolled in 0625, one manual deck whose every
  card has been reviewed :attr:`~lemely.db.models.flashcards.ReviewGrade.good`
  through :meth:`~lemely.db.flashcard_repo.FlashcardService.record_review` —
  a real SM-2 scheduler outcome that pushes ``due_at`` into the future,
  never a hand-written date. :func:`seed` asserts
  :meth:`~lemely.db.flashcard_repo.FlashcardService.due_session` reports zero
  due and a real ``next_due_at`` immediately afterward. S-22/S-23's "nothing
  due today".
* ``bare`` — onboarded, enrolled in 0625, and nothing else: no weakness
  rows, no decks. S-20's honest ``no_weaknesses`` refusal, S-22's genuinely
  empty deck list, and S-22's weakness-generate 409 (free — ``generate_deck``
  resolves the topic, and raises, before ever calling the generator).

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

from sqlalchemy import delete as sa_delete

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
from lemely.db.models.enums import (
    DifficultySource,
    QuestionSource,
    QuizQuestionStatus,
    Role,
)
from lemely.db.models.flashcards import DeckOrigin, ReviewGrade
from lemely.db.models.quizzes import QuestionBank
from lemely.db.practice_repo import PracticeRequest
from lemely.db.question_bank_repo import NewBankQuestion
from lemely.db.session import get_sessionmaker
from lemely.web import deps

if TYPE_CHECKING:
    from lemely.auth.service import AuthResult
    from lemely.core.difficulty import Band

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
# P3.10 chunk e1 additions: a review-queue item (T-08), a quiz + assignment +
# marked submission (T-09/T-10), and two genuinely-empty accounts. See this
# module's docstring for the full contract these additions extend.
# ---------------------------------------------------------------------------

#: Below `lemely.core.schemas.REVIEW_CONFIDENCE_THRESHOLD` (0.90) — the ONE
#: thing that makes `AttemptRepository._persist`'s real fan-out queue this
#: question for review (`qr.confidence_score < REVIEW_CONFIDENCE_THRESHOLD`),
#: never a hand-inserted `review_queue` row. Deliberately reused on the
#: `inactive` student's own single attempt (same score/date/subject as
#: `INACTIVE_SCORE`/`inactive_recorded_at`) rather than a new attempt or a new
#: student: `assess_at_risk` never reads confidence at all, so this cannot
#: change `expectedAtRiskReasons`, and the Playwright suite's hardcoded roster
#: numbers (teacher-journey.spec.ts: 3 students, 69% average, 2 at-risk) never
#: see a 4th enrolled student or a 4th grade-bearing attempt.
REVIEW_ITEM_CONFIDENCE_SCORE = 0.55

#: `allocate_difficulty(None, 5)` (`lemely.core.difficulty`) for an untargeted
#: quiz, worked out by hand: the balanced (0.2, 0.6, 0.2) mix * 5 questions =
#: (1.0, 3.0, 1.0) exactly, no remainder to break a tie over. If either of
#: these two constants changes, re-derive the allocation by hand again —
#: `generate_questions` treats a supply/allocation mismatch as an honest
#: shortfall, not an error, so a drift here would silently materialize fewer
#: than 5 questions rather than raising.
QUIZ_REQUESTED_COUNT = 5
QUIZ_BANK_BANDS: list[Band] = ["foundation", "standard", "standard", "standard", "challenge"]
#: One MCQ answer letter per bank row above, distinct only so a human
#: skimming the seeded bank can tell the rows apart — never read by the
#: allocator or the marker.
QUIZ_BANK_ANSWERS: list[str] = ["A", "B", "C", "D", "A"]

_MCQ_LETTERS: tuple[str, ...] = ("A", "B", "C", "D")


# ---------------------------------------------------------------------------
# P4.8 chunk C additions: a placement-eligible 0625 past-paper bank, plus four
# distinct student accounts covering S-01..S-05's real, un-faked states. See
# this module's docstring for the full contract these additions extend.
#
# **The trap this whole section exists to avoid (D4.6 §4):**
# ``PlacementService.availability`` excludes a student's OWN prior placement
# questions for the same subject from the eligible pool. Reusing one student
# for both "invite available" and "already completed a 0625 placement" would
# report the pool exhausted (``no_eligible_questions``) on the invite screen
# instead of ``available`` — so this seed uses four distinct student accounts,
# one per S-01..S-05 state, never one account wearing two hats.
# ---------------------------------------------------------------------------

#: Same subject as the at-risk roster (:data:`SUBJECT_CODE`) — reused rather
#: than restated, since both need a bank that already has a bundled syllabus
#: taxonomy (:mod:`lemely.io.syllabus_topics`) and a transcribed paper timing
#: entry (:mod:`lemely.io.paper_timing`).
PLACEMENT_SUBJECT_CODE = SUBJECT_CODE

#: 0625's real top-level syllabus labels (``lemely/data/syllabus_topics.json``),
#: the exact "<code> <name>" vocabulary D4.2's classifier writes — copied from
#: ``tests/test_placement_repo.py``'s viable-0625-bank fixture (its
#: ``_PHYSICS_TOPICS``) rather than invented, per this chunk's brief.
PLACEMENT_TOPICS: list[str] = [
    "1 Motion, forces and energy",
    "2 Thermal physics",
    "3 Waves",
    "4 Electricity and magnetism",
]

#: 0625 Paper 2 (Multiple Choice, Extended) — a real, non-practical paper
#: carried in ``lemely/data/paper_timing.json`` (45 min / 40 marks; Papers 5/6
#: are practical and excluded from placement by
#: :func:`~lemely.io.paper_timing.get_paper_timings`'s default).
#:
#: **Paper 2 is chosen to make this seed hermetic, and that is the whole
#: point — do not "restore" it to Paper 4.** An earlier revision used Paper 4
#: (copying ``tests/test_placement_repo.py``'s fixture) and was measured
#: against the live stack: the assembled placement drew **5 of its 8 questions
#: from the real ingested 0625 corpus**, not from this seed at all, because
#: ``PlacementService._load_candidates`` selects every ``source='past_paper'``
#: row for the subject and this dev database also holds P4.1's 273 real ones.
#: Two concrete failures followed, both invisible to the suite:
#:
#: 1. Three drawn questions were **theory** questions with no ``mcq_answer``,
#:    so marking routed them to the AI marker — **a live, billed Gemini call
#:    on every single seed run** (~$0.014 measured, against the hard $8 cap),
#:    and a hard dependency on a network and an API key in what must be an
#:    offline-reproducible seeding step.
#: 2. The uniform :data:`PLACEMENT_MCQ_ANSWER` was simply wrong for the drawn
#:    corpus questions, so the "one deliberate mistake" student scored
#:    **6/16 instead of the documented 14/16** and S-05 would have
#:    screenshotted a near-fail baseline built out of noise, with a weakness
#:    profile spread across topics the seed never intended to fail.
#:
#: Paper 2 has **zero** rows in the real corpus (measured: the ingested 0625
#: papers are 1, 3, 4, 5 and 6), so pinning both this bank and the seeded
#: students' ``student_enrolment_papers`` to Paper 2 narrows the eligible pool
#: to exactly this seed's own MCQ rows. Deterministic, all-MCQ, **$0.00**.
#: :func:`seed` additionally *verifies* that hermeticity per run rather than
#: trusting it — see the assembled-pool guard there, which fails loudly the
#: day someone ingests real Paper 2 questions.
PLACEMENT_PAPER_NUMBER = 2
PLACEMENT_PAPER_NUMBER_VARIANT = "21"


def build_placement_paper_stem(run_tag: str) -> str:
    """A per-run CAIE-shaped question-paper filename stem for 0625 Paper 2.

    Feeding this stem through ``source_question_id`` is what lets
    :meth:`~lemely.db.question_bank_repo.QuestionBankService.link_past_paper_rows`
    create the real ``Paper``/``Subject`` rows the placement loader joins
    against — never a hand-inserted ``papers`` row.

    **Why this is a function of ``run_tag`` rather than a constant.** A *fixed*
    stem would put every run's rows on one ``papers`` row; hashing ``run_tag``
    into the session-year digits (mirrors :func:`build_phone`'s per-character
    hashing) usually mints a distinct one per run. The resulting year is
    filename shape only, never a claim about a real CAIE sitting — see
    :func:`build_placement_bank_questions` for why the question text itself is
    honestly synthetic regardless.

    **This function is NOT what makes a rerun safe, and an earlier version of
    this docstring wrongly claimed it was.** It reads only ``run_tag``'s first
    two characters, so the year has a 100-value namespace: by the birthday
    bound two runs land on the same ``papers`` row roughly every dozen runs,
    and then their identical ``#1..#24`` suffixes trip
    ``uq_question_bank_paper_question (paper_id, source_question_id)`` on the
    second run's ``link_past_paper_rows()``. That is not hypothetical — it
    fired for real on ``0625_s88_qp_21#12`` after a day of repeated gate runs,
    failing ``playwright-e2e``. Uniqueness now lives in the
    ``source_question_id`` **suffix**, which carries the whole 12-character
    tag; see :func:`build_placement_bank_questions`. Sharing a ``papers`` row
    across runs is harmless once the suffixes differ.
    """
    digits = "".join(str(ord(ch) % 10) for ch in run_tag)
    year = (digits[:2] or "00").ljust(2, "0")
    return f"0625_s{year}_qp_{PLACEMENT_PAPER_NUMBER_VARIANT}"


#: One 2-mark MCQ per (topic, index) pair, 4 topics x 6 = 24 rows — the exact
#: per-topic count ``tests/test_placement_repo.py``'s
#: ``test_availability_true_for_a_viable_0625_bank`` already proves clears
#: ``assemble``'s 6-question/4-topic floor. Copied rather than re-derived
#: (this chunk's brief).
PLACEMENT_QUESTIONS_PER_TOPIC = 6
PLACEMENT_QUESTION_MARKS = 2
#: Every seeded placement question's correct MCQ answer — uniform, like
#: :func:`build_quiz_bank_questions`' quiz bank, so :func:`wrong_mcq_answer`
#: can produce a deliberately-wrong first answer for the "completed" student
#: (see its use in :func:`seed`) without per-row bookkeeping.
#:
#: Uniformity is only safe *because* :data:`PLACEMENT_PAPER_NUMBER` makes the
#: assembled pool hermetic. :func:`seed` never relies on that assumption
#: blind: it resolves each served question's expected answer through
#: :func:`placement_answer_key` and refuses to answer a question this seed
#: did not author.
PLACEMENT_MCQ_ANSWER = "B"

#: Embedded verbatim in every seeded placement prompt, and the thing
#: :func:`is_placement_seed_prompt` recognises. It does double duty: it is the
#: honesty label a human reading the bank sees (this text is not real CAIE
#: content), and it is the machine-checkable marker that separates this seed's
#: rows from the real ingested corpus.
PLACEMENT_PROMPT_MARKER = "P4.8 chunk C fixture text — not real CAIE content"


# ---------------------------------------------------------------------------
# P4.9 chunk C additions: three student accounts for S-20/S-21 (practice) and
# S-22/S-23 (flashcards). No new bank — these accounts draw from the same
# hermetic 0625 Paper 2 pool PLACEMENT_PAPER_NUMBER already seeds. See this
# module's docstring for the full contract these additions extend.
# ---------------------------------------------------------------------------

#: How many questions each of ``practice-active``'s three sets requests —
#: comfortably inside the hermetic 24-row Paper 2 bank (6 rows/topic x 4
#: topics), so ``PracticeService.create`` never reports ``insufficient_pool``
#: for a set *this seed* builds. That reason IS deliberately exercised — but
#: through S-20's own live preview query at its frontend default count,
#: against the single weak topic set A's own marking narrows the pool to,
#: never through what this script requests here.
PRACTICE_SET_COUNT = 6


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


def accuracy_report_for_score(
    score: tuple[float, str],
    *,
    paper_number: int,
    confidence: ConfidenceBand = ConfidenceBand.HIGH,
    confidence_score: float = 0.95,
    needs_teacher_review: bool = False,
) -> AccuracyReport:
    """Build a minimal, valid :class:`AccuracyReport` carrying ``score``.

    One question whose marks approximate the target percentage, wrapped in a
    :class:`GradePrediction` that carries the exact ``(percentage, grade)``
    pair — :meth:`AttemptRepository.persist_correction` stores
    ``prediction.percentage``/``prediction.grade`` verbatim onto the
    ``Attempt`` row, so this is the only pair that actually matters for
    at-risk assessment.

    ``confidence``/``confidence_score``/``needs_teacher_review`` default to
    the HIGH-confidence, review-suppressing shape every original scenario
    attempt needs (a seed attempt must never accidentally land in the review
    queue — see ``TestAccuracyReportForScore.test_never_needs_teacher_review``).
    P3.10 chunk e1 overrides them exactly once, for the ``inactive`` student's
    own attempt, to produce T-08's one *genuine* low-confidence review-queue
    row through :class:`~lemely.db.attempt_repo.AttemptRepository`'s real
    fan-out (never a hand-inserted ``review_queue`` row) — see
    ``REVIEW_ITEM_CONFIDENCE_SCORE``'s docstring for why the score/date/subject
    stay untouched.
    """
    percentage, grade = score
    awarded = round(percentage)
    maximum = 100
    question = CorrectedQuestion(
        question_id="1",
        awarded_marks=awarded,
        maximum_marks=maximum,
        confidence=confidence,
        confidence_score=confidence_score,
        needs_teacher_review=needs_teacher_review,
        review_reason=(
            f"confidence {confidence_score:.2f} below review threshold"
            if needs_teacher_review
            else None
        ),
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
        confidence=confidence,
        needs_teacher_review=needs_teacher_review,
        boundary_source="subject_default",
    )
    return AccuracyReport(correction=correction, weaknesses=weaknesses, grade_prediction=prediction)


def build_empty_parent_phone(run_tag: str) -> str:
    """A second, distinct phone for the genuinely-empty parent account.

    **The trap this avoids:** :func:`build_phone` only reads a string's
    *first 10 characters* (then pads/truncates to a national number). The
    default ``run_tag`` is a 12-hex-char string, so a same-tag *suffix*
    (``f"{run_tag}-empty"``) would leave those first 10 characters completely
    unchanged and produce a phone number IDENTICAL to :func:`build_phone`'s —
    silently colliding with the linked parent's own number and tripping the
    30s per-phone OTP resend cooldown (module docstring) on this run's second
    :meth:`~lemely.auth.service.AuthService.request_otp` call. Prefixing
    instead of suffixing changes the leading characters and sidesteps this
    for any ``run_tag`` (default or custom, any length).
    """
    return build_phone(f"empty-{run_tag}")


def build_quiz_bank_questions(teacher_id: uuid.UUID) -> list[NewBankQuestion]:
    """The quiz's ``question_bank`` rows: generated/teacher-authored, ``paper_id=None``.

    D3.7's empty-bank trap: mark schemes carry marking points but no question
    stems, and no stem extractor exists, so ``POST /questions/generate`` has
    nothing to draw from for this seed. Seeding ``question_bank`` rows
    directly (through :meth:`~lemely.db.question_bank_repo.QuestionBankService.add_questions`
    — never a raw INSERT) is the intended path for exactly this reason: these
    rows carry no ``paper_id``, which the partial unique index
    ``uq_question_bank_paper_question`` deliberately does not cover.

    ``owner_id=teacher_id`` is what makes these rows visible to
    :meth:`~lemely.db.question_bank_repo.QuestionBankService.select_questions`
    for exactly this seed run's teacher (``question_bank_repo.visible_bank_filter``)
    — never the platform-shared pool, so one run's rows can never be selected
    into another run's quiz.

    One row per ``(band, answer)`` pair in ``QUIZ_BANK_BANDS``/``QUIZ_BANK_ANSWERS``
    — exactly the ``{foundation: 1, standard: 3, challenge: 1}`` supply
    ``QUIZ_REQUESTED_COUNT``'s allocation needs (see that constant's
    docstring); every row is MCQ so :func:`~lemely.core.correction.correct_paper`
    takes its deterministic path and never touches Gemini (module docstring's
    hard cost constraint).
    """
    return [
        NewBankQuestion(
            subject_code=SUBJECT_CODE,
            source=QuestionSource.generated,
            difficulty=band,
            difficulty_source=DifficultySource.declared_by_generator,
            question_type="mcq",
            prompt=f"Seed MCQ question {i + 1} ({band})",
            total_marks=1,
            owner_id=teacher_id,
            topic="Seed quiz topic",
            mark_scheme_points=[],
            mcq_options=["Option A", "Option B", "Option C", "Option D"],
            mcq_answer=answer,
            created_by=teacher_id,
        )
        for i, (band, answer) in enumerate(zip(QUIZ_BANK_BANDS, QUIZ_BANK_ANSWERS, strict=True))
    ]


def wrong_mcq_answer(correct: str) -> str:
    """Any MCQ letter other than ``correct`` — deterministic, first mismatch in ``ABCD``.

    Used to build the seeded quiz submission's answers. **Deliberately never
    correct:** a *correct* MCQ answer's ``student_answer`` is, by
    construction, character-identical to the mark scheme's
    ``expected_answer`` (both are the same one-letter string) —
    ``lemely.io.integrity.apply_integrity_checks``'s plagiarism check (on by
    default, ``IntegritySettings.plagiarism_enabled``) runs
    ``difflib.SequenceMatcher.ratio()`` over exactly that pair and scores an
    identical string 1.0, comfortably over its 0.85 threshold — so every
    correctly-answered MCQ question in every quiz submission is, today, a
    false-positive plagiarism flag (verified directly against
    ``PlagiarismChecker`` — a real defect, not a seed artifact; see the P3.10
    chunk e1 report). Answering every question wrong sidesteps it: this seed
    must not paper over a defect with a hand-picked "safe" score, and must not
    trip it either, so the submission is a genuine (if unflattering) 0/N —
    still `QuizMarkingService.mark_submission`'s real, unmodified path.
    """
    for letter in _MCQ_LETTERS:
        if letter != correct:
            return letter
    raise AssertionError("unreachable: _MCQ_LETTERS always has an alternative")


def build_placement_bank_questions(run_tag: str) -> list[NewBankQuestion]:
    """Synthetic ``source=past_paper`` 0625 rows placement can actually assemble from.

    **Honestly synthetic** (P4.8 chunk C's hard constraint): the prompts below
    are seed fixture text, never real CAIE past-paper content — every prompt
    says so plainly. What *is* real: the topic labels
    (:data:`PLACEMENT_TOPICS`, verified against the bundled syllabus
    taxonomy), the paper this bank links to (:data:`PLACEMENT_PAPER_STEM` ->
    Paper 4, Theory Extended, 75 min / 80 marks — the transcribed rate D4.8
    calls "the measurement that stands"), and the resulting assembly
    behaviour (:func:`~lemely.core.placement.assemble` is exercised for real,
    never stubbed).

    ``paper_id`` is left ``None`` here, exactly like the P4.1 past-paper
    importer's own rows — :func:`seed` calls
    :meth:`~lemely.db.question_bank_repo.QuestionBankService.link_past_paper_rows`
    immediately after inserting these, which is the one real path that
    resolves ``source_question_id`` into a ``Paper``/``Subject`` row pair
    (never a hand-inserted one).

    No prompt here matches
    :data:`~lemely.db.question_bank_repo._FIGURE_DEPENDENT_PATTERN` (no
    "diagram"/"figure ... shows"), so none is dropped by chunk 0's
    :func:`~lemely.db.question_bank_repo.renderable_bank_filter` — the point
    of this seed is a placement test that actually assembles, not one that
    silently loses rows to the same filter it exists to prove works.
    """
    stem = build_placement_paper_stem(run_tag)
    rows: list[NewBankQuestion] = []
    ref = 1
    for topic in PLACEMENT_TOPICS:
        for _ in range(PLACEMENT_QUESTIONS_PER_TOPIC):
            rows.append(
                NewBankQuestion(
                    subject_code=PLACEMENT_SUBJECT_CODE,
                    source=QuestionSource.past_paper,
                    difficulty="standard",
                    difficulty_source=DifficultySource.inferred_from_marks,
                    question_type="mcq",
                    prompt=(
                        f"Synthetic placement seed item {ref} for topic {topic!r} "
                        f"({PLACEMENT_PROMPT_MARKER})."
                    ),
                    total_marks=PLACEMENT_QUESTION_MARKS,
                    topic=topic,
                    # The `#` suffix carries the FULL run_tag, and that is what
                    # actually makes a rerun safe. `build_placement_paper_stem`
                    # hashes only the tag's first two characters into the
                    # session-year digits, so it has a 100-value namespace — two
                    # runs collide on the same `papers` row roughly every dozen
                    # runs (birthday bound), which is exactly what happened here
                    # after a day of repeated gate runs: a real
                    # `uq_question_bank_paper_question` IntegrityError on
                    # `0625_s88_qp_21#12`. `_paper_identity` splits on the first
                    # `#` and parses only the stem, so the suffix is opaque to
                    # the linker and free to carry all 12 hex characters.
                    source_question_id=f"{stem}#{run_tag}-{ref}",
                    mcq_options=["A", "B", "C", "D"],
                    mcq_answer=PLACEMENT_MCQ_ANSWER,
                )
            )
            ref += 1
    return rows


def is_placement_seed_prompt(prompt: str) -> bool:
    """Was this question authored by :func:`build_placement_bank_questions`?

    Pure, and deliberately keyed on ``prompt``: that is the only identifying
    field of a question which reaches the student-facing take payload —
    :class:`~lemely.db.quiz_taking_repo.QuizTakeQuestionRow` has no
    ``mcq_answer`` field at all, so a seed script cannot (and must not) ask the
    take endpoint what the right answer is. Recognising our own prompt keeps
    the answer flowing from this module's own data rather than from a
    privileged read-back.

    **Matches any run's rows, not just the current one, and that is correct.**
    Prompts carry no run tag. Since P4.9 chunk C :func:`seed` purges earlier
    runs' fixture rows before seeding its own, so in practice only one run's
    rows are ever in the bank — but this staying run-agnostic is still the
    right shape, because every seeded row shares :data:`PLACEMENT_MCQ_ANSWER`
    and a prompt-exact match would couple this guard to that purge holding.
    The failure worth catching is a **real corpus** question, whose
    prompt carries no such marker; :func:`seed` treats that as a hard error
    rather than guessing, because it is exactly what previously spent live
    Gemini budget and produced a meaningless S-05 baseline.
    """
    return PLACEMENT_PROMPT_MARKER in prompt


def build_result_payload(
    *,
    run_tag: str,
    generated_at: datetime,
    teacher: dict[str, Any],
    school_admin: dict[str, Any],
    class_row: dict[str, Any],
    students: dict[str, dict[str, Any]],
    parent: dict[str, Any],
    review_item: dict[str, Any],
    quiz: dict[str, Any],
    empty_teacher: dict[str, Any],
    empty_parent: dict[str, Any],
    placement: dict[str, Any],
    practice: dict[str, Any],
    study_plan: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the documented output contract from already-computed pieces.

    Pure — no I/O, so the exact JSON shape is pinned by a unit test that
    feeds fake ids/tokens and asserts the nesting, independent of ever
    touching Postgres or GoTrue. ``reviewItem``/``quiz``/``emptyTeacher``/
    ``emptyParent`` are additive (P3.10 chunk e1); ``placement`` is additive
    on top of those (P4.8 chunk C); ``practice`` is additive on top of all of
    it (P4.9 chunk C); ``studyPlan`` is additive on top of that (P4.10 chunk C)
    — every key present before it is unchanged.
    """
    return {
        "runTag": run_tag,
        "generatedAt": generated_at.isoformat(),
        "teacher": teacher,
        "schoolAdmin": school_admin,
        "class": class_row,
        "students": students,
        "parent": parent,
        "reviewItem": review_item,
        "quiz": quiz,
        "emptyTeacher": empty_teacher,
        "emptyParent": empty_parent,
        "placement": placement,
        "practice": practice,
        "studyPlan": study_plan,
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
    attempt_repo = deps.get_attempt_repo()
    review_service = deps.get_review_service()
    question_bank_service = deps.get_question_bank_service()
    quiz_service = deps.get_quiz_service()
    quiz_taking_service = deps.get_quiz_taking_service()
    quiz_marking_service = deps.get_quiz_marking_service()
    placement_service = deps.get_placement_service()
    student_profile_service = deps.get_student_profile_service()
    practice_service = deps.get_practice_service()
    flashcard_service = deps.get_flashcard_service()
    study_plan_service = deps.get_study_plan_service()

    teacher = _signup_account("teacher", Role.teacher, run_tag)
    school_admin = _signup_account("admin", Role.school_admin, run_tag)

    declining = _signup_account("declining", Role.student, run_tag)
    inactive = _signup_account("inactive", Role.student, run_tag)
    control = _signup_account("control", Role.student, run_tag)
    corrected = _signup_account("corrected", Role.student, run_tag)

    _log("Signing up the empty teacher (no classes) and empty parent (no linked children)")
    empty_teacher = _signup_account("empty-teacher", Role.teacher, run_tag)
    empty_parent_phone = build_empty_parent_phone(run_tag)
    _log(f"Requesting one OTP challenge for the empty parent's phone {empty_parent_phone}")
    empty_dev_code = auth_service.request_otp(empty_parent_phone)
    if empty_dev_code is None:
        raise RuntimeError(
            "AuthService.request_otp returned no code for the empty parent — the "
            "configured SMS provider delivers out of band, so this script cannot "
            "recover it to verify."
        )
    empty_parent_result = auth_service.verify_otp(empty_parent_phone, empty_dev_code)
    # Deliberately no ParentLinkService.link call — this account must stay
    # genuinely childless for the `empty` parent-portal screenshot capture.

    _log("Creating class and enrolling the at-risk roster")
    class_row = class_service.create_class(
        uuid.UUID(teacher["userId"]), f"P3.10 Seed Class {run_tag}"
    )
    assert class_row.join_code is not None  # noqa: S101 - always generated, see create_class
    for student in (declining, inactive, control):
        class_service.join_by_code(uuid.UUID(student["userId"]), class_row.join_code)

    _log("Persisting the declining-trend run (single subject, 3 papers)")
    _persist_attempts(declining["userId"], DECLINING_SCORES, declining_recorded_ats(now))

    _log(
        "Persisting the >=14-day-inactive attempt (deliberately LOW-confidence: T-08's "
        "real review-queue item, same score/date as always)"
    )
    inactive_report = accuracy_report_for_score(
        INACTIVE_SCORE,
        paper_number=1,
        confidence=ConfidenceBand.LOW,
        confidence_score=REVIEW_ITEM_CONFIDENCE_SCORE,
        needs_teacher_review=True,
    )
    inactive_attempt_id = attempt_repo.persist_correction(
        user_id=inactive["userId"],
        report=inactive_report,
        recorded_at=inactive_recorded_at(now).isoformat(),
    )

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

    _log("Locating the review-queue row the inactive attempt's fan-out created (T-08)")
    review_rows = review_service.list_queue(
        uuid.UUID(teacher["userId"]),
        Role.teacher,
        class_id=class_row.class_id,
        reason="low_confidence",
    )
    review_rows = [r for r in review_rows if r.attempt_id == inactive_attempt_id]
    if len(review_rows) != 1:
        raise RuntimeError(
            f"Expected exactly 1 low_confidence review-queue row for attempt "
            f"{inactive_attempt_id}, found {len(review_rows)} — REVIEW_ITEM_CONFIDENCE_SCORE "
            "may no longer be below REVIEW_CONFIDENCE_THRESHOLD."
        )
    review_item_row = review_rows[0]

    _log("Seeding the quiz's question bank (generated rows, paper_id=None — D3.7)")
    teacher_uuid = uuid.UUID(teacher["userId"])
    question_bank_service.add_questions(build_quiz_bank_questions(teacher_uuid))

    _log("Building and assigning the quiz")
    quiz_row = quiz_service.create_quiz(teacher_uuid, SUBJECT_CODE, f"P3.10 Seed Quiz {run_tag}")
    quiz_service.patch_draft(
        teacher_uuid,
        quiz_row.quiz_id,
        pool_source=QuestionSource.generated,
        requested_count=QUIZ_REQUESTED_COUNT,
        builder_step=4,
    )
    generation = quiz_service.generate_questions(teacher_uuid, quiz_row.quiz_id)
    if generation.shortfall:
        raise RuntimeError(
            f"Quiz question-bank shortfall {generation.shortfall} — QUIZ_BANK_BANDS/"
            f"QUIZ_REQUESTED_COUNT have drifted from allocate_difficulty(None, "
            f"{QUIZ_REQUESTED_COUNT})'s split; re-derive both together."
        )
    assignment_row = quiz_service.create_assignment(
        teacher_uuid, Role.teacher, quiz_row.quiz_id, class_row.class_id
    )

    _log(
        "Submitting the quiz as the control student, every answer deliberately wrong "
        "(see wrong_mcq_answer's docstring), then marking it — MCQ-only: zero Gemini calls"
    )
    control_uuid = uuid.UUID(control["userId"])
    quiz_taking_service.get_take(control_uuid, assignment_row.assignment_id)
    quiz_detail = quiz_service.get_quiz(teacher_uuid, quiz_row.quiz_id)
    included_questions = [
        q for q in quiz_detail.questions if q.status == QuizQuestionStatus.included
    ]
    for q in included_questions:
        # Every seeded row is MCQ (build_quiz_bank_questions), so this always holds.
        assert q.mcq_answer is not None  # noqa: S101
        quiz_taking_service.save_answer(
            control_uuid,
            assignment_row.assignment_id,
            q.question_ref,
            answer_text=wrong_mcq_answer(q.mcq_answer),
        )
    submit_result = quiz_taking_service.submit(control_uuid, assignment_row.assignment_id)
    mark_result = quiz_marking_service.mark_submission(submit_result.submission_id)
    if mark_result.status.value != "marked":
        _log(
            f"WARNING: quiz submission {submit_result.submission_id} did not mark "
            f"(status={mark_result.status.value}, error={mark_result.marking_error!r}) — "
            "T-10 will see an unmarked submission; not faked as marked."
        )

    # P4.9 chunk C: drop any PREVIOUS run's fixture rows before seeding this
    # run's. Without this the bank grows by 24 rows every run — the prompts
    # carry no run tag, and a student's practice/placement pool is scoped by
    # subject+paper, never by run — so the "hermetic 24-row Paper 2 bank
    # (6 rows/topic x 4 topics)" that PRACTICE_SET_COUNT and the placement
    # assembly are both reasoned against was only ever true on a virgin
    # database. It silently became a 48-, 72-, 96-row bank.
    #
    # That is not cosmetic: S-20's `insufficient_pool` capture is the first
    # state whose truth depends on the pool's SIZE (6 available < 10 requested
    # at the screen's default count). Once two runs had accumulated, the weak
    # topic held 12+ rows, the shortfall panel stopped rendering, and the audit
    # route timed out — a gate that passed on a fresh DB and failed ever after.
    # `question_bank` is referenced only by `quiz_questions.question_bank_id`
    # ON DELETE SET NULL, so retiring an earlier run's rows cannot orphan a
    # foreign key; those runs' quizzes are dead fixture data already.
    with get_sessionmaker()() as purge_session:
        purged = len(
            purge_session.execute(
                sa_delete(QuestionBank)
                .where(QuestionBank.prompt.contains(PLACEMENT_PROMPT_MARKER))
                .returning(QuestionBank.id)
            ).all()
        )
        purge_session.commit()
    _log(f"Purged {purged} placement fixture bank row(s) from previous seed runs")

    _log(
        "Seeding the placement-eligible 0625 past-paper bank (P4.8 chunk C) — real "
        "Subject/Paper rows via link_past_paper_rows(), never a hand-inserted one"
    )
    placement_bank_rows = build_placement_bank_questions(run_tag)
    question_bank_service.add_questions(placement_bank_rows)
    paper_link_outcome = question_bank_service.link_past_paper_rows()
    if paper_link_outcome.linked < len(placement_bank_rows):
        raise RuntimeError(
            f"Expected all {len(placement_bank_rows)} placement bank rows to link to a "
            f"Paper row, but only {paper_link_outcome.linked} did "
            f"(unparseable={paper_link_outcome.unparseable}, "
            f"no_subject_taxonomy={paper_link_outcome.no_subject_taxonomy}) — "
            "build_placement_paper_stem() may no longer parse as a CAIE question-paper "
            "filename."
        )

    _log(
        "Signing up the four placement-state accounts — distinct students per state "
        "(D4.6 §4's own-prior-placement exclusion forbids reusing one account across states)"
    )
    placement_unonboarded = _signup_account("placement-unonboarded", Role.student, run_tag)
    placement_available = _signup_account("placement-available", Role.student, run_tag)
    placement_in_progress = _signup_account("placement-in-progress", Role.student, run_tag)
    placement_completed = _signup_account("placement-completed", Role.student, run_tag)

    _log(
        "Onboarding + enrolling in 0625 the three placement accounts that need it — "
        "placement-unonboarded stays untouched so S-01/S-02 see a genuine first-run state. "
        f"Papers pinned to [{PLACEMENT_PAPER_NUMBER}] so the eligible pool is this seed's "
        "own MCQ rows only (see PLACEMENT_PAPER_NUMBER)"
    )
    for account in (placement_available, placement_in_progress, placement_completed):
        account_uuid = uuid.UUID(account["userId"])
        student_profile_service.mark_onboarding_complete(account_uuid)
        student_profile_service.upsert_enrolment(account_uuid, PLACEMENT_SUBJECT_CODE)
        # D4.9: an empty paper set means "not answered" and imposes NO restriction,
        # so this call is what actually narrows the pool. Without it the assembled
        # placement draws from the real ingested corpus too.
        student_profile_service.set_enrolment_papers(
            account_uuid, PLACEMENT_SUBJECT_CODE, [PLACEMENT_PAPER_NUMBER]
        )

    _log("Creating (never submitting) placement-in-progress's placement test — S-04")
    in_progress_uuid = uuid.UUID(placement_in_progress["userId"])
    in_progress_created = placement_service.create(in_progress_uuid, PLACEMENT_SUBJECT_CODE)

    _log(
        "Creating, taking, submitting and marking placement-completed's placement test — S-05, "
        "through the real /api/student/quizzes take/submit repos and QuizMarkingService, "
        "never a hand-inserted mark"
    )
    completed_uuid = uuid.UUID(placement_completed["userId"])
    completed_created = placement_service.create(completed_uuid, PLACEMENT_SUBJECT_CODE)
    take_detail = quiz_taking_service.get_take(completed_uuid, completed_created.assignment_id)
    foreign = [
        q.question_ref for q in take_detail.questions if not is_placement_seed_prompt(q.prompt)
    ]
    if foreign:
        # The hermeticity guard PLACEMENT_PAPER_NUMBER's note promises. Answering a
        # question this seed did not author is what previously (a) billed a live
        # Gemini call per theory question drawn from the real corpus and (b) scored
        # the "one deliberate mistake" student 6/16 instead of 14/16. Fail loudly
        # rather than silently reproduce either.
        raise RuntimeError(
            f"Placement assembled {len(foreign)} question(s) this seed did not author "
            f"({', '.join(foreign)}) — the eligible pool is no longer hermetic. Something "
            f"has ingested real 0625 Paper {PLACEMENT_PAPER_NUMBER} questions into "
            "question_bank; see PLACEMENT_PAPER_NUMBER for why that breaks S-05 and costs "
            "real Gemini budget."
        )
    for position, question in enumerate(take_detail.questions):
        # First question deliberately wrong, mirroring
        # tests/test_placement_repo.py::test_create_take_submit_mark_end_to_end — a
        # perfect score produces no WeaknessRecord at all (group_weak_areas excludes
        # any topic with zero net lost marks), and S-05's topic breakdown needs one.
        answer = wrong_mcq_answer(PLACEMENT_MCQ_ANSWER) if position == 0 else PLACEMENT_MCQ_ANSWER
        quiz_taking_service.save_answer(
            completed_uuid,
            completed_created.assignment_id,
            question.question_ref,
            answer_text=answer,
        )
    completed_submit = quiz_taking_service.submit(completed_uuid, completed_created.assignment_id)
    completed_mark = quiz_marking_service.mark_submission(completed_submit.submission_id)
    if completed_mark.status.value != "marked":
        raise RuntimeError(
            f"Placement submission {completed_submit.submission_id} did not mark "
            f"(status={completed_mark.status.value}, error={completed_mark.marking_error!r}) — "
            "S-05 needs a real marked result, not an unmarked one; this account's whole "
            "purpose is to provide it."
        )
    completed_result = placement_service.result(completed_uuid, completed_created.assignment_id)
    if not completed_result.marked:  # pragma: no cover - contradicts the check just above
        raise RuntimeError(
            "PlacementService.result reports marked=False immediately after a 'marked' "
            "QuizMarkingService outcome — investigate before trusting S-05's seed data."
        )

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
    review_item = {
        "itemId": str(review_item_row.item_id),
        "attemptId": str(review_item_row.attempt_id),
        "studentKey": "inactive",
    }
    quiz = {
        "quizId": str(quiz_row.quiz_id),
        "assignmentId": str(assignment_row.assignment_id),
        "submissionId": str(submit_result.submission_id),
        "submittedBy": "control",
        "status": mark_result.status.value,
    }
    empty_parent_dict = {
        "userId": str(empty_parent_result.user_id),
        "phone": empty_parent_phone,
        "accessToken": empty_parent_result.access_token,
    }
    placement_dict = {
        "subjectCode": PLACEMENT_SUBJECT_CODE,
        # Derived, never restated: a literal here silently drifted from the constant
        # that actually drives the paper stem the moment the paper changed.
        "paperNumber": PLACEMENT_PAPER_NUMBER,
        "bankQuestionCount": len(placement_bank_rows),
        "students": {
            "unonboarded": placement_unonboarded,
            "available": placement_available,
            "inProgress": {
                **placement_in_progress,
                "quizId": str(in_progress_created.quiz_id),
                "assignmentId": str(in_progress_created.assignment_id),
                "questionCount": in_progress_created.question_count,
            },
            "completed": {
                **placement_completed,
                "quizId": str(completed_created.quiz_id),
                "assignmentId": str(completed_created.assignment_id),
                "submissionId": str(completed_submit.submission_id),
                "awardedMarks": completed_result.awarded_marks,
                "maximumMarks": completed_result.maximum_marks,
            },
        },
    }

    # -------------------------------------------------------------------
    # P4.9 chunk C: the S-20..S-23 practice/flashcard accounts. No new bank
    # — these draw from the same hermetic 0625 Paper 2 pool the placement
    # block above already seeded and linked. See this module's docstring
    # for the full contract.
    # -------------------------------------------------------------------
    _log(
        "Signing up the three P4.9 practice/flashcard accounts — active/settled/bare, each "
        "the only one that can demonstrate its own mutually exclusive state"
    )
    practice_active = _signup_account("practice-active", Role.student, run_tag)
    practice_settled = _signup_account("practice-settled", Role.student, run_tag)
    practice_bare = _signup_account("practice-bare", Role.student, run_tag)

    _log(
        "Onboarding + enrolling all three in 0625, papers pinned to "
        f"[{PLACEMENT_PAPER_NUMBER}] so their pool is the same hermetic bank placement uses"
    )
    for account in (practice_active, practice_settled, practice_bare):
        account_uuid = uuid.UUID(account["userId"])
        student_profile_service.mark_onboarding_complete(account_uuid)
        student_profile_service.upsert_enrolment(account_uuid, PLACEMENT_SUBJECT_CODE)
        student_profile_service.set_enrolment_papers(
            account_uuid, PLACEMENT_SUBJECT_CODE, [PLACEMENT_PAPER_NUMBER]
        )

    active_uuid = uuid.UUID(practice_active["userId"])
    practice_request = PracticeRequest(
        subject_code=PLACEMENT_SUBJECT_CODE, count=PRACTICE_SET_COUNT
    )

    def _answer_practice_set(assignment_id: uuid.UUID, *, one_deliberate_mistake: bool) -> None:
        """Answer every question of a just-created practice set, MCQ-only.

        Reuses the identical hermeticity guard the placement block above
        uses: refuses to answer a question this seed did not author, rather
        than silently drawing on the real ingested corpus (see
        PLACEMENT_PAPER_NUMBER's note on why that both costs live Gemini
        budget and produces a meaningless baseline).
        """
        take_detail = quiz_taking_service.get_take(active_uuid, assignment_id)
        foreign = [
            q.question_ref for q in take_detail.questions if not is_placement_seed_prompt(q.prompt)
        ]
        if foreign:
            raise RuntimeError(
                f"Practice set {assignment_id} assembled {len(foreign)} question(s) this seed "
                f"did not author ({', '.join(foreign)}) — the hermetic pool has been "
                "contaminated; see PLACEMENT_PAPER_NUMBER."
            )
        for position, question in enumerate(take_detail.questions):
            answer = (
                wrong_mcq_answer(PLACEMENT_MCQ_ANSWER)
                if one_deliberate_mistake and position == 0
                else PLACEMENT_MCQ_ANSWER
            )
            quiz_taking_service.save_answer(
                active_uuid, assignment_id, question.question_ref, answer_text=answer
            )

    _log(
        "Creating practice-active's set A: answered (one deliberate mistake), submitted, and "
        "marked — S-21's 'marked' capture, and the WeaknessRecord S-20's weak-topic prefill needs"
    )
    set_a = practice_service.create(active_uuid, practice_request)
    _answer_practice_set(set_a.assignment_id, one_deliberate_mistake=True)
    set_a_submit = quiz_taking_service.submit(active_uuid, set_a.assignment_id)
    set_a_mark = quiz_marking_service.mark_submission(set_a_submit.submission_id)
    if set_a_mark.status.value != "marked":
        raise RuntimeError(
            f"Practice set A submission {set_a_submit.submission_id} did not mark "
            f"(status={set_a_mark.status.value}, error={set_a_mark.marking_error!r}) — S-21's "
            "'marked' capture and S-20's weak-topic prefill both need a real marked result."
        )

    _log(
        "Creating practice-active's set B: created only, never answered or submitted — "
        "S-21's working view (QuizTaker) and its not_submitted result"
    )
    set_b = practice_service.create(active_uuid, practice_request)

    _log(
        "Creating practice-active's set C: answered and submitted, deliberately NOT marked — "
        "S-21's marking state. Seedable at all only because "
        "quiz_taking_service.submit does not mark; the real HTTP route marks on a "
        "background thread, which is the race this direct service call sidesteps."
    )
    set_c = practice_service.create(active_uuid, practice_request)
    _answer_practice_set(set_c.assignment_id, one_deliberate_mistake=False)
    quiz_taking_service.submit(active_uuid, set_c.assignment_id)
    # Deliberately no quiz_marking_service.mark_submission call here — see the
    # log line above for why that omission is what makes this state seedable.

    _log("Creating practice-active's manual flashcard deck (3 cards, due now — S-22/S-23 default)")
    active_deck = flashcard_service.create_deck(
        active_uuid,
        subject_code=PLACEMENT_SUBJECT_CODE,
        title=f"P4.9 Seed Deck {run_tag}",
        origin=DeckOrigin.manual,
    )
    for i in range(1, 4):
        flashcard_service.add_card(
            active_uuid,
            active_deck.id,
            front=f"P4.9 seed card {i} — front ({run_tag})",
            back=f"P4.9 seed card {i} — back ({run_tag})",
        )

    _log(
        "Creating practice-settled's manual deck and reviewing every card 'good' — a real SM-2 "
        "scheduler outcome that pushes due_at into the future, never a hand-written date"
    )
    settled_uuid = uuid.UUID(practice_settled["userId"])
    settled_deck = flashcard_service.create_deck(
        settled_uuid,
        subject_code=PLACEMENT_SUBJECT_CODE,
        title=f"P4.9 Seed Deck {run_tag}",
        origin=DeckOrigin.manual,
    )
    settled_cards = [
        flashcard_service.add_card(
            settled_uuid,
            settled_deck.id,
            front=f"P4.9 settled card {i} — front ({run_tag})",
            back=f"P4.9 settled card {i} — back ({run_tag})",
        )
        for i in range(1, 4)
    ]
    for card in settled_cards:
        flashcard_service.record_review(settled_uuid, card.id, ReviewGrade.good)

    settled_due = flashcard_service.due_session(settled_uuid, subject_code=PLACEMENT_SUBJECT_CODE)
    if settled_due.total_due != 0 or settled_due.next_due_at is None:
        raise RuntimeError(
            "Expected practice-settled to have zero due cards and a real next_due_at after "
            f"grading every card 'good', got total_due={settled_due.total_due} "
            f"next_due_at={settled_due.next_due_at!r} — ReviewGrade.good may no longer push "
            "due_at into the future from initial_schedule's baseline."
        )

    # -- Study plans (P4.10 chunk C) ------------------------------------------
    # S-24 has four states and two of them cannot share an account: D4.13's
    # ``generated: false`` (no plan row this ISO week) and its
    # ``available: false / reason="no_signal"`` (a plan row that *is* a
    # persisted refusal) are mutually exclusive per account per week. They are
    # therefore split across accounts that already exist rather than seeded
    # onto a new one. Every state below is produced by calling the real
    # service; none is hand-written.

    _log("Generating practice-active's study plan — the real populated week")
    active_plan = study_plan_service.generate(active_uuid, PLACEMENT_SUBJECT_CODE)
    if not active_plan.available or not active_plan.sessions:
        raise RuntimeError(
            "Expected practice-active to generate a populated study plan — it is the only "
            "practice account carrying a WeaknessRecord, which is the signal `generate` needs. "
            f"Got available={active_plan.available} reason={active_plan.reason!r} "
            f"sessions={len(active_plan.sessions)}. If the seeded deliberately-wrong marked "
            "set stopped producing a weakness row, this state is no longer reachable."
        )

    # S-25's *provable* rationale arm ("this is one of your recorded weak
    # topics") only renders when the session's topic really is in the weak-topic
    # list the screen joins against. That list has a public source —
    # ``PracticeService.topics().weak_topics`` is the very list
    # ``GET /practice/{code}/topics`` returns, and its query is byte-identical
    # to the planner's — so it is read here rather than hardcoded. Taking
    # ``sessions[0]`` instead would assume weakness is active's only signal and
    # could silently capture the *honest-absence* arm under a screenshot named
    # for the provable one.
    active_weak_topics = set(
        practice_service.topics(active_uuid, PLACEMENT_SUBJECT_CODE).weak_topics
    )
    active_session = next((s for s in active_plan.sessions if s.topic in active_weak_topics), None)
    if active_session is None:
        raise RuntimeError(
            "No session in practice-active's study plan targets one of its own recorded weak "
            f"topics. Plan topics={sorted({s.topic for s in active_plan.sessions})!r}; "
            f"weak topics={sorted(active_weak_topics)!r}. S-25's provable recorded-weakness "
            "rationale would not render, so the capture would be named for a state it is not."
        )

    _log("Generating practice-settled's study plan — the persisted honest refusal")
    settled_plan = study_plan_service.generate(settled_uuid, PLACEMENT_SUBJECT_CODE)
    if settled_plan.available or settled_plan.reason != "no_signal":
        raise RuntimeError(
            "Expected practice-settled to generate a persisted refusal (available=False, "
            f"reason='no_signal'), got available={settled_plan.available} "
            f"reason={settled_plan.reason!r}. The account has none of the planner's three "
            "signals (no weakness rows, no placement, no confidence ratings); if one has "
            "leaked in, this capture has silently become a populated week."
        )

    # practice-bare gets no call at all: its state *is* the absence of a plan
    # row this week. Asserted rather than assumed — and note `get_current`
    # returns None, it does not raise.
    bare_uuid = uuid.UUID(practice_bare["userId"])
    if study_plan_service.get_current(bare_uuid, PLACEMENT_SUBJECT_CODE) is not None:
        raise RuntimeError(
            "Expected practice-bare to have no study plan row for this ISO week — its S-24 "
            "state is `generated: false`, the absence of a generate call. Something else in "
            "this seed is now generating a plan for it."
        )

    _log("Generating and fully completing placement-completed's study plan — the finished week")
    complete_plan = study_plan_service.generate(completed_uuid, PLACEMENT_SUBJECT_CODE)
    if not complete_plan.available or not complete_plan.sessions:
        raise RuntimeError(
            "Expected placement-completed to generate a populated study plan — its "
            "deliberately-wrong first placement answer leaves it both a WeaknessRecord and a "
            f"marked placement result, two of the planner's three signals. Got "
            f"available={complete_plan.available} reason={complete_plan.reason!r} "
            f"sessions={len(complete_plan.sessions)}."
        )
    for session_view in complete_plan.sessions:
        study_plan_service.complete_session(completed_uuid, session_view.id)
    # Re-read rather than trusting the return values: a partially-completed week
    # is the one failure mode here that would still screenshot cleanly, silently
    # becoming the populated week's twin.
    completed_plan = study_plan_service.get_current(completed_uuid, PLACEMENT_SUBJECT_CODE)
    if completed_plan is None or not completed_plan.sessions:
        raise RuntimeError(
            "placement-completed's study plan vanished between generation and read-back; "
            f"got {completed_plan!r}."
        )
    unfinished = [s.id for s in completed_plan.sessions if s.completed_at is None]
    if unfinished:
        raise RuntimeError(
            f"{len(unfinished)} of {len(completed_plan.sessions)} sessions in "
            f"placement-completed's week are not completed_at-stamped: {unfinished!r}. "
            "A half-complete week renders as the populated week, not the finished one."
        )

    study_plan_dict = {
        "subjectCode": PLACEMENT_SUBJECT_CODE,
        # S-25's route needs a real session id and no existing payload key carries one.
        "activeSessionId": str(active_session.id),
        "activeSessionTopic": active_session.topic,
        "activeSessionCount": len(active_plan.sessions),
        "completedSessionCount": len(completed_plan.sessions),
    }

    practice_dict = {
        "subjectCode": PLACEMENT_SUBJECT_CODE,
        "students": {
            "active": {
                **practice_active,
                "unsubmittedAssignmentId": str(set_b.assignment_id),
                "markingAssignmentId": str(set_c.assignment_id),
                "markedAssignmentId": str(set_a.assignment_id),
                "deckId": str(active_deck.id),
            },
            "settled": {
                **practice_settled,
                "deckId": str(settled_deck.id),
            },
            "bare": practice_bare,
        },
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
        review_item=review_item,
        quiz=quiz,
        empty_teacher=empty_teacher,
        empty_parent=empty_parent_dict,
        placement=placement_dict,
        practice=practice_dict,
        study_plan=study_plan_dict,
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
