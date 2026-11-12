"""Edge-trust helpers for public routes: the Worker's shared secret, the real client IP, body caps.

``lemely/web/routers/client_errors.py`` records the gap these close: the Cloud Run service is
reachable directly at its ``*.run.app`` URL, so ``X-Forwarded-For`` is whatever a direct caller
says and a per-client rate limit keyed on it binds nobody. The Cloudflare Worker
(``web/worker/index.ts``) stamps ``X-Lemely-Edge-Secret`` on every request it forwards, and
:func:`edge_caller` is the reusable dependency that checks it.

* Secret configured (``[edge] origin_secret``, plus ``origin_secret_previous`` during a
  rotation): a request without a matching header is 403, and only then is ``CF-Connecting-IP``
  (set by the Worker from Cloudflare's edge-verified address) trusted as the caller's address.
* Secret not configured (dev, tests): no refusal, and the socket peer is the address; a
  client-supplied ``CF-Connecting-IP`` is never believed.
"""

from __future__ import annotations

import hmac
import ipaddress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import Depends, HTTPException, Request
from starlette.responses import JSONResponse

from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import get_settings

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

EDGE_SECRET_HEADER: Final = "X-Lemely-Edge-Secret"  # noqa: S105 - a header name
CLIENT_IP_HEADER: Final = "CF-Connecting-IP"


@dataclass(frozen=True, slots=True)
class EdgeCaller:
    """``ip`` keys rate limits; ``via_edge`` is true only when the secret matched."""

    ip: str
    via_edge: bool


def _accepted_secrets(settings: Settings) -> list[str]:
    """The non-empty secrets a request may carry: the current one and the one being rotated out."""
    candidates = (settings.edge.origin_secret, settings.edge.origin_secret_previous)
    return [value for c in candidates if c is not None and (value := c.get_secret_value())]


def rate_limit_key(ip: str) -> str:
    """The key a per-client rate limit is charged to.

    An IPv4 address is its own key. An IPv6 address maps to its /64: a single subscriber is
    routinely handed a whole /64, so keying on the full address would let one machine rotate
    through 2**64 fresh buckets. An IPv4-mapped IPv6 address is treated as the IPv4 it wraps;
    anything unparseable (``"unknown"``) is its own key.
    """
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def edge_caller(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> EdgeCaller:
    """Refuse a request that skipped the Worker (when a secret is set); resolve the client IP.

    The header may match the current secret or the previous one (rotation). Every accepted value
    is compared, in constant time, so neither the match nor which one matched shows in timing.
    An empty configured value is never accepted, so an empty header cannot match it.
    """
    peer = request.client.host if request.client else "unknown"
    accepted = _accepted_secrets(settings)
    if not accepted:
        return EdgeCaller(peer, via_edge=False)
    supplied = request.headers.get(EDGE_SECRET_HEADER, "").encode()
    matched = False
    for secret in accepted:
        matched |= hmac.compare_digest(supplied, secret.encode())
    if not supplied or not matched:
        raise HTTPException(status_code=403, detail="Forbidden")
    forwarded = request.headers.get(CLIENT_IP_HEADER, "").strip()
    return EdgeCaller(forwarded or peer, via_edge=True)


class BodyLimitMiddleware:
    """Cap request bodies on chosen routes, enforced while they are read.

    Pure ASGI, scoped to ``paths`` and ``methods`` so no other route is affected.

    * A declared ``Content-Length`` over ``limit`` is answered 413 here, before the application
      (and so FastAPI's body parsing) runs and before any body byte is read.
    * Otherwise the body the application reads is counted as it streams in, and the moment it
      passes ``limit`` the read raises a 413: a chunked or lying-length body is cut off after at
      most one chunk past the limit rather than buffered whole. Starlette's exception handling
      turns that into the same 413 JSON answer.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        limit: int,
        paths: frozenset[str],
        methods: frozenset[str] = frozenset({"POST", "PATCH", "PUT"}),
    ) -> None:
        self._app = app
        self._limit = limit
        self._paths = paths
        self._methods = methods

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["path"] not in self._paths
            or scope["method"] not in self._methods
        ):
            await self._app(scope, receive, send)
            return
        detail = f"Body exceeds {self._limit} byte limit."
        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self._limit:
                    await JSONResponse({"detail": detail}, status_code=413)(scope, receive, send)
                    return
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self._limit:
                    raise HTTPException(status_code=413, detail=detail)
            return message

        await self._app(scope, counted, send)
