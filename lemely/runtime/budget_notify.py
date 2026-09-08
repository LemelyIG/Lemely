"""Wire budget-guard events to ntfy delivery.

Subscribes to :data:`lemely.runtime.events.bus` so that ``BUDGET_WARNING`` and
``BUDGET_EXCEEDED`` events (published by the Gemini client when the persistent
cost ledger crosses a threshold) are delivered as ntfy push notifications.

:func:`register_budget_ntfy` is idempotent, so repeated calls register the
subscription exactly once.

The CLI is now its only caller. The web app used to register it too, but its
Gemini client is built with ``ledger=None`` (DS3), so it publishes no
``BUDGET_*`` events at all and there is nothing for a subscription to hear —
the cap is enforced by a GCP billing budget on the deployed service rather
than by this process counting its own spend.

Import-linter contract: ``lemely.runtime`` must not depend on ``core``/``io``/
``app``. This module uses only stdlib, structlog, and sibling ``runtime``
modules (``events``, ``notify``).
"""

from __future__ import annotations

import threading
from typing import Any

from lemely.runtime.events import EventType, bus
from lemely.runtime.notify import post_ntfy

_registered = False
_lock = threading.Lock()


def _as_float(value: Any) -> float:  # noqa: ANN401
    """Coerce an event payload value to float, treating ``None`` as ``0.0``."""
    return float(value) if value is not None else 0.0


def _on_budget_warning(**payload: Any) -> None:  # noqa: ANN401
    """Handle a BUDGET_WARNING event by posting an ntfy notification."""
    total = _as_float(payload.get("total_usd"))
    ceiling = _as_float(payload.get("ceiling"))
    post_ntfy(
        f"Gemini budget warning: ${total:.2f} of ${ceiling:.2f} ceiling reached",
        title="Lemely budget",
    )


def _on_budget_exceeded(**payload: Any) -> None:  # noqa: ANN401
    """Handle a BUDGET_EXCEEDED event by posting a high-priority ntfy notification."""
    total = _as_float(payload.get("total_usd"))
    ceiling = _as_float(payload.get("ceiling"))
    post_ntfy(
        f"Gemini budget EXCEEDED: ${total:.2f} of ${ceiling:.2f} ceiling reached",
        title="Lemely budget",
        priority="high",
    )


def register_budget_ntfy() -> None:
    """Subscribe the budget-event ntfy handlers to the bus, exactly once.

    Idempotent and thread-safe: repeated calls (e.g. across multiple ``launch``
    invocations) register the subscription only on the first call. See the
    module docstring for why the CLI is the only entrypoint that calls this.
    """
    global _registered
    with _lock:
        if _registered:
            return
        bus.subscribe(EventType.BUDGET_WARNING, _on_budget_warning)
        bus.subscribe(EventType.BUDGET_EXCEEDED, _on_budget_exceeded)
        _registered = True
