"""SMS delivery seam for phone-OTP.

``SmsProvider`` is the single switch point between the offline mock provider used
in dev/tests and a real SMS gateway (Twilio/etc.) added later — swapping the
implementation injected into :class:`~lemely.auth.service.AuthService` is the only
change required. The mock provider logs the code and never returns it, so an OTP
secret is never leaked through a return value.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("lemely.auth.sms")


class SmsProvider(Protocol):
    """Delivers a one-time code to a phone number."""

    def send_code(self, phone: str, code: str) -> None:
        """Deliver ``code`` to ``phone``. Raises on delivery failure."""
        ...


class MockSmsProvider:
    """Offline ``SmsProvider`` that logs the OTP instead of sending an SMS.

    Intended for local dev and tests: the code is written to the
    ``lemely.auth.sms`` logger at ``INFO`` so a developer can read it from the
    console, but it is never returned to the caller.
    """

    def send_code(self, phone: str, code: str) -> None:
        """Log the OTP for ``phone`` at INFO level (never returns the code)."""
        logger.info("Mock SMS to %s: your Lemely code is %s", phone, code)


__all__ = ["MockSmsProvider", "SmsProvider"]
