"""Weekly leaderboard endpoint (``GET /api/student/leaderboard``, P5.3 chunk B).

A new router file, mirroring ``lemely.web.routers.practice``/``study_plan``:
thin, its own DTOs, no growth of ``student.py``. This router adds no ranking,
opt-out or windowing logic of its own — every one of those decisions is
D5.1's and lives in :class:`~lemely.db.leaderboard_repo.LeaderboardService`
(P5.3 chunk A). **No mark ever crosses this boundary** (D5.1 §0) — the
response DTOs in ``lemely.web.schemas_leaderboard`` structurally cannot carry
one; see that module's docstring.

**Requesting a class the viewer is not enrolled in is a 403, not a 404** —
following the precedent set by ``lemely.web.routers.quiz``'s
``QuizTakingOwnershipError`` ("the assignment exists but the caller is not
enrolled in its class") mapping to 403, the closest existing "not enrolled in
a class you asked about" case in this codebase.
:class:`~lemely.db.leaderboard_repo.LeaderboardClassAccessError` does not
distinguish "class does not exist" from "class exists but you are not in it"
(the service checks enrolment only, never class existence in isolation), so
both collapse to the identical 403 — never an existence oracle either way.

**The school scope's "viewer has no school" is not an error.** It is the
honest ``status="unavailable"`` result the service already models (mirroring
P4.5's practice-generator refusal shape) — this route returns it as a normal
200, never reshaped into a 404 or a false empty board.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lemely.db.leaderboard_repo import (
    ANONYMOUS_DISPLAY_NAME,
    DEFAULT_TOP_N,
    LeaderboardClassAccessError,
    LeaderboardIneligibleViewerError,
    LeaderboardResult,
    LeaderboardRow,
    LeaderboardScope,
    LeaderboardService,
    LeaderboardUserNotFoundError,
    LeaderboardViewerRow,
)
from lemely.db.models.enums import Role
from lemely.web.deps import AuthContext, get_leaderboard_service, require_role
from lemely.web.schemas_leaderboard import LeaderboardDTO, LeaderboardRowDTO, LeaderboardViewerDTO

if TYPE_CHECKING:
    import uuid

router = APIRouter(
    prefix="/api/student/leaderboard", dependencies=[Depends(require_role(Role.student))]
)


def _row_to_dto(
    row: LeaderboardRow, names: dict[uuid.UUID, str], streaks: dict[uuid.UUID, int]
) -> LeaderboardRowDTO:
    return LeaderboardRowDTO(
        userId=str(row.user_id),
        displayName=names.get(row.user_id, ANONYMOUS_DISPLAY_NAME),
        xp=row.xp,
        rank=row.rank,
        # `.get` with no default, deliberately: a missing key is "no streaks
        # row" and must stay `None` rather than becoming a `0` the table never
        # asserted (D5.14 §2). A real broken streak is a real `0` and arrives
        # here as one.
        streak=streaks.get(row.user_id),
    )


def _viewer_to_dto(
    viewer: LeaderboardViewerRow, names: dict[uuid.UUID, str], streaks: dict[uuid.UUID, int]
) -> LeaderboardViewerDTO:
    return LeaderboardViewerDTO(
        userId=str(viewer.user_id),
        displayName=names.get(viewer.user_id, ANONYMOUS_DISPLAY_NAME),
        xp=viewer.xp,
        rank=viewer.rank,
        streak=streaks.get(viewer.user_id),
    )


def _result_to_dto(
    result: LeaderboardResult, names: dict[uuid.UUID, str], streaks: dict[uuid.UUID, int]
) -> LeaderboardDTO:
    return LeaderboardDTO(
        status=result.status,
        unavailableReason=result.unavailable_reason.value if result.unavailable_reason else None,
        weekStart=result.week_start,
        weekEnd=result.week_end,
        rows=[_row_to_dto(row, names, streaks) for row in result.rows],
        viewer=(
            _viewer_to_dto(result.viewer, names, streaks) if result.viewer is not None else None
        ),
        viewerOptedOut=result.viewer_opted_out,
    )


@router.get("", response_model=LeaderboardDTO)
def get_leaderboard(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[LeaderboardService, Depends(get_leaderboard_service)],
    scope: str = "global",
    basis: str = "total",
    class_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = DEFAULT_TOP_N,
) -> LeaderboardDTO:
    """S-29: this week's board for the caller (D5.1 §6, Monday..Sunday Cairo).

    Query params (snake_case, mirroring ``practice.py``'s convention):

    - ``scope``: ``class``, ``school``, ``global`` or ``friends`` (readable
      spellings — never the Python enum's ``class_``/``global_``
      trailing-underscore forms). ``friends`` needs no ``class_id`` (P5.4
      chunk A, D5.6 §6 — the scope ranks the caller against their accepted
      friends, resolved from ``friendships`` directly, not a class). Unknown
      value is 422.
    - ``basis``: ``total`` for all-subjects XP, or a subject code (e.g.
      ``0625``) for a per-subject board.
    - ``class_id``: required when ``scope=class``; ignored otherwise.
      Missing when required, or malformed, is 422.
    - ``limit``: how many ranked rows to return (bounded 1..200); the
      viewer's own pinned row is always included regardless of this cut.

    Identity is always ``auth.user_id`` — there is no caller-supplied viewer
    id anywhere on this route, so one student can never request another's
    board as if it were their own; that is structural, not merely
    permission-checked.
    """
    try:
        scope_enum = LeaderboardScope(scope)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown scope: {scope!r}") from exc
    subject_code = None if basis == "total" else basis

    try:
        result = service.board(
            auth.user_id,
            scope_enum,
            subject_code=subject_code,
            class_id=class_id,
            top_n=limit,
        )
    except LeaderboardClassAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LeaderboardUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LeaderboardIneligibleViewerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    user_ids = {row.user_id for row in result.rows}
    if result.viewer is not None:
        user_ids.add(result.viewer.user_id)
    names = service.display_names_for(user_ids)
    # One batched read over the same id set, mirroring `display_names_for`
    # exactly — never a per-row query (D5.14 §2).
    streaks = service.streaks_for(user_ids)
    return _result_to_dto(result, names, streaks)


__all__ = ["router"]
