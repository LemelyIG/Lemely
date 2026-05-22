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
    q_json = question.model_dump_json(indent=2, exclude_none=True, exclude_defaults=True)
    answer_text = student_answer if student_answer.strip() else "(blank — no response written)"
    return (
        f"Mark this CAIE question.\n\n"
        f"MARK SCHEME SUBTREE (JSON):\n{q_json}\n\n"
        f"STUDENT ANSWER (verbatim from scan):\n{answer_text}\n\n"
        f"Apply the mark scheme above. The maximum_marks for your awarded_marks field is "
        f"{question.marks}. Return JSON matching the AIMarkResponse schema."
    )
