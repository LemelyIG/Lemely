"""``POST /api/internal/jobs/sweep``: one sweeper pass, called by Cloud Scheduler.

Cloud Run deploys with ``--min-instances=0`` and throttled CPU, so an in-process sweep loop
(:func:`lemely.web.scheduled_notifications.run_sweeper`) would do nothing while no request is
being served: no payment reconcile, no subscription period or overdue sweep, no grant or hold
expiry. Scheduler calls this route every minute instead; the request itself keeps the instance
awake and its CPU allocated for the length of the pass. On Cloud Run the deploy switches the loop
off (``LEMELY_NOTIFICATIONS__SWEEPER_ENABLED=false``) once it finds the Scheduler job in place,
because a loop pass whose CPU is throttled once its request ends could stall while holding the
pass lock; until then the loop stays on so the service always has a driver. The loop remains for
local runs and hosts with always-on CPU.

Not a user route, so it carries no bearer token. It uses the waitlist digest trigger's scheme
(:mod:`lemely.web.routers.waitlist`): the shared secret ``[notifications] jobs_secret`` in an
``X-Cron-Secret`` header, compared in constant time, a missing or wrong one is 403. With no
secret configured it answers 503 rather than 404 (the digest's choice): the Scheduler job exists
and is failing, which the operator should see, and a bare 404 would read as a wrong URL.

The pass is :meth:`~lemely.web.scheduled_notifications.Sweeper.sweep_exclusive`: everything one
loop tick runs, including the daily usage reconcile once it is due, under an advisory lock so a
second concurrent call is skipped at once (``status: "skipped"``, still 200: nothing is wrong).
A job that raises is a ``sweep_job_failed`` log line (the event alerts key on) and ``None`` in
the response; the others still run, and the status stays 200 so Scheduler does not retry a whole
pass because one job is unhealthy. The response never carries rows or exception text.

The pass is bounded (``[notifications] sweep_pass_budget_seconds``, 60 s) so it finishes inside
the Scheduler job's 90 s attempt deadline and Cloud Run's 300 s request timeout: jobs not started
when the budget runs out come back as ``skipped`` (a ``sweep_pass_budget_spent`` warning) and run
on the next tick. Each batch starts a unit of work (a row, an inquiry, a charge) only while its
expected time fits the budget, and stops between units, never inside a claimed charge. The
Scheduler job makes no retries; the next minute's call is the retry.

Rotation: ``jobs_secret_previous`` is accepted beside ``jobs_secret`` while Scheduler may still
send the old value (docs/deployment.md section 5.2).
"""

from __future__ import annotations

import hmac
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException

from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import get_settings, get_sweeper
from lemely.web.scheduled_notifications import Sweeper  # noqa: TC001 - FastAPI resolves it
from lemely.web.schemas_internal_jobs import SweepResultDTO

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api")


def require_cron_secret(
    settings: Annotated[Settings, Depends(get_settings)],
    x_cron_secret: Annotated[str | None, Header()] = None,
) -> None:
    """Refuse the call unless it carries the current or the previous jobs secret.

    A dependency of its own, listed before the sweeper, so FastAPI checks the secret before it
    resolves :func:`get_sweeper`: an unauthenticated caller never makes the process build the
    sweeper, its payment client or its pool.
    """
    notifications = settings.notifications
    if notifications.jobs_secret is None:
        raise HTTPException(status_code=503, detail="The sweep trigger is not configured")
    # Either the current secret or, during a staged rotation, the previous one. Every candidate
    # is compared, in a list built before the verdict, so which one matched is not a timing
    # signal; a missing header is compared as empty bytes, which matches no candidate.
    supplied = (x_cron_secret or "").encode()
    candidates = [notifications.jobs_secret, notifications.jobs_secret_previous]
    matches = [
        hmac.compare_digest(supplied, secret.get_secret_value().encode())
        for secret in candidates
        if secret is not None
    ]
    if x_cron_secret is None or not any(matches):
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post(
    "/internal/jobs/sweep",
    response_model=SweepResultDTO,
    dependencies=[Depends(require_cron_secret)],
)
def run_sweep(sweeper: Annotated[Sweeper, Depends(get_sweeper)]) -> SweepResultDTO:
    """Run one full sweeper pass now, unless one is already running."""
    outcome = sweeper.sweep_exclusive()
    if outcome is None:
        log.info("sweep_pass_skipped", reason="another pass is running")
        return SweepResultDTO(status="skipped", jobs={}, failed=[], skipped=[])
    failed = [name for name, count in outcome.results.items() if count is None]
    return SweepResultDTO(
        status="completed", jobs=outcome.results, failed=failed, skipped=outcome.skipped
    )
