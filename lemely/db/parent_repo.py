"""Parent-child link model service — the parent-portal read backend (D3.11).

Mirrors :mod:`lemely.db.class_repo`'s ``ClassService`` shape directly: pure
lookup/linking logic over a ``sessionmaker``, domain errors mapped to HTTP
status codes by a thin router layer, testable against Postgres with no
GoTrue dependency.

**This service is the single ``parent_child_links`` query in the codebase** —
no parent or student route may query that table directly (the same
single-seam discipline :meth:`~lemely.db.class_repo.ClassService.enrolled_class_ids`
already established for ``ClassEnrollment``). A row in ``parent_child_links``
*is* the grant — there is no separate status column, so "linked" and
"a row exists" are the same fact everywhere in this module.

**Linking direction is fixed (D3.11), decided upstream of this module — do
not redesign it here.** The student invites a parent by phone
(:meth:`ParentLinkService.link`), which resolves that phone to an *existing*
``role=parent`` user and links to it. It never creates a user from a
student-supplied phone: a stranger's mistyped or spoofed number could
otherwise be handed a child's grades on the strength of nothing but a phone
number the student typed in. A phone with no matching parent account raises
:class:`ParentUserNotFoundError` — the parent must OTP-login at least once
(which auto-creates their ``role=parent`` user, :meth:`AuthService.verify_otp`)
before a student can invite them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from lemely.db.models import ParentChildLink, User
from lemely.db.models.enums import Role

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class ParentLinkError(Exception):
    """Base class for parent-link-model failures."""


class ParentUserNotFoundError(ParentLinkError):
    """No ``role=parent`` user exists with the supplied phone (→ 404)."""


@dataclass(frozen=True, slots=True)
class ChildRow:
    """One linked child: identity only (no history/analytics)."""

    child_id: uuid.UUID
    display_name: str
    email: str | None
    phone: str | None


@dataclass(frozen=True, slots=True)
class ParentRow:
    """One linked parent: identity only."""

    parent_id: uuid.UUID
    display_name: str
    phone: str | None


def _parent_display_name(display_name: str | None, email: str, phone: str | None) -> str:
    """Best honest identity for a parent, never an internal artefact.

    A phone-only parent is minted by :meth:`~lemely.auth.service.AuthService.verify_otp`
    with a **synthesised** ``phone+20…@parents.lemely.local`` address, because
    ``users.email`` is NOT NULL + unique and no real address has been captured
    yet (:func:`~lemely.auth.service._phone_placeholder_email`). Falling back
    straight to ``email`` therefore showed a student that machine-generated
    string as their parent's name — found in P3.9 chunk-d verification.

    The phone number is the right fallback: it is the identifier the student
    typed to create the link, so they recognise it, and unlike the placeholder
    it is a real fact about the account. The real email is still preferred over
    it when one exists, and the placeholder is only ever reached if a parent
    somehow has neither a name nor a phone — in which case it is the sole
    remaining identifier and showing it beats showing nothing.
    """
    if display_name:
        return display_name
    if email.endswith(_PLACEHOLDER_EMAIL_DOMAIN) and phone:
        return phone
    return email


_PLACEHOLDER_EMAIL_DOMAIN = "@parents.lemely.local"
"""Domain of the synthesised address above. Kept beside its only consumer
rather than imported from ``lemely.auth.service`` — the DB layer must not
depend on the auth layer (import-linter enforces this), so the two are pinned
together by a test instead."""


class ParentLinkService:
    """Parent-child link lookup/create/delete (D3.11).

    Constructed with a ``sessionmaker`` (mirroring
    :class:`~lemely.db.class_repo.ClassService`). Every method re-derives its
    result from ``parent_child_links`` directly — there is no cached/derived
    notion of "linked" anywhere else.
    """

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the service to a session factory."""
        self._sessionmaker = sessionmaker

    # -- Introspection ------------------------------------------------------

    def linked_children(self, parent_id: uuid.UUID | str) -> list[ChildRow]:
        """Return every child linked to ``parent_id``, deterministically ordered."""
        parent_uuid = _as_uuid(parent_id)
        with self._sessionmaker() as session:
            stmt = (
                select(User.id, User.display_name, User.email, User.phone)
                .join(ParentChildLink, ParentChildLink.child_id == User.id)
                .where(ParentChildLink.parent_id == parent_uuid)
                .order_by(User.display_name, User.email)
            )
            return [
                ChildRow(
                    child_id=child_id,
                    display_name=display_name or email,
                    email=email,
                    phone=phone,
                )
                for child_id, display_name, email, phone in session.execute(stmt).all()
            ]

    def get_child(self, parent_id: uuid.UUID | str, child_id: uuid.UUID | str) -> ChildRow | None:
        """Return the linked child row for ``(parent_id, child_id)``, or ``None``.

        **The authz seam.** Returns ``None`` when no link row exists for this
        exact pair — callers use this to distinguish "linked" from "not
        linked"; this method never raises for the not-linked case. Whether
        that becomes a 403 (child exists but isn't linked to this parent) or
        a 404 (no such child at all) is a router-layer decision, not this
        service's — see ``lemely.web.routers.parent``.
        """
        parent_uuid = _as_uuid(parent_id)
        child_uuid = _as_uuid(child_id)
        with self._sessionmaker() as session:
            stmt = (
                select(User.id, User.display_name, User.email, User.phone)
                .join(ParentChildLink, ParentChildLink.child_id == User.id)
                .where(
                    ParentChildLink.parent_id == parent_uuid,
                    ParentChildLink.child_id == child_uuid,
                )
            )
            row = session.execute(stmt).first()
            if row is None:
                return None
            child_id_, display_name, email, phone = row
            return ChildRow(
                child_id=child_id_,
                display_name=display_name or email,
                email=email,
                phone=phone,
            )

    def list_parents(self, student_id: uuid.UUID | str) -> list[ParentRow]:
        """Return every parent linked to this child, deterministically ordered."""
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            stmt = (
                select(User.id, User.display_name, User.email, User.phone)
                .join(ParentChildLink, ParentChildLink.parent_id == User.id)
                .where(ParentChildLink.child_id == student_uuid)
                .order_by(User.display_name, User.email)
            )
            return [
                ParentRow(
                    parent_id=parent_id,
                    display_name=_parent_display_name(display_name, email, phone),
                    phone=phone,
                )
                for parent_id, display_name, email, phone in session.execute(stmt).all()
            ]

    # -- Linking --------------------------------------------------------------

    def link(self, student_id: uuid.UUID | str, phone: str) -> ParentRow:
        """Link an existing ``role=parent`` user (found by ``phone``) to this child.

        Idempotent: re-linking an already-linked pair does not attempt a
        duplicate insert (checked first, mirroring
        :meth:`~lemely.db.class_repo.ClassService._enrol_if_absent` rather
        than relying on catching the unique-constraint violation) and simply
        returns the existing link's :class:`ParentRow`.

        Never creates a user. When multiple ``role=parent`` users somehow
        share a phone, the tie-break mirrors
        :meth:`~lemely.auth.mirror.DbUserMirror.get_by_phone`: the
        most-recently-created one wins, so both lookups agree on "the"
        parent for a phone.

        Raises:
            ParentUserNotFoundError: No ``role=parent`` user has ``phone``.
        """
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session, session.begin():
            parent = session.scalars(
                select(User)
                .where(User.phone == phone, User.role == Role.parent)
                .order_by(User.created_at.desc())
                .limit(1)
            ).first()
            if parent is None:
                raise ParentUserNotFoundError(f"No parent account found for phone {phone!r}")
            self._link_if_absent(session, parent.id, student_uuid)
            return ParentRow(
                parent_id=parent.id,
                display_name=_parent_display_name(parent.display_name, parent.email, parent.phone),
                phone=parent.phone,
            )

    def unlink(self, student_id: uuid.UUID | str, parent_id: uuid.UUID | str) -> None:
        """Delete the ``(parent_id, child_id)`` link row. Idempotent.

        Deleting a link that does not exist is a silent no-op, not an error —
        mirrors :meth:`~lemely.db.class_repo.ClassService.remove_student`.
        """
        student_uuid = _as_uuid(student_id)
        parent_uuid = _as_uuid(parent_id)
        with self._sessionmaker() as session, session.begin():
            session.execute(
                delete(ParentChildLink).where(
                    ParentChildLink.parent_id == parent_uuid,
                    ParentChildLink.child_id == student_uuid,
                )
            )

    # -- Internals ------------------------------------------------------------

    def _link_if_absent(
        self, session: Session, parent_uuid: uuid.UUID, child_uuid: uuid.UUID
    ) -> None:
        existing = session.scalars(
            select(ParentChildLink.id).where(
                ParentChildLink.parent_id == parent_uuid,
                ParentChildLink.child_id == child_uuid,
            )
        ).first()
        if existing is None:
            session.add(ParentChildLink(parent_id=parent_uuid, child_id=child_uuid))
            session.flush()


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "ChildRow",
    "ParentLinkError",
    "ParentLinkService",
    "ParentRow",
    "ParentUserNotFoundError",
]
