"""Tests for Phase 2: HistoryStore persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from lemely.core.history import HISTORY_SCHEMA_VERSION, PaperRecord, StudentHistory
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.io.history_store import HistoryStore
from lemely.runtime.errors import ParseError

if TYPE_CHECKING:
    from pathlib import Path


def _make_record(student_id: str = "alice", grade: str = "B") -> PaperRecord:
    return PaperRecord(
        student_id=student_id,
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        awarded_marks=65,
        maximum_marks=80,
        percentage=81.25,
        grade=grade,
        weak_areas=[
            WeakArea(
                topic="Waves",
                lost_marks=5,
                maximum_marks=10,
                accuracy=0.5,
                question_ids=["3a"],
            )
        ],
        recorded_at=datetime.now(UTC).isoformat(),
    )


class TestHistoryStore:
    def test_load_unknown_student_returns_empty(self, tmp_path: Path) -> None:
        store = HistoryStore(tmp_path / "history")
        history = store.load("nobody")
        assert isinstance(history, StudentHistory)
        assert history.records == []

    def test_append_then_load_roundtrip(self, tmp_path: Path) -> None:
        store = HistoryStore(tmp_path / "history")
        record = _make_record()
        store.append("alice", record)
        history = store.load("alice")
        assert len(history.records) == 1
        assert history.records[0].grade == "B"
        assert history.records[0].weak_areas[0].topic == "Waves"

    def test_two_appends_accumulate(self, tmp_path: Path) -> None:
        store = HistoryStore(tmp_path / "history")
        store.append("alice", _make_record(grade="B"))
        store.append("alice", _make_record(grade="A"))
        history = store.load("alice")
        assert len(history.records) == 2
        grades = {r.grade for r in history.records}
        assert grades == {"A", "B"}

    def test_list_students(self, tmp_path: Path) -> None:
        store = HistoryStore(tmp_path / "history")
        store.append("alice", _make_record("alice"))
        store.append("bob", _make_record("bob"))
        students = store.list_students()
        assert "alice" in students
        assert "bob" in students

    def test_file_created_atomically(self, tmp_path: Path) -> None:
        store = HistoryStore(tmp_path / "history")
        store.append("charlie", _make_record("charlie"))
        path = tmp_path / "history" / "charlie.json"
        assert path.exists()
        # No temp files should remain
        tmp_files = list((tmp_path / "history").glob(".charlie_*"))
        assert tmp_files == []

    def test_written_file_carries_schema_version(self, tmp_path: Path) -> None:
        store = HistoryStore(tmp_path / "history")
        store.append("alice", _make_record())
        data = json.loads((tmp_path / "history" / "alice.json").read_text(encoding="utf-8"))
        assert data["schema_version"] == HISTORY_SCHEMA_VERSION

    def test_corrupt_json_surfaces_not_silently_empty(self, tmp_path: Path) -> None:
        store = HistoryStore(tmp_path / "history")
        (tmp_path / "history" / "alice.json").write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ParseError, match="invalid JSON"):
            store.load("alice")

    def test_schema_mismatch_surfaces(self, tmp_path: Path) -> None:
        store = HistoryStore(tmp_path / "history")
        # Valid JSON, wrong shape (records must be a list of PaperRecord).
        (tmp_path / "history" / "alice.json").write_text(
            json.dumps({"student_id": "alice", "records": "not-a-list"}), encoding="utf-8"
        )
        with pytest.raises(ParseError, match="schema mismatch"):
            store.load("alice")

    def test_future_schema_version_refused(self, tmp_path: Path) -> None:
        store = HistoryStore(tmp_path / "history")
        (tmp_path / "history" / "alice.json").write_text(
            json.dumps(
                {"schema_version": HISTORY_SCHEMA_VERSION + 1, "student_id": "alice", "records": []}
            ),
            encoding="utf-8",
        )
        with pytest.raises(ParseError, match="unsupported schema_version"):
            store.load("alice")

    @pytest.mark.parametrize(
        "bad_key",
        ["../secrets", "a/b", "a\\b", "", ".", "..", "with\x00nul"],
    )
    def test_unsafe_student_id_rejected(self, tmp_path: Path, bad_key: str) -> None:
        # A student_id becomes a filename ({root}/{id}.json). Some callers pass a
        # request-supplied id, so a path separator / dot-segment / NUL byte could
        # escape the store root. Every access path must reject it, not traverse.
        store = HistoryStore(tmp_path / "history")
        with pytest.raises(ValueError, match="Unsafe history store key"):
            store.load(bad_key)
        with pytest.raises(ValueError, match="Unsafe history store key"):
            store.append(bad_key, _make_record())

    def test_safe_student_id_with_dots_and_at_is_allowed(self, tmp_path: Path) -> None:
        # A single-segment id that merely *contains* dots (e.g. an email-shaped id)
        # is fine — only path separators and the bare "."/".." segments are unsafe.
        store = HistoryStore(tmp_path / "history")
        store.append("a.user@example.com", _make_record("a.user@example.com"))
        assert (tmp_path / "history" / "a.user@example.com.json").exists()

    def test_pre_versioning_file_loads_as_v1(self, tmp_path: Path) -> None:
        # Files written before schema_version existed must still load (default 1).
        store = HistoryStore(tmp_path / "history")
        (tmp_path / "history" / "alice.json").write_text(
            json.dumps({"student_id": "alice", "records": []}), encoding="utf-8"
        )
        history = store.load("alice")
        assert history.schema_version == 1
        assert history.records == []
