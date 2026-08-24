"""#45 (M2.2): failure-reason census over the 229 det-parser failures.

Two things are tested:

1. The pure classifier helper that flags a "paper-profile misconfiguration"
   (the 0625 p2 class, see BUILD/accuracy-runs/census-2026-08-24-a/manifest.json's
   ``known_bug_not_fixed_here``) — this requires no I/O, matching
   ``BUILD/accuracy-runs/census-2026-08-24-b/classify_failures.py``'s claim that
   its classification rules are pure functions of captured signals. Mirrors
   ``tests/test_parsers_det.py``'s ``IsMarksColumnTests`` style.

2. A mechanical, cheap (no PDF re-parsing) check that the committed census
   artifact never narrowed the denominator: every one of the 229 stems in
   ``det-failures.txt`` appears exactly once in ``classified-failures.txt``
   with a non-empty cause label. This is the acceptance criterion "the
   denominator (229) is never narrowed" made falsifiable by a test rather
   than trusted by construction.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from lemely.io.det.profiles import get_profile

_CENSUS_A = Path(__file__).resolve().parents[1] / "BUILD" / "accuracy-runs" / "census-2026-08-24-a"
_CENSUS_B = Path(__file__).resolve().parents[1] / "BUILD" / "accuracy-runs" / "census-2026-08-24-b"
_SCRIPT = _CENSUS_B / "classify_failures.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("classify_failures_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


class ClassifyProfileMisconfigurationTests(unittest.TestCase):
    def test_0625_p2_cover_says_mcq_but_number_map_says_theory_core(self) -> None:
        profile = get_profile("0625")
        cover_text = (
            "UNIVERSITY OF CAMBRIDGE INTERNATIONAL EXAMINATIONS\n"
            "Cambridge IGCSE\n"
            "MARK SCHEME for the May/June 2021 series\n"
            "0625 PHYSICS\n"
            "0625/21\n"
            "Paper 2 Multiple Choice (Extended)\n"
            "Maximum Mark: 40\n"
        )
        evidence = mod.classify_profile_misconfiguration(2, cover_text, profile)
        self.assertIsNotNone(evidence)
        self.assertIn("mcq", evidence.lower())

    def test_matching_paper_is_not_flagged(self) -> None:
        profile = get_profile("0625")
        cover_text = "Paper 1 Multiple Choice (Core)\nMaximum Mark: 40\n"
        evidence = mod.classify_profile_misconfiguration(1, cover_text, profile)
        self.assertIsNone(evidence)

    def test_ambiguous_cover_text_is_not_flagged(self) -> None:
        profile = get_profile("0580")
        # Cover text carries none of the recognised keywords -> no signal either way.
        evidence = mod.classify_profile_misconfiguration(1, "no keywords here", profile)
        self.assertIsNone(evidence)

    def test_paper_not_in_number_map_is_not_flagged(self) -> None:
        # 0625 paper 61/62 are not in paper_type_by_number's small-int keys used
        # by the misconfiguration check's own paper_number param range here;
        # use a code with an empty map instead to exercise the "not consulted" path.
        profile = get_profile("9999")  # falls back to _DEFAULT_PROFILE
        evidence = mod.classify_profile_misconfiguration(99, "Paper 99 Multiple Choice", profile)
        self.assertIsNone(evidence)

    def test_0625_p3_core_extended_is_not_flagged_no_path_change(self) -> None:
        # profiles.py maps p3 to THEORY_EXTENDED but the cover text reads
        # "Paper 3 Core Theory" -> implies THEORY_CORE. Both mapped and implied
        # are non-MCQ, so classify_one would take the SAME (_classify_theory)
        # branch either way -- the discrepancy is causally inert and must NOT
        # be counted as paper_profile_misconfiguration (round-2 review MUST-FIX).
        profile = get_profile("0625")
        cover_text = (
            "UNIVERSITY OF CAMBRIDGE INTERNATIONAL EXAMINATIONS\n"
            "Cambridge IGCSE\n"
            "0625 PHYSICS\n"
            "0625/32\n"
            "Paper 3 Core Theory\n"
            "Maximum Mark: 80\n"
        )
        evidence = mod.classify_profile_misconfiguration(3, cover_text, profile)
        self.assertIsNone(evidence)

    def test_0625_p2_mcq_still_flagged_after_counterfactual_gate(self) -> None:
        # Regression guard: the gate must not over-correct away the real p2
        # finding, where mapped=THEORY_CORE vs implied=MCQ IS a path change.
        profile = get_profile("0625")
        cover_text = "Paper 2 Multiple Choice (Extended)\nMaximum Mark: 40\n"
        evidence = mod.classify_profile_misconfiguration(2, cover_text, profile)
        self.assertIsNotNone(evidence)
        self.assertIn("mcq", evidence.lower())


class MismatchCauseSplitTests(unittest.TestCase):
    def test_computed_total_exceeds_maximum_mark_splits_to_overcount_bucket(self) -> None:
        self.assertEqual(mod.mismatch_cause(50, 40), "mark_aggregation_overcount")

    def test_computed_total_below_maximum_mark_is_genuine_mismatch(self) -> None:
        self.assertEqual(mod.mismatch_cause(38, 40), "genuine_mark_total_mismatch")

    def test_equal_totals_is_an_out_of_contract_call_not_a_supported_case(self) -> None:
        # mismatch_cause's documented contract is "called once computed !=
        # maximum_mark" (see classify_failures.py callers) -- equal inputs are
        # NOT a case this helper is asked to classify in production. This
        # pins the current defensive fallback (genuine_mark_total_mismatch,
        # not a crash) as a characterisation test of out-of-contract input,
        # not an endorsement that "computed == maximum_mark" is a real
        # mismatch cause (round-3 NIT 9: clarify, don't just assert).
        self.assertEqual(mod.mismatch_cause(40, 40), "genuine_mark_total_mismatch")


class TheoryResidualSufficiencyTests(unittest.TestCase):
    """Sufficiency-condition gate for the theory-path residual causes.

    Empty marks cells default to 1 mark each (``lemely/io/det/rows.py``'s
    ``make_point``), so N empty cells can inflate ``computed_total`` away from
    ``maximum_mark`` by AT MOST N. ``marks_cell_notation_not_parsed`` may only
    be claimed when that bound actually explains the observed delta; anything
    larger is positively-evidenced overcounting that empty-cell defaulting
    cannot produce, and must fall through to ``mismatch_cause`` (round-3
    brief, blocking defect: 27/135 rows previously violated this).

    Round 5: the DEFICIT side of this gate (``empty_count <= computed_total``)
    is retired as a causal classifier -- see ``DeficitConsistencyCheckOnlyTests``
    below and the module docstring's bucket-4 entry. The EXCESS side is
    unaffected and still enforced exactly as round 4 left it.
    """

    def test_excess_larger_than_empty_count_falls_through_to_overcount(self) -> None:
        # Shape of the round-3 brief's own counterexample (0606_m20_ms_12:
        # empty=4, excess=20 -- 20 > 4, so defaulting cannot explain it).
        result = mod.classify_theory_residual(
            computed_total=60, maximum_mark=40, empty_count=4, marks_col=2
        )
        self.assertEqual(result["cause"], "mark_aggregation_overcount")
        self.assertIn("empty", result["evidence"].lower())

    def test_computed_leq_maximum_with_empty_cells_no_longer_lands_in_notation_bucket(
        self,
    ) -> None:
        # Round 5 (was "still_lands_in_notation_bucket" through round 4):
        # a deficit shape is no longer a positive classifier for this bucket
        # -- see DeficitConsistencyCheckOnlyTests for why the bound is
        # unsound even over the corrected (AnswerPoint) population.
        result = mod.classify_theory_residual(
            computed_total=38, maximum_mark=40, empty_count=2, marks_col=2
        )
        self.assertNotEqual(result["cause"], "marks_cell_notation_not_parsed")

    def test_small_explainable_excess_still_lands_in_notation_bucket(self) -> None:
        # excess (2) <= empty_count (4) -> within the magnitude the defaulting
        # mechanism can produce -- must still land in the notation bucket.
        result = mod.classify_theory_residual(
            computed_total=42, maximum_mark=40, empty_count=4, marks_col=2
        )
        self.assertEqual(result["cause"], "marks_cell_notation_not_parsed")

    def test_excess_exactly_equal_to_empty_count_is_the_boundary_and_still_explainable(
        self,
    ) -> None:
        result = mod.classify_theory_residual(
            computed_total=44, maximum_mark=40, empty_count=4, marks_col=2
        )
        self.assertEqual(result["cause"], "marks_cell_notation_not_parsed")

    def test_zero_empty_cells_goes_straight_to_mismatch_cause(self) -> None:
        result = mod.classify_theory_residual(
            computed_total=50, maximum_mark=40, empty_count=0, marks_col=2
        )
        self.assertEqual(result["cause"], "mark_aggregation_overcount")

    def test_excess_larger_than_empty_count_can_still_resolve_via_mismatch_cause(self) -> None:
        # Falling through must actually re-run mismatch_cause's own
        # comparison, not hardcode overcount: computed_total > maximum_mark
        # with an unexplainable excess still resolves via mismatch_cause,
        # which for computed_total > maximum_mark is mark_aggregation_overcount.
        result = mod.classify_theory_residual(
            computed_total=61, maximum_mark=40, empty_count=1, marks_col=2
        )
        self.assertEqual(result["cause"], "mark_aggregation_overcount")
        self.assertIn("empty", result["evidence"].lower())

    def test_zero_empty_cells_and_clean_totals_is_unclassified(self) -> None:
        result = mod.classify_theory_residual(
            computed_total=40, maximum_mark=40, empty_count=0, marks_col=2
        )
        self.assertEqual(result["cause"], "UNCLASSIFIED")

    def test_deficit_below_empty_count_does_not_land_in_notation_bucket(self) -> None:
        # Round-4 brief's headline counterexample: 0606_w23_ms_11 -- empty=65,
        # computed_total=0. Each empty cell defaults to >=1 mark
        # (lemely/io/det/rows.py's make_point), so computed_total can never
        # validly fall BELOW empty_count under that mechanism. Round 3 bounded
        # only the excess side; the pre-round-4 deficit disjunct
        # (`computed_total <= maximum_mark`) was unconditional and would
        # wrongly claim this row. It must fall through to mismatch_cause
        # instead (genuine_mark_total_mismatch, since 0 < maximum_mark).
        result = mod.classify_theory_residual(
            computed_total=0, maximum_mark=80, empty_count=65, marks_col=2
        )
        self.assertNotEqual(result["cause"], "marks_cell_notation_not_parsed")
        self.assertEqual(result["cause"], "genuine_mark_total_mismatch")

    def test_deficit_counterexamples_from_round_4_brief_do_not_land_in_notation_bucket(
        self,
    ) -> None:
        # The other 3 verified deficit counterexample rows (empty_count,
        # computed_total, maximum_mark triples taken from the live re-run of
        # classify_failures.py against the real corpus, i.e.
        # classified-failures.txt -- NOT the round-4 brief's own approximate
        # list, two of whose six named rows turn out on the real maximum_mark
        # to be excess-explainable (computed_total > maximum_mark), not
        # deficit counterexamples at all: 0625_w21_ms_43 (empty=119,
        # computed=90, maximum_mark=80 -> excess=10<=119, correctly stays in
        # the bucket) and 0625_w21_ms_53 (empty=54, computed=41,
        # maximum_mark=40 -> excess=1<=54, likewise). Using the brief's
        # approximate numbers instead of the real ones would misrepresent the
        # evidence, so only the four rows independently verified against
        # classified-failures.txt are pinned here (0606_w23_ms_11 is pinned
        # separately above).
        counterexamples = [
            # (empty_count, computed_total, maximum_mark)
            (96, 78, 80),  # 0625_w21_ms_41
            (69, 61, 80),  # 0606_w19_ms_13
            (60, 54, 80),  # 0606_s23_ms_22
        ]
        for empty_count, computed_total, maximum_mark in counterexamples:
            with self.subTest(
                empty_count=empty_count, computed_total=computed_total, maximum_mark=maximum_mark
            ):
                result = mod.classify_theory_residual(
                    computed_total=computed_total,
                    maximum_mark=maximum_mark,
                    empty_count=empty_count,
                    marks_col=2,
                )
                self.assertNotEqual(result["cause"], "marks_cell_notation_not_parsed")

    def test_deficit_at_or_above_empty_count_no_longer_a_positive_case(self) -> None:
        # Round 3/4 treated "computed_total >= empty_count and <=
        # maximum_mark" as a positive, bucket-claiming case. Round 5 retires
        # that disjunct entirely (DeficitConsistencyCheckOnlyTests) -- this
        # exact input is now a duplicate of the deficit test above, kept as
        # its own test so a future edit can't silently resurrect the old
        # behaviour for this specific input without a test failing.
        result = mod.classify_theory_residual(
            computed_total=38, maximum_mark=40, empty_count=2, marks_col=2
        )
        self.assertNotEqual(result["cause"], "marks_cell_notation_not_parsed")


class DeficitConsistencyCheckOnlyTests(unittest.TestCase):
    """Round 5: no sound two-sided magnitude bound survives for the deficit
    direction, even once ``empty_count`` is re-derived over the correct
    (AnswerPoint) population (``count_defaulted_answer_points``) -- see the
    module docstring's bucket-4 entry and ``BUILD/ACCURACY-STATE.md``'s
    round-5 commit message for the proof sketch.

    Root cause of why the deficit bound cannot be salvaged: a defaulted
    ``AnswerPoint`` is not guaranteed to ever reach ``computed_total`` at
    all. ``lemely/io/det/rows.py``'s ``flush()`` only sums a leaf's
    ``AnswerPoint``s into ``Question.marks`` when that leaf's own
    ``q_row_had_answer`` flag was set (i.e. the Q-number row itself carried
    an answer, or an EITHER/OR bracket appeared) -- a very common table shape
    (Q-number row with NO answer, all marks on continuation rows below it)
    never sets that flag, so the leaf's ``Question.marks`` stays at
    whatever ``push_question`` set (0, when that row's own marks cell was
    blank), regardless of what the continuation rows' ``AnswerPoint.marks``
    values are. So "every empty cell contributes >= 1 to computed_total" is
    false in general, not just under the wrong (raw-row) population --
    ``CountDefaultedAnswerPointsTests.test_does_not_change_build_questions_output``
    demonstrates the same shape.

    Because of this, the deficit disjunct is retired as a CAUSAL classifier:
    ``marks_cell_notation_not_parsed`` may only be claimed via the EXCESS
    side now. A deficit shape (``computed_total <= maximum_mark`` with
    ``empty_count > 0``) always falls through to ``mismatch_cause``, carrying
    a consistency-check-only note in its evidence rather than an enforced
    bound.
    """

    def test_deficit_shape_falls_through_to_mismatch_cause(self) -> None:
        # Before round 5, classify_theory_residual's deficit_explainable
        # disjunct (empty_count <= computed_total <= maximum_mark) claimed
        # this bucket for ANY row satisfying that arithmetic. It must land
        # OUTSIDE marks_cell_notation_not_parsed now.
        result = mod.classify_theory_residual(
            computed_total=38, maximum_mark=40, empty_count=2, marks_col=2
        )
        self.assertNotEqual(result["cause"], "marks_cell_notation_not_parsed")
        self.assertEqual(result["cause"], "genuine_mark_total_mismatch")

    def test_deficit_evidence_states_upper_bound_deficit_side_unbounded(self) -> None:
        result = mod.classify_theory_residual(
            computed_total=38, maximum_mark=40, empty_count=2, marks_col=2
        )
        self.assertIn("upper bound, deficit side unbounded", result["evidence"])

    def test_zero_empty_count_deficit_carries_no_spurious_note(self) -> None:
        # No empty cells at all -> nothing to caveat; the note must not
        # appear when empty_count is 0 (there is no defaulting mechanism in
        # play to caveat about).
        result = mod.classify_theory_residual(
            computed_total=38, maximum_mark=40, empty_count=0, marks_col=2
        )
        self.assertNotIn("upper bound, deficit side unbounded", result["evidence"])

    def test_excess_side_still_enforced_unchanged(self) -> None:
        # The excess-side sufficiency check is unaffected by the round-5
        # downgrade: it remains sound as a NECESSARY-condition bound, since a
        # defaulted point contributes AT MOST 1 to computed_total whether or
        # not it actually flows into a leaf's Question.marks.
        result = mod.classify_theory_residual(
            computed_total=42, maximum_mark=40, empty_count=4, marks_col=2
        )
        self.assertEqual(result["cause"], "marks_cell_notation_not_parsed")

    def test_excess_beyond_empty_count_still_falls_through(self) -> None:
        result = mod.classify_theory_residual(
            computed_total=61, maximum_mark=40, empty_count=1, marks_col=2
        )
        self.assertEqual(result["cause"], "mark_aggregation_overcount")


class TheoryPathHalfShortfallDocstringTests(unittest.TestCase):
    """MUST-FIX 2 (round-4 brief): the module docstring claimed the
    ``computed < maximum_mark / 2`` shortfall check is enforced in BOTH
    ``_classify_mcq`` and ``_classify_theory``. Verified false -- the sole
    occurrence was inside ``_classify_mcq``. Resolution taken here: correct
    the docstring to state the true, narrower claim (MCQ-path-only) rather
    than implement a new, untested heuristic on the theory path. This test
    pins that resolution so a future edit cannot silently re-introduce the
    false claim without a test noticing.
    """

    def test_docstring_no_longer_claims_theory_path_enforcement(self) -> None:
        doc = mod.__doc__ or ""
        self.assertIn("_classify_mcq", doc)
        # The corrected docstring must not claim the shortfall check is
        # enforced in _classify_theory -- it must say ONLY in _classify_mcq.
        self.assertIn("enforced ONLY in ``_classify_mcq``", doc)

    def test_classify_theory_has_no_half_shortfall_heuristic(self) -> None:
        import inspect

        source = inspect.getsource(mod._classify_theory)
        self.assertNotIn("maximum_mark / 2", source)


class SanitizeEvidenceTests(unittest.TestCase):
    def test_redacts_a_simple_quoted_span(self) -> None:
        out = mod.sanitize_evidence("select_tables: no table matched header 'Question'")
        self.assertNotIn("Question", out)
        self.assertIn("[redacted]", out)

    def test_redacts_parenthesised_quote_with_apostrophe_inside(self) -> None:
        # rows.py:242's actual ParseError shape: f"Level-descriptor row
        # ('{q_cell}'): document uses levels-based marking..." -- if q_cell
        # itself contains an apostrophe (e.g. "student's response"), a
        # naive quote-to-quote regex stops at that inner apostrophe and
        # leaks the rest of the PDF-derived text. This is the exact case
        # the round-3 brief's SHOULD-FIX 7 flags as unverified.
        raw = (
            "Level-descriptor row ('student's response level'): document uses "
            "levels-based marking — fall back to Gemini parser"
        )
        out = mod.sanitize_evidence(raw)
        self.assertNotIn("student", out)
        self.assertNotIn("response", out)
        self.assertNotIn("level'", out)
        self.assertIn("[redacted]", out)
        self.assertIn("document uses", out)  # non-quoted prose survives

    def test_text_with_no_quotes_is_unchanged(self) -> None:
        raw = "Theory table contained no questions after parsing"
        self.assertEqual(mod.sanitize_evidence(raw), raw)


class PureHelperTests(unittest.TestCase):
    def test_find_real_marks_col_returns_none_on_fallback(self) -> None:
        # No column here satisfies is_marks_column (no numeric-looking marks
        # cells at all) -> the right-to-left scan must return None, not
        # silently fall back to the rightmost column.
        rows: list[list[str | None]] = [
            ["Q1", "some answer text", "more text"],
            ["Q2", "another answer", "other text"],
        ]
        result = mod.find_real_marks_col(rows, ncols=3, max_mark=40)
        self.assertIsNone(result)

    def test_count_empty_marks_cells(self) -> None:
        rows: list[list[str | None]] = [
            ["1", "answer one", "2"],
            ["2", "answer two", ""],
            ["", "", ""],  # not a data row: everything else is empty too
            ["3", "answer three", None],
        ]
        # marks_col = 2; two data rows have an empty/None marks cell.
        self.assertEqual(mod.count_empty_marks_cells(rows, marks_col=2), 2)

    def test_profile_misconfiguration_breakdown_groups_by_subject_and_paper(self) -> None:
        rows = [
            ("0625_s21_ms_21", "paper_profile_misconfiguration", "paper_number=2 maps to ..."),
            ("0625_w20_ms_21", "paper_profile_misconfiguration", "paper_number=2 maps to ..."),
            ("0580_s19_ms_11", "table_layout_extraction_failure", "no tables found"),
        ]
        breakdown = mod.profile_misconfiguration_breakdown(rows)
        self.assertEqual(breakdown, {"0625 p2": 2})


class ExcessBoundNearVacuousStemsTests(unittest.TestCase):
    """The excess sufficiency check is technically satisfied but close to
    vacuous when ``empty_count >= maximum_mark`` -- honestly surfaced in the
    manifest (``excess_bound_near_vacuous``) rather than silently claimed
    as a tight bound.
    """

    def test_flags_only_rows_with_empty_count_at_or_above_maximum_mark(self) -> None:
        rows = [
            (
                "stem_vacuous",
                "marks_cell_notation_not_parsed",
                "marks_col=6: 90 empty marks cell(s) defaulted to 1; "
                "computed_total=98 maximum_mark=80 (excess explainable by defaulting: at most 90)",
            ),
            (
                "stem_tight",
                "marks_cell_notation_not_parsed",
                "marks_col=2: 4 empty marks cell(s) defaulted to 1; "
                "computed_total=42 maximum_mark=40 (excess explainable by defaulting: at most 4)",
            ),
            (
                "stem_other_bucket",
                "genuine_mark_total_mismatch",
                "marks_col=2 well-detected; 90 empty marks cell(s) were also defaulted "
                "(upper bound, deficit side unbounded); computed_total=30 maximum_mark=80",
            ),
        ]
        result = mod.excess_bound_near_vacuous_stems(rows)
        self.assertEqual(result, ["stem_vacuous"])


class CountDefaultedAnswerPointsTests(unittest.TestCase):
    """Round 5's re-derivation of ``empty_count`` over the population that
    actually feeds ``computed_total`` (AnswerPoints created by
    ``build_questions``), replacing ``count_empty_marks_cells``' raw-table-row
    scan for that purpose (round-5 root cause: the two counts were measuring
    different populations -- ``count_empty_marks_cells`` could report
    ``empty_count=119`` for a scheme whose ``maximum_mark`` is 80, which
    cannot have 119 answer points at all).
    """

    def test_counts_only_created_answer_points_not_raw_rows(self) -> None:
        from lemely.io.det.columns import ColumnLayout

        # Row 0 and row 2 are Q-number-only rows with NO answer text -- they
        # never reach make_point at all (no AnswerPoint is created), yet
        # count_empty_marks_cells' raw-row scan counts them anyway because
        # their Q-cell is non-empty and their marks cell is blank. Row 1 has
        # a real, correctly-parsed (non-defaulted) marks value. Row 3 is the
        # ONLY row that both produces an AnswerPoint AND had its marks value
        # actually defaulted by make_point.
        rows: list[list[str | None]] = [
            ["1(a)", "", ""],
            ["", "actual answer text one", "1"],
            ["1(b)", "", ""],
            ["", "actual answer text two", ""],
        ]
        layout = ColumnLayout(q_col=0, answer_col_end=2, guidance_col=None, marks_col=2)

        old_count = mod.count_empty_marks_cells(rows, marks_col=2)
        new_count = mod.count_defaulted_answer_points(
            rows, layout, mod.MAX_MARK_PER_POINT, mod.HEADER_KEYWORDS
        )

        self.assertEqual(old_count, 3, "sanity: old raw-row scan sees 3 blank-marks data rows")
        self.assertEqual(
            new_count,
            1,
            "corrected count must only see the ONE row that actually created a "
            "defaulted AnswerPoint",
        )

    def test_does_not_change_build_questions_output(self) -> None:
        # The instrumentation must be a transparent pass-through: deriving
        # empty_count must never perturb the actual parse result that feeds
        # computed_total. Also demonstrates the DeficitConsistencyCheckOnlyTests
        # root cause directly: this leaf's own Q-row carries no answer, so
        # neither of its two AnswerPoints (one parsed, one defaulted) is
        # summed into Question.marks -- computed_total is 0 despite a
        # non-zero empty_count.
        from lemely.io.det import reconcile as _reconcile
        from lemely.io.det.columns import ColumnLayout
        from lemely.io.det.rows import build_questions

        rows: list[list[str | None]] = [
            ["1(a)", "", ""],
            ["", "actual answer text one", "1"],
            ["", "actual answer text two", ""],
        ]
        layout = ColumnLayout(q_col=0, answer_col_end=2, guidance_col=None, marks_col=2)
        kwargs = {"max_mark": mod.MAX_MARK_PER_POINT, "header_keywords": mod.HEADER_KEYWORDS}

        before = build_questions(rows, layout, **kwargs)
        before_total = _reconcile._leaf_marks(before)

        empty_count = mod.count_defaulted_answer_points(
            rows, layout, mod.MAX_MARK_PER_POINT, mod.HEADER_KEYWORDS
        )

        after = build_questions(rows, layout, **kwargs)
        after_total = _reconcile._leaf_marks(after)

        self.assertEqual(before_total, after_total, "instrumentation must not change the parse")
        self.assertEqual(empty_count, 1)
        self.assertEqual(before_total, 0, "root cause: the defaulted point never reaches marks")


# ---------------------------------------------------------------------------
# Denominator-never-narrowed: mechanical, artifact-only (no PDF re-parsing).
# ---------------------------------------------------------------------------


def _read_stems(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class ManifestPublishesUpperBoundTests(unittest.TestCase):
    """Round 5: with the deficit disjunct downgraded to consistency-check-
    only, D7's headline share is no longer a fully-enforced count for the
    ``marks_cell_notation_not_parsed`` half of it -- the manifest must say so
    explicitly rather than silently implying the old two-sided bound still
    holds (acceptance criterion: "D7's share is published explicitly as an
    upper bound rather than an enforced count").
    """

    def test_d7_hypothesis_note_states_upper_bound(self) -> None:
        import json

        manifest = json.loads((_CENSUS_B / "manifest.json").read_text(encoding="utf-8"))
        note = manifest["d7_hypothesis"]["note"]
        self.assertIn("upper bound", note.lower())

    def test_counts_still_sum_to_229(self) -> None:
        import json

        manifest = json.loads((_CENSUS_B / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["counts_sum_to_229"])
        self.assertEqual(sum(manifest["cause_counts_ranked"].values()), 229)


class DenominatorNeverNarrowedTests(unittest.TestCase):
    def test_every_det_failure_stem_is_classified_exactly_once(self) -> None:
        classified_path = _CENSUS_B / "classified-failures.txt"
        self.assertTrue(
            classified_path.exists(),
            f"missing committed artifact {classified_path} -- a deleted census artifact "
            "must fail this test, not silently pass as skipped",
        )

        input_stems = _read_stems(_CENSUS_A / "det-failures.txt")
        rows = _read_stems(classified_path)

        classified_stems: list[str] = []
        labels_by_stem: dict[str, str] = {}
        for row in rows:
            parts = row.split("\t")
            self.assertGreaterEqual(
                len(parts), 2, f"malformed row (expected 'stem<TAB>label<TAB>evidence'): {row!r}"
            )
            stem, label = parts[0], parts[1]
            classified_stems.append(stem)
            labels_by_stem[stem] = label

        self.assertEqual(
            len(input_stems), 229, f"det-failures.txt denominator drifted: {len(input_stems)}"
        )
        self.assertEqual(
            len(classified_stems),
            len(input_stems),
            "the denominator was narrowed: "
            f"{len(classified_stems)} classified rows vs {len(input_stems)} input stems",
        )
        self.assertEqual(
            set(classified_stems), set(input_stems), "classified stems do not match input"
        )
        self.assertEqual(len(classified_stems), len(set(classified_stems)), "duplicate stem rows")
        for stem, label in labels_by_stem.items():
            self.assertTrue(label.strip(), f"empty cause label for {stem}")


if __name__ == "__main__":
    unittest.main()
