"""Prompts for AICorrector. Per-question rubric marking. VERSION invalidates cache."""

from __future__ import annotations

from lemely.core.loose_schemas import Question

VERSION = "5"

MARKER_SYSTEM_PROMPT = """
You are an experienced CAIE examiner marking a single exam question for a Cambridge
IGCSE / O-Level / A-Level paper. Apply the mark scheme strictly and consistently.

Rules:
- Apply standard CAIE abbreviations: ecf (error carried forward), owtte (or words to that effect),
  oe (or equivalent), cao (correct answer only), dep (dependent), ft (follow-through),
  nfww (not from wrong working), soi (seen or implied), AVP (alternative valid point),
  ora (or reverse argument), bo (benefit of the doubt), AW (alternative wording).
- Where the mark scheme lists "accept" variants, credit any of them.
- Where the mark scheme lists "reject" or "ignore", do NOT credit those forms.

**Method / accuracy / independent marks (M / A / B):**
- M marks are method marks: award when the student demonstrates a correct method step,
  even if they made an arithmetic slip that leads to a wrong final value. If a WORKING block
  is supplied, look there for evidence of the method step.
- A marks are accuracy marks and require the correct numerical value. **Whether an A mark
  depends on its preceding M mark is decided by THIS PAPER'S OWN printed Generic Marking
  Principles**, which are supplied in the user prompt when the paper prints them and they
  could be parsed. Those principles take precedence over anything in this section.
- **FALLBACK ONLY — where no Generic Marking Principles are supplied:** apply strict
  dependency, i.e. do not award an A mark if its associated M mark was not earned. This is
  the published CAIE default and is the fallback, never the primary rule.
- B marks are independent: award when the specific fact or value is correct, regardless of
  other marks.
- If WORKING is supplied and the student's final ANSWER is wrong but the working shows
  a correct substitution or intermediate step, award the M mark and apply ECF for subsequent
  A marks where the mark scheme permits (ecf / ft).

**Error carried forward (ECF / FT):**
- When the mark scheme marks a point as ecf or ft, award the mark if the student applied
  the correct method to their (incorrect) earlier value — i.e. the error was carried forward
  consistently. Check both the ANSWER and the WORKING for evidence.

**Levels-based and indicative content:**
- Judge extended-writing responses against each LevelDescriptor's mark_range and pick the
  band that best fits. Apply owtte: if the student's phrasing conveys the same meaning as
  a marking point, credit it.

**Diagrams / graphs:**
- The student's response is given as a text description by an earlier OCR pass. Mark
  accordingly; set confidence < 0.5 if the description is too vague to judge.

**When WORKING is supplied:**
- Read the WORKING block carefully before reading the ANSWER. Working may contain:
  - Correct intermediate values that earn M or B marks even when the final answer is wrong.
  - Crossed-out attempts that are still legible — if a crossed-out attempt shows correct
    method, award the method mark unless the student has replaced it with wrong working.
  - Unit conversions, substitutions, or rearrangements that count as method steps.
- Do NOT penalise for messy, partial, or disorganised working — only assess correctness.

**Marking chain of thought:**
Before writing `awarded_marks`, go through each mark point in the scheme one by one and state
whether the student satisfied it and why. Then sum only the satisfied marks.

Return:
- awarded_marks: integer, 0 ≤ awarded ≤ maximum_marks (the question's marks field).
- confidence: 0.0–1.0 — calibrated to these bands:
  - 0.95–1.00: exact match to a listed mark point or accepted variant; no judgment required
  - 0.80–0.95: clear owtte match / minor wording difference; confident but applied judgment
  - 0.60–0.80: borderline; could go either way, or mark scheme phrasing genuinely ambiguous
  - 0.00–0.60: mark scheme interpretation highly uncertain, or student response is illegible
- matched_point_ids: ids of AnswerPoints / LevelDescriptors / DrawingCriteria the student satisfied.
- feedback: one or two sentences a teacher can read; explain what was and was not credited,
  and cite the mark code (M1, A1, B1, ECF, etc.) where relevant.

---

## Worked Examples

**Example 1 — exact mark-point match (confidence 0.95–1.00)**
Mark scheme: "states that resistance increases with temperature (B1)"
Student: "resistance goes up as temperature rises"
-> awarded_marks=1, confidence=0.96, matched_point_ids=["p_resistance_temp"],
   feedback="B1 awarded: student correctly states the relationship (owtte)."

**Example 2 — owtte acceptance (confidence 0.80–0.95)**
Mark scheme: "speed of light = 3.0 x 10^8 m/s (B1)"
Student: "speed of light is 300 million metres per second"
-> awarded_marks=1, confidence=0.85, matched_point_ids=["p_light_speed"],
   feedback="B1 awarded: equivalent value stated in a different form (owtte)."

**Example 3 — borderline rejection (confidence 0.60–0.80)**
Mark scheme: "g = 9.81 N/kg (B1, cao)"
Student: "g is approximately 10 N/kg"
-> awarded_marks=0, confidence=0.68, matched_point_ids=[],
   feedback="B1 not awarded: mark scheme requires cao; 10 N/kg is an approximation not accepted here."
"""


def build_marker_user_prompt(
    question: Question,
    student_answer: str,
    student_working: str | None = None,
    prior_results: dict[str, int] | None = None,
    principles: list[str] | None = None,
    *,
    equivalence_gate: bool = False,
    prior_values: dict[str, str] | None = None,
) -> str:
    """Build the per-question marking prompt embedding the mark scheme subtree + student response.

    ``principles`` is the paper's own ``metadata.generic_marking_principles``,
    already extracted by :func:`lemely.io.det.gmp.extract_gmp` and, until #41,
    discarded. Ruling A13 makes them the **authority** on the A-mark dependency
    rather than the hard-coded rule in the system prompt, so they are injected
    with an explicit precedence statement — printing them without saying they
    govern would leave the model following the generic text.

    Injected into the USER prompt, not the system prompt, for two reasons: the
    principles are per-paper rather than per-run, and the cache key is built
    from the user prompt (``gemini.py:339``), so two papers with different
    printed principles cannot share a cached mark.

    ``equivalence_gate`` (US-013, defaults False): when True, appends the I6
    per-point-verdict instructions block below. With the flag at its default
    (False, every call today), the returned prompt is BYTE-IDENTICAL to
    before this story — no ``VERSION`` bump is needed because the prompt
    actually sent for the default-off path never changes (D19: I6/I7/I8
    share one bump, taken later at US-018's funded sweep).

    Post-I6-review Critical A fix: the I6 block used to ask for "one entry
    per AnswerPoint / LevelDescriptor / DrawingCriteria id", but
    ``correction_ai._awarded_from_verdicts``/``_check_point_evidence`` only
    ever resolve a verdict's ``point_id`` against ``question.answer_points``
    -- and ``LevelDescriptor`` (``loose_schemas.py``) has no ``id`` field at
    all, so the old wording asked the model for something the schema cannot
    supply. When ``question.answer_points`` is empty (levels-based,
    indicative-content, or a diagram/graph question judged holistically),
    the block now tells the model to leave ``point_verdicts`` empty instead
    -- matching ``_build_ai_corrected``'s dispatch guard, which falls back
    to the legacy (non-verdict) body in that exact case.

    ``prior_values`` (I7, US-013, defaults None): the student's OWN
    extracted answer (and working, if supplied) for each prerequisite part
    -- always a DIFFERENT LEAF question, never ``question`` itself, since
    ``correction_ai._maybe_apply_ecf_substitution`` excludes any prerequisite
    that resolves to the same leaf -- that a gated point structurally
    depends on. A NEW channel, distinct from ``prior_results`` above: that
    dict carries AWARDED MARKS for ECF's predecessor story; this one
    carries the raw answer VALUE (and working), because I7's re-mark needs
    to know what the student actually wrote, not how many marks it earned.
    Each value is now also TAGGED with the prerequisite point's own scheme
    text (a "depends on: ..." line) when known, so the model is told WHICH
    of the leaf's numbers is being carried forward when a leaf's answer
    contains more than one. Rendered as separate labelled LINES
    ("answer:"/"working:"/"depends on:"), indented under the id, never
    packed onto one line -- see the rendering site's own comment for why a
    single-line ``repr()`` was rejected.

    Per-LEAF VALUE, not per-POINT VALUE -- a DECLINED finding, not merely
    an undocumented one: extraction resolves no finer than one question's
    answer/working as a whole (``answers`` is keyed by leaf question id),
    so there is no per-point VALUE to look up regardless of how this
    channel is built; only the scheme TEXT the prerequisite point is
    checked against can be point-scoped, and now is. Appends its own block
    only when non-empty, so a call that never substitutes (every call
    today, and every call with ``ecf_substitution`` off) produces a
    BYTE-IDENTICAL prompt to before this story existed.
    """
    q_json = question.model_dump_json(indent=2, exclude_none=True, exclude_defaults=True)
    answer_text = student_answer if student_answer.strip() else "(blank — no response written)"
    parts = [
        "Mark this CAIE question.\n",
        f"MARK SCHEME SUBTREE (JSON):\n{q_json}\n",
        f"STUDENT ANSWER (verbatim from scan):\n{answer_text}\n",
    ]
    if student_working and student_working.strip():
        parts.append(
            f"WORKING (verbatim from scan, may be partial or messy):\n{student_working.strip()}\n"
        )
    if principles:
        principle_lines = "\n".join(f"  - {p}" for p in principles)
        parts.append(
            "THIS PAPER'S PRINTED GENERIC MARKING PRINCIPLES (verbatim from the mark scheme):\n"
            f"{principle_lines}\n"
            "These are the paper's own published rules and TAKE PRECEDENCE over the general "
            "guidance in the system prompt wherever the two differ — including the M/A "
            "dependency rule.\n"
        )
    if prior_results:
        prior_lines = "\n".join(
            f"  {qid}: {marks} mark(s) awarded" for qid, marks in prior_results.items()
        )
        parts.append(
            f"PRIOR PART RESULTS (same parent question, corrected before this part):\n"
            f"{prior_lines}\n"
            "Use these when applying ECF / follow-through rules.\n"
        )
    if equivalence_gate:
        if question.answer_points:
            parts.append(
                "PER-POINT VERDICTS (I6): in addition to the fields above, populate "
                "`point_verdicts` with one entry per AnswerPoint id in the mark scheme "
                "subtree above. For each point, work in this order — evidence, then "
                "verdict, then note:\n"
                "  1. evidence_span: quote the EXACT substring, verbatim, from the STUDENT "
                "ANSWER or WORKING above that justifies your verdict. Never invent or "
                "paraphrase text that is not present verbatim; leave it as an empty string "
                'for a "withheld" or "unverifiable" verdict.\n'
                '  2. verdict: "awarded" (the quoted evidence satisfies the point), '
                '"withheld" (the evidence shows the point was not satisfied), or '
                '"unverifiable" (the transcription is too unclear or incomplete to judge '
                "either way).\n"
                "  3. note: a short reason for the verdict (optional).\n"
                "Only once every point has a verdict, compute the total: sum the marks of "
                'every "awarded" point into awarded_marks and list their ids in '
                "matched_point_ids, exactly as you would without this section — "
                "point_verdicts must agree with those totals, not contradict them.\n"
            )
        else:
            parts.append(
                "PER-POINT VERDICTS (I6): this question has no `answer_points` "
                "(levels-based, indicative-content, or a diagram/graph question judged "
                "holistically) — there is no per-point id to attach a verdict to. Leave "
                "`point_verdicts` EMPTY and report `awarded_marks` / `matched_point_ids` "
                "exactly as you would without this section.\n"
            )
    if prior_values:
        # Post-review fix: `{value!r}` on a value containing a newline (the
        # answer/working composite -- see `_prior_value_text`) emitted a
        # literal backslash-n inside one quoted line, e.g.
        # `1a_i: 'v = 18\na = 150'` -- the model never sees a real line
        # break, only the two-character escape sequence. Dropping `!r`
        # outright traded that for a different defect: an unindented
        # continuation line at column 0 breaks out of this list, making it
        # ambiguous whether it is still part of the entry above or a new
        # top-level one. Fixed by indenting every line of `value` under its
        # own `qid:` header instead of rendering it inline, so a multi-line
        # value cannot be confused with an escape sequence OR with a
        # sibling entry:
        #     1a_i:
        #       answer: v = 18
        #       working: a = 150
        #       depends on: (a=) (v-u)/t in any form
        prior_value_blocks = []
        for qid, value in prior_values.items():
            indented = "\n".join(f"    {line}" for line in value.splitlines())
            prior_value_blocks.append(f"  {qid}:\n{indented}")
        prior_value_text = "\n".join(prior_value_blocks)
        parts.append(
            "PRIOR PART ANSWER VALUES -- ERROR CARRIED FORWARD (I7, US-013): for each "
            "id below, `answer`/`working` are the student's OWN extracted text for an "
            "earlier part a point below structurally depends on, verbatim -- this is "
            "NOT the mark scheme's correct value for that earlier part, and NOT marks "
            "awarded. `depends on`, where present, is the SCHEME's own text for the "
            "specific prerequisite point being carried forward, supplied by this tool, "
            "not transcribed from the student -- it tells you WHICH of the leaf's "
            "value(s) matters when the leaf answers more than one point:\n"
            f"{prior_value_text}\n"
            "The point(s) this applies to are marked ecf / ft / dep in the scheme and "
            "were NOT satisfied when checked against the scheme's correct value. "
            "Re-mark them now: if the student's method in THIS part correctly follows "
            "from the (possibly wrong) value shown above, award the point. Do not "
            "re-check or recompute whether the value above is itself correct -- that "
            "was already marked separately and is not this call's job.\n"
        )
    parts.append(
        f"Apply the mark scheme above. The maximum_marks for your awarded_marks field is "
        f"{question.marks}. Return JSON matching the AIMarkResponse schema."
    )
    return "\n".join(parts)
