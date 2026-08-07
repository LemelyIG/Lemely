"""Adobe SymbolEncoding glyph recovery, shared by the det parsers.

CAIE PDFs embed a "Symbol" subset font for Greek letters and a handful of
maths operators. Both det parsers hit it — the mark-scheme table extractor
(:mod:`lemely.io.det.tables`) and the question-paper stem extractor
(:mod:`lemely.io.det.question_papers`) — so the table and the conversion
live here rather than being duplicated or imported sideways.
"""

from __future__ import annotations

# CAIE PDFs embed a "Symbol" subset font for Greek letters and a handful of
# math operators. pdfplumber/PyPDF surface each glyph as whatever codepoint
# the PDF's (missing or trivial) ToUnicode CMap gives it — for these fonts
# that is consistently 0xF000 + <SymbolEncoding byte>, landing squarely in
# the Unicode Private Use Area (verified against every PUA codepoint found
# across a 30-file 0625 corpus scan: every one decoded cleanly to
# `0xF0xx`). ``SYMBOL_FONT_MAP`` is keyed by that low byte, using Adobe's
# own SymbolEncoding vector (PostScript LRM Appendix E) — a stable, publicly
# documented 40-year-old table, not a guess.
#
# Deliberately partial. A handful of low-range codes look like they should
# be ASCII punctuation but are officially something else in SymbolEncoding
# (0x22 "universal" ∀, 0x24 "existential" ∃, 0x27 "suchthat" ∋, 0x40
# "congruent" ≅) — those are left OUT rather than guessed, and the large
# 0xE0–0xFF range of glyph-assembly pieces (parenthesis/bracket/brace/
# integral fragments used to draw multi-line delimiters around a stacked
# fraction) has no single-character Unicode equivalent at all and is also
# left out. Any PUA codepoint not in this table is, by construction,
# something this module is not confident about — see ``desymbolize``.
SYMBOL_FONT_MAP: dict[int, str] = {
    # Greek uppercase
    0x41: "Α",
    0x42: "Β",
    0x43: "Χ",
    0x44: "Δ",
    0x45: "Ε",
    0x46: "Φ",
    0x47: "Γ",
    0x48: "Η",
    0x49: "Ι",
    0x4B: "Κ",
    0x4C: "Λ",
    0x4D: "Μ",
    0x4E: "Ν",
    0x4F: "Ο",
    0x50: "Π",
    0x51: "Θ",
    0x52: "Ρ",
    0x53: "Σ",
    0x54: "Τ",
    0x55: "Υ",
    0x57: "Ω",
    0x58: "Ξ",
    0x59: "Ψ",
    0x5A: "Ζ",
    # Greek lowercase
    0x61: "α",
    0x62: "β",
    0x63: "χ",
    0x64: "δ",
    0x65: "ε",
    0x66: "φ",
    0x67: "γ",
    0x68: "η",
    0x69: "ι",
    0x6B: "κ",
    0x6C: "λ",
    0x6D: "μ",
    0x6E: "ν",
    0x6F: "ο",
    0x70: "π",
    0x71: "θ",
    0x72: "ρ",
    0x73: "σ",
    0x74: "τ",
    0x75: "υ",
    0x77: "ω",
    0x78: "ξ",
    0x79: "ψ",
    0x7A: "ζ",
    # ASCII-identical punctuation/digits (SymbolEncoding, verified positions only)
    0x20: " ",
    0x21: "!",
    0x23: "#",
    0x25: "%",
    0x26: "&",
    0x28: "(",
    0x29: ")",
    0x2B: "+",
    0x2C: ",",
    0x2D: "-",
    0x2E: ".",
    0x2F: "/",
    0x30: "0",
    0x31: "1",
    0x32: "2",
    0x33: "3",
    0x34: "4",
    0x35: "5",
    0x36: "6",
    0x37: "7",
    0x38: "8",
    0x39: "9",
    0x3A: ":",
    0x3B: ";",
    0x3C: "<",
    0x3D: "=",
    0x3E: ">",
    0x3F: "?",
    # Well-known math/arrow operators (SymbolEncoding upper range)
    0xA3: "≤",
    0xA5: "∞",
    0xAB: "↔",
    0xAC: "←",
    0xAD: "↑",
    0xAE: "→",
    0xAF: "↓",
    0xB0: "°",
    0xB1: "±",
    0xB3: "≥",
    0xB4: "×",
    0xB5: "∝",
    0xB6: "∂",
    0xB7: "•",
    0xB8: "÷",
    0xB9: "≠",
    0xBA: "≡",
    0xBB: "≈",
    0xBC: "…",
    # Delimiters. SymbolEncoding names these bracketleft/bracketright/
    # braceleft/braceright/bar at exactly their ASCII positions, so the
    # mapping is an identity, not a guess. Added after a corpus scan found
    # 0xF07B/0xF07D (brace pairs, used around grouped marking points) as the
    # only unmappable glyphs left in the whole 0625 mark-point corpus.
    0x5B: "[",
    0x5D: "]",
    0x7B: "{",
    0x7C: "|",
    0x7D: "}",
}


def desymbolize(text: str) -> tuple[str, bool]:
    """String-level Symbol-glyph substitution (no char position data needed).

    Used by :mod:`lemely.io.det.tables` on every extracted mark-scheme cell,
    and by :mod:`lemely.io.det.question_papers` as the fallback when no
    ``page.chars`` fall in a line's band and as the base case inside its
    per-character line reconstruction. Returns ``(converted_text,
    had_unmapped_glyph)`` — a raw, unmapped PUA glyph is dropped from the
    text entirely (never emitted) and flagged so the caller excludes the
    leaf, per the module docstring.
    """
    out: list[str] = []
    unmapped = False
    for ch in text:
        cp = ord(ch)
        if 0xE000 <= cp <= 0xF8FF:
            mapped = SYMBOL_FONT_MAP.get(cp - 0xF000) if 0xF000 <= cp <= 0xF0FF else None
            if mapped is not None:
                out.append(mapped)
            else:
                unmapped = True
        else:
            out.append(ch)
    return "".join(out), unmapped
