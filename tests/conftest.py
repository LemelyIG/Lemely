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
