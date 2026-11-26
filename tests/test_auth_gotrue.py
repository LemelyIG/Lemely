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
from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic import SecretStr

from lemely.auth.gotrue import HttpGoTrueAdmin, HttpGoTrueBackend
from lemely.runtime.config import Settings
from lemely.runtime.errors import AuthError, ExternalServiceError
from tests.auth_fakes import FakeGoTrueBackend

if TYPE_CHECKING:
    from collections.abc import Callable


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


# --- HttpGoTrueAdmin.list_users: paging -------------------------------------------------------
#
# `list_users` feeds the staging purge and the Playwright reset's account cleanup, both of which
# delete whatever it returns, so how it pages decides what they can reach. `httpx.get` is routed
# through an `httpx.MockTransport` client, the same monkeypatch seam as the tests above.

PAGE = HttpGoTrueAdmin._PAGE_SIZE


def _raw_user(email: str | None) -> dict[str, str]:
    user = {"id": str(uuid.uuid4())}
    if email is not None:
        user["email"] = email
    return user


def _serve_pages(
    monkeypatch: pytest.MonkeyPatch, pages: Callable[[int], list[dict[str, str]]]
) -> list[httpx.Request]:
    """Answer ``GET /auth/v1/admin/users?page=N`` with ``pages(N)``; return the requests seen."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"users": pages(int(request.url.params["page"]))})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: client.get(url, **kwargs))
    return seen


def test_list_users_stops_at_the_first_short_page(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _serve_pages(
        monkeypatch,
        lambda _page: [_raw_user("a@example.com"), _raw_user(None), _raw_user("b@example.com")],
    )

    users = HttpGoTrueAdmin(_settings()).list_users()

    assert [u.email for u in users] == ["a@example.com", "b@example.com"]
    assert len(seen) == 1
    assert seen[0].url.params["per_page"] == str(PAGE)
    assert seen[0].headers["apikey"] == "svc-key"
    assert seen[0].headers["authorization"] == "Bearer svc-key"


def test_list_users_counts_email_less_rows_toward_the_page_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full page of which 50 rows have no email is still a full page: read the next one."""

    def pages(page: int) -> list[dict[str, str]]:
        if page == 1:
            return [_raw_user(f"u{i}@example.com") for i in range(PAGE - 50)] + [
                _raw_user(None) for _ in range(50)
            ]
        return [_raw_user("last@example.com")]

    seen = _serve_pages(monkeypatch, pages)

    users = HttpGoTrueAdmin(_settings()).list_users()

    assert len(users) == (PAGE - 50) + 1
    assert users[-1].email == "last@example.com"
    assert [r.url.params["page"] for r in seen] == ["1", "2"]


def test_list_users_raises_when_the_list_never_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    full_page = [_raw_user(f"u{i}@example.com") for i in range(PAGE)]
    seen = _serve_pages(monkeypatch, lambda _page: full_page)

    with pytest.raises(ExternalServiceError, match="page limit"):
        HttpGoTrueAdmin(_settings()).list_users()

    assert len(seen) == 500
