"""Plan terms: a subscriber keeps the terms they are on until their next renewal (UD13-A, Part A).

Real Postgres (a throwaway ``create_all`` database). An admin edit inserts the next terms version
and moves the tier; no subscription changes. Every reader that prices or grants for an existing
subscriber must read the subscriber's own terms, never the tier's live columns.
"""

from __future__ import annotations

import ast
import uuid
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
import sqlalchemy as sa

from lemely.db.models.billing import (
    Payment,
    PlanAudience,
    PlanTier,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.usage import GrantKind
from lemely.db.plan_terms_repo import (
    TierTerms,
    current_terms_for,
    pending_terms_for,
    terms_for,
    terms_in_force_for_next_period,
)
from lemely.db.seat_allowance_repo import grant_seat_allowance_on_claim
from lemely.db.subscription_repo import (
    TRIGGER_SUCCESS,
    SubscriptionService,
    _line_items,
    handle_subscription_first,
)
from lemely.db.teacher_team_repo import TeacherTeamService
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    charge,
    edit_tier_terms,
    grants_of,
    paymob_settings,
    remote_subscription,
    seed_first_payment,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    subscription_webhook,
    throwaway_database,
)
from tests.team_db import emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

END = T0 + timedelta(days=30)
PID = 4321


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def sm(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(_database)


def _sub(sm: sessionmaker[Session], sid: uuid.UUID) -> Subscription:
    with sm() as session:
        row = session.get(Subscription, sid)
        assert row is not None
        return row


def _terms(sm: sessionmaker[Session], sid: uuid.UUID) -> TierTerms:
    with sm() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        return terms_for(session, sub)


def _teacher_plan(
    sm: sessionmaker[Session], *, included_seats: int, seat_allowance_units: int = 0
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    teacher = seed_user(sm, Role.teacher)
    tier_id = seed_tier(
        sm,
        audience=PlanAudience.teacher,
        included_seats=included_seats,
        seat_allowance_units=seat_allowance_units,
    )
    sid = seed_subscription(
        sm, user_id=teacher, tier_id=tier_id, payer_id=teacher, paymob_amount_minor=10_000
    )
    return teacher, tier_id, sid


# -- the reader ---------------------------------------------------------------------------


def test_terms_for_is_the_version_the_subscription_is_on(sm: sessionmaker[Session]) -> None:
    student = seed_user(sm, Role.student)
    tier = seed_tier(sm, price_minor=10_000, allowance_units=1_000)
    sid = seed_subscription(sm, user_id=student, tier_id=tier, payer_id=student)
    edit_tier_terms(sm, tier, price_minor=12_000, allowance_units=2_000)
    terms = _terms(sm, sid)
    assert (terms.terms_version, terms.price_minor, terms.allowance_units) == (1, 10_000, 1_000)
    with sm() as session:
        current = current_terms_for(session, session.get(PlanTier, tier))  # type: ignore[arg-type]
    assert (current.terms_version, current.price_minor) == (2, 12_000)


def test_pending_terms_for_is_none_without_a_pending_version(sm: sessionmaker[Session]) -> None:
    student = seed_user(sm, Role.student)
    tier = seed_tier(sm)
    sid = seed_subscription(sm, user_id=student, tier_id=tier, payer_id=student)
    with sm() as session:
        assert pending_terms_for(session, session.get(Subscription, sid)) is None  # type: ignore[arg-type]


def test_pending_terms_for_returns_the_pending_version(sm: sessionmaker[Session]) -> None:
    student = seed_user(sm, Role.student)
    tier = seed_tier(sm, price_minor=10_000)
    edit_tier_terms(sm, tier, price_minor=15_000)
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        pending_terms_version=2,
        pending_terms_effective_at=END,
    )
    with sm() as session:
        pending = pending_terms_for(session, session.get(Subscription, sid))  # type: ignore[arg-type]
    assert pending is not None
    assert (pending.terms_version, pending.price_minor) == (2, 15_000)


@pytest.mark.parametrize(
    ("effective_offset", "expected_version"),
    [
        (timedelta(0), 2),  # the period end is the effective instant: it qualifies
        (timedelta(days=-1), 2),  # effective earlier than the period end: it qualifies
        (timedelta(seconds=1), 1),  # the period ends before the move is effective: not yet
    ],
)
def test_pending_terms_apply_only_when_the_period_end_reaches_the_effective_date(
    sm: sessionmaker[Session], effective_offset: timedelta, expected_version: int
) -> None:
    student = seed_user(sm, Role.student)
    tier = seed_tier(sm, price_minor=10_000)
    edit_tier_terms(sm, tier, price_minor=15_000)
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        period_end=END,
        pending_terms_version=2,
        pending_terms_effective_at=END + effective_offset,
    )
    with sm() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        assert terms_in_force_for_next_period(session, sub).terms_version == expected_version


def test_a_pending_plan_change_wins_over_pending_terms(sm: sessionmaker[Session]) -> None:
    student = seed_user(sm, Role.student)
    tier = seed_tier(sm, price_minor=10_000)
    edit_tier_terms(sm, tier, price_minor=15_000)
    cheaper = seed_tier(sm, price_minor=5_000)
    edit_tier_terms(sm, cheaper, price_minor=6_000)
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        period_end=END,
        pending_plan_tier_id=cheaper,
        pending_terms_version=2,
        pending_terms_effective_at=END,
    )
    with sm() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        terms = terms_in_force_for_next_period(session, sub)
    assert (terms.plan_tier_id, terms.terms_version, terms.price_minor) == (cheaper, 2, 6_000)


# -- the built readers keep the subscriber's terms ---------------------------------------


def test_seat_capacity_is_unchanged_by_an_edit(sm: sessionmaker[Session]) -> None:
    teacher, tier, _ = _teacher_plan(sm, included_seats=5)
    edit_tier_terms(sm, tier, included_seats=2)
    with sm() as session:
        assert TeacherTeamService(session).seat_capacity(teacher) == 5


def test_seat_capacity_of_a_new_subscriber_uses_the_new_terms(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, audience=PlanAudience.teacher, included_seats=5)
    edit_tier_terms(sm, tier, included_seats=2)
    teacher = seed_user(sm, Role.teacher)
    seed_subscription(sm, user_id=teacher, tier_id=tier, payer_id=teacher, terms_version=2)
    with sm() as session:
        assert TeacherTeamService(session).seat_capacity(teacher) == 2


def test_monthly_seat_grant_uses_the_subscribers_seat_allowance(sm: sessionmaker[Session]) -> None:
    teacher, tier, _ = _teacher_plan(sm, included_seats=2, seat_allowance_units=600)
    member = seed_seat(sm, teacher_id=teacher, student_id=seed_user(sm, Role.student))
    edit_tier_terms(sm, tier, seat_allowance_units=100)
    with sm.begin() as session:
        grant = grant_seat_allowance_on_claim(session, member, now=T0 + timedelta(hours=1))
    assert grant is not None
    assert grant.units > 100  # the 600-unit plan prorated for the days left, never the 100


def test_first_payment_grants_the_terms_the_checkout_priced(sm: sessionmaker[Session]) -> None:
    """A checkout paid after an edit activates on the version it was priced at (Part A.3)."""
    student = seed_user(sm, Role.student)
    tier = seed_tier(sm, price_minor=10_000, allowance_units=1_000)
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        status=SubscriptionStatus.pending_first_payment,
        period_start=None,
        period_end=None,
    )
    pay = seed_first_payment(sm, subscription_id=sid, amount_minor=10_000, paid_at=T0)
    edit_tier_terms(sm, tier, price_minor=20_000, allowance_units=9_000)
    with sm.begin() as session:
        payment = session.get(Payment, pay)
        assert payment is not None
        handle_subscription_first(session, payment, {})
    grants = [g for g in grants_of(sm, student) if g.kind is GrantKind.period_allowance]
    assert [g.units for g in grants] == [1_000]
    with sm() as session:
        period = session.scalars(
            sa.select(SubscriptionPeriod).where(SubscriptionPeriod.subscription_id == sid)
        ).one()
    assert period.terms_version == 1
    assert _sub(sm, sid).terms_version == 1


def _renew(sm: sessionmaker[Session], *, amount: int) -> None:
    client = FakePaymobClient()
    client.subscriptions[PID] = remote_subscription(PID, amount_cents=amount)
    client.last_transactions[PID] = charge(888, amount, created_at=END - timedelta(hours=2))
    with sm.begin() as session:
        SubscriptionService(session, client, paymob_settings()).apply_renewal_webhook(
            subscription_webhook(TRIGGER_SUCCESS, PID), now=END + timedelta(minutes=5)
        )


def test_next_renewal_amount_is_unchanged_by_an_edit_before_any_notice(
    sm: sessionmaker[Session],
) -> None:
    student = seed_user(sm, Role.student)
    tier = seed_tier(sm, price_minor=10_000)
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        paymob_subscription_id=PID,
        paymob_amount_minor=10_000,
    )
    edit_tier_terms(sm, tier, price_minor=14_000)
    with sm() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        service = SubscriptionService(session, FakePaymobClient(), paymob_settings())
        assert service.next_renewal_amount(sub) == 10_000


def test_a_renewal_after_an_edit_grants_the_old_allowance_and_keeps_the_terms(
    sm: sessionmaker[Session],
) -> None:
    student = seed_user(sm, Role.student)
    tier = seed_tier(sm, price_minor=10_000, allowance_units=1_000)
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        paymob_subscription_id=PID,
        paymob_amount_minor=10_000,
        activated_at=T0,
    )
    edit_tier_terms(sm, tier, price_minor=14_000, allowance_units=7_000)
    _renew(sm, amount=10_000)
    grants = [g for g in grants_of(sm, student) if g.kind is GrantKind.period_allowance]
    assert [g.units for g in grants] == [1_000]
    sub = _sub(sm, sid)
    assert sub.terms_version == 1
    assert sub.current_period_end is not None
    assert sub.current_period_end > END


def test_a_new_checkout_is_priced_at_the_new_terms(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    edit_tier_terms(sm, tier, price_minor=14_000)
    with sm() as session:
        row = session.get(PlanTier, tier)
        assert row is not None
        assert row.terms_version == 2
        assert _line_items(row, 0)[0]["amount"] == 14_000


# -- source scan: nobody prices or grants from the live tier ------------------------------

_TERM_ATTRS = frozenset(
    {
        "price_minor",
        "extra_seat_price_minor",
        "allowance_units",
        "included_seats",
        "seat_allowance_units",
    }
)
#: Receiver names a ``PlanTier`` (or a row of one) is bound to in ``lemely/``. ``terms``,
#: ``new_terms`` and friends hold a ``TierTerms`` and are the right thing to read from. An
#: attribute chain ending in ``.tier`` (``s.tier.price_minor``) is a tier read whatever precedes it.
_TIER_NAMES = frozenset(
    {
        "tier",
        "plan_tier",
        "target",
        "current",
        "old_tier",
        "new_tier",
        "current_tier",
        "target_tier",
        "t",
        "row",
        "p",
        "PlanTier",
    }
)
_ROOT = Path(__file__).resolve().parent.parent / "lemely"
_SKIPPED_DIRS = ("db/models/", "db/migrations/")

#: The functions that may read a tier's own term columns, each named. A read anywhere else is a
#: grandfathering leak: an existing subscriber would see an admin edit at once.
_ALLOWED: Final = frozenset(
    {
        # New purchases: checkout pricing, the Paymob plan sync, the seat-cover check of the plan
        # being bought.
        "db/subscription_repo.py::_line_items",
        "db/subscription_repo.py::SubscriptionService._require_seats_covered",
        "db/subscription_repo.py::SubscriptionService._sellable_tier",
        "db/subscription_repo.py::SubscriptionService.create_subscription_checkout",
        "db/subscription_repo.py::sync_paymob_plan",
        # The admin catalogue: edits and lists tiers, the activation queue and a manual activation
        # (a new purchase priced at the current terms, which it stamps).
        "db/admin_billing_repo.py::_check_tier_shape",
        "db/admin_billing_repo.py::paymob_drift",
        "db/admin_billing_repo.py::AdminCatalogueService.update_plan_tier",
        "db/admin_customer_repo.py::AdminCustomerService.manual_activation",
        "db/admin_repo.py::PlatformAdminService.pending_activations",
        "web/routers/admin.py::activation_queue",
        "web/routers/admin_billing.py::credit_pack_dto",
        "web/routers/admin_billing.py::plan_tier_dto",
        # The public catalogue (new customers get the current terms).
        "db/billing_repo.py::active_catalogue",
        "web/routers/billing.py::_render_public_catalogue",
        "web/routers/billing.py::get_catalogue",
        # KNOWN LEAK (review I-4): ``_plan_tier_dto`` also serves the subscriber's own summary,
        # which must show ``terms_for(sub)``. Remove this line when I-4 splits it.
        "web/routers/billing.py::_plan_tier_dto",
    }
)


def _is_tier_receiver(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _TIER_NAMES
    return isinstance(node, ast.Attribute) and node.attr == "tier"


def _tier_term_reads(tree: ast.AST) -> list[tuple[str, int, str]]:
    """``(qualified function, line, text)`` for every ``<tier>.<term>`` attribute read.

    The qualified name joins the enclosing classes and functions (``Service.method.helper``), so a
    same-named function elsewhere in a module never inherits an exemption.
    """
    found: list[tuple[str, int, str]] = []

    def walk(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = function
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                name = child.name if function == "<module>" else f"{function}.{child.name}"
            if (
                isinstance(child, ast.Attribute)
                and child.attr in _TERM_ATTRS
                and _is_tier_receiver(child.value)
            ):
                found.append((function, child.lineno, f"{ast.unparse(child.value)}.{child.attr}"))
            walk(child, name)

    walk(tree, "<module>")
    return found


def _scan_violations(root: Path, allowed: frozenset[str] = _ALLOWED) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(_SKIPPED_DIRS):
            continue
        for function, line, text in _tier_term_reads(ast.parse(path.read_text(encoding="utf-8"))):
            if f"{rel}::{function}" not in allowed:
                violations.append(f"{rel}:{line} {text} in {function}")
    return violations


def test_no_module_prices_or_grants_for_a_subscriber_from_the_live_tier() -> None:
    assert _scan_violations(_ROOT) == []


def test_every_allow_list_entry_still_reads_a_tier() -> None:
    """A stale entry would hide a future leak in a function that no longer needs the exemption."""
    reads = {
        f"{path.relative_to(_ROOT).as_posix()}::{function}"
        for path in _ROOT.rglob("*.py")
        if not path.relative_to(_ROOT).as_posix().startswith(_SKIPPED_DIRS)
        for function, _, _ in _tier_term_reads(ast.parse(path.read_text(encoding="utf-8")))
    }
    assert sorted(_ALLOWED - reads) == []


@pytest.mark.parametrize(
    "source",
    [
        "def grant(tier):\n    return tier.allowance_units\n",
        "def grant(t):\n    return t.price_minor\n",
        "def grant(row):\n    return row.included_seats\n",
        "def grant(s):\n    return s.tier.extra_seat_price_minor\n",
        "def grant(s):\n    return s.subscription.tier.seat_allowance_units\n",
    ],
)
def test_the_scan_catches_a_tier_read_by_any_receiver_style(tmp_path: Path, source: str) -> None:
    bad = tmp_path / "db"
    bad.mkdir()
    (bad / "somewhere.py").write_text(source, encoding="utf-8")
    assert len(_scan_violations(tmp_path, frozenset())) == 1


def test_the_scan_allows_a_named_function_and_nothing_else_in_its_module(tmp_path: Path) -> None:
    bad = tmp_path / "db"
    bad.mkdir()
    (bad / "somewhere.py").write_text(
        "def priced(tier):\n    return tier.price_minor\n"
        "def leaky(tier):\n    return tier.allowance_units\n",
        encoding="utf-8",
    )
    assert _scan_violations(tmp_path, frozenset({"db/somewhere.py::priced"})) == [
        "db/somewhere.py:4 tier.allowance_units in leaky"
    ]


def test_an_exemption_is_qualified_by_class_and_never_covers_a_same_named_function(
    tmp_path: Path,
) -> None:
    bad = tmp_path / "db"
    bad.mkdir()
    (bad / "somewhere.py").write_text(
        "class Svc:\n    def priced(self, tier):\n        return tier.price_minor\n"
        "def priced(tier):\n    return tier.price_minor\n",
        encoding="utf-8",
    )
    assert _scan_violations(tmp_path, frozenset({"db/somewhere.py::Svc.priced"})) == [
        "db/somewhere.py:5 tier.price_minor in priced"
    ]


def test_the_scan_catches_a_tier_read_in_a_function_nested_in_an_exempt_one(
    tmp_path: Path,
) -> None:
    bad = tmp_path / "db"
    bad.mkdir()
    (bad / "somewhere.py").write_text(
        "def outer(tier):\n    def amount(t):\n        return t.price_minor\n    return amount\n",
        encoding="utf-8",
    )
    assert _scan_violations(tmp_path, frozenset({"db/somewhere.py::outer"})) == [
        "db/somewhere.py:3 t.price_minor in outer.amount"
    ]
