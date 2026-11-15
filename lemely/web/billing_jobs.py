"""Billing sweeper jobs (billing spec §3 "Jobs", §5.10).

``billing.reconcile_pending`` inquires Paymob for payments whose callback never
came (about 2% of transactions; abandoned 3DS sends none). Idempotency comes
from row state: ``FOR UPDATE SKIP LOCKED`` on each payment, the unique
``paymob_events.dedupe_key``, and status transitions that only move forward. A
second replica or a re-run after a crash therefore never double-grants.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import lemely.db.subscription_repo  # noqa: F401  (registers the subscription paid handlers)
from lemely.db.billing_repo import BillingService

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings


def reconcile_pending_payments(
    sessionmaker: sessionmaker[Session],
    client: PaymobClient,
    settings: PaymobSettings,
    *,
    now: datetime,
) -> int:
    """One pass of ``billing.reconcile_pending``; returns the payments inquired."""
    with sessionmaker() as session:
        return BillingService(session, client, settings, now=lambda: now).reconcile_pending(now=now)


__all__ = ["reconcile_pending_payments"]
