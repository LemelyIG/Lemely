"""Pure email-domain matching for the access gate.

While Lemely is not launched, signup and login are open only to accounts whose
email domain is on ``[access] allowed_email_domains``. This module owns the one
rule, with no I/O, so the HTTP layer, the auth service and the purge tool all
answer "is this address allowed?" the same way.

**Exact match, nothing clever.** An address is allowed when its domain, after
normalisation, *equals* an allowed domain. Subdomains (``x@sub.lemelyig.com``),
suffix lookalikes (``x@lemelyig.com.evil.com``, ``x@lemelyig.co``) and a trailing
dot (``x@lemelyig.com.``) are all different strings and so are refused.

**Hostile input is refused, not repaired.** An address that is not plain ASCII
(unicode homoglyphs: a Cyrillic letter standing in for a Latin one in
``lemelyig.com``) or whose local part holds a quote, a space, a second ``@`` or any
other character outside the plain RFC 5322 atom set is not allowed, whatever its
domain says. That closes the quoted-local-part trick (``"x@lemelyig.com"@evil.com``
splits on the last ``@`` to ``evil.com``, and ``x@evil.com"@lemelyig.com`` is refused for
the quote).

The ASCII test runs *before* lowercasing: ``str.lower`` maps some non-ASCII
characters (the Kelvin sign) onto ASCII letters, which would let a lookalike
through.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

MAX_EMAIL_LENGTH = 254

# RFC 5322 atext plus the dot, without quoted strings, comments or whitespace.
_LOCAL_PART = re.compile(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+")
# A multi-label DNS name: letters, digits and inner hyphens; no empty label.
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")


def normalise_domain(raw: str) -> str | None:
    """The canonical form of a configured domain, or ``None`` when it is not a valid one.

    Trims, lowercases and drops one leading ``@`` (so ``@lemelyig.com`` is accepted in
    config). Non-ASCII input is refused rather than folded.
    """
    text = raw.strip()
    if not text.isascii():
        return None
    text = text.lower().removeprefix("@")
    return text if _DOMAIN.fullmatch(text) else None


def email_domain(raw: str) -> str | None:
    """The normalised domain of ``raw``, or ``None`` when it is not a plain address.

    Trims, lowercases and splits on the **last** ``@``. ``None`` for anything not plain ASCII,
    over :data:`MAX_EMAIL_LENGTH`, with an empty or non-atom local part, or whose domain is not
    a well-formed multi-label name.
    """
    text = raw.strip()
    if not text.isascii() or len(text) > MAX_EMAIL_LENGTH:
        return None
    text = text.lower()
    local, separator, domain = text.rpartition("@")
    if not separator or not _LOCAL_PART.fullmatch(local):
        return None
    return domain if _DOMAIN.fullmatch(domain) else None


def is_allowed_email(raw: str | None, allowed_domains: Iterable[str]) -> bool:
    """Whether ``raw``'s domain equals one of ``allowed_domains`` (exact, case-insensitive).

    ``allowed_domains`` is taken as configured and normalised here, so a caller may pass the raw
    setting. An empty ``allowed_domains`` allows nothing: *open access* (no restriction at all)
    is decided by the caller, which skips the check, never by this function.
    """
    if raw is None:
        return False
    domain = email_domain(raw)
    if domain is None:
        return False
    allowed = {normalised for d in allowed_domains if (normalised := normalise_domain(d))}
    return domain in allowed


__all__ = ["MAX_EMAIL_LENGTH", "email_domain", "is_allowed_email", "normalise_domain"]
