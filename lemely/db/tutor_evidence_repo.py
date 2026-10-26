"""Tutor evidence files and the admin's evidence-open log (SPEC §a.2, §b.2 T6/T7/A2, SC-22, SC-23).

The single writer of ``tutor_evidence_files`` and of the ``evidence_open`` rows
of ``tutoring_admin_access`` (PLAN §1.4 #2). Bytes never pass through here: the
route checks and re-encodes them (:mod:`lemely.io.evidence_files`) and stores the
object; this module records it.

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
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa

from lemely.core.contact_patterns import find_contact_details
from lemely.db.models.enums import TutoringAdminAction, TutorListingState
from lemely.db.models.tutoring import TutorEvidenceFile, TutoringAdminAccess, TutorProfile
from lemely.db.tutor_profile_repo import (
    EvidenceFile,
    ProfileNotFoundError,
    TutorClosedError,
    TutorSuspendedError,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

#: SPEC §a.2 / SC-22: at most five files per tutor.
MAX_EVIDENCE_FILES: Final = 5
#: ``tutor_evidence_files.description`` is varchar(200).
MAX_DESCRIPTION_LENGTH: Final = 200


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
    "MAX_DESCRIPTION_LENGTH",
    "MAX_EVIDENCE_FILES",
    "EvidenceError",
    "EvidenceLimitError",
    "EvidenceNotFoundError",
    "EvidenceValidationError",
    "IssuedEvidence",
    "StoredEvidence",
    "TutorEvidenceRepository",
    "clean_description",
]
