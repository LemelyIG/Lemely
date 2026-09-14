"""Contrast guarantees for the Study Notebook design tokens (DESIGN.md §3).

Why this test exists in a Python repo whose UI is TypeScript: the token values
are *design decisions recorded in DESIGN.md*, and the thing worth protecting is
the arithmetic, not the CSS. The build-era system shipped an accessibility
failure on its lightest text token three separate times, each round fixing the
contrast against one surface and leaving it broken against another. Every fix
was applied by hand and verified by hand, so every fix was one distraction away
from being wrong.

These tests encode the claims DESIGN.md makes, so if someone nudges a token to
make a design look nicer, the failure is a red test naming the exact pair and
the exact ratio, rather than an axe finding on a screenshot three phases later.

Ratios are WCAG 2.x relative luminance. The AA floor is 4.5:1 for normal text
and 3.0:1 for large text (>=18.66px, or >=14px bold) and for UI components.

Phase C task C5a extends every guarantee below to a second ladder: the dark
theme, shipped as `:root[data-theme="dark"]` in `index.css` (a token swap, no
component changes). `THEMES` holds both palettes; parametrised tests run
against both so a guarantee the light ladder makes is proven for the dark one
by the same test body, not a hand-duplicated copy that can drift.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

INDEX_CSS = Path(__file__).resolve().parents[1] / "web" / "src" / "index.css"

# ── Colour maths ────────────────────────────────────────────────────────────


def oklch_to_srgb(lightness: float, chroma: float, hue_deg: float) -> tuple[float, float, float]:
    """Convert OKLCH to gamma-encoded sRGB in 0..1, clipping out-of-gamut."""
    hue = math.radians(hue_deg)
    a, b = chroma * math.cos(hue), chroma * math.sin(hue)
    # Long / medium / short cone responses, cubed back out of OKLab's cube root.
    # Named `cone_*` rather than the l/m/s of the reference formula because a
    # bare `l` is an ambiguous identifier (ruff E741).
    cone_l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    cone_m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    cone_s = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    linear = (
        4.0767416621 * cone_l - 3.3077115913 * cone_m + 0.2309699292 * cone_s,
        -1.2684380046 * cone_l + 2.6097574011 * cone_m - 0.3413193965 * cone_s,
        -0.0041960863 * cone_l - 0.7034186147 * cone_m + 1.7076147010 * cone_s,
    )

    def encode(value: float) -> float:
        value = max(0.0, min(1.0, value))
        return 1.055 * value ** (1 / 2.4) - 0.055 if value > 0.0031308 else 12.92 * value

    return tuple(encode(v) for v in linear)  # type: ignore[return-value]


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    def linearize(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    r, g, b = (linearize(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    a, b = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# ── The tokens, transcribed from DESIGN.md §3 ───────────────────────────────

LIGHT_TOKENS: dict[str, tuple[float, float, float]] = {
    # §3.1 paper
    "paper": (0.976, 0.004, 85),
    "paper-raised": (0.992, 0.003, 85),
    "paper-sunk": (0.952, 0.006, 85),
    "paper-inverse": (0.28, 0.008, 250),
    # §3.2 ink
    "ink": (0.321, 0.009, 234),
    "ink-muted": (0.48, 0.006, 240),
    "ink-faint": (0.52, 0.006, 240),  # D6.7: was 0.529, floored by tints not paper
    "ink-inverse": (0.97, 0.004, 85),
    # §3.4 accent
    "accent": (0.576, 0.146, 33),
    "accent-hover": (0.505, 0.132, 34),
    "accent-wash": (0.945, 0.028, 34),
    "accent-ink": (0.38, 0.10, 34),
    # §3.9 focus
    "focus-ring": (0.50, 0.14, 240),
    # §3.5 pastels
    "pastel-rose": (0.94, 0.032, 20),
    "pastel-rose-ink": (0.42, 0.11, 20),
    "pastel-amber": (0.945, 0.045, 85),
    "pastel-amber-ink": (0.42, 0.08, 70),
    "pastel-sage": (0.94, 0.032, 155),
    "pastel-sage-ink": (0.40, 0.07, 160),
    "pastel-sky": (0.94, 0.030, 235),
    "pastel-sky-ink": (0.42, 0.08, 240),
    "pastel-lilac": (0.94, 0.030, 300),
    "pastel-lilac-ink": (0.42, 0.08, 300),
    "pastel-clay": (0.94, 0.022, 55),
    "pastel-clay-ink": (0.42, 0.06, 50),
    # §3.6 semantic
    "ok": (0.48, 0.075, 175),
    "ok-wash": (0.945, 0.030, 175),
    "warn": (0.45, 0.085, 70),
    "warn-wash": (0.945, 0.045, 85),
    "err": (0.38, 0.145, 27),
    "err-wash": (0.94, 0.035, 27),
    "info": (0.44, 0.080, 265),
    "info-wash": (0.94, 0.030, 265),
}

# Task C5a (DESIGN.md §3.10). Hue and chroma are kept from LIGHT_TOKENS for
# every token except `--accent*` (chroma nudged down, see index.css) and
# `--ok`/`--warn` (lightness nudged below the 0.78-0.82 starting band so the
# §3.6 ladder's step size survives greyscale — see
# `test_state_colours_form_a_monotonic_lightness_ladder`). Values here must
# match `web/src/index.css`'s `:root[data-theme="dark"]` block exactly;
# `test_transcribed_token_matches_the_css_the_product_ships` is the guard.
DARK_TOKENS: dict[str, tuple[float, float, float]] = {
    # §3.1 paper
    "paper": (0.20, 0.004, 85),
    "paper-raised": (0.24, 0.003, 85),
    "paper-sunk": (0.17, 0.006, 85),
    "paper-inverse": (0.92, 0.008, 250),
    # §3.2 ink
    "ink": (0.93, 0.009, 234),
    "ink-muted": (0.78, 0.006, 240),
    "ink-faint": (0.72, 0.006, 240),
    "ink-inverse": (0.25, 0.004, 85),
    # §3.4 accent
    "accent": (0.72, 0.13, 33),
    "accent-hover": (0.78, 0.13, 34),
    "accent-wash": (0.28, 0.05, 34),
    "accent-ink": (0.80, 0.10, 34),
    # §3.9 focus
    "focus-ring": (0.72, 0.14, 240),
    # §3.5 pastels
    "pastel-rose": (0.30, 0.032, 20),
    "pastel-rose-ink": (0.85, 0.11, 20),
    "pastel-amber": (0.30, 0.045, 85),
    "pastel-amber-ink": (0.85, 0.08, 70),
    "pastel-sage": (0.30, 0.032, 155),
    "pastel-sage-ink": (0.85, 0.07, 160),
    "pastel-sky": (0.30, 0.030, 235),
    "pastel-sky-ink": (0.85, 0.08, 240),
    "pastel-lilac": (0.30, 0.030, 300),
    "pastel-lilac-ink": (0.85, 0.08, 300),
    "pastel-clay": (0.30, 0.022, 55),
    "pastel-clay-ink": (0.85, 0.06, 50),
    # §3.6 semantic
    "ok": (0.74, 0.075, 175),
    "ok-wash": (0.28, 0.030, 175),
    "warn": (0.77, 0.085, 70),
    "warn-wash": (0.28, 0.045, 85),
    "err": (0.82, 0.145, 27),
    "err-wash": (0.27, 0.035, 27),
    "info": (0.80, 0.080, 265),
    "info-wash": (0.29, 0.030, 265),
}

THEMES: dict[str, dict[str, tuple[float, float, float]]] = {
    "light": LIGHT_TOKENS,
    "dark": DARK_TOKENS,
}

# The CSS selector each theme's literal-value tokens are declared under.
SELECTORS: dict[str, str] = {
    "light": ":root {",
    "dark": ':root[data-theme="dark"] {',
}

AA_NORMAL = 4.5
AA_LARGE = 3.0

# Every surface a text token is allowed to sit on. `paper-sunk` is the darkest
# and is the one the build-era system kept forgetting, which is exactly why it
# is listed explicitly rather than left implicit.
TEXT_SURFACES = ("paper", "paper-raised", "paper-sunk")


def ratio(theme: str, fg: str, bg: str) -> float:
    tokens = THEMES[theme]
    return contrast(oklch_to_srgb(*tokens[fg]), oklch_to_srgb(*tokens[bg]))


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("token", ["ink", "ink-muted", "ink-faint", "accent-ink"])
@pytest.mark.parametrize("surface", TEXT_SURFACES)
def test_text_tokens_clear_aa_on_every_surface_they_may_sit_on(
    theme: str, token: str, surface: str
) -> None:
    """The rule the build-era system broke three times.

    A text token is not "accessible" against its best-case background. It has to
    clear AA against every surface it is allowed to appear on, and `paper-sunk`
    (sidebars, table headers, wells) is darker than the canvas — in EITHER
    theme, which is why this runs against both ladders.
    """
    assert ratio(theme, token, surface) >= AA_NORMAL, (
        f"[{theme}] --{token} on --{surface} is {ratio(theme, token, surface):.2f}:1, below the "
        f"{AA_NORMAL}:1 AA floor for normal text. Darken (light) or lighten (dark) the text "
        f"token; do not touch the surface and do not add another text step (DESIGN.md §3.2)."
    )


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_ink_faint_is_the_floor_and_has_real_margin_on_the_darkest_surface(theme: str) -> None:
    """Pins the specific value that a draft of DESIGN.md got wrong.

    At L 0.575 this measured 3.80:1 on paper-sunk and would have shipped a
    system-wide caption failure. It is set at L 0.529 for that reason (light);
    the dark ladder's `--ink-faint` is held to the same floor.
    """
    assert ratio(theme, "ink-faint", "paper-sunk") >= AA_NORMAL
    # And it must genuinely be the lightest-contrast text token, or the
    # hierarchy lies.
    for lighter in ("ink", "ink-muted", "accent-ink"):
        assert ratio(theme, lighter, "paper") > ratio(theme, "ink-faint", "paper"), (
            f"[{theme}] --{lighter} is more muted than --ink-faint, which is supposed to be "
            "the floor"
        )


def test_white_not_ink_inverse_is_used_on_accent_fills() -> None:
    """DESIGN.md §3.4's exception to the no-pure-white rule, and why it exists.

    Button labels are `label` (13px/500), i.e. normal text, so they need 4.5:1.
    Light-theme-specific: this is the historical bug this test was written to
    pin. The dark theme's equivalent decision is a different answer (below).
    """
    white = (1.0, 1.0, 1.0)
    accent = oklch_to_srgb(*LIGHT_TOKENS["accent"])
    assert contrast(white, accent) >= AA_NORMAL, "pure white must clear AA on the accent fill"
    assert contrast(oklch_to_srgb(*LIGHT_TOKENS["ink-inverse"]), accent) < AA_NORMAL, (
        "--ink-inverse now passes on --accent, so DESIGN.md's stated reason for "
        "permitting pure white there is stale. Re-check the token and the prose together."
    )


def test_accent_on_aliases_paper_in_dark_because_white_fails_aa() -> None:
    """DESIGN.md §3.4's dark-ladder rule for `--accent-on`.

    Pure white measures 2.61:1 on the dark `--accent` (fails AA), so
    `index.css` makes `--accent-on: var(--paper)` in the dark block instead of
    a second literal. This pins the measurement that decision is based on, so
    a future nudge to the dark accent's lightness/chroma has to re-check it.
    """
    white = (1.0, 1.0, 1.0)
    dark_accent = oklch_to_srgb(*DARK_TOKENS["accent"])
    assert contrast(white, dark_accent) < AA_NORMAL, (
        f"white now clears AA on the dark --accent ({contrast(white, dark_accent):.2f}:1). "
        "--accent-on could go back to a literal #ffffff; update index.css and this test together."
    )
    dark_paper = oklch_to_srgb(*DARK_TOKENS["paper"])
    assert contrast(dark_paper, dark_accent) >= AA_NORMAL, (
        f"the dark --paper is {contrast(dark_paper, dark_accent):.2f}:1 on the dark --accent, "
        "below AA — --accent-on's fallback in index.css (`var(--paper)`) no longer clears the bar."
    )


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_accent_clears_large_text_and_ui_component_contrast(theme: str) -> None:
    """--accent is for fills, marks and large text, not for body copy."""
    assert ratio(theme, "accent", "paper") >= AA_LARGE
    assert ratio(theme, "accent-ink", "paper") >= AA_NORMAL


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("name", ["rose", "amber", "sage", "sky", "lilac", "clay"])
def test_every_pastel_pair_is_aa_on_its_own_fill_and_on_paper(theme: str, name: str) -> None:
    """A tag must be legible on its fill, and still legible if the fill is dropped."""
    assert ratio(theme, f"pastel-{name}-ink", f"pastel-{name}") >= AA_NORMAL
    assert ratio(theme, f"pastel-{name}-ink", "paper") >= AA_NORMAL


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("name", ["ok", "warn", "err", "info"])
def test_every_semantic_pair_is_aa_on_its_own_wash_and_on_paper(theme: str, name: str) -> None:
    assert ratio(theme, name, f"{name}-wash") >= AA_NORMAL
    assert ratio(theme, name, "paper") >= AA_NORMAL


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_focus_ring_is_visible_against_the_page(theme: str) -> None:
    """A focus ring is a UI component: 3:1. It clears the stricter bar anyway."""
    assert ratio(theme, "focus-ring", "paper") >= AA_NORMAL


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_inverse_text_is_legible_on_the_one_permitted_inverse_surface(theme: str) -> None:
    """`--ink-inverse` on `--paper-inverse`.

    In light theme, `--paper-inverse` is the one deliberately dark surface in
    an otherwise light system. In the dark theme it flips: `--paper-inverse`
    is the one deliberately LIGHT surface. Either way it is a single
    intentional exception, and the text token paired with it must clear AA.
    """
    assert ratio(theme, "ink-inverse", "paper-inverse") >= AA_NORMAL


@pytest.mark.parametrize(
    ("theme", "expect_ascending"),
    [("light", False), ("dark", True)],
)
def test_state_colours_form_a_monotonic_lightness_ladder(
    theme: str, expect_ascending: bool
) -> None:
    """DESIGN.md §3.6's greyscale guarantee, in both directions.

    Teal-instead-of-green protects the red/green colour-blind case, but it does
    nothing for a reader who gets no hue at all. The structural guarantee is
    that ok, warn and err form a monotonic luminance ladder, so the three
    states stay distinguishable with hue removed entirely.

    Light DESCENDS: ok > warn > err (darkest text reads loudest on white
    paper). Dark ASCENDS: ok < warn < err (brightest text reads loudest on
    near-black paper) — the theme swap keeps the same *steps*, not the same
    *direction*, which is why this is parametrized rather than one assertion.

    A draft set all three at roughly the same lightness in light mode. They
    measured as three near-identical greys, which made the teal decision
    pointless. This test is what caught that, in both ladders.
    """
    tokens = THEMES[theme]
    ok_l = relative_luminance(oklch_to_srgb(*tokens["ok"]))
    warn_l = relative_luminance(oklch_to_srgb(*tokens["warn"]))
    err_l = relative_luminance(oklch_to_srgb(*tokens["err"]))

    if expect_ascending:
        assert ok_l < warn_l < err_l, (
            f"[{theme}] the state ladder is not ascending: ok={ok_l:.4f} warn={warn_l:.4f} "
            f"err={err_l:.4f}. The dark ladder is supposed to ASCEND with severity "
            "(ok < warn < err) — the mirror image of the light ladder's descent."
        )
        gap = min(warn_l - ok_l, err_l - warn_l)
    else:
        assert ok_l > warn_l > err_l, (
            f"[{theme}] the state ladder is not descending: ok={ok_l:.4f} warn={warn_l:.4f} "
            f"err={err_l:.4f}. DESIGN.md §3.6 promises the light ladder DESCENDS with severity "
            "(ok > warn > err)."
        )
        gap = min(ok_l - warn_l, warn_l - err_l)

    # A gap too small to see is the same as no gap. 0.02 in relative luminance
    # is roughly the smallest step that survives greyscale conversion legibly.
    assert gap >= 0.02, (
        f"[{theme}] the state ladder is monotonic but the steps are too small to perceive "
        "in greyscale"
    )


# ── The ink x tinted-fill matrix (P6.4 part 2, D6.6 option A) ───────────────
#
# Everything above this line measures text against `TEXT_SURFACES`, i.e. the
# three paper rungs. That is what "this project's contrast authority" has
# actually been asserting since Phase 2: ink on *paper*. The product also paints
# text on eleven tinted fills — the pastels, the four semantic washes, and
# `--accent-wash` — and until now not one of those pairings had ever been
# measured here.
#
# The hole was not theoretical. P6.4 part 1 found `--ink-faint` on
# `--accent-wash` at 4.47:1 on the leaderboard's viewer row, and found it via
# axe on a rendered page, because axe sees what a route happens to render and
# this file was not looking. Deriving the whole matrix showed that instance was
# not special: at L 0.529 `--ink-faint` was below 4.5 on **eight of the eleven**
# tinted fills and cleared the other three by 0.01-0.06. It was not a bad
# pairing on one surface, it was a token that cleared paper and missed every
# tint.
#
# D6.7 (proposed here, accepted by the human 2026-08-14) took it to L 0.52,
# which clears 4.5 on all fourteen surfaces — worst `--err-wash` at 4.53 — and
# keeps the three-rung ink hierarchy (11.77 / 6.09 / 5.13 on paper). The token
# is therefore floored by the worst TINT now, not by the worst paper rung, and
# `ink-faint` joins the other three in the matrix below rather than sitting in
# a split of passing and xfailing lists.
#
# Task C5a extends the whole matrix to the dark ladder, where `--ink-faint`'s
# binding constraint turns out to be `--pastel-sage` rather than `--err-wash`
# (see `test_binding_constraint_on_ink_faint` below).

TINTED_SURFACES = (
    "accent-wash",
    "pastel-rose",
    "pastel-amber",
    "pastel-sage",
    "pastel-sky",
    "pastel-lilac",
    "pastel-clay",
    "ok-wash",
    "warn-wash",
    "err-wash",
    "info-wash",
)


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("token", ["ink", "ink-muted", "ink-faint", "accent-ink"])
@pytest.mark.parametrize("surface", TINTED_SURFACES)
def test_ink_tokens_clear_aa_on_every_tinted_fill(theme: str, token: str, surface: str) -> None:
    """The same rule as on paper, extended to the fills the product actually paints."""
    assert ratio(theme, token, surface) >= AA_NORMAL, (
        f"[{theme}] --{token} on --{surface} is {ratio(theme, token, surface):.2f}:1, "
        f"below {AA_NORMAL}:1."
    )


# `--ink-faint` is the token D6.7 moved, and the tint it is closest to failing
# on is the one that decides its value. Pinned by name so that a later nudge to
# either colour reports WHICH pair went under rather than one of eleven
# parametrised cases going red with no indication that this specific pair is
# the binding constraint on the whole token. The binding surface differs by
# theme (light: `--err-wash`; dark: `--pastel-sage`), which is exactly why it
# is named explicitly per theme rather than assumed to carry over.
@pytest.mark.parametrize(
    ("theme", "binding_surface"),
    [("light", "err-wash"), ("dark", "pastel-sage")],
)
def test_binding_constraint_on_ink_faint(theme: str, binding_surface: str) -> None:
    """The floor under `--ink-faint`, per theme. Everything else has more room than this."""
    tightest = min(ratio(theme, "ink-faint", s) for s in TINTED_SURFACES)
    actual_binding = min(TINTED_SURFACES, key=lambda s: ratio(theme, "ink-faint", s))
    assert actual_binding == binding_surface, (
        f"[{theme}] the tightest ink-faint pairing is now --{actual_binding}, "
        f"not --{binding_surface}. The token's value was derived against a constraint "
        "that has moved — re-derive it, or update this test's expected binding surface "
        "to match the new evidence."
    )
    assert tightest >= AA_NORMAL, (
        f"[{theme}] --ink-faint's tightest pairing ({binding_surface}) is {tightest:.2f}:1"
    )


# ── The transcription itself (P6.5, found while applying D6.7) ──────────────
#
# `LIGHT_TOKENS`/`DARK_TOKENS` above are transcribed BY HAND from DESIGN.md §3,
# and until now nothing checked either against `web/src/index.css`, which is
# what the product actually paints. So this file could measure one palette
# while the browser rendered another, and every ratio it asserts would still
# be green.
#
# That is not hypothetical: it happened during D6.7's own application. The
# token was changed in `index.css` first, the suite was re-run, and eight
# tests went red reporting the OLD value — the file that calls itself this
# project's contrast authority was still measuring 0.529 because the edit had
# not been mirrored here. The failure was loud in that direction, which is
# luck. The opposite edit order is silent: nudge a colour in `index.css`
# alone, and this file happily proves AA about a value nothing renders.
#
# Parsed rather than transcribed a third time, so the check cannot itself
# drift. Task C5a: the parser is now selector-scoped rather than "everything
# after the first `:root {`", because the file now has a second block
# (`:root[data-theme="dark"]`) with property names that collide with the
# first — an unscoped regex would let the dark block's values silently
# overwrite the light ones (or vice versa) in the parsed dict.


def css_root_tokens(selector: str) -> dict[str, tuple[float, float, float]]:
    """Every three-component `oklch()` custom property declared directly inside `selector`'s block.

    Bounded to the block's own braces (brace-depth matching, not "to the next
    `}`") so a selector whose block happens to contain a nested rule would
    still be parsed correctly. Neither current block does, but the guard is
    cheap and this function is the project's one source of truth for "what
    does the CSS actually say", so it should not be the thing that's wrong.
    """
    text = INDEX_CSS.read_text(encoding="utf-8")
    start = text.index(selector)
    body_start = text.index("{", start) + 1
    depth = 1
    i = body_start
    while depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    block = text[body_start : i - 1]
    return {
        name: (float(lightness), float(chroma), float(hue))
        for name, lightness, chroma, hue in re.findall(
            r"--([a-z0-9-]+):\s*oklch\(\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\)\s*;", block
        )
    }


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_the_css_actually_declares_the_tokens_this_file_measures(theme: str) -> None:
    """A guard on the parser, so an empty match set cannot pass everything below."""
    parsed = css_root_tokens(SELECTORS[theme])
    tokens = THEMES[theme]
    assert len(parsed) >= len(tokens), (
        f"[{theme}] parsed only {len(parsed)} oklch tokens out of {INDEX_CSS.name} but this file "
        f"measures {len(tokens)}. The regex has stopped matching the way the tokens are "
        "written — fix the parser, do not narrow the assertions below it."
    )


def test_dark_ladder_declares_the_same_token_set_as_light() -> None:
    """The dark block is a token swap, not a partial one.

    Every literal-value colour token the light `:root` block declares
    (paper/ink/rule/accent/pastel/semantic/focus-ring — the aliases like
    `--grade-*` and `--mark-*` are `var()` references and never match the
    oklch() regex in either block, so they are already excluded on both
    sides) must reappear in the dark block. A name present in one ladder and
    missing from the other means some surface silently keeps its light-mode
    colour when `data-theme="dark"` is set.
    """
    light_names = set(css_root_tokens(SELECTORS["light"]))
    dark_names = set(css_root_tokens(SELECTORS["dark"]))
    missing_from_dark = light_names - dark_names
    extra_in_dark = dark_names - light_names
    assert not missing_from_dark, (
        f"declared in light but not redefined in dark: {sorted(missing_from_dark)}"
    )
    assert not extra_in_dark, f"declared in dark but not present in light: {sorted(extra_in_dark)}"


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("token", sorted(LIGHT_TOKENS))
def test_transcribed_token_matches_the_css_the_product_ships(theme: str, token: str) -> None:
    """DESIGN.md's value and the implementation's value are the same value, in both ladders."""
    parsed = css_root_tokens(SELECTORS[theme])
    tokens = THEMES[theme]
    assert token in parsed, (
        f"[{theme}] --{token} is measured here but is not declared as an oklch() triple under "
        f"{SELECTORS[theme]!r} in {INDEX_CSS.name}. Either the token was renamed or removed and "
        "this file was not updated, or it is now defined by reference and cannot be checked."
    )
    expected, actual = tokens[token], parsed[token]
    assert tuple(round(v, 6) for v in actual) == tuple(round(v, 6) for v in expected), (
        f"[{theme}] --{token} is oklch{actual} in {INDEX_CSS.name} but oklch{expected} here. "
        "Every ratio this file asserts about that token is therefore about a colour "
        "the product does not paint. Change both, or neither."
    )
