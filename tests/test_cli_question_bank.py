"""CLI-level tests for ``lemely question-bank`` (P3.5 chunk B).

Real Postgres (a throwaway database, mirroring ``test_review_repo.py``),
invoked through :class:`click.testing.CliRunner` exactly as a user would run
these commands — env vars point the CLI's own ``load_settings()`` at the
throwaway database and a tmp output directory, nothing inside the CLI
command functions is mocked.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from lemely.app.cli import cli
from lemely.core.loose_schemas import MarkScheme as LooseMarkScheme
from lemely.db.base import Base
from lemely.db.models import Paper, Subject
from lemely.db.models.academic import MarkScheme as MarkSchemeRecord
from lemely.db.models.enums import SessionMonth
from lemely.db.session import dispose_engine
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


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
def pg_url() -> Iterator[str]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    # NB: str(URL) masks the password ("***") by default in SQLAlchemy 2.0 —
    # render_as_string(hide_password=False) is required to get a URL the CLI
    # subprocess can actually authenticate with via LEMELY_DATABASE__URL.
    db_url = make_url(base_url).set(database=dbname).render_as_string(hide_password=False)
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    dispose_engine()
    try:
        yield db_url
    finally:
        dispose_engine()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _env(pg_url: str, output_dir: Path) -> dict[str, str]:
    return {
        "LEMELY_DATABASE__URL": pg_url,
        "LEMELY_PATHS__OUTPUT_DIR": str(output_dir),
    }


def test_survey_command_reports_honest_zero_on_empty_corpus(pg_url: str, tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--json", "question-bank", "survey-past-papers"], env=_env(pg_url, tmp_path)
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["markSchemesScanned"] == 0
    assert payload["leafQuestionsSeen"] == 0
    assert payload["produced"] == 0
    assert "0 past-paper questions produced" in payload["explanation"]


def test_survey_command_prints_real_nonzero_leaf_counts_not_an_empty_table(
    pg_url: str, tmp_path: Path
) -> None:
    engine = create_engine(pg_url)
    payload = LooseMarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "theory_core",
                "maximum_mark": 1,
                "scheme_format": "mixed",
            },
            "questions": [{"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"}],
        }
    ).model_dump(mode="json")
    sm = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with sm.begin() as session:
        session.add(Subject(code="0625", name="Physics"))
        session.flush()
        paper = Paper(
            subject_code="0625",
            session_month=SessionMonth.may_june,
            session_year=2020,
            paper_number=1,
            paper_variant=2,
        )
        session.add(paper)
        session.flush()
        session.add(MarkSchemeRecord(paper_id=paper.id, maximum_mark=1, parsed_payload=payload))
    engine.dispose()

    runner = CliRunner()
    result = runner.invoke(cli, ["question-bank", "survey-past-papers"], env=_env(pg_url, tmp_path))
    assert result.exit_code == 0, result.output
    assert "Mark schemes scanned: 1" in result.output
    assert "Leaf questions seen: 1" in result.output
    assert "Produced: 0" in result.output
    assert "0 past-paper questions produced" in result.output
    # Not an empty table — the explanation text is always present, zero or not.
    assert "structural" in result.output


def test_import_generated_command_reports_real_counts(pg_url: str, tmp_path: Path) -> None:
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir()
    (questions_dir / "quiz.json").write_text(
        json.dumps(
            {
                "subject_code": "0625",
                "questions": [
                    {
                        "topic": "Waves",
                        "difficulty": "standard",
                        "prompt": "Explain a transverse wave.",
                        "model_answer": "Perpendicular oscillation.",
                        "mark_scheme_points": ["perpendicular"],
                        "total_marks": 2,
                        "source_question_ids": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--json", "question-bank", "import-generated"], env=_env(pg_url, tmp_path)
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["filesRead"] == 1
    assert payload["rowsCreated"] == 1
    assert payload["skipped"] == []


def test_import_generated_command_missing_directory_is_honest_zero(
    pg_url: str, tmp_path: Path
) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["question-bank", "import-generated"], env=_env(pg_url, tmp_path))
    assert result.exit_code == 0, result.output
    assert "Files read: 0" in result.output
    assert "Rows created: 0" in result.output
    assert "Skipped (malformed): 0" in result.output
