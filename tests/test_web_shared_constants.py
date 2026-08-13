"""Pins the handful of backend constants the TypeScript client re-declares.

Why this exists: there is no shared schema artefact between the Python backend
and the React client, so a number that both sides must agree on is written
twice. That is tolerable only if a drift between the two copies is a red test
rather than a silent product defect.

The defect that prompted it (redesign P4.2) is the case worth reading. The
student's paper-result screen bucketed each mark's confidence against **0.85**,
a threshold its own comment described as "a frontend judgement call made for
this retrofit". The real review floor is
:data:`lemely.core.schemas.REVIEW_CONFIDENCE_THRESHOLD` = 0.90, it is not
operator-tunable, and the teacher portal reports against it directly
(``routers/teacher.py`` counts ``confidence_score >= REVIEW_CONFIDENCE``).

So a mark scoring 0.87 was called *confident* on the student's copy of the
paper and *not confident* on the teacher's copy of the same paper, and the
number shown to the student was the invented one. Nothing in either test suite
could see it, because each side was internally consistent.

Same technique as ``tests/test_design_tokens.py``: a Python test reading a web
source file, because the claim being protected is a cross-artefact one and
Python is where this repo's assertions live.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD

WEB_SRC = Path(__file__).resolve().parents[1] / "web" / "src"


def _read_number(relative: str, name: str) -> float:
    """Read `export const <name> = <number>` out of a TypeScript module."""
    source = (WEB_SRC / relative).read_text(encoding="utf-8")
    match = re.search(rf"^export const {re.escape(name)} = ([0-9.]+)$", source, re.MULTILINE)
    if match is None:
        pytest.fail(
            f"{relative} no longer exports a numeric `{name}`. "
            "If it moved, move this pin with it rather than deleting it."
        )
    return float(match.group(1))


def test_client_confidence_threshold_matches_the_backend() -> None:
    """The student client must bucket confidence at the same floor the backend uses."""
    client_value = _read_number("lib/markingConfidence.ts", "REVIEW_CONFIDENCE_THRESHOLD")
    assert client_value == pytest.approx(REVIEW_CONFIDENCE_THRESHOLD), (
        f"web/src/lib/markingConfidence.ts says {client_value}, "
        f"lemely.core.schemas says {REVIEW_CONFIDENCE_THRESHOLD}. "
        "A mark between the two reads as confident to one reader and uncertain "
        "to the other, on the same paper."
    )


def test_no_other_web_module_invents_its_own_confidence_floor() -> None:
    """One place decides this. A second copy is how the first one drifted."""
    offenders: list[str] = []
    for path in WEB_SRC.rglob("*.ts*"):
        if path.name == "markingConfidence.ts":
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            # A bare numeric comparison against `confidence` is the shape the
            # defect had: `q.confidence < 0.85`.
            if re.search(r"\bconfidence\b\s*[<>]=?\s*0\.\d+", line):
                offenders.append(f"{path.relative_to(WEB_SRC)}:{line_no}: {line.strip()}")
    assert not offenders, "confidence bucketed outside markingConfidence.ts:\n" + "\n".join(
        offenders
    )
