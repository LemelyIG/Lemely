"""The deterministic parse of a user's mark-scheme PDF, run in a worker (#260).

:class:`~lemely.io.det.DeterministicMarkSchemeParser` reads the PDF with
pdfplumber (pdfminer.six), which inflates every content stream it walks with
no bound of its own: a 204 KB scheme whose one page inflates to 200 MiB took
the parse from 253 to 669 MiB resident, in the web process, on the event
loop of ``POST /api/schemes`` (final review R3, I3). Every user scheme PDF is
therefore parsed in :data:`~lemely.runtime.sandbox.EXTRACTION_WORKER`, a
memory-limited child killed past its timeout:

* ``POST /api/schemes`` calls :func:`parse_scheme_in_worker` off the event
  loop, within ``scheme_parse_timeout_seconds``, and maps every failure to a
  fixed message (``teacher.upload_scheme``).
* A scheme uploaded alongside a scan is parsed in the grading thread by
  :class:`WorkerSchemeParser`, the deterministic half of the
  ``ChainedMarkSchemeParser`` both portals build, within
  ``scheme_parse_timeout_seconds`` too.

The child imports this module and runs :func:`parse_scheme_pdf`
(:data:`SCHEME_PARSE_TARGET`). The parser is imported inside it, so the web
process, which imports this module for the caller side, never loads
pdfplumber for it. What crosses the pipe is small and picklable: the bytes,
the client filename (the parser reads the paper's identity from a CAIE-style
name) and the parser settings (a pydantic model) going in, the parsed
:class:`~lemely.core.loose_schemas.MarkScheme` coming back. A
:class:`~lemely.runtime.errors.ParseError` crosses intact (a ``LemelyError``),
so a scheme the deterministic parser cannot read still reaches the Gemini
fallback; any other exception becomes a
:class:`~lemely.runtime.sandbox.SandboxError`.

Measured 2026-10-05 (Linux 7.2, CPython 3.13, pdfplumber 0.11.10; ``VmData``
sampled every 5 ms, MiB): the child idles at 37 with the parser imported. The
four 0625 schemes in ``Sources/`` (10-21 pages) peak at 47-71 in 0.14-0.44 s;
synthetic theory schemes of 8, 42 and 102 pages at 43, 79 and 149 in 0.10,
0.69 and 1.68 s. The reviewer's 204 KB bomb (one page inflating to 200 MiB)
peaks at 475 and fails to parse (``ParseError``) in 1.3 s; inflating to
1 GiB, it needs 2133 unbounded and, under the worker's 640 MiB, fails with
pdfminer's ``MemoryError`` (a ``SandboxError``) in 1.0 s.

The memory limit does not bound pdfplumber's CPU time. Table finding is
superlinear in a page's ruling lines and nothing caps the page count: a
16.8 KB single page of a 100 x 100 line grid parses in 2.1 s, and the same
page ten times over (29.4 KB) in 21.4 s, linear at about 2.1 s a page, so
about 140 KB would outlast the extraction worker's 180 s (final review R4,
I2). Both paths therefore use ``scheme_parse_timeout_seconds`` (20 s) and not
the extraction timeout, which would hold the shared worker, and with it every
scan check and render, for minutes. Real schemes take under 2 s.

The scan pre-scan (:func:`~lemely.io.scan_limits.check_scan_bytes`) is not
applied. It bounds what MuPDF and pdfium would do with a file, not pdfminer,
which repairs and walks a PDF its own way, so it would add two readers'
opens without bounding the third; and its scan rules would refuse real
schemes, :data:`~lemely.io.scan_limits.MAX_SCAN_PAGES` (40 pages) first
among them. The worker's limits are the bound.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from lemely.core.loose_schemas import MarkScheme
from lemely.runtime import sandbox
from lemely.runtime.errors import LemelyError

if TYPE_CHECKING:
    from lemely.runtime.config import DetParserSettings

__all__ = [
    "SCHEME_PARSE_TARGET",
    "SCHEME_READ_FAILED_MESSAGE",
    "SchemeReadFailedError",
    "WorkerSchemeParser",
    "parse_scheme_in_worker",
    "parse_scheme_pdf",
]

log = structlog.get_logger(__name__)

#: The worker's name for :func:`parse_scheme_pdf`. Read at each call, so a
#: test can point it at a stand-in target.
SCHEME_PARSE_TARGET = "lemely.io.scheme_parse.parse_scheme_pdf"

#: What a user is told when their mark scheme could not be read, whatever the
#: cause: the parser's refusal, an unreadable file, or a worker failure.
SCHEME_READ_FAILED_MESSAGE = "Could not read this mark scheme"

#: The name the PDF is parsed under when the client sent none worth keeping.
_FALLBACK_NAME = "scheme.pdf"


class SchemeReadFailedError(LemelyError):
    """The worker could not parse a scheme; ``str()`` is :data:`SCHEME_READ_FAILED_MESSAGE`.

    Both grading flows show a failure's ``str()`` to the user (the student's
    SSE error frame, the teacher's failed row), so the worker's own failure
    travels only as ``__cause__`` and on the ``scheme_parse_failed`` log
    line. Pickles as :class:`~lemely.io.rasterise.ScanRenderFailedError`
    does: ``__init__`` accepts and ignores the ``args`` it is rebuilt from.
    """

    def __init__(self, *_: object) -> None:
        super().__init__(SCHEME_READ_FAILED_MESSAGE)


def parse_scheme_pdf(data: bytes, filename: str, cfg: DetParserSettings) -> MarkScheme:
    """Parse the mark-scheme PDF ``data`` deterministically, as if saved as ``filename``.

    The worker's target. ``filename`` is reduced to its basename here as well
    as by the caller: the parser reads the paper's identity from a CAIE-style
    name (``0625_s23_ms_11.pdf``) and records it as the scheme's
    ``source_document``, so it must be the client's name, but it is never a
    path. The file lives in a private temporary directory for the parse only.

    Raises :class:`~lemely.runtime.errors.ParseError` for a scheme the parser
    cannot read; whatever pdfplumber raises for bytes it cannot open
    propagates.
    """
    from lemely.io.det import DeterministicMarkSchemeParser

    name = Path(filename).name
    if name in {"", ".", ".."}:
        name = _FALLBACK_NAME
    with tempfile.TemporaryDirectory(prefix="lemely-scheme-") as tmp:
        pdf_path = Path(tmp) / name
        pdf_path.write_bytes(data)
        return DeterministicMarkSchemeParser(cfg=cfg)(pdf_path)


def parse_scheme_in_worker(
    data: bytes, filename: str, cfg: DetParserSettings, *, timeout: float
) -> MarkScheme:
    """:func:`parse_scheme_pdf` run in :data:`~lemely.runtime.sandbox.EXTRACTION_WORKER`.

    Blocks for up to ``timeout`` seconds, counting any wait for a scan
    extraction already running there; call it off the event loop. Raises the
    parser's :class:`~lemely.runtime.errors.ParseError` as it was raised, or
    a :class:`~lemely.runtime.sandbox.SandboxFailure`. With the sandbox
    disabled the parse runs in this process, and its exceptions propagate
    unchanged.
    """
    return sandbox.EXTRACTION_WORKER.call(
        SCHEME_PARSE_TARGET, data, filename, cfg, timeout=timeout, result_type=MarkScheme
    )


class WorkerSchemeParser:
    """``Path -> MarkScheme``: the deterministic parse of a scheme file, in the worker.

    The primary of the ``ChainedMarkSchemeParser`` that parses a scheme
    uploaded alongside a scan. A :class:`~lemely.runtime.errors.ParseError`
    propagates, so the chain hands the scheme to Gemini as before. A worker
    failure is logged (``scheme_parse_failed``, with its reason and text)
    and raised as :class:`SchemeReadFailedError`, whose text a user may see:
    it is not a ``ParseError``, so a file that ran the worker out of memory
    or time is never sent on to Gemini.
    """

    def __init__(self, cfg: DetParserSettings) -> None:
        self._cfg = cfg

    def __call__(self, pdf_path: Path) -> MarkScheme:
        data = pdf_path.read_bytes()
        try:
            return parse_scheme_in_worker(
                data,
                pdf_path.name,
                self._cfg,
                timeout=sandbox.sandbox_settings().scheme_parse_timeout_seconds,
            )
        except sandbox.SandboxFailure as exc:
            log.warning(
                "scheme_parse_failed", reason=exc.reason, error=str(exc), byte_size=len(data)
            )
            raise SchemeReadFailedError from exc
