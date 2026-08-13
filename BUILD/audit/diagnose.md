# Diagnose — redesign-existing-projects checklist

Scope: `web/src` (React SPA). Branch `redesign/phase-0`. Read-only audit; no files under
`web/` were modified. Every claim below is grounded in a file:line or a literal command run
from `/home/sico/Lemely/web`.

## Stack inventory

| Layer | Value | Source |
|---|---|---|
| Framework | React 19.2.7 + `react-dom` 19.2.7 | `web/package.json:22-23` |
| Router | `react-router-dom` 7.18.1, `createBrowserRouter` data-router API | `web/package.json:24`, `web/src/App.tsx:3,66` |
| Build | Vite 8.1.1, `@vitejs/plugin-react` 6.0.3 | `web/package.json:41,32` |
| Styling | Tailwind v4.3.3 (`@tailwindcss/vite` 4.3.3), CSS-first config via `@import "tailwindcss"` + `@theme`-style custom properties in `src/index.css` — no `tailwind.config.js` | `web/package.json:30,38`, `web/src/index.css:1` |
| Component variants | `class-variance-authority` 0.7.1 (`cva`), `tailwind-variants` 3.3.0, `tailwind-merge` 3.6.0 via a local `cn()` helper | `web/package.json:19,27,26`, `web/src/components/ui/button.tsx:1,13` |
| State/data | `@tanstack/react-query` 5.101.4 | `web/package.json:18`, `web/src/main.tsx:4-6` |
| Icons | `@phosphor-icons/react` 2.1.10, mixed `regular`/`fill` weight (weight swaps on `isActive`), one library throughout observed nav code — matches REDESIGN-MISSION §3.2 item 3 already | `web/package.json:20`, `web/src/portals/teacher/index.tsx:76-82` |
| Fonts loaded | Instrument Serif 400 + 400-italic (`@fontsource/instrument-serif`), Work Sans Variable (`@fontsource-variable/work-sans`), JetBrains Mono Variable (`@fontsource-variable/jetbrains-mono`) | `web/src/index.css:3-6` |
| Fonts actually used | `--font-sans: "Work Sans"`, `--font-serif: "Instrument Serif"`, `--font-mono: "JetBrains Mono Variable"` — all three loaded faces are consumed; no unused `@fontsource` import found | `web/src/index.css:325-327,591-695` |
| No 4th handwritten/marginalia face | REDESIGN-MISSION §4 calls for a Caveat-class handwritten accent face; none is imported | `web/src/index.css:3-6` (only 3 `@import` lines) |
| Design tokens source | `DESIGN.md` at repo root, theme name **"Academic Warmth"** (Material-3-derived hex palette: surface/on-surface/primary/secondary/tertiary roles), ported into `src/index.css` as `--md-*` then re-exposed as semantic `--bg/--surface/--t1..t3/--accent` etc. | `/home/sico/Lemely/DESIGN.md:1-8`, `web/src/index.css:9-16` |
| This is a **prior** design system, not the Study Notebook one | No paper-grain texture, no ruled/dotted hairline pattern, no handwritten face, no OKLCH token block — the token layer the redesign mission will replace | `web/src/index.css:1-60` (full read) |
| PWA | `vite-plugin-pwa` 1.3.0, `workbox-*` 7.4.1, manifest icons in `public/` | `web/package.json:44,45-47`, `ls web/public` |
| Testing | Vitest 4.1.10 (unit), Playwright 1.62.1 (e2e, `web/e2e/*.spec.ts`, 13 files), axe-core 4.12.1 + `@axe-core/playwright`, Lighthouse 13.4.1, oxlint 1.71.0 | `web/package.json:12,13,50,52,53,54,49` |
| Camera capture | Custom `CameraCapture.tsx` (no third-party camera lib), `pdf-lib` for client-side multi-page PDF assembly | `web/package.json:21`, `web/src/components/CameraCapture.tsx` |

## Typography

- Three faces loaded and all three consumed (serif display, sans body/UI, mono for
  numerals) — a real hierarchy already exists, not the Inter/system-ui default the skill
  warns about. `web/src/index.css:591-695` shows a full type-scale utility set
  (`.text-display-*`, `.btn-text*`) rather than ad hoc `text-[Npx]` scattered through
  components.
- Gap vs REDESIGN-MISSION §4: no handwritten/marginalia face imported at all
  (`web/src/index.css:3-6` has exactly 3 `@import` lines) — required for Phase 2, not
  present today.
- `font-variant-numeric: tabular-nums` discipline for scores/grades/XP was not verified
  file-by-file in this pass (see "Not reached" below); `--font-mono` exists and is applied
  to at least the header breadcrumb (`web/src/portals/student/index.tsx:219`) and audit
  comments describe "tabular-nums" as intended elsewhere but that was not individually
  confirmed per screen.
- Sentence-case heading discipline: `Login.tsx:79` (`<h1>Lemely</h1>`) and sidebar headers
  observed are short brand/nav strings, not a title-case violation in the surfaces read.

## Color and surfaces

- Single palette family, no purple/blue AI gradient found in any read file. `DESIGN.md`'s
  hex values (`primary: '#964232'` terracotta, `tertiary: '#006857'` teal,
  `secondary: '#80534a'`) are desaturated, warm-toned — already compliant with the
  "one accent, <80% saturation" rule (`/home/sico/Lemely/DESIGN.md:19-25`).
- Per-portal accent swap via `data-portal` attribute (student=terracotta, teacher=teal) —
  documented in `web/src/App.tsx:11-14` and implemented via CSS custom-property
  overrides scoped by `[data-portal="..."]` (confirmed present at
  `web/src/index.css:9-16` comment block; the actual selector block sits later in the
  750-line file and was not individually re-read past line ~80 — see "Not reached").
- No pure `#000`/pure white found in the token excerpt read (`background: '#fff8f6'`,
  `on-surface: '#231917'` — both off-white/off-black per `/home/sico/Lemely/DESIGN.md:44,45,13`).
- This entire palette predates the REDESIGN-MISSION §4 OKLCH "Study Notebook" direction
  (paper bone `#F7F6F3` family, ink `#111`/`#2F3437` family) and will be replaced in
  Phase 2 per the mission's own plan — flagging here only so Phase 2 does not assume a
  green field; a real, coherent, AA-conscious system already exists and needs a
  swap-not-rescue.

## Layout

- Container max-widths present and distinct per portal: student `max-w-[1320px]`
  (`web/src/portals/student/index.tsx:249`), teacher `max-w-[1480px]`
  (`web/src/portals/teacher/index.tsx:244`), parent `max-w-240` (Tailwind spacing scale,
  `web/src/portals/parent/index.tsx:147`) — no edge-to-edge stretch on wide screens.
- Sidebar-left pattern on student and teacher portals (`web/src/portals/student/index.tsx:136`,
  `web/src/portals/teacher/index.tsx:192`) — REDESIGN-MISSION doesn't ban sidebars, so not
  flagged as a defect, but it is the single layout pattern across both dashboards; no
  top-nav or command-menu alternative exists anywhere in the app.
- Landing screen (`web/src/portals/student/screens/Landing.tsx:22`) uses an intentional
  asymmetric `grid-cols-[1.15fr_1fr]`, not a forced 3-equal-column row — good, but see IA
  finding below: this page is unreachable in normal use.
- A responsiveness bug was found and already fixed by the team, per an inline comment
  (`web/src/portals/student/index.tsx:199-206`): the header CTA + breadcrumb overflowed at
  380px; the comment documents the fix (`min-w-0 truncate`, tightened padding
  below 640px). Left as an example that this codebase already runs some responsive gates
  — not a currently-open defect, but evidence the team's "quality bar" grep needs to keep
  covering routes as they're added (see `audit.mjs` scope note below).

## Interactive states

- `Button` (`web/src/components/ui/button.tsx:13-42`) implements hover
  (`hover:bg-accent-hover` etc.), active press (`active:translate-y-px`), focus-visible
  ring (`focus-visible:outline-2 focus-visible:outline-offset-2
  focus-visible:outline-accent`), and disabled (`disabled:opacity-50
  disabled:pointer-events-none`) in one `cva` definition — 4 of the 8 REDESIGN-MISSION
  states (default/hover/focus-visible/active/disabled) covered at the primitive level;
  loading/error/success are not part of `Button` itself and were not traced to callers in
  this pass (see "Not reached").
- Active nav-link styling present on both dashboard sidebars: `NavLink`'s `isActive`
  toggles background, text weight, and an accent dot
  (`web/src/portals/student/index.tsx:153-169`,
  `web/src/portals/teacher/index.tsx:65-83`) — "no indication of current page" is not a
  problem here.
- `RouteFallback` (`web/src/components/ui/state-views.tsx:150-156`) is a real, shared
  loading affordance for lazy route chunks (`role="status"`, one component, not four
  ad hoc `Loading…` divs) — good; still text-only, not a skeleton that matches the target
  layout shape, so the skill's "skeletons over spinners" guidance is only partially met
  (a plain text status line, at least not a spinner icon).
- `StateView` family (`web/src/components/ui/state-views.tsx:53-124`) gives one shared
  empty/error/offline component used across the app, with a documented tone rule pulled
  straight from PRODUCT.md ("avoid red-heavy error states; prefer amber/neutral" —
  `web/src/components/ui/state-views.tsx:13-17`, matching `PRODUCT.md:119`). This is a
  genuinely above-average implementation of the skill's "no empty/error states" checklist
  item — not a gap.
- Back navigation (`navigate(-1)`) exists in exactly one screen in the entire codebase:
  `web/src/portals/teacher/screens/StudentDetail.tsx:103,116`. No other screen offers a
  "back" affordance beyond browser chrome or the sidebar/breadcrumb (student portal has a
  breadcrumb, `web/src/portals/student/index.tsx:219`; teacher and parent portals have no
  breadcrumb at all). Flagged as a strategic omission below.

## Content

- No `John Doe`/`Acme Corp`-style placeholders found in the files read; user-facing names
  are pulled from real API data with an explicit no-fabrication policy documented inline
  (`web/src/portals/student/index.tsx:83-96`, `web/src/portals/teacher/index.tsx:145-152`
  — both blocks describe removing a previously-hardcoded fake name/school in favor of
  `data.displayName ?? email.split("@")[0]`).
- A hardcoded "24 day streak" pill and a fake search input were found and *removed* by the
  team already, documented at `web/src/portals/student/index.tsx:206-217` — the streak
  literal was traced to no real backing field and pulled rather than mislabelled. This is
  the skill's "fake round numbers" anti-pattern already caught and fixed upstream of this
  audit; noted as evidence, not a live defect.
- Copy voice matches PRODUCT.md ("warm, plain, encouraging, no hype") in the strings read:
  `"Your session expired. Please sign in again."` (`Login.tsx:82-83`), `"Couldn't load
  classes."` (`web/src/portals/teacher/index.tsx:110`) — active voice, no "Oops!", no
  exclamation marks.
- The `Login` screen is explicitly marked as unfinished by its own author comment:
  *"Minimal email/password login screen — infrastructure to exercise the auth plumbing…
  not final UI. Screen polish is P2.7/P2.8's job."* (`web/src/portals/auth/Login.tsx:11-14`).
  Confirms the whole auth surface is pre-visual-design, not merely un-redesigned.

## Component patterns

- `web/src/components/ui/` holds 18 files: `button, card, checkbox, chip, confidence-indicator,
  grade-badge, mark-display, nav-shells, paper-identity, primitives, processing-state,
  question-row, role-switcher, slider, state-views, stepper, trend-sparkline,
  weakness-chip, xp-streak, boundary-bar` (`ls web/src/components/ui`). This is a real,
  domain-specific component library (grade badges, confidence indicators, mark-scheme
  boundary bars) — not a generic shadcn-default set. No `Modal`, `Popover`, `Toast`,
  `Tabs`, `Table`, `Select`, `Avatar`(dedicated), `Kbd`, or `ProgressBar` primitive was
  found in this directory listing; REDESIGN-MISSION Phase 2's component kit list
  (Modal/Popover/Toast/Tabs/Table/Skeleton/Avatar squircle/Kbd/ProgressBar) is therefore
  still to be built from scratch for at least those 8 primitives, not merely restyled.
- A teacher-only `Avatar.tsx` exists at `web/src/portals/teacher/components/Avatar.tsx`
  (scoped to that portal, not shared) — one of the "component replacement" targets: this
  should become the shared squircle `Avatar` primitive Phase 2 calls for.
- Quiz-taking has its own subtree, `web/src/components/quiz/QuizTaker.tsx` +
  `quizTakerData.ts` — a substantial, non-trivial interactive component (429+ lines,
  handles 404s explicitly at `QuizTaker.tsx:421`) outside `components/ui`, worth Phase 4
  attention as its own surface rather than folding into "teacher dashboard."

## Iconography

- Single library confirmed: `@phosphor-icons/react` only, no Lucide/Feather/FontAwesome
  import found anywhere the grep covered (`web/package.json:20` is the only icon dependency
  listed). Weight is inconsistent by design (`regular` default, `fill` on active state,
  `web/src/portals/teacher/index.tsx:78`) rather than a stray mixed-weight bug — this
  matches REDESIGN-MISSION §3.2 item 3's instruction to standardize on Phosphor, though
  Phase 2 still needs to lock ONE weight for the redesign per that same rule (today's
  regular/fill toggle is a *state* signal, not two different resting weights, so it is
  compatible with — not a violation of — a future single-weight lock).
- Favicon exists and is not the generic default: `public/favicon.svg` +
  `apple-touch-icon`/`pwa-192x192.png`/`pwa-512x512.png`/`maskable-icon-512x512.png`, all
  wired in `index.html:5-6` and `ls web/public`. Not a strategic omission (see below) —
  this item is actually done.

## Code quality

- Semantic layout landmarks: `<header>`, `<aside>`, `<main>`, `<nav>` are used in all
  three portal shells (`web/src/portals/student/index.tsx:136,194,243`,
  `web/src/portals/teacher/index.tsx:192,200,239`,
  `web/src/portals/parent/index.tsx:89,143`) — no div-soup at the shell level in the files
  read.
- `alt` text: only 2 `<img>` tags found in the entire `src` tree
  (`grep -rn "<img" src --include=*.tsx` → 2 hits); not individually inspected for alt
  content in this pass (see "Not reached") — low risk given the count, but unverified.
- z-index: at least one deliberate, low, documented value found
  (`z-20` on the student header, `web/src/portals/student/index.tsx:218`), not a `9999`
  magic number — no arbitrary z-index found in the files read, but no centralized z-index
  *scale* (CSS custom properties) was found either; REDESIGN-MISSION §4 asks for one to be
  defined in `DESIGN.md` during Phase 2, so this is prep work, not yet a defect to fix now.
- Token discipline is already partially self-enforced: `web/src/components/ui/button.tsx:14-15`
  has an inline comment insisting on the exact DESIGN.md radius token (`rounded`, not
  `rounded-md`) — the codebase already polices "no raw values" culturally, which the
  redesign's Hard Gate 3 (token discipline) can build on rather than fight.
- `web/scripts/audit.mjs` exists (`"audit": "node scripts/audit.mjs"`,
  `web/package.json:14`) but per an inline comment elsewhere is "still scoped to the four
  student routes" (`web/src/portals/parent/index.tsx:119`) — i.e., the project's own
  automated audit tool does not yet cover the teacher or parent portals. This is a real,
  named gap in the existing tooling, not something this audit is asserting from outside.
- No commented-out dead code, no `9999` z-index, and no import hallucination were found
  in the files actually read; a full-repo sweep for these was not performed (see "Not
  reached").

## Strategic omissions (checked explicitly)

| Omission | Status | Evidence |
|---|---|---|
| **404 / catch-all route** | **Missing.** `createBrowserRouter([...])` in `web/src/App.tsx:66-125` has no `path: "*"` entry and no `errorElement`. Any unmatched path renders react-router's default blank/console-error boundary. | `web/src/App.tsx:66-125` (full array read), confirmed via `grep -rni "notfound\|404" src/` returning only in-code `error.status === 404` API-response handling, never a route or component named NotFound. |
| **Error boundary (React)** | **Missing.** `grep -rn "ErrorBoundary\|componentDidCatch" src/` returns zero hits. No route in `App.tsx` sets `errorElement`/`ErrorBoundary` (react-router v7's mechanism for this). A render-time exception in any screen currently white-screens the tab. | `grep -rn "ErrorBoundary\|componentDidCatch" web/src/` → no output |
| **Skip-to-content link** | **Missing.** `grep -rni "skip.to.content\|skip-link\|skiplink" src/` returns zero hits; none of the three portal shells (`main.tsx` root, `App.tsx`, or any layout) renders one. | `grep -rni "skip.to.content\|skip-link\|skiplink" web/src/` → no output |
| **Legal links (privacy/terms)** | **Missing.** `grep -rni "privacy\|terms of service\|cookie" src/` returns zero hits anywhere in the app, including `Login.tsx` and the `Landing.tsx` marketing page (which has a pricing section but no footer legal links). | `grep -rni "privacy\|terms of service\|cookie" web/src/` → no output |
| **Favicon** | **Present**, not an omission. `index.html:5-10` wires `favicon.svg`, `apple-touch-icon`, PWA meta; `public/` has 4 icon files. | `web/index.html:5-10`, `ls web/public` |
| **Meta / OG tags** | **Missing** beyond the bare minimum. `index.html` has `<title>Lemely</title>` and a `theme-color`/PWA meta block but no `<meta name="description">`, no `og:title`/`og:description`/`og:image`, no Twitter card tags — and only one static `<title>`, so every route (including the marketing `Landing` screen) shares the same generic tab title. | `web/index.html:1-15` (full file read); `grep -n "og:\|meta name=\"description\"" web/index.html` → no output |
| **Back navigation** | **Present in exactly 1 of ~40 screens.** `navigate(-1)` only in `StudentDetail.tsx:103,116`. Every other screen relies on the sidebar (student/teacher) or nothing at all (parent, which the spec deliberately keeps nav-free — see IA report — but that only covers 4 screens, not the auth/settings top-level routes, which have no way back to `/login` other than browser Back). | `grep -rn "navigate(-1)" web/src/` → 2 hits, both in one file |
| **Cookie consent** | Not applicable / not checked against a jurisdiction requirement — no analytics or tracking cookie usage was found in any file read, so this is likely N/A rather than missing; not independently verified against GDPR/Egypt data-protection requirements (out of scope for a UI diagnose). | — |
| **Custom error copy on API failure** | **Partially present.** `StateView`'s `error` kind exists and is used (see Interactive States above) but is opt-in per screen; no global fetch-error boundary or toast-on-network-failure was found wired at the app root (`main.tsx` has no such provider). | `web/src/main.tsx:18-26` (full file) |

## Not reached (explicitly out of depth for this pass)

- The full 750-line `web/src/index.css` was read only through line ~80 (token
  provenance comments) plus a targeted grep for `font-family`; the `[data-portal="teacher"]`
  override block, the full OKLCH/hex value table, spacing scale, and any existing
  z-index scale were not read line-by-line.
- Individual screen files under `web/src/portals/student/screens/**`,
  `web/src/portals/teacher/screens/**`, and `web/src/portals/parent/screens/**` (roughly
  40 screen components) were sampled (Landing, Directions, Overview via grep/partial
  reads) but not each read in full — loading/empty/error-state completeness was verified
  structurally (the shared `StateView`/`RouteFallback` components exist and are imported
  widely) but not confirmed screen-by-screen that every screen actually renders them for
  every applicable condition.
- `alt` text content on the 2 `<img>` tags found was not inspected.
- `web/src/lib/hooks/**` and `web/src/lib/auth/**` beyond `RequireAuth.tsx` and the
  `Login`/`ParentLogin` screens were not read.
- No component-by-component 8-state (default/hover/focus-visible/active/disabled/loading/
  error/success) audit was performed beyond `Button`; `Checkbox`, `Slider`, `Chip`, `Card`
  etc. were not opened.
- `web/scripts/audit.mjs`'s actual contents (only its scope, per an inline code comment
  elsewhere) were not read.
- oxlint output (`npm run lint`) and `tsc --noEmit` (`npm run typecheck`) were not
  executed in this pass — no live lint/type-error count is reported here.
