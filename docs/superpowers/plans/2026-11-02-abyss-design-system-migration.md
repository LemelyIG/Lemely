# Abyss Design System Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every web screen from the retired "Study Notebook" tokens to the v5 "Abyss" Material 3 system in `DESIGN.md`, and ship the teacher home and teacher setup screens backed by real API data.

**Architecture:** One token layer (`web/src/index.css`) declares the `DESIGN.md` M3 roles as `--md-*` custom properties (light on `:root`, dark on `:root[data-theme="dark"]`) and exposes them as Tailwind utilities. A checked-in mapping table plus an idempotent codemod renames every retired utility across `web/src`; what the table cannot express is fixed by hand. The teacher home is split into small components whose display logic lives in pure, unit-tested view-model functions, fed by five new additive fields on `GET /api/teacher/overview`.

**Tech Stack:** React 19, React Router, TanStack Query, Tailwind CSS 4 (`@theme inline`), Vite 8, Vitest 4 (node environment, no jsdom), FastAPI + Pydantic, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-02-abyss-design-system-migration-design.md`

## Global Constraints

- Work only in the worktree `/home/sico/Code/Lemely/.claude/worktrees/teacher-home-variants` on branch `design/teacher-home-variants`. Never write to the main checkout.
- **Do not commit.** The project rule is "Do not create commits unless asked". Each task ends with a "Checkpoint" step (stage nothing, report the changed paths). If the user later asks for commits: `git commit -S`, conventional message, `pre-commit run --all-files` first.
- Never run the full Python suite locally (`make test` or bare `pytest`): run touched test files only. The web suite (`npx vitest run` in `web/`) is allowed; it is the CI web gate and runs in seconds.
- Colour values come only from `DESIGN.md` frontmatter. No raw hex/oklch in components.
- Fonts: display `Bricolage Grotesque Variable`, UI `Schibsted Grotesk Variable`, data `JetBrains Mono Variable`. Bricolage only at 28px and above.
- Confidence is always shown as a percentage (`64%`), never `0.64`.
- Crimson (`error`) only for lost marks, low confidence and genuine errors. Gold (`tertiary`) only for XP, streaks and medium confidence.
- No Binny on teacher, parent, school or admin surfaces.
- No em dashes in UI copy. Never say: cram, hack, easy A, guaranteed grade.
- Every animation is disabled under `prefers-reduced-motion: reduce`.
- No number is rendered that does not come from the API.
- Backend fields are additive with defaults, so older clients still deserialise.

## File Structure

| Path | Responsibility |
|---|---|
| `web/scripts/abyss-token-map.json` | The reviewed retired-to-M3 mapping table |
| `web/scripts/abyss-codemod.mjs` | Applies the table to `web/src` (idempotent, `--compat` phase once) |
| `web/tests/unit/abyssCodemod.test.ts` | Codemod behaviour |
| `web/src/index.css` | Token layer: M3 roles, custom colours, radii, fonts, motion, type scale |
| `web/src/portals/marketing/brand-tokens.css` | Reads `--md-*` roles, no own colour values |
| `tests/test_design_tokens.py` | AA contrast of the M3 text roles, light and dark |
| `web/tests/unit/design-tokens.test.ts` | CSS declares exactly the `DESIGN.md` token set |
| `web/tests/unit/retiredTokens.test.ts` | Fails on any retired name in `web/src` |
| `lemely/web/schemas_teacher.py` | `OverviewDTO` + `AtRiskStudentDTO` new fields |
| `lemely/web/routers/teacher.py` | Computes the new fields |
| `tests/test_web_teacher_overview_fields.py` | Pytest for the new fields |
| `web/src/lib/teacherTypes.ts` | Mirrors the new fields |
| `web/src/portals/teacher/home/setup.ts` | `deriveSetup()` pure function |
| `web/src/portals/teacher/home/models.ts` | Pure view models for each overview tile |
| `web/src/portals/teacher/home/ReviewQueueTile.tsx` | Review queue tile |
| `web/src/portals/teacher/home/MarkClassSet.tsx` | Drop zone + received animation |
| `web/src/portals/teacher/home/ClassStrip.tsx` | Class cards row |
| `web/src/portals/teacher/home/AtRiskTable.tsx` | At-risk link rows |
| `web/src/portals/teacher/home/TeacherSetup.tsx` | Setup (empty) state |
| `web/src/portals/teacher/home/TeacherHome.tsx` | Chooses setup vs overview |
| `web/src/portals/teacher/home/home.css` | Keyframes and reduced-motion rules for the home |
| `web/tests/unit/teacherSetup.test.ts` | `deriveSetup` truth table |
| `web/tests/unit/teacherHomeModels.test.ts` | Tile view models |

---

### Task 1: Mapping table and codemod

**Files:**
- Create: `web/scripts/abyss-token-map.json`
- Create: `web/scripts/abyss-codemod.mjs`
- Test: `web/tests/unit/abyssCodemod.test.ts`

**Interfaces:**
- Produces: `rewriteClasses(source: string, map: TokenMap, opts: { compat: boolean }): string` exported from `web/scripts/abyss-codemod.mjs`; CLI `node scripts/abyss-codemod.mjs [--compat] [--check]`. `--check` exits 1 if any file would change.
- `TokenMap` shape: `{ tokens: Record<string,string>, overrides: Record<string,string>, compat: Record<string,string> }`. `tokens` maps a token suffix for any colour prefix; `overrides` maps a full `prefix-token` pair and wins over `tokens`; `compat` is applied only with `--compat`.

- [ ] **Step 1: Write the mapping table**

`web/scripts/abyss-token-map.json`:

```json
{
  "prefixes": ["bg", "text", "border", "border-t", "border-b", "border-l", "border-r", "border-x", "border-y", "ring", "ring-offset", "outline", "fill", "stroke", "divide", "from", "via", "to", "decoration", "placeholder", "caret", "accent", "shadow"],
  "tokens": {
    "ink": "on-surface",
    "ink-muted": "on-surface-variant",
    "ink-faint": "on-surface-variant",
    "ink-hover": "on-surface",
    "ink-inverse": "inverse-on-surface",
    "paper": "surface",
    "paper-raised": "surface-container-lowest",
    "paper-sunk": "surface-container-low",
    "paper-inverse": "inverse-surface",
    "rule": "outline-variant",
    "rule-strong": "outline",
    "rule-faint": "outline-variant",
    "accent": "primary",
    "accent-hover": "primary-hover",
    "accent-wash": "primary-container",
    "accent-ink": "on-primary-container",
    "accent-on": "on-primary",
    "accent-subtle": "primary-container",
    "accent-subtle-on": "on-primary-container",
    "focus-ring": "primary",
    "ok": "success",
    "ok-wash": "success-container",
    "ok-bg": "success-container",
    "warn": "tertiary",
    "warn-wash": "tertiary-container",
    "warn-bg": "tertiary-container",
    "err": "error",
    "err-wash": "error-container",
    "err-bg": "error-container",
    "info": "primary",
    "info-wash": "primary-container",
    "confidence-high": "success",
    "confidence-high-bg": "success-container",
    "confidence-medium": "tertiary",
    "confidence-medium-bg": "tertiary-container",
    "confidence-low": "error",
    "confidence-low-bg": "error-container",
    "mark-correct": "success",
    "mark-correct-bg": "success-container",
    "mark-partial": "tertiary",
    "mark-partial-bg": "tertiary-container",
    "mark-wrong": "error",
    "mark-wrong-bg": "error-container",
    "secondary": "on-surface-variant"
  },
  "overrides": {
    "bg-ink": "bg-inverse-surface",
    "text-paper": "text-inverse-on-surface",
    "text-paper-raised": "text-inverse-on-surface",
    "text-warn": "text-on-tertiary-container",
    "text-ok": "text-success",
    "text-confidence-medium": "text-on-tertiary-container",
    "text-mark-partial": "text-on-tertiary-container"
  },
  "compat": {
    "surface": "surface-container-lowest",
    "surface-2": "surface-container-low",
    "bg": "surface",
    "border": "outline-variant",
    "t1": "on-surface",
    "t2": "on-surface-variant",
    "t3": "on-surface-variant"
  }
}
```

Why `compat` is separate: the retired compatibility names `surface` and `bg` collide with the new M3 `surface` role. They are rewritten once, in the first run, and never again, which keeps every later run idempotent.

`grade-*`, `pastel-*`, `subject-*` are deliberately absent. Those uses are fixed by hand in Task 4 because they need a per-use decision.

- [ ] **Step 2: Write the failing test**

`web/tests/unit/abyssCodemod.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
// @ts-expect-error: plain .mjs script without types
import { rewriteClasses } from "../../scripts/abyss-codemod.mjs"

const map = JSON.parse(readFileSync(join(__dirname, "../../scripts/abyss-token-map.json"), "utf8"))

describe("abyss codemod", () => {
  it("renames a token for any colour prefix", () => {
    expect(rewriteClasses(`className="text-ink bg-paper-raised border-rule"`, map, { compat: false }))
      .toBe(`className="text-on-surface bg-surface-container-lowest border-outline-variant"`)
  })

  it("keeps variant prefixes and opacity suffixes", () => {
    expect(rewriteClasses(`"hover:bg-accent-hover dark:text-ink-muted/70 md:border-t-rule"`, map, { compat: false }))
      .toBe(`"hover:bg-primary-hover dark:text-on-surface-variant/70 md:border-t-outline-variant"`)
  })

  it("prefers a full-pair override over the token rule", () => {
    expect(rewriteClasses(`"bg-ink text-paper"`, map, { compat: false })).toBe(`"bg-inverse-surface text-inverse-on-surface"`)
  })

  it("does not touch a longer token that merely starts with a mapped one", () => {
    expect(rewriteClasses(`"text-inkwell bg-paperish"`, map, { compat: false })).toBe(`"text-inkwell bg-paperish"`)
  })

  it("applies compat names only with compat on", () => {
    expect(rewriteClasses(`"bg-surface text-t2"`, map, { compat: false })).toBe(`"bg-surface text-t2"`)
    expect(rewriteClasses(`"bg-surface text-t2"`, map, { compat: true })).toBe(`"bg-surface-container-lowest text-on-surface-variant"`)
  })

  it("is idempotent without compat", () => {
    const once = rewriteClasses(`"text-ink-faint bg-err-wash ring-focus-ring"`, map, { compat: false })
    expect(rewriteClasses(once, map, { compat: false })).toBe(once)
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd web && npx vitest run tests/unit/abyssCodemod.test.ts`
Expected: FAIL, "Failed to load url ../../scripts/abyss-codemod.mjs".

- [ ] **Step 4: Write the codemod**

`web/scripts/abyss-codemod.mjs`:

```js
#!/usr/bin/env node
// Renames retired Study Notebook utilities to the v5 Abyss M3 roles.
// Table: scripts/abyss-token-map.json. Run once with --compat, then any number
// of times without it (idempotent). --check exits 1 when a file would change.
import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")

export function rewriteClasses(source, map, { compat }) {
  const tokens = { ...map.tokens, ...(compat ? map.compat : {}) }
  const prefixes = [...map.prefixes].sort((a, b) => b.length - a.length).map(escape).join("|")
  const names = Object.keys(tokens).sort((a, b) => b.length - a.length).map(escape).join("|")
  // variants (hover:, md:, dark:...), prefix, token, optional /opacity, then a hard boundary
  const re = new RegExp(`(?<![\\w-])((?:[\\w-]+:)*)(${prefixes})-(${names})(\\/\\d+)?(?![\\w-])`, "g")
  return source.replace(re, (whole, variants, prefix, token, opacity = "") => {
    const pair = `${prefix}-${token}`
    const replaced = map.overrides[pair] ?? `${prefix}-${tokens[token]}`
    return `${variants}${replaced}${opacity}`
  })
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(tsx|ts|css)$/.test(name) && name !== "index.css") out.push(p)
  }
  return out
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]
if (isMain) {
  const here = dirname(fileURLToPath(import.meta.url))
  const map = JSON.parse(readFileSync(join(here, "abyss-token-map.json"), "utf8"))
  const compat = process.argv.includes("--compat")
  const check = process.argv.includes("--check")
  let changed = 0
  for (const file of walk(join(here, "..", "src"))) {
    const before = readFileSync(file, "utf8")
    const after = rewriteClasses(before, map, { compat })
    if (after !== before) {
      changed++
      if (!check) writeFileSync(file, after)
      console.log(`${check ? "would change" : "changed"}: ${file}`)
    }
  }
  console.log(`${changed} file(s)`)
  if (check && changed) process.exit(1)
}
```

`index.css` is skipped on purpose: Task 2 rewrites it by hand.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd web && npx vitest run tests/unit/abyssCodemod.test.ts`
Expected: PASS, 6 tests.

- [ ] **Step 6: Checkpoint**

Report: `web/scripts/abyss-token-map.json`, `web/scripts/abyss-codemod.mjs`, `web/tests/unit/abyssCodemod.test.ts`. Do not commit.

---

### Task 2: Token layer

**Files:**
- Modify: `web/src/index.css` (lines 1-8 imports, 49-330 `:root` + dark block, 331-480 `@theme inline`, 597-690 compat block, 861-1080 type scale, 1080-1208 texture layer)
- Modify: `web/package.json` (font dependencies)
- Modify: `tests/test_design_tokens.py` (rewrite)
- Modify: `web/tests/unit/design-tokens.test.ts` (rewrite)

**Interfaces:**
- Produces CSS custom properties `--md-<role>` for every colour key in `DESIGN.md` frontmatter (light keys on `:root`, `dark-*` keys without the prefix under `:root[data-theme="dark"]`), plus `--md-primary-hover`, `--md-success-container`, `--md-on-success-container`.
- Produces Tailwind utilities `bg|text|border|ring|fill|stroke-<role>` for every role, `bg-grade-{a-star,a,b,c,d,e,u}`, `rounded-{bar,row,chip,button,inner,tile,card,board,pill}`, `font-{display,sans,mono}`.

- [ ] **Step 1: Rewrite the contrast test first (failing)**

Replace `tests/test_design_tokens.py` with a test that reads `DESIGN.md` frontmatter and `web/src/index.css`:

```python
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
TEXT_ON_SURFACES = ["on-surface", "on-surface-variant", "primary", "error"]
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


@pytest.mark.parametrize(("theme", "selector"), [("light", ":root"), ("dark", ':root[data-theme="dark"]')])
def test_css_declares_the_design_md_values(theme: str, selector: str) -> None:
    declared = _css_block(selector)
    for role, value in _scheme(theme).items():
        if role in {"abyss", "abyss-hover", "abyss-lip", "tide", "tide-hover", "mist-blue", "night", "white",
                    "gold", "crimson", "crimson-on-dark", "binny-steel", "binny-cheek"} or role.startswith("grade-"):
            continue
        assert declared.get(role, "").strip() == value, f"{theme} --md-{role}: css {declared.get(role)!r} != DESIGN.md {value!r}"
```

Run: `pytest tests/test_design_tokens.py -q`
Expected: FAIL in `test_css_declares_the_design_md_values` (index.css has no `--md-*` yet). If any AA test fails, that is a real `DESIGN.md` defect: stop and report the failing pair to the user before changing a colour; do not edit DESIGN.md silently.

- [ ] **Step 2: Replace font imports**

`web/src/index.css` lines 1-8 become:

```css
@import "tailwindcss";

/* v5 Abyss faces (DESIGN.md §3). Each has one job. */
@import "@fontsource-variable/bricolage-grotesque"; /* T1 display, 28px and above */
@import "@fontsource-variable/schibsted-grotesk"; /* T2 UI and text */
@import "@fontsource-variable/jetbrains-mono"; /* data */
```

In `web/package.json` remove `@fontsource-variable/newsreader`, `@fontsource-variable/geist`, `@fontsource-variable/caveat` and make sure `@fontsource-variable/bricolage-grotesque` and `@fontsource-variable/schibsted-grotesk` are in `dependencies`. Run `cd web && npm install`.

- [ ] **Step 3: Replace the `:root` and dark blocks**

Delete the old `:root { ... }` (from line 49) and `:root[data-theme="dark"] { ... }` blocks and the header comment, and write:

```css
/* ============================================================================
 * Lemely tokens, v5 "Abyss". SOURCE OF TRUTH: DESIGN.md frontmatter.
 * tests/test_design_tokens.py pins every value below against DESIGN.md and
 * measures AA contrast. Do not change a value here without changing DESIGN.md.
 * ========================================================================== */
:root {
  --md-primary: #042f4f;
  --md-primary-hover: #0a3d62;
  --md-on-primary: #ffffff;
  --md-primary-container: oklch(0.92 0.035 235);
  --md-on-primary-container: #042f4f;
  --md-secondary: oklch(0.40 0.010 235);
  --md-on-secondary: #ffffff;
  --md-secondary-container: oklch(0.90 0.037 235);
  --md-on-secondary-container: oklch(0.10 0.006 235);
  --md-tertiary: oklch(0.80 0.13 80);
  --md-on-tertiary: oklch(0.20 0.019 80);
  --md-tertiary-container: oklch(0.95 0.098 80);
  --md-on-tertiary-container: oklch(0.30 0.022 80);
  --md-error: oklch(0.55 0.20 25);
  --md-on-error: #ffffff;
  --md-error-container: oklch(0.95 0.067 25);
  --md-on-error-container: oklch(0.30 0.117 25);
  --md-success: oklch(0.60 0.12 150);
  --md-success-container: oklch(0.95 0.04 150);
  --md-on-success-container: oklch(0.32 0.08 150);
  --md-surface: oklch(0.985 0.004 240);
  --md-surface-container-lowest: #ffffff;
  --md-surface-container-low: oklch(0.97 0.006 240);
  --md-surface-container: oklch(0.955 0.008 240);
  --md-surface-container-high: oklch(0.94 0.01 240);
  --md-surface-container-highest: oklch(0.92 0.012 240);
  --md-on-surface: #130e10;
  --md-on-surface-variant: oklch(0.47 0.02 240);
  --md-outline: oklch(0.87 0.012 240);
  --md-outline-variant: oklch(0.92 0.01 240);
  --md-inverse-surface: #130e10;
  --md-inverse-on-surface: oklch(0.95 0.006 240);
  --md-inverse-primary: #7fb8e0;
  --md-scrim: oklch(0.20 0.03 242 / 0.4);
  --md-shadow: oklch(0.30 0.06 242);

  --grade-a-star: oklch(0.46 0.12 155);
  --grade-a: oklch(0.52 0.12 132);
  --grade-b: oklch(0.58 0.12 110);
  --grade-c: oklch(0.63 0.12 88);
  --grade-d: oklch(0.59 0.125 62);
  --grade-e: oklch(0.54 0.13 38);
  --grade-u: oklch(0.50 0.14 15);

  --shadow-hover: 0 22px 40px -26px oklch(0.3 0.06 242 / 0.4);
  --shadow-panel: 0 30px 60px -40px oklch(0.3 0.06 242 / 0.45), 0 0 0 1px oklch(0.92 0.01 240);

  --ease-out: cubic-bezier(0.2, 0.8, 0.2, 1);
  --ease-expo: cubic-bezier(0.16, 1, 0.3, 1);
  --dur-fast: 150ms;
  --dur-base: 200ms;
  --dur-slow: 350ms;

  color-scheme: light;
}

:root[data-theme="dark"] {
  --md-primary: #7fb8e0;
  --md-primary-hover: #9ccaea;
  --md-on-primary: #042f4f;
  --md-primary-container: oklch(0.34 0.07 242);
  --md-on-primary-container: oklch(0.92 0.035 235);
  --md-secondary: oklch(0.80 0.037 235);
  --md-on-secondary: oklch(0.20 0.006 235);
  --md-secondary-container: oklch(0.30 0.006 235);
  --md-on-secondary-container: oklch(0.90 0.037 235);
  --md-tertiary: oklch(0.80 0.13 80);
  --md-on-tertiary: oklch(0.20 0.019 80);
  --md-tertiary-container: oklch(0.30 0.022 80);
  --md-on-tertiary-container: oklch(0.90 0.108 80);
  --md-error: oklch(0.72 0.15 25);
  --md-on-error: oklch(0.20 0.083 25);
  --md-error-container: oklch(0.30 0.117 25);
  --md-on-error-container: oklch(0.90 0.083 25);
  --md-success: oklch(0.72 0.12 150);
  --md-success-container: oklch(0.30 0.06 150);
  --md-on-success-container: oklch(0.90 0.06 150);
  --md-surface: #130e10;
  --md-surface-container-lowest: oklch(0.12 0.006 240);
  --md-surface-container-low: oklch(0.19 0.01 240);
  --md-surface-container: oklch(0.215 0.014 240);
  --md-surface-container-high: oklch(0.25 0.018 240);
  --md-surface-container-highest: oklch(0.29 0.022 240);
  --md-on-surface: oklch(0.95 0.006 240);
  --md-on-surface-variant: oklch(0.77 0.015 240);
  --md-outline: oklch(0.38 0.02 240);
  --md-outline-variant: oklch(0.30 0.018 240);
  --md-inverse-surface: oklch(0.95 0.006 240);
  --md-inverse-on-surface: #130e10;
  --md-inverse-primary: #042f4f;

  color-scheme: dark;
}
```

The `success-container`, `on-success-container`, `primary-hover` and dark `success` values are not in `DESIGN.md` yet. Add them to `DESIGN.md` frontmatter (light keys and `dark-` keys) in this same step so the parity test covers them; they follow the kit's success palette at the container tones.

- [ ] **Step 4: Replace the `@theme inline` blocks**

Delete both old `@theme inline` blocks and the compat `:root, [data-portal=...]` block (lines 597-690, but keep the `--spacing-*` and `--breakpoint-tablet` lines, which screens still use) and write one block:

```css
@theme inline {
  --color-*: initial;
  --color-transparent: transparent;
  --color-current: currentColor;
  --color-white: var(--md-surface-container-lowest);

  --color-primary: var(--md-primary);
  --color-primary-hover: var(--md-primary-hover);
  --color-on-primary: var(--md-on-primary);
  --color-primary-container: var(--md-primary-container);
  --color-on-primary-container: var(--md-on-primary-container);
  --color-secondary: var(--md-secondary);
  --color-on-secondary: var(--md-on-secondary);
  --color-secondary-container: var(--md-secondary-container);
  --color-on-secondary-container: var(--md-on-secondary-container);
  --color-tertiary: var(--md-tertiary);
  --color-on-tertiary: var(--md-on-tertiary);
  --color-tertiary-container: var(--md-tertiary-container);
  --color-on-tertiary-container: var(--md-on-tertiary-container);
  --color-error: var(--md-error);
  --color-on-error: var(--md-on-error);
  --color-error-container: var(--md-error-container);
  --color-on-error-container: var(--md-on-error-container);
  --color-success: var(--md-success);
  --color-success-container: var(--md-success-container);
  --color-on-success-container: var(--md-on-success-container);
  --color-surface: var(--md-surface);
  --color-surface-container-lowest: var(--md-surface-container-lowest);
  --color-surface-container-low: var(--md-surface-container-low);
  --color-surface-container: var(--md-surface-container);
  --color-surface-container-high: var(--md-surface-container-high);
  --color-surface-container-highest: var(--md-surface-container-highest);
  --color-on-surface: var(--md-on-surface);
  --color-on-surface-variant: var(--md-on-surface-variant);
  --color-outline: var(--md-outline);
  --color-outline-variant: var(--md-outline-variant);
  --color-inverse-surface: var(--md-inverse-surface);
  --color-inverse-on-surface: var(--md-inverse-on-surface);
  --color-inverse-primary: var(--md-inverse-primary);
  --color-scrim: var(--md-scrim);

  --color-grade-a-star: var(--grade-a-star);
  --color-grade-a: var(--grade-a);
  --color-grade-b: var(--grade-b);
  --color-grade-c: var(--grade-c);
  --color-grade-d: var(--grade-d);
  --color-grade-e: var(--grade-e);
  --color-grade-u: var(--grade-u);

  --font-display: "Bricolage Grotesque Variable", "Schibsted Grotesk Variable", sans-serif;
  --font-sans: "Schibsted Grotesk Variable", system-ui, sans-serif;
  --font-mono: "JetBrains Mono Variable", ui-monospace, monospace;
  --font-serif: var(--font-display);

  --radius-bar: 4px;
  --radius-row: 10px;
  --radius-chip: 12px;
  --radius-button: 14px;
  --radius-inner: 18px;
  --radius-tile: 20px;
  --radius-card: 24px;
  --radius-board: 32px;
  --radius-pill: 999px;
  --radius-sm: 10px;
  --radius-md: 12px;
  --radius-lg: 14px;
  --radius-xl: 20px;
  --radius-2xl: 24px;
  --radius: 12px;

  --shadow-float: var(--shadow-panel);
  --shadow-hover: var(--shadow-hover);
  --shadow-panel: var(--shadow-panel);

  --ease-out: var(--ease-out);
  --ease-expo: var(--ease-expo);
}
```

`--color-*: initial` removes Tailwind's default palette so a stray `bg-blue-500` fails `utilityExistence.test.ts` instead of shipping.

- [ ] **Step 5: Retarget the type scale**

In the `§4.2 Type scale` section, keep every class name (`text-display-*`, `text-body-*`, `text-label`, `text-eyebrow`, `text-data-*`, `text-metadata`, `btn-text*`) and set their declarations to the `DESIGN.md` ramp:

```css
.text-display-hero { font: 800 64px/1 var(--font-display); letter-spacing: -0.03em; }
.text-display-xl   { font: 800 64px/1 var(--font-display); letter-spacing: -0.03em; }
.text-display-lg   { font: 800 40px/1.05 var(--font-display); letter-spacing: -0.03em; }
.text-display-md   { font: 800 32px/1.15 var(--font-sans); letter-spacing: -0.02em; }
.text-display-sm   { font: 700 21px/1.25 var(--font-sans); letter-spacing: -0.01em; }
.text-display-xs   { font: 700 16px/1.3 var(--font-sans); }
.text-body-lg      { font: 400 16px/1.5 var(--font-sans); }
.text-body-md      { font: 400 16px/1.5 var(--font-sans); }
.text-body-sm      { font: 400 14px/1.45 var(--font-sans); }
.text-field        { font: 600 14px/1.3 var(--font-sans); }
.text-label        { font: 600 14px/1.3 var(--font-sans); }
.text-label-sm     { font: 600 11px/1.2 var(--font-mono); letter-spacing: 0.08em; text-transform: uppercase; }
.text-eyebrow      { font: 600 11px/1.2 var(--font-mono); letter-spacing: 0.08em; text-transform: uppercase; }
.text-metadata     { font: 400 14px/1.45 var(--font-sans); color: var(--md-on-surface-variant); }
.text-data-lg      { font: 600 16px/1.3 var(--font-mono); font-variant-numeric: tabular-nums; }
.text-data-md      { font: 600 14px/1.3 var(--font-mono); font-variant-numeric: tabular-nums; }
.text-data-sm      { font: 600 11px/1.2 var(--font-mono); font-variant-numeric: tabular-nums; }
.btn-text          { font: 700 14px/1 var(--font-sans); }
.btn-text-sm       { font: 700 14px/1 var(--font-sans); }
.btn-text-lg       { font: 700 16px/1 var(--font-sans); }
```

Keep any existing responsive overrides for these classes only if they still land on `DESIGN.md` sizes; delete the rest. Delete `.text-hand` (Task 4 removes its uses).

- [ ] **Step 6: Delete the texture layer**

Delete the `§8 The notebook texture layer` section (`.paper-grain`, `.ruled-bg`, `.dotted-bg`, `.margin-rule`, `.sticker` and their dark variants). Task 4 removes the uses. Restyle `.lm-red-pen` to `color: var(--md-error)` with no font change.

Replace the base layer's body rule so the page uses the roles:

```css
body {
  background: var(--md-surface);
  color: var(--md-on-surface);
  font-family: var(--font-sans);
}
```

- [ ] **Step 7: Rewrite `web/tests/unit/design-tokens.test.ts`**

Replace its body with a parity check that every `DESIGN.md` role is exposed as a Tailwind colour:

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

const css = readFileSync(join(__dirname, "../../src/index.css"), "utf8")
const design = readFileSync(join(__dirname, "../../../DESIGN.md"), "utf8")
const front = design.split("---")[1]
const roles = [...front.matchAll(/^  ([a-z0-9-]+): "/gm)]
  .map((m) => m[1])
  .filter((k) => !k.startsWith("dark-") && !k.startsWith("grade-") && !k.startsWith("binny-"))
  .filter((k) => !["abyss", "abyss-hover", "abyss-lip", "tide", "tide-hover", "mist-blue", "night", "white", "gold", "crimson", "crimson-on-dark"].includes(k))

describe("token layer", () => {
  it.each(roles)("exposes --color-%s as a utility", (role) => {
    expect(css).toContain(`--color-${role}: var(--md-${role})`)
  })

  it("declares a dark value for every light role", () => {
    const light = new Set([...css.split(':root[data-theme="dark"]')[0].matchAll(/--md-([a-z0-9-]+):/g)].map((m) => m[1]))
    const dark = new Set([...css.split(':root[data-theme="dark"]')[1].split("}")[0].matchAll(/--md-([a-z0-9-]+):/g)].map((m) => m[1]))
    for (const role of ["scrim", "shadow"]) light.delete(role)
    expect([...light].filter((r) => !dark.has(r))).toEqual([])
  })

  it("loads no retired face", () => {
    for (const face of ["newsreader", "geist", "caveat"]) expect(css.toLowerCase()).not.toContain(face)
  })
})
```

- [ ] **Step 8: Run both token tests**

Run: `pytest tests/test_design_tokens.py -q && cd web && npx vitest run tests/unit/design-tokens.test.ts`
Expected: both PASS.

- [ ] **Step 9: Checkpoint**

Report changed paths. Do not commit. `npm run build` is expected to fail until Task 3 (old utility names no longer exist).

---

### Task 3: Run the codemod

**Files:**
- Modify: about 147 files under `web/src` (generated)

**Interfaces:**
- Consumes: Task 1 CLI, Task 2 utilities.

- [ ] **Step 1: Dry run**

Run: `cd web && node scripts/abyss-codemod.mjs --compat --check`
Expected: lists files and exits 1 (changes pending). Skim 10 lines of output for sanity.

- [ ] **Step 2: Apply with compat (the only compat run)**

Run: `cd web && node scripts/abyss-codemod.mjs --compat`
Expected: about 147 files changed.

- [ ] **Step 3: Prove idempotency**

Run: `cd web && node scripts/abyss-codemod.mjs --check`
Expected: `0 file(s)`, exit 0.

- [ ] **Step 4: Find what is left for Task 4**

Run: `cd web && grep -rnoE '(bg|text|border|ring|fill|stroke)-(grade-(top|mid|borderline|fail)|pastel-[a-z]+|subject-[a-z]+)[a-z-]*' src | sort | uniq -c`
Expected: the grade-band, pastel and subject uses (about 40 lines). Save the list in the checkpoint report.

- [ ] **Step 5: Typecheck**

Run: `cd web && npm run typecheck`
Expected: PASS (the codemod changes strings only).

- [ ] **Step 6: Checkpoint**

Report the file count and the Step 4 list. Do not commit.

---

### Task 4: Hand fixes for what the table cannot express

**Files:**
- Modify: files listed by Task 3 Step 4, plus files using `paper-grain`, `ruled-bg`, `margin-rule`, `sticker`, `text-hand`, `lm-mark`, `lm-confetti` (find with the command in Step 1)

**Interfaces:**
- Produces: `gradeTone(grade: string): "a-star" | "a" | "b" | "c" | "d" | "e" | "u" | null` in `web/src/lib/grade.ts`, used by every grade chip.

- [ ] **Step 1: List the hand-fix sites**

Run: `cd web && grep -rlnE 'grade-(top|mid|borderline|fail)|pastel-|subject-|paper-grain|ruled-bg|margin-rule|\bsticker\b|text-hand|lm-mark|lm-confetti|#[0-9a-fA-F]{6}\b' src`
Expected: about 35 files.

- [ ] **Step 2: Write the grade helper test**

`web/tests/unit/gradeTone.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { gradeTone } from "@/lib/grade"

describe("gradeTone", () => {
  it.each([
    ["A*", "a-star"], ["A", "a"], ["B", "b"], ["C", "c"], ["D", "d"], ["E", "e"], ["U", "u"],
    ["a*", "a-star"], [" b ", "b"],
  ])("%s maps to %s", (grade, tone) => expect(gradeTone(grade)).toBe(tone))

  it.each(["", "F", "9", "A**"])("%s has no tone", (grade) => expect(gradeTone(grade)).toBeNull())
})
```

Run: `cd web && npx vitest run tests/unit/gradeTone.test.ts` and expect FAIL (module missing).

- [ ] **Step 3: Implement the helper**

`web/src/lib/grade.ts`:

```ts
/** Maps a CAIE letter grade to its Jewel scale token (DESIGN.md "Grade scale"). */
export type GradeTone = "a-star" | "a" | "b" | "c" | "d" | "e" | "u"

const TONES: Record<string, GradeTone> = { "A*": "a-star", A: "a", B: "b", C: "c", D: "d", E: "e", U: "u" }

export function gradeTone(grade: string): GradeTone | null {
  return TONES[grade.trim().toUpperCase()] ?? null
}

/** Tailwind classes for a grade chip: Jewel fill, white letter, always labelled. */
export function gradeChipClass(grade: string): string {
  const tone = gradeTone(grade)
  return tone ? `bg-grade-${tone} text-white` : "bg-surface-container-high text-on-surface"
}
```

Tailwind only generates classes it can see as literals, so add this safelist line to `index.css` directly after the `@theme inline` block:

```css
@source inline("bg-grade-{a-star,a,b,c,d,e,u}");
```

Run the test again: PASS.

- [ ] **Step 4: Apply the per-use rules**

For each file from Step 1, apply exactly these rules:

| Retired use | Replacement |
|---|---|
| `bg-grade-top`/`-mid`/`-borderline`/`-fail` (+`-bg`, `text-grade-*`) on a chip that shows a letter | `className={gradeChipClass(grade)}` |
| grade band colour on something that is not a letter chip (bars, dots) | `bg-primary` for the fill, `bg-surface-container-high` for the track |
| `bg-pastel-*` with `text-pastel-*-ink` (tags) | `bg-secondary-container text-on-secondary-container rounded-pill` |
| `subject-*` colour | `bg-primary-container text-on-primary-container` (subjects are not colour-coded in v5) |
| `paper-grain`, `ruled-bg`, `dotted-bg`, `margin-rule` | delete the class |
| `sticker` | `rounded-chip bg-secondary-container text-on-secondary-container` |
| `text-hand` (marginalia) | delete the element if decorative; if it carries information, `text-body-sm text-on-surface-variant` |
| `lm-confetti` | delete (PRODUCT.md anti-reference) and keep only `lm-pop` |
| `lm-mark` (old notebook logo) | the Clip Letters wordmark from the marketing portal (`BrandLockup` already renders it if it imports the marketing logo; otherwise move the marketing wordmark component to `web/src/components/ui/brand-lockup.tsx` and use it) |
| hard-coded hex | the matching role utility |
| `Binny` imported anywhere under `portals/teacher`, `portals/parent`, `portals/admin` | delete the import and element |

- [ ] **Step 5: Verify nothing retired remains in this set**

Run the Step 1 command again.
Expected: no output.

- [ ] **Step 6: Build**

Run: `cd web && npm run build`
Expected: PASS, bundle budget check passes.

- [ ] **Step 7: Checkpoint**

Report changed files. Do not commit.

---

### Task 5: Retired-token guard

**Files:**
- Create: `web/tests/unit/retiredTokens.test.ts`
- Delete: `web/tests/unit/studyNotebookMigration.test.ts` (it guards the retired system)

- [ ] **Step 1: Write the guard**

```ts
import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import { relativeTo, sourceFiles, stripComments } from "./support/jsxSource"

/** Any of these in web/src means a screen still speaks the retired Study Notebook vocabulary. */
export const RETIRED = [
  /(?<![\w-])(?:[\w-]+:)*(?:bg|text|border|ring|fill|stroke|outline|divide)-(?:paper|ink|rule|accent|pastel|subject|ok|warn|err|info|confidence|mark|t1|t2|t3)(?:-[a-z0-9-]+)?(?![\w-])/,
  /\b(?:paper-grain|ruled-bg|dotted-bg|margin-rule|text-hand|font-hand|lm-confetti)\b/,
  /Caveat|Newsreader|Geist/,
]

export function retiredHits(source: string): string[] {
  const code = stripComments(source)
  return RETIRED.flatMap((re) => {
    const m = code.match(new RegExp(re.source, "g"))
    return m ?? []
  })
}

describe("retired token guard", () => {
  it("catches a planted retired name (proves the guard can go red)", () => {
    expect(retiredHits(`<div className="hover:text-ink-muted bg-paper-raised" />`)).toEqual(["hover:text-ink-muted", "bg-paper-raised"])
    expect(retiredHits(`<p className="text-hand">x</p>`)).toEqual(["text-hand"])
  })

  it("ignores names that only start with a retired word", () => {
    expect(retiredHits(`<div className="text-inkwell bg-paperless" />`)).toEqual([])
  })

  it("finds no retired name anywhere in web/src", () => {
    const offenders = sourceFiles()
      .map((file) => ({ file: relativeTo(file), hits: retiredHits(readFileSync(file, "utf8")) }))
      .filter((r) => r.hits.length)
    expect(offenders).toEqual([])
  })
})
```

Check `web/tests/unit/support/jsxSource.ts` exports `sourceFiles`, `relativeTo`, `stripComments` (it is used by `utilityExistence.test.ts`). If `sourceFiles()` does not include `.css` files under `src/portals`, that is fine: CSS is covered by `design-tokens.test.ts` and the build.

- [ ] **Step 2: Run it**

Run: `cd web && npx vitest run tests/unit/retiredTokens.test.ts`
Expected: the first two tests PASS. The third PASSES if Tasks 3 and 4 are complete; if it lists offenders, fix each with the Task 4 table and re-run.

- [ ] **Step 3: Prove it goes red on the tree**

Temporarily add `className="text-ink"` to any component, re-run, expect FAIL naming that file, then remove it and re-run to PASS.

- [ ] **Step 4: Checkpoint**

Report paths. Do not commit.

---

### Task 6: Triage the tests and scripts coupled to the old system

**Files:**
- Modify or delete: the vitest files below, `web/scripts/{check_copy,adapt_audit,check-native-invariants,audit,compare_screens}.mjs`, `web/scripts/generate_mark_svg.mjs`, `web/scripts/generate_icons.mjs`

Coupled vitest files (found by grepping for retired names): `brandMark, celebration, darkConsumers, fontPreload, chartTheme, fullPageStateCopy, nativeMechanics, a11yRules, navShells, checkCopy, designDocs, elevationScale, loadingTiers, rtlSafety, formsMigration, shadcnSetup, splashScreens, hoverTransition, subjectGlyph, practiceSources, printStyles, themeInit, brandTokens, teacherPaperDeletionWiring, adaptRules, motionDefaults, marketingCardPadding, routeSkeleton, preMountShell, redPen, streakChip, overlayExit, tableDensity, teacherTables, progressRing, screenEntrance, contrastRules, utilityExistence, utils`.

- [ ] **Step 1: Run the web suite and list failures**

Run: `cd web && npx vitest run 2>&1 | grep -E 'FAIL|✗' | sort -u`
Expected: a list of failing files.

- [ ] **Step 2: Classify and fix each failing assertion with this rule**

For each failing assertion, decide which kind it is and act:

1. **It asserts a retired value or name** (a Study Notebook hex, `--paper`, `Newsreader`, `Caveat`, pastel, texture, the old notebook logo). Rewrite the assertion to the `DESIGN.md` equivalent (same intent, new value). Example: a test expecting `--ink-faint` to clear AA becomes one expecting `--md-on-surface-variant` to clear AA.
2. **It asserts a behaviour that still exists** (focus visible, reduced motion, tabular numbers, table density, RTL safety) but names the old class. Rename the class in the assertion using `web/scripts/abyss-token-map.json`.
3. **It guards a rule that `DESIGN.md` retired** (Caveat-only-decorative, paper texture opacity, pastel ink pairs, subject colours). Delete the test case, and the file if nothing remains. List every deleted case in the checkpoint report.
4. **It points at `DESIGN.md` section numbers** (`designDocs.test.ts`). Update it to the six sections of the new `DESIGN.md`: Overview, Colors, Typography, Elevation, Components, Do's and Don'ts.

Never weaken a still-valid behaviour test to make it pass.

- [ ] **Step 3: Fix the scripts**

In each script listed above, replace retired token names with their M3 roles from the mapping table. `check_copy.mjs`: keep the copy rules, add the never-say list (`cram`, `hack`, `easy A`, `guaranteed grade`) if absent. `generate_mark_svg.mjs`/`generate_icons.mjs`: if they draw the old notebook mark, switch them to the Clip Letters "lm" icon geometry in `DESIGN.md` (rounded square rx 24/100, Abyss tile, Tide clip with stroke 5, white `m`).

- [ ] **Step 4: Run every web gate from ci.yml**

Run: `cd web && npm run typecheck && npx vitest run && npm run lint && npm run check:copy && npm run build`
Expected: all PASS.

- [ ] **Step 5: Checkpoint**

Report rewritten and deleted test cases. Do not commit.

---

### Task 7: Fold marketing tokens into the role set

**Files:**
- Modify: `web/src/portals/marketing/brand-tokens.css`
- Modify: `web/tests/unit/brandTokens.test.ts`

- [ ] **Step 1: Point marketing variables at the roles**

In `brand-tokens.css`, keep the variable names the marketing components use (`--background`, `--foreground`, `--primary`, `--primary-foreground`, `--secondary-foreground`, `--muted`, `--muted-foreground`, `--ring`, `--border`) but define each as a role reference instead of a literal:

```css
.marketing-root, [data-portal="marketing"] {
  --background: var(--md-surface);
  --foreground: var(--md-on-surface);
  --primary: var(--md-primary);
  --primary-foreground: var(--md-on-primary);
  --secondary-foreground: var(--md-on-secondary-container);
  --muted: var(--md-surface-container-low);
  --muted-foreground: var(--md-on-surface-variant);
  --ring: var(--md-primary);
  --border: var(--md-outline-variant);
}
```

Use whatever selector the file already scopes to (read it first; keep that selector). Remove the duplicate `@fontsource-variable` imports (index.css loads them now). Delete every remaining literal colour in the file; if a marketing-only colour has no role (for example a Binny colour), move it to `index.css` `:root` as `--binny-steel` / `--binny-cheek` from `DESIGN.md`.

- [ ] **Step 2: Update the test**

In `brandTokens.test.ts`, assert that `brand-tokens.css` contains no `#`/`oklch(` literal and that each variable above resolves to a `var(--md-...)`.

- [ ] **Step 3: Run**

Run: `cd web && npx vitest run tests/unit/brandTokens.test.ts && npm run build`
Expected: PASS.

- [ ] **Step 4: Checkpoint**

Report paths. Do not commit.

---

### Task 8: Backend overview fields

**Files:**
- Modify: `lemely/web/schemas_teacher.py:464-480` (`AtRiskStudentDTO`) and `:505-520` (`OverviewDTO`)
- Modify: `lemely/web/routers/teacher.py` (`teacher_overview` around line 1948, `_at_risk` loop)
- Test: `tests/test_web_teacher_overview_fields.py`

**Interfaces:**
- Produces JSON: `OverviewDTO.paperCount: int`, `pendingReviewCount: int`, `reviewConfidenceBuckets: list[int]` (always length 10, band `i` = confidence in `[i/10, (i+1)/10)`, `1.0` lands in band 9, items with no confidence are not bucketed), `reviewEstimateMinutes: int`; `AtRiskStudentDTO.previousGrade: str | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_web_teacher_overview_fields.py` reuses the fixtures and helpers of `tests/test_web_teacher.py` (`client`, `pg_sessionmaker`, `class_service`, `history_store`, `_seed_user`, `_use_class_service`, `_auth_as`, `_join_student`, `_seed_history_record`). Import the helpers from that module:

```python
"""The five additive overview fields behind the teacher home (spec 2026-11-02)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.models import Role
from lemely.web.routers.teacher import _confidence_buckets, _review_estimate_minutes
from tests.test_web_teacher import (
    _auth_as,
    _join_student,
    _seed_history_record,
    _seed_user,
    _use_class_service,
)


def test_buckets_are_ten_wide_and_skip_missing_confidence() -> None:
    assert _confidence_buckets([0.05, 0.15, 0.15, 0.99, 1.0, None]) == [1, 2, 0, 0, 0, 0, 0, 0, 0, 2]
    assert _confidence_buckets([]) == [0] * 10


def test_estimate_rounds_up_and_is_zero_when_empty() -> None:
    assert _review_estimate_minutes(0) == 0
    assert _review_estimate_minutes(1) == 1
    assert _review_estimate_minutes(23) == 8  # ceil(23 * 20 / 60)


def test_empty_teacher_gets_zeroed_fields(client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service) -> None:  # type: ignore[no-untyped-def]
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    body = client.get("/api/teacher/overview").json()
    assert body["paperCount"] == 0
    assert body["pendingReviewCount"] == 0
    assert body["reviewConfidenceBuckets"] == [0] * 10
    assert body["reviewEstimateMinutes"] == 0


def test_paper_count_and_previous_grade(client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service, history_store) -> None:  # type: ignore[no-untyped-def]
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _join_student(pg_sessionmaker, class_service, cls.join_code, "Ziad")
    _seed_history_record(history_store, str(ziad), percentage=72.0, grade="B")
    _seed_history_record(history_store, str(ziad), percentage=65.0, grade="C")
    _seed_history_record(history_store, str(ziad), percentage=58.0, grade="D")
    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    body = client.get("/api/teacher/overview").json()
    assert body["paperCount"] == 3
    (student,) = body["atRisk"]
    assert student["grade"] == "D"
    assert student["previousGrade"] == "C"


def test_previous_grade_is_null_with_one_paper(client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service, history_store) -> None:  # type: ignore[no-untyped-def]
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10B")
    assert cls.join_code is not None
    nour = _join_student(pg_sessionmaker, class_service, cls.join_code, "Nour")
    # A single low paper still trips "predicted below target" only with a target, so
    # call the helper directly on the stored history rather than relying on a flag.
    _seed_history_record(history_store, str(nour), percentage=40.0, grade="E")
    from lemely.web.routers.teacher import _previous_grade

    assert _previous_grade(history_store.load(str(nour)).records) is None
    assert _previous_grade([]) is None
```

Before running, open `tests/test_web_teacher.py` and check where the fixtures (`client`, `pg_sessionmaker`, `class_service`, `history_store`) are defined. If they are in `tests/conftest.py`, the imports above are enough. If they are defined inside `tests/test_web_teacher.py`, import them too: `from tests.test_web_teacher import client, pg_sessionmaker, class_service, history_store  # noqa: F401`. Adjust the `Role` import path to match the one `tests/test_web_teacher.py` uses.

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/test_web_teacher_overview_fields.py -q`
Expected: FAIL, `ImportError: cannot import name '_confidence_buckets'`.

- [ ] **Step 3: Add the schema fields**

In `lemely/web/schemas_teacher.py`, `AtRiskStudentDTO` gains (after `grade`):

```python
    previousGrade: str | None = None
```

`OverviewDTO` gains (after `recentActivity`):

```python
    paperCount: int = 0
    pendingReviewCount: int = 0
    reviewConfidenceBuckets: list[int] = Field(default_factory=lambda: [0] * 10)
    reviewEstimateMinutes: int = 0
```

Extend both docstrings with one sentence each naming the new fields as additive (spec 2026-11-02).

- [ ] **Step 4: Add the helpers and wire them**

In `lemely/web/routers/teacher.py`, next to `_count_review_items`:

```python
SECONDS_PER_REVIEW = 20
"""Heuristic seconds a teacher spends per review item; the UI labels the result "about"."""


def _confidence_buckets(confidences: Iterable[float | None]) -> list[int]:
    """Count pending review items per 10% confidence band (band 9 includes 1.0)."""
    buckets = [0] * 10
    for value in confidences:
        if value is None:
            continue
        buckets[min(9, max(0, int(value * 10)))] += 1
    return buckets


def _review_estimate_minutes(pending: int) -> int:
    return math.ceil(pending * SECONDS_PER_REVIEW / 60)


def _previous_grade(records: Sequence[HistoryRecord]) -> str | None:
    """Grade of the grade-bearing paper before the latest one, or None."""
    bearing = [r for r in records if is_grade_bearing(r)]
    return bearing[-2].grade if len(bearing) >= 2 else None
```

Add the imports the file lacks (`import math`, `from collections.abc import Iterable, Sequence`, and `HistoryRecord`/`is_grade_bearing` from wherever `latest_grade_bearing` and `is_paper` are imported in this file). Confirm the record ordering `latest_grade_bearing` assumes (oldest first or newest first) and index accordingly; the test in Step 1 pins it.

In `teacher_overview`, replace `needs_review = _count_review_items(review_service, auth)` with:

```python
    queue = review_service.list_queue(auth.user_id, auth.role)
    needs_review = queue.total
    buckets = _confidence_buckets(row.confidence_score for row in queue.rows)
```

Keep `_count_review_items` if anything else calls it; otherwise delete it and move its docstring's granularity note onto the two lines above. Compute the paper count once and reuse it for the stat card:

```python
    paper_count = sum(1 for history, _ in histories for record in history.records if is_paper(record))
```

and use `value=str(paper_count)` in the "Papers graded" card. Return:

```python
    return OverviewDTO(
        stats=stats,
        atRisk=at_risk_students,
        retention=[],
        recentActivity=recent_activity,
        paperCount=paper_count,
        pendingReviewCount=needs_review,
        reviewConfidenceBuckets=buckets,
        reviewEstimateMinutes=_review_estimate_minutes(needs_review),
    )
```

In `_at_risk`, add `previousGrade=_previous_grade(history.records),` to the `AtRiskStudentDTO(...)` call.

`list_queue` without `limit` returns every row; that is fine for a teacher's own queue. If `ReviewQueuePage.rows` is limited by default, pass `limit=None` explicitly.

- [ ] **Step 5: Run the new tests and the existing overview tests**

Run: `pytest tests/test_web_teacher_overview_fields.py tests/test_web_teacher.py -k overview -q`
Expected: PASS.

Run: `pytest tests/test_authz_matrix.py tests/test_authz_matrix_complete.py -q`
Expected: PASS (route unchanged).

- [ ] **Step 6: Lint and types**

Run: `ruff check lemely/web tests/test_web_teacher_overview_fields.py && ruff format --check lemely/web tests/test_web_teacher_overview_fields.py && mypy lemely/web/routers/teacher.py lemely/web/schemas_teacher.py`
Expected: clean.

- [ ] **Step 7: Checkpoint**

Report paths. Do not commit.

---

### Task 9: Types, setup derivation and tile view models

**Files:**
- Modify: `web/src/lib/teacherTypes.ts:238-273`
- Create: `web/src/portals/teacher/home/setup.ts`
- Create: `web/src/portals/teacher/home/models.ts`
- Test: `web/tests/unit/teacherSetup.test.ts`, `web/tests/unit/teacherHomeModels.test.ts`

**Interfaces:**
- Produces:
  - `deriveSetup(classCount: number, overview: Pick<Overview, "paperCount" | "pendingReviewCount">): SetupProgress` where `SetupProgress = { created: boolean; uploaded: boolean; reviewed: boolean; done: number; complete: boolean }`.
  - `reviewQueueModel(o: Pick<Overview, "pendingReviewCount" | "reviewConfidenceBuckets" | "reviewEstimateMinutes">): ReviewQueueModel` where `ReviewQueueModel = { count: number; bars: { band: number; height: number; low: boolean }[]; estimate: string | null; empty: boolean }`. `height` is 0..1 relative to the largest bucket; `low` is true for bands below the 70% threshold (bands 0-6).
  - `atRiskRowModel(s: AtRiskStudent): AtRiskRowModel` where `AtRiskRowModel = { initials: string; name: string; reason: string; from: string | null; to: string | null }`.
  - `classCardModel(c: ClassSummary): ClassCardModel` where `ClassCardModel = { id: string; title: string; meta: string; average: string | null; weakTopic: string | null }`.
  - `REVIEW_THRESHOLD_BAND = 7`.

- [ ] **Step 1: Mirror the backend fields**

In `teacherTypes.ts`, `AtRiskStudent` gains `previousGrade: string | null` and `Overview` gains:

```ts
  paperCount: number
  pendingReviewCount: number
  /** 10 counts, one per 10% confidence band over pending review items. */
  reviewConfidenceBuckets: number[]
  /** ceil(pending x 20s / 60); a heuristic, rendered as "about N min". */
  reviewEstimateMinutes: number
```

- [ ] **Step 2: Write the failing tests**

`web/tests/unit/teacherSetup.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { deriveSetup } from "@/portals/teacher/home/setup"

describe("deriveSetup", () => {
  it.each([
    // classes, papers, pending, created, uploaded, reviewed, done
    [0, 0, 0, false, false, false, 0],
    [1, 0, 0, true, false, false, 1],
    [1, 3, 5, true, true, false, 2],
    [1, 3, 0, true, true, true, 3],
    [0, 3, 0, false, true, true, 2],
  ])("classes=%i papers=%i pending=%i", (classes, papers, pending, created, uploaded, reviewed, done) => {
    const s = deriveSetup(classes, { paperCount: papers, pendingReviewCount: pending })
    expect(s).toEqual({ created, uploaded, reviewed, done, complete: done === 3 })
  })

  it("never counts review as done before any paper exists", () => {
    expect(deriveSetup(2, { paperCount: 0, pendingReviewCount: 0 }).reviewed).toBe(false)
  })
})
```

`web/tests/unit/teacherHomeModels.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { atRiskRowModel, classCardModel, reviewQueueModel } from "@/portals/teacher/home/models"

describe("reviewQueueModel", () => {
  it("scales bars to the largest bucket and marks bands under 70% as low", () => {
    const m = reviewQueueModel({ pendingReviewCount: 6, reviewConfidenceBuckets: [0, 0, 0, 0, 0, 2, 4, 0, 0, 0], reviewEstimateMinutes: 2 })
    expect(m.count).toBe(6)
    expect(m.bars[6]).toEqual({ band: 6, height: 1, low: true })
    expect(m.bars[5]).toEqual({ band: 5, height: 0.5, low: true })
    expect(m.bars[7].low).toBe(false)
    expect(m.estimate).toBe("about 2 min")
    expect(m.empty).toBe(false)
  })

  it("is empty with zero pending and shows no estimate", () => {
    const m = reviewQueueModel({ pendingReviewCount: 0, reviewConfidenceBuckets: Array(10).fill(0), reviewEstimateMinutes: 0 })
    expect(m.empty).toBe(true)
    expect(m.estimate).toBeNull()
    expect(m.bars.every((b) => b.height === 0)).toBe(true)
  })

  it("tolerates a short or missing bucket list from an older server", () => {
    const m = reviewQueueModel({ pendingReviewCount: 1, reviewConfidenceBuckets: [], reviewEstimateMinutes: 1 })
    expect(m.bars).toHaveLength(10)
  })
})

describe("atRiskRowModel", () => {
  it("shows previous to current grade and the first flag summary", () => {
    const m = atRiskRowModel({ name: "Omar Hassan", grade: "D", previousGrade: "C", delta: -0.6, weakTopic: "Moments",
      flags: [{ reason: "declining", summary: "Down 0.6 over 3 papers", evidence: {}, acknowledged: null }] })
    expect(m).toEqual({ initials: "OH", name: "Omar Hassan", reason: "Down 0.6 over 3 papers", from: "C", to: "D" })
  })

  it("has no trail when there is no grade yet", () => {
    const m = atRiskRowModel({ name: "Laila", grade: "", previousGrade: null, delta: null, weakTopic: null,
      flags: [{ reason: "inactive", summary: "No paper in 3 weeks", evidence: {}, acknowledged: null }] })
    expect(m.from).toBeNull()
    expect(m.to).toBeNull()
    expect(m.initials).toBe("L")
  })
})

describe("classCardModel", () => {
  it("formats meta from real fields only", () => {
    const m = classCardModel({ id: "c1", label: "Year 11 Chemistry", studentCount: 52, average: 61.4, subjectCode: "0620",
      subjectName: "Chemistry", schoolId: null, joinCode: "K7M4QX", atRiskCount: 2, lastActivityAt: null, topWeakness: "Electrolysis" })
    expect(m).toEqual({ id: "c1", title: "Year 11 Chemistry", meta: "0620 · 52 students", average: "61%", weakTopic: "Electrolysis" })
  })

  it("omits what the class does not have", () => {
    const m = classCardModel({ id: "c2", label: "Physics group", studentCount: 1, average: null, subjectCode: null,
      subjectName: null, schoolId: null, joinCode: null, atRiskCount: null, lastActivityAt: null, topWeakness: null })
    expect(m.meta).toBe("1 student")
    expect(m.average).toBeNull()
  })
})
```

Run: `cd web && npx vitest run tests/unit/teacherSetup.test.ts tests/unit/teacherHomeModels.test.ts`
Expected: FAIL, modules missing.

- [ ] **Step 3: Implement**

`web/src/portals/teacher/home/setup.ts`:

```ts
import type { Overview } from "@/lib/teacherTypes"

export interface SetupProgress {
  created: boolean
  uploaded: boolean
  reviewed: boolean
  done: number
  complete: boolean
}

/** Setup steps derived from account data only (spec: no tracking field, no localStorage). */
export function deriveSetup(classCount: number, overview: Pick<Overview, "paperCount" | "pendingReviewCount">): SetupProgress {
  const created = classCount > 0
  const uploaded = overview.paperCount > 0
  const reviewed = uploaded && overview.pendingReviewCount === 0
  const done = [created, uploaded, reviewed].filter(Boolean).length
  return { created, uploaded, reviewed, done, complete: done === 3 }
}
```

`web/src/portals/teacher/home/models.ts`:

```ts
import type { AtRiskStudent, ClassSummary, Overview } from "@/lib/teacherTypes"

export const REVIEW_THRESHOLD_BAND = 7

export interface ReviewQueueModel {
  count: number
  bars: { band: number; height: number; low: boolean }[]
  estimate: string | null
  empty: boolean
}

export function reviewQueueModel(
  o: Pick<Overview, "pendingReviewCount" | "reviewConfidenceBuckets" | "reviewEstimateMinutes">,
): ReviewQueueModel {
  const counts = Array.from({ length: 10 }, (_, i) => o.reviewConfidenceBuckets?.[i] ?? 0)
  const max = Math.max(0, ...counts)
  return {
    count: o.pendingReviewCount,
    bars: counts.map((c, band) => ({ band, height: max ? c / max : 0, low: band < REVIEW_THRESHOLD_BAND })),
    estimate: o.pendingReviewCount > 0 && o.reviewEstimateMinutes > 0 ? `about ${o.reviewEstimateMinutes} min` : null,
    empty: o.pendingReviewCount === 0,
  }
}

export interface AtRiskRowModel {
  initials: string
  name: string
  reason: string
  from: string | null
  to: string | null
}

export function atRiskRowModel(s: AtRiskStudent): AtRiskRowModel {
  const initials = s.name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("")
  return {
    initials,
    name: s.name,
    reason: s.flags[0]?.summary ?? "",
    from: s.grade ? (s.previousGrade ?? null) : null,
    to: s.grade || null,
  }
}

export interface ClassCardModel {
  id: string
  title: string
  meta: string
  average: string | null
  weakTopic: string | null
}

export function classCardModel(c: ClassSummary): ClassCardModel {
  const students = `${c.studentCount} ${c.studentCount === 1 ? "student" : "students"}`
  return {
    id: c.id,
    title: c.label,
    meta: c.subjectCode ? `${c.subjectCode} · ${students}` : students,
    average: c.average === null ? null : `${Math.round(c.average)}%`,
    weakTopic: c.topWeakness,
  }
}
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run tests/unit/teacherSetup.test.ts tests/unit/teacherHomeModels.test.ts && npm run typecheck`
Expected: PASS. Typecheck may flag existing consumers of `AtRiskStudent`/`Overview` test fixtures that now miss the new fields; add the fields to those fixtures.

- [ ] **Step 5: Checkpoint**

Report paths. Do not commit.

---

### Task 10: Overview tile components

**Files:**
- Create: `web/src/portals/teacher/home/ReviewQueueTile.tsx`, `MarkClassSet.tsx`, `ClassStrip.tsx`, `AtRiskTable.tsx`, `home.css`
- Reference (read, do not import): `web/dev-previews/teacher-home.html`, `web/dev-previews/teacher-home/teacher-home.css` (the approved look)

**Interfaces:**
- Consumes: Task 9 models; `gradeChipClass` from Task 4.
- Produces:
  - `<ReviewQueueTile overview={Overview} />`
  - `<MarkClassSet lastUpload={string | null} onFiles={(files: File[]) => void} />`
  - `<ClassStrip classes={ClassSummary[]} />`
  - `<AtRiskTable students={AtRiskStudent[]} />`

- [ ] **Step 1: Keyframes and reduced motion**

`web/src/portals/teacher/home/home.css` (imported by `MarkClassSet.tsx`):

```css
@keyframes th-big { 0% { opacity: 0; transform: scale(0.6); } 40% { opacity: 1; transform: scale(1.05); } 100% { opacity: 0; transform: scale(1); } }
@keyframes th-draw { from { stroke-dashoffset: 30; } to { stroke-dashoffset: 0; } }
@keyframes th-chip { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
.th-received .th-big { animation: th-big 900ms var(--ease-expo) both; }
.th-received .th-big path { stroke-dasharray: 30; animation: th-draw 500ms 120ms var(--ease-expo) both; }
.th-received .th-got { animation: th-chip 350ms var(--ease-expo) both; }
@media (prefers-reduced-motion: reduce) {
  .th-received .th-big, .th-received .th-big path, .th-received .th-got { animation: none; }
}
```

- [ ] **Step 2: ReviewQueueTile**

```tsx
import { Link } from "react-router-dom"
import type { Overview } from "@/lib/teacherTypes"
import { ForwardArrow } from "@/components/ui/inline-arrow"
import { reviewQueueModel } from "./models"

export function ReviewQueueTile({ overview }: { overview: Overview }) {
  const m = reviewQueueModel(overview)
  return (
    <section aria-labelledby="rq-h" className="rounded-card bg-inverse-surface p-6 text-inverse-on-surface">
      <h2 id="rq-h" className="text-eyebrow text-inverse-primary">Review queue</h2>
      <div className="mt-3 grid grid-cols-[auto_1fr] items-end gap-6">
        <div>
          <p className="font-display text-[64px] font-extrabold leading-none tracking-[-0.03em] tabular-nums">{m.count}</p>
          {m.empty ? (
            <p className="mt-2 text-body-md">Nothing needs your eyes.</p>
          ) : (
            <p className="mt-2 text-body-md">
              answers below <span className="text-inverse-primary">70%</span> confidence.
              <span className="block text-body-sm opacity-80">None count until you confirm.</span>
            </p>
          )}
        </div>
        <figure aria-label="Pending answers by confidence" className="relative h-40">
          <div className="flex h-full items-end gap-1">
            {m.bars.map((b) => (
              <span key={b.band} className={b.low ? "flex-1 rounded-t-bar bg-error" : "flex-1 rounded-t-bar bg-inverse-primary"}
                style={{ height: `${Math.round(b.height * 100)}%` }} />
            ))}
          </div>
          <span aria-hidden className="absolute inset-y-0 left-[70%] border-l border-dashed border-inverse-on-surface/50" />
          <figcaption className="mt-1 flex justify-between text-data-sm opacity-80">
            <span>0%</span><span>confidence</span><span>100%</span>
          </figcaption>
        </figure>
      </div>
      {!m.empty && (
        <Link to="/teacher/review" className="mt-4 inline-flex items-center gap-1 font-bold text-inverse-primary">
          Open queue{m.estimate ? ` · ${m.estimate}` : ""}<ForwardArrow />
        </Link>
      )}
    </section>
  )
}
```

The bar heights are the one inline style: they are data, not design values.

- [ ] **Step 3: MarkClassSet**

```tsx
import { useRef, useState } from "react"
import { UploadSimple } from "@phosphor-icons/react"
import "./home.css"

const isPdf = (f: File) => f.type === "application/pdf" || /\.pdf$/i.test(f.name)

export function MarkClassSet({ lastUpload, onFiles }: { lastUpload: string | null; onFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [received, setReceived] = useState(false)
  const take = (list: FileList | null) => {
    const pdfs = [...(list ?? [])].filter(isPdf)
    if (!pdfs.length) return
    setReceived(true)
    window.setTimeout(() => onFiles(pdfs), 600)
  }
  return (
    <section aria-labelledby="mcs-h" className={`relative rounded-card bg-surface-container-lowest p-6 shadow-panel ${received ? "th-received" : ""}`}
      onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); take(e.dataTransfer.files) }}>
      <div className="flex items-baseline justify-between">
        <h2 id="mcs-h" className="text-eyebrow text-on-surface-variant">Mark a class set</h2>
        {received ? <span className="th-got text-data-md text-success">✓ Received</span>
          : lastUpload && <small className="text-body-sm text-on-surface-variant">Last: {lastUpload}</small>}
      </div>
      <div className="mt-4 grid place-items-center gap-3 rounded-tile border border-dashed border-outline p-8 text-center">
        <span aria-hidden className="grid size-11 place-items-center rounded-chip bg-primary-container text-on-primary-container"><UploadSimple size={20} /></span>
        <p className="text-display-xs">Drop papers anywhere on this page</p>
        <p className="max-w-[44ch] text-body-sm text-on-surface-variant">One PDF per student. Lemely reads each student's name off the paper.</p>
        <button type="button" onClick={() => input.current?.click()}
          className="inline-flex items-center gap-2 rounded-button bg-primary px-5 py-3 btn-text text-on-primary hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
          <UploadSimple size={16} />Upload papers
        </button>
        <input ref={input} type="file" accept="application/pdf" multiple hidden onChange={(e) => take(e.target.files)} />
      </div>
      <span aria-hidden className="pointer-events-none absolute inset-0 grid place-items-center">
        <svg className="th-big size-24 opacity-0" viewBox="0 0 24 24" fill="none" stroke="var(--md-success)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
      </span>
    </section>
  )
}
```

Check `@phosphor-icons/react` exports `UploadSimple` (it does in v2); if the project wraps icons in `web/src/components/ui`, use that wrapper instead.

- [ ] **Step 4: ClassStrip**

```tsx
import { Link } from "react-router-dom"
import type { ClassSummary } from "@/lib/teacherTypes"
import { classCardModel } from "./models"

export function ClassStrip({ classes }: { classes: ClassSummary[] }) {
  if (!classes.length) return null
  return (
    <section aria-labelledby="cs-h">
      <div className="flex items-baseline justify-between">
        <h2 id="cs-h" className="text-display-xs">Your classes</h2>
        <Link to="/teacher/classes" className="font-bold text-primary">All classes</Link>
      </div>
      <ul className="mt-3 flex snap-x gap-4 overflow-x-auto pb-2">
        {classes.map((c) => {
          const m = classCardModel(c)
          return (
            <li key={m.id} className="min-w-[280px] snap-start">
              <Link to={`/teacher/classes/${m.id}`} className="block rounded-tile bg-surface-container-lowest p-5 shadow-panel transition-shadow duration-150 hover:shadow-hover focus-visible:outline-2 focus-visible:outline-primary">
                <p className="font-bold">{m.title}</p>
                <p className="text-data-sm text-on-surface-variant">{m.meta}</p>
                {m.average && <p className="mt-2 text-data-md">Average {m.average}</p>}
                {m.weakTopic && <p className="mt-3 border-t border-outline-variant pt-3 text-body-sm">Weakest: {m.weakTopic}</p>}
              </Link>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
```

- [ ] **Step 5: AtRiskTable**

```tsx
import { Link } from "react-router-dom"
import type { AtRiskStudent } from "@/lib/teacherTypes"
import { gradeChipClass } from "@/lib/grade"
import { atRiskRowModel } from "./models"

export function AtRiskTable({ students }: { students: AtRiskStudent[] }) {
  return (
    <section aria-labelledby="ar-h" className="rounded-card bg-surface-container-lowest p-6 shadow-panel">
      <div className="flex items-baseline justify-between">
        <h2 id="ar-h" className="font-display text-[28px] font-extrabold tracking-[-0.03em]">
          At-risk students <span className="text-eyebrow text-on-surface-variant">{students.length} this week</span>
        </h2>
        <Link to="/teacher/at-risk" className="font-bold text-primary">View all</Link>
      </div>
      {students.length === 0 ? (
        <p className="mt-4 text-body-md text-on-surface-variant">No student is on a falling trend right now.</p>
      ) : (
        <ul className="mt-2">
          {students.slice(0, 4).map((s) => {
            const m = atRiskRowModel(s)
            return (
              <li key={m.name} className="[&+&]:border-t [&+&]:border-outline-variant">
                <Link to="/teacher/at-risk" className="group flex items-center gap-4 py-3 outline-offset-[-2px] transition-transform duration-150 hover:translate-x-1 focus-visible:outline-2 focus-visible:outline-primary">
                  <span aria-hidden className="grid size-10 place-items-center rounded-pill bg-primary-container font-bold text-on-primary-container transition-colors group-hover:bg-primary group-hover:text-on-primary">{m.initials}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-bold group-hover:underline">{m.name}</span>
                    <span className="block truncate text-body-sm text-on-surface-variant">{m.reason}</span>
                  </span>
                  {m.to && (
                    <span className="flex items-center gap-2" aria-label={m.from ? `${m.from} to ${m.to}` : m.to}>
                      {m.from && <span className={`grid size-9 place-items-center rounded-row font-display font-extrabold ${gradeChipClass(m.from)}`}>{m.from}</span>}
                      {m.from && <span aria-hidden className="text-on-surface-variant">→</span>}
                      <span className={`grid size-9 place-items-center rounded-row font-display font-extrabold ${gradeChipClass(m.to)}`}>{m.to}</span>
                    </span>
                  )}
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
```

If the at-risk list route supports a per-student anchor or the student detail route needs a student id (the overview DTO carries only `name`), keep the link at `/teacher/at-risk`; do not invent an id.

- [ ] **Step 6: Typecheck, lint, guard**

Run: `cd web && npm run typecheck && npm run lint && npx vitest run tests/unit/retiredTokens.test.ts tests/unit/utilityExistence.test.ts`
Expected: PASS.

- [ ] **Step 7: Checkpoint**

Report paths. Do not commit.

---

### Task 11: TeacherSetup, TeacherHome and routing

**Files:**
- Create: `web/src/portals/teacher/home/TeacherSetup.tsx`, `web/src/portals/teacher/home/TeacherHome.tsx`
- Modify: `web/src/portals/teacher/index.tsx` (the `Overview` lazy import at line 51, the index route, and `teacherFirstClassRedirect`)
- Modify: `web/src/portals/teacher/screens/Overview.tsx` (becomes the composed full home)
- Modify: `web/src/portals/teacher/screens/Grading.tsx` (accept files from router state)
- Modify: `web/tests/unit/teacherFirstRun.test.ts`
- Reference: `web/dev-previews/teacher-empty.html`, `web/dev-previews/teacher-home/teacher-empty.{css,js}`

**Interfaces:**
- Consumes: Tasks 9 and 10.
- Produces: `TeacherHome` default route component; router state `{ files: File[] }` on navigation to `/teacher/grading`.

Behaviour change to note in the checkpoint: the D7.10 gate that redirected a zero-class teacher to `/teacher/first-class` is replaced by the setup screen at `/teacher`, whose step 1 links to `/teacher/first-class`. The redirect function stays exported only if something else still calls it.

- [ ] **Step 1: Update the first-run test (failing)**

Replace the redirect assertions in `web/tests/unit/teacherFirstRun.test.ts` with the new rule, keeping the file's pending/error discipline:

```ts
import { describe, expect, it } from "vitest"
import { teacherHomeView } from "@/portals/teacher/home/TeacherHome"

describe("teacherHomeView", () => {
  const ready = { paperCount: 0, pendingReviewCount: 0 }
  it("waits while either query is pending", () => {
    expect(teacherHomeView("pending", 0, "success", ready)).toBe("loading")
    expect(teacherHomeView("success", 0, "pending", undefined)).toBe("loading")
  })
  it("shows an error, never setup, when a query failed", () => {
    expect(teacherHomeView("error", 0, "success", ready)).toBe("error")
    expect(teacherHomeView("success", 2, "error", undefined)).toBe("error")
  })
  it("shows setup for a zero-class teacher instead of redirecting", () => {
    expect(teacherHomeView("success", 0, "success", ready)).toBe("setup")
  })
  it("shows the overview once a class and a paper exist, even with items pending", () => {
    expect(teacherHomeView("success", 1, "success", { paperCount: 3, pendingReviewCount: 4 })).toBe("overview")
    expect(teacherHomeView("success", 1, "success", { paperCount: 0, pendingReviewCount: 0 })).toBe("setup")
  })
})
```

Run: `cd web && npx vitest run tests/unit/teacherFirstRun.test.ts` and expect FAIL.

**Rule and deviation (report to the user at the checkpoint).** The spec says setup shows "until all three steps are done". Read literally, a teacher who finished setup would fall back to the setup screen every time new review items arrive, because "reviewed" means "pending is 0". So the home shows `setup` while `!created || !uploaded`, and `overview` from then on. Step 3 ("Review flagged answers") stays visible on the setup screen as the next step, and is completed on the overview's review tile.

- [ ] **Step 2: TeacherHome**

```tsx
import { useNavigate } from "react-router-dom"
import { useTeacherClasses, useTeacherOverview } from "@/lib/hooks/useTeacherApi"
import type { Overview } from "@/lib/teacherTypes"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { deriveSetup } from "./setup"
import { TeacherSetup } from "./TeacherSetup"
import { Overview as OverviewScreen } from "../screens/Overview"

type Status = "pending" | "error" | "success"
export type HomeView = "loading" | "error" | "setup" | "overview"

export function teacherHomeView(
  classesStatus: Status, classCount: number, overviewStatus: Status,
  overview: Pick<Overview, "paperCount" | "pendingReviewCount"> | undefined,
): HomeView {
  if (classesStatus === "error" || overviewStatus === "error") return "error"
  if (classesStatus === "pending" || overviewStatus === "pending" || !overview) return "loading"
  const s = deriveSetup(classCount, overview)
  return s.created && s.uploaded ? "overview" : "setup"
}

export function TeacherHome() {
  const navigate = useNavigate()
  const classes = useTeacherClasses()
  const overview = useTeacherOverview()
  const view = teacherHomeView(classes.status, classes.data?.classes.length ?? 0, overview.status, overview.data)
  const toGrading = (files: File[]) => navigate("/teacher/grading", { state: { files } })
  if (view === "loading") return <RouteSkeleton />
  if (view === "error") {
    return (
      <div role="alert" className="rounded-card bg-error-container p-6 text-on-error-container">
        <p className="font-bold">We couldn't load your overview.</p>
        <button type="button" className="mt-3 font-bold underline" onClick={() => { void classes.refetch(); void overview.refetch() }}>Try again</button>
      </div>
    )
  }
  if (view === "setup") {
    return <TeacherSetup progress={deriveSetup(classes.data!.classes.length, overview.data!)} firstClass={classes.data!.classes[0] ?? null} onFiles={toGrading} />
  }
  return <OverviewScreen overview={overview.data!} classes={classes.data!.classes} onFiles={toGrading} />
}
```

Check `RouteSkeleton`'s props (it is used in `index.tsx`); pass what it needs.

- [ ] **Step 3: TeacherSetup**

Port `teacher-empty.html` structure and `teacher-empty.css` styles to utilities. Props: `{ progress: SetupProgress; firstClass: ClassSummary | null; onFiles: (files: File[]) => void }`.

```tsx
import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { Check, Plus, UploadSimple } from "@phosphor-icons/react"
import type { ClassSummary } from "@/lib/teacherTypes"
import type { SetupProgress } from "./setup"
import "./home.css"

const STEPS = [
  { key: "created", title: "Create a class", what: "Get a join code to share with your students." },
  { key: "uploaded", title: "Upload papers", what: "A whole class set at once, as PDFs." },
  { key: "reviewed", title: "Review flagged answers", what: "Check the answers Lemely is unsure about." },
] as const

const isPdf = (f: File) => f.type === "application/pdf" || /\.pdf$/i.test(f.name)

export function TeacherSetup({ progress, firstClass, onFiles }: { progress: SetupProgress; firstClass: ClassSummary | null; onFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [nudge, setNudge] = useState(0)
  const [copied, setCopied] = useState(false)
  const current = STEPS.findIndex((s) => !progress[s.key])

  const upload = (list: FileList | File[] | null) => {
    const pdfs = [...(list ?? [])].filter(isPdf)
    if (!pdfs.length) return
    if (!progress.created) { setNudge((n) => n + 1); return }
    onFiles(pdfs)
  }

  useEffect(() => {
    const over = (e: DragEvent) => e.preventDefault()
    const drop = (e: DragEvent) => { e.preventDefault(); upload(e.dataTransfer?.files ?? null) }
    window.addEventListener("dragover", over)
    window.addEventListener("drop", drop)
    return () => { window.removeEventListener("dragover", over); window.removeEventListener("drop", drop) }
  })

  const copy = async (code: string) => {
    try { await navigator.clipboard.writeText(code) } catch { /* clipboard blocked: the code is still visible */ }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="grid gap-8">
      <header className="rounded-card bg-inverse-surface p-8 text-inverse-on-surface">
        <p className="text-eyebrow text-inverse-primary">Every mark, explained.</p>
        <h1 className="mt-2 font-display text-[40px] font-extrabold leading-[1.05] tracking-[-0.03em]">Mark your first class set</h1>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link to="/teacher/first-class" className="inline-flex items-center gap-2 rounded-button bg-inverse-primary px-5 py-3 btn-text text-primary">Create a class</Link>
          <button type="button" onClick={() => (progress.created ? input.current?.click() : setNudge((n) => n + 1))}
            className="rounded-button border border-inverse-on-surface/40 px-5 py-3 btn-text">Upload papers</button>
        </div>
      </header>

      <section aria-labelledby="gs-h">
        <div className="flex items-baseline justify-between">
          <h2 id="gs-h" className="text-display-xs">Get started</h2>
          <span aria-live="polite" className="text-data-md text-on-surface-variant">{progress.complete ? "All set" : `${progress.done} of 3 done`}</span>
        </div>
        <div aria-hidden className="mt-3 h-2 overflow-hidden rounded-bar bg-surface-container-high">
          <i className="block h-full origin-left bg-primary transition-transform duration-350 ease-expo" style={{ transform: `scaleX(${progress.done / 3})` }} />
        </div>
        <ol className="mt-4 grid gap-3">
          {STEPS.map((s, i) => {
            const done = progress[s.key]
            const now = i === current
            return (
              <li key={now ? `${s.key}-${nudge}` : s.key}
                className={`flex gap-4 rounded-tile p-5 ${now ? "bg-surface-container-lowest shadow-panel" : "bg-surface-container-low"} ${now && nudge ? "animate-[em-nudge_400ms_var(--ease-expo)] motion-reduce:animate-none" : ""}`}>
                <span className={`grid size-8 shrink-0 place-items-center rounded-pill font-bold ${done ? "bg-primary text-on-primary" : now ? "bg-primary-container text-on-primary-container" : "bg-surface-container-high text-on-surface-variant"}`}>
                  {done ? <Check size={16} weight="bold" aria-label="Done" /> : i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="font-bold">{s.title}</h3>
                  {s.key === "created" && done && firstClass?.joinCode ? (
                    <p className="text-body-sm text-on-surface-variant">
                      {firstClass.label} · join code <code className="text-data-md text-on-surface">{firstClass.joinCode}</code>{" "}
                      <button type="button" onClick={() => void copy(firstClass.joinCode!)} className="font-bold text-primary">{copied ? "Copied" : "Copy"}</button>
                    </p>
                  ) : (
                    <p className="text-body-sm text-on-surface-variant">{s.what}</p>
                  )}
                  {now && s.key === "created" && (
                    <Link to="/teacher/first-class" className="mt-3 inline-flex items-center gap-2 rounded-button bg-primary px-4 py-2.5 btn-text text-on-primary hover:bg-primary-hover"><Plus size={16} />Create a class</Link>
                  )}
                  {now && s.key === "uploaded" && (
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      <button type="button" onClick={() => input.current?.click()} className="inline-flex items-center gap-2 rounded-button bg-primary px-4 py-2.5 btn-text text-on-primary hover:bg-primary-hover"><UploadSimple size={16} />Upload papers</button>
                      <span className="text-body-sm text-on-surface-variant">or drop them anywhere on this page</span>
                    </div>
                  )}
                  {now && s.key === "reviewed" && (
                    <Link to="/teacher/review" className="mt-3 inline-flex rounded-button bg-primary px-4 py-2.5 btn-text text-on-primary hover:bg-primary-hover">Open review queue</Link>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      </section>
      <input ref={input} type="file" accept="application/pdf" multiple hidden onChange={(e) => upload(e.target.files)} />
    </div>
  )
}
```

Keying the current step by the nudge counter remounts it on each nudge, so the animation replays. Add the keyframe to `home.css`:

```css
@keyframes em-nudge { 0%, 100% { transform: none; } 25% { transform: translateX(-4px); } 75% { transform: translateX(4px); } }
```

The prototype's join-code "settle" scramble applies only at the moment a class is created, which now happens on `/teacher/first-class`. Port it there only if `CreateFirstClass.tsx` shows the new code after creation; otherwise drop it and say so in the checkpoint.

- [ ] **Step 4: Compose the full Overview**

Rewrite `web/src/portals/teacher/screens/Overview.tsx` to a presentational component with props `{ overview: Overview; classes: ClassSummary[]; onFiles: (files: File[]) => void }`:

```tsx
import type { ClassSummary, Overview as OverviewDTO } from "@/lib/teacherTypes"
import { ReviewQueueTile } from "../home/ReviewQueueTile"
import { MarkClassSet } from "../home/MarkClassSet"
import { ClassStrip } from "../home/ClassStrip"
import { AtRiskTable } from "../home/AtRiskTable"

/** Teacher home (T-01), v5 Abyss. Data comes from TeacherHome; this file only lays it out. */
export function Overview({ overview, classes, onFiles }: { overview: OverviewDTO; classes: ClassSummary[]; onFiles: (files: File[]) => void }) {
  const last = overview.recentActivity[0]
  const lastUpload = last ? `${last.subjectCode} · ${new Date(last.recordedAt).toLocaleDateString(undefined, { weekday: "short" })}` : null
  return (
    <div className="grid gap-8">
      <div className="grid gap-6 lg:grid-cols-2">
        <ReviewQueueTile overview={overview} />
        <MarkClassSet lastUpload={lastUpload} onFiles={onFiles} />
      </div>
      <ClassStrip classes={classes} />
      <AtRiskTable students={overview.atRisk} />
    </div>
  )
}
```

The old file's docstring lists five contents from `docs/LEMELY_UI_SPEC.md` §4.7 T-01, including recent activity. Recent activity now appears only as "Last:" on the drop zone. Note this in the checkpoint so the user can decide whether T-01 item 4 needs its own block.

- [ ] **Step 5: Route it**

In `web/src/portals/teacher/index.tsx`, change line 51 to lazy-load `TeacherHome`:

```tsx
const Overview = lazy(() => import("./home/TeacherHome").then((m) => ({ default: m.TeacherHome })))
```

Find where `TeacherLayout` calls `teacherFirstClassRedirect` and remove that redirect branch (setup now covers it). If no other caller remains, delete the function.

- [ ] **Step 6: Grading accepts handed-over files**

In `Grading.tsx`, read `useLocation().state?.files` once on mount and pass them to the same handler the file `<input>` at line 689 uses. Then clear the state with `navigate(".", { replace: true, state: null })` so a reload does not re-submit.

- [ ] **Step 7: Run**

Run: `cd web && npx vitest run tests/unit/teacherFirstRun.test.ts tests/unit/teacherSetup.test.ts tests/unit/teacherHomeModels.test.ts && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 8: Checkpoint**

Report paths and the three noted deviations (setup rule, recent activity, join-code settle). Do not commit.

---

### Task 12: Teacher shell (sidebar and top bar)

**Files:**
- Modify: `web/src/portals/teacher/index.tsx` (`TeacherLayout`), `web/src/portals/teacher/data.ts` (nav labels), `web/src/components/ui/nav-shells.tsx` only if its styles are teacher-specific

**Interfaces:**
- Consumes: `useTeacherClasses`, `useReviewQueueCount` (already imported in `index.tsx`).

- [ ] **Step 1: Sidebar**

Match `teacher-home.html`'s sidebar: Clip Letters wordmark at the top, primary nav (Overview, Grading, Review with count, Classes, At-risk students with count), a `text-eyebrow` "Your classes" heading listing each class with a grade chip and student count, a "Tools" group (Mark schemes, AI quizzes, Announcements), and a full-width primary "Upload papers" button pinned to the bottom. Nav item classes:

```
flex items-center gap-2.5 rounded-chip px-2.5 py-2 text-[14px] font-semibold text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface aria-[current=page]:bg-primary-container aria-[current=page]:text-primary
```

Count badge: `ml-auto rounded-pill bg-surface-container-high px-1.5 text-data-sm text-on-surface` and `bg-primary text-on-primary` when active or urgent. Rename any "Your groups" label in `data.ts` to "Your classes".

- [ ] **Step 2: Top bar**

Page title in `text-[19px] font-extrabold tracking-[-0.04em]`; a tonal "Create" button (`bg-secondary-container text-on-secondary-container`), primary "Upload papers", then icon buttons in `text-on-surface-variant` that turn `text-on-surface` on hover, all with `focus-visible:outline-2 focus-visible:outline-primary`. The bar keeps 28px side margins; the content well 72px (`px-7` and `px-[72px]` at `lg`, falling back to 16px gutters below `md`).

- [ ] **Step 3: Run**

Run: `cd web && npx vitest run tests/unit/navShells.test.ts tests/unit/retiredTokens.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 4: Checkpoint**

Report paths. Do not commit.

---

### Task 13: Verify end to end

**Files:** none created (screenshots go to the scratchpad and are deleted after review)

- [ ] **Step 1: All web gates**

Run: `cd web && npm run typecheck && npx vitest run && npm run lint && npm run check:copy && npm run build`
Expected: all PASS.

- [ ] **Step 2: Touched Python tests**

Run: `pytest tests/test_design_tokens.py tests/test_web_teacher_overview_fields.py tests/test_web_teacher.py -k "overview or design" -q && ruff check . && mypy lemely/web`
Expected: PASS.

- [ ] **Step 3: Screenshots**

Start the app (`cd web && npm run dev`) against the dev API with a seeded teacher, and capture `/teacher` in the setup state and the full state, plus one screen per portal (`/student`, `/parent`, `/admin`, `/login`, `/`), light and dark, at 1440 and 375 wide. Compare the teacher screens to `web/dev-previews/teacher-home.html` and `teacher-empty.html`. Check: no Study Notebook surface remains, no horizontal scroll at 375, focus rings visible, Binny absent outside student and marketing.

- [ ] **Step 4: Report**

Summarise to the user: gates run and results, screenshots reviewed, the deviations recorded in Tasks 4, 6 and 11, and anything left. Do not commit; offer to commit (signed, `pre-commit run --all-files` first) if they want it.
