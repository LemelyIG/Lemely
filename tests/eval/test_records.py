"""EvalRecord field-set, Literal enforcement, and extra='forbid' tests (spec §3.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lemely.eval.records import EvalRecord

# Spec §3.3 "The record model" — EvalRecord field list, exactly.
_SPEC_3_3_EVAL_RECORD_FIELDS = {
    "run_id",
    "arm",
    "paper_id",
    "fixture_variant",
    "question_id",
    "mark_point_id",
    "parse_path",
    "predicted_marks",
    "truth_marks",
    "outcome",
    "extraction_conf",
    "marker_conf",
    "id_match",
    "triggers",
}


def _make_record(**overrides: object) -> EvalRecord:
    base: dict[str, object] = {
        "run_id": "run-2026-08-21-a",
        "arm": "extract+mark",
        "paper_id": "0625_m20_qp_12",
        "fixture_variant": None,
        "question_id": "1",
        "mark_point_id": None,
        "parse_path": "det",
        "predicted_marks": 2,
        "truth_marks": 2,
        "outcome": "correct",
        "extraction_conf": 0.9,
        "marker_conf": 0.95,
        "id_match": "exact",
        "triggers": [],
    }
    base.update(overrides)
    return EvalRecord(**base)  # type: ignore[arg-type]


class TestEvalRecordFieldSet:
    def test_eval_record_field_set_matches_spec(self) -> None:
        assert set(EvalRecord.model_fields) == _SPEC_3_3_EVAL_RECORD_FIELDS


class TestEvalRecordLiteralEnforcement:
    @pytest.mark.parametrize("arm", ["extract+mark", "oracle+mark"])
    def test_accepts_each_valid_arm(self, arm: str) -> None:
        assert _make_record(arm=arm).arm == arm

    def test_rejects_invalid_arm(self) -> None:
        with pytest.raises(ValidationError):
            _make_record(arm="hybrid+mark")

    @pytest.mark.parametrize("parse_path", ["det", "gemini"])
    def test_accepts_each_valid_parse_path(self, parse_path: str) -> None:
        assert _make_record(parse_path=parse_path).parse_path == parse_path

    def test_rejects_invalid_parse_path(self) -> None:
        with pytest.raises(ValidationError):
            _make_record(parse_path="ocr")

    @pytest.mark.parametrize(
        "outcome", ["correct", "over", "under", "abstain", "unmatched", "excluded"]
    )
    def test_accepts_each_valid_outcome(self, outcome: str) -> None:
        assert _make_record(outcome=outcome).outcome == outcome

    def test_rejects_invalid_outcome(self) -> None:
        with pytest.raises(ValidationError):
            _make_record(outcome="wrong")

    @pytest.mark.parametrize("id_match", ["exact", "fuzzy", "unmatched"])
    def test_accepts_each_valid_id_match(self, id_match: str) -> None:
        assert _make_record(id_match=id_match).id_match == id_match

    def test_rejects_invalid_id_match(self) -> None:
        with pytest.raises(ValidationError):
            _make_record(id_match="partial")


class TestEvalRecordExtraForbid:
    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            _make_record(unexpected_field="oops")


class TestEvalRecordMarkPointLevel:
    def test_mark_point_id_none_means_question_level(self) -> None:
        record = _make_record(mark_point_id=None)
        assert record.mark_point_id is None

    def test_mark_point_id_set_means_sub_question_row(self) -> None:
        record = _make_record(mark_point_id="1a")
        assert record.mark_point_id == "1a"

    def test_optional_numeric_fields_accept_none(self) -> None:
        record = _make_record(predicted_marks=None, truth_marks=None, extraction_conf=None)
        assert record.predicted_marks is None
        assert record.truth_marks is None
        assert record.extraction_conf is None
