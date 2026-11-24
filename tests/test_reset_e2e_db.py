"""The Playwright database reset must never be able to drop a shared database."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scripts import reset_e2e_db

SERVER = "postgresql+psycopg://user:secret@127.0.0.1:54322"


@pytest.mark.parametrize("name", ["postgres", "lemely_test_abc", "e2e_lemely", ""])
def test_reset_rejects_other_databases_before_connecting(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    connect = MagicMock()
    monkeypatch.setattr(reset_e2e_db.psycopg, "connect", connect)
    with pytest.raises(ValueError, match="must start with 'lemely_e2e'"):
        reset_e2e_db.reset_database(f"{SERVER}/{name}")
    connect.assert_not_called()


def test_reset_drops_and_creates_only_the_e2e_database(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    connection.__enter__ = MagicMock(return_value=connection)
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


def test_reset_quotes_a_hostile_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    connection.__enter__ = MagicMock(return_value=connection)
    monkeypatch.setattr(reset_e2e_db.psycopg, "connect", MagicMock(return_value=connection))

    reset_e2e_db.reset_database(f'{SERVER}/lemely_e2e"; DROP DATABASE postgres; --')

    first = connection.execute.call_args_list[0].args[0].as_string()
    assert (
        first == 'DROP DATABASE IF EXISTS "lemely_e2e""; DROP DATABASE postgres; --" WITH (FORCE)'
    )
