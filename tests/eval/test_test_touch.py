"""Test-touch ledger gate tests (spec §3.3 split, §7 M0.7a, DA1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemely.eval.manifest import Split
from lemely.eval.test_touch import (
    TestSplitAccessError,
    authorize_test_split_join,
)

_TOKEN_ENV_VAR = "LEMELY_TEST_SPLIT_TOKEN"


def _read_ledger_lines(ledger_path: Path) -> list[str]:
    if not ledger_path.exists():
        return []
    return ledger_path.read_text(encoding="utf-8").splitlines()


def test_raises_without_token_for_test_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_TOKEN_ENV_VAR, "correct-token")
    ledger_path = tmp_path / "test-touch-ledger.jsonl"

    with pytest.raises(TestSplitAccessError):
        authorize_test_split_join(
            "test",
            token=None,
            run_id="run-1",
            caller="test_raises_without_token_for_test_split",
            ledger_path=ledger_path,
        )

    assert _read_ledger_lines(ledger_path) == []


def test_raises_with_invalid_token_for_test_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_TOKEN_ENV_VAR, "correct-token")
    ledger_path = tmp_path / "test-touch-ledger.jsonl"

    with pytest.raises(TestSplitAccessError):
        authorize_test_split_join(
            "test",
            token="wrong-token",
            run_id="run-1",
            caller="test_raises_with_invalid_token_for_test_split",
            ledger_path=ledger_path,
        )

    assert _read_ledger_lines(ledger_path) == []


def test_authorised_test_access_appends_ledger_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_TOKEN_ENV_VAR, "correct-token")
    ledger_path = tmp_path / "test-touch-ledger.jsonl"

    authorize_test_split_join(
        "test",
        token="correct-token",
        run_id="run-1",
        caller="test_authorised_test_access_appends_ledger_entry",
        ledger_path=ledger_path,
    )

    lines = _read_ledger_lines(ledger_path)
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["run_id"] == "run-1"
    assert entry["caller"] == "test_authorised_test_access_appends_ledger_entry"
    assert "timestamp" in entry

    # A second authorised call appends exactly one more line.
    authorize_test_split_join(
        "test",
        token="correct-token",
        run_id="run-2",
        caller="test_authorised_test_access_appends_ledger_entry",
        ledger_path=ledger_path,
    )
    assert len(_read_ledger_lines(ledger_path)) == 2


@pytest.mark.parametrize("split", ["train", "dev"])
def test_train_and_dev_are_ungated(
    split: Split, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_TOKEN_ENV_VAR, raising=False)
    ledger_path = tmp_path / "test-touch-ledger.jsonl"

    # No token, no ceremony, no exception.
    authorize_test_split_join(
        split,
        token=None,
        run_id="run-1",
        caller="test_train_and_dev_are_ungated",
        ledger_path=ledger_path,
    )

    assert _read_ledger_lines(ledger_path) == []
