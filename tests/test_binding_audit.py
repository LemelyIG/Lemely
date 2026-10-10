"""Tests for the read-only stored-attempt binding audit (``lemely audit-bindings``).

The checks and the report are tested on plain stand-ins for stored rows, built from
the recorded 0625/41 fixtures, so they need no database. The command-level
read-only test uses a spy session and also needs none. The two tests that run real
queries against Postgres skip when no local Postgres is reachable.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from click.testing import CliRunner
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.app.cli import cli
from lemely.core.loose_schemas import MarkScheme, Question
from lemely.db.base import Base
from lemely.db.binding_audit import (
    audit_attempt,
    audit_attempts,
    exam_metadata,
    is_judgeable,
    is_suspect,
    load_attempts,
)
from lemely.db.models.attempts import Attempt, QuestionResult, Upload
from lemely.db.models.enums import AttemptOrigin, MarkerSource, Role, SessionMonth
from lemely.db.models.enums import ConfidenceBand as DbConfidenceBand
from lemely.db.models.users import User
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "binding" / "0625_w24_41"


@pytest.fixture(scope="module")
def scheme() -> MarkScheme:
    path = ROOT / "corpus" / "mark-schemes" / "0625_w24_ms_41.json"
    return MarkScheme.model_validate(json.loads(path.read_text()))


def _rows(name: str) -> list[SimpleNamespace]:
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    return [
        SimpleNamespace(question_id=a["question_id"], student_answer=a["answer"])
        for a in data["answers"]
    ]


def _attempt(
    name: str,
    *,
    subject_code: str | None = "0625",
    paper_number: int | None = 4,
    paper_variant: int | None = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        subject_code=subject_code,
        paper_number=paper_number,
        paper_variant=paper_variant,
        session_month=SessionMonth.oct_nov,
        session_year=2024,
        awarded_marks=2,
        maximum_marks=80,
        recorded_at=datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
        question_results=_rows(name),
    )


def test_audit_flags_a_shifted_attempt(scheme: MarkScheme) -> None:
    checks = audit_attempt(_rows("full_shift_lite"), scheme)
    assert is_suspect(checks)
    failed = [c for c in checks if not c.passed and c.scope == "paper"]
    assert [c.id for c in failed] == ["G7"]
    assert {c.id for c in checks} == {"G6", "G7"}


def test_audit_passes_an_aligned_attempt(scheme: MarkScheme) -> None:
    checks = audit_attempt(_rows("aligned"), scheme)
    assert not is_suspect(checks)
    assert all(c.passed for c in checks)


def test_audit_ignores_blank_answers(scheme: MarkScheme) -> None:
    rows = [*_rows("aligned"), SimpleNamespace(question_id="7c", student_answer=None)]
    rows.append(SimpleNamespace(question_id="7b", student_answer="  "))
    assert not is_suspect(audit_attempt(rows, scheme))


def test_is_suspect_ignores_question_scope_failures() -> None:
    from lemely.core.binding import BindingCheck

    minor = BindingCheck(id="G7", passed=False, scope="question", question_ids=["1"], detail="x")
    major = BindingCheck(id="G7", passed=False, scope="paper", question_ids=["1"], detail="x")
    ok = BindingCheck(id="G6", passed=True, scope="paper", detail="x")
    assert not is_suspect([ok, minor])
    assert is_suspect([ok, minor, major])


def test_audit_skips_attempts_whose_scheme_cannot_be_resolved_and_counts_them(
    scheme: MarkScheme,
) -> None:
    attempts = [
        _attempt("full_shift_lite"),
        _attempt("aligned", paper_variant=2),
        _attempt("aligned", subject_code=None),
        _attempt("aligned"),
    ]

    def find(meta: Any) -> MarkScheme | None:
        return scheme if (meta.paper_number, meta.paper_variant) == (4, 1) else None

    report = audit_attempts(attempts, find)
    assert report.audited == 2
    assert report.scheme_not_found == 2
    assert len(report.suspects) == 1
    assert report.suspects[0].attempt_id == str(attempts[0].id)


def test_audit_counts_attempts_the_checks_cannot_judge() -> None:
    def leaf(qid: str, value: str | None) -> Question:
        body: dict[str, Any] = {"id": qid, "marks": 1, "type": "recall"}
        if value:
            body["answer_points"] = [{"id": "p1", "marks": 1, "point": value}]
        return Question.model_validate(body)

    thin = MarkScheme.model_construct(questions=[leaf("1", "5"), leaf("2", "Explain in words")])
    assert not is_judgeable(thin)
    attempts = [_attempt("aligned"), _attempt("aligned")]
    report = audit_attempts(attempts, lambda _meta: thin)
    assert (report.audited, report.not_judgeable) == (2, 2)


def test_a_judgeable_scheme_is_not_counted(scheme: MarkScheme) -> None:
    assert is_judgeable(scheme)
    report = audit_attempts([_attempt("aligned")], lambda _meta: scheme)
    assert (report.audited, report.not_judgeable) == (1, 0)


def test_question_scope_only_attempts_are_counted_not_listed(scheme: MarkScheme) -> None:
    # partial_a shifts three answers or fewer: nothing at paper scope, so it is counted
    # separately when the checks see a short run.
    attempt = _attempt("partial_a")
    report = audit_attempts([attempt], lambda _meta: scheme)
    checks = audit_attempt(attempt.question_results, scheme)
    only_minor = not is_suspect(checks) and any(not c.passed for c in checks)
    assert report.question_scope_only == (1 if only_minor else 0)
    assert len(report.suspects) == (1 if is_suspect(checks) else 0)


def test_exam_metadata_maps_the_stored_columns() -> None:
    meta = exam_metadata(_attempt("aligned"))
    assert meta is not None
    assert (meta.subject_code, meta.paper_number, meta.paper_variant) == ("0625", 4, 1)
    assert (meta.session_month, meta.session_year) == ("Oct/Nov", 2024)
    assert exam_metadata(_attempt("aligned", paper_number=None)) is None


# --- the command ------------------------------------------------------------


class _SpySession:
    """A session that records every call; any write-shaped call fails the test."""

    def __init__(self, attempts: list[Any]) -> None:
        self._attempts = attempts
        self.calls: list[str] = []

    def scalars(self, _stmt: object) -> SimpleNamespace:
        self.calls.append("scalars")
        return SimpleNamespace(all=lambda: self._attempts)

    def close(self) -> None:
        self.calls.append("close")

    def __getattr__(self, name: str) -> Any:
        if name in {"add", "add_all", "commit", "flush", "delete", "merge", "execute", "begin"}:

            def record(*_a: object, **_k: object) -> None:
                self.calls.append(name)

            return record
        raise AttributeError(name)


def _patch(monkeypatch: pytest.MonkeyPatch, session: _SpySession, scheme: MarkScheme) -> None:
    monkeypatch.setattr("lemely.db.session.get_sessionmaker", lambda _settings: lambda: session)
    monkeypatch.setattr(
        "lemely.db.scheme_corpus_repo.SchemeCorpusRepository.__init__",
        lambda self, _sm: None,
    )
    monkeypatch.setattr(
        "lemely.db.scheme_corpus_repo.SchemeCorpusRepository.find_for",
        lambda _self, meta: scheme if meta.paper_variant == 1 else None,
    )


def test_audit_command_is_read_only(monkeypatch: pytest.MonkeyPatch, scheme: MarkScheme) -> None:
    session = _SpySession([_attempt("full_shift_lite"), _attempt("aligned")])
    _patch(monkeypatch, session, scheme)
    result = CliRunner().invoke(cli, ["audit-bindings"])
    assert result.exit_code == 0, result.output
    assert session.calls == ["scalars", "close"]


def test_audit_command_text_output(monkeypatch: pytest.MonkeyPatch, scheme: MarkScheme) -> None:
    shifted = _attempt("full_shift_lite")
    session = _SpySession([shifted, _attempt("aligned"), _attempt("aligned", paper_variant=2)])
    _patch(monkeypatch, session, scheme)
    result = CliRunner().invoke(cli, ["audit-bindings"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert f"attempt {shifted.id}" in out
    assert f"user {shifted.user_id}" in out
    assert "0625/41 Oct/Nov 2024" in out
    assert "2/80" in out
    assert "failed G7" in out
    assert "hold the value expected of the previous question" in out
    assert "Suspect attempts: 1" in out
    assert "Audited: 2" in out
    assert "Skipped, mark scheme not found: 1" in out
    assert "(too few numeric answers for the shift check): 0" in out
    assert "Not listed does not mean correctly bound" in out


def test_audit_command_json_output(monkeypatch: pytest.MonkeyPatch, scheme: MarkScheme) -> None:
    shifted = _attempt("full_shift_lite")
    session = _SpySession([shifted, _attempt("aligned"), _attempt("aligned", paper_variant=2)])
    _patch(monkeypatch, session, scheme)
    result = CliRunner().invoke(cli, ["--json", "audit-bindings"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {
        "suspects",
        "question_scope_only",
        "audited",
        "not_judgeable",
        "scheme_not_found",
    }
    assert (payload["audited"], payload["scheme_not_found"], payload["not_judgeable"]) == (2, 1, 0)
    assert payload["question_scope_only"] == 0
    (suspect,) = payload["suspects"]
    assert suspect["attempt_id"] == str(shifted.id)
    assert suspect["user_id"] == str(shifted.user_id)
    assert suspect["failed_checks"] == ["G7"]
    assert (suspect["awarded_marks"], suspect["maximum_marks"]) == (2, 80)


def test_audit_command_rejects_a_bad_date() -> None:
    result = CliRunner().invoke(cli, ["audit-bindings", "--since", "last week"])
    assert result.exit_code != 0


# --- real queries (skip without Postgres) -------------------------------------


def _server_reachable(url: str) -> bool:
    engine = create_engine(make_url(url).set(database="postgres"))
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
    admin = create_engine(make_url(base_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
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


def _seed(
    sm: sessionmaker[Session],
    *,
    origin: AttemptOrigin,
    with_upload: bool,
    recorded_at: datetime,
    answers: list[tuple[str, str]],
) -> uuid.UUID:
    user_id, attempt_id = uuid.uuid4(), uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=user_id, email=f"{user_id}@example.com", role=Role.student))
        session.flush()
        upload_id = None
        if with_upload:
            upload_id = uuid.uuid4()
            session.add(Upload(id=upload_id, user_id=user_id, storage_path="scan.pdf"))
            session.flush()
        session.add(
            Attempt(
                id=attempt_id,
                user_id=user_id,
                upload_id=upload_id,
                subject_code="0625",
                session_month=SessionMonth.oct_nov,
                session_year=2024,
                paper_number=4,
                paper_variant=1,
                awarded_marks=2,
                maximum_marks=80,
                percentage=2.5,
                recorded_at=recorded_at,
                origin=origin,
            )
        )
        session.flush()
        for qid, text in answers:
            session.add(
                QuestionResult(
                    attempt_id=attempt_id,
                    question_id=qid,
                    awarded_marks=0,
                    maximum_marks=1,
                    confidence_band=DbConfidenceBand.high,
                    confidence_score=1.0,
                    marker_source=MarkerSource.ai,
                    student_answer=text,
                )
            )
    return attempt_id


def test_load_attempts_filters_by_origin_date_and_limit(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    old = datetime(2026, 1, 1, tzinfo=UTC)
    new = datetime(2026, 10, 1, tzinfo=UTC)
    scanned = _seed(
        sm,
        origin=AttemptOrigin.past_paper,
        with_upload=True,
        recorded_at=new,
        answers=[("1a_i", "5")],
    )
    _seed(sm, origin=AttemptOrigin.quiz, with_upload=False, recorded_at=new, answers=[])
    typed = _seed(
        sm, origin=AttemptOrigin.past_paper, with_upload=False, recorded_at=new, answers=[]
    )
    older = _seed(
        sm, origin=AttemptOrigin.past_paper, with_upload=True, recorded_at=old, answers=[]
    )
    with sm() as session:
        got = [a.id for a in load_attempts(session)]
        assert got == [scanned, older]
        assert [a.id for a in load_attempts(session, since=datetime(2026, 6, 1, tzinfo=UTC))] == [
            scanned
        ]
        assert [a.id for a in load_attempts(session, limit=1)] == [scanned]
        everything = {a.id for a in load_attempts(session, uploaded_only=False)}
        assert typed in everything
        assert len(everything) == 4
        assert len(next(a for a in load_attempts(session) if a.id == scanned).question_results) == 1


def test_audit_changes_nothing_in_a_real_database(
    pg_sessionmaker: sessionmaker[Session], scheme: MarkScheme
) -> None:
    sm = pg_sessionmaker
    answers = [(r.question_id, r.student_answer) for r in _rows("full_shift_lite")]
    _seed(
        sm,
        origin=AttemptOrigin.past_paper,
        with_upload=True,
        recorded_at=datetime(2026, 10, 1, tzinfo=UTC),
        answers=answers,
    )
    writes: list[str] = []
    event.listen(sm, "before_commit", lambda _s: writes.append("commit"))
    event.listen(
        sm,
        "before_flush",
        lambda s, _ctx, _inst: writes.append("flush") if (s.new or s.dirty or s.deleted) else None,
    )
    with sm() as session:
        report = audit_attempts(load_attempts(session), lambda _meta: scheme)
    assert len(report.suspects) == 1
    assert writes == []
