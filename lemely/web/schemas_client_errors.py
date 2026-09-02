"""``POST /api/client-errors`` DTOs — the browser error-report contract.

The React app posts here from its ``ErrorBoundary`` and from its
``window``-level ``error``/``unhandledrejection`` listeners (PR 1's frontend
half), so a client-side crash — including one on the signed-out login screen —
lands somewhere a human can see it. There is no stored row for a report:
``lemely.web.routers.client_errors`` turns an accepted one straight into a
structured ``client_error`` log line for Cloud Logging, so these DTOs
describe the wire contract only, never a persisted shape.

Field caps are a second, independent backstop behind the router's own
HTTP-layer size guard (``_MAX_BODY_BYTES``, 32 KiB): a request that slips past
that check (or is crafted directly, bypassing the browser and its 32 KiB
budget entirely) still cannot make a single log line larger than roughly
about 19 000 characters — see :class:`ClientErrorReportDTO`'s own field comments for
each cap's number.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic needs the real type at runtime
from typing import Annotated, Literal

from pydantic import Field

from lemely.web.schemas import ApiModel

ClientErrorKind = Literal["render", "unhandled", "rejection"]
"""How the browser caught the error: a React ``ErrorBoundary`` (``render``), a
``window.onerror`` handler (``unhandled``), or an ``unhandledrejection``
listener (``rejection``)."""


class ClientErrorReportDTO(ApiModel):
    """One browser-side crash report."""

    message: Annotated[str, Field(min_length=1, max_length=2000)]
    stack: Annotated[str, Field(max_length=8000)] | None = None
    componentStack: Annotated[str, Field(max_length=8000)] | None = None
    """React's component tree at the point of failure — populated only for
    ``kind="render"`` reports (the ``ErrorBoundary``'s own
    ``errorInfo.componentStack``)."""
    route: Annotated[str, Field(max_length=500)]
    """The client-side path the app was showing when it crashed (e.g.
    ``/student/overview``), not a server route — purely descriptive, never
    matched against anything."""
    buildId: Annotated[str, Field(min_length=1, max_length=64)]
    """The frontend build/version the report came from, so a report can be
    correlated with the deploy that shipped the bug."""
    kind: ClientErrorKind
    userAgent: Annotated[str, Field(max_length=500)] | None = None
    occurredAt: datetime | None = None
    """Client-reported wall-clock time of the failure. Advisory only — never
    the ordering key for anything server-side, since the log line's own
    timestamp already is that — useful for a UI that wants to show "how long
    ago"."""


class ClientErrorAcceptedDTO(ApiModel):
    """Response for a successfully-logged report. The body is never echoed back."""

    accepted: bool = True


__all__ = ["ClientErrorAcceptedDTO", "ClientErrorKind", "ClientErrorReportDTO"]
