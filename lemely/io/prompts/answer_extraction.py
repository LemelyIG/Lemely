"""Prompts for GeminiAnswerExtractor. VERSION invalidates the cache on change."""

from __future__ import annotations

from lemely.core.loose_schemas import MarkScheme, Question, QuestionType

VERSION = "4"

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
- answer (string) — the final answer as described above; empty string if blank/unanswered.
- confidence (float 0.0-1.0) — calibrated to these bands:
  - 0.95–1.00: handwriting unambiguous; answer matches expected format exactly
  - 0.80–0.95: answer clear but required minor interpretation (e.g. messy digit, standard form)
  - 0.60–0.80: genuinely borderline — handwriting partially obscured or layout ambiguous
  - 0.00–0.60: handwriting unclear, student skipped the question, or answer contradicts itself
- source_region (string or null) — e.g. "page 2, q1a area".
- working_out (string or null) — see below.

**working_out field:**
Capture everything the student wrote in designated working/annotation areas for that question.
This includes:
- Show-your-working boxes and rough-work space adjacent to the question.
- Intermediate calculation steps, substituted values, and unit conversions written out.
- Equations the student wrote before arriving at the final answer.
- Annotations, labelled diagrams, or marginal notes in the allowed area for that question.
- Crossed-out attempts that are still legible and relevant.

Set working_out to null for MCQ questions or simple one-line recall questions where
no working area is present. For all other question types, transcribe the working content
faithfully even if messy or incomplete — a null here means no working was found at all.

Do not invent answers. Do not extract questions absent from the manifest. If the student left
a question blank, return answer="" with high confidence.

---

## Worked Examples

**Example 1 — unambiguous MCQ (confidence 0.95–1.00)**
Manifest entry: `- 1: type=mcq, marks=1`
Student: large circled "B" with no ambiguity.
-> question_id="1", answer="B", confidence=0.97, source_region="page 1 top-right", working_out=null

**Example 2 — handwritten calculation (confidence 0.80–0.95)**
Manifest entry: `- 3(b): type=calculation, marks=2`
Student writes: "F = ma = 2.0 x 9.8 = 19.6 N" with intermediate steps in the working box.
-> question_id="3(b)", answer="19.6 N", confidence=0.88,
   source_region="page 3 q3b area",
   working_out="F = ma = 2.0 x 9.8"

**Example 3 — ambiguous MCQ, partially circled letter (confidence < 0.50)**
Manifest entry: `- 5: type=mcq, marks=1`
Student appears to circle both B and C; a faint line through B suggests B was reconsidered.
-> question_id="5", answer="C", confidence=0.38,
   source_region="page 5 q5: pencil circle overlapping B and C, faint strikethrough on B",
   working_out=null
"""


def _summarize_question(q: Question) -> str:
    cmd = q.question_command or ""
    type_hint = q.type.value
    parts = [f"- {q.id}: type={type_hint}, marks={q.marks}"]
    if cmd:
        parts.append(f"  command: {cmd[:120]}")
    if q.type == QuestionType.MCQ:
        parts.append("  expected answer shape: single letter A/B/C/D")
        parts.append("  working_out: null (no working expected)")
    elif q.type in {QuestionType.CALCULATION, QuestionType.EQUATION}:
        parts.append("  expected answer shape: numerical value + unit if applicable")
        parts.append("  working_out: transcribe all steps, substitutions, and intermediate values")
    elif q.type in {QuestionType.LEVELS_BASED, QuestionType.INDICATIVE_CONTENT}:
        parts.append("  expected answer shape: extended written response")
        parts.append("  working_out: transcribe any planning notes or annotations in the allowed area")
    else:
        parts.append("  working_out: transcribe any working or annotations if present, else null")
    return "\n".join(parts)


def build_extractor_user_prompt(mark_scheme: MarkScheme) -> str:
    """Build the user prompt enumerating every leaf question the student should have answered."""
    leaves: list[Question] = []
    for q in mark_scheme.all_questions_flat():
        if q.parts:
            continue
        if q.marks <= 0:
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
        f"you cannot find at all (do not invent question_ids). "
        f"Populate working_out for non-MCQ questions that have visible working or annotations; "
        f"set it to null where no working area exists."
    )


def build_question_manifest_hash_key(mark_scheme: MarkScheme) -> str:
    """Hash the question id+type+marks tuple list so cache keys vary by paper, not just file."""
    import hashlib
    tokens = []
    for q in mark_scheme.all_questions_flat():
        tokens.append(f"{q.id}:{q.type.value}:{q.marks}")
    return hashlib.sha256("|".join(tokens).encode()).hexdigest()[:12]
