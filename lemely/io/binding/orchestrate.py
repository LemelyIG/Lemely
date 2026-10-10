"""Bind a script's answers to questions, check the binding, and decide whether to trust it.

This is where the pieces meet. ``LabelBinder`` asks the model for one reading-order list
of labels and writing; ``bind_stream`` decides which question each block belongs to;
the checks in ``lemely.core.binding_gate`` say whether the result can be trusted. Here
the script is read (twice, unless that is switched off), each read is bound and checked,
and one read is chosen or the paper is held.

Nothing here gives an answer a question id. A read's answers are the ones
``bind_stream`` bound; choosing between two reads only picks which read's answers go on.

The choice, with two reads (``G9`` compares them):

1. the reads disagree at paper scope about where answers belong: hold, first read;
2. the first read has no paper-scope failure: pass, first read;
3. the second read has none: pass, second read (``retried``);
4. otherwise: hold, first read.

With one read (the second switched off, or failed), a paper-scope failure is a hold.
The checks see part of what can go wrong: a pass means nothing was found, not that the
binding is right.

The label binder runs only with the gate enforcing (``BindingSettings`` rejects the
rest): its checks are part of reading a script safely. ``gate="observe"`` and
``gate="off"`` belong to the legacy binder. Under observe its answers are checked and
the result is published in the ``BINDING_GATE_RESULT`` event, and nothing else
changes: no report is returned, so nothing downstream has a verdict to act on, and no
call is made that only enforcing would make.

The legacy binder, where the model hands out ids itself, is gated here too
(``gate_legacy``); its call and the reading of its reply stay with the extractor.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from lemely.core.binding import BindingCheck, BindingReport
from lemely.core.binding_gate import (
    GateThresholds,
    check_duplicate_ids,
    check_label_coverage,
    check_second_read,
    check_shape,
    check_shift,
    check_unknown_ids,
    verdict,
)
from lemely.core.label_sequence import bind_stream
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from lemely.io.binding.label_binder import BoundRead, LabelBinder, to_bound_read
from lemely.runtime.errors import CostCeilingError, LemelyError
from lemely.runtime.events import EventType, bus

if TYPE_CHECKING:
    from collections.abc import Callable

    from lemely.core.binding import BindingVerdict, SeenWriting
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.gemini import GeminiClient, ImageUploads
    from lemely.io.rasterise import RasterisedPage
    from lemely.runtime.config import BindingSettings, Settings

SECOND_READ_TASK_TAG = "binding_second_read"
# Reasons in ``StreamRead.drops`` for a reply item that was left out and may have been
# writing. A part whose block was lost this way looks blank and is not.
LOST_ITEM_REASONS = ("malformed_item", "unknown_type")


@dataclass(frozen=True, slots=True)
class BindingOutcome:
    """What binding a script came to.

    ``answers`` are the chosen read's, one per leaf that has writing. Any verdict on
    ``report`` other than ``pass`` means the paper must not be published, and its
    failed checks say why. ``unbound`` is the
    writing no leaf could be given. ``review_only_ids`` are the chosen read's unaligned
    leaves: no label was lined up with them, so whatever was written for them could not
    be bound, and they must go to a teacher without a mark being attempted. ``drops`` is
    the chosen read's count of reply items left out or repaired, by reason.
    """

    answers: list[ExtractedAnswer]
    report: BindingReport
    unbound: list[SeenWriting]
    review_only_ids: list[str]
    drops: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LegacyRead:
    """One reply of the legacy extractor: its answers, ids already mapped to the mark scheme's.

    ``drops`` is the extractor's count of answers it had to leave out, by reason.
    """

    answers: list[ExtractedAnswer]
    drops: dict[str, int]


@dataclass(frozen=True, slots=True)
class LegacyOutcome:
    """What gating the legacy extractor's answers came to.

    ``used_retry`` says which read the caller goes on with. ``report`` is ``None``
    under ``gate="observe"``: the caller then goes on with the first read exactly as
    it is. Otherwise ``unverified_ids`` are the ids a failed question-scope check of
    the read used names.
    """

    used_retry: bool
    report: BindingReport | None
    unverified_ids: frozenset[str]


def _as_extracted(answers: list[ExtractedAnswer]) -> ExtractedAnswers:
    """``answers`` in the record the checks take. Only the answers are read."""
    return ExtractedAnswers(paper_id="", source_scan="", answers=answers)


def _paper_failed(checks: list[BindingCheck]) -> bool:
    return verdict(checks, retried=False) != "pass"


def _lost_items(drops: dict[str, int]) -> int:
    return sum(drops.get(reason, 0) for reason in LOST_ITEM_REASONS)


def _label_checks(
    read: BoundRead, mark_scheme: MarkScheme, thresholds: GateThresholds
) -> list[BindingCheck]:
    """G1, G2, G5, G6 and G7 over one bound read."""
    extracted = _as_extracted(read.answers)
    return [
        check_unknown_ids(extracted, mark_scheme),
        check_duplicate_ids(extracted),
        check_label_coverage(
            extracted,
            mark_scheme,
            read.unaligned_ids,
            read.unplaced_labels,
            thresholds,
            listing_suspects=len(read.listing_suspects),
            lost_items=_lost_items(read.drops),
        ),
        check_shape(extracted, mark_scheme, thresholds),
        *check_shift(extracted, mark_scheme, thresholds),
    ]


def _legacy_checks(
    answers: list[ExtractedAnswer], mark_scheme: MarkScheme, thresholds: GateThresholds
) -> list[BindingCheck]:
    """G1, G2, G6 and G7. The legacy extractor reports no labels, so G5 has nothing to read."""
    extracted = _as_extracted(answers)
    return [
        check_unknown_ids(extracted, mark_scheme),
        check_duplicate_ids(extracted),
        check_shape(extracted, mark_scheme, thresholds),
        *check_shift(extracted, mark_scheme, thresholds),
    ]


def _question_scope_ids(checks: list[BindingCheck]) -> frozenset[str]:
    """Ids named by the checks that failed at question scope."""
    return frozenset(
        qid
        for check in checks
        if not check.passed and check.scope == "question"
        for qid in check.question_ids
    )


def _publish_failed_read(exc: LemelyError, stage: str) -> None:
    bus.publish(
        EventType.SECOND_READ_FAILED,
        error=str(exc),
        error_type=type(exc).__name__,
        stage=stage,
    )


def _publish_result(
    enforced: BindingReport,
    *,
    settings: BindingSettings,
    returned_checks: list[BindingCheck],
    unbound: int,
    unaligned: int,
    inferred_numbers: list[str],
    drops: dict[str, int],
    second_read: bool,
) -> None:
    """Publish what the gate decided.

    ``enforced`` is the report an enforcing gate returns: its verdict, ``retried`` and
    model are published as fields, and the whole of it as ``report``, which under
    ``gate="observe"`` is the only place it goes. ``returned_checks`` are the checks of
    the read whose answers go on (the first read, under observe), and the counts are
    that read's.
    """
    bus.publish(
        EventType.BINDING_GATE_RESULT,
        binder=enforced.binder,
        gate=settings.gate,
        verdict=enforced.verdict,
        retried=enforced.retried,
        failed_checks=list(dict.fromkeys(c.id for c in returned_checks if not c.passed)),
        unbound=unbound,
        unaligned=unaligned,
        inferred_numbers=list(inferred_numbers),
        drops=dict(drops),
        model=enforced.model,
        second_read=second_read,
        report=enforced.model_dump(),
    )


def _read_both(
    first: Callable[[], BoundRead], second: Callable[[], BoundRead]
) -> tuple[BoundRead, BoundRead | None]:
    """Run the two reads at the same time; the second may come back ``None``.

    Each read runs under ``contextvars.copy_context().run`` so that its bus events
    carry the run id. Both are waited for before anything is raised, so that a
    cost-ceiling breach in one is never hidden behind another error in the other: the
    breach stops the run and always wins. Otherwise a failed first read fails the
    paper, as a failed extraction call always has, and a failed second read (any
    ``LemelyError``) only costs the comparison. Both calls have started by the time
    either fails, so a breach or a failure in one does not save the cost of the other.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(contextvars.copy_context().run, first),
            pool.submit(contextvars.copy_context().run, second),
        ]
        results: list[BoundRead | None] = [None, None]
        errors: list[Exception | None] = [None, None]
        for position, future in enumerate(futures):
            try:
                results[position] = future.result()
            except Exception as exc:  # sorted out below, never swallowed
                errors[position] = exc
    for error in errors:
        if isinstance(error, CostCeilingError):
            raise error
    first_error, second_error = errors
    if first_error is not None:
        raise first_error
    first_read = results[0]
    if first_read is None:  # pragma: no cover - a read returns or raises
        raise RuntimeError("the first read gave neither a result nor an error")
    if second_error is None:
        return first_read, results[1]
    if not isinstance(second_error, LemelyError):
        raise second_error
    _publish_failed_read(second_error, SECOND_READ_TASK_TAG)
    return first_read, None


def _with_statuses(
    answers: list[ExtractedAnswer], unverified: frozenset[str]
) -> list[ExtractedAnswer]:
    """``answers`` with those in ``unverified`` marked so; the binder's own doubts are kept."""
    return [
        answer.model_copy(update={"binding_status": "unverified"})
        if answer.question_id in unverified
        else answer
        for answer in answers
    ]


def run_binding(
    client: GeminiClient,
    pages: list[RasterisedPage],
    mark_scheme: MarkScheme,
    *,
    uploads: ImageUploads,
    settings: Settings,
    manifest_key: str,
) -> BindingOutcome:
    """Read ``pages`` with the label binder, check the binding, and choose a read or hold.

    Every call uses ``uploads``, the page uploads the caller already has, and
    ``settings.binding.read_model``. The gate must be enforcing: the label binder is
    not run without its checks.

    A ``CostCeilingError`` from either read propagates unchanged. So does any error
    from the first read. A second read that fails otherwise is published as
    ``SECOND_READ_FAILED`` and the paper goes on as if there were none.
    """
    binding = settings.binding
    if binding.binder != "label":
        raise ValueError(
            f"run_binding binds by labels; binder={binding.binder!r} is gated by gate_legacy"
        )
    if binding.gate != "enforce":
        raise ValueError(
            f"the label binder runs only with gate='enforce', not gate={binding.gate!r}"
        )
    binder = LabelBinder(client)

    def _read(task_tag: str, suffix: str) -> BoundRead:
        stream = binder.read(
            pages,
            mark_scheme,
            uploads=uploads,
            model=binding.read_model,
            extra_cache_key=manifest_key + suffix,
            task_tag=task_tag,
        )
        return to_bound_read(
            bind_stream(stream.items, mark_scheme), page_count=len(pages), drops=stream.drops
        )

    def _first() -> BoundRead:
        return _read("extraction", "|bind1")

    def _second() -> BoundRead:
        return _read(SECOND_READ_TASK_TAG, "|bind2")

    second: BoundRead | None = None
    if binding.second_read:
        first, second = _read_both(_first, _second)
    else:
        first = _first()

    thresholds = GateThresholds()
    first_checks = _label_checks(first, mark_scheme, thresholds)
    second_checks: list[BindingCheck] | None = None
    compared: list[BindingCheck] = []
    if second is not None:
        second_checks = _label_checks(second, mark_scheme, thresholds)
        compared = [
            check_second_read(
                _as_extracted(first.answers),
                _as_extracted(second.answers),
                mark_scheme,
                thresholds,
            )
        ]

    chosen, chosen_checks = first, first_checks
    decided: BindingVerdict
    if _paper_failed(compared):
        decided, retried = "hold", True
    elif not _paper_failed(first_checks):
        decided, retried = "pass", False
    elif second is not None and second_checks is not None and not _paper_failed(second_checks):
        chosen, chosen_checks = second, second_checks
        decided, retried = "pass", True
    else:
        decided, retried = "hold", second is not None

    checks = [*chosen_checks, *compared]
    enforced = BindingReport(
        binder="label",
        checks=checks,
        verdict=decided,
        retried=retried,
        model=binding.read_model,
    )
    _publish_result(
        enforced,
        settings=binding,
        returned_checks=checks,
        unbound=len(chosen.unbound),
        unaligned=len(chosen.unaligned_ids),
        inferred_numbers=chosen.inferred_numbers,
        drops=chosen.drops,
        second_read=second is not None,
    )
    return BindingOutcome(
        answers=_with_statuses(chosen.answers, _question_scope_ids(checks)),
        report=enforced,
        unbound=[u.writing for u in chosen.unbound],
        review_only_ids=list(chosen.unaligned_ids),
        drops=dict(chosen.drops),
    )


def gate_legacy(
    first: LegacyRead,
    mark_scheme: MarkScheme,
    *,
    settings: Settings,
    model: str,
    retry: Callable[[], LegacyRead],
) -> LegacyOutcome:
    """Check the legacy extractor's answers; on a paper-scope failure, try once more.

    ``first`` came from ``model``. ``retry`` makes the same call again on
    ``settings.binding.retry_model`` and is called at most once, only when ``first``
    fails at paper scope. The retry is used when it passes; otherwise the paper is held
    on the first read. A ``CostCeilingError`` from the retry propagates unchanged; a
    retry that fails otherwise is published as ``SECOND_READ_FAILED`` and the paper is
    held on the first read, its one retry spent.

    Under ``gate="observe"`` the retry is never called: observing must not spend what
    only enforcing spends. A first read that fails at paper scope is published with the
    verdict ``retry``, which is what enforcing would have done next, and no report is
    returned. Not to be called with the gate off.
    """
    binding = settings.binding
    if binding.gate == "off":
        raise ValueError("gate_legacy runs the gate; with gate='off' there is nothing to run")
    thresholds = GateThresholds()
    first_checks = _legacy_checks(first.answers, mark_scheme, thresholds)
    if binding.gate == "observe":
        _publish_result(
            BindingReport(
                binder="legacy",
                checks=first_checks,
                verdict=verdict(first_checks, retried=False),
                retried=False,
                model=model,
            ),
            settings=binding,
            returned_checks=first_checks,
            unbound=0,
            unaligned=0,
            inferred_numbers=[],
            drops=first.drops,
            second_read=False,
        )
        return LegacyOutcome(used_retry=False, report=None, unverified_ids=frozenset())

    second: LegacyRead | None = None
    second_checks: list[BindingCheck] = []
    retried = False
    if _paper_failed(first_checks):
        retried = True
        try:
            second = retry()
        except CostCeilingError:
            raise
        except LemelyError as exc:
            _publish_failed_read(exc, "binding_retry")
        else:
            second_checks = _legacy_checks(second.answers, mark_scheme, thresholds)

    use_retry = second is not None and not _paper_failed(second_checks)
    chosen = second if use_retry and second is not None else first
    checks = second_checks if use_retry else first_checks
    report = BindingReport(
        binder="legacy",
        checks=checks,
        verdict="hold" if _paper_failed(checks) else "pass",
        retried=retried,
        model=binding.retry_model if use_retry else model,
    )
    _publish_result(
        report,
        settings=binding,
        returned_checks=checks,
        unbound=0,
        unaligned=0,
        inferred_numbers=[],
        drops=chosen.drops,
        second_read=second is not None,
    )
    return LegacyOutcome(
        used_retry=use_retry, report=report, unverified_ids=_question_scope_ids(checks)
    )


def binding_models(settings: Settings) -> dict[str, str]:
    """The models the binding step calls by name, for ``lemely doctor``'s model table.

    ``binding_read`` is the label binder's model, for both of its reads.
    ``binding_retry`` is the gated legacy binder's retry. The legacy binder's first
    call is the ordinary extraction call and is already in the table as ``extraction``.
    """
    binding = settings.binding
    if binding.binder == "label":
        return {"binding_read": binding.read_model}
    if binding.gate != "off":
        return {"binding_retry": binding.retry_model}
    return {}


def binding_status(settings: Settings) -> tuple[bool, str]:
    """Advisory status for ``lemely doctor``: how answers are bound, and at what cost.

    Not ok when a second read is configured and would be the first read again: both
    go to the same model, so only how hard each thinks makes the second a second
    opinion. For a 3.x model that is ``gemini.thinking_level_for`` (tags
    ``extraction`` and ``binding_second_read``); a table for it in ``lemely.toml``
    replaces the defaults, so one written before the binder existed leaves
    ``binding_second_read`` out. A 2.5 model ignores that table and reads
    ``gemini.thinking_budget_for`` instead, so the advice names the table the
    configured model actually reads.
    """
    from lemely.io.gemini import GeminiClient

    binding = settings.binding
    summary = f"binder={binding.binder}, gate={binding.gate}"
    if binding.binder == "legacy":
        if binding.gate == "off":
            return True, f"{summary}: one extraction call, unchecked"
        if binding.gate == "observe":
            return True, f"{summary}: one extraction call, checked and reported, never held"
        return True, f"{summary}: one extraction call, and one retry on {binding.retry_model}"
    model = binding.read_model
    client = GeminiClient(settings, ledger=None)
    first = client.resolved_thinking("extraction", model)
    if not binding.second_read:
        return True, f"{summary}: one read on {model} (thinking {first})"
    second = client.resolved_thinking(SECOND_READ_TASK_TAG, model)
    if first == second:
        # A level is a name (3.x); a budget is a number of tokens (2.5 and earlier).
        table = "thinking_level_for" if isinstance(first, str) else "thinking_budget_for"
        return (
            False,
            f"{summary}: both reads on {model} resolve to the same thinking ({first}), so the "
            "second read is the first one again; set a different value for "
            f"{SECOND_READ_TASK_TAG} in [gemini.{table}]",
        )
    return (
        True,
        f"{summary}: two reads on {model} per extraction (thinking {first}, then {second})",
    )
