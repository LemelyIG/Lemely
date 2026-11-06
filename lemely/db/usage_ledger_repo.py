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
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa

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

    from sqlalchemy.orm import Session

logger = logging.getLogger("lemely.db.usage_ledger_repo")

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
            if existing.kind is not kind or existing.units != units:
                logger.warning(
                    "grant replay under key %r for owner %s differs from the stored grant "
                    "(kind %s vs %s, units %d vs %d); returning the stored grant",
                    idempotency_key,
                    owner_user_id,
                    kind.value,
                    existing.kind.value,
                    units,
                    existing.units,
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
    ) -> None:
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

    def expire_stale_jobs(self, *, now: datetime) -> int:
        """Release open jobs past ``expires_at`` and mark them expired (§5.7 step 7)."""
        rows = self._session.execute(
            sa.select(UsageJob.job_id, UsageJob.payer_chain)
            .where(UsageJob.status == UsageJobStatus.open, UsageJob.expires_at <= now)
            .order_by(UsageJob.expires_at, UsageJob.job_id)
        ).all()
        # One sorted pass over every owner involved: closing the jobs one by one
        # would otherwise take owner locks in expiry order and deadlock with a
        # reserve that takes them in ascending UUID order.
        self._lock_owners([payer_from_json(p).owner_user_id for _, chain in rows for p in chain])
        expired = 0
        for job_id, _chain in rows:
            # Count only the jobs this sweep closed: another transaction may have
            # released, settled or expired one between the candidate read and the lock.
            if self._close(job_id, UsageJobStatus.expired, now)[1]:
                expired += 1
        return expired

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
        self, job_id: uuid.UUID, status: UsageJobStatus, now: datetime
    ) -> tuple[UsageJob, bool]:
        """Release every hold and move an open job to ``status``.

        Returns the job and whether this call changed it: a job that is no longer
        open (closed by a concurrent transaction) is left alone and reported as
        unchanged.
        """
        job, payers = self._locked_job(job_id)
        if job.status is not UsageJobStatus.open:
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
            raise RuntimeError(
                f"usage job {job_id} holds units on grants {sorted(stranded)} "
                "that its payer chain no longer reaches"
            )

    def settle(self, job_id: uuid.UUID, *, actual_cost_usd: Decimal, now: datetime) -> UsageJob:
        """Charge the actual cost (§5.7 step 5). A job no longer open is returned unchanged.

        Holds are released and charged first, in chain order; any rest keeps drawing
        down the stored chain (skipping indebted non-exempt payers, within caps); what
        is still left becomes a debt on the payer of last resort. Takes the same
        owner and job locks as :meth:`release`, so a concurrent release or sweep either
        finishes first (settle is then a no-op) or waits for this one.

        ``actual_cost_usd`` is quantized to 6 decimal places (half up) first, so the
        stored USD and the units charged always agree. ``job.charged`` is the actual
        cost in units; the amount drawn from grants is ``charged - debt_created``.
        """
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


__all__ = ["HELD_KINDS", "REMAINING_KINDS", "InsufficientBalance", "UsageLedger"]
