"""deploy.yml hands every Paymob setting to Cloud Run, secrets from secrets (spec §3, §7)."""

from __future__ import annotations

from pathlib import Path

import yaml

from lemely.runtime.config import PaymobSettings

_DEPLOY = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "deploy.yml"
_PREFIX = "LEMELY_PAYMOB__"

#: Server-only credentials: must come from repository/environment SECRETS.
_SECRETS = {
    "SECRET_KEY": "PAYMOB_SECRET_KEY",
    "API_KEY": "PAYMOB_API_KEY",
    "HMAC_SECRET": "PAYMOB_HMAC_SECRET",
    "CARD_TOKEN_KEY": "PAYMOB_CARD_TOKEN_KEY",
}
#: Non-secret values: repository/environment VARIABLES.
_VARIABLES = {
    "PUBLIC_KEY": "PAYMOB_PUBLIC_KEY",
    "CARD_INTEGRATION_ID": "PAYMOB_CARD_INTEGRATION_ID",
    "MOTO_INTEGRATION_ID": "PAYMOB_MOTO_INTEGRATION_ID",
    "APPLE_PAY_INTEGRATION_ID": "PAYMOB_APPLE_PAY_INTEGRATION_ID",
}
#: Fields that keep their code default in every environment. ``expect_live`` stays off until
#: live keys are installed; then set ``LEMELY_PAYMOB__EXPECT_LIVE=true`` for production (see
#: the go-live checklist, L1).
_DEFAULTED = {"api_base", "checkout_base", "timeout_seconds", "expect_live"}


def _env_vars() -> dict[str, str]:
    workflow = yaml.safe_load(_DEPLOY.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["deploy-backend"]["steps"]
    deploy = next(step for step in steps if step.get("id") == "deploy")
    pairs = (line.split("=", 1) for line in deploy["with"]["env_vars"].splitlines() if line)
    return {name: value for name, value in pairs}


def test_server_only_credentials_come_from_secrets() -> None:
    env = _env_vars()
    for field, secret in _SECRETS.items():
        assert env[_PREFIX + field] == f"${{{{ secrets.{secret} }}}}", field


def test_public_values_come_from_variables_never_secrets() -> None:
    env = _env_vars()
    for field, variable in _VARIABLES.items():
        assert env[_PREFIX + field] == f"${{{{ vars.{variable} }}}}", field


def test_every_paymob_field_is_deployed_or_deliberately_defaulted() -> None:
    env = _env_vars()
    deployed = {name.removeprefix(_PREFIX).lower() for name in env if name.startswith(_PREFIX)}
    assert deployed == set(PaymobSettings.model_fields) - _DEFAULTED


def test_callback_origins_follow_the_environment_like_the_email_links() -> None:
    env = _env_vars()
    origin = env["LEMELY_EMAIL__APP_BASE_URL"]
    assert env[_PREFIX + "NOTIFICATION_BASE_URL"] == origin
    assert env[_PREFIX + "REDIRECTION_BASE_URL"] == origin
