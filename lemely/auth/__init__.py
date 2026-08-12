"""Identity package: GoTrue email/password + self-signed parent phone-OTP.

Public surface (decision D1.4):

* :class:`AuthService` — orchestrates signup/login/OTP.
* :class:`GoTrueBackend` / :class:`HttpGoTrueBackend` — email/password seam.
* :class:`UserMirror` / :class:`DbUserMirror` — ``public.users`` mirror seam.
* :class:`SmsProvider` / :class:`MockSmsProvider` — OTP delivery seam.
* :class:`OtpStore` — in-memory challenge store.
* :func:`mint_otp_token` / :func:`decode_token` — Supabase-compatible tokens.
"""

from __future__ import annotations

from lemely.auth.gotrue import (
    GoTrueBackend,
    GoTrueToken,
    GoTrueUser,
    HttpGoTrueBackend,
)
from lemely.auth.mirror import DbUserMirror, UserMirror
from lemely.auth.otp import OtpChallenge, OtpResult, OtpStore
from lemely.auth.service import AuthResult, AuthService, TokenSigner
from lemely.auth.sms import MockSmsProvider, SmsProvider
from lemely.auth.tokens import Claims, decode_token, mint_otp_token

__all__ = [
    "AuthResult",
    "AuthService",
    "Claims",
    "DbUserMirror",
    "GoTrueBackend",
    "GoTrueToken",
    "GoTrueUser",
    "HttpGoTrueBackend",
    "MockSmsProvider",
    "OtpChallenge",
    "OtpResult",
    "OtpStore",
    "SmsProvider",
    "TokenSigner",
    "UserMirror",
    "decode_token",
    "mint_otp_token",
]
