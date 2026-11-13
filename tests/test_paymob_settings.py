"""PaymobSettings: env-driven, secrets stay secret, blank means unset (spec §3, §7)."""

from __future__ import annotations

import traceback

import pytest
from pydantic import ValidationError, model_validator
from structlog.testing import capture_logs

from lemely.runtime.config import PaymobKeyModeError, PaymobSettings, Settings


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


# -- key mode (skill audit I2, review I2 and I3) ------------------------------------------

LIVE_SECRET = "egy_sk_live_abcdef0123456789"
LIVE_PUBLIC = "egy_pk_live_abcdef0123456789"
TEST_SECRET = "egy_sk_test_abcdef0123456789"
TEST_PUBLIC = "egy_pk_test_abcdef0123456789"
COMPLETE = {
    "api_key": "api_key_abc",
    "hmac_secret": "hmac_abc",
    "card_integration_id": 4569876,
}


def _paymob(**fields: object) -> PaymobSettings:
    return PaymobSettings.model_validate(fields)


def test_expect_live_is_off_by_default_so_dev_and_test_keep_working() -> None:
    paymob = _paymob(secret_key=TEST_SECRET, public_key=TEST_PUBLIC)
    assert PaymobSettings().expect_live is False
    assert paymob.expect_live is False
    paymob.require_live_keys()  # no error: nothing asked for live keys


def test_require_live_keys_accepts_live_keys() -> None:
    paymob = _paymob(expect_live=True, secret_key=LIVE_SECRET, public_key=LIVE_PUBLIC)
    paymob.require_live_keys()


def test_require_live_keys_accepts_an_unconfigured_account() -> None:
    """Credentials unset is a supported state (checkout answers 503), even in production."""
    paymob = _paymob(expect_live=True)
    paymob.require_live_keys()
    assert paymob.checkout_configured is False


@pytest.mark.parametrize(
    "fields",
    [
        {"secret_key": TEST_SECRET, "public_key": TEST_PUBLIC},
        {"secret_key": TEST_SECRET},
        {"public_key": TEST_PUBLIC},
        {"secret_key": "sk_test_abcdef0123456789"},
        {"secret_key": TEST_SECRET, "public_key": LIVE_PUBLIC},
        {"secret_key": LIVE_SECRET, "public_key": TEST_PUBLIC},
    ],
)
def test_expect_live_refuses_a_test_mode_key_with_a_plain_error(
    fields: dict[str, object],
) -> None:
    paymob = _paymob(expect_live=True, **fields)  # constructing it never raises
    with pytest.raises(PaymobKeyModeError, match="test-mode") as caught:
        paymob.require_live_keys()
    assert isinstance(caught.value, RuntimeError)
    assert not isinstance(caught.value, ValidationError)


def test_keys_with_no_recognisable_mode_are_not_judged() -> None:
    """The existing fixtures use bare ``sk``/``pk``; only a marked key can be refused."""
    _paymob(expect_live=True, secret_key="sk", public_key="pk").require_live_keys()
    assert _paymob(secret_key="sk", public_key=TEST_PUBLIC).key_mode_mismatch is False


def test_the_refusal_names_the_field_but_carries_no_credential() -> None:
    paymob = _paymob(
        expect_live=True,
        secret_key=TEST_SECRET,
        public_key=LIVE_PUBLIC,
        api_key="APIKEYDISTINCTIVE0001",
        hmac_secret="HMACSECRETDISTINCTIVE02",
    )
    with pytest.raises(PaymobKeyModeError) as caught:
        paymob.require_live_keys()
    rendered = "".join(
        [
            str(caught.value),
            repr(caught.value),
            repr(caught.value.args),
            *traceback.format_exception(caught.value),
        ]
    )
    assert "secret_key" in rendered
    for secret in (TEST_SECRET, LIVE_PUBLIC, "APIKEYDISTINCTIVE0001", "HMACSECRETDISTINCTIVE02"):
        assert secret not in rendered


@pytest.mark.parametrize(
    "fields",
    [
        {"secret_key": TEST_SECRET, "public_key": LIVE_PUBLIC},
        {"secret_key": LIVE_SECRET, "public_key": TEST_PUBLIC},
    ],
)
@pytest.mark.parametrize("expect_live", [False, True])
def test_a_mode_mismatch_does_not_stop_the_settings_from_loading(
    fields: dict[str, object], expect_live: bool
) -> None:
    paymob = _paymob(expect_live=expect_live, **fields, **COMPLETE)
    assert paymob.key_mode_mismatch is True


@pytest.mark.parametrize(
    "fields",
    [
        {"secret_key": TEST_SECRET, "public_key": TEST_PUBLIC},
        {"secret_key": LIVE_SECRET, "public_key": LIVE_PUBLIC},
        {"secret_key": TEST_SECRET},
        {"public_key": LIVE_PUBLIC},
        {"secret_key": "sk", "public_key": LIVE_PUBLIC},
        {},
    ],
)
def test_matching_unset_or_unreadable_keys_are_not_a_mismatch(fields: dict[str, object]) -> None:
    assert _paymob(**fields).key_mode_mismatch is False


def test_a_mismatch_makes_checkout_unconfigured() -> None:
    full = {"secret_key": LIVE_SECRET, "public_key": LIVE_PUBLIC, **COMPLETE}
    assert _paymob(**full).checkout_configured is True
    assert _paymob(**{**full, "public_key": TEST_PUBLIC}).checkout_configured is False


def test_a_mismatch_is_logged_as_an_alert_without_the_keys() -> None:
    paymob = _paymob(secret_key=TEST_SECRET, public_key=LIVE_PUBLIC, **COMPLETE)
    with capture_logs() as logs:
        assert paymob.log_key_mode_mismatch() is True
    (entry,) = [e for e in logs if e["event"] == "paymob_key_mode_mismatch"]
    assert entry["log_level"] == "error"
    assert entry["alert"] is True
    rendered = str(logs)
    for secret in (TEST_SECRET, LIVE_PUBLIC, COMPLETE["api_key"], COMPLETE["hmac_secret"]):
        assert str(secret) not in rendered


def test_no_mismatch_logs_nothing() -> None:
    with capture_logs() as logs:
        assert (
            _paymob(secret_key=LIVE_SECRET, public_key=LIVE_PUBLIC).log_key_mode_mismatch() is False
        )
    assert logs == []


def test_the_env_route_loads_and_the_refusal_comes_from_require_live_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMELY_PAYMOB__EXPECT_LIVE", "true")
    monkeypatch.setenv("LEMELY_PAYMOB__SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("LEMELY_PAYMOB__PUBLIC_KEY", TEST_PUBLIC)
    paymob = Settings().paymob  # no ValidationError, so no input dict to echo
    with pytest.raises(PaymobKeyModeError, match="test-mode") as caught:
        paymob.require_live_keys()
    assert TEST_SECRET not in str(caught.value)
    assert TEST_PUBLIC not in str(caught.value)
    monkeypatch.setenv("LEMELY_PAYMOB__SECRET_KEY", LIVE_SECRET)
    monkeypatch.setenv("LEMELY_PAYMOB__PUBLIC_KEY", LIVE_PUBLIC)
    Settings().paymob.require_live_keys()


def test_expect_live_false_in_the_env_allows_test_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMELY_PAYMOB__EXPECT_LIVE", "false")
    monkeypatch.setenv("LEMELY_PAYMOB__SECRET_KEY", TEST_SECRET)
    paymob = Settings().paymob
    assert paymob.expect_live is False
    paymob.require_live_keys()


class _FailingSettings(Settings):
    """The real ``Settings`` config with a validator that always fails: a stand-in for any
    future validator that rejects a value, whose error would carry the whole input."""

    @model_validator(mode="after")
    def _always_fails(self) -> _FailingSettings:
        raise ValueError("probe")


SECRETS = {
    "secret_key": "SKDISTINCTIVE0000000000001",
    "api_key": "APIDISTINCTIVE000000000002",
    "hmac_secret": "HMACDISTINCTIVE0000000003",
    "card_token_key": "CTKDISTINCTIVE0000000004",
}


def test_a_settings_validation_error_never_echoes_the_paymob_secrets() -> None:
    """``str``/``repr`` are what a startup traceback prints, so the root hides its input.

    ``errors()`` and ``json()`` keep ``input`` by pydantic's design (only
    ``include_input=False`` drops it), which is why the one validator that handled the keys
    no longer raises a ``ValidationError`` (see ``require_live_keys``) and why nothing may log
    a settings error's ``errors()``. The values here are short enough that pydantic's own
    truncation of a long input could not hide a leak.
    """
    with pytest.raises(ValidationError) as caught:
        _FailingSettings(paymob=dict(SECRETS))
    exc = caught.value
    forms = [
        str(exc),
        repr(exc),
        str(exc.errors(include_input=False)),
        exc.json(include_input=False),
    ]
    for secret in SECRETS.values():
        for form in forms:
            assert secret not in form
            assert secret[:12] not in form
            assert secret[-12:] not in form


def test_key_mode_is_read_from_the_secret_key_prefix() -> None:
    assert _paymob(secret_key=TEST_SECRET).key_mode == "test"
    assert _paymob(secret_key=LIVE_SECRET).key_mode == "live"


def test_key_mode_of_an_unreadable_key_follows_expect_live() -> None:
    """A bare key has no prefix to read: production (``expect_live``) means live, else test."""
    assert _paymob(secret_key="sk").key_mode == "test"
    assert _paymob(secret_key="sk", expect_live=True).key_mode == "live"
    assert _paymob().key_mode == "test"
