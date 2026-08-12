#!/usr/bin/env python3
"""Ingest official CAIE grade-threshold tables into lemely/data/grade_boundaries.json.

Source: Cambridge International's own published grade-threshold-tables index
(cambridgeinternational.org) — the authoritative source, not a third-party mirror.
Fetches each published session's index page, finds the per-subject grade-threshold
PDF for 0580 (Mathematics), 0606 (Additional Mathematics), 0625 (Physics), downloads
it, and parses the per-component (paper+variant) raw-mark threshold table.

Idempotent / additive: re-running re-fetches the current session list and overwrites
matching keys; it never removes keys for sessions the site stops listing. Extending
coverage to older sessions later just means adding their slugs to SESSION_URL or
re-running once Cambridge's index grows.

Usage: python scripts/ingest_grade_boundaries.py [--dry-run]
"""

from __future__ import annotations

import argparse
import io
import json
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path
from typing import TypedDict

import pdfplumber


class _ComponentThresholds(TypedDict):
    max_mark: int
    thresholds: dict[str, int]


INDEX_URL = (
    "https://www.cambridgeinternational.org/programmes-and-qualifications/"
    "cambridge-upper-secondary/cambridge-igcse/grade-threshold-tables"
)
SESSION_INDEX_TMPL = (
    "https://www.cambridgeinternational.org/programmes-and-qualifications/"
    "cambridge-upper-secondary/cambridge-igcse/grade-threshold-tables/{slug}/index.aspx"
)
PDF_BASE = "https://cambridgeinternational.org"

SUBJECTS = ["0580", "0606", "0625"]

SESSION_SLUG_RE = re.compile(
    r'href="/programmes-and-qualifications/cambridge-upper-secondary/cambridge-igcse/'
    r'grade-threshold-tables/([a-z]+-\d{4})/index\.aspx"'
)
PDF_HREF_RE = re.compile(
    r"(?:https://cambridgeinternational\.org)?(/Images/[0-9]+-[a-z0-9-]+\.pdf)"
)

_SLUG_MONTH_TO_SESSION = {
    "june": "May/June",
    "november": "Oct/Nov",
    "march": "Feb/Mar",
}
_SESSION_TO_CODE = {"May/June": "m", "Oct/Nov": "w", "Feb/Mar": "s"}

DATA_PATH = Path(__file__).resolve().parent.parent / "lemely" / "data" / "grade_boundaries.json"
PROVENANCE_PATH = (
    Path(__file__).resolve().parent.parent / "lemely" / "data" / "grade_boundaries_provenance.json"
)

USER_AGENT = (
    "Lemely-ingest/1.0 (+https://github.com/LemelyIG/Lemely; educational grade-boundary ingestion)"
)


def _fetch(url: str, retries: int = 3) -> bytes:
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
                return bytes(resp.read())
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("unreachable: _fetch exhausted retries without an exception")


def discover_sessions() -> list[tuple[str, str, int]]:
    """Return (slug, session_month, session_year) for every session CAIE currently lists."""
    html = _fetch(INDEX_URL).decode("utf-8", errors="replace")
    sessions = []
    for slug in sorted(set(SESSION_SLUG_RE.findall(html))):
        month_word, year_str = slug.split("-")
        session_month = _SLUG_MONTH_TO_SESSION.get(month_word)
        if session_month is None:
            continue
        sessions.append((slug, session_month, int(year_str)))
    return sessions


def find_subject_pdfs(slug: str) -> dict[str, str]:
    """Return {subject_code: absolute_pdf_url} for whichever of SUBJECTS this session has."""
    url = SESSION_INDEX_TMPL.format(slug=slug)
    html = _fetch(url).decode("utf-8", errors="replace")
    found: dict[str, str] = {}
    for path in PDF_HREF_RE.findall(html):
        if "grade-threshold-table" not in path:
            continue
        for code in SUBJECTS:
            if f"-{code}-" in path and code not in found:
                found[code] = PDF_BASE + path
    return found


COMPONENT_RE = re.compile(r"^Component\s+(\d)(\d)\s+(\d+)\s+(.+)$")
# Two observed CAIE template layouts for the grade-letter header line:
#   older:  "mark A B C D E"        (letters follow "mark")
#   newer:  "Component A B C D E"   (letters follow "Component", "mark" is on its own line after)
GRADE_HEADER_RE = re.compile(r"^(?:mark|Component)\s+((?:[A-Z]\*?\s+)*[A-Z]\*?)$")


def parse_threshold_pdf(pdf_bytes: bytes) -> dict[str, _ComponentThresholds]:
    """Parse a grade-threshold PDF into {'p{paper}{variant}': {max_mark, thresholds}}."""
    components: dict[str, _ComponentThresholds] = {}
    grades: list[str] | None = None
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    for line in (raw.strip() for raw in text.splitlines()):
        header_match = GRADE_HEADER_RE.match(line)
        if header_match:
            grades = header_match.group(1).split()
            continue
        comp_match = COMPONENT_RE.match(line)
        if not comp_match or grades is None:
            continue
        paper_num, variant, max_mark, rest = comp_match.groups()
        values = rest.split()
        if len(values) != len(grades):
            continue
        # CAIE marks "not applicable at this tier" with an en dash (U+2013) or hyphen.
        not_applicable = ("\u2013", "-")
        thresholds = {
            g: int(v) for g, v in zip(grades, values, strict=True) if v not in not_applicable
        }
        components[f"p{paper_num}{variant}"] = {"max_mark": int(max_mark), "thresholds": thresholds}
    return components


def raw_to_percentage(thresholds: dict[str, int], max_mark: int) -> dict[str, float]:
    return {grade: round((mark / max_mark) * 100.0, 2) for grade, mark in thresholds.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Fetch and parse but don't write files"
    )
    args = parser.parse_args()

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    provenance: dict[str, dict[str, str | int]] = {}
    if PROVENANCE_PATH.exists():
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))

    exact = {k: v for k, v in data.items() if not k.startswith("_")}

    print("Discovering published grade-threshold sessions...", file=sys.stderr)
    sessions = discover_sessions()
    print(f"  found {len(sessions)} sessions: {[s[0] for s in sessions]}", file=sys.stderr)

    fetched, skipped = 0, 0
    for slug, session_month, session_year in sessions:
        try:
            subject_pdfs = find_subject_pdfs(slug)
        except Exception as exc:
            print(f"  [{slug}] index fetch failed: {exc}", file=sys.stderr)
            continue
        code = _SESSION_TO_CODE[session_month]
        yy = str(session_year)[-2:]
        for subject_code in SUBJECTS:
            pdf_url = subject_pdfs.get(subject_code)
            if pdf_url is None:
                skipped += 1
                continue
            try:
                pdf_bytes = _fetch(pdf_url)
                components = parse_threshold_pdf(pdf_bytes)
            except Exception as exc:
                print(f"  [{slug}/{subject_code}] fetch/parse failed: {exc}", file=sys.stderr)
                continue
            if not components:
                print(f"  [{slug}/{subject_code}] parsed zero components, skip", file=sys.stderr)
                continue
            for comp_key, comp in components.items():
                boundary_key = f"{subject_code}_{code}{yy}_{comp_key}"
                exact[boundary_key] = raw_to_percentage(comp["thresholds"], comp["max_mark"])
                provenance[boundary_key] = {
                    "source_url": pdf_url,
                    "session": f"{session_month} {session_year}",
                    "max_mark": comp["max_mark"],
                }
            fetched += 1
            time.sleep(0.3)  # be polite to the source

    print(f"Fetched {fetched} subject/session documents, {skipped} not published.", file=sys.stderr)

    # Recompute per-subject historical averages from every exact entry now on file.
    defaults: dict[str, dict[str, float]] = {}
    per_subject_grades: dict[str, dict[str, list[float]]] = {}
    for key, boundaries in exact.items():
        subject_code = key.split("_", 1)[0]
        bucket = per_subject_grades.setdefault(subject_code, {})
        for grade, pct in boundaries.items():
            bucket.setdefault(grade, []).append(pct)
    for subject_code, grade_values in per_subject_grades.items():
        defaults[subject_code] = {
            grade: round(statistics.mean(values), 2) for grade, values in grade_values.items()
        }

    data = {"_comment": data.get("_comment", "")}
    data.update(exact)
    data["_defaults"] = defaults
    data["_global"] = {"A": 80.0, "B": 70.0, "C": 60.0, "D": 50.0, "E": 40.0}

    print(f"Total exact entries: {len(exact)}; subjects with computed averages: {list(defaults)}")

    if args.dry_run:
        print("--dry-run: not writing files", file=sys.stderr)
        return 0

    DATA_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    PROVENANCE_PATH.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
