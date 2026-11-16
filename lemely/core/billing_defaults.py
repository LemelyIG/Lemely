"""Seed values of the admin-editable billing settings (UD-13, UD13-DV-3).

These are the values a fresh ``billing_settings`` row starts with, nothing more: the running
code reads the row (never these constants), and an admin edits it. They equal the column
defaults of ``billing_settings`` in migration 0057.
"""

from __future__ import annotations

from typing import Final

#: How many months a purchased or converted credit grant stays valid.
CREDIT_VALIDITY_MONTHS: Final = 12

#: Days a failed renewal keeps access (UD13-C); also Paymob ``retrial_days`` on new plan syncs.
GRACE_DAYS: Final = 3

#: Ceiling on extra seats one subscription may hold.
MAX_EXTRA_SEATS: Final = 200

#: Days a teacher's signup credits stay valid; ``credit_packs.signup_validity_days`` is seeded
#: with it (the student allowance is seeded NULL, never expires).
TEACHER_SIGNUP_VALIDITY_DAYS: Final = 30

#: Days of notice before a worse plan-terms change reaches a subscriber (UD13-G).
PRICE_CHANGE_NOTICE_DAYS: Final = 14

__all__ = [
    "CREDIT_VALIDITY_MONTHS",
    "GRACE_DAYS",
    "MAX_EXTRA_SEATS",
    "PRICE_CHANGE_NOTICE_DAYS",
    "TEACHER_SIGNUP_VALIDITY_DAYS",
]
