"""Settings for the Haiku accuracy levers H2a-H2d: all off by default, bounded, exclusive."""

import pytest
from pydantic import ValidationError

from lemely.runtime.config import GeminiSettings
from lemely.runtime.example_toml import render_example_toml

H2_NAMES = (
    "correction_retry_keep_higher",
    "correction_retry_keep_higher_below",
    "correction_reason_first",
    "correction_syllabus_conventions",
    "adjudication_drawing_leaves",
    "adjudication_drawing_max_leaves",
)


def test_h2_defaults_are_off() -> None:
    s = GeminiSettings()
    assert s.correction_retry_keep_higher is False
    assert s.correction_retry_keep_higher_below == 0.86
    assert s.correction_reason_first is False
    assert s.correction_syllabus_conventions is False
    assert s.adjudication_drawing_leaves is False
    assert s.adjudication_drawing_max_leaves == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"correction_retry_keep_higher_below": 1.2},
        {"correction_retry_keep_higher_below": -0.1},
        {"adjudication_drawing_max_leaves": -1},
    ],
)
def test_h2_values_are_bounded(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        GeminiSettings(**kwargs)


def test_reason_first_refuses_citations() -> None:
    with pytest.raises(ValidationError, match="correction_reason_first") as err:
        GeminiSettings(correction_reason_first=True, correction_citations=True)
    assert "correction_citations" in str(err.value)
    assert GeminiSettings(correction_reason_first=True).correction_reason_first is True
    assert GeminiSettings(correction_citations=True).correction_citations is True


@pytest.mark.parametrize("name", H2_NAMES)
def test_example_toml_lists_h2_settings(name: str) -> None:
    lines = render_example_toml().splitlines()
    assert any(line.startswith(f"# {name} = ") for line in lines)
