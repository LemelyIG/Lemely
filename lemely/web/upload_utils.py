"""Shared upload helpers for the portal routers.

Both the teacher grading console and the student self-mark flow ingest
client-supplied files. The two concerns that must be identical across every
upload path — deriving a sandbox-safe destination name and capping the written
size — live here so a single hardened implementation backs them all.

Neither helper trusts the client filename as a path: only its basename survives
:func:`safe_upload_name`, and :func:`check_upload_cap` rejects a body once the
byte cap is exceeded rather than letting a hostile client exhaust disk or
memory.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import HTTPException

from lemely.io.scan_limits import ScanRejectedError, check_scan_bytes

log = structlog.get_logger(__name__)

# Hard cap on a single uploaded file (scan or mark scheme), enforced once the
# whole body has been read into memory, before it is written anywhere —
# object storage included.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def safe_upload_name(filename: str | None, fallback: str) -> str:
    """Return a sandbox-safe basename for a client-supplied upload filename.

    The client filename is *never* trusted as a path: only its basename is kept,
    any traversal / separator components are dropped, and an empty or dangerous
    result falls back to a server-chosen name. Callers still join the result to a
    server-namespaced directory, so the returned value can only ever name a file
    *inside* that directory.
    """
    if not filename:
        return fallback
    base = Path(filename).name
    if not base or base in {".", ".."}:
        return fallback
    return base


def _log_refusal(
    refusal: str, data: bytes, content_type: str | None, *, reason: str | None = None
) -> None:
    """One structured line for a refused upload: why, how big, and what it claimed to be.

    Final review, Important 3: refusals were invisible to operators. The
    file's bytes are never logged -- only their count and the client's
    declared content type. ``reason`` (#276) is the scan check's reason code,
    which says which rule refused the file within a class; the 413 path has
    none, so it logs its three fields as before.
    """
    fields: dict[str, object] = {
        "refusal": refusal,
        "byte_size": len(data),
        "content_type": content_type,
    }
    if reason is not None:
        fields["reason"] = reason
    log.warning("upload_refused", **fields)


def check_upload_cap(
    data: bytes, *, max_bytes: int = MAX_UPLOAD_BYTES, content_type: str | None = None
) -> None:
    """Raise 413 when ``data`` exceeds ``max_bytes``.

    Every upload path in the app ships bytes to the object-storage seam
    (never the container filesystem, spec §4.1), so this is the one cap-check
    every one of them shares. A refusal is logged (``too_large``), with the
    client's declared ``content_type``.
    """
    if len(data) > max_bytes:
        _log_refusal("too_large", data, content_type)
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds {max_bytes} byte limit.",
        )


def check_scan_geometry(data: bytes, content_type: str | None = None) -> None:
    """Raise 422 when ``data`` declares a page geometry or content extraction will refuse.

    Spec 2026-09-26 §6: both grading flows run outside a plain
    request/response (the student run is an SSE stream, the teacher run a
    daemon thread), so a geometry error at extraction time becomes a failed
    status, not an HTTP code. The clear error therefore happens here, at
    upload, from page sizes, image headers and (Task 11b) the decoded size
    of each page's content streams alone -- nothing is rendered. Bytes that
    are not a readable PDF or image pass: extraction fails on them later, as
    today. 413 (:func:`check_upload_cap`) stays the answer for byte size.

    A refusal is logged with the exception's class as its refusal class,
    its ``reason`` code, and the client's declared ``content_type`` (positional, so
    ``anyio.to_thread.run_sync`` can pass it).
    """
    try:
        check_scan_bytes(data)
    except ScanRejectedError as exc:
        _log_refusal(type(exc).__name__, data, content_type, reason=exc.reason)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = [
    "MAX_UPLOAD_BYTES",
    "check_scan_geometry",
    "check_upload_cap",
    "safe_upload_name",
]
