"""TokenCipher: saved-card tokens encrypted at rest (billing spec §4.2, §7)."""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lemely.runtime.token_cipher import TokenCipher

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
OTHER_KEY = base64.urlsafe_b64encode(b"o" * 32).decode()
TOKEN = "3f22ce8a4e5b6c7d8e9f0a1b2c3d4e5f"


def test_round_trip() -> None:
    cipher = TokenCipher(KEY)
    sealed = cipher.encrypt(TOKEN)
    assert sealed.startswith("v1:")
    assert TOKEN not in sealed
    assert cipher.decrypt(sealed) == TOKEN


def test_round_trip_non_ascii_and_empty() -> None:
    cipher = TokenCipher(KEY)
    for value in ("", "tokén-☃"):
        assert cipher.decrypt(cipher.encrypt(value)) == value


def test_each_encryption_uses_a_fresh_nonce() -> None:
    cipher = TokenCipher(KEY)
    assert cipher.encrypt(TOKEN) != cipher.encrypt(TOKEN)
    nonces = {base64.urlsafe_b64decode(cipher.encrypt(TOKEN)[3:])[:12] for _ in range(50)}
    assert len(nonces) == 50


def test_nonce_is_96_bits() -> None:
    raw = base64.urlsafe_b64decode(TokenCipher(KEY).encrypt(TOKEN)[3:])
    # 12-byte nonce + plaintext + 16-byte GCM tag.
    assert len(raw) == 12 + len(TOKEN) + 16


def test_tampering_is_detected() -> None:
    cipher = TokenCipher(KEY)
    sealed = cipher.encrypt(TOKEN)
    raw = bytearray(base64.urlsafe_b64decode(sealed[3:]))
    raw[-1] ^= 0x01
    with pytest.raises(ValueError, match="could not be decrypted"):
        cipher.decrypt("v1:" + base64.urlsafe_b64encode(bytes(raw)).decode())


def test_tampered_nonce_is_detected() -> None:
    cipher = TokenCipher(KEY)
    raw = bytearray(base64.urlsafe_b64decode(cipher.encrypt(TOKEN)[3:]))
    raw[0] ^= 0x01
    with pytest.raises(ValueError, match="could not be decrypted"):
        cipher.decrypt("v1:" + base64.urlsafe_b64encode(bytes(raw)).decode())


def test_the_wrong_key_cannot_decrypt() -> None:
    sealed = TokenCipher(KEY).encrypt(TOKEN)
    with pytest.raises(ValueError, match="could not be decrypted"):
        TokenCipher(OTHER_KEY).decrypt(sealed)


def test_ciphertext_is_bound_to_its_purpose() -> None:
    """A blob sealed under the same key for another purpose (other AAD) is refused."""
    cipher = TokenCipher(KEY)
    # Reach the derived encryption key the way a sibling feature sharing the master
    # key would not be able to: seal with the cipher's own AEAD but a different AAD.
    nonce = b"n" * 12
    foreign = cipher._aead.encrypt(nonce, TOKEN.encode(), b"lemely.some-other-purpose")
    blob = "v1:" + base64.urlsafe_b64encode(nonce + foreign).decode()
    with pytest.raises(ValueError, match="could not be decrypted"):
        cipher.decrypt(blob)


def test_encryption_key_is_not_the_raw_master_key() -> None:
    """Sealing with the raw master key must not produce something the cipher opens."""
    nonce = b"n" * 12
    raw_sealed = AESGCM(b"k" * 32).encrypt(nonce, TOKEN.encode(), b"lemely.card-token.v1")
    blob = "v1:" + base64.urlsafe_b64encode(nonce + raw_sealed).decode()
    with pytest.raises(ValueError, match="could not be decrypted"):
        TokenCipher(KEY).decrypt(blob)


@pytest.mark.parametrize("bad", ["", "v2:abcd", "v1:", "v1:!!!", "plain"])
def test_malformed_ciphertext_is_a_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        TokenCipher(KEY).decrypt(bad)


def test_non_text_and_non_ascii_ciphertext_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        TokenCipher(KEY).decrypt("v1:éééé")
    with pytest.raises(ValueError):
        TokenCipher(KEY).decrypt(None)  # type: ignore[arg-type]


def test_failures_do_not_leak_plaintext_or_key() -> None:
    cipher = TokenCipher(KEY)
    sealed = cipher.encrypt(TOKEN)
    for attempt in (
        lambda: TokenCipher(OTHER_KEY).decrypt(sealed),
        lambda: cipher.decrypt("v1:!!"),
    ):
        with pytest.raises(ValueError) as info:
            attempt()
        text = repr(info.value) + str(info.value.__cause__)
        assert TOKEN not in text
        assert KEY not in text
        assert OTHER_KEY not in text


def test_a_key_that_is_not_32_bytes_is_refused() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        TokenCipher(base64.urlsafe_b64encode(b"short").decode())


def test_a_key_that_is_not_base64_is_refused_without_echoing_it() -> None:
    bad = "not*base64*key*not*base64*key*not*base64*key"
    with pytest.raises(ValueError, match="base64") as info:
        TokenCipher(bad)
    assert bad not in str(info.value)


def test_unpadded_keys_are_accepted() -> None:
    assert TokenCipher(KEY.rstrip("=")).decrypt(TokenCipher(KEY).encrypt(TOKEN)) == TOKEN


def test_repr_and_str_never_show_key_material() -> None:
    cipher = TokenCipher(KEY)
    for text in (repr(cipher), str(cipher), f"{cipher!r}"):
        assert KEY not in text
        assert KEY.rstrip("=") not in text
        assert "kkkk" not in text


def test_fingerprint_is_deterministic_and_keyed() -> None:
    a, b = TokenCipher(KEY), TokenCipher(OTHER_KEY)
    assert a.fingerprint(TOKEN) == a.fingerprint(TOKEN)
    assert len(a.fingerprint(TOKEN)) == 64
    assert a.fingerprint(TOKEN) != b.fingerprint(TOKEN)
    assert a.fingerprint(TOKEN) != a.fingerprint(TOKEN + "x")
    assert TOKEN not in a.fingerprint(TOKEN)


def test_fingerprint_uses_a_key_derived_separately_from_the_master_key() -> None:
    naive = hmac.new(b"k" * 32, TOKEN.encode(), hashlib.sha256).hexdigest()
    assert TokenCipher(KEY).fingerprint(TOKEN) != naive


def test_generated_keys_work() -> None:
    key = TokenCipher.generate_key()
    assert TokenCipher(key).decrypt(TokenCipher(key).encrypt(TOKEN)) == TOKEN
    assert TokenCipher.generate_key() != key
