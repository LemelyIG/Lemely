"""Shared upload helpers for the portal routers.

Both the teacher grading console and the student self-mark flow ingest
client-supplied files. The two concerns that must be identical across every
upload path — deriving a sandbox-safe destination name and capping the written
size — live here so a single hardened implementation backs them all.

Neither helper trusts the client filename as a path: only its basename survives
:func:`safe_upload_name`, and :func:`write_upload_capped` aborts with a 413 once
the byte cap is exceeded rather than letting a hostile body exhaust disk.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

# Hard cap on a single uploaded file (scan or mark scheme). Uploads are written
# to disk in chunks and aborted with a 413 once this many bytes are seen, so a
# hostile client cannot exhaust disk by streaming an unbounded body.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024


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

    The same cap-check :func:`write_upload_capped` applies before writing to
    disk, extracted so callers that ship bytes elsewhere (e.g. Supabase
    Storage) can enforce the cap without a local write.
    """
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds {max_bytes} byte limit.",
        )


def write_upload_capped(
    data: bytes,
    dest: Path,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> None:
    """Write ``data`` to ``dest`` in chunks, raising 413 past ``max_bytes``."""
    check_upload_cap(data, max_bytes=max_bytes)
    with dest.open("wb") as fh:
        for start in range(0, len(data), UPLOAD_CHUNK_BYTES):
            fh.write(data[start : start + UPLOAD_CHUNK_BYTES])


__all__ = [
    "MAX_UPLOAD_BYTES",
    "UPLOAD_CHUNK_BYTES",
    "check_upload_cap",
    "safe_upload_name",
    "write_upload_capped",
]
