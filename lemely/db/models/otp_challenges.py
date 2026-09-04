"""ORM model for a Postgres-backed OTP challenge (spec 2026-09-03 §4.4, D7.7).

Mirrors :class:`~lemely.auth.otp.OtpStore`'s in-memory shape exactly — same
five fields, same ``(channel, address)`` identity — so ``DbOtpStore``
(``lemely.db.otp_repo``, a later task) can be a drop-in
:class:`~lemely.auth.otp.OtpChallengeStore` for a Cloud Run deployment with
more than one instance, where a process-local dict cannot let one instance
verify a code a second one issued.

**A row never holds a redeemable credential or a raw contact (D7.7).**
``address_hash`` is the SHA-256 hex digest of the normalised phone number or
email address; ``code_hash`` is the SHA-256 hex digest of the code. Neither
column ever holds plaintext — a database read (a backup, a log, a support
query, a leak) yields nothing that verifies a code or identifies a contact.

**No :class:`~lemely.db.models.enums.TimestampMixin`.** Every other table in
this schema carries ``created_at``/``updated_at`` because a row is a durable
record worth knowing the history of. A challenge is not: it lives seconds to
minutes, is replaced wholesale on reissue and deleted outright on success,
expiry or lockout, and ``issued_at`` already answers "when was this
challenge created" for the one case (the resend cooldown) that needs it.
Adding a second, redundant timestamp pair here would track nothing a caller
ever reads.

``channel`` and ``address_hash`` are the composite primary key: a phone
challenge and an email challenge for the same underlying string are two
independent rows with independent codes and independent TTLs, never one row
two channels contend over.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from lemely.auth.otp import OtpChannel
from lemely.db.base import Base


class OtpChallenge(Base):
    """One pending OTP challenge row, keyed by ``(channel, address_hash)``."""

    __tablename__ = "otp_challenges"

    channel: Mapped[OtpChannel] = mapped_column(
        sa.Enum(OtpChannel, name="otpchannel"), primary_key=True
    )
    address_hash: Mapped[str] = mapped_column(sa.String, primary_key=True)
    """SHA-256 hex digest of the normalised phone number or email address."""
    code_hash: Mapped[str] = mapped_column(sa.String, nullable=False)
    """SHA-256 hex digest of the current code. Never the plaintext code."""
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))


__all__ = ["OtpChallenge"]
