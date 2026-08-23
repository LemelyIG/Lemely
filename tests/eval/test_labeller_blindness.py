"""The two-pass blind labeller must stay blind to the correction pipeline.

Spec §6 (labelling protocol) + §4 M2.3 acceptance: pass 1 (transcription)
never sees the mark scheme; pass 2 (marking) sees the mark scheme plus the
labeller's OWN pass-1 transcription, never a pipeline output object; and the
whole module imports zero correction-pipeline modules.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pytest

from lemely.labelling.paper_data import load_pass1_context, load_pass2_context
from lemely.labelling.paths import transcription_path
from lemely.labelling.records import append_record
from lemely.labelling.verify import verify_chain

_GOLDEN_MARK_SCHEME = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "golden"
    / "0580_s23_qp_22_theory_correct"
    / "mark_scheme.json"
)
_GOLDEN_SCAN = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "golden"
    / "0580_s23_qp_22_theory_correct"
    / "scan.pdf"
)


def _seed_real_paper(eval_root: Path, paper_id: str) -> None:
    """Set up a real scan dir + mark scheme for ``paper_id`` under ``eval_root``.

    Uses the golden corpus fixture (real, already-parsed mark scheme data)
    rather than an invented paper_id with nothing on disk — a smoke test
    against an empty corpus "passes" over an empty corpus.
    """
    scan_dir = eval_root / "scans" / paper_id
    scan_dir.mkdir(parents=True)
    shutil.copyfile(_GOLDEN_SCAN, scan_dir / "scan.pdf")
    schemes_dir = eval_root / "mark_schemes"
    schemes_dir.mkdir(parents=True)
    shutil.copyfile(_GOLDEN_MARK_SCHEME, schemes_dir / f"{paper_id}.json")


class _RenderedFormFields(HTMLParser):
    """Extract a rendered page's ``<form action=...>`` and its field names.

    Used so tests exercise the *actual* field names ``pages.py`` emits
    (derived from the served HTML) rather than a hand-typed guess that could
    silently drift out of sync with the real markup.
    """

    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.field_names: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "form":
            self.action = attr_map.get("action")
        elif tag in {"input", "textarea"} and attr_map.get("name"):
            name = attr_map["name"]
            assert name is not None
            self.field_names.append(name)


def _parse_rendered_form(html: str) -> _RenderedFormFields:
    parser = _RenderedFormFields()
    parser.feed(html)
    assert parser.action, "rendered page has no <form action=...>"
    assert parser.field_names, "rendered page's <form> has no named fields"
    return parser


def test_pass1_context_carries_no_mark_scheme_data(tmp_path: Path) -> None:
    _seed_real_paper(tmp_path, "0580_s23_qp_22")

    context = load_pass1_context("0580_s23_qp_22", eval_root=tmp_path)

    assert "mark_scheme" not in context
    assert "mark_scheme" not in json.dumps(context)
    assert context["scan_images"]


def test_pass2_context_has_mark_scheme_and_own_transcription_only(tmp_path: Path) -> None:
    _seed_real_paper(tmp_path, "0580_s23_qp_22")
    # Own pass-1 transcription, already written.
    trans_path = transcription_path("0580_s23_qp_22", "labeller-A", eval_root=tmp_path)
    append_record(trans_path, {"question_id": "q0", "text": "my transcription"})

    context = load_pass2_context("0580_s23_qp_22", "labeller-A", eval_root=tmp_path)

    assert context["paper_id"] == "0580_s23_qp_22"
    assert context["own_transcription"][0]["payload"]["text"] == "my transcription"
    # A real mark scheme is on disk for this test (unlike a vacuous "nothing
    # to leak" fixture) — this genuinely exercises that no CorrectedQuestion
    # or other pipeline-output type is anywhere in the context.
    mark_scheme = context["mark_scheme"]
    assert isinstance(mark_scheme, dict)
    assert mark_scheme["questions"]
    for value in context.values():
        assert type(value).__module__ != "lemely.core.schemas"


def test_pass2_context_for_a_different_labeller_does_not_see_labeller_a(tmp_path: Path) -> None:
    _seed_real_paper(tmp_path, "0580_s23_qp_22")
    path_a = transcription_path("0580_s23_qp_22", "labeller-A", eval_root=tmp_path)
    append_record(path_a, {"question_id": "q0", "text": "A's answer"})

    context_b = load_pass2_context("0580_s23_qp_22", "labeller-B", eval_root=tmp_path)

    # Labeller B has written nothing yet, and must not see A's transcription
    # even though A labelled the same paper.
    assert context_b["own_transcription"] == []
    assert "A's answer" not in json.dumps(context_b)


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
    """Spec M2.3 acceptance: hash-chained JSONL, and a real page is served.

    Uses the golden corpus's real mark scheme + scan, not an invented
    paper_id with nothing on disk (an empty-corpus "pass" here would be
    vacuous). The "zero pipeline imports" half of the M2.3 acceptance is
    asserted in a fresh subprocess by
    ``test_labelling_module_never_imports_the_correction_pipeline`` above —
    an in-process check here would be unreliable, since another test module
    in this same pytest run may have already imported the correction
    pipeline for unrelated reasons.
    """
    monkeypatch.chdir(tmp_path)
    _seed_real_paper(Path("eval"), "SMOKE01")

    from lemely.labelling.server import create_server

    server = create_server(port=0, labeller_id="A", split="train")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        base = f"http://127.0.0.1:{port}"

        resp = urllib.request.urlopen(f"{base}/pass1?paper_id=SMOKE01", timeout=5)
        assert resp.headers.get("Content-Type", "").startswith("text/html")
        pass1_html = resp.read().decode("utf-8")
        assert pass1_html.startswith("<!DOCTYPE html")
        assert "<html" in pass1_html
        assert "mark_scheme" not in pass1_html
        assert "/scan?paper_id=SMOKE01&amp;name=scan.pdf" in pass1_html

        scan_resp = urllib.request.urlopen(f"{base}/scan?paper_id=SMOKE01&name=scan.pdf", timeout=5)
        assert scan_resp.headers.get("Content-Type") == "application/pdf"
        assert scan_resp.read()

        req = urllib.request.Request(
            f"{base}/pass1?paper_id=SMOKE01",
            data=json.dumps({"question_id": "q0", "text": "smoke transcription"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)

        pass2_resp = urllib.request.urlopen(f"{base}/pass2?paper_id=SMOKE01", timeout=5)
        pass2_html = pass2_resp.read().decode("utf-8")
        assert pass2_html.startswith("<!DOCTYPE html")
        assert "smoke transcription" in pass2_html

        req2 = urllib.request.Request(
            f"{base}/pass2?paper_id=SMOKE01",
            data=json.dumps({"question_id": "q0", "awarded_marks": 1}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req2, timeout=5)
    finally:
        server.shutdown()
        server.server_close()

    # Records must land under the server's bound identity ("A"), never under
    # a client-supplied query-string value the server no longer reads.
    trans_path = Path("eval") / "labels" / "SMOKE01" / "A" / "transcription.jsonl"
    mark_path = Path("eval") / "labels" / "SMOKE01" / "A" / "marking.jsonl"
    assert trans_path.is_file()
    assert mark_path.is_file()
    assert verify_chain(trans_path).ok
    assert verify_chain(mark_path).ok


def test_labeller_rejects_a_cross_origin_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_real_paper(Path("eval"), "SMOKE02")

    from lemely.labelling.server import create_server

    server = create_server(port=0, labeller_id="A", split="train")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/pass1?paper_id=SMOKE02",
            headers={"Origin": "http://evil.example.com"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=5)
        assert exc_info.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_labeller_rejects_path_traversal_in_paper_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    from lemely.labelling.server import create_server

    server = create_server(port=0, labeller_id="A", split="train")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/pass1?paper_id=../../../../etc/evil",
            data=json.dumps({"question_id": "q0", "text": "malicious"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=5)
        assert exc_info.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_labeller_pass1_and_pass2_forms_submit_as_real_browsers_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUST-FIX (accuracy-review, #46 repair pass 2): the human path.

    A real browser posts ``application/x-www-form-urlencoded`` with exactly
    the field names the rendered ``<form>`` declares, not hand-built JSON.
    Before this fix the server unconditionally did
    ``json.loads(raw_body)``, so this exact request crashed with an
    unhandled ``JSONDecodeError`` and dropped the connection with zero
    bytes written — the whole point of shipping a browser-served labeller.

    Field names are parsed out of the actually-rendered HTML rather than
    hand-typed, so this test cannot silently drift out of sync with
    ``pages.py``.
    """
    monkeypatch.chdir(tmp_path)
    _seed_real_paper(Path("eval"), "FORM01")

    from lemely.labelling.server import create_server

    server = create_server(port=0, labeller_id="A", split="train")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        base = f"http://127.0.0.1:{port}"

        # --- pass 1: transcription, as a browser's form submit would send it ---
        pass1_resp = urllib.request.urlopen(f"{base}/pass1?paper_id=FORM01", timeout=5)
        pass1_form = _parse_rendered_form(pass1_resp.read().decode("utf-8"))
        assert pass1_form.action is not None

        pass1_values = {name: f"real browser value for {name}" for name in pass1_form.field_names}
        pass1_body = urllib.parse.urlencode(pass1_values).encode("ascii")
        pass1_action_url = urllib.parse.urljoin(f"{base}/pass1", pass1_form.action)
        req1 = urllib.request.Request(
            pass1_action_url,
            data=pass1_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        resp1 = urllib.request.urlopen(req1, timeout=5)
        assert resp1.status == 201

        # --- pass 2: marking, same real-form-submit shape ---
        pass2_resp = urllib.request.urlopen(f"{base}/pass2?paper_id=FORM01", timeout=5)
        pass2_form = _parse_rendered_form(pass2_resp.read().decode("utf-8"))
        assert pass2_form.action is not None
        assert "awarded_marks" in pass2_form.field_names

        pass2_values: dict[str, str] = {}
        for name in pass2_form.field_names:
            pass2_values[name] = "3" if name == "awarded_marks" else "q0"
        pass2_body = urllib.parse.urlencode(pass2_values).encode("ascii")
        pass2_action_url = urllib.parse.urljoin(f"{base}/pass2", pass2_form.action)
        req2 = urllib.request.Request(
            pass2_action_url,
            data=pass2_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        resp2 = urllib.request.urlopen(req2, timeout=5)
        assert resp2.status == 201
    finally:
        server.shutdown()
        server.server_close()

    trans_path = Path("eval") / "labels" / "FORM01" / "A" / "transcription.jsonl"
    mark_path = Path("eval") / "labels" / "FORM01" / "A" / "marking.jsonl"
    assert trans_path.is_file()
    assert mark_path.is_file()
    assert verify_chain(trans_path).ok
    assert verify_chain(mark_path).ok

    trans_records = [
        json.loads(line) for line in trans_path.read_text(encoding="utf-8").splitlines()
    ]
    assert trans_records[0]["payload"]["text"] == "real browser value for text"

    mark_records = [json.loads(line) for line in mark_path.read_text(encoding="utf-8").splitlines()]
    # awarded_marks must be coerced to an int — the marking record schema
    # downstream expects a number, not the string a raw form field yields.
    assert mark_records[0]["payload"]["awarded_marks"] == 3
    assert isinstance(mark_records[0]["payload"]["awarded_marks"], int)


def test_labeller_malformed_json_body_returns_400_not_a_dropped_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUST-FIX: a malformed body must produce an HTTP response, never a dropped socket."""
    monkeypatch.chdir(tmp_path)
    _seed_real_paper(Path("eval"), "BAD01")

    from lemely.labelling.server import create_server

    server = create_server(port=0, labeller_id="A", split="train")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/pass1?paper_id=BAD01",
            data=b"{not valid json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=5)
        assert exc_info.value.code == 400
    finally:
        server.shutdown()
        server.server_close()

    # And nothing was appended.
    trans_path = Path("eval") / "labels" / "BAD01" / "A" / "transcription.jsonl"
    assert not trans_path.exists()


def test_labeller_rejects_unknown_or_missing_content_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUST-FIX: an unrecognised/absent Content-Type is rejected, not guessed at."""
    monkeypatch.chdir(tmp_path)
    _seed_real_paper(Path("eval"), "CT01")

    from lemely.labelling.server import create_server

    server = create_server(port=0, labeller_id="A", split="train")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port

        # No Content-Type header at all. ``urllib.request`` helpfully
        # defaults to form-urlencoded whenever ``data=`` is set and no
        # Content-Type is given, so a raw ``http.client`` connection is used
        # here to genuinely send zero Content-Type header — the case a
        # non-browser, non-urllib client (e.g. a bare ``nc``/curl
        # ``--header`` omission) can actually produce.
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = b"question_id=q0&text=hi"
        conn.putrequest("POST", "/pass1?paper_id=CT01")
        conn.putheader("Content-Length", str(len(body)))
        conn.endheaders()
        conn.send(body)
        missing_ct_resp = conn.getresponse()
        assert missing_ct_resp.status == 400
        conn.close()

        # An unrecognised Content-Type.
        req_unknown = urllib.request.Request(
            f"http://127.0.0.1:{port}/pass1?paper_id=CT01",
            data=b"whatever",
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_unknown, timeout=5)
        assert exc_info.value.code == 400
    finally:
        server.shutdown()
        server.server_close()

    trans_path = Path("eval") / "labels" / "CT01" / "A" / "transcription.jsonl"
    assert not trans_path.exists()


def test_labelling_source_does_not_import_test_split_authorisation() -> None:
    package_dir = Path(__file__).resolve().parents[2] / "lemely" / "labelling"
    for path in package_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "authorize_test_split_join(" not in text
        assert "import lemely.eval.test_touch" not in text
        assert "from lemely.eval.test_touch" not in text

    # Run in a fresh interpreter: another test module already imported in
    # this same pytest session may have pulled in lemely.eval.test_touch for
    # unrelated reasons, which would make an in-process sys.modules check
    # pass or fail order-dependently rather than on this package's own merit.
    script = (
        "import sys\n"
        "import lemely.labelling.paper_data\n"
        "import lemely.labelling.records\n"
        "import lemely.labelling.server\n"
        "import lemely.labelling.verify\n"
        "assert 'lemely.eval.test_touch' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
