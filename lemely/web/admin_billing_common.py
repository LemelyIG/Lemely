"""Helpers every admin billing router shares (DV-2).

Lane routers import from here, never from the parent router, so there is no import cycle.
Errors leave as ``{"code", "message"}`` in ``detail``; the status comes from the service
error's class.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime  # noqa: TC003 - used in a signature FastAPI never inspects
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException

from lemely.db.admin_billing_repo import (
    AdminBillingError,
    AdminConflictError,
    AdminInvalidError,
    AdminNotFoundError,
    PaymobCallError,
)
from lemely.db.models.enums import Role
from lemely.web.deps import AuthContext, require_role

if TYPE_CHECKING:
    from collections.abc import Iterator

AdminAuth = Annotated[AuthContext, Depends(require_role(Role.platform_admin))]

_STATUS: tuple[tuple[type[AdminBillingError], int], ...] = (
    (AdminNotFoundError, 404),
    (AdminConflictError, 409),
    (AdminInvalidError, 422),
    (PaymobCallError, 502),
)


def admin_id(auth: AuthContext) -> uuid.UUID:
    """The signed-in platform admin, for the audit row."""
    return uuid.UUID(auth.user_id)


@contextmanager
def mapped_errors() -> Iterator[None]:
    """Turn a service error into an ``HTTPException`` carrying ``{"code", "message"}``."""
    try:
        yield
    except AdminBillingError as exc:
        status = next((code for kind, code in _STATUS if isinstance(exc, kind)), 500)
        raise HTTPException(
            status_code=status, detail={"code": exc.code, "message": exc.message}
        ) from exc


def require_aware(value: datetime | None, field: str) -> datetime | None:
    """``value`` unchanged when it carries a time zone (or is absent); else 422 ``naive_datetime``.

    A naive instant compared with a ``timestamptz`` column is read in the server's zone, so a
    value the admin typed in their own is silently shifted (DV-24).
    """
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise AdminInvalidError(
            "naive_datetime", f"{field} needs a time zone, such as Z or +02:00."
        )
    return value
