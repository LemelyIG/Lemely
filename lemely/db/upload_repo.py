"""Student upload persistence for the self-mark flow (P2.1).

A student's scan (+ optional mark scheme) is uploaded to Supabase Storage by the
router (P2.5); this repository owns the :class:`~lemely.db.models.attempts.Upload`
row that records its storage object key, ownership, and processing status.
``storage_path`` holds the Storage object key, not a local filesystem path.
Ownership is always
keyed on the authenticated ``user_id`` — :meth:`get_owned_upload` returns
``None`` for an upload owned by anyone else, so the ``/correct`` endpoint can 404
a foreign paper before streaming.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from lemely.db.history_repo import parse_user_id
from lemely.db.models.attempts import Upload
from lemely.db.models.enums import UploadStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class OwnedUpload:
    """A detached snapshot of the upload fields the correct flow needs.

    Returned instead of a live ORM object so callers never touch an expired /
    session-bound instance after the session has closed.
    """

    id: uuid.UUID
    storage_path: str
    original_filename: str | None


class StudentUploadRepository:
    """CRUD for a student's :class:`Upload` rows, scoped to the owning user."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Bind the repository to a ``sessionmaker`` (one op = one transaction)."""
        self._sm = session_factory

    def create_upload(
        self,
        *,
        user_id: str,
        storage_path: str,
        original_filename: str | None,
        content_type: str | None,
        byte_size: int | None,
        upload_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Insert a pending :class:`Upload` and return its id.

        When ``upload_id`` is supplied it becomes the row's primary key (so the
        router can pre-generate the id, namespace the on-disk directory by it,
        and keep paperId == upload id); otherwise the DB assigns one.
        """
        owner = parse_user_id(user_id)
        upload = Upload(
            user_id=owner,
            storage_path=storage_path,
            original_filename=original_filename,
            content_type=content_type,
            byte_size=byte_size,
            status=UploadStatus.pending,
        )
        if upload_id is not None:
            upload.id = upload_id
        with self._sm.begin() as session:
            session.add(upload)
            session.flush()
            new_id = upload.id
        return new_id

    def get_owned_upload(self, *, user_id: str, upload_id: str) -> OwnedUpload | None:
        """Return the caller-owned upload, or ``None`` if missing or foreign.

        Both a malformed ``upload_id`` and an upload owned by another user yield
        ``None`` so the caller responds with a uniform 404 (no ownership oracle).
        """
        owner = parse_user_id(user_id)
        try:
            target = uuid.UUID(upload_id)
        except (ValueError, AttributeError, TypeError):
            return None
        stmt = select(Upload).where(Upload.id == target, Upload.user_id == owner)
        with self._sm() as session:
            upload = session.scalars(stmt).one_or_none()
            if upload is None:
                return None
            return OwnedUpload(
                id=upload.id,
                storage_path=upload.storage_path,
                original_filename=upload.original_filename,
            )

    def set_status(self, upload_id: uuid.UUID, status: UploadStatus) -> None:
        """Update a single upload's processing status."""
        with self._sm.begin() as session:
            upload = session.get(Upload, upload_id)
            if upload is not None:
                upload.status = status


__all__ = ["OwnedUpload", "StudentUploadRepository"]
