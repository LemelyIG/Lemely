"""Regression tests for ``accuracy_board.py``'s off-board issue paths.

MISSION §3.4 requires *every* issue comment to go through this script, and §3.3
gives the reason: the script exists so the H-issue guard sits on every mutation
path, and a raw ``gh`` call bypasses it. But ``cmd_comment`` gated on **board
membership** — a fact about project hygiene, not about whether an issue is a
human task — so the sanctioned path refused any issue with no project item.
Run 55 alone had to post four rulings (#112, #136, #127, #151) via raw ``gh``
for exactly this reason, and #114 was what opened ask B17 in the first place.

B17 ruled that board membership must stop standing in for the H-guard. That was
implemented for ``done`` and not for ``comment``; these tests pin both halves.

The asymmetry between them is deliberate and is asserted here rather than left
to be "tidied up" later: ``done`` REFUSES a human task, while ``comment`` must
ALLOW one, because MISSION §3.5 requires posting a comment on an H issue to say
what is needed. A guard copied from ``done`` onto ``comment`` would break the
protocol it was meant to protect.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "accuracy_board.py"


def _load_board():
    spec = importlib.util.spec_from_file_location("accuracy_board_offboard_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


board = _load_board()


def _gh_issue_payload(number: int, title: str, labels: list[str], state: str = "OPEN") -> str:
    return json.dumps(
        {
            "number": number,
            "title": title,
            "state": state,
            "labels": [{"name": name} for name in labels],
        }
    )


@pytest.fixture
def offboard(monkeypatch):
    """No issue is on the board; record what the script asks ``gh`` to do."""
    calls: list[list[str]] = []

    def fake_fetch_issues() -> dict[int, object]:
        return {}

    def fake_run_gh(args: list[str], stdin_text: str | None = None) -> str:
        calls.append(args)
        if args[:2] == ["issue", "view"]:
            number = int(args[2])
            return _gh_issue_payload(number, board_titles[number], board_labels.get(number, []))
        return ""

    board_titles: dict[int, str] = {}
    board_labels: dict[int, list[str]] = {}

    monkeypatch.setattr(board, "_fetch_issues", fake_fetch_issues)
    monkeypatch.setattr(board, "_run_gh", fake_run_gh)
    return calls, board_titles, board_labels


def _feed_stdin(monkeypatch, text: str) -> None:
    stream = io.StringIO(text)
    stream.isatty = lambda: False  # type: ignore[method-assign]
    monkeypatch.setattr(sys, "stdin", stream)


def test_comment_posts_on_an_issue_with_no_board_item(offboard, monkeypatch, capsys):
    """The defect: this raised BoardError, so the sanctioned path was unusable."""
    calls, titles, _ = offboard
    titles[151] = "C6: 'det parses MCQ only' retires 100% of the det marking path"
    _feed_stdin(monkeypatch, "the ruling body")

    assert board.cmd_comment(151) == 0

    posted = [c for c in calls if c[:2] == ["issue", "comment"]]
    assert len(posted) == 1, f"expected exactly one comment call, got {calls}"
    assert posted[0][2] == "151"


def test_comment_is_allowed_on_an_H_issue(offboard, monkeypatch):
    """MISSION §3.5 REQUIRES commenting on an H issue to say what is needed.

    ``done`` refuses these; ``comment`` must not. Pinned so that a later pass
    "for consistency" cannot copy the H-guard onto this path.
    """
    calls, titles, labels = offboard
    titles[49] = "H4 — Approve the frozen train/dev/test split membership"
    labels[49] = ["accuracy", "owner:human"]
    _feed_stdin(monkeypatch, "blocked on this, here is what is needed")

    assert board.cmd_comment(49) == 0
    assert [c for c in calls if c[:2] == ["issue", "comment"]]


def test_comment_refuses_when_gh_returns_a_different_issue(offboard, monkeypatch):
    """Fail-closed: never post the body onto the wrong issue."""
    calls, titles, _ = offboard
    titles[151] = "irrelevant"
    _feed_stdin(monkeypatch, "body")

    monkeypatch.setattr(
        board,
        "_run_gh",
        lambda args, stdin_text=None: _gh_issue_payload(999, "some other issue", []),
    )

    with pytest.raises(board.BoardError):
        board.cmd_comment(151)


def test_comment_still_rejects_an_empty_body(offboard, monkeypatch):
    calls, titles, _ = offboard
    titles[151] = "whatever"
    _feed_stdin(monkeypatch, "   ")

    with pytest.raises(board.BoardError):
        board.cmd_comment(151)
    assert not [c for c in calls if c[:2] == ["issue", "comment"]]


def test_done_refuses_an_off_board_owner_human_issue(offboard, monkeypatch):
    """Backfill: B17's ``done`` guards shipped with no test at all.

    Off-board, the ``owner:human`` label is the ONLY thing standing between an
    agent and closing a human task — board membership used to be an incidental
    second net and no longer is.
    """
    calls, titles, labels = offboard
    titles[127] = "golden: 0625_w21_qp_32_theory_nested fixture says theory_extended"
    labels[127] = ["accuracy", "owner:human"]

    assert board.cmd_done(127) == 2
    assert not [c for c in calls if c[:2] == ["issue", "close"]]


def test_done_refuses_an_off_board_H_titled_issue(offboard):
    calls, titles, _ = offboard
    titles[55] = "H9 — Authorise the single run of the frozen test split"

    assert board.cmd_done(55) == 2
    assert not [c for c in calls if c[:2] == ["issue", "close"]]


def test_done_fails_closed_on_a_degraded_gh_payload(offboard, monkeypatch):
    """A guard whose fetch failure defaults to "not a human task" is worse than none.

    ``str(payload["title"])`` on a null title yields "None", which matches no
    H-pattern — so a degraded response would sail past the guard and close the
    issue. Pinned because it only ever fails on the bad path.
    """
    _calls, titles, _ = offboard
    titles[55] = "H9 — Authorise the single run of the frozen test split"

    monkeypatch.setattr(
        board,
        "_run_gh",
        lambda args, stdin_text=None: json.dumps(
            {"number": 55, "title": None, "state": "OPEN", "labels": []}
        ),
    )

    with pytest.raises(board.BoardError):
        board.cmd_done(55)
