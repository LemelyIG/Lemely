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
    BILLING_EMAIL_TEMPLATES,
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


def _spec_b4_text() -> str:
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("### b.4 Side effects")
    return text[start : text.index("### b.5", start)]


def spec_listing_copy() -> dict[str, str]:
    """The two reinstatement titles SPEC §b.4's listing-decision line gives, by resulting state."""
    line = next(
        line for line in _spec_b4_text().splitlines() if line.startswith("**Listing decision copy")
    )
    copy = dict(re.findall(r'to `(listed|pending_review)` is titled "([^"]+)"', line))
    assert set(copy) == {"listed", "pending_review"}, line  # non-vacuity: both outcomes named
    return copy


def spec_listing_context_keys() -> set[str]:
    """The ``tutor_listing_decision`` context keys SPEC §b.4's listing-decision line names."""
    line = next(
        line for line in _spec_b4_text().splitlines() if line.startswith("**Listing decision copy")
    )
    match = re.search(r"context is ((?:`[a-z_]+`(?:, | and )?)+)", line)
    assert match is not None, line
    return set(re.findall(r"`([a-z_]+)`", match.group(1)))


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
    "tutor_listing_decision": {
        "approval_event_id": str(EVENT_ID),
        "decision": "approved",
        "listed": True,
    },
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
    assert set(EMAIL_TEMPLATES) - BILLING_EMAIL_TEMPLATES == named
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


def test_listing_decision_context_keys_are_the_spec_ones() -> None:
    keys = spec_listing_context_keys()
    assert len(keys) == 3  # non-vacuity: approval_event_id, decision, listed
    assert EMAIL_TEMPLATES["tutor_listing_decision"].context_fields == keys  # type: ignore[attr-defined]
    assert set(VALID["tutor_listing_decision"]) == keys


@pytest.mark.parametrize(
    ("decision", "listed", "allowed"),
    [
        ("approved", True, True),
        ("approved", False, False),
        ("reinstated", True, True),
        ("reinstated", False, True),
        ("rejected", False, True),
        ("rejected", True, False),
        ("suspended", False, True),
        ("suspended", True, False),
        ("closed", False, True),
        ("closed", True, False),
    ],
)
def test_listing_decision_listed_must_fit_the_decision(
    decision: str, listed: bool, allowed: bool
) -> None:
    """Only a reinstatement may end either way; any other pair would be false copy."""
    context = {"approval_event_id": str(EVENT_ID), "decision": decision, "listed": listed}
    if allowed:
        assert validate_context("tutor_listing_decision", context)["listed"] is listed
    else:
        with pytest.raises(InvalidEmailContext):
            validate_context("tutor_listing_decision", context)


@pytest.mark.parametrize(("listed", "outcome"), [(True, "listed"), (False, "pending_review")])
def test_reinstatement_mail_says_where_the_profile_went(listed: bool, outcome: str) -> None:
    """T10 EXTRA: a reinstatement back to review never says "listed again" (SPEC §b.4)."""
    copy = spec_listing_copy()
    context = {"approval_event_id": str(EVENT_ID), "decision": "reinstated", "listed": listed}

    subject, html_body, text_body = render_email(
        "tutor_listing_decision", context, app_base_url=BASE_URL
    )

    other = "pending_review" if outcome == "listed" else "listed"
    lead = text_body.split("\n\n")[1]
    assert lead.startswith(copy[outcome])
    assert copy[other] not in html_body + text_body
    assert subject == "Your tutor profile"


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


# -- billing (Paymob billing Phase 05) -----------------------------------------

SUBSCRIPTION_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")


def _notice(notice: str, effective_at: str = "2026-12-10T09:00:00+00:00") -> dict[str, object]:
    return {
        "subscription_id": str(SUBSCRIPTION_ID),
        "notice": notice,
        "effective_at": effective_at,
    }


def test_billing_templates_are_disjoint_from_the_tutoring_spec() -> None:
    assert {
        "subscription_notice",
        "auto_topup_failed",
        "auto_topup_card_missing",
        "auto_topup_phone_required",
        "extra_seats_charge_failed",
        "plan_terms_change",
        "plan_terms_ends",
        "plan_terms_cancelled",
        "charge_after_plan_end",
    } == BILLING_EMAIL_TEMPLATES
    assert set(EMAIL_TEMPLATES) >= BILLING_EMAIL_TEMPLATES
    assert BILLING_EMAIL_TEMPLATES.isdisjoint(set(VALID))
    template = EMAIL_TEMPLATES["subscription_notice"]
    assert template.notification_type.value == "billing"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("notice", "words"),
    [
        ("renewed", "renewed"),
        ("payment_failed", "could not take"),
        ("expired", "ended"),
        ("cancelled", "cancelled"),
        ("credited", "added to your credits because you already have an active plan"),
    ],
)
def test_subscription_notice_renders_each_notice(notice: str, words: str) -> None:
    subject, html_body, text = render_email(
        "subscription_notice", _notice(notice), app_base_url=BASE_URL
    )
    assert subject == "Your Lemely plan"
    assert words in text
    assert "10 Dec 2026" in text
    assert f"{BASE_URL}/billing" in html_body
    assert f"{BASE_URL}/billing" in text


def test_subscription_notice_names_the_date_in_utc() -> None:
    # 23:30 UTC on 10 Dec is already 11 Dec in Cairo; the copy names the UTC date.
    _, _, late_utc = render_email(
        "subscription_notice",
        _notice("renewed", "2026-12-10T23:30:00+00:00"),
        app_base_url=BASE_URL,
    )
    assert "10 Dec 2026" in late_utc
    assert "11 Dec" not in late_utc
    # The same instant written with a +02:00 offset names the same UTC date.
    _, _, offset = render_email(
        "subscription_notice",
        _notice("renewed", "2026-12-11T01:30:00+02:00"),
        app_base_url=BASE_URL,
    )
    assert "10 Dec 2026" in offset
    assert "11 Dec" not in offset


ALL_NOTICES = ["renewed", "payment_failed", "expired", "cancelled", "credited"]


@pytest.mark.parametrize("notice", ALL_NOTICES)
def test_subscription_notice_carries_no_amount_card_or_plan_detail(notice: str) -> None:
    _, html_body, text = render_email("subscription_notice", _notice(notice), app_base_url=BASE_URL)
    for rendered in (html_body, text):
        assert "EGP" not in rendered
        assert "card" not in rendered.lower()
        assert str(SUBSCRIPTION_ID) not in rendered
    # Strip the one date the copy states: no other digit may remain in the plain text.
    assert not re.search(r"\d", text.replace("10 Dec 2026", ""))
    fields = EMAIL_TEMPLATES["subscription_notice"].context_fields  # type: ignore[attr-defined]
    assert fields == {"subscription_id", "notice", "effective_at"}


def test_subscription_notice_rejects_extra_keys_unknown_notices_and_naive_instants() -> None:
    assert validate_context("subscription_notice", _notice("renewed"))
    for extra in ("note", "email", "amount", "plan_name", "amount_minor", "card_last4"):
        with pytest.raises(InvalidEmailContext):
            validate_context("subscription_notice", {**_notice("renewed"), extra: "x"})
    with pytest.raises(InvalidEmailContext):
        validate_context("subscription_notice", _notice("refunded"))
    with pytest.raises(InvalidEmailContext):
        validate_context("subscription_notice", _notice("renewed", "2026-12-10T09:00:00"))
    for key in _notice("renewed"):
        partial = {k: v for k, v in _notice("renewed").items() if k != key}
        with pytest.raises(InvalidEmailContext):
            validate_context("subscription_notice", partial)


@pytest.mark.parametrize("notice", ALL_NOTICES)
def test_subscription_notice_copy_makes_no_promise_about_retries_refunds_or_the_processor(
    notice: str,
) -> None:
    subject, html_body, text = render_email(
        "subscription_notice", _notice(notice), app_base_url=BASE_URL
    )
    for rendered in (subject, html_body, text):
        lowered = rendered.lower()
        for word in ("retry", "paymob", "refund"):
            assert word not in lowered


# -- plan terms notices (UD13-A, UD13-E: no amount) ----------------------------------------


def _terms_change(**overrides: object) -> dict[str, object]:
    return {
        "subscription_id": str(SUBSCRIPTION_ID),
        "applies_at": "2026-12-10T09:00:00+00:00",
        "price_changes": True,
        "entitlements_change": False,
        **overrides,
    }


def test_terms_templates_are_cap_exempt_billing_templates() -> None:
    for name in (
        "plan_terms_change",
        "plan_terms_ends",
        "plan_terms_cancelled",
        "charge_after_plan_end",
    ):
        template = EMAIL_TEMPLATES[name]
        assert name in BILLING_EMAIL_TEMPLATES
        assert template.notification_type.value == "billing"  # type: ignore[attr-defined]


def test_terms_change_names_the_date_and_how_to_cancel_and_no_amount() -> None:
    _, html_body, text = render_email("plan_terms_change", _terms_change(), app_base_url=BASE_URL)
    assert "10 Dec 2026" in text
    assert "price" in text
    assert "cancel" in text.lower()
    assert not re.search(r"\d[\d,.]*\s*(EGP|SAR|AED|OMR|USD)|EGP|\$", html_body + text)
    assert f"{BASE_URL}/billing" in text


def test_terms_change_says_how_many_students_to_remove_or_seats_to_add() -> None:
    _, _, text = render_email(
        "plan_terms_change",
        _terms_change(seats_over=2, entitlements_change=True),
        app_base_url=BASE_URL,
    )
    assert "remove 2 students or add 2 seats before 10 Dec 2026" in text


def test_terms_change_without_excess_seats_says_nothing_about_removing() -> None:
    _, _, text = render_email("plan_terms_change", _terms_change(), app_base_url=BASE_URL)
    assert "remove" not in text.lower()


def test_terms_ends_says_the_plan_ends_and_to_subscribe_again() -> None:
    _, _, text = render_email(
        "plan_terms_ends",
        {"subscription_id": str(SUBSCRIPTION_ID), "ends_at": "2026-12-10T09:00:00+00:00"},
        app_base_url=BASE_URL,
    )
    assert "ends on 10 Dec 2026" in text
    assert "subscribe again" in text.lower()
    assert "open billing" in text.lower()  # how to re-subscribe
    assert "EGP" not in text


def test_terms_contexts_refuse_extra_keys_and_naive_instants() -> None:
    assert validate_context("plan_terms_change", _terms_change())
    with pytest.raises(InvalidEmailContext):
        validate_context("plan_terms_change", {**_terms_change(), "amount_minor": 100})
    with pytest.raises(InvalidEmailContext):
        validate_context("plan_terms_change", _terms_change(applies_at="2026-12-10T09:00:00"))
    with pytest.raises(InvalidEmailContext):
        validate_context("plan_terms_ends", {"subscription_id": str(SUBSCRIPTION_ID)})


def test_terms_cancelled_says_the_change_is_cancelled_and_carries_no_amount() -> None:
    subject, html_body, text = render_email(
        "plan_terms_cancelled", {"subscription_id": str(SUBSCRIPTION_ID)}, app_base_url=BASE_URL
    )
    assert "has been cancelled" in text
    assert "has been cancelled" in subject
    assert "price" not in text.lower()  # the copy promises no price: the processor may lag
    assert not re.search(r"\d[\d,.]*\s*(EGP|SAR|AED|OMR|USD)|EGP|\$", html_body + text)
    assert f"{BASE_URL}/billing" in text


def test_terms_cancelled_context_refuses_extra_keys() -> None:
    assert validate_context("plan_terms_cancelled", {"subscription_id": str(SUBSCRIPTION_ID)})
    with pytest.raises(InvalidEmailContext):
        validate_context(
            "plan_terms_cancelled", {"subscription_id": str(SUBSCRIPTION_ID), "amount_minor": 1}
        )


def test_terms_cancelled_names_the_announced_amount_risk_not_the_earlier_one() -> None:
    """R2-M5: the amount at risk is the one we ANNOUNCED, never "the earlier amount"."""
    _, _, text = render_email(
        "plan_terms_cancelled", {"subscription_id": str(SUBSCRIPTION_ID)}, app_base_url=BASE_URL
    )
    assert "announced" in text
    assert "earlier amount" not in text
    assert "refund the difference" in text


def test_terms_cancelled_for_a_withdrawn_cancel_says_the_plan_renews_and_charges_the_card() -> None:
    subject, _, text = render_email(
        "plan_terms_cancelled",
        {"subscription_id": str(SUBSCRIPTION_ID), "plan_continues": True},
        app_base_url=BASE_URL,
    )
    assert "will not end" in text
    assert "renew" in text
    assert "card will be charged" in text
    assert "cancel your plan in billing" in text
    assert "cancelled" in subject
    assert not re.search(r"\d[\d,.]*\s*(EGP|SAR|AED|OMR|USD)|EGP|\$", text)


PAYMENT_ID_FOR_REFUND = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def test_charge_after_plan_end_says_it_will_be_refunded_and_states_no_amount() -> None:
    subject, html_body, text = render_email(
        "charge_after_plan_end", {"payment_id": str(PAYMENT_ID_FOR_REFUND)}, app_base_url=BASE_URL
    )
    assert "after it was set to end" in text
    assert "refund it" in text
    assert "refunded" in subject
    assert not re.search(r"\d[\d,.]*\s*(EGP|SAR|AED|OMR|USD)|EGP|\$", html_body + text)
    assert f"{BASE_URL}/billing" in text


def test_charge_after_plan_end_context_refuses_extra_keys_and_a_missing_payment() -> None:
    assert validate_context("charge_after_plan_end", {"payment_id": str(PAYMENT_ID_FOR_REFUND)})
    with pytest.raises(InvalidEmailContext):
        validate_context(
            "charge_after_plan_end",
            {"payment_id": str(PAYMENT_ID_FOR_REFUND), "amount_minor": 1},
        )
    with pytest.raises(InvalidEmailContext):
        validate_context("charge_after_plan_end", {})


def test_charge_after_plan_end_for_a_plan_that_had_ended_says_so_and_promises_no_end_date() -> None:
    _, _, text = render_email(
        "charge_after_plan_end",
        {"payment_id": str(PAYMENT_ID_FOR_REFUND), "plan_ended": True},
        app_base_url=BASE_URL,
    )
    assert "after it had ended" in text
    assert "refund it" in text
    assert "still ends" not in text  # it already ended
