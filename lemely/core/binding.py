from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Same config as lemely.core.schemas.StrictModel. Declared here rather than
# imported because schemas.py imports these types, so importing back would be
# circular.


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


BindingSource = Literal["position", "label"]
BindingStatus = Literal["verified", "unverified", "unbound"]
BindingVerdict = Literal["pass", "retry", "hold"]
CheckId = Literal["G1", "G2", "G5", "G6", "G7", "G8", "G9"]


class BindingCheck(_StrictModel):
    """One gate check's outcome, paper-wide or for a set of questions."""

    id: CheckId
    passed: bool
    scope: Literal["paper", "question"]
    question_ids: list[str] = Field(default_factory=list)
    detail: str


class BindingReport(_StrictModel):
    """What the binding gate concluded about how answers were tied to questions."""

    binder: BindingSource
    checks: list[BindingCheck]
    verdict: BindingVerdict
    retried: bool = False
    model: str | None = None


class LabelMarker(_StrictModel):
    """A question label seen on a page, with its vertical position."""

    page: int
    top: int
    text: str
    kind: Literal["printed", "handwritten"]


class ReadAnswer(_StrictModel):
    """An answer read off the page that has no question assigned yet."""

    page: int
    box: list[int]
    answer: str
    working_out: str | None
    confidence: float
