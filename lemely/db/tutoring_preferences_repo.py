"""A student's own tutoring settings (SPEC §a.2 ``student_tutoring_preferences``, PLAN P30).

The row is the student's alone (SPEC §a.5): S12/S13 read and change the
outcome-figure opt-out, S15 records the safety-notice acknowledgement, and the
booking service reads the acknowledgement in its own transaction (T13). An
absent row reads as :data:`DEFAULT_PREFERENCES`: counted in outcome figures
(decision row 8, default on), no change instant, no acknowledgement.

* :meth:`TutoringPreferencesRepository.set_opt_out` sets
  ``outcome_pref_changed_at`` only when the stored value actually changes: that
  instant starts the 90-day hold on the tutor's figures (SC-13d), so saving the
  same choice again must not restart it. With no row yet the stored value is the
  default (counted), so a first opt-out is a change and a first "keep counting"
  is not.
* :meth:`TutoringPreferencesRepository.acknowledge_safety_notice` is idempotent:
  the first acknowledgement's instant is kept (decision row 16 ii).

Each write is one ``INSERT ... ON CONFLICT (user_id) DO UPDATE`` statement, so two
concurrent saves cannot lose either the row or the change instant. Instants are
the database ``now()`` (SPEC §0 "Clock").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, sessionmaker

_COLUMNS: Final = "outcome_stats_opt_out, outcome_pref_changed_at, safety_notice_acknowledged_at"


@dataclass(frozen=True, slots=True)
class TutoringPreferences:
    """The three settings of one student."""

    outcome_stats_opt_out: bool
    outcome_pref_changed_at: datetime | None
    safety_notice_acknowledged_at: datetime | None


#: What a student with no row has (decision row 8: counted by default).
DEFAULT_PREFERENCES: Final = TutoringPreferences(
    outcome_stats_opt_out=False,
    outcome_pref_changed_at=None,
    safety_notice_acknowledged_at=None,
)


def _optional_instant(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise TypeError(f"expected a datetime, got {value!r}")
    return value


def _preferences(row: Row[tuple[object, ...]]) -> TutoringPreferences:
    mapping = row._mapping
    return TutoringPreferences(
        outcome_stats_opt_out=bool(mapping["outcome_stats_opt_out"]),
        outcome_pref_changed_at=_optional_instant(mapping["outcome_pref_changed_at"]),
        safety_notice_acknowledged_at=_optional_instant(mapping["safety_notice_acknowledged_at"]),
    )


class TutoringPreferencesRepository:
    """Reads and writes ``student_tutoring_preferences``; one statement per call."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the repository to a session factory."""
        self._sessionmaker = sessionmaker

    def get(self, student_id: uuid.UUID) -> TutoringPreferences:
        """The student's settings, or the defaults when they never saved any."""
        with self._sessionmaker() as session:
            row = session.execute(
                sa.text(
                    f"SELECT {_COLUMNS} FROM student_tutoring_preferences "  # noqa: S608 - constant
                    "WHERE user_id = :user_id"
                ),
                {"user_id": student_id},
            ).first()
        return _preferences(row) if row is not None else DEFAULT_PREFERENCES

    def set_opt_out(self, student_id: uuid.UUID, value: bool) -> TutoringPreferences:
        """S13: opt out of (or back into) tutors' outcome figures.

        ``outcome_pref_changed_at`` moves only when the stored value changes.
        """
        with self._sessionmaker.begin() as session:
            row = session.execute(
                sa.text(
                    "INSERT INTO student_tutoring_preferences AS p "  # noqa: S608 - constant
                    "(user_id, outcome_stats_opt_out, outcome_pref_changed_at) "
                    "VALUES (:user_id, :value, CASE WHEN :value THEN now() END) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "outcome_stats_opt_out = EXCLUDED.outcome_stats_opt_out, "
                    "outcome_pref_changed_at = CASE "
                    "WHEN p.outcome_stats_opt_out IS DISTINCT FROM EXCLUDED.outcome_stats_opt_out "
                    "THEN now() ELSE p.outcome_pref_changed_at END, "
                    "updated_at = CASE "
                    "WHEN p.outcome_stats_opt_out IS DISTINCT FROM EXCLUDED.outcome_stats_opt_out "
                    "THEN now() ELSE p.updated_at END "
                    f"RETURNING {_COLUMNS}"
                ),
                {"user_id": student_id, "value": value},
            ).one()
        return _preferences(row)

    def acknowledge_safety_notice(self, student_id: uuid.UUID) -> TutoringPreferences:
        """S15: record that the student read the safety notice; a repeat keeps the first instant."""
        with self._sessionmaker.begin() as session:
            row = session.execute(
                sa.text(
                    "INSERT INTO student_tutoring_preferences AS p "  # noqa: S608 - constant
                    "(user_id, safety_notice_acknowledged_at) VALUES (:user_id, now()) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "safety_notice_acknowledged_at = COALESCE("
                    "p.safety_notice_acknowledged_at, EXCLUDED.safety_notice_acknowledged_at), "
                    "updated_at = CASE WHEN p.safety_notice_acknowledged_at IS NULL "
                    "THEN now() ELSE p.updated_at END "
                    f"RETURNING {_COLUMNS}"
                ),
                {"user_id": student_id},
            ).one()
        return _preferences(row)


__all__ = ["DEFAULT_PREFERENCES", "TutoringPreferences", "TutoringPreferencesRepository"]
