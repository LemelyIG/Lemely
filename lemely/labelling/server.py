"""Minimal localhost HTTP server for the two-pass blind labeller (spec §6).

Uses the stdlib ``http.server`` only — not the ``lemely/web/`` FastAPI/DB
session stack, which is a product surface this labeller must not depend on.

Routes:
  GET  /pass1?paper_id=...                       -> scan-region data only
  POST /pass1?paper_id=...&labeller_id=...        -> append a transcription record
  GET  /pass2?paper_id=...&labeller_id=...        -> mark scheme + own transcription
  POST /pass2?paper_id=...&labeller_id=...        -> append a marking record
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from lemely.eval.manifest import Split
from lemely.labelling.manifest_io import write_label_manifest
from lemely.labelling.paper_data import load_pass1_context, load_pass2_context
from lemely.labelling.records import append_marking_record, append_transcription_record

_DEFAULT_LABELLER_ID = "anonymous"


class LabellerRequestHandler(BaseHTTPRequestHandler):
    """Serves the pass-1 and pass-2 views/routes for one labelling session."""

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _query_params(self) -> tuple[str, str | None, str]:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        paper_id = qs.get("paper_id", [None])[0]
        labeller_id = qs.get("labeller_id", [_DEFAULT_LABELLER_ID])[0] or _DEFAULT_LABELLER_ID
        return parsed.path, paper_id, labeller_id

    def do_GET(self) -> None:  # noqa: N802 - stdlib http.server naming
        route, paper_id, labeller_id = self._query_params()
        if not paper_id:
            self._send_json(400, {"error": "paper_id is required"})
            return
        if route == "/pass1":
            self._send_json(200, load_pass1_context(paper_id))
            return
        if route == "/pass2":
            self._send_json(200, load_pass2_context(paper_id, labeller_id))
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib http.server naming
        route, paper_id, labeller_id = self._query_params()
        if not paper_id:
            self._send_json(400, {"error": "paper_id is required"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw_body) if raw_body else {}
        if route == "/pass1":
            record = append_transcription_record(paper_id, labeller_id, payload)
            self._send_json(201, record)
            return
        if route == "/pass2":
            record = append_marking_record(paper_id, labeller_id, payload)
            self._send_json(201, record)
            return
        self._send_json(404, {"error": "not found"})

    def log_message(self, format_str: str, *args: object) -> None:
        # Silence the default stderr access log — keep the labeller quiet.
        return


def create_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), LabellerRequestHandler)


def run_labeller(
    paper_id: str,
    *,
    split: Split,
    labeller_id: str,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Write the label manifest, then serve pass 1 / pass 2 for ``paper_id`` until stopped."""
    write_label_manifest(paper_id, split=split, labeller_id=labeller_id)
    server = create_server(host, port)
    print(  # noqa: T201 - CLI operator feedback, not library logging
        f"Labeller server for {paper_id} (labeller={labeller_id}, split={split}) "
        f"listening on http://{host}:{server.server_port}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
