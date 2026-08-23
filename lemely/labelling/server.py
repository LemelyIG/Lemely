"""Minimal localhost HTTP server for the two-pass blind labeller (spec §6).

Uses the stdlib ``http.server`` only — not the ``lemely/web/`` FastAPI/DB
session stack, which is a product surface this labeller must not depend on.

Routes:
  GET  /pass1?paper_id=...                -> pass-1 HTML page (scan images + form)
  POST /pass1?paper_id=...                -> append a transcription record
  GET  /pass2?paper_id=...                -> pass-2 HTML page (mark scheme + form)
  POST /pass2?paper_id=...                -> append a marking record
  GET  /scan?paper_id=...&name=...        -> scan-region image bytes

``labeller_id`` and ``split`` are bound into the server at construction time
from :func:`run_labeller`'s (CLI-supplied) arguments and never re-read from
the request — a client-supplied ``labeller_id`` query parameter would let
records land under an identity that never appears in ``manifest.json``,
defeating spec §6's identity/split attribution.

Every request is checked against ``Host``/``Origin`` before it is handled at
all: this server is unauthenticated by design (it is a local labelling tool,
not a product surface), so the only thing standing between it and an
unrelated page in the labeller's browser issuing cross-origin writes is
refusing anything that doesn't look like it came from this machine.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from lemely.labelling.manifest_io import write_label_manifest
from lemely.labelling.pages import render_pass1_page, render_pass2_page
from lemely.labelling.paper_data import load_pass1_context, load_pass2_context, read_scan_image
from lemely.labelling.paths import InvalidIdentifierError
from lemely.labelling.records import append_marking_record, append_transcription_record

if TYPE_CHECKING:
    from lemely.eval.manifest import Split

_LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}


def _hostname_is_local(netloc: str) -> str:
    """Extract the bare hostname from a ``Host``/``Origin``-style value."""
    return netloc[1:].split("]", 1)[0] if netloc.startswith("[") else netloc.split(":", 1)[0]


class LabellerHTTPServer(ThreadingHTTPServer):
    """Carries the identity that every handled request is attributed to.

    ``labeller_id``/``split`` live here, bound once at construction from the
    CLI's ``--labeller-id``/``--split`` — never re-derived from a request.
    """

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        labeller_id: str,
        split: Split,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.labeller_id = labeller_id
        self.split = split


class LabellerRequestHandler(BaseHTTPRequestHandler):
    """Serves the pass-1 and pass-2 views/routes for one labelling session."""

    server: LabellerHTTPServer  # narrows the stdlib base class's generic attribute

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status: int, content_type: str, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _request_is_local(self) -> bool:
        """Reject anything whose Host or Origin doesn't look like this machine.

        ``Host`` guards DNS-rebinding style attacks (a page navigates the
        browser to a hostname that resolves to 127.0.0.1, but the browser
        still sends the original ``Host`` header). ``Origin`` guards
        ordinary cross-origin fetch/XHR from any other page open in the
        labeller's browser.
        """
        host_header = self.headers.get("Host")
        if not host_header or _hostname_is_local(host_header) not in _LOCAL_HOSTNAMES:
            return False
        origin_header = self.headers.get("Origin")
        if origin_header is not None:
            origin_netloc = urlparse(origin_header).netloc or origin_header
            if _hostname_is_local(origin_netloc) not in _LOCAL_HOSTNAMES:
                return False
        return True

    def _query_params(self) -> tuple[str, str | None, str | None]:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        paper_id = qs.get("paper_id", [None])[0]
        name = qs.get("name", [None])[0]
        return parsed.path, paper_id, name

    def do_GET(self) -> None:
        if not self._request_is_local():
            self._send_json(403, {"error": "cross-origin or non-local request rejected"})
            return
        route, paper_id, name = self._query_params()
        if not paper_id:
            self._send_json(400, {"error": "paper_id is required"})
            return
        try:
            if route == "/pass1":
                context = load_pass1_context(paper_id)
                self._send_html(200, render_pass1_page(context))
                return
            if route == "/pass2":
                context = load_pass2_context(paper_id, self.server.labeller_id)
                self._send_html(200, render_pass2_page(context))
                return
            if route == "/scan":
                if not name:
                    self._send_json(400, {"error": "name is required"})
                    return
                content_type, data = read_scan_image(paper_id, name)
                self._send_bytes(200, content_type, data)
                return
        except InvalidIdentifierError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except FileNotFoundError as exc:
            self._send_json(404, {"error": str(exc)})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._request_is_local():
            self._send_json(403, {"error": "cross-origin or non-local request rejected"})
            return
        route, paper_id, _name = self._query_params()
        if not paper_id:
            self._send_json(400, {"error": "paper_id is required"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw_body) if raw_body else {}
        try:
            if route == "/pass1":
                record = append_transcription_record(paper_id, self.server.labeller_id, payload)
                self._send_json(201, record)
                return
            if route == "/pass2":
                record = append_marking_record(paper_id, self.server.labeller_id, payload)
                self._send_json(201, record)
                return
        except InvalidIdentifierError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(404, {"error": "not found"})

    def log_message(self, format_str: str, *args: object) -> None:
        # Silence the default stderr access log — keep the labeller quiet.
        return


def create_server(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    labeller_id: str = "anonymous",
    split: Split | None = None,
) -> LabellerHTTPServer:
    resolved_split: Split = split if split is not None else "train"
    return LabellerHTTPServer(
        (host, port), LabellerRequestHandler, labeller_id=labeller_id, split=resolved_split
    )


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
    server = create_server(host, port, labeller_id=labeller_id, split=split)
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
