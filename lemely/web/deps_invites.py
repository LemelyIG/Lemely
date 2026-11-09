"""Dependencies for the public invite preview, ``GET /api/invites/{code}``.

Process-wide, lazily built singletons, the ``lru_cache`` pattern of
``lemely.web.deps_billing``; tests override them through ``app.dependency_overrides``.
``deps.reset_singletons`` calls :func:`reset_invite_singletons`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache

from lemely.web.ratelimit import SlidingWindowLimiter

#: Public invite preview (no auth): 60 reads per client IP per minute. A class join
#: code is unlimited-use and widely shared, so the route is a guessing oracle for
#: anyone who can send requests; the preview no longer returns anything private (no
#: email), so this bounds enumeration of which codes exist, not a secret. 60 rather
#: than a tighter number because a whole classroom behind one school NAT previews the
#: same code within a minute and must not lock itself out.
#:
#: Keyed by the same ``_client_ip`` the contact form and the public catalogue use, with
#: the same caveat (``ClientErrorLimiters`` in ``deps.py``): ``per_client`` binds only a
#: caller that arrives through the Cloudflare Worker. A direct caller of the Cloud Run
#: URL can rotate ``X-Forwarded-For``; for that caller ``global_`` is the only bound.
_INVITE_PREVIEW_PER_CLIENT_LIMIT = 60
_INVITE_PREVIEW_PER_CLIENT_WINDOW_SECONDS = 60.0

#: Aggregate ceiling across every caller: 1200 previews per minute (20 a second), far
#: above any real join rush (a few hundred students opening one code) and low enough
#: that a rotating-header guesser cannot sweep the code space.
_INVITE_PREVIEW_GLOBAL_LIMIT = 1200
_INVITE_PREVIEW_GLOBAL_WINDOW_SECONDS = 60.0

#: The key the global limiter tracks its one shared bucket under. Not a real client
#: identity: ``SlidingWindowLimiter`` is keyed by arbitrary strings.
INVITE_PREVIEW_GLOBAL_KEY = "__global__"


@dataclass(frozen=True, slots=True)
class InvitePreviewLimiters:
    """The two :class:`SlidingWindowLimiter` instances guarding the public preview.

    ``per_client`` throttles one caller, keyed by IP; ``global_`` caps the route's
    aggregate volume regardless of caller.
    """

    per_client: SlidingWindowLimiter
    global_: SlidingWindowLimiter


@lru_cache(maxsize=1)
def get_invite_preview_limiters() -> InvitePreviewLimiters:
    """The process-wide limiters for ``GET /api/invites/{code}``.

    Wired with ``time.monotonic``; tests override this dependency with limiters built
    on a fake clock, so no test sleeps out a 60-second window.
    """
    return InvitePreviewLimiters(
        per_client=SlidingWindowLimiter(
            limit=_INVITE_PREVIEW_PER_CLIENT_LIMIT,
            window_seconds=_INVITE_PREVIEW_PER_CLIENT_WINDOW_SECONDS,
            clock=time.monotonic,
        ),
        global_=SlidingWindowLimiter(
            limit=_INVITE_PREVIEW_GLOBAL_LIMIT,
            window_seconds=_INVITE_PREVIEW_GLOBAL_WINDOW_SECONDS,
            clock=time.monotonic,
        ),
    )


def reset_invite_singletons() -> None:
    """Clear this module's cached providers (``deps.reset_singletons`` does not know them)."""
    get_invite_preview_limiters.cache_clear()


__all__ = [
    "INVITE_PREVIEW_GLOBAL_KEY",
    "InvitePreviewLimiters",
    "get_invite_preview_limiters",
    "reset_invite_singletons",
]
