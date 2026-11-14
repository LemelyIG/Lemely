"""Per-model split of a settled usage job's LLM cost (Phase 07 task 3, part B).

``MeteredJob`` collects the split while the work runs (:mod:`lemely.io.llm.model_costs`) and
hands it here at settle, inside the settle's own transaction. The rows feed the admin margin
view; they never touch what a user is charged.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.db.models.billing_ops import UsageJobModelCost
from lemely.io.llm.model_costs import MODEL_NAME_MAX_LENGTH

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.orm import Session


def record_job_model_costs(
    session: Session, *, usage_job_id: uuid.UUID, totals: Mapping[str, Decimal]
) -> int:
    """Store one row per model for the usage job ``usage_job_id``; return the count.

    ``usage_job_id`` is the ``usage_jobs`` primary key (``UsageJob.id``). ``totals`` is the
    job's complete per-model snapshot, so a replay REPLACES the row it already wrote: it can
    neither duplicate a row nor double the money. Names are cut to the column width (the
    accumulator already does this; the cut here covers direct callers). The caller owns the
    transaction.
    """
    merged: dict[str, Decimal] = {}
    for model, cost in totals.items():
        key = model[:MODEL_NAME_MAX_LENGTH]
        merged[key] = merged.get(key, Decimal(0)) + cost
    if not merged:
        return 0
    rows = [
        {"id": uuid.uuid4(), "usage_job_id": usage_job_id, "model": model, "cost_usd": cost}
        for model, cost in merged.items()
    ]
    stmt = pg_insert(UsageJobModelCost).values(rows)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["usage_job_id", "model"],
            set_={"cost_usd": stmt.excluded.cost_usd},
        )
    )
    return len(rows)
