"""Model-shape tests for the catalogue tables (no database required)."""

from __future__ import annotations

from lemely.db.models.academic import Subject
from lemely.db.models.catalogue import SubjectTopic, SyllabusPaper
from lemely.db.models.enums import PaperTier


def test_paper_tier_has_exactly_core_and_extended() -> None:
    assert {t.value for t in PaperTier} == {"core", "extended"}


def test_syllabus_paper_provenance_columns_are_not_nullable() -> None:
    cols = SyllabusPaper.__table__.columns
    for name in ("source_document", "source_url", "syllabus_version"):
        assert cols[name].nullable is False, f"{name} must be NOT NULL"


def test_syllabus_paper_is_unique_per_board_subject_and_number() -> None:
    uniques = {
        tuple(sorted(c.name for c in con.columns))
        for con in SyllabusPaper.__table__.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("board", "paper_number", "subject_code") in uniques


def test_subject_topic_nests_via_self_referential_parent() -> None:
    parent = SubjectTopic.__table__.columns["parent_id"]
    assert parent.nullable is True
    assert {fk.column.table.name for fk in parent.foreign_keys} == {"subject_topics"}


def test_subject_gains_active_and_qualification_level() -> None:
    cols = Subject.__table__.columns
    assert cols["active"].nullable is False
    assert "qualification_level" in cols
    # `SyllabusTaxonomy.source_url` is a required str, so the subject must be
    # able to supply one — see `lemely/core/topics.py`.
    assert "source_url" in cols
