"""MockEmailProvider behaviour and the delivers_out_of_band contract."""

from __future__ import annotations

import logging

import pytest

from lemely.auth.email import MockEmailProvider


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
