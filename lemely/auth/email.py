"""Email delivery seam for verification and password-reset links.

``EmailProvider`` is the single switch point between the offline mock used in
dev/tests and the real transactional-email service — swapping the
implementation injected into :class:`~lemely.auth.service.AuthService` is the
only change required. This is deliberately the same shape as
:mod:`lemely.auth.sms`, because that module already solved this problem and
already reasoned through the dangerous part.

Each provider declares :attr:`EmailProvider.delivers_out_of_band`: whether it
actually gets the link (and, for verification, the code sent alongside it —
spec §4.4/DS15) to the recipient's inbox by a channel outside this API. That
flag — **not** an environment string — is what gates whether the auth routes
may hand the link or code back for §G-06/§G-07's developer affordance,
exactly as D3.16 gates the OTP's ``devCode``. A provider that does deliver
never leaks a live link or code through the API; a provider that does not
deliver is the only situation in which the API is the sole way to obtain
either.

**The honesty rule that follows from it.** ``deps.py`` now wires
:class:`ResendEmailProvider` when ``[email] api_key`` is configured and
:class:`MockEmailProvider` when it is not, so whether a mail is really sent is
a deployment fact rather than a constant. No screen and no page description may
therefore *hardcode* the claim that a mail was sent — they read
:attr:`EmailProvider.delivers_out_of_band` and say what is true for the
provider actually running. ``routes.tsx`` records the same problem for the
parent OTP screen, which does make that claim unconditionally; this seam ships
without repeating it.

**Why Resend rather than Cloudflare.** ``lemelyig.com``'s DNS is on Cloudflare
and the SPF/DKIM/DMARC records authorising this sender live in that zone, but
Cloudflare Email Sending is not available on the Workers Free plan: that plan
gets inbound Email Routing plus outbound only to addresses already verified
inside the account, and someone signing up never is. Resend's free tier covers
the same ground at no cost, and the domain a recipient sees is ``lemelyig.com``
either way. ``docs/email-delivery.md`` holds the DNS records and the migration
note for moving to Cloudflare Email Sending should the account ever go Paid.
"""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urljoin

import httpx

from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from lemely.runtime.config import EmailSettings

logger = logging.getLogger("lemely.auth.email")


class EmailProvider(Protocol):
    """Delivers an account-lifecycle link to an email address."""

    delivers_out_of_band: bool
    """True when the link and code actually reach the inbox by a channel
    outside this API (a real mail service). False means the API is the only
    way to obtain them, which is the sole condition under which a route may
    return either. Any real provider added later **must** set this True.

    Setting it True carries a second obligation: ``link`` arrives as a
    *frontend route* (``/verify-email/<token>``), and an inbox has no origin to
    resolve that against, so a provider that delivers out of band must join it
    onto a configured origin before sending. Skipping that step is not a
    cosmetic bug — it mails an unreachable ``http:///…`` URL."""

    def send_verification(self, email: str, link: str, code: str) -> None:
        """Deliver an email-verification ``link`` and typed ``code`` to ``email``.

        The two are independent, equivalent credentials (spec §4.4/DS15): a
        recipient who cannot follow the link — a different device, a mangled
        mail client — can instead type ``code`` into the app. Raises on
        failure.
        """
        ...

    def send_password_reset(self, email: str, link: str) -> None:
        """Deliver a password-reset ``link`` to ``email``. Raises on failure."""
        ...

    def send_signup_code(self, email: str, code: str) -> None:
        """Deliver a parent-signup verification ``code`` to ``email`` (spec §4).

        Unlike :meth:`send_verification`, there is no accompanying link: the
        parent-invite signup flow proves an email address *before* any account
        exists, so there is nothing yet for a link to point at — the typed
        code is the only credential. Raises on failure.
        """
        ...

    def send_contact_message(self, from_email: str, message: str) -> None:
        """Forward a landing-page visitor's question to the team. Raises on failure.

        ``from_email`` is the visitor's own, already-validated address; a real
        provider sets it as ``Reply-To`` so the team can answer directly.
        """
        ...

    def send_waitlist_confirmation(self, email: str, link: str) -> None:
        """Mail a waitlist applicant the link that confirms their address. Raises on failure.

        ``link`` is a frontend route (``/waitlist/confirm?token=...``); a real provider joins
        it onto the configured app origin. The mail carries the address and nothing else.
        """
        ...

    def send_team_digest(self, subject: str, text_body: str) -> None:
        """Mail an internal plain-text digest to the team address. Raises on failure.

        The body is composed by the caller from aggregates only: it must never carry an
        applicant's email or phone number.
        """
        ...


class MockEmailProvider:
    """Offline :class:`EmailProvider` that logs the link instead of sending it.

    Intended for local dev and tests: the link (and code) are written to the
    ``lemely.auth.email`` logger at ``INFO`` so a developer can copy either from
    the console. Because nothing reaches an inbox, :attr:`delivers_out_of_band`
    is False and the auth routes may surface both for the §G-06/§G-07 developer
    affordance.
    """

    delivers_out_of_band = False

    def send_verification(self, email: str, link: str, code: str) -> None:
        """Log the verification link and code for ``email`` at INFO level."""
        logger.info("Mock email to %s: verify at %s or enter code %s", email, link, code)

    def send_password_reset(self, email: str, link: str) -> None:
        """Log the reset link for ``email`` at INFO level."""
        logger.info("Mock email to %s: reset your Lemely password at %s", email, link)

    def send_signup_code(self, email: str, code: str) -> None:
        """Log the parent-signup code for ``email`` at INFO level."""
        logger.info("Mock email to %s: your Lemely signup code is %s", email, code)

    def send_contact_message(self, from_email: str, message: str) -> None:
        """Log that a landing-page question arrived (sender and length only)."""
        logger.info("Mock contact message from %s (%d characters)", from_email, len(message))

    def send_waitlist_confirmation(self, email: str, link: str) -> None:
        """Log the waitlist confirmation link for ``email`` at INFO level."""
        logger.info("Mock email to %s: confirm your waitlist spot at %s", email, link)

    def send_team_digest(self, subject: str, text_body: str) -> None:
        """Log that a team digest would have been sent (subject and length only)."""
        logger.info("Mock team digest %r (%d characters)", subject, len(text_body))


#: Body copy per purpose: (subject, lead paragraph, button label, ignore-notice).
#: Kept as data rather than four near-identical template functions because the
#: two mails differ only in wording. Deliberately states no expiry *duration* —
#: the real lifetimes are ``[auth] email_verification_ttl_seconds`` and
#: ``password_reset_ttl_seconds``, and a number written here would silently
#: drift from them the first time either is tuned.
_TEMPLATES = {
    "verification": (
        "Verify your Lemely email address",
        "Confirm this address to finish setting up your Lemely account.",
        "Verify email address",
        "If you did not create a Lemely account, you can ignore this email.",
    ),
    "password_reset": (
        "Reset your Lemely password",
        "Use the link below to choose a new password for your Lemely account.",
        "Reset password",
        (
            "If you did not ask to reset your password, you can ignore this "
            "email — your current password still works."
        ),
    ),
}


def _render(purpose: str, link: str, code: str | None = None) -> tuple[str, str, str]:
    """Return ``(subject, html_body, text_body)`` for ``purpose`` and ``link``.

    ``code`` is DS15's typed six digits, shown beside the link when the
    purpose has one (verification does; password reset does not). It is the
    same credential in a form someone can retype on a second device, so it
    appears in both the HTML and the plain-text alternative.

    The HTML is a single document with every style inlined: mail clients strip
    ``<style>`` blocks and external CSS unpredictably, so any rule that must
    survive has to sit on the element. The plain-text part is a real
    alternative rather than a stripped-tags afterthought — a recipient reading
    it must be able to complete the action, so the URL appears in full.
    """
    subject, lead, button, notice = _TEMPLATES[purpose]
    safe_link = html.escape(link, quote=True)
    code_html = (
        ""
        if code is None
        else (
            '<p style="margin:0 0 24px;font-size:13px;line-height:1.5;color:#52606d;">'
            "Or enter this code:</p>"
            '<p style="margin:0 0 24px;font-size:22px;line-height:1.3;font-weight:600;'
            f'letter-spacing:0.12em;">{html.escape(code)}</p>'
        )
    )
    code_text = "" if code is None else f"Or enter this code: {code}\n\n"

    html_body = (
        '<!doctype html><html lang="en"><body style="margin:0;padding:24px;'
        "background:#f6f7f9;font-family:-apple-system,BlinkMacSystemFont,"
        "'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2933;\">"
        '<div style="max-width:480px;margin:0 auto;background:#ffffff;'
        'border-radius:12px;padding:32px;">'
        f'<h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;">{html.escape(subject)}</h1>'
        f'<p style="margin:0 0 24px;font-size:15px;line-height:1.55;">{html.escape(lead)}</p>'
        f'<p style="margin:0 0 24px;"><a href="{safe_link}" '
        'style="display:inline-block;background:#1f2933;color:#ffffff;'
        "text-decoration:none;padding:12px 20px;border-radius:8px;"
        f'font-size:15px;font-weight:600;">{html.escape(button)}</a></p>'
        '<p style="margin:0 0 8px;font-size:13px;line-height:1.5;color:#52606d;">'
        "If the button does not work, copy this link into your browser:</p>"
        '<p style="margin:0 0 24px;font-size:13px;line-height:1.5;word-break:break-all;">'
        f'<a href="{safe_link}" style="color:#2563eb;">{safe_link}</a></p>'
        f"{code_html}"
        '<p style="margin:0;font-size:13px;line-height:1.5;color:#52606d;">'
        f"{html.escape(notice)}</p>"
        "</div></body></html>"
    )

    text_body = f"{subject}\n\n{lead}\n\n{link}\n\n{code_text}{notice}\n"
    return subject, html_body, text_body


def _render_signup_code(code: str) -> tuple[str, str, str]:
    """Return ``(subject, html_body, text_body)`` for a parent-signup code mail.

    Deliberately not routed through :func:`_render`: that function's template
    is built around a link and a button, and a signup code has neither — the
    account this would link to does not exist yet (spec §4). Reusing it would
    render an empty, broken button rather than simply omitting one.

    States the expiry as ten minutes rather than reading
    ``[auth] email_otp_ttl_seconds`` live, for the same reason
    :data:`_TEMPLATES` states no duration at all: a number written here would
    silently drift from the setting the first time it is tuned. Ten minutes is
    that setting's default (spec §4/DS15's task brief), so it is accurate until
    someone changes the default without also changing this copy.
    """
    subject = "Your Lemely code"
    safe_code = html.escape(code)
    lead = "Enter this code to continue setting up your Lemely account."
    notice = (
        "This code expires in ten minutes. If you did not request it, you can ignore this email."
    )
    html_body = (
        '<!doctype html><html lang="en"><body style="margin:0;padding:24px;'
        "background:#f6f7f9;font-family:-apple-system,BlinkMacSystemFont,"
        "'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2933;\">"
        '<div style="max-width:480px;margin:0 auto;background:#ffffff;'
        'border-radius:12px;padding:32px;">'
        f'<h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;">{html.escape(subject)}</h1>'
        f'<p style="margin:0 0 24px;font-size:15px;line-height:1.55;">{html.escape(lead)}</p>'
        '<p style="margin:0 0 24px;font-size:22px;line-height:1.3;font-weight:600;'
        f'letter-spacing:0.12em;">{safe_code}</p>'
        '<p style="margin:0;font-size:13px;line-height:1.5;color:#52606d;">'
        f"{html.escape(notice)}</p>"
        "</div></body></html>"
    )
    text_body = f"{subject}\n\n{lead}\n\n{code}\n\n{notice}\n"
    return subject, html_body, text_body


# Waitlist confirmation: brand colours resolved to hex (Abyss, Tide and their neutral steps). Mail
# clients have no CSS variables, so the web app's role tokens cannot be referenced from here.
_WL_ABYSS = "#042f4f"
_WL_WASH = "#cfe9f9"
_WL_PAGE = "#eef3f7"
_WL_INK = "#130e10"
_WL_MUTED = "#515d65"
_WL_RULE = "#cdd5db"
_WL_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_WL_DISPLAY = "'Bricolage Grotesque','Avenir Next','Trebuchet MS','Arial Black',Arial,sans-serif"

_WL_SUBJECT = "Confirm your spot on the Lemely waitlist"
_WL_PREHEADER = "One tap to confirm your email."
_WL_HEADLINE = "One quick tap, then you're set."
_WL_LEAD = (
    "Thanks for joining the Lemely waitlist. Confirm your email and we'll write when access opens."
)
_WL_BUTTON = "Confirm my email"
_WL_FALLBACK = "Button not working? Paste this link into your browser:"
_WL_WHY = (
    "You're getting this because you asked to join the Lemely waitlist. "
    "If that wasn't you, ignore this email and nothing happens."
)
_WL_CONTACT = "contact@lemelyig.com"

# Dark-mode overrides for clients that honour ``prefers-color-scheme`` (Apple Mail, iOS, the
# Outlook apps). Gmail and others ignore this block and recolour on their own; every colour is
# also inline, so losing the block loses only the dark restyle.
_WL_DARK_CSS = (
    ":root{color-scheme:light dark;supported-color-schemes:light dark;}"
    "@media (prefers-color-scheme: dark){"
    ".bg-page{background-color:#080e13 !important;}"
    ".bg-card{background-color:#0f151a !important;border-color:#1a232b !important;}"
    ".bg-wash{background-color:#0b3a5b !important;}"
    ".tx{color:#ebeff2 !important;}"
    ".tx-muted{color:#acb6bd !important;}"
    ".rule{border-color:#1a232b !important;}"
    ".btn-cell{background-color:#7fb8e0 !important;}"
    ".btn-a{color:#042f4f !important;}"
    ".lnk{color:#7fb8e0 !important;}"
    "}"
    "[data-ogsc] .tx{color:#ebeff2 !important;}"
    "[data-ogsc] .tx-muted{color:#acb6bd !important;}"
    "[data-ogsb] .bg-page{background-color:#080e13 !important;}"
    "[data-ogsb] .bg-card{background-color:#0f151a !important;}"
    "[data-ogsb] .bg-wash{background-color:#0b3a5b !important;}"
)


def _waitlist_image(
    base: str, name: str, width: int, height: int, alt: str, style: str = ""
) -> str:
    """One hosted PNG as an ``<img>``. Absolute URL, because an inbox has no origin."""
    src = html.escape(f"{base}/email/{name}")
    return (
        f'<img src="{src}" width="{width}" height="{height}" alt="{html.escape(alt)}" '
        'style="display:block;border:0;outline:none;text-decoration:none;'
        f'-ms-interpolation-mode:bicubic;{style}">'
    )


def _waitlist_button(safe_link: str) -> str:
    """A bulletproof button: a VML round-rect for Outlook's Word engine, a padded link elsewhere."""
    label = html.escape(_WL_BUTTON)
    return (
        f'<!--[if mso]><v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" href="{safe_link}" '
        'style="height:52px;v-text-anchor:middle;width:240px;" arcsize="27%" stroke="f" '
        f'fillcolor="{_WL_ABYSS}"><w:anchorlock xmlns:w="urn:schemas-microsoft-com:office:word"/>'
        '<center style="color:#ffffff;font-family:Arial,sans-serif;font-size:17px;'
        f'font-weight:bold;">{label}</center></v:roundrect><![endif]-->'
        "<!--[if !mso]><!-->"
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:separate;"><tr>'
        f'<td class="btn-cell" align="center" bgcolor="{_WL_ABYSS}" '
        f'style="border-radius:14px;background-color:{_WL_ABYSS};">'
        f'<a class="btn-a" href="{safe_link}" target="_blank" '
        f'style="display:inline-block;padding:16px 32px;font-family:{_WL_FONT};font-size:17px;'
        'line-height:20px;font-weight:700;color:#ffffff;text-decoration:none;border-radius:14px;">'
        f"{label}</a></td></tr></table><!--<![endif]-->"
    )


def _render_waitlist_confirmation(link: str, *, app_base_url: str = "") -> tuple[str, str, str]:
    """Return ``(subject, html_body, text_body)`` for the waitlist confirmation mail.

    Branded and short: the Lemely wordmark on an Abyss band, Binny on a Tide wash, one headline,
    one sentence, one button, the link again in the open, and one line on why they got it. No
    dates, counts or promises, and no expiry duration (the token's lifetime is a setting, so a
    number here would drift from it, as :data:`_TEMPLATES` notes).

    Contract (pinned by ``tests/test_auth_email.py``): ``link`` is absolute and appears
    HTML-escaped in the button ``href`` and in the visible fallback text, never raw, and verbatim
    in the text body. Nothing else about the applicant is an input, so nothing else can appear.
    ``app_base_url`` (no trailing-slash guarantee) builds the absolute URLs of the images in
    ``web/public/email/``; with it empty the images are left out rather than emitting a broken
    ``src``, and the header falls back to the word "Lemely".
    """
    safe_link = html.escape(link)
    base = app_base_url.rstrip("/")

    if base:
        wordmark = _waitlist_image(base, "lemely-wordmark.png", 104, 39, "Lemely")
        binny = _waitlist_image(
            base, "binny.png", 126, 171, "Binny, the Lemely mascot", "margin:0 auto;"
        )
        hero = (
            f'<tr><td class="bg-wash" align="center" bgcolor="{_WL_WASH}" valign="bottom" '
            f'style="padding:32px 32px 0;background-color:{_WL_WASH};line-height:0;'
            f'font-size:0;">{binny}</td></tr>'
        )
    else:
        wordmark = (
            f'<span style="font-family:{_WL_DISPLAY};font-size:26px;font-weight:800;'
            'color:#ffffff;">Lemely</span>'
        )
        hero = ""

    head = (
        '<!doctype html><html lang="en" xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:o="urn:schemas-microsoft-com:office:office"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="supported-color-schemes" content="light dark">'
        f"<title>{html.escape(_WL_SUBJECT)}</title>"
        "<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96"
        "</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->"
        f"<style>{_WL_DARK_CSS}</style></head>"
    )
    preheader = (
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;font-size:1px;'
        f'line-height:1px;color:{_WL_PAGE};">{html.escape(_WL_PREHEADER)}'
        "&#8199;&#847;&#8199;&#847;&#8199;&#847;</div>"
    )
    card_open = (
        f'<body class="bg-page" style="margin:0;padding:0;background-color:{_WL_PAGE};">'
        f"{preheader}"
        '<table role="presentation" class="bg-page" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" bgcolor="{_WL_PAGE}" style="background-color:{_WL_PAGE};"><tr>'
        '<td align="center" style="padding:24px 12px;">'
        '<table role="presentation" class="bg-card" width="560" cellpadding="0" cellspacing="0" '
        'border="0" bgcolor="#ffffff" style="width:100%;max-width:560px;'
        f"background-color:#ffffff;border:1px solid {_WL_RULE};border-radius:20px;"
        'border-collapse:separate;overflow:hidden;">'
        f'<tr><td bgcolor="{_WL_ABYSS}" style="padding:22px 32px;'
        f'background-color:{_WL_ABYSS};">{wordmark}</td></tr>'
        f"{hero}"
    )
    copy = (
        f'<tr><td class="tx" style="padding:32px 32px 8px;font-family:{_WL_FONT};'
        f'color:{_WL_INK};"><h1 class="tx" style="margin:0 0 14px;font-family:{_WL_DISPLAY};'
        "font-size:32px;line-height:34px;font-weight:800;letter-spacing:-0.5px;"
        f'color:{_WL_ABYSS};">{html.escape(_WL_HEADLINE)}</h1>'
        f'<p class="tx" style="margin:0 0 28px;font-size:17px;line-height:26px;'
        f'color:{_WL_INK};">{html.escape(_WL_LEAD)}</p>'
        f"{_waitlist_button(safe_link)}"
        f'<p class="tx-muted" style="margin:28px 0 6px;font-size:14px;line-height:21px;'
        f'color:{_WL_MUTED};">{html.escape(_WL_FALLBACK)}</p>'
        '<p style="margin:0 0 8px;font-size:14px;line-height:21px;word-break:break-all;">'
        f'<a class="lnk" href="{safe_link}" target="_blank" '
        f'style="color:{_WL_ABYSS};text-decoration:underline;">{safe_link}</a></p></td></tr>'
    )
    footer = (
        f'<tr><td style="padding:24px 32px 32px;font-family:{_WL_FONT};">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td class="rule" style="border-top:1px solid {_WL_RULE};padding-top:20px;">'
        f'<p class="tx-muted" style="margin:0 0 10px;font-size:13px;line-height:20px;'
        f'color:{_WL_MUTED};">{html.escape(_WL_WHY)}</p>'
        f'<p class="tx-muted" style="margin:0;font-size:13px;line-height:20px;'
        f'color:{_WL_MUTED};">Questions? <a class="lnk" href="mailto:{_WL_CONTACT}" '
        f'style="color:{_WL_ABYSS};">{_WL_CONTACT}</a></p></td></tr></table></td></tr>'
        "</table></td></tr></table></body></html>"
    )
    html_body = head + card_open + copy + footer

    text_body = (
        f"{_WL_SUBJECT}\n\n{_WL_LEAD}\n\n{_WL_BUTTON}: {link}\n\n{_WL_WHY}\n\n"
        f"Questions? {_WL_CONTACT}\n"
    )
    return _WL_SUBJECT, html_body, text_body


def _render_contact_message(from_email: str, message: str) -> tuple[str, str, str]:
    """Return ``(subject, html_body, text_body)`` for a landing-page question.

    Both ``from_email`` and ``message`` come from an anonymous visitor, so the
    HTML escapes both and the subject has every control character (CR/LF in
    particular, which would otherwise allow header injection) collapsed to a
    space.
    """
    clean_email = " ".join(from_email.split())
    subject = f"Landing page question from {clean_email}"
    safe_email = html.escape(clean_email)
    safe_message = html.escape(message).replace("\r\n", "\n").replace("\r", "\n")
    safe_message = safe_message.replace("\n", "<br>")
    html_body = (
        '<!doctype html><html lang="en"><body style="margin:0;padding:24px;'
        "background:#f6f7f9;font-family:-apple-system,BlinkMacSystemFont,"
        "'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2933;\">"
        '<div style="max-width:480px;margin:0 auto;background:#ffffff;'
        'border-radius:12px;padding:32px;">'
        '<p style="margin:0 0 16px;font-size:13px;line-height:1.5;color:#52606d;">'
        f"From {safe_email}. Reply to this email to answer them.</p>"
        f'<p style="margin:0;font-size:15px;line-height:1.55;">{safe_message}</p>'
        "</div></body></html>"
    )
    text_body = f"From {clean_email}. Reply to this email to answer them.\n\n{message}\n"
    return subject, html_body, text_body


class ResendEmailProvider:
    """Real :class:`EmailProvider` sending over Resend's REST API.

    Synchronous ``httpx`` to match the codebase's call style and
    :class:`~lemely.auth.gotrue.HttpGoTrueBackend` in particular. The client is
    injectable for the same reason
    :class:`~lemely.web.push.VapidPushTransport`'s is: a test can drive real
    status codes through ``httpx.MockTransport`` without a network.

    :attr:`delivers_out_of_band` is True, which is what stops the auth routes
    returning a live link through the API once this provider is wired — the
    link is a bearer credential, and with a real sender the inbox is the only
    place it belongs.

    Failures raise :class:`~lemely.runtime.errors.ExternalServiceError`. Both
    call sites in :class:`~lemely.auth.service.AuthService` already decide what
    a failure means (``_try_send_verification`` swallows it to avoid stranding a
    just-created account; ``_try_send_password_reset`` swallows it to preserve
    anti-enumeration), so raising here is the honest report and never reaches a
    user as a 500.
    """

    delivers_out_of_band = True

    def __init__(self, settings: EmailSettings, client: httpx.Client | None = None) -> None:
        """Build a provider from ``[email]`` settings, optionally with a test client.

        Raises:
            ValueError: ``settings.api_key`` is unset. Callers pick the provider
                by that key's presence (see ``lemely.web.deps``), so reaching
                here without one is a wiring bug, not a runtime condition — and
                a provider that silently could not send while reporting
                ``delivers_out_of_band = True`` would suppress the dev link as
                well, leaving no way at all to obtain it.
        """
        if settings.api_key is None:
            raise ValueError(
                "ResendEmailProvider requires [email] api_key; "
                "wire MockEmailProvider when no key is configured."
            )
        self._settings = settings
        self._api_key = settings.api_key.get_secret_value()
        self._client = client or httpx.Client(timeout=settings.timeout_seconds)

    @property
    def _sender(self) -> str:
        """The ``From:`` header, as ``Display Name <address>``."""
        return f"{self._settings.from_name} <{self._settings.from_address}>"

    def _absolute(self, link: str) -> str:
        """Resolve ``link`` against the configured app origin.

        :class:`~lemely.auth.service.AuthService` mints links as *frontend
        routes* — ``/verify-email/<token>`` — because the SPA navigates to them
        directly and the API returns them as dev links. That is meaningless in
        an inbox: a mail client resolving a root-relative href against no base
        produced ``http:///verify-email/<token>``, an empty-host URL that
        cannot be reached. Absolutising here rather than in ``AuthService``
        keeps the dev link relative, which is what the SPA wants, and puts the
        join at the one boundary that actually requires it.

        :func:`~urllib.parse.urljoin` also makes this idempotent — an already
        absolute link passes through untouched — so a future caller that mints
        full URLs is not double-prefixed.
        """
        return urljoin(self._settings.app_base_url, link)

    def send_verification(self, email: str, link: str, code: str) -> None:
        """Send the email-verification ``link`` and typed ``code`` to ``email``.

        Both credentials go in one mail (spec §4.4/DS15). The signature gained
        ``code`` when DS15 landed; #220 wrote this provider against the older
        two-argument shape, and because ``AuthService._try_send_verification``
        swallows delivery errors, a mismatch here would have meant signups
        succeeding while no verification mail ever left the building.
        """
        self._send(email, *_render("verification", self._absolute(link), code))

    def send_password_reset(self, email: str, link: str) -> None:
        """Send the password-reset ``link`` to ``email``."""
        self._send(email, *_render("password_reset", self._absolute(link)))

    def send_signup_code(self, email: str, code: str) -> None:
        """Send the parent-signup code to ``email`` (subject "Your Lemely code").

        No link to absolutise here — see :func:`_render_signup_code` for why
        this purpose has none.
        """
        self._send(email, *_render_signup_code(code))

    def send_contact_message(self, from_email: str, message: str) -> None:
        """Forward a landing-page visitor's question to ``[email] contact_address``.

        ``Reply-To`` is the visitor's address so the team answers them directly.
        """
        subject, html_body, text_body = _render_contact_message(from_email, message)
        self._send(
            self._settings.contact_address,
            subject,
            html_body,
            text_body,
            reply_to=from_email,
        )

    def send_waitlist_confirmation(self, email: str, link: str) -> None:
        """Send the waitlist confirmation ``link`` (a frontend route) to ``email``."""
        self._send(
            email,
            *_render_waitlist_confirmation(
                self._absolute(link), app_base_url=self._settings.app_base_url
            ),
        )

    def send_team_digest(self, subject: str, text_body: str) -> None:
        """Send an internal plain-text digest to ``[email] contact_address``."""
        clean_subject = " ".join(subject.split())
        html_body = (
            '<!doctype html><html lang="en"><body style="margin:0;padding:24px;'
            "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,"
            'Arial,sans-serif;color:#1f2933;">'
            '<pre style="margin:0;font:inherit;white-space:pre-wrap;">'
            f"{html.escape(text_body)}</pre></body></html>"
        )
        self._send(self._settings.contact_address, clean_subject, html_body, text_body)

    def _send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        reply_to: str | None = None,
    ) -> None:
        """POST one mail to Resend, raising :class:`ExternalServiceError` on failure.

        The link is never logged here, on success or on failure: it is a live
        credential, and this provider exists precisely because it should reach
        an inbox and nowhere else. Only the recipient, the subject, and the
        provider's own message id are recorded.

        ``reply_to`` overrides ``[email] reply_to`` for this one mail.
        """
        payload: dict[str, object] = {
            "from": self._sender,
            "to": [to],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        }
        effective_reply_to = reply_to if reply_to is not None else self._settings.reply_to
        if effective_reply_to is not None:
            payload["reply_to"] = effective_reply_to

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
            raise ExternalServiceError(f"Email delivery to {to} failed: {exc}") from exc

        if response.status_code >= 400:
            # Resend reports the reason in the body; include it, truncated,
            # because "422" alone has never been enough to fix a sender
            # problem (an unverified domain and a malformed From: both 4xx).
            raise ExternalServiceError(
                f"Email delivery to {to} was rejected "
                f"(HTTP {response.status_code}): {response.text[:300]}"
            )

        logger.info("Sent %r email to %s (message id %s)", subject, to, _message_id(response))

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()


def _message_id(response: httpx.Response) -> str:
    """Best-effort provider message id from a success response, for logs only.

    A body that is not the JSON object the API documents is not worth failing a
    send that already returned 2xx — the mail is accepted either way, and this
    value exists only to make a delivery traceable in the provider's dashboard.
    """
    try:
        body = response.json()
    except ValueError:
        return "unknown"
    return str(body.get("id", "unknown")) if isinstance(body, dict) else "unknown"


__all__ = ["EmailProvider", "MockEmailProvider", "ResendEmailProvider"]
