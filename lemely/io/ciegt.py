"""Client for the CIE Grade Thresholds Database (ciegt.pooruli.com).

Supplies component threshold rows and the index of which sessions exist. Its
numbers are verified against the official Cambridge PDFs by
``scripts/ingest_thresholds.py`` before they are stored, because the site is an
unaffiliated transcription and these numbers decide real grades: a measured
comparison of 57 records found 51 exact matches and 6 rows in 0606 carrying F
and G grades the official document does not publish at all.

No browser is involved. The site is a SvelteKit app, but its data route serves
JSON directly, so this is plain ``urllib``.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any

from lemely.db.models.enums import SessionMonth
from lemely.runtime.errors import ExternalServiceError

_BASE = "https://ciegt.pooruli.com"
_PAPACAMBRIDGE = "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload"
_USER_AGENT = (
    "Lemely-ingest/1.0 (+https://github.com/LemelyIG/Lemely; educational grade-boundary ingestion)"
)
_TIMEOUT_SECONDS = 60.0

#: ciegt's session labels → our enum plus the short code CAIE uses in filenames.
_SESSIONS: dict[str, tuple[SessionMonth, str]] = {
    "M/J": (SessionMonth.may_june, "s"),
    "O/N": (SessionMonth.oct_nov, "w"),
    "F/M": (SessionMonth.feb_mar, "m"),
}

#: The payload marks "not available at this tier" as -1, mirroring the en dash
#: the PDF prints. An absence, never a threshold.
_NOT_APPLICABLE = -1

_GRADES = ("A", "B", "C", "D", "E", "F", "G")


@dataclass(frozen=True, slots=True)
class ComponentRow:
    """One component's thresholds for one session, as ciegt reports them."""

    subject_code: str
    session_month: SessionMonth
    session_year: int
    paper_number: int
    paper_variant: int
    max_mark: int
    thresholds: dict[str, int]
    source_url: str


def parse_session_label(label: str) -> tuple[SessionMonth, int]:
    """``"M/J 24"`` → ``(SessionMonth.may_june, 2024)``.

    Raises rather than guessing on an unknown label: a mis-parsed session
    silently files a paper's thresholds under the wrong year, which surfaces as
    a wrong grade rather than as an error.
    """
    try:
        prefix, year = label.rsplit(" ", 1)
        month, _code = _SESSIONS[prefix]
        return month, 2000 + int(year)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Unrecognised session label: {label!r}") from exc


def parse_component(component: str) -> tuple[int, int]:
    """``"11"`` → ``(1, 1)``; ``"50"`` → ``(5, 0)``; ``"1"`` → ``(1, 0)``.

    A single-digit component is an unvaried paper, which we store as variant 0
    rather than inventing variant 1.
    """
    if len(component) == 1:
        return int(component), 0
    return int(component[0]), int(component[1])


def session_filename_code(month: SessionMonth, year: int) -> str:
    """``(may_june, 2024)`` → ``"s24"`` — CAIE's own filename convention."""
    code = next(c for m, c in _SESSIONS.values() if m is month)
    return f"{code}{year % 100:02d}"


def gt_pdf_url(subject_code: str, month: SessionMonth, year: int) -> str:
    """The official grade-threshold PDF for one syllabus and session."""
    return f"{_PAPACAMBRIDGE}/{subject_code}_{session_filename_code(month, year)}_gt.pdf"


def ciegt_page_url(subject_code: str, *, qualification: str = "igcse") -> str:
    """The human-checkable ciegt page for one syllabus.

    Distinct from the ``__data.json`` route :func:`fetch_rows` calls: this is a
    page a person can open in a browser. It is the honest ``source_url`` for a
    row the official PDF never confirmed — naming Cambridge for a number
    Cambridge was never checked against would misattribute it.
    """
    return f"{_BASE}/{qualification}/{subject_code}"


def _unflatten(pool: list[Any], index: Any) -> Any:
    """Resolve one devalue index into a plain Python value.

    A number *inside* a dict or list is an index into ``pool``; a number found
    *in* ``pool`` is a literal. That asymmetry is the whole format. Negative
    indices are devalue's sentinels (``-1`` undefined, ``-2`` a hole).
    """
    if isinstance(index, int) and index < 0:
        return None
    value = pool[index]
    if isinstance(value, dict):
        return {k: _unflatten(pool, i) for k, i in value.items()}
    if isinstance(value, list):
        return [_unflatten(pool, i) for i in value]
    return value


def decode_devalue(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the threshold table from a decoded ``__data.json`` payload."""
    for node in payload.get("nodes", []):
        if node.get("type") != "data":
            continue
        root = _unflatten(node["data"], 0)
        if isinstance(root, dict) and "table" in root:
            table = root["table"]
            if isinstance(table, list):
                return table
    raise ExternalServiceError("ciegt payload carried no threshold table")


def rows_from_payload(payload: dict[str, Any], subject_code: str) -> list[ComponentRow]:
    """Decode a payload into typed rows, dropping the -1 sentinel."""
    rows: list[ComponentRow] = []
    for raw in decode_devalue(payload):
        month, year = parse_session_label(raw["session"])
        number, variant = parse_component(str(raw["component"]))
        rows.append(
            ComponentRow(
                subject_code=subject_code,
                session_month=month,
                session_year=year,
                paper_number=number,
                paper_variant=variant,
                max_mark=int(raw["max"]),
                thresholds={
                    grade: int(raw[grade])
                    for grade in _GRADES
                    if raw.get(grade) not in (None, _NOT_APPLICABLE)
                },
                source_url=gt_pdf_url(subject_code, month, year),
            )
        )
    return rows


def fetch_rows(subject_code: str, *, qualification: str = "igcse") -> list[ComponentRow]:
    """Fetch and decode one syllabus's rows. One request per syllabus."""
    url = f"{_BASE}/{qualification}/{subject_code}/__data.json"
    request = urllib.request.Request(  # noqa: S310 - fixed https host
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
            payload = json.loads(response.read().decode())
    except (OSError, ValueError) as exc:
        raise ExternalServiceError(f"ciegt fetch failed for {subject_code}: {exc}") from exc
    return rows_from_payload(payload, subject_code)
