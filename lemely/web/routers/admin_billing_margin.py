"""Admin billing, area 4: the money and margin report (spec §8).

A lane router of ``admin_billing`` (DV-2, DV-T5a). It is mounted in ``app.py`` beside the parent
with the full prefix and carries its own ``platform_admin`` guard, never nested into the parent
(FastAPI 0.138 would hide its prefix from ``flatten_routes``). Read-only: no audit rows.
"""

# FastAPI ``Depends``/``Query`` and pydantic construction need these type imports at runtime
# (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

from datetime import datetime  # noqa: TC003 - FastAPI resolves the query type at runtime
from decimal import Decimal  # noqa: TC003 - FastAPI resolves the query type at runtime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from lemely.db.admin_margin_repo import AdminMarginService, CostRow, MarginReport
from lemely.db.models.enums import Role
from lemely.db.session import get_sessionmaker
from lemely.web.admin_billing_common import mapped_errors, require_aware
from lemely.web.deps import get_settings, require_role
from lemely.web.schemas_admin_billing_margin import (
    AccuracyRowDTO,
    CostDTO,
    CostRowDTO,
    DebtorDTO,
    ExpiredJobsDTO,
    ExposureDTO,
    MarginReportDTO,
    ModelCostDTO,
    MoneyByKeyDTO,
    RevenueDTO,
)

router = APIRouter(
    prefix="/api/admin/billing/margin",
    dependencies=[Depends(require_role(Role.platform_admin))],
)


def get_admin_margin_service() -> AdminMarginService:
    """Built per request (the service holds only the sessionmaker); tests override it."""
    return AdminMarginService(get_sessionmaker(get_settings()))


MarginService = Annotated[AdminMarginService, Depends(get_admin_margin_service)]


def _aware(value: datetime, field: str) -> datetime:
    """``value`` when it carries a time zone, else 422 ``naive_datetime`` (DV-24)."""
    return require_aware(value, field) or value


def _usd(value: Decimal) -> str:
    return f"{value:.6f}"


def _cost_row(row: CostRow) -> CostRowDTO:
    return CostRowDTO(key=row.key, jobs=row.jobs, costUsd=_usd(row.cost_usd))


def margin_dto(r: MarginReport) -> MarginReportDTO:
    return MarginReportDTO(
        windowStart=r.start,
        windowEnd=r.end,
        revenue=RevenueDTO(
            recurringMinor=r.revenue.recurring_minor,
            packsMinor=r.revenue.packs_minor,
            refundedMinor=r.revenue.refunded_minor,
            netMinor=r.revenue.net_minor,
            byPurpose=r.revenue.by_purpose,
            byPlan=[MoneyByKeyDTO(key=k, minor=v) for k, v in r.revenue.by_plan],
        ),
        cost=CostDTO(
            totalUsd=_usd(r.cost.total_usd),
            byAction=[_cost_row(x) for x in r.cost.by_action],
            byPlan=[_cost_row(x) for x in r.cost.by_plan],
            byModel=[ModelCostDTO(model=m, costUsd=_usd(c)) for m, c in r.cost.by_model],
            unattributedModelUsd=_usd(r.cost.unattributed_model_usd),
        ),
        egpPerUsd=None if r.egp_per_usd is None else str(r.egp_per_usd),
        costMinor=r.cost_minor,
        marginMinor=r.margin_minor,
        accuracy=[
            AccuracyRowDTO(
                action=a.action,
                estimatorVersion=a.estimator_version,
                jobs=a.jobs,
                below=a.below,
                above=a.above,
                shareOutside=a.share_outside,
                meanOverrunUnits=a.mean_overrun_units,
                maxOverrunUnits=a.max_overrun_units,
            )
            for a in r.accuracy
        ],
        exposure=ExposureDTO(
            outstandingDebtUnits=r.exposure.outstanding_debt_units,
            debtors=r.exposure.debtors,
            topDebtors=[
                DebtorDTO(userId=str(d.user_id), email=d.email, outstanding=d.outstanding)
                for d in r.exposure.top_debtors
            ],
            usersAtLimit=r.exposure.users_at_limit,
            creditsExpiring30dUnits=r.exposure.credits_expiring_30d_units,
            creditsExpiring30dOwners=r.exposure.credits_expiring_30d_owners,
            creditsExpiredUnusedUnits=r.exposure.credits_expired_unused_units,
            expiredJobs=ExpiredJobsDTO(
                count=r.exposure.expired_jobs, costUsd=_usd(r.exposure.expired_jobs_cost_usd)
            ),
        ),
    )


@router.get("", response_model=MarginReportDTO)
def margin_report(
    service: MarginService,
    start: Annotated[datetime, Query(alias="from")],
    end: Annotated[datetime, Query(alias="to")],
    egpPerUsd: Annotated[Decimal | None, Query(gt=0, le=10_000)] = None,
) -> MarginReportDTO:
    """The window is half-open ``[from, to)``; both ends need a time zone (DV-24)."""
    with mapped_errors():
        return margin_dto(
            service.margin(_aware(start, "from"), _aware(end, "to"), egp_per_usd=egpPerUsd)
        )
