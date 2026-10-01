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

from lemely.core.schemas import (
    REVIEW_CONFIDENCE_THRESHOLD,
    UNSCORED_MARKER_SOURCES,
    CorrectedQuestion,
)
from lemely.db.models.enums import MarkerSource
from lemely.web.schemas import MarkerSource as WireMarkerSource

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


#: Functions whose body is allowed to compare a bare number against a
#: confidence-like value. Exactly one entry, and adding a second is the thing
#: this test exists to make someone argue for.
_CONFIDENCE_OWNER = "markingConfidence.ts"

#: Identifiers that hold a confidence value under another name.
#:
#: P4.5 added this list, because the original regex below was defeated in the
#: most ordinary way possible: ``Review.tsx`` bucketed with
#: ``confidenceTone(score)`` and compared ``score >= 0.8``, so the word
#: ``confidence`` never appeared beside the operator and the gate saw nothing.
#: The teacher's review queue — the screen that exists *because* a mark fell
#: below 0.90 — was therefore painting marks at 0.85 in the same green it uses
#: for marks it is sure about.
#:
#: This is ``BUILD/DECISIONS.md`` D6.12's lesson in miniature: a condition
#: every harness shares is a condition no harness tests. Here the shared
#: condition was an assumption about *naming* — that a variable holding a
#: confidence would be called one.
_CONFIDENCE_ALIASES = ("confidence", "confidenceScore", "score", "conf", "certainty")


def test_no_other_web_module_invents_its_own_confidence_floor() -> None:
    """One place decides this. A second copy is how the first one drifted."""
    # A bare numeric comparison against a confidence-like identifier is the
    # shape the defect had, in both its instances: `q.confidence < 0.85` and
    # `score >= 0.8`.
    pattern = re.compile(
        r"\b(?:" + "|".join(_CONFIDENCE_ALIASES) + r")\b\s*[<>]=?\s*0\.\d+",
    )
    offenders: list[str] = []
    for path in WEB_SRC.rglob("*.ts*"):
        if path.name == _CONFIDENCE_OWNER:
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            # Comments explain the thresholds; several of these files quote the
            # old comparison in the note recording why it was removed, and a
            # gate that fails on its own fix note is the trap
            # `utilityExistence.test.ts` already documents.
            if stripped.startswith(("*", "//", "/*")):
                continue
            if pattern.search(line):
                offenders.append(f"{path.relative_to(WEB_SRC)}:{line_no}: {stripped}")
    assert not offenders, "confidence bucketed outside markingConfidence.ts:\n" + "\n".join(
        offenders
    )


def test_the_confidence_floor_gate_catches_a_renamed_variable() -> None:
    """Inversion, so the widened gate is known to fail on the real string.

    The exact line that shipped in ``Review.tsx`` and that the previous
    regex could not see.
    """
    pattern = re.compile(
        r"\b(?:" + "|".join(_CONFIDENCE_ALIASES) + r")\b\s*[<>]=?\s*0\.\d+",
    )
    assert pattern.search('  if (score >= 0.8) return "ok"')
    assert pattern.search("  if (q.confidence < 0.85) return 'uncertain'")
    assert pattern.search("  const ok = conf > 0.9")
    # And does not fire on things that merely contain a number.
    assert not pattern.search("  const width = size >= 0.8 ? 'wide' : 'narrow'")


# ── The one formulation of "did a marker score this question?" (task #36) ─────
#
# The frontend copy of `UNSCORED_MARKER_SOURCES` is the same cross-language
# duplication `REVIEW_CONFIDENCE_THRESHOLD` above is, pinned the same way and
# for a sharper reason: that set is the answer to a question eight sites used to
# answer independently, and the ninth consumer found was a grading-AUTHORITY
# gate (`attempt_repo.is_marking_low_confidence`).


def _ts_string_set(relative: str, name: str) -> set[str]:
    """Read `export const <name>: ... = new Set([...])` out of a TypeScript module."""
    source = (WEB_SRC / relative).read_text(encoding="utf-8")
    match = re.search(
        rf"^export const {re.escape(name)}[^=]*= new Set\(\[(.*?)\]\)",
        source,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        pytest.fail(
            f"{relative} no longer exports a `new Set` named `{name}`. "
            "If it moved, move this pin with it rather than deleting it."
        )
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _ts_union(relative: str, name: str) -> set[str]:
    """Read `export type <name> = "a" | "b" | ...` out of a TypeScript module."""
    source = (WEB_SRC / relative).read_text(encoding="utf-8")
    match = re.search(rf"^export type {re.escape(name)} = (.+)$", source, re.MULTILINE)
    if match is None:
        pytest.fail(f"{relative} no longer exports a `type {name}` union.")
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_client_unscored_marker_sources_match_the_backend() -> None:
    """Both sides must agree on which marker sources mean "nobody looked"."""
    client = _ts_string_set("lib/markingConfidence.ts", "UNSCORED_MARKER_SOURCES")
    assert client == set(UNSCORED_MARKER_SOURCES), (
        f"web/src/lib/markingConfidence.ts says {sorted(client)}, "
        f"lemely.core.schemas says {sorted(UNSCORED_MARKER_SOURCES)}. "
        "A value in one set and not the other renders a question no marker read "
        "as a confident or uncertain mark on whichever side is missing it."
    )


def test_every_layer_declares_the_same_marker_source_values() -> None:
    """Four declarations of one vocabulary: core, the DB enum, the wire, the client.

    Task #36 added ``"blank"`` to all four. A migration that adds a sixth member
    to the DB enum without widening the others makes
    ``routers/practice._marker_source`` raise on a real row; this pins that from
    the other side, before a row exists to trip over.
    """
    annotation = CorrectedQuestion.model_fields["marker_source"].annotation
    core = set(annotation.__args__)  # type: ignore[union-attr]
    db = {member.value for member in MarkerSource}
    wire = set(WireMarkerSource.__args__)  # type: ignore[attr-defined]
    client = _ts_union("lib/types.ts", "MarkerSource")
    assert core == db == wire == client, (
        f"core={sorted(core)} db={sorted(db)} wire={sorted(wire)} client={sorted(client)}"
    )


def test_the_unscored_values_are_a_subset_of_the_vocabulary() -> None:
    """A typo in the set would silently make a real value scored again."""
    assert set(UNSCORED_MARKER_SOURCES) <= {member.value for member in MarkerSource}


#: Every web module may ASK whether a question was scored; only
#: `markingConfidence.ts` may say what the answer is made of.
_MARKER_SOURCE_OWNER = "markingConfidence.ts"

#: Identifiers that hold a marker source under some name.
_MARKER_SOURCE_ALIASES = ("markerSource", "marker_source", "source", "msrc")

#: `markerSource === "missing" || markerSource === "dropped"` — the shape that
#: shipped twice (here and in `Review.tsx`) and that would have silently
#: excluded `"blank"` in both. Both call `markerScored` now.
_UNSCORED_SPELLING = re.compile(
    r"\b(?:" + "|".join(_MARKER_SOURCE_ALIASES) + r")\b\s*[=!]==?\s*"
    r'"(?:missing|dropped|blank)"'
)


def test_no_other_web_module_spells_out_the_unscored_marker_set() -> None:
    """One place decides this, because two places is how nine consumers happened."""
    offenders: list[str] = []
    for path in WEB_SRC.rglob("*.ts*"):
        if path.name == _MARKER_SOURCE_OWNER:
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            # Comments record the removed spelling; a gate that fails on its own
            # fix note is the trap `utilityExistence.test.ts` documents.
            if stripped.startswith(("*", "//", "/*")):
                continue
            if _UNSCORED_SPELLING.search(line):
                offenders.append(f"{path.relative_to(WEB_SRC)}:{line_no}: {stripped}")
    assert not offenders, (
        "the unscored-marker-source set is spelled out outside "
        f"{_MARKER_SOURCE_OWNER} — call `markerScored` instead:\n" + "\n".join(offenders)
    )


def test_the_unscored_marker_gate_catches_the_spelling_it_replaced() -> None:
    """Inversion, so the gate is known to fire on the real removed lines."""
    assert _UNSCORED_SPELLING.search(
        '    (q.markerSource === "missing" || q.markerSource === "dropped")'
    )
    assert _UNSCORED_SPELLING.search(
        '  if (markerSource === "missing" || markerSource === "dropped") return "neutral"'
    )
    assert _UNSCORED_SPELLING.search('  return source === "blank" ? "not marked" : source')
    # And does not fire on an unrelated string comparison.
    assert not _UNSCORED_SPELLING.search('  if (kind === "graded") return "ok"')
