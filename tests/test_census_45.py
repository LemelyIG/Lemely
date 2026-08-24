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
    """

    def test_excess_larger_than_empty_count_falls_through_to_overcount(self) -> None:
        # Shape of the round-3 brief's own counterexample (0606_m20_ms_12:
        # empty=4, excess=20 -- 20 > 4, so defaulting cannot explain it).
        result = mod.classify_theory_residual(
            computed_total=60, maximum_mark=40, empty_count=4, marks_col=2
        )
        self.assertEqual(result["cause"], "mark_aggregation_overcount")
        self.assertIn("empty", result["evidence"].lower())

    def test_computed_leq_maximum_with_empty_cells_still_lands_in_notation_bucket(self) -> None:
        # Positive case: computed_total <= maximum_mark is always explainable
        # by *some* cells being under-counted via defaulting -- the gate must
        # not over-correct away the real notation-bucket finding.
        result = mod.classify_theory_residual(
            computed_total=38, maximum_mark=40, empty_count=2, marks_col=2
        )
        self.assertEqual(result["cause"], "marks_cell_notation_not_parsed")

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

    def test_deficit_at_or_above_empty_count_still_lands_in_notation_bucket(self) -> None:
        # Positive case, unchanged from round 3: computed_total >= empty_count
        # and <= maximum_mark IS within what the defaulting mechanism can
        # produce -- the round-4 fix must not over-correct away this finding.
        result = mod.classify_theory_residual(
            computed_total=38, maximum_mark=40, empty_count=2, marks_col=2
        )
        self.assertEqual(result["cause"], "marks_cell_notation_not_parsed")


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


# ---------------------------------------------------------------------------
# Denominator-never-narrowed: mechanical, artifact-only (no PDF re-parsing).
# ---------------------------------------------------------------------------


def _read_stems(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
