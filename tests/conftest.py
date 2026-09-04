"""Shared pytest fixtures and test-environment isolation.

The test suite assumes a clean configuration environment: many tests exercise
"no API key" / "defaults only" code paths and construct :class:`Settings`
directly. Pydantic-settings, however, reads a repo-root ``.env`` file
(``env_file=".env"``) at every instantiation. A developer who keeps a real
``.env`` (with ``GEMINI_API_KEY`` / ``LEMELY_GEMINI_API_KEY``) for local runs
would otherwise see those secrets leak into the suite and flip "without key"
assertions. CI has no ``.env`` and is unaffected either way.

This autouse fixture neutralises that single source for the whole session by
disabling ``.env`` file discovery in ``Settings.model_config``. It does NOT
touch ``os.environ`` — tests that need specific env vars still set them, and the
shell's exported vars (if any) still apply, exactly as in CI.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import lemely.runtime.config as config_module
from lemely.runtime.config import Settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="session", autouse=True)
def _disable_dotenv_file() -> Iterator[None]:
    original = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    try:
        yield
    finally:
        Settings.model_config["env_file"] = original


@pytest.fixture(scope="session", autouse=True)
def _forbid_live_gemini_calls() -> Iterator[None]:
    """Make a real Gemini API call impossible for the whole suite.

    MISSION §8 requires every automated test to mock Gemini; live calls are
    permitted only for controlled accuracy validation under the budget
    protocol. Nothing enforced that, and the ``.env``-neutralising fixture
    above deliberately leaves ``os.environ`` alone — so running the gates the
    documented way (``set -a && . ./.env``) put a real key in the environment
    and a study-plan narration test in ``tests/test_web_student.py`` made a
    **billed** ``gemini-2.5-flash`` call against the hard $8 cap, then failed
    on the 200 it got back instead of the expected 503. (That test and the
    route it covered were retired in P4.10 chunk D — D4.22 — but the guard is
    suite-wide and protects every unmocked path, so it stays.)

    Guarding at client *construction* rather than at the key is deliberate:
    tests that legitimately exercise "a key is configured" inject a fake
    client (``_genai_client=...``) or a ``MagicMock`` and never reach here, so
    they keep working. Only an unmocked path that would actually open a
    socket trips this — and it trips loudly rather than spending money.
    """
    import lemely.io.gemini as gemini_module

    original = gemini_module.GeminiClient._client.fget  # type: ignore[attr-defined]

    def _guarded(self: object) -> object:
        if getattr(self, "_raw_client", None) is None:
            raise RuntimeError(
                "A test tried to construct a real google-genai client. Automated "
                "tests must mock Gemini (MISSION §8) — inject _genai_client=... or "
                "patch the call site. Live calls belong in the accuracy harness."
            )
        return original(self)

    gemini_module.GeminiClient._client = property(_guarded)  # type: ignore[method-assign]
    try:
        yield
    finally:
        gemini_module.GeminiClient._client = property(original)  # type: ignore[method-assign]


class RepoLedgerWriteAttempted(BaseException):
    """Raised when a test tries to write the repo's real spend ledger.

    Derives from :class:`BaseException`, not :class:`Exception`, so that broad
    ``except Exception`` handlers in production code cannot swallow it and turn
    a blocked write into a silently-passing test. See
    :func:`_forbid_repo_ledger_writes` for the incident that forced this.
    """


@pytest.fixture(scope="session", autouse=True)
def _forbid_repo_ledger_writes() -> Iterator[None]:
    """Make it impossible for a test to write the real ``outputs/gemini_spend.json``.

    :class:`~lemely.io.cost_ledger.CostLedger` is a plain read-modify-write file
    store with no notion of "test" vs "real" — it will happily create and
    append to whatever path it is given. A test that builds ``Settings`` via
    ``model_copy(update={"paths": PathsSettings(cache_dir=...)})`` (naming only
    ``cache_dir``) silently replaces the *entire* ``paths`` model, since
    ``PathsSettings`` is a pydantic ``BaseModel`` and ``model_copy`` does not
    merge nested models field-by-field. ``output_dir`` then falls back to its
    relative default (``"outputs"``), which resolves under whatever the
    process's cwd happens to be — the real repo root under pytest — so a
    synthetic, mocked-Gemini test spend lands in the actual spend ledger that
    the accuracy programme's cost tracking depends on. See
    ``tests/test_gemini_client.py``'s ``_make_settings`` helper for the
    correct pattern: pass ``output_dir`` alongside ``cache_dir`` explicitly.

    This guards :meth:`CostLedger._write` specifically, not ``__init__`` or
    ``total()``. ``CostLedger.__init__`` is documented side-effect-free
    (``cost_ledger.py`` — constructing one only stores the path), and
    ``total()`` only reads, so neither can move the real ledger; only ``_write``
    can, so only ``_write`` needs to be intercepted. Guarding earlier (e.g. at
    construction) would also incorrectly reject legitimate reads of the real
    ledger path if any ever occurred.

    The repo root is computed from ``Path(__file__)`` rather than ``Path.cwd()``
    because ``cwd()`` is exactly the ambient, unreliable value this bug already
    exploited — a subprocess, a ``pytest`` invocation from a different
    directory, or a runner that ``chdir``s would all change ``cwd()`` without
    changing which repo we're actually in. ``Path(__file__).resolve().parent.parent``
    is fixed at import time and always names *this* repo's root, regardless of
    where the test process is launched from.

    Both the candidate path and the repo root are passed through
    :meth:`Path.resolve` before the :meth:`Path.is_relative_to` check. This is
    deliberate: a tmp directory handed to a test (e.g. via ``tempfile.mkdtemp``)
    may itself be reached through a symlink (macOS puts ``/tmp`` under
    ``/private/tmp``), and an unresolved comparison could either false-positive
    (flagging a legitimate tmp path that merely shares a symlinked prefix with
    the repo) or false-negative (missing a real repo-internal path expressed
    through a symlink). Resolving both sides first makes the containment check
    exact.

    Finally, the guard raises :class:`RepoLedgerWriteAttempted`, which derives
    from :class:`BaseException` rather than :class:`Exception`. That is not
    stylistic — it is the whole difference between a guard and a decoration.
    An earlier revision raised ``RuntimeError`` and was caught in the wild:
    ``correct_paper``'s broad ``except Exception`` handler
    (``lemely/io/correction_ai.py``) swallowed it, logged ``ai_marking_failed``,
    and fell through to ``_build_missing_corrected``. The real ledger was
    protected, but ``test_quiz_marking_repo.py``'s low-confidence test stayed
    **green while silently exercising the error-fallback path instead of the
    ``confidence=0.5`` path it documents** — the guard had converted a visible
    data-corruption bug into an invisible test-integrity one. Deriving from
    ``BaseException`` puts the guard outside every ``except Exception`` *on the
    same call stack*, so a masked write becomes a hard, immediate test failure
    that names its own cause. This mirrors how ``KeyboardInterrupt`` and
    pytest's own ``Failed`` avoid being eaten by application error handling.

    Two limits of this guard, stated here rather than left to be rediscovered:

    1. **It does not cross a thread boundary by itself.** Two ledger-writing
       paths run off-thread — ``_trigger_marking_in_background``
       (``lemely/web/routers/quiz.py``) and ``_grading_pool``
       (``lemely/web/routers/teacher.py``), neither of which calls
       ``Future.result()``. An exception raised there surfaces only as
       ``PytestUnhandledThreadExceptionWarning``. That warning is promoted to
       an error in ``pyproject.toml``'s ``filterwarnings`` precisely so this
       guard stays loud across those two paths; without that promotion the
       write would be blocked but invisible. No test reaches a real
       ``CostLedger`` through either path today (both override the marking
       service), but the promotion is what keeps that true by accident-proof
       means rather than by luck.
    2. **It guards the ledger only, not ``output_dir`` generally.** The same
       ``paths.output_dir`` also feeds ``HistoryStore``, ``outputs/uploads/``
       and ``outputs/schemes/``, none of which are guarded, and ``outputs/``
       is gitignored (``.gitignore:46``) so repo-internal writes there are
       invisible to a dirty-tree check — which is exactly why this bug
       survived so long. Measured: the web/CLI fixtures that reach those
       consumers all set ``output_dir`` into ``tmp_path`` explicitly, and a
       before/after ``find outputs`` over the relevant modules shows no
       change, so the narrowing is safe today. It is not a general guarantee.
    """
    import lemely.io.cost_ledger as cost_ledger_module

    repo_root = Path(__file__).resolve().parent.parent
    original = cost_ledger_module.CostLedger._write

    def _guarded_write(
        self: cost_ledger_module.CostLedger, cumulative_usd: float, warnings_sent: list[float]
    ) -> None:
        resolved = self._path.resolve()
        if resolved.is_relative_to(repo_root):
            raise RepoLedgerWriteAttempted(
                f"A test tried to write the real spend ledger at {resolved}. "
                "Automated tests must never touch the repo's real "
                "outputs/gemini_spend.json — pass output_dir=Path(tmp) / "
                "'outputs' into PathsSettings alongside cache_dir (see "
                "tests/test_gemini_client.py's _make_settings helper)."
            )
        return original(self, cumulative_usd, warnings_sent)

    cost_ledger_module.CostLedger._write = _guarded_write  # type: ignore[method-assign]
    try:
        yield
    finally:
        cost_ledger_module.CostLedger._write = original  # type: ignore[method-assign]


@pytest.fixture(scope="session", autouse=True)
def _disable_ambient_toml() -> Iterator[None]:
    """Neutralise *ambient* ``lemely.toml`` discovery for the whole session.

    A developer's local ``lemely.toml`` — at the real repo root (``Path.cwd()``)
    or in ``~/.config/lemely/`` — would otherwise leak into ``load_settings()``
    calls that pass no explicit ``toml_path``/``cwd``, flipping defaults-only
    assertions. This wrapper suppresses discovery of those two ambient files but
    still discovers a ``lemely.toml`` inside a caller-supplied temporary ``cwd``
    (as the TOML-discovery test does) and never touches explicit ``toml_path``.
    """
    from pathlib import Path as _Path

    original = config_module._discover_toml
    real_root_toml = (_Path.cwd() / "lemely.toml").resolve()

    def _guarded_discovery(cwd: Path) -> Path | None:
        found = original(cwd)
        if found is None:
            return None
        resolved = found.resolve()
        # Suppress the real repo-root toml and any home-config toml (ambient
        # developer config); allow temp-cwd tomls that tests create explicitly.
        if resolved == real_root_toml or "lemely" in resolved.parent.parts[-2:]:
            return None
        return found

    config_module._discover_toml = _guarded_discovery  # type: ignore[assignment]
    try:
        yield
    finally:
        config_module._discover_toml = original  # type: ignore[assignment]


@pytest.fixture(scope="session", autouse=True)
def _seed_ambient_grade_boundaries() -> Iterator[None]:
    """Seed `component_thresholds` on the *ambient* database (once, session-wide).

    `GradeBoundaryStore()` (no sessionmaker argument -- used all over the web
    layer: `review_repo.py`, `student.py`, `parent.py`, `web/services/grading.py`,
    `app/cli.py`, `web/deps.py`) always resolves against `get_sessionmaker()`,
    the ambient database from `DatabaseSettings().url` -- never a test's own
    throwaway `pg_sessionmaker`/`migrated_sessionmaker` database. In CI (and any
    freshly migrated Postgres) that database's `component_thresholds` starts
    empty: `python scripts/ingest_thresholds.py` (docs/deployment.md §3.5) is a
    live scrape against ciegt.pooruli.com plus the official Cambridge PDFs,
    deliberately NOT run by a migration and unsuitable to run in CI (network
    dependency, "politeness" pacing, three parallel matrix jobs hammering one
    small site). Without *something* seeding that database, every code path
    above raises `EmptyGradeBoundaryStoreError` on its very first call, in any
    fresh environment -- which is exactly what broke CI on
    feature/backend-served-reference-data (component_thresholds' own migration)
    and every branch built on develop since.

    The rows below are clearly-fake fixture data (`example.invalid` source
    URLs) standing in for that ingest, mirroring facts already documented
    elsewhere in this codebase so behaviour that depends on them stays correct:

    - 0625 paper 1 is Core-tier only (C-G, no A/B) on every recent session --
      see `lemely.io.grade_boundaries._load`'s own docstring and
      `test_web_parent.py::test_a_core_paper_has_no_reachable_grade_above_its_own_ceiling`.
    - 0625 paper 2 variant 2, May/June 2020 carries an A boundary -- the exact
      session `test_student_correct.py::_mcq_scheme_extended` resolves, whose
      docstring explains why paper 1 (Core, capped at C) cannot stand in for it.
    - `component_thresholds` never carries A* -- see
      `lemely.db.models.thresholds.ComponentThreshold`'s docstring ("Grade A*
      does not exist at this level").

    A third, otherwise-unused subject code carries a full A-G range so the
    global-default rung (every code path that resolves a subject/paper this
    fixture does not know about) has more than a Core-only vocabulary to draw
    on.

    Reachability is checked the same way `pg_sessionmaker` fixtures already do
    across the router test files: unreachable Postgres means every one of
    those tests already skips on its own, so this fixture just returns without
    seeding rather than failing collection for the whole session.
    """
    import sqlalchemy as sa
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError

    from lemely.db.models.enums import SessionMonth
    from lemely.db.models.thresholds import ComponentThreshold
    from lemely.db.session import get_sessionmaker
    from lemely.io.grade_boundaries import invalidate_reference_cache
    from lemely.runtime.config import DatabaseSettings

    base_url = DatabaseSettings().url
    server_url = make_url(base_url).set(database="postgres")
    try:
        probe = create_engine(server_url)
        with probe.connect():
            pass
        probe.dispose()
    except OperationalError:
        yield
        return

    sm = get_sessionmaker()
    seeded_ids: list[object] = []
    try:
        with sm() as session:
            rows = [
                ComponentThreshold(
                    subject_code="0625",
                    session_month=SessionMonth.may_june,
                    session_year=2023,
                    paper_number=1,
                    paper_variant=1,
                    max_mark=40,
                    thresholds={"C": 25, "D": 22, "E": 19, "F": 16, "G": 13},
                    verified=True,
                    source_url="https://example.invalid/test-fixture/0625_s23_p11.pdf",
                ),
                ComponentThreshold(
                    subject_code="0625",
                    session_month=SessionMonth.may_june,
                    session_year=2024,
                    paper_number=1,
                    paper_variant=1,
                    max_mark=40,
                    thresholds={"C": 26, "D": 23, "E": 20, "F": 17, "G": 14},
                    verified=True,
                    source_url="https://example.invalid/test-fixture/0625_s24_p11.pdf",
                ),
                ComponentThreshold(
                    subject_code="0625",
                    session_month=SessionMonth.may_june,
                    session_year=2020,
                    paper_number=2,
                    paper_variant=2,
                    max_mark=40,
                    thresholds={"A": 30, "B": 26, "C": 22, "D": 18, "E": 14, "F": 10, "G": 6},
                    verified=True,
                    source_url="https://example.invalid/test-fixture/0625_s20_p22.pdf",
                ),
                ComponentThreshold(
                    subject_code="0000",
                    session_month=SessionMonth.may_june,
                    session_year=2024,
                    paper_number=1,
                    paper_variant=1,
                    max_mark=100,
                    thresholds={"A": 80, "B": 70, "C": 60, "D": 50, "E": 40, "F": 30, "G": 20},
                    verified=True,
                    source_url="https://example.invalid/test-fixture/0000_s24_p11.pdf",
                ),
            ]
            session.add_all(rows)
            session.commit()
            seeded_ids = [row.id for row in rows]
    except sa.exc.SQLAlchemyError:
        # `component_thresholds` not migrated yet, or some other setup gap --
        # leave the ambient database untouched and let downstream tests fail
        # or skip on their own, as they did before this fixture existed.
        yield
        return

    invalidate_reference_cache()
    try:
        yield
    finally:
        try:
            with sm() as session:
                session.execute(
                    sa.delete(ComponentThreshold).where(ComponentThreshold.id.in_(seeded_ids))
                )
                session.commit()
        except sa.exc.SQLAlchemyError:
            pass
        invalidate_reference_cache()


@pytest.fixture
def migrated_sessionmaker() -> Iterator[sessionmaker[Session]]:
    """A throwaway Postgres database with `alembic upgrade head` applied.

    Distinct from the `pg_sessionmaker` fixtures in the router tests, which use
    `Base.metadata.create_all` and therefore never execute a migration's data
    steps. Anything asserting what a migration *inserted* needs this one.
    """
    import os as _os
    import uuid as _uuid

    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from lemely.runtime.config import DatabaseSettings

    base_url = DatabaseSettings().url
    server_url = make_url(base_url).set(database="postgres")
    try:
        probe = create_engine(server_url)
        with probe.connect():
            pass
        probe.dispose()
    except OperationalError:
        pytest.skip("local Postgres not reachable")

    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_mig_{_uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    url = make_url(base_url).set(database=dbname)

    cfg = Config("alembic.ini")
    rendered_url = url.render_as_string(hide_password=False)
    cfg.set_main_option("sqlalchemy.url", rendered_url)
    # `lemely/db/migrations/env.py` deliberately re-derives the URL from
    # `load_settings().database.url` rather than trusting whatever
    # `alembic.ini`/the Config object carries, so that migrations run with the
    # same env > .env > lemely.toml > default precedence as the app
    # (`env.py`'s own docstring). That means the `sqlalchemy.url` set above is
    # never actually read — `command.upgrade` would silently migrate the real
    # dev database instead of this throwaway one. Route through the same
    # env-var Settings reads (`LEMELY_DATABASE__URL`) so `load_settings()`
    # resolves to the throwaway database too.
    previous_db_url = _os.environ.get("LEMELY_DATABASE__URL")
    _os.environ["LEMELY_DATABASE__URL"] = rendered_url
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous_db_url is None:
            _os.environ.pop("LEMELY_DATABASE__URL", None)
        else:
            _os.environ["LEMELY_DATABASE__URL"] = previous_db_url

    engine = create_engine(url)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()
