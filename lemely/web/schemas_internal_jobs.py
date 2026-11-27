"""DTO for the Cloud Scheduler sweep trigger (``POST /api/internal/jobs/sweep``)."""

from __future__ import annotations

from typing import Literal

from lemely.web.schemas import ApiModel


class SweepResultDTO(ApiModel):
    """What one triggered pass did: job names and counts, never rows or exception text.

    ``jobs`` maps each job that ran to the rows it handled, or ``None`` for a job that raised;
    ``failed`` lists those names. ``skipped`` lists the jobs not started because the pass had
    spent its time budget: they did not fail, and the next pass runs them again in the usual
    order. A batch job that stopped between rows at its share of the budget counts as run, with
    the rows it finished; the rest wait for a later pass. A pass skipped as a whole because
    another was running has no jobs and an empty ``skipped``.
    """

    status: Literal["completed", "skipped"]
    jobs: dict[str, int | None]
    failed: list[str]
    skipped: list[str]


__all__ = ["SweepResultDTO"]
