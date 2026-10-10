"""``correct-paper --record`` never appends a paper the binding check did not pass."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from lemely.app.cli import cli
from lemely.core.binding import BindingCheck, BindingReport
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

_SCHEME = {
    "metadata": {
        "subject": "Physics",
        "subject_code": "0625",
        "paper_number": 1,
        "paper_variant": 2,
        "session_month": "May/June",
        "session_year": 2020,
        "paper_type": "mcq",
        "maximum_mark": 2,
        "scheme_format": "mcq",
    },
    "questions": [
        {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
        {"id": "2", "marks": 1, "type": "mcq", "mcq_answer": "B"},
    ],
}


def _answers(verdict: str) -> str:
    return ExtractedAnswers(
        paper_id="p",
        source_scan="s.pdf",
        answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.9)],
        unbound_question_ids=["2"],
        binding=BindingReport(
            binder="label",
            verdict=verdict,  # type: ignore[arg-type]
            checks=[BindingCheck(id="G1", passed=verdict == "pass", scope="paper", detail="d")],
        ),
    ).model_dump_json()


def _run(tmp_path: Path, verdict: str, *extra: str):  # type: ignore[no-untyped-def]
    ms = tmp_path / "ms.json"
    ms.write_text(json.dumps(_SCHEME), "utf-8")
    answers = tmp_path / "answers.json"
    answers.write_text(_answers(verdict), "utf-8")
    return CliRunner().invoke(
        cli,
        [
            "correct-paper",
            "--mark-scheme",
            str(ms),
            "--answers",
            str(answers),
            "--mcq-only",
            "--student-id",
            "maya",
            *extra,
        ],
        env={"LEMELY_PATHS__OUTPUT_DIR": str(tmp_path / "out")},
    )


@pytest.mark.parametrize("verdict", ["hold", "retry"])
def test_record_refuses_a_paper_whose_verdict_is_not_pass(tmp_path: Path, verdict: str) -> None:
    result = _run(tmp_path, verdict, "--record")

    assert result.exit_code != 0
    assert "not recorded" in result.output
    assert verdict in result.output
    assert not (tmp_path / "out" / "history").exists()


def test_without_record_a_held_paper_prints_as_before(tmp_path: Path) -> None:
    result = _run(tmp_path, "hold")

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "out").exists()


def test_record_appends_a_paper_that_passed(tmp_path: Path) -> None:
    result = _run(tmp_path, "pass", "--record")

    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "history").exists()
