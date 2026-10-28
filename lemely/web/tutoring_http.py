"""HTTP plumbing shared by every tutoring router (SPEC §b.2 legend as amended by PLAN P12, §b.5).

**Route classes.** Every tutoring router is built with one of two
``APIRoute`` subclasses, so its cache headers are set in one place and cannot be
forgotten by a handler:

* :class:`TutoringRoute`: ``Cache-Control: private, no-store`` on **every**
  response of every non-PUBLIC tutoring route (67 of 70), whatever the status:
  the 401 the token check raises, the 403 of a role guard, an ``HTTPException``
  from a handler, FastAPI's own 422 for a malformed request (SC-26: granted data,
  notes and bookings must never sit in a shared or browser cache).
* :class:`PublicTutoringRoute`: ``Cache-Control: public, max-age=60`` and
  ``X-Robots-Tag: noindex`` on P1-P3 (SC-18, PP-7: the edge read-through cache
  keys on the URL for 60 s; the JSON API itself is never indexed).

An exception raised while the route runs is turned into its response here, by
the same handler the application registered for it (FastAPI's defaults for
``HTTPException`` and ``RequestValidationError``), so the body is unchanged and
only the headers are added. An exception with no registered handler propagates
untouched (a 500 carries no data and is left to the server).

**Builders.** The public card and the logged-in profile are serialised the same
way wherever a tutoring route returns them, from the directory read models.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute

from lemely.core.keyset import CursorError
from lemely.core.tutor_directory import public_name, zone_label
from lemely.core.tutor_ratings import rating_display
from lemely.db.tutor_directory_repo import parse_directory_cursor
from lemely.web.schemas_tutoring import (
    AreaRefDTO,
    AvailabilityRuleDTO,
    DirectoryFacetsDTO,
    PublicTutorCardDTO,
    RatingDTO,
    SubjectRefDTO,
    TutorCardDTO,
    TutorProfileDTO,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterable, Mapping

    from lemely.db.tutor_directory_repo import (
        DirectoryKey,
        Facets,
        PublicCard,
        SubjectRef,
        TutorCard,
        TutorProfileView,
    )
    from lemely.io.tutoring_areas import AreaCatalogue

NO_STORE: Final = "private, no-store"
PUBLIC_CACHE: Final = "public, max-age=60"
NOINDEX: Final = "noindex"


class _HeaderRoute(APIRoute):
    """An ``APIRoute`` that sets :attr:`response_headers` on every response it produces."""

    response_headers: ClassVar[Mapping[str, str]] = MappingProxyType({})

    def get_route_handler(self) -> Callable[[Request], Coroutine[object, object, Response]]:
        """Wrap FastAPI's handler: run it, render a handled exception, then set the headers."""
        handler = super().get_route_handler()
        headers = self.response_headers

        async def with_headers(request: Request) -> Response:
            try:
                response = await handler(request)
            except Exception as exc:
                registered = _registered_handler(request, exc)
                if registered is None:
                    raise
                response = await _call_handler(registered, request, exc)
            for name, value in headers.items():
                response.headers[name] = value
            return response

        return with_headers


class TutoringRoute(_HeaderRoute):
    """Every non-PUBLIC tutoring route: ``Cache-Control: private, no-store`` on every status."""

    response_headers: ClassVar[Mapping[str, str]] = MappingProxyType({"Cache-Control": NO_STORE})


class PublicTutoringRoute(_HeaderRoute):
    """P1-P3 only: ``Cache-Control: public, max-age=60`` and ``X-Robots-Tag: noindex``."""

    response_headers: ClassVar[Mapping[str, str]] = MappingProxyType(
        {"Cache-Control": PUBLIC_CACHE, "X-Robots-Tag": NOINDEX}
    )


def _registered_handler(
    request: Request, exc: Exception
) -> Callable[[Request, Exception], object] | None:
    """The handler Starlette's exception middleware would use for ``exc``, if any."""
    registered: object = request.scope.get("starlette.exception_handlers")
    handlers: object = request.app.exception_handlers
    if isinstance(registered, tuple) and registered and isinstance(registered[0], dict):
        handlers = registered[0]
    if not isinstance(handlers, dict):
        return None
    for cls in type(exc).__mro__:
        candidate: object = handlers.get(cls)
        if callable(candidate):
            return candidate
    return None


async def _call_handler(
    handler: Callable[[Request, Exception], object], request: Request, exc: Exception
) -> Response:
    result: object = handler(request, exc)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, Response):
        raise TypeError(f"exception handler returned {type(result).__name__}, not a Response")
    return result


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def tutoring_error(status_code: int, code: str, message: str) -> HTTPException:
    """A tutoring error in the SPEC §0 shape: ``detail = {"code", "message"}``."""
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def tutor_not_found() -> HTTPException:
    """The one 404 for a tutor the caller may not see (PP-6: identical for every reason)."""
    return tutoring_error(404, "not_found", "Tutor not found.")


def decode_directory_cursor(cursor: str | None, endpoint: str) -> DirectoryKey | None:
    """The page start from a client cursor; 422 ``invalid_cursor`` for anything not minted here.

    ``endpoint`` is the list's cursor tag (P1 ``public_tutors``, SP1 ``tutors``),
    so one list's cursor is refused by the other (O21).
    """
    if cursor is None:
        return None
    try:
        return parse_directory_cursor(cursor, endpoint)
    except CursorError as exc:
        raise tutoring_error(422, "invalid_cursor", "This page link is not valid.") from exc


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def iso_instant(value: datetime) -> str:
    """An API instant: ISO-8601 in UTC with its offset (SPEC §0 "Times")."""
    return value.astimezone(UTC).isoformat()


def rating_dto(rating_sum: int, rating_count: int) -> RatingDTO:
    """The card's rating: "New" below three distinct students, else a one-decimal average."""
    shown = rating_display(rating_sum, rating_count)
    return RatingDTO(state=shown.state, average=shown.average, count=shown.count)


def area_ref_dto(code: str, areas: AreaCatalogue) -> AreaRefDTO:
    """An area by code with its catalogue name."""
    return AreaRefDTO(code=code, name=areas.name_for(code))


def subject_ref_dtos(subjects: Iterable[SubjectRef]) -> list[SubjectRefDTO]:
    """Subjects as ``{code, name}``, in the order given."""
    return [SubjectRefDTO(code=subject.code, name=subject.name) for subject in subjects]


def _card_fields(card: TutorCard, areas: AreaCatalogue) -> dict[str, object]:
    return {
        "tutorId": str(card.tutor_id),
        "publicName": public_name(card.public_first_name, card.public_last_initial),
        "headline": card.headline,
        "subjects": subject_ref_dtos(card.subjects),
        "modes": list(card.modes),
        "area": area_ref_dto(card.area_code, areas),
        "rating": rating_dto(card.rating_sum, card.rating_count),
    }


def tutor_card_dto(card: TutorCard, areas: AreaCatalogue) -> TutorCardDTO:
    """The public card (row 5b): exactly the fields the open web may see."""
    return TutorCardDTO.model_validate(_card_fields(card, areas))


def public_tutor_card_dto(card: PublicCard, areas: AreaCatalogue) -> PublicTutorCardDTO:
    """P2: the card plus ``indexable`` (row 17); no other DTO carries it (O31)."""
    return PublicTutorCardDTO.model_validate(
        {**_card_fields(card.card, areas), "indexable": card.indexable}
    )


def listed_since(first_listed_at: datetime | None, zone: str) -> str | None:
    """``"YYYY-MM"`` of the first approval in the tutor's zone; ``None`` before it."""
    if first_listed_at is None:
        return None
    return first_listed_at.astimezone(ZoneInfo(zone)).strftime("%Y-%m")


def profile_fields(view: TutorProfileView, areas: AreaCatalogue) -> dict[str, object]:
    """Every :class:`TutorProfileDTO` field of ``view`` (shared by SP2, T1 and T8)."""
    return {
        **_card_fields(view.card, areas),
        "bio": view.bio,
        "qualificationNote": view.qualification_note,
        "otherModeNote": view.other_mode_note,
        "documentsSeen": view.documents_seen,
        "availability": [
            AvailabilityRuleDTO(
                isoWeekday=rule.iso_weekday,
                startMinute=rule.start_minute,
                endMinute=rule.end_minute,
            )
            for rule in view.availability
        ],
        "zone": view.zone,
        "zoneLabel": zone_label(view.zone),
        "listedSince": listed_since(view.first_listed_at, view.zone),
    }


def tutor_profile_dto(view: TutorProfileView, areas: AreaCatalogue) -> TutorProfileDTO:
    """SP2: the logged-in profile."""
    return TutorProfileDTO.model_validate(profile_fields(view, areas))


def facets_dto(facets: Facets, areas: AreaCatalogue) -> DirectoryFacetsDTO:
    """Filter options; areas ordered by display name."""
    area_refs = sorted(
        (area_ref_dto(code, areas) for code in facets.area_codes), key=lambda ref: ref.name
    )
    return DirectoryFacetsDTO(subjects=subject_ref_dtos(facets.subjects), areas=area_refs)


__all__ = [
    "NOINDEX",
    "NO_STORE",
    "PUBLIC_CACHE",
    "PublicTutoringRoute",
    "TutoringRoute",
    "area_ref_dto",
    "decode_directory_cursor",
    "facets_dto",
    "iso_instant",
    "listed_since",
    "profile_fields",
    "public_tutor_card_dto",
    "rating_dto",
    "subject_ref_dtos",
    "tutor_card_dto",
    "tutor_not_found",
    "tutor_profile_dto",
    "tutoring_error",
]
