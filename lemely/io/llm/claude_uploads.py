"""One job's page images on the Claude Files API (spec 2026-10-19 §2a).

Data exposure (recorded on purpose): Files API storage is not covered by zero data
retention, and an uploaded file can be read by any API key of the workspace it lives
in. These are student scans. Every file is uploaded with a one-hour expiry and
deleted when the job ends, on success or failure; the expiry is the backstop if the
process dies. The Anthropic key must belong to a dedicated Lemely workspace. Only
ids this object uploaded are ever sent or deleted: a file_id is never taken from
user input. The reply cache key comes from the image bytes, never from an id.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import structlog

from lemely.io.llm.image_fit import FittedImages, fit
from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from collections.abc import Sequence

    import anthropic


class ClaudeImageUploads:
    """Fitted pages uploaded once, reused by every read and retry of the job."""

    EXPIRES_IN_SECONDS = 3600

    def __init__(
        self,
        raw_client: anthropic.Anthropic,
        images: Sequence[bytes],
        *,
        token_budget: int,
        floor_px: int,
    ) -> None:
        self._raw = raw_client
        self._images = list(images)
        self._token_budget = token_budget
        self._floor_px = floor_px
        self._lock = threading.Lock()
        self._fitted: FittedImages | None = None
        self._file_ids: list[str] = []
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
                return self._fitted, tuple(self._file_ids)
            fitted = fit(
                self._images,
                byte_limit=None,
                token_budget=self._token_budget,
                floor_px=self._floor_px,
            )
            try:
                for page, data in enumerate(fitted.images, start=1):
                    uploaded = self._raw.files.upload(
                        file=(f"page-{page}.png", data, "image/png"),
                        expires_in_seconds=self.EXPIRES_IN_SECONDS,
                    )
                    self._file_ids.append(str(uploaded.id))
            except Exception as exc:
                self._error = exc
                raise ExternalServiceError(
                    f"Claude Files API upload of page {len(self._file_ids) + 1} failed: {exc}"
                ) from exc
            self._fitted = fitted
            return fitted, tuple(self._file_ids)

    def delete(self) -> None:
        """Delete every file this object uploaded; a failed delete is logged, never raised."""
        with self._lock:
            file_ids, self._file_ids = self._file_ids, []
            self._fitted = None
        for file_id in file_ids:
            try:
                self._raw.files.delete(file_id)
            except Exception as exc:
                self._log.warning(
                    "claude_file_delete_failed", file_id=file_id, error=str(exc)[:200]
                )
