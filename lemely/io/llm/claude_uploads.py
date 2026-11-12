"""One job's page images on the Claude Files API (spec 2026-10-19 §2a).

Data exposure (recorded on purpose): Files API storage is not covered by zero data
retention, and an uploaded file can be read by any API key of the workspace it lives
in. These are student scans. Every file is uploaded with a one-hour expiry and
deleted when the job ends, on success or failure; the expiry is the backstop if the
process dies. The Anthropic key must belong to a dedicated Lemely workspace. Only
ids this object uploaded are ever sent or deleted: a file_id is never taken from
user input. The reply cache key comes from the image bytes, never from an id.

A file_id that expires mid-job (a job longer than the one-hour expiry) is not
refreshed: the next call that references it fails and the job's own retry handling
decides what follows.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import anthropic
import structlog

from lemely.io.llm.image_fit import DEFAULT_BYTE_LIMIT, FittedImages, fit
from lemely.io.providers.anthropic_adapter import _is_transient
from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class _UploadFailedError(Exception):
    """Internal: one page's upload failed; ``__cause__`` is the error, ``page`` is 1-based."""

    def __init__(self, page: int) -> None:
        super().__init__(page)
        self.page = page


class ClaudeImageUploads:
    """Fitted pages uploaded once, reused by every read and retry of the job."""

    EXPIRES_IN_SECONDS = 3600
    #: Tries per page for a transient upload error (429, 5xx, connection), then the
    #: failure is recorded and every later call falls back inline.
    UPLOAD_ATTEMPTS = 3
    #: Seconds slept before try 2, 3, ... of one page.
    UPLOAD_BACKOFF_SECONDS = (0.5, 1.5)
    #: Default pages uploaded at once (and fitted at once): uploads take ~2 s each, so serial
    #: cost grew with the page count; a small pool stays well inside API rate limits.
    UPLOAD_CONCURRENCY = 6

    def __init__(
        self,
        raw_client: Callable[[], anthropic.Anthropic],
        images: Sequence[bytes],
        *,
        token_budget: int,
        floor_px: int,
        enhance: bool = True,
        concurrency: int | None = None,
    ) -> None:
        # ``raw_client`` is resolved on the first upload, never earlier: a cached
        # reply is replayed without an Anthropic key, so building this must not need one.
        self._raw_client = raw_client
        self._raw: anthropic.Anthropic | None = None
        self._images = list(images)
        self._token_budget = token_budget
        self._floor_px = floor_px
        self._enhance = enhance
        # The caller's bound (``gemini.upload_concurrency``); the class default otherwise.
        self._concurrency = max(1, concurrency or self.UPLOAD_CONCURRENCY)
        self._lock = threading.Lock()
        self._fitted: FittedImages | None = None
        self._inline: FittedImages | None = None
        #: Every id ever uploaded (what :meth:`delete` removes) and the ids of the
        #: finished round, in page order (what :meth:`ensure` returns).
        self._file_ids: list[str] = []
        self._page_ids: tuple[str, ...] = ()
        self._error: BaseException | None = None
        self._log = structlog.get_logger().bind(component="gemini_client", tool="claude_files_api")

    def matches(self, image_parts: Sequence[bytes]) -> bool:
        """Whether ``image_parts`` is the exact page sequence this uploads."""
        return list(image_parts) == self._images

    def __enter__(self) -> ClaudeImageUploads:
        """Context-manager entry: returns ``self``."""
        return self

    def __exit__(self, *_: object) -> None:
        """Context-manager exit: :meth:`delete`, on success and failure alike."""
        self.delete()

    def ensure(self) -> tuple[FittedImages, tuple[str, ...]]:
        """Fit (no inline byte limit) and upload every page once; return the fit and ids.

        Raises:
            ExternalServiceError: an upload failed, now or on an earlier call.
        """
        with self._lock:
            if self._error is not None:
                raise ExternalServiceError(
                    f"Claude Files API upload failed earlier: {self._error}"
                ) from self._error
            if self._fitted is not None:
                return self._fitted, self._page_ids
            try:
                if self._raw is None:
                    self._raw = self._raw_client()
                fitted = fit(
                    self._images,
                    byte_limit=None,
                    token_budget=self._token_budget,
                    floor_px=self._floor_px,
                    enhance=self._enhance,
                    workers=self._concurrency,
                )
                self._page_ids = tuple(self._upload_all(self._raw, fitted.images))
            except _UploadFailedError as exc:
                self._error = exc.__cause__
                raise ExternalServiceError(
                    f"Claude Files API upload of page {exc.page} failed: {exc.__cause__}"
                ) from exc.__cause__
            except (anthropic.AnthropicError, OSError, ExternalServiceError) as exc:
                self._error = exc
                raise ExternalServiceError(f"Claude Files API upload failed: {exc}") from exc
            self._fitted = fitted
            return fitted, self._page_ids

    def _upload_all(self, raw: anthropic.Anthropic, images: Sequence[bytes]) -> list[str]:
        """Upload every page on a bounded pool; the ids come back in page order.

        On a failure every page that did upload stays in ``self._file_ids`` so
        :meth:`delete` removes it (ids are only ever appended); once a page has failed,
        pages not yet started are skipped; the failing page (lowest number) is named.
        """
        ids: list[str | None] = [None] * len(images)
        failures: list[tuple[int, BaseException]] = []
        bug: BaseException | None = None
        stop = threading.Event()

        def run(page: int) -> None:
            nonlocal bug
            if stop.is_set():
                return
            try:
                ids[page - 1] = self._upload_page(raw, page, images[page - 1])
            except (anthropic.AnthropicError, OSError, ExternalServiceError) as exc:
                failures.append((page, exc))
                stop.set()
            except BaseException as exc:  # a programming error: surfaced as itself below
                bug = bug or exc
                stop.set()

        with ThreadPoolExecutor(max_workers=min(self._concurrency, len(images) or 1)) as pool:
            list(pool.map(run, range(1, len(images) + 1)))
        uploaded = [i for i in ids if i is not None]
        self._file_ids.extend(uploaded)
        if bug is not None:
            raise bug
        if failures:
            page, exc = min(failures, key=lambda f: f[0])
            raise _UploadFailedError(page) from exc
        return uploaded

    def _upload_page(self, raw: anthropic.Anthropic, page: int, data: bytes) -> str:
        """Upload one page, retrying a transient error; return its file id."""
        for attempt in range(1, self.UPLOAD_ATTEMPTS + 1):
            try:
                uploaded = raw.files.upload(
                    file=(f"page-{page}.png", data, "image/png"),
                    expires_in_seconds=self.EXPIRES_IN_SECONDS,
                )
            except anthropic.APIError as exc:
                if attempt == self.UPLOAD_ATTEMPTS or not _is_transient(exc):
                    raise
                self._log.warning(
                    "claude_upload_retry", page=page, attempt=attempt, error=str(exc)[:200]
                )
                time.sleep(self.UPLOAD_BACKOFF_SECONDS[attempt - 1])
            else:
                return str(uploaded.id)
        raise AssertionError("unreachable")  # pragma: no cover

    def inline_fit(self) -> FittedImages:
        """The pages fitted for inline base64, made once per job.

        The fallback when the Files API is unavailable: every call after a recorded
        upload failure reuses this instead of fitting the pages again.
        """
        with self._lock:
            if self._inline is None:
                self._inline = fit(
                    self._images,
                    byte_limit=DEFAULT_BYTE_LIMIT,
                    token_budget=self._token_budget,
                    floor_px=self._floor_px,
                    enhance=self._enhance,
                )
            return self._inline

    def delete(self) -> None:
        """Delete every file this object uploaded; a failed delete is logged, never raised."""
        with self._lock:
            file_ids, self._file_ids = self._file_ids, []
            self._fitted = None
            self._inline = None
        if not file_ids or self._raw is None:
            return
        for file_id in file_ids:
            try:
                self._raw.files.delete(file_id)
            except Exception as exc:
                self._log.warning(
                    "claude_file_delete_failed", file_id=file_id, error=str(exc)[:200]
                )
