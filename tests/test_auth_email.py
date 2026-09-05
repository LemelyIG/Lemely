"""EmailProvider behaviour: the mock, the Resend sender, and the deps wiring.

The ``delivers_out_of_band`` contract is the load-bearing assertion in this
file. It is what decides whether the auth routes may hand a live verification
or reset link back through the API, so each provider is pinned to its value
here rather than left implied by the class it happens to be.
"""

from __future__ import annotations

import json
import logging
import re

import httpx
import pytest

from lemely.auth.email import MockEmailProvider, ResendEmailProvider
from lemely.runtime.config import EmailSettings, Settings
from lemely.runtime.errors import ExternalServiceError
from lemely.web.deps import _build_email_provider

VERIFY_LINK = "https://lemelyig.com/verify-email/abc123"
RESET_LINK = "https://lemelyig.com/reset-password/xyz789"


def test_mock_provider_does_not_deliver_out_of_band() -> None:
    """The mock is the sole condition under which the API may surface a link."""
    assert MockEmailProvider().delivers_out_of_band is False


def test_mock_provider_logs_the_verification_link_and_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = MockEmailProvider()
    with caplog.at_level(logging.INFO, logger="lemely.auth.email"):
        provider.send_verification("student@example.com", "https://app/verify-email/abc", "123456")
    assert "student@example.com" in caplog.text
    assert "https://app/verify-email/abc" in caplog.text
    assert "123456" in caplog.text


def test_mock_provider_logs_the_reset_link(caplog: pytest.LogCaptureFixture) -> None:
    provider = MockEmailProvider()
    with caplog.at_level(logging.INFO, logger="lemely.auth.email"):
        provider.send_password_reset("student@example.com", "https://app/reset/xyz")
    assert "https://app/reset/xyz" in caplog.text


# --------------------------------------------------------------------------
# ResendEmailProvider
# --------------------------------------------------------------------------


def _settings(**overrides: object) -> EmailSettings:
    """An ``[email]`` config with a key present, so the real provider is buildable."""
    base: dict[str, object] = {"api_key": "re_test_key", "from_address": "noreply@lemelyig.com"}
    base.update(overrides)
    return EmailSettings(**base)  # type: ignore[arg-type]


def _provider(
    handler: object,
    settings: EmailSettings | None = None,
) -> tuple[ResendEmailProvider, list[httpx.Request]]:
    """Build a provider whose HTTP goes to ``handler`` instead of the network."""
    seen: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)  # type: ignore[operator]

    client = httpx.Client(transport=httpx.MockTransport(_record))
    return ResendEmailProvider(settings or _settings(), client=client), seen


def _ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"id": "msg_abc123"})


def test_resend_provider_delivers_out_of_band() -> None:
    """A real sender must suppress the API's dev-link affordance."""
    provider, _ = _provider(_ok)
    assert provider.delivers_out_of_band is True


def test_resend_provider_requires_an_api_key() -> None:
    """Building without a key is a wiring bug, not a runtime state."""
    with pytest.raises(ValueError, match="requires \\[email\\] api_key"):
        ResendEmailProvider(EmailSettings())


def test_verification_send_posts_the_expected_request() -> None:
    provider, seen = _provider(_ok)
    provider.send_verification("student@example.com", VERIFY_LINK)

    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.resend.com/emails"
    assert request.headers["Authorization"] == "Bearer re_test_key"

    body = json.loads(request.content)
    assert body["from"] == "Lemely <noreply@lemelyig.com>"
    assert body["to"] == ["student@example.com"]
    assert body["subject"] == "Verify your Lemely email address"
    # Both parts carry the link: a text-only reader must be able to act on it.
    assert VERIFY_LINK in body["html"]
    assert VERIFY_LINK in body["text"]


def test_password_reset_send_is_a_distinct_mail() -> None:
    """The two purposes must not be indistinguishable to a recipient."""
    provider, seen = _provider(_ok)
    provider.send_password_reset("student@example.com", RESET_LINK)

    body = json.loads(seen[0].content)
    assert body["subject"] == "Reset your Lemely password"
    assert RESET_LINK in body["text"]
    assert "your current password still works" in body["text"]


def test_reply_to_is_omitted_when_unset_and_sent_when_set() -> None:
    provider, seen = _provider(_ok)
    provider.send_verification("student@example.com", VERIFY_LINK)
    assert "reply_to" not in json.loads(seen[0].content)

    provider, seen = _provider(_ok, _settings(reply_to="support@lemelyig.com"))
    provider.send_verification("student@example.com", VERIFY_LINK)
    assert json.loads(seen[0].content)["reply_to"] == "support@lemelyig.com"


def test_link_is_html_escaped_in_the_html_part() -> None:
    """A query string must not break out of the href attribute."""
    provider, seen = _provider(_ok)
    provider.send_verification("student@example.com", "https://lemelyig.com/v?a=1&b=2")

    body = json.loads(seen[0].content)
    assert 'href="https://lemelyig.com/v?a=1&amp;b=2"' in body["html"]
    # The text part is not markup and keeps the URL usable verbatim.
    assert "https://lemelyig.com/v?a=1&b=2" in body["text"]


# A frontend route is what AuthService mints; an inbox needs a URL.
RELATIVE_VERIFY = "/verify-email/abc123"
RELATIVE_RESET = "/reset/xyz789"


def test_a_relative_link_is_made_absolute_before_it_is_sent() -> None:
    """Regression: the emailed link must never be a bare frontend route.

    ``AuthService._mint_verification_link`` returns ``/verify-email/<token>``
    — correct for the SPA, meaningless in an inbox. Shipped as-is, a mail
    client resolved that root-relative href against no base and produced
    ``http:///verify-email/<token>``: an empty-host URL that no browser can
    reach, reported from a real inbox. The provider must join the configured
    origin on first.
    """
    provider, seen = _provider(_ok)
    provider.send_verification("student@example.com", RELATIVE_VERIFY)

    body = json.loads(seen[0].content)
    expected = "https://lemelyig.com/verify-email/abc123"
    assert expected in body["text"]
    assert f'href="{expected}"' in body["html"]
    # The exact shape of the bug, asserted directly rather than implied.
    assert "http:///" not in body["html"]
    assert "http:///" not in body["text"]


def test_a_relative_reset_link_is_made_absolute_too() -> None:
    """The reset mail carries the same defect if only verification is fixed."""
    provider, seen = _provider(_ok)
    provider.send_password_reset("student@example.com", RELATIVE_RESET)

    body = json.loads(seen[0].content)
    assert "https://lemelyig.com/reset/xyz789" in body["text"]
    assert "http:///" not in body["html"]


def test_the_origin_is_configurable_per_environment() -> None:
    """Staging must mail staging links, not production ones."""
    provider, seen = _provider(_ok, _settings(app_base_url="https://staging.lemelyig.com"))
    provider.send_verification("student@example.com", RELATIVE_VERIFY)

    body = json.loads(seen[0].content)
    assert "https://staging.lemelyig.com/verify-email/abc123" in body["text"]
    assert "https://lemelyig.com/verify-email" not in body["text"]


def test_an_already_absolute_link_is_not_double_prefixed() -> None:
    """Joining must be idempotent, so a caller that mints full URLs still works."""
    provider, seen = _provider(_ok)
    provider.send_verification("student@example.com", VERIFY_LINK)

    body = json.loads(seen[0].content)
    assert VERIFY_LINK in body["text"]
    assert "lemelyig.com/https" not in body["text"]
    assert body["text"].count("https://") == 1


def test_rejected_send_raises_with_status_and_body() -> None:
    """ "422" alone never fixed a sender problem; the reason must survive."""

    def _rejected(_: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text="The lemelyig.com domain is not verified.")

    provider, _ = _provider(_rejected)
    with pytest.raises(ExternalServiceError) as excinfo:
        provider.send_verification("student@example.com", VERIFY_LINK)

    message = str(excinfo.value)
    assert "422" in message
    assert "domain is not verified" in message
    assert "student@example.com" in message


def test_transport_failure_raises_external_service_error() -> None:
    """A connection error is reported as a delivery failure, not a crash."""

    def _boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider, _ = _provider(_boom)
    expected = re.escape("Email delivery to student@example.com failed")
    with pytest.raises(ExternalServiceError, match=expected):
        provider.send_verification("student@example.com", VERIFY_LINK)


def test_the_live_link_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    """The whole point of a real sender is that the credential reaches only the inbox."""
    provider, _ = _provider(_ok)
    with caplog.at_level(logging.DEBUG, logger="lemely.auth.email"):
        provider.send_verification("student@example.com", VERIFY_LINK)

    assert VERIFY_LINK not in caplog.text
    assert "msg_abc123" in caplog.text  # the traceable id is kept


def test_success_with_an_unexpected_body_still_succeeds() -> None:
    """A 2xx means the mail was accepted; an odd body must not undo that."""

    def _odd(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    provider, _ = _provider(_odd)
    provider.send_verification("student@example.com", VERIFY_LINK)  # does not raise


# --------------------------------------------------------------------------
# deps wiring — the credential, not an environment name, picks the provider
# --------------------------------------------------------------------------


def test_deps_wires_the_mock_when_no_key_is_configured() -> None:
    provider = _build_email_provider(Settings())
    assert isinstance(provider, MockEmailProvider)
    assert provider.delivers_out_of_band is False


def test_deps_wires_resend_when_a_key_is_configured() -> None:
    settings = Settings(email=_settings())
    provider = _build_email_provider(settings)
    assert isinstance(provider, ResendEmailProvider)
    assert provider.delivers_out_of_band is True
    provider.close()
