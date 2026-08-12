"""Uvicorn runner for the Lemely web backend.

Usage::

    python -m lemely.web            # serve on 127.0.0.1:8000
    python -m lemely.web --reload   # dev auto-reload

Host / port default to localhost and 8000 and can be overridden by the
``LEMELY_WEB_HOST`` / ``LEMELY_WEB_PORT`` environment variables.
"""

from __future__ import annotations

import argparse
import os


def main() -> None:
    """Parse CLI args and launch the FastAPI app via uvicorn."""
    import uvicorn

    parser = argparse.ArgumentParser(prog="lemely.web", description="Run the Lemely API server.")
    parser.add_argument(
        "--host",
        default=os.environ.get("LEMELY_WEB_HOST", "127.0.0.1"),
        help="Bind host (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("LEMELY_WEB_PORT", "8000")),
        help="Bind port (default: 8000).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development.",
    )
    args = parser.parse_args()

    # P6.10-followup. Without this, **no `lemely.*` log record below WARNING is
    # emitted by this process at all** — which is how the parent's mock OTP came
    # to be documented as "printed to the backend log" and then not appear in
    # `docker compose logs backend` on the fresh-clone run.
    #
    # The chain: uvicorn's default `LOGGING_CONFIG` declares handlers for the
    # `uvicorn*` loggers only and carries no `root` entry, so `dictConfig` leaves
    # the root logger untouched — handler-less. A bare `logging.getLogger(
    # "lemely.auth.sms").info(...)` then propagates to a root with no handler and
    # falls through to `logging.lastResort`, which is fixed at WARNING and drops
    # it silently. Nothing errors; the record simply never exists.
    #
    # `configure_logging()` installs the structlog bridge on root, so it has to
    # run *before* `uvicorn.run` applies its dictConfig. That ordering is safe in
    # both directions: dictConfig will not remove our root handler (no `root`
    # key), and uvicorn's own loggers set `propagate: False`, so its access log
    # is not duplicated through the bridge.
    #
    # This is the container's entry point (`docker-entrypoint.sh` runs
    # `python -m lemely.web`), so the fix lands exactly where the gap was
    # observed. It is deliberately *not* in `create_app()`: that factory is also
    # imported by the test suite and `scripts/e2e_server.py`, and reconfiguring
    # global logging as a side effect of building the app would reach into
    # processes that never asked for it.
    from lemely.runtime.logging import configure_logging

    configure_logging()

    uvicorn.run(
        "lemely.web.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
