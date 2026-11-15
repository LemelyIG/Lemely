"""DTOs for billing health (``GET /api/admin/billing/health``, spec §8 area 5).

Responses only: camelCase on the wire, ``extra="forbid"`` (``ApiModel``). The keys equal the
frontend's ``BillingHealth`` and ``SweeperJobHealth`` (``web/src/lib/billingTypes.ts``).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import Literal

from lemely.web.schemas_admin import ApiModel


class JobHealthDTO(ApiModel):
    name: str
    neverRun: bool
    lastStartedAt: datetime | None
    lastFinishedAt: datetime | None
    lastOutcome: Literal["ok", "failed"] | None
    lastResultCount: int | None
    lastError: str | None
    lastSuccessAt: datetime | None
    consecutiveFailures: int
    totalRuns: int
    totalFailures: int


class BillingHealthDTO(ApiModel):
    """The billing health report for the last ``windowHours``.

    ``verifiedEvents`` counts every stored Paymob event (callbacks and reconcile inquiry
    results; the table records no source), so ``webhookErrorRate`` is HMAC failures per stored
    Paymob event. ``hmacFailures`` is capped at 60 rows per minute per process and undercounts in
    a flood. ``renewalFailureEvents`` counts failure callbacks received, stale replays included.
    A job whose first run never finished reads ``neverRun``.
    """

    windowHours: int
    jobs: list[JobHealthDTO]
    verifiedEvents: int
    hmacFailures: int
    webhookErrorRate: float | None
    """0..1; ``None`` with no callbacks in the window."""
    mismatches: int
    renewalFailureEvents: int
    pastDueNow: int
    failedAutoTopups: int
    failedExtraSeatCharges: int
