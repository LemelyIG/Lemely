"""``lemely push-keygen`` (push-delivery spec §5).

The generated pair is checked by **round-tripping** it: a transport built from
the printed keys mints a VAPID header, and the assertion in it verifies against
the printed public key. A keygen test that only checked lengths would prove
the encoding, not that a push service would accept the result.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import jwt
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric import ec

from lemely.app.cli import cli
from lemely.db.notification_repo import PushSubscriptionRow
from lemely.runtime.config import PushSettings
from lemely.runtime.vapid import generate_vapid_keypair, render_push_toml
from lemely.web.push import VapidPushTransport, _b64url_decode, push_audience

ENDPOINT = "https://push.example.test/v1/abc-123"


def _subscription() -> PushSubscriptionRow:
    return PushSubscriptionRow(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        endpoint=ENDPOINT,
        p256dh="p256dh",
        auth="auth",
        user_agent=None,
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
    )


def _verify(public_key_b64: str, header: str) -> dict[str, object]:
    assert header.startswith("vapid t=")
    token = header.removeprefix("vapid t=").split(",", 1)[0]
    raw = _b64url_decode(public_key_b64)
    assert len(raw) == 65 and raw[0] == 0x04, "uncompressed P-256 point"
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    return jwt.decode(token, public, algorithms=["ES256"], audience=push_audience(ENDPOINT))


def test_the_generated_pair_signs_a_header_the_public_key_verifies() -> None:
    pair = generate_vapid_keypair()
    settings = PushSettings(
        vapid_public_key=pair.public_key,
        vapid_private_key=pair.private_key,
        vapid_subject="mailto:ops@example.test",
    )
    # The real clock, deliberately: ``jwt.decode`` below verifies ``exp``, so a
    # pinned past signing time would mint a token that is already expired and
    # the round-trip would fail for a reason that has nothing to do with the
    # keypair. A push service checks expiry against real time too.
    transport = VapidPushTransport(settings)

    assert transport.available is True
    claims = _verify(pair.public_key, transport.authorization_header(ENDPOINT))
    assert claims["sub"] == "mailto:ops@example.test"
    assert len(_b64url_decode(pair.private_key)) == 32
    transport.close()


def test_two_runs_generate_two_different_pairs() -> None:
    assert generate_vapid_keypair() != generate_vapid_keypair()


def test_the_toml_block_loads_as_push_settings() -> None:
    import tomllib

    pair = generate_vapid_keypair()
    block = render_push_toml(pair, "mailto:ops@example.test")
    data = tomllib.loads(block)
    assert PushSettings(**data["push"]).vapid_public_key == pair.public_key


def test_the_command_prints_a_pair_that_round_trips_and_writes_no_file() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli, ["--json", "push-keygen", "--subject", "mailto:ops@example.test"]
        )
        assert result.exit_code == 0, result.output
        import os

        assert os.listdir(".") == [], "push-keygen must write nothing to disk"

    payload = json.loads(result.output)
    settings = PushSettings(
        vapid_public_key=payload["vapid_public_key"],
        vapid_private_key=payload["vapid_private_key"],
        vapid_subject=payload["vapid_subject"],
    )
    transport = VapidPushTransport(settings)  # real clock: see the test above
    claims = _verify(payload["vapid_public_key"], transport.authorization_header(ENDPOINT))
    assert claims["sub"] == "mailto:ops@example.test"
    assert payload["toml"].startswith("[push]\n")
    transport.close()


def test_the_human_output_carries_a_paste_ready_block() -> None:
    result = CliRunner().invoke(cli, ["push-keygen"])
    assert result.exit_code == 0, result.output
    assert "[push]" in result.output
    assert "vapid_private_key = " in result.output
    assert "Rotating" in result.output
