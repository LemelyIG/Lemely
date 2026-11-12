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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from lemely.db.history_repo import parse_user_id
from lemely.db.models.attempts import Upload
from lemely.db.models.enums import UploadStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker


#: How long a submitted ``Idempotency-Key`` still dedupes a retry. Enforced
#: above ``ux_uploads_user_idempotency`` (migration 0036), which has no time
#: bound of its own — see :meth:`StudentUploadRepository.create_upload`.
IDEMPOTENCY_KEY_WINDOW = timedelta(hours=24)


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
        idempotency_key: str | None = None,
    ) -> uuid.UUID:
        """Insert a pending :class:`Upload` and return its id.

        When ``upload_id`` is supplied it becomes the row's primary key (so the
        router can pre-generate the id, namespace the on-disk directory by it,
        and keep paperId == upload id); otherwise the DB assigns one.

        ``idempotency_key``, when given, is enforced unique per user by
        ``ux_uploads_user_idempotency`` (migration 0036). The router's own
        :meth:`find_by_idempotency_key` pre-check already excludes a match
        older than :data:`IDEMPOTENCY_KEY_WINDOW`, so an ``IntegrityError``
        reaching this insert is one of three things: a genuine concurrent
        duplicate of *this* request, still inside the window (hand back its
        id — closes the race two callers racing with the same key can hit,
        since both can miss the pre-check and both reach here, but only one
        insert can win the unique index); a stale key surviving from a
        prior, now-expired upload, which is released and the insert retried
        once so this upload gets its own new row (and, if a *second*
        concurrent request wins that retry, resolved the same way as the
        first case rather than left to raise); or an unrelated constraint
        violation with nothing to do with the idempotency key, which is
        re-raised as-is.

        Callers that write to another system before calling this (e.g. the
        router uploads the scan to object storage first) must compare the
        returned id against the ``upload_id`` they passed in: a mismatch
        means this call lost an idempotency race and returned an *existing*
        row's id — whatever the caller wrote under its own ``upload_id`` is
        now unreferenced by any row and must be cleaned up.
        """
        owner = parse_user_id(user_id)

        def _new_row() -> Upload:
            row = Upload(
                user_id=owner,
                storage_path=storage_path,
                original_filename=original_filename,
                content_type=content_type,
                byte_size=byte_size,
                status=UploadStatus.pending,
                idempotency_key=idempotency_key,
            )
            if upload_id is not None:
                row.id = upload_id
            return row

        try:
            with self._sm.begin() as session:
                row = _new_row()
                session.add(row)
                session.flush()
                return row.id
        except IntegrityError:
            if idempotency_key is None:
                raise
            since = datetime.now(UTC) - IDEMPOTENCY_KEY_WINDOW
            existing = self.find_by_idempotency_key(
                user_id=user_id, key=idempotency_key, since=since
            )
            if existing is not None:
                return existing.id
            if not self._idempotency_key_row_exists(owner=owner, key=idempotency_key):
                # Nothing with this key exists at all, fresh or stale — this
                # IntegrityError is about a different constraint entirely
                # (e.g. an unrelated ``upload_id`` collision). Nulling a key
                # that was never the conflicting one would only retry into
                # the same failure; surface the real error instead.
                raise
            return self._retry_after_releasing_stale_key(
                owner=owner,
                idempotency_key=idempotency_key,
                user_id=user_id,
                new_row=_new_row,
                since=since,
            )

    def _idempotency_key_row_exists(self, *, owner: uuid.UUID, key: str) -> bool:
        """Whether any row — fresh or stale — currently holds ``key`` for ``owner``.

        Only a genuinely existing row justifies treating an ``IntegrityError``
        as the idempotency-key race handled by :meth:`create_upload`; anything
        else means the conflict came from an unrelated constraint.
        """
        stmt = (
            select(Upload.id).where(Upload.user_id == owner, Upload.idempotency_key == key).limit(1)
        )
        with self._sm() as session:
            return session.scalars(stmt).first() is not None

    def _retry_after_releasing_stale_key(
        self,
        *,
        owner: uuid.UUID,
        idempotency_key: str,
        user_id: str,
        new_row: Callable[[], Upload],
        since: datetime,
    ) -> uuid.UUID:
        """Null out a stale idempotency key and retry the insert once.

        Only rows older than ``since`` are released — a fresh row must never
        have its key erased here, or a concurrent winner's own future
        dedupe lookups would silently stop matching it.

        A second, concurrent request can win the same race between the
        moment this releases the key and the moment it retries its own
        insert: its retry then raises a second ``IntegrityError``, this
        time against a fresh row. That is resolved exactly like the first
        race above, rather than left to escape as an unhandled 500.
        """
        try:
            with self._sm.begin() as session:
                session.execute(
                    update(Upload)
                    .where(
                        Upload.user_id == owner,
                        Upload.idempotency_key == idempotency_key,
                        Upload.created_at < since,
                    )
                    .values(idempotency_key=None)
                )
                row = new_row()
                session.add(row)
                session.flush()
                return row.id
        except IntegrityError:
            existing = self.find_by_idempotency_key(
                user_id=user_id, key=idempotency_key, since=since
            )
            if existing is not None:
                return existing.id
            raise

    def find_by_idempotency_key(
        self, *, user_id: str, key: str, since: datetime
    ) -> OwnedUpload | None:
        """Return the caller-owned upload already stored under ``key``, if any.

        Only a row created at or after ``since`` counts as a match — the
        24h dedupe window is enforced here, not by the unique index, which
        has no time bound of its own (see :meth:`create_upload`).
        """
        owner = parse_user_id(user_id)
        stmt = (
            select(Upload)
            .where(
                Upload.user_id == owner,
                Upload.idempotency_key == key,
                Upload.created_at >= since,
            )
            .order_by(Upload.created_at.desc())
            .limit(1)
        )
        with self._sm() as session:
            upload = session.scalars(stmt).one_or_none()
            if upload is None:
                return None
            return OwnedUpload(
                id=upload.id,
                storage_path=upload.storage_path,
                original_filename=upload.original_filename,
            )

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
