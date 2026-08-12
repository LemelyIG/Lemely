"""ORM models for schools, memberships, seats, classes, and enrolments."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import MembershipRole, SeatStatus, TimestampMixin


class School(TimestampMixin, Base):
    """An educational institution that purchases seats for its students."""

    __tablename__ = "schools"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    seat_quota: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    memberships: Mapped[list[SchoolMembership]] = relationship(
        "SchoolMembership", back_populates="school", cascade="all, delete-orphan"
    )
    seats: Mapped[list[Seat]] = relationship(
        "Seat", back_populates="school", cascade="all, delete-orphan"
    )
    classes: Mapped[list[SchoolClass]] = relationship(
        "SchoolClass", back_populates="school", cascade="all, delete-orphan"
    )


class SchoolMembership(TimestampMixin, Base):
    """Staff member (teacher or school_admin) association with a school."""

    __tablename__ = "school_memberships"
    __table_args__ = (
        sa.UniqueConstraint(
            "school_id",
            "user_id",
            name="uq_school_memberships_school_id_user_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    membership_role: Mapped[MembershipRole] = mapped_column(
        sa.Enum(MembershipRole, name="membershiprole"),
        nullable=False,
    )

    school: Mapped[School] = relationship("School", back_populates="memberships")


class Seat(TimestampMixin, Base):
    """A single purchasable slot in a school's seat quota."""

    __tablename__ = "seats"
    __table_args__ = (sa.Index("ix_seats_school_id_status", "school_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[SeatStatus] = mapped_column(
        sa.Enum(SeatStatus, name="seatstatus"),
        nullable=False,
        server_default=sa.text("'available'::seatstatus"),
    )
    assigned_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    school: Mapped[School] = relationship("School", back_populates="seats")


class SchoolClass(TimestampMixin, Base):
    """A teacher-led class, optionally within a school.

    Table name ``classes`` avoids the SQL reserved word ``class``. ``school_id``
    is nullable (D3.1): a teacher may run a class independently of any school,
    in which case the class has no seat pool and enrols students only via
    ``join_code``.
    """

    __tablename__ = "classes"
    __table_args__ = (sa.Index("ix_classes_join_code", "join_code"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=True,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    subject_code: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # Server-generated per class by ClassService.create_class; a student
    # self-enrols by posting this code (the only enrolment path available to an
    # independent teacher's class, which has no seat pool). Nullable at the
    # column level only because the constraint cannot retroactively backfill a
    # pre-existing row; every row created through the service carries one.
    join_code: Mapped[str | None] = mapped_column(sa.String, nullable=True, unique=True)

    school: Mapped[School | None] = relationship("School", back_populates="classes")
    enrollments: Mapped[list[ClassEnrollment]] = relationship(
        "ClassEnrollment", back_populates="school_class", cascade="all, delete-orphan"
    )


class ClassEnrollment(TimestampMixin, Base):
    """Enrols a student in a class."""

    __tablename__ = "class_enrollments"
    __table_args__ = (
        sa.UniqueConstraint(
            "class_id",
            "student_id",
            name="uq_class_enrollments_class_id_student_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    school_class: Mapped[SchoolClass] = relationship("SchoolClass", back_populates="enrollments")


__all__ = ["ClassEnrollment", "School", "SchoolClass", "SchoolMembership", "Seat"]
