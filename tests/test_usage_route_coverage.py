"""Every route that can reach a paid model call is metered (billing plan phase 04 audit).

The scan reads the mounted routes' dependency trees, so it needs no request and no
database:

* a route that depends on a model-backed service factory and is neither in ``METERED`` nor
  in ``EXEMPT`` (with its reason) fails
  ``test_every_route_that_can_reach_a_model_is_accounted_for``;
* a ``METERED`` route that stops resolving the usage meter fails
  ``test_every_metered_route_resolves_the_meter``.

The dependency scan is only as wide as ``MODEL_FACTORIES``, so a second, source-level scan
(AST) covers what it cannot see: any call under ``lemely/web`` that constructs or obtains a
model client (``get_gemini_client()``, ``GeminiClient(...)``, the service and generator
constructors, the Anthropic builders) must sit inside a ``MODEL_FACTORIES`` factory, a
``METERED`` route handler, or a documented ``DIRECT_USE_EXEMPT`` helper. The scan resolves
import aliases and also flags ``getattr(obj, "<name>")`` and bare references that are
stored or passed (annotations, ``Depends(...)`` arguments and ``cache_clear()`` are not).
A route that calls ``get_gemini_client()`` in its body, aliased or not, or a new factory
that builds a client, fails
``test_every_model_client_call_sits_in_a_factory_or_a_metered_route``.

``test_the_scan_is_not_vacuous`` fails when the walk stops seeing the routes the audit
knows about. The ``test_scan_*`` tests prove each check goes red on a synthetic app or
source, so they cannot rot into always-green.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NamedTuple

from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute

import lemely.web
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
#: A function in the source scan: ``(dotted module, outermost enclosing function's qualname)``.
Scope = tuple[str, str]

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


#: Names whose call constructs or obtains a paid model client, or builds a service or
#: generator around one. Anthropic and Google SDK clients are built only inside
#: ``GeminiClient`` (``lemely/io/gemini.py``), so web code reaches them through these.
MODEL_CALL_NAMES: frozenset[str] = frozenset(
    {
        "get_gemini_client",
        "GeminiClient",
        "ClaudeProvider",
        "GeminiProvider",
        "AnthropicAdapter",
        "Anthropic",
        "AsyncAnthropic",
        "genai.Client",
        "get_quiz_marking_service",
        "get_self_review_service",
        "get_flashcard_service",
        "QuizMarkingService",
        "SelfReviewService",
        "FlashcardService",
        "QuestionGenerator",
        "FlashcardGenerator",
        "GeminiEvidenceJudge",
        "build_self_review_judge",
    }
)

#: Helpers that build model-backed objects for a listed scope. Each is a documented
#: exemption: its own body may name a client builder, and its callers are checked too.
DIRECT_USE_EXEMPT: Mapping[Scope, str] = {
    ("lemely.web.deps", "build_self_review_judge"): (
        "wraps the shared Gemini client in the lenient judge; called only by "
        "get_self_review_service"
    ),
    ("lemely.web.routers.teacher", "_build_quiz"): (
        "builds the question generator; called only by _build_quiz_metered"
    ),
    ("lemely.web.routers.teacher", "_build_quiz_metered"): (
        "runs _build_quiz inside the metered job; called only by the metered quiz preview "
        "and generate handlers"
    ),
}


class ModelUse(NamedTuple):
    """One mention in the web source of a way to construct or obtain a model client."""

    module: str
    line: int
    name: str
    scope: Scope | None  # None: outside any function


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr}" if head else node.attr
    return None


_DEPENDENCY_MARKERS = frozenset({"Depends", "Security"})
_CACHE_METHODS = frozenset({"cache_clear", "cache_info"})


def _subtree_ids(nodes: Iterable[ast.AST | None]) -> set[int]:
    return {id(sub) for node in nodes if node is not None for sub in ast.walk(node)}


def _legitimate_reference_ids(tree: ast.AST) -> set[int]:
    """Nodes whose mention of a listed name is not a way to reach a model.

    Type annotations; the argument of ``Depends(...)`` or ``Security(...)`` (the
    dependency scan owns those); and the factory in ``factory.cache_clear()``.
    """
    nodes: list[ast.AST | None] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            args = node.args
            every_arg = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
            nodes.extend(arg.annotation for arg in every_arg if arg is not None)
            nodes.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            nodes.append(node.annotation)
        elif isinstance(node, ast.Call):
            callee = _dotted(node.func)
            if callee is not None and callee.rsplit(".", 1)[-1] in _DEPENDENCY_MARKERS:
                nodes.extend(node.args)
                nodes.extend(keyword.value for keyword in node.keywords)
        elif isinstance(node, ast.Attribute) and node.attr in _CACHE_METHODS:
            nodes.append(node.value)
    return _subtree_ids(nodes)


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """``from x import name as alias`` and ``import x.y as alias``, alias to real name."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            for imported in node.names:
                if imported.asname:
                    aliases[imported.asname] = imported.name.rsplit(".", 1)[-1]
    return aliases


def model_uses(
    module: str, source: str, names: Collection[str] = MODEL_CALL_NAMES
) -> list[ModelUse]:
    """Every mention in ``source`` of one of ``names``, with its outermost enclosing function.

    A mention is a call, an aliased call (``from x import get_gemini_client as g``), a
    ``getattr(obj, "<name>")``, or a bare reference that is passed or stored (so
    ``build = deps.get_gemini_client`` is caught where it is made). Annotations,
    ``Depends(...)`` arguments and ``factory.cache_clear()`` are not mentions.
    """
    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    legitimate = _legitimate_reference_ids(tree)
    found: list[ModelUse] = []

    def flag(node: ast.AST, name: str, scope: Scope | None) -> None:
        found.append(ModelUse(module, getattr(node, "lineno", 0), name, scope))

    def visit(node: ast.AST, qual: list[str], scope: Scope | None) -> None:
        if isinstance(node, ast.ClassDef):
            qual = [*qual, node.name]
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and scope is None:
            qual = [*qual, node.name]
            scope = (module, ".".join(qual))
        if id(node) not in legitimate:
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                real = aliases.get(node.id, node.id)
                if real in names:
                    flag(node, real, scope)
            elif isinstance(node, ast.Attribute):
                dotted = _dotted(node)
                if dotted is not None and (dotted in names or node.attr in names):
                    flag(node, dotted, scope)
            elif (
                isinstance(node, ast.Call)
                and _dotted(node.func) == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in names
            ):
                flag(node, f"getattr:{node.args[1].value}", scope)
        for child in ast.iter_child_nodes(node):
            visit(child, qual, scope)

    visit(tree, [], None)
    return found


def web_model_uses() -> list[ModelUse]:
    """``model_uses`` over every module under ``lemely/web``, helper names included."""
    root = Path(lemely.web.__file__).parent
    names = MODEL_CALL_NAMES | {qual.rsplit(".", 1)[-1] for _, qual in DIRECT_USE_EXEMPT}
    uses: list[ModelUse] = []
    for path in sorted(root.rglob("*.py")):
        parts = ["lemely", "web", *path.relative_to(root).with_suffix("").parts]
        if parts[-1] == "__init__":
            parts.pop()
        uses.extend(model_uses(".".join(parts), path.read_text(), names))
    return uses


def _scope_of(function: Callable[..., object]) -> Scope:
    return (function.__module__, function.__qualname__)


def allowed_scopes(routes: Mapping[Key, APIRoute], metered: Collection[Key]) -> set[Scope]:
    """The functions allowed to name a model client: factories, metered handlers, helpers."""
    handlers = {_scope_of(routes[key].endpoint) for key in metered if key in routes}
    return {_scope_of(f) for f in MODEL_FACTORIES} | handlers | set(DIRECT_USE_EXEMPT)


def unaccounted_model_uses(uses: Iterable[ModelUse], allowed: Collection[Scope]) -> list[ModelUse]:
    """The uses that sit outside every allowed function (or outside any function)."""
    return [use for use in uses if use.scope not in allowed]


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


def test_every_model_client_call_sits_in_a_factory_or_a_metered_route() -> None:
    stray = unaccounted_model_uses(web_model_uses(), allowed_scopes(_app_routes(), METERED))
    assert not stray, (
        "code under lemely/web constructs or obtains a model client outside a listed "
        f"factory, a metered route or a documented helper: {stray}. Meter the route "
        "(and add it to METERED), register the factory in MODEL_FACTORIES, or document "
        "the helper in DIRECT_USE_EXEMPT."
    )


def test_the_source_scan_is_not_vacuous() -> None:
    uses = web_model_uses()
    scopes = {use.scope for use in uses}
    assert {_scope_of(f) for f in MODEL_FACTORIES} <= scopes
    assert set(DIRECT_USE_EXEMPT) <= scopes
    # Every listed helper is called from somewhere that is allowed (checked above), and
    # a stale entry fails here rather than lingering.
    called = {use.name.rsplit(".", 1)[-1] for use in uses}
    assert {qual.rsplit(".", 1)[-1] for _, qual in DIRECT_USE_EXEMPT} <= called
    assert all(reason.strip() for reason in DIRECT_USE_EXEMPT.values())


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


_MUTANT_ROUTE = """
from fastapi import APIRouter
from lemely.web.deps import get_gemini_client

router = APIRouter()


@router.post("/api/student/study-plan/_mutant-paid")
def mutant_paid() -> None:
    client = get_gemini_client()
    client.generate_structured()
"""


def test_source_scan_goes_red_on_a_route_that_calls_the_client_in_its_body() -> None:
    uses = model_uses("lemely.web.routers.study_plan", _MUTANT_ROUTE)
    assert [(u.name, u.scope) for u in uses] == [
        ("get_gemini_client", ("lemely.web.routers.study_plan", "mutant_paid"))
    ]
    allowed = allowed_scopes(_app_routes(), METERED)
    assert unaccounted_model_uses(uses, allowed) == uses
    # The same call inside a metered handler is fine.
    metered_scope = _scope_of(_app_routes()[("POST", "/api/student/study-plan")].endpoint)
    assert (
        unaccounted_model_uses(uses, allowed | {("lemely.web.routers.study_plan", "mutant_paid")})
        == []
    )
    assert metered_scope in allowed


def test_source_scan_goes_red_on_a_new_factory_and_on_nested_and_module_level_calls() -> None:
    source = """
from lemely.io.gemini import GeminiClient

_AT_IMPORT = GeminiClient(None)


def get_new_service():
    return Service(GeminiClient(settings))


class Holder:
    def build(self):
        def worker():
            return QuestionGenerator(client)
        return worker
"""
    uses = model_uses("lemely.web.deps", source)
    assert [(u.name, u.scope) for u in uses] == [
        ("GeminiClient", None),
        ("GeminiClient", ("lemely.web.deps", "get_new_service")),
        ("QuestionGenerator", ("lemely.web.deps", "Holder.build")),
    ]
    assert unaccounted_model_uses(uses, allowed_scopes(_app_routes(), METERED)) == uses


def test_source_scan_matches_attribute_calls_and_ignores_other_names() -> None:
    source = """
import anthropic
from google import genai


def f():
    anthropic.Anthropic()
    genai.Client(api_key="x")
    helpers.get_gemini_client()
    unrelated()
    GeminiClientSettings()
"""
    assert [u.name for u in model_uses("m", source)] == [
        "anthropic.Anthropic",
        "genai.Client",
        "helpers.get_gemini_client",
    ]


_ALIASED_MUTANT = """
from fastapi import APIRouter
from lemely.web.deps import get_gemini_client as _model_client

router = APIRouter()


@router.post("/api/student/study-plan/_mutant-aliased")
def mutant_aliased() -> None:
    _model_client()
"""


def test_source_scan_goes_red_on_an_aliased_import() -> None:
    uses = model_uses("lemely.web.routers.study_plan", _ALIASED_MUTANT)
    assert [(u.name, u.scope) for u in uses] == [
        ("get_gemini_client", ("lemely.web.routers.study_plan", "mutant_aliased"))
    ]
    assert unaccounted_model_uses(uses, allowed_scopes(_app_routes(), METERED)) == uses


def test_source_scan_resolves_aliases_for_classes_and_modules_too() -> None:
    source = """
from lemely.io.gemini import GeminiClient as Model
import lemely.web.deps as plumbing


def f():
    Model(None)
    plumbing.get_gemini_client()
"""
    assert [u.name for u in model_uses("m", source)] == [
        "GeminiClient",
        "plumbing.get_gemini_client",
    ]


def test_source_scan_goes_red_on_getattr_and_on_stored_or_passed_references() -> None:
    source = """
from lemely.web import deps


def by_getattr():
    return getattr(deps, "get_gemini_client")()


def stored():
    build = deps.get_gemini_client
    return build()


def passed():
    return run(get_flashcard_service)


def in_a_table():
    return {"model": GeminiClient}
"""
    uses = model_uses("lemely.web.routers.sneaky", source)
    assert [(u.scope[1] if u.scope else None, u.name) for u in uses] == [
        ("by_getattr", "getattr:get_gemini_client"),
        ("stored", "deps.get_gemini_client"),
        ("passed", "get_flashcard_service"),
        ("in_a_table", "GeminiClient"),
    ]
    assert unaccounted_model_uses(uses, allowed_scopes(_app_routes(), METERED)) == uses


def test_source_scan_ignores_dependencies_annotations_and_cache_clears() -> None:
    """The legitimate bare references: ``Depends(...)`` (the dependency scan owns those),
    type annotations, and ``cache_clear()`` on a factory."""
    source = """
from typing import Annotated
from fastapi import Depends


def handler(
    client: Annotated[GeminiClient, Depends(get_gemini_client)],
    service: "SelfReviewService" = Depends(get_self_review_service),
) -> FlashcardService:
    return None


def reset() -> None:
    get_gemini_client.cache_clear()
    get_flashcard_service.cache_info()


count: QuizMarkingService | None = None
"""
    assert model_uses("m", source) == []
