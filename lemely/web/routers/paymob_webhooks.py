"""Paymob callbacks (billing spec §5.1 step 4, §5.5, §6; research 02 §1-§2).

``POST /api/webhooks/paymob/transaction?hmac=…`` receives both callback types
Paymob sends to an intention's ``notification_url``: ``"type": "TRANSACTION"``
(the Transaction Processed callback) and ``"type": "TOKEN"`` (a saved card). The
HMAC is in the query string for both. Order of operations:

1. No HMAC secret configured -> 503 (Paymob retries once we are configured).
2. Body over 64 KiB -> 413, counted as it streams, before any parsing. Not JSON,
   not an object, or an ``obj`` that is not an object -> 400.
3. HMAC mismatch or missing -> 401, logged at error level. The 401 is decided first and
   the database is not reached to decide it. Once the response is sent (a background task),
   one row goes to
   ``paymob_webhook_failures`` (kind, a fixed reason, the best-effort caller address; never
   the body, the HMAC or the object id) in its own transaction, capped at 60 rows per
   minute per process. A failure to record never changes the 401.
4. Verified -> one ``sessionmaker.begin()`` transaction applies it; the 200 is
   sent only after that commits. Duplicates and unknown references are 200
   no-ops inside :class:`BillingService`, so Paymob stops retrying them. A
   callback the service rejects as malformed (including a TOKEN body whose fields
   have the wrong shape) is 400, logged at error level. Any other failure rolls the
   transaction back and answers 500, so Paymob retries; the log line carries the
   exception type only, never its message (a driver error can echo parameters).

Any other ``type`` (Paymob also has delivery-status callbacks) is acknowledged
with 200 and ignored: no state changes, so no verification is needed.

PUBLIC by necessity: Paymob holds no Lemely token. Authenticity is the HMAC
alone (Paymob publishes no source IPs). Not rate-limited: a limiter keyed by IP
would throttle Paymob itself. This application never logs the raw body, card tokens
or the received HMAC. The HMAC is a query parameter, so it does appear in the access
logs of uvicorn and Cloud Run; it signs one finished transaction and grants nothing
that the callback itself would not.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Annotated, Final

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session, sessionmaker  # noqa: TC002 - FastAPI reads the type at runtime
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse

from lemely.db.billing_observability_repo import record_webhook_failure
from lemely.db.billing_repo import BillingService, MalformedCallback
from lemely.io.paymob.client import PaymobClient  # noqa: TC001 - FastAPI reads the type at runtime
from lemely.io.paymob.hmac import verify_token_hmac, verify_transaction_hmac
from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI reads the type at runtime
from lemely.web.deps import get_settings
from lemely.web.deps_billing import get_billing_sessionmaker, get_paymob_client
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.routers.client_errors import _client_ip

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/webhooks/paymob")

# A real transaction callback is a few KiB; 64 KiB is generous and bounds what an
# unauthenticated caller can make us buffer and hash.
_MAX_BODY_BYTES: Final = 64 * 1024

_VERIFIERS = {"TRANSACTION": verify_transaction_hmac, "TOKEN": verify_token_hmac}

# The ``paymob_webhook_failures.kind`` each verified callback type is filed under.
_FAILURE_KINDS: Final = {"TRANSACTION": "transaction", "TOKEN": "token"}

# One alert line per minute when the failure writer's own cap drops rows, so a flood of bad
# signatures is visible without the log growing with it. Process-local, like the writer's cap.
_UNRECORDED_ALERT = SlidingWindowLimiter(limit=1, window_seconds=60.0, clock=time.monotonic)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _record_hmac_failure(
    sm: sessionmaker[Session], *, kind: str, hmac_present: bool, remote_addr: str, now: datetime
) -> None:
    """File a refused callback for the admin problem queue, after the 401 has been sent.

    Runs as a Starlette background task, so the write never delays the response, and any
    failure (the database down, the table missing) is logged by type only: a driver error
    message can echo bound parameters.
    """
    try:
        recorded = record_webhook_failure(
            sm,
            kind=kind,
            reason="hmac_mismatch" if hmac_present else "hmac_missing",
            remote_addr=remote_addr,
            now=now,
        )
    except Exception as exc:
        log.error("paymob_hmac_failure_record_failed", kind=kind, error_type=type(exc).__name__)
        return
    if not recorded and _UNRECORDED_ALERT.allow("unrecorded"):
        log.error("paymob_hmac_failure_unrecorded", alert=True, kind=kind)


def _hmac_secret(settings: Annotated[Settings, Depends(get_settings)]) -> str:
    """The configured HMAC secret, or 503 so Paymob retries until we are configured."""
    secret = settings.paymob.hmac_secret
    if secret is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Paymob webhooks are not configured"
        )
    return secret.get_secret_value()


def _too_large() -> HTTPException:
    return HTTPException(
        status.HTTP_413_CONTENT_TOO_LARGE, f"Callback exceeds {_MAX_BODY_BYTES} byte limit"
    )


async def _callback_body(request: Request) -> dict[str, object]:
    """The request body as a JSON object, read under the size cap.

    The declared ``Content-Length`` rejects an honest oversized body at once; the
    streamed byte count catches a chunked one that declares nothing.
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
        except ValueError:
            declared_bytes = 0
        if declared_bytes > _MAX_BODY_BYTES:
            raise _too_large()
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > _MAX_BODY_BYTES:
            raise _too_large()
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks))
    except (ValueError, RecursionError) as exc:  # UnicodeDecodeError is a ValueError
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Callback body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Callback body is not an object")
    return body


@router.post("/transaction", response_model=None)
def paymob_transaction_callback(
    request: Request,
    secret: Annotated[str, Depends(_hmac_secret)],
    body: Annotated[dict[str, object], Depends(_callback_body)],
    settings: Annotated[Settings, Depends(get_settings)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
    client: Annotated[PaymobClient, Depends(get_paymob_client)],
    hmac: Annotated[str | None, Query()] = None,
) -> dict[str, str] | JSONResponse:
    """Verify and apply a Paymob transaction or card-token callback."""
    kind = body.get("type")
    verifier = _VERIFIERS.get(kind) if isinstance(kind, str) else None
    if verifier is None:
        log.info("paymob_callback_ignored", callback_type=str(kind)[:40])
        return {"status": "ignored"}
    obj = body.get("obj")
    if not isinstance(obj, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Callback has no obj")
    if not verifier(obj, hmac or "", secret):
        log.error(
            "paymob_hmac_mismatch",
            callback_type=kind,
            obj_id=str(obj.get("id"))[:40],
            hmac_present=bool(hmac),
        )
        # The 401 is decided; the row is written after it is sent (a background task is not
        # run for a raised ``HTTPException``, so the response is built here). The body is the
        # one ``HTTPException`` would have produced.
        return JSONResponse(
            {"detail": "HMAC verification failed"},
            status_code=status.HTTP_401_UNAUTHORIZED,
            background=BackgroundTask(
                _record_hmac_failure,
                sm,
                kind=_FAILURE_KINDS[str(kind)],
                hmac_present=bool(hmac),
                remote_addr=_client_ip(request),
                now=_utcnow(),
            ),
        )
    try:
        with sm.begin() as session:
            service = BillingService(session, client, settings.paymob)
            if kind == "TRANSACTION":
                service.apply_transaction_callback(obj)
            else:
                service.apply_token_callback(obj)
    except MalformedCallback as exc:
        # Signed yet malformed: a re-split signature, or a Paymob format change. Worth a
        # human look, so error level, with the type and a truncated id only.
        log.error(
            "paymob_callback_malformed",
            callback_type=kind,
            obj_id=str(obj.get("id"))[:40],
            reason=str(exc)[:120],
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:
        # sm.begin() has rolled back. Answer 5xx so Paymob retries; never a 200 for
        # a change that did not commit. Type only: a driver error message can echo
        # bound parameters.
        log.error(
            "paymob_callback_failed",
            callback_type=kind,
            obj_id=str(obj.get("id"))[:40],
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Callback could not be processed"
        ) from None
    return {"status": "ok"}
