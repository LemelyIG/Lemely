"""Spec 2026-10-19 §2a: page images uploaded once per job to the Claude Files API."""

from __future__ import annotations

import io
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from PIL import Image
from structlog.testing import capture_logs

from lemely.core.schemas import AIMarkResponse
from lemely.io.gemini import GeminiClient, _reset_process_counters, record_calls
from lemely.io.llm.claude_uploads import ClaudeImageUploads
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _settings

_HAIKU = "claude-haiku-5-5"


class _FakeFiles:
    def __init__(self, *, fail_on: int | None = None) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self._fail_on = fail_on

    def upload(self, *, file: tuple[str, bytes, str], expires_in_seconds: int) -> SimpleNamespace:
        if self._fail_on is not None and len(self.uploads) + 1 == self._fail_on:
            raise OSError("upload refused")
        self.uploads.append({"file": file, "expires_in_seconds": expires_in_seconds})
        return SimpleNamespace(id=f"file_{len(self.uploads)}")

    def delete(self, file_id: str) -> None:
        self.deleted.append(file_id)


def _page(shade: int) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (400, 600), shade).save(buf, "PNG")
    return buf.getvalue()


_PAGES = [_page(10), _page(200)]


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)

    def _client(
        self, files: _FakeFiles, *outcomes: object, files_api: bool = True
    ) -> tuple[GeminiClient, _FakeAnthropic]:
        settings = _settings(self.tmp)
        settings = settings.model_copy(
            update={"gemini": settings.gemini.model_copy(update={"claude_files_api": files_api})}
        )
        fake = _FakeAnthropic(*outcomes)
        fake.files = files
        return GeminiClient(
            settings, _genai_client=object(), _anthropic_client=fake, ledger=None
        ), fake

    def _read(self, client: GeminiClient, uploads: Any, tag: str) -> None:
        client.generate_structured(
            system_prompt="sys",
            user_prompt="read",
            image_parts=list(_PAGES),
            image_uploads=uploads,
            response_schema=AIMarkResponse,
            prompt_version="v1",
            model=_HAIKU,
            task_tag=tag,
        )


def _sources(call: dict[str, Any]) -> list[dict[str, Any]]:
    return [b["source"] for b in call["messages"][0]["content"] if b["type"] == "image"]


class UploadTests(_Base):
    def test_pages_upload_once_and_both_reads_reference_them(self) -> None:
        files = _FakeFiles()
        client, fake = self._client(files, _message(_VALID_MARK), _message(_VALID_MARK))
        with client.image_uploads(list(_PAGES), concurrency=1) as uploads:
            self._read(client, uploads, "extraction")
            self._read(client, uploads, "binding_second_read")
            self.assertEqual(len(files.uploads), 2)
        expected = [{"type": "file", "file_id": "file_1"}, {"type": "file", "file_id": "file_2"}]
        self.assertEqual([_sources(c) for c in fake.messages.calls], [expected, expected])
        self.assertEqual(files.deleted, ["file_1", "file_2"])

    def test_uploads_expire_in_one_hour(self) -> None:
        files = _FakeFiles()
        client, _fake = self._client(files, _message(_VALID_MARK))
        with client.image_uploads(list(_PAGES), concurrency=1) as uploads:
            self._read(client, uploads, "extraction")
        self.assertEqual({u["expires_in_seconds"] for u in files.uploads}, {3600})
        self.assertEqual([u["file"][2] for u in files.uploads], ["image/png", "image/png"])

    def test_files_are_deleted_when_the_job_fails(self) -> None:
        files = _FakeFiles()
        client, _fake = self._client(files, _message(_VALID_MARK))
        with (
            self.assertRaises(RuntimeError),
            client.image_uploads(list(_PAGES), concurrency=1) as uploads,
        ):
            self._read(client, uploads, "extraction")
            raise RuntimeError("job failed after the read")
        self.assertEqual(files.deleted, ["file_1", "file_2"])

    def test_a_failed_upload_falls_back_inline_and_cleans_up(self) -> None:
        files = _FakeFiles(fail_on=2)
        client, fake = self._client(files, _message(_VALID_MARK))
        with capture_logs() as logs, client.image_uploads(list(_PAGES), concurrency=1) as uploads:
            self._read(client, uploads, "extraction")
        self.assertEqual(
            [s["type"] for s in _sources(fake.messages.calls[0])], ["base64", "base64"]
        )
        self.assertIn("claude_files_api_fallback", [e["event"] for e in logs])
        self.assertEqual(files.deleted, ["file_1"])

    def test_the_cache_key_never_depends_on_an_upload(self) -> None:
        files = _FakeFiles()
        client, _fake = self._client(files, _message(_VALID_MARK))
        key = client.structured_cache_key(
            system_prompt="sys",
            user_prompt="read",
            image_parts=list(_PAGES),
            response_schema=AIMarkResponse,
            prompt_version="v1",
            model=_HAIKU,
            task_tag="extraction",
        )
        with client.image_uploads(list(_PAGES), concurrency=1) as uploads:
            self._read(client, uploads, "extraction")
        written = sorted(
            p.stem for p in (client._settings.paths.cache_dir / "gemini").glob("*.json")
        )
        self.assertEqual(written, [key])

    def test_files_api_off_sends_the_bytes_inline(self) -> None:
        files = _FakeFiles()
        client, fake = self._client(files, _message(_VALID_MARK), files_api=False)
        with client.image_uploads(list(_PAGES), concurrency=1) as uploads:
            self._read(client, uploads, "extraction")
        self.assertEqual(files.uploads, [])
        self.assertEqual(
            [s["type"] for s in _sources(fake.messages.calls[0])], ["base64", "base64"]
        )


class ClaudeImageUploadsUnitTests(unittest.TestCase):
    def test_ensure_is_idempotent_and_a_failure_is_remembered(self) -> None:
        files = _FakeFiles(fail_on=1)
        uploads = ClaudeImageUploads(
            SimpleNamespace(files=files), list(_PAGES), token_budget=95_000, floor_px=1568
        )
        for _ in range(2):
            with self.assertRaisesRegex(Exception, "upload"):
                uploads.ensure()
        self.assertEqual(files.uploads, [])

    def test_matches_only_the_same_pages(self) -> None:
        uploads = ClaudeImageUploads(
            SimpleNamespace(files=_FakeFiles()), list(_PAGES), token_budget=95_000, floor_px=1568
        )
        self.assertTrue(uploads.matches(list(_PAGES)))
        self.assertFalse(uploads.matches(list(reversed(_PAGES))))
