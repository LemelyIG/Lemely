"""Invite code generation shared by every invite minter (D7.3; paymob billing Phase 03).

Moved out of ``lemely/db/invite_repo.py`` so ``lemely/db/teacher_team_repo.py`` can
mint assistant invites without importing ``invite_repo`` (which imports
``class_repo``, which imports ``teacher_team_repo``). Codes are unchanged.

The alphabet excludes visually ambiguous characters (0/O, 1/I/L), mirroring
``class_repo._JOIN_CODE_ALPHABET``: a holder must be able to transcribe a code read
off a screen. The length differs from a class join code's so the two families look
different.
"""

from __future__ import annotations

import secrets
from typing import Final

INVITE_CODE_ALPHABET: Final = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
INVITE_CODE_LENGTH: Final = 10


def generate_invite_code() -> str:
    """Return a random invite code from the non-ambiguous alphabet."""
    return "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


__all__ = ["INVITE_CODE_ALPHABET", "INVITE_CODE_LENGTH", "generate_invite_code"]
