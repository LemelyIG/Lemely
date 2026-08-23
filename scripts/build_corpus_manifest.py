#!/usr/bin/env python3
"""#44 (M2.1): build the committed corpus-manifest artifact from the PaperScraper catalogue.

Reads the PaperScraper catalogue (a SQLite DB maintained by the separate
``PaperScraper`` tool at ``/home/sico/PaperScraper``, **outside** this repo —
see ``BUILD/corpus/README.md``) **read-only** and emits a JSON manifest
recording, as data: a deterministic digest over the ``done`` rows, counts by
subject/doc_type, the session/topical split, the per-topic table for 0625,
the coverage check (question papers with no matching mark scheme), and the
one known failed document.

This script never fetches anything and never writes to the catalogue. It
only reads rows that ``paperscraper fetch`` already downloaded and recorded
elsewhere.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = Path("/home/sico/PaperScraper/papers/index.db")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "BUILD" / "corpus"

# The three human-approved commands run under closed issue #48 to produce
# this catalogue state (scope approved in #48's comment thread; run without
# --dry-run/-o once confirmed). Recorded here (not re-run) purely as
# provenance.
APPROVED_FETCH_COMMANDS = [
    "paperscraper fetch -s 0580 -s 0606 -s 0625 --qual IGCSE --only-papers --from 2019",
    "paperscraper fetch -s 0580 -s 0606 -s 0625 --qual IGCSE -t gt",
    "paperscraper fetch --source pmt -s 0625 --only-topical",
]
APPROVAL_ISSUE = "#48 (closed, human-approved scope for #44 M2.1)"


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open ``db_path`` strictly read-only via a ``file:`` URI.

    Uses ``mode=ro`` so a bug in this script cannot mutate the catalogue —
    SQLite refuses any write attempt at the driver level, not just by
    convention.
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _done_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Fetch every ``status='done'`` row from ``documents``, as plain dicts.

    Selects only the columns this script actually uses (inspecting the
    schema first rather than assuming), so a catalogue with a narrower
    ``documents`` table than expected fails loudly instead of silently
    hashing fewer fields than intended.
    """
    columns = _table_columns(conn, "documents")
    required = {"key", "subject_code", "doc_type", "session_code", "paper", "filename"}
    missing = required - columns
    if missing:
        raise SystemExit(
            f"build_corpus_manifest: documents table is missing required columns: {sorted(missing)}"
        )
    has_checksum = "checksum" in columns
    has_topical = "topical" in columns
    select_cols = ["key", "subject_code", "doc_type", "session_code", "paper", "filename"]
    if has_checksum:
        select_cols.append("checksum")
    if has_topical:
        select_cols.append("topical")
    sql = f"SELECT {', '.join(select_cols)} FROM documents WHERE status = 'done'"  # noqa: S608
    return [dict(row) for row in conn.execute(sql)]


def _sort_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("subject_code") or ""),
        str(row.get("doc_type") or ""),
        str(row.get("session_code") or ""),
        str(row.get("paper") or ""),
        str(row.get("filename") or ""),
    )


def compute_corpus_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    """Digest of the exact set of ``done`` catalogue rows behind this manifest.

    Mirrors ``lemely.accuracy.harness._corpus_digest``, which does the
    equivalent job for the golden corpus: derived from what was actually
    read — each row's identifying fields (``subject_code``, ``doc_type``,
    ``session_code``, ``paper``, ``filename``) plus its ``checksum`` when the
    column exists — not a placeholder. Rows are sorted by a stable key
    first, so row order returned by SQLite (which is not guaranteed) cannot
    change the digest. Two runs over an unchanged catalogue reproduce the
    same digest; any row added, removed, or changed (including a
    re-downloaded file landing with a different ``checksum``) changes it.
    """
    h = hashlib.sha256()
    for row in sorted(rows, key=_sort_key):
        fields = [
            str(row.get("subject_code") or ""),
            str(row.get("doc_type") or ""),
            str(row.get("session_code") or ""),
            str(row.get("paper") or ""),
            str(row.get("filename") or ""),
            str(row.get("checksum") or ""),
        ]
        h.update("|".join(fields).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:16]


def _counts_by_subject_doctype(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.get("subject_code") or ""), str(row.get("doc_type") or ""))
        counts[key] = counts.get(key, 0) + 1
    return [
        {"subject_code": subject, "doc_type": doc_type, "count": count}
        for (subject, doc_type), count in sorted(counts.items())
    ]


def _session_topical_split(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    session = sum(1 for row in rows if not row.get("topical"))
    topical = sum(1 for row in rows if row.get("topical"))
    return {"session": session, "topical": topical}


def _topic_table(conn: sqlite3.Connection, subject_code: str) -> list[dict[str, Any]]:
    """Per-topic document counts for ``subject_code``.

    Reads from the ``topics``/``document_topics`` join tables, restricted to
    ``done`` documents.
    """
    sql = """
        SELECT t.unit AS unit, t.slug AS slug, COUNT(DISTINCT d.key) AS count
        FROM topics t
        JOIN document_topics dt ON dt.topic_id = t.id
        JOIN documents d ON d.key = dt.key
        WHERE t.subject_code = ? AND d.status = 'done'
        GROUP BY t.unit, t.slug
        ORDER BY t.unit
    """
    return [dict(row) for row in conn.execute(sql, (subject_code,))]


def _coverage_check(conn: sqlite3.Connection) -> int:
    """Count of question papers with no matching mark scheme.

    Counts ``(subject_code, session_code, paper)`` triples that have a
    ``done`` question paper but no ``done`` mark scheme. Zero means every
    fetched question paper has a matching mark scheme.
    """
    sql = """
        SELECT COUNT(*) FROM (
            SELECT subject_code, session_code, paper FROM documents
                WHERE status='done' AND doc_type='qp'
            EXCEPT
            SELECT subject_code, session_code, paper FROM documents
                WHERE status='done' AND doc_type='ms'
        )
    """
    (count,) = conn.execute(sql).fetchone()
    return int(count)


def _failed_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    columns = _table_columns(conn, "documents")
    select_cols = ["key", "filename", "subject_code", "doc_type", "source", "attempts", "error"]
    select_cols = [c for c in select_cols if c in columns]
    sql = f"SELECT {', '.join(select_cols)} FROM documents WHERE status = 'failed'"  # noqa: S608
    return [dict(row) for row in conn.execute(sql)]


def build_manifest(db_path: Path) -> dict[str, Any]:
    """Build the full corpus-manifest dict by reading ``db_path`` read-only."""
    conn = _connect_readonly(db_path)
    try:
        (total_done,) = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE status='done'"
        ).fetchone()
        (total_failed,) = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE status='failed'"
        ).fetchone()
        rows = _done_rows(conn)
        digest = compute_corpus_digest(rows)
        counts = _counts_by_subject_doctype(rows)
        split = _session_topical_split(rows)
        topics_0625 = _topic_table(conn, "0625")
        qp_without_ms = _coverage_check(conn)
        failed = _failed_documents(conn)
    finally:
        conn.close()

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus_digest": digest,
        "totals": {"done": int(total_done), "failed": int(total_failed)},
        "counts_by_subject_doctype": counts,
        "session_topical_split": split,
        "topics_0625": topics_0625,
        "coverage_check": {
            "qp_without_matching_ms": qp_without_ms,
            "passed": qp_without_ms == 0,
        },
        "failed_documents": failed,
        "provenance": {
            "catalogue_path": str(db_path),
            "approved_fetch_commands": APPROVED_FETCH_COMMANDS,
            "approval": APPROVAL_ISSUE,
            "note": (
                "Fetch already complete at time of manifest generation; this script "
                "only reads the catalogue, it never invokes `paperscraper fetch`."
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to the PaperScraper catalogue SQLite DB (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Output JSON path (default: BUILD/corpus/corpus-manifest-<UTC date>.json "
            "under the repo root)"
        ),
    )
    args = parser.parse_args(argv)

    if not args.db_path.is_file():
        print(f"build_corpus_manifest: catalogue not found at {args.db_path}", file=sys.stderr)
        return 1

    manifest = build_manifest(args.db_path)

    output = args.output
    if output is None:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        output = DEFAULT_OUTPUT_DIR / f"corpus-manifest-{date_str}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    output.write_text(text, encoding="utf-8")

    print(
        f"corpus-manifest: digest={manifest['corpus_digest']} done={manifest['totals']['done']} "
        f"failed={manifest['totals']['failed']} -> {output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
