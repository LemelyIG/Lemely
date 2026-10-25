"""T0 golden: pins today's Gemini behaviour before the provider refactor.

Spec 2026-10-19 §1 invariant: with today's configured Gemini models, cache keys,
logged events, the CallRecord fields that exist today, requests and outputs stay
byte-identical. Captured on 6b9ac91c. For each representative call this pins the
cache entries written, the bus events, the structlog lines, the CallRecords (T0
fields only), the requests sent to google-genai, the Files API traffic and the
returned outputs.

Regenerate ONLY for a change that is meant to move Gemini behaviour:
``python -m tests.test_llm_golden --regen``, and say why in the commit message.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import sys
import tempfile
import unittest
from collections.abc import Callable
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from pydantic import BaseModel
from structlog.testing import capture_logs

from lemely.io.gemini import (
    GeminiClient,
    SharedPrefix,
    _reset_process_counters,
    process_call_records,
    record_calls,
    set_call_context,
)
from lemely.runtime.events import EventType, bus
from tests.gemini_fakes import fake_genai_client, make_settings, mock_response

GOLDEN = Path(__file__).parent / "fixtures" / "llm_golden" / "gemini_calls.json"
_TODAY = date(2026, 10, 19)
#: The CallRecord fields that exist at T0 (latency_ms left out: wall clock).
_T0_RECORD_FIELDS = (
    "provider",
    "task_tag",
    "model",
    "thinking",
    "input_tokens",
    "cached_tokens",
    "output_tokens",
    "thinking_tokens",
    "usd_now",
    "usd_2027",
    "attempt",
    "question_id",
    "case_key",
    "parse_ok",
)
_EVENTS = (
    EventType.GEMINI_CALL_START,
    EventType.GEMINI_CALL_END,
    EventType.GEMINI_CACHE_HIT,
    EventType.GEMINI_RETRY,
)
_VOLATILE_KEYS = frozenset({"latency_ms"})
_PDF = b"%PDF-1.4\n% lemely golden\n"
_PAGES = (b"\x89PNG\r\n\x1a\ngolden-page-1", b"\x89PNG\r\n\x1a\ngolden-page-2")
_OK = '{"value": "ok"}'


class _Reply(BaseModel):
    value: str


def _jsonable(value: Any) -> Any:
    """A JSON-ready copy: pydantic models dumped, bytes base64, mocks by type name."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Path):
        return value.name
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return f"<{type(value).__name__}>"


def _scrub(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in e.items() if k not in _VOLATILE_KEYS} for e in entries]


def _structured(**overrides: Any) -> Callable[[GeminiClient, Path], Any]:
    def call(client: GeminiClient, tmp: Path) -> Any:
        kwargs: dict[str, Any] = {
            "system_prompt": "sys",
            "user_prompt": "user",
            "response_schema": _Reply,
            "prompt_version": "v1",
            **overrides,
        }
        if kwargs.pop("pdf", False):
            pdf = tmp / "doc.pdf"
            pdf.write_bytes(_PDF)
            kwargs["file_paths"] = [pdf]
        if kwargs.pop("uploads", False):
            with client.image_uploads(list(_PAGES), concurrency=1) as uploads:
                return client.generate_structured(
                    image_parts=list(_PAGES), image_uploads=uploads, **kwargs
                ).model_dump()
        return client.generate_structured(**kwargs).model_dump()

    return call


def _code_execution(client: GeminiClient, tmp: Path) -> Any:
    return client.generate_with_code_execution(
        prompt="compute 6*7", prompt_version="v1", task_tag="question_validity"
    )


def _code_response() -> MagicMock:
    resp = mock_response("", prompt=50, candidates=5)
    part = MagicMock()
    part.code_execution_result.output = "42"
    resp.candidates[0].content.parts = [part]
    return resp


_PREFIX = SharedPrefix(
    instructions="INSTR\n", paper="PAPER", text="INSTR\nPAPER", cache="implicit", version="v1"
)
_EXPLICIT_PREFIX = dataclasses.replace(_PREFIX, cache="explicit")
_PREFIX_CACHE_NAME = "cachedContents/golden-prefix"
_PREFIX_CACHE_TOKENS = 2000

#: name -> (call, responses, how many times the call is made)
_CASES: dict[str, tuple[Callable[[GeminiClient, Path], Any], Callable[[], list[Any]], int]] = {
    "correction": (
        _structured(task_tag="correction"),
        lambda: [mock_response(_OK, prompt=900, candidates=60, thoughts=12)],
        1,
    ),
    "correction_cache_hit": (_structured(task_tag="correction"), lambda: [mock_response(_OK)], 2),
    "correction_shared_prefix": (
        _structured(task_tag="correction", system_prompt="INSTR\nPAPER", shared_prefix=_PREFIX),
        lambda: [mock_response(_OK, prompt=1200, cached=1000, candidates=40)],
        1,
    ),
    "correction_schema_retry": (
        _structured(task_tag="correction"),
        lambda: [mock_response("{}"), mock_response(_OK)],
        1,
    ),
    "correction_transient_retry": (
        _structured(task_tag="correction"),
        lambda: [Exception("503 Service Unavailable"), mock_response(_OK, prompt=900)],
        1,
    ),
    "correction_explicit_prefix_cache": (
        _structured(
            task_tag="correction",
            model="gemini-3.8-flash",
            system_prompt="INSTR\nPAPER",
            shared_prefix=_EXPLICIT_PREFIX,
        ),
        lambda: [mock_response(_OK, prompt=1200, cached=1000, candidates=40)],
        1,
    ),
    "correction_borderline": (
        _structured(task_tag="correction_borderline", attempt="borderline", question_id="3b"),
        lambda: [mock_response(_OK, prompt=800, candidates=70, thoughts=300)],
        1,
    ),
    "escalation": (
        _structured(task_tag="escalation", attempt="escalation", question_id="3b"),
        lambda: [mock_response(_OK, prompt=800, candidates=70, thoughts=500)],
        1,
    ),
    "extraction_inline_images": (
        _structured(
            task_tag="extraction",
            model="gemini-3.8-flash",
            image_parts=list(_PAGES),
            media_resolution="high",
        ),
        lambda: [mock_response(_OK, prompt=24000, candidates=9000)],
        1,
    ),
    "extraction_files_api": (
        _structured(
            task_tag="extraction", model="gemini-3.8-flash", media_resolution="high", uploads=True
        ),
        lambda: [mock_response(_OK, prompt=24000, candidates=9000)],
        1,
    ),
    "extraction_cap_truncated": (
        _structured(task_tag="extraction", model="gemini-3.8-flash", image_parts=list(_PAGES)),
        lambda: [
            mock_response(_OK, prompt=24000, candidates=32768, finish_reason="MAX_TOKENS"),
            mock_response(_OK, prompt=24000, candidates=9000),
        ],
        1,
    ),
    "binding_second_read": (
        _structured(
            task_tag="binding_second_read",
            model="gemini-3.8-flash",
            image_parts=list(_PAGES),
            media_resolution="high",
        ),
        lambda: [mock_response(_OK, prompt=24000, candidates=7000)],
        1,
    ),
    "mark_scheme_pdf": (
        _structured(task_tag="mark_scheme", pdf=True),
        lambda: [mock_response(_OK, prompt=30000, candidates=20000, thoughts=7000)],
        1,
    ),
    "scan_metadata_pdf": (
        _structured(task_tag="scan_metadata", pdf=True, extra_cache_key="scan.pdf"),
        lambda: [mock_response(_OK, prompt=5000, candidates=100)],
        1,
    ),
    "generation": (_structured(task_tag="generation"), lambda: [mock_response(_OK)], 1),
    "untagged": (_structured(), lambda: [mock_response(_OK)], 1),
    "question_validity_code_execution": (_code_execution, lambda: [_code_response()], 1),
}


def _run(
    call: Callable[[GeminiClient, Path], Any], responses: Callable[[], list[Any]], repeat: int
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        return _run_in(Path(tmp_dir), call, responses, repeat)


def _run_in(
    tmp: Path,
    call: Callable[[GeminiClient, Path], Any],
    responses: Callable[[], list[Any]],
    repeat: int,
) -> dict[str, Any]:
    settings = make_settings(str(tmp))
    genai = fake_genai_client()
    genai.caches.create.return_value = MagicMock(
        usage_metadata=MagicMock(total_token_count=_PREFIX_CACHE_TOKENS)
    )
    genai.caches.create.return_value.name = _PREFIX_CACHE_NAME
    genai.models.generate_content.side_effect = responses()
    client = GeminiClient(settings, _genai_client=genai, ledger=None)
    events: list[dict[str, Any]] = []
    spies: list[tuple[EventType, Callable[..., None]]] = []
    for event_type in _EVENTS:

        def spy(_event_type: EventType = event_type, **payload: Any) -> None:
            events.append({"event": str(_event_type), **payload})

        bus.subscribe(event_type, spy)
        spies.append((event_type, spy))
    _reset_process_counters()
    set_call_context(case_key=None)
    try:
        with record_calls(), capture_logs() as logs:
            outputs = [call(client, tmp) for _ in range(repeat)]
            records = [
                {field: getattr(r, field) for field in _T0_RECORD_FIELDS}
                for r in process_call_records()
            ]
    finally:
        for event_type, spy in spies:
            bus.unsubscribe(event_type, spy)
    cache_dir = settings.paths.cache_dir / "gemini"
    return _jsonable(
        {
            "cache_keys": sorted(p.stem for p in cache_dir.glob("*.json")),
            # Entries are the raw model text (no timestamps), so nothing is dropped.
            "cache_entries": {
                p.stem: p.read_text(encoding="utf-8") for p in sorted(cache_dir.glob("*.json"))
            },
            "cache_creates": [
                {"model": c.kwargs["model"], "config": c.kwargs["config"]}
                for c in genai.caches.create.call_args_list
            ],
            "outputs": outputs,
            "events": _scrub(events),
            "logs": _scrub(logs),
            "records": records,
            "requests": [
                {
                    "model": c.kwargs["model"],
                    "config": c.kwargs["config"],
                    "contents": c.kwargs["contents"],
                }
                for c in genai.models.generate_content.call_args_list
            ],
            "uploads": [
                {"sha256": hashlib.sha256(data).hexdigest()[:16], "config": cfg}
                for data, cfg in genai.files.uploads
            ],
            "deleted": list(genai.files.deleted),
        }
    )


def _actual() -> dict[str, Any]:
    with (
        patch("lemely.io.gemini._today", lambda: _TODAY),
        patch("lemely.io.gemini.time.sleep"),
    ):
        result = {name: _run(*case) for name, case in _CASES.items()}
    return json.loads(json.dumps(result, sort_keys=True))


class GeminiGoldenTests(unittest.TestCase):
    def test_every_case_matches_the_golden(self) -> None:
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        actual = _actual()
        self.assertEqual(sorted(actual), sorted(expected))
        for name in sorted(expected):
            with self.subTest(case=name):
                self.assertEqual(actual[name], expected[name])

    def test_golden_covers_every_task_tag(self) -> None:
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        tags = {r["task_tag"] for case in expected.values() for r in case["records"]}
        self.assertLessEqual(
            {
                "correction",
                "correction_borderline",
                "escalation",
                "extraction",
                "binding_second_read",
                "mark_scheme",
                "scan_metadata",
                "generation",
                "question_validity",
                None,
            },
            tags,
        )

    def test_golden_holds_real_calls(self) -> None:
        """Guards against a fixture generated from a broken run (no requests, no keys)."""
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        for name, case in expected.items():
            with self.subTest(case=name):
                self.assertTrue(case["requests"])
                self.assertTrue(case["cache_keys"])
                self.assertTrue(case["records"])


if __name__ == "__main__":
    if "--regen" in sys.argv:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(_actual(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {GOLDEN}")  # noqa: T201
    else:
        unittest.main()
