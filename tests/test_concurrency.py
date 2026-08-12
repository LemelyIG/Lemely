"""Postgres integration tests for concurrent writers (Phase 6, P6.2).

MISSION.md §4 Phase 6 requires "concurrency test (parallel uploads/markings)".
Every test here fires *real* threads, each opening its own DB session/
connection through a shared ``sessionmaker`` — never ``asyncio.gather`` over
one session, which would just serialise everything on a single connection and
prove nothing about a genuine race. Mirrors the throwaway-database/skip-
cleanly convention from ``test_device_repo.py``.

Three races, chosen because each is a real read-then-write a naive
implementation can get wrong under concurrency, not because they are easy to
write:

1. **Parallel corrections for different students don't bleed** — the
   literal "parallel uploads/markings" MISSION asks for. Each
   :meth:`~lemely.db.attempt_repo.AttemptRepository.persist_correction` call
   opens its own transaction and writes one owner-scoped ``Attempt`` row; a
   thread-safety regression (e.g. session/state leaking across threads)
   would show up as a paper landing on the wrong student.
2. **The 3-device cap holds under concurrent logins**
   (:data:`~lemely.db.device_repo.MAX_DEVICES`). ``DeviceRegistry.register_login``
   locks the owning ``users`` row ``FOR UPDATE`` for exactly this reason (see
   its docstring); this test is the concurrency proof for that lock, run with
   real parallel logins rather than trusted from reading the code.
3. **XP anti-farming caps under concurrent awards**
   (:class:`~lemely.db.xp_repo.XpService`, D5.1 §3/§8). ``award()`` is a
   textbook TOCTOU: it reads today's per-source event count, compares to
   :data:`~lemely.db.xp_repo.DAILY_SOURCE_CAPS`, and only *then* inserts —
   with no row lock between the read and the write. Two concurrent awards for
   the same student/source, each with a distinct ``dedupe_key`` (so the
   unique-dedupe constraint can't save it), can both read "under the cap" and
   both insert. This test proves whether that race is real; see the docstring
   on ``test_xp_source_cap_is_not_exceeded_by_concurrent_awards`` for what was
   found.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

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
from lemely.db.base import Base
from lemely.db.device_repo import MAX_DEVICES, DeviceRegistry
from lemely.db.models import Device, User
from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import Role, XpSource
from lemely.db.xp_repo import DAILY_SOURCE_CAPS, XpService
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


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

    # A real pool (not NullPool/single-conn) so concurrent threads actually
    # get concurrent connections — this is what makes the race observable.
    engine = create_engine(make_url(base_url).set(database=dbname), pool_size=10, max_overflow=10)
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


# ── 1. Parallel corrections for different students do not bleed ────────────


def _report_for(
    *, awarded_marks: int, maximum_marks: int, subject_code: str = "0625"
) -> AccuracyReport:
    """A minimal one-question :class:`AccuracyReport` carrying a distinguishing mark.

    ``awarded_marks`` is unique per caller in the test below, so if two
    threads' writes ever got attributed to the wrong ``Attempt``/owner, the
    per-student assertions would catch it deterministically rather than
    relying on timing to make a mismatch visible.
    """
    metadata = ExamMetadata(
        subject_code=subject_code,
        paper_number=1,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )
    question = CorrectedQuestion(
        question_id="1",
        awarded_marks=awarded_marks,
        maximum_marks=maximum_marks,
        confidence=ConfidenceBand.HIGH,
        confidence_score=1.0,
        needs_teacher_review=False,
        student_answer="A",
        expected_answer="A",
        topic="Waves",
        marker_source="deterministic",
        matched_point_ids=["p1"],
    )
    correction = CorrectionResult(metadata=metadata, questions=[question])
    weaknesses = WeaknessReport(weak_areas=[])
    prediction = GradePrediction(
        awarded_marks=awarded_marks,
        maximum_marks=maximum_marks,
        percentage=round(awarded_marks / maximum_marks * 100.0, 2),
        grade="A" if awarded_marks else "U",
        confidence=ConfidenceBand.HIGH,
        needs_teacher_review=False,
        boundary_source="subject_default",
    )
    return AccuracyReport(correction=correction, weaknesses=weaknesses, grade_prediction=prediction)


def test_parallel_corrections_for_different_students_do_not_bleed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # MISSION §4 Phase 6's literal "parallel uploads/markings": N students all
    # get corrected at once (e.g. a class submitting near a deadline). Each
    # student's awarded_marks is unique so a cross-attribution bug — thread A's
    # write landing under thread B's owner, or on the wrong Attempt — fails
    # this test's per-student assertions rather than passing by coincidence.
    n = 8
    user_ids = [_seed_user(pg_sessionmaker) for _ in range(n)]
    repo = AttemptRepository(pg_sessionmaker)

    def _persist(index: int, uid: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID, int]:
        report = _report_for(awarded_marks=index, maximum_marks=n)
        attempt_id = repo.persist_correction(user_id=str(uid), report=report)
        return uid, attempt_id, index

    results: list[tuple[uuid.UUID, uuid.UUID, int]] = []
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(_persist, i, uid) for i, uid in enumerate(user_ids)]
        for future in as_completed(futures):
            results.append(future.result())

    assert len(results) == n
    # Every attempt landed under its own owner with its own mark — no bleed.
    with pg_sessionmaker() as session:
        for uid, attempt_id, expected_marks in results:
            attempt = session.get(Attempt, attempt_id)
            assert attempt is not None
            assert attempt.user_id == uid
            assert attempt.awarded_marks == expected_marks

        all_attempts = session.scalars(select(Attempt)).all()
        assert len(all_attempts) == n
        assert {a.user_id for a in all_attempts} == set(user_ids)


# ── 2. The 3-device cap holds under concurrent logins ───────────────────────


def test_device_cap_holds_under_concurrent_logins(pg_sessionmaker: sessionmaker[Session]) -> None:
    # N *simultaneous* registrations for one user (e.g. the same account
    # opening the app on several devices back-to-back with no serialising
    # delay between requests). A naive count-then-insert would race: two
    # threads could both read "2 live devices, room for one more" and both
    # insert, leaving more than MAX_DEVICES live rows.
    # DeviceRegistry.register_login guards against exactly this with a
    # `SELECT ... FOR UPDATE` on the owning user row (see its docstring).
    #
    # Falsifiability, verified by hand (not asserted here — this is a record
    # of how this test was checked, not a self-test): with
    # `with_for_update=True` reverted to `False` at device_repo.py:134 and 4
    # threads with no synchronisation, the earlier version of this test only
    # caught the regression in ~12/20 runs — the race window is short enough
    # that unsynchronised Python threads often serialise on the GIL and never
    # actually overlap inside it, so a lucky run looked green with the lock
    # removed. Two changes close that gap: a `threading.Barrier` forces every
    # thread to enter `register_login` at (as near as CPython allows) the same
    # instant, and MAX_DEVICES + 8 threads (vs. 4) means several must overlap
    # for the cap to hold even if a few happen to interleave harmlessly. With
    # both changes, 20/20 runs failed with the lock removed and 20/20 passed
    # with it restored.
    uid = _seed_user(pg_sessionmaker)
    registry = DeviceRegistry(pg_sessionmaker)
    n = MAX_DEVICES + 8
    barrier = threading.Barrier(n)

    def _login(i: int) -> uuid.UUID:
        barrier.wait()  # release all n threads into register_login at once
        return registry.register_login(
            uid, client_device_id=f"device-{i}", now=datetime(2026, 7, 31, tzinfo=UTC)
        ).session_id

    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(_login, i) for i in range(n)]
        session_ids = [f.result() for f in as_completed(futures)]

    assert len(session_ids) == n
    with pg_sessionmaker() as session:
        live = session.scalars(
            select(Device).where(Device.user_id == uid, Device.revoked_at.is_(None))
        ).all()
    # Exactly MAX_DEVICES survive, no matter which of the n logins the
    # eviction race picked as the loser.
    assert len(live) == MAX_DEVICES


# ── 3. XP anti-farming caps are not defeated by concurrency ────────────────


def test_xp_source_cap_is_not_exceeded_by_concurrent_awards(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Concurrent awards for one student/source must not exceed the daily cap.

    **This race is real.** ``XpService.award`` (lemely/db/xp_repo.py) reads
    today's per-source event count, compares it to
    ``DAILY_SOURCE_CAPS[source]``, and only afterwards inserts the new
    ``XpEvent`` row. Each award here uses a distinct ``dedupe_key``, so
    migration 0013's per-(user, source, dedupe_key) unique constraint cannot
    save it — that constraint stops the *same* dedupe_key being awarded
    twice, not N different ones racing past the cap.

    **This race was real and has been fixed.** Before this change,
    ``XpService.award`` read today's per-source event count with a plain
    ``session.get(User, ...)`` and only afterwards inserted, with no lock
    between the read and the write — unlike
    ``DeviceRegistry.register_login``, which locks the owning ``users`` row
    ``FOR UPDATE`` for exactly this reason. Run against the unpatched code,
    this test observed 8 of 8 concurrent awards succeed against a cap of 3.
    The fix mirrors the device registry exactly (``with_for_update=True`` on
    the same ``session.get(User, ...)`` call in ``XpService.award``) — the
    same lock, the same table, the same TOCTOU shape, already an established
    idiom in this codebase — so it qualified as the "SELECT ... FOR UPDATE is
    the clear intent" case rather than one that needed a design review. See
    the "Concurrency" section of ``XpService.award``'s docstring
    (``lemely/db/xp_repo.py``) for the fix itself.
    """
    uid = _seed_user(pg_sessionmaker)
    xp = XpService(pg_sessionmaker)
    source = XpSource.quiz_completed
    cap = DAILY_SOURCE_CAPS[source]
    # Fire more concurrent awards than the cap allows for this source.
    attempts = cap + 5
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

    def _award(i: int) -> bool:
        result = xp.award(uid, source, f"dedupe-{i}", now=now)
        return result.awarded

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        futures = [pool.submit(_award, i) for i in range(attempts)]
        awarded_flags = [f.result() for f in as_completed(futures)]

    successful = sum(awarded_flags)
    # The row count is the ground truth — not the returned "awarded" flags,
    # in case a caller-side miscount and a DB-side overcount happened to
    # cancel out.
    with pg_sessionmaker() as session:
        row_count = session.scalar(
            sa.select(sa.func.count())
            .select_from(xp_events_table())
            .where(xp_events_table().c.user_id == uid, xp_events_table().c.source == source.value)
        )

    assert successful <= cap, (
        f"{successful} concurrent awards succeeded for a cap of {cap} — "
        "the read-then-write cap check in XpService.award is not safe under "
        "concurrency (see this test's docstring)."
    )
    assert row_count is not None
    assert row_count <= cap, (
        f"{row_count} XpEvent rows written for a cap of {cap} — same race, "
        "confirmed at the storage layer."
    )


def xp_events_table() -> sa.Table:
    """The ``xp_events`` table, fetched from the shared metadata (avoids a second import)."""
    return Base.metadata.tables["xp_events"]
