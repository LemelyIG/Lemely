"""The golden corpus must exercise the whitespace metamorphic property (B5, #88 item 6).

Before these fixtures existed, ``normalise_answer_whitespace`` was a strict
no-op corpus-wide: every one of the 71 golden answers was already
whitespace-normal, so the property reported 0 held / 0 violated / 71 skipped
and bought no evidence at any price.

The human's B5 ruling (2026-08-26) is that the fixtures join the ORDINARY
golden corpus rather than a metamorphic-only set, against the orchestrator's
recommendation. These tests pin both halves of that: the property fires, and
adding the variant does not disturb the DA6 distinct-leaf denominator.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from lemely.accuracy.harness import load_golden_cases

GOLDEN = Path(__file__).resolve().parent / "golden"
_RUNS = re.compile(r"\s+")


def _is_collapsible(text: str) -> bool:
    """True when whitespace normalisation would actually change *text*."""
    return _RUNS.sub(" ", text).strip() != text


class TestWhitespacePropertyHasCoverage(unittest.TestCase):
    def test_some_golden_answer_carries_collapsible_whitespace(self) -> None:
        """Fails before the fixture is added: the transform was a corpus-wide no-op."""
        cases = load_golden_cases(GOLDEN)
        collapsible = [
            (case.paper_id, case.fixture_variant, qid)
            for case in cases
            for qid, golden in case.ground_truth.items()
            if _is_collapsible(golden.student_answer)
        ]
        self.assertTrue(
            collapsible,
            "no golden answer carries collapsible whitespace, so "
            "normalise_answer_whitespace is a no-op and the property is untestable",
        )

    def test_the_whitespace_variant_is_loaded_as_an_ordinary_golden_case(self) -> None:
        """B5: ordinary corpus member, not a metamorphic-only side set."""
        variants = {(case.paper_id, case.fixture_variant) for case in load_golden_cases(GOLDEN)}
        self.assertIn(("0580_s23_qp_22_theory", "whitespace"), variants)


class TestWhitespaceVariantPreservesTheDenominator(unittest.TestCase):
    """DA6 counts distinct leaves by (paper_id, question_id).

    The variant shares its paper_id with the sibling it was derived from, so it
    contributes no NEW distinct leaf. This is what makes B5 cheaper than the
    ruling anticipated, and it is asserted rather than claimed.
    """

    def test_distinct_leaf_count_is_unchanged_at_31(self) -> None:
        cases = load_golden_cases(GOLDEN)
        leaves = {(c.paper_id, qid) for c in cases for qid in c.ground_truth}
        self.assertEqual(len(leaves), 31)

    def test_variant_leaves_are_a_subset_of_its_siblings_leaves(self) -> None:
        cases = load_golden_cases(GOLDEN)
        by_variant = {
            c.fixture_variant: set(c.ground_truth)
            for c in cases
            if c.paper_id == "0580_s23_qp_22_theory"
        }
        self.assertTrue(
            by_variant["whitespace"] <= by_variant["correct"],
            "the whitespace variant must not introduce leaves its siblings lack, "
            "or it would silently enlarge the denominator",
        )

    def test_awarded_marks_are_inherited_not_invented(self) -> None:
        """Marking is examiner judgment (MISSION 12.7); the variant may only
        restate marks its sibling already carries."""
        cases = {
            c.fixture_variant: c
            for c in load_golden_cases(GOLDEN)
            if c.paper_id == "0580_s23_qp_22_theory"
        }
        for qid, golden in cases["whitespace"].ground_truth.items():
            self.assertEqual(
                golden.awarded_marks,
                cases["correct"].ground_truth[qid].awarded_marks,
                f"{qid}: whitespace variant changed a mark",
            )

    def test_answers_differ_from_the_sibling_only_by_whitespace(self) -> None:
        cases = {
            c.fixture_variant: c
            for c in load_golden_cases(GOLDEN)
            if c.paper_id == "0580_s23_qp_22_theory"
        }
        for qid, golden in cases["whitespace"].ground_truth.items():
            sibling = cases["correct"].ground_truth[qid].student_answer
            self.assertEqual(
                _RUNS.sub(" ", golden.student_answer).strip(),
                _RUNS.sub(" ", sibling).strip(),
                f"{qid}: differs from its sibling by more than whitespace",
            )


if __name__ == "__main__":
    unittest.main()
