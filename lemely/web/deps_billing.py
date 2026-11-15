"""Dependencies shared by the billing and Paymob webhook routers (billing spec §3).

Process-wide, lazily built singletons, the ``lru_cache`` pattern of
``lemely.web.deps``; tests override them through ``app.dependency_overrides``.
``deps.reset_singletons`` calls :func:`reset_billing_singletons`.
"""

from __future__ import annotations

import threading
import time
from functools import lru_cache
from typing import TYPE_CHECKING

from lemely.db.session import get_sessionmaker
from lemely.io.paymob.client import PaymobClient
from lemely.web.billing_jobs import reconcile_pending_payments
from lemely.web.deps import get_settings
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.subscription_deps import SubscriptionDeps

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.web.schemas_billing import PublicCatalogueDTO


@lru_cache(maxsize=1)
def get_paymob_client() -> PaymobClient:
    """The process-wide Paymob client (it caches the one-hour auth token)."""
    return PaymobClient(get_settings().paymob)


def get_billing_sessionmaker() -> sessionmaker[Session]:
    """The process sessionmaker, as a dependency tests can point at a throwaway DB."""
    return get_sessionmaker(get_settings())


@lru_cache(maxsize=1)
def get_subscription_deps() -> SubscriptionDeps:
    """The subscription routes' collaborators (Paymob billing Phase 05)."""
    return SubscriptionDeps(get_billing_sessionmaker(), get_paymob_client(), get_settings().paymob)


def get_subscription_jobs() -> SubscriptionDeps | None:
    """The sweeper's subscription collaborators, or ``None`` when Paymob is unconfigured.

    Mirrors :func:`get_billing_reconcile_job`: with no checkout configured there is nothing to
    sweep against, and the sweeper registers no subscription job.
    """
    if not get_settings().paymob.checkout_configured:
        return None
    return get_subscription_deps()


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


#: Subscription checkout: 10 per user per 10 minutes. Each one costs a Paymob intention and
#: replaces the payer's unpaid one, so this bounds what a single account can make Paymob do
#: while leaving room for a declined card and a retry.
_SUBSCRIPTION_CHECKOUT_LIMIT = 10
_SUBSCRIPTION_CHECKOUT_WINDOW_SECONDS = 600.0


@lru_cache(maxsize=1)
def get_subscription_checkout_limiter() -> SlidingWindowLimiter:
    """Per-user limiter for ``POST /api/billing/subscriptions/checkout`` (keyed by user id)."""
    return SlidingWindowLimiter(
        limit=_SUBSCRIPTION_CHECKOUT_LIMIT,
        window_seconds=_SUBSCRIPTION_CHECKOUT_WINDOW_SECONDS,
        clock=time.monotonic,
    )


#: Subscription webhook: 30 deliveries per Paymob subscription id per minute, counted only for a
#: delivery whose HMAC verified. A real subscription sends a handful of callbacks per charge;
#: this bounds the Paymob re-fetch a replayed (genuinely signed) body can trigger. Keyed by the
#: signed id, never by IP, which would throttle Paymob itself.
_SUBSCRIPTION_WEBHOOK_LIMIT = 30
_SUBSCRIPTION_WEBHOOK_WINDOW_SECONDS = 60.0


@lru_cache(maxsize=1)
def get_subscription_webhook_limiter() -> SlidingWindowLimiter:
    """Per-subscription limiter for ``POST /api/webhooks/paymob/subscription``."""
    return SlidingWindowLimiter(
        limit=_SUBSCRIPTION_WEBHOOK_LIMIT,
        window_seconds=_SUBSCRIPTION_WEBHOOK_WINDOW_SECONDS,
        clock=time.monotonic,
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


#: How long a rendered public catalogue is served from memory. Short enough that an
#: admin price edit shows within a minute, long enough that a caller who rotates
#: ``X-Forwarded-For`` past the per-IP limiter cannot turn every request into DB reads.
_PUBLIC_CATALOGUE_TTL_SECONDS = 30.0


class PublicCatalogueCache:
    """A tiny per-audience TTL cache of the rendered public catalogue (in-process).

    Per Cloud Run instance, like the limiters. Only two audiences exist, so it is
    bounded without eviction. The clock is injected so tests drive expiry.
    """

    def __init__(self, *, ttl_seconds: float, clock: Callable[[], float]) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, PublicCatalogueDTO]] = {}

    def get(self, audience: str) -> PublicCatalogueDTO | None:
        """The cached catalogue for ``audience``, or ``None`` if absent or expired."""
        with self._lock:
            entry = self._entries.get(audience)
            if entry is None:
                return None
            stored_at, value = entry
            if self._clock() - stored_at >= self._ttl:
                del self._entries[audience]
                return None
            return value

    def put(self, audience: str, value: PublicCatalogueDTO) -> None:
        """Store ``value`` for ``audience`` from now."""
        with self._lock:
            self._entries[audience] = (self._clock(), value)


@lru_cache(maxsize=1)
def get_public_catalogue_cache() -> PublicCatalogueCache:
    """The process-wide cache behind ``GET /api/billing/public-catalogue``."""
    return PublicCatalogueCache(ttl_seconds=_PUBLIC_CATALOGUE_TTL_SECONDS, clock=time.monotonic)


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
        get_public_catalogue_cache.cache_clear()
        get_subscription_deps.cache_clear()
        get_subscription_checkout_limiter.cache_clear()
        get_subscription_webhook_limiter.cache_clear()


__all__ = [
    "PublicCatalogueCache",
    "get_billing_reconcile_job",
    "get_billing_sessionmaker",
    "get_checkout_limiter",
    "get_paymob_client",
    "get_public_catalogue_cache",
    "get_public_catalogue_limiter",
    "get_subscription_checkout_limiter",
    "get_subscription_deps",
    "get_subscription_jobs",
    "get_subscription_webhook_limiter",
    "reset_billing_singletons",
]
