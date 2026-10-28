"""Tutor evidence routes T6 and T7 (SPEC §b.2 "Tutor", §a.2 ``tutor_evidence_files``, SC-22, O20).

The caller's own profile only (O1): both routes resolve it through
``deps_tutoring.require_writable_tutor_profile``, so a teacher without one gets
404 ``no_tutor_profile`` and a suspended or closed profile 409
``tutor_suspended`` / ``tutor_closed`` (CB-7). Neither is **V**.

**T6 upload**, in this order: the attempt quota (T30 F30-5: the attempt is
recorded and committed first, so one the check refuses still counts and a T7
delete gives none back; past 20 attempts in 24 elapsed hours the answer is 429
``too_many_requests`` with ``Retry-After``, before any bytes are read or checked;
the same 429 past 200 attempts from every profile together in 60 elapsed
minutes, Wave 8 finding 2, logged as ``tutor_evidence_upload_ceiling`` because
it refuses every tutor), the five-file pre-check (cheap, before any bytes
are stored), at most 10 MiB + 1 read from the spooled upload, the description
(SC-7), :func:`~lemely.io.evidence_files.prepare_evidence_in_worker` (magic-byte
sniff, polyglot refusal, image re-encode, the PDF scan check and pages-only
rewrite; 413/415), the object written under
``tutor-evidence/{profile}/{uuid}.{ext}`` in the private evidence bucket, then
the row. If the row is refused (a race past the pre-check, a suspension) the
object is deleted again; a storage failure is a 503 with no row.

The check runs in the extraction worker (T10 review R2), within the scan upload
check's timeout (``upload_check_timeout_seconds``, counting any wait for the
worker), so Pillow and MuPDF never decode an upload in the web process. A
worker that gives no verdict is logged (``tutor_evidence_check_failed``, with
its reason) and answered with fixed text: 503 ``evidence_check_unavailable``
when it is busy or cannot start (try again), 413 when the file ran it out of
memory, 415 for a timeout, a crash or an error.

**T7 delete** removes the row (scoped to the caller's profile, O20) and commits,
then deletes the object, best effort: a failure is logged as
``tutor_evidence_orphan`` with the bucket and path, and the route still answers
204, because the row is what decides that the file is gone.

Evidence bytes are never served here: only A2 issues (logged, 300 s,
attachment) URLs (O17). Built with ``TutoringRoute`` (``private, no-store``).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Final

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from lemely.db.session import get_sessionmaker
from lemely.db.tutor_evidence_repo import (
    MAX_EVIDENCE_FILES,
    EvidenceCeilingError,
    EvidenceError,
    EvidenceLimitError,
    EvidenceNotFoundError,
    EvidenceQuotaError,
    EvidenceValidationError,
    TutorEvidenceRepository,
    clean_description,
)
from lemely.db.tutor_profile_repo import (
    EvidenceFile,
    ProfileNotFoundError,
    TutorClosedError,
    TutorProfileError,
    TutorProfileRow,
    TutorSuspendedError,
)
from lemely.io.evidence_files import (
    MAX_EVIDENCE_BYTES,
    EvidenceFileError,
    EvidenceTooLargeError,
    UnsupportedEvidenceError,
    evidence_object_path,
    prepare_evidence_in_worker,
)
from lemely.io.storage import StorageBackend  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.runtime import sandbox
from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI resolves it at runtime
from lemely.runtime.errors import ExternalServiceError
from lemely.web.deps import get_settings, get_storage_backend
from lemely.web.deps_tutoring import require_writable_tutor_profile
from lemely.web.schemas_tutoring import EvidenceDTO
from lemely.web.tutoring_http import TutoringRoute, iso_instant, tutoring_error

router = APIRouter(
    prefix="/api/tutor/profile/evidence", tags=["tutoring"], route_class=TutoringRoute
)
log = structlog.get_logger(__name__)

_PROFILE_STATUS: Final[dict[type[TutorProfileError], int]] = {
    ProfileNotFoundError: 404,
    TutorSuspendedError: 409,
    TutorClosedError: 409,
}
_EVIDENCE_STATUS: Final[dict[type[EvidenceError], int]] = {
    EvidenceLimitError: 409,
    EvidenceNotFoundError: 404,
    EvidenceValidationError: 422,
}


def get_tutor_evidence_repo() -> TutorEvidenceRepository:
    """A :class:`TutorEvidenceRepository` on the process-wide sessionmaker (cheap; not cached)."""
    return TutorEvidenceRepository(get_sessionmaker(get_settings()))


def _http(exc: TutorProfileError | EvidenceError) -> HTTPException:
    if isinstance(exc, EvidenceQuotaError):
        # The SPEC §0 body with the header a client waits on (``tutoring_error`` sets none).
        return HTTPException(
            status_code=429,
            detail={"code": exc.code, "message": exc.message},
            headers={"Retry-After": str(exc.retry_after)},
        )
    if isinstance(exc, EvidenceError):
        return tutoring_error(_EVIDENCE_STATUS.get(type(exc), 409), exc.code, exc.message)
    return tutoring_error(_PROFILE_STATUS.get(type(exc), 409), exc.code, exc.message)


def evidence_dto(item: EvidenceFile) -> EvidenceDTO:
    """An evidence file's metadata as the tutor sees it: never a URL, never a path (O17)."""
    return EvidenceDTO(
        evidenceId=str(item.id),
        filename=item.filename,
        contentType=item.content_type,
        sizeBytes=item.size_bytes,
        description=item.description,
        uploadedAt=iso_instant(item.uploaded_at),
    )


def _check_failed(exc: sandbox.SandboxFailure, *, byte_size: int) -> HTTPException:
    """The answer when the worker gave no verdict on a file; its own text goes to the log only."""
    log.warning(
        "tutor_evidence_check_failed", reason=exc.reason, error=str(exc), byte_size=byte_size
    )
    if isinstance(exc, sandbox.SandboxUnavailable):
        return tutoring_error(
            503,
            "evidence_check_unavailable",
            "Could not check the file just now. Try again in a moment.",
        )
    if isinstance(exc, sandbox.SandboxMemory):
        return tutoring_error(
            EvidenceTooLargeError.status,
            EvidenceTooLargeError.code,
            "This file is too large to check. Upload a smaller file.",
        )
    return tutoring_error(
        UnsupportedEvidenceError.status,
        UnsupportedEvidenceError.code,
        "This file could not be checked. Upload a PDF, JPEG or PNG file.",
    )


def _delete_quietly(storage: StorageBackend, bucket: str, path: str) -> None:
    """Remove an object, logging (never raising) a failure as an orphan with its path."""
    try:
        storage.delete(bucket, path)
    except Exception as exc:
        log.error("tutor_evidence_orphan", bucket=bucket, storage_path=path, error=str(exc))


@router.post("", status_code=201, response_model=EvidenceDTO)
def upload_evidence(
    profile: Annotated[TutorProfileRow, Depends(require_writable_tutor_profile)],
    file: Annotated[UploadFile, File()],
    repo: Annotated[TutorEvidenceRepository, Depends(get_tutor_evidence_repo)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    settings: Annotated[Settings, Depends(get_settings)],
    description: Annotated[str | None, Form()] = None,
) -> EvidenceDTO:
    """T6: add one evidence file (PDF, JPEG or PNG by its bytes; at most 5 x 10 MiB)."""
    try:
        repo.record_upload_attempt(profile.id)
    except EvidenceQuotaError as exc:
        if isinstance(exc, EvidenceCeilingError):
            log.warning("tutor_evidence_upload_ceiling", retry_after=exc.retry_after)
        raise _http(exc) from exc
    if repo.count(profile.id) >= MAX_EVIDENCE_FILES:
        raise _http(
            EvidenceLimitError(
                f"You can keep at most {MAX_EVIDENCE_FILES} files. Delete one first."
            )
        )
    data = file.file.read(MAX_EVIDENCE_BYTES + 1)
    try:
        cleaned = clean_description(description)
        prepared = prepare_evidence_in_worker(
            data,
            filename=file.filename,
            declared_type=file.content_type,
            timeout=sandbox.sandbox_settings().upload_check_timeout_seconds,
        )
    except EvidenceValidationError as exc:
        raise _http(exc) from exc
    except EvidenceFileError as exc:
        raise tutoring_error(exc.status, exc.code, exc.message) from exc
    except sandbox.SandboxFailure as exc:
        raise _check_failed(exc, byte_size=len(data)) from exc
    evidence_id = uuid.uuid4()
    bucket = settings.storage.tutor_evidence_bucket
    path = evidence_object_path(profile.id, evidence_id, prepared.content_type)
    try:
        storage.upload(bucket, path, prepared.data, prepared.content_type)
    except ExternalServiceError as exc:
        log.warning("tutor_evidence_upload_failed", error=str(exc))
        raise tutoring_error(
            503, "storage_unavailable", "Could not store the file. Try again in a moment."
        ) from exc
    try:
        stored = repo.add(
            profile.id,
            evidence_id=evidence_id,
            storage_path=path,
            filename=prepared.filename,
            content_type=prepared.content_type,
            size_bytes=prepared.size_bytes,
            description=cleaned,
        )
    except (TutorProfileError, EvidenceError) as exc:
        _delete_quietly(storage, bucket, path)
        raise _http(exc) from exc
    except Exception:
        _delete_quietly(storage, bucket, path)
        raise
    return evidence_dto(stored)


@router.delete("/{evidence_id}", status_code=204, response_class=Response)
def delete_evidence(
    evidence_id: uuid.UUID,
    profile: Annotated[TutorProfileRow, Depends(require_writable_tutor_profile)],
    repo: Annotated[TutorEvidenceRepository, Depends(get_tutor_evidence_repo)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """T7: delete one of the caller's evidence files (404 for anyone else's, O20)."""
    try:
        path = repo.delete(profile.id, evidence_id)
    except (TutorProfileError, EvidenceError) as exc:
        raise _http(exc) from exc
    _delete_quietly(storage, settings.storage.tutor_evidence_bucket, path)
    return Response(status_code=204)


__all__ = ["evidence_dto", "get_tutor_evidence_repo", "router"]
