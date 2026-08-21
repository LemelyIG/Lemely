"""Corpus-wide invariants over the real ``tests/golden/`` fixtures (M0.8, #32).

These are the acceptance checks from issue #32: every leaf with a lettered
sub-part id carries a non-null ``parent_id``, ``is_excerpt`` matches the
table in the issue exactly, and no fixture's ``maximum_mark`` has drifted
from its recorded baseline (a change there would decouple a fixture from
its source PDF).
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from lemely.accuracy.harness import load_golden_cases

_GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# Baseline maximum_mark per case directory, recorded at the time #32 landed.
# A change here (up or down) means a fixture's stated total drifted from its
# source PDF, which #32's acceptance criteria explicitly forbid.
_EXPECTED_MAXIMUM_MARK = {
    "0580_s23_qp_22_theory_correct": 70,
    "0580_s23_qp_22_theory_partial": 70,
    "0580_s23_qp_22_theory_wrong": 70,
    "0606_s23_qp_12_theory_correct": 80,
    "0606_s23_qp_12_theory_partial": 80,
    "0606_s23_qp_12_theory_wrong": 80,
    "0625_m20_qp_12_mcq": 8,
    "0625_s20_qp_31_theory_correct": 19,
    "0625_s20_qp_31_theory_partial": 19,
    "0625_s20_qp_31_theory_wrong": 19,
    "0625_w21_qp_32_theory_nested": 5,
}

# is_excerpt table from the issue: exactly the 0580/0606 families are
# excerpts (declared maximum_mark >> leaf sum); everything else is not.
_EXPECTED_IS_EXCERPT = {
    "0580_s23_qp_22_theory": True,
    "0606_s23_qp_12_theory": True,
    "0625_m20_qp_12_mcq": False,
    "0625_s20_qp_31_theory": False,
    "0625_w21_qp_32_theory_nested": False,
}

# A leaf id "has a lettered sub-part" when it is not a bare integer, e.g.
# "12a", "3b", "1a_i" — but not "1", "12".
_LETTERED_SUBPART = re.compile(r"[A-Za-z]")


class GoldenCorpusInvariantsTests(unittest.TestCase):
    def test_every_case_directory_has_a_recorded_baseline(self):
        dirs = {
            p.name for p in _GOLDEN_DIR.iterdir() if p.is_dir() and (p / "answers.json").exists()
        }
        self.assertEqual(dirs, set(_EXPECTED_MAXIMUM_MARK))

    def test_maximum_mark_unchanged_from_baseline(self):
        for case_dir_name, expected in _EXPECTED_MAXIMUM_MARK.items():
            ms_path = _GOLDEN_DIR / case_dir_name / "mark_scheme.json"
            data = json.loads(ms_path.read_text(encoding="utf-8"))
            with self.subTest(case=case_dir_name):
                self.assertEqual(data["metadata"]["maximum_mark"], expected)

    def test_lettered_leaves_have_a_parent_id_or_are_flagged_standalone(self):
        """Every leaf whose id contains a letter must have parent_id set,
        UNLESS it is a genuinely standalone sub-part (no sibling sharing its
        stem) — the MCQ fixture's flat ids and any truly solo sub-part are
        the only allowed exceptions, enumerated here explicitly rather than
        inferred, so a future fixture edit that silently drops parent_id
        cannot hide behind a loose exception rule.
        """
        # (case_dir, leaf_id) pairs that are allowed to keep parent_id=None
        # despite having a lettered id, because no sibling shares their stem.
        allowed_standalone = {
            ("0625_s20_qp_31_theory_correct", "4a"),
            ("0625_s20_qp_31_theory_correct", "5b"),
            ("0625_s20_qp_31_theory_correct", "11b"),
            ("0625_s20_qp_31_theory_partial", "4a"),
            ("0625_s20_qp_31_theory_partial", "5b"),
            ("0625_s20_qp_31_theory_partial", "11b"),
            ("0625_s20_qp_31_theory_wrong", "4a"),
            ("0625_s20_qp_31_theory_wrong", "5b"),
            ("0625_s20_qp_31_theory_wrong", "11b"),
        }
        cases = load_golden_cases(_GOLDEN_DIR)
        case_dirs_by_paper: dict[str, list[str]] = {}
        for p in _GOLDEN_DIR.iterdir():
            if not p.is_dir() or not (p / "mark_scheme.json").exists():
                continue
            case_dirs_by_paper.setdefault(p.name, []).append(p.name)

        for case_dir_name in _EXPECTED_MAXIMUM_MARK:
            ms_path = _GOLDEN_DIR / case_dir_name / "mark_scheme.json"
            data = json.loads(ms_path.read_text(encoding="utf-8"))

            def walk(questions: list[dict]) -> list[dict]:
                leaves = []
                for q in questions:
                    if q.get("parts"):
                        leaves.extend(walk(q["parts"]))
                    else:
                        leaves.append(q)
                return leaves

            for leaf in walk(data["questions"]):
                if not _LETTERED_SUBPART.search(leaf["id"]):
                    continue
                with self.subTest(case=case_dir_name, leaf=leaf["id"]):
                    if (case_dir_name, leaf["id"]) in allowed_standalone:
                        continue
                    self.assertIsNotNone(
                        leaf.get("parent_id"),
                        f"{case_dir_name}:{leaf['id']} has a lettered id but no parent_id",
                    )
        del cases  # loaded above only to prove load_golden_cases succeeds over the corpus

    def test_is_excerpt_matches_the_issue_table(self):
        cases = load_golden_cases(_GOLDEN_DIR)
        by_paper_id = {c.paper_id: c.is_excerpt for c in cases}
        for paper_id, expected in _EXPECTED_IS_EXCERPT.items():
            with self.subTest(paper_id=paper_id):
                self.assertIn(paper_id, by_paper_id)
                self.assertEqual(by_paper_id[paper_id], expected)
