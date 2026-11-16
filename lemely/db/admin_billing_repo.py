"""Shared pieces of the admin billing surface (spec §8): the audit helper, errors, names.

**Every admin money or catalogue change goes through :func:`audited` in the same
session and transaction as the change.** The audit row and the change commit or roll
back together; a change with no audit row cannot exist.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Literal

import sqlalchemy as sa
import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from lemely.core.metered_actions import MeteredAction
from lemely.core.subscription_rules import paymob_frequency
from lemely.db.models.admin_audit import (
    HAS_IDEMPOTENCY_KEY_SQL,
    IDEMPOTENCY_KEY_SQL,
    AdminAuditLog,
)
from lemely.db.models.billing import (
    LIVE_SUBSCRIPTION_STATUSES,
    AutoTopupSettings,
    CreditPack,
    PaymentPurpose,
    PlanAudience,
    PlanTier,
    PlanTierTerms,
    Subscription,
)
from lemely.db.models.billing_ops import (
    BillingSettings,
    PaymentRefund,
    RefundKind,
    RefundStatus,
)
from lemely.db.models.usage import EstimatorInputKind, UsageEstimator, UsageRate
from lemely.db.plan_terms_repo import subscribers_to_move
from lemely.db.subscription_repo import PlanNotPurchasable, PlanSyncFailed
from lemely.db.subscription_repo import sync_paymob_plan as link_paymob_plan
from lemely.db.usage_catalogue_repo import (
    SIGNUP_STUDENT_PACK,
    SIGNUP_TEACHER_PACK,
    ensure_usage_catalogue,
)
from lemely.io.paymob.client import PaymobError, PaymobNotConfigured

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.models.billing import Payment
    from lemely.db.models.enums import PlanInterval
    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

#: Prefix of the advisory-lock key, so an admin key can never equal the usage ledger's
#: ``usage:<owner id>`` keys (DV-12: both hash into the same 64-bit space).
_LOCK_KEY_PREFIX = "admin-billing:"

#: Events the operator alerts on (``alert=True`` survives only in structlog).
alerts = structlog.get_logger("lemely.db.admin_billing_repo")


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
    BILLING_SETTINGS = "billing_settings"
    LLM_PRICE = "llm_price"
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
    CREDIT_RATE_SET = "catalogue.credit_rate.set"
    CREDIT_RATE_CLEAR = "catalogue.credit_rate.clear"
    BILLING_SETTINGS_UPDATE = "catalogue.settings.update"
    LLM_PRICE_SET = "catalogue.llm_price.set"
    LLM_PRICE_CLEAR = "catalogue.llm_price.clear"
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


# A version may start a little in the past (clock skew between admin and server), never more.
_BACKDATE_TOLERANCE: Final = timedelta(minutes=5)

#: How a tier compares with its Paymob plan (:func:`paymob_drift`).
DriftState = Literal["in_sync", "not_synced", "unverified", "drifted"]


class Unset(enum.Enum):
    """Marks "the caller did not send this field", distinct from ``None`` (a real value)."""

    TOKEN = enum.auto()


UNSET: Final = Unset.TOKEN
FreeAudience = Literal["student", "teacher"]

#: The free start is stored as non-sellable credit packs whose code starts with this prefix
#: (Phase 04 deviation 7). The prefix is reserved: such a pack must never become sellable, so
#: only ``PUT /free-allowances`` (units alone) may touch one.
SIGNUP_PREFIX: Final = "signup_"

PLAN_TIER_MUTABLE: Final = (
    "name",
    "price_minor",
    "allowance_units",
    "included_seats",
    "seat_allowance_units",
    "extra_seat_price_minor",
    "features",
    "is_active",
)
_PLAN_TIER_AUDIT: Final = (
    "code",
    "name",
    "audience",
    "interval",
    "price_minor",
    "currency",
    "allowance_units",
    "included_seats",
    "seat_allowance_units",
    "extra_seat_price_minor",
    "features",
    "is_active",
    "terms_version",
    "paymob_plan_id",
    "paymob_plan_mode",
    "paymob_plan_synced_price_minor",
    "paymob_plan_synced_frequency",
)
#: The columns a ``plan_tier_terms`` row snapshots. Changing one inserts the next terms version
#: in the same transaction as the tier edit, so the tier always equals its latest terms row.
_TERMS_FIELDS: Final = (
    "price_minor",
    "extra_seat_price_minor",
    "allowance_units",
    "included_seats",
    "seat_allowance_units",
)
CREDIT_PACK_MUTABLE: Final = ("name", "units", "price_minor", "is_active")
_CREDIT_PACK_AUDIT: Final = ("code", "name", "units", "price_minor", "currency", "is_active")
_FREE_ALLOWANCE_AUDIT: Final = (*_CREDIT_PACK_AUDIT, "signup_validity_days")
#: ``price_change_notice_days`` when ``billing_settings`` has no row (the migration's seed).
_DEFAULT_NOTICE_DAYS: Final = 14
_SIGNUP_CODES: Final[dict[FreeAudience, str]] = {
    "student": SIGNUP_STUDENT_PACK,
    "teacher": SIGNUP_TEACHER_PACK,
}
_RATE_AUDIT: Final = ("version", "action", "units_per_usd", "effective_from")
_ESTIMATOR_AUDIT: Final = (
    "version",
    "action",
    "input_kind",
    "base_low",
    "base_high",
    "per_input_low",
    "per_input_high",
    "effective_from",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PlanTierFields:
    code: str
    name: str
    audience: PlanAudience
    interval: PlanInterval
    price_minor: int
    currency: str
    allowance_units: int
    included_seats: int
    seat_allowance_units: int
    extra_seat_price_minor: int
    features: dict[str, object]
    is_active: bool


@dataclass(frozen=True, slots=True)
class CreditPackFields:
    code: str
    name: str
    units: int
    price_minor: int
    currency: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class FreeAllowanceView:
    """The student free allowance or teacher signup credits, and the pack that stores it."""

    audience: FreeAudience
    pack: CreditPack
    valid_days: int | None


def _free_allowance_view(audience: FreeAudience, pack: CreditPack) -> FreeAllowanceView:
    return FreeAllowanceView(audience=audience, pack=pack, valid_days=pack.signup_validity_days)


@dataclass(frozen=True, slots=True)
class TierCounts:
    """How many subscribers a tier has, and how many still bill on an older terms version."""

    live: int = 0
    pending_moves: int = 0


@dataclass(frozen=True, slots=True)
class CatalogueSnapshot:
    plan_tiers: list[PlanTier]
    credit_packs: list[CreditPack]
    free_allowances: list[FreeAllowanceView]
    usage_rates: list[UsageRate]
    usage_estimators: list[UsageEstimator]
    tier_counts: Mapping[uuid.UUID, TierCounts] = field(default_factory=dict)
    auto_topup_counts: Mapping[uuid.UUID, int] = field(default_factory=dict)
    auto_topup_cap_below_price_counts: Mapping[uuid.UUID, int] = field(default_factory=dict)
    price_change_notice_days: int = _DEFAULT_NOTICE_DAYS


def paymob_drift(tier: PlanTier, key_mode: str) -> DriftState:
    """How the tier compares with the Paymob plan it is linked to.

    ``not_synced`` (no plan), ``drifted`` (the plan was made under the other key mode, which
    cannot be charged with these keys, or the price or frequency changed since the sync),
    ``unverified`` (a plan set outside the admin sync: no stamps to compare) or ``in_sync``.
    """
    if tier.paymob_plan_id is None:
        return "not_synced"
    if tier.paymob_plan_mode != key_mode:
        return "drifted"
    if tier.paymob_plan_synced_price_minor is None or tier.interval is None:
        return "unverified"
    if tier.paymob_plan_synced_price_minor != tier.price_minor or (
        tier.paymob_plan_synced_frequency != paymob_frequency(tier.interval.value)
    ):
        return "drifted"
    return "in_sync"


def _has_terms(session: Session, plan_tier_id: uuid.UUID) -> bool:
    """True when the tier has a ``plan_tier_terms`` row (every tier gets version 1 at insert)."""
    with session.no_autoflush:  # the caller's edited tier must not be written by this read
        return (
            session.scalar(
                select(PlanTierTerms.id).where(PlanTierTerms.plan_tier_id == plan_tier_id).limit(1)
            )
            is not None
        )


def tier_extra_seats_held(session: Session, plan_tier_id: uuid.UUID) -> int:
    """Extra seats held on a tier: the one definition ``seat price -> 0`` is refused against.

    The ``extra_seats`` of every live subscription on the tier (a pending checkout counts, it holds
    the beneficiary's live slot and was priced with them).
    """
    return int(
        session.scalar(
            select(sa.func.coalesce(sa.func.sum(Subscription.extra_seats), 0)).where(
                Subscription.plan_tier_id == plan_tier_id,
                Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            )
        )
        or 0
    )


def _require_version(row_version: int, expected: int | None) -> None:
    """Refuse a write that carries a version other than the locked row's (UD13-DV-1)."""
    if expected is not None and expected != row_version:
        raise AdminConflictError(
            "stale_write", "This was changed by someone else. Reload and try again."
        )


def _check_tier_shape(tier: PlanTier) -> None:
    if tier.audience is PlanAudience.student and (
        (tier.included_seats or 0)
        or (tier.seat_allowance_units or 0)
        or (tier.extra_seat_price_minor or 0)
    ):
        raise AdminInvalidError("seat_fields_on_student_tier", "Student tiers carry no seats.")


def require_reason(reason: str) -> None:
    """Refuse a blank reason before anything is read or written."""
    if not (reason or "").strip():
        raise ReasonRequiredError


def _require_not_before(latest: UsageRate | UsageEstimator | None, starts: datetime) -> None:
    """A new version may not start before the latest one.

    The Phase 04 readers take the highest version already in effect, so a version scheduled
    for next month would be silently overridden by a later "fix" that starts today.
    """
    if latest is not None and starts < latest.effective_from:
        raise AdminInvalidError(
            "effective_from_before_latest",
            "A new version cannot start before the latest one "
            f"({latest.effective_from.isoformat()}).",
        )


def _require_metered(action: str) -> None:
    try:
        MeteredAction(action)
    except ValueError as exc:
        raise AdminInvalidError("unknown_action", f"{action} is not a metered action.") from exc


def _tier_counts(session: Session) -> dict[uuid.UUID, TierCounts]:
    """Live subscribers and not-yet-moved subscribers per tier, in one grouped query."""
    rows = session.execute(
        select(
            Subscription.plan_tier_id,
            sa.func.count(),
            sa.func.count().filter(Subscription.terms_version < PlanTier.terms_version),
        )
        .join(PlanTier, PlanTier.id == Subscription.plan_tier_id)
        .where(Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES))
        .group_by(Subscription.plan_tier_id)
    )
    return {tier_id: TierCounts(live=live, pending_moves=moves) for tier_id, live, moves in rows}


def _auto_topup_counts(session: Session) -> dict[uuid.UUID, int]:
    """Enabled auto top-up settings per credit pack, in one grouped query."""
    rows = session.execute(
        select(AutoTopupSettings.credit_pack_id, sa.func.count())
        .where(AutoTopupSettings.enabled.is_(True))
        .group_by(AutoTopupSettings.credit_pack_id)
    )
    return {pack_id: count for pack_id, count in rows}


def _impact_audit(impact: AutoTopupImpact) -> dict[str, object]:
    """The audit's ``impact`` block, kept apart from the pack fields so a rename shows no diff."""
    return {
        "autoTopupsAffected": impact.affected,
        "autoTopupsCapBelowPrice": impact.cap_below_price,
    }


def _can_fire() -> tuple[sa.ColumnElement[bool], ...]:
    """What lets a setting charge at all: enabled, consented, a card, an active pack."""
    return (
        AutoTopupSettings.enabled.is_(True),
        AutoTopupSettings.consented_at.is_not(None),
        AutoTopupSettings.saved_card_id.is_not(None),
        CreditPack.is_active.is_(True),
    )


def _auto_topup_cap_below_price_counts(session: Session) -> dict[uuid.UUID, int]:
    """Settings that can fire per pack whose monthly cap is below the pack's stored price.

    Phase 06 never queues such a top-up (the cap check), so the setting stays armed and idle until
    the customer raises the cap. One grouped query.
    """
    rows = session.execute(
        select(AutoTopupSettings.credit_pack_id, sa.func.count())
        .join(CreditPack, CreditPack.id == AutoTopupSettings.credit_pack_id)
        .where(*_can_fire(), AutoTopupSettings.monthly_cap_minor < CreditPack.price_minor)
        .group_by(AutoTopupSettings.credit_pack_id)
    )
    return {pack_id: count for pack_id, count in rows}


@dataclass(frozen=True, slots=True)
class AutoTopupImpact:
    """Auto top-up settings on one pack at a price.

    ``enabled`` is every enabled setting, ``affected`` those that can fire, and ``cap_below_price``
    the affected ones whose monthly cap is below the price (they stay armed and never charge).
    """

    enabled: int
    affected: int
    cap_below_price: int


def _pack_auto_topup_impact(
    session: Session, credit_pack_id: uuid.UUID, price_minor: int
) -> AutoTopupImpact:
    """The pack's auto top-up counts at ``price_minor``: one aggregate query."""
    fires = sa.and_(*_can_fire())
    row = session.execute(
        select(
            sa.func.count(),
            sa.func.count().filter(fires),
            sa.func.count().filter(
                sa.and_(fires, AutoTopupSettings.monthly_cap_minor < price_minor)
            ),
        )
        .select_from(AutoTopupSettings)
        .join(CreditPack, CreditPack.id == AutoTopupSettings.credit_pack_id)
        .where(
            AutoTopupSettings.credit_pack_id == credit_pack_id,
            AutoTopupSettings.enabled.is_(True),
        )
    ).one()
    return AutoTopupImpact(enabled=row[0], affected=row[1], cap_below_price=row[2])


class AdminCatalogueService:
    """Plan tiers, credit packs, free allowances, usage rates and estimators (spec §8 area 1).

    Tiers and packs are edited in place (their history is the audit log). Rates and
    estimators are versioned: every write is a new row with the next version for its
    action, and old rows are never touched. Free allowances are the two signup packs, edited
    only through :meth:`set_free_allowance`.

    Every write checks its input first and adds its audit row last, in the same transaction
    as the change: a refused write leaves neither.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        client: PaymobClient,
        paymob_settings: PaymobSettings,
        *,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sm = sessionmaker
        self._client = client
        self._settings = paymob_settings
        self._now = now

    @property
    def key_mode(self) -> str:
        """The Paymob key mode (``test`` or ``live``) plans are created under now."""
        return self._settings.key_mode

    @property
    def subscription_amount_updatable(self) -> bool:
        """Whether Paymob can change an existing subscription's renewal amount (sandbox S14)."""
        return self._settings.subscription_amount_updatable

    def auto_topup_counts(self) -> Mapping[uuid.UUID, int]:
        """Enabled auto top-up settings per credit pack (one grouped query)."""
        with self._sm() as s:
            return _auto_topup_counts(s)

    def pack_price_impact(self, credit_pack_id: uuid.UUID, price_minor: int) -> AutoTopupImpact:
        """Read-only: the pack's auto top-ups if it cost ``price_minor`` (pre-save)."""
        with self._sm() as s:
            if s.get(CreditPack, credit_pack_id) is None:
                raise AdminNotFoundError("credit_pack_not_found")
            return _pack_auto_topup_impact(s, credit_pack_id, price_minor)

    def tier_counts(self) -> Mapping[uuid.UUID, TierCounts]:
        """Live and not-yet-moved subscriber counts per tier (one grouped query)."""
        with self._sm() as s:
            return _tier_counts(s)

    def catalogue(self) -> CatalogueSnapshot:
        with self._sm() as s:
            packs = list(s.scalars(select(CreditPack).order_by(CreditPack.code)))
            signup = {p.code: p for p in packs}
            return CatalogueSnapshot(
                plan_tiers=list(s.scalars(select(PlanTier).order_by(PlanTier.code))),
                credit_packs=[p for p in packs if not p.code.startswith(SIGNUP_PREFIX)],
                free_allowances=[
                    _free_allowance_view(audience, signup[code])
                    for audience, code in _SIGNUP_CODES.items()
                    if code in signup
                ],
                usage_rates=list(
                    s.scalars(
                        select(UsageRate).order_by(UsageRate.action, UsageRate.version.desc())
                    )
                ),
                usage_estimators=list(
                    s.scalars(
                        select(UsageEstimator).order_by(
                            UsageEstimator.action, UsageEstimator.version.desc()
                        )
                    )
                ),
                tier_counts=_tier_counts(s),
                auto_topup_counts=_auto_topup_counts(s),
                auto_topup_cap_below_price_counts=_auto_topup_cap_below_price_counts(s),
                price_change_notice_days=s.scalar(select(BillingSettings.price_change_notice_days))
                or _DEFAULT_NOTICE_DAYS,
            )

    # -- tiers ---------------------------------------------------------------

    def create_plan_tier(
        self, fields: PlanTierFields, *, admin_user_id: uuid.UUID, reason: str
    ) -> PlanTier:
        """Add a tier. Its terms version 1 is written by ``trg_plan_tiers_seed_terms``."""
        require_reason(reason)
        try:
            with self._sm.begin() as s:
                if s.scalar(select(PlanTier.id).where(PlanTier.code == fields.code)) is not None:
                    raise AdminConflictError(
                        "code_taken", f"A tier with code {fields.code} exists."
                    )
                tier = PlanTier(**asdict(fields))
                _check_tier_shape(tier)
                s.add(tier)
                s.flush()
                audited(
                    s,
                    admin_user_id,
                    AuditAction.PLAN_TIER_CREATE,
                    AuditTarget.PLAN_TIER,
                    tier.id,
                    reason,
                    None,
                    snapshot(tier, _PLAN_TIER_AUDIT),
                )
                return tier
        except IntegrityError as exc:
            raise AdminConflictError(
                "code_taken", f"A tier with code {fields.code} exists."
            ) from exc

    def update_plan_tier(
        self,
        plan_tier_id: uuid.UUID,
        changes: Mapping[str, object],
        *,
        admin_user_id: uuid.UUID,
        reason: str,
        expected_version: int | None = None,
    ) -> PlanTier:
        """Edit a tier in place.

        A change to any of the five terms inserts the next ``plan_tier_terms`` row (before it
        moves ``terms_version``, DV-T1a) in the same transaction, so the tier equals its latest
        terms row. Subscribers keep their own ``terms_version`` until their renewal move (T16).
        """
        require_reason(reason)
        if set(changes) - set(PLAN_TIER_MUTABLE):
            raise AdminInvalidError(
                "immutable_field", "code, audience, interval and currency are fixed."
            )
        with self._sm.begin() as s:
            tier = s.get(PlanTier, plan_tier_id, with_for_update=True)
            if tier is None:
                raise AdminNotFoundError("plan_tier_not_found")
            _require_version(tier.version, expected_version)
            before = snapshot(tier, _PLAN_TIER_AUDIT)
            terms_changed = any(
                name in _TERMS_FIELDS and getattr(tier, name) != value
                for name, value in changes.items()
            )
            had_terms = _has_terms(s, tier.id)
            seat_price_before = tier.extra_seat_price_minor
            for name, value in changes.items():
                setattr(tier, name, value)
            _check_tier_shape(tier)
            if seat_price_before > 0 and tier.extra_seat_price_minor == 0:
                held = tier_extra_seats_held(s, tier.id)
                if held:
                    raise AdminConflictError(
                        "extra_seats_held",
                        f"Subscribers on this plan hold {held} extra seats; "
                        "the seat price cannot be set to zero.",
                    )
            tier.version += 1
            if terms_changed and had_terms:
                s.add(
                    PlanTierTerms(
                        plan_tier_id=tier.id,
                        terms_version=tier.terms_version + 1,
                        price_minor=tier.price_minor,
                        extra_seat_price_minor=tier.extra_seat_price_minor,
                        allowance_units=tier.allowance_units,
                        included_seats=tier.included_seats,
                        seat_allowance_units=tier.seat_allowance_units,
                        created_by=admin_user_id,
                    )
                )
                s.flush()  # the terms row exists before the tier points at it
                tier.terms_version += 1
            s.flush()
            audited(
                s,
                admin_user_id,
                AuditAction.PLAN_TIER_UPDATE,
                AuditTarget.PLAN_TIER,
                tier.id,
                reason,
                before,
                {
                    **snapshot(tier, _PLAN_TIER_AUDIT),
                    "termsVersion": tier.terms_version,
                    "subscribersToMove": subscribers_to_move(s, tier.id),
                },
            )
            return tier

    def sync_paymob_plan(
        self, plan_tier_id: uuid.UUID, *, admin_user_id: uuid.UUID, reason: str
    ) -> PlanTier:
        """Create a new Paymob plan at the tier's current price and interval, and link it.

        Delegates to Phase 05's ``sync_paymob_plan(..., force_new=True)``, which locks the
        tier, calls Paymob, links the plan with the key mode it was made under and stamps the
        synced price and frequency (one stamping path, shared with the checkout link).

        Every Paymob failure rolls the transaction back: no link, no stamp, no audit row.
        """
        require_reason(reason)
        created_plan_id: int | None = None
        try:
            with self._sm.begin() as s:
                tier = s.get(PlanTier, plan_tier_id, with_for_update=True)
                if tier is None:
                    raise AdminNotFoundError("plan_tier_not_found")
                if paymob_drift(tier, self.key_mode) == "in_sync":
                    raise AdminConflictError(
                        "already_in_sync", "This tier already matches its Paymob plan."
                    )
                before = snapshot(tier, _PLAN_TIER_AUDIT)
                created_plan_id = link_paymob_plan(
                    s, self._client, self._settings, plan_tier_id, force_new=True
                )
                s.flush()
                audited(
                    s,
                    admin_user_id,
                    AuditAction.PLAN_TIER_SYNC,
                    AuditTarget.PLAN_TIER,
                    tier.id,
                    reason,
                    before,
                    snapshot(tier, _PLAN_TIER_AUDIT),
                )
                return tier
        except PlanNotPurchasable as exc:
            raise AdminInvalidError("not_billable", str(exc)) from exc
        except PlanSyncFailed as exc:
            raise PaymobCallError("paymob_plan_response_unusable", str(exc)) from exc
        except PaymobNotConfigured as exc:
            raise PaymobCallError("paymob_not_configured", str(exc)) from exc
        except PaymobError as exc:
            raise PaymobCallError("paymob_plan_create_failed", str(exc)) from exc
        except Exception:
            if created_plan_id is not None:
                # Paymob holds a plan our database never linked (the stamp, audit insert or
                # commit failed afterwards). It charges no one; the operator should know.
                alerts.error(
                    "paymob_plan_orphaned",
                    plan_tier_id=str(plan_tier_id),
                    paymob_plan_id=created_plan_id,
                    alert=True,
                )
            raise

    # -- packs ---------------------------------------------------------------

    def create_credit_pack(
        self, fields: CreditPackFields, *, admin_user_id: uuid.UUID, reason: str
    ) -> CreditPack:
        require_reason(reason)
        if fields.code.startswith(SIGNUP_PREFIX):
            raise AdminConflictError(
                "reserved_code", "Signup packs are set through free allowances."
            )
        try:
            with self._sm.begin() as s:
                if (
                    s.scalar(select(CreditPack.id).where(CreditPack.code == fields.code))
                    is not None
                ):
                    raise AdminConflictError(
                        "code_taken", f"A pack with code {fields.code} exists."
                    )
                pack = CreditPack(**asdict(fields))
                s.add(pack)
                s.flush()
                audited(
                    s,
                    admin_user_id,
                    AuditAction.CREDIT_PACK_CREATE,
                    AuditTarget.CREDIT_PACK,
                    pack.id,
                    reason,
                    None,
                    snapshot(pack, _CREDIT_PACK_AUDIT),
                )
                return pack
        except IntegrityError as exc:
            raise AdminConflictError(
                "code_taken", f"A pack with code {fields.code} exists."
            ) from exc

    def update_credit_pack(
        self,
        credit_pack_id: uuid.UUID,
        changes: Mapping[str, object],
        *,
        admin_user_id: uuid.UUID,
        reason: str,
        expected_version: int | None = None,
    ) -> CreditPack:
        return self.update_credit_pack_with_impact(
            credit_pack_id,
            changes,
            admin_user_id=admin_user_id,
            reason=reason,
            expected_version=expected_version,
        )[0]

    def update_credit_pack_with_impact(
        self,
        credit_pack_id: uuid.UUID,
        changes: Mapping[str, object],
        *,
        admin_user_id: uuid.UUID,
        reason: str,
        expected_version: int | None = None,
    ) -> tuple[CreditPack, AutoTopupImpact]:
        """:meth:`update_credit_pack`, plus the pack's auto top-up counts at its new price.

        The counts are the ones the audit row records, read in the same locked transaction.
        """
        require_reason(reason)
        if set(changes) - set(CREDIT_PACK_MUTABLE):
            raise AdminInvalidError("immutable_field", "code and currency are fixed.")
        with self._sm.begin() as s:
            pack = s.get(CreditPack, credit_pack_id, with_for_update=True)
            if pack is None:
                raise AdminNotFoundError("credit_pack_not_found")
            if pack.code.startswith(SIGNUP_PREFIX):
                raise AdminConflictError(
                    "signup_pack_use_free_allowances", "Edit signup packs through free allowances."
                )
            _require_version(pack.version, expected_version)
            old_impact = _pack_auto_topup_impact(s, pack.id, pack.price_minor)
            before = snapshot(pack, _CREDIT_PACK_AUDIT)
            for name, value in changes.items():
                setattr(pack, name, value)
            pack.version += 1
            s.flush()
            # UD13-B (a): auto top-ups keep charging the new price, held to each customer's cap.
            impact = _pack_auto_topup_impact(s, pack.id, pack.price_minor)
            audited(
                s,
                admin_user_id,
                AuditAction.CREDIT_PACK_UPDATE,
                AuditTarget.CREDIT_PACK,
                pack.id,
                reason,
                {**before, "impact": _impact_audit(old_impact)},
                {**snapshot(pack, _CREDIT_PACK_AUDIT), "impact": _impact_audit(impact)},
            )
            return pack, impact

    def set_free_allowance(
        self,
        *,
        audience: FreeAudience,
        units: int,
        valid_days: int | None | Unset = UNSET,
        admin_user_id: uuid.UUID,
        reason: str,
        expected_version: int | None = None,
    ) -> FreeAllowanceView:
        """Set the units and validity of the student free allowance or teacher signup credits.

        Units and ``valid_days`` (``None`` = never expires, ``UNSET`` = keep). The pack stays
        inactive at price zero, and ``0`` units switches the allowance off. Phase 04's
        ``ensure_usage_catalogue`` creates the signup packs on first use, so the first edit works
        on a fresh database too.
        """
        require_reason(reason)
        code = _SIGNUP_CODES[audience]
        with self._sm.begin() as s:
            ensure_usage_catalogue(s, now=self._now())
            pack = s.scalars(
                select(CreditPack).where(CreditPack.code == code).with_for_update()
            ).one()
            _require_version(pack.version, expected_version)
            before = snapshot(pack, _FREE_ALLOWANCE_AUDIT)
            pack.units = units
            if not isinstance(valid_days, Unset):
                pack.signup_validity_days = valid_days
            pack.version += 1
            s.flush()
            audited(
                s,
                admin_user_id,
                AuditAction.FREE_ALLOWANCE_UPDATE,
                AuditTarget.CREDIT_PACK,
                pack.id,
                reason,
                before,
                snapshot(pack, _FREE_ALLOWANCE_AUDIT),
            )
            return _free_allowance_view(audience, pack)

    # -- versioned rows ------------------------------------------------------

    def _effective(self, effective_from: datetime | None) -> datetime:
        now = self._now()
        if effective_from is None:
            return now
        if effective_from < now - _BACKDATE_TOLERANCE:
            raise AdminInvalidError(
                "effective_from_in_past", "A new version cannot start in the past."
            )
        return effective_from

    def add_usage_rate(
        self,
        *,
        action: str,
        units_per_usd: int,
        effective_from: datetime | None,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> UsageRate:
        require_reason(reason)
        _require_metered(action)
        starts = self._effective(effective_from)
        with self._sm.begin() as s:
            lock_idempotency_key(s, f"catalogue-version:usage_rates:{action}")
            latest = s.scalars(
                select(UsageRate)
                .where(UsageRate.action == action)
                .order_by(UsageRate.version.desc())
                .limit(1)
            ).first()
            _require_not_before(latest, starts)
            row = UsageRate(
                version=(latest.version if latest else 0) + 1,
                action=action,
                units_per_usd=units_per_usd,
                effective_from=starts,
            )
            s.add(row)
            s.flush()
            audited(
                s,
                admin_user_id,
                AuditAction.USAGE_RATE_VERSION,
                AuditTarget.USAGE_RATE,
                row.id,
                reason,
                snapshot(latest, _RATE_AUDIT) if latest else None,
                snapshot(row, _RATE_AUDIT),
            )
            return row

    def add_usage_estimator(
        self,
        *,
        action: str,
        input_kind: EstimatorInputKind,
        base_low: int,
        base_high: int,
        per_input_low: int,
        per_input_high: int,
        effective_from: datetime | None,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> UsageEstimator:
        require_reason(reason)
        _require_metered(action)
        if base_low > base_high or per_input_low > per_input_high:
            raise AdminInvalidError(
                "low_above_high", "Each low bound must not exceed its high bound."
            )
        if input_kind is EstimatorInputKind.none and (per_input_low or per_input_high):
            raise AdminInvalidError("per_input_without_input_kind")
        starts = self._effective(effective_from)
        with self._sm.begin() as s:
            lock_idempotency_key(s, f"catalogue-version:usage_estimators:{action}")
            latest = s.scalars(
                select(UsageEstimator)
                .where(UsageEstimator.action == action)
                .order_by(UsageEstimator.version.desc())
                .limit(1)
            ).first()
            _require_not_before(latest, starts)
            row = UsageEstimator(
                version=(latest.version if latest else 0) + 1,
                action=action,
                input_kind=input_kind,
                base_low=base_low,
                base_high=base_high,
                per_input_low=per_input_low,
                per_input_high=per_input_high,
                effective_from=starts,
            )
            s.add(row)
            s.flush()
            audited(
                s,
                admin_user_id,
                AuditAction.USAGE_ESTIMATOR_VERSION,
                AuditTarget.USAGE_ESTIMATOR,
                row.id,
                reason,
                snapshot(latest, _ESTIMATOR_AUDIT) if latest else None,
                snapshot(row, _ESTIMATOR_AUDIT),
            )
            return row


def _callback_refunded(last_callback: Mapping[str, object] | None) -> int:
    """``refunded_amount_cents`` as Paymob last reported it; 0 when absent or not a count."""
    value = (last_callback or {}).get("refunded_amount_cents")
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        return int(value.strip())
    return 0


@dataclass(frozen=True, slots=True)
class PaymentView:
    """A payment with its refund attempts, oldest first (DV-19).

    ``reverse_effects`` holds, per refund id, the outcome of a requested reverse that has been
    applied (read from the audit row that closed the refund; nothing else stores it).
    """

    payment: Payment
    refunds: list[PaymentRefund] = field(default_factory=list)

    @property
    def refunded_minor(self) -> int:
        """Money already returned: the larger of our succeeded refunds and Paymob's total.

        A refund made in the Paymob dashboard leaves no ``payment_refunds`` row; Phase 02
        records it in ``last_callback.refunded_amount_cents``.
        """
        console = sum(
#: Purposes that buy credits by design. Their ``grant_units`` is the purchase itself, not a
#: conversion of a payment that bought nothing (UD-3).
CREDIT_PURCHASE_PURPOSES: Final = frozenset({PaymentPurpose.credit_pack, PaymentPurpose.auto_topup})


@dataclass(frozen=True, slots=True)
class ReverseEffect:
    """What the undo of a refund or void came to, as its closing audit row recorded it.

    ``effect`` is the audit's ``reverse_effect``; ``reason`` is the service's explanation when
    the undo could not run after the money had moved.
    """

    effect: str
    reason: str | None = None


            r.amount_minor
            for r in self.refunds
            if r.status is RefundStatus.succeeded and r.kind is RefundKind.refund
        )
        return max(console, _callback_refunded(self.payment.last_callback))

    reverse_effects: Mapping[uuid.UUID, ReverseEffect] = field(default_factory=dict)

    @property
    def credited_units(self) -> int | None:
        """Credits a payment that bought nothing was turned into (UD-3), else ``None``.

        The same stamp the checkout-return page reads (``grant_units``). A pack or top-up is
        excluded: it carries the stamp because credits are what it sells.
        """
        payment = self.payment
        if payment.purpose in CREDIT_PURCHASE_PURPOSES:
            return None
        return payment.grant_units

def payment_views(session: Session, payments: Sequence[Payment]) -> list[PaymentView]:
    """Attach refunds to ``payments`` in one query, keeping the input order."""
    ids = [p.id for p in payments]
    by_payment: dict[uuid.UUID, list[PaymentRefund]] = {pid: [] for pid in ids}
    if ids:
        for refund in session.scalars(
            select(PaymentRefund)
            .where(PaymentRefund.payment_id.in_(ids))
            .order_by(PaymentRefund.created_at, PaymentRefund.id)
        ):
            by_payment[refund.payment_id].append(refund)
    effects = _reverse_effects(session, by_payment)
    return [
        PaymentView(payment=p, refunds=by_payment[p.id], reverse_effects=effects.get(p.id, {}))
        for p in payments
    ]


def _reverse_effects(
    session: Session, by_payment: Mapping[uuid.UUID, Sequence[PaymentRefund]]
) -> dict[uuid.UUID, dict[uuid.UUID, ReverseEffect]]:
    """Per payment, the reverse outcome of each succeeded refund that asked for one."""
    wanted: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    for payment_id, refunds in by_payment.items():
        ids = {
            str(r.id): r.id
            for r in refunds
            if r.reverse_change and r.status is RefundStatus.succeeded
        }
        if ids:
            wanted[payment_id] = ids
    found: dict[uuid.UUID, dict[uuid.UUID, ReverseEffect]] = {}
    if not wanted:
        return found
    for row in session.scalars(
        select(AdminAuditLog).where(
            AdminAuditLog.target_kind == AuditTarget.PAYMENT.value,
            AdminAuditLog.target_id.in_(list(wanted)),
            AdminAuditLog.action == AuditAction.PAYMENT_REFUND_SUCCEEDED.value,
        )
    ):
        after = row.after or {}
        effect = after.get("reverse_effect")
        refund_id = wanted[row.target_id].get(str(after.get("refund_id")))
        if refund_id is None or not isinstance(effect, str):
            continue
        reason = after.get("reverse_reason")
        found.setdefault(row.target_id, {})[refund_id] = ReverseEffect(
            effect, reason if isinstance(reason, str) else None
        )
    return found


__all__ = [
    "CREDIT_PACK_MUTABLE",
    "PLAN_TIER_MUTABLE",
    "SIGNUP_PREFIX",
    "AdminBillingError",
    "AdminCatalogueService",
    "AdminConflictError",
    "AdminInvalidError",
    "AdminNotFoundError",
    "AuditAction",
    "AuditTarget",
    "CatalogueSnapshot",
    "CreditPackFields",
    "FreeAllowanceView",
    "PaymentView",
    "PaymobCallError",
    "PlanTierFields",
    "CREDIT_PURCHASE_PURPOSES",
    "ReasonRequiredError",
    "already_applied",
    "audited",
    "idempotency_lookup",
    "lock_idempotency_key",
    "payment_views",
    "paymob_drift",
    "require_reason",
    "snapshot",
    "to_jsonable",
]
    "ReverseEffect",
