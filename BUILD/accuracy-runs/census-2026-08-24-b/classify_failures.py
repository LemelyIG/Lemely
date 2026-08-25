"""#45 (M2.2): failure-reason census over the 229 det-parser failures from #88.

Zero-cost, zero-network diagnostic script (not production code). Reads the 229
stems from ``../census-2026-08-24-a/det-failures.txt``, locates each PDF under
the restored corpus, re-runs the deterministic parsing pipeline stage-by-stage
(``extract_metadata`` -> ``select_tables``/MCQ table extraction ->
``detect_columns``/``is_marks_column`` -> ``build_questions`` ->
``reconcile._leaf_marks``), comparing the leaf-mark total to
``metadata.maximum_mark`` directly rather than calling
``reconcile.check``/going through ``DeterministicMarkSchemeParser`` at all --
so there is no ``escalate_on_mark_mismatch`` flag in play here, and a mismatch
never aborts the run before the structural state that produced it is visible
-- and applies a rule-based classifier over the captured signals.

Every classification rule is a **pure function** of already-captured signals
(cover text vs. mapped ``PaperType``, whether a column search hit a real match
or the rightmost-column fallback, a count of marks cells that were empty/
unparsed, ``computed_total`` vs ``maximum_mark``) — never of the PDF's
mark-scheme prose. Only derived labels/counts/filenames are ever written to
the output; table cell text is read in-process and discarded.

Zero Gemini calls: only ``lemely.io.det.*`` is imported. No network.

Cause taxonomy (seven buckets, checked in this priority order — the first
rule whose evidence is found wins). Round 3's brief established a general
property that every bucket below must satisfy: a cause label may only be
assigned when there is a **sufficiency condition** — positive evidence that
the named mechanism can actually produce the observed magnitude — checked in
code, not just claimed in prose. A row failing its bucket's sufficiency
condition falls through to the next bucket in priority order, ending at
``UNCLASSIFIED`` if nothing else claims it; ``UNCLASSIFIED`` growing is a
correct outcome, not a defect. Each entry below states its sufficiency
condition and where it is enforced:

1. ``paper_profile_misconfiguration``  — cover text names a paper type that
   the subject profile's ``paper_type_by_number`` overrides (the 0625 p2
   class). Sufficiency condition: a DEMONSTRATED branch difference, not
   merely a metadata discrepancy — ``_changes_parse_path`` checks that
   reclassifying under the cover-text-implied ``PaperType`` would actually
   send ``classify_one`` down a different branch (MCQ vs. not-MCQ is the only
   branch it takes on ``metadata.paper_type``). This excludes 0625 p3
   (profiles.py maps THEORY_EXTENDED, cover text implies THEORY_CORE — both
   non-MCQ, so the discrepancy is real but causally inert for this pipeline;
   see ``manifest.json``'s ``ruled_out_metadata_defect_not_a_cause``).
   Enforced in ``classify_profile_misconfiguration``. Classified, NOT
   repaired — this script never touches ``lemely/io/det/profiles.py``.
2. ``table_layout_extraction_failure`` — a pipeline stage before reconciliation
   raised ``ParseError`` (no tables found, no valid rows, indicative-content /
   levels-based section, etc.), or, on the MCQ path only, the parsed answer
   count came up short of ``maximum_mark`` by more than half. Sufficiency
   condition: the failure is DIRECTLY OBSERVED — either an exception was
   actually raised by the stage itself, or (MCQ path only) the parsed count
   is short by more than half of ``maximum_mark`` (rows dropped, not a small
   residual mismatch). The ``ParseError`` catches are enforced inline in both
   ``_classify_mcq`` and ``_classify_theory``; the ``computed < maximum_mark
   / 2`` shortfall check is enforced ONLY in ``_classify_mcq`` (round-4
   correction — an earlier draft of this docstring claimed it was also
   enforced in ``_classify_theory``; it never was). The theory path has no
   equivalent shortfall heuristic, so a large theory-path deficit falls
   through to ``classify_theory_residual``'s ``mismatch_cause`` instead —
   see ``manifest.json``'s ``table_layout_extraction_failure`` note, which is
   qualified accordingly.
3. ``marks_column_detection_failure`` — no column of the merged table
   satisfied ``is_marks_column``/``find_mcq_answer_col``; the detector had to
   fall back to a column that is not actually a marks column. Sufficiency
   condition: DIRECTLY OBSERVED by re-running the same right-to-left scan
   ``detect_columns`` uses (``find_real_marks_col``) and finding it returns
   None — not inferred from a mismatched total.
4. ``marks_cell_notation_not_parsed`` — a real marks column WAS found, but one
   or more of its cells were empty/unparsed and got defaulted (1-mark
   default), which can move ``computed_total`` away from ``maximum_mark``.
   Sufficiency condition (round-5 fix — see below; round 4 bounded a
   two-sided claim that turned out unsound, round 3 bounded only the EXCESS
   side): ``empty_count`` is now measured by ``count_defaulted_answer_points``
   over the SAME population that feeds ``computed_total`` — AnswerPoints
   actually created by ``build_questions`` whose marks value was defaulted by
   ``lemely/io/det/rows.py``'s ``make_point`` — rather than raw table rows
   (round-4's ``count_empty_marks_cells``, whose population mismatch let one
   scheme report ``empty_count=119`` against a ``maximum_mark`` of 80, which
   cannot have 119 answer points at all). Even over this corrected
   population, only the EXCESS side survives as a sound bound: a defaulted
   point contributes AT MOST 1 to ``computed_total``, so
   ``computed_total - maximum_mark <= empty_count`` remains a valid
   necessary-condition check. The DEFICIT side ("every empty cell
   contributes >= 1, so ``computed_total`` can never fall below
   ``empty_count``") does NOT survive: ``lemely/io/det/rows.py``'s ``flush()``
   only sums a leaf's AnswerPoints into ``Question.marks`` when that leaf's
   ``q_row_had_answer`` flag was set, which a common table shape (Q-number
   row with no answer, all marks on continuation rows below it) never sets —
   so a defaulted AnswerPoint can contribute exactly 0 to ``computed_total``,
   not >= 1. The deficit disjunct is therefore RETIRED as a causal
   classifier and kept only as a consistency-check-only note in the
   evidence string (``"upper bound, deficit side unbounded"``) — it no
   longer gates the bucket. The bucket is claimed only when
   ``empty_count > 0`` AND the excess bound holds
   (``computed_total > maximum_mark`` and
   ``computed_total - maximum_mark <= empty_count``). Enforced in
   ``classify_theory_residual``. See ``manifest.json``'s ``d7_hypothesis``
   note: D7's share is published explicitly as an upper bound, not an
   enforced count, because of this downgrade.
5. ``mark_aggregation_overcount`` — every structural check above is clean, or
   the notation bucket's sufficiency condition failed, yet
   ``computed_total > maximum_mark``: positively-evidenced overcounting (e.g.
   double-counted alternative-answer branches), not a plain "totals don't
   match" residual. Sufficiency condition: the direction alone
   (``computed_total > maximum_mark``) IS the positive evidence — an excess
   above the target can only come from something being counted that
   shouldn't be. Enforced in ``mismatch_cause``.
6. ``genuine_mark_total_mismatch`` — every structural check above is clean
   (real column found, empty-cell defaulting ruled out or insufficient to
   explain the delta, tables extracted, profile mapping consistent with
   cover text) yet ``computed_total < maximum_mark``. This is the residual,
   hardest-to-positively-confirm bucket; its sufficiency condition is
   negative by construction — it requires the ABSENCE of every other
   explanation (not an overcount, not a column-detection failure, not a
   cell-notation delta the defaulting mechanism can explain) rather than
   being used as a default. Enforced in ``mismatch_cause`` /
   ``classify_theory_residual``.
7. ``UNCLASSIFIED`` — anything else (PDF missing on disk, an exception outside
   the anticipated ``ParseError`` set, metadata extraction itself failing, or
   any row whose evidence failed every bucket's sufficiency condition above).
   Sufficiency condition: none required by design — this is the "no positive
   evidence for any named mechanism" bucket, and growing it is the correct,
   honest outcome of a failed sufficiency check. The denominator is never
   narrowed: an unclassifiable scheme lands here with what was observed, it
   is not dropped.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from lemely.core.loose_schemas import PaperType
from lemely.io.det import gmp as _gmp
from lemely.io.det import metadata as _meta
from lemely.io.det import reconcile as _reconcile
from lemely.io.det.columns import detect_columns
from lemely.io.det.marks import is_marks_column
from lemely.io.det.mcq import find_mcq_answer_col, parse_mcq_tables
from lemely.io.det.profiles import SubjectProfile, get_profile
from lemely.io.det.rows import build_questions
from lemely.io.det.tables import select_tables
from lemely.runtime.config import DetParserSettings
from lemely.runtime.errors import ParseError

CORPUS_ROOT = Path("/home/sico/PaperScraper/papers")
CENSUS_A_DIR = Path(__file__).resolve().parent.parent / "census-2026-08-24-a"
OUT_DIR = Path(__file__).resolve().parent

# Same knobs DeterministicMarkSchemeParser uses (lemely/runtime/config.py's
# DetParserSettings), read from that single source rather than hardcoded
# copies that could silently drift from the production defaults. This script
# never instantiates the parser itself and never consults
# ``escalate_on_mark_mismatch`` -- see the module docstring.
_DET_CFG = DetParserSettings()
MAX_MARK_PER_POINT = _DET_CFG.max_mark_per_point
HEADER_KEYWORDS = _DET_CFG.header_keywords

# Cause taxonomy, in priority order -- see module docstring. Used to seed the
# Counter so cause_counts_ranked never silently omits a zero-count bucket.
ALL_CAUSES: tuple[str, ...] = (
    "paper_profile_misconfiguration",
    "table_layout_extraction_failure",
    "marks_column_detection_failure",
    "marks_cell_notation_not_parsed",
    "mark_aggregation_overcount",
    "genuine_mark_total_mismatch",
    "UNCLASSIFIED",
)

_QUOTED_RE = re.compile(r"['\"][^'\"]*['\"]")
# rows.py:242's ParseError embeds a PDF-derived q_cell inside a
# SINGLE-quoted span that is itself parenthesised: f"...('{q_cell}'): ...".
# If q_cell contains an apostrophe (e.g. "student's response"), the naive
# quote-to-quote scan above stops at that inner apostrophe and leaks the
# remainder of the PDF text. This pattern matches greedily from the first
# quote after "(" to the LAST matching quote immediately before ")" -- so an
# embedded apostrophe is swallowed as part of the redacted span rather than
# terminating it early. Applied before ``_QUOTED_RE`` so the general regex
# never sees the parenthesised span at all.
_PAREN_QUOTED_RE = re.compile(r"\((['\"])(.*)\1\)")


def sanitize_evidence(text: str) -> str:
    """Strip any quoted PDF-derived text from a ParseError-derived string.

    ``lemely.io.det.rows``'s ``ParseError`` messages embed raw cell/prose text
    in quotes (e.g. "Level-descriptor row ('...'): ..."). Only derived
    labels/counts are safe to commit (MISSION 12.7) -- this replaces any
    quoted span with a placeholder before an exception message is written
    into ``classified-failures.txt``. The parenthesised-quote pattern is
    handled first (see ``_PAREN_QUOTED_RE``) so a stray apostrophe inside the
    quoted PDF text cannot truncate the redaction and leak the rest of it.
    """
    text = _PAREN_QUOTED_RE.sub("('[redacted]')", text)
    return _QUOTED_RE.sub("'[redacted]'", text)

# Keyword -> implied PaperType, in the SAME priority order as
# SubjectProfile.paper_type's cover-text fallback branch (lemely/io/det/profiles.py).
_COVER_KEYWORD_TYPES: list[tuple[str, PaperType]] = [
    ("multiple choice", PaperType.MCQ),
    ("alternative to practical", PaperType.ALTERNATIVE_PRACTICAL),
    ("practical", PaperType.PRACTICAL),
    ("core", PaperType.THEORY_CORE),
    ("extended", PaperType.THEORY_EXTENDED),
]


# ---------------------------------------------------------------------------
# Pure classification helpers (no I/O; unit-tested in tests/test_census_45.py)
# ---------------------------------------------------------------------------


def cover_text_implied_paper_type(cover_text: str) -> PaperType | None:
    """Return the PaperType the cover text's own wording implies, or None.

    Mirrors ``SubjectProfile.paper_type``'s keyword scan exactly, but runs
    unconditionally — i.e. it does NOT stop early because ``paper_number``
    happens to be in ``paper_type_by_number``. That is precisely the signal
    ``classify_profile_misconfiguration`` needs: what the document itself
    says, independent of what the profile's number map says.
    """
    lower = cover_text.lower()
    for keyword, paper_type in _COVER_KEYWORD_TYPES:
        if keyword in lower:
            return paper_type
    return None


def _changes_parse_path(mapped: PaperType, implied: PaperType) -> bool:
    """True iff *mapped* vs *implied* would send ``classify_one`` down a
    different branch.

    ``classify_one`` only ever branches on ``metadata.paper_type`` once: MCQ
    vs. not-MCQ (``_classify_mcq`` vs. ``_classify_theory``). A profile/cover
    disagreement that keeps both sides on the same side of that MCQ/not-MCQ
    line (e.g. THEORY_CORE vs. THEORY_EXTENDED, the 0625 p3 case) is real as
    a metadata discrepancy but causally inert for this pipeline -- it cannot
    be the reason a scheme is in the det-failure set.
    """
    return (mapped == PaperType.MCQ) != (implied == PaperType.MCQ)


def classify_profile_misconfiguration(
    paper_number: int, cover_text: str, profile: SubjectProfile
) -> str | None:
    """Return evidence if the profile's ``paper_type_by_number`` overrides a
    DIFFERENT type than the cover text itself implies AND that difference
    would actually change the downstream parse path, else None.

    This is the 0625 p2 class from #88's manifest: ``paper_type_by_number``
    maps paper 2 to THEORY_CORE, so ``profile.paper_type`` never even reads
    the cover text (which reads "Paper 2 Multiple Choice (Extended)") -- and
    MCQ vs. THEORY_CORE really does send the pipeline down a different
    branch. The counterfactual gate (``_changes_parse_path``) excludes the
    0625 p3 case (THEORY_EXTENDED mapped vs. THEORY_CORE implied -- both
    non-MCQ, no path change), which is a real profiles.py discrepancy but not
    a cause of this parse failing (see ``manifest.json``'s
    ``ruled_out_metadata_defect_not_a_cause``). A pure function of
    (paper_number, cover_text, profile) — no PDF I/O.
    """
    if paper_number not in profile.paper_type_by_number:
        # The number map doesn't override anything for this paper — the
        # profile would have consulted cover text anyway, so there is no
        # "misconfiguration" (a mismatch here is just profile.paper_type()
        # doing its documented job).
        return None
    mapped = profile.paper_type_by_number[paper_number]
    implied = cover_text_implied_paper_type(cover_text)
    if implied is None or implied == mapped:
        return None
    if not _changes_parse_path(mapped, implied):
        return None
    return (
        f"paper_number={paper_number} maps to {mapped.value} via "
        f"paper_type_by_number, but cover_text implies {implied.value}"
    )


def find_real_marks_col(rows: list[list[str | None]], ncols: int, max_mark: int) -> int | None:
    """Same right-to-left scan as ``columns._find_marks_col``, but returns
    None instead of silently falling back to the last column when nothing
    qualifies — the fallback IS the marks-column-detection-failure signal.
    """
    for c in range(ncols - 1, -1, -1):
        col_values = [((row[c] if c < len(row) else None) or "") for row in rows]
        if is_marks_column(col_values, max_mark):
            return c
    return None


_PAPER_NUMBER_IN_EVIDENCE_RE = re.compile(r"paper_number=(\d+)")


def profile_misconfiguration_breakdown(rows: list[tuple[str, str, str]]) -> Counter[str]:
    """Group ``paper_profile_misconfiguration`` rows by ``{subject_code} p{paper_number}``.

    A pure function over already-classified (stem, cause, evidence) rows —
    it exists so the manifest never reports a single aggregate count that
    could hide MULTIPLE distinct profiles.py bugs (e.g. 0625 p2 AND p3) behind
    one number attributed only to the known p2 case.
    """
    breakdown: Counter[str] = Counter()
    for stem, cause, evidence in rows:
        if cause != "paper_profile_misconfiguration":
            continue
        subject_code = stem.split("_", 1)[0]
        m = _PAPER_NUMBER_IN_EVIDENCE_RE.search(evidence)
        paper_number = m.group(1) if m else "?"
        breakdown[f"{subject_code} p{paper_number}"] += 1
    return breakdown


_EMPTY_MAX_IN_EVIDENCE_RE = re.compile(
    r"(\d+) empty marks cell.*maximum_mark=(\d+)"
)


def excess_bound_near_vacuous_stems(rows: list[tuple[str, str, str]]) -> list[str]:
    """Return stems classified ``marks_cell_notation_not_parsed`` whose
    ``empty_count >= maximum_mark`` — the excess sufficiency check
    (``computed_total - maximum_mark <= empty_count``) is technically
    satisfied for these but close to vacuous, since a bound that large
    barely constrains anything (round-5 residual: the population fix
    (``count_defaulted_answer_points``) sharply reduced how often this
    happens -- round 4's raw-row count put 4 rows at empty_count >=
    maximum_mark, one as high as 119 for a maximum_mark of 80 -- but does
    not eliminate it entirely for schemes with a genuinely high fraction of
    defaulted cells). A pure function of already-classified rows, exists so
    this residual limitation is surfaced honestly in the manifest rather
    than silently claimed away.
    """
    stems: list[str] = []
    for stem, cause, evidence in rows:
        if cause != "marks_cell_notation_not_parsed":
            continue
        m = _EMPTY_MAX_IN_EVIDENCE_RE.search(evidence)
        if m is None:
            continue
        empty_count, maximum_mark = int(m.group(1)), int(m.group(2))
        if empty_count >= maximum_mark:
            stems.append(stem)
    return stems


def mismatch_cause(computed_total: int, maximum_mark: int) -> str:
    """Split the final-residual mismatch bucket: overcount vs. genuine mismatch.

    ``computed_total > maximum_mark`` is positively-evidenced overcounting
    (e.g. a double-counted alternative-answer branch) — a distinct, more
    specific claim than "the totals don't match", so it gets its own bucket
    rather than being folded into ``genuine_mark_total_mismatch``, which is
    reserved for stating what was *ruled out* (not an overcount; column
    detection and cell parsing were clean).
    """
    if computed_total > maximum_mark:
        return "mark_aggregation_overcount"
    return "genuine_mark_total_mismatch"


def classify_theory_residual(
    computed_total: int, maximum_mark: int, empty_count: int, marks_col: int
) -> dict[str, Any]:
    """Decide the theory-path residual cause once a real marks column and its
    (population-correct) defaulted-AnswerPoint count are known -- the
    sufficiency-gated core of ``_classify_theory``, pulled out as a pure
    function so the gate is unit-testable without re-parsing a PDF
    (round-3 brief). ``empty_count`` must be measured by
    ``count_defaulted_answer_points`` (round 5), not ``count_empty_marks_cells``
    (round 4 and earlier) -- see the module docstring's bucket-4 entry for why.

    Sufficiency condition for ``marks_cell_notation_not_parsed`` (round 5 --
    round 4 bounded a two-sided claim that turned out unsound on the deficit
    side even over the corrected population; round 3 bounded only the EXCESS
    side). Empty marks cells default to EXACTLY 1 mark each
    (``lemely/io/det/rows.py``'s ``make_point``), so N empty cells can
    inflate ``computed_total`` above what the non-empty cells alone would
    sum to by AT MOST N -- this EXCESS bound survives as a sound
    necessary-condition check regardless of population, because a defaulted
    point contributes AT MOST 1 whether or not it is actually summed into a
    leaf's ``Question.marks``. The DEFICIT claim ("computed_total can never
    fall below empty_count, since every empty cell still contributes 1") does
    NOT survive: ``lemely/io/det/rows.py``'s ``flush()`` only sums a leaf's
    AnswerPoints into ``Question.marks`` when that leaf's own
    ``q_row_had_answer`` flag was set (the Q-number row itself carried an
    answer, or an EITHER/OR bracket appeared) -- a common table shape
    (Q-number row with NO answer, marks on continuation rows below it) never
    sets that flag, so a defaulted AnswerPoint can contribute exactly 0 to
    ``computed_total``, not >= 1 as round 3/4 assumed.

    The bucket is therefore claimed ONLY via the EXCESS side:
    ``empty_count > 0`` and ``computed_total > maximum_mark`` and
    ``computed_total - maximum_mark <= empty_count``. A deficit shape
    (``computed_total <= maximum_mark``) always falls through to
    ``mismatch_cause`` now; when ``empty_count > 0`` its evidence carries an
    explicit consistency-check-only note (``"upper bound, deficit side
    unbounded"``) rather than an enforced bound, so a reader cannot mistake
    the empty-cell fact for a ruled-in or ruled-out cause in that direction.
    """
    excess_explainable = computed_total > maximum_mark and (
        computed_total - maximum_mark
    ) <= empty_count
    if empty_count > 0 and excess_explainable:
        return {
            "cause": "marks_cell_notation_not_parsed",
            "evidence": (
                f"marks_col={marks_col}: {empty_count} empty marks cell(s) defaulted to 1; "
                f"computed_total={computed_total} maximum_mark={maximum_mark} "
                f"(excess explainable by defaulting: at most {empty_count})"
            ),
        }

    if computed_total != maximum_mark:
        cause = mismatch_cause(computed_total, maximum_mark)
        if empty_count > 0 and computed_total <= maximum_mark:
            # Deficit direction: consistency-check-only, NOT an enforced
            # bound -- see this function's docstring for why the deficit
            # claim is unsound even over the corrected population.
            empty_note = (
                f"{empty_count} empty marks cell(s) were also defaulted (upper bound, "
                "deficit side unbounded: a defaulted AnswerPoint is not guaranteed to "
                "reach computed_total at all, so this count neither confirms nor rules "
                "out empty-cell defaulting as a cause here); "
            )
        elif empty_count > 0:
            empty_note = (
                f"{empty_count} empty marks cell(s) were also defaulted but cannot explain the "
                f"full delta (excess exceeds empty_count={empty_count}); "
            )
        else:
            empty_note = ""
        ruled_out = (
            "an overcount (computed_total < maximum_mark), "
            if cause == "genuine_mark_total_mismatch"
            else ""
        )
        return {
            "cause": cause,
            "evidence": (
                f"marks_col={marks_col} well-detected; {empty_note}ruling out "
                f"{ruled_out}column detection and (sufficient) cell-notation parsing as the "
                f"cause; computed_total={computed_total} maximum_mark={maximum_mark}"
            ),
        }

    return {
        "cause": "UNCLASSIFIED",
        "evidence": (
            f"theory path reconciled cleanly (computed_total={computed_total}) "
            "but was in the det-failure set -- reconcile discrepancy not reproduced"
        ),
    }


def count_empty_marks_cells(rows: list[list[str | None]], marks_col: int) -> int:
    """Count RAW TABLE ROWS where the marks column cell is empty.

    Superseded for ``classify_theory_residual``'s ``empty_count`` by
    ``count_defaulted_answer_points`` (round 5) -- kept here (and still
    unit-tested) only as the documented, characterised counterexample of
    what NOT to use: this scans every "data row" with a blank marks cell,
    including rows that ``build_questions`` never turns into an
    ``AnswerPoint`` at all (e.g. a Q-number row with no answer text of its
    own), which is why it could report ``empty_count=119`` for a scheme
    whose ``maximum_mark`` is 80 -- a population that cannot physically hold
    119 answer points. See ``count_defaulted_answer_points`` for the
    population-correct replacement.
    """
    count = 0
    for row in rows:
        # A "data row" carries some non-empty content elsewhere in the row.
        others = [(c or "").strip() for i, c in enumerate(row) if i != marks_col]
        if not any(others):
            continue
        cell = (row[marks_col] if marks_col < len(row) else None) or ""
        if not cell.strip():
            count += 1
    return count


def count_defaulted_answer_points(
    rows: list[list[str | None]],
    layout: Any,
    max_mark: int,
    header_keywords: frozenset[str],
) -> int:
    """Count AnswerPoints ``build_questions`` actually created whose marks
    value was DEFAULTED by ``lemely/io/det/rows.py``'s ``make_point`` (i.e.
    their marks cell failed to parse), by re-running row-building once with
    transparent instrumentation -- the population-correct replacement for
    ``count_empty_marks_cells``' raw-table-row scan (round-5 root cause: the
    two counts were measuring different populations, so ``empty_count`` and
    ``computed_total`` were not commensurable).

    Mechanism, kept strictly read-only/diagnostic and never touching
    ``lemely/io/det/rows.py``: monkeypatches two names in that module's OWN
    namespace, for the duration of this one call only --

    * ``parse_marks_cell`` — records, per call, whether the real function
      returned ``None`` (an unparseable/empty cell).
    * ``AnswerPoint`` — records, at each construction, whether the most
      recent ``parse_marks_cell`` call (see above) was ``None``.

    Both wrappers are transparent pass-throughs: they call straight through
    to the real function/class and return its exact result unchanged, so
    this does not alter ``build_questions``' actual output in any way (the
    caller re-runs ``build_questions`` separately, unpatched, to get the
    real ``computed_total`` -- this function exists only to OBSERVE, on the
    identical input, how many of the AnswerPoints actually created got the
    1-mark default).

    Correctness of the parse-call/point-construction pairing relies on one
    property of ``build_questions``' row loop, verified by reading
    ``lemely/io/det/rows.py``'s source: exactly one ``parse_marks_cell`` call
    happens per non-blank row (unconditionally, before any row-type branch),
    and AT MOST one ``make_point``/``AnswerPoint`` call happens per row
    thereafter, always consuming that SAME row's parsed value -- so "the most
    recent parse_marks_cell call was None" is an exact per-row correlate of
    "this AnswerPoint was defaulted", not an approximation.
    """
    from lemely.io.det import rows as _rows_mod

    state = {"last_call_was_default": False, "defaulted": 0}
    real_parse_marks_cell = _rows_mod.parse_marks_cell
    real_answer_point = _rows_mod.AnswerPoint

    def _spy_parse_marks_cell(raw: str, cap: int) -> Any:
        result = real_parse_marks_cell(raw, cap)
        state["last_call_was_default"] = result is None
        return result

    def _spy_answer_point(*args: Any, **kwargs: Any) -> Any:
        if state["last_call_was_default"]:
            state["defaulted"] += 1
        return real_answer_point(*args, **kwargs)

    _rows_mod.parse_marks_cell = _spy_parse_marks_cell  # type: ignore[assignment]
    _rows_mod.AnswerPoint = _spy_answer_point  # type: ignore[assignment]
    try:
        _rows_mod.build_questions(rows, layout, max_mark=max_mark, header_keywords=header_keywords)
    finally:
        _rows_mod.parse_marks_cell = real_parse_marks_cell
        _rows_mod.AnswerPoint = real_answer_point

    return state["defaulted"]


# ---------------------------------------------------------------------------
# Per-scheme classification (I/O: opens one PDF, discards its text after use)
# ---------------------------------------------------------------------------


def classify_one(pdf_path: Path) -> dict[str, Any]:
    """Classify a single failing mark-scheme PDF. Returns {cause, evidence}.

    Never raises — every exception is caught and folded into UNCLASSIFIED so
    the denominator is never narrowed by a script crash.
    """
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - environment issue, not a census outcome
        return {"cause": "UNCLASSIFIED", "evidence": f"pdfplumber unavailable: {exc}"}

    try:
        with pdfplumber.open(pdf_path) as pdf:
            cover_text = (pdf.pages[0].extract_text() or "") if pdf.pages else ""

            try:
                metadata = _meta.extract_metadata(pdf, pdf_path)
            except ParseError as exc:
                return {
                    "cause": "UNCLASSIFIED",
                    "evidence": f"metadata extraction failed: {sanitize_evidence(str(exc))}",
                }

            profile = get_profile(metadata.subject_code)
            evidence = classify_profile_misconfiguration(
                metadata.paper_number, cover_text, profile
            )
            if evidence is not None:
                return {"cause": "paper_profile_misconfiguration", "evidence": evidence}

            _gmp.extract_gmp(pdf, metadata)

            if metadata.paper_type == PaperType.MCQ:
                return _classify_mcq(pdf, metadata)
            return _classify_theory(pdf, metadata)
    except Exception as exc:  # noqa: BLE001 - census must never crash on one scheme
        return {
            "cause": "UNCLASSIFIED",
            "evidence": f"unexpected {type(exc).__name__}: {sanitize_evidence(str(exc))}",
        }


def _classify_mcq(pdf: Any, metadata: Any) -> dict[str, Any]:
    all_tables: list[list[list[str | None]]] = []
    for page in pdf.pages[1:]:
        all_tables.extend(page.extract_tables())
    if not all_tables:
        return {
            "cause": "table_layout_extraction_failure",
            "evidence": "MCQ path: no tables found on pages after the cover page",
        }

    any_answer_col = False
    for table in all_tables:
        data_rows = [r for r in table if r and sum(1 for c in r if (c or "").strip()) >= 2]
        if data_rows and find_mcq_answer_col(data_rows) is not None:
            any_answer_col = True
            break
    if not any_answer_col:
        return {
            "cause": "marks_column_detection_failure",
            "evidence": "MCQ path: no table column satisfied find_mcq_answer_col",
        }

    try:
        questions = parse_mcq_tables(all_tables)
    except ParseError as exc:
        return {
            "cause": "table_layout_extraction_failure",
            "evidence": f"MCQ path: {sanitize_evidence(str(exc))}",
        }

    computed = len(questions)  # each MCQ Question carries marks=1
    maximum_mark = metadata.maximum_mark
    if computed < maximum_mark / 2:
        return {
            "cause": "table_layout_extraction_failure",
            "evidence": (
                f"MCQ path: parsed {computed} answers vs maximum_mark={maximum_mark} "
                "(more than half missing -> rows dropped, not a genuine mismatch)"
            ),
        }
    if computed != maximum_mark:
        return {
            "cause": mismatch_cause(computed, maximum_mark),
            "evidence": f"MCQ path: computed_total={computed} maximum_mark={maximum_mark}",
        }
    return {
        "cause": "UNCLASSIFIED",
        "evidence": (
            f"MCQ path reconciled cleanly (computed_total={computed}) "
            "but was in the det-failure set -- reconcile discrepancy not reproduced"
        ),
    }


def _classify_theory(pdf: Any, metadata: Any) -> dict[str, Any]:
    try:
        tables = select_tables(pdf, page_start=2, max_mark=MAX_MARK_PER_POINT)
    except ParseError as exc:
        return {
            "cause": "table_layout_extraction_failure",
            "evidence": f"select_tables: {sanitize_evidence(str(exc))}",
        }
    if not tables:
        return {
            "cause": "table_layout_extraction_failure",
            "evidence": "select_tables returned zero qualifying tables",
        }

    merged: list[list[str | None]] = []
    for table in tables:
        for row in table:
            if not row or len(row) < 2:
                continue
            cells_lower = {(c or "").strip().lower() for c in row}
            if cells_lower & HEADER_KEYWORDS:
                continue
            merged.append(row)
    if not merged:
        return {
            "cause": "table_layout_extraction_failure",
            "evidence": "no non-header theory rows survived merging",
        }

    ncols = max(len(r) for r in merged)
    if ncols < 2:
        return {
            "cause": "table_layout_extraction_failure",
            "evidence": f"merged table has fewer than 2 columns ({ncols})",
        }

    real_marks_col = find_real_marks_col(merged, ncols, MAX_MARK_PER_POINT)
    if real_marks_col is None:
        layout = detect_columns(merged, max_mark=MAX_MARK_PER_POINT)
        return {
            "cause": "marks_column_detection_failure",
            "evidence": (
                f"no column of {ncols} satisfied is_marks_column; "
                f"detect_columns fell back to marks_col={layout.marks_col}"
            ),
        }

    layout = detect_columns(merged, max_mark=MAX_MARK_PER_POINT)
    try:
        questions = build_questions(
            merged, layout, max_mark=MAX_MARK_PER_POINT, header_keywords=HEADER_KEYWORDS
        )
    except ParseError as exc:
        return {
            "cause": "table_layout_extraction_failure",
            "evidence": f"build_questions: {sanitize_evidence(str(exc))}",
        }

    computed = _reconcile._leaf_marks(questions)
    maximum_mark = metadata.maximum_mark
    # Round 5: empty_count is re-derived over the SAME population that
    # feeds `computed` (AnswerPoints build_questions actually created), not
    # raw table rows -- see count_defaulted_answer_points' docstring.
    empty_count = count_defaulted_answer_points(
        merged, layout, MAX_MARK_PER_POINT, HEADER_KEYWORDS
    )

    return classify_theory_residual(
        computed_total=computed,
        maximum_mark=maximum_mark,
        empty_count=empty_count,
        marks_col=real_marks_col,
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _find_pdf(stem: str) -> Path | None:
    matches = list(CORPUS_ROOT.rglob(f"{stem}.pdf"))
    return matches[0] if matches else None


def main() -> None:
    stems = [
        line.strip()
        for line in (CENSUS_A_DIR / "det-failures.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    rows: list[str] = []
    classified: list[tuple[str, str, str]] = []
    # Seeded with every taxonomy label so a zero-count bucket is reported as
    # 0, not silently omitted from cause_counts_ranked.
    causes: Counter[str] = Counter({label: 0 for label in ALL_CAUSES})

    for i, stem in enumerate(stems, 1):
        pdf_path = _find_pdf(stem)
        if pdf_path is None:
            result = {"cause": "UNCLASSIFIED", "evidence": "PDF not found on disk under corpus_root"}
        else:
            result = classify_one(pdf_path)
        cause = result["cause"]
        evidence = result["evidence"]
        causes[cause] += 1
        rows.append(f"{stem}\t{cause}\t{evidence}")
        classified.append((stem, cause, evidence))
        print(f"[{i}/{len(stems)}] {stem}: {cause}", flush=True)

    (OUT_DIR / "classified-failures.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")

    profile_breakdown = profile_misconfiguration_breakdown(classified)
    near_vacuous_stems = excess_bound_near_vacuous_stems(classified)

    assert sum(causes.values()) == len(stems) == 229, (
        f"denominator drift: {sum(causes.values())} classified vs {len(stems)} input stems"
    )

    d7_hypothesis_n = causes["marks_column_detection_failure"] + causes["marks_cell_notation_not_parsed"]

    manifest = {
        "label": "census-2026-08-24-b",
        "issue": 45,
        "milestone": "M2.2",
        "kind": "failure-reason census over the 229 det-parser failures (#88's output set)",
        "spend_usd": 0.0,
        "gemini_calls": 0,
        "input": {
            "source": "../census-2026-08-24-a/det-failures.txt",
            "n": len(stems),
        },
        "cause_counts_ranked": dict(causes.most_common()),
        "counts_sum_to_229": sum(causes.values()) == 229,
        "table_layout_extraction_failure_note": (
            f"count={causes.get('table_layout_extraction_failure', 0)}: this bucket's "
            "ParseError catches are enforced on BOTH the MCQ and theory paths, but the "
            "'computed < maximum_mark / 2' shortfall heuristic (round-4 fix) is enforced "
            "ONLY on the MCQ path (_classify_mcq) -- the theory path has no equivalent "
            "check, so a large theory-path deficit falls through to "
            "classify_theory_residual's mismatch_cause instead of landing here. This count "
            "is therefore a lower bound on structural extraction failures, not a claim that "
            "none occurred on the theory path under a maximum_mark/2 heuristic; an earlier "
            "draft of the module docstring claimed theory-path enforcement that was never "
            "implemented -- corrected in this round."
        ),
        "d7_hypothesis": {
            "statement": (
                "D7 hypothesised that parse_marks_cell/is_marks_column failures "
                "(marks_column_detection_failure + marks_cell_notation_not_parsed) "
                "explain the det-parser failure set."
            ),
            "n_explained": d7_hypothesis_n,
            "n_total": len(stems),
            "share": round(d7_hypothesis_n / len(stems), 4) if stems else 0.0,
            "falsifiable": True,
            "is_upper_bound": True,
            "note": (
                "This count is measured from re-running the pipeline's own column/cell "
                "detectors over each failing PDF, not assumed from the hypothesis by "
                "construction -- other causes (paper_profile_misconfiguration, "
                "table_layout_extraction_failure, mark_aggregation_overcount, "
                "genuine_mark_total_mismatch, UNCLASSIFIED) were checked FIRST wherever "
                "their evidence is more specific. Round 5: marks_cell_notation_not_parsed's "
                "own sufficiency check is now excess-side only (see manifest's absence of a "
                "deficit disjunct) -- the deficit direction is a consistency-check-only note, "
                "not an enforced bound, because a defaulted AnswerPoint is not guaranteed to "
                "reach computed_total at all (lemely/io/det/rows.py's flush() only sums a "
                "leaf's AnswerPoints when that leaf's q_row_had_answer flag was set). This "
                "D7 share is therefore published explicitly as an UPPER BOUND on what the "
                "column/cell-detection hypothesis explains, not a fully enforced count."
            ),
        },
        "excess_bound_near_vacuous": {
            "count": len(near_vacuous_stems),
            "stems": near_vacuous_stems,
            "detail": (
                "Rows in marks_cell_notation_not_parsed whose empty_count >= maximum_mark: "
                "the excess sufficiency check (computed_total - maximum_mark <= empty_count) "
                "is technically satisfied but close to vacuous there, since a bound that "
                "large barely constrains anything. The round-5 population fix "
                "(count_defaulted_answer_points) sharply reduced how often this happens -- "
                "round 4's raw-row count put 4 rows at empty_count >= maximum_mark, one as "
                "high as 119 for a maximum_mark of 80 -- but does not eliminate it entirely "
                "for schemes with a genuinely high fraction of defaulted cells. Recorded "
                "here rather than silently claimed away; these rows are still correctly in "
                "the denominator and still labelled, just with a weaker-than-usual bound."
            ),
        },
        "known_bug_classified_not_fixed": {
            "file": "lemely/io/det/profiles.py:50",
            "count_in_this_bucket": causes.get("paper_profile_misconfiguration", 0),
            "breakdown_by_subject_and_paper": dict(profile_breakdown.most_common()),
            "detail": (
                "0625 p2 maps to THEORY_CORE via paper_type_by_number even though its "
                "cover text reads 'Paper 2 Multiple Choice (Extended)' -- this is #88's "
                "documented bug, labelled here on a demonstrated branch difference "
                "(_changes_parse_path confirms MCQ vs. THEORY_CORE actually sends "
                "classify_one down a different code path), not an attempted counterfactual "
                "reparse. Classified under paper_profile_misconfiguration by this "
                "census. NOT repaired here: question 2 on #88 is an unanswered human "
                "decision, and fixing it would move ~40 schemes between DA1 strata and "
                "invalidate #88's preflight denominator. git diff against "
                "lemely/io/det/profiles.py is empty."
            ),
        },
        "ruled_out_metadata_defect_not_a_cause": {
            "file": "lemely/io/det/profiles.py:52",
            "detail": (
                "profiles.py maps 0625 paper 3 to THEORY_EXTENDED via "
                "paper_type_by_number, but every sampled p3 cover page reads 'Paper 3 Core "
                "Theory' (e.g. 0625_m19_ms_32.pdf, 0625_s21_ms_32.pdf) -- a real metadata "
                "discrepancy, structurally identical to the 0625 p2 bug. It is deliberately "
                "NOT counted among paper_profile_misconfiguration's 229-scheme causes: "
                "classify_one only ever branches on metadata.paper_type once (MCQ vs. "
                "not-MCQ, see classify_one/_classify_mcq/_classify_theory), and "
                "THEORY_EXTENDED vs. THEORY_CORE are on the SAME side of that branch, so "
                "reclassifying under the cover-text-implied type would not change which "
                "code path parses any 0625 p3 scheme in this failure set -- the counterfactual "
                "gate (_changes_parse_path) falsifies it as a cause for all of them, whatever "
                "their exact count (this script does not separately track a 0625-p3-only "
                "count; round 1's '34' was a since-superseded classification, not a number "
                "re-derived by this run). It is recorded here as a "
                "separate, ruled-out metadata defect, flagged for the human alongside "
                "question 2 on #88, and equally NOT repaired here -- git diff against "
                "lemely/io/det/profiles.py is empty."
            ),
        },
        "reproduce": {
            "cost": "free, zero network, ~229 PDFs re-parsed with pdfplumber",
            "steps": [
                "1. .venv/bin/python BUILD/accuracy-runs/census-2026-08-24-b/classify_failures.py",
                "(reads ../census-2026-08-24-a/det-failures.txt, writes classified-failures.txt "
                "+ this manifest in place)",
            ],
        },
        "not_committed": {
            "what": "no PDF text or mark-scheme content is committed",
            "why": (
                "MISSION 12.7: never commit CAIE mark-scheme text verbatim -- only derived "
                "counts, PDF filenames/stems, and classification labels are in "
                "classified-failures.txt."
            ),
        },
    }

    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print("\ncause counts (ranked):")
    for cause, n in causes.most_common():
        print(f"  {cause}: {n}")
    print(f"\nD7 hypothesis explains {d7_hypothesis_n}/{len(stems)} of the 229")


if __name__ == "__main__":
    main()
