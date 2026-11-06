"""``POST /api/contact`` DTOs: the landing-page FAQ composer's wire contract.

The visitor types a question and a reply-to address into the marketing page;
``lemely.web.routers.contact`` emails it to the team. Nothing is stored.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from lemely.web.schemas import ApiModel

# ``email-validator`` is not a dependency, and the address is only ever used as a
# Reply-To header and in a subject line, so this checks shape rather than
# deliverability: one ``@``, a dotted domain, and no whitespace, angle brackets,
# quotes, commas or semicolons. Excluding whitespace is also what rules out CR/LF
# header injection.
_EMAIL_PATTERN = r"^[^@\s<>\",;]+@[^@\s<>\",;]+\.[^@\s<>\",;]+$"


class ContactMessageDTO(ApiModel):
    """One question from the landing page."""

    email: Annotated[str, Field(min_length=3, max_length=254, pattern=_EMAIL_PATTERN)]
    # At least one non-whitespace character; the router strips before sending.
    message: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]


class ContactAcceptedDTO(ApiModel):
    """Bare acknowledgement; the submitted text is never echoed back."""

    accepted: bool
