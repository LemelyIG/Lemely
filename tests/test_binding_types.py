from pathlib import Path

import pytest
from pydantic import ValidationError

from lemely.core.binding import BindingCheck, BindingReport, LabelMarker, ReadAnswer
from lemely.core.schemas import AIMarkResponse, ExtractedAnswers

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "binding" / "0625_w24_41"


def test_new_fields_default_to_none_so_stored_documents_still_load():
    paths = sorted(FIXTURE_DIR.glob("*.json"))
    assert len(paths) == 8
    for path in paths:
        doc = ExtractedAnswers.model_validate_json(path.read_text())
        assert doc.binding is None, path.name
        assert doc.unbound_answers == [], path.name
        for answer in doc.answers:
            assert answer.binding_source is None, path.name
            assert answer.binding_status is None, path.name
            assert answer.label_seen is None, path.name


def test_binding_report_round_trips_through_json():
    report = BindingReport(
        binder="label",
        checks=[
            BindingCheck(id="G1", passed=True, scope="paper", detail="all ids known"),
            BindingCheck(
                id="G5",
                passed=False,
                scope="question",
                question_ids=["1a", "1b"],
                detail="order inverted",
            ),
        ],
        verdict="retry",
        retried=True,
        model="gemini-test",
    )
    assert BindingReport.model_validate_json(report.model_dump_json()) == report
    assert BindingCheck(id="G2", passed=True, scope="paper", detail="").question_ids == []
    assert LabelMarker(page=0, top=120, text="(a)", kind="printed").kind == "printed"
    read = ReadAnswer(page=1, box=[1, 2, 3, 4], answer="4", working_out=None, confidence=0.9)
    assert ReadAnswer.model_validate_json(read.model_dump_json()) == read


def test_check_id_rejects_unknown_ids():
    with pytest.raises(ValidationError):
        BindingCheck.model_validate(
            {"id": "G3", "passed": True, "scope": "paper", "question_ids": [], "detail": ""}
        )


def test_addresses_question_defaults_to_unclear_on_a_reply_without_it():
    reply = AIMarkResponse.model_validate({"awarded_marks": 1, "confidence": 0.8, "feedback": "ok"})
    assert reply.addresses_question == "unclear"
