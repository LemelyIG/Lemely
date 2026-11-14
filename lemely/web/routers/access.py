"""``GET /api/access/config``: whether sign-in is restricted right now.

The SPA asks this before it shows a signup or login form: while ``restricted`` is true the
visitor sees the "coming soon" screen instead. Public and unauthenticated (it is read before
anyone has an account) and it reveals only the boolean, **never** which domains are allowed, so
it cannot be used to learn the allow-list. The enforcement is not here: every authenticated
route and every account-creating flow refuses a non-allowed caller on its own
(:func:`lemely.web.deps.get_auth_context`, :class:`lemely.auth.service.AuthService`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.web.deps import get_settings
from lemely.web.schemas_access import AccessConfigDTO

router = APIRouter(prefix="/api")


@router.get("/access/config", response_model=AccessConfigDTO)
def access_config(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AccessConfigDTO:
    """``{"restricted": bool}``: true while ``[access] allowed_email_domains`` is non-empty."""
    # Flipped by a deploy, so a cached answer would keep showing the wrong screen.
    response.headers["Cache-Control"] = "no-store"
    return AccessConfigDTO(restricted=settings.access.restricted)
