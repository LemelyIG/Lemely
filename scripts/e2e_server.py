#!/usr/bin/env python3
"""Standalone FastAPI bootstrap for the Playwright E2E acceptance test (P2.10).

Runs the real app against the real local Supabase stack (Postgres, GoTrue,
Storage) so login, upload, and persistence are all genuine. The only seam
replaced is Gemini-vision answer extraction / mark-scheme resolution, which
MISSION.md requires mocking in every automated test — this reuses the exact
seam ``tests/test_student_correct.py`` already proved out
(``student.resolve_mark_scheme`` / ``student.extract_answers`` are reassigned
module-level functions, which FastAPI resolves at call time regardless of
whether the app runs under ``TestClient`` or real ``uvicorn``), fed from the
real ``tests/golden/0625_m20_qp_12_mcq`` fixture. MCQ marking is 100%
deterministic (D0.5) — Gemini is only ever needed to *read* the scan/scheme,
which this bootstrap replaces with the known-good fixture data.

Usage: ``python scripts/e2e_server.py`` (reads ``PORT`` from env, default
8000 — matches ``web/vite.config.ts``'s ``/api`` proxy target).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import uvicorn
from sqlalchemy.engine import make_url

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import Settings, load_settings
from lemely.web import create_app
from lemely.web.deps import get_gemini_client, get_settings
from lemely.web.routers import student

if TYPE_CHECKING:
    from fastapi import FastAPI

#: Opt-in database guard: when set, the server refuses to start unless the database it
#: resolves from settings has exactly this name. ``web/playwright.config.ts`` sets it to
#: ``lemely_e2e``, so a configuration regression fails loudly instead of landing test
#: traffic in the shared development database. Unset (the default) for hand runs.
EXPECT_DATABASE_ENV = "LEMELY_E2E_EXPECT_DATABASE"

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden" / "0625_m20_qp_12_mcq"


def _fixture_mark_scheme() -> MarkScheme:
    data = json.loads((FIXTURE_DIR / "mark_scheme.json").read_text(encoding="utf-8"))
    return MarkScheme.model_validate(data)


def _fixture_extracted() -> ExtractedAnswers:
    answers: dict[str, dict[str, object]] = json.loads(
        (FIXTURE_DIR / "answers.json").read_text(encoding="utf-8")
    )
    return ExtractedAnswers(
        paper_id="e2e",
        source_scan="scan.pdf",
        answers=[
            ExtractedAnswer(question_id=qid, answer=str(a["student_answer"]), confidence=0.95)
            for qid, a in answers.items()
        ],
    )


def build_app() -> FastAPI:
    """Build the real app with only the Gemini-vision seam replaced."""
    base = load_settings()
    data = base.model_dump()
    # Skip ScanMetadataExtractor entirely (student_correct's run() only calls it
    # when a key is configured) and force the offline resolve/extract path below.
    data["gemini_api_key"] = None
    settings = Settings.model_validate(data)

    student.resolve_mark_scheme = lambda *args, **kwargs: _fixture_mark_scheme()
    student.extract_answers = lambda *args, **kwargs: _fixture_extracted()  # type: ignore[attr-defined]

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock(spec=GeminiClient)
    return app


def require_expected_database(settings: Settings, expected: str | None) -> None:
    """Exit unless ``settings`` resolves to the database named ``expected`` (no-op if unset)."""
    if not expected:
        return
    actual = make_url(settings.database.url).database
    if actual != expected:
        raise SystemExit(
            f"e2e_server: refusing to start: the database resolves to {actual!r}, "
            f"but {EXPECT_DATABASE_ENV} requires {expected!r}."
        )


def main() -> None:
    require_expected_database(load_settings(), os.environ.get(EXPECT_DATABASE_ENV))
    app = build_app()
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
