from pathlib import Path

import pytest
from pydantic import ValidationError

from lemely.core.binding import (
    BindingCheck,
    BindingReport,
    ReadAnswer,
    SeenLabel,
    SeenWriting,
    UnboundWriting,
)
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


def test_stream_items_round_trip_and_default_what_a_reader_may_leave_out():
    label = SeenLabel(page=0, text="(a)", kind="printed")
    assert label.box is None
    assert SeenLabel.model_validate_json(label.model_dump_json()) == label
    with pytest.raises(ValidationError):
        SeenLabel.model_validate({"page": 0, "text": "(a)", "kind": "typed"})
    with pytest.raises(ValidationError):
        SeenLabel.model_validate({"page": 0, "text": "(a)", "kind": "printed", "top": 120})

    bare = SeenWriting(page=1, answer="4")
    assert (bare.working_out, bare.confidence, bare.box, bare.placed_by) == (
        None,
        0.0,
        None,
        "position",
    )
    full = SeenWriting(
        page=1, box=[1, 2, 3, 4], answer="4", working_out="2 + 2", confidence=0.9, placed_by="arrow"
    )
    assert SeenWriting.model_validate_json(full.model_dump_json()) == full
    with pytest.raises(ValidationError):
        SeenWriting.model_validate({"page": 1, "answer": "4", "placed_by": "guess"})

    for reason in (
        "before_first_label",
        "after_unplaced_label",
        "after_container_label",
        "uncertain",
        "next_label_not_seen",
        "next_label_unreadable",
        "neighbour_left_blank",
    ):
        unbound = UnboundWriting.model_validate({"writing": full.model_dump(), "reason": reason})
        assert UnboundWriting.model_validate_json(unbound.model_dump_json()) == unbound
    with pytest.raises(ValidationError):
        UnboundWriting.model_validate({"writing": full.model_dump(), "reason": "lost"})


def test_read_answer_is_the_writing_type_under_its_old_name():
    # schemas.ExtractedAnswers.unbound_answers is typed list[ReadAnswer].
    assert ReadAnswer is SeenWriting
    read = ReadAnswer(page=1, box=[1, 2, 3, 4], answer="4", working_out=None, confidence=0.9)
    doc = ExtractedAnswers.model_validate_json(
        (FIXTURE_DIR / "aligned.json").read_text()
    ).model_copy(update={"unbound_answers": [read]})
    assert ExtractedAnswers.model_validate_json(doc.model_dump_json()).unbound_answers == [read]


def test_check_id_rejects_unknown_ids():
    with pytest.raises(ValidationError):
        BindingCheck.model_validate(
            {"id": "G3", "passed": True, "scope": "paper", "question_ids": [], "detail": ""}
        )


def test_addresses_question_defaults_to_unclear_on_a_reply_without_it():
    reply = AIMarkResponse.model_validate_json(
        '{"awarded_marks": 1, "confidence": 0.8, "feedback": "ok"}'
    )
    assert reply.addresses_question == "unclear"
