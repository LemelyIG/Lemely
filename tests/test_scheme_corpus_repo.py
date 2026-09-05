"""Postgres integration tests for :class:`~lemely.db.scheme_corpus_repo.SchemeCorpusRepository`

(spec 2026-09-03 §4.3). Skip cleanly when no local Postgres is reachable
(mirrors ``test_auth_token_repo.py`` / ``test_teacher_paper_repo.py``). This is
the first production writer of ``mark_schemes``, and the tests prove the
guarantees the design depends on:

* **``store`` is get-or-create-and-replace, keyed on the paper's identity.**
  Storing the same paper twice replaces its one ``mark_schemes`` row rather
  than accumulating a second one — ``paper_id`` is unique.
* **A subject with no bundled syllabus taxonomy is not stored at all.** This
  is a real, silent branch (``None``), not an error path — a scheme cannot
  be filed under a subject the taxonomy does not know.
* **``find_for`` matches on the caller's *detected* metadata, exactly.** A
  near-miss on paper number, variant, session month, or year must return
  ``None`` (or a different row), never the wrong paper's scheme — marking a
  student's work against the wrong scheme would be silent and wrong. Omitting
  the year is the one deliberate exception: it falls back to the newest
  matching paper.
* **``SchemeCorpusRow.doc``** is the source PDF's basename when one has been
  uploaded, and a stable synthetic name when it has not.
"""

from __future__ import annotations

import uuid
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
    PaperType,
    Question,
    QuestionType,
    SchemeFormat,
)
from lemely.core.loose_schemas import SessionMonth as SchemeSessionMonth
from lemely.core.schemas import ExamMetadata
from lemely.db.base import Base
from lemely.db.models.enums import SessionMonth
from lemely.db.question_bank_repo import (
    PaperIdentity,
    _PaperIdentity,
    _resolve_paper,
    resolve_paper,
)
from lemely.db.scheme_corpus_repo import SchemeCorpusRepository
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


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


# ---------------------------------------------------------------------------
# Builders (real core objects — nothing fabricated; mirrors
# tests/test_web_teacher.py's ``_scheme()``, parameterised on paper identity).
# ---------------------------------------------------------------------------


def _scheme(
    *,
    subject: str = "0625",
    paper: int = 1,
    variant: int = 1,
    month: str = "May/June",
    year: int | None = 2023,
) -> MarkScheme:
    """A minimal, real two-question :class:`MarkScheme` for one paper identity."""
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code=subject,
            paper_number=paper,
            paper_variant=variant,
            session_month=SchemeSessionMonth(month),
            session_year=year,
            paper_type=PaperType.THEORY_CORE,
            maximum_mark=4,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            Question(
                id="1",
                marks=2,
                type=QuestionType.RECALL,
                answer_points=[AnswerPoint(id="p1", point="correct", marks=2)],
            ),
            Question(
                id="2",
                marks=2,
                type=QuestionType.RECALL,
                answer_points=[AnswerPoint(id="p1", point="correct", marks=2)],
            ),
        ],
    )


def _scheme_with_container_question(
    *,
    subject: str = "0625",
    paper: int = 1,
    variant: int = 1,
    month: str = "May/June",
    year: int | None = 2023,
) -> MarkScheme:
    """A paper whose only top-level question is a *container* (``marks=0``)
    wrapping two real sub-parts — mirrors a real CAIE scheme where "3" wraps
    "3a"/"3b" (``Question.marks`` is documented as "Set to 0 for container
    questions that only group sub-parts"). ``sum(q.marks for q in
    scheme.questions)`` reads 0 here; only ``metadata.maximum_mark`` (4)
    carries the real paper total — the divergence this fixture exists to
    exercise.
    """
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code=subject,
            paper_number=paper,
            paper_variant=variant,
            session_month=SchemeSessionMonth(month),
            session_year=year,
            paper_type=PaperType.THEORY_CORE,
            maximum_mark=4,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            Question(
                id="1",
                marks=0,
                type=QuestionType.RECALL,
                parts=[
                    Question(
                        id="1a",
                        marks=2,
                        type=QuestionType.RECALL,
                        answer_points=[AnswerPoint(id="p1", point="correct", marks=2)],
                    ),
                    Question(
                        id="1b",
                        marks=2,
                        type=QuestionType.RECALL,
                        answer_points=[AnswerPoint(id="p1", point="correct", marks=2)],
                    ),
                ],
            )
        ],
    )


def _find(
    *,
    subject: str = "0625",
    paper: int = 1,
    variant: int = 1,
    month: str = "May/June",
    year: int | None = 2023,
) -> ExamMetadata:
    return ExamMetadata(
        subject_code=subject,
        paper_number=paper,
        paper_variant=variant,
        session_month=month,
        session_year=year,
    )


# ---------------------------------------------------------------------------
# store / find_for — the hit path (from the brief).
# ---------------------------------------------------------------------------


def test_store_then_find_by_detected_metadata(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    sid = repo.store(_scheme(), provenance="teacher_upload:deterministic")
    assert sid is not None
    found = repo.find_for(_find())
    assert found is not None and len(found.questions) == 2


def test_store_replaces_the_row_for_the_same_paper(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    first = repo.store(_scheme(), provenance="a")
    second = repo.store(_scheme(), provenance="b")
    assert first == second
    assert len(repo.list_rows()) == 1


def test_find_without_year_prefers_the_newest(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    repo.store(_scheme(year=2022), provenance="x")
    repo.store(_scheme(year=2023), provenance="x")
    found = repo.find_for(_find(year=None))
    assert found is not None and found.metadata.session_year == 2023


def test_unknown_subject_is_not_stored(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    assert repo.store(_scheme(subject="9999"), provenance="x") is None
    assert repo.list_rows() == []


def test_store_uses_metadata_maximum_mark_not_a_naive_top_level_sum(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A container top-level question (``marks=0``) must not undercount the paper.

    ``sum(q.marks for q in scheme.questions)`` reads 0 for
    :func:`_scheme_with_container_question` — the real marks live in the
    top-level question's ``parts`` — so this pins that the stored (and
    round-tripped) ``maximum_mark`` is the cover-page total from
    ``metadata.maximum_mark`` (4), not a re-derived sum that would silently
    diverge from it on exactly this paper shape.
    """
    repo = SchemeCorpusRepository(pg_sessionmaker)
    sid = repo.store(_scheme_with_container_question(), provenance="x")
    assert sid is not None
    rows = repo.list_rows()
    assert len(rows) == 1
    assert rows[0].maximum_mark == 4
    found = repo.find_for(_find())
    assert found is not None and found.metadata.maximum_mark == 4


# ---------------------------------------------------------------------------
# find_for — near-miss cases. Each of these stores exactly one real scheme and
# then queries for a paper that differs from it in exactly one dimension; a
# `find_for` that ignored that dimension would wrongly return the stored
# scheme instead of `None`.
# ---------------------------------------------------------------------------


def test_find_for_different_paper_number_is_a_miss(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    repo.store(_scheme(paper=1), provenance="x")
    assert repo.find_for(_find(paper=2)) is None


def test_find_for_different_variant_is_a_miss(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    repo.store(_scheme(variant=1), provenance="x")
    assert repo.find_for(_find(variant=2)) is None


def test_find_for_different_session_month_is_a_miss(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    repo.store(_scheme(month="May/June"), provenance="x")
    assert repo.find_for(_find(month="Oct/Nov")) is None


def test_find_for_different_year_is_a_miss(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Unlike an *omitted* year, an explicit mismatched year must not fall back."""
    repo = SchemeCorpusRepository(pg_sessionmaker)
    repo.store(_scheme(year=2022), provenance="x")
    assert repo.find_for(_find(year=2023)) is None


def test_find_for_different_subject_is_a_miss(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Same paper/variant/session, different (bundled) subject: still a miss."""
    repo = SchemeCorpusRepository(pg_sessionmaker)
    repo.store(_scheme(subject="0625", paper=1, variant=1), provenance="x")
    repo.store(_scheme(subject="0580", paper=1, variant=1), provenance="x")
    found = repo.find_for(_find(subject="0625"))
    assert found is not None and found.metadata.subject_code == "0625"


def test_find_for_no_stored_scheme_is_none(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    assert repo.find_for(_find()) is None


def test_find_for_fails_closed_on_an_unmapped_session_month(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """An unmapped session month must narrow the match to nothing, not drop the filter.

    Unreachable through the normal constructor — ``ExamMetadata.session_month``
    is a ``Literal`` on a ``StrictModel`` — so this bypasses validation with
    ``model_construct`` to reach the defensive branch directly. A ``find_for``
    that instead dropped the month filter here would match on
    subject/paper/variant alone and could return a scheme from the wrong
    session — the wrong-scheme outcome this repository must never produce.
    """
    repo = SchemeCorpusRepository(pg_sessionmaker)
    repo.store(_scheme(), provenance="x")
    bogus = ExamMetadata.model_construct(
        subject_code="0625",
        paper_number=1,
        paper_variant=1,
        session_month="Not/AMonth",  # type: ignore[arg-type]
        session_year=2023,
        source_document=None,
    )
    assert repo.find_for(bogus) is None


# ---------------------------------------------------------------------------
# SchemeCorpusRow — both `doc` branches.
# ---------------------------------------------------------------------------


def test_row_doc_defaults_to_a_synthetic_name_without_a_source_document(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    repo.store(_scheme(subject="0625", paper=1, variant=1), provenance="x")
    rows = repo.list_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.doc == "0625_11.json"
    assert row.paper_number == 1
    assert row.paper_variant == 1
    assert row.session_month == SessionMonth.may_june
    assert row.session_year == 2023
    assert row.maximum_mark == 4
    assert row.question_count == 2


def test_row_doc_is_the_source_document_basename_once_set(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    sid = repo.store(_scheme(), provenance="x")
    assert sid is not None
    repo.set_source_document(sid, "schemes/abc123/0625_s23_ms_11.pdf")
    rows = repo.list_rows()
    assert rows[0].doc == "0625_s23_ms_11.pdf"


def test_set_source_document_on_unknown_id_is_a_silent_no_op(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    repo.set_source_document(uuid.uuid4(), "schemes/nope.pdf")
    assert repo.list_rows() == []


def test_list_rows_is_empty_for_a_fresh_corpus(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    assert repo.list_rows() == []


def test_list_rows_newest_first(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = SchemeCorpusRepository(pg_sessionmaker)
    repo.store(_scheme(paper=1), provenance="x")
    repo.store(_scheme(paper=2), provenance="x")
    rows = repo.list_rows()
    assert [r.paper_number for r in rows] == [2, 1]


# ---------------------------------------------------------------------------
# The question_bank_repo rename (Task 7): old private names must keep working
# as plain aliases of the new public ones, for any caller that imported them
# under the old names.
# ---------------------------------------------------------------------------


def test_renamed_paper_helpers_keep_their_old_names_as_aliases() -> None:
    assert _PaperIdentity is PaperIdentity
    assert _resolve_paper is resolve_paper
