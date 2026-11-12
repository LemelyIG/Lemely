"""A failing CLI run must never print a secret setting, in any log format.

A staging purge once failed with a rich traceback whose locals included the whole ``Settings``;
the fields that were plain ``str`` printed in clear text into Cloud Logging. Two layers hold now:
the four credential settings are ``SecretStr``, and no traceback is ever rendered with locals.
"""

from __future__ import annotations

import pytest

from lemely.app import cli as cli_module
from lemely.app import purge_cli
from lemely.runtime.config import Settings

SECRETS = {
    "LEMELY_WAITLIST__DIGEST_SECRET": "sentinel-digest-9f3a",
    "LEMELY_WAITLIST__TURNSTILE_SECRET_KEY": "sentinel-turnstile-1c7b",
    "LEMELY_EDGE__ORIGIN_SECRET": "sentinel-origin-5d2e",
    "LEMELY_EDGE__ORIGIN_SECRET_PREVIOUS": "sentinel-origin-prev-8a41",
    "LEMELY_PUSH__VAPID_PRIVATE_KEY": "sentinel-vapid-77ce",
    "LEMELY_SUPABASE__SERVICE_ROLE_KEY": "sentinel-service-role-30bd",
}


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    for key, value in SECRETS.items():
        monkeypatch.setenv(key, value)
    return SECRETS


def test_the_database_password_is_not_in_the_settings_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LEMELY_DATABASE__URL",
        "postgresql+psycopg://postgres.ref:sentinel-dbpass-62f1@host:6543/db",
    )
    settings = Settings()
    assert settings.database.url.endswith("@host:6543/db")  # still readable by the code
    assert "sentinel-dbpass-62f1" not in repr(settings)
    assert "sentinel-dbpass-62f1" not in str(settings.database)


def test_credential_settings_are_masked_in_every_rendering(secret_env: dict[str, str]) -> None:
    settings = Settings()
    rendered = repr(settings) + str(settings) + settings.model_dump_json()
    for value in secret_env.values():
        assert value not in rendered, value
    # ... and still readable by the code that needs them.
    assert settings.waitlist.digest_secret is not None
    assert (
        settings.waitlist.digest_secret.get_secret_value()
        == secret_env["LEMELY_WAITLIST__DIGEST_SECRET"]
    )
    assert settings.edge.origin_secret is not None
    assert (
        settings.edge.origin_secret.get_secret_value() == secret_env["LEMELY_EDGE__ORIGIN_SECRET"]
    )


@pytest.mark.parametrize("log_format", ["json", "console"])
def test_an_unexpected_failure_prints_no_secret(
    secret_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    log_format: str,
) -> None:
    def boom(settings: Settings, **_kwargs: object) -> int:
        local_copy = settings  # a local holding every secret, as in the incident
        plain_local = "sentinel-plain-local-4e9d"  # a plain str, which no SecretStr can mask
        raise RuntimeError(f"unexpected failure ({type(local_copy).__name__}, {len(plain_local)})")

    monkeypatch.setattr(purge_cli, "purge_users_command", boom)
    code = cli_module.main(
        ["--log-format", log_format, "admin", "purge-users", "--keep-domain", "lemelyig.com"]
    )
    out = capsys.readouterr()
    text = out.out + out.err
    assert code == 1
    assert "unexpected failure" in text
    assert "sentinel-plain-local-4e9d" not in text, f"a local variable leaked ({log_format})"
    for value in secret_env.values():
        assert value not in text, f"{value} leaked in {log_format} output"


def test_a_click_refusal_prints_only_its_message(
    secret_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "LEMELY_DATABASE__URL",
        "postgresql+psycopg://postgres.ynrmqjiqcvmcakondjbp:pw@aws-0-eu.pooler.supabase.com:6543/postgres",
    )
    code = cli_module.main(["admin", "purge-users", "--keep-domain", "lemelyig.com", "--execute"])
    text = "".join(capsys.readouterr())
    assert code != 0
    assert "Refusing to purge a production target" in text
    assert "Traceback" not in text
    for value in secret_env.values():
        assert value not in text
