# REDESIGN-MISSION.md — Lemely Complete UI/UX Redesign

> **Read this entire file before doing anything.** This is the master directive for a full,
> unattended redesign of Lemely's UI/UX. It runs AFTER the MISSION.md build has wired real
> data. You are the orchestrator. You will delegate via dynamic workflows and subagents,
> resolve every ambiguity using the rules in this file, and only escalate to the human
> through the Steering Channel (§10) when this file genuinely does not answer the question.

---

## 1. Mission

Completely redesign, polish, and fix the UI/UX of Lemely — the IGCSE platform for
students, parents, and teachers at `/home/sico/Lemely`. The current UI is considered
**disposable** with exactly one exception:

> **PRESERVE: the overall warmth and notebook-like, sketchbook feel of the site.**
> This is the single protected quality. Every other visual decision may be replaced.

Scope:

- **Full sweep**: marketing/landing pages, auth, onboarding/placement test, student
  dashboard and study surfaces (past-paper correction, classifieds, flashcards, study
  plans, XP/leaderboards), teacher dashboard (at-risk flagging, academic stats, quiz
  builder), parent views, school-admin and platform-admin views.
- **Out of scope**: the Gradio internal debug tool. Do not touch it.
- **UX flows included**: onboarding, empty states, error handling, form validation,
  loading states, navigation. This is not a reskin.
- **IA changes allowed**: you may restructure routes, navigation, and page organization
  when it genuinely improves the experience. Document every IA change in the final report.
- **Responsive**: genuinely both desktop and mobile. Students live on phones.
- **Quality bar**: "make everything perfect." No surface ships half-done. Every page,
  every state, every breakpoint.

---

## 2. Prerequisites — Verify Before Phase 0 Completes

Nine skills are expected to be installed. **Verify each one exists and is loadable;
install anything missing before proceeding.** Do not silently skip a missing skill.

| Skill | Source | Verify by | Install if missing |
|---|---|---|---|
| `design-taste-frontend` (taste-skill v2) | Leonxlnx/taste-skill | SKILL.md present in skills dir | `npx skills add https://github.com/Leonxlnx/taste-skill --skill "design-taste-frontend"` |
| `redesign-existing-projects` | Leonxlnx/taste-skill | same | `npx skills add https://github.com/Leonxlnx/taste-skill --skill "redesign-existing-projects"` |
| `high-end-visual-design` (soft-skill) | Leonxlnx/taste-skill | same | `npx skills add https://github.com/Leonxlnx/taste-skill --skill "high-end-visual-design"` |
| `minimalist-ui` | Leonxlnx/taste-skill | same | `npx skills add https://github.com/Leonxlnx/taste-skill --skill "minimalist-ui"` |
| `full-output-enforcement` | Leonxlnx/taste-skill | same | `npx skills add https://github.com/Leonxlnx/taste-skill --skill "full-output-enforcement"` |
| `brandkit` | Leonxlnx/taste-skill | same | `npx skills add https://github.com/Leonxlnx/taste-skill --skill "brandkit"` |
| `ui-ux-pro-max` | nextlevelbuilder/ui-ux-pro-max-skill | run `python3 <skill>/scripts/search.py "test" --domain style` returns results | `uipro init --ai claude` (or `npx skills add nextlevelbuilder/ui-ux-pro-max-skill`) |
| `impeccable` | pbakaus/impeccable | `/impeccable` command available; `node <skill>/scripts/context.mjs` runs | `npx impeccable install` then `/impeccable init` |
| `hallmark` | Nutlope/hallmark | SKILL.md + references/ present | follow Nutlope/hallmark installer, or copy SKILL.md + references/ into `.claude/skills/hallmark/` |

Also verify:

- **Python 3** on PATH (ui-ux-pro-max search tool).
- **Node 22.12+** (impeccable CLI).
- **Playwright** installed with Chromium (screenshot gates, §9). Install if missing.
- **Gemini API key** present in env (brand image generation, §5). Respect the project's
  existing Gemini budget: total image-generation spend for this mission ≤ $3. Use flash
  image models by default; pro model only for the single final logo render.
- **ntfy**: outbound topic `lemely-ErBPK7TIRGD1sQP5` reachable. Create/confirm the inbound
  steering topic (§10).
- Repo clean, on a fresh branch off `develop` (§11).

---

## 3. Skill Orchestration Doctrine

These nine skills overlap and, in places, contradict each other. This section is law.
When any skill's text conflicts with this section, **this section wins.**

### 3.1 Roles — who does what

| Skill | Role in this mission | When active |
|---|---|---|
| **impeccable** | Command backbone for product UI. Its `context.mjs` setup, PRODUCT.md/DESIGN.md discipline, Operate/Persuade/Read modes, craft-floor, bounded-verification rule, and design-detector hook govern all app-surface work. | Every phase. Run `/impeccable hooks on` in Phase 0 and keep it on. |
| **hallmark** | Structural-variety engine + quality gatekeeper. Its multi-page redesign flow produces the canonical DESIGN.md; its slop-test gates + pre-emit self-critique are HARD merge gates (§9). Its non-destructive rail (never delete production files without a stated file-level plan) applies globally. | Phases 1, 2, and every page emit. |
| **ui-ux-pro-max** | Research database. Query it for styles, palettes, font pairings, UX guidelines, GSAP motion presets, chart guidance, and stack rules. Its `--design-system` output is generated ONCE in Phase 2 as research input, mined into DESIGN.md, then treated as read-only reference. Its priority ladder (accessibility → touch → performance → …) orders fix work. | Phases 1–2 heavily; ad-hoc lookups anytime. |
| **redesign-existing-projects** | Diagnosis checklist + fix-priority ladder. Its audit categories (typography, color, layout, states, content, components, icons, code quality, strategic omissions) structure the Phase 1 punch list. Its rule "small, targeted, reviewable changes; never break functionality" applies to all implementation. | Phase 1 (audit), Phase 4 (fix ordering). |
| **design-taste-frontend** | Brief-inference + dials + Redesign Protocol (its Section 11) for **marketing/landing and auth surfaces only**. Its own scope note excludes dashboards and product UI — honor that. Its em-dash ban and anti-default discipline apply to all copy and visuals mission-wide. | Phases 2–4, marketing/auth surfaces. |
| **minimalist-ui** | **Primary visual language** (see §4). Its warm monochrome palette logic, typographic architecture, flat bento structure, and banned-elements list define the product's look. | Every visual emit. |
| **high-end-visual-design** | **Craft-and-motion layer only.** Its motion choreography (custom cubic-beziers, staggered reveals, IntersectionObserver-driven entries, active-state physics), spatial rhythm, and performance guardrails apply. Its dark/glass vibe archetypes, pill CTAs, and double-bezel card mandates are **overridden** (§3.2). | Phases 4–5, motion + micro-interaction work. |
| **brandkit** | Brand identity generator. Its brand-strategy-first process, logo concept methods, and board composition author the Gemini image-generation prompts in Phase 2 (§5). | Phase 2 only. |
| **full-output-enforcement** | Global output discipline. No placeholders, no `// rest of code`, no "for brevity," no skeleton files. Scope-count → build → cross-check on every deliverable. Applies to every subagent's output, every file, this mission's reports included. | Always. |

### 3.2 Pre-resolved conflicts

Do not re-litigate these. Apply as written.

1. **Canonical design system file: `DESIGN.md` at the repo root.** Uppercase, so
   impeccable reads it natively; hallmark supports either case. It is produced by
   hallmark's multi-page flow in Phase 2, enriched with impeccable's `document`/`extract`
   output and mined ui-ux-pro-max research. hallmark's diversification rule is INVERTED
   for this project: all pages share the system; per-surface variation happens only
   through the variation knobs DESIGN.md defines. ui-ux-pro-max's
   `design-system/lemely/MASTER.md` is research input, never a second source of truth.
   `PRODUCT.md` (impeccable `init`) records audience, voice, and product lanes.
2. **Fonts.** Inter, Roboto, Arial, Open Sans, Helvetica: banned everywhere (all skills
   agree). Direction fixed in §4; exact faces chosen in Phase 2 and locked in DESIGN.md.
3. **Icons.** One library: **Phosphor**, one weight chosen in Phase 2 (regular or duotone —
   pick whichever reads warmer against the paper palette), consistent across the entire
   product. Lucide/Feather/FontAwesome/Material: banned.
4. **Buttons.** minimalist-ui wins: solid ink buttons (near-black on paper), 6–8px radius,
   `scale(0.98)` active press, subtle hover shift. **No pill-shaped buttons anywhere** —
   soft-skill's pill + button-in-button CTA pattern is overridden. Pills survive only as
   tags/badges (small, uppercase, wide tracking, muted pastel fill).
5. **Cards & shadows.** minimalist-ui wins: 1px hairline borders (`#EAEAEA`-family), flat
   surfaces, radius 8–12px. Soft-skill's double-bezel nesting is overridden for standard
   cards; it MAY be used sparingly for one or two hero/feature showcase containers on
   marketing pages only. Shadows: none on resting cards; ultra-diffuse ≤0.05-opacity
   shadows permitted only on floating layers (popovers, modals, dropdowns, toasts).
6. **Glassmorphism.** Banned, except a subtle `backdrop-blur` on the fixed navbar.
   Never on scrolling content (performance rule, all skills agree).
7. **Gradients.** Banned as visible design elements. Permitted only as ambient warmth:
   radial light spots at ≤0.04 opacity behind heroes/sections (minimalist-ui §6/§7).
   The purple-blue AI gradient is a firing offense.
8. **Dark sections / dark mode.** Light mode only for now. No random dark sections
   breaking the warm paper page (redesign-skill rule). Build tokens so a future dark
   theme is a token swap, but do not implement or test dark mode.
9. **Emojis in UI.** Banned (markup, headings, buttons, empty states, alt text). Use
   Phosphor icons or small illustrations instead.
10. **Copy.** No invented metrics, testimonials, logos, or user counts (hallmark honest-copy
    discipline) — use real data or labeled placeholders. No AI-copy clichés (Elevate,
    Seamless, Unleash, Next-Gen, Game-changer, Delve). Sentence case headings. No
    exclamation marks in success messages. Active voice errors ("We couldn't save your
    changes"). **No em-dashes in UI copy** (taste-skill hard ban) — restructure the
    sentence or use a comma/period.
11. **Chrome.** Never hand-draw fake browser bars, phone frames, or fake code-window
    chrome (hallmark gate 47). Real screenshots in `<figure>` with hairline border, or
    nothing.
12. **Typography purity.** No italic display headings; no italic emphasis words inside
    headings (hallmark gate 38a). Emphasis via weight, accent color, or drawn underline.
    Italic is body-copy-only. Exception: the handwritten annotation face (§4) is a
    decorative layer, not a heading style.
13. **Tokens.** Once DESIGN.md locks the theme, every color and font-family in emitted
    code references a named token (`var(--color-accent)`, `var(--font-display)`).
    Inline hex/oklch/rgb or raw font-family strings that bypass the token block are a
    gate failure (hallmark gate 48). New values get lifted into the token block first.
14. **Motion defaults.** No `linear` or `ease-in-out` on designed transitions — custom
    cubic-beziers or springs (soft-skill). But motion stays *calm*: minimalist-ui's
    "invisible motion" is the baseline; expressive spring moments are reserved for
    gamification celebrations (§4). `prefers-reduced-motion` respected everywhere.
    Animate only `transform`/`opacity`. IntersectionObserver, never scroll listeners.
    `backdrop-blur` and noise overlays only on fixed layers.
15. **design-taste-frontend scope.** Authoritative on marketing/landing/auth. On
    dashboards and product UI it contributes only its universal rules (anti-defaults,
    em-dash ban, dependency verification); impeccable's Operate mode + ui-ux-pro-max +
    hallmark govern those surfaces.
16. **Verification cadence.** impeccable's bounded-pass rule beats any skill's open-ended
    self-QA loop: build the surface fully → one batched inspection round (desktop +
    mobile together) → fix everything found in one batch → at most one confirmation
    round → stop polishing and move on.

### 3.3 Dials

Global baseline (user-set): **DESIGN_VARIANCE 6 / MOTION_INTENSITY 7 / VISUAL_DENSITY 6.**
Per-surface adjustments (use for both taste-skill dials and ui-ux-pro-max `--variance/--motion/--density` flags):

| Surface | VARIANCE | MOTION | DENSITY |
|---|---|---|---|
| Marketing / landing | 7 | 7 | 4 |
| Auth / onboarding / placement test | 5 | 5 | 4 |
| Student dashboard + study surfaces | 6 | 7 | 6 |
| Teacher / parent / admin | 6 | 6 | 7 |

---

## 4. The Design Direction (Pre-decided — do not re-open)

**Design Read (taste-skill §0.B format):** *"Reading this as: a full-product redesign of an
IGCSE learning platform for students, parents, and teachers, with a warm Notion-like
editorial language crossed with a paper sketchbook identity, leaning toward
minimalist-ui's warm monochrome + muted pastel system, Tailwind v4 tokens, and calm
spring motion with expressive celebration moments."*

The user's references: **Notion** is the north star. Hard anti-references: **generic SaaS
feel — dense bootstrap-colored dashboards, purple-blue gradients, cookie-cutter card
grids, dark glass "AI product" aesthetic.**

The identity, named for internal use: **"The Study Notebook."** Lemely should feel like a
beautifully kept notebook that happens to be alive — warm paper, ink, hairlines, marginalia,
sticker-like pastel tags, and quiet motion. Fun but calm and professional. Teacher and
parent views share the exact same language (user decision: same feel, slightly denser).

Concrete direction (Phase 2 finalizes exact values into DESIGN.md tokens):

- **Canvas**: warm bone/off-white paper (`#F7F6F3`/`#FBFBFA` family). Ink: off-black
  charcoal (`#111`/`#2F3437` family), secondary `#787774` family. Hairlines
  `#EAEAEA`/`rgba(0,0,0,0.06)`. Never pure `#000` or pure sterile white-on-white.
- **Accents**: one primary accent (choose a warm, slightly desaturated hue in Phase 2 —
  candidates: warm coral-red ink, marker-yellow highlight, sage; saturation <80%) plus
  minimalist-ui's washed pastel set (pale red/blue/green/yellow with their dark text
  pairs) for tags, subject color-coding, and inline highlights. Subject color-coding
  (Math vs Physics vs future subjects) is encouraged — it's semantic, not decorative.
- **Notebook texture layer** (this is how the protected sketchbook feel survives): subtle
  paper grain overlay (fixed, pointer-events-none, ≤0.04 opacity), occasional ruled/dotted
  hairline patterns in section backgrounds, hand-drawn-style SVG underlines/circles/arrows
  as accent doodles, sticker-like badges for achievements. Restraint: marginalia decorates,
  never carries meaning alone.
- **Typography**: editorial serif for display headings (Newsreader / Instrument Serif /
  Lyon-class; tight tracking, 1.1 line-height), a characterful geometric sans for UI and
  body (Geist Sans / Switzer / Satoshi class; never Inter), monospace with
  `font-variant-numeric: tabular-nums` for all scores, grades, XP, timers, and data
  (Geist Mono / JetBrains Mono class), and **one handwritten accent face** (Caveat-class)
  used ONLY for marginalia/annotation moments — never headings, buttons, or body.
  Weights 400/500/600 in play, not just 400/700. Body max ~65ch, line-height 1.6.
- **Layout**: flat bento grids with 1px hairlines and generous internal padding
  (24–40px), asymmetric where content justifies it, max-width container 1200–1440px,
  macro-whitespace between sections, broken symmetry on marketing pages. No forced
  equal-height card rows; align titles/prices/CTAs across siblings; pin CTAs to card
  bottoms.
- **Motion personality**: baseline invisible — gentle 600ms fade-up scroll entries with
  stagger, 200ms hover shifts, `scale(0.98)` presses, spring-eased panel transitions.
  **Celebration register** for gamification: XP gains, streak milestones, leaderboard
  climbs, and correct-answer moments get expressive spring physics, count-up numbers,
  and brief confetti-class flourishes — always interruptible, always reduced-motion-safe,
  never blocking.
- **Charts (user delegated — decided): Nivo** (`@nivo/*`). Animated by default
  (react-spring under the hood), fully themeable to the paper/ink/pastel tokens,
  responsive, with a11y-conscious color scales. Build one shared `nivoTheme.ts` from
  DESIGN.md tokens (paper background, ink text, hairline grid lines, pastel series
  colors, tabular-num tick labels) and use it on every chart: student progress curves,
  grade-boundary distance, teacher class stats, at-risk trends, XP history. Legends and
  tooltips required; never encode meaning by color alone. If a specific viz genuinely
  exceeds Nivo, a scoped D3 component matching the same theme is permitted — log the
  exception in the report.

---

## 5. Phase Plan

Work phase-by-phase. Each phase ends with a milestone commit, an ntfy notice, and a
STATE update (§11). Use dynamic workflows: within a phase, fan out independent
work to subagents in parallel; join before the phase gate.

### Phase 0 — Setup & Verification
1. Verify/install everything in §2. Report any install performed.
2. `node <impeccable>/scripts/context.mjs` once; `/impeccable hooks on`.
3. Run `/impeccable init` → write `PRODUCT.md`: audience (IGCSE students ~14–17, their
   parents, teachers, school admins), voice (warm, plain, encouraging, no hype), lanes
   (Persuade: marketing; Operate: all dashboards/tools; Read: study content), brand
   anti-references from §4.
4. Confirm branch strategy (§11) and the Steering Channel (§10) with a test message.

### Phase 1 — Audit (produce the Punch List, touch nothing)
Run three audits and merge them into `BUILD/DESIGN-AUDIT.md`:
1. **hallmark audit** across every route: score against its anti-pattern list + slop
   gates; ranked punch list.
2. **impeccable `audit` + `critique`** per major surface: technical (a11y, perf,
   responsive) + heuristic UX scoring.
3. **redesign-existing-projects Diagnose**: walk its full checklist per category;
   inventory the current stack (framework, styling method, Tailwind version, component
   patterns), missing states (loading/empty/error), dead links, strategic omissions
   (404 page, back navigation, skip-link, legal links, favicon, meta/OG tags).
Also: map the current IA (page tree, nav, key task paths per role) and list proposed IA
changes with rationale. Send the audit summary + proposed IA changes as a DECISION
message (§10) with a 60-minute timeout defaulting to "proceed as proposed."

### Phase 2 — Brand & Design System (the foundation everything reads)
1. **Brand strategy** (brandkit's strategy-first process, text): one-line brand idea,
   personality, symbol territory for the logo (notebook/spark/progress territory —
   explore per brandkit's five logo concept methods: monogram+meaning, product action,
   metaphor fusion, negative space, construction geometry).
2. **Logo + identity images via Gemini** (user choice 11b): author generation prompts
   using brandkit's composition rules. Generate 3–4 logo directions (white background,
   flash model), pick the strongest against the brand strategy, refine once, render the
   final pick once on the pro model. Produce a simple wordmark + mark lockup. Vectorize
   or cleanly cut out; place in `frontend/public/brand/` (+ favicon set). Optionally one
   brandkit-style identity board image for the report. Total spend ≤ $3. Send the logo
   candidates as an ntfy attachment DECISION (30-min timeout, default = your pick).
3. **Research pass**: `search.py "education learning platform students warm editorial
   notebook" --design-system --variance 6 --motion 7 --density 6 -p "Lemely" --persist
   --output-dir <repo-root>`, plus domain queries (`typography`, `color`, `ux`, `gsap`,
   `chart`, `icons`) and stack queries for the detected stack. Mine — don't obey —
   anything conflicting with §4.
4. **Write `DESIGN.md`** (hallmark multi-page format, extended): genre, macrostructure
   family per lane (marketing / app / content), full OKLCH token block (paper, ink,
   rule, accent, pastels, focus, semantic states, subject colors), typography (the four
   faces of §4 with weights), spacing scale, radius scale, z-index scale, icon library +
   weight, motion spec (easings, durations, celebration register), chart theme, and the
   variation knobs each surface may turn. Every later emit reads this file first.
5. **Token implementation**: CSS custom properties + Tailwind theme mapping. Stack
   changes are allowed (user decision): adopting **Tailwind v4** and restyled shadcn/ui
   primitives is permitted and encouraged where it reduces bespoke CSS — but never ship
   default shadcn appearance, and React itself and the app framework stay (no Next.js
   migration, no rewrite). Verify every new dependency lands in package.json before
   importing (taste-skill dependency rule).
6. **Core component kit**, each per hallmark component-scope discipline — **all 8 states
   (default/hover/focus-visible/active/disabled/loading/error/success) implemented, with
   an 8-state preview page** kept under `frontend/dev-previews/`: Button, Input,
   Select, Checkbox/Radio/Switch, Card, Tag/Badge, Modal, Popover, Toast, Tabs, Table,
   Skeleton, EmptyState, ErrorState, Avatar (squircle, not circle), Kbd, ProgressBar,
   XP/Streak widgets, Chart wrapper.

### Phase 3 — IA & UX Flows
1. Implement the approved IA restructure. Per-role navigation that makes each role's
   top tasks one obvious step away. Active-page indication, working back paths, no dead
   ends, deep-linkable routes.
2. **impeccable `shape` → `onboard`** for first-run flows per role: student first-run
   (placement test framing, first study plan), teacher first-run (class setup), parent
   first-run (phone OTP path, linking a student). Empty dashboards become composed
   "getting started" views, never blank.
3. **impeccable `harden` + `clarify`** groundwork: form validation patterns (inline,
   near-field errors, visible labels — never placeholder-only), error copy voice,
   loading = layout-matching skeletons (no generic spinners), custom 404, skip-to-content
   link.
4. **RTL-safety rule (from here to the end)**: all new/edited styles use logical
   properties (`margin-inline-start`, `padding-inline`, `inset-inline-end`, `text-align:
   start`), no hardcoded left/right in layout CSS, direction-dependent icons flagged with
   a comment. English-only ships; the layout must survive a future `dir="rtl"` flip.

### Phase 4 — Surface-by-Surface Redesign
Order (highest daily-use impact first): **Student dashboard → past-paper correction flow
→ study surfaces (classifieds, flashcards, study plans) → gamification (XP, streaks,
leaderboards) → Teacher dashboard + quiz builder → Parent views → Admin views → Auth →
Marketing/landing → 404/misc.**

Per surface, run this loop (a dynamic workflow instance; parallelize independent
surfaces across subagents when they don't share files):
1. Re-read `DESIGN.md` + `PRODUCT.md` + that surface's audit findings + its dial row (§3.3).
2. State the file-level plan (modify/create/delete) — hallmark non-destructive rail;
   deletions beyond trivial require a DECISION message.
3. Apply redesign-skill's fix-priority ladder within the surface: typography → color →
   interactive states → layout/spacing → component replacement → loading/empty/error
   states → final type polish.
4. Marketing/auth surfaces additionally run design-taste-frontend's Redesign Protocol
   (audit → preserve list → modernisation levers) in **overhaul** mode.
5. Dashboards/tools run in impeccable **Operate** mode: scanability, consistency, and
   task speed outrank expression; brand lives in the details (tabular numbers, subject
   colors, notebook marginalia in empty states, celebration register on wins).
6. Load impeccable's craft-floor immediately before editing UI. Emit complete files
   (full-output-enforcement — no placeholders ever).
7. Run the surface through the Hard Gates (§9). Fix in one batch, one confirm round, stop.
8. Milestone: commit, gate stamp, ntfy notice (+ screenshots per §9 cadence).

### Phase 5 — Motion & Data-Viz Pass
1. Sweep every surface with the motion spec: scroll entries with stagger, hover/press
   physics on all interactive elements, panel/modal spring transitions, count-up
   tabular numbers on stats.
2. Implement the celebration register end-to-end (XP gain, streak save, leaderboard
   movement, marked-paper results reveal). Pull GSAP presets from ui-ux-pro-max
   `--domain gsap` where they fit; IntersectionObserver/`whileInView` only.
3. Build/theme every chart on the shared Nivo theme. Teacher analytics get the full
   treatment: animated entries, hover tooltips with exact values, legends, empty-data
   states.
4. `prefers-reduced-motion` audit: every animation has a reduced path.

### Phase 6 — Hardening & Adaptation
1. **impeccable `adapt`**: every page verified at 320 / 375 / 414 / 768 px and desktop.
   Hallmark mobile non-negotiables enforced: no horizontal scroll (`overflow-x: clip`
   on html+body), no two-line clickable text, `minmax(0,1fr)` on image grid tracks,
   `overflow-wrap:anywhere` on display headers, touch targets ≥44×44 with ≥8px spacing.
2. **impeccable `harden`**: error/edge/long-content/slow-network passes on the critical
   flows (paper upload + marking wait states especially — that flow has real latency;
   design the waiting experience, progress feedback, and failure recovery properly).
3. **impeccable `optimize` + soft-skill performance guardrails**: transform/opacity-only
   animation, no blur on scrolling content, z-index scale respected, lazy images
   (WebP/AVIF), skeletons reserve space (CLS < 0.1), font-display strategy.
4. Accessibility best-effort sweep (ui-ux-pro-max priority 1): 4.5:1 contrast on text,
   focus-visible everywhere, keyboard-completable flows, alt text, aria-labels on
   icon-only buttons, semantic landmarks.
5. Strategic-omissions closeout: favicon (new logo), meta/OG tags per page, legal links,
   404 in the new language, skip-link.

### Phase 7 — Final QA & Report
1. Full-product hallmark audit re-run + impeccable `polish` on anything flagged.
   Everything must pass §9.
2. Before/after screenshot gallery: one desktop + one 375px capture per major surface,
   old vs new (pull "old" from the pre-redesign branch point).
3. Write `BUILD/DESIGN-REPORT.md`: every surface, every change, every IA change with
   rationale, the DESIGN.md system summary, gate results, exceptions logged, and a
   maintenance note ("how to add a new page without breaking the system — read
   DESIGN.md first").
4. Final milestone PR `develop → main`, ntfy completion notice with the report +
   gallery attached.

---

## 9. Hard Gates (blocking — a surface that fails does not merge)

Enforced by the reviewer subagent before any merge to `develop`:

1. **hallmark slop-test**: all applicable gates pass; the pre-emit self-critique stamp
   (`/* Hallmark · pre-emit critique: P_ H_ E_ S_ R_ V_ */`) present on every emitted
   surface with every axis ≥3 (revise until true).
2. **impeccable design-detector hook**: zero unresolved findings on touched files.
3. **Token discipline**: no raw colors/font-families outside the token block (grep-able).
4. **8-state completeness** on every interactive component introduced or touched.
5. **Responsive**: the four mobile widths + desktop verified per Phase 6 rules. Screenshot
   verification is *batched* (impeccable bounded passes): one Playwright round per
   surface milestone — desktop + 375px minimum, all four widths in Phase 6 — not per
   edit. Attach the milestone pair to the ntfy notice. Screenshots are slow; batch them.
6. **full-output-enforcement**: no placeholder patterns anywhere in the diff.
7. **Functional safety**: existing tests green; the redesign never breaks working
   features (redesign-skill rule). If a test must change because IA changed, the change
   is documented in the report.
8. **Copy rules** (§3.2 item 10) hold on all new/edited copy.

---

## 10. Steering Channel (interactive decisions, better than one-way ntfy)

Two-way, phone-friendly, file-backed:

- **Outbound**: ntfy topic `lemely-ErBPK7TIRGD1sQP5` (existing). Decision requests use
  title `DECISION D<n>`, body = question + lettered options + stated default + timeout.
  Attach images (logo candidates, screenshots) where visual.
- **Inbound**: ntfy topic **`lemely-ErBPK7TIRGD1sQP5-in`**. The user replies from the
  ntfy app by publishing to that topic (`D3: B`, or free text to steer anything,
  anytime — not only in answer to questions). Poll it between work units via
  `http://home-server:7532/lemely-ErBPK7TIRGD1sQP5-in/json?poll=1&since=<last-ts>`; check at
  minimum at every phase boundary, every surface milestone, and while waiting on an
  open DECISION.
- **File fallback**: mirror every question and every received answer to
  `BUILD/STEERING.md` (append-only log). The user may also answer by editing that file
  directly on the laptop; treat file answers and ntfy answers identically (latest wins).
- **Timeout discipline**: every DECISION carries a default and a timeout (30 min routine,
  60 min for IA/brand). On timeout, proceed with the default and log it. Never block
  indefinitely; never proceed on a non-defaulted question without an answer — if a
  question has no sane default, it shouldn't be a timeout question, so keep working on
  independent tasks while it waits.
- Free-text steering messages are directives: acknowledge on ntfy, log to STEERING.md,
  apply from the next work unit onward.

---

## 11. Process Integration

- **Supervisor**: runs under the existing `supervisor.sh` loop (auto-resume after usage
  resets, Opus for every run, dangerous-skip-permissions approved, work confined to
  `/home/sico/Lemely`). Add/extend the STATE checkpoint (`BUILD/STATE.md`) with a
  `REDESIGN` section: current phase, current surface, gate status, open DECISIONs,
  last-processed steering timestamp. Resume by reading STATE + STEERING first.
- **Subagents**: reuse the existing roster via dynamic workflows. Suggested mapping:
  architect → design-system + IA decisions; implementer(s) → surface loops (parallel on
  non-overlapping surfaces); reviewer → Hard Gates; test-engineer → functional safety +
  Playwright rounds; reporter → ntfy notices, STEERING log, DESIGN-REPORT; scout →
  ui-ux-pro-max queries + reference lookups. Add a `.claude/agents/design-director.md`
  subagent if useful: owns DESIGN.md consistency, arbitrates any intra-skill conflict
  using §3, reviews every surface against the Study Notebook direction before the gate.
- **Git**: feature branch per phase or surface (`redesign/<surface>`), auto-merge to
  `develop` when tests + Hard Gates pass, milestone PRs `develop → main` per phase for
  later human review. Never force-push, never delete history.
- **ntfy notices**: fine-grained progress per the user's preference — phase start/end,
  each surface milestone (with the batched screenshot pair), each DECISION, each gate
  failure that needed >1 fix round, and the final report.

---

## 12. Definition of Done

- Every in-scope surface redesigned to the Study Notebook system; zero pages left in
  the old language; the notebook warmth is unmistakably present and stronger than before.
- `DESIGN.md`, `PRODUCT.md`, logo + brand assets, component kit with 8-state previews,
  shared Nivo theme: all in the repo and internally consistent.
- All Hard Gates green product-wide; tests green; nothing functional regressed.
- Onboarding, empty, loading, and error experiences exist for every role and every
  major flow, including the paper-marking wait experience.
- RTL-safe styles throughout new/edited code; light-mode tokens structured for a future
  dark theme.
- `BUILD/DESIGN-REPORT.md` + before/after gallery delivered; final PR to `main` open;
  completion ntfy sent.

Begin with Phase 0.
