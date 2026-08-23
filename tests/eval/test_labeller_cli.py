"""`lemely label` is a registered Click subcommand (#46, spec §6)."""

from __future__ import annotations

from click.testing import CliRunner

from lemely.app.cli import cli


def test_label_help_is_registered() -> None:
    result = CliRunner().invoke(cli, ["label", "--help"])
    assert result.exit_code == 0
    assert "PAPER_ID" in result.output
    assert "--split" in result.output
    assert "--labeller-id" in result.output
