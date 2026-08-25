"""Append-only, hash-chained ruling log (spec §3.1, DA3/#52, H8).

Per DA3 (``BUILD/DECISIONS.md``): a ruling is a *record*, not an authority
— the person raising a judgement question during labelling is the same
person ruling on it. Its entire value is the written record that later
sessions and labeller B (DA2/#51) can be calibrated against. This module
therefore ships:

- **Scope as a machine-evaluable predicate** (:class:`RulingScope`,
  :func:`applies_to`) over a fixed small set of label fields — syllabus
  code, tariff band, parse path, the labeller's own type judgement, and
  mark-scheme token presence (e.g. ``oe``/``ecf``). This is what makes "the
  corpus is consistent under the final rule set" a checkable claim rather
  than something the labeller has to remember.
- **Supersede records**: a ruling is never edited or deleted in place. A
  later record supersedes an earlier one by id; both remain readable and
  the hash chain stays intact — this is what makes DA3's *one deferred
  sweep before the split freeze* expressible.
- **``pending_ruling`` parking**: a mid-session judgement question is
  recorded as pending, not guessed, and the session continues. DA3 requires
  the pending tail to reach zero before the freeze.

Every append here reuses :func:`lemely.labelling.records.append_record` /
:func:`lemely.labelling.records.record_hash` /
:func:`lemely.labelling.records.read_records` — there is deliberately no
second hash-chain implementation in this module.

**A ruling is never resolved by looking at pipeline output.** This is
enforced structurally, not by convention: the "blind labeller must not
depend on the correction pipeline" import-linter contract in
``pyproject.toml`` covers all of ``lemely.labelling`` (this module lives
inside it), and
``tests/architecture/test_rulings_import_contract.py`` proves that contract
actually fires for this module specifically.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, TypedDict

from lemely.eval.manifest import StrictModel
from lemely.labelling.paths import DEFAULT_EVAL_ROOT, rulings_path
from lemely.labelling.records import append_record, read_records

if TYPE_CHECKING:
    from pathlib import Path


class RulingScope(StrictModel):
    """A machine-evaluable scope predicate over a fixed set of label fields.

    Every field is optional; an unset (``None``) field is a wildcard — it
    imposes no constraint and matches any leaf. ``mark_scheme_tokens``, when
    set, matches a leaf iff the leaf's token set intersects it (i.e. the
    ruling applies if the leaf's mark scheme carries *any* of the named
    tokens, e.g. ``oe`` or ``ecf``).
    """

    syllabus_code: str | None = None
    tariff_band: str | None = None
    parse_path: str | None = None
    question_type_judgement: str | None = None
    mark_scheme_tokens: list[str] | None = None


class LeafFields(TypedDict):
    """The fixed set of label fields a ruling's scope may be evaluated against."""

    syllabus_code: str
    tariff_band: str
    parse_path: str
    question_type_judgement: str
    mark_scheme_tokens: list[str]


def applies_to(scope: RulingScope, leaf_fields: LeafFields) -> bool:
    """Pure predicate: does ``scope`` apply to a leaf carrying ``leaf_fields``?

    An unset scope field matches unconditionally. A set field must match the
    leaf's corresponding value exactly, except ``mark_scheme_tokens``, which
    matches on non-empty intersection (any-of), not exact-set-equality.
    """
    if scope.syllabus_code is not None and scope.syllabus_code != leaf_fields["syllabus_code"]:
        return False
    if scope.tariff_band is not None and scope.tariff_band != leaf_fields["tariff_band"]:
        return False
    if scope.parse_path is not None and scope.parse_path != leaf_fields["parse_path"]:
        return False
    if (
        scope.question_type_judgement is not None
        and scope.question_type_judgement != leaf_fields["question_type_judgement"]
    ):
        return False
    if scope.mark_scheme_tokens is None:
        return True
    return bool(set(scope.mark_scheme_tokens) & set(leaf_fields["mark_scheme_tokens"]))


class RulingPayload(StrictModel):
    """One ruling record: a scope predicate plus the decision it governs."""

    ruling_id: str
    scope: RulingScope
    decision: str
    labeller_id: str
    supersedes: str | None = None
    """The ``ruling_id`` this record supersedes, or ``None`` for an original
    (non-superseding) ruling."""


class PendingRulingPayload(StrictModel):
    """A mid-session judgement question, parked rather than guessed (DA3)."""

    pending_id: str
    paper_id: str
    question_id: str
    question: str
    labeller_id: str


class PendingRulingResolvedPayload(StrictModel):
    """Marks a previously-parked pending ruling as resolved.

    Append-only: resolving a pending ruling never mutates or removes the
    original ``pending_ruling`` record, it appends a new record referencing
    it by ``pending_id``.
    """

    pending_id: str
    resolving_ruling_id: str
    labeller_id: str


def append_ruling(
    *,
    scope: RulingScope,
    decision: str,
    labeller_id: str,
    eval_root: Path = DEFAULT_EVAL_ROOT,
    ruling_id: str | None = None,
) -> dict[str, object]:
    """Append one original (non-superseding) ruling record."""
    payload = RulingPayload(
        ruling_id=ruling_id or uuid.uuid4().hex,
        scope=scope,
        decision=decision,
        labeller_id=labeller_id,
        supersedes=None,
    )
    return append_record(rulings_path(eval_root), payload.model_dump(mode="json"))


def append_supersede_ruling(
    *,
    supersedes_ruling_id: str,
    scope: RulingScope,
    decision: str,
    labeller_id: str,
    eval_root: Path = DEFAULT_EVAL_ROOT,
    ruling_id: str | None = None,
) -> dict[str, object]:
    """Append a ruling that supersedes an earlier one by id.

    The earlier record is never edited or removed; both remain readable via
    :func:`~lemely.labelling.records.read_records` and the hash chain stays
    intact (DA3's "supersede, don't rewrite").
    """
    payload = RulingPayload(
        ruling_id=ruling_id or uuid.uuid4().hex,
        scope=scope,
        decision=decision,
        labeller_id=labeller_id,
        supersedes=supersedes_ruling_id,
    )
    return append_record(rulings_path(eval_root), payload.model_dump(mode="json"))


def append_pending_ruling(
    *,
    paper_id: str,
    question_id: str,
    question: str,
    labeller_id: str,
    eval_root: Path = DEFAULT_EVAL_ROOT,
    pending_id: str | None = None,
) -> dict[str, object]:
    """Park a mid-session judgement question rather than guessing (DA3)."""
    payload = PendingRulingPayload(
        pending_id=pending_id or uuid.uuid4().hex,
        paper_id=paper_id,
        question_id=question_id,
        question=question,
        labeller_id=labeller_id,
    )
    return append_record(rulings_path(eval_root), payload.model_dump(mode="json"))


def resolve_pending_ruling(
    *,
    pending_id: str,
    resolving_ruling_id: str,
    labeller_id: str,
    eval_root: Path = DEFAULT_EVAL_ROOT,
) -> dict[str, object]:
    """Append a record marking ``pending_id`` resolved, without mutating it."""
    payload = PendingRulingResolvedPayload(
        pending_id=pending_id,
        resolving_ruling_id=resolving_ruling_id,
        labeller_id=labeller_id,
    )
    return append_record(rulings_path(eval_root), payload.model_dump(mode="json"))


def _pending_and_resolved_ids(eval_root: Path) -> tuple[list[dict[str, object]], set[str]]:
    records = read_records(rulings_path(eval_root))
    pending_records: list[dict[str, object]] = []
    resolved_ids: set[str] = set()
    for record in records:
        payload = record["payload"]
        if not isinstance(payload, dict):
            raise TypeError(
                f"corrupt ruling record: 'payload' is not an object, got {type(payload)!r}"
            )
        is_pending = (
            "question" in payload
            and "pending_id" in payload
            and "resolving_ruling_id" not in payload
        )
        if is_pending:
            pending_records.append(record)
        elif "resolving_ruling_id" in payload:
            pending_id = payload["pending_id"]
            if not isinstance(pending_id, str):
                raise TypeError(
                    f"corrupt ruling record: 'pending_id' is not a string, got {type(pending_id)!r}"
                )
            resolved_ids.add(pending_id)
    return pending_records, resolved_ids


def list_pending(eval_root: Path = DEFAULT_EVAL_ROOT) -> list[dict[str, object]]:
    """List every ``pending_ruling`` record not yet resolved."""
    pending_records, resolved_ids = _pending_and_resolved_ids(eval_root)
    return [
        record
        for record in pending_records
        if record["payload"]["pending_id"] not in resolved_ids  # type: ignore[index]
    ]


def count_pending(eval_root: Path = DEFAULT_EVAL_ROOT) -> int:
    """Count unresolved ``pending_ruling`` records — DA3 requires this at zero before the freeze."""
    return len(list_pending(eval_root))
