"""GoTrue (Supabase Auth) backend seam.

Email/password identity is delegated to the local Supabase GoTrue stack: an
admin creates the user with the service-role key (email pre-confirmed for dev,
role placed in ``user_metadata``) and a password grant authenticates on login
(decision D1.4). :class:`GoTrueBackend` is the Protocol both the real HTTP client
and the test fake implement, so :class:`~lemely.auth.service.AuthService` never
touches the network in unit tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

import httpx

from lemely.runtime.errors import AuthError, ExternalServiceError

if TYPE_CHECKING:
    from lemely.runtime.config import Settings

_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class GoTrueUser:
    """A GoTrue user record (subset we mirror into ``public.users``)."""

    id: uuid.UUID
    email: str


@dataclass(frozen=True, slots=True)
class GoTrueToken:
    """A GoTrue password-grant response (access token + authenticated user)."""

    access_token: str
    refresh_token: str
    user: GoTrueUser


class GoTrueBackend(Protocol):
    """Admin-create and password-grant operations against GoTrue."""

    def admin_create_user(
        self,
        email: str,
        password: str,
        role: str,
        phone: str | None = None,
    ) -> GoTrueUser:
        """Create a confirmed GoTrue user with ``role`` in ``user_metadata``."""
        ...

    def password_grant(self, email: str, password: str) -> GoTrueToken:
        """Authenticate ``email``/``password`` and return an access token."""
        ...


def _parse_user(body: dict[str, Any]) -> GoTrueUser:
    """Build a :class:`GoTrueUser` from a GoTrue JSON user object."""
    try:
        return GoTrueUser(id=uuid.UUID(str(body["id"])), email=str(body["email"]))
    except (KeyError, ValueError) as exc:
        raise ExternalServiceError(f"Malformed GoTrue user response: {exc}") from exc


class HttpGoTrueBackend:
    """Real :class:`GoTrueBackend` backed by the Supabase GoTrue REST API.

    Uses synchronous ``httpx`` to match the codebase's sync call style. Requires
    the service-role key (admin create) and anon key (password grant) to be
    present in :class:`SupabaseSettings`; a missing key raises
    :class:`~lemely.runtime.errors.ConfigError` at call time via
    :meth:`_service_key` / :meth:`_anon_key`.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise the client against ``settings.supabase``."""
        self._settings = settings
        self._base_url = settings.supabase.url.rstrip("/")

    def _service_key(self) -> str:
        key = self._settings.supabase.service_role_key
        if key is None:
            raise AuthError("Supabase service-role key is not configured.")
        return key.get_secret_value()

    def _anon_key(self) -> str:
        key = self._settings.supabase.anon_key
        if key is None:
            raise AuthError("Supabase anon key is not configured.")
        return key.get_secret_value()

    def admin_create_user(
        self,
        email: str,
        password: str,
        role: str,
        phone: str | None = None,
    ) -> GoTrueUser:
        """Admin-create a confirmed GoTrue user (service-role key)."""
        service_key = self._service_key()
        user_metadata: dict[str, Any] = {"role": role}
        payload: dict[str, Any] = {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": user_metadata,
        }
        if phone is not None:
            payload["phone"] = phone
        try:
            response = httpx.post(
                f"{self._base_url}/auth/v1/admin/users",
                json=payload,
                headers={
                    "Authorization": f"Bearer {service_key}",
                    "apikey": service_key,
                },
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"GoTrue admin-create request failed: {exc}") from exc
        if response.status_code >= 400:
            raise AuthError(f"GoTrue admin-create failed ({response.status_code}): {response.text}")
        return _parse_user(cast("dict[str, Any]", response.json()))

    def password_grant(self, email: str, password: str) -> GoTrueToken:
        """Exchange ``email``/``password`` for a GoTrue access token (anon key)."""
        anon_key = self._anon_key()
        try:
            response = httpx.post(
                f"{self._base_url}/auth/v1/token",
                params={"grant_type": "password"},
                json={"email": email, "password": password},
                headers={"apikey": anon_key},
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"GoTrue password-grant request failed: {exc}") from exc
        if response.status_code >= 400:
            raise AuthError(
                f"GoTrue password-grant failed ({response.status_code}): {response.text}"
            )
        body = cast("dict[str, Any]", response.json())
        try:
            return GoTrueToken(
                access_token=str(body["access_token"]),
                refresh_token=str(body["refresh_token"]),
                user=_parse_user(cast("dict[str, Any]", body["user"])),
            )
        except (KeyError, TypeError) as exc:
            raise ExternalServiceError(f"Malformed GoTrue token response: {exc}") from exc


__all__ = ["GoTrueBackend", "GoTrueToken", "GoTrueUser", "HttpGoTrueBackend"]
