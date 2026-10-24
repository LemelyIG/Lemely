"""Sub-project C P0: reference files, the check-first list and the freeze manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemely.accuracy import reference as ref
from lemely.accuracy.reference import OtherMarks, ReferenceLeaf, ReferenceStateError


def _leaf(qid: str, mark: int, max_marks: int = 2, source: ref.Source = "opus") -> ReferenceLeaf:
    return ReferenceLeaf(
        question_id=qid, mark=mark, max_marks=max_marks, source=source, evidence="e"
    )


def _script_dir(tmp_path: Path, leaves: list[ReferenceLeaf]) -> Path:
    d = tmp_path / "0625_w24_41"
    ref.write_reference(d / ref.REFERENCE_FILE, leaves)
    (d / ref.SCHEME_FILE).write_text('{"questions": []}', encoding="utf-8")
    return d


def test_mark_outside_range_is_refused() -> None:
    with pytest.raises(ValueError, match=r"outside 0\.\.2"):
        _leaf("1a", 3)


def test_round_trip_and_total(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    ref.write_reference(path, [_leaf("2a", 1), _leaf("1a", 2)])
    loaded = ref.read_reference(path)
    assert list(loaded) == ["1a", "2a"]
    assert ref.reference_total(loaded) == 3


def test_duplicate_leaf_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ref.write_reference(tmp_path / "r.json", [_leaf("1a", 1), _leaf("1a", 2)])


def test_disagreement_low_confidence_and_ambiguous_are_listed() -> None:
    reference = {q.question_id: q for q in (_leaf("1a", 2), _leaf("1b", 1), _leaf("1c", 0))}
    flagged = ref.check_first(
        reference,
        others=[OtherMarks("gemini", {"1a": 2, "1b": 0}), OtherMarks("claude", {"1a": 2})],
        confidence={"1a": 0.95, "1c": 0.6},
        ambiguous=["1a"],
    )
    assert flagged["1b"] == ["disagrees with gemini (0)"]
    assert flagged["1c"] == ["confidence 0.60 below 0.8"]
    assert flagged["1a"] == ["ambiguous tick"]


def test_agreeing_confident_leaf_is_not_listed() -> None:
    reference = {"1a": _leaf("1a", 2)}
    assert ref.check_first(reference, others=[OtherMarks("gemini", {"1a": 2})]) == {}


def test_gap_to_teacher_total_lists_the_disagreeing_leaves() -> None:
    reference = {q.question_id: q for q in (_leaf("1a", 2), _leaf("1b", 0))}
    flagged = ref.check_first(reference, others=[OtherMarks("opus", {"1b": 1})], expected_total=3)
    assert flagged["1b"][-1] == "total 2 is 1 below 3"
    assert "1a" not in flagged


def test_gap_with_no_disagreement_lists_every_leaf_that_could_hold_it() -> None:
    reference = {q.question_id: q for q in (_leaf("1a", 2), _leaf("1b", 0))}
    flagged = ref.check_first(reference, expected_total=3)
    assert list(flagged) == ["1b"]  # 1a is at full marks: it cannot hold a missing tick


def test_review_markdown_lists_reasons_and_total(tmp_path: Path) -> None:
    reference = {"1a": _leaf("1a", 2), "1b": _leaf("1b", 0)}
    text = ref.render_review("k", reference, {"1b": ["disagrees with gemini (1)"]})
    assert "| 1b | 0 / 2 | opus | disagrees with gemini (1) |" in text
    assert "Total: 2" in text


def test_override_is_stored_and_refused_after_freeze(tmp_path: Path) -> None:
    d = _script_dir(tmp_path, [_leaf("1a", 1)])
    leaf = ref.apply_override(d, "1a", 2, "teacher ticked twice")
    assert leaf.source == "user_override" and leaf.mark == 2
    assert ref.read_reference(d / ref.REFERENCE_FILE)["1a"].note == "teacher ticked twice"
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF-1")
    ref.freeze(
        d,
        key="k",
        scan_path=scan,
        sources={},
        expected_total=None,
        manifest_path=tmp_path / ref.MANIFEST_FILE,
    )
    with pytest.raises(ReferenceStateError, match="frozen"):
        ref.apply_override(d, "1a", 1, "no")


def test_override_of_unknown_leaf_is_refused(tmp_path: Path) -> None:
    d = _script_dir(tmp_path, [_leaf("1a", 1)])
    with pytest.raises(ReferenceStateError, match="9z"):
        ref.apply_override(d, "9z", 1, "")


def test_freeze_writes_manifest_with_digests(tmp_path: Path) -> None:
    d = _script_dir(tmp_path, [_leaf("1a", 2), _leaf("1b", 1)])
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF-1 scan")
    copy = tmp_path / "corrected.pdf"
    copy.write_bytes(b"%PDF-1 ticks")
    manifest = tmp_path / ref.MANIFEST_FILE
    entry = ref.freeze(
        d,
        key="0625_w24_41",
        scan_path=scan,
        sources={"corrected_copy": copy},
        expected_total=3,
        manifest_path=manifest,
    )
    assert entry.reference_sha256 == ref.sha256_file(d / ref.REFERENCE_FILE)
    assert entry.scan_sha256 == ref.sha256_file(scan)
    assert entry.source_sha256 == {"corrected_copy": ref.sha256_file(copy)}
    assert ref.is_frozen(d)
    (loaded,) = ref.read_manifest(manifest)
    assert loaded == entry


def test_freeze_refuses_a_total_that_misses_the_teacher_total(tmp_path: Path) -> None:
    d = _script_dir(tmp_path, [_leaf("1a", 2)])
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"x")
    with pytest.raises(ReferenceStateError, match="sums to 2, not 66"):
        ref.freeze(
            d,
            key="k",
            scan_path=scan,
            sources={},
            expected_total=66,
            manifest_path=tmp_path / ref.MANIFEST_FILE,
        )
    assert not ref.is_frozen(d)


def test_refreeze_replaces_the_manifest_entry(tmp_path: Path) -> None:
    manifest = tmp_path / ref.MANIFEST_FILE
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"x")
    for key in ("a", "b"):
        d = tmp_path / key
        ref.write_reference(d / ref.REFERENCE_FILE, [_leaf("1a", 1)])
        (d / ref.SCHEME_FILE).write_text("{}", encoding="utf-8")
        ref.freeze(
            d, key=key, scan_path=scan, sources={}, expected_total=None, manifest_path=manifest
        )
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert [e["key"] for e in data["scripts"]] == ["a", "b"]
