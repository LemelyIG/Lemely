"""Student upload persistence for the self-mark flow (P2.1).

A student's scan (+ optional mark scheme) is uploaded to object storage
(:mod:`lemely.io.storage` — Google Cloud Storage in a deployment) by the
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
    from datetime import datetime

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


@dataclass(frozen=True, slots=True)
class UploadRun:
    """A detached snapshot of what a *reader* needs to know about an upload.

    Distinct from :class:`OwnedUpload`, which carries what the marking pipeline
    needs to *do the work* (a storage key). This carries what a student's screen
    needs to answer "what is happening to my paper" after the browser that
    started the run has gone away.

    ``started_at`` is the row's ``updated_at``, which is the moment the status
    last changed. While the status is ``processing`` that is exactly the moment
    marking began, because ``processing`` is written once, at the top of the
    run. It is meaningless for the other three states and is not read for them.
    """

    id: uuid.UUID
    status: UploadStatus
    original_filename: str | None
    started_at: datetime


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

    def get_run(self, *, user_id: str, upload_id: str) -> UploadRun | None:
        """Return the caller-owned upload's *run state*, or ``None`` if foreign.

        Same ownership and malformed-id handling as :meth:`get_owned_upload`,
        for the same reason: a uniform ``None`` gives the router one 404 to
        return and no ownership oracle.
        """
        owner = parse_user_id(user_id)
        try:
            target = uuid.UUID(upload_id)
        except (ValueError, AttributeError, TypeError):
            return None
        stmt = select(Upload).where(Upload.id == target, Upload.user_id == owner)
        with self._sm() as session:
            upload = session.scalars(stmt).one_or_none()
            return None if upload is None else _to_run(upload)

    def get_active_run(self, *, user_id: str) -> UploadRun | None:
        """Return this student's marking run that is still going, if any.

        ``processing`` only, deliberately — **not** ``pending``. A ``pending``
        upload is a scan that was stored and never marked, which is what a
        student produces every time they choose a file and then change their
        mind. Counting those as "still going" is how you get a queue depth that
        only ever grows; see the note on :meth:`set_status`.

        Ordered newest-first and limited to one. More than one row can be
        ``processing`` only if a previous run's process died before writing a
        terminal status, and in that case the newest is the one the student is
        actually waiting on; the older ones are stale and answer as such through
        :meth:`get_run`.
        """
        owner = parse_user_id(user_id)
        stmt = (
            select(Upload)
            .where(Upload.user_id == owner, Upload.status == UploadStatus.processing)
            .order_by(Upload.updated_at.desc())
            .limit(1)
        )
        with self._sm() as session:
            upload = session.scalars(stmt).one_or_none()
            return None if upload is None else _to_run(upload)

    def set_status(self, upload_id: uuid.UUID, status: UploadStatus) -> None:
        """Update a single upload's processing status.

        ``updated_at`` moves with every call (``TimestampMixin.onupdate``), so
        the write of :attr:`UploadStatus.processing` is also the record of when
        marking started. That is what lets a reload find a run in flight without
        a new column or a job table.
        """
        with self._sm.begin() as session:
            upload = session.get(Upload, upload_id)
            if upload is not None:
                upload.status = status


def _to_run(upload: Upload) -> UploadRun:
    """Detach the reader-facing fields of an :class:`Upload` row."""
    return UploadRun(
        id=upload.id,
        status=upload.status,
        original_filename=upload.original_filename,
        started_at=upload.updated_at,
    )


__all__ = ["OwnedUpload", "StudentUploadRepository", "UploadRun"]
