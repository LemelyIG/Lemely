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

    uvicorn.run(
        "lemely.web.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
