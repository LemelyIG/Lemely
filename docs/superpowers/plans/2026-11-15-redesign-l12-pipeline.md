# L12 Pipeline: Blank Flag and Cover Names, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every marked question a `blank` flag at no extra model call, and let a teacher drop a whole class set in one PDF. Lemely finds the cover pages, reads each student's name with one Haiku call per cover, splits the set into per-student papers and marks them. A short fix-it list shows the names it could not match. Both feed the Blank tile and the "names need you" row on L6's upload and processing screens.

**Architecture:**
- **Blank flag.** Lemely already makes no call for an empty answer box (`marker_source == "blank"`, US-039). This lane adds a trailing `no_attempt` field to the marker's reply schema, behind a lever, for answers that hold text but no attempt ("?", "idk", crossed-out work). A pure `question_is_blank()` joins the two signals, and every `MARKING_PROGRESS` frame and `QuestionResultDTO` carries the result.
- **Class sets.** A new `class_sets` table and a `class_set_papers` link table. A background job does four things:
  1. Renders tiny thumbnails in the sandbox and finds cover candidates by matching each page's header against page 1 (free and deterministic).
  2. Reads each candidate with one Haiku call, which also confirms that it is a cover.
  3. Splits the set into child `teacher_papers` rows, each marked by the existing grading job.
  4. Matches names against the class roster in pure code.
- **Teacher side.** A new `class_sets` router serves the recent-uploads rows and the fix-it list. A new Name check screen resolves the misses.

**Tech Stack:**
- Backend: FastAPI, SQLAlchemy and Alembic, pydantic v2, PyMuPDF and pypdfium2 (in the sandbox), numpy and Pillow
- Models: Claude Haiku 5.5 through `GeminiClient.generate_structured`
- Web: React 19, TanStack Query, Tailwind 4, Vitest, Playwright

**Spec:** `docs/superpowers/specs/2026-11-14-redesign-implementation-design.md` (line 49, Model cost; lines 154–157, lane 12). **Master:** `docs/superpowers/plans/2026-11-15-redesign-00-master.md`. **Mock:** `.impeccable/mocks/upload-r1/final.html`, with `up.css` and `base.css`.

## Global Constraints

Inherits master plan Global Constraints. Lane-specific additions:

- **Python runner.** Every pytest command in this plan runs from the worktree root as `PYTHONPATH="$(pwd)" /home/sico/Code/Lemely/.venv/bin/python -m pytest <files> -q`, written below as `PY -m pytest`. The venv is shared across worktrees, and without `PYTHONPATH` the editable `.pth` can import another worktree's `lemely`.
- **No live model calls in tests.** Every model call in a test goes through a `MagicMock` client or a recorded reply. Never set `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` in a test, and never run the accuracy harness live as part of a task.
- **Marking must not drift.** With `correction_no_attempt` off (the shipped default), every marker request must be byte-identical to today's. The pinned schema hash `b41db5c1bbd5` in `tests/test_correction_ai.py::MarkingSchemaHashStableAcrossPythonOptimizeTests` must not move.
- **Accuracy test set.** Run this set for any change to `lemely/core/schemas.py`, `lemely/io/correction_ai.py` or the marker reply:
  - `tests/test_correction_ai.py`, `tests/test_claude_schema_limits.py`, `tests/test_reason_first.py`, `tests/test_cited_marks.py`, `tests/test_correction_off_topic.py`
  - `tests/test_retry_median.py`, `tests/test_retry_keep_higher.py`, `tests/test_correction_shared_prefix.py`, `tests/test_anthropic_adapter.py`, `tests/test_claude_default_flip.py`
  - `tests/test_accuracy_harness.py`, `tests/test_golden_corpus.py`, `tests/test_golden_binding_shapes.py`, `tests/test_schemas.py`, `tests/test_web_shared_constants.py`, `tests/test_settings_example_drift.py`

  Nothing else is run locally (memory: no full test suite).
- **Cost.** Every model call is tagged (`task_tag`), so `script_cost_scope` reports it per paper. The cover read reports its USD per paper on `class_set_papers.cover_cost_usd`. The ceiling is $0.10 per paper, and the target total is ≤ $0.068 per paper (see Cost maths).
- **PDF safety.** Every byte of an uploaded class set is opened only inside `sandbox.EXTRACTION_WORKER` and only through `open_checked_pdf` and `canonical_pdf_bytes`. Every child paper is ≤ `MAX_SCAN_PAGES` (40) and re-enters the normal scan pipeline unchanged. Task 3 needs an Opus `security-reviewer` pass before merge.
- **Attribution.** Setting `teacher_papers.student_id` on a confirmed name does **not** write the student's history and does not show the paper to the student. D1.12 stays as it is (see Needs user decision 1).
- **Rollback safety.** `report_json` must stay loadable by the previous Cloud Run revision. `no_attempt` joins `_NOT_STORED` the same way `addresses_question` did.

## Cost maths

Prices come from `lemely/io/llm/pricing.py:37`. Claude Haiku 5.5 costs $0.0001 per 1k input tokens and $0.0005 per 1k output tokens, below the 100k-token tier. Image tokens = ⌈w × h / 750⌉ (`lemely/io/llm/image_fit.py:101`).

| Item | Working | USD per paper |
|---|---|---|
| Today's marking (FLIP.md, 5 frozen scripts) | measured | avg 0.049, worst 0.066 |
| Cover detection (thumbnails, template match) | no model call | 0 |
| Cover name read | 1 page at 120 DPI: 992 × 1403 px = 1,391,776 / 750 = **1,856** image tokens, plus about 260 prompt tokens = 2,116 input × 0.0001/1k = 0.000212. Output ≤ 60 tokens × 0.0005/1k = 0.000030 | **0.00024** (worst, one schema retry: 0.00048) |
| `no_attempt` lever (only when on) | about 45 schema input tokens + 7 output tokens per marker call = 45 × 0.0001/1k + 7 × 0.0005/1k = 0.000008. Avg 45 calls per script (30 leaves × 1.5 with median-of-three), worst 90 | avg **0.00036**, worst 0.00072 |
| **Total** | 0.049 + 0.00024 + 0.00036 | **avg ≈ 0.0496, worst ≈ 0.0672** (cap 0.10, margin ≥ 0.033) |

Single-paper uploads through the class-set route also pay the cover read (0.00024) and get the student's name for it.

## Opportunities (cost and accuracy)

In scope:
1. The cover read costs about half a percent of a paper and replaces typing 28 names.
2. Template matching keeps cover *detection* at $0. A per-page classifier call would cost about 16 × 0.0002 = $0.003 per paper.

Candidates to screen later, not built here:
3. The cover read could also return the paper code printed on the cover. That would let `ScanMetadataExtractor` (`lemely/io/scan_metadata.py`) skip its own 2-page call on child papers (about $0.0005 per paper saved).
4. A `no_attempt=true` leaf could skip the borderline median-of-three retry, which is pointless on a non-attempt. That saves up to 2 calls per such leaf, but changes marking, so it needs a cost-ladder screen.

## Keep-list (behaviour this lane must not lose)

| # | Feature or state | Where |
|---|---|---|
| K1 | An empty answer box makes no paid call, gets an unflagged 0 and `marker_source="blank"` | `lemely/io/correction_ai.py:3513-3533`, `:2331-2376` |
| K2 | An MCQ with no letter is 0, flagged, "missing answer" | `lemely/io/correction_ai.py:1188-1200` |
| K3 | A blank is never queued for review (`review_reasons_for` exemption) | `lemely/db/teacher_paper_repo.py:138-160` |
| K4 | `marker_scored()` stays the only "was this scored" test | `lemely/core/schemas.py:123` |
| K5 | `MARKING_PROGRESS` frames keep `question_id`, `marker_source`, `confidence`, `awarded`, `max_marks`, `index`, `total` | `lemely/io/correction_ai.py:3457-3636` |
| K6 | The marker wire schema and its hash are unchanged with the lever off | `lemely/core/schemas.py:821-1028`, pin at `tests/test_correction_ai.py:5866` |
| K7 | `addresses_question` is still required on the wire and still kept out of `report_json` | `lemely/core/schemas.py:854-877`, `lemely/db/teacher_paper_repo.py:169-171` |
| K8 | Single-file teacher upload: 25 MB cap, geometry check, `mark_scheme` sibling, run claimed on upload | `lemely/web/routers/teacher.py:879-944` |
| K9 | The grading job (scheme resolve, binding gate, failure messages, progress tracker) is unchanged per paper | `lemely/web/routers/teacher.py:516-662` |
| K10 | DS11 visibility: owner, plus a school admin over their teachers, plus a platform admin | `lemely/db/teacher_paper_repo.py:179-202` |
| K11 | The page 1 preview stays staff-only (it is reused as the cover image) | `lemely/web/routers/teacher.py`, `GET /api/papers/{paper_id}/preview` |
| K12 | Every route sits in the authz matrix | `tests/test_authz_matrix_complete.py:356-362` |
| K13 | The scan page cap of 40, the content budgets and the sandbox are untouched for single scans | `lemely/io/_scan_common.py:63`, `lemely/io/pdf_content_walk.py:1179-1272` |
| K14 | The script cost scope warns when a paper goes over `paper_cost_target_usd` | `lemely/io/gemini.py:347-370` |
| K15 | `ScanMetadataExtractor` still reads 2 pages per paper on Claude | `lemely/io/scan_metadata.py:28-75` |
| K16 | The roster scope comes from `ClassService.list_classes` plus `roster` (the teacher's own classes; a school admin sees the school's) | `lemely/db/class_repo.py:209-276` |

## Frame-to-state table (L12-owned frames)

The frames below come from `.impeccable/mocks/upload-r1/final.html`. L6 owns every other frame on this page.

| Mock frame | Real state | Breakpoint | Trigger |
|---|---|---|---|
| "Name check (teacher)" | `NameCheck` two-pane: fix list (420px) and cover panel | ≥1024 | `/teacher/papers/sets/:setId/names` with ≥1 item |
| "Tablet · name check" | Same, list 330px, panel padding 20/24 | 640–1023 | Same |
| (no phone frame) | List, then a bottom sheet with the cover panel | <640 | Tap a row (Needs user decision 4) |
| `nrow.on` | The selected fix row | all | Selection (defaults to the first item) |
| `details` "Show the 21 matched papers" | Collapsed list of matched papers | all | `matched.length > 0` |
| "Desktop · upload" `.r` row "3 names need you · Check names" | `RecentSetRow` needs-names variant in L6's Recent uploads | all | `namesNeedYou > 0 && paperCount > 1` |
| `.r` "Marking 17 of 28" + `.mini` bar | `RecentSetRow` marking variant | all | `status==='ready' && markedCount < paperCount` |
| "After a drop" `.rnote` "Reading names off the covers. Problems will show here." | Note under L6's "files received" card | all | Any class-set upload with `status==='reading'` |
| Marking board `.qt.blank` "Blank" | L6 marking tile `blank` state | all | `isBlank(question)` |
| (new) all matched | `NameCheck` sparse state: "All names matched" with a head-crop Binny | all | `items.length === 0` |
| (new) loading | `GhostRows rows={3} withLeading` on the left, a skeleton panel on the right | all | Query pending |
| (new) still reading | "Still reading covers" with `GhostRows` | all | `status==='reading'` |
| (new) error | `StateView` error with "Try again" | all | Query error |
| (new) failed set | "Couldn't split this file" plus the server's reason | all | `status==='failed'` |

## Interactions and motion

All values come from `up.css` and `base.css`. Easing `--ease: cubic-bezier(.2,.8,.2,1)` equals the `--ease-out` token in `web/src/index.css:92`.

| Interaction | Values | Reduced motion |
|---|---|---|
| `.btn` hover and press | `transition: transform .15s var(--ease), background .15s`; `:active { transform: scale(.97) }`; hover background goes to `--color-primary-hover` | No transform; colour change only |
| Fix row select | Instant; the selected row gets `bg surface-container-lowest` and `inset 0 0 0 2px primary` (`.nrow.on`) | Same (no motion) |
| Ring | Static conic gradient `conic-gradient(var(--t) calc(v*1%), surface-container-high 0)`, inner disc inset 5px | Same |
| Picker options popover (`.opts`) | Shadow `0 30px 60px -40px oklch(.3 .06 242/.45), 0 0 0 1px outline-variant`; first option filled `primary-container` | Same |
| After a confirm or skip | The row leaves the list, and selection moves to the next item. Use the existing list-exit pattern: opacity 1→0 and height collapse, 180ms `ease-out` | Remove at once |
| Phone sheet | Existing `components/ui/bottom-sheet.tsx` motion (`--native-sheet-ease`) | That component's own fallback |
| Global | `@media (prefers-reduced-motion: reduce) { * { animation: none !important } }` (up.css:49) | Built in |

## File structure

Backend (new):
- `lemely/core/blank.py`: `question_is_blank(q) -> bool`
- `lemely/core/roster_match.py`: name normalising, scoring and `match_name`
- `lemely/io/class_set/__init__.py`: empty package marker
- `lemely/io/class_set/pdf.py`: sandbox targets (thumbnails, page render, split) and their parent wrappers
- `lemely/io/class_set/covers.py`: `find_cover_candidates`, `plan_split`
- `lemely/io/class_set/cover_reader.py`: `CoverRead`, `CoverNameReader` (Haiku)
- `lemely/io/prompts/cover_names.py`: the versioned prompt
- `lemely/db/models/class_sets.py`: `ClassSet`, `ClassSetPaper`
- `lemely/db/migrations/versions/0055_class_sets.py`
- `lemely/db/class_set_repo.py`: `ClassSetRepository`, `class_set_visible`
- `lemely/web/services/class_set_job.py`: `run_class_set_job`
- `lemely/web/schemas_class_sets.py`: DTOs
- `lemely/web/routers/class_sets.py`: routes

Backend (modified):
- `lemely/core/schemas.py`
- `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`
- `lemely/io/correction_ai.py`
- `lemely/io/pdf_content_walk.py`, `lemely/io/pdf_canonical.py`
- `lemely/db/teacher_paper_repo.py`: the `_NOT_STORED` entry only
- `lemely/db/models/__init__.py`: model import
- `lemely/web/schemas.py`: `QuestionResultDTO.blank`
- `lemely/web/app.py`: one `include_router` line
- `tests/test_authz_matrix_complete.py`: the new routes

Web (new):
- `web/src/lib/classSetTypes.ts`
- `web/src/lib/hooks/useClassSetsApi.ts`
- `web/src/lib/blank.ts`
- `web/src/portals/teacher/screens/names/nameCheckModel.ts`
- `web/src/portals/teacher/screens/names/NameCheck.tsx`, `NameFixList.tsx`, `CoverPanel.tsx`, `StudentPicker.tsx`
- `web/tests/unit/classSetsApi.test.ts`, `nameCheckModel.test.ts`, `blank.test.ts`
- `web/e2e/name-check.spec.ts`

Web (modified):
- `web/src/lib/types.ts`: `QuestionResult.blank`
- `web/src/portals/teacher/index.tsx`: one route entry
- L6's upload and processing files (Task 15 only)

---

## Part A: Blank flag

### Task 1: `no_attempt` lever on the marker reply schema

**Files:**
- Modify: `lemely/core/schemas.py` (after `AIMarkResponseReasonedTerse`, about line 1018, and `marker_response_schema` at 1020-1028)
- Modify: `lemely/runtime/config.py` (after `correction_reason_first`, line 336)
- Modify: `lemely/runtime/example_toml.py` (after the `correction_terse_rationale` lines, about 185)
- Modify: `lemely.toml.example` (regenerated)
- Test: `tests/test_no_attempt_schema.py`

**Interfaces:**
- Produces:
  - `NO_ATTEMPT_DESCRIPTION: Final[str]`
  - `no_attempt_variant(base: type[AIMarkResponse]) -> type[AIMarkResponse]`
  - `marker_response_schema(*, cited: bool, terse: bool = False, reason_first: bool = False, no_attempt: bool = False) -> type[AIMarkResponse]`
  - `GeminiSettings.correction_no_attempt: bool = False`
- A reply parsed by a variant has `.no_attempt: bool`. When the reply left it out, the value is `False` and `"no_attempt" not in reply.model_fields_set`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_no_attempt_schema.py
"""Lever ``correction_no_attempt``: a trailing, wire-required ``no_attempt`` flag on the marker reply.

Off (the shipped default), every schema is exactly today's, so no request and no cache key moves.
On, ``no_attempt`` is the last property and listed in ``required``. A reply that leaves it out
still parses (False, unset), the same lenient split ``addresses_question`` uses.
"""

from __future__ import annotations

import anthropic
import pytest
from pydantic import ValidationError

from lemely.core.schemas import (
    NO_ATTEMPT_DESCRIPTION,
    AIMarkResponse,
    AIMarkResponseCited,
    AIMarkResponseCitedTerse,
    AIMarkResponseReasoned,
    AIMarkResponseReasonedTerse,
    AIMarkResponseTerse,
    marker_response_schema,
    no_attempt_variant,
)
from lemely.io.providers.claude_schema import needs_prompt_json
from lemely.runtime.config import GeminiSettings

_COMBOS = [
    dict(cited=False, terse=False, reason_first=False),
    dict(cited=False, terse=True, reason_first=False),
    dict(cited=True, terse=False, reason_first=False),
    dict(cited=True, terse=True, reason_first=False),
    dict(cited=False, terse=False, reason_first=True),
    dict(cited=False, terse=True, reason_first=True),
]

_BASES = {
    (False, False, False): AIMarkResponse,
    (False, True, False): AIMarkResponseTerse,
    (True, False, False): AIMarkResponseCited,
    (True, True, False): AIMarkResponseCitedTerse,
    (False, False, True): AIMarkResponseReasoned,
    (False, True, True): AIMarkResponseReasonedTerse,
}


def _reply(**extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "awarded_marks": 0,
        "confidence": 0.9,
        "matched_point_ids": [],
        "feedback": "No working shown.",
        "point_verdicts": [],
        "addresses_question": "yes",
    }
    body.update(extra)
    return body


def test_lever_defaults_off() -> None:
    assert GeminiSettings().correction_no_attempt is False


@pytest.mark.parametrize("combo", _COMBOS)
def test_off_returns_todays_class_unchanged(combo: dict[str, bool]) -> None:
    schema = marker_response_schema(**combo)
    assert schema is _BASES[(combo["cited"], combo["terse"], combo["reason_first"])]
    assert "no_attempt" not in schema.model_json_schema()["properties"]


@pytest.mark.parametrize("combo", _COMBOS)
def test_on_adds_a_required_last_property_with_the_fixed_description(
    combo: dict[str, bool],
) -> None:
    schema = marker_response_schema(**combo, no_attempt=True)
    sent = schema.model_json_schema()
    props = list(sent["properties"])
    assert props[-1] == "no_attempt"
    assert "no_attempt" in sent["required"]
    assert sent["required"].count("no_attempt") == 1
    assert sent["properties"]["no_attempt"]["description"] == NO_ATTEMPT_DESCRIPTION
    assert sent["properties"]["no_attempt"]["type"] == "boolean"
    # addresses_question stays required (K7).
    assert "addresses_question" in sent["required"]


@pytest.mark.parametrize("combo", _COMBOS)
def test_variant_is_one_stable_class_per_base(combo: dict[str, bool]) -> None:
    a = marker_response_schema(**combo, no_attempt=True)
    b = marker_response_schema(**combo, no_attempt=True)
    assert a is b
    base = _BASES[(combo["cited"], combo["terse"], combo["reason_first"])]
    assert issubclass(a, base)
    assert no_attempt_variant(base) is a


def test_omitted_flag_parses_false_and_unset() -> None:
    schema = marker_response_schema(cited=False, no_attempt=True)
    reply = schema.model_validate(_reply())
    assert reply.no_attempt is False  # type: ignore[attr-defined]
    assert "no_attempt" not in reply.model_fields_set


def test_explicit_true_round_trips() -> None:
    schema = marker_response_schema(cited=False, no_attempt=True)
    reply = schema.model_validate(_reply(no_attempt=True))
    assert reply.no_attempt is True  # type: ignore[attr-defined]
    assert "no_attempt" in reply.model_fields_set


def test_unknown_keys_are_still_refused() -> None:
    schema = marker_response_schema(cited=False, no_attempt=True)
    with pytest.raises(ValidationError):
        schema.model_validate(_reply(no_attempt=False, surprise=1))


def test_terse_variant_still_cuts_feedback() -> None:
    schema = marker_response_schema(cited=False, terse=True, no_attempt=True)
    reply = schema.model_validate(_reply(feedback="x" * 500, no_attempt=False))
    assert len(reply.feedback) == 300


@pytest.mark.parametrize("combo", _COMBOS)
def test_claude_keeps_structured_outputs(combo: dict[str, bool]) -> None:
    schema = marker_response_schema(**combo, no_attempt=True)
    assert needs_prompt_json(anthropic.transform_schema(schema)) is False
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PY -m pytest tests/test_no_attempt_schema.py -q`
Expected: FAIL with `ImportError: cannot import name 'NO_ATTEMPT_DESCRIPTION'`.

- [ ] **Step 3: Implement**

In `lemely/core/schemas.py`, add `cast` to the `typing` import (`from typing import Final, Literal, cast`). Then, directly after `class AIMarkResponseReasonedTerse` and before `def marker_response_schema`, insert:

```python
#: The no-attempt question put to the marker under lever ``correction_no_attempt``. Hard-coded,
#: never a docstring: it is part of ``model_json_schema()``, which the cache key hashes, and
#: ``-OO`` strips docstrings (see the Critical B note above ``PointVerdictWire``).
NO_ATTEMPT_DESCRIPTION: Final[str] = (
    "True only when the response holds no attempt at an answer: nothing but a dash, a "
    "question mark, crossed-out work, 'I don't know' or the question copied out. Never "
    "changes the marks or the feedback."
)

#: The exact property the variants send; one dict so every variant hashes the same way.
_NO_ATTEMPT_PROPERTY: Final[dict[str, object]] = {
    "default": False,
    "description": NO_ATTEMPT_DESCRIPTION,
    "title": "No Attempt",
    "type": "boolean",
}


# Lever correction_no_attempt: a mixin, so each reply schema gains the flag without a second
# copy of its own wire rules. A comment, not a docstring (a docstring becomes a description).
class _NoAttemptFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    no_attempt: bool = False

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: pydantic_core_schema.CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        """The base schema's wire rules, then ``no_attempt`` last and required."""
        json_schema = super().__get_pydantic_json_schema__(core_schema, handler)  # type: ignore[misc]
        reply = handler.resolve_ref_schema(json_schema)
        # The reasoned schema rebuilds its properties from a fixed order and drops this field,
        # so it is always written back from one constant, at the end.
        reply["properties"].pop("no_attempt", None)
        reply["properties"]["no_attempt"] = dict(_NO_ATTEMPT_PROPERTY)
        required = [name for name in reply.get("required", []) if name != "no_attempt"]
        reply["required"] = [*required, "no_attempt"]
        return json_schema


def _make_no_attempt_variant(base: type[AIMarkResponse]) -> type[AIMarkResponse]:
    name = f"{base.__name__}NoAttempt"
    made = type(name, (_NoAttemptFlag, base), {"__module__": __name__, "__qualname__": name})
    return cast("type[AIMarkResponse]", made)


#: One class per base, built once at import: the schema hash (the cache key) is stable.
_NO_ATTEMPT_VARIANTS: Final[dict[type[AIMarkResponse], type[AIMarkResponse]]] = {
    base: _make_no_attempt_variant(base)
    for base in (
        AIMarkResponse,
        AIMarkResponseTerse,
        AIMarkResponseCited,
        AIMarkResponseCitedTerse,
        AIMarkResponseReasoned,
        AIMarkResponseReasonedTerse,
    )
}


def no_attempt_variant(base: type[AIMarkResponse]) -> type[AIMarkResponse]:
    """``base`` with the trailing ``no_attempt`` flag (lever ``correction_no_attempt``)."""
    return _NO_ATTEMPT_VARIANTS[base]
```

Check that `ConfigDict` and `GetJsonSchemaHandler` are already in the `pydantic` import block at line 8. Add them if not.

Replace `marker_response_schema` with:

```python
def marker_response_schema(
    *, cited: bool, terse: bool = False, reason_first: bool = False, no_attempt: bool = False
) -> type[AIMarkResponse]:
    """The correction reply schema for the flags in force."""
    if cited:
        base: type[AIMarkResponse] = AIMarkResponseCitedTerse if terse else AIMarkResponseCited
    elif reason_first:
        base = AIMarkResponseReasonedTerse if terse else AIMarkResponseReasoned
    else:
        base = AIMarkResponseTerse if terse else AIMarkResponse
    return no_attempt_variant(base) if no_attempt else base
```

In `lemely/runtime/config.py`, after `correction_reason_first: bool = False`:

```python
    # Lever L12 (redesign): the marker reply gains a trailing `no_attempt` flag, true when the
    # answer holds text but no attempt ("?", "idk", crossed-out work). Read only by the Blank
    # tile, never by the mark. Off: every marker request is byte-identical to before.
    correction_no_attempt: bool = False
```

In `lemely/runtime/example_toml.py`, after the two `correction_terse_rationale` lines:

```python
    lines.append("# Ask the marker whether an answer is a real attempt (Blank tile only; never")
    lines.append("# changes a mark).")
    lines.append(f"# correction_no_attempt = {_toml_bool(s.gemini.correction_no_attempt)}")
```

Then regenerate the example: `PYTHONPATH="$(pwd)" /home/sico/Code/Lemely/.venv/bin/python -m lemely.runtime.example_toml > lemely.toml.example`. First check that the module's `__main__` prints to stdout. If it writes the file itself, run it without the redirect.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PY -m pytest tests/test_no_attempt_schema.py tests/test_settings_example_drift.py tests/test_correction_ai.py::MarkingSchemaHashStableAcrossPythonOptimizeTests tests/test_claude_schema_limits.py tests/test_reason_first.py tests/test_cited_marks.py tests/test_schemas.py -q`
Expected: all PASS. The `b41db5c1bbd5` pin is unchanged.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/core/schemas.py lemely/runtime/config.py lemely/runtime/example_toml.py lemely.toml.example tests/test_no_attempt_schema.py
git commit -S -m "feat(core): no_attempt lever on the marker reply schema" -- lemely/core/schemas.py lemely/runtime/config.py lemely/runtime/example_toml.py lemely.toml.example tests/test_no_attempt_schema.py
```

### Task 2: Per-question `blank` flag through marking, frames and the DTO

**Files:**
- Create: `lemely/core/blank.py`
- Modify: `lemely/core/schemas.py` (`CorrectedQuestion`, after `addresses_question` at line 325)
- Modify: `lemely/io/correction_ai.py`:
  - `_mark_schema`, lines 514-521
  - a new `_no_attempt_judgement` beside `_addresses_judgement`, line 1909
  - the two `addresses_question=_addresses_judgement(mark)` sites, lines 2099 and 2284
  - the five `MARKING_PROGRESS` publishes in `correct_paper`, lines 3457, 3474, 3490, 3518 and 3627
- Modify: `lemely/db/teacher_paper_repo.py:169-171` (`_NOT_STORED`)
- Modify: `lemely/web/schemas.py` (`QuestionResultDTO`, `question_to_dto`)
- Modify: `web/src/lib/types.ts` (`QuestionResult`)
- Create: `web/src/lib/blank.ts`
- Test: `tests/test_blank_flag.py`, `web/tests/unit/blank.test.ts`

**Interfaces:**
- Consumes (Task 1): `marker_response_schema(..., no_attempt=)`, `GeminiSettings.correction_no_attempt`
- Produces:
  - `CorrectedQuestion.no_attempt: bool | None = None` (None means not judged)
  - `lemely.core.blank.question_is_blank(q: CorrectedQuestion) -> bool`
  - every `MARKING_PROGRESS` per-question frame carries `blank: bool`
  - `QuestionResultDTO.blank: bool = False`
  - TS `QuestionResult.blank?: boolean`
  - `web/src/lib/blank.ts: isBlankQuestion(q: Pick<QuestionResult, "blank" | "markerSource">): boolean`

- [ ] **Step 1: Write the failing Python test**

```python
# tests/test_blank_flag.py
"""L12: one ``blank`` answer per question, from signals marking already has.

Blank = the student made no attempt. Three sources, none of which adds a model call:
an empty answer box (US-039, ``marker_source == "blank"``), an MCQ with no letter read,
and, under lever ``correction_no_attempt``, the marker's own trailing ``no_attempt`` flag.
Blank never changes a mark or a review flag.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lemely.core.blank import question_is_blank
from lemely.core.schemas import ConfidenceBand, CorrectedQuestion, marker_response_schema
from lemely.db.teacher_paper_repo import _NOT_STORED
from lemely.io import correction_ai
from lemely.web.schemas import question_to_dto


def _cq(**kw: object) -> CorrectedQuestion:
    base: dict[str, object] = dict(
        question_id="1a",
        awarded_marks=0,
        maximum_marks=2,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.0,
        needs_teacher_review=False,
        marker_source="ai",
    )
    base.update(kw)
    return CorrectedQuestion(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        (dict(marker_source="blank"), True),
        (dict(marker_source="deterministic", student_answer=None), True),
        (dict(marker_source="deterministic", student_answer="B", awarded_marks=1), False),
        (dict(marker_source="ai", student_answer="?", no_attempt=True), True),
        (dict(marker_source="ai", student_answer="x = 3", no_attempt=False), False),
        (dict(marker_source="ai", student_answer="x = 3", no_attempt=None), False),
        (dict(marker_source="dropped"), False),  # extraction lost it: not the student's blank
        (dict(marker_source="missing"), False),  # we chose not to mark it
    ],
)
def test_question_is_blank(kw: dict[str, object], expected: bool) -> None:
    assert question_is_blank(_cq(**kw)) is expected


def test_no_attempt_never_changes_marks_or_review() -> None:
    q = _cq(marker_source="ai", student_answer="?", no_attempt=True, awarded_marks=1)
    assert q.awarded_marks == 1
    assert q.needs_teacher_review is False


def test_no_attempt_judgement_reads_only_an_explicit_flag() -> None:
    schema = marker_response_schema(cited=False, no_attempt=True)
    common = dict(awarded_marks=0, confidence=0.9, feedback="f", addresses_question="yes")
    assert correction_ai._no_attempt_judgement(schema.model_validate(common)) is None
    explicit = schema.model_validate({**common, "no_attempt": True})
    assert correction_ai._no_attempt_judgement(explicit) is True
    legacy = marker_response_schema(cited=False).model_validate(common)
    assert correction_ai._no_attempt_judgement(legacy) is None


def test_mark_schema_follows_the_lever() -> None:
    client = MagicMock()
    g = client._settings.gemini
    g.correction_citations = False
    g.correction_terse_rationale = False
    g.correction_reason_first = False
    g.correction_retry_median = False
    g.correction_retry_keep_higher = False
    g.correction_no_attempt = False
    ai = correction_ai.AICorrector(client)
    assert "no_attempt" not in ai._mark_schema().model_fields
    g.correction_no_attempt = True
    assert "no_attempt" in ai._mark_schema().model_fields


def test_no_attempt_is_not_stored_in_report_json() -> None:
    assert _NOT_STORED["correction"]["questions"]["__all__"]["no_attempt"] is True


def test_dto_carries_blank() -> None:
    assert question_to_dto(_cq(marker_source="blank")).blank is True
    assert question_to_dto(_cq(student_answer="x", no_attempt=False)).blank is False
```

Then append a `correct_paper` integration test, so every progress frame gets checked. Copy the fixture shape used by the existing blank tests in `tests/test_correction_ai.py`: search that file for `_build_blank_corrected` / `marker_source == "blank"`, then reuse its scheme and extracted-answers helpers by import, not by copy.

```python
def test_every_marking_progress_frame_carries_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    from lemely.runtime.events import EventType, bus
    from tests.test_correction_ai import _blank_and_answered_case  # added below if absent

    scheme, extracted, ai = _blank_and_answered_case()
    seen: list[dict[str, object]] = []
    q = bus.subscribe_queue(None)
    try:
        correction_ai.correct_paper(scheme, extracted, ai=ai)
        while not q.empty():
            event = q.get_nowait()
            if event is not None and event.type is EventType.MARKING_PROGRESS:
                seen.append(dict(event.payload))
    finally:
        bus.unsubscribe_queue(q)
    per_question = [frame for frame in seen if "question_id" in frame]
    assert per_question, "no per-question frames were published"
    assert all(isinstance(frame["blank"], bool) for frame in per_question)
    by_id = {frame["question_id"]: frame["blank"] for frame in per_question}
    assert by_id["1"] is True    # empty box: US-039 short circuit
    assert by_id["2"] is False   # answered, marker said attempted
```

If `tests/test_correction_ai.py` has no `_blank_and_answered_case`, add it there. It is a module-level helper that returns a two-leaf non-MCQ `MarkScheme` (ids `"1"` and `"2"`, 2 marks each), an `ExtractedAnswers` with leaf 1 empty and leaf 2 `"x = 3"`, and a `MagicMock(spec=correction_ai.AICorrector)` whose `mark_question` returns `AIMarkResponse(awarded_marks=1, confidence=0.95, feedback="ok", addresses_question="yes")`, with `review_threshold.return_value = 0.72`, `citations_on.return_value = False`, `deferred = set()` and `escalate_deferred.return_value = {}`. Build it with the same constructors the nearest existing blank test uses. Before writing, confirm the `correct_paper` keyword names (`ai=`, or `gemini_client=` plus an internal corrector) from its signature at `lemely/io/correction_ai.py:3296`, and match them exactly.

- [ ] **Step 2: Run it to make sure it fails**

Run: `PY -m pytest tests/test_blank_flag.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.core.blank'`.

- [ ] **Step 3: Implement**

`lemely/core/blank.py`:

```python
"""Was this question left blank by the student? One answer, from signals marking already has.

No model call is added for it (spec 2026-11-14, Model cost). Three sources:

* ``marker_source == "blank"``: the answer box and the working were empty, so no marking
  call was made (US-039, ``lemely.io.correction_ai._build_blank_corrected``).
* A deterministic (MCQ) question with no letter read (``_build_mcq_corrected``'s
  ``answer is None`` branch). It stays flagged for review as before; this only names it.
* ``no_attempt is True``: the marker's own trailing flag (lever ``correction_no_attempt``)
  for text that is not an attempt ("?", "idk", crossed-out work).

``"dropped"`` and ``"missing"`` are NOT blank: extraction lost the answer, or we chose not
to mark it. Neither is the student's statement. Blank never feeds a mark, a confidence or
a review decision (``marker_scored`` stays the only "was this scored" test).
"""

from __future__ import annotations

from lemely.core.schemas import CorrectedQuestion


def question_is_blank(question: CorrectedQuestion) -> bool:
    """True when the student made no attempt at ``question``."""
    if question.marker_source == "blank":
        return True
    if question.marker_source == "deterministic":
        return question.student_answer is None
    if question.marker_source == "ai":
        return question.no_attempt is True
    return False
```

In `CorrectedQuestion` (`lemely/core/schemas.py`), directly after the `addresses_question` field and its docstring:

```python
    no_attempt: bool | None = None
    """The marker's trailing ``no_attempt`` flag (lever ``correction_no_attempt``): the
    response holds text but no attempt. ``None`` means NOT JUDGED (the lever was off, no
    marker was called, or the reply left the field out). Read through
    :func:`lemely.core.blank.question_is_blank`. Never an input to ``awarded_marks``,
    ``confidence`` or ``needs_teacher_review``. Not stored in ``report_json``
    (``teacher_paper_repo._NOT_STORED``), for revision-rollback safety."""
```

In `lemely/io/correction_ai.py`:

1. `_mark_schema`:

```python
    def _mark_schema(self) -> type[AIMarkResponse]:
        """The reply schema for the flags in force; ``AIMarkResponse`` with them off."""
        g = self._client._settings.gemini
        return marker_response_schema(
            cited=self.citations_on(),
            terse=g.correction_terse_rationale is True,
            reason_first=self._reason_first(),
            no_attempt=g.correction_no_attempt is True,
        )
```

2. Directly after `_addresses_judgement`:

```python
def _no_attempt_judgement(mark: AIMarkResponse) -> bool | None:
    """The marker's ``no_attempt``, or ``None`` when the schema or the reply lacked it.

    Same rule as :func:`_addresses_judgement`: an omitted field is not a judgement.
    ``model_fields_set`` survives the cache (raw reply text, re-validated) and ``model_copy``.
    """
    if "no_attempt" not in mark.model_fields_set:
        return None
    return bool(getattr(mark, "no_attempt"))
```

3. At both `CorrectedQuestion(...)` constructions that pass `addresses_question=_addresses_judgement(mark),` (lines 2099 and 2284), add the next line:

```python
        no_attempt=_no_attempt_judgement(mark),
```

4. Add `from lemely.core.blank import question_is_blank` to the imports. In each of the five per-question `bus.publish(EventType.MARKING_PROGRESS, question_id=q.id, ...)` calls in `correct_paper`, add `blank=question_is_blank(cq),` after `max_marks=q.marks,`. Every branch has a `cq` bound just before its publish (dropped, MCQ, missing, blank, ai). Check each of the five by eye. Do not touch the adjudication or escalation frames unless they publish `question_id`; if they do, add the same keyword there too, using the rebuilt `cq`.

In `lemely/db/teacher_paper_repo.py`:

```python
_NOT_STORED = {
    "correction": {
        "binding": True,
        "questions": {"__all__": {"addresses_question": True, "no_attempt": True}},
    }
}
```

Then check the student path. `lemely/db/attempt_repo.py` persists `CorrectedQuestion` into `question_results` columns. Search it for `addresses_question` and confirm it maps explicit fields, not `model_dump()`. If it uses `model_dump()`, exclude `no_attempt` there the same way.

In `lemely/web/schemas.py`, add to `QuestionResultDTO` after `needsTeacherReview`:

```python
    #: L12: the student made no attempt (``lemely.core.blank.question_is_blank``). Default
    #: False for the DB-row constructor in ``routers/student_self_review.py``; the client
    #: also treats ``markerSource == "blank"`` as blank, so that path loses nothing.
    blank: bool = False
```

and in `question_to_dto` add `blank=question_is_blank(question),` (import from `lemely.core.blank`).

`web/src/lib/types.ts`, in `QuestionResult` after `needsTeacherReview?`:

```ts
  /** L12: no attempt was made (mirrors `QuestionResultDTO.blank`). Absent on older payloads;
   * read it through `isBlankQuestion` in `lib/blank.ts`, which also counts `markerSource === "blank"`. */
  blank?: boolean
```

`web/src/lib/blank.ts`:

```ts
import type { QuestionResult } from "@/lib/types"

/** The Blank tile's one rule (L12). Mirrors `lemely/core/blank.py`. The server's `blank` wins;
 * a payload without it still reads a US-039 blank from `markerSource`. */
export function isBlankQuestion(q: Pick<QuestionResult, "blank" | "markerSource">): boolean {
  return q.blank === true || q.markerSource === "blank"
}
```

`web/tests/unit/blank.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { isBlankQuestion } from "@/lib/blank"

describe("isBlankQuestion", () => {
  it("trusts the server flag", () => {
    expect(isBlankQuestion({ blank: true, markerSource: "ai" })).toBe(true)
  })
  it("falls back to a US-039 blank when the flag is absent", () => {
    expect(isBlankQuestion({ markerSource: "blank" })).toBe(true)
  })
  it("is not blank for a marked answer", () => {
    expect(isBlankQuestion({ blank: false, markerSource: "ai" })).toBe(false)
    expect(isBlankQuestion({ markerSource: "dropped" })).toBe(false)
  })
})
```

- [ ] **Step 4: Run the accuracy set and the new tests**

Run: `PY -m pytest tests/test_blank_flag.py tests/test_no_attempt_schema.py tests/test_correction_ai.py tests/test_claude_schema_limits.py tests/test_reason_first.py tests/test_cited_marks.py tests/test_correction_off_topic.py tests/test_retry_median.py tests/test_retry_keep_higher.py tests/test_correction_shared_prefix.py tests/test_anthropic_adapter.py tests/test_claude_default_flip.py tests/test_accuracy_harness.py tests/test_golden_corpus.py tests/test_golden_binding_shapes.py tests/test_schemas.py tests/test_web_shared_constants.py tests/test_settings_example_drift.py -q`
Then: `cd web && npx vitest run tests/unit/blank.test.ts && npm run typecheck`
Expected: all PASS. If a golden or harness test compares full `CorrectedQuestion` dumps, it now sees `no_attempt: None`. Fix the comparison to exclude the new key. Do not re-record goldens.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/core/blank.py lemely/core/schemas.py lemely/io/correction_ai.py lemely/db/teacher_paper_repo.py lemely/web/schemas.py tests/test_blank_flag.py tests/test_correction_ai.py web/src/lib/types.ts web/src/lib/blank.ts web/tests/unit/blank.test.ts
git commit -S -m "feat(core): per-question blank flag on marking frames and results" -- lemely/core/blank.py lemely/core/schemas.py lemely/io/correction_ai.py lemely/db/teacher_paper_repo.py lemely/web/schemas.py tests/test_blank_flag.py tests/test_correction_ai.py web/src/lib/types.ts web/src/lib/blank.ts web/tests/unit/blank.test.ts
```

---

## Part B: Class sets and cover names

### Task 3: Sandboxed class-set PDF targets (SECURITY-SENSITIVE)

Opus `security-reviewer` must approve this task before merge. It widens the page bound for one sandboxed caller only.

**Files:**
- Modify: `lemely/io/pdf_content_walk.py` (`check_pdf_content`, lines 1179-1272)
- Modify: `lemely/io/pdf_canonical.py` (`canonical_pdf_bytes`, line 128, and its call into `check_pdf_content`)
- Modify: `lemely/io/_scan_common.py` (add `MAX_CLASS_SET_PAGES` next to `MAX_SCAN_PAGES`, line 63)
- Create: `lemely/io/class_set/__init__.py` (empty), `lemely/io/class_set/pdf.py`
- Test: `tests/test_class_set_pdf.py`

**Interfaces:**
- Produces:
  - `MAX_CLASS_SET_PAGES = 480`
  - `check_pdf_content(doc, *, pdfium_pages=None, max_pages: int = MAX_SCAN_PAGES)`
  - `canonical_pdf_bytes(data, *, max_pages: int = MAX_SCAN_PAGES)`
  - `CoverThumb(index: int, width: int, height: int, grey: bytes)`, a dataclass where `grey` is `width*height` uint8
  - `SplitPdfs(pdfs: tuple[bytes, ...])`, a dataclass
  - `class_set_thumbnails(data: bytes) -> list[CoverThumb]`
  - `class_set_pages(data: bytes, indices: list[int], *, dpi: float = 120.0) -> list[RasterisedPage]`
  - `split_class_set(data: bytes, ranges: list[tuple[int, int]]) -> list[bytes]`, where ranges are inclusive and 0-based
  - `class_set_page_count(data: bytes) -> int`
- Raises: `ScanRejectedError` or `ScanTooLargeError` (the existing types) for a refused file. A range longer than `MAX_SCAN_PAGES` raises `ScanTooLargeError(reason="class_set_paper_too_long")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_class_set_pdf.py
"""Class-set PDFs: bounded, checked and rendered only in the extraction worker.

The single-scan cap (40) and budgets are untouched (K13). A class set may hold up to
MAX_CLASS_SET_PAGES; its content budget is held per 40-page window, so every child paper
is within one scan's budget; each child is <= 40 pages and goes through the normal pipeline.
"""

from __future__ import annotations

import pymupdf
import pytest

from lemely.io._scan_common import MAX_CLASS_SET_PAGES, MAX_SCAN_PAGES
from lemely.io.class_set.pdf import (
    class_set_page_count,
    class_set_pages,
    class_set_thumbnails,
    split_class_set,
)
from lemely.io.pdf_canonical import canonical_pdf_bytes
from lemely.io.rasterise import ScanRejectedError, ScanTooLargeError


def _pdf(pages: int, *, cover_every: int = 4) -> bytes:
    """A4 pages; every `cover_every`th page carries a heavy printed header block."""
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        if i % cover_every == 0:
            page.draw_rect(pymupdf.Rect(40, 40, 555, 120), color=(0, 0, 0), fill=(0, 0, 0))
            page.draw_rect(pymupdf.Rect(40, 150, 300, 190), color=(0, 0, 0), width=2)
            page.insert_text((60, 175), f"Student {i}", fontsize=14)
        else:
            for y in range(80, 800, 24):
                page.draw_line(pymupdf.Point(40, y), pymupdf.Point(555, y), color=(0.6, 0.6, 0.6))
    data = doc.tobytes()
    doc.close()
    return bytes(data)


def test_single_scan_cap_is_unchanged() -> None:
    with pytest.raises(ScanTooLargeError):
        canonical_pdf_bytes(_pdf(MAX_SCAN_PAGES + 1))


def test_class_set_cap_admits_more_than_one_scan() -> None:
    data = _pdf(MAX_SCAN_PAGES + 8)
    assert class_set_page_count(data) == MAX_SCAN_PAGES + 8


def test_class_set_cap_still_refuses_past_its_bound() -> None:
    with pytest.raises(ScanTooLargeError):
        class_set_page_count(_pdf(MAX_CLASS_SET_PAGES + 1, cover_every=50))


def test_thumbnails_one_per_page_small_and_grey() -> None:
    data = _pdf(45)
    thumbs = class_set_thumbnails(data)
    assert [t.index for t in thumbs] == list(range(45))
    assert all(len(t.grey) == t.width * t.height for t in thumbs)
    assert all(t.width <= 64 and t.height <= 91 for t in thumbs)


def test_pages_render_only_the_requested_indices() -> None:
    data = _pdf(12)
    pages = class_set_pages(data, [0, 4, 8], dpi=120.0)
    assert [p.index for p in pages] == [0, 4, 8]
    assert all(p.png_bytes.startswith(b"\x89PNG") for p in pages)


def test_split_makes_checked_child_pdfs() -> None:
    data = _pdf(12)
    children = split_class_set(data, [(0, 3), (4, 7), (8, 11)])
    assert len(children) == 3
    for child in children:
        assert canonical_pdf_bytes(child)  # each child passes the single-scan pipeline
        doc = pymupdf.open(stream=child, filetype="pdf")  # type: ignore[no-untyped-call]
        assert doc.page_count == 4
        doc.close()


def test_split_refuses_a_child_longer_than_one_scan() -> None:
    data = _pdf(MAX_SCAN_PAGES + 2, cover_every=100)
    with pytest.raises(ScanTooLargeError):
        split_class_set(data, [(0, MAX_SCAN_PAGES)])


def test_split_refuses_bad_ranges() -> None:
    data = _pdf(8)
    with pytest.raises(ValueError):
        split_class_set(data, [(4, 2)])
    with pytest.raises(ValueError):
        split_class_set(data, [(0, 8)])


def test_garbage_is_refused_not_rendered() -> None:
    with pytest.raises(ScanRejectedError):
        class_set_thumbnails(b"%PDF-1.7 not really")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PY -m pytest tests/test_class_set_pdf.py -q`
Expected: FAIL with `ImportError: cannot import name 'MAX_CLASS_SET_PAGES'`.

- [ ] **Step 3: Implement**

`lemely/io/_scan_common.py`, next to `MAX_SCAN_PAGES = 40`:

```python
#: A whole class set in one PDF (L12): 28 students x 16 pages is 448. Only the class-set
#: targets in ``lemely.io.class_set.pdf`` pass it, and only to the whole-set check; every
#: child paper they cut is held to MAX_SCAN_PAGES and re-enters the normal scan pipeline.
MAX_CLASS_SET_PAGES = 480
```

`lemely/io/pdf_content_walk.py`, in `check_pdf_content`:
1. Change the signature to `def check_pdf_content(doc: pymupdf.Document, *, pdfium_pages: int | None = None, max_pages: int = MAX_SCAN_PAGES) -> None:`.
2. Replace the early cap check with:

```python
    if page_count > max_pages:
        raise ScanTooLargeError(
            f"The scan has {page_count} pages; the limit is {max_pages}.", reason="page_cap"
        )
```

3. Replace `tree = _page_tree(doc, bound=_SCAN_PAGE_BOUND)` with:

```python
        bound = (
            _SCAN_PAGE_BOUND
            if max_pages == MAX_SCAN_PAGES
            else _PageBound(max_pages, _SCAN_PAGES_MESSAGE, "page_cap")
        )
        tree = _page_tree(doc, bound=bound)
```

4. Replace the final loop with:

```python
    budget = _ContentBudget()
    for page_index in range(page_count):
        # L12: a class set is held to one scan's budget per 40-page window, so no child paper
        # can carry more content than a scan the renderer was sized for. For a single scan
        # (<= 40 pages) this never fires after page 0: behaviour is unchanged.
        if page_index and page_index % MAX_SCAN_PAGES == 0:
            budget = _ContentBudget()
        _check_page(doc, tree, budget, page_index)
```

Add a sentence to the docstring naming `max_pages` and the window rule.

`lemely/io/pdf_canonical.py`: give `canonical_pdf_bytes` a keyword `max_pages: int = MAX_SCAN_PAGES` (import from `lemely.io._scan_common`) and pass it to its `check_pdf_content(doc)` call as `check_pdf_content(doc, max_pages=max_pages)`. Nothing else changes.

`lemely/io/class_set/pdf.py`:

```python
"""Class-set PDFs (L12): page count, cover thumbnails, page renders and the split.

Every function whose name starts with ``iter_`` or ``_child_`` runs in
``sandbox.EXTRACTION_WORKER`` (#260): it opens the uploaded bytes only through
``canonical_pdf_bytes(max_pages=MAX_CLASS_SET_PAGES)``, the pages-only MuPDF rewrite that
the whole-document content check gates. Rendering goes through ``rasterise``'s own
``_iter_canonical_pages`` on chunks of at most MAX_SCAN_PAGES, so the renderer's page cap and
its per-scan content check apply unchanged to every chunk. The parent-side wrappers below
are what the job calls.
"""

from __future__ import annotations

import contextlib
import io
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from typing import cast

import pymupdf
from PIL import Image

from lemely.io._scan_common import MAX_CLASS_SET_PAGES, MAX_SCAN_PAGES
from lemely.io.pdf_canonical import canonical_pdf_bytes
from lemely.io.rasterise import RasterisedPage, ScanTooLargeError, _iter_canonical_pages
from lemely.runtime import sandbox

#: Thumbnail size: enough to tell a printed cover header from a lined page, nothing more.
THUMB_W, THUMB_H = 64, 91
#: Renders run at the floor DPI; the child shrinks each page before sending it.
_THUMB_DPI = 100.0
#: 480 pages is 12 single-scan chunks; the worker's per-scan timeout is scaled to match.
_TIMEOUT_FACTOR = 12

THUMBS_TARGET = "lemely.io.class_set.pdf.iter_class_set_thumbnails"
PAGES_TARGET = "lemely.io.class_set.pdf.iter_class_set_pages"
SPLIT_TARGET = "lemely.io.class_set.pdf.child_split_class_set"
COUNT_TARGET = "lemely.io.class_set.pdf.child_page_count"


@dataclass(frozen=True)
class CoverThumb:
    index: int
    width: int
    height: int
    grey: bytes


@dataclass(frozen=True)
class SplitPdfs:
    pdfs: tuple[bytes, ...]


@dataclass(frozen=True)
class PageCount:
    pages: int


def _open_canonical(data: bytes) -> pymupdf.Document:
    canonical = canonical_pdf_bytes(data, max_pages=MAX_CLASS_SET_PAGES)
    return pymupdf.open(stream=canonical, filetype="pdf")  # type: ignore[no-untyped-call]


def _range_bytes(doc: pymupdf.Document, start: int, end: int) -> bytes:
    """Pages ``start..end`` (inclusive) of an already-canonical ``doc`` as a new PDF."""
    out = pymupdf.open()  # type: ignore[no-untyped-call]
    try:
        out.insert_pdf(doc, from_page=start, to_page=end, links=False, annots=True, widgets=True)
        return bytes(out.tobytes(garbage=1))
    finally:
        out.close()


def _chunks(page_count: int) -> Iterator[tuple[int, int]]:
    for start in range(0, page_count, MAX_SCAN_PAGES):
        yield start, min(start + MAX_SCAN_PAGES, page_count) - 1


# -- sandbox children -----------------------------------------------------------------


def child_page_count(data: bytes) -> PageCount:
    doc = _open_canonical(data)
    try:
        return PageCount(int(doc.page_count))
    finally:
        doc.close()


def iter_class_set_thumbnails(data: bytes) -> Iterator[CoverThumb]:
    doc = _open_canonical(data)
    try:
        for start, end in _chunks(int(doc.page_count)):
            chunk = _range_bytes(doc, start, end)
            rendering = cast("Generator[RasterisedPage]", _iter_canonical_pages(chunk, dpi=_THUMB_DPI))
            with contextlib.closing(rendering):
                for page in rendering:
                    img = Image.open(io.BytesIO(page.png_bytes)).convert("L")
                    img = img.resize((THUMB_W, THUMB_H), Image.Resampling.BOX)
                    yield CoverThumb(start + page.index, THUMB_W, THUMB_H, img.tobytes())
    finally:
        doc.close()


def iter_class_set_pages(data: bytes, indices: list[int], dpi: float) -> Iterator[RasterisedPage]:
    doc = _open_canonical(data)
    try:
        count = int(doc.page_count)
        for index in indices:
            if not 0 <= index < count:
                raise ValueError(f"page {index} is outside 0..{count - 1}")
            one = _range_bytes(doc, index, index)
            for page in _iter_canonical_pages(one, dpi=dpi):
                yield RasterisedPage(index, page.width, page.height, page.png_bytes, page.dpi)
    finally:
        doc.close()


def child_split_class_set(data: bytes, ranges: list[tuple[int, int]]) -> SplitPdfs:
    doc = _open_canonical(data)
    try:
        count = int(doc.page_count)
        out: list[bytes] = []
        for start, end in ranges:
            if not (0 <= start <= end < count):
                raise ValueError(f"range {start}..{end} is outside 0..{count - 1}")
            if end - start + 1 > MAX_SCAN_PAGES:
                raise ScanTooLargeError(
                    f"One paper in this set has {end - start + 1} pages; the limit is "
                    f"{MAX_SCAN_PAGES}.",
                    reason="class_set_paper_too_long",
                )
            out.append(_range_bytes(doc, start, end))
        return SplitPdfs(tuple(out))
    finally:
        doc.close()


# -- parent wrappers --------------------------------------------------------------------


def _timeout() -> float:
    return sandbox.sandbox_settings().extraction_timeout_seconds * _TIMEOUT_FACTOR


def class_set_page_count(data: bytes) -> int:
    result = sandbox.EXTRACTION_WORKER.call(
        COUNT_TARGET, data, timeout=_timeout(), result_type=PageCount
    )
    return result.pages


def class_set_thumbnails(data: bytes) -> list[CoverThumb]:
    stream = cast(
        "Generator[CoverThumb]",
        sandbox.EXTRACTION_WORKER.stream(THUMBS_TARGET, data, timeout=_timeout(), item_type=CoverThumb),
    )
    with contextlib.closing(stream):
        return list(stream)


def class_set_pages(data: bytes, indices: list[int], *, dpi: float = 120.0) -> list[RasterisedPage]:
    stream = cast(
        "Generator[RasterisedPage]",
        sandbox.EXTRACTION_WORKER.stream(
            PAGES_TARGET, data, list(indices), dpi, timeout=_timeout(), item_type=RasterisedPage
        ),
    )
    with contextlib.closing(stream):
        return list(stream)


def split_class_set(data: bytes, ranges: list[tuple[int, int]]) -> list[bytes]:
    result = sandbox.EXTRACTION_WORKER.call(
        SPLIT_TARGET, data, list(ranges), timeout=_timeout(), result_type=SplitPdfs
    )
    return list(result.pdfs)
```

Check that the sandbox re-raises `ScanRejectedError`, `ScanTooLargeError` and `ValueError` from the child as themselves. `rasterise_scan_to_pages` documents that "a scan refusal arrives as itself". If `ValueError` arrives as `SandboxFailure`, catch it in the wrapper and re-raise `ValueError(str(exc))`, then keep the test as written. If `_iter_canonical_pages` lowers the requested DPI (MIN_EXTRACTION_DPI is 100), the thumbnails are unaffected, because the child resizes.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PY -m pytest tests/test_class_set_pdf.py tests/test_pdf_content_walk*.py tests/test_pdf_canonical*.py tests/test_rasterise*.py -q`. The globs pick up whichever of those files exist; list them with `ls tests | grep -E "pdf_content|pdf_canonical|rasterise"` first and name them explicitly.
Expected: PASS, and no change in any existing PDF safety test.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/io/_scan_common.py lemely/io/pdf_content_walk.py lemely/io/pdf_canonical.py lemely/io/class_set/__init__.py lemely/io/class_set/pdf.py tests/test_class_set_pdf.py
git commit -S -m "feat(io): sandboxed class-set page bound, thumbnails and split" -- lemely/io/_scan_common.py lemely/io/pdf_content_walk.py lemely/io/pdf_canonical.py lemely/io/class_set/__init__.py lemely/io/class_set/pdf.py tests/test_class_set_pdf.py
```

### Task 4: Cover detection and split plan (pure, no model)

**Files:**
- Create: `lemely/io/class_set/covers.py`
- Test: `tests/test_class_set_covers.py`

**Interfaces:**
- Consumes (Task 3): `CoverThumb`
- Produces:
  - `COVER_SIMILARITY = 0.80`, `MIN_PAPER_PAGES = 2`
  - `header_similarity(a: CoverThumb, b: CoverThumb) -> float`
  - `find_cover_candidates(thumbs: Sequence[CoverThumb]) -> list[int]`, where the first is always 0
  - `PaperSplit(start: int, end: int)` with `.pages` (frozen dataclass, inclusive)
  - `plan_split(page_count: int, covers: Sequence[int]) -> list[PaperSplit]`
  - `modal_pages(splits) -> int`
  - `pages_differ(split, modal) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_class_set_covers.py
from __future__ import annotations

import numpy as np
import pytest

from lemely.io.class_set.covers import (
    PaperSplit,
    find_cover_candidates,
    header_similarity,
    modal_pages,
    pages_differ,
    plan_split,
)
from lemely.io.class_set.pdf import THUMB_H, THUMB_W, CoverThumb

_RNG = np.random.default_rng(7)


def _thumb(index: int, kind: str, *, rotate: bool = False) -> CoverThumb:
    img = np.full((THUMB_H, THUMB_W), 245, dtype=np.uint8)
    if kind == "cover":
        img[4:12, 4:60] = 20      # printed title band
        img[16:20, 4:30] = 40     # name box
        img[24:26, 4:60] = 60     # instructions rule
        img[16:19, 6:20] = _RNG.integers(0, 120, size=(3, 14))  # handwriting differs per student
    else:
        img[::6, 4:60] = 170      # ruled answer lines
        img[30:60, 10:50] = _RNG.integers(60, 200, size=(30, 40))  # working
    if rotate:
        img = img[::-1, ::-1]
    return CoverThumb(index, THUMB_W, THUMB_H, img.tobytes())


def _set(papers: int, pages_each: int) -> list[CoverThumb]:
    thumbs = []
    for i in range(papers * pages_each):
        thumbs.append(_thumb(i, "cover" if i % pages_each == 0 else "answer"))
    return thumbs


def test_covers_match_each_other_and_not_answer_pages() -> None:
    assert header_similarity(_thumb(0, "cover"), _thumb(8, "cover")) >= 0.80
    assert header_similarity(_thumb(0, "cover"), _thumb(1, "answer")) < 0.80


def test_finds_every_cover_in_an_even_set() -> None:
    assert find_cover_candidates(_set(5, 4)) == [0, 4, 8, 12, 16]


def test_upside_down_cover_still_counts() -> None:
    thumbs = _set(3, 4)
    thumbs[4] = _thumb(4, "cover", rotate=True)
    assert find_cover_candidates(thumbs) == [0, 4, 8]


def test_single_paper_has_one_cover() -> None:
    assert find_cover_candidates(_set(1, 16)) == [0]


def test_adjacent_lookalikes_are_not_two_papers() -> None:
    thumbs = _set(2, 4)
    thumbs[1] = _thumb(1, "cover")  # a reprinted cover straight after the first
    assert find_cover_candidates(thumbs) == [0, 4]


def test_empty_input() -> None:
    assert find_cover_candidates([]) == []


def test_plan_split_ranges_are_inclusive_and_cover_every_page() -> None:
    assert plan_split(12, [0, 4, 8]) == [PaperSplit(0, 3), PaperSplit(4, 7), PaperSplit(8, 11)]
    assert plan_split(5, [0]) == [PaperSplit(0, 4)]


def test_plan_split_refuses_bad_covers() -> None:
    with pytest.raises(ValueError):
        plan_split(8, [2, 4])      # must start at page 0
    with pytest.raises(ValueError):
        plan_split(8, [0, 4, 4])   # strictly increasing
    with pytest.raises(ValueError):
        plan_split(8, [0, 9])      # inside the document


def test_modal_and_pages_differ() -> None:
    splits = plan_split(36, [0, 4, 8, 12, 16, 20, 24, 28, 32])
    splits.append(PaperSplit(36, 43))
    assert modal_pages(splits) == 4
    assert pages_differ(splits[-1], 4) is True
    assert pages_differ(splits[0], 4) is False
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PY -m pytest tests/test_class_set_covers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.io.class_set.covers'`.

- [ ] **Step 3: Implement**

```python
# lemely/io/class_set/covers.py
"""Where each student's paper starts in a class set, without a model call (L12).

Every cover in a class set is the same printed page with a different handwritten name, so
its header region matches page 1's header almost exactly, and an answer page's does not.
Pearson correlation of the top 40% of a 64x91 grey thumbnail, against page 1's (and page 1
turned 180 degrees, for a sheet fed upside down). Candidates are confirmed by the cover read
(``cover_reader.CoverRead.is_cover_page``) before anything is split.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from lemely.io.class_set.pdf import CoverThumb

#: Header correlation at or above this marks a cover candidate. Synthetic fixtures sit
#: >= 0.95 for covers and <= 0.4 for answer pages; real-set calibration is Needs-user-decision 5.
COVER_SIMILARITY = 0.80
#: A paper is at least a cover plus one page.
MIN_PAPER_PAGES = 2
_HEADER_FRACTION = 0.40


def _header(thumb: CoverThumb, *, rotate: bool = False) -> NDArray[np.float64]:
    img = np.frombuffer(thumb.grey, dtype=np.uint8).reshape(thumb.height, thumb.width)
    if rotate:
        img = img[::-1, ::-1]
    rows = max(1, int(round(thumb.height * _HEADER_FRACTION)))
    head = img[:rows].astype(np.float64)
    head -= head.mean()
    norm = float(np.linalg.norm(head))
    return head / norm if norm > 1e-9 else np.zeros_like(head)


def header_similarity(a: CoverThumb, b: CoverThumb) -> float:
    """Correlation of ``b``'s header with ``a``'s, the better of upright and turned."""
    ha = _header(a)
    upright = float((ha * _header(b)).sum())
    turned = float((ha * _header(b, rotate=True)).sum())
    return max(upright, turned)


def find_cover_candidates(thumbs: Sequence[CoverThumb]) -> list[int]:
    """Page indices that look like page 1's cover. Page 0 always starts the first paper."""
    if not thumbs:
        return []
    first = thumbs[0]
    covers = [first.index]
    for thumb in thumbs[1:]:
        if thumb.index - covers[-1] < MIN_PAPER_PAGES:
            continue
        if header_similarity(first, thumb) >= COVER_SIMILARITY:
            covers.append(thumb.index)
    return covers


@dataclass(frozen=True)
class PaperSplit:
    start: int
    end: int

    @property
    def pages(self) -> int:
        return self.end - self.start + 1


def plan_split(page_count: int, covers: Sequence[int]) -> list[PaperSplit]:
    """One inclusive page range per cover, up to the page before the next cover."""
    if not covers or covers[0] != 0:
        raise ValueError("the first paper must start on page 0")
    if any(b <= a for a, b in zip(covers, covers[1:], strict=False)):
        raise ValueError("cover pages must strictly increase")
    if covers[-1] >= page_count:
        raise ValueError("a cover lies outside the document")
    ends = [*(c - 1 for c in covers[1:]), page_count - 1]
    return [PaperSplit(start, end) for start, end in zip(covers, ends, strict=True)]


def modal_pages(splits: Sequence[PaperSplit]) -> int:
    """The most common paper length (ties: the shorter)."""
    counts = Counter(s.pages for s in splits)
    best = max(counts.values())
    return min(pages for pages, n in counts.items() if n == best)


def pages_differ(split: PaperSplit, modal: int) -> bool:
    return split.pages != modal
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PY -m pytest tests/test_class_set_covers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/io/class_set/covers.py tests/test_class_set_covers.py
git commit -S -m "feat(io): find class-set covers by header match and plan the split" -- lemely/io/class_set/covers.py tests/test_class_set_covers.py
```

### Task 5: Cover name reader (one Haiku call per cover)

**Files:**
- Create: `lemely/io/prompts/cover_names.py`, `lemely/io/class_set/cover_reader.py`
- Test: `tests/test_cover_reader.py`

**Interfaces:**
- Consumes: `GeminiClient.generate_structured(...)` (`lemely/io/gemini.py:1685`), `GeminiClient.model_for_tag("scan_metadata")`
- Produces:
  - `COVER_TASK_TAG = "cover_names"`
  - `CoverRead(is_cover_page: bool, candidate_name: str | None, candidate_number: str | None)`
  - `CoverNameReader(client)(page_png: bytes, *, cache_key: str) -> CoverRead`
  - `MAX_COVER_IMAGE_TOKENS = 2000`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cover_reader.py
from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from PIL import Image
from pydantic import ValidationError

from lemely.io.class_set.cover_reader import (
    COVER_TASK_TAG,
    MAX_COVER_IMAGE_TOKENS,
    CoverNameReader,
    CoverRead,
)
from lemely.io.llm.image_fit import estimate_tokens
from lemely.io.prompts import cover_names


def _png(w: int = 992, h: int = 1403) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (w, h), 255).save(buf, format="PNG")
    return buf.getvalue()


def _client(read: CoverRead) -> MagicMock:
    client = MagicMock()
    client.model_for_tag.return_value = "claude-haiku-5-5"
    client.generate_structured.return_value = read
    return client


def test_one_tagged_call_with_one_image() -> None:
    read = CoverRead(is_cover_page=True, candidate_name="Omr S.", candidate_number=None)
    client = _client(read)
    assert CoverNameReader(client)(_png(), cache_key="set1:p4") == read
    client.generate_structured.assert_called_once()
    kw = client.generate_structured.call_args.kwargs
    assert kw["task_tag"] == COVER_TASK_TAG
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["response_schema"] is CoverRead
    assert kw["prompt_version"] == cover_names.VERSION
    assert len(kw["image_parts"]) == 1
    assert kw["extra_cache_key"] == "set1:p4"
    client.model_for_tag.assert_called_once_with("scan_metadata")


def test_120_dpi_a4_stays_inside_the_token_budget() -> None:
    assert estimate_tokens(992, 1403) <= MAX_COVER_IMAGE_TOKENS


def test_oversized_image_is_shrunk_before_sending() -> None:
    client = _client(CoverRead(is_cover_page=True, candidate_name=None, candidate_number=None))
    CoverNameReader(client)(_png(2480, 3508), cache_key="k")
    sent = client.generate_structured.call_args.kwargs["image_parts"][0]
    w, h = Image.open(io.BytesIO(sent)).size
    assert estimate_tokens(w, h) <= MAX_COVER_IMAGE_TOKENS


def test_schema_trims_and_blanks_names() -> None:
    assert CoverRead(is_cover_page=True, candidate_name="  ", candidate_number=" ").candidate_name is None
    assert CoverRead(is_cover_page=True, candidate_name=" Nour Adl ", candidate_number=None).candidate_name == "Nour Adl"
    with pytest.raises(ValidationError):
        CoverRead(is_cover_page=True, candidate_name="x" * 121, candidate_number=None)


def test_prompt_never_asks_for_marks_and_names_the_fields() -> None:
    assert "candidate_name" in cover_names.build_cover_user_prompt()
    assert "mark" not in cover_names.COVER_SYSTEM_PROMPT.lower().replace("remark", "")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PY -m pytest tests/test_cover_reader.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# lemely/io/prompts/cover_names.py
"""Versioned prompt for reading a student's name off a class-set cover page (L12)."""

from __future__ import annotations

VERSION = "1"

COVER_SYSTEM_PROMPT = """
You read the front page of a student's exam answer booklet.

Decide whether this page is a cover page: the printed front page of a Cambridge (CAIE)
paper with boxes for the candidate's name and number. A page of written answers, a lined
continuation sheet or a blank page is not a cover page.

If it is a cover page, copy the handwritten candidate name exactly as written, including
misspellings and initials, and the candidate number if one is written. Do not guess,
correct or complete a name. If the name box is empty or unreadable, return null.
""".strip()


def build_cover_user_prompt() -> str:
    return (
        "Return is_cover_page, candidate_name and candidate_number as JSON. "
        "Use null for a name or number that is not written or cannot be read."
    )
```

```python
# lemely/io/class_set/cover_reader.py
"""One Haiku call per class-set cover: is it a cover, and whose name is on it (L12).

Cost per call (pricing.py, Haiku 5.5): a 120 DPI A4 page is 992 x 1403 px, so 1,856 image
tokens. Plus about 260 prompt tokens, at $0.0001/1k, plus at most 60 output tokens at
$0.0005/1k, that is about $0.00024. Tagged ``cover_names``, so ``script_cost_scope``
reports it on its own line.
"""

from __future__ import annotations

import io
import math
from typing import TYPE_CHECKING

from PIL import Image
from pydantic import Field, field_validator

from lemely.core.schemas import StrictModel
from lemely.io.llm.image_fit import PIXELS_PER_TOKEN
from lemely.io.prompts.cover_names import COVER_SYSTEM_PROMPT, VERSION, build_cover_user_prompt

if TYPE_CHECKING:
    from lemely.io.gemini import GeminiClient

COVER_TASK_TAG = "cover_names"
MAX_COVER_IMAGE_TOKENS = 2000


class CoverRead(StrictModel):
    is_cover_page: bool
    candidate_name: str | None = Field(default=None, max_length=120)
    candidate_number: str | None = Field(default=None, max_length=20)

    @field_validator("candidate_name", "candidate_number", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


def _fit(png: bytes) -> bytes:
    """``png`` shrunk, keeping its aspect, until it costs at most MAX_COVER_IMAGE_TOKENS."""
    img = Image.open(io.BytesIO(png))
    w, h = img.size
    budget_px = MAX_COVER_IMAGE_TOKENS * PIXELS_PER_TOKEN
    if w * h <= budget_px:
        return png
    scale = math.sqrt(budget_px / (w * h)) * 0.99
    small = img.convert("L").resize((max(1, int(w * scale)), max(1, int(h * scale))))
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


class CoverNameReader:
    """Reads one cover page. Uses the scan-metadata model: the same job (read the cover)."""

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

    def __call__(self, page_png: bytes, *, cache_key: str) -> CoverRead:
        return self._client.generate_structured(
            system_prompt=COVER_SYSTEM_PROMPT,
            user_prompt=build_cover_user_prompt(),
            image_parts=[_fit(page_png)],
            response_schema=CoverRead,
            prompt_version=VERSION,
            model=self._client.model_for_tag("scan_metadata"),
            task_tag=COVER_TASK_TAG,
            extra_cache_key=cache_key,
        )
```

Before committing, search `lemely/` for any allow-list of task tags (`MODEL_TABLE_TAGS`, `claude_effort_for` validators, `_KNOWN_TASK_TAGS`) and confirm none rejects `"cover_names"`. `GeminiSettings.model_for` falls back to `model` for an unknown tag, but this call passes `model=` explicitly anyway. If a validator rejects unknown tags, add `"cover_names"` to it in this task, along with its test.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PY -m pytest tests/test_cover_reader.py tests/test_scan_metadata.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/io/prompts/cover_names.py lemely/io/class_set/cover_reader.py tests/test_cover_reader.py
git commit -S -m "feat(io): read the candidate name off a cover with one Haiku call" -- lemely/io/prompts/cover_names.py lemely/io/class_set/cover_reader.py tests/test_cover_reader.py
```

### Task 6: Roster matcher (pure)

**Files:**
- Create: `lemely/core/roster_match.py`
- Test: `tests/test_roster_match.py`

**Interfaces:**
- Produces:
  - `NameStatus = Literal["matched", "ambiguous", "spelling", "not_found", "no_name", "unreadable", "confirmed", "skipped"]`
  - `RosterStudent(student_id: uuid.UUID, name: str, class_id: uuid.UUID, class_name: str)`
  - `Candidate(student: RosterStudent, score: float)`
  - `NameMatch(status: NameStatus, best: RosterStudent | None, candidates: tuple[Candidate, ...], match_pct: int)`
  - `match_name(read: str | None, roster: Sequence[RosterStudent], *, readable: bool = True) -> NameMatch`
  - `name_score(read: str, name: str) -> float`
  - `AUTO_MATCH = 0.97`, `NEAR = 0.60`, `CLOSE_GAP = 0.10`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roster_match.py
"""Roster matching for cover names: conservative, because a wrong match files marks under
the wrong student. Auto only for an exact (normalised) or near-exact unique name."""

from __future__ import annotations

import uuid

import pytest

from lemely.core.roster_match import RosterStudent, match_name, name_score

_C = uuid.uuid4()


def _s(name: str) -> RosterStudent:
    return RosterStudent(uuid.uuid4(), name, _C, "10A")


ROSTER = [_s("Omar Saleh"), _s("Omar Sherif"), _s("Nour Adel"), _s("Layla Hassan"), _s("Mohammed Ali")]


def test_exact_name_matches_automatically_ignoring_case_and_accents() -> None:
    m = match_name("layla HASSAN", ROSTER)
    assert m.status == "matched"
    assert m.best is not None and m.best.name == "Layla Hassan"
    assert match_name("Láyla Hassán", ROSTER).status == "matched"


def test_swapped_order_matches() -> None:
    assert match_name("Hassan Layla", ROSTER).status == "matched"


def test_initial_with_two_candidates_is_ambiguous() -> None:
    m = match_name("Omr S.", ROSTER)
    assert m.status == "ambiguous"
    assert {c.student.name for c in m.candidates[:2]} == {"Omar Saleh", "Omar Sherif"}
    assert 0 < m.match_pct < 60


def test_misspelling_is_a_suggestion_not_a_match() -> None:
    m = match_name("Nour Adl", ROSTER)
    assert m.status == "spelling"
    assert m.best is not None and m.best.name == "Nour Adel"
    assert m.candidates[0].student.name == "Nour Adel"
    assert m.match_pct >= 60


def test_one_letter_short_long_name_is_still_spelling() -> None:
    assert match_name("Mohamed Ali", ROSTER).status == "spelling"


def test_unknown_name() -> None:
    m = match_name("Zainab Kareem", ROSTER)
    assert m.status == "not_found"
    assert m.best is None


@pytest.mark.parametrize("read", [None, "", "   "])
def test_no_name(read: str | None) -> None:
    m = match_name(read, ROSTER)
    assert m.status == "no_name"
    assert m.match_pct == 0


def test_unreadable_cover() -> None:
    assert match_name(None, ROSTER, readable=False).status == "unreadable"


def test_empty_roster_is_not_found() -> None:
    assert match_name("Layla Hassan", []).status == "not_found"


def test_candidates_are_top_three_best_first() -> None:
    m = match_name("Omar", ROSTER)
    assert len(m.candidates) <= 3
    scores = [c.score for c in m.candidates]
    assert scores == sorted(scores, reverse=True)


def test_score_bounds() -> None:
    assert name_score("Layla Hassan", "Layla Hassan") == 1.0
    assert 0.0 <= name_score("x", "Layla Hassan") < 0.5
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PY -m pytest tests/test_roster_match.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# lemely/core/roster_match.py
"""Match a handwritten cover name to a class roster (L12). Pure and deterministic.

Conservative by design: a wrong automatic match files a student's marks under someone
else. Auto-match only when the best score is >= AUTO_MATCH (an exact name after
normalising, or order swapped) and no other student is close. Everything else goes to the
teacher's fix-it list with up to three suggestions.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import permutations
from typing import Literal

NameStatus = Literal[
    "matched", "ambiguous", "spelling", "not_found", "no_name", "unreadable", "confirmed", "skipped"
]

AUTO_MATCH = 0.97
NEAR = 0.60
CLOSE_GAP = 0.10
_TOP = 3


@dataclass(frozen=True)
class RosterStudent:
    student_id: uuid.UUID
    name: str
    class_id: uuid.UUID
    class_name: str


@dataclass(frozen=True)
class Candidate:
    student: RosterStudent
    score: float


@dataclass(frozen=True)
class NameMatch:
    status: NameStatus
    best: RosterStudent | None
    candidates: tuple[Candidate, ...]
    match_pct: int


def _normalise(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", text)
    letters = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-z\s]", " ", letters.casefold())
    return cleaned.split()


def _token_score(read: list[str], name: list[str]) -> float:
    """Each read token against its best name token; an initial matches a token it starts."""
    if not read or not name:
        return 0.0
    total = 0.0
    weight = 0
    for token in read:
        if len(token) == 1:
            best = 1.0 if any(n.startswith(token) for n in name) else 0.0
        else:
            best = max(SequenceMatcher(None, token, n).ratio() for n in name)
        total += best * len(token)
        weight += len(token)
    coverage = min(len(read), len(name)) / max(len(read), len(name))
    return (total / weight) * (0.85 + 0.15 * coverage)


def name_score(read: str, name: str) -> float:
    r, n = _normalise(read), _normalise(name)
    if not r or not n:
        return 0.0
    if r == n:
        return 1.0
    whole = max(
        SequenceMatcher(None, " ".join(p), " ".join(n)).ratio() for p in permutations(r[:4])
    )
    return round(max(whole, _token_score(r, n)), 4)


def match_name(
    read: str | None, roster: Sequence[RosterStudent], *, readable: bool = True
) -> NameMatch:
    if not readable:
        return NameMatch("unreadable", None, (), 0)
    if read is None or not read.strip():
        return NameMatch("no_name", None, (), 0)
    ranked = sorted(
        (Candidate(s, name_score(read, s.name)) for s in roster),
        key=lambda c: (-c.score, c.student.name),
    )
    top = tuple(c for c in ranked[:_TOP] if c.score >= NEAR / 2)
    if not ranked or ranked[0].score < NEAR:
        return NameMatch("not_found", None, top, round(100 * (ranked[0].score if ranked else 0)))
    best = ranked[0]
    close = [c for c in ranked if best.score - c.score <= CLOSE_GAP]
    if len(close) > 1:
        return NameMatch("ambiguous", None, top, round(100 * best.score / len(close)))
    if best.score >= AUTO_MATCH:
        return NameMatch("matched", best.student, top, round(100 * best.score))
    return NameMatch("spelling", best.student, top, round(100 * best.score))
```

Check the tests against the code. "Omr S." against both Omars scores about 0.86 each, so they are close: ambiguous, with pct 86/2 = 43. "Nour Adl" against "Nour Adel" scores about 0.94 and against nothing else within 0.10: spelling, with pct 94. "Mohamed Ali" against "Mohammed Ali" scores about 0.96, below 0.97: spelling. Adjust the code, not the test, if a value lands on the wrong side.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PY -m pytest tests/test_roster_match.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/core/roster_match.py tests/test_roster_match.py
git commit -S -m "feat(core): conservative roster matcher for cover names" -- lemely/core/roster_match.py tests/test_roster_match.py
```

### Task 7: Migration `0055_class_sets` and ORM models

> **User approval required before this migration runs on any shared database** (staging or prod). Writing it and testing it on the throwaway test database is allowed.

**Files:**
- Create: `lemely/db/models/class_sets.py`, `lemely/db/migrations/versions/0055_class_sets.py`
- Modify: `lemely/db/models/__init__.py` (import the module the same way the others are imported, so `import_all_models()` sees it)
- Test: `tests/test_migration_0055_class_sets.py`

**Interfaces:**
- Produces:
  - Table `class_sets`, with columns: `id` uuid PK, `uploaded_by` uuid FK users CASCADE, `class_id` uuid FK classes SET NULL, `storage_path`, `scheme_storage_path`, `original_filename`, `byte_size`, `status` varchar(16) CHECK in (`reading`,`ready`,`failed`), `page_count`, `paper_count`, `error`, `created_at`, `updated_at`, `deleted_at`
  - Table `class_set_papers`, with columns: `paper_id` uuid PK FK teacher_papers CASCADE, `set_id` uuid FK class_sets CASCADE, `page_start`, `page_end`, `cover_name` varchar(120), `cover_number` varchar(20), `name_status` varchar(16) CHECK, `match_pct` smallint, `candidates` JSONB, `pages_differ` bool, `student_name` varchar(200), `cover_cost_usd` numeric(10,6)
- ORM: `ClassSet`, `ClassSetPaper`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_0055_class_sets.py
"""Migration 0055_class_sets: two new tables, nothing else touched. Downgrade drops both."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import current_revision, head_revision, upgrade_head

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0055_class_sets"
TABLES = ("class_sets", "class_set_papers")


def _down_revision() -> str:
    script = ScriptDirectory.from_config(Config("alembic.ini")).get_revision(REVISION)
    assert script is not None
    return str(script.down_revision)


def _user(session: Session) -> uuid.UUID:
    uid = uuid.uuid4()
    session.execute(
        sa.text("INSERT INTO users (id, email, role) VALUES (:i, :e, 'teacher')"),
        {"i": uid, "e": f"{uid.hex}@example.com"},
    )
    return uid


def test_revision_is_well_formed() -> None:
    assert len(REVISION) <= 32
    assert _down_revision() != "None"


def test_tables_match_the_orm(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        diff = compare_metadata(
            MigrationContext.configure(session.connection(), opts={"compare_type": True}),
            Base.metadata,
        )
    assert [d for d in diff if any(t in repr(d) for t in TABLES)] == []


def test_status_and_name_status_are_checked(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        uid = _user(session)
        with pytest.raises(sa.exc.IntegrityError):
            session.execute(
                sa.text(
                    "INSERT INTO class_sets (uploaded_by, storage_path, status) "
                    "VALUES (:u, 'k', 'bogus')"
                ),
                {"u": uid},
            )
        session.rollback()


def test_deleting_a_paper_removes_its_link(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        uid = _user(session)
        set_id = session.execute(
            sa.text(
                "INSERT INTO class_sets (uploaded_by, storage_path, status) "
                "VALUES (:u, 'k', 'reading') RETURNING id"
            ),
            {"u": uid},
        ).scalar_one()
        paper_id = session.execute(
            sa.text(
                "INSERT INTO teacher_papers (uploaded_by, storage_path) VALUES (:u, 'p') RETURNING id"
            ),
            {"u": uid},
        ).scalar_one()
        session.execute(
            sa.text(
                "INSERT INTO class_set_papers (paper_id, set_id, page_start, page_end, name_status, "
                "match_pct, pages_differ) VALUES (:p, :s, 0, 3, 'no_name', 0, false)"
            ),
            {"p": paper_id, "s": set_id},
        )
        session.execute(sa.text("DELETE FROM teacher_papers WHERE id = :p"), {"p": paper_id})
        assert session.execute(sa.text("SELECT count(*) FROM class_set_papers")).scalar_one() == 0


def test_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    down = _down_revision()
    downgrade_to(down)
    with sm() as session:
        assert current_revision(session) == down
        for table in TABLES:
            assert session.execute(sa.text("SELECT to_regclass(:t)"), {"t": table}).scalar_one() is None
    upgrade_head()
    with sm() as session:
        assert current_revision(session) == head_revision()
```

Before running, check the `users` insert columns against `lemely/db/models/users.py`. If `users` has more NOT NULL columns, add them, copying from `tests/test_migration_tutor_reviews.py`'s user seed.

- [ ] **Step 2: Run it to make sure it fails**

Run: `PY -m pytest tests/test_migration_0055_class_sets.py -q`
Expected: FAIL, because `get_revision` returns None for `0055_class_sets`.

- [ ] **Step 3: Implement**

```python
# lemely/db/models/class_sets.py
"""A whole class set uploaded as one PDF, and each student's paper cut from it (L12)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin

CLASS_SET_STATUSES = ("reading", "ready", "failed")
NAME_STATUSES = (
    "matched", "ambiguous", "spelling", "not_found", "no_name", "unreadable", "confirmed", "skipped"
)


class ClassSet(TimestampMixin, Base):
    __tablename__ = "class_sets"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('reading', 'ready', 'failed')", name="ck_class_sets_status"
        ),
        sa.Index("ix_class_sets_uploaded_by_created_at", "uploaded_by", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="SET NULL"), nullable=True
    )
    storage_path: Mapped[str] = mapped_column(sa.String, nullable=False)
    scheme_storage_path: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'reading'")
    )
    page_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    paper_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class ClassSetPaper(Base):
    __tablename__ = "class_set_papers"
    __table_args__ = (
        sa.CheckConstraint(
            "name_status IN ('matched', 'ambiguous', 'spelling', 'not_found', 'no_name', "
            "'unreadable', 'confirmed', 'skipped')",
            name="ck_class_set_papers_name_status",
        ),
        sa.CheckConstraint("page_end >= page_start", name="ck_class_set_papers_pages"),
        sa.Index("ix_class_set_papers_set_id", "set_id"),
    )

    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("teacher_papers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("class_sets.id", ondelete="CASCADE"), nullable=False
    )
    page_start: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    cover_name: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    cover_number: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    name_status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    match_pct: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    candidates: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
    pages_differ: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    student_name: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    cover_cost_usd: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 6), nullable=True)


__all__ = ["CLASS_SET_STATUSES", "NAME_STATUSES", "ClassSet", "ClassSetPaper"]
```

```python
# lemely/db/migrations/versions/0055_class_sets.py
"""class sets: one uploaded class-set PDF and the per-student papers cut from it (L12).

Revision ID: 0055_class_sets
Revises: 0054_waitlist_email_confirmation
Create Date: 2026-11-15 00:00:00.000000

Two new tables. Additive: no existing table or row changes. ``class_set_papers.paper_id`` is
the child ``teacher_papers`` row (CASCADE), so deleting a paper removes its link, and
deleting a set removes every link (the papers stay, as ordinary console papers).

``downgrade`` drops both tables. Rebase ``down_revision`` onto develop's head before merge
(master plan, Shared files).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055_class_sets"
down_revision: str | Sequence[str] | None = "0054_waitlist_email_confirmation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "class_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("classes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("scheme_storage_path", sa.String(), nullable=True),
        sa.Column("original_filename", sa.String(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'reading'")),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("paper_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('reading', 'ready', 'failed')", name="ck_class_sets_status"),
    )
    op.create_index("ix_class_sets_uploaded_by_created_at", "class_sets",
                    ["uploaded_by", "created_at"])
    op.create_table(
        "class_set_papers",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("teacher_papers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("set_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("class_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("cover_name", sa.String(120), nullable=True),
        sa.Column("cover_number", sa.String(20), nullable=True),
        sa.Column("name_status", sa.String(16), nullable=False),
        sa.Column("match_pct", sa.SmallInteger(), nullable=False),
        sa.Column("candidates", postgresql.JSONB(), nullable=True),
        sa.Column("pages_differ", sa.Boolean(), nullable=False),
        sa.Column("student_name", sa.String(200), nullable=True),
        sa.Column("cover_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.CheckConstraint(
            "name_status IN ('matched', 'ambiguous', 'spelling', 'not_found', 'no_name', "
            "'unreadable', 'confirmed', 'skipped')",
            name="ck_class_set_papers_name_status",
        ),
        sa.CheckConstraint("page_end >= page_start", name="ck_class_set_papers_pages"),
    )
    op.create_index("ix_class_set_papers_set_id", "class_set_papers", ["set_id"])


def downgrade() -> None:
    op.drop_index("ix_class_set_papers_set_id", table_name="class_set_papers")
    op.drop_table("class_set_papers")
    op.drop_index("ix_class_sets_uploaded_by_created_at", table_name="class_sets")
    op.drop_table("class_sets")
```

Check how `TimestampMixin` declares `created_at` and `updated_at` (server defaults, `onupdate`) in `lemely/db/models/enums.py`, and mirror its exact column definitions in the migration so `compare_metadata` is clean. Then check `alembic heads` at implementation time. If develop's head is no longer `0054_waitlist_email_confirmation` (L6 may add a migration), set `down_revision` to the current head.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PY -m pytest tests/test_migration_0055_class_sets.py -q`
Expected: PASS (needs the local test Postgres).

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/db/models/class_sets.py lemely/db/models/__init__.py lemely/db/migrations/versions/0055_class_sets.py tests/test_migration_0055_class_sets.py
git commit -S -m "feat(db): class_sets and class_set_papers tables (migration 0055)" -- lemely/db/models/class_sets.py lemely/db/models/__init__.py lemely/db/migrations/versions/0055_class_sets.py tests/test_migration_0055_class_sets.py
```

### Task 8: `ClassSetRepository`

**Files:**
- Create: `lemely/db/class_set_repo.py`
- Test: `tests/test_class_set_repo.py`

**Interfaces:**
- Consumes: the Task 7 models, `NameMatch` (Task 6), `TeacherPaper`, and the `teacher_paper_visible` pattern
- Produces:
  - `class_set_visible(viewer_id: uuid.UUID, viewer_role: Role) -> ColumnElement[bool]`
  - `ClassSetRow(id, uploaded_by, class_id, storage_path, scheme_storage_path, original_filename, status, page_count, paper_count, error, created_at)`
  - `SetPaperRow(paper_id, page_start, page_end, cover_name, name_status, match_pct, candidates: list[dict], pages_differ, student_id, student_name, paper_status: UploadStatus, has_report: bool, metadata: ExamMetadata | None)`
  - `ClassSetRepository(sm)` with these methods:
    - `.create(...) -> uuid.UUID`
    - `.get(set_id) -> ClassSetRow | None` (worker only)
    - `.get_visible(set_id, *, viewer_id, viewer_role) -> ClassSetRow | None`
    - `.list_visible(*, viewer_id, viewer_role, limit=20) -> list[ClassSetRow]`
    - `.mark_ready(set_id, *, page_count, paper_count, class_id)`
    - `.fail(set_id, error)`
    - `.attach_paper(*, paper_id, set_id, split, match, cover_name, cover_number, pages_differ, cover_cost_usd)`
    - `.papers(set_id) -> list[SetPaperRow]`
    - `.resolve(set_id, paper_id, *, student_id, student_name) -> bool`
    - `.skip(set_id, paper_id) -> bool`

  If `matched` is auto, `attach_paper` also writes `teacher_papers.student_id` and `student_name`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_class_set_repo.py
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from lemely.core.roster_match import Candidate, NameMatch, RosterStudent
from lemely.db.class_set_repo import ClassSetRepository
from lemely.db.models.enums import Role
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.io.class_set.covers import PaperSplit
from tests.test_web_teacher import _seed_user  # existing helper: (sm, role, display_name)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _repos(sm: sessionmaker[Session]) -> tuple[ClassSetRepository, TeacherPaperRepository]:
    return ClassSetRepository(sm), TeacherPaperRepository(sm, stale_after=timedelta(minutes=15))


def _paper(papers: TeacherPaperRepository, owner: uuid.UUID) -> uuid.UUID:
    pid = uuid.uuid4()
    papers.create(paper_id=pid, uploaded_by=owner, storage_path=f"k/{pid}", scheme_storage_path=None,
                  original_filename="s.pdf", content_type="application/pdf", byte_size=1)
    return pid


def test_owner_sees_set_other_teacher_does_not(pg_sessionmaker: sessionmaker[Session]) -> None:
    sets, _ = _repos(pg_sessionmaker)
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    other = _seed_user(pg_sessionmaker, Role.teacher)
    set_id = sets.create(uploaded_by=owner, class_id=None, storage_path="k", scheme_storage_path=None,
                         original_filename="set.pdf", byte_size=10)
    assert sets.get_visible(set_id, viewer_id=owner, viewer_role=Role.teacher) is not None
    assert sets.get_visible(set_id, viewer_id=other, viewer_role=Role.teacher) is None
    assert sets.list_visible(viewer_id=other, viewer_role=Role.teacher) == []
    assert sets.get_visible(set_id, viewer_id=other, viewer_role=Role.platform_admin) is not None


def test_attach_auto_match_writes_student_and_resolve_skip(pg_sessionmaker: sessionmaker[Session]) -> None:
    sets, papers = _repos(pg_sessionmaker)
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, "Layla Hassan")
    set_id = sets.create(uploaded_by=owner, class_id=None, storage_path="k", scheme_storage_path=None,
                         original_filename="set.pdf", byte_size=10)
    p1, p2 = _paper(papers, owner), _paper(papers, owner)
    rs = RosterStudent(student, "Layla Hassan", uuid.uuid4(), "10A")
    sets.attach_paper(paper_id=p1, set_id=set_id, split=PaperSplit(0, 3),
                      match=NameMatch("matched", rs, (Candidate(rs, 1.0),), 100),
                      cover_name="Layla Hassan", cover_number=None, pages_differ=False,
                      cover_cost_usd=Decimal("0.000240"))
    sets.attach_paper(paper_id=p2, set_id=set_id, split=PaperSplit(4, 7),
                      match=NameMatch("no_name", None, (), 0), cover_name=None, cover_number=None,
                      pages_differ=False, cover_cost_usd=Decimal("0.000230"))
    rows = {r.paper_id: r for r in sets.papers(set_id)}
    assert rows[p1].student_id == student and rows[p1].student_name == "Layla Hassan"
    assert rows[p2].name_status == "no_name" and rows[p2].student_id is None
    assert papers.get(p1).student_id == student  # type: ignore[union-attr]

    assert sets.resolve(set_id, p2, student_id=student, student_name="Layla Hassan") is True
    assert {r.paper_id: r for r in sets.papers(set_id)}[p2].name_status == "confirmed"
    assert sets.skip(set_id, p1) is True
    row = {r.paper_id: r for r in sets.papers(set_id)}[p1]
    assert row.name_status == "skipped" and row.student_id is None
    # A paper from another set is never touched through this set's id.
    assert sets.resolve(uuid.uuid4(), p2, student_id=student, student_name="x") is False


def test_mark_ready_and_fail(pg_sessionmaker: sessionmaker[Session]) -> None:
    sets, _ = _repos(pg_sessionmaker)
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    set_id = sets.create(uploaded_by=owner, class_id=None, storage_path="k", scheme_storage_path=None,
                         original_filename="set.pdf", byte_size=10)
    sets.mark_ready(set_id, page_count=48, paper_count=3, class_id=None)
    row = sets.get(set_id)
    assert row is not None and (row.status, row.page_count, row.paper_count) == ("ready", 48, 3)
    sets.fail(set_id, "Couldn't split this file.")
    row = sets.get(set_id)
    assert row is not None and row.status == "failed" and row.error == "Couldn't split this file."
```

`_seed_user` lives in `tests/test_web_teacher.py:286`. If its signature differs (role first, a display_name keyword), adapt the call sites to it, not the helper.

- [ ] **Step 2: Run it to make sure it fails**

Run: `PY -m pytest tests/test_class_set_repo.py -q`
Expected: FAIL with `ModuleNotFoundError: lemely.db.class_set_repo`.

- [ ] **Step 3: Implement**

```python
# lemely/db/class_set_repo.py
"""Class sets and the per-student papers cut from them (L12).

Visibility is DS11's rule, applied to ``ClassSet.uploaded_by`` with the same shape as
:func:`~lemely.db.teacher_paper_repo.teacher_paper_visible`: the owner, a school admin over
their school's teachers, a platform admin. A set's child papers are ordinary
``teacher_papers`` rows owned by the same uploader, so the grading console's own rule
already agrees about them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import or_, select

from lemely.core.schemas import ExamMetadata
from lemely.db.models.class_sets import ClassSet, ClassSetPaper
from lemely.db.models.enums import MembershipRole, Role, UploadStatus
from lemely.db.models.orgs import SchoolMembership
from lemely.db.models.teacher_papers import TeacherPaper

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.sql.elements import ColumnElement

    from lemely.core.roster_match import NameMatch
    from lemely.io.class_set.covers import PaperSplit


def class_set_visible(viewer_id: uuid.UUID, viewer_role: Role) -> ColumnElement[bool]:
    if viewer_role is Role.platform_admin:
        return sa.true()
    own = ClassSet.uploaded_by == viewer_id
    if viewer_role is not Role.school_admin:
        return own
    admin_schools = select(SchoolMembership.school_id).where(
        SchoolMembership.user_id == viewer_id,
        SchoolMembership.membership_role == MembershipRole.school_admin,
    )
    teachers = select(SchoolMembership.user_id).where(
        SchoolMembership.school_id.in_(admin_schools),
        SchoolMembership.membership_role == MembershipRole.teacher,
    )
    return or_(own, ClassSet.uploaded_by.in_(teachers))


@dataclass(frozen=True)
class ClassSetRow:
    id: uuid.UUID
    uploaded_by: uuid.UUID
    class_id: uuid.UUID | None
    storage_path: str
    scheme_storage_path: str | None
    original_filename: str | None
    status: str
    page_count: int | None
    paper_count: int | None
    error: str | None
    created_at: datetime


@dataclass(frozen=True)
class SetPaperRow:
    paper_id: uuid.UUID
    page_start: int
    page_end: int
    cover_name: str | None
    name_status: str
    match_pct: int
    candidates: list[dict[str, object]]
    pages_differ: bool
    student_id: uuid.UUID | None
    student_name: str | None
    paper_status: UploadStatus
    has_report: bool
    metadata: ExamMetadata | None


def _row(s: ClassSet) -> ClassSetRow:
    return ClassSetRow(s.id, s.uploaded_by, s.class_id, s.storage_path, s.scheme_storage_path,
                       s.original_filename, s.status, s.page_count, s.paper_count, s.error,
                       s.created_at)


class ClassSetRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sm = session_factory

    def create(self, *, uploaded_by: uuid.UUID, class_id: uuid.UUID | None, storage_path: str,
               scheme_storage_path: str | None, original_filename: str | None,
               byte_size: int | None, set_id: uuid.UUID | None = None) -> uuid.UUID:
        new_id = set_id or uuid.uuid4()
        with self._sm.begin() as session:
            session.add(ClassSet(id=new_id, uploaded_by=uploaded_by, class_id=class_id,
                                 storage_path=storage_path, scheme_storage_path=scheme_storage_path,
                                 original_filename=original_filename, byte_size=byte_size))
        return new_id

    def get(self, set_id: uuid.UUID) -> ClassSetRow | None:
        with self._sm() as session:
            row = session.get(ClassSet, set_id)
            return None if row is None or row.deleted_at is not None else _row(row)

    def get_visible(self, set_id: uuid.UUID, *, viewer_id: uuid.UUID,
                    viewer_role: Role) -> ClassSetRow | None:
        stmt = select(ClassSet).where(ClassSet.id == set_id, ClassSet.deleted_at.is_(None),
                                      class_set_visible(viewer_id, viewer_role))
        with self._sm() as session:
            row = session.scalars(stmt).one_or_none()
            return None if row is None else _row(row)

    def list_visible(self, *, viewer_id: uuid.UUID, viewer_role: Role,
                     limit: int = 20) -> list[ClassSetRow]:
        stmt = (select(ClassSet)
                .where(ClassSet.deleted_at.is_(None), class_set_visible(viewer_id, viewer_role))
                .order_by(ClassSet.created_at.desc()).limit(limit))
        with self._sm() as session:
            return [_row(r) for r in session.scalars(stmt)]

    def mark_ready(self, set_id: uuid.UUID, *, page_count: int, paper_count: int,
                   class_id: uuid.UUID | None) -> None:
        values: dict[str, object] = {"status": "ready", "page_count": page_count,
                                     "paper_count": paper_count, "updated_at": datetime.now(UTC)}
        if class_id is not None:
            values["class_id"] = class_id
        with self._sm.begin() as session:
            session.execute(sa.update(ClassSet).where(ClassSet.id == set_id).values(**values))

    def fail(self, set_id: uuid.UUID, error: str) -> None:
        with self._sm.begin() as session:
            session.execute(sa.update(ClassSet).where(ClassSet.id == set_id)
                            .values(status="failed", error=error, updated_at=datetime.now(UTC)))

    def attach_paper(self, *, paper_id: uuid.UUID, set_id: uuid.UUID, split: PaperSplit,
                     match: NameMatch, cover_name: str | None, cover_number: str | None,
                     pages_differ: bool, cover_cost_usd: Decimal | None) -> None:
        auto = match.status == "matched" and match.best is not None
        candidates = [
            {"studentId": str(c.student.student_id), "name": c.student.name,
             "classId": str(c.student.class_id), "className": c.student.class_name,
             "score": c.score}
            for c in match.candidates
        ]
        with self._sm.begin() as session:
            session.add(ClassSetPaper(
                paper_id=paper_id, set_id=set_id, page_start=split.start, page_end=split.end,
                cover_name=cover_name, cover_number=cover_number, name_status=match.status,
                match_pct=match.match_pct, candidates=candidates, pages_differ=pages_differ,
                student_name=match.best.name if auto and match.best else None,
                cover_cost_usd=cover_cost_usd))
            if auto and match.best is not None:
                session.execute(sa.update(TeacherPaper).where(TeacherPaper.id == paper_id)
                                .values(student_id=match.best.student_id))

    def papers(self, set_id: uuid.UUID) -> list[SetPaperRow]:
        stmt = (select(ClassSetPaper, TeacherPaper)
                .join(TeacherPaper, TeacherPaper.id == ClassSetPaper.paper_id)
                .where(ClassSetPaper.set_id == set_id, TeacherPaper.deleted_at.is_(None))
                .order_by(ClassSetPaper.page_start))
        with self._sm() as session:
            out: list[SetPaperRow] = []
            for link, paper in session.execute(stmt).tuples():
                meta = ExamMetadata.model_validate(paper.metadata_json) if paper.metadata_json else None
                out.append(SetPaperRow(
                    link.paper_id, link.page_start, link.page_end, link.cover_name,
                    link.name_status, link.match_pct, list(link.candidates or []),
                    link.pages_differ, paper.student_id, link.student_name, paper.status,
                    paper.report_json is not None, meta))
            return out

    def _link(self, session: Session, set_id: uuid.UUID, paper_id: uuid.UUID) -> ClassSetPaper | None:
        return session.scalars(select(ClassSetPaper).where(
            ClassSetPaper.set_id == set_id, ClassSetPaper.paper_id == paper_id)).one_or_none()

    def resolve(self, set_id: uuid.UUID, paper_id: uuid.UUID, *, student_id: uuid.UUID,
                student_name: str) -> bool:
        with self._sm.begin() as session:
            link = self._link(session, set_id, paper_id)
            if link is None:
                return False
            link.name_status = "confirmed"
            link.student_name = student_name
            session.execute(sa.update(TeacherPaper).where(TeacherPaper.id == paper_id)
                            .values(student_id=student_id))
            return True

    def skip(self, set_id: uuid.UUID, paper_id: uuid.UUID) -> bool:
        with self._sm.begin() as session:
            link = self._link(session, set_id, paper_id)
            if link is None:
                return False
            link.name_status = "skipped"
            link.student_name = None
            session.execute(sa.update(TeacherPaper).where(TeacherPaper.id == paper_id)
                            .values(student_id=None))
            return True
```

Check `TeacherPaper.metadata_json`'s stored shape against `TeacherPaperRepository._snapshot` (`lemely/db/teacher_paper_repo.py:413`) and parse metadata the same way it does.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PY -m pytest tests/test_class_set_repo.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/db/class_set_repo.py tests/test_class_set_repo.py
git commit -S -m "feat(db): class-set repository with DS11 visibility" -- lemely/db/class_set_repo.py tests/test_class_set_repo.py
```

### Task 9: Class-set job

**Files:**
- Create: `lemely/web/services/class_set_job.py`
- Test: `tests/test_class_set_job.py`

**Interfaces:**
- Consumes:
  - Task 3: `class_set_thumbnails`, `class_set_pages`, `split_class_set`
  - Task 4: `find_cover_candidates`, `plan_split`, `modal_pages`, `pages_differ`
  - Task 5: `CoverNameReader`, `COVER_TASK_TAG`
  - Task 6: `match_name`, `RosterStudent`
  - Task 8: `ClassSetRepository`
  - `TeacherPaperRepository.create`, `ClassService.list_classes` plus `.roster`, `script_cost_scope`
- Produces:
  - `roster_for(class_service, viewer_id, viewer_role, class_id) -> list[RosterStudent]`
  - `infer_class(matches) -> uuid.UUID | None`
  - `run_class_set_job(set_id, *, settings, sets, papers, storage, gemini_client, class_service, start_paper_run: Callable[[uuid.UUID], object]) -> None`
  - `FAILED_SPLIT_MESSAGE = "Couldn't split this file into papers."`
- Behaviour:
  1. Download the set.
  2. If it is not a PDF, treat it as one paper.
  3. Render thumbnails, find candidates, then render each candidate page at 120 DPI.
  4. Read every candidate. Drop a candidate after page 0 whose read says `is_cover_page=False`.
  5. Plan the split and split the PDF.
  6. For each split: upload `teacher/{uid}/{paper_id.hex}/scan.pdf`, copy the scheme, `papers.create`, match against the roster, `sets.attach_paper`, then `start_paper_run(paper_id)`.
  7. Mark the set `ready`, with the inferred `class_id`.

  Any failure before the first paper is created sets `failed` with `FAILED_SPLIT_MESSAGE` plus the refusal text. A failed cover read for one paper gives that paper `unreadable` and a cost of 0, and the set carries on.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_class_set_job.py
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lemely.core.roster_match import RosterStudent
from lemely.io.class_set.cover_reader import CoverRead
from lemely.io.class_set.pdf import CoverThumb
from lemely.io.rasterise import RasterisedPage, ScanTooLargeError
from lemely.web.services import class_set_job as job

_CLS = uuid.uuid4()
_OWNER = uuid.uuid4()


def _roster() -> list[RosterStudent]:
    return [RosterStudent(uuid.uuid4(), n, _CLS, "10A")
            for n in ("Omar Saleh", "Omar Sherif", "Nour Adel", "Layla Hassan")]


def _set_row(**kw: object) -> SimpleNamespace:
    base = dict(id=uuid.uuid4(), uploaded_by=_OWNER, class_id=None, storage_path="teacher/x/set.pdf",
                scheme_storage_path=None, original_filename="10A.pdf", status="reading")
    base.update(kw)
    return SimpleNamespace(**base)


def _deps(reads: list[CoverRead | Exception]) -> dict[str, object]:
    sets = MagicMock()
    papers = MagicMock()
    storage = MagicMock()
    storage.download.return_value = b"%PDF-1.7 fake"
    client = MagicMock()
    settings = MagicMock()
    settings.storage.bucket = "b"
    settings.gemini.paper_cost_target_usd = 0.10
    reader = MagicMock(side_effect=reads)
    return dict(sets=sets, papers=papers, storage=storage, gemini_client=client, settings=settings,
                class_service=MagicMock(), start_paper_run=MagicMock(), reader=reader)


def _run(deps: dict[str, object], row: SimpleNamespace, *, pages: int, covers: list[int]) -> None:
    deps["sets"].get.return_value = row  # type: ignore[attr-defined]
    thumbs = [CoverThumb(i, 1, 1, b"\x00") for i in range(pages)]
    with (
        patch.object(job, "looks_like_pdf_bytes", return_value=True),
        patch.object(job, "class_set_thumbnails", return_value=thumbs),
        patch.object(job, "find_cover_candidates", return_value=covers),
        patch.object(job, "class_set_pages",
                     side_effect=lambda data, idx, dpi=120.0: [RasterisedPage(i, 1, 1, b"png") for i in idx]),
        patch.object(job, "split_class_set", side_effect=lambda data, ranges: [b"%PDF" for _ in ranges]),
        patch.object(job, "roster_for", return_value=_roster()),
        patch.object(job, "CoverNameReader", return_value=deps["reader"]),
    ):
        job.run_class_set_job(
            row.id, settings=deps["settings"], sets=deps["sets"], papers=deps["papers"],
            storage=deps["storage"], gemini_client=deps["gemini_client"],
            class_service=deps["class_service"], start_paper_run=deps["start_paper_run"],
        )


def test_three_papers_split_named_and_started() -> None:
    reads = [CoverRead(is_cover_page=True, candidate_name="Layla Hassan", candidate_number=None),
             CoverRead(is_cover_page=True, candidate_name="Omr S.", candidate_number=None),
             CoverRead(is_cover_page=True, candidate_name=None, candidate_number=None)]
    deps = _deps(reads)
    row = _set_row()
    _run(deps, row, pages=12, covers=[0, 4, 8])
    attach = deps["sets"].attach_paper.call_args_list  # type: ignore[attr-defined]
    assert [c.kwargs["match"].status for c in attach] == ["matched", "ambiguous", "no_name"]
    assert [(c.kwargs["split"].start, c.kwargs["split"].end) for c in attach] == [(0, 3), (4, 7), (8, 11)]
    assert deps["start_paper_run"].call_count == 3  # type: ignore[attr-defined]
    deps["sets"].mark_ready.assert_called_once()  # type: ignore[attr-defined]
    assert deps["sets"].mark_ready.call_args.kwargs["paper_count"] == 3  # type: ignore[attr-defined]
    assert deps["papers"].create.call_count == 3  # type: ignore[attr-defined]


def test_a_candidate_the_reader_rejects_is_merged_into_the_paper_before() -> None:
    reads = [CoverRead(is_cover_page=True, candidate_name="Layla Hassan", candidate_number=None),
             CoverRead(is_cover_page=False, candidate_name=None, candidate_number=None)]
    deps = _deps(reads)
    _run(deps, _set_row(), pages=8, covers=[0, 4])
    attach = deps["sets"].attach_paper.call_args_list  # type: ignore[attr-defined]
    assert len(attach) == 1
    assert (attach[0].kwargs["split"].start, attach[0].kwargs["split"].end) == (0, 7)


def test_one_failed_read_marks_that_paper_unreadable_and_carries_on() -> None:
    reads = [RuntimeError("timeout"),
             CoverRead(is_cover_page=True, candidate_name="Nour Adel", candidate_number=None)]
    deps = _deps(reads)
    _run(deps, _set_row(), pages=8, covers=[0, 4])
    attach = deps["sets"].attach_paper.call_args_list  # type: ignore[attr-defined]
    assert [c.kwargs["match"].status for c in attach] == ["unreadable", "matched"]
    assert attach[0].kwargs["cover_cost_usd"] == Decimal("0")


def test_refused_file_fails_the_set_and_creates_nothing() -> None:
    deps = _deps([])
    deps["sets"].get.return_value = _set_row()  # type: ignore[attr-defined]
    with (patch.object(job, "looks_like_pdf_bytes", return_value=True),
          patch.object(job, "class_set_thumbnails", side_effect=ScanTooLargeError("too many", reason="page_cap"))):
        job.run_class_set_job(uuid.uuid4(), settings=deps["settings"], sets=deps["sets"],
                              papers=deps["papers"], storage=deps["storage"],
                              gemini_client=deps["gemini_client"], class_service=deps["class_service"],
                              start_paper_run=deps["start_paper_run"])
    deps["sets"].fail.assert_called_once()  # type: ignore[attr-defined]
    assert deps["sets"].fail.call_args.args[1].startswith(job.FAILED_SPLIT_MESSAGE)  # type: ignore[attr-defined]
    deps["papers"].create.assert_not_called()  # type: ignore[attr-defined]


def test_pages_differ_is_flagged_against_the_modal_length() -> None:
    reads = [CoverRead(is_cover_page=True, candidate_name=n, candidate_number=None)
             for n in ("Layla Hassan", "Nour Adel", "Omar Saleh")]
    deps = _deps(reads)
    _run(deps, _set_row(), pages=16, covers=[0, 4, 8])
    flags = [c.kwargs["pages_differ"] for c in deps["sets"].attach_paper.call_args_list]  # type: ignore[attr-defined]
    assert flags == [False, False, True]


def test_infer_class_takes_the_class_with_most_auto_matches() -> None:
    from lemely.core.roster_match import NameMatch
    a, b = uuid.uuid4(), uuid.uuid4()
    s = lambda c: RosterStudent(uuid.uuid4(), "n", c, "x")  # noqa: E731
    matches = [NameMatch("matched", s(a), (), 100), NameMatch("matched", s(a), (), 100),
               NameMatch("matched", s(b), (), 100), NameMatch("no_name", None, (), 0)]
    assert job.infer_class(matches) == a
    assert job.infer_class([NameMatch("matched", s(a), (), 100), NameMatch("matched", s(b), (), 100)]) is None


def test_non_pdf_is_one_paper() -> None:
    reads = [CoverRead(is_cover_page=True, candidate_name="Layla Hassan", candidate_number=None)]
    deps = _deps(reads)
    row = _set_row(original_filename="photo.jpg")
    deps["sets"].get.return_value = row  # type: ignore[attr-defined]
    with (patch.object(job, "looks_like_pdf_bytes", return_value=False),
          patch.object(job, "roster_for", return_value=_roster()),
          patch.object(job, "render_image_page", return_value=b"png"),
          patch.object(job, "CoverNameReader", return_value=deps["reader"])):
        job.run_class_set_job(row.id, settings=deps["settings"], sets=deps["sets"], papers=deps["papers"],
                              storage=deps["storage"], gemini_client=deps["gemini_client"],
                              class_service=deps["class_service"], start_paper_run=deps["start_paper_run"])
    assert deps["papers"].create.call_count == 1  # type: ignore[attr-defined]
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PY -m pytest tests/test_class_set_job.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# lemely/web/services/class_set_job.py
"""Split a class set into per-student papers, read their names, start their marking (L12).

Runs on its own one-worker pool (``routers/class_sets._class_set_pool``), never on the
request. Order matters: covers are confirmed by the read BEFORE the PDF is split, so a page
that only looked like a cover never becomes a paper of its own.
"""

from __future__ import annotations

import io
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from PIL import Image

from lemely.core.roster_match import NameMatch, RosterStudent, match_name
from lemely.io.class_set.cover_reader import COVER_TASK_TAG, CoverNameReader, CoverRead
from lemely.io.class_set.covers import (
    PaperSplit,
    find_cover_candidates,
    modal_pages,
    pages_differ,
    plan_split,
)
from lemely.io.class_set.pdf import class_set_pages, class_set_thumbnails, split_class_set
from lemely.io.gemini import script_cost_scope
from lemely.io.rasterise import PDF_MAGIC

if TYPE_CHECKING:
    from lemely.db.class_repo import ClassService
    from lemely.db.class_set_repo import ClassSetRepository
    from lemely.db.models.enums import Role
    from lemely.db.teacher_paper_repo import TeacherPaperRepository
    from lemely.io.gemini import GeminiClient
    from lemely.io.storage import StorageBackend
    from lemely.runtime.config import Settings

log = structlog.get_logger(__name__)

FAILED_SPLIT_MESSAGE = "Couldn't split this file into papers."
_COVER_DPI = 120.0


def looks_like_pdf_bytes(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(PDF_MAGIC)


def render_image_page(data: bytes) -> bytes:
    """A single uploaded image as PNG. Pillow decode of an image the upload check passed."""
    img = Image.open(io.BytesIO(data)).convert("L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def roster_for(class_service: ClassService, viewer_id: uuid.UUID, viewer_role: Role,
               class_id: uuid.UUID | None) -> list[RosterStudent]:
    """The students a cover may name: one class when given, else every class the viewer sees."""
    classes = class_service.list_classes(viewer_id, viewer_role)
    if class_id is not None:
        classes = [c for c in classes if c.class_id == class_id]
    out: list[RosterStudent] = []
    for cls in classes:
        for entry in class_service.roster(viewer_id, viewer_role, cls.class_id):
            out.append(RosterStudent(entry.student_id, entry.display_name, cls.class_id, cls.name))
    return out


def infer_class(matches: Sequence[NameMatch]) -> uuid.UUID | None:
    """The class most auto-matched students sit in; None on a tie or no matches."""
    counts = Counter(m.best.class_id for m in matches if m.status == "matched" and m.best)
    if not counts:
        return None
    ranked = counts.most_common(2)
    if len(ranked) == 2 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def _read(reader: CoverNameReader, png: bytes, key: str) -> CoverRead | None:
    try:
        return reader(png, cache_key=key)
    except Exception:
        log.exception("class_set_cover_read_failed", cache_key=key)
        return None


def run_class_set_job(
    set_id: uuid.UUID, *, settings: Settings, sets: ClassSetRepository,
    papers: TeacherPaperRepository, storage: StorageBackend, gemini_client: GeminiClient,
    class_service: ClassService, start_paper_run: Callable[[uuid.UUID], object],
) -> None:
    from lemely.db.models.enums import Role

    row = sets.get(set_id)
    if row is None:
        return
    bucket = settings.storage.bucket
    try:
        data = storage.download(bucket, row.storage_path)
        scheme = (storage.download(bucket, row.scheme_storage_path)
                  if row.scheme_storage_path else None)
        reader = CoverNameReader(gemini_client)
        reads: dict[int, CoverRead | None] = {}
        costs_by_page: dict[int, Decimal] = {}
        with script_cost_scope(settings, script_key=f"class_set:{set_id}") as costs:
            if looks_like_pdf_bytes(data):
                thumbs = class_set_thumbnails(data)
                page_count = len(thumbs)
                candidates = find_cover_candidates(thumbs)
                rendered = {p.index: p.png_bytes
                            for p in class_set_pages(data, candidates, dpi=_COVER_DPI)}
            else:
                page_count, candidates = 1, [0]
                rendered = {0: render_image_page(data)}
            for index in candidates:
                before = costs.get(COVER_TASK_TAG, 0.0)
                reads[index] = _read(reader, rendered[index], f"{set_id}:{index}")
                costs_by_page[index] = Decimal(str(round(costs.get(COVER_TASK_TAG, 0.0) - before, 6)))
        covers = [i for i in candidates
                  if i == 0 or (reads.get(i) is not None and reads[i].is_cover_page)]  # type: ignore[union-attr]
        splits = plan_split(page_count, covers)
        children = (split_class_set(data, [(s.start, s.end) for s in splits])
                    if looks_like_pdf_bytes(data) else [data])
    except Exception as exc:
        log.exception("class_set_split_failed", set_id=str(set_id))
        sets.fail(set_id, f"{FAILED_SPLIT_MESSAGE} {exc}".strip())
        return

    roster = roster_for(class_service, row.uploaded_by, Role.teacher, row.class_id)
    modal = modal_pages(splits)
    matches: list[NameMatch] = []
    for split, child in zip(splits, children, strict=True):
        paper_id = uuid.uuid4()
        prefix = f"teacher/{row.uploaded_by}/{paper_id.hex}"
        name = "scan.pdf" if looks_like_pdf_bytes(child) else (row.original_filename or "scan.jpg")
        storage.upload(bucket, f"{prefix}/{name}", child,
                       "application/pdf" if name.endswith(".pdf") else None)
        scheme_key = None
        if scheme is not None:
            scheme_key = f"{prefix}/mark_scheme.pdf"
            storage.upload(bucket, scheme_key, scheme, "application/pdf")
        papers.create(paper_id=paper_id, uploaded_by=row.uploaded_by, storage_path=f"{prefix}/{name}",
                      scheme_storage_path=scheme_key,
                      original_filename=f"{row.original_filename or 'set'} p.{split.start + 1}",
                      content_type="application/pdf", byte_size=len(child))
        read = reads.get(split.start)
        match = match_name(
            read.candidate_name if read is not None else None, roster, readable=read is not None
        )
        matches.append(match)
        sets.attach_paper(
            paper_id=paper_id, set_id=set_id, split=split, match=match,
            cover_name=read.candidate_name if read else None,
            cover_number=read.candidate_number if read else None,
            pages_differ=pages_differ(split, modal),
            cover_cost_usd=costs_by_page.get(split.start, Decimal("0")),
        )
        start_paper_run(paper_id)
    sets.mark_ready(set_id, page_count=page_count, paper_count=len(splits),
                    class_id=row.class_id or infer_class(matches))
```

Two points to settle while implementing:
1. **The roster role.** `row.uploaded_by` acts as a teacher because the upload route only accepts staff. A school admin uploading their own set should see their school's classes, so the router stores the uploader's role. Add a `uploader_role: Role` parameter to `run_class_set_job`, passed from the route, and use it here instead of `Role.teacher`. Update the test's calls (add `uploader_role=Role.teacher`).
2. **`PDF_MAGIC`.** It is exported from `lemely.io.rasterise` (it is in `__all__`). Confirm it is `bytes`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PY -m pytest tests/test_class_set_job.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/web/services/class_set_job.py tests/test_class_set_job.py
git commit -S -m "feat(web): class-set job splits, reads names and starts marking" -- lemely/web/services/class_set_job.py tests/test_class_set_job.py
```

### Task 10: Class-set routes, DTOs and authz

**Files:**
- Create: `lemely/web/schemas_class_sets.py`, `lemely/web/routers/class_sets.py`
- Modify: `lemely/web/deps.py` (add `get_class_set_repo`, an `lru_cache` singleton like `get_teacher_paper_repo` at line 163)
- Modify: `lemely/web/app.py` (one `include_router` line plus its import)
- Modify: `tests/test_authz_matrix_complete.py` (the `EXPECTED` rows)
- Test: `tests/test_class_set_routes.py`

**Interfaces:**
- Routes. Every route is under prefix `/api`, guarded by `require_role(teacher, school_admin, platform_admin)`, and uses `get_auth_context` from `lemely/web/deps.py`:
  - `POST /api/class-sets` takes multipart `scan`, an optional `mark_scheme` and an optional form `class_id`, and returns `ClassSetCreatedDTO{setId}`. It validates the 25 MB cap and the class (404 when `class_id` is not one of the caller's classes), stores the file, creates the row and submits the job.
  - `GET /api/class-sets` returns `ClassSetListDTO{sets: ClassSetSummaryDTO[]}`.
  - `GET /api/class-sets/{set_id}/names` returns `ClassSetNamesDTO`, or 404 when the set is not visible.
  - `POST /api/class-sets/{set_id}/papers/{paper_id}/name` takes `{studentId}` and returns 204. It returns 404 when the set or paper is not visible, and 422 when the student is not on the caller's rosters.
  - `POST /api/class-sets/{set_id}/papers/{paper_id}/skip` returns 204, or 404.
- DTOs (camelCase):
  - `ClassSetSummaryDTO{id, label, status, paperCount, markedCount, namesNeedYou, createdAt, error}`
  - `NameFixItemDTO{paperId, coverPage, pageStart, pageEnd, readName, reason, matchPct, pageCount, candidates: RosterStudentDTO[]}`
  - `MatchedPaperDTO{paperId, coverPage, studentId, studentName}`
  - `RosterStudentDTO{studentId, name, className, best}`
  - `ClassSetNamesDTO{setId, label, status, paperCount, matchedCount, items, matched, roster: RosterStudentDTO[]}`
- `reason` comes from `name_status` plus `pages_differ`. The values are `ambiguous`, `no_name`, `spelling`, `not_found`, `unreadable`, `pages_differ`. A paper is in `items` when its status is in {ambiguous, no_name, spelling, not_found, unreadable}, or when `pages_differ` is true and its status is not confirmed or skipped. Single-paper sets (`paperCount == 1`) always return `items: []` and `namesNeedYou: 0`.
- `label` = `"{className} class set · {code}"`, where `code` = `"{subject_code}/{paper_number}{paper_variant}"` from the first child that has metadata. When there is no class: `"{original_filename}"`. When there is no code yet: the label without ` · code`. A single-paper set shows `"{studentName} · {code}"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_class_set_routes.py
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lemely.core.roster_match import Candidate, NameMatch, RosterStudent
from lemely.db.class_set_repo import ClassSetRepository
from lemely.db.models.enums import Role
from lemely.io.class_set.covers import PaperSplit
from lemely.web.app import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_class_service,
    get_class_set_repo,
    get_gemini_client,
    get_settings,
    get_storage_backend,
    get_teacher_paper_repo,
)
from tests.test_web_teacher import _seed_user

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def world(pg_sessionmaker: sessionmaker[Session], settings, storage_backend, paper_repo, class_service):  # type: ignore[no-untyped-def]
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    other = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, Role.teacher, name="10A", subject_code="0625")
    student = _seed_user(pg_sessionmaker, Role.student, "Omar Saleh")
    stranger = _seed_user(pg_sessionmaker, Role.student, "Not Mine")
    # Enrol through the class repo's own seat or code path; mirror tests/test_class_repo.py.
    class_service.join_by_code(student, cls.join_code)
    sets = ClassSetRepository(pg_sessionmaker)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_storage_backend] = lambda: storage_backend
    app.dependency_overrides[get_teacher_paper_repo] = lambda: paper_repo
    app.dependency_overrides[get_class_service] = lambda: class_service
    app.dependency_overrides[get_class_set_repo] = lambda: sets
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock()
    client = TestClient(app)

    def as_(uid: uuid.UUID, role: Role = Role.teacher) -> TestClient:
        app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id=str(uid), role=role.value)
        return client

    return dict(teacher=teacher, other=other, cls=cls, student=student, stranger=stranger,
                sets=sets, papers=paper_repo, as_=as_)


def _seed_set(world: dict) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:  # type: ignore[type-arg]
    sets, papers = world["sets"], world["papers"]
    set_id = sets.create(uploaded_by=world["teacher"], class_id=world["cls"].class_id,
                         storage_path="k", scheme_storage_path=None, original_filename="10A.pdf",
                         byte_size=1)
    ids = []
    for _ in range(2):
        pid = uuid.uuid4()
        papers.create(paper_id=pid, uploaded_by=world["teacher"], storage_path=f"k/{pid}",
                      scheme_storage_path=None, original_filename="p", content_type="application/pdf",
                      byte_size=1)
        ids.append(pid)
    rs = RosterStudent(world["student"], "Omar Saleh", world["cls"].class_id, "10A")
    sets.attach_paper(paper_id=ids[0], set_id=set_id, split=PaperSplit(0, 3),
                      match=NameMatch("matched", rs, (Candidate(rs, 1.0),), 100),
                      cover_name="Omar Saleh", cover_number=None, pages_differ=False, cover_cost_usd=None)
    sets.attach_paper(paper_id=ids[1], set_id=set_id, split=PaperSplit(4, 7),
                      match=NameMatch("spelling", rs, (Candidate(rs, 0.9),), 90),
                      cover_name="Omr Saleh", cover_number=None, pages_differ=False, cover_cost_usd=None)
    sets.mark_ready(set_id, page_count=8, paper_count=2, class_id=None)
    return set_id, ids[0], ids[1]


def test_upload_creates_set_and_submits_job(world: dict) -> None:  # type: ignore[type-arg]
    client = world["as_"](world["teacher"])
    with patch("lemely.web.routers.class_sets._class_set_pool") as pool:
        res = client.post("/api/class-sets", files={"scan": ("10A.pdf", b"%PDF-1.7 x", "application/pdf")},
                          data={"class_id": str(world["cls"].class_id)})
    assert res.status_code == 200, res.text
    set_id = uuid.UUID(res.json()["setId"])
    assert world["sets"].get(set_id).status == "reading"
    pool.submit.assert_called_once()


def test_upload_refuses_someone_elses_class(world: dict) -> None:  # type: ignore[type-arg]
    client = world["as_"](world["other"])
    with patch("lemely.web.routers.class_sets._class_set_pool"):
        res = client.post("/api/class-sets", files={"scan": ("a.pdf", b"%PDF-1.7 x", "application/pdf")},
                          data={"class_id": str(world["cls"].class_id)})
    assert res.status_code == 404


def test_upload_refuses_oversize(world: dict) -> None:  # type: ignore[type-arg]
    client = world["as_"](world["teacher"])
    big = b"%PDF" + b"0" * (25 * 1024 * 1024 + 1)
    with patch("lemely.web.routers.class_sets._class_set_pool"):
        res = client.post("/api/class-sets", files={"scan": ("a.pdf", big, "application/pdf")})
    assert res.status_code == 413


def test_names_lists_only_the_misses_and_the_roster(world: dict) -> None:  # type: ignore[type-arg]
    set_id, matched_id, miss_id = _seed_set(world)
    res = world["as_"](world["teacher"]).get(f"/api/class-sets/{set_id}/names")
    assert res.status_code == 200
    body = res.json()
    assert [i["paperId"] for i in body["items"]] == [str(miss_id)]
    assert body["items"][0]["reason"] == "spelling"
    assert body["items"][0]["coverPage"] == 5
    assert body["matchedCount"] == 1
    assert [m["paperId"] for m in body["matched"]] == [str(matched_id)]
    assert {r["name"] for r in body["roster"]} == {"Omar Saleh"}


def test_names_is_404_for_another_teacher(world: dict) -> None:  # type: ignore[type-arg]
    set_id, _, _ = _seed_set(world)
    assert world["as_"](world["other"]).get(f"/api/class-sets/{set_id}/names").status_code == 404


def test_resolve_and_skip(world: dict) -> None:  # type: ignore[type-arg]
    set_id, _, miss_id = _seed_set(world)
    client = world["as_"](world["teacher"])
    res = client.post(f"/api/class-sets/{set_id}/papers/{miss_id}/name",
                      json={"studentId": str(world["student"])})
    assert res.status_code == 204
    assert world["papers"].get(miss_id).student_id == world["student"]
    body = client.get(f"/api/class-sets/{set_id}/names").json()
    assert body["items"] == [] and body["matchedCount"] == 2
    assert client.post(f"/api/class-sets/{set_id}/papers/{miss_id}/skip").status_code == 204


def test_resolve_refuses_a_student_not_on_the_callers_rosters(world: dict) -> None:  # type: ignore[type-arg]
    set_id, _, miss_id = _seed_set(world)
    res = world["as_"](world["teacher"]).post(f"/api/class-sets/{set_id}/papers/{miss_id}/name",
                                               json={"studentId": str(world["stranger"])})
    assert res.status_code == 422
    assert world["papers"].get(miss_id).student_id is None


def test_list_counts(world: dict) -> None:  # type: ignore[type-arg]
    set_id, _, _ = _seed_set(world)
    body = world["as_"](world["teacher"]).get("/api/class-sets").json()
    row = next(s for s in body["sets"] if s["id"] == str(set_id))
    assert (row["paperCount"], row["markedCount"], row["namesNeedYou"]) == (2, 0, 1)
    assert row["label"].startswith("10A class set")
```

Reuse the `settings`, `storage_backend`, `paper_repo` and `class_service` fixtures from `tests/test_web_teacher.py`. Import them by name into this file (`from tests.test_web_teacher import settings, storage_backend, paper_repo, class_service, history_store  # noqa: F401`). Check `ClassService.create_class`'s and `join_by_code`'s exact signatures at `lemely/db/class_repo.py:473` and `:603`, and the `AuthContext` constructor fields in `deps.py`, then adapt the calls.

- [ ] **Step 2: Run it to make sure it fails**

Run: `PY -m pytest tests/test_class_set_routes.py -q`
Expected: FAIL with `ImportError: cannot import name 'get_class_set_repo'`.

- [ ] **Step 3: Implement**

`lemely/web/deps.py`:

```python
@lru_cache(maxsize=1)
def get_class_set_repo() -> ClassSetRepository:
    """Return the process-wide :class:`ClassSetRepository` singleton (L12)."""
    return ClassSetRepository(get_sessionmaker(get_settings()))
```

(import `ClassSetRepository` from `lemely.db.class_set_repo`).

`lemely/web/schemas_class_sets.py`:

```python
"""DTOs for class sets and the name fix-it list (L12). camelCase, extra forbidden."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


FixReason = Literal["ambiguous", "no_name", "spelling", "not_found", "unreadable", "pages_differ"]


class ClassSetCreatedDTO(ApiModel):
    setId: str


class ClassSetSummaryDTO(ApiModel):
    id: str
    label: str
    status: Literal["reading", "ready", "failed"]
    paperCount: int
    markedCount: int
    namesNeedYou: int
    createdAt: str
    error: str | None = None


class ClassSetListDTO(ApiModel):
    sets: list[ClassSetSummaryDTO]


class RosterStudentDTO(ApiModel):
    studentId: str
    name: str
    className: str
    best: bool = False


class NameFixItemDTO(ApiModel):
    paperId: str
    coverPage: int
    pageStart: int
    pageEnd: int
    pageCount: int
    readName: str | None
    reason: FixReason
    matchPct: int
    candidates: list[RosterStudentDTO]


class MatchedPaperDTO(ApiModel):
    paperId: str
    coverPage: int
    studentId: str | None
    studentName: str | None


class ClassSetNamesDTO(ApiModel):
    setId: str
    label: str
    status: Literal["reading", "ready", "failed"]
    paperCount: int
    matchedCount: int
    items: list[NameFixItemDTO]
    matched: list[MatchedPaperDTO]
    roster: list[RosterStudentDTO]


class ResolveNameDTO(ApiModel):
    studentId: str
```

`lemely/web/routers/class_sets.py`:

```python
"""Class sets: upload a whole class in one PDF, then fix the names Lemely could not match (L12)."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from lemely.db.class_repo import ClassService
from lemely.db.class_set_repo import ClassSetRepository, ClassSetRow, SetPaperRow
from lemely.db.history_repo import parse_user_id
from lemely.db.models.enums import Role, UploadStatus
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.io.gemini import GeminiClient
from lemely.io.storage import StorageBackend
from lemely.runtime.config import Settings
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_class_service,
    get_class_set_repo,
    get_gemini_client,
    get_history_store,
    get_scheme_corpus_repo,
    get_settings,
    get_storage_backend,
    get_teacher_paper_repo,
    require_role,
)
from lemely.web.schemas_class_sets import (
    ClassSetCreatedDTO,
    ClassSetListDTO,
    ClassSetNamesDTO,
    ClassSetSummaryDTO,
    MatchedPaperDTO,
    NameFixItemDTO,
    ResolveNameDTO,
    RosterStudentDTO,
)
from lemely.web.services.class_set_job import roster_for, run_class_set_job
from lemely.web.upload_utils import check_upload_cap, safe_upload_name

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_role(Role.teacher, Role.school_admin, Role.platform_admin))],
)

#: One split at a time per instance; each child's marking goes to the grading pool.
_class_set_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="class-set")
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_FIX_STATUSES = frozenset({"ambiguous", "no_name", "spelling", "not_found", "unreadable"})
_SETTLED = frozenset({"confirmed", "skipped"})


def _viewer(auth: AuthContext) -> tuple[uuid.UUID, Role]:
    return parse_user_id(auth.user_id), Role(auth.role)


def _needs_you(p: SetPaperRow) -> bool:
    return p.name_status in _FIX_STATUSES or (p.pages_differ and p.name_status not in _SETTLED)


def _reason(p: SetPaperRow) -> str:
    return p.name_status if p.name_status in _FIX_STATUSES else "pages_differ"


def _code(papers: list[SetPaperRow]) -> str | None:
    for p in papers:
        if p.metadata is not None:
            m = p.metadata
            return f"{m.subject_code}/{m.paper_number}{m.paper_variant}"
    return None


def _label(row: ClassSetRow, papers: list[SetPaperRow], class_names: dict[uuid.UUID, str]) -> str:
    code = _code(papers)
    if len(papers) == 1 and papers[0].student_name:
        head = papers[0].student_name
    elif row.class_id is not None and row.class_id in class_names:
        head = f"{class_names[row.class_id]} class set"
    else:
        head = row.original_filename or "Class set"
    return f"{head} · {code}" if code else head


def _class_names(cs: ClassService, viewer_id: uuid.UUID, role: Role) -> dict[uuid.UUID, str]:
    return {c.class_id: c.name for c in cs.list_classes(viewer_id, role)}


def _summary(row: ClassSetRow, papers: list[SetPaperRow], names: dict[uuid.UUID, str]) -> ClassSetSummaryDTO:
    single = len(papers) <= 1
    return ClassSetSummaryDTO(
        id=str(row.id), label=_label(row, papers, names), status=row.status,  # type: ignore[arg-type]
        paperCount=row.paper_count or len(papers),
        markedCount=sum(1 for p in papers if p.has_report and p.paper_status is UploadStatus.complete),
        namesNeedYou=0 if single else sum(1 for p in papers if _needs_you(p)),
        createdAt=row.created_at.isoformat(), error=row.error,
    )


@router.post("/class-sets", response_model=ClassSetCreatedDTO)
async def upload_class_set(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    sets: Annotated[ClassSetRepository, Depends(get_class_set_repo)],
    papers: Annotated[TeacherPaperRepository, Depends(get_teacher_paper_repo)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
    history_store: Annotated[object, Depends(get_history_store)],
    corpus: Annotated[object, Depends(get_scheme_corpus_repo)],
    scan: Annotated[UploadFile, File()],
    mark_scheme: Annotated[UploadFile | None, File()] = None,
    class_id: Annotated[str | None, Form()] = None,
) -> ClassSetCreatedDTO:
    """Store the set and start the split job. No model work and no PDF parsing on the request."""
    viewer_id, role = _viewer(auth)
    chosen: uuid.UUID | None = None
    if class_id:
        try:
            chosen = uuid.UUID(class_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Class not found") from exc
        if chosen not in _class_names(class_service, viewer_id, role):
            raise HTTPException(status_code=404, detail="Class not found")
    data = await scan.read()
    check_upload_cap(data, max_bytes=_MAX_UPLOAD_BYTES, content_type=scan.content_type)
    set_id = uuid.uuid4()
    prefix = f"teacher/{viewer_id}/sets/{set_id.hex}"
    key = f"{prefix}/{safe_upload_name(scan.filename, 'set.pdf')}"
    await anyio.to_thread.run_sync(storage.upload, settings.storage.bucket, key, data, scan.content_type)
    scheme_key = None
    if mark_scheme is not None:
        scheme = await mark_scheme.read()
        check_upload_cap(scheme, max_bytes=_MAX_UPLOAD_BYTES, content_type=mark_scheme.content_type)
        scheme_key = f"{prefix}/mark_scheme.pdf"
        await anyio.to_thread.run_sync(storage.upload, settings.storage.bucket, scheme_key, scheme,
                                       mark_scheme.content_type)
    sets.create(set_id=set_id, uploaded_by=viewer_id, class_id=chosen, storage_path=key,
                scheme_storage_path=scheme_key, original_filename=safe_upload_name(scan.filename, "set.pdf"),
                byte_size=len(data))

    from lemely.web.routers.teacher import _start_run_if_claimed  # the one place a run is claimed

    def start(paper_id: uuid.UUID) -> object:
        return _start_run_if_claimed(paper_id, settings, papers, storage, history_store,  # type: ignore[arg-type]
                                     gemini_client, corpus)  # type: ignore[arg-type]

    _class_set_pool.submit(run_class_set_job, set_id, settings=settings, sets=sets, papers=papers,
                           storage=storage, gemini_client=gemini_client, class_service=class_service,
                           start_paper_run=start, uploader_role=role)
    return ClassSetCreatedDTO(setId=str(set_id))


@router.get("/class-sets", response_model=ClassSetListDTO)
def list_class_sets(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    sets: Annotated[ClassSetRepository, Depends(get_class_set_repo)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
) -> ClassSetListDTO:
    viewer_id, role = _viewer(auth)
    names = _class_names(class_service, viewer_id, role)
    rows = sets.list_visible(viewer_id=viewer_id, viewer_role=role)
    return ClassSetListDTO(sets=[_summary(r, sets.papers(r.id), names) for r in rows])


def _require_set(sets: ClassSetRepository, auth: AuthContext, set_id: str) -> ClassSetRow:
    viewer_id, role = _viewer(auth)
    try:
        sid = uuid.UUID(set_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    row = sets.get_visible(sid, viewer_id=viewer_id, viewer_role=role)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return row


@router.get("/class-sets/{set_id}/names", response_model=ClassSetNamesDTO)
def class_set_names(
    set_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    sets: Annotated[ClassSetRepository, Depends(get_class_set_repo)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
) -> ClassSetNamesDTO:
    row = _require_set(sets, auth, set_id)
    viewer_id, role = _viewer(auth)
    papers = sets.papers(row.id)
    names = _class_names(class_service, viewer_id, role)
    single = len(papers) <= 1
    items = [] if single else [
        NameFixItemDTO(
            paperId=str(p.paper_id), coverPage=p.page_start + 1, pageStart=p.page_start + 1,
            pageEnd=p.page_end + 1, pageCount=p.page_end - p.page_start + 1, readName=p.cover_name,
            reason=_reason(p), matchPct=p.match_pct,  # type: ignore[arg-type]
            candidates=[RosterStudentDTO(studentId=str(c["studentId"]), name=str(c["name"]),
                                         className=str(c["className"]), best=i == 0)
                        for i, c in enumerate(p.candidates)],
        )
        for p in papers if _needs_you(p)
    ]
    matched = [MatchedPaperDTO(paperId=str(p.paper_id), coverPage=p.page_start + 1,
                               studentId=str(p.student_id) if p.student_id else None,
                               studentName=p.student_name)
               for p in papers if p.name_status in {"matched", "confirmed"} and not _needs_you(p)]
    roster = [RosterStudentDTO(studentId=str(s.student_id), name=s.name, className=s.class_name)
              for s in roster_for(class_service, viewer_id, role, None)]
    return ClassSetNamesDTO(setId=str(row.id), label=_label(row, papers, names),
                            status=row.status, paperCount=len(papers),  # type: ignore[arg-type]
                            matchedCount=len(matched), items=items, matched=matched, roster=roster)


@router.post("/class-sets/{set_id}/papers/{paper_id}/name", status_code=204)
def resolve_name(
    set_id: str, paper_id: str, body: ResolveNameDTO,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    sets: Annotated[ClassSetRepository, Depends(get_class_set_repo)],
    class_service: Annotated[ClassService, Depends(get_class_service)],
) -> Response:
    row = _require_set(sets, auth, set_id)
    viewer_id, role = _viewer(auth)
    try:
        pid, sid = uuid.UUID(paper_id), uuid.UUID(body.studentId)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    roster = {s.student_id: s for s in roster_for(class_service, viewer_id, role, None)}
    if sid not in roster:
        raise HTTPException(status_code=422, detail="That student is not in your classes.")
    if not sets.resolve(row.id, pid, student_id=sid, student_name=roster[sid].name):
        raise HTTPException(status_code=404, detail="Not found")
    return Response(status_code=204)


@router.post("/class-sets/{set_id}/papers/{paper_id}/skip", status_code=204)
def skip_name(
    set_id: str, paper_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    sets: Annotated[ClassSetRepository, Depends(get_class_set_repo)],
) -> Response:
    row = _require_set(sets, auth, set_id)
    try:
        pid = uuid.UUID(paper_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    if not sets.skip(row.id, pid):
        raise HTTPException(status_code=404, detail="Not found")
    return Response(status_code=204)
```

Check `check_upload_cap` and `safe_upload_name`'s exact homes and signatures in `lemely/web/upload_utils.py`. `teacher.py` imports `check_upload_cap` from there and wraps `safe_upload_name`. Check too that `routers/teacher.py`'s `_start_run_if_claimed` signature is unchanged when L12 starts. Then add `uploader_role: Role` to `run_class_set_job` (Task 9 note) and pass it through to `roster_for`.

`lemely/web/app.py`: `from lemely.web.routers import class_sets` and `app.include_router(class_sets.router)`, next to the other includes.

`tests/test_authz_matrix_complete.py`, in `EXPECTED`, beside the `/api/papers` rows:

```python
    # L12 class sets: staff only, like the grading console they feed.
    ("POST", "/api/class-sets"): STAFF,
    ("GET", "/api/class-sets"): STAFF,
    ("GET", "/api/class-sets/{set_id}/names"): STAFF,
    ("POST", "/api/class-sets/{set_id}/papers/{paper_id}/name"): STAFF,
    ("POST", "/api/class-sets/{set_id}/papers/{paper_id}/skip"): STAFF,
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `PY -m pytest tests/test_class_set_routes.py tests/test_authz_matrix_complete.py tests/test_class_set_job.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/web/schemas_class_sets.py lemely/web/routers/class_sets.py lemely/web/deps.py lemely/web/app.py tests/test_authz_matrix_complete.py tests/test_class_set_routes.py lemely/web/services/class_set_job.py tests/test_class_set_job.py
git commit -S -m "feat(web): class-set upload, list and name fix-it routes" -- lemely/web/schemas_class_sets.py lemely/web/routers/class_sets.py lemely/web/deps.py lemely/web/app.py tests/test_authz_matrix_complete.py tests/test_class_set_routes.py lemely/web/services/class_set_job.py tests/test_class_set_job.py
```

---

## Part C: Web

### Task 11: Class-set types, API and query hooks

**Files:**
- Create: `web/src/lib/classSetTypes.ts`, `web/src/lib/hooks/useClassSetsApi.ts`
- Test: `web/tests/unit/classSetsApi.test.ts`

**Interfaces:**
- Produces:
  - Types: `ClassSetSummary`, `ClassSetNames`, `NameFixItem`, `MatchedPaper`, `RosterStudent`, `FixReason`
  - Query keys: `classSetsKey = ["teacher","classSets"] as const`, `classSetNamesKey(setId)`
  - Functions: `uploadClassSet(scan: File, opts?: { markScheme?: File; classId?: string }): Promise<{ setId: string }>`
  - Hooks:
    - `useClassSets(opts?: { poll?: boolean })`, which refetches every 4s while any set is `reading`, or any set has `markedCount < paperCount`
    - `useClassSetNames(setId)`, which refetches every 4s while `status === "reading"`
    - `useResolveName(setId)`, a mutation taking `{ paperId, studentId }`
    - `useSkipName(setId)`, a mutation taking `{ paperId }`

  Both mutations invalidate `classSetNamesKey(setId)` and `classSetsKey`.

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/unit/classSetsApi.test.ts
import { afterEach, describe, expect, it, vi } from "vitest"
import { classSetNamesKey, classSetsKey, pollInterval, uploadClassSet } from "@/lib/hooks/useClassSetsApi"
import type { ClassSetSummary } from "@/lib/classSetTypes"

afterEach(() => vi.unstubAllGlobals())

function stubFetch(body: unknown, status = 200) {
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal("fetch", fn)
  return fn
}

const set = (over: Partial<ClassSetSummary>): ClassSetSummary => ({
  id: "s1", label: "10A class set · 0625/22", status: "ready", paperCount: 24, markedCount: 24,
  namesNeedYou: 0, createdAt: "2026-11-15T10:00:00Z", error: null, ...over,
})

describe("uploadClassSet", () => {
  it("posts multipart with the backend's field names", async () => {
    const fetchMock = stubFetch({ setId: "abc" })
    const scan = new File(["%PDF"], "10A.pdf", { type: "application/pdf" })
    await expect(uploadClassSet(scan, { classId: "c1" })).resolves.toEqual({ setId: "abc" })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe("/api/class-sets")
    const form = init.body as FormData
    expect(form.get("scan")).toBeInstanceOf(File)
    expect(form.get("class_id")).toBe("c1")
    expect(form.get("mark_scheme")).toBeNull()
  })
})

describe("keys and polling", () => {
  it("names keys are scoped per set", () => {
    expect(classSetNamesKey("s1")).toEqual([...classSetsKey, "s1", "names"])
  })
  it("polls only while something is still moving", () => {
    expect(pollInterval([set({})])).toBe(false)
    expect(pollInterval([set({ status: "reading" })])).toBe(4000)
    expect(pollInterval([set({ markedCount: 17 })])).toBe(4000)
    expect(pollInterval([set({ status: "failed", markedCount: 0 })])).toBe(false)
    expect(pollInterval(undefined)).toBe(false)
  })
})
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd web && npx vitest run tests/unit/classSetsApi.test.ts`
Expected: FAIL with a failed import.

- [ ] **Step 3: Implement**

```ts
// web/src/lib/classSetTypes.ts
/** Mirrors `lemely/web/schemas_class_sets.py` (L12). */
export type ClassSetStatus = "reading" | "ready" | "failed"
export type FixReason = "ambiguous" | "no_name" | "spelling" | "not_found" | "unreadable" | "pages_differ"

export interface ClassSetSummary {
  id: string
  label: string
  status: ClassSetStatus
  paperCount: number
  markedCount: number
  namesNeedYou: number
  createdAt: string
  error: string | null
}

export interface RosterStudent {
  studentId: string
  name: string
  className: string
  best: boolean
}

export interface NameFixItem {
  paperId: string
  coverPage: number
  pageStart: number
  pageEnd: number
  pageCount: number
  readName: string | null
  reason: FixReason
  matchPct: number
  candidates: RosterStudent[]
}

export interface MatchedPaper {
  paperId: string
  coverPage: number
  studentId: string | null
  studentName: string | null
}

export interface ClassSetNames {
  setId: string
  label: string
  status: ClassSetStatus
  paperCount: number
  matchedCount: number
  items: NameFixItem[]
  matched: MatchedPaper[]
  roster: RosterStudent[]
}
```

```ts
// web/src/lib/hooks/useClassSetsApi.ts
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import type { ClassSetNames, ClassSetSummary } from "@/lib/classSetTypes"

/* L12. One hook per endpoint, no `fallback`, so a failure reaches the screen as an error. */

export const classSetsKey = ["teacher", "classSets"] as const
export const classSetNamesKey = (setId: string) => [...classSetsKey, setId, "names"] as const

const POLL_MS = 4000

/** Poll while a set is still being read or any of its papers is still being marked. */
export function pollInterval(sets: ClassSetSummary[] | undefined): number | false {
  if (!sets) return false
  const moving = sets.some(
    (s) => s.status === "reading" || (s.status === "ready" && s.markedCount < s.paperCount),
  )
  return moving ? POLL_MS : false
}

export async function uploadClassSet(
  scan: File,
  opts: { markScheme?: File; classId?: string } = {},
): Promise<{ setId: string }> {
  const form = new FormData()
  form.append("scan", scan)
  if (opts.markScheme) form.append("mark_scheme", opts.markScheme)
  if (opts.classId) form.append("class_id", opts.classId)
  return request<{ setId: string }>("/class-sets", { method: "POST", body: form })
}

export function useClassSets(): UseQueryResult<ClassSetSummary[], Error> {
  return useQuery({
    queryKey: classSetsKey,
    queryFn: async () => (await request<{ sets: ClassSetSummary[] }>("/class-sets")).sets,
    refetchInterval: (query) => pollInterval(query.state.data),
  })
}

export function useClassSetNames(setId: string): UseQueryResult<ClassSetNames, Error> {
  return useQuery({
    queryKey: classSetNamesKey(setId),
    queryFn: () => request<ClassSetNames>(`/class-sets/${encodeURIComponent(setId)}/names`),
    refetchInterval: (query) => (query.state.data?.status === "reading" ? POLL_MS : false),
  })
}

function useInvalidate(setId: string) {
  const qc = useQueryClient()
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: classSetNamesKey(setId) }),
      qc.invalidateQueries({ queryKey: classSetsKey, exact: true }),
    ])
}

export function useResolveName(
  setId: string,
): UseMutationResult<void, Error, { paperId: string; studentId: string }> {
  const invalidate = useInvalidate(setId)
  return useMutation({
    mutationFn: ({ paperId, studentId }) =>
      request<void>(
        `/class-sets/${encodeURIComponent(setId)}/papers/${encodeURIComponent(paperId)}/name`,
        { method: "POST", body: JSON.stringify({ studentId }), headers: { "Content-Type": "application/json" } },
      ),
    onSuccess: invalidate,
  })
}

export function useSkipName(setId: string): UseMutationResult<void, Error, { paperId: string }> {
  const invalidate = useInvalidate(setId)
  return useMutation({
    mutationFn: ({ paperId }) =>
      request<void>(
        `/class-sets/${encodeURIComponent(setId)}/papers/${encodeURIComponent(paperId)}/skip`,
        { method: "POST" },
      ),
    onSuccess: invalidate,
  })
}
```

Check how `request()` handles a 204 (no body). If it calls `res.json()` unconditionally, see how `usePaperDeletionApi.ts`'s `DELETE` (204) works and mirror that.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd web && npx vitest run tests/unit/classSetsApi.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd web && npx oxlint src/lib/classSetTypes.ts src/lib/hooks/useClassSetsApi.ts tests/unit/classSetsApi.test.ts && cd ..
pre-commit run --files web/src/lib/classSetTypes.ts web/src/lib/hooks/useClassSetsApi.ts web/tests/unit/classSetsApi.test.ts
git commit -S -m "feat(web): class-set API types and query hooks" -- web/src/lib/classSetTypes.ts web/src/lib/hooks/useClassSetsApi.ts web/tests/unit/classSetsApi.test.ts
```

### Task 12: Name check view model (pure)

**Files:**
- Create: `web/src/portals/teacher/screens/names/nameCheckModel.ts`
- Test: `web/tests/unit/nameCheckModel.test.ts`

**Interfaces:**
- Consumes: Task 11 types
- Produces:
  - `REASON_COPY: Record<FixReason, string>`
  - `rowTitle(item): string`
  - `headline(names): { count: number; rest: string }`
  - `subline(names): string`
  - `pickerOptions(item, roster): { inClass: RosterStudent[]; other: RosterStudent[] }`
  - `defaultChoice(item): RosterStudent | null`
  - `confirmLabel(student | null): string`
  - `nextSelection(items, removedId, currentId): string | null`
  - `screenState(q): "loading" | "error" | "reading" | "failed" | "done" | "fix"`
  - `recentRowVariant(s: ClassSetSummary): "needsNames" | "marking" | "marked" | "failed" | "reading"`
  - `recentRowStatus(s): string`

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/unit/nameCheckModel.test.ts
import { describe, expect, it } from "vitest"
import type { ClassSetNames, ClassSetSummary, NameFixItem, RosterStudent } from "@/lib/classSetTypes"
import {
  REASON_COPY,
  confirmLabel,
  defaultChoice,
  headline,
  nextSelection,
  pickerOptions,
  recentRowStatus,
  recentRowVariant,
  rowTitle,
  screenState,
  subline,
} from "@/portals/teacher/screens/names/nameCheckModel"

const r = (name: string, className = "10A", best = false): RosterStudent => ({ studentId: name, name, className, best })
const item = (over: Partial<NameFixItem>): NameFixItem => ({
  paperId: "p1", coverPage: 5, pageStart: 5, pageEnd: 20, pageCount: 16, readName: "Omr S.",
  reason: "ambiguous", matchPct: 43, candidates: [r("Omar Saleh", "10A", true), r("Omar Sherif")], ...over,
})
const names = (over: Partial<ClassSetNames> = {}): ClassSetNames => ({
  setId: "s", label: "10A class set · 0625/22", status: "ready", paperCount: 24, matchedCount: 21,
  items: [item({}), item({ paperId: "p2", readName: null, reason: "no_name", coverPage: 12 }),
          item({ paperId: "p3", readName: "Nour Adl", reason: "spelling", coverPage: 19 })],
  matched: [], roster: [r("Omar Saleh"), r("Omar Sherif"), r("Nour Adel"), r("Ali Mansour", "10B")], ...over,
})

describe("copy", () => {
  it("matches the mock's reasons", () => {
    expect(REASON_COPY.ambiguous).toBe("Two students match")
    expect(REASON_COPY.no_name).toBe("Cover is blank")
    expect(REASON_COPY.spelling).toBe("Spelling differs from roster")
  })
  it("titles quote what was read, or say no name was written", () => {
    expect(rowTitle(item({}))).toBe("“Omr S.”")
    expect(rowTitle(item({ readName: null, reason: "no_name" }))).toBe("No name written")
    expect(rowTitle(item({ readName: null, reason: "unreadable" }))).toBe("Couldn’t read the cover")
  })
  it("headline and subline", () => {
    expect(headline(names())).toEqual({ count: 3, rest: "names need you" })
    expect(headline(names({ items: [item({})] }))).toEqual({ count: 1, rest: "name needs you" })
    expect(subline(names())).toBe("10A class set · 0625/22 · 21 of 24 matched automatically")
  })
})

describe("picker", () => {
  it("puts the set's class first and the rest under 'Not in this class'", () => {
    const opts = pickerOptions(item({}), names().roster)
    expect(opts.inClass.map((s) => s.name)).toEqual(["Omar Saleh", "Omar Sherif", "Nour Adel"])
    expect(opts.other.map((s) => s.name)).toEqual(["Ali Mansour"])
  })
  it("defaults to the best candidate and labels the button with it", () => {
    expect(defaultChoice(item({}))?.name).toBe("Omar Saleh")
    expect(defaultChoice(item({ candidates: [] }))).toBeNull()
    expect(confirmLabel(r("Omar Saleh"))).toBe("Confirm Omar Saleh")
    expect(confirmLabel(null)).toBe("Pick a student")
  })
})

describe("selection", () => {
  it("moves to the next row after a resolve, wrapping to the previous at the end", () => {
    const items = names().items
    expect(nextSelection(items, "p1", "p1")).toBe("p2")
    expect(nextSelection(items, "p3", "p3")).toBe("p2")
    expect(nextSelection([items[0]], "p1", "p1")).toBeNull()
    expect(nextSelection(items, "p2", "p1")).toBe("p1")
  })
})

describe("states", () => {
  it("chooses one state", () => {
    expect(screenState({ isPending: true })).toBe("loading")
    expect(screenState({ isPending: false, error: new Error("x") })).toBe("error")
    expect(screenState({ isPending: false, data: names({ status: "reading" }) })).toBe("reading")
    expect(screenState({ isPending: false, data: names({ status: "failed" }) })).toBe("failed")
    expect(screenState({ isPending: false, data: names({ items: [] }) })).toBe("done")
    expect(screenState({ isPending: false, data: names() })).toBe("fix")
  })
})

describe("recent upload rows", () => {
  const s = (over: Partial<ClassSetSummary>): ClassSetSummary => ({
    id: "s", label: "10A class set · 0625/22", status: "ready", paperCount: 28, markedCount: 28,
    namesNeedYou: 0, createdAt: "2026-11-15T10:00:00Z", error: null, ...over,
  })
  it("names come first, then marking, then done", () => {
    expect(recentRowVariant(s({ namesNeedYou: 3, markedCount: 10 }))).toBe("needsNames")
    expect(recentRowVariant(s({ markedCount: 17 }))).toBe("marking")
    expect(recentRowVariant(s({}))).toBe("marked")
    expect(recentRowVariant(s({ status: "failed" }))).toBe("failed")
    expect(recentRowVariant(s({ status: "reading" }))).toBe("reading")
  })
  it("status copy", () => {
    expect(recentRowStatus(s({ namesNeedYou: 3 }))).toBe("3 names need you")
    expect(recentRowStatus(s({ namesNeedYou: 1 }))).toBe("1 name needs you")
    expect(recentRowStatus(s({ markedCount: 17 }))).toBe("Marking 17 of 28")
    expect(recentRowStatus(s({ status: "reading" }))).toBe("Reading names off the covers")
    expect(recentRowStatus(s({ status: "failed" }))).toBe("Couldn’t split this file")
  })
})
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd web && npx vitest run tests/unit/nameCheckModel.test.ts`
Expected: FAIL with a failed import.

- [ ] **Step 3: Implement**

```ts
// web/src/portals/teacher/screens/names/nameCheckModel.ts
import type {
  ClassSetNames,
  ClassSetSummary,
  FixReason,
  NameFixItem,
  RosterStudent,
} from "@/lib/classSetTypes"

/* L12 Name check: every decision lives here, so the screen stays a render. */

export const REASON_COPY: Record<FixReason, string> = {
  ambiguous: "Two students match",
  no_name: "Cover is blank",
  spelling: "Spelling differs from roster",
  not_found: "Not on your class lists",
  unreadable: "Couldn’t read the cover",
  pages_differ: "Page count differs from the rest",
}

export function rowTitle(item: NameFixItem): string {
  if (item.readName) return `“${item.readName}”`
  return item.reason === "unreadable" ? "Couldn’t read the cover" : "No name written"
}

export function headline(names: ClassSetNames): { count: number; rest: string } {
  const count = names.items.length
  return { count, rest: count === 1 ? "name needs you" : "names need you" }
}

export function subline(names: ClassSetNames): string {
  return `${names.label} · ${names.matchedCount} of ${names.paperCount} matched automatically`
}

function setClassName(item: NameFixItem, roster: RosterStudent[]): string | null {
  return item.candidates[0]?.className ?? roster[0]?.className ?? null
}

export function pickerOptions(
  item: NameFixItem,
  roster: RosterStudent[],
): { inClass: RosterStudent[]; other: RosterStudent[] } {
  const cls = setClassName(item, roster)
  const order = new Map(item.candidates.map((c, i) => [c.studentId, i]))
  const rank = (s: RosterStudent) => order.get(s.studentId) ?? Number.MAX_SAFE_INTEGER
  const byRank = (a: RosterStudent, b: RosterStudent) => rank(a) - rank(b) || a.name.localeCompare(b.name)
  const inClass = roster.filter((s) => s.className === cls).sort(byRank)
  const other = roster.filter((s) => s.className !== cls).sort((a, b) => a.name.localeCompare(b.name))
  return { inClass, other }
}

export function defaultChoice(item: NameFixItem): RosterStudent | null {
  return item.candidates[0] ?? null
}

export function confirmLabel(student: RosterStudent | null): string {
  return student ? `Confirm ${student.name}` : "Pick a student"
}

export function nextSelection(items: NameFixItem[], removedId: string, currentId: string | null): string | null {
  if (currentId !== removedId) return currentId
  const at = items.findIndex((i) => i.paperId === removedId)
  const rest = items.filter((i) => i.paperId !== removedId)
  if (rest.length === 0) return null
  return (rest[at] ?? rest[at - 1] ?? rest[0]).paperId
}

export type NameCheckState = "loading" | "error" | "reading" | "failed" | "done" | "fix"

export function screenState(q: { isPending: boolean; error?: Error | null; data?: ClassSetNames }): NameCheckState {
  if (q.isPending) return "loading"
  if (q.error || !q.data) return "error"
  if (q.data.status === "reading") return "reading"
  if (q.data.status === "failed") return "failed"
  return q.data.items.length === 0 ? "done" : "fix"
}

export type RecentRowVariant = "needsNames" | "marking" | "marked" | "failed" | "reading"

export function recentRowVariant(s: ClassSetSummary): RecentRowVariant {
  if (s.status === "failed") return "failed"
  if (s.status === "reading") return "reading"
  if (s.namesNeedYou > 0 && s.paperCount > 1) return "needsNames"
  return s.markedCount < s.paperCount ? "marking" : "marked"
}

export function recentRowStatus(s: ClassSetSummary): string {
  switch (recentRowVariant(s)) {
    case "failed":
      return "Couldn’t split this file"
    case "reading":
      return "Reading names off the covers"
    case "needsNames":
      return s.namesNeedYou === 1 ? "1 name needs you" : `${s.namesNeedYou} names need you`
    case "marking":
      return `Marking ${s.markedCount} of ${s.paperCount}`
    case "marked":
      return "Marked"
  }
}
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd web && npx vitest run tests/unit/nameCheckModel.test.ts && npm run typecheck && npm run check:copy`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files web/src/portals/teacher/screens/names/nameCheckModel.ts web/tests/unit/nameCheckModel.test.ts
git commit -S -m "feat(web): name check view model" -- web/src/portals/teacher/screens/names/nameCheckModel.ts web/tests/unit/nameCheckModel.test.ts
```

### Task 13: Name check screen (designer)

**Agent:** `designer`. Before editing, invoke the `impeccable` skill and read `.claude/skills/impeccable/reference/craft-floor.md`, plus the three taste memories (`design-taste-first-try.md`, `design-redesign-decisions.md`, `design-empty-sparse-states.md`).

**Files:**
- Create in `web/src/portals/teacher/screens/names/`: `NameCheck.tsx` (route screen), `NameFixList.tsx`, `CoverPanel.tsx`, `StudentPicker.tsx`, `MatchRing.tsx`
- Modify: `web/src/portals/teacher/index.tsx` (one child route after `"grading"`)

**Interfaces:**
- Consumes:
  - Task 11 hooks
  - Task 12 model
  - F1 kit from `@/components/redesign`: `HairRows`, `HairRow`, `GhostRows`, `Binny`
  - `components/ui/state-views.tsx`, `components/ui/bottom-sheet.tsx`
  - `GET /api/papers/{paperId}/preview` (existing, staff-only, page 1 = the cover)
- Route: `{ path: "papers/sets/:setId/names", element: <NameCheck />, handle: { title: "Check names", skeleton: "list" } }`

**Mock to token mapping** (from `up.css`):

| Mock | Tailwind / token |
|---|---|
| `.nq` grid `420px 1fr` (tablet `330px 1fr`) | `lg:grid lg:grid-cols-[420px_1fr] md:grid-cols-[330px_1fr]` |
| `.ql` `padding:24px 18px 24px 24px; border-right:1px solid --ov; background:--sl; gap:12px` | `p-6 pr-[18px] border-r border-outline-variant bg-surface-container-low grid gap-3 content-start` |
| h1 `800 30px/1.1 Schibsted`, count `800 56px Bricolage` in `--p` | `font-sans font-extrabold text-[30px] leading-[1.1] tracking-[-.02em]`; count `font-display font-extrabold text-[56px] text-primary` |
| sub `color:--v` | `text-on-surface-variant` |
| `.nrow` `grid auto 1fr auto; gap:12px; padding:12px; radius:14px` | `grid grid-cols-[auto_1fr_auto] gap-3 items-center p-3 rounded-[14px]` |
| `.nrow.on` | `bg-surface-container-lowest shadow-[inset_0_0_0_2px_var(--color-primary)]` |
| `.ring` 52px conic `--err`, inner inset 5px | `MatchRing` (below): `size-[52px] rounded-full grid place-items-center`, style `background: conic-gradient(var(--color-error) calc(var(--v)*1%), var(--color-surface-container-high) 0)` |
| `.ring .m` `600 14px JetBrains` | `font-mono font-semibold text-sm relative z-[1]` |
| `.nrow b` `700 15px` | `font-bold text-[15px]` |
| `.why` `13.5px`, `.dot` 8px `--err` | `text-[13.5px] flex gap-[7px] items-center`; dot `size-2 rounded-full bg-error` |
| page tag `600 12.5px JetBrains --v` | `font-mono font-semibold text-[12.5px] text-on-surface-variant` |
| `.np` `padding:24px 36px; gap:16px` (tablet `20px 24px`) | `px-9 py-6 md:max-lg:px-6 md:max-lg:py-5 grid gap-4 content-start` |
| h2 `700 21px` | `font-bold text-[21px]` |
| `.coverc` `radius:18px; bg #fbfbf8; inset 0 0 0 1px --o; padding:22px 26px` | the real cover image in `rounded-[18px] shadow-[inset_0_0_0_1px_var(--color-outline)] bg-surface-container-lowest overflow-hidden` (the mock's drawn boxes become the real scan, see Needs user decision 3) |
| `.field label` `600 13px --v` | `font-semibold text-[13px] text-on-surface-variant` |
| `.combo` `h-48 r-12 inset 1.5px --p + 0 0 0 3px --pc; bg --l; 600 15px` | Radix `Select` or `Popover` trigger: `h-12 rounded-xl bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-primary),0_0_0_3px_var(--color-primary-container)] px-3.5 font-semibold text-[15px] flex items-center gap-2.5` |
| `.opts` | `bg-surface-container-lowest rounded-2xl p-1.5 shadow-[0_30px_60px_-40px_oklch(.3_.06_242/.45),0_0_0_1px_var(--color-outline-variant)]`; option `px-3 py-2.5 rounded-[10px] flex justify-between text-[14.5px]`; highlighted `bg-primary-container`; meta `text-on-surface-variant text-[12.5px]` |
| `.btn` primary | `min-h-11 rounded-[14px] bg-primary text-on-primary font-bold text-sm px-[18px] transition-[transform,background] duration-150 ease-out hover:bg-primary-hover active:scale-[.97] motion-reduce:active:scale-100` |
| `.btn.o` | `bg-surface-container-lowest text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline)]` |
| `details summary` `700 14px --p` | `font-bold text-sm text-primary cursor-pointer` |

**Component tree:**

```
NameCheck (route; useParams setId; useClassSetNames; useResolveName; useSkipName)
├─ state "loading"  → two-pane skeleton: GhostRows rows={3} withLeading + panel skeleton
├─ state "error"    → StateView error "Couldn’t load the names" + Try again (refetch)
├─ state "reading"  → header "Still reading covers" + GhostRows rows={3} withLeading
├─ state "failed"   → StateView error "Couldn’t split this file" + data.label
├─ state "done"     → Binny head-crop (mood "happy", size 56, motion "pop") + "All names matched" + "Back to papers" link
└─ state "fix"
   ├─ <section aria-labelledby="names-h"> NameFixList
   │   ├─ h1#names-h: <span count/> {rest}
   │   ├─ p subline
   │   ├─ HairRows aria-label="Names to check" → per item: button row (MatchRing, title, why, page tag), aria-pressed=selected
   │   └─ details "Show the {matchedCount} matched papers" → HairRows of matched (name · p.N)
   └─ CoverPanel (desktop and tablet inline; phone: BottomSheet open when a row is tapped)
       ├─ h2 "Cover page {coverPage}" + mono "Pages {pageStart}–{pageEnd}" + mono "{i} of {n}"
       ├─ cover image (preview route), alt "Cover page {coverPage}"
       ├─ StudentPicker (label "Which student is this?")
       └─ actions: [Confirm X] [Skip paper]
```

- [ ] **Step 1: Write the Playwright happy path first (it fails: no route)**

```ts
// web/e2e/name-check.spec.ts
import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

/*
 * L12 Name check, end to end against the real app with the class-set API stubbed (no
 * model call, no seeded set): a teacher sees the misses, picks a student, confirms, and the
 * row leaves the list; the last confirm shows the all-matched state.
 */

const SET = "11111111-1111-4111-8111-111111111111"
const names = (items: unknown[], matched = 21) => ({
  setId: SET, label: "10A class set · 0625/22", status: "ready", paperCount: 24, matchedCount: matched,
  items, matched: [],
  roster: [
    { studentId: "s-omar-saleh", name: "Omar Saleh", className: "10A", best: false },
    { studentId: "s-omar-sherif", name: "Omar Sherif", className: "10A", best: false },
  ],
})
const omr = {
  paperId: "p-omr", coverPage: 5, pageStart: 5, pageEnd: 20, pageCount: 16, readName: "Omr S.",
  reason: "ambiguous", matchPct: 43,
  candidates: [
    { studentId: "s-omar-saleh", name: "Omar Saleh", className: "10A", best: true },
    { studentId: "s-omar-sherif", name: "Omar Sherif", className: "10A", best: false },
  ],
}

async function login(page: Page) {
  const { teacher } = readSeed()
  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher$/, { timeout: 15_000 })
}

test("a teacher confirms the one name Lemely could not match", async ({ page }) => {
  const errors = watchConsole(page)
  let resolved = false
  await page.route(`**/api/class-sets/${SET}/names`, (route) =>
    route.fulfill({ json: resolved ? names([], 22) : names([omr]) }),
  )
  await page.route(`**/api/class-sets/${SET}/papers/p-omr/name`, async (route) => {
    expect(route.request().postDataJSON()).toEqual({ studentId: "s-omar-saleh" })
    resolved = true
    await route.fulfill({ status: 204 })
  })
  await page.route("**/api/papers/p-omr/preview", (route) =>
    route.fulfill({ path: "e2e/fixtures/cover.png", contentType: "image/png" }),
  )

  await login(page)
  await page.goto(`/teacher/papers/sets/${SET}/names`)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/1\s*name needs you/)
  await expect(page.getByText("10A class set · 0625/22 · 21 of 24 matched automatically")).toBeVisible()
  await expect(page.getByRole("button", { name: /“Omr S\.”.*Two students match/ })).toHaveAttribute("aria-pressed", "true")
  await expect(page.getByRole("heading", { name: "Cover page 5" })).toBeVisible()
  await page.getByRole("button", { name: "Confirm Omar Saleh" }).click()
  await expect(page.getByText("All names matched")).toBeVisible()
  expect(errors()).toEqual([])
})
```

Add `web/e2e/fixtures/cover.png` (any small PNG; generate one with a script, never by hand-editing binary). Before writing, check `watchConsole`'s return shape in `web/e2e/console-errors.ts`, and match how `teacher-review.spec.ts` asserts on it.

Run: `cd web && npx playwright test e2e/name-check.spec.ts`
Expected: FAIL (the route does not exist, so a NotFound heading appears).

- [ ] **Step 2: Build the screen**

`MatchRing.tsx`:

```tsx
import type { CSSProperties } from "react"

/** The fix-it row's ring (up.css `.ring`): a conic fill of `pct`, error tone, the number in Mono. */
export function MatchRing({ pct }: { pct: number }) {
  const v = Math.max(0, Math.min(100, Math.round(pct)))
  return (
    <span
      aria-hidden
      className="relative grid size-[52px] place-items-center rounded-full after:absolute after:inset-[5px] after:rounded-full after:bg-[var(--ring-bg)]"
      style={{
        background: `conic-gradient(var(--color-error) ${v}%, var(--color-surface-container-high) 0)`,
        "--ring-bg": "var(--color-surface-container-low)",
      } as CSSProperties}
    >
      <span className="relative z-[1] font-mono text-sm font-semibold">{v}</span>
    </span>
  )
}
```

`NameFixList.tsx`:

```tsx
import { HairRow, HairRows } from "@/components/redesign"
import type { ClassSetNames } from "@/lib/classSetTypes"
import { cn } from "@/lib/utils"
import { MatchRing } from "./MatchRing"
import { REASON_COPY, headline, rowTitle, subline } from "./nameCheckModel"

export function NameFixList({
  names,
  selectedId,
  onSelect,
}: {
  names: ClassSetNames
  selectedId: string | null
  onSelect: (paperId: string) => void
}) {
  const { count, rest } = headline(names)
  return (
    <section
      aria-labelledby="names-h"
      className="grid content-start gap-3 bg-surface-container-low p-6 pr-[18px] md:border-r md:border-outline-variant"
    >
      <h1 id="names-h" className="font-sans text-[30px] font-extrabold leading-[1.1] tracking-[-.02em]">
        <span className="font-display text-[56px] font-extrabold text-primary">{count}</span> {rest}
      </h1>
      <p className="text-on-surface-variant">{subline(names)}</p>
      <ul aria-label="Names to check" className="grid gap-1">
        {names.items.map((item) => {
          const on = item.paperId === selectedId
          return (
            <li key={item.paperId}>
              <button
                type="button"
                aria-pressed={on}
                onClick={() => onSelect(item.paperId)}
                className={cn(
                  "grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 rounded-[14px] p-3 text-left",
                  on && "bg-surface-container-lowest shadow-[inset_0_0_0_2px_var(--color-primary)] [--ring-bg:var(--color-surface-container-lowest)]",
                )}
              >
                <MatchRing pct={item.matchPct} />
                <span className="min-w-0">
                  <b className="block truncate text-[15px] font-bold">{rowTitle(item)}</b>
                  <span className="flex items-center gap-[7px] text-[13.5px]">
                    <i aria-hidden className="size-2 rounded-full bg-error" />
                    {REASON_COPY[item.reason]}
                  </span>
                </span>
                <span className="font-mono text-[12.5px] font-semibold text-on-surface-variant">p.{item.coverPage}</span>
              </button>
            </li>
          )
        })}
      </ul>
      {names.matched.length > 0 && (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-sm font-bold text-primary">
            Show the {names.matchedCount} matched papers
          </summary>
          <HairRows aria-label="Matched papers">
            {names.matched.map((m) => (
              <HairRow
                key={m.paperId}
                title={m.studentName ?? "Unnamed"}
                trailing={<span className="font-mono text-[12.5px] text-on-surface-variant">p.{m.coverPage}</span>}
              />
            ))}
          </HairRows>
        </details>
      )}
    </section>
  )
}
```

The `MatchRing` inner disc reads `--ring-bg`. The selected row sets it to surface-container-lowest, matching `.nrow.on .ring::after`. To do that, have `MatchRing` read the variable from its parent: drop its inline `--ring-bg` default and set the default on the list instead (`[--ring-bg:var(--color-surface-container-low)]` on the `ul`).

`StudentPicker.tsx`, built on Radix `Popover` (already a dependency; check with `grep -n "@radix-ui/react-popover" web/package.json`, and if it is absent use `@radix-ui/react-select`):

```tsx
import * as Popover from "@radix-ui/react-popover"
import { useId, useState } from "react"
import type { NameFixItem, RosterStudent } from "@/lib/classSetTypes"
import { cn } from "@/lib/utils"
import { pickerOptions } from "./nameCheckModel"

export function StudentPicker({
  item,
  roster,
  value,
  onChange,
}: {
  item: NameFixItem
  roster: RosterStudent[]
  value: RosterStudent | null
  onChange: (s: RosterStudent) => void
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [showOther, setShowOther] = useState(false)
  const { inClass, other } = pickerOptions(item, roster)
  const best = item.candidates[0]?.studentId
  const option = (s: RosterStudent) => (
    <button
      key={s.studentId}
      type="button"
      role="option"
      aria-selected={value?.studentId === s.studentId}
      onClick={() => {
        onChange(s)
        setOpen(false)
      }}
      className={cn(
        "flex w-full justify-between rounded-[10px] px-3 py-2.5 text-left text-[14.5px]",
        value?.studentId === s.studentId && "bg-primary-container",
      )}
    >
      <span>{s.name}</span>
      <span className="text-[12.5px] text-on-surface-variant">
        {s.className}
        {s.studentId === best ? " · best match" : ""}
      </span>
    </button>
  )
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-[13px] font-semibold text-on-surface-variant">
        Which student is this?
      </label>
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger
          id={id}
          className="flex h-12 items-center gap-2.5 rounded-xl bg-surface-container-lowest px-3.5 text-[15px] font-semibold shadow-[inset_0_0_0_1.5px_var(--color-primary),0_0_0_3px_var(--color-primary-container)]"
        >
          {value?.name ?? "Pick a student"}
          <span className="ms-auto font-mono text-[12.5px] font-semibold text-on-surface-variant">{value?.className}</span>
        </Popover.Trigger>
        <Popover.Content
          align="start"
          sideOffset={6}
          role="listbox"
          aria-label="Students"
          className="z-50 w-[var(--radix-popover-trigger-width)] max-h-80 overflow-auto rounded-2xl bg-surface-container-lowest p-1.5 shadow-[0_30px_60px_-40px_oklch(.3_.06_242/.45),0_0_0_1px_var(--color-outline-variant)]"
        >
          {inClass.map(option)}
          {other.length > 0 && !showOther && (
            <button type="button" onClick={() => setShowOther(true)} className="flex w-full rounded-[10px] px-3 py-2.5 text-left text-[14.5px]">
              Not in this class…
            </button>
          )}
          {showOther && other.map(option)}
        </Popover.Content>
      </Popover.Root>
    </div>
  )
}
```

`CoverPanel.tsx`:

```tsx
import { useEffect, useState } from "react"
import type { NameFixItem, RosterStudent } from "@/lib/classSetTypes"
import { useAuthedImage } from "@/lib/hooks/useTeacherApi"
import { StudentPicker } from "./StudentPicker"
import { confirmLabel, defaultChoice } from "./nameCheckModel"

export function CoverPanel({
  item,
  index,
  total,
  roster,
  busy,
  onConfirm,
  onSkip,
}: {
  item: NameFixItem
  index: number
  total: number
  roster: RosterStudent[]
  busy: boolean
  onConfirm: (studentId: string) => void
  onSkip: () => void
}) {
  const [choice, setChoice] = useState<RosterStudent | null>(defaultChoice(item))
  useEffect(() => setChoice(defaultChoice(item)), [item])
  const cover = useAuthedImage(`/papers/${encodeURIComponent(item.paperId)}/preview`)
  return (
    <section aria-labelledby="cover-h" className="grid content-start gap-4 px-9 py-6 md:max-lg:px-6 md:max-lg:py-5">
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <h2 id="cover-h" className="text-[21px] font-bold">Cover page {item.coverPage}</h2>
          <div className="font-mono text-[12.5px] font-semibold text-on-surface-variant">
            Pages {item.pageStart}–{item.pageEnd}
          </div>
        </div>
        <span className="font-mono text-[13px] font-semibold text-on-surface-variant">
          {index + 1} of {total}
        </span>
      </div>
      <div className="overflow-hidden rounded-[18px] bg-surface-container-lowest shadow-[inset_0_0_0_1px_var(--color-outline)]">
        {cover.src ? (
          <img src={cover.src} alt={`Cover page ${item.coverPage}`} className="block w-full object-contain object-top max-h-[46vh]" />
        ) : (
          <div className="h-64 animate-pulse bg-surface-container motion-reduce:animate-none" role="status" aria-label="Loading cover" />
        )}
      </div>
      <StudentPicker item={item} roster={roster} value={choice} onChange={setChoice} />
      <div className="flex gap-2">
        <button
          type="button"
          disabled={!choice || busy}
          onClick={() => choice && onConfirm(choice.studentId)}
          className="min-h-11 flex-1 rounded-[14px] bg-primary px-[18px] text-sm font-bold text-on-primary transition-[transform,background] duration-150 ease-out hover:bg-primary-hover active:scale-[.97] disabled:opacity-60 motion-reduce:active:scale-100"
        >
          {confirmLabel(choice)}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onSkip}
          className="min-h-11 rounded-[14px] bg-surface-container-lowest px-[18px] text-sm font-bold text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline)] transition-transform duration-150 ease-out active:scale-[.97] motion-reduce:active:scale-100"
        >
          Skip paper
        </button>
      </div>
    </section>
  )
}
```

`useAuthedImage` stands for whatever hook the existing staff preview uses to fetch `/papers/{id}/preview` with the bearer token into an object URL. Find it by searching `web/src` for `"/preview"` (the Grading console renders that preview). Import it under its real name. If it is a local function inside `Grading.tsx`, move it to `web/src/lib/hooks/useTeacherApi.ts` as an exported hook in this task, and update `Grading.tsx`'s import (one-line edit).

`NameCheck.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { Binny, GhostRows } from "@/components/redesign"
import { BottomSheet } from "@/components/ui/bottom-sheet"
import { StateView } from "@/components/ui/state-views"
import { useClassSetNames, useResolveName, useSkipName } from "@/lib/hooks/useClassSetsApi"
import { useMediaQuery } from "@/lib/hooks/useMediaQuery"
import { CoverPanel } from "./CoverPanel"
import { NameFixList } from "./NameFixList"
import { nextSelection, screenState } from "./nameCheckModel"

export default function NameCheck() {
  const { setId = "" } = useParams()
  const q = useClassSetNames(setId)
  const resolve = useResolveName(setId)
  const skip = useSkipName(setId)
  const wide = useMediaQuery("(min-width: 640px)")
  const [selected, setSelected] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const items = q.data?.items ?? []
  useEffect(() => {
    if (selected === null || !items.some((i) => i.paperId === selected)) setSelected(items[0]?.paperId ?? null)
  }, [items, selected])
  const index = useMemo(() => items.findIndex((i) => i.paperId === selected), [items, selected])
  const state = screenState({ isPending: q.isPending, error: q.error, data: q.data })

  if (state === "loading")
    return (
      <div className="md:grid md:grid-cols-[330px_1fr] lg:grid-cols-[420px_1fr]">
        <div className="p-6"><GhostRows rows={3} withLeading /></div>
        <div className="hidden p-9 md:block"><div className="h-80 rounded-[18px] bg-surface-container motion-safe:animate-pulse" /></div>
      </div>
    )
  if (state === "error")
    return <StateView kind="error" title="Couldn’t load the names" action={{ label: "Try again", onClick: () => q.refetch() }} />
  if (state === "failed")
    return <StateView kind="error" title="Couldn’t split this file" body={q.data?.label} />
  if (state === "reading")
    return (
      <div className="grid gap-3 p-6">
        <h1 className="font-sans text-[30px] font-extrabold leading-[1.1]">Still reading covers</h1>
        <GhostRows rows={3} withLeading />
      </div>
    )
  if (state === "done")
    return (
      <div className="grid justify-items-center gap-3 p-10 text-center">
        <Binny mood="happy" size={56} motion="pop" aria-hidden />
        <h1 className="font-sans text-[30px] font-extrabold">All names matched</h1>
        <Link to="/teacher/grading" className="font-bold text-primary">Back to papers</Link>
      </div>
    )

  const data = q.data!
  const current = index >= 0 ? items[index] : null
  const act = async (fn: () => Promise<unknown>, paperId: string) => {
    await fn()
    setSelected(nextSelection(items, paperId, selected))
    setSheetOpen(false)
  }
  const panel = current && (
    <CoverPanel
      item={current}
      index={index}
      total={items.length}
      roster={data.roster}
      busy={resolve.isPending || skip.isPending}
      onConfirm={(studentId) => act(() => resolve.mutateAsync({ paperId: current.paperId, studentId }), current.paperId)}
      onSkip={() => act(() => skip.mutateAsync({ paperId: current.paperId }), current.paperId)}
    />
  )
  return (
    <div className="min-w-0 md:grid md:grid-cols-[330px_1fr] lg:grid-cols-[420px_1fr]">
      <NameFixList
        names={data}
        selectedId={selected}
        onSelect={(id) => {
          setSelected(id)
          if (!wide) setSheetOpen(true)
        }}
      />
      {wide ? panel : (
        <BottomSheet open={sheetOpen} onOpenChange={setSheetOpen} title={current ? `Cover page ${current.coverPage}` : ""}>
          {panel}
        </BottomSheet>
      )}
    </div>
  )
}
```

Match the real prop names of `StateView`, `BottomSheet` and `useMediaQuery`: read `components/ui/state-views.tsx` and `bottom-sheet.tsx`, and search for a media-query hook. If none exists, use the shell's existing breakpoint hook, or Tailwind-only layout plus `matchMedia` in a small effect inside this file. A mutation error shows the existing `toast` ("Couldn’t save that name. Try again.") and keeps the row selected.

Register the route in `web/src/portals/teacher/index.tsx`, after `grading`:

```tsx
    {
      path: "papers/sets/:setId/names",
      element: <NameCheck />,
      handle: { title: "Check names", skeleton: "list" },
    },
```

with `const NameCheck = lazy(() => import("./screens/names/NameCheck"))`, following the lazy pattern the file already uses.

- [ ] **Step 3: Run the e2e test and the unit gates**

Run: `cd web && npx playwright test e2e/name-check.spec.ts && npx vitest run tests/unit/nameCheckModel.test.ts tests/unit/a11yRules.test.ts && npm run typecheck && npm run lint && npm run check:copy`
Expected: PASS. `a11yRules` and `check:copy`/`check:native` count as touched because they scan `src/`.

- [ ] **Step 4: Commit**

```bash
pre-commit run --files web/src/portals/teacher/screens/names/*.tsx web/src/portals/teacher/index.tsx web/e2e/name-check.spec.ts web/e2e/fixtures/cover.png
git commit -S -m "feat(web): teacher name check screen for class-set covers" -- web/src/portals/teacher/screens/names web/src/portals/teacher/index.tsx web/e2e/name-check.spec.ts web/e2e/fixtures/cover.png
```

### Task 14: Cost and accuracy evidence (no live calls)

**Files:**
- Create: `tests/test_l12_cost.py`

**Interfaces:**
- Consumes: Tasks 1, 5 and 9

This task pins the cost maths as executable checks, so a later change that inflates the cover call (higher DPI, a second image) fails CI.

- [ ] **Step 1: Write the test**

```python
# tests/test_l12_cost.py
"""L12 cost maths, executable: cover read + no_attempt stay far under $0.10 per paper."""

from __future__ import annotations

import json

from lemely.core.schemas import AIMarkResponse, marker_response_schema
from lemely.io.class_set.cover_reader import MAX_COVER_IMAGE_TOKENS
from lemely.io.llm.image_fit import estimate_tokens
from lemely.io.llm.pricing import CLAUDE_PRICING, row_cost
from lemely.io.prompts.cover_names import COVER_SYSTEM_PROMPT, build_cover_user_prompt

_HAIKU = CLAUDE_PRICING["claude-haiku-5-5"]
_BASELINE_WORST = 0.066  # FLIP.md worst real script on Haiku
_CAP = 0.10


def _approx_tokens(text: str) -> int:
    return len(text) // 4 + 1


def test_cover_read_costs_under_half_a_tenth_of_a_cent() -> None:
    prompt = _approx_tokens(COVER_SYSTEM_PROMPT + build_cover_user_prompt())
    usd = row_cost(_HAIKU, input_tokens=MAX_COVER_IMAGE_TOKENS + prompt, cached_tokens=0, output_tokens=60)
    assert usd < 0.0005, usd
    assert estimate_tokens(992, 1403) == 1856


def test_no_attempt_adds_under_a_tenth_of_a_cent_per_script_worst_case() -> None:
    off = json.dumps(AIMarkResponse.model_json_schema())
    on = json.dumps(marker_response_schema(cited=False, no_attempt=True).model_json_schema())
    extra_in = _approx_tokens(on) - _approx_tokens(off)
    per_call = row_cost(_HAIKU, input_tokens=extra_in, cached_tokens=0, output_tokens=8)
    assert per_call * 90 < 0.001, per_call * 90


def test_total_worst_case_stays_far_under_the_cap() -> None:
    cover = 2 * row_cost(_HAIKU, input_tokens=2300, cached_tokens=0, output_tokens=60)  # one retry
    no_attempt = 90 * row_cost(_HAIKU, input_tokens=60, cached_tokens=0, output_tokens=8)
    total = _BASELINE_WORST + cover + no_attempt
    assert total < 0.07 < _CAP, total
```

- [ ] **Step 2: Run it**

Run: `PY -m pytest tests/test_l12_cost.py -q`
Expected: PASS. If `row_cost`'s keyword names differ (`lemely/io/llm/pricing.py:65`), match them.

- [ ] **Step 3: Run the full accuracy set once more** (the list in Global Constraints), plus all L12 Python tests:

`PY -m pytest tests/test_no_attempt_schema.py tests/test_blank_flag.py tests/test_class_set_pdf.py tests/test_class_set_covers.py tests/test_cover_reader.py tests/test_roster_match.py tests/test_migration_0055_class_sets.py tests/test_class_set_repo.py tests/test_class_set_job.py tests/test_class_set_routes.py tests/test_l12_cost.py tests/test_correction_ai.py tests/test_claude_schema_limits.py tests/test_reason_first.py tests/test_cited_marks.py tests/test_correction_off_topic.py tests/test_retry_median.py tests/test_retry_keep_higher.py tests/test_correction_shared_prefix.py tests/test_anthropic_adapter.py tests/test_claude_default_flip.py tests/test_accuracy_harness.py tests/test_golden_corpus.py tests/test_golden_binding_shapes.py tests/test_schemas.py tests/test_web_shared_constants.py tests/test_settings_example_drift.py tests/test_authz_matrix_complete.py -q`

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
pre-commit run --files tests/test_l12_cost.py
git commit -S -m "test(accuracy): pin L12 cost maths per paper" -- tests/test_l12_cost.py
```

### Task 15: Wire the Blank tile and the names row into L6's screens (BLOCKED until L6 merges)

**Agent:** `designer` (UI), with `implementer` for the progress payload. Start only after L6's PR is merged into `develop`. Rebase `redesign/l12` onto `develop` first.

**Files:**
- Modify: L6's marking-board tile component, which renders `.qt` tiles with the states Blank, Page missing and Marking. Find it with `grep -rn "Page missing" web/src` after L6 merges.
- Modify: L6's per-question progress model or view model, wherever it maps a progress frame to a tile state.
- Modify: L6's backend per-question progress DTO or SSE serializer (spec line 118, "marking progress per question over SSE"). Add `blank: bool`, taken from the `MARKING_PROGRESS` frame's `blank` (Task 2).
- Modify: L6's teacher upload screen (drop zone, files-received card, Recent uploads list):
  - teacher drops go to `uploadClassSet` (Task 11) instead of `uploadPaper`
  - Recent uploads gains `useClassSets()` rows
  - the files-received card shows the `.rnote`
- Test: L6's view-model unit test file (extend it), plus `web/e2e/name-check.spec.ts` (extend it with an upload-row hop)

**Interfaces:**
- Consumes:
  - Task 2: the `blank` frame key and `isBlankQuestion`
  - Task 11: `useClassSets`, `uploadClassSet`
  - Task 12: `recentRowVariant`, `recentRowStatus`
- Contract assumed from L6:
  - a pure tile-state function, say `tileState(q): "done" | "now" | "wait" | "blank" | "miss"`
  - a Recent uploads list component that takes rows

If L6 named them differently, use L6's names. The behaviour below is the contract.

- [ ] **Step 1: Write the failing tests in L6's test files**

In L6's marking-board view-model test, add:

```ts
it("a question with no attempt is a Blank tile, never Marking", () => {
  expect(tileState({ questionId: "6", state: "marked", blank: true, markerSource: "ai" })).toBe("blank")
  expect(tileState({ questionId: "6", state: "marked", markerSource: "blank" })).toBe("blank")
  expect(tileState({ questionId: "7", state: "marked", blank: false, markerSource: "ai" })).toBe("done")
})
```

In L6's teacher-upload view-model test (or `nameCheckModel.test.ts` if L6 has none), add a check that a set row with `namesNeedYou: 3` renders the variant `needsNames` with a "Check names" action linking to `/teacher/papers/sets/{id}/names`.

Extend `web/e2e/name-check.spec.ts`:

```ts
test("the names row in Recent uploads opens Name check", async ({ page }) => {
  await page.route("**/api/class-sets", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: { sets: [{ id: SET, label: "10A class set · 0625/22", status: "ready",
          paperCount: 24, markedCount: 24, namesNeedYou: 3, createdAt: new Date().toISOString(), error: null }] } })
      : route.continue(),
  )
  await page.route(`**/api/class-sets/${SET}/names`, (route) => route.fulfill({ json: names([omr]) }))
  await login(page)
  await page.goto("/teacher/grading")  // L6's upload route; use L6's real path
  await expect(page.getByText("3 names need you")).toBeVisible()
  await page.getByRole("link", { name: "Check names" }).click()
  await expect(page).toHaveURL(new RegExp(`/teacher/papers/sets/${SET}/names$`))
})
```

Run: `cd web && npx vitest run <L6 test files> && npx playwright test e2e/name-check.spec.ts`
Expected: FAIL.

- [ ] **Step 2: Implement**

1. **Backend.** In L6's per-question progress serializer, forward `blank=bool(payload.get("blank", False))` into its DTO, and add `blank: bool = False` to that DTO. In the TS mirror, add `blank?: boolean`.
2. **Tile.** In L6's `tileState`, return `"blank"` when `isBlankQuestion(q)` holds, ahead of the done or marked branch. The tile renders the mock's `.qt.blank`: `bg-transparent outline-2 outline-dashed outline-[oklch(.7_.02_240)] -outline-offset-2 text-on-surface-variant`, with the `<small>` label "Blank" (`font-sans text-[11px] font-semibold tracking-[.02em]`). The tile is static, with no animation.
3. **Upload.** In L6's teacher upload handler, call `uploadClassSet(file, { markScheme })` for every PDF, JPG or PNG file a teacher drops, then invalidate `classSetsKey`. The student flow keeps `/student/uploads` unchanged.
4. **Files-received card.** While any just-uploaded set is `reading`, show `<p className="rnote">Reading names off the covers. Problems will show here.</p>`, using L6's styling for `.rnote`.
5. **Recent uploads.** Merge `useClassSets()` rows with L6's single-paper rows, newest first. For each set row:
   - `needsNames`: the chip `chip low` "{n} names need you", plus a `btn t` `<Link to={`/teacher/papers/sets/${id}/names`}>Check names</Link>`
   - `marking`: a `.mini` bar at width `markedCount/paperCount`, plus "Marking {m} of {n}"
   - `marked`: "Marked" in success colour, plus an "Open" button to L8's papers screen
   - `failed`: the bad tone "Couldn’t split this file", plus the `error` in `title`
   - `reading`: "Reading names off the covers"

   Copy comes from `recentRowStatus`.

- [ ] **Step 3: Run the tests**

Run: `cd web && npx vitest run <L6 test files> tests/unit/nameCheckModel.test.ts tests/unit/blank.test.ts && npx playwright test e2e/name-check.spec.ts <L6's upload e2e spec> && npm run typecheck && npm run lint && npm run check:copy`
Plus the backend file L6 owns for progress: `PY -m pytest <L6's progress test file> -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
pre-commit run --files <every touched path>
git commit -S -m "feat(web): Blank tile and class-set rows on the upload and marking screens" -- <every touched path>
```

### Task 16: Fidelity screenshots, drift fixes and polish

**Agent:** `visual-qa` for the screenshots, `designer` for the fixes.

- [ ] **Step 1:** Serve the mocks with `cd .impeccable/mocks && python3 -m http.server 8765`. Capture `upload-r1/final.html`'s frames "Name check (teacher)" and "Tablet · name check", the Recent uploads `.r` rows, and the marking board with a Blank tile. Capture the app's `/teacher/papers/sets/:setId/names` at 390, 834 and 1280, with the class-set API stubbed as in `name-check.spec.ts`. Save the pairs to `reports/redesign/l12/` (not committed, per memory).
- [ ] **Step 2:** Compare pair by pair. Fix drift in spacing, type, colour and radius. List every deliberate difference in the PR body (the ring tone, the real cover image).
- [ ] **Step 3:** Run `/impeccable polish` on `web/src/portals/teacher/screens/names/`.
- [ ] **Step 4:** Re-run Task 13's gates and commit with explicit paths: `git commit -S -m "style(web): name check polish" -- web/src/portals/teacher/screens/names`.

### Task 17: Keep-list check

- [ ] **Step 1:** For each of K1–K16, write one line in the PR body naming the test that proves it, and run that test:
  - K1–K2: `tests/test_correction_ai.py` (existing blank and MCQ tests)
  - K3: `tests/test_web_review.py` blank exemption (existing)
  - K4–K5: `tests/test_blank_flag.py`
  - K6: `MarkingSchemaHashStableAcrossPythonOptimizeTests`
  - K7: `tests/test_correction_off_topic.py`
  - K8–K9: `tests/test_web_teacher.py` upload tests (existing, unchanged)
  - K10: `tests/test_class_set_repo.py::test_owner_sees_set_other_teacher_does_not`
  - K11–K12: `tests/test_authz_matrix_complete.py`
  - K13: `tests/test_class_set_pdf.py::test_single_scan_cap_is_unchanged` plus the existing PDF safety tests
  - K14: `tests/test_l12_cost.py`
  - K15: `tests/test_scan_metadata.py`
  - K16: `tests/test_class_set_routes.py::test_resolve_refuses_a_student_not_on_the_callers_rosters`

  Run: `PY -m pytest tests/test_web_teacher.py tests/test_web_review.py tests/test_scan_metadata.py -q`, plus the L12 set from Task 14.
- [ ] **Step 2:** Tick every item in the PR body.

### Task 18: Delete the old code

- [ ] **Step 1:** After Task 15, teacher drops use `uploadClassSet`. Search for `uploadPaper(` in `web/src`. If no caller remains, delete `uploadPaper` from `web/src/lib/hooks/useTeacherApi.ts:1073-1081`, and its `UploadResponse` type in `web/src/lib/teacherTypes.ts:89` if that type has no other user.
- [ ] **Step 2:** Keep `POST /api/papers/upload`. It is the regrade-compatible single-paper path and sits in the authz matrix. Deleting it is Needs user decision 6.
- [ ] **Step 3:** Run `cd web && npm run typecheck && npm run lint`, then commit: `git commit -S -m "refactor(web): drop the unused single-paper teacher upload call" -- web/src/lib/hooks/useTeacherApi.ts web/src/lib/teacherTypes.ts`.

### Task 19: Push and PR

- [ ] **Step 1:** Rebase onto `develop`. Move `0055_class_sets.down_revision` onto develop's Alembic head (`alembic heads`). Re-run Task 7's test.
- [ ] **Step 2:** Get the Opus `security-reviewer` pass on Task 3's diff (`lemely/io/pdf_content_walk.py`, `lemely/io/pdf_canonical.py`, `lemely/io/class_set/pdf.py`) and the routes' IDOR checks. Fix what it finds.
- [ ] **Step 3:** `git push -u origin redesign/l12`, then `gh pr create --base develop`. Give the PR body: the cost table, the keep-list ticks, the screenshot list, the "Needs user decision" items and the migration note ("0055 must not run on a shared database before the user approves").
- [ ] **Step 4:** After the Opus review, fixes and green CI, merge. Do not run the migration on staging until the user approves.

---

## Needs user decision

1. **Attribution (D1.12).** A confirmed cover name sets `teacher_papers.student_id`, but nothing writes the student's history, and the student never sees the paper. *Recommendation:* ship like that now. A follow-up decides whether console papers join student history, since that changes parents' and students' views.
2. **Upload size for class sets.** The mock shows a 41 MB set, but the cap is 25 MB, and Cloud Run refuses request bodies over 32 MiB. 25 MB holds about 15 papers of 16 pages each. *Recommendation:* keep 25 MB in v1, and in a follow-up add direct-to-storage signed upload URLs for sets (cap 150 MB).
3. **Cover panel shows the real scan.** The mock draws tidy "CANDIDATE NAME / NUMBER" boxes. The app shows the real cover page image from the existing staff preview route. *Recommendation:* real image, because the teacher needs to see the handwriting.
4. **Phone layout for Name check.** The mock has no phone frame. *Recommendation:* the list full width, then a bottom sheet with the cover panel when a row is tapped.
5. **Cover detection calibration.** The threshold of 0.80 is set on synthetic pages. No real class-set scan is in the repo. *Recommendation:* before release, run the detector on 2–3 real class sets (no model call; it is free) and adjust `COVER_SIMILARITY`. A missed cover merges two students into one paper, and that paper is flagged `pages_differ`.
6. **Extra fix-it reasons beyond the mock.** The mock shows "Two students match", "Cover is blank" and "Spelling differs". This plan adds "Not on your class lists", "Couldn't read the cover" and "Page count differs from the rest". *Recommendation:* keep all six; the last one catches a missed cover. Also: keep `POST /api/papers/upload` for now (Task 18).
7. **"Skip paper" meaning.** *Recommendation:* the paper stays marked and in Papers, but unnamed. Deleting it stays on the existing delete action.
8. **`no_attempt` lever default.** It ships off, so marking stays byte-identical. Turning it on changes the marker's input schema slightly. *Recommendation:* run one paid A/B on the 5 frozen real scripts (about $0.50 total, with your approval) before turning it on. The Blank tile works without it, for empty answer boxes and MCQ blanks.
9. **Ring tone.** The F1 `KeyRing` has no error tone, so this plan builds a small local `MatchRing` on the existing `--color-error` token. *Recommendation:* keep it local and add no F1 change.

## Dependencies beyond the master plan

- **L6 interface (Task 15).** L12 needs L6 to expose a pure tile-state function and a per-question progress DTO it can extend with `blank`, plus a Recent uploads list that accepts extra rows. L6's plan should name these. Task 15 adapts to L6's real names.
- **Shared `teacher.py`.** L12 imports `_start_run_if_claimed` from `lemely/web/routers/teacher.py` without editing that file. L8 or L5 must keep that function's signature.
- **Grading preview hook.** Task 13 may move the staff preview image hook out of `Grading.tsx`, which L6 or L8 also touch. That is a one-line import change; coordinate at rebase.
- **Migration order.** If L6 adds a migration, rebase `0055_class_sets.down_revision` onto it.
