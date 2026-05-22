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
        f"you cannot find at all (do not invent question_ids)."
    )


def build_question_manifest_hash_key(mark_scheme: MarkScheme) -> str:
    """Hash the question id+type+marks tuple list so cache keys vary by paper, not just file."""
    import hashlib
    tokens = []
    for q in mark_scheme.all_questions_flat():
        tokens.append(f"{q.id}:{q.type.value}:{q.marks}")
    return hashlib.sha256("|".join(tokens).encode()).hexdigest()[:12]
