"""Tests for question-paper pairing + writing (P4.1, ``lemely.io.question_papers``).

Two tiers:

* Pure-Python unit tests over :func:`_pair_paper` / :func:`_build_row` with
  in-memory :class:`~lemely.core.loose_schemas.MarkScheme` and
  :class:`~lemely.core.question_papers.QuestionPaper` objects — no PDFs, no
  database. Covers every honesty gate named in the P4.1 brief: figure
  exclusion, no-scheme-match skip, no-marking-points skip, marks-mismatch
  skip.
* One Postgres-integration test (mirrors ``test_question_bank_repo.py``'s
  throwaway-database fixture, skipping cleanly when no local Postgres is
  reachable) proving :func:`ingest_question_papers_dir` is idempotent
  end-to-end through the real :class:`QuestionBankService`, with a fake
  extractor callback standing in for pdfplumber.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.loose_schemas import (
    AnswerPoint,
    MarkScheme,
    MarkSchemeMetadata,
    MCQAnswer,
    PaperType,
    Question,
    QuestionType,
    SchemeFormat,
    SessionMonth,
)
from lemely.core.question_papers import (
    QuestionPaper,
    QuestionPaperMetadata,
    QuestionPaperQuestion,
)
from lemely.db.base import Base
from lemely.db.models.enums import QuestionSource
from lemely.db.question_bank_repo import QuestionBankService
from lemely.io.question_papers import _build_row, _pair_paper, ingest_question_papers_dir
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Fixtures — in-memory mark scheme + question paper
# ---------------------------------------------------------------------------


def _theory_scheme() -> MarkScheme:
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code="0625",
            paper_number=4,
            paper_variant=1,
            session_month=SessionMonth.MAY_JUNE,
            session_year=2024,
            paper_type=PaperType.THEORY_EXTENDED,
            maximum_mark=20,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            Question(
                id="1",
                marks=0,
                type=QuestionType.MULTI_STEP,
                parts=[
                    Question(
                        id="1a",
                        parent_id="1",
                        marks=0,
                        type=QuestionType.MULTI_STEP,
                        parts=[
                            Question(
                                id="1a_i",
                                parent_id="1a",
                                marks=2,
                                type=QuestionType.CALCULATION,
                                answer_points=[
                                    AnswerPoint(id="p1", point="uses v=d/t", marks=1),
                                    AnswerPoint(id="p2", point="correct value", marks=1),
                                ],
                            ),
                            Question(
                                id="1a_ii",
                                parent_id="1a",
                                marks=3,
                                type=QuestionType.CALCULATION,
                                answer_points=[
                                    AnswerPoint(id="p1", point="correct method", marks=2),
                                    AnswerPoint(id="p2", point="correct answer", marks=1),
                                ],
                            ),
                        ],
                    ),
                    Question(
                        id="1b",
                        parent_id="1",
                        marks=4,
                        type=QuestionType.EXPLANATION,
                        answer_points=[
                            AnswerPoint(id="p1", point="explains cause", marks=2),
                            AnswerPoint(id="p2", point="explains effect", marks=2),
                        ],
                    ),
                    Question(
                        id="1c",
                        parent_id="1",
                        marks=6,
                        type=QuestionType.CALCULATION,
                        answer_points=[AnswerPoint(id="p1", point="working shown", marks=6)],
                    ),
                    Question(
                        id="1e",
                        parent_id="1",
                        marks=6,
                        type=QuestionType.CALCULATION,
                        answer_points=[AnswerPoint(id="p1", point="working shown", marks=6)],
                    ),
                ],
            ),
        ],
    )


def _qpq(ref: str, *, marks: int | None, has_figure: bool = False) -> QuestionPaperQuestion:
    return QuestionPaperQuestion(
        ref=ref,
        stem=f"Stem text for {ref}.",
        options=None,
        marks=marks,
        page_number=2,
        has_figure=has_figure,
    )


def _theory_qp() -> QuestionPaper:
    return QuestionPaper(
        metadata=QuestionPaperMetadata(
            subject_code="0625",
            paper_number=4,
            paper_variant=1,
            session_month="May/June",
            session_year=2024,
            is_mcq=False,
            stated_total_marks=20,
            source_document="0625_s24_qp_41.pdf",
        ),
        questions=[
            _qpq("1a_i", marks=2),  # bank-eligible
            _qpq("1a_ii", marks=3),  # bank-eligible
            _qpq("1b", marks=4),  # bank-eligible
            _qpq("1c", marks=6, has_figure=True),  # skipped: has_figure
            _qpq("1a", marks=None),  # skipped: matches a container, not a leaf
            _qpq("1z", marks=1),  # skipped: no scheme match at all
            _qpq("1e", marks=5),  # skipped: marks mismatch (scheme says 6)
        ],
    )


def _mcq_scheme() -> MarkScheme:
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code="0625",
            paper_number=1,
            paper_variant=1,
            session_month=SessionMonth.MAY_JUNE,
            session_year=2024,
            paper_type=PaperType.MCQ,
            maximum_mark=1,
            scheme_format=SchemeFormat.MCQ,
        ),
        questions=[Question(id="1", marks=1, type=QuestionType.MCQ, mcq_answer=MCQAnswer.B)],
    )


def _mcq_qp() -> QuestionPaper:
    return QuestionPaper(
        metadata=QuestionPaperMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=1,
            session_month="May/June",
            session_year=2024,
            is_mcq=True,
            stated_total_marks=1,
            source_document="0625_s24_qp_11.pdf",
        ),
        questions=[
            QuestionPaperQuestion(
                ref="1",
                stem="Which unit is a unit of weight?",
                options={"A": "kilogram", "B": "kilonewton", "C": "kilometre", "D": "kilojoule"},
                marks=1,
                page_number=2,
                has_figure=False,
            )
        ],
    )


# ---------------------------------------------------------------------------
# _pair_paper — every honesty gate
# ---------------------------------------------------------------------------


def test_pair_paper_theory_every_gate() -> None:
    outcome = _pair_paper(
        _theory_qp(), _theory_scheme(), qp_stem="0625_s24_qp_41", already_banked=set()
    )

    assert {row.source_question_id for row in outcome.rows} == {
        "0625_s24_qp_41#1a_i",
        "0625_s24_qp_41#1a_ii",
        "0625_s24_qp_41#1b",
    }
    assert outcome.leaves_examined == 7
    assert outcome.skipped_figure == 1  # "1c"
    assert outcome.skipped_no_scheme_match == 2  # "1a" (container) + "1z" (no match)
    assert outcome.skipped_no_marking_points == 0
    assert outcome.skipped_marks_mismatch == 1  # "1e"
    assert outcome.skipped_already_banked == 0
    # extracted 2+3+4+6+0(None)+1+5 = 21 vs stated 20 — a real, honestly
    # reported mismatch (BUILD/BLOCKERS.md B2), not something this fixture
    # was built to avoid.
    assert outcome.reconcile_mismatch is True


def test_pair_paper_reconcile_mismatch_is_reported_not_hidden() -> None:
    qp = _theory_qp()
    # Mutate the stated total so it disagrees with the extracted sum —
    # BUILD/BLOCKERS.md B2: this must be surfaced, never silently tolerated.
    qp = qp.model_copy(
        update={"metadata": qp.metadata.model_copy(update={"stated_total_marks": 999})}
    )
    outcome = _pair_paper(qp, _theory_scheme(), qp_stem="0625_s24_qp_41", already_banked=set())
    assert outcome.reconcile_mismatch is True


def test_pair_paper_already_banked_is_skipped_not_duplicated() -> None:
    already = {"0625_s24_qp_41#1a_i"}
    outcome = _pair_paper(
        _theory_qp(), _theory_scheme(), qp_stem="0625_s24_qp_41", already_banked=already
    )
    refs = {row.source_question_id for row in outcome.rows}
    assert "0625_s24_qp_41#1a_i" not in refs
    assert outcome.skipped_already_banked == 1


def test_pair_paper_no_marking_points_is_skipped() -> None:
    scheme = _theory_scheme()
    # Replace "1b" with a leaf that has zero answer_points — matched, but
    # nothing to mark against.
    scheme.questions[0].parts = [
        p if p.id != "1b" else p.model_copy(update={"answer_points": []})
        for p in scheme.questions[0].parts
    ]
    outcome = _pair_paper(_theory_qp(), scheme, qp_stem="0625_s24_qp_41", already_banked=set())
    assert outcome.skipped_no_marking_points == 1
    assert "0625_s24_qp_41#1b" not in {row.source_question_id for row in outcome.rows}


def test_pair_paper_mcq() -> None:
    outcome = _pair_paper(_mcq_qp(), _mcq_scheme(), qp_stem="0625_s24_qp_11", already_banked=set())
    assert len(outcome.rows) == 1
    row = outcome.rows[0]
    assert row.question_type == "mcq"
    assert row.mcq_answer == "B"
    assert row.mcq_options == ["A kilogram", "B kilonewton", "C kilometre", "D kilojoule"]
    assert row.mark_scheme_points == []
    assert row.total_marks == 1


def test_build_row_topic_is_never_faked() -> None:
    scheme_q = _theory_scheme().questions[0].parts[0].parts[0]  # "1a_i"
    qp_q = _qpq("1a_i", marks=2)
    row = _build_row(qp_q, scheme_q, subject_code="0625", source_question_id="x#1a_i")
    assert row.topic is None  # P4.2, not this task — never guessed here
    assert row.source == QuestionSource.past_paper
    assert row.prompt == qp_q.stem


def test_build_row_mcq_without_options_leaves_mcq_options_none() -> None:
    scheme_q = _mcq_scheme().questions[0]
    qp_q = QuestionPaperQuestion(
        ref="1", stem="stem", options=None, marks=1, page_number=2, has_figure=False
    )
    row = _build_row(qp_q, scheme_q, subject_code="0625", source_question_id="x#1")
    assert row.mcq_options is None
    assert row.mcq_answer == "B"


# ---------------------------------------------------------------------------
# ingest_question_papers_dir — Postgres integration + idempotency
# ---------------------------------------------------------------------------


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def test_ingest_question_papers_dir_is_idempotent(
    pg_sessionmaker: sessionmaker[Session], tmp_path: Path
) -> None:
    qp_dir = tmp_path / "qp"
    schemes_dir = tmp_path / "schemes"
    qp_dir.mkdir()
    schemes_dir.mkdir()

    qp_path = qp_dir / "0625_s24_qp_41.pdf"
    qp_path.write_bytes(b"%PDF-1.4 fake")
    scheme_path = schemes_dir / "0625_s24_ms_41.json"
    scheme_path.write_text(json.dumps(_theory_scheme().model_dump(mode="json")), encoding="utf-8")

    fake_qp = _theory_qp()

    def fake_extractor(path: Path) -> QuestionPaper:
        assert path == qp_path
        return fake_qp

    service = QuestionBankService(pg_sessionmaker)

    first = ingest_question_papers_dir(service, qp_dir, schemes_dir, extractor=fake_extractor)
    assert first.produced == 3
    assert first.papers_scanned == 1
    assert first.papers_no_scheme == 0
    # _theory_qp()'s extracted total (21) disagrees with its stated total
    # (20) — surfaced here at the whole-directory report level too, not
    # just from the paper-level _pair_paper tests above.
    assert first.papers_reconcile_mismatch == 1
    assert first.reconcile_mismatch_papers == ["0625_s24_qp_41.pdf"]

    second = ingest_question_papers_dir(service, qp_dir, schemes_dir, extractor=fake_extractor)
    assert second.produced == 0
    assert second.skipped_already_banked == 3

    ids = service.existing_source_question_ids(source=QuestionSource.past_paper)
    assert ids == {
        "0625_s24_qp_41#1a_i",
        "0625_s24_qp_41#1a_ii",
        "0625_s24_qp_41#1b",
    }


def test_ingest_question_papers_dir_no_scheme_found(
    pg_sessionmaker: sessionmaker[Session], tmp_path: Path
) -> None:
    qp_dir = tmp_path / "qp"
    schemes_dir = tmp_path / "schemes"
    qp_dir.mkdir()
    schemes_dir.mkdir()
    qp_path = qp_dir / "0625_s24_qp_41.pdf"
    qp_path.write_bytes(b"%PDF-1.4 fake")

    def fake_extractor(path: Path) -> QuestionPaper:
        return _theory_qp()

    service = QuestionBankService(pg_sessionmaker)
    report = ingest_question_papers_dir(service, qp_dir, schemes_dir, extractor=fake_extractor)

    assert report.produced == 0
    assert report.papers_no_scheme == 1
    assert report.no_scheme_papers == ["0625_s24_qp_41.pdf"]


def test_ingest_question_papers_dir_malformed_scheme_json_counts_as_no_scheme(
    pg_sessionmaker: sessionmaker[Session], tmp_path: Path
) -> None:
    qp_dir = tmp_path / "qp"
    schemes_dir = tmp_path / "schemes"
    qp_dir.mkdir()
    schemes_dir.mkdir()
    qp_path = qp_dir / "0625_s24_qp_41.pdf"
    qp_path.write_bytes(b"%PDF-1.4 fake")
    (schemes_dir / "0625_s24_ms_41.json").write_text("not valid json", encoding="utf-8")

    def fake_extractor(path: Path) -> QuestionPaper:
        return _theory_qp()

    service = QuestionBankService(pg_sessionmaker)
    report = ingest_question_papers_dir(service, qp_dir, schemes_dir, extractor=fake_extractor)

    assert report.produced == 0
    assert report.papers_no_scheme == 1


def test_ingest_question_papers_dir_extract_failure_is_counted_not_fatal(
    pg_sessionmaker: sessionmaker[Session], tmp_path: Path
) -> None:
    from lemely.runtime.errors import ParseError

    qp_dir = tmp_path / "qp"
    schemes_dir = tmp_path / "schemes"
    qp_dir.mkdir()
    schemes_dir.mkdir()
    bad_path = qp_dir / "0625_s24_qp_41.pdf"
    bad_path.write_bytes(b"%PDF-1.4 fake")
    good_path = qp_dir / "0625_s24_qp_11.pdf"
    good_path.write_bytes(b"%PDF-1.4 fake")
    (schemes_dir / "0625_s24_ms_11.json").write_text(
        json.dumps(_mcq_scheme().model_dump(mode="json")), encoding="utf-8"
    )

    def fake_extractor(path: Path) -> QuestionPaper:
        if path == bad_path:
            raise ParseError("no questions extracted")
        return _mcq_qp()

    service = QuestionBankService(pg_sessionmaker)
    report = ingest_question_papers_dir(service, qp_dir, schemes_dir, extractor=fake_extractor)

    assert report.papers_scanned == 2
    assert report.papers_extract_failed == 1
    assert "0625_s24_qp_41.pdf" in report.extract_failures[0]
    assert report.produced == 1  # the good paper still gets banked


def test_ingest_question_papers_dir_ignores_non_caie_filenames(
    pg_sessionmaker: sessionmaker[Session], tmp_path: Path
) -> None:
    qp_dir = tmp_path / "qp"
    schemes_dir = tmp_path / "schemes"
    qp_dir.mkdir()
    schemes_dir.mkdir()
    (qp_dir / "readme.pdf").write_bytes(b"%PDF-1.4 fake")

    def fake_extractor(path: Path) -> QuestionPaper:
        raise AssertionError("should never be called for a non-CAIE filename")

    service = QuestionBankService(pg_sessionmaker)
    report = ingest_question_papers_dir(service, qp_dir, schemes_dir, extractor=fake_extractor)

    assert report.papers_scanned == 0
