"""Prompts for the label binder's read. VERSION invalidates the cache on change.

The reader returns one list, in reading order, of the question labels it sees and the
blocks of student writing. It is never asked for a question id and is never shown a
mark-scheme point: ``lemely.core.label_sequence.bind_stream`` decides which question each
block belongs to, from the order of the list alone.

Both prompts are a measured artefact (gemini-3.8-flash, five runs on one scan, prompt
version "il1" of the measurement harness). They differ from what was measured by one
rule, stated once in each prompt: a label is listed before the writing that sits under
it. ``bind_stream`` trusts that order and has no way to check it, so a reader that
lists writing before its label binds the whole paper one part late.
"""

from __future__ import annotations

from lemely.core.loose_schemas import MarkScheme, Question

VERSION = "1"

LABEL_BINDING_SYSTEM_PROMPT = """
You are an expert at reading scanned CAIE (Cambridge IGCSE / O-Level / A-Level) exam scripts.

You are given the scan as a sequence of separate page images, one image per page, in
page order starting at page 0 (the first image is page 0, the second is page 1, and so on).

Write down what is on the script as ONE list, `items`, in the order a person reads it: page
by page, top to bottom within a page, and left to right along a line. The list holds two
types of item, mixed together in that reading order:

- "label" -- a question label.
- "answer" -- a block of the student's own writing or drawing.

The ORDER of the list is what matters. Afterwards, each answer is given to the question
whose label comes most recently before it in your list. So every label must be in the list
at the place where it is on the page, and every answer must come after the label of the
part it answers and before the next label.

Always list a question label BEFORE the student's writing that sits under it, never after
it: the label first, then the writing in that part's space, then the next label. The same
holds for writing the student tied to a part with an arrow or a note: it goes after that
part's label, never before it.

You do NOT name the question an answer belongs to. Never write a question number or a part
label in any field of an answer item, and never add a question id field of any kind.

Every item says where it is: "page" is the 0-based page image index, one of the indices you
were actually given, and "box" is [ymin, xmin, ymax, xmax], the four coordinates normalised
to 0-1000 relative to that page image's own height and width (0,0 = top-left, 1000,1000 =
bottom-right). The distance down the page comes first.

## label items

A question label is the short number, letter or numeral that opens a question or one of
its parts: a question number ("1", "2", "10"), a part letter ("(a)", "(b)"), a sub-part
numeral ("(i)", "(ii)", "(iii)"). On a printed paper it sits at the left edge, at the start
of the question or part it opens.

- One label item per label. When two labels share a line -- "(a)  (i)  Name the two
  cities ..." -- write two label items, "(a)" then "(i)".
- `text`: copy the label exactly as it appears, brackets included: "1", "(a)", "(ii)".
- `kind`: "printed" for a label printed on the paper. "handwritten" for a label the STUDENT
  wrote to say which question a piece of their writing answers -- for example "Q3 b" beside
  writing on a blank page. Copy a handwritten label exactly as written, as one item.
- `box`: a tight box around the label itself, not around the question text beside it.
- List a label every time it opens a question or part, on every page, including parts the
  student left blank and pages the student did not write on.
- A printed label is still a printed label when someone has ringed it, underlined it,
  ticked it or written over it. List it, with kind "printed".
- The question number that opens a whole question ("1", "2", ...) is a label like any
  other. List it where it is printed, even when its page holds only the introduction to
  the question or a figure, with no part letter and no student writing.

These are NOT question labels. Never list them as label items:
- Numbered lines inside one part. A part may ask for several answers on numbered lines --
  "1. ........" and "2. ........" under one question and one mark bracket. Those numbers
  count lines within a single part; they do not open a question.
- Page numbers at the top or bottom of a page, and any sheet numbering added by hand or by
  a scanner in a corner.
- Mark brackets and totals: "[1]", "[3]", "[Total: 15]".
- Figure and table names: "Fig. 12.1", "Table 12.2".
- A label mentioned inside a sentence: "Use your answer to (a) to ...",
  "your answer to (b)(ii)".
- Numbers and letters on diagrams, graphs, axes and scales; the option letters A, B, C, D
  of a multiple-choice question; candidate and centre numbers; barcodes.

## answer items

One answer item for each block of the student's own handwriting or drawing.

- A block is writing that sits together in one place on the page: the lines of an answer,
  a patch of working with the final answer beside or below it, something the student drew
  on a printed diagram or graph, a ring or a tick the student used to choose an option.
- A block never crosses a question label. Where a printed question label lies between two
  pieces of writing, they are two blocks. If you are not sure that two pieces of writing
  belong together, write them as separate items.
- `box`: the tight box around the whole block of student writing, where it physically is
  on the page -- not the printed question, not the printed answer line or its prompt.
- `answer`: what the student wrote, transcribed faithfully in their own wording and
  spelling.
  - For a calculation, `answer` is the final stated value with its unit ("42 m/s",
    "1.6 x 10^-19 C"); keep the student's own standard form and units. Everything leading
    up to it goes in `working_out`.
  - Where the student answered on printed numbered lines within one part, keep the line
    numbers: "1. copper 2. zinc".
  - Where one part has several printed prompt lines to fill in, keep each printed prompt
    with what the student wrote on it: "colour at start: blue; colour at end:
    colourless". A single answer line ("mass = ........ g") needs only the value.
  - For a drawing, or for marks added to a printed diagram or graph, describe briefly what
    the student drew: "curved line through (2,4) and (5,10)".
  - For a ringed or ticked option, give the option chosen.
  - Crossed-out work: `answer` is the final attempt that is not crossed out; an earlier
    crossed-out attempt that is still legible goes in `working_out`.
- `working_out`: the working that belongs to the block -- equations, substituted values,
  intermediate steps, unit conversions, annotations. null when the block has none.
- `confidence` (0.0-1.0): how legible the block is.
  - 0.95-1.00: handwriting unambiguous
  - 0.80-0.95: clear, but needed minor interpretation (a messy digit, standard form)
  - 0.60-0.80: genuinely borderline -- partly obscured, or two readings are plausible
  - 0.00-0.60: unclear

### Where an answer item goes in the list, and `placed_by`

- "position" -- the usual case. The writing sits in the space of the part it answers. Put
  the item where it is on the page: after the label above it, before the next label.
- "arrow" -- the student has TIED a piece of writing to a part that it does not sit under.
  Students who run out of room finish an answer somewhere else -- at the foot of the page,
  in a margin, above the question, on a blank page -- and show where it belongs with an
  arrow, a bracket, a line, a matching pair of asterisks, or a note such as "continued
  from (b)". Put that item directly after the label it is tied to, together with the other
  writing for that part, NOT where it sits on the page. Its `page` and `box` still say
  where the writing physically is.
- "uncertain" -- you cannot tell which part a piece of writing belongs to: a stray note or
  rough working with no arrow or other tie, away from any answer space. Put the item where
  it is on the page, as for "position", and mark it "uncertain".

Never drop writing. Every piece of the student's writing appears in exactly one answer
item, whichever of the three ways it was placed.

Do not write as an answer item: anything printed on the paper; a marker's ticks, crosses,
mark totals and comments (usually in a different ink, often red); scanner watermarks; a
label the student wrote, which is a label item. Where the student left an answer space
blank, write nothing for it. Do not invent writing that is not on the page.
"""


def _is_question_number(text: str) -> bool:
    return text.isascii() and text.isdigit() and not text.startswith("0")


def _is_part_name(text: str) -> bool:
    return text.isascii() and text.isalpha() and text.islower()


def _printed_labels(mark_scheme: MarkScheme) -> list[tuple[str, int]]:
    """Each leaf's label as the paper prints it ("1(a)(i)") with its marks, in paper order.

    The label comes from the scheme tree, not from the shape of the id. A top-level id is
    the question number. A part's own piece is what its id adds to its parent's id, with
    the "_" separators dropped: "1a_i" under "1a" under "1" is "1(a)(i)", "3ii" under "3"
    is "3(ii)", and "7a_ii_a" under "7a_ii" is "7(a)(ii)(a)".

    A leaf whose label cannot be told this way is left out, with everything under it: a
    top-level id that is not a number, a part whose id does not extend its parent's, a
    piece that is not lower-case letters. A made-up label would send the reader looking
    for something the paper does not print, and ``bind_stream`` cannot bind such a leaf
    either. No scheme in the corpus has one.
    """
    labels: list[tuple[str, int]] = []

    def walk(questions: list[Question], parent_id: str | None, above: str) -> None:
        for question in questions:
            if parent_id is None:
                if not _is_question_number(question.id):
                    continue
                label = question.id
            else:
                if not question.id.startswith(parent_id):
                    continue
                pieces = [p for p in question.id[len(parent_id) :].split("_") if p]
                if not pieces or not all(_is_part_name(piece) for piece in pieces):
                    continue
                label = above + "".join(f"({piece})" for piece in pieces)
            if question.parts:
                walk(question.parts, question.id, label)
            else:
                labels.append((label, question.marks))

    walk(mark_scheme.questions, None, "")
    return labels


def build_label_binding_user_prompt(mark_scheme: MarkScheme, *, page_count: int) -> str:
    """Build the user prompt: the page indices, the paper, and the labels to look for.

    From the mark scheme it carries each leaf's printed label and marks, and nothing
    else: no id, no stem, no mark-scheme point.

    Raises:
        ValueError: ``page_count`` is less than 1.
    """
    if page_count < 1:
        raise ValueError(f"page_count must be at least 1, got {page_count}")
    if page_count == 1:
        pages = "You are given 1 page image, index 0. Every `page` value MUST be 0."
    else:
        pages = (
            f"You are given {page_count} page images, indexed 0 to {page_count - 1} in the "
            "order attached. Every `page` value MUST be one of these indices."
        )
    meta = mark_scheme.metadata
    year = meta.session_year if meta.session_year is not None else "Specimen"
    label_list = "\n".join(
        f"- {label} [{marks} mark{'s' if marks != 1 else ''}]"
        for label, marks in _printed_labels(mark_scheme)
    )
    return (
        "Read the attached scanned paper and write down its question labels and the student's "
        "writing as one list, in reading order.\n\n"
        f"{pages}\n\n"
        f"Paper: {meta.subject_code}/{meta.paper_number}{meta.paper_variant} "
        f"{meta.session_month.value} {year}.\n\n"
        "For orientation only, these are the questions the printed paper asks, in order, with "
        "their marks. Use the list to know which printed labels to look for. List a label "
        "only where you can see it on a page, and never copy an entry of this list into "
        f"your reply:\n{label_list}\n\n"
        'Return JSON: {"items": [...]}. Each item has "type" "label" or "answer". The list is in '
        "reading order, except that writing the student tied to a part with an arrow or a note "
        "goes directly after that part's label. A label is always listed before the writing "
        "that sits under it, never after it. No item contains a question id."
    )
