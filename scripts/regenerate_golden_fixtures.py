#!/usr/bin/env python
"""Regenerate tests/golden/*/scan.pdf from the committed answers.json corpus.

This is the M0.0 (#56) fixture-renderer repair's re-runnable regeneration
entrypoint. Each ``tests/golden/<case>/`` directory already carries
``answers.json`` (ground truth: question_id -> {student_answer, ...}) and
``mark_scheme.json``, both of which are left untouched here. Only
``scan.pdf`` is rewritten, using the fixed ``render_handwritten_scan``
(see ``lemely/accuracy/synth.py``): wrap-width measured at max-jitter font
size, cursor advance by actual rendered line height with an overlap check,
four-edge fidelity checks, and per-glyph fallback to the vendored
NotoSansMath-Subset font for Greek/math codepoints the handwriting fonts
lack.

``render_handwritten_scan`` is called with no try/except around it:
``RenderFidelityError`` (or any other exception) is left to propagate and
abort the run. That is deliberate — it *is* the generation-time round-trip
assertion this issue asks for. A script that caught the error and silently
fell back to a different font or truncated text would defeat the point.

Usage::

    python scripts/regenerate_golden_fixtures.py            # all cases
    python scripts/regenerate_golden_fixtures.py 0625_s20_qp_31_theory_partial

Per-case font is fixed at "Caveat" for every fixture except where noted
below in ``_FONT_OVERRIDES``; there is no recorded original seed/font_name
per fixture (no committed generator existed before this issue), so
regenerated PDFs are fidelity-equivalent to, not byte-identical with, any
prior scan.pdf.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lemely.accuracy.synth import AnswerBlock, render_handwritten_scan

_GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden"

# All current fixtures render fine with the default handwriting font; this
# is here so a future fixture with a font-specific need has a documented
# place to add an override rather than editing the loop below.
_FONT_OVERRIDES: dict[str, str] = {}

_SEED = 0


def _iter_case_dirs() -> list[Path]:
    return sorted(p for p in _GOLDEN_DIR.iterdir() if p.is_dir() and (p / "answers.json").exists())


def _load_answer_blocks(answers_json: Path) -> list[AnswerBlock]:
    data = json.loads(answers_json.read_text(encoding="utf-8"))
    return [
        AnswerBlock(question_id=question_id, text=entry["student_answer"])
        for question_id, entry in data.items()
    ]


def regenerate_case(case_dir: Path) -> None:
    answers = _load_answer_blocks(case_dir / "answers.json")
    font_name = _FONT_OVERRIDES.get(case_dir.name, "Caveat")
    out_pdf = case_dir / "scan.pdf"
    # No try/except: RenderFidelityError must propagate uncaught so a corpus
    # edit that reintroduces a missing-glyph or overprint defect fails this
    # script rather than silently shipping a bad fixture.
    render_handwritten_scan(answers, out_pdf, font_name=font_name, seed=_SEED)
    print(f"regenerated {out_pdf.relative_to(_GOLDEN_DIR.parent.parent)}")


def main(argv: list[str]) -> int:
    wanted = set(argv[1:])
    case_dirs = _iter_case_dirs()
    if wanted:
        case_dirs = [d for d in case_dirs if d.name in wanted]
        missing = wanted - {d.name for d in case_dirs}
        if missing:
            print(f"unknown case(s): {sorted(missing)}", file=sys.stderr)
            return 1
    if not case_dirs:
        print(f"no golden cases found under {_GOLDEN_DIR}", file=sys.stderr)
        return 1
    for case_dir in case_dirs:
        regenerate_case(case_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
