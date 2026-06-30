# Deterministic Mark Scheme Parser

**Date:** 2026-06-30  
**Status:** Approved for implementation

## Context

Mark scheme PDFs are currently parsed entirely by Gemini (`GeminiMarkSchemeParser` in
`lemely/io/parsers.py`). Each call incurs API cost, latency, and risks transient failures
(503s, rate limits) already handled by the `transient_failed` batch status. The existing
prompt (`lemely/io/prompts/mark_scheme_parsing.py`) is 11 sections long and relies on the
model to resolve table structure, merged cells, and question hierarchy — tasks that are
fully deterministic given a structured PDF.

The goal is a `DeterministicMarkSchemeParser` that handles MCQ and point-based theory
papers using `pdfplumber` alone (no AI), producing the same `MarkScheme` schema. Papers
containing levels-based, indicative-content, or other complex question types raise
`ParseError` and fall back to Gemini via a `ChainedMarkSchemeParser` wrapper.

Primary gains: eliminate API cost for the majority of papers; remove network dependency;
reduce per-PDF latency from seconds to milliseconds.

---

## Architecture

Single library (`pdfplumber`) handles all three stages:

```
PDF path
  │
  └─ pdfplumber
       ├─ Page 0 (cover)       → text extraction → metadata fields
       ├─ Pages 1–3 (GMP)      → text extraction → marking principles
       └─ Question table pages → table extraction → list[Question]
```

`DeterministicMarkSchemeParser.__call__(pdf_path) -> MarkScheme`

- Uses `pdfplumber.open()` for the entire document.
- `page.extract_text()` for unstructured cover and GMP pages.
- `page.extract_tables()` for question table pages.
- Raises `ParseError` for unsupported types; `ValidationError` from pydantic is promoted
  to `ParseError` with the original exception chained.

`ChainedMarkSchemeParser` (added to `lemely/io/parsers.py`) wraps two callbacks:

```python
class ChainedMarkSchemeParser:
    def __call__(self, pdf_path: Path) -> MarkScheme:
        try:
            return self._deterministic(pdf_path)
        except ParseError:
            return self._gemini(pdf_path)
```

No changes to `process_mark_scheme_batch` — it already catches `ParseError` as `failed`.
The chain is composed at the CLI/app wiring layer.

---

## Components

### 1. `lemely/io/parsers_det.py` (new)

**`DeterministicMarkSchemeParser`**

```
__call__(pdf_path)
  ├─ _extract_metadata(pdf)   → MarkSchemeMetadata
  ├─ _extract_gmp(pdf)        → updates metadata fields
  └─ _extract_questions(pdf)  → list[Question]
       ├─ _parse_mcq_table(table)    → list[Question]  (MCQ papers)
       └─ _parse_theory_table(table) → list[Question]  (theory papers)
```

Each helper is a pure function accepting pdfplumber page/table objects and returning
typed data — testable in isolation by passing synthetic table data.

### 2. Metadata extraction (cover page)

`page.extract_text()` on page 0. Regex patterns extract:
- Subject name (first non-blank line after "Mark Scheme")
- Subject code (4-digit pattern `\d{4}`)
- Paper code → `paper_number` and `paper_variant`
- Session month and year
- Maximum mark (pattern `Maximum Mark: \d+` or similar)
- Paper type (heuristic from document title keywords)

`parse_caie_filename_metadata()` (already in `lemely/io/metadata.py`) already extracts
`subject_code`, `session_month`, `session_year`, `paper_number`, `paper_variant` from the
filename — these serve as the primary source; cover-page values are a cross-check.

### 3. GMP extraction (pages 1–3)

`page.extract_text()` on each GMP page. Text is split at numbered list markers
(`^\d+\.` or `^GMP \d+`) to produce individual principle strings for
`generic_marking_principles` and `subject_specific_principles`.

### 4. Column detection

pdfplumber returns tables as `list[list[str | None]]`. Column identity is inferred by
position index and content patterns:

| Column | Position | Content pattern |
|--------|----------|-----------------|
| Q-number | 0 (leftmost) | `^\d+$`, `\([a-z]\)`, `\([ivx]+\)`, or empty |
| Answer | 1 (or 1..−2 for wide tables) | free text |
| Guidance | −2 (if 4-column table) | free text → `question.notes` |
| Marks | −1 (rightmost) | integer string or empty |

For MCQ answer-key tables (2 columns): column −1 contains `A/B/C/D` not an integer.

### 5. Row state machine (theory papers)

Tracks: `current_q_id`, `parts_stack: list[Question]`, `current_points: list[AnswerPoint]`,
`next_is_alternative: bool`.

```
For each row:
  q_cell      = row[0] stripped
  answer_cell = row[answer_col] stripped
  marks_int   = parse_int(row[-1])  # None if empty/non-integer

  if q_cell matches question-number pattern:
      flush current_points → current question
      determine hierarchy level from q_cell depth
      push new Question onto parts_stack at correct level

  elif q_cell is empty and answer_cell non-empty:
      add AnswerPoint to current_points
      if answer_cell starts with "OR" or "EITHER":
          next_is_alternative = True
      else:
          create AnswerPoint(is_alternative=next_is_alternative)
          next_is_alternative = False
```

Nested numbering creates nested `Question.parts`. Top-level (`1`) → `parts_stack[0]`;
`(a)` → nested under `parts_stack[0].parts`; `(i)` → nested further. The stack is
unwound when a higher-level question number is encountered.

### 6. MCQ table parser

Find the 2-column table (or 2-effective-column section of a wider table) whose second
column contains only `A/B/C/D` values. Each row: `Question(type=MCQ, id=str(row[0]),
marks=1, mcq_answer=MCQAnswer(row[1]))`.

### 7. `ParseError` triggers

The parser raises `ParseError` (imported from `lemely.runtime.errors`) when:

- A row in the question table matches level-descriptor patterns: Q cell contains
  `"Level \d+"` and the answer cell contains banding language ("descriptors", "marks
  available", "AO").
- An "Indicative content" section header is detected in the answer column.
- `pdfplumber` returns no tables on question pages (image-only or scan-based PDF).
- The extracted table has fewer than 2 columns.
- pydantic raises `ValidationError` when assembling the `MarkScheme` — promoted to
  `ParseError` with `raise ParseError(...) from exc`.

The fallback is per-document: if any question triggers an unsupported type, the whole
document is handed to Gemini. This ensures each output JSON is produced by exactly one
parser.

---

## Files Changed

| File | Change |
|------|--------|
| `lemely/io/parsers_det.py` | New — `DeterministicMarkSchemeParser` |
| `lemely/io/parsers.py` | Add `ChainedMarkSchemeParser` |
| `pyproject.toml` | Add `pdfplumber` to dependencies |
| `lemely/app/cli.py` | Wire `ChainedMarkSchemeParser` as default parser |
| `tests/test_parsers_det.py` | New — unit + integration tests |

---

## Testing

### Unit tests (`tests/test_parsers_det.py`)

Mock `pdfplumber.open()` to return canned table/text data — no real PDFs required:

- **MCQ extraction**: 40-row synthetic table → 40 `Question(type=MCQ)` objects with
  correct `mcq_answer` values.
- **Theory extraction**: synthetic 3-column table → hierarchical `Question` objects with
  nested `parts`, `answer_points`, correct `marks`.
- **OR block**: row containing "OR" → next `AnswerPoint` has `is_alternative=True`.
- **Continuation row**: empty Q cell → `AnswerPoint` added to current question, not a
  new one.
- **`ParseError` on level descriptors**: row with "Level 1"/"Level 2" pattern → raises
  `ParseError`.
- **`ParseError` on indicative content**: row with "Indicative content" header → raises.
- **`ChainedMarkSchemeParser`**: primary raises `ParseError` → fallback is called;
  primary succeeds → fallback is not called.

### Integration tests (`@pytest.mark.live`, skipped by default)

Run against the 4 real PDFs in `Sources/Physics/MarkingSchemes/`:

- Parsed `MarkSchemeMetadata` fields match the corresponding known-good JSON values.
- Output passes pydantic `MarkScheme` validation.
- MCQ paper (0625_m20_ms_12): 40 questions, all `type=MCQ`, all `mcq_answer` present.

### Regression

Existing `tests/test_mark_schemes.py`, `tests/test_parsers.py`, and the full suite must
pass unchanged. The `GeminiMarkSchemeParser` interface is untouched.

---

## Verification

```bash
# Run unit suite (no API key needed)
uv run pytest tests/test_parsers_det.py -v

# Run full suite with coverage
uv run pytest

# Integration tests (requires real PDFs, no API key needed)
uv run pytest tests/test_parsers_det.py -m live -v
```

Expected outcome: unit tests pass, coverage stays ≥ 70%, integration tests produce
valid `MarkScheme` objects for the Physics MCQ papers.
