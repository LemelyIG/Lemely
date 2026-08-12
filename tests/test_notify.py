"""Unit tests for lemely.runtime.notify and budget_notify wiring."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from lemely.runtime import budget_notify, notify


class _NoTopicEnv:
    """Context manager that removes LEMELY_NTFY_TOPIC for the duration."""

    def __enter__(self) -> _NoTopicEnv:
        import os

        self._snap = os.environ.pop("LEMELY_NTFY_TOPIC", None)
        return self

    def __exit__(self, *_: object) -> None:
        import os

        if self._snap is not None:
            os.environ["LEMELY_NTFY_TOPIC"] = self._snap


class PostNtfyTests(unittest.TestCase):
    def test_no_topic_is_noop(self) -> None:
        with _NoTopicEnv():
            self.assertFalse(notify.post_ntfy("hello"))

    def test_posts_to_correct_url(self) -> None:
        opened: dict[str, Any] = {}

        def _fake_urlopen(request: Any, timeout: float = 0) -> Any:
            opened["url"] = request.full_url
            opened["data"] = request.data
            opened["headers"] = request.headers
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=cm)
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        with (
            patch.dict("os.environ", {"LEMELY_NTFY_TOPIC": "my-topic"}),
            patch("urllib.request.urlopen", side_effect=_fake_urlopen),
        ):
            ok = notify.post_ntfy("body text", title="T", priority="high")

        self.assertTrue(ok)
        self.assertEqual(opened["url"], "http://home-server/my-topic")
        self.assertEqual(opened["data"], b"body text")
        # urllib title-cases header keys.
        self.assertEqual(opened["headers"].get("Title"), "T")
        self.assertEqual(opened["headers"].get("Priority"), "high")

    def test_network_error_swallowed(self) -> None:
        with (
            patch.dict("os.environ", {"LEMELY_NTFY_TOPIC": "my-topic"}),
            patch("urllib.request.urlopen", side_effect=OSError("boom")),
        ):
            self.assertFalse(notify.post_ntfy("body"))


class BudgetNotifyTests(unittest.TestCase):
    def test_register_is_idempotent(self) -> None:
        # Reset module state so the test is deterministic regardless of import order.
        budget_notify._registered = False
        with patch.object(budget_notify.bus, "subscribe") as sub:
            budget_notify.register_budget_ntfy()
            budget_notify.register_budget_ntfy()
            budget_notify.register_budget_ntfy()
        # Two subscriptions (warning + exceeded), registered once total.
        self.assertEqual(sub.call_count, 2)

    def test_warning_handler_posts_ntfy(self) -> None:
        with patch.object(budget_notify, "post_ntfy") as post:
            budget_notify._on_budget_warning(threshold=4.0, total_usd=4.5, ceiling=8.0)
        post.assert_called_once()
        msg = post.call_args.args[0]
        self.assertIn("$4.50", msg)
        self.assertIn("$8.00", msg)

    def test_exceeded_handler_posts_high_priority(self) -> None:
        with patch.object(budget_notify, "post_ntfy") as post:
            budget_notify._on_budget_exceeded(total_usd=8.5, ceiling=8.0)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs.get("priority"), "high")


if __name__ == "__main__":
    unittest.main()
