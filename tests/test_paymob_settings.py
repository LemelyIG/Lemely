"""PaymobSettings: env-driven, secrets stay secret, blank means unset (spec §3, §7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lemely.runtime.config import PaymobSettings, Settings


def test_defaults_are_unconfigured_with_the_egypt_hosts() -> None:
    paymob = PaymobSettings()
    assert paymob.api_base == "https://accept.paymob.com"
    assert paymob.checkout_base == "https://eg.checkout.paymob.com"
    assert paymob.notification_base_url == "https://lemelyig.com"
    assert paymob.redirection_base_url == "https://lemelyig.com"
    assert paymob.timeout_seconds == 20.0
    assert paymob.secret_key is None
    assert paymob.checkout_configured is False


def test_env_vars_populate_every_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMELY_PAYMOB__SECRET_KEY", "egy_sk_test_abc")
    monkeypatch.setenv("LEMELY_PAYMOB__PUBLIC_KEY", "egy_pk_test_abc")
    monkeypatch.setenv("LEMELY_PAYMOB__API_KEY", "api_key_abc")
    monkeypatch.setenv("LEMELY_PAYMOB__HMAC_SECRET", "hmac_abc")
    monkeypatch.setenv("LEMELY_PAYMOB__CARD_INTEGRATION_ID", "4569876")
    monkeypatch.setenv("LEMELY_PAYMOB__MOTO_INTEGRATION_ID", "4569877")
    monkeypatch.setenv("LEMELY_PAYMOB__NOTIFICATION_BASE_URL", "https://staging.lemelyig.com/")
    paymob = Settings().paymob
    assert paymob.secret_key is not None
    assert paymob.secret_key.get_secret_value() == "egy_sk_test_abc"
    assert paymob.public_key == "egy_pk_test_abc"
    assert paymob.card_integration_id == 4569876
    assert paymob.moto_integration_id == 4569877
    assert paymob.apple_pay_integration_id is None
    assert paymob.notification_base_url == "https://staging.lemelyig.com"
    assert paymob.checkout_configured is True


def test_blank_env_values_read_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """deploy.yml renders an unregistered secret or variable as "" (as for RESEND_API_KEY)."""
    for name in (
        "SECRET_KEY",
        "PUBLIC_KEY",
        "API_KEY",
        "HMAC_SECRET",
        "CARD_INTEGRATION_ID",
        "MOTO_INTEGRATION_ID",
        "APPLE_PAY_INTEGRATION_ID",
        "CARD_TOKEN_KEY",
    ):
        monkeypatch.setenv(f"LEMELY_PAYMOB__{name}", "")
    paymob = Settings().paymob
    assert paymob.secret_key is None
    assert paymob.public_key is None
    assert paymob.card_integration_id is None
    assert paymob.card_token_key is None
    assert paymob.checkout_configured is False


def test_checkout_needs_all_five_credentials() -> None:
    full = {
        "secret_key": "sk",
        "public_key": "pk",
        "api_key": "ak",
        "hmac_secret": "hs",
        "card_integration_id": 1,
    }
    assert PaymobSettings.model_validate(full).checkout_configured is True
    for missing in full:
        partial = {k: v for k, v in full.items() if k != missing}
        assert PaymobSettings.model_validate(partial).checkout_configured is False, missing


def test_secrets_never_appear_in_repr() -> None:
    paymob = PaymobSettings.model_validate(
        {
            "secret_key": "sk_live_SECRET",
            "api_key": "API_SECRET",
            "hmac_secret": "HMAC_SECRET",
            "card_token_key": "CARD_TOKEN_SECRET",
        }
    )
    rendered = repr(paymob) + str(paymob.model_dump())
    assert "sk_live_SECRET" not in rendered
    assert "API_SECRET" not in rendered
    assert "HMAC_SECRET" not in rendered
    assert "CARD_TOKEN_SECRET" not in rendered


def test_a_relative_callback_origin_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PaymobSettings.model_validate({"notification_base_url": "lemelyig.com"})


def test_integration_ids_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        PaymobSettings.model_validate({"card_integration_id": 0})
