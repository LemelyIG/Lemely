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
import json
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


class TestDoneForOffBoardIssues:
    """B17 option 3: ``done`` must close a non-H issue that has no board item.

    Board membership used to be a proxy for the H-guard (``_require_issue``
    raised before the guard could even run), which meant an issue simply not
    being on the board — not a human-task property — was what blocked `done`.
    This closes #114, #120, #121, #122, #124, none of which are on the board.

    The H-guard itself must still work identically off-board: it is checked
    directly against the fetched title, never against board membership.
    """

    def _on_board_issue(self, board, number: int, title: str, state: str = "OPEN"):
        return board.Issue(
            number=number,
            title=title,
            state=state,
            parent=23,
            status="Ready",
            size=None,
            item_id="item-xyz",
        )

    def _gh_stub(
        self,
        monkeypatch,
        board,
        *,
        view_title: str,
        view_state: str = "OPEN",
        labels: list[str] | None = None,
        raw_override: str | None = None,
    ):
        """Patch ``_run_gh`` to answer ``issue view`` and record every call.

        ``raw_override`` returns a literal payload string instead of a
        well-formed one, so the fail-closed paths can be driven with the
        degraded responses they exist for.
        """
        calls: list[list[str]] = []

        def fake_run_gh(args, stdin_text=None):
            calls.append(args)
            if args[:2] == ["issue", "view"]:
                if raw_override is not None:
                    return raw_override
                payload = {
                    "number": int(args[2]),
                    "title": view_title,
                    "state": view_state,
                    "labels": [{"name": n} for n in (labels or [])],
                }
                return json.dumps(payload)
            if args[:2] == ["issue", "close"]:
                return ""
            raise AssertionError(f"unexpected gh invocation in this test: {args}")

        monkeypatch.setattr(board, "_run_gh", fake_run_gh)
        return calls

    def _forbid_set_status(self, monkeypatch, board):
        def fail(*_a, **_kw):
            raise AssertionError("_set_status must not be called: there is no board item")

        monkeypatch.setattr(board, "_set_status", fail)

    def test_off_board_non_h_issue_closes_and_skips_set_status(self, monkeypatch):
        board = _load_board()
        monkeypatch.setattr(board, "_fetch_issues", lambda: {})
        self._forbid_set_status(monkeypatch, board)
        calls = self._gh_stub(board=board, monkeypatch=monkeypatch, view_title="M1.6 — some fix")

        assert board.cmd_done(114) == 0

        close_calls = [c for c in calls if c[:2] == ["issue", "close"]]
        assert len(close_calls) == 1
        assert close_calls[0][2] == "114"

    def test_off_board_h_issue_is_refused_exit_2_no_close(self, monkeypatch):
        board = _load_board()
        monkeypatch.setattr(board, "_fetch_issues", lambda: {})
        self._forbid_set_status(monkeypatch, board)
        calls = self._gh_stub(
            board=board, monkeypatch=monkeypatch, view_title="H4 — human approval needed"
        )

        assert board.cmd_done(4999) == 2

        close_calls = [c for c in calls if c[:2] == ["issue", "close"]]
        assert close_calls == [], "H-guard must fire before any close is attempted"

    def test_on_board_non_h_issue_is_unchanged(self, monkeypatch):
        board = _load_board()
        issue = self._on_board_issue(board, 200, "M1.2 — positional fallback deletion")
        monkeypatch.setattr(board, "_fetch_issues", lambda: {200: issue})

        set_status_calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            board, "_set_status", lambda item_id, status: set_status_calls.append((item_id, status))
        )
        calls = self._gh_stub(board=board, monkeypatch=monkeypatch, view_title=issue.title)

        assert board.cmd_done(200) == 0

        assert set_status_calls == [("item-xyz", "Done")]
        close_calls = [c for c in calls if c[:2] == ["issue", "close"]]
        assert len(close_calls) == 1
        assert close_calls[0][2] == "200"

    def test_on_board_h_issue_is_still_refused_exit_2(self, monkeypatch):
        board = _load_board()
        issue = self._on_board_issue(board, 49, "H4 — human approval")
        monkeypatch.setattr(board, "_fetch_issues", lambda: {49: issue})
        self._forbid_set_status(monkeypatch, board)
        calls = self._gh_stub(board=board, monkeypatch=monkeypatch, view_title=issue.title)

        assert board.cmd_done(49) == 2

        close_calls = [c for c in calls if c[:2] == ["issue", "close"]]
        assert close_calls == [], "H-guard must fire before any close is attempted"

    def test_nonexistent_issue_fails_clearly(self, monkeypatch):
        board = _load_board()
        monkeypatch.setattr(board, "_fetch_issues", lambda: {})

        def fake_run_gh(args, stdin_text=None):
            if args[:2] == ["issue", "view"]:
                raise board.BoardError(
                    "gh issue view failed (exit 1): GraphQL: Could not resolve to an Issue"
                )
            raise AssertionError(f"unexpected gh invocation: {args}")

        monkeypatch.setattr(board, "_run_gh", fake_run_gh)

        with pytest.raises(board.BoardError, match="Could not resolve"):
            board.cmd_done(999999)

    def test_off_board_owner_human_label_is_refused_exit_2_no_close(self, monkeypatch):
        """The label half of B17's ruling: not every human task carries an H-number.

        ``owner:human`` marks issues that are human-only without an H-numbered
        title (#47 is one, though it is on-board today). Off-board this guard
        stands alone — board membership used to be an incidental second net —
        so a title-only check would close such an issue.
        """
        board = _load_board()
        monkeypatch.setattr(board, "_fetch_issues", lambda: {})
        self._forbid_set_status(monkeypatch, board)
        calls = self._gh_stub(
            monkeypatch,
            board,
            view_title="M2.4 — Label ~300 distinct leaf questions",
            labels=["owner:human"],
        )

        assert board.cmd_done(4747) == 2
        assert [c for c in calls if c[:2] == ["issue", "close"]] == []

    def test_off_board_unrelated_labels_do_not_block_a_close(self, monkeypatch):
        """Guard against an over-broad fix: only ``owner:human`` refuses."""
        board = _load_board()
        monkeypatch.setattr(board, "_fetch_issues", lambda: {})
        self._forbid_set_status(monkeypatch, board)
        calls = self._gh_stub(
            monkeypatch, board, view_title="tests: something", labels=["bug", "accuracy"]
        )

        assert board.cmd_done(4748) == 0
        assert [c for c in calls if c[:2] == ["issue", "close"]] != []

    @pytest.mark.parametrize(
        ("raw", "match"),
        [
            ('{"number": 4749, "title": null, "state": "OPEN"}', "no usable title"),
            ('{"number": 4749, "title": "   ", "state": "OPEN"}', "no usable title"),
            ('{"number": 4749, "state": "OPEN"}', "no usable title"),
            ('{"number": 4749, "title": "x", "state": "weird"}', "unrecognised state"),
            ('{"number": 1, "title": "x", "state": "OPEN"}', "when asked for"),
            ("[]", "non-object payload"),
        ],
    )
    def test_degraded_gh_payloads_fail_closed_and_never_close(self, monkeypatch, raw, match):
        """A degraded fetch must raise, NEVER fall through to a close.

        This is the failure shape the guard exists to prevent: ``str(None)``
        and ``str("")`` produce titles that match no H-pattern, so coercing
        instead of validating would let a broken response close a human task.
        Each payload below was verified to close the issue before the
        validation landed.
        """
        board = _load_board()
        monkeypatch.setattr(board, "_fetch_issues", lambda: {})
        self._forbid_set_status(monkeypatch, board)
        calls = self._gh_stub(monkeypatch, board, view_title="unused", raw_override=raw)

        with pytest.raises(board.BoardError, match=match):
            board.cmd_done(4749)
        assert [c for c in calls if c[:2] == ["issue", "close"]] == []


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
