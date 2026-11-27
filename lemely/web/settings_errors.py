"""A missing ``billing_settings`` row is a 503 with a code, not a bare 500 (UD-13).

``create_all`` and the migration both insert the row, so its absence is a damaged database. The
readers fail closed and alert (no constant stands in for the value); an admin or a customer who
loads a screen that needs the setting then sees a retryable 503 with a stable code instead of an
unexplained 500. The body carries the code under both keys the two clients read: ``error`` (the
customer billing routes) and ``code`` (the admin billing routes).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from fastapi.responses import JSONResponse

from lemely.db.billing_repo import CreditValiditySettingMissing
from lemely.db.plan_terms_repo import NoticeSettingMissing
from lemely.db.subscription_repo import GraceSettingMissing

if TYPE_CHECKING:
    from fastapi import Request

#: The exceptions this module answers, with the code each one carries.
SETTINGS_ERROR_CODES: Final = {
    GraceSettingMissing: "grace_setting_missing",
    NoticeSettingMissing: "notice_setting_missing",
    CreditValiditySettingMissing: "credit_validity_setting_missing",
}
MESSAGE: Final = "Billing settings are temporarily unavailable"


async def settings_unavailable_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Render a missing-settings error as a retryable 503 with its code."""
    code = next((c for kind, c in SETTINGS_ERROR_CODES.items() if isinstance(exc, kind)), None)
    if code is None:
        raise exc
    return JSONResponse(
        status_code=503,
        content={"detail": {"error": code, "code": code, "message": MESSAGE}},
    )


__all__ = ["MESSAGE", "SETTINGS_ERROR_CODES", "settings_unavailable_handler"]
