from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Same config as lemely.core.schemas.StrictModel. Declared here rather than
# imported because schemas.py imports these types, so importing back would be
# circular.


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# "legacy": the model handed out the question ids itself (the extractor as it was
# before the label binder), as opposed to "label", bound from the labels it listed.
BindingSource = Literal["position", "label", "legacy"]
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


class SeenLabel(_StrictModel):
    """A question label the reader saw, in the place it holds in the reading-order list.

    The reader never says which question it is. ``box`` is kept for display only:
    nothing that binds a label to a question reads it.
    """

    page: int
    text: str
    kind: Literal["printed", "handwritten"]
    box: list[int] | None = None


class SeenWriting(_StrictModel):
    """A block of student writing, in the place it holds in the reading-order list."""

    page: int
    answer: str
    working_out: str | None = None
    confidence: float = 0.0
    box: list[int] | None = None
    placed_by: Literal["position", "arrow", "uncertain"] = "position"


StreamItem = SeenLabel | SeenWriting

# ``schemas.ExtractedAnswers.unbound_answers`` is typed ``list[ReadAnswer]``: writing
# that no question could be given. That is a ``SeenWriting``; the old name is kept so
# that ``schemas.py`` keeps importing it.
ReadAnswer = SeenWriting

UnboundReason = Literal[
    "before_first_label",
    "after_unplaced_label",
    "after_container_label",
    "uncertain",
    # The label the paper prints next was not seen, so this writing may be that
    # question's and not the one whose label it follows.
    "next_label_not_seen",
    # The same, where the scheme's next id is one no label can name ("1a_i_A"): the
    # list can never show where this leaf's writing ends.
    "next_label_unreadable",
    # The leaf this writing follows holds two blocks or more and the leaf beside it
    # holds none: one of the blocks may be the neighbour's, its label listed out of place.
    "neighbour_left_blank",
]


class UnboundWriting(_StrictModel):
    """Writing that was not given to a question, and why."""

    writing: SeenWriting
    reason: UnboundReason
