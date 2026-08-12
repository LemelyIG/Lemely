"""P5.6 chunk C — the fail-open notify helper (:mod:`lemely.web.notify`).

No database here, deliberately. :func:`~lemely.web.notify.notify_safely` is
pure orchestration over two collaborators, and the behaviours worth pinning
are precisely the ones a real Postgres makes *harder* to arrange: a service
that raises, a push endpoint that 410s, quiet hours in force. Chunk A already
tests the real :class:`~lemely.db.notification_repo.NotificationService`
against a live database; repeating that here would test SQLAlchemy twice and
the orchestration once.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from lemely.db.models.enums import NotificationType
from lemely.db.notification_repo import (
    CreateResult,
    NotificationOutcome,
    NotificationRow,
    PushSubscriptionRow,
)
from lemely.web.notify import notify_safely
from lemely.web.push import PushOutcome, RecordingPushTransport

if TYPE_CHECKING:
    from lemely.web.push import NotificationTransport

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
RECIPIENT = uuid.uuid4()


def a_row(user_id: uuid.UUID = RECIPIENT) -> NotificationRow:
    return NotificationRow(
        id=uuid.uuid4(),
        user_id=user_id,
        type=NotificationType.grade_ready,
        title="Your paper has been marked",
        body=None,
        payload={"uploadId": "u-1"},
        created_at=NOW,
        read_at=None,
    )


def a_subscription(endpoint: str) -> PushSubscriptionRow:
    return PushSubscriptionRow(
        id=uuid.uuid4(),
        user_id=RECIPIENT,
        endpoint=endpoint,
        p256dh="p256dh",
        auth="auth",
        user_agent=None,
        created_at=NOW,
    )


@dataclass
class FakeNotificationService:
    """Just enough of ``NotificationService`` for the orchestration under test."""

    result: CreateResult | None = None
    subscriptions: list[PushSubscriptionRow] = field(default_factory=list)
    raise_on_create: bool = False
    raise_on_subscriptions: bool = False
    forgotten: list[str] = field(default_factory=list)
    created_calls: list[dict[str, object]] = field(default_factory=list)

    def create(
        self,
        user_id: uuid.UUID | str,
        type: NotificationType,
        title: str,
        *,
        body: str | None = None,
        payload: dict[str, object] | None = None,
        dedupe_key: str | None = None,
    ) -> CreateResult:
        if self.raise_on_create:
            msg = "the database fell over"
            raise RuntimeError(msg)
        self.created_calls.append(
            {
                "user_id": user_id,
                "type": type,
                "title": title,
                "body": body,
                "payload": payload,
                "dedupe_key": dedupe_key,
            }
        )
        assert self.result is not None
        return self.result

    def subscriptions_for(self, user_id: uuid.UUID | str) -> list[PushSubscriptionRow]:
        if self.raise_on_subscriptions:
            msg = "the database fell over mid-fan-out"
            raise RuntimeError(msg)
        return list(self.subscriptions)

    def forget_endpoint(self, endpoint: str) -> bool:
        self.forgotten.append(endpoint)
        return True


def notify(
    service: FakeNotificationService,
    transport: NotificationTransport,
    **kwargs: object,
) -> object:
    return notify_safely(
        service,  # type: ignore[arg-type]
        transport,
        user_id=RECIPIENT,
        type=NotificationType.grade_ready,
        title="Your paper has been marked",
        seam="test_seam",
        **kwargs,  # type: ignore[arg-type]
    )


def created(
    row: NotificationRow, *, push_allowed: bool = True, reason: str | None = None
) -> CreateResult:
    return CreateResult(
        outcome=NotificationOutcome.created,
        row=row,
        push_allowed=push_allowed,
        push_suppressed_reason=reason,
    )


# -- The happy path --------------------------------------------------------


def test_a_row_is_written_and_every_device_is_pushed() -> None:
    service = FakeNotificationService(
        result=created(a_row()),
        subscriptions=[
            a_subscription("https://push.test/a"),
            a_subscription("https://push.test/b"),
        ],
    )
    transport = RecordingPushTransport()

    result = notify(service, transport)

    assert result.created is True
    assert transport.endpoints == ["https://push.test/a", "https://push.test/b"]
    assert result.pushes_attempted == 2
    assert result.pushes_delivered == 2
    assert result.subscriptions_forgotten == 0


def test_a_user_with_no_subscriptions_still_gets_the_row() -> None:
    """The inbox is the notification; a device is optional (D5.9 §1)."""
    service = FakeNotificationService(result=created(a_row()))

    result = notify(service, RecordingPushTransport())

    assert result.created is True
    assert result.row is not None
    assert result.push_suppressed_reason == "no_subscriptions"


# -- The two preference kinds, which must not collapse (D5.9 §2) -----------


def test_an_opted_out_type_writes_no_row_and_pushes_nothing() -> None:
    """A type toggle is a *content* preference: no row, no push."""
    service = FakeNotificationService(
        result=CreateResult(
            outcome=NotificationOutcome.opted_out,
            row=None,
            push_allowed=False,
            push_suppressed_reason="opted_out",
        ),
        subscriptions=[a_subscription("https://push.test/a")],
    )
    transport = RecordingPushTransport()

    result = notify(service, transport)

    assert result.outcome is NotificationOutcome.opted_out
    assert result.row is None
    assert transport.sent == []


def test_quiet_hours_keep_the_row_and_drop_only_the_push() -> None:
    """Quiet hours are a *timing* preference. Losing the row would lose the
    notification entirely for a student asleep at the moment it fired."""
    row = a_row()
    service = FakeNotificationService(
        result=created(row, push_allowed=False, reason="quiet_hours"),
        subscriptions=[a_subscription("https://push.test/a")],
    )
    transport = RecordingPushTransport()

    result = notify(service, transport)

    assert result.created is True
    assert result.row == row
    assert result.push_suppressed_reason == "quiet_hours"
    assert transport.sent == [], "quiet hours must suppress the push, not the row"


def test_a_duplicate_writes_nothing_and_pushes_nothing() -> None:
    """Re-running a correction on one PDF must not re-buzz the phone (D5.9 §6)."""
    service = FakeNotificationService(
        result=CreateResult(
            outcome=NotificationOutcome.duplicate,
            row=None,
            push_allowed=False,
            push_suppressed_reason="duplicate",
        ),
        subscriptions=[a_subscription("https://push.test/a")],
    )
    transport = RecordingPushTransport()

    result = notify(service, transport)

    assert result.outcome is NotificationOutcome.duplicate
    assert transport.sent == []


# -- The transport being unavailable is normal (D5.9 §4) -------------------


def test_an_unavailable_transport_still_writes_the_row() -> None:
    """This build has no VAPID keys, so this is the path it actually runs."""
    service = FakeNotificationService(
        result=created(a_row()),
        subscriptions=[a_subscription("https://push.test/a")],
    )
    transport = RecordingPushTransport(available=False)

    result = notify(service, transport)

    assert result.created is True
    assert result.row is not None
    assert result.push_suppressed_reason == "transport_unavailable"
    assert transport.sent == []


# -- Dead subscriptions ----------------------------------------------------


def test_a_gone_endpoint_is_deleted_and_the_live_one_is_not() -> None:
    """410 means permanently gone; the other device must survive it (D5.9 §4)."""
    service = FakeNotificationService(
        result=created(a_row()),
        subscriptions=[
            a_subscription("https://push.test/live"),
            a_subscription("https://push.test/dead"),
        ],
    )
    transport = RecordingPushTransport()
    transport.program("https://push.test/dead", PushOutcome.expired)

    result = notify(service, transport)

    assert service.forgotten == ["https://push.test/dead"]
    assert result.pushes_attempted == 2
    assert result.pushes_delivered == 1
    assert result.subscriptions_forgotten == 1


def test_a_transient_failure_leaves_the_subscription_alone() -> None:
    """One bad minute at a push service must not evict a healthy device."""
    service = FakeNotificationService(
        result=created(a_row()),
        subscriptions=[a_subscription("https://push.test/flaky")],
    )
    transport = RecordingPushTransport()
    transport.program("https://push.test/flaky", PushOutcome.failed)

    result = notify(service, transport)

    assert service.forgotten == []
    assert result.subscriptions_forgotten == 0
    assert result.pushes_delivered == 0
    assert result.created is True


# -- Fail-open, the whole point (D5.9 §1) ----------------------------------


def test_a_failing_inbox_write_is_swallowed_not_raised() -> None:
    """The action that produced this notification has already committed."""
    service = FakeNotificationService(raise_on_create=True)

    result = notify(service, RecordingPushTransport())

    assert result.outcome is None
    assert result.row is None


def test_a_failing_fan_out_still_reports_the_row_as_created() -> None:
    """A failure after the row exists loses a buzz, not a notification."""
    service = FakeNotificationService(
        result=created(a_row()),
        raise_on_subscriptions=True,
    )

    result = notify(service, RecordingPushTransport())

    assert result.created is True
    assert result.row is not None
    assert result.push_suppressed_reason == "push_failed"


def test_a_transport_that_raises_does_not_reach_the_caller() -> None:
    """The protocol says never raise; a broken implementation must still not
    turn an already-successful student action into a 500."""

    class ExplodingTransport:
        available = True

        def send(self, subscription: PushSubscriptionRow) -> object:
            msg = "this transport is broken"
            raise RuntimeError(msg)

    service = FakeNotificationService(
        result=created(a_row()),
        subscriptions=[a_subscription("https://push.test/a")],
    )

    result = notify(service, ExplodingTransport())  # type: ignore[arg-type]

    assert result.created is True
    assert result.push_suppressed_reason == "push_failed"


# -- What gets passed through ----------------------------------------------


def test_the_dedupe_key_and_payload_reach_the_service_unchanged() -> None:
    service = FakeNotificationService(result=created(a_row()))

    notify(service, RecordingPushTransport(), dedupe_key="upload:abc", payload={"uploadId": "abc"})

    call = service.created_calls[0]
    assert call["dedupe_key"] == "upload:abc"
    assert call["payload"] == {"uploadId": "abc"}


def test_the_recipient_is_whoever_the_seam_named_not_the_caller() -> None:
    """``at_risk_alert`` goes to a teacher or parent, never the student who
    triggered it — so the recipient is a parameter, not ``auth.user_id``."""
    other = uuid.uuid4()
    service = FakeNotificationService(result=created(a_row(other)))

    notify_safely(
        service,  # type: ignore[arg-type]
        RecordingPushTransport(),
        user_id=other,
        type=NotificationType.at_risk_alert,
        title="A student in your class needs attention",
        seam="at_risk_alert",
    )

    assert service.created_calls[0]["user_id"] == other
    assert service.created_calls[0]["type"] is NotificationType.at_risk_alert


@pytest.mark.parametrize("type", list(NotificationType))
def test_every_notification_type_can_be_sent_through_the_helper(type: NotificationType) -> None:
    """No type is special-cased, so none can be accidentally unroutable."""
    service = FakeNotificationService(result=created(a_row()))

    notify_safely(
        service,  # type: ignore[arg-type]
        RecordingPushTransport(),
        user_id=RECIPIENT,
        type=type,
        title="something happened",
        seam="parametrised",
    )

    assert service.created_calls[0]["type"] is type
