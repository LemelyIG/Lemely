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
    """Render the pass-2 (marking) page: mark scheme + the labeller's own transcription."""
    paper_id = context["paper_id"]
    if not isinstance(paper_id, str):
        raise TypeError(f"paper_id must be a str, got {type(paper_id)!r}")
    mark_scheme = context.get("mark_scheme")
    if not isinstance(mark_scheme, dict):
        raise TypeError(f"mark_scheme must be a dict, got {type(mark_scheme)!r}")
    own_transcription = context.get("own_transcription", [])
    if not isinstance(own_transcription, list):
        raise TypeError(f"own_transcription must be a list, got {type(own_transcription)!r}")

    paper_id_html = escape(paper_id)
    questions = mark_scheme.get("questions", [])
    if not isinstance(questions, list):
        raise TypeError(f"mark_scheme['questions'] must be a list, got {type(questions)!r}")
    questions_html = "\n".join(
        f"    <li>Q{escape(str(question.get('id')))} "
        f"({escape(str(question.get('marks')))} marks)</li>"
        for question in questions
        if isinstance(question, dict)
    )
    transcription_html = "\n".join(
        f"    <li><pre>{escape(json.dumps(record.get('payload', {})))}</pre></li>"
        for record in own_transcription
        if isinstance(record, dict)
    )
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
  <form method="post" action="/pass2?paper_id={paper_id_html}">
    <label for="question_id">Question ID:</label>
    <input id="question_id" name="question_id"><br>
    <label for="awarded_marks">Awarded marks:</label>
    <input id="awarded_marks" name="awarded_marks" type="number"><br>
    <button type="submit">Submit mark</button>
  </form>
</body>
</html>
"""
