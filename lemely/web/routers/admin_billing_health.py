"""Admin billing, area 5: billing health (spec §8).

A lane router of ``admin_billing`` (DV-2, DV-T5a): mounted in ``app.py`` with its full prefix
and its own ``platform_admin`` guard, never nested. Read-only, so it writes no audit row.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these type imports at
# runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from lemely.db.admin_health_repo import AdminHealthService, JobHealth
from lemely.db.models.enums import Role
from lemely.db.session import get_sessionmaker
from lemely.web.deps import get_settings, require_role
from lemely.web.schemas_admin_billing_health import BillingHealthDTO, JobHealthDTO

router = APIRouter(
    prefix="/api/admin/billing",
    dependencies=[Depends(require_role(Role.platform_admin))],
)


def get_admin_health_service() -> AdminHealthService:
    return AdminHealthService(get_sessionmaker(get_settings()))


HealthService = Annotated[AdminHealthService, Depends(get_admin_health_service)]


def _outcome(value: str | None) -> Literal["ok", "failed"] | None:
    # ``job_runs`` CHECKs the column to these two values.
    if value is None:
        return None
    return "ok" if value == "ok" else "failed"


def _job_health_dto(job: JobHealth) -> JobHealthDTO:
    run = job.run
    if run is None:
        return JobHealthDTO(
            name=job.name,
            neverRun=True,
            lastStartedAt=None,
            lastFinishedAt=None,
            lastOutcome=None,
            lastResultCount=None,
            lastError=None,
            lastSuccessAt=None,
            consecutiveFailures=0,
            totalRuns=0,
            totalFailures=0,
        )
    return JobHealthDTO(
        name=job.name,
        neverRun=False,
        lastStartedAt=run.last_started_at,
        lastFinishedAt=run.last_finished_at,
        lastOutcome=_outcome(run.last_outcome),
        lastResultCount=run.last_result_count,
        lastError=run.last_error,
        lastSuccessAt=run.last_success_at,
        consecutiveFailures=run.consecutive_failures,
        totalRuns=run.total_runs,
        totalFailures=run.total_failures,
    )


@router.get("/health", response_model=BillingHealthDTO)
def billing_health(
    service: HealthService, hours: Annotated[int, Query(ge=1, le=720)] = 24
) -> BillingHealthDTO:
    h = service.health(hours=hours)
    return BillingHealthDTO(
        windowHours=h.window_hours,
        jobs=[_job_health_dto(j) for j in h.jobs],
        verifiedEvents=h.verified_events,
        hmacFailures=h.hmac_failures,
        webhookErrorRate=h.webhook_error_rate,
        mismatches=h.mismatches,
        renewalFailureEvents=h.renewal_failure_events,
        pastDueNow=h.past_due_now,
        failedAutoTopups=h.failed_auto_topups,
        failedExtraSeatCharges=h.failed_extra_seat_charges,
    )
