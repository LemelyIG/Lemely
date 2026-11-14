"""Shared pieces of the admin billing surface (spec §8): the audit helper, errors, names.

**Every admin money or catalogue change goes through :func:`audited` in the same
session and transaction as the change.** The audit row and the change commit or roll
back together; a change with no audit row cannot exist.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import select

from lemely.db.models.admin_audit import (
    HAS_IDEMPOTENCY_KEY_SQL,
    IDEMPOTENCY_KEY_SQL,
    AdminAuditLog,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

#: Prefix of the advisory-lock key, so an admin key can never equal the usage ledger's
#: ``usage:<owner id>`` keys (DV-12: both hash into the same 64-bit space).
_LOCK_KEY_PREFIX = "admin-billing:"


class AdminBillingError(Exception):
    """Base error; ``code`` is the machine-readable string the API returns."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class AdminNotFoundError(AdminBillingError):
    """The record named in the path does not exist (404)."""


class AdminConflictError(AdminBillingError):
    """The record's state forbids the action (409)."""


class AdminInvalidError(AdminBillingError):
    """The request is well-formed but its values are not acceptable (422)."""


class PaymobCallError(AdminBillingError):
    """Paymob refused or failed a call this action depends on (502)."""


class ReasonRequiredError(AdminInvalidError):
    """An admin change was attempted without a reason."""

    def __init__(self) -> None:
        super().__init__("reason_required", "Every admin change needs a reason.")


class AuditTarget(enum.StrEnum):
    PLAN_TIER = "plan_tier"
    CREDIT_PACK = "credit_pack"
    USAGE_RATE = "usage_rate"
    USAGE_ESTIMATOR = "usage_estimator"
    CONVERSION_RATE = "conversion_rate"
    USER = "user"
    SUBSCRIPTION = "subscription"
    PAYMENT = "payment"


class AuditAction(enum.StrEnum):
    PLAN_TIER_CREATE = "catalogue.plan_tier.create"
    PLAN_TIER_UPDATE = "catalogue.plan_tier.update"
    PLAN_TIER_SYNC = "catalogue.plan_tier.sync_paymob"
    CREDIT_PACK_CREATE = "catalogue.credit_pack.create"
    CREDIT_PACK_UPDATE = "catalogue.credit_pack.update"
    FREE_ALLOWANCE_UPDATE = "catalogue.free_allowance.update"
    USAGE_RATE_VERSION = "catalogue.usage_rate.version"
    USAGE_ESTIMATOR_VERSION = "catalogue.usage_estimator.version"
    CONVERSION_RATE_UPDATE = "catalogue.conversion_rate.update"
    CUSTOMER_GRANT = "customer.grant"
    CUSTOMER_ADJUST = "customer.adjust"
    CUSTOMER_FORGIVE_DEBT = "customer.forgive_debt"
    SUBSCRIPTION_MANUAL_ACTIVATION = "subscription.manual_activation"
    SUBSCRIPTION_ACTIVATION_DECISION = "subscription.activation_decision"
    SUBSCRIPTION_EXTEND = "subscription.extend"
    SUBSCRIPTION_CANCEL = "subscription.cancel"
    PAYMENT_REFUND_REQUESTED = "payment.refund.requested"
    PAYMENT_VOID_REQUESTED = "payment.void.requested"
    PAYMENT_REFUND_SUCCEEDED = "payment.refund.succeeded"
    PAYMENT_REFUND_FAILED = "payment.refund.failed"
    PAYMENT_REFUND_UNKNOWN = "payment.refund.unknown"
    PAYMENT_RECONCILE = "payment.reconcile"


def to_jsonable(value: object) -> object:
    """Convert a snapshot value to JSON-safe data. Unknown types are an error, not ``str()``."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return to_jsonable(value.value)
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(item) for item in value]
    raise TypeError(f"cannot audit a value of type {type(value).__name__}")


def _json_object(values: Mapping[str, object]) -> dict[str, object]:
    """``values`` converted for a JSONB column; unknown value types raise ``TypeError``."""
    return {str(key): to_jsonable(item) for key, item in values.items()}


def snapshot(obj: object, fields: Sequence[str]) -> dict[str, object]:
    """The named attributes of ``obj`` as JSON-safe data, for ``before``/``after``."""
    return {name: to_jsonable(getattr(obj, name)) for name in fields}


def audited(
    session: Session,
    admin_user_id: uuid.UUID,
    action: str,
    target_kind: str,
    target_id: uuid.UUID,
    reason: str,
    before: Mapping[str, object] | None,
    after: Mapping[str, object] | None,
) -> AdminAuditLog:
    """Add one audit row to ``session``'s transaction and flush it.

    Raises:
        ReasonRequiredError: ``reason`` is empty or whitespace. Nothing is added.
    """
    cleaned = (reason or "").strip()
    if not cleaned:
        raise ReasonRequiredError
    row = AdminAuditLog(
        admin_user_id=admin_user_id,
        action=str(action),
        target_kind=str(target_kind),
        target_id=target_id,
        reason=cleaned,
        before=None if before is None else _json_object(before),
        after=None if after is None else _json_object(after),
    )
    session.add(row)
    session.flush()
    return row


def idempotency_lookup(action: str, idempotency_key: str) -> sa.Select[tuple[bool]]:
    """The statement behind :func:`already_applied`.

    It repeats the index expression and predicate of ``ix_admin_audit_log_idempotency``
    verbatim, because Postgres uses a partial expression index only when the query's
    expression equals the index's and its WHERE implies the index predicate.
    """
    return (
        select(sa.literal(True))
        .select_from(AdminAuditLog)
        .where(
            AdminAuditLog.action == str(action),
            sa.text(HAS_IDEMPOTENCY_KEY_SQL),
            sa.literal_column(IDEMPOTENCY_KEY_SQL) == idempotency_key,
        )
        .limit(1)
    )


def already_applied(session: Session, *, action: str, idempotency_key: str) -> bool:
    """True when an audit row for ``action`` already carries ``after.idempotency_key``.

    Callers first take :func:`lock_idempotency_key` so two identical requests serialise on the
    key instead of both passing this check.
    """
    return session.scalar(idempotency_lookup(action, idempotency_key)) is not None


def lock_idempotency_key(session: Session, idempotency_key: str) -> None:
    """Serialise concurrent requests carrying the same key until this transaction ends.

    ``pg_advisory_xact_lock(hashtextextended('admin-billing:' || key, 0))``: a 64-bit hash
    (DV-12; the 32-bit ``hashtext`` would share the ledger's keyspace and collide far more).
    """
    session.execute(
        select(
            sa.func.pg_advisory_xact_lock(
                sa.func.hashtextextended(
                    sa.cast(_LOCK_KEY_PREFIX + idempotency_key, sa.Text),
                    sa.cast(0, sa.BigInteger),
                )
            )
        )
    )


__all__ = [
    "AdminBillingError",
    "AdminConflictError",
    "AdminInvalidError",
    "AdminNotFoundError",
    "AuditAction",
    "AuditTarget",
    "PaymobCallError",
    "ReasonRequiredError",
    "already_applied",
    "audited",
    "idempotency_lookup",
    "lock_idempotency_key",
    "snapshot",
    "to_jsonable",
]
