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

from fastapi import HTTPException

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


def check_upload_cap(data: bytes, *, max_bytes: int = MAX_UPLOAD_BYTES) -> None:
    """Raise 413 when ``data`` exceeds ``max_bytes``.

    Every upload path in the app ships bytes to the object-storage seam
    (never the container filesystem, spec §4.1), so this is the one cap-check
    every one of them shares.
    """
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds {max_bytes} byte limit.",
        )


__all__ = [
    "MAX_UPLOAD_BYTES",
    "check_upload_cap",
    "safe_upload_name",
]
