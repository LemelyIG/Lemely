"""Generic Marking Principles (GMP) extractor."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lemely.core.loose_schemas import MarkSchemeMetadata

# GMP numbered list markers: "1." / "GMP 1" / "GMP1"
_GMP_SPLIT_RE = re.compile(r"(?m)^(?:GMP\s*\d+|\d+\.)\s+")


def extract_gmp(
    pdf: Any,
    metadata: MarkSchemeMetadata,
    pages_start: int = 1,
    pages_end: int = 4,
) -> None:
    """Populate ``metadata.generic_marking_principles`` from the GMP pages.

    Modifies *metadata* in-place (the field is mutable despite being a Pydantic
    model because we use the ``model_config`` default; callers treat this as an
    initialisation step before the model is handed off read-only).

    Args:
        pdf: Open pdfplumber PDF object.
        metadata: Metadata model to update.
        pages_start: First page (0-indexed) to search for GMP text.
        pages_end: Exclusive end page for the GMP search range.
    """
    pages = pdf.pages
    gmp_pages = pages[pages_start:pages_end] if len(pages) > pages_start else []
    all_text = "\n".join((p.extract_text() or "") for p in gmp_pages)

    # Split on numbered markers; parts[0] is pre-marker text (skip it),
    # parts[1:] are the bodies of each principle.
    parts = _GMP_SPLIT_RE.split(all_text)
    principles: list[str] = []
    for body in parts[1:]:
        paragraph = body.split("\n\n")[0].strip()
        if paragraph:
            principles.append(paragraph)

    if principles:
        metadata.generic_marking_principles = principles
