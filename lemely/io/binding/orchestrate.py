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

Whichever read goes on, three kinds of leaf in it are not taken at face value. A leaf
that has writing in exactly one of the two reads: if the read that goes on has the
writing it is kept and doubted (``unverified``); if it has none, the leaf is not a
blank, it goes to a teacher and the other read's writing for it is kept as unbound.
A leaf in a group whose writing was listed before its labels: doubted if answered,
to a teacher if not. A leaf with nothing under its label in the read that goes on,
for which the other read found no label: to a teacher, since the other reader may
have seen its writing and had nowhere to put it. And every leaf a failed
question-scope check names: doubted.

With ``second_read`` off there is one read, and a paper-scope failure on it is a hold.
With it on, a paper is never let out on one read: a second read that fails is made
once more, and if it fails again the job fails as it does when the first read fails.
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
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, get_args

import structlog

from lemely.core.binding import BindingCheck, BindingReport
from lemely.core.binding_gate import (
    GateThresholds,
    all_multiple_choice,
    check_duplicate_ids,
    check_label_coverage,
    check_second_read,
    check_shape,
    check_shift,
    check_unknown_ids,
    presence_disagreements,
    suspect_group_leaves,
    unread_in_one_read,
    verdict,
)
from lemely.core.label_sequence import UnalignedReason, bind_stream
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from lemely.core.text_agreement import text_agreement
from lemely.io.binding.label_binder import BoundRead, LabelBinder, to_bound_read
from lemely.runtime.errors import CostCeilingError, ExternalServiceError, LemelyError
from lemely.runtime.events import EventType, bus

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from lemely.core.binding import BindingVerdict, SeenWriting
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.gemini import GeminiClient, ImageUploads
    from lemely.io.rasterise import RasterisedPage
    from lemely.runtime.config import BindingSettings, Settings

SECOND_READ_TASK_TAG = "binding_second_read"
#: Why a leaf is sent to a teacher with no answer when it is not one of the read's own
#: unaligned leaves (those carry a reason from ``label_sequence.UNALIGNED_REASONS``):
#: the other read has writing for it and this one has none; it is the part left with
#: nothing in a group whose writing was listed before its labels; this read has nothing
#: under its label and the other read placed no label for it.
ReviewOnlyReason = Literal[
    "answered_in_one_read_only", "listing_suspect", "unaligned_in_other_read"
]
REVIEW_ONLY_REASONS: tuple[ReviewOnlyReason, ...] = get_args(ReviewOnlyReason)
#: Why an answer is doubted when it was taken from the read that was not returned
#: (``_from_other_read``). Carried beside the review-only reasons, by id, so that the
#: review reason a teacher reads can say what happened.
MARKED_FROM_OTHER_READ = "marked_from_other_read"
# Reasons in ``StreamRead.drops`` for a reply item that was left out and may have been
# writing. A part whose block was lost this way looks blank and is not.
LOST_ITEM_REASONS = ("malformed_item", "unknown_type")

# Each read's task tag and the suffix its cache key takes after the paper's own key.
_FIRST_READ = ("extraction", "|bind1")
_SECOND_READ = (SECOND_READ_TASK_TAG, "|bind2")


@dataclass(frozen=True, slots=True)
class BindingOutcome:
    """What binding a script came to.

    ``answers`` are the chosen read's, one per leaf that has writing. Any verdict on
    ``report`` other than ``pass`` means the paper must not be published, and its
    failed checks say why. ``unbound`` is the writing no leaf could be given.
    ``review_only_ids`` are the leaves that have no answer and are not blanks, so they
    must go to a teacher without a mark being attempted: the chosen read's unaligned
    leaves (no label was lined up with them, so whatever was written for them could not
    be bound), the leaf left with nothing in a group whose writing was listed before
    its labels, and a leaf the chosen read left blank that the other read answered
    (that writing is added to ``unbound``). ``drops`` is the chosen read's count of
    reply items left out or repaired, by reason. ``review_reasons`` says why each id
    in ``review_only_ids`` is there: the binder's own reason for an unaligned leaf, or
    one of ``REVIEW_ONLY_REASONS``. ``read_cache_keys`` are the response-cache keys of
    the reads that were made, for whoever holds the paper later (the marker's check
    runs after this) to forget them by. ``marked_from_other_read`` are the leaves whose
    answer in ``answers`` is the other read's (``_from_other_read``): each is
    ``unverified``, and none is in ``review_only_ids``.
    """

    answers: list[ExtractedAnswer]
    report: BindingReport
    unbound: list[SeenWriting]
    review_only_ids: list[str]
    drops: dict[str, int] = field(default_factory=dict)
    review_reasons: dict[str, UnalignedReason | ReviewOnlyReason] = field(default_factory=dict)
    read_cache_keys: tuple[str, ...] = ()
    marked_from_other_read: list[str] = field(default_factory=list)


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


@dataclass(frozen=True, slots=True)
class _Read:
    """One read of the script: what ``bind_stream`` made of it, as records and as bound.

    ``writings`` is the writing each bound leaf holds, by question id.
    """

    bound: BoundRead
    writings: dict[str, list[SeenWriting]]


def binder_for(
    mark_scheme: MarkScheme, binding: BindingSettings
) -> tuple[Literal["label", "legacy"], bool]:
    """Which binder reads this paper, and whether the paper's shape decided it.

    A scheme whose every marked leaf is multiple choice is read by the legacy binder,
    gated as configured, whatever ``binding.binder`` says. The reason is that it is
    unmeasured: the label binder has been read live on one theory paper and on no
    multiple-choice scan (none is on disk to measure), so a paper shape it has never
    read keeps the behaviour it had before the binder existed. What would lift the rule
    is a live read of a multiple-choice scan by the label binder that passes. It is a
    rule in code and not a setting: nothing in ``lemely.toml`` or the environment turns
    it off. A scheme with at least one leaf that is not multiple choice uses the
    configured binder.

    "Multiple choice" is the gate's own test (``binding_gate.all_multiple_choice``).
    """
    if binding.binder == "label" and all_multiple_choice(mark_scheme):
        return "legacy", True
    return binding.binder, False


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
            listing_suspects=read.listing_suspects,
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


#: What is said when the second read crashed with something that is not a
#: ``LemelyError``: on the ``SECOND_READ_FAILED`` event, and as the message of the
#: error the job fails with if it crashes again. Both reach the student's browser
#: (``lemely.web.sse``), and the text of an arbitrary exception is internal: it goes
#: to the server log with its traceback and nowhere else.
SECOND_READ_CRASH_MESSAGE = "the second read of the script failed unexpectedly"


def _publish_failed_read(exc: Exception, stage: str) -> None:
    """Publish that a second read or the legacy binder's retry failed.

    The label binder's second read is then made once more (``_read_both``); the legacy
    binder's paper is held on its first read (``gate_legacy``).

    A ``LemelyError`` is a service or parsing failure and its message is published, as
    the text second reader's is. Anything else is a bug: a fixed sentence is published
    in place of its text.
    """
    bus.publish(
        EventType.SECOND_READ_FAILED,
        error=str(exc) if isinstance(exc, LemelyError) else SECOND_READ_CRASH_MESSAGE,
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
    first_read_failed: list[BindingCheck] | None = None,
    review_reasons: Mapping[str, str] | None = None,
    by_paper_shape: bool = False,
    marked_from_other_read: int = 0,
) -> None:
    """Publish and log what the gate decided.

    ``enforced`` is the report an enforcing gate returns: its verdict, ``retried`` and
    model are published as fields, and the whole of it as ``report``, which under
    ``gate="observe"`` is the only place it goes. ``returned_checks`` are the checks of
    the read whose answers go on. ``unbound`` counts the writing kept with no question
    and ``unaligned`` the leaves sent to a teacher with no answer. ``first_read_failed``
    is what failed at paper scope on a first read that the second read replaced, which
    the report (the second read's) does not show. ``review_reasons`` (leaf id to
    reason) is published as a count per reason, ``unaligned_reasons``: it is what
    tells a mark scheme that lists a question twice from a read that missed labels.
    ``by_paper_shape`` says the binder was chosen by ``binder_for``'s rule and not by
    the settings, so that the hold rate can be read per path. ``marked_from_other_read``
    counts the leaves whose answer was taken from the read that was not returned; they
    are not among ``unaligned``.

    The event has no subscriber of its own and is never sent to a browser
    (``lemely.web.sse``), so the same fields are written as one ``binding_gate_result``
    log line: the server's record of the decision. The line carries check ids and
    counts, never a check's sentence or any answer text.
    """
    set_aside = list(first_read_failed or [])
    fields: dict[str, object] = {
        "binder": enforced.binder,
        "gate": settings.gate,
        "verdict": enforced.verdict,
        "retried": enforced.retried,
        "failed_checks": list(dict.fromkeys(c.id for c in returned_checks if not c.passed)),
        "unbound": unbound,
        "unaligned": unaligned,
        "inferred_numbers": list(inferred_numbers),
        "drops": dict(drops),
        "model": enforced.model,
        "second_read": second_read,
        "unaligned_reasons": dict(Counter((review_reasons or {}).values())),
        "binder_by_paper_shape": by_paper_shape,
        "marked_from_other_read": marked_from_other_read,
    }
    structlog.get_logger().bind(component="binding_gate").info(
        "binding_gate_result",
        **fields,
        first_read_failed_checks=list(dict.fromkeys(c.id for c in set_aside)),
    )
    bus.publish(
        EventType.BINDING_GATE_RESULT,
        **fields,
        first_read_failed_checks=[c.model_dump() for c in set_aside],
        report=enforced.model_dump(),
    )


def _note_failed_second_read(error: Exception) -> None:
    """Log a crash with its traceback; publish that the second read failed."""
    if not isinstance(error, LemelyError):
        structlog.get_logger().bind(component="binding_gate").error(
            "binding_second_read_crashed", exc_info=error
        )
    _publish_failed_read(error, SECOND_READ_TASK_TAG)


def _read_both(
    first: Callable[[], _Read],
    second: Callable[[], _Read],
    *,
    forget_second: Callable[[], object] | None = None,
) -> tuple[_Read, _Read]:
    """Run the two reads at the same time and return both, or raise.

    Each read runs under ``contextvars.copy_context().run`` so that its bus events
    carry the run id. Both are waited for before anything is raised, so that a
    cost-ceiling breach in one is never hidden behind another error in the other: the
    breach stops the run and always wins. Otherwise a failed first read fails the
    paper, as a failed extraction call always has.

    A paper is never let out on one read when two were asked for: on one read a block
    the reader missed is a blank, and a blank is an unflagged zero. So a second read
    that fails (a service error, a reply that does not parse, or a crash) is published
    as ``SECOND_READ_FAILED`` and made once more, here, on the calling thread.
    ``forget_second`` is called before that attempt: it takes the second read's reply
    out of the response cache, because a crash in parsing or binding a reply comes
    after the reply was cached, and the same reply back from the cache would crash the
    same way. With it the second attempt is a model call. If it
    fails again the job fails with that error, exactly as for the first read: nothing
    is known about the binding, so there is no verdict to give. A crash that is not a
    ``LemelyError`` is logged with its traceback and raised as an
    ``ExternalServiceError`` that carries a fixed sentence, because the text of an
    arbitrary exception is internal and this error's text reaches the student's
    stream. ``KeyboardInterrupt`` and ``SystemExit`` are not caught. Both calls have
    started by the time either fails, so a breach or a failure in one does not save
    the cost of the other.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(contextvars.copy_context().run, first),
            pool.submit(contextvars.copy_context().run, second),
        ]
        results: list[_Read | None] = [None, None]
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
    first_read, second_read = results
    if first_read is None:  # pragma: no cover - a read returns or raises
        raise RuntimeError("the first read gave neither a result nor an error")
    if second_error is None and second_read is not None:
        return first_read, second_read
    if second_error is not None:
        _note_failed_second_read(second_error)
    if forget_second is not None:
        forget_second()
    try:
        return first_read, second()
    except CostCeilingError:
        raise
    except LemelyError:
        raise
    except Exception as crash:
        structlog.get_logger().bind(component="binding_gate").error(
            "binding_second_read_crashed", exc_info=crash
        )
        raise ExternalServiceError(SECOND_READ_CRASH_MESSAGE) from crash


def _in_paper_order(mark_scheme: MarkScheme, ids: list[str]) -> list[str]:
    """``ids`` once each, in the order the paper has its questions; strangers last."""
    wanted = dict.fromkeys(ids)
    ordered = list(dict.fromkeys(q.id for q in mark_scheme.all_questions_flat() if q.id in wanted))
    return [*ordered, *(qid for qid in wanted if qid not in ordered)]


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


def _whole_text(answer: ExtractedAnswer) -> str:
    """An answer's writing, answer and working, with its white space collapsed."""
    return " ".join(f"{answer.answer} {answer.working_out or ''}".split())


def _from_other_read(
    wanted: Iterable[str],
    returned: BoundRead,
    other: BoundRead,
    other_checks: list[BindingCheck],
    thresholds: GateThresholds,
) -> dict[str, ExtractedAnswer]:
    """The other read's answers for ``wanted`` leaves that can be marked, each ``unverified``.

    ``wanted`` are leaves the returned read has no answer for and that are not blanks:
    it has nothing under their label where the other read has writing, or it could not
    align them. Sent to a teacher unmarked, such a leaf is a zero in the total until
    the teacher acts, although one of two reads bound an answer to it. So the answer
    the other read bound is marked, and doubted: the mark is provisional and the
    question is in review, where before it was in review with no mark.

    Only an answer the other read would itself have returned without a flag is taken:

    - the other read passed its own checks at paper scope: a read that failed them is
      not a witness for any single leaf;
    - the binder gave the answer no content doubt there, and no question-scope check of
      that read names the leaf (G5 names every leaf of a group that shows the trace of
      writing listed before its label, so no leaf of such a group is taken);
    - the returned read does not hold that same writing on another leaf
      (``text_agreement`` at the gate's ``agreement_floor``, the test G9 uses for moved
      text). Where a part was left blank and the other read listed its label one place
      early, that read holds the neighbour's answer on the blank part with no doubt of
      its own; the returned read, which has that writing on the neighbour, is what
      shows it.

    A leaf with writing in neither read is not here at all, and one that fails any of
    the three stays as it was: with a teacher, unmarked.
    """
    if _paper_failed(other_checks):
        return {}
    doubted = {*other.review_ids, *_question_scope_ids(other_checks)}
    held_here = [_whole_text(answer) for answer in returned.answers]
    wanted_ids = set(wanted)
    taken: dict[str, ExtractedAnswer] = {}
    for answer in other.answers:
        qid = answer.question_id
        if qid not in wanted_ids or qid in doubted:
            continue
        writing = _whole_text(answer)
        if any(text_agreement(writing, held) >= thresholds.agreement_floor for held in held_here):
            continue
        taken[qid] = answer.model_copy(update={"binding_status": "unverified"})
    return taken


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

    A verdict other than ``pass``, or a job that fails in the reads, leaves neither
    read in the response cache: the next run on the same scan and scheme makes both
    model calls again. A paper that passed is served from the cache on a re-run.

    A ``CostCeilingError`` from either read propagates unchanged. So does any error
    from the first read. A second read that fails otherwise is published as
    ``SECOND_READ_FAILED`` and made once more; if it fails again its error is raised
    and the job fails (``_read_both``). With ``second_read`` on, nothing is returned
    from one read.
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
    if all_multiple_choice(mark_scheme):
        raise ValueError(
            "the label binder is not run on a scheme that is all multiple choice: "
            "binder_for keeps such a paper on the legacy binder"
        )
    binder = LabelBinder(client)

    def _read(task_tag: str, suffix: str) -> _Read:
        stream = binder.read(
            pages,
            mark_scheme,
            uploads=uploads,
            model=binding.read_model,
            extra_cache_key=manifest_key + suffix,
            task_tag=task_tag,
        )
        bound = bind_stream(stream.items, mark_scheme)
        return _Read(
            bound=to_bound_read(bound, page_count=len(pages), drops=stream.drops),
            writings={leaf.question_id: list(leaf.writings) for leaf in bound.leaves},
        )

    reads = [_FIRST_READ, _SECOND_READ] if binding.second_read else [_FIRST_READ]
    # The keys the reads are cached under: taken out here for a paper held before
    # marking or a job that failed, and handed on for a paper held after marking.
    read_cache_keys = tuple(
        binder.cache_key(
            pages,
            mark_scheme,
            model=binding.read_model,
            extra_cache_key=manifest_key + suffix,
            task_tag=task_tag,
        )
        for task_tag, suffix in reads
    )

    def _first() -> _Read:
        return _read(*_FIRST_READ)

    def _second() -> _Read:
        return _read(*_SECOND_READ)

    def _forget_reads() -> None:
        """Take the reads out of the response cache: the next run reads the scan afresh."""
        client.forget_cached(read_cache_keys)

    second_read: _Read | None = None
    if binding.second_read:
        try:
            first_read, second_read = _read_both(
                _first, _second, forget_second=lambda: client.forget_cached(read_cache_keys[1:])
            )
        except CostCeilingError:
            raise
        except Exception:
            # The job fails with nothing known about the binding. The read that did
            # come back must not be what the next attempt is handed.
            _forget_reads()
            raise
    else:
        first_read = _first()
    first = first_read.bound
    second = second_read.bound if second_read is not None else None

    thresholds = GateThresholds()
    first_checks = _label_checks(first, mark_scheme, thresholds)
    second_checks: list[BindingCheck] | None = None
    compared: list[BindingCheck] = []
    lopsided: list[str] = []
    unread: list[str] = []
    if second is not None:
        second_checks = _label_checks(second, mark_scheme, thresholds)
        one, two = _as_extracted(first.answers), _as_extracted(second.answers)
        compared = [
            check_second_read(
                one,
                two,
                mark_scheme,
                thresholds,
                first_unaligned=first.unaligned_ids,
                second_unaligned=second.unaligned_ids,
            )
        ]
        lopsided = presence_disagreements(
            one, two, mark_scheme, first.unaligned_ids, second.unaligned_ids
        )
        unread = unread_in_one_read(
            one, two, mark_scheme, first.unaligned_ids, second.unaligned_ids
        )

    chosen, chosen_checks, other = first, first_checks, second_read
    other_checks = second_checks
    decided: BindingVerdict
    if _paper_failed(compared):
        decided, retried = "hold", True
    elif not _paper_failed(first_checks):
        decided, retried = "pass", False
    elif second is not None and second_checks is not None and not _paper_failed(second_checks):
        chosen, chosen_checks, other = second, second_checks, first_read
        other_checks = first_checks
        decided, retried = "pass", True
    else:
        decided, retried = "hold", second is not None

    if decided != "pass":
        # A held paper has no teacher queue: running it again is the only way on, and
        # a hold that one unlucky read caused must not be replayed from the cache.
        # The keys are fixed by the page bytes, the scheme and the prompt, so without
        # this the same replies would come back until the instance was recycled. The
        # entries are removed after the fact, and not withheld until a pass, so that
        # the paper that passes (most of them) is cached by the one mechanism the
        # client already has.
        _forget_reads()
    checks = [*chosen_checks, *compared]
    enforced = BindingReport(
        binder="label",
        checks=checks,
        verdict=decided,
        retried=retried,
        model=binding.read_model,
    )
    answered = {answer.question_id for answer in chosen.answers}
    # A group that shows the trace of writing listed before its label is never
    # trusted, whatever the check's scope came out as: its answers sit one part out.
    # The answered leaves keep their answer, doubted; the blank one is not a blank
    # (its writing went to the leaf before) and goes to a teacher.
    suspect_leaves = suspect_group_leaves(mark_scheme, chosen.listing_suspects)
    # A leaf with writing in one read only is trusted on neither side, held paper or
    # not. Where this read has the writing it is kept and doubted. Where it has
    # none the leaf is not a blank: it goes to a teacher, and what the other read
    # saw there is kept as writing with no question.
    seen_elsewhere = [leaf for leaf in lopsided if leaf not in answered]
    # A leaf with nothing under its label here, for which the other read found no
    # label, is not known to be blank either: that reader may have seen the writing
    # and could bind it to nothing. (Where it is this read that found no label, the
    # leaf is already among its unaligned ones.) It goes to a teacher too, and the
    # other read's unbound writing is kept, since some of it may be this leaf's.
    missed_elsewhere = [leaf for leaf in unread if leaf not in chosen.unaligned_ids]
    unverified = _question_scope_ids(checks) | (frozenset([*suspect_leaves, *lopsided]) & answered)
    # A leaf with no answer here that the other read answered without doubt is marked
    # from that read and doubted, not left as an unmarked zero (``_from_other_read``).
    # Not on a held paper, whose record stays the returned read's; and not a leaf of a
    # suspect group of this read, which is trusted in neither direction.
    from_other: dict[str, ExtractedAnswer] = {}
    if decided == "pass" and other is not None and other_checks is not None:
        from_other = _from_other_read(
            (
                leaf
                for leaf in [*chosen.unaligned_ids, *seen_elsewhere]
                if leaf not in suspect_leaves
            ),
            chosen,
            other.bound,
            other_checks,
            thresholds,
        )
    seen_elsewhere = [leaf for leaf in seen_elsewhere if leaf not in from_other]
    review_only = _in_paper_order(
        mark_scheme,
        [
            *(leaf for leaf in chosen.unaligned_ids if leaf not in from_other),
            *(leaf for leaf in suspect_leaves if leaf not in answered),
            *seen_elsewhere,
            *missed_elsewhere,
        ],
    )
    # Why each of them is there. The read's own reason comes first: a leaf it could
    # not align is unaligned whatever else is true of it.
    why: dict[str, UnalignedReason | ReviewOnlyReason] = {}
    why.update(dict.fromkeys(missed_elsewhere, "unaligned_in_other_read"))
    why.update(dict.fromkeys(seen_elsewhere, "answered_in_one_read_only"))
    why.update(
        dict.fromkeys((leaf for leaf in suspect_leaves if leaf not in answered), "listing_suspect")
    )
    why.update(chosen.unaligned_reasons)
    review_reasons: dict[str, UnalignedReason | ReviewOnlyReason] = {
        leaf: why[leaf] for leaf in review_only if leaf in why
    }
    unbound = [u.writing for u in chosen.unbound]
    if other is not None:
        for leaf in seen_elsewhere:
            unbound.extend(other.writings.get(leaf, []))
        if missed_elsewhere:
            unbound.extend(u.writing for u in other.bound.unbound if u.writing not in unbound)
    _publish_result(
        enforced,
        settings=binding,
        returned_checks=checks,
        unbound=len(unbound),
        unaligned=len(review_only),
        inferred_numbers=chosen.inferred_numbers,
        drops=chosen.drops,
        second_read=second is not None,
        first_read_failed=(
            [c for c in first_checks if not c.passed and c.scope == "paper"]
            if chosen is not first
            else []
        ),
        review_reasons=review_reasons,
        marked_from_other_read=len(from_other),
    )
    by_id = {
        **{a.question_id: a for a in _with_statuses(chosen.answers, unverified)},
        **from_other,
    }
    return BindingOutcome(
        answers=[by_id[qid] for qid in _in_paper_order(mark_scheme, list(by_id))],
        report=enforced,
        unbound=unbound,
        review_only_ids=review_only,
        drops=dict(chosen.drops),
        review_reasons=review_reasons,
        read_cache_keys=read_cache_keys,
        marked_from_other_read=_in_paper_order(mark_scheme, list(from_other)),
    )


def gate_legacy(
    first: LegacyRead,
    mark_scheme: MarkScheme,
    *,
    settings: Settings,
    model: str,
    retry: Callable[[], LegacyRead],
    by_paper_shape: bool = False,
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
    returned. Not to be called with the gate off. ``by_paper_shape`` is passed on to
    the log line and event: the legacy binder is here by ``binder_for``'s rule.
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
            by_paper_shape=by_paper_shape,
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
        by_paper_shape=by_paper_shape,
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
    # ``binder_for``: a paper shape the label binder has never read keeps the old path.
    summary += " (a scheme that is all multiple choice keeps the legacy binder)"
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
