"""Every request body model rejects unknown fields (P6.3).

The P6.3 security sweep could confirm that the four ``ApiModel`` bases in
``lemely/web/schemas*.py`` each set ``extra="forbid"``, but not that every request
body actually inherits one — a body model that quietly subclasses ``BaseModel``
directly accepts and silently drops unknown keys, which is the shape of a
mass-assignment hole. Grepping for the base class cannot answer it either,
because the risk lives in *nested* models: a strict outer model whose
``list[Enrolment]`` element type is lax still takes unknown keys.

So this walks the real dependency tree of every route, collects the body models
transitively, and requires strictness of all of them. It is a gate, not a
measurement — a new lax model fails here rather than at a pen test.

Measured when written: 39 models across the whole surface, all strict.
"""

from __future__ import annotations

import typing

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel, ValidationError

from lemely.web import create_app


def _flatten(router: object) -> list[APIRoute]:
    """Collect every ``APIRoute``; included routers are wrappers, not flat routes."""
    found: list[APIRoute] = []
    for route in getattr(router, "routes", []):
        if isinstance(route, APIRoute):
            found.append(route)
        else:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                found.extend(_flatten(inner))
    return found


def _collect(annotation: object, seen: set[type[BaseModel]]) -> None:
    """Add every ``BaseModel`` reachable from ``annotation`` to ``seen``.

    Recurses through generic args (``list[X]``, ``X | None``, ``dict[str, X]``)
    and through each model's own fields, so nested bodies are covered.
    """
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return
        seen.add(annotation)
        for field in annotation.model_fields.values():
            _collect(field.annotation, seen)
        return
    for arg in typing.get_args(annotation):
        _collect(arg, seen)


def _request_models() -> set[type[BaseModel]]:
    models: set[type[BaseModel]] = set()
    for route in _flatten(create_app().router):
        dependants = [route.dependant]
        while dependants:
            dependant = dependants.pop()
            dependants.extend(dependant.dependencies)
            for param in dependant.body_params:
                _collect(param.field_info.annotation, models)
    return models


REQUEST_MODELS = sorted(_request_models(), key=lambda m: f"{m.__module__}.{m.__name__}")


def test_the_sweep_found_the_request_surface() -> None:
    """A collector that silently returns nothing would make every case below vacuous."""
    assert len(REQUEST_MODELS) >= 39


@pytest.mark.parametrize("model", REQUEST_MODELS, ids=lambda m: f"{m.__module__}.{m.__name__}")
def test_request_model_forbids_unknown_fields(model: type[BaseModel]) -> None:
    assert model.model_config.get("extra") == "forbid", (
        f"{model.__module__}.{model.__name__} accepts unknown fields; "
        "inherit an ApiModel base or set extra='forbid'"
    )


@pytest.mark.parametrize("model", REQUEST_MODELS, ids=lambda m: f"{m.__module__}.{m.__name__}")
def test_the_config_is_actually_enforced(model: type[BaseModel]) -> None:
    """Config is declarative; prove pydantic acts on it rather than trusting the flag.

    Validation is expected to fail either way here — the payload omits required
    fields. What must be true is that the *unknown key* is among the reasons.
    """
    with pytest.raises(ValidationError) as caught:
        model.model_validate({"lemely_unexpected_field": "x"})
    assert any(error["type"] == "extra_forbidden" for error in caught.value.errors()), (
        f"{model.__name__} did not report the unknown field as forbidden"
    )
