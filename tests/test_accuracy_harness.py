"""Unit tests for the golden-dataset accuracy measurement harness."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class LoadGoldenCasesTests(unittest.TestCase):
    def _make_case_dir(self, root: Path, name: str = "0625_m20_qp_12") -> Path:
        case_dir = root / name
        case_dir.mkdir()
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
            "questions": [
                {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
            ],
        }
        (case_dir / "mark_scheme.json").write_text(json.dumps(ms))
        answers = {"1": {"student_answer": "A", "awarded_marks": 1}}
        (case_dir / "answers.json").write_text(json.dumps(answers))
        return case_dir

    def test_loads_single_case(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].paper_id, "0625_m20_qp_12")

    def test_ground_truth_parsed(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        gt = cases[0].ground_truth
        self.assertIn("1", gt)
        self.assertEqual(gt["1"].student_answer, "A")
        self.assertEqual(gt["1"].awarded_marks, 1)

    def test_scan_path_none_when_no_pdf(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        self.assertIsNone(cases[0].scan_path)

    def test_scan_path_set_when_pdf_present(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "scan.pdf").write_bytes(b"%PDF-1.4")
            cases = load_golden_cases(Path(tmp))
        self.assertIsNotNone(cases[0].scan_path)

    # -- #137: more than one render of the SAME paper -----------------

    def test_extra_renders_do_not_add_cases(self):
        """The property the whole design rests on.

        Every interval and power figure in this programme is computed on
        distinct leaves keyed ``(paper_id, question_id)`` (DA6). A render that
        produced its own case would inflate ``n`` with a duplicate of a leaf
        that already exists — the trap #134 declined for the whitespace
        fixture. One directory, one case, however many renders.
        """
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "scan.pdf").write_bytes(b"%PDF-1.4")
            (case_dir / "scan.handwritten.pdf").write_bytes(b"%PDF-1.4")
            (case_dir / "scan.rescanned.pdf").write_bytes(b"%PDF-1.4")
            cases = load_golden_cases(Path(tmp))

        self.assertEqual(len(cases), 1, "three renders, still one case")
        self.assertEqual(len(cases[0].ground_truth), 1, "and still one leaf")

    def test_renders_are_discovered_and_named(self):
        from lemely.accuracy.harness import DEFAULT_RENDER, load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "scan.pdf").write_bytes(b"%PDF-1.4")
            (case_dir / "scan.handwritten.pdf").write_bytes(b"%PDF-1.4")
            cases = load_golden_cases(Path(tmp))

        case = cases[0]
        self.assertEqual(case.render_names, [DEFAULT_RENDER, "handwritten"])
        self.assertEqual(case.render("handwritten"), case_dir / "scan.handwritten.pdf")
        self.assertEqual(case.render(), case.scan_path)

    def test_scan_path_and_default_render_never_disagree(self):
        """Two names for one path must not become two sources of truth."""
        from lemely.accuracy.harness import DEFAULT_RENDER, load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "scan.pdf").write_bytes(b"%PDF-1.4")
            cases = load_golden_cases(Path(tmp))

        self.assertEqual(cases[0].renders[DEFAULT_RENDER], cases[0].scan_path)

    def test_a_case_with_no_scan_has_no_renders(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))

        self.assertIsNone(cases[0].scan_path)
        self.assertEqual(cases[0].renders, {})
        self.assertEqual(cases[0].render_names, [])
        self.assertIsNone(cases[0].render("handwritten"))

    def test_an_alternate_render_without_a_default_is_still_found(self):
        """A fixture may have only the non-default render.

        ``scan_path`` stays ``None`` — nothing pretends the default exists —
        but the render is discoverable, so #59 can pair renders across a
        corpus where not every case carries both.
        """
        from lemely.accuracy.harness import DEFAULT_RENDER, load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "scan.handwritten.pdf").write_bytes(b"%PDF-1.4")
            cases = load_golden_cases(Path(tmp))

        self.assertIsNone(cases[0].scan_path)
        self.assertNotIn(DEFAULT_RENDER, cases[0].renders)
        self.assertEqual(cases[0].render_names, ["handwritten"])

    def test_renders_are_orthogonal_to_fixture_variant(self):
        """Same paper + different ANSWERS is a variant; + different IMAGE is a render.

        Conflating them is how a render would end up inflating the leaf count,
        so this asserts both axes hold at once: two variant directories, one of
        them carrying an extra render, give two cases sharing one ``paper_id``.
        """
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            correct = self._make_case_dir(root, name="0625_x_theory_correct")
            wrong = self._make_case_dir(root, name="0625_x_theory_wrong")
            (correct / "scan.pdf").write_bytes(b"%PDF-1.4")
            (correct / "scan.handwritten.pdf").write_bytes(b"%PDF-1.4")
            (wrong / "scan.pdf").write_bytes(b"%PDF-1.4")
            cases = load_golden_cases(root)

        self.assertEqual(len(cases), 2, "variants are cases; renders are not")
        self.assertEqual({c.paper_id for c in cases}, {"0625_x_theory"})
        by_variant = {c.fixture_variant: c for c in cases}
        self.assertEqual(by_variant["correct"].render_names, ["default", "handwritten"])
        self.assertEqual(by_variant["wrong"].render_names, ["default"])

    def test_skips_dir_without_required_files(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "incomplete").mkdir()
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 0)

    def test_notes_field_optional(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            answers = {"1": {"student_answer": "A", "awarded_marks": 1, "notes": "owtte"}}
            (case_dir / "answers.json").write_text(json.dumps(answers))
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(cases[0].ground_truth["1"].notes, "owtte")

    def test_multiple_cases_sorted_order(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp), name="zzz_paper")
            self._make_case_dir(Path(tmp), name="aaa_paper")
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].paper_id, "aaa_paper")
        self.assertEqual(cases[1].paper_id, "zzz_paper")

    def test_fixture_variant_parsed_from_dir_suffix(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp), name="0625_s20_qp_31_theory_correct")
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(cases[0].paper_id, "0625_s20_qp_31_theory")
        self.assertEqual(cases[0].fixture_variant, "correct")

    def test_fixture_variant_none_when_dir_has_no_variant_suffix(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp), name="0625_m20_qp_12_mcq")
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(cases[0].paper_id, "0625_m20_qp_12_mcq")
        self.assertIsNone(cases[0].fixture_variant)

    def test_skips_malformed_answers_json(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "answers.json").write_text("{ not valid json }")
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 0)

    def test_is_excerpt_defaults_false_when_marker_absent(self):
        """M0.8 (#32): a fixture with no case.json sidecar is not an excerpt."""
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        self.assertFalse(cases[0].is_excerpt)

    def test_is_excerpt_true_when_case_json_marker_present(self):
        """M0.8 (#32): case.json is a sidecar, never routed through MarkScheme
        validation, so it cannot silently be dropped as an unknown pydantic key."""
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "case.json").write_text(json.dumps({"is_excerpt": True}))
            cases = load_golden_cases(Path(tmp))
        self.assertTrue(cases[0].is_excerpt)

    def test_is_excerpt_string_false_does_not_coerce_to_true(self):
        """#32/#69: ``bool("false")`` is ``True`` in Python, so a JSON string
        value for ``is_excerpt`` must not be coerced with ``bool()`` -- that
        would silently flip a falsy-looking string into a truthy flag.

        US-037 (second instance): a non-bool marker value used to fall into
        a fail-open handler that logged and kept the case with
        ``is_excerpt`` defaulted to ``False`` -- silently promoting what may
        actually be an EXCERPT case into a FULL-PAPER case, since the marker
        that would have said otherwise couldn't be read. That is worse than
        dropping the case, so it is now rejected outright: not returned by
        ``load_golden_cases`` at all, and counted in ``.unparseable`` instead
        of silently defaulting.
        """
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "case.json").write_text(json.dumps({"is_excerpt": "false"}))
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 0, "a case whose is_excerpt could not be verified is rejected")
        self.assertEqual(cases.unparseable, [case_dir])

    # -- US-037: unparseable cases must shrink the denominator LOUDLY -----

    def test_unparseable_mark_scheme_is_reported_not_silently_dropped(self):
        """A corpus with one unparseable ``mark_scheme.json`` among N good
        ones must not silently yield N-1 cases with no observable trace:
        the dropped directory must be named in ``.unparseable``."""
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_case_dir(root, name="good_paper")
            bad_dir = self._make_case_dir(root, name="bad_paper")
            (bad_dir / "mark_scheme.json").write_text("{ not valid json }")
            cases = load_golden_cases(root)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].paper_id, "good_paper")
        self.assertEqual(cases.unparseable, [bad_dir])

    def test_unparseable_answers_json_is_reported(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "answers.json").write_text("{ not valid json }")
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 0)
        self.assertEqual(cases.unparseable, [case_dir])

    def test_legitimate_non_case_dir_is_not_counted_as_unparseable(self):
        """The false-positive direction: a directory that is legitimately
        not a case (missing mark_scheme.json/answers.json) is a normal skip,
        not a parse failure -- it must not inflate ``.unparseable``. This is
        the distinction ``golden_case_load_error`` already draws by only
        firing once parsing is actually attempted (PRD framing withdrawn:
        the swallow itself was never silent, only unconsumed)."""
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "not_a_case").mkdir()
            (root / "also_not_a_case.txt").write_text("stray file")
            self._make_case_dir(root, name="good_paper")
            cases = load_golden_cases(root)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases.unparseable, [])

    def test_clean_corpus_reports_zero_unparseable(self):
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_case_dir(root, name="paper_a")
            self._make_case_dir(root, name="paper_b")
            cases = load_golden_cases(root)

        self.assertEqual(len(cases), 2)
        self.assertEqual(cases.unparseable, [])

    def test_load_result_is_still_a_plain_list_for_existing_callers(self):
        """The return type must stay additive: every existing call site
        (``len(cases)``, ``for case in cases``, ``cases[0]``, list
        comprehensions) keeps working unmodified. Only a caller that wants
        the new signal reads ``.unparseable``."""
        from lemely.accuracy.harness import load_golden_cases

        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))

        self.assertIsInstance(cases, list)
        self.assertEqual([c.paper_id for c in cases], ["0625_m20_qp_12"])


class MetricComputationTests(unittest.TestCase):
    def _qr(
        self,
        predicted: int,
        truth: int,
        confidence: float,
        review: bool,
        is_mcq: bool = False,
        scored: bool = True,
    ) -> object:
        from lemely.accuracy.harness import QuestionResult

        return QuestionResult(
            question_id="q",
            question_type="mcq" if is_mcq else "theory",
            predicted_marks=predicted,
            truth_marks=truth,
            confidence_score=confidence,
            needs_teacher_review=review,
            scored=scored,
        )

    def test_all_correct_accuracy_is_1(self):
        from lemely.accuracy.harness import _compute_metrics

        results = [self._qr(2, 2, 0.95, False), self._qr(1, 1, 0.92, False)]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.mark_accuracy, 1.0)

    def test_half_correct_accuracy(self):
        from lemely.accuracy.harness import _compute_metrics

        results = [self._qr(2, 2, 0.95, False), self._qr(0, 2, 0.72, True)]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.mark_accuracy, 0.5)

    def test_theory_only_excludes_mcq(self):
        from lemely.accuracy.harness import _compute_metrics

        results = [
            self._qr(1, 1, 1.0, False, is_mcq=True),  # MCQ correct
            self._qr(0, 2, 0.72, True, is_mcq=False),  # theory wrong
        ]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.mark_accuracy_theory, 0.0)

    def test_flag_precision_high(self):
        from lemely.accuracy.harness import _compute_metrics

        results = [
            self._qr(2, 2, 0.95, False),  # confident + correct
            self._qr(0, 2, 0.91, False),  # confident + wrong
        ]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.flag_precision_high, 0.5)

    def test_flag_recall(self):
        from lemely.accuracy.harness import _compute_metrics

        results = [
            self._qr(0, 2, 0.55, True),  # wrong + flagged
            self._qr(0, 2, 0.91, False),  # wrong + not flagged
        ]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.flag_recall, 0.5)

    def test_no_wrong_flag_recall_is_one(self):
        from lemely.accuracy.harness import _compute_metrics

        results = [self._qr(2, 2, 0.97, False)]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.flag_recall, 1.0)

    def test_calibration_bucket_assignment(self):
        from lemely.accuracy.harness import _build_calibration

        results = [
            self._qr(1, 1, 0.95, False),  # 0.90–1.00 bucket, correct
            self._qr(0, 1, 0.85, True),  # 0.80–0.90 bucket, wrong
        ]
        buckets = _build_calibration(results)
        top = buckets[0]  # 0.90–1.00
        second = buckets[1]  # 0.80–0.90
        self.assertEqual(top.predictions, 1)
        self.assertEqual(top.correct, 1)
        self.assertEqual(second.predictions, 1)
        self.assertEqual(second.correct, 0)

    def test_mcq_results_enter_the_calibration_curve(self) -> None:
        """MCQ QuestionResults must appear in a non-empty calibration bucket (D19, #36/M1.1).

        Before this change, ``_build_calibration`` filtered to
        ``question_type == "theory"`` only, silently dropping every MCQ
        result from the curve.
        """
        from lemely.accuracy.harness import _build_calibration

        results = [self._qr(1, 1, 0.95, False, is_mcq=True)]
        buckets = _build_calibration(results)
        total_predictions = sum(b.predictions for b in buckets)
        self.assertEqual(total_predictions, 1)

    def test_unscored_result_excluded_from_calibration(self) -> None:
        """Finding H (US-039 consumer fixes, lane 3): a genuinely-blank answer
        earns ``predicted_marks=0`` against a ``truth_marks=0`` ground truth,
        so ``is_correct`` is True at ``confidence_score=0.0`` -- a correct
        prediction the calibration curve would read as "confidently right
        when it claims to be unsure", even though no marker ever formed an
        opinion. ``scored=False`` marks that row as having no marking
        evidence, and ``_build_calibration`` must drop it from the
        population entirely (not just from the numerator).
        """
        from lemely.accuracy.harness import _build_calibration

        results = [self._qr(0, 0, 0.0, False, scored=False)]
        buckets = _build_calibration(results)
        total_predictions = sum(b.predictions for b in buckets)
        self.assertEqual(total_predictions, 0)

    def test_unscored_result_still_counts_for_mark_accuracy(self) -> None:
        """The same blank row must NOT disappear from ``mark_accuracy`` --
        a blank scored 0 against a truth of 0 is a genuinely correct
        prediction for that metric. Only the calibration population is
        wrong (Finding H); ``scored`` must not touch ``_compute_metrics``.
        """
        from lemely.accuracy.harness import _compute_metrics

        results = [self._qr(0, 0, 0.0, False, scored=False)]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.mark_accuracy, 1.0)

    def test_unscored_blank_inflates_flag_precision_high(self) -> None:
        """Whole-branch review Minor D: unlike ``_build_calibration``,
        ``_compute_metrics`` does not check ``r.scored`` before folding a row
        into ``flag_precision_high``/``flag_recall``. A genuine blank
        (``scored=False``, ``predicted_marks=truth_marks=0``,
        ``needs_teacher_review=False``) is confident-and-correct by
        construction -- US-039's short-circuit never asks a marker, so it
        never flags -- so it is a free correct-unflagged row that inflates
        ``flag_precision_high``. This pins the CURRENT (accepted, now
        disclosed -- see ``_compute_metrics``'s docstring) behaviour: it
        must keep failing if someone later filters ``scored`` here without
        updating the disclosure alongside it.
        """
        from lemely.accuracy.harness import _compute_metrics

        genuine_blank = self._qr(0, 0, 0.0, False, scored=False)  # confident + "correct"
        confident_and_wrong = self._qr(0, 2, 0.91, False)
        m = _compute_metrics([genuine_blank, confident_and_wrong])
        # If the blank were excluded (the calibration treatment), precision
        # would be 0/1 = 0.0; because it is not, the blank's free "correct"
        # drags a 0-for-1 confident set up to 1-for-2.
        self.assertAlmostEqual(m.flag_precision_high, 0.5)

    def test_unscored_blank_flag_metrics_disclosed_as_population_change(self) -> None:
        """The docstring must name the same population change for
        ``flag_precision_high``/``flag_recall`` that
        ``_build_calibration``'s docstring names for calibration -- both are
        downstream of US-039's blank short-circuit, and only the
        calibration one was disclosed when that fix landed (877869c9).
        """
        import inspect

        from lemely.accuracy.harness import _compute_metrics, _metrics_from_eval_records

        for fn in (_compute_metrics, _metrics_from_eval_records):
            doc = inspect.getdoc(fn) or ""
            self.assertIn("US-039", doc, f"{fn.__name__} does not name US-039")
            self.assertIn(
                "not comparable",
                doc,
                f"{fn.__name__} does not disclose the pre/post baseline break",
            )


class MeasureAccuracyTests(unittest.TestCase):
    """Tests for measure_accuracy()'s scan_path-gated extraction path.

    Mark schemes here are MCQ-only so `correct_paper` never needs a real (or
    mocked) Gemini client — the only Gemini-touching seam under test is
    `extract_answers`, which is mocked at its definition site
    (`lemely.web.services.grading.extract_answers`) since `measure_accuracy`
    lazily imports it by name on each call.
    """

    def _mark_scheme(self, question_ids: list[str]) -> object:
        from lemely.core.loose_schemas import MarkScheme

        ms = {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": len(question_ids),
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": qid, "marks": 1, "type": "mcq", "mcq_answer": "A"} for qid in question_ids
            ],
        }
        return MarkScheme.model_validate(ms)

    def test_no_scan_path_keeps_bypass_behaviour(self):
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy

        case = GoldenCase(
            paper_id="p1",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=None,
        )

        with patch("lemely.web.services.grading.extract_answers") as mock_extract:
            result = measure_accuracy([case], gemini_client=None, settings=None)

        mock_extract.assert_not_called()
        self.assertIsNone(result.metrics.id_match_rate)
        self.assertEqual(len(result.question_results), 1)
        self.assertTrue(result.question_results[0].is_correct)

    def test_arm_override_forces_oracle_mark_even_with_scan_path(self):
        """#28/M0.4: passing arm="oracle+mark" explicitly must bypass
        extraction and use ground-truth text even when the case carries a
        scan_path — the arm parameter, not scan_path presence, decides.
        """
        from lemely.accuracy.harness import (
            DEFAULT_RENDER,
            GoldenAnswer,
            GoldenCase,
            measure_accuracy,
        )

        scan_path = Path("/nonexistent/scan.pdf")
        case = GoldenCase(
            paper_id="p-oracle-override",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=scan_path,
            renders={DEFAULT_RENDER: scan_path},
        )

        with patch("lemely.web.services.grading.extract_answers") as mock_extract:
            result = measure_accuracy([case], gemini_client=None, settings=None, arm="oracle+mark")

        mock_extract.assert_not_called()
        self.assertEqual(len(result.eval_records), 1)
        self.assertEqual(result.eval_records[0].arm, "oracle+mark")

    def test_arm_override_extract_mark_without_scan_path_raises(self):
        """#28/M0.4: forcing arm="extract+mark" on a case with no scan_path
        must fail fast, before any Gemini spend, rather than silently
        falling back to the oracle bypass.
        """
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy

        case = GoldenCase(
            paper_id="p-no-scan",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=None,
        )

        with self.assertRaises(ValueError) as ctx:
            measure_accuracy([case], gemini_client=None, settings=None, arm="extract+mark")

        self.assertIn("p-no-scan", str(ctx.exception))

    def test_both_arms_over_same_cases_produce_ablation_2x2_nonzero(self):
        """#28/M0.4: running both arms over the same case and feeding the
        concatenated records into ablation_2x2() must yield a non-degenerate
        (not-all-zero) cross-tabulation.
        """
        from lemely.accuracy.harness import (
            DEFAULT_RENDER,
            GoldenAnswer,
            GoldenCase,
            measure_accuracy,
        )
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.eval.analyses import ablation_2x2

        scan_path = Path("/nonexistent/scan.pdf")
        case = GoldenCase(
            paper_id="p-ablation",
            mark_scheme=self._mark_scheme(["1", "2"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "2": GoldenAnswer(student_answer="A", awarded_marks=1),
            },
            scan_path=scan_path,
            renders={DEFAULT_RENDER: scan_path},
        )

        oracle_result = measure_accuracy(
            [case], gemini_client=None, settings=None, arm="oracle+mark"
        )

        # Extraction gets "1" right and "2" wrong.
        fake_extracted = ExtractedAnswers(
            paper_id="p-ablation",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),
                ExtractedAnswer(question_id="2", answer="B", confidence=0.9),
            ],
        )
        with patch("lemely.web.services.grading.extract_answers", return_value=fake_extracted):
            extract_result = measure_accuracy(
                [case], gemini_client=None, settings=None, arm="extract+mark"
            )

        combined = oracle_result.eval_records + extract_result.eval_records
        table = ablation_2x2(combined)

        total = sum(table.values())
        self.assertEqual(total, 2)
        self.assertGreater(total, 0)
        self.assertFalse(all(v == 0 for v in table.values()))

    def test_scan_path_case_uses_extracted_answers_not_ground_truth(self):
        from lemely.accuracy.harness import (
            DEFAULT_RENDER,
            GoldenAnswer,
            GoldenCase,
            measure_accuracy,
        )
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        # Ground truth text is deliberately NOT a valid MCQ letter — if the
        # harness fed this into correct_paper instead of the extracted text,
        # both questions would be marked wrong.
        scan_path = Path("/nonexistent/scan.pdf")
        case = GoldenCase(
            paper_id="p2",
            mark_scheme=self._mark_scheme(["1", "2"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="ignored", awarded_marks=1),
                "2": GoldenAnswer(student_answer="ignored", awarded_marks=1),
            },
            scan_path=scan_path,
            renders={DEFAULT_RENDER: scan_path},
        )
        fake_extracted = ExtractedAnswers(
            paper_id="p2",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),
                ExtractedAnswer(question_id="2", answer="A", confidence=0.9),
            ],
        )

        with patch(
            "lemely.web.services.grading.extract_answers", return_value=fake_extracted
        ) as mock_extract:
            result = measure_accuracy([case], gemini_client=None, settings=None)

        mock_extract.assert_called_once()
        self.assertEqual(result.metrics.id_match_rate, 1.0)
        self.assertEqual(len(result.question_results), 2)
        self.assertTrue(all(r.is_correct for r in result.question_results))

    def test_scan_path_case_missing_id_reflected_in_id_match_rate(self):
        from lemely.accuracy.harness import (
            DEFAULT_RENDER,
            GoldenAnswer,
            GoldenCase,
            measure_accuracy,
        )
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        scan_path = Path("/nonexistent/scan2.pdf")
        case = GoldenCase(
            paper_id="p3",
            mark_scheme=self._mark_scheme(["1", "2", "3"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "2": GoldenAnswer(student_answer="A", awarded_marks=1),
                "3": GoldenAnswer(student_answer="A", awarded_marks=1),
            },
            scan_path=scan_path,
            renders={DEFAULT_RENDER: scan_path},
        )
        # Extraction misses question "3" entirely.
        fake_extracted = ExtractedAnswers(
            paper_id="p3",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),
                ExtractedAnswer(question_id="2", answer="A", confidence=0.9),
            ],
        )

        with patch("lemely.web.services.grading.extract_answers", return_value=fake_extracted):
            result = measure_accuracy([case], gemini_client=None, settings=None)

        self.assertAlmostEqual(result.metrics.id_match_rate, 2 / 3)
        # No QuestionResult for "3" — QuestionResult stays matched-rows-only.
        self.assertEqual(len(result.question_results), 2)
        self.assertNotIn("3", {r.question_id for r in result.question_results})
        # But it is NOT silently dropped (D18): an EvalRecord for "3" exists,
        # recorded honestly as unmatched rather than vanishing from the
        # denominator.
        records_by_qid = {r.question_id: r for r in result.eval_records}
        self.assertIn("3", records_by_qid)
        self.assertEqual(records_by_qid["3"].outcome, "unmatched")
        self.assertEqual(records_by_qid["3"].id_match, "unmatched")
        self.assertIsNone(records_by_qid["3"].predicted_marks)

    def test_fewer_extracted_questions_cannot_score_higher(self):
        """D18 regression (#29): a run whose extractor returns FEWER answers
        must never score HIGHER than a run whose extractor returned more —
        answers it never returns cannot be silently dropped from the
        denominator, only the previously reachable id_match_rate.

        Run A gets all three ids back, one of them (``"2"``) wrong. Run B
        gets a strict subset — only ``"1"``, identical to run A's ``"1"`` and
        correct. Under the pre-fix `harness.py:596` ``continue``, run B's
        denominator shrinks to just the one id it got right, scoring 1.0 —
        strictly higher than run A's 2/3, even though B did no better work.
        """
        from lemely.accuracy.harness import (
            DEFAULT_RENDER,
            GoldenAnswer,
            GoldenCase,
            measure_accuracy,
        )
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        def make_case() -> GoldenCase:
            scan_path = Path("/nonexistent/scanD18.pdf")
            return GoldenCase(
                paper_id="pD18",
                mark_scheme=self._mark_scheme(["1", "2", "3"]),
                ground_truth={
                    "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                    "2": GoldenAnswer(student_answer="A", awarded_marks=1),
                    "3": GoldenAnswer(student_answer="A", awarded_marks=1),
                },
                scan_path=scan_path,
                renders={DEFAULT_RENDER: scan_path},
            )

        extracted_full = ExtractedAnswers(
            paper_id="pD18",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),  # correct
                ExtractedAnswer(question_id="2", answer="B", confidence=0.9),  # wrong
                ExtractedAnswer(question_id="3", answer="A", confidence=0.9),  # correct
            ],
        )
        extracted_subset = ExtractedAnswers(
            paper_id="pD18",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),  # correct
            ],
        )

        with patch("lemely.web.services.grading.extract_answers", return_value=extracted_full):
            result_a = measure_accuracy([make_case()], gemini_client=None, settings=None)
        with patch("lemely.web.services.grading.extract_answers", return_value=extracted_subset):
            result_b = measure_accuracy([make_case()], gemini_client=None, settings=None)

        self.assertLessEqual(result_b.metrics.mark_accuracy, result_a.metrics.mark_accuracy)

    def test_unmatched_question_id_stays_in_denominator(self):
        """A leaf the extractor never returned an answer for must produce an
        EvalRecord (outcome='unmatched', id_match='unmatched',
        predicted_marks=None) and must stay in the mark_accuracy denominator
        — never silently dropped (D18, spec §3.3 outcome table)."""
        from lemely.accuracy.harness import (
            DEFAULT_RENDER,
            GoldenAnswer,
            GoldenCase,
            measure_accuracy,
        )
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        scan_path = Path("/nonexistent/scanUnmatched.pdf")
        case = GoldenCase(
            paper_id="pUnmatched",
            mark_scheme=self._mark_scheme(["1", "2", "3"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "2": GoldenAnswer(student_answer="A", awarded_marks=1),
                "3": GoldenAnswer(student_answer="A", awarded_marks=1),
            },
            scan_path=scan_path,
            renders={DEFAULT_RENDER: scan_path},
        )
        fake_extracted = ExtractedAnswers(
            paper_id="pUnmatched",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),
                ExtractedAnswer(question_id="2", answer="A", confidence=0.9),
                # "3" never returned by extraction.
            ],
        )

        with patch("lemely.web.services.grading.extract_answers", return_value=fake_extracted):
            result = measure_accuracy([case], gemini_client=None, settings=None)

        records_by_qid = {r.question_id: r for r in result.eval_records}
        self.assertIn("3", records_by_qid)
        rec3 = records_by_qid["3"]
        self.assertEqual(rec3.outcome, "unmatched")
        self.assertEqual(rec3.id_match, "unmatched")
        self.assertIsNone(rec3.predicted_marks)

        # Denominator includes all three leaves; "3" counts as not-correct.
        self.assertEqual(len(result.eval_records), 3)
        self.assertAlmostEqual(result.metrics.mark_accuracy, 2 / 3)

    def test_never_attempted_leaf_is_excluded_not_unmatched(self):
        """A ground-truth leaf with no corresponding correct_paper output at
        all (not a marked leaf in the mark scheme) is recorded
        outcome='excluded' and is absent from the scored denominator —
        distinct from 'unmatched', which is an attempted-but-not-returned
        leaf (spec §3.3 outcome table)."""
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, measure_accuracy
        from lemely.eval.analyses import exclusion_funnel

        case = GoldenCase(
            paper_id="pExcluded",
            mark_scheme=self._mark_scheme(["1"]),  # mark scheme has only leaf "1"
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "99": GoldenAnswer(student_answer="A", awarded_marks=1),  # not a scheme leaf
            },
            scan_path=None,
        )

        result = measure_accuracy([case], gemini_client=None, settings=None)

        records_by_qid = {r.question_id: r for r in result.eval_records}
        self.assertIn("99", records_by_qid)
        self.assertEqual(records_by_qid["99"].outcome, "excluded")
        self.assertNotEqual(records_by_qid["1"].outcome, "excluded")

        funnel = exclusion_funnel(result.eval_records)
        self.assertEqual(funnel["excluded"], 1)
        self.assertEqual(funnel["scored"], 1)

        # D18/Blocker 1: the excluded leaf "99" must not enter the
        # mark_accuracy denominator or be scored as wrong. Only the one
        # attempted+correct leaf "1" is scored, so mark_accuracy is 1.0 —
        # not 0.5, which is what you get if the excluded row is counted as
        # a wrong answer alongside the correct one.
        self.assertEqual(result.metrics.mark_accuracy, 1.0)

        # The excluded row must also not collapse flag_recall: flag_recall
        # is computed over `wrong` records, and if "99" (excluded, treated
        # as id_match="unmatched", not flagged for review) were counted as
        # wrong, flag_recall would be 0/1 = 0.0 instead of the excluded-free
        # baseline of 1.0 (no wrong records at all -> vacuous 1.0).
        self.assertEqual(result.metrics.flag_recall, 1.0)

    def test_printed_funnel_chain_never_rises(self):
        """The printed exclusion funnel must be monotonically non-increasing.

        A funnel that rises mid-chain reads as a denominator *growing*, which
        is the opposite of what an exclusion funnel documents and exactly the
        confusion M0.5 exists to remove. `extracted` is deliberately NOT a
        stage of the chain: it counts leaves the extractor returned an id
        for, while `matched` counts leaves `correct_paper` produced a
        CorrectedQuestion for — neither implies the other, so putting them in
        sequence could print `extracted=2 -> matched=3`.
        """
        import itertools
        import re

        from lemely.accuracy.harness import (
            GoldenAnswer,
            GoldenCase,
            format_report,
            measure_accuracy,
        )

        # Leaf "99" is a ground-truth leaf with no corresponding mark-scheme
        # leaf, so `correct_paper` produces no CorrectedQuestion for it and it
        # is recorded `excluded`. This fixture yields
        # FunnelCounts(leaves=3, extracted=3, matched=2, marked=2) — note
        # extracted > matched here, because `scan_path=None` is oracle mode and
        # harness.py sets `extracted_ids = set(case.ground_truth)`.
        #
        # So this fixture does NOT reproduce the extracted < matched case that
        # motivated removing `extracted` from the chain; that needs a
        # scan_path-backed run where extraction genuinely misses an id. The
        # assertions below are therefore deliberately structural (exact stage
        # list, `extracted` absent from the chain) rather than relying on this
        # fixture to produce a rise — an earlier monotonicity-only version of
        # this test passed against the un-fixed code for exactly that reason.
        case = GoldenCase(
            paper_id="pFunnel",
            mark_scheme=self._mark_scheme(["1", "2"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "2": GoldenAnswer(student_answer="A", awarded_marks=1),
                "99": GoldenAnswer(student_answer="A", awarded_marks=1),
            },
            scan_path=None,
        )

        from lemely.runtime.config import Settings

        report = format_report(
            measure_accuracy([case], gemini_client=None, settings=None),
            Settings().accuracy_eval,
        )

        chain_line = next(line for line in report.splitlines() if "Exclusion funnel:" in line)

        # `extracted` must not appear in the chain at all. This is the
        # load-bearing assertion: it is the only one that fails
        # deterministically if `extracted` is put back between `leaves` and
        # `matched`, regardless of whether this particular fixture happens
        # to produce extracted < matched.
        self.assertNotIn(
            "extracted", chain_line, f"`extracted` is not a funnel stage: {chain_line!r}"
        )
        self.assertEqual(
            [n for n, _ in re.findall(r"(\w+)=(\d+)", chain_line)],
            ["leaves", "matched", "marked", "scored"],
            f"unexpected funnel stages in {chain_line!r}",
        )

        stages = [int(n) for n in re.findall(r"=(\d+)", chain_line)]
        for earlier, later in itertools.pairwise(stages):
            self.assertGreaterEqual(
                earlier, later, f"funnel chain rises: {chain_line!r} -> {stages}"
            )

        # …and it is still reported, just not as a stage.
        self.assertIn("extracted=", report)

    def test_report_discloses_flag_metric_baseline_break(self):
        """Whole-branch review Minor D: the printed run report -- the thing a
        human reads to compare one run against a prior baseline -- must
        carry the same disclosure ``_metrics_from_eval_records``'s docstring
        does, not just bury it in source: pre-US-039 ``flag_precision_high``/
        ``flag_recall`` numbers are not comparable to post-fix numbers, and
        the next baseline should be taken post-merge.
        """
        from lemely.accuracy.harness import (
            GoldenAnswer,
            GoldenCase,
            format_report,
            measure_accuracy,
        )
        from lemely.runtime.config import Settings

        case = GoldenCase(
            paper_id="pDisclosure",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=None,
        )
        report = format_report(
            measure_accuracy([case], gemini_client=None, settings=None),
            Settings().accuracy_eval,
        )
        self.assertIn("US-039", report)
        self.assertIn("not comparable", report)

    def test_format_report_local_scored_var_does_not_collide_with_the_field(self):
        """Whole-branch review Minor E: ``QuestionResult.scored`` ("a marker
        ran") and the DA6a funnel stage exposed by
        ``analyses.exclusion_funnel()["scored"]`` ("the leaf was attempted")
        are two different things, printed on the same funnel line the first
        is excluded from. ``format_report``'s local variable must not be
        bare ``scored`` -- that name collision is exactly what would confuse
        a reader of a run report the first time both are non-trivial. The
        printed label stays ``scored=`` (that is the funnel stage's name,
        not a Python identifier) -- only the local variable is renamed.
        """
        import inspect

        from lemely.accuracy.harness import format_report

        src = inspect.getsource(format_report)
        self.assertNotIn(
            "\n    scored = exclusion_funnel(",
            src,
            "format_report's local funnel-stage variable still shadows the "
            "QuestionResult.scored field name",
        )
        self.assertIn("scored=", src, "the printed funnel line must still say scored=")

    def test_mixed_batch_id_match_rate_only_from_extraction_case(self):
        from lemely.accuracy.harness import (
            DEFAULT_RENDER,
            GoldenAnswer,
            GoldenCase,
            measure_accuracy,
        )
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        _case_scan_path = Path("/nonexistent/scan3.pdf")
        case_scan = GoldenCase(
            paper_id="p4",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=_case_scan_path,
            renders={DEFAULT_RENDER: _case_scan_path},
        )
        case_bypass = GoldenCase(
            paper_id="p5",
            mark_scheme=self._mark_scheme(["1", "2"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "2": GoldenAnswer(student_answer="A", awarded_marks=1),
            },
            scan_path=None,
        )
        fake_extracted = ExtractedAnswers(
            paper_id="p4",
            source_scan="fake",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.9)],
        )

        with patch(
            "lemely.web.services.grading.extract_answers", return_value=fake_extracted
        ) as mock_extract:
            result = measure_accuracy([case_scan, case_bypass], gemini_client=None, settings=None)

        mock_extract.assert_called_once()
        self.assertEqual(result.metrics.id_match_rate, 1.0)
        self.assertEqual(len(result.question_results), 3)

    def test_leaf_key_sets_identical_between_arms_over_golden_corpus(self):
        """#28/M0.4: the set of (paper_id, question_id) leaves the harness
        iterates over must be identical between arms — a structural property
        of the harness's leaf loop (it always iterates ``case.ground_truth``,
        regardless of ``case_arm``), independent of what extraction/marking
        actually return. Both extraction and marking are mocked so no live
        Gemini calls are ever made, and to sidestep correct_paper's
        ConfigError for non-MCQ leaves when gemini_client=None.
        """
        from lemely.accuracy.harness import load_golden_cases, measure_accuracy
        from lemely.core.schemas import CorrectionResult, ExamMetadata, ExtractedAnswers

        golden_dir = Path(__file__).resolve().parent / "golden"
        cases = load_golden_cases(golden_dir)
        self.assertGreater(len(cases), 0)

        def _fake_correct_paper(mark_scheme, extracted_answers, *, gemini_client=None, **kwargs):
            md = mark_scheme.metadata
            return CorrectionResult(
                metadata=ExamMetadata(
                    subject_code=md.subject_code,
                    paper_number=md.paper_number,
                    paper_variant=md.paper_variant,
                    session_month=md.session_month,
                    session_year=md.session_year,
                ),
                questions=[],
            )

        def _fake_extract_answers(scan_path, mark_scheme, *, gemini_client=None):
            return ExtractedAnswers(paper_id="fake", source_scan="fake", answers=[])

        with (
            patch("lemely.io.correction_ai.correct_paper", side_effect=_fake_correct_paper),
            patch(
                "lemely.web.services.grading.extract_answers",
                side_effect=_fake_extract_answers,
            ),
        ):
            oracle_result = measure_accuracy(
                cases, gemini_client=None, settings=None, arm="oracle+mark"
            )
            extract_result = measure_accuracy(
                cases, gemini_client=None, settings=None, arm="extract+mark"
            )

        oracle_keys = {(r.paper_id, r.question_id) for r in oracle_result.eval_records}
        extract_keys = {(r.paper_id, r.question_id) for r in extract_result.eval_records}
        self.assertTrue(oracle_keys)
        self.assertEqual(oracle_keys, extract_keys)


class EvalRecordDerivationBitIdenticalTests(unittest.TestCase):
    """M0.1 acceptance line (spec §4): AccuracyMetrics reproduced bit-identically
    from ``list[EvalRecord]``.

    No literal saved 2026-08-04 JSON exists in the repo (checked), so this
    compares the legacy ``_compute_metrics(question_results)`` path against
    the new ``EvalRecord``-derived path over equivalent inputs, per the
    accepted risk-mitigation reading of that acceptance line.
    """

    def _qr(
        self, qid: str, predicted: int, truth: int, confidence: float, review: bool, is_mcq: bool
    ) -> object:
        from lemely.accuracy.harness import QuestionResult

        return QuestionResult(
            question_id=qid,
            question_type="mcq" if is_mcq else "theory",
            predicted_marks=predicted,
            truth_marks=truth,
            confidence_score=confidence,
            needs_teacher_review=review,
        )

    def test_synthetic_mixed_results_reproduce_bit_identically(self):
        from lemely.accuracy.harness import (
            _compute_metrics,
            _metrics_from_eval_records,
            question_result_to_eval_record,
        )

        results = [
            self._qr("1", 2, 2, 0.95, False, is_mcq=True),  # mcq, correct, confident
            self._qr("2", 0, 2, 0.55, True, is_mcq=False),  # theory, under, flagged
            self._qr("3", 3, 1, 0.91, False, is_mcq=False),  # theory, over, confident+wrong
            self._qr("4", 1, 1, 0.88, False, is_mcq=True),  # mcq, correct
        ]
        id_match_rate = 0.75

        legacy = _compute_metrics(results, id_match_rate=id_match_rate)

        eval_records = [
            question_result_to_eval_record(
                r, run_id="test-run", paper_id="paper-1", arm="extract+mark"
            )
            for r in results
        ]
        derived = _metrics_from_eval_records(eval_records, id_match_rate=id_match_rate)

        self.assertEqual(legacy, derived)

    def test_empty_results_reproduce_bit_identically(self):
        from lemely.accuracy.harness import _compute_metrics, _metrics_from_eval_records

        legacy = _compute_metrics([], id_match_rate=None)
        derived = _metrics_from_eval_records([], id_match_rate=None)
        self.assertEqual(legacy, derived)

    def test_all_correct_reproduces_bit_identically(self):
        from lemely.accuracy.harness import (
            _compute_metrics,
            _metrics_from_eval_records,
            question_result_to_eval_record,
        )

        results = [self._qr("1", 1, 1, 0.99, False, is_mcq=False)]
        legacy = _compute_metrics(results, id_match_rate=1.0)
        eval_records = [
            question_result_to_eval_record(
                r, run_id="test-run", paper_id="paper-1", arm="oracle+mark"
            )
            for r in results
        ]
        derived = _metrics_from_eval_records(eval_records, id_match_rate=1.0)
        self.assertEqual(legacy, derived)

    def test_extraction_conf_propagates_from_question_result(self) -> None:
        """question_result_to_eval_record must not hardcode extraction_conf=None (#36/M1.1)."""
        from lemely.accuracy.harness import QuestionResult, question_result_to_eval_record

        result = QuestionResult(
            question_id="1",
            question_type="mcq",
            predicted_marks=1,
            truth_marks=1,
            confidence_score=0.95,
            needs_teacher_review=False,
            extraction_confidence=0.77,
        )
        record = question_result_to_eval_record(
            result, run_id="test-run", paper_id="paper-1", arm="extract+mark"
        )
        self.assertEqual(record.extraction_conf, 0.77)

    def test_measure_accuracy_pipeline_matches_legacy_compute_metrics(self):
        """Runs the real measure_accuracy() pipeline (both arms) and checks its
        reported AccuracyMetrics — now internally EvalRecord-derived — equal
        what _compute_metrics(question_results) would have computed for the
        same question_results, proving no behavioural drift end-to-end."""
        from lemely.accuracy.harness import (
            DEFAULT_RENDER,
            GoldenAnswer,
            GoldenCase,
            _compute_metrics,
            measure_accuracy,
        )
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

        _case_scan_path = Path("/nonexistent/scan.pdf")
        case_scan = GoldenCase(
            paper_id="p1",
            mark_scheme=self._mark_scheme(["1", "2"]),
            ground_truth={
                "1": GoldenAnswer(student_answer="A", awarded_marks=1),
                "2": GoldenAnswer(student_answer="A", awarded_marks=1),
            },
            scan_path=_case_scan_path,
            renders={DEFAULT_RENDER: _case_scan_path},
        )
        case_bypass = GoldenCase(
            paper_id="p2",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=None,
        )
        fake_extracted = ExtractedAnswers(
            paper_id="p1",
            source_scan="fake",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.9),
                ExtractedAnswer(question_id="2", answer="B", confidence=0.9),  # wrong
            ],
        )

        with patch("lemely.web.services.grading.extract_answers", return_value=fake_extracted):
            result = measure_accuracy([case_scan, case_bypass], gemini_client=None, settings=None)

        expected = _compute_metrics(
            result.question_results, id_match_rate=result.metrics.id_match_rate
        )
        self.assertEqual(result.metrics, expected)

    def _mark_scheme(self, question_ids: list[str]) -> object:
        from lemely.core.loose_schemas import MarkScheme

        ms = {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": len(question_ids),
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": qid, "marks": 1, "type": "mcq", "mcq_answer": "A"} for qid in question_ids
            ],
        }
        return MarkScheme.model_validate(ms)


class RunManifestTests(unittest.TestCase):
    """M0.1/#25: run_id is the join key between EvalRecord rows and a
    RunManifest (spec §3.3); it must not be a hardcoded literal."""

    def _mark_scheme(self, question_ids: list[str]) -> object:
        from lemely.core.loose_schemas import MarkScheme

        ms = {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": len(question_ids),
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": qid, "marks": 1, "type": "mcq", "mcq_answer": "A"} for qid in question_ids
            ],
        }
        return MarkScheme.model_validate(ms)

    def _case(self) -> object:
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase

        return GoldenCase(
            paper_id="p1",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=None,
        )

    def test_default_run_id_varies_between_runs(self):
        from lemely.accuracy.harness import measure_accuracy

        r1 = measure_accuracy([self._case()], gemini_client=None, settings=None)
        r2 = measure_accuracy([self._case()], gemini_client=None, settings=None)
        self.assertNotEqual(r1.manifest.run_id, r2.manifest.run_id)

    def test_manifest_records_n_cases(self):
        """US-037: the manifest must state how many cases the run actually
        measured -- the complement to ``corpus_digest``, which hashes the
        same already-loaded corpus and so cannot by itself reveal that the
        corpus was shrunk before it got there."""
        from lemely.accuracy.harness import measure_accuracy

        result = measure_accuracy([self._case(), self._case()], gemini_client=None, settings=None)
        self.assertEqual(result.manifest.n_cases, 2)

    def test_manifest_n_unparseable_defaults_to_zero(self):
        from lemely.accuracy.harness import measure_accuracy

        result = measure_accuracy([self._case()], gemini_client=None, settings=None)
        self.assertEqual(result.manifest.n_unparseable, 0)

    def test_manifest_records_n_unparseable_when_caller_supplies_it(self):
        """A caller that loaded a corpus with ``load_golden_cases`` and
        chose to proceed anyway (rather than refuse, as the CLI does) must
        still get an honest manifest: two sweeps over 40 and 39 papers are
        not distinguishable from ``corpus_digest`` alone (it only hashes
        whatever loaded), but they are from ``n_unparseable``."""
        from lemely.accuracy.harness import measure_accuracy

        result = measure_accuracy(
            [self._case()], gemini_client=None, settings=None, n_unparseable=1
        )
        self.assertEqual(result.manifest.n_cases, 1)
        self.assertEqual(result.manifest.n_unparseable, 1)

    def test_explicit_run_id_propagates_to_manifest_and_eval_records(self):
        from lemely.accuracy.harness import measure_accuracy

        result = measure_accuracy(
            [self._case()], gemini_client=None, settings=None, run_id="run-explicit-1"
        )
        self.assertEqual(result.manifest.run_id, "run-explicit-1")
        self.assertTrue(result.eval_records)
        self.assertTrue(all(r.run_id == "run-explicit-1" for r in result.eval_records))

    def test_measure_accuracy_populates_eval_records(self):
        """AccuracyResult.eval_records must expose the records already built
        inside measure_accuracy (#72): before this fix they fell out of scope
        and were unobservable outside the function."""
        from lemely.accuracy.harness import measure_accuracy
        from lemely.eval.records import EvalRecord

        result = measure_accuracy([self._case()], gemini_client=None, settings=None)

        self.assertIsInstance(result.eval_records, list)
        self.assertTrue(result.eval_records)
        for record in result.eval_records:
            self.assertIsInstance(record, EvalRecord)
        self.assertEqual(len(result.eval_records), len(result.question_results))

    def _settings_with_models(
        self,
        thinking_level_for=None,
        temperature_for=None,
        top_p_for=None,
        seed_for=None,
        escalation_confidence_threshold=0.80,
        **models,
    ):
        """Minimal stand-in for Settings.gemini with controllable per-task models.

        F1 review MUST-FIX 1: ``correction_borderline``/``escalation`` are
        real, independently-resolvable ``model_for()`` tags now (default to
        the same stand-in model as "correction" unless a caller overrides
        them), and ``thinking_level_for`` is a real attribute the harness
        reads — both must exist here or the harness's F1 fingerprint code
        raises on this stand-in.

        US-028: ``scan_metadata`` is now a resolvable tag too, and
        ``temperature_for``/``top_p_for``/``seed_for``/
        ``escalation_confidence_threshold`` are real attributes the harness
        now reads — all must exist here for the same reason.
        """
        from types import SimpleNamespace

        defaults = {
            "mark_scheme": "m-a",
            "extraction": "m-a",
            "correction": "m-a",
            "correction_borderline": "m-a",
            "escalation": "m-a",
            "scan_metadata": "m-a",
        }
        defaults.update(models)
        gemini = SimpleNamespace(
            temperature=0.0,
            top_p=1.0,
            seed=7,
            thinking_budget_for={"extraction": 100},
            thinking_level_for=thinking_level_for or {},
            # Each default dict below carries one distinct, non-empty entry
            # (rather than all three rendering identically as ``{}`` ->
            # ``[]``) so the pinned no-arm-override fingerprint below is
            # sensitive to *which* of the three dicts a future edit drops,
            # not just to whether one was dropped at all.
            temperature_for=(
                temperature_for if temperature_for is not None else {"mark_scheme": 0.11}
            ),
            top_p_for=top_p_for if top_p_for is not None else {"mark_scheme": 0.22},
            seed_for=seed_for if seed_for is not None else {"mark_scheme": 33},
            escalation_confidence_threshold=escalation_confidence_threshold,
            model_for=lambda task: defaults[task],
        )
        return SimpleNamespace(gemini=gemini)

    def test_params_fingerprint_distinguishes_different_models(self):
        """Two runs on different models must NOT share a params_fingerprint.

        Regression test for the false-zero-delta trap: the fingerprint omitted
        the model entirely, so an A/B across models recorded identical
        parameters and M0.3 would read the difference as noise from the
        instrument rather than a real change (spec §3.3).
        """
        from lemely.accuracy.harness import measure_accuracy

        a = measure_accuracy(
            [self._case()], gemini_client=None, settings=self._settings_with_models()
        )
        b = measure_accuracy(
            [self._case()],
            gemini_client=None,
            settings=self._settings_with_models(extraction="m-DIFFERENT"),
        )
        self.assertNotEqual(
            a.manifest.params_fingerprint,
            b.manifest.params_fingerprint,
            "a different extraction model must change the run's params_fingerprint",
        )

    def test_params_fingerprint_is_stable_for_identical_settings(self):
        """The fingerprint must be deterministic, or every run looks like a change."""
        from lemely.accuracy.harness import measure_accuracy

        a = measure_accuracy(
            [self._case()], gemini_client=None, settings=self._settings_with_models()
        )
        b = measure_accuracy(
            [self._case()], gemini_client=None, settings=self._settings_with_models()
        )
        self.assertEqual(a.manifest.params_fingerprint, b.manifest.params_fingerprint)

    def test_params_fingerprint_covers_max_output_tokens(self):
        """``_MAX_OUTPUT_TOKENS`` is part of the hashed input, as it is canonically."""
        import lemely.accuracy.harness as harness_mod
        from lemely.accuracy.harness import measure_accuracy

        settings = self._settings_with_models()
        before = measure_accuracy(
            [self._case()], gemini_client=None, settings=settings
        ).manifest.params_fingerprint

        original = harness_mod._MAX_OUTPUT_TOKENS
        try:
            harness_mod._MAX_OUTPUT_TOKENS = original + 1
            after = measure_accuracy(
                [self._case()], gemini_client=None, settings=settings
            ).manifest.params_fingerprint
        finally:
            harness_mod._MAX_OUTPUT_TOKENS = original

        self.assertNotEqual(before, after)

    def test_params_fingerprint_distinguishes_arms(self):
        """The two arms of an M0.4 ablation sweep (#28) must archive
        distinguishable manifests. Before this fix ``arm`` was not part of
        ``fingerprint_raw`` at all, so ``oracle+mark`` and ``extract+mark``
        runs -- identical in every other knob -- hashed to the same
        ``params_fingerprint``, and the pair of archived runs #28 exists to
        produce would be indistinguishable evidence the moment M0.3's
        cross-run comparator reads them.
        """
        from lemely.accuracy.harness import _build_run_manifest

        settings = self._settings_with_models()
        oracle = _build_run_manifest(
            "run-oracle",
            [self._case()],
            settings,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
            arm="oracle+mark",
        )
        extract = _build_run_manifest(
            "run-extract",
            [self._case()],
            settings,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
            arm="extract+mark",
        )
        self.assertNotEqual(
            oracle.params_fingerprint,
            extract.params_fingerprint,
            "the arm override must change the run's params_fingerprint",
        )

    def test_params_fingerprint_for_no_arm_override_is_unchanged(self):
        """``arm=None`` (today's default -- no override, per-case selection by
        ``scan_path``) must reproduce the exact pre-change fingerprint for
        otherwise-identical inputs. Pinned as a literal (not re-derived by
        calling ``_build_run_manifest`` again) so a future change to the hash
        inputs is caught by this test rather than silently accepted.

        Re-pinned for the F1 review MUST-FIX 1 fix (2026-09-17): the hash now
        also folds in ``correction_borderline``/``escalation`` models and
        ``thinking_level_for``, which is a deliberate widening of what
        invalidates a manifest, not an accidental drift — see
        ``_build_run_manifest``.

        Re-pinned again for US-028 (2026-09-18): the hash now also folds in
        ``scan_metadata`` (models_by_task), the per-task ``temperature_for``/
        ``top_p_for``/``seed_for`` dicts, and
        ``escalation_confidence_threshold`` — closing the pre-existing gaps
        the F1 adversarial review found, per the same deliberate-widening
        rationale as the F1 re-pin above.

        Re-pinned again for I1 (2026-09-18): the hash now also folds in the
        constant ``EXTRACTION_MEDIA_RESOLUTION`` -- see
        ``_build_run_manifest``'s I1 comment: nothing set a media resolution
        before this story, and a per-page-image extraction run must not
        archive the same fingerprint as a pre-I1 run that set none at all.

        Re-pinned a third time, still under US-028 (2026-09-18 review fix):
        no further fingerprint input changed here — ``_settings_with_models``
        itself changed, giving ``temperature_for``/``top_p_for``/``seed_for``
        each a distinct default entry instead of all three defaulting to
        ``{}`` (review NIT: makes this pin sensitive to *which* dict a future
        edit drops, not just to whether one was dropped at all).
        """
        from lemely.accuracy.harness import _build_run_manifest

        settings = self._settings_with_models()
        manifest = _build_run_manifest(
            "run-x",
            [self._case()],
            settings,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        self.assertEqual(manifest.params_fingerprint, "af7fa9cd0e2a")

    def test_params_fingerprint_distinguishes_thinking_level_for(self):
        """F1 review MUST-FIX 1: after the Gemini 3.x migration,
        ``thinking_level_for`` is the dominant knob on the correction model
        (2.5's ``thinking_budget_for`` no longer covers it). Two sweeps
        differing ONLY in ``thinking_level_for["correction"]`` issue
        genuinely different API calls and must NOT archive the same
        ``params_fingerprint`` — that would be the exact false-zero-delta
        failure ``test_params_fingerprint_distinguishes_different_models``
        already guards for models.
        """
        from lemely.accuracy.harness import _build_run_manifest

        settings_low = self._settings_with_models(thinking_level_for={"correction": "low"})
        settings_high = self._settings_with_models(thinking_level_for={"correction": "high"})

        low = _build_run_manifest(
            "run-low",
            [self._case()],
            settings_low,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        high = _build_run_manifest(
            "run-high",
            [self._case()],
            settings_high,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        self.assertNotEqual(
            low.params_fingerprint,
            high.params_fingerprint,
            "a different thinking_level_for['correction'] must change the run's params_fingerprint",
        )

    def _manifest(self, settings: object) -> object:
        from lemely.accuracy.harness import _build_run_manifest

        return _build_run_manifest(
            "run",
            [self._case()],
            settings,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )

    def test_flag_off_fingerprint_is_unchanged(self) -> None:
        """Settings with both flags off hash exactly as before this change.

        Before the change the harness never read ``settings.grading``, so a
        stand-in without it reproduces the old computation. Adding a
        flags-off ``grading`` must not move the hash, or every existing
        baseline becomes incomparable.
        """
        from lemely.runtime.config import GradingSettings

        without = self._settings_with_models()
        with_off = self._settings_with_models()
        with_off.grading = GradingSettings()
        self.assertEqual(
            self._manifest(without).params_fingerprint,
            self._manifest(with_off).params_fingerprint,
        )

    def test_each_flag_moves_the_fingerprint(self) -> None:
        from lemely.runtime.config import GradingSettings

        prints = set()
        for grading in (
            GradingSettings(),
            GradingSettings(equivalence_gate=True),
            GradingSettings(ecf_substitution=True),
            GradingSettings(equivalence_gate=True, ecf_substitution=True),
        ):
            settings = self._settings_with_models()
            settings.grading = grading
            prints.add(self._manifest(settings).params_fingerprint)
        self.assertEqual(len(prints), 4, "each flag combination must hash differently")

    def test_measure_accuracy_passes_marking_options_from_settings(self) -> None:
        """measure_accuracy must forward the settings' marking flags to
        correct_paper as MarkingOptions, not merely read them for the
        manifest fingerprint.

        The spy patches ``lemely.io.correction_ai.correct_paper`` (not
        ``lemely.accuracy.harness.correct_paper``): the harness imports
        ``correct_paper`` freshly inside ``measure_accuracy``'s body on
        every call (``from lemely.io.correction_ai import correct_paper``),
        so there is no module-level ``lemely.accuracy.harness.correct_paper``
        attribute to patch -- patching the real source, as the existing
        ``test_leaf_key_sets_identical_between_arms_over_golden_corpus``
        does above, is what actually intercepts the call.
        """
        import contextlib

        from lemely.accuracy.harness import measure_accuracy
        from lemely.runtime.config import GradingSettings, MarkingOptions

        class _Stop(Exception):
            pass

        recorded: dict[str, object] = {}

        def _spy(mark_scheme, extracted_answers, *, gemini_client=None, **kwargs):
            recorded["options"] = kwargs["options"]
            raise _Stop

        settings = self._settings_with_models()
        settings.grading = GradingSettings(equivalence_gate=True, ecf_substitution=True)

        with (
            patch("lemely.io.correction_ai.correct_paper", side_effect=_spy),
            contextlib.suppress(_Stop),
        ):
            measure_accuracy([self._case()], gemini_client=None, settings=settings)

        self.assertEqual(
            recorded.get("options"),
            MarkingOptions(equivalence_gate=True, ecf_substitution=True),
        )

    def test_params_fingerprint_distinguishes_temperature_for(self):
        """US-028: ``temperature_for`` per-task overrides were never hashed —
        only the global ``temperature`` scalar was. The dict is live only for
        a 2.5-and-earlier tag (``GeminiClient._resolved_gen_params`` returns
        ``temperature=None`` unconditionally for any 3.x model and never
        reads it) — today that means "mark_scheme" (still 2.5-flash, D20);
        any other tag can move onto 2.5 in a future sweep. It is hashed
        unconditionally regardless of which tag it is keyed on, a deliberate
        over-approximation that errs toward telling two runs apart rather
        than risk missing a case where it genuinely changes a call. Two
        sweeps differing ONLY in ``temperature_for["correction"]`` must NOT
        archive the same ``params_fingerprint``.
        """
        from lemely.accuracy.harness import _build_run_manifest

        settings_low = self._settings_with_models(temperature_for={"correction": 0.0})
        settings_high = self._settings_with_models(temperature_for={"correction": 1.0})

        low = _build_run_manifest(
            "run-temp-low",
            [self._case()],
            settings_low,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        high = _build_run_manifest(
            "run-temp-high",
            [self._case()],
            settings_high,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        self.assertNotEqual(
            low.params_fingerprint,
            high.params_fingerprint,
            "a different temperature_for['correction'] must change the run's params_fingerprint",
        )

    def test_params_fingerprint_distinguishes_top_p_for(self):
        """US-028: ``top_p_for`` per-task overrides were never hashed — only
        the global ``top_p`` scalar was. Same "live only for a 2.5-and-
        earlier tag, hashed unconditionally as a deliberate over-
        approximation" rationale as ``temperature_for`` above.
        """
        from lemely.accuracy.harness import _build_run_manifest

        settings_low = self._settings_with_models(top_p_for={"correction": 0.5})
        settings_high = self._settings_with_models(top_p_for={"correction": 0.9})

        low = _build_run_manifest(
            "run-topp-low",
            [self._case()],
            settings_low,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        high = _build_run_manifest(
            "run-topp-high",
            [self._case()],
            settings_high,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        self.assertNotEqual(
            low.params_fingerprint,
            high.params_fingerprint,
            "a different top_p_for['correction'] must change the run's params_fingerprint",
        )

    def test_params_fingerprint_distinguishes_seed_for(self):
        """US-028: ``seed_for`` per-task overrides were never hashed — only
        the global ``seed`` scalar was. Same "live only for a 2.5-and-earlier
        tag, hashed unconditionally as a deliberate over-approximation"
        rationale as ``temperature_for``/``top_p_for`` above.
        """
        from lemely.accuracy.harness import _build_run_manifest

        settings_a = self._settings_with_models(seed_for={"correction": 1})
        settings_b = self._settings_with_models(seed_for={"correction": 2})

        a = _build_run_manifest(
            "run-seed-a",
            [self._case()],
            settings_a,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        b = _build_run_manifest(
            "run-seed-b",
            [self._case()],
            settings_b,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        self.assertNotEqual(
            a.params_fingerprint,
            b.params_fingerprint,
            "a different seed_for['correction'] must change the run's params_fingerprint",
        )

    def test_params_fingerprint_distinguishes_escalation_confidence_threshold(self):
        """US-028: ``escalation_confidence_threshold`` decides WHICH calls a
        run issues (whether a low-confidence mark escalates to the stronger
        escalation model at all) and is a knob a measurement sweep may
        legitimately vary — it was entirely absent from the hash, so two
        such sweeps collided on the same ``params_fingerprint`` despite
        issuing a different set of calls.
        """
        from lemely.accuracy.harness import _build_run_manifest

        settings_low = self._settings_with_models(escalation_confidence_threshold=0.5)
        settings_high = self._settings_with_models(escalation_confidence_threshold=0.9)

        low = _build_run_manifest(
            "run-esc-low",
            [self._case()],
            settings_low,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        high = _build_run_manifest(
            "run-esc-high",
            [self._case()],
            settings_high,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        self.assertNotEqual(
            low.params_fingerprint,
            high.params_fingerprint,
            "a different escalation_confidence_threshold must change the run's params_fingerprint",
        )

    def test_params_fingerprint_distinguishes_scan_metadata_model(self):
        """US-028: ``scan_metadata_model`` resolves through its own
        ``model_for("scan_metadata")`` tag but was never named in
        ``models_by_task``, so two sweeps differing only in the scan-metadata
        model collided on the same ``params_fingerprint``. This harness path
        never issues a scan-metadata call itself (that tag is only ever
        resolved on the ingestion path, ``lemely/io/scan_metadata.py``) —
        recording it here is on the same "record the resolved pipeline
        config this run is an instance of" basis as "mark_scheme" already is
        above, not a claim that this run's own calls exercise it.
        """
        from lemely.accuracy.harness import _build_run_manifest

        settings = self._settings_with_models()
        different = self._settings_with_models(scan_metadata="m-DIFFERENT")

        base = _build_run_manifest(
            "run-scanmeta-base",
            [self._case()],
            settings,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        changed = _build_run_manifest(
            "run-scanmeta-changed",
            [self._case()],
            different,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )
        self.assertNotEqual(
            base.params_fingerprint,
            changed.params_fingerprint,
            "a different scan_metadata model must change the run's params_fingerprint",
        )

    def test_manifest_is_a_run_manifest_instance(self):
        from lemely.accuracy.harness import measure_accuracy
        from lemely.eval.manifest import RunManifest

        result = measure_accuracy([self._case()], gemini_client=None, settings=None)
        self.assertIsInstance(result.manifest, RunManifest)
        self.assertEqual(result.manifest.split, "dev")
        self.assertEqual(
            result.manifest.prompt_versions.keys(), {"extraction", "correction", "mark_scheme"}
        )

    def _bypass_gemini_client(self, tmp: str):
        """A real GeminiClient instantiated with a non-default cache mode.

        The genai SDK client is mocked out (``_genai_client``) so no network
        call can happen; the point under test is purely that the client's own
        configured default cache mode — not the literal "read_write" — is
        what ends up in the manifest.
        """
        from unittest.mock import MagicMock

        from lemely.io.gemini import GeminiClient
        from lemely.runtime.config import PathsSettings, load_settings

        with patch.dict(os.environ, {}, clear=False):
            for k in [k for k in os.environ if k.startswith("LEMELY_")]:
                del os.environ[k]
            settings = load_settings(toml_path=None, cwd=Path(tmp))
        settings = settings.model_copy(
            update={
                "paths": PathsSettings(
                    cache_dir=Path(tmp) / ".cache",
                    output_dir=Path(tmp) / "outputs",
                )
            }
        )
        return GeminiClient(
            settings,
            _genai_client=MagicMock(),
            default_cache_mode="bypass",
        )

    def test_manifest_cache_mode_reads_client_bypass_default(self):
        """manifest.cache_mode must reflect the client's configured default,
        not the harness's own hardcoded "read_write" literal (#73)."""
        from lemely.accuracy.harness import measure_accuracy

        with tempfile.TemporaryDirectory() as tmp:
            client = self._bypass_gemini_client(tmp)
            result = measure_accuracy([self._case()], gemini_client=client, settings=None)

        self.assertEqual(result.manifest.cache_mode, "bypass")

    def test_authorised_test_split_records_split_test(self):
        """An authorised split="test" run must record manifest.split == "test",
        and must append EXACTLY ONE entry to the test-touch ledger (#73).

        The ledger is pointed at a tmp path, never the real
        ``reports/accuracy/test-touch-ledger.jsonl``: this test does not touch
        the test split in any meaningful sense, and letting it append to the
        real M0.7a audit artefact on every unit-test run would forge audit
        history — the artefact would record test-split touches that never
        happened. The exactly-one assertion also pins the fix for the
        double-gating bug: authorising in both ``measure_accuracy`` and
        ``_build_run_manifest`` would write two entries for one run.
        """
        from lemely.accuracy.harness import measure_accuracy

        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "test-touch-ledger.jsonl"
            with patch.dict(os.environ, {"LEMELY_TEST_SPLIT_TOKEN": "shh-secret"}):
                result = measure_accuracy(
                    [self._case()],
                    gemini_client=None,
                    settings=None,
                    split="test",
                    test_split_token="shh-secret",
                    ledger_path=ledger,
                )

            self.assertEqual(result.manifest.split, "test")
            entries = ledger.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(entries), 1, f"expected exactly one ledger entry, got {entries}")

    def test_unauthorised_test_split_raises_before_reading_or_spending(self):
        """No/wrong token for split="test" must raise TestSplitAccessError, not
        silently record "dev" or "test" (#73).

        Crucially it must raise BEFORE the corpus is read or a single Gemini
        call is made. The gate originally lived in ``_build_run_manifest``,
        which runs only in ``measure_accuracy``'s final ``return`` — so an
        unauthorised test-split run read the whole split and spent real budget
        before being refused, which defeats the entire point of M0.7a. The
        spy below is what pins the ordering; without it this test passes even
        with the gate at the very end.
        """
        from lemely.accuracy.harness import measure_accuracy
        from lemely.eval.test_touch import TestSplitAccessError

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEMELY_TEST_SPLIT_TOKEN", None)
            with patch("lemely.io.correction_ai.correct_paper") as correct_spy:
                with self.assertRaises(TestSplitAccessError):
                    measure_accuracy(
                        [self._case()],
                        gemini_client=None,
                        settings=None,
                        split="test",
                        test_split_token=None,
                    )
                correct_spy.assert_not_called()


class SaveResultRoundTripTests(unittest.TestCase):
    """#72: save_result must persist manifest and eval_records, not just the
    legacy metrics/calibration/question_results keys -- both were computed
    inside measure_accuracy but discarded before this fix, making the
    run_id -> RunManifest join unobservable outside the function."""

    def _mark_scheme(self, question_ids: list[str]) -> object:
        from lemely.core.loose_schemas import MarkScheme

        ms = {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": len(question_ids),
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": qid, "marks": 1, "type": "mcq", "mcq_answer": "A"} for qid in question_ids
            ],
        }
        return MarkScheme.model_validate(ms)

    def _case(self) -> object:
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase

        return GoldenCase(
            paper_id="p1",
            mark_scheme=self._mark_scheme(["1"]),
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=None,
        )

    def test_save_result_round_trips_manifest_and_eval_records(self):
        from lemely.accuracy.harness import measure_accuracy, save_result
        from lemely.eval.analyses import review_rate
        from lemely.eval.manifest import RunManifest
        from lemely.eval.records import EvalRecord

        result = measure_accuracy(
            [self._case()], gemini_client=None, settings=None, run_id="run-round-trip-1"
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_path = save_result(result, Path(tmp))
            data = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertIn("manifest", data)
        self.assertIn("eval_records", data)

        manifest = RunManifest.model_validate(data["manifest"])
        self.assertEqual(manifest, result.manifest)

        records = [EvalRecord.model_validate(r) for r in data["eval_records"]]
        self.assertEqual(records, result.eval_records)
        self.assertTrue(all(r.run_id == "run-round-trip-1" for r in records))

        # Point the instrument at something real: a pure analysis over the
        # records reconstructed from disk, not the in-memory objects.
        #
        # The assertions below are deliberately exact rather than bounds.
        # ``0.0 <= review_rate_total <= 1.0`` holds *by construction* and
        # passes on an EMPTY record list — as does ``all(...)`` above — so a
        # regression that made ``save_result`` write ``"eval_records": []``
        # would sail straight through a bounds check while destroying the very
        # thing #72 exists to deliver. Pinning ``n`` to the record count is
        # what makes this test fail if the records stop arriving.
        self.assertTrue(records, "eval_records round-tripped empty — #72's whole point")
        rate = review_rate(records)
        self.assertEqual(rate["n"], len(records))
        self.assertEqual(rate["review_rate_total"], 0.0)
        self.assertEqual(rate["review_rate_signal"], 0.0)


class CoherenceTriggerWiringTests(unittest.TestCase):
    """M1.5 (#40) SHOULD-FIX: the correction_ai -> harness coherence-trigger
    wiring is stringly-typed (``_review_triggers`` substring-matches every
    ``_check_coherence`` review_reason against
    ``lemely.io.correction_ai.COHERENCE_TRIGGER_MARKER``). A reworded message
    on one side without updating the other would make
    ``coherence_trigger_rate`` silently read 0.0 with every unit test still
    green, because the two sides were never exercised together end to end.
    This test drives the REAL production message through
    ``_build_ai_corrected`` -> ``QuestionResult`` -> ``_review_triggers`` (via
    ``question_result_to_eval_record``), rather than hand-typing a literal
    review_reason string, so it fails if either side of the wiring drifts.
    """

    def test_real_coherence_review_reason_produces_coherence_mismatch_trigger(self) -> None:
        from lemely.accuracy.harness import QuestionResult, question_result_to_eval_record
        from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType
        from lemely.core.schemas import AIMarkResponse
        from lemely.io.correction_ai import _build_ai_corrected

        question = Question.model_construct(
            id="2",
            marks=2,
            type=QuestionType.EXPLANATION,
            answer_points=[
                AnswerPoint(id="p1", point="method", marks=1),
                AnswerPoint(id="p2", point="final answer", marks=1),
            ],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )
        mark = AIMarkResponse(
            awarded_marks=2,
            confidence=1.0,
            matched_point_ids=["p1"],  # implies [1, 1]; awarded_marks=2 is outside it.
            feedback="test",
        )
        cq = _build_ai_corrected(question, "answer", mark)
        self.assertTrue(cq.needs_teacher_review)  # sanity: the gate actually fired

        result = QuestionResult(
            question_id="2",
            question_type="theory",
            predicted_marks=cq.awarded_marks,
            truth_marks=1,
            confidence_score=mark.confidence,
            needs_teacher_review=cq.needs_teacher_review,
            review_reason=cq.review_reason,
        )
        record = question_result_to_eval_record(
            result, run_id="wiring-test", paper_id="p1", arm="extract+mark"
        )
        self.assertIn("coherence_mismatch", record.triggers)
        self.assertIn("needs_teacher_review", record.triggers)

    def test_review_reason_without_the_marker_does_not_fire_coherence_trigger(self) -> None:
        """Negative control: a review reason from a DIFFERENT gate (e.g. low
        confidence) must not spuriously carry the coherence trigger."""
        from lemely.accuracy.harness import QuestionResult, question_result_to_eval_record

        result = QuestionResult(
            question_id="1",
            question_type="theory",
            predicted_marks=1,
            truth_marks=1,
            confidence_score=0.5,
            needs_teacher_review=True,
            review_reason="confidence 0.50 is below review threshold 0.90",
        )
        record = question_result_to_eval_record(
            result, run_id="wiring-test", paper_id="p1", arm="extract+mark"
        )
        self.assertNotIn("coherence_mismatch", record.triggers)
        self.assertIn("needs_teacher_review", record.triggers)


class CostCeilingAbortsTheSweepTests(unittest.TestCase):
    """US-030: a run that breached its spend ceiling is never archived.

    ``_check_cost_ceiling`` raises :class:`~lemely.runtime.errors.CostCeilingError`
    -- a stop signal for the whole run. Before this fix ``correct_paper``'s broad
    ``except Exception`` absorbed it into a ``marker_source="missing"`` question
    with ``awarded=0`` and ``review_reason="AI marking failed: USD ceiling
    (...)"``, so the sweep ran to completion over every remaining case and the
    CLI archived a full accuracy report whose zeros were indistinguishable from
    real model failures. The breach must abort the sweep with nothing archived.
    """

    @staticmethod
    def _theory_mark_scheme(question_ids: list[str]) -> object:
        from lemely.core.loose_schemas import MarkScheme

        return MarkScheme.model_validate(
            {
                "metadata": {
                    "subject": "Physics",
                    "subject_code": "0625",
                    "paper_number": 4,
                    "paper_variant": 2,
                    "session_month": "May/June",
                    "session_year": 2020,
                    "paper_type": "theory_extended",
                    "maximum_mark": 2 * len(question_ids),
                    "scheme_format": "point_based",
                },
                "questions": [
                    {
                        "id": qid,
                        "marks": 2,
                        "type": "explanation",
                        "question_command": "explain why",
                        "answer_points": [
                            {"id": "p1", "point": "the reason", "marks": 2},
                        ],
                    }
                    for qid in question_ids
                ],
            }
        )

    @staticmethod
    def _mark_response() -> object:
        from lemely.core.schemas import AIMarkResponse

        return AIMarkResponse(
            awarded_marks=2, confidence=0.9, matched_point_ids=["p1"], feedback="good"
        )

    def _cases(self) -> list[object]:
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase

        return [
            GoldenCase(
                paper_id=paper_id,
                mark_scheme=self._theory_mark_scheme(["1", "2"]),
                ground_truth={
                    "1": GoldenAnswer(student_answer="the reason", awarded_marks=2),
                    "2": GoldenAnswer(student_answer="the reason", awarded_marks=2),
                },
                scan_path=None,
            )
            for paper_id in ("p-first", "p-second")
        ]

    def _marker_that_breaches_after(self, n_successes: int):
        """A ``mark_question`` stub: ``n_successes`` clean marks, then the
        ceiling binds and keeps binding (as the real client's check does)."""
        from lemely.runtime.errors import CostCeilingError

        calls: list[str] = []

        def _mark_question(_self, question, *args, **kwargs):
            calls.append(question.id)
            if len(calls) > n_successes:
                raise CostCeilingError(
                    "USD ceiling ($14.0000) exceeded; persistent cumulative spend "
                    "is $14.0100 (across all runs)."
                )
            return self._mark_response()

        return _mark_question, calls

    def test_measure_accuracy_aborts_the_sweep_and_returns_no_result(self) -> None:
        """Three clean marks, then the ceiling binds on the fourth (the second
        paper's last leaf). ``measure_accuracy`` must raise rather than return
        an ``AccuracyResult`` -- no ``RunManifest``, no metrics, no records."""
        from unittest.mock import MagicMock

        from lemely.accuracy.harness import measure_accuracy
        from lemely.io.correction_ai import AICorrector
        from lemely.runtime.errors import CostCeilingError

        stub, calls = self._marker_that_breaches_after(3)

        with (
            patch.object(AICorrector, "mark_question", stub),
            self.assertRaises(CostCeilingError) as ctx,
        ):
            measure_accuracy(
                self._cases(),
                # ``default_cache_mode`` is the one attribute
                # ``_build_run_manifest`` reads off the client; a bare
                # MagicMock would fail RunManifest validation and mask
                # the behaviour under test.
                gemini_client=MagicMock(default_cache_mode="bypass"),
                settings=None,
                arm="oracle+mark",
            )

        self.assertIn("USD ceiling", str(ctx.exception))
        # Exactly four attempts: the run stopped at the breach instead of
        # re-breaching on every remaining leaf.
        self.assertEqual(len(calls), 4)

    def test_a_breach_mid_sweep_archives_no_report_and_exits_ten(self) -> None:
        """AC4, end to end through the CLI.

        Asserts on the ABSENCE of the archived artifact -- ``--results-dir``
        stays empty, so no ``<date>-<sha>.json`` carrying a ``RunManifest``
        and a metric table was written -- and on the exit classification:
        ``CostCeilingError.exit_code`` is 10, not 1 (an unhandled programming
        error) and not 0 (a run reported as complete).
        """
        import json as _json
        from unittest.mock import MagicMock

        from lemely.app.cli import main
        from lemely.io.correction_ai import AICorrector

        stub, calls = self._marker_that_breaches_after(3)

        with tempfile.TemporaryDirectory() as tmp:
            golden_dir = Path(tmp) / "golden"
            results_dir = Path(tmp) / "results"
            results_dir.mkdir(parents=True)
            for case in self._cases():
                case_dir = golden_dir / case.paper_id
                case_dir.mkdir(parents=True)
                (case_dir / "mark_scheme.json").write_text(
                    case.mark_scheme.model_dump_json(), encoding="utf-8"
                )
                (case_dir / "answers.json").write_text(
                    _json.dumps(
                        {
                            qid: {"student_answer": gt.student_answer, "awarded_marks": 2}
                            for qid, gt in case.ground_truth.items()
                        }
                    ),
                    encoding="utf-8",
                )

            with (
                patch.object(AICorrector, "mark_question", stub),
                patch(
                    "lemely.io.gemini.GeminiClient",
                    # ``default_cache_mode`` is read back off the client into
                    # ``RunManifest.cache_mode``; a bare MagicMock would fail
                    # that validation and exit 1 for an unrelated reason.
                    return_value=MagicMock(default_cache_mode="bypass"),
                ),
            ):
                exit_code = main(
                    [
                        "measure-accuracy",
                        "--golden",
                        str(golden_dir),
                        "--results-dir",
                        str(results_dir),
                        "--arm",
                        "oracle+mark",
                    ]
                )

            archived = sorted(p.name for p in results_dir.iterdir())

        self.assertEqual(len(calls), 4)
        # Nothing archived: no result JSON, so no manifest and no metric table
        # claiming this partial run as a completed measurement.
        self.assertEqual(archived, [])
        # Classified as a budget-ceiling stop (exit 10), not 1 / not 0.
        self.assertEqual(exit_code, 10)


class CorpusDigestTests(unittest.TestCase):
    """US-029: `_corpus_digest` must fold in the two inputs actually sent to
    the model (the mark scheme content and the scan bytes) so that two runs
    over corpora that differ only in those respects do not collide on the
    same digest, while staying stable when nothing changed at all.
    """

    def _build_corpus(
        self,
        root: Path,
        *,
        case_name: str = "0625_m20_qp_12",
        maximum_mark: int = 1,
        scan_bytes: bytes = b"%PDF-1.4 fake scan bytes, version A\n",
    ) -> Path:
        case_dir = root / case_name
        case_dir.mkdir(parents=True, exist_ok=True)
        ms = {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": maximum_mark,
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": "1", "marks": maximum_mark, "type": "mcq", "mcq_answer": "A"},
            ],
        }
        (case_dir / "mark_scheme.json").write_text(json.dumps(ms), encoding="utf-8")
        answers = {"1": {"student_answer": "A", "awarded_marks": 1}}
        (case_dir / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
        (case_dir / "scan.pdf").write_bytes(scan_bytes)
        return case_dir

    def _digest_of(self, golden_dir: Path) -> str:
        from lemely.accuracy.harness import _corpus_digest, load_golden_cases

        cases = load_golden_cases(golden_dir)
        self.assertEqual(len(cases), 1, "test corpus must load exactly one case")
        return _corpus_digest(cases)

    def test_digest_stable_across_repeated_runs(self):
        """Same corpus, loaded and digested twice, must produce the same
        digest — a digest that moves on every invocation for no reason is
        as useless as one that never moves at all (AC 4).
        """
        with tempfile.TemporaryDirectory() as tmp:
            golden_dir = Path(tmp)
            self._build_corpus(golden_dir)

            first = self._digest_of(golden_dir)
            second = self._digest_of(golden_dir)

        self.assertEqual(first, second)

    def test_digest_moves_when_mark_scheme_edited(self):
        """Editing a golden ``mark_scheme.json`` must move the digest (AC 2):
        before this story, `_corpus_digest` folded in only `paper_id`,
        `fixture_variant`, and the ground-truth leaves — never the mark
        scheme content — so this edit was invisible to it and two sweeps
        against different mark schemes could collide on one digest.
        """
        with (
            tempfile.TemporaryDirectory() as original_root,
            tempfile.TemporaryDirectory() as edited_root,
        ):
            original_case_dir = self._build_corpus(Path(original_root))
            original_digest = self._digest_of(Path(original_root))

            # Copy to a second throwaway temp dir, then mutate ONLY the copy
            # — never the original golden fixture in place.
            edited_golden_dir = Path(edited_root)
            edited_case_dir = edited_golden_dir / "0625_m20_qp_12"
            shutil.copytree(original_case_dir, edited_case_dir)
            ms_path = edited_case_dir / "mark_scheme.json"
            ms = json.loads(ms_path.read_text(encoding="utf-8"))
            ms["metadata"]["maximum_mark"] = 2
            ms["questions"][0]["marks"] = 2
            ms_path.write_text(json.dumps(ms), encoding="utf-8")

            edited_digest = self._digest_of(edited_golden_dir)

        self.assertNotEqual(original_digest, edited_digest)

    def test_digest_moves_when_scan_rerendered(self):
        """Re-rendering a golden ``scan.pdf`` (same paper, same answers,
        different bytes) must move the digest (AC 2): before this story,
        `_corpus_digest` never read scan bytes at all, so a re-render was
        invisible to run identity.
        """
        with (
            tempfile.TemporaryDirectory() as original_root,
            tempfile.TemporaryDirectory() as edited_root,
        ):
            original_case_dir = self._build_corpus(Path(original_root))
            original_digest = self._digest_of(Path(original_root))

            edited_golden_dir = Path(edited_root)
            edited_case_dir = edited_golden_dir / "0625_m20_qp_12"
            shutil.copytree(original_case_dir, edited_case_dir)
            (edited_case_dir / "scan.pdf").write_bytes(b"%PDF-1.4 fake scan bytes, RE-RENDERED\n")

            edited_digest = self._digest_of(edited_golden_dir)

        self.assertNotEqual(original_digest, edited_digest)

    def test_digest_ignores_missing_render_file_without_raising(self):
        """A case constructed with a render path that does not exist on disk
        (as several existing `measure_accuracy` tests do, e.g. with
        ``scan_path=Path("/nonexistent/scan.pdf")``) must not crash the
        digest — it simply contributes no scan bytes for that render.
        """
        from lemely.accuracy.harness import (
            DEFAULT_RENDER,
            GoldenAnswer,
            GoldenCase,
            MarkScheme,
            _corpus_digest,
        )

        mark_scheme = MarkScheme.model_validate(
            {
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
        )
        missing_scan_path = Path("/nonexistent/scan.pdf")
        case = GoldenCase(
            paper_id="p-missing-render",
            mark_scheme=mark_scheme,
            ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
            scan_path=missing_scan_path,
            renders={DEFAULT_RENDER: missing_scan_path},
        )

        digest = _corpus_digest([case])

        self.assertIsInstance(digest, str)
        self.assertEqual(len(digest), 16)

    def test_scan_path_without_matching_render_raises(self):
        """SF-1 (review): `GoldenCase.__post_init__` must refuse a case whose
        ``scan_path`` disagrees with ``renders[DEFAULT_RENDER]`` — including
        the empty-``renders`` shape — because `_corpus_digest` folds
        ``renders``, not ``scan_path``, and a case built this way would
        silently exclude its own scan bytes from the digest: exactly the
        pre-US-029 defect, one field away. `load_golden_cases` always keeps
        the two fields in agreement, so this can only happen via direct
        construction (as ~20 test sites in this file used to do before this
        fix), which is exactly why it must raise rather than pass silently.
        """
        from lemely.accuracy.harness import GoldenAnswer, GoldenCase, MarkScheme

        mark_scheme = MarkScheme.model_validate(
            {
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
        )

        with self.assertRaises(ValueError) as ctx:
            GoldenCase(
                paper_id="p-bad-invariant",
                mark_scheme=mark_scheme,
                ground_truth={"1": GoldenAnswer(student_answer="A", awarded_marks=1)},
                scan_path=Path("/some/real/looking/scan.pdf"),
                # renders left empty — disagrees with scan_path.
            )

        self.assertIn("invariant", str(ctx.exception).lower())

    def test_digest_distinguishes_declared_missing_render_from_undeclared(self):
        """SF-2 (review): a render that is DECLARED but missing on disk must
        not digest identically to a corpus where that render was never
        declared at all — before this fix, folding the render's byte
        content only (and skipping the name on a missing file) made
        ``{default: real, handwritten: missing}`` and ``{default: real}``
        collide, silently treating two different corpora as the same one.
        """
        from lemely.accuracy.harness import (
            DEFAULT_RENDER,
            GoldenAnswer,
            GoldenCase,
            MarkScheme,
            _corpus_digest,
        )

        with tempfile.TemporaryDirectory() as tmp:
            real_scan = Path(tmp) / "scan.pdf"
            real_scan.write_bytes(b"%PDF-1.4 real bytes\n")

            mark_scheme = MarkScheme.model_validate(
                {
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
            )
            ground_truth = {"1": GoldenAnswer(student_answer="A", awarded_marks=1)}

            case_with_declared_missing_render = GoldenCase(
                paper_id="p-declared-missing",
                mark_scheme=mark_scheme,
                ground_truth=ground_truth,
                scan_path=real_scan,
                renders={
                    DEFAULT_RENDER: real_scan,
                    "handwritten": Path("/nonexistent/handwritten.pdf"),
                },
            )
            case_without_that_render = GoldenCase(
                paper_id="p-declared-missing",
                mark_scheme=mark_scheme,
                ground_truth=ground_truth,
                scan_path=real_scan,
                renders={DEFAULT_RENDER: real_scan},
            )

            digest_with_declared_missing = _corpus_digest([case_with_declared_missing_render])
            digest_without = _corpus_digest([case_without_that_render])

        self.assertNotEqual(digest_with_declared_missing, digest_without)


class MeasureAccuracyCmdRefusesShrunkCorpusTests(unittest.TestCase):
    """US-037: ``measure-accuracy`` is the one place a shrunken corpus turns
    into a published accuracy figure (``cli.py`` prints "Loaded N golden
    case(s)." and proceeds as though N were the whole corpus). It must
    refuse rather than silently sweep over fewer papers than the corpus
    actually contains.
    """

    def _make_case_dir(self, root: Path, name: str) -> Path:
        case_dir = root / name
        case_dir.mkdir()
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
        return case_dir

    def test_refuses_when_a_case_is_unparseable(self):
        from click.testing import CliRunner

        from lemely.app.cli import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_case_dir(root, "good_paper")
            bad_dir = self._make_case_dir(root, "bad_paper")
            (bad_dir / "mark_scheme.json").write_text("{ not valid json }")

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["measure-accuracy", "--golden", str(root)],
                env={"GEMINI_API_KEY": "test-key-not-validated-with-no-network"},
            )

        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("bad_paper", result.output)

    def test_proceeds_normally_when_corpus_is_clean(self):
        """False-positive direction: a clean corpus must not be refused by
        the new check -- only reaching a real target-miss/no-cases failure
        downstream (no network call is expected to succeed in this test
        environment, so this just asserts the refusal message is absent)."""
        from click.testing import CliRunner

        from lemely.app.cli import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_case_dir(root, "good_paper")

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["measure-accuracy", "--golden", str(root)],
                env={"GEMINI_API_KEY": "test-key-not-validated-with-no-network"},
            )

        self.assertNotIn("could not be parsed", result.output)
