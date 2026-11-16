"""Seed values of the admin-editable billing settings (UD-13, UD13-DV-3).

These are the values a fresh ``billing_settings`` row and the signup credit packs start with:
the running code reads the stored row (never these constants), and an admin edits it. The
settings ones equal the column defaults of ``billing_settings`` in migration 0057.
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

#: Units of the student's hidden one-time signup allowance (about two papers at the top of the
#: seeded marking estimate); ``credit_packs.units`` of ``signup_student`` is seeded with it.
STUDENT_SIGNUP_UNITS: Final = 250

#: Units of a teacher's visible signup credits; ``credit_packs.units`` of ``signup_teacher``.
TEACHER_SIGNUP_UNITS: Final = 2000

#: Days of notice before a worse plan-terms change reaches a subscriber (UD13-G).
PRICE_CHANGE_NOTICE_DAYS: Final = 14

__all__ = [
    "CREDIT_VALIDITY_MONTHS",
    "GRACE_DAYS",
    "MAX_EXTRA_SEATS",
    "PRICE_CHANGE_NOTICE_DAYS",
    "STUDENT_SIGNUP_UNITS",
    "TEACHER_SIGNUP_UNITS",
    "TEACHER_SIGNUP_VALIDITY_DAYS",
]
