"""`python -m lemely.web` must leave `lemely.*` INFO records actually emitted.

P6.10's fresh-clone run found the parent's mock OTP documented in README and
DELIVERY.md §7 as "printed to the backend log" and then absent from
`docker compose logs backend`. The flow itself was fine — the code comes back
as `devCode` — but the log line genuinely did not exist, and the cause was not
specific to the OTP: **no `lemely.*` record below WARNING was emitted by that
process at all.**

uvicorn's default ``LOGGING_CONFIG`` declares handlers for the ``uvicorn*``
loggers and carries no ``root`` entry, so ``dictConfig`` leaves the root logger
handler-less. A plain ``logging.getLogger("lemely.auth.sms").info(...)`` then
propagates to that empty root and falls through to ``logging.lastResort``,
which is pinned at WARNING and drops it. Nothing raises; the record simply
never exists — which is why five phases of green gates never saw it.

The second test here is the regression proper, and it is written so that it
**fails if the fix is removed**: it asserts both that the record survives with
``configure_logging()`` applied and that it is lost without it. Per the P6.2
rule, a test asserting a guarantee has to be shown to fail when the guarantee
is taken away, or it is decoration.
"""

from __future__ import annotations

import io
import logging
import logging.config
from collections.abc import Iterator
from typing import Any

import pytest
from uvicorn.config import LOGGING_CONFIG

from lemely.runtime.logging import configure_logging
from lemely.web.__main__ import main

OTP_MESSAGE = "Mock SMS to +10000000000: your Lemely code is 424242"


@pytest.fixture
def pristine_root_logger() -> Iterator[None]:
    """Save and restore root logging state.

    Both tests reconfigure global logging, which would otherwise leak into
    every test that runs after them in the same process (including pytest's own
    ``caplog``).
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        yield
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)


def _emit_after_uvicorn_config(*, configure: bool) -> str:
    """Replay the container's startup order and return what reached the stream.

    ``configure`` toggles the single line under test, so the same helper serves
    the assertion and its inversion.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)

    stream = io.StringIO()
    if configure:
        # `stream` keeps the record out of the real stderr; the production call
        # in `__main__` takes the default.
        configure_logging(stream=stream)

    # Exactly what `uvicorn.run` does to logging on startup.
    logging.config.dictConfig(LOGGING_CONFIG)

    logging.getLogger("lemely.auth.sms").info(OTP_MESSAGE)
    return stream.getvalue()


def test_lemely_info_is_dropped_without_configure_logging(
    pristine_root_logger: None,
) -> None:
    """The defect itself: uvicorn's log config leaves root with no handler.

    This is the inversion that gives the next test its teeth. If uvicorn ever
    starts configuring a root handler, this test fails and the fix below can be
    reconsidered rather than cargo-culted.
    """
    assert _emit_after_uvicorn_config(configure=False) == ""
    # Root is cleared inside the helper first, so this is a statement about
    # uvicorn's config and not about whatever handlers pytest's own logging
    # plugin has attached to root in this process.
    assert logging.getLogger().handlers == [], (
        "uvicorn's LOGGING_CONFIG now configures a root handler; the reason "
        "`__main__` calls configure_logging() no longer holds as written."
    )


def test_lemely_info_survives_uvicorn_log_config(pristine_root_logger: None) -> None:
    """With `configure_logging()` first, the record is really emitted.

    Ordering matters in both directions and this proves the safe one: our root
    handler is installed before `dictConfig` runs, and `dictConfig` does not
    remove it.
    """
    emitted = _emit_after_uvicorn_config(configure=True)
    assert OTP_MESSAGE in emitted
    assert '"level": "info"' in emitted


def test_main_configures_logging_before_starting_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
    pristine_root_logger: None,
) -> None:
    """`main()` calls `configure_logging()`, and calls it *before* `uvicorn.run`.

    Recorded as an order, not as two independent calls: configuring after
    uvicorn has already applied its dictConfig would still leave the window
    this fixes, and a test that only checked "both were called" would pass on
    the broken ordering.
    """
    calls: list[str] = []

    def fake_configure(**_kwargs: Any) -> None:
        calls.append("configure_logging")

    def fake_run(*_args: Any, **_kwargs: Any) -> None:
        calls.append("uvicorn.run")

    # Patched where `main()` looks them up: `configure_logging` is imported
    # inside the function body, so the binding that matters is the module's.
    monkeypatch.setattr("lemely.runtime.logging.configure_logging", fake_configure)
    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr("sys.argv", ["lemely.web"])

    main()

    assert calls == ["configure_logging", "uvicorn.run"]
