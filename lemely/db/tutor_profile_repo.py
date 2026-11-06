"""Tutor profiles: create, edit, pause, ``indexable``, availability, submit (SPEC §b.2 T1-T5).

A tutor is a ``tutor_profiles`` row on a ``teacher`` account (ADR-T01). This
module is the single writer of the profile's own fields and of
``tutor_subjects`` and ``tutor_availability_rules``; approval, rejection,
suspension, closure and evidence belong to the admin and evidence repositories
(PLAN §1.4 #2). Every tutor route resolves the caller's profile through
:meth:`TutorProfileRepository.for_user` (O1), never from an id the client sends.

**Writes are one transaction each**, which locks the profile row
(``SELECT ... FOR UPDATE``, SPEC §a.4b order: the profile first) and re-checks
the listing state inside it, so a suspension or closure that commits between
the route's guard and the write still wins: a suspended or closed profile is
refused with ``tutor_suspended`` / ``tutor_closed`` (CB-7) and never re-enters
the admin queue (F14). Time guards use the database ``now()``.

**Moderation (SPEC §a.3).** Editing a moderated field (:data:`MODERATED_FIELDS`;
``other_mode_note`` is on the list, SC-7) of a ``listed`` profile sends it back
to ``pending_review``: it leaves the directory until re-approved, its bookings
and grants stay. Only a real change counts (whitespace-only differences do not).
``paused`` and ``indexable`` are not moderated (row 17), nor are subjects,
modes, area or availability.

**Validation (SC-7, SC-25).** Free text passes
``core.contact_patterns.find_contact_details``; the public name passes
``core.tutor_directory.validate_public_name``; the area must be in the bundled
catalogue (``lemely.io.tutoring_areas``); subjects must exist and be active, 1 to
:data:`MAX_SUBJECTS`. A failure is a :class:`ProfileValidationError` carrying an
API ``code`` and the offending ``field``; nothing is written.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from lemely.core.booking import AvailabilityRule, OverlappingRules, normalize_rules
from lemely.core.contact_patterns import find_contact_details
from lemely.core.tutor_directory import InvalidPublicNameError, validate_public_name
from lemely.db.models.enums import Role, TutorApprovalDecision, TutorListingState
from lemely.db.models.tutoring import TutorAvailabilityRule, TutorProfile, TutorSubject
from lemely.db.models.users import User
from lemely.db.tutor_directory_repo import TutorProfileView, fetch_profile_view
from lemely.io.tutoring_areas import AreaCatalogue, load_tutoring_areas

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

#: SPEC §a.3 "listed -> pending_review": the fields whose edit needs re-approval.
MODERATED_FIELDS: Final = (
    "public_first_name",
    "public_last_initial",
    "headline",
    "bio",
    "qualification_note",
    "other_mode_note",
)
MAX_SUBJECTS: Final = 10  # SPEC §a.2 tutor_subjects
MAX_AVAILABILITY_RULES: Final = 42  # SPEC §a.2 tutor_availability_rules, T5
_MAX_HEADLINE: Final = 160
_MAX_BIO: Final = 2000
_MAX_QUALIFICATION_NOTE: Final = 1000
_MAX_OTHER_MODE_NOTE: Final = 200
_SUBMITTABLE: Final = frozenset({TutorListingState.draft, TutorListingState.rejected})
#: Approval notes the tutor may read (SPEC §a.2: the rest are admin-internal).
_TUTOR_VISIBLE_NOTES: Final = frozenset(
    {TutorApprovalDecision.rejected.value, TutorApprovalDecision.suspended.value}
)


# ---------------------------------------------------------------------------
# Errors (each carries the API code the router sends)
# ---------------------------------------------------------------------------


class TutorProfileError(Exception):
    """Base class: ``code`` is the stable API code, ``message`` plain English."""

    code: str = "tutor_profile_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ProfileNotFoundError(TutorProfileError):
    """No profile with that id (the caller has none)."""

    code = "no_tutor_profile"


class NotATeacherError(TutorProfileError):
    """Only a ``teacher`` account may hold a tutor profile (ADR-T01)."""

    code = "not_a_teacher"


class ProfileExistsError(TutorProfileError):
    """The account already has a tutor profile (T2)."""

    code = "profile_exists"


class TutorSuspendedError(TutorProfileError):
    """The profile is suspended: no tutor write is accepted (CB-7)."""

    code = "tutor_suspended"


class TutorClosedError(TutorProfileError):
    """The profile is closed: no tutor write is accepted (CB-7, SC-21)."""

    code = "tutor_closed"


class IllegalTransitionError(TutorProfileError):
    """Submit from a state other than ``draft`` or ``rejected`` (SPEC §a.3)."""

    code = "illegal_transition"


class IncompleteProfileError(TutorProfileError):
    """Submit without the SPEC §a.3 minimum; ``missing`` names what to add."""

    code = "incomplete_profile"

    def __init__(self, missing: Sequence[str]) -> None:
        self.missing: tuple[str, ...] = tuple(missing)
        super().__init__("Before submitting, add: " + ", ".join(self.missing) + ".")


class EmailUnverifiedError(TutorProfileError):
    """Submit needs a verified email (SPEC §a.3, SC-15)."""

    code = "email_unverified"


class ProfileValidationError(TutorProfileError):
    """A field failed validation; ``code`` is the 422 code, ``field`` the snake_case field."""

    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


# ---------------------------------------------------------------------------
# Inputs and read models
# ---------------------------------------------------------------------------


class _Unset(enum.Enum):
    UNSET = "unset"


#: "Not part of this edit" in :class:`ProfileChanges` (``None`` means "clear").
UNSET: Final = _Unset.UNSET


@dataclass(frozen=True, slots=True)
class ProfileFields:
    """Every field of a new profile (T2)."""

    public_first_name: str
    public_last_initial: str | None
    headline: str
    bio: str
    qualification_note: str | None
    subject_codes: tuple[str, ...]
    offers_virtual: bool
    offers_in_person: bool
    offers_other: bool
    other_mode_note: str | None
    area_code: str


@dataclass(frozen=True, slots=True)
class ProfileChanges:
    """An edit (T3). :data:`UNSET` leaves a field alone; ``None`` clears a nullable one.

    ``None`` on a field that cannot be empty is a validation error, not "unchanged".
    """

    public_first_name: str | None | _Unset = UNSET
    public_last_initial: str | None | _Unset = UNSET
    headline: str | None | _Unset = UNSET
    bio: str | None | _Unset = UNSET
    qualification_note: str | None | _Unset = UNSET
    subject_codes: tuple[str, ...] | None | _Unset = UNSET
    offers_virtual: bool | None | _Unset = UNSET
    offers_in_person: bool | None | _Unset = UNSET
    offers_other: bool | None | _Unset = UNSET
    other_mode_note: str | None | _Unset = UNSET
    area_code: str | None | _Unset = UNSET
    paused: bool | None | _Unset = UNSET
    indexable: bool | None | _Unset = UNSET


@dataclass(frozen=True, slots=True)
class TutorProfileRow:
    """The profile facts the tutor guards and routes need (no free text beyond the name)."""

    id: uuid.UUID
    user_id: uuid.UUID
    listing_state: TutorListingState
    paused_at: datetime | None
    closed_at: datetime | None
    zone: str
    public_first_name: str
    public_last_initial: str | None
    indexable: bool
    first_listed_at: datetime | None


@dataclass(frozen=True, slots=True)
class EvidenceFile:
    """An evidence file's metadata; the file itself is never served to the tutor (O17)."""

    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    description: str | None
    uploaded_at: datetime


@dataclass(frozen=True, slots=True)
class OwnProfileView:
    """T1: the profile as students see it, plus what only its owner sees."""

    profile: TutorProfileView
    listing_state: TutorListingState
    paused: bool
    indexable: bool
    submitted_at: datetime | None
    review_note: str | None
    evidence: tuple[EvidenceFile, ...]


def _row(profile: TutorProfile) -> TutorProfileRow:
    return TutorProfileRow(
        id=profile.id,
        user_id=profile.user_id,
        listing_state=profile.listing_state,
        paused_at=profile.paused_at,
        closed_at=profile.closed_at,
        zone=profile.zone,
        public_first_name=profile.public_first_name,
        public_last_initial=profile.public_last_initial,
        indexable=profile.indexable,
        first_listed_at=profile.first_listed_at,
    )


# ---------------------------------------------------------------------------
# Field validation (SC-7, SC-25)
# ---------------------------------------------------------------------------


def _contact_free(field: str, value: str) -> None:
    if find_contact_details(value):
        raise ProfileValidationError(
            "contact_details_not_allowed",
            field,
            "Keep contact details off your profile: students reach you through Lemely.",
        )


def _required_text(field: str, value: str | None, limit: int) -> str:
    if value is None or not value.strip():
        raise ProfileValidationError("invalid_profile", field, f"{field} cannot be empty.")
    text = value.strip()
    if len(text) > limit:
        raise ProfileValidationError(
            "invalid_profile", field, f"{field} is over {limit} characters."
        )
    _contact_free(field, text)
    return text


def _bio(value: str | None) -> str:
    if value is None:
        raise ProfileValidationError(
            "invalid_profile", "bio", "bio cannot be null; send an empty text."
        )
    text = value.strip()
    if len(text) > _MAX_BIO:
        raise ProfileValidationError(
            "invalid_profile", "bio", f"bio is over {_MAX_BIO} characters."
        )
    _contact_free("bio", text)
    return text


def _optional_text(field: str, value: str | None, limit: int) -> str | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    if len(text) > limit:
        raise ProfileValidationError(
            "invalid_profile", field, f"{field} is over {limit} characters."
        )
    _contact_free(field, text)
    return text


def _name(first: str | None, initial: str | None) -> tuple[str, str | None]:
    if first is None:
        raise ProfileValidationError(
            "invalid_public_name", "public_first_name", "A first name is required."
        )
    first_clean = first.strip()
    initial_clean = (initial or "").strip() or None
    try:
        validate_public_name(first_clean, None)
    except InvalidPublicNameError as exc:
        raise ProfileValidationError("invalid_public_name", "public_first_name", str(exc)) from exc
    try:
        validate_public_name(first_clean, initial_clean)
    except InvalidPublicNameError as exc:
        raise ProfileValidationError(
            "invalid_public_name", "public_last_initial", str(exc)
        ) from exc
    return first_clean, initial_clean


def _flag(field: str, value: bool | None) -> bool:
    if value is None:
        raise ProfileValidationError("invalid_profile", field, f"{field} must be true or false.")
    return value


def _modes(
    offers_virtual: bool, offers_in_person: bool, offers_other: bool, note: str | None
) -> None:
    if not (offers_virtual or offers_in_person or offers_other):
        raise ProfileValidationError(
            "invalid_modes", "offers_other", "Offer at least one way to meet."
        )
    if note is not None and not offers_other:
        raise ProfileValidationError(
            "invalid_modes",
            "other_mode_note",
            "A note on other ways to meet needs the 'other' mode.",
        )


def _subject_codes(session: Session, codes: Sequence[str] | None) -> tuple[str, ...]:
    if codes is None:
        raise ProfileValidationError("invalid_subjects", "subject_codes", "Choose your subjects.")
    unique = tuple(dict.fromkeys(code.strip() for code in codes))
    if not 1 <= len(unique) <= MAX_SUBJECTS:
        raise ProfileValidationError(
            "invalid_subjects", "subject_codes", f"Choose 1 to {MAX_SUBJECTS} subjects."
        )
    known = set(
        session.execute(
            sa.text(
                "SELECT code FROM subjects WHERE code = ANY(CAST(:codes AS varchar[])) AND active"
            ),
            {"codes": list(unique)},
        ).scalars()
    )
    unknown = [code for code in unique if code not in known]
    if unknown:
        raise ProfileValidationError(
            "invalid_subjects", "subject_codes", f"Unknown subjects: {', '.join(unknown)}."
        )
    return unique


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class TutorProfileRepository:
    """Tutor profile reads and writes over a ``sessionmaker``."""

    def __init__(
        self, sessionmaker: sessionmaker[Session], areas: AreaCatalogue | None = None
    ) -> None:
        """Wire the repository to a session factory and the area catalogue."""
        self._sessionmaker = sessionmaker
        self._areas = areas if areas is not None else load_tutoring_areas()

    # -- reads --------------------------------------------------------------

    def for_user(self, user_id: uuid.UUID) -> TutorProfileRow | None:
        """The caller's profile, or ``None`` (every tutor route's resolver, O1)."""
        with self._sessionmaker() as session:
            profile = session.scalars(
                sa.select(TutorProfile).where(TutorProfile.user_id == user_id)
            ).first()
            return _row(profile) if profile is not None else None

    def get(self, profile_id: uuid.UUID) -> TutorProfileRow | None:
        """A profile by id, or ``None``."""
        with self._sessionmaker() as session:
            profile = session.get(TutorProfile, profile_id)
            return _row(profile) if profile is not None else None

    def own_profile(self, profile_id: uuid.UUID) -> OwnProfileView | None:
        """T1: the owner's view of a profile, in any listing state."""
        with self._sessionmaker() as session:
            view = fetch_profile_view(
                session, where="tp.id = :tutor_id", params={"tutor_id": profile_id}
            )
            profile = session.get(TutorProfile, profile_id)
            if view is None or profile is None:
                return None
            latest = session.execute(
                sa.text(
                    "SELECT decision::text, note FROM tutor_approval_events "
                    "WHERE tutor_profile_id = :p ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"p": profile_id},
            ).first()
            evidence = session.execute(
                sa.text(
                    "SELECT id, original_filename, content_type, size_bytes, description, "
                    "created_at FROM tutor_evidence_files WHERE tutor_profile_id = :p "
                    "ORDER BY created_at, id"
                ),
                {"p": profile_id},
            ).all()
        note = None
        if latest is not None and latest[0] in _TUTOR_VISIBLE_NOTES:
            note = latest[1]
        return OwnProfileView(
            profile=view,
            listing_state=profile.listing_state,
            paused=profile.paused_at is not None,
            indexable=profile.indexable,
            submitted_at=profile.submitted_at,
            review_note=note,
            evidence=tuple(
                EvidenceFile(
                    id=row[0],
                    filename=row[1],
                    content_type=row[2],
                    size_bytes=row[3],
                    description=row[4],
                    uploaded_at=row[5],
                )
                for row in evidence
            ),
        )

    # -- writes -------------------------------------------------------------

    def create(self, user_id: uuid.UUID, fields: ProfileFields) -> TutorProfileRow:
        """T2: a ``draft`` profile for a teacher account (``indexable`` defaults to true).

        Raises :class:`NotATeacherError`, :class:`ProfileExistsError` or
        :class:`ProfileValidationError`.
        """
        try:
            with self._sessionmaker.begin() as session:
                user = session.get(User, user_id)
                if user is None or user.role is not Role.teacher:
                    raise NotATeacherError("Only a teacher account can hold a tutor profile.")
                existing = session.scalars(
                    sa.select(TutorProfile.id).where(TutorProfile.user_id == user_id)
                ).first()
                if existing is not None:
                    raise ProfileExistsError("You already have a tutor profile.")
                first, initial = _name(fields.public_first_name, fields.public_last_initial)
                headline = _required_text("headline", fields.headline, _MAX_HEADLINE)
                bio = _bio(fields.bio)
                qualification = _optional_text(
                    "qualification_note", fields.qualification_note, _MAX_QUALIFICATION_NOTE
                )
                other_note = _optional_text(
                    "other_mode_note", fields.other_mode_note, _MAX_OTHER_MODE_NOTE
                )
                _modes(
                    fields.offers_virtual, fields.offers_in_person, fields.offers_other, other_note
                )
                self._check_area(fields.area_code)
                subjects = _subject_codes(session, fields.subject_codes)
                profile = TutorProfile(
                    user_id=user_id,
                    public_first_name=first,
                    public_last_initial=initial,
                    headline=headline,
                    bio=bio,
                    qualification_note=qualification,
                    offers_virtual=fields.offers_virtual,
                    offers_in_person=fields.offers_in_person,
                    offers_other=fields.offers_other,
                    other_mode_note=other_note,
                    area_code=fields.area_code,
                )
                session.add(profile)
                session.flush()
                session.add_all(
                    TutorSubject(tutor_profile_id=profile.id, subject_code=code)
                    for code in subjects
                )
                session.flush()
                session.refresh(profile)
                return _row(profile)
        except IntegrityError as exc:
            if _constraint(exc) == "uq_tutor_profiles_user_id":
                raise ProfileExistsError("You already have a tutor profile.") from exc
            raise

    def update(
        self, profile_id: uuid.UUID, changes: ProfileChanges
    ) -> tuple[TutorProfileRow, bool]:
        """T3: apply an edit; returns the profile and whether it went back to review.

        Raises :class:`TutorSuspendedError`, :class:`TutorClosedError`,
        :class:`ProfileNotFoundError` or :class:`ProfileValidationError`.
        """
        with self._sessionmaker.begin() as session:
            profile = self._lock_writable(session, profile_id)
            before = {name: getattr(profile, name) for name in MODERATED_FIELDS}
            self._apply_text(profile, changes)
            self._apply_modes(profile, changes)
            if not isinstance(changes.area_code, _Unset):
                if changes.area_code is None:
                    raise ProfileValidationError("invalid_area", "area_code", "Choose an area.")
                self._check_area(changes.area_code)
                profile.area_code = changes.area_code
            if not isinstance(changes.subject_codes, _Unset):
                codes = _subject_codes(session, changes.subject_codes)
                session.execute(
                    sa.delete(TutorSubject).where(TutorSubject.tutor_profile_id == profile.id)
                )
                session.add_all(
                    TutorSubject(tutor_profile_id=profile.id, subject_code=code) for code in codes
                )
            if not isinstance(changes.paused, _Unset):
                paused = _flag("paused", changes.paused)
                if not paused:
                    profile.paused_at = None
                elif profile.paused_at is None:
                    profile.paused_at = sa.func.now()
            if not isinstance(changes.indexable, _Unset):
                profile.indexable = _flag("indexable", changes.indexable)
            moderated = any(getattr(profile, name) != before[name] for name in MODERATED_FIELDS)
            re_review = moderated and profile.listing_state is TutorListingState.listed
            if re_review:
                profile.listing_state = TutorListingState.pending_review
                profile.submitted_at = sa.func.now()
            session.flush()
            session.refresh(profile)
            return _row(profile), re_review

    def replace_availability(
        self, profile_id: uuid.UUID, rules: Sequence[AvailabilityRule]
    ) -> tuple[AvailabilityRule, ...]:
        """T5: replace every weekly rule (0 to 42); returns them sorted.

        Raises :class:`ProfileValidationError` (``overlapping_rules`` or
        ``invalid_rules``), :class:`TutorSuspendedError` or :class:`TutorClosedError`.
        """
        if len(rules) > MAX_AVAILABILITY_RULES:
            raise ProfileValidationError(
                "invalid_rules", "rules", f"At most {MAX_AVAILABILITY_RULES} weekly windows."
            )
        try:
            ordered = normalize_rules(rules)
        except OverlappingRules as exc:
            raise ProfileValidationError("overlapping_rules", "rules", str(exc)) from exc
        except ValueError as exc:
            raise ProfileValidationError(
                "invalid_rules",
                "rules",
                "Each window needs a weekday 1 to 7 and 15-minute steps within one day.",
            ) from exc
        try:
            with self._sessionmaker.begin() as session:
                profile = self._lock_writable(session, profile_id)
                session.execute(
                    sa.delete(TutorAvailabilityRule).where(
                        TutorAvailabilityRule.tutor_profile_id == profile.id
                    )
                )
                session.add_all(
                    TutorAvailabilityRule(
                        tutor_profile_id=profile.id,
                        iso_weekday=rule.iso_weekday,
                        start_minute=rule.start_minute,
                        end_minute=rule.end_minute,
                    )
                    for rule in ordered
                )
                session.flush()
        except IntegrityError as exc:
            if _constraint(exc) == "excl_tutor_availability_rules_no_overlap":
                raise ProfileValidationError(
                    "overlapping_rules", "rules", "Two weekly windows overlap."
                ) from exc
            raise
        return ordered

    def submit(self, profile_id: uuid.UUID) -> TutorProfileRow:
        """T4: ``draft`` or ``rejected`` to ``pending_review`` (SPEC §a.3).

        Needs a verified email and a complete profile: a headline, at least one
        subject, one mode, an area and one weekly availability window. Raises
        :class:`EmailUnverifiedError`, :class:`IncompleteProfileError`,
        :class:`IllegalTransitionError`, :class:`TutorSuspendedError` or
        :class:`TutorClosedError`.
        """
        with self._sessionmaker.begin() as session:
            profile = self._lock_writable(session, profile_id)
            if profile.listing_state not in _SUBMITTABLE:
                raise IllegalTransitionError("This profile is already submitted or listed.")
            verified = session.execute(
                sa.select(User.email_verified_at).where(User.id == profile.user_id)
            ).scalar_one_or_none()
            if verified is None:
                raise EmailUnverifiedError("Verify your email before submitting your profile.")
            counts = session.execute(
                sa.text(
                    "SELECT (SELECT count(*) FROM tutor_subjects WHERE tutor_profile_id = :p), "
                    "(SELECT count(*) FROM tutor_availability_rules WHERE tutor_profile_id = :p)"
                ),
                {"p": profile.id},
            ).one()
            missing: list[str] = []
            if not profile.headline.strip():
                missing.append("headline")
            if counts[0] == 0:
                missing.append("subjects")
            if not (profile.offers_virtual or profile.offers_in_person or profile.offers_other):
                missing.append("modes")
            if self._areas.get(profile.area_code) is None:
                missing.append("area")
            if counts[1] == 0:
                missing.append("availability")
            if missing:
                raise IncompleteProfileError(missing)
            profile.listing_state = TutorListingState.pending_review
            profile.submitted_at = sa.func.now()
            session.flush()
            session.refresh(profile)
            return _row(profile)

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _lock_writable(session: Session, profile_id: uuid.UUID) -> TutorProfile:
        profile = session.get(TutorProfile, profile_id, with_for_update=True)
        if profile is None:
            raise ProfileNotFoundError("No tutor profile.")
        if profile.listing_state is TutorListingState.suspended:
            raise TutorSuspendedError("Your tutor profile is suspended.")
        if profile.listing_state is TutorListingState.closed:
            raise TutorClosedError("Your tutor profile is closed.")
        return profile

    def _check_area(self, code: str) -> None:
        area = self._areas.get(code)
        if area is None or area.country_code != "EG":
            raise ProfileValidationError(
                "invalid_area", "area_code", "Choose an area from the list."
            )

    @staticmethod
    def _apply_text(profile: TutorProfile, changes: ProfileChanges) -> None:
        if not (
            isinstance(changes.public_first_name, _Unset)
            and isinstance(changes.public_last_initial, _Unset)
        ):
            first = (
                profile.public_first_name
                if isinstance(changes.public_first_name, _Unset)
                else changes.public_first_name
            )
            initial = (
                profile.public_last_initial
                if isinstance(changes.public_last_initial, _Unset)
                else changes.public_last_initial
            )
            profile.public_first_name, profile.public_last_initial = _name(first, initial)
        if not isinstance(changes.headline, _Unset):
            profile.headline = _required_text("headline", changes.headline, _MAX_HEADLINE)
        if not isinstance(changes.bio, _Unset):
            profile.bio = _bio(changes.bio)
        if not isinstance(changes.qualification_note, _Unset):
            profile.qualification_note = _optional_text(
                "qualification_note", changes.qualification_note, _MAX_QUALIFICATION_NOTE
            )
        if not isinstance(changes.other_mode_note, _Unset):
            profile.other_mode_note = _optional_text(
                "other_mode_note", changes.other_mode_note, _MAX_OTHER_MODE_NOTE
            )

    @staticmethod
    def _apply_modes(profile: TutorProfile, changes: ProfileChanges) -> None:
        if not isinstance(changes.offers_virtual, _Unset):
            profile.offers_virtual = _flag("offers_virtual", changes.offers_virtual)
        if not isinstance(changes.offers_in_person, _Unset):
            profile.offers_in_person = _flag("offers_in_person", changes.offers_in_person)
        if not isinstance(changes.offers_other, _Unset):
            profile.offers_other = _flag("offers_other", changes.offers_other)
        _modes(
            profile.offers_virtual,
            profile.offers_in_person,
            profile.offers_other,
            profile.other_mode_note,
        )


def _constraint(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return name if isinstance(name, str) else None


__all__ = [
    "MAX_AVAILABILITY_RULES",
    "MAX_SUBJECTS",
    "MODERATED_FIELDS",
    "UNSET",
    "EmailUnverifiedError",
    "EvidenceFile",
    "IllegalTransitionError",
    "IncompleteProfileError",
    "NotATeacherError",
    "OwnProfileView",
    "ProfileChanges",
    "ProfileExistsError",
    "ProfileFields",
    "ProfileNotFoundError",
    "ProfileValidationError",
    "TutorClosedError",
    "TutorProfileError",
    "TutorProfileRepository",
    "TutorProfileRow",
    "TutorSuspendedError",
]
