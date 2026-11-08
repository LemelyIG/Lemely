"""Invite code generation shared by every invite minter (D7.3; paymob billing Phase 03).

Moved out of ``lemely/db/invite_repo.py`` (with the ``IntegrityError`` constraint-name
helper both modules share) so ``lemely/db/teacher_team_repo.py`` can
mint assistant invites without importing ``invite_repo`` (which imports
``class_repo``, which imports ``teacher_team_repo``). Codes are unchanged.

The alphabet excludes visually ambiguous characters (0/O, 1/I/L), mirroring
``class_repo._JOIN_CODE_ALPHABET``: a holder must be able to transcribe a code read
off a screen. The length differs from a class join code's so the two families look
different.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from sqlalchemy.exc import IntegrityError

INVITE_CODE_ALPHABET: Final = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
INVITE_CODE_LENGTH: Final = 10


def generate_invite_code() -> str:
    """Return a random invite code from the non-ambiguous alphabet."""
    return "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


def constraint_name(exc: IntegrityError) -> str | None:
    """Best-effort constraint name off a psycopg ``IntegrityError``.

    Lets an invite writer retry only the violation it expects (a code collision, a
    duplicate pair) and re-raise every other one.
    """
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name is not None else None


__all__ = ["INVITE_CODE_ALPHABET", "INVITE_CODE_LENGTH", "constraint_name", "generate_invite_code"]
