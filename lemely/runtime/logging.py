"""structlog configuration: stderr-only, TTY-auto JSON vs console, secret redaction."""
from __future__ import annotations

import logging
import sys
from typing import IO, Any, Literal

import structlog

_SECRET_KEYS = frozenset(
    {"api_key", "gemini_api_key", "password", "token", "authorization"}
)


def _redact(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: ("***" if k.lower() in _SECRET_KEYS else walk(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(event_dict)  # type: ignore[return-value]


def configure_logging(
    *,
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO",
    fmt: Literal["auto", "json", "console"] = "auto",
    stream: IO[str] | None = None,
) -> None:
    """Configure structlog + stdlib logging once at process startup.

    Logs to stderr unless `stream` is given (used in tests).
    """
    out = stream if stream is not None else sys.stderr
    use_console = fmt == "console" or (fmt == "auto" and out.isatty())

    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer(colors=use_console)
        if use_console
        else structlog.processors.JSONRenderer()
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact,
    ]

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=out),
        cache_logger_on_first_use=True,
    )

    # Stdlib bridge: route any logging.getLogger(...) into structlog.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    class _StructlogBridge(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            structlog.get_logger(record.name).log(
                record.levelno, record.getMessage()
            )

    root.addHandler(_StructlogBridge(level=getattr(logging, level)))
    root.setLevel(getattr(logging, level))
