"""TokenCipher: saved-card tokens encrypted at rest (billing spec §4.2, §7)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lemely.runtime.token_cipher import TokenCipher, TokenCipherError

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
OTHER_KEY = base64.urlsafe_b64encode(b"o" * 32).decode()
TOKEN = "3f22ce8a4e5b6c7d8e9f0a1b2c3d4e5f"

# Known answers pin the at-rest format: any change to the key derivation (labels, salt,
# hash), the AAD, the nonce layout or the fingerprint algorithm makes rows already in the
# database unreadable, so these constants must never be "regenerated" to make a test pass.
# SEALED_V1 is KEY sealing TOKEN for USER with nonce bytes 00..0b and AAD
# b"lemely.card-token.v1:" + str(USER) (R22: the owner is bound into the AAD and the
# fingerprint). FINGERPRINT_V1 is HMAC-SHA256 under the HKDF fingerprint key over
# str(USER) + b":" + TOKEN.
USER = uuid.UUID("11111111-2222-4333-8444-555555555555")
OTHER_USER = uuid.UUID("66666666-7777-4888-8999-aaaaaaaaaaaa")
SEALED_V1 = "v1:AAECAwQFBgcICQoLnKXV-P8OGBLPw_i_f8qTAUrfoigNVbRHQQH-b2TsbhBY5Nl4DtI27E_AU0KQclso"
FINGERPRINT_V1 = "c3bc60b0043fa2f0768249da8b1b215c75eb63d22888dceea0910e7af3794a77"
AAD_V1 = b"lemely.card-token.v1:" + str(USER).encode()
NONCE = bytes(range(12))


def _blob(cipher: TokenCipher, aad: bytes | None) -> str:
    sealed = cipher._aead.encrypt(NONCE, TOKEN.encode(), aad)
    return "v1:" + base64.urlsafe_b64encode(NONCE + sealed).decode()


def test_known_answer_blob_decrypts() -> None:
    assert TokenCipher(KEY).decrypt(SEALED_V1, USER) == TOKEN


def test_known_answer_blob_is_reproduced_by_the_pinned_aad() -> None:
    assert _blob(TokenCipher(KEY), AAD_V1) == SEALED_V1


def test_known_answer_fingerprint() -> None:
    assert TokenCipher(KEY).fingerprint(TOKEN, USER) == FINGERPRINT_V1


def test_derived_keys_are_independent_of_each_other_and_the_master_key() -> None:
    cipher = TokenCipher(KEY)
    mac_key = cipher._mac_key
    assert mac_key != b"k" * 32
    # If the fingerprint key were also the encryption key, a blob sealed under it would open.
    foreign = AESGCM(mac_key).encrypt(NONCE, TOKEN.encode(), AAD_V1)
    blob = "v1:" + base64.urlsafe_b64encode(NONCE + foreign).decode()
    with pytest.raises(TokenCipherError, match="could not be decrypted"):
        cipher.decrypt(blob, USER)


def test_round_trip() -> None:
    cipher = TokenCipher(KEY)
    sealed = cipher.encrypt(TOKEN, USER)
    assert sealed.startswith("v1:")
    assert TOKEN not in sealed
    assert cipher.decrypt(sealed, USER) == TOKEN


def test_round_trip_non_ascii_and_empty() -> None:
    cipher = TokenCipher(KEY)
    for value in ("", "tokén-☃"):
        assert cipher.decrypt(cipher.encrypt(value, USER), USER) == value


def test_each_encryption_uses_a_fresh_nonce() -> None:
    cipher = TokenCipher(KEY)
    assert cipher.encrypt(TOKEN, USER) != cipher.encrypt(TOKEN, USER)
    nonces = {base64.urlsafe_b64decode(cipher.encrypt(TOKEN, USER)[3:])[:12] for _ in range(50)}
    assert len(nonces) == 50


def test_nonce_is_96_bits() -> None:
    raw = base64.urlsafe_b64decode(TokenCipher(KEY).encrypt(TOKEN, USER)[3:])
    # 12-byte nonce + plaintext + 16-byte GCM tag.
    assert len(raw) == 12 + len(TOKEN) + 16


def test_tampering_is_detected() -> None:
    cipher = TokenCipher(KEY)
    sealed = cipher.encrypt(TOKEN, USER)
    raw = bytearray(base64.urlsafe_b64decode(sealed[3:]))
    raw[-1] ^= 0x01
    with pytest.raises(TokenCipherError, match="could not be decrypted"):
        cipher.decrypt("v1:" + base64.urlsafe_b64encode(bytes(raw)).decode(), USER)


def test_tampered_nonce_is_detected() -> None:
    cipher = TokenCipher(KEY)
    raw = bytearray(base64.urlsafe_b64decode(cipher.encrypt(TOKEN, USER)[3:]))
    raw[0] ^= 0x01
    with pytest.raises(TokenCipherError, match="could not be decrypted"):
        cipher.decrypt("v1:" + base64.urlsafe_b64encode(bytes(raw)).decode(), USER)


def test_the_wrong_key_cannot_decrypt() -> None:
    sealed = TokenCipher(KEY).encrypt(TOKEN, USER)
    with pytest.raises(TokenCipherError, match="could not be decrypted"):
        TokenCipher(OTHER_KEY).decrypt(sealed, USER)


@pytest.mark.parametrize(
    "aad",
    [
        None,
        b"",
        b"lemely.card-token.v1",  # the pre-R22 label with no owner
        b"lemely.card-token.v2:" + str(USER).encode(),
        b"lemely.other-purpose.v1:" + str(USER).encode(),
        b"lemely.card-token.v1:" + str(OTHER_USER).encode(),
    ],
)
def test_ciphertext_is_bound_to_its_purpose(aad: bytes | None) -> None:
    """A blob sealed under the same key with any other AAD is refused."""
    with pytest.raises(TokenCipherError, match="could not be decrypted"):
        TokenCipher(KEY).decrypt(_blob(TokenCipher(KEY), aad), USER)


def test_encryption_key_is_not_the_raw_master_key() -> None:
    """Sealing with the raw master key must not produce something the cipher opens."""
    nonce = b"n" * 12
    raw_sealed = AESGCM(b"k" * 32).encrypt(nonce, TOKEN.encode(), AAD_V1)
    blob = "v1:" + base64.urlsafe_b64encode(nonce + raw_sealed).decode()
    with pytest.raises(TokenCipherError, match="could not be decrypted"):
        TokenCipher(KEY).decrypt(blob, USER)


@pytest.mark.parametrize("bad", ["", "v2:abcd", "v1:", "v1:!!!", "plain"])
def test_malformed_ciphertext_is_a_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        TokenCipher(KEY).decrypt(bad, USER)


def test_non_text_and_non_ascii_ciphertext_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        TokenCipher(KEY).decrypt("v1:éééé", USER)
    with pytest.raises(ValueError):
        TokenCipher(KEY).decrypt(None, USER)  # type: ignore[arg-type]


def test_failures_do_not_leak_plaintext_or_key() -> None:
    cipher = TokenCipher(KEY)
    sealed = cipher.encrypt(TOKEN, USER)
    for attempt in (
        lambda: TokenCipher(OTHER_KEY).decrypt(sealed, USER),
        lambda: cipher.decrypt("v1:!!", USER),
    ):
        with pytest.raises(ValueError) as info:
            attempt()
        assert info.value.__cause__ is None
        assert info.value.__context__ is None
        text = repr(info.value)
        assert TOKEN not in text
        assert KEY not in text
        assert OTHER_KEY not in text


def test_a_key_that_is_not_32_bytes_is_refused() -> None:
    with pytest.raises(TokenCipherError, match="32 bytes"):
        TokenCipher(base64.urlsafe_b64encode(b"short").decode())


def test_a_key_that_is_not_base64_is_refused_without_echoing_it() -> None:
    bad = "not*base64*key*not*base64*key*not*base64*key"
    with pytest.raises(TokenCipherError, match="base64") as info:
        TokenCipher(bad)
    assert bad not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


def test_unpadded_keys_are_accepted() -> None:
    assert (
        TokenCipher(KEY.rstrip("=")).decrypt(TokenCipher(KEY).encrypt(TOKEN, USER), USER) == TOKEN
    )


def test_repr_and_str_never_show_key_material() -> None:
    cipher = TokenCipher(KEY)
    assert repr(cipher) == "TokenCipher(<redacted>)"
    assert str(cipher) == "TokenCipher(<redacted>)"
    assert not hasattr(cipher, "__dict__")


def test_fingerprint_is_deterministic_and_keyed() -> None:
    a, b = TokenCipher(KEY), TokenCipher(OTHER_KEY)
    assert a.fingerprint(TOKEN, USER) == a.fingerprint(TOKEN, USER)
    assert len(a.fingerprint(TOKEN, USER)) == 64
    assert a.fingerprint(TOKEN, USER) != b.fingerprint(TOKEN, USER)
    assert a.fingerprint(TOKEN, USER) != a.fingerprint(TOKEN + "x", USER)
    assert TOKEN not in a.fingerprint(TOKEN, USER)


def test_fingerprint_uses_a_key_derived_separately_from_the_master_key() -> None:
    naive = hmac.new(b"k" * 32, TOKEN.encode(), hashlib.sha256).hexdigest()
    assert TokenCipher(KEY).fingerprint(TOKEN, USER) != naive


def test_generated_keys_work() -> None:
    key = TokenCipher.generate_key()
    assert TokenCipher(key).decrypt(TokenCipher(key).encrypt(TOKEN, USER), USER) == TOKEN
    assert TokenCipher.generate_key() != key


def test_every_failure_is_a_token_cipher_error_and_a_value_error() -> None:
    assert issubclass(TokenCipherError, ValueError)
    cipher = TokenCipher(KEY)
    for bad in ("", "v2:abcd", "v1:", "v1:!!!", "plain", "v1:\u00e9\u00e9\u00e9\u00e9", None):
        with pytest.raises(TokenCipherError):
            cipher.decrypt(bad, USER)  # type: ignore[arg-type]
    for bad_key in ("", "!!!", base64.urlsafe_b64encode(b"short").decode(), None):
        with pytest.raises(TokenCipherError):
            TokenCipher(bad_key)  # type: ignore[arg-type]


def test_only_the_urlsafe_alphabet_is_accepted() -> None:
    # 32 bytes whose standard base64 contains "+" and "/" (urlsafe uses "-" and "_").
    raw = bytes([0xFB, 0xFF] * 16)
    urlsafe = base64.urlsafe_b64encode(raw).decode()
    standard = base64.b64encode(raw).decode()
    assert "-" in urlsafe
    assert "_" in urlsafe
    assert "+" in standard
    assert "/" in standard
    TokenCipher(urlsafe)
    with pytest.raises(TokenCipherError, match="base64"):
        TokenCipher(standard)
    sealed = TokenCipher(KEY).encrypt(TOKEN, USER)
    body = sealed[3:]
    assert TokenCipher(KEY).decrypt("v1:" + body.rstrip("="), USER) == TOKEN
    with pytest.raises(TokenCipherError):
        TokenCipher(KEY).decrypt("v1:" + body.replace("-", "+").replace("_", "/") + "+", USER)


# -- R22: saved-card tokens are bound to their owner --------------------------


def test_a_blob_sealed_for_one_user_cannot_be_opened_as_another() -> None:
    cipher = TokenCipher(KEY)
    sealed = cipher.encrypt(TOKEN, USER)
    assert cipher.decrypt(sealed, USER) == TOKEN
    with pytest.raises(TokenCipherError, match="could not be decrypted"):
        cipher.decrypt(sealed, OTHER_USER)


def test_the_known_answer_blob_is_not_valid_for_another_owner() -> None:
    with pytest.raises(TokenCipherError, match="could not be decrypted"):
        TokenCipher(KEY).decrypt(SEALED_V1, OTHER_USER)


def test_the_same_card_has_a_different_fingerprint_per_user_and_a_stable_one_per_owner() -> None:
    cipher = TokenCipher(KEY)
    assert cipher.fingerprint(TOKEN, USER) == cipher.fingerprint(TOKEN, USER)
    assert cipher.fingerprint(TOKEN, USER) != cipher.fingerprint(TOKEN, OTHER_USER)


def test_the_fingerprint_binds_the_owner_not_just_the_token() -> None:
    unbound = hmac.new(TokenCipher(KEY)._mac_key, TOKEN.encode(), hashlib.sha256).hexdigest()
    assert TokenCipher(KEY).fingerprint(TOKEN, USER) != unbound


def test_a_user_id_that_is_not_a_uuid_is_refused() -> None:
    cipher = TokenCipher(KEY)
    sealed = cipher.encrypt(TOKEN, USER)
    for bad in (str(USER), None, USER.bytes):
        with pytest.raises(TokenCipherError, match="owner"):
            cipher.encrypt(TOKEN, bad)  # type: ignore[arg-type]
        with pytest.raises(TokenCipherError, match="owner"):
            cipher.decrypt(sealed, bad)  # type: ignore[arg-type]
        with pytest.raises(TokenCipherError, match="owner"):
            cipher.fingerprint(TOKEN, bad)  # type: ignore[arg-type]
