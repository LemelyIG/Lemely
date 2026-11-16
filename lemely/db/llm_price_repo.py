"""Admin-set AI token price overrides, one row per model (UD13-D, Phase 07 T19).

Prices are USD per million tokens. A write validates first (``Override`` is the one rule set, shared
with the runtime registry), then takes a per-model advisory lock and the row ``FOR UPDATE``,
compares the version the admin read, writes, bumps ``version`` and adds exactly one audit row last,
in the caller's transaction, so a refusal leaves none.

Clearing deletes the row, and a recreated model keeps counting versions: it starts above the highest
version any set or clear of that model left in the audit log, so a stale tab cannot overwrite a
recreated price (the T14 credit-rate fix, ``cfd4635e``).

The runtime never reads this table directly. ``lemely.web.llm_price_refresh`` loads it into the
``lemely.io.llm.price_overrides`` snapshot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa

from lemely.db.admin_billing_repo import (
    AdminConflictError,
    AdminInvalidError,
    AdminNotFoundError,
    AuditAction,
    AuditTarget,
    audited,
    lock_idempotency_key,
    require_reason,
    snapshot,
)
from lemely.db.models.admin_audit import AdminAuditLog
from lemely.db.models.billing_ops import LlmPriceOverride, UsageJobModelCost
from lemely.io.llm.price_overrides import InvalidPriceError, Override

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable, Mapping
    from decimal import Decimal

    from sqlalchemy.orm import Session

ACTION_SET: Final = AuditAction.LLM_PRICE_SET
ACTION_CLEAR: Final = AuditAction.LLM_PRICE_CLEAR
TARGET: Final = AuditTarget.LLM_PRICE

#: The columns an admin sets (the wire names are camelCase of these).
RATE_FIELDS: Final = (
    "input_usd_per_mtok",
    "output_usd_per_mtok",
    "cached_input_usd_per_mtok",
    "cache_write_5m_usd_per_mtok",
    "cache_write_1h_usd_per_mtok",
    "tier_threshold_tokens",
    "tier2_input_usd_per_mtok",
    "tier2_output_usd_per_mtok",
)
_AUDIT_FIELDS: Final = ("model", *RATE_FIELDS, "version")
_MODEL_RE: Final = re.compile(r"[A-Za-z0-9._:-]{1,128}")
SEEN_WINDOW: Final = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class LlmPriceView:
    model: str
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    cached_input_usd_per_mtok: Decimal | None
    cache_write_5m_usd_per_mtok: Decimal | None
    cache_write_1h_usd_per_mtok: Decimal | None
    tier_threshold_tokens: int | None
    tier2_input_usd_per_mtok: Decimal | None
    tier2_output_usd_per_mtok: Decimal | None
    version: int
    updated_at: datetime
    updated_by: uuid.UUID | None


def _view(row: LlmPriceOverride) -> LlmPriceView:
    return LlmPriceView(
        model=row.model,
        input_usd_per_mtok=row.input_usd_per_mtok,
        output_usd_per_mtok=row.output_usd_per_mtok,
        cached_input_usd_per_mtok=row.cached_input_usd_per_mtok,
        cache_write_5m_usd_per_mtok=row.cache_write_5m_usd_per_mtok,
        cache_write_1h_usd_per_mtok=row.cache_write_1h_usd_per_mtok,
        tier_threshold_tokens=row.tier_threshold_tokens,
        tier2_input_usd_per_mtok=row.tier2_input_usd_per_mtok,
        tier2_output_usd_per_mtok=row.tier2_output_usd_per_mtok,
        version=row.version,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def validate_model(model: str) -> str:
    if not _MODEL_RE.fullmatch(model):
        raise AdminInvalidError(
            "invalid_price", "A model id is 1 to 128 letters, digits, '.', '_', ':' or '-'."
        )
    return model


def validate_rates(model: str, rates: Mapping[str, object]) -> Override:
    """The checked :class:`Override`, or ``AdminInvalidError`` (``invalid_price``)."""
    unknown = set(rates) - set(RATE_FIELDS)
    if unknown:
        raise AdminInvalidError("invalid_price", f"{sorted(unknown)[0]} is not a price field.")
    try:
        return Override(model=model, **rates)  # type: ignore[arg-type]
    except InvalidPriceError as exc:
        raise AdminInvalidError("invalid_price", str(exc)) from exc


def list_overrides(session: Session) -> list[LlmPriceView]:
    rows = session.scalars(
        sa.select(LlmPriceOverride)
        .order_by(LlmPriceOverride.model)
        .execution_options(populate_existing=True)
    )
    return [_view(r) for r in rows]


def seen_models(session: Session, *, now: datetime) -> set[str]:
    """Models with recorded LLM cost on a usage job in the last :data:`SEEN_WINDOW`."""
    return set(
        session.scalars(
            sa.select(UsageJobModelCost.model)
            .where(UsageJobModelCost.created_at >= now - SEEN_WINDOW)
            .distinct()
        )
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stale(model: str) -> AdminConflictError:
    return AdminConflictError(
        "stale_write", f"The {model} price changed since you loaded it. Reload and try again."
    )


class LlmPriceService:
    """Audited writes of the per-model price overrides.

    The caller owns the transaction, as with ``BillingSettingsService``.
    """

    def __init__(self, session: Session, *, now: Callable[[], datetime] = _utc_now) -> None:
        self._s = session
        self._now = now
        #: True once a set or clear went through; the router refreshes the runtime then.
        self.wrote = False

    def list(self) -> list[LlmPriceView]:
        return list_overrides(self._s)

    def seen(self) -> set[str]:
        return seen_models(self._s, now=self._now())

    def _locked(self, model: str) -> LlmPriceOverride | None:
        lock_idempotency_key(self._s, f"llm-price:{model}")
        return self._s.execute(
            sa.select(LlmPriceOverride)
            .where(LlmPriceOverride.model == model)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    def _highest_version_seen(self, model: str) -> int:
        """The highest version any set or clear of ``model`` left in the audit log (0 if none).

        Called under the per-model advisory lock, so no other writer adds a row meanwhile.
        """
        versions = [
            sa.cast(AdminAuditLog.before["version"].astext, sa.Integer),
            sa.cast(AdminAuditLog.after["version"].astext, sa.Integer),
        ]
        highest = self._s.scalar(
            sa.select(sa.func.max(sa.func.greatest(*versions))).where(
                AdminAuditLog.action.in_((ACTION_SET, ACTION_CLEAR)),
                sa.or_(
                    AdminAuditLog.before["model"].astext == model,
                    AdminAuditLog.after["model"].astext == model,
                ),
            )
        )
        return highest or 0

    def set_price(
        self,
        admin_id: uuid.UUID,
        *,
        model: str,
        rates: Mapping[str, object],
        expected_version: int | None,
        reason: str,
    ) -> LlmPriceView:
        """Create (``expected_version`` ``None``) or replace the override of ``model``."""
        require_reason(reason)
        validate_model(model)
        validate_rates(model, rates)
        row = self._locked(model)
        before: dict[str, object] | None = None
        if row is None:
            if expected_version is not None:
                raise _stale(model)
            row = LlmPriceOverride(
                model=model,
                version=self._highest_version_seen(model) + 1,
                updated_by=admin_id,
                updated_at=self._now(),
                **rates,
            )
            self._s.add(row)
        else:
            if expected_version is None:
                raise AdminConflictError(
                    "llm_price_exists",
                    f"A {model} price is already set. Send its version to replace it.",
                )
            if row.version != expected_version:
                raise _stale(model)
            before = snapshot(row, _AUDIT_FIELDS)
            for name in RATE_FIELDS:
                setattr(row, name, rates.get(name))
            row.version += 1
            row.updated_by = admin_id
            row.updated_at = self._now()
        self._s.flush()
        self._s.refresh(row)  # the audit and the answer carry the stored (quantised) values
        audited(
            self._s,
            admin_id,
            ACTION_SET,
            TARGET,
            row.id,
            reason,
            before,
            snapshot(row, _AUDIT_FIELDS),
        )
        self.wrote = True
        return _view(row)

    def clear_price(
        self, admin_id: uuid.UUID, *, model: str, expected_version: int, reason: str
    ) -> None:
        """Delete the override of ``model``; its price is the config or code value again."""
        require_reason(reason)
        validate_model(model)
        row = self._locked(model)
        if row is None:
            raise AdminNotFoundError("llm_price_not_set", f"No {model} price is set.")
        if row.version != expected_version:
            raise _stale(model)
        before = snapshot(row, _AUDIT_FIELDS)
        row_id = row.id
        self._s.delete(row)
        self._s.flush()
        audited(self._s, admin_id, ACTION_CLEAR, TARGET, row_id, reason, before, None)
        self.wrote = True
