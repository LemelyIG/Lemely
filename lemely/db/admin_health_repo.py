"""Billing health (spec §8 area 5): what ran, what failed, and how webhooks are doing.

``BILLING_JOB_NAMES`` lists the billing sweeper jobs the sweeper registers, so a job that has
never run shows as ``never_run`` instead of being absent. ``job_runs`` also holds the
notification jobs (announcements, tutoring email, streaks); those are not billing and are left
off: only a recorded name under a billing prefix is listed beyond the fixed names, which is how
a job a later phase registers appears before this list learns it. ``job_runs`` holds one row per
job name, shared by every instance: a healthy instance running ``billing.llm_price_refresh`` hides
a stale one, whose only signal is the ``llm_price_refresh_failed`` log (``alert=True`` from the
fifth failure in a row). Read-only: no audit rows.

``verified_events`` counts every stored ``paymob_events`` row in the window: callbacks and
reconcile inquiry results alike (the table records no source), so the error rate is "HMAC
failures per stored Paymob event", not a pure callback failure rate. The failure side is capped
at 60 rows a minute per process (``record_webhook_failure``), so ``hmac_failures`` undercounts
in a flood; a ``paymob_hmac_failure_unrecorded`` alert means the count is low.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
from sqlalchemy import select

from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PaymobEvent,
    PaymobEventKind,
    Subscription,
)
from lemely.db.models.billing_ops import JobRun, PaymobWebhookFailure
from lemely.db.models.enums import SubscriptionStatus
from lemely.db.subscription_repo import TRIGGER_FAILED, TRIGGER_OVERDUE

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

BILLING_JOB_NAMES: Final = (
    "admin.expire_manual_subscriptions",
    "billing.llm_price_refresh",
    "billing.prune_webhook_failures",
    "billing.reconcile_pending",
    "billing.terms_change_notices",
    "billing.terms_move_fixed_path",
    "seats.monthly_allowance",
    "seats.release_due",
    "subscriptions.drift_check",
    "subscriptions.expire_overdue",
    "subscriptions.period_end",
    "usage.expire_grants",
    "usage.expire_stale_jobs",
    "usage.reconcile_balances",
    "usage.repair_signup_grants",
)
"""Fixed names, shown as never run until a row exists. Later phases append their sweeps."""

BILLING_JOB_PREFIXES: Final = ("billing.", "usage.", "subscriptions.", "seats.", "admin.")
"""A recorded job under one of these belongs on the billing screen (DV-7)."""

_RENEWAL_FAILURES: Final = (TRIGGER_FAILED, TRIGGER_OVERDUE)
_FAILED: Final = (PaymentStatus.failed, PaymentStatus.failed_mismatch)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class JobHealth:
    name: str
    run: JobRun | None


@dataclass(frozen=True, slots=True)
class HealthReport:
    window_hours: int
    jobs: list[JobHealth]
    verified_events: int
    hmac_failures: int
    webhook_error_rate: float | None
    mismatches: int
    renewal_failure_events: int
    past_due_now: int
    failed_auto_topups: int
    failed_extra_seat_charges: int


class AdminHealthService:
    def __init__(
        self, sessionmaker: sessionmaker[Session], *, now: Callable[[], datetime] = _utcnow
    ) -> None:
        self._sm = sessionmaker
        self._now = now

    def health(self, *, hours: int) -> HealthReport:
        """The report for the last ``hours``; ``pastDueNow`` is live, not windowed."""
        since = self._now() - timedelta(hours=hours)
        with self._sm() as s:

            def count(stmt: sa.Select[tuple[int]]) -> int:
                return int(s.scalar(stmt) or 0)

            runs = {
                r.name: r
                for r in s.scalars(select(JobRun))
                if r.name in BILLING_JOB_NAMES or r.name.startswith(BILLING_JOB_PREFIXES)
            }
            names = sorted(set(BILLING_JOB_NAMES) | set(runs))
            events = count(
                select(sa.func.count())
                .select_from(PaymobEvent)
                .where(PaymobEvent.created_at >= since)
            )
            failures = count(
                select(sa.func.count())
                .select_from(PaymobWebhookFailure)
                .where(PaymobWebhookFailure.received_at >= since)
            )
            # Phase 05 stores the callback under ``payload["body"]`` (``apply_renewal_webhook``).
            renewal_failures = count(
                select(sa.func.count())
                .select_from(PaymobEvent)
                .where(
                    PaymobEvent.kind == PaymobEventKind.subscription,
                    PaymobEvent.payload["body"]["trigger_type"].as_string().in_(_RENEWAL_FAILURES),
                    PaymobEvent.created_at >= since,
                )
            )
            past_due = count(
                select(sa.func.count())
                .select_from(Subscription)
                .where(Subscription.status == SubscriptionStatus.past_due)
            )
            # One scan of the window for the three failed-payment counts (no new index).
            mismatches, auto_topups, extra_seats = s.execute(
                select(
                    sa.func.count().filter(Payment.status == PaymentStatus.failed_mismatch),
                    sa.func.count().filter(Payment.purpose == PaymentPurpose.auto_topup),
                    sa.func.count().filter(Payment.purpose == PaymentPurpose.extra_seats),
                ).where(Payment.status.in_(_FAILED), Payment.updated_at >= since)
            ).one()
            seen = events + failures
            return HealthReport(
                window_hours=hours,
                jobs=[JobHealth(name, runs.get(name)) for name in names],
                verified_events=events,
                hmac_failures=failures,
                webhook_error_rate=round(failures / seen, 4) if seen else None,
                mismatches=mismatches,
                renewal_failure_events=renewal_failures,
                past_due_now=past_due,
                failed_auto_topups=auto_topups,
                failed_extra_seat_charges=extra_seats,
            )


__all__ = [
    "BILLING_JOB_NAMES",
    "BILLING_JOB_PREFIXES",
    "AdminHealthService",
    "HealthReport",
    "JobHealth",
]
