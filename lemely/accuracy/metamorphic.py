"""Label-free metamorphic properties for the marker (spec §4 M1.8, issue #58).

These properties must hold *whatever* the ground truth is, so they need no
labels and can run against the golden set today. They catch a class of marker
instability that accuracy measurement over ~31 distinct leaves is far too
underpowered to see.

Three properties, one per acceptance bullet:

``reorder_mark_points``
    Permuting a question's mark points must not change ``awarded_marks``.
``rename_mark_point_ids``
    Rewriting the mark points' ids must not change ``awarded_marks``.
``normalise_answer_whitespace``
    Collapsing whitespace runs in the student answer must not change
    ``awarded_marks``.

**A perturbation is only evidence if it preserves meaning.** Two of the three
transforms have inputs on which they demonstrably do *not*, and both are
skipped with a recorded reason rather than marked or silently dropped:

- ``AnswerPoint.is_alternative`` is defined relative to *the previous point*
  ("True if this point is an OR/EITHER…OR alternative to the previous point"),
  so a question carrying one has order-dependent semantics and permuting it
  changes what the scheme says. A violation harvested from such a question
  would be an artefact of the test, not a marker defect.
- A rename is only inert if nothing else refers to the old id. Mark schemes do
  carry free text like ``"award p2 only if p1 was given"`` in
  ``marking_guidance`` and ``notes``; renaming underneath that text leaves a
  dangling reference and changes what the marker reads.

  Free text is the case that must be *skipped*, because a transform cannot
  safely rewrite prose. The one **structured** cross-reference,
  ``AnswerPoint.required_with``, is rewritten instead — it names an id
  outright, so the rename can carry it and the leaf keeps its coverage rather
  than being discarded.

Skips are a first-class outcome here, reported per question exactly like holds
and violations. A property that could not be applied to a leaf is *not* a leaf
that passed.

This module lives in ``lemely.accuracy`` rather than ``lemely.eval`` because it
must call the correction pipeline, and the import-linter contract "Evaluation
analyses must stay pure — no IO, no app" forbids ``lemely.eval`` from importing
``lemely.io``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

import structlog

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import CorrectionResult

if TYPE_CHECKING:
    from lemely.accuracy.harness import GoldenCase

log = structlog.get_logger()

PROPERTY_REORDER = "reorder_mark_points"
PROPERTY_RENAME = "rename_mark_point_ids"
PROPERTY_WHITESPACE = "normalise_answer_whitespace"

#: Every property, in the order the issue lists them.
ALL_PROPERTIES: tuple[str, ...] = (PROPERTY_REORDER, PROPERTY_RENAME, PROPERTY_WHITESPACE)

#: Prefix applied by `rename_mark_point_ids`. Prefixing (rather than
#: renumbering) keeps ids unique by construction, since the source ids are
#: already unique within a question.
_RENAME_PREFIX = "mp_"

Status = Literal["held", "violated", "skipped"]

#: A marking function: mark *scheme* against *answers* and return the result.
#: Injected so the properties can be exercised offline with a stub, and driven
#: live with a ``cache_mode=bypass`` client without this module owning either.
MarkFn = Callable[[MarkScheme, Mapping[str, str]], CorrectionResult]

_WHITESPACE_RUN = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Outcome records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionOutcome:
    """One property applied to one leaf question.

    ``baseline_marks``/``perturbed_marks`` are ``None`` for a ``skipped``
    outcome — no marking was attempted, so there is no figure to report and a
    zero would read as a real measurement.
    """

    property_name: str
    paper_id: str
    question_id: str
    status: Status
    baseline_marks: int | None = None
    perturbed_marks: int | None = None
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "property": self.property_name,
            "paper_id": self.paper_id,
            "question_id": self.question_id,
            "status": self.status,
            "baseline_marks": self.baseline_marks,
            "perturbed_marks": self.perturbed_marks,
            "skip_reason": self.skip_reason,
        }


@dataclass(frozen=True)
class MetamorphicReport:
    """Every outcome from a run, reported per question (acceptance bullet 5)."""

    outcomes: tuple[QuestionOutcome, ...]

    @property
    def violations(self) -> tuple[QuestionOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status == "violated")

    def counts(self) -> dict[str, int]:
        tally = {"held": 0, "violated": 0, "skipped": 0}
        for outcome in self.outcomes:
            tally[outcome.status] += 1
        return tally

    def to_dict(self) -> dict[str, object]:
        return {
            "counts": self.counts(),
            "outcomes": [o.to_dict() for o in self.outcomes],
        }


# ---------------------------------------------------------------------------
# Scheme transforms
# ---------------------------------------------------------------------------


def _map_questions(
    raw: list[dict[str, object]],
    transform: Callable[[dict[str, object]], str | None],
) -> dict[str, str]:
    """Apply *transform* to every question dict in *raw*, depth first.

    *transform* mutates the dict in place and returns a skip reason, or
    ``None`` when it applied the change. Returns ``question_id -> reason`` for
    every question that was skipped.
    """
    skipped: dict[str, str] = {}
    for question in raw:
        reason = transform(question)
        if reason is not None:
            skipped[str(question.get("id", ""))] = reason
        parts = cast("list[dict[str, object]]", question.get("parts") or [])
        if parts:
            skipped.update(_map_questions(parts, transform))
    return skipped


def reorder_mark_points(scheme: MarkScheme) -> tuple[MarkScheme, dict[str, str]]:
    """Reverse each question's ``answer_points``.

    Reversal rather than a shuffle: it is deterministic, needs no seed, and
    moves every point that can move. Questions carrying an ``is_alternative``
    point are skipped — see the module docstring.
    """
    raw: dict[str, object] = scheme.model_dump(mode="json")

    def transform(question: dict[str, object]) -> str | None:
        points = cast("list[dict[str, object]]", question.get("answer_points") or [])
        if len(points) < 2:
            return "fewer than two mark points, so a permutation is a no-op"
        if any(p.get("is_alternative") for p in points):
            return (
                "carries an is_alternative point, which is defined relative to "
                "the previous point — reordering would not preserve meaning"
            )
        question["answer_points"] = list(reversed(points))
        return None

    skipped = _map_questions(cast("list[dict[str, object]]", raw["questions"]), transform)
    return MarkScheme.model_validate(raw), skipped


def _free_text_of(question: dict[str, object]) -> str:
    """Serialise everything in *question* except its own mark points and parts.

    Used to detect free text that refers to a mark-point id.
    """
    shell = {k: v for k, v in question.items() if k not in ("answer_points", "parts")}
    return json.dumps(shell, ensure_ascii=False)


def rename_mark_point_ids(scheme: MarkScheme) -> tuple[MarkScheme, dict[str, str]]:
    """Prefix every mark-point id, preserving order and marks.

    Questions whose free text mentions one of their own point ids are skipped:
    the rename would leave that reference dangling and change the scheme's
    meaning rather than only its labelling.
    """
    raw: dict[str, object] = scheme.model_dump(mode="json")

    def transform(question: dict[str, object]) -> str | None:
        points = cast("list[dict[str, object]]", question.get("answer_points") or [])
        if not points:
            return "no mark points to rename"
        free_text = _free_text_of(question)
        for point in points:
            point_id = str(point.get("id", ""))
            if point_id and point_id in free_text:
                return (
                    f"mark-point id {point_id!r} is referenced in the question's "
                    "own free text; renaming would leave it dangling"
                )
        for point in points:
            point["id"] = f"{_RENAME_PREFIX}{point['id']}"
            # `required_with` names another point's id. It is structured data
            # rather than free text, so `_free_text_of` cannot see it; rewrite
            # it here or the dependency is left pointing at an id that no
            # longer exists.
            required_with = point.get("required_with")
            if required_with:
                point["required_with"] = f"{_RENAME_PREFIX}{required_with}"
        return None

    skipped = _map_questions(cast("list[dict[str, object]]", raw["questions"]), transform)
    return MarkScheme.model_validate(raw), skipped


def normalise_answer_whitespace(answers: Mapping[str, str]) -> dict[str, str]:
    """Collapse whitespace runs to a single space and strip each answer."""
    return {qid: _WHITESPACE_RUN.sub(" ", text).strip() for qid, text in answers.items()}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _marks_by_question(result: CorrectionResult) -> dict[str, int]:
    return {q.question_id: q.awarded_marks for q in result.questions}


def check_case(
    case: GoldenCase,
    *,
    mark: MarkFn,
    properties: Sequence[str] = ALL_PROPERTIES,
) -> list[QuestionOutcome]:
    """Run *properties* against one golden case and return per-leaf outcomes.

    The case is marked once unperturbed, then once per property. Comparison is
    per question id, so one unstable leaf cannot mask a stable sibling and vice
    versa (acceptance bullet 5).
    """
    answers = {qid: golden.student_answer for qid, golden in case.ground_truth.items()}
    baseline = _marks_by_question(mark(case.mark_scheme, answers))

    outcomes: list[QuestionOutcome] = []
    for property_name in properties:
        if property_name == PROPERTY_WHITESPACE:
            perturbed_scheme = case.mark_scheme
            perturbed_answers = normalise_answer_whitespace(answers)
            skipped = {
                qid: "answer has no collapsible whitespace, so the transform is a no-op"
                for qid, text in answers.items()
                if perturbed_answers[qid] == text
            }
        elif property_name == PROPERTY_REORDER:
            perturbed_scheme, skipped = reorder_mark_points(case.mark_scheme)
            perturbed_answers = dict(answers)
        elif property_name == PROPERTY_RENAME:
            perturbed_scheme, skipped = rename_mark_point_ids(case.mark_scheme)
            perturbed_answers = dict(answers)
        else:
            raise ValueError(f"unknown metamorphic property: {property_name!r}")

        # Every leaf skipped means nothing was perturbed; marking again would
        # spend a call to compare a scheme against itself.
        if set(skipped) >= set(case.ground_truth):
            outcomes.extend(
                QuestionOutcome(
                    property_name=property_name,
                    paper_id=case.paper_id,
                    question_id=qid,
                    status="skipped",
                    skip_reason=skipped[qid],
                )
                for qid in case.ground_truth
            )
            continue

        perturbed = _marks_by_question(mark(perturbed_scheme, perturbed_answers))

        for qid in case.ground_truth:
            if qid in skipped:
                outcomes.append(
                    QuestionOutcome(
                        property_name=property_name,
                        paper_id=case.paper_id,
                        question_id=qid,
                        status="skipped",
                        skip_reason=skipped[qid],
                    )
                )
                continue
            before = baseline.get(qid)
            after = perturbed.get(qid)
            if before is None or after is None:
                # The marker returned no CorrectedQuestion for this leaf on one
                # side or the other. That is not agreement — recording it as
                # "held" would count a missing answer as a passing property.
                missing = "baseline" if before is None else "perturbed"
                outcomes.append(
                    QuestionOutcome(
                        property_name=property_name,
                        paper_id=case.paper_id,
                        question_id=qid,
                        status="skipped",
                        skip_reason=f"leaf was not marked in the {missing} run",
                    )
                )
                continue
            outcomes.append(
                QuestionOutcome(
                    property_name=property_name,
                    paper_id=case.paper_id,
                    question_id=qid,
                    status="held" if before == after else "violated",
                    baseline_marks=before,
                    perturbed_marks=after,
                )
            )
    return outcomes


def check_cases(
    cases: Iterable[GoldenCase],
    *,
    mark: MarkFn,
    properties: Sequence[str] = ALL_PROPERTIES,
) -> MetamorphicReport:
    """Run *properties* over every case in *cases*."""
    outcomes: list[QuestionOutcome] = []
    for case in cases:
        outcomes.extend(check_case(case, mark=mark, properties=properties))
    report = MetamorphicReport(outcomes=tuple(outcomes))
    log.info("metamorphic_run_complete", **report.counts())
    return report
