"""Pure object-key derivations shared by the paper purge and the account purge."""

from __future__ import annotations

from pathlib import PurePosixPath


def sibling_scheme_key(storage_path: str) -> str:
    """Where a student's own mark-scheme scan sits beside ``storage_path``.

    The same derivation the marking run reads it from (``lemely.web.routers.student``).
    """
    return f"{PurePosixPath(storage_path).parent.as_posix()}/mark_scheme.pdf"


__all__ = ["sibling_scheme_key"]
