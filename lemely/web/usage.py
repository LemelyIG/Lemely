"""Metering for every LLM-backed web action (paymob billing spec §2.4, §5.6, §5.7).

Every metered route takes three steps, in this order:

1. :meth:`UsageMeter.authorize` makes no ledger writes. It computes the estimate from
   server-side inputs, builds the payer chain and checks that the chain covers the top of
   the range. It raises :class:`UsageBlocked`, which ``create_app`` turns into the 402
   contract. Its first call on an empty database may seed the usage catalogue (about 18
   idempotent inserts, ``ensure_usage_catalogue``), so it is not strictly read-only.
2. :meth:`UsageMeter.reserve` holds ``estimate_high`` across the chain and opens the
   ``usage_jobs`` row, under the ledger's per-owner locks, so two concurrent reserves can
   never overdraw. It runs in the request, so a 402 can still come back before a stream or
   a pool job starts. A job whose subject is not known yet (a student's scan, read inside
   the job) reserves later, in :meth:`MeteredJob.bind_subject`.
3. ``with job.run():`` wraps the work, in whatever thread does it. It opens the cost
   accumulator and settles the actual cost on a normal exit. It releases on an exception
   or after :meth:`MeteredJob.abandon`, so failed work and input rejected before any model
   call cost nothing. The web layer's thread hops (the SSE worker, the grading pool, the
   quiz marking thread) do not copy context, which is why the scope opens inside the
   worker. The block must join every thread it starts before it exits: the total is read
   once, at exit. The hold is a lease: on entry ``run()`` restarts it (queued work can
   start long after its reserve), reserving again if the sweeper already expired it, and
   one shared daemon thread renews it while the work runs. A job that can no longer be
   covered fails with a block reason before any model call; only a request still open can
   send that as a 402 (a pool or SSE worker reports it its own way). ``run()`` must enter
   and exit in one thread and one context, so it wraps the worker's callable, never the
   body of a generator the framework iterates. Metered
   jobs never nest (an inner cost scope would shadow the outer one and the outer job would
   under-charge), so :meth:`MeteredJob.run` refuses to. :meth:`MeteredJob.release` is only
   for a reserved job whose ``run()`` will never start.

:meth:`UsageMeter.job` is steps 2 and 3 together, for a synchronous route. A settle or
release that fails after the work finished is logged (``usage_finish_failed``) and never
raised into the request; the sweeper expires the job left open.
"""

from __future__ import annotations

import contextlib
import contextvars
import inspect
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, TypeVar

import structlog
from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse

from lemely.core.metered_actions import (
    ACTION_SPECS,
    JOB_SLACK,
    MeteredAction,
    UsageTarget,
    clamp_inputs,
)
from lemely.core.payer_chain import (
    UsageBlockReason,
    block_reason,
    build_payer_chain,
    job_teacher_member_id,
)
from lemely.core.usage_pricing import estimate_range
from lemely.core.usage_types import GrantScope
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageJobStatus
from lemely.db.session import get_sessionmaker
from lemely.db.usage_catalogue_repo import current_estimator, current_rate_version
from lemely.db.usage_context_repo import (
    AssistantUnavailable,
    allowance_units,
    candidate_subjects,
    load_block_facts,
    load_chain_context,
)
from lemely.db.usage_ledger_repo import InsufficientBalance, UsageLedger
from lemely.io.llm.cost_meter import cost_scope
from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import (
    AuthContext,
    TeamActor,
    get_settings,
    require_role,
    team_lead_unavailable_error,
    team_permission_denied_error,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import Request
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.payer_chain import ChainContext
    from lemely.core.usage_types import EstimatorParams, Payer
    from lemely.db.models.usage import UsageJob

log = structlog.get_logger(__name__)

T = TypeVar("T")

#: Called after a job settles, in the settle's transaction (paymob billing phase 06
#: registers the auto top-up hook in ``create_app``). It runs while the chain owners'
#: advisory locks are held, so a hook must be quick and do no network I/O (spec §6:
#: metering never calls Paymob); phase 06's hook only enqueues.
PostSettleHook = Callable[["Session", "UsageJob", Sequence["Payer"], datetime], None]
_POST_SETTLE_HOOKS: list[PostSettleHook] = []


def register_post_settle_hook(hook: PostSettleHook) -> None:
    """Add ``hook`` once. ``create_app`` registers the billing hooks at startup."""
    if hook not in _POST_SETTLE_HOOKS:
        _POST_SETTLE_HOOKS.append(hook)


def clear_post_settle_hooks() -> None:
    """Remove every hook (tests)."""
    _POST_SETTLE_HOOKS.clear()


def run_post_settle_hooks(
    session: Session, job: UsageJob, payers: Sequence[Payer], now: datetime
) -> None:
    """Run each hook in its own savepoint. A failing hook is logged and never undoes the settle.

    Only ``Exception`` is caught: a ``BaseException`` from a hook (``KeyboardInterrupt``,
    interpreter exit) rolls the settle back with it, and the sweeper expires the open job.
    """
    for hook in tuple(_POST_SETTLE_HOOKS):
        try:
            with session.begin_nested():
                hook(session, job, payers, now)
        except Exception:
            log.warning(
                "post_settle_hook_failed",
                hook=getattr(hook, "__name__", repr(hook)),
                exc_info=True,
            )


#: The copy an SSE error frame carries when a job is blocked after it started streaming.
USAGE_BLOCKED_MESSAGE = "You don't have enough usage left for this. Check your plan or credits."
#: Roles never metered (plan deviation 10). Their cost is still logged.
EXEMPT_ROLES: frozenset[Role] = frozenset({Role.platform_admin})

#: The metered job running in this context, so a second one inside it is refused.
_RUNNING_JOB: contextvars.ContextVar[MeteredJob | None] = contextvars.ContextVar(
    "lemely_running_metered_job", default=None
)
#: The shortest gap between two renewals of one running job's hold.
_MIN_RENEW_EVERY = timedelta(seconds=30)


class _HoldRenewer:
    """One daemon thread that keeps every running metered job's hold alive.

    A job joins when its run holds units (at :meth:`MeteredJob.run` entry, or in
    :meth:`MeteredJob.bind_subject` inside the run) and leaves before it settles or
    releases. Each due job's hold is extended to ``now + job_timeout + JOB_SLACK`` from
    this thread, so a run that outlasts its timeout keeps its hold. A stopped process
    stops renewing, so its holds still clear one lease after the last renewal. One
    thread serves every job; renewals of different jobs run one after another.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._due: dict[MeteredJob, float] = {}
        self._every: dict[MeteredJob, float] = {}
        self._renewing: MeteredJob | None = None
        self._thread: threading.Thread | None = None

    def add(self, job: MeteredJob, every: float) -> None:
        """Renew ``job``'s hold every ``every`` seconds until :meth:`remove`."""
        with self._cond:
            self._every[job] = every
            self._due[job] = time.monotonic() + every
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._loop, name="lemely-hold-renewer", daemon=True
                )
                self._thread.start()
            self._cond.notify_all()

    def remove(self, job: MeteredJob) -> None:
        """Stop renewing ``job``. Returns only once no renewal of it is in flight."""
        with self._cond:
            self._due.pop(job, None)
            self._every.pop(job, None)
            while self._renewing is job:
                self._cond.wait()

    def _next_due(self) -> MeteredJob:
        """Wait (holding the condition) until a job is due, then mark it in flight."""
        while True:
            if not self._due:
                self._cond.wait()
                continue
            job, due = min(self._due.items(), key=lambda item: item[1])
            delay = due - time.monotonic()
            if delay <= 0:
                self._renewing = job
                self._due[job] = time.monotonic() + self._every[job]
                return job
            self._cond.wait(delay)

    def _loop(self) -> None:
        while True:
            with self._cond:
                job = self._next_due()
            keep = True
            try:
                keep = job._renew()
            except Exception:
                # The next tick retries; the hold keeps its last deadline meanwhile.
                log.warning(
                    "usage_renew_failed",
                    job_id=str(job.job_id),
                    action=job.ctx.request.action.value,
                    exc_info=True,
                )
            finally:
                with self._cond:
                    self._renewing = None
                    if not keep:
                        self._due.pop(job, None)
                        self._every.pop(job, None)
                    self._cond.notify_all()


_RENEWER = _HoldRenewer()

_NESTED_JOB = "nested metered job: an inner cost scope would hide its cost from the outer job"
_CROSSED_CONTEXT = (
    "MeteredJob.run() exited in a different thread or context than it entered: wrap the "
    "worker's callable, never the body of a generator the framework iterates"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UsageBlocked(Exception):
    """The payer chain cannot cover the top of the estimate (HTTP 402)."""

    def __init__(self, reason: UsageBlockReason, estimate: tuple[int, int]) -> None:
        super().__init__(f"usage blocked: {reason.value}")
        self.reason = reason
        self.estimate = estimate

    def body(self) -> dict[str, object]:
        """The 402 body every client reads (index, phase 04 contract)."""
        return {
            "error": "usage_blocked",
            "reason": self.reason.value,
            "estimate": [self.estimate[0], self.estimate[1]],
        }


class UsageUnavailable(Exception):
    """The ledger could not restart a queued job's hold, and the old one may lapse mid-run.

    Raised by :meth:`MeteredJob.run` before any work, after the hold was released, so
    nothing is charged and the job can be run again later. Workers report it like
    :class:`UsageBlocked`; it is not a 402 (no block reason fits a ledger outage).
    """


async def usage_blocked_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Render :class:`UsageBlocked` as the top-level 402 body (not under ``detail``)."""
    if not isinstance(exc, UsageBlocked):
        raise exc
    return JSONResponse(status_code=402, content=exc.body())


def _assistant_refusal(exc: AssistantUnavailable) -> HTTPException:
    """Phase 03's team-guard 403 for an assistant the chain loader would not confirm.

    Never caught and continued: falling back to the assistant's own chain would let the
    assistant's balance pay for team work (R4).
    """
    if exc.code == "team_lead_unavailable":
        return team_lead_unavailable_error()
    return team_permission_denied_error()


@dataclass(frozen=True)
class UsageRequest:
    """One metered action, as the server sees it. Every field is read on the server."""

    actor_user_id: uuid.UUID
    actor_role: Role
    action: MeteredAction
    subject_code: str | None = None
    input_count: int = 0
    assistant_member_id: uuid.UUID | None = None
    subject_pending: bool = False


@dataclass(frozen=True)
class UsageGrantContext:
    """What :meth:`UsageMeter.authorize` approved: the chain and the estimate."""

    request: UsageRequest
    chain: tuple[Payer, ...]
    estimate: tuple[int, int]
    estimator_version: int
    rate_version: int
    teacher_member_id: uuid.UUID | None
    exempt: bool = False

    @classmethod
    def exempt_for(cls, request: UsageRequest) -> UsageGrantContext:
        """A context that reserves nothing (exempt role, or enforcement off)."""
        return cls(
            request=request,
            chain=(),
            estimate=(0, 0),
            estimator_version=0,
            rate_version=0,
            teacher_member_id=None,
            exempt=True,
        )


@dataclass(frozen=True)
class EstimateView:
    """``POST /api/usage/estimate``'s answer: the range and who would pay."""

    low: int
    high: int
    payer: str
    percent_low: int | None
    percent_high: int | None
    blocked_reason: UsageBlockReason | None


@dataclass(frozen=True)
class _Evaluation:
    estimator: EstimatorParams
    rate_version: int
    estimate: tuple[int, int]
    chain_ctx: ChainContext
    chain: tuple[Payer, ...]
    available: int


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


class MeteredJob:
    """One metered job: reserved in the request, run and settled wherever the work runs."""

    def __init__(self, meter: UsageMeter | None, ctx: UsageGrantContext, job_id: uuid.UUID) -> None:
        self._meter = meter
        self.ctx = ctx
        self.job_id = job_id
        self._reserved = False
        self._abandoned = False
        self._finished = False
        self._running = False
        # The hold's current deadline as this job last set or saw it.
        self._deadline: datetime | None = None
        # Guards _finished and _running: release() may come from the request thread
        # while run() starts in a worker.
        self._lock = threading.Lock()

    @classmethod
    def unmetered(cls, action: MeteredAction) -> MeteredJob:
        """A job that records nothing and needs no database (callers outside a request)."""
        request = UsageRequest(
            actor_user_id=uuid.UUID(int=0), actor_role=Role.platform_admin, action=action
        )
        return cls(None, UsageGrantContext.exempt_for(request), uuid.uuid4())

    def _live_meter(self) -> UsageMeter:
        if self._meter is None:
            raise RuntimeError("an unmetered job has no meter")
        return self._meter

    def _reserve(self, *, in_worker: bool = False) -> None:
        meter = self._live_meter()
        ctx = self.ctx
        now = meter.now()
        spec = ACTION_SPECS[ctx.request.action]
        expires_at = now + spec.job_timeout + JOB_SLACK
        try:
            with meter.sessionmaker.begin() as session:
                # The ledger takes a transaction-scoped advisory lock per payer owner before
                # it reads balances, so concurrent reserves on one owner serialize.
                UsageLedger(session).reserve(
                    job_id=self.job_id,
                    actor_user_id=ctx.request.actor_user_id,
                    action=ctx.request.action.value,
                    payers=list(ctx.chain),
                    estimate_low=ctx.estimate[0],
                    estimate_high=ctx.estimate[1],
                    estimator_version=ctx.estimator_version,
                    rate_version=ctx.rate_version,
                    teacher_member_id=ctx.teacher_member_id,
                    expires_at=expires_at,
                    now=now,
                )
        except InsufficientBalance as exc:
            # Another job took the balance between authorize and reserve.
            raise UsageBlocked(self._block_reason(in_worker=in_worker), ctx.estimate) from exc
        self._reserved = True
        self._deadline = expires_at

    def _block_reason(self, *, in_worker: bool) -> UsageBlockReason:
        """The block reason, read on fresh facts.

        In a worker, a chain that no longer loads (an assistant removed while the job was
        queued is phase 03's 403) is reported as a block: no request is left to send a 403.
        """
        meter = self._live_meter()
        if not in_worker:
            return meter.reason_for(self.ctx.request)
        try:
            return meter.reason_for(self.ctx.request)
        except HTTPException:
            return UsageBlockReason.INSUFFICIENT_CREDITS

    def bind_subject(self, subject_code: str | None) -> None:
        """Fix a deferred job's subject (read inside the job), re-check and reserve.

        Raises :class:`UsageBlocked` when no payer covers the detected subject; inside
        :meth:`run` that releases (nothing was held) and re-raises.
        """
        if self.ctx.exempt:
            return
        if not self.ctx.request.subject_pending or self._reserved:
            raise RuntimeError("bind_subject is only for a job whose subject is still pending")
        meter = self._live_meter()
        self.ctx = meter.authorize(
            replace(self.ctx.request, subject_code=subject_code, subject_pending=False)
        )
        self._reserve()
        if self._running:
            _RENEWER.add(self, meter.renew_interval(self.ctx.request.action))

    def abandon(self) -> None:
        """Mark the work failed without raising: :meth:`run` releases instead of settling."""
        self._abandoned = True

    def release(self) -> None:
        """Release a reserved job whose :meth:`run` will never start (claim lost, submit refused).

        Never call it while :meth:`run` is active, in this thread or another: the work
        would finish free. Such a call is logged (``usage_release_while_running``) and
        ignored; use :meth:`abandon` to fail running work. Once released, :meth:`run`
        refuses to start.
        """
        with self._lock:
            if self._running:
                log.warning(
                    "usage_release_while_running",
                    job_id=str(self.job_id),
                    action=self.ctx.request.action.value,
                )
                return
            if self._finished:
                return
            self._finished = True
        self._finish(Decimal(0), settle=False)

    @contextlib.contextmanager
    def run(self) -> Iterator[MeteredJob]:
        """Meter the enclosed work: settle on a normal exit, release on failure.

        Enter and exit in one thread and one context: wrap the worker's callable, never
        the body of a generator the framework iterates (Starlette runs each ``next()`` of
        a sync stream in a fresh context, so costs after the first yield would be lost).
        An exit in another thread or context releases the job, logs
        ``usage_run_crossed_context`` and raises :class:`RuntimeError`. One job runs once:
        a second ``run()`` while the first is active (re-entered, or another thread) logs
        ``usage_run_already_running`` and raises :class:`RuntimeError` without touching the
        running hold. On entry the hold's lease restarts (:meth:`_restart_clock`, which may
        raise :class:`UsageBlocked` or :class:`UsageUnavailable` before any work), and it is
        renewed every third of the action's timeout until exit. Join every worker
        thread before the block exits; the total is read at exit.
        """
        # This job already running (re-entered here, or in another thread) is refused
        # without touching its hold; only a different job running here is a nested one.
        with self._lock:
            self._refuse_if_unrunnable()
        if _RUNNING_JOB.get() is not None:
            self._end(Decimal(0), settle=False)
            raise RuntimeError(_NESTED_JOB)
        with self._lock:
            self._refuse_if_unrunnable()
            self._running = True
        if self._reserved:
            try:
                self._restart_clock()
            except BaseException:
                # Refused before any work. A hold still open is released (best effort).
                if self._reserved:
                    self._end(Decimal(0), settle=False)
                with self._lock:
                    self._running = False
                    self._finished = True
                raise
            _RENEWER.add(self, self._live_meter().renew_interval(self.ctx.request.action))
        entry_thread = threading.get_ident()
        token = _RUNNING_JOB.set(self)
        scope = cost_scope()
        accumulator = scope.__enter__()
        try:
            yield self
        except BaseException:
            self._exit(scope, token, entry_thread, accumulator.total_usd, settle=False)
            raise
        self._exit(scope, token, entry_thread, accumulator.total_usd, settle=not self._abandoned)

    def _refuse_if_unrunnable(self) -> None:
        """Raise if this job finished or is running. The caller holds ``self._lock``."""
        if self._finished:
            raise RuntimeError("this metered job was already released or finished")
        if self._running:
            # Its cost would never be billed, and releasing would free the running hold.
            log.error(
                "usage_run_already_running",
                job_id=str(self.job_id),
                action=self.ctx.request.action.value,
            )
            raise RuntimeError("this metered job is already running")

    def _restart_clock(self) -> None:
        """Start the hold's lease when the work starts, not when it was reserved.

        Queued work (a class set behind one grading worker) can start long after its
        reserve. The open hold is extended to ``now + job_timeout + JOB_SLACK``; while the
        work runs, :class:`_HoldRenewer` keeps extending it. A synchronous route pays this
        one transaction too: the in-memory deadline cannot tell whether a sweeper (or an
        admin) closed the job since the reserve.

        * Expired (the sweeper returned it): reserved again, same chain and estimate,
          under a new job id. A chain that cannot cover it raises :class:`UsageBlocked`;
          a database failure propagates. Either way no work starts unmetered.
        * Settled or released by someone else: raises; re-reserving would bill the work
          twice or bill work that was cancelled.
        * The extend fails twice: the work starts only if the old deadline is still a
          whole ``job_timeout`` away; otherwise :class:`UsageUnavailable` (fail closed).
        """
        meter = self._live_meter()
        now = meter.now()
        spec = ACTION_SPECS[self.ctx.request.action]
        lease = spec.job_timeout + JOB_SLACK
        deadline = self._deadline
        status = self._extend_with_retry(now + lease, now)
        if status is None:
            if deadline is not None and deadline - now >= spec.job_timeout:
                return
            log.error(
                "usage_extend_refused_start",
                job_id=str(self.job_id),
                action=self.ctx.request.action.value,
                deadline=None if deadline is None else deadline.isoformat(),
            )
            raise UsageUnavailable("the usage ledger could not restart this job's hold")
        if status is UsageJobStatus.open:
            return
        if status is not UsageJobStatus.expired:
            log.error(
                "usage_job_closed_before_start",
                job_id=str(self.job_id),
                action=self.ctx.request.action.value,
                status=status.value,
            )
            raise RuntimeError(
                f"usage job {self.job_id} was {status.value} before its work started"
            )
        old_job_id, new_job_id = self.job_id, uuid.uuid4()
        log.warning(
            "usage_hold_expired_before_start",
            old_job_id=str(old_job_id),
            new_job_id=str(new_job_id),
            action=self.ctx.request.action.value,
        )
        self.job_id = new_job_id
        self._reserved = False
        self._reserve(in_worker=True)

    def _extend_with_retry(self, expires_at: datetime, now: datetime) -> UsageJobStatus | None:
        """Extend the hold, retrying once. ``None`` when both attempts failed."""
        for attempt in (1, 2):
            try:
                return self._extend(expires_at, now)
            except Exception:
                log.warning(
                    "usage_extend_failed",
                    job_id=str(self.job_id),
                    action=self.ctx.request.action.value,
                    attempt=attempt,
                    exc_info=True,
                )
        return None

    def _extend(self, expires_at: datetime, now: datetime) -> UsageJobStatus:
        meter = self._live_meter()
        with meter.sessionmaker.begin() as session:
            job = UsageLedger(session).extend(self.job_id, expires_at=expires_at, now=now)
            status, deadline = job.status, job.expires_at
        if status is UsageJobStatus.open:
            self._deadline = deadline
        return status

    def _renew(self) -> bool:
        """Extend the running job's hold (the renewer's thread). False once it is gone."""
        meter = self._live_meter()
        now = meter.now()
        spec = ACTION_SPECS[self.ctx.request.action]
        status = self._extend(now + spec.job_timeout + JOB_SLACK, now)
        if status is UsageJobStatus.open:
            return True
        # The settle at exit is refused (usage_settle_on_closed_job), so this run is unbilled.
        log.warning(
            "usage_hold_lost_mid_run",
            job_id=str(self.job_id),
            action=self.ctx.request.action.value,
            status=status.value,
        )
        return False

    def _exit(
        self,
        scope: contextlib.AbstractContextManager[object],
        token: contextvars.Token[MeteredJob | None],
        entry_thread: int,
        cost_usd: Decimal,
        *,
        settle: bool,
    ) -> None:
        _RENEWER.remove(self)
        crossed = _RUNNING_JOB.get() is not self or threading.get_ident() != entry_thread
        if crossed:
            log.error(
                "usage_run_crossed_context",
                job_id=str(self.job_id),
                action=self.ctx.request.action.value,
                cost_usd=str(cost_usd),
            )
            self._end(cost_usd, settle=False)
            with self._lock:
                self._running = False
            # Both context variables were set in the context run() entered; resetting
            # them from another one raises ValueError, which would hide the real error.
            with contextlib.suppress(ValueError):
                scope.__exit__(None, None, None)
            with contextlib.suppress(ValueError):
                _RUNNING_JOB.reset(token)
            raise RuntimeError(_CROSSED_CONTEXT)
        try:
            self._end(cost_usd, settle=settle)
        finally:
            with self._lock:
                self._running = False
            scope.__exit__(None, None, None)
            _RUNNING_JOB.reset(token)

    def _end(self, cost_usd: Decimal, *, settle: bool) -> None:
        """Finish once: the first caller settles or releases, any later call does nothing."""
        with self._lock:
            if self._finished:
                return
            self._finished = True
        self._finish(cost_usd, settle=settle)

    def _finish(self, cost_usd: Decimal, *, settle: bool) -> None:
        """Settle or release in the ledger. Callers claim the job first (:meth:`_end`)."""
        request = self.ctx.request
        if not self._reserved:
            if settle and request.subject_pending and not self.ctx.exempt:
                # A deferred job finished its work without bind_subject: nothing was held,
                # so the work ran free. Never raised (spec §2.4); monitoring alerts on it.
                log.warning(
                    "usage_deferred_unbound",
                    job_id=str(self.job_id),
                    action=request.action.value,
                    actor_user_id=str(request.actor_user_id),
                    cost_usd=str(cost_usd),
                )
                return
            log.info(
                "usage_unmetered_cost",
                action=request.action.value,
                actor_user_id=str(request.actor_user_id),
                cost_usd=str(cost_usd),
                exempt=self.ctx.exempt,
            )
            return
        meter = self._live_meter()
        now = meter.now()
        try:
            with meter.sessionmaker.begin() as session:
                ledger = UsageLedger(session)
                if settle:
                    # The single settle point (plan deviation 12). Hooks run in the settle's
                    # transaction, each in its own savepoint.
                    settled_job = ledger.settle(self.job_id, actual_cost_usd=cost_usd, now=now)
                    if settled_job.status is UsageJobStatus.settled:
                        run_post_settle_hooks(session, settled_job, list(self.ctx.chain), now)
                    else:
                        # The sweeper closed the job while the work ran past its whole
                        # deadline: the hold is back and the balance may be spent, so a late
                        # charge would make unplanned debt. Refused; the cost is in this line.
                        # ``alert=True``: unbilled work, the event a log-based alert keys on.
                        log.error(
                            "usage_settle_on_closed_job",
                            alert=True,
                            job_id=str(self.job_id),
                            action=request.action.value,
                            actor_user_id=str(request.actor_user_id),
                            status=settled_job.status.value,
                            cost_usd=str(cost_usd),
                            rate_version=settled_job.rate_version,
                        )
                else:
                    ledger.release(self.job_id, now=now)
        except Exception:
            # The work has finished; metering must not turn it into a failure (spec §2.4).
            # The sweeper expires a job left open, and the cost is in this line.
            log.exception(
                "usage_finish_failed",
                job_id=str(self.job_id),
                action=request.action.value,
                settle=settle,
                cost_usd=str(cost_usd),
            )


class UsageMeter:
    """Authorize, estimate and reserve metered jobs against the usage ledger."""

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        enforce: bool = True,
        now: Callable[[], datetime] = _utcnow,
        renew_every: timedelta | None = None,
    ) -> None:
        self.sessionmaker = sessionmaker
        self._enforce = enforce
        self._now = now
        self._renew_every = renew_every

    def renew_interval(self, action: MeteredAction) -> float:
        """Seconds between renewals of a running job's hold: a third of its timeout."""
        if self._renew_every is not None:
            return self._renew_every.total_seconds()
        return max(ACTION_SPECS[action].job_timeout / 3, _MIN_RENEW_EVERY).total_seconds()

    def now(self) -> datetime:
        """The meter's clock (timezone-aware)."""
        return self._now()

    def _exempt(self, request: UsageRequest) -> bool:
        return not self._enforce or request.actor_role in EXEMPT_ROLES

    def _chain_context(
        self, session: Session, request: UsageRequest, subject: str | None, now: datetime
    ) -> ChainContext:
        try:
            return load_chain_context(
                session,
                actor_user_id=request.actor_user_id,
                action=request.action,
                subject_code=subject,
                assistant_member_id=request.assistant_member_id,
                now=now,
            )
        except AssistantUnavailable as exc:
            raise _assistant_refusal(exc) from exc

    def _evaluate(self, session: Session, request: UsageRequest, now: datetime) -> _Evaluation:
        params = current_estimator(session, request.action, now=now)
        rate_version = current_rate_version(session, request.action, now=now)
        estimate = estimate_range(params, clamp_inputs(request.input_count))
        ledger = UsageLedger(session)
        subjects = (
            candidate_subjects(session, actor_user_id=request.actor_user_id, action=request.action)
            if request.subject_pending
            else [request.subject_code]
        )
        best: _Evaluation | None = None
        for subject in subjects:
            chain_ctx = self._chain_context(session, request, subject, now)
            chain = tuple(build_payer_chain(chain_ctx))
            available = ledger.available(chain, now=now)
            if best is None or available > best.available:
                best = _Evaluation(params, rate_version, estimate, chain_ctx, chain, available)
        if best is None:
            raise RuntimeError("candidate_subjects returned no subject")
        return best

    def authorize(self, request: UsageRequest) -> UsageGrantContext:
        """Check the chain covers ``estimate_high``. Raises :class:`UsageBlocked`.

        No ledger writes: nothing is held until :meth:`reserve`. The first call on an
        empty database may seed the usage catalogue (idempotent inserts). An assistant the
        chain loader cannot confirm is phase 03's 403 (``team_permission_denied`` or
        ``team_lead_unavailable``). Exempt roles, and every caller when enforcement is
        off, get an exempt context without a database read.
        """
        if self._exempt(request):
            return UsageGrantContext.exempt_for(request)
        now = self._now()
        with self.sessionmaker.begin() as session:
            ev = self._evaluate(session, request, now)
            reason = (
                None
                if ev.available >= ev.estimate[1]
                else block_reason(load_block_facts(session, ev.chain_ctx, ev.chain, now=now))
            )
        if reason is not None:
            raise UsageBlocked(reason, ev.estimate)
        return UsageGrantContext(
            request=request,
            chain=ev.chain,
            estimate=ev.estimate,
            estimator_version=ev.estimator.version,
            rate_version=ev.rate_version,
            teacher_member_id=job_teacher_member_id(ev.chain),
        )

    def reason_for(self, request: UsageRequest) -> UsageBlockReason:
        """The block reason against fresh facts (after a lost reservation race)."""
        now = self._now()
        with self.sessionmaker.begin() as session:
            ev = self._evaluate(session, request, now)
            return block_reason(load_block_facts(session, ev.chain_ctx, ev.chain, now=now))

    def estimate(self, request: UsageRequest) -> EstimateView:
        """The range, the scope that would pay first, and a block reason if any.

        No ledger writes; like :meth:`authorize` it may seed a missing catalogue.
        """
        if self._exempt(request):
            return EstimateView(0, 0, "none", None, None, None)
        now = self._now()
        with self.sessionmaker.begin() as session:
            ev = self._evaluate(session, request, now)
            ledger = UsageLedger(session)
            payer = next((p for p in ev.chain if ledger.available([p], now=now) > 0), None)
            units = (
                allowance_units(session, payer, now=now)
                if payer is not None and payer.scope is not GrantScope.CREDITS
                else None
            )
            blocked = (
                None
                if ev.available >= ev.estimate[1]
                else block_reason(load_block_facts(session, ev.chain_ctx, ev.chain, now=now))
            )
        low, high = ev.estimate
        return EstimateView(
            low=low,
            high=high,
            payer="none" if payer is None else payer.scope.value,
            percent_low=_ceil_div(100 * low, units) if units else None,
            percent_high=_ceil_div(100 * high, units) if units else None,
            blocked_reason=blocked,
        )

    def reserve(self, ctx: UsageGrantContext) -> MeteredJob:
        """Hold the estimate now (a deferred-subject job holds in ``bind_subject``).

        Raises :class:`UsageBlocked` when another job took the balance since
        :meth:`authorize`, so the 402 still comes before any stream or pool job starts.
        """
        job = MeteredJob(self, ctx, uuid.uuid4())
        if not ctx.exempt and not ctx.request.subject_pending:
            job._reserve()
        return job

    @contextlib.contextmanager
    def job(self, ctx: UsageGrantContext) -> Iterator[MeteredJob]:
        """Reserve and run in one block, for a synchronous route.

        Refuses a nested job before it reserves, so the refusal costs no ledger writes.
        """
        if _RUNNING_JOB.get() is not None:
            raise RuntimeError(_NESTED_JOB)
        metered = self.reserve(ctx)
        with metered.run():
            yield metered

    def resolve_target(self, fn: Callable[[Session], UsageTarget | None]) -> UsageTarget | None:
        """Read an action's server-side target. Without enforcement, reads nothing."""
        if not self._enforce:
            return UsageTarget(subject_code=None, input_count=0)
        with self.sessionmaker() as session:
            return fn(session)

    def read(self, fn: Callable[[Session], T]) -> T:
        """Run a read-only query (the meter and history views)."""
        with self.sessionmaker() as session:
            return fn(session)


def get_usage_meter(settings: Annotated[Settings, Depends(get_settings)]) -> UsageMeter:
    """The request's meter. Building it opens no connection (the engine is lazy).

    The sessionmaker comes from ``get_sessionmaker(get_settings())``, the process-wide
    one every other store dependency uses, so a test that overrides ``get_settings``
    with another database URL never makes this dependency rebuild the shared engine.
    """
    return UsageMeter(get_sessionmaker(get_settings()), enforce=settings.usage.enforce)


def request_from_auth(
    auth: AuthContext,
    action: MeteredAction,
    *,
    subject_code: str | None = None,
    input_count: int = 0,
    assistant_member_id: uuid.UUID | None = None,
    subject_pending: bool = False,
) -> UsageRequest:
    """A :class:`UsageRequest` for the authenticated caller."""
    return UsageRequest(
        actor_user_id=uuid.UUID(auth.user_id),
        actor_role=Role(auth.role),
        action=action,
        subject_code=subject_code,
        input_count=input_count,
        assistant_member_id=assistant_member_id,
        subject_pending=subject_pending,
    )


def request_from_team(
    actor: TeamActor,
    action: MeteredAction,
    *,
    subject_code: str | None = None,
    input_count: int = 0,
) -> UsageRequest:
    """A :class:`UsageRequest` for a team route (R4): an assistant bills the lead.

    ``actor.member_id`` is the assistant's row, so the chain is the lead's allowance, then the
    lead's credits, within the assistant's cap; the assistant's own balance is never in it.
    ``actor.auth`` is the lead's context (role ``teacher``) for an assistant, else the
    caller's own, so ``actor_role`` is the caller's real role when acting as themselves.
    """
    return UsageRequest(
        actor_user_id=actor.actor_user_id,
        actor_role=Role(actor.auth.role),
        action=action,
        subject_code=subject_code,
        input_count=input_count,
        assistant_member_id=actor.member_id,
    )


def _no_target() -> UsageTarget:
    return UsageTarget(subject_code=None, input_count=0)


# FastAPI dependencies: callables whose parameters FastAPI itself resolves, so their
# parameter lists are open by design.
TargetDependency = Callable[..., UsageTarget]  # type: ignore[explicit-any]
TeamDependency = Callable[..., TeamActor]  # type: ignore[explicit-any]
UsageDependency = Callable[..., UsageGrantContext]  # type: ignore[explicit-any]


def require_usage(
    action: MeteredAction,
    *,
    roles: Sequence[Role] = (),
    target: TargetDependency | None = None,
    team: TeamDependency | None = None,
) -> UsageDependency:
    """A dependency that authorizes ``action`` for the caller (402 when blocked).

    It carries the route's guard, so a wrong role or a team refusal is its 401/403 before
    the meter reads the ledger, wherever the route declares this dependency. Pass exactly
    one guard:

    * ``roles``: the platform roles the route allows, checked by :func:`require_role`;
    * ``team``: the route's own ``require_team_permission(...)`` guard (the same object,
      so FastAPI resolves it once per request). An assistant's usage is then charged to
      the lead teacher (R4).

    Building it with neither or both raises :class:`TypeError`. ``target`` is a dependency
    returning the server-side :class:`UsageTarget` (subject and countable inputs). It must
    read through :meth:`UsageMeter.resolve_target`, so a non-enforcing meter reads nothing.
    """
    if team is None and not roles:
        raise TypeError("require_usage needs the route's guard: pass roles=... or team=...")
    if team is not None and roles:
        raise TypeError("require_usage takes roles= or team=, not both (team checks roles)")
    resolver = target or _no_target

    def _usage(
        who: AuthContext | TeamActor, meter: UsageMeter, resolved: UsageTarget
    ) -> UsageGrantContext:
        if isinstance(who, TeamActor):
            request = request_from_team(
                who, action, subject_code=resolved.subject_code, input_count=resolved.input_count
            )
        else:
            request = request_from_auth(
                who, action, subject_code=resolved.subject_code, input_count=resolved.input_count
            )
        return meter.authorize(request)

    # Built as objects, not source annotations: under `from __future__ import annotations`
    # FastAPI evaluates string annotations against module globals, where the closure's
    # `resolver` and `team` do not exist.
    keyword = inspect.Parameter.KEYWORD_ONLY
    caller = (
        Annotated[TeamActor, Depends(team)]
        if team is not None
        else Annotated[AuthContext, Depends(require_role(*roles))]
    )
    _usage.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=[
            inspect.Parameter("who", keyword, annotation=caller),
            inspect.Parameter(
                "meter", keyword, annotation=Annotated[UsageMeter, Depends(get_usage_meter)]
            ),
            inspect.Parameter(
                "resolved", keyword, annotation=Annotated[UsageTarget, Depends(resolver)]
            ),
        ],
        return_annotation=UsageGrantContext,
    )
    return _usage


__all__ = [
    "EXEMPT_ROLES",
    "USAGE_BLOCKED_MESSAGE",
    "EstimateView",
    "MeteredJob",
    "PostSettleHook",
    "UsageBlocked",
    "UsageGrantContext",
    "UsageMeter",
    "UsageRequest",
    "UsageUnavailable",
    "clear_post_settle_hooks",
    "get_usage_meter",
    "register_post_settle_hook",
    "request_from_auth",
    "request_from_team",
    "require_usage",
    "run_post_settle_hooks",
    "usage_blocked_handler",
]
