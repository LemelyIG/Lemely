"""The tutor profile repository (SPEC §b.2 T1-T5, §a.3 tutor listing, §a.4b CB-7, SC-7, SC-25).

DB-backed against a ``create_all`` database (helpers from
``tests/test_tutor_directory_repo.py``). Every write is one transaction that
locks the profile row and re-checks the listing state inside it, so these tests
drive the repository directly; the route tests in ``tests/test_web_tutor.py``
cover the HTTP mapping of each error.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.booking import AvailabilityRule
from lemely.db.models.enums import Role, TutorApprovalDecision, TutorListingState
from lemely.db.models.tutoring import TutorApprovalEvent, TutorEvidenceFile, TutorProfile
from lemely.db.tutor_profile_repo import (
    MODERATED_FIELDS,
    EmailUnverifiedError,
    IllegalTransitionError,
    IncompleteProfileError,
    NotATeacherError,
    ProfileChanges,
    ProfileExistsError,
    ProfileFields,
    ProfileValidationError,
    TutorClosedError,
    TutorProfileRepository,
    TutorSuspendedError,
)
from tests.test_tutor_directory_repo import (
    add_subject,
    add_tutor,
    add_user,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


def fields(subject: str, **overrides: object) -> ProfileFields:
    values: dict[str, object] = {
        "public_first_name": "Sara",
        "public_last_initial": "M",
        "headline": "IGCSE Mathematics, exam focused",
        "bio": "",
        "qualification_note": None,
        "subject_codes": (subject,),
        "offers_virtual": True,
        "offers_in_person": False,
        "offers_other": False,
        "other_mode_note": None,
        "area_code": "cairo",
    }
    values.update(overrides)
    return ProfileFields(**values)  # type: ignore[arg-type]


def _state(sm: sessionmaker[Session], profile_id: uuid.UUID) -> TutorProfile:
    with sm() as session:
        profile = session.get(TutorProfile, profile_id)
        assert profile is not None
        return profile


def _rules(sm: sessionmaker[Session], profile_id: uuid.UUID) -> list[tuple[int, int, int]]:
    with sm() as session:
        rows = session.execute(
            sa.text(
                "SELECT iso_weekday, start_minute, end_minute FROM tutor_availability_rules "
                "WHERE tutor_profile_id = :p ORDER BY iso_weekday, start_minute"
            ),
            {"p": profile_id},
        ).all()
    return [tuple(row) for row in rows]


# ---------------------------------------------------------------------------
# Create (T2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", [Role.student, Role.parent, Role.school_admin, Role.platform_admin]
)
def test_create_requires_teacher_role(sm: sessionmaker[Session], role: Role) -> None:
    repo = TutorProfileRepository(sm)
    subject = add_subject(sm)
    user = add_user(sm, role)
    with pytest.raises(NotATeacherError) as excinfo:
        repo.create(user, fields(subject))
    assert excinfo.value.code == "not_a_teacher"
    assert repo.for_user(user) is None

    teacher = add_user(sm, Role.teacher)
    row = repo.create(teacher, fields(subject))
    assert row.user_id == teacher
    assert row.listing_state is TutorListingState.draft
    assert row.indexable is True
    assert row.zone == "Africa/Cairo"
    assert repo.for_user(teacher) == row
    assert repo.get(row.id) == row


def test_create_twice_raises_profile_exists(sm: sessionmaker[Session]) -> None:
    repo = TutorProfileRepository(sm)
    subject = add_subject(sm)
    teacher = add_user(sm, Role.teacher)
    repo.create(teacher, fields(subject))
    with pytest.raises(ProfileExistsError) as excinfo:
        repo.create(teacher, fields(subject))
    assert excinfo.value.code == "profile_exists"


@pytest.mark.parametrize(
    ("overrides", "code", "field"),
    [
        ({"public_first_name": "Sara1"}, "invalid_public_name", "public_first_name"),
        ({"public_first_name": "sara.example"}, "invalid_public_name", "public_first_name"),
        ({"public_last_initial": "7"}, "invalid_public_name", "public_last_initial"),
        ({"headline": "Call 01012345678"}, "contact_details_not_allowed", "headline"),
        ({"bio": "Email me at sara@example.com"}, "contact_details_not_allowed", "bio"),
        ({"headline": "   "}, "invalid_profile", "headline"),
        ({"headline": "x" * 161}, "invalid_profile", "headline"),
        ({"bio": "x" * 2001}, "invalid_profile", "bio"),
        ({"qualification_note": "x" * 1001}, "invalid_profile", "qualification_note"),
        ({"area_code": "atlantis"}, "invalid_area", "area_code"),
        ({"subject_codes": ("NOPE",)}, "invalid_subjects", "subject_codes"),
        ({"subject_codes": ()}, "invalid_subjects", "subject_codes"),
        (
            {"offers_virtual": False, "offers_in_person": False, "offers_other": False},
            "invalid_modes",
            "offers_other",
        ),
        ({"other_mode_note": "At a library"}, "invalid_modes", "other_mode_note"),
    ],
)
def test_create_validates_fields(
    sm: sessionmaker[Session], overrides: dict[str, object], code: str, field: str
) -> None:
    repo = TutorProfileRepository(sm)
    subject = add_subject(sm)
    teacher = add_user(sm, Role.teacher)
    with pytest.raises(ProfileValidationError) as excinfo:
        repo.create(teacher, fields(subject, **overrides))
    assert (excinfo.value.code, excinfo.value.field) == (code, field)
    assert repo.for_user(teacher) is None


def test_create_caps_subjects_at_ten(sm: sessionmaker[Session]) -> None:
    repo = TutorProfileRepository(sm)
    codes = tuple(add_subject(sm, name=f"Subject {n}") for n in range(11))
    teacher = add_user(sm, Role.teacher)
    with pytest.raises(ProfileValidationError) as excinfo:
        repo.create(teacher, fields(codes[0], subject_codes=codes))
    assert excinfo.value.code == "invalid_subjects"
    row = repo.create(teacher, fields(codes[0], subject_codes=codes[:10]))
    view = repo.own_profile(row.id)
    assert view is not None
    assert len(view.profile.card.subjects) == 10


# ---------------------------------------------------------------------------
# Edit (T3): moderation, toggles, suspended/closed
# ---------------------------------------------------------------------------

_MODERATED_EDITS = {
    "public_first_name": "Mona",
    "public_last_initial": "K",
    "headline": "A different headline",
    "bio": "A new bio paragraph.",
    "qualification_note": "Cambridge trained",
    "other_mode_note": "Small groups at a library",
}


def test_moderated_field_list_is_the_spec_list() -> None:
    """SPEC §a.3 "listed -> pending_review" row, with SC-7's `other_mode_note`."""
    assert set(MODERATED_FIELDS) == set(_MODERATED_EDITS)


@pytest.mark.parametrize("field", sorted(_MODERATED_EDITS))
def test_moderated_field_edit_sends_listed_profile_to_review(
    sm: sessionmaker[Session], field: str
) -> None:
    repo = TutorProfileRepository(sm)
    tutor = add_tutor(sm, modes=("virtual", "other"), subjects=(add_subject(sm),))
    before = _state(sm, tutor.profile_id)

    row, re_review = repo.update(
        tutor.profile_id, ProfileChanges(**{field: _MODERATED_EDITS[field]})
    )

    assert re_review is True
    assert row.listing_state is TutorListingState.pending_review
    after = _state(sm, tutor.profile_id)
    assert after.listing_state is TutorListingState.pending_review
    assert getattr(after, field) == _MODERATED_EDITS[field]
    assert after.submitted_at is not None
    assert before.submitted_at is not None
    assert after.submitted_at > before.submitted_at
    # The first approval is never reset (F10).
    assert after.first_listed_at == before.first_listed_at


def test_unchanged_or_unmoderated_edit_keeps_listed_profile_listed(
    sm: sessionmaker[Session],
) -> None:
    repo = TutorProfileRepository(sm)
    maths, physics = add_subject(sm), add_subject(sm, name="Physics")
    tutor = add_tutor(sm, subjects=(maths,), headline="Same headline")

    same, re_review = repo.update(tutor.profile_id, ProfileChanges(headline="  Same headline "))
    assert re_review is False
    assert same.listing_state is TutorListingState.listed

    moved, re_review = repo.update(
        tutor.profile_id,
        ProfileChanges(subject_codes=(maths, physics), area_code="giza", offers_in_person=True),
    )
    assert re_review is False
    assert moved.listing_state is TutorListingState.listed
    after = _state(sm, tutor.profile_id)
    assert (after.area_code, after.offers_in_person) == ("giza", True)


def test_moderated_edit_on_a_draft_stays_draft(sm: sessionmaker[Session]) -> None:
    repo = TutorProfileRepository(sm)
    tutor = add_tutor(sm, state="draft", subjects=(add_subject(sm),))
    row, re_review = repo.update(tutor.profile_id, ProfileChanges(headline="New headline"))
    assert re_review is False
    assert row.listing_state is TutorListingState.draft


def test_indexable_change_does_not_send_profile_back_to_review(sm: sessionmaker[Session]) -> None:
    repo = TutorProfileRepository(sm)
    tutor = add_tutor(sm, subjects=(add_subject(sm),))

    row, re_review = repo.update(tutor.profile_id, ProfileChanges(indexable=False))
    assert re_review is False
    assert row.indexable is False
    assert row.listing_state is TutorListingState.listed

    row, re_review = repo.update(tutor.profile_id, ProfileChanges(paused=True))
    assert re_review is False
    assert row.paused_at is not None
    assert row.listing_state is TutorListingState.listed

    row, _ = repo.update(tutor.profile_id, ProfileChanges(paused=False, indexable=True))
    assert row.paused_at is None
    assert row.indexable is True
    assert _state(sm, tutor.profile_id).listing_state is TutorListingState.listed


@pytest.mark.parametrize("field", ["headline", "bio", "public_first_name", "paused", "indexable"])
def test_null_for_a_required_field_is_refused(sm: sessionmaker[Session], field: str) -> None:
    repo = TutorProfileRepository(sm)
    tutor = add_tutor(sm, subjects=(add_subject(sm),))
    with pytest.raises(ProfileValidationError) as excinfo:
        repo.update(tutor.profile_id, ProfileChanges(**{field: None}))
    assert excinfo.value.field == field


def test_null_clears_an_optional_field(sm: sessionmaker[Session]) -> None:
    repo = TutorProfileRepository(sm)
    tutor = add_tutor(sm, state="draft", subjects=(add_subject(sm),), qualification_note="PGCE")
    repo.update(tutor.profile_id, ProfileChanges(qualification_note=None, public_last_initial=None))
    after = _state(sm, tutor.profile_id)
    assert after.qualification_note is None
    assert after.public_last_initial is None


def test_edit_validates_contact_details(sm: sessionmaker[Session]) -> None:
    repo = TutorProfileRepository(sm)
    tutor = add_tutor(sm, modes=("other",), subjects=(add_subject(sm),))
    with pytest.raises(ProfileValidationError) as excinfo:
        repo.update(tutor.profile_id, ProfileChanges(other_mode_note="WhatsApp 01112223334"))
    assert (excinfo.value.code, excinfo.value.field) == (
        "contact_details_not_allowed",
        "other_mode_note",
    )
    assert _state(sm, tutor.profile_id).listing_state is TutorListingState.listed


@pytest.mark.parametrize(
    ("state", "error", "code"),
    [
        ("suspended", TutorSuspendedError, "tutor_suspended"),
        ("closed", TutorClosedError, "tutor_closed"),
    ],
)
def test_edit_suspended_or_closed_409(
    sm: sessionmaker[Session], state: str, error: type[Exception], code: str
) -> None:
    repo = TutorProfileRepository(sm)
    tutor = add_tutor(sm, state=state, subjects=(add_subject(sm),))
    calls = [
        lambda: repo.update(tutor.profile_id, ProfileChanges(headline="Back again")),
        lambda: repo.update(tutor.profile_id, ProfileChanges(indexable=False)),
        lambda: repo.replace_availability(tutor.profile_id, [AvailabilityRule(1, 540, 600)]),
        lambda: repo.submit(tutor.profile_id),
    ]
    for call in calls:
        with pytest.raises(error) as excinfo:
            call()
        assert excinfo.value.code == code  # type: ignore[attr-defined]
    after = _state(sm, tutor.profile_id)
    assert after.listing_state is TutorListingState(state)
    assert after.headline != "Back again"
    assert after.indexable is True
    assert _rules(sm, tutor.profile_id) == [(4, 1020, 1200)]


# ---------------------------------------------------------------------------
# Availability (T5)
# ---------------------------------------------------------------------------


def test_availability_replace_maps_overlap_to_422_code(sm: sessionmaker[Session]) -> None:
    repo = TutorProfileRepository(sm)
    tutor = add_tutor(sm, subjects=(add_subject(sm),))
    with pytest.raises(ProfileValidationError) as excinfo:
        repo.replace_availability(
            tutor.profile_id, [AvailabilityRule(1, 600, 720), AvailabilityRule(1, 660, 780)]
        )
    assert excinfo.value.code == "overlapping_rules"
    assert _rules(sm, tutor.profile_id) == [(4, 1020, 1200)]

    stored = repo.replace_availability(
        tutor.profile_id,
        [
            AvailabilityRule(3, 600, 720),
            AvailabilityRule(1, 720, 780),
            AvailabilityRule(1, 600, 720),
        ],
    )
    assert [(r.iso_weekday, r.start_minute, r.end_minute) for r in stored] == [
        (1, 600, 720),
        (1, 720, 780),
        (3, 600, 720),
    ]
    assert _rules(sm, tutor.profile_id) == [(1, 600, 720), (1, 720, 780), (3, 600, 720)]

    assert repo.replace_availability(tutor.profile_id, []) == ()
    assert _rules(sm, tutor.profile_id) == []


def test_availability_replace_refuses_bad_rules_and_too_many(sm: sessionmaker[Session]) -> None:
    repo = TutorProfileRepository(sm)
    tutor = add_tutor(sm, subjects=(add_subject(sm),))
    with pytest.raises(ProfileValidationError) as excinfo:
        repo.replace_availability(tutor.profile_id, [AvailabilityRule(8, 600, 720)])
    assert excinfo.value.code == "invalid_rules"
    with pytest.raises(ProfileValidationError) as excinfo:
        repo.replace_availability(tutor.profile_id, [AvailabilityRule(1, 610, 720)])
    assert excinfo.value.code == "invalid_rules"
    many = [
        AvailabilityRule(day, start, start + 15)
        for day in range(1, 8)
        for start in range(0, 105, 15)
    ]
    assert len(many) == 49
    with pytest.raises(ProfileValidationError) as excinfo:
        repo.replace_availability(tutor.profile_id, many)
    assert excinfo.value.code == "invalid_rules"
    assert len(repo.replace_availability(tutor.profile_id, many[:42])) == 42


# ---------------------------------------------------------------------------
# Submit (T4)
# ---------------------------------------------------------------------------


def test_submit_requires_complete_profile_and_verified_email(sm: sessionmaker[Session]) -> None:
    repo = TutorProfileRepository(sm)
    subject = add_subject(sm)
    tutor = add_tutor(sm, state="draft", subjects=(), rules=(), verified=False)

    with pytest.raises(EmailUnverifiedError) as unverified:
        repo.submit(tutor.profile_id)
    assert unverified.value.code == "email_unverified"
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE users SET email_verified_at = now() WHERE id = :u"),
            {"u": tutor.user_id},
        )

    with pytest.raises(IncompleteProfileError) as incomplete:
        repo.submit(tutor.profile_id)
    assert incomplete.value.code == "incomplete_profile"
    assert set(incomplete.value.missing) == {"subjects", "availability"}

    repo.update(tutor.profile_id, ProfileChanges(subject_codes=(subject,)))
    with pytest.raises(IncompleteProfileError) as incomplete:
        repo.submit(tutor.profile_id)
    assert incomplete.value.missing == ("availability",)
    assert _state(sm, tutor.profile_id).listing_state is TutorListingState.draft

    repo.replace_availability(tutor.profile_id, [AvailabilityRule(2, 600, 720)])
    row = repo.submit(tutor.profile_id)
    assert row.listing_state is TutorListingState.pending_review
    assert _state(sm, tutor.profile_id).submitted_at is not None

    with pytest.raises(IllegalTransitionError) as illegal:
        repo.submit(tutor.profile_id)
    assert illegal.value.code == "illegal_transition"


@pytest.mark.parametrize(("state", "allowed"), [("rejected", True), ("listed", False)])
def test_submit_from_rejected_only_besides_draft(
    sm: sessionmaker[Session], state: str, allowed: bool
) -> None:
    repo = TutorProfileRepository(sm)
    tutor = add_tutor(sm, state=state, subjects=(add_subject(sm),))
    if allowed:
        assert repo.submit(tutor.profile_id).listing_state is TutorListingState.pending_review
    else:
        with pytest.raises(IllegalTransitionError):
            repo.submit(tutor.profile_id)


# ---------------------------------------------------------------------------
# The own-profile read model (T1)
# ---------------------------------------------------------------------------


def test_own_profile_reads_state_evidence_and_review_note(sm: sessionmaker[Session]) -> None:
    repo = TutorProfileRepository(sm)
    tutor = add_tutor(sm, state="rejected", subjects=(add_subject(sm),), indexable=False)
    admin = add_user(sm, Role.platform_admin)
    with sm.begin() as session:
        session.add(
            TutorEvidenceFile(
                tutor_profile_id=tutor.profile_id,
                storage_path=f"tutor-evidence/{tutor.profile_id}/{uuid.uuid4()}.pdf",
                original_filename="certificate.pdf",
                content_type="application/pdf",
                size_bytes=1234,
                description="PGCE certificate",
            )
        )
        session.add(
            TutorApprovalEvent(
                tutor_profile_id=tutor.profile_id,
                admin_user_id=admin,
                decision=TutorApprovalDecision.rejected,
                note="Please describe your teaching experience.",
                profile_snapshot={},
            )
        )
    view = repo.own_profile(tutor.profile_id)
    assert view is not None
    assert view.listing_state is TutorListingState.rejected
    assert view.indexable is False
    assert view.paused is False
    assert view.review_note == "Please describe your teaching experience."
    assert [(e.filename, e.size_bytes, e.description) for e in view.evidence] == [
        ("certificate.pdf", 1234, "PGCE certificate")
    ]
    assert view.profile.card.tutor_id == tutor.profile_id


def test_own_profile_hides_internal_approval_notes(sm: sessionmaker[Session]) -> None:
    """Only a rejection or suspension note reaches the tutor (SPEC §a.2 approval events)."""
    repo = TutorProfileRepository(sm)
    tutor = add_tutor(sm, subjects=(add_subject(sm),))
    with sm.begin() as session:
        session.add(
            TutorApprovalEvent(
                tutor_profile_id=tutor.profile_id,
                decision=TutorApprovalDecision.approved,
                note="Internal: checked references by phone.",
                profile_snapshot={},
            )
        )
    view = repo.own_profile(tutor.profile_id)
    assert view is not None
    assert view.review_note is None
