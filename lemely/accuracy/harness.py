"""Golden-dataset accuracy measurement harness for the Lemely pipeline."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from lemely.core.loose_schemas import MarkScheme


class GoldenAnswer(BaseModel):
    """Ground truth for a single leaf question."""

    student_answer: str
    awarded_marks: int
    notes: str | None = None


@dataclass
class GoldenCase:
    """One paper-worth of ground truth data."""

    paper_id: str
    mark_scheme: MarkScheme
    ground_truth: dict[str, GoldenAnswer]   # question_id -> GoldenAnswer
    scan_path: Path | None = None           # present only when extraction test is possible


def load_golden_cases(golden_dir: Path) -> list[GoldenCase]:
    """Load all golden cases from direct subdirectories of *golden_dir*.

    Each subdirectory must contain:
      mark_scheme.json  — already-parsed JSON mark scheme
      answers.json      — ground truth per leaf question
      scan.pdf          — optional; enables extraction tests
    """
    cases: list[GoldenCase] = []
    for case_dir in sorted(golden_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        ms_path = case_dir / "mark_scheme.json"
        ans_path = case_dir / "answers.json"
        if not ms_path.exists() or not ans_path.exists():
            continue

        mark_scheme = MarkScheme.model_validate_json(ms_path.read_text(encoding="utf-8"))
        raw: dict[str, object] = json.loads(ans_path.read_text(encoding="utf-8"))
        ground_truth = {
            qid: GoldenAnswer.model_validate(v)
            for qid, v in raw.items()
        }
        scan_path = case_dir / "scan.pdf"
        cases.append(GoldenCase(
            paper_id=case_dir.name,
            mark_scheme=mark_scheme,
            ground_truth=ground_truth,
            scan_path=scan_path if scan_path.exists() else None,
        ))
    return cases
