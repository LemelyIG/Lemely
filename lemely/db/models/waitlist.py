"""ORM model for the public landing-page waitlist (migration ``0052_waitlist_applicants``).

One row per applicant. Step 1 of the two-step form creates the row with an email, a name and a role
(``completed_at`` NULL, a partial applicant); step 2 fills the rest with a one-time completion
token whose SHA-256 digest is stored here and cleared on use. The consent wording shown to the
applicant and the instant they accepted it are kept per row so the policy can change later
without losing what each person agreed to.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin


class WaitlistRole(enum.Enum):
    """Who is applying."""

    student = "student"
    teacher = "teacher"
    parent = "parent"
    centre_admin = "centre_admin"


class WaitlistStatus(enum.Enum):
    """Where an applicant is in the team's follow-up."""

    new = "new"
    contacted = "contacted"
    invited = "invited"
    declined = "declined"


class WaitlistApplicant(TimestampMixin, Base):
    """One landing-page waitlist applicant (partial until ``completed_at`` is set)."""

    __tablename__ = "waitlist_applicants"
    __table_args__ = (
        sa.UniqueConstraint("email", name="uq_waitlist_applicants_email"),
        sa.Index(
            "uq_waitlist_applicants_token_hash",
            "completion_token_hash",
            unique=True,
            postgresql_where=sa.text("completion_token_hash IS NOT NULL"),
        ),
        sa.Index(
            "uq_waitlist_applicants_confirm_token_hash",
            "confirm_token_hash",
            unique=True,
            postgresql_where=sa.text("confirm_token_hash IS NOT NULL"),
        ),
        sa.Index("ix_waitlist_applicants_created_at", "created_at"),
        sa.Index("ix_waitlist_applicants_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(sa.String(254), nullable=False)
    #: Applicant's name from step 1; NULL only for rows created before migration 0053.
    name: Mapped[str | None] = mapped_column(sa.String(100))
    role: Mapped[WaitlistRole] = mapped_column(
        sa.Enum(WaitlistRole, name="waitlistrole"), nullable=False
    )
    centre_name: Mapped[str | None] = mapped_column(sa.String(120))
    levels: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(20)), nullable=False, server_default=sa.text("'{}'")
    )
    subjects: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(40)), nullable=False, server_default=sa.text("'{}'")
    )
    other_subjects: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(60)), nullable=False, server_default=sa.text("'{}'")
    )
    exam_boards: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(20)), nullable=False, server_default=sa.text("'{}'")
    )
    exam_session: Mapped[str | None] = mapped_column(sa.String(10))
    phone: Mapped[str | None] = mapped_column(sa.String(20))
    phone_has_whatsapp: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    email_confirmed: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    #: When the address was confirmed through the emailed link (NULL until then).
    email_confirmed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    #: SHA-256 of the newest emailed confirmation token and the expiry shared by every link of the
    #: current window (7 days after the latest mail). The digest is kept after use so a repeat
    #: click still reads "already confirmed".
    confirm_token_hash: Mapped[str | None] = mapped_column(sa.String(64))
    confirm_token_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    #: Digests of the earlier links of the window: a re-send never kills a link already in the
    #: owner's inbox (a stranger re-submitting the address cannot invalidate it).
    confirm_prev_hashes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(64)), nullable=False, server_default=sa.text("'{}'")
    )
    #: When a confirmation mail was last issued (the per-address resend throttle) and how many
    #: went out in the current window (the cap).
    confirm_sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    confirm_send_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    consent_version: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    consent_text: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    consent_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    status: Mapped[WaitlistStatus] = mapped_column(
        sa.Enum(WaitlistStatus, name="waitliststatus"),
        nullable=False,
        server_default=sa.text("'new'::waitliststatus"),
    )
    admin_note: Mapped[str | None] = mapped_column(sa.String(2000))
    utm_source: Mapped[str | None] = mapped_column(sa.String(100))
    utm_medium: Mapped[str | None] = mapped_column(sa.String(100))
    utm_campaign: Mapped[str | None] = mapped_column(sa.String(100))
    utm_content: Mapped[str | None] = mapped_column(sa.String(100))
    utm_term: Mapped[str | None] = mapped_column(sa.String(100))
    completion_token_hash: Mapped[str | None] = mapped_column(sa.String(64))
    completion_token_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class WaitlistDigestLog(Base):
    """One row per UTC day a team digest was claimed: the idempotency marker and window cursor.

    The row is inserted *before* the mail is sent (``ON CONFLICT DO NOTHING`` is the claim) and
    deleted again if the send fails, so a second scheduler firing the same day finds the row and
    does nothing, while a failed send can still be retried.
    """

    __tablename__ = "waitlist_digest_log"

    day: Mapped[date] = mapped_column(sa.Date, primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    new_applicants: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: End of the window this digest covered, set only once the mail was sent: the next digest
    #: starts here. ``NULL`` is a claim whose send has not (yet) succeeded.
    window_end: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
