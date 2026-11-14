"""Per-model split of a settled usage job's LLM cost (Phase 07 task 3, part B).

``MeteredJob`` collects the split while the work runs (:mod:`lemely.io.llm.model_costs`) and
hands it here at settle, inside the settle's own transaction. The rows feed the admin margin
view; they never touch what a user is charged.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.db.models.billing_ops import UsageJobModelCost
from lemely.db.models.usage import UsageJob
from lemely.io.llm.model_costs import MODEL_NAME_MAX_LENGTH

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.orm import Session


def record_job_model_costs(
    session: Session, *, job_id: uuid.UUID, totals: Mapping[str, Decimal]
) -> int:
    """Store one row per model for the job whose metering id is ``job_id``; return the count.

    ``job_id`` is ``UsageJob.job_id`` (the id the meter reserved under), not the row's primary
    key. A replay adds to the row it already wrote rather than duplicating it (unique on job
    and model). Raises :class:`LookupError` when no such job exists. The caller owns the
    transaction.
    """
    if not totals:
        return 0
    usage_job_id = session.scalar(sa.select(UsageJob.id).where(UsageJob.job_id == job_id))
    if usage_job_id is None:
        raise LookupError(f"no usage job with job_id {job_id}")
    merged: dict[str, Decimal] = {}
    for model, cost in totals.items():
        key = model[:MODEL_NAME_MAX_LENGTH]
        merged[key] = merged.get(key, Decimal(0)) + cost
    rows = [
        {"id": uuid.uuid4(), "usage_job_id": usage_job_id, "model": model, "cost_usd": cost}
        for model, cost in merged.items()
    ]
    stmt = pg_insert(UsageJobModelCost).values(rows)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["usage_job_id", "model"],
            set_={"cost_usd": UsageJobModelCost.cost_usd + stmt.excluded.cost_usd},
        )
    )
    return len(rows)
