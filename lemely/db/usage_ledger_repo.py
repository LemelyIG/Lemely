"""The usage ledger: grants, reservations, settlement, expiry, debt (spec §4.5, §5.6-§5.8).

:class:`UsageLedger` works inside the caller's transaction and never commits.
Every method that changes a balance first takes one transaction-scoped advisory
lock per owner involved, in ascending UUID order, then locks the
``usage_grant_balances`` rows it touches with ``FOR UPDATE`` in payer-chain
order and, within one payer, in spend order (``priority``, then ``expires_at``
with never-expiring last, then ``effective_at``, then ``id``). The owner locks
give every writer one global order, so two jobs whose chains name the same
owners in a different order cannot deadlock, and they also serialise the debt
check for an owner that has no grants to lock.

The balance cache and the entries change together under those locks, so
:meth:`UsageLedger.reconcile_balances` finding drift means a bug, not a race.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from sqlalchemy.exc import IntegrityError

from lemely.core.usage_pricing import GRANT_PRIORITY, usd_to_units
from lemely.core.usage_types import GrantScope, Payer, payer_from_json, payer_to_json
from lemely.db.models.usage import (
    GrantKind,
    UsageDebt,
    UsageEntry,
    UsageEntryKind,
    UsageGrant,
    UsageGrantBalance,
    UsageJob,
    UsageJobStatus,
    UsageRate,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session, SessionTransaction

logger = logging.getLogger("lemely.db.usage_ledger_repo")
#: Structured events the sweeps raise alerts on (``alert=True`` survives only in structlog).
alerts = structlog.get_logger("lemely.db.usage_ledger_repo")

#: Rows one expiry sweep handles, oldest first; the rest wait for the next pass.
DEFAULT_SWEEP_LIMIT = 500
#: How far a job whose expiry failed steps back, so it stops pinning the head of the batch.
FAILED_EXPIRY_BACKOFF = timedelta(hours=1)


class _Member(Enum):
    """``_entry``'s default: tag the entry with the payer's member, else the job's."""

    FROM_PAYER_OR_JOB = "from_payer_or_job"


@dataclass(frozen=True)
class StaleJobSweep:
    """One :meth:`UsageLedger.sweep_stale_jobs` pass."""

    candidates: int
    expired: int
    failed: tuple[uuid.UUID, ...]


#: Entry kinds that move a grant's ``remaining``; ``hold``/``release`` move ``held``.
REMAINING_KINDS: tuple[UsageEntryKind, ...] = (
    UsageEntryKind.grant,
    UsageEntryKind.settle,
    UsageEntryKind.expire,
    UsageEntryKind.refund,
    UsageEntryKind.adjust,
    UsageEntryKind.debt_repay,
)

HELD_KINDS: tuple[UsageEntryKind, ...] = (UsageEntryKind.hold, UsageEntryKind.release)

_SPEND_ORDER = (
    UsageGrant.priority.asc(),
    UsageGrant.expires_at.asc().nulls_last(),
    UsageGrant.effective_at.asc(),
    UsageGrant.id.asc(),
)


class GrantAlreadyExpired(ValueError):
    """A grant's expiry cannot be extended: the sweep or a claw-back already took its leftover."""


class StrandedHolds(RuntimeError):
    """A job holds units on grants its stored payer chain no longer reaches."""

    def __init__(self, job_id: uuid.UUID, grant_ids: set[uuid.UUID]) -> None:
        super().__init__(
            f"usage job {job_id} holds units on grants {sorted(grant_ids)} "
            "that its payer chain no longer reaches"
        )
        self.job_id = job_id
        self.grant_ids = grant_ids


class InsufficientBalance(Exception):
    """The chain cannot cover the amount asked for."""

    def __init__(self, message: str = "", *, available: int = 0, required: int = 0) -> None:
        super().__init__(message or f"available {available} < required {required}")
        self.available = available
        self.required = required


@dataclass
class _Slot:
    """A grant and its balance row, as one payer in the chain sees it."""

    grant: UsageGrant
    balance: UsageGrantBalance
    payer: Payer
    taken: int = 0

    @property
    def free(self) -> int:
        return self.balance.remaining - self.balance.held - self.taken


def _scope_filter(payer: Payer) -> sa.ColumnElement[bool]:
    if payer.scope is GrantScope.ALLOWANCE:
        return sa.and_(UsageGrant.visible.is_(False), UsageGrant.teacher_member_id.is_(None))
    if payer.scope is GrantScope.CREDITS:
        return UsageGrant.visible.is_(True)
    return sa.and_(
        UsageGrant.kind == GrantKind.seat_allowance,
        UsageGrant.teacher_member_id == payer.teacher_member_id,
    )


def _usable_at(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        UsageGrant.effective_at <= now,
        sa.or_(UsageGrant.expires_at.is_(None), UsageGrant.expires_at > now),
    )


def _is_usable(grant: UsageGrant, now: datetime) -> bool:
    return grant.effective_at <= now and (grant.expires_at is None or grant.expires_at > now)


def _cap_key(payer: Payer) -> tuple[uuid.UUID, uuid.UUID] | None:
    if payer.cap_units is None or payer.teacher_member_id is None:
        return None
    return (payer.owner_user_id, payer.teacher_member_id)


class UsageLedger:
    def __init__(self, session: Session) -> None:
        self._session = session

    @classmethod
    def lock_owner(cls, session: Session, owner_user_id: uuid.UUID) -> None:
        """Take the owner's ledger lock until the transaction ends.

        The ledger's own writers take it too, and it is re-entrant within a transaction, so a
        caller that reads a balance to audit a ledger write can take it first and read a
        balance no concurrent write can change before that write.
        """
        cls(session)._lock_owners([owner_user_id])

    def issue_grant(
        self,
        *,
        owner_user_id: uuid.UUID,
        kind: GrantKind,
        units: int,
        idempotency_key: str,
        expires_at: datetime | None,
        visible: bool,
        effective_at: datetime | None = None,
        payment_id: uuid.UUID | None = None,
        subscription_period_id: uuid.UUID | None = None,
        teacher_member_id: uuid.UUID | None = None,
    ) -> UsageGrant:
        """Create a grant, or return the one already issued under this key.

        A new grant first repays the owner's debts, oldest first (§5.8). A
        ``seat_allowance`` grant does not: it is the teacher's money for
        in-scope work, and §5.6 keeps it usable while the student has debt.
        """
        return self._issue(
            owner_user_id=owner_user_id,
            kind=kind,
            units=units,
            idempotency_key=idempotency_key,
            expires_at=expires_at,
            visible=visible,
            effective_at=effective_at,
            payment_id=payment_id,
            subscription_period_id=subscription_period_id,
            teacher_member_id=teacher_member_id,
            reason=None,
        )

    def _issue(
        self,
        *,
        owner_user_id: uuid.UUID,
        kind: GrantKind,
        units: int,
        idempotency_key: str,
        expires_at: datetime | None,
        visible: bool,
        effective_at: datetime | None,
        payment_id: uuid.UUID | None,
        subscription_period_id: uuid.UUID | None,
        teacher_member_id: uuid.UUID | None,
        reason: str | None,
    ) -> UsageGrant:
        if units <= 0:
            raise ValueError("units must be > 0")
        if (kind is GrantKind.seat_allowance) != (teacher_member_id is not None):
            raise ValueError("teacher_member_id is set exactly on seat_allowance grants")
        if visible and kind in (GrantKind.period_allowance, GrantKind.seat_allowance):
            raise ValueError("allowance grants are never visible")
        self._lock_owners([owner_user_id])
        existing = self._session.scalars(
            sa.select(UsageGrant).where(
                UsageGrant.owner_user_id == owner_user_id,
                UsageGrant.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        if existing is not None:
            stored_reason = self._session.scalar(
                sa.select(UsageEntry.reason).where(
                    UsageEntry.grant_id == existing.id, UsageEntry.kind == UsageEntryKind.grant
                )
            )
            if existing.kind is not kind or existing.units != units or stored_reason != reason:
                logger.warning(
                    "grant replay under key %r for owner %s differs from the stored grant "
                    "(kind %s vs %s, units %d vs %d, reason %r vs %r); "
                    "returning the stored grant",
                    idempotency_key,
                    owner_user_id,
                    kind.value,
                    existing.kind.value,
                    units,
                    existing.units,
                    reason,
                    stored_reason,
                )
            return existing
        at = effective_at if effective_at is not None else datetime.now(UTC)
        grant = UsageGrant(
            owner_user_id=owner_user_id,
            kind=kind,
            visible=visible,
            teacher_member_id=teacher_member_id,
            priority=GRANT_PRIORITY[kind.value],
            units=units,
            effective_at=at,
            expires_at=expires_at,
            payment_id=payment_id,
            subscription_period_id=subscription_period_id,
            idempotency_key=idempotency_key,
        )
        self._session.add(grant)
        self._session.flush()
        balance = UsageGrantBalance(grant_id=grant.id, remaining=units, held=0)
        self._session.add(balance)
        self._entry(
            kind=UsageEntryKind.grant,
            units=units,
            event_at=at,
            key=idempotency_key,
            grant_id=grant.id,
            reason=reason,
        )
        if kind is not GrantKind.seat_allowance:
            self._repay_debts(grant, balance, at)
        self._session.flush()
        return grant

    def _repay_debts(self, grant: UsageGrant, balance: UsageGrantBalance, at: datetime) -> None:
        for debt in self._open_debts(grant.owner_user_id):
            if balance.remaining == 0:
                return
            repay = min(debt.outstanding, balance.remaining)
            self._entry(
                kind=UsageEntryKind.debt_repay,
                units=-repay,
                event_at=max(at, datetime.now(UTC)),
                key=f"repay:{debt.id}",
                grant_id=grant.id,
                debt_id=debt.id,
            )
            debt.outstanding -= repay
            balance.remaining -= repay

    def has_debt(self, owner_user_id: uuid.UUID) -> bool:
        return bool(
            self._session.scalar(
                sa.select(
                    sa.exists().where(
                        UsageDebt.owner_user_id == owner_user_id, UsageDebt.outstanding > 0
                    )
                )
            )
        )

    def available(self, payers: Sequence[Payer], *, now: datetime) -> int:
        """Units the chain could reserve now: usable grants, minus holds, within caps."""
        slots = self._slots(payers, now=now, lock=False)
        return sum(take for _slot, take in self._walk(slots, None, payers, now=now))

    def meter_fraction(
        self, owner_user_id: uuid.UUID, *, teacher_member_id: uuid.UUID | None, now: datetime
    ) -> float | None:
        """``(units - remaining) / units`` over the current allowance grants (§4.5).

        With ``teacher_member_id`` it reads that seat's ``seat_allowance``
        grants; without, the owner's ``period_allowance`` grants (an upgrade
        adds a second one for the same period, so they are summed). ``None``
        when there is no current grant.
        """
        if teacher_member_id is not None:
            which = sa.and_(
                UsageGrant.kind == GrantKind.seat_allowance,
                UsageGrant.teacher_member_id == teacher_member_id,
            )
        else:
            which = UsageGrant.kind == GrantKind.period_allowance
        total, remaining = self._session.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(UsageGrant.units), 0),
                sa.func.coalesce(sa.func.sum(UsageGrantBalance.remaining), 0),
            )
            .join(UsageGrantBalance, UsageGrantBalance.grant_id == UsageGrant.id)
            .where(UsageGrant.owner_user_id == owner_user_id, which, _usable_at(now))
        ).one()
        if not total:
            return None
        return (int(total) - int(remaining)) / int(total)

    def _lock_owners(self, owner_ids: Sequence[uuid.UUID]) -> None:
        for owner_id in sorted(set(owner_ids)):
            self._session.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"usage:{owner_id}"},
            )

    def _slots(
        self,
        payers: Sequence[Payer],
        *,
        now: datetime,
        lock: bool,
        include: set[uuid.UUID] | None = None,
    ) -> list[_Slot]:
        """Each payer's grants in spend order, chain order across payers, each grant once."""
        slots: list[_Slot] = []
        seen: set[uuid.UUID] = set()
        for payer in payers:
            reachable = _usable_at(now)
            if include:
                reachable = sa.or_(reachable, UsageGrant.id.in_(include))
            stmt = (
                sa.select(UsageGrant, UsageGrantBalance)
                .join(UsageGrantBalance, UsageGrantBalance.grant_id == UsageGrant.id)
                .where(UsageGrant.owner_user_id == payer.owner_user_id, _scope_filter(payer))
                .where(reachable)
                .order_by(*_SPEND_ORDER)
            )
            if lock:
                stmt = stmt.with_for_update(of=UsageGrantBalance).execution_options(
                    populate_existing=True
                )
            for grant, balance in self._session.execute(stmt).tuples():
                if grant.id in seen:
                    continue
                seen.add(grant.id)
                slots.append(_Slot(grant=grant, balance=balance, payer=payer))
        return slots

    def _walk(
        self,
        slots: Sequence[_Slot],
        need: int | None,
        payers: Sequence[Payer],
        *,
        now: datetime,
        after_release: bool = False,
    ) -> list[tuple[_Slot, int]]:
        """Draw ``need`` (``None`` = everything) down the slots, honouring debt and caps.

        A payer whose owner has debt is skipped unless it is ``debt_exempt``.
        A cap is shared by every payer with the same ``(owner, teacher_member_id)``.
        Marks each drawn amount on ``slot.taken`` and returns ``(slot, take)`` pairs.
        """
        indebted = {
            p.owner_user_id for p in payers if not p.debt_exempt and self.has_debt(p.owner_user_id)
        }
        cap_left: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
        for payer in payers:
            key = _cap_key(payer)
            if key is not None and key not in cap_left and payer.cap_units is not None:
                used = self._cap_used(payer)
                if after_release:
                    used += sum(s.taken for s in slots if _cap_key(s.payer) == key)
                cap_left[key] = max(payer.cap_units - used, 0)
        plan: list[tuple[_Slot, int]] = []
        left = need
        for slot in slots:
            if left is not None and left <= 0:
                break
            if slot.payer.owner_user_id in indebted and not slot.payer.debt_exempt:
                continue
            if not _is_usable(slot.grant, now):
                continue
            take = slot.free
            if left is not None:
                take = min(take, left)
            key = _cap_key(slot.payer)
            if key is not None:
                take = min(take, cap_left[key])
            if take <= 0:
                continue
            slot.taken += take
            if key is not None:
                cap_left[key] -= take
            if left is not None:
                left -= take
            plan.append((slot, take))
        return plan

    def _cap_used(self, payer: Payer) -> int:
        """Settled draws in the cap window plus open holds, for this payer's cap (§5.6)."""
        base = (
            sa.select(sa.func.coalesce(sa.func.sum(UsageEntry.units), 0))
            .join(UsageGrant, UsageGrant.id == UsageEntry.grant_id)
            .where(
                UsageGrant.owner_user_id == payer.owner_user_id,
                UsageEntry.teacher_member_id == payer.teacher_member_id,
            )
        )
        settled = base.where(UsageEntry.kind == UsageEntryKind.settle)
        if payer.cap_window_start is not None:
            settled = settled.where(UsageEntry.event_at >= payer.cap_window_start)
        held = base.where(UsageEntry.kind.in_(HELD_KINDS))
        return -int(self._session.scalar(settled) or 0) + int(self._session.scalar(held) or 0)

    def _open_debt(
        self, owner_user_id: uuid.UUID, units: int, *, job_id: uuid.UUID | None = None
    ) -> UsageDebt:
        """Insert a fully outstanding debt row.

        ``created_at`` is the DB's ``clock_timestamp()``, not the transaction-start
        ``now()`` default: debts created in one transaction would tie, and
        :meth:`_open_debts` repays oldest first.
        """
        debt = UsageDebt(
            owner_user_id=owner_user_id,
            job_id=job_id,
            units=units,
            outstanding=units,
            created_at=sa.func.clock_timestamp(),
        )
        self._session.add(debt)
        self._session.flush()
        return debt

    def _open_debts(self, owner_user_id: uuid.UUID) -> Sequence[UsageDebt]:
        return self._session.scalars(
            sa.select(UsageDebt)
            .where(UsageDebt.owner_user_id == owner_user_id, UsageDebt.outstanding > 0)
            .order_by(UsageDebt.created_at, UsageDebt.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()

    def _entry(
        self,
        *,
        kind: UsageEntryKind,
        units: int,
        event_at: datetime,
        key: str,
        grant_id: uuid.UUID | None = None,
        debt_id: uuid.UUID | None = None,
        job: UsageJob | None = None,
        payer: Payer | None = None,
        reason: str | None = None,
        member: uuid.UUID | None | _Member = _Member.FROM_PAYER_OR_JOB,
    ) -> None:
        if isinstance(member, _Member):
            member = payer.teacher_member_id if payer is not None else None
            if member is None and job is not None:
                member = job.teacher_member_id
        self._session.add(
            UsageEntry(
                grant_id=grant_id,
                job_id=job.job_id if job is not None else None,
                debt_id=debt_id,
                teacher_member_id=member,
                kind=kind,
                units=units,
                rate_version=job.rate_version if job is not None else None,
                event_at=event_at,
                idempotency_key=key,
                reason=reason,
            )
        )

    def reserve(
        self,
        *,
        job_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        action: str,
        payers: Sequence[Payer],
        estimate_low: int,
        estimate_high: int,
        estimator_version: int,
        rate_version: int,
        teacher_member_id: uuid.UUID | None,
        expires_at: datetime,
        now: datetime,
    ) -> UsageJob:
        """Hold ``estimate_high`` across the chain and open the job (§5.7 step 3)."""
        if not payers:
            raise ValueError("payers must not be empty")
        if not 0 <= estimate_low <= estimate_high:
            raise ValueError("need 0 <= estimate_low <= estimate_high")
        if expires_at <= now:
            raise ValueError("expires_at must be after now")
        self._lock_owners([p.owner_user_id for p in payers])
        slots = self._slots(payers, now=now, lock=True)
        plan = self._walk(slots, estimate_high, payers, now=now)
        covered = sum(take for _slot, take in plan)
        if covered < estimate_high:
            raise InsufficientBalance(available=covered, required=estimate_high)
        job = UsageJob(
            job_id=job_id,
            actor_user_id=actor_user_id,
            teacher_member_id=teacher_member_id,
            action=action,
            estimate_low=estimate_low,
            estimate_high=estimate_high,
            estimator_version=estimator_version,
            reserved=estimate_high,
            charged=0,
            debt_created=0,
            rate_version=rate_version,
            payer_chain=[payer_to_json(p) for p in payers],
            status=UsageJobStatus.open,
            expires_at=expires_at,
        )
        self._session.add(job)
        self._session.flush()
        for slot, take in plan:
            self._entry(
                kind=UsageEntryKind.hold,
                units=take,
                event_at=now,
                key=f"job:{job_id}",
                grant_id=slot.grant.id,
                job=job,
                payer=slot.payer,
            )
            slot.balance.held += take
        self._session.flush()
        return job

    def release(self, job_id: uuid.UUID, *, now: datetime) -> UsageJob:
        """Free every hold of a failed job at no charge (§5.7 step 6)."""
        return self._close(job_id, UsageJobStatus.released, now)[0]

    def extend(self, job_id: uuid.UUID, *, expires_at: datetime, now: datetime) -> UsageJob:
        """Restart an open job's hold clock when its work starts (queued work, §5.7 step 7).

        Moves ``expires_at`` later on an open job and touches nothing else: no amount,
        hold, entry or balance changes, and a deadline never moves earlier. A job that is
        no longer open (the sweeper expired it, or it was released or settled) is returned
        unchanged, so the caller can see the hold is gone and reserve again. Takes the same
        owner and job locks as :meth:`expire_stale_jobs`, which re-checks the deadline
        under them, so an extend and a sweep never both win.
        """
        if expires_at <= now:
            raise ValueError("expires_at must be after now")
        job, _payers = self._locked_job(job_id)
        if job.status is UsageJobStatus.open and expires_at > job.expires_at:
            job.expires_at = expires_at
            self._session.flush()
        return job

    def expire_stale_jobs(self, *, now: datetime, limit: int = DEFAULT_SWEEP_LIMIT) -> int:
        """Release open jobs past ``expires_at`` and mark them expired; returns how many.

        :meth:`sweep_stale_jobs`, reporting only the jobs this pass closed.
        """
        return self.sweep_stale_jobs(now=now, limit=limit).expired

    def sweep_stale_jobs(self, *, now: datetime, limit: int = DEFAULT_SWEEP_LIMIT) -> StaleJobSweep:
        """Release open jobs past ``expires_at`` and mark them expired (§5.7 step 7).

        Takes at most ``limit`` jobs, oldest deadline first. The candidates are read
        without locks; each one's deadline is checked again under its locks, so a job
        whose clock :meth:`extend` restarted meanwhile is skipped.

        Each job closes in its own savepoint, so one bad row never stops the sweep:

        * a job whose stored chain no longer reaches a grant it holds units on
          (:class:`StrandedHolds`) has every hold released on the grant that holds it
          (a release needs no chain; only a charge does), is marked expired, and raises an
          error-level ``usage_job_stranded_holds`` alert naming it;
        * any other failure rolls that job back alone, leaves it open, and raises a
          ``usage_expire_job_failed`` alert. Its deadline steps back by
          :data:`FAILED_EXPIRY_BACKOFF`, so a job that keeps failing is retried hourly
          instead of pinning the head of every batch.

        The result counts the candidates read (failures included, so a batch full of
        failures still reads as full), the jobs closed, and the jobs that failed.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        rows = self._session.execute(
            sa.select(UsageJob.job_id, UsageJob.payer_chain)
            .where(UsageJob.status == UsageJobStatus.open, UsageJob.expires_at <= now)
            .order_by(UsageJob.expires_at, UsageJob.job_id)
            .limit(limit)
        ).all()
        job_ids = [job_id for job_id, _chain in rows]
        # One sorted pass over every owner involved, before any row is locked: closing the
        # jobs one by one would otherwise take owner locks in expiry order and deadlock
        # with a reserve that takes them in ascending UUID order. The owners of the grants
        # the jobs hold are included, so a stranded job's holds can be released in place.
        held_owners = (
            self._session.scalars(
                sa.select(UsageGrant.owner_user_id)
                .join(UsageEntry, UsageEntry.grant_id == UsageGrant.id)
                .where(UsageEntry.job_id.in_(job_ids), UsageEntry.kind.in_(HELD_KINDS))
                .distinct()
            ).all()
            if job_ids
            else []
        )
        # Each chain is parsed under its own guard: one unreadable row must not stop the
        # sweep. Such a job is never closed (its owners are unknown, so it cannot be locked
        # safely); it is alerted, counted as failed and stepped back like any other failure.
        owners: list[uuid.UUID] = list(held_owners)
        unreadable: set[uuid.UUID] = set()
        for job_id, chain in rows:
            try:
                chain_owners = [payer_from_json(p).owner_user_id for p in chain]
            except Exception:
                unreadable.add(job_id)
                continue
            owners.extend(chain_owners)
        self._lock_owners(owners)
        expired = 0
        failed: list[uuid.UUID] = []
        for job_id in job_ids:
            if job_id in unreadable:
                alerts.error(
                    "usage_expire_job_failed",
                    alert=True,
                    job_id=str(job_id),
                    reason="unreadable payer chain",
                )
                failed.append(job_id)
                self._step_back(job_id, now)
                continue
            try:
                closed = self._expire_one(job_id, now)
            except Exception:
                alerts.error(
                    "usage_expire_job_failed", alert=True, job_id=str(job_id), exc_info=True
                )
                failed.append(job_id)
                self._step_back(job_id, now)
                continue
            # Count only the jobs this sweep closed: another transaction may have
            # released, settled, extended or expired one between the candidate read
            # and the lock.
            if closed:
                expired += 1
        return StaleJobSweep(candidates=len(job_ids), expired=expired, failed=tuple(failed))

    def _step_back(self, job_id: uuid.UUID, now: datetime) -> None:
        """Move a job whose expiry failed behind the batch; never moves a deadline earlier.

        Touches only the job row, so it needs no owner lock (an unreadable chain names none).
        """
        try:
            with self._session.begin_nested():
                self._session.execute(
                    sa.update(UsageJob)
                    .where(UsageJob.job_id == job_id, UsageJob.status == UsageJobStatus.open)
                    .values(
                        expires_at=sa.func.greatest(
                            UsageJob.expires_at, now + FAILED_EXPIRY_BACKOFF
                        )
                    )
                )
        except Exception:
            alerts.error(
                "usage_expire_step_back_failed", alert=True, job_id=str(job_id), exc_info=True
            )

    def _expire_one(self, job_id: uuid.UUID, now: datetime) -> bool:
        """Expire one stale job in its own savepoint; True when this call closed it."""
        try:
            with self._session.begin_nested():
                return self._close(job_id, UsageJobStatus.expired, now, due_by=now)[1]
        except StrandedHolds as exc:
            return self._expire_stranded(exc, now)

    def _expire_stranded(self, exc: StrandedHolds, now: datetime) -> bool:
        """Release a stranded job's holds on the grants that hold them, and expire it.

        The caller holds the owner locks of the job's chain and of every grant it holds.
        Each release carries the member its hold entry carried: a seat cap counts holds
        and releases by ``teacher_member_id``, so a release filed under another member
        would leave that cap used up for good.
        """
        job_id = exc.job_id
        with self._session.begin_nested():
            job, _payers = self._locked_job(job_id)
            # Defensive: the first savepoint re-checked the deadline under the job lock,
            # and the sweep's owner locks keep ``extend`` out until it commits.
            if job.status is not UsageJobStatus.open or job.expires_at > now:
                return False
            holds = self._job_holds_by_member(job_id)
            per_grant: dict[uuid.UUID, int] = defaultdict(int)
            for grant_id, _member in holds:
                per_grant[grant_id] += 1
            balances = {grant_id: self._locked_balance(grant_id) for grant_id in sorted(per_grant)}
            for (grant_id, member), held in sorted(
                holds.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))
            ):
                # One hold per grant is the normal shape and keeps the usual key; a grant
                # held under two members needs one key per member (one entry per key).
                key = f"job:{job_id}" if per_grant[grant_id] == 1 else f"job:{job_id}:{member}"
                self._entry(
                    kind=UsageEntryKind.release,
                    units=-held,
                    event_at=now,
                    key=key,
                    grant_id=grant_id,
                    job=job,
                    member=member,
                )
                balances[grant_id].held -= held
            job.status = UsageJobStatus.expired
            self._session.flush()
        alerts.error(
            "usage_job_stranded_holds",
            alert=True,
            job_id=str(job_id),
            grant_ids=[str(g) for g in sorted(exc.grant_ids)],
            released_units=sum(holds.values()),
        )
        return True

    def _job_holds_by_member(
        self, job_id: uuid.UUID
    ) -> dict[tuple[uuid.UUID, uuid.UUID | None], int]:
        """A job's units still held, by grant and by the member each hold was counted under."""
        rows = self._session.execute(
            sa.select(
                UsageEntry.grant_id, UsageEntry.teacher_member_id, sa.func.sum(UsageEntry.units)
            )
            .where(UsageEntry.job_id == job_id, UsageEntry.kind.in_(HELD_KINDS))
            .group_by(UsageEntry.grant_id, UsageEntry.teacher_member_id)
        ).all()
        return {
            (grant_id, member): int(total)
            for grant_id, member, total in rows
            if grant_id is not None and total
        }

    def _locked_job(self, job_id: uuid.UUID) -> tuple[UsageJob, list[Payer]]:
        chain = self._session.scalar(
            sa.select(UsageJob.payer_chain).where(UsageJob.job_id == job_id)
        )
        if chain is None:
            raise LookupError(f"no usage job {job_id}")
        payers = [payer_from_json(p) for p in chain]
        self._lock_owners([p.owner_user_id for p in payers])
        job = self._session.scalars(
            sa.select(UsageJob)
            .where(UsageJob.job_id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        return job, payers

    def _job_holds(self, job_id: uuid.UUID) -> dict[uuid.UUID, int]:
        rows = self._session.execute(
            sa.select(UsageEntry.grant_id, sa.func.sum(UsageEntry.units))
            .where(UsageEntry.job_id == job_id, UsageEntry.kind.in_(HELD_KINDS))
            .group_by(UsageEntry.grant_id)
        ).all()
        return {gid: int(total) for gid, total in rows if gid is not None and total}

    def _close(
        self,
        job_id: uuid.UUID,
        status: UsageJobStatus,
        now: datetime,
        *,
        due_by: datetime | None = None,
    ) -> tuple[UsageJob, bool]:
        """Release every hold and move an open job to ``status``.

        Returns the job and whether this call changed it: a job that is no longer
        open (closed by a concurrent transaction) is left alone and reported as
        unchanged. With ``due_by`` (the sweeper), so is a job whose deadline, read
        under the lock, is later than ``due_by``.
        """
        job, payers = self._locked_job(job_id)
        if job.status is not UsageJobStatus.open:
            return job, False
        if due_by is not None and job.expires_at > due_by:
            return job, False
        holds = self._job_holds(job_id)
        slots = self._slots(payers, now=now, lock=True, include=set(holds))
        self._require_reachable(job_id, holds, slots)
        for slot in slots:
            if held := holds.get(slot.grant.id, 0):
                self._release_slot(slot, held, job, now)
        job.status = status
        self._session.flush()
        return job, True

    @staticmethod
    def _require_reachable(
        job_id: uuid.UUID, holds: dict[uuid.UUID, int], slots: Sequence[_Slot]
    ) -> None:
        """Raise before any write when the chain cannot reach a grant the job holds."""
        reached = {slot.grant.id for slot in slots}
        if stranded := set(holds) - reached:
            raise StrandedHolds(job_id, stranded)

    def settle(self, job_id: uuid.UUID, *, actual_cost_usd: Decimal, now: datetime) -> UsageJob:
        """Charge the actual cost (§5.7 step 5). A job no longer open is returned unchanged.

        Holds are released and charged first, in chain order; any rest keeps drawing
        down the stored chain (skipping indebted non-exempt payers, within caps); what
        is still left becomes a debt on the payer of last resort. Takes the same
        owner and job locks as :meth:`release`, so a concurrent release or sweep either
        finishes first (settle is then a no-op) or waits for this one.

        ``actual_cost_usd`` is quantized to 6 decimal places (half up) first, so the
        stored USD and the units charged always agree; a negative cost raises
        ``ValueError`` before that rounding. ``job.charged`` is the actual
        cost in units; the amount drawn from grants is ``charged - debt_created``.
        """
        if actual_cost_usd < 0:  # before quantizing: -0.0000001 would round to zero
            raise ValueError("actual_cost_usd must be >= 0")
        job, payers = self._locked_job(job_id)
        if job.status is not UsageJobStatus.open:
            return job
        units_per_usd = self._session.scalar(
            sa.select(UsageRate.units_per_usd).where(
                UsageRate.version == job.rate_version, UsageRate.action == job.action
            )
        )
        if units_per_usd is None:
            raise LookupError(f"no usage rate for version {job.rate_version}, {job.action!r}")
        actual_cost_usd = actual_cost_usd.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        need = usd_to_units(actual_cost_usd, units_per_usd)
        charged = need
        holds = self._job_holds(job_id)
        slots = self._slots(payers, now=now, lock=True, include=set(holds))
        self._require_reachable(job_id, holds, slots)
        settled: dict[uuid.UUID, int] = defaultdict(int)
        # Release every hold, then charge the held grants first, in chain order.
        for slot in slots:
            held = holds.get(slot.grant.id, 0)
            if held == 0:
                continue
            self._release_slot(slot, held, job, now)
            take = min(held, need)
            if take:
                slot.taken += take
                settled[slot.grant.id] += take
                need -= take
        if need:
            # The cap query must see the release entries just staged, not rely on autoflush.
            self._session.flush()
            for slot, take in self._walk(slots, need, payers, now=now, after_release=True):
                settled[slot.grant.id] += take
                need -= take
        if need:
            self._create_debt(payers[-1].owner_user_id, need, job, now)
        for slot in slots:
            amount = settled.get(slot.grant.id, 0)
            if amount:
                self._entry(
                    kind=UsageEntryKind.settle,
                    units=-amount,
                    event_at=now,
                    key=f"job:{job_id}",
                    grant_id=slot.grant.id,
                    job=job,
                    payer=slot.payer,
                )
                slot.balance.remaining -= amount
        job.status = UsageJobStatus.settled
        job.charged = charged
        job.debt_created = need
        job.actual_cost_usd = actual_cost_usd
        job.settled_at = now
        self._session.flush()
        return job

    def _create_debt(
        self, owner_user_id: uuid.UUID, units: int, job: UsageJob, now: datetime
    ) -> None:
        debt = self._open_debt(owner_user_id, units, job_id=job.job_id)
        self._entry(
            kind=UsageEntryKind.debt,
            units=-units,
            event_at=now,
            key=f"job:{job.job_id}",
            debt_id=debt.id,
            job=job,
        )

    def _release_slot(self, slot: _Slot, held: int, job: UsageJob, now: datetime) -> None:
        self._entry(
            kind=UsageEntryKind.release,
            units=-held,
            event_at=now,
            key=f"job:{job.job_id}",
            grant_id=slot.grant.id,
            job=job,
            payer=slot.payer,
        )
        slot.balance.held -= held

    def expire_grants(self, *, now: datetime, limit: int = DEFAULT_SWEEP_LIMIT) -> int:
        """Expire the unheld rest of every grant past ``expires_at`` (§5.7 step 8).

        Takes at most ``limit`` grants, oldest expiry first; the rest wait for the next
        pass. Units a running job still holds stay on the grant; the sweep after that
        job lets them go takes them. Each grant expires in its own savepoint: one that
        fails is rolled back alone, alerted (``usage_expire_grant_failed``) and skipped.
        Returns the number of grants given an ``expire`` entry.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        candidates = self._session.execute(
            sa.select(UsageGrant.id, UsageGrant.owner_user_id)
            .join(UsageGrantBalance, UsageGrantBalance.grant_id == UsageGrant.id)
            .where(
                UsageGrant.expires_at <= now,
                UsageGrantBalance.remaining > UsageGrantBalance.held,
            )
            .order_by(UsageGrant.expires_at, UsageGrant.id)
            .limit(limit)
        ).all()
        # One sorted pass over every owner involved, before any grant row is
        # locked: taking owner locks grant by grant, in expiry order, would
        # deadlock with a reserve that takes them in ascending UUID order.
        self._lock_owners([owner_user_id for _, owner_user_id in candidates])
        expired = 0
        for grant_id, _owner in candidates:
            try:
                with self._session.begin_nested():
                    done = self._expire_grant(grant_id, now)
            except Exception:
                alerts.error(
                    "usage_expire_grant_failed", alert=True, grant_id=str(grant_id), exc_info=True
                )
                continue
            if done:
                expired += 1
        self._session.flush()
        return expired

    def _expire_grant(self, grant_id: uuid.UUID, now: datetime) -> bool:
        """Expire one grant's unheld rest (owner lock held); True when it wrote an entry."""
        # Re-read under the lock: another transaction may have spent, held or
        # clawed back or re-dated the grant between the candidate read and the lock.
        balance, expires_at = self._locked_balance_and_expiry(grant_id)
        amount = balance.remaining - balance.held
        if amount <= 0 or expires_at is None or expires_at > now:
            return False
        count = self._entry_count(grant_id, UsageEntryKind.expire)
        self._entry(
            kind=UsageEntryKind.expire,
            units=-amount,
            event_at=now,
            key=f"expire:{count}",
            grant_id=grant_id,
        )
        balance.remaining -= amount
        self._session.flush()
        return True

    def claw_back_grant(self, grant_id: uuid.UUID, *, reason: str, now: datetime) -> int:
        """Remove a refunded grant's unspent, unheld units; spent units stay spent (§6).

        The return value is the units refunded by this call. Units a running job
        still holds are not counted: they stay on the grant until the job lets
        them go, then :meth:`expire_grants` removes them as ``expire`` entries
        (or a later call removes them as a ``refund`` entry, when none was
        written yet). To make that safe the grant is always closed: ``expires_at``
        becomes ``max(now, effective_at + 1 microsecond)`` unless it is already
        earlier, so released units are never spendable again. A second call
        after a refund entry exists returns 0.
        """
        grant = self._session.get(UsageGrant, grant_id)
        if grant is None:
            raise LookupError(f"no usage grant {grant_id}")
        self._lock_owners([grant.owner_user_id])
        balance = self._locked_balance(grant_id)
        if self._entry_count(grant_id, UsageEntryKind.refund):
            return 0
        amount = max(balance.remaining - balance.held, 0)
        # The CHECK needs expires_at > effective_at, so a grant that starts at or
        # after ``now`` is closed one microsecond past its start.
        close_at = max(now, grant.effective_at + timedelta(microseconds=1))
        if grant.expires_at is None or grant.expires_at > close_at:
            grant.expires_at = close_at
        if amount:
            self._entry(
                kind=UsageEntryKind.refund,
                units=-amount,
                event_at=now,
                key="claw_back",
                grant_id=grant_id,
                reason=reason,
            )
            balance.remaining -= amount
        self._session.flush()
        return amount

    def extend_grant_expiry(
        self,
        grant_id: uuid.UUID,
        *,
        expires_at: datetime,
        now: datetime,
        issued_expires_at: datetime | None = None,
    ) -> UsageGrant:
        """Keep a grant's leftover usable until ``expires_at`` (a plan's failed-renewal grace).

        Moves ``expires_at`` later and touches nothing else: no entry is written and no balance
        changes, so a lapse loses nothing and a grace period grants nothing. An expiry never moves
        earlier (a grant already expiring later, or never, is returned as it is), so a repeat is a
        no-op.

        A grant whose ``expires_at`` has passed can still be extended while the expiry sweep has
        not processed it: Paymob charges a renewal at the period end, so its failure usually
        arrives at or after the end. Once the sweep has taken the leftover (an ``expire`` entry) or
        a claw-back refunded it (a ``refund`` entry), it is not reopened. A claw-back that found
        nothing unheld to refund closes the grant by moving ``expires_at`` earlier and leaves no
        entry, and the grant row records no closure, so a lapsed grant is extended only when the
        caller states the expiry the grant was issued with (``issued_expires_at``) and the grant
        still carries it: an expiry that was moved is never reopened. One gap remains: a claw-back
        of a grant that had already lapsed (and was not yet swept) while all its units were held
        leaves ``expires_at`` at the issued value and writes no entry, so such a grant can still
        be extended. Closing it needs a durable closure marker on the grant (a schema change),
        or ``claw_back_grant`` stamping ``expires_at`` even when it is already earlier. The
        owner lock and the
        balance row lock are the ones :meth:`expire_grants` takes, and the grant is re-read under
        them, so an extend and a sweep never both win: a sweep queued behind an extend finds the
        expiry moved and skips the grant; an extend queued behind a sweep finds it expired.

        Raises:
            GrantAlreadyExpired: the grant lapsed and the sweep or a claw-back took it, or it
                lapsed and ``issued_expires_at`` is not given or is not its current expiry.
            ValueError: ``expires_at`` is not after ``now``.
            LookupError: no such grant.
        """
        if expires_at <= now:
            raise ValueError("expires_at must be after now")
        grant = self._session.get(UsageGrant, grant_id)
        if grant is None:
            raise LookupError(f"no usage grant {grant_id}")
        self._lock_owners([grant.owner_user_id])
        self._locked_balance(grant_id)
        self._session.refresh(grant)
        if grant.expires_at is None:
            return grant
        if grant.expires_at <= now and (
            issued_expires_at is None
            or grant.expires_at != issued_expires_at
            or self._entry_count(grant_id, UsageEntryKind.expire)
            or self._entry_count(grant_id, UsageEntryKind.refund)
        ):
            raise GrantAlreadyExpired(f"usage grant {grant_id} already expired")
        if expires_at > grant.expires_at:
            grant.expires_at = expires_at
            self._session.flush()
        return grant

    def shorten_grant_expiry(self, grant_id: uuid.UUID, *, expires_at: datetime) -> UsageGrant:
        """End a grant's usability at ``expires_at`` (undoing :meth:`extend_grant_expiry`).

        Moves ``expires_at`` earlier and touches nothing else: no entry, no balance change. A
        value in the past makes the leftover unusable at once and leaves it for
        :meth:`expire_grants` to take. An expiry never moves later, and one is never set at or
        before ``effective_at`` (the table's check), so a repeat is a no-op. A call that would
        move nothing returns before taking any lock (it is on the renewal and expiry paths, where
        a ledger lock must not be taken needlessly: see the lock order of the subscription
        module); one that moves it takes the locks of :meth:`extend_grant_expiry` and
        :meth:`expire_grants` and decides again under them.

        Raises:
            LookupError: no such grant.
        """
        # A fresh, lock-free read of the columns (not the identity map's possibly stale entity).
        row = self._session.execute(
            sa.select(
                UsageGrant.owner_user_id, UsageGrant.effective_at, UsageGrant.expires_at
            ).where(UsageGrant.id == grant_id)
        ).one_or_none()
        if row is None:
            raise LookupError(f"no usage grant {grant_id}")
        owner_user_id, effective_at, current = row
        target = max(expires_at, effective_at + timedelta(microseconds=1))
        grant = self._session.get_one(UsageGrant, grant_id)
        if current is not None and target >= current:
            return grant  # nothing to move: no lock taken
        self._lock_owners([owner_user_id])
        self._locked_balance(grant_id)
        self._session.refresh(grant)
        if grant.expires_at is None or target < grant.expires_at:
            grant.expires_at = target
            self._session.flush()
        return grant

    def adjust(
        self,
        *,
        owner_user_id: uuid.UUID,
        units: int,
        reason: str,
        idempotency_key: str,
        now: datetime,
    ) -> None:
        """Admin correction: ``+units`` grants, ``-units`` debits.

        ``+units`` issues a visible ``adjustment`` grant (which repays debt
        first). ``-units`` debits the owner's own allowance and credits in spend
        order, never a seat grant (the teacher's money); whatever they cannot
        cover becomes a job-less ``usage_debts`` row on the owner, because a
        negative balance exists only as debt (§6). Idempotent on the key.
        """
        if units == 0:
            raise ValueError("units must not be 0")
        if units > 0:
            self._lock_owners([owner_user_id])
            if (stored := self._recorded_debit(owner_user_id, idempotency_key)) is not None:
                self._warn_adjust_replay(owner_user_id, idempotency_key, units, reason, *stored)
                return
            self._issue(
                owner_user_id=owner_user_id,
                kind=GrantKind.adjustment,
                units=units,
                idempotency_key=idempotency_key,
                expires_at=None,
                visible=True,
                effective_at=now,
                payment_id=None,
                subscription_period_id=None,
                teacher_member_id=None,
                reason=reason,
            )
            return
        self._lock_owners([owner_user_id])
        if (stored := self._recorded_debit(owner_user_id, idempotency_key)) is not None:
            self._warn_adjust_replay(owner_user_id, idempotency_key, units, reason, *stored)
            return
        if (credit := self._credit_for_key(owner_user_id, idempotency_key)) is not None:
            self._warn_adjust_replay(
                owner_user_id, idempotency_key, units, reason, credit.units, None
            )
            return
        own = [
            Payer(owner_user_id=owner_user_id, scope=GrantScope.ALLOWANCE),
            Payer(owner_user_id=owner_user_id, scope=GrantScope.CREDITS),
        ]
        # Plan the whole debit before staging a single entry.
        need = -units
        plan: list[tuple[_Slot, int]] = []
        for slot in self._slots(own, now=now, lock=True):
            take = min(max(slot.free, 0), need)
            if take:
                plan.append((slot, take))
                need -= take
        for slot, take in plan:
            self._entry(
                kind=UsageEntryKind.adjust,
                units=-take,
                event_at=now,
                key=idempotency_key,
                grant_id=slot.grant.id,
                reason=reason,
            )
            slot.balance.remaining -= take
        if need:
            debt = self._open_debt(owner_user_id, need)
            self._entry(
                kind=UsageEntryKind.debt,
                units=-need,
                event_at=now,
                key=idempotency_key,
                debt_id=debt.id,
                reason=reason,
            )
        self._session.flush()

    def _credit_for_key(self, owner_user_id: uuid.UUID, idempotency_key: str) -> UsageGrant | None:
        """The owner's ``adjustment`` grant issued under this key (a positive adjust's record)."""
        return self._session.scalars(
            sa.select(UsageGrant).where(
                UsageGrant.owner_user_id == owner_user_id,
                UsageGrant.idempotency_key == idempotency_key,
                UsageGrant.kind == GrantKind.adjustment,
            )
        ).one_or_none()

    def _recorded_debit(
        self, owner_user_id: uuid.UUID, idempotency_key: str
    ) -> tuple[int, str | None] | None:
        """``(signed units, reason)`` of a negative adjust already recorded under this key.

        A negative adjust writes ``adjust`` entries on grants and/or a ``debt``
        entry; the units are their sum (negative). ``None`` when there are none.
        """
        on_grant = (
            sa.select(UsageEntry.units, UsageEntry.reason)
            .join(UsageGrant, UsageGrant.id == UsageEntry.grant_id)
            .where(
                UsageGrant.owner_user_id == owner_user_id,
                UsageEntry.kind == UsageEntryKind.adjust,
                UsageEntry.idempotency_key == idempotency_key,
            )
        )
        on_debt = (
            sa.select(UsageEntry.units, UsageEntry.reason)
            .join(UsageDebt, UsageDebt.id == UsageEntry.debt_id)
            .where(
                UsageDebt.owner_user_id == owner_user_id,
                UsageEntry.kind == UsageEntryKind.debt,
                UsageEntry.idempotency_key == idempotency_key,
            )
        )
        rows = self._session.execute(on_grant.union_all(on_debt)).all()
        if not rows:
            return None
        return sum(int(u) for u, _ in rows), rows[0][1]

    @staticmethod
    def _warn_adjust_replay(
        owner_user_id: uuid.UUID,
        idempotency_key: str,
        units: int,
        reason: str,
        stored_units: int,
        stored_reason: str | None,
    ) -> None:
        """Log a replay that is not identical to the stored adjustment (the call is a no-op)."""
        if stored_units != units or stored_reason != reason:
            logger.warning(
                "adjust replay under key %r for owner %s differs from the stored adjustment "
                "(units %d vs %d, reason %r vs %r); ignoring it",
                idempotency_key,
                owner_user_id,
                units,
                stored_units,
                reason,
                stored_reason,
            )

    def forgive_debt(
        self, owner_user_id: uuid.UUID, *, units: int | None, reason: str, now: datetime
    ) -> int:
        """Forgive up to ``units`` of debt, oldest first (``None`` = all); return units forgiven."""
        if units is not None and units <= 0:
            raise ValueError("units must be > 0 or None")
        self._lock_owners([owner_user_id])
        left = units
        forgiven = 0
        for debt in self._open_debts(owner_user_id):
            amount = debt.outstanding if left is None else min(debt.outstanding, left)
            if amount == 0:
                break
            count = self._session.scalar(
                sa.select(sa.func.count()).where(
                    UsageEntry.debt_id == debt.id,
                    UsageEntry.grant_id.is_(None),
                    UsageEntry.kind == UsageEntryKind.adjust,
                )
            )
            self._entry(
                kind=UsageEntryKind.adjust,
                units=amount,
                event_at=now,
                key=f"forgive:{count}",
                debt_id=debt.id,
                reason=reason,
            )
            debt.outstanding -= amount
            forgiven += amount
            if left is not None:
                left -= amount
        self._session.flush()
        return forgiven

    def _locked_balance(self, grant_id: uuid.UUID) -> UsageGrantBalance:
        return self._session.scalars(
            sa.select(UsageGrantBalance)
            .where(UsageGrantBalance.grant_id == grant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()

    def _locked_balance_and_expiry(
        self, grant_id: uuid.UUID
    ) -> tuple[UsageGrantBalance, datetime | None]:
        """The locked balance row with the grant's ``expires_at``, in one statement."""
        row = self._session.execute(
            sa.select(UsageGrantBalance, UsageGrant.expires_at)
            .join(UsageGrant, UsageGrant.id == UsageGrantBalance.grant_id)
            .where(UsageGrantBalance.grant_id == grant_id)
            .with_for_update(of=UsageGrantBalance)
            .execution_options(populate_existing=True)
        ).one()
        return row[0], row[1]

    def _entry_count(self, grant_id: uuid.UUID, kind: UsageEntryKind) -> int:
        return int(
            self._session.scalar(
                sa.select(sa.func.count()).where(
                    UsageEntry.grant_id == grant_id, UsageEntry.kind == kind
                )
            )
            or 0
        )

    def reconcile_balances(self) -> list[tuple[uuid.UUID, int, int]]:
        """Rebuild the cache from the entries; return every drift as ``(id, cached, actual)``.

        One tuple per drifted value: a grant's ``remaining``, a grant's ``held``
        (both keyed by grant id) and a debt's ``outstanding`` (keyed by debt id),
        then the cache is repaired. Finding drift means a bug, not a race, since
        entries and cache change together under the owner locks.

        The first scan reads without locks and finds the suspects. Their owners
        are then locked once, in ascending UUID order, before any balance or debt
        row is: the order every other writer uses, so a reserve over the same
        owners cannot deadlock with this sweep. Under those locks each suspect is
        re-read and recomputed, so a write that landed after the scan is not
        reported.
        """
        grants = [row[0] for row in self._grant_sums() if row[1:3] != row[3:5]]
        drifted_debts = [row[0] for row in self._debt_sums() if row[1] != row[2]]
        if not grants and not drifted_debts:
            return []
        self._lock_owners(self._owners_of(grants, drifted_debts))
        drift: list[tuple[uuid.UUID, int, int]] = []
        for grant_id in grants:
            balance = self._locked_balance(grant_id)
            [(_gid, _rem, _held, actual_rem, actual_held)] = self._grant_sums(grant_id)
            found: list[tuple[uuid.UUID, int, int]] = []
            if balance.remaining != actual_rem:
                found.append((grant_id, balance.remaining, actual_rem))
            if balance.held != actual_held:
                found.append((grant_id, balance.held, actual_held))
            if not found:
                continue
            drift.extend(found)
            savepoint = self._session.begin_nested()  # before the change: it flushes first
            balance.remaining, balance.held = actual_rem, actual_held
            self._flush_or_skip(savepoint, f"grant balance {grant_id}", balance)
        for debt_id in drifted_debts:
            debt = self._session.scalars(
                sa.select(UsageDebt)
                .where(UsageDebt.id == debt_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).one()
            [(_did, _cached, actual_out)] = self._debt_sums(debt_id)
            if debt.outstanding != actual_out:
                drift.append((debt_id, debt.outstanding, actual_out))
                savepoint = self._session.begin_nested()  # before the change: it flushes first
                debt.outstanding = actual_out
                self._flush_or_skip(savepoint, f"debt {debt_id}", debt)
        return drift

    def _flush_or_skip(
        self, savepoint: SessionTransaction, what: str, row: UsageGrantBalance | UsageDebt
    ) -> None:
        """Flush the repair staged on ``row`` since ``savepoint`` began; undo it if rejected.

        A recomputed value can break a CHECK (held above remaining when a stray
        hold entry exists). That row stays as it was, the error is logged naming
        it, and the sweep goes on: one bad row must not leave the rest of the
        cache drifted. Its drift is still reported by the caller.
        """
        try:
            self._session.flush()
        except IntegrityError:
            savepoint.rollback()
            self._session.expire(row)  # drop the rejected value, or the next autoflush retries it
            logger.error(
                "reconcile could not repair %s: the value recomputed from its entries "
                "violates a constraint; left unrepaired",
                what,
                exc_info=True,
            )
        else:
            savepoint.commit()

    def _owners_of(
        self, grant_ids: Sequence[uuid.UUID], debt_ids: Sequence[uuid.UUID]
    ) -> list[uuid.UUID]:
        return list(
            self._session.scalars(
                sa.select(UsageGrant.owner_user_id)
                .where(UsageGrant.id.in_(grant_ids))
                .union(sa.select(UsageDebt.owner_user_id).where(UsageDebt.id.in_(debt_ids)))
            )
        )

    def _grant_sums(
        self, grant_id: uuid.UUID | None = None
    ) -> list[tuple[uuid.UUID, int, int, int, int]]:
        """``(grant, cached remaining, cached held, remaining from entries, held from entries)``."""
        remaining = sa.func.coalesce(
            sa.func.sum(sa.case((UsageEntry.kind.in_(REMAINING_KINDS), UsageEntry.units), else_=0)),
            0,
        )
        held = sa.func.coalesce(
            sa.func.sum(sa.case((UsageEntry.kind.in_(HELD_KINDS), UsageEntry.units), else_=0)),
            0,
        )
        stmt = (
            sa.select(
                UsageGrantBalance.grant_id,
                UsageGrantBalance.remaining,
                UsageGrantBalance.held,
                remaining,
                held,
            )
            .outerjoin(UsageEntry, UsageEntry.grant_id == UsageGrantBalance.grant_id)
            .group_by(
                UsageGrantBalance.grant_id, UsageGrantBalance.remaining, UsageGrantBalance.held
            )
            .order_by(UsageGrantBalance.grant_id)
        )
        if grant_id is not None:
            stmt = stmt.where(UsageGrantBalance.grant_id == grant_id)
        return [
            (g, int(cr), int(ch), int(ar), int(ah))
            for g, cr, ch, ar, ah in self._session.execute(stmt)
        ]

    def _debt_sums(self, debt_id: uuid.UUID | None = None) -> list[tuple[uuid.UUID, int, int]]:
        """``(debt, cached outstanding, outstanding from entries)``.

        The debt's ``units`` less its repayments (``debt_repay``, negative) and
        its forgiveness (a grant-less ``adjust``, positive).
        """
        repaid = sa.func.coalesce(
            sa.func.sum(
                sa.case((UsageEntry.kind == UsageEntryKind.debt_repay, UsageEntry.units), else_=0)
            ),
            0,
        )
        forgiven = sa.func.coalesce(
            sa.func.sum(
                sa.case(
                    (
                        sa.and_(
                            UsageEntry.kind == UsageEntryKind.adjust, UsageEntry.grant_id.is_(None)
                        ),
                        UsageEntry.units,
                    ),
                    else_=0,
                )
            ),
            0,
        )
        stmt = (
            sa.select(UsageDebt.id, UsageDebt.outstanding, UsageDebt.units + repaid - forgiven)
            .outerjoin(UsageEntry, UsageEntry.debt_id == UsageDebt.id)
            .group_by(UsageDebt.id, UsageDebt.outstanding, UsageDebt.units)
            .order_by(UsageDebt.id)
        )
        if debt_id is not None:
            stmt = stmt.where(UsageDebt.id == debt_id)
        return [(d, int(c), int(a)) for d, c, a in self._session.execute(stmt)]


__all__ = [
    "DEFAULT_SWEEP_LIMIT",
    "FAILED_EXPIRY_BACKOFF",
    "HELD_KINDS",
    "REMAINING_KINDS",
    "GrantAlreadyExpired",
    "InsufficientBalance",
    "StaleJobSweep",
    "StrandedHolds",
    "UsageLedger",
]
