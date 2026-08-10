"""The web-push transport seam: a protocol, a real VAPID sender, a recording double.

D5.9 §4 fixed the shape of this module before any of it was written — web
push cannot be exercised from a headless test, and MISSION §4's Phase-5
acceptance asks explicitly for "push delivery (headless push mock)", so the
sender is chosen behind a :class:`NotificationTransport` protocol rather than
imported directly by whoever wants to notify someone.

**D5.10 fixed what actually goes on the wire: nothing.** A push carries an
empty body and an RFC 8292 VAPID ``Authorization`` header, and the service
worker fetches the inbox over the authenticated API to find out what happened.
That is D5.9 §1's architecture ("the inbox row is the source of truth; a push
is one delivery of it") stated on the wire instead of contradicted by it, and
it keeps every student's notification title and body off Google's, Mozilla's
and Apple's push infrastructure. D5.10 therefore **supersedes D5.9 §4's
``send(subscription, payload)`` sketch** — there is no payload, and a
parameter every implementation ignores would be a lie about the design.

Three things live here and nothing else:

* :class:`NotificationTransport` — the protocol, one method and one property.
* :class:`VapidPushTransport` — the real sender, over the ``httpx`` this
  project already depends on and the ``pyjwt[crypto]`` already in the ``db``
  extra. Zero new dependencies (D5.10).
* :class:`RecordingPushTransport` — the in-memory double that captures what
  would have been sent and can be programmed to answer with any outcome, so
  the ``410 ⇒ forget the subscription`` path is testable without a network.

**Nothing here decides whether a notification exists**, and nothing here
raises into a caller. A push is a best-effort side effect of an action that
has already committed (D5.9 §1); every failure mode is returned as a
:class:`PushResult`, never as an exception. The fail-open router-layer helper
that fans a notification out over a user's subscriptions — the analogue of
:func:`~lemely.web.xp_awards.award_xp_safely` — is chunk C's, not this
module's.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx
import jwt
import structlog
from cryptography.hazmat.primitives.asymmetric import ec

if TYPE_CHECKING:
    from collections.abc import Callable

    from lemely.db.notification_repo import PushSubscriptionRow
    from lemely.runtime.config import PushSettings

log = structlog.get_logger(__name__)

#: RFC 8292 caps the VAPID assertion's lifetime at 24 hours. Half of that
#: leaves room for a clock a few hours out of step without minting a token a
#: push service will reject as expired-on-arrival.
_VAPID_TOKEN_LIFETIME = timedelta(hours=12)

#: A push service answering either of these means the browser subscription is
#: permanently gone, not that this attempt failed (D5.9 §4).
_GONE_STATUSES = frozenset({404, 410})


class PushNotConfiguredError(RuntimeError):
    """Raised when the VAPID signing path is reached without credentials.

    Deliberately *not* what :meth:`VapidPushTransport.send` does — an absent
    key set is a supported state there (D5.9 §4). This exists only so a direct
    caller of :meth:`VapidPushTransport.authorization_header` fails loudly
    rather than receiving an assertion no push service would accept.
    """


class PushOutcome(Enum):
    """What happened to one :meth:`NotificationTransport.send` call."""

    #: The push service accepted the message.
    delivered = "delivered"
    #: No VAPID credentials are configured, so nothing was attempted. Not an
    #: error (D5.9 §4) — this build ships without keys.
    unavailable = "unavailable"
    #: The push service said the subscription is gone (404/410). The caller
    #: must delete it rather than retry.
    expired = "expired"
    #: Anything else: a 5xx, a rejected assertion, a network error.
    failed = "failed"


@dataclass(frozen=True, slots=True)
class PushResult:
    """The outcome of one push attempt, plus enough context to act on it.

    ``outcome`` and :attr:`should_forget` are deliberately separate: only one
    kind of failure means "delete this subscription", and a caller that
    treated every non-delivery that way would evict a healthy endpoint the
    first time a push service returned a 503.
    """

    outcome: PushOutcome
    endpoint: str
    #: The push service's HTTP status, when there was one.
    status_code: int | None = None
    #: A short, non-sensitive reason. Never contains notification content —
    #: there is none to contain (D5.10).
    detail: str | None = None

    @property
    def delivered(self) -> bool:
        """``True`` when the push service accepted the message."""
        return self.outcome is PushOutcome.delivered

    @property
    def should_forget(self) -> bool:
        """``True`` when this endpoint is permanently gone and must be deleted."""
        return self.outcome is PushOutcome.expired


@dataclass(frozen=True, slots=True)
class _VapidCredentials:
    """The three values RFC 8292 requires, all present.

    See :meth:`VapidPushTransport._credentials`.
    """

    public_key: str
    private_key: str
    subject: str


@runtime_checkable
class NotificationTransport(Protocol):
    """One delivery mechanism for a notification that already exists as a row.

    Implementations must never raise: a push is a side effect of an action
    that has already succeeded (D5.9 §1), so every failure is a
    :class:`PushResult`.
    """

    @property
    def available(self) -> bool:
        """Whether this transport can currently send anything at all."""
        ...

    def send(self, subscription: PushSubscriptionRow) -> PushResult:
        """Wake one subscribed device. Returns; never raises."""
        ...


def _b64url_decode(value: str) -> bytes:
    """Decode unpadded base64url, the encoding every VAPID key is published in."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def push_audience(endpoint: str) -> str:
    """Return the RFC 8292 ``aud`` for an endpoint: its origin, and nothing more.

    The audience is the push *service*, not the subscription, so the path —
    which is the closest thing a subscription has to a secret — must not
    appear in the signed assertion.
    """
    parts = urlsplit(endpoint)
    return f"{parts.scheme}://{parts.netloc}"


class VapidPushTransport:
    """Send payload-less RFC 8030 pushes, authorised per RFC 8292 (D5.10).

    Constructed from :class:`~lemely.runtime.config.PushSettings` and an
    injectable clock, the same shape every other service in this codebase
    takes. The ``httpx`` client is injectable too, so a test can drive real
    status codes through ``httpx.MockTransport`` without a network.
    """

    def __init__(
        self,
        settings: PushSettings,
        *,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Wire the transport to its credentials, an HTTP client, and a clock."""
        self._settings = settings
        self._now = now
        self._client = client or httpx.Client(timeout=settings.timeout_seconds)
        self._warned_unavailable = False

    def _credentials(self) -> _VapidCredentials | None:
        """Return the complete credential triple, or ``None`` if any is missing.

        One method answers both "is this transport usable" and "what do I sign
        with", so the availability check and the signing path can never
        disagree about what counts as configured.
        """
        s = self._settings
        if not (s.vapid_public_key and s.vapid_private_key and s.vapid_subject):
            return None
        return _VapidCredentials(
            public_key=s.vapid_public_key,
            private_key=s.vapid_private_key.get_secret_value(),
            subject=s.vapid_subject,
        )

    @property
    def available(self) -> bool:
        """``True`` only when a key pair *and* a contact subject are configured.

        All three are required by RFC 8292; a partial configuration is
        indistinguishable in effect from none, so it is reported as
        unavailable rather than attempted and rejected by every push service.
        """
        return self._credentials() is not None

    def authorization_header(self, endpoint: str) -> str:
        """Mint one RFC 8292 ``vapid t=<jwt>, k=<public key>`` header.

        Public so a test can verify the assertion by *decoding it with the
        public key* rather than by asserting the bytes match what this method
        produced — a signature check that only compares against itself proves
        nothing.

        Raises:
            PushNotConfiguredError: if called without complete credentials.
                :meth:`send` never does — it returns
                :attr:`PushOutcome.unavailable` first — so this is a
                programming error by a direct caller, and it is louder than
                silently minting an assertion no push service would accept.
        """
        credentials = self._credentials()
        if credentials is None:
            msg = "VAPID credentials are not configured"
            raise PushNotConfiguredError(msg)
        raw = _b64url_decode(credentials.private_key)
        signing_key = ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
        claims = {
            "aud": push_audience(endpoint),
            "exp": int((self._now() + _VAPID_TOKEN_LIFETIME).timestamp()),
            "sub": credentials.subject,
        }
        token = jwt.encode(claims, signing_key, algorithm="ES256")
        return f"vapid t={token}, k={credentials.public_key}"

    def send(self, subscription: PushSubscriptionRow) -> PushResult:
        """Wake one device with an empty push. Returns; never raises."""
        if not self.available:
            if not self._warned_unavailable:
                # Once per process, not once per push: a build with no keys
                # would otherwise log a line for every notification it writes.
                log.info("push_transport_unavailable", reason="vapid_keys_not_configured")
                self._warned_unavailable = True
            return PushResult(
                outcome=PushOutcome.unavailable,
                endpoint=subscription.endpoint,
                detail="vapid_keys_not_configured",
            )

        headers = {
            "Authorization": self.authorization_header(subscription.endpoint),
            "TTL": str(self._settings.ttl_seconds),
            "Content-Length": "0",
        }
        try:
            response = self._client.post(
                subscription.endpoint,
                headers=headers,
                content=b"",
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            # A push service being unreachable is routine, not exceptional.
            log.warning("push_send_failed", endpoint_host=push_audience(subscription.endpoint))
            return PushResult(
                outcome=PushOutcome.failed,
                endpoint=subscription.endpoint,
                detail=type(exc).__name__,
            )

        if response.status_code in _GONE_STATUSES:
            return PushResult(
                outcome=PushOutcome.expired,
                endpoint=subscription.endpoint,
                status_code=response.status_code,
                detail="subscription_gone",
            )
        if response.is_success:
            return PushResult(
                outcome=PushOutcome.delivered,
                endpoint=subscription.endpoint,
                status_code=response.status_code,
            )
        log.warning(
            "push_send_rejected",
            endpoint_host=push_audience(subscription.endpoint),
            status_code=response.status_code,
        )
        return PushResult(
            outcome=PushOutcome.failed,
            endpoint=subscription.endpoint,
            status_code=response.status_code,
            detail="push_service_rejected",
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()


class RecordingPushTransport:
    """An in-memory :class:`NotificationTransport` that records instead of sending.

    This is what MISSION §4's "headless push mock" means. It is not a stub
    that always succeeds: outcomes are programmable **per endpoint**, because
    the interesting paths are the failures — a 410 that must delete a
    subscription, and one dead endpoint among three live ones.
    """

    def __init__(
        self,
        *,
        available: bool = True,
        default_outcome: PushOutcome = PushOutcome.delivered,
    ) -> None:
        """Create a double that answers ``default_outcome`` for every endpoint."""
        self._available = available
        self._default_outcome = default_outcome
        self._programmed: dict[str, PushOutcome] = {}
        #: Every subscription this transport was asked to send to, in order,
        #: including the ones it then answered with a failure.
        self.sent: list[PushSubscriptionRow] = []

    @property
    def available(self) -> bool:
        """Whether this double reports itself as usable."""
        return self._available

    def set_available(self, available: bool) -> None:
        """Flip availability, to exercise the unconfigured-keys path."""
        self._available = available

    def program(self, endpoint: str, outcome: PushOutcome) -> None:
        """Make one specific endpoint answer with ``outcome``."""
        self._programmed[endpoint] = outcome

    @property
    def endpoints(self) -> list[str]:
        """The endpoints sent to, in order — the usual thing a test asserts on."""
        return [subscription.endpoint for subscription in self.sent]

    def reset(self) -> None:
        """Forget what was sent, keeping the programmed outcomes."""
        self.sent.clear()

    def send(self, subscription: PushSubscriptionRow) -> PushResult:
        """Record the attempt and answer with the programmed outcome."""
        if not self._available:
            return PushResult(
                outcome=PushOutcome.unavailable,
                endpoint=subscription.endpoint,
                detail="vapid_keys_not_configured",
            )
        self.sent.append(subscription)
        outcome = self._programmed.get(subscription.endpoint, self._default_outcome)
        return PushResult(
            outcome=outcome,
            endpoint=subscription.endpoint,
            detail=None if outcome is PushOutcome.delivered else outcome.value,
        )


__all__ = [
    "NotificationTransport",
    "PushNotConfiguredError",
    "PushOutcome",
    "PushResult",
    "RecordingPushTransport",
    "VapidPushTransport",
    "push_audience",
]
