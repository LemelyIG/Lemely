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
"""

from __future__ import annotations

import math

import pytest

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

TOKENS: dict[str, tuple[float, float, float]] = {
    # §3.1 paper
    "paper": (0.976, 0.004, 85),
    "paper-raised": (0.992, 0.003, 85),
    "paper-sunk": (0.952, 0.006, 85),
    "paper-inverse": (0.28, 0.008, 250),
    # §3.2 ink
    "ink": (0.321, 0.009, 234),
    "ink-muted": (0.48, 0.006, 240),
    "ink-faint": (0.529, 0.006, 240),
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
    "info": (0.44, 0.080, 240),
    "info-wash": (0.94, 0.030, 235),
}

AA_NORMAL = 4.5
AA_LARGE = 3.0

# Every surface a text token is allowed to sit on. `paper-sunk` is the darkest
# and is the one the build-era system kept forgetting, which is exactly why it
# is listed explicitly rather than left implicit.
TEXT_SURFACES = ("paper", "paper-raised", "paper-sunk")


def ratio(fg: str, bg: str) -> float:
    return contrast(oklch_to_srgb(*TOKENS[fg]), oklch_to_srgb(*TOKENS[bg]))


@pytest.mark.parametrize("token", ["ink", "ink-muted", "ink-faint", "accent-ink"])
@pytest.mark.parametrize("surface", TEXT_SURFACES)
def test_text_tokens_clear_aa_on_every_surface_they_may_sit_on(token: str, surface: str) -> None:
    """The rule the build-era system broke three times.

    A text token is not "accessible" against its best-case background. It has to
    clear AA against every surface it is allowed to appear on, and `paper-sunk`
    (sidebars, table headers, wells) is darker than the canvas.
    """
    assert ratio(token, surface) >= AA_NORMAL, (
        f"--{token} on --{surface} is {ratio(token, surface):.2f}:1, below the "
        f"{AA_NORMAL}:1 AA floor for normal text. Darken the text token; do not "
        f"lighten the surface and do not add a lighter text step (DESIGN.md §3.2)."
    )


def test_ink_faint_is_the_floor_and_has_real_margin_on_the_darkest_surface() -> None:
    """Pins the specific value that a draft of DESIGN.md got wrong.

    At L 0.575 this measured 3.80:1 on paper-sunk and would have shipped a
    system-wide caption failure. It is set at L 0.529 for that reason.
    """
    assert ratio("ink-faint", "paper-sunk") >= AA_NORMAL
    # And it must genuinely be the lightest text token, or the hierarchy lies.
    for lighter in ("ink", "ink-muted", "accent-ink"):
        assert ratio(lighter, "paper") > ratio("ink-faint", "paper"), (
            f"--{lighter} is more muted than --ink-faint, which is supposed to be the floor"
        )


def test_white_not_ink_inverse_is_used_on_accent_fills() -> None:
    """DESIGN.md §3.4's exception to the no-pure-white rule, and why it exists.

    Button labels are `label` (13px/500), i.e. normal text, so they need 4.5:1.
    """
    white = (1.0, 1.0, 1.0)
    accent = oklch_to_srgb(*TOKENS["accent"])
    assert contrast(white, accent) >= AA_NORMAL, "pure white must clear AA on the accent fill"
    assert contrast(oklch_to_srgb(*TOKENS["ink-inverse"]), accent) < AA_NORMAL, (
        "--ink-inverse now passes on --accent, so DESIGN.md's stated reason for "
        "permitting pure white there is stale. Re-check the token and the prose together."
    )


def test_accent_clears_large_text_and_ui_component_contrast() -> None:
    """--accent is for fills, marks and large text, not for body copy."""
    assert ratio("accent", "paper") >= AA_LARGE
    assert ratio("accent-ink", "paper") >= AA_NORMAL


@pytest.mark.parametrize("name", ["rose", "amber", "sage", "sky", "lilac", "clay"])
def test_every_pastel_pair_is_aa_on_its_own_fill_and_on_paper(name: str) -> None:
    """A tag must be legible on its fill, and still legible if the fill is dropped."""
    assert ratio(f"pastel-{name}-ink", f"pastel-{name}") >= AA_NORMAL
    assert ratio(f"pastel-{name}-ink", "paper") >= AA_NORMAL


@pytest.mark.parametrize("name", ["ok", "warn", "err", "info"])
def test_every_semantic_pair_is_aa_on_its_own_wash_and_on_paper(name: str) -> None:
    assert ratio(name, f"{name}-wash") >= AA_NORMAL
    assert ratio(name, "paper") >= AA_NORMAL


def test_focus_ring_is_visible_against_the_page() -> None:
    """A focus ring is a UI component: 3:1. It clears the stricter bar anyway."""
    assert ratio("focus-ring", "paper") >= AA_NORMAL


def test_inverse_text_is_legible_on_the_one_permitted_dark_surface() -> None:
    assert ratio("ink-inverse", "paper-inverse") >= AA_NORMAL


def test_state_colours_form_a_monotonic_lightness_ladder() -> None:
    """DESIGN.md §3.6's greyscale guarantee, which a draft of that file did not keep.

    Teal-instead-of-green protects the red/green colour-blind case, but it does
    nothing for a reader who gets no hue at all. The structural guarantee is
    that ok, warn and err descend in luminance, so the three states stay
    distinguishable with hue removed entirely.

    A draft set all three at roughly L 0.45. They measured as three near
    identical greys, which made the teal decision pointless. This test is what
    caught that.
    """
    ok_l = relative_luminance(oklch_to_srgb(*TOKENS["ok"]))
    warn_l = relative_luminance(oklch_to_srgb(*TOKENS["warn"]))
    err_l = relative_luminance(oklch_to_srgb(*TOKENS["err"]))

    assert ok_l > warn_l > err_l, (
        f"the state ladder is not monotonic: ok={ok_l:.4f} warn={warn_l:.4f} "
        f"err={err_l:.4f}. DESIGN.md §3.6 promises a descending lightness step."
    )
    # A gap too small to see is the same as no gap. 0.02 in relative luminance
    # is roughly the smallest step that survives greyscale conversion legibly.
    assert min(ok_l - warn_l, warn_l - err_l) >= 0.02, (
        "the state ladder is monotonic but the steps are too small to perceive in greyscale"
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
# this file was not looking. Deriving the whole matrix shows that instance was
# not special: `--ink-faint` is below 4.5 on **eight of the eleven** tinted
# fills, and clears the other three by 0.01-0.06. It is not a bad pairing on one
# surface, it is a token that clears paper and misses every tint.
#
# The three darker ink tokens are unaffected and are pinned here so the matrix
# is a real check rather than one xfail.

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


@pytest.mark.parametrize("token", ["ink", "ink-muted", "accent-ink"])
@pytest.mark.parametrize("surface", TINTED_SURFACES)
def test_ink_tokens_clear_aa_on_every_tinted_fill(token: str, surface: str) -> None:
    """The same rule as on paper, extended to the fills the product actually paints."""
    assert ratio(token, surface) >= AA_NORMAL, (
        f"--{token} on --{surface} is {ratio(token, surface):.2f}:1, below {AA_NORMAL}:1."
    )


# The split is the finding, so it is written down rather than parametrised over
# one list. `--ink-faint` clears AA on exactly three of the eleven tinted fills,
# and it clears those three by 0.01-0.06 — amber 4.51, warn-wash 4.51,
# ok-wash 4.56. There is no tint this token sits comfortably on; three of them
# happen to land on the right side of the line.
INK_FAINT_TINTS_PASSING = ("pastel-amber", "ok-wash", "warn-wash")
INK_FAINT_TINTS_FAILING = tuple(s for s in TINTED_SURFACES if s not in INK_FAINT_TINTS_PASSING)


@pytest.mark.parametrize("surface", INK_FAINT_TINTS_PASSING)
def test_ink_faint_clears_aa_on_the_three_tints_it_clears(surface: str) -> None:
    """Pinned so the margin cannot quietly erode. These pass by 0.01-0.06."""
    assert ratio("ink-faint", surface) >= AA_NORMAL


@pytest.mark.xfail(
    strict=True,
    reason=(
        "--ink-faint is below AA on 8 of the 11 tinted fills (worst: --err-wash at "
        "4.36:1). This is a token change on the caption colour, which has 334 call "
        "sites, so it is PROPOSED and not applied: see BUILD/DECISIONS.md D6.7. "
        "strict=True on purpose — when the token is changed these start passing and "
        "xfail(strict) then FAILS, so the proposal cannot be quietly forgotten, nor "
        "applied without this file being updated alongside it."
    ),
)
@pytest.mark.parametrize("surface", INK_FAINT_TINTS_FAILING)
def test_ink_faint_clears_aa_on_every_tinted_fill(surface: str) -> None:
    assert ratio("ink-faint", surface) >= AA_NORMAL
