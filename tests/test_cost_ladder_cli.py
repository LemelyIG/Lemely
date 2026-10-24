"""Sub-project C P1: the cost-ladder CLI's real-split wiring. The runner is stubbed."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "cost_ladder_cli", Path(__file__).resolve().parents[1] / "scripts" / "cost_ladder.py"
)
assert _SPEC is not None and _SPEC.loader is not None
cli = importlib.util.module_from_spec(_SPEC)
sys.modules["cost_ladder_cli"] = cli
_SPEC.loader.exec_module(cli)


@pytest.fixture(autouse=True)
def _env_restored() -> Any:
    """Teardown check: no test in this file may leak an environment change."""
    before = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    yield
    assert {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"} == before


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setattr(cli, "load_keys", lambda: calls.setdefault("keys", True))
    monkeypatch.setattr(cli, "require_gemini_key", lambda env: None)
    monkeypatch.setattr(
        cli,
        "load_real_scripts",
        lambda path, only=(): calls.setdefault("scripts", (path, tuple(only))) and ["S"],
    )
    return calls


def test_screen_passes_split_repeats_judge_and_scripts(
    seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lemely.accuracy.cost_ladder.gate import Verdict

    def fake_screen(label: str, sets: dict[str, object], **kw: Any) -> Verdict:
        seen["screen"] = (label, sets, kw)
        return Verdict(True, "small", 0.0, 0, 0, ())

    monkeypatch.setattr(cli, "run_screen", fake_screen)
    toml = tmp_path / "base.toml"
    toml.write_text('[gemini]\ncorrection_model = "claude-haiku-5-5"\n')
    code = cli.main(
        [
            "--out-dir",
            str(tmp_path),
            "--config",
            str(toml),
            "--split",
            "both",
            "--repeats",
            "2",
            "--only",
            "0625_w24_41",
            "screen",
            "--label",
            "b1",
            "--judge",
            "accuracy",
            "--set",
            "gemini.correction_citations=true",
        ]
    )
    assert code == 0 and seen["keys"] is True
    label, sets, kw = seen["screen"]
    assert label == "b1" and sets == {"gemini.correction_citations": True}
    assert kw["split"] == "both" and kw["repeats"] == 2 and kw["judge_kind"] == "accuracy"
    assert kw["real_scripts"] == ["S"]
    assert kw["settings"].gemini.correction_model == "claude-haiku-5-5"
    assert seen["scripts"][1] == ("0625_w24_41",)


def test_dev_split_loads_no_real_scripts(
    seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "run_baseline", lambda **kw: seen.setdefault("baseline", kw) and 0)
    assert cli.main(["--out-dir", str(tmp_path), "baseline"]) == 0
    assert "scripts" not in seen and seen["baseline"]["real_scripts"] == ()


def test_reference_rung_and_judge_flip(
    seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lemely.accuracy.cost_ladder.gate import RunSummary, Verdict

    monkeypatch.setattr(
        cli,
        "run_reference_rung",
        lambda label, **kw: (
            seen.setdefault("ref", (label, kw)) and RunSummary(0, 0, frozenset(), 0, 1, 1, ())
        ),
    )
    monkeypatch.setattr(
        cli, "flip_verdict", lambda out, **kw: Verdict(False, "small", 0, 0, 0, ("x",))
    )
    monkeypatch.setattr(cli, "write_flip", lambda out, **kw: out / "FLIP.md")
    dev = tmp_path / "summary.json"
    assert (
        cli.main(
            [
                "--out-dir",
                str(tmp_path),
                "--split",
                "real",
                "reference-rung",
                "--label",
                "gemini",
                "--dev-from",
                str(dev),
            ]
        )
        == 0
    )
    assert seen["ref"][0] == "gemini" and seen["ref"][1]["dev_summary_from"] == dev
    assert (
        cli.main(
            ["--out-dir", str(tmp_path), "judge-flip", "--candidate", "stack", "--gemini", "gemini"]
        )
        == 1
    )


def test_load_keys_reads_files_without_overwriting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    (home / ".config" / "lemely").mkdir(parents=True)
    (home / ".config" / "lemely" / "anthropic_key").write_text("ak-1\n")
    (home / ".config" / "lemely" / "gemini_key").write_text("from-file\n")
    monkeypatch.setenv("HOME", str(home))
    # setenv (not delenv) so monkeypatch records an undo even when the var was absent
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "kept")
    cli.load_keys()
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "ak-1"
    assert os.environ["GEMINI_API_KEY"] == "kept"


def test_runner_refusals_exit_2_with_message(
    seen: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def refuse(label: str, sets: dict[str, object], **kw: Any) -> None:
        raise ValueError("no projection for provider anthropic")

    monkeypatch.setattr(cli, "run_screen", refuse)
    code = cli.main(["--out-dir", str(tmp_path), "--split", "real", "screen", "--label", "b1"])
    assert code == 2
    assert "no projection for provider anthropic" in capsys.readouterr().err


def test_ladder_state_error_and_reference_drift_exit_2(
    seen: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lemely.accuracy.cost_ladder.real_split import ReferenceDrift
    from lemely.accuracy.cost_ladder.runner import LadderStateError

    def not_ladder(out: Path, **kw: Any) -> None:
        raise LadderStateError("'x' is not a ladder row")

    monkeypatch.setattr(cli, "flip_verdict", not_ladder)
    assert (
        cli.main(["--out-dir", str(tmp_path), "judge-flip", "--candidate", "x", "--gemini", "g"])
        == 2
    )
    assert "not a ladder row" in capsys.readouterr().err

    def drift(path: Path, only: tuple[str, ...] = ()) -> None:
        raise ReferenceDrift("digest mismatch")

    monkeypatch.setattr(cli, "load_real_scripts", drift)
    assert cli.main(["--out-dir", str(tmp_path), "--split", "real", "screen", "--label", "b"]) == 2
    assert "digest mismatch" in capsys.readouterr().err


def test_other_exceptions_are_not_swallowed(
    seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json

    def corrupt(label: str, sets: dict[str, object], **kw: Any) -> None:
        raise json.JSONDecodeError("bad", "", 0)

    monkeypatch.setattr(cli, "run_screen", corrupt)
    with pytest.raises(json.JSONDecodeError):
        cli.main(["--out-dir", str(tmp_path), "screen", "--label", "b"])


def test_max_run_usd_projections_reach_the_runner(
    seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "run_baseline", lambda **kw: seen.setdefault("baseline", kw) and 0)
    assert (
        cli.main(
            [
                "--out-dir",
                str(tmp_path),
                "--max-run-usd",
                "anthropic=0.30",
                "--max-run-usd",
                "gemini=0.05",
                "baseline",
            ]
        )
        == 0
    )
    assert seen["baseline"]["max_run_usd"] == {"anthropic": 0.30, "gemini": 0.05}


def test_reference_rung_loads_scripts_even_on_dev_split(
    seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lemely.accuracy.cost_ladder.gate import RunSummary

    monkeypatch.setattr(
        cli,
        "run_reference_rung",
        lambda label, **kw: (
            seen.setdefault("ref", (label, kw)) and RunSummary(0, 0, frozenset(), 0, 1, 1, ())
        ),
    )
    assert (
        cli.main(
            [
                "--out-dir",
                str(tmp_path),
                "reference-rung",
                "--label",
                "g",
                "--dev-from",
                str(tmp_path / "s.json"),
            ]
        )
        == 0
    )
    assert seen["scripts"] and seen["ref"][1]["repeats"] == 2
    assert seen["ref"][1]["real_scripts"] == ["S"]


def test_missing_anthropic_key_refuses_before_spend(
    seen: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("LEMELY_ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(cli, "run_screen", lambda *a, **kw: seen.setdefault("spent", True))
    toml = tmp_path / "base.toml"
    toml.write_text("[gemini]\n")
    argv = ["--out-dir", str(tmp_path), "--config", str(toml), "screen", "--label", "b"]
    # a claude- model reached only through --set is caught as well
    code = cli.main([*argv, "--set", "gemini.correction_model=claude-haiku-5-5"])
    assert code == 2 and "spent" not in seen
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err and "correction=claude-haiku-5-5" in err


def test_value_error_mid_run_is_not_a_refusal(
    seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pydantic import BaseModel

    class M(BaseModel):
        x: int

    def boom(label: str, sets: dict[str, object], **kw: Any) -> None:
        M.model_validate({"x": "nope"})

    monkeypatch.setattr(cli, "run_screen", boom)
    with pytest.raises(ValueError, match="validation error"):
        cli.main(["--out-dir", str(tmp_path), "screen", "--label", "b"])


def test_baseline_passes_settings_split_repeats(
    seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "run_baseline", lambda **kw: seen.setdefault("baseline", kw) and 0)
    toml = tmp_path / "base.toml"
    toml.write_text('[gemini]\ncorrection_model = "claude-haiku-5-5"\n')
    assert (
        cli.main(
            [
                "--out-dir",
                str(tmp_path),
                "--config",
                str(toml),
                "--split",
                "both",
                "--repeats",
                "2",
                "baseline",
            ]
        )
        == 0
    )
    kw = seen["baseline"]
    assert kw["split"] == "both" and kw["repeats"] == 2
    assert kw["settings"].gemini.correction_model == "claude-haiku-5-5"
    assert kw["real_scripts"] == ["S"]


def test_judge_flip_passes_candidate_and_gemini(
    seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lemely.accuracy.cost_ladder.gate import Verdict

    def flip(out: Path, **kw: Any) -> Verdict:
        seen["flip"] = kw
        return Verdict(True, "small", 0, 0, 0, ())

    monkeypatch.setattr(cli, "flip_verdict", flip)
    monkeypatch.setattr(cli, "write_flip", lambda out, **kw: out / "FLIP.md")
    assert (
        cli.main(["--out-dir", str(tmp_path), "judge-flip", "--candidate", "c1", "--gemini", "g1"])
        == 0
    )
    assert seen["flip"] == {"candidate": "c1", "gemini": "g1"}


def test_settings_load_after_keys(
    seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lemely.accuracy.cost_ladder.gate import Verdict

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    def keys() -> None:
        os.environ["ANTHROPIC_API_KEY"] = "from-file"

    monkeypatch.setattr(cli, "load_keys", keys)
    monkeypatch.setattr(
        cli,
        "run_screen",
        lambda label, sets, **kw: seen.setdefault("kw", kw) and Verdict(True, "s", 0, 0, 0, ()),
    )
    cli.main(["--out-dir", str(tmp_path), "screen", "--label", "b"])
    secret = seen["kw"]["settings"].anthropic_api_key
    assert secret is not None and secret.get_secret_value() == "from-file"


@pytest.mark.parametrize("flags", [["--split", "real"], ["--repeats", "2"], ["--only", "k"]])
@pytest.mark.parametrize("cmd", [["resummarise", "--label", "x"], ["report", "--stop-reason", "r"]])
def test_dev_only_commands_refuse_ladder_flags(
    seen: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    flags: list[str],
    cmd: list[str],
) -> None:
    def ran(*a: Any, **kw: Any) -> None:
        raise AssertionError("ran despite ignored flags")

    monkeypatch.setattr(cli, "resummarise", ran)
    monkeypatch.setattr(cli, "write_report", ran)
    assert cli.main(["--out-dir", str(tmp_path), *flags, *cmd]) == 2


def test_inherited_claude_override_needs_the_key_before_spend(
    seen: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("LEMELY_ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(cli, "run_screen", lambda *a, **kw: seen.setdefault("spent", True))
    b1 = tmp_path / "b1"
    b1.mkdir()
    (b1 / "summary.json").write_text(
        json.dumps({"overrides": {"gemini.correction_model": "claude-haiku-5-5"}})
    )
    (b1 / "verdict.json").write_text(json.dumps({"passed": True}))
    toml = tmp_path / "base.toml"
    toml.write_text("[gemini]\n")
    code = cli.main(
        [
            "--out-dir",
            str(tmp_path),
            "--config",
            str(toml),
            "screen",
            "--label",
            "b2",
            "--against",
            "b1",
            "--set",
            "gemini.correction_citations=true",
        ]
    )
    assert code == 2 and "spent" not in seen
    assert "correction=claude-haiku-5-5" in capsys.readouterr().err


def test_baseline_needing_restart_exits_cleanly(
    seen: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "baseline").mkdir()
    (tmp_path / "baseline" / "summary.json").write_text("{}")
    toml = tmp_path / "base.toml"
    toml.write_text("[gemini]\n")
    code = cli.main(
        [
            "--out-dir",
            str(tmp_path),
            "--config",
            str(toml),
            "--spend-file",
            str(tmp_path / "s.json"),
            "--max-run-usd",
            "gemini=0.01",
            "--max-run-usd",
            "anthropic=0.01",
            "--split",
            "real",
            "baseline",
        ]
    )
    assert code == 2
    assert "--restart-baseline" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["CorpusDigestMismatch", "UpstreamNotFrozen"])
def test_pre_spend_runtime_refusals_exit_2(
    seen: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
) -> None:
    from lemely.accuracy.cost_ladder import runner

    def refuse(label: str, sets: dict[str, object], **kw: Any) -> None:
        if name == "UpstreamNotFrozen":
            raise runner.UpstreamNotFrozen("b", ["correction"], ["extraction"])
        raise runner.CorpusDigestMismatch("refused")

    monkeypatch.setattr(cli, "run_screen", refuse)
    assert cli.main(["--out-dir", str(tmp_path), "screen", "--label", "b"]) == 2
    assert capsys.readouterr().err.startswith("error: ")
