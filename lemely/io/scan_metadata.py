"""Gemini vision extractor: student scan PDF → ExamMetadata."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.schemas import ExamMetadata
from lemely.io.prompts.scan_metadata import (
    SCAN_META_SYSTEM_PROMPT,
    VERSION,
    build_scan_meta_user_prompt,
)
from lemely.runtime.events import EventType, bus

if TYPE_CHECKING:
    from pathlib import Path

    from lemely.io.gemini import GeminiClient


class ScanMetadataExtractor:
    """Extract ExamMetadata from a student scan PDF via Gemini vision.

    Gemini treats schema constraints (pattern/enum) as soft hints; a violation
    costs one validate-retry (gemini.py:211-248) before raising ParseError.
    Blurry scans may trigger retries.
    """

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def __call__(self, scan_path: Path) -> ExamMetadata:
        """Extract ExamMetadata from the given scan PDF.

        Args:
            scan_path: Path to the student answer scan PDF.

        Returns:
            ExamMetadata extracted from the cover page / header.
        """
        return self._client.generate_structured(
            system_prompt=SCAN_META_SYSTEM_PROMPT,
            user_prompt=build_scan_meta_user_prompt(scan_path),
            file_paths=[scan_path],
            response_schema=ExamMetadata,
            prompt_version=VERSION,
            task_tag="scan_metadata",
            extra_cache_key=scan_path.name,
        )


def cross_check_metadata(
    scan_metadata: ExamMetadata,
    ms_metadata: ExamMetadata,
) -> ExamMetadata:
    """Cross-check scan-derived metadata against mark-scheme metadata.

    Mark-scheme metadata is authoritative. Mismatches fire a WARNING event.
    Always returns ms_metadata.
    """
    mismatches: list[str] = []
    for field in ("subject_code", "paper_number", "paper_variant", "session_month"):
        scan_val = getattr(scan_metadata, field)
        ms_val = getattr(ms_metadata, field)
        if scan_val != ms_val:
            mismatches.append(f"{field}: scan={scan_val!r} ms={ms_val!r}")

    if mismatches:
        bus.publish(
            EventType.WARNING,
            message=(
                "Scan metadata differs from mark-scheme metadata "
                f"(mark-scheme is authoritative): {'; '.join(mismatches)}"
            ),
            scan_metadata=scan_metadata.model_dump(mode="json"),
            ms_metadata=ms_metadata.model_dump(mode="json"),
        )

    return ms_metadata
