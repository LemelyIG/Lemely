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

from pydantic import ValidationError

from lemely.labelling.manifest_io import write_label_manifest
from lemely.labelling.pages import render_pass1_page, render_pass2_page
from lemely.labelling.paper_data import (
    load_pass1_context,
    load_pass2_context,
    question_mark_point_ids,
    read_scan_image,
)
from lemely.labelling.paths import InvalidIdentifierError
from lemely.labelling.records import append_marking_record, append_transcription_record

if TYPE_CHECKING:
    from lemely.eval.manifest import Split

_LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}

# Marking-record fields that must be coerced to something other than the raw
# string every form-urlencoded field arrives as. Downstream consumers (e.g.
# EvalRecord/analyses.py's ``predicted_marks``-style fields, and the golden
# JSON payloads used throughout this test suite) treat this as a number.
_INT_FIELDS = {"awarded_marks"}

# Rendered as several ``<input type="checkbox" name="mark_point_id"
# value="...">`` sharing one name (the spec §6 pass-2 mark-point checkboxes,
# see pages.py) — a real browser submits these as repeated
# ``mark_point_id=p1&mark_point_id=p3`` pairs, which ``parse_qs`` already
# groups into a list. Every other form field is collapsed to its first value
# (``_parse_request_body``'s form branch); this one must not be, or only the
# first checked mark point would ever survive.
_MARK_POINT_ID_FIELD = "mark_point_id"
_MULTI_VALUE_FIELDS = {_MARK_POINT_ID_FIELD}


class _BadRequestError(ValueError):
    """Raised for a request body that cannot be turned into a payload dict.

    Distinct from :class:`~lemely.labelling.paths.InvalidIdentifierError`
    (which is about a bad ``paper_id``/``labeller_id``/scan name) — this is
    about the POST *body* itself: malformed JSON, a Content-Type this server
    does not understand, or a field that fails its required coercion.
    """


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

    def _query_param(self, key: str) -> str | None:
        qs = parse_qs(urlparse(self.path).query)
        return qs.get(key, [None])[0]

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def _parse_request_body(self) -> dict[str, object]:
        """Turn the POST body into a payload dict, or raise ``_BadRequestError``.

        Handles both a real browser's form submit
        (``application/x-www-form-urlencoded``, what every ``<form>`` in
        :mod:`lemely.labelling.pages` actually sends) and a programmatic
        JSON client. An unrecognised or absent ``Content-Type`` is rejected
        outright rather than guessed at — silently defaulting to JSON here
        is exactly what let a real form-urlencoded submission reach
        ``json.loads`` unguarded and drop the connection with no response.
        """
        content_type = self.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        raw_body = self._read_body()

        if media_type == "application/json":
            if not raw_body:
                return {}
            try:
                json_payload: object = json.loads(raw_body)
            except json.JSONDecodeError as exc:
                raise _BadRequestError(f"malformed JSON body: {exc}") from exc
            if not isinstance(json_payload, dict):
                raise _BadRequestError("JSON body must be an object")
            return json_payload

        if media_type == "application/x-www-form-urlencoded":
            parsed = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
            form_payload: dict[str, object] = {
                name: (values if name in _MULTI_VALUE_FIELDS else values[0])
                for name, values in parsed.items()
            }
            for field in _INT_FIELDS & form_payload.keys():
                try:
                    form_payload[field] = int(str(form_payload[field]))
                except ValueError as exc:
                    raise _BadRequestError(f"{field!r} must be an integer") from exc
            return form_payload

        raise _BadRequestError(f"unsupported or missing Content-Type: {content_type!r}")

    def _build_marking_payload(
        self, paper_id: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """Turn the raw pass-2 POST payload into the spec §6 output contract.

        Checkbox presence (repeated ``mark_point_id`` values) becomes an
        explicit True/False verdict for every mark point the mark scheme
        actually has for this question — the full set of point ids is
        loaded from the mark scheme itself (never trusted from the client),
        so an unticked box is recorded as an explicit False rather than a
        silently missing key. A checked id that is not one of the
        question's real mark points is rejected rather than silently kept
        or dropped.
        """
        question_id = payload.get("question_id")
        if not isinstance(question_id, str) or not question_id:
            raise _BadRequestError("question_id is required")

        point_ids = question_mark_point_ids(paper_id, question_id)

        checked_raw = payload.pop(_MARK_POINT_ID_FIELD, [])
        if isinstance(checked_raw, str):
            checked = [checked_raw]
        elif isinstance(checked_raw, list):
            checked = [str(item) for item in checked_raw]
        else:
            raise _BadRequestError(f"{_MARK_POINT_ID_FIELD!r} must be a string or list of strings")

        unknown = set(checked) - set(point_ids)
        if unknown:
            raise _BadRequestError(
                f"checked mark point(s) {sorted(unknown)} are not part of question {question_id!r}"
            )

        payload["mark_point_verdicts"] = {point_id: point_id in checked for point_id in point_ids}
        return payload

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
                question_id = self._query_param("question_id")
                context = load_pass2_context(
                    paper_id, self.server.labeller_id, question_id=question_id
                )
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
        try:
            payload = self._parse_request_body()
        except _BadRequestError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        try:
            if route == "/pass1":
                record = append_transcription_record(paper_id, self.server.labeller_id, payload)
                self._send_json(201, record)
                return
            if route == "/pass2":
                payload = self._build_marking_payload(paper_id, payload)
                record = append_marking_record(paper_id, self.server.labeller_id, payload)
                self._send_json(201, record)
                return
        except InvalidIdentifierError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except _BadRequestError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except ValidationError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except FileNotFoundError as exc:
            self._send_json(404, {"error": str(exc)})
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
