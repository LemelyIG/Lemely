# Sign-Up Flows for Students & Teachers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Issue:** [#10](https://github.com/LemelyIG/Lemely/issues/10) — sub-issues [#11](https://github.com/LemelyIG/Lemely/issues/11) (student) and [#12](https://github.com/LemelyIG/Lemely/issues/12) (teacher). All three were filed title-only; the specification is the design doc below.

**Spec:** `docs/superpowers/specs/2026-08-25-signup-flows-design.md` — **read it before Task 1.** The twelve interview decisions (D7.1–D7.12) it records are binding on this plan, and several tasks below only make sense against the findings in its §1.

**Goal:** Ship the five specified public account screens (G-02, G-03, G-06, G-07, G-08), extend self-service signup to teachers, close the account-graph hole that makes teacher accounts unreachable in production, and route both new roles into a first run that leaves them somewhere useful.

**Architecture:** Three additive migrations (`0021`–`0023`) add account-lifecycle timestamps, a hashed single-use `auth_tokens` table, and redeemable `invites`. An `EmailProvider` seam mirrors `SmsProvider` exactly, with an offline mock. `AuthService` grows verification and password-reset flows and admits `teacher` to self-service signup. A new invites service and a platform-admin schools service make seats, class codes and school creation reachable. On the frontend, nine public routes join the four that exist today, and each portal layout gains a first-run gate.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), React 19 + TypeScript + Vite + Tailwind v4 (frontend), pytest, vitest, Playwright.

## Plan fidelity — read this before judging the shape

Tasks 1–12 (backend) are written at full house fidelity: real code, real test bodies, real assertions. That is where the irreversible decisions live — schema, token handling, role admission, anti-enumeration — and where a wrong guess is expensive.

Tasks 13–23 (frontend, docs) are written as **precise task specifications**: exact files, exact interfaces, exact test names, exact acceptance criteria and copy rules — but not line-by-line JSX. This is deliberate, not an omission. Those screens must be built against `DESIGN.md` and the existing component kit by someone reading both, and a plan that dictated their markup would be pre-empting the design pass while being no more likely to produce a screen that matches the Study Notebook identity. Every constraint that *is* binding on them is stated.

## Global Constraints

- **Signed commits: `git commit -S`.** Conventional messages with scopes (`feat(auth):`, `feat(db):`, `feat(web):`, `test(auth):`, `docs(plans):`).
- **Run `pre-commit run --all-files` and fix every failure before each commit.** Not once at the end.
- **Additive-only schema (D1.2).** No column is dropped, no column becomes NOT NULL, no existing enum loses a member. Enum `server_default`s render with an explicit `::type` cast (D1.3).
- **Alembic revision ids are ≤32 characters** — `alembic_version.version_num` is `varchar(32)`. The three below are 22, 16 and 12.
- **Postgres-dependent tests skip cleanly** via the existing `pg_engine` / `pg_sessionmaker` fixture pattern (`pytest.skip("local Postgres not reachable")`). Never invent a new fixture shape.
- **No user-facing string is a server `detail`.** Every failure message on a new screen resolves through the `lib/*Outcome.ts` family. `authOutcome.ts` is **extended**, never duplicated. Rendering `error.message` is a defect, not a shortcut — see the spec §4.6 for why this rule is stated so bluntly.
- **Anti-enumeration is binding.** `password-reset/request` answers 200 for an address that does not exist. The signup conflict never confirms that an address is held. Neither behaviour may be "helpfully" relaxed.
- **Tokens are stored hashed.** A `SELECT *` on `auth_tokens` must not yield anything a caller could redeem.
- **Never claim a mail was sent.** `EmailProvider.delivers_out_of_band` is the only thing permitted to decide what a screen says about delivery (D3.16's rule for `devCode`, applied to `devLink`).
- **Logical CSS properties only** in new styles (`margin-inline-start`, `padding-inline`, `text-align: start`) — PRODUCT.md's deferred-not-hardcoded RTL rule.
- **`users.is_active` stays dead.** Do not repurpose it for verification; do not drop it. Task 23 documents it.

---

## Task 1: Migration `0021` — account lifecycle timestamps

Adds the two nullable timestamps D7.4 and D7.11 call for. Smallest possible first step, and everything downstream depends on `email_verified_at` existing.

**Files:**
- Create: `lemely/db/migrations/versions/0021_account_lifecycle.py`
- Modify: `lemely/db/models/users.py` (`User` — two columns)
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces `User.email_verified_at: datetime | None` — consumed by Tasks 8, 10.
- Produces `User.terms_accepted_at: datetime | None` — consumed by Task 8.

- [ ] **Step 1: Write the failing schema test**

Add to `tests/test_db_schema.py`, beside the other `User` tests:

```python
def test_user_account_lifecycle_timestamps_are_nullable(pg_engine: sa.Engine) -> None:
    """D7.4/D7.11: both timestamps default NULL and round-trip when set."""
    from lemely.db.models import User
    from lemely.db.models.enums import Role

    with Session(pg_engine) as session:
        user = User(id=uuid.uuid4(), email="lifecycle@example.com", role=Role.student)
        session.add(user)
        session.commit()
        session.refresh(user)
        assert user.email_verified_at is None
        assert user.terms_accepted_at is None

        now = datetime.now(UTC)
        user.email_verified_at = now
        user.terms_accepted_at = now
        session.commit()
        session.refresh(user)
        assert user.email_verified_at is not None
        assert user.terms_accepted_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

`pytest tests/test_db_schema.py::test_user_account_lifecycle_timestamps_are_nullable -v`

Expected: FAIL with `AttributeError: 'User' object has no attribute 'email_verified_at'` (`pg_engine` builds from `Base.metadata`, so the model change alone drives it), or SKIP with no local Postgres — if it skips, continue and rely on Step 5, then return here once Postgres is available.

- [ ] **Step 3: Add the columns to the ORM model**

In `lemely/db/models/users.py`, inside `User`, after `is_active`:

```python
    email_verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """Migration ``0021`` (D7.4). Set when the account redeems an
    ``email_verification`` token. Verification state lives **here**, not in
    GoTrue: ``admin_create_user`` keeps ``email_confirm: True`` so the password
    grant always succeeds, because UI spec §G-07 requires "a way to continue
    into a limited preview of the app rather than a hard wall" and GoTrue-native
    confirmation *is* that wall. NULL gates exactly one route —
    ``POST /api/student/correct``, the Gemini spend (D7.5) — and nothing else.

    Note this is unrelated to ``is_active``, which is dead: it is written
    nowhere and read nowhere, and activation in this product is a
    *subscription* concept (``/api/admin/activations/*``), not a user one."""

    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """Migration ``0021`` (D7.11). Set at signup when the G-03 consent box is
    ticked. The consent is to ``/data`` — the data-handling page that actually
    exists — not to a terms-of-service document, because this repository has
    none and PRODUCT.md forbids fabricating one. Nullable because every account
    created before this migration (and every parent, who signs up through no
    form at all) has no such timestamp and inventing one would be a lie about a
    consent nobody gave."""
```

- [ ] **Step 4: Write the migration**

`lemely/db/migrations/versions/0021_account_lifecycle.py`:

```python
"""account lifecycle timestamps on users (issue #10, D7.4 + D7.11)

Revision ID: 0021_account_lifecycle
Revises: 0020_enrolment_qual_level
Create Date: 2026-08-25 00:00:00.000000

Additive: two nullable timestamps on ``users``. No backfill and no default —
an existing account has neither verified an email through a flow that did not
exist nor accepted a consent it was never shown, and stamping "now" on either
would manufacture a fact. NULL is the honest value and both readers treat it
as such: ``email_verified_at IS NULL`` gates one route (D7.5), and
``terms_accepted_at`` is recorded for audit rather than enforced retroactively.

Reversible: ``downgrade`` drops both columns. No enum type is created here, so
there is none to drop (contrast ``0022``/``0023``).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0021_account_lifecycle"
down_revision: str | Sequence[str] | None = "0020_enrolment_qual_level"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "email_verified_at")
```

- [ ] **Step 5: Run test to verify it passes**

`pytest tests/test_db_schema.py::test_user_account_lifecycle_timestamps_are_nullable -v` → PASS.

- [ ] **Step 6: Verify the migration against a real Postgres**

```
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

Both directions must be clean. A migration that only goes one way is not done.

- [ ] **Step 7: Run pre-commit and the full schema file**

```
pre-commit run --all-files
pytest tests/test_db_schema.py -q
```

- [ ] **Step 8: Commit**

```
git commit -S -m "feat(db): add email_verified_at and terms_accepted_at to users

Migration 0021. Verification state lives in public.users rather than GoTrue
so the password grant always succeeds (D7.4) - UI spec G-07 requires a soft
gate, and GoTrue-native confirmation is a hard wall. terms_accepted_at
records consent to /data, the page that exists (D7.11).

Both nullable with no backfill: an existing account has neither verified
through a flow that did not exist nor accepted a consent it was never shown."
```

---

## Task 2: Migration `0022` — the `auth_tokens` table

One table serves both verification and reset (D7.7). Tokens are stored as a SHA-256 hash; the plaintext exists only in the emitted link.

**Files:**
- Create: `lemely/db/migrations/versions/0022_auth_tokens.py`
- Create: `lemely/db/models/auth_tokens.py`
- Modify: `lemely/db/models/enums.py` (`AuthTokenPurpose`), `lemely/db/models/__init__.py`
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces `AuthToken` ORM model + `AuthTokenPurpose` enum — consumed by Task 5.

- [ ] **Step 1: Add the enum**

In `lemely/db/models/enums.py`, beside the other domain enums:

```python
class AuthTokenPurpose(str, enum.Enum):
    """What a row in ``auth_tokens`` entitles its holder to do (D7.7).

    Two purposes, one table: the lifecycle is identical (mint, single-use,
    expire, revoke-all-on-password-change), so a second table would duplicate
    a repository rather than express a distinction. The purpose is part of the
    redemption predicate, never inferred — a verification token presented to
    the reset route must not be accepted, and matching on ``purpose`` in the
    lookup is what makes that structural rather than careful.
    """

    email_verification = "email_verification"
    password_reset = "password_reset"
```

- [ ] **Step 2: Write the failing schema test**

```python
def test_auth_token_round_trips_and_enforces_unique_hash(pg_engine: sa.Engine) -> None:
    """D7.7: a token row stores a hash, expires, and is single-use."""
    from lemely.db.models import AuthToken, User
    from lemely.db.models.enums import AuthTokenPurpose, Role

    with Session(pg_engine) as session:
        user = User(id=uuid.uuid4(), email="tokens@example.com", role=Role.student)
        session.add(user)
        session.flush()

        token = AuthToken(
            user_id=user.id,
            purpose=AuthTokenPurpose.password_reset,
            token_hash="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(token)
        session.commit()
        session.refresh(token)
        assert token.used_at is None
        assert token.purpose is AuthTokenPurpose.password_reset

        token.used_at = datetime.now(UTC)
        session.commit()
        session.refresh(token)
        assert token.used_at is not None

    with Session(pg_engine) as session:
        duplicate = AuthToken(
            user_id=user.id,
            purpose=AuthTokenPurpose.email_verification,
            token_hash="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(duplicate)
        with pytest.raises(sa.exc.IntegrityError):
            session.commit()
```

- [ ] **Step 3: Run test to verify it fails**

`pytest tests/test_db_schema.py::test_auth_token_round_trips_and_enforces_unique_hash -v` → FAIL (`ImportError: cannot import name 'AuthToken'`), or SKIP without Postgres.

- [ ] **Step 4: Write the ORM model**

`lemely/db/models/auth_tokens.py`:

```python
"""ORM model for single-use email-verification and password-reset tokens."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import AuthTokenPurpose, TimestampMixin


class AuthToken(TimestampMixin, Base):
    """A single-use credential emitted into an email link (D7.7).

    **The row never holds the credential.** ``token_hash`` is the SHA-256 of
    the token that went into the link; the plaintext exists in the email and
    in the requester's browser and nowhere else. A database read — a backup, a
    log, a support query, a leak — therefore yields nothing redeemable. This is
    the one property that makes storing these in Postgres safer than the
    in-memory ``OtpStore`` they otherwise resemble, rather than merely more
    durable.

    **Durability is the reason they are not in memory.** ``OtpStore`` is a
    plain dict: challenges die on restart and do not exist across workers.
    That is tolerable for a code a parent types within sixty seconds and not
    for a reset link someone opens from their inbox an hour and one deploy
    later.

    Single-use is ``used_at``, not deletion: a redeemed row is evidence, and a
    second presentation of the same token should be distinguishable from a
    token that was never minted. Expiry is absolute (``expires_at``), so a
    clock comparison is the whole validity check and there is no sliding
    window to reason about.
    """

    __tablename__ = "auth_tokens"
    __table_args__ = (
        sa.Index("ix_auth_tokens_token_hash", "token_hash", unique=True),
        sa.Index("ix_auth_tokens_user_id_purpose", "user_id", "purpose"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[AuthTokenPurpose] = mapped_column(
        sa.Enum(AuthTokenPurpose, name="authtokenpurpose"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    """SHA-256 hex digest of the emitted token. Unique so a redemption lookup
    is a single indexed read and a hash collision is a rejected insert."""
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


__all__ = ["AuthToken"]
```

Export `AuthToken` from `lemely/db/models/__init__.py` alongside the others.

- [ ] **Step 5: Write the migration**

`0022_auth_tokens.py`, revision `0022_auth_tokens`, down_revision `0021_account_lifecycle`. Let `op.create_table` create the `authtokenpurpose` type implicitly (the pattern `0015_friendships` follows), and drop it explicitly in `downgrade` **after** the table — a table drop does not drop the Postgres type backing an enum column, the trap `0006_at_risk_acknowledgements` documents:

```python
def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("auth_tokens")
    sa.Enum(name="authtokenpurpose").drop(op.get_bind(), checkfirst=False)
```

- [ ] **Step 6: Run test to verify it passes**, then `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.

- [ ] **Step 7: Run pre-commit and `pytest tests/test_db_schema.py -q`.**

- [ ] **Step 8: Commit**

```
git commit -S -m "feat(db): add auth_tokens for verification and password reset

Migration 0022. One table with a purpose enum rather than two near-identical
tables: mint, single-use, expire and revoke-on-password-change are the same
lifecycle, so a second table would duplicate a repository (D7.7).

Tokens are stored as a SHA-256 hash - the plaintext lives in the email link
and nowhere else, so a database read yields nothing redeemable. Durable
rather than in-memory like OtpStore, because a reset link is opened an hour
and one deploy after it is minted."
```

---

## Task 3: Migration `0023` — redeemable `invites`

D7.3 keeps the direct-create endpoints and adds codes alongside them. The `CHECK` makes an invite-to-nothing a rejected insert rather than a case the redemption path has to defend against.

**Files:**
- Create: `lemely/db/migrations/versions/0023_invites.py`, `lemely/db/models/invites.py`
- Modify: `lemely/db/models/enums.py` (`InviteRole`), `lemely/db/models/__init__.py`
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces `Invite` + `InviteRole` — consumed by Task 11.

- [ ] **Step 1: Add `InviteRole` to `enums.py`**

```python
class InviteRole(str, enum.Enum):
    """The role an invite code provisions (D7.3).

    Deliberately **not** :class:`Role`. An invite may only ever produce a
    student or a teacher; reusing the five-member ``Role`` here would put
    ``platform_admin`` in the type system of a code an anonymous caller
    redeems, and the only thing standing between that and an escalation would
    be a validation nobody had written yet. A narrower type cannot express the
    mistake.
    """

    student = "student"
    teacher = "teacher"
```

- [ ] **Step 2: Write the failing schema test**

Assert three things: a school-scoped invite round-trips; a class-scoped invite round-trips; and an invite with **both** `school_id` and `class_id` NULL raises `IntegrityError` on the `ck_invites_target` constraint.

```python
def test_invite_requires_a_target(pg_engine: sa.Engine) -> None:
    """D7.3: an invite that points at neither a school nor a class is refused."""
    from lemely.db.models import Invite, User
    from lemely.db.models.enums import InviteRole, Role

    with Session(pg_engine) as session:
        admin = User(id=uuid.uuid4(), email="inviter@example.com", role=Role.school_admin)
        session.add(admin)
        session.flush()
        session.add(
            Invite(code="TARGETLESS", role=InviteRole.student, created_by=admin.id)
        )
        with pytest.raises(sa.exc.IntegrityError):
            session.commit()
```

- [ ] **Step 3: Run test to verify it fails.**

- [ ] **Step 4: Write the ORM model**

`lemely/db/models/invites.py` — `Invite` with the columns in spec §4.1. Docstring must carry the two load-bearing notes:

```python
    __table_args__ = (
        sa.CheckConstraint(
            "school_id IS NOT NULL OR class_id IS NOT NULL",
            name="ck_invites_target",
        ),
        sa.Index("ix_invites_code", "code", unique=True),
    )
```

> An invite to nothing is not an invite. Both target columns are nullable
> because an invite is to a school **or** a class, never necessarily both —
> and `ck_invites_target` is what stops "either" degrading into "neither".
> This is the `friendships` rule again: idempotency and validity are enforced
> by the database, not by care.

> `redeemed_by`/`redeemed_at` mark consumption rather than deleting the row,
> for the same reason `AuthToken.used_at` does: a school admin asking "did
> that code ever get used, and by whom" is a question the schema should be
> able to answer.

- [ ] **Step 5: Write the migration** `0023_invites.py` (revision `0023_invites`, down_revision `0022_auth_tokens`), same implicit-create / explicit-drop enum handling as Task 2.

- [ ] **Step 6: Run test to verify it passes**, then round-trip alembic both directions.

- [ ] **Step 7: pre-commit + `pytest tests/test_db_schema.py -q`.**

- [ ] **Step 8: Commit**

```
git commit -S -m "feat(db): add redeemable invites table

Migration 0023. Codes coexist with the existing direct-create endpoints
rather than replacing them (D7.3): direct-create suits bulk provisioning
from a roster, codes are what UI spec G-08 describes.

ck_invites_target makes an invite pointing at neither a school nor a class
a rejected insert rather than a case the redemption path defends against.
InviteRole is narrower than Role on purpose - platform_admin must not be
expressible in a code an anonymous caller redeems."
```

---

## Task 4: The `EmailProvider` seam

Modelled line-for-line on `lemely/auth/sms.py` (D7.6). The `delivers_out_of_band` flag is the whole point: it is what makes returning a live link through the API defensible in dev and impossible in production, under exactly D3.16's reasoning.

**Files:**
- Create: `lemely/auth/email.py`
- Test: `tests/test_auth_email.py`

**Interfaces:**
- Produces `EmailProvider` (Protocol) and `MockEmailProvider` — consumed by Tasks 8, 9 and `deps.py`.

- [ ] **Step 1: Write the failing test**

`tests/test_auth_email.py`:

```python
"""MockEmailProvider behaviour and the delivers_out_of_band contract."""

import logging

from lemely.auth.email import MockEmailProvider


def test_mock_provider_does_not_deliver_out_of_band() -> None:
    """The mock is the sole condition under which the API may surface a link."""
    assert MockEmailProvider().delivers_out_of_band is False


def test_mock_provider_logs_the_verification_link(caplog) -> None:
    provider = MockEmailProvider()
    with caplog.at_level(logging.INFO, logger="lemely.auth.email"):
        provider.send_verification("student@example.com", "https://app/verify-email/abc")
    assert "student@example.com" in caplog.text
    assert "https://app/verify-email/abc" in caplog.text


def test_mock_provider_logs_the_reset_link(caplog) -> None:
    provider = MockEmailProvider()
    with caplog.at_level(logging.INFO, logger="lemely.auth.email"):
        provider.send_password_reset("student@example.com", "https://app/reset/xyz")
    assert "https://app/reset/xyz" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails** — `ModuleNotFoundError: lemely.auth.email`.

- [ ] **Step 3: Implement `lemely/auth/email.py`**

```python
"""Email delivery seam for verification and password-reset links.

``EmailProvider`` is the single switch point between the offline mock used in
dev/tests and a real transactional-email service added later — swapping the
implementation injected into :class:`~lemely.auth.service.AuthService` is the
only change required. This is deliberately the same shape as
:mod:`lemely.auth.sms`, because that module already solved this problem and
already reasoned through the dangerous part.

Each provider declares :attr:`EmailProvider.delivers_out_of_band`: whether it
actually gets the link to the recipient's inbox by a channel outside this API.
That flag — **not** an environment string — is what gates whether the auth
routes may hand the link back for §G-06/§G-07's developer affordance, exactly
as D3.16 gates the OTP's ``devCode``. A provider that does deliver never leaks
a live link through the API; a provider that does not deliver is the only
situation in which the API is the sole way to obtain it.

**The honesty rule that follows from it.** ``deps.py`` wires
:class:`MockEmailProvider` unconditionally, so no deployment of this code as
written sends a mail. No screen and no page description may therefore say a
mail *was sent* — they read the flag and say what is true. ``routes.tsx``
records the same problem for the parent OTP screen, which does make that claim;
this seam ships without repeating it.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("lemely.auth.email")


class EmailProvider(Protocol):
    """Delivers an account-lifecycle link to an email address."""

    delivers_out_of_band: bool
    """True when the link actually reaches the inbox by a channel outside this
    API (a real mail service). False means the API is the only way to obtain
    it, which is the sole condition under which a route may return it. Any real
    provider added later **must** set this True."""

    def send_verification(self, email: str, link: str) -> None:
        """Deliver an email-verification ``link`` to ``email``. Raises on failure."""
        ...

    def send_password_reset(self, email: str, link: str) -> None:
        """Deliver a password-reset ``link`` to ``email``. Raises on failure."""
        ...


class MockEmailProvider:
    """Offline :class:`EmailProvider` that logs the link instead of sending it.

    Intended for local dev and tests: the link is written to the
    ``lemely.auth.email`` logger at ``INFO`` so a developer can copy it from the
    console. Because nothing reaches an inbox, :attr:`delivers_out_of_band` is
    False and the auth routes may surface the link for the §G-06/§G-07 developer
    affordance.
    """

    delivers_out_of_band = False

    def send_verification(self, email: str, link: str) -> None:
        """Log the verification link for ``email`` at INFO level."""
        logger.info("Mock email to %s: verify your Lemely account at %s", email, link)

    def send_password_reset(self, email: str, link: str) -> None:
        """Log the reset link for ``email`` at INFO level."""
        logger.info("Mock email to %s: reset your Lemely password at %s", email, link)


__all__ = ["EmailProvider", "MockEmailProvider"]
```

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: pre-commit, then commit**

```
git commit -S -m "feat(auth): add EmailProvider seam with an offline mock

Mirrors lemely/auth/sms.py deliberately (D7.6): that module already solved
this and already reasoned through when returning a live credential through
the API is safe (D3.16). delivers_out_of_band gates the dev affordance and
any real provider must set it True.

Because deps.py wires the mock unconditionally, no screen may claim a mail
was sent - they read the flag. The module docstring records that rule."
```

---

## Task 5: `AuthTokenService` — mint, redeem, revoke

The security core of this issue. Read every docstring below before implementing; the failure modes are not obvious from the signatures.

**Files:**
- Create: `lemely/db/auth_token_repo.py`
- Test: `tests/test_auth_token_repo.py`

**Interfaces:**
- Produces `AuthTokenService.mint(user_id, purpose) -> str` (returns **plaintext**, stores the hash), `.redeem(token, purpose) -> uuid.UUID`, `.revoke_all(user_id, purpose)`.
- Raises `AuthTokenError` subclasses: `TokenNotFound`, `TokenExpired`, `TokenAlreadyUsed`.
- Consumed by Task 8.

- [ ] **Step 1: Write the failing tests**

`tests/test_auth_token_repo.py` — cover all seven behaviours. These are the assertions that matter:

```python
def test_mint_returns_plaintext_and_stores_only_a_hash(pg_sessionmaker) -> None:
    """The stored row must not contain anything redeemable."""
    service = AuthTokenService(pg_sessionmaker, ttl_seconds=3600)
    token = service.mint(user_id, AuthTokenPurpose.password_reset)
    with pg_sessionmaker() as session:
        row = session.scalars(select(AuthToken)).one()
    assert row.token_hash != token
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()


def test_redeem_returns_the_user_and_marks_the_token_used(pg_sessionmaker) -> None: ...


def test_redeem_twice_raises_token_already_used(pg_sessionmaker) -> None:
    """Single-use is enforced on the row, not by deleting it."""


def test_redeem_after_expiry_raises_token_expired(pg_sessionmaker) -> None: ...


def test_redeem_with_the_wrong_purpose_raises_token_not_found(pg_sessionmaker) -> None:
    """A verification token presented to the reset route is not a reset token.

    This is the test that matters most in the file: purpose is part of the
    lookup predicate, so cross-purpose redemption is structurally impossible
    rather than checked. Assert it against a *live, unexpired, unused* token
    so the failure can only come from the purpose mismatch.
    """


def test_redeem_with_an_unknown_token_raises_token_not_found(pg_sessionmaker) -> None: ...


def test_revoke_all_marks_every_live_token_for_that_purpose_used(pg_sessionmaker) -> None:
    """Called on password change: every outstanding reset link dies at once."""
```

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `lemely/db/auth_token_repo.py`**

Binding implementation rules:

1. **`mint` returns the plaintext and never stores it.** Generate with `secrets.token_urlsafe(32)`; store `hashlib.sha256(token.encode()).hexdigest()`.
2. **`redeem` matches on `(token_hash, purpose)` in the `WHERE` clause**, not by fetching on hash and then comparing purpose in Python. A cross-purpose token must be indistinguishable from an unknown one — both `TokenNotFound` — so the error cannot be used to probe which tokens exist for which purpose.
3. **`redeem` marks `used_at` in the same transaction that reads the row**, with `SELECT … FOR UPDATE`. Two concurrent redemptions of one link must not both succeed.
4. **Order the checks: found → not used → not expired.** An expired-but-unused token and a used token are different facts and the caller's copy differs.
5. **`revoke_all` is called on password change** for both purposes, and stamps `used_at` rather than deleting.
6. Take a `clock` callable so expiry is testable without sleeping, matching `OtpStore`'s constructor shape.

- [ ] **Step 4: Run tests to verify they pass.**

- [ ] **Step 5: pre-commit, then commit**

```
git commit -S -m "feat(db): add AuthTokenService for verification and reset tokens

mint returns plaintext and stores only a SHA-256 hash, so a database read
yields nothing redeemable. redeem matches on (token_hash, purpose) in the
WHERE clause rather than fetching by hash and comparing purpose after, which
makes cross-purpose redemption structurally impossible and stops the error
distinguishing an unknown token from a wrong-purpose one.

SELECT FOR UPDATE so two concurrent redemptions of one link cannot both
succeed. revoke_all stamps used_at rather than deleting - a redeemed row is
evidence."
```

---

## Task 6: A reusable cooldown store

D7.12 reuses D1.7's mechanism. `OtpStore` already implements exactly this and couples it to phone challenges; extract the reusable part rather than writing a third copy.

**Files:**
- Create: `lemely/auth/cooldown.py`
- Test: `tests/test_auth_cooldown.py`

**Interfaces:**
- Produces `CooldownStore(clock, min_seconds).check_and_stamp(key) -> None`, raising `CooldownError` with the seconds remaining.
- Consumed by Task 9 (mapped to **429**, matching the OTP route).

- [ ] **Step 1: Write the failing tests** — first call passes; an immediate second call raises with `retry_after > 0`; a call after the window passes; distinct keys do not interfere.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** Keep it in-process and dict-backed, matching `OtpStore` — and **say so in the docstring**, including the consequence: the cooldown resets on restart and is per-worker. That is a real limitation and recording it is the difference between a known simplification and a surprise. Do not silently make it look stronger than it is.

- [ ] **Step 4: Run tests to verify they pass.**

- [ ] **Step 5: pre-commit, then commit** (`feat(auth): add a reusable in-process cooldown store`).

---

## Task 7: GoTrue password update

`reset_password` needs a way to actually change the credential. `GoTrueBackend` has no such method.

**Files:**
- Modify: `lemely/auth/gotrue.py` (Protocol + `HttpGoTrueBackend`)
- Modify: the GoTrue fake used by the auth tests (find it via `grep -rn "class Fake.*GoTrue\|admin_create_user" tests/`)
- Test: `tests/test_auth_gotrue.py` (or the existing GoTrue test module)

**Interfaces:**
- Produces `GoTrueBackend.admin_update_user_password(user_id: uuid.UUID, password: str) -> None` — consumed by Task 8.

- [ ] **Step 1: Write the failing test** — the fake records the new password; a subsequent `password_grant` with the old one fails and with the new one succeeds. Assert against the fake, not the network.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement.** `PUT {base}/auth/v1/admin/users/{id}` with the service-role key and `{"password": …}`. Map a non-2xx to `AuthError` and a transport failure to `ExternalServiceError`, exactly as `admin_create_user` does. **Update the fake in the same step** — a Protocol method the fake does not implement makes every hermetic auth test a lie about a service that would fail in production.

- [ ] **Step 4: Run to verify it passes**, plus the whole existing auth test suite (`pytest tests/ -k auth -q`).

- [ ] **Step 5: pre-commit, then commit** (`feat(auth): add admin_update_user_password to the GoTrue seam`).

---

## Task 8: `AuthService` — teacher signup, verification, password reset

The behavioural centre of the issue. Four changes, each independently testable.

**Files:**
- Modify: `lemely/auth/service.py`
- Modify: `lemely/auth/mirror.py` (mirror needs to stamp `terms_accepted_at` and read/write `email_verified_at`)
- Test: `tests/test_auth_service.py`

**Interfaces:**
- Modified: `AuthService.signup(..., accepted_terms: bool)` — now admits `Role.teacher`, stamps `terms_accepted_at`, mints a verification token and sends it.
- Produces `.verify_email(token) -> uuid.UUID`, `.resend_verification(user_id) -> str | None`, `.request_password_reset(email) -> str | None`, `.reset_password(token, new_password) -> None`.
- The three `str | None` returns are the **dev link**, non-`None` only when `not email.delivers_out_of_band` — the `devCode` rule (D3.16), applied identically.

- [ ] **Step 1: Write the failing tests**

The eight that carry the decisions:

```python
def test_signup_admits_a_teacher() -> None:
    """D7.1: teacher is now self-service; the service must not refuse it."""

def test_signup_stamps_terms_accepted_at() -> None:
    """D7.11: consent is recorded, not merely collected."""

def test_signup_mints_and_sends_a_verification_token() -> None:
    """A new account leaves signup with a live verification token."""

def test_signup_returns_the_dev_link_only_when_the_provider_does_not_deliver() -> None:
    """D3.16 applied to email. Assert BOTH directions - a provider with
    delivers_out_of_band=True must yield None, or the rule is decorative."""

def test_verify_email_sets_email_verified_at() -> None: ...

def test_request_password_reset_for_an_unknown_address_does_not_raise() -> None:
    """Anti-enumeration: the caller cannot tell whether the address exists.
    The service returns normally and mints nothing."""

def test_reset_password_revokes_outstanding_tokens_and_all_devices() -> None:
    """The reason for a reset may be a compromise, so every session dies."""

def test_reset_password_with_an_expired_token_raises_auth_error() -> None: ...
```

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement**

Binding rules:

1. **`signup` keeps `admin_create_user(..., email_confirm=True)`.** D7.4: the password grant must always succeed. Do not "improve" this to `False`.
2. **`request_password_reset` never signals whether the address exists.** No raise, no different return shape, and no timing tell worth engineering around — but do not add a branch that returns early in a visibly different way. Mint nothing for an unknown address and return `None`.
3. **`reset_password` calls `revoke_all` for both purposes and revokes every device row** for the user via `DeviceRegistry`. State this in the docstring, because the G-06 success screen has to say it.
4. **The verification token is minted in `signup` but its send failure must not fail the signup.** An account that exists with no mail sent is recoverable (resend); a signup that 500s after `admin_create_user` succeeded leaves an orphaned GoTrue user the caller cannot re-register. Catch, log, continue — and say why in the docstring.
5. **`AuthService.__init__` gains `email: EmailProvider` and `tokens: AuthTokenService`**, both injected, both defaulting to `None` for the hermetic tests that do not exercise them — matching how `device_registry` is already optional.

- [ ] **Step 4: Run tests to verify they pass**, then the whole file: `pytest tests/test_auth_service.py -q`.

- [ ] **Step 5: Run the full backend auth surface** — `pytest tests/ -k "auth or signup or otp" -q`. This task changes a constructor every auth test builds.

- [ ] **Step 6: pre-commit, then commit**

```
git commit -S -m "feat(auth): teacher signup, email verification, password reset

Extends _SELF_SERVICE_SIGNUP_ROLES to teacher (D7.1). D1.7's stated risk was
privilege escalation - anyone POSTing role=platform_admin - and a teacher
escalates nothing: every teacher service is ownership-scoped with no
super-role bypass (D1.6/D1.10), so a self-registered teacher sees only
classes they created and students who chose to type their join code. Both
admin roles remain unobtainable by an anonymous caller.

signup keeps email_confirm=True so the password grant always succeeds;
verification lives in users.email_verified_at instead (D7.4).

A verification send that fails does not fail the signup: an account with no
mail sent is recoverable by resend, while a 500 after admin_create_user
succeeded strands a GoTrue user the caller cannot re-register.

request_password_reset returns identically for an unknown address."
```

---

## Task 9: Auth router — DTOs and the four new routes

**Files:**
- Modify: `lemely/web/schemas_auth.py`, `lemely/web/routers/auth.py`, `lemely/web/deps.py`
- Test: `tests/test_web_auth.py`

**Interfaces:**
- Modified: `SignupRequestDTO` gains `acceptedTerms: bool`; the response gains `devLink: str | None`.
- Produces `POST /api/auth/verify-email`, `/verify-email/resend`, `/password-reset/request`, `/password-reset/confirm`.

- [ ] **Step 1: Write the failing router tests**

```python
def test_signup_as_teacher_returns_a_token(client) -> None:
    """D7.1. The counterpart to test_signup_elevated_role_forbidden."""
    res = client.post("/api/auth/signup", json={
        "email": "t@example.com", "password": "pw", "role": "teacher",
        "acceptedTerms": True,
    })
    assert res.status_code == 200
    assert res.json()["role"] == "teacher"


def test_signup_elevated_role_still_forbidden(client) -> None:
    """D1.7 item 1 survives D7.1. This test must never be deleted.

    Assert both remaining elevated roles explicitly - school_admin and
    platform_admin - so widening the allow-list again cannot pass silently.
    """
    for role in ("school_admin", "platform_admin"):
        res = client.post("/api/auth/signup", json={
            "email": f"{role}@example.com", "password": "pw", "role": role,
            "acceptedTerms": True,
        })
        assert res.status_code == 403


def test_signup_without_accepted_terms_is_rejected(client) -> None:
    """D7.11: consent is required, and required server-side - a client-side
    checkbox that the API does not enforce is decorative."""


def test_signup_within_cooldown_is_429(client) -> None:
    """D7.12, mirroring test_otp_resend_within_cooldown_returns_429."""


def test_password_reset_request_is_200_for_an_unknown_address(client) -> None:
    """Anti-enumeration at the HTTP boundary. A 404 here would be an oracle."""


def test_password_reset_confirm_with_a_bad_token_is_400(client) -> None: ...


def test_verify_email_with_a_bad_token_is_400(client) -> None: ...


def test_resend_verification_requires_a_session(client) -> None:
    """401 unauthenticated: resend names no address, so it must be told who
    the caller is by their token rather than by a body field an attacker
    could fill with someone else's address."""
```

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement the DTOs**

`acceptedTerms: bool` on `SignupRequestDTO` (no default — an absent field must be a 422, not a silent `False`). `devLink: str | None = None` on the responses, documented with the same warning `OtpRequestResponse.devCode` carries: *render it in an explicitly-labelled developer panel, never as ordinary product copy.*

- [ ] **Step 4: Implement the routes**

```python
# Self-service signup may create a student or a teacher. Elevated roles
# (school_admin / platform_admin) are privileged and MUST NOT be obtainable by
# an anonymous caller — otherwise anyone could POST role="platform_admin" and
# mint an admin token (D1.7). Those two are created by an authenticated admin:
# school_admin via the platform-admin schools surface, teacher-in-a-school via
# the seat/invite flow. Parents authenticate via phone-OTP, not signup.
#
# D7.1 added `teacher` and did not weaken D1.7's rule. D1.7's stated risk is
# *escalation*, and a self-registered teacher escalates nothing: every teacher
# service is ownership-scoped by construction with no super-role bypass
# (D1.6/D1.10), so they reach only classes they created and students who chose
# to type their join code.
_SELF_SERVICE_SIGNUP_ROLES = frozenset({Role.student, Role.teacher})
```

Error mapping, consistent with the existing router: `AuthError` → 400 on signup/verify/reset-confirm, 401 on login; `CooldownError` → **429**; `DeviceLimitReachedError` → 409. `/verify-email/resend` takes the caller from `AuthContext`, never from a body field.

- [ ] **Step 5: Wire `deps.py`**

Add `MockEmailProvider()`, an `AuthTokenService` and two `CooldownStore`s to the `get_auth_service` singleton. Mirror the existing comment style — the docstring there enumerates what it is wired with, and it must stay accurate.

- [ ] **Step 6: Run tests to verify they pass**, then `pytest tests/test_web_auth.py -q`.

- [ ] **Step 7: pre-commit, then commit** (`feat(web): add verification and password-reset routes`).

---

## Task 10: Gate marking on verification

D7.5. One route, one guard, one carefully-worded refusal.

**Files:**
- Modify: `lemely/web/routers/student.py` (`POST /student/correct`, line ~874)
- Modify: `lemely/web/deps.py` (a `require_verified_email` dependency)
- Test: `tests/test_web_student.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_correct_is_403_for_an_unverified_account(client) -> None:
    """D7.5: the Gemini spend is the gated operation."""


def test_correct_succeeds_once_verified(client) -> None:
    """The other direction. A guard asserted in one direction only is a guard
    that could be permanently closed and still pass."""


def test_upload_is_not_gated_by_verification(client) -> None:
    """Deliberate: a student who has already photographed a paper must not
    lose the capture to a verification wall. D7.5 gates marking, not upload."""
```

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement** a `require_verified_email` dependency in `deps.py` that reads `users.email_verified_at` and raises 403 with a **stable machine-readable marker** the frontend can branch on (the existing `authOutcome` family maps server outcomes to copy; give it something to match that is not prose, e.g. `detail={"code": "email_unverified"}`). Apply it to `/student/correct` only.

- [ ] **Step 4: Run tests to verify they pass**, plus `pytest tests/test_web_student.py -q`.

- [ ] **Step 5: pre-commit, then commit** (`feat(web): require a verified email to submit a paper for marking`).

---

## Task 11: Invites — service, preview, redemption

Closes spec §1.2: two working endpoints that no user can reach.

**Files:**
- Create: `lemely/db/invite_repo.py`, `lemely/web/routers/invites.py`, `lemely/web/schemas_invites.py`
- Modify: `lemely/web/routers/school.py` (mint a seat invite code), `lemely/web/routers/classes.py` (mint a class invite code), `lemely/web/routers/__init__.py`
- Test: `tests/test_invite_repo.py`, `tests/test_web_invites.py`

**Interfaces:**
- `InviteService.mint_seat_invite(admin_id, school_id) -> Invite` (reserves a seat; 409 at quota)
- `InviteService.mint_class_invite(teacher_id, class_id) -> Invite`
- `InviteService.preview(code) -> InvitePreview` — resolves an `invites.code` **or** a `classes.join_code`
- `InviteService.redeem(user_id, code) -> RedeemResult` — idempotent

- [ ] **Step 1: Write the failing service tests**

```python
def test_preview_resolves_a_class_join_code(pg_sessionmaker) -> None:
    """G-08 must accept the code teachers already hand out. classes.join_code
    predates this table (D3.1) and thousands of nothing depend on it, but the
    screen that reads a code cannot ask the holder which kind they have."""


def test_preview_resolves_an_invite_code(pg_sessionmaker) -> None: ...


def test_preview_of_an_unknown_code_raises_invite_not_found(pg_sessionmaker) -> None: ...


def test_preview_does_not_leak_member_identities(pg_sessionmaker) -> None:
    """A preview is public and pre-account. It may name the school, the class
    and the teacher - all of which the code's holder was told by whoever gave
    it to them - and must expose no student, no roster count and no id."""


def test_redeem_assigns_the_seat_and_marks_the_invite_used(pg_sessionmaker) -> None: ...


def test_redeem_is_idempotent(pg_sessionmaker) -> None:
    """Re-redeeming your own invite is a no-op, matching join_by_code."""


def test_redeem_an_already_redeemed_invite_by_another_user_is_refused(pg_sessionmaker) -> None:
    """The one that matters: a code shared onward must not consume a second
    seat or attach a stranger to a school."""


def test_mint_seat_invite_at_quota_raises(pg_sessionmaker) -> None:
    """A code that cannot be redeemed must not be mintable - reserving the
    seat at mint time is what makes the preview's promise true."""
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement `InviteService`**

Binding rules:
1. **Ownership is checked in the service, never the router** — the pattern `SeatService` and `ClassService` already establish (D1.10). `mint_seat_invite` touches only a school the caller holds a `school_admin` membership for; `mint_class_invite` only a class they own.
2. **A seat invite reserves its seat at mint time.** Otherwise the preview promises a place that may be gone by redemption.
3. **`redeem` reuses `ClassService.join_by_code` for class codes** rather than writing a second enrolment path. That method's own docstring asks callers not to write one.
4. **Preview is public, so it is the one place to be paranoid about disclosure.** Name the school, class and teacher; expose no id, no roster, no count.

- [ ] **Step 4: Implement the router** — `GET /api/invites/{code}` (public), `POST /api/invites/{code}/redeem` (authenticated), plus the two mint routes on the existing school/classes routers. Map `InviteNotFound` → 404, `InviteAlreadyRedeemed` → 409, ownership → 403, quota → 409.

- [ ] **Step 5: Run all invite tests**, then `pytest tests/ -k invite -q`.

- [ ] **Step 6: pre-commit, then commit**

```
git commit -S -m "feat(web): redeemable invite codes with a public preview

Closes the gap where two working endpoints had no user could reach them:
POST /student/classes/join was implemented and tested while ClassRoster told
teachers 'they enter it from the student portal', which had no such screen.

preview resolves either an invites.code or a classes.join_code, because the
holder of a code cannot be asked which kind they have. It is public and
pre-account, so it names the school, class and teacher the holder was
already told and exposes no id, roster or count.

A seat invite reserves its seat at mint time - otherwise the preview
promises a place that may be gone by redemption."
```

---

## Task 12: Platform-admin schools surface (backend)

The missing first link (spec §1.1). Without this, `POST /api/school/teachers/invite` remains unreachable in any real deployment.

**Files:**
- Modify: `lemely/db/admin_repo.py` (or create `school_provisioning_repo.py` if `admin_repo` is already large), `lemely/web/routers/admin.py`, `lemely/web/schemas_admin.py`
- Test: `tests/test_web_admin.py`

**Interfaces:**
- `GET /api/admin/schools`, `POST /api/admin/schools`, `PATCH /api/admin/schools/{id}`, `POST /api/admin/schools/{id}/admins` — all `platform_admin`.

- [ ] **Step 1: Write the failing tests**

```python
def test_create_school_requires_platform_admin(client) -> None:
    """Assert 403 for student, teacher AND school_admin. A school_admin
    administers a school; they do not mint one, and this is the boundary
    where getting that wrong creates a tenant."""


def test_create_school_admin_creates_the_account_and_the_membership(client) -> None:
    """Both halves, in one transaction. An account with no membership is a
    school_admin who administers nothing and sees an empty console -
    indistinguishable on screen from a broken one (D4.10's own finding)."""


def test_create_school_admin_returns_the_temporary_password_once(client) -> None:
    """Same credential handling as invite_teacher: no email provider delivers,
    so it is generated once and returned once for out-of-band conveyance."""


def test_quota_below_assigned_seats_is_refused(client) -> None:
    """Lowering a quota under the seats already assigned would make usage
    exceed capacity - a 409 naming both numbers, never a silent accept."""
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** Follow `admin_repo.py`'s existing shape — it is the one service in the product with no tenant scope, reached by its own door. Creating a school_admin reuses `AuthService.signup` at the service layer (which bypasses the router's role guard by design, exactly as `seed.py` does) and writes the `SchoolMembership` in the same unit of work.

- [ ] **Step 4: Run tests to verify they pass**, plus `pytest tests/test_web_admin.py -q`.

- [ ] **Step 5: pre-commit, then commit**

```
git commit -S -m "feat(web): platform-admin school and school-admin provisioning

The account graph had no first link: no production code path created a
School row or a school_admin, so POST /api/school/teachers/invite - the only
teacher-creation path D1.7 allows - was unreachable in any real deployment.
Only seed.py and eighteen test files ever constructed either.

Account and membership are written in one unit of work: a school_admin with
no membership administers nothing and meets an empty console, which D4.10
found is indistinguishable on screen from a broken one."
```

---

# Frontend

From here the plan states files, interfaces, tests and binding constraints rather than markup — see "Plan fidelity" at the top. Two rules apply to **every** task below and are not repeated in each:

- **Build against `DESIGN.md` and the existing kit in `web/src/components/ui/`.** `Input` already carries label, all eight states and a field-level error slot; `Button` has `loading`; `Stepper`, `Checkbox`, `Select` and `Modal` exist. A new screen that hand-rolls a form control is a defect. `AuthFrame` (exported from `portals/auth/Login.tsx`) is the signed-out frame and takes `footer` and `dataPortal` — use it, do not copy it. Its docstring explains what a third copy of that frame costs.
- **No screen renders `error.message`.** Extend `web/src/lib/authOutcome.ts`. Every new failure string is a function there with a test in `web/tests/unit/authOutcome.test.ts`.

---

## Task 13: Types, context and failure copy

**Files:** `web/src/lib/authTypes.ts`, `web/src/lib/auth/AuthContext.tsx`, `web/src/lib/authOutcome.ts`
**Test:** `web/tests/unit/authOutcome.test.ts`

- [ ] **Step 1:** Extend `SignupRequest` with `acceptedTerms: boolean`; add `VerifyEmailBody`, `ResendVerificationResponse`, `PasswordResetRequestBody`, `PasswordResetConfirmBody`, `InvitePreview`. Add `devLink: string | null` to the relevant responses, carrying the same warning comment `OtpRequestResponse.devCode` has.
- [ ] **Step 2:** `AuthContext.signup` currently **hardcodes `role: "student"`** — it must take a role, constrained to `"student" | "teacher"` in the type so the two forbidden roles are not expressible from the client. Add `verifyEmail`, `resendVerification`, `requestPasswordReset`, `confirmPasswordReset` mutations in the same shape.
- [ ] **Step 3:** Extend `authOutcome.ts`: `signUpFailureMessage`, `verificationFailureMessage`, `resetFailureMessage`, `inviteFailureMessage`. Rules — an already-registered address offers a route to sign in **without confirming the address is held**; an expired token says so and offers a resend; the `email_unverified` marker from Task 10 gets its own message routing to G-07.
- [ ] **Step 4:** Unit-test every branch, then pre-commit and commit.

---

## Task 14: G-02 — role selection

**Files:** `web/src/portals/auth/SignupRoleSelect.tsx`
**Spec:** UI spec §G-02.

- [ ] Three choices — *I'm a student*, *I'm a teacher or tutor*, *I'm a parent* — each with one line of what they get. Student → `/signup/student`; teacher → `/signup/teacher`; **parent → `/login/parent`**, because parents authenticate by phone and have no form to fill (§G-02's own exit).
- [ ] Secondary link: "I have an invite code from my school" → `/join`.
- [ ] Footer link to `/login` for people who already have an account.
- [ ] The three choices are **links, not a radio group with a Continue button** — there is no state to collect, and a two-step interaction for a pure branch is friction the spec does not ask for.

---

## Task 15: G-03 — signup details

**Files:** `web/src/portals/auth/SignupDetails.tsx`
**Test:** `web/tests/unit/signup.test.ts`
**Spec:** UI spec §G-03.

- [ ] One component, `role` from the route. Fields: name, email, password (strength feedback, show/hide toggle), consent checkbox linking to `/data`.
- [ ] **No school field on the teacher variant** (D7.2) — the spec's optional "school or centre name" is deliberately dropped, and the component carries a comment saying so and why, so the next reader does not restore it as an oversight.
- [ ] **Validation on blur, not on keystroke** (§G-03, explicit).
- [ ] Submit → `/verify-email`. An already-registered address shows the copy from Task 13 with a link to `/login`.
- [ ] If the route carries an invite code (from G-08), it is retained through signup and redeemed immediately after — §G-08's "flows into G-03 with the code retained".
- [ ] Unit-test the payload builder: consent unticked never submits, and `role` is only ever `student` or `teacher`.

---

## Task 16: G-07 — email verification

**Files:** `web/src/portals/auth/VerifyEmail.tsx`
**Spec:** UI spec §G-07.

- [ ] Pending state: address shown, resend with cooldown, "Wrong address?" route.
- [ ] **"A way to continue into a limited preview rather than a hard wall"** (§G-07, and D7.5): a clear route into the app. What is unavailable — submitting a paper for marking — is stated plainly here rather than discovered at the point of failure.
- [ ] **The delivery claim reads from `devLink`.** When the backend returns one, the provider does not deliver, and the screen must not say a mail was sent — show the developer affordance in an explicitly-labelled panel, exactly as §G-05's `devCode` is handled. This is the one screen where getting the copy wrong reproduces the defect `routes.tsx` records against the parent OTP screen.
- [ ] `/verify-email/:token` confirms and routes to the role home.

---

## Task 17: G-06 — password reset

**Files:** `web/src/portals/auth/PasswordReset.tsx`
**Spec:** UI spec §G-06 ("three screens, no surprises").

- [ ] Request → confirmation → set-new-password → success.
- [ ] The confirmation screen says the same thing whether or not the address exists — the UI half of the anti-enumeration rule. A screen that says "no account found" undoes the backend's care in one line.
- [ ] The success screen states that **all devices have been signed out** (Task 8 rule 3). Surfacing it here is the difference between a security property and a confusing surprise on someone's phone.
- [ ] Same `devLink` handling as Task 16.

---

## Task 18: G-08 — join with an invite code

**Files:** `web/src/portals/auth/JoinWithCode.tsx`
**Spec:** UI spec §G-08.

- [ ] Code field, or pre-filled from `/join/:code`.
- [ ] Preview before committing — "Al-Nasr Language School — Mr Hassan's Physics 0625 class" — from `GET /api/invites/{code}`.
- [ ] Signed out → confirm carries the code into `/signup/student`. Signed in → redeem directly.
- [ ] States: invalid, expired, already redeemed, seat quota full ("explain and tell them to contact their school" — §G-08).
- [ ] Reachable from G-02 and from `/login`.

---

## Task 19: Routes, and the links that make all of this reachable

**Files:** `web/src/routes.tsx`, `web/src/portals/auth/Login.tsx`, `web/src/portals/marketing/index.tsx`, `web/src/portals/marketing/Landing.tsx`
**Test:** `web/tests/unit/navigation.test.ts`, `web/tests/unit/marketing.test.ts`, `web/tests/unit/documentMeta.test.ts`

- [ ] Register the nine routes from spec §4.4, lazy like their neighbours, each with its own inline `<Suspense>` (the reason is documented at the top of `routes.tsx` — no shared wrapper exists at that level).
- [ ] Wrap in `LoginRoute` where a signed-in visitor should be bounced to their portal. **`/verify-email` and `/join` are the exceptions** — both are reachable and useful *with* a session, and wrapping them would make verification unreachable for the account that needs it.
- [ ] `PageMeta` with a `description` on each: these join `/`, `/landing`, `/data`, `/login`, `/login/parent` as the only routes a signed-out reader can reach. Descriptions claim only what the product does, and **must not claim a mail is sent**.
- [ ] `Login.tsx` gains a "Create an account" link to `/signup` and a "Forgot your password?" link to `/reset`. The parent link stays.
- [ ] Marketing CTAs move from `/login` to `/signup` — both hero CTAs and the close CTA. The comment in `Landing.tsx` explaining why they pointed at `/login` is now stale and must be updated, not left to mislead.
- [ ] Extend `navigation.test.ts` to assert public-vs-guarded in **both directions** for every new route. `marketing.test.ts` exists because a guard around the wrong subtree passes typecheck, lint and every design gate — that failure mode is what this assertion style is for.

---

## Task 20: The student onboarding gate

**Files:** `web/src/portals/student/index.tsx`
**Test:** `web/tests/unit/onboardingGate.test.ts`
**Decision:** D7.9.

- [ ] In the portal layout: resolved profile + `onboardingCompletedAt == null` + not already on `/student/onboard` → `<Navigate to="/student/onboard" replace />`.
- [ ] **Never redirect on a pending or errored query.** Render the route fallback while pending; render the portal on error. A gate that fires on `undefined` bounces every returning student on every cold load, and a gate that fires on error traps an account whenever the profile endpoint hiccups.
- [ ] Test all four states explicitly: pending → no redirect; error → no redirect; completed → no redirect; null-and-resolved → redirect.
- [ ] Onboarding's existing "Skip for now" must still work — the gate is a redirect, not a trap, and completing the wizard is what clears it.

---

## Task 21: The teacher first-class gate

**Files:** `web/src/portals/teacher/index.tsx`, plus a first-class step (reuse the existing create-class form rather than building a second one)
**Test:** `web/tests/unit/teacherFirstRun.test.ts`
**Decision:** D7.10.

- [ ] Resolved class list + `length === 0` + not already on the first-class route → redirect.
- [ ] Same four-state pending/error discipline as Task 20.
- [ ] The step ends by showing the **join code** for the class just created, with copy-to-clipboard — that is the artifact the teacher came for, and `ClassDetail.tsx` already has a `JoinCodeChip` to reuse.

---

## Task 22: Platform-admin Schools screen

**Files:** `web/src/portals/admin/screens/Schools.tsx`, `web/src/portals/admin/index.tsx`, `web/src/lib/hooks/useAdminApi.ts`, `web/src/lib/adminTypes.ts`
**Test:** `web/tests/unit/adminRoutes.test.ts`
**Decision:** D7.8.

- [ ] Route `/platform/schools`, guarded `PLATFORM_ADMIN_ROLES`, asserted in both directions in `adminRoutes.test.ts`.
- [ ] List: name, seat quota, seats assigned, school admins. Create a school; edit name/quota; create a school_admin.
- [ ] The generated password is shown **once**, in a panel that says it will not be shown again and that no email is sent — the same honesty the seat-invite response already requires.
- [ ] Quota below assigned seats surfaces the 409 with both numbers, per Task 12.

---

## Task 23: E2E, screenshots, and the written record

**Files:** `web/e2e/signup.spec.ts`, `BUILD/DECISIONS.md`, `BUILD/STATE.md`, `CHANGELOG.md`, `DELIVERY.md`, `docs/LEMELY_UI_SPEC.md`

- [ ] **Step 1: E2E journeys.** Student: `/landing` → `/signup` → `/signup/student` → verify (dev link) → onboarding → dashboard. Teacher: `/signup/teacher` → first class → join code. Invite: mint a code as school_admin → redeem it signed-out through `/join` → land on a seat. Follow `web/e2e/global-setup.ts` and the existing seeded-identity pattern; do not invent a new fixture shape.
- [ ] **Step 2: Screenshots** at 1440 and 375 for all nine new screens into `reports/`, via the existing capture harness. Note the harness switches identity per **surface**, not per state.
- [ ] **Step 3: `BUILD/DECISIONS.md`** — append D7.1–D7.12 from spec §3, in the house format (What / Why / Tests / Alternatives). **Confirm `D7` is still a free namespace** before writing; shift the block if the redesign claimed it.
  - D7.1 must state plainly that it **revises D1.7 item 1 in scope and not in spirit**, and why a teacher is not an escalation. A decision that quietly contradicts an earlier one is how a rule gets lost.
  - Record two known limitations honestly rather than letting them be discovered: the **cooldown is in-process and per-worker** (Task 6), and **no configured provider sends mail** (Task 4).
  - Record that **`users.is_active` remains dead** — written nowhere, read nowhere — and that verification deliberately did not repurpose it.
- [ ] **Step 4: `docs/LEMELY_UI_SPEC.md`** — annotate G-03 where the teacher school field was dropped (D7.2) and G-07 where the soft gate landed on marking (D7.5). The spec is the reference; a divergence it does not record becomes a bug report later.
- [ ] **Step 5: `CHANGELOG.md` and `DELIVERY.md`** — the user-visible summary and the traceability row.
- [ ] **Step 6: Full gate run.**

```
pre-commit run --all-files
pytest -q --tb=short
cd web && npm run typecheck && npm run lint && npm run test:unit && npm run test:e2e
```

- [ ] **Step 7: Commit and push**

```
git push -u origin claude/issue-10-ideation-interview-ya0mgb
```

Retry on network failure up to four times with exponential backoff (2s, 4s, 8s, 16s). **Do not open a pull request unless asked.**

---

## Verification checklist

Mapped to spec §6. Every line is a behaviour to exercise, not a file to look at.

- [ ] A visitor reaches `/signup` from the marketing page, creates a student account, and lands in onboarding.
- [ ] A visitor creates a teacher account and lands in the create-first-class step, ending with a join code.
- [ ] An unverified student is refused at `POST /api/student/correct` with copy routing to resend — **and is refused nowhere else**, uploads included.
- [ ] A forgotten password can be reset end to end, and every prior session is revoked.
- [ ] A platform admin creates a school, sets its quota, and creates a school_admin for it, entirely from the web surface.
- [ ] A school admin mints a seat invite code; a signed-out holder sees the school's name before committing and signs up straight into the seat.
- [ ] A student redeems a class join code from `/join` — closing spec §1.2.
- [ ] `POST /api/auth/signup` with `school_admin` **or** `platform_admin` is still 403, asserted for both.
- [ ] `password-reset/request` answers 200 for an address that does not exist, at both the service and HTTP layers.
- [ ] No new screen renders a raw server `detail`. Grep the diff for `error.message` and `err.message` before opening the PR.
- [ ] No screen or page description claims a mail was sent while `MockEmailProvider` is wired.
