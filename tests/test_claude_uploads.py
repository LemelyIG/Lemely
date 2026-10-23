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
from lemely.io.llm import image_fit
from lemely.io.llm.claude_uploads import ClaudeImageUploads
from tests.test_anthropic_adapter import (
    _VALID_MARK,
    _FakeAnthropic,
    _message,
    _settings,
    _status_error,
)

_HAIKU = "claude-haiku-5-5"


class _FakeFiles:
    def __init__(
        self, *, fail_on: int | None = None, errors: list[Exception] | None = None
    ) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.attempts = 0
        self._fail_on = fail_on
        self._errors = list(errors or [])

    def upload(self, *, file: tuple[str, bytes, str], expires_in_seconds: int) -> SimpleNamespace:
        self.attempts += 1
        if self._errors:
            raise self._errors.pop(0)
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
        self,
        files: _FakeFiles,
        *outcomes: object,
        files_api: bool = True,
        **gemini: Any,
    ) -> tuple[GeminiClient, _FakeAnthropic]:
        settings = _settings(self.tmp)
        settings = settings.model_copy(
            update={
                "gemini": settings.gemini.model_copy(
                    update={"claude_files_api": files_api, **gemini}
                )
            }
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

    def test_file_sources_skip_the_count_endpoint_and_log_why(self) -> None:
        # The endpoint answers 400 "File sources are not supported" for file ids
        # (.superpowers/sdd/binding-investigation.md, Q1), so it is not asked.
        files = _FakeFiles()
        client, fake = self._client(files, _message(_VALID_MARK), claude_image_token_budget=700)
        with client.image_uploads(list(_PAGES), concurrency=1) as uploads:
            with capture_logs() as logs:
                self._read(client, uploads, "binding_second_read")
        self.assertEqual(fake.messages.count_calls, [])
        (pre,) = [e for e in logs if e["event"] == "claude_token_preflight"]
        self.assertIsNone(pre["counted_tokens"])
        self.assertEqual(pre["reason"], "file_sources")
        self.assertGreater(pre["est_tokens"], 0)

    def test_inline_images_still_use_the_count_endpoint(self) -> None:
        files = _FakeFiles()
        client, fake = self._client(
            files, _message(_VALID_MARK), files_api=False, claude_image_token_budget=700
        )
        with capture_logs() as logs:
            self._read(client, None, "binding_second_read")
        self.assertEqual(len(fake.messages.count_calls), 1)
        (pre,) = [e for e in logs if e["event"] == "claude_token_preflight"]
        self.assertIsNotNone(pre["counted_tokens"])
        self.assertNotIn("reason", pre)

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


class KeylessReplayTests(_Base):
    def test_a_cached_reply_replays_without_an_anthropic_key_when_uploads_are_passed(self) -> None:
        files = _FakeFiles()
        client, _fake = self._client(files, _message(_VALID_MARK))
        with client.image_uploads(list(_PAGES), concurrency=1) as uploads:
            self._read(client, uploads, "extraction")
        self.assertEqual(len(files.uploads), 2)

        keyless = _settings(self.tmp).model_copy(update={"anthropic_api_key": None})
        replay = GeminiClient(keyless, _genai_client=object(), ledger=None)
        with replay.image_uploads(list(_PAGES), concurrency=1) as uploads:
            self._read(replay, uploads, "extraction")  # raises without the lazy lookup
        self.assertEqual(len(files.uploads), 2)
        self.assertEqual(files.deleted, ["file_1", "file_2"])


class InlineFallbackTests(_Base):
    def test_the_inline_fit_is_made_once_per_job_after_an_upload_failure(self) -> None:
        files = _FakeFiles(fail_on=1)
        client, fake = self._client(files, *(_message(_VALID_MARK) for _ in range(3)))
        with (
            patch("lemely.io.llm.claude_uploads.fit", wraps=image_fit.fit) as uploads_fit,
            client.image_uploads(list(_PAGES), concurrency=1) as uploads,
        ):
            for tag in ("extraction", "binding_second_read", "binding_first_read"):
                self._read(client, uploads, tag)
        self.assertEqual(len(fake.messages.calls), 3)
        inline = [c for c in uploads_fit.call_args_list if c.kwargs["byte_limit"] is not None]
        self.assertEqual(len(inline), 1)


class ClaudeImageUploadsUnitTests(unittest.TestCase):
    def _uploads(self, files: _FakeFiles, **kw: Any) -> ClaudeImageUploads:
        return ClaudeImageUploads(
            lambda: SimpleNamespace(files=files),  # type: ignore[arg-type,return-value]
            list(_PAGES),
            token_budget=95_000,
            floor_px=1568,
            **kw,
        )

    def test_the_client_is_looked_up_on_first_upload_not_at_construction(self) -> None:
        looked_up: list[int] = []

        def lookup() -> Any:
            looked_up.append(1)
            return SimpleNamespace(files=_FakeFiles())

        uploads = ClaudeImageUploads(lookup, list(_PAGES), token_budget=95_000, floor_px=1568)
        uploads.delete()
        self.assertEqual(looked_up, [])
        uploads.ensure()
        uploads.ensure()
        self.assertEqual(looked_up, [1])

    def test_a_transient_upload_error_is_retried(self) -> None:
        files = _FakeFiles(errors=[_status_error(429), _status_error(529)])
        uploads = self._uploads(files)
        with patch("lemely.io.llm.claude_uploads.time.sleep") as sleep:
            _fitted, ids = uploads.ensure()
        self.assertEqual(ids, ("file_1", "file_2"))
        self.assertEqual(files.attempts, 4)
        self.assertEqual(sleep.call_count, 2)

    def test_transient_errors_are_recorded_after_the_last_try(self) -> None:
        files = _FakeFiles(errors=[_status_error(500)] * 3)
        uploads = self._uploads(files)
        with patch("lemely.io.llm.claude_uploads.time.sleep"):
            for _ in range(2):
                with self.assertRaisesRegex(Exception, "upload"):
                    uploads.ensure()
        self.assertEqual(files.attempts, 3)

    def test_a_permanent_upload_error_is_not_retried(self) -> None:
        files = _FakeFiles(errors=[_status_error(400)])
        uploads = self._uploads(files)
        with (
            patch("lemely.io.llm.claude_uploads.time.sleep") as sleep,
            self.assertRaisesRegex(Exception, "upload"),
        ):
            uploads.ensure()
        self.assertEqual(files.attempts, 1)
        sleep.assert_not_called()

    def test_a_programming_error_propagates_as_itself(self) -> None:
        files = _FakeFiles(errors=[TypeError("bug")])
        with self.assertRaises(TypeError):
            self._uploads(files).ensure()

    def test_enhance_reaches_the_fit(self) -> None:
        with patch("lemely.io.llm.claude_uploads.fit", wraps=image_fit.fit) as spy:
            self._uploads(_FakeFiles(), enhance=False).ensure()
        self.assertIs(spy.call_args.kwargs["enhance"], False)

    def test_ensure_is_idempotent_and_a_failure_is_remembered(self) -> None:
        files = _FakeFiles(fail_on=1)
        uploads = ClaudeImageUploads(
            lambda: SimpleNamespace(files=files), list(_PAGES), token_budget=95_000, floor_px=1568
        )
        for _ in range(2):
            with self.assertRaisesRegex(Exception, "upload"):
                uploads.ensure()
        self.assertEqual(files.uploads, [])

    def test_matches_only_the_same_pages(self) -> None:
        uploads = ClaudeImageUploads(
            lambda: SimpleNamespace(files=_FakeFiles()),
            list(_PAGES),
            token_budget=95_000,
            floor_px=1568,
        )
        self.assertTrue(uploads.matches(list(_PAGES)))
        self.assertFalse(uploads.matches(list(reversed(_PAGES))))
