"""SMS delivery seam for phone-OTP.

``SmsProvider`` is the single switch point between the offline mock provider used
in dev/tests and a real SMS gateway (Twilio/etc.) added later — swapping the
implementation injected into :class:`~lemely.auth.service.AuthService` is the only
change required.

Each provider also declares :attr:`SmsProvider.delivers_out_of_band`: whether it
actually gets the code to the handset by a channel outside this API. That flag —
**not** an environment string — is what gates whether
:meth:`~lemely.auth.service.AuthService.request_otp` may hand the code back for
``docs/LEMELY_UI_SPEC.md`` §G-05's developer affordance (D3.16). A provider that
does deliver never leaks a live code through the API; a provider that does not
deliver is the only situation in which the API is the sole way to obtain it.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("lemely.auth.sms")


class SmsProvider(Protocol):
    """Delivers a one-time code to a phone number."""

    delivers_out_of_band: bool
    """True when the code actually reaches the handset by a channel outside this
    API (a real SMS gateway). False means the API is the only way to obtain it,
    which is the sole condition under which ``request_otp`` may return it (D3.16).
    Any real provider added later **must** set this True."""

    def send_code(self, phone: str, code: str) -> None:
        """Deliver ``code`` to ``phone``. Raises on delivery failure."""
        ...


class MockSmsProvider:
    """Offline ``SmsProvider`` that logs the OTP instead of sending an SMS.

    Intended for local dev and tests: the code is written to the
    ``lemely.auth.sms`` logger at ``INFO`` so a developer can read it from the
    console. Because nothing reaches the parent's handset,
    :attr:`delivers_out_of_band` is False and
    :meth:`~lemely.auth.service.AuthService.request_otp` may surface the code for
    the §G-05 developer affordance (D3.16).
    """

    delivers_out_of_band = False

    def send_code(self, phone: str, code: str) -> None:
        """Log the OTP for ``phone`` at INFO level (never returns the code)."""
        logger.info("Mock SMS to %s: your Lemely code is %s", phone, code)


__all__ = ["MockSmsProvider", "SmsProvider"]
