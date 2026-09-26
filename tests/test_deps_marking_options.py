"""``get_quiz_marking_service`` must wire the configured marking flags.

The AST guard (``tests/test_marking_options_wiring.py``) only looks at calls
to ``correct_paper``, ``hybrid_correct_paper`` and ``grade_paper`` -- it does
not look at the ``QuizMarkingService(...)`` construction in
``lemely.web.deps``. Every quiz test in ``tests/test_quiz_marking_repo.py``
builds its own ``QuizMarkingService`` directly and passes ``MarkingOptions``
explicitly, so none of them exercises ``get_quiz_marking_service``'s own
``marking_options=settings.grading.marking_options()`` line
(``lemely/web/deps.py``). Deleting that line would leave every other test
green. This test is the one thing that exercises that link.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import lemely.web.deps as deps
from lemely.runtime.config import MarkingOptions


def test_quiz_marking_service_wires_configured_marking_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMELY_GRADING__EQUIVALENCE_GATE", "true")
    monkeypatch.setenv("LEMELY_GRADING__ECF_SUBSTITUTION", "true")
    deps.reset_singletons()
    try:
        # Scoped so these three singletons are un-patched again before the
        # final `reset_singletons()` below tries to `.cache_clear()` them --
        # an `lru_cache`d function replaced by a plain lambda has no
        # `cache_clear`.
        with monkeypatch.context() as m:
            m.setattr(deps, "get_sessionmaker", lambda _settings: MagicMock())
            m.setattr(deps, "get_attempt_repo", lambda: MagicMock())
            m.setattr(deps, "get_gemini_client", lambda: MagicMock())
            service = deps.get_quiz_marking_service()
            assert service._marking_options == MarkingOptions(
                equivalence_gate=True, ecf_substitution=True
            )
    finally:
        deps.reset_singletons()
