"""Hermetic tests for the GoTrue seam's admin_update_user_password.

Two layers, both without touching the network:

* The Protocol contract, asserted against ``FakeGoTrueBackend`` (per the
  plan: "assert against the fake, not the network") — this is what every
  hermetic auth test in the suite relies on being a faithful stand-in.
* ``HttpGoTrueBackend``'s HTTP-level behaviour, asserted by monkeypatching
  ``httpx.put``, matching the pattern ``test_storage.py`` established for
  ``HttpGoTrueBackend``'s sibling seam (``HttpStorageBackend``) after that
  seam shipped with no hermetic coverage at all.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from pydantic import SecretStr

from lemely.auth.gotrue import HttpGoTrueBackend
from lemely.runtime.config import Settings
from lemely.runtime.errors import AuthError, ExternalServiceError
from tests.auth_fakes import FakeGoTrueBackend


def test_admin_update_user_password_changes_the_credential() -> None:
    """The fake records the new password; a subsequent password_grant with the
    old one fails and with the new one succeeds."""
    backend = FakeGoTrueBackend()
    user = backend.admin_create_user("student@example.com", "old-pw-123456", "student")

    backend.admin_update_user_password(user.id, "new-pw-654321")

    with pytest.raises(AuthError):
        backend.password_grant("student@example.com", "old-pw-123456")
    token = backend.password_grant("student@example.com", "new-pw-654321")
    assert token.user.id == user.id


def test_admin_update_user_password_for_an_unknown_user_raises_auth_error() -> None:
    backend = FakeGoTrueBackend()
    with pytest.raises(AuthError):
        backend.admin_update_user_password(uuid.uuid4(), "new-pw-654321")


def _settings() -> Settings:
    base = Settings()
    return base.model_copy(
        update={
            "supabase": base.supabase.model_copy(update={"service_role_key": SecretStr("svc-key")})
        }
    )


def _fake_response(status_code: int, text: str = "") -> httpx.Response:
    return httpx.Response(
        status_code,
        text=text,
        request=httpx.Request("PUT", "http://example.invalid"),
    )


def test_http_backend_admin_update_user_password_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "put", lambda *a, **k: _fake_response(200))
    backend = HttpGoTrueBackend(_settings())
    backend.admin_update_user_password(uuid.uuid4(), "new-pw")  # no raise


def test_http_backend_admin_update_user_password_maps_non_2xx_to_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "put", lambda *a, **k: _fake_response(404, "not found"))
    backend = HttpGoTrueBackend(_settings())
    with pytest.raises(AuthError):
        backend.admin_update_user_password(uuid.uuid4(), "new-pw")


def test_http_backend_admin_update_user_password_maps_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*a: object, **k: object) -> httpx.Response:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "put", _raise)
    backend = HttpGoTrueBackend(_settings())
    with pytest.raises(ExternalServiceError):
        backend.admin_update_user_password(uuid.uuid4(), "new-pw")


def test_http_backend_admin_update_user_password_sends_service_role_key_and_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _capture(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _fake_response(200)

    monkeypatch.setattr(httpx, "put", _capture)
    backend = HttpGoTrueBackend(_settings())
    user_id = uuid.uuid4()
    backend.admin_update_user_password(user_id, "new-pw")

    settings = _settings()
    assert captured["url"] == f"{settings.supabase.url.rstrip('/')}/auth/v1/admin/users/{user_id}"
    kwargs = captured["kwargs"]
    assert kwargs["json"] == {"password": "new-pw"}
    headers = kwargs["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer svc-key"
    assert headers["apikey"] == "svc-key"
