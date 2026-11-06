"""Anonymous, rate-limited ``POST /api/contact`` for the landing page FAQ composer.

A signed-out visitor types a question and their address; this route emails it to
``[email] contact_address`` through the same :class:`~lemely.auth.email.EmailProvider`
seam the verification mails use (Reply-To is the visitor, so the team answers
directly). Like ``POST /api/client-errors`` it is deliberately public (see its
``PUBLIC`` entry in ``tests/test_authz_matrix_complete.py``), so it is
throttled per caller IP and across all callers
(:func:`~lemely.web.deps.get_contact_limiters`) and size-capped by declared
``Content-Length``. The per-IP limit only binds traffic that came through the
Cloudflare Worker; the global cap, sized under Resend's free daily quota,
binds everyone. See :mod:`lemely.web.routers.client_errors` for that reasoning.

A provider failure answers 502 with a fixed message and is logged without the
visitor's text.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from lemely.auth.email import EmailProvider  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import ContactLimiters, get_contact_limiters, get_email_provider
from lemely.web.routers.client_errors import _client_ip
from lemely.web.schemas_contact import ContactAcceptedDTO, ContactMessageDTO

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api")

_MAX_BODY_BYTES = 8 * 1024
_GLOBAL_LIMITER_KEY = "__global__"
_SEND_FAILED_DETAIL = "Could not send your message. Please email contact@lemelyig.com."


def _reject_oversized_content_length(request: Request) -> None:
    """Reject a declared body over 8 KiB with 413 before pydantic parses it.

    Checks the declared ``Content-Length`` only, like the client-errors guard; a
    missing or malformed header falls through to the DTO's own field caps.
    """
    declared = request.headers.get("content-length")
    if declared is None:
        return
    try:
        declared_bytes = int(declared)
    except ValueError:
        return
    if declared_bytes > _MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413, detail=f"Message exceeds {_MAX_BODY_BYTES} byte limit."
        )


def _rate_limited(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=f"Too many messages; retry in {retry_after}s.",
        headers={"Retry-After": str(retry_after)},
    )


@router.post(
    "/contact",
    response_model=ContactAcceptedDTO,
    status_code=202,
    dependencies=[Depends(_reject_oversized_content_length)],
)
def send_contact_message(
    request: Request,
    body: ContactMessageDTO,
    limiters: Annotated[ContactLimiters, Depends(get_contact_limiters)],
    provider: Annotated[EmailProvider, Depends(get_email_provider)],
) -> ContactAcceptedDTO:
    """Email one landing-page question to the team.

    Per-client limiter first, so one address cannot drain the shared daily
    budget on requests that are all rejected (same ordering as client-errors).
    """
    client_ip = _client_ip(request)
    if not limiters.per_client.allow(client_ip):
        raise _rate_limited(limiters.per_client.retry_after(client_ip))
    if not limiters.global_.allow(_GLOBAL_LIMITER_KEY):
        raise _rate_limited(limiters.global_.retry_after(_GLOBAL_LIMITER_KEY))

    try:
        provider.send_contact_message(body.email, body.message.strip())
    except Exception as exc:
        # Never log or echo the visitor's text: type name only.
        log.warning("contact_send_failed", error_type=type(exc).__name__, client_ip=client_ip)
        raise HTTPException(status_code=502, detail=_SEND_FAILED_DETAIL) from None
    return ContactAcceptedDTO(accepted=True)
