"""P5.6 chunk B — the web-push transport seam (D5.9 §4, D5.10).

Every HTTP-level test drives a real :class:`httpx.Client` through
``httpx.MockTransport``, so the request this code would put on the wire is
asserted exactly as built — headers, body and all — without a network.

The VAPID assertion is checked by **decoding it with the public key**, never
by comparing it against bytes this same code produced. A signature test that
only proves the code agrees with itself proves nothing.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from lemely.db.notification_repo import PushSubscriptionRow
from lemely.runtime.config import PushSettings
from lemely.web import deps
from lemely.web.push import (
    NotificationTransport,
    PushNotConfiguredError,
    PushOutcome,
    RecordingPushTransport,
    VapidPushTransport,
    push_audience,
)

FIXED_NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
SUBJECT = "mailto:build@lemely.test"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def keypair() -> tuple[str, str, ec.EllipticCurvePublicKey]:
    """A real P-256 keypair, encoded the way a VAPID key is published.

    Generated rather than hardcoded: the point of these tests is that our
    encoding round-trips through ``cryptography``'s own parsing, and a pinned
    key would test one arbitrary scalar instead of the conversion.
    """
    private = ec.generate_private_key(ec.SECP256R1())
    private_raw = private.private_numbers().private_value.to_bytes(32, "big")
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return _b64url(private_raw), _b64url(public_raw), private.public_key()


@pytest.fixture
def configured(keypair: tuple[str, str, ec.EllipticCurvePublicKey]) -> PushSettings:
    private_b64, public_b64, _ = keypair
    return PushSettings(
        vapid_private_key=private_b64,
        vapid_public_key=public_b64,
        vapid_subject=SUBJECT,
    )


def subscription(
    endpoint: str = "https://push.example.test/v1/abc-123?token=xyz",
) -> PushSubscriptionRow:
    """One stored subscription. The values other than ``endpoint`` are inert here."""
    return PushSubscriptionRow(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        endpoint=endpoint,
        p256dh="p256dh-public-material",
        auth="auth-secret",
        user_agent="Mozilla/5.0",
        created_at=FIXED_NOW,
    )


def client_answering(
    status_code: int, *, capture: list[httpx.Request] | None = None
) -> httpx.Client:
    """An ``httpx.Client`` whose every request gets ``status_code``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(status_code)

    return httpx.Client(transport=httpx.MockTransport(handler))


def transport(settings: PushSettings, *, client: httpx.Client | None = None) -> VapidPushTransport:
    return VapidPushTransport(settings, client=client, now=lambda: FIXED_NOW)


# -- Availability ----------------------------------------------------------


def test_absent_keys_are_unavailable_not_an_error() -> None:
    """D5.9 §4: this build ships with no VAPID keys and must keep working."""
    sender = transport(PushSettings(), client=client_answering(201))

    assert sender.available is False
    result = sender.send(subscription())

    assert result.outcome is PushOutcome.unavailable
    assert result.should_forget is False
    assert result.delivered is False


def test_unavailable_transport_makes_no_http_call() -> None:
    """The absence of keys must short-circuit, not produce an unauthenticated POST."""
    requests: list[httpx.Request] = []
    sender = transport(PushSettings(), client=client_answering(201, capture=requests))

    sender.send(subscription())

    assert requests == []


@pytest.mark.parametrize(
    "missing",
    ["vapid_private_key", "vapid_public_key", "vapid_subject"],
)
def test_a_partial_configuration_is_unavailable(configured: PushSettings, missing: str) -> None:
    """RFC 8292 needs all three; two of them is unavailable, not half-working."""
    partial = configured.model_copy(update={missing: None})

    assert transport(partial).available is False


def test_full_configuration_is_available(configured: PushSettings) -> None:
    assert transport(configured).available is True


def test_signing_without_credentials_raises_rather_than_minting_junk() -> None:
    """``send`` returns ``unavailable``; reaching the signer directly is a bug.

    Producing an assertion from absent keys would fail at the push service
    instead of here, which is a much worse place to find out.
    """
    with pytest.raises(PushNotConfiguredError):
        transport(PushSettings()).authorization_header(subscription().endpoint)


# -- The VAPID assertion ---------------------------------------------------


def test_authorization_header_verifies_against_the_public_key(
    configured: PushSettings, keypair: tuple[str, str, ec.EllipticCurvePublicKey]
) -> None:
    """Decode the assertion with the public key — not against our own bytes."""
    _, public_b64, public_key = keypair
    sub = subscription()
    header = transport(configured).authorization_header(sub.endpoint)

    scheme, _, params = header.partition(" ")
    parts = dict(part.strip().split("=", 1) for part in params.split(","))

    assert scheme == "vapid"
    assert parts["k"] == public_b64

    claims = jwt.decode(
        parts["t"],
        public_key,
        algorithms=["ES256"],
        audience="https://push.example.test",
    )
    assert claims["sub"] == SUBJECT
    assert claims["aud"] == "https://push.example.test"


def test_the_assertion_expires_inside_rfc_8292s_24_hour_cap(configured: PushSettings) -> None:
    """An assertion longer-lived than 24h is rejected by real push services."""
    header = transport(configured).authorization_header(subscription().endpoint)
    token = dict(part.strip().split("=", 1) for part in header.partition(" ")[2].split(","))["t"]

    claims = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
    expiry = datetime.fromtimestamp(claims["exp"], tz=UTC)

    assert FIXED_NOW < expiry <= FIXED_NOW + timedelta(hours=24)


def test_the_audience_is_the_origin_and_never_the_subscription_path() -> None:
    """The path is the nearest thing a subscription has to a secret."""
    assert (
        push_audience("https://fcm.googleapis.com/fcm/send/cXY:APA91b-secret-token")
        == "https://fcm.googleapis.com"
    )


def test_the_signed_audience_excludes_the_endpoint_path(configured: PushSettings) -> None:
    header = transport(configured).authorization_header(
        "https://push.example.test/v1/abc-123?token=xyz"
    )
    token = dict(part.strip().split("=", 1) for part in header.partition(" ")[2].split(","))["t"]

    claims = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})

    assert claims["aud"] == "https://push.example.test"
    assert "abc-123" not in claims["aud"]
    assert "xyz" not in claims["aud"]


# -- What goes on the wire (D5.10) -----------------------------------------


def test_the_push_body_is_empty(configured: PushSettings) -> None:
    """D5.10's load-bearing guard: no student content transits a push service.

    Inverting this — attaching any payload — is precisely the disclosure the
    decision exists to prevent, so the emptiness is asserted on the request
    itself rather than trusted.
    """
    requests: list[httpx.Request] = []
    sender = transport(configured, client=client_answering(201, capture=requests))

    sender.send(subscription())

    assert len(requests) == 1
    assert requests[0].content == b""
    assert requests[0].headers["Content-Length"] == "0"


def test_the_request_carries_ttl_and_authorization(configured: PushSettings) -> None:
    requests: list[httpx.Request] = []
    sender = transport(configured, client=client_answering(201, capture=requests))

    sender.send(subscription())

    assert requests[0].method == "POST"
    assert requests[0].headers["TTL"] == str(configured.ttl_seconds)
    assert requests[0].headers["Authorization"].startswith("vapid t=")


def test_the_request_goes_to_the_subscription_endpoint(configured: PushSettings) -> None:
    requests: list[httpx.Request] = []
    sender = transport(configured, client=client_answering(201, capture=requests))
    sub = subscription("https://push.example.test/v1/target-endpoint")

    sender.send(sub)

    assert str(requests[0].url) == sub.endpoint


# -- Outcomes --------------------------------------------------------------


@pytest.mark.parametrize("status_code", [200, 201, 202, 204])
def test_a_2xx_is_delivered(configured: PushSettings, status_code: int) -> None:
    result = transport(configured, client=client_answering(status_code)).send(subscription())

    assert result.outcome is PushOutcome.delivered
    assert result.delivered is True
    assert result.should_forget is False
    assert result.status_code == status_code


@pytest.mark.parametrize("status_code", [404, 410])
def test_404_and_410_mean_the_subscription_is_gone(
    configured: PushSettings, status_code: int
) -> None:
    """D5.9 §4: a permanently gone browser subscription is deleted, not retried."""
    result = transport(configured, client=client_answering(status_code)).send(subscription())

    assert result.outcome is PushOutcome.expired
    assert result.should_forget is True


@pytest.mark.parametrize("status_code", [400, 401, 429, 500, 503])
def test_other_failures_do_not_delete_the_subscription(
    configured: PushSettings, status_code: int
) -> None:
    """A 503 is this attempt failing, not the endpoint being gone.

    Collapsing these into ``expired`` would evict a perfectly healthy device
    the first time a push service had a bad minute.
    """
    result = transport(configured, client=client_answering(status_code)).send(subscription())

    assert result.outcome is PushOutcome.failed
    assert result.should_forget is False
    assert result.status_code == status_code


def test_a_network_error_is_returned_never_raised(configured: PushSettings) -> None:
    """A push is a side effect of an already-committed action (D5.9 §1)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("push service unreachable", request=request)

    sender = transport(configured, client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = sender.send(subscription())

    assert result.outcome is PushOutcome.failed
    assert result.should_forget is False
    assert result.detail == "ConnectError"


def test_the_result_never_carries_notification_content(configured: PushSettings) -> None:
    """There is no content to leak into a log or a result (D5.10)."""
    result = transport(configured, client=client_answering(500)).send(subscription())

    assert result.detail == "push_service_rejected"


# -- The recording double --------------------------------------------------


def test_the_double_records_what_it_was_asked_to_send() -> None:
    double = RecordingPushTransport()
    first, second = subscription("https://push.test/a"), subscription("https://push.test/b")

    double.send(first)
    double.send(second)

    assert double.endpoints == ["https://push.test/a", "https://push.test/b"]
    assert double.sent == [first, second]


def test_the_double_can_program_one_dead_endpoint_among_live_ones() -> None:
    """The interesting path is a mixed fan-out, not a uniformly happy one."""
    double = RecordingPushTransport()
    double.program("https://push.test/dead", PushOutcome.expired)

    live = double.send(subscription("https://push.test/live"))
    dead = double.send(subscription("https://push.test/dead"))

    assert live.delivered is True
    assert dead.should_forget is True
    assert double.endpoints == ["https://push.test/live", "https://push.test/dead"]


def test_the_double_can_report_itself_unavailable() -> None:
    double = RecordingPushTransport(available=False)

    result = double.send(subscription())

    assert double.available is False
    assert result.outcome is PushOutcome.unavailable
    assert double.sent == [], "an unavailable transport attempted nothing to record"


def test_the_double_can_be_flipped_available_mid_test() -> None:
    double = RecordingPushTransport(available=False)
    double.set_available(True)

    assert double.send(subscription()).delivered is True


def test_reset_forgets_sends_but_keeps_programming() -> None:
    double = RecordingPushTransport()
    double.program("https://push.test/dead", PushOutcome.expired)
    double.send(subscription("https://push.test/dead"))

    double.reset()

    assert double.sent == []
    assert double.send(subscription("https://push.test/dead")).should_forget is True


def test_both_implementations_satisfy_the_protocol(configured: PushSettings) -> None:
    """The seam is only a seam if both sides are interchangeable (D5.9 §4)."""
    assert isinstance(RecordingPushTransport(), NotificationTransport)
    assert isinstance(transport(configured), NotificationTransport)


# -- deps wiring -----------------------------------------------------------


def test_deps_returns_the_real_transport_even_with_no_keys() -> None:
    """Substituting a double when keys are absent would leave this build's
    actual code path untested — so ``deps`` returns the real class and lets it
    report itself unavailable (D5.9 §4)."""
    deps.reset_singletons()
    try:
        sender = deps.get_push_transport()

        assert isinstance(sender, VapidPushTransport)
        assert sender.available is False
    finally:
        deps.reset_singletons()


def test_the_transport_and_notification_service_are_singletons() -> None:
    deps.reset_singletons()
    try:
        assert deps.get_push_transport() is deps.get_push_transport()
        assert deps.get_notification_service() is deps.get_notification_service()
    finally:
        deps.reset_singletons()


def test_reset_singletons_clears_both_new_entries() -> None:
    """A singleton missing from ``reset_singletons`` leaks a stale settings
    object into the next test that swaps configuration."""
    deps.reset_singletons()
    first_transport = deps.get_push_transport()
    first_service = deps.get_notification_service()

    deps.reset_singletons()

    assert deps.get_push_transport() is not first_transport
    assert deps.get_notification_service() is not first_service
    deps.reset_singletons()


def test_the_notification_service_shares_the_preferences_singleton() -> None:
    """One gate, one endpoint, one preferences service — they cannot disagree
    about what the user asked for (D5.9 §2)."""
    deps.reset_singletons()
    try:
        service = deps.get_notification_service()

        assert service._preferences is deps.get_notification_prefs_service()
    finally:
        deps.reset_singletons()
