"""Every model a configuration can call, by task tag.

One table for ``lemely doctor`` (its model table, the pricing checks and the
Anthropic-key check) and the web startup check, so the two cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from lemely.io.binding.orchestrate import binding_models

if TYPE_CHECKING:
    from datetime import date

    from lemely.io.llm.pricing import PriceRow
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


@dataclass(frozen=True)
class ModelRow:
    """One task tag as ``lemely doctor`` lists it."""

    tag: str
    model: str
    provider: Literal["gemini", "anthropic"]
    effort: str
    price: str | None


def _per_mtok(row: PriceRow) -> str:
    return f"{row.input * 1000:g}/{row.cached_input * 1000:g}/{row.output * 1000:g}"


def model_rows(settings: Settings, *, on: date) -> list[ModelRow]:
    """Every configured tag with its provider, effort (thinking level) and price row."""
    from lemely.io.gemini import GeminiClient, UnpricedModelError, price_row
    from lemely.io.providers import is_anthropic_model

    client = GeminiClient(settings, _genai_client=object(), ledger=None)
    rows: list[ModelRow] = []
    for tag, model in configured_models(settings).items():
        try:
            row = price_row(model, settings, on=on)
        except UnpricedModelError:
            price: str | None = None
        else:
            price = f"{_per_mtok(row)} $/MTok"
            if row.tier2 is not None and row.tier_threshold_tokens is not None:
                price += f", >{row.tier_threshold_tokens} tokens {_per_mtok(row.tier2)}"
        rows.append(
            ModelRow(
                tag=tag,
                model=model,
                provider="anthropic" if is_anthropic_model(model) else "gemini",
                effort=str(client.resolved_thinking(tag, model)),
                price=price,
            )
        )
    return rows
