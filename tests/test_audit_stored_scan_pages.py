"""Tests for ``scripts/audit_stored_scan_pages.py`` (#269).

The audit counts the pages of every stored scan with pdfium alone, before the
page caps ship, so the owner can see how many live scans would be refused.
These tests drive it against the in-memory ``FakeStorageBackend`` and
synthetic PDFs built with pdfium itself: never a real database or bucket.
"""

from __future__ import annotations

import io
import random
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pymupdf
import pypdfium2 as pdfium
import pytest
from PIL import Image
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.models import TeacherPaper, Upload, User
from lemely.db.models.enums import Role
from lemely.runtime.errors import ExternalServiceError
from scripts import audit_stored_scan_pages as audit_script
from scripts.audit_stored_scan_pages import StoredObject
from tests.storage_fakes import FakeStorageBackend

BUCKET = "audit-bucket"


def _pdf(pages: int) -> bytes:
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(200, 200)
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()
    return buffer.getvalue()


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _store(storage: FakeStorageBackend, path: str, data: bytes) -> None:
    storage.upload(BUCKET, path, data, None)


def _objects() -> list[StoredObject]:
    return [
        StoredObject("uploads", "u1", "uploads/small.pdf"),
        StoredObject("uploads", "u2", "uploads/forty-one.pdf"),
        StoredObject("uploads", "u3", "uploads/photo.png"),
        StoredObject("teacher_papers", "t1", "teacher/two-oh-one.pdf"),
        StoredObject("teacher_papers", "t2", "teacher/gone.pdf"),
        StoredObject("teacher_papers", "t3", "teacher/garbage.pdf"),
    ]


def _seeded_storage() -> FakeStorageBackend:
    storage = FakeStorageBackend()
    _store(storage, "uploads/small.pdf", _pdf(3))
    _store(storage, "uploads/forty-one.pdf", _pdf(41))
    _store(storage, "uploads/photo.png", _png())
    _store(storage, "teacher/two-oh-one.pdf", _pdf(201))
    _store(storage, "teacher/garbage.pdf", b"%PDF-1.4 this is not a document")
    return storage


class _FlakyStorage(FakeStorageBackend):
    """Raises ``ExternalServiceError`` for the named paths, serves the rest."""

    def __init__(self, failing: set[str]) -> None:
        super().__init__()
        self._failing = failing

    def download(self, bucket: str, object_path: str) -> bytes:
        if object_path in self._failing:
            raise ExternalServiceError(f"backend unavailable for {object_path}")
        return super().download(bucket, object_path)


class _ReadOnlyStorage(FakeStorageBackend):
    """A fake whose every write raises: the audit must never write."""

    def upload(self, bucket: str, object_path: str, data: bytes, content_type: str | None) -> None:
        raise AssertionError("the audit must not upload")

    def delete(self, bucket: str, object_path: str) -> None:
        raise AssertionError("the audit must not delete")

    def seed(self, path: str, data: bytes) -> None:
        super().upload(BUCKET, path, data, None)


class _CountingStorage(FakeStorageBackend):
    def __init__(self) -> None:
        super().__init__()
        self.downloads: list[str] = []

    def download(self, bucket: str, object_path: str) -> bytes:
        self.downloads.append(object_path)
        return super().download(bucket, object_path)


def test_audit_buckets_each_object_by_page_count_and_table() -> None:
    histogram = audit_script.audit(
        _objects(), _seeded_storage(), BUCKET, sample=None, rng=random.Random(0)
    )

    assert dict(histogram.by_table["uploads"]) == {"1-40": 2, "41-200": 1}
    assert dict(histogram.by_table["teacher_papers"]) == {
        "over_200": 1,
        "missing": 1,
        "unreadable": 1,
    }
    assert histogram.sampled == 6


def test_audit_never_renders_or_opens_with_mupdf() -> None:
    with (
        patch.object(pymupdf, "open") as mupdf_open,
        patch.object(pdfium.PdfPage, "render") as render,
    ):
        audit_script.audit(_objects(), _seeded_storage(), BUCKET, sample=None, rng=random.Random(0))

    mupdf_open.assert_not_called()
    render.assert_not_called()


def test_sample_limits_downloads() -> None:
    storage = _CountingStorage()
    objects = [StoredObject("uploads", f"u{n}", f"uploads/{n}.pdf") for n in range(1, 6)]
    sizes: dict[str, int] = {}
    for n, obj in enumerate(objects, start=1):
        data = _pdf(n)
        sizes[obj.storage_path] = len(data)
        _store(storage, obj.storage_path, data)
    expected_picks = random.Random(7).sample(objects, 2)

    histogram = audit_script.audit(objects, storage, BUCKET, sample=2, rng=random.Random(7))

    assert sorted(storage.downloads) == sorted(o.storage_path for o in expected_picks)
    assert histogram.bytes_downloaded == sum(sizes[o.storage_path] for o in expected_picks)
    assert histogram.sampled == 2
    assert histogram.total == 5


def test_sample_larger_than_the_population_audits_everything() -> None:
    histogram = audit_script.audit(
        _objects(), _seeded_storage(), BUCKET, sample=100, rng=random.Random(0)
    )

    assert histogram.sampled == 6
    assert histogram.total == 6


def test_render_prints_the_over_40_and_over_200_totals() -> None:
    histogram = audit_script.audit(
        _objects(), _seeded_storage(), BUCKET, sample=None, rng=random.Random(0)
    )

    text = audit_script.render(histogram)

    # 41 pages and 201 pages are over 40; only the 201-page scan is over 200.
    assert "over 40: 2" in text
    assert "over 200: 1" in text
    assert f"bytes downloaded: {histogram.bytes_downloaded}" in text
    assert "sampled: 6 of 6" in text
    for header in ("1-40", "41-200", "over_200", "unreadable", "missing"):
        assert header in text
    assert "uploads" in text
    assert "teacher_papers" in text


@pytest.mark.parametrize(
    ("pages", "bucket"),
    [
        (1, "1-40"),
        (40, "1-40"),
        (41, "41-200"),
        (200, "41-200"),
        (201, "over_200"),
        (None, "unreadable"),
        (0, "unreadable"),
    ],
)
def test_bucket_edges_match_the_page_caps(pages: int | None, bucket: str) -> None:
    storage = FakeStorageBackend()
    _store(storage, "x", b"")
    with patch.object(audit_script, "count_pages", return_value=pages):
        histogram = audit_script.audit(
            [StoredObject("uploads", "u", "x")], storage, BUCKET, sample=None, rng=random.Random(0)
        )

    assert dict(histogram.by_table["uploads"]) == {bucket: 1}


class TestCountPages:
    def test_a_pdf_is_counted_by_pdfium(self) -> None:
        assert audit_script.count_pages(_pdf(7)) == 7

    def test_an_image_is_one_page(self) -> None:
        assert audit_script.count_pages(_png()) == 1

    def test_a_pdf_pdfium_cannot_open_is_none(self) -> None:
        assert audit_script.count_pages(b"%PDF-1.4 nothing parseable follows") is None

    def test_bytes_that_are_neither_pdf_nor_image_are_none(self) -> None:
        assert audit_script.count_pages(b"just some text") is None

    def test_the_pdfium_document_is_closed(self) -> None:
        closed: list[bool] = []
        real_close = pdfium.PdfDocument.close

        def spy(self: pdfium.PdfDocument) -> None:
            closed.append(True)
            real_close(self)

        with patch.object(pdfium.PdfDocument, "close", spy):
            audit_script.count_pages(_pdf(2))

        assert closed


class _FakeRows:
    def __init__(self, rows: list[tuple[uuid.UUID, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[uuid.UUID, str]]:
        return self._rows


class _FakeSession:
    def __init__(self, tables: dict[str, list[tuple[uuid.UUID, str]]], seen: list[str]) -> None:
        self._tables = tables
        self._seen = seen

    def execute(self, statement: Any) -> _FakeRows:
        table = statement.get_final_froms()[0].name
        self._seen.append(table)
        return _FakeRows(self._tables[table])


def _fake_session_factory(tables: dict[str, list[tuple[uuid.UUID, str]]], seen: list[str]) -> Any:
    @contextmanager
    def begin() -> Iterator[_FakeSession]:
        yield _FakeSession(tables, seen)

    class _Factory:
        def __call__(self) -> Any:
            return begin()

    return _Factory()


class TestStoredObjects:
    def test_it_reads_uploads_then_teacher_papers_one_session_each(self) -> None:
        upload_id, paper_id = uuid.uuid4(), uuid.uuid4()
        seen: list[str] = []
        factory = _fake_session_factory(
            {
                "uploads": [(upload_id, "uploads/a.pdf")],
                "teacher_papers": [(paper_id, "teacher/b.pdf")],
            },
            seen,
        )

        found = list(audit_script.stored_objects(factory))

        assert found == [
            StoredObject("uploads", str(upload_id), "uploads/a.pdf"),
            StoredObject("teacher_papers", str(paper_id), "teacher/b.pdf"),
        ]
        assert seen == ["uploads", "teacher_papers"]

    def test_it_skips_soft_deleted_rows_in_a_real_database(
        self, migrated_sessionmaker: sessionmaker[Session]
    ) -> None:
        user_id = uuid.uuid4()
        with migrated_sessionmaker.begin() as session:
            session.add(User(id=user_id, email=f"{user_id.hex}@example.com", role=Role.teacher))
            session.flush()
            session.add(Upload(user_id=user_id, storage_path="uploads/live.pdf"))
            session.add(
                Upload(
                    user_id=user_id,
                    storage_path="uploads/deleted.pdf",
                    deleted_at=datetime.now(UTC),
                )
            )
            session.add(TeacherPaper(uploaded_by=user_id, storage_path="teacher/live.pdf"))

        found = {
            o.storage_path: o.table for o in audit_script.stored_objects(migrated_sessionmaker)
        }

        assert found == {"uploads/live.pdf": "uploads", "teacher/live.pdf": "teacher_papers"}


class TestMain:
    def test_it_prints_the_rendered_histogram(self, capsys: pytest.CaptureFixture[str]) -> None:
        factory = _fake_session_factory(
            {"uploads": [(uuid.uuid4(), "uploads/small.pdf")], "teacher_papers": []}, []
        )
        storage = FakeStorageBackend()
        storage.upload("from-settings", "uploads/small.pdf", _pdf(3), None)

        with patch.object(
            audit_script, "_runtime", return_value=(factory, storage, "from-settings")
        ):
            code = audit_script.main(["--sample", "10", "--seed", "1"])

        assert code == 0
        out = capsys.readouterr().out
        assert "sampled: 1 of 1" in out
        assert "over 40: 0" in out

    def test_the_bucket_flag_overrides_the_settings_bucket(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        factory = _fake_session_factory(
            {"uploads": [(uuid.uuid4(), "uploads/small.pdf")], "teacher_papers": []}, []
        )
        storage = FakeStorageBackend()
        storage.upload("flag-bucket", "uploads/small.pdf", _pdf(2), None)

        with patch.object(
            audit_script, "_runtime", return_value=(factory, storage, "from-settings")
        ):
            audit_script.main(["--bucket", "flag-bucket"])

        # Found under the flag's bucket, so nothing is "missing" (the settings
        # bucket holds no such object).
        assert "missing: 0" in capsys.readouterr().out

    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exit_info:
            audit_script.main(["--help"])

        assert exit_info.value.code == 0
        assert "--sample" in capsys.readouterr().out


class TestDownloadErrors:
    def test_one_error_is_counted_on_its_own_and_the_run_continues(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        storage = _FlakyStorage({"uploads/bad.pdf"})
        _store(storage, "uploads/before.pdf", _pdf(2))
        _store(storage, "uploads/after.pdf", _pdf(3))
        objects = [
            StoredObject("uploads", "u1", "uploads/before.pdf"),
            StoredObject("uploads", "u2", "uploads/bad.pdf"),
            StoredObject("uploads", "u3", "uploads/after.pdf"),
        ]

        histogram = audit_script.audit(objects, storage, BUCKET, sample=None, rng=random.Random(0))

        assert dict(histogram.by_table["uploads"]) == {"1-40": 2, "download_error": 1}
        assert "uploads/bad.pdf" in capsys.readouterr().err

    def test_an_error_is_never_counted_as_unreadable_or_missing(self) -> None:
        storage = _FlakyStorage({"uploads/bad.pdf"})

        histogram = audit_script.audit(
            [StoredObject("uploads", "u1", "uploads/bad.pdf")],
            storage,
            BUCKET,
            sample=None,
            rng=random.Random(0),
        )

        assert histogram.count("unreadable") == 0
        assert histogram.count("missing") == 0
        assert histogram.count("download_error") == 1

    def test_five_consecutive_errors_abort_the_audit(self) -> None:
        paths = [f"uploads/{n}.pdf" for n in range(8)]
        storage = _FlakyStorage(set(paths))
        objects = [StoredObject("uploads", f"u{n}", path) for n, path in enumerate(paths)]

        with pytest.raises(audit_script.AuditAbortedError) as aborted:
            audit_script.audit(objects, storage, BUCKET, sample=None, rng=random.Random(0))

        assert aborted.value.histogram.count("download_error") == 5

    def test_a_good_download_resets_the_consecutive_count(self) -> None:
        bad = {f"uploads/bad{n}.pdf" for n in range(8)}
        storage = _FlakyStorage(bad)
        _store(storage, "uploads/good.pdf", _pdf(1))
        order = [f"uploads/bad{n}.pdf" for n in range(4)] + ["uploads/good.pdf"]
        order += [f"uploads/bad{n}.pdf" for n in range(4, 8)]
        objects = [StoredObject("uploads", f"u{n}", path) for n, path in enumerate(order)]

        histogram = audit_script.audit(objects, storage, BUCKET, sample=None, rng=random.Random(0))

        assert histogram.count("download_error") == 8

    def test_render_shows_the_download_error_count(self) -> None:
        storage = _FlakyStorage({"uploads/bad.pdf"})
        histogram = audit_script.audit(
            [StoredObject("uploads", "u1", "uploads/bad.pdf")],
            storage,
            BUCKET,
            sample=None,
            rng=random.Random(0),
        )

        text = audit_script.render(histogram)

        assert "download_error: 1" in text

    def test_main_exits_non_zero_when_any_download_failed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        factory = _fake_session_factory(
            {
                "uploads": [(uuid.uuid4(), "uploads/ok.pdf"), (uuid.uuid4(), "uploads/bad.pdf")],
                "teacher_papers": [],
            },
            [],
        )
        storage = _FlakyStorage({"uploads/bad.pdf"})
        _store(storage, "uploads/ok.pdf", _pdf(1))

        with patch.object(audit_script, "_runtime", return_value=(factory, storage, BUCKET)):
            code = audit_script.main([])

        assert code != 0
        assert "download_error: 1" in capsys.readouterr().out

    def test_main_exits_non_zero_and_still_reports_after_an_abort(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rows = [(uuid.uuid4(), f"uploads/{n}.pdf") for n in range(6)]
        factory = _fake_session_factory({"uploads": rows, "teacher_papers": []}, [])
        storage = _FlakyStorage({path for _, path in rows})

        with patch.object(audit_script, "_runtime", return_value=(factory, storage, BUCKET)):
            code = audit_script.main([])

        captured = capsys.readouterr()
        assert code != 0
        assert "download_error: 5" in captured.out
        assert "aborted" in captured.err


class TestReadOnly:
    def test_audit_never_writes_or_deletes(self) -> None:
        storage = _ReadOnlyStorage()
        storage.seed("uploads/a.pdf", _pdf(2))

        histogram = audit_script.audit(
            [
                StoredObject("uploads", "u1", "uploads/a.pdf"),
                StoredObject("uploads", "u2", "uploads/gone.pdf"),
            ],
            storage,
            BUCKET,
            sample=None,
            rng=random.Random(0),
        )

        assert histogram.sampled == 2

    def test_main_never_writes_or_deletes(self) -> None:
        factory = _fake_session_factory(
            {"uploads": [(uuid.uuid4(), "uploads/a.pdf")], "teacher_papers": []}, []
        )
        storage = _ReadOnlyStorage()
        storage.seed("uploads/a.pdf", _pdf(2))

        with patch.object(audit_script, "_runtime", return_value=(factory, storage, BUCKET)):
            assert audit_script.main([]) == 0


def test_render_says_what_the_audit_leaves_out() -> None:
    text = audit_script.render(audit_script.Histogram())

    assert "soft-deleted" in text
    assert "restorable" in text
    assert "scheme_storage_path" in text


def test_the_caps_are_the_ones_scan_limits_defines() -> None:
    from lemely.io.scan_limits import MAX_CROP_PAGES, MAX_SCAN_PAGES

    assert audit_script.MAX_SCAN_PAGES is MAX_SCAN_PAGES
    assert audit_script.MAX_CROP_PAGES is MAX_CROP_PAGES
