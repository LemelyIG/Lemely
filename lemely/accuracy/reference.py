"""Sub-project C reference set: per-leaf truth for the real scripts, built once and frozen.

Pure file handling: the leaf files under ``BUILD/accuracy-runs/claude-c-reference/``,
the check-first list a human reviews, overrides, and the freeze manifest the real
split checks before any spend. The model calls that fill a reference are in
``scripts/build_reference.py``. Nothing here is committed data: every file it writes
holds student marks and stays under the gitignored BUILD tree.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, get_args

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

REFERENCE_ROOT = (
    Path(__file__).resolve().parents[2] / "BUILD" / "accuracy-runs" / "claude-c-reference"
)
MANIFEST_FILE = "manifest.json"
REFERENCE_FILE = "reference.json"
SCHEME_FILE = "mark_scheme.json"
REVIEW_FILE = "REVIEW.md"
FROZEN_MARKER = "FROZEN"
#: A reference confidence below this puts the leaf on the check-first list (spec P0).
LOW_CONFIDENCE = 0.8

Source = Literal["teacher_tick", "opus", "user_override"]


class ReferenceStateError(RuntimeError):
    """A reference file is frozen, inconsistent, or missing what a step needs."""


@dataclass(frozen=True)
class ReferenceLeaf:
    question_id: str
    mark: int
    max_marks: int
    source: Source
    evidence: str
    note: str = ""

    def __post_init__(self) -> None:
        """Refuse a non-int mark, an unknown source, or a mark outside ``0..max_marks``."""
        for name in ("mark", "max_marks"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{self.question_id}: {name} {value!r} is not an int")
        if self.source not in get_args(Source):
            raise ValueError(f"{self.question_id}: unknown source {self.source!r}")
        if not 0 <= self.mark <= self.max_marks:
            raise ValueError(f"{self.question_id}: mark {self.mark} outside 0..{self.max_marks}")


@dataclass(frozen=True)
class OtherMarks:
    """Another source's marks for the same leaves (Opus, Gemini, Claude), by question id."""

    name: str
    marks: Mapping[str, int]


@dataclass(frozen=True)
class ManifestEntry:
    key: str
    scan_path: str
    scheme_path: str
    reference_path: str
    reference_sha256: str
    scheme_sha256: str
    scan_sha256: str
    source_sha256: Mapping[str, str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_reference(path: Path, leaves: Iterable[ReferenceLeaf]) -> None:
    rows = sorted((asdict(leaf) for leaf in leaves), key=lambda row: row["question_id"])
    ids = [row["question_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question_id in reference")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def read_reference(path: Path) -> dict[str, ReferenceLeaf]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    leaves = [ReferenceLeaf(**row) for row in rows]
    ids = [leaf.question_id for leaf in leaves]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate question_id in {path}")
    return {leaf.question_id: leaf for leaf in leaves}


def reference_total(leaves: Mapping[str, ReferenceLeaf]) -> int:
    return sum(leaf.mark for leaf in leaves.values())


def check_first(
    reference: Mapping[str, ReferenceLeaf],
    *,
    others: Iterable[OtherMarks] = (),
    confidence: Mapping[str, float] | None = None,
    ambiguous: Iterable[str] = (),
    flags: Mapping[str, str] | None = None,
    expected_total: int | None = None,
) -> dict[str, list[str]]:
    """The leaves a human checks first, each with its reasons, in question-id order.

    A leaf is listed when another source's mark differs from the reference, when the
    reference's confidence is below `LOW_CONFIDENCE`, when its tick is ambiguous, or
    when *flags* names it (id to reason, e.g. a leaf the model skipped or over-marked).
    When the reference total misses *expected_total* (the teacher's total), the gap
    sits among the listed leaves; with none listed, among every leaf that could hold
    it (below full marks for a total that is short, above zero for one that is over);
    with none able to, on every leaf. A non-finite confidence counts as low. An
    ambiguous id or another source's id that is not a leaf raises ``ValueError``.
    """
    sources = list(others)
    ambiguous = list(ambiguous)
    flags = dict(flags or {})
    unknown = sorted(
        {q for q in ambiguous if q not in reference}
        | {q for q in flags if q not in reference}
        | {q for o in sources for q in o.marks if q not in reference}
    )
    if unknown:
        raise ValueError(f"not leaves of the reference: {', '.join(unknown)}")
    reasons: dict[str, list[str]] = {qid: [] for qid in reference}
    for qid, leaf in reference.items():
        seen = {o.name: o.marks[qid] for o in sources if qid in o.marks}
        differing = sorted(name for name, mark in seen.items() if mark != leaf.mark)
        if differing:
            reasons[qid].append(
                "disagrees with " + ", ".join(f"{name} ({seen[name]})" for name in differing)
            )
        if confidence is not None and qid in confidence:
            conf = confidence[qid]
            if not math.isfinite(conf) or conf < LOW_CONFIDENCE:
                reasons[qid].append(f"confidence {conf:.2f} below {LOW_CONFIDENCE}")
    for qid in ambiguous:
        reasons[qid].append("ambiguous tick")
    for qid, reason in flags.items():
        reasons[qid].append(reason)
    if expected_total is not None:
        total = reference_total(reference)
        gap = expected_total - total
        if gap:
            suspects = [qid for qid, why in reasons.items() if why] or [
                qid
                for qid, leaf in reference.items()
                if (leaf.mark < leaf.max_marks if gap > 0 else leaf.mark > 0)
            ]
            suspects = suspects or list(reasons)
            side = "below" if gap > 0 else "above"
            for qid in suspects:
                reasons[qid].append(f"total {total} is {abs(gap)} {side} {expected_total}")
    return {qid: why for qid, why in sorted(reasons.items()) if why}


def render_review(
    key: str, reference: Mapping[str, ReferenceLeaf], flagged: Mapping[str, list[str]]
) -> str:
    """``REVIEW.md``: the check-first table, then the total. Holds marks: never committed."""
    lines = [
        f"# Reference review: {key}",
        "",
        f"Total: {reference_total(reference)} of "
        f"{sum(leaf.max_marks for leaf in reference.values())}; "
        f"{len(flagged)} of {len(reference)} leaves to check first.",
        "",
        "| leaf | mark | source | reasons |",
        "|---|---|---|---|",
    ]
    for qid, why in flagged.items():
        leaf = reference[qid]
        lines.append(
            f"| {qid} | {leaf.mark} / {leaf.max_marks} | {leaf.source} | {'; '.join(why)} |"
        )
    return "\n".join(lines) + "\n"


def is_frozen(script_dir: Path) -> bool:
    return (script_dir / FROZEN_MARKER).is_file()


def apply_override(script_dir: Path, question_id: str, mark: int, note: str) -> ReferenceLeaf:
    """Store the user's mark for one leaf as ``user_override``; refused once frozen."""
    if is_frozen(script_dir):
        raise ReferenceStateError(f"{script_dir} is frozen; an override would change it")
    path = script_dir / REFERENCE_FILE
    leaves = read_reference(path)
    if question_id not in leaves:
        raise ReferenceStateError(f"{question_id} is not a leaf of {path}")
    updated = replace(leaves[question_id], mark=mark, source="user_override", note=note)
    leaves[question_id] = updated
    write_reference(path, leaves.values())
    return updated


def read_manifest(path: Path) -> list[ManifestEntry]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ManifestEntry(**entry) for entry in data["scripts"]]


def freeze(
    script_dir: Path,
    *,
    key: str,
    scan_path: Path,
    sources: Mapping[str, Path],
    expected_total: int | None,
    manifest_path: Path,
) -> ManifestEntry:
    """Freeze a reviewed reference: record its digests in the manifest, then mark it frozen.

    Refuses a reference whose total misses *expected_total* (the teacher's total).
    Re-freezing a key replaces its manifest entry.
    """
    reference_path = script_dir / REFERENCE_FILE
    scheme_path = script_dir / SCHEME_FILE
    for needed in (reference_path, scheme_path, scan_path):
        if not needed.is_file():
            raise ReferenceStateError(f"cannot freeze {key}: {needed} is missing")
    total = reference_total(read_reference(reference_path))
    if expected_total is not None and total != expected_total:
        raise ReferenceStateError(f"{key}: reference sums to {total}, not {expected_total}")
    entry = ManifestEntry(
        key=key,
        scan_path=str(scan_path.resolve()),
        scheme_path=str(scheme_path.resolve()),
        reference_path=str(reference_path.resolve()),
        reference_sha256=sha256_file(reference_path),
        scheme_sha256=sha256_file(scheme_path),
        scan_sha256=sha256_file(scan_path),
        source_sha256={name: sha256_file(p) for name, p in sorted(sources.items())},
    )
    entries = [e for e in read_manifest(manifest_path) if e.key != key] + [entry]
    entries.sort(key=lambda e: e.key)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    # Marker first: a crash between the writes leaves a frozen script with no manifest
    # entry (re-freeze fixes it), never an entry for a script that can still be overridden.
    _write_atomic(script_dir / FROZEN_MARKER, entry.reference_sha256 + "\n")
    _write_atomic(
        manifest_path,
        json.dumps({"scripts": [asdict(e) for e in entries]}, indent=1, sort_keys=True) + "\n",
    )
    return entry


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
