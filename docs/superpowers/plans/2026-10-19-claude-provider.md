# Claude Provider Parity and Native Levers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every task tag can run on a `claude-` model (parity), Claude-native cost levers exist behind flags that default off, and a live run of the real script `0625_w24_41` measures $ per marked paper against the $0.10 target.

**Architecture:** A new package `lemely/io/llm/` holds a provider-neutral `LLMRequest`, a `Provider` protocol, a `GeminiProvider` (today's Gemini call code, moved unchanged) and a `ClaudeProvider` (today's adapter path, extended). `GeminiClient` keeps the response cache, retry, cost ceiling, ledger and `CallRecord`, builds one `LLMRequest` per attempt and dispatches by model prefix. A golden test written first (Task 0) pins today's Gemini cache keys, events, log lines, records, requests and outputs, and must pass unchanged after every later task.

**Tech Stack:** Python 3, pydantic v2 settings, google-genai, anthropic (`>=1.15.0,<2`, already pinned), Pillow, pypdfium2, structlog, tenacity, pytest/unittest.

**Spec:** `docs/superpowers/specs/2026-10-19-claude-provider-design.md` (the "spec" below). Task numbers keep the spec's T-numbers; a letter suffix marks a split.

## Global Constraints

- Signed, conventional commits: `git commit -S -m "<type>(<scope>): ..."`. Scopes used here: `llm`, `anthropic`, `gemini`, `pricing`, `binding`, `correction`, `config`, `doctor`, `test`.
- Commit path-scoped only: `git add -- <paths> && git commit -S -m "..." -- <paths>`. Never `git add -A`, `git add .` or `git add -f`.
- Run `pre-commit run --all-files` before every commit and fix every failure. The ruff hook autofixes: after it runs, re-run it until it passes with no changes, then `git diff --stat` to confirm the tree you commit is the tree you tested.
- Never run the full test suite locally (no `make test`, no bare `pytest`). Run only the touched test files plus the source-scanning tests:
  `python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""`.
  CI's full run is the only judge of green; say so when reporting.
- Every pytest command in this plan has the form `python -m pytest <file> -q --no-cov -o addopts=""`, run from the repo root with `.venv` active.
- A new settings flag read on a hot path is tested with `is True` (`if g.flag is True:`), never truthiness: many tests build settings from `MagicMock`, whose attributes are truthy. When a task adds such a read, also run every test file that builds `MagicMock` settings and reaches that code (`grep -l "MagicMock" tests/test_*.py | xargs grep -l "<entry point>"`).
- Never commit or echo an API key. Live runs read keys inside a scratch driver from `~/.config/lemely/gemini_key` and `~/.config/lemely/anthropic_key`; no key on a command line or in an environment assignment typed into a shell.
- Student data goes only through the synchronous Messages API, never the Message Batches API.
- **Default Gemini path byte-identical.** With today's configured Gemini models, cache keys, logged events, the `CallRecord` fields that exist today, requests and outputs do not change. `tests/test_llm_golden.py` (Task 0) pins this and must pass unchanged after every task. Regenerating its fixture is never part of this plan.
- Every new lever is off by default (one exception the spec decides: `claude_files_api` is on, and it acts only on `claude-` calls with page images).
- Never commit `.superpowers/`, `BUILD/**/cache/`, `BUILD/accuracy-runs/**` student-answer files (`extracted.json`, `correction.json`, `records*.jsonl`), or anything under `outputs/`.
- Task 11 is a live run made by the main session, not by a subagent. This plan describes its driver and its report only. Anthropic spend for all cost-ladder and Claude runs combined is capped at **$40.00** (ledger `BUILD/accuracy-runs/cost-ladder-spend.json`, read and written through `lemely.accuracy.cost_ladder.spend`).
- Prove every new guard goes red: each task has a step that breaks the code on purpose, watches the named test fail, and reverts.
- Implementers touch only the files their task lists, and commit with `git commit -S -- <those paths>`.

---

## Facts this plan relies on

Verified against official docs on 2026-10-19 (by the controller, or by the planner where marked *planner*):

- Files API is GA, no beta header. `client.files.upload(file=(name, bytes, mime), expires_in_seconds=3600)` (SDK 1.15 signature confirmed by *planner*: `upload(*, file, expires_in_seconds, workspace_id)`); image block `{"type": "image", "source": {"type": "file", "file_id": ...}}`; `client.files.delete(file_id)`. File operations are free; content bills as input tokens; not ZDR-eligible; workspace-scoped.
- Pricing per MTok: Haiku 5.5 up to 100k input 0.10 in / 0.50 out / 0.125 write 5m / 0.20 write 1h / 0.01 hit; above 100k 0.50 / 2.50 / 0.625 / 1.00 / 0.05. Sonnet 5.5 2 / 10 / 2.50 / 4 / 0.10. Opus 5.5 4 / 20 / 5 / 8 / 0.20. Fable 5.1 10 / 50 / 12.50 / 20 / 0.25. Task 3 re-reads every rate.
- Code execution: `code_execution_20260521` is the latest version; billed $0.05 per container-hour, **minimum 5 minutes per execution**, 1,550 free hours a month (ignored here); not ZDR-eligible; results arrive as `bash_code_execution_tool_result` blocks whose `content` (`bash_code_execution_result`) has `stdout`, `stderr`, `return_code`. The response `usage` has no container-time field (SDK 1.15 `Usage` fields: `cache_creation`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `inference_geo`, `input_tokens`, `output_tokens`, `output_tokens_details`, `server_tool_use`, `service_tier`, `speed`). *planner*
- **Citations and structured outputs are incompatible**: enabling citations on a document while sending `output_config.format` returns a 400 (citations docs). *planner*
- Structured outputs do not support string `minLength`/`maxLength`. *planner*
- PDFs: 32 MB maximum request; 600 pages per request, 100 when the context window is under 1M tokens. *planner*
- Prompt-cache minimum 512 tokens on 5.5 models; at most 4 breakpoints; images are cacheable. `usage.cache_creation` has `ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`.
- Effort values: `low`, `medium`, `high`, `xhigh`, `max`.
- The SDK refuses a non-streaming `messages.create` whose `max_tokens` implies more than 10 minutes: `3600 * max_tokens / 128000 > 600`, i.e. `max_tokens > 21_333` (`anthropic._base_client._calculate_nonstreaming_timeout`). *planner*
- Real scans render at 2430×3439 RGB; the 19-page script is 79.6 MB base64 after today's downscale. The real script used by the Gemini E2E run at `01f371c3` is `/home/sico/Documents/P4 N24 V1_annotated (NO Corrections).pdf` with mark scheme `/home/sico/0625_w24_ms_41.pdf` (from `BUILD/accuracy-runs/e2e-0625-w24-41-2026-10-19/run.sh`).

Anything else is marked "confirm in step 1" in the task that needs it.

---

## File structure

| Path | Responsibility | Task |
|---|---|---|
| `lemely/io/llm/__init__.py` | Package docstring only | 1a |
| `lemely/io/llm/errors.py` | `TransientCallError`, `CapTruncatedError` (the client's retry vocabulary) | 1a |
| `lemely/io/llm/request.py` | `LLMRequest` and its parts, `provider_fingerprint`, effort and cache-spot literals | 1a, 2b, 5, 6 |
| `lemely/io/llm/provider.py` | `Usage`, `ProviderReply`, `Provider` protocol | 1a, 3a |
| `lemely/io/llm/gemini_provider.py` | Gemini call code moved out of `GeminiClient` | 1b, 4 |
| `lemely/io/llm/claude_provider.py` | Request to adapter: image fit, uploads, documents, code execution, cache plan | 1b, 2b, 2c, 4, 5, 6 |
| `lemely/io/llm/image_fit.py` | Pure image-fit policy (greyscale, token/byte budgets, thumbnails) | 2a |
| `lemely/io/llm/claude_uploads.py` | `ClaudeImageUploads` (Files API, one job) | 2c |
| `lemely/io/llm/pricing.py` | `PriceRow` with tiers and cache writes, Claude rows, `row_cost` | 3a |
| `lemely/io/providers/anthropic_adapter.py` | Messages API request building and sending | 2b, 3a, 4, 5, 6, 7 |
| `lemely/io/gemini.py` | Client shell: cache, retry, ceiling, ledger, records, dispatch | 0 (read only), 1a, 1b, 2b, 2c, 3a, 3c, 4, 5, 7 |
| `lemely/core/leaf_kind.py` | `QuestionType` to `mcq`/`numeric`/`short`/`extended` | 7 |
| `lemely/core/cited_marks.py` | Evidence-quote check, `uncited_mark` flag | 8a |
| `lemely/io/binding/chunked_read.py` | Overview pass, chunk plan, chunk reads, merge | 10 |
| `tests/fixtures/llm_golden/gemini_calls.json` | The T0 golden | 0 |

## File ownership and waves

| Task | Owns |
|---|---|
| 0 Golden | `tests/test_llm_golden.py`, `tests/fixtures/llm_golden/gemini_calls.json` (new) |
| 1a Types | `lemely/io/llm/{__init__,errors,request,provider}.py` (new), `lemely/io/gemini.py` (imports, error classes, `_params_fingerprint` provider segment), `lemely/io/providers/anthropic_adapter.py` (`Usage` import only), `tests/test_llm_request.py` (new) |
| 1b Providers | `lemely/io/llm/gemini_provider.py`, `lemely/io/llm/claude_provider.py` (new), `lemely/io/gemini.py` (`__init__`, `_call_once`, `_call_code_execution_once`, new `_build_request`/`_provider_for_model`/`_check_stop`, removal of `_call_anthropic_once`/`_usage_as_gemini_response`), `tests/test_llm_providers.py` (new) |
| 2a Image fit | `lemely/io/llm/image_fit.py`, `tests/test_image_fit.py` (new) |
| 2b Claude images | `lemely/io/llm/request.py`, `lemely/io/llm/claude_provider.py`, `lemely/io/providers/anthropic_adapter.py`, `lemely/io/gemini.py` (Claude cap, fingerprint, provider construction), `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `tests/test_claude_images.py` (new), `tests/test_anthropic_adapter.py` |
| 2c Files API | `lemely/io/llm/claude_uploads.py` (new), `lemely/io/llm/claude_provider.py`, `lemely/io/providers/anthropic_adapter.py` (`raw` property), `lemely/io/gemini.py` (`ImageUploads.for_claude`, `generate_structured` wiring), `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `lemely/app/cli.py` (one advisory check), `docs/deployment.md`, `tests/test_claude_uploads.py` (new), `tests/test_anthropic_adapter.py` |
| 3a Pricing | `lemely/io/llm/pricing.py` (new), `lemely/io/llm/provider.py`, `lemely/io/llm/claude_provider.py`, `lemely/io/providers/anthropic_adapter.py` (`_usage_of`), `lemely/io/gemini.py` (pricing, `CallRecord`, `_record_spend`, `_require_price`), `tests/test_llm_pricing.py` (new), `tests/test_anthropic_adapter.py` |
| 3b Doctor | `lemely/io/model_table.py`, `lemely/app/cli.py` (doctor only), `tests/test_model_table.py`, `tests/test_cli_doctor.py` |
| 3c Cost guard | `lemely/io/gemini.py` (`script_cost_scope`, one line in `_record_spend`), `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `lemely/web/routers/student.py`, `lemely/web/routers/teacher.py` (the marked spans only), `tests/test_script_cost_scope.py` (new) |
| 4 PDFs | `lemely/io/llm/gemini_provider.py`, `lemely/io/llm/claude_provider.py`, `lemely/io/providers/anthropic_adapter.py`, `lemely/io/gemini.py` (`documents`), `lemely/io/parsers.py`, `lemely/io/scan_metadata.py`, `tests/test_claude_documents.py` (new), `tests/test_anthropic_adapter.py` |
| 5 Code execution | `lemely/io/llm/request.py`, `lemely/io/llm/claude_provider.py`, `lemely/io/providers/anthropic_adapter.py`, `lemely/io/gemini.py` (`generate_with_code_execution`), `tests/test_claude_code_execution.py` (new), `tests/test_anthropic_adapter.py` |
| 6 Cache breakpoints | `lemely/io/llm/request.py`, `lemely/io/llm/claude_provider.py`, `lemely/io/providers/anthropic_adapter.py`, `lemely/io/gemini.py` (`_build_request`), `lemely/io/binding/orchestrate.py`, `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `tests/test_claude_cache_plan.py` (new), `tests/test_anthropic_adapter.py` |
| 7 Effort | `lemely/core/leaf_kind.py` (new), `lemely/io/gemini.py` (`_resolved_gen_params`, `generate_structured`), `lemely/io/providers/anthropic_adapter.py`, `lemely/io/correction_ai.py` (the five `generate_structured` calls), `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `tests/test_claude_effort.py` (new) |
| 8a Evidence | `lemely/core/cited_marks.py` (new), `lemely/core/schemas.py` (new response classes), `lemely/io/correction_ai.py`, `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `tests/test_cited_marks.py` (new) |
| 8b Terse | `lemely/core/schemas.py`, `lemely/io/correction_ai.py` (schema choice only), `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `tests/test_cited_marks.py` |
| 9 Blank skip | none (verification only) |
| 10 Chunked read | `lemely/io/binding/chunked_read.py` (new), `lemely/io/binding/label_binder.py`, `lemely/io/binding/orchestrate.py`, `lemely/io/prompts/label_binding.py`, `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `tests/test_chunked_read.py` (new) |
| 11 Live E2E | `BUILD/accuracy-runs/claude-e2e-0625-w24-41-<date>/` (uncommitted except `COST.md`) |

**Waves.** Task 0 first, alone. Then Task 1a; Task 2a and Task 9 run beside it (they share no file with it). Then 1b, 2b, 2c, 3a in that order (all edit `gemini.py` or the Claude provider). Then 3b and 3c in parallel (disjoint files). Then 4, 5, 6, 7, 8a, 8b in order. Task 10 after Task 6 (both edit `orchestrate.py`) and after 2a. A final CI gate sweep after the last commit. Then Task 11 by the main session.

Each task gets a spec review and a quality review. After Task 1b, and after every later task, the reviewer also runs `python -m pytest tests/test_llm_golden.py -q --no-cov -o addopts=""` and confirms it passes with the fixture file untouched (`git diff --stat -- tests/fixtures/llm_golden` is empty).

---

### Task 0: Golden pin of Gemini behaviour (spec T0)

**Files:**
- Create: `tests/test_llm_golden.py`
- Create: `tests/fixtures/llm_golden/gemini_calls.json` (generated by the test module at HEAD `6b9ac91c`, before any other task)

**Interfaces:**
- Consumes: today's `lemely.io.gemini` public surface (`GeminiClient`, `SharedPrefix`, `record_calls`, `process_call_records`, `set_call_context`, `_reset_process_counters`) and `tests/gemini_fakes.py` (`fake_genai_client`, `make_settings`, `mock_response`).
- Produces: `tests/test_llm_golden.py::GeminiGoldenTests`, run by every later task's reviewer. `_T0_RECORD_FIELDS` names the `CallRecord` fields that exist at T0; later tasks may add fields with defaults, and the golden compares only these.

- [ ] **Step 1: Confirm the start point.** Run `git rev-parse HEAD` and `git status --short -- lemely tests`. Expected: HEAD is `6b9ac91c` (or a docs-only descendant of it: `git diff --stat 6b9ac91c -- lemely tests` is empty) and nothing under `lemely/` or `tests/` is modified. Stop and report if either fails: the golden must be captured from unmodified code.

- [ ] **Step 2: Write the golden test module.** Create `tests/test_llm_golden.py`:

```python
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
    tmp = Path(tempfile.mkdtemp())
    settings = make_settings(str(tmp))
    genai = fake_genai_client()
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
```

- [ ] **Step 3: Run it to see it fail.** Run `python -m pytest tests/test_llm_golden.py -q --no-cov -o addopts=""`. Expected: 3 errors, `FileNotFoundError` on `gemini_calls.json`.

- [ ] **Step 4: Generate the golden at the unmodified HEAD.** Run `python -m tests.test_llm_golden --regen`. Expected: `wrote .../tests/fixtures/llm_golden/gemini_calls.json`. Open the file and check by eye: 15 cases; `correction_cache_hit` has two `outputs`, one request and a `gemini.cache_hit`-type event; `extraction_cap_truncated` has two requests, two records (the first `parse_ok: false`) and a `gemini_cap_truncated_retry` log line; `extraction_files_api` has 2 uploads and 2 deletes; `mark_scheme_pdf` records carry `thinking: 8000`; `question_validity_code_execution` output is `"42"`. If anything else looks wrong (an empty request list, a `<MagicMock>` where a number belongs), fix `_jsonable` or the case and regenerate before going on.

- [ ] **Step 5: Run it to see it pass, twice.** Run `python -m pytest tests/test_llm_golden.py -q --no-cov -o addopts=""` two times. Expected: `3 passed` both times (the golden is deterministic).

- [ ] **Step 6: Prove it goes red.** In `lemely/io/gemini.py` change `_MAX_OUTPUT_TOKENS: int = 65536` to `65535`, run the same command, expect failures in at least `correction` and `extraction_inline_images` (`cache_keys` and `config.max_output_tokens` differ). Revert with `git checkout -- lemely/io/gemini.py` and rerun: `3 passed`.

- [ ] **Step 7: Commit.**

```bash
pre-commit run --all-files
git add -- tests/test_llm_golden.py tests/fixtures/llm_golden/gemini_calls.json
git commit -S -m "test(llm): golden pin of Gemini cache keys, events, records and requests" -- tests/test_llm_golden.py tests/fixtures/llm_golden/gemini_calls.json
```

---

### Task 1a: Request and provider types (spec T1, part 1)

**Files:**
- Create: `lemely/io/llm/__init__.py`, `lemely/io/llm/errors.py`, `lemely/io/llm/request.py`, `lemely/io/llm/provider.py`
- Modify: `lemely/io/gemini.py` (replace the `_TransientError`/`_CapTruncatedError` class definitions with imports; Anthropic segment in `_params_fingerprint`)
- Modify: `lemely/io/providers/anthropic_adapter.py` (`Usage` now imported from `lemely.io.llm.provider`)
- Test: `tests/test_llm_request.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `lemely.io.llm.errors.TransientCallError(Exception)` and `CapTruncatedError(ExternalServiceError)`. `lemely.io.gemini._TransientError is TransientCallError` and `lemely.io.gemini._CapTruncatedError is CapTruncatedError`.
  - `lemely.io.llm.request`: `Effort = Literal["low", "medium", "high", "xhigh", "max"]`; `CacheSpot = Literal["system", "documents", "images", "prefix"]`; `MAX_CACHE_BREAKPOINTS = 4`; frozen dataclasses `ImageInput(data: bytes, media_type: Literal["image/png", "image/jpeg"] = "image/png")`, `DocumentInput(data: bytes, media_type: Literal["application/pdf", "text/plain"] = "application/pdf", cache: bool = False, citations: bool = False, title: str | None = None, source_path: Path | None = None)` with `DocumentInput.from_path(path: Path, **kwargs) -> DocumentInput`, `CodeExecution()`, `CachePlan(breakpoints: tuple[CacheSpot, ...] = (), ttl: Literal["5m"] = "5m")`, and `LLMRequest` (fields below); `provider_fingerprint(model: str, *, max_output_tokens: int) -> str`.
  - `LLMRequest(model: str, task_tag: str | None, system: str, prompt: str, response_schema: type[BaseModel] | None, images: tuple[ImageInput, ...] = (), documents: tuple[DocumentInput, ...] = (), tool: CodeExecution | None = None, cache_plan: CachePlan = CachePlan(), effort: str | None = None, max_output_tokens: int = 65536, cache_prefix: str | None = None, media_resolution: str | None = None, uploads: Any = None, shared_prefix: Any = None)` with `fingerprint() -> str` (= `provider_fingerprint(self.model, max_output_tokens=self.max_output_tokens)`).
  - `lemely.io.llm.provider`: `Usage(input_tokens: int, cached_tokens: int, output_tokens: int, thinking_tokens: int)` (moved, unchanged); `ProviderReply(text: str, usage_response: Any, stop_reason: str | None, stop_detail: str, latency_ms: int, usage: Usage | None = None)`; `Provider` protocol with `complete(self, req: LLMRequest, *, log: Any) -> ProviderReply` and `count_tokens(self, req: LLMRequest) -> int | None`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_llm_request.py`:

```python
"""Spec 2026-10-19 §1: the provider-neutral request and its single cache-key source."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lemely.io import gemini as gemini_module
from lemely.io.llm.errors import CapTruncatedError, TransientCallError
from lemely.io.llm.provider import ProviderReply, Usage
from lemely.io.llm.request import (
    CachePlan,
    DocumentInput,
    LLMRequest,
    provider_fingerprint,
)
from lemely.io.providers import anthropic_adapter
from lemely.runtime.errors import ExternalServiceError


class ProviderFingerprintTests(unittest.TestCase):
    def test_gemini_models_add_nothing(self) -> None:
        for model in ("gemini-3.8-flash", "gemini-2.5-flash", "gemini-3.1-flash-lite"):
            with self.subTest(model=model):
                self.assertEqual(provider_fingerprint(model, max_output_tokens=65536), "")

    def test_claude_segment_is_todays(self) -> None:
        self.assertEqual(
            provider_fingerprint("claude-haiku-5-5", max_output_tokens=16000),
            "|provider=anthropic|max_tokens=16000",
        )

    def test_request_fingerprint_is_the_module_function(self) -> None:
        req = LLMRequest(
            model="claude-haiku-5-5",
            task_tag="correction",
            system="s",
            prompt="p",
            response_schema=None,
            max_output_tokens=16000,
        )
        self.assertEqual(
            req.fingerprint(), provider_fingerprint("claude-haiku-5-5", max_output_tokens=16000)
        )


class CachePlanTests(unittest.TestCase):
    def test_more_than_four_breakpoints_refused(self) -> None:
        with self.assertRaises(ValueError):
            CachePlan(breakpoints=("system", "documents", "images", "prefix", "system"))

    def test_duplicate_breakpoints_refused(self) -> None:
        with self.assertRaises(ValueError):
            CachePlan(breakpoints=("system", "system"))

    def test_default_is_no_breakpoints(self) -> None:
        self.assertEqual(CachePlan().breakpoints, ())


class DocumentInputTests(unittest.TestCase):
    def test_from_path_reads_bytes_and_keeps_path(self) -> None:
        path = Path(tempfile.mkdtemp()) / "ms.pdf"
        path.write_bytes(b"%PDF-1.4 x")
        doc = DocumentInput.from_path(path, cache=True)
        self.assertEqual(doc.data, b"%PDF-1.4 x")
        self.assertEqual(doc.source_path, path)
        self.assertTrue(doc.cache)
        self.assertEqual(doc.media_type, "application/pdf")


class MovedNamesTests(unittest.TestCase):
    def test_client_error_names_are_the_shared_classes(self) -> None:
        self.assertIs(gemini_module._TransientError, TransientCallError)
        self.assertIs(gemini_module._CapTruncatedError, CapTruncatedError)
        self.assertTrue(issubclass(CapTruncatedError, ExternalServiceError))

    def test_adapter_usage_is_the_provider_usage(self) -> None:
        self.assertIs(anthropic_adapter.Usage, Usage)

    def test_reply_defaults(self) -> None:
        reply = ProviderReply(
            text="t", usage_response=None, stop_reason=None, stop_detail="", latency_ms=0
        )
        self.assertIsNone(reply.usage)
```

- [ ] **Step 2: Run them to see them fail.** Run `python -m pytest tests/test_llm_request.py -q --no-cov -o addopts=""`. Expected: collection error, `ModuleNotFoundError: No module named 'lemely.io.llm'`.

- [ ] **Step 3: Write the package.** Create `lemely/io/llm/__init__.py`:

```python
"""Provider-neutral model requests (spec 2026-10-19 §1).

``GeminiClient`` builds one :class:`~lemely.io.llm.request.LLMRequest` per attempt
and hands it to the provider its model prefix picks. The client keeps the response
cache, retry, cost ceiling, ledger and ``CallRecord``. Nothing here imports a
provider SDK at module load.
"""
```

Create `lemely/io/llm/errors.py`:

```python
"""The client's retry vocabulary, shared by every provider."""

from __future__ import annotations

from lemely.runtime.errors import ExternalServiceError


class TransientCallError(Exception):
    """A failure the client's retry policy retries (5xx, 429, overload, connection)."""


class CapTruncatedError(ExternalServiceError):
    """A reply cut off at an output cap: billed, recorded unparsed, retried once afresh."""
```

Create `lemely/io/llm/request.py`:

```python
"""One model request, whatever the provider (spec 2026-10-19 §1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from lemely.io.providers import is_anthropic_model

Effort = Literal["low", "medium", "high", "xhigh", "max"]
CacheSpot = Literal["system", "documents", "images", "prefix"]
#: The API's limit on cache breakpoints in one request.
MAX_CACHE_BREAKPOINTS = 4


@dataclass(frozen=True)
class ImageInput:
    """One page image as encoded bytes."""

    data: bytes
    media_type: Literal["image/png", "image/jpeg"] = "image/png"


@dataclass(frozen=True)
class DocumentInput:
    """One document. ``source_path`` is kept for Gemini's Files API, which uploads a path."""

    data: bytes
    media_type: Literal["application/pdf", "text/plain"] = "application/pdf"
    cache: bool = False
    citations: bool = False
    title: str | None = None
    source_path: Path | None = None

    @classmethod
    def from_path(cls, path: Path, **kwargs: Any) -> DocumentInput:
        """The document at ``path``: its bytes, and the path itself for Gemini."""
        return cls(data=path.read_bytes(), source_path=path, **kwargs)


@dataclass(frozen=True)
class CodeExecution:
    """Ask the provider's own server-side code-execution tool to run code."""


@dataclass(frozen=True)
class CachePlan:
    """Where a Claude request places its prompt-cache breakpoints (spec §4 B1)."""

    breakpoints: tuple[CacheSpot, ...] = ()
    ttl: Literal["5m"] = "5m"

    def __post_init__(self) -> None:
        """Refuse more than the API's four breakpoints, or one spot named twice."""
        if len(self.breakpoints) > MAX_CACHE_BREAKPOINTS:
            raise ValueError(
                f"at most {MAX_CACHE_BREAKPOINTS} cache breakpoints, got {len(self.breakpoints)}"
            )
        if len(set(self.breakpoints)) != len(self.breakpoints):
            raise ValueError(f"cache breakpoints named twice: {self.breakpoints}")


def provider_fingerprint(model: str, *, max_output_tokens: int) -> str:
    """The provider part of a reply's cache key: the single source for it.

    Empty for every Gemini model, so no Gemini key moves. A ``claude-`` model adds
    the provider name and the reply cap it is sent with.
    """
    if not is_anthropic_model(model):
        return ""
    return f"|provider=anthropic|max_tokens={max_output_tokens}"


@dataclass(frozen=True)
class LLMRequest:
    """Everything one attempt sends; built by ``GeminiClient`` and read by a provider.

    ``effort`` is the provider's own effort value (Claude) or None. ``uploads`` is a
    provider's uploads handle (Gemini ``ImageUploads``, Claude ``ClaudeImageUploads``).
    ``shared_prefix`` is a Gemini-only ``SharedPrefix`` for its explicit cache; on
    Claude the prefix arrives split into ``system`` and ``cache_prefix``.
    """

    model: str
    task_tag: str | None
    system: str
    prompt: str
    response_schema: type[BaseModel] | None
    images: tuple[ImageInput, ...] = ()
    documents: tuple[DocumentInput, ...] = ()
    tool: CodeExecution | None = None
    cache_plan: CachePlan = field(default_factory=CachePlan)
    effort: str | None = None
    max_output_tokens: int = 65536
    cache_prefix: str | None = None
    media_resolution: str | None = None
    uploads: Any = None
    shared_prefix: Any = None

    def fingerprint(self) -> str:
        """The provider part of this request's cache key (:func:`provider_fingerprint`)."""
        return provider_fingerprint(self.model, max_output_tokens=self.max_output_tokens)
```

Create `lemely/io/llm/provider.py`:

```python
"""What a provider returns, and the protocol every provider meets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from lemely.io.llm.request import LLMRequest


@dataclass(frozen=True)
class Usage:
    """Token counts for one Claude call, in the units ``CallRecord`` uses.

    ``input_tokens`` is the billing-equivalent input count: uncached tokens, cache
    reads, and cache writes weighted by the 1.25x premium of a 5-minute write.
    ``cached_tokens`` is the cache reads. ``output_tokens`` includes
    ``thinking_tokens``.
    """

    input_tokens: int
    cached_tokens: int
    output_tokens: int
    thinking_tokens: int


@dataclass(frozen=True)
class ProviderReply:
    """One attempt's reply.

    ``usage_response`` is what ``GeminiClient._record_spend`` reads (an object with
    ``usage_metadata``). ``stop_reason`` is normalised: ``"max_tokens"`` for a reply
    cut off at its cap, ``"refusal"`` for a refusal, else the provider's own value or
    None. ``stop_detail`` is the provider's raw value as ``str()``.
    """

    text: str
    usage_response: Any
    stop_reason: str | None
    stop_detail: str
    latency_ms: int
    usage: Usage | None = None


class Provider(Protocol):
    """Turns one request into one reply. Retry, cache and spend stay in the client."""

    def complete(self, req: LLMRequest, *, log: Any) -> ProviderReply:
        """Send ``req`` once."""
        ...

    def count_tokens(self, req: LLMRequest) -> int | None:
        """The input tokens ``req`` would bill, or None when the provider cannot say."""
        ...
```

- [ ] **Step 4: Move `Usage` and the error classes.** In `lemely/io/providers/anthropic_adapter.py` delete the `@dataclass(frozen=True) class Usage` block and add, after the `from lemely.io.providers import ...` line:

```python
from lemely.io.llm.provider import Usage
```

Leave every other use of `Usage` in the adapter as it is. In `lemely/io/gemini.py`:
  - change the `TYPE_CHECKING` import `from lemely.io.providers.anthropic_adapter import AnthropicAdapter, Usage` to import `AnthropicAdapter` only, and add `from lemely.io.llm.provider import Usage` under the same `TYPE_CHECKING` block;
  - delete the two class definitions `class _TransientError(Exception)` and `class _CapTruncatedError(ExternalServiceError)` and add at module top, after `from lemely.io.cost_ledger import CostLedger`:

```python
from lemely.io.llm.errors import CapTruncatedError as _CapTruncatedError
from lemely.io.llm.errors import TransientCallError as _TransientError
from lemely.io.llm.request import provider_fingerprint
```

  - in `_params_fingerprint`, replace the block

```python
        if is_anthropic_model(model):
            from lemely.io.providers.anthropic_adapter import MAX_OUTPUT_TOKENS

            raw += f"|provider=anthropic|max_tokens={MAX_OUTPUT_TOKENS}"
```

  with

```python
        if is_anthropic_model(model):
            from lemely.io.providers.anthropic_adapter import MAX_OUTPUT_TOKENS

            raw += provider_fingerprint(model, max_output_tokens=MAX_OUTPUT_TOKENS)
```

- [ ] **Step 5: Run the tests to see them pass.** Run `python -m pytest tests/test_llm_request.py tests/test_llm_golden.py tests/test_anthropic_adapter.py tests/test_gemini_client.py tests/test_gemini_cost_record.py -q --no-cov -o addopts=""`. Expected: all pass; the golden is unchanged.

- [ ] **Step 6: Prove the guard goes red.** In `provider_fingerprint` change `max_tokens=` to `max_tok=`; run `python -m pytest tests/test_llm_request.py tests/test_anthropic_adapter.py -q --no-cov -o addopts=""`; expect `test_claude_segment_is_todays` to fail. Revert.

- [ ] **Step 7: Source-scanning tests and commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git add -- lemely/io/llm/__init__.py lemely/io/llm/errors.py lemely/io/llm/request.py lemely/io/llm/provider.py tests/test_llm_request.py
git commit -S -m "refactor(llm): LLMRequest, Provider protocol and shared retry errors" -- lemely/io/llm/__init__.py lemely/io/llm/errors.py lemely/io/llm/request.py lemely/io/llm/provider.py lemely/io/gemini.py lemely/io/providers/anthropic_adapter.py tests/test_llm_request.py
```

---

### Task 1b: Gemini and Claude providers; client dispatch (spec T1, part 2)

**Files:**
- Create: `lemely/io/llm/gemini_provider.py`, `lemely/io/llm/claude_provider.py`
- Modify: `lemely/io/gemini.py`: `GeminiClient.__init__`; replace `_call_once` and `_call_code_execution_once`; add `_build_request`, `_provider_for_model`, `_check_stop`; delete `_call_anthropic_once` and `_usage_as_gemini_response`
- Test: `tests/test_llm_providers.py`

**Interfaces:**
- Consumes (Task 1a): `LLMRequest`, `ImageInput`, `DocumentInput`, `CodeExecution`, `ProviderReply`, `Usage`, `TransientCallError`, `CapTruncatedError`.
- Produces:
  - `GeminiProvider(client: GeminiClient)` with `complete(req, *, log) -> ProviderReply` and `count_tokens(req) -> None`.
  - `ClaudeProvider(adapter: AnthropicAdapter)` with the same two methods, and `usage_as_gemini_response(usage: Usage) -> SimpleNamespace` (moved from `gemini._usage_as_gemini_response`). Task 2b changes the constructor to `ClaudeProvider(adapter, settings)`.
  - `GeminiClient._build_request(*, model: str, task_tag: str | None, system_prompt: str, user_prompt: str, response_schema: type[BaseModel] | None, file_paths: list[Path] | None = None, image_parts: list[bytes] | None = None, media_resolution: str | None = None, image_uploads: Any = None, shared_prefix: SharedPrefix | None = None, tool: CodeExecution | None = None) -> LLMRequest`.
  - `GeminiClient._provider_for_model(model: str) -> Provider`; `GeminiClient._check_stop(reply: ProviderReply, req: LLMRequest) -> None`.
  - `_call_once` and `_call_code_execution_once` keep their signatures (tests call them).

- [ ] **Step 1: Write the failing tests.** Create `tests/test_llm_providers.py`:

```python
"""Spec 2026-10-19 §1: Gemini and Claude providers behind GeminiClient, no behaviour change."""

from __future__ import annotations

import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock

from pydantic import BaseModel, SecretStr

from lemely.io.gemini import GeminiClient
from lemely.io.llm.claude_provider import ClaudeProvider, usage_as_gemini_response
from lemely.io.llm.errors import TransientCallError
from lemely.io.llm.gemini_provider import GeminiProvider
from lemely.io.llm.provider import Usage
from lemely.io.llm.request import CodeExecution
from lemely.io.providers import ProviderTransientError
from lemely.runtime.errors import ExternalServiceError
from tests.gemini_fakes import fake_genai_client, make_settings, mock_response


class _Reply(BaseModel):
    value: str


def _client(genai: Any = None, anthropic_client: Any = None) -> GeminiClient:
    settings = make_settings(tempfile.mkdtemp()).model_copy(
        update={"anthropic_api_key": SecretStr("test-key")}
    )
    return GeminiClient(
        settings,
        _genai_client=genai or fake_genai_client(),
        _anthropic_client=anthropic_client,
        ledger=None,
    )


class GeminiProviderTests(unittest.TestCase):
    def test_reply_carries_text_stop_and_the_raw_response(self) -> None:
        genai = fake_genai_client()
        response = mock_response('{"value": "ok"}', finish_reason="MAX_TOKENS")
        genai.models.generate_content.return_value = response
        client = _client(genai)
        req = client._build_request(
            model="gemini-3.8-flash",
            task_tag="extraction",
            system_prompt="sys",
            user_prompt="user",
            response_schema=_Reply,
        )
        reply = GeminiProvider(client).complete(req, log=MagicMock())
        self.assertEqual(reply.text, '{"value": "ok"}')
        self.assertEqual(reply.stop_reason, "max_tokens")
        self.assertEqual(reply.stop_detail, str(response.candidates[0].finish_reason))
        self.assertIs(reply.usage_response, response)

    def test_transient_sdk_error_becomes_transient_call_error(self) -> None:
        genai = fake_genai_client()
        genai.models.generate_content.side_effect = Exception("503 unavailable")
        client = _client(genai)
        req = client._build_request(
            model="gemini-3.8-flash",
            task_tag="correction",
            system_prompt="s",
            user_prompt="u",
            response_schema=_Reply,
        )
        with self.assertRaises(TransientCallError):
            GeminiProvider(client).complete(req, log=MagicMock())

    def test_code_execution_reply_is_the_executed_output(self) -> None:
        genai = fake_genai_client()
        response = mock_response("", prompt=5, candidates=1)
        part = MagicMock()
        part.code_execution_result.output = "42"
        response.candidates[0].content.parts = [part]
        genai.models.generate_content.return_value = response
        client = _client(genai)
        req = client._build_request(
            model="gemini-2.5-flash",
            task_tag="question_validity",
            system_prompt="",
            user_prompt="compute",
            response_schema=None,
            tool=CodeExecution(),
        )
        self.assertEqual(GeminiProvider(client).complete(req, log=MagicMock()).text, "42")


class _RaisingAdapter:
    def complete(self, **kwargs: Any) -> Any:
        raise ProviderTransientError("529 overloaded")


class ClaudeProviderTests(unittest.TestCase):
    def test_adapter_transient_becomes_transient_call_error(self) -> None:
        client = _client()
        req = client._build_request(
            model="claude-haiku-5-5",
            task_tag="correction",
            system_prompt="s",
            user_prompt="u",
            response_schema=_Reply,
        )
        with self.assertRaises(TransientCallError):
            ClaudeProvider(_RaisingAdapter()).complete(req, log=MagicMock())  # type: ignore[arg-type]

    def test_usage_in_the_gemini_shape(self) -> None:
        shaped = usage_as_gemini_response(
            Usage(input_tokens=100, cached_tokens=40, output_tokens=30, thinking_tokens=10)
        )
        meta = shaped.usage_metadata
        self.assertEqual(
            (
                meta.prompt_token_count,
                meta.candidates_token_count,
                meta.thoughts_token_count,
                meta.cached_content_token_count,
            ),
            (100, 20, 10, 40),
        )


class DispatchTests(unittest.TestCase):
    def test_provider_by_model_prefix(self) -> None:
        client = _client(anthropic_client=MagicMock())
        self.assertIsInstance(client._provider_for_model("gemini-3.8-flash"), GeminiProvider)
        claude = client._provider_for_model("claude-haiku-5-5")
        self.assertIsInstance(claude, ClaudeProvider)
        self.assertIs(client._provider_for_model("claude-haiku-5-5"), claude)

    def test_claude_request_splits_a_shared_prefix(self) -> None:
        from lemely.io.gemini import SharedPrefix

        prefix = SharedPrefix(instructions="I", paper="P", text="IP", cache="implicit", version="v")
        client = _client()
        req = client._build_request(
            model="claude-haiku-5-5",
            task_tag="correction",
            system_prompt="IP",
            user_prompt="u",
            response_schema=_Reply,
            shared_prefix=prefix,
        )
        self.assertEqual((req.system, req.cache_prefix, req.shared_prefix), ("I", "P", None))

    def test_unknown_error_from_claude_adapter_is_not_rewrapped(self) -> None:
        class _Broken:
            def complete(self, **kwargs: Any) -> Any:
                raise ExternalServiceError("permanent")

        client = _client()
        req = client._build_request(
            model="claude-haiku-5-5",
            task_tag="correction",
            system_prompt="s",
            user_prompt="u",
            response_schema=_Reply,
        )
        with self.assertRaisesRegex(ExternalServiceError, "permanent"):
            ClaudeProvider(_Broken()).complete(req, log=MagicMock())  # type: ignore[arg-type]
```

- [ ] **Step 2: Run them to see them fail.** Run `python -m pytest tests/test_llm_providers.py -q --no-cov -o addopts=""`. Expected: `ModuleNotFoundError: No module named 'lemely.io.llm.claude_provider'`.

- [ ] **Step 3: Write `lemely/io/llm/gemini_provider.py`.** The body of today's `_call_once` Gemini branch and `_call_code_execution_once`, moved; read them side by side while you do this and keep every statement's order.

```python
"""Gemini through google-genai: GeminiClient's call code, moved here unchanged (spec §1).

Request building, the explicit prefix cache, the Files API parts and the
code-execution tool are exactly what ``GeminiClient._call_once`` and
``_call_code_execution_once`` did. Spend is recorded by the client from the
returned reply, before it looks at the stop reason, as before.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from lemely.io.llm.errors import TransientCallError
from lemely.io.llm.provider import ProviderReply
from lemely.io.providers import ProviderError
from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from pydantic import BaseModel

    from lemely.io.gemini import GeminiClient
    from lemely.io.llm.request import LLMRequest


class GeminiProvider:
    """One attempt on a Gemini model."""

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

    def count_tokens(self, req: LLMRequest) -> int | None:
        """Gemini calls are not preflighted."""
        return None

    def complete(self, req: LLMRequest, *, log: Any) -> ProviderReply:
        """Send ``req``; a transient SDK failure raises ``TransientCallError``."""
        if req.tool is not None:
            return self._complete_code_execution(req)
        from google.genai import types

        from lemely.io.gemini import (
            _MEDIA_RESOLUTION_LEVELS,
            _is_3x,
            _is_transient,
            _strip_schema,
        )

        client = self._client
        model = req.model
        media_resolution = req.media_resolution
        resolved_media_resolution = (
            _MEDIA_RESOLUTION_LEVELS.get(media_resolution, media_resolution)
            if media_resolution is not None
            else None
        )
        file_parts: list[Any] = []
        if req.uploads is not None:
            for uploaded in req.uploads.ensure():
                file_parts.append(
                    types.Part.from_uri(
                        file_uri=uploaded.uri,
                        mime_type=uploaded.mime_type,
                        media_resolution=resolved_media_resolution,
                    )
                )
        elif req.images:
            for image in req.images:
                file_parts.append(
                    types.Part.from_bytes(
                        data=image.data,
                        mime_type="image/png",
                        media_resolution=resolved_media_resolution,
                    )
                )
        elif req.documents:
            for doc in req.documents:
                if doc.source_path is None:
                    raise ProviderError("a Gemini document needs a source_path to upload")
                file_parts.append(client._client.files.upload(file=doc.source_path))

        is_3x = _is_3x(model)
        gen_params = client._resolved_gen_params(req.task_tag, model)
        schema = cast("type[BaseModel]", req.response_schema)
        stripped_schema = _strip_schema(schema.model_json_schema(), is_3x=is_3x)
        log.debug(
            "gemini_schema_sent",
            schema=schema.__name__,
            top_level_properties=list((stripped_schema.get("properties") or {}).keys()),
        )
        t0 = time.monotonic()
        config_kwargs: dict[str, Any] = {
            "max_output_tokens": req.max_output_tokens,
            "response_mime_type": "application/json",
            "system_instruction": req.system,
        }
        if is_3x:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=gen_params["thinking_level"]
            )
            config_kwargs["response_json_schema"] = stripped_schema
        else:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=gen_params["thinking_budget"]
            )
            config_kwargs["response_schema"] = stripped_schema
            config_kwargs["temperature"] = gen_params["temperature"]
            config_kwargs["top_p"] = gen_params["top_p"]
            config_kwargs["seed"] = gen_params["seed"]
        prefix = req.shared_prefix
        if prefix is not None and prefix.cache == "explicit" and is_3x:
            cache_name = client.cached_prefix_handle(model, prefix, log=log)
            if cache_name is not None:
                # The cache carries the system instruction; the API refuses both.
                del config_kwargs["system_instruction"]
                config_kwargs["cached_content"] = cache_name
        try:
            response = client._client.models.generate_content(
                model=model,
                config=types.GenerateContentConfig(**config_kwargs),
                contents=[req.prompt, *file_parts],
            )
        except Exception as exc:
            if _is_transient(exc):
                raise TransientCallError(str(exc)) from exc
            raise ExternalServiceError(str(exc)) from exc
        latency_ms = int((time.monotonic() - t0) * 1000)
        finish_reason = response.candidates[0].finish_reason if response.candidates else None
        # The SDK's FinishReason is a str-enum: str() gives "FinishReason.MAX_TOKENS",
        # so the normalised value compares the member name; stop_detail keeps str().
        name = getattr(finish_reason, "name", str(finish_reason))
        return ProviderReply(
            text=response.text or "",
            usage_response=response,
            stop_reason="max_tokens" if name == "MAX_TOKENS" else None,
            stop_detail=str(finish_reason),
            latency_ms=latency_ms,
        )

    def _complete_code_execution(self, req: LLMRequest) -> ProviderReply:
        """Gemini's ``code_execution`` tool; the reply text is what the code printed."""
        from google.genai import types

        tool = types.Tool(code_execution=types.ToolCodeExecution())
        t0 = time.monotonic()
        try:
            response = self._client._client.models.generate_content(
                model=req.model,
                config=types.GenerateContentConfig(tools=[tool]),
                contents=[req.prompt],
            )
        except Exception as exc:
            raise ExternalServiceError(str(exc)) from exc
        latency_ms = int((time.monotonic() - t0) * 1000)
        candidates = response.candidates or []
        parts = candidates[0].content.parts if candidates and candidates[0].content else []
        output = ""
        for part in parts or []:
            result = getattr(part, "code_execution_result", None)
            value = getattr(result, "output", None) if result is not None else None
            if value:
                output = str(value)
                break
        return ProviderReply(
            text=output,
            usage_response=response,
            stop_reason=None,
            stop_detail="",
            latency_ms=latency_ms,
        )
```

- [ ] **Step 4: Write `lemely/io/llm/claude_provider.py`.**

```python
"""Claude through the Anthropic adapter (spec 2026-10-19 §1).

Imports the Anthropic SDK (through the adapter), so ``GeminiClient`` imports this
module lazily, on the first ``claude-`` call.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import anthropic

from lemely.io.llm.errors import TransientCallError
from lemely.io.llm.provider import ProviderReply, Usage
from lemely.io.providers import ProviderTransientError
from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from lemely.io.llm.request import LLMRequest
    from lemely.io.providers.anthropic_adapter import AnthropicAdapter


def usage_as_gemini_response(usage: Usage) -> SimpleNamespace:
    """A Claude :class:`Usage` in the ``usage_metadata`` shape ``_record_spend`` reads.

    Gemini reports candidate and thought tokens apart; Anthropic's output total
    already includes thinking, so the candidate count is the remainder.
    """
    return SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=usage.input_tokens,
            candidates_token_count=usage.output_tokens - usage.thinking_tokens,
            thoughts_token_count=usage.thinking_tokens,
            cached_content_token_count=usage.cached_tokens,
        )
    )


class ClaudeProvider:
    """One attempt on a ``claude-`` model."""

    def __init__(self, adapter: AnthropicAdapter) -> None:
        self._adapter = adapter

    def count_tokens(self, req: LLMRequest) -> int | None:
        """Not preflighted yet (Task 2b)."""
        return None

    def complete(self, req: LLMRequest, *, log: Any) -> ProviderReply:
        """Send ``req``; 429/529/5xx/connection raise ``TransientCallError``."""
        t0 = time.monotonic()
        try:
            reply = self._adapter.complete(
                model=req.model,
                system_prompt=req.system,
                user_prompt=req.prompt,
                response_schema=req.response_schema,
                thinking=req.effort,
                cache_prefix=req.cache_prefix,
                images=[image.data for image in req.images],
            )
        except ProviderTransientError as exc:
            raise TransientCallError(str(exc)) from exc
        except ExternalServiceError:
            # ProviderError and friends already say what failed.
            raise
        except (anthropic.AnthropicError, OSError) as exc:
            # SDK and I/O failures only: a programming error propagates as itself.
            raise ExternalServiceError(str(exc)) from exc
        latency_ms = int((time.monotonic() - t0) * 1000)
        return ProviderReply(
            text=reply.text,
            usage_response=usage_as_gemini_response(reply.usage),
            stop_reason=reply.stop_reason,
            stop_detail=str(reply.stop_reason),
            latency_ms=latency_ms,
            usage=reply.usage,
        )
```

`response_schema` is `type[BaseModel] | None` on the request; `AnthropicAdapter.complete` takes `type[BaseModel]`. Keep the adapter's annotation and add `assert req.response_schema is not None` only if mypy demands it; do not change the adapter's signature in this task.

- [ ] **Step 5: Rewire `GeminiClient`.** In `lemely/io/gemini.py`:

Add imports at module top (no SDK loads):

```python
from lemely.io.llm.gemini_provider import GeminiProvider
from lemely.io.llm.request import CodeExecution, DocumentInput, ImageInput, LLMRequest
from lemely.io.providers import ProviderError
```

and under `TYPE_CHECKING`:

```python
    from lemely.io.llm.claude_provider import ClaudeProvider
    from lemely.io.llm.provider import Provider, ProviderReply
```

At the end of `GeminiClient.__init__` add:

```python
        self._gemini_provider = GeminiProvider(self)
        self._claude_provider: ClaudeProvider | None = None
```

Add these methods after `_retry_policy`:

```python
    def _provider_for_model(self, model: str) -> Provider:
        """The provider for ``model``'s prefix; the Claude one is built on first use."""
        if is_anthropic_model(model):
            if self._claude_provider is None:
                from lemely.io.llm.claude_provider import ClaudeProvider

                self._claude_provider = ClaudeProvider(self._anthropic)
            return self._claude_provider
        return self._gemini_provider

    def _build_request(
        self,
        *,
        model: str,
        task_tag: str | None,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel] | None,
        file_paths: list[Path] | None = None,
        image_parts: list[bytes] | None = None,
        media_resolution: str | None = None,
        image_uploads: Any = None,
        shared_prefix: SharedPrefix | None = None,
        tool: CodeExecution | None = None,
    ) -> LLMRequest:
        """The one request an attempt sends (spec §1)."""
        on_claude = is_anthropic_model(model)
        if on_claude:
            from lemely.io.providers.anthropic_adapter import MAX_OUTPUT_TOKENS

            cap = MAX_OUTPUT_TOKENS
            effort: str | None = self._resolved_gen_params(task_tag, model)["thinking_level"]
        else:
            cap = self._output_cap(task_tag)[0]
            effort = None
        split = on_claude and shared_prefix is not None
        return LLMRequest(
            model=model,
            task_tag=task_tag,
            system=shared_prefix.instructions if split and shared_prefix else system_prompt,
            prompt=user_prompt,
            response_schema=response_schema,
            images=tuple(ImageInput(data) for data in (image_parts or ())),
            documents=tuple(DocumentInput.from_path(fp) for fp in (file_paths or ())),
            tool=tool,
            effort=effort,
            max_output_tokens=cap,
            cache_prefix=shared_prefix.paper if split and shared_prefix else None,
            media_resolution=media_resolution,
            uploads=None if on_claude else image_uploads,
            shared_prefix=None if on_claude else shared_prefix,
        )

    def _check_stop(self, reply: ProviderReply, req: LLMRequest) -> None:
        """The stop rules each provider had, applied after the spend is recorded."""
        model, task_tag = req.model, req.task_tag
        if is_anthropic_model(model):
            if reply.stop_reason == "max_tokens":
                # Billed (recorded already), marked unparsed, not transient: one
                # fresh retry in _call_with_retry, then this raises.
                _mark_last_record_unparsed()
                raise _CapTruncatedError(
                    f"Anthropic hit the {req.max_output_tokens}-token max_tokens "
                    f"for {task_tag} ({model})"
                )
            if reply.stop_reason == "refusal":
                raise ProviderError(f"Anthropic refused the request ({model})")
            return
        output_cap, cap_is_per_tag = self._output_cap(task_tag)
        if cap_is_per_tag:
            if reply.stop_reason == "max_tokens":
                _mark_last_record_unparsed()
                raise _CapTruncatedError(
                    f"Gemini hit the {output_cap}-token output cap for {task_tag} ({model})"
                )
        elif reply.stop_detail == "MAX_TOKENS":
            # Inert against the real SDK (str() of the enum is
            # "FinishReason.MAX_TOKENS"); kept as it was, see the history of _call_once.
            raise _TransientError(f"Gemini hit max_output_tokens ({model})")
```

Replace the whole body of `_call_once` (keep its signature) with:

```python
        req = self._build_request(
            model=model,
            task_tag=task_tag,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            file_paths=file_paths,
            image_parts=image_parts,
            media_resolution=media_resolution,
            image_uploads=image_uploads,
            shared_prefix=shared_prefix,
        )
        reply = self._provider_for_model(model).complete(req, log=log)
        self._record_spend(
            response=reply.usage_response,
            model=model,
            task_tag=task_tag,
            latency_ms=reply.latency_ms,
            log=log,
            params_fingerprint=self._params_fingerprint(
                model, task_tag, response_schema, media_resolution=media_resolution
            ),
        )
        self._check_stop(reply, req)
        return reply.text
```

Replace the whole body of `_call_code_execution_once` (keep its signature and docstring's `Raises:` section) with:

```python
        req = self._build_request(
            model=model,
            task_tag=task_tag,
            system_prompt="",
            user_prompt=prompt,
            response_schema=None,
            tool=CodeExecution(),
        )
        reply = self._provider_for_model(model).complete(req, log=log)
        self._record_spend(
            response=reply.usage_response,
            model=model,
            task_tag=task_tag,
            latency_ms=reply.latency_ms,
            log=log,
            params_fingerprint=params_fingerprint,
            extra_log_fields={"latency_ms": reply.latency_ms, "tool": "code_execution"},
            sends_thinking=False,
        )
        if reply.text:
            return reply.text
        raise ParseError(
            f"Gemini code_execution call ({model}) returned no code_execution_result part."
        )
```

Delete `_call_anthropic_once` and the module function `_usage_as_gemini_response`. Delete any import that is now unused (ruff will name them).

- [ ] **Step 6: Run the tests.** Run `python -m pytest tests/test_llm_providers.py tests/test_llm_golden.py tests/test_llm_request.py tests/test_anthropic_adapter.py tests/test_gemini_client.py tests/test_gemini_cost_record.py tests/test_gemini_output_cap.py tests/test_gemini_cache_mode_for.py tests/test_gemini_cache_forget.py tests/test_correction_shared_prefix.py tests/test_question_generation.py -q --no-cov -o addopts=""`. Expected: all pass, the golden unchanged (`git diff --stat -- tests/fixtures` empty).

- [ ] **Step 7: Prove the golden guards the move.** In `GeminiProvider.complete` swap the order of `[req.prompt, *file_parts]` to `[*file_parts, req.prompt]`; run `python -m pytest tests/test_llm_golden.py -q --no-cov -o addopts=""`; expect failures in `extraction_inline_images`, `extraction_files_api` and `mark_scheme_pdf`. Revert.

- [ ] **Step 8: Source-scanning tests and commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git add -- lemely/io/llm/gemini_provider.py lemely/io/llm/claude_provider.py tests/test_llm_providers.py
git commit -S -m "refactor(llm): move Gemini and Claude call code into providers behind GeminiClient" -- lemely/io/llm/gemini_provider.py lemely/io/llm/claude_provider.py lemely/io/gemini.py tests/test_llm_providers.py
```

---
### Task 2a: The image-fit policy (spec T2, part 1; §2 steps 1-6)

**Files:**
- Create: `lemely/io/llm/image_fit.py`
- Test: `tests/test_image_fit.py`

**Interfaces:**
- Consumes: `lemely.io.providers.ProviderError`.
- Produces (all in `lemely.io.llm.image_fit`):
  - Constants: `IMG_FIT_VERSION = "v1"`, `LONG_EDGE_STEPS = (2576, 2200, 2000, 1800, 1568)`, `MANY_IMAGES_THRESHOLD = 20`, `MANY_IMAGES_LONG_EDGE = 2000`, `DEFAULT_TOKEN_BUDGET = 95_000`, `DEFAULT_BYTE_LIMIT = 30_000_000`, `DEFAULT_FLOOR_PX = 1568`, `THUMBNAIL_LONG_EDGE = 768`, `PIXELS_PER_TOKEN = 750`.
  - `FittedImages(images: tuple[bytes, ...], long_edge: int, est_tokens: int, page_tokens: tuple[int, ...], base64_bytes: int, over_token_budget: bool, over_byte_limit: bool, colour_pages: tuple[int, ...])` (frozen; `colour_pages` are 1-based).
  - `estimate_tokens(width: int, height: int) -> int`, `base64_len(n: int) -> int`, `has_colour_ink(img: Image.Image) -> bool`, `steps_for(floor_px: int, count: int) -> tuple[int, ...]`.
  - `fit(images: Sequence[bytes], *, byte_limit: int | None = DEFAULT_BYTE_LIMIT, token_budget: int = DEFAULT_TOKEN_BUDGET, floor_px: int = DEFAULT_FLOOR_PX) -> FittedImages`. Never raises for being over a budget: the caller decides (byte limit at the floor is the caller's refusal; token budget at the floor is the caller's tier warning or chunked read).
  - `thumbnails(images: Sequence[bytes], *, long_edge: int = THUMBNAIL_LONG_EDGE) -> tuple[bytes, ...]` (greyscale PNG, for the overview pass of Task 10).

Policy decisions this task makes (recorded for the reviewer):
- "Meaningful colour ink" = at least two saturated hue families (six 60° families, red centred on 0°) each covering at least 0.1% of the page. One ink colour (a blue pen) carries no information greyscale loses.
- An image that is already a greyscale PNG (or a colour-kept RGB PNG) within the step's edge is sent byte for byte: no re-encode, so its bytes and the cache key built from them stay as they came.
- To bound memory on a 19-page script, every page is scaled once to the first step's edge and later steps resample from that copy.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_image_fit.py`:

```python
"""Spec 2026-10-19 §2: greyscale, token and byte budgets, floor, and a real-size fixture."""

from __future__ import annotations

import functools
import io
import random
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from lemely.io.llm import image_fit
from lemely.io.llm.image_fit import (
    DEFAULT_BYTE_LIMIT,
    DEFAULT_TOKEN_BUDGET,
    estimate_tokens,
    fit,
    has_colour_ink,
    steps_for,
    thumbnails,
)
from lemely.io.providers import ProviderError

_REAL_W, _REAL_H = 2430, 3439
#: Paper noise levels per channel; calibrated in Task 2a step 6 against the real script.
_NOISE_LEVELS = 7


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _page(width: int, height: int, *, inks: tuple[tuple[int, int, int], ...] = ()) -> bytes:
    """A white RGB page with a thick stroke in each ink colour."""
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for i, ink in enumerate(inks):
        top = height // 4 + i * height // 4
        draw.rectangle([width // 10, top, width * 9 // 10, top + height // 20], fill=ink)
    return _png(img)


@functools.lru_cache(maxsize=1)
def _realistic_page() -> bytes:
    """One 2430x3439 RGB scan page: noisy near-white paper and 40 lines of blue writing."""
    rng = random.Random(41)
    channels = [
        Image.frombytes("L", (_REAL_W, _REAL_H), rng.randbytes(_REAL_W * _REAL_H)).point(
            lambda v: 255 - _NOISE_LEVELS + v % _NOISE_LEVELS
        )
        for _ in range(3)
    ]
    page = Image.merge("RGB", channels)
    draw = ImageDraw.Draw(page)
    for line in range(40):
        y = 300 + line * 75
        for x in range(200, 2200, 9):
            draw.line(
                [(x, y + rng.randint(-12, 12)), (x + 9, y + rng.randint(-12, 12))],
                fill=(30, 40, 140),
                width=3,
            )
    return _png(page)


class ColourTests(unittest.TestCase):
    def test_one_ink_is_not_meaningful_colour(self) -> None:
        img = Image.open(io.BytesIO(_page(800, 1100, inks=((30, 40, 140),))))
        self.assertFalse(has_colour_ink(img.convert("RGB")))

    def test_two_inks_are_meaningful_colour(self) -> None:
        img = Image.open(io.BytesIO(_page(800, 1100, inks=((30, 40, 140), (200, 20, 20)))))
        self.assertTrue(has_colour_ink(img.convert("RGB")))

    def test_single_ink_page_is_sent_greyscale(self) -> None:
        fitted = fit([_page(800, 1100, inks=((30, 40, 140),))])
        with Image.open(io.BytesIO(fitted.images[0])) as sent:
            self.assertEqual(sent.mode, "L")
        self.assertEqual(fitted.colour_pages, ())

    def test_two_ink_page_keeps_its_colour(self) -> None:
        fitted = fit([_page(800, 1100), _page(800, 1100, inks=((30, 40, 140), (200, 20, 20)))])
        with Image.open(io.BytesIO(fitted.images[1])) as sent:
            self.assertEqual(sent.mode, "RGB")
        self.assertEqual(fitted.colour_pages, (2,))

    def test_greyscale_png_within_the_edge_is_sent_byte_for_byte(self) -> None:
        grey = _png(Image.new("L", (300, 400), 200))
        self.assertEqual(fit([grey]).images, (grey,))


class BudgetTests(unittest.TestCase):
    def test_estimate_is_area_over_750_rounded_up(self) -> None:
        self.assertEqual(estimate_tokens(750, 1), 1)
        self.assertEqual(estimate_tokens(751, 1), 2)

    def test_steps(self) -> None:
        self.assertEqual(steps_for(1568, 19), (2576, 2200, 2000, 1800, 1568))
        self.assertEqual(steps_for(1568, 21), (2000, 1800, 1568))
        self.assertEqual(steps_for(1900, 19), (2576, 2200, 2000, 1900))

    def test_nineteen_real_size_pages_step_down_to_2200(self) -> None:
        """2576: 19 x 6252 = 118,788 tokens, over 95k. 2200: 19 x 4559 = 86,621, under."""
        fitted = fit([_page(_REAL_W, _REAL_H, inks=((30, 40, 140),))] * 19)
        self.assertEqual(fitted.long_edge, 2200)
        self.assertLessEqual(fitted.est_tokens, DEFAULT_TOKEN_BUDGET)
        self.assertFalse(fitted.over_token_budget)
        self.assertEqual(len(fitted.page_tokens), 19)
        self.assertEqual(sum(fitted.page_tokens), fitted.est_tokens)

    def test_forty_five_pages_are_over_the_budget_at_the_floor(self) -> None:
        fitted = fit([_page(_REAL_W, _REAL_H)] * 45)
        self.assertEqual(fitted.long_edge, 1568)
        self.assertTrue(fitted.over_token_budget)
        self.assertFalse(fitted.over_byte_limit)

    def test_byte_limit_at_the_floor_is_reported_not_raised(self) -> None:
        fitted = fit([_page(1000, 1400)] * 3, byte_limit=100)
        self.assertTrue(fitted.over_byte_limit)
        self.assertEqual(fitted.long_edge, 1568)

    def test_no_byte_limit_for_file_uploads(self) -> None:
        self.assertFalse(fit([_page(1000, 1400)], byte_limit=None).over_byte_limit)

    def test_order_is_kept(self) -> None:
        a, b = _png(Image.new("L", (10, 10), 0)), _png(Image.new("L", (12, 10), 255))
        self.assertEqual(fit([a, b]).images, (a, b))

    def test_fit_is_deterministic(self) -> None:
        pages = [_page(_REAL_W, _REAL_H, inks=((30, 40, 140),))] * 2
        self.assertEqual(fit(pages).images, fit(pages).images)


class ErrorTests(unittest.TestCase):
    def test_unreadable_page_names_its_number(self) -> None:
        good = _png(Image.new("L", (10, 10), 0))
        with self.assertRaisesRegex(ProviderError, "page 2"):
            fit([good, b"\x89PNG\r\n\x1a\n-truncated"])

    def test_encode_error_is_a_provider_error_naming_the_page(self) -> None:
        big = _page(3000, 3000)
        with (
            patch.object(Image.Image, "save", side_effect=OSError("disk")),
            self.assertRaisesRegex(ProviderError, "page 1 could not be encoded"),
        ):
            fit([big])


class ThumbnailTests(unittest.TestCase):
    def test_thumbnails_are_greyscale_at_768(self) -> None:
        (thumb,) = thumbnails([_page(_REAL_W, _REAL_H, inks=((30, 40, 140), (200, 20, 20)))])
        with Image.open(io.BytesIO(thumb)) as img:
            self.assertEqual(img.mode, "L")
            self.assertEqual(max(img.size), 768)


class RealisticFixtureTests(unittest.TestCase):
    """Spec §7: 19 pages at 2430x3439, noisy RGB, fit under both limits at or above the floor."""

    def test_nineteen_noisy_pages_fit_under_both_limits(self) -> None:
        fitted = fit([_realistic_page()] * 19)
        self.assertGreaterEqual(fitted.long_edge, 1568)
        self.assertLessEqual(fitted.base64_bytes, DEFAULT_BYTE_LIMIT)
        self.assertLessEqual(fitted.est_tokens, DEFAULT_TOKEN_BUDGET)
        self.assertFalse(fitted.over_byte_limit or fitted.over_token_budget)
        self.assertEqual(fitted.colour_pages, ())

    def test_the_fixture_is_at_least_as_hard_as_the_real_scan(self) -> None:
        """Its 2576-edge RGB page is no smaller than the real script's (Task 2a step 6)."""
        with Image.open(io.BytesIO(_realistic_page())) as img:
            scale = 2576 / max(img.size)
            size = (round(img.width * scale), round(img.height * scale))
            rgb = _png(img.resize(size, Image.Resampling.LANCZOS))
        self.assertGreaterEqual(image_fit.base64_len(len(rgb)), _REAL_SCAN_B64_PER_PAGE)


#: Median base64 bytes of one real-script page at 2576 px RGB, measured in step 6.
_REAL_SCAN_B64_PER_PAGE = 4_190_000
```

- [ ] **Step 2: Run them to see them fail.** Run `python -m pytest tests/test_image_fit.py -q --no-cov -o addopts=""`. Expected: `ModuleNotFoundError: No module named 'lemely.io.llm.image_fit'` (if Task 1a has not landed yet in this worktree, `No module named 'lemely.io.llm'`; create an empty `lemely/io/llm/__init__.py` only if Task 1a has not, and do not commit it from this task).

- [ ] **Step 3: Write `lemely/io/llm/image_fit.py`.**

```python
"""Fit page images under Claude's token and byte limits (spec 2026-10-19 §2).

Pure: Pillow only, no I/O, no SDK. The result is deterministic in the input bytes
and the constants below; ``IMG_FIT_VERSION`` goes into the Claude cache key, so a
policy change invalidates replies cached under the old one.

1. Greyscale every page, unless it carries meaningful colour (two or more ink
   colours, :func:`has_colour_ink`).
2. Estimate tokens per page as ``w * h / 750``.
3. Step the long edge down (2576, 2200, 2000, 1800, then the floor) while the
   request is over ``token_budget`` or ``byte_limit``.
4. Stop at ``floor_px``: below it handwriting is treated as unreadable. Being over a
   budget there is reported in the result, never raised: the caller decides.
"""

from __future__ import annotations

import io
import math
from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from lemely.io.providers import ProviderError

IMG_FIT_VERSION = "v1"
LONG_EDGE_STEPS: tuple[int, ...] = (2576, 2200, 2000, 1800, 1568)
#: Above this many images in one request the API holds each to MANY_IMAGES_LONG_EDGE.
MANY_IMAGES_THRESHOLD = 20
MANY_IMAGES_LONG_EDGE = 2000
#: The 100k Haiku price-tier line, less headroom for the prompt.
DEFAULT_TOKEN_BUDGET = 95_000
#: Inline base64 bytes of images per request: the 32 MB request limit less room.
DEFAULT_BYTE_LIMIT = 30_000_000
#: About 135 DPI on A4.
DEFAULT_FLOOR_PX = 1568
THUMBNAIL_LONG_EDGE = 768
PIXELS_PER_TOKEN = 750

_GREY_MODES = frozenset({"1", "L", "LA", "I", "I;16", "F"})
_COLOUR_SAMPLE_EDGE = 256
_SATURATION_MIN = 90
_VALUE_MIN = 60
_HUE_FAMILIES = 6
#: Shift so that red (hue near 0 and near 255) falls in one family.
_HUE_SHIFT = 21
_HUE_FAMILY_MIN_SHARE = 0.001


@dataclass(frozen=True)
class FittedImages:
    """The pages as they will be sent, and what the fit found."""

    images: tuple[bytes, ...]
    long_edge: int
    est_tokens: int
    page_tokens: tuple[int, ...]
    base64_bytes: int
    over_token_budget: bool
    over_byte_limit: bool
    colour_pages: tuple[int, ...]


@dataclass(frozen=True)
class _Page:
    original: bytes
    image: Image.Image
    as_is: bool


def estimate_tokens(width: int, height: int) -> int:
    """Claude's image-token estimate for a ``width`` x ``height`` image."""
    return math.ceil(width * height / PIXELS_PER_TOKEN)


def base64_len(n: int) -> int:
    """Length of ``n`` bytes once base64-encoded."""
    return 4 * math.ceil(n / 3)


def has_colour_ink(img: Image.Image) -> bool:
    """True when two or more saturated hue families each cover 0.1% of the page."""
    sample = img.convert("RGB")
    sample.thumbnail((_COLOUR_SAMPLE_EDGE, _COLOUR_SAMPLE_EDGE))
    hue, sat, val = sample.convert("HSV").split()
    total = sample.width * sample.height
    counts = [0] * _HUE_FAMILIES
    for h, s, v in zip(hue.getdata(), sat.getdata(), val.getdata(), strict=True):
        if s >= _SATURATION_MIN and v >= _VALUE_MIN:
            counts[((h + _HUE_SHIFT) % 256) * _HUE_FAMILIES // 256] += 1
    return sum(1 for c in counts if c / total >= _HUE_FAMILY_MIN_SHARE) >= 2


def steps_for(floor_px: int, count: int) -> tuple[int, ...]:
    """The long edges tried, largest first, ending at the floor."""
    start = MANY_IMAGES_LONG_EDGE if count > MANY_IMAGES_THRESHOLD else LONG_EDGE_STEPS[0]
    if floor_px >= start:
        return (start,)
    return (*(s for s in LONG_EDGE_STEPS if floor_px < s <= start), floor_px)


def _size_at(width: int, height: int, long_edge: int) -> tuple[int, int]:
    if max(width, height) <= long_edge:
        return width, height
    scale = long_edge / max(width, height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _resized(img: Image.Image, long_edge: int) -> Image.Image:
    size = _size_at(img.width, img.height, long_edge)
    if size == img.size:
        return img
    return img.resize(size, Image.Resampling.LANCZOS)


def _prepare(data: bytes, page: int, first_edge: int) -> tuple[_Page, bool]:
    """The page decoded, greyscaled unless meaningful colour, held to ``first_edge``."""
    try:
        with Image.open(io.BytesIO(data)) as src:
            src.load()
            fmt = src.format
            if src.mode in _GREY_MODES:
                work, colour = src.convert("L"), False
            else:
                rgb = src.convert("RGB")
                colour = has_colour_ink(rgb)
                work = rgb if colour else rgb.convert("L")
            as_is = fmt == "PNG" and src.mode == ("RGB" if colour else "L")
            if max(work.size) > first_edge:
                work, as_is = _resized(work, first_edge), False
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ProviderError(f"page {page} could not be read as an image: {exc}") from exc
    return _Page(original=data, image=work, as_is=as_is), colour


def _encode(page: _Page, long_edge: int, number: int) -> bytes:
    if page.as_is and max(page.image.size) <= long_edge:
        return page.original
    try:
        out = io.BytesIO()
        _resized(page.image, long_edge).save(out, "PNG")
    except (OSError, ValueError) as exc:
        raise ProviderError(f"page {number} could not be encoded: {exc}") from exc
    return out.getvalue()


def fit(
    images: Sequence[bytes],
    *,
    byte_limit: int | None = DEFAULT_BYTE_LIMIT,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    floor_px: int = DEFAULT_FLOOR_PX,
) -> FittedImages:
    """``images`` greyscaled and stepped down until under both limits, or at the floor.

    ``byte_limit`` None means the images go by Files API id: no inline limit.

    Raises:
        ProviderError: a page cannot be read or encoded (named by its 1-based number).
        ValueError: ``floor_px`` is less than 1.
    """
    if floor_px < 1:
        raise ValueError(f"floor_px must be positive, got {floor_px}")
    steps = steps_for(floor_px, len(images))
    pages: list[_Page] = []
    colour_pages: list[int] = []
    for number, data in enumerate(images, start=1):
        page, colour = _prepare(data, number, steps[0])
        pages.append(page)
        if colour:
            colour_pages.append(number)
    for edge in steps:
        page_tokens = tuple(
            estimate_tokens(*_size_at(p.image.width, p.image.height, edge)) for p in pages
        )
        tokens = sum(page_tokens)
        last = edge == steps[-1]
        if tokens > token_budget and not last:
            continue
        encoded = tuple(_encode(p, edge, n) for n, p in enumerate(pages, start=1))
        b64 = sum(base64_len(len(e)) for e in encoded)
        over_tokens = tokens > token_budget
        over_bytes = byte_limit is not None and b64 > byte_limit
        if last or not (over_tokens or over_bytes):
            return FittedImages(
                images=encoded,
                long_edge=edge,
                est_tokens=tokens,
                page_tokens=page_tokens,
                base64_bytes=b64,
                over_token_budget=over_tokens,
                over_byte_limit=over_bytes,
                colour_pages=tuple(colour_pages),
            )
    raise AssertionError("unreachable: the last step always returns")  # pragma: no cover


def thumbnails(images: Sequence[bytes], *, long_edge: int = THUMBNAIL_LONG_EDGE) -> tuple[bytes, ...]:
    """Greyscale PNG thumbnails, ``long_edge`` on the long side, for an overview pass."""
    out: list[bytes] = []
    for number, data in enumerate(images, start=1):
        page = _Page(original=data, image=_prepare(data, number, long_edge)[0].image.convert("L"), as_is=False)
        out.append(_encode(page, long_edge, number))
    return tuple(out)
```

- [ ] **Step 4: Run the tests.** Run `python -m pytest tests/test_image_fit.py -q --no-cov -o addopts=""`. Expected: all pass except possibly `test_the_fixture_is_at_least_as_hard_as_the_real_scan`, which step 6 settles. The file takes up to about a minute (19 full-size pages); that is accepted for this one fixture.

- [ ] **Step 5: Prove the guards go red.** (a) In `fit`, change `if tokens > token_budget and not last:` to `if False:`; `test_nineteen_real_size_pages_step_down_to_2200` must fail (it returns at 2576). Revert. (b) In `_encode`, move the `.save(...)` call out of the `try`; `test_encode_error_is_a_provider_error_naming_the_page` must fail with a bare `OSError`. Revert.

- [ ] **Step 6: Calibrate the fixture against the real script.** Write a scratch script in your scratchpad (not in the repo) and run it:

```python
import io
import statistics
from pathlib import Path

from PIL import Image

from lemely.io.llm.image_fit import base64_len, fit
from lemely.io.rasterise import rasterise_pdf_to_pages

SCAN = Path("/home/sico/Documents/P4 N24 V1_annotated (NO Corrections).pdf")
pages = rasterise_pdf_to_pages(SCAN)
sizes = []
for p in pages:
    with Image.open(io.BytesIO(p.png_bytes)) as img:
        rgb = img.convert("RGB")
        scale = 2576 / max(rgb.size)
        rgb = rgb.resize((round(rgb.width * scale), round(rgb.height * scale)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        rgb.save(buf, "PNG")
        sizes.append(base64_len(len(buf.getvalue())))
print("pages", len(pages), "size", pages[0].width, pages[0].height)
print("median b64 per page at 2576 RGB", statistics.median(sizes), "total", sum(sizes))
fitted = fit([p.png_bytes for p in pages])
print("fit", fitted.long_edge, fitted.est_tokens, fitted.base64_bytes, fitted.colour_pages)
```

Expected: 19 pages, about 2430x3439, a total near the review's 79.6 MB. Set `_REAL_SCAN_B64_PER_PAGE` in the test to the printed median (rounded down to 10,000). If `test_the_fixture_is_at_least_as_hard_as_the_real_scan` then fails, raise `_NOISE_LEVELS` one step at a time until it passes; if `test_nineteen_noisy_pages_fit_under_both_limits` then fails, stop and report both numbers: it means a real script cannot be sent inline at the floor, and Task 2c's Files API path becomes required rather than preferred. Record the printed `fit` line (long edge, tokens, bytes, colour pages) in the commit message body; that is the real script's fit.

- [ ] **Step 7: Commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
pre-commit run --all-files
git add -- lemely/io/llm/image_fit.py tests/test_image_fit.py
git commit -S -m "feat(llm): image_fit greyscales and steps page images under Claude's limits" -- lemely/io/llm/image_fit.py tests/test_image_fit.py
```

---

### Task 2b: Claude images through image_fit; output cap; cache-key version (spec T2, part 2)

Fixes the review findings on `188542b1`/`4e065532`: the critical byte limit (pages are now fitted, refused only at the floor), the fixed 16,000-token cap, the missing preprocessing version in the cache key, `save` outside the `try` (the adapter's `_fit` is deleted; `image_fit` encodes inside its `try`), and the stale `second_read_model` TOML comment.

**Files:**
- Modify: `lemely/io/llm/request.py` (`provider_fingerprint` gains `img_fit`)
- Modify: `lemely/io/llm/claude_provider.py` (fit, refusal, tier warning, preflight, cap; constructor takes settings)
- Modify: `lemely/io/providers/anthropic_adapter.py` (no resizing; file-id blocks; `max_tokens`; streaming; `count_tokens`; `_send`)
- Modify: `lemely/io/gemini.py` (`_claude_output_cap`; `_params_fingerprint` and `_build_request` use it; `ClaudeProvider(self._anthropic, self._settings)`)
- Modify: `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`
- Test: `tests/test_claude_images.py` (new); `tests/test_anthropic_adapter.py` (fakes extended; four moved tests deleted)

**Interfaces:**
- Consumes: Task 2a `fit`, `FittedImages`, `IMG_FIT_VERSION`, `DEFAULT_BYTE_LIMIT`; Task 1b `ClaudeProvider`, `_build_request`.
- Produces:
  - `provider_fingerprint(model, *, max_output_tokens) -> str` now returns `"|provider=anthropic|max_tokens={cap}|img_fit=v1"` for `claude-` models (still `""` for Gemini).
  - `GeminiSettings.claude_image_token_budget: int = 95_000` (`gt=0`), `GeminiSettings.claude_image_floor_px: int = 1568` (`ge=256`).
  - `GeminiClient._claude_output_cap(task_tag: str | None) -> int`: `max_output_tokens_for[tag]` when set, else the adapter's `MAX_OUTPUT_TOKENS` (16,000).
  - `ClaudeProvider(adapter: AnthropicAdapter, settings: Settings)`; `ClaudeProvider._fit(req: LLMRequest, *, inline: bool) -> FittedImages`; `ClaudeProvider.count_tokens(req) -> int | None` (real, via the adapter; None on error).
  - `anthropic_adapter.NONSTREAMING_MAX_TOKENS = 21_333`; `image_blocks(images)` (validates, never resizes); `file_image_blocks(file_ids: Sequence[str])`; `AnthropicAdapter.complete(..., images=(), image_file_ids=(), max_tokens=MAX_OUTPUT_TOKENS)`; `AnthropicAdapter.count_tokens(*, model, system_prompt, user_prompt, cache_prefix, images=(), image_file_ids=()) -> int`.
  - Log events: `claude_over_tier` (fields `pages`, `est_tokens`, `long_edge`, `tag`) and `claude_token_preflight` (`est_tokens`, `counted_tokens`, `tag`).
  - `claude_provider.PREFLIGHT_SHARE = 0.9`.

- [ ] **Step 1: Extend the SDK fakes.** In `tests/test_anthropic_adapter.py` replace `_FakeMessages` and `_FakeAnthropic` with:

```python
class _FakeStream:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome

    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_final_message(self) -> object:
        return self._outcome


class _FakeMessages:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.streamed: list[dict[str, Any]] = []
        self.count_calls: list[dict[str, Any]] = []
        self.count_result = 1_000

    def _next(self) -> object:
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return self._next()

    def stream(self, **kwargs: Any) -> _FakeStream:
        self.calls.append(kwargs)
        self.streamed.append(kwargs)
        return _FakeStream(self._next())

    def count_tokens(self, **kwargs: Any) -> object:
        self.count_calls.append(kwargs)
        return SimpleNamespace(input_tokens=self.count_result)


class _FakeAnthropic:
    """Stands in for ``anthropic.Anthropic``: ``messages`` and ``files``."""

    def __init__(self, *outcomes: object) -> None:
        self.messages = _FakeMessages(list(outcomes))
        self.files = MagicMock()
```

Delete these four adapter tests (the behaviour moved to `image_fit` and is covered by `tests/test_image_fit.py` and `tests/test_claude_images.py`): `test_a_page_over_the_native_long_edge_is_downscaled`, `test_a_jpeg_page_stays_jpeg_when_downscaled`, `test_more_than_twenty_pages_are_held_to_the_many_image_edge`, `test_pages_over_the_request_size_are_refused`, and drop `MANY_IMAGES_LONG_EDGE`, `MAX_LONG_EDGE` from the import list. In `test_bytes_that_are_not_png_or_jpeg_are_refused`, drop the `b"\x89PNG\r\n\x1a\n-truncated"` case (the adapter no longer decodes; `tests/test_image_fit.py::ErrorTests` covers a truncated page).

- [ ] **Step 2: Write the failing tests.** Create `tests/test_claude_images.py`:

```python
"""Spec 2026-10-19 §2 on the Claude path: fit, refusal at the floor, tier warning,
preflight, output cap and the img_fit cache-key version."""

from __future__ import annotations

import io
import tempfile
import unittest
from datetime import date
from typing import Any
from unittest.mock import patch

from PIL import Image, ImageDraw
from structlog.testing import capture_logs

from lemely.core.schemas import AIMarkResponse
from lemely.io.gemini import GeminiClient, _reset_process_counters, record_calls
from lemely.io.llm import image_fit
from lemely.io.providers import ProviderError
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _sent_images, _settings

_HAIKU = "claude-haiku-5-5"


def _scan_page(width: int = 2430, height: int = 3439) -> bytes:
    img = Image.new("RGB", (width, height), (255, 255, 255))
    ImageDraw.Draw(img).rectangle([200, 400, 2000, 500], fill=(30, 40, 140))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)

    def _client(self, *outcomes: object, **gemini: Any) -> tuple[GeminiClient, _FakeAnthropic]:
        settings = _settings(self.tmp)
        if gemini:
            settings = settings.model_copy(
                update={"gemini": settings.gemini.model_copy(update=gemini)}
            )
        fake = _FakeAnthropic(*outcomes)
        return GeminiClient(settings, _genai_client=object(), _anthropic_client=fake, ledger=None), fake

    def _read(self, client: GeminiClient, pages: list[bytes], tag: str = "binding_second_read") -> None:
        client.generate_structured(
            system_prompt="sys",
            user_prompt="read",
            image_parts=pages,
            response_schema=AIMarkResponse,
            prompt_version="v1",
            model=_HAIKU,
            task_tag=tag,
        )


class FitOnTheWireTests(_Base):
    def test_real_size_pages_are_fitted_and_greyscaled(self) -> None:
        client, fake = self._client(_message(_VALID_MARK))
        self._read(client, [_scan_page()] * 19)
        sent = _sent_images(fake.messages.calls[0])
        self.assertEqual(len(sent), 19)
        for media_type, data in sent:
            self.assertEqual(media_type, "image/png")
            with Image.open(io.BytesIO(data)) as img:
                self.assertEqual((img.mode, max(img.size)), ("L", 2200))

    def test_inline_bytes_over_the_limit_at_the_floor_are_refused(self) -> None:
        client, fake = self._client(_message(_VALID_MARK))
        with (
            patch.object(image_fit, "DEFAULT_BYTE_LIMIT", 100),
            self.assertRaisesRegex(ProviderError, r"3 pages .* bytes"),
        ):
            self._read(client, [_scan_page(1000, 1400)] * 3)
        self.assertEqual(fake.messages.calls, [])

    def test_over_budget_at_the_floor_is_sent_and_logged(self) -> None:
        client, fake = self._client(_message(_VALID_MARK), claude_image_token_budget=1_000)
        with capture_logs() as logs:
            self._read(client, [_scan_page(1000, 1400)] * 3)
        self.assertEqual(len(fake.messages.calls), 1)
        (over,) = [e for e in logs if e["event"] == "claude_over_tier"]
        self.assertEqual((over["pages"], over["tag"]), (3, "binding_second_read"))
        self.assertGreater(over["est_tokens"], 1_000)

    def test_preflight_counts_tokens_near_the_budget(self) -> None:
        # One 1000x1400 page is 1,867 estimated tokens: within 10% of a 2,000 budget.
        client, fake = self._client(_message(_VALID_MARK), claude_image_token_budget=2_000)
        with capture_logs() as logs:
            self._read(client, [_scan_page(1000, 1400)])
        self.assertEqual(len(fake.messages.count_calls), 1)
        (pre,) = [e for e in logs if e["event"] == "claude_token_preflight"]
        self.assertEqual((pre["est_tokens"], pre["counted_tokens"]), (1_867, 1_000))

    def test_no_preflight_far_under_the_budget(self) -> None:
        client, fake = self._client(_message(_VALID_MARK))
        self._read(client, [_scan_page(400, 600)])
        self.assertEqual(fake.messages.count_calls, [])


class OutputCapTests(_Base):
    def test_cap_follows_max_output_tokens_for(self) -> None:
        client, fake = self._client(_message(_VALID_MARK), _message(_VALID_MARK))
        self._read(client, [_scan_page(400, 600)], tag="binding_second_read")
        self._read(client, [_scan_page(401, 600)], tag="correction")
        self.assertEqual([c["max_tokens"] for c in fake.messages.calls], [16_384, 16_000])
        self.assertEqual(fake.messages.streamed, [])

    def test_a_cap_above_the_nonstreaming_limit_streams(self) -> None:
        client, fake = self._client(_message(_VALID_MARK))
        self._read(client, [_scan_page(400, 600)], tag="extraction")
        self.assertEqual(len(fake.messages.streamed), 1)
        self.assertEqual(fake.messages.streamed[0]["max_tokens"], 32_768)


class CacheKeyTests(_Base):
    def test_claude_key_carries_the_cap_and_the_fit_version(self) -> None:
        client, _fake = self._client()
        second = client._params_fingerprint(_HAIKU, "binding_second_read", AIMarkResponse)
        correction = client._params_fingerprint(_HAIKU, "correction", AIMarkResponse)
        self.assertNotEqual(second, correction)
        with patch("lemely.io.llm.request.IMG_FIT_VERSION", "v2"):
            moved = client._params_fingerprint(_HAIKU, "binding_second_read", AIMarkResponse)
        self.assertNotEqual(second, moved)
```

- [ ] **Step 3: Run them to see them fail.** Run `python -m pytest tests/test_claude_images.py -q --no-cov -o addopts=""`. Expected: failures (pages sent at 2576 RGB, no `claude_over_tier`, `max_tokens` 16000 for every tag, `AttributeError` on `IMG_FIT_VERSION` in `request`).

- [ ] **Step 4: Settings.** In `lemely/runtime/config.py`, in `GeminiSettings` after `correction_prefix_cache`, add:

```python
    # Claude page images (spec 2026-10-19 §2): greyscaled unless two ink colours,
    # stepped down from 2576 px until the request is under this many estimated
    # tokens (95,000 keeps Haiku 5.5 under its 100k price tier), never below the
    # floor (about 135 DPI on A4). Gemini calls do not read either.
    claude_image_token_budget: int = Field(default=95_000, gt=0)
    claude_image_floor_px: int = Field(default=1568, ge=256)
```

In `lemely/runtime/example_toml.py`, after the line that emits `# correction_prefix_cache = ...`, add:

```python
    lines.append("# Claude page images: greyscaled (unless two ink colours) and stepped down")
    lines.append("# from 2576 px until under this many estimated tokens (95,000 keeps Haiku")
    lines.append("# 5.5 under its 100k price tier), never below the floor in pixels.")
    lines.append(f"# claude_image_token_budget = {s.gemini.claude_image_token_budget}")
    lines.append(f"# claude_image_floor_px = {s.gemini.claude_image_floor_px}")
```

Replace the six `second_read_model` comment lines (from `"# The second read's model. Unset: read_model reads twice. A claude- model"` to `"# doctor` checks for it."`) with:

```python
    lines.append("# The second read's model. Unset: read_model reads twice. A claude- model")
    lines.append("# (e.g. claude-haiku-5-5) makes it a cross-model read under the")
    lines.append("# binding_second_read task tag: its thinking level is the Anthropic effort")
    lines.append("# and its max_output_tokens_for cap applies. Claude gets the pages")
    lines.append("# greyscaled and fitted under gemini.claude_image_token_budget, never")
    lines.append("# below gemini.claude_image_floor_px. Needs ANTHROPIC_API_KEY; `lemely")
    lines.append("# doctor` checks for it.")
```

Then run `python -m lemely.runtime.example_toml` from the repo root (it rewrites `lemely.toml.example`).

- [ ] **Step 5: The cache-key version.** In `lemely/io/llm/request.py` add `from lemely.io.llm.image_fit import IMG_FIT_VERSION` and change the Claude return of `provider_fingerprint` to:

```python
    return f"|provider=anthropic|max_tokens={max_output_tokens}|img_fit={IMG_FIT_VERSION}"
```

Update `tests/test_llm_request.py::ProviderFingerprintTests.test_claude_segment_is_todays` to expect `"|provider=anthropic|max_tokens=16000|img_fit=v1"` and rename it `test_claude_segment`. (Claude keys move: every reply cached for a `claude-` model before this task is no longer reused. That is the intent.)

- [ ] **Step 6: The adapter.** In `lemely/io/providers/anthropic_adapter.py`:
  - delete `MAX_LONG_EDGE`, `MANY_IMAGES_THRESHOLD`, `MANY_IMAGES_LONG_EDGE`, `MAX_IMAGES_BASE64_TOTAL`, the function `_fit`, and the `PIL` import; rewrite the module docstring's "Image limits" paragraph to say: "Images arrive already fitted by `lemely.io.llm.image_fit` (greyscale, long edge, token and byte budgets). This module only checks what the API would refuse outright: the media type, more than `MAX_IMAGES_PER_REQUEST` images, or one image over `MAX_IMAGE_BASE64_BYTES` encoded.";
  - add the constant and helpers:

```python
#: The SDK refuses a non-streaming request whose max_tokens implies more than ten
#: minutes (3600 * max_tokens / 128000 > 600); above this the reply is streamed.
NONSTREAMING_MAX_TOKENS = 21_333


def image_blocks(images: Sequence[bytes]) -> list[ImageBlockParam]:
    """Base64 ``image`` blocks for already-fitted ``images``, in order.

    Raises:
        ProviderError: a page is not PNG or JPEG, one is over the per-image size,
            or there are more images than the API takes.
    """
    if len(images) > MAX_IMAGES_PER_REQUEST:
        raise ProviderError(
            f"{len(images)} images in one Claude request; the limit is {MAX_IMAGES_PER_REQUEST}"
        )
    blocks: list[ImageBlockParam] = []
    for page, data in enumerate(images, start=1):
        media_type = _media_type(data, page)
        encoded = base64.standard_b64encode(data).decode("ascii")
        if len(encoded) > MAX_IMAGE_BASE64_BYTES:
            raise ProviderError(
                f"page {page} is {len(encoded)} bytes base64-encoded; Claude takes at most "
                f"{MAX_IMAGE_BASE64_BYTES} per image"
            )
        source: Base64ImageSourceParam = {
            "type": "base64",
            "media_type": media_type,
            "data": encoded,
        }
        blocks.append({"type": "image", "source": source})
    return blocks


def file_image_blocks(file_ids: Sequence[str]) -> list[ImageBlockParam]:
    """``image`` blocks that reference Files API uploads by id, in order."""
    if len(file_ids) > MAX_IMAGES_PER_REQUEST:
        raise ProviderError(
            f"{len(file_ids)} images in one Claude request; the limit is {MAX_IMAGES_PER_REQUEST}"
        )
    return [
        {"type": "image", "source": cast("FileImageSourceParam", {"type": "file", "file_id": fid})}
        for fid in file_ids
    ]
```

  (add `FileImageSourceParam` to the `TYPE_CHECKING` import from `anthropic.types`, and `cast` and `Any` to the `typing` import);
  - replace `AnthropicAdapter.complete` and add `_user_message`, `_send`, `count_tokens`, `raw`:

```python
    @property
    def raw(self) -> anthropic.Anthropic:
        """The SDK client (the Files API uploads use it)."""
        return self._client

    @staticmethod
    def _user_message(
        user_prompt: str,
        *,
        cache_prefix: str | None,
        images: Sequence[bytes],
        image_file_ids: Sequence[str],
    ) -> MessageParam:
        if not (cache_prefix or images or image_file_ids):
            return {"role": "user", "content": user_prompt}
        content: list[ContentBlockParam] = [
            *image_blocks(images),
            *file_image_blocks(image_file_ids),
        ]
        if cache_prefix:
            content.append(
                {"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}}
            )
        content.append({"type": "text", "text": user_prompt})
        return {"role": "user", "content": content}

    def _send(self, **kwargs: Any) -> Message:
        """One request; streamed when ``max_tokens`` is past the SDK's non-streaming limit."""
        try:
            if kwargs["max_tokens"] > NONSTREAMING_MAX_TOKENS:
                with self._client.messages.stream(**kwargs) as stream:
                    return stream.get_final_message()
            return self._client.messages.create(**kwargs)
        except anthropic.APIError as exc:
            if _is_transient(exc):
                raise ProviderTransientError(str(exc)) from exc
            raise ProviderError(str(exc)) from exc

    def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel],
        thinking: str | None,
        cache_prefix: str | None,
        images: Sequence[bytes] = (),
        image_file_ids: Sequence[str] = (),
        max_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> AnthropicReply:
        """Send one request; return the unvalidated reply.

        ``images`` are already fitted (``lemely.io.llm.image_fit``) and go first, as
        base64 blocks; ``image_file_ids`` reference the same kind of pages uploaded
        through the Files API. ``max_tokens`` above :data:`NONSTREAMING_MAX_TOKENS`
        is streamed.

        Raises:
            ProviderTransientError: 429, 529, any 5xx, or a connection failure.
            ProviderError: any other API error, or images the API would refuse.
        """
        output_config: OutputConfigParam = {
            "format": {
                "type": "json_schema",
                "schema": anthropic.transform_schema(response_schema),
            }
        }
        if thinking is not None:
            output_config["effort"] = effort_for(thinking)
        system: list[TextBlockParam] = (
            [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
            if system_prompt
            else []
        )
        message = self._user_message(
            user_prompt, cache_prefix=cache_prefix, images=images, image_file_ids=image_file_ids
        )
        response = self._send(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[message],
            thinking={"type": "adaptive"},
            output_config=output_config,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return AnthropicReply(
            text=text, usage=_usage_of(response), stop_reason=response.stop_reason
        )

    def count_tokens(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        cache_prefix: str | None,
        images: Sequence[bytes] = (),
        image_file_ids: Sequence[str] = (),
    ) -> int:
        """Input tokens the request would bill, from the free count endpoint.

        Raises:
            ProviderError: the endpoint failed (a preflight caller treats it as unknown).
        """
        message = self._user_message(
            user_prompt, cache_prefix=cache_prefix, images=images, image_file_ids=image_file_ids
        )
        system: list[TextBlockParam] = (
            [{"type": "text", "text": system_prompt}] if system_prompt else []
        )
        try:
            counted = self._client.messages.count_tokens(
                model=model, system=system, messages=[message]
            )
        except anthropic.APIError as exc:
            raise ProviderError(str(exc)) from exc
        return int(counted.input_tokens)
```

  `generate` keeps its signature and passes `images=images` through as before.

- [ ] **Step 7: The provider.** Replace `lemely/io/llm/claude_provider.py`'s `ClaudeProvider` class with:

```python
#: Preflight with the count endpoint when the estimate is within 10% of the budget.
PREFLIGHT_SHARE = 0.9


class ClaudeProvider:
    """One attempt on a ``claude-`` model."""

    def __init__(self, adapter: AnthropicAdapter, settings: Settings) -> None:
        self._adapter = adapter
        self._settings = settings

    def _fit(self, req: LLMRequest, *, inline: bool) -> FittedImages:
        g = self._settings.gemini
        return image_fit.fit(
            [image.data for image in req.images],
            byte_limit=image_fit.DEFAULT_BYTE_LIMIT if inline else None,
            token_budget=g.claude_image_token_budget,
            floor_px=g.claude_image_floor_px,
        )

    def _pages(self, req: LLMRequest, log: Any) -> tuple[FittedImages | None, tuple[bytes, ...], tuple[str, ...]]:
        """The fit, and the inline images or Files API ids to send (Task 2c adds ids)."""
        if not req.images:
            return None, (), ()
        fitted = self._fit(req, inline=True)
        if fitted.over_byte_limit:
            raise ProviderError(
                f"{len(req.images)} pages are {fitted.base64_bytes} bytes base64-encoded at "
                f"the {fitted.long_edge} px floor; one Claude request takes at most "
                f"{image_fit.DEFAULT_BYTE_LIMIT} bytes of inline images"
            )
        return fitted, fitted.images, ()

    def count_tokens(self, req: LLMRequest) -> int | None:
        """The count endpoint's figure for ``req`` as it would be sent, or None."""
        images = self._fit(req, inline=True).images if req.images else ()
        try:
            return self._adapter.count_tokens(
                model=req.model,
                system_prompt=req.system,
                user_prompt=req.prompt,
                cache_prefix=req.cache_prefix,
                images=images,
            )
        except ExternalServiceError:
            return None

    def complete(self, req: LLMRequest, *, log: Any) -> ProviderReply:
        """Send ``req``; 429/529/5xx/connection raise ``TransientCallError``."""
        fitted, images, file_ids = self._pages(req, log)
        if fitted is not None:
            if fitted.over_token_budget:
                log.warning(
                    "claude_over_tier",
                    pages=len(req.images),
                    est_tokens=fitted.est_tokens,
                    long_edge=fitted.long_edge,
                    tag=req.task_tag,
                )
            budget = self._settings.gemini.claude_image_token_budget
            if fitted.est_tokens >= PREFLIGHT_SHARE * budget:
                try:
                    counted: int | None = self._adapter.count_tokens(
                        model=req.model,
                        system_prompt=req.system,
                        user_prompt=req.prompt,
                        cache_prefix=req.cache_prefix,
                        images=images,
                        image_file_ids=file_ids,
                    )
                except ExternalServiceError:
                    counted = None
                log.info(
                    "claude_token_preflight",
                    est_tokens=fitted.est_tokens,
                    counted_tokens=counted,
                    tag=req.task_tag,
                )
        t0 = time.monotonic()
        try:
            reply = self._adapter.complete(
                model=req.model,
                system_prompt=req.system,
                user_prompt=req.prompt,
                response_schema=cast("type[BaseModel]", req.response_schema),
                thinking=req.effort,
                cache_prefix=req.cache_prefix,
                images=images,
                image_file_ids=file_ids,
                max_tokens=req.max_output_tokens,
            )
        except ProviderTransientError as exc:
            raise TransientCallError(str(exc)) from exc
        except ExternalServiceError:
            raise
        except (anthropic.AnthropicError, OSError) as exc:
            raise ExternalServiceError(str(exc)) from exc
        latency_ms = int((time.monotonic() - t0) * 1000)
        return ProviderReply(
            text=reply.text,
            usage_response=usage_as_gemini_response(reply.usage),
            stop_reason=reply.stop_reason,
            stop_detail=str(reply.stop_reason),
            latency_ms=latency_ms,
            usage=reply.usage,
        )
```

  with imports `from typing import TYPE_CHECKING, Any, cast`, `from lemely.io.llm import image_fit`, `from lemely.io.providers import ProviderError, ProviderTransientError`, and under `TYPE_CHECKING`: `from pydantic import BaseModel`, `from lemely.io.llm.image_fit import FittedImages`, `from lemely.runtime.config import Settings`. Update `tests/test_llm_providers.py`: `ClaudeProvider(_RaisingAdapter(), client._settings)` and `ClaudeProvider(_Broken(), client._settings)`.

- [ ] **Step 8: The client.** In `lemely/io/gemini.py` add to `GeminiClient`:

```python
    def _claude_output_cap(self, task_tag: str | None) -> int:
        """A claude- call's max_tokens: the tag's max_output_tokens_for, else the adapter's."""
        from lemely.io.providers.anthropic_adapter import MAX_OUTPUT_TOKENS

        return self._settings.gemini.max_output_tokens_for.get(task_tag or "", MAX_OUTPUT_TOKENS)
```

In `_params_fingerprint` replace the Anthropic block with:

```python
        if is_anthropic_model(model):
            raw += provider_fingerprint(model, max_output_tokens=self._claude_output_cap(task_tag))
```

In `_build_request` replace the Claude cap lines with `cap = self._claude_output_cap(task_tag)`. In `_provider_for_model` construct `ClaudeProvider(self._anthropic, self._settings)`.

- [ ] **Step 9: Run the tests.** Run `python -m pytest tests/test_claude_images.py tests/test_image_fit.py tests/test_anthropic_adapter.py tests/test_llm_providers.py tests/test_llm_request.py tests/test_llm_golden.py tests/test_settings_example_drift.py tests/test_cost_ladder_settings.py tests/test_extraction_binding.py -q --no-cov -o addopts=""`. Expected: all pass. In `tests/test_anthropic_adapter.py` some client tests compare sent bytes with the input: those use `_image(...)`, already-greyscale PNGs under the edge, which `image_fit` sends byte for byte, so they pass unchanged. If any other adapter test fails, it is because it asserted the old resizing or the old cap: change its expected value to what `image_fit.fit(<its pages>).images` or `_claude_output_cap(<its tag>)` gives, and name each such test in the commit message.

- [ ] **Step 10: Prove the guards go red.** (a) In `ClaudeProvider._pages` delete the `over_byte_limit` raise; `test_inline_bytes_over_the_limit_at_the_floor_are_refused` must fail. Revert. (b) In `AnthropicAdapter._send` change `>` to `>=` and set `NONSTREAMING_MAX_TOKENS = 40_000`; `test_a_cap_above_the_nonstreaming_limit_streams` must fail. Revert.

- [ ] **Step 11: Commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git add -- tests/test_claude_images.py
git commit -S -m "fix(anthropic): fit page images under Claude's budgets, honour max_output_tokens_for, version the fit in the cache key" -- lemely/io/llm/request.py lemely/io/llm/claude_provider.py lemely/io/providers/anthropic_adapter.py lemely/io/gemini.py lemely/runtime/config.py lemely/runtime/example_toml.py lemely.toml.example tests/test_claude_images.py tests/test_anthropic_adapter.py tests/test_llm_request.py tests/test_llm_providers.py
```

---

### Task 2c: Claude Files API uploads (spec T2, part 3; §2a)

**Files:**
- Create: `lemely/io/llm/claude_uploads.py`
- Modify: `lemely/io/llm/claude_provider.py` (`_pages` uses uploads, falls back inline)
- Modify: `lemely/io/gemini.py` (`ImageUploads.for_claude`, Claude uploads deleted in `ImageUploads.delete`; `generate_structured` passes them; `_build_request` passes `uploads` on Claude too)
- Modify: `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example` (`claude_files_api`)
- Modify: `lemely/app/cli.py` (advisory doctor check `claude_files_workspace`)
- Modify: `docs/deployment.md` (one paragraph on the data exposure)
- Test: `tests/test_claude_uploads.py` (new); `tests/test_anthropic_adapter.py` (`test_files_api_uploads_are_not_used_for_claude` rewritten)

**Interfaces:**
- Consumes: Task 2a `fit`; Task 2b `ClaudeProvider._pages`, `file_image_blocks`, `AnthropicAdapter.raw`.
- Produces:
  - `ClaudeImageUploads(raw_client: Any, images: Sequence[bytes], *, token_budget: int, floor_px: int)`, with `EXPIRES_IN_SECONDS = 3600`, `matches(image_parts) -> bool`, `ensure() -> tuple[FittedImages, tuple[str, ...]]` (fit with no byte limit, upload once, idempotent, thread-safe; a failure is remembered and re-raised as `ExternalServiceError`), `delete() -> None` (best effort; logs `claude_file_delete_failed`), context-manager `__enter__`/`__exit__` (exit deletes).
  - `ImageUploads.for_claude(client: GeminiClient) -> ClaudeImageUploads` (one per `ImageUploads`; deleted by `ImageUploads.delete()`).
  - `GeminiSettings.claude_files_api: bool = True` (spec: on whenever the provider is Claude and the request has images).
  - Log event `claude_files_api_fallback` (`error`, `tag`).

- [ ] **Step 1: Confirm in the docs.** Read https://platform.claude.com/docs/en/build-with-claude/files and https://platform.claude.com/docs/en/build-with-claude/vision. Record in the commit body: (a) the image-count limit when images come by `file_id` (the code keeps `MAX_IMAGES_PER_REQUEST = 100` unless the docs give a lower one; if lower, lower the constant); (b) whether any endpoint a standard API key can call reports the key's workspace (the SDK's `files.upload` takes a `workspace_id`, but that is an input). If one does, note it and leave the doctor check below as the static advisory anyway: no network call is added to `doctor` in this task.

- [ ] **Step 2: Write the failing tests.** Create `tests/test_claude_uploads.py`:

```python
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

    def _client(self, files: _FakeFiles, *outcomes: object, files_api: bool = True) -> tuple[GeminiClient, _FakeAnthropic]:
        settings = _settings(self.tmp)
        settings = settings.model_copy(
            update={"gemini": settings.gemini.model_copy(update={"claude_files_api": files_api})}
        )
        fake = _FakeAnthropic(*outcomes)
        fake.files = files
        return GeminiClient(settings, _genai_client=object(), _anthropic_client=fake, ledger=None), fake

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
        with self.assertRaises(RuntimeError), client.image_uploads(list(_PAGES), concurrency=1) as uploads:
            self._read(client, uploads, "extraction")
            raise RuntimeError("job failed after the read")
        self.assertEqual(files.deleted, ["file_1", "file_2"])

    def test_a_failed_upload_falls_back_inline_and_cleans_up(self) -> None:
        files = _FakeFiles(fail_on=2)
        client, fake = self._client(files, _message(_VALID_MARK))
        with capture_logs() as logs, client.image_uploads(list(_PAGES), concurrency=1) as uploads:
            self._read(client, uploads, "extraction")
        self.assertEqual([s["type"] for s in _sources(fake.messages.calls[0])], ["base64", "base64"])
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
        written = sorted(p.stem for p in (client._settings.paths.cache_dir / "gemini").glob("*.json"))
        self.assertEqual(written, [key])

    def test_files_api_off_sends_the_bytes_inline(self) -> None:
        files = _FakeFiles()
        client, fake = self._client(files, _message(_VALID_MARK), files_api=False)
        with client.image_uploads(list(_PAGES), concurrency=1) as uploads:
            self._read(client, uploads, "extraction")
        self.assertEqual(files.uploads, [])
        self.assertEqual([s["type"] for s in _sources(fake.messages.calls[0])], ["base64", "base64"])


class ClaudeImageUploadsUnitTests(unittest.TestCase):
    def test_ensure_is_idempotent_and_a_failure_is_remembered(self) -> None:
        files = _FakeFiles(fail_on=1)
        uploads = ClaudeImageUploads(SimpleNamespace(files=files), list(_PAGES), token_budget=95_000, floor_px=1568)
        for _ in range(2):
            with self.assertRaisesRegex(Exception, "upload"):
                uploads.ensure()
        self.assertEqual(files.uploads, [])

    def test_matches_only_the_same_pages(self) -> None:
        uploads = ClaudeImageUploads(SimpleNamespace(files=_FakeFiles()), list(_PAGES), token_budget=95_000, floor_px=1568)
        self.assertTrue(uploads.matches(list(_PAGES)))
        self.assertFalse(uploads.matches(list(reversed(_PAGES))))
```

In `tests/test_anthropic_adapter.py` replace `test_files_api_uploads_are_not_used_for_claude` with:

```python
    def test_files_api_off_keeps_gemini_uploads_unused(self) -> None:
        """With claude_files_api off, a claude- call sends the bytes and never ensures uploads."""
        pages = [_image(20, 30)]
        settings = _settings(self.tmp)
        settings = settings.model_copy(
            update={"gemini": settings.gemini.model_copy(update={"claude_files_api": False})}
        )
        client, fake, genai = self._client(_message(_VALID_MARK), settings=settings)
        uploads = MagicMock(spec=ImageUploads)
        uploads.matches.return_value = True
        self._mark(client, image_parts=pages, image_uploads=uploads)
        uploads.ensure.assert_not_called()
        uploads.for_claude.assert_not_called()
        self.assertEqual(_sent_images(fake.messages.calls[0]), [("image/png", pages[0])])
        genai.files.upload.assert_not_called()
```

- [ ] **Step 3: Run them to see them fail.** Run `python -m pytest tests/test_claude_uploads.py -q --no-cov -o addopts=""`. Expected: `ModuleNotFoundError: No module named 'lemely.io.llm.claude_uploads'`.

- [ ] **Step 4: Write `lemely/io/llm/claude_uploads.py`.**

```python
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
from collections.abc import Sequence
from typing import Any

import structlog

from lemely.io.llm.image_fit import FittedImages, fit
from lemely.runtime.errors import ExternalServiceError


class ClaudeImageUploads:
    """Fitted pages uploaded once, reused by every read and retry of the job."""

    EXPIRES_IN_SECONDS = 3600

    def __init__(
        self, raw_client: Any, images: Sequence[bytes], *, token_budget: int, floor_px: int
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
                self._log.warning("claude_file_delete_failed", file_id=file_id, error=str(exc)[:200])
```

- [ ] **Step 5: Wire it.** In `lemely/io/gemini.py`:
  - in `ImageUploads.__init__` add `self._claude: ClaudeImageUploads | None = None` and `self._claude_lock = threading.Lock()` (import `ClaudeImageUploads` under `TYPE_CHECKING`);
  - add to `ImageUploads`:

```python
    def for_claude(self, client: GeminiClient) -> ClaudeImageUploads:
        """The same pages for the Claude Files API; made once, deleted with this object."""
        with self._claude_lock:
            if self._claude is None:
                from lemely.io.llm.claude_uploads import ClaudeImageUploads

                g = client._settings.gemini
                self._claude = ClaudeImageUploads(
                    client._anthropic.raw,
                    self._images,
                    token_budget=g.claude_image_token_budget,
                    floor_px=g.claude_image_floor_px,
                )
            return self._claude
```

  - at the start of `ImageUploads.delete`, before `with self._lock:`, add:

```python
        with self._claude_lock:
            claude, self._claude = self._claude, None
        if claude is not None:
            claude.delete()
```

  - in `generate_structured` replace

```python
        if on_claude:
            # Files API handles are Gemini's: a claude- call sends `image_parts` inline.
            image_uploads = None
```

  with

```python
        claude_uploads: ClaudeImageUploads | None = None
        if on_claude:
            # Spec §2a: the same pages go to Claude's own Files API, once per job.
            if image_uploads is not None and self._settings.gemini.claude_files_api is True:
                claude_uploads = image_uploads.for_claude(self)
            image_uploads = None
```

    and pass `image_uploads=claude_uploads if on_claude else image_uploads` in both `_call_with_retry(...)` calls (the first attempt and the schema-correction retry). Leave the Gemini-only pre-ensure (`if image_uploads is not None: image_uploads.ensure()`) as it is: `image_uploads` is None on Claude at that point;
  - in `_build_request` change `uploads=None if on_claude else image_uploads` to `uploads=image_uploads`, and widen `_call_with_retry`'s and `_call_once`'s `image_uploads` annotation to `ImageUploads | ClaudeImageUploads | None`.

  In `lemely/io/llm/claude_provider.py` replace `_pages` with:

```python
    def _pages(
        self, req: LLMRequest, log: Any
    ) -> tuple[FittedImages | None, tuple[bytes, ...], tuple[str, ...]]:
        """The fit, and the inline images or the Files API ids to send.

        Uploads first (no inline byte limit); an upload failure falls back to inline
        base64, where the byte limit at the floor is the one refusal.
        """
        if not req.images:
            return None, (), ()
        if req.uploads is not None:
            try:
                fitted, file_ids = req.uploads.ensure()
                return fitted, (), file_ids
            except ExternalServiceError as exc:
                log.warning("claude_files_api_fallback", error=str(exc)[:200], tag=req.task_tag)
        fitted = self._fit(req, inline=True)
        if fitted.over_byte_limit:
            raise ProviderError(
                f"{len(req.images)} pages are {fitted.base64_bytes} bytes base64-encoded at "
                f"the {fitted.long_edge} px floor; one Claude request takes at most "
                f"{image_fit.DEFAULT_BYTE_LIMIT} bytes of inline images"
            )
        return fitted, fitted.images, ()
```

- [ ] **Step 6: Settings, doctor, docs.** In `GeminiSettings` after `claude_image_floor_px` add:

```python
    # Spec §2a: page images for a claude- call go through Claude's Files API, uploaded
    # once per job (1 h expiry, deleted at job end) and referenced by id. Files API
    # storage is not ZDR-eligible; the key must belong to a dedicated workspace.
    # Off: the pages are sent inline, under the 30 MB base64 limit.
    claude_files_api: bool = True
```

  In `example_toml.py` after the `claude_image_floor_px` line:

```python
    lines.append("# Page images for claude- calls go through Claude's Files API (1 h expiry,")
    lines.append("# deleted at job end; not ZDR-eligible: use a dedicated workspace key).")
    lines.append(f"# claude_files_api = {_toml_bool(s.gemini.claude_files_api)}")
```

  Run `python -m lemely.runtime.example_toml`. In `lemely/app/cli.py` `doctor_cmd`, directly after the `anthropic_api_key` record, add:

```python
    if claude_tags_any := [t for t, m in configured_models.items() if m.startswith("claude-")]:
        record(
            "claude_files_workspace",
            True,
            detail=(
                "claude_files_api is on: page images for "
                + ", ".join(claude_tags_any)
                + " are uploaded (1 h expiry, deleted at job end; not ZDR-eligible). "
                "A standard key cannot report its workspace: confirm ANTHROPIC_API_KEY "
                "belongs to the dedicated Lemely workspace."
                if settings.gemini.claude_files_api
                else "claude_files_api is off: page images are sent inline"
            ),
        )
```

  and add `"claude_files_workspace"` to `advisory_checks`. In `docs/deployment.md`, in the Anthropic section added by the cost ladder (search for `ANTHROPIC_API_KEY`), append:

```markdown
**Claude Files API (page images).** With `gemini.claude_files_api` on (the default), page images for `claude-` calls are uploaded to Anthropic's Files API once per job, with a one-hour expiry, and deleted when the job ends. Files API storage is not covered by zero data retention, and any API key of the workspace can read an uploaded file, so the Anthropic key must belong to a dedicated Lemely workspace. Turn the flag off to send pages inline instead (limited to 30 MB of base64 per request).
```

- [ ] **Step 7: Run the tests.** Run `python -m pytest tests/test_claude_uploads.py tests/test_claude_images.py tests/test_anthropic_adapter.py tests/test_llm_providers.py tests/test_llm_golden.py tests/test_gemini_client.py tests/test_settings_example_drift.py tests/test_cli_doctor.py tests/test_extraction_binding.py -q --no-cov -o addopts=""`. Expected: all pass.

- [ ] **Step 8: Prove the guards go red.** (a) In `ImageUploads.delete` remove the Claude block; `test_pages_upload_once_and_both_reads_reference_them` and `test_files_are_deleted_when_the_job_fails` must fail. Revert. (b) In `ClaudeImageUploads.ensure` remove the `if self._fitted is not None` early return; `test_pages_upload_once...` must fail with 4 uploads. Revert.

- [ ] **Step 9: Commit.** The commit body records, from step 1, the file-id image-count limit and the workspace finding, and states the data exposure in one sentence.

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git add -- lemely/io/llm/claude_uploads.py tests/test_claude_uploads.py
git commit -S -m "feat(anthropic): upload page images once per job to the Claude Files API" -- lemely/io/llm/claude_uploads.py lemely/io/llm/claude_provider.py lemely/io/gemini.py lemely/runtime/config.py lemely/runtime/example_toml.py lemely.toml.example lemely/app/cli.py docs/deployment.md tests/test_claude_uploads.py tests/test_anthropic_adapter.py
```

---
### Task 3a: Tiered Claude prices, cache writes, container time (spec T3, part 1)

**Files:**
- Create: `lemely/io/llm/pricing.py`
- Modify: `lemely/io/llm/provider.py` (`Usage` fields and docstring)
- Modify: `lemely/io/llm/claude_provider.py` (`usage_as_gemini_response` carries the new fields)
- Modify: `lemely/io/providers/anthropic_adapter.py` (`_usage_of`; drop the 1.25 weighting)
- Modify: `lemely/io/gemini.py` (`PriceRow` from `pricing`; Claude rows out of the Gemini tables; `price_row`, `price_call`, `_row_cost`; `CallRecord` fields; `_record_spend`; `_require_price`; `fallback_pricing_status`)
- Test: `tests/test_llm_pricing.py` (new); `tests/test_anthropic_adapter.py` only if a token assertion moved (see step 6)

**Interfaces:**
- Consumes: Task 1a `Usage`; Task 1b `usage_as_gemini_response`.
- Produces:
  - `lemely.io.llm.pricing.PriceRow(NamedTuple)`: `input: float, cached_input: float, output: float, cache_write_5m: float | None = None, cache_write_1h: float | None = None, tier_threshold_tokens: int | None = None, tier2: PriceRow | None = None` (USD per 1k). `lemely.io.gemini.PriceRow` is this class.
  - `CLAUDE_PRICING: dict[str, PriceRow]`, `CLAUDE_PRICE_SOURCES: dict[str, tuple[str, date]]` (URL and read date per row), `PRICING_URL`, `CODE_EXECUTION_USD_PER_CONTAINER_HOUR = 0.05`, `CODE_EXECUTION_MIN_BILLED_SECONDS = 300`.
  - `claude_row(model: str) -> PriceRow | None` (longest key contained in `model`).
  - `row_cost(row: PriceRow, *, input_tokens: int, cached_tokens: int, output_tokens: int, cache_write_5m_tokens: int = 0, cache_write_1h_tokens: int = 0, container_seconds: float = 0.0) -> float`; the tier is chosen on total input (`input_tokens`, which includes reads and writes). For a row with no tier and no writes it is bit-for-bit today's `_row_cost`.
  - `Usage` gains `cache_write_5m_tokens: int = 0`, `cache_write_1h_tokens: int = 0`, `container_seconds: float = 0.0`; `Usage.input_tokens` is now the plain total (uncached + reads + writes), no longer weighted.
  - `price_call(..., cache_write_5m_tokens: int = 0, cache_write_1h_tokens: int = 0, container_seconds: float = 0.0)`.
  - `CallRecord` gains, at the end: `cache_write_5m_tokens: int = 0`, `cache_write_1h_tokens: int = 0`, `container_seconds: float = 0.0`.
  - `GeminiClient._require_price(model: str) -> None`: raises `UnpricedModelError` for a `claude-` model with no row, before any paid call.
  - The `gemini_call` log line carries `cache_write_5m_tokens`, `cache_write_1h_tokens`, `container_seconds` only when non-zero (so a Gemini line is unchanged).

- [ ] **Step 1: Re-read every rate.** Open https://platform.claude.com/docs/en/about-claude/pricing and https://platform.claude.com/docs/en/about-claude/models/overview. For Haiku 5.5, Sonnet 5.5, Opus 5.5 and Fable 5.1 confirm: the API model id (expected `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-fable-5-1`), base input, 5-minute write, 1-hour write, cache hit and output per MTok, any long-context tier (Haiku's above 100k; check whether the others have one), and that `inference_geo` "us" costs 1.1x. Where a figure differs from "Facts this plan relies on", use the page's figure in the code and the tests below and list every difference in the commit message. Record the date read.

- [ ] **Step 2: Write the failing tests.** Create `tests/test_llm_pricing.py`:

```python
"""Spec 2026-10-19 §3: tiered Claude prices, cache writes, container time, fail-closed."""

from __future__ import annotations

import random
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from structlog.testing import capture_logs

from lemely.core.schemas import AIMarkResponse
from lemely.io.gemini import (
    GeminiClient,
    UnpricedModelError,
    _reset_process_counters,
    price_row,
    process_call_records,
    record_calls,
)
from lemely.io.llm.pricing import (
    CLAUDE_PRICE_SOURCES,
    CLAUDE_PRICING,
    PriceRow,
    claude_row,
    row_cost,
)
from tests.gemini_fakes import make_settings, mock_response
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _settings

_TODAY = date(2026, 10, 19)


def _old_row_cost(row: PriceRow, *, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    """Today's gemini._row_cost, copied verbatim, as the oracle for Gemini rows."""
    cached = min(max(cached_tokens, 0), max(input_tokens, 0))
    uncached = max(input_tokens, 0) - cached
    return (
        uncached / 1000 * row.input
        + cached / 1000 * row.cached_input
        + output_tokens / 1000 * row.output
    )


class RowTests(unittest.TestCase):
    def test_rows_per_mtok(self) -> None:
        expected = {
            "claude-haiku-5-5": (0.10, 0.01, 0.50, 0.125, 0.20),
            "claude-sonnet-5-5": (2.0, 0.10, 10.0, 2.50, 4.0),
            "claude-opus-5-5": (4.0, 0.20, 20.0, 5.0, 8.0),
            "claude-fable-5-1": (10.0, 0.25, 50.0, 12.50, 20.0),
        }
        for model, per_mtok in expected.items():
            row = CLAUDE_PRICING[model]
            got = (row.input, row.cached_input, row.output, row.cache_write_5m, row.cache_write_1h)
            for g, e in zip(got, per_mtok, strict=True):
                with self.subTest(model=model):
                    self.assertAlmostEqual(g * 1000, e, places=9)

    def test_haiku_tier_two(self) -> None:
        row = CLAUDE_PRICING["claude-haiku-5-5"]
        self.assertEqual(row.tier_threshold_tokens, 100_000)
        assert row.tier2 is not None
        self.assertAlmostEqual(row.tier2.input * 1000, 0.50, places=9)
        self.assertAlmostEqual(row.tier2.output * 1000, 2.50, places=9)
        self.assertAlmostEqual(row.tier2.cache_write_5m * 1000, 0.625, places=9)  # type: ignore[operator]
        self.assertAlmostEqual(row.tier2.cached_input * 1000, 0.05, places=9)

    def test_every_row_records_its_source(self) -> None:
        for model in CLAUDE_PRICING:
            url, read_on = CLAUDE_PRICE_SOURCES[model]
            self.assertTrue(url.startswith("https://platform.claude.com/"))
            self.assertIsInstance(read_on, date)

    def test_longest_key_wins(self) -> None:
        self.assertIs(claude_row("claude-haiku-5-5"), CLAUDE_PRICING["claude-haiku-5-5"])
        self.assertIsNone(claude_row("claude-nonexistent-9"))


class CostTests(unittest.TestCase):
    def test_tier_switches_above_100k_total_input(self) -> None:
        row = CLAUDE_PRICING["claude-haiku-5-5"]
        at = row_cost(row, input_tokens=100_000, cached_tokens=0, output_tokens=0)
        over = row_cost(row, input_tokens=100_001, cached_tokens=0, output_tokens=0)
        self.assertAlmostEqual(at, 100_000 * 0.10 / 1e6, places=12)
        self.assertAlmostEqual(over, 100_001 * 0.50 / 1e6, places=12)

    def test_reads_and_writes_count_toward_the_tier(self) -> None:
        row = CLAUDE_PRICING["claude-haiku-5-5"]
        usd = row_cost(row, input_tokens=120_000, cached_tokens=60_000, output_tokens=0, cache_write_5m_tokens=50_000)
        self.assertAlmostEqual(usd, (10_000 * 0.50 + 60_000 * 0.05 + 50_000 * 0.625) / 1e6, places=12)

    def test_cache_writes_at_their_rates(self) -> None:
        row = CLAUDE_PRICING["claude-haiku-5-5"]
        usd = row_cost(
            row,
            input_tokens=10_000,
            cached_tokens=3_000,
            output_tokens=1_000,
            cache_write_5m_tokens=2_000,
            cache_write_1h_tokens=1_000,
        )
        expected = (4_000 * 0.10 + 3_000 * 0.01 + 2_000 * 0.125 + 1_000 * 0.20 + 1_000 * 0.50) / 1e6
        self.assertAlmostEqual(usd, expected, places=12)

    def test_container_seconds_at_five_cents_an_hour(self) -> None:
        row = CLAUDE_PRICING["claude-haiku-5-5"]
        usd = row_cost(row, input_tokens=0, cached_tokens=0, output_tokens=0, container_seconds=300)
        self.assertAlmostEqual(usd, 300 / 3600 * 0.05, places=12)

    def test_gemini_rows_cost_exactly_what_they_did(self) -> None:
        rng = random.Random(7)
        row = PriceRow(0.000750, 0.000075, 0.003750)
        for _ in range(500):
            i, c, o = rng.randint(0, 200_000), rng.randint(0, 200_000), rng.randint(0, 40_000)
            self.assertEqual(
                row_cost(row, input_tokens=i, cached_tokens=c, output_tokens=o),
                _old_row_cost(row, input_tokens=i, cached_tokens=c, output_tokens=o),
            )


class ClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: _TODAY)
        today.start()
        self.addCleanup(today.stop)

    def _mark(self, client: GeminiClient, model: str = "claude-haiku-5-5") -> None:
        client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=AIMarkResponse,
            prompt_version="v1",
            model=model,
            task_tag="correction",
        )

    def test_unpriced_claude_model_fails_before_any_request(self) -> None:
        fake = _FakeAnthropic(_message(_VALID_MARK))
        client = GeminiClient(_settings(self.tmp), _genai_client=object(), _anthropic_client=fake, ledger=None)
        with self.assertRaises(UnpricedModelError):
            self._mark(client, model="claude-nonexistent-9")
        self.assertEqual(fake.messages.calls, [])
        with self.assertRaises(UnpricedModelError):
            price_row("claude-nonexistent-9", make_settings(self.tmp), on=_TODAY)

    def test_record_carries_cache_writes(self) -> None:
        fake = _FakeAnthropic(_message(_VALID_MARK, input_tokens=1_000, cache_write=2_000, cache_read=500))
        client = GeminiClient(_settings(self.tmp), _genai_client=object(), _anthropic_client=fake, ledger=None)
        self._mark(client)
        (rec,) = process_call_records()
        self.assertEqual((rec.input_tokens, rec.cached_tokens, rec.cache_write_5m_tokens), (3_500, 500, 2_000))
        expected = (1_000 * 0.10 + 500 * 0.01 + 2_000 * 0.125 + 200 * 0.50) / 1e6
        self.assertAlmostEqual(rec.usd_now, expected, places=12)

    def test_inference_geo_is_never_sent(self) -> None:
        fake = _FakeAnthropic(_message(_VALID_MARK))
        client = GeminiClient(_settings(self.tmp), _genai_client=object(), _anthropic_client=fake, ledger=None)
        self._mark(client)
        self.assertNotIn("inference_geo", fake.messages.calls[0])

    def test_gemini_record_and_log_line_unchanged(self) -> None:
        from tests.gemini_fakes import fake_genai_client

        genai = fake_genai_client()
        genai.models.generate_content.return_value = mock_response(
            '{"awarded_marks": 1, "confidence": 0.9, "feedback": "f", "addresses_question": "yes"}'
        )
        client = GeminiClient(make_settings(self.tmp), _genai_client=genai, ledger=None)
        with capture_logs() as logs:
            self._mark(client, model="gemini-3.8-flash")
        (rec,) = process_call_records()
        self.assertEqual((rec.cache_write_5m_tokens, rec.cache_write_1h_tokens, rec.container_seconds), (0, 0, 0.0))
        (line,) = [e for e in logs if e["event"] == "gemini_call"]
        self.assertFalse({"cache_write_5m_tokens", "cache_write_1h_tokens", "container_seconds"} & set(line))
```

- [ ] **Step 3: Run them to see them fail.** Run `python -m pytest tests/test_llm_pricing.py -q --no-cov -o addopts=""`. Expected: `ModuleNotFoundError: No module named 'lemely.io.llm.pricing'`.

- [ ] **Step 4: Write `lemely/io/llm/pricing.py`.**

```python
"""Price rows with tiers and cache writes; Claude's rows (spec 2026-10-19 §3).

USD per 1k tokens, the convention ``lemely.io.gemini``'s tables use. Every Claude
rate was read from ``PRICING_URL`` on the date in ``CLAUDE_PRICE_SOURCES``; the
research numbers from brainstorming are not trusted on their own. ``inference_geo``
is never sent, so the 1.1x US-only multiplier never applies.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
#: Code execution: per container-hour, at least 5 minutes per execution. The
#: monthly free hours are ignored, so the ledger reads high, never low.
CODE_EXECUTION_USD_PER_CONTAINER_HOUR = 0.05
CODE_EXECUTION_MIN_BILLED_SECONDS = 300


class PriceRow(NamedTuple):
    """USD per 1k tokens. ``tier2`` applies above ``tier_threshold_tokens`` of total input.

    A row with no write rates bills cache writes at its input rate.
    """

    input: float
    cached_input: float
    output: float
    cache_write_5m: float | None = None
    cache_write_1h: float | None = None
    tier_threshold_tokens: int | None = None
    tier2: PriceRow | None = None


CLAUDE_PRICING: dict[str, PriceRow] = {
    "claude-haiku-5-5": PriceRow(
        0.000100,
        0.000010,
        0.000500,
        0.000125,
        0.000200,
        100_000,
        PriceRow(0.000500, 0.000050, 0.002500, 0.000625, 0.001000),
    ),
    "claude-sonnet-5-5": PriceRow(0.002000, 0.000100, 0.010000, 0.002500, 0.004000),
    "claude-opus-5-5": PriceRow(0.004000, 0.000200, 0.020000, 0.005000, 0.008000),
    "claude-fable-5-1": PriceRow(0.010000, 0.000250, 0.050000, 0.012500, 0.020000),
}
#: model -> (where the rates were read, the day they were read).
CLAUDE_PRICE_SOURCES: dict[str, tuple[str, date]] = {
    model: (PRICING_URL, date(2026, 10, 19)) for model in CLAUDE_PRICING
}


def claude_row(model: str) -> PriceRow | None:
    """The row whose key is the longest one contained in ``model``, or None."""
    for key in sorted(CLAUDE_PRICING, key=len, reverse=True):
        if key in model:
            return CLAUDE_PRICING[key]
    return None


def row_cost(
    row: PriceRow,
    *,
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
    container_seconds: float = 0.0,
) -> float:
    """USD for one call. ``input_tokens`` is the total: uncached + reads + writes.

    The tier is chosen on that total. With no writes, no container time and no tier,
    the sum is formed in the same order as before, so Gemini costs are bit-identical.
    """
    total = max(input_tokens, 0)
    if row.tier2 is not None and row.tier_threshold_tokens is not None and total > row.tier_threshold_tokens:
        row = row.tier2
    cached = min(max(cached_tokens, 0), total)
    write_5m = max(cache_write_5m_tokens, 0)
    write_1h = max(cache_write_1h_tokens, 0)
    uncached = max(total - cached - write_5m - write_1h, 0)
    write_5m_rate = row.cache_write_5m if row.cache_write_5m is not None else row.input
    write_1h_rate = row.cache_write_1h if row.cache_write_1h is not None else row.input
    return (
        uncached / 1000 * row.input
        + cached / 1000 * row.cached_input
        + write_5m / 1000 * write_5m_rate
        + write_1h / 1000 * write_1h_rate
        + output_tokens / 1000 * row.output
        + container_seconds / 3600 * CODE_EXECUTION_USD_PER_CONTAINER_HOUR
    )
```

(`test_gemini_rows_cost_exactly_what_they_did` is the proof that the added zero terms do not move a Gemini cost: `x + 0.0` is `x` exactly. The golden test proves it end to end.)

- [ ] **Step 5: Usage, adapter, provider.** In `lemely/io/llm/provider.py` replace `Usage` with:

```python
@dataclass(frozen=True)
class Usage:
    """Token counts for one Claude call, in the units ``CallRecord`` uses.

    ``input_tokens`` is the total input: uncached tokens, cache reads and cache
    writes. ``cached_tokens`` is the reads; the two write counts are the 5-minute
    and 1-hour writes (``usage.cache_creation``). ``output_tokens`` includes
    ``thinking_tokens``. ``container_seconds`` is billed code-execution time.
    """

    input_tokens: int
    cached_tokens: int
    output_tokens: int
    thinking_tokens: int
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    container_seconds: float = 0.0
```

In `anthropic_adapter.py` delete `_CACHE_WRITE_PREMIUM_NUM, _CACHE_WRITE_PREMIUM_DEN` and replace `_usage_of` with:

```python
def _usage_of(message: Message) -> Usage:
    u = message.usage
    cache_read = int(u.cache_read_input_tokens or 0)
    creation = getattr(u, "cache_creation", None)
    if creation is not None:
        write_5m = int(creation.ephemeral_5m_input_tokens or 0)
        write_1h = int(creation.ephemeral_1h_input_tokens or 0)
    else:
        write_5m, write_1h = int(u.cache_creation_input_tokens or 0), 0
    details = u.output_tokens_details
    return Usage(
        input_tokens=int(u.input_tokens) + cache_read + write_5m + write_1h,
        cached_tokens=cache_read,
        output_tokens=int(u.output_tokens),
        thinking_tokens=int(details.thinking_tokens) if details is not None else 0,
        cache_write_5m_tokens=write_5m,
        cache_write_1h_tokens=write_1h,
    )
```

In `claude_provider.usage_as_gemini_response` add to the inner namespace:

```python
            cache_write_5m_tokens=usage.cache_write_5m_tokens,
            cache_write_1h_tokens=usage.cache_write_1h_tokens,
            container_seconds=usage.container_seconds,
```

- [ ] **Step 6: The client.** In `lemely/io/gemini.py`:
  - delete the local `class PriceRow(NamedTuple)` and import `from lemely.io.llm.pricing import PriceRow, claude_row, row_cost`;
  - delete the `"claude-haiku-5-5"` entries (and their comment) from `_DEFAULT_PRICING` and `_CACHED_INPUT_PRICING`;
  - in `price_row`, after the user-override branch, insert:

```python
    if is_anthropic_model(model):
        row = claude_row(model)
        if row is None:
            raise UnpricedModelError(model)
        return row
```

  - replace the body of `_row_cost` with `return row_cost(row, input_tokens=input_tokens, cached_tokens=cached_tokens, output_tokens=output_tokens)`;
  - give `price_call` three keyword parameters `cache_write_5m_tokens: int = 0, cache_write_1h_tokens: int = 0, container_seconds: float = 0.0` and return `row_cost(price_row(model, settings, on=on), input_tokens=..., cached_tokens=..., output_tokens=..., cache_write_5m_tokens=..., cache_write_1h_tokens=..., container_seconds=...)`;
  - add to `CallRecord`, after `parse_ok`:

```python
    #: Claude prompt-cache writes (5-minute and 1-hour), part of ``input_tokens``.
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    #: Billed code-execution container time.
    container_seconds: float = 0.0
```

  - add a module helper and use it in `_record_spend`:

```python
def _usage_number(meta: Any, name: str) -> float:
    """A usage field as a number; a missing field or a mock attribute reads as 0."""
    raw = getattr(meta, name, 0)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return 0
    return max(raw, 0)
```

    In `_record_spend`, after `cached_tok` is computed:

```python
        write_5m = int(_usage_number(response.usage_metadata, "cache_write_5m_tokens"))
        write_1h = int(_usage_number(response.usage_metadata, "cache_write_1h_tokens"))
        container_s = float(_usage_number(response.usage_metadata, "container_seconds"))
        extra_usage = {
            k: v
            for k, v in (
                ("cache_write_5m_tokens", write_5m),
                ("cache_write_1h_tokens", write_1h),
                ("container_seconds", container_s),
            )
            if v
        }
```

    pass `cache_write_5m_tokens=write_5m, cache_write_1h_tokens=write_1h, container_seconds=container_s` to both `price_call` calls; pass the same three to the `CallRecord(...)`; and in the `log.info("gemini_call", ...)` call add `**extra_usage,` before `**(extra_log_fields or {})`;
  - add to `GeminiClient`:

```python
    def _require_price(self, model: str) -> None:
        """Fail closed: a claude- model with no price row is never called (spec §6)."""
        if is_anthropic_model(model):
            price_row(model, self._settings, on=_today())
```

    and call `self._require_price(active_model)` immediately before `self._check_cost_ceiling()` in both `generate_structured` and `generate_with_code_execution`;
  - in `fallback_pricing_status`, change the hit condition to `model not in user_pricing and not any(key in model for key in pricing_table) and claude_row(model) is None`.

  Run `python -m pytest tests/test_anthropic_adapter.py -q --no-cov -o addopts=""`. `test_cache_write_premium_priced` keeps its dollar assertion (a 5-minute write at $0.125/MTok is the old 1.25x of $0.10). Any test that asserted the old weighted `input_tokens` (uncached + reads + 1.25 x writes) now sees the plain total: change only that expected token count, and name the test in the commit message.

- [ ] **Step 7: Run the tests.** Run `python -m pytest tests/test_llm_pricing.py tests/test_anthropic_adapter.py tests/test_llm_golden.py tests/test_gemini_cost_record.py tests/test_gemini_client.py tests/test_cost_ledger.py tests/test_cost_ladder_runner.py tests/test_cli_doctor.py tests/test_llm_providers.py -q --no-cov -o addopts=""`. Expected: all pass, golden unchanged.

- [ ] **Step 8: Prove the guards go red.** (a) In `row_cost` change `>` to `>=` in the tier test; `test_tier_switches_above_100k_total_input` must fail. Revert. (b) Remove the `self._require_price(active_model)` line from `generate_structured`; `test_unpriced_claude_model_fails_before_any_request` must fail (a request is made). Revert.

- [ ] **Step 9: Commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git add -- lemely/io/llm/pricing.py tests/test_llm_pricing.py
git commit -S -m "feat(pricing): tiered Claude rows with cache writes and container time; unpriced Claude fails closed" -- lemely/io/llm/pricing.py lemely/io/llm/provider.py lemely/io/llm/claude_provider.py lemely/io/providers/anthropic_adapter.py lemely/io/gemini.py tests/test_llm_pricing.py tests/test_anthropic_adapter.py
```

---

### Task 3b: Doctor price table per task tag (spec T3, part 2)

**Files:**
- Modify: `lemely/io/model_table.py` (`ModelRow`, `model_rows`)
- Modify: `lemely/app/cli.py` (`doctor_cmd`: two checks; `advisory_checks`)
- Test: `tests/test_model_table.py`, `tests/test_cli_doctor.py`

**Interfaces:**
- Consumes: Task 3a `price_row`, `UnpricedModelError`, `PriceRow`; `GeminiClient.resolved_thinking`.
- Produces:
  - `ModelRow(tag: str, model: str, provider: Literal["gemini", "anthropic"], effort: str, price: str | None)` (frozen dataclass); `price` is `"<in>/<hit>/<out> $/MTok"` plus `", >N tokens <in>/<hit>/<out>"` for a tiered row, or None when the model has no row.
  - `model_rows(settings: Settings, *, on: date) -> list[ModelRow]`, one per entry of `configured_models(settings)`, same order.
  - Doctor checks: `llm_price_table` (advisory; ok when every tag has a row; detail lists every row) and `claude_price_rows` (fatal; ok unless a `claude-` tag has no row).

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_model_table.py`:

```python
class ModelRowsTests(unittest.TestCase):
    def _settings(self, **gemini: object) -> Settings:
        s = Settings()
        return s.model_copy(update={"gemini": s.gemini.model_copy(update=gemini)})

    def test_one_row_per_configured_tag_with_provider_effort_and_price(self) -> None:
        from datetime import date

        from lemely.io.model_table import configured_models, model_rows

        s = self._settings(correction_model="claude-haiku-5-5")
        rows = model_rows(s, on=date(2026, 10, 19))
        self.assertEqual([r.tag for r in rows], list(configured_models(s)))
        correction = next(r for r in rows if r.tag == "correction")
        self.assertEqual((correction.provider, correction.effort), ("anthropic", "low"))
        self.assertEqual(correction.price, "0.1/0.01/0.5 $/MTok, >100000 tokens 0.5/0.05/2.5")
        extraction = next(r for r in rows if r.tag == "extraction")
        self.assertEqual(extraction.provider, "gemini")
        self.assertIsNotNone(extraction.price)

    def test_unpriced_model_has_no_price(self) -> None:
        from datetime import date

        from lemely.io.model_table import model_rows

        rows = model_rows(self._settings(correction_model="claude-nonexistent-9"), on=date(2026, 10, 19))
        self.assertIsNone(next(r for r in rows if r.tag == "correction").price)
```

(add `from lemely.runtime.config import Settings` to the file's imports if it is not there). Append to `tests/test_cli_doctor.py`'s `DoctorTests`:

```python
    def test_doctor_lists_the_price_table_and_fails_an_unpriced_claude_tag(self) -> None:
        with TemporaryDirectory() as tmp:
            env = self._doctor_env(
                tmp,
                LEMELY_GEMINI__CORRECTION_MODEL="claude-nonexistent-9",
                ANTHROPIC_API_KEY="test-key",
            )
            result = self.runner.invoke(cli, ["--json", "doctor", "--no-network"], env=env)
        payload = json.loads(result.output)
        checks = {c["name"]: c for c in payload["checks"]}
        self.assertIn("correction=anthropic:claude-nonexistent-9", checks["llm_price_table"]["detail"])
        self.assertFalse(checks["claude_price_rows"]["ok"])
        self.assertFalse(payload["all_passed"])

    def test_doctor_price_rows_pass_on_defaults(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self.runner.invoke(
                cli, ["--json", "doctor", "--no-network"], env=self._doctor_env(tmp)
            )
        checks = {c["name"]: c for c in json.loads(result.output)["checks"]}
        self.assertTrue(checks["claude_price_rows"]["ok"])
        self.assertTrue(checks["llm_price_table"]["ok"])
```

- [ ] **Step 2: Run them to see them fail.** Run `python -m pytest tests/test_model_table.py tests/test_cli_doctor.py -q --no-cov -o addopts=""`. Expected: `ImportError: cannot import name 'model_rows'` and `KeyError: 'llm_price_table'`.

- [ ] **Step 3: Implement.** Append to `lemely/io/model_table.py`:

```python
@dataclass(frozen=True)
class ModelRow:
    """One task tag as ``lemely doctor`` lists it."""

    tag: str
    model: str
    provider: Literal["gemini", "anthropic"]
    effort: str
    price: str | None


def _per_mtok(row: PriceRow) -> str:
    return f"{row.input * 1000:g}/{row.cached_input * 1000:g}/{row.output * 1000:g}"


def model_rows(settings: Settings, *, on: date) -> list[ModelRow]:
    """Every configured tag with its provider, effort (thinking level) and price row."""
    from lemely.io.gemini import GeminiClient, UnpricedModelError, price_row
    from lemely.io.providers import is_anthropic_model

    client = GeminiClient(settings, _genai_client=object(), ledger=None)
    rows: list[ModelRow] = []
    for tag, model in configured_models(settings).items():
        try:
            row = price_row(model, settings, on=on)
        except UnpricedModelError:
            price: str | None = None
        else:
            price = f"{_per_mtok(row)} $/MTok"
            if row.tier2 is not None and row.tier_threshold_tokens is not None:
                price += f", >{row.tier_threshold_tokens} tokens {_per_mtok(row.tier2)}"
        rows.append(
            ModelRow(
                tag=tag,
                model=model,
                provider="anthropic" if is_anthropic_model(model) else "gemini",
                effort=str(client.resolved_thinking(tag, model)),
                price=price,
            )
        )
    return rows
```

with imports `from dataclasses import dataclass`, `from datetime import date`, `from typing import TYPE_CHECKING, Literal`, and `from lemely.io.llm.pricing import PriceRow` under `TYPE_CHECKING`. In `doctor_cmd`, after the `gemini_fallback_pricing` record, add:

```python
    # Spec 2026-10-19 §3: every tag's provider, model, effort and price row. A claude-
    # tag with no row is fatal (its calls fail closed); a Gemini tag with no row only
    # warns (it is priced through the fallback, as gemini_fallback_pricing says).
    from lemely.io.gemini import _today
    from lemely.io.model_table import model_rows

    rows = model_rows(settings, on=_today())
    record(
        "llm_price_table",
        all(r.price is not None for r in rows),
        detail="; ".join(
            f"{r.tag}={r.provider}:{r.model} effort={r.effort} price={r.price or 'NO ROW'}"
            for r in rows
        ),
    )
    unpriced_claude = [r.tag for r in rows if r.provider == "anthropic" and r.price is None]
    record(
        "claude_price_rows",
        not unpriced_claude,
        detail=""
        if not unpriced_claude
        else "no price row for the claude- model of: "
        + ", ".join(unpriced_claude)
        + "; every call to it fails closed",
    )
```

and add `"llm_price_table"` to `advisory_checks`.

- [ ] **Step 4: Run the tests.** Run `python -m pytest tests/test_model_table.py tests/test_cli_doctor.py tests/test_llm_golden.py -q --no-cov -o addopts=""`. Expected: all pass.

- [ ] **Step 5: Prove the guard goes red.** Add `"claude_price_rows"` to `advisory_checks`; `test_doctor_lists_the_price_table_and_fails_an_unpriced_claude_tag` must fail on `all_passed`. Revert.

- [ ] **Step 6: Commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git commit -S -m "feat(doctor): list provider, model, effort and price row per task tag" -- lemely/io/model_table.py lemely/app/cli.py tests/test_model_table.py tests/test_cli_doctor.py
```

---

### Task 3c: Per-script cost guard (spec §2 "Cost guard")

**Files:**
- Modify: `lemely/io/gemini.py` (`script_cost_scope`; one accumulation in `_record_spend`)
- Modify: `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example` (`paper_cost_target_usd`)
- Modify: `lemely/web/routers/student.py` (the `extracted = extract_answers(...)` to `report = grade_paper(...)` span), `lemely/web/routers/teacher.py` (the `repo.set_stage(paper_id, "extract")` to `report = grade_paper(...)` span)
- Test: `tests/test_script_cost_scope.py` (new)

**Interfaces:**
- Consumes: `_record_spend`'s `usd` and `task_tag`.
- Produces:
  - `GeminiSettings.paper_cost_target_usd: float = 0.10` (`gt=0`).
  - `script_cost_scope(settings: Settings, *, script_key: str) -> contextlib.AbstractContextManager[dict[str, float]]` in `lemely.io.gemini`: while open, every paid call made in this context (and in threads started with `contextvars.copy_context().run`, which the binder and the uploads use) adds its `usd` to the yielded dict under its task tag (`"untagged"` for none). On exit, a total above the target logs `script_over_cost_target` (`script_key`, `total_usd`, `target_usd`, `by_tag`) at warning. It never raises and never blocks marking.

Note for the reviewer: the shipped Gemini configuration costs about $0.158 a script (`01f371c3` run), so on the default path this logs one warning per marked script. That is the guard doing its job; it is a log line in the web routes, outside `GeminiClient`, so the golden is not affected.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_script_cost_scope.py`:

```python
"""Spec 2026-10-19 §2: each script's cost is compared with paper_cost_target_usd."""

from __future__ import annotations

import contextvars
import inspect
import tempfile
import threading
import unittest
from datetime import date
from unittest.mock import patch

from pydantic import BaseModel
from structlog.testing import capture_logs

from lemely.io.gemini import GeminiClient, _reset_process_counters, script_cost_scope
from lemely.web.routers import student, teacher
from tests.gemini_fakes import fake_genai_client, make_settings, mock_response


class _Reply(BaseModel):
    value: str


class ScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)
        settings = make_settings(tempfile.mkdtemp())
        self.settings = settings.model_copy(
            update={"gemini": settings.gemini.model_copy(update={"paper_cost_target_usd": 0.001})}
        )
        genai = fake_genai_client()
        genai.models.generate_content.side_effect = [
            mock_response('{"value": "a"}', prompt=10_000, candidates=1_000),
            mock_response('{"value": "b"}', prompt=10_000, candidates=1_000),
        ]
        self.client = GeminiClient(self.settings, _genai_client=genai, ledger=None)

    def _call(self, tag: str, extra: str) -> None:
        self.client.generate_structured(
            system_prompt="s",
            user_prompt=extra,
            response_schema=_Reply,
            prompt_version="v1",
            model="gemini-3.8-flash",
            task_tag=tag,
        )

    def test_over_target_logs_the_split_by_tag(self) -> None:
        with capture_logs() as logs, script_cost_scope(self.settings, script_key="upload:7") as costs:
            self._call("extraction", "x")
            self._call("correction", "y")
        self.assertEqual(sorted(costs), ["correction", "extraction"])
        (line,) = [e for e in logs if e["event"] == "script_over_cost_target"]
        self.assertEqual(line["script_key"], "upload:7")
        self.assertEqual(sorted(line["by_tag"]), ["correction", "extraction"])
        self.assertAlmostEqual(line["total_usd"], round(sum(costs.values()), 6), places=6)
        self.assertEqual(line["log_level"], "warning")

    def test_under_target_logs_nothing(self) -> None:
        settings = self.settings.model_copy(
            update={"gemini": self.settings.gemini.model_copy(update={"paper_cost_target_usd": 100.0})}
        )
        with capture_logs() as logs, script_cost_scope(settings, script_key="k"):
            self._call("correction", "y")
        self.assertNotIn("script_over_cost_target", [e["event"] for e in logs])

    def test_calls_in_copied_context_threads_count(self) -> None:
        with script_cost_scope(self.settings, script_key="k") as costs:
            ctx = contextvars.copy_context()
            worker = threading.Thread(target=ctx.run, args=(self._call, "binding_second_read", "z"))
            worker.start()
            worker.join()
        self.assertIn("binding_second_read", costs)

    def test_no_scope_no_accumulation(self) -> None:
        with capture_logs() as logs:
            self._call("correction", "y")
        self.assertNotIn("script_over_cost_target", [e["event"] for e in logs])


class WiringTests(unittest.TestCase):
    def test_both_web_marking_routes_open_a_scope(self) -> None:
        for module in (student, teacher):
            with self.subTest(module=module.__name__):
                self.assertIn("script_cost_scope(", inspect.getsource(module))
```

- [ ] **Step 2: Run them to see them fail.** Run `python -m pytest tests/test_script_cost_scope.py -q --no-cov -o addopts=""`. Expected: `ImportError: cannot import name 'script_cost_scope'`.

- [ ] **Step 3: Implement.** In `GeminiSettings` (after `claude_files_api`):

```python
    # Spec §2 cost guard: a marked script whose model spend passes this logs
    # `script_over_cost_target` with the split by task tag. Never blocks marking.
    paper_cost_target_usd: float = Field(default=0.10, gt=0)
```

In `example_toml.py` after the `claude_files_api` line:

```python
    lines.append("# A script whose model spend passes this logs script_over_cost_target")
    lines.append("# (split by task tag). It never blocks marking.")
    lines.append(f"# paper_cost_target_usd = {s.gemini.paper_cost_target_usd}")
```

then `python -m lemely.runtime.example_toml`. In `lemely/io/gemini.py` add, next to `_call_labels`:

```python
#: The per-script cost accumulator `script_cost_scope` opens; None outside one.
_script_cost: contextvars.ContextVar[dict[str, float] | None] = contextvars.ContextVar(
    "lemely_script_cost", default=None
)


@contextlib.contextmanager
def script_cost_scope(settings: Settings, *, script_key: str) -> Iterator[dict[str, float]]:
    """Add up one script's paid calls by task tag; warn past ``paper_cost_target_usd``.

    Threads see the scope when started under ``contextvars.copy_context().run``
    (the binder's two reads and the uploads are). Never raises, never blocks.
    """
    costs: dict[str, float] = {}
    token = _script_cost.set(costs)
    try:
        yield costs
    finally:
        _script_cost.reset(token)
        total = sum(costs.values())
        target = settings.gemini.paper_cost_target_usd
        if total > target:
            structlog.get_logger().warning(
                "script_over_cost_target",
                script_key=script_key,
                total_usd=round(total, 6),
                target_usd=target,
                by_tag={tag: round(usd, 6) for tag, usd in sorted(costs.items())},
            )
```

In `_record_spend`, inside the `with _SPEND_LOCK:` block, after the `_process_cost_by_task` update, add:

```python
            scope = _script_cost.get()
            if scope is not None:
                bucket = task_tag or "untagged"
                scope[bucket] = scope.get(bucket, 0.0) + usd
```

In `lemely/web/routers/student.py`, import `from lemely.io.gemini import script_cost_scope` and wrap the span from `extracted = extract_answers(scan_path, mark_scheme, gemini_client=gemini_client)` through the end of the `report = grade_paper(...)` call:

```python
                with script_cost_scope(settings, script_key=f"upload:{owned.id}"):
                    extracted = extract_answers(scan_path, mark_scheme, gemini_client=gemini_client)
                    ensure_binding_allows_marking(extracted)
                    report = grade_paper(
                        mark_scheme,
                        extracted,
                        gemini_client=gemini_client,
                        student_id=None,
                        integrity_settings=settings.integrity,
                        options=settings.grading.marking_options(),
                    )
```

In `lemely/web/routers/teacher.py`, same import, and wrap from `repo.set_stage(paper_id, "extract")` through the end of its `report = grade_paper(...)` call:

```python
            with script_cost_scope(settings, script_key=f"teacher_paper:{paper_id}"):
                repo.set_stage(paper_id, "extract")
                extracted = extract_answers(scan_path, scheme, gemini_client=gemini_client)
                ensure_binding_allows_marking(extracted)

                repo.set_stage(paper_id, "mark")
                # (keep the existing comment block here unchanged)
                report = grade_paper(
                    scheme,
                    extracted,
                    gemini_client=gemini_client,
                    student_id=None,
                    history_store=None,
                    integrity_settings=settings.integrity,
                    options=settings.grading.marking_options(),
                )
```

Keep every other line of both functions as it is; only the indentation of the wrapped span changes.

- [ ] **Step 4: Run the tests.** Run `python -m pytest tests/test_script_cost_scope.py tests/test_llm_golden.py tests/test_settings_example_drift.py tests/test_web_app.py tests/test_web_practice.py -q --no-cov -o addopts=""` plus the teacher-route tests (`grep -l "teacher" tests/test_web*.py`). Expected: all pass.

- [ ] **Step 5: Prove the guard goes red.** Change `if total > target:` to `if total > target * 1e9:`; `test_over_target_logs_the_split_by_tag` must fail. Revert.

- [ ] **Step 6: Commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git add -- tests/test_script_cost_scope.py
git commit -S -m "feat(gemini): per-script cost scope warns past paper_cost_target_usd" -- lemely/io/gemini.py lemely/runtime/config.py lemely/runtime/example_toml.py lemely.toml.example lemely/web/routers/student.py lemely/web/routers/teacher.py tests/test_script_cost_scope.py
```

---

### Task 4: PDFs as documents; the mark-scheme and scan-metadata callers (spec T4)

**Files:**
- Modify: `lemely/io/gemini.py` (`documents` on `generate_structured`, `structured_cache_key`, `_structured_cache_key`, `_cache_key`, `_call_with_retry`, `_call_once`, `_build_request`; `model_for_tag`; the `file_paths`-on-Claude error)
- Modify: `lemely/io/llm/claude_provider.py` (`document_blocks`, request-size check, citations/structured-output guard)
- Modify: `lemely/io/providers/anthropic_adapter.py` (`documents` in `complete`, `count_tokens`, `_user_message`)
- Modify: `lemely/io/parsers.py`, `lemely/io/scan_metadata.py`
- Test: `tests/test_claude_documents.py` (new)

**Interfaces:**
- Consumes: Task 1a `DocumentInput`; Task 2b `_user_message`, `ClaudeProvider._pages`.
- Produces:
  - `GeminiClient.generate_structured(..., documents: Sequence[DocumentInput] | None = None)` and the same parameter on `structured_cache_key`. `file_paths` and `documents` together raise `ValueError`. The documents' hash is `sha256` over each document's bytes in order: for one document it equals today's `file_paths` hash, so a Gemini mark-scheme key does not move.
  - `GeminiClient.model_for_tag(task_tag: str) -> str` (public form of `_active_model(None, task_tag)`).
  - `claude_provider.MAX_REQUEST_BYTES = 32_000_000`, `claude_provider.MAX_PDF_PAGES = 100`, `claude_provider.document_blocks(docs: Sequence[DocumentInput]) -> list[DocumentBlockParam]`.
  - `AnthropicAdapter.complete(..., documents: Sequence[DocumentBlockParam] = ())`: documents go first, before images and text.
  - `file_paths` on a `claude-` model raises `ValueError` naming the task tag.

- [ ] **Step 1: Confirm in the docs.** https://platform.claude.com/docs/en/build-with-claude/pdf-support: the planner read "Maximum request size 32 MB; maximum pages per request 600 (100 when the request's context window is under 1M tokens)". Confirm Haiku 5.5's context window on the models page; if it is 1M or more, set `MAX_PDF_PAGES = 600`, else keep 100. Record it in the commit message.

- [ ] **Step 2: Write the failing tests.** Create `tests/test_claude_documents.py`:

```python
"""Spec 2026-10-19 §3 PDFs: typed PDFs as document blocks, scans as images; Gemini unchanged."""

from __future__ import annotations

import base64
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pypdfium2 as pdfium
from PIL import Image

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import AIMarkResponse
from lemely.io.gemini import GeminiClient, _reset_process_counters, record_calls
from lemely.io.llm import claude_provider
from lemely.io.llm.request import DocumentInput
from lemely.io.parsers import GeminiMarkSchemeParser
from lemely.io.providers import ProviderError
from lemely.io.scan_metadata import ScanMetadataExtractor
from tests.gemini_fakes import fake_genai_client, make_settings, mock_response
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _settings

_HAIKU = "claude-haiku-5-5"


def _pdf(pages: int) -> bytes:
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(612, 792)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)
        self.pdf = self.tmp / "ms.pdf"
        self.pdf.write_bytes(_pdf(2))

    def _claude(self, *outcomes: object, **gemini: object) -> tuple[GeminiClient, _FakeAnthropic]:
        settings = _settings(str(self.tmp))
        settings = settings.model_copy(update={"gemini": settings.gemini.model_copy(update=gemini)})
        fake = _FakeAnthropic(*outcomes)
        return GeminiClient(settings, _genai_client=object(), _anthropic_client=fake, ledger=None), fake


class ClaudeDocumentTests(_Base):
    def test_document_block_goes_first_as_base64_pdf(self) -> None:
        client, fake = self._claude(_message(_VALID_MARK))
        client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            documents=[DocumentInput.from_path(self.pdf, cache=True)],
            response_schema=AIMarkResponse,
            prompt_version="v1",
            model=_HAIKU,
            task_tag="mark_scheme",
        )
        content = fake.messages.calls[0]["messages"][0]["content"]
        self.assertEqual([b["type"] for b in content], ["document", "text"])
        self.assertEqual(content[0]["source"]["media_type"], "application/pdf")
        self.assertEqual(base64.b64decode(content[0]["source"]["data"]), self.pdf.read_bytes())
        self.assertEqual(content[0]["cache_control"], {"type": "ephemeral"})

    def test_too_many_pdf_pages_refused_before_sending(self) -> None:
        client, fake = self._claude(_message(_VALID_MARK))
        with patch.object(claude_provider, "MAX_PDF_PAGES", 1), self.assertRaisesRegex(ProviderError, "2 PDF pages"):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                documents=[DocumentInput.from_path(self.pdf)],
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model=_HAIKU,
                task_tag="mark_scheme",
            )
        self.assertEqual(fake.messages.calls, [])

    def test_request_over_32_mb_refused(self) -> None:
        client, fake = self._claude(_message(_VALID_MARK))
        with patch.object(claude_provider, "MAX_REQUEST_BYTES", 100), self.assertRaisesRegex(ProviderError, "bytes"):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                documents=[DocumentInput.from_path(self.pdf)],
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model=_HAIKU,
                task_tag="mark_scheme",
            )
        self.assertEqual(fake.messages.calls, [])

    def test_citations_with_a_response_schema_refused(self) -> None:
        """The API returns 400 for citations plus structured outputs; refuse before sending."""
        client, fake = self._claude(_message(_VALID_MARK))
        with self.assertRaisesRegex(ProviderError, "citations"):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                documents=[DocumentInput(data=b"scheme text", media_type="text/plain", citations=True)],
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model=_HAIKU,
                task_tag="correction",
            )
        self.assertEqual(fake.messages.calls, [])

    def test_file_paths_on_claude_name_the_task_tag(self) -> None:
        client, fake = self._claude()
        with self.assertRaisesRegex(ValueError, "task_tag='study_plan'"):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                file_paths=[self.pdf],
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model=_HAIKU,
                task_tag="study_plan",
            )

    def test_file_paths_and_documents_together_refused(self) -> None:
        client, _fake = self._claude()
        with self.assertRaises(ValueError):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                file_paths=[self.pdf],
                documents=[DocumentInput.from_path(self.pdf)],
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model="gemini-2.5-flash",
                task_tag="mark_scheme",
            )


class GeminiUnchangedTests(_Base):
    def test_parser_documents_reproduce_the_file_paths_call(self) -> None:
        def run(use_parser: bool) -> tuple[list[str], list[bytes], object]:
            tmp = Path(tempfile.mkdtemp())
            genai = fake_genai_client()
            genai.models.generate_content.return_value = mock_response("{}")
            client = GeminiClient(make_settings(str(tmp)), _genai_client=genai, ledger=None)
            with patch.object(MarkScheme, "model_validate_json", return_value=MagicMock()):
                if use_parser:
                    GeminiMarkSchemeParser(client)(self.pdf)
                else:
                    from lemely.io.prompts.mark_scheme_parsing import (
                        PARSER_SYSTEM_PROMPT,
                        PARSER_USER_PROMPT,
                        VERSION,
                    )

                    client.generate_structured(
                        system_prompt=PARSER_SYSTEM_PROMPT,
                        user_prompt=PARSER_USER_PROMPT,
                        file_paths=[self.pdf],
                        response_schema=MarkScheme,
                        prompt_version=VERSION,
                        task_tag="mark_scheme",
                    )
            keys = sorted(p.stem for p in (tmp / ".cache" / "gemini").glob("*.json"))
            uploads = [data for data, _cfg in genai.files.uploads]
            return keys, uploads, genai.models.generate_content.call_args.kwargs["contents"][0]

        self.assertEqual(run(use_parser=True), run(use_parser=False))

    def test_scan_metadata_on_gemini_still_uploads_the_pdf(self) -> None:
        client = MagicMock()
        client.model_for_tag.return_value = "gemini-3.5-flash-lite"
        ScanMetadataExtractor(client)(self.pdf)
        kwargs = client.generate_structured.call_args.kwargs
        self.assertEqual(kwargs["file_paths"], [self.pdf])
        self.assertNotIn("image_parts", kwargs)

    def test_scan_metadata_on_claude_sends_rasterised_pages(self) -> None:
        client = MagicMock()
        client.model_for_tag.return_value = _HAIKU
        page = MagicMock(png_bytes=b"\x89PNG-page")
        with patch("lemely.io.scan_metadata.rasterise_pdf_to_pages", return_value=[page, page]):
            ScanMetadataExtractor(client)(self.pdf)
        kwargs = client.generate_structured.call_args.kwargs
        self.assertEqual(kwargs["image_parts"], [b"\x89PNG-page", b"\x89PNG-page"])
        self.assertNotIn("file_paths", kwargs)

    def test_scan_metadata_with_a_mock_model_stays_on_gemini(self) -> None:
        client = MagicMock()
        ScanMetadataExtractor(client)(self.pdf)
        self.assertIn("file_paths", client.generate_structured.call_args.kwargs)
```

- [ ] **Step 3: Run them to see them fail.** Run `python -m pytest tests/test_claude_documents.py -q --no-cov -o addopts=""`. Expected: `TypeError: ... unexpected keyword argument 'documents'` and similar.

- [ ] **Step 4: The client.** In `lemely/io/gemini.py`:
  - add `documents: Sequence[DocumentInput] | None = None` (import `Sequence` from `collections.abc`) to `generate_structured` (after `file_paths`), `structured_cache_key`, `_structured_cache_key`, `_call_with_retry` and `_call_once` (keyword), and thread it through every call between them, exactly as `file_paths` is threaded (both `_call_with_retry` calls in `generate_structured`);
  - `_cache_key` gains a trailing keyword `documents: Sequence[DocumentInput] | None = None`, and its hashing chain becomes:

```python
        if image_parts:
            ...  # unchanged
        elif file_paths:
            ...  # unchanged
        elif documents:
            # One document hashes exactly as today's one-file `file_paths` does, so a
            # caller moved from file_paths to documents keeps its cache keys.
            h = hashlib.sha256()
            for doc in documents:
                h.update(doc.data)
            files_hash = h.hexdigest()[:12]
        else:
            files_hash = "none"
```

  - in `generate_structured`, replace the existing `if on_claude and file_paths:` block with:

```python
        if file_paths and documents:
            raise ValueError("pass file_paths or documents, not both")
        if on_claude and file_paths:
            raise ValueError(
                f"claude- models take no file_paths (task_tag={task_tag!r}); send typed PDFs "
                "as documents and scans as rasterised image_parts"
            )
```

  - in `_build_request` add the keyword `documents: Sequence[DocumentInput] | None = None` and set `documents=tuple(documents) if documents else tuple(DocumentInput.from_path(fp) for fp in (file_paths or ()))`;
  - add:

```python
    def model_for_tag(self, task_tag: str) -> str:
        """The model a call under ``task_tag`` runs on when it names none."""
        return self._active_model(None, task_tag)
```

- [ ] **Step 5: The Claude path.** In `lemely/io/llm/claude_provider.py` add:

```python
#: The API's request limit (PDF support docs, read 2026-10-19).
MAX_REQUEST_BYTES = 32_000_000
#: PDF pages per request when the context window is under 1M tokens (confirmed in Task 4 step 1).
MAX_PDF_PAGES = 100


def _pdf_pages(data: bytes, number: int) -> int:
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(data)
    except (pdfium.PdfiumError, ValueError, OSError) as exc:
        raise ProviderError(f"document {number} is not a readable PDF: {exc}") from exc
    try:
        return len(doc)
    finally:
        doc.close()


def document_blocks(docs: Sequence[DocumentInput]) -> list[DocumentBlockParam]:
    """``document`` blocks: PDFs as base64, text as plain text; page limit enforced."""
    blocks: list[DocumentBlockParam] = []
    pages = 0
    for number, doc in enumerate(docs, start=1):
        source: dict[str, Any]
        if doc.media_type == "application/pdf":
            pages += _pdf_pages(doc.data, number)
            source = {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(doc.data).decode("ascii"),
            }
        else:
            source = {"type": "text", "media_type": "text/plain", "data": doc.data.decode("utf-8")}
        block: dict[str, Any] = {"type": "document", "source": source}
        if doc.cache:
            block["cache_control"] = {"type": "ephemeral"}
        if doc.citations:
            block["citations"] = {"enabled": True}
        if doc.title:
            block["title"] = doc.title
        blocks.append(cast("DocumentBlockParam", block))
    if pages > MAX_PDF_PAGES:
        raise ProviderError(f"{pages} PDF pages in one Claude request; the limit is {MAX_PDF_PAGES}")
    return blocks


def _request_bytes(req: LLMRequest, images: Sequence[bytes]) -> int:
    """What the request body carries, near enough: base64 payloads plus the text."""
    docs = sum(
        image_fit.base64_len(len(d.data)) if d.media_type == "application/pdf" else len(d.data)
        for d in req.documents
    )
    pics = sum(image_fit.base64_len(len(i)) for i in images)
    text = sum(len(s.encode()) for s in (req.system, req.prompt, req.cache_prefix or ""))
    return docs + pics + text
```

  (imports: `base64`, `from collections.abc import Sequence`; under `TYPE_CHECKING` `from anthropic.types import DocumentBlockParam` and `from lemely.io.llm.request import DocumentInput`). In `ClaudeProvider.complete`, before the preflight block, add:

```python
        if req.response_schema is not None and any(d.citations for d in req.documents):
            raise ProviderError(
                "citations cannot be combined with a response schema (the API returns 400)"
            )
        documents = document_blocks(req.documents)
        size = _request_bytes(req, images)
        if size > MAX_REQUEST_BYTES:
            raise ProviderError(
                f"the request is {size} bytes; one Claude request takes at most {MAX_REQUEST_BYTES}"
            )
```

  and pass `documents=documents` to `self._adapter.complete(...)` and to the preflight `count_tokens(...)`.

  In `anthropic_adapter.py` give `_user_message`, `complete` and `count_tokens` a keyword `documents: Sequence[DocumentBlockParam] = ()`; in `_user_message` treat documents as content (the early "plain string" return applies only when there are no documents, images, ids or prefix) and build `content = [*documents, *image_blocks(images), *file_image_blocks(image_file_ids)]`.

- [ ] **Step 6: The callers.** `lemely/io/parsers.py`:

```python
from lemely.io.llm.request import DocumentInput
...
    def __call__(self, pdf_path: Path) -> MarkScheme:
        # A typed PDF: a Claude document block, or (on Gemini) the same Files API
        # upload `file_paths` made, under the same cache key.
        return self._client.generate_structured(
            system_prompt=PARSER_SYSTEM_PROMPT,
            user_prompt=PARSER_USER_PROMPT,
            documents=[DocumentInput.from_path(pdf_path)],
            response_schema=MarkScheme,
            prompt_version=VERSION,
            task_tag="mark_scheme",
        )
```

`lemely/io/scan_metadata.py`:

```python
from lemely.io.providers import is_anthropic_model
from lemely.io.rasterise import rasterise_pdf_to_pages
...
    def __call__(self, scan_path: Path) -> ExamMetadata:
        """Extract ExamMetadata from the given scan PDF.

        Gemini is sent the PDF itself. A claude- model takes no PDF scan: the pages
        are rasterised and sent as images (fitted by ``lemely.io.llm.image_fit``).
        """
        kwargs: dict[str, Any] = {
            "system_prompt": SCAN_META_SYSTEM_PROMPT,
            "user_prompt": build_scan_meta_user_prompt(scan_path),
            "response_schema": ExamMetadata,
            "prompt_version": VERSION,
            "task_tag": "scan_metadata",
            "extra_cache_key": scan_path.name,
        }
        model = self._client.model_for_tag("scan_metadata")
        if isinstance(model, str) and is_anthropic_model(model):
            pages = rasterise_pdf_to_pages(scan_path)
            return self._client.generate_structured(
                image_parts=[page.png_bytes for page in pages], **kwargs
            )
        return self._client.generate_structured(file_paths=[scan_path], **kwargs)
```

  (`from typing import TYPE_CHECKING, Any`; the `isinstance` guard keeps a `MagicMock` client on the Gemini path). Read `build_scan_meta_user_prompt`: if it calls the input "the attached PDF", leave it; the prompt text is not changed in this task (a prompt change would move the Gemini key), and note it in the commit message as a candidate for sub-project C.

- [ ] **Step 7: Run the tests.** Run `python -m pytest tests/test_claude_documents.py tests/test_parsers.py tests/test_scan_metadata.py tests/test_anthropic_adapter.py tests/test_claude_images.py tests/test_claude_uploads.py tests/test_llm_golden.py tests/test_gemini_client.py -q --no-cov -o addopts=""`. Expected: all pass.

- [ ] **Step 8: Prove the guards go red.** (a) In `_cache_key` hash `len(doc.data).to_bytes(8, "big")` before each document; `test_parser_documents_reproduce_the_file_paths_call` must fail. Revert. (b) Delete the citations guard in `ClaudeProvider.complete`; `test_citations_with_a_response_schema_refused` must fail. Revert.

- [ ] **Step 9: Commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git add -- tests/test_claude_documents.py
git commit -S -m "feat(anthropic): PDFs as document blocks; mark-scheme and scan-metadata callers on Claude" -- lemely/io/gemini.py lemely/io/llm/claude_provider.py lemely/io/providers/anthropic_adapter.py lemely/io/parsers.py lemely/io/scan_metadata.py tests/test_claude_documents.py
```

---

### Task 5: Code execution on Claude (spec T5)

**Files:**
- Modify: `lemely/io/llm/request.py` (`CLAUDE_CODE_EXECUTION_TAGS`, `CODE_EXECUTION_TOOL`)
- Modify: `lemely/io/providers/anthropic_adapter.py` (`complete_code_execution`, `code_execution_output`, `AnthropicReply.ran_code`)
- Modify: `lemely/io/llm/claude_provider.py` (`req.tool` path; container seconds)
- Modify: `lemely/io/gemini.py` (`generate_with_code_execution` allows Claude on non-student tags; the no-result message names the provider)
- Test: `tests/test_claude_code_execution.py` (new)

**Interfaces:**
- Consumes: Task 3a `CODE_EXECUTION_MIN_BILLED_SECONDS`, `Usage.container_seconds`; Task 1b `_call_code_execution_once`.
- Produces:
  - `request.CODE_EXECUTION_TOOL = "code_execution_20260521"`, `request.CLAUDE_CODE_EXECUTION_TAGS = frozenset({"question_validity", "generation"})`.
  - `AnthropicReply.ran_code: bool = False`; `AnthropicAdapter.complete_code_execution(*, model: str, prompt: str, thinking: str | None, max_tokens: int = MAX_OUTPUT_TOKENS) -> AnthropicReply`; `code_execution_output(message) -> tuple[str, bool]` (text, whether code ran).
  - Reply text: the `stdout` of the last code-execution result with `return_code == 0` and non-empty output; failing that, the last text block. (Spec says "the final text block"; stdout is what today's Gemini contract returns, "what the executed code printed", and the prompt asks the code to print only the answer. The final text block is the fallback.)
  - Billed container time: `max(latency_seconds, 300)` when code ran, else 0.
  - `generate_with_code_execution` on a `claude-` model with any tag outside `CLAUDE_CODE_EXECUTION_TAGS` (including None) raises `ValueError` before sending.

- [ ] **Step 1: Confirm in the docs.** https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool (the planner read on 2026-10-19: latest `code_execution_20260521`; 5-minute minimum; $0.05 per container-hour; result blocks `bash_code_execution_tool_result` with `content.stdout`, `content.return_code`; no container time in `usage`). Confirm the tool block shape `{"type": "code_execution_20260521", "name": "code_execution"}` and whether a Python result block type (`code_execution_tool_result` with `code_execution_result`) still occurs; the parser below accepts both.

- [ ] **Step 2: Write the failing tests.** Create `tests/test_claude_code_execution.py`:

```python
"""Spec 2026-10-19 §3 code execution: Claude's server tool, priced by container time."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from lemely.io.gemini import GeminiClient, _reset_process_counters, process_call_records, record_calls
from lemely.runtime.errors import ParseError
from tests.test_anthropic_adapter import _FakeAnthropic, _settings

_HAIKU = "claude-haiku-5-5"


def _result(stdout: str, return_code: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        type="bash_code_execution_tool_result",
        content=SimpleNamespace(
            type="bash_code_execution_result", stdout=stdout, stderr="", return_code=return_code
        ),
    )


def _message(*blocks: object) -> SimpleNamespace:
    return SimpleNamespace(
        content=list(blocks),
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=2_000,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            output_tokens=300,
            output_tokens_details=SimpleNamespace(thinking_tokens=0),
        ),
    )


class CodeExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)

    def _run(self, *outcomes: object, tag: str | None = "question_validity") -> tuple[str, _FakeAnthropic]:
        fake = _FakeAnthropic(*outcomes)
        client = GeminiClient(_settings(self.tmp), _genai_client=object(), _anthropic_client=fake, ledger=None)
        text = client.generate_with_code_execution(
            prompt="compute 6*7", prompt_version="v1", model=_HAIKU, task_tag=tag
        )
        return text, fake

    def test_reply_is_the_stdout_of_the_last_successful_run(self) -> None:
        text, fake = self._run(
            _message(
                _result("42\n"),
                _result("41\n", return_code=1),
                SimpleNamespace(type="text", text="The answer is 42."),
            )
        )
        self.assertEqual(text, "42")
        (call,) = fake.messages.calls
        self.assertEqual(call["tools"], [{"type": "code_execution_20260521", "name": "code_execution"}])
        self.assertNotIn("format", call.get("output_config", {}))

    def test_falls_back_to_the_final_text_block(self) -> None:
        text, _fake = self._run(_message(SimpleNamespace(type="text", text="42")))
        self.assertEqual(text, "42")

    def test_container_time_billed_at_the_five_minute_minimum(self) -> None:
        self._run(_message(_result("42\n")))
        (rec,) = process_call_records()
        self.assertEqual(rec.container_seconds, 300)
        expected = (2_000 * 0.10 + 300 * 0.50) / 1e6 + 300 / 3600 * 0.05
        self.assertAlmostEqual(rec.usd_now, expected, places=12)

    def test_no_code_ran_no_container_time(self) -> None:
        self._run(_message(SimpleNamespace(type="text", text="42")))
        (rec,) = process_call_records()
        self.assertEqual(rec.container_seconds, 0)

    def test_student_data_tags_refused_before_sending(self) -> None:
        for tag in ("correction", "extraction", None):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                self._run(_message(_result("42\n")), tag=tag)

    def test_empty_reply_is_a_parse_error(self) -> None:
        with self.assertRaises(ParseError):
            self._run(_message())

    def test_cache_key_is_not_the_structured_calls(self) -> None:
        fake = _FakeAnthropic()
        client = GeminiClient(_settings(self.tmp), _genai_client=object(), _anthropic_client=fake, ledger=None)
        plain = client._params_fingerprint(_HAIKU, "question_validity", None)
        tool = client._params_fingerprint(_HAIKU, "question_validity", None, tool="code_execution")
        self.assertNotEqual(plain, tool)
```

- [ ] **Step 3: Run them to see them fail.** Run `python -m pytest tests/test_claude_code_execution.py -q --no-cov -o addopts=""`. Expected: `ValueError: generate_with_code_execution is Gemini-only` on the success cases.

- [ ] **Step 4: Implement.** In `request.py` add:

```python
#: Claude's server-side code-execution tool version (docs read 2026-10-19).
CODE_EXECUTION_TOOL = "code_execution_20260521"
#: Code execution is not covered by zero data retention: only tags that carry no
#: student data may use it on Claude.
CLAUDE_CODE_EXECUTION_TAGS: frozenset[str] = frozenset({"question_validity", "generation"})
```

In `anthropic_adapter.py`: add `ran_code: bool = False` as the last field of `AnthropicReply`, and:

```python
_RESULT_BLOCKS = frozenset({"bash_code_execution_tool_result", "code_execution_tool_result"})
_RESULT_CONTENT = frozenset({"bash_code_execution_result", "code_execution_result"})


def code_execution_output(message: Message) -> tuple[str, bool]:
    """What the code printed (last successful run), else the final text; and whether code ran."""
    stdout: str | None = None
    ran = False
    for block in message.content:
        if getattr(block, "type", None) not in _RESULT_BLOCKS:
            continue
        ran = True
        content = getattr(block, "content", None)
        if getattr(content, "type", None) not in _RESULT_CONTENT:
            continue
        out = getattr(content, "stdout", "") or ""
        if getattr(content, "return_code", 1) == 0 and out.strip():
            stdout = out
    if stdout is not None:
        return stdout.strip(), ran
    texts = [b.text for b in message.content if getattr(b, "type", None) == "text"]
    return (texts[-1].strip() if texts else ""), ran
```

and on `AnthropicAdapter`:

```python
    def complete_code_execution(
        self, *, model: str, prompt: str, thinking: str | None, max_tokens: int = MAX_OUTPUT_TOKENS
    ) -> AnthropicReply:
        """One request with Claude's code-execution tool; plain text, no response schema."""
        from lemely.io.llm.request import CODE_EXECUTION_TOOL

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"type": CODE_EXECUTION_TOOL, "name": "code_execution"}],
            "thinking": {"type": "adaptive"},
        }
        if thinking is not None:
            kwargs["output_config"] = {"effort": effort_for(thinking)}
        response = self._send(**kwargs)
        text, ran = code_execution_output(response)
        return AnthropicReply(
            text=text, usage=_usage_of(response), stop_reason=response.stop_reason, ran_code=ran
        )
```

In `claude_provider.py`, at the top of `ClaudeProvider.complete`:

```python
        if req.tool is not None:
            return self._complete_code_execution(req)
```

and the method:

```python
    def _complete_code_execution(self, req: LLMRequest) -> ProviderReply:
        """Claude's code-execution tool; container time billed at the 5-minute minimum."""
        t0 = time.monotonic()
        try:
            reply = self._adapter.complete_code_execution(
                model=req.model,
                prompt=req.prompt,
                thinking=req.effort,
                max_tokens=req.max_output_tokens,
            )
        except ProviderTransientError as exc:
            raise TransientCallError(str(exc)) from exc
        except ExternalServiceError:
            raise
        except (anthropic.AnthropicError, OSError) as exc:
            raise ExternalServiceError(str(exc)) from exc
        latency_ms = int((time.monotonic() - t0) * 1000)
        seconds = (
            max(latency_ms / 1000, float(CODE_EXECUTION_MIN_BILLED_SECONDS)) if reply.ran_code else 0.0
        )
        usage = dataclasses.replace(reply.usage, container_seconds=seconds)
        return ProviderReply(
            text=reply.text,
            usage_response=usage_as_gemini_response(usage),
            stop_reason=reply.stop_reason,
            stop_detail=str(reply.stop_reason),
            latency_ms=latency_ms,
            usage=usage,
        )
```

(imports `dataclasses`, `from lemely.io.llm.pricing import CODE_EXECUTION_MIN_BILLED_SECONDS`). In `gemini.py` `generate_with_code_execution`, replace the `if is_anthropic_model(active_model): raise ValueError(... Gemini-only ...)` block with:

```python
        if is_anthropic_model(active_model) and task_tag not in CLAUDE_CODE_EXECUTION_TAGS:
            raise ValueError(
                "code execution on Claude is allowed only for task tags "
                f"{sorted(CLAUDE_CODE_EXECUTION_TAGS)} (it is not ZDR-covered and must "
                f"never see student data); got task_tag={task_tag!r}"
            )
```

(import `CLAUDE_CODE_EXECUTION_TAGS` from `lemely.io.llm.request`), and in `_call_code_execution_once` change the final raise to:

```python
        provider = "Anthropic" if is_anthropic_model(model) else "Gemini"
        raise ParseError(
            f"{provider} code_execution call ({model}) returned no code_execution_result part."
        )
```

(the Gemini message is unchanged byte for byte).

- [ ] **Step 5: Run the tests.** Run `python -m pytest tests/test_claude_code_execution.py tests/test_anthropic_adapter.py tests/test_question_generation.py tests/test_gemini_cost_record.py tests/test_gemini_client.py tests/test_llm_golden.py -q --no-cov -o addopts=""`. Expected: all pass (`test_code_execution_rejects_claude_model` still raises: it passes no tag).

- [ ] **Step 6: Prove the guards go red.** (a) Remove the `task_tag not in CLAUDE_CODE_EXECUTION_TAGS` condition; `test_student_data_tags_refused_before_sending` must fail. Revert. (b) In `code_execution_output` drop the `getattr(content, "return_code", 1) == 0 and` test; `test_reply_is_the_stdout_of_the_last_successful_run` must fail (it returns the failed run's "41"). Revert.

- [ ] **Step 7: Commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git add -- tests/test_claude_code_execution.py
git commit -S -m "feat(anthropic): code execution on Claude for non-student tags, billed by container time" -- lemely/io/llm/request.py lemely/io/providers/anthropic_adapter.py lemely/io/llm/claude_provider.py lemely/io/gemini.py tests/test_claude_code_execution.py
```

---
### Task 6: B1 cache breakpoints per tag (spec T6; §4 B1)

**Files:**
- Modify: `lemely/io/llm/request.py` (`LEGACY_CLAUDE_CACHE_PLAN`, `CACHE_MIN_TOKENS`, `CHARS_PER_TOKEN`)
- Modify: `lemely/io/providers/anthropic_adapter.py` (`_request_parts` places breakpoints by plan and the 512-token rule; `complete`/`count_tokens` take `cache_plan`)
- Modify: `lemely/io/llm/claude_provider.py` (passes `req.cache_plan`)
- Modify: `lemely/io/gemini.py` (`_build_request` sets the plan from settings)
- Modify: `lemely/io/binding/orchestrate.py` (`_reads_share_a_claude_cache`; sequential reads when they do)
- Modify: `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example` (`claude_cache_for`)
- Test: `tests/test_claude_cache_plan.py` (new); `tests/test_anthropic_adapter.py` (two tests get long prompts)

**Interfaces:**
- Consumes: Task 1a `CachePlan`, `CacheSpot`, `MAX_CACHE_BREAKPOINTS`; Task 4 `documents`; Task 2a `estimate_tokens`.
- Produces:
  - `request.LEGACY_CLAUDE_CACHE_PLAN = CachePlan(("system", "prefix"))`: what a `claude-` call has done since lever A1 (system prompt and shared-prefix paper marked). Used for a tag with no `claude_cache_for` entry, so the lever is off by default.
  - `request.CACHE_MIN_TOKENS = 512`, `request.CHARS_PER_TOKEN = 4`.
  - `GeminiSettings.claude_cache_for: dict[str, list[Literal["system", "documents", "images", "prefix"]]] = {}`; each list at most 4 entries, no repeats (validated).
  - Block order: system, documents, images, prefix text, per-call text. A spot gets `cache_control` only when the estimated tokens of everything up to and including it reach `CACHE_MIN_TOKENS` (text at 4 characters a token, images by `estimate_tokens`, a file-id image or a PDF counted as at least the minimum). More than 4 `cache_control` blocks in one request (plan plus documents marked `cache`) raises `ProviderError`.
  - `AnthropicAdapter.complete(..., cache_plan: CachePlan | None = None)` and `count_tokens(..., cache_plan=None)`; None means `LEGACY_CLAUDE_CACHE_PLAN`.
  - `orchestrate._reads_share_a_claude_cache(settings: Settings, first_model: str, second_model: str) -> bool`: both reads on the same `claude-` model and `"images"` in `claude_cache_for` for both `extraction` and `binding_second_read`. Then `run_binding` makes the first read, then the second (`_read_second_after`), instead of both at once: a prompt-cache entry is readable only once the first response has begun, so parallel reads would both write and neither hit.

- [ ] **Step 1: Confirm the effort risk in the docs.** Read https://platform.claude.com/docs/en/build-with-claude/prompt-caching ("what invalidates the cache"). Record in the commit body whether a different `output_config.effort` (or thinking setting) between two requests invalidates the cached message blocks. Either way the default config is safe: `extraction` (`minimal`, mapped to `low`) and `binding_second_read` (`low`) send the same effort. If the docs say it invalidates, add one sentence to the `claude_cache_for` comment in `example_toml.py`: "Both binder tags must send the same effort for the second read to hit." The live check of the same question (two Haiku calls) is made by the main session before Task 11 (see Task 11 step 2).

- [ ] **Step 2: Write the failing tests.** Create `tests/test_claude_cache_plan.py`:

```python
"""Spec 2026-10-19 §4 B1: cache breakpoints per tag, the 512-token rule, binder reads."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pydantic
from PIL import Image

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import AIMarkResponse
from lemely.io.binding import orchestrate
from lemely.io.binding.orchestrate import run_binding
from lemely.io.gemini import GeminiClient, _reset_process_counters, record_calls
from lemely.io.llm.request import DocumentInput
from lemely.io.providers import ProviderError
from lemely.runtime.config import GeminiSettings
from tests.gemini_fakes import fake_genai_client, make_settings
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _settings
from tests.test_extraction_binding import _items, _Model, _pages, _run

_HAIKU = "claude-haiku-5-5"
_LONG = "x" * 4_000  # 1,000 estimated tokens
_ROOT = Path(__file__).resolve().parents[1]
_EPHEMERAL = {"type": "ephemeral"}


def _page() -> bytes:
    buf = io.BytesIO()
    Image.new("L", (1000, 1400), 200).save(buf, "PNG")
    return buf.getvalue()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)

    def _call(self, cache_for: dict[str, list[str]] | None = None, **kwargs: Any) -> dict[str, Any]:
        settings = _settings(self.tmp)
        if cache_for is not None:
            settings = settings.model_copy(
                update={"gemini": settings.gemini.model_copy(update={"claude_cache_for": cache_for})}
            )
        fake = _FakeAnthropic(_message(_VALID_MARK))
        client = GeminiClient(settings, _genai_client=object(), _anthropic_client=fake, ledger=None)
        params: dict[str, Any] = {
            "system_prompt": _LONG,
            "user_prompt": "read",
            "response_schema": AIMarkResponse,
            "prompt_version": "v1",
            "model": _HAIKU,
            "task_tag": "binding_second_read",
            **kwargs,
        }
        client.generate_structured(**params)
        (call,) = fake.messages.calls
        return call


def _marked(call: dict[str, Any]) -> list[str]:
    """The type of every block that carries cache_control, system first."""
    blocks = list(call["system"]) + list(
        call["messages"][0]["content"] if isinstance(call["messages"][0]["content"], list) else []
    )
    return [b["type"] for b in blocks if b.get("cache_control") == _EPHEMERAL]


class PlanTests(_Base):
    def test_default_is_the_legacy_system_breakpoint(self) -> None:
        call = self._call(image_parts=[_page()])
        self.assertEqual(_marked(call), ["text"])
        self.assertIn("cache_control", call["system"][0])

    def test_images_breakpoint_marks_the_last_image(self) -> None:
        call = self._call(
            cache_for={"binding_second_read": ["system", "images"]}, image_parts=[_page(), _page()]
        )
        content = call["messages"][0]["content"]
        self.assertNotIn("cache_control", content[0])
        self.assertEqual(content[1]["cache_control"], _EPHEMERAL)
        self.assertEqual(_marked(call), ["text", "image"])

    def test_empty_plan_marks_nothing(self) -> None:
        call = self._call(cache_for={"binding_second_read": []}, image_parts=[_page()])
        self.assertEqual(_marked(call), [])

    def test_a_prefix_under_512_tokens_gets_no_breakpoint(self) -> None:
        call = self._call(cache_for={"binding_second_read": ["system"]}, system_prompt="short")
        self.assertEqual(_marked(call), [])

    def test_documents_breakpoint_marks_the_last_document(self) -> None:
        call = self._call(
            cache_for={"binding_second_read": ["documents"]},
            system_prompt="",
            documents=[DocumentInput(data=b"y" * 4_000, media_type="text/plain")],
            response_schema=AIMarkResponse,
        )
        self.assertEqual(_marked(call), ["document"])

    def test_more_than_four_breakpoints_in_one_request_refused(self) -> None:
        docs = [DocumentInput(data=b"y" * 4_000, media_type="text/plain", cache=True)] * 4
        with self.assertRaisesRegex(ProviderError, "cache breakpoints"):
            self._call(documents=docs)

    def test_settings_refuse_five_spots_or_a_repeat(self) -> None:
        for spots in (["system", "documents", "images", "prefix", "system"], ["images", "images"]):
            with self.subTest(spots=spots), self.assertRaises(pydantic.ValidationError):
                GeminiSettings(claude_cache_for={"extraction": spots})


def _scheme() -> MarkScheme:
    path = _ROOT / "corpus" / "mark-schemes" / "0625_w24_ms_41.json"
    return MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _binder_client(tmp: str, cache_for: dict[str, list[str]]) -> GeminiClient:
    settings = make_settings(tmp)
    settings = settings.model_copy(
        update={
            "binding": settings.binding.model_copy(update={"read_model": _HAIKU}),
            "gemini": settings.gemini.model_copy(update={"claude_cache_for": cache_for}),
        }
    )
    return GeminiClient(settings, _genai_client=fake_genai_client(), ledger=None)


class BinderSequencingTests(unittest.TestCase):
    _SHARED = {"extraction": ["system", "images"], "binding_second_read": ["system", "images"]}

    def _bind(self, cache_for: dict[str, list[str]]) -> tuple[_Model, Any]:
        client = _binder_client(tempfile.mkdtemp(), cache_for)
        model = _Model(first=_items(_run(1)), second=_items(_run(1)))
        pages = _pages()
        with (
            client.image_uploads([p.png_bytes for p in pages], concurrency=1) as uploads,
            patch.object(client, "generate_structured", side_effect=model),
            patch.object(orchestrate, "_read_both", wraps=orchestrate._read_both) as both,
        ):
            outcome = run_binding(
                client, pages, _scheme(), uploads=uploads, settings=client._settings, manifest_key="k"
            )
        self.assertEqual(outcome.report.verdict if outcome.report else None, "pass")
        return model, both

    def test_reads_sharing_a_claude_cache_run_one_after_the_other(self) -> None:
        model, both = self._bind(self._SHARED)
        both.assert_not_called()
        self.assertEqual([c["task_tag"] for c in model.calls], ["extraction", "binding_second_read"])

    def test_without_the_images_breakpoint_the_reads_run_together(self) -> None:
        _model, both = self._bind({})
        both.assert_called_once()

    def test_the_predicate(self) -> None:
        settings = _binder_client(tempfile.mkdtemp(), self._SHARED)._settings
        share = orchestrate._reads_share_a_claude_cache
        self.assertTrue(share(settings, _HAIKU, _HAIKU))
        self.assertFalse(share(settings, _HAIKU, "claude-sonnet-5-5"))
        self.assertFalse(share(settings, "gemini-3.8-flash", "gemini-3.8-flash"))
```

In `tests/test_anthropic_adapter.py`: in `test_prompt_caching_marks_system_and_prefix` replace `system_prompt="sys"` by `system_prompt=_LONG_SYSTEM` (both calls) and `"sys"` in the expected system block by `_LONG_SYSTEM`; in `test_images_come_before_a_cached_prefix_too` replace `cache_prefix="paper"` by `cache_prefix=_LONG_PREFIX` and the expected `"paper"` by `_LONG_PREFIX`. Define at module level `_LONG_SYSTEM = "s" * 2_100` and `_LONG_PREFIX = "p" * 2_100` (over 512 estimated tokens each). The adapter tests' meaning is unchanged: they pin that the legacy spots are marked.

- [ ] **Step 3: Run them to see them fail.** Run `python -m pytest tests/test_claude_cache_plan.py -q --no-cov -o addopts=""`. Expected: failures (`claude_cache_for` is an unknown setting; no image breakpoint; `_reads_share_a_claude_cache` missing).

- [ ] **Step 4: Settings.** In `lemely/runtime/config.py` (add `field_validator` to the pydantic import):

```python
ClaudeCacheSpot = Literal["system", "documents", "images", "prefix"]
```

  at module level near `ThinkingLevel`, and in `GeminiSettings` after `paper_cost_target_usd`:

```python
    # Spec §4 B1: prompt-cache breakpoints per task tag for claude- calls. A tag not
    # listed keeps the A1 behaviour (system prompt and shared-prefix paper marked).
    # "images" after the binder's pages lets its second read hit the first's cache;
    # with it on both binder tags and both reads on one claude- model, the reads run
    # one after the other. At most 4 spots per tag.
    claude_cache_for: dict[str, list[ClaudeCacheSpot]] = Field(default_factory=dict)

    @field_validator("claude_cache_for")
    @classmethod
    def _at_most_four_distinct_spots(
        cls, value: dict[str, list[ClaudeCacheSpot]]
    ) -> dict[str, list[ClaudeCacheSpot]]:
        for tag, spots in value.items():
            if len(spots) > 4 or len(set(spots)) != len(spots):
                raise ValueError(f"claude_cache_for[{tag!r}]: at most 4 distinct spots, got {spots}")
        return value
```

  In `example_toml.py` after `paper_cost_target_usd`:

```python
    lines.append("# Claude prompt-cache breakpoints per task tag: system | documents | images |")
    lines.append("# prefix. Unlisted tags mark system and prefix (the A1 behaviour).")
    lines.append(f"# claude_cache_for = {_toml_inline(s.gemini.claude_cache_for)}")
```

  then `python -m lemely.runtime.example_toml`.

- [ ] **Step 5: Request, client, provider.** In `request.py`:

```python
#: Below this many tokens a cache breakpoint is not placed (5.5 models' minimum).
CACHE_MIN_TOKENS = 512
#: Text-length estimate of tokens.
CHARS_PER_TOKEN = 4
#: The breakpoints every claude- call has placed since lever A1.
LEGACY_CLAUDE_CACHE_PLAN = CachePlan(breakpoints=("system", "prefix"))
```

  In `GeminiClient._build_request`, for Claude:

```python
            spots = self._settings.gemini.claude_cache_for.get(task_tag or "")
            cache_plan = LEGACY_CLAUDE_CACHE_PLAN if spots is None else CachePlan(tuple(spots))
```

  and `CachePlan()` for Gemini; pass `cache_plan=cache_plan` to `LLMRequest`. In `ClaudeProvider.complete` and in its preflight `count_tokens` call pass `cache_plan=req.cache_plan`.

- [ ] **Step 6: The adapter.** Replace `_user_message` with `_request_parts`, used by `complete` and `count_tokens` (each now builds `system, message = self._request_parts(...)` instead of building `system` itself):

```python
_EPHEMERAL: CacheControlEphemeralParam = {"type": "ephemeral"}


def _image_tokens(data: bytes) -> int:
    with Image.open(io.BytesIO(data)) as img:
        return estimate_tokens(*img.size)


def _request_parts(
    *,
    system_prompt: str,
    user_prompt: str,
    cache_prefix: str | None,
    documents: Sequence[DocumentBlockParam],
    images: Sequence[bytes],
    image_file_ids: Sequence[str],
    cache_plan: CachePlan | None,
) -> tuple[list[TextBlockParam], MessageParam]:
    """System blocks and the user message, with breakpoints where the plan and size allow.

    Order: system, documents, images, prefix, per-call text. A spot is marked only
    when the estimated tokens up to and including it reach CACHE_MIN_TOKENS.
    """
    spots = set((cache_plan or LEGACY_CLAUDE_CACHE_PLAN).breakpoints)
    running = len(system_prompt) // CHARS_PER_TOKEN
    system: list[TextBlockParam] = []
    if system_prompt:
        block: TextBlockParam = {"type": "text", "text": system_prompt}
        if "system" in spots and running >= CACHE_MIN_TOKENS:
            block["cache_control"] = _EPHEMERAL
        system.append(block)
    docs = [cast("DocumentBlockParam", dict(d)) for d in documents]
    for doc in docs:
        source = cast("dict[str, Any]", doc["source"])
        running += (
            len(source["data"]) // CHARS_PER_TOKEN if source["type"] == "text" else CACHE_MIN_TOKENS
        )
    if docs and "documents" in spots and running >= CACHE_MIN_TOKENS:
        docs[-1]["cache_control"] = _EPHEMERAL
    pictures = [*image_blocks(images), *file_image_blocks(image_file_ids)]
    running += sum(_image_tokens(i) for i in images) + CACHE_MIN_TOKENS * len(image_file_ids)
    if pictures and "images" in spots and running >= CACHE_MIN_TOKENS:
        pictures[-1]["cache_control"] = _EPHEMERAL
    content: list[ContentBlockParam] = [*docs, *pictures]
    if cache_prefix:
        running += len(cache_prefix) // CHARS_PER_TOKEN
        prefix: TextBlockParam = {"type": "text", "text": cache_prefix}
        if "prefix" in spots and running >= CACHE_MIN_TOKENS:
            prefix["cache_control"] = _EPHEMERAL
        content.append(prefix)
    marked = sum(1 for b in [*system, *content] if "cache_control" in b)
    if marked > MAX_CACHE_BREAKPOINTS:
        raise ProviderError(
            f"{marked} cache breakpoints in one Claude request; the limit is {MAX_CACHE_BREAKPOINTS}"
        )
    if not content:
        return system, {"role": "user", "content": user_prompt}
    content.append({"type": "text", "text": user_prompt})
    return system, {"role": "user", "content": content}
```

  (imports: `io`, `from PIL import Image`, `from lemely.io.llm.image_fit import estimate_tokens`, `from lemely.io.llm.request import CACHE_MIN_TOKENS, CHARS_PER_TOKEN, LEGACY_CLAUDE_CACHE_PLAN, MAX_CACHE_BREAKPOINTS, CachePlan`; `CacheControlEphemeralParam` under `TYPE_CHECKING`). `complete` and `count_tokens` gain `cache_plan: CachePlan | None = None`. `count_tokens` sends the same system blocks (`cache_control` is accepted by the count endpoint). `generate` passes nothing new (legacy plan).

- [ ] **Step 7: Binder reads.** In `lemely/io/binding/orchestrate.py` add:

```python
def _reads_share_a_claude_cache(settings: Settings, first_model: str, second_model: str) -> bool:
    """Both reads on one claude- model, each with a breakpoint after the pages (spec §4 B1).

    The second read can then be served the pages from the first read's prompt cache,
    but only once the first response has begun: so the reads are made in turn.
    """
    if first_model != second_model or not is_anthropic_model(first_model):
        return False
    cache_for = settings.gemini.claude_cache_for
    return all("images" in cache_for.get(tag, []) for tag in (_FIRST_READ[0], _SECOND_READ[0]))
```

  (import `is_anthropic_model` from `lemely.io.providers`), and in `run_binding` replace the `elif binding.second_read:` branch's `try` body with:

```python
        try:
            if _reads_share_a_claude_cache(settings, binding.read_model, second_model):
                first_read = _first()
                second_read = _read_second_after(
                    _second, forget_second=lambda: client.forget_cached(read_cache_keys[1:])
                )
            else:
                first_read, second_read = _read_both(
                    _first, _second, forget_second=lambda: client.forget_cached(read_cache_keys[1:])
                )
```

  (the `except` clauses after it stay). Add one sentence to `run_binding`'s docstring: "When both reads share a Claude prompt cache (`_reads_share_a_claude_cache`) the second is made after the first, not beside it."

- [ ] **Step 8: Run the tests.** Run `python -m pytest tests/test_claude_cache_plan.py tests/test_anthropic_adapter.py tests/test_claude_documents.py tests/test_claude_images.py tests/test_extraction_binding.py tests/test_correction_shared_prefix.py tests/test_settings_example_drift.py tests/test_llm_golden.py -q --no-cov -o addopts=""`. Expected: all pass.

- [ ] **Step 9: Prove the guards go red.** (a) Change `running >= CACHE_MIN_TOKENS` to `True` for the system block; `test_a_prefix_under_512_tokens_gets_no_breakpoint` must fail. Revert. (b) Make `_reads_share_a_claude_cache` return False always; `test_reads_sharing_a_claude_cache_run_one_after_the_other` must fail. Revert.

- [ ] **Step 10: Commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git add -- tests/test_claude_cache_plan.py
git commit -S -m "feat(anthropic): per-tag Claude cache breakpoints; binder reads share the page cache" -- lemely/io/llm/request.py lemely/io/providers/anthropic_adapter.py lemely/io/llm/claude_provider.py lemely/io/gemini.py lemely/io/binding/orchestrate.py lemely/runtime/config.py lemely/runtime/example_toml.py lemely.toml.example tests/test_claude_cache_plan.py tests/test_anthropic_adapter.py
```

---

### Task 7: B3 effort per tag and per leaf kind (spec T7; §4 B3, §5.2)

**Files:**
- Create: `lemely/core/leaf_kind.py`
- Modify: `lemely/io/gemini.py` (`_call_leaf_kind` context variable; `generate_structured` and `structured_cache_key` take `leaf_kind`; `_resolved_gen_params` Claude branch)
- Modify: `lemely/io/providers/anthropic_adapter.py` (`Effort` widened; an effort value passes through)
- Modify: `lemely/io/correction_ai.py` (`_PrefixKwargs` carries `leaf_kind` when the table is set)
- Modify: `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example` (`claude_effort_for`)
- Test: `tests/test_claude_effort.py` (new)

**Interfaces:**
- Consumes: `QuestionType` (`lemely.core.loose_schemas`); Task 1a `Effort`.
- Produces:
  - `lemely.core.leaf_kind.LeafKind = Literal["mcq", "numeric", "short", "extended"]`, `leaf_kind(question: Question) -> LeafKind`. Mapping (spec says "from the leaf's mark-scheme answer type"; the scheme's type is `QuestionType`): `mcq`, `tickbox` -> `mcq`; `calculation`, `equation`, `graph_read` -> `numeric`; `explanation`, `comparison`, `multi_step`, `levels_based`, `indicative_content`, `fieldwork` -> `extended`; `recall`, `list`, `table`, `diagram`, `graph_draw` -> `short`.
  - `GeminiSettings.claude_effort_for: dict[str, Literal["low", "medium", "high", "xhigh", "max"]] = {}`, keyed by tag or `tag:kind`.
  - `generate_structured(..., leaf_kind: str | None = None)`, `structured_cache_key(..., leaf_kind=None)`. Effort for a `claude-` model: `claude_effort_for["tag:kind"]`, else `claude_effort_for["tag"]`, else `effort_for(thinking_level_for[tag])`. Effort is already in the cache key (`thinking_level` in the fingerprint). Gemini ignores `leaf_kind`.
  - `anthropic_adapter.EFFORTS = ("low", "medium", "high", "xhigh", "max")`; `Effort` is that literal. `complete(thinking=...)` sends an effort value as is and maps a thinking level through `effort_for`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_claude_effort.py`:

```python
"""Spec 2026-10-19 §4 B3: Claude effort per tag and per leaf kind."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

from lemely.core.leaf_kind import leaf_kind
from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import AIMarkResponse
from lemely.io.gemini import GeminiClient, _reset_process_counters, record_calls
from tests.gemini_fakes import fake_genai_client, make_settings, mock_response
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _settings

_HAIKU = "claude-haiku-5-5"


class LeafKindTests(unittest.TestCase):
    def test_every_question_type_has_a_kind(self) -> None:
        for qtype in QuestionType:
            with self.subTest(qtype=qtype):
                self.assertIn(leaf_kind(MagicMock(type=qtype)), {"mcq", "numeric", "short", "extended"})

    def test_examples(self) -> None:
        self.assertEqual(leaf_kind(MagicMock(type=QuestionType.CALCULATION)), "numeric")
        self.assertEqual(leaf_kind(MagicMock(type=QuestionType.LEVELS_BASED)), "extended")
        self.assertEqual(leaf_kind(MagicMock(type=QuestionType.TICKBOX)), "mcq")
        self.assertEqual(leaf_kind(MagicMock(type=QuestionType.RECALL)), "short")


class EffortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)

    def _effort(self, table: dict[str, str], *, kind: str | None) -> str | None:
        settings = _settings(self.tmp)
        settings = settings.model_copy(
            update={"gemini": settings.gemini.model_copy(update={"claude_effort_for": table})}
        )
        fake = _FakeAnthropic(_message(_VALID_MARK))
        client = GeminiClient(settings, _genai_client=object(), _anthropic_client=fake, ledger=None)
        client.generate_structured(
            system_prompt="s",
            user_prompt=f"u{kind}",
            response_schema=AIMarkResponse,
            prompt_version="v1",
            model=_HAIKU,
            task_tag="correction",
            leaf_kind=kind,
        )
        return fake.messages.calls[0]["output_config"].get("effort")

    def test_lookup_order(self) -> None:
        table = {"correction:extended": "xhigh", "correction": "medium"}
        self.assertEqual(self._effort(table, kind="extended"), "xhigh")
        self.assertEqual(self._effort(table, kind="numeric"), "medium")
        self.assertEqual(self._effort({}, kind="extended"), "low")
        self.assertEqual(self._effort({"correction": "max"}, kind=None), "max")

    def test_effort_is_in_the_cache_key(self) -> None:
        settings = _settings(self.tmp)
        settings = settings.model_copy(
            update={"gemini": settings.gemini.model_copy(update={"claude_effort_for": {"correction:extended": "high"}})}
        )
        client = GeminiClient(settings, _genai_client=object(), _anthropic_client=_FakeAnthropic(), ledger=None)
        args: dict[str, Any] = {
            "system_prompt": "s",
            "user_prompt": "u",
            "response_schema": AIMarkResponse,
            "prompt_version": "v1",
            "model": _HAIKU,
            "task_tag": "correction",
        }
        self.assertNotEqual(
            client.structured_cache_key(leaf_kind="extended", **args),
            client.structured_cache_key(leaf_kind="numeric", **args),
        )
        self.assertEqual(
            client.structured_cache_key(leaf_kind="numeric", **args),
            client.structured_cache_key(**args),
        )

    def test_gemini_ignores_leaf_kind(self) -> None:
        settings = make_settings(self.tmp)
        settings = settings.model_copy(
            update={"gemini": settings.gemini.model_copy(update={"claude_effort_for": {"correction": "max"}})}
        )
        client = GeminiClient(settings, _genai_client=fake_genai_client(), ledger=None)
        args: dict[str, Any] = {
            "system_prompt": "s",
            "user_prompt": "u",
            "response_schema": AIMarkResponse,
            "prompt_version": "v1",
            "model": "gemini-3.8-flash",
            "task_tag": "correction",
        }
        self.assertEqual(
            client.structured_cache_key(leaf_kind="extended", **args),
            client.structured_cache_key(**args),
        )


class CorrectorPassesKindTests(unittest.TestCase):
    def _kwargs(self, table: dict[str, str]) -> dict[str, Any]:
        from lemely.io.correction_ai import AICorrector

        settings = make_settings(tempfile.mkdtemp())
        settings = settings.model_copy(
            update={"gemini": settings.gemini.model_copy(update={"claude_effort_for": table})}
        )
        client = GeminiClient(settings, _genai_client=fake_genai_client(), ledger=None)
        question = MagicMock(type=QuestionType.EXPLANATION, id="2", marks=2)
        reply = AIMarkResponse.model_validate(_VALID_MARK)
        with (
            patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
            patch.object(client, "generate_structured", return_value=reply) as call,
        ):
            AICorrector(client).mark_question(question, "answer")
        return call.call_args_list[0].kwargs

    def test_kind_sent_only_when_the_table_is_set(self) -> None:
        self.assertNotIn("leaf_kind", self._kwargs({}))
        self.assertEqual(self._kwargs({"correction": "high"})["leaf_kind"], "extended")
```

- [ ] **Step 2: Run them to see them fail.** Run `python -m pytest tests/test_claude_effort.py -q --no-cov -o addopts=""`. Expected: `ModuleNotFoundError: No module named 'lemely.core.leaf_kind'`.

- [ ] **Step 3: `lemely/core/leaf_kind.py`.**

```python
"""A leaf's kind, from its mark-scheme question type (spec 2026-10-19 §4 B3)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from lemely.core.loose_schemas import QuestionType

if TYPE_CHECKING:
    from lemely.core.loose_schemas import Question

LeafKind = Literal["mcq", "numeric", "short", "extended"]

_KIND: dict[QuestionType, LeafKind] = {
    QuestionType.MCQ: "mcq",
    QuestionType.TICKBOX: "mcq",
    QuestionType.CALCULATION: "numeric",
    QuestionType.EQUATION: "numeric",
    QuestionType.GRAPH_READ: "numeric",
    QuestionType.EXPLANATION: "extended",
    QuestionType.COMPARISON: "extended",
    QuestionType.MULTI_STEP: "extended",
    QuestionType.LEVELS_BASED: "extended",
    QuestionType.INDICATIVE_CONTENT: "extended",
    QuestionType.FIELDWORK: "extended",
    QuestionType.RECALL: "short",
    QuestionType.LIST: "short",
    QuestionType.TABLE: "short",
    QuestionType.DIAGRAM: "short",
    QuestionType.GRAPH_DRAW: "short",
}


def leaf_kind(question: Question) -> LeafKind:
    """``mcq``, ``numeric``, ``short`` or ``extended``; a type with no entry is ``short``."""
    return _KIND.get(question.type, "short")
```

- [ ] **Step 4: Settings.** In `config.py`, next to `ClaudeCacheSpot`:

```python
ClaudeEffort = Literal["low", "medium", "high", "xhigh", "max"]
```

  and in `GeminiSettings` after `claude_cache_for`:

```python
    # Spec §4 B3: Anthropic effort per task tag, or per "tag:kind" (kind: mcq,
    # numeric, short, extended, from the leaf's question type). Lookup: tag:kind,
    # then tag, then thinking_level_for[tag] mapped to effort. Claude calls only.
    claude_effort_for: dict[str, ClaudeEffort] = Field(default_factory=dict)
```

  In `example_toml.py` after `claude_cache_for`:

```python
    lines.append("# Claude effort (low | medium | high | xhigh | max) per tag or tag:kind,")
    lines.append('# e.g. { "correction:extended" = "medium" }. Unlisted: thinking_level_for.')
    lines.append(f"# claude_effort_for = {_toml_inline(s.gemini.claude_effort_for)}")
```

  then `python -m lemely.runtime.example_toml`.

- [ ] **Step 5: The client and the adapter.** In `lemely/io/gemini.py` add next to `_call_labels`:

```python
#: The leaf kind of the structured call in progress (B3 effort lookup); None outside one.
_call_leaf_kind: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "lemely_call_leaf_kind", default=None
)
```

  Rename today's `generate_structured` to `_generate_structured` (same parameters, same body) and add the public method in front of it, with the old docstring plus one paragraph:

```python
    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        file_paths: list[Path] | None = None,
        documents: Sequence[DocumentInput] | None = None,
        image_parts: list[bytes] | None = None,
        media_resolution: str | None = None,
        image_uploads: ImageUploads | None = None,
        response_schema: type[_T],
        prompt_version: str,
        model: str | None = None,
        extra_cache_key: str = "",
        task_tag: str | None = None,
        cache_mode: Literal["read_write", "bypass", "refresh"] | None = None,
        attempt: _Attempt | None = None,
        question_id: str | None = None,
        shared_prefix: SharedPrefix | None = None,
        leaf_kind: str | None = None,
    ) -> _T:
        """I1: send per-page images instead of uploading a whole file.

        (Move the rest of today's ``generate_structured`` docstring here verbatim,
        from its second paragraph on; ``_generate_structured`` gets a one-line
        docstring, "The body of :meth:`generate_structured`.")

        ``leaf_kind`` (B3) picks a ``claude_effort_for["tag:kind"]`` effort on a
        claude- model; Gemini ignores it. It reaches the cache key only through
        the effort it selects.
        """
        token = _call_leaf_kind.set(leaf_kind)
        try:
            return self._generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                file_paths=file_paths,
                documents=documents,
                image_parts=image_parts,
                media_resolution=media_resolution,
                image_uploads=image_uploads,
                response_schema=response_schema,
                prompt_version=prompt_version,
                model=model,
                extra_cache_key=extra_cache_key,
                task_tag=task_tag,
                cache_mode=cache_mode,
                attempt=attempt,
                question_id=question_id,
                shared_prefix=shared_prefix,
            )
        finally:
            _call_leaf_kind.reset(token)
```

  Give `structured_cache_key` the same `leaf_kind: str | None = None` parameter, setting and resetting `_call_leaf_kind` around its body the same way. In `_resolved_gen_params`, replace the Claude branch's `"thinking_level": effort_for(...)` with:

```python
            table = g.claude_effort_for if isinstance(g.claude_effort_for, dict) else {}
            kind = _call_leaf_kind.get()
            effort = (
                (table.get(f"{key}:{kind}") if kind else None)
                or table.get(key)
                or effort_for(g.thinking_level_for.get(key, "low"))
            )
            return {
                "thinking_budget": None,
                "temperature": None,
                "top_p": None,
                "seed": None,
                "thinking_level": effort,
            }
```

  In `anthropic_adapter.py`:

```python
EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
Effort = Literal["low", "medium", "high", "xhigh", "max"]
```

  (replacing the old three-value `Effort`), and in `complete` and `complete_code_execution` replace `effort_for(thinking)` with `_as_effort(thinking)`:

```python
def _as_effort(value: str) -> Effort:
    """An effort passes as it is; a Lemely thinking level maps through effort_for."""
    return cast("Effort", value) if value in EFFORTS else effort_for(value)
```

- [ ] **Step 6: The corrector.** In `lemely/io/correction_ai.py`: add `leaf_kind: str` to `_PrefixKwargs` and change its docstring to "``generate_structured``'s ``shared_prefix`` and ``leaf_kind`` arguments, each present only when set."; import `from lemely.core.leaf_kind import leaf_kind`; in `mark_question`, right after `prefix_kwargs` is built, add:

```python
        # B3: the leaf's kind picks a claude_effort_for["tag:kind"] effort. Sent only
        # when that table is set, so a call without it passes exactly what it did.
        table = getattr(g, "claude_effort_for", None)
        if isinstance(table, dict) and table:
            prefix_kwargs["leaf_kind"] = leaf_kind(question)
```

  All five `generate_structured` calls already pass `**prefix_kwargs`, so every pass of the leaf (first, borderline, escalation, cascade second pass, cascade strong) carries the kind.

- [ ] **Step 7: Run the tests.** Run `python -m pytest tests/test_claude_effort.py tests/test_correction_ai.py tests/test_correction_cascade.py tests/test_correction_shared_prefix.py tests/test_anthropic_adapter.py tests/test_llm_golden.py tests/test_settings_example_drift.py -q --no-cov -o addopts=""`, plus the MagicMock-settings files that reach `mark_question`: `grep -l "MagicMock" tests/test_*.py | xargs grep -l "mark_question\|correct_paper" | tr '\n' ' '`. Expected: all pass (a `MagicMock` `gemini` returns a `MagicMock` for `claude_effort_for`, which is not a dict, so no kind is sent).

- [ ] **Step 8: Prove the guards go red.** (a) In `_resolved_gen_params` swap the first two lookups (tag before `tag:kind`); `test_lookup_order` must fail. Revert. (b) Drop the `isinstance(table, dict) and` guard in `mark_question`; at least one MagicMock-settings test from step 7 must fail (if none does, say so in the report: the guard is then belt-and-braces). Revert.

- [ ] **Step 9: Commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git add -- lemely/core/leaf_kind.py tests/test_claude_effort.py
git commit -S -m "feat(anthropic): Claude effort per task tag and per leaf kind" -- lemely/core/leaf_kind.py lemely/io/gemini.py lemely/io/providers/anthropic_adapter.py lemely/io/correction_ai.py lemely/runtime/config.py lemely/runtime/example_toml.py lemely.toml.example tests/test_claude_effort.py
```

---

### Task 8a: B2 evidence quotes and the `uncited_mark` flag (spec T8, part 1; §4 B2)

The spec's first choice, native citations, is ruled out by the docs: "Citations cannot be used together with structured outputs ... the API returns a 400 error" (citations docs, read 2026-10-19; Task 4 already refuses the combination before sending). This task builds the spec's fallback: an `evidence_quotes` field in the correction schema, checked by a deterministic substring check. It has no API dependency and works on both providers.

**Files:**
- Create: `lemely/core/cited_marks.py`
- Modify: `lemely/core/schemas.py` (`AIMarkResponseCited`, `marker_response_schema`)
- Modify: `lemely/io/correction_ai.py` (`AICorrector._mark_schema`, `AICorrector.citations_on`; the five `response_schema=AIMarkResponse` become `response_schema=self._mark_schema()`; the check after `_build_ai_corrected` in `correct_paper`)
- Modify: `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example` (`correction_citations`)
- Test: `tests/test_cited_marks.py` (new)

**Interfaces:**
- Consumes: `AIMarkResponse`, `CorrectedQuestion`, `Question`.
- Produces:
  - `schemas.AIMarkResponseCited(AIMarkResponse)` with `evidence_quotes: list[str]`; `schemas.marker_response_schema(*, cited: bool) -> type[AIMarkResponse]` (Task 8b adds `terse`).
  - `cited_marks.UNCITED_MARK = "uncited_mark"`, `scheme_text(question: Question) -> str`, `uncited(question: Question, mark: AIMarkResponse) -> bool`, `flag_uncited(cq: CorrectedQuestion) -> CorrectedQuestion`.
  - Rule: a mark with `awarded_marks > 0` is uncited when it has fewer valid quotes than `max(1, len(set(matched_point_ids)))`, or any quote is invalid. A quote is valid when, case-folded and whitespace-collapsed, it is at least 3 characters and a substring of the question's mark-scheme text (every string value of the question as the marker is shown it). An uncited mark gets `needs_teacher_review=True` and `review_reason` `"uncited_mark"` (appended after ` | ` to an existing reason).
  - `GeminiSettings.correction_citations: bool = False`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_cited_marks.py`:

```python
"""Spec 2026-10-19 §4 B2 (fallback): evidence quotes checked against the mark scheme."""

from __future__ import annotations

import json
import tempfile
import unittest

from lemely.core.cited_marks import UNCITED_MARK, flag_uncited, scheme_text, uncited
from lemely.core.schemas import AIMarkResponse, AIMarkResponseCited, marker_response_schema
from lemely.io.correction_ai import correct_paper
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from tests.gemini_fakes import mock_response
from tests.test_correction_ai import _client_with_seq, _hybrid_paper_mark_scheme


def _leaf():
    return next(q for q in _hybrid_paper_mark_scheme().all_questions_flat() if q.id == "2")


def _quote() -> str:
    return max(scheme_text(_leaf()).split("\n"), key=len)


def _mark(quotes: list[str], *, awarded: int = 1, matched: list[str] | None = None) -> AIMarkResponseCited:
    return AIMarkResponseCited(
        awarded_marks=awarded,
        confidence=0.95,
        matched_point_ids=matched or [],
        feedback="f",
        addresses_question="yes",
        evidence_quotes=quotes,
    )


class CheckTests(unittest.TestCase):
    def test_a_verbatim_quote_cites(self) -> None:
        self.assertFalse(uncited(_leaf(), _mark([_quote()])))

    def test_case_and_spacing_do_not_matter(self) -> None:
        self.assertFalse(uncited(_leaf(), _mark(["  " + _quote().upper().replace(" ", "   ") + " "])))

    def test_no_quote_is_uncited(self) -> None:
        self.assertTrue(uncited(_leaf(), _mark([])))

    def test_a_quote_not_in_the_scheme_is_uncited(self) -> None:
        self.assertTrue(uncited(_leaf(), _mark([_quote(), "the student wrote this"])))

    def test_one_quote_per_matched_point(self) -> None:
        self.assertTrue(uncited(_leaf(), _mark([_quote()], awarded=2, matched=["M1", "A1"])))
        self.assertFalse(uncited(_leaf(), _mark([_quote(), _quote()], awarded=2, matched=["M1", "A1"])))

    def test_zero_marks_need_no_quote(self) -> None:
        self.assertFalse(uncited(_leaf(), _mark([], awarded=0)))

    def test_a_plain_response_has_no_quotes(self) -> None:
        plain = AIMarkResponse(awarded_marks=1, confidence=0.9, feedback="f")
        self.assertTrue(uncited(_leaf(), plain))

    def test_flag_appends_to_an_existing_reason(self) -> None:
        from lemely.core.schemas import CorrectedQuestion

        cq = CorrectedQuestion.model_construct(needs_teacher_review=False, review_reason="low confidence")
        flagged = flag_uncited(cq)
        self.assertTrue(flagged.needs_teacher_review)
        self.assertEqual(flagged.review_reason, f"low confidence | {UNCITED_MARK}")
        self.assertEqual(flag_uncited(cq.model_copy(update={"review_reason": None})).review_reason, UNCITED_MARK)


class SchemaTests(unittest.TestCase):
    def test_schema_choice(self) -> None:
        self.assertIs(marker_response_schema(cited=False), AIMarkResponse)
        self.assertIs(marker_response_schema(cited=True), AIMarkResponseCited)
        schema = AIMarkResponseCited.model_json_schema()
        self.assertIn("evidence_quotes", schema["properties"])
        self.assertIn("addresses_question", schema["required"])


class PipelineTests(unittest.TestCase):
    def _run(self, quotes: list[str], *, on: bool) -> object:
        tmp = tempfile.mkdtemp()
        reply: dict[str, object] = {
            "awarded_marks": 1,
            "confidence": 0.97,
            "matched_point_ids": [],
            "feedback": "ok",
            "addresses_question": "yes",
        }
        if on:
            # With the flag off the schema has no such field (and forbids extras).
            reply["evidence_quotes"] = quotes
        client = _client_with_seq(tmp, [mock_response(json.dumps(reply))])
        client._settings = client._settings.model_copy(
            update={"gemini": client._settings.gemini.model_copy(update={"correction_citations": on})}
        )
        extracted = ExtractedAnswers(
            paper_id="t",
            source_scan="s.png",
            answers=[ExtractedAnswer(question_id="2", answer="an answer", confidence=0.99)],
        )
        result = correct_paper(
            mark_scheme=_hybrid_paper_mark_scheme(), extracted_answers=extracted, gemini_client=client
        )
        return next(q for q in result.questions if q.question_id == "2")

    def test_an_uncited_mark_goes_to_review(self) -> None:
        q2 = self._run(["not in the scheme"], on=True)
        self.assertTrue(q2.needs_teacher_review)
        self.assertIn(UNCITED_MARK, q2.review_reason or "")

    def test_a_cited_mark_is_not_flagged(self) -> None:
        q2 = self._run([_quote()], on=True)
        self.assertNotIn(UNCITED_MARK, q2.review_reason or "")

    def test_flag_off_checks_nothing(self) -> None:
        q2 = self._run([], on=False)
        self.assertNotIn(UNCITED_MARK, q2.review_reason or "")
```

  If `_hybrid_paper_mark_scheme()`'s leaf `"2"` has `marks` of 0 or its reply needs more fields to validate, read the helper at the top of `tests/test_correction_ai.py` and adjust `awarded_marks` and `matched_point_ids` in `reply` so that the reply is valid and awards one mark; do not change the assertions.

- [ ] **Step 2: Run them to see them fail.** Run `python -m pytest tests/test_cited_marks.py -q --no-cov -o addopts=""`. Expected: `ModuleNotFoundError: No module named 'lemely.core.cited_marks'`.

- [ ] **Step 3: Schemas.** In `lemely/core/schemas.py`, after `AIMarkResponse`:

```python
class AIMarkResponseCited(AIMarkResponse):
    """A mark with the mark-scheme words each awarded mark rests on (spec §4 B2).

    The fallback for citations, which the Messages API cannot combine with
    structured outputs. ``lemely.core.cited_marks`` checks each quote against the
    mark scheme the marker was shown.
    """

    evidence_quotes: list[str] = Field(
        default_factory=list,
        description=(
            "For every mark awarded, the exact words of the MARK SCHEME SUBTREE it was "
            "awarded against, copied character for character. One quote per matched "
            "point. Quote the mark scheme, never the student's answer."
        ),
    )


def marker_response_schema(*, cited: bool) -> type[AIMarkResponse]:
    """The correction reply schema for the flags in force."""
    return AIMarkResponseCited if cited else AIMarkResponse
```

- [ ] **Step 4: `lemely/core/cited_marks.py`.**

```python
"""Is every awarded mark backed by a quote from its mark scheme? (spec §4 B2 fallback)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lemely.core.loose_schemas import Question
    from lemely.core.schemas import AIMarkResponse, CorrectedQuestion

UNCITED_MARK = "uncited_mark"
_MIN_QUOTE_CHARS = 3


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def scheme_text(question: Question) -> str:
    """Every string in the question's mark-scheme subtree, one per line."""
    return "\n".join(_strings(question.model_dump(mode="json", exclude_none=True)))


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def uncited(question: Question, mark: AIMarkResponse) -> bool:
    """True when awarded marks lack valid quotes (see the module's rule in the plan)."""
    if mark.awarded_marks <= 0:
        return False
    quotes = [_norm(q) for q in getattr(mark, "evidence_quotes", None) or []]
    text = _norm(scheme_text(question))
    valid = [q for q in quotes if len(q) >= _MIN_QUOTE_CHARS and q in text]
    needed = max(1, len(set(mark.matched_point_ids)))
    return len(valid) < needed or len(valid) != len(quotes)


def flag_uncited(cq: CorrectedQuestion) -> CorrectedQuestion:
    """``cq`` sent to a teacher, with ``uncited_mark`` added to its reason."""
    reason = UNCITED_MARK if not cq.review_reason else f"{cq.review_reason} | {UNCITED_MARK}"
    return cq.model_copy(update={"needs_teacher_review": True, "review_reason": reason})
```

- [ ] **Step 5: Settings and the corrector.** In `GeminiSettings` after `claude_effort_for`:

```python
    # Spec §4 B2 (fallback; native citations cannot combine with structured output):
    # the marker quotes the mark-scheme words each awarded mark rests on, and a mark
    # without a valid quote goes to review as "uncited_mark". Both providers.
    correction_citations: bool = False
```

  In `example_toml.py` after the `claude_effort_for` line:

```python
    lines.append("# The marker quotes the mark scheme for every awarded mark; an unquoted or")
    lines.append("# misquoted mark goes to review as uncited_mark.")
    lines.append(f"# correction_citations = {_toml_bool(s.gemini.correction_citations)}")
```

  then `python -m lemely.runtime.example_toml`. In `lemely/io/correction_ai.py` add to `AICorrector`:

```python
    def citations_on(self) -> bool:
        """B2: whether marks carry evidence quotes (``correction_citations``)."""
        return self._client._settings.gemini.correction_citations is True

    def _mark_schema(self) -> type[AIMarkResponse]:
        """The reply schema for the flags in force; ``AIMarkResponse`` with them off."""
        return marker_response_schema(cited=self.citations_on())
```

  replace each of the five `response_schema=AIMarkResponse,` inside `AICorrector` with `response_schema=self._mark_schema(),`, and in `correct_paper`, directly after `cq = _build_ai_corrected(...)` (the call followed by `_maybe_apply_ecf_substitution`), add:

```python
        if ai.citations_on() and uncited(q, mark):
            cq = flag_uncited(cq)
```

  (imports: `from lemely.core.cited_marks import flag_uncited, uncited`, `marker_response_schema` from `lemely.core.schemas`). A leaf whose marks are re-made by the ECF substitution keeps the first mark's check; note that in the commit message as a known limit.

- [ ] **Step 6: Run the tests.** Run `python -m pytest tests/test_cited_marks.py tests/test_correction_ai.py tests/test_correction_cascade.py tests/test_correction_shared_prefix.py tests/test_marker_scored_one_formulation.py tests/test_llm_golden.py tests/test_settings_example_drift.py -q --no-cov -o addopts=""` plus the MagicMock-settings files reaching `mark_question` (the command in Task 7 step 7). Expected: all pass; with the flag off `self._mark_schema()` is `AIMarkResponse`, so prompts and cache keys are unchanged.

- [ ] **Step 7: Prove the guards go red.** (a) In `uncited`, drop `or len(valid) != len(quotes)`; `test_a_quote_not_in_the_scheme_is_uncited` must fail. Revert. (b) Remove the `correct_paper` check; `test_an_uncited_mark_goes_to_review` must fail. Revert.

- [ ] **Step 8: Commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git add -- lemely/core/cited_marks.py tests/test_cited_marks.py
git commit -S -m "feat(correction): evidence quotes per awarded mark; uncited marks go to review" -- lemely/core/cited_marks.py lemely/core/schemas.py lemely/io/correction_ai.py lemely/runtime/config.py lemely/runtime/example_toml.py lemely.toml.example tests/test_cited_marks.py
```

---

### Task 8b: Terse rationale (spec T8, part 2; §5.4)

**Files:**
- Modify: `lemely/core/schemas.py` (`AIMarkResponseTerse`, `AIMarkResponseCitedTerse`, `TERSE_FEEDBACK_MAX_CHARS`; `marker_response_schema` gains `terse`)
- Modify: `lemely/io/correction_ai.py` (`_mark_schema` passes `terse`)
- Modify: `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example` (`correction_terse_rationale`)
- Test: `tests/test_cited_marks.py` (append)

**Interfaces:**
- Consumes: Task 8a `marker_response_schema`, `AIMarkResponseCited`, `_mark_schema`.
- Produces: `marker_response_schema(*, cited: bool, terse: bool = False) -> type[AIMarkResponse]`; `TERSE_FEEDBACK_MAX_CHARS = 300`; `GeminiSettings.correction_terse_rationale: bool = False`. The cap is a schema description ("at most 25 words") plus a truncating validator: structured outputs drop `maxLength` (docs read 2026-10-19), and a validation failure would cost a schema-correction retry, so the reply is cut, not refused.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_cited_marks.py`:

```python
class TerseTests(unittest.TestCase):
    def test_schema_choice(self) -> None:
        from lemely.core.schemas import AIMarkResponseCitedTerse, AIMarkResponseTerse

        self.assertIs(marker_response_schema(cited=False, terse=True), AIMarkResponseTerse)
        self.assertIs(marker_response_schema(cited=True, terse=True), AIMarkResponseCitedTerse)
        self.assertIs(marker_response_schema(cited=True, terse=False), AIMarkResponseCited)

    def test_long_feedback_is_cut_not_refused(self) -> None:
        from lemely.core.schemas import TERSE_FEEDBACK_MAX_CHARS, AIMarkResponseTerse

        reply = AIMarkResponseTerse(awarded_marks=1, confidence=0.9, feedback="w " * 400)
        self.assertEqual(len(reply.feedback), TERSE_FEEDBACK_MAX_CHARS)

    def test_the_cap_is_asked_for_in_the_schema(self) -> None:
        from lemely.core.schemas import AIMarkResponseCitedTerse

        description = AIMarkResponseCitedTerse.model_json_schema()["properties"]["feedback"]["description"]
        self.assertIn("25 words", description)
        self.assertIn("evidence_quotes", AIMarkResponseCitedTerse.model_json_schema()["properties"])
```

- [ ] **Step 2: Run them to see them fail.** Run `python -m pytest tests/test_cited_marks.py -q --no-cov -o addopts=""`. Expected: `ImportError` on `AIMarkResponseTerse`.

- [ ] **Step 3: Implement.** In `lemely/core/schemas.py` (add `field_validator` to the pydantic import if missing):

```python
#: A terse rationale is cut to this many characters (never refused: a refusal
#: would cost a schema-correction retry).
TERSE_FEEDBACK_MAX_CHARS = 300
_TERSE_FEEDBACK_DESCRIPTION = (
    "At most 25 words: why the marks were or were not awarded. No restating the answer."
)


def _cut(value: str) -> str:
    return value[:TERSE_FEEDBACK_MAX_CHARS]


class AIMarkResponseTerse(AIMarkResponse):
    """Spec §5.4: a correction reply whose rationale is capped (output tokens)."""

    feedback: str = Field(..., description=_TERSE_FEEDBACK_DESCRIPTION)

    @field_validator("feedback")
    @classmethod
    def _cap_feedback(cls, value: str) -> str:
        return _cut(value)


class AIMarkResponseCitedTerse(AIMarkResponseCited):
    """Terse rationale with evidence quotes: the evidence lives in the quotes."""

    feedback: str = Field(..., description=_TERSE_FEEDBACK_DESCRIPTION)

    @field_validator("feedback")
    @classmethod
    def _cap_feedback(cls, value: str) -> str:
        return _cut(value)


def marker_response_schema(*, cited: bool, terse: bool = False) -> type[AIMarkResponse]:
    """The correction reply schema for the flags in force."""
    if cited:
        return AIMarkResponseCitedTerse if terse else AIMarkResponseCited
    return AIMarkResponseTerse if terse else AIMarkResponse
```

  (this replaces Task 8a's `marker_response_schema`). In `GeminiSettings` after `correction_citations`:

```python
    # Spec §5.4: the correction reply's rationale is asked for in at most 25 words
    # and cut at 300 characters (output tokens). Screened with and without
    # correction_citations in sub-project C.
    correction_terse_rationale: bool = False
```

  `example_toml.py` after `correction_citations`:

```python
    lines.append("# Ask the marker for a rationale of at most 25 words (cut at 300 chars).")
    lines.append(f"# correction_terse_rationale = {_toml_bool(s.gemini.correction_terse_rationale)}")
```

  then `python -m lemely.runtime.example_toml`. In `AICorrector._mark_schema`:

```python
        g = self._client._settings.gemini
        return marker_response_schema(
            cited=self.citations_on(), terse=g.correction_terse_rationale is True
        )
```

- [ ] **Step 4: Run the tests.** Run `python -m pytest tests/test_cited_marks.py tests/test_correction_ai.py tests/test_llm_golden.py tests/test_settings_example_drift.py -q --no-cov -o addopts=""`. Expected: all pass.

- [ ] **Step 5: Prove the guard goes red.** Remove the `_cap_feedback` validator from `AIMarkResponseTerse`; `test_long_feedback_is_cut_not_refused` must fail. Revert.

- [ ] **Step 6: Commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
pre-commit run --all-files
git commit -S -m "feat(correction): terse-rationale schema variant behind correction_terse_rationale" -- lemely/core/schemas.py lemely/io/correction_ai.py lemely/runtime/config.py lemely/runtime/example_toml.py lemely.toml.example tests/test_cited_marks.py
```

---

### Task 9: Blank-leaf skip (spec T9; §5.1): confirm, no code

The spec says T9 first confirms that no blank-skip path exists, and becomes a no-op if one does. One does: US-039. `correct_paper` (`lemely/io/correction_ai.py`, the `if _is_blank(student_answer) and _is_blank(student_working):` branch before `ai.mark_question`) gives a non-MCQ leaf with a blank answer and blank working an unflagged 0 with `marker_source="blank"` and makes no model call. It is stricter than the spec's sketch (it also requires blank working, so a blank answer box with visible working is still marked), and its `marker_source` already has a migration (`0040_marker_source_blank`). A second literal `"blank_skip"` would need a migration and would trip `tests/test_marker_scored_one_formulation.py`; it is not added.

**Files:** none.

**Interfaces:** none produced.

- [ ] **Step 1: Run the existing proof.** Run `python -m pytest tests/test_correction_ai.py -q --no-cov -o addopts="" -k "BlankAnswerShortCircuitTests"`. Expected: all pass, including `test_blank_non_mcq_answer_is_unflagged_zero_without_a_paid_call` (`_client_with_seq(self.tmp, [])`: any model call would raise `StopIteration`).

- [ ] **Step 2: Confirm the path is provider-neutral.** Read the branch named above and confirm it runs before any `GeminiClient` call and reads no provider setting. Expected: yes; a `claude-` correction model changes nothing about it.

- [ ] **Step 3: Report, no commit.** Report "T9: no-op, US-039 blank skip exists (marker_source='blank'), tests pass" to the controller, which records it in the Task 11 report.

---
### Task 10: Overview and chunked binder read (spec T10; §2b)

**Files:**
- Create: `lemely/io/binding/chunked_read.py`
- Modify: `lemely/io/prompts/label_binding.py` (`build_label_binding_user_prompt` gains `labels`; overview and chunk prompts)
- Modify: `lemely/io/binding/label_binder.py` (`LabelBinder(client, *, chunked=None)`; `read` dispatches)
- Modify: `lemely/io/binding/orchestrate.py` (`run_binding` builds the chunked reader when the flag is on)
- Modify: `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example` (`BindingSettings.claude_chunked_read`)
- Test: `tests/test_chunked_read.py` (new)

**Interfaces:**
- Consumes: Task 2a `fit`, `thumbnails`, `FittedImages.page_tokens`; Task 2b `claude_image_token_budget`, `claude_image_floor_px`; `label_binder._StreamOutput`, `parse_stream_items`, `StreamRead`; `SeenLabel`/`SeenWriting` (`page` field).
- Produces:
  - `BindingSettings.claude_chunked_read: bool = False`.
  - `chunked_read.OVERVIEW_TASK_TAG = "binding_overview"`; `PageEntry(page: int, labels: list[str] = [], continues_to_next: bool = False)`; `PageMap(pages: list[PageEntry])` with `labels_on(pages: Iterable[int]) -> list[str]` and `text() -> str`; `plan_chunks(page_tokens: Sequence[int], budget: int) -> list[range]`; `merge_chunk_reads(reads: Sequence[StreamRead]) -> StreamRead`; `ChunkedLabelReader(client: GeminiClient)` with `applies(pages: list[RasterisedPage], model: str | None) -> bool` and `read(pages, mark_scheme, *, model: str, extra_cache_key: str, task_tag: str) -> StreamRead`.
  - `label_binding.OVERVIEW_SYSTEM_PROMPT`, `OVERVIEW_VERSION = "overview-1"`, `CHUNK_VERSION = f"{VERSION}+chunk1"`, `build_overview_user_prompt(mark_scheme, *, page_count) -> str`, `build_chunk_user_prompt(mark_scheme, *, page_count: int, first_page: int, total_pages: int, overlap: bool, page_map: str, labels: Sequence[str]) -> str`; `build_label_binding_user_prompt(mark_scheme, *, page_count, labels: Collection[str] | None = None)` (None: byte-identical to today).
  - `LabelBinder(client, *, chunked: ChunkedLabelReader | None = None)`.
  - Log event `binding_chunked_read` with `chunked_read=True` and `role` in `overview`, `plan`, `chunk`, `merge`.

Decisions this task makes (recorded for the reviewer):
- The overlap page (the previous chunk's last page, sent again first) belongs to the earlier chunk: every item the later chunk lists on it is dropped at merge. Writing that continues onto the chunk's first new page has no label before it in that chunk, so in the concatenated stream it follows the previous label, which is where the map says it goes.
- A label seen in two chunks becomes a label seen twice in one stream; `label_sequence` already treats that as a doubt, so the gate holds or unverifies the leaf. (The spec says "G9 disagreement"; the effect, a leaf the gate will not pass silently, is the same; the check that fires differs.)
- Chunk and overview calls bypass the response cache (`cache_mode="bypass"`): a held paper is then never replayed from cached chunks, so `run_binding`'s forget-on-hold needs no new keys. The overview runs once per script per process (memo by page bytes, under a lock, so the two reads share it). Prompt caching still applies.
- The prompt's label list is restricted to the labels the map gives the chunk's pages (a scheme label matches a mapped one when equal, or when one is the other followed by "("); an empty match keeps the full list.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_chunked_read.py`:

```python
"""Spec 2026-10-19 §2b: overview plus chunks reproduces a one-pass read on a long script."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from PIL import Image

from lemely.core.loose_schemas import MarkScheme
from lemely.io.binding.chunked_read import (
    OVERVIEW_TASK_TAG,
    ChunkedLabelReader,
    PageEntry,
    PageMap,
    plan_chunks,
)
from lemely.io.binding.label_binder import LabelBinder, parse_stream_items
from lemely.io.gemini import GeminiClient
from lemely.io.rasterise import RasterisedPage
from tests.gemini_fakes import fake_genai_client, make_settings

_HAIKU = "claude-haiku-5-5"
_PAGES = 45
_ROOT = Path(__file__).resolve().parents[1]


def _scheme() -> MarkScheme:
    path = _ROOT / "corpus" / "mark-schemes" / "0625_w24_ms_41.json"
    return MarkScheme.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _pages() -> list[RasterisedPage]:
    out = []
    for i in range(_PAGES):
        buf = io.BytesIO()
        Image.new("L", (400, 600), i).save(buf, "PNG")
        out.append(RasterisedPage(index=i, width=400, height=600, png_bytes=buf.getvalue()))
    return out


def _truth() -> list[dict[str, Any]]:
    """One label and one answer per page, as a one-pass read would list them."""
    items: list[dict[str, Any]] = []
    for p in range(_PAGES):
        items.append({"type": "label", "page": p, "text": f"{p + 1}", "kind": "printed"})
        items.append({"type": "answer", "page": p, "answer": f"answer {p + 1}", "confidence": 0.9, "placed_by": "position"})
    return items


class _FakeModel:
    """Answers the overview with the true map and each chunk with the truth for its pages."""

    def __init__(self, pages: list[RasterisedPage]) -> None:
        self.index = {p.png_bytes: p.index for p in pages}
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        schema = kwargs["response_schema"]
        if kwargs["task_tag"] == OVERVIEW_TASK_TAG:
            return PageMap(pages=[PageEntry(page=p, labels=[f"{p + 1}"]) for p in range(_PAGES)])
        sent = [self.index[b] for b in kwargs["image_parts"]]
        local = [
            {**item, "page": sent.index(item["page"])} for item in _truth() if item["page"] in sent
        ]
        return schema.model_validate({"items": local})


def _client(budget: int = 5_000) -> GeminiClient:
    settings = make_settings(tempfile.mkdtemp())
    settings = settings.model_copy(
        update={
            "gemini": settings.gemini.model_copy(update={"claude_image_token_budget": budget}),
            "binding": settings.binding.model_copy(update={"claude_chunked_read": True}),
        }
    )
    return GeminiClient(settings, _genai_client=fake_genai_client(), ledger=None)


class PlanTests(unittest.TestCase):
    def test_chunks_fit_the_budget_with_the_overlap_page(self) -> None:
        self.assertEqual(
            plan_chunks([320] * 45, 5_000),
            [range(0, 15), range(15, 29), range(29, 43), range(43, 45)],
        )

    def test_a_page_over_the_budget_is_a_chunk_of_its_own(self) -> None:
        self.assertEqual(plan_chunks([10, 9_000, 10], 5_000), [range(0, 1), range(1, 2), range(2, 3)])

    def test_page_map_text_and_labels(self) -> None:
        page_map = PageMap(
            pages=[PageEntry(page=0, labels=["1(a)"], continues_to_next=True), PageEntry(page=1, labels=["1(b)"])]
        )
        self.assertEqual(page_map.labels_on(range(1, 2)), ["1(b)"])
        self.assertIn("page 1: 1(a); writing continues onto the next page", page_map.text())


class ReadTests(unittest.TestCase):
    def _read(self, reader: ChunkedLabelReader, pages: list[RasterisedPage], model: _FakeModel, tag: str) -> Any:
        from unittest.mock import patch

        with patch.object(reader._client, "generate_structured", side_effect=model):
            return reader.read(pages, _scheme(), model=_HAIKU, extra_cache_key="k|bind1", task_tag=tag)

    def test_the_merge_reproduces_the_one_pass_read(self) -> None:
        pages = _pages()
        reader = ChunkedLabelReader(_client())
        self.assertTrue(reader.applies(pages, _HAIKU))
        merged = self._read(reader, pages, _FakeModel(pages), "extraction")
        expected = parse_stream_items(_truth(), page_count=_PAGES).items
        self.assertEqual(merged.items, expected)

    def test_overview_runs_once_for_both_reads_and_chunks_bypass_the_cache(self) -> None:
        pages = _pages()
        reader = ChunkedLabelReader(_client())
        model = _FakeModel(pages)
        self._read(reader, pages, model, "extraction")
        self._read(reader, pages, model, "binding_second_read")
        tags = [c["task_tag"] for c in model.calls]
        self.assertEqual(tags.count(OVERVIEW_TASK_TAG), 1)
        self.assertEqual(tags.count("extraction"), 4)
        self.assertEqual(tags.count("binding_second_read"), 4)
        self.assertTrue(all(c["cache_mode"] == "bypass" for c in model.calls))

    def test_chunks_are_told_the_map_and_their_place(self) -> None:
        pages = _pages()
        reader = ChunkedLabelReader(_client())
        model = _FakeModel(pages)
        self._read(reader, pages, model, "extraction")
        second = next(c for c in model.calls if "pages 15 to 29" in c["user_prompt"])
        self.assertIn("page 16: 16", second["user_prompt"])
        self.assertIn("Image 0 is the last page of the previous part", second["user_prompt"])

    def test_not_applied_under_the_budget_or_off_claude(self) -> None:
        pages = _pages()
        self.assertFalse(ChunkedLabelReader(_client(budget=95_000)).applies(pages, _HAIKU))
        self.assertFalse(ChunkedLabelReader(_client()).applies(pages, "gemini-3.8-flash"))


class BinderDispatchTests(unittest.TestCase):
    def test_label_binder_uses_the_chunked_read_when_it_applies(self) -> None:
        from unittest.mock import patch

        pages = _pages()
        client = _client()
        model = _FakeModel(pages)
        binder = LabelBinder(client, chunked=ChunkedLabelReader(client))
        with patch.object(client, "generate_structured", side_effect=model):
            read = binder.read(pages, _scheme(), uploads=None, model=_HAIKU, extra_cache_key="k|bind1")  # type: ignore[arg-type]
        self.assertEqual(len(read.items), 2 * _PAGES)
        self.assertIn(OVERVIEW_TASK_TAG, [c["task_tag"] for c in model.calls])
```

- [ ] **Step 2: Run them to see them fail.** Run `python -m pytest tests/test_chunked_read.py -q --no-cov -o addopts=""`. Expected: `ModuleNotFoundError: No module named 'lemely.io.binding.chunked_read'`.

- [ ] **Step 3: Prompts.** In `lemely/io/prompts/label_binding.py`: give `build_label_binding_user_prompt` a keyword `labels: Collection[str] | None = None` and build the list from

```python
    printed = _printed_labels(mark_scheme)
    if labels:
        wanted = [
            (label, marks)
            for label, marks in printed
            if any(label == m or label.startswith(m + "(") or m.startswith(label + "(") for m in labels)
        ]
        printed = wanted or printed
    label_list = "\n".join(
        f"- {label} [{marks} mark{'s' if marks != 1 else ''}]" for label, marks in printed
    )
```

  (with `labels=None` this is today's list, so the prompt and every key are unchanged; `from collections.abc import Collection, Sequence`). Then append:

```python
OVERVIEW_VERSION = "overview-1"
CHUNK_VERSION = f"{VERSION}+chunk1"

OVERVIEW_SYSTEM_PROMPT = """You map a scanned exam script page by page.

For every attached page image, list the question labels you can see on it (printed or
handwritten, as written, for example "3(b)(ii)"), in reading order, and say whether
the student's writing at the bottom of the page carries on onto the next page. Do not
transcribe any answer. Return one entry per page, for every page, in order."""


def build_overview_user_prompt(mark_scheme: MarkScheme, *, page_count: int) -> str:
    """The overview pass's request: the page indices and the labels to look for."""
    labels = "\n".join(f"- {label}" for label, _marks in _printed_labels(mark_scheme))
    return (
        f"You are given {page_count} page thumbnails, indexed 0 to {page_count - 1}.\n\n"
        f"The printed paper's labels, for orientation only:\n{labels}\n\n"
        'Return JSON: {"pages": [{"page": 0, "labels": ["1(a)"], "continues_to_next": '
        "false}, ...]} with exactly one entry per page."
    )


def build_chunk_user_prompt(
    mark_scheme: MarkScheme,
    *,
    page_count: int,
    first_page: int,
    total_pages: int,
    overlap: bool,
    page_map: str,
    labels: Sequence[str],
) -> str:
    """One chunk's binder request: the normal request, its labels, its place, the map."""
    base = build_label_binding_user_prompt(mark_scheme, page_count=page_count, labels=labels)
    place = (
        f"This is part of a longer script of {total_pages} pages. The attached images are "
        f"pages {first_page + 1} to {first_page + page_count} of it, indexed 0 to "
        f"{page_count - 1} here."
    )
    if overlap:
        place += (
            " Image 0 is the last page of the previous part, sent again only so that writing "
            "carrying on from it makes sense: list nothing that is on image 0."
        )
    return f"{base}\n\n{place}\n\nPage map of the whole script, from an overview read:\n{page_map}"
```

- [ ] **Step 4: `lemely/io/binding/chunked_read.py`.**

```python
"""Overview-and-chunks binder read for a script over the token budget at the floor.

Spec 2026-10-19 §2b, behind ``binding.claude_chunked_read`` (off by default). An
overview pass on 768 px thumbnails maps the labels page by page; contiguous chunks
under the budget are then read in parallel at full fitted resolution, each with the
map and the previous chunk's last page as overlap; the merge concatenates them in
page order. Every call is priced on its own and stays under the price tier.
"""

from __future__ import annotations

import contextvars
import hashlib
import threading
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, ConfigDict, Field

from lemely.io.binding.label_binder import StreamRead, _StreamOutput, parse_stream_items
from lemely.io.llm.image_fit import FittedImages, fit, thumbnails
from lemely.io.prompts.label_binding import (
    CHUNK_VERSION,
    LABEL_BINDING_SYSTEM_PROMPT,
    OVERVIEW_SYSTEM_PROMPT,
    OVERVIEW_VERSION,
    build_chunk_user_prompt,
    build_overview_user_prompt,
)
from lemely.io.providers import is_anthropic_model

if TYPE_CHECKING:
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.gemini import GeminiClient
    from lemely.io.rasterise import RasterisedPage

OVERVIEW_TASK_TAG = "binding_overview"


class PageEntry(BaseModel):
    """One page of the overview: its labels and whether its writing carries on."""

    model_config = ConfigDict(extra="ignore")
    page: int
    labels: list[str] = Field(default_factory=list)
    continues_to_next: bool = False


class PageMap(BaseModel):
    """The overview's map of the whole script, 0-based page indices."""

    model_config = ConfigDict(extra="ignore")
    pages: list[PageEntry]

    def labels_on(self, pages: Iterable[int]) -> list[str]:
        """The labels the map puts on ``pages``, in page order."""
        wanted = set(pages)
        return [label for entry in self.pages if entry.page in wanted for label in entry.labels]

    def text(self) -> str:
        """The map as lines of 1-based pages, for a chunk's prompt."""
        lines = []
        for entry in sorted(self.pages, key=lambda e: e.page):
            line = f"page {entry.page + 1}: {', '.join(entry.labels) or 'no label'}"
            if entry.continues_to_next:
                line += "; writing continues onto the next page"
            lines.append(line)
        return "\n".join(lines)


def plan_chunks(page_tokens: Sequence[int], budget: int) -> list[range]:
    """Contiguous page ranges each under ``budget`` with the overlap page counted.

    A page over the budget on its own is a chunk of its own.
    """
    chunks: list[range] = []
    start = 0
    while start < len(page_tokens):
        used = page_tokens[start - 1] if start > 0 else 0
        end = start
        while end < len(page_tokens) and (end == start or used + page_tokens[end] <= budget):
            used += page_tokens[end]
            end += 1
        chunks.append(range(start, end))
        start = end
    return chunks


def merge_chunk_reads(reads: Sequence[StreamRead]) -> StreamRead:
    """The chunks' items in chunk order (already on whole-script pages); drops summed."""
    drops: dict[str, int] = {}
    for read in reads:
        for reason, count in read.drops.items():
            drops[reason] = drops.get(reason, 0) + count
    return StreamRead(items=[item for read in reads for item in read.items], drops=drops)


class ChunkedLabelReader:
    """Reads a long script as an overview plus chunks; shared by both binder reads."""

    def __init__(self, client: GeminiClient) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._maps: dict[str, PageMap] = {}
        self._fits: dict[str, FittedImages] = {}
        self._log = structlog.get_logger().bind(component="label_binder", chunked_read=True)

    @staticmethod
    def _digest(pages: list[RasterisedPage]) -> str:
        h = hashlib.sha256()
        for page in pages:
            h.update(len(page.png_bytes).to_bytes(8, "big"))
            h.update(page.png_bytes)
        return h.hexdigest()

    def _fit(self, pages: list[RasterisedPage]) -> FittedImages:
        key = self._digest(pages)
        with self._lock:
            fitted = self._fits.get(key)
        if fitted is None:
            g = self._client._settings.gemini
            fitted = fit(
                [p.png_bytes for p in pages],
                byte_limit=None,
                token_budget=g.claude_image_token_budget,
                floor_px=g.claude_image_floor_px,
            )
            with self._lock:
                self._fits[key] = fitted
        return fitted

    def applies(self, pages: list[RasterisedPage], model: str | None) -> bool:
        """A claude- read whose pages are still over the token budget at the floor."""
        return model is not None and is_anthropic_model(model) and self._fit(pages).over_token_budget

    def _page_map(self, pages: list[RasterisedPage], mark_scheme: MarkScheme, *, model: str) -> PageMap:
        key = self._digest(pages)
        # Held across the call on purpose: the two reads start together and must share one overview.
        with self._lock:
            page_map = self._maps.get(key)
            if page_map is None:
                page_map = self._client.generate_structured(
                    system_prompt=OVERVIEW_SYSTEM_PROMPT,
                    user_prompt=build_overview_user_prompt(mark_scheme, page_count=len(pages)),
                    image_parts=list(thumbnails([p.png_bytes for p in pages])),
                    response_schema=PageMap,
                    prompt_version=OVERVIEW_VERSION,
                    model=model,
                    task_tag=OVERVIEW_TASK_TAG,
                    cache_mode="bypass",
                )
                self._maps[key] = page_map
                self._log.info("binding_chunked_read", role="overview", pages=len(pages))
        return page_map

    def _read_chunk(
        self,
        pages: list[RasterisedPage],
        mark_scheme: MarkScheme,
        page_map: PageMap,
        chunk: range,
        number: int,
        *,
        model: str,
        extra_cache_key: str,
        task_tag: str,
    ) -> StreamRead:
        overlap = chunk.start > 0
        first = chunk.start - 1 if overlap else chunk.start
        sent = pages[first : chunk.stop]
        raw = self._client.generate_structured(
            system_prompt=LABEL_BINDING_SYSTEM_PROMPT,
            user_prompt=build_chunk_user_prompt(
                mark_scheme,
                page_count=len(sent),
                first_page=first,
                total_pages=len(pages),
                overlap=overlap,
                page_map=page_map.text(),
                labels=page_map.labels_on(chunk),
            ),
            image_parts=[p.png_bytes for p in sent],
            media_resolution="high",
            response_schema=_StreamOutput,
            prompt_version=CHUNK_VERSION,
            model=model,
            extra_cache_key=f"{extra_cache_key}|chunk{number}",
            task_tag=task_tag,
            cache_mode="bypass",
        )
        local = parse_stream_items(raw.model_dump()["items"], page_count=len(sent))
        skip = 1 if overlap else 0
        items = [
            item.model_copy(update={"page": first + item.page})
            for item in local.items
            if item.page >= skip
        ]
        self._log.info(
            "binding_chunked_read",
            role="chunk",
            chunk=number,
            first_page=chunk.start + 1,
            last_page=chunk.stop,
            items=len(items),
            task=task_tag,
        )
        return StreamRead(items=items, drops=dict(local.drops))

    def read(
        self,
        pages: list[RasterisedPage],
        mark_scheme: MarkScheme,
        *,
        model: str,
        extra_cache_key: str,
        task_tag: str,
    ) -> StreamRead:
        """The overview (once per script), the chunks in parallel, then the merge."""
        fitted = self._fit(pages)
        page_map = self._page_map(pages, mark_scheme, model=model)
        chunks = plan_chunks(fitted.page_tokens, self._client._settings.gemini.claude_image_token_budget)
        self._log.info("binding_chunked_read", role="plan", pages=len(pages), chunks=len(chunks), task=task_tag)
        with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
            futures = [
                pool.submit(
                    contextvars.copy_context().run,
                    self._read_chunk,
                    pages,
                    mark_scheme,
                    page_map,
                    chunk,
                    number,
                    model=model,
                    extra_cache_key=extra_cache_key,
                    task_tag=task_tag,
                )
                for number, chunk in enumerate(chunks, start=1)
            ]
            reads = [future.result() for future in futures]
        merged = merge_chunk_reads(reads)
        self._log.info("binding_chunked_read", role="merge", items=len(merged.items), task=task_tag)
        return merged
```

  `SeenLabel` and `SeenWriting` are pydantic models with a `page` field, so `model_copy(update={"page": ...})` keeps every other field.

- [ ] **Step 5: Wire it.** In `lemely/io/binding/label_binder.py`, `LabelBinder.__init__(self, client: GeminiClient, *, chunked: ChunkedLabelReader | None = None)` stores `self._chunked = chunked` (import `ChunkedLabelReader` under `TYPE_CHECKING` only), and `read` begins:

```python
        if self._chunked is not None and self._chunked.applies(pages, model):
            return self._chunked.read(
                pages, mark_scheme, model=cast(str, model), extra_cache_key=extra_cache_key, task_tag=task_tag
            )
```

  In `orchestrate.run_binding` replace `binder = LabelBinder(client)` with:

```python
    chunked = ChunkedLabelReader(client) if binding.claude_chunked_read is True else None
    binder = LabelBinder(client, chunked=chunked)
```

  (`from lemely.io.binding.chunked_read import ChunkedLabelReader`). In `BindingSettings` after `second_read_model`:

```python
    #: Spec §2b: a claude- read whose pages are still over the token budget at the
    #: floor is read as an overview plus chunks. Off by default; screened in C.
    claude_chunked_read: bool = False
```

  and in `example_toml.py`, after the `second_read_model` comment line:

```python
    lines.append("# A claude- read still over the token budget at the image floor is read as")
    lines.append("# an overview pass plus page chunks under the budget (off until screened).")
    lines.append(f"# claude_chunked_read = {_toml_bool(s.binding.claude_chunked_read)}")
```

  then `python -m lemely.runtime.example_toml`.

- [ ] **Step 6: Run the tests.** Run `python -m pytest tests/test_chunked_read.py tests/test_extraction_binding.py tests/test_claude_cache_plan.py tests/test_image_fit.py tests/test_settings_example_drift.py tests/test_llm_golden.py -q --no-cov -o addopts=""`. Expected: all pass (with the flag off nothing about binding changes).

- [ ] **Step 7: Prove the guards go red.** (a) In `_read_chunk` keep the overlap page's items (`skip = 0`); `test_the_merge_reproduces_the_one_pass_read` must fail (pages 15, 29, 43 listed twice). Revert. (b) Remove the `with self._lock:` around the overview (keep the body); run `test_overview_runs_once_for_both_reads_and_chunks_bypass_the_cache` 5 times; it may still pass (sequential reads in the test). If it does, note in the report that the lock is covered only by review; do not add a timing-dependent test.

- [ ] **Step 8: Commit.**

```bash
python -m pytest tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""
lint-imports
pre-commit run --all-files
git add -- lemely/io/binding/chunked_read.py tests/test_chunked_read.py
git commit -S -m "feat(binding): overview plus chunked binder read for long scripts over the Claude tier" -- lemely/io/binding/chunked_read.py lemely/io/binding/label_binder.py lemely/io/binding/orchestrate.py lemely/io/prompts/label_binding.py lemely/runtime/config.py lemely/runtime/example_toml.py lemely.toml.example tests/test_chunked_read.py
```

---

### Final gate sweep (after Task 10, before Task 11)

Run by the controller on the final commit, in a clean tree. A sweep certifies only the tree it ran on: any later fix commit voids it.

- [ ] **Step 1:** `git status --short -- lemely tests` is empty; `git log --oneline 6b9ac91c..HEAD` lists the tasks' commits.
- [ ] **Step 2:** Read `.github/workflows/ci.yml` and run every Python job's commands that do not need services, as written there: `ruff check .`, `ruff format --check .`, `mypy lemely`, `pyright lemely`, `lint-imports`, `pre-commit run --all-files --show-diff-on-failure`, and `python scripts/check_review_rate_gate.py` if the workflow runs it without a database.
- [ ] **Step 3:** Run every test file this plan created or touched plus the source-scanning tests:
  `python -m pytest tests/test_llm_golden.py tests/test_llm_request.py tests/test_llm_providers.py tests/test_image_fit.py tests/test_claude_images.py tests/test_claude_uploads.py tests/test_llm_pricing.py tests/test_model_table.py tests/test_cli_doctor.py tests/test_script_cost_scope.py tests/test_claude_documents.py tests/test_claude_code_execution.py tests/test_claude_cache_plan.py tests/test_claude_effort.py tests/test_cited_marks.py tests/test_chunked_read.py tests/test_anthropic_adapter.py tests/test_gemini_client.py tests/test_gemini_cost_record.py tests/test_correction_ai.py tests/test_extraction_binding.py tests/test_parsers.py tests/test_scan_metadata.py tests/test_settings_example_drift.py tests/architecture $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) -q --no-cov -o addopts=""`.
- [ ] **Step 4:** `git diff --stat 6b9ac91c -- tests/fixtures/llm_golden` shows only Task 0's addition (the golden was never regenerated). Report the results and say that CI's full run is the only judge of green.

---

### Task 11: Live E2E on the real script (spec T11): main session only

Not a subagent task. The main session runs it from a worktree pinned at the final SHA, after the gate sweep. Nothing in this task is committed except, optionally, `COST.md` (see step 6).

**Inputs:** scan `/home/sico/Documents/P4 N24 V1_annotated (NO Corrections).pdf` (19 pages, the script of the `01f371c3` Gemini run), mark scheme `/home/sico/0625_w24_ms_41.pdf`, the Gemini baseline `BUILD/accuracy-runs/e2e-0625-w24-41-2026-10-19/` ($0.15801 a script; `correction.json` for marks per leaf).

**Run directory:** `BUILD/accuracy-runs/claude-e2e-0625-w24-41-<date>/` (`<date>` the day of the run).

- [ ] **Step 1: Pin and check.** `git worktree add .claude/worktrees/claude-e2e <final SHA>`; in it, with `PYTHONPATH` pinned to the worktree (the venv is shared, see `shared-venv-editable-pth`), confirm `python -c "import lemely; print(lemely.__file__)"` prints a path inside the worktree. Read `BUILD/accuracy-runs/cost-ladder-spend.json`: Anthropic spend so far plus a projected $1.00 for this run must be at most $40.00, else stop.

- [ ] **Step 2: The effort-and-cache check (spec §4 B1 risk).** A scratch script (scratchpad, not the repo) makes two `claude-haiku-5-5` calls through `GeminiClient` with `cache_mode="bypass"`, the same system prompt (over 512 tokens), the same 2 fitted page images, `claude_cache_for={"extraction": ["system", "images"], "binding_second_read": ["system", "images"]}`, and `claude_effort_for={"binding_second_read": "medium"}` (the first read stays `low`). It prints both calls' `CallRecord.cached_tokens` and `cache_write_5m_tokens`. Then the same pair with equal effort. Record: does a different effort still read the cache? Cost: under $0.01. The finding goes into the report and, if a different effort misses, into the `claude_cache_for` comment (one-line follow-up commit, `docs(config): ...`).

- [ ] **Step 3: The configuration.** `lemely.toml` in the run directory:

```toml
[paths]
output_dir = "<run dir>/outputs"
cache_dir = "<run dir>/cache"

[gemini]
model = "claude-haiku-5-5"
mark_scheme_model = "claude-haiku-5-5"
extraction_model = "claude-haiku-5-5"
correction_model = "claude-haiku-5-5"
escalation_model = "claude-haiku-5-5"
generation_model = "claude-haiku-5-5"
scan_metadata_model = "claude-haiku-5-5"
study_plan_model = "claude-haiku-5-5"
self_review_judge_model = "claude-haiku-5-5"
correction_shared_prefix = true
claude_files_api = true
claude_cache_for = { extraction = ["system", "images"], binding_second_read = ["system", "images"], correction = ["system", "prefix"], correction_borderline = ["system", "prefix"], escalation = ["system", "prefix"] }
claude_effort_for = { "correction:mcq" = "low", "correction:numeric" = "low", "correction:short" = "low", "correction:extended" = "medium" }
correction_citations = true
correction_terse_rationale = true

[binding]
read_model = "claude-haiku-5-5"
retry_model = "claude-haiku-5-5"
claude_chunked_read = true
```

  Run `lemely doctor --no-network` with this file first: every check other than `push_transport` passes, and `llm_price_table` lists every tag on `anthropic:claude-haiku-5-5` with a price row.

- [ ] **Step 4: The driver.** `<run dir>/driver.py` (uncommitted), a copy of `BUILD/accuracy-runs/e2e-0625-w24-41-2026-10-19/driver.py` with these changes:
  - before any `lemely` import, read the keys inside the process:

```python
import os
from pathlib import Path

for var, path in (("ANTHROPIC_API_KEY", "~/.config/lemely/anthropic_key"), ("GEMINI_API_KEY", "~/.config/lemely/gemini_key")):
    os.environ.setdefault(var, Path(path).expanduser().read_text(encoding="utf-8").strip())
```

  - before the first call: `from lemely.accuracy.cost_ladder.spend import DEFAULT_SPEND_FILE, SpendCaps, SpendLedger, check_can_start, cost_by_provider`, `ledger = SpendLedger(DEFAULT_SPEND_FILE)`, `check_can_start(ledger.spent(), {"anthropic": 1.00}, SpendCaps())`;
  - wrap the whole run in `with record_calls():` and a `try:` whose `finally:` does `ledger.add(cost_by_provider(process_call_records()))` and writes `records.jsonl`, so a crash still books its spend;
  - wrap the extraction and correction stages in `with script_cost_scope(settings, script_key="0625_w24_41") as costs:` and write `costs` to `script_costs.json`;
  - after the production mark-scheme stage (deterministic parser first, as before), run two parity stages and record their calls separately: the Claude mark-scheme parse (`GeminiMarkSchemeParser(client)(MS)`, records to `records_markscheme_claude.jsonl`) and `ScanMetadataExtractor(client)(SCAN)` (records to `records_scan_metadata.jsonl`);
  - configure structlog to also write JSON lines to `<run dir>/events.jsonl` so `claude_over_tier`, `script_over_cost_target`, `claude_token_preflight`, `claude_files_api_fallback` and `binding_chunked_read` can be counted.

  Run it with output to `run.log`, in the background, from the pinned worktree.

- [ ] **Step 5: The report.** `<run dir>/COST.md`, in the shape of the Gemini run's `COST.md`:
  - Manifest: worktree SHA, config, inputs, doctor result, ledger before and after.
  - **$ per paper against $0.10**: extraction plus correction (from `script_costs.json` and the records), with the mark-scheme parse amortised over 30 scripts: once at $0 (the deterministic parser accepted the scheme) and once with the Claude parse's cost / 30. Split by task tag, model, attempt; cached, cache-write and container figures; the Gemini figure ($0.158) beside it.
  - Binding verdict and checks; whether the chunked read fired (19 pages should fit at 2200 px and not fire; say so either way); whether the Files API was used.
  - Marks per leaf against the `01f371c3` Gemini run: totals, leaves that differ, leaves flagged `uncited_mark`, leaves flagged for review. (The per-leaf table goes in an uncommitted `MARKS.md` beside it; `COST.md` carries counts only.)
  - Event counts: `claude_over_tier`, `script_over_cost_target`, `claude_token_preflight`, `claude_files_api_fallback`, `binding_chunked_read`.
  - The T9 finding (blank skip already exists), the step 2 finding (effort and cache), and the data-exposure note from Task 2c.
  - Opportunities for sub-project C seen in the run (standing rule): at least the three the spec lists, with the run's numbers where it has them.

- [ ] **Step 6: Keep student data out of git.** `extracted.json`, `correction.json`, `records*.jsonl`, `events.jsonl`, `MARKS.md`, `cache/` and `outputs/` stay uncommitted. `COST.md` may be committed (`git add -- <run dir>/COST.md && git commit -S -m "docs(accuracy): Claude E2E cost on 0625_w24_41" -- <run dir>/COST.md`) only after reading it through for answer text or student names; when in doubt, leave it uncommitted and link it from the session report.

---

## Spec coverage (self-review)

| Spec item | Task |
|---|---|
| §1 `lemely/io/llm/` package, `LLMRequest` with `fingerprint()`, `Provider.complete`/`count_tokens` | 1a, 1b (count_tokens real in 2b) |
| §1 Gemini provider moved unchanged; Claude provider; client keeps cache/retry/ceiling/ledger/records | 1b |
| §1 invariant: Gemini keys, events, records, outputs byte-identical; golden first | 0, every later task's review |
| §2 greyscale (colour exception), estimate, step-down, floor, over-budget behaviour, byte refusal at floor | 2a, 2b |
| §2 output cap honours `max_output_tokens_for`, cap in the fingerprint | 2b |
| §2 cache-key version `img_fit=v1`; encode inside `try`; stale TOML comment | 2b (2a for the encode) |
| §2 preflight with `count_tokens` within 10% | 2b |
| §2 cost guard `paper_cost_target_usd` | 3c |
| §2a Files API: upload once per job, 1 h expiry, delete at end, reuse, fallback inline, key from bytes, workspace, ZDR note | 2c |
| §2b overview and chunked read, merge, second read reuses map, pricing per call, logged | 10 |
| §3 PDFs: document blocks, 32 MB check, page limit, Gemini mapping, `parsers.py`, `scan_metadata.py`, other `file_paths` raise | 4 |
| §3 code execution: tool version, reply text, container pricing, non-student tags only | 5 |
| §3 pricing: rows with sources, cache writes, tier on total input, `inference_geo` unset test, unpriced fails closed, doctor/model table | 3a, 3b |
| §4 B1 cache breakpoints, 512-token rule, binder after images, correction prefix, effort risk | 6 (risk: 6 step 1, 11 step 2) |
| §4 B2 citations (fallback: evidence quotes), `uncited_mark` | 8a |
| §4 B3 effort per tag and per kind | 7 |
| §5.1 blank-leaf skip | 9 (no-op: exists) |
| §5.2 effort by leaf kind | 7 |
| §5.3 greyscale everywhere on Claude images | 2a/2b (every Claude image goes through `image_fit`) |
| §5.4 terse rationale | 8b |
| §6 errors: permanent vs transient, image refusal wording, cap retry, unpriced fail closed, code-exec tag check | 1b, 2b, 3a, 5 |
| §7 tests: golden, fake-SDK units, 45-page fixture, realistic 19-page fixture, `inference_geo`, live E2E, CI sweep last | 0, 2a, 3a, 10, 11, Final gate sweep |

## Spec decisions made in this plan

1. **Native citations are not built**: the docs say citations plus structured outputs return a 400. The spec's fallback (`evidence_quotes` + substring check) is Task 8a, and Task 4 refuses the combination before sending.
2. **Terse rationale** caps by schema description plus truncation, because structured outputs drop `maxLength` and a refusal would cost a retry.
3. **Code-execution reply** is the last successful run's stdout, falling back to the final text block (the spec says final text block; stdout is what today's Gemini contract returns). Container time is not in `usage`, so it is billed as `max(latency, 300 s)` when code ran.
4. **Meaningful colour** = two or more ink hue families; a single-ink page is greyscaled. Already-greyscale PNGs inside the edge are sent byte for byte.
5. **Leaf kinds** come from `QuestionType` by a fixed table (Task 7).
6. **B1 default** for a tag with no `claude_cache_for` entry is the A1 behaviour (system and prefix marked), so the lever is off by default without dropping what Claude calls already did. The binder's two reads run in turn when they share a cache, since parallel reads cannot hit each other's cache.
7. **Chunked reads** bypass the response cache, own the overlap page in the earlier chunk, and surface a duplicated label through `label_sequence`'s doubt rather than a literal G9.
8. **`claude_files_api` defaults on** (spec §2a), the one new flag that is on; it only affects `claude-` calls with page images.
9. **Cost guard** is wired into the two web marking routes; on the shipped Gemini config it logs one warning per script ($0.158 > $0.10).
10. **Non-streaming limit**: a Claude cap above 21,333 tokens (the `extraction` cap is 32,768) is streamed, because the SDK refuses such a non-streaming request.
11. **`Usage.input_tokens`** for Claude becomes the plain total (reads and writes included) now that writes are priced at their own rates; the dollar figures do not move for 5-minute writes.
12. **T9** is a no-op: US-039's blank skip (`marker_source="blank"`) already exists and is stricter.
13. **`Provider.complete`** takes a `log` keyword besides the request (the Gemini code logs its schema line on the call's bound logger).
14. **Scan metadata on Claude** sends every rasterised page, as the spec says; sending only the first pages is listed as a C candidate in Task 11's report.

Still open, settled in a named step: the Files API image-count limit by `file_id` (2c step 1), whether a different effort invalidates the binder's cached pages (6 step 1, 11 step 2), every Claude rate and model id (3a step 1), Haiku 5.5's context window for the PDF page limit (4 step 1).
