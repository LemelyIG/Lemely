"""`lemely label` is a registered Click subcommand (#46, spec §6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from lemely.app.cli import cli


def test_label_help_is_registered() -> None:
    result = CliRunner().invoke(cli, ["label", "--help"])
    assert result.exit_code == 0
    assert "PAPER_ID" in result.output
    assert "--split" in result.output
    assert "--labeller-id" in result.output


def test_write_label_manifest_writes_correct_identity_attribution(tmp_path: Path) -> None:
    """SHOULD-FIX (accuracy-review, #46 repair pass 2).

    ``write_label_manifest``/``run_labeller``'s identity-attribution fix
    (dd10889) had no test at all: every server test calls ``create_server``
    directly, skipping ``run_labeller``'s manifest write, and the CLI test
    above only exercises ``--help``. A regression that silently dropped the
    manifest write would have passed CI. This drives
    ``write_label_manifest`` directly against a tmp eval root and asserts
    the manifest lands with the correct ``paper_id``, ``split``, and
    ``labeller_id``.
    """
    from lemely.labelling.manifest_io import write_label_manifest
    from lemely.labelling.paths import manifest_path

    manifest = write_label_manifest(
        "0580_s23_qp_22", split="dev", labeller_id="labeller-Z", eval_root=tmp_path
    )

    assert manifest.paper_id == "0580_s23_qp_22"
    assert manifest.split == "dev"
    assert manifest.labeller_id == "labeller-Z"

    path = manifest_path("0580_s23_qp_22", "labeller-Z", eval_root=tmp_path)
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["paper_id"] == "0580_s23_qp_22"
    assert on_disk["split"] == "dev"
    assert on_disk["labeller_id"] == "labeller-Z"


def test_run_labeller_writes_the_manifest_before_serving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run_labeller`` itself (not just ``write_label_manifest``) must write the manifest.

    Starts the real server thread ``run_labeller`` would drive (via
    ``port=0`` so it binds an ephemeral port), captures the created server
    through a wrapped ``create_server`` so the test can shut it down
    cleanly, and asserts the manifest exists once the server has come up —
    exercising ``run_labeller``'s own body (including its call into
    ``write_label_manifest``) rather than re-testing that function alone.
    """
    import threading
    import time

    from lemely.labelling import server as server_module

    monkeypatch.chdir(tmp_path)

    real_create_server = server_module.create_server
    created: list[server_module.LabellerHTTPServer] = []

    def _create_and_capture(*args: object, **kwargs: object) -> server_module.LabellerHTTPServer:
        server = real_create_server(*args, **kwargs)  # type: ignore[arg-type]
        created.append(server)
        return server

    monkeypatch.setattr(server_module, "create_server", _create_and_capture)

    server_thread = threading.Thread(
        target=server_module.run_labeller,
        kwargs={"paper_id": "RUN01", "split": "train", "labeller_id": "labeller-R", "port": 0},
        daemon=True,
    )
    server_thread.start()

    try:
        manifest_file = Path("eval") / "labels" / "RUN01" / "labeller-R" / "manifest.json"
        for _ in range(200):
            if manifest_file.is_file():
                break
            time.sleep(0.01)
        else:
            raise AssertionError("manifest.json was never written by run_labeller")

        on_disk = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert on_disk["paper_id"] == "RUN01"
        assert on_disk["split"] == "train"
        assert on_disk["labeller_id"] == "labeller-R"
    finally:
        for server in created:
            server.shutdown()
        server_thread.join(timeout=5)
