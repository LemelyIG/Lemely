"""ORM model for a teacher's team: leased student seats and assistants (spec §4.4).

One row per person attached to a teacher, unique on ``(teacher_user_id,
member_user_id)``. ``kind`` decides which columns mean anything, and two CHECK
constraints make that a database fact:

* ``student_seat``: ``scope_subjects`` (``subjects.code`` values) and
  ``scope_actions`` (``MeteredAction`` values) are set; ``role_preset`` and
  ``permissions`` are null.
* ``assistant``: ``role_preset`` and ``permissions`` (JSONB toggles over the preset)
  are set; both scope columns are null.

``cap_units`` caps the teacher's credits a seat may overflow into (null means no
overflow), or the teacher's balance an assistant may draw (null means no limit), per
``cap_period``. A removed seat keeps its row. ``status`` moves ``active`` → ``leaving``
(``leaves_at`` = end of the month removal was requested) → ``removed``, so a rejoin
reuses the row and the seat count (active plus leaving seats ≤ the plan's seats) is a
plain COUNT under the subscription row lock (``lemely/db/teacher_team_repo.py``).

The four enums mirror nothing in ``lemely.core`` except :class:`AssistantRole`, which
``lemely.core.team_permissions.AssistantRole`` mirrors; ``tests/test_team_schema.py``
pins the pair. ``lemely.db.models`` never imports ``lemely.core``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin


class TeacherMemberKind(enum.StrEnum):
    student_seat = "student_seat"
    assistant = "assistant"


class TeacherMemberStatus(enum.StrEnum):
    active = "active"
    leaving = "leaving"
    removed = "removed"


class AssistantRole(enum.StrEnum):
    co_teacher = "co_teacher"
    marker = "marker"
    viewer = "viewer"


class CapPeriod(enum.StrEnum):
    month = "month"
    total = "total"


class TeacherMember(TimestampMixin, Base):
    __tablename__ = "teacher_members"
    __table_args__ = (
        sa.UniqueConstraint(
            "teacher_user_id", "member_user_id", name="uq_teacher_members_teacher_member"
        ),
        sa.CheckConstraint("teacher_user_id <> member_user_id", name="not_self"),
        sa.CheckConstraint(
            "kind <> 'student_seat' OR (scope_subjects IS NOT NULL AND scope_actions IS NOT NULL"
            " AND role_preset IS NULL AND permissions IS NULL)",
            name="seat_fields",
        ),
        sa.CheckConstraint(
            "kind <> 'assistant' OR (role_preset IS NOT NULL AND permissions IS NOT NULL"
            " AND scope_subjects IS NULL AND scope_actions IS NULL)",
            name="assistant_fields",
        ),
        sa.CheckConstraint("cap_units IS NULL OR cap_units >= 0", name="cap_nonnegative"),
        sa.CheckConstraint("status <> 'leaving' OR leaves_at IS NOT NULL", name="leaving_has_date"),
        sa.CheckConstraint("status <> 'active' OR leaves_at IS NULL", name="active_has_no_date"),
        sa.Index("ix_teacher_members_member_user_id", "member_user_id"),
        sa.Index("ix_teacher_members_teacher_kind_status", "teacher_user_id", "kind", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    teacher_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    member_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[TeacherMemberKind] = mapped_column(
        sa.Enum(TeacherMemberKind, name="teachermemberkind"), nullable=False
    )
    scope_subjects: Mapped[list[str] | None] = mapped_column(ARRAY(sa.String), nullable=True)
    scope_actions: Mapped[list[str] | None] = mapped_column(ARRAY(sa.String), nullable=True)
    role_preset: Mapped[AssistantRole | None] = mapped_column(
        sa.Enum(AssistantRole, name="assistantrole"), nullable=True
    )
    permissions: Mapped[dict[str, bool] | None] = mapped_column(JSONB, nullable=True)
    cap_units: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    cap_period: Mapped[CapPeriod] = mapped_column(
        sa.Enum(CapPeriod, name="capperiod"),
        nullable=False,
        server_default=sa.text("'month'::capperiod"),
    )
    status: Mapped[TeacherMemberStatus] = mapped_column(
        sa.Enum(TeacherMemberStatus, name="teachermemberstatus"),
        nullable=False,
        server_default=sa.text("'active'::teachermemberstatus"),
    )
    leaves_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


__all__ = [
    "AssistantRole",
    "CapPeriod",
    "TeacherMember",
    "TeacherMemberKind",
    "TeacherMemberStatus",
]
