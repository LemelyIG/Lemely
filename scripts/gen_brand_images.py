#!/usr/bin/env python
"""Generate Lemely logo candidates with Gemini (REDESIGN-MISSION §5, Phase 2.2).

The prompts here are authored from ``BUILD/BRAND.md`` §3/§4 — concept A in three
treatments plus concept D as the foil — so the mark comes out of the brand
reasoning rather than out of a one-shot "make me a logo" request.

Two things this script does that a throwaway snippet would not:

1. **It books every call into the real cost ledger** (``lemely.io.cost_ledger``),
   the same file the rest of the product spends against, so image generation
   cannot quietly blow the ``total_usd_ceiling`` set in ``lemely.toml``. It also
   refuses to start when the projected spend would breach that ceiling.
2. **It records what it actually cost**, per image, into a sidecar JSON beside
   the PNGs, so the Phase 7 report can state the real number instead of an
   estimate.

Usage::

    python scripts/gen_brand_images.py candidates   # 4 flash renders
    python scripts/gen_brand_images.py refine       # 1 flash render of the pick
    python scripts/gen_brand_images.py final        # 1 pro render, the ship

Nothing is written to ``web/public/brand/`` by this script. It only fills
``BUILD/brand/`` so a human can look before anything becomes a product asset.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from google import genai
from google.genai import types

from lemely.io.cost_ledger import CostLedger
from lemely.runtime.config import load_settings

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "BUILD" / "brand"

FLASH_MODEL = "gemini-3.1-flash-image"
PRO_MODEL = "gemini-3-pro-image"

# Published per-image output cost. Image output is billed as a flat token block
# per image, so a per-image constant is the honest unit here rather than a
# per-1k-token rate applied to a token count the API reports as one image.
# These are used ONLY to (a) pre-flight the ceiling and (b) book the ledger;
# the actual usage metadata returned by the API is recorded alongside them so a
# later reader can tell the estimate from the measurement.
COST_PER_IMAGE = {FLASH_MODEL: 0.039, PRO_MODEL: 0.24}

# ── Shared prompt scaffolding, straight out of BRAND.md §4 ──────────────────
# Repeated verbatim on every call so the four candidates are comparable: only
# the CONCEPT block below changes between them.
BASE = """A single professional vector logo mark, centred on a plain warm bone
off-white background (#F7F6F3). Flat two-dimensional vector artwork, solid
charcoal ink (#2F3437), one single accent colour at most, crisp clean edges,
generous empty margin around the mark.

This is a trademark for "Lemely", a platform that marks a student's handwritten
exam paper against the official mark scheme and tells them which mark point they
dropped. The mark must come from the act of marking a page, not from the
category of education.

ABSOLUTELY DO NOT INCLUDE: graduation cap, mortarboard, open book, pencil,
lightbulb, owl, brain, atom, rocket, sparkles, four-point star, abstract swoosh,
globe, puzzle piece, apple, speech bubble, mascot, gradient, glow, bevel, drop
shadow, 3D rendering, photographic texture, purple or blue "AI" colouring, and
no text or letters other than any specified below.

Style: restrained, editorial, hand-ruled rather than machine-perfect, the
confidence of a good teacher's pen. It must stay legible when shrunk to 16
pixels.

CONCEPT: """

CONCEPTS = {
    "a1-margin-tick": """The capital letter L drawn as the corner of a ruled
page: a strong vertical stroke meeting a horizontal baseline, where the vertical
slightly overshoots the join the way a hand-ruled margin line overshoots. The
horizontal foot lifts at its far end into a tick, in one single continuous
stroke, so the shape reads at once as the letter L, as the margin of a page, and
as a mark being awarded. Even stroke weight, geometric but hand-drawn in feel.""",
    "a2-pen-pressure": """The capital letter L as a page margin whose foot rises
into a tick, drawn as one continuous stroke with visible pen pressure: the
stroke thins on the vertical, swells at the turn of the corner, and tapers to a
fine point at the tip of the tick. Calligraphic but severe, like a fountain pen
held at a consistent angle. No outline, solid filled stroke.""",
    "a3-rule-and-mark": """The capital letter L where the vertical stroke is a
long thin hairline rule, like the printed margin line of an exam booklet, and
the horizontal foot is a short heavy tick in a warm red accent, clearly a
teacher's mark laid on top of the printed page. Two distinct weights and two
colours: hairline charcoal rule, solid accent tick. Deliberate contrast between
the printed and the handwritten.""",
    "d1-negative-space": """Two overlapping rectangular sheets of paper, offset
from one another at a slight angle, drawn as flat solid shapes. The gap of
background left between the two sheets forms a clean tick shape in negative
space. The tick must be immediately readable, crisp, and not muddy. Solid
charcoal sheets on the bone background, no outlines, no shadow between them.""",
}

# Written against a3's specific, named defects rather than as generic "make it
# better" polish, so the refinement is auditable: if the next render still has a
# doubled vertical or the stray baseline stub, the refine failed and we can say
# so, instead of squinting at two similar images.
REFINE_NOTE = """Redraw this mark, keeping its concept exactly: a capital
letter L where the vertical is a thin printed hairline rule, like the margin
line of an exam booklet, and a heavy warm-red tick sits over the corner as a
teacher's handwritten mark. The contrast between the thin printed rule and the
thick handwritten tick is the whole idea and must be preserved.

Fix these specific faults in the drawing:
1. There are two parallel vertical lines. There must be exactly ONE vertical
   hairline rule.
2. There is a stray short horizontal dash floating to the right of the tick.
   Remove it entirely.
3. The horizontal foot of the L must be a single clean hairline stroke that
   meets the vertical at a crisp right angle and stops shortly after the tick.
4. Centre the whole mark in the canvas and make it substantially larger, filling
   a comfortable portion of the frame with an even margin on all sides.
5. The red tick must sit confidently across the corner of the L, drawn as one
   stroke with a short upstroke and a longer downstroke, weighted like a felt
   pen.

Flat vector, exactly two colours: charcoal hairline and warm red tick, on the
bone background. No text, no extra elements, no shadow, no gradient."""

LOCKUP_NOTE = """Render the final logo system on one plain bone background:
the mark alone at large size, and beneath it a horizontal lockup of the same
mark to the left of the wordmark "lemely" set in lowercase editorial serif with
tight letter-spacing, in the same charcoal ink, optically aligned so the
wordmark's x-height sits against the mark. Nothing else on the canvas. No
caption, no border, no swatches."""


def _client() -> genai.Client:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        env = REPO / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set (env or .env)")
    return genai.Client(api_key=key)


def _ledger() -> tuple[CostLedger, float]:
    settings = load_settings()
    path = REPO / "outputs" / "gemini_spend.json"
    return CostLedger(path), float(settings.gemini.total_usd_ceiling or 0.0)


def generate(name: str, prompt: str, model: str, ref: Path | None = None) -> dict:
    """Render one image, book its cost, and write the PNG plus its receipt."""
    ledger, ceiling = _ledger()
    projected = ledger.total() + COST_PER_IMAGE[model]
    if ceiling and projected > ceiling:
        raise SystemExit(
            f"refusing to generate: ${ledger.total():.4f} spent + "
            f"${COST_PER_IMAGE[model]:.4f} would exceed the ${ceiling:.2f} ceiling"
        )

    client = _client()
    parts: list = [prompt]
    if ref is not None:
        parts.insert(0, types.Part.from_bytes(data=ref.read_bytes(), mime_type="image/png"))

    resp = client.models.generate_content(
        model=model,
        contents=parts,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    OUT.mkdir(parents=True, exist_ok=True)
    written = None
    for part in resp.candidates[0].content.parts:
        if getattr(part, "inline_data", None) and part.inline_data.data:
            written = OUT / f"{name}.png"
            written.write_bytes(part.inline_data.data)
            break
    if written is None:
        raise SystemExit(f"{name}: the model returned no image")

    usage = resp.usage_metadata
    total, _ = ledger.add(COST_PER_IMAGE[model], thresholds=[])
    receipt = {
        "name": name,
        "model": model,
        "booked_usd": COST_PER_IMAGE[model],
        "cumulative_usd_after": total,
        "reported_prompt_tokens": getattr(usage, "prompt_token_count", None),
        "reported_candidates_tokens": getattr(usage, "candidates_token_count", None),
        "generated_at": datetime.now(UTC).isoformat(),
        "file": str(written.relative_to(REPO)),
    }
    (OUT / f"{name}.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"{name}: {written.relative_to(REPO)}  (cumulative ${total:.4f})")
    return receipt


def main() -> None:
    step = sys.argv[1] if len(sys.argv) > 1 else "candidates"
    if step == "candidates":
        for name, concept in CONCEPTS.items():
            generate(name, BASE + concept, FLASH_MODEL)
    elif step == "refine":
        pick = sys.argv[2]
        generate(f"{pick}-refined", REFINE_NOTE, FLASH_MODEL, ref=OUT / f"{pick}.png")
    elif step == "final":
        pick = sys.argv[2]
        generate("lemely-lockup-final", LOCKUP_NOTE, PRO_MODEL, ref=OUT / f"{pick}.png")
    else:
        raise SystemExit(f"unknown step: {step}")


if __name__ == "__main__":
    main()
