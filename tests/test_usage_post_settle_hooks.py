"""Post-settle hooks (Phase 04 registry, consumed by Phase 06): run after a settle, never undo it.

These pin the contract Phase 06's auto top-up relies on. They pass on arrival against Phase 04's
registry; their job is to go red if Phase 04 drops the savepoint, moves the call away from the
settle, or runs a hook for a settle that was refused.
"""

from __future__ import annotations

import ast
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa

from lemely.core.metered_actions import MeteredAction
from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web import usage
from lemely.web.usage import UsageRequest
from tests.usage_helpers import NOW, enforcing_meter, give, jobs_for, seed_catalogue, seed_user

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

_USAGE_PY = Path(usage.__file__)


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    saved = list(usage._POST_SETTLE_HOOKS)
    usage.clear_post_settle_hooks()
    yield
    usage.clear_post_settle_hooks()
    usage._POST_SETTLE_HOOKS.extend(saved)


def test_register_is_idempotent() -> None:
    def hook(*_: Any) -> None:
        return None

    usage.register_post_settle_hook(hook)
    usage.register_post_settle_hook(hook)
    assert [hook] == usage._POST_SETTLE_HOOKS


def test_failing_hook_is_rolled_back_alone(migrated_sessionmaker: sessionmaker[Session]) -> None:
    kept, dropped = uuid.uuid4(), uuid.uuid4()

    def writes_then_fails(session: Session, *_: Any) -> None:
        session.add(User(id=dropped, email=f"{dropped}@example.com", role=Role.student))
        session.flush()
        raise RuntimeError("boom")

    seen: list[object] = []
    usage.register_post_settle_hook(writes_then_fails)
    usage.register_post_settle_hook(lambda _s, job, payers, now: seen.append((job, payers, now)))
    with migrated_sessionmaker() as session:
        session.add(User(id=kept, email=f"{kept}@example.com", role=Role.student))
        session.flush()
        usage.run_post_settle_hooks(session, "job", [], NOW)  # type: ignore[arg-type]
        session.commit()
    with migrated_sessionmaker() as session:
        ids = set(session.scalars(sa.select(User.id).where(User.id.in_([kept, dropped]))))
    assert ids == {kept}
    assert seen == [("job", [], NOW)]


def test_usage_meter_runs_hooks_right_after_settle() -> None:
    """Structural pin: every function in usage.py that settles a job runs the hooks after it."""
    tree = ast.parse(_USAGE_PY.read_text(encoding="utf-8"))
    settling: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        settle_lines = [c.lineno for c in calls if getattr(c.func, "attr", None) == "settle"]
        hook_lines = [
            c.lineno
            for c in calls
            if getattr(c.func, "id", getattr(c.func, "attr", None)) == "run_post_settle_hooks"
        ]
        if settle_lines:
            settling.append(fn.name)
            assert hook_lines, fn.name
            assert min(hook_lines) > max(settle_lines), fn.name
    assert settling  # non-vacuity: the meter does settle somewhere


def _drive_a_settle(sm: sessionmaker[Session], *, sweeper_closes_the_job: bool) -> list[Any]:
    """Run one metered job to its settle; return what the registered recording hook saw."""
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=1000)
    seen: list[Any] = []
    usage.register_post_settle_hook(lambda _s, job, payers, now: seen.append((job.id, payers, now)))
    meter = enforcing_meter(sm)
    request = UsageRequest(
        actor_user_id=student,
        actor_role=Role.student,
        action=MeteredAction.MARK_PAPER,
        subject_code=None,
        assistant_member_id=None,
        subject_pending=False,
    )
    with meter.job(meter.authorize(request)):
        record_llm_cost(Decimal("0.020"))
        if sweeper_closes_the_job:
            # The work overran its whole deadline: the sweeper expires the open job.
            with sm.begin() as session:
                assert UsageLedger(session).expire_stale_jobs(now=NOW + timedelta(days=1)) == 1
    (row,) = jobs_for(sm, student)
    assert row.status.value == ("expired" if sweeper_closes_the_job else "settled")
    return seen


def test_a_settled_job_runs_the_hook_once(migrated_sessionmaker: sessionmaker[Session]) -> None:
    """Non-vacuity for the next test: the same drive does reach the hook when the settle holds."""
    seen = _drive_a_settle(migrated_sessionmaker, sweeper_closes_the_job=False)
    assert len(seen) == 1


def test_a_settle_on_a_closed_job_runs_no_hook(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """``usage_settle_on_closed_job`` is a refused settle: no charge, so no top-up check.

    Driven through ``MeteredJob._finish`` with a real database: the sweeper expires the job
    while the work runs, then the exit settle is refused and the hook must not run.
    """
    seen = _drive_a_settle(migrated_sessionmaker, sweeper_closes_the_job=True)
    assert seen == []
