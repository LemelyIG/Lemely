"""Dependencies shared by the billing and Paymob webhook routers (billing spec §3).

Process-wide, lazily built singletons, the ``lru_cache`` pattern of
``lemely.web.deps``; tests override them through ``app.dependency_overrides``.
``deps.reset_singletons`` calls :func:`reset_billing_singletons`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from lemely.db.session import get_sessionmaker
from lemely.io.paymob.client import PaymobClient
from lemely.web.billing_jobs import reconcile_pending_payments
from lemely.web.deps import get_settings

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker


@lru_cache(maxsize=1)
def get_paymob_client() -> PaymobClient:
    """The process-wide Paymob client (it caches the one-hour auth token)."""
    return PaymobClient(get_settings().paymob)


def get_billing_sessionmaker() -> sessionmaker[Session]:
    """The process sessionmaker, as a dependency tests can point at a throwaway DB."""
    return get_sessionmaker(get_settings())


def get_billing_reconcile_job() -> Callable[[datetime], int] | None:
    """The ``billing.reconcile_pending`` job, or ``None`` when Paymob is unconfigured."""
    settings = get_settings().paymob
    if not settings.checkout_configured:
        return None

    def job(now: datetime) -> int:
        return reconcile_pending_payments(
            get_billing_sessionmaker(), get_paymob_client(), settings, now=now
        )

    return job


def reset_billing_singletons() -> None:
    """Close the cached Paymob client, then clear this module's cached providers.

    ``deps.reset_singletons`` does not know them. The client owns an ``httpx``
    connection pool, so a cache clear alone would leak it. A client is closed only if
    one was built: asking ``get_paymob_client`` to build one just to close it would
    fail on an unconfigured process and open a pool for nothing. The cache is cleared
    even when ``close`` raises.
    """
    try:
        if get_paymob_client.cache_info().currsize:
            get_paymob_client().close()
    finally:
        get_paymob_client.cache_clear()


__all__ = [
    "get_billing_reconcile_job",
    "get_billing_sessionmaker",
    "get_paymob_client",
    "reset_billing_singletons",
]
