"""Every route that can reach a paid model call is metered (billing plan phase 04 audit).

The scan reads the mounted routes' dependency trees, so it needs no request and no
database:

* a route that depends on a model-backed service factory and is neither in ``METERED`` nor
  in ``EXEMPT`` (with its reason) fails
  ``test_every_route_that_can_reach_a_model_is_accounted_for``;
* a ``METERED`` route that stops resolving the usage meter fails
  ``test_every_metered_route_resolves_the_meter``.

The scan is only as wide as ``MODEL_FACTORIES``: a new factory that builds a model client
into a service must be added there. ``test_the_scan_is_not_vacuous`` fails when the walk
stops seeing the routes the audit knows about. The ``test_scan_*`` tests prove the two
checks go red on a synthetic app, so they cannot rot into always-green.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute

from lemely.web import create_app
from lemely.web.deps import (
    get_flashcard_service,
    get_gemini_client,
    get_quiz_marking_service,
    get_self_review_service,
)
from lemely.web.usage import get_usage_meter
from tests.tutoring_app import flatten_routes

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Mapping

    from fastapi.dependencies.models import Dependant

Key = tuple[str, str]

#: Dependencies that put a paid model behind a route: the Gemini client itself, and every
#: service factory that builds one in (quiz marker, self-review judge, flashcard generator).
MODEL_FACTORIES: tuple[Callable[..., object], ...] = (
    get_gemini_client,
    get_quiz_marking_service,
    get_self_review_service,
    get_flashcard_service,
)

#: The audit's route list (plan "Audit" table), method and path as mounted. The study-plan
#: route makes no model call today but is metered (seeded 0 to 0 estimate), so it is here.
METERED: frozenset[Key] = frozenset(
    {
        ("POST", "/api/student/correct"),
        ("POST", "/api/papers/upload"),
        ("POST", "/api/papers/{paper_id}/regrade"),
        ("POST", "/api/quizzes/preview"),
        ("POST", "/api/quizzes/generate"),
        ("POST", "/api/student/attempts/{attempt_id}/questions/{question_result_id}/self-review"),
        ("POST", "/api/student/flashcards/decks/generate"),
        ("POST", "/api/student/quizzes/{assignment_id}/submit"),
        ("POST", "/api/student/study-plan"),
    }
)

_FLASHCARD_NO_MODEL = (
    "shares the flashcard service with the metered generate route, but only reads or "
    "edits stored decks and cards; nothing calls FlashcardGenerator"
)
_SELF_REVIEW_NO_MODEL = (
    "shares the self-review service with the metered POST, but only reads stored "
    "questions and challenges; the judge is called only from the POST"
)
QUESTION_BANK_ROUTE: Key = ("POST", "/api/teacher/quizzes/{quiz_id}/questions/generate")

#: Routes the scan may find but that are deliberately not metered, each with its reason.
EXEMPT: Mapping[Key, str] = {
    QUESTION_BANK_ROUTE: (
        "a deterministic query over the existing question bank: no model call, so nothing "
        "to charge (phase 04 Task 11 pins it as unmetered)"
    ),
    ("GET", "/api/student/flashcards/decks"): _FLASHCARD_NO_MODEL,
    ("POST", "/api/student/flashcards/decks"): _FLASHCARD_NO_MODEL,
    ("GET", "/api/student/flashcards/decks/{deck_id}"): _FLASHCARD_NO_MODEL,
    ("DELETE", "/api/student/flashcards/decks/{deck_id}"): _FLASHCARD_NO_MODEL,
    ("POST", "/api/student/flashcards/decks/{deck_id}/cards"): _FLASHCARD_NO_MODEL,
    ("PATCH", "/api/student/flashcards/cards/{card_id}"): _FLASHCARD_NO_MODEL,
    ("DELETE", "/api/student/flashcards/cards/{card_id}"): _FLASHCARD_NO_MODEL,
    ("GET", "/api/student/flashcards/due"): _FLASHCARD_NO_MODEL,
    ("POST", "/api/student/flashcards/cards/{card_id}/review"): _FLASHCARD_NO_MODEL,
    ("GET", "/api/student/attempts/{attempt_id}/questions"): _SELF_REVIEW_NO_MODEL,
    (
        "GET",
        "/api/student/attempts/{attempt_id}/questions/{question_result_id}/self-review",
    ): _SELF_REVIEW_NO_MODEL,
}

_HIDDEN_METHODS = frozenset({"HEAD", "OPTIONS"})


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for sub in dependant.dependencies:
        yield from _walk(sub)


def _calls(route: APIRoute) -> set[object]:
    return {d.call for d in _walk(route.dependant)}


def _keyed(routes: Iterable[APIRoute]) -> dict[Key, APIRoute]:
    return {
        (method, route.path): route
        for route in routes
        for method in route.methods
        if method not in _HIDDEN_METHODS
    }


def model_reaching(routes: Mapping[Key, APIRoute]) -> set[Key]:
    """The routes whose dependency tree contains a model-backed factory."""
    return {key for key, route in routes.items() if _calls(route) & set(MODEL_FACTORIES)}


def unaccounted_model_routes(
    routes: Mapping[Key, APIRoute], metered: Collection[Key], exempt: Collection[Key]
) -> set[Key]:
    """Routes that can reach a model and are neither metered nor exempt."""
    return model_reaching(routes) - set(metered) - set(exempt)


def metered_routes_without_meter(
    routes: Mapping[Key, APIRoute], metered: Collection[Key]
) -> set[Key]:
    """Metered routes that are missing, or no longer resolve the usage meter."""
    return {
        key for key in metered if key not in routes or get_usage_meter not in _calls(routes[key])
    }


def _app_routes() -> dict[Key, APIRoute]:
    return _keyed(flatten_routes(create_app()))


# ---------------------------------------------------------------------------
# The real application
# ---------------------------------------------------------------------------


def test_every_route_that_can_reach_a_model_is_accounted_for() -> None:
    missed = unaccounted_model_routes(_app_routes(), METERED, EXEMPT)
    assert not missed, (
        f"routes that can reach a paid model are not metered: {sorted(missed)}. "
        "Meter them (require_usage or meter.job) and add them to METERED, or add them to "
        "EXEMPT with the reason they make no model call."
    )


def test_every_metered_route_resolves_the_meter() -> None:
    unmetered = metered_routes_without_meter(_app_routes(), METERED)
    assert not unmetered, f"metered routes that do not resolve the usage meter: {sorted(unmetered)}"


def test_the_scan_is_not_vacuous() -> None:
    """The walk must see the audited model routes, or a green scan means nothing."""
    routes = _app_routes()
    study_plan: Key = ("POST", "/api/student/study-plan")
    assert model_reaching(routes) >= METERED - {study_plan}
    assert set(routes) >= METERED


def test_exemptions_name_live_unmetered_routes() -> None:
    """A stale exemption (route renamed, or since metered) fails instead of lingering."""
    routes = _app_routes()
    assert set(EXEMPT) <= set(routes), sorted(set(EXEMPT) - set(routes))
    assert not set(EXEMPT) & METERED
    assert all(reason.strip() for reason in EXEMPT.values())


def test_the_question_bank_route_stays_a_deterministic_query() -> None:
    """The one exemption the scan cannot see through: it must stay free of model factories.

    If a model-backed service is ever injected here, meter the route as ``generate_quiz``
    through ``TeamActor`` (Task 11's seat), move it to ``METERED`` and drop this exemption.
    """
    route = _app_routes()[QUESTION_BANK_ROUTE]
    assert not _calls(route) & set(MODEL_FACTORIES)


# ---------------------------------------------------------------------------
# Proof the scan goes red (synthetic app: no request is ever made)
# ---------------------------------------------------------------------------


def _synthetic_routes() -> dict[Key, APIRoute]:
    router = APIRouter(prefix="/api/synthetic")

    @router.post("/metered-ok")
    def metered_ok(
        client: Annotated[object, Depends(get_gemini_client)],
        meter: Annotated[object, Depends(get_usage_meter)],
    ) -> None:
        return None

    @router.post("/lost-its-meter")
    def lost_its_meter(client: Annotated[object, Depends(get_gemini_client)]) -> None:
        return None

    @router.post("/new-paid-route")
    def new_paid_route(marker: Annotated[object, Depends(get_quiz_marking_service)]) -> None:
        return None

    @router.get("/documented-exemption")
    def documented_exemption(cards: Annotated[object, Depends(get_flashcard_service)]) -> None:
        return None

    @router.get("/no-model")
    def no_model() -> None:
        return None

    app = FastAPI()
    app.include_router(router)
    return _keyed(flatten_routes(app))


_OK: Key = ("POST", "/api/synthetic/metered-ok")
_LOST: Key = ("POST", "/api/synthetic/lost-its-meter")
_NEW: Key = ("POST", "/api/synthetic/new-paid-route")
_DOCUMENTED: Key = ("GET", "/api/synthetic/documented-exemption")


def test_scan_goes_red_when_a_new_paid_route_has_no_meter() -> None:
    routes = _synthetic_routes()
    assert model_reaching(routes) == {_OK, _LOST, _NEW, _DOCUMENTED}
    assert unaccounted_model_routes(routes, {_OK, _LOST, _NEW}, {_DOCUMENTED}) == set()
    # The new route is not listed anywhere: the scan names exactly it.
    assert unaccounted_model_routes(routes, {_OK, _LOST}, {_DOCUMENTED}) == {_NEW}
    # Listing it is not enough without the exemption or the meter being real.
    assert unaccounted_model_routes(routes, {_OK, _LOST}, set()) == {_NEW, _DOCUMENTED}


def test_scan_goes_red_when_a_metered_route_loses_its_meter() -> None:
    routes = _synthetic_routes()
    assert metered_routes_without_meter(routes, {_OK}) == set()
    assert metered_routes_without_meter(routes, {_OK, _LOST}) == {_LOST}
    # A listed route that is not mounted at all also fails.
    gone: Key = ("POST", "/api/synthetic/gone")
    assert metered_routes_without_meter(routes, {_OK, gone}) == {gone}


def _meter_dependency(meter: Annotated[object, Depends(get_usage_meter)]) -> object:
    return meter


def test_scan_sees_the_meter_through_a_nested_dependency() -> None:
    """``require_usage`` is a sub-dependency, not a parameter of the endpoint itself."""

    router = APIRouter(prefix="/api/nested")

    @router.post("/paid")
    def paid(
        client: Annotated[object, Depends(get_gemini_client)],
        usage: Annotated[object, Depends(_meter_dependency)],
    ) -> None:
        return None

    app = FastAPI()
    app.include_router(router)
    routes = _keyed(flatten_routes(app))
    key: Key = ("POST", "/api/nested/paid")
    assert metered_routes_without_meter(routes, {key}) == set()
    assert unaccounted_model_routes(routes, {key}, set()) == set()
