# Phase 2 — Multi-Paper Extraction, AI Correction, Subject Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Lemely correct any CAIE paper type (MCQ + theory + ATP) end-to-end and roll multiple papers up into a subject grade. Adds the shared Gemini client, a paper-type-agnostic answer extractor, a rubric-driven AI marker for non-MCQ questions, and a subject-level aggregator. Adds `extract-answers`, `aggregate-subject` CLI commands and updates `correct-paper`. Reshapes Gradio Tabs 2 and 3.

**Architecture:** A `GeminiClient` in `lemely/io/gemini.py` provides retry, cache, cost-guard, and structured-output enforcement to every AI consumer. `GeminiAnswerExtractor` builds its prompt from the mark scheme's full question manifest (hierarchical IDs, types, command words), so it handles MCQ, short answer, calculation, levels-based, and diagram extraction uniformly. `correction_ai.AICorrector` marks one non-MCQ question per call against that question's `answer_points` / `level_descriptors` / `drawing_criteria` / `plot_requirements` / `marking_guidance` subtree. A hybrid `correct_paper` orchestrator routes MCQ questions through the existing deterministic path and non-MCQ questions through AI, merging into a single `CorrectionResult` whose `CorrectedQuestion` entries carry `marker_source` ("deterministic" / "ai" / "missing"). `lemely/io/subject.py` sums multiple `CorrectionResult`s into a `SubjectResult` with subject-level grade and aggregated weaknesses.

**Tech Stack:** `google-genai`, `tenacity`, `structlog`, `pydantic`, `click`, `gradio`, `rich`

---

## File Map

**Create:**
- `lemely/io/gemini.py` — `GeminiClient`
- `lemely/io/answer_extraction.py` — `GeminiAnswerExtractor` (any paper type)
- `lemely/io/correction_ai.py` — `AICorrector` + `correct_paper` hybrid orchestrator
- `lemely/io/subject.py` — `aggregate_subject()`
- `lemely/io/prompts/answer_extraction.py` — extraction prompts + `VERSION`
- `lemely/io/prompts/correction_ai.py` — per-question AI marking prompt + `VERSION`
- `lemely/app/gradio_callbacks.py` — pure Tab 2 + Tab 3 callbacks
- `tests/test_gemini_client.py`
- `tests/test_answer_extraction.py`
- `tests/test_correction_ai.py`
- `tests/test_subject.py`

**Modify:**
- `lemely/core/schemas.py` — add `ExtractedAnswer`, `ExtractedAnswers`, `AIMarkResponse`, `SubjectResult`; extend `CorrectedQuestion` with `marker_source`, `feedback`, `matched_point_ids`
- `lemely/core/correction.py` — set `marker_source="deterministic"` on outputs
- `lemely/core/analytics.py` — accept `WeaknessReport` aggregation helper
- `lemely/io/parsers.py` — refactor to use `GeminiClient`; drop `raw_output_dir`
- `lemely/io/prompts/mark_scheme_parsing.py` — add `VERSION = "1"`
- `lemely/app/cli.py` — add `_get_settings()`, `extract-answers`, `aggregate-subject`; rewrite `correct-paper` for hybrid path
- `lemely/app/renderers.py` — `render_extracted_answers`, `render_subject_result`, update correction renderer for `marker_source`
- `lemely/app/gradio_app.py` — 6-tab structure with live Tab 2 + Tab 3
- `pyproject.toml` — extend `disallow_any_explicit = false` overrides; add ruff per-file ignore for `gemini.py`

---

## Task 1: Extend Schemas

**Files:**
- Modify: `lemely/core/schemas.py`
- Modify: `tests/test_schemas.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_schemas.py`:

```python
from lemely.core.schemas import (
    AIMarkResponse,
    ExtractedAnswer,
    ExtractedAnswers,
    SubjectResult,
    WeakArea,
    WeaknessReport,
)


class ExtractedAnswerTests(unittest.TestCase):
    def test_valid_extracted_answer(self) -> None:
        ea = ExtractedAnswer(question_id="1(a)(i)", answer="42 m/s", confidence=0.95)
        self.assertEqual(ea.question_id, "1(a)(i)")
        self.assertEqual(ea.answer, "42 m/s")
        self.assertIsNone(ea.source_region)

    def test_confidence_out_of_range_raises(self) -> None:
        with self.assertRaises(ValidationError):
            ExtractedAnswer(question_id="1", answer="A", confidence=1.5)

    def test_extracted_answers_round_trip(self) -> None:
        ea = ExtractedAnswers(
            paper_id="0625_MayJune_2020_p12",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="B", confidence=0.9),
                ExtractedAnswer(question_id="2(a)", answer="osmosis", confidence=0.8),
            ],
        )
        restored = ExtractedAnswers.model_validate(ea.model_dump(mode="json"))
        self.assertEqual(restored.paper_id, ea.paper_id)
        self.assertEqual(len(restored.answers), 2)


class AIMarkResponseTests(unittest.TestCase):
    def test_valid_response(self) -> None:
        r = AIMarkResponse(awarded_marks=2, confidence=0.85, matched_point_ids=["p1"], feedback="ok")
        self.assertEqual(r.awarded_marks, 2)

    def test_negative_marks_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AIMarkResponse(awarded_marks=-1, confidence=0.5, matched_point_ids=[], feedback="")


class CorrectedQuestionMarkerSourceTests(unittest.TestCase):
    def test_default_marker_source_is_deterministic(self) -> None:
        cq = CorrectedQuestion(
            question_id="1", awarded_marks=1, maximum_marks=1,
            confidence=ConfidenceBand.HIGH, confidence_score=1.0,
            needs_teacher_review=False,
        )
        self.assertEqual(cq.marker_source, "deterministic")
        self.assertIsNone(cq.feedback)
        self.assertEqual(cq.matched_point_ids, [])

    def test_ai_marked_question_accepts_feedback(self) -> None:
        cq = CorrectedQuestion(
            question_id="1", awarded_marks=2, maximum_marks=3,
            confidence=ConfidenceBand.MEDIUM, confidence_score=0.8,
            needs_teacher_review=False, marker_source="ai",
            feedback="Missed point p3.", matched_point_ids=["p1", "p2"],
        )
        self.assertEqual(cq.marker_source, "ai")
        self.assertEqual(cq.feedback, "Missed point p3.")


class SubjectResultTests(unittest.TestCase):
    def _paper(self, awarded: int, maximum: int) -> CorrectionResult:
        return CorrectionResult(
            metadata=ExamMetadata(
                subject_code="0625", paper_number=2, paper_variant=1,
                session_month="May/June", session_year=2020,
            ),
            questions=[
                CorrectedQuestion(
                    question_id="q1",
                    awarded_marks=awarded, maximum_marks=maximum,
                    confidence=ConfidenceBand.HIGH, confidence_score=1.0,
                    needs_teacher_review=False,
                )
            ],
        )

    def test_subject_result_sums_marks(self) -> None:
        sr = SubjectResult(
            subject_code="0625", session_month="May/June", session_year=2020,
            paper_results=[self._paper(30, 40), self._paper(60, 80), self._paper(35, 40)],
            weaknesses=WeaknessReport(weak_areas=[]),
        )
        self.assertEqual(sr.awarded_marks, 125)
        self.assertEqual(sr.maximum_marks, 160)
        self.assertAlmostEqual(sr.percentage, 78.125, places=2)
        self.assertEqual(sr.grade, "B")  # 78% with default boundaries A=80, B=70

    def test_subject_result_rejects_mismatched_subject(self) -> None:
        with self.assertRaises(ValidationError):
            SubjectResult(
                subject_code="0625", session_month="May/June", session_year=2020,
                paper_results=[
                    self._paper(10, 10),  # 0625
                ],
                weaknesses=WeaknessReport(weak_areas=[]),
            )._mutate_to_mismatch_for_test()  # noqa: pragma — we test via ValidationError below
```

Replace the mismatch test with this simpler form:
```python
    def test_subject_result_rejects_mismatched_subject(self) -> None:
        p1 = self._paper(10, 10)
        p2_meta = ExamMetadata(
            subject_code="0972", paper_number=2, paper_variant=1,
            session_month="May/June", session_year=2020,
        )
        p2 = CorrectionResult(metadata=p2_meta, questions=p1.questions)
        with self.assertRaises(ValidationError):
            SubjectResult(
                subject_code="0625", session_month="May/June", session_year=2020,
                paper_results=[p1, p2],
                weaknesses=WeaknessReport(weak_areas=[]),
            )
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/sico/Code/Lemely && source lemely/bin/activate && python -m pytest tests/test_schemas.py -v 2>&1 | tail -20
```

Expected: `ImportError: cannot import name 'ExtractedAnswer'`

- [ ] **Step 3: Update `lemely/core/schemas.py`**

Modify `CorrectedQuestion` to add three optional fields and a `Literal` import. Replace the `CorrectedQuestion` class:

```python
class CorrectedQuestion(StrictModel):
    question_id: str
    awarded_marks: int = Field(..., ge=0)
    maximum_marks: int = Field(..., ge=0)
    confidence: ConfidenceBand
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    needs_teacher_review: bool
    student_answer: str | None = None
    expected_answer: str | None = None
    topic: str | None = None
    review_reason: str | None = None
    marker_source: Literal["deterministic", "ai", "missing"] = "deterministic"
    feedback: str | None = None
    matched_point_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_awarded_marks(self) -> CorrectedQuestion:
        if self.awarded_marks > self.maximum_marks:
            raise ValueError("awarded_marks cannot exceed maximum_marks")
        return self
```

Append the new schemas after `AccuracyReport`:

```python
class ExtractedAnswer(StrictModel):
    question_id: str
    answer: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    source_region: str | None = None


class ExtractedAnswers(StrictModel):
    paper_id: str
    source_scan: str
    answers: list[ExtractedAnswer]


class AIMarkResponse(StrictModel):
    awarded_marks: int = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    matched_point_ids: list[str] = Field(default_factory=list)
    feedback: str


class SubjectResult(StrictModel):
    subject_code: str = Field(..., pattern=r"^\d{4}$")
    session_month: Literal["May/June", "Oct/Nov", "Feb/Mar", "Specimen"]
    session_year: int | None = Field(None, ge=2000, le=2100)
    paper_results: list[CorrectionResult] = Field(..., min_length=1)
    awarded_marks: int = 0
    maximum_marks: int = 0
    percentage: float = 0.0
    grade: str = "U"
    weaknesses: WeaknessReport
    needs_teacher_review: bool = False

    @model_validator(mode="after")
    def validate_and_compute(self) -> SubjectResult:
        # All papers must share the same subject+session
        for paper in self.paper_results:
            m = paper.metadata
            if m.subject_code != self.subject_code:
                raise ValueError(
                    f"paper subject_code {m.subject_code} != subject {self.subject_code}"
                )
            if m.session_month != self.session_month:
                raise ValueError(
                    f"paper session_month {m.session_month} != subject {self.session_month}"
                )
            if m.session_year != self.session_year:
                raise ValueError(
                    f"paper session_year {m.session_year} != subject {self.session_year}"
                )

        awarded = sum(p.awarded_marks for p in self.paper_results)
        maximum = sum(p.maximum_marks for p in self.paper_results)
        pct = (awarded / maximum * 100.0) if maximum else 0.0
        # Default CAIE-ish boundaries (same as analytics.DEFAULT_GRADE_BOUNDARIES)
        grade = "U"
        for cand, threshold in [("A", 80.0), ("B", 70.0), ("C", 60.0), ("D", 50.0), ("E", 40.0)]:
            if pct >= threshold:
                grade = cand
                break
        needs_review = any(p.needs_teacher_review for p in self.paper_results)

        object.__setattr__(self, "awarded_marks", awarded)
        object.__setattr__(self, "maximum_marks", maximum)
        object.__setattr__(self, "percentage", round(pct, 2))
        object.__setattr__(self, "grade", grade)
        object.__setattr__(self, "needs_teacher_review", needs_review)
        return self
```

- [ ] **Step 4: Update existing deterministic correction to set marker_source**

In `lemely/core/correction.py`, the three places that construct `CorrectedQuestion` already default to `marker_source="deterministic"` — but we should be explicit. Open the file and for every `CorrectedQuestion(...)` call, add the kwarg `marker_source="deterministic"` for clarity (optional since it's the default).

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_schemas.py tests/test_correction.py tests/test_renderers.py -v 2>&1 | tail -25
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add lemely/core/schemas.py lemely/core/correction.py tests/test_schemas.py
git commit -S -m "feat(schemas): add ExtractedAnswer/Answers, AIMarkResponse, SubjectResult; extend CorrectedQuestion"
```

---

## Task 2: GeminiClient — Shared Infrastructure

**Files:**
- Create: `lemely/io/gemini.py`
- Modify: `pyproject.toml`
- Create: `tests/test_gemini_client.py`

- [ ] **Step 1: Update `pyproject.toml`** — extend mypy `disallow_any_explicit = false` override:

Find the `[[tool.mypy.overrides]]` block listing `lemely.core.schemas`, `lemely.core.loose_schemas`, etc. Add to that list:
```
  "lemely.io.gemini",
  "lemely.io.answer_extraction",
  "lemely.io.correction_ai",
  "lemely.io.subject",
  "lemely.app.gradio_callbacks",
```

Also add this ruff per-file ignore (in the `[tool.ruff.lint.per-file-ignores]` block):
```toml
"lemely/io/gemini.py" = ["PLW0603", "PLW0602", "BLE001"]
"lemely/io/correction_ai.py" = ["BLE001"]
```

- [ ] **Step 2: Write failing tests** — create `tests/test_gemini_client.py`:

```python
"""Unit tests for lemely.io.gemini.GeminiClient (genai.Client mocked)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pydantic import BaseModel

from lemely.io.gemini import GeminiClient, _reset_process_counters
from lemely.runtime.config import GeminiSettings, PathsSettings, load_settings
from lemely.runtime.errors import ExternalServiceError, ParseError


class _SimpleSchema(BaseModel):
    value: str


def _mock_response(text: str, in_tok: int = 10, out_tok: int = 20) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    cand = MagicMock()
    finish = MagicMock()
    finish.__str__ = lambda self: "STOP"
    cand.finish_reason = finish
    resp.candidates = [cand]
    resp.usage_metadata = MagicMock(
        prompt_token_count=in_tok, candidates_token_count=out_tok,
    )
    return resp


class _IsolatedEnv:
    def __enter__(self) -> _IsolatedEnv:
        self._snap = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("LEMELY_"):
                del os.environ[k]
        return self

    def __exit__(self, *_: object) -> None:
        os.environ.clear()
        os.environ.update(self._snap)


def _make_settings(tmp: str, **gemini_overrides: object):
    with _IsolatedEnv():
        s = load_settings(toml_path=None, cwd=Path(tmp))
    s = s.model_copy(update={"paths": PathsSettings(cache_dir=Path(tmp) / ".cache")})
    if gemini_overrides:
        s = s.model_copy(update={"gemini": s.gemini.model_copy(update=gemini_overrides)})
    return s


class GeminiClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        _reset_process_counters()

    def test_cache_hit_skips_api(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        for _ in range(2):
            r = client.generate_structured(
                system_prompt="sys", user_prompt="user",
                response_schema=_SimpleSchema, prompt_version="1",
            )
            self.assertEqual(r.value, "hi")
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_version_bump_busts_cache(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "v1"}'),
            _mock_response('{"value": "v2"}'),
        ]
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        r1 = client.generate_structured(
            system_prompt="s", user_prompt="u", response_schema=_SimpleSchema, prompt_version="1",
        )
        r2 = client.generate_structured(
            system_prompt="s", user_prompt="u", response_schema=_SimpleSchema, prompt_version="2",
        )
        self.assertEqual((r1.value, r2.value), ("v1", "v2"))

    def test_cost_guard_raises_after_token_ceiling(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response(
            '{"value": "x"}', in_tok=500, out_tok=600,
        )
        mock_genai.files.upload.return_value = MagicMock()
        settings = _make_settings(self.tmp, per_run_token_ceiling=100)
        client = GeminiClient(settings, _genai_client=mock_genai)

        client.generate_structured(
            system_prompt="s", user_prompt="u1",
            response_schema=_SimpleSchema, prompt_version="1",
        )
        with self.assertRaises(ExternalServiceError):
            client.generate_structured(
                system_prompt="s", user_prompt="u2",
                response_schema=_SimpleSchema, prompt_version="1",
            )

    def test_schema_validation_failure_raises_parse_error(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"wrong": "key"}')
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(
            _make_settings(self.tmp, max_retries=0),
            _genai_client=mock_genai,
        )

        with self.assertRaises(ParseError):
            client.generate_structured(
                system_prompt="s", user_prompt="u",
                response_schema=_SimpleSchema, prompt_version="1",
            )
```

- [ ] **Step 3: Create `lemely/io/gemini.py`**

```python
"""Shared Gemini AI client: retry, persistent cache, cost guard, structured logging."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from lemely.runtime.config import Settings
from lemely.runtime.errors import ExternalServiceError, ParseError

_T = TypeVar("_T", bound=BaseModel)

# Approximate Gemini 2.5 Flash pricing (USD per 1K tokens)
_FLASH_INPUT_USD_PER_1K: float = 0.00015
_FLASH_OUTPUT_USD_PER_1K: float = 0.0006

_process_input_tokens: int = 0
_process_output_tokens: int = 0


def _reset_process_counters() -> None:
    global _process_input_tokens, _process_output_tokens
    _process_input_tokens = 0
    _process_output_tokens = 0


def process_token_totals() -> tuple[int, int]:
    """Read-only accessor for tests / doctor."""
    return _process_input_tokens, _process_output_tokens


class _TransientError(Exception):
    """Wraps transient Gemini SDK errors so tenacity can detect them."""


class GeminiClient:
    def __init__(self, settings: Settings, *, _genai_client: Any = None) -> None:
        self._settings = settings
        self._raw_client: Any = _genai_client

    @property
    def _client(self) -> Any:
        if self._raw_client is None:
            from google import genai  # type: ignore[import-untyped]

            api_key = (
                self._settings.gemini_api_key.get_secret_value()
                if self._settings.gemini_api_key
                else None
            )
            self._raw_client = genai.Client(api_key=api_key)
        return self._raw_client

    def _cache_key(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        prompt_version: str,
        file_paths: list[Path] | None,
        extra_key: str,
    ) -> str:
        prompt_hash = hashlib.sha256(
            (system_prompt + user_prompt + prompt_version + extra_key).encode()
        ).hexdigest()[:12]
        if file_paths:
            h = hashlib.sha256()
            for fp in sorted(file_paths):
                h.update(fp.read_bytes())
            files_hash = h.hexdigest()[:12]
        else:
            files_hash = "none"
        combined = f"{model}:{prompt_hash}:{files_hash}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def _cache_path(self, key: str) -> Path:
        d = self._settings.paths.cache_dir / "gemini"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{key}.json"

    def _check_cost_ceiling(self) -> None:
        g = self._settings.gemini
        if g.per_run_token_ceiling is not None:
            total = _process_input_tokens + _process_output_tokens
            if total >= g.per_run_token_ceiling:
                raise ExternalServiceError(
                    f"Token ceiling ({g.per_run_token_ceiling}) exceeded; accumulated {total}."
                )
        if g.monthly_usd_ceiling is not None:
            usd = (
                _process_input_tokens / 1000 * _FLASH_INPUT_USD_PER_1K
                + _process_output_tokens / 1000 * _FLASH_OUTPUT_USD_PER_1K
            )
            if usd >= g.monthly_usd_ceiling:
                raise ExternalServiceError(
                    f"USD ceiling (${g.monthly_usd_ceiling:.4f}) exceeded; "
                    f"accumulated ${usd:.4f} this process."
                )

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        file_paths: list[Path] | None = None,
        response_schema: type[_T],
        prompt_version: str,
        model: str | None = None,
        extra_cache_key: str = "",
    ) -> _T:
        active_model = model or self._settings.gemini.model
        log = structlog.get_logger().bind(component="gemini_client", model=active_model)

        cache_key = self._cache_key(
            active_model, system_prompt, user_prompt, prompt_version, file_paths, extra_cache_key,
        )
        cache_path = self._cache_path(cache_key)

        if cache_path.exists():
            log.info("gemini_cache_hit", cache_key=cache_key)
            return response_schema.model_validate_json(
                cache_path.read_text(encoding="utf-8")
            )

        self._check_cost_ceiling()

        t0 = time.monotonic()
        raw_text = self._call_with_retry(
            active_model, system_prompt, user_prompt, file_paths, response_schema, log,
        )
        log.debug("gemini_latency_ms", latency_ms=int((time.monotonic() - t0) * 1000))

        try:
            result: _T = response_schema.model_validate_json(raw_text)
        except Exception:
            corrected = (
                user_prompt
                + f"\n\nYour previous response did not match the required JSON schema for "
                f"{response_schema.__name__}. Return JSON matching the schema exactly."
            )
            raw_text = self._call_once(
                active_model, system_prompt, corrected, file_paths, response_schema, log,
            )
            try:
                result = response_schema.model_validate_json(raw_text)
            except Exception as exc:
                raise ParseError(
                    f"Gemini response did not validate against {response_schema.__name__} "
                    "even after schema-correction retry."
                ) from exc

        cache_path.write_text(raw_text, encoding="utf-8")
        return result

    def _call_with_retry(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        file_paths: list[Path] | None,
        response_schema: type[_T],
        log: Any,
    ) -> str:
        def _before_sleep(state: RetryCallState) -> None:
            exc = state.outcome.exception() if state.outcome else None
            log.warning(
                "gemini_retry",
                attempt=state.attempt_number,
                error=str(exc) if exc else "",
            )

        g = self._settings.gemini
        for attempt in Retrying(
            stop=stop_after_attempt(g.max_retries + 1),
            wait=wait_exponential(multiplier=g.backoff_seconds, min=1, max=60),
            retry=retry_if_exception_type(_TransientError),
            before_sleep=_before_sleep,
            reraise=True,
        ):
            with attempt:
                return self._call_once(
                    model, system_prompt, user_prompt, file_paths, response_schema, log,
                )
        raise ParseError("Unreachable")  # pragma: no cover

    def _call_once(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        file_paths: list[Path] | None,
        response_schema: type[_T],
        log: Any,
    ) -> str:
        from google.genai import types  # type: ignore[import-untyped]

        file_parts: list[Any] = []
        if file_paths:
            for fp in file_paths:
                file_parts.append(self._client.files.upload(file=fp))

        try:
            response = self._client.models.generate_content(
                model=model,
                config=types.GenerateContentConfig(
                    max_output_tokens=65536,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    response_mime_type="application/json",
                    response_schema=response_schema.model_json_schema(),
                    system_instruction=system_prompt,
                ),
                contents=[user_prompt, *file_parts],
            )
        except Exception as exc:
            msg = str(exc).lower()
            if any(t in msg for t in ("500", "503", "rate limit", "resource exhausted", "connection")):
                raise _TransientError(str(exc)) from exc
            raise ExternalServiceError(str(exc)) from exc

        global _process_input_tokens, _process_output_tokens
        in_tok = int(getattr(response.usage_metadata, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(response.usage_metadata, "candidates_token_count", 0) or 0)
        _process_input_tokens += in_tok
        _process_output_tokens += out_tok
        usd = in_tok / 1000 * _FLASH_INPUT_USD_PER_1K + out_tok / 1000 * _FLASH_OUTPUT_USD_PER_1K
        log.info(
            "gemini_call",
            input_tokens=in_tok, output_tokens=out_tok,
            usd_cost=round(usd, 6), cache_hit=False,
        )

        raw = response.text or ""
        finish = str(response.candidates[0].finish_reason if response.candidates else "")
        if finish == "MAX_TOKENS":
            raise _TransientError(f"Gemini hit max_output_tokens ({model})")
        return raw
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_gemini_client.py -v 2>&1 | tail -20
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add lemely/io/gemini.py tests/test_gemini_client.py pyproject.toml
git commit -S -m "feat(io): add GeminiClient with retry, cache, cost guard, logging"
```

---

## Task 3: Refactor parsers.py + Update CLI

**Files:**
- Modify: `lemely/io/parsers.py`
- Modify: `lemely/io/prompts/mark_scheme_parsing.py`
- Modify: `lemely/app/cli.py`
- Modify: `tests/test_parsers.py`

- [ ] **Step 1: Add `VERSION` to mark scheme prompt**

In `lemely/io/prompts/mark_scheme_parsing.py`, add at the top after the module docstring (or before `PARSER_SYSTEM_PROMPT`):

```python
VERSION = "1"
```

- [ ] **Step 2: Replace `lemely/io/parsers.py`**

```python
from __future__ import annotations

from pathlib import Path

from lemely.core.loose_schemas import MarkScheme
from lemely.io.gemini import GeminiClient
from lemely.io.prompts.mark_scheme_parsing import (
    PARSER_SYSTEM_PROMPT,
    PARSER_USER_PROMPT,
    VERSION,
)


class GeminiMarkSchemeParser:
    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def __call__(self, pdf_path: Path) -> MarkScheme:
        return self._client.generate_structured(
            system_prompt=PARSER_SYSTEM_PROMPT,
            user_prompt=PARSER_USER_PROMPT,
            file_paths=[pdf_path],
            response_schema=MarkScheme,
            prompt_version=VERSION,
        )
```

- [ ] **Step 3: Update `tests/test_parsers.py`**

Replace the existing `ParserHookTests` body:

```python
import unittest
from unittest.mock import MagicMock

from lemely.core.loose_schemas import MarkScheme
from lemely.io.gemini import GeminiClient
from lemely.io.parsers import GeminiMarkSchemeParser
from lemely.io.prompts.mark_scheme_parsing import (
    PARSER_SYSTEM_PROMPT,
    PARSER_USER_PROMPT,
    VERSION,
)


class ParserHookTests(unittest.TestCase):
    def test_gemini_parser_wires_through_client_with_correct_prompt(self):
        mock_client = MagicMock(spec=GeminiClient)
        parser = GeminiMarkSchemeParser(mock_client)
        self.assertIn("Cambridge IGCSE mark schemes", PARSER_SYSTEM_PROMPT)
        self.assertIn("Extract the following IGCSE mark scheme PDF", PARSER_USER_PROMPT)
        self.assertEqual(VERSION, "1")
        self.assertIn("questions", MarkScheme.model_json_schema()["properties"])
        # parser._client is the injected mock
        self.assertIs(parser._client, mock_client)
```

- [ ] **Step 4: Add `_get_settings()` helper in `lemely/app/cli.py`**

Add after `_load_json_file`:

```python
def _get_settings(ctx: click.Context):
    from lemely.runtime.config import load_settings

    cfg = ctx.obj.get("config_path")
    return load_settings(toml_path=Path(cfg) if cfg else None)
```

- [ ] **Step 5: Update `parse_mark_schemes_cmd` in `lemely/app/cli.py`**

Remove the top-level import of `GeminiMarkSchemeParser` from `cli.py`. Replace the command body:

```python
@cli.command("parse-mark-schemes")
@click.argument("source_root", type=click.Path(exists=True, file_okay=False))
@click.option("--output-root", type=click.Path(file_okay=False), default=None)
@click.option("--force", is_flag=True)
@click.option("--use-gemini", is_flag=True)
@click.option("--gemini-model", default=None,
              help="Override gemini model (default: settings.gemini.model)")
@click.option(
    "--on-error",
    type=click.Choice(["continue", "fail"]),
    default="continue", show_default=True,
)
@click.pass_context
def parse_mark_schemes_cmd(
    ctx: click.Context,
    source_root: str,
    output_root: str | None,
    force: bool,
    use_gemini: bool,
    gemini_model: str | None,
    on_error: str,
) -> None:
    from lemely.io.gemini import GeminiClient
    from lemely.io.parsers import GeminiMarkSchemeParser
    from lemely.runtime.errors import PartialFailureError

    parser = None
    if use_gemini:
        settings = _get_settings(ctx)
        if gemini_model:
            settings = settings.model_copy(
                update={"gemini": settings.gemini.model_copy(update={"model": gemini_model})}
            )
        parser = GeminiMarkSchemeParser(GeminiClient(settings))

    result = process_mark_scheme_batch(source_root, output_root, force=force, parser=parser)
    _print_result(ctx, result)
    failures = [item for item in result.items if item.status in {"failed", "invalid_existing"}]
    if failures:
        if on_error == "fail":
            raise click.exceptions.Exit(ParseError.exit_code)
        raise click.exceptions.Exit(PartialFailureError.exit_code)
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_parsers.py tests/test_cli.py tests/test_mark_schemes.py -v 2>&1 | tail -25
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add lemely/io/parsers.py lemely/io/prompts/mark_scheme_parsing.py lemely/app/cli.py tests/test_parsers.py
git commit -S -m "refactor(io): GeminiMarkSchemeParser uses shared GeminiClient"
```

---

## Task 4: Answer Extraction Prompt + GeminiAnswerExtractor (Paper-Type-Agnostic)

**Files:**
- Create: `lemely/io/prompts/answer_extraction.py`
- Modify: `lemely/io/prompts/__init__.py`
- Create: `lemely/io/answer_extraction.py`
- Create: `tests/test_answer_extraction.py`

- [ ] **Step 1: Create `lemely/io/prompts/answer_extraction.py`**

```python
"""Prompts for GeminiAnswerExtractor. VERSION invalidates the cache on change."""

from __future__ import annotations

from lemely.core.loose_schemas import MarkScheme, Question, QuestionType

VERSION = "1"

EXTRACTOR_SYSTEM_PROMPT = """
You are an expert at reading scanned CAIE (Cambridge IGCSE / O-Level / A-Level) exam scripts.
Your task is to extract the student's response for every leaf question in the mark scheme.

A leaf question is one with marks > 0 that has no further sub-parts. Container questions
(marks == 0 that only group sub-parts) MUST be skipped — they have no answer to extract.

Different question types require different extraction:
- **mcq**: extract the selected letter ("A", "B", "C", "D"). Use empty string "" if blank.
- **recall / explanation**: extract the student's free-text answer, preserving wording.
- **calculation / equation**: extract the numerical answer including any unit, e.g. "42 m/s",
  "1.6 × 10⁵ N". Preserve standard form if the student used it.
- **list / tickbox**: extract a semicolon-separated list of the student's selected items.
- **levels_based / indicative_content**: extract the full response as-is.
- **diagram / graph_draw**: describe what the student drew briefly, e.g.
  "curved line through (2,4) and (5,10), labelled axes".

Each ExtractedAnswer needs:
- question_id (string) — must match the mark scheme question id exactly (e.g. "1", "1(a)(i)").
- answer (string) — see above; empty string if blank/unanswered.
- confidence (float 0.0-1.0) — set below 0.7 when handwriting or layout makes you uncertain.
- source_region (string or null) — e.g. "page 2, q1a area".

Do not invent answers. Do not extract questions absent from the manifest. If the student left
a question blank, return answer="" with high confidence.
"""


def _summarize_question(q: Question) -> str:
    cmd = q.question_command or ""
    type_hint = q.type.value
    parts = [f"- {q.id}: type={type_hint}, marks={q.marks}"]
    if cmd:
        parts.append(f"  command: {cmd[:120]}")
    if q.type == QuestionType.MCQ:
        parts.append("  expected answer shape: single letter A/B/C/D")
    elif q.type in {QuestionType.CALCULATION, QuestionType.EQUATION}:
        parts.append("  expected answer shape: numerical value + unit if applicable")
    elif q.type in {QuestionType.LEVELS_BASED, QuestionType.INDICATIVE_CONTENT}:
        parts.append("  expected answer shape: extended written response")
    return "\n".join(parts)


def build_extractor_user_prompt(mark_scheme: MarkScheme) -> str:
    """Build the user prompt enumerating every leaf question the student should have answered."""
    leaves: list[Question] = []
    for q in mark_scheme.all_questions_flat():
        if q.parts:  # container question
            continue
        if q.marks <= 0:  # zero-mark container
            continue
        leaves.append(q)

    if not leaves:
        manifest = "(no leaf questions found)"
    else:
        manifest = "\n".join(_summarize_question(q) for q in leaves)

    meta = mark_scheme.metadata
    year = meta.session_year if meta.session_year is not None else "Specimen"
    return (
        f"Extract this student's answers from the attached scanned paper.\n\n"
        f"Paper: {meta.subject_code}/{meta.paper_number}{meta.paper_variant} "
        f"{meta.session_month.value} {year} ({meta.paper_type.value}).\n\n"
        f"Question manifest:\n{manifest}\n\n"
        f"Return JSON: {{\"answers\": [ExtractedAnswer, ...]}}. Include one ExtractedAnswer "
        f"per leaf question above whose answer you can identify in the scan. Skip questions "
        f"you cannot find at all (do not invent question_ids)."
    )


def build_question_manifest_hash_key(mark_scheme: MarkScheme) -> str:
    """Hash the question id+type+marks tuple list so cache keys vary by paper, not just file."""
    import hashlib
    tokens = []
    for q in mark_scheme.all_questions_flat():
        tokens.append(f"{q.id}:{q.type.value}:{q.marks}")
    return hashlib.sha256("|".join(tokens).encode()).hexdigest()[:12]
```

- [ ] **Step 2: Update `lemely/io/prompts/__init__.py`** — add re-export:

```python
from lemely.io.prompts.answer_extraction import (  # noqa: F401
    EXTRACTOR_SYSTEM_PROMPT,
    VERSION as EXTRACTOR_PROMPT_VERSION,
    build_extractor_user_prompt,
    build_question_manifest_hash_key,
)
```

- [ ] **Step 3: Write failing tests** — create `tests/test_answer_extraction.py`:

```python
"""Unit tests for GeminiAnswerExtractor (GeminiClient mocked)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswers
from lemely.io.answer_extraction import GeminiAnswerExtractor
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import PathsSettings, load_settings


def _minimal_mcq_mark_scheme() -> MarkScheme:
    return MarkScheme.model_validate({
        "metadata": {
            "subject": "Physics", "subject_code": "0625",
            "paper_number": 1, "paper_variant": 2,
            "session_month": "May/June", "session_year": 2020,
            "paper_type": "mcq", "maximum_mark": 3, "scheme_format": "mcq",
        },
        "questions": [
            {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
            {"id": "2", "marks": 1, "type": "mcq", "mcq_answer": "B"},
            {"id": "3", "marks": 1, "type": "mcq", "mcq_answer": "C"},
        ],
    })


def _theory_mark_scheme() -> MarkScheme:
    return MarkScheme.model_validate({
        "metadata": {
            "subject": "Physics", "subject_code": "0625",
            "paper_number": 4, "paper_variant": 2,
            "session_month": "May/June", "session_year": 2020,
            "paper_type": "theory_extended", "maximum_mark": 5, "scheme_format": "point_based",
        },
        "questions": [
            {
                "id": "1(a)", "marks": 2, "type": "explanation",
                "question_command": "explain why",
                "answer_points": [
                    {"id": "p1", "point": "due to gravity", "marks": 1},
                    {"id": "p2", "point": "acting downward", "marks": 1},
                ],
            },
            {
                "id": "1(b)", "marks": 3, "type": "calculation",
                "question_command": "calculate the speed",
                "answer_points": [
                    {"id": "p1", "point": "v = d/t", "marks": 1, "math_mark_type": "M"},
                    {"id": "p2", "point": "v = 100/5", "marks": 1, "math_mark_type": "M"},
                    {"id": "p3", "point": "20 m/s", "marks": 1, "math_mark_type": "A"},
                ],
            },
        ],
    })


class _IsolatedEnv:
    def __enter__(self) -> _IsolatedEnv:
        self._snap = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("LEMELY_"):
                del os.environ[k]
        return self

    def __exit__(self, *_: object) -> None:
        os.environ.clear()
        os.environ.update(self._snap)


def _client_with_response(tmp: str, body: dict) -> GeminiClient:
    mock_genai = MagicMock()
    resp = MagicMock(
        text=json.dumps(body),
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(prompt_token_count=5, candidates_token_count=30),
    )
    mock_genai.models.generate_content.return_value = resp
    mock_genai.files.upload.return_value = MagicMock()
    with _IsolatedEnv():
        settings = load_settings(toml_path=None, cwd=Path(tmp))
    settings = settings.model_copy(
        update={"paths": PathsSettings(cache_dir=Path(tmp) / ".cache")}
    )
    return GeminiClient(settings, _genai_client=mock_genai)


class AnswerExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.scan = Path(self.tmp) / "scan.png"
        self.scan.write_bytes(b"\x89PNG\r\n\x1a\n")

    def test_mcq_extraction(self) -> None:
        body = {"answers": [
            {"question_id": "1", "answer": "A", "confidence": 0.99, "source_region": None},
            {"question_id": "2", "answer": "B", "confidence": 0.95, "source_region": None},
            {"question_id": "3", "answer": "C", "confidence": 0.85, "source_region": None},
        ]}
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        self.assertIsInstance(result, ExtractedAnswers)
        self.assertEqual(len(result.answers), 3)
        self.assertEqual(result.answers[0].answer, "A")
        self.assertIn("0625", result.paper_id)

    def test_theory_extraction_handles_freetext(self) -> None:
        body = {"answers": [
            {"question_id": "1(a)", "answer": "because gravity pulls it down", "confidence": 0.8, "source_region": None},
            {"question_id": "1(b)", "answer": "20 m/s using v=d/t", "confidence": 0.9, "source_region": None},
        ]}
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self.scan, mark_scheme=_theory_mark_scheme())
        self.assertEqual(len(result.answers), 2)
        self.assertIn("gravity", result.answers[0].answer)
        self.assertIn("20 m/s", result.answers[1].answer)
```

- [ ] **Step 4: Create `lemely/io/answer_extraction.py`**

```python
"""GeminiAnswerExtractor — extracts student responses from scanned exam papers (any paper type)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from lemely.io.gemini import GeminiClient
from lemely.io.prompts.answer_extraction import (
    EXTRACTOR_SYSTEM_PROMPT,
    VERSION,
    build_extractor_user_prompt,
    build_question_manifest_hash_key,
)


class _ExtractorOutput(BaseModel):
    """Inner schema we ask Gemini to return — just the answers list."""

    answers: list[ExtractedAnswer]


def _build_paper_id(mark_scheme: MarkScheme) -> str:
    m = mark_scheme.metadata
    session = m.session_month.value.replace("/", "")
    year = str(m.session_year) if m.session_year is not None else "specimen"
    return f"{m.subject_code}_{session}_{year}_p{m.paper_number}{m.paper_variant}"


class GeminiAnswerExtractor:
    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def __call__(self, scan_path: Path, mark_scheme: MarkScheme) -> ExtractedAnswers:
        manifest_key = build_question_manifest_hash_key(mark_scheme)
        raw = self._client.generate_structured(
            system_prompt=EXTRACTOR_SYSTEM_PROMPT,
            user_prompt=build_extractor_user_prompt(mark_scheme),
            file_paths=[scan_path],
            response_schema=_ExtractorOutput,
            prompt_version=VERSION,
            extra_cache_key=manifest_key,
        )
        return ExtractedAnswers(
            paper_id=_build_paper_id(mark_scheme),
            source_scan=str(scan_path),
            answers=raw.answers,
        )
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_answer_extraction.py -v 2>&1 | tail -20
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add lemely/io/prompts/answer_extraction.py lemely/io/prompts/__init__.py lemely/io/answer_extraction.py tests/test_answer_extraction.py
git commit -S -m "feat(io): paper-type-agnostic GeminiAnswerExtractor"
```

---

## Task 5: AI Marking Prompt + AICorrector + Hybrid Orchestrator

**Files:**
- Create: `lemely/io/prompts/correction_ai.py`
- Modify: `lemely/io/prompts/__init__.py`
- Create: `lemely/io/correction_ai.py`
- Create: `tests/test_correction_ai.py`

- [ ] **Step 1: Create `lemely/io/prompts/correction_ai.py`**

```python
"""Prompts for AICorrector. Per-question rubric marking. VERSION invalidates cache."""

from __future__ import annotations

from lemely.core.loose_schemas import Question

VERSION = "1"

MARKER_SYSTEM_PROMPT = """
You are an experienced CAIE examiner marking a single exam question for a Cambridge
IGCSE / O-Level / A-Level paper. Apply the mark scheme strictly and consistently.

Rules:
- Apply standard CAIE abbreviations: ecf (error carried forward), owtte (or words to that effect),
  oe (or equivalent), cao (correct answer only), dep (dependent), ft (follow-through),
  nfww (not from wrong working), soi (seen or implied), AVP (alternative valid point).
- Where the mark scheme lists "accept" variants, credit any of them.
- Where the mark scheme lists "reject" or "ignore", do NOT credit those forms.
- For mathematics, M marks are method marks (award if working shown even with arithmetic slip);
  A marks are dependent accuracy marks (require the preceding M and the correct value).
- For levels-based questions, judge the response against each LevelDescriptor's mark_range
  and pick the band that best fits.
- For diagrams/graphs, the student's response is given as a text description by an earlier
  OCR pass; if the description matches the criteria mark accordingly. If the description is
  too vague to judge, set confidence < 0.5.

Return:
- awarded_marks: integer, 0 ≤ awarded ≤ maximum_marks (the question's marks field)
- confidence: 0.0–1.0. Mark < 0.7 when scheme application is uncertain.
- matched_point_ids: ids of AnswerPoints / LevelDescriptors / DrawingCriteria the student satisfied.
- feedback: one or two sentences a teacher can read; explain what was and was not credited.
"""


def build_marker_user_prompt(question: Question, student_answer: str) -> str:
    """Build the per-question marking prompt embedding the mark scheme subtree + student response."""
    # Serialise the question subtree compactly (omit nulls / empty defaults).
    q_json = question.model_dump_json(indent=2, exclude_none=True, exclude_defaults=True)
    answer_text = student_answer if student_answer.strip() else "(blank — no response written)"
    return (
        f"Mark this CAIE question.\n\n"
        f"MARK SCHEME SUBTREE (JSON):\n{q_json}\n\n"
        f"STUDENT ANSWER (verbatim from scan):\n{answer_text}\n\n"
        f"Apply the mark scheme above. The maximum_marks for your awarded_marks field is "
        f"{question.marks}. Return JSON matching the AIMarkResponse schema."
    )
```

- [ ] **Step 2: Add re-export to `lemely/io/prompts/__init__.py`**

Append:
```python
from lemely.io.prompts.correction_ai import (  # noqa: F401
    MARKER_SYSTEM_PROMPT,
    VERSION as MARKER_PROMPT_VERSION,
    build_marker_user_prompt,
)
```

- [ ] **Step 3: Write failing tests** — create `tests/test_correction_ai.py`:

```python
"""Unit tests for AICorrector and the hybrid correct_paper orchestrator."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import (
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExtractedAnswer,
    ExtractedAnswers,
)
from lemely.io.correction_ai import AICorrector, correct_paper
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import PathsSettings, load_settings
from lemely.runtime.errors import ConfigError


def _hybrid_paper_mark_scheme() -> MarkScheme:
    """Two questions: one MCQ + one short theory question."""
    return MarkScheme.model_validate({
        "metadata": {
            "subject": "Physics", "subject_code": "0625",
            "paper_number": 4, "paper_variant": 2,
            "session_month": "May/June", "session_year": 2020,
            "paper_type": "theory_extended", "maximum_mark": 3, "scheme_format": "mixed",
        },
        "questions": [
            {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
            {
                "id": "2", "marks": 2, "type": "explanation",
                "question_command": "explain why",
                "answer_points": [
                    {"id": "p1", "point": "gravity acts on it", "marks": 1},
                    {"id": "p2", "point": "no air resistance", "marks": 1},
                ],
            },
        ],
    })


class _IsolatedEnv:
    def __enter__(self) -> _IsolatedEnv:
        self._snap = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("LEMELY_"):
                del os.environ[k]
        return self

    def __exit__(self, *_: object) -> None:
        os.environ.clear()
        os.environ.update(self._snap)


def _mock_marker_response(awarded: int, matched: list[str], feedback: str = "good") -> MagicMock:
    body = {
        "awarded_marks": awarded,
        "confidence": 0.9,
        "matched_point_ids": matched,
        "feedback": feedback,
    }
    return MagicMock(
        text=json.dumps(body),
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
    )


def _client_with_seq(tmp: str, responses: list[MagicMock]) -> GeminiClient:
    mock_genai = MagicMock()
    mock_genai.models.generate_content.side_effect = responses
    mock_genai.files.upload.return_value = MagicMock()
    with _IsolatedEnv():
        s = load_settings(toml_path=None, cwd=Path(tmp))
    s = s.model_copy(update={"paths": PathsSettings(cache_dir=Path(tmp) / ".cache")})
    return GeminiClient(s, _genai_client=mock_genai)


class HybridCorrectPaperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.ms = _hybrid_paper_mark_scheme()

    def _extracted(self, mcq_answer: str, theory_answer: str) -> ExtractedAnswers:
        return ExtractedAnswers(
            paper_id="test", source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer=mcq_answer, confidence=0.99),
                ExtractedAnswer(question_id="2", answer=theory_answer, confidence=0.85),
            ],
        )

    def test_mcq_only_flag_skips_ai_and_marks_theory_missing(self) -> None:
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=self._extracted("A", "because gravity"),
            gemini_client=None,
            mcq_only=True,
        )
        self.assertEqual(len(result.questions), 2)
        q1 = next(q for q in result.questions if q.question_id == "1")
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q1.marker_source, "deterministic")
        self.assertEqual(q1.awarded_marks, 1)
        self.assertEqual(q2.marker_source, "missing")
        self.assertEqual(q2.awarded_marks, 0)

    def test_hybrid_routes_mcq_deterministic_theory_to_ai(self) -> None:
        client = _client_with_seq(self.tmp, [_mock_marker_response(2, ["p1", "p2"], "full marks")])
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=self._extracted("A", "because gravity and no air resistance"),
            gemini_client=client,
            mcq_only=False,
        )
        q1 = next(q for q in result.questions if q.question_id == "1")
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q1.marker_source, "deterministic")
        self.assertEqual(q1.awarded_marks, 1)
        self.assertEqual(q2.marker_source, "ai")
        self.assertEqual(q2.awarded_marks, 2)
        self.assertEqual(q2.matched_point_ids, ["p1", "p2"])

    def test_hybrid_without_client_raises_config_error(self) -> None:
        with self.assertRaises(ConfigError):
            correct_paper(
                mark_scheme=self.ms,
                extracted_answers=self._extracted("A", "x"),
                gemini_client=None,
                mcq_only=False,
            )

    def test_awarded_marks_clamped_to_question_max(self) -> None:
        # Marker mistakenly returns 5 marks for a 2-mark question — must clamp.
        client = _client_with_seq(self.tmp, [_mock_marker_response(5, ["p1", "p2"], "ok")])
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=self._extracted("A", "answer"),
            gemini_client=client,
            mcq_only=False,
        )
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q2.awarded_marks, 2)  # clamped
```

- [ ] **Step 4: Create `lemely/io/correction_ai.py`**

```python
"""AI-driven marking for non-MCQ questions + hybrid orchestrator for full papers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Iterable

import structlog

from lemely.core.correction import _exam_metadata, _load_mark_scheme, correct_mcq_answers
from lemely.core.loose_schemas import MarkScheme, Question, QuestionType
from lemely.core.schemas import (
    AIMarkResponse,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExtractedAnswer,
    ExtractedAnswers,
    confidence_band_for_score,
)
from lemely.io.gemini import GeminiClient
from lemely.io.prompts.correction_ai import (
    MARKER_SYSTEM_PROMPT,
    VERSION,
    build_marker_user_prompt,
)
from lemely.runtime.errors import ConfigError


def _is_leaf_marked(q: Question) -> bool:
    """Mark only leaf questions with marks > 0. Skip container/zero-mark items."""
    return q.marks > 0 and not q.parts


def _flatten_answers(extracted: ExtractedAnswers | Mapping[str, str]) -> dict[str, str]:
    if isinstance(extracted, ExtractedAnswers):
        return {a.question_id: a.answer for a in extracted.answers}
    return {str(k): str(v) for k, v in extracted.items()}


class AICorrector:
    """Marks individual non-MCQ questions via the shared GeminiClient."""

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def mark_question(self, question: Question, student_answer: str) -> AIMarkResponse:
        return self._client.generate_structured(
            system_prompt=MARKER_SYSTEM_PROMPT,
            user_prompt=build_marker_user_prompt(question, student_answer),
            response_schema=AIMarkResponse,
            prompt_version=VERSION,
            extra_cache_key=f"q={question.id}",
        )


def _build_mcq_corrected(question: Question, answer: str | None) -> CorrectedQuestion:
    """Deterministic MCQ correction for one question; mirrors core.correction logic."""
    expected = question.mcq_answer.value if question.mcq_answer else None
    if answer is None or answer == "":
        return CorrectedQuestion(
            question_id=question.id, awarded_marks=0, maximum_marks=question.marks,
            confidence=ConfidenceBand.LOW, confidence_score=0.0, needs_teacher_review=True,
            student_answer=None, expected_answer=expected,
            topic=question.topic_hint, review_reason="missing answer",
            marker_source="deterministic",
        )
    if answer.upper() not in {"A", "B", "C", "D"}:
        return CorrectedQuestion(
            question_id=question.id, awarded_marks=0, maximum_marks=question.marks,
            confidence=ConfidenceBand.LOW, confidence_score=0.0, needs_teacher_review=True,
            student_answer=answer, expected_answer=expected,
            topic=question.topic_hint, review_reason="invalid MCQ answer",
            marker_source="deterministic",
        )
    is_correct = answer.upper() == expected
    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=question.marks if is_correct else 0,
        maximum_marks=question.marks,
        confidence=ConfidenceBand.HIGH, confidence_score=1.0, needs_teacher_review=False,
        student_answer=answer.upper(), expected_answer=expected,
        topic=question.topic_hint,
        marker_source="deterministic",
    )


def _build_ai_corrected(
    question: Question, student_answer: str, mark: AIMarkResponse,
) -> CorrectedQuestion:
    """Convert AIMarkResponse + question metadata into a CorrectedQuestion."""
    awarded = max(0, min(mark.awarded_marks, question.marks))  # clamp
    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=awarded,
        maximum_marks=question.marks,
        confidence=confidence_band_for_score(mark.confidence),
        confidence_score=mark.confidence,
        needs_teacher_review=mark.confidence < 0.7,
        student_answer=student_answer or None,
        expected_answer=None,
        topic=question.topic_hint,
        marker_source="ai",
        feedback=mark.feedback,
        matched_point_ids=list(mark.matched_point_ids),
    )


def _build_missing_corrected(question: Question, student_answer: str | None) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=0,
        maximum_marks=question.marks,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.0,
        needs_teacher_review=True,
        student_answer=student_answer or None,
        expected_answer=None,
        topic=question.topic_hint,
        review_reason="non-MCQ question not marked (--mcq-only or no AI client)",
        marker_source="missing",
    )


def correct_paper(
    mark_scheme: MarkScheme | str | Mapping[str, object],
    extracted_answers: ExtractedAnswers | Mapping[str, str],
    *,
    gemini_client: GeminiClient | None = None,
    mcq_only: bool = False,
) -> CorrectionResult:
    """Hybrid paper correction: MCQ deterministic, non-MCQ via AICorrector.

    Args:
        mark_scheme: parsed mark scheme.
        extracted_answers: per-question student responses.
        gemini_client: required when paper contains non-MCQ questions and mcq_only is False.
        mcq_only: if True, skip AI; non-MCQ questions get marker_source="missing".

    Raises:
        ConfigError: paper has non-MCQ questions, mcq_only=False, and gemini_client is None.
    """
    scheme = _load_mark_scheme(mark_scheme)
    answers = _flatten_answers(extracted_answers)
    log = structlog.get_logger().bind(component="correct_paper")

    leaves = [q for q in scheme.all_questions_flat() if _is_leaf_marked(q)]
    has_non_mcq = any(q.type != QuestionType.MCQ for q in leaves)

    if has_non_mcq and not mcq_only and gemini_client is None:
        raise ConfigError(
            "This paper contains non-MCQ questions. Pass a GeminiClient or set mcq_only=True."
        )

    ai = AICorrector(gemini_client) if (gemini_client and not mcq_only) else None

    corrected: list[CorrectedQuestion] = []
    for q in leaves:
        student_answer = answers.get(q.id)
        if q.type == QuestionType.MCQ:
            corrected.append(_build_mcq_corrected(q, student_answer))
            continue
        if ai is None:
            corrected.append(_build_missing_corrected(q, student_answer))
            continue
        try:
            mark = ai.mark_question(q, student_answer or "")
        except Exception as exc:  # propagate? for MVP we mark as missing + log
            log.warning("ai_marking_failed", question_id=q.id, error=str(exc))
            cq = _build_missing_corrected(q, student_answer)
            corrected.append(cq.model_copy(update={"review_reason": f"AI marking failed: {exc!s}"}))
            continue
        corrected.append(_build_ai_corrected(q, student_answer or "", mark))

    return CorrectionResult(metadata=_exam_metadata(scheme), questions=corrected)
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_correction_ai.py -v 2>&1 | tail -20
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add lemely/io/prompts/correction_ai.py lemely/io/prompts/__init__.py lemely/io/correction_ai.py tests/test_correction_ai.py
git commit -S -m "feat(io): AICorrector + hybrid correct_paper orchestrator"
```

---

## Task 6: Subject Aggregation

**Files:**
- Create: `lemely/io/subject.py`
- Create: `tests/test_subject.py`

- [ ] **Step 1: Write failing tests** — create `tests/test_subject.py`:

```python
"""Tests for lemely.io.subject.aggregate_subject."""

from __future__ import annotations

import unittest

from lemely.core.schemas import (
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    SubjectResult,
)
from lemely.io.subject import aggregate_subject
from lemely.runtime.errors import UsageError


def _paper(paper_number: int, awarded: int, maximum: int, topic: str = "kinematics") -> CorrectionResult:
    return CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=paper_number,
            paper_variant=1,
            session_month="May/June",
            session_year=2020,
        ),
        questions=[
            CorrectedQuestion(
                question_id=f"p{paper_number}_q1",
                awarded_marks=awarded,
                maximum_marks=maximum,
                confidence=ConfidenceBand.HIGH,
                confidence_score=1.0,
                needs_teacher_review=False,
                topic=topic,
            )
        ],
    )


class AggregateSubjectTests(unittest.TestCase):
    def test_aggregate_three_papers_into_subject_result(self) -> None:
        p2 = _paper(2, 30, 40)
        p4 = _paper(4, 56, 80)
        p6 = _paper(6, 30, 40)
        result = aggregate_subject([p2, p4, p6])
        self.assertIsInstance(result, SubjectResult)
        self.assertEqual(result.subject_code, "0625")
        self.assertEqual(result.awarded_marks, 116)
        self.assertEqual(result.maximum_marks, 160)
        self.assertAlmostEqual(result.percentage, 72.5, places=1)
        self.assertEqual(result.grade, "B")

    def test_mismatched_subject_raises_usage_error(self) -> None:
        p1 = _paper(2, 10, 10)
        p2_meta = ExamMetadata(
            subject_code="9701", paper_number=2, paper_variant=1,
            session_month="May/June", session_year=2020,
        )
        p2 = CorrectionResult(metadata=p2_meta, questions=p1.questions)
        with self.assertRaises(UsageError):
            aggregate_subject([p1, p2])

    def test_weaknesses_aggregated_across_papers(self) -> None:
        p2 = _paper(2, 0, 10, topic="dynamics")
        p4 = _paper(4, 5, 10, topic="dynamics")
        result = aggregate_subject([p2, p4])
        topics = {w.topic for w in result.weaknesses.weak_areas}
        self.assertIn("dynamics", topics)

    def test_empty_list_raises_usage_error(self) -> None:
        with self.assertRaises(UsageError):
            aggregate_subject([])
```

- [ ] **Step 2: Create `lemely/io/subject.py`**

```python
"""Subject-level aggregation: combine multiple per-paper CorrectionResults into a SubjectResult."""

from __future__ import annotations

from collections.abc import Sequence

from lemely.core.analytics import summarize_weaknesses
from lemely.core.schemas import (
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    SubjectResult,
    WeakArea,
    WeaknessReport,
)
from lemely.runtime.errors import UsageError


def _virtual_combined_correction(papers: Sequence[CorrectionResult]) -> CorrectionResult:
    """Synthesise a single CorrectionResult whose questions list is the union of all papers'.

    Used only for feeding summarize_weaknesses() across the subject.
    """
    first_meta = papers[0].metadata
    all_qs: list[CorrectedQuestion] = []
    for p in papers:
        for q in p.questions:
            # Prefix question_id with paper number to keep ids unique across papers
            prefixed_id = f"p{p.metadata.paper_number}{p.metadata.paper_variant}_{q.question_id}"
            all_qs.append(q.model_copy(update={"question_id": prefixed_id}))
    return CorrectionResult(metadata=first_meta, questions=all_qs)


def aggregate_subject(papers: Sequence[CorrectionResult]) -> SubjectResult:
    """Combine per-paper corrections into a single SubjectResult.

    Args:
        papers: 1+ CorrectionResults that must all share subject_code + session_month + session_year.

    Raises:
        UsageError: empty list or mismatched subject/session across papers.
    """
    if not papers:
        raise UsageError("aggregate_subject requires at least one CorrectionResult.")

    ref = papers[0].metadata
    for p in papers[1:]:
        m = p.metadata
        if (m.subject_code, m.session_month, m.session_year) != (
            ref.subject_code, ref.session_month, ref.session_year,
        ):
            raise UsageError(
                f"Paper subject/session mismatch: "
                f"{m.subject_code}/{m.session_month}/{m.session_year} "
                f"vs reference {ref.subject_code}/{ref.session_month}/{ref.session_year}"
            )

    combined = _virtual_combined_correction(papers)
    weaknesses = summarize_weaknesses(combined)

    return SubjectResult(
        subject_code=ref.subject_code,
        session_month=ref.session_month,
        session_year=ref.session_year,
        paper_results=list(papers),
        weaknesses=weaknesses,
    )
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_subject.py -v 2>&1 | tail -15
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add lemely/io/subject.py tests/test_subject.py
git commit -S -m "feat(io): aggregate_subject combines per-paper corrections into SubjectResult"
```

---

## Task 7: Renderers (extracted_answers, subject_result, correction marker_source)

**Files:**
- Modify: `lemely/app/renderers.py`
- Modify: `tests/test_renderers.py`

- [ ] **Step 1: Add failing tests** to `tests/test_renderers.py`:

```python
from lemely.core.schemas import (
    ExtractedAnswer,
    ExtractedAnswers,
    SubjectResult,
    WeaknessReport,
)


class ExtractedAnswersRendererTests(unittest.TestCase):
    def test_renders_low_confidence_highlighted(self) -> None:
        ea = ExtractedAnswers(
            paper_id="0625_test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.99),
                ExtractedAnswer(question_id="2(a)", answer="osmosis", confidence=0.6),
            ],
        )
        out = _render_to_str(renderers.render_extracted_answers(ea))
        self.assertIn("1", out)
        self.assertIn("2(a)", out)
        self.assertIn("osmosis", out)


class SubjectResultRendererTests(unittest.TestCase):
    def test_renders_subject_grade_and_papers(self) -> None:
        meta = ExamMetadata(
            subject_code="0625", paper_number=2, paper_variant=1,
            session_month="May/June", session_year=2020,
        )
        paper = CorrectionResult(metadata=meta, questions=[
            CorrectedQuestion(
                question_id="q1", awarded_marks=8, maximum_marks=10,
                confidence=ConfidenceBand.HIGH, confidence_score=1.0,
                needs_teacher_review=False,
            ),
        ])
        sr = SubjectResult(
            subject_code="0625", session_month="May/June", session_year=2020,
            paper_results=[paper], weaknesses=WeaknessReport(weak_areas=[]),
        )
        out = _render_to_str(renderers.render_subject_result(sr))
        self.assertIn("0625", out)
        self.assertIn("80", out)  # 80% or 80/10 etc.
```

- [ ] **Step 2: Update `lemely/app/renderers.py`**

Add `ExtractedAnswers` and `SubjectResult` to the `TYPE_CHECKING` import block.

Add the new renderers and update `render_correction` to surface `marker_source`. Insert after `render_batch_result`:

```python
def render_extracted_answers(result: ExtractedAnswers) -> Table:
    t = Table(
        title=f"Extracted answers — {escape(result.paper_id)}",
        box=box.SIMPLE,
    )
    t.add_column("Question", justify="left")
    t.add_column("Answer")
    t.add_column("Confidence", justify="right")
    t.add_column("Review?")
    for a in result.answers:
        low = a.confidence < 0.70
        style = "yellow" if low else "green"
        t.add_row(
            escape(a.question_id),
            f"[{style}]{escape(a.answer or '—')}[/]",
            f"{a.confidence:.0%}",
            "yes" if low else "",
        )
    return t


def render_subject_result(result: SubjectResult) -> tuple[Table, Table, Table]:
    """Returns (subject banner, per-paper breakdown, weakness table)."""
    banner = Table(
        title=f"Subject — {escape(result.subject_code)} "
        f"{escape(result.session_month)} {result.session_year or 'Specimen'}",
        box=box.SIMPLE,
    )
    banner.add_column("metric")
    banner.add_column("value")
    banner.add_row("Awarded / Max", f"{result.awarded_marks}/{result.maximum_marks}")
    banner.add_row("Percentage", f"{result.percentage:.1f}%")
    banner.add_row("Subject grade", escape(result.grade))
    banner.add_row("Review?", "yes" if result.needs_teacher_review else "no")

    papers = Table(title="Per-paper breakdown", box=box.SIMPLE)
    papers.add_column("Paper", justify="right")
    papers.add_column("Awarded", justify="right")
    papers.add_column("Max", justify="right")
    papers.add_column("Percentage", justify="right")
    for p in result.paper_results:
        pct = (p.awarded_marks / p.maximum_marks * 100.0) if p.maximum_marks else 0.0
        papers.add_row(
            f"{p.metadata.paper_number}{p.metadata.paper_variant}",
            str(p.awarded_marks),
            str(p.maximum_marks),
            f"{pct:.1f}%",
        )

    return banner, papers, render_weakness_report(result.weaknesses)
```

Update `render_correction` to show `marker_source` — modify the table to add a "Marker" column. Replace the function:

```python
def render_correction(result: CorrectionResult) -> Table:
    meta = result.metadata
    paper_id = (
        f"{escape(meta.subject_code)}/{meta.paper_number}{meta.paper_variant}"
        f" {escape(meta.session_month)}{f' {meta.session_year}' if meta.session_year else ''}"
    )
    t = Table(
        title=f"Correction — {paper_id} — {result.awarded_marks}/{result.maximum_marks}",
        box=box.SIMPLE,
    )
    t.add_column("Q", justify="right")
    t.add_column("Student")
    t.add_column("Expected")
    t.add_column("Marks", justify="right")
    t.add_column("Topic")
    t.add_column("Confidence")
    t.add_column("Marker")
    t.add_column("Review?")
    marker_glyph = {"deterministic": "✓", "ai": "AI", "missing": "—"}
    for q in result.questions:
        marks = f"{q.awarded_marks}/{q.maximum_marks}"
        style = "green" if q.awarded_marks == q.maximum_marks else "red"
        review = "yes" if q.needs_teacher_review else ""
        t.add_row(
            escape(q.question_id),
            escape(q.student_answer or "—"),
            escape(q.expected_answer or "—"),
            f"[{style}]{marks}[/]",
            escape(q.topic or "—"),
            q.confidence.value,
            marker_glyph.get(q.marker_source, "?"),
            review,
        )
    return t
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_renderers.py -v 2>&1 | tail -15
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add lemely/app/renderers.py tests/test_renderers.py
git commit -S -m "feat(app): renderers for ExtractedAnswers, SubjectResult; marker_source column"
```

---

## Task 8: CLI Subcommands — `extract-answers`, `correct-paper` (rewrite), `aggregate-subject`

**Files:**
- Modify: `lemely/app/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests** — add to `tests/test_cli.py`:

```python
from unittest.mock import MagicMock, patch


def test_correct_paper_mcq_only_works_without_api_key():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        scheme_path = root / "0625_m20_ms_12.json"
        scheme_path.write_text(real_mcq_mark_scheme_text(), "utf-8")
        answers = '{"1": "A", "2": "B"}'
        # mcq paper, so --mcq-only path should succeed without Gemini
        exit_code, payload = run_cli(
            "correct-paper",
            "--mark-scheme", str(scheme_path),
            "--answers", answers,
            "--mcq-only",
        )
    assert exit_code == 0
    assert "correction" in payload


def test_extract_answers_requires_existing_scan():
    with tempfile.TemporaryDirectory() as tmp:
        scheme = Path(tmp) / "0625_m20_ms_12.json"
        scheme.write_text(real_mcq_mark_scheme_text(), "utf-8")
        exit_code = main([
            "--json", "extract-answers",
            "--mark-scheme", str(scheme),
            "--scan", str(Path(tmp) / "nonexistent.png"),
        ])
    assert exit_code != 0


def test_aggregate_subject_combines_three_papers():
    with tempfile.TemporaryDirectory() as tmp:
        # Build three minimal correction JSON files for the same subject+session
        from lemely.core.schemas import (
            ConfidenceBand, CorrectedQuestion, CorrectionResult, ExamMetadata,
        )
        paths = []
        for paper_num in (2, 4, 6):
            meta = ExamMetadata(
                subject_code="0625", paper_number=paper_num, paper_variant=1,
                session_month="May/June", session_year=2020,
            )
            cr = CorrectionResult(metadata=meta, questions=[
                CorrectedQuestion(
                    question_id=f"q{paper_num}", awarded_marks=5, maximum_marks=10,
                    confidence=ConfidenceBand.HIGH, confidence_score=1.0,
                    needs_teacher_review=False, topic="kinematics",
                ),
            ])
            p = Path(tmp) / f"paper{paper_num}.json"
            p.write_text(cr.model_dump_json(indent=2), "utf-8")
            paths.append(str(p))

        exit_code, payload = run_cli("aggregate-subject", *paths)
    assert exit_code == 0
    assert payload["subject_code"] == "0625"
    assert payload["awarded_marks"] == 15
    assert payload["maximum_marks"] == 30
```

- [ ] **Step 2: Update imports in `lemely/app/cli.py`**

Replace the schemas import block with the expanded set including the new schemas:

```python
from lemely.core.schemas import (
    AccuracyReport,
    BatchParseResult,
    CorrectionResult,
    CostEstimate,
    ExtractedAnswers,
    GradePrediction,
    QuizPayload,
    SubjectResult,
    WeaknessReport,
)
```

- [ ] **Step 3: Update `_print_result` to handle new types**

Add to the dispatch chain (after `BatchParseResult`):
```python
    elif isinstance(payload, ExtractedAnswers):
        console.print(renderers.render_extracted_answers(payload))
    elif isinstance(payload, SubjectResult):
        for table in renderers.render_subject_result(payload):
            console.print(table)
```

- [ ] **Step 4: Replace `correct-paper` command**

```python
@cli.command("correct-paper")
@click.option("--mark-scheme", "mark_scheme", required=True,
              type=click.Path(exists=True, dir_okay=False))
@click.option("--answers", required=True,
              help="Answer JSON object, ExtractedAnswers JSON file path, or simple text.")
@click.option("--mcq-only", is_flag=True,
              help="Skip AI marking for non-MCQ questions (they'll be marker_source=missing).")
@click.option("--on-error", type=click.Choice(["continue", "fail"]),
              default="fail", show_default=True)
@click.pass_context
def correct_paper_cmd(
    ctx: click.Context,
    mark_scheme: str,
    answers: str,
    mcq_only: bool,
    on_error: str,
) -> None:
    import json as _json

    from lemely.core.loose_schemas import MarkScheme
    from lemely.core.schemas import ExtractedAnswers
    from lemely.io.correction_ai import correct_paper as hybrid_correct_paper
    from lemely.io.gemini import GeminiClient

    ms = MarkScheme.model_validate(_load_json_file(mark_scheme))

    payload = _read_text_or_value(answers)
    # Try ExtractedAnswers JSON first; fall back to simple {qid:answer} dict.
    try:
        ea = ExtractedAnswers.model_validate_json(payload)
        extracted: object = ea
    except Exception:
        try:
            ea_dict = _json.loads(payload)
            if isinstance(ea_dict, dict):
                extracted = ea_dict
            else:
                raise ValueError("Answers JSON must be an object.")
        except Exception:
            from lemely.core.correction import parse_answer_input
            extracted = parse_answer_input(payload)

    settings = _get_settings(ctx)
    client = None if mcq_only else GeminiClient(settings)

    correction = hybrid_correct_paper(
        mark_scheme=ms,
        extracted_answers=extracted,  # type: ignore[arg-type]
        gemini_client=client,
        mcq_only=mcq_only,
    )
    from lemely.core.analytics import predict_grade, summarize_weaknesses
    report = AccuracyReport(
        correction=correction,
        weaknesses=summarize_weaknesses(correction),
        grade_prediction=predict_grade(correction),
    )
    _print_result(ctx, report)
```

- [ ] **Step 5: Add `extract-answers` command**

Insert after `parse_mark_schemes_cmd`:

```python
@cli.command("extract-answers")
@click.option("--mark-scheme", "mark_scheme", required=True,
              type=click.Path(exists=True, dir_okay=False))
@click.option("--scan", required=True, type=click.Path(exists=True, dir_okay=False),
              help="Scanned student paper (PDF, PNG, or JPG).")
@click.option("--on-error", type=click.Choice(["continue", "fail"]),
              default="fail", show_default=True)
@click.pass_context
def extract_answers_cmd(
    ctx: click.Context, mark_scheme: str, scan: str, on_error: str,
) -> None:
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.answer_extraction import GeminiAnswerExtractor
    from lemely.io.gemini import GeminiClient

    settings = _get_settings(ctx)
    ms = MarkScheme.model_validate(_load_json_file(mark_scheme))
    extractor = GeminiAnswerExtractor(GeminiClient(settings))
    result = extractor(scan_path=Path(scan), mark_scheme=ms)
    _print_result(ctx, result)
```

- [ ] **Step 6: Add `aggregate-subject` command**

Insert after `extract_answers_cmd`:

```python
@cli.command("aggregate-subject")
@click.argument("correction_jsons", nargs=-1, required=True,
                type=click.Path(exists=True, dir_okay=False))
@click.option("--on-error", type=click.Choice(["continue", "fail"]),
              default="fail", show_default=True)
@click.pass_context
def aggregate_subject_cmd(
    ctx: click.Context, correction_jsons: tuple[str, ...], on_error: str,
) -> None:
    from lemely.io.subject import aggregate_subject

    papers = [
        CorrectionResult.model_validate(_load_json_file(p))
        for p in correction_jsons
    ]
    _print_result(ctx, aggregate_subject(papers))
```

- [ ] **Step 7: Add `ui` command if not present** (or update it)

Replace any existing `ui` command with:

```python
@cli.command("ui")
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
@click.pass_context
def ui_cmd(ctx: click.Context, host: str | None, port: int | None) -> None:
    from lemely.app.gradio_app import launch
    from lemely.runtime.config import GradioSettings

    settings = _get_settings(ctx)
    if host is not None or port is not None:
        cur = settings.gradio
        settings = settings.model_copy(update={"gradio": GradioSettings(
            host=host or cur.host, port=port or cur.port,
            max_file_size_mb=cur.max_file_size_mb,
        )})
    launch(settings)
```

- [ ] **Step 8: Run tests**

```bash
python -m pytest tests/test_cli.py -v 2>&1 | tail -25
```

Expected: all pass. If the existing `test_correct_paper_outputs_accuracy_report` test fails because it doesn't pass `--mcq-only`, update it to add the flag (the existing fixture is an MCQ-only paper but the new `correct-paper` defaults to hybrid which requires a Gemini client). Add `"--mcq-only"` to that test invocation.

- [ ] **Step 9: Commit**

```bash
git add lemely/app/cli.py tests/test_cli.py
git commit -S -m "feat(cli): add extract-answers, aggregate-subject; rewrite correct-paper for hybrid"
```

---

## Task 9: Gradio Callbacks (Tab 2 + Tab 3)

**Files:**
- Create: `lemely/app/gradio_callbacks.py`
- Modify: `tests/test_gradio_app.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_gradio_app.py`:

```python
"""Tests for gradio_callbacks (no gradio import needed)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from lemely.app.gradio_callbacks import (
    build_mark_scheme_dropdown_choices,
    build_subject_session_choices,
    parse_mark_scheme_path_from_label,
)


class _IsolatedEnv:
    def __enter__(self) -> _IsolatedEnv:
        self._snap = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("LEMELY_"):
                del os.environ[k]
        return self

    def __exit__(self, *_: object) -> None:
        os.environ.clear()
        os.environ.update(self._snap)


REAL_MS = Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.json")


class GradioCallbackTests(unittest.TestCase):
    def test_dropdown_choices_built_from_sources_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4")
            (root / "0625_m20_ms_12.json").write_text(
                REAL_MS.read_text(encoding="utf-8"), "utf-8",
            )
            choices = build_mark_scheme_dropdown_choices(root)
        self.assertIsInstance(choices, list)
        self.assertTrue(len(choices) > 0)
        path = parse_mark_scheme_path_from_label(choices[0])
        self.assertTrue(str(path).endswith(".json"))

    def test_subject_session_choices_groups_paper_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "0625" / "MayJune_2020").mkdir(parents=True)
            (out / "0625" / "MayJune_2020" / "0625_MayJune_2020_p21__2026-05-22-100000").mkdir()
            (out / "0625" / "MayJune_2020" / "0625_MayJune_2020_p21__2026-05-22-100000" / "accuracy_report.json").write_text("{}", "utf-8")
            choices = build_subject_session_choices(out)
        self.assertEqual(len(choices), 1)
        self.assertIn("0625", choices[0])
```

- [ ] **Step 2: Create `lemely/app/gradio_callbacks.py`**

```python
"""Pure callback functions for Gradio tabs. No gradio imports — testable standalone."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import (
    AccuracyReport,
    CorrectionResult,
    ExtractedAnswer,
    ExtractedAnswers,
)
from lemely.io.mark_schemes import index_source_library


# ----------------------------------------------------------------------
# Tab 2 — Correct a paper
# ----------------------------------------------------------------------

def build_mark_scheme_dropdown_choices(sources_dir: Path) -> list[str]:
    """Return dropdown labels for mark schemes that have a parsed JSON file."""
    choices: list[str] = []
    for entry in index_source_library(sources_dir):
        json_path = entry.source_path.with_suffix(".json")
        if not json_path.exists():
            continue
        m = entry.metadata
        year = str(m.session_year) if m.session_year else "Specimen"
        label = (
            f"{m.subject_code}/{m.paper_number}{m.paper_variant} "
            f"{m.session_month} {year} — {json_path}"
        )
        choices.append(label)
    return choices


def parse_mark_scheme_path_from_label(label: str) -> Path:
    return Path(label.rsplit(" — ", 1)[-1].strip())


def extracted_to_table_rows(extracted: ExtractedAnswers) -> list[list[str]]:
    """Convert ExtractedAnswers into editable Dataframe rows."""
    return [
        [a.question_id, a.answer, f"{a.confidence:.0%}"]
        for a in extracted.answers
    ]


def rows_to_reviewed_answers_json(rows: list[list[str]]) -> str:
    """Take edited Dataframe rows and produce {question_id: answer} JSON."""
    out: dict[str, str] = {}
    for row in rows:
        if not row or not row[0]:
            continue
        out[str(row[0])] = str(row[1]) if len(row) > 1 else ""
    return json.dumps(out)


def save_correction_artifacts(
    output_dir: Path,
    mark_scheme_label: str,
    extracted_answers_json: str,
    reviewed_answers_json: str,
    accuracy_report_dict: dict[str, Any],
) -> Path:
    """Persist extracted/reviewed/report files under output_dir/<subject>/<session>/<paper>__<ts>/."""
    report = AccuracyReport.model_validate(accuracy_report_dict)
    meta = report.correction.metadata
    session = meta.session_month.replace("/", "")
    year = str(meta.session_year) if meta.session_year else "specimen"
    paper_code = f"{meta.subject_code}_{session}_{year}_p{meta.paper_number}{meta.paper_variant}"
    ts = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    session_dir = output_dir / meta.subject_code / f"{session}_{year}" / f"{paper_code}__{ts}"
    session_dir.mkdir(parents=True, exist_ok=True)

    (session_dir / "extracted_answers.json").write_text(extracted_answers_json, encoding="utf-8")
    (session_dir / "reviewed_answers.json").write_text(reviewed_answers_json, encoding="utf-8")
    (session_dir / "accuracy_report.json").write_text(
        json.dumps(accuracy_report_dict, indent=2), encoding="utf-8",
    )
    return session_dir


# ----------------------------------------------------------------------
# Tab 3 — Subject result
# ----------------------------------------------------------------------

def build_subject_session_choices(output_dir: Path) -> list[str]:
    """Discover subject_code/session pairs from output_dir/<subject>/<session>/ structure."""
    choices: list[str] = []
    if not output_dir.exists():
        return choices
    for subject_dir in sorted(output_dir.iterdir()):
        if not subject_dir.is_dir() or not subject_dir.name.isdigit():
            continue
        for session_dir in sorted(subject_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            paper_dirs = [p for p in session_dir.iterdir() if p.is_dir()]
            if not paper_dirs:
                continue
            choices.append(f"{subject_dir.name} / {session_dir.name} ({len(paper_dirs)} papers)")
    return choices


def load_papers_for_subject_session(
    output_dir: Path, subject_session_label: str,
) -> list[CorrectionResult]:
    """Load every accuracy_report.json under a given subject_code / session label."""
    subject_code, rest = subject_session_label.split(" / ", 1)
    session_name = rest.split(" (", 1)[0]
    session_dir = output_dir / subject_code / session_name
    papers: list[CorrectionResult] = []
    for paper_dir in sorted(session_dir.iterdir()):
        report_path = paper_dir / "accuracy_report.json"
        if not report_path.exists():
            continue
        report = AccuracyReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        papers.append(report.correction)
    return papers
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_gradio_app.py -v 2>&1 | tail -20
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add lemely/app/gradio_callbacks.py tests/test_gradio_app.py
git commit -S -m "feat(app): gradio_callbacks for Tab 2 + Tab 3"
```

---

## Task 10: Reshape Gradio App — Multi-Paper Tab 2 + Subject Tab 3

**Files:**
- Modify: `lemely/app/gradio_app.py`

This file is excluded from coverage, so no automated tests required. Smoke test by launching locally.

- [ ] **Step 1: Replace `lemely/app/gradio_app.py`**

```python
"""Gradio UI — 6 tabs. Tab 2 (Correct a Paper) and Tab 3 (Subject Result) are live."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_app(settings: Any = None) -> Any:
    try:
        import gradio as gr
    except ImportError as exc:
        raise RuntimeError("gradio is not installed. Run: pip install 'lemely[ui]'") from exc

    from lemely.app.gradio_callbacks import (
        build_mark_scheme_dropdown_choices,
        build_subject_session_choices,
        extracted_to_table_rows,
        load_papers_for_subject_session,
        parse_mark_scheme_path_from_label,
        rows_to_reviewed_answers_json,
        save_correction_artifacts,
    )
    from lemely.core.analytics import predict_grade, summarize_weaknesses
    from lemely.core.loose_schemas import MarkScheme
    from lemely.core.schemas import AccuracyReport, ExtractedAnswers
    from lemely.io.answer_extraction import GeminiAnswerExtractor
    from lemely.io.correction_ai import correct_paper as hybrid_correct_paper
    from lemely.io.gemini import GeminiClient
    from lemely.io.subject import aggregate_subject
    from lemely.runtime.config import load_settings as _load_settings

    if settings is None:
        settings = _load_settings()

    # --- Tab 2 callbacks ------------------------------------------------
    def _ms_choices() -> list[str]:
        return build_mark_scheme_dropdown_choices(settings.paths.sources_dir)

    def _extract(ms_label: str, scan_file: str) -> tuple[list[list[str]], str]:
        ms_path = parse_mark_scheme_path_from_label(ms_label)
        ms = MarkScheme.model_validate_json(ms_path.read_text(encoding="utf-8"))
        extractor = GeminiAnswerExtractor(GeminiClient(settings))
        result = extractor(scan_path=Path(scan_file), mark_scheme=ms)
        return extracted_to_table_rows(result), result.model_dump_json(indent=2)

    def _grade(
        ms_label: str, table_data: list[list[str]], mcq_only: bool,
    ) -> dict[str, Any]:
        ms_path = parse_mark_scheme_path_from_label(ms_label)
        ms = MarkScheme.model_validate_json(ms_path.read_text(encoding="utf-8"))
        reviewed = json.loads(rows_to_reviewed_answers_json(table_data))
        client = None if mcq_only else GeminiClient(settings)
        correction = hybrid_correct_paper(
            mark_scheme=ms, extracted_answers=reviewed,
            gemini_client=client, mcq_only=mcq_only,
        )
        report = AccuracyReport(
            correction=correction,
            weaknesses=summarize_weaknesses(correction),
            grade_prediction=predict_grade(correction),
        )
        return report.model_dump(mode="json")

    def _save(
        ms_label: str,
        extracted_json: str,
        table_data: list[list[str]],
        report: dict[str, Any],
    ) -> str:
        reviewed_json = rows_to_reviewed_answers_json(table_data)
        session_dir = save_correction_artifacts(
            output_dir=settings.paths.output_dir,
            mark_scheme_label=ms_label,
            extracted_answers_json=extracted_json or "{}",
            reviewed_answers_json=reviewed_json,
            accuracy_report_dict=report,
        )
        return f"Saved to {session_dir}"

    # --- Tab 3 callbacks ------------------------------------------------
    def _subject_choices() -> list[str]:
        return build_subject_session_choices(settings.paths.output_dir)

    def _aggregate(subject_session_label: str) -> dict[str, Any]:
        papers = load_papers_for_subject_session(settings.paths.output_dir, subject_session_label)
        result = aggregate_subject(papers)
        return result.model_dump(mode="json")

    with gr.Blocks(title="Lemely Assessment Tool") as demo:
        gr.Markdown("# Lemely Assessment Tool")

        # ------------------------------------------------------------------
        # Tab 1: Library (stub)
        # ------------------------------------------------------------------
        with gr.Tab("Library"):
            gr.Markdown("Browse / parse mark schemes. *(Full library tab — Phase 3.)*")
            gr.Textbox(label="Sources directory",
                       value=str(settings.paths.sources_dir), interactive=False)

        # ------------------------------------------------------------------
        # Tab 2: Correct a Paper (live)
        # ------------------------------------------------------------------
        with gr.Tab("Correct a Paper"):
            gr.Markdown(
                "Upload a scanned paper, extract answers with AI, review, then grade.\n"
                "MCQ questions are graded deterministically; theory / ATP questions are AI-marked."
            )
            ms_dropdown = gr.Dropdown(label="Mark scheme", choices=_ms_choices(), interactive=True)
            refresh = gr.Button("↻ Refresh", size="sm")
            refresh.click(fn=_ms_choices, inputs=[], outputs=[ms_dropdown])

            scan_upload = gr.File(
                label="Scanned student paper (PDF / PNG / JPG)",
                file_types=[".pdf", ".png", ".jpg", ".jpeg"],
            )
            extract_btn = gr.Button("Extract answers", variant="primary")

            answers_table = gr.Dataframe(
                headers=["Question", "Answer", "Confidence"],
                datatype=["str", "str", "str"],
                col_count=(3, "fixed"),
                interactive=True,
                label="Extracted answers — edit before grading",
            )
            extracted_json_state = gr.State("")
            extract_btn.click(fn=_extract,
                              inputs=[ms_dropdown, scan_upload],
                              outputs=[answers_table, extracted_json_state])

            mcq_only_cb = gr.Checkbox(label="MCQ-only (skip AI marking for non-MCQ questions)",
                                       value=False)
            grade_btn = gr.Button("Grade", variant="secondary")
            report_out = gr.JSON(label="Accuracy report")
            grade_btn.click(fn=_grade,
                            inputs=[ms_dropdown, answers_table, mcq_only_cb],
                            outputs=[report_out])

            save_btn = gr.Button("Save result")
            save_status = gr.Textbox(label="Save status", interactive=False)
            save_btn.click(fn=_save,
                           inputs=[ms_dropdown, extracted_json_state, answers_table, report_out],
                           outputs=[save_status])

        # ------------------------------------------------------------------
        # Tab 3: Subject Result (live)
        # ------------------------------------------------------------------
        with gr.Tab("Subject Result"):
            gr.Markdown(
                "Combine all paper corrections for a subject + session into a single grade."
            )
            subject_dropdown = gr.Dropdown(
                label="Subject + session", choices=_subject_choices(), interactive=True,
            )
            refresh_subj = gr.Button("↻ Refresh", size="sm")
            refresh_subj.click(fn=_subject_choices, inputs=[], outputs=[subject_dropdown])

            aggregate_btn = gr.Button("Aggregate subject grade", variant="primary")
            subject_out = gr.JSON(label="Subject result")
            aggregate_btn.click(fn=_aggregate, inputs=[subject_dropdown], outputs=[subject_out])

        # ------------------------------------------------------------------
        # Tab 4: Past Results (stub)
        # ------------------------------------------------------------------
        with gr.Tab("Past Results"):
            gr.Markdown("*(Past results browser — Phase 3.)*")

        # ------------------------------------------------------------------
        # Tab 5: Quiz (stub)
        # ------------------------------------------------------------------
        with gr.Tab("Quiz"):
            gr.Markdown("*(Interactive quiz — Phase 3.)*")

        # ------------------------------------------------------------------
        # Tab 6: Settings
        # ------------------------------------------------------------------
        with gr.Tab("Settings"):
            gr.Markdown("**Effective configuration** (read-only)")
            gr.Dataframe(
                headers=["Setting", "Value"],
                value=[
                    ["gradio.host", settings.gradio.host],
                    ["gradio.port", str(settings.gradio.port)],
                    ["gradio.max_file_size_mb", str(settings.gradio.max_file_size_mb)],
                    ["paths.sources_dir", str(settings.paths.sources_dir)],
                    ["paths.output_dir", str(settings.paths.output_dir)],
                    ["paths.cache_dir", str(settings.paths.cache_dir)],
                    ["logging.level", settings.logging.level],
                    ["gemini.model", settings.gemini.model],
                    ["gemini_api_key", "***" if settings.gemini_api_key else "(not set)"],
                ],
                interactive=False,
            )

    return demo


def launch(settings: Any = None) -> None:
    from lemely.runtime.config import load_settings as _load_settings

    if settings is None:
        settings = _load_settings()

    import structlog

    log = structlog.get_logger().bind(component="gradio")
    if settings.gradio.host != "127.0.0.1":
        log.warning("gradio_non_localhost", host=settings.gradio.host,
                    message="Exposing Gradio outside localhost — ensure this is intentional.")

    build_app(settings).launch(
        server_name=settings.gradio.host,
        server_port=settings.gradio.port,
        share=False,
        show_api=False,
        max_file_size=f"{settings.gradio.max_file_size_mb}mb",
        allowed_paths=[str(settings.paths.sources_dir.resolve())],
    )
```

- [ ] **Step 2: Commit**

```bash
git add lemely/app/gradio_app.py
git commit -S -m "feat(ui): 6-tab Gradio app with live Tab 2 (Correct) and Tab 3 (Subject)"
```

---

## Task 11: Final Pass — Tests, Mypy, Lint, Import-Linter

- [ ] **Step 1: Run the full test suite**

```bash
python -m pytest -x -q 2>&1 | tail -40
```

Common fix-ups likely needed:
- `tests/test_cli.py::test_correct_paper_outputs_accuracy_report` — add `"--mcq-only"` to the args, since the default `correct-paper` now needs a GeminiClient unless we force MCQ-only mode.
- `tests/test_cli_json_contract.py` — review if `correct-paper` is exercised; if so, ensure `--mcq-only` is passed or the mark scheme is MCQ-only.
- `tests/test_cli_doctor.py` — should still pass; doctor is independent.
- `tests/test_settings_example_drift.py` — should still pass; we haven't changed `Settings`.

- [ ] **Step 2: Run import-linter**

```bash
lint-imports 2>&1
```

Expected: contracts pass. `lemely.io.correction_ai` imports from `lemely.core.correction` — allowed (io → core). `lemely.io.subject` imports from `lemely.core.analytics` — allowed.

- [ ] **Step 3: Run mypy**

```bash
mypy lemely 2>&1 | tail -30
```

If errors appear:
- For `Any` in tenacity / google.genai contexts — ensure module is in the `disallow_any_explicit = false` override (Task 2 Step 1 did this).
- For `model_copy` nested updates — pass full nested model instances rather than partial dicts.

- [ ] **Step 4: Run ruff**

```bash
ruff check lemely tests && ruff format --check lemely tests 2>&1 | tail -15
```

Fix any reported issues. Use `ruff check --fix` for auto-fixable; format with `ruff format`.

- [ ] **Step 5: Check coverage threshold**

```bash
python -m pytest --cov=lemely --cov-report=term-missing -q 2>&1 | grep -E "TOTAL|FAIL" | tail -5
```

Expected: ≥ 70% (project threshold). If below, add tests to whichever module dropped (most likely `gemini.py` if test_gemini_client failed, or `correction_ai.py`).

- [ ] **Step 6: Final commit (if any fixes needed)**

```bash
git status
# stage any fixes
git commit -S -m "fix: resolve mypy / ruff / test failures from Phase 2 integration"
```

---

## Self-Review Checklist

**Spec coverage (revised spec):**
- [x] Shared GeminiClient with retry/cache/cost-guard/logging → Task 2
- [x] `ExtractedAnswer` / `ExtractedAnswers` schemas → Task 1
- [x] `AIMarkResponse` schema → Task 1
- [x] `SubjectResult` schema → Task 1
- [x] `CorrectedQuestion` extended with `marker_source`, `feedback`, `matched_point_ids` → Task 1
- [x] Paper-type-agnostic extractor (MCQ + theory + ATP) → Task 4
- [x] AI rubric marker for non-MCQ → Task 5
- [x] Hybrid `correct_paper` orchestrator → Task 5
- [x] Subject aggregation → Task 6
- [x] CLI: `extract-answers`, `aggregate-subject`, hybrid `correct-paper` (with `--mcq-only`) → Task 8
- [x] Renderers for `ExtractedAnswers`, `SubjectResult`, `marker_source` column → Task 7
- [x] Gradio Tab 2 (paper-type-aware) + Tab 3 (subject) → Tasks 9, 10
- [x] parsers.py refactored to use GeminiClient → Task 3
- [x] Prompt VERSION constants for cache invalidation → Tasks 3, 4, 5

**Out of scope (Phase 3+):** quiz schemas, quiz generation, quiz marking, Past Results browser interactivity, Library bulk-parse UI, HTML report rendering.

**Type consistency check:**
- `GeminiClient.generate_structured` signature: `(system_prompt, user_prompt, file_paths, response_schema, prompt_version, model, extra_cache_key)` — same in Tasks 2, 4, 5
- `correct_paper(mark_scheme, extracted_answers, *, gemini_client, mcq_only)` — same in Tasks 5, 8, 10
- `aggregate_subject(papers: Sequence[CorrectionResult]) -> SubjectResult` — same in Tasks 6, 8, 10
- `CorrectedQuestion.marker_source: Literal["deterministic","ai","missing"]` — same in Tasks 1, 5, 7, 8

**Placeholders:** none — every step has the exact code an engineer needs.
