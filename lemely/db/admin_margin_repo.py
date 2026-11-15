"""Money and margin (spec §8 area 4): aggregate SQL over payments and the usage ledger.

Every figure is one ``GROUP BY`` over indexed columns (migration 0057 adds the indexes this
module's ``WHERE`` clauses use); nothing loops over jobs or payments in Python. Windows are
half-open ``[start, end)``: an instant equal to ``start`` is in, one equal to ``end`` is out.
The service only reads: it writes no audit row.

Definitions, stated once so the screen and the tests agree:

* **Gross revenue**: payments ``paid``/``partially_refunded``/``refunded`` whose ``paid_at`` is
  in the window. A ``voided`` payment never counts (it did not settle); a ``failed`` one has no
  ``paid_at``. Recurring is the subscription purposes, packs is ``credit_pack``/``auto_topup``.
* **Refunded**: money returned in the window, from two sources that never overlap.
  (a) *Console refunds*: ``payment_refunds`` of kind ``refund`` and status ``succeeded``, by the
  time the attempt closed (``updated_at``). A void is not a refund (DV-19).
  (b) *Dashboard refunds* (Phase 02): a refund made in the Paymob dashboard leaves no console
  row; the callback records Paymob's running total in ``last_callback.refunded_amount_cents``.
  The dashboard part is that total (capped at the payment amount) minus every succeeded console
  refund of the payment, when positive, attributed to the payment's ``updated_at`` (the last
  callback). A payment refunded in the console and reported back by Paymob therefore counts
  once. A value that is not a non-negative integer of at most 15 digits counts as 0, as
  ``PaymentView.refunded_minor`` does. Caveat: any later write to the payment moves its
  ``updated_at`` and so the attribution of an earlier dashboard refund.
  Net = gross - refunded, and may be negative when a window refunds earlier sales.
* **LLM cost**: ``usage_jobs.actual_cost_usd`` of jobs created in the window, any status (an
  expired job's recorded cost is real money spent). Every query that filters ``usage_jobs`` by
  ``created_at`` also states ``actual_cost_usd IS NOT NULL``: ``ix_admin_usage_jobs_created_at``
  is partial on it and is unusable otherwise. So a job with no recorded cost is in no figure
  here, including the expired-jobs exposure (it counts expired jobs *with* a cost).
* **Cost by plan**: the plan of the actor's subscription period covering the job's creation;
  jobs with none (credits-only users, assistants acting without a plan of their own) are the
  ``None`` row.
* **Cost by model**: ``usage_job_model_costs`` of jobs created in the window; the remainder of
  the total is ``unattributed`` (jobs settled before per-model recording, or expired by crash),
  never negative: model rows above the total mean double counting, so the remainder is clamped
  to 0 and ``margin_model_cost_exceeds_total`` is logged.
* **Accuracy**: settled jobs only; actual units = ``ceil(actual_cost_usd x units_per_usd)`` at
  the job's own rate version, compared with its own estimate range.
* **Margin**: needs an EGP-per-USD rate from the caller; without one it is ``None`` rather than
  a number built on a guessed rate. ``costMinor = ceil(totalUsd x rate x 100)``: the cost is
  rounded up, against us.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog

from lemely.db.admin_billing_repo import AdminInvalidError
from lemely.db.models.billing import PaymentPurpose

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

#: Events the operator alerts on (``alert=True`` survives only in structlog).
alerts = structlog.get_logger("lemely.db.admin_margin_repo")

RECURRING_PURPOSES: Final = frozenset(
    {
        PaymentPurpose.subscription_first,
        PaymentPurpose.subscription_renewal,
        PaymentPurpose.upgrade_proration,
        PaymentPurpose.extra_seats,
    }
)
PACK_PURPOSES: Final = frozenset({PaymentPurpose.credit_pack, PaymentPurpose.auto_topup})
_MAX_WINDOW = timedelta(days=400)
_EXPIRING_SOON = timedelta(days=30)
_TOP_DEBTORS = 20
_ZERO = Decimal("0")

_REVENUE_FILTER = (
    "p.paid_at >= :start AND p.paid_at < :end"
    " AND p.status::text IN ('paid', 'partially_refunded', 'refunded')"
)

#: The predicate every ``usage_jobs`` query on ``created_at`` carries (the partial index's).
_JOBS_IN_WINDOW = "j.created_at >= :start AND j.created_at < :end AND j.actual_cost_usd IS NOT NULL"

_COST_BY_ACTION = (
    "SELECT j.action, COUNT(*), SUM(j.actual_cost_usd) FROM usage_jobs j"  # noqa: S608 - fixed fragments, no caller input
    f" WHERE {_JOBS_IN_WINDOW} GROUP BY j.action ORDER BY j.action"
)
_COST_BY_PLAN = (
    "SELECT t.code, COUNT(*), SUM(j.actual_cost_usd) FROM usage_jobs j"  # noqa: S608 - fixed fragments, no caller input
    " LEFT JOIN LATERAL ("
    "   SELECT s.plan_tier_id FROM subscription_periods sp"
    "   JOIN subscriptions s ON s.id = sp.subscription_id"
    "   WHERE s.user_id = j.actor_user_id"
    "     AND sp.period_start <= j.created_at AND j.created_at < sp.period_end"
    "   ORDER BY sp.period_start DESC LIMIT 1"
    " ) plan ON TRUE"
    " LEFT JOIN plan_tiers t ON t.id = plan.plan_tier_id"
    f" WHERE {_JOBS_IN_WINDOW} GROUP BY t.code ORDER BY t.code NULLS LAST"
)
_COST_BY_MODEL = (
    "SELECT c.model, SUM(c.cost_usd) FROM usage_job_model_costs c"  # noqa: S608 - fixed fragments, no caller input
    " JOIN usage_jobs j ON j.id = c.usage_job_id"
    f" WHERE {_JOBS_IN_WINDOW} GROUP BY c.model ORDER BY c.model"
)
_ACCURACY = (
    "WITH settled AS ("  # noqa: S608 - fixed fragments, no caller input
    "  SELECT j.action, j.estimator_version, j.estimate_low, j.estimate_high,"
    "         CEIL(j.actual_cost_usd * r.units_per_usd)::bigint AS actual_units"
    "  FROM usage_jobs j"
    "  JOIN usage_rates r ON r.version = j.rate_version AND r.action = j.action"
    f"  WHERE j.status::text = 'settled' AND {_JOBS_IN_WINDOW}"
    ")"
    " SELECT action, estimator_version, COUNT(*),"
    "  COUNT(*) FILTER (WHERE actual_units < estimate_low),"
    "  COUNT(*) FILTER (WHERE actual_units > estimate_high),"
    "  AVG(actual_units - estimate_high) FILTER (WHERE actual_units > estimate_high),"
    "  MAX(actual_units - estimate_high) FILTER (WHERE actual_units > estimate_high)"
    " FROM settled GROUP BY action, estimator_version"
    " ORDER BY action, estimator_version"
)
_EXPIRED_JOBS = (
    "SELECT COUNT(*), COALESCE(SUM(j.actual_cost_usd), 0) FROM usage_jobs j"  # noqa: S608 - fixed fragments, no caller input
    f" WHERE j.status::text = 'expired' AND {_JOBS_IN_WINDOW}"
)

#: Every statement that filters ``usage_jobs`` by ``created_at``, named for the EXPLAIN pin in
#: ``tests/test_admin_billing_margin.py``. Bind parameters: ``:start`` and ``:end``.
JOB_WINDOW_QUERIES: Final[dict[str, str]] = {
    "cost_by_action": _COST_BY_ACTION,
    "cost_by_plan": _COST_BY_PLAN,
    "cost_by_model": _COST_BY_MODEL,
    "accuracy": _ACCURACY,
    "expired_jobs": _EXPIRED_JOBS,
}

_GROSS_BY_PURPOSE = (
    "SELECT p.purpose::text, SUM(p.amount_minor) FROM payments p"  # noqa: S608 - fixed fragments, no caller input
    f" WHERE {_REVENUE_FILTER} GROUP BY p.purpose::text"
)
_GROSS_BY_PLAN = (
    "SELECT t.code, SUM(p.amount_minor) FROM payments p"  # noqa: S608 - fixed fragments, no caller input
    " JOIN plan_tiers t ON t.id = p.plan_tier_id"
    f" WHERE {_REVENUE_FILTER} GROUP BY t.code ORDER BY t.code"
)
_CONSOLE_REFUNDED = (
    "SELECT COALESCE(SUM(r.amount_minor), 0) FROM payment_refunds r"
    " WHERE r.kind::text = 'refund' AND r.status::text = 'succeeded'"
    " AND r.updated_at >= :start AND r.updated_at < :end"
)
_DASHBOARD_REFUNDED = (
    "SELECT COALESCE(SUM(GREATEST(reported.minor - reported.console, 0)), 0) FROM ("
    "  SELECT LEAST(p.amount_minor,"
    "           CASE WHEN p.last_callback->>'refunded_amount_cents' ~ '^[0-9]{1,15}$'"
    "                THEN (p.last_callback->>'refunded_amount_cents')::bigint ELSE 0 END"
    "         ) AS minor,"
    "         COALESCE(("
    "           SELECT SUM(r.amount_minor) FROM payment_refunds r"
    "           WHERE r.payment_id = p.id AND r.kind::text = 'refund'"
    "             AND r.status::text = 'succeeded'"
    "         ), 0) AS console"
    "  FROM payments p"
    "  WHERE p.status::text IN ('partially_refunded', 'refunded')"
    "    AND p.updated_at >= :start AND p.updated_at < :end"
    ") reported"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CostRow:
    key: str | None
    jobs: int
    cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class RevenueReport:
    recurring_minor: int
    packs_minor: int
    refunded_minor: int
    net_minor: int
    by_purpose: dict[str, int]
    by_plan: list[tuple[str, int]]


@dataclass(frozen=True, slots=True)
class CostReport:
    total_usd: Decimal
    by_action: list[CostRow]
    by_plan: list[CostRow]
    by_model: list[tuple[str, Decimal]]
    unattributed_model_usd: Decimal


@dataclass(frozen=True, slots=True)
class AccuracyRow:
    action: str
    estimator_version: int
    jobs: int
    below: int
    above: int
    share_outside: float
    mean_overrun_units: float | None
    max_overrun_units: int | None


@dataclass(frozen=True, slots=True)
class Debtor:
    user_id: uuid.UUID
    email: str
    outstanding: int


@dataclass(frozen=True, slots=True)
class ExposureReport:
    outstanding_debt_units: int
    debtors: int
    top_debtors: list[Debtor]
    users_at_limit: int
    credits_expiring_30d_units: int
    credits_expiring_30d_owners: int
    credits_expired_unused_units: int
    expired_jobs: int
    expired_jobs_cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class MarginReport:
    start: datetime
    end: datetime
    revenue: RevenueReport
    cost: CostReport
    egp_per_usd: Decimal | None
    cost_minor: int | None
    margin_minor: int | None
    accuracy: list[AccuracyRow]
    exposure: ExposureReport


class AdminMarginService:
    def __init__(
        self, sessionmaker: sessionmaker[Session], *, now: Callable[[], datetime] = _utcnow
    ) -> None:
        self._sm = sessionmaker
        self._now = now

    def margin(
        self, start: datetime, end: datetime, *, egp_per_usd: Decimal | None
    ) -> MarginReport:
        if end <= start or end - start > _MAX_WINDOW:
            raise AdminInvalidError("bad_window", "The window must run forwards, at most 400 days.")
        window = {"start": start, "end": end}
        with self._sm() as s:
            revenue = self._revenue(s, window)
            cost = self._cost(s, window)
            accuracy = self._accuracy(s, window)
            exposure = self._exposure(s, window, now=self._now())
        cost_minor = margin_minor = None
        if egp_per_usd is not None:
            cost_minor = int(
                (cost.total_usd * egp_per_usd * 100).to_integral_value(rounding=ROUND_CEILING)
            )
            margin_minor = revenue.net_minor - cost_minor
        return MarginReport(
            start, end, revenue, cost, egp_per_usd, cost_minor, margin_minor, accuracy, exposure
        )

    # -- revenue -------------------------------------------------------------------

    @staticmethod
    def _revenue(s: Session, window: dict[str, datetime]) -> RevenueReport:
        by_purpose = {
            str(purpose): int(minor)
            for purpose, minor in s.execute(sa.text(_GROSS_BY_PURPOSE), window)
        }
        console = int(s.execute(sa.text(_CONSOLE_REFUNDED), window).scalar_one())
        dashboard = int(s.execute(sa.text(_DASHBOARD_REFUNDED), window).scalar_one())
        by_plan = [
            (str(code), int(minor)) for code, minor in s.execute(sa.text(_GROSS_BY_PLAN), window)
        ]
        recurring = sum(v for k, v in by_purpose.items() if PaymentPurpose(k) in RECURRING_PURPOSES)
        packs = sum(v for k, v in by_purpose.items() if PaymentPurpose(k) in PACK_PURPOSES)
        refunded = console + dashboard
        return RevenueReport(
            recurring_minor=recurring,
            packs_minor=packs,
            refunded_minor=refunded,
            net_minor=recurring + packs - refunded,
            by_purpose=dict(sorted(by_purpose.items())),
            by_plan=by_plan,
        )

    # -- cost ------------------------------------------------------------------------

    @staticmethod
    def _cost(s: Session, window: dict[str, datetime]) -> CostReport:
        by_action = [
            CostRow(str(action), int(jobs), Decimal(cost))
            for action, jobs, cost in s.execute(sa.text(_COST_BY_ACTION), window)
        ]
        by_plan = [
            CostRow(None if code is None else str(code), int(jobs), Decimal(cost))
            for code, jobs, cost in s.execute(sa.text(_COST_BY_PLAN), window)
        ]
        by_model = [
            (str(model), Decimal(cost))
            for model, cost in s.execute(sa.text(_COST_BY_MODEL), window)
        ]
        total = sum((row.cost_usd for row in by_action), _ZERO)
        attributed = sum((cost for _, cost in by_model), _ZERO)
        unattributed = total - attributed
        if unattributed < _ZERO:
            alerts.warning(
                "margin_model_cost_exceeds_total",
                total_usd=str(total),
                model_usd=str(attributed),
                alert=True,
            )
            unattributed = _ZERO
        return CostReport(total, by_action, by_plan, by_model, unattributed)

    # -- estimate accuracy -------------------------------------------------------------

    @staticmethod
    def _accuracy(s: Session, window: dict[str, datetime]) -> list[AccuracyRow]:
        rows = s.execute(sa.text(_ACCURACY), window)
        return [
            AccuracyRow(
                action=str(action),
                estimator_version=int(version),
                jobs=int(jobs),
                below=int(below),
                above=int(above),
                share_outside=round((int(below) + int(above)) / int(jobs), 4),
                mean_overrun_units=None if mean is None else round(float(mean), 2),
                max_overrun_units=None if peak is None else int(peak),
            )
            for action, version, jobs, below, above, mean, peak in rows
        ]

    # -- exposure ----------------------------------------------------------------------

    @staticmethod
    def _exposure(s: Session, window: dict[str, datetime], *, now: datetime) -> ExposureReport:
        debt_units, debtors = s.execute(
            sa.text(
                "SELECT COALESCE(SUM(outstanding), 0), COUNT(DISTINCT owner_user_id)"
                " FROM usage_debts WHERE outstanding > 0"
            )
        ).one()
        top = [
            Debtor(uid, str(email), int(outstanding))
            for uid, email, outstanding in s.execute(
                sa.text(
                    "SELECT d.owner_user_id, u.email, SUM(d.outstanding) AS owed"
                    " FROM usage_debts d JOIN users u ON u.id = d.owner_user_id"
                    " WHERE d.outstanding > 0 GROUP BY d.owner_user_id, u.email"
                    " ORDER BY owed DESC, u.email LIMIT :top"
                ),
                {"top": _TOP_DEBTORS},
            )
        ]
        live = "g.effective_at <= :now AND (g.expires_at IS NULL OR g.expires_at > :now)"
        at_limit = s.execute(
            sa.text(
                "SELECT COUNT(*) FROM ("  # noqa: S608 - fixed fragments, no caller input
                "  SELECT g.owner_user_id FROM usage_grants g"
                "  JOIN usage_grant_balances b ON b.grant_id = g.id"
                f"  WHERE g.kind::text = 'period_allowance' AND {live}"
                "  GROUP BY g.owner_user_id HAVING SUM(b.remaining - b.held) <= 0"
                ") at_limit"
            ),
            {"now": now},
        ).scalar_one()
        expiring_units, expiring_owners = s.execute(
            sa.text(
                "SELECT COALESCE(SUM(b.remaining - b.held), 0), COUNT(DISTINCT g.owner_user_id)"
                " FROM usage_grants g JOIN usage_grant_balances b ON b.grant_id = g.id"
                " WHERE g.visible AND g.expires_at > :now AND g.expires_at <= :soon"
                " AND b.remaining - b.held > 0"
            ),
            {"now": now, "soon": now + _EXPIRING_SOON},
        ).one()
        expired_unused = s.execute(
            sa.text(
                "SELECT COALESCE(SUM(ABS(e.units)), 0) FROM usage_entries e"
                " JOIN usage_grants g ON g.id = e.grant_id"
                " WHERE e.kind::text = 'expire' AND g.visible"
                " AND e.event_at >= :start AND e.event_at < :end"
            ),
            window,
        ).scalar_one()
        expired_jobs, expired_cost = s.execute(sa.text(_EXPIRED_JOBS), window).one()
        return ExposureReport(
            outstanding_debt_units=int(debt_units),
            debtors=int(debtors),
            top_debtors=top,
            users_at_limit=int(at_limit),
            credits_expiring_30d_units=int(expiring_units),
            credits_expiring_30d_owners=int(expiring_owners),
            credits_expired_unused_units=int(expired_unused),
            expired_jobs=int(expired_jobs),
            expired_jobs_cost_usd=Decimal(expired_cost),
        )


__all__ = [
    "JOB_WINDOW_QUERIES",
    "PACK_PURPOSES",
    "RECURRING_PURPOSES",
    "AccuracyRow",
    "AdminMarginService",
    "CostReport",
    "CostRow",
    "Debtor",
    "ExposureReport",
    "MarginReport",
    "RevenueReport",
    "alerts",
]
