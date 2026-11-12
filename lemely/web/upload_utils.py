"""Shared upload helpers for the portal routers.

Both the teacher grading console and the student self-mark flow ingest
client-supplied files. The two concerns that must be identical across every
upload path — deriving a sandbox-safe destination name and capping the written
size — live here so a single hardened implementation backs them all.

Neither helper trusts the client filename as a path: only its basename survives
:func:`safe_upload_name`, and :func:`check_upload_cap` rejects a body once the
byte cap is exceeded rather than letting a hostile client exhaust disk or
memory. :func:`sandbox_failure_to_http` is the one mapping from a worker's
failure to an HTTP answer, shared by every route that renders a stored scan
or parses an uploaded mark scheme in a worker.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import HTTPException

from lemely.io.rasterise import RENDER_FAILED_MESSAGE
from lemely.io.scan_limits import ScanRejectedError
from lemely.runtime import sandbox
from lemely.runtime.sandbox import SandboxFailure, SandboxUnavailable

log = structlog.get_logger(__name__)

# Hard cap on a single uploaded file (scan or mark scheme), enforced once the
# whole body has been read into memory, before it is written anywhere —
# object storage included.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: The upload check :func:`check_scan_geometry` runs in the extraction worker.
SCAN_CHECK_TARGET = "lemely.io.scan_limits.check_scan_bytes"


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

    #260: the check opens the bytes with pdfium, MuPDF and Pillow, so it runs
    in :data:`~lemely.runtime.sandbox.EXTRACTION_WORKER` under its memory
    limit, within ``sandbox_settings().upload_check_timeout_seconds``
    (counting any wait for an extraction already running there). A bomb
    that blows a reader up while it opens the file (a catalog ``/Metadata``
    pdfium inflates on open, say) takes down the child, not the web process.

    A refusal is logged with the exception's class as its refusal class,
    its ``reason`` code, and the client's declared ``content_type`` (positional, so
    ``anyio.to_thread.run_sync`` can pass it). A worker failure is mapped by
    :func:`sandbox_failure_to_http` and logged as ``upload_check_failed``:
    503 when the worker is busy past the timeout or cannot start, otherwise
    422 with a fixed message.
    """
    try:
        sandbox.EXTRACTION_WORKER.call(
            SCAN_CHECK_TARGET,
            data,
            timeout=sandbox.sandbox_settings().upload_check_timeout_seconds,
            result_type=type(None),
        )
    except ScanRejectedError as exc:
        _log_refusal(type(exc).__name__, data, content_type, reason=exc.reason)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SandboxFailure as exc:
        raise sandbox_failure_to_http(
            exc, event="upload_check_failed", content_type=content_type, byte_size=len(data)
        ) from exc


#: The client's answer when no render worker could take the request.
SANDBOX_UNAVAILABLE_DETAIL = "Scan rendering is temporarily unavailable. Try again in a moment."

#: The client's answer for any other render worker failure, and for a render
#: that fails in process: the one fixed text a user is shown (owner decision,
#: #249), extraction's :data:`~lemely.io.rasterise.RENDER_FAILED_MESSAGE`
#: itself, so the copies cannot drift.
SANDBOX_FAILED_DETAIL = RENDER_FAILED_MESSAGE


#: The client's answer when no worker could take a mark-scheme parse.
SCHEME_PARSE_UNAVAILABLE_DETAIL = (
    "Reading mark schemes is temporarily unavailable. Try again in a moment."
)


def sandbox_failure_to_http(
    exc: SandboxFailure,
    *,
    event: str,
    failed_detail: str = SANDBOX_FAILED_DETAIL,
    unavailable_detail: str = SANDBOX_UNAVAILABLE_DETAIL,
    **fields: object,
) -> HTTPException:
    """The HTTP answer for a worker failure (#260), logged as ``event``.

    :class:`~lemely.runtime.sandbox.SandboxUnavailable` (the worker is busy
    past the call's timeout, or no child could start) is the server's
    problem, not the file's: 503 with ``unavailable_detail``, so the client
    tries again. Every other failure (timeout, memory, crash, an unexpected
    error in the target) is a 422 with the fixed ``failed_detail``. The
    defaults are a scan render's texts; the mark-scheme upload passes its
    own. The failure's ``reason`` and text go to the log line, with the
    caller's ``fields``; they never reach the client. The caller raises the
    result (``raise sandbox_failure_to_http(...) from exc``).
    """
    log.warning(event, reason=exc.reason, error=str(exc), **fields)
    if isinstance(exc, SandboxUnavailable):
        return HTTPException(status_code=503, detail=unavailable_detail)
    return HTTPException(status_code=422, detail=failed_detail)


__all__ = [
    "MAX_UPLOAD_BYTES",
    "SANDBOX_FAILED_DETAIL",
    "SANDBOX_UNAVAILABLE_DETAIL",
    "SCAN_CHECK_TARGET",
    "SCHEME_PARSE_UNAVAILABLE_DETAIL",
    "check_scan_geometry",
    "check_upload_cap",
    "safe_upload_name",
    "sandbox_failure_to_http",
]
