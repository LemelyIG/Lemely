"""Anonymous, rate-limited landing-page waitlist: ``POST``/``PATCH /api/waitlist`` + the digest.

Two unauthenticated writes, like :mod:`lemely.web.routers.contact` (and listed ``PUBLIC`` in
``tests/test_authz_matrix_complete.py``):

* ``POST /api/waitlist`` (step 1) creates a partial applicant from email, name, role, UTM tags and
  the consent version, and returns a one-time completion token. An address already on the list
  gets ``{"status": "already_listed"}`` with **no token and no change**, so nobody can
  overwrite another applicant's details. The two outcomes run the same single statement.
* ``PATCH /api/waitlist`` (step 2) redeems the token (24 hours, single use) with the optional
  detail. An unknown, expired or used token is 400.

Both are throttled per caller IP and across all callers (:func:`get_waitlist_limiters`),
capped at 8 KiB by :class:`lemely.web.edge.BodyLimitMiddleware` (installed in ``create_app`` for
``POST``/``PATCH /api/waitlist`` only: a declared ``Content-Length`` over the cap is answered 413
before the app runs, and a chunked or lying body is cut off with 413 as it streams in), and carry
a honeypot field (``website``): a filled one is answered with a normal-looking success and
nothing is stored.

Step 1 also needs a Cloudflare Turnstile token (``turnstileToken``) when
``[waitlist] turnstile_secret_key`` is set; verification fails closed (403). All the public
waitlist routes use the edge guard (:func:`lemely.web.edge.edge_caller`): with
``[edge] origin_secret`` set, a request that did not come through the Worker is 403, and the
rate limiter is keyed on the Worker-verified ``CF-Connecting-IP``; otherwise on the socket peer.
The consent wording is owned by the server: the client names a ``consentVersion`` and the stored
text is the canonical one (unknown version is 422).

``POST /api/internal/waitlist/digest`` is the daily team digest trigger. It is not a user
route: Cloud Scheduler calls it with ``X-Cron-Secret`` equal to ``[waitlist] digest_secret``.
With no secret configured it answers 404; a wrong or missing header is 403.
"""

from __future__ import annotations

import hmac
import secrets
from typing import TYPE_CHECKING, Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException

from lemely.auth.email import EmailProvider  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.core.waitlist import CONSENT_VERSIONS, CURRENT_CONSENT_VERSION
from lemely.db.session import get_sessionmaker
from lemely.db.waitlist_repo import CompletionDetails, WaitlistRepository
from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import (
    WaitlistLimiters,
    get_email_provider,
    get_settings,
    get_turnstile_verifier,
    get_waitlist_limiters,
)
from lemely.web.edge import EdgeCaller, edge_caller, rate_limit_key
from lemely.web.schemas_waitlist import (
    WaitlistCompletedDTO,
    WaitlistCompleteDTO,
    WaitlistConfigDTO,
    WaitlistCreatedDTO,
    WaitlistCreateDTO,
    WaitlistDigestResultDTO,
)
from lemely.web.turnstile import TurnstileVerifier  # noqa: TC001 - FastAPI resolves it
from lemely.web.waitlist_digest import send_waitlist_digest

if TYPE_CHECKING:
    from lemely.web.ratelimit import SlidingWindowLimiter

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api")

MAX_BODY_BYTES = 8 * 1024
#: Paths the body-size middleware guards (installed in ``create_app``).
BODY_LIMITED_PATHS = frozenset({"/api/waitlist"})
_GLOBAL_LIMITER_KEY = "__global__"
_TURNSTILE_DETAIL = "turnstile_failed"
_REFUSED_DETAIL = "This link has expired or was already used."
_DIGEST_FAILED_DETAIL = "Could not send the digest."
_DIGEST_PENDING_DETAIL = "digest_pending"


def get_waitlist_repo() -> WaitlistRepository:
    """A :class:`WaitlistRepository` on the process-wide sessionmaker (cheap; not cached)."""
    return WaitlistRepository(get_sessionmaker(get_settings()))


def _too_many(limiter: SlidingWindowLimiter, key: str) -> HTTPException:
    retry_after = limiter.retry_after(key)
    return HTTPException(
        status_code=429,
        detail=f"Too many requests; retry in {retry_after}s.",
        headers={"Retry-After": str(retry_after)},
    )


def _charge_client(caller: EdgeCaller, limiters: WaitlistLimiters) -> None:
    """Charge the per-client limit (IPv6 callers by their /64). Cheap, and one caller's own."""
    key = rate_limit_key(caller.ip)
    if not limiters.per_client.allow(key):
        raise _too_many(limiters.per_client, key)


def _charge_global(limiters: WaitlistLimiters) -> None:
    """Charge the shared daily budget. Only requests that passed the cheap checks reach it."""
    if not limiters.global_.allow(_GLOBAL_LIMITER_KEY):
        raise _too_many(limiters.global_, _GLOBAL_LIMITER_KEY)


@router.get("/waitlist/config", response_model=WaitlistConfigDTO)
def waitlist_config(
    _caller: Annotated[EdgeCaller, Depends(edge_caller)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> WaitlistConfigDTO:
    """Public page settings: Turnstile's site key (only when enforced) and the consent wording.

    The form renders the exact text the server will store for ``consentVersion``.
    """
    enforced = settings.waitlist.turnstile_secret_key is not None
    return WaitlistConfigDTO(
        turnstileSiteKey=settings.waitlist.turnstile_site_key if enforced else None,
        consentVersion=CURRENT_CONSENT_VERSION,
        consentText=CONSENT_VERSIONS[CURRENT_CONSENT_VERSION],
    )


@router.post(
    "/waitlist",
    response_model=WaitlistCreatedDTO,
    response_model_exclude_none=True,
)
def join_waitlist(
    body: WaitlistCreateDTO,
    caller: Annotated[EdgeCaller, Depends(edge_caller)],
    limiters: Annotated[WaitlistLimiters, Depends(get_waitlist_limiters)],
    repo: Annotated[WaitlistRepository, Depends(get_waitlist_repo)],
    turnstile: Annotated[TurnstileVerifier | None, Depends(get_turnstile_verifier)],
) -> WaitlistCreatedDTO:
    """Step 1: create a partial applicant and hand back its completion token.

    The order is deliberate. The caller's own limit is charged first. Then the checks that cost
    the shared budget nothing: a honeypot hit (a silent fake success), a missing Turnstile token,
    and Turnstile's verdict. Only a request that passed them all is charged to the global daily
    budget, so a flood of token-less or bad-token posts cannot use it up for real applicants.
    """
    _charge_client(caller, limiters)
    if body.website:
        # A bot filled the hidden field: look like a success, store nothing.
        return WaitlistCreatedDTO(status="created", token=secrets.token_urlsafe(32))
    if turnstile is not None and not (
        body.turnstileToken and turnstile.verify(body.turnstileToken, caller.ip)
    ):
        # Fail closed: a missing token, a rejected one and an unreachable Cloudflare all land here.
        raise HTTPException(status_code=403, detail=_TURNSTILE_DETAIL)
    _charge_global(limiters)
    token = repo.create(
        email=body.email,
        name=body.name,
        role=body.role,
        consent_version=body.consentVersion,
        consent_text=CONSENT_VERSIONS[body.consentVersion],
        utm={
            "utm_source": body.utmSource,
            "utm_medium": body.utmMedium,
            "utm_campaign": body.utmCampaign,
            "utm_content": body.utmContent,
            "utm_term": body.utmTerm,
        },
    )
    if token is None:
        return WaitlistCreatedDTO(status="already_listed")
    return WaitlistCreatedDTO(status="created", token=token)


@router.patch(
    "/waitlist",
    response_model=WaitlistCompletedDTO,
)
def complete_waitlist(
    body: WaitlistCompleteDTO,
    caller: Annotated[EdgeCaller, Depends(edge_caller)],
    limiters: Annotated[WaitlistLimiters, Depends(get_waitlist_limiters)],
    repo: Annotated[WaitlistRepository, Depends(get_waitlist_repo)],
) -> WaitlistCompletedDTO:
    """Step 2: fill in the optional detail with the step-1 token.

    Only the caller's own limit is charged. A valid token proves its holder already spent one
    step on the global daily budget (step 1 charged it), so charging it again here would only
    let junk-token requests, which fail the token check, use the budget up for real applicants.
    """
    _charge_client(caller, limiters)
    if body.website:
        return WaitlistCompletedDTO(status="completed")
    done = repo.complete(
        body.token,
        CompletionDetails(
            levels=list(body.levels),
            subjects=list(body.subjects),
            other_subjects=list(body.otherSubjects),
            exam_boards=list(body.examBoards),
            exam_session=body.examSession,
            phone=body.phone,
            phone_has_whatsapp=body.phoneHasWhatsapp,
            centre_name=body.centreName,
        ),
    )
    if not done:
        raise HTTPException(status_code=400, detail=_REFUSED_DETAIL)
    return WaitlistCompletedDTO(status="completed")


@router.post("/internal/waitlist/digest", response_model=WaitlistDigestResultDTO)
def send_digest(
    settings: Annotated[Settings, Depends(get_settings)],
    repo: Annotated[WaitlistRepository, Depends(get_waitlist_repo)],
    provider: Annotated[EmailProvider, Depends(get_email_provider)],
    x_cron_secret: Annotated[str | None, Header()] = None,
) -> WaitlistDigestResultDTO:
    """Email the team the applicants since the last digest (nothing is sent when there are none)."""
    expected = settings.waitlist.digest_secret
    if expected is None:
        raise HTTPException(status_code=404, detail="Not found")
    if x_cron_secret is None or not hmac.compare_digest(x_cron_secret.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        outcome = send_waitlist_digest(repo, provider)
    except Exception as exc:
        log.warning("waitlist_digest_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail=_DIGEST_FAILED_DETAIL) from None
    if outcome.pending:
        # Today's claim exists but was never confirmed: not sent, so say so with a failure
        # status the scheduler retries (the claim becomes takeable after its lease).
        raise HTTPException(status_code=503, detail=_DIGEST_PENDING_DETAIL)
    return WaitlistDigestResultDTO(
        newApplicants=outcome.new_applicants,
        sent=outcome.sent,
        alreadySent=outcome.already_sent,
    )
