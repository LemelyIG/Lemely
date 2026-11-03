"""Contrast and parity checks for the v5 Abyss token layer.

``DESIGN.md`` frontmatter is the source of truth. ``web/src/index.css`` must declare
the same values, and every text role must clear WCAG AA (4.5:1) on every surface it
may sit on, in both themes.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "DESIGN.md"
INDEX_CSS = ROOT / "web" / "src" / "index.css"


def _frontmatter() -> dict[str, str]:
    text = DESIGN.read_text()
    colors: dict[str, str] = yaml.safe_load(text.split("---")[1])["colors"]
    return colors


def _css_block(selector: str) -> dict[str, str]:
    css = INDEX_CSS.read_text()
    match = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", css, re.S)
    assert match, f"{selector} block missing from index.css"
    return dict(re.findall(r"--md-([a-z0-9-]+):\s*([^;]+);", match.group(1)))


def _to_linear_rgb(value: str) -> tuple[float, float, float]:
    value = value.strip()
    if value.startswith("#"):
        h = value[1:]
        rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)  # type: ignore[return-value]
    m = re.match(r"oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)", value)
    assert m, f"unparseable colour {value}"
    lightness, chroma, hue = (float(x) for x in m.groups())
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bl = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    return tuple(min(1.0, max(0.0, c)) for c in (r, g, bl))  # type: ignore[return-value]


def _contrast(fg: str, bg: str) -> float:
    def lum(c: str) -> float:
        r, g, b = _to_linear_rgb(c)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


SURFACES = [
    "surface",
    "surface-container-lowest",
    "surface-container-low",
    "surface-container",
    "surface-container-high",
    "surface-container-highest",
]
TEXT_ON_SURFACES = ["on-surface", "on-surface-variant", "primary", "error", "success-text"]
PAIRS = [
    ("on-primary", "primary"),
    ("on-primary-container", "primary-container"),
    ("on-secondary-container", "secondary-container"),
    ("on-tertiary", "tertiary"),
    ("on-tertiary-container", "tertiary-container"),
    ("on-error-container", "error-container"),
    ("inverse-on-surface", "inverse-surface"),
]


def _scheme(theme: str) -> dict[str, str]:
    fm = _frontmatter()
    if theme == "light":
        return {k: v for k, v in fm.items() if not k.startswith("dark-")}
    return {k.removeprefix("dark-"): v for k, v in fm.items() if k.startswith("dark-")}


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("text", TEXT_ON_SURFACES)
@pytest.mark.parametrize("surface", SURFACES)
def test_text_roles_clear_aa_on_every_surface(theme: str, text: str, surface: str) -> None:
    s = _scheme(theme)
    ratio = _contrast(s[text], s[surface])
    assert ratio >= 4.5, f"{theme}: {text} on {surface} is {ratio:.2f}:1"


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize(("text", "fill"), PAIRS)
def test_on_roles_clear_aa_on_their_fill(theme: str, text: str, fill: str) -> None:
    s = _scheme(theme)
    ratio = _contrast(s[text], s[fill])
    assert ratio >= 4.5, f"{theme}: {text} on {fill} is {ratio:.2f}:1"


@pytest.mark.parametrize("grade", ["a-star", "a", "b", "c", "d", "e", "u"])
def test_white_grade_letters_clear_large_text_contrast(grade: str) -> None:
    fm = _frontmatter()
    assert _contrast(fm["white"], fm[f"grade-{grade}"]) >= 3.0


@pytest.mark.parametrize(
    ("theme", "selector"), [("light", ":root"), ("dark", ':root[data-theme="dark"]')]
)
def test_css_declares_the_design_md_values(theme: str, selector: str) -> None:
    declared = _css_block(selector)
    for role, value in _scheme(theme).items():
        if role in {
            "abyss",
            "abyss-hover",
            "abyss-lip",
            "tide",
            "tide-hover",
            "mist-blue",
            "night",
            "white",
            "gold",
            "crimson",
            "crimson-on-dark",
            "binny-steel",
            "binny-cheek",
        } or role.startswith("grade-"):
            continue
        assert declared.get(role, "").strip() == value, (
            f"{theme} --md-{role}: css {declared.get(role)!r} != DESIGN.md {value!r}"
        )
