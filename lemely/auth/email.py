"""Email delivery seam for verification and password-reset links.

``EmailProvider`` is the single switch point between the offline mock used in
dev/tests and a real transactional-email service added later — swapping the
implementation injected into :class:`~lemely.auth.service.AuthService` is the
only change required. This is deliberately the same shape as
:mod:`lemely.auth.sms`, because that module already solved this problem and
already reasoned through the dangerous part.

Each provider declares :attr:`EmailProvider.delivers_out_of_band`: whether it
actually gets the link (and, for verification, the code sent alongside it —
spec §4.4/DS15) to the recipient's inbox by a channel outside this API. That
flag — **not** an environment string — is what gates whether the auth routes
may hand the link or code back for §G-06/§G-07's developer affordance,
exactly as D3.16 gates the OTP's ``devCode``. A provider that does deliver
never leaks a live link or code through the API; a provider that does not
deliver is the only situation in which the API is the sole way to obtain
either.

**The honesty rule that follows from it.** ``deps.py`` wires
:class:`MockEmailProvider` unconditionally, so no deployment of this code as
written sends a mail. No screen and no page description may therefore say a
mail *was sent* — they read the flag and say what is true. ``routes.tsx``
records the same problem for the parent OTP screen, which does make that claim;
this seam ships without repeating it.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("lemely.auth.email")


class EmailProvider(Protocol):
    """Delivers an account-lifecycle link to an email address."""

    delivers_out_of_band: bool
    """True when the link (and code) actually reach the inbox by a channel
    outside this API (a real mail service). False means the API is the only
    way to obtain them, which is the sole condition under which a route may
    return either. Any real provider added later **must** set this True."""

    def send_verification(self, email: str, link: str, code: str) -> None:
        """Deliver an email-verification ``link`` and typed ``code`` to ``email``.

        The two are independent, equivalent credentials (spec §4.4/DS15): a
        recipient who cannot follow the link — a different device, a mangled
        mail client — can instead type ``code`` into the app. Raises on
        failure.
        """
        ...

    def send_password_reset(self, email: str, link: str) -> None:
        """Deliver a password-reset ``link`` to ``email``. Raises on failure."""
        ...


class MockEmailProvider:
    """Offline :class:`EmailProvider` that logs the link instead of sending it.

    Intended for local dev and tests: the link (and code) are written to the
    ``lemely.auth.email`` logger at ``INFO`` so a developer can copy either from
    the console. Because nothing reaches an inbox, :attr:`delivers_out_of_band`
    is False and the auth routes may surface both for the §G-06/§G-07 developer
    affordance.
    """

    delivers_out_of_band = False

    def send_verification(self, email: str, link: str, code: str) -> None:
        """Log the verification link and code for ``email`` at INFO level."""
        logger.info("Mock email to %s: verify at %s or enter code %s", email, link, code)

    def send_password_reset(self, email: str, link: str) -> None:
        """Log the reset link for ``email`` at INFO level."""
        logger.info("Mock email to %s: reset your Lemely password at %s", email, link)


__all__ = ["EmailProvider", "MockEmailProvider"]
