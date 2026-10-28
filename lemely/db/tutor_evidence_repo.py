"""Tutor evidence files and the admin's evidence-open log (SPEC §a.2, §b.2 T6/T7/A2, SC-22, SC-23).

The single writer of ``tutor_evidence_files``, of ``tutor_evidence_uploads`` and
of the ``evidence_open`` rows of ``tutoring_admin_access`` (PLAN §1.4 #2). Bytes
never pass through here: the route checks and re-encodes them
(:mod:`lemely.io.evidence_files`) and stores the object; this module records it.

* **Upload attempts are a quota (T30 F30-5).** Each T6 check holds the extraction
  worker that marking shares, so :meth:`TutorEvidenceRepository.record_upload_attempt`
  runs first and commits one ``tutor_evidence_uploads`` row before the check: an
  attempt the check refuses still counts, and a T7 delete (which removes the
  ``tutor_evidence_files`` row only) gives none back. Past
  :data:`UPLOAD_ATTEMPT_QUOTA` attempts in 24 elapsed hours (the SC-15 window of
  the booking and report quotas) T6 is 429 ``too_many_requests`` and nothing is
  recorded. The profile's advisory lock (:func:`_lock_upload_attempts`) is taken
  before the count, so two attempts never both count below the quota.
* **And the platform has a ceiling (Wave 8 review finding 2).** Teacher signup is
  not verified, so throwaway accounts would multiply the per-profile quota. Past
  :data:`GLOBAL_UPLOAD_ATTEMPT_CEILING` attempts from every profile together in
  :data:`GLOBAL_UPLOAD_WINDOW_SECONDS` of elapsed time T6 is the same 429, raised as
  :class:`EvidenceCeilingError`, and nothing is recorded, so a refused attempt
  takes nothing from its profile's quota either. One global advisory lock
  (:func:`_lock_global_upload_attempts`) is taken before the profile's.

* **Writes are one transaction each** and lock the profile row first
  (``SELECT ... FOR UPDATE``, SPEC §a.4b order), so the five-file limit and the
  listing state are re-checked against concurrent uploads and a suspension that
  committed after the route's guard: a suspended or closed profile is refused
  with ``tutor_suspended`` / ``tutor_closed`` (CB-7).
* **Scoped by the caller's profile (O20).** Every read and delete is
  ``WHERE tutor_profile_id = :profile``; another tutor's evidence id is
  indistinguishable from an unknown one.
* **"Documents seen" means only this** (F14): any upload or delete clears
  ``tutor_profiles.documents_seen_at``, in the same transaction.
* **Admin access is logged where the URL is issued (SC-23).** :meth:`issue_admin_urls`
  signs each file's URL and writes one ``evidence_open`` row per URL, in one
  transaction; if a row cannot be written the transaction fails and no URL is
  returned. A file the storage backend cannot sign gets no URL and no row.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa

from lemely.core.contact_patterns import find_contact_details
from lemely.db.booking_repo import QUOTA_BINDS, QUOTA_SINCE_SQL
from lemely.db.models.enums import TutoringAdminAction, TutorListingState
from lemely.db.models.tutoring import (
    TutorEvidenceFile,
    TutorEvidenceUpload,
    TutoringAdminAccess,
    TutorProfile,
)
from lemely.db.tutor_profile_repo import (
    EvidenceFile,
    ProfileNotFoundError,
    TutorClosedError,
    TutorSuspendedError,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable, Mapping
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

#: SPEC §a.2 / SC-22: at most five files per tutor.
MAX_EVIDENCE_FILES: Final = 5
#: ``tutor_evidence_files.description`` is varchar(200).
MAX_DESCRIPTION_LENGTH: Final = 200
#: T30 F30-5: at most this many T6 upload attempts per tutor profile in 24 elapsed hours.
UPLOAD_ATTEMPT_QUOTA: Final = 20
#: Wave 8 review finding 2: at most this many T6 upload attempts from every tutor
#: profile together in any :data:`GLOBAL_UPLOAD_WINDOW_SECONDS` of elapsed time.
GLOBAL_UPLOAD_ATTEMPT_CEILING: Final = 200
#: The ceiling's window: 60 elapsed minutes, in seconds.
GLOBAL_UPLOAD_WINDOW_SECONDS: Final = 60 * 60
#: Seconds until the oldest attempt in the window leaves it, rounded up. Bound like
#: :data:`~lemely.db.booking_repo.QUOTA_SINCE_SQL` (elapsed seconds, never a ``timedelta``).
_RETRY_AFTER_SQL: Final = (
    "ceil(EXTRACT(EPOCH FROM (min(created_at) "
    "+ make_interval(secs => CAST(:quota_window_s AS double precision)) - now())))"
)
#: The profile's attempts in the last 24 elapsed hours, and its Retry-After.
_PROFILE_ATTEMPTS_SQL: Final = (
    f"SELECT count(*), {_RETRY_AFTER_SQL} FROM tutor_evidence_uploads "  # noqa: S608 - constants
    f"WHERE tutor_profile_id = :p AND created_at > {QUOTA_SINCE_SQL}"
)
#: Every profile's attempts in the ceiling's window, and its Retry-After: the
#: profile's statement without the profile, over the window :data:`_GLOBAL_BINDS` binds.
#:
#: Expected cost: no index leads with ``created_at`` (the one index,
#: ``ix_tutor_evidence_uploads_profile_day``, is ``(tutor_profile_id, created_at)``),
#: so this reads the whole append-only table, by a sequential scan or a full scan of
#: that index, on every T6 attempt and under the global lock. The ceiling bounds how
#: fast it grows: at most 4,800 rows a day, about 1.75 M in a year of the ceiling
#: every hour. Measured 2026-10-27 (Postgres 17, warm cache, sequential scan): 0.3 ms
#: at 5,000 rows, 7 ms at 100,000, 47 ms at 1.75 M (208 MB). No index is added
#: (no migration): one on ``created_at``, or pruning rows older than 24 hours, is the
#: remedy if the table nears a million rows.
_GLOBAL_ATTEMPTS_SQL: Final = (
    f"SELECT count(*), {_RETRY_AFTER_SQL} FROM tutor_evidence_uploads "  # noqa: S608 - constants
    f"WHERE created_at > {QUOTA_SINCE_SQL}"
)
_GLOBAL_BINDS: Final[Mapping[str, object]] = MappingProxyType(
    {"quota_window_s": float(GLOBAL_UPLOAD_WINDOW_SECONDS)}
)
_QUOTA_MESSAGE: Final = "That is happening too often. Try again in a little while."


class EvidenceError(Exception):
    """Base class: ``code`` is the stable API code, ``message`` plain English."""

    code: str = "evidence_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EvidenceLimitError(EvidenceError):
    """The tutor already has :data:`MAX_EVIDENCE_FILES` files (409)."""

    code = "evidence_limit"


class EvidenceNotFoundError(EvidenceError):
    """No such evidence file on the caller's profile (404, O20)."""

    code = "evidence_not_found"


class EvidenceQuotaError(EvidenceError):
    """Past :data:`UPLOAD_ATTEMPT_QUOTA` T6 attempts in 24 elapsed hours (429, F30-5).

    ``retry_after`` is the whole seconds until the oldest counted attempt leaves
    the window, so one more attempt is admitted then.
    """

    code = "too_many_requests"

    def __init__(self, message: str, *, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class EvidenceCeilingError(EvidenceQuotaError):
    """Past :data:`GLOBAL_UPLOAD_ATTEMPT_CEILING` T6 attempts on the platform (429, finding 2).

    The same answer as the profile's quota (``retry_after`` is when the oldest
    attempt counted leaves :data:`GLOBAL_UPLOAD_WINDOW_SECONDS`); its own type only
    so that the route can log that every tutor is being refused.
    """


class EvidenceValidationError(EvidenceError):
    """The description failed validation (422); ``field`` is the snake_case field."""

    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


@dataclass(frozen=True, slots=True)
class StoredEvidence:
    """An evidence file with its storage path: admin and storage use only, never serialised."""

    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    description: str | None
    uploaded_at: datetime
    storage_path: str

    def metadata(self) -> EvidenceFile:
        """The file without its path (what a DTO may carry)."""
        return EvidenceFile(
            id=self.id,
            filename=self.filename,
            content_type=self.content_type,
            size_bytes=self.size_bytes,
            description=self.description,
            uploaded_at=self.uploaded_at,
        )


@dataclass(frozen=True, slots=True)
class IssuedEvidence:
    """A file and the URL issued for it on A2, or ``None`` when it could not be signed."""

    evidence: StoredEvidence
    signed_url: str | None


def clean_description(value: str | None) -> str | None:
    """The description to store: stripped, at most 200 characters, no contact details (SC-7).

    Blank means none. Raises :class:`EvidenceValidationError`.
    """
    if value is None or not value.strip():
        return None
    text = value.strip()
    if len(text) > MAX_DESCRIPTION_LENGTH:
        raise EvidenceValidationError(
            "invalid_description",
            "description",
            f"Keep the description to {MAX_DESCRIPTION_LENGTH} characters.",
        )
    if find_contact_details(text):
        raise EvidenceValidationError(
            "contact_details_not_allowed",
            "description",
            "Keep contact details off your profile: students reach you through Lemely.",
        )
    return text


def _stored(model: TutorEvidenceFile) -> StoredEvidence:
    return StoredEvidence(
        id=model.id,
        filename=model.original_filename,
        content_type=model.content_type,
        size_bytes=model.size_bytes,
        description=model.description,
        uploaded_at=model.created_at,
        storage_path=model.storage_path,
    )


def _lock_writable(session: Session, profile_id: uuid.UUID) -> TutorProfile:
    """Lock the profile row and refuse a suspended or closed one (SPEC §a.4b, CB-7)."""
    profile = session.get(TutorProfile, profile_id, with_for_update=True)
    if profile is None:
        raise ProfileNotFoundError("No tutor profile.")
    if profile.listing_state is TutorListingState.suspended:
        raise TutorSuspendedError("Your tutor profile is suspended.")
    if profile.listing_state is TutorListingState.closed:
        raise TutorClosedError("Your tutor profile is closed.")
    return profile


def _lock_global_upload_attempts(session: Session) -> None:
    """The attempt transaction's first statement: the platform's advisory lock (finding 2).

    ``pg_advisory_xact_lock(hashtextextended('tutoring_evidence_upload_global', 0))``
    serialises every T6 attempt on the platform, so two attempts of different
    profiles never both count one below :data:`GLOBAL_UPLOAD_ATTEMPT_CEILING`. It is a
    single serialising key, but it is held only for the count and the insert (two
    counts, one insert, then commit), never while the file is read or checked, so
    attempts queue on it for milliseconds. Only
    :meth:`TutorEvidenceRepository.record_upload_attempt` takes it, before the
    profile's key and with no other lock held, so it cannot form a cycle with the
    SPEC §a.4b order.
    """
    session.execute(
        sa.text(
            "SELECT pg_advisory_xact_lock(hashtextextended('tutoring_evidence_upload_global', 0))"
        )
    )


def _lock_upload_attempts(session: Session, profile_id: uuid.UUID) -> None:
    """The attempt transaction's second statement: the profile's advisory lock (F30-5).

    ``pg_advisory_xact_lock(hashtextextended('tutoring_evidence_upload:' || tutor_profile_id,
    0))`` serialises one profile's attempts, so the quota COUNT and the INSERT of two
    of them never interleave. Only :meth:`TutorEvidenceRepository.record_upload_attempt`
    takes this key, after the global one and before any tutoring lock, so it cannot
    form a cycle with the SPEC §a.4b order.
    """
    session.execute(
        sa.text(
            "SELECT pg_advisory_xact_lock(hashtextextended("
            "'tutoring_evidence_upload:' || CAST(CAST(:p AS uuid) AS text), 0))"
        ),
        {"p": profile_id},
    )


def _retry_after_at(
    session: Session, counted_sql: str, binds: Mapping[str, object], limit: int
) -> int | None:
    """``Retry-After`` seconds once ``counted_sql`` counts ``limit`` attempts, else ``None``.

    ``counted_sql`` is :data:`_PROFILE_ATTEMPTS_SQL` or :data:`_GLOBAL_ATTEMPTS_SQL`:
    the attempts in a window and the seconds until the oldest of them leaves it (at
    least 1).
    """
    held, retry_after = session.execute(sa.text(counted_sql), binds).one()
    if int(held) < limit:
        return None
    return max(1, int(retry_after))


def _files(session: Session, profile_id: uuid.UUID) -> list[TutorEvidenceFile]:
    return list(
        session.scalars(
            sa.select(TutorEvidenceFile)
            .where(TutorEvidenceFile.tutor_profile_id == profile_id)
            .order_by(TutorEvidenceFile.created_at, TutorEvidenceFile.id)
        )
    )


class TutorEvidenceRepository:
    """Evidence reads and writes over a ``sessionmaker``."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the repository to a session factory."""
        self._sessionmaker = sessionmaker

    def count(self, profile_id: uuid.UUID) -> int:
        """How many files the profile has (the route's cheap pre-check before storing bytes)."""
        with self._sessionmaker() as session:
            total = session.scalar(
                sa.select(sa.func.count())
                .select_from(TutorEvidenceFile)
                .where(TutorEvidenceFile.tutor_profile_id == profile_id)
            )
            return int(total or 0)

    def record_upload_attempt(self, profile_id: uuid.UUID) -> None:
        """T6's first step: count this attempt and commit it before the file is checked.

        Under the global advisory lock and then the profile's, counts the profile's
        ``tutor_evidence_uploads`` rows newer than 24 elapsed hours before ``now()``,
        then every profile's rows newer than :data:`GLOBAL_UPLOAD_WINDOW_SECONDS`. At
        :data:`UPLOAD_ATTEMPT_QUOTA` raises :class:`EvidenceQuotaError`, at
        :data:`GLOBAL_UPLOAD_ATTEMPT_CEILING` :class:`EvidenceCeilingError`, and
        records nothing; otherwise inserts one row, committed when this returns.
        """
        with self._sessionmaker.begin() as session:
            _lock_global_upload_attempts(session)
            _lock_upload_attempts(session, profile_id)
            retry_after = _retry_after_at(
                session,
                _PROFILE_ATTEMPTS_SQL,
                {**QUOTA_BINDS, "p": profile_id},
                UPLOAD_ATTEMPT_QUOTA,
            )
            if retry_after is not None:
                raise EvidenceQuotaError(_QUOTA_MESSAGE, retry_after=retry_after)
            retry_after = _retry_after_at(
                session, _GLOBAL_ATTEMPTS_SQL, _GLOBAL_BINDS, GLOBAL_UPLOAD_ATTEMPT_CEILING
            )
            if retry_after is not None:
                raise EvidenceCeilingError(_QUOTA_MESSAGE, retry_after=retry_after)
            session.execute(sa.insert(TutorEvidenceUpload).values(tutor_profile_id=profile_id))

    def add(
        self,
        profile_id: uuid.UUID,
        *,
        evidence_id: uuid.UUID,
        storage_path: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        description: str | None,
    ) -> EvidenceFile:
        """T6: record a stored object and clear "documents seen".

        Raises :class:`EvidenceLimitError`, or ``TutorSuspendedError``,
        ``TutorClosedError`` or ``ProfileNotFoundError`` from
        :mod:`lemely.db.tutor_profile_repo`; the caller then deletes the object it
        stored.
        """
        with self._sessionmaker.begin() as session:
            profile = _lock_writable(session, profile_id)
            held = session.scalar(
                sa.select(sa.func.count())
                .select_from(TutorEvidenceFile)
                .where(TutorEvidenceFile.tutor_profile_id == profile_id)
            )
            if int(held or 0) >= MAX_EVIDENCE_FILES:
                raise EvidenceLimitError(
                    f"You can keep at most {MAX_EVIDENCE_FILES} files. Delete one first."
                )
            row = TutorEvidenceFile(
                id=evidence_id,
                tutor_profile_id=profile_id,
                storage_path=storage_path,
                original_filename=filename,
                content_type=content_type,
                size_bytes=size_bytes,
                description=description,
            )
            session.add(row)
            profile.documents_seen_at = None
            session.flush()
            session.refresh(row)
            return _stored(row).metadata()

    def delete(self, profile_id: uuid.UUID, evidence_id: uuid.UUID) -> str:
        """T7: delete the caller's file and clear "documents seen"; returns its storage path.

        The caller removes the object after this returns (the row is committed by
        then). Raises :class:`EvidenceNotFoundError` for an id that is not on this
        profile (O20), or the profile errors of :meth:`add`.
        """
        with self._sessionmaker.begin() as session:
            profile = _lock_writable(session, profile_id)
            path = session.execute(
                sa.delete(TutorEvidenceFile)
                .where(
                    TutorEvidenceFile.id == evidence_id,
                    TutorEvidenceFile.tutor_profile_id == profile_id,
                )
                .returning(TutorEvidenceFile.storage_path)
            ).scalar_one_or_none()
            if path is None:
                raise EvidenceNotFoundError("No such file on your profile.")
            profile.documents_seen_at = None
            return path

    def list_stored(self, profile_id: uuid.UUID) -> tuple[StoredEvidence, ...]:
        """Every file of the profile with its path, oldest first.

        Logs nothing, so no URL may be issued from it: A2 uses :meth:`issue_admin_urls`.
        """
        with self._sessionmaker() as session:
            return tuple(_stored(model) for model in _files(session, profile_id))

    def issue_admin_urls(
        self,
        profile_id: uuid.UUID,
        *,
        admin_user_id: uuid.UUID,
        sign: Callable[[StoredEvidence], str | None],
    ) -> tuple[IssuedEvidence, ...]:
        """A2: sign each file's URL and log one ``evidence_open`` row per URL, in one transaction.

        ``sign`` returns the URL, or ``None`` when the backend could not sign (no
        row then). A failed insert propagates and nothing is returned (SC-23: fail
        closed).
        """
        issued: list[IssuedEvidence] = []
        with self._sessionmaker.begin() as session:
            for model in _files(session, profile_id):
                evidence = _stored(model)
                url = sign(evidence)
                if url is not None:
                    session.add(
                        TutoringAdminAccess(
                            admin_user_id=admin_user_id,
                            action=TutoringAdminAction.evidence_open,
                            tutor_profile_id=profile_id,
                            evidence_id=evidence.id,
                        )
                    )
                    session.flush()
                issued.append(IssuedEvidence(evidence=evidence, signed_url=url))
        return tuple(issued)


__all__ = [
    "GLOBAL_UPLOAD_ATTEMPT_CEILING",
    "GLOBAL_UPLOAD_WINDOW_SECONDS",
    "MAX_DESCRIPTION_LENGTH",
    "MAX_EVIDENCE_FILES",
    "UPLOAD_ATTEMPT_QUOTA",
    "EvidenceCeilingError",
    "EvidenceError",
    "EvidenceLimitError",
    "EvidenceNotFoundError",
    "EvidenceQuotaError",
    "EvidenceValidationError",
    "IssuedEvidence",
    "StoredEvidence",
    "TutorEvidenceRepository",
    "clean_description",
]
