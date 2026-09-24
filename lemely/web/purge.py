"""Permanently remove papers deleted longer ago than the retention window (design §7).

The only code in the deletion feature that destroys data irreversibly. One of
the permitted callers of :data:`~lemely.db.session.INCLUDE_DELETED`: every row
it touches is soft-deleted, so the loader criterion would otherwise hide all of
them. Every read is an explicit ``select``, never a relationship walk, for the
reason :mod:`lemely.db.deletion_repo` gives.

**GCS first, the row as the record of intent.** The scan (and a student's own
sibling ``mark_scheme.pdf`` next to it — a D2 clarification: the
``mark_schemes`` *table* is shared reference data and is never touched) is
deleted before any row. If storage fails, every row stays: still hidden, still
past the cutoff, retried on the next pass. Deleting rows first would leak an
object no row remembers, and the public data-handling page would then be
describing something untrue.

**The unit is the upload (R7).** The object goes only when the upload and
*every* attempt on it are deleted at or before the cutoff; then the attempts go,
then the upload (``attempts.upload_id`` has no ``ondelete``, so the other order
is refused by the FK). An expired attempt whose sibling is still inside the
window, or whose upload is live and could be re-marked, loses its rows but not
the scan. Leaving it whole would park it at the head of the ``(deleted_at, id)``
order, taking a batch slot on every pass for up to thirty days.

**Lock order is upload, then attempts in id order** — the order
:class:`~lemely.db.deletion_repo.PaperDeletionService` and
``AttemptRepository._persist`` take. Any other order is a lock cycle with them.

**No lock is held across the storage call** (option (a) of the Task 10 brief).
Each upload is decided under lock and that transaction commits; the objects are
deleted with no transaction open; then a second transaction re-locks in the
same order, re-takes the decision on the locked copies, and deletes only if it
is unchanged. Holding row locks across a GCS round trip would let a slow or
retrying storage call stall a student's delete, restore or marking run on the
same upload for as long as the call takes. Releasing them is safe because
nothing can legitimately change the decision in between: restore can only win
while ``deleted_at > now - RETENTION``, purge only acts once
``deleted_at <= now - RETENTION - PURGE_GRACE``, and a marking run cannot add an
attempt to a deleted upload (``attempt_repo._lock_live_upload``). The re-check,
and the ``deleted_at <= cutoff`` every ``DELETE`` re-asserts in its own WHERE,
are there for the case that should not happen — replica clock skew beyond the
grace — and turn it into a logged error with the rows kept, never a deleted
paper the student can see.

**The invariant from Task 5a is asserted, not assumed.** A live attempt on a
deleted upload is logged at error and that upload is skipped whole; purge never
cascades past it.

**Throughput limit, accepted.** A pass takes at most ``limit`` expired attempts,
oldest ``(deleted_at, id)`` first. An upload whose objects persistently fail to
delete, or which breaks the invariant, is re-selected every pass and holds its
slots; enough of them could stall the batch. That is accepted rather than
engineered around, and the purge-backlog metric (Task 11) is what surfaces it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from sqlalchemy import select

from lemely.core.deletion import purge_cutoff
from lemely.db.models.attempts import Attempt, Upload
from lemely.db.session import INCLUDE_DELETED
from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.storage import StorageBackend

log = structlog.get_logger(__name__)

#: Rows per pass, counted in attempts (design §7).
DEFAULT_PURGE_LIMIT = 50


@dataclass(frozen=True, slots=True)
class _Decision:
    """What one upload's purge will remove, as decided under its locks."""

    attempt_ids: tuple[uuid.UUID, ...]
    """The expired attempts, by id."""
    object_paths: tuple[str, ...]
    """The objects to delete first — empty when the scan must stay."""


class _InvariantBroken(Exception):
    """A live attempt references a soft-deleted upload (Task 5a's invariant)."""


def purge_expired_papers(
    session_factory: sessionmaker[Session],
    storage: StorageBackend,
    bucket: str,
    *,
    now: datetime | None = None,
    limit: int = DEFAULT_PURGE_LIMIT,
) -> int:
    """Permanently remove papers deleted at or before :func:`purge_cutoff`.

    Returns the number of attempts removed. Idempotent: a second pass, or a
    second replica mid-pass, finds nothing left to remove and deletes a
    missing object harmlessly. One upload's failure — storage or database —
    is logged and never stops the rest of the batch.
    """
    cutoff = purge_cutoff(now or datetime.now(UTC))
    purged = 0
    for upload_id, attempt_ids in _candidates(session_factory, cutoff, limit):
        try:
            if upload_id is None:
                purged += _purge_attempts_without_upload(session_factory, attempt_ids, cutoff)
            else:
                purged += _purge_upload(session_factory, storage, bucket, upload_id, cutoff)
        except sa.exc.SQLAlchemyError:
            log.warning(
                "purge_paper_failed",
                upload_id=str(upload_id) if upload_id else None,
                exc_info=True,
            )
    if purged:
        log.info("purge_expired_papers", count=purged)
    return purged


def _candidates(
    session_factory: sessionmaker[Session], cutoff: datetime, limit: int
) -> list[tuple[uuid.UUID | None, list[uuid.UUID]]]:
    """The oldest expired attempts, grouped by upload in first-seen order.

    Unlocked: it only nominates. Every decision that counts is taken again
    under lock in :func:`_decide`.
    """
    with session_factory() as session:
        rows = session.execute(
            select(Attempt.id, Attempt.upload_id)
            .where(Attempt.deleted_at.is_not(None), Attempt.deleted_at <= cutoff)
            .order_by(Attempt.deleted_at, Attempt.id)
            .limit(limit)
            .execution_options(**{INCLUDE_DELETED: True})
        ).all()
    grouped: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for attempt_id, upload_id in rows:
        grouped.setdefault(upload_id, []).append(attempt_id)
    return list(grouped.items())


def _purge_upload(
    session_factory: sessionmaker[Session],
    storage: StorageBackend,
    bucket: str,
    upload_id: uuid.UUID,
    cutoff: datetime,
) -> int:
    """Purge one upload's expired attempts, and its objects when all of it has expired."""
    try:
        with session_factory.begin() as session:
            decision = _decide(session, upload_id, cutoff)
    except _InvariantBroken:
        log.error("purge_live_attempt_on_deleted_upload", upload_id=str(upload_id))
        return 0
    if decision is None:
        return 0

    try:
        for path in decision.object_paths:
            storage.delete(bucket, path)
    except ExternalServiceError:
        log.warning("purge_object_delete_failed", upload_id=str(upload_id), exc_info=True)
        return 0

    with session_factory.begin() as session:
        try:
            again = _decide(session, upload_id, cutoff)
        except _InvariantBroken:
            again = None
        if again != decision:
            # Only reachable through clock skew past PURGE_GRACE. With the
            # objects already gone this is an error; the rows are kept so a
            # person can see what happened.
            log.error(
                "purge_paper_changed_after_object_delete",
                upload_id=str(upload_id),
                objects_deleted=bool(decision.object_paths),
            )
            return 0
        removed = _delete_attempts(session, decision.attempt_ids, cutoff)
        if decision.object_paths:
            session.execute(
                sa.delete(Upload)
                .where(
                    Upload.id == upload_id,
                    Upload.deleted_at <= cutoff,
                    ~sa.exists().where(Attempt.upload_id == upload_id),
                )
                .execution_options(**{INCLUDE_DELETED: True}, synchronize_session=False)
            )
        return removed


def _decide(session: Session, upload_id: uuid.UUID, cutoff: datetime) -> _Decision | None:
    """Lock the upload then its attempts, and decide what may go; ``None`` for nothing.

    Raises:
        _InvariantBroken: a live attempt references this deleted upload.
    """
    upload = session.scalars(
        select(Upload)
        .where(Upload.id == upload_id)
        .with_for_update()
        .execution_options(**{INCLUDE_DELETED: True}, populate_existing=True)
    ).one_or_none()
    if upload is None:
        return None
    attempts: Sequence[Attempt] = session.scalars(
        select(Attempt)
        .where(Attempt.upload_id == upload_id)
        .order_by(Attempt.id)
        .with_for_update()
        .execution_options(**{INCLUDE_DELETED: True}, populate_existing=True)
    ).all()
    if upload.deleted_at is not None and any(a.deleted_at is None for a in attempts):
        raise _InvariantBroken
    expired = tuple(a.id for a in attempts if a.deleted_at is not None and a.deleted_at <= cutoff)
    if not expired:
        return None
    whole = (
        upload.deleted_at is not None
        and upload.deleted_at <= cutoff
        and len(expired) == len(attempts)
    )
    paths = (upload.storage_path, _scheme_path(upload.storage_path)) if whole else ()
    return _Decision(attempt_ids=expired, object_paths=paths)


def _purge_attempts_without_upload(
    session_factory: sessionmaker[Session], attempt_ids: list[uuid.UUID], cutoff: datetime
) -> int:
    """Remove expired attempts that never had an upload: rows only, no object."""
    with session_factory.begin() as session:
        return _delete_attempts(session, attempt_ids, cutoff, require_no_upload=True)


def _delete_attempts(
    session: Session,
    attempt_ids: Sequence[uuid.UUID],
    cutoff: datetime,
    *,
    require_no_upload: bool = False,
) -> int:
    """Hard-delete these attempts; FK cascades take their question and review rows.

    The cutoff is re-asserted here rather than trusted from the decision:
    a row restored in between must not be removed by a decision taken a
    moment ago.
    """
    stmt = sa.delete(Attempt).where(
        Attempt.id.in_(attempt_ids),
        Attempt.deleted_at.is_not(None),
        Attempt.deleted_at <= cutoff,
    )
    if require_no_upload:
        stmt = stmt.where(Attempt.upload_id.is_(None))
    result = session.execute(
        stmt.execution_options(**{INCLUDE_DELETED: True}, synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


def _scheme_path(storage_path: str) -> str:
    """Where a student's own mark-scheme scan sits beside ``storage_path``.

    The same derivation the marking run reads it from
    (``lemely.web.routers.student``).
    """
    return f"{PurePosixPath(storage_path).parent.as_posix()}/mark_scheme.pdf"


__all__ = ["DEFAULT_PURGE_LIMIT", "purge_expired_papers"]
