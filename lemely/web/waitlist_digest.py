"""The daily waitlist digest: what is composed, and when it is sent.

Aggregates only. The body carries counts by role, the top subjects, the exam-board split and
completed versus partial; it never names an applicant, so it cannot leak an email address or
a phone number. Zero new applicants means no mail at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from lemely.core.waitlist import ALL_SUBJECTS, OTHER_SUBJECT_LABEL

if TYPE_CHECKING:
    from lemely.auth.email import EmailProvider
    from lemely.db.waitlist_repo import DigestStats, WaitlistRepository

DIGEST_WINDOW: Final = timedelta(hours=24)

_ROLE_LABELS: Final = {
    "student": "Students",
    "teacher": "Teachers",
    "parent": "Parents",
    "centre_admin": "Centre administrators",
}
_BOARD_LABELS: Final = {
    "caie": "CAIE",
    "edexcel": "Edexcel",
    "oxford_aqa": "Oxford AQA",
    "other": "Other",
}


@dataclass(frozen=True, slots=True)
class DigestOutcome:
    """What a digest trigger did."""

    new_applicants: int
    sent: bool
    already_sent: bool
    #: Another call holds today's claim and has not finished (or failed without releasing it).
    #: The digest has NOT gone out; the trigger should report a failure so it is retried.
    pending: bool = False


def compose_digest(stats: DigestStats, moment: datetime) -> tuple[str, str] | None:
    """Return ``(subject, plain-text body)``, or ``None`` when there is nothing to report."""
    if stats.total == 0:
        return None
    noun = "applicant" if stats.total == 1 else "applicants"
    subject = f"Lemely waitlist: {stats.total} new {noun} ({moment:%Y-%m-%d})"
    lines = [
        f"{stats.total} new waitlist {noun} since the previous digest.",
        "",
        f"Completed the full form: {stats.completed}",
        f"Email and role only (partial): {stats.partial}",
        "",
        "By role",
        *(
            f"  {_ROLE_LABELS[role]}: {count}"
            for role, count in sorted(stats.by_role.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
    ]
    if stats.top_subjects:
        lines += ["", "Top subjects"]
        lines += [
            f"  {ALL_SUBJECTS.get(value, OTHER_SUBJECT_LABEL)}: {count}"
            for value, count in stats.top_subjects
        ]
    if stats.by_board:
        lines += ["", "Exam boards"]
        lines += [
            f"  {_BOARD_LABELS.get(board, board)}: {count}"
            for board, count in sorted(stats.by_board.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
    lines += ["", "Open the admin waitlist to follow up."]
    return subject, "\n".join(lines) + "\n"


def send_waitlist_digest(
    repo: WaitlistRepository, provider: EmailProvider, *, now: datetime | None = None
) -> DigestOutcome:
    """Send the digest of applicants since the last sent digest, at most once per UTC day.

    The window runs from where the previous sent digest stopped (the last 24 hours when there
    has been none) to now, so an applicant is in exactly one digest however late or early the
    scheduler fires. "Now" and the UTC day come from the database clock, the one ``created_at``
    is stamped with, not the app server's. The cursor moves only after the mail went out, so a
    failed send (even one whose claim could not be released) skips nobody. If the cursor update
    itself fails after a successful send, the next digest repeats those applicants rather than
    missing any.

    The day is claimed in the database before the mail goes out, so a second trigger the same
    day is a no-op. A provider failure releases the claim and propagates, so the scheduler's
    retry can still send it. Zero new applicants claims nothing. A claim that was made but never
    confirmed (the send failed and could not release it) is reported as ``pending``, never as
    already sent, and is taken over once its lease runs out. That is at-least-once: if the mail
    did go out but the cursor update failed, the takeover sends it again.
    """
    moment = now if now is not None else repo.db_now().astimezone(UTC)
    since = repo.last_digest_window_end() or moment - DIGEST_WINDOW
    stats = repo.digest_stats(since, moment)
    composed = compose_digest(stats, moment)
    if composed is None:
        return DigestOutcome(0, sent=False, already_sent=False)
    day = moment.date()
    claim = repo.claim_digest_day(day, stats.total)
    if claim == "sent":
        return DigestOutcome(stats.total, sent=False, already_sent=True)
    if claim == "pending":
        # Claimed but never confirmed: do not call it sent. It becomes retryable once the
        # claim's lease runs out.
        return DigestOutcome(stats.total, sent=False, already_sent=False, pending=True)
    try:
        provider.send_team_digest(*composed)
    except Exception:
        # If releasing fails too, the claim stays but its cursor is unset, so the next
        # digest still starts from the last *sent* one and nobody is skipped.
        repo.release_digest_day(day)
        raise
    repo.mark_digest_sent(day, moment)
    return DigestOutcome(stats.total, sent=True, already_sent=False)
