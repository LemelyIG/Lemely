"""Cloudflare Turnstile server-side verification (``siteverify``).

Used by ``POST /api/waitlist``. The verifier fails closed: any problem reaching Cloudflare, a
non-2xx answer or an unreadable body counts as "not verified". When no secret key is configured
(dev, tests) the dependency yields ``None`` and the route skips the check entirely.
"""

from __future__ import annotations

from typing import Final, Protocol

import httpx
import structlog

log = structlog.get_logger(__name__)

SITEVERIFY_URL: Final = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileVerifier(Protocol):
    """Decides whether a Turnstile token is genuine."""

    def verify(self, token: str, remote_ip: str | None) -> bool:
        """``True`` only when Cloudflare confirms the token. Never raises."""
        ...


class CloudflareTurnstile:
    """The real verifier: one POST to Cloudflare's ``siteverify``."""

    def __init__(
        self, secret_key: str, *, url: str = SITEVERIFY_URL, timeout_seconds: float = 5.0
    ) -> None:
        self._secret = secret_key
        self._url = url
        self._timeout = timeout_seconds

    def verify(self, token: str, remote_ip: str | None) -> bool:
        data = {"secret": self._secret, "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip
        try:
            response = httpx.post(self._url, data=data, timeout=self._timeout)
            response.raise_for_status()
            return bool(response.json().get("success") is True)
        except Exception as exc:
            log.warning("turnstile_verify_failed", error_type=type(exc).__name__)
            return False
