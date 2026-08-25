"""Regression tests for ``scripts/accuracy_board.py``'s state header handling.

The state file is the supervisor's resume pointer: it is read between runs with
``grep -m1 "^<key>:"``. A bug in ``_parse_state_header`` made an *empty-valued*
key (``in_the_middle_of:`` with nothing after the colon) invisible, because the
parser tested ``": " in line`` and that line has no space after the colon.
``state set`` therefore took its "key is absent" branch and INSERTED a second
line, leaving the empty one above the populated one — so ``grep -m1`` matched
the empty value and every handoff note written to the file was invisible to the
next run. The duplicate-key guard could not fire either, because the offending
line was never recognised as a key.

This was repaired by hand once and silently came back, which is what earns it a
test rather than another repair.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "accuracy_board.py"


def _load_board():
    spec = importlib.util.spec_from_file_location("accuracy_board_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


board = _load_board()


HEADER_KEYS = (
    "run_pointer: run-x",
    "worktree: /tmp/wt",
    "branch: none",
    "last_run_label: none",
    "last_run_headline: none",
    "review_rate: 19.1%",
    "ratchet: unarmed",
    "spend_usd: 0.4026",
)


def _write_state(tmp_path: Path, in_the_middle_of_line: str) -> Path:
    path = tmp_path / "ACCURACY-STATE.md"
    path.write_text(
        "# ACCURACY-STATE.md\n\n"
        + "\n".join(HEADER_KEYS)
        + f"\n{in_the_middle_of_line}\n---\n\n## body\n\nprose\n"
    )
    return path


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    def _make(in_the_middle_of_line: str) -> Path:
        path = _write_state(tmp_path, in_the_middle_of_line)
        monkeypatch.setattr(board, "_state_path", lambda: path)
        return path

    return _make


def test_empty_valued_key_is_recognised_not_duplicated(state_file):
    """``state set`` must REPLACE an empty-valued key, never insert beside it."""
    path = state_file("in_the_middle_of:")

    assert board.cmd_state_set("in_the_middle_of", "#25 mid-flight") == 0

    lines = path.read_text().split("\n")
    keyed = [line for line in lines if line.startswith("in_the_middle_of:")]
    assert keyed == ["in_the_middle_of: #25 mid-flight"], (
        "empty-valued key must be replaced in place, not left above a second line"
    )


def test_supervisor_grep_m1_sees_the_real_value(state_file):
    """What the supervisor actually does: first match wins. It must be the note."""
    path = state_file("in_the_middle_of:")
    board.cmd_state_set("in_the_middle_of", "#25 mid-flight")

    first_match = next(
        line for line in path.read_text().split("\n") if line.startswith("in_the_middle_of:")
    )
    assert first_match == "in_the_middle_of: #25 mid-flight"


def test_empty_valued_key_reads_back_as_empty_string(state_file):
    """``state get`` must not raise on a key that is present but has no value."""
    state_file("in_the_middle_of:")
    header, _ = board._parse_state_header(board._read_state_lines())
    assert "in_the_middle_of" in header


def test_duplicate_key_is_rejected(state_file):
    """The guard must fire on a genuinely duplicated key instead of silently picking one."""
    path = state_file("in_the_middle_of:")
    text = path.read_text().replace(
        "in_the_middle_of:\n", "in_the_middle_of:\nin_the_middle_of: real note\n"
    )
    path.write_text(text)

    with pytest.raises(board.BoardError, match="appears twice"):
        board._parse_state_header(board._read_state_lines())


def test_populated_key_still_round_trips(state_file):
    """The ordinary path must be unaffected by the empty-value fix."""
    path = state_file("in_the_middle_of: old note")

    assert board.cmd_state_set("in_the_middle_of", "new note") == 0

    keyed = [line for line in path.read_text().split("\n") if line.startswith("in_the_middle_of:")]
    assert keyed == ["in_the_middle_of: new note"]


def test_spend_usd_increment_still_works(state_file):
    """``+delta`` accumulation reads the current value through the new helper."""
    path = state_file("in_the_middle_of: note")

    assert board.cmd_state_set("spend_usd", "+1.0") == 0

    spend = next(line for line in path.read_text().split("\n") if line.startswith("spend_usd:"))
    assert spend.split(": ", 1)[1].startswith("1.4")


class TestAppendBlockerIsIdempotent:
    """``block`` must not append a second stub for an issue it already logged.

    BUILD/BLOCKERS.md is under a never-delete contract, so a duplicated section
    cannot be tidied away after the fact — it has to not be written. #40 was
    appended twice by the old unconditional ``open(..., "a")`` and had to be
    de-duplicated by hand on 2026-08-25 under an explicit human authorisation.
    """

    def _issue(self, board, number: int, title: str):
        return board.Issue(
            number=number,
            title=title,
            state="OPEN",
            parent=23,
            status="Ready",
            size=None,
            item_id="item-id",
        )

    def test_second_block_for_the_same_issue_appends_nothing(self, tmp_path, monkeypatch):
        board = _load_board()
        blockers = tmp_path / "BLOCKERS.md"
        blockers.write_text("# BLOCKERS\n", encoding="utf-8")
        monkeypatch.setattr(board, "BLOCKERS_FILE", blockers)

        issue = self._issue(board, 40, "Coherence gate")
        assert board._append_blocker(issue, "a human decision") is True
        after_first = blockers.read_text(encoding="utf-8")
        assert after_first.count("## #40 — ") == 1

        # Same issue, different stated reason: still no second section.
        assert board._append_blocker(issue, "something else entirely") is False
        assert blockers.read_text(encoding="utf-8") == after_first

    def test_a_retitled_issue_is_still_recognised(self, tmp_path, monkeypatch):
        """The heading is matched on the number, because titles get edited."""
        board = _load_board()
        blockers = tmp_path / "BLOCKERS.md"
        blockers.write_text("# BLOCKERS\n", encoding="utf-8")
        monkeypatch.setattr(board, "BLOCKERS_FILE", blockers)

        assert board._append_blocker(self._issue(board, 51, "Old title"), "x") is True
        assert board._append_blocker(self._issue(board, 51, "New title"), "x") is False
        assert blockers.read_text(encoding="utf-8").count("## #51 — ") == 1

    def test_a_different_issue_still_gets_its_own_section(self, tmp_path, monkeypatch):
        board = _load_board()
        blockers = tmp_path / "BLOCKERS.md"
        blockers.write_text("# BLOCKERS\n", encoding="utf-8")
        monkeypatch.setattr(board, "BLOCKERS_FILE", blockers)

        assert board._append_blocker(self._issue(board, 40, "A"), "x") is True
        assert board._append_blocker(self._issue(board, 41, "B"), "x") is True
        text = blockers.read_text(encoding="utf-8")
        assert text.count("## #40 — ") == 1
        assert text.count("## #41 — ") == 1
