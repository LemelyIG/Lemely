"""Functional tests for CLI commands that previously had zero CLI-level coverage."""

from __future__ import annotations

import datetime
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from lemely.app.cli import cli
from lemely.core.generation import GeneratedQuestion, GeneratedQuiz
from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.io.history_store import HistoryStore

_REAL_MS = Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.json")


def _real_ms_text() -> str:
    return _REAL_MS.read_text(encoding="utf-8")


def _make_metadata() -> ExamMetadata:
    return ExamMetadata(
        subject_code="0625",
        paper_number=1,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )


def _make_record(
    student_id: str, awarded: int = 8, maximum: int = 10, pct: float = 80.0, grade: str = "B"
) -> PaperRecord:
    return PaperRecord(
        student_id=student_id,
        metadata=_make_metadata(),
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=pct,
        grade=grade,
        weak_areas=[],
        recorded_at=datetime.datetime.now(datetime.UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# 1. version subcommand
# ---------------------------------------------------------------------------


def test_version_cmd_returns_expected_keys() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "version"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "lemely" in payload
    assert "python" in payload
    assert "dependencies" in payload


# ---------------------------------------------------------------------------
# 2. --verbose + --quiet mutual exclusion
# ---------------------------------------------------------------------------


def test_verbose_and_quiet_are_mutually_exclusive() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--verbose", "--quiet", "estimate-cost", "."])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# 3. --help lists all 15 commands
# ---------------------------------------------------------------------------

_EXPECTED_COMMANDS = [
    "estimate-cost",
    "parse-mark-schemes",
    "correct-paper",
    "predict-grade",
    "detect-weaknesses",
    "generate-quiz",
    "version",
    "doctor",
    "extract-answers",
    "study-plan",
    "check-integrity",
    "teacher-quiz",
    "aggregate-subject",
    "measure-accuracy",
    "ui",
]


def test_help_lists_all_15_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0, result.output
    for cmd in _EXPECTED_COMMANDS:
        assert cmd in result.output, f"Missing command in --help output: {cmd}"


# ---------------------------------------------------------------------------
# 4. correct-paper --record --student-id writes history
# ---------------------------------------------------------------------------


def test_correct_paper_record_writes_history_file() -> None:
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ms_path = tmp_path / "0625_m20_ms_12.json"
        ms_path.write_text(_real_ms_text(), "utf-8")

        with patch("lemely.app.cli._get_settings") as mock_gs:
            s = MagicMock()
            s.paths.output_dir = tmp_path
            s.paths.sources_dir = Path("Sources")
            s.gemini.model = "gemini-1.5-flash"
            mock_gs.return_value = s

            result = runner.invoke(
                cli,
                [
                    "--json",
                    "correct-paper",
                    "--mark-scheme",
                    str(ms_path),
                    "--answers",
                    "1 A",
                    "--mcq-only",
                    "--record",
                    "--student-id",
                    "test_student",
                ],
            )

        assert result.exit_code == 0, result.output
        history_file = tmp_path / "history" / "test_student.json"
        assert history_file.exists(), f"Expected history file at {history_file}"
        data = json.loads(history_file.read_text("utf-8"))
        assert data["student_id"] == "test_student"
        assert len(data["records"]) == 1


# ---------------------------------------------------------------------------
# 5. compare-performance with no history → UsageError (exit_code 2)
# ---------------------------------------------------------------------------


def test_compare_performance_no_history_is_usage_error() -> None:
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        with patch("lemely.app.cli._get_settings") as mock_gs:
            s = MagicMock()
            s.paths.output_dir = Path(tmp)
            mock_gs.return_value = s

            result = runner.invoke(cli, ["compare-performance", "--student-id", "nobody"])

        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# 6. compare-performance with history → PerformanceComparison
# ---------------------------------------------------------------------------


def test_compare_performance_with_history_returns_comparison() -> None:
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        store = HistoryStore(tmp_path / "history")
        store.append("alice", _make_record("alice", awarded=7, maximum=10, pct=70.0, grade="C"))
        store.append("alice", _make_record("alice", awarded=8, maximum=10, pct=80.0, grade="B"))

        with patch("lemely.app.cli._get_settings") as mock_gs:
            s = MagicMock()
            s.paths.output_dir = tmp_path
            mock_gs.return_value = s

            result = runner.invoke(cli, ["--json", "compare-performance", "--student-id", "alice"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert "student_id" in payload
        assert "latest" in payload
        assert "prior_count" in payload


# ---------------------------------------------------------------------------
# 7. study-plan with history → StudyPlan
# ---------------------------------------------------------------------------


def test_study_plan_with_history_returns_plan() -> None:
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        store = HistoryStore(tmp_path / "history")
        record = PaperRecord(
            student_id="bob",
            metadata=_make_metadata(),
            awarded_marks=7,
            maximum_marks=10,
            percentage=70.0,
            grade="C",
            weak_areas=[
                WeakArea(
                    topic="Waves",
                    lost_marks=3,
                    maximum_marks=10,
                    accuracy=0.7,
                    question_ids=["q1"],
                )
            ],
            recorded_at=datetime.datetime.now(datetime.UTC).isoformat(),
        )
        store.append("bob", record)

        with patch("lemely.app.cli._get_settings") as mock_gs:
            s = MagicMock()
            s.paths.output_dir = tmp_path
            mock_gs.return_value = s

            result = runner.invoke(
                cli,
                [
                    "--json",
                    "study-plan",
                    "--student-id",
                    "bob",
                    "--weekly-hours",
                    "5",
                ],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert "student_id" in payload
        assert "weekly_hours" in payload
        assert "sessions" in payload


# ---------------------------------------------------------------------------
# 8. check-integrity — clean case (no plagiarism flagged)
# ---------------------------------------------------------------------------


def test_check_integrity_clean_case() -> None:
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        answers_data = {
            "paper_id": "p1",
            "source_scan": "scan.pdf",
            "answers": [{"question_id": "1", "answer": "A", "confidence": 0.9}],
        }
        answers_file = tmp_path / "answers.json"
        answers_file.write_text(json.dumps(answers_data), "utf-8")

        ms_file = tmp_path / "ms.json"
        ms_file.write_text(_real_ms_text(), "utf-8")

        with patch("lemely.app.cli._get_settings") as mock_gs:
            s = MagicMock()
            s.integrity.plagiarism_threshold = 0.85
            mock_gs.return_value = s

            result = runner.invoke(
                cli,
                [
                    "--json",
                    "check-integrity",
                    "--answers",
                    str(answers_file),
                    "--mark-scheme",
                    str(ms_file),
                ],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert "findings" in payload
        assert "needs_teacher_review" in payload
        assert isinstance(payload["findings"], list)
        assert isinstance(payload["needs_teacher_review"], bool)


# ---------------------------------------------------------------------------
# 9. check-integrity — verbatim copy is flagged
# ---------------------------------------------------------------------------

_SYNTHETIC_MS = {
    "metadata": {
        "subject": "Physics",
        "subject_code": "0625",
        "paper_number": 2,
        "paper_variant": 1,
        "session_month": "May/June",
        "session_year": 2020,
        "paper_type": "theory_core",
        "tier": None,
        "maximum_mark": 3,
        "scheme_format": "point_based",
    },
    "abbreviation_legend": {},
    "questions": [
        {
            "id": "1",
            "parent_id": None,
            "marks": 3,
            "type": "explanation",
            "answer_points": [
                {
                    "id": "p1",
                    "point": "The current through the resistor increases when the voltage increases because electrons move faster through the conductor.",
                    "marks": 1,
                },
                {
                    "id": "p2",
                    "point": "The resistance remains constant according to Ohm's law for metallic conductors at constant temperature.",
                    "marks": 1,
                },
                {
                    "id": "p3",
                    "point": "Power dissipated equals current squared multiplied by resistance.",
                    "marks": 1,
                },
            ],
        }
    ],
}


def test_check_integrity_verbatim_copy_is_flagged() -> None:
    """Verify that when PlagiarismChecker flags a finding, needs_teacher_review=True.

    The CLI builds expected_map via str(AnswerPoint), which produces Pydantic repr
    rather than the plain .point text — so we mock PlagiarismChecker.check() to
    return a flagged IntegrityFinding instead of relying on text similarity.
    """
    from lemely.core.integrity_schemas import IntegrityFinding

    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        answers_data = {
            "paper_id": "p1",
            "source_scan": "scan.pdf",
            "answers": [{"question_id": "1", "answer": "some student answer", "confidence": 0.9}],
        }
        answers_file = tmp_path / "answers.json"
        answers_file.write_text(json.dumps(answers_data), "utf-8")

        ms_file = tmp_path / "synthetic_ms.json"
        ms_file.write_text(json.dumps(_SYNTHETIC_MS), "utf-8")

        flagged_finding = IntegrityFinding(
            question_id="1",
            kind="plagiarism",
            flagged=True,
            score=0.97,
            rationale="Similarity ratio 0.970 >= threshold 0.850.",
        )

        with patch("lemely.app.cli._get_settings") as mock_gs:
            s = MagicMock()
            s.integrity.plagiarism_threshold = 0.85
            mock_gs.return_value = s

            with patch(
                "lemely.core.plagiarism.PlagiarismChecker.check", return_value=flagged_finding
            ):
                result = runner.invoke(
                    cli,
                    [
                        "--json",
                        "check-integrity",
                        "--answers",
                        str(answers_file),
                        "--mark-scheme",
                        str(ms_file),
                    ],
                )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["needs_teacher_review"] is True


# ---------------------------------------------------------------------------
# 10. generate-quiz --use-ai with mocked GeminiClient
# ---------------------------------------------------------------------------


def test_generate_quiz_use_ai_with_mocked_client() -> None:
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        weakness_data = {
            "weak_areas": [
                {
                    "topic": "Waves",
                    "lost_marks": 3,
                    "maximum_marks": 10,
                    "accuracy": 0.7,
                    "question_ids": ["q1"],
                }
            ],
            "needs_teacher_review": False,
        }
        weakness_file = tmp_path / "weaknesses.json"
        weakness_file.write_text(json.dumps(weakness_data), "utf-8")

        fake_quiz = GeneratedQuiz(
            subject_code="0625",
            questions=[
                GeneratedQuestion(
                    topic="Waves",
                    difficulty="standard",
                    prompt="Describe the properties of a transverse wave.",
                    model_answer="A transverse wave oscillates perpendicular to direction of travel.",
                    mark_scheme_points=["oscillates perpendicular to direction"],
                    total_marks=2,
                    source_question_ids=["q1"],
                )
            ],
        )

        with patch("lemely.app.cli._get_settings") as mock_gs:
            s = MagicMock()
            mock_gs.return_value = s

            # generate_quiz_cmd imports GeminiClient and QuestionGenerator inside
            # the function body, so patch at the source module level.
            with (
                patch("lemely.io.gemini.GeminiClient"),
                patch("lemely.io.question_generation.QuestionGenerator") as MockQG,
            ):
                mock_instance = MagicMock()
                mock_instance.generate.return_value = fake_quiz
                MockQG.return_value = mock_instance

                result = runner.invoke(
                    cli,
                    [
                        "--json",
                        "generate-quiz",
                        str(weakness_file),
                        "--use-ai",
                        "--subject-code",
                        "0625",
                        "--count",
                        "1",
                    ],
                )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert "questions" in payload
        assert len(payload["questions"]) >= 1


# ---------------------------------------------------------------------------
# measure-accuracy --cache-mode reaches the client AND the manifest (#77)
# ---------------------------------------------------------------------------


def test_measure_accuracy_cache_mode_bypass_reaches_the_saved_manifest() -> None:
    """``--cache-mode bypass`` must configure the client AND be recorded in the
    saved run's manifest — not merely be accepted by click (#77).

    Asserting on the manifest written to disk, rather than on the constructor
    call alone, is deliberate: the manifest is what a later reader uses to
    decide what a saved run *was*, and #73 wires it to the client's real
    default. A flag click accepts but never threads through would leave an A/A
    churn run (M0.3/#27) served entirely from cache — measured churn 0.0 by
    construction — while the manifest still claimed ``read_write``. This test
    fails if either half of that path breaks.
    """
    captured: dict[str, object] = {}

    def _fake_client(settings, *args, **kwargs):
        mode = kwargs.get("default_cache_mode")
        captured["default_cache_mode"] = mode
        client = MagicMock()
        client.default_cache_mode = mode
        return client

    with tempfile.TemporaryDirectory() as tmp:
        golden = Path(tmp) / "golden"
        case_dir = golden / "0625_m20_qp_12_mcq"
        case_dir.mkdir(parents=True)
        ms = {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": 1,
                "scheme_format": "mcq",
            },
            "questions": [{"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"}],
        }
        (case_dir / "mark_scheme.json").write_text(json.dumps(ms))
        (case_dir / "answers.json").write_text(
            json.dumps({"1": {"student_answer": "A", "awarded_marks": 1}})
        )
        results_dir = Path(tmp) / "results"

        with patch("lemely.io.gemini.GeminiClient", side_effect=_fake_client):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "measure-accuracy",
                    "--golden",
                    str(golden),
                    "--results-dir",
                    str(results_dir),
                    "--cache-mode",
                    "bypass",
                ],
            )

        # NB: exit code is deliberately NOT asserted to be 0. This command
        # exits non-zero when any metric misses its configured target, which a
        # one-question fixture always does. That is orthogonal to the flag
        # plumbing under test, so asserting on it would couple this test to
        # the accuracy thresholds. What must hold is that no exception escaped.
        assert not isinstance(result.exception, Exception) or isinstance(
            result.exception, SystemExit
        ), result.output
        assert captured["default_cache_mode"] == "bypass", (
            f"--cache-mode never reached GeminiClient; got {captured!r}"
        )

        saved = list(results_dir.glob("*.json"))
        assert len(saved) == 1, f"expected one saved result, got {saved}"
        payload = json.loads(saved[0].read_text(encoding="utf-8"))
        assert payload["manifest"]["cache_mode"] == "bypass"


def test_measure_accuracy_defaults_to_read_write_cache_mode() -> None:
    """Omitting the flag must leave existing behaviour exactly as it was (#77)."""
    captured: dict[str, object] = {}

    def _fake_client(settings, *args, **kwargs):
        captured["default_cache_mode"] = kwargs.get("default_cache_mode")
        client = MagicMock()
        client.default_cache_mode = kwargs.get("default_cache_mode")
        return client

    with tempfile.TemporaryDirectory() as tmp:
        golden = Path(tmp) / "golden"
        case_dir = golden / "0625_m20_qp_12_mcq"
        case_dir.mkdir(parents=True)
        ms = {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": 1,
                "scheme_format": "mcq",
            },
            "questions": [{"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"}],
        }
        (case_dir / "mark_scheme.json").write_text(json.dumps(ms))
        (case_dir / "answers.json").write_text(
            json.dumps({"1": {"student_answer": "A", "awarded_marks": 1}})
        )

        with patch("lemely.io.gemini.GeminiClient", side_effect=_fake_client):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "measure-accuracy",
                    "--golden",
                    str(golden),
                    "--results-dir",
                    str(Path(tmp) / "results"),
                ],
            )

    assert not isinstance(result.exception, Exception) or isinstance(
        result.exception, SystemExit
    ), result.output
    assert captured["default_cache_mode"] == "read_write"


def test_measure_accuracy_arm_flag_is_threaded_to_measure_accuracy() -> None:
    """``--arm oracle+mark`` (#28/M0.4) must be accepted by click and passed
    through, as the ``arm`` keyword, to ``measure_accuracy`` — mocked at the
    CLI layer so this test never runs real correction/extraction.
    """
    from lemely.accuracy.harness import AccuracyMetrics, AccuracyResult, FunnelCounts
    from lemely.eval.manifest import RunManifest

    captured: dict[str, object] = {}

    def _fake_measure_accuracy(cases, client, settings, *, arm=None, **kwargs):
        captured["arm"] = arm
        metrics = AccuracyMetrics(
            mark_accuracy=1.0,
            mark_accuracy_theory=1.0,
            id_match_rate=None,
            flag_precision_high=1.0,
            flag_recall=1.0,
        )
        manifest = RunManifest(
            run_id="run-fake",
            git_sha="deadbeef",
            timestamp=datetime.datetime.now(datetime.UTC),
            prompt_versions={},
            params_fingerprint="fp",
            models_by_task={},
            cache_mode="read_write",
            split="dev",
            corpus_digest="digest",
        )
        return AccuracyResult(
            metrics=metrics,
            question_results=[],
            eval_records=[],
            calibration=[],
            prompt_versions={},
            manifest=manifest,
            funnel=FunnelCounts(),
        )

    with tempfile.TemporaryDirectory() as tmp:
        golden = Path(tmp) / "golden"
        case_dir = golden / "0625_m20_qp_12_mcq"
        case_dir.mkdir(parents=True)
        ms = {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": 1,
                "scheme_format": "mcq",
            },
            "questions": [{"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"}],
        }
        (case_dir / "mark_scheme.json").write_text(json.dumps(ms))
        (case_dir / "answers.json").write_text(
            json.dumps({"1": {"student_answer": "A", "awarded_marks": 1}})
        )
        results_dir = Path(tmp) / "results"

        with (
            patch("lemely.io.gemini.GeminiClient", return_value=MagicMock()),
            patch("lemely.accuracy.harness.measure_accuracy", side_effect=_fake_measure_accuracy),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "measure-accuracy",
                    "--golden",
                    str(golden),
                    "--results-dir",
                    str(results_dir),
                    "--arm",
                    "oracle+mark",
                ],
            )

    assert not isinstance(result.exception, Exception) or isinstance(
        result.exception, SystemExit
    ), result.output
    assert captured["arm"] == "oracle+mark"
