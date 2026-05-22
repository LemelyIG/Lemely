from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import BatchParseItem, BatchParseResult, SourceLibraryEntry
from lemely.io.metadata import parse_caie_filename_metadata

ParserCallback = Callable[[Path], dict[str, object] | MarkScheme]


def index_source_library(source_root: str | Path) -> list[SourceLibraryEntry]:
    root = Path(source_root)
    entries: list[SourceLibraryEntry] = []
    for pdf_path in sorted(root.rglob("*.pdf")):
        try:
            metadata = parse_caie_filename_metadata(pdf_path.name)
        except ValueError:
            continue
        entries.append(SourceLibraryEntry(source_path=pdf_path, metadata=metadata))
    return entries


def _validate_mark_scheme_json(path: Path) -> MarkScheme:
    return MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _coerce_mark_scheme(raw: dict[str, object] | MarkScheme) -> MarkScheme:
    if isinstance(raw, MarkScheme):
        return raw
    return MarkScheme.model_validate(raw)


def process_mark_scheme_batch(
    source_root: str | Path,
    output_root: str | Path | None = None,
    *,
    force: bool = False,
    parser: ParserCallback | None = None,
) -> BatchParseResult:
    output_dir = Path(output_root) if output_root is not None else None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    items: list[BatchParseItem] = []

    for entry in index_source_library(source_root):
        output_path = (
            output_dir / f"{entry.source_path.stem}.json"
            if output_dir is not None
            else entry.source_path.with_suffix(".json")
        )
        if output_path.exists() and not force:
            try:
                _validate_mark_scheme_json(output_path)
            except (ValidationError, json.JSONDecodeError, OSError) as exc:
                items.append(
                    BatchParseItem(
                        source_path=str(entry.source_path),
                        output_path=str(output_path),
                        status="invalid_existing",
                        message=str(exc),
                    )
                )
            else:
                items.append(
                    BatchParseItem(
                        source_path=str(entry.source_path),
                        output_path=str(output_path),
                        status="skipped_existing",
                    )
                )
            continue

        if parser is None:
            items.append(
                BatchParseItem(
                    source_path=str(entry.source_path),
                    output_path=str(output_path),
                    status="needs_parser",
                    message="No parser callback supplied for PDF source.",
                )
            )
            continue

        try:
            mark_scheme = _coerce_mark_scheme(parser(entry.source_path))
            output_path.write_text(
                mark_scheme.model_dump_json(indent=2),
                encoding="utf-8",
            )
        except (ValidationError, ValueError, OSError, TypeError) as exc:
            items.append(
                BatchParseItem(
                    source_path=str(entry.source_path),
                    output_path=str(output_path),
                    status="failed",
                    message=str(exc),
                )
            )
        else:
            items.append(
                BatchParseItem(
                    source_path=str(entry.source_path),
                    output_path=str(output_path),
                    status="parsed",
                )
            )

    return BatchParseResult(items=items)
