"""Rate limiters for the invite routes: the public preview and the authenticated redeem.

Process-wide, lazily built singletons, the ``lru_cache`` pattern of
``lemely.web.deps_billing``; tests override them through ``app.dependency_overrides``.

**Wiring pending.** :func:`reset_invite_singletons` is not yet called from
``deps.reset_singletons``: ``deps.py`` is being edited by a concurrent change, so the
one-line call is left for its owner to add. Until then a test that wants clean limiters
calls :func:`reset_invite_singletons` itself.

**Every limit here is per Cloud Run instance** (``SlidingWindowLimiter`` is
in-process), and the service runs with ``max-instances=3``. The effective ceilings are
therefore up to three times the constants below, and a flood spread over instances
fills each budget separately. They are deterrents, not a security boundary.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache

from lemely.web.ratelimit import SlidingWindowLimiter

# -- Public preview: GET /api/invites/{code} ---------------------------------------

#: Per client IP, every preview call counts: 240 per minute. High on purpose: a whole
#: classroom behind one school NAT previews the same code within a minute and must not
#: lock itself out. The preview no longer returns anything private (no email), so this
#: bounds enumeration of which codes exist, not a secret.
#:
#: Keyed by the same ``_client_ip`` the contact form and the public catalogue use, with
#: the same caveat (``ClientErrorLimiters`` in ``deps.py``): ``per_client`` binds only a
#: caller that arrives through the Cloudflare Worker. A direct caller of the Cloud Run
#: URL can rotate ``X-Forwarded-For`` and get a fresh bucket each time; for that caller
#: the global miss budget below is the only bound.
_INVITE_PREVIEW_PER_CLIENT_LIMIT = 240
_INVITE_PREVIEW_PER_CLIENT_WINDOW_SECONDS = 60.0

#: Global budget of *misses* only: 300 unknown codes per minute across every caller. A
#: request that resolves a real code never consumes it, so a flood of valid previews
#: cannot lock students out; only guessing (unknown codes) spends it. Once spent, the
#: route refuses new requests, hits included, until the window rolls, so a flood of
#: guesses can still hold the route shut for its duration. That is the price of making
#: a sweep of the code space impossible, and a real join rush produces almost no misses.
_INVITE_PREVIEW_GLOBAL_MISS_LIMIT = 300
_INVITE_PREVIEW_GLOBAL_MISS_WINDOW_SECONDS = 60.0

#: The key the global miss limiter tracks its one shared bucket under. Not a real client
#: identity: ``SlidingWindowLimiter`` is keyed by arbitrary strings.
INVITE_PREVIEW_GLOBAL_KEY = "__global__"


@dataclass(frozen=True, slots=True)
class InvitePreviewLimiters:
    """The two :class:`SlidingWindowLimiter` instances guarding the public preview.

    ``per_client`` throttles one caller (keyed by IP) on every call. ``global_misses``
    caps unknown-code lookups across all callers: the route checks it before the lookup
    (``retry_after`` > 0 means spent) and records a miss with ``allow`` only on a 404.
    """

    per_client: SlidingWindowLimiter
    global_misses: SlidingWindowLimiter


@lru_cache(maxsize=1)
def get_invite_preview_limiters() -> InvitePreviewLimiters:
    """The process-wide limiters for ``GET /api/invites/{code}``.

    Wired with ``time.monotonic``; tests override this dependency with limiters built
    on a fake clock, so no test sleeps out a window.
    """
    return InvitePreviewLimiters(
        per_client=SlidingWindowLimiter(
            limit=_INVITE_PREVIEW_PER_CLIENT_LIMIT,
            window_seconds=_INVITE_PREVIEW_PER_CLIENT_WINDOW_SECONDS,
            clock=time.monotonic,
        ),
        global_misses=SlidingWindowLimiter(
            limit=_INVITE_PREVIEW_GLOBAL_MISS_LIMIT,
            window_seconds=_INVITE_PREVIEW_GLOBAL_MISS_WINDOW_SECONDS,
            clock=time.monotonic,
        ),
    )


# -- Authenticated redeem: POST /api/invites/{code}/redeem -------------------------

#: Per user, every redeem attempt counts: 30 per 10 minutes. A real user redeems one
#: code; a retry after a typo or a refusal needs a few more.
_INVITE_REDEEM_PER_USER_LIMIT = 30
_INVITE_REDEEM_PER_USER_WINDOW_SECONDS = 600.0

#: Per user, unknown codes only: 10 per hour. The redeem route answers 404 / 403 / 409
#: differently, so an account probing codes learns which exist from the status alone;
#: only the 404s (guesses) are counted, and once spent the user is refused with 429
#: before any lookup. A real user mistypes a code a few times at most.
_INVITE_REDEEM_MISS_LIMIT = 10
_INVITE_REDEEM_MISS_WINDOW_SECONDS = 3600.0


@dataclass(frozen=True, slots=True)
class InviteRedeemLimiters:
    """The two per-user :class:`SlidingWindowLimiter` instances guarding redeem.

    ``per_user`` counts every attempt (``allow``). ``misses`` is checked before the
    lookup (``retry_after`` > 0 means spent) and records with ``allow`` only on a 404.
    Both are keyed by the authenticated user id.
    """

    per_user: SlidingWindowLimiter
    misses: SlidingWindowLimiter


@lru_cache(maxsize=1)
def get_invite_redeem_limiters() -> InviteRedeemLimiters:
    """The process-wide limiters for ``POST /api/invites/{code}/redeem``."""
    return InviteRedeemLimiters(
        per_user=SlidingWindowLimiter(
            limit=_INVITE_REDEEM_PER_USER_LIMIT,
            window_seconds=_INVITE_REDEEM_PER_USER_WINDOW_SECONDS,
            clock=time.monotonic,
        ),
        misses=SlidingWindowLimiter(
            limit=_INVITE_REDEEM_MISS_LIMIT,
            window_seconds=_INVITE_REDEEM_MISS_WINDOW_SECONDS,
            clock=time.monotonic,
        ),
    )


def reset_invite_singletons() -> None:
    """Clear this module's cached providers (``deps.reset_singletons`` does not know them yet)."""
    get_invite_preview_limiters.cache_clear()
    get_invite_redeem_limiters.cache_clear()


__all__ = [
    "INVITE_PREVIEW_GLOBAL_KEY",
    "InvitePreviewLimiters",
    "InviteRedeemLimiters",
    "get_invite_preview_limiters",
    "get_invite_redeem_limiters",
    "reset_invite_singletons",
]
