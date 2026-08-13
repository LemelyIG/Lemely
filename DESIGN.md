# DESIGN.md — The Study Notebook

> **Read this file before emitting any UI.** It is the single source of truth for
> Lemely's visual system. `BUILD/BRAND.md` owns *meaning*; this file owns *values*.
> Where they disagree on a value, this file wins; on meaning, BRAND.md wins.
>
> Supersedes the build-era "Academic Warmth" system (a Material-3 palette
> generated before the Study Notebook direction existed). Nothing from that
> palette survives except the semantic *names*, which are deliberately reused so
> the ~20 components already consuming them keep working while surfaces are
> migrated one at a time in Phase 4.
>
> Authority: `BUILD/REDESIGN-MISSION.md` §3 (skill conflicts, pre-resolved) and
> §4 (the direction, not re-openable). `design-system/lemely/MASTER.md` is
> research input that was mined and mostly rejected; it is never a second source
> of truth.

---

## 1. Genre and the one protected quality

**Genre:** warm editorial product UI. Notion's calm information density crossed
with the physical artefact the product is actually about, a student's exam
paper and the teacher's marks on it.

**The one protected quality** (REDESIGN-MISSION §1): the warmth and
notebook/sketchbook feel. Every other visual decision is replaceable. This is
what the texture layer (§8) exists to protect, and it is the thing to check
first when a surface feels wrong.

**Hard anti-references.** Generic SaaS: dense bootstrap-coloured dashboards,
purple-blue gradients, cookie-cutter card grids, dark glass "AI product"
aesthetic. If an emitted screen would look at home in a Y-Combinator batch
screenshot, it is wrong.

**The tone in one sentence.** A beautifully kept notebook that happens to be
alive: warm paper, ink, hairlines, marginalia, sticker-like pastel tags, and
quiet motion, with expressive celebration reserved for genuine wins.

---

## 2. Macrostructure per lane

Three lanes, from `PRODUCT.md`. Each gets its own page skeleton; all three share
the token system, and per-surface variation happens only through §13's knobs.

### Persuade — marketing, landing, public pages
Full-bleed warm paper, generous macro-whitespace (96–128px between sections),
asymmetric and deliberately broken symmetry, one idea per section. Section
rhythm: hero → proof → the loop → who it serves → plans → close. Wide container
(1200–1440px). Display type does the work; imagery is real screenshots in a
`<figure>` with a hairline border, never hand-drawn browser chrome.

### Operate — dashboards, marking, teacher and parent and admin tools
Sidebar plus content well. Content max-width 1200px, sidebar 240–280px fixed.
Scanability and task speed outrank expression: tabular numbers, consistent row
rhythm, a single obvious primary action per screen. Brand lives in the details
here (subject colours, marginalia in empty states, the celebration register on
wins), never in decoration that costs a teacher a second.

### Read — study content, flashcards, worksheets, explanations
Single centred column, body max 65ch, line-height 1.6, ruled-paper background
option on. This lane is the closest to literal paper and may use the texture
layer most heavily. No sidebar; navigation collapses to a back path and progress.

---

## 3. Colour tokens (OKLCH)

OKLCH throughout, so lightness is perceptually uniform and a future dark theme
is a lightness inversion rather than a re-pick. **Light mode only ships now**
(§3.2 item 8); the scale is built so dark is a token swap, but dark is not
implemented and not tested.

Every value below is a token. Raw hex, `rgb()`, or `oklch()` written inline in a
component is a gate failure (§3.2 item 13); lift the value here first.

### 3.1 Paper (canvas and surfaces)

| Token | OKLCH | ≈ hex | Use |
|---|---|---|---|
| `--paper` | `oklch(0.976 0.004 85)` | `#F8F7F4` | The page. The default background of everything. |
| `--paper-raised` | `oklch(0.992 0.003 85)` | `#FDFCFA` | Cards and panels sitting on the page. Slightly *lighter* than the canvas, the way a sheet laid on a desk catches more light. |
| `--paper-sunk` | `oklch(0.952 0.006 85)` | `#F1EFEB` | Wells: sidebars, table headers, code blocks, inset areas. |
| `--paper-inverse` | `oklch(0.28 0.008 250)` | `#26292D` | The one dark surface permitted, for a single proof/close band on marketing only. Never a dark section inside an app screen. |

Never pure `#FFF` and never pure `#000`. Both read as sterile and break the
paper illusion instantly.

### 3.2 Ink (text)

| Token | OKLCH | ≈ hex | Use | Measured on `--paper` |
|---|---|---|---|---|
| `--ink` | `oklch(0.321 0.009 234)` | `#2F3437` | Primary text, headings, the logo mark. | 11.6:1 |
| `--ink-muted` | `oklch(0.48 0.006 240)` | `#5B5E61` | Secondary text, descriptions, inactive nav. | 6.09:1 |
| `--ink-faint` | `oklch(0.529 0.006 240)` | `#696C6F` | Captions, metadata, timestamps. The floor. | 4.94:1 |
| `--ink-inverse` | `oklch(0.97 0.004 85)` | `#F6F5F2` | Text on `--paper-inverse` or on a filled accent. | 13.37:1 on inverse |

Every ratio in that table is **measured**, not estimated, by converting the
OKLCH value to sRGB and applying the WCAG relative-luminance formula. `--ink` is
exactly the logo's ink, derived by converting `#2F3437` to OKLCH rather than
eyeballed, so the mark and the interface are literally the same colour.

`--ink-faint` is the lightest text token that exists. It is set at L 0.529
rather than anything lighter for a specific reason: it must clear AA against
`--paper-sunk` (`#F1EFEB`), the *darkest* surface it ever sits on, not just
against `--paper`. At L 0.529 it measures **4.94:1 on `--paper`, 5.17:1 on
`--paper-raised`, and 4.60:1 on `--paper-sunk`** — all three clear. An earlier
draft of this file had it at L 0.575, which measured 4.08:1 and 3.80:1 and
would have shipped a system-wide AA failure on every caption in the product.

There is deliberately no fifth, lighter step. The build-era system had one and
spent three separate rounds failing and re-nudging AA on it, each round fixing
one surface and leaving another broken. If text needs to recede further than
`--ink-faint`, make it smaller or move it. Do not make it lighter.

### 3.3 Rules (hairlines)

| Token | OKLCH | ≈ hex | Use |
|---|---|---|---|
| `--rule` | `oklch(0.905 0.004 85)` | `#E1DFDD` | The default 1px border. Cards, inputs, dividers, table rows. |
| `--rule-strong` | `oklch(0.845 0.005 85)` | `#CDCCC8` | Emphasis borders, focused input rest state, header underlines. |
| `--rule-faint` | `oklch(0.945 0.003 85)` | `#EEEDEA` | Ruled-paper lines, dotted grids, the texture layer. |

Borders are the primary containment strategy. Shadows are not (§7).

### 3.4 Accent

One accent, warm and slightly desaturated, taken directly from the logo mark so
the brand and the UI are literally the same red.

| Token | OKLCH | ≈ hex | Use |
|---|---|---|---|
| `--accent` | `oklch(0.576 0.146 33)` | `#C0523D` | Primary buttons, active nav, links, the logo tick, the teacher's mark. |
| `--accent-hover` | `oklch(0.505 0.132 34)` | `#A2422D` | Hover and pressed states of accent fills. |
| `--accent-wash` | `oklch(0.945 0.028 34)` | `#FFE7E1` | Tinted backgrounds: selected rows, highlight bands, tag fills. |
| `--accent-ink` | `oklch(0.38 0.10 34)` | `#6E2A1B` | Accent-coloured *text* on paper or on `--accent-wash`. |
| `--accent-on` | `#FFFFFF` | `#FFFFFF` | Text and icons **on** an `--accent` fill. Nothing else. |

`--accent` is derived by converting the logo's `#C0523D` to OKLCH, so the mark's
tick and the product's primary button are the same red by construction rather
than by eye.

Three accent values, because three different jobs have three different contrast
requirements, all measured:

- **`--accent` measures 4.34:1 on `--paper`.** That clears AA for large text (≥18.66px, or ≥14px bold) and for graphics and UI components, so it is correct for a filled button, an icon, or the logo tick. It is **not** correct for body copy or small labels.
- **`--accent-ink` measures 9.75:1 on `--paper` and 8.84:1 on `--accent-wash`.** Use it for any accent-coloured text below the large-text threshold. `--accent-hover` is also safe as text at 5.85:1 if a darker fill is wanted.
- **`--accent-on` is the one place pure white is permitted in this system.** It measures **4.65:1** on an `--accent` fill and clears AA for normal text, which matters because button labels are `label` (13px/500), i.e. normal text, not large. `--ink-inverse` was tried here first and measures only **4.27:1**, which fails. Do not substitute it back.

The §3.1 ban on pure white governs *surfaces* (a white canvas reads sterile and
kills the paper illusion). It does not govern a label sitting on a saturated
fill, where the only question is legibility.

### 3.5 Pastels

The sticker set. Washed fills with a dark text pair each, for tags, subject
coding, and inline highlights. Every pair is AA on its own fill.

| Name | Fill | Text on fill | hex fill / text | Measured |
|---|---|---|---|---|
| `--pastel-rose` | `oklch(0.94 0.032 20)` | `oklch(0.42 0.11 20)` | `#FFE3E2` / `#7E2F33` | 7.41:1 |
| `--pastel-amber` | `oklch(0.945 0.045 85)` | `oklch(0.42 0.08 70)` | `#FBEBCB` / `#694413` | 7.32:1 |
| `--pastel-sage` | `oklch(0.94 0.032 155)` | `oklch(0.40 0.07 160)` | `#DBF2E2` / `#1F533A` | 7.54:1 |
| `--pastel-sky` | `oklch(0.94 0.030 235)` | `oklch(0.42 0.08 240)` | `#D9EFFD` / `#1B5274` | 7.05:1 |
| `--pastel-lilac` | `oklch(0.94 0.030 300)` | `oklch(0.42 0.08 300)` | `#EEE7FD` / `#544272` | 7.27:1 |
| `--pastel-clay` | `oklch(0.94 0.022 55)` | `oklch(0.42 0.06 50)` | `#F8E8DE` / `#68432F` | 7.22:1 |

Last column is the measured ratio of each pair's text on its own fill. Every
pastel text colour is also AA on `--paper` (7.80:1 to 8.36:1), so a tag's label
stays legible if the fill is ever dropped.

Lilac is the one hue that must never be used for a primary action, a chart's
first series, or anything AI-adjacent. It exists for subject coding only. The
purple-blue AI gradient is a firing offence (§3.2 item 7) and lilac is the
nearest legal neighbour to it.

### 3.6 Semantic states

Deliberately **not** green/amber/red. Teal replaces green so the
success/error pair stays distinguishable under deuteranopia and protanopia,
which pure green against red does not. This was a real decision in the build-era
system and it is carried forward on purpose.

| Token | Text | Fill | Measured on fill | Use |
|---|---|---|---|---|
| `--ok` / `--ok-wash` | `oklch(0.48 0.075 175)` `#256B5B` | `oklch(0.945 0.030 175)` `#D9F4EC` | 5.41:1 | Correct, complete, saved, on track. |
| `--warn` / `--warn-wash` | `oklch(0.45 0.085 70)` `#734C17` | `oklch(0.945 0.045 85)` `#FBEBCB` | 6.45:1 | Partial credit, uncertain, borderline, needs attention. |
| `--err` / `--err-wash` | `oklch(0.38 0.145 27)` `#7E0D10` | `oklch(0.94 0.035 27)` `#FFE3DF` | 8.86:1 | Wrong, failed, destructive, blocked. |
| `--info` / `--info-wash` | `oklch(0.44 0.080 240)` `#22587A` | `oklch(0.94 0.030 235)` `#D9EFFD` | 6.47:1 | Neutral notices, tips, "how this works". |

Every semantic text colour is also AA on `--paper` (5.38:1 to 10.04:1) and on
`--paper-sunk`.

**The lightness ladder is deliberate and load-bearing.** `--ok`, `--warn` and
`--err` descend in relative luminance (0.117 → 0.089 → 0.048), so the three
states remain distinguishable when hue is removed entirely: in greyscale, for a
colour-blind reader, or on a bad projector. An earlier draft of this file set
all three at roughly L 0.45, which read as three identical greys and made the
teal-not-green decision above pointless. If one of these values is ever
adjusted, the ordering must be preserved; a test enforces it
(`tests/test_design_tokens.py`).

**Colour never carries meaning alone.** Every state pairs its colour with an
icon or a text label. A student who cannot distinguish the teal from the red
must still be able to read their paper.

### 3.7 Product scales

These three scales are load-bearing product semantics, not decoration. They
carry over from the build-era system with their meaning intact and their values
re-pointed at the new palette.

**Confidence** (how sure the marker is). Three tiers, separated by hue *and* a
monotonic lightness step so the ladder survives greyscale:

| Tier | Text | Wash | Meaning |
|---|---|---|---|
| `--confidence-high` | `--ok` | `--ok-wash` | Confident. |
| `--confidence-medium` | `--warn` | `--warn-wash` | Uncertain, re-marked or flagged. |
| `--confidence-low` | `--err` | `--err-wash` | Below the review floor, a teacher is asked. |

**Marking** (what happened to this mark): `--mark-correct` = `--ok`,
`--mark-partial` = `--warn`, `--mark-wrong` = `--err`. Always paired with a
distinct glyph (check, half-circle, cross), never colour alone.

**Grade bands**, grouped across A*–G/U so a badge never reads as a button
(hence: never `--accent`):

| Band | Grades | Text / wash |
|---|---|---|
| `--grade-top` | A*, A, B | `--ok` / `--ok-wash` |
| `--grade-mid` | C, D | `--pastel-clay` text / fill |
| `--grade-borderline` | E | `--warn` / `--warn-wash` |
| `--grade-fail` | F, G, U | `--err` / `--err-wash` |

### 3.8 Subject colours

Semantic, not decorative: a student scanning a dashboard should find Physics by
colour before reading. Assign from the pastel set, fixed:

| Subject | Pastel |
|---|---|
| Mathematics | `--pastel-sky` |
| Physics | `--pastel-lilac` |
| Chemistry | `--pastel-sage` |
| Biology | `--pastel-clay` |
| English | `--pastel-amber` |
| Unassigned / other | `--pastel-rose` |

New subjects extend this table here first. Never pick a subject colour at a call
site.

### 3.9 Focus

| Token | Value |
|---|---|
| `--focus-ring` | `oklch(0.50 0.14 240)` `#006AAA` (5.37:1 on `--paper`) |
| `--focus-ring-offset` | `--paper` |

Focus is a 2px solid ring at 2px offset, **deliberately blue** rather than the
accent: it must be distinguishable from the accent's own hover and selected
states, and it must read as "the browser is talking to you" rather than as
brand. `:focus-visible` only, never `:focus` (no rings on mouse click). It is
never removed, on any element, for any reason.

---

## 4. Typography

Four faces, each with exactly one job. Weights 400/500/600 are all in play;
400/700 alone is a build-era habit and reads generic.

| Role | Face | Package | Weights | Job |
|---|---|---|---|---|
| Display | **Newsreader Variable** | `@fontsource-variable/newsreader` | 400, 500, 600 (+ italic) | Headings, hero, section titles, big numbers on marketing. |
| UI / body | **Geist Variable** | `@fontsource-variable/geist` | 400, 500, 600 | Everything interface: body, buttons, nav, labels, forms. |
| Data | **JetBrains Mono Variable** | `@fontsource-variable/jetbrains-mono` | 400, 500 | All scores, grades, marks, XP, timers, paper codes, IDs. Always `font-variant-numeric: tabular-nums`. |
| Marginalia | **Caveat Variable** | `@fontsource-variable/caveat` | 400, 600 | Annotation moments only. See the hard rule below. |

**Banned faces, everywhere, no exceptions:** Inter, Roboto, Arial, Open Sans,
Helvetica. All nine skills agree and §3.2 item 2 makes it law.

**Why Newsreader and not Instrument Serif** (which the build-era system used and
which is already installed): Instrument Serif ships a single 400 weight with no
bold. That forces every heading hierarchy to be built from size alone, which is
exactly why the build-era teacher portal invented six ad-hoc sizes across
eighteen screens. Newsreader is a variable serif drawn for screen reading, it is
warmer and more bookish than Instrument Serif's high-fashion contrast, and it
gives the 500 and 600 the scale below actually needs.

### 4.1 The Caveat rule (hard)

Caveat is a decorative layer, never an information layer.

- **Permitted:** empty-state marginalia, a "nice work" note beside a result, decorative annotations pointing at a chart, sticker captions.
- **Forbidden:** headings, buttons, labels, form fields, table content, error messages, navigation, and anything a screen reader must announce as meaningful.
- If the text would be a problem to lose, it is not Caveat.

Caveat has poor legibility at small sizes and near-zero legibility for dyslexic
readers. It decorates; it never carries.

### 4.2 Type scale

Sizes in px for precision. Every rung names its face, so a rung cannot be used
with the wrong family.

| Token | Face | Size | Line-height | Tracking | Weight | Use |
|---|---|---|---|---|---|---|
| `display-hero` | Newsreader | 60 | 1.05 | -0.015em | 400 | Marketing hero only. One per page. |
| `display-xl` | Newsreader | 44 | 1.08 | -0.01em | 400 | Marketing section openers. |
| `display-lg` | Newsreader | 32 | 1.12 | -0.005em | 400 | Page titles in-app. |
| `display-md` | Newsreader | 24 | 1.18 | 0 | 500 | Section headings, card titles. |
| `display-sm` | Newsreader | 19 | 1.25 | 0 | 500 | Sub-section headings. |
| `body-lg` | Geist | 15 | 1.6 | 0 | 400 | Default body. Max 65ch. |
| `body-md` | Geist | 14 | 1.55 | 0 | 400 | Dense body, table cells, descriptions. |
| `body-sm` | Geist | 13 | 1.5 | 0 | 400 | Captions, helper text, secondary rows. |
| `label` | Geist | 13 | 1 | 0 | 500 | Buttons, form labels, nav items. |
| `eyebrow` | Geist | 11 | 1 | 0.1em | 600 | Uppercase kickers above headings. |
| `data-lg` | JetBrains Mono | 32 | 1 | -0.01em | 500 | The big number: a score, a predicted grade. |
| `data-md` | JetBrains Mono | 15 | 1.2 | 0 | 500 | Inline figures, marks, XP. |
| `data-sm` | JetBrains Mono | 11 | 1 | 0.05em | 500 | Paper codes, IDs, timestamps, metadata. |
| `hand` | Caveat | 19 | 1.35 | 0 | 400 | Marginalia. See §4.1. |

**Mobile.** `display-hero` → 38px, `display-xl` → 30px, `display-lg` → 26px
below 768px. Everything else holds; the body scale is already comfortable on a
phone and shrinking it is how learning platforms become unreadable on the device
students actually use.

**Rules.** Sentence case for all headings. Body copy never below 13px. No italic
display headings and no italic emphasis inside a heading (§3.2 item 12);
emphasis is weight, accent colour, or a drawn underline. Italic is body-copy
only, plus Caveat, which is its own thing.

---

## 5. Spacing

Base unit **4px**. The scale is the set of values allowed; a value outside it
gets added here or is wrong.

| Token | px | Typical |
|---|---|---|
| `space-1` | 4 | Icon-to-label gap. |
| `space-2` | 8 | Tight stacks, chip padding. |
| `space-3` | 12 | Related elements. |
| `space-4` | 16 | Default gap between components. |
| `space-5` | 20 | Card internal padding, compact. |
| `space-6` | 24 | Card internal padding, default. Grid gutter. |
| `space-8` | 32 | Between cards, between form groups. |
| `space-10` | 40 | Card padding, generous (marketing). |
| `space-12` | 48 | Sub-section separation. |
| `space-16` | 64 | Section separation, in-app. |
| `space-24` | 96 | Section separation, marketing. |
| `space-32` | 128 | Hero breathing room, marketing only. |

Card internal padding is **24–40px** (§4). Cramped padding is the single
fastest way to lose the notebook feel; when in doubt go up one rung.

**Containers.** Marketing 1280px max. App content 1200px max. Read lane 680px
max (65ch at `body-lg`). Page gutter 32px desktop, 20px tablet, 16px mobile.

---

## 6. Radius

| Token | px | Use |
|---|---|---|
| `radius-sm` | 4 | Chips, tags, small inline elements. |
| `radius-md` | 8 | Buttons, inputs, selects. |
| `radius-lg` | 12 | Cards, panels, table containers. |
| `radius-xl` | 16 | Modals, large feature containers. |
| `radius-full` | 9999 | Pills and circles. **Tags and status badges only.** |

**Buttons are never pills** (§3.2 item 4). `radius-full` on an interactive
element is a gate failure, with two exceptions: avatars (which are squircles,
see below) and true icon-only circular controls like a close button.

**Avatars are squircles**, `radius-lg` on a square, not circles. Circles are
reserved for live/status dots so a dot never reads as a person.

---

## 7. Elevation

Flat. Depth comes from tonal layering (`--paper-sunk` < `--paper` <
`--paper-raised`) and 1px `--rule` borders.

- **Resting cards have no shadow.** Ever.
- Floating layers only — popovers, dropdowns, modals, toasts — may use `shadow-float`: `0 4px 16px oklch(0.30 0.006 240 / 0.05), 0 1px 3px oklch(0.30 0.006 240 / 0.04)`. Ultra-diffuse, ≤0.05 opacity.
- Modal scrim: `oklch(0.30 0.006 240 / 0.28)`.
- **Glassmorphism is banned** except a `backdrop-blur(10px)` on the fixed navbar. Never on scrolling content: it is a real performance cost on the mid-range Android phones students use.
- **Gradients are banned** as visible elements. Permitted only as ambient warmth: a radial light spot at ≤0.04 opacity behind a hero or section.

### Z-index scale
Only these values. A raw `z-index` outside the scale is a gate failure.

| Token | Value | Layer |
|---|---|---|
| `z-base` | 0 | Page content. |
| `z-sticky` | 10 | Sticky table headers, section headers. |
| `z-nav` | 20 | Fixed navbar, sidebar. |
| `z-dropdown` | 30 | Popovers, selects, tooltips. |
| `z-scrim` | 40 | Modal backdrop. |
| `z-modal` | 50 | Dialogs, sheets. |
| `z-toast` | 60 | Toasts. Above everything, always. |

---

## 8. The notebook texture layer

This is how the protected quality (§1) survives contact with a dashboard. It is
also the easiest thing in this system to overdo.

**The restraint rule: marginalia decorates, never carries meaning alone.**
Remove every texture element and the product must still be fully usable and
fully understandable. If removing a doodle loses information, it was not a
doodle.

1. **Paper grain.** One fixed, `pointer-events: none`, full-viewport SVG noise overlay at **≤0.04 opacity**. Fixed, so it never repaints on scroll.
2. **Ruled and dotted backgrounds.** `--rule-faint` horizontal lines at 32px, or a 24px dot grid. For section backgrounds and the Read lane. Never behind body text at more than 0.5 opacity.
3. **Hand-drawn accents.** SVG underlines, circles, and arrows in `--accent` or `--ink`, slightly irregular. Budget: **at most two per viewport.** They punctuate; they are not a pattern.
4. **Sticker badges.** Achievements and streak milestones as pastel-filled, slightly rotated (±2°) badges with `radius-sm`. Rotation only on genuinely decorative badges, never on a status chip that must be scanned.
5. **Margin rule.** A single `--rule` vertical hairline at the content's inline start, echoing the logo. The cheapest and most on-brand texture available. Prefer it over a doodle.

**Reduced motion and print:** the grain and doodles are decorative, so they are
hidden under `prefers-reduced-motion` only if animated (they should not be), and
always hidden in print styles.

---

## 9. Motion

Baseline is **invisible**. The user should feel the interface is responsive, not
watch it perform. Expressive motion is rationed to genuine wins (§9.2).

### 9.1 Easings and durations

| Token | Value | Use |
|---|---|---|
| `ease-out-soft` | `cubic-bezier(0.22, 0.61, 0.36, 1)` | Entrances, reveals, most things. |
| `ease-in-soft` | `cubic-bezier(0.55, 0.06, 0.68, 0.19)` | Exits, dismissals. |
| `ease-spring` | `cubic-bezier(0.34, 1.36, 0.64, 1)` | Panels, modals, anything that should feel physical. |
| `ease-celebrate` | `cubic-bezier(0.18, 1.5, 0.5, 1)` | Celebration register only. |

| Token | ms | Use |
|---|---|---|
| `dur-instant` | 120 | Hover colour, focus ring. |
| `dur-fast` | 200 | Button press, chip toggle, tooltip. |
| `dur-base` | 320 | Panel open, tab switch, card entrance. |
| `dur-slow` | 600 | Scroll-triggered section reveal. |
| `dur-celebrate` | 900 | XP count-up, streak flourish. |

**Never `linear` or `ease-in-out` on a designed transition** (§3.2 item 14).

### 9.2 Rules

- **Animate only `transform` and `opacity`.** Anything else is a gate failure. No animating `height`, `top`, `width`, or `box-shadow`.
- **`IntersectionObserver` for scroll entries, never a scroll listener.**
- Scroll entries: fade up 8px over `dur-slow` with `ease-out-soft`, staggered 60ms per item, capped at 6 items of stagger (beyond that it reads as slow, not choreographed).
- Press: `scale(0.98)` over `dur-fast`. Hover: a colour or 1px translate shift over `dur-instant`.
- **Nothing blocks input.** No animation gates a click.

### 9.3 The celebration register

Reserved for: XP gained, a streak milestone, a leaderboard climb, a correct
answer, and the marked-paper result reveal. Nothing else.

- Count-up on tabular numbers over `dur-celebrate`, `ease-celebrate`.
- A brief confetti-class flourish on milestones, paper-coloured and pastel, never neon.
- Spring scale on the badge or number, 1 → 1.08 → 1.
- **Always interruptible.** A user who taps through mid-celebration is never blocked or made to wait.
- **Never on a failure.** A dropped mark gets calm, specific, useful feedback. Celebrating engagement rather than achievement is how learning products become slot machines, and it is banned here.

### 9.4 Reduced motion

`prefers-reduced-motion: reduce` is respected everywhere, and it means *reduced*,
not *broken*: transforms and celebration flourishes drop to a simple opacity
change or nothing, but every state change stays legible and every element still
arrives. Count-ups jump to their final value immediately. Confetti does not run.

---

## 10. Icons

**Phosphor** (`@phosphor-icons/react`), already installed. One library, product-wide.
Lucide, Feather, FontAwesome, Material: banned (§3.2 item 3).

**Weight: `regular`.** Chosen over duotone because duotone's second tone
competes with the pastel tag system for the same visual register, and against
`bold` because the hairline aesthetic wants icons that sit at roughly the weight
of a `--rule` border. `fill` is permitted for a single active-state nav icon.

Default size 20px inline with `body-lg`, 16px with `body-sm`/`label`, 24px
standalone. Icon-only buttons **must** carry an `aria-label`, and icon plus
label is preferred wherever space allows.

**No emoji anywhere in the UI** (§3.2 item 9): not in markup, headings, buttons,
empty states, or alt text.

---

## 11. Chart theme (Nivo)

Charts use **Nivo** (`@nivo/*`), decided in §4. One shared `nivoTheme.ts` built
from these tokens; no chart sets its own colours.

- **Background** `--paper-raised`. **Text** `--ink-muted` at `data-sm`, tabular-nums.
- **Grid lines** `--rule-faint`, horizontal only. **Axis** `--rule`.
- **Series order** (categorical): sky, sage, amber, clay, lilac, rose. Accent red is *not* a series colour: it means "the teacher's mark" everywhere else and must not come to mean "series 1".
- **Sequential** scales: lightness ramp on a single hue, never a rainbow.
- **A single-series line** uses `--accent` deliberately, since there is no ambiguity with one line.
- **Legends and tooltips are required.** Tooltips give exact values. Meaning is never encoded by colour alone: pair with direct labels, shape, or pattern.
- **Empty-data state is mandatory** on every chart, in the Read/Operate voice, with marginalia rather than a blank box.
- A scoped D3 component is permitted if a viz genuinely exceeds Nivo, matching this theme; log the exception in the Phase 7 report.

---

## 12. Component rules

Full component kit and its 8-state preview live at `web/dev-previews/`. Rules
that bind every component:

- **Every interactive component implements all 8 states:** default, hover, focus-visible, active, disabled, loading, error, success. A component missing one does not merge (§9 gate 4).
- **Buttons.** Solid ink or accent fill, `radius-md`, `scale(0.98)` press, subtle hover shift. Primary (accent fill), secondary (paper-raised + rule border), ghost (no fill or border). No pills. No button-in-button.
- **Inputs.** Visible label always, never placeholder-as-label. `radius-md`, `--rule` border going `--rule-strong` on hover and `--focus-ring` on focus. Errors inline and adjacent to the field, never only at the top of the form.
- **Cards.** `--paper-raised`, 1px `--rule`, `radius-lg`, 24px padding, no shadow. No forced equal-height rows; align titles and CTAs across siblings and pin CTAs to the bottom.
- **Tags and badges.** Pastel fill with its paired text colour, `radius-full`, `eyebrow` type, tight padding. This is the *only* place pills are legal.
- **Tables.** `--paper-sunk` header, `--rule` row dividers, tabular-nums on every numeric column, right-aligned numbers, sticky header at `z-sticky`.
- **Skeletons, not spinners.** Loading states match the layout they replace so nothing shifts (CLS < 0.1). A spinner is permitted only for an indeterminate action under ~1s inside a button.
- **Empty states** are composed, never blank: a line of Caveat marginalia, a one-sentence explanation, and the action that fills it.
- **Error states** name what happened and what to do, in active voice ("We couldn't save your changes"), and offer a retry.

---

## 13. Variation knobs

The system is shared product-wide; hallmark's per-page diversification rule is
**inverted** for this project (§3.2 item 1). Surfaces differ only by turning
these knobs. Anything else is drift.

| Knob | Range | Notes |
|---|---|---|
| Section spacing | `space-12` … `space-32` | Marketing turns it up, Operate turns it down. |
| Card padding | `space-5` … `space-10` | Density. |
| Display rung | `display-md` … `display-hero` | Which rung a page's title uses. |
| Texture intensity | 0 … 3 elements/viewport | Read lane high, Operate low, per §8's budget. |
| Motion | per §3.3 dials | Marketing 7, auth 5, student 7, teacher/parent 6. |
| Accent density | sparse … prominent | How much accent appears; Operate stays sparse. |
| Container | 680 / 1200 / 1280px | Read / Operate / Persuade. |

Per-surface dial rows are in REDESIGN-MISSION §3.3 and are authoritative.

---

## 14. Adding a new page without breaking the system

1. Read this file and `PRODUCT.md`. Identify the lane (§2).
2. Take the container, spacing, and display rung from §13 for that lane.
3. Use only tokens. If a value is missing, add it *here* first, then use it.
4. Use only the four faces (§4), Phosphor regular (§10), and the 8 states (§12).
5. Every state exists before ship: loading, empty, error, and the long-content case.
6. Check the four mobile widths (320/375/414/768) and desktop.
7. Check `prefers-reduced-motion`, keyboard traversal, and focus-visible on every control.
8. Ask the §1 question last: does this still feel like a well-kept notebook? If not, the texture layer (§8) is the first thing to reach for, and restraint is the second.
