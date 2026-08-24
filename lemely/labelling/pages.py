"""Server-rendered HTML pages for the two-pass blind labeller (spec §6, M2.3/#46).

A human cannot transcribe or mark handwriting from raw JSON in a terminal —
the spec requires a browser page precisely for that reason. Plain string
templates from the stdlib only: no template engine, and nothing added under
``web/`` (see the package docstring for why this stays outside that stack).

``render_pass1_page`` only ever reads ``context["scan_images"]`` /
``context["paper_id"]`` — never ``mark_scheme`` — so a leak would require
this function itself to start reading a key it does not read; the blindness
test suite (:mod:`tests.eval.test_labeller_blindness`) instead checks the
*context* passed into it never carries that key at all.
"""

from __future__ import annotations

import json
from html import escape


def render_pass1_page(context: dict[str, object]) -> str:
    """Render the pass-1 (transcription) page: scan images + a transcription form."""
    paper_id = context["paper_id"]
    if not isinstance(paper_id, str):
        raise TypeError(f"paper_id must be a str, got {type(paper_id)!r}")
    scan_images = context.get("scan_images", [])
    if not isinstance(scan_images, list):
        raise TypeError(f"scan_images must be a list, got {type(scan_images)!r}")

    paper_id_html = escape(paper_id)
    images_html = "\n".join(
        f'    <img class="scan-image" alt="scan region {index + 1}" '
        f'src="/scan?paper_id={paper_id_html}&amp;name={escape(str(name))}">'
        for index, name in enumerate(scan_images)
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Pass 1 (transcription) - {paper_id_html}</title>
</head>
<body>
  <h1>Pass 1: transcribe the handwriting</h1>
  <p>Paper: {paper_id_html}</p>
  <div class="scans">
{images_html}
  </div>
  <form method="post" action="/pass1?paper_id={paper_id_html}">
    <label for="question_id">Question ID:</label>
    <input id="question_id" name="question_id"><br>
    <label for="text">Transcription (exact, no correction):</label><br>
    <textarea id="text" name="text" rows="12" cols="90"></textarea><br>
    <button type="submit">Submit transcription</button>
  </form>
</body>
</html>
"""


def render_pass2_page(context: dict[str, object]) -> str:
    """Render the pass-2 (marking) page: mark scheme + the labeller's own transcription.

    Spec §6 pass-2 output contract: the rendered form carries one checkbox
    per mark point of the currently ``selected_question`` (keyed by the
    same ``mark_point_id`` concept :mod:`lemely.eval.records` uses), plus a
    ``question_type_judgement`` select populated from
    :class:`~lemely.core.loose_schemas.QuestionType` — the labeller's OWN
    judgement of the question's true type, deliberately independent of any
    pipeline-emitted ``question_type``. This is a REPORTING field for
    M2.4's stratification table (DA1); it must never be wired into
    split-assignment logic.
    """
    from lemely.core.loose_schemas import QuestionType

    paper_id = context["paper_id"]
    if not isinstance(paper_id, str):
        raise TypeError(f"paper_id must be a str, got {type(paper_id)!r}")
    mark_scheme = context.get("mark_scheme")
    if not isinstance(mark_scheme, dict):
        raise TypeError(f"mark_scheme must be a dict, got {type(mark_scheme)!r}")
    own_transcription = context.get("own_transcription", [])
    if not isinstance(own_transcription, list):
        raise TypeError(f"own_transcription must be a list, got {type(own_transcription)!r}")
    selected_question = context.get("selected_question")
    if selected_question is not None and not isinstance(selected_question, dict):
        raise TypeError(
            f"selected_question must be a dict or None, got {type(selected_question)!r}"
        )

    paper_id_html = escape(paper_id)
    questions = mark_scheme.get("questions", [])
    if not isinstance(questions, list):
        raise TypeError(f"mark_scheme['questions'] must be a list, got {type(questions)!r}")
    questions_html = "\n".join(
        f'    <li><a href="/pass2?paper_id={paper_id_html}'
        f'&amp;question_id={escape(str(question.get("id")))}">'
        f"Q{escape(str(question.get('id')))}</a> "
        f"({escape(str(question.get('marks')))} marks)</li>"
        for question in questions
        if isinstance(question, dict)
    )
    transcription_html = "\n".join(
        f"    <li><pre>{escape(json.dumps(record.get('payload', {})))}</pre></li>"
        for record in own_transcription
        if isinstance(record, dict)
    )

    if selected_question is None:
        marking_form_html = "  <p>No question available to mark for this paper.</p>"
    else:
        question_id_html = escape(str(selected_question.get("id")))
        answer_points = selected_question.get("answer_points", [])
        if not isinstance(answer_points, list):
            raise TypeError(f"answer_points must be a list, got {type(answer_points)!r}")
        mark_points_html = "\n".join(
            f'    <li><input type="checkbox" name="mark_point_id" '
            f'value="{escape(str(point.get("id")))}" id="mp_{escape(str(point.get("id")))}">'
            f'<label for="mp_{escape(str(point.get("id")))}">'
            f"{escape(str(point.get('id')))}: {escape(str(point.get('point')))} "
            f"({escape(str(point.get('marks')))} marks)</label></li>"
            for point in answer_points
            if isinstance(point, dict)
        )
        question_type_options_html = "\n".join(
            f'      <option value="{escape(member.value)}">{escape(member.value)}</option>'
            for member in QuestionType
        )
        marking_form_html = f"""  <h2>Marking Q{question_id_html}</h2>
  <form method="post" action="/pass2?paper_id={paper_id_html}">
    <input type="hidden" name="question_id" value="{question_id_html}">
    <h3>Mark points (check each one actually awarded)</h3>
    <ul>
{mark_points_html}
    </ul>
    <label for="awarded_marks">Awarded marks:</label>
    <input id="awarded_marks" name="awarded_marks" type="number"><br>
    <label for="question_type_judgement">Your judgement of this question's true type:</label>
    <select id="question_type_judgement" name="question_type_judgement">
{question_type_options_html}
    </select><br>
    <button type="submit">Submit mark</button>
  </form>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Pass 2 (marking) - {paper_id_html}</title>
</head>
<body>
  <h1>Pass 2: mark against the scheme</h1>
  <p>Paper: {paper_id_html}</p>
  <h2>Mark scheme</h2>
  <ul>
{questions_html}
  </ul>
  <h2>Your pass-1 transcription</h2>
  <ul>
{transcription_html}
  </ul>
{marking_form_html}
</body>
</html>
"""
