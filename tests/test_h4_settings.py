"""Settings for the accuracy levers H4a and H4c: all off by default, bounded, exclusive."""

import pytest
from pydantic import ValidationError

from lemely.runtime.config import GeminiSettings
from lemely.runtime.example_toml import render_example_toml

H4_NAMES = (
    "adjudication_reread_disagreed",
    "adjudication_reread_max_leaves",
    "correction_retry_median",
    "correction_retry_median_below",
)


def test_h4_defaults() -> None:
    s = GeminiSettings()
    # Sub-project C flipped both levers on (the final rung, FLIP.md).
    assert s.adjudication_reread_disagreed is True
    assert s.adjudication_reread_max_leaves == 3
    assert s.correction_retry_median is True
    assert s.correction_retry_median_below == 0.86


@pytest.mark.parametrize(
    "kwargs",
    [
        {"correction_retry_median_below": 1.2},
        {"correction_retry_median_below": -0.1},
        {"adjudication_reread_max_leaves": -1},
    ],
)
def test_h4_values_are_bounded(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        GeminiSettings(**kwargs)


def test_median_refuses_keep_higher() -> None:
    with pytest.raises(ValidationError, match="correction_retry_median") as err:
        GeminiSettings(correction_retry_median=True, correction_retry_keep_higher=True)
    assert "correction_retry_keep_higher" in str(err.value)
    assert GeminiSettings(correction_retry_median=True).correction_retry_median is True
    # Median is on by default, so keep-higher needs it off.
    kept = GeminiSettings(correction_retry_keep_higher=True, correction_retry_median=False)
    assert kept.correction_retry_keep_higher is True


@pytest.mark.parametrize("name", H4_NAMES)
def test_example_toml_lists_h4_settings(name: str) -> None:
    lines = render_example_toml().splitlines()
    assert any(line.startswith(f"# {name} = ") for line in lines)
