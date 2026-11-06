"""Authenticated encryption for Paymob saved-card tokens (billing spec §4.2, §7).

A card token lets Lemely charge a card without the customer present (Phase 06
merchant-initiated charges), so a database dump must not yield usable tokens.
Tokens are sealed with AES-256-GCM under ``PaymobSettings.card_token_key`` (urlsafe
base64 of 32 random bytes, a deploy secret), with a fresh random 96-bit nonce per
seal. The stored form is ``"v1:" + urlsafe_b64(nonce || ciphertext||tag)``.

* The master key is never used directly: HKDF-SHA256 derives an independent
  encryption key and an independent fingerprint key from it, so the two uses cannot
  interact.
* The version prefix, a purpose label and the **owner's user id** are bound into the
  GCM additional authenticated data (``b"lemely.card-token.v1:" + str(user_id)``). A
  blob sealed for another purpose, relabelled with another version, or moved to
  another user's row fails authentication, so a database writer cannot make one
  user's card charge as another's, and a later key-rotation scheme (``v2:``) can
  coexist with old rows without guessing.
* Because sealing is randomised, the same card arriving twice cannot be matched on
  ciphertext. :meth:`TokenCipher.fingerprint` is an HMAC-SHA256 of the owner's user
  id and the token under the derived fingerprint key: deterministic per (owner,
  card), useless without the key, and two users who share a card do not share a
  fingerprint, so the column cannot link them.
* Failures raise :class:`TokenCipherError` (a ``ValueError``) with fixed messages that
  never contain the token, the key or the ciphertext, and carry no ``__cause__`` or
  ``__context__``; ``repr`` shows no key material.
* Keys and ciphertext bodies are urlsafe base64 only (``-`` and ``_``); the standard
  ``+`` and ``/`` alphabet is rejected. Missing ``=`` padding is tolerated.

Lives in ``lemely.runtime`` (stdlib + ``cryptography`` only), so the ``db`` layer
can use it without importing ``io`` or ``web``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_VERSION = "v1:"
_NONCE_BYTES = 12
_KEY_BYTES = 32
# Bound into every ciphertext as GCM AAD: purpose label plus the format version.
_AAD = b"lemely.card-token.v1"
_ENCRYPTION_INFO = b"lemely.card-token.encryption.v1"
_FINGERPRINT_INFO = b"lemely.card-token.fingerprint.v1"


class TokenCipherError(ValueError):
    """Any key, format or authentication failure; messages never include secrets."""


def _owner(user_id: uuid.UUID) -> bytes:
    """The canonical, fixed-length (36 ASCII bytes) form of the owner id."""
    if not isinstance(user_id, uuid.UUID):
        raise TokenCipherError("card token owner must be a UUID")
    return str(user_id).encode("ascii")


def _aad(user_id: uuid.UUID) -> bytes:
    return _AAD + b":" + _owner(user_id)


def _b64decode(value: str) -> bytes | None:
    """Strict urlsafe base64 decode (padding optional); ``None`` if it is not valid."""
    if "+" in value or "/" in value:  # b64decode(altchars=...) would accept these too
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError, UnicodeError):
        return None


def _derive(master: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=_KEY_BYTES, salt=None, info=info).derive(master)


class TokenCipher:
    """Seal, open and fingerprint card tokens under one 32-byte master key."""

    __slots__ = ("_aead", "_mac_key")

    def __init__(self, key_b64: str) -> None:
        # Failures are raised outside any ``except`` block so no ``__context__`` is kept.
        master = _b64decode(key_b64.strip()) if isinstance(key_b64, str) else None
        if master is None:
            raise TokenCipherError("card token key is not valid urlsafe base64")
        if len(master) != _KEY_BYTES:
            raise TokenCipherError("card token key must decode to exactly 32 bytes")
        self._aead = AESGCM(_derive(master, _ENCRYPTION_INFO))
        self._mac_key = _derive(master, _FINGERPRINT_INFO)

    def __repr__(self) -> str:
        """Fixed text: no key material ever reaches logs or tracebacks."""
        return "TokenCipher(<redacted>)"

    @staticmethod
    def generate_key() -> str:
        """A fresh random key in the form ``card_token_key`` expects."""
        return base64.urlsafe_b64encode(os.urandom(_KEY_BYTES)).decode()

    def encrypt(self, plaintext: str, user_id: uuid.UUID) -> str:
        """Seal ``plaintext`` for ``user_id``; every call yields a different string."""
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, plaintext.encode("utf-8"), _aad(user_id))
        return _VERSION + base64.urlsafe_b64encode(nonce + sealed).decode()

    def decrypt(self, ciphertext: str, user_id: uuid.UUID) -> str:
        """Open a value :meth:`encrypt` sealed for ``user_id``; ``TokenCipherError`` otherwise."""
        aad = _aad(user_id)
        if not isinstance(ciphertext, str) or not ciphertext.startswith(_VERSION):
            raise TokenCipherError("unknown card token ciphertext format")
        raw = _b64decode(ciphertext[len(_VERSION) :])
        if raw is None:
            raise TokenCipherError("card token ciphertext is not valid base64")
        if len(raw) <= _NONCE_BYTES:
            raise TokenCipherError("card token ciphertext is truncated")
        plain: str | None
        try:
            plain = self._aead.decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], aad).decode("utf-8")
        except (InvalidTag, UnicodeDecodeError):
            plain = None
        if plain is None:
            raise TokenCipherError("card token could not be decrypted")
        return plain

    def fingerprint(self, plaintext: str, user_id: uuid.UUID) -> str:
        """Deterministic keyed digest used to recognise ``user_id``'s same card twice."""
        message = _owner(user_id) + b":" + plaintext.encode("utf-8")
        return hmac.new(self._mac_key, message, hashlib.sha256).hexdigest()


__all__ = ["TokenCipher", "TokenCipherError"]
