"""Transactional email templates, providers and error scrubbing (SPEC §b.4, SC-25, EM-3, EM-5).

No database here: the context schemas, the rendered output, the links and the
provider's HTTP shape are pure functions of their inputs. The outbox and the
delivery job are in ``tests/test_email_outbox_repo.py``.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from lemely.io.notify_email import (
    EMAIL_TEMPLATES,
    InvalidEmailContext,
    MockTransactionalEmailProvider,
    ResendTransactionalEmailProvider,
    build_transactional_provider,
    render_email,
    scrub_error,
    validate_context,
)
from lemely.runtime.config import EmailSettings, Settings
from lemely.runtime.errors import ExternalServiceError

SPEC = Path(__file__).resolve().parent.parent / "docs" / "tutoring" / "SPEC.md"
BASE_URL = "https://staging.lemelyig.example"

BOOKING_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
CHILD_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
GRANT_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
EVENT_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
ENROLMENT_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")


def spec_b4_rows() -> list[list[str]]:
    """The cells of every data row of SPEC §b.4's event table, parsed from the spec text."""
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("### b.4 Side effects")
    end = text.index("### b.5", start)
    rows: list[list[str]] = []
    for line in text[start:end].splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5 or cells[0] == "Event" or set(cells[0]) <= {"-", " "}:
            continue
        rows.append(cells)
    return rows


def _booking(audience: str = "tutor", *, child_id: uuid.UUID | None = None) -> dict[str, object]:
    return {
        "booking_id": str(BOOKING_ID),
        "audience": audience,
        "child_id": None if child_id is None else str(child_id),
        "tutor_first_name": "Sara",
        "tutor_last_initial": "M",
        "subject_name": "Art & Design",
        "starts_at": "2026-10-30T14:00:00+00:00",
        "tutor_zone": "Africa/Cairo",
        "mode": "virtual",
    }


VALID: dict[str, dict[str, object]] = {
    "booking_requested": _booking("tutor"),
    "booking_requested_family": _booking("parent", child_id=CHILD_ID),
    "booking_accepted": _booking("student"),
    "booking_declined": _booking("parent", child_id=CHILD_ID),
    "booking_cancelled": _booking("tutor"),
    "tutor_access_granted": {
        "grant_id": str(GRANT_ID),
        "child_id": str(CHILD_ID),
        "tutor_first_name": "Sara",
        "tutor_last_initial": "M",
    },
    "tutor_listing_decision": {"approval_event_id": str(EVENT_ID), "decision": "approved"},
    "parent_unlinked": {"event_id": str(EVENT_ID)},
    "parent_linked": {"event_id": str(EVENT_ID)},
    "class_joined_tutor": {
        "enrollment_id": str(ENROLMENT_ID),
        "child_id": str(CHILD_ID),
        "tutor_first_name": "Sara",
        "tutor_last_initial": "M",
    },
}


def test_templates_are_exactly_the_ones_the_spec_table_names() -> None:
    """Derived from SPEC §b.4 column 4 (backticked names), not from a literal of ours."""
    named: set[str] = set()
    for row in spec_b4_rows():
        named.update(re.findall(r"`([a-z_]+)`", row[3]))
    assert len(named) == 10  # non-vacuity: ten templates in the spec table
    assert set(EMAIL_TEMPLATES) == named
    assert set(VALID) == named


@pytest.mark.parametrize("template", sorted(VALID))
def test_email_context_schema_rejects_extra_keys(template: str) -> None:
    assert validate_context(template, VALID[template])
    for extra in ("note", "meeting_link", "location", "email", "reason", "anything"):
        with pytest.raises(InvalidEmailContext):
            validate_context(template, {**VALID[template], extra: "x"})


@pytest.mark.parametrize("template", sorted(VALID))
def test_email_context_schema_rejects_a_missing_key(template: str) -> None:
    for key in VALID[template]:
        partial = {k: v for k, v in VALID[template].items() if k != key}
        required = key not in {"child_id", "tutor_last_initial", "tutor_zone"}
        if required:
            with pytest.raises(InvalidEmailContext):
                validate_context(template, partial)


def test_unknown_template_is_refused() -> None:
    with pytest.raises(InvalidEmailContext):
        validate_context("password_reset", {})
    with pytest.raises(InvalidEmailContext):
        render_email("password_reset", {}, app_base_url=BASE_URL)


@pytest.mark.parametrize(
    "first_name",
    [
        "Sara visit lemely-help.com",
        "Sara‮evil",
        "Sara​",
        "Sara/phish",
        "sara@example.org",
        "Sara2",
        "",
    ],
)
def test_tutor_name_outside_the_sc25_allowlist_is_refused(first_name: str) -> None:
    context = {**VALID["booking_accepted"], "tutor_first_name": first_name}
    with pytest.raises(InvalidEmailContext):
        validate_context("booking_accepted", context)


def test_subject_name_cannot_carry_markup_or_urls() -> None:
    for subject in ("<script>alert(1)</script>", "Maths https://evil.example", "a@b.c", "x\ny"):
        with pytest.raises(InvalidEmailContext):
            validate_context(
                "booking_accepted", {**VALID["booking_accepted"], "subject_name": subject}
            )


def test_audience_must_match_the_template() -> None:
    # The tutor's request mail is for the tutor only; the family mail is for parents only.
    with pytest.raises(InvalidEmailContext):
        validate_context("booking_requested", _booking("parent", child_id=CHILD_ID))
    with pytest.raises(InvalidEmailContext):
        validate_context("booking_requested_family", _booking("tutor"))
    # A parent audience needs the child id for the link, and nobody else may carry one.
    with pytest.raises(InvalidEmailContext):
        validate_context("booking_accepted", _booking("parent"))
    with pytest.raises(InvalidEmailContext):
        validate_context("booking_accepted", _booking("student", child_id=CHILD_ID))


@pytest.mark.parametrize("template", ["booking_accepted", "booking_declined"])
def test_accepted_and_declined_are_never_addressed_to_the_tutor(template: str) -> None:
    """R6: the tutor is the one who accepts or declines, so those mails go to student or parent."""
    with pytest.raises(InvalidEmailContext):
        validate_context(template, _booking("tutor"))
    assert validate_context(template, _booking("student"))
    assert validate_context(template, _booking("parent", child_id=CHILD_ID))


def test_start_instant_must_be_timezone_aware() -> None:
    naive = {**VALID["booking_accepted"], "starts_at": "2026-10-30T14:00:00"}
    with pytest.raises(InvalidEmailContext):
        validate_context("booking_accepted", naive)


def test_validated_context_is_json_serialisable_and_round_trips() -> None:
    for template, context in VALID.items():
        stored = validate_context(template, context)
        assert json.loads(json.dumps(stored)) == stored
        assert validate_context(template, stored) == stored


@pytest.mark.parametrize("template", sorted(VALID))
def test_email_links_only_from_app_base_url(template: str) -> None:
    subject, html_body, text_body = render_email(template, VALID[template], app_base_url=BASE_URL)
    assert subject
    urls = re.findall(r"https?://[^\s\"'<>]+", html_body + " " + text_body)
    assert urls, f"{template} renders no link at all"
    assert all(url.startswith(BASE_URL + "/") for url in urls), urls


def test_every_link_is_a_fixed_path_plus_an_id() -> None:
    _, _, text = render_email("booking_accepted", _booking("student"), app_base_url=BASE_URL)
    assert f"{BASE_URL}/student/sessions/{BOOKING_ID}" in text
    _, _, text = render_email(
        "booking_declined", _booking("parent", child_id=CHILD_ID), app_base_url=BASE_URL
    )
    assert f"{BASE_URL}/parent/children/{CHILD_ID}/sessions/{BOOKING_ID}" in text
    _, _, text = render_email("booking_requested", _booking("tutor"), app_base_url=BASE_URL)
    assert f"{BASE_URL}/teacher/tutoring/sessions/{BOOKING_ID}" in text


@pytest.mark.parametrize("template", sorted(VALID))
def test_a_public_name_ending_in_a_stop_never_doubles_it(template: str) -> None:
    subject, html_body, text_body = render_email(template, VALID[template], app_base_url=BASE_URL)
    assert ".." not in subject + html_body + text_body.replace("...", "")


def test_templates_html_escaped() -> None:
    subject, html_body, text_body = render_email(
        "booking_accepted", _booking("student"), app_base_url=BASE_URL
    )
    assert "Art &amp; Design" in html_body
    assert "Art & Design" not in html_body
    assert "Art & Design" in text_body
    assert "<script" not in html_body.lower()
    assert "&amp;" not in subject  # a subject line is plain text, never HTML-escaped


def test_rendered_mail_states_the_time_in_the_tutor_zone() -> None:
    _, _, text = render_email("booking_accepted", _booking("student"), app_base_url=BASE_URL)
    # 14:00 UTC on 30 Oct 2026 is 16:00 in Cairo (UTC+2 after the October clock change).
    assert "16:00" in text
    assert "Cairo time" in text


def test_email_context_never_contains_note_link_location_or_address() -> None:
    forbidden = re.compile(
        r"note|link|location|place|address|email|phone|reason|url|body|text|name$"
    )
    fields: set[str] = set()
    for template in EMAIL_TEMPLATES.values():
        fields.update(template.context_fields)  # type: ignore[attr-defined]
    assert len(fields) >= 12  # non-vacuity: the union of the ten schemas
    allowed_names = {"tutor_first_name", "subject_name"}
    offenders = {f for f in fields if forbidden.search(f) and f not in allowed_names}
    assert offenders == set()


def test_rendered_cancellation_carries_no_reason_text() -> None:
    subject, html_body, text_body = render_email(
        "booking_cancelled", _booking("student"), app_base_url=BASE_URL
    )
    combined = (subject + html_body + text_body).lower()
    assert "reason" not in combined
    assert "open lemely" in combined


# -- error scrubbing ----------------------------------------------------------


def test_email_last_error_has_no_address() -> None:
    message = (
        "Email delivery to Parent.One+tag@Example.org was rejected (HTTP 422): "
        '{"message":"The to field parent.one+tag@example.org is invalid, cc other@mail.test"}'
    )
    scrubbed = scrub_error(message, address="Parent.One+tag@Example.org")
    assert "@" not in scrubbed
    assert "example.org" not in scrubbed.lower()
    assert "HTTP 422" in scrubbed  # the status survives: it is what an operator needs


def test_scrub_error_truncates_to_the_column_width() -> None:
    assert len(scrub_error("x" * 2000, address=None)) <= 500


# -- providers -----------------------------------------------------------------


def _resend(handler: httpx.MockTransport) -> ResendTransactionalEmailProvider:
    settings = EmailSettings(api_key="re_test_key", app_base_url=BASE_URL)  # type: ignore[arg-type]
    return ResendTransactionalEmailProvider(settings, client=httpx.Client(transport=handler))


def test_resend_provider_posts_one_mail_in_the_existing_resend_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "msg_1"})

    provider = _resend(httpx.MockTransport(handler))
    provider.send("tutor@example.org", "booking_requested", VALID["booking_requested"])

    assert provider.delivers_out_of_band is True
    (request,) = seen
    assert str(request.url) == "https://api.resend.com/emails"
    assert request.headers["authorization"] == "Bearer re_test_key"
    body = json.loads(request.content)
    assert body["to"] == ["tutor@example.org"]
    assert body["from"] == "Lemely <noreply@lemelyig.com>"
    assert body["subject"]
    assert BASE_URL in body["html"]
    assert BASE_URL in body["text"]


def test_resend_failure_message_never_contains_the_address() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text='{"message":"bad recipient tutor@example.org"}')

    provider = _resend(httpx.MockTransport(handler))
    with pytest.raises(ExternalServiceError) as caught:
        provider.send("tutor@example.org", "booking_requested", VALID["booking_requested"])
    assert "tutor@example.org" not in str(caught.value)
    assert "422" in str(caught.value)


def test_resend_network_failure_message_never_contains_the_address() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom for tutor@example.org")

    provider = _resend(httpx.MockTransport(handler))
    with pytest.raises(ExternalServiceError) as caught:
        provider.send("tutor@example.org", "booking_requested", VALID["booking_requested"])
    assert "tutor@example.org" not in str(caught.value)


def test_resend_provider_refuses_an_invalid_context_before_any_request() -> None:
    called: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(1)
        return httpx.Response(200, json={})

    provider = _resend(httpx.MockTransport(handler))
    with pytest.raises(InvalidEmailContext):
        provider.send("a@b.example", "booking_requested", {**VALID["booking_requested"], "x": 1})
    assert called == []


def test_resend_provider_requires_an_api_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        ResendTransactionalEmailProvider(EmailSettings())


def test_mock_provider_does_not_deliver_and_logs_no_address_or_context() -> None:
    import structlog.testing

    provider = MockTransactionalEmailProvider()
    outbox_id = uuid.uuid4()
    with structlog.testing.capture_logs() as logs:
        provider.send(
            "tutor@example.org",
            "booking_requested",
            VALID["booking_requested"],
            outbox_id=outbox_id,
        )
    assert provider.delivers_out_of_band is False
    rendered = json.dumps(logs, default=str)
    assert str(outbox_id) in rendered
    assert "booking_requested" in rendered
    assert "tutor@example.org" not in rendered
    assert "Sara" not in rendered


def test_build_transactional_provider_follows_the_api_key() -> None:
    unkeyed = Settings.model_construct(email=EmailSettings())  # skips env, .env and toml sources
    assert isinstance(build_transactional_provider(unkeyed), MockTransactionalEmailProvider)
    keyed = Settings.model_construct(email=EmailSettings(api_key="re_x"))  # type: ignore[arg-type]
    assert isinstance(build_transactional_provider(keyed), ResendTransactionalEmailProvider)


def test_validated_start_instant_is_stored_in_utc() -> None:
    cairo = {**_booking("student"), "starts_at": "2026-10-30T16:00:00+02:00"}
    stored = validate_context("booking_accepted", cairo)
    assert datetime.fromisoformat(str(stored["starts_at"])) == datetime(
        2026, 10, 30, 14, 0, tzinfo=UTC
    )
