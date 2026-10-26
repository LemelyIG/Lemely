"""Transactional email for the tutoring marketplace: templates, schemas and providers.

SPEC ``docs/tutoring/SPEC.md`` §b.4 (email delivery), THREAT-MODEL SC-6 (an honest mock) and
SC-25 (hardened content). Three rules shape everything here.

* **Templates are fixed and the context is typed.** Each template is an :class:`EmailContext`
  subclass whose fields are the only values that can reach a mail: ids, a tutor's public name,
  a subject name, a start instant and a mode. ``extra="forbid"`` means a note, a meeting link,
  a place, a reason or an address cannot be smuggled in; there is no field for them to land in.
  The same schema validates the context when a row is written to the outbox and again when it
  is rendered.
* **Links are built, never passed.** Every URL is ``urljoin(app_base_url, fixed_path(ids))``;
  nothing in the context is ever a URL.
* **Nothing prints an address.** The Resend provider's own error text and
  :func:`scrub_error` both drop the recipient, because the existing auth provider's
  ``ExternalServiceError`` messages carry it (EM-5) and the delivery job stores the message in
  ``email_outbox.last_error``.

The mock provider never pretends: it reports ``delivers_out_of_band = False`` and the delivery
job records its rows as ``skipped`` with ``last_error='mock_provider'``, never ``sent`` (SC-6).
"""

from __future__ import annotations

import abc
import html
import re
import unicodedata
import uuid  # noqa: TC003  (pydantic resolves the field annotations at runtime)
from datetime import UTC
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Protocol
from urllib.parse import urljoin
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import structlog
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)

from lemely.core.tutor_directory import (
    InvalidPublicNameError,
    public_name,
    validate_public_name,
    zone_label,
)
from lemely.db.models.enums import NotificationType
from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from lemely.runtime.config import EmailSettings, Settings

log = structlog.get_logger(__name__)

#: ``email_outbox.last_error`` is varchar(500).
LAST_ERROR_MAX: Final = 500

DEFAULT_TUTOR_ZONE: Final = "Africa/Cairo"

_ADDRESS_RE: Final = re.compile(r"[^\s@<>\"',;()\[\]]+@[^\s@<>\"',;()\[\]]+")
_SUBJECT_FORBIDDEN: Final = frozenset("/@:\\<>")
_MODE_TEXT: Final = {
    "virtual": "online",
    "in_person": "in person",
    "other": "arranged in the session notes",
}
_NOTICE: Final = "Open Lemely to see the details."


class InvalidEmailContext(ValueError):
    """A template name is unknown or its context fails the template's schema."""


# ---------------------------------------------------------------------------
# Context schemas, one per template
# ---------------------------------------------------------------------------


class EmailContext(BaseModel, abc.ABC):
    """Base of every template: the typed context plus the fixed copy and the link."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    template: ClassVar[str]
    notification_type: ClassVar[NotificationType]
    subject: ClassVar[str]
    button: ClassVar[str]
    context_fields: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        """Record the schema's field names (the allow-list tests read)."""
        super().__pydantic_init_subclass__(**kwargs)
        cls.context_fields = frozenset(cls.model_fields)

    @abc.abstractmethod
    def lead(self) -> str:
        """The first paragraph: fixed words plus validated values."""

    @abc.abstractmethod
    def detail(self) -> str | None:
        """An optional second line, or ``None``."""

    @abc.abstractmethod
    def path(self) -> str:
        """The root-relative path of the screen to open, built from ids only."""


class _TutorNamed(EmailContext, abc.ABC):
    """Mixin for contexts that name a tutor by public first name and last initial."""

    tutor_first_name: str
    tutor_last_initial: str | None = None

    @model_validator(mode="after")
    def _check_public_name(self) -> _TutorNamed:
        try:
            validate_public_name(self.tutor_first_name, self.tutor_last_initial)
        except InvalidPublicNameError as exc:
            raise ValueError(str(exc)) from exc
        return self

    def tutor(self) -> str:
        return public_name(self.tutor_first_name, self.tutor_last_initial)


class _Booking(_TutorNamed, abc.ABC):
    """A booking mail: who it is for decides the link."""

    booking_id: uuid.UUID
    audience: Literal["tutor", "student", "parent"]
    child_id: uuid.UUID | None = None
    subject_name: str
    starts_at: AwareDatetime
    tutor_zone: str = DEFAULT_TUTOR_ZONE
    mode: Literal["virtual", "in_person", "other"]

    allowed_audiences: ClassVar[frozenset[str]] = frozenset({"tutor", "student", "parent"})

    @field_validator("subject_name")
    @classmethod
    def _check_subject(cls, value: str) -> str:
        if not 1 <= len(value) <= 80 or value != value.strip():
            raise ValueError("subject name must be 1 to 80 characters without outer spaces")
        for char in value:
            if unicodedata.category(char)[0] == "C" or char in _SUBJECT_FORBIDDEN:
                raise ValueError("subject name contains a character mail must not carry")
        return value

    @field_validator("starts_at")
    @classmethod
    def _to_utc(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(UTC)

    @field_validator("tutor_zone")
    @classmethod
    def _check_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown time zone") from exc
        return value

    @model_validator(mode="after")
    def _check_audience(self) -> _Booking:
        if self.audience not in self.allowed_audiences:
            raise ValueError(f"{self.template} is not sent to the {self.audience} audience")
        if (self.audience == "parent") != (self.child_id is not None):
            raise ValueError("a child id is required for, and only for, the parent audience")
        return self

    def when(self) -> str:
        local = self.starts_at.astimezone(ZoneInfo(self.tutor_zone))
        return f"{local.strftime('%a %d %b, %H:%M')} {zone_label(self.tutor_zone)}"

    def detail(self) -> str | None:
        return f"Format: {_MODE_TEXT[self.mode]}."

    def path(self) -> str:
        if self.audience == "tutor":
            return f"/teacher/tutoring/sessions/{self.booking_id}"
        if self.audience == "student":
            return f"/student/sessions/{self.booking_id}"
        return f"/parent/children/{self.child_id}/sessions/{self.booking_id}"


class BookingRequested(_Booking):
    template: ClassVar[str] = "booking_requested"
    notification_type: ClassVar[NotificationType] = NotificationType.booking_request
    subject: ClassVar[str] = "New session request"
    button: ClassVar[str] = "Open request"
    allowed_audiences: ClassVar[frozenset[str]] = frozenset({"tutor"})

    def lead(self) -> str:
        return f"You have a new session request for {self.subject_name} on {self.when()}."


class BookingRequestedFamily(_Booking):
    template: ClassVar[str] = "booking_requested_family"
    notification_type: ClassVar[NotificationType] = NotificationType.booking_update
    subject: ClassVar[str] = "A session was requested"
    button: ClassVar[str] = "Open session"
    allowed_audiences: ClassVar[frozenset[str]] = frozenset({"parent"})

    def lead(self) -> str:
        return (
            f"A session with {self.tutor()} for {self.subject_name} on {self.when()} was requested."
        )


class BookingAccepted(_Booking):
    template: ClassVar[str] = "booking_accepted"
    notification_type: ClassVar[NotificationType] = NotificationType.booking_update
    subject: ClassVar[str] = "Session accepted"
    button: ClassVar[str] = "Open session"
    allowed_audiences: ClassVar[frozenset[str]] = frozenset({"student", "parent"})

    def lead(self) -> str:
        return f"{self.tutor()} accepted the session for {self.subject_name} on {self.when()}."


class BookingDeclined(_Booking):
    template: ClassVar[str] = "booking_declined"
    notification_type: ClassVar[NotificationType] = NotificationType.booking_update
    subject: ClassVar[str] = "Session declined"
    button: ClassVar[str] = "Open session"
    allowed_audiences: ClassVar[frozenset[str]] = frozenset({"student", "parent"})

    def lead(self) -> str:
        return (
            f"{self.tutor()} declined the session request for {self.subject_name} on {self.when()}."
        )


class BookingCancelled(_Booking):
    """A cancellation. There is deliberately no field for a reason (row 18, SC-9)."""

    template: ClassVar[str] = "booking_cancelled"
    notification_type: ClassVar[NotificationType] = NotificationType.booking_update
    subject: ClassVar[str] = "Session cancelled"
    button: ClassVar[str] = "Open session"

    def lead(self) -> str:
        return f"The session for {self.subject_name} on {self.when()} was cancelled."


class TutorAccessGranted(_TutorNamed):
    template: ClassVar[str] = "tutor_access_granted"
    notification_type: ClassVar[NotificationType] = NotificationType.tutor_access
    subject: ClassVar[str] = "Progress sharing started"
    button: ClassVar[str] = "See who has access"

    grant_id: uuid.UUID
    child_id: uuid.UUID

    def lead(self) -> str:
        return _stop(
            f"A child linked to your Lemely account shared their progress with {self.tutor()}"
        )

    def detail(self) -> str | None:
        return None

    def path(self) -> str:
        return f"/parent/children/{self.child_id}/tutor-access"


class TutorListingDecision(EmailContext):
    template: ClassVar[str] = "tutor_listing_decision"
    notification_type: ClassVar[NotificationType] = NotificationType.tutor_listing
    subject: ClassVar[str] = "Your tutor profile"
    button: ClassVar[str] = "Open your profile"

    approval_event_id: uuid.UUID
    decision: Literal["approved", "rejected", "suspended", "reinstated", "closed"]

    _LEADS: ClassVar[dict[str, str]] = {
        "approved": "Your tutor profile was approved and is now listed.",
        "rejected": "Your tutor profile was not approved. Open it to see the note from Lemely.",
        "suspended": "Your tutor profile has been suspended. Open it to see the note from Lemely.",
        "reinstated": "Your tutor profile is listed again.",
        "closed": "Your tutor profile has been closed.",
    }

    def lead(self) -> str:
        return self._LEADS[self.decision]

    def detail(self) -> str | None:
        return None

    def path(self) -> str:
        return "/teacher/tutoring/profile"


class ParentUnlinked(EmailContext):
    template: ClassVar[str] = "parent_unlinked"
    notification_type: ClassVar[NotificationType] = NotificationType.parent_link
    subject: ClassVar[str] = "A child was unlinked from your account"
    button: ClassVar[str] = "Open Lemely"

    event_id: uuid.UUID

    def lead(self) -> str:
        return "Your Lemely account was unlinked from a child's account."

    def detail(self) -> str | None:
        return "If you did not expect this, sign in to review the children linked to you."

    def path(self) -> str:
        return "/parent"


class ParentLinked(EmailContext):
    template: ClassVar[str] = "parent_linked"
    notification_type: ClassVar[NotificationType] = NotificationType.parent_link
    subject: ClassVar[str] = "Another parent was linked to a child"
    button: ClassVar[str] = "Open Lemely"

    event_id: uuid.UUID

    def lead(self) -> str:
        return "Another parent account was linked to a child on your Lemely account."

    def detail(self) -> str | None:
        return "If you did not expect this, sign in to review who is linked."

    def path(self) -> str:
        return "/parent"


class ClassJoinedTutor(_TutorNamed):
    template: ClassVar[str] = "class_joined_tutor"
    notification_type: ClassVar[NotificationType] = NotificationType.tutor_access
    subject: ClassVar[str] = "A child joined a tutor's class"
    button: ClassVar[str] = "Open tutoring"

    enrollment_id: uuid.UUID
    child_id: uuid.UUID

    def lead(self) -> str:
        return (
            "A child linked to your Lemely account joined a class taught by "
            f"{self.tutor()}, who also offers tutoring on Lemely."
        )

    def detail(self) -> str | None:
        return None

    def path(self) -> str:
        return f"/parent/children/{self.child_id}/tutoring"


_TEMPLATE_CLASSES: Final[tuple[type[EmailContext], ...]] = (
    BookingRequested,
    BookingRequestedFamily,
    BookingAccepted,
    BookingDeclined,
    BookingCancelled,
    TutorAccessGranted,
    TutorListingDecision,
    ParentUnlinked,
    ParentLinked,
    ClassJoinedTutor,
)

#: Every template, keyed by the name stored in ``email_outbox.template``.
EMAIL_TEMPLATES: Final[Mapping[str, type[EmailContext]]] = {
    cls.template: cls for cls in _TEMPLATE_CLASSES
}


def _stop(sentence: str) -> str:
    """End ``sentence`` with one full stop (a public name such as "Sara M." already has one)."""
    return sentence if sentence.endswith(".") else f"{sentence}."


def _parse(template: str, context: Mapping[str, object]) -> EmailContext:
    cls = EMAIL_TEMPLATES.get(template)
    if cls is None:
        raise InvalidEmailContext(f"unknown email template {template!r}")
    try:
        return cls.model_validate(dict(context))
    except ValidationError as exc:
        # Field names and error kinds only: the input values may be the very thing refused.
        problems = sorted(
            {".".join(str(p) for p in e["loc"]) + ":" + e["type"] for e in exc.errors()}
        )
        raise InvalidEmailContext(f"{template} context refused ({', '.join(problems)})") from exc


def validate_context(template: str, context: Mapping[str, object]) -> dict[str, object]:
    """Validate ``context`` against ``template``'s schema and return its JSON-safe form.

    Raises:
        InvalidEmailContext: the template is unknown, a key is missing or extra, or a value
            is outside its allow-list.
    """
    return dict(_parse(template, context).model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_email(
    template: str, context: Mapping[str, object], *, app_base_url: str
) -> tuple[str, str, str]:
    """Return ``(subject, html_body, text_body)``; every value is HTML-escaped in the HTML part."""
    parsed = _parse(template, context)
    link = urljoin(app_base_url, parsed.path())
    subject = parsed.subject
    lead = parsed.lead()
    detail = parsed.detail()
    safe_link = html.escape(link, quote=True)
    detail_html = (
        ""
        if detail is None
        else (
            f'<p style="margin:0 0 16px;font-size:15px;line-height:1.55;">{html.escape(detail)}</p>'
        )
    )
    html_body = (
        '<!doctype html><html lang="en"><body style="margin:0;padding:24px;'
        "background:#f6f7f9;font-family:-apple-system,BlinkMacSystemFont,"
        "'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2933;\">"
        '<div style="max-width:480px;margin:0 auto;background:#ffffff;'
        'border-radius:12px;padding:32px;">'
        f'<h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;">{html.escape(subject)}</h1>'
        f'<p style="margin:0 0 16px;font-size:15px;line-height:1.55;">{html.escape(lead)}</p>'
        f"{detail_html}"
        f'<p style="margin:0 0 24px;"><a href="{safe_link}" '
        'style="display:inline-block;background:#1f2933;color:#ffffff;'
        "text-decoration:none;padding:12px 20px;border-radius:8px;"
        f'font-size:15px;font-weight:600;">{html.escape(parsed.button)}</a></p>'
        '<p style="margin:0 0 8px;font-size:13px;line-height:1.5;color:#52606d;">'
        "If the button does not work, copy this link into your browser:</p>"
        '<p style="margin:0 0 24px;font-size:13px;line-height:1.5;word-break:break-all;">'
        f'<a href="{safe_link}" style="color:#2563eb;">{safe_link}</a></p>'
        '<p style="margin:0;font-size:13px;line-height:1.5;color:#52606d;">'
        f"{html.escape(_NOTICE)}</p>"
        "</div></body></html>"
    )
    detail_text = "" if detail is None else f"{detail}\n\n"
    text_body = f"{subject}\n\n{lead}\n\n{detail_text}{link}\n\n{_NOTICE}\n"
    return subject, html_body, text_body


def scrub_error(message: str, *, address: str | None) -> str:
    """Remove every email address from ``message`` and cap it at the column width.

    The recipient is removed by exact (case-insensitive) match first, then any other address-
    shaped text is replaced as well, because a provider may echo a normalised or a second one.
    """
    cleaned = message
    if address:
        cleaned = re.sub(re.escape(address), "[address]", cleaned, flags=re.IGNORECASE)
    cleaned = _ADDRESS_RE.sub("[address]", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned[:LAST_ERROR_MAX]


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class TransactionalEmailProvider(Protocol):
    """Sends one rendered template to one address."""

    delivers_out_of_band: bool
    """True only when the mail really leaves for an inbox. The delivery job records a row as
    ``sent`` only for a provider that sets this, and as ``skipped`` otherwise (SC-6)."""

    def send(
        self,
        to: str,
        template: str,
        context: Mapping[str, object],
        *,
        outbox_id: uuid.UUID | None = None,
    ) -> None:
        """Send, raising on failure. ``outbox_id`` is for logs only."""
        ...


class MockTransactionalEmailProvider:
    """Offline provider: sends nothing and says so (SC-6)."""

    delivers_out_of_band = False

    def send(
        self,
        to: str,
        template: str,
        context: Mapping[str, object],
        *,
        outbox_id: uuid.UUID | None = None,
    ) -> None:
        """Log the outbox id and template. Never the address and never the context."""
        log.info(
            "tutoring_email_not_sent_mock_provider",
            outbox_id=None if outbox_id is None else str(outbox_id),
            template=template,
        )


class ResendTransactionalEmailProvider:
    """Sends over Resend's REST API with the same ``[email]`` settings as the auth mails."""

    delivers_out_of_band = True

    def __init__(self, settings: EmailSettings, client: httpx.Client | None = None) -> None:
        """Build from ``[email]`` settings, optionally with a test client.

        Raises:
            ValueError: ``settings.api_key`` is unset (callers pick the mock in that case).
        """
        if settings.api_key is None:
            raise ValueError(
                "ResendTransactionalEmailProvider requires [email] api_key; "
                "use MockTransactionalEmailProvider when no key is configured."
            )
        self._settings = settings
        self._api_key = settings.api_key.get_secret_value()
        self._client = client or httpx.Client(timeout=settings.timeout_seconds)

    def send(
        self,
        to: str,
        template: str,
        context: Mapping[str, object],
        *,
        outbox_id: uuid.UUID | None = None,
    ) -> None:
        """Validate, render and POST one mail. Error text never contains ``to``."""
        subject, html_body, text_body = render_email(
            template, context, app_base_url=self._settings.app_base_url
        )
        payload: dict[str, object] = {
            "from": f"{self._settings.from_name} <{self._settings.from_address}>",
            "to": [to],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        }
        if self._settings.reply_to is not None:
            payload["reply_to"] = self._settings.reply_to
        url = f"{self._settings.api_base_url.rstrip('/')}/emails"
        try:
            response = self._client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"Email delivery failed ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            raise ExternalServiceError(
                f"Email delivery was rejected (HTTP {response.status_code}): "
                f"{scrub_error(response.text[:300], address=to)}"
            )
        log.info(
            "tutoring_email_sent",
            outbox_id=None if outbox_id is None else str(outbox_id),
            template=template,
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()


def build_transactional_provider(settings: Settings) -> TransactionalEmailProvider:
    """The real provider when ``[email] api_key`` is set, otherwise the honest mock."""
    if settings.email.api_key is None:
        return MockTransactionalEmailProvider()
    return ResendTransactionalEmailProvider(settings.email)


__all__ = [
    "EMAIL_TEMPLATES",
    "EmailContext",
    "InvalidEmailContext",
    "MockTransactionalEmailProvider",
    "ResendTransactionalEmailProvider",
    "TransactionalEmailProvider",
    "build_transactional_provider",
    "render_email",
    "scrub_error",
    "validate_context",
]
