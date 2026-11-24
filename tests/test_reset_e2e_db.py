"""The Playwright reset must never be able to drop a shared database or delete a real account.

Every test body here is mocked and touches no database. Run the file with
``LEMELY_DATABASE__URL`` pointed at a throwaway ``lemely_test_*`` database all the
same: ``tests/conftest.py``'s autouse session fixture writes to whatever database is
configured, which is the shared development ``postgres`` by default.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

from lemely.auth.gotrue import GoTrueUser
from scripts import e2e_server, reset_e2e_db, seed_e2e, seed_e2e_boundaries
from scripts.e2e_fixtures import E2E_DATABASE_NAME, E2E_EMAIL_DOMAIN

if TYPE_CHECKING:
    from lemely.runtime.config import Settings

SERVER = "postgresql+psycopg://user:sentinelpw@127.0.0.1:54322"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _settings(*, supabase_url: str = "http://127.0.0.1:54321", database_url: str = "") -> Settings:
    """A stand-in carrying only what the scripts read (a real ``Settings`` would read the env)."""
    return cast(
        "Settings",
        SimpleNamespace(
            supabase=SimpleNamespace(url=supabase_url),
            database=SimpleNamespace(url=database_url),
        ),
    )


def _connection() -> MagicMock:
    connection = MagicMock()
    connection.__enter__ = MagicMock(return_value=connection)
    return connection


# --- reset_database: the name and host guard ---------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "postgres",
        "lemely_test_abc",
        "e2e_lemely",
        "",
        "lemely_e2e_other",
        "lemely_e2e2",
        "Lemely_E2E",
        'lemely_e2e"; DROP DATABASE postgres; --',
    ],
)
def test_reset_rejects_any_name_but_exactly_lemely_e2e_before_connecting(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    connect = MagicMock()
    monkeypatch.setattr(reset_e2e_db.psycopg, "connect", connect)
    with pytest.raises(ValueError, match="only 'lemely_e2e' may be reset"):
        reset_e2e_db.reset_database(f"{SERVER}/{name}")
    connect.assert_not_called()


@pytest.mark.parametrize(
    "server",
    [
        "postgresql+psycopg://u:p@db.example.com:5432",
        "postgresql+psycopg://u:p@10.0.0.5:54322",
        "postgresql+psycopg://u:p@127.0.0.1.evil.com:54322",
        "postgresql+psycopg://u:p@0.0.0.0:54322",
        "postgresql+psycopg://u:p@",  # no host: libpq would resolve it through PGHOST
    ],
)
def test_reset_rejects_a_non_loopback_or_missing_host_before_connecting(
    monkeypatch: pytest.MonkeyPatch, server: str
) -> None:
    connect = MagicMock()
    monkeypatch.setattr(reset_e2e_db.psycopg, "connect", connect)
    with pytest.raises(ValueError, match="host must be one of"):
        reset_e2e_db.reset_database(f"{server}/{E2E_DATABASE_NAME}")
    connect.assert_not_called()


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_reset_accepts_each_loopback_host(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    connect = MagicMock(return_value=_connection())
    monkeypatch.setattr(reset_e2e_db.psycopg, "connect", connect)
    url = f"postgresql+psycopg://user:pw@{host}:54322/{E2E_DATABASE_NAME}"
    assert reset_e2e_db.reset_database(url) == E2E_DATABASE_NAME
    assert connect.call_args.kwargs["host"] == host.strip("[]")


def test_reset_drops_and_creates_only_the_e2e_database(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _connection()
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(reset_e2e_db.psycopg, "connect", connect)

    assert reset_e2e_db.reset_database(f"{SERVER}/lemely_e2e") == "lemely_e2e"

    kwargs = connect.call_args.kwargs
    assert kwargs["dbname"] == "postgres"
    assert (kwargs["host"], kwargs["port"], kwargs["user"]) == ("127.0.0.1", 54322, "user")
    statements = [call.args[0].as_string() for call in connection.execute.call_args_list]
    assert statements == [
        'DROP DATABASE IF EXISTS "lemely_e2e" WITH (FORCE)',
        'CREATE DATABASE "lemely_e2e"',
    ]


# --- is_e2e_account: the domain filter ---------------------------------------------------


@pytest.mark.parametrize(
    "email",
    [
        f"teacher-ab12@{E2E_EMAIL_DOMAIN}",
        f"Student-X@{E2E_EMAIL_DOMAIN.upper()}",
        f"  padded@{E2E_EMAIL_DOMAIN}  ",
        f"a@b@{E2E_EMAIL_DOMAIN}",
    ],
)
def test_e2e_domain_accounts_match(email: str) -> None:
    assert reset_e2e_db.is_e2e_account(email)


@pytest.mark.parametrize(
    "email",
    [
        "student@example.com",
        "lemelyig@gmail.com",
        f"x@evil-{E2E_EMAIL_DOMAIN}",
        f"x@{E2E_EMAIL_DOMAIN}.evil.com",
        f"x@sub.{E2E_EMAIL_DOMAIN}",
        f"@{E2E_EMAIL_DOMAIN}",
        E2E_EMAIL_DOMAIN,
        f"{E2E_EMAIL_DOMAIN}@example.com",
        "",
    ],
)
def test_other_accounts_never_match(email: str) -> None:
    assert not reset_e2e_db.is_e2e_account(email)


def test_the_domain_is_the_one_the_seed_writes() -> None:
    assert E2E_EMAIL_DOMAIN == seed_e2e.EMAIL_DOMAIN


# --- purge_e2e_auth_users: the loopback guard and the deletion set ------------------------


def _user(email: str) -> GoTrueUser:
    return GoTrueUser(id=uuid.uuid4(), email=email)


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:54321", "http://localhost:54321", "http://[::1]:54321"],
)
def test_supabase_loopback_urls_are_accepted(url: str) -> None:
    assert reset_e2e_db.supabase_url_is_loopback(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://abcdefgh.supabase.co",
        "http://127.0.0.1.evil.com:54321",
        "http://127.0.0.1@evil.com",
        "http://localhost.evil.com",
        "http://0.0.0.0:54321",
        "",
    ],
)
def test_supabase_non_loopback_urls_are_refused(url: str) -> None:
    assert not reset_e2e_db.supabase_url_is_loopback(url)


def test_purge_deletes_only_e2e_domain_users() -> None:
    mine = [_user(f"a@{E2E_EMAIL_DOMAIN}"), _user(f"B@{E2E_EMAIL_DOMAIN.upper()}")]
    theirs = [
        _user("owner@example.com"),
        _user("lemelyig@gmail.com"),
        _user(f"x@evil-{E2E_EMAIL_DOMAIN}"),
    ]
    admin = MagicMock()
    admin.list_users.return_value = [mine[0], *theirs, mine[1]]
    admin.delete_user.return_value = True

    assert reset_e2e_db.purge_e2e_auth_users(_settings(), admin) == 2

    deleted = [call.args[0] for call in admin.delete_user.call_args_list]
    assert deleted == [mine[0].id, mine[1].id]


def test_purge_counts_only_users_that_still_existed() -> None:
    gone, here = _user(f"gone@{E2E_EMAIL_DOMAIN}"), _user(f"here@{E2E_EMAIL_DOMAIN}")
    admin = MagicMock()
    admin.list_users.return_value = [gone, here]
    admin.delete_user.side_effect = lambda user_id: user_id == here.id

    assert reset_e2e_db.purge_e2e_auth_users(_settings(), admin) == 1


@pytest.mark.parametrize(
    "url", ["https://abcdefgh.supabase.co", "http://127.0.0.1.evil.com:54321", ""]
)
def test_purge_never_touches_gotrue_unless_supabase_is_loopback(url: str) -> None:
    admin = MagicMock()
    admin.list_users.return_value = [_user(f"a@{E2E_EMAIL_DOMAIN}")]

    assert reset_e2e_db.purge_e2e_auth_users(_settings(supabase_url=url), admin) == 0

    admin.list_users.assert_not_called()
    admin.delete_user.assert_not_called()


# --- main: the URL comes from the environment, then the reset, then the purge --------------


def test_main_resets_the_environment_url_not_a_lemely_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "lemely.toml").write_text(
        '[database]\nurl = "postgresql+psycopg://u:p@db.example.com:5432/postgres"\n'
    )
    monkeypatch.chdir(tmp_path)
    env_url = f"{SERVER}/{E2E_DATABASE_NAME}"
    monkeypatch.setenv("LEMELY_DATABASE__URL", env_url)
    calls = MagicMock()
    calls.reset.return_value = E2E_DATABASE_NAME
    calls.purge.return_value = 3
    monkeypatch.setattr(reset_e2e_db, "ensure_supabase_env", calls.keys)
    monkeypatch.setattr(reset_e2e_db, "reset_database", calls.reset)
    monkeypatch.setattr(reset_e2e_db, "purge_e2e_auth_users", calls.purge)

    assert reset_e2e_db.main() == 0

    assert [c[0] for c in calls.mock_calls] == ["keys", "reset", "purge"]
    assert calls.reset.call_args.args == (env_url,)


# --- seed_e2e_boundaries ---------------------------------------------------------------------


def test_boundary_seed_refuses_any_database_but_lemely_e2e(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sessionmaker = MagicMock()
    monkeypatch.setattr(seed_e2e_boundaries, "get_sessionmaker", sessionmaker)
    for name in ("postgres", "lemely_e2e_other", "lemely_tutoring_e2e"):
        url = f"{SERVER}/{name}"
        monkeypatch.setattr(
            seed_e2e_boundaries, "load_settings", lambda url=url: _settings(database_url=url)
        )
        assert seed_e2e_boundaries.main() == 2
    sessionmaker.assert_not_called()
    assert "refusing database" in capsys.readouterr().err


# --- e2e_server's opt-in database guard ----------------------------------------------------------


@pytest.mark.parametrize("expected", [None, ""])
def test_server_guard_is_off_unless_asked(expected: str | None) -> None:
    e2e_server.require_expected_database(_settings(database_url=f"{SERVER}/postgres"), expected)


def test_server_guard_accepts_the_expected_database() -> None:
    settings = _settings(database_url=f"{SERVER}/{E2E_DATABASE_NAME}")
    e2e_server.require_expected_database(settings, E2E_DATABASE_NAME)


def test_server_guard_refuses_another_database_without_leaking_the_url() -> None:
    settings = _settings(database_url=f"{SERVER}/postgres")
    with pytest.raises(SystemExit) as refused:
        e2e_server.require_expected_database(settings, E2E_DATABASE_NAME)
    message = str(refused.value)
    assert "'postgres'" in message
    assert "sentinelpw" not in message


def test_playwright_config_arms_the_server_guard_for_the_same_database() -> None:
    config = (REPO_ROOT / "web" / "playwright.config.ts").read_text(encoding="utf-8")
    assert f'const E2E_DATABASE_NAME = "{E2E_DATABASE_NAME}"' in config
    assert re.search(rf"{e2e_server.EXPECT_DATABASE_ENV}:\s*E2E_DATABASE_NAME\b", config), (
        "the backend webServer env must set the e2e_server database guard"
    )
