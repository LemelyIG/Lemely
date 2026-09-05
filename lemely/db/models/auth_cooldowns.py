"""ORM model for a Postgres-backed cooldown stamp (spec 2026-09-03 §4.4, D7.7).

Mirrors :class:`~lemely.auth.cooldown.CooldownStore`'s in-memory shape
exactly — one row per key it has ever stamped — so ``DbCooldownStore``
(``lemely.db.cooldown_repo``) can be a drop-in
:class:`~lemely.auth.cooldown.CooldownStoreProtocol` for a Cloud Run
deployment with more than one instance, where a process-local dict cannot
let one instance's stamp throttle a caller a second instance receives.

**A row never holds a raw contact (D7.7).** ``key_hash`` is the SHA-256 hex
digest of the cooldown key — an email address for every caller this table
serves today (signup, password-reset, verification-resend) — never the
plaintext. A database read (a backup, a log, a support query, a leak)
therefore yields nothing that identifies who a cooldown was stamped for.
``String(64)`` — a SHA-256 hex digest is always exactly 64 characters — the
same explicit length ``otp_challenges`` and ``auth_tokens.token_hash``
(migration ``0022``) use.

**``purpose`` is a plain string, not an enum.** Two values exist today
(``signup_and_reset``, ``resend_verification`` — the two stores
``lemely.web.deps`` builds), but this table's whole point is per-caller
independence, not an enumerated vocabulary the schema should enforce; a
third D7.12 caller can start stamping a new purpose with no migration. The
same ``(purpose, key_hash)`` key never contends across purposes — signing up
and resending a verification email for the same address are stamped, and
throttled, independently, exactly as two separate ``CooldownStore``
instances (``deps.py`` builds one per purpose today) already are.

**No :class:`~lemely.db.models.enums.TimestampMixin`.** A cooldown row is
overwritten wholesale on every successful stamp and carries no history worth
keeping — ``stamped_at`` already answers "when was this last touched" for
the one thing a caller ever asks, the same reasoning
``lemely/db/models/otp_challenges.py`` gives for the identical omission.

``purpose`` and ``key_hash`` are the composite primary key: a signup
cooldown and a resend cooldown for the same underlying email are two
independent rows with independent stamps, never one row two purposes
contend over.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base


class AuthCooldown(Base):
    """One resend-cooldown stamp, keyed by ``(purpose, key_hash)``."""

    __tablename__ = "auth_cooldowns"

    purpose: Mapped[str] = mapped_column(sa.String, primary_key=True)
    """The calling flow: ``signup_and_reset`` or ``resend_verification`` today."""
    key_hash: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    """SHA-256 hex digest of the cooldown key. Never the plaintext contact."""
    stamped_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


__all__ = ["AuthCooldown"]
