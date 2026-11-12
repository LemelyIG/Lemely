"""Anonymous, rate-limited ingest for browser-side crash reports.

``POST /api/client-errors`` is the one deliberately unauthenticated,
unauthorized route this file adds (see the ``PUBLIC`` entry for it in
``tests/test_authz_matrix_complete.py``) — every other route in this app
requires a bearer token. That is not an oversight: the React app's
``ErrorBoundary`` and its ``window``-level ``error``/``unhandledrejection``
listeners must still be able to report a crash that happens *before* a user
has signed in — a broken login screen is exactly the case this route exists
for — and a route gated behind ``get_auth_context`` would swallow precisely
those reports.

**Production topology** (see ``web/worker/index.ts``): browser → a Cloudflare
Worker that proxies ``/api/*`` and stamps ``X-Forwarded-For``/``X-Real-IP``
from Cloudflare's edge-verified ``CF-Connecting-IP`` → this Cloud Run service.
:func:`_client_ip` reads those headers (falling back to the ASGI-level peer
address, then the literal string ``"unknown"``) purely to key the rate
limiter below — it is never treated as an authenticated identity, and no
route in this app ever will be on the strength of an IP address alone.

**The per-client limiter only binds traffic that actually came through the
Worker.** ``docs/ci-cd.md`` ("Known gaps this setup doesn't close") records,
as a known live gap, that this Cloud Run service is reachable directly
(``--allow-unauthenticated``) at its ``*.run.app`` URL, bypassing the Worker
entirely. A caller who hits that URL directly controls its own
``X-Forwarded-For`` header — a fresh, unverified value on every request
buys a fresh :func:`_client_ip` bucket each time, so :attr:`ClientErrorLimiters.per_client`
does nothing for that caller. What still holds regardless of how the request
arrived is the shared cap: at most 300 accepted reports per minute, each at
most about 19 000 characters (see :class:`~lemely.web.schemas_client_errors.ClientErrorReportDTO`'s
``max_length``s). Making the per-client limit honest against a direct caller
needs the shared-secret header ``docs/ci-cd.md`` proposes there (the Worker
stamps it, a small FastAPI middleware checks it) — infrastructure work out of
scope for this route.

**There is no database row for a report.** The only sink is Cloud Logging: an
accepted report becomes one structured ``client_error`` event
(``lemely.runtime.logging`` ships JSON to stderr, which Cloud Run forwards on
to Cloud Logging), logged at **``warning``**, not ``error`` — a client report
is evidence about something that went wrong in a browser, not proof this
process did anything wrong, and answering one is not this endpoint failing.

**Anonymous, plus "the only sink is a shared log stream", is exactly why this
route must be rate-limited and size-capped**: with no auth and no per-caller
allowance to spend, an unthrottled version of this route would let anyone
flood Cloud Logging — and its bill — for free. Two independent
:class:`~lemely.web.ratelimit.SlidingWindowLimiter` instances
(:func:`~lemely.web.deps.get_client_error_limiters`) guard the one thing worth
guarding, the volume of *accepted* reports (i.e. the volume that actually
reaches the log sink): 10 per :func:`_client_ip` per minute, and 300 across
every caller per minute. A flood of malformed bodies fails pydantic validation
before either limiter is even consulted — that costs this route nothing to
answer and writes no log line, so there is nothing there worth throttling.
:func:`_reject_oversized_content_length` separately rejects an oversized
request by its declared ``Content-Length`` before pydantic ever parses the
body — see that function's own docstring for exactly what it does and does
not bound.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from lemely.web.deps import ClientErrorLimiters, get_client_error_limiters
from lemely.web.schemas_client_errors import ClientErrorAcceptedDTO, ClientErrorReportDTO

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api")

# 96 KiB. The DTO's own per-field max_length is in *characters*, not bytes:
# message (2000) + stack (8000) + componentStack (8000) + route (500) +
# buildId (64) + userAgent (500) = 19064 chars at the very most, and a
# character can cost up to 4 bytes in UTF-8 (astral-plane characters —
# emoji, some CJK — are exactly this worst case), so a DTO-valid report can
# be ~19064 * 4 ≈ 74.5 KB of text alone before the JSON structure (field
# names, quotes, commas, braces) around it is even counted. 32 KiB — this
# constant's old value — undercounted that and could 413 a legitimate report
# with enough multi-byte content. 96 KiB comfortably covers the ~75 KB worst
# case with headroom for structure, and is still small enough that the
# global limiter's worst case (300 requests/minute) tops out around 28 MB.
_MAX_BODY_BYTES = 96 * 1024
_OVERSIZED_DETAIL = f"Client error report exceeds {_MAX_BODY_BYTES} byte limit."

# The key the global limiter tracks its one shared bucket under. Not a real
# client identity — SlidingWindowLimiter is keyed by arbitrary strings, and
# "every caller shares this one" is what makes a limiter instance global
# rather than per-client.
_GLOBAL_LIMITER_KEY = "__global__"


def _client_ip(request: Request) -> str:
    """Best-effort caller IP, for keying the per-client limiter only.

    Prefers the leftmost hop of ``X-Forwarded-For`` (the Cloudflare Worker
    sets this from ``CF-Connecting-IP``, see the module docstring), then
    ``X-Real-IP``, then the ASGI-level peer address, then the literal string
    ``"unknown"`` — which means every caller with no identifying header at all
    shares one rate-limit bucket, never that the request is refused for
    lacking one.

    This trusts ``X-Forwarded-For`` as-is, which is only honest for a request
    that actually transited the Cloudflare Worker. A caller reaching this
    Cloud Run service directly (see the module docstring's "per-client
    limiter only binds..." section) can set that header to anything,
    including a fresh value per request — for that caller this function
    still returns *a* key, but not one that binds them to a shared bucket
    across requests, so only the global limiter constrains them.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_hop = forwarded_for.split(",", 1)[0].strip()
        if first_hop:
            return first_hop
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def _reject_oversized_content_length(request: Request) -> None:
    """Reject a declared oversized body with 413 before pydantic parses it.

    FastAPI resolves every route ``Depends`` — this one included, wired via
    the route decorator's ``dependencies=`` below — before it validates the
    request body against its declared model
    (``fastapi.dependencies.utils.solve_dependencies`` walks
    ``dependant.dependencies`` first and ``dependant.body_params`` only
    after), so this 413 always beats pydantic ever seeing an oversized
    payload.

    **Limitation, stated as plainly as
    :class:`~lemely.auth.cooldown.CooldownStore`'s own docstring states its
    own.** This checks the *declared* ``Content-Length`` header only. It does
    not — and short of app-wide ASGI middleware, out of scope here, could not
    — bound the bytes Starlette itself reads for a request that omits the
    header or understates it (chunked transfer encoding). Every JSON-body
    route in this app shares that same characteristic; this route is not a
    weaker version of them, only an anonymous one. A missing or unparsable
    header is therefore treated as "unknown" and let through to ordinary
    validation rather than guessed at. What *does* bound an accepted report
    regardless is
    :class:`~lemely.web.schemas_client_errors.ClientErrorReportDTO`'s own
    per-field ``max_length``s — about 19 000 characters at the very most.
    """
    declared = request.headers.get("content-length")
    if declared is None:
        return
    try:
        declared_bytes = int(declared)
    except ValueError:
        return  # Malformed header: not a signal we trust either way.
    if declared_bytes > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail=_OVERSIZED_DETAIL)


def _rate_limited(retry_after: int) -> HTTPException:
    """Build the 429 both limiters below answer with, ``Retry-After`` included."""
    return HTTPException(
        status_code=429,
        detail=f"Too many client error reports; retry in {retry_after}s.",
        headers={"Retry-After": str(retry_after)},
    )


@router.post(
    "/client-errors",
    response_model=ClientErrorAcceptedDTO,
    status_code=202,
    dependencies=[Depends(_reject_oversized_content_length)],
)
def report_client_error(
    request: Request,
    body: ClientErrorReportDTO,
    limiters: Annotated[ClientErrorLimiters, Depends(get_client_error_limiters)],
) -> ClientErrorAcceptedDTO:
    """Accept one browser-side crash report and log it as a structured event.

    No auth dependency (see the module docstring) — every caller is throttled
    instead: 10 accepted reports per :func:`_client_ip` per minute, and 300
    across every caller per minute, either of which answers **429** with a
    ``Retry-After`` header once exceeded. The body is never echoed back — the
    response is a bare acknowledgement.
    """
    # Per-client is consulted first, deliberately. The alternative (global
    # first) would let one IP burn the *entire* shared 300/min budget on
    # requests that all get rejected once its own 10 are gone — silencing
    # every other caller's reports for the rest of the window. Per-client
    # first bounds the damage one address can do to the shared budget to its
    # own 10 slots, at the cost of an honest caller sometimes burning some of
    # its 10 per-client slots on a request that the global limiter would have
    # rejected anyway during a global flood. That trade is intentional.
    client_ip = _client_ip(request)
    if not limiters.per_client.allow(client_ip):
        raise _rate_limited(limiters.per_client.retry_after(client_ip))
    if not limiters.global_.allow(_GLOBAL_LIMITER_KEY):
        raise _rate_limited(limiters.global_.retry_after(_GLOBAL_LIMITER_KEY))

    # warning, not error: a client report is evidence about a browser-side
    # failure, not proof this process did anything wrong (see module docstring).
    log.warning(
        "client_error",
        kind=body.kind,
        message=body.message,
        route=body.route,
        build_id=body.buildId,
        client_ip=client_ip,
        user_agent=body.userAgent,
        occurred_at=body.occurredAt.isoformat() if body.occurredAt else None,
        stack=body.stack,
        component_stack=body.componentStack,
    )
    return ClientErrorAcceptedDTO()
