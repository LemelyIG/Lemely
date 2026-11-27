# Paymob billing Phase 01 — usage ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the usage ledger: migration `0052_usage_ledger`, its ORM models, the pure pricing
core, and `UsageLedger` (grants, reserve, settle, release, expiry, debt, caps, reconcile), all
tested against real Postgres.

**Architecture:** `lemely/core/usage_types.py` and `lemely/core/usage_pricing.py` are pure (no DB,
pinned by a new import-linter contract). `lemely/db/models/usage.py` declares seven tables;
`usage_entries` is append-only through a trigger installed both by migration `0052` and, for
`create_all` test databases, by an `after_create` listener. `lemely/db/usage_ledger_repo.py`
holds `UsageLedger`, which works inside the caller's transaction: it takes one advisory lock per
owner (ascending UUID), then `FOR UPDATE` row locks on `usage_grant_balances` in payer-chain and
spend order, and writes the cached balance and the append-only entries together.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 (typed ORM), Alembic, Postgres (psycopg 3), pytest,
ruff, mypy `--strict`, pyright, import-linter.

**Spec:** `docs/superpowers/specs/2026-11-02-paymob-billing-design.md` §4.1 (`usage_rates`,
`usage_estimators`), §4.5, §5.6–§5.8, §6, §9. **Index and fixed contracts:**
`docs/superpowers/plans/2026-11-05-paymob-billing-00-index.md` ("Phase 01 — usage ledger").

## Contract deviations

Each is the closest correct version of the index contract; the reason follows.

1. **`usage_jobs.payer_chain` (JSONB, NOT NULL) is an extra column.** The fixed signature
   `settle(job_id, *, actual_cost_usd, now)` takes no payers, yet settle must keep drawing down
   the chain past the reservation and must find the payer of last resort (§5.7 step 5). The
   ledger stores the chain at `reserve` time and reads it back. To serialise it,
   `lemely/core/usage_types.py` also exports `PayerJson`, `payer_to_json` and `payer_from_json`
   (additive), plus `ESTIMATOR_INPUT_KINDS` for the enum pin test.
2. **`usage_entries.reason` (TEXT, NULL) is an extra column.** `claw_back_grant`, `adjust` and
   `forgive_debt` take a `reason`; it is stored on the entries they write instead of being
   dropped. (Phase 07's audit log still records admin actions separately.)
3. **`usage_entries.teacher_member_id` is the payer's `teacher_member_id` when the payer has one,
   else the job's.** The spec says "copied from the job". With two seats on one subject (§5.6:
   all seat allowances, then each seat's teacher credits), the job carries only the first seat,
   so the second teacher's credit draws would count against the first seat's cap. Caps are
   counted per `(grant owner, payer.teacher_member_id)`.
4. **Lock order: owner advisory locks in ascending UUID order first, then row locks in chain
   order.** The spec says "across owners, locks are taken in payer-chain order". That order
   deadlocks when two chains name the same two owners in opposite orders: Task 9's
   `test_opposite_chain_orders_do_not_deadlock` fails with `DeadlockDetected` when the owner locks
   follow chain order (verified while writing this plan). The global UUID order cannot deadlock,
   and the owner lock also serialises the debt check for an owner with no grants to lock.
5. **A `seat_allowance` grant does not repay the student's debt.** §5.8 says "every new grant";
   §2.4 names the repayers (renewal allowance, credit pack, auto top-up), and §5.6 keeps a seat
   allowance usable while the student has debt. A seat grant is the teacher's money for in-scope
   work, so it never pays the student's own debt.
6. **`InsufficientBalance(message: str = "", *, available: int = 0, required: int = 0)`** carries
   both numbers as attributes (the index shows `...`); Phase 04 needs them for the 402 body. The
   optional positional message keeps Phase 07's test double (`InsufficientBalance("not enough")`)
   valid.
7. **`reconcile_balances()` returns one `(row_id, cached, actual)` tuple per drifted value** — a
   grant's `remaining`, a grant's `held` (both keyed by grant id) and a debt's `outstanding`
   (keyed by debt id) — and repairs the cache. The spec also asks for drift on debts (§11).
8. **`adjust` with negative units never touches seat grants**: it debits the owner's own
   allowance and credits in spend order, and whatever they cannot cover becomes a `usage_debts`
   row on the owner (no job) plus a `debt` entry — a negative balance exists only as debt (§6).
   Phase 05 relies on this (`adjust(units=-n)` on an empty balance seeds debt). `adjust` therefore
   never raises `InsufficientBalance`. `claw_back_grant` also closes the grant
   (`expires_at = now`) so units a running job still holds go to `expire_grants` afterwards.
9. **Schema details the spec leaves open:** `usage_entries` has `created_at` only (no
   `updated_at`), following the append-only tutoring logs; foreign keys to `users` are
   `RESTRICT` (ledger rows are a money record; the app never hard-deletes users);
   `usage_debts.job_id` is nullable (FK to `usage_jobs.job_id`); `Payer` rejects a capped payer
   with no `teacher_member_id` (the cap could not be counted); `meter_fraction` sums every current
   allowance grant (an upgrade adds a second one for the same period).

## Global Constraints

- Work only in the worktree `/home/sico/Code/Lemely/.claude/worktrees/paymob-integration`
  (branch `feat/paymob-integration`). All commands below run from that directory.
- Signed commits only, staged by path: `git add <paths>` then
  `git commit -S -m "<type>(<scope>): ..." -- <paths>`. Scope for this phase: `feat(usage):`
  (`test(usage):` for a tests-only task).
- Before each commit run `/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files` and fix
  every failure. The ruff hook autofixes: re-run until it passes, then re-run the task's tests
  on the fixed tree before committing.
- Run tests as `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest <files> -v --no-cov`.
  `--no-cov` is required: `pyproject.toml` sets `--cov-fail-under=70`, which fails any subset
  run. Never run the full suite (`make test`, bare `pytest`). The DB tests need the local
  Postgres on `127.0.0.1:54322` (they skip, not fail, without it — a skip is not a pass).
- `lemely/db/models/*` never imports `lemely.core`; mirror enums and pin them with a test.
- `lemely/core/usage_types.py` and `lemely/core/usage_pricing.py` import no DB, web or I/O code.
- Usage is integer units (`BIGINT`); USD cost is `Decimal` stored as `NUMERIC(12, 6)`.
- UUID primary keys with `server_default=sa.text("gen_random_uuid()")`, Postgres enums whose
  member names equal their values, `TimestampMixin` on every mutable table.
- No placeholders: no `TODO`, no `pass` bodies, no skipped or stub tests.
- Do not push. Do not open PRs.

## File structure

| File | Responsibility | Task |
|---|---|---|
| `lemely/core/usage_types.py` | `GrantScope`, `Payer`, `EstimatorParams`, payer JSON round trip | 1 |
| `lemely/core/usage_pricing.py` | `GRANT_PRIORITY`, `usd_to_units`, `estimate_range`, `prorate_minor`, `prorate_units` | 1 |
| `pyproject.toml` | import-linter contract keeping the two modules above pure | 1 |
| `lemely/db/models/usage.py` | 4 enums, 7 models, append-only trigger SQL and `create_all` listener | 2 |
| `lemely/db/models/__init__.py` | register `usage` in `import_all_models` | 2 |
| `lemely/db/migrations/versions/0052_usage_ledger.py` | the migration | 3 |
| `lemely/db/usage_ledger_repo.py` | `InsufficientBalance`, `UsageLedger` | 4–8 |
| `tests/usage_db.py` | shared throwaway-DB fixture helpers and seeders (not collected) | 2, 4, 5 |
| `tests/test_usage_pricing.py` | pure unit tests | 1 |
| `tests/test_usage_models.py` | enum pins, CHECKs, trigger on `create_all` | 2 |
| `tests/test_migration_usage_ledger.py` | migration names, trigger, round trip | 3 |
| `tests/test_usage_ledger_grants.py` | `issue_grant`, debt repay, `has_debt`, `available`, `meter_fraction` | 4 |
| `tests/test_usage_ledger_reserve.py` | `reserve`, caps, debt skip, `release`, `expire_stale_jobs` | 5 |
| `tests/test_usage_ledger_settle.py` | `settle` under/at/over, chain draw-down, debt | 6 |
| `tests/test_usage_ledger_admin.py` | `expire_grants`, `claw_back_grant`, `adjust`, `forgive_debt` | 7 |
| `tests/test_usage_ledger_reconcile.py` | `reconcile_balances` | 8 |
| `tests/test_usage_ledger_concurrency.py` | lock races across real connections | 9 |
| `tests/test_db_schema.py`, `tests/test_migration_tutor_evidence_uploads.py` | existing tests pinned to the old table set / head | 2, 3 |

**Ledger arithmetic (read before Tasks 4–8).** A grant's `remaining` is the sum of its `grant`,
`settle`, `expire`, `refund`, `adjust` and `debt_repay` entries; its `held` is the sum of its
`hold` (+) and `release` (−) entries. `available = remaining − held` over usable grants
(`effective_at <= now < expires_at`, or no expiry). Settle first releases every hold of the job,
then charges the held grants (in chain order) up to what each held, then keeps drawing down the
chain, then puts any rest on the last payer as a `usage_debts` row plus a `debt` entry (no grant,
negative units). A forgiveness `adjust` entry has no grant and positive units. Every entry key
is unique per `(grant_id, idempotency_key, kind)`; job entries use `job:<job_id>`.

---

### Task 1: Pure usage types and pricing

**Files:**
- Create: `lemely/core/usage_types.py`
- Create: `lemely/core/usage_pricing.py`
- Modify: `pyproject.toml` (add one `[[tool.importlinter.contracts]]` block before `[tool.pyright]`)
- Test: `tests/test_usage_pricing.py`

**Interfaces:**
- Consumes: nothing.
- Produces (used by Tasks 2, 4–9 and Phase 04):
  - `GrantScope` (`ALLOWANCE`, `CREDITS`, `SEAT`), `Payer(owner_user_id, scope, teacher_member_id=None, cap_units=None, cap_window_start=None, debt_exempt=False)`, `EstimatorParams(version, input_kind, base_low, base_high, per_input_low, per_input_high)`
  - `ESTIMATOR_INPUT_KINDS: frozenset[str]`, `PayerJson = dict[str, str | int | bool | None]`, `payer_to_json(payer: Payer) -> PayerJson`, `payer_from_json(data: PayerJson) -> Payer`
  - `GRANT_PRIORITY: Mapping[str, int]`, `usd_to_units(cost_usd: Decimal, units_per_usd: int) -> int`, `estimate_range(params: EstimatorParams, input_count: int) -> tuple[int, int]`, `prorate_minor(amount_minor, period_start, period_end, now) -> int`, `prorate_units(units, period_start, period_end, now) -> int`

- [ ] **Step 1: Write the failing test**

Create `tests/test_usage_pricing.py`:

```python
"""Pure usage pricing and value types (Paymob billing spec §4.5, §5.6, §9 "Unit")."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from lemely.core.usage_pricing import (
    GRANT_PRIORITY,
    estimate_range,
    prorate_minor,
    prorate_units,
    usd_to_units,
)
from lemely.core.usage_types import (
    ESTIMATOR_INPUT_KINDS,
    EstimatorParams,
    GrantScope,
    Payer,
    payer_from_json,
    payer_to_json,
)

START = datetime(2026, 11, 1, tzinfo=UTC)
END = datetime(2026, 12, 1, tzinfo=UTC)  # 30 days


# ---------------------------------------------------------------------------
# usd_to_units
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cost", "rate", "units"),
    [
        (Decimal("0"), 1000, 0),
        (Decimal("0.004"), 1000, 4),
        (Decimal("0.0042"), 1000, 5),  # rounds up
        (Decimal("0.000001"), 1000, 1),  # any cost is at least one unit
        (Decimal("1.5"), 200, 300),
    ],
)
def test_usd_to_units_rounds_up(cost: Decimal, rate: int, units: int) -> None:
    assert usd_to_units(cost, rate) == units


def test_usd_to_units_refuses_negative_cost_and_nonpositive_rate() -> None:
    with pytest.raises(ValueError, match="cost_usd"):
        usd_to_units(Decimal("-0.01"), 1000)
    with pytest.raises(ValueError, match="units_per_usd"):
        usd_to_units(Decimal("1"), 0)


# ---------------------------------------------------------------------------
# estimate_range
# ---------------------------------------------------------------------------


def _params(kind: str = "pages") -> EstimatorParams:
    return EstimatorParams(
        version=3, input_kind=kind, base_low=2, base_high=4, per_input_low=1, per_input_high=3
    )


@pytest.mark.parametrize("kind", ["pages", "marks", "questions"])
def test_estimate_range_scales_with_the_input_count(kind: str) -> None:
    assert estimate_range(_params(kind), 0) == (2, 4)
    assert estimate_range(_params(kind), 5) == (7, 19)


def test_estimate_range_ignores_the_count_for_input_kind_none() -> None:
    assert estimate_range(_params("none"), 50) == (2, 4)


def test_estimate_range_refuses_a_negative_count() -> None:
    with pytest.raises(ValueError, match="input_count"):
        estimate_range(_params(), -1)


def test_estimator_params_refuse_inverted_or_unknown_settings() -> None:
    with pytest.raises(ValueError, match="input_kind"):
        EstimatorParams(1, "words", 0, 1, 0, 1)
    with pytest.raises(ValueError, match="base_low"):
        EstimatorParams(1, "pages", 5, 4, 0, 1)
    with pytest.raises(ValueError, match="per_input_low"):
        EstimatorParams(1, "pages", 0, 1, 2, 1)
    assert {"pages", "marks", "questions", "none"} == ESTIMATOR_INPUT_KINDS


# ---------------------------------------------------------------------------
# Proration
# ---------------------------------------------------------------------------


def test_prorate_minor_charges_the_remaining_fraction_rounded_up() -> None:
    assert prorate_minor(30000, START, END, START + timedelta(days=10)) == 20000
    # 1/3 of 100 = 33.33 -> 34
    assert prorate_minor(100, START, END, START + timedelta(days=20)) == 34


def test_prorate_minor_clamps_to_the_period() -> None:
    assert prorate_minor(500, START, END, START - timedelta(days=1)) == 500
    assert prorate_minor(500, START, END, START) == 500
    assert prorate_minor(500, START, END, END) == 0
    assert prorate_minor(500, START, END, END + timedelta(days=3)) == 0


def test_prorate_units_matches_minor_rounding() -> None:
    assert prorate_units(1000, START, END, START + timedelta(days=15)) == 500
    assert prorate_units(10, START, END, START + timedelta(days=29, hours=23)) == 1


def test_proration_refuses_an_empty_period_and_a_negative_amount() -> None:
    with pytest.raises(ValueError, match="period_end"):
        prorate_minor(100, END, START, START)
    with pytest.raises(ValueError, match="amount"):
        prorate_units(-1, START, END, START)


# ---------------------------------------------------------------------------
# GRANT_PRIORITY and Payer
# ---------------------------------------------------------------------------


def test_grant_priority_matches_the_spec_table() -> None:
    assert dict(GRANT_PRIORITY) == {
        "period_allowance": 10,
        "seat_allowance": 10,
        "signup": 20,
        "refund": 30,
        "adjustment": 40,
        "credit_pack": 50,
        "auto_topup": 50,
    }
    with pytest.raises(TypeError):
        GRANT_PRIORITY["signup"] = 1  # type: ignore[index]


def test_payer_rules() -> None:
    owner, member = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(ValueError, match="SEAT payer needs"):
        Payer(owner_user_id=owner, scope=GrantScope.SEAT)
    with pytest.raises(ValueError, match="debt_exempt"):
        Payer(owner_user_id=owner, scope=GrantScope.CREDITS, debt_exempt=True)
    with pytest.raises(ValueError, match="cap_units must be"):
        Payer(owner_user_id=owner, scope=GrantScope.CREDITS, teacher_member_id=member, cap_units=-1)
    with pytest.raises(ValueError, match="capped payer"):
        Payer(owner_user_id=owner, scope=GrantScope.CREDITS, cap_units=10)
    with pytest.raises(ValueError, match="cap_window_start"):
        Payer(owner_user_id=owner, scope=GrantScope.CREDITS, cap_window_start=START)
    seat = Payer(
        owner_user_id=owner, scope=GrantScope.SEAT, teacher_member_id=member, debt_exempt=True
    )
    assert seat.debt_exempt


def test_payer_json_round_trip() -> None:
    payers = [
        Payer(owner_user_id=uuid.uuid4(), scope=GrantScope.ALLOWANCE),
        Payer(
            owner_user_id=uuid.uuid4(),
            scope=GrantScope.SEAT,
            teacher_member_id=uuid.uuid4(),
            debt_exempt=True,
        ),
        Payer(
            owner_user_id=uuid.uuid4(),
            scope=GrantScope.CREDITS,
            teacher_member_id=uuid.uuid4(),
            cap_units=250,
            cap_window_start=START,
        ),
    ]
    for payer in payers:
        assert payer_from_json(payer_to_json(payer)) == payer
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_pricing.py -v --no-cov`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'lemely.core.usage_pricing'`.

- [ ] **Step 3: Write `lemely/core/usage_types.py`**

```python
"""Pure value types for the usage ledger (Paymob billing spec §4.5, §5.6).

No database, no web: :mod:`lemely.db.usage_ledger_repo` and the Phase 04 payer
chain builder both import these. ``GrantScope`` decides which of an owner's
grants a :class:`Payer` may draw from:

* ``ALLOWANCE``: hidden grants (``visible = false``) with no seat link.
* ``CREDITS``: visible grants (credit packs, auto top-ups, adjustments).
* ``SEAT``: ``seat_allowance`` grants carrying this payer's ``teacher_member_id``.

A payer chain is an ordered ``Sequence[Payer]``; the last payer is the payer of
last resort and takes any debt. :func:`payer_to_json` and :func:`payer_from_json`
let the ledger store the chain on the job row, so ``settle`` can keep drawing
down the same chain without the caller passing it again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

ESTIMATOR_INPUT_KINDS: frozenset[str] = frozenset({"pages", "marks", "questions", "none"})


class GrantScope(StrEnum):
    ALLOWANCE = "allowance"  # visible=False, teacher_member_id IS NULL
    CREDITS = "credits"  # visible=True
    SEAT = "seat"  # kind=seat_allowance AND teacher_member_id = Payer.teacher_member_id


@dataclass(frozen=True)
class Payer:
    owner_user_id: UUID
    scope: GrantScope
    teacher_member_id: UUID | None = None  # SEAT grants, and cap accounting
    cap_units: int | None = None  # None = no cap
    cap_window_start: datetime | None = None  # None with a cap = lifetime ("total")
    debt_exempt: bool = False  # True only for SEAT payers

    def __post_init__(self) -> None:
        """Reject payers the ledger could not honour."""
        if self.scope is GrantScope.SEAT and self.teacher_member_id is None:
            raise ValueError("a SEAT payer needs teacher_member_id")
        if self.debt_exempt and self.scope is not GrantScope.SEAT:
            raise ValueError("only a SEAT payer may be debt_exempt")
        if self.cap_units is not None and self.cap_units < 0:
            raise ValueError("cap_units must be >= 0")
        if self.cap_units is not None and self.teacher_member_id is None:
            raise ValueError("a capped payer needs teacher_member_id to count the cap")
        if self.cap_window_start is not None and self.cap_units is None:
            raise ValueError("cap_window_start without cap_units")


@dataclass(frozen=True)
class EstimatorParams:
    version: int
    input_kind: str
    base_low: int
    base_high: int
    per_input_low: int
    per_input_high: int

    def __post_init__(self) -> None:
        """Reject settings that would give an inverted or negative range."""
        if self.input_kind not in ESTIMATOR_INPUT_KINDS:
            raise ValueError(f"unknown estimator input_kind {self.input_kind!r}")
        if not 0 <= self.base_low <= self.base_high:
            raise ValueError("need 0 <= base_low <= base_high")
        if not 0 <= self.per_input_low <= self.per_input_high:
            raise ValueError("need 0 <= per_input_low <= per_input_high")


PayerJson = dict[str, str | int | bool | None]


def payer_to_json(payer: Payer) -> PayerJson:
    """A JSON-safe dict for ``usage_jobs.payer_chain``."""
    return {
        "owner_user_id": str(payer.owner_user_id),
        "scope": payer.scope.value,
        "teacher_member_id": (
            str(payer.teacher_member_id) if payer.teacher_member_id is not None else None
        ),
        "cap_units": payer.cap_units,
        "cap_window_start": (
            payer.cap_window_start.isoformat() if payer.cap_window_start is not None else None
        ),
        "debt_exempt": payer.debt_exempt,
    }


def payer_from_json(data: PayerJson) -> Payer:
    """Inverse of :func:`payer_to_json`."""
    member = data["teacher_member_id"]
    cap = data["cap_units"]
    window = data["cap_window_start"]
    return Payer(
        owner_user_id=UUID(str(data["owner_user_id"])),
        scope=GrantScope(str(data["scope"])),
        teacher_member_id=UUID(str(member)) if member is not None else None,
        cap_units=int(cap) if cap is not None else None,
        cap_window_start=datetime.fromisoformat(str(window)) if window is not None else None,
        debt_exempt=bool(data["debt_exempt"]),
    )


__all__ = [
    "ESTIMATOR_INPUT_KINDS",
    "EstimatorParams",
    "GrantScope",
    "Payer",
    "PayerJson",
    "payer_from_json",
    "payer_to_json",
]
```

- [ ] **Step 4: Write `lemely/core/usage_pricing.py`**

```python
"""Pure usage pricing: units from USD, estimate ranges, proration (spec §3, §4.1, §4.5).

No database and no I/O. Every number here is an integer except the USD cost,
which is a :class:`~decimal.Decimal`. Rounding always favours Lemely's books
staying whole: a charge rounds up (``usd_to_units``) and a prorated price rounds
up (``prorate_minor``); a prorated allowance also rounds up (``prorate_units``),
so a user is never short-changed by a fraction of a unit.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from lemely.core.usage_types import EstimatorParams

#: Spend-order priority per ``GrantKind`` value (spec §4.5). Lower spends first.
GRANT_PRIORITY: Mapping[str, int] = MappingProxyType(
    {
        "period_allowance": 10,
        "seat_allowance": 10,
        "signup": 20,
        "refund": 30,
        "adjustment": 40,
        "credit_pack": 50,
        "auto_topup": 50,
    }
)

_MICROSECOND = timedelta(microseconds=1)


def usd_to_units(cost_usd: Decimal, units_per_usd: int) -> int:
    """``ceil(cost_usd * units_per_usd)``; a zero cost is zero units."""
    if units_per_usd <= 0:
        raise ValueError("units_per_usd must be > 0")
    if cost_usd < 0:
        raise ValueError("cost_usd must be >= 0")
    return int((cost_usd * units_per_usd).to_integral_value(rounding=ROUND_CEILING))


def estimate_range(params: EstimatorParams, input_count: int) -> tuple[int, int]:
    """``(low, high)`` units for ``input_count`` inputs; ``none`` ignores the count."""
    if input_count < 0:
        raise ValueError("input_count must be >= 0")
    count = 0 if params.input_kind == "none" else input_count
    return (
        params.base_low + params.per_input_low * count,
        params.base_high + params.per_input_high * count,
    )


def _prorate_ceil(amount: int, period_start: datetime, period_end: datetime, now: datetime) -> int:
    if amount < 0:
        raise ValueError("amount must be >= 0")
    if period_end <= period_start:
        raise ValueError("period_end must be after period_start")
    if now <= period_start:
        return amount
    if now >= period_end:
        return 0
    total = (period_end - period_start) // _MICROSECOND
    left = (period_end - now) // _MICROSECOND
    return -(-amount * left // total)


def prorate_minor(
    amount_minor: int, period_start: datetime, period_end: datetime, now: datetime
) -> int:
    """The share of ``amount_minor`` for the rest of the period, rounded up, in 0..amount."""
    return _prorate_ceil(amount_minor, period_start, period_end, now)


def prorate_units(units: int, period_start: datetime, period_end: datetime, now: datetime) -> int:
    """The share of ``units`` for the rest of the period, rounded up, in 0..units."""
    return _prorate_ceil(units, period_start, period_end, now)


__all__ = ["GRANT_PRIORITY", "estimate_range", "prorate_minor", "prorate_units", "usd_to_units"]
```

- [ ] **Step 5: Add the purity contract to `pyproject.toml`**

Insert this block immediately before the `[tool.pyright]` line (after the
"Tutoring pure rules stay pure" contract):

```toml
[[tool.importlinter.contracts]]
name = "Usage pricing stays pure (Paymob billing spec §3)"
type = "forbidden"
source_modules = [
  "lemely.core.usage_types",
  "lemely.core.usage_pricing",
]
forbidden_modules = [
  "lemely.db",
  "lemely.web",
  "lemely.io",
  "sqlalchemy",
  "fastapi",
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_pricing.py tests/architecture/test_import_linter.py -v --no-cov`
Expected: `20 passed`.

- [ ] **Step 7: Prove the contract can go red, then restore**

Temporarily add `import sqlalchemy  # noqa: F401` as the last import line of
`lemely/core/usage_pricing.py`, run
`/home/sico/Code/Lemely/.venv/bin/lint-imports`, and expect
`Usage pricing stays pure (Paymob billing spec §3) BROKEN`. Remove the line and re-run:
`Contracts: 6 kept, 0 broken.`

- [ ] **Step 8: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/core/usage_types.py lemely/core/usage_pricing.py tests/test_usage_pricing.py pyproject.toml
git commit -S -m "feat(usage): pure usage types, unit pricing and proration" -- lemely/core/usage_types.py lemely/core/usage_pricing.py tests/test_usage_pricing.py pyproject.toml
```

---

### Task 2: Usage-ledger ORM models and append-only trigger

**Files:**
- Create: `lemely/db/models/usage.py`
- Modify: `lemely/db/models/__init__.py` (`import_all_models`)
- Create: `tests/usage_db.py`
- Test: `tests/test_usage_models.py`
- Modify: `tests/test_db_schema.py` (`EXPECTED_TABLES`, `TABLES_WITHOUT_TIMESTAMPS`)

**Interfaces:**
- Consumes (tests only): `GRANT_PRIORITY`, `ESTIMATOR_INPUT_KINDS` from Task 1.
- Produces:
  - Enums `GrantKind`, `UsageJobStatus`, `UsageEntryKind`, `EstimatorInputKind` (Postgres types `grantkind`, `usagejobstatus`, `usageentrykind`, `estimatorinputkind`).
  - Models `UsageRate`, `UsageEstimator`, `UsageGrant`, `UsageGrantBalance` (PK `grant_id`), `UsageJob` (unique `job_id`, `payer_chain: list[PayerJson-shaped dict]`), `UsageDebt`, `UsageEntry`.
  - `APPEND_ONLY_FUNCTION_SQL`, `APPEND_ONLY_TRIGGER_SQL` (Task 3 copies the same SQL into the migration).
  - `tests/usage_db.py`: `NOW`, `usage_database()`, `emptied_after(factory)`, `add_user(factory, role=Role.student) -> uuid.UUID`.

- [ ] **Step 1: Write the failing tests**

Create `tests/usage_db.py`:

```python
"""Database helpers shared by the usage-ledger test modules (Paymob billing Phase 01).

Not a test module (no ``test_`` prefix). Each test module defines its own
``usage_db``/``sm`` fixtures from these helpers, as ``tests/tutoring_db.py``'s
callers do.

* :func:`usage_database` builds one throwaway ``create_all`` database per module.
  ``create_all`` installs the ``usage_entries`` append-only trigger through the
  model's ``after_create`` listener.
* :func:`emptied_after` empties it after every test. ``TRUNCATE`` fires no row
  trigger, so the append-only trigger does not block it.
* :func:`add_user` seeds a user directly. Task 4 adds the ledger seeders.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.enums import Role
from lemely.db.models.users import User
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

import_all_models()

#: A fixed instant, so expiry arithmetic in the tests is exact.
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


@contextmanager
def usage_database() -> Iterator[sessionmaker[Session]]:
    """A fresh ``create_all`` database for one test module."""
    base = make_url(DatabaseSettings().url)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip("local Postgres not reachable")
    name = f"lemely_usage_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(base.set(database=name))
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def emptied_after(factory: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    """Yield ``factory``, then empty every table that references users, and the rates."""
    yield factory
    with factory.begin() as session:
        session.execute(sa.text("TRUNCATE users, usage_rates, usage_estimators CASCADE"))


def add_user(factory: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with factory.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


__all__ = [
    "NOW",
    "add_user",
    "emptied_after",
    "usage_database",
]
```

Create `tests/test_usage_models.py`:

```python
"""Usage-ledger ORM models: enum pins, CHECK constraints, append-only trigger (spec §4.5, §6)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from lemely.core.usage_pricing import GRANT_PRIORITY
from lemely.core.usage_types import ESTIMATOR_INPUT_KINDS
from lemely.db.base import Base
from lemely.db.models.usage import (
    EstimatorInputKind,
    GrantKind,
    UsageEntry,
    UsageEntryKind,
    UsageGrant,
    UsageGrantBalance,
    UsageJobStatus,
)
from tests.usage_db import NOW, add_user, emptied_after, usage_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

USAGE_TABLES = {
    "usage_rates",
    "usage_estimators",
    "usage_grants",
    "usage_grant_balances",
    "usage_jobs",
    "usage_entries",
    "usage_debts",
}


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


# ---------------------------------------------------------------------------
# Metadata layer
# ---------------------------------------------------------------------------


def test_all_usage_tables_registered() -> None:
    assert set(Base.metadata.tables) >= USAGE_TABLES


def test_enum_values_match_the_index_contract() -> None:
    assert [m.value for m in GrantKind] == [
        "period_allowance",
        "seat_allowance",
        "signup",
        "credit_pack",
        "auto_topup",
        "refund",
        "adjustment",
    ]
    assert [m.value for m in UsageJobStatus] == ["open", "settled", "released", "expired"]
    assert [m.value for m in UsageEntryKind] == [
        "grant",
        "hold",
        "release",
        "settle",
        "expire",
        "refund",
        "adjust",
        "debt",
        "debt_repay",
    ]


def test_db_enums_mirror_the_core_vocabularies() -> None:
    """``lemely.db.models`` never imports ``lemely.core``; this pins the copies together."""
    assert {m.value for m in GrantKind} == set(GRANT_PRIORITY)
    assert {m.value for m in EstimatorInputKind} == ESTIMATOR_INPUT_KINDS


def test_foreign_keys_deferred_to_later_phases_are_plain_columns() -> None:
    grants = Base.metadata.tables["usage_grants"]
    for column in ("payment_id", "subscription_period_id", "teacher_member_id"):
        assert grants.c[column].nullable
        assert not grants.c[column].foreign_keys


# ---------------------------------------------------------------------------
# Database layer (create_all)
# ---------------------------------------------------------------------------


def _grant(owner: uuid.UUID, **overrides: object) -> UsageGrant:
    values: dict[str, object] = {
        "owner_user_id": owner,
        "kind": GrantKind.credit_pack,
        "visible": True,
        "priority": 50,
        "units": 10,
        "effective_at": NOW,
        "idempotency_key": f"k:{uuid.uuid4()}",
    }
    values.update(overrides)
    return UsageGrant(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"units": 0},
        {"expires_at": NOW},
        {"kind": GrantKind.seat_allowance, "visible": False},  # seat grant with no member
        {"teacher_member_id": uuid.uuid4()},  # member on a non-seat grant
        {"kind": GrantKind.period_allowance, "visible": True},
    ],
)
def test_usage_grants_checks_reject(
    sm: sessionmaker[Session], overrides: dict[str, object]
) -> None:
    owner = add_user(sm)
    with pytest.raises(IntegrityError), sm.begin() as session:
        session.add(_grant(owner, **overrides))


def test_usage_grants_idempotency_key_is_unique_per_owner(sm: sessionmaker[Session]) -> None:
    owner, other = add_user(sm), add_user(sm)
    with sm.begin() as session:
        session.add(_grant(owner, idempotency_key="same"))
        session.add(_grant(other, idempotency_key="same"))
    with pytest.raises(IntegrityError), sm.begin() as session:
        session.add(_grant(owner, idempotency_key="same"))


@pytest.mark.parametrize(("remaining", "held"), [(5, 6), (5, -1), (-1, 0)])
def test_balance_check_keeps_held_within_remaining(
    sm: sessionmaker[Session], remaining: int, held: int
) -> None:
    owner = add_user(sm)
    with sm.begin() as session:
        row = _grant(owner)
        session.add(row)
    with pytest.raises(IntegrityError), sm.begin() as session:
        session.add(UsageGrantBalance(grant_id=row.id, remaining=remaining, held=held))


def test_usage_entries_are_append_only(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    with sm.begin() as session:
        row = _grant(owner)
        session.add(row)
        session.flush()
        entry = UsageEntry(
            grant_id=row.id,
            kind=UsageEntryKind.grant,
            units=10,
            event_at=NOW,
            idempotency_key="grant",
        )
        session.add(entry)
    with pytest.raises(DBAPIError, match="append-only: UPDATE rejected"), sm.begin() as session:
        session.execute(
            sa.text("UPDATE usage_entries SET units = 99 WHERE id = :i"), {"i": entry.id}
        )
    with pytest.raises(DBAPIError, match="append-only: DELETE rejected"), sm.begin() as session:
        session.execute(sa.text("DELETE FROM usage_entries WHERE id = :i"), {"i": entry.id})
    with sm() as session:
        assert session.scalar(sa.select(UsageEntry.units).where(UsageEntry.id == entry.id)) == 10


def test_usage_entries_unique_per_grant_key_kind(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    with sm.begin() as session:
        row = _grant(owner)
        session.add(row)
        session.flush()
        session.add(
            UsageEntry(
                grant_id=row.id,
                kind=UsageEntryKind.hold,
                units=3,
                event_at=NOW,
                idempotency_key="job:1",
            )
        )
    with pytest.raises(IntegrityError), sm.begin() as session:
        session.add(
            UsageEntry(
                grant_id=row.id,
                kind=UsageEntryKind.hold,
                units=3,
                event_at=NOW + timedelta(seconds=1),
                idempotency_key="job:1",
            )
        )


def test_usage_entries_need_a_target_and_nonzero_units(sm: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError), sm.begin() as session:
        session.add(
            UsageEntry(kind=UsageEntryKind.adjust, units=1, event_at=NOW, idempotency_key="x")
        )
    owner = add_user(sm)
    with sm.begin() as session:
        row = _grant(owner)
        session.add(row)
    with pytest.raises(IntegrityError), sm.begin() as session:
        session.add(
            UsageEntry(
                grant_id=row.id,
                kind=UsageEntryKind.grant,
                units=0,
                event_at=NOW,
                idempotency_key="z",
            )
        )
```

In `tests/test_db_schema.py`, add the seven tables to `EXPECTED_TABLES` (after
`"tutoring_blocks",`, before the closing `}`):

```python
    # Usage ledger (lemely/db/models/usage.py, migration 0052).
    "usage_rates",
    "usage_estimators",
    "usage_grants",
    "usage_grant_balances",
    "usage_jobs",
    "usage_entries",
    "usage_debts",
```

and in the comment block above `TABLES_WITHOUT_TIMESTAMPS`, after the line
`# of the same shape: one row per T6 upload attempt, never updated.`, add:

```python
# ``usage_entries`` (migration 0052) is the usage ledger: a trigger rejects every
# UPDATE and DELETE, so it carries ``created_at`` (and ``event_at``) only.
```

then add `"usage_entries",` as the last member of `TABLES_WITHOUT_TIMESTAMPS` (after
`"tutor_evidence_uploads",`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_models.py tests/test_db_schema.py -v --no-cov`
Expected: `tests/test_usage_models.py` collection ERROR
`ModuleNotFoundError: No module named 'lemely.db.models.usage'`; in `tests/test_db_schema.py`,
`test_all_expected_tables_registered` FAILS (the seven tables are missing from the metadata).

- [ ] **Step 3: Write `lemely/db/models/usage.py`**

```python
"""ORM models for the usage ledger (Paymob billing spec §4.1, §4.5; migration ``0052``).

Seven tables:

* :class:`UsageRate` and :class:`UsageEstimator`: versioned, admin-edited
  catalogue rows. A job records the ``rate_version`` and ``estimator_version``
  it used.
* :class:`UsageGrant`: one block of units owned by one account, with a priority
  and an optional expiry. ``payment_id``, ``subscription_period_id`` and
  ``teacher_member_id`` are plain UUID columns here; migrations ``0053``,
  ``0055`` and ``0054`` add their foreign keys when the target tables exist.
* :class:`UsageGrantBalance`: the cached ``remaining`` and ``held`` of a grant.
  ``reconcile_balances`` rebuilds it from the entries.
* :class:`UsageJob`: one metered action, which is also the usage history row.
  ``payer_chain`` keeps the chain the job reserved against, so ``settle`` can
  keep drawing down it.
* :class:`UsageEntry`: the append-only ledger. A trigger rejects ``UPDATE`` and
  ``DELETE``; :func:`_install_append_only_trigger` installs it on ``create_all``
  databases and migration ``0052`` installs the same SQL on migrated ones.
* :class:`UsageDebt`: negative balance, owed by the payer of last resort.

Sign convention for ``usage_entries.units``: a grant's ``remaining`` is the sum
of its ``grant``, ``settle``, ``expire``, ``refund``, ``adjust`` and
``debt_repay`` entries; its ``held`` is the sum of its ``hold`` (positive) and
``release`` (negative) entries. A ``debt`` entry has no grant and carries the
debt as a negative number; a forgiveness ``adjust`` entry with no grant carries
the forgiven units as a positive number.

The enums mirror (do not import) ``lemely.core``: no module under
``lemely.db.models`` imports ``lemely.core``. ``tests/test_usage_models.py``
pins ``GrantKind`` against ``GRANT_PRIORITY`` and ``EstimatorInputKind`` against
``ESTIMATOR_INPUT_KINDS``.

Foreign keys to ``users`` are ``RESTRICT``: ledger rows are a money record and
the app never hard-deletes a user.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin


class GrantKind(enum.Enum):
    period_allowance = "period_allowance"
    seat_allowance = "seat_allowance"
    signup = "signup"
    credit_pack = "credit_pack"
    auto_topup = "auto_topup"
    refund = "refund"
    adjustment = "adjustment"


class UsageJobStatus(enum.Enum):
    open = "open"
    settled = "settled"
    released = "released"
    expired = "expired"


class UsageEntryKind(enum.Enum):
    grant = "grant"
    hold = "hold"
    release = "release"
    settle = "settle"
    expire = "expire"
    refund = "refund"
    adjust = "adjust"
    debt = "debt"
    debt_repay = "debt_repay"


class EstimatorInputKind(enum.Enum):
    pages = "pages"
    marks = "marks"
    questions = "questions"
    none = "none"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


class UsageRate(TimestampMixin, Base):
    """Units charged per USD of LLM cost, per action, per version."""

    __tablename__ = "usage_rates"
    __table_args__ = (
        sa.UniqueConstraint("version", "action", name="uq_usage_rates_version_action"),
        sa.CheckConstraint("units_per_usd > 0", name="units_per_usd_positive"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    action: Mapped[str] = mapped_column(sa.String, nullable=False)
    units_per_usd: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class UsageEstimator(TimestampMixin, Base):
    """Estimate-range settings per action, per version."""

    __tablename__ = "usage_estimators"
    __table_args__ = (
        sa.UniqueConstraint("version", "action", name="uq_usage_estimators_version_action"),
        sa.CheckConstraint("0 <= base_low AND base_low <= base_high", name="base_range"),
        sa.CheckConstraint(
            "0 <= per_input_low AND per_input_low <= per_input_high", name="per_input_range"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    action: Mapped[str] = mapped_column(sa.String, nullable=False)
    input_kind: Mapped[EstimatorInputKind] = mapped_column(
        sa.Enum(EstimatorInputKind, name="estimatorinputkind"), nullable=False
    )
    base_low: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    base_high: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    per_input_low: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    per_input_high: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class UsageGrant(TimestampMixin, Base):
    """A block of units owned by one account."""

    __tablename__ = "usage_grants"
    __table_args__ = (
        sa.UniqueConstraint(
            "owner_user_id", "idempotency_key", name="uq_usage_grants_owner_idempotency"
        ),
        sa.CheckConstraint("units > 0", name="units_positive"),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_at", name="expires_after_effective"
        ),
        sa.CheckConstraint(
            "(kind = 'seat_allowance') = (teacher_member_id IS NOT NULL)", name="seat_link"
        ),
        sa.CheckConstraint(
            "NOT (visible AND kind IN ('period_allowance', 'seat_allowance'))",
            name="allowance_hidden",
        ),
        sa.Index("ix_usage_grants_owner_spend", "owner_user_id", "priority", "effective_at"),
        sa.Index(
            "ix_usage_grants_expiring",
            "expires_at",
            postgresql_where=sa.text("expires_at IS NOT NULL"),
        ),
        sa.Index(
            "ix_usage_grants_seat",
            "teacher_member_id",
            postgresql_where=sa.text("teacher_member_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[GrantKind] = mapped_column(sa.Enum(GrantKind, name="grantkind"), nullable=False)
    visible: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    teacher_member_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    priority: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    units: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subscription_period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(sa.String, nullable=False)


class UsageGrantBalance(TimestampMixin, Base):
    """Cached ``remaining`` and ``held`` for one grant; rebuilt from the entries."""

    __tablename__ = "usage_grant_balances"
    __table_args__ = (
        sa.CheckConstraint("0 <= held AND held <= remaining", name="held_within_remaining"),
    )

    grant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("usage_grants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    remaining: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    held: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, server_default=sa.literal(0))


class UsageJob(TimestampMixin, Base):
    """One metered action: reservation, charge and the usage-history row."""

    __tablename__ = "usage_jobs"
    __table_args__ = (
        sa.CheckConstraint(
            "0 <= estimate_low AND estimate_low <= estimate_high", name="estimate_range"
        ),
        sa.CheckConstraint("reserved >= 0", name="reserved_nonnegative"),
        sa.CheckConstraint("charged >= 0", name="charged_nonnegative"),
        sa.CheckConstraint(
            "debt_created >= 0 AND debt_created <= charged", name="debt_within_charged"
        ),
        sa.CheckConstraint(
            "(status = 'settled') = (settled_at IS NOT NULL)", name="settled_at_matches"
        ),
        sa.Index("ix_usage_jobs_actor_created", "actor_user_id", "created_at"),
        sa.Index(
            "ix_usage_jobs_open_expires",
            "expires_at",
            postgresql_where=sa.text("status = 'open'"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    teacher_member_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(sa.String, nullable=False)
    estimate_low: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    estimate_high: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    estimator_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    reserved: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    charged: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.literal(0)
    )
    debt_created: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.literal(0)
    )
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 6), nullable=True)
    rate_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    payer_chain: Mapped[list[dict[str, str | int | bool | None]]] = mapped_column(
        JSONB, nullable=False
    )
    status: Mapped[UsageJobStatus] = mapped_column(
        sa.Enum(UsageJobStatus, name="usagejobstatus"),
        nullable=False,
        server_default=sa.text("'open'::usagejobstatus"),
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class UsageDebt(TimestampMixin, Base):
    """Units an account owes after a job overran its chain."""

    __tablename__ = "usage_debts"
    __table_args__ = (
        sa.CheckConstraint("units > 0", name="units_positive"),
        sa.CheckConstraint(
            "0 <= outstanding AND outstanding <= units", name="outstanding_within_units"
        ),
        sa.Index(
            "ix_usage_debts_owner_outstanding",
            "owner_user_id",
            "created_at",
            postgresql_where=sa.text("outstanding > 0"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("usage_jobs.job_id", ondelete="RESTRICT"), nullable=True
    )
    units: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    outstanding: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)


class UsageEntry(Base):
    """One append-only ledger line. ``created_at`` only: a row is never updated."""

    __tablename__ = "usage_entries"
    __table_args__ = (
        sa.UniqueConstraint(
            "grant_id", "idempotency_key", "kind", name="uq_usage_entries_grant_key_kind"
        ),
        sa.CheckConstraint("units <> 0", name="units_nonzero"),
        sa.CheckConstraint("grant_id IS NOT NULL OR debt_id IS NOT NULL", name="has_target"),
        sa.CheckConstraint(
            "kind NOT IN ('debt', 'debt_repay') OR debt_id IS NOT NULL", name="debt_kinds_link"
        ),
        sa.Index(
            "uq_usage_entries_debt_key_kind",
            "debt_id",
            "idempotency_key",
            "kind",
            unique=True,
            postgresql_where=sa.text("grant_id IS NULL"),
        ),
        sa.Index("ix_usage_entries_grant", "grant_id"),
        sa.Index("ix_usage_entries_job", "job_id"),
        sa.Index(
            "ix_usage_entries_cap",
            "teacher_member_id",
            "event_at",
            postgresql_where=sa.text("teacher_member_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("usage_grants.id", ondelete="RESTRICT"), nullable=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("usage_jobs.job_id", ondelete="RESTRICT"), nullable=True
    )
    debt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("usage_debts.id", ondelete="RESTRICT"), nullable=True
    )
    teacher_member_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[UsageEntryKind] = mapped_column(
        sa.Enum(UsageEntryKind, name="usageentrykind"), nullable=False
    )
    units: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    rate_version: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    event_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String, nullable=False)
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


# ---------------------------------------------------------------------------
# Append-only trigger (spec §4.5, §6). Migration 0052 runs the same two statements.
# ---------------------------------------------------------------------------

APPEND_ONLY_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION usage_entries_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'usage_entries is append-only: % rejected', TG_OP;
END;
$$
"""

APPEND_ONLY_TRIGGER_SQL = """
CREATE TRIGGER trg_usage_entries_append_only
BEFORE UPDATE OR DELETE ON usage_entries
FOR EACH ROW EXECUTE FUNCTION usage_entries_reject_mutation()
"""


def _install_append_only_trigger(
    target: sa.Table, connection: sa.Connection, **_kw: object
) -> None:
    """Install the append-only trigger right after ``create_all`` creates the table."""
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text(APPEND_ONLY_FUNCTION_SQL))
        connection.execute(sa.text(APPEND_ONLY_TRIGGER_SQL))


event.listen(UsageEntry.__table__, "after_create", _install_append_only_trigger)


__all__ = [
    "APPEND_ONLY_FUNCTION_SQL",
    "APPEND_ONLY_TRIGGER_SQL",
    "EstimatorInputKind",
    "GrantKind",
    "UsageDebt",
    "UsageEntry",
    "UsageEntryKind",
    "UsageEstimator",
    "UsageGrant",
    "UsageGrantBalance",
    "UsageJob",
    "UsageJobStatus",
    "UsageRate",
]
```

- [ ] **Step 4: Register the module**

In `lemely/db/models/__init__.py`, inside `import_all_models`, add `usage,` between
`tutoring,` and `users,`:

```python
        tutoring,
        usage,
        users,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_models.py tests/test_db_schema.py -v --no-cov`
Expected: all PASS (`test_usage_models.py`: 16 passed). No test may report SKIPPED for
"local Postgres not reachable".

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/models/usage.py lemely/db/models/__init__.py tests/usage_db.py tests/test_usage_models.py tests/test_db_schema.py
git commit -S -m "feat(usage): usage ledger models with append-only entries" -- lemely/db/models/usage.py lemely/db/models/__init__.py tests/usage_db.py tests/test_usage_models.py tests/test_db_schema.py
```

---

### Task 3: Migration `0052_usage_ledger`

**Files:**
- Create: `lemely/db/migrations/versions/0052_usage_ledger.py`
- Test: `tests/test_migration_usage_ledger.py`
- Modify: `tests/test_migration_tutor_evidence_uploads.py:59-64` and `:116` (stop pinning 0051 as head)
- Modify: `tests/test_db_schema.py:286` (stop pinning 0051 as head)

**Interfaces:**
- Consumes: Task 2's models (the test compares the migrated schema with the ORM's names).
- Produces: revision `0052_usage_ledger` (down revision `0051_tutor_evidence_uploads`). Phases
  02–05 chain `0053`–`0055` from it and add the deferred foreign keys on `usage_grants`.
- Index R10: after this task no test asserts that any particular revision is the head (only
  `test_migrations_have_a_single_head` remains). `tests/test_migration_usage_ledger.py` checks
  "0052 is in the history", `>= 48` ORM names (later FKs on `usage_grants` add more) and, after
  downgrading to 0051, only that the seven ledger tables are gone — so 0053–0057 never need to
  edit Phase 01's tests, and later phases' own migration tests assert only that their revision is
  in the history and round-trips.

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration_usage_ledger.py`:

```python
"""Migration 0052_usage_ledger: the usage ledger (Paymob billing spec §4.1, §4.5).

The expected constraint and index names come from the ORM
(``lemely/db/models/usage.py``), so these tests compare the migration with an
independent declaration. The trigger must exist on the migrated schema too,
not only on ``create_all`` databases. A downgrade to 0051 must drop the ledger
and leave 0051's schema in place. Nothing here assumes 0052 is the head, so later
migrations (0053-0057) do not have to edit this file.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import DBAPIError

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import (
    current_revision,
    enum_labels,
    object_names,
    public_tables,
    type_exists,
    upgrade_head,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0052_usage_ledger"
DOWN_REVISION = "0051_tutor_evidence_uploads"
TABLES = [
    "usage_rates",
    "usage_estimators",
    "usage_grants",
    "usage_grant_balances",
    "usage_jobs",
    "usage_debts",
    "usage_entries",
]
ENUMS = {
    "grantkind": [
        "period_allowance",
        "seat_allowance",
        "signup",
        "credit_pack",
        "auto_topup",
        "refund",
        "adjustment",
    ],
    "usagejobstatus": ["open", "settled", "released", "expired"],
    "usageentrykind": [
        "grant",
        "hold",
        "release",
        "settle",
        "expire",
        "refund",
        "adjust",
        "debt",
        "debt_repay",
    ],
    "estimatorinputkind": ["pages", "marks", "questions", "none"],
}


def _orm_names() -> set[str]:
    names: set[str] = set()
    for name in TABLES:
        table = Base.metadata.tables[name]
        names |= {str(constraint.name) for constraint in table.constraints}
        names |= {str(index.name) for index in table.indexes}
    return names


def _trigger_names(session: Session) -> set[str]:
    return set(
        session.execute(
            sa.text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'usage_entries'::regclass "
                "AND NOT tgisinternal"
            )
        ).scalars()
    )


def test_revision_chains_from_0051() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    lineage = {r.revision for r in script_dir.iterate_revisions("heads", "base")}
    assert REVISION in lineage


def test_orm_names_are_non_vacuous() -> None:
    names = _orm_names()
    assert "uq_usage_grants_owner_idempotency" in names
    assert "ck_usage_grant_balances_held_within_remaining" in names
    assert "uq_usage_entries_debt_key_kind" in names
    # At least the 48 objects 0052 creates; 0053-0055 add foreign keys on usage_grants.
    assert len(names) >= 48


def test_tables_constraints_enums_and_trigger_present(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        assert set(TABLES) <= public_tables(session)
        assert object_names(session, TABLES) == _orm_names()
        for name, labels in ENUMS.items():
            assert enum_labels(session, name) == labels
        assert _trigger_names(session) == {"trg_usage_entries_append_only"}


def test_migrated_trigger_rejects_update_and_delete(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    user_id, grant_id = uuid.uuid4(), uuid.uuid4()
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, 'student')"),
            {"u": user_id, "e": f"{user_id}@example.com"},
        )
        session.execute(
            sa.text(
                "INSERT INTO usage_grants (id, owner_user_id, kind, visible, priority, units, "
                "idempotency_key) VALUES (:g, :u, 'signup', false, 20, 10, 'signup')"
            ),
            {"g": grant_id, "u": user_id},
        )
        session.execute(
            sa.text(
                "INSERT INTO usage_entries (grant_id, kind, units, event_at, idempotency_key) "
                "VALUES (:g, 'grant', 10, now(), 'signup')"
            ),
            {"g": grant_id},
        )
    for statement in (
        "UPDATE usage_entries SET units = 11",
        "DELETE FROM usage_entries",
    ):
        with pytest.raises(DBAPIError, match="append-only"), migrated_sessionmaker.begin() as s:
            s.execute(sa.text(statement))


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm() as session:
        before = public_tables(session)

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        # Later revisions' tables are gone too; only "0052's are gone" is this test's claim.
        assert set(TABLES).isdisjoint(public_tables(session))
        assert "tutor_evidence_uploads" in public_tables(session)
        for name in ENUMS:
            assert not type_exists(session, name)
        assert not session.execute(
            sa.text("SELECT count(*) FROM pg_proc WHERE proname = 'usage_entries_reject_mutation'")
        ).scalar_one()

    upgrade_head()

    with sm() as session:
        assert public_tables(session) == before
        assert object_names(session, TABLES) == _orm_names()
        assert _trigger_names(session) == {"trg_usage_entries_append_only"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_migration_usage_ledger.py -v --no-cov`
Expected: `test_revision_chains_from_0051` FAILS with
`alembic.util.exc.CommandError: Can't locate revision identified by '0052_usage_ledger'`;
`test_tables_constraints_enums_and_trigger_present` FAILS (the tables are not in the migrated
database); `test_orm_names_are_non_vacuous` PASSES.

- [ ] **Step 3: Write the migration**

Create `lemely/db/migrations/versions/0052_usage_ledger.py`:

```python
"""usage ledger: rates, estimators, grants, balances, jobs, entries, debts

Revision ID: 0052_usage_ledger
Revises: 0051_tutor_evidence_uploads
Create Date: 2026-11-05 00:00:00.000000

Paymob billing spec §4.1 (``usage_rates``, ``usage_estimators``) and §4.5 (the
ledger). Entirely additive: four new enum types, seven new tables, one trigger
function. The ORM declaration is ``lemely/db/models/usage.py``.

* ``usage_grants.payment_id``, ``subscription_period_id`` and
  ``teacher_member_id`` are plain UUID columns; ``0053``, ``0055`` and ``0054``
  add their foreign keys when ``payments``, ``subscription_periods`` and
  ``teacher_members`` exist.
* ``usage_entries`` is append-only: ``trg_usage_entries_append_only`` rejects
  ``UPDATE`` and ``DELETE``. The SQL is copied from the model module on purpose,
  so a later edit there cannot rewrite history here.
* ``usage_jobs.payer_chain`` (JSONB) and ``usage_entries.reason`` are not in the
  spec's column list; see the Phase 01 plan's "Contract deviations".

``downgrade`` drops the tables, the trigger function and the four enum types.
**It destroys the usage ledger**: snapshot the seven tables before any
downgrade past this revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0052_usage_ledger"
down_revision: str | Sequence[str] | None = "0051_tutor_evidence_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "grantkind",
        (
            "period_allowance",
            "seat_allowance",
            "signup",
            "credit_pack",
            "auto_topup",
            "refund",
            "adjustment",
        ),
    ),
    ("usagejobstatus", ("open", "settled", "released", "expired")),
    (
        "usageentrykind",
        (
            "grant",
            "hold",
            "release",
            "settle",
            "expire",
            "refund",
            "adjust",
            "debt",
            "debt_repay",
        ),
    ),
    ("estimatorinputkind", ("pages", "marks", "questions", "none")),
)

_APPEND_ONLY_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION usage_entries_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'usage_entries is append-only: % rejected', TG_OP;
END;
$$
"""

_APPEND_ONLY_TRIGGER_SQL = """
CREATE TRIGGER trg_usage_entries_append_only
BEFORE UPDATE OR DELETE ON usage_entries
FOR EACH ROW EXECUTE FUNCTION usage_entries_reject_mutation()
"""


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _id() -> sa.Column:
    return sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=False)

    op.create_table(
        "usage_rates",
        _id(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("units_per_usd", sa.BigInteger(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("units_per_usd > 0", name=op.f("ck_usage_rates_units_per_usd_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_rates")),
        sa.UniqueConstraint("version", "action", name="uq_usage_rates_version_action"),
    )

    op.create_table(
        "usage_estimators",
        _id(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("input_kind", _enum("estimatorinputkind"), nullable=False),
        sa.Column("base_low", sa.BigInteger(), nullable=False),
        sa.Column("base_high", sa.BigInteger(), nullable=False),
        sa.Column("per_input_low", sa.BigInteger(), nullable=False),
        sa.Column("per_input_high", sa.BigInteger(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "0 <= base_low AND base_low <= base_high", name=op.f("ck_usage_estimators_base_range")
        ),
        sa.CheckConstraint(
            "0 <= per_input_low AND per_input_low <= per_input_high",
            name=op.f("ck_usage_estimators_per_input_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_estimators")),
        sa.UniqueConstraint("version", "action", name="uq_usage_estimators_version_action"),
    )

    op.create_table(
        "usage_grants",
        _id(),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("kind", _enum("grantkind"), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("teacher_member_id", sa.UUID(), nullable=True),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column("subscription_period_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("units > 0", name=op.f("ck_usage_grants_units_positive")),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_at",
            name=op.f("ck_usage_grants_expires_after_effective"),
        ),
        sa.CheckConstraint(
            "(kind = 'seat_allowance') = (teacher_member_id IS NOT NULL)",
            name=op.f("ck_usage_grants_seat_link"),
        ),
        sa.CheckConstraint(
            "NOT (visible AND kind IN ('period_allowance', 'seat_allowance'))",
            name=op.f("ck_usage_grants_allowance_hidden"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_usage_grants_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_grants")),
        sa.UniqueConstraint(
            "owner_user_id", "idempotency_key", name="uq_usage_grants_owner_idempotency"
        ),
    )
    op.create_index(
        "ix_usage_grants_owner_spend", "usage_grants", ["owner_user_id", "priority", "effective_at"]
    )
    op.create_index(
        "ix_usage_grants_expiring",
        "usage_grants",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.create_index(
        "ix_usage_grants_seat",
        "usage_grants",
        ["teacher_member_id"],
        postgresql_where=sa.text("teacher_member_id IS NOT NULL"),
    )

    op.create_table(
        "usage_grant_balances",
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("remaining", sa.BigInteger(), nullable=False),
        sa.Column("held", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "0 <= held AND held <= remaining",
            name=op.f("ck_usage_grant_balances_held_within_remaining"),
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["usage_grants.id"],
            name=op.f("fk_usage_grant_balances_grant_id_usage_grants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("grant_id", name=op.f("pk_usage_grant_balances")),
    )

    op.create_table(
        "usage_jobs",
        _id(),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("teacher_member_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("estimate_low", sa.BigInteger(), nullable=False),
        sa.Column("estimate_high", sa.BigInteger(), nullable=False),
        sa.Column("estimator_version", sa.Integer(), nullable=False),
        sa.Column("reserved", sa.BigInteger(), nullable=False),
        sa.Column("charged", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("debt_created", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("actual_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("rate_version", sa.Integer(), nullable=False),
        sa.Column("payer_chain", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            _enum("usagejobstatus"),
            server_default=sa.text("'open'::usagejobstatus"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "0 <= estimate_low AND estimate_low <= estimate_high",
            name=op.f("ck_usage_jobs_estimate_range"),
        ),
        sa.CheckConstraint("reserved >= 0", name=op.f("ck_usage_jobs_reserved_nonnegative")),
        sa.CheckConstraint("charged >= 0", name=op.f("ck_usage_jobs_charged_nonnegative")),
        sa.CheckConstraint(
            "debt_created >= 0 AND debt_created <= charged",
            name=op.f("ck_usage_jobs_debt_within_charged"),
        ),
        sa.CheckConstraint(
            "(status = 'settled') = (settled_at IS NOT NULL)",
            name=op.f("ck_usage_jobs_settled_at_matches"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_usage_jobs_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_jobs")),
        sa.UniqueConstraint("job_id", name=op.f("uq_usage_jobs_job_id")),
    )
    op.create_index("ix_usage_jobs_actor_created", "usage_jobs", ["actor_user_id", "created_at"])
    op.create_index(
        "ix_usage_jobs_open_expires",
        "usage_jobs",
        ["expires_at"],
        postgresql_where=sa.text("status = 'open'"),
    )

    op.create_table(
        "usage_debts",
        _id(),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.Column("outstanding", sa.BigInteger(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("units > 0", name=op.f("ck_usage_debts_units_positive")),
        sa.CheckConstraint(
            "0 <= outstanding AND outstanding <= units",
            name=op.f("ck_usage_debts_outstanding_within_units"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_usage_debts_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["usage_jobs.job_id"],
            name=op.f("fk_usage_debts_job_id_usage_jobs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_debts")),
    )
    op.create_index(
        "ix_usage_debts_owner_outstanding",
        "usage_debts",
        ["owner_user_id", "created_at"],
        postgresql_where=sa.text("outstanding > 0"),
    )

    op.create_table(
        "usage_entries",
        _id(),
        sa.Column("grant_id", sa.UUID(), nullable=True),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("debt_id", sa.UUID(), nullable=True),
        sa.Column("teacher_member_id", sa.UUID(), nullable=True),
        sa.Column("kind", _enum("usageentrykind"), nullable=False),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.Column("rate_version", sa.Integer(), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("units <> 0", name=op.f("ck_usage_entries_units_nonzero")),
        sa.CheckConstraint(
            "grant_id IS NOT NULL OR debt_id IS NOT NULL", name=op.f("ck_usage_entries_has_target")
        ),
        sa.CheckConstraint(
            "kind NOT IN ('debt', 'debt_repay') OR debt_id IS NOT NULL",
            name=op.f("ck_usage_entries_debt_kinds_link"),
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["usage_grants.id"],
            name=op.f("fk_usage_entries_grant_id_usage_grants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["usage_jobs.job_id"],
            name=op.f("fk_usage_entries_job_id_usage_jobs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["debt_id"],
            ["usage_debts.id"],
            name=op.f("fk_usage_entries_debt_id_usage_debts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_entries")),
        sa.UniqueConstraint(
            "grant_id", "idempotency_key", "kind", name="uq_usage_entries_grant_key_kind"
        ),
    )
    op.create_index(
        "uq_usage_entries_debt_key_kind",
        "usage_entries",
        ["debt_id", "idempotency_key", "kind"],
        unique=True,
        postgresql_where=sa.text("grant_id IS NULL"),
    )
    op.create_index("ix_usage_entries_grant", "usage_entries", ["grant_id"])
    op.create_index("ix_usage_entries_job", "usage_entries", ["job_id"])
    op.create_index(
        "ix_usage_entries_cap",
        "usage_entries",
        ["teacher_member_id", "event_at"],
        postgresql_where=sa.text("teacher_member_id IS NOT NULL"),
    )
    op.execute(_APPEND_ONLY_FUNCTION_SQL)
    op.execute(_APPEND_ONLY_TRIGGER_SQL)


def downgrade() -> None:
    """Downgrade schema: drop the ledger, its trigger function and its enum types."""
    op.drop_table("usage_entries")  # drops trg_usage_entries_append_only with it
    op.execute("DROP FUNCTION usage_entries_reject_mutation()")
    op.drop_table("usage_debts")
    op.drop_table("usage_jobs")
    op.drop_table("usage_grant_balances")
    op.drop_table("usage_grants")
    op.drop_table("usage_estimators")
    op.drop_table("usage_rates")
    bind = op.get_bind()
    for name, _values in reversed(_ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
```

- [ ] **Step 4: Unpin 0051 as the head in the two existing tests**

Adding 0052 breaks two assertions that hard-code 0051 as the head. Replace them with lineage
checks, so the next migration (0053) does not break them again.

In `tests/test_migration_tutor_evidence_uploads.py`, replace

```python
def test_revision_chains_from_0050_and_is_the_head() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    assert head_revision() == REVISION
```

with

```python
def test_revision_chains_from_0050_and_is_in_the_head_lineage() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    lineage = {r.revision for r in script_dir.iterate_revisions(head_revision(), "base")}
    assert REVISION in lineage
```

and, in `test_upgrade_downgrade_upgrade_round_trip`, after `upgrade_head()`, replace

```python
        assert current_revision(session) == REVISION
```

with

```python
        assert current_revision(session) == head_revision()
```

In `tests/test_db_schema.py`, in `test_0043_merge_heads_joins_the_develop_and_branch_chains`,
replace

```python
    assert script_dir.get_heads() == ["0051_tutor_evidence_uploads"]
```

with

```python
    lineage = {r.revision for r in script_dir.iterate_revisions("heads", "base")}
    assert "0043_merge_heads" in lineage
```

(`test_migrations_have_a_single_head` in the same file still guards against split heads.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_migration_usage_ledger.py tests/test_migration_tutor_evidence_uploads.py tests/test_db_schema.py -v --no-cov`
Expected: all PASS (`test_migration_usage_ledger.py`: 5 passed). The log shows
`Running upgrade 0051_tutor_evidence_uploads -> 0052_usage_ledger`.

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/migrations/versions/0052_usage_ledger.py tests/test_migration_usage_ledger.py tests/test_migration_tutor_evidence_uploads.py tests/test_db_schema.py
git commit -S -m "feat(usage): migration 0052 for the usage ledger" -- lemely/db/migrations/versions/0052_usage_ledger.py tests/test_migration_usage_ledger.py tests/test_migration_tutor_evidence_uploads.py tests/test_db_schema.py
```

---

### Task 4: Ledger grants, debt repayment, availability and the meter

**Files:**
- Create: `lemely/db/usage_ledger_repo.py`
- Modify: `tests/usage_db.py` (replace whole file)
- Test: `tests/test_usage_ledger_grants.py`

**Interfaces:**
- Consumes: Task 1 (`GRANT_PRIORITY`, `GrantScope`, `Payer`), Task 2 models.
- Produces:
  - `class InsufficientBalance(Exception)` with `__init__(self, message: str = "", *, available: int = 0, required: int = 0)` and attributes `available`, `required`.
  - `REMAINING_KINDS`, `HELD_KINDS: tuple[UsageEntryKind, ...]`.
  - `UsageLedger(session: Session)` with `issue_grant(...) -> UsageGrant` (index signature), `has_debt(owner_user_id) -> bool`, `available(payers, *, now) -> int`, `meter_fraction(owner_user_id, *, teacher_member_id, now) -> float | None`.
  - Internals later tasks call: `_issue(..., reason: str | None)`, `_lock_owners(owner_ids)`, `_slots(payers, *, now, lock, include=None) -> list[_Slot]`, `_walk(slots, need, payers, *, now, after_release=False) -> list[tuple[_Slot, int]]`, `_cap_used(payer) -> int`, `_open_debts(owner_user_id)`, `_entry(*, kind, units, event_at, key, grant_id=None, debt_id=None, job=None, payer=None, reason=None)`; module helpers `_Slot`, `_scope_filter`, `_usable_at`, `_is_usable`, `_cap_key`.
  - `tests/usage_db.py` adds `ACTION`, `RATE_VERSION`, `ESTIMATOR_VERSION`, `UNITS_PER_USD`, `add_rate`, `grant`, `own_chain`, `seat_chain`, `add_debt`, `balance`, `entries`, `debts`, `grant_row`.

- [ ] **Step 1: Write the failing test**

Replace `tests/usage_db.py` with:

```python
"""Database helpers shared by the usage-ledger test modules (Paymob billing Phase 01).

Not a test module (no ``test_`` prefix). Each test module defines its own
``usage_db``/``sm`` fixtures from these helpers, as ``tests/tutoring_db.py``'s
callers do.

* :func:`usage_database` builds one throwaway ``create_all`` database per module.
  ``create_all`` installs the ``usage_entries`` append-only trigger through the
  model's ``after_create`` listener.
* :func:`emptied_after` empties it after every test. ``TRUNCATE`` fires no row
  trigger, so the append-only trigger does not block it.
* ``add_*`` seed users and rates directly; ``balance``/``entries`` read the
  ledger back without going through the repository under test.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.enums import Role
from lemely.db.models.usage import (
    GrantKind,
    UsageDebt,
    UsageEntry,
    UsageGrant,
    UsageGrantBalance,
    UsageRate,
)
from lemely.db.models.users import User
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

import_all_models()

#: A fixed instant, so expiry arithmetic in the tests is exact.
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
RATE_VERSION = 1
ESTIMATOR_VERSION = 1
ACTION = "mark_paper"
#: 1000 units per USD: ``Decimal("0.0042")`` USD is 5 units (ceil of 4.2).
UNITS_PER_USD = 1000


@contextmanager
def usage_database() -> Iterator[sessionmaker[Session]]:
    """A fresh ``create_all`` database for one test module."""
    base = make_url(DatabaseSettings().url)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip("local Postgres not reachable")
    name = f"lemely_usage_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(base.set(database=name))
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def emptied_after(factory: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    """Yield ``factory``, then empty every table that references users, and the rates."""
    yield factory
    with factory.begin() as session:
        session.execute(sa.text("TRUNCATE users, usage_rates, usage_estimators CASCADE"))


def add_user(factory: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with factory.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def add_rate(
    factory: sessionmaker[Session],
    *,
    version: int = RATE_VERSION,
    action: str = ACTION,
    units_per_usd: int = UNITS_PER_USD,
) -> None:
    with factory.begin() as session:
        session.add(
            UsageRate(
                version=version,
                action=action,
                units_per_usd=units_per_usd,
                effective_from=NOW - timedelta(days=30),
            )
        )


def grant(
    factory: sessionmaker[Session],
    owner: uuid.UUID,
    units: int,
    *,
    kind: GrantKind = GrantKind.period_allowance,
    visible: bool = False,
    expires_at: datetime | None = None,
    effective_at: datetime | None = None,
    teacher_member_id: uuid.UUID | None = None,
    key: str | None = None,
) -> uuid.UUID:
    """Issue a grant through the ledger in its own transaction; return its id."""
    with factory.begin() as session:
        issued = UsageLedger(session).issue_grant(
            owner_user_id=owner,
            kind=kind,
            units=units,
            idempotency_key=key or f"test:{uuid.uuid4()}",
            expires_at=expires_at,
            visible=visible,
            effective_at=effective_at or NOW - timedelta(days=1),
            teacher_member_id=teacher_member_id,
        )
        return issued.id


def own_chain(owner: uuid.UUID) -> list[Payer]:
    """``own allowance -> own credits`` (spec §5.6, "anyone else")."""
    return [
        Payer(owner_user_id=owner, scope=GrantScope.ALLOWANCE),
        Payer(owner_user_id=owner, scope=GrantScope.CREDITS),
    ]


def seat_chain(
    student: uuid.UUID, teacher: uuid.UUID, member: uuid.UUID, cap: int | None
) -> list[Payer]:
    """Seated student, in-scope action: seat -> teacher credits (if capped) -> own (§5.6)."""
    chain = [
        Payer(
            owner_user_id=student, scope=GrantScope.SEAT, teacher_member_id=member, debt_exempt=True
        )
    ]
    if cap is not None:
        chain.append(
            Payer(
                owner_user_id=teacher,
                scope=GrantScope.CREDITS,
                teacher_member_id=member,
                cap_units=cap,
            )
        )
    return [*chain, *own_chain(student)]


def add_debt(factory: sessionmaker[Session], owner: uuid.UUID, units: int) -> uuid.UUID:
    """A debt row with no job, inserted directly, bypassing the ledger."""
    with factory.begin() as session:
        debt = UsageDebt(owner_user_id=owner, units=units, outstanding=units)
        session.add(debt)
        session.flush()
        return debt.id


def balance(factory: sessionmaker[Session], grant_id: uuid.UUID) -> tuple[int, int]:
    """``(remaining, held)`` from the cache row."""
    with factory() as session:
        row = session.get(UsageGrantBalance, grant_id)
        assert row is not None
        return row.remaining, row.held


def entries(factory: sessionmaker[Session], **filters: object) -> list[UsageEntry]:
    with factory() as session:
        stmt = sa.select(UsageEntry).order_by(UsageEntry.created_at, UsageEntry.id)
        for column, value in filters.items():
            stmt = stmt.where(getattr(UsageEntry, column) == value)
        return list(session.scalars(stmt))


def debts(factory: sessionmaker[Session], owner: uuid.UUID) -> list[UsageDebt]:
    with factory() as session:
        return list(
            session.scalars(
                sa.select(UsageDebt)
                .where(UsageDebt.owner_user_id == owner)
                .order_by(UsageDebt.created_at, UsageDebt.id)
            )
        )


def grant_row(factory: sessionmaker[Session], grant_id: uuid.UUID) -> UsageGrant:
    with factory() as session:
        row = session.get(UsageGrant, grant_id)
        assert row is not None
        return row


__all__ = [
    "ACTION",
    "ESTIMATOR_VERSION",
    "NOW",
    "RATE_VERSION",
    "UNITS_PER_USD",
    "add_debt",
    "add_rate",
    "add_user",
    "balance",
    "debts",
    "emptied_after",
    "entries",
    "grant",
    "grant_row",
    "own_chain",
    "seat_chain",
    "usage_database",
]
```

Create `tests/test_usage_ledger_grants.py`:

```python
"""UsageLedger grants, debt repayment, availability and the meter (spec §4.5, §5.6, §5.8)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageEntryKind
from lemely.db.usage_ledger_repo import UsageLedger
from tests.usage_db import (
    NOW,
    add_debt,
    add_user,
    balance,
    debts,
    emptied_after,
    entries,
    grant,
    grant_row,
    own_chain,
    usage_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


# ---------------------------------------------------------------------------
# issue_grant
# ---------------------------------------------------------------------------


def test_issue_grant_writes_grant_balance_and_grant_entry(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 120, kind=GrantKind.credit_pack, visible=True, key="pack:1")
    row = grant_row(sm, gid)
    assert (row.kind, row.priority, row.units, row.visible) == (
        GrantKind.credit_pack,
        50,
        120,
        True,
    )
    assert balance(sm, gid) == (120, 0)
    [entry] = entries(sm, grant_id=gid)
    assert (entry.kind, entry.units, entry.idempotency_key) == (UsageEntryKind.grant, 120, "pack:1")


def test_issue_grant_is_idempotent_per_owner_and_key(sm: sessionmaker[Session]) -> None:
    owner, other = add_user(sm), add_user(sm)
    first = grant(sm, owner, 50, key="period:2026-11")
    again = grant(sm, owner, 999, key="period:2026-11")
    elsewhere = grant(sm, other, 50, key="period:2026-11")
    assert again == first
    assert elsewhere != first
    assert balance(sm, first) == (50, 0)
    assert len(entries(sm, grant_id=first)) == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"units": 0}, "units must be > 0"),
        ({"kind": GrantKind.seat_allowance}, "teacher_member_id"),
        ({"teacher_member_id": uuid.uuid4()}, "teacher_member_id"),
        ({"visible": True}, "never visible"),
    ],
)
def test_issue_grant_validates(
    sm: sessionmaker[Session], kwargs: dict[str, object], message: str
) -> None:
    owner = add_user(sm)
    values: dict[str, object] = {
        "owner_user_id": owner,
        "kind": GrantKind.period_allowance,
        "units": 10,
        "idempotency_key": "k",
        "expires_at": None,
        "visible": False,
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match=message), sm.begin() as session:
        UsageLedger(session).issue_grant(**values)  # type: ignore[arg-type]


def test_new_grant_repays_debts_oldest_first(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    older = add_debt(sm, owner, 30)
    newer = add_debt(sm, owner, 50)
    gid = grant(sm, owner, 60, kind=GrantKind.credit_pack, visible=True)
    assert balance(sm, gid) == (0, 0)
    assert [(d.id, d.outstanding) for d in debts(sm, owner)] == [(older, 0), (newer, 20)]
    repays = entries(sm, grant_id=gid, kind=UsageEntryKind.debt_repay)
    assert {e.debt_id: e.units for e in repays} == {older: -30, newer: -30}


def test_seat_allowance_does_not_repay_the_students_debt(sm: sessionmaker[Session]) -> None:
    student = add_user(sm)
    add_debt(sm, student, 30)
    seat = grant(sm, student, 40, kind=GrantKind.seat_allowance, teacher_member_id=uuid.uuid4())
    assert balance(sm, seat) == (40, 0)
    assert debts(sm, student)[0].outstanding == 30


def test_has_debt(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    with sm() as session:
        assert not UsageLedger(session).has_debt(owner)
    add_debt(sm, owner, 5)
    with sm() as session:
        assert UsageLedger(session).has_debt(owner)
    grant(sm, owner, 5, kind=GrantKind.credit_pack, visible=True)
    with sm() as session:
        assert not UsageLedger(session).has_debt(owner)


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------


def test_available_filters_by_scope_and_validity(sm: sessionmaker[Session]) -> None:
    owner, member = add_user(sm), uuid.uuid4()
    grant(sm, owner, 10)  # hidden allowance
    grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    grant(sm, owner, 40, kind=GrantKind.seat_allowance, teacher_member_id=member)
    grant(sm, owner, 80, expires_at=NOW)  # expired at NOW
    grant(sm, owner, 160, effective_at=NOW + timedelta(hours=1))  # not yet effective
    seat = Payer(owner_user_id=owner, scope=GrantScope.SEAT, teacher_member_id=member)
    other_seat = Payer(owner_user_id=owner, scope=GrantScope.SEAT, teacher_member_id=uuid.uuid4())
    with sm() as session:
        ledger = UsageLedger(session)
        assert ledger.available([own_chain(owner)[0]], now=NOW) == 10
        assert ledger.available([own_chain(owner)[1]], now=NOW) == 20
        assert ledger.available(own_chain(owner), now=NOW) == 30
        assert ledger.available([seat], now=NOW) == 40
        assert ledger.available([other_seat], now=NOW) == 0
        assert ledger.available([seat, *own_chain(owner)], now=NOW) == 70


def test_available_skips_an_indebted_payer_but_not_a_debt_exempt_seat(
    sm: sessionmaker[Session],
) -> None:
    student, member = add_user(sm), uuid.uuid4()
    grant(sm, student, 25, kind=GrantKind.seat_allowance, teacher_member_id=member)
    grant(sm, student, 10)
    add_debt(sm, student, 3)  # added after the grants, so nothing repays it
    seat = Payer(
        owner_user_id=student, scope=GrantScope.SEAT, teacher_member_id=member, debt_exempt=True
    )
    with sm() as session:
        assert UsageLedger(session).available([seat, *own_chain(student)], now=NOW) == 25


def test_available_honours_a_cap_shared_by_payers_with_the_same_member(
    sm: sessionmaker[Session],
) -> None:
    teacher, member = add_user(sm, Role.teacher), uuid.uuid4()
    grant(sm, teacher, 50)
    grant(sm, teacher, 50, kind=GrantKind.credit_pack, visible=True)
    capped = [
        Payer(
            owner_user_id=teacher,
            scope=GrantScope.ALLOWANCE,
            teacher_member_id=member,
            cap_units=30,
        ),
        Payer(
            owner_user_id=teacher,
            scope=GrantScope.CREDITS,
            teacher_member_id=member,
            cap_units=30,
        ),
    ]
    with sm() as session:
        assert UsageLedger(session).available(capped, now=NOW) == 30


# ---------------------------------------------------------------------------
# meter_fraction
# ---------------------------------------------------------------------------


def test_meter_fraction_sums_current_period_allowances(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    with sm() as session:
        assert UsageLedger(session).meter_fraction(owner, teacher_member_id=None, now=NOW) is None
    add_debt(sm, owner, 30)
    grant(sm, owner, 100, expires_at=NOW + timedelta(days=10))  # repays 30
    grant(sm, owner, 100, expires_at=NOW + timedelta(days=10))  # an upgrade's top-up
    grant(
        sm, owner, 100, expires_at=NOW - timedelta(minutes=1), effective_at=NOW - timedelta(days=40)
    )
    with sm() as session:
        assert UsageLedger(session).meter_fraction(
            owner, teacher_member_id=None, now=NOW
        ) == pytest.approx(0.15)


def test_meter_fraction_reads_the_seat_grant_for_in_scope_work(sm: sessionmaker[Session]) -> None:
    student, member = add_user(sm), uuid.uuid4()
    grant(sm, student, 40, kind=GrantKind.seat_allowance, teacher_member_id=member)
    grant(sm, student, 100)
    with sm() as session:
        ledger = UsageLedger(session)
        assert ledger.meter_fraction(student, teacher_member_id=member, now=NOW) == 0.0
        assert ledger.meter_fraction(student, teacher_member_id=uuid.uuid4(), now=NOW) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_ledger_grants.py -v --no-cov`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'lemely.db.usage_ledger_repo'`.

- [ ] **Step 3: Write `lemely/db/usage_ledger_repo.py`**

```python
"""The usage ledger: grants, reservations, settlement, expiry, debt (spec §4.5, §5.6-§5.8).

:class:`UsageLedger` works inside the caller's transaction and never commits.
Every method that changes a balance first takes one transaction-scoped advisory
lock per owner involved, in ascending UUID order, then locks the
``usage_grant_balances`` rows it touches with ``FOR UPDATE`` in payer-chain
order and, within one payer, in spend order (``priority``, then ``expires_at``
with never-expiring last, then ``effective_at``, then ``id``). The owner locks
give every writer one global order, so two jobs whose chains name the same
owners in a different order cannot deadlock, and they also serialise the debt
check for an owner that has no grants to lock.

The balance cache and the entries change together under those locks, so
:meth:`UsageLedger.reconcile_balances` finding drift means a bug, not a race.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.core.usage_pricing import GRANT_PRIORITY
from lemely.core.usage_types import GrantScope, Payer
from lemely.db.models.usage import (
    GrantKind,
    UsageDebt,
    UsageEntry,
    UsageEntryKind,
    UsageGrant,
    UsageGrantBalance,
    UsageJob,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

#: Entry kinds that move a grant's ``remaining``; ``hold``/``release`` move ``held``.
REMAINING_KINDS: tuple[UsageEntryKind, ...] = (
    UsageEntryKind.grant,
    UsageEntryKind.settle,
    UsageEntryKind.expire,
    UsageEntryKind.refund,
    UsageEntryKind.adjust,
    UsageEntryKind.debt_repay,
)

HELD_KINDS: tuple[UsageEntryKind, ...] = (UsageEntryKind.hold, UsageEntryKind.release)

_SPEND_ORDER = (
    UsageGrant.priority.asc(),
    UsageGrant.expires_at.asc().nulls_last(),
    UsageGrant.effective_at.asc(),
    UsageGrant.id.asc(),
)


class InsufficientBalance(Exception):
    """The chain cannot cover the amount asked for."""

    def __init__(self, message: str = "", *, available: int = 0, required: int = 0) -> None:
        super().__init__(message or f"available {available} < required {required}")
        self.available = available
        self.required = required


@dataclass
class _Slot:
    """A grant and its balance row, as one payer in the chain sees it."""

    grant: UsageGrant
    balance: UsageGrantBalance
    payer: Payer
    taken: int = 0

    @property
    def free(self) -> int:
        return self.balance.remaining - self.balance.held - self.taken


def _scope_filter(payer: Payer) -> sa.ColumnElement[bool]:
    if payer.scope is GrantScope.ALLOWANCE:
        return sa.and_(UsageGrant.visible.is_(False), UsageGrant.teacher_member_id.is_(None))
    if payer.scope is GrantScope.CREDITS:
        return UsageGrant.visible.is_(True)
    return sa.and_(
        UsageGrant.kind == GrantKind.seat_allowance,
        UsageGrant.teacher_member_id == payer.teacher_member_id,
    )


def _usable_at(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        UsageGrant.effective_at <= now,
        sa.or_(UsageGrant.expires_at.is_(None), UsageGrant.expires_at > now),
    )


def _is_usable(grant: UsageGrant, now: datetime) -> bool:
    return grant.effective_at <= now and (grant.expires_at is None or grant.expires_at > now)


def _cap_key(payer: Payer) -> tuple[uuid.UUID, uuid.UUID] | None:
    if payer.cap_units is None or payer.teacher_member_id is None:
        return None
    return (payer.owner_user_id, payer.teacher_member_id)


class UsageLedger:
    def __init__(self, session: Session) -> None:
        self._session = session

    def issue_grant(
        self,
        *,
        owner_user_id: uuid.UUID,
        kind: GrantKind,
        units: int,
        idempotency_key: str,
        expires_at: datetime | None,
        visible: bool,
        effective_at: datetime | None = None,
        payment_id: uuid.UUID | None = None,
        subscription_period_id: uuid.UUID | None = None,
        teacher_member_id: uuid.UUID | None = None,
    ) -> UsageGrant:
        """Create a grant, or return the one already issued under this key.

        A new grant first repays the owner's debts, oldest first (§5.8). A
        ``seat_allowance`` grant does not: it is the teacher's money for
        in-scope work, and §5.6 keeps it usable while the student has debt.
        """
        return self._issue(
            owner_user_id=owner_user_id,
            kind=kind,
            units=units,
            idempotency_key=idempotency_key,
            expires_at=expires_at,
            visible=visible,
            effective_at=effective_at,
            payment_id=payment_id,
            subscription_period_id=subscription_period_id,
            teacher_member_id=teacher_member_id,
            reason=None,
        )

    def _issue(
        self,
        *,
        owner_user_id: uuid.UUID,
        kind: GrantKind,
        units: int,
        idempotency_key: str,
        expires_at: datetime | None,
        visible: bool,
        effective_at: datetime | None,
        payment_id: uuid.UUID | None,
        subscription_period_id: uuid.UUID | None,
        teacher_member_id: uuid.UUID | None,
        reason: str | None,
    ) -> UsageGrant:
        if units <= 0:
            raise ValueError("units must be > 0")
        if (kind is GrantKind.seat_allowance) != (teacher_member_id is not None):
            raise ValueError("teacher_member_id is set exactly on seat_allowance grants")
        if visible and kind in (GrantKind.period_allowance, GrantKind.seat_allowance):
            raise ValueError("allowance grants are never visible")
        self._lock_owners([owner_user_id])
        existing = self._session.scalars(
            sa.select(UsageGrant).where(
                UsageGrant.owner_user_id == owner_user_id,
                UsageGrant.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        if existing is not None:
            return existing
        at = effective_at if effective_at is not None else datetime.now(UTC)
        grant = UsageGrant(
            owner_user_id=owner_user_id,
            kind=kind,
            visible=visible,
            teacher_member_id=teacher_member_id,
            priority=GRANT_PRIORITY[kind.value],
            units=units,
            effective_at=at,
            expires_at=expires_at,
            payment_id=payment_id,
            subscription_period_id=subscription_period_id,
            idempotency_key=idempotency_key,
        )
        self._session.add(grant)
        self._session.flush()
        balance = UsageGrantBalance(grant_id=grant.id, remaining=units, held=0)
        self._session.add(balance)
        self._entry(
            kind=UsageEntryKind.grant,
            units=units,
            event_at=at,
            key=idempotency_key,
            grant_id=grant.id,
            reason=reason,
        )
        if kind is not GrantKind.seat_allowance:
            self._repay_debts(grant, balance, at)
        self._session.flush()
        return grant

    def _repay_debts(self, grant: UsageGrant, balance: UsageGrantBalance, at: datetime) -> None:
        for debt in self._open_debts(grant.owner_user_id):
            if balance.remaining == 0:
                return
            repay = min(debt.outstanding, balance.remaining)
            self._entry(
                kind=UsageEntryKind.debt_repay,
                units=-repay,
                event_at=at,
                key=f"repay:{debt.id}",
                grant_id=grant.id,
                debt_id=debt.id,
            )
            debt.outstanding -= repay
            balance.remaining -= repay

    def has_debt(self, owner_user_id: uuid.UUID) -> bool:
        return bool(
            self._session.scalar(
                sa.select(
                    sa.exists().where(
                        UsageDebt.owner_user_id == owner_user_id, UsageDebt.outstanding > 0
                    )
                )
            )
        )

    def available(self, payers: Sequence[Payer], *, now: datetime) -> int:
        """Units the chain could reserve now: usable grants, minus holds, within caps."""
        slots = self._slots(payers, now=now, lock=False)
        return sum(take for _slot, take in self._walk(slots, None, payers, now=now))

    def meter_fraction(
        self, owner_user_id: uuid.UUID, *, teacher_member_id: uuid.UUID | None, now: datetime
    ) -> float | None:
        """``(units - remaining) / units`` over the current allowance grants (§4.5).

        With ``teacher_member_id`` it reads that seat's ``seat_allowance``
        grants; without, the owner's ``period_allowance`` grants (an upgrade
        adds a second one for the same period, so they are summed). ``None``
        when there is no current grant.
        """
        if teacher_member_id is not None:
            which = sa.and_(
                UsageGrant.kind == GrantKind.seat_allowance,
                UsageGrant.teacher_member_id == teacher_member_id,
            )
        else:
            which = UsageGrant.kind == GrantKind.period_allowance
        total, remaining = self._session.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(UsageGrant.units), 0),
                sa.func.coalesce(sa.func.sum(UsageGrantBalance.remaining), 0),
            )
            .join(UsageGrantBalance, UsageGrantBalance.grant_id == UsageGrant.id)
            .where(UsageGrant.owner_user_id == owner_user_id, which, _usable_at(now))
        ).one()
        if not total:
            return None
        return (int(total) - int(remaining)) / int(total)

    def _lock_owners(self, owner_ids: Sequence[uuid.UUID]) -> None:
        for owner_id in sorted(set(owner_ids)):
            self._session.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"usage:{owner_id}"},
            )

    def _slots(
        self,
        payers: Sequence[Payer],
        *,
        now: datetime,
        lock: bool,
        include: set[uuid.UUID] | None = None,
    ) -> list[_Slot]:
        """Each payer's grants in spend order, chain order across payers, each grant once."""
        slots: list[_Slot] = []
        seen: set[uuid.UUID] = set()
        for payer in payers:
            reachable = _usable_at(now)
            if include:
                reachable = sa.or_(reachable, UsageGrant.id.in_(include))
            stmt = (
                sa.select(UsageGrant, UsageGrantBalance)
                .join(UsageGrantBalance, UsageGrantBalance.grant_id == UsageGrant.id)
                .where(UsageGrant.owner_user_id == payer.owner_user_id, _scope_filter(payer))
                .where(reachable)
                .order_by(*_SPEND_ORDER)
            )
            if lock:
                stmt = stmt.with_for_update(of=UsageGrantBalance).execution_options(
                    populate_existing=True
                )
            for grant, balance in self._session.execute(stmt).tuples():
                if grant.id in seen:
                    continue
                seen.add(grant.id)
                slots.append(_Slot(grant=grant, balance=balance, payer=payer))
        return slots

    def _walk(
        self,
        slots: Sequence[_Slot],
        need: int | None,
        payers: Sequence[Payer],
        *,
        now: datetime,
        after_release: bool = False,
    ) -> list[tuple[_Slot, int]]:
        """Draw ``need`` (``None`` = everything) down the slots, honouring debt and caps.

        A payer whose owner has debt is skipped unless it is ``debt_exempt``.
        A cap is shared by every payer with the same ``(owner, teacher_member_id)``.
        Marks each drawn amount on ``slot.taken`` and returns ``(slot, take)`` pairs.
        """
        indebted = {
            p.owner_user_id for p in payers if not p.debt_exempt and self.has_debt(p.owner_user_id)
        }
        cap_left: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
        for payer in payers:
            key = _cap_key(payer)
            if key is not None and key not in cap_left and payer.cap_units is not None:
                used = self._cap_used(payer)
                if after_release:
                    used += sum(s.taken for s in slots if _cap_key(s.payer) == key)
                cap_left[key] = max(payer.cap_units - used, 0)
        plan: list[tuple[_Slot, int]] = []
        left = need
        for slot in slots:
            if left is not None and left <= 0:
                break
            if slot.payer.owner_user_id in indebted and not slot.payer.debt_exempt:
                continue
            if not _is_usable(slot.grant, now):
                continue
            take = slot.free
            if left is not None:
                take = min(take, left)
            key = _cap_key(slot.payer)
            if key is not None:
                take = min(take, cap_left[key])
            if take <= 0:
                continue
            slot.taken += take
            if key is not None:
                cap_left[key] -= take
            if left is not None:
                left -= take
            plan.append((slot, take))
        return plan

    def _cap_used(self, payer: Payer) -> int:
        """Settled draws in the cap window plus open holds, for this payer's cap (§5.6)."""
        base = (
            sa.select(sa.func.coalesce(sa.func.sum(UsageEntry.units), 0))
            .join(UsageGrant, UsageGrant.id == UsageEntry.grant_id)
            .where(
                UsageGrant.owner_user_id == payer.owner_user_id,
                UsageEntry.teacher_member_id == payer.teacher_member_id,
            )
        )
        settled = base.where(UsageEntry.kind == UsageEntryKind.settle)
        if payer.cap_window_start is not None:
            settled = settled.where(UsageEntry.event_at >= payer.cap_window_start)
        held = base.where(UsageEntry.kind.in_(HELD_KINDS))
        return -int(self._session.scalar(settled) or 0) + int(self._session.scalar(held) or 0)

    def _open_debts(self, owner_user_id: uuid.UUID) -> Sequence[UsageDebt]:
        return self._session.scalars(
            sa.select(UsageDebt)
            .where(UsageDebt.owner_user_id == owner_user_id, UsageDebt.outstanding > 0)
            .order_by(UsageDebt.created_at, UsageDebt.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()

    def _entry(
        self,
        *,
        kind: UsageEntryKind,
        units: int,
        event_at: datetime,
        key: str,
        grant_id: uuid.UUID | None = None,
        debt_id: uuid.UUID | None = None,
        job: UsageJob | None = None,
        payer: Payer | None = None,
        reason: str | None = None,
    ) -> None:
        member = payer.teacher_member_id if payer is not None else None
        if member is None and job is not None:
            member = job.teacher_member_id
        self._session.add(
            UsageEntry(
                grant_id=grant_id,
                job_id=job.job_id if job is not None else None,
                debt_id=debt_id,
                teacher_member_id=member,
                kind=kind,
                units=units,
                rate_version=job.rate_version if job is not None else None,
                event_at=event_at,
                idempotency_key=key,
                reason=reason,
            )
        )


__all__ = ["HELD_KINDS", "REMAINING_KINDS", "InsufficientBalance", "UsageLedger"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_ledger_grants.py tests/test_usage_models.py -v --no-cov`
Expected: `30 passed`.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/usage_ledger_repo.py tests/usage_db.py tests/test_usage_ledger_grants.py
git commit -S -m "feat(usage): ledger grants, debt repayment and availability" -- lemely/db/usage_ledger_repo.py tests/usage_db.py tests/test_usage_ledger_grants.py
```

---

### Task 5: Reserve, release and job expiry

**Files:**
- Modify: `lemely/db/usage_ledger_repo.py` (import block; append methods to `UsageLedger`)
- Modify: `tests/usage_db.py` (add `reserve`, `job`)
- Test: `tests/test_usage_ledger_reserve.py`

**Interfaces:**
- Consumes: Task 4 internals (`_lock_owners`, `_slots`, `_walk`, `_entry`), `payer_to_json`/`payer_from_json` (Task 1).
- Produces:
  - `reserve(*, job_id, actor_user_id, action, payers, estimate_low, estimate_high, estimator_version, rate_version, teacher_member_id, expires_at, now) -> UsageJob` (raises `InsufficientBalance`, `ValueError` on empty payers or a bad range).
  - `release(job_id, *, now) -> UsageJob`, `expire_stale_jobs(*, now) -> int`. Both raise `LookupError` for an unknown job; closing a job that is not open is a no-op returning it.
  - Internals: `_locked_job(job_id) -> tuple[UsageJob, list[Payer]]`, `_job_holds(job_id) -> dict[uuid.UUID, int]`, `_close(job_id, status, now)`, `_release_slot(slot, held, job, now)`.
  - `tests/usage_db.py`: `reserve(factory, payers, high, *, actor=None, low=0, teacher_member_id=None, expires_at=None, now=NOW) -> uuid.UUID`, `job(factory, job_id) -> UsageJob`.

- [ ] **Step 1: Write the failing test**

In `tests/usage_db.py`, add `UsageJob,` to the `from lemely.db.models.usage import (...)` list
(after `UsageGrantBalance,`), insert this function directly after `add_debt`:

```python
def reserve(
    factory: sessionmaker[Session],
    payers: list[Payer],
    high: int,
    *,
    actor: uuid.UUID | None = None,
    low: int = 0,
    teacher_member_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
    now: datetime = NOW,
```

insert this function directly after `entries`:

```python
def job(factory: sessionmaker[Session], job_id: uuid.UUID) -> UsageJob:
    with factory() as session:
        return session.scalars(sa.select(UsageJob).where(UsageJob.job_id == job_id)).one()
```

and add `"job",` and `"reserve",` to `__all__` (alphabetical: `"job",` after `"grant_row",`,
`"reserve",` after `"own_chain",`).

Create `tests/test_usage_ledger_reserve.py`:

```python
"""UsageLedger reserve, release and job expiry (spec §5.6, §5.7 steps 3, 6, 7)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from lemely.core.usage_types import GrantScope, Payer, payer_to_json
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageEntryKind, UsageJobStatus
from lemely.db.usage_ledger_repo import InsufficientBalance, UsageLedger
from tests.usage_db import (
    NOW,
    add_debt,
    add_user,
    balance,
    emptied_after,
    entries,
    grant,
    job,
    own_chain,
    reserve,
    seat_chain,
    usage_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


# ---------------------------------------------------------------------------
# reserve
# ---------------------------------------------------------------------------


def test_reserve_holds_the_top_of_the_range_in_chain_order(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    allowance = grant(sm, owner, 6)
    credits = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    job_id = reserve(sm, own_chain(owner), 10, low=4)
    assert balance(sm, allowance) == (6, 6)
    assert balance(sm, credits) == (20, 4)
    holds = entries(sm, job_id=job_id, kind=UsageEntryKind.hold)
    assert {(e.grant_id, e.units, e.idempotency_key) for e in holds} == {
        (allowance, 6, f"job:{job_id}"),
        (credits, 4, f"job:{job_id}"),
    }
    row = job(sm, job_id)
    assert (row.status, row.reserved, row.estimate_low, row.estimate_high) == (
        UsageJobStatus.open,
        10,
        4,
        10,
    )
    assert row.payer_chain == [payer_to_json(p) for p in own_chain(owner)]


def test_reserve_spends_by_priority_then_soonest_expiry(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    later = grant(
        sm, owner, 5, kind=GrantKind.credit_pack, visible=True, expires_at=NOW + timedelta(days=60)
    )
    never = grant(sm, owner, 5, kind=GrantKind.credit_pack, visible=True)
    sooner = grant(
        sm, owner, 5, kind=GrantKind.credit_pack, visible=True, expires_at=NOW + timedelta(days=5)
    )
    adjustment = grant(sm, owner, 5, kind=GrantKind.adjustment, visible=True)
    reserve(sm, [own_chain(owner)[1]], 12)
    assert balance(sm, adjustment) == (5, 5)  # priority 40 before 50
    assert balance(sm, sooner) == (5, 5)
    assert balance(sm, later) == (5, 2)
    assert balance(sm, never) == (5, 0)  # never-expiring last


def test_reserve_refuses_when_the_chain_is_short_and_writes_nothing(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 9)
    with pytest.raises(InsufficientBalance) as caught:
        reserve(sm, own_chain(owner), 10)
    assert (caught.value.available, caught.value.required) == (9, 10)
    assert balance(sm, gid) == (9, 0)
    assert entries(sm, kind=UsageEntryKind.hold) == []


def test_insufficient_balance_message_defaults_to_the_numbers() -> None:
    assert str(InsufficientBalance(available=3, required=5)) == "available 3 < required 5"
    assert str(InsufficientBalance("not enough")) == "not enough"


def test_reserve_validates(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    with pytest.raises(ValueError, match="payers"):
        reserve(sm, [], 1, actor=owner)
    with pytest.raises(ValueError, match="estimate_low"):
        reserve(sm, own_chain(owner), 1, low=2)


def test_debt_blocks_the_owners_own_balance_but_not_a_seat(sm: sessionmaker[Session]) -> None:
    student, teacher, member = add_user(sm), add_user(sm, Role.teacher), uuid.uuid4()
    own = grant(sm, student, 50)
    seat = grant(sm, student, 8, kind=GrantKind.seat_allowance, teacher_member_id=member)
    add_debt(sm, student, 1)
    with pytest.raises(InsufficientBalance):
        reserve(sm, own_chain(student), 5)
    reserve(sm, seat_chain(student, teacher, member, cap=None), 8)
    assert balance(sm, seat) == (8, 8)
    assert balance(sm, own) == (50, 0)


def test_teacher_credits_stop_at_the_seat_cap_counting_open_holds(
    sm: sessionmaker[Session],
) -> None:
    student, teacher, member = add_user(sm), add_user(sm, Role.teacher), uuid.uuid4()
    teacher_credits = grant(sm, teacher, 100, kind=GrantKind.credit_pack, visible=True)
    chain = seat_chain(student, teacher, member, cap=10)
    reserve(sm, chain, 6, actor=student, teacher_member_id=member)
    assert balance(sm, teacher_credits) == (100, 6)
    # Only 4 of the cap is left; the student has nothing of their own.
    with pytest.raises(InsufficientBalance) as caught:
        reserve(sm, chain, 6, actor=student, teacher_member_id=member)
    assert caught.value.available == 4
    own = grant(sm, student, 2)
    reserve(sm, chain, 6, actor=student, teacher_member_id=member)
    assert balance(sm, teacher_credits) == (100, 10)
    assert balance(sm, own) == (2, 2)


def test_hold_entries_carry_the_payers_member_for_cap_accounting(
    sm: sessionmaker[Session],
) -> None:
    """Two seats on one subject: the second teacher's credits count against the second cap."""
    student = add_user(sm)
    teacher_a, teacher_b = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    seat_a, seat_b = uuid.uuid4(), uuid.uuid4()
    credits_b = grant(sm, teacher_b, 100, kind=GrantKind.credit_pack, visible=True)
    chain = [
        Payer(
            owner_user_id=student, scope=GrantScope.SEAT, teacher_member_id=seat_a, debt_exempt=True
        ),
        Payer(
            owner_user_id=student, scope=GrantScope.SEAT, teacher_member_id=seat_b, debt_exempt=True
        ),
        Payer(
            owner_user_id=teacher_a, scope=GrantScope.CREDITS, teacher_member_id=seat_a, cap_units=5
        ),
        Payer(
            owner_user_id=teacher_b, scope=GrantScope.CREDITS, teacher_member_id=seat_b, cap_units=5
        ),
        *own_chain(student),
    ]
    job_id = reserve(sm, chain, 5, actor=student, teacher_member_id=seat_a)
    [hold] = entries(sm, job_id=job_id, kind=UsageEntryKind.hold)
    assert (hold.grant_id, hold.teacher_member_id) == (credits_b, seat_b)


# ---------------------------------------------------------------------------
# release and expiry
# ---------------------------------------------------------------------------


def test_release_frees_every_hold_at_no_charge(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    allowance = grant(sm, owner, 6)
    credits = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    job_id = reserve(sm, own_chain(owner), 10)
    with sm.begin() as session:
        released = UsageLedger(session).release(job_id, now=NOW)
        assert released.status is UsageJobStatus.released
    assert balance(sm, allowance) == (6, 0)
    assert balance(sm, credits) == (20, 0)
    releases = entries(sm, job_id=job_id, kind=UsageEntryKind.release)
    assert sorted(e.units for e in releases) == [-6, -4]
    assert job(sm, job_id).charged == 0
    with sm.begin() as session:  # a second release is a no-op
        UsageLedger(session).release(job_id, now=NOW)
    assert len(entries(sm, job_id=job_id, kind=UsageEntryKind.release)) == 2


def test_release_of_an_unknown_job_raises(sm: sessionmaker[Session]) -> None:
    with pytest.raises(LookupError), sm.begin() as session:
        UsageLedger(session).release(uuid.uuid4(), now=NOW)


def test_expire_stale_jobs_releases_only_jobs_past_expiry(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 30)
    stale = reserve(sm, own_chain(owner), 10, expires_at=NOW + timedelta(minutes=5))
    fresh = reserve(sm, own_chain(owner), 10, expires_at=NOW + timedelta(hours=1))
    with sm.begin() as session:
        assert UsageLedger(session).expire_stale_jobs(now=NOW + timedelta(minutes=10)) == 1
    assert job(sm, stale).status is UsageJobStatus.expired
    assert job(sm, fresh).status is UsageJobStatus.open
    assert balance(sm, gid) == (30, 10)
    with sm.begin() as session:
        assert UsageLedger(session).expire_stale_jobs(now=NOW + timedelta(minutes=10)) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_ledger_reserve.py -v --no-cov`
Expected: 10 FAILED, each with `AttributeError: 'UsageLedger' object has no attribute 'reserve'`
(or `'release'`); `test_insufficient_balance_message_defaults_to_the_numbers` PASSES (Task 4
code).

- [ ] **Step 3: Update the import block of `lemely/db/usage_ledger_repo.py`**

Replace everything from the first import after `from __future__ import annotations` down to
(not including) the `#: Entry kinds that move a grant's` comment with:

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.core.usage_pricing import GRANT_PRIORITY
from lemely.core.usage_types import GrantScope, Payer, payer_from_json, payer_to_json
from lemely.db.models.usage import (
    GrantKind,
    UsageDebt,
    UsageEntry,
    UsageEntryKind,
    UsageGrant,
    UsageGrantBalance,
    UsageJob,
    UsageJobStatus,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session
```

- [ ] **Step 4: Append to `class UsageLedger` (after `_entry`)**

```python
    def reserve(
        self,
        *,
        job_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        action: str,
        payers: Sequence[Payer],
        estimate_low: int,
        estimate_high: int,
        estimator_version: int,
        rate_version: int,
        teacher_member_id: uuid.UUID | None,
        expires_at: datetime,
        now: datetime,
    ) -> UsageJob:
        """Hold ``estimate_high`` across the chain and open the job (§5.7 step 3)."""
        if not payers:
            raise ValueError("payers must not be empty")
        if not 0 <= estimate_low <= estimate_high:
            raise ValueError("need 0 <= estimate_low <= estimate_high")
        self._lock_owners([p.owner_user_id for p in payers])
        slots = self._slots(payers, now=now, lock=True)
        plan = self._walk(slots, estimate_high, payers, now=now)
        covered = sum(take for _slot, take in plan)
        if covered < estimate_high:
            raise InsufficientBalance(available=covered, required=estimate_high)
        job = UsageJob(
            job_id=job_id,
            actor_user_id=actor_user_id,
            teacher_member_id=teacher_member_id,
            action=action,
            estimate_low=estimate_low,
            estimate_high=estimate_high,
            estimator_version=estimator_version,
            reserved=estimate_high,
            charged=0,
            debt_created=0,
            rate_version=rate_version,
            payer_chain=[payer_to_json(p) for p in payers],
            status=UsageJobStatus.open,
            expires_at=expires_at,
        )
        self._session.add(job)
        self._session.flush()
        for slot, take in plan:
            self._entry(
                kind=UsageEntryKind.hold,
                units=take,
                event_at=now,
                key=f"job:{job_id}",
                grant_id=slot.grant.id,
                job=job,
                payer=slot.payer,
            )
            slot.balance.held += take
        self._session.flush()
        return job

    def release(self, job_id: uuid.UUID, *, now: datetime) -> UsageJob:
        """Free every hold of a failed job at no charge (§5.7 step 6)."""
        return self._close(job_id, UsageJobStatus.released, now)

    def expire_stale_jobs(self, *, now: datetime) -> int:
        """Release open jobs past ``expires_at`` and mark them expired (§5.7 step 7)."""
        job_ids = self._session.scalars(
            sa.select(UsageJob.job_id)
            .where(UsageJob.status == UsageJobStatus.open, UsageJob.expires_at <= now)
            .order_by(UsageJob.expires_at, UsageJob.job_id)
        ).all()
        expired = 0
        for job_id in job_ids:
            if self._close(job_id, UsageJobStatus.expired, now).status is UsageJobStatus.expired:
                expired += 1
        return expired

    def _locked_job(self, job_id: uuid.UUID) -> tuple[UsageJob, list[Payer]]:
        chain = self._session.scalar(
            sa.select(UsageJob.payer_chain).where(UsageJob.job_id == job_id)
        )
        if chain is None:
            raise LookupError(f"no usage job {job_id}")
        payers = [payer_from_json(p) for p in chain]
        self._lock_owners([p.owner_user_id for p in payers])
        job = self._session.scalars(
            sa.select(UsageJob)
            .where(UsageJob.job_id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        return job, payers

    def _job_holds(self, job_id: uuid.UUID) -> dict[uuid.UUID, int]:
        rows = self._session.execute(
            sa.select(UsageEntry.grant_id, sa.func.sum(UsageEntry.units))
            .where(UsageEntry.job_id == job_id, UsageEntry.kind.in_(HELD_KINDS))
            .group_by(UsageEntry.grant_id)
        ).all()
        return {gid: int(total) for gid, total in rows if gid is not None and total}

    def _close(self, job_id: uuid.UUID, status: UsageJobStatus, now: datetime) -> UsageJob:
        job, payers = self._locked_job(job_id)
        if job.status is not UsageJobStatus.open:
            return job
        holds = self._job_holds(job_id)
        for slot in self._slots(payers, now=now, lock=True, include=set(holds)):
            held = holds.get(slot.grant.id, 0)
            if held:
                self._release_slot(slot, held, job, now)
        job.status = status
        self._session.flush()
        return job

    def _release_slot(self, slot: _Slot, held: int, job: UsageJob, now: datetime) -> None:
        self._entry(
            kind=UsageEntryKind.release,
            units=-held,
            event_at=now,
            key=f"job:{job.job_id}",
            grant_id=slot.grant.id,
            job=job,
            payer=slot.payer,
        )
        slot.balance.held -= held
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_ledger_reserve.py tests/test_usage_ledger_grants.py -v --no-cov`
Expected: `25 passed`.

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/usage_ledger_repo.py tests/usage_db.py tests/test_usage_ledger_reserve.py
git commit -S -m "feat(usage): reserve across the payer chain, release and job expiry" -- lemely/db/usage_ledger_repo.py tests/usage_db.py tests/test_usage_ledger_reserve.py
```

---

### Task 6: Settle at actual cost, chain draw-down and debt

**Files:**
- Modify: `lemely/db/usage_ledger_repo.py` (import block; append methods)
- Test: `tests/test_usage_ledger_settle.py`

**Interfaces:**
- Consumes: Task 5 (`_locked_job`, `_job_holds`, `_release_slot`), Task 4 (`_slots(include=...)`, `_walk(after_release=True)`, `_entry`), `usd_to_units` (Task 1), `UsageRate` (Task 2).
- Produces: `settle(job_id, *, actual_cost_usd: Decimal, now) -> UsageJob` — converts at the
  job's `(rate_version, action)` rate (`LookupError` if missing), releases the holds, charges held
  grants first, draws down the stored chain (skipping indebted non-exempt payers, within caps),
  creates a `UsageDebt` on the last payer's owner for any rest, and sets `status=settled`,
  `charged`, `debt_created`, `actual_cost_usd`, `settled_at`. A job that is not open is returned
  unchanged. Internal: `_create_debt(owner_user_id, units, job, now)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_usage_ledger_settle.py`:

```python
"""UsageLedger settle: actual cost, chain draw-down and debt (spec §5.7 step 5, §5.8, §9)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageEntryKind, UsageJobStatus
from lemely.db.usage_ledger_repo import InsufficientBalance, UsageLedger
from tests.usage_db import (
    NOW,
    add_rate,
    add_user,
    balance,
    debts,
    emptied_after,
    entries,
    grant,
    job,
    own_chain,
    reserve,
    seat_chain,
    usage_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


@pytest.fixture(autouse=True)
def _rate(sm: sessionmaker[Session]) -> None:
    """``emptied_after`` truncates ``usage_rates`` too, so every test re-adds its rate."""
    add_rate(sm)  # 1000 units per USD


def settle(factory: sessionmaker[Session], job_id: uuid.UUID, usd: str) -> None:
    with factory.begin() as session:
        UsageLedger(session).settle(job_id, actual_cost_usd=Decimal(usd), now=NOW)


def test_settle_under_the_reservation_charges_actual_and_releases_the_rest(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 20)
    job_id = reserve(sm, own_chain(owner), 10)
    settle(sm, job_id, "0.0042")  # ceil(4.2) = 5 units
    assert balance(sm, gid) == (15, 0)
    row = job(sm, job_id)
    assert (row.status, row.charged, row.debt_created, row.settled_at) == (
        UsageJobStatus.settled,
        5,
        0,
        NOW,
    )
    assert row.actual_cost_usd == Decimal("0.004200")
    kinds = [(e.kind, e.units) for e in entries(sm, job_id=job_id)]
    assert sorted(kinds, key=lambda k: k[0].value) == [
        (UsageEntryKind.hold, 10),
        (UsageEntryKind.release, -10),
        (UsageEntryKind.settle, -5),
    ]
    assert all(e.rate_version == 1 for e in entries(sm, job_id=job_id))


def test_settle_at_the_reservation(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10)
    job_id = reserve(sm, own_chain(owner), 10)
    settle(sm, job_id, "0.010")
    assert balance(sm, gid) == (0, 0)
    assert job(sm, job_id).charged == 10


def test_settle_over_the_reservation_keeps_drawing_down_the_chain(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    allowance = grant(sm, owner, 10)
    credits = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    job_id = reserve(sm, own_chain(owner), 10)
    assert balance(sm, credits) == (20, 0)
    settle(sm, job_id, "0.025")
    assert balance(sm, allowance) == (0, 0)
    assert balance(sm, credits) == (5, 0)
    assert job(sm, job_id).debt_created == 0
    assert debts(sm, owner) == []


def test_settle_beyond_the_chain_creates_debt_that_blocks_and_is_repaid(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10)
    credits = grant(sm, owner, 30, kind=GrantKind.credit_pack, visible=True)
    allowance_only = own_chain(owner)[:1]
    job_id = reserve(sm, allowance_only, 10)
    settle(sm, job_id, "0.025")  # the credits are not in this chain
    assert balance(sm, gid) == (0, 0)
    assert balance(sm, credits) == (30, 0)
    row = job(sm, job_id)
    assert (row.charged, row.debt_created) == (25, 15)
    [debt] = debts(sm, owner)
    assert (debt.units, debt.outstanding, debt.job_id) == (15, 15, job_id)
    [debt_entry] = entries(sm, kind=UsageEntryKind.debt)
    assert (debt_entry.debt_id, debt_entry.units, debt_entry.grant_id) == (debt.id, -15, None)
    # Debt blocks new jobs on the owner's own balance, even one the credits could cover.
    with pytest.raises(InsufficientBalance):
        reserve(sm, own_chain(owner), 1)
    # The next own grant pays the debt first.
    pack = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    assert balance(sm, pack) == (5, 0)
    assert debts(sm, owner)[0].outstanding == 0
    reserve(sm, own_chain(owner), 5)


def test_debt_lands_on_the_payer_of_last_resort_not_the_teacher(
    sm: sessionmaker[Session],
) -> None:
    student, teacher, member = add_user(sm), add_user(sm, Role.teacher), uuid.uuid4()
    seat = grant(sm, student, 10, kind=GrantKind.seat_allowance, teacher_member_id=member)
    teacher_credits = grant(sm, teacher, 100, kind=GrantKind.credit_pack, visible=True)
    chain = seat_chain(student, teacher, member, cap=5)
    job_id = reserve(sm, chain, 10, actor=student, teacher_member_id=member)
    settle(sm, job_id, "0.030")  # 30 units: seat 10, teacher cap 5, then 15 of debt
    assert balance(sm, seat) == (0, 0)
    assert balance(sm, teacher_credits) == (95, 0)
    assert debts(sm, teacher) == []
    assert [d.units for d in debts(sm, student)] == [15]


def test_cap_window_ignores_settled_draws_before_it(sm: sessionmaker[Session]) -> None:
    student, teacher, member = add_user(sm), add_user(sm, Role.teacher), uuid.uuid4()
    teacher_credits = grant(sm, teacher, 100, kind=GrantKind.credit_pack, visible=True)
    lifetime = seat_chain(student, teacher, member, cap=10)
    first = reserve(sm, lifetime, 8, actor=student, teacher_member_id=member)
    settle(sm, first, "0.008")
    assert balance(sm, teacher_credits) == (92, 0)
    # Lifetime cap: 2 left. A monthly window starting after the first job: 10 left.
    with pytest.raises(InsufficientBalance):
        reserve(sm, lifetime, 8, actor=student, teacher_member_id=member)
    windowed = seat_chain(student, teacher, member, cap=10)
    windowed[1] = Payer(
        owner_user_id=teacher,
        scope=GrantScope.CREDITS,
        teacher_member_id=member,
        cap_units=10,
        cap_window_start=NOW + timedelta(seconds=1),
    )
    reserve(sm, windowed, 8, actor=student, teacher_member_id=member)
    assert balance(sm, teacher_credits) == (92, 8)


def test_held_units_on_a_grant_that_expired_still_settle(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10, expires_at=NOW + timedelta(minutes=1))
    job_id = reserve(sm, own_chain(owner), 10)
    with sm.begin() as session:
        UsageLedger(session).settle(
            job_id, actual_cost_usd=Decimal("0.004"), now=NOW + timedelta(minutes=5)
        )
    assert balance(sm, gid) == (6, 0)
    assert job(sm, job_id).debt_created == 0


def test_settle_is_a_no_op_on_a_closed_job(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10)
    job_id = reserve(sm, own_chain(owner), 10)
    with sm.begin() as session:
        UsageLedger(session).release(job_id, now=NOW)
    settle(sm, job_id, "0.005")
    assert balance(sm, gid) == (10, 0)
    assert job(sm, job_id).status is UsageJobStatus.released
    settled = reserve(sm, own_chain(owner), 10)
    settle(sm, settled, "0.002")
    settle(sm, settled, "0.009")
    assert job(sm, settled).charged == 2
    assert balance(sm, gid) == (8, 0)


def test_settle_needs_the_jobs_rate_and_an_existing_job(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    grant(sm, owner, 10)
    job_id = reserve(sm, own_chain(owner), 1)
    with sm.begin() as session:
        session.execute(sa.text("DELETE FROM usage_rates"))
    with pytest.raises(LookupError, match="no usage rate"):
        settle(sm, job_id, "0.001")
    with pytest.raises(LookupError, match="no usage job"):
        settle(sm, uuid.uuid4(), "0.001")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_ledger_settle.py -v --no-cov`
Expected: 9 FAILED with `AttributeError: 'UsageLedger' object has no attribute 'settle'`.

- [ ] **Step 3: Update the import block**

Replace everything from the first import after `from __future__ import annotations` down to
(not including) the `#: Entry kinds that move a grant's` comment with:

```python
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.core.usage_pricing import GRANT_PRIORITY, usd_to_units
from lemely.core.usage_types import GrantScope, Payer, payer_from_json, payer_to_json
from lemely.db.models.usage import (
    GrantKind,
    UsageDebt,
    UsageEntry,
    UsageEntryKind,
    UsageGrant,
    UsageGrantBalance,
    UsageJob,
    UsageJobStatus,
    UsageRate,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from decimal import Decimal

    from sqlalchemy.orm import Session
```

- [ ] **Step 4: Append to `class UsageLedger` (after `_release_slot`)**

```python
    def settle(self, job_id: uuid.UUID, *, actual_cost_usd: Decimal, now: datetime) -> UsageJob:
        """Charge the actual cost (§5.7 step 5). A job no longer open is returned unchanged."""
        job, payers = self._locked_job(job_id)
        if job.status is not UsageJobStatus.open:
            return job
        units_per_usd = self._session.scalar(
            sa.select(UsageRate.units_per_usd).where(
                UsageRate.version == job.rate_version, UsageRate.action == job.action
            )
        )
        if units_per_usd is None:
            raise LookupError(f"no usage rate for version {job.rate_version}, {job.action!r}")
        need = usd_to_units(actual_cost_usd, units_per_usd)
        charged = need
        holds = self._job_holds(job_id)
        slots = self._slots(payers, now=now, lock=True, include=set(holds))
        settled: dict[uuid.UUID, int] = defaultdict(int)
        # Release every hold, then charge the held grants first, in chain order.
        for slot in slots:
            held = holds.get(slot.grant.id, 0)
            if held == 0:
                continue
            self._release_slot(slot, held, job, now)
            take = min(held, need)
            if take:
                slot.taken += take
                settled[slot.grant.id] += take
                need -= take
        if need:
            for slot, take in self._walk(slots, need, payers, now=now, after_release=True):
                settled[slot.grant.id] += take
                need -= take
        if need:
            self._create_debt(payers[-1].owner_user_id, need, job, now)
        for slot in slots:
            amount = settled.get(slot.grant.id, 0)
            if amount:
                self._entry(
                    kind=UsageEntryKind.settle,
                    units=-amount,
                    event_at=now,
                    key=f"job:{job_id}",
                    grant_id=slot.grant.id,
                    job=job,
                    payer=slot.payer,
                )
                slot.balance.remaining -= amount
        job.status = UsageJobStatus.settled
        job.charged = charged
        job.debt_created = need
        job.actual_cost_usd = actual_cost_usd
        job.settled_at = now
        self._session.flush()
        return job

    def _create_debt(
        self, owner_user_id: uuid.UUID, units: int, job: UsageJob, now: datetime
    ) -> None:
        debt = UsageDebt(
            owner_user_id=owner_user_id, job_id=job.job_id, units=units, outstanding=units
        )
        self._session.add(debt)
        self._session.flush()
        self._entry(
            kind=UsageEntryKind.debt,
            units=-units,
            event_at=now,
            key=f"job:{job.job_id}",
            debt_id=debt.id,
            job=job,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_ledger_settle.py tests/test_usage_ledger_reserve.py tests/test_usage_ledger_grants.py -v --no-cov`
Expected: `34 passed`.

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/usage_ledger_repo.py tests/test_usage_ledger_settle.py
git commit -S -m "feat(usage): settle at actual cost with chain draw-down and debt" -- lemely/db/usage_ledger_repo.py tests/test_usage_ledger_settle.py
```

---

### Task 7: Grant expiry, claw-back, adjustments and debt forgiveness

**Files:**
- Modify: `lemely/db/usage_ledger_repo.py` (append methods; imports unchanged)
- Test: `tests/test_usage_ledger_admin.py`

**Interfaces:**
- Consumes: Task 4 (`_issue`, `_lock_owners`, `_slots`, `_open_debts`, `_entry`). Consumed by Phase 05 (`adjust(units=-n)` seeds debt in its tests), Phase 06 (`adjust`), Phase 07 (`adjust`, `forgive_debt`, `claw_back_grant`).
- Produces:
  - `expire_grants(*, now) -> int` (grants given an `expire` entry; covers `remaining − held` only, keys `expire:<n>`).
  - `claw_back_grant(grant_id, *, reason, now) -> int` (units clawed; second call 0; `LookupError` for an unknown grant).
  - `adjust(*, owner_user_id, units, reason, idempotency_key, now) -> None` (`+units`: visible `adjustment` grant via `_issue`; `-units`: debit own allowance and credits, the uncovered rest becomes a job-less `UsageDebt` plus a `debt` entry, idempotent on the key; `0`: `ValueError`).
  - `forgive_debt(owner_user_id, *, units: int | None, reason, now) -> int`.
  - Internals: `_locked_balance(grant_id) -> UsageGrantBalance`, `_entry_count(grant_id, kind) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_usage_ledger_admin.py`:

```python
"""UsageLedger grant expiry, claw-back, adjustments and debt forgiveness (spec §5.7-§5.8, §6)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from lemely.db.models.usage import GrantKind, UsageEntryKind
from lemely.db.usage_ledger_repo import UsageLedger
from tests.usage_db import (
    NOW,
    add_debt,
    add_user,
    balance,
    debts,
    emptied_after,
    entries,
    grant,
    grant_row,
    own_chain,
    reserve,
    usage_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


def expire_grants(factory: sessionmaker[Session], at: datetime) -> int:
    with factory.begin() as session:
        return UsageLedger(session).expire_grants(now=at)


# ---------------------------------------------------------------------------
# expire_grants
# ---------------------------------------------------------------------------


def test_expire_grants_expires_only_grants_past_expiry(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    old = grant(sm, owner, 10, expires_at=NOW + timedelta(minutes=1))
    live = grant(sm, owner, 10, expires_at=NOW + timedelta(days=1))
    forever = grant(sm, owner, 10, kind=GrantKind.credit_pack, visible=True)
    assert expire_grants(sm, NOW + timedelta(minutes=2)) == 1
    assert balance(sm, old) == (0, 0)
    assert balance(sm, live) == (10, 0)
    assert balance(sm, forever) == (10, 0)
    [entry] = entries(sm, grant_id=old, kind=UsageEntryKind.expire)
    assert entry.units == -10
    assert expire_grants(sm, NOW + timedelta(minutes=3)) == 0


def test_a_grant_expiring_while_held_expires_only_the_unheld_part(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10, expires_at=NOW + timedelta(minutes=1))
    job_id = reserve(sm, own_chain(owner), 4)
    assert expire_grants(sm, NOW + timedelta(minutes=2)) == 1
    assert balance(sm, gid) == (4, 4)
    with sm.begin() as session:
        UsageLedger(session).release(job_id, now=NOW + timedelta(minutes=3))
    assert balance(sm, gid) == (4, 0)
    # The released units are past expiry: unusable now, and the next sweep takes them.
    with sm() as session:
        assert UsageLedger(session).available(own_chain(owner), now=NOW + timedelta(minutes=3)) == 0
    assert expire_grants(sm, NOW + timedelta(minutes=4)) == 1
    assert balance(sm, gid) == (0, 0)
    assert [e.units for e in entries(sm, grant_id=gid, kind=UsageEntryKind.expire)] == [-6, -4]


# ---------------------------------------------------------------------------
# claw_back_grant
# ---------------------------------------------------------------------------


def test_claw_back_removes_unspent_units_and_closes_the_grant(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    pack = grant(sm, owner, 50, kind=GrantKind.credit_pack, visible=True)
    reserve(sm, own_chain(owner), 15)
    with sm.begin() as session:
        assert UsageLedger(session).claw_back_grant(pack, reason="refund #12", now=NOW) == 35
    assert balance(sm, pack) == (15, 15)
    assert grant_row(sm, pack).expires_at == NOW
    [entry] = entries(sm, grant_id=pack, kind=UsageEntryKind.refund)
    assert (entry.units, entry.reason) == (-35, "refund #12")
    with sm.begin() as session:
        assert UsageLedger(session).claw_back_grant(pack, reason="again", now=NOW) == 0
    with pytest.raises(LookupError), sm.begin() as session:
        UsageLedger(session).claw_back_grant(uuid.uuid4(), reason="x", now=NOW)


# ---------------------------------------------------------------------------
# adjust
# ---------------------------------------------------------------------------


def test_positive_adjust_issues_a_visible_grant_that_repays_debt(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    add_debt(sm, owner, 4)
    with sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=owner, units=10, reason="goodwill", idempotency_key="adj:1", now=NOW
        )
    [entry] = entries(sm, kind=UsageEntryKind.grant)
    assert (entry.units, entry.reason) == (10, "goodwill")
    assert entry.grant_id is not None
    adjustment = grant_row(sm, entry.grant_id)
    assert (adjustment.kind, adjustment.visible) == (GrantKind.adjustment, True)
    assert balance(sm, entry.grant_id) == (6, 0)
    assert debts(sm, owner)[0].outstanding == 0


def test_negative_adjust_debits_own_grants_then_records_debt_never_a_seat(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    seat = grant(sm, owner, 100, kind=GrantKind.seat_allowance, teacher_member_id=uuid.uuid4())
    allowance = grant(sm, owner, 5)
    credits = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    with sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=owner, units=-8, reason="abuse", idempotency_key="adj:2", now=NOW
        )
    assert balance(sm, allowance) == (0, 0)
    assert balance(sm, credits) == (17, 0)
    assert balance(sm, seat) == (100, 0)
    with sm.begin() as session:  # the same key again is a no-op
        UsageLedger(session).adjust(
            owner_user_id=owner, units=-8, reason="abuse", idempotency_key="adj:2", now=NOW
        )
    assert balance(sm, credits) == (17, 0)
    # A debit the balance cannot cover leaves the rest as debt on the owner (§6).
    with sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=owner, units=-25, reason="too much", idempotency_key="adj:3", now=NOW
        )
    assert balance(sm, credits) == (0, 0)
    assert balance(sm, seat) == (100, 0)
    [debt] = debts(sm, owner)
    assert (debt.units, debt.outstanding, debt.job_id) == (8, 8, None)
    [debt_entry] = entries(sm, kind=UsageEntryKind.debt)
    assert (debt_entry.units, debt_entry.reason, debt_entry.grant_id) == (-8, "too much", None)
    with sm.begin() as session:  # idempotent even when the debit was all or partly debt
        UsageLedger(session).adjust(
            owner_user_id=owner, units=-25, reason="too much", idempotency_key="adj:3", now=NOW
        )
    assert len(debts(sm, owner)) == 1
    empty = add_user(sm)
    with sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=empty, units=-300, reason="seed debt", idempotency_key="adj:5", now=NOW
        )
    with sm() as session:
        assert UsageLedger(session).has_debt(empty)
    with pytest.raises(ValueError, match="must not be 0"), sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=owner, units=0, reason="zero", idempotency_key="adj:4", now=NOW
        )


# ---------------------------------------------------------------------------
# forgive_debt
# ---------------------------------------------------------------------------


def test_forgive_debt_oldest_first_partial_then_all(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    older = add_debt(sm, owner, 10)
    newer = add_debt(sm, owner, 10)
    with sm.begin() as session:
        assert UsageLedger(session).forgive_debt(owner, units=12, reason="support", now=NOW) == 12
    assert [(d.id, d.outstanding) for d in debts(sm, owner)] == [(older, 0), (newer, 8)]
    with sm.begin() as session:
        assert UsageLedger(session).forgive_debt(owner, units=None, reason="close", now=NOW) == 8
    with sm() as session:
        assert not UsageLedger(session).has_debt(owner)
    forgiven = entries(sm, kind=UsageEntryKind.adjust)
    assert sorted((e.debt_id == older, e.units, e.reason) for e in forgiven) == [
        (False, 2, "support"),
        (False, 8, "close"),
        (True, 10, "support"),
    ]
    with pytest.raises(ValueError, match="units"), sm.begin() as session:
        UsageLedger(session).forgive_debt(owner, units=0, reason="x", now=NOW)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_ledger_admin.py -v --no-cov`
Expected: 6 FAILED with `AttributeError: 'UsageLedger' object has no attribute 'expire_grants'`
(respectively `'claw_back_grant'`, `'adjust'`, `'forgive_debt'`).

- [ ] **Step 3: Append to `class UsageLedger` (after `_create_debt`)**

```python
    def expire_grants(self, *, now: datetime) -> int:
        """Expire the unheld rest of every grant past ``expires_at`` (§5.7 step 8)."""
        candidates = self._session.execute(
            sa.select(UsageGrant.id, UsageGrant.owner_user_id)
            .join(UsageGrantBalance, UsageGrantBalance.grant_id == UsageGrant.id)
            .where(
                UsageGrant.expires_at <= now,
                UsageGrantBalance.remaining > UsageGrantBalance.held,
            )
            .order_by(UsageGrant.expires_at, UsageGrant.id)
        ).all()
        expired = 0
        for grant_id, owner_user_id in candidates:
            self._lock_owners([owner_user_id])
            balance = self._locked_balance(grant_id)
            amount = balance.remaining - balance.held
            if amount <= 0:
                continue
            count = self._entry_count(grant_id, UsageEntryKind.expire)
            self._entry(
                kind=UsageEntryKind.expire,
                units=-amount,
                event_at=now,
                key=f"expire:{count}",
                grant_id=grant_id,
            )
            balance.remaining -= amount
            expired += 1
        self._session.flush()
        return expired

    def claw_back_grant(self, grant_id: uuid.UUID, *, reason: str, now: datetime) -> int:
        """Remove a refunded grant's unspent, unheld units; spent units stay spent (§6).

        The grant is also closed (``expires_at = now``) so units a running job
        still holds go to ``expire_grants`` when that job lets them go.
        Returns the units clawed back; a second call returns 0.
        """
        grant = self._session.get(UsageGrant, grant_id)
        if grant is None:
            raise LookupError(f"no usage grant {grant_id}")
        self._lock_owners([grant.owner_user_id])
        balance = self._locked_balance(grant_id)
        if self._entry_count(grant_id, UsageEntryKind.refund):
            return 0
        if now > grant.effective_at and (grant.expires_at is None or grant.expires_at > now):
            grant.expires_at = now
        amount = balance.remaining - balance.held
        if amount > 0:
            self._entry(
                kind=UsageEntryKind.refund,
                units=-amount,
                event_at=now,
                key="claw_back",
                grant_id=grant_id,
                reason=reason,
            )
            balance.remaining -= amount
        self._session.flush()
        return max(amount, 0)

    def adjust(
        self,
        *,
        owner_user_id: uuid.UUID,
        units: int,
        reason: str,
        idempotency_key: str,
        now: datetime,
    ) -> None:
        """Admin correction: ``+units`` grants, ``-units`` debits.

        ``+units`` issues a visible ``adjustment`` grant (which repays debt
        first). ``-units`` debits the owner's own allowance and credits in spend
        order, never a seat grant (the teacher's money); whatever they cannot
        cover becomes a ``usage_debts`` row on the owner (no job), because a
        negative balance exists only as debt (§6). Idempotent on the key.
        """
        if units == 0:
            raise ValueError("units must not be 0")
        if units > 0:
            self._issue(
                owner_user_id=owner_user_id,
                kind=GrantKind.adjustment,
                units=units,
                idempotency_key=idempotency_key,
                expires_at=None,
                visible=True,
                effective_at=now,
                payment_id=None,
                subscription_period_id=None,
                teacher_member_id=None,
                reason=reason,
            )
            return
        self._lock_owners([owner_user_id])
        on_grant = (
            sa.select(UsageEntry.id)
            .join(UsageGrant, UsageGrant.id == UsageEntry.grant_id)
            .where(
                UsageGrant.owner_user_id == owner_user_id,
                UsageEntry.kind == UsageEntryKind.adjust,
                UsageEntry.idempotency_key == idempotency_key,
            )
        )
        on_debt = (
            sa.select(UsageEntry.id)
            .join(UsageDebt, UsageDebt.id == UsageEntry.debt_id)
            .where(
                UsageDebt.owner_user_id == owner_user_id,
                UsageEntry.kind == UsageEntryKind.debt,
                UsageEntry.idempotency_key == idempotency_key,
            )
        )
        if self._session.scalar(sa.select(sa.exists(on_grant.union_all(on_debt).subquery()))):
            return
        own = [
            Payer(owner_user_id=owner_user_id, scope=GrantScope.ALLOWANCE),
            Payer(owner_user_id=owner_user_id, scope=GrantScope.CREDITS),
        ]
        need = -units
        for slot in self._slots(own, now=now, lock=True):
            take = min(slot.free, need)
            if take <= 0:
                continue
            self._entry(
                kind=UsageEntryKind.adjust,
                units=-take,
                event_at=now,
                key=idempotency_key,
                grant_id=slot.grant.id,
                reason=reason,
            )
            slot.balance.remaining -= take
            need -= take
        if need:
            debt = UsageDebt(owner_user_id=owner_user_id, units=need, outstanding=need)
            self._session.add(debt)
            self._session.flush()
            self._entry(
                kind=UsageEntryKind.debt,
                units=-need,
                event_at=now,
                key=idempotency_key,
                debt_id=debt.id,
                reason=reason,
            )
        self._session.flush()

    def forgive_debt(
        self, owner_user_id: uuid.UUID, *, units: int | None, reason: str, now: datetime
    ) -> int:
        """Forgive up to ``units`` of debt, oldest first (``None`` = all); return units forgiven."""
        if units is not None and units <= 0:
            raise ValueError("units must be > 0 or None")
        self._lock_owners([owner_user_id])
        left = units
        forgiven = 0
        for debt in self._open_debts(owner_user_id):
            amount = debt.outstanding if left is None else min(debt.outstanding, left)
            if amount == 0:
                break
            count = self._session.scalar(
                sa.select(sa.func.count()).where(
                    UsageEntry.debt_id == debt.id,
                    UsageEntry.grant_id.is_(None),
                    UsageEntry.kind == UsageEntryKind.adjust,
                )
            )
            self._entry(
                kind=UsageEntryKind.adjust,
                units=amount,
                event_at=now,
                key=f"forgive:{count}",
                debt_id=debt.id,
                reason=reason,
            )
            debt.outstanding -= amount
            forgiven += amount
            if left is not None:
                left -= amount
        self._session.flush()
        return forgiven

    def _locked_balance(self, grant_id: uuid.UUID) -> UsageGrantBalance:
        return self._session.scalars(
            sa.select(UsageGrantBalance)
            .where(UsageGrantBalance.grant_id == grant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()

    def _entry_count(self, grant_id: uuid.UUID, kind: UsageEntryKind) -> int:
        return int(
            self._session.scalar(
                sa.select(sa.func.count()).where(
                    UsageEntry.grant_id == grant_id, UsageEntry.kind == kind
                )
            )
            or 0
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_ledger_admin.py tests/test_usage_ledger_settle.py tests/test_usage_ledger_reserve.py tests/test_usage_ledger_grants.py -v --no-cov`
Expected: `40 passed`.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/usage_ledger_repo.py tests/test_usage_ledger_admin.py
git commit -S -m "feat(usage): grant expiry, claw-back, adjustments and debt forgiveness" -- lemely/db/usage_ledger_repo.py tests/test_usage_ledger_admin.py
```

---

### Task 8: Nightly reconcile

**Files:**
- Modify: `lemely/db/usage_ledger_repo.py` (append methods; imports unchanged)
- Test: `tests/test_usage_ledger_reconcile.py`

**Interfaces:**
- Consumes: every earlier ledger method (the test drives all entry kinds), `REMAINING_KINDS`, `HELD_KINDS`, `_locked_balance`.
- Produces: `reconcile_balances() -> list[tuple[uuid.UUID, int, int]]` (see deviation 7);
  Phase 04's `usage.reconcile_balances` sweeper alerts when it is non-empty. Internals
  `_grant_sums(grant_id=None)`, `_debt_sums(debt_id=None)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_usage_ledger_reconcile.py`:

```python
"""UsageLedger.reconcile_balances: entries against the cache and the debts (spec §4.5, §6, §11)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind
from lemely.db.usage_ledger_repo import UsageLedger
from tests.usage_db import (
    NOW,
    add_rate,
    add_user,
    balance,
    debts,
    emptied_after,
    grant,
    own_chain,
    reserve,
    seat_chain,
    usage_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


def reconcile(factory: sessionmaker[Session]) -> list[tuple[uuid.UUID, int, int]]:
    with factory.begin() as session:
        return UsageLedger(session).reconcile_balances()


def _busy_ledger(factory: sessionmaker[Session]) -> uuid.UUID:
    """Every entry kind at least once; returns the student, who ends up in debt."""
    add_rate(factory)
    student, teacher, member = add_user(factory), add_user(factory, Role.teacher), uuid.uuid4()
    grant(factory, student, 10, expires_at=NOW + timedelta(minutes=1))
    grant(factory, student, 6, kind=GrantKind.seat_allowance, teacher_member_id=member)
    pack = grant(factory, teacher, 50, kind=GrantKind.credit_pack, visible=True)
    chain = seat_chain(student, teacher, member, cap=5)
    settled = reserve(factory, chain, 8, actor=student, teacher_member_id=member)
    released = reserve(factory, own_chain(student), 3)
    reserve(factory, own_chain(student), 2, expires_at=NOW + timedelta(seconds=30))  # goes stale
    later = NOW + timedelta(minutes=5)
    with factory.begin() as session:
        ledger = UsageLedger(session)
        ledger.settle(settled, actual_cost_usd=Decimal("0.040"), now=later)  # debt
        ledger.release(released, now=later)
        ledger.expire_stale_jobs(now=later)
        ledger.expire_grants(now=later)
        ledger.claw_back_grant(pack, reason="refund", now=later)
        ledger.forgive_debt(student, units=3, reason="support", now=later)
        ledger.adjust(owner_user_id=student, units=4, reason="fix", idempotency_key="a", now=later)
    return student


def test_a_busy_ledger_reconciles_with_zero_drift(sm: sessionmaker[Session]) -> None:
    student = _busy_ledger(sm)
    assert debts(sm, student)  # the run really did create (and partly repay) debt
    assert reconcile(sm) == []


def test_reconcile_reports_and_repairs_grant_drift(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 20)
    reserve(sm, own_chain(owner), 5)
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE usage_grant_balances SET remaining = remaining + 3, held = held + 1 "
                "WHERE grant_id = :g"
            ),
            {"g": gid},
        )
    assert balance(sm, gid) == (23, 6)
    assert sorted(reconcile(sm)) == sorted([(gid, 23, 20), (gid, 6, 5)])
    assert balance(sm, gid) == (20, 5)
    assert reconcile(sm) == []


def test_reconcile_reports_and_repairs_debt_drift(sm: sessionmaker[Session]) -> None:
    student = _busy_ledger(sm)
    [debt] = debts(sm, student)
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE usage_debts SET outstanding = units WHERE id = :d"), {"d": debt.id}
        )
    assert reconcile(sm) == [(debt.id, debt.units, debt.outstanding)]
    assert debts(sm, student)[0].outstanding == debt.outstanding
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_ledger_reconcile.py -v --no-cov`
Expected: 3 FAILED with `AttributeError: 'UsageLedger' object has no attribute 'reconcile_balances'`.

- [ ] **Step 3: Append to `class UsageLedger` (after `_entry_count`)**

```python
    def reconcile_balances(self) -> list[tuple[uuid.UUID, int, int]]:
        """Rebuild the cache from the entries; return every drift as ``(id, cached, actual)``.

        One tuple per drifted value: a grant's ``remaining``, a grant's
        ``held`` (both keyed by grant id) and a debt's ``outstanding`` (keyed
        by debt id). Each drifted row is re-read under its row lock before it
        is repaired, so a write that committed mid-scan is not reported.
        """
        drift: list[tuple[uuid.UUID, int, int]] = []
        for grant_id, cached_rem, cached_held, actual_rem, actual_held in self._grant_sums():
            if (cached_rem, cached_held) == (actual_rem, actual_held):
                continue
            balance = self._locked_balance(grant_id)
            actual = self._grant_sums(grant_id)
            _gid, _r, _h, actual_rem, actual_held = actual[0]
            if balance.remaining != actual_rem:
                drift.append((grant_id, balance.remaining, actual_rem))
                balance.remaining = actual_rem
            if balance.held != actual_held:
                drift.append((grant_id, balance.held, actual_held))
                balance.held = actual_held
        for debt_id, cached_out, actual_out in self._debt_sums():
            if cached_out == actual_out:
                continue
            debt = self._session.scalars(
                sa.select(UsageDebt)
                .where(UsageDebt.id == debt_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).one()
            _did, _c, actual_out = self._debt_sums(debt_id)[0]
            if debt.outstanding != actual_out:
                drift.append((debt_id, debt.outstanding, actual_out))
                debt.outstanding = actual_out
        self._session.flush()
        return drift

    def _grant_sums(
        self, grant_id: uuid.UUID | None = None
    ) -> list[tuple[uuid.UUID, int, int, int, int]]:
        remaining = sa.func.coalesce(
            sa.func.sum(sa.case((UsageEntry.kind.in_(REMAINING_KINDS), UsageEntry.units), else_=0)),
            0,
        )
        held = sa.func.coalesce(
            sa.func.sum(sa.case((UsageEntry.kind.in_(HELD_KINDS), UsageEntry.units), else_=0)),
            0,
        )
        stmt = (
            sa.select(
                UsageGrantBalance.grant_id,
                UsageGrantBalance.remaining,
                UsageGrantBalance.held,
                remaining,
                held,
            )
            .outerjoin(UsageEntry, UsageEntry.grant_id == UsageGrantBalance.grant_id)
            .group_by(
                UsageGrantBalance.grant_id, UsageGrantBalance.remaining, UsageGrantBalance.held
            )
            .order_by(UsageGrantBalance.grant_id)
        )
        if grant_id is not None:
            stmt = stmt.where(UsageGrantBalance.grant_id == grant_id)
        return [
            (g, int(cr), int(ch), int(ar), int(ah))
            for g, cr, ch, ar, ah in self._session.execute(stmt)
        ]

    def _debt_sums(self, debt_id: uuid.UUID | None = None) -> list[tuple[uuid.UUID, int, int]]:
        repaid = sa.func.coalesce(
            sa.func.sum(
                sa.case((UsageEntry.kind == UsageEntryKind.debt_repay, UsageEntry.units), else_=0)
            ),
            0,
        )
        forgiven = sa.func.coalesce(
            sa.func.sum(
                sa.case(
                    (
                        sa.and_(
                            UsageEntry.kind == UsageEntryKind.adjust, UsageEntry.grant_id.is_(None)
                        ),
                        UsageEntry.units,
                    ),
                    else_=0,
                )
            ),
            0,
        )
        stmt = (
            sa.select(UsageDebt.id, UsageDebt.outstanding, UsageDebt.units + repaid - forgiven)
            .outerjoin(UsageEntry, UsageEntry.debt_id == UsageDebt.id)
            .group_by(UsageDebt.id, UsageDebt.outstanding, UsageDebt.units)
            .order_by(UsageDebt.id)
        )
        if debt_id is not None:
            stmt = stmt.where(UsageDebt.id == debt_id)
        return [(d, int(c), int(a)) for d, c, a in self._session.execute(stmt)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_ledger_reconcile.py -v --no-cov`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/usage_ledger_repo.py tests/test_usage_ledger_reconcile.py
git commit -S -m "feat(usage): rebuild the balance cache and report drift" -- lemely/db/usage_ledger_repo.py tests/test_usage_ledger_reconcile.py
```

---

### Task 9: Concurrency proofs

**Files:**
- Test: `tests/test_usage_ledger_concurrency.py`

**Interfaces:**
- Consumes: `tests/_concurrency.py` (`_Paused`, `_wait_until_a_backend_waits_on_a_lock`), the full `UsageLedger`.
- Produces: no code. Evidence that the owner advisory locks and the `FOR UPDATE` row locks
  prevent over-commit, enforce a shared cap, close a job once, and cannot deadlock.

These tests pass against the Tasks 4–8 code; the point of this task is to prove they would go
red without the locks (Step 3).

- [ ] **Step 1: Write the tests**

Create `tests/test_usage_ledger_concurrency.py`:

```python
"""Races on the usage ledger (spec §5.7 step 3, §9 "Concurrent jobs on one balance").

* **Two jobs, one balance.** A reservation held open makes a second reservation
  on the same owner queue behind it; once the first commits, the second sees the
  held units and is refused. Deterministic: the second transaction is proven to
  be waiting on a lock before the first commits.
* **Many jobs, one balance.** N reservations started together from a barrier:
  exactly as many succeed as the balance covers, and ``held`` equals their sum.
* **Shared cap.** Two jobs under one assistant's cap, against a teacher with
  plenty of credits: the cap admits only one.
* **Settle against the expiry sweeper.** Exactly one of them closes the job and
  the ledger reconciles.
* **Opposite chain orders.** Jobs whose chains name two owners in opposite
  orders run together without a deadlock.
"""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageJobStatus
from lemely.db.usage_ledger_repo import InsufficientBalance, UsageLedger
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.usage_db import (
    ACTION,
    ESTIMATOR_VERSION,
    NOW,
    RATE_VERSION,
    add_rate,
    add_user,
    balance,
    emptied_after,
    grant,
    job,
    own_chain,
    reserve,
    usage_database,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker

WORKERS = 6


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


def _reserve_in(session: Session, payers: list[Payer], high: int) -> uuid.UUID:
    job_id = uuid.uuid4()
    UsageLedger(session).reserve(
        job_id=job_id,
        actor_user_id=payers[0].owner_user_id,
        action=ACTION,
        payers=payers,
        estimate_low=0,
        estimate_high=high,
        estimator_version=ESTIMATOR_VERSION,
        rate_version=RATE_VERSION,
        teacher_member_id=payers[0].teacher_member_id,
        expires_at=NOW + timedelta(minutes=15),
        now=NOW,
    )
    return job_id


def _run_together(
    factory: sessionmaker[Session], calls: list[Callable[[Session], object]]
) -> list[object]:
    """Start every call from one barrier, each in its own transaction; return results or errors."""
    barrier = threading.Barrier(len(calls))
    results: list[object] = [None] * len(calls)

    def run(index: int) -> None:
        barrier.wait()
        try:
            with factory.begin() as session:
                results[index] = calls[index](session)
        except Exception as exc:  # collected and asserted on by the test
            results[index] = exc

    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "worker thread hung"
    return results


def test_a_second_reservation_waits_for_the_first_and_is_refused(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10)
    holder = sm()
    try:
        holder.begin()
        _reserve_in(holder, own_chain(owner), 8)
        second = _Paused(lambda: reserve(sm, own_chain(owner), 8))
        _wait_until_a_backend_waits_on_a_lock(sm)
        holder.commit()
    finally:
        holder.close()
    second.join()
    assert isinstance(second.error, InsufficientBalance)
    assert balance(sm, gid) == (10, 8)


def test_concurrent_reservations_never_overcommit_a_balance(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10)
    results = _run_together(
        sm, [lambda s: _reserve_in(s, own_chain(owner), 4) for _ in range(WORKERS)]
    )
    won = [r for r in results if isinstance(r, uuid.UUID)]
    refused = [r for r in results if isinstance(r, InsufficientBalance)]
    assert (len(won), len(refused)) == (2, WORKERS - 2), results
    assert balance(sm, gid) == (10, 8)


def test_concurrent_jobs_under_one_cap_admit_only_what_the_cap_allows(
    sm: sessionmaker[Session],
) -> None:
    teacher, member = add_user(sm, Role.teacher), uuid.uuid4()
    credits = grant(sm, teacher, 1000, kind=GrantKind.credit_pack, visible=True)
    chain = [
        Payer(
            owner_user_id=teacher,
            scope=GrantScope.CREDITS,
            teacher_member_id=member,
            cap_units=10,
        )
    ]
    results = _run_together(sm, [lambda s: _reserve_in(s, chain, 6) for _ in range(WORKERS)])
    assert sum(isinstance(r, uuid.UUID) for r in results) == 1, results
    assert balance(sm, credits) == (1000, 6)


def test_settle_racing_the_expiry_sweeper_closes_the_job_once(sm: sessionmaker[Session]) -> None:
    add_rate(sm)
    owner = add_user(sm)
    gid = grant(sm, owner, 20)
    job_id = reserve(sm, own_chain(owner), 10, expires_at=NOW + timedelta(seconds=1))
    later = NOW + timedelta(minutes=1)
    results = _run_together(
        sm,
        [
            lambda s: UsageLedger(s).settle(job_id, actual_cost_usd=Decimal("0.007"), now=later),
            lambda s: UsageLedger(s).expire_stale_jobs(now=later),
        ],
    )
    assert not [r for r in results if isinstance(r, Exception)], results
    status = job(sm, job_id).status
    assert status in {UsageJobStatus.settled, UsageJobStatus.expired}
    assert balance(sm, gid) == ((13, 0) if status is UsageJobStatus.settled else (20, 0))
    with sm.begin() as session:
        assert UsageLedger(session).reconcile_balances() == []


def test_opposite_chain_orders_do_not_deadlock(sm: sessionmaker[Session]) -> None:
    a, b = add_user(sm), add_user(sm)
    grant(sm, a, 100, kind=GrantKind.credit_pack, visible=True)
    grant(sm, b, 100, kind=GrantKind.credit_pack, visible=True)
    a_first = [own_chain(a)[1], own_chain(b)[1]]
    b_first = [own_chain(b)[1], own_chain(a)[1]]
    calls: list[Callable[[Session], object]] = []
    for _ in range(WORKERS // 2):
        calls.append(lambda s: _reserve_in(s, a_first, 30))
        calls.append(lambda s: _reserve_in(s, b_first, 30))
    results = _run_together(sm, calls)
    assert all(isinstance(r, uuid.UUID | InsufficientBalance) for r in results), results
    with sm.begin() as session:
        assert UsageLedger(session).reconcile_balances() == []
```

- [ ] **Step 2: Run them (three times, to catch flakiness)**

Run: `for i in 1 2 3; do PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_ledger_concurrency.py -v --no-cov; done`
Expected: `5 passed` each time.

- [ ] **Step 3: Prove the tests go red without the locks, then restore**

(a) In `lemely/db/usage_ledger_repo.py`, make `_lock_owners` return immediately (insert `return`
as its first statement) and change `if lock:` in `_slots` to `if False:`. Run the file once.
Expected: 4 FAILED — `test_a_second_reservation_waits_for_the_first_and_is_refused`
("the second transaction never queued behind the first"),
`test_concurrent_reservations_never_overcommit_a_balance`,
`test_concurrent_jobs_under_one_cap_admit_only_what_the_cap_allows`,
`test_opposite_chain_orders_do_not_deadlock`. Restore with
`git checkout -- lemely/db/usage_ledger_repo.py`.

(b) In `_lock_owners`, replace `sorted(set(owner_ids))` with `dict.fromkeys(owner_ids)` (chain
order, as the spec words it). Run
`PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_ledger_concurrency.py -k opposite -v --no-cov`.
Expected: FAILED with `psycopg.errors.DeadlockDetected` (contract deviation 4). Restore with
`git checkout -- lemely/db/usage_ledger_repo.py` and confirm `git status --short` shows only the
new test file.

- [ ] **Step 4: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add tests/test_usage_ledger_concurrency.py
git commit -S -m "test(usage): concurrency proofs for reservations, caps and lock order" -- tests/test_usage_ledger_concurrency.py
```

---

### Phase close-out

- [ ] Run every test file this phase touched, plus the repo lint tests, on the final tree:

```bash
PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest \
  tests/test_usage_pricing.py tests/test_usage_models.py tests/test_migration_usage_ledger.py \
  tests/test_usage_ledger_grants.py tests/test_usage_ledger_reserve.py \
  tests/test_usage_ledger_settle.py tests/test_usage_ledger_admin.py \
  tests/test_usage_ledger_reconcile.py tests/test_usage_ledger_concurrency.py \
  tests/test_db_schema.py tests/test_migration_tutor_evidence_uploads.py tests/architecture/ \
  -v --no-cov
```

Expected: all PASS, none SKIPPED for an unreachable Postgres.

- [ ] Run `/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files` once more; expected all
  hooks `Passed` (mypy and pyright check all of `lemely`, including the migration).
- [ ] Scan the diff for placeholders:
  `git diff origin/develop... -- lemely tests | grep -nE "TODO|FIXME|pytest.skip|\.only\(|^\+\s+pass$"`
  Expected: no output.
