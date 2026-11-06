"""Dependencies shared by the billing and Paymob webhook routers (billing spec §3).

Process-wide, lazily built singletons, the ``lru_cache`` pattern of
``lemely.web.deps``; tests override them through ``app.dependency_overrides``.
``deps.reset_singletons`` calls :func:`reset_billing_singletons`.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import TYPE_CHECKING

from lemely.db.session import get_sessionmaker
from lemely.io.paymob.client import PaymobClient
from lemely.web.billing_jobs import reconcile_pending_payments
from lemely.web.deps import get_settings
from lemely.web.ratelimit import SlidingWindowLimiter

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


#: Checkout creation (spec §7): 5 per user per minute. A real buyer needs one; a
#: retry after a declined card needs a second. Each checkout also costs a Paymob
#: intention, so this bounds what one account can make Paymob do.
_CHECKOUT_LIMIT = 5
_CHECKOUT_WINDOW_SECONDS = 60.0


@lru_cache(maxsize=1)
def get_checkout_limiter() -> SlidingWindowLimiter:
    """Per-user limiter for ``POST /api/billing/checkout/*`` (keyed by user id)."""
    return SlidingWindowLimiter(
        limit=_CHECKOUT_LIMIT, window_seconds=_CHECKOUT_WINDOW_SECONDS, clock=time.monotonic
    )


#: Public pricing page (no auth): 60 reads per client IP per minute. Keyed by the
#: same ``_client_ip`` the contact form uses, with the same caveat
#: (``ClientErrorLimiters`` in ``deps.py``): it binds callers that arrive through
#: the Cloudflare Worker. The response is a few hundred bytes of public data, so
#: this is a deterrent, not a security boundary.
_PUBLIC_CATALOGUE_LIMIT = 60
_PUBLIC_CATALOGUE_WINDOW_SECONDS = 60.0


@lru_cache(maxsize=1)
def get_public_catalogue_limiter() -> SlidingWindowLimiter:
    """Per-IP limiter for ``GET /api/billing/public-catalogue``."""
    return SlidingWindowLimiter(
        limit=_PUBLIC_CATALOGUE_LIMIT,
        window_seconds=_PUBLIC_CATALOGUE_WINDOW_SECONDS,
        clock=time.monotonic,
    )


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
        get_checkout_limiter.cache_clear()
        get_public_catalogue_limiter.cache_clear()


__all__ = [
    "get_billing_reconcile_job",
    "get_billing_sessionmaker",
    "get_checkout_limiter",
    "get_paymob_client",
    "get_public_catalogue_limiter",
    "reset_billing_singletons",
]
