"""ntfy push delivery for Lemely runtime notifications.

Used to surface budget-guard events (Gemini spend warnings / ceiling breach)
during unattended runs. Delivery is best-effort: the topic is read from the
``LEMELY_NTFY_TOPIC`` environment variable and network failures are swallowed
and logged, never raised into callers.

Import-linter contract: ``lemely.runtime`` must not depend on ``core``/``io``/
``app``. This module uses only the standard library plus structlog.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

import structlog

_NTFY_BASE = "http://home-server"
_TIMEOUT_SECONDS = 5.0


def post_ntfy(message: str, *, title: str = "Lemely", priority: str | None = None) -> bool:
    """Post a message to the configured ntfy topic.

    The topic is read from the ``LEMELY_NTFY_TOPIC`` environment variable. When
    unset (or empty) this is a no-op that returns ``False`` — ntfy is opt-in.

    Network and encoding errors are caught and logged; this function never
    raises into the caller.

    Args:
        message: The notification body.
        title: The notification title (ntfy ``Title`` header).
        priority: Optional ntfy priority (e.g. ``"high"``); omitted when ``None``.

    Returns:
        ``True`` if the message was posted successfully, ``False`` otherwise
        (topic unset or delivery failed).
    """
    log = structlog.get_logger().bind(component="notify")
    topic = os.environ.get("LEMELY_NTFY_TOPIC")
    if not topic:
        return False

    url = f"{_NTFY_BASE}/{topic}"
    headers = {"Title": title}
    if priority is not None:
        headers["Priority"] = priority

    try:
        request = urllib.request.Request(  # noqa: S310  # scheme fixed to https above
            url,
            data=message.encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS):  # noqa: S310
            pass
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("ntfy_post_failed", topic=topic, error=str(exc))
        return False
    return True
