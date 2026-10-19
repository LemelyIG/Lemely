"""Every model a configuration can call, by task tag.

One table for ``lemely doctor`` (its model table, the pricing checks and the
Anthropic-key check) and the web startup check, so the two cannot drift apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.io.binding.orchestrate import binding_models

if TYPE_CHECKING:
    from lemely.runtime.config import Settings

#: The task tags resolved through ``GeminiSettings.model_for``.
MODEL_TABLE_TAGS: tuple[str, ...] = (
    "correction",
    "correction_borderline",
    "escalation",
    "extraction",
    "generation",
    "mark_scheme",
    "scan_metadata",
    "study_plan",
)


def configured_models(settings: Settings) -> dict[str, str]:
    """Task tag -> the model it calls under *settings*.

    The ``model_for`` tags, then ``cascade_strong`` when the cascade is on and
    names its own strong model (otherwise the cascade escalates to the
    ``escalation`` model, already listed), then the binding step's models
    (:func:`binding_models`), which it names itself rather than through
    ``model_for``.
    """
    g = settings.gemini
    models = {tag: g.model_for(tag) for tag in MODEL_TABLE_TAGS}
    if g.cascade_enabled and g.cascade_strong_model:
        models["cascade_strong"] = g.cascade_strong_model
    models.update(binding_models(settings))
    return models
