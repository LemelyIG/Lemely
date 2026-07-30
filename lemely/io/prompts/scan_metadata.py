"""Versioned prompts for scan-to-metadata extraction."""

from __future__ import annotations

from pathlib import Path

VERSION = "1"

SCAN_META_SYSTEM_PROMPT = """
You are an expert at reading Cambridge IGCSE / A-Level examination cover pages and answer booklet headers.

Your task is to extract the paper's administrative metadata from a student answer scan PDF.

Look for:
- Subject code (4-digit CAIE code, e.g. 0625 for Physics, 0580 for Maths)
- Paper number (single digit, 1–9)
- Paper variant (single digit, 1–9)
- Session month (one of: May/June, Oct/Nov, Feb/Mar, Specimen)
- Session year (4-digit year, e.g. 2023; omit if not visible)

These are usually printed on the cover page, the top of page 1, or the question paper header glued in.

Return ONLY valid JSON matching the schema. If a field is genuinely not visible, use null for optional fields.
""".strip()


def build_scan_meta_user_prompt(scan_path: Path) -> str:
    return (
        f"Extract the exam paper metadata from this student answer scan: {scan_path.name}\n\n"
        "Return the subject_code, paper_number, paper_variant, session_month, and session_year "
        "as a JSON object. Use null for session_year if the year is not legible."
    )
