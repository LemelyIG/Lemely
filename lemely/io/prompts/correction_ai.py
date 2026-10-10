"""Prompts for AICorrector. Per-question rubric marking. VERSION invalidates cache."""

from __future__ import annotations

import re

from lemely.core.loose_schemas import MarkSchemeMetadata, Question

VERSION = "11"

_SYSTEM_PROMPT_HEAD = """
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

"""

#: The section on drawings for an answer the label binder's reader did not write: a typed
#: answer, a plain mapping, a legacy extraction. It is the text every marking call had before
#: VERSION "8". It names no `Drawing:`, so a student who writes that word has written an
#: answer and nothing more.
_DIAGRAMS_SECTION = """\
**Diagrams / graphs:**
- The student's response is given as a text description by an earlier OCR pass. Mark
  accordingly; set confidence < 0.5 if the description is too vague to judge.

"""

#: The section on drawings for an answer the label binder's reader wrote from a scan
#: (``binding_source == "label"``). That reader opens its description of a drawing with
#: `Drawing:` (``lemely.io.prompts.label_binding``), and only for its answers is the word
#: taken as that. Unmeasured.
_READER_DRAWINGS_SECTION = """\
**Drawings, diagrams and graphs:**
- You are never shown an image. Text in the response that follows `Drawing:` is not the
  student's own words: it is a description of what the student drew, written by the reader
  that looked at the scan. The drawing is on the page; the description is your evidence of it.
- Judge each mark point against the facts the description states: what was drawn and how
  many, where lines start and end, which way arrows point, where lines are closer or further
  apart, labels, values and units, plotted points and the line through them.
- Do not refuse a mark because no image or diagram is provided, and do not treat the
  description as a written answer offered in place of a drawing.
- Do not award a point that needs a detail the description does not state. Silence about a
  detail is not evidence of it: withhold that point and say in `feedback` which detail was
  missing. A word of praise in a description ("correct", "accurate") is not a fact and earns
  nothing.
- Set confidence < 0.5 if the description is too vague to judge a mark point.
- A description of a drawing that the reader did not open with `Drawing:` is marked by the
  same rules.

"""

_SYSTEM_PROMPT_TAIL = """\
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

**Last field: `addresses_question` (a separate observation, not part of the marking):**
Once everything else in your reply is decided, and without revisiting it, also report whether
the student's response is an attempt at the question this mark scheme entry belongs to. You
are not shown the question paper, only the mark scheme entry, so judge from the subject matter
and the task the entry is about.
- `yes`: the response is an attempt at this question, however poor. A wrong method, a wrong
  quantity or unit, a definition offered where a calculation is needed, a muddled or incomplete
  attempt, or any other zero-mark answer on the same subject matter is `yes`.
- `no`: only when the response is plainly about a different topic or task from anything this
  entry concerns, so that it reads as the answer to some other question. Being wrong, however
  badly, is never a reason for `no`.
- `unclear`: the response is blank, is a single word or number that could fit many questions,
  or is too short to tell. Whenever you are torn between `no` and anything else, choose
  `unclear`.
For instance:
  - The entry is a calculation of the mass of a product from the moles reacting; the student
    wrote "a mole is 6.02 x 10^23 particles of a substance" -> `yes` (a definition where the
    calculation was needed: no credit, but an attempt at this question).
  - The entry asks how vaccination gives long-term immunity; the student wrote "the left
    ventricle has a thicker wall because it pumps blood to the whole body" -> `no`.
  - The entry asks for two causes of inflation; the student wrote "2.5" -> `unclear`.
This field never changes awarded_marks, confidence, matched_point_ids or feedback: mark exactly
as you would if it were not asked for. It only records whether the response belongs here.

---

## Worked Examples

**Example 1 — exact mark-point match (confidence 0.95–1.00)**
Mark scheme: "states that resistance increases with temperature (B1)"
Student: "resistance goes up as temperature rises"
-> awarded_marks=1, confidence=0.96, matched_point_ids=["p_resistance_temp"],
   feedback="B1 awarded: student correctly states the relationship (owtte).",
   addresses_question="yes"

**Example 2 — owtte acceptance (confidence 0.80–0.95)**
Mark scheme: "speed of light = 3.0 x 10^8 m/s (B1)"
Student: "speed of light is 300 million metres per second"
-> awarded_marks=1, confidence=0.85, matched_point_ids=["p_light_speed"],
   feedback="B1 awarded: equivalent value stated in a different form (owtte).",
   addresses_question="yes"

**Example 3 — borderline rejection (confidence 0.60–0.80)**
Mark scheme: "g = 9.81 N/kg (B1, cao)"
Student: "g is approximately 10 N/kg"
-> awarded_marks=0, confidence=0.68, matched_point_ids=[],
   feedback="B1 not awarded: mark scheme requires cao; 10 N/kg is an approximation not accepted here.",
   addresses_question="yes"
"""

#: The system prompt for every answer the label binder's reader did not write. It is the
#: text of VERSION "7", from before that reader described drawings.
MARKER_SYSTEM_PROMPT = _SYSTEM_PROMPT_HEAD + _DIAGRAMS_SECTION + _SYSTEM_PROMPT_TAIL

#: The system prompt for an answer the label binder's reader wrote from a scan. It differs
#: from ``MARKER_SYSTEM_PROMPT`` in the section on drawings and nowhere else.
READER_MARKER_SYSTEM_PROMPT = _SYSTEM_PROMPT_HEAD + _READER_DRAWINGS_SECTION + _SYSTEM_PROMPT_TAIL

# The label binder's reader opens its description of a drawing with this word
# (``lemely.io.prompts.label_binding``). Two blocks bound to one part are joined, so it
# may come after the student's own writing. Capital D and a colon, with no letter before:
# a student who writes "my drawing: ..." has not written a description. The word is looked
# for only in an answer that reader wrote: anywhere else the student wrote or typed it.
_DRAWING_DESCRIPTION = re.compile(r"(?<![A-Za-z])Drawing:")
_ANSWER_HEADER = "STUDENT ANSWER (verbatim from scan):"
_DRAWING_ANSWER_HEADER = (
    "STUDENT ANSWER (from the scan; the text after `Drawing:` is the reader's description "
    "of what the student drew, not the student's own words):"
)

#: The syllabuses whose schemes get ``SCIENCE_DEFAULT_RULES`` when they print none of their
#: own: Cambridge IGCSE Biology, Chemistry and Physics. One published scheme was read
#: (0625/41, Oct/Nov 2024). Its "Science-Specific Marking Principles" are common text: a
#: physics scheme that gives rules for chemical equations and takes its spelling examples
#: from chemistry and biology. No other syllabus is listed because no scheme of another was
#: read. Mathematics prints different rules and must never be added here.
SCIENCE_SYLLABUS_CODES: frozenset[str] = frozenset({"0610", "0620", "0625"})

#: The marking rules Cambridge publishes for its science papers, restated in this project's
#: own words from the "Science-Specific Marking Principles" of the scheme named above. Sent
#: only for a science scheme stored without principles of its own
#: (:func:`default_marking_rules`): the deterministic parser stored none for any of the 289
#: corpus schemes, and the marker then made up a rule on significant figures that is the
#: reverse of the printed one.
#:
#: Two departures from the published text, both on purpose. A missing unit is left alone:
#: the published rule withholds the final mark for it, but the paper often prints the unit
#: on the answer line and the marker is not shown the paper. Error carried forward is tied
#: to a wrong value the marker can see, since it cannot check one it cannot see.
#:
#: The rule on significant figures says more than the published sentence, so that it cannot
#: be read loosely. A mark scheme answer of 20 or 300 shows one figure or several, and a
#: marker that chose one would accept 24 for 20 and 340 for 300: such an answer is compared
#: at two figures or more. An answer given to one figure is accepted only for a mark scheme
#: answer of one figure: the scheme that was read credits a rounded answer only when it is
#: "expressed to two or more significant figures".
#:
#: The closing paragraph is the limit on all of it: a rule here never loosens a mark point
#: that sets its own precision. This text has not been measured.
SCIENCE_DEFAULT_RULES = """\
GENERAL MARKING RULES FOR CAMBRIDGE SCIENCE PAPERS (this mark scheme was stored without its \
printed marking principles; these are the rules Cambridge publishes for its science papers, \
restated, and they are not text from this paper):
  - Keywords: credit a scientific term only where it is used correctly in its context. A \
keyword that is present but misused earns nothing.
  - Contradictions: do not choose between contradictory statements in the same question \
part, and give no credit for a correct statement that the same part contradicts. Wrong \
science that is irrelevant to the question is ignored.
  - Spelling: spelling need not be correct, but a syllabus term must be clear enough that it \
cannot be taken for a different syllabus term.
  - Error carried forward: a wrong answer from an earlier part that is then used in a \
scientifically correct way earns the later marking points. Apply this only where the \
student's working, or an earlier-part value supplied below, shows the wrong value being \
used; never assume it.
  - Lists: where a set number of responses is asked for, read the whole response as \
continuous prose. A response the mark scheme says to ignore does not count towards the \
number. A wrong response earns nothing and does count towards it. Give no credit for a \
response that is contradicted elsewhere in the answer; two responses that contradict each \
other count as one wrong response. Further responses beyond the number asked for may be \
ignored if they contradict nothing.
  - Calculations: a correct final answer earns full credit for its calculation even with no \
working or with wrong working, unless the mark scheme entry requires the working.
  - Significant figures: where the mark scheme entry does not say how many significant \
figures are required, count the significant figures the mark scheme's answer shows, round \
the student's final answer to that many, and accept it only if it then equals the mark \
scheme's answer. For a mark scheme answer of 7.3 J, 7.26 J is correct, and 7.2 J and 7 J \
are not. Where the mark scheme's answer ends in zeros before the decimal point (20, 300, \
17 000), those zeros may or may not be significant, so the count is ambiguous: count the \
digits up to the last one that is not zero, and compare at that many significant figures or \
at two, whichever is more. Never compare with such an answer at one significant figure. \
Two worked cases, for a mark scheme answer of 600 Pa: 604 Pa is 600 at two significant \
figures, so it is correct; 640 Pa is 640 at two significant figures, so it is not correct, \
although it would round to 600 at one. A student's answer given to one significant figure \
is accepted only when the mark scheme's answer has one significant figure too; an answer \
written exactly as the mark scheme's is always correct. A mark point that sets its own \
precision, or that asks for the exact value or says cao, is never loosened by this rule. \
This may not hold for a value the student had to measure.
  - Standard form: an answer in standard form whose coefficient is not between 1 and 10 is \
still correct if it converts to the mark scheme's answer.
  - Units: a final answer to a calculation given with a wrong unit does not earn the final \
answer mark, unless the mark scheme gives the unit a mark of its own or shows it as \
optional. You are not shown the question paper, which often prints the unit on the answer \
line: these rules say nothing about an answer written with no unit, so treat that case \
exactly as you would without them.
  - Chemical equations: multiples and fractions of the balancing numbers are acceptable, and \
state symbols are ignored, unless the mark scheme entry says otherwise.
The MARK SCHEME SUBTREE above always wins. Where an entry sets its own precision or says an \
exact value is required (a stated number of significant figures or decimal places, a \
tolerance or a range, cao, "exact", or accept / reject / ignore forms), apply the entry as \
written: none of these rules loosens it. These rules take precedence over the general \
guidance in the system prompt only where the two differ. Apart from the rule on \
calculations, they say nothing about whether an A mark depends on an M mark: no Generic \
Marking Principles are supplied for this paper, so the system prompt's fallback for that \
still applies.
"""


def printed_principles(metadata: MarkSchemeMetadata) -> list[str] | None:
    """The marking principles the scheme itself carries, generic first, or None.

    Both lists: ``generic_marking_principles`` and ``subject_specific_principles``. The
    second is where a scheme's own rules on significant figures, units and error carried
    forward are stored, and it used to be left out. An entry of whitespace is not a
    principle.
    """
    printed = [
        principle
        for principle in (
            *metadata.generic_marking_principles,
            *metadata.subject_specific_principles,
        )
        if principle.strip()
    ]
    return printed or None


def default_marking_rules(metadata: MarkSchemeMetadata) -> str | None:
    """``SCIENCE_DEFAULT_RULES`` for a science scheme that carries no principles, else None.

    A scheme that carries any principle of its own gets no default: its own text is what
    the marker is given, and a default beside it would be a second voice. A syllabus
    outside ``SCIENCE_SYLLABUS_CODES`` gets none either, so a mathematics paper is marked
    exactly as before unless its scheme carries its own principles.
    """
    if printed_principles(metadata) is not None:
        return None
    if metadata.subject_code not in SCIENCE_SYLLABUS_CODES:
        return None
    return SCIENCE_DEFAULT_RULES


def marker_system_prompt(*, reader_describes_drawings: bool = False) -> str:
    """The system prompt for one marking call.

    ``reader_describes_drawings`` is True only for an answer whose text the label binder's
    reader wrote from a scan. Such a call gets ``READER_MARKER_SYSTEM_PROMPT``, whose
    section on drawings takes what follows ``Drawing:`` as the reader's description. Every
    other call (a typed quiz answer, a plain mapping, a legacy extraction) gets
    ``MARKER_SYSTEM_PROMPT``, which does not name the word.
    """
    return READER_MARKER_SYSTEM_PROMPT if reader_describes_drawings else MARKER_SYSTEM_PROMPT


def build_marker_user_prompt(
    question: Question,
    student_answer: str,
    student_working: str | None = None,
    prior_results: dict[str, int] | None = None,
    principles: list[str] | None = None,
    *,
    equivalence_gate: bool = False,
    prior_values: dict[str, str] | None = None,
    default_rules: str | None = None,
    reader_describes_drawings: bool = False,
) -> str:
    """Build the per-question marking prompt embedding the mark scheme subtree + student response.

    ``principles`` is the paper's own printed principles (:func:`printed_principles`:
    ``metadata.generic_marking_principles``, which
    :func:`lemely.io.det.gmp.extract_gmp` fills and which was discarded until #41,
    followed by ``metadata.subject_specific_principles``). Ruling A13 makes them
    the **authority** on the A-mark dependency
    rather than the hard-coded rule in the system prompt, so they are injected
    with an explicit precedence statement — printing them without saying they
    govern would leave the model following the generic text.

    ``default_rules`` (:func:`default_marking_rules`, defaults None) is the block
    sent for a scheme that carries no principles of its own and belongs to a
    syllabus family with published general rules. It is appended as given, and
    only when ``principles`` is empty: the paper's own text is never sent with a
    default beside it. With None the prompt is byte-identical to before.

    ``reader_describes_drawings`` (defaults False) says the answer's text was
    written by the label binder's reader from a scan. Only then is ``Drawing:``
    in the answer taken as the opening of that reader's description of a
    drawing, and the answer headed as one. With False the word is the student's
    own, written or typed, and the answer is headed "verbatim from scan" as it
    always was: the student controls the text, so the text alone cannot say who
    wrote it. Pass the same value to :func:`marker_system_prompt`.

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
    # A drawing reaches the marker as the reader's description of it. Calling that
    # "verbatim" had the marker refuse marks because "no diagram was provided".
    answer_header = (
        _DRAWING_ANSWER_HEADER
        if reader_describes_drawings and _DRAWING_DESCRIPTION.search(student_answer)
        else _ANSWER_HEADER
    )
    parts = [
        "Mark this CAIE question.\n",
        f"MARK SCHEME SUBTREE (JSON):\n{q_json}\n",
        f"{answer_header}\n{answer_text}\n",
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
    elif default_rules:
        parts.append(default_rules)
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
