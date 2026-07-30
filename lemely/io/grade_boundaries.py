"""CAIE grade boundary resolver — bundled static JSON, no network calls."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from lemely.data import DATA_DIR

if TYPE_CHECKING:
    from pathlib import Path

    from lemely.core.schemas import ExamMetadata

_BOUNDARIES_PATH = DATA_DIR / "grade_boundaries.json"

# Maps ExamMetadata.session_month values to the short session code used in boundary keys.
_SESSION_CODE: dict[str, str] = {
    "May/June": "m",
    "Oct/Nov": "w",
    "Feb/Mar": "s",
    "Specimen": "sp",
}

BoundarySource = Literal["exact", "subject_default", "global_default"]


def _make_key(metadata: ExamMetadata) -> str | None:
    """Derive the exact boundary lookup key from ExamMetadata.

    Returns None when session_year is None (caller skips exact lookup).
    Specimen papers have no real session boundaries; they always return None.

    Example: subject_code='0625', session_month='May/June', session_year=2020,
             paper_number=1, paper_variant=2 → '0625_m20_p12'
    """
    if metadata.session_year is None:
        return None
    if metadata.session_month == "Specimen":
        return None
    code = _SESSION_CODE[metadata.session_month]
    year_suffix = str(metadata.session_year)[-2:]
    return (
        f"{metadata.subject_code}_{code}{year_suffix}"
        f"_p{metadata.paper_number}{metadata.paper_variant}"
    )


def raw_to_percentage(raw: dict[str, int | float], max_mark: int | float) -> dict[str, float]:
    """Convert raw mark thresholds to percentages.

    Args:
        raw: Grade → raw mark threshold mapping.
        max_mark: Maximum marks for the paper.

    Returns:
        Grade → percentage threshold mapping.

    Raises:
        ValueError: When max_mark <= 0.
    """
    if max_mark <= 0:
        raise ValueError(f"max_mark must be positive, got {max_mark}")
    return {grade: (mark / max_mark) * 100.0 for grade, mark in raw.items()}


class GradeBoundaryStore:
    """Resolver for CAIE grade boundaries from bundled static JSON.

    Fallback chain: exact key → subject default → global default.
    source_tag vocabulary matches GradePrediction.boundary_source Literal values.
    """

    def __init__(self, data_path: Path | None = None) -> None:
        path = data_path or _BOUNDARIES_PATH
        data = json.loads(path.read_text(encoding="utf-8"))
        self._exact: dict[str, dict[str, float]] = {
            k: v for k, v in data.items() if not k.startswith("_")
        }
        self._defaults: dict[str, dict[str, float]] = data.get("_defaults", {})
        self._global: dict[str, float] = data.get(
            "_global",
            {
                "A": 80.0,
                "B": 70.0,
                "C": 60.0,
                "D": 50.0,
                "E": 40.0,
            },
        )

    def resolve(self, metadata: ExamMetadata) -> tuple[dict[str, float], BoundarySource]:
        """Return (boundary_map, source_tag) using the fallback chain.

        source_tag is one of: 'exact', 'subject_default', 'global_default'.
        """
        key = _make_key(metadata)
        if key and key in self._exact:
            return self._exact[key], "exact"

        subject = metadata.subject_code
        if subject in self._defaults:
            return self._defaults[subject], "subject_default"

        return self._global, "global_default"
