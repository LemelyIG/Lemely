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


# -- key mode: production must not run on test keys (skill audit I2) -----------------------

LIVE_SECRET = "egy_sk_live_abcdef0123456789"
LIVE_PUBLIC = "egy_pk_live_abcdef0123456789"
TEST_SECRET = "egy_sk_test_abcdef0123456789"
TEST_PUBLIC = "egy_pk_test_abcdef0123456789"


def _paymob(**fields: object) -> PaymobSettings:
    return PaymobSettings.model_validate(fields)


def test_expect_live_is_off_by_default_so_dev_and_test_keep_working() -> None:
    assert PaymobSettings().expect_live is False
    paymob = _paymob(secret_key=TEST_SECRET, public_key=TEST_PUBLIC)
    assert paymob.expect_live is False


def test_expect_live_accepts_live_keys() -> None:
    paymob = _paymob(expect_live=True, secret_key=LIVE_SECRET, public_key=LIVE_PUBLIC)
    assert paymob.expect_live is True


def test_expect_live_accepts_an_unconfigured_account() -> None:
    """Credentials unset is a supported state (checkout answers 503), even in production."""
    assert _paymob(expect_live=True).checkout_configured is False


@pytest.mark.parametrize(
    "fields",
    [
        {"secret_key": TEST_SECRET, "public_key": TEST_PUBLIC},
        {"secret_key": TEST_SECRET},
        {"public_key": TEST_PUBLIC},
        {"secret_key": "sk_test_abcdef0123456789"},
    ],
)
def test_expect_live_refuses_a_test_mode_key(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="test-mode"):
        _paymob(expect_live=True, **fields)


@pytest.mark.parametrize("expect_live", [False, True])
@pytest.mark.parametrize(
    "fields",
    [
        {"secret_key": TEST_SECRET, "public_key": LIVE_PUBLIC},
        {"secret_key": LIVE_SECRET, "public_key": TEST_PUBLIC},
    ],
)
def test_public_and_secret_key_modes_must_agree(
    fields: dict[str, object], expect_live: bool
) -> None:
    with pytest.raises(ValidationError, match="different modes"):
        _paymob(expect_live=expect_live, **fields)


def test_keys_with_no_recognisable_mode_are_not_judged() -> None:
    """The existing fixtures use bare ``sk``/``pk``; only a marked key can be refused."""
    assert _paymob(expect_live=True, secret_key="sk", public_key="pk").expect_live is True
    assert _paymob(secret_key="sk", public_key=TEST_PUBLIC).secret_key is not None


def test_the_error_names_the_field_but_never_the_key() -> None:
    with pytest.raises(ValidationError) as caught:
        _paymob(expect_live=True, secret_key=TEST_SECRET, public_key=LIVE_PUBLIC)
    message = str(caught.value)
    assert "secret_key" in message
    assert TEST_SECRET not in message
    assert LIVE_PUBLIC not in message


def test_settings_refuse_to_start_on_test_keys_when_the_env_says_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMELY_PAYMOB__EXPECT_LIVE", "true")
    monkeypatch.setenv("LEMELY_PAYMOB__SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("LEMELY_PAYMOB__PUBLIC_KEY", TEST_PUBLIC)
    with pytest.raises(ValidationError, match="test-mode") as caught:
        Settings()
    assert TEST_SECRET not in str(caught.value)  # the env route must not echo the credentials
    assert TEST_PUBLIC not in str(caught.value)
    monkeypatch.setenv("LEMELY_PAYMOB__SECRET_KEY", LIVE_SECRET)
    monkeypatch.setenv("LEMELY_PAYMOB__PUBLIC_KEY", LIVE_PUBLIC)
    assert Settings().paymob.expect_live is True


def test_expect_live_false_in_the_env_allows_test_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMELY_PAYMOB__EXPECT_LIVE", "false")
    monkeypatch.setenv("LEMELY_PAYMOB__SECRET_KEY", TEST_SECRET)
    assert Settings().paymob.expect_live is False


def test_key_mode_is_read_from_the_secret_key_prefix() -> None:
    assert _paymob(secret_key=TEST_SECRET).key_mode == "test"
    assert _paymob(secret_key=LIVE_SECRET).key_mode == "live"


def test_key_mode_of_an_unreadable_key_follows_expect_live() -> None:
    """A bare key has no prefix to read: production (``expect_live``) means live, else test."""
    assert _paymob(secret_key="sk").key_mode == "test"
    assert _paymob(secret_key="sk", expect_live=True).key_mode == "live"
    assert _paymob().key_mode == "test"
