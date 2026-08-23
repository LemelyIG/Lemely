"""#44 (M2.1): ``scripts/build_corpus_manifest.py`` digest determinism/sensitivity.

Builds a small temporary SQLite fixture shaped like the PaperScraper
catalogue (``documents``/``topics``/``document_topics``) rather than
depending on the real catalogue at ``/home/sico/PaperScraper/papers/index.db``
— that DB lives outside this repo and is not reproducible in CI.

Proves the two properties the manifest's provenance value depends on:
unchanged corpus -> same digest across repeated computation, and any
added/removed/changed ``done`` row -> a different digest. Without this, a
silently-corrupted catalogue snapshot could be committed with a digest that
no longer means anything.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_corpus_manifest.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_corpus_manifest_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


_SCHEMA = """
CREATE TABLE documents (
    key            TEXT PRIMARY KEY,
    board          TEXT NOT NULL,
    subject_code   TEXT,
    session_code   TEXT,
    doc_type       TEXT,
    paper          TEXT,
    filename       TEXT,
    checksum       TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',
    attempts       INTEGER NOT NULL DEFAULT 0,
    error          TEXT,
    source         TEXT,
    topical        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE topics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_code  TEXT NOT NULL,
    slug          TEXT NOT NULL,
    label         TEXT NOT NULL,
    unit          INTEGER,
    source        TEXT NOT NULL DEFAULT ''
);
CREATE TABLE document_topics (
    key       TEXT NOT NULL,
    topic_id  INTEGER NOT NULL,
    PRIMARY KEY (key, topic_id)
);
"""


def _make_db(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA)
        conn.executemany(
            "INSERT INTO documents "
            "(key, board, subject_code, session_code, doc_type, paper, filename, checksum, status, "
            "attempts, error, source, topical) "
            "VALUES (?, 'CAIE', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


_BASE_ROWS = [
    ("k1", "0580", "s24", "qp", "1", "0580_s24_qp_1.pdf", "aaa111", "done", 1, None, "gceguide", 0),
    ("k2", "0580", "s24", "ms", "1", "0580_s24_ms_1.pdf", "bbb222", "done", 1, None, "gceguide", 0),
    ("k3", "0625", "nosession", "qp", "0", "Motion.pdf", "ccc333", "done", 1, None, "pmt", 1),
    (
        "k4",
        "0625",
        "nosession",
        "qp",
        "0",
        "Broken.pdf",
        None,
        "failed",
        2,
        "not a valid PDF",
        "pmt",
        1,
    ),
]


def test_digest_is_deterministic_across_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "index.db"
    _make_db(db_path, _BASE_ROWS)

    conn1 = mod._connect_readonly(db_path)
    rows1 = mod._done_rows(conn1)
    conn1.close()
    digest1 = mod.compute_corpus_digest(rows1)

    conn2 = mod._connect_readonly(db_path)
    rows2 = mod._done_rows(conn2)
    conn2.close()
    digest2 = mod.compute_corpus_digest(rows2)

    assert digest1 == digest2
    assert len(digest1) == 16


def test_digest_is_order_independent(tmp_path: Path) -> None:
    """Row order returned by SQLite is not guaranteed; the digest must not depend on it."""
    forward = tmp_path / "forward.db"
    reversed_ = tmp_path / "reversed.db"
    _make_db(forward, _BASE_ROWS)
    _make_db(reversed_, list(reversed(_BASE_ROWS)))

    conn_a = mod._connect_readonly(forward)
    digest_a = mod.compute_corpus_digest(mod._done_rows(conn_a))
    conn_a.close()

    conn_b = mod._connect_readonly(reversed_)
    digest_b = mod.compute_corpus_digest(mod._done_rows(conn_b))
    conn_b.close()

    assert digest_a == digest_b


def test_digest_changes_when_row_added(tmp_path: Path) -> None:
    db_path = tmp_path / "index.db"
    _make_db(db_path, _BASE_ROWS)
    conn = mod._connect_readonly(db_path)
    base_digest = mod.compute_corpus_digest(mod._done_rows(conn))
    conn.close()

    extra_rows = [
        *_BASE_ROWS,
        (
            "k5",
            "0625",
            "s24",
            "qp",
            "2",
            "0625_s24_qp_2.pdf",
            "ddd444",
            "done",
            1,
            None,
            "gceguide",
            0,
        ),
    ]
    db_path2 = tmp_path / "index2.db"
    _make_db(db_path2, extra_rows)
    conn2 = mod._connect_readonly(db_path2)
    new_digest = mod.compute_corpus_digest(mod._done_rows(conn2))
    conn2.close()

    assert new_digest != base_digest


def test_digest_changes_when_row_removed(tmp_path: Path) -> None:
    db_path = tmp_path / "index.db"
    _make_db(db_path, _BASE_ROWS)
    conn = mod._connect_readonly(db_path)
    base_digest = mod.compute_corpus_digest(mod._done_rows(conn))
    conn.close()

    fewer_rows = _BASE_ROWS[:-2]  # drop the failed row and one done row
    db_path2 = tmp_path / "index2.db"
    _make_db(db_path2, fewer_rows)
    conn2 = mod._connect_readonly(db_path2)
    new_digest = mod.compute_corpus_digest(mod._done_rows(conn2))
    conn2.close()

    assert new_digest != base_digest


def test_digest_changes_when_checksum_changes(tmp_path: Path) -> None:
    """A re-downloaded file landing with a different checksum must change the digest."""
    db_path = tmp_path / "index.db"
    _make_db(db_path, _BASE_ROWS)
    conn = mod._connect_readonly(db_path)
    base_digest = mod.compute_corpus_digest(mod._done_rows(conn))
    conn.close()

    changed_rows = list(_BASE_ROWS)
    k1 = list(changed_rows[0])
    k1[7] = "zzz999"  # checksum column
    changed_rows[0] = tuple(k1)
    db_path2 = tmp_path / "index2.db"
    _make_db(db_path2, changed_rows)
    conn2 = mod._connect_readonly(db_path2)
    new_digest = mod.compute_corpus_digest(mod._done_rows(conn2))
    conn2.close()

    assert new_digest != base_digest


def test_connect_readonly_refuses_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "index.db"
    _make_db(db_path, _BASE_ROWS)

    conn = mod._connect_readonly(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM documents")
    finally:
        conn.close()


def test_build_manifest_computes_expected_shape(tmp_path: Path) -> None:
    db_path = tmp_path / "index.db"
    _make_db(db_path, _BASE_ROWS)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO topics (subject_code, slug, label, unit, source) "
        "VALUES ('0625', 'motion', 'Motion', 1, 'pmt')"
    )
    conn.execute("INSERT INTO document_topics (key, topic_id) VALUES ('k3', 1)")
    conn.commit()
    conn.close()

    manifest = mod.build_manifest(db_path)

    assert manifest["totals"] == {"done": 3, "failed": 1}
    assert (
        manifest["coverage_check"]["qp_without_matching_ms"] == 1
    )  # k3 (0625 qp) has no matching ms
    assert manifest["coverage_check"]["passed"] is False
    assert manifest["session_topical_split"] == {"session": 2, "topical": 1}
    assert len(manifest["failed_documents"]) == 1
    assert manifest["failed_documents"][0]["filename"] == "Broken.pdf"
    assert manifest["topics_0625"] == [{"unit": 1, "slug": "motion", "count": 1}]

    verify_conn = mod._connect_readonly(db_path)
    try:
        expected_digest = mod.compute_corpus_digest(mod._done_rows(verify_conn))
    finally:
        verify_conn.close()
    assert manifest["corpus_digest"] == expected_digest
