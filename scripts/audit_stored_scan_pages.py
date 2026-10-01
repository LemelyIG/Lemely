#!/usr/bin/env python3
"""Count the pages of every stored scan, with pdfium only (#269).

The scan page caps (``MAX_SCAN_PAGES`` 40 for extraction, ``MAX_CROP_PAGES``
200 for the crop and preview) must not refuse scans that are already stored
and in use. Before they deploy, run this against production to see how many
live uploads and teacher papers sit over each cap.

It downloads each object, counts its pages with ``pdfium.PdfDocument`` and
buckets the result. Nothing is rendered and MuPDF never opens a byte, so a
hostile stored file cannot reach the parser this audit is guarding against.
Soft-deleted rows are excluded by the session's own rule
(``lemely.db.session._exclude_soft_deleted``).

    python scripts/audit_stored_scan_pages.py --sample 500 --seed 1

Needs the same configuration as the web process: the database URL and the
Google Cloud credentials (``gcloud auth application-default login``). Run it
read-only; it never writes to the database or the bucket.
"""

from __future__ import annotations

import argparse
import io
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import pypdfium2 as pdfium
from PIL import Image
from sqlalchemy import select

from lemely.db.models import TeacherPaper, Upload
from lemely.io.storage import StorageBackend, StorageObjectNotFoundError

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from sqlalchemy.orm import Session, sessionmaker

# Kept in step with ``lemely.io.scan_limits.PDF_MAGIC``. Re-stated here rather
# than imported: the audit must not depend on the module the page caps live in.
_PDF_MAGIC = b"%PDF-"

TableName = Literal["uploads", "teacher_papers"]
TABLES: tuple[TableName, ...] = ("uploads", "teacher_papers")

BUCKETS = ("1-40", "41-200", "over_200", "unreadable", "missing")
_MAX_SCAN_PAGES = 40
_MAX_CROP_PAGES = 200


@dataclass(frozen=True)
class StoredObject:
    """One stored scan: the table and row that own it, and its storage key."""

    table: TableName
    row_id: str
    storage_path: str


@dataclass
class Histogram:
    """Page-count buckets per table, plus what the audit downloaded."""

    by_table: dict[str, Counter[str]] = field(
        default_factory=lambda: {table: Counter() for table in TABLES}
    )
    bytes_downloaded: int = 0
    sampled: int = 0
    total: int = 0

    def count(self, bucket: str) -> int:
        return sum(counter[bucket] for counter in self.by_table.values())


def stored_objects(session_factory: sessionmaker[Session]) -> Iterator[StoredObject]:
    """Yield every live upload and teacher paper, one session per table.

    The repositories expose no listing, so the models are read directly through
    the same ``sessionmaker`` they use. Soft-deleted rows never appear: the
    session-level loader criterion hides them from every ORM select.
    """
    with session_factory() as session:
        for row_id, storage_path in session.execute(select(Upload.id, Upload.storage_path)).all():
            yield StoredObject("uploads", str(row_id), storage_path)
    with session_factory() as session:
        for row_id, storage_path in session.execute(
            select(TeacherPaper.id, TeacherPaper.storage_path)
        ).all():
            yield StoredObject("teacher_papers", str(row_id), storage_path)


def count_pages(data: bytes) -> int | None:
    """Pages in a stored scan: pdfium's count for a PDF, 1 for an image.

    ``None`` when the bytes are neither a PDF pdfium can open nor an image.
    Nothing is rendered and MuPDF is never involved.
    """
    if data.startswith(_PDF_MAGIC):
        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError:
            return None
        try:
            return len(pdf)
        finally:
            pdf.close()
    try:
        # ``open`` reads the header only; no pixel is decoded.
        with Image.open(io.BytesIO(data)):
            return 1
    except Image.DecompressionBombError:
        return 1  # An image too large to decode is still an image.
    except Exception:
        return None


def _bucket_for(pages: int | None) -> str:
    if pages is None or pages < 1:
        return "unreadable"
    if pages <= _MAX_SCAN_PAGES:
        return "1-40"
    if pages <= _MAX_CROP_PAGES:
        return "41-200"
    return "over_200"


def audit(
    objects: Iterable[StoredObject],
    storage: StorageBackend,
    bucket: str,
    *,
    sample: int | None,
    rng: random.Random,
) -> Histogram:
    """Download and bucket ``objects`` (or an ``rng.sample`` of ``sample`` of them)."""
    population = list(objects)
    chosen = population
    if sample is not None and sample < len(population):
        chosen = rng.sample(population, sample)

    histogram = Histogram(total=len(population), sampled=len(chosen))
    for stored in chosen:
        counter = histogram.by_table[stored.table]
        try:
            data = storage.download(bucket, stored.storage_path)
        except StorageObjectNotFoundError:
            counter["missing"] += 1
            continue
        histogram.bytes_downloaded += len(data)
        counter[_bucket_for(count_pages(data))] += 1
    return histogram


def render(histogram: Histogram) -> str:
    """One table of buckets per storage table, then the totals the caps care about."""
    name_width = max(len("table"), *(len(table) for table in histogram.by_table))
    widths = [max(len(bucket), 6) for bucket in BUCKETS]
    header = "  ".join(
        [f"{'table':<{name_width}}"] + [f"{b:>{w}}" for b, w in zip(BUCKETS, widths, strict=True)]
    )
    lines = [header, "-" * len(header)]
    for table, counter in histogram.by_table.items():
        cells = [f"{counter[b]:>{w}}" for b, w in zip(BUCKETS, widths, strict=True)]
        lines.append("  ".join([f"{table:<{name_width}}", *cells]))
    lines += [
        "",
        f"over 40: {histogram.count('41-200') + histogram.count('over_200')}",
        f"over 200: {histogram.count('over_200')}",
        f"unreadable: {histogram.count('unreadable')}",
        f"missing: {histogram.count('missing')}",
        f"bytes downloaded: {histogram.bytes_downloaded}",
        f"sampled: {histogram.sampled} of {histogram.total}",
    ]
    return "\n".join(lines)


def _runtime() -> tuple[sessionmaker[Session], StorageBackend, str]:
    """The session factory, storage backend and default bucket the web process uses."""
    from lemely.db.session import get_sessionmaker
    from lemely.web.deps import get_settings, get_storage_backend

    settings = get_settings()
    return (
        get_sessionmaker(settings),
        get_storage_backend(),
        settings.storage.bucket,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Histogram the page counts of every stored scan, using pdfium only."
    )
    parser.add_argument(
        "--sample", type=int, default=None, metavar="N", help="audit a random N objects only"
    )
    parser.add_argument("--seed", type=int, default=None, metavar="S", help="seed for --sample")
    parser.add_argument(
        "--bucket", default=None, help="storage bucket (default: settings.storage.bucket)"
    )
    args = parser.parse_args(argv)

    session_factory, storage, default_bucket = _runtime()
    histogram = audit(
        stored_objects(session_factory),
        storage,
        args.bucket or default_bucket,
        sample=args.sample,
        rng=random.Random(args.seed),  # noqa: S311 - sampling, not security
    )
    print(render(histogram))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
