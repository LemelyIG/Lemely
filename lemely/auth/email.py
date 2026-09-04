"""Email delivery seam for verification and password-reset links.

``EmailProvider`` is the single switch point between the offline mock used in
dev/tests and the real transactional-email service — swapping the
implementation injected into :class:`~lemely.auth.service.AuthService` is the
only change required. This is deliberately the same shape as
:mod:`lemely.auth.sms`, because that module already solved this problem and
already reasoned through the dangerous part.

Each provider declares :attr:`EmailProvider.delivers_out_of_band`: whether it
actually gets the link to the recipient's inbox by a channel outside this API.
That flag — **not** an environment string — is what gates whether the auth
routes may hand the link back for §G-06/§G-07's developer affordance, exactly
as D3.16 gates the OTP's ``devCode``. A provider that does deliver never leaks
a live link through the API; a provider that does not deliver is the only
situation in which the API is the sole way to obtain it.

**The honesty rule that follows from it.** ``deps.py`` now wires
:class:`ResendEmailProvider` when ``[email] api_key`` is configured and
:class:`MockEmailProvider` when it is not, so whether a mail is really sent is
a deployment fact rather than a constant. No screen and no page description may
therefore *hardcode* the claim that a mail was sent — they read
:attr:`EmailProvider.delivers_out_of_band` and say what is true for the
provider actually running. ``routes.tsx`` records the same problem for the
parent OTP screen, which does make that claim unconditionally; this seam ships
without repeating it.

**Why Resend rather than Cloudflare.** ``lemelyig.com``'s DNS is on Cloudflare
and the SPF/DKIM/DMARC records authorising this sender live in that zone, but
Cloudflare Email Sending is not available on the Workers Free plan: that plan
gets inbound Email Routing plus outbound only to addresses already verified
inside the account, and someone signing up never is. Resend's free tier covers
the same ground at no cost, and the domain a recipient sees is ``lemelyig.com``
either way. ``docs/email-delivery.md`` holds the DNS records and the migration
note for moving to Cloudflare Email Sending should the account ever go Paid.
"""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urljoin

import httpx

from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from lemely.runtime.config import EmailSettings

logger = logging.getLogger("lemely.auth.email")


class EmailProvider(Protocol):
    """Delivers an account-lifecycle link to an email address."""

    delivers_out_of_band: bool
    """True when the link actually reaches the inbox by a channel outside this
    API (a real mail service). False means the API is the only way to obtain
    it, which is the sole condition under which a route may return it. Any real
    provider added later **must** set this True.

    Setting it True carries a second obligation: ``link`` arrives as a
    *frontend route* (``/verify-email/<token>``), and an inbox has no origin to
    resolve that against, so a provider that delivers out of band must join it
    onto a configured origin before sending. Skipping that step is not a
    cosmetic bug — it mails an unreachable ``http:///…`` URL."""

    def send_verification(self, email: str, link: str) -> None:
        """Deliver an email-verification ``link`` to ``email``. Raises on failure."""
        ...

    def send_password_reset(self, email: str, link: str) -> None:
        """Deliver a password-reset ``link`` to ``email``. Raises on failure."""
        ...


class MockEmailProvider:
    """Offline :class:`EmailProvider` that logs the link instead of sending it.

    Intended for local dev and tests: the link is written to the
    ``lemely.auth.email`` logger at ``INFO`` so a developer can copy it from the
    console. Because nothing reaches an inbox, :attr:`delivers_out_of_band` is
    False and the auth routes may surface the link for the §G-06/§G-07 developer
    affordance.
    """

    delivers_out_of_band = False

    def send_verification(self, email: str, link: str) -> None:
        """Log the verification link for ``email`` at INFO level."""
        logger.info("Mock email to %s: verify your Lemely account at %s", email, link)

    def send_password_reset(self, email: str, link: str) -> None:
        """Log the reset link for ``email`` at INFO level."""
        logger.info("Mock email to %s: reset your Lemely password at %s", email, link)


#: Body copy per purpose: (subject, lead paragraph, button label, ignore-notice).
#: Kept as data rather than four near-identical template functions because the
#: two mails differ only in wording. Deliberately states no expiry *duration* —
#: the real lifetimes are ``[auth] email_verification_ttl_seconds`` and
#: ``password_reset_ttl_seconds``, and a number written here would silently
#: drift from them the first time either is tuned.
_TEMPLATES = {
    "verification": (
        "Verify your Lemely email address",
        "Confirm this address to finish setting up your Lemely account.",
        "Verify email address",
        "If you did not create a Lemely account, you can ignore this email.",
    ),
    "password_reset": (
        "Reset your Lemely password",
        "Use the link below to choose a new password for your Lemely account.",
        "Reset password",
        (
            "If you did not ask to reset your password, you can ignore this "
            "email — your current password still works."
        ),
    ),
}


def _render(purpose: str, link: str) -> tuple[str, str, str]:
    """Return ``(subject, html_body, text_body)`` for ``purpose`` and ``link``.

    The HTML is a single document with every style inlined: mail clients strip
    ``<style>`` blocks and external CSS unpredictably, so any rule that must
    survive has to sit on the element. The plain-text part is a real
    alternative rather than a stripped-tags afterthought — a recipient reading
    it must be able to complete the action, so the URL appears in full.
    """
    subject, lead, button, notice = _TEMPLATES[purpose]
    safe_link = html.escape(link, quote=True)

    html_body = (
        '<!doctype html><html lang="en"><body style="margin:0;padding:24px;'
        "background:#f6f7f9;font-family:-apple-system,BlinkMacSystemFont,"
        "'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2933;\">"
        '<div style="max-width:480px;margin:0 auto;background:#ffffff;'
        'border-radius:12px;padding:32px;">'
        f'<h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;">{html.escape(subject)}</h1>'
        f'<p style="margin:0 0 24px;font-size:15px;line-height:1.55;">{html.escape(lead)}</p>'
        f'<p style="margin:0 0 24px;"><a href="{safe_link}" '
        'style="display:inline-block;background:#1f2933;color:#ffffff;'
        "text-decoration:none;padding:12px 20px;border-radius:8px;"
        f'font-size:15px;font-weight:600;">{html.escape(button)}</a></p>'
        '<p style="margin:0 0 8px;font-size:13px;line-height:1.5;color:#52606d;">'
        "If the button does not work, copy this link into your browser:</p>"
        '<p style="margin:0 0 24px;font-size:13px;line-height:1.5;word-break:break-all;">'
        f'<a href="{safe_link}" style="color:#2563eb;">{safe_link}</a></p>'
        '<p style="margin:0;font-size:13px;line-height:1.5;color:#52606d;">'
        f"{html.escape(notice)}</p>"
        "</div></body></html>"
    )

    text_body = f"{subject}\n\n{lead}\n\n{link}\n\n{notice}\n"
    return subject, html_body, text_body


class ResendEmailProvider:
    """Real :class:`EmailProvider` sending over Resend's REST API.

    Synchronous ``httpx`` to match the codebase's call style and
    :class:`~lemely.auth.gotrue.HttpGoTrueBackend` in particular. The client is
    injectable for the same reason
    :class:`~lemely.web.push.VapidPushTransport`'s is: a test can drive real
    status codes through ``httpx.MockTransport`` without a network.

    :attr:`delivers_out_of_band` is True, which is what stops the auth routes
    returning a live link through the API once this provider is wired — the
    link is a bearer credential, and with a real sender the inbox is the only
    place it belongs.

    Failures raise :class:`~lemely.runtime.errors.ExternalServiceError`. Both
    call sites in :class:`~lemely.auth.service.AuthService` already decide what
    a failure means (``_try_send_verification`` swallows it to avoid stranding a
    just-created account; ``_try_send_password_reset`` swallows it to preserve
    anti-enumeration), so raising here is the honest report and never reaches a
    user as a 500.
    """

    delivers_out_of_band = True

    def __init__(self, settings: EmailSettings, client: httpx.Client | None = None) -> None:
        """Build a provider from ``[email]`` settings, optionally with a test client.

        Raises:
            ValueError: ``settings.api_key`` is unset. Callers pick the provider
                by that key's presence (see ``lemely.web.deps``), so reaching
                here without one is a wiring bug, not a runtime condition — and
                a provider that silently could not send while reporting
                ``delivers_out_of_band = True`` would suppress the dev link as
                well, leaving no way at all to obtain it.
        """
        if settings.api_key is None:
            raise ValueError(
                "ResendEmailProvider requires [email] api_key; "
                "wire MockEmailProvider when no key is configured."
            )
        self._settings = settings
        self._api_key = settings.api_key.get_secret_value()
        self._client = client or httpx.Client(timeout=settings.timeout_seconds)

    @property
    def _sender(self) -> str:
        """The ``From:`` header, as ``Display Name <address>``."""
        return f"{self._settings.from_name} <{self._settings.from_address}>"

    def _absolute(self, link: str) -> str:
        """Resolve ``link`` against the configured app origin.

        :class:`~lemely.auth.service.AuthService` mints links as *frontend
        routes* — ``/verify-email/<token>`` — because the SPA navigates to them
        directly and the API returns them as dev links. That is meaningless in
        an inbox: a mail client resolving a root-relative href against no base
        produced ``http:///verify-email/<token>``, an empty-host URL that
        cannot be reached. Absolutising here rather than in ``AuthService``
        keeps the dev link relative, which is what the SPA wants, and puts the
        join at the one boundary that actually requires it.

        :func:`~urllib.parse.urljoin` also makes this idempotent — an already
        absolute link passes through untouched — so a future caller that mints
        full URLs is not double-prefixed.
        """
        return urljoin(self._settings.app_base_url, link)

    def send_verification(self, email: str, link: str) -> None:
        """Send the email-verification ``link`` to ``email``."""
        self._send(email, *_render("verification", self._absolute(link)))

    def send_password_reset(self, email: str, link: str) -> None:
        """Send the password-reset ``link`` to ``email``."""
        self._send(email, *_render("password_reset", self._absolute(link)))

    def _send(self, to: str, subject: str, html_body: str, text_body: str) -> None:
        """POST one mail to Resend, raising :class:`ExternalServiceError` on failure.

        The link is never logged here, on success or on failure: it is a live
        credential, and this provider exists precisely because it should reach
        an inbox and nowhere else. Only the recipient, the subject, and the
        provider's own message id are recorded.
        """
        payload: dict[str, object] = {
            "from": self._sender,
            "to": [to],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        }
        if self._settings.reply_to is not None:
            payload["reply_to"] = self._settings.reply_to

        url = f"{self._settings.api_base_url.rstrip('/')}/emails"
        try:
            response = self._client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"Email delivery to {to} failed: {exc}") from exc

        if response.status_code >= 400:
            # Resend reports the reason in the body; include it, truncated,
            # because "422" alone has never been enough to fix a sender
            # problem (an unverified domain and a malformed From: both 4xx).
            raise ExternalServiceError(
                f"Email delivery to {to} was rejected "
                f"(HTTP {response.status_code}): {response.text[:300]}"
            )

        logger.info("Sent %r email to %s (message id %s)", subject, to, _message_id(response))

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()


def _message_id(response: httpx.Response) -> str:
    """Best-effort provider message id from a success response, for logs only.

    A body that is not the JSON object the API documents is not worth failing a
    send that already returned 2xx — the mail is accepted either way, and this
    value exists only to make a delivery traceable in the provider's dashboard.
    """
    try:
        body = response.json()
    except ValueError:
        return "unknown"
    return str(body.get("id", "unknown")) if isinstance(body, dict) else "unknown"


__all__ = ["EmailProvider", "MockEmailProvider", "ResendEmailProvider"]
