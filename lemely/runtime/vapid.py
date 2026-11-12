"""Generate a VAPID (RFC 8292) application-server keypair (push-delivery spec §5).

Lives in ``lemely.runtime`` rather than beside the transport so the CLI can
import it without pulling in the web layer, and so it can never depend on
``lemely.core``/``lemely.io``/``lemely.app`` (import-linter). It writes no
file: the private key never touches disk through this module, so there is no
half-written secret to forget about.

The encodings are the ones every push service and every browser expect, and
the ones :class:`~lemely.web.push.VapidPushTransport` decodes:

* the public key is the **uncompressed** P-256 point, 65 bytes, base64url
  without padding — the value a browser passes to ``pushManager.subscribe``
  as ``applicationServerKey``;
* the private key is the 32-byte scalar, base64url without padding.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


@dataclass(frozen=True, slots=True)
class VapidKeyPair:
    """One freshly generated keypair, both halves base64url-encoded."""

    public_key: str
    private_key: str


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_vapid_keypair() -> VapidKeyPair:
    """Generate a P-256 keypair in the shapes RFC 8292 and the browser need."""
    private = ec.generate_private_key(ec.SECP256R1())
    private_raw = private.private_numbers().private_value.to_bytes(32, "big")
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return VapidKeyPair(public_key=_b64url(public_raw), private_key=_b64url(private_raw))


def render_push_toml(pair: VapidKeyPair, subject: str) -> str:
    """A paste-ready ``[push]`` block for ``lemely.toml``.

    ``lemely.toml`` is gitignored, but the private key still does not belong
    on disk where it can be avoided — the deploy pipeline reads it from a
    repository secret. The block is offered because a local test of real push
    needs it somewhere the settings loader reads.
    """
    return (
        "[push]\n"
        f'vapid_public_key = "{pair.public_key}"\n'
        f'vapid_private_key = "{pair.private_key}"\n'
        f'vapid_subject = "{subject}"\n'
    )


__all__ = ["VapidKeyPair", "generate_vapid_keypair", "render_push_toml"]
