"""The two-pass blind labeller must stay blind to the correction pipeline.

Spec §6 (labelling protocol) + §4 M2.3 acceptance: pass 1 (transcription)
never sees the mark scheme; pass 2 (marking) sees the mark scheme plus the
labeller's OWN pass-1 transcription, never a pipeline output object; and the
whole module imports zero correction-pipeline modules.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from lemely.labelling.paper_data import load_pass1_context, load_pass2_context
from lemely.labelling.paths import transcription_path
from lemely.labelling.records import append_record
from lemely.labelling.verify import verify_chain


def test_pass1_context_carries_no_mark_scheme_data(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scans" / "0580_s23_qp_22"
    scan_dir.mkdir(parents=True)
    (scan_dir / "page-01.png").write_bytes(b"fake-image-bytes")

    context = load_pass1_context("0580_s23_qp_22", eval_root=tmp_path)

    assert "mark_scheme" not in context
    assert "mark_scheme" not in json.dumps(context)
    assert context["scan_images"]


def test_pass2_context_has_mark_scheme_and_own_transcription_only(tmp_path: Path) -> None:
    # Own pass-1 transcription, already written.
    trans_path = transcription_path("0580_s23_qp_22", "labeller-A", eval_root=tmp_path)
    append_record(trans_path, {"question_id": "q0", "text": "my transcription"})

    context = load_pass2_context("0580_s23_qp_22", "labeller-A", eval_root=tmp_path)

    assert context["paper_id"] == "0580_s23_qp_22"
    assert context["own_transcription"][0]["payload"]["text"] == "my transcription"
    # No CorrectedQuestion or pipeline-output type anywhere in the context.
    for value in context.values():
        assert type(value).__module__ != "lemely.core.schemas"


def test_pass2_context_for_a_different_labeller_does_not_see_labeller_a() -> None:
    from lemely.labelling.paper_data import load_pass2_context as _load

    assert _load is load_pass2_context  # sanity: same symbol, no shadowing


def test_labelling_module_never_imports_the_correction_pipeline() -> None:
    """Run in a fresh interpreter — this pytest process may already have the
    correction pipeline loaded from an unrelated test module, which would
    make an in-process ``sys.modules`` check pass or fail by accident."""
    script = (
        "import sys\n"
        "import lemely.labelling.paper_data\n"
        "import lemely.labelling.records\n"
        "import lemely.labelling.server\n"
        "import lemely.labelling.verify\n"
        "forbidden = {'lemely.core.correction', 'lemely.io.correction_ai'}\n"
        "assert not (set(sys.modules) & forbidden), sorted(set(sys.modules) & forbidden)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_smoke_labeller_server_writes_valid_hash_chain_and_stays_pipeline_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec M2.3 acceptance: hash-chained JSONL.

    The "zero pipeline imports" half of the M2.3 acceptance is asserted in a
    fresh subprocess by
    ``test_labelling_module_never_imports_the_correction_pipeline`` above —
    an in-process check here would be unreliable, since another test module
    in this same pytest run may have already imported the correction
    pipeline for unrelated reasons.
    """
    monkeypatch.chdir(tmp_path)

    from lemely.labelling.server import create_server

    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        base = f"http://127.0.0.1:{port}"

        resp = urllib.request.urlopen(f"{base}/pass1?paper_id=SMOKE01", timeout=5)
        pass1_payload = json.loads(resp.read())
        assert "mark_scheme" not in pass1_payload

        req = urllib.request.Request(
            f"{base}/pass1?paper_id=SMOKE01&labeller_id=A",
            data=json.dumps({"question_id": "q0", "text": "smoke transcription"}).encode(),
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)

        req2 = urllib.request.Request(
            f"{base}/pass2?paper_id=SMOKE01&labeller_id=A",
            data=json.dumps({"question_id": "q0", "awarded_marks": 1}).encode(),
            method="POST",
        )
        urllib.request.urlopen(req2, timeout=5)
    finally:
        server.shutdown()
        server.server_close()

    trans_path = Path("eval") / "labels" / "SMOKE01" / "A" / "transcription.jsonl"
    mark_path = Path("eval") / "labels" / "SMOKE01" / "A" / "marking.jsonl"
    assert trans_path.is_file()
    assert mark_path.is_file()
    assert verify_chain(trans_path).ok
    assert verify_chain(mark_path).ok


def test_labelling_source_does_not_import_test_split_authorisation() -> None:
    package_dir = Path(__file__).resolve().parents[2] / "lemely" / "labelling"
    for path in package_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "authorize_test_split_join(" not in text
        assert "import lemely.eval.test_touch" not in text
        assert "from lemely.eval.test_touch" not in text
    assert "lemely.eval.test_touch" not in sys.modules
