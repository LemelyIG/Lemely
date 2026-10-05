"""Behaviour-preservation tests for the shared text-agreement function (#264).

``reread`` and ``second_read`` used to each carry a copy of the same difflib
stand-in. These tests pin that they now share one function and that its
ratios are unchanged.
"""

from __future__ import annotations

import pytest

from lemely.io.second_read import text_agreement as second_read_text_agreement


def test_module_imports() -> None:
    from lemely.core.text_agreement import text_agreement

    assert callable(text_agreement)


def test_reread_and_second_read_share_one_function() -> None:
    from lemely.core.text_agreement import text_agreement
    from lemely.io import reread, second_read

    assert reread.text_agreement is second_read.text_agreement
    assert reread.text_agreement is text_agreement


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("A", " a ", 1.0),
        ("42 m/s", "42 m/s", 1.0),
        ("  42 M/S ", "42 m/s", 1.0),
        ("B", "D", 0.0),
        ("0.5", "1/2", 0.0),
        ("gravity acts on it", "gravity acts", 0.8),
        ("42 m/s", "42 ms", 0.909091),
        ("2.4 x 10^4 J", "2.4x10^4J", 0.857143),
    ],
)
def test_ratio_table_is_unchanged(a: str, b: str, expected: float) -> None:
    assert second_read_text_agreement(a, b) == pytest.approx(expected, abs=5e-7)
