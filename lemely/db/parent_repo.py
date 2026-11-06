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
not redesign it here.** The student mints an invite
(:meth:`~lemely.db.invite_repo.InviteService.mint_parent_invite`); the parent
proves control of an email address via a one-time code before redeeming it
(:meth:`~lemely.auth.service.AuthService.verify_parent_signup_code`). This
module never resolves an identity from anything the student typed — by the
time :meth:`ParentLinkService.link_in_session` runs, the invite service has
already decided the link is safe to create. It is the sole caller, invoking
``link_in_session`` inside the same transaction that marks the invite
redeemed, which is why this method takes an open ``Session`` instead of
opening its own.

**Link integrity (tutoring SPEC §c.4, decision row 14 = SC-1).** A child
could remove the parent who oversees them, or link anyone as a "parent",
and nobody was told (THREAT-MODEL CB-1, CB-2). So every link change here now
leaves a trace and a notice, in the change's own transaction:

* a new link appends a ``parent_link_events(linked)`` row and queues a
  ``parent_linked`` email to every parent already linked; a removed link
  appends ``parent_link_events(unlinked)`` and queues ``parent_unlinked`` to
  the parent removed. A no-op (re-linking a linked pair, unlinking an absent
  one) writes nothing at all;
* a child has at most :data:`MAX_LINKED_PARENTS` linked parents. The cap is
  counted under ``SELECT … FROM users WHERE id = :child FOR UPDATE``, so two
  concurrent redemptions cannot both see three links and both insert. A child
  who already had more links before the cap keeps them.

The inbox notices go out after commit, from the router (D5.9 §1): each change
returns a :class:`ParentLinkChange` carrying the event id and the parents to
tell. Booking and grant writes reach the links through
:meth:`ParentLinkService.lock_link_in_session` and
:meth:`ParentLinkService.linked_parent_ids_in_session`, so this module stays the
single ``parent_child_links`` query.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import delete, insert, select

from lemely.db.email_outbox_repo import enqueue_in_session
from lemely.db.models import ParentChildLink, User
from lemely.db.models.enums import ParentLinkEvent
from lemely.db.models.tutoring import ParentLinkEventLog

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

MAX_LINKED_PARENTS: Final = 4
"""Most parents one child may have linked (SPEC §c.4, SC-1 d). Re-linking a
parent who is already linked is always allowed, and children linked to more
parents before the cap existed keep every link."""


class ParentLinkError(Exception):
    """Base class for parent-link-model failures."""


class ParentLimitReachedError(ParentLinkError):
    """The child already has :data:`MAX_LINKED_PARENTS` linked parents (→ 409 ``parent_limit``)."""


@dataclass(frozen=True, slots=True)
class ParentLinkChange:
    """A link that was created or removed, as the after-commit notice needs it.

    ``event_id`` is the ``parent_link_events`` row written in the same
    transaction (the inbox dedupe key is ``parent-link:{event_id}``, SPEC §b.4);
    ``notify_parent_ids`` are the parents to tell: every parent linked before a
    new link, or the one parent a removal unlinked.
    """

    event_id: uuid.UUID
    event: ParentLinkEvent
    child_id: uuid.UUID
    parent_id: uuid.UUID
    notify_parent_ids: tuple[uuid.UUID, ...]


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
    email: str
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
                    email=email,
                    phone=phone,
                )
                for parent_id, display_name, email, phone in session.execute(stmt).all()
            ]

    # -- In the caller's transaction (bookings, grants, sweeps) ---------------

    def linked_parent_ids_in_session(
        self, session: Session, child_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Every parent linked to ``child_id``, ordered by id, read in the caller's transaction.

        The recipient list for the tutoring notices to a child's parents: read
        inside the change's transaction, so the outbox rows it writes and the
        inbox notices sent after commit name the same parents.
        """
        return list(
            session.scalars(
                select(ParentChildLink.parent_id)
                .where(ParentChildLink.child_id == child_id)
                .order_by(ParentChildLink.parent_id)
            )
        )

    def lock_link_in_session(
        self, session: Session, parent_id: uuid.UUID, child_id: uuid.UUID
    ) -> bool:
        """Share-lock the ``(parent_id, child_id)`` link for the caller's transaction.

        ``True`` when the link exists (and is now held ``FOR SHARE``), ``False``
        when it does not. A concurrent :meth:`unlink` (a ``DELETE``) waits for
        the caller's commit, so a parent's booking or cancellation cannot
        interleave with the child removing that parent (SPEC §a.4b step 4,
        BK-3).
        """
        held = session.scalars(
            select(ParentChildLink.id)
            .where(
                ParentChildLink.parent_id == parent_id,
                ParentChildLink.child_id == child_id,
            )
            .with_for_update(read=True)
        ).first()
        return held is not None

    # -- Linking --------------------------------------------------------------

    def link_in_session(
        self, session: Session, parent_id: uuid.UUID, child_id: uuid.UUID
    ) -> ParentLinkChange | None:
        """Create the ``(parent_id, child_id)`` link, record it and queue the parents' emails.

        Runs inside the caller's own transaction rather than opening one of
        its own — :meth:`~lemely.db.invite_repo.InviteService.redeem` is the
        only caller, and it needs the invite marked redeemed and the link row
        created atomically. No role check: the caller (the invite service)
        has already verified ``parent_id`` is a ``role=parent`` user by the
        time it gets here, per :class:`~lemely.db.invite_repo.InviteRoleMismatchError`.

        The child's ``users`` row is locked ``FOR UPDATE`` before the links are
        read, so the cap count and the recipient list cannot change under it
        until the caller commits.

        Idempotent: re-linking an already-linked pair, or redeeming a reusable
        invite a second time, writes nothing and returns ``None`` (checked
        first, mirroring :meth:`~lemely.db.class_repo.ClassService._enrol_if_absent`
        rather than relying on catching the unique-constraint violation), even
        for a child at or over the cap.

        Returns:
            The change for the after-commit notices, or ``None`` when the pair
            was already linked.

        Raises:
            ParentLimitReachedError: ``child_id`` already has
                :data:`MAX_LINKED_PARENTS` linked parents and ``parent_id`` is
                not one of them. Nothing was written.
        """
        session.execute(select(User.id).where(User.id == child_id).with_for_update())
        linked = self.linked_parent_ids_in_session(session, child_id)
        if parent_id in linked:
            return None
        if len(linked) >= MAX_LINKED_PARENTS:
            raise ParentLimitReachedError(
                f"Child {child_id} already has {len(linked)} linked parents"
            )
        session.add(ParentChildLink(parent_id=parent_id, child_id=child_id))
        session.flush()
        event_id = self._record_event(session, child_id, parent_id, ParentLinkEvent.linked)
        for recipient in linked:
            self._queue_email(session, "parent_linked", event_id, recipient)
        return ParentLinkChange(
            event_id=event_id,
            event=ParentLinkEvent.linked,
            child_id=child_id,
            parent_id=parent_id,
            notify_parent_ids=tuple(linked),
        )

    def unlink(self, student_id: uuid.UUID | str, parent_id: uuid.UUID | str) -> bool:
        """Delete the ``(parent_id, child_id)`` link. ``True`` when a link was removed.

        Deleting a link that does not exist is a silent no-op that writes
        nothing and returns ``False`` — mirrors
        :meth:`~lemely.db.class_repo.ClassService.remove_student`. See
        :meth:`unlink_with_event`, which this delegates to, for what a removal
        records; the route uses that method directly because its inbox notice
        needs the event id.
        """
        return self.unlink_with_event(student_id, parent_id) is not None

    def unlink_with_event(
        self, student_id: uuid.UUID | str, parent_id: uuid.UUID | str
    ) -> ParentLinkChange | None:
        """Delete the link, record ``unlinked`` and queue the unlinked parent's email.

        All in one transaction: the ``parent_link_events(unlinked)`` row is the
        durable record of a link that no longer exists (SPEC §b.4 item 4), so it
        commits or rolls back with the delete. ``None`` (and nothing written)
        when the pair was not linked.

        **Lock order (SPEC §a.4b).** The child's ``users`` row is locked before
        the link row is touched, the same order :meth:`link_in_session` and a
        booking create use (the student row, then the link). Deleting first
        would hold the link row while the event insert's foreign-key check
        waits for the child row, which a booking create holds while it waits
        for the link: a deadlock.

        The child-row lock is ``FOR NO KEY UPDATE``, not ``FOR UPDATE``. It
        still queues behind (and blocks) the ``FOR UPDATE`` that
        :meth:`link_in_session` and a booking create take, but it does not
        block the key-share lock a foreign-key check takes. A parent's cancel
        or complete holds the link ``FOR SHARE`` (step 4) and then inserts rows
        that reference the child; under ``FOR UPDATE`` here that insert would
        wait for this unlink while this unlink waits for its link: a deadlock.
        """
        student_uuid = _as_uuid(student_id)
        parent_uuid = _as_uuid(parent_id)
        with self._sessionmaker() as session, session.begin():
            session.execute(
                select(User.id).where(User.id == student_uuid).with_for_update(key_share=True)
            )
            removed = session.scalars(
                delete(ParentChildLink)
                .where(
                    ParentChildLink.parent_id == parent_uuid,
                    ParentChildLink.child_id == student_uuid,
                )
                .returning(ParentChildLink.id)
                .execution_options(synchronize_session=False)
            ).first()
            if removed is None:
                return None
            event_id = self._record_event(
                session, student_uuid, parent_uuid, ParentLinkEvent.unlinked
            )
            self._queue_email(session, "parent_unlinked", event_id, parent_uuid)
        return ParentLinkChange(
            event_id=event_id,
            event=ParentLinkEvent.unlinked,
            child_id=student_uuid,
            parent_id=parent_uuid,
            notify_parent_ids=(parent_uuid,),
        )

    # -- Internals ------------------------------------------------------------

    def _record_event(
        self,
        session: Session,
        child_id: uuid.UUID,
        parent_id: uuid.UUID,
        event: ParentLinkEvent,
    ) -> uuid.UUID:
        """Append one ``parent_link_events`` row and return its id."""
        return session.execute(
            insert(ParentLinkEventLog)
            .values(child_id=child_id, parent_id=parent_id, event=event)
            .returning(ParentLinkEventLog.id)
        ).scalar_one()

    def _queue_email(
        self, session: Session, template: str, event_id: uuid.UUID, recipient: uuid.UUID
    ) -> None:
        """Queue one link email; skipped by the outbox when the recipient switched it off."""
        enqueue_in_session(
            session,
            recipient_user_id=recipient,
            template=template,
            context={"event_id": event_id},
            dedupe_key=f"parent-link:{event_id}:{recipient}",
        )


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "MAX_LINKED_PARENTS",
    "ChildRow",
    "ParentLimitReachedError",
    "ParentLinkChange",
    "ParentLinkError",
    "ParentLinkService",
    "ParentRow",
]
