r"""Flatten the real-handwriting papers to images before extraction ever sees them (#59).

Implements DECISION 1 of the human's 2026-08-25T12:35:00+03:00 ruling
(``BUILD/ACCURACY-INBOX.md``).

**Why this script has to exist.** The three Paper 42 files are *not* scans.
They are the original CAIE question-paper PDFs with vector stylus ink drawn
on top, and their **text layer is intact** — ``0625_s25_qp_42`` carries 23,727
characters of extractable printed text by this script's own count (the
2026-08-25 audit recorded 34,090 for the same file; see the manifest's
``text_char_counts_differ_from_the_2026_08_25_audit`` note — it is a
counting-method difference, not a different file, and both are emphatically
non-zero). Feeding those PDFs to extraction
would let the extractor read the printed question text without using vision
at all. That measures nothing, it would produce a figure that overstates real
performance, and it is not comparable with the synthetic corpus, which is
rasterised and carries **0** text characters.

**Why 150 DPI A4, and not a number picked for looking nice.** The synthetic
corpus is rendered by :func:`lemely.accuracy.synth.render_handwritten_scan`
at ``page_size=(1240, 1754)`` and ``resolution=150.0`` — 1240x1754 px at
150 DPI is exactly A4 (8.27in x 11.69in). Matching it is what makes the two
arms of #59 comparable; a different render scale would put a resolution
difference inside a measurement whose entire purpose is to isolate
handwriting.

**Output is NOT committed, deliberately.** The rendered pages are verbatim
CAIE question-paper content. MISSION 12.7 makes publishing real-paper content
a human decision, and the human's 2026-08-25 authorisation to commit the
parsed mark schemes said in terms that it was "NOT blanket permission to
commit real-paper content in future". So this script writes to a path outside
the repo and commits only itself plus the manifest, which records the input
and output digests so the render is reproducible and auditable without the
pixels being published.

Usage::

    .venv/bin/python scripts/rasterise_handwritten_fixtures.py \\
        --source-dir /home/sico/Downloads \\
        --out-dir /home/sico/lemely-fixtures/handwritten-59
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import pypdfium2 as pdfium

# Matches lemely/accuracy/synth.py:133 (page_size) and :159 (resolution).
# A4 at 150 DPI. Do not change one without changing the synthetic renderer,
# or the two arms of #59 stop being comparable.
TARGET_DPI = 150.0
A4_PX = (1240, 1754)

# The three files the human supplied. All are Paper 42 = Paper 4 Theory
# (Extended), so this corpus has no MCQ coverage and no paper-type diversity
# (limit 1 on #59).
SOURCES = (
    "0625_s25_qp_42.pdf",
    "0625_w24_qp_42.pdf",
    "0625_w25_qp_42.pdf",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_char_count(path: Path) -> int:
    """Total extractable text characters across every page.

    The acceptance check for this whole script: it must be non-zero on the
    input and **zero** on the output. A non-zero output means the flattening
    silently did not happen and the extractor would read printed question
    text instead of seeing it.
    """
    pdf = pdfium.PdfDocument(str(path))
    try:
        return sum(len(page.get_textpage().get_text_range()) for page in pdf)
    finally:
        pdf.close()


def rasterise(source: Path, out_pdf: Path) -> dict[str, object]:
    """Render every page of *source* to a pixel image and save as a PDF."""
    pdf = pdfium.PdfDocument(str(source))
    try:
        # pypdfium2's scale is in units of 72dpi-points, so 150/72 renders at
        # 150 DPI for a page declared in points.
        scale = TARGET_DPI / 72.0
        images = [page.render(scale=scale).to_pil().convert("RGB") for page in pdf]
        page_count = len(images)
    finally:
        pdf.close()

    if not images:
        raise ValueError(f"{source} produced no pages")

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    # Pillow otherwise embeds the current wall-clock time and a /Title derived
    # from the output filename, so two renders of the same input produce
    # different bytes. That was measured, not assumed: before pinning these,
    # two consecutive runs gave three different output_sha256 values, which
    # would have made the digest recorded in the manifest a false claim of
    # reproducibility. Pinned exactly as lemely/accuracy/synth.py:150-162 does
    # for the synthetic renderer, and for the same reason.
    images[0].save(
        out_pdf,
        "PDF",
        save_all=True,
        append_images=images[1:],
        resolution=TARGET_DPI,
        title="lemely-handwritten-fixture",
        creationDate=time.gmtime(0),
        modDate=time.gmtime(0),
    )

    return {
        "source": source.name,
        "source_sha256": _sha256(source),
        "source_text_chars": _text_char_count(source),
        "pages": page_count,
        "page_pixel_sizes": sorted({f"{im.width}x{im.height}" for im in images}),
        "output": out_pdf.name,
        "output_sha256": _sha256(out_pdf),
        "output_text_chars": _text_char_count(out_pdf),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("BUILD/accuracy-runs/handwritten-59/raster-manifest.json"),
        help="Written into the repo; records settings and digests, never pixels.",
    )
    args = parser.parse_args()

    entries: list[dict[str, object]] = []
    for name in SOURCES:
        source = args.source_dir / name
        if not source.is_file():
            raise SystemExit(f"missing source: {source}")
        entry = rasterise(source, args.out_dir / name)
        if entry["output_text_chars"] != 0:
            raise SystemExit(
                f"FLATTENING FAILED for {name}: output still carries "
                f"{entry['output_text_chars']} text characters. Extraction would "
                "read the printed question text instead of seeing it."
            )
        entries.append(entry)
        print(
            f"{name}: {entry['pages']}pp  "
            f"text {entry['source_text_chars']} -> {entry['output_text_chars']}  "
            f"{entry['page_pixel_sizes']}"
        )

    manifest = {
        "issue": 59,
        "purpose": (
            "Rasterisation settings for the real-handwriting fixtures (#59 DECISION 1). "
            "The three source PDFs are the original CAIE question papers with vector "
            "stylus ink on top and INTACT TEXT LAYERS; extraction must never see them "
            "unflattened, or it would read the printed question text without vision."
        ),
        "settings": {
            "dpi": TARGET_DPI,
            "colour_mode": "RGB",
            "target_page_px_a4": f"{A4_PX[0]}x{A4_PX[1]}",
            "renderer": "pypdfium2 PdfPage.render(scale=dpi/72)",
            "why_these_settings": (
                "Matches lemely/accuracy/synth.py:133 page_size=(1240,1754) and :159 "
                "resolution=150.0 — A4 at 150 DPI. The synthetic arm and the handwriting "
                "arm must render at the same scale or a resolution difference sits inside "
                "a measurement whose whole purpose is to isolate handwriting."
            ),
            "observed_vs_target_width": (
                "Rendered pages are 1241x1754, not the synthetic renderer's 1240x1754. A4 is "
                "595.276pt wide and 595.276 * 150/72 = 1240.16, which pypdfium2 rounds UP. "
                "The difference is ONE pixel of width (0.08%) and is recorded rather than "
                "described as an exact match — it is far below any plausible effect on "
                "extraction, but the claim 'identical geometry' would have been false."
            ),
        },
        "reproducibility": (
            "Byte-deterministic: PDF /Title, /CreationDate and /ModDate are pinned, so a "
            "re-render of the same input reproduces output_sha256 exactly. This was MEASURED "
            "rather than assumed — before pinning them, two consecutive runs produced three "
            "different digests, which would have made every output_sha256 below a false claim."
        ),
        "acceptance_check": (
            "source_text_chars must be non-zero and output_text_chars must be 0 for every "
            "file. The script exits non-zero otherwise rather than writing a fixture that "
            "would silently measure nothing."
        ),
        "text_char_counts_differ_from_the_2026_08_25_audit": (
            "The human's audit recorded 34,090 / 32,961 / 32,259 characters for s25 / w24 / "
            "w25; this script counts 23,727 / 24,754 / 22,961 via pypdfium2 "
            "get_textpage().get_text_range(). The gap is a counting-method difference "
            "(whitespace and layout-reconstruction handling differ between extractors), not "
            "a different file — the SHA256 of each input is recorded above, so which bytes "
            "were rendered is not in doubt. Noted rather than silently adopting whichever "
            "number is convenient; the finding that matters is direction, non-zero -> zero, "
            "and every extractor agrees on that."
        ),
        "outputs_not_committed": (
            "The rendered pages are verbatim CAIE question-paper content. MISSION 12.7 makes "
            "publishing real-paper content a human decision, and the 2026-08-25 authorisation "
            "to commit the parsed mark schemes stated it was NOT blanket permission for future "
            "real-paper content. Only these digests are committed, which is enough to verify a "
            "re-render reproduces the same bytes."
        ),
        "files": entries,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nmanifest -> {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
