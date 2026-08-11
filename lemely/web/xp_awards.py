"""Router-layer helper that awards XP without ever failing the underlying action.

P5.2 chunk B wires :class:`~lemely.db.xp_repo.XpService` at exactly four
seams (D5.1): a corrected paper, a submitted quiz, a completed study-plan
session, a reviewed flashcard. Every one of those actions has *already*
succeeded and committed by the time XP is considered — the paper is marked,
the quiz is submitted, the card is scheduled. D5.1 §3 ("if the two ever
conflict, the learning wins") is binding: a failure inside
:meth:`~lemely.db.xp_repo.XpService.award` (a DB hiccup, a genuine bug) must
never turn an already-successful student action into an error response.

:func:`award_xp_safely` is the **single** place that calls ``XpService.award``
from ``lemely.web`` — every router seam goes through it rather than four
hand-rolled ``try``/``except`` blocks that could drift out of sync. It is not
silent: an exception is logged at warning level (with the seam name and the
user id, never a mark/score) via :mod:`structlog`, so a genuine infrastructure
failure stays visible in the logs even though it is deliberately kept from
reaching the caller. A capped award or a duplicate-dedupe no-op are *not*
failures (D5.1 §3/§8) — :meth:`XpService.award` already returns those as a
successful, no-exception :class:`~lemely.db.xp_repo.XpAwardResult` with
``awarded=False``, so this helper never needs to special-case them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import uuid

    from lemely.db.models.enums import XpSource
    from lemely.db.xp_repo import XpAwardResult, XpService

log = structlog.get_logger(__name__)


def award_xp_safely(
    xp_service: XpService,
    *,
    user_id: uuid.UUID | str,
    source: XpSource,
    dedupe_key: str,
    subject_code: str | None,
    seam: str,
) -> XpAwardResult | None:
    """Award XP for one call site, catching and logging instead of raising.

    Args:
        xp_service: The process-wide :class:`XpService` (via
            :func:`~lemely.web.deps.get_xp_service`).
        user_id: The student earning XP (``auth.user_id`` at every call site
            — never a caller-supplied id).
        source: Which of the four :class:`~lemely.db.models.enums.XpSource`
            acts this is.
        dedupe_key: Identity of the thing that caused this award (D5.1 §8) —
            the **upload** id for a corrected paper (D5.3: *not* the attempt
            id, which is re-minted on every re-correction), the assignment
            id, the plan-session id, or the flashcard-review id. Never a
            mark, score, grade, or accuracy
            value (D5.1 §0) — this function's signature has no such
            parameter for the same reason ``XpService.award`` doesn't.
        subject_code: The award's subject attribution, or ``None`` when the
            seam genuinely has none.
        seam: A short, stable label for *which* of the four call sites this
            is (e.g. ``"paper_corrected"``), used only in the warning log
            line so a failure can be traced back to its seam.

    Returns:
        The :class:`~lemely.db.xp_repo.XpAwardResult` on success — including
        the capped/duplicate no-op cases, which are successes, not failures
        — or ``None`` if ``XpService.award`` raised. Callers must treat
        ``None`` exactly like any other "XP wasn't awarded" outcome: the
        underlying action they just performed has already succeeded and
        stays succeeded regardless.
    """
    try:
        return xp_service.award(
            user_id,
            source,
            dedupe_key,
            subject_code=subject_code,
        )
    except Exception:
        log.exception("xp_award_failed", seam=seam, user_id=str(user_id))
        return None


__all__ = ["award_xp_safely"]
