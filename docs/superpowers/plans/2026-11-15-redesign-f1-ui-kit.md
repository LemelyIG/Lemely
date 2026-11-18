# Redesign F1: UI Kit and Shell Additions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the F1 interface contract (`web/src/components/redesign/`), restyle the kit switch to the mock, put Scan in the centre of the student tab bar and "Scan a paper" in the rail, and give the parent portal the shared shell with a child switcher and four tabs.

**Architecture:** One focused `.tsx` per component under `web/src/components/redesign/`, re-exported from `index.ts`. Pure helpers live in `.ts` modules beside them, so the node-only Vitest runner can pin them. Every mock-faithful size and colour lives in one component stylesheet, `redesign.css` (all classes `rd-`). Every animation sits inside `@media (prefers-reduced-motion: no-preference)`, and a test enforces that. The student shell changes are config plus a small `BottomNav` restyle. The parent portal swaps its bespoke header for `PortalShell`, the same shell student and teacher use, with a pure parent shell model and a new `ChildSwitcher`.

**Tech Stack:** React 19, react-router 7, TanStack Query, Tailwind 4, Phosphor icons, Vitest (node environment, `renderToStaticMarkup`), Playwright.

**Spec:** `docs/superpowers/specs/2026-11-14-redesign-implementation-design.md` (Wave 0, F1). **Master plan:** `docs/superpowers/plans/2026-11-15-redesign-00-master.md` (the F1 interface contract is the source of truth for names and signatures).

## Global Constraints

Inherits the master plan Global Constraints. Lane-specific constraints:

- **Branch:** `redesign/f1-ui-kit`, cut from `develop` after F2 (`redesign/f2-groundwork`) merges. Worktree of its own.
- **No backend, no migration.** F1 is web-only.
- **Owned files:** `web/src/components/redesign/**`, `web/tests/unit/redesign/**`, `web/src/portals/parent/{shell.tsx,shellModel.ts,ChildSwitcher.tsx}`, `web/dev-previews/redesign-kit.html`, `web/dev-previews/redesign-kit/**`, `web/e2e/redesign-shell.spec.ts`.
- **Narrow edits:** `web/src/components/ui/switch.tsx` (classes only), `web/src/components/ui/nav-shells.tsx` (emphasis tab only), `web/src/components/shell/{PortalShell.tsx,ShellSidebar.tsx,shellStyles.ts,icons.tsx}`, `web/src/portals/student/shell.tsx`, `web/src/portals/parent/index.tsx`, `web/src/index.css` (one native variable value, nothing else), `web/vite.preview.config.ts` (one entry), the source-scanning tests named in Tasks 10 and 12, `web/scripts/drift/{checks-native.mjs,checks-shell.mjs}` (label strings only).
- **Unit runner has no DOM** (`web/vitest.config.ts`: `environment: "node"`, include `tests/unit/**/*.test.ts`). Component tests are `.ts` files that render with `renderToStaticMarkup(createElement(...))`, wrapped in `MemoryRouter` when a `Link` is inside. Effects do not run there; logic that needs pinning goes in a pure `.ts` module.
- **Source rules the tests enforce** (they scan `src/components` and all of `src`):
  - No hex, `oklch(`, `rgb(` or `hsl(` literal in any `.ts`/`.tsx` (`darkConsumers.test.ts`). Colours in TSX are tokens only. `color-mix(in oklch, …)` is fine.
  - No `text-[Npx]`, `rounded-[Npx]` or `[font:…px]` in `src/components` (`design-tokens.test.ts`). Mock px sizes go in `redesign.css`.
  - No weak text role as small text in a class list (`contrastRules.test.ts`): never `text-tertiary`, `text-success`, `text-grade-*` on small type. Use `text-on-tertiary-container` and `text-success-text`.
  - Every `.tsx` under `src/components/` and `src/portals/` carries the Hallmark stamp `/* Hallmark · pre-emit critique: P_ H_ E_ S_ R_ V_ */` with every axis at 3 or more (`hallmarkStamp.test.ts`). Derive the six scores from your own critique after building the file. The stamp lines in this plan show the format; re-derive the numbers, never copy them blind.
  - `components/ui/*.tsx`: every `hover:` on a clickable has an `active:` (`check-native-invariants.mjs`).
  - Copy: no em dash in prose, no `!` in product copy (`npm run check:copy`). Mock lines that end in "!" ship with a full stop ("7 of 9 back.").
- **Route tables:** student routes live in `web/src/portals/student/index.tsx`, teacher routes in `web/src/portals/teacher/index.tsx`, parent routes in `web/src/portals/parent/index.tsx` (`/parent/children/:childId/...`). `web/src/routes.tsx` only mounts the portals.
- **Run commands** (from `web/`): `npx vitest run <files>`; `npm run typecheck`; `npm run lint` (oxlint plus `check:native`); `npm run check:copy`. Never bare `npm test`. When you touch `index.css`, `nav-shells.tsx`, the shell or parent layout, also run the source-scanning tests listed in that task.
- **UI tasks** go to the `designer` agent, who invokes the impeccable skill and reads `.claude/skills/impeccable/reference/craft-floor.md` before editing.
- **Binny:** official geometry only, from `portals/marketing/Binny.tsx` plus the mock's added `sad` mood and paper sheet. No Binny on parent surfaces.

---

## File Structure

```
web/src/components/redesign/
  redesign.css        all rd- styles and keyframes (Task 1 creates, later tasks append one block each)
  motion.ts           usePrefersReducedMotion, resolveMotion
  icons.tsx           Chevron, SmallChevron, CalendarGlyph, FlameGlyph, TopicGlyph, TrendGlyph
  Binny.tsx           Binny
  BinnyLine.tsx       BinnyLine
  rings.ts            clamp01, goldRingGeometry, goldRingDone, keyRingGeometry
  GoldRing.tsx        GoldRing
  KeyRing.tsx         KeyRing
  grades.ts           Grade, gradeColorVar, stepHeight, stepsSummary, EMPTY_GHOST_HEIGHTS
  StepsPath.tsx       StepsPath
  RowAction.tsx       RowAction (internal: Link | button | div)
  H2Row.tsx           H2Row
  HairRows.tsx        HairRows, HairRow
  RankRow.tsx         RankRow, Trend, TREND_LABEL
  topics.ts           TopicState, TOPIC_STATE_LABEL, topicState
  TopicChip.tsx       TopicChip
  TopicChips.tsx      TopicChips
  Tile.tsx            Tile, TileTone
  Walkthrough.tsx     Walkthrough
  GhostRows.tsx       GhostRows
  game.ts             comboVisible, comboRose, levelFraction
  ComboChip.tsx       ComboChip
  LevelBar.tsx        LevelBar
  countdown.ts        daysUntil, countdownTone, countdownLabel
  CountdownPill.tsx   CountdownPill
  index.ts            the barrel
web/tests/unit/redesign/
  redesignCss.test.ts binny.test.ts rings.test.ts steps.test.ts rows.test.ts
  topics.test.ts tile.test.ts states.test.ts game.test.ts contract.test.ts
  switch.test.ts studentShellScan.test.ts parentShellModel.test.ts parentShell.test.ts
web/src/portals/parent/
  shellModel.ts       parentTabs, resolveChildId, parentShellTrail, parentPageTitle, switchChildPath
  ChildSwitcher.tsx   ChildSwitcher
  shell.tsx           ParentShell (PortalShell config)
web/dev-previews/redesign-kit.html, redesign-kit/{main.tsx,Gallery.tsx}
web/e2e/redesign-shell.spec.ts
```

Extra optional props F1 adds beyond the contract (all keep the contract signatures; the lane-requested ones are marked *):
- `Binny.roamDistance`, `Binny.headCrop`* (the teacher head-crop: viewBox `30 10 140 140`, no paper, cheeks or mouth)
- `KeyRing.tone` gains `'neutral'`* (track only, no arc, for "no score"); `'warn'` is the error red*
- `StepsPath.{goalPct, goalCaption*, goalNote, ghosts, 'aria-label'}` and per paper `caption`* and `marks?: { got: number; max: number }`*; ghost bars for sparse and first run*
- `TopicChip.pct`, `TopicChips.topics[].pct`*; folded secure topics show as one "N secure" chip that unfolds on tap*
- `RankRow.sub` widened to `ReactNode`* (so a subject dot can render)
- `H2Row.right`* (a slot, e.g. the Paper 4 / Paper 2 toggle), `H2Row.titleTo`
- `Tile.status` widened from `string` to `ReactNode`; `Walkthrough.steps[].icon` widened to optional; `CountdownPill.{subject,to}`

Parent shell (lane-requested): `ChildSwitcher` keeps the current tail (`/topics`, `/weaknesses`, `/tutoring`, `/tutor-access`) when switching; the Topics tab is `/parent/children/:childId/topics`; the account menu has "Emails" pointing to `/parent/emails` (L11 mounts that route). The shell hides its own offline banner on immersive routes (`handle: { immersive: true }`, the practice run), so two banners never show at once (L3 request).

Extra helper exports: `MASTERY = { getting: 0.6, secure: 0.75 }` and `topicState(pct)` (the one shared source for mastery thresholds, L3 request), `TOPIC_STATE_LABEL`, `TOPIC_STATE_LABEL`, `TREND_LABEL`, `gradeColorVar`, `daysUntil`, `countdownLabel`. No `NumberStepper` and no `MasteryBar`: L3 and L10 plans build their own (`practice/result/MasteryBar.tsx`, `flashcards/parts/CountStepper.tsx`).

---

## Keep-list

Every live feature, state and edge case F1 touches. Task 15 checks each box.

**Student shell** (`web/src/portals/student/shell.tsx`, `components/shell/PortalShell.tsx`, `components/ui/nav-shells.tsx`)
- [ ] S1 Four route tabs plus the shell's "More" (`shell.tsx:43-48`, `PortalShell.tsx:249-260`). Changed by ruling to the mock's Home, Practice, Scan, Subjects, Me. Every destination survives: Overview is Home, Profile is Me, Correct is Scan, and Classes plus Standings, Friends, Tutors and Sessions sit in the sidebar's More group (rail, drawer and phone sheet).
- [ ] S2 Correct/Scan tab goes to `/student/correct` and prefetches the CorrectPaper chunk on pointer enter (`shell.tsx:206`).
- [ ] S3 Raised emphasis tab is excluded from the selected colour and pill rules on iOS and Android (`index.css:2121-2124`, `:2141-2152`). Kept by keeping `data-emphasis`.
- [ ] S4 Active-tab re-tap scrolls to top or pops to root (`PortalShell.tsx:190-209`).
- [ ] S5 Tab bar hidden from `sidebar` (820px) up and on immersive routes on native (`PortalShell.tsx:264`).
- [ ] S6 Native More opens the titled sheet; tablet and desktop open the drawer (`PortalShell.tsx:257`). Student: replaced by the navigation sheet (top bar menu or the Subjects tab), which lists the subject tree and the More group. Teacher and parent keep the More cell.
- [ ] S7 Sidebar foot action, hidden in the phone sheet where the bar has it (`ShellSidebar.tsx:79-82`).
- [ ] S8 Top bar action hidden on `/student/correct`, where it would do nothing, and below `shell-sm` (`shell.tsx:191`).
- [ ] S9 `viewTransition` on the upload link (`shell.tsx:140`).
- [ ] S10 Every bottom tab points at a mounted route (`tests/unit/navigation.test.ts:251-259`). Kept for every tab with a route; Practice's `/student/practice` is mounted by F1 (`PracticeEntry`); Subjects opens the sheet.
- [ ] S11 Every sidebar row reachable before is reachable after: Overview, Your classes, Standings, Friends, Tutors, Sessions, the subject tree with each subject's Practice, Flashcards and Study plan rows (`shell.tsx:88-101`, `data.ts:37-45`).

**Parent layout** (`web/src/portals/parent/index.tsx`)
- [ ] P1 Brand link to `/parent` (`:244-249`). Becomes the sidebar wordmark, `homeTo="/parent"`.
- [ ] P2 Child switcher only on a child route and only with 2+ children (`:93-100`). Kept; with one child F1 shows a static name pill (no control).
- [ ] P3 Switching keeps the `/weaknesses`, `/tutoring`, `/tutor-access` tails, everything else lands on the overview (`:120-124`). Kept, plus `/topics`.
- [ ] P4 Switcher has an accessible name at every width ("Choose which child to view", `:114`).
- [ ] P5 Notifications link with unread badge (`:228-238`, `:268-276`). Becomes the shell bell plus the Inbox tab with the same `unreadBadgeLabel` badge.
- [ ] P6 Tutors directory link (`:279-286`). Becomes a sidebar item (rail on desktop, More sheet on phone).
- [ ] P7 Settings link to `/settings/devices` (`:287-294`). Becomes the shell gear (`settingsTo`) and an account panel link.
- [ ] P8 Sign out, then `/login` (`:301-321`). Becomes the account panel's Sign out (`AccountPanel.tsx:87-90`).
- [ ] P9 Header row wraps at 320px so Sign out never clips (`:250-258`). Replaced by the shell's top bar and account panel, which fit 320px.
- [ ] P10 Breadcrumb trail with conditional "Your children", subject name from cache with code fallback, and no row when it has one crumb (`:178-225`). Ported to `parentShellTrail` and the shell top bar.
- [ ] P11 SkipLink, BadgeSync, OfflineBanner with refetch-on-retry, VerifyEmailBanner, Suspense with RouteSkeleton, ErrorBoundary reset on path, ScreenOutlet (`:334-394`). All provided by `PortalShell`.
- [ ] P12 Every route and `handle` kept, incl. the `*` not-found route last (`:396-465`).
- [ ] P13 960px content cap (`:54-58`). Not kept: the shell's page well wins (master plan shell rule). Listed in the PR.

---

## Frame-to-state table

Kit frames come from `.impeccable/mocks/student-r2/` unless named. "Gallery" is the section in `dev-previews/redesign-kit` (Task 13) that renders the state.

| Mock frame | Source | Becomes | Breakpoint | Trigger |
|---|---|---|---|---|
| `P5`, `D5` (home4, `h6.js` TAB6/DRAIL6) | `TAB6`, `DRAIL6` | Student `BottomNav` Home, Practice, raised Scan, Subjects, Me; rail Home, Practice, Me, Subjects tree, More group, foot "Scan a paper" outline | <820 tab bar; ≥1248 rail | always on student routes |
| `F_T` tablet top bar (`sjf.js` TTOP) | `.scan2` | Top bar outline "Scan a paper" | 720–1247 | not on `/student/correct` |
| `SB`, `FA` (pa.js `ptab`, `kid`) | `ptab`, `kid` | Parent `BottomNav` (Overview, Topics, Inbox, Tutoring, More) + top bar `ChildSwitcher` | <820 | parent child routes |
| `FDK`, `TDK` (pa.js rail2 + kid) | `rail2 .kid` | Parent rail with `ChildSwitcher` under the wordmark | ≥1248 | parent routes |
| `P4a`..`P4d`, `P5` stage | `BIN()` moods | `Binny` mood happy/wink/open/thinking/sad, motion idle | all | prop |
| S1 reveal (`student-r1/reveal.js`) | hop, roam, popin | `Binny` motion hop/roam/pop | all | prop |
| `F_P` Binny tip (`sjf.js` `say`) | `.say2 .bub2` | `BinnyLine` | all | prop |
| `P5` today line (`h4.js` ring4) | `ring4`, `.gring2` | `GoldRing` 32px (no centre) and 60px with `1/3` centre | all | parts 0..1 |
| `ME2` avatar ring (`h5.js` ringLv), review `final2` confidence | `.mav`, ring | `KeyRing` tones tide/gold/ok/warn | all | value |
| `F_P`, `F_D` path | `steps()` | `StepsPath` full, current bar solid, goal block | all | papers ≥ 2 |
| `S_P` sparse | `steps(ONE,{ghosts:3})` | `StepsPath` 1 paper + 3 ghosts labelled "next" | all | `ghosts` |
| `Z_P`, `FZ1` first run | `ghostPath` | `StepsPath` 0 papers, 4 ghosts at 30/45/52/70%, goal | all | `papers=[]` |
| `F_P` "More marks to win", "Papers" | `.h2row`, `.wrow`, `.rp` | `H2Row`, `HairRows`/`HairRow` | all | prop |
| `SB`, `WA`, `TDK` | `.rkr`, `rankBar`, `.rkr.on` | `RankRow` plain, with bar, selected | all | `bar`, `selected` |
| `F_P` topics folded, `F_D` unfolded | `.tmap .tm`, `.tm.more`, `.tleg` | `TopicChips` foldSecure true/false, legend | phone+tablet fold | `foldSecure` |
| `CF`, `CDK` (ph.js `gridC`) | `.pgrid.tint .ptile` | `Tile` tones tide/violet/mint/gold | all | prop |
| `PA` homework row | `.ptile.big` | `Tile big` | all | `big` |
| `Z_P`, `PZ`, `FZ1` walkthrough | `.walk2 .wn2` | `Walkthrough` numbered | all | prop |
| `L_P`, `CL`, `FL1` skeletons | `.sk2c .sk` | `GhostRows` (hairline geometry) | all | loading |
| `QA`..`RC` run header (pr.js) | `.combo` | `ComboChip` hidden <2, bump on rise | all | count |
| `D5` (h4/h5 `lvl2`), `ME2` | `.lvl2 .lb` | `LevelBar` | all | level/xp |
| `P5` pills (`top6`), `F_P` header pill | `.pill4` | `CountdownPill` neutral, near (≤30 days, Tide) | all | examDate |
| `FM` Emails switches (pa.js) | `.sw` | `components/ui/switch.tsx` restyled | all | checked |

---

## Interactions and motion

All values from the mock CSS/JS. Every animation is inside `@media (prefers-reduced-motion: no-preference)`; under `reduce` the element renders static at its end state. `Binny` additionally resolves `motion` to `'none'` in JS.

| What | Values | Reduced motion |
|---|---|---|
| Binny idle bob | `translateY(-4px)` at 50%, 3.2s ease-in-out infinite, origin `100px 200px` | static |
| Binny blink | `scaleY(.1)` at 97%, 4.6s infinite | static |
| Binny ear twitch | L `rotate(-10deg)` / R `rotate(10deg)` at 88%, 5s ease-in-out infinite, R delay .2s | static (sad ears keep their ±22deg pose) |
| Binny happy hop (`motion='hop'`) | 1.1s `cubic-bezier(.3,.7,.4,1)` infinite: 20% `scale(1.06,.94)`, 50% `translateY(-14px) scale(.97,1.03)`, 80% `scale(1.04,.96)` | static |
| Binny sad sway | `rotate(-3deg) translateY(2px)` at 50%, 4s | static |
| Binny wink tilt | `rotate(5deg)` at 50%, 2.4s | static |
| Binny thinking look | pupils `translateX(-5px)` at 50%, 3s | static |
| Binny pop-in | 0% `translateY(14px) scale(.4)` opacity 0, 60% `scale(1.12)`, .6s `cubic-bezier(.16,1,.3,1)`, then bob after .6s | appears static |
| Binny roam | 4.4s ease-in-out infinite: hops 0 → −R → 0 → +R → 0, 18px peaks, R = `roamDistance` (48px). Zone reserves R each side, so it never overlaps content | static, centred |
| Steps bar grow | `scaleY(.4)` → 1, .7s `var(--ease-out)`, delay 60ms × index, origin bottom | static |
| Steps bar hover | `translate 0 -3px`, `saturate(1.15)`, .2s | none |
| Topic chip hover | `translate 0 -2px`, .2s | none |
| Row press | `scale(.985)`, 150ms | kept (no motion query: press feedback is instant) |
| Tile press / hover | `scale(.97)` / `brightness(.98)`, 150ms | kept |
| Combo bump | on rise: 0% `scale(.4)`, 60% `scale(1.15)`, .5s `var(--ease-out)` | none |
| Switch thumb | `translateX` 20px, .2s ease | none (`motion-reduce:transition-none`) |
| Student Scan tab press | existing `active:scale-[0.98]` | unchanged |

---

## Task 1: Kit foundation, Binny and BinnyLine

**Agent:** designer.

**Files:**
- Create: `web/src/components/redesign/redesign.css`, `motion.ts`, `icons.tsx`, `Binny.tsx`, `BinnyLine.tsx`, `index.ts`
- Test: `web/tests/unit/redesign/redesignCss.test.ts`, `web/tests/unit/redesign/binny.test.ts`

**Interfaces:**
- Produces: `Binny`, `BinnyLine`, `BinnyMood`, `BinnyMotion` (contract); `usePrefersReducedMotion(): boolean`, `resolveMotion<T extends string>(m: T, reduced: boolean): T | 'none'`; icons `Chevron`, `SmallChevron`, `CalendarGlyph`, `FlameGlyph`, `TopicGlyph({state})`, `TrendGlyph({trend})` used by later tasks.

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/redesign/redesignCss.test.ts`:

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const CSS_PATH = join(fileURLToPath(new URL("../../../", import.meta.url)), "src/components/redesign/redesign.css")

/** The CSS with every `@media (prefers-reduced-motion: no-preference) { … }` block removed (brace-balanced). */
export function outsideMotionBlocks(css: string): string {
  const OPEN = "@media (prefers-reduced-motion: no-preference)"
  let out = ""
  let i = 0
  while (i < css.length) {
    const at = css.indexOf(OPEN, i)
    if (at === -1) return out + css.slice(i)
    out += css.slice(i, at)
    let j = css.indexOf("{", at)
    let depth = 0
    for (; j < css.length; j++) {
      if (css[j] === "{") depth++
      else if (css[j] === "}" && --depth === 0) break
    }
    i = j + 1
  }
  return out
}

describe("redesign.css motion rule", () => {
  const css = readFileSync(CSS_PATH, "utf8").replace(/\/\*[\s\S]*?\*\//g, "")

  it("goes red on a planted animation outside the motion block", () => {
    expect(outsideMotionBlocks(".a{animation:x 1s}")).toMatch(/animation\s*:/)
    expect(outsideMotionBlocks("@media (prefers-reduced-motion: no-preference) { .a { animation: x 1s } }")).not.toMatch(/animation\s*:/)
  })

  it("declares every animation inside prefers-reduced-motion: no-preference", () => {
    expect(outsideMotionBlocks(css)).not.toMatch(/animation\s*:/)
  })

  it("uses only rd- class selectors", () => {
    const selectors = [...outsideMotionBlocks(css).matchAll(/(^|\})\s*([^{}@]+)\{/g)].map((m) => m[2].trim())
    const foreign = selectors.flatMap((s) => [...s.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1])).filter((c) => !c.startsWith("rd-"))
    expect(foreign).toEqual([])
  })
})
```

`web/tests/unit/redesign/binny.test.ts`:

```ts
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { Binny, BinnyLine } from "@/components/redesign"
import { resolveMotion } from "@/components/redesign/motion"

const html = (props: Parameters<typeof Binny>[0]) => renderToStaticMarkup(createElement(Binny, props))

describe("Binny", () => {
  it("carries mood and motion as data attributes and sizes 1:1.1", () => {
    const out = html({ mood: "happy", size: 96 })
    expect(out).toMatch(/data-mood="happy"/)
    expect(out).toMatch(/data-motion="idle"/)
    expect(out).toMatch(/width="96" height="106"/)
    expect(out).toMatch(/viewBox="0 0 200 220"/)
  })
  it("happy: both eyes are arcs, no pupils", () => {
    const out = html({ mood: "happy" })
    expect(out).toContain("M68 143 Q78 130 88 143")
    expect(out).toContain("M112 143 Q122 130 132 143")
    expect(out).not.toContain("rd-bn-pupil")
  })
  it("wink: left eye open, right an arc", () => {
    const out = html({ mood: "wink" })
    expect(out.match(/rd-bn-pupil/g)).toHaveLength(1)
    expect(out).toContain("M112 143 Q122 130 132 143")
  })
  it("open: open mouth", () => {
    expect(html({ mood: "open" })).toContain("M86 160 H114")
  })
  it("thinking: pupils look right and the mouth is flat", () => {
    const out = html({ mood: "thinking" })
    expect(out).toMatch(/cx="84" cy="141"/)
    expect(out).toMatch(/cx="128" cy="141"/)
    expect(out).toContain("M92 167 H108")
  })
  it("sad: pupils look down and the mouth frowns", () => {
    const out = html({ mood: "sad" })
    expect(out).toMatch(/cx="80" cy="145"/)
    expect(out).toContain("M90 172 Q100 163 110 172")
  })
  it("draws the clipped paper sheet behind the body", () => {
    const out = html({ mood: "open" })
    expect(out.indexOf('transform="rotate(-3 100 192)"')).toBeLessThan(out.indexOf("M40 104 H160"))
  })
  it("is hidden from assistive tech by default, an img when asked", () => {
    expect(html({ mood: "open" })).toMatch(/aria-hidden="true"/)
    const named = html({ mood: "open", "aria-hidden": false })
    expect(named).toMatch(/role="img"/)
    expect(named).toMatch(/aria-label="Binny"/)
  })
  it("roam reserves a free zone on both sides", () => {
    const out = html({ mood: "happy", motion: "roam", roamDistance: 40 })
    expect(out).toMatch(/^<span class="rd-binny-zone" style="--rd-roam:40px">/)
  })
  it("headCrop: the teacher head-and-shoulders crop, square, no paper and no mouth", () => {
    const out = html({ mood: "happy", size: 32, headCrop: true })
    expect(out).toMatch(/viewBox="30 10 140 140"/)
    expect(out).toMatch(/width="32" height="32"/)
    expect(out).toContain("M40 104 H160 L154 150 H46 Z")
    expect(out).toContain('transform="translate(0 -8)"')
    expect(out).not.toContain("rotate(-3 100 192)")
    expect(out).not.toContain("M90 163 Q100 172 110 163")
  })
  it("uses no literal colours (tokens only)", () => {
    expect(html({ mood: "sad" })).not.toMatch(/#[0-9a-f]{3,8}\b|oklch\(/i)
  })
})

describe("resolveMotion", () => {
  it("turns every motion into none under reduced motion", () => {
    for (const m of ["idle", "hop", "roam", "pop", "none"] as const) expect(resolveMotion(m, true)).toBe("none")
    expect(resolveMotion("hop", false)).toBe("hop")
  })
})

describe("BinnyLine", () => {
  it("renders Binny at 60px beside a speech bubble", () => {
    const out = renderToStaticMarkup(createElement(BinnyLine, { mood: "happy", line: "7 marks to A*" }))
    expect(out).toMatch(/class="rd-say"/)
    expect(out).toMatch(/width="60" height="66"/)
    expect(out).toMatch(/<p class="rd-bubble">7 marks to A\*<\/p>/)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx vitest run tests/unit/redesign/redesignCss.test.ts tests/unit/redesign/binny.test.ts`
Expected: FAIL, `ENOENT … redesign.css` and `Failed to resolve import "@/components/redesign"`.

- [ ] **Step 3: Write the implementation**

`web/src/components/redesign/redesign.css`:

```css
/*
 * F1 redesign kit (docs/superpowers/plans/2026-11-15-redesign-f1-ui-kit.md).
 * Mock-faithful sizes from .impeccable/mocks/student-r2/{t,pr,ph,pa}.css, mapped
 * onto the Abyss tokens in index.css. A component stylesheet, not index.css: the
 * kit's px type sizes are banned as `text-[Npx]` in TSX (design-tokens.test.ts),
 * and this file adds no design token. Every class is `rd-`. Every animation sits
 * inside the prefers-reduced-motion: no-preference block (redesignCss.test.ts).
 */

/* ── Binny (mock h.js BIN, t.css .bn) ───────────────────────────────────── */
.rd-binny {
  display: block;
  flex: none;
  overflow: visible;
  --rd-bn-body: var(--md-primary);
  --rd-bn-face: var(--md-on-primary);
  --rd-bn-pupil: var(--md-on-surface);
}
:root[data-theme="dark"] .rd-binny {
  --rd-bn-body: var(--md-on-primary);
  --rd-bn-face: var(--md-on-surface);
  --rd-bn-pupil: var(--md-surface);
}
.rd-binny .rd-bn-body { transform-origin: 100px 200px; }
.rd-binny .rd-bn-ear { transform-box: fill-box; transform-origin: 50% 100%; }
.rd-binny .rd-bn-eyes { transform-box: fill-box; transform-origin: 50% 50%; }
.rd-binny[data-mood="sad"] .rd-bn-ear-l { transform: rotate(-22deg); }
.rd-binny[data-mood="sad"] .rd-bn-ear-r { transform: rotate(22deg); }
.rd-binny-zone { display: inline-flex; justify-content: center; padding-inline: var(--rd-roam, 48px); }

/* ── BinnyLine (t.css .say2 / .bub2) ────────────────────────────────────── */
.rd-say { display: flex; align-items: center; gap: 6px; }
.rd-bubble {
  position: relative;
  margin: 0;
  padding: 9px 14px;
  border-radius: 16px;
  background: var(--md-surface-container-lowest);
  color: var(--md-primary);
  font: 700 17px/1.2 var(--font-sans);
  box-shadow: 0 3px 10px -3px color-mix(in oklch, var(--md-shadow) 25%, transparent);
}
.rd-bubble::before {
  content: "";
  position: absolute;
  inset-inline-start: -6px;
  top: 50%;
  width: 12px;
  height: 12px;
  border-radius: 2px;
  background: inherit;
  rotate: 45deg;
  translate: 0 -50%;
}

@media (prefers-reduced-motion: no-preference) {
  .rd-binny:not([data-motion="none"]) .rd-bn-eyes { animation: rd-blink 4.6s infinite; }
  .rd-binny:not([data-motion="none"]):not([data-mood="sad"]) .rd-bn-ear-l { animation: rd-ear-l 5s ease-in-out infinite; }
  .rd-binny:not([data-motion="none"]):not([data-mood="sad"]) .rd-bn-ear-r { animation: rd-ear-r 5s ease-in-out 0.2s infinite; }
  .rd-binny[data-mood="thinking"]:not([data-motion="none"]) .rd-bn-pupil { animation: rd-look 3s ease-in-out infinite; }
  .rd-binny:is([data-motion="idle"], [data-motion="roam"]) .rd-bn-body { animation: rd-bob 3.2s ease-in-out infinite; }
  .rd-binny[data-motion="idle"][data-mood="sad"] .rd-bn-body { animation: rd-sway 4s ease-in-out infinite; }
  .rd-binny[data-motion="idle"][data-mood="wink"] .rd-bn-body { animation: rd-tilt 2.4s ease-in-out infinite; }
  .rd-binny[data-motion="hop"] .rd-bn-body { animation: rd-hop 1.1s cubic-bezier(0.3, 0.7, 0.4, 1) infinite; }
  .rd-binny[data-motion="pop"] { animation: rd-popin 0.6s cubic-bezier(0.16, 1, 0.3, 1) both; }
  .rd-binny[data-motion="pop"] .rd-bn-body { animation: rd-bob 3.2s ease-in-out 0.6s infinite; }
  .rd-binny[data-motion="roam"] { animation: rd-roam 4.4s ease-in-out infinite; }
}
@keyframes rd-bob { 50% { transform: translateY(-4px); } }
@keyframes rd-blink { 0%, 94%, 100% { transform: scaleY(1); } 97% { transform: scaleY(0.1); } }
@keyframes rd-ear-l { 0%, 80%, 100% { transform: rotate(0); } 88% { transform: rotate(-10deg); } }
@keyframes rd-ear-r { 0%, 80%, 100% { transform: rotate(0); } 88% { transform: rotate(10deg); } }
@keyframes rd-look { 0%, 100% { transform: translateX(0); } 50% { transform: translateX(-5px); } }
@keyframes rd-sway { 50% { transform: rotate(-3deg) translateY(2px); } }
@keyframes rd-tilt { 50% { transform: rotate(5deg); } }
@keyframes rd-hop {
  0%, 100% { transform: translateY(0) scale(1, 1); }
  20% { transform: translateY(0) scale(1.06, 0.94); }
  50% { transform: translateY(-14px) scale(0.97, 1.03); }
  80% { transform: translateY(0) scale(1.04, 0.96); }
}
@keyframes rd-popin {
  0% { transform: translateY(14px) scale(0.4); opacity: 0; }
  60% { transform: scale(1.12); }
  100% { transform: none; opacity: 1; }
}
@keyframes rd-roam {
  0%, 50%, 100% { translate: 0 0; }
  12.5% { translate: calc(var(--rd-roam, 48px) * -0.5) -18px; }
  25% { translate: calc(var(--rd-roam, 48px) * -1) 0; }
  37.5% { translate: calc(var(--rd-roam, 48px) * -0.5) -18px; }
  62.5% { translate: calc(var(--rd-roam, 48px) * 0.5) -18px; }
  75% { translate: var(--rd-roam, 48px) 0; }
  87.5% { translate: calc(var(--rd-roam, 48px) * 0.5) -18px; }
}
```

`web/src/components/redesign/motion.ts`:

```ts
import { useSyncExternalStore } from "react"

const QUERY = "(prefers-reduced-motion: reduce)"

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {}
  const mq = window.matchMedia(QUERY)
  mq.addEventListener("change", onChange)
  return () => mq.removeEventListener("change", onChange)
}

function snapshot(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(QUERY).matches
}

/** True when the reader asked for reduced motion. False on the server and in node tests. */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false)
}

/** Every motion becomes 'none' under reduced motion (F1 contract). */
export function resolveMotion<T extends string>(motion: T, reduced: boolean): T | "none" {
  return reduced ? "none" : motion
}
```

`web/src/components/redesign/icons.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { TopicState } from "./topics"

/* The mock's drawn stroke icons (t.js CHEV/SUB/CAL/FLAME, sjf.js IC, pa.js AR). Decorative: aria-hidden. */

export function Chevron() {
  return (
    <svg className="rd-chev" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M7 4l5 5-5 5" />
    </svg>
  )
}

export function SmallChevron() {
  return (
    <svg className="rd-chev" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M6 3.5 10.5 8 6 12.5" />
    </svg>
  )
}

export function CalendarGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true" focusable="false">
      <rect x="3" y="4.5" width="14" height="12" rx="2.5" />
      <path d="M3 8.5h14M7 2.5v4M13 2.5v4" />
    </svg>
  )
}

export function FlameGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M10 2.5c.5 3 4.5 4.5 4.5 9a4.5 4.5 0 0 1-9 0c0-2 1-3.2 2-4 .2 1.6 1 2.4 2 2.6C9 8 9.5 5 10 2.5Z" />
    </svg>
  )
}

const TOPIC_PATHS: Record<TopicState, React.ReactNode> = {
  secure: <path d="M2.5 6.3 5 8.6l4.5-5" />,
  getting: <path d="M2.5 6h7" />,
  work: (
    <>
      <circle cx="6" cy="6" r="3.6" />
      <circle cx="6" cy="6" r=".6" fill="currentColor" />
    </>
  ),
}

/** Target for Work on (never a down arrow), dash for Getting there, tick for Secure. */
export function TopicGlyph({ state }: { state: TopicState }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {TOPIC_PATHS[state]}
    </svg>
  )
}

const TREND_PATHS = {
  better: "M6 10V2.5M2.8 5.5 6 2.3l3.2 3.2",
  worse: "M6 2v7.5M2.8 6.5 6 9.7l3.2-3.2",
  same: "M2 6h8",
} as const

export function TrendGlyph({ trend }: { trend: keyof typeof TREND_PATHS }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={TREND_PATHS[trend]} />
    </svg>
  )
}
```

`icons.tsx` imports `TopicState` from `./topics`, which Task 5 creates. Create `web/src/components/redesign/topics.ts` now with its final content (Task 5 adds its tests):

```ts
export type TopicState = "work" | "getting" | "secure"

export const TOPIC_STATE_LABEL: Record<TopicState, string> = {
  work: "Work on",
  getting: "Getting there",
  secure: "Secure",
}

/**
 * The one shared source for mastery thresholds (mock sjf.js `lvl`, pr.css lvl3 zones),
 * as fractions of the marks. Every lane reads these; none hard-codes 60 or 75.
 */
export const MASTERY = { getting: 0.6, secure: 0.75 } as const

/** A topic's state from its percentage (0..100). */
export function topicState(pct: number): TopicState {
  const fraction = pct / 100
  if (fraction >= MASTERY.secure) return "secure"
  if (fraction >= MASTERY.getting) return "getting"
  return "work"
}
```

`web/src/components/redesign/Binny.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { CSSProperties } from "react"
import { cn } from "@/lib/utils"
import { resolveMotion, usePrefersReducedMotion } from "./motion"
import "./redesign.css"

export type BinnyMood = "happy" | "wink" | "open" | "thinking" | "sad"
export type BinnyMotion = "idle" | "hop" | "roam" | "pop" | "none"

export interface BinnyProps {
  mood: BinnyMood
  size?: number
  motion?: BinnyMotion
  className?: string
  "aria-hidden"?: boolean
  /** Roam only: how far Binny wanders each side. The zone reserves it, so he never overlaps content. */
  roamDistance?: number
  /** Teacher screens: the small head-and-shoulders crop (Binny.tsx `compact`), square, no paper, cheeks or mouth. */
  headCrop?: boolean
}

const EAR_L = "M66 102 L62 40 Q62 16 75 16 Q88 16 88 40 L84 102"
const EAR_R = "M116 102 L112 40 Q112 16 125 16 Q138 16 138 40 L134 102"
const ARC_L = "M68 143 Q78 130 88 143"
const ARC_R = "M112 143 Q122 130 132 143"

function OpenEye({ cx, pupilX, pupilY }: { cx: number; pupilX: number; pupilY: number }) {
  return (
    <>
      <ellipse cx={cx} cy="140" rx="11" ry="12" fill="var(--rd-bn-face)" />
      <circle className="rd-bn-pupil" cx={pupilX} cy={pupilY} r="6.5" fill="var(--rd-bn-pupil)" />
    </>
  )
}

function ClosedEye({ d }: { d: string }) {
  return <path d={d} fill="none" stroke="var(--rd-bn-face)" strokeWidth="6" strokeLinecap="round" />
}

function Mouth({ mood }: { mood: BinnyMood }) {
  if (mood === "open") {
    return <path d="M86 160 H114 Q113 180 100 180 Q87 180 86 160Z" fill="var(--rd-bn-pupil)" stroke="var(--rd-bn-face)" strokeWidth="3" strokeLinejoin="round" />
  }
  const d = mood === "sad" ? "M90 172 Q100 163 110 172" : mood === "thinking" ? "M92 167 H108" : "M90 163 Q100 172 110 163"
  return <path d={d} fill="none" stroke="var(--rd-bn-face)" strokeWidth="4.5" strokeLinecap="round" />
}

/**
 * The official Binny (portals/marketing/Binny.tsx geometry) with the clipped
 * paper sheet and the mock's added sad mood (student-r2/h.js BIN). Student
 * screens only, once per screen. Under prefers-reduced-motion every motion is 'none'.
 */
export function Binny({ mood, size = 96, motion = "idle", className, "aria-hidden": ariaHidden = true, roamDistance = 48, headCrop = false }: BinnyProps) {
  const reduced = usePrefersReducedMotion()
  const resolved = resolveMotion(motion, reduced)
  const dx = mood === "thinking" ? 4 : 0
  const dy = mood === "sad" ? 4 : 0
  const a11y = ariaHidden ? { "aria-hidden": true as const } : { role: "img", "aria-label": "Binny" }
  const eyes = (
    <g className="rd-bn-eyes">
      {mood === "happy" ? <ClosedEye d={ARC_L} /> : <OpenEye cx={78} pupilX={80 + dx} pupilY={141 + dy} />}
      {mood === "happy" || mood === "wink" ? <ClosedEye d={ARC_R} /> : <OpenEye cx={122} pupilX={124 + dx} pupilY={141 + dy} />}
    </g>
  )
  const svg = (
    <svg
      className={cn("rd-binny", className)}
      data-mood={mood}
      data-motion={resolved}
      data-crop={headCrop ? "head" : undefined}
      width={size}
      height={headCrop ? size : Math.round(size * 1.1)}
      viewBox={headCrop ? "30 10 140 140" : "0 0 200 220"}
      overflow="visible"
      focusable="false"
      {...a11y}
    >
      <g className="rd-bn-body">
        {headCrop ? null : (
          <rect x="54" y="168" width="92" height="48" rx="4" fill="var(--md-surface-container-lowest)" stroke="var(--md-outline)" strokeWidth="2" transform="rotate(-3 100 192)" />
        )}
        <g className="rd-bn-ear rd-bn-ear-l" transform={headCrop ? "rotate(-6 75 100)" : undefined}>
          <path d={EAR_L} fill="none" stroke="var(--binny-steel)" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round" />
        </g>
        <g className="rd-bn-ear rd-bn-ear-r" transform={headCrop ? "rotate(6 125 100)" : undefined}>
          <path d={EAR_R} fill="none" stroke="var(--binny-steel)" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round" />
        </g>
        <path d={headCrop ? "M40 104 H160 L154 150 H46 Z" : "M40 104 H160 L152 186 Q151 196 141 196 H59 Q49 196 48 186 Z"} fill="var(--rd-bn-body)" />
        <rect x="34" y="94" width="132" height="18" rx="8" fill="color-mix(in oklch, var(--rd-bn-body) 65%, black)" />
        {headCrop ? (
          <g transform="translate(0 -8)">{eyes}</g>
        ) : (
          <>
            <ellipse cx="62" cy="160" rx="9" ry="5.5" opacity=".55" fill="var(--binny-cheek)" />
            <ellipse cx="138" cy="160" rx="9" ry="5.5" opacity=".55" fill="var(--binny-cheek)" />
            {eyes}
            <Mouth mood={mood} />
          </>
        )}
      </g>
    </svg>
  )
  if (resolved !== "roam") return svg
  return (
    <span className="rd-binny-zone" style={{ "--rd-roam": `${roamDistance}px` } as CSSProperties}>
      {svg}
    </span>
  )
}
```

`web/src/components/redesign/BinnyLine.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Binny, type BinnyMood, type BinnyMotion } from "./Binny"

export interface BinnyLineProps {
  mood: BinnyMood
  /** 2–4 words. Binny appears once per screen. */
  line: string
  motion?: BinnyMotion
  size?: number
}

/** Binny with a short speech bubble (mock .say2 / .bub2). */
export function BinnyLine({ mood, line, motion = "idle", size = 60 }: BinnyLineProps) {
  return (
    <div className="rd-say">
      <Binny mood={mood} size={size} motion={motion} />
      <p className="rd-bubble">{line}</p>
    </div>
  )
}
```

`web/src/components/redesign/index.ts`:

```ts
/* F1 redesign kit barrel: every name in the master plan's F1 interface contract. */
export { Binny, type BinnyMood, type BinnyMotion, type BinnyProps } from "./Binny"
export { BinnyLine, type BinnyLineProps } from "./BinnyLine"
export { type TopicState, MASTERY, TOPIC_STATE_LABEL, topicState } from "./topics"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npx vitest run tests/unit/redesign/redesignCss.test.ts tests/unit/redesign/binny.test.ts tests/unit/hallmarkStamp.test.ts tests/unit/darkConsumers.test.ts tests/unit/design-tokens.test.ts`
Expected: PASS.

- [ ] **Step 5: Typecheck, lint, commit**

```bash
cd web && npm run typecheck && npx oxlint src/components/redesign
cd .. && PYTHONPATH=$PWD pre-commit run --files web/src/components/redesign/*.ts* web/src/components/redesign/redesign.css web/tests/unit/redesign/redesignCss.test.ts web/tests/unit/redesign/binny.test.ts
git add web/src/components/redesign web/tests/unit/redesign/redesignCss.test.ts web/tests/unit/redesign/binny.test.ts
git commit -S -m "feat(web): redesign kit foundation with Binny and BinnyLine" -- web/src/components/redesign web/tests/unit/redesign/redesignCss.test.ts web/tests/unit/redesign/binny.test.ts
```

---

## Task 2: GoldRing and KeyRing

**Agent:** designer.

**Files:**
- Create: `web/src/components/redesign/rings.ts`, `GoldRing.tsx`, `KeyRing.tsx`
- Modify: `web/src/components/redesign/redesign.css` (append), `index.ts` (append)
- Test: `web/tests/unit/redesign/rings.test.ts`

**Interfaces:**
- Consumes: `ringDash(value0to100, circumference)` from `@/components/ui/progress-ring`.
- Produces: `GoldRing(p: { parts: [number, number, number]; size?: number; label?: string; center?: ReactNode })`, `KeyRing(p: { value: number; size?: number; tone?: 'tide'|'gold'|'ok'|'warn'; center: ReactNode; label: string })`, `clamp01(v: number): number` (used by Tasks 4 and 8).

- [ ] **Step 1: Write the failing test**

`web/tests/unit/redesign/rings.test.ts`:

```ts
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { GoldRing, KeyRing } from "@/components/redesign"
import { clamp01, goldRingDone, goldRingGeometry, keyRingGeometry } from "@/components/redesign/rings"

describe("ring geometry", () => {
  it("matches the mock ring4 at 32px (r 13, stroke 4.5, 23-unit segments)", () => {
    const g = goldRingGeometry(32)
    expect(g.r).toBe(13)
    expect(g.stroke).toBe(4.5)
    expect(g.dash).toBeCloseTo(23.1, 0)
  })
  it("matches the mock level ring at 92px (r 42, stroke 6)", () => {
    expect(keyRingGeometry(92)).toMatchObject({ r: 42, stroke: 6 })
  })
  it("clamps to 0..1 and treats NaN as 0", () => {
    expect([clamp01(-1), clamp01(0.4), clamp01(3), clamp01(Number.NaN)]).toEqual([0, 0.4, 1, 0])
  })
  it("counts only complete parts as done", () => {
    expect(goldRingDone([1, 0.99, 0])).toBe(1)
  })
})

describe("GoldRing", () => {
  it("is gold only for a complete part", () => {
    const out = renderToStaticMarkup(createElement(GoldRing, { parts: [1, 0.5, 0] }))
    expect(out.match(/rd-ring-gold/g)).toHaveLength(1)
    expect(out.match(/rd-ring-partial/g)).toHaveLength(1)
    expect(out).toMatch(/aria-label="1 of 3 done"/)
  })
  it("renders a centre and a custom label", () => {
    const out = renderToStaticMarkup(createElement(GoldRing, { parts: [1, 1, 1], size: 60, label: "Today: 3 of 3", center: "3/3" }))
    expect(out).toMatch(/aria-label="Today: 3 of 3"/)
    expect(out).toMatch(/<span class="rd-ring-center" aria-hidden="true">3\/3<\/span>/)
  })
})

describe("KeyRing", () => {
  it("draws the value arc in its tone with the label as the name", () => {
    const out = renderToStaticMarkup(createElement(KeyRing, { value: 0.48, tone: "gold", center: "7", label: "Level 7, 48% to level 8" }))
    expect(out).toMatch(/role="img" aria-label="Level 7, 48% to level 8"/)
    expect(out).toContain("rd-ring-tone-gold")
    expect(out).toMatch(/stroke-dasharray="126\.7 263\.9"/)
  })
  it("warn is the error red; neutral draws no arc and mutes the centre", () => {
    const warn = renderToStaticMarkup(createElement(KeyRing, { value: 0.62, tone: "warn", center: "62%", label: "Confidence 62%" }))
    expect(warn).toContain("rd-ring-tone-warn")
    const none = renderToStaticMarkup(createElement(KeyRing, { value: 0, tone: "neutral", center: "–", label: "No score yet" }))
    expect(none).toMatch(/data-tone="neutral"/)
    expect(none).not.toContain("stroke-dasharray")
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run tests/unit/redesign/rings.test.ts`
Expected: FAIL, `GoldRing` is not exported.

- [ ] **Step 3: Write the implementation**

`web/src/components/redesign/rings.ts`:

```ts
/** 0..1, with NaN and infinities as 0. */
export function clamp01(value: number): number {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0
}

/** Mock ring4 (32px: r 13, stroke 4.5, dash 23 of each 27.2 third), scaled. */
export function goldRingGeometry(size: number) {
  const r = (size * 13) / 32
  const stroke = (size * 4.5) / 32
  const circumference = 2 * Math.PI * r
  const third = circumference / 3
  return { r, stroke, circumference, third, dash: third * (23 / 27.2) }
}

export function goldRingDone(parts: readonly number[]): number {
  return parts.filter((p) => clamp01(p) >= 1).length
}

/** Mock level ring (92px: r 42, stroke 6), scaled. */
export function keyRingGeometry(size: number) {
  const r = (size * 42) / 92
  const stroke = (size * 6) / 92
  return { r, stroke, circumference: 2 * Math.PI * r }
}
```

`web/src/components/redesign/GoldRing.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { clamp01, goldRingDone, goldRingGeometry } from "./rings"
import "./redesign.css"

export interface GoldRingProps {
  parts: [number, number, number]
  size?: number
  label?: string
  center?: ReactNode
}

const f = (n: number) => n.toFixed(2)

/** The gold three-part ring (mock ring4 / gring2). Gold only when a part is complete. */
export function GoldRing({ parts, size = 32, label, center }: GoldRingProps) {
  const { r, stroke, circumference, third, dash } = goldRingGeometry(size)
  const half = size / 2
  return (
    <span className="rd-goldring" role="img" aria-label={label ?? `${goldRingDone(parts)} of 3 done`} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" focusable="false">
        {parts.map((raw, i) => {
          const v = clamp01(raw)
          const ring = {
            r: f(r),
            cx: half,
            cy: half,
            fill: "none",
            strokeWidth: f(stroke),
            strokeLinecap: "round" as const,
            strokeDashoffset: f(-i * third),
            transform: `rotate(-90 ${half} ${half})`,
          }
          return (
            <g key={i} data-part={v >= 1 ? "done" : v > 0 ? "partial" : "empty"}>
              <circle {...ring} className={v >= 1 ? "rd-ring-gold" : "rd-ring-track"} strokeDasharray={`${f(dash)} ${f(circumference - dash)}`} />
              {v > 0 && v < 1 ? (
                <circle {...ring} className="rd-ring-partial" strokeDasharray={`${f(dash * v)} ${f(circumference - dash * v)}`} />
              ) : null}
            </g>
          )
        })}
      </svg>
      {center !== undefined ? (
        <span className="rd-ring-center" aria-hidden="true">
          {center}
        </span>
      ) : null}
    </span>
  )
}
```

`web/src/components/redesign/KeyRing.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { ringDash } from "@/components/ui/progress-ring"
import { clamp01, keyRingGeometry } from "./rings"
import "./redesign.css"

export interface KeyRingProps {
  value: number
  size?: number
  /** 'warn' is the error red (confidence under 70%); 'neutral' draws the track only, for "no score". */
  tone?: "tide" | "gold" | "ok" | "warn" | "neutral"
  center: ReactNode
  /** The accessible name; include the key number, because the centre is hidden from assistive tech. */
  label: string
}

/** The single big key-number ring (confidence, level). */
export function KeyRing({ value, size = 92, tone = "tide", center, label }: KeyRingProps) {
  const { r, stroke, circumference } = keyRingGeometry(size)
  const half = size / 2
  const ring = { r: r.toFixed(1), cx: half, cy: half, fill: "none", strokeWidth: stroke.toFixed(1) }
  return (
    <span className="rd-keyring" data-tone={tone} role="img" aria-label={label} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" focusable="false">
        <circle {...ring} className="rd-ring-track" />
        {tone === "neutral" ? null : (
          <circle
            {...ring}
            className={`rd-ring-tone-${tone}`}
            strokeLinecap="round"
            strokeDasharray={ringDash(clamp01(value) * 100, circumference)}
            transform={`rotate(-90 ${half} ${half})`}
          />
        )}
      </svg>
      <span className="rd-ring-center" aria-hidden="true">
        {center}
      </span>
    </span>
  )
}
```

Append to `redesign.css`:

```css
/* ── GoldRing, KeyRing (h4.js ring4, t.css .gring2, h5.js ringLv) ───────── */
.rd-goldring, .rd-keyring { position: relative; display: inline-grid; place-items: center; flex: none; }
.rd-goldring svg, .rd-keyring svg { position: absolute; inset: 0; }
.rd-ring-track { stroke: var(--md-surface-container-highest); }
.rd-ring-gold { stroke: var(--md-tertiary); }
.rd-ring-partial { stroke: var(--md-outline); }
.rd-ring-tone-tide { stroke: var(--md-inverse-primary); }
.rd-ring-tone-gold { stroke: var(--md-tertiary); }
.rd-ring-tone-ok { stroke: var(--md-success); }
.rd-ring-tone-warn { stroke: var(--md-error); }
.rd-ring-center { position: relative; font: 700 14px/1 var(--font-mono); color: var(--md-on-surface); }
.rd-keyring .rd-ring-center { font: 800 28px/1 var(--font-display); color: var(--md-primary); }
.rd-keyring[data-tone="warn"] .rd-ring-center { color: var(--md-error); }
.rd-keyring[data-tone="neutral"] .rd-ring-center { color: var(--md-on-surface-variant); }
```

Append to `index.ts`:

```ts
export { GoldRing, type GoldRingProps } from "./GoldRing"
export { KeyRing, type KeyRingProps } from "./KeyRing"
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run tests/unit/redesign/rings.test.ts tests/unit/redesign/redesignCss.test.ts`
Expected: PASS. If the KeyRing dash string differs only in the last digit, the expected value in the test is wrong, not the code: `ringDash(48, 2π·42)` is `"126.7 263.9"`.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(web): redesign GoldRing and KeyRing" -- web/src/components/redesign/rings.ts web/src/components/redesign/GoldRing.tsx web/src/components/redesign/KeyRing.tsx web/src/components/redesign/redesign.css web/src/components/redesign/index.ts web/tests/unit/redesign/rings.test.ts
```

(Run `pre-commit run --files <those paths>` with `PYTHONPATH=<worktree>` before every commit in this plan.)

---

## Task 3: StepsPath

**Agent:** designer.

**Files:**
- Create: `web/src/components/redesign/grades.ts`, `StepsPath.tsx`
- Modify: `redesign.css` (append), `index.ts` (append)
- Test: `web/tests/unit/redesign/steps.test.ts`

**Interfaces:**
- Produces: `type Grade = string`; `gradeColorVar(grade: string): string` (`"var(--grade-b)"`); `stepHeight(pct: number, goalPct?: number): number` (0..100); `StepsPath(p: StepsPathProps)` with `papers: { id: string; label: string; grade: Grade; pct: number; caption?: string; marks?: { got: number; max: number } }[]`, `goal?`, `onSelect?`, `goalPct?`, `goalCaption?` (the whole line under the goal block, e.g. "68/80 · A* line · 7 to go"; default "A* line"), `goalNote?` (inside the block), `ghosts?`, `'aria-label'?`. A paper's Mono line is `caption`, else `got/max` from `marks`.

- [ ] **Step 1: Write the failing test**

`web/tests/unit/redesign/steps.test.ts`:

```ts
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { StepsPath } from "@/components/redesign"
import { gradeColorVar, stepHeight, stepsSummary } from "@/components/redesign/grades"

const PAPERS = [
  { id: "p1", label: "Oct", grade: "C", pct: 56, caption: "45/80" },
  { id: "p2", label: "Jan", grade: "B", pct: 60, marks: { got: 48, max: 80 } },
  { id: "p3", label: "Apr", grade: "A", pct: 76, caption: "61/80" },
]
const html = (p: Parameters<typeof StepsPath>[0]) => renderToStaticMarkup(createElement(StepsPath, p))

describe("grades helpers", () => {
  it("maps grades to the token ramp", () => {
    expect(gradeColorVar("A*")).toBe("var(--grade-a-star)")
    expect(gradeColorVar("b")).toBe("var(--grade-b)")
    expect(gradeColorVar("?")).toBe("var(--md-outline)")
  })
  it("scales bars from 40% of the marks up to the goal line (sjf.js hOf)", () => {
    expect(stepHeight(56, 85)).toBe(36)
    expect(stepHeight(85, 85)).toBe(100)
    expect(stepHeight(30, 85)).toBe(0)
    expect(stepHeight(120, 85)).toBe(100)
    expect(stepHeight(70, 30)).toBe(100)
  })
  it("summarises the path in words", () => {
    expect(stepsSummary(PAPERS.slice(0, 2), "A*", "7 to go")).toBe("Marks so far: C, 45/80 in Oct; B, 48 out of 80 in Jan. Goal A*, 7 to go.")
    expect(stepsSummary([], undefined)).toBe("No papers yet.")
  })
})

describe("StepsPath", () => {
  it("one bar per paper, the latest solid, then the goal block and its caption", () => {
    const out = html({ papers: PAPERS, goal: "A*", goalPct: 85, goalCaption: "68/80 · A* line", goalNote: "7 to go" })
    expect(out.match(/class="rd-step"/g)).toHaveLength(4)
    expect(out.match(/data-current=""/g)).toHaveLength(2) // the bar and its label
    expect(out).toMatch(/data-goal=""[^>]*><b>A\*<\/b><span>7 to go<\/span>/)
    expect(out).toContain('<span data-goal="">68/80 · A* line</span>')
    expect(out).toContain("<b>48/80</b>Jan") // marks become the Mono line when there is no caption
    expect(out).toMatch(/--n:4/)
  })
  it("the goal caption defaults to the grade's line", () => {
    expect(html({ papers: PAPERS, goal: "A" })).toContain('<span data-goal="">A line</span>')
  })
  it("bars are buttons named by grade, marks and date when selectable", () => {
    const out = html({ papers: PAPERS, onSelect: () => {} })
    expect(out).toMatch(/<button type="button" class="rd-step"[^>]*aria-label="B, 48 out of 80, Jan"/)
    expect(out).toMatch(/aria-label="C, 45\/80, Oct"/)
  })
  it("sparse: ghosts after the papers are labelled next", () => {
    const out = html({ papers: PAPERS.slice(2), goal: "A*", ghosts: 3 })
    expect(out.match(/data-ghost=""/g)).toHaveLength(6)
    expect(out.match(/>next</g)).toHaveLength(3)
  })
  it("first run: no papers draws four fixed-height ghosts and the goal", () => {
    const out = html({ papers: [], goal: "A*", ghosts: 4 })
    expect(out).toMatch(/--h:30%/)
    expect(out).toMatch(/--h:70%/)
    expect(out).not.toContain(">next<")
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/unit/redesign/steps.test.ts`
Expected: FAIL, `StepsPath` not exported.

- [ ] **Step 3: Write the implementation**

`web/src/components/redesign/grades.ts`:

```ts
/** 'A*' | 'A' | … | 'G' | 'U' */
export type Grade = string

const GRADE_VARS: Record<string, string> = {
  "A*": "--grade-a-star",
  A: "--grade-a",
  B: "--grade-b",
  C: "--grade-c",
  D: "--grade-d",
  E: "--grade-e",
  F: "--grade-f",
  G: "--grade-g",
  U: "--grade-u",
}

export function gradeColorVar(grade: Grade): string {
  return `var(${GRADE_VARS[grade.trim().toUpperCase()] ?? "--md-outline"})`
}

/** Ghost heights for an empty path (sjf.js ghostPath). */
export const EMPTY_GHOST_HEIGHTS = [30, 45, 52, 70] as const

/** Bars run from 40% of the marks up to the goal line, so each grade reads as a real step (sjf.js hOf). */
export function stepHeight(pct: number, goalPct = 100): number {
  if (!Number.isFinite(pct)) return 0
  const floor = 40
  if (goalPct <= floor) return 100
  return Math.max(0, Math.min(100, Math.round(((pct - floor) / (goalPct - floor)) * 100)))
}

export interface PaperScore {
  pct: number
  caption?: string
  marks?: { got: number; max: number }
}

/** The Mono line under a bar: the caption, else got/max, else nothing. */
export function paperCaption(p: PaperScore): string | undefined {
  return p.caption ?? (p.marks ? `${p.marks.got}/${p.marks.max}` : undefined)
}

/** How a bar's score is spoken: marks in words when known, else the caption, else the percentage. */
export function paperSpoken(p: PaperScore): string {
  if (p.marks) return `${p.marks.got} out of ${p.marks.max}`
  return p.caption ?? `${p.pct}%`
}

export function stepsSummary(
  papers: readonly (PaperScore & { label: string; grade: Grade })[],
  goal?: Grade,
  goalNote?: string,
): string {
  const parts = papers.map((p) => `${p.grade}, ${paperSpoken(p)} in ${p.label}`)
  let text = parts.length ? `Marks so far: ${parts.join("; ")}.` : "No papers yet."
  if (goal) text += ` Goal ${goal}${goalNote ? `, ${goalNote}` : ""}.`
  return text
}
```

`web/src/components/redesign/StepsPath.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { CSSProperties } from "react"
import { EMPTY_GHOST_HEIGHTS, type Grade, gradeColorVar, paperCaption, paperSpoken, stepHeight, stepsSummary } from "./grades"
import "./redesign.css"

export interface StepsPaper {
  id: string
  label: string
  grade: Grade
  pct: number
  /** Shown above the label in Mono, e.g. "61/80". */
  caption?: string
  /** Marks; the Mono line is "got/max" when there is no caption, and the bar is named "48 out of 80". */
  marks?: { got: number; max: number }
}

export interface StepsPathProps {
  papers: StepsPaper[]
  goal?: Grade
  onSelect?: (id: string) => void
  /** The goal line as a percentage of the paper; bars scale from 40% up to it. Default 100. */
  goalPct?: number
  /** The whole line under the goal block, e.g. "68/80 · A* line · 7 to go". Default "A* line". */
  goalCaption?: string
  /** Inside the goal block, e.g. "7 to go". */
  goalNote?: string
  /** Outline bars after the papers (sparse) or instead of them (first run). */
  ghosts?: number
  "aria-label"?: string
}

const css = (vars: Record<string, string | number>) => vars as CSSProperties

/** The Steps grade path: one solid bar per paper, a solid goal block, letters on one baseline. */
export function StepsPath({ papers, goal, onSelect, goalPct = 100, goalCaption, goalNote, ghosts = 0, "aria-label": ariaLabel }: StepsPathProps) {
  const ghostCount = Math.max(0, ghosts)
  const columns = Math.max(1, papers.length + ghostCount + (goal ? 1 : 0))
  const last = papers.length - 1
  return (
    <div className="rd-steps" role="group" aria-label={ariaLabel ?? stepsSummary(papers, goal, goalNote)}>
      <div className="rd-steps-track" style={css({ "--n": columns })}>
        {papers.map((p, i) => {
          const style = css({ "--h": `${stepHeight(p.pct, goalPct)}%`, "--c": gradeColorVar(p.grade), "--i": i })
          const current = i === last || undefined
          return onSelect ? (
            <button key={p.id} type="button" className="rd-step" data-current={current} style={style} aria-label={`${p.grade}, ${paperSpoken(p)}, ${p.label}`} onClick={() => onSelect(p.id)}>
              <b>{p.grade}</b>
            </button>
          ) : (
            <span key={p.id} className="rd-step" data-current={current} style={style} aria-hidden="true">
              <b>{p.grade}</b>
            </span>
          )
        })}
        {Array.from({ length: ghostCount }, (_, i) => (
          <span
            key={`ghost-${i}`}
            className="rd-step"
            data-ghost=""
            aria-hidden="true"
            style={papers.length === 0 ? css({ "--h": `${EMPTY_GHOST_HEIGHTS[i % EMPTY_GHOST_HEIGHTS.length]}%` }) : undefined}
          />
        ))}
        {goal ? (
          <span className="rd-step" data-goal="" aria-hidden="true" style={css({ "--h": "100%", "--i": papers.length })}>
            <b>{goal}</b>
            {goalNote ? <span>{goalNote}</span> : null}
          </span>
        ) : null}
      </div>
      <div className="rd-steps-labels" style={css({ "--n": columns })} aria-hidden="true">
        {papers.map((p, i) => {
          const caption = paperCaption(p)
          return (
            <span key={p.id} data-current={i === last || undefined}>
              {caption ? <b>{caption}</b> : null}
              {p.label}
            </span>
          )
        })}
        {Array.from({ length: ghostCount }, (_, i) => (
          <span key={`ghost-${i}`} data-ghost="">
            {papers.length ? "next" : ""}
          </span>
        ))}
        {goal ? <span data-goal="">{goalCaption ?? `${goal} line`}</span> : null}
      </div>
    </div>
  )
}
```

Append to `redesign.css`:

```css
/* ── StepsPath (t.css .gp2 / .gp2t / .gp2l / .stp, final overrides) ────── */
.rd-steps { display: grid; gap: 8px; }
.rd-steps-track {
  display: grid;
  grid-template-columns: repeat(var(--n, 5), minmax(0, 1fr));
  align-items: end;
  gap: 8px;
  height: 108px;
  margin-top: 4px;
  border-bottom: 2px solid var(--md-outline);
}
.rd-step {
  --c: var(--md-outline);
  justify-self: center;
  width: min(100%, 64px);
  height: var(--h, 34%);
  min-height: 44px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 0 0;
  border: 0;
  border-radius: 14px 14px 4px 4px;
  background: color-mix(in oklch, var(--c) 22%, var(--md-surface-container-lowest));
  transform-origin: bottom;
  font: inherit;
  transition: translate 0.2s var(--ease-out), filter 0.2s;
}
.rd-step b { font: 800 22px/1 var(--font-display); color: color-mix(in oklch, var(--c), black 25%); }
.rd-step[data-current] { background: var(--c); }
.rd-step[data-current] b { color: white; font-size: 28px; }
.rd-step[data-goal] {
  background: color-mix(in oklch, var(--grade-a-star) 12%, var(--md-surface-container-lowest));
  box-shadow: inset 0 0 0 2px color-mix(in oklch, var(--grade-a-star) 40%, var(--md-surface-container-lowest));
}
.rd-step[data-goal] b { color: var(--grade-a-star); }
.rd-step[data-goal] span { font: 600 12px var(--font-sans); white-space: nowrap; color: var(--grade-a-star); }
.rd-step[data-ghost] { background: transparent; box-shadow: inset 0 0 0 2px var(--md-outline-variant); }
button.rd-step { cursor: pointer; }
.rd-step:focus-visible { outline: 2.5px solid var(--md-primary); outline-offset: 2px; }
.rd-steps-labels {
  display: grid;
  grid-template-columns: repeat(var(--n, 5), minmax(0, 1fr));
  text-align: center;
  font: 500 12px var(--font-sans);
  color: var(--md-on-surface-variant);
}
.rd-steps-labels > span { display: grid; gap: 1px; }
.rd-steps-labels b { font: 600 12.5px var(--font-mono); color: var(--md-on-surface); }
.rd-steps-labels [data-current] b { font-weight: 800; }
.rd-steps-labels [data-goal], .rd-steps-labels [data-goal] b { color: var(--grade-a-star); font-weight: 600; }
.rd-steps-labels [data-ghost] { align-self: end; color: var(--md-on-surface-variant); }
@media (prefers-reduced-motion: no-preference) {
  .rd-step:not([data-ghost]) { animation: rd-grow 0.7s var(--ease-out) calc(var(--i, 0) * 60ms) both; }
  button.rd-step:hover { translate: 0 -3px; filter: saturate(1.15); }
}
@keyframes rd-grow { from { transform: scaleY(0.4); } }
```

Append to `index.ts`:

```ts
export { StepsPath, type StepsPaper, type StepsPathProps } from "./StepsPath"
export { type Grade, gradeColorVar } from "./grades"
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run tests/unit/redesign/steps.test.ts tests/unit/redesign/redesignCss.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(web): redesign StepsPath grade path" -- web/src/components/redesign/grades.ts web/src/components/redesign/StepsPath.tsx web/src/components/redesign/redesign.css web/src/components/redesign/index.ts web/tests/unit/redesign/steps.test.ts
```

---

## Task 4: Rows (H2Row, HairRows, HairRow, RankRow, SubjectDot)

**Agent:** designer.

**Files:**
- Create: `web/src/components/redesign/RowAction.tsx`, `H2Row.tsx`, `HairRows.tsx`, `RankRow.tsx`, `subjects.ts`, `SubjectDot.tsx`
- Modify: `redesign.css` (append), `index.ts` (append)
- Test: `web/tests/unit/redesign/rows.test.ts`

**Interfaces:**
- Consumes: `clamp01` (Task 2), `Chevron`, `SmallChevron`, `TrendGlyph` (Task 1).
- Produces: `H2Row({ title, link?: { label; to?; onClick? }, titleTo?, right? })` (`right` is a slot, e.g. the Paper 4 / Paper 2 toggle; it replaces `link` when both are given); `HairRows({ children, 'aria-label'? })` (a `<ul>`); `HairRow({ leading?, title, sub?, trailing?, to?, onClick?, selected? })` (an `<li>`); `RankRow({ rank, title, sub?: ReactNode, marksLost, trend, assigned?, bar?, selected?, onClick? })` (an `<li>`, place it inside `HairRows`); `type Trend`; `TREND_LABEL`; `SubjectDot({ subject: string; size?: number })` and `subjectDotColor(subject): string` (L9 and L10 use it; L11 puts it in `RankRow.sub`).

- [ ] **Step 1: Write the failing test**

`web/tests/unit/redesign/rows.test.ts`:

```ts
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { H2Row, HairRow, HairRows, RankRow, SubjectDot, subjectDotColor } from "@/components/redesign"

const html = (node: Parameters<typeof renderToStaticMarkup>[0]) => renderToStaticMarkup(createElement(MemoryRouter, null, node))

describe("H2Row", () => {
  it("a heading with a trailing link", () => {
    const out = html(createElement(H2Row, { title: "Topics costing marks", link: { label: "All topics", to: "/parent/topics" } }))
    expect(out).toMatch(/<h2 class="rd-h2">Topics costing marks<\/h2>/)
    expect(out).toMatch(/<a class="rd-lnk"[^>]*href="\/parent\/topics"[^>]*>All topics<\/a>/)
  })
  it("a button link when there is no route, and a linked title", () => {
    const out = html(createElement(H2Row, { title: "Papers", titleTo: "/papers", link: { label: "More", onClick: () => {} } }))
    expect(out).toMatch(/<h2 class="rd-h2"><a class="rd-h2link"[^>]*href="\/papers"/)
    expect(out).toMatch(/<button type="button" class="rd-lnk">More<\/button>/)
  })
  it("a right slot replaces the link", () => {
    const out = html(createElement(H2Row, { title: "Your path to A*", link: { label: "x", to: "/x" }, right: createElement("div", { role: "tablist" }) }))
    expect(out).toContain('<div class="rd-h2row-right"><div role="tablist"></div></div>')
    expect(out).not.toContain("rd-lnk")
  })
})

describe("SubjectDot", () => {
  it("maps subjects by name or code to existing tokens, stable for unknowns", () => {
    expect(subjectDotColor("Mathematics")).toBe("var(--grade-a)")
    expect(subjectDotColor("0580")).toBe("var(--grade-a)")
    expect(subjectDotColor("Physics")).toBe("var(--md-primary)")
    expect(subjectDotColor("Additional Maths")).toBe("var(--grade-d)")
    expect(subjectDotColor("Latin")).toBe(subjectDotColor("latin "))
    expect(subjectDotColor("Latin")).toMatch(/^var\(--/)
  })
  it("renders a decorative dot at 8px by default", () => {
    const out = renderToStaticMarkup(createElement(SubjectDot, { subject: "Physics" }))
    expect(out).toBe('<i class="rd-dot" aria-hidden="true" style="width:8px;height:8px;background:var(--md-primary)"></i>')
  })
  it("fits inside a ranked row's sub line", () => {
    const out = html(createElement(RankRow, { rank: 1, title: "Waves", sub: createElement("span", null, createElement(SubjectDot, { subject: "Physics" }), "Physics"), marksLost: 6, trend: "same" }))
    expect(out).toContain('<i class="rd-dot"')
  })
})

describe("HairRows / HairRow", () => {
  it("a labelled list of hairline rows; links get a chevron, static rows do not", () => {
    const out = html(
      createElement(HairRows, { "aria-label": "Papers" }, [
        createElement(HairRow, { key: "a", title: "Mathematics · Paper 4", sub: "61/80 · 2 days ago", to: "/r/1", trailing: "+9" }),
        createElement(HairRow, { key: "b", title: "Static" }),
      ]),
    )
    expect(out).toMatch(/^<ul class="rd-hairrows" aria-label="Papers">/)
    expect(out.match(/<li class="rd-hairrow-item">/g)).toHaveLength(2)
    expect(out).toMatch(/<a class="rd-hairrow"[^>]*href="\/r\/1"/)
    expect(out.match(/rd-chev/g)).toHaveLength(1)
    expect(out).toContain('<div class="rd-hairrow">')
  })
  it("a selected button row says so", () => {
    const out = html(createElement(HairRow, { title: "Vectors", onClick: () => {}, selected: true }))
    expect(out).toMatch(/<button type="button" class="rd-hairrow rd-selected" aria-current="true">/)
  })
})

describe("RankRow", () => {
  it("rank, title, Assigned tag, marks lost, trend", () => {
    const out = html(createElement(RankRow, { rank: 1, title: "Vectors", sub: "Practised twice", marksLost: 9, trend: "better", assigned: true }))
    expect(out).toMatch(/<span class="rd-rank-n">1<\/span>/)
    expect(out).toContain('<em class="rd-tag">Assigned</em>')
    expect(out).toContain("<b>−9</b><small>marks</small>")
    expect(out).toMatch(/class="rd-trend rd-trend-better">.*Better<\/span>/)
  })
  it("a marks-lost bar sets its width and the bar layout", () => {
    const out = html(createElement(RankRow, { rank: 2, title: "Waves", marksLost: 4, trend: "worse", bar: 0.44 }))
    expect(out).toContain("rd-rank rd-rank-bar")
    expect(out).toMatch(/style="--w:44%"/)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/unit/redesign/rows.test.ts`
Expected: FAIL, `H2Row` not exported.

- [ ] **Step 3: Write the implementation**

`web/src/components/redesign/RowAction.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { Link } from "react-router-dom"

/** A row's hit area: a Link for a route, a button for an action, otherwise a plain div. */
export function RowAction({
  to,
  onClick,
  selected,
  className,
  children,
}: {
  to?: string
  onClick?: () => void
  selected?: boolean
  className: string
  children: ReactNode
}) {
  const current = selected ? ("true" as const) : undefined
  if (to) {
    return (
      <Link to={to} className={className} aria-current={current}>
        {children}
      </Link>
    )
  }
  if (onClick) {
    return (
      <button type="button" className={className} aria-current={current} onClick={onClick}>
        {children}
      </button>
    )
  }
  return <div className={className}>{children}</div>
}
```

`web/src/components/redesign/H2Row.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { SmallChevron } from "./icons"
import "./redesign.css"

export interface H2RowProps {
  title: string
  link?: { label: string; to?: string; onClick?: () => void }
  /** The whole title links somewhere, with a small chevron (mock .hlink.h). */
  titleTo?: string
  /** A trailing slot, e.g. the Paper 4 / Paper 2 toggle (mock sjf.js `tog`). Wins over `link`. */
  right?: ReactNode
}

/** A section heading with an optional trailing link or slot (mock .h2row). No eyebrow, ever. */
export function H2Row({ title, link, titleTo, right }: H2RowProps) {
  return (
    <div className="rd-h2row">
      <h2 className="rd-h2">
        {titleTo ? (
          <Link to={titleTo} className="rd-h2link">
            {title}
            <SmallChevron />
          </Link>
        ) : (
          title
        )}
      </h2>
      {right !== undefined ? (
        <div className="rd-h2row-right">{right}</div>
      ) : link ? (
        link.to ? (
          <Link to={link.to} className="rd-lnk">
            {link.label}
          </Link>
        ) : (
          <button type="button" className="rd-lnk" onClick={link.onClick}>
            {link.label}
          </button>
        )
      ) : null}
    </div>
  )
}
```

`web/src/components/redesign/HairRows.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { cn } from "@/lib/utils"
import { Chevron } from "./icons"
import { RowAction } from "./RowAction"
import "./redesign.css"

export function HairRows({ children, "aria-label": ariaLabel }: { children: ReactNode; "aria-label"?: string }) {
  return (
    <ul className="rd-hairrows" aria-label={ariaLabel}>
      {children}
    </ul>
  )
}

export interface HairRowProps {
  leading?: ReactNode
  title: ReactNode
  sub?: ReactNode
  trailing?: ReactNode
  to?: string
  onClick?: () => void
  selected?: boolean
}

/** One hairline row (mock .wrow / .rp / .arow): leading, title and sub, trailing, chevron when it goes somewhere. */
export function HairRow({ leading, title, sub, trailing, to, onClick, selected }: HairRowProps) {
  return (
    <li className="rd-hairrow-item">
      <RowAction to={to} onClick={onClick} selected={selected} className={cn("rd-hairrow", selected && "rd-selected")}>
        {leading !== undefined ? <span className="rd-hr-lead">{leading}</span> : null}
        <span className="rd-at">
          <b>{title}</b>
          {sub !== undefined ? <span>{sub}</span> : null}
        </span>
        {trailing !== undefined ? <span className="rd-hr-trail">{trailing}</span> : null}
        {to || onClick ? <Chevron /> : null}
      </RowAction>
    </li>
  )
}
```

`web/src/components/redesign/RankRow.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { CSSProperties, ReactNode } from "react"
import { cn } from "@/lib/utils"
import { TrendGlyph } from "./icons"
import { clamp01 } from "./rings"
import { RowAction } from "./RowAction"
import "./redesign.css"

export type Trend = "better" | "worse" | "same"

export const TREND_LABEL: Record<Trend, string> = { better: "Better", worse: "Worse", same: "Same" }

export interface RankRowProps {
  rank: number
  title: string
  /** What the child is doing; a node so a SubjectDot can lead it. */
  sub?: ReactNode
  marksLost: number
  trend: Trend
  assigned?: boolean
  /** 0..1 of the list's largest loss: a thin marks-lost bar under the number. */
  bar?: number
  selected?: boolean
  onClick?: () => void
}

/** The parent ranked row (mock pa.js rank / rankBar / .rkr.on). A list item: put it in HairRows. */
export function RankRow({ rank, title, sub, marksLost, trend, assigned, bar, selected, onClick }: RankRowProps) {
  const barPct = bar === undefined ? undefined : Math.round(clamp01(bar) * 100)
  return (
    <li className="rd-hairrow-item">
      <RowAction onClick={onClick} selected={selected} className={cn("rd-rank", barPct !== undefined && "rd-rank-bar", selected && "rd-selected")}>
        <span className="rd-rank-n">{rank}</span>
        <span className="rd-at">
          <b>
            {title}
            {assigned ? <em className="rd-tag">Assigned</em> : null}
          </b>
          {sub !== undefined && sub !== null && sub !== "" ? <span>{sub}</span> : null}
        </span>
        <span className="rd-rank-m" style={barPct !== undefined ? ({ "--w": `${barPct}%` } as CSSProperties) : undefined}>
          <b>{`−${marksLost}`}</b>
          <small>marks</small>
        </span>
        <span className={`rd-trend rd-trend-${trend}`}>
          <TrendGlyph trend={trend} />
          {TREND_LABEL[trend]}
        </span>
      </RowAction>
    </li>
  )
}
```

`web/src/components/redesign/subjects.ts`:

```ts
/*
 * Subject dot colours (mock pa.js / sp.js / fc.js `SUBC`: Maths green, Physics blue,
 * Add Maths violet), mapped onto existing tokens only. The dot is decorative; the
 * subject's name always sits beside it (DESIGN.md: subjects are told apart by label).
 */
const NAMED: [RegExp, string][] = [
  [/^(additional\s+math(s|ematics)?|add\s+maths|0606)$/, "--grade-d"],
  [/^(math(s|ematics)?|0580|0980)$/, "--grade-a"],
  [/^(physics|0625|0972)$/, "--md-primary"],
  [/^(chemistry|0620|0971)$/, "--md-tertiary"],
  [/^(biology|0610|0970)$/, "--grade-b"],
]

const PALETTE = ["--grade-a", "--md-primary", "--grade-d", "--md-tertiary", "--grade-b", "--grade-u", "--md-secondary"]

/** `var(--token)` for a subject name or syllabus code; unknown subjects hash to a stable palette slot. */
export function subjectDotColor(subject: string): string {
  const key = subject.trim().toLowerCase()
  const named = NAMED.find(([pattern]) => pattern.test(key))
  if (named) return `var(${named[1]})`
  let hash = 0
  for (const ch of key) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return `var(${PALETTE[hash % PALETTE.length]})`
}
```

Additional Maths is matched before Maths: the more specific pattern goes first.

`web/src/components/redesign/SubjectDot.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { subjectDotColor } from "./subjects"
import "./redesign.css"

/** A subject's colour dot (mock .sdot). Decorative: the subject name always follows it. */
export function SubjectDot({ subject, size = 8 }: { subject: string; size?: number }) {
  return <i className="rd-dot" aria-hidden="true" style={{ width: size, height: size, background: subjectDotColor(subject) }} />
}
```

Append to `redesign.css`:

```css
/* ── Rows (t.css .h2row/.sjh2/.lnk/.wrow/.rp/.at, pa.css .rkr) ─────────── */
.rd-dot { display: inline-block; flex: none; border-radius: 50%; margin-inline-end: 6px; vertical-align: 1px; }
.rd-h2row-right { flex: none; }
.rd-h2row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.rd-h2 { margin: 0; font: 800 18px/1.25 var(--font-sans); letter-spacing: -0.01em; color: var(--md-on-surface); }
.rd-h2link { display: inline-flex; align-items: center; gap: 8px; color: inherit; text-decoration: none; min-height: 44px; }
.rd-lnk {
  display: inline-flex; align-items: center; gap: 6px; min-height: 44px; padding: 0;
  border: 0; background: none; cursor: pointer; text-decoration: none;
  font: 700 14px var(--font-sans); color: var(--md-primary);
}
.rd-lnk:active, .rd-h2link:active { transform: scale(0.97); }
.rd-lnk:focus-visible, .rd-h2link:focus-visible { outline: 2.5px solid var(--md-primary); outline-offset: 2px; border-radius: 10px; }
.rd-hairrows { list-style: none; margin: 0; padding: 0; display: grid; }
.rd-hairrow-item + .rd-hairrow-item { border-top: 1px solid var(--md-outline-variant); }
.rd-hairrow, .rd-rank {
  width: 100%; margin: 0; border: 0; background: none; text-align: start; text-decoration: none;
  font: inherit; color: var(--md-on-surface);
  transition: background-color var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}
.rd-hairrow { display: flex; align-items: center; gap: 12px; min-height: 56px; padding: 11px 2px; }
a.rd-hairrow, button.rd-hairrow, button.rd-rank { cursor: pointer; }
a.rd-hairrow:hover, button.rd-hairrow:hover, button.rd-rank:hover {
  background: linear-gradient(90deg, transparent, var(--md-surface-container-low) 12%, var(--md-surface-container-low) 88%, transparent);
}
a.rd-hairrow:active, button.rd-hairrow:active, button.rd-rank:active { transform: scale(0.985); }
.rd-hairrow:focus-visible, .rd-rank:focus-visible { outline: 2.5px solid var(--md-primary); outline-offset: 2px; border-radius: 14px; }
.rd-selected, .rd-selected:hover { background: var(--md-primary-container); border-radius: 14px; padding-inline: 8px; }
.rd-hr-lead { flex: none; width: 36px; display: grid; place-items: center; }
.rd-hr-trail { flex: none; }
.rd-at { flex: 1; min-width: 0; display: grid; gap: 1px; }
.rd-at > b { font: 700 15px/1.3 var(--font-sans); overflow-wrap: anywhere; }
.rd-at > span { font: 400 13px/1.35 var(--font-sans); color: var(--md-on-surface-variant); }
.rd-chev { flex: none; color: var(--md-on-surface-variant); }
.rd-rank { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto 64px; align-items: center; gap: 10px; min-height: 60px; padding: 10px 0; }
.rd-rank-bar { grid-template-columns: 24px minmax(0, 1fr) 96px 64px; }
.rd-rank-n { font: 700 14px var(--font-mono); color: var(--md-on-surface-variant); text-align: center; }
.rd-rank-m { position: relative; display: grid; justify-items: end; }
.rd-rank-m b { font: 800 17px/1 var(--font-mono); color: var(--md-on-error-container); }
.rd-rank-m small { margin-top: 2px; font: 600 12px var(--font-sans); color: var(--md-on-surface-variant); }
.rd-rank-bar .rd-rank-m { min-width: 56px; }
.rd-rank-bar .rd-rank-m::before {
  content: ""; position: absolute; inset-inline-end: 0; bottom: -8px; height: 4px; width: var(--w, 0%);
  border-radius: 2px; background: color-mix(in oklch, var(--md-on-error-container), var(--md-surface-container-lowest) 55%);
}
.rd-trend { display: inline-flex; align-items: center; gap: 4px; justify-self: end; font: 600 12.5px var(--font-sans); }
.rd-trend-better { color: var(--md-success-text); }
.rd-trend-worse { color: var(--md-on-error-container); }
.rd-trend-same { color: var(--md-on-surface-variant); }
.rd-tag {
  margin-inline-start: 6px; padding: 3px 6px; border-radius: 6px; vertical-align: 2px; white-space: nowrap;
  font: 700 12px/1 var(--font-sans); font-style: normal; color: var(--md-primary); background: var(--md-primary-container);
}
```

Append to `index.ts`:

```ts
export { H2Row, type H2RowProps } from "./H2Row"
export { HairRows, HairRow, type HairRowProps } from "./HairRows"
export { RankRow, TREND_LABEL, type RankRowProps, type Trend } from "./RankRow"
export { SubjectDot } from "./SubjectDot"
export { subjectDotColor } from "./subjects"
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run tests/unit/redesign/rows.test.ts tests/unit/redesign/redesignCss.test.ts tests/unit/rtlSafety.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(web): redesign hairline rows, h2 row, ranked row and subject dot" -- web/src/components/redesign/subjects.ts web/src/components/redesign/SubjectDot.tsx web/src/components/redesign/RowAction.tsx web/src/components/redesign/H2Row.tsx web/src/components/redesign/HairRows.tsx web/src/components/redesign/RankRow.tsx web/src/components/redesign/redesign.css web/src/components/redesign/index.ts web/tests/unit/redesign/rows.test.ts
```

---

## Task 5: TopicChip and TopicChips

**Agent:** designer.

**Files:**
- Create: `web/src/components/redesign/TopicChip.tsx`, `TopicChips.tsx`
- Modify: `redesign.css` (append), `index.ts` (append)
- Test: `web/tests/unit/redesign/topics.test.ts`

**Interfaces:**
- Consumes: `TopicState`, `TOPIC_STATE_LABEL`, `topicState` (`topics.ts`, Task 1); `TopicGlyph`, `SmallChevron`.
- Produces: `TopicChip({ topic, state, onClick?, pct? })`, `TopicChips({ topics: { topic; state; pct? }[]; foldSecure?; onSelect? })`.

- [ ] **Step 1: Write the failing test**

`web/tests/unit/redesign/topics.test.ts`:

```ts
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { MASTERY, TopicChip, TopicChips, topicState } from "@/components/redesign"

const TOPICS = [
  { topic: "Vectors", state: "work" as const, pct: 41 },
  { topic: "Algebra", state: "getting" as const, pct: 62 },
  { topic: "Number", state: "secure" as const, pct: 82 },
  { topic: "Probability", state: "secure" as const, pct: 88 },
]

describe("topicState", () => {
  it("uses the mock thresholds", () => {
    expect([topicState(59), topicState(60), topicState(74), topicState(75)]).toEqual(["work", "getting", "getting", "secure"])
  })
  it("reads its thresholds from MASTERY, the one shared source", () => {
    expect(MASTERY).toEqual({ getting: 0.6, secure: 0.75 })
    expect(topicState(MASTERY.secure * 100)).toBe("secure")
    expect(topicState(MASTERY.getting * 100 - 0.01)).toBe("work")
  })
})

describe("TopicChip", () => {
  it("names its state for screen readers and shows the percentage in Mono", () => {
    const out = renderToStaticMarkup(createElement(TopicChip, { topic: "Vectors", state: "work", pct: 41 }))
    expect(out).toMatch(/^<span class="rd-chip" data-state="work">/)
    expect(out).toContain('<span class="sr-only">, Work on</span>')
    expect(out).toContain("<b>41%</b>")
  })
  it("is a button when it opens something", () => {
    const out = renderToStaticMarkup(createElement(TopicChip, { topic: "Vectors", state: "work", onClick: () => {} }))
    expect(out).toMatch(/^<button type="button" class="rd-chip" data-state="work">/)
  })
})

describe("TopicChips", () => {
  it("folds secure topics into one chip that names the count", () => {
    const out = renderToStaticMarkup(createElement(TopicChips, { topics: TOPICS, foldSecure: true }))
    expect(out).not.toContain(">Number<")
    expect(out).toMatch(/class="rd-chip rd-chip-more"[^>]*aria-expanded="false"/)
    expect(out).toContain(">2 secure<")
  })
  it("shows everything unfolded, with the legend", () => {
    const out = renderToStaticMarkup(createElement(TopicChips, { topics: TOPICS }))
    expect(out).toContain(">Number<")
    expect(out).not.toContain("rd-chip-more")
    expect(out).toMatch(/<p class="rd-chip-legend" aria-hidden="true">.*Work on.*Getting there.*Secure/)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/unit/redesign/topics.test.ts`
Expected: FAIL, `TopicChip` not exported.

- [ ] **Step 3: Write the implementation**

`web/src/components/redesign/TopicChip.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { TopicGlyph } from "./icons"
import { TOPIC_STATE_LABEL, type TopicState } from "./topics"
import "./redesign.css"

export interface TopicChipProps {
  topic: string
  state: TopicState
  onClick?: () => void
  pct?: number
}

/** A topic chip with its state icon (mock .tm): Work on, Getting there, Secure. */
export function TopicChip({ topic, state, onClick, pct }: TopicChipProps) {
  const inner = (
    <>
      <TopicGlyph state={state} />
      <span>{topic}</span>
      <span className="sr-only">{`, ${TOPIC_STATE_LABEL[state]}`}</span>
      {pct !== undefined ? <b>{`${pct}%`}</b> : null}
    </>
  )
  return onClick ? (
    <button type="button" className="rd-chip" data-state={state} onClick={onClick}>
      {inner}
    </button>
  ) : (
    <span className="rd-chip" data-state={state}>
      {inner}
    </span>
  )
}
```

`web/src/components/redesign/TopicChips.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useState } from "react"
import { SmallChevron, TopicGlyph } from "./icons"
import { TopicChip } from "./TopicChip"
import { TOPIC_STATE_LABEL, type TopicState } from "./topics"
import "./redesign.css"

export interface TopicChipsProps {
  /** Order is the caller's (weakest first on student screens). */
  topics: { topic: string; state: TopicState; pct?: number }[]
  /** Phone and tablet: secure topics fold into one "N secure" chip that expands in place. */
  foldSecure?: boolean
  onSelect?: (topic: string) => void
}

const ORDER: TopicState[] = ["work", "getting", "secure"]

export function TopicChips({ topics, foldSecure = false, onSelect }: TopicChipsProps) {
  const [open, setOpen] = useState(false)
  const secureCount = topics.filter((t) => t.state === "secure").length
  const folded = foldSecure && !open && secureCount > 0
  const shown = folded ? topics.filter((t) => t.state !== "secure") : topics
  return (
    <div className="rd-chips-wrap">
      <ul className="rd-chips">
        {shown.map((t) => (
          <li key={t.topic}>
            <TopicChip topic={t.topic} state={t.state} pct={t.pct} onClick={onSelect ? () => onSelect(t.topic) : undefined} />
          </li>
        ))}
        {folded ? (
          <li>
            <button type="button" className="rd-chip rd-chip-more" data-state="secure" aria-expanded="false" onClick={() => setOpen(true)}>
              <TopicGlyph state="secure" />
              <span>{`${secureCount} secure`}</span>
              <SmallChevron />
            </button>
          </li>
        ) : null}
      </ul>
      <p className="rd-chip-legend" aria-hidden="true">
        {ORDER.map((s) => (
          <span key={s}>
            <TopicGlyph state={s} />
            {TOPIC_STATE_LABEL[s]}
          </span>
        ))}
      </p>
    </div>
  )
}
```

Append to `redesign.css`:

```css
/* ── Topic chips (t.css .tmap/.tm/.tleg) ─────────────────────────────── */
.rd-chips { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
.rd-chip {
  position: relative; display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 12px;
  border: 0; border-radius: 12px; font: 600 13.5px var(--font-sans); transition: translate 0.2s var(--ease-out);
}
.rd-chip b { font: 700 12px var(--font-mono); }
.rd-chip svg { flex: none; }
.rd-chip[data-state="secure"] { background: var(--md-primary-container); color: var(--md-primary); }
.rd-chip[data-state="getting"] { background: var(--md-surface-container-low); color: var(--md-on-surface); box-shadow: inset 0 0 0 1px var(--md-outline-variant); }
.rd-chip[data-state="work"] { background: var(--md-error-container); color: var(--md-on-error-container); }
.rd-chip.rd-chip-more { background: transparent; box-shadow: inset 0 0 0 1.5px var(--md-outline); }
button.rd-chip { cursor: pointer; }
button.rd-chip:active { transform: scale(0.97); }
.rd-chip:focus-visible { outline: 2.5px solid var(--md-primary); outline-offset: 2px; }
.rd-chip-legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 8px 0 0; font: 500 12px var(--font-sans); color: var(--md-on-surface-variant); }
.rd-chip-legend span { display: inline-flex; align-items: center; gap: 6px; }
@media (prefers-reduced-motion: no-preference) {
  button.rd-chip:hover { translate: 0 -2px; }
}
```

Append to `index.ts`:

```ts
export { TopicChip, type TopicChipProps } from "./TopicChip"
export { TopicChips, type TopicChipsProps } from "./TopicChips"
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run tests/unit/redesign/topics.test.ts tests/unit/redesign/redesignCss.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(web): redesign topic chips with secure fold" -- web/src/components/redesign/TopicChip.tsx web/src/components/redesign/TopicChips.tsx web/src/components/redesign/redesign.css web/src/components/redesign/index.ts web/tests/unit/redesign/topics.test.ts
```

---

## Task 6: Tile

**Agent:** designer.

**Files:**
- Create: `web/src/components/redesign/Tile.tsx`
- Modify: `redesign.css` (append), `index.ts` (append)
- Test: `web/tests/unit/redesign/tile.test.ts`

**Interfaces:**
- Produces: `type TileTone = 'tide'|'sea'|'gold'|'coral'|'violet'|'mint'`; `Tile({ icon, title, status?, tone, big?, to?, onClick?, disabled? })`. `icon` is a Phosphor `Icon` (it receives `size` and `weight`).

- [ ] **Step 1: Write the failing test**

`web/tests/unit/redesign/tile.test.ts`:

```ts
import { Cards } from "@phosphor-icons/react"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { Tile } from "@/components/redesign"

const html = (p: Parameters<typeof Tile>[0]) => renderToStaticMarkup(createElement(MemoryRouter, null, createElement(Tile, p)))

describe("Tile", () => {
  it("a tinted link tile with a big faint icon in its corner", () => {
    const out = html({ icon: Cards, title: "Flashcards", status: "26 due today", tone: "violet", to: "/student/flashcards" })
    expect(out).toMatch(/<a class="rd-tile" data-tone="violet"[^>]*href="\/student\/flashcards"/)
    expect(out).toContain('<b class="rd-tile-title">Flashcards</b>')
    expect(out).toMatch(/<span class="rd-tile-art" aria-hidden="true"><svg[^>]*width="64"/)
  })
  it("a big row tile with a leading icon and a chevron", () => {
    const out = html({ icon: Cards, title: "Homework", status: "Due Friday", tone: "tide", big: true, onClick: () => {} })
    expect(out).toMatch(/<button type="button" class="rd-tile rd-tile-big" data-tone="tide">/)
    expect(out).toContain("rd-tile-ic")
    expect(out).toContain("rd-chev")
  })
  it("disabled is not a control", () => {
    const out = html({ icon: Cards, title: "Placement test", tone: "gold", to: "/x", disabled: true })
    expect(out).toMatch(/^<div class="rd-tile" data-tone="gold" aria-disabled="true">/)
    expect(out).not.toContain("href=")
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/unit/redesign/tile.test.ts`
Expected: FAIL, `Tile` not exported.

- [ ] **Step 3: Write the implementation**

`web/src/components/redesign/Tile.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ElementType, ReactNode } from "react"
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import { Chevron } from "./icons"
import "./redesign.css"

export type TileTone = "tide" | "sea" | "gold" | "coral" | "violet" | "mint"

export interface TileProps {
  /** A Phosphor icon. */
  icon: ElementType
  title: string
  /** e.g. "Build your own · 10 min", or a node with a Mono count in <b>. */
  status?: ReactNode
  tone: TileTone
  /** The full-width row variant (the homework row). */
  big?: boolean
  to?: string
  onClick?: () => void
  disabled?: boolean
}

/** A tinted tile with a big faint icon (Practice tab C, mock ph.js gridC). */
export function Tile({ icon: Icon, title, status, tone, big = false, to, onClick, disabled = false }: TileProps) {
  const className = cn("rd-tile", big && "rd-tile-big")
  const body = big ? (
    <>
      <span className="rd-tile-ic" aria-hidden="true">
        <Icon size={22} />
      </span>
      <span className="rd-at">
        <b>{title}</b>
        {status !== undefined ? <span>{status}</span> : null}
      </span>
      <Chevron />
    </>
  ) : (
    <>
      <b className="rd-tile-title">{title}</b>
      {status !== undefined ? <span className="rd-tile-status">{status}</span> : null}
      <span className="rd-tile-art" aria-hidden="true">
        <Icon size={64} weight="light" />
      </span>
    </>
  )
  if (disabled) {
    return (
      <div className={className} data-tone={tone} aria-disabled="true">
        {body}
      </div>
    )
  }
  if (to) {
    return (
      <Link to={to} className={className} data-tone={tone}>
        {body}
      </Link>
    )
  }
  if (onClick) {
    return (
      <button type="button" className={className} data-tone={tone} onClick={onClick}>
        {body}
      </button>
    )
  }
  return (
    <div className={className} data-tone={tone}>
      {body}
    </div>
  )
}
```

Append to `redesign.css`. The violet tint has no Abyss token (see Needs user decision 6), so it is the one place this file holds a literal colour, scoped to the tile:

```css
/* ── Tile (ph.css .pgrid.tint .ptile, .ptile.big) ─────────────────────── */
.rd-tile {
  position: relative; overflow: hidden; display: grid; align-content: start; gap: 4px;
  min-height: 124px; padding: 14px; border: 0; border-radius: 20px; text-align: start; text-decoration: none;
  font: inherit; color: var(--md-on-surface); background: var(--rd-tile-bg);
  transition: transform var(--dur-fast) var(--ease-out), filter var(--dur-fast) var(--ease-out);
}
.rd-tile[data-tone="tide"] { --rd-tile-bg: var(--md-primary-container); --rd-tile-ink: var(--md-primary); }
.rd-tile[data-tone="sea"] { --rd-tile-bg: var(--md-secondary-container); --rd-tile-ink: var(--md-on-secondary-container); }
.rd-tile[data-tone="mint"] { --rd-tile-bg: var(--md-success-container); --rd-tile-ink: var(--md-success-text); }
.rd-tile[data-tone="coral"] { --rd-tile-bg: var(--md-error-container); --rd-tile-ink: var(--md-on-error-container); }
.rd-tile[data-tone="gold"] { --rd-tile-bg: color-mix(in oklch, var(--md-tertiary-container) 45%, var(--md-surface-container-lowest)); --rd-tile-ink: var(--md-on-tertiary-container); }
.rd-tile[data-tone="violet"] { --rd-tile-bg: oklch(0.95 0.03 300); --rd-tile-ink: oklch(0.42 0.1 300); }
:root[data-theme="dark"] .rd-tile[data-tone="gold"] { --rd-tile-bg: color-mix(in oklch, var(--md-tertiary) 22%, var(--md-surface-container-high)); --rd-tile-ink: var(--md-on-surface); }
:root[data-theme="dark"] .rd-tile[data-tone="violet"] { --rd-tile-bg: oklch(0.32 0.05 300); --rd-tile-ink: oklch(0.88 0.06 300); }
.rd-tile-title { position: relative; z-index: 1; font: 700 17px/1.2 var(--font-sans); }
.rd-tile-status { position: relative; z-index: 1; font: 500 13px/1.3 var(--font-sans); color: var(--md-on-surface-variant); }
.rd-tile-status b { font: 800 15px var(--font-mono); color: var(--md-primary); }
.rd-tile-art { position: absolute; inset-inline-end: -8px; bottom: -10px; width: 72px; height: 72px; display: grid; place-items: center; opacity: 0.35; color: var(--rd-tile-ink); }
a.rd-tile, button.rd-tile { cursor: pointer; }
a.rd-tile:hover, button.rd-tile:hover { filter: brightness(0.98); }
a.rd-tile:active, button.rd-tile:active { transform: scale(0.97); }
.rd-tile:focus-visible { outline: 2.5px solid var(--md-primary); outline-offset: 2px; }
.rd-tile[aria-disabled="true"] { opacity: 0.5; cursor: not-allowed; }
.rd-tile-big { grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; min-height: 0; padding: 12px 14px 12px 8px; }
.rd-tile-ic { width: 40px; height: 40px; border-radius: 13px; display: grid; place-items: center; background: var(--md-surface-container-lowest); color: var(--rd-tile-ink); }
.rd-tile-big .rd-at > b { font-size: 18px; }
.rd-tile-big .rd-at > span { font-size: 13.5px; font-weight: 500; }
```

Append to `index.ts`:

```ts
export { Tile, type TileProps, type TileTone } from "./Tile"
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run tests/unit/redesign/tile.test.ts tests/unit/redesign/redesignCss.test.ts tests/unit/darkConsumers.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(web): redesign tinted tile" -- web/src/components/redesign/Tile.tsx web/src/components/redesign/redesign.css web/src/components/redesign/index.ts web/tests/unit/redesign/tile.test.ts
```

---

## Task 7: Walkthrough and GhostRows

**Agent:** designer.

**Files:**
- Create: `web/src/components/redesign/Walkthrough.tsx`, `GhostRows.tsx`
- Modify: `redesign.css` (append), `index.ts` (append)
- Test: `web/tests/unit/redesign/states.test.ts`

**Interfaces:**
- Consumes: `SkeletonBlock`, `SkeletonLine` from `@/components/ui/skeleton`.
- Produces: `Walkthrough({ steps: { icon?: ElementType; title: string; body?: string }[] })` (numbered by default, matching every mock; an icon replaces the number when given); `GhostRows({ rows?: number; withLeading?: boolean })`.

- [ ] **Step 1: Write the failing test**

`web/tests/unit/redesign/states.test.ts`:

```ts
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { GhostRows, Walkthrough } from "@/components/redesign"

describe("Walkthrough", () => {
  it("an ordered list of numbered tips", () => {
    const out = renderToStaticMarkup(
      createElement(Walkthrough, {
        steps: [
          { title: "Scan a Maths paper", body: "Any past paper you have tried." },
          { title: "Lemely marks it" },
        ],
      }),
    )
    expect(out).toMatch(/^<ol class="rd-walk">/)
    expect(out).toContain('<span class="rd-walk-n" aria-hidden="true">1</span>')
    expect(out).toContain("<b>Scan a Maths paper</b><span>Any past paper you have tried.</span>")
    expect(out).toContain('<span class="rd-walk-n" aria-hidden="true">2</span>')
  })
})

describe("GhostRows", () => {
  it("one loading status around rows in the hairline geometry", () => {
    const out = renderToStaticMarkup(createElement(GhostRows, { rows: 2, withLeading: true }))
    expect(out.match(/role="status"/g)).toHaveLength(1)
    expect(out).toMatch(/aria-label="Loading"/)
    expect(out.match(/class="rd-ghostrow"/g)).toHaveLength(2)
    expect(out.match(/h-9 w-9/g)).toHaveLength(2)
  })
  it("defaults to three rows without a leading block", () => {
    const out = renderToStaticMarkup(createElement(GhostRows, {}))
    expect(out.match(/class="rd-ghostrow"/g)).toHaveLength(3)
    expect(out).not.toContain("h-9 w-9")
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/unit/redesign/states.test.ts`
Expected: FAIL, `Walkthrough` not exported.

- [ ] **Step 3: Write the implementation**

`web/src/components/redesign/Walkthrough.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ElementType } from "react"
import "./redesign.css"

export interface WalkthroughStep {
  /** Optional: the mocks number every tip; an icon replaces the number when given. */
  icon?: ElementType
  title: string
  body?: string
}

/** The first-run walkthrough list (mock .walk2 / .wn2). */
export function Walkthrough({ steps }: { steps: WalkthroughStep[] }) {
  return (
    <ol className="rd-walk">
      {steps.map((step, i) => {
        const Icon = step.icon
        return (
          <li key={step.title}>
            <span className="rd-walk-n" aria-hidden="true">
              {Icon ? <Icon size={18} /> : i + 1}
            </span>
            <span className="rd-at">
              <b>{step.title}</b>
              {step.body ? <span>{step.body}</span> : null}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
```

`web/src/components/redesign/GhostRows.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { SkeletonBlock, SkeletonLine } from "@/components/ui/skeleton"
import "./redesign.css"

/** Ghost skeleton rows in the hairline-row geometry. One status region; the pulse is the kit's (DESIGN.md §9.2). */
export function GhostRows({ rows = 3, withLeading = false }: { rows?: number; withLeading?: boolean }) {
  return (
    <div role="status" aria-label="Loading" className="rd-ghostrows">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="rd-ghostrow">
          {withLeading ? <SkeletonBlock announce={false} className="h-9 w-9 flex-none rounded-row bg-surface-container-high" /> : null}
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <SkeletonLine announce={false} width="60%" className="bg-surface-container-high" />
            <SkeletonLine announce={false} width="38%" className="h-3 bg-surface-container-high" />
          </div>
        </div>
      ))}
    </div>
  )
}
```

Append to `redesign.css`:

```css
/* ── Walkthrough and ghost rows (t.css .walk2/.wn2, .sk2c) ────────────── */
.rd-walk { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.rd-walk li { display: grid; grid-template-columns: 36px minmax(0, 1fr); gap: 12px; align-items: center; padding: 10px 0; }
.rd-walk li + li { border-top: 1px solid var(--md-outline-variant); }
.rd-walk-n { width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; background: var(--md-primary-container); color: var(--md-primary); font: 700 14px var(--font-mono); }
.rd-ghostrows { display: grid; }
.rd-ghostrow { display: flex; align-items: center; gap: 12px; min-height: 56px; padding: 11px 2px; }
.rd-ghostrow + .rd-ghostrow { border-top: 1px solid var(--md-outline-variant); }
```

Append to `index.ts`:

```ts
export { Walkthrough, type WalkthroughStep } from "./Walkthrough"
export { GhostRows } from "./GhostRows"
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run tests/unit/redesign/states.test.ts tests/unit/redesign/redesignCss.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(web): redesign walkthrough and ghost rows" -- web/src/components/redesign/Walkthrough.tsx web/src/components/redesign/GhostRows.tsx web/src/components/redesign/redesign.css web/src/components/redesign/index.ts web/tests/unit/redesign/states.test.ts
```

---

## Task 8: ComboChip, LevelBar, CountdownPill, and the contract test

**Agent:** designer.

**Files:**
- Create: `web/src/components/redesign/game.ts`, `ComboChip.tsx`, `LevelBar.tsx`, `countdown.ts`, `CountdownPill.tsx`
- Modify: `redesign.css` (append), `index.ts` (append)
- Test: `web/tests/unit/redesign/game.test.ts`, `web/tests/unit/redesign/contract.test.ts`

**Interfaces:**
- Consumes: `clamp01` (Task 2), `FlameGlyph`, `CalendarGlyph`, `SmallChevron`.
- Produces: `ComboChip({ count })`; `LevelBar({ level, xp, nextXp })`; `CountdownPill({ examDate, now?, subject?, to? })`; `countdownTone(examDate, now?)`; `daysUntil(examDate, now?)`; `countdownLabel(days, subject?)`.

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/redesign/game.test.ts`:

```ts
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { ComboChip, CountdownPill, LevelBar, countdownTone } from "@/components/redesign"
import { countdownLabel, daysUntil } from "@/components/redesign/countdown"
import { comboRose, comboVisible, levelFraction } from "@/components/redesign/game"

const NOW = new Date(2026, 10, 15, 21, 30) // 15 Nov 2026, late evening local time

describe("combo", () => {
  it("is hidden below 2 and bumps only on a rise", () => {
    expect([comboVisible(1), comboVisible(2)]).toEqual([false, true])
    expect([comboRose(2, 3), comboRose(3, 3), comboRose(4, 2)]).toEqual([true, false, false])
  })
  it("renders nothing below 2", () => {
    expect(renderToStaticMarkup(createElement(ComboChip, { count: 1 }))).toBe("")
  })
  it("shows ×N with a spoken name", () => {
    const out = renderToStaticMarkup(createElement(ComboChip, { count: 3 }))
    expect(out).toMatch(/^<span class="rd-combo">/)
    expect(out).toContain('<span aria-hidden="true">×3</span>')
    expect(out).toContain('<span class="sr-only">Combo of 3</span>')
  })
})

describe("LevelBar", () => {
  it("fills gold by xp over nextXp and reads as a progressbar", () => {
    expect([levelFraction(240, 500), levelFraction(10, 0), levelFraction(900, 500)]).toEqual([0.48, 0, 1])
    const out = renderToStaticMarkup(createElement(LevelBar, { level: 7, xp: 240, nextXp: 500 }))
    expect(out).toContain("<b>Level 7</b>")
    expect(out).toMatch(/role="progressbar"[^>]*aria-valuenow="240"[^>]*aria-valuetext="240 of 500 XP"/)
    expect(out).toContain('style="width:48%"')
    expect(out).toContain("<small>240 / 500 XP</small>")
  })
})

describe("countdown", () => {
  it("counts whole local days, ignoring the time of day", () => {
    expect(daysUntil("2026-11-16", NOW)).toBe(1)
    expect(daysUntil("2026-11-15", NOW)).toBe(0)
    expect(daysUntil("2027-05-14T09:00:00Z", NOW)).toBe(180)
  })
  it("turns near inside 30 days, neutral otherwise and after the exam", () => {
    expect([countdownTone("2026-12-15", NOW), countdownTone("2026-12-16", NOW), countdownTone("2026-11-14", NOW)]).toEqual(["near", "neutral", "neutral"])
  })
  it("labels", () => {
    expect(countdownLabel(180)).toBe("180 days to exams")
    expect(countdownLabel(1, "Physics")).toBe("1 day to Physics")
    expect(countdownLabel(0)).toBe("Exams today")
    expect(countdownLabel(188, null)).toBe("188 days")
    expect(countdownLabel(-1)).toBeNull()
  })
  it("renders a neutral pill, a near pill, and nothing after the exam", () => {
    expect(renderToStaticMarkup(createElement(CountdownPill, { examDate: "2027-05-14", now: NOW }))).toMatch(/data-tone="neutral".*180 days to exams/)
    expect(renderToStaticMarkup(createElement(CountdownPill, { examDate: "2026-12-01", now: NOW }))).toMatch(/data-tone="near"/)
    expect(renderToStaticMarkup(createElement(CountdownPill, { examDate: "2026-11-01", now: NOW }))).toBe("")
  })
})
```

`web/tests/unit/redesign/contract.test.ts` (compile-time contract check: `npm run typecheck` fails if a signature drifts from the master plan):

```ts
import type { ElementType, ReactNode } from "react"
import { describe, expect, it } from "vitest"
import * as Kit from "@/components/redesign"
import type { BinnyMood, BinnyMotion, Grade, TileTone, TopicState, Trend } from "@/components/redesign"

type Fn<P> = (p: P) => unknown

// Each line copies a signature from the F1 interface contract (master plan). Assignment fails to compile on drift.
const contract = {
  Binny: Kit.Binny satisfies Fn<{ mood: BinnyMood; size?: number; motion?: BinnyMotion; className?: string; "aria-hidden"?: boolean }>,
  BinnyLine: Kit.BinnyLine satisfies Fn<{ mood: BinnyMood; line: string; motion?: BinnyMotion; size?: number }>,
  StepsPath: Kit.StepsPath satisfies Fn<{ papers: { id: string; label: string; grade: Grade; pct: number }[]; goal?: Grade; onSelect?: (id: string) => void }>,
  GoldRing: Kit.GoldRing satisfies Fn<{ parts: [number, number, number]; size?: number; label?: string; center?: ReactNode }>,
  KeyRing: Kit.KeyRing satisfies Fn<{ value: number; size?: number; tone?: "tide" | "gold" | "ok" | "warn"; center: ReactNode; label: string }>,
  Tile: Kit.Tile satisfies Fn<{ icon: ElementType; title: string; status?: string; tone: TileTone; big?: boolean; to?: string; onClick?: () => void; disabled?: boolean }>,
  H2Row: Kit.H2Row satisfies Fn<{ title: string; link?: { label: string; to?: string; onClick?: () => void } }>,
  HairRows: Kit.HairRows satisfies Fn<{ children: ReactNode; "aria-label"?: string }>,
  HairRow: Kit.HairRow satisfies Fn<{ leading?: ReactNode; title: ReactNode; sub?: ReactNode; trailing?: ReactNode; to?: string; onClick?: () => void; selected?: boolean }>,
  TopicChip: Kit.TopicChip satisfies Fn<{ topic: string; state: TopicState; onClick?: () => void }>,
  TopicChips: Kit.TopicChips satisfies Fn<{ topics: { topic: string; state: TopicState }[]; foldSecure?: boolean; onSelect?: (topic: string) => void }>,
  RankRow: Kit.RankRow satisfies Fn<{ rank: number; title: string; sub?: string; marksLost: number; trend: Trend; assigned?: boolean; bar?: number; selected?: boolean; onClick?: () => void }>,
  Walkthrough: Kit.Walkthrough satisfies Fn<{ steps: { icon: ElementType; title: string; body?: string }[] }>,
  GhostRows: Kit.GhostRows satisfies Fn<{ rows?: number; withLeading?: boolean }>,
  ComboChip: Kit.ComboChip satisfies Fn<{ count: number }>,
  LevelBar: Kit.LevelBar satisfies Fn<{ level: number; xp: number; nextXp: number }>,
  CountdownPill: Kit.CountdownPill satisfies Fn<{ examDate: string; now?: Date }>,
  countdownTone: Kit.countdownTone satisfies (examDate: string, now?: Date) => "neutral" | "near",
}

describe("F1 interface contract", () => {
  it("exports every contract name as a function from the barrel", () => {
    for (const [name, value] of Object.entries(contract)) expect(typeof value, name).toBe("function")
  })
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npx vitest run tests/unit/redesign/game.test.ts tests/unit/redesign/contract.test.ts`
Expected: FAIL, `ComboChip` not exported.

- [ ] **Step 3: Write the implementation**

`web/src/components/redesign/game.ts`:

```ts
import { clamp01 } from "./rings"

/** The combo chip is hidden below 2 (mock pr.js runTop). */
export function comboVisible(count: number): boolean {
  return count >= 2
}

/** The chip bumps only when the count rises. */
export function comboRose(previous: number, next: number): boolean {
  return next > previous
}

export function levelFraction(xp: number, nextXp: number): number {
  return nextXp > 0 ? clamp01(xp / nextXp) : 0
}
```

`web/src/components/redesign/ComboChip.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useRef } from "react"
import { comboRose, comboVisible } from "./game"
import { FlameGlyph } from "./icons"
import "./redesign.css"

/** The gold combo chip (mock .combo). Hidden below 2; bumps when the count rises. */
export function ComboChip({ count }: { count: number }) {
  const previous = useRef(count)
  const rose = comboRose(previous.current, count)
  useEffect(() => {
    previous.current = count
  }, [count])
  if (!comboVisible(count)) return null
  // Re-keyed on every count so the bump replays; data-bump only on a rise.
  return (
    <span key={count} className="rd-combo" data-bump={rose || undefined}>
      <FlameGlyph />
      <span aria-hidden="true">{`×${count}`}</span>
      <span className="sr-only">{`Combo of ${count}`}</span>
    </span>
  )
}
```

The first render has `previous.current === count`, so SSR output carries no `data-bump`, which is what the test expects.

`web/src/components/redesign/LevelBar.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { levelFraction } from "./game"
import "./redesign.css"

/** Level, a gold XP bar and "240 / 500 XP" (mock .lvl2 / .lb). Gold because XP is earned. */
export function LevelBar({ level, xp, nextXp }: { level: number; xp: number; nextXp: number }) {
  const pct = Math.round(levelFraction(xp, nextXp) * 100)
  return (
    <div className="rd-level">
      <b>{`Level ${level}`}</b>
      <span
        className="rd-level-bar"
        role="progressbar"
        aria-label={`Level ${level}`}
        aria-valuemin={0}
        aria-valuemax={nextXp}
        aria-valuenow={Math.min(xp, nextXp)}
        aria-valuetext={`${xp} of ${nextXp} XP`}
      >
        <i style={{ width: `${pct}%` }} />
      </span>
      <small>{`${xp} / ${nextXp} XP`}</small>
    </div>
  )
}
```

`web/src/components/redesign/countdown.ts`:

```ts
const DAY_MS = 86_400_000

/** Whole calendar days from `now`'s local date to the exam's date (YYYY-MM-DD, time ignored). */
export function daysUntil(examDate: string, now: Date = new Date()): number {
  const [y, m, d] = examDate.slice(0, 10).split("-").map(Number)
  const exam = Date.UTC(y, m - 1, d)
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.round((exam - today) / DAY_MS)
}

/** Neutral until 30 days before the exam, then Tide (spec: exam countdown decision). */
export function countdownTone(examDate: string, now?: Date): "neutral" | "near" {
  const days = daysUntil(examDate, now)
  return days >= 0 && days <= 30 ? "near" : "neutral"
}

/** "180 days to exams", "1 day to Physics", "Exams today", "188 days" (subject null). Null after the exam. */
export function countdownLabel(days: number, subject: string | null = "exams"): string | null {
  if (days < 0) return null
  if (days === 0) return subject === null || subject === "exams" ? "Exams today" : `${subject} today`
  const span = `${days} ${days === 1 ? "day" : "days"}`
  return subject === null ? span : `${span} to ${subject}`
}
```

`web/src/components/redesign/CountdownPill.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Link } from "react-router-dom"
import { countdownLabel, countdownTone, daysUntil } from "./countdown"
import { CalendarGlyph, SmallChevron } from "./icons"
import "./redesign.css"

export interface CountdownPillProps {
  examDate: string
  now?: Date
  /** "exams" (default), a subject name, or null for a bare "188 days". */
  subject?: string | null
  /** The pill opens the study plan's exam dates (mock top6). */
  to?: string
}

/** Neutral pill; inside 30 days of the exam it turns Tide. Nothing after the exam. */
export function CountdownPill({ examDate, now, subject = "exams", to }: CountdownPillProps) {
  const text = countdownLabel(daysUntil(examDate, now), subject)
  if (text === null) return null
  const tone = countdownTone(examDate, now)
  const inner = (
    <>
      <CalendarGlyph />
      <span>{text}</span>
      {to ? <SmallChevron /> : null}
    </>
  )
  return to ? (
    <Link to={to} className="rd-pill" data-tone={tone}>
      {inner}
    </Link>
  ) : (
    <span className="rd-pill" data-tone={tone}>
      {inner}
    </span>
  )
}
```

Append to `redesign.css`:

```css
/* ── Combo, level, countdown (pr.css .combo, t.css .lvl2/.lb/.pill4) ──── */
.rd-combo {
  display: inline-flex; align-items: center; gap: 3px; padding: 3px 9px 3px 6px; border-radius: 10px;
  font: 800 13px var(--font-mono); color: var(--md-on-tertiary-container); background: var(--md-tertiary-container);
}
.rd-combo svg { color: var(--md-tertiary); }
.rd-level { display: grid; gap: 4px; }
.rd-level > b { font: 700 14px var(--font-sans); color: var(--md-on-surface); }
.rd-level > small { font: 600 12px var(--font-mono); color: var(--md-on-surface-variant); }
.rd-level-bar { display: block; height: 8px; border-radius: 4px; background: var(--md-surface-container-high); overflow: hidden; }
.rd-level-bar i { display: block; height: 100%; border-radius: 4px; background: var(--md-tertiary); }
.rd-pill {
  position: relative; display: inline-flex; align-items: center; gap: 6px; min-height: 32px; padding: 6px 11px;
  border-radius: 12px; white-space: nowrap; text-decoration: none; font: 600 12.5px var(--font-sans);
  color: var(--md-on-surface-variant); background: color-mix(in oklch, var(--md-surface-container-lowest) 70%, transparent);
}
.rd-pill[data-tone="near"] { color: var(--md-primary); background: color-mix(in oklch, var(--md-inverse-primary) 32%, var(--md-surface-container-lowest)); }
a.rd-pill::before { content: ""; position: absolute; inset: -8px -3px; }
a.rd-pill:active { transform: scale(0.97); }
a.rd-pill:focus-visible { outline: 2.5px solid var(--md-primary); outline-offset: 2px; }
.rd-pill .rd-chev { opacity: 0.55; margin-inline-start: -2px; }
@media (prefers-reduced-motion: no-preference) {
  .rd-combo[data-bump] { animation: rd-bump 0.5s var(--ease-out); }
}
@keyframes rd-bump { 0% { transform: scale(0.4); } 60% { transform: scale(1.15); } }
```

Append to `index.ts`:

```ts
export { ComboChip } from "./ComboChip"
export { LevelBar } from "./LevelBar"
export { CountdownPill, type CountdownPillProps } from "./CountdownPill"
export { countdownTone, countdownLabel, daysUntil } from "./countdown"
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd web && npx vitest run tests/unit/redesign && npm run typecheck`
Expected: every redesign test passes; typecheck clean (the contract file compiles).

- [ ] **Step 5: Prove the contract test goes red, then commit**

Temporarily change `LevelBar`'s prop `nextXp` to `next` and run `npm run typecheck`. Expected: an error in `contract.test.ts`. Revert, re-run, expect clean. Then:

```bash
git commit -S -m "feat(web): redesign combo chip, level bar, countdown pill and contract test" -- web/src/components/redesign/game.ts web/src/components/redesign/ComboChip.tsx web/src/components/redesign/LevelBar.tsx web/src/components/redesign/countdown.ts web/src/components/redesign/CountdownPill.tsx web/src/components/redesign/redesign.css web/src/components/redesign/index.ts web/tests/unit/redesign/game.test.ts web/tests/unit/redesign/contract.test.ts
```

---

## Task 9: Switch restyle

**Agent:** designer. The only existing kit piece whose mock differs. Stepper (a wizard indicator, not the mock's −/+ stepper), chip and skeleton stay as they are: the skeleton's sweep in the mock is banned by DESIGN.md §9.2, so the pulse stays (see Needs user decision 8).

**Files:**
- Modify: `web/src/components/ui/switch.tsx:88-111` (track and thumb classes only)
- Test: `web/tests/unit/redesign/switch.test.ts`

**Interfaces:**
- Consumes/Produces: `Switch` props unchanged. Callers (2) unchanged.

- [ ] **Step 1: Write the failing test**

`web/tests/unit/redesign/switch.test.ts`:

```ts
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { Switch } from "@/components/ui/switch"

/* Mock ph.css .sw: 48×28 track, 22px thumb, off = outline, on = primary, 20px travel, .2s. */
describe("Switch matches the redesign mock", () => {
  it("off: 48×28 outline track", () => {
    const out = renderToStaticMarkup(createElement(Switch, { label: "Weekly Maths email" }))
    expect(out).toMatch(/role="switch"[^>]*class="[^"]*\bh-7 w-12\b[^"]*\bbg-outline\b/)
    expect(out).toMatch(/h-\[22px\] w-\[22px\][^"]*translate-x-\[2px\]/)
  })
  it("on: primary track, thumb travels 20px", () => {
    const out = renderToStaticMarkup(createElement(Switch, { label: "Weekly Maths email", checked: true }))
    expect(out).toMatch(/aria-checked="true"[^>]*class="[^"]*\bbg-primary\b/)
    expect(out).toContain("translate-x-[22px]")
    expect(out).toContain("motion-reduce:transition-none")
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/unit/redesign/switch.test.ts`
Expected: FAIL (current track is `h-6 w-10`).

- [ ] **Step 3: Edit the classes**

In `web/src/components/ui/switch.tsx`, replace the button's class list and the thumb's class list with:

```tsx
          className={cn(
            "relative inline-flex h-7 w-12 flex-none cursor-pointer items-center rounded-full border",
            "transition-colors duration-200 ease-out motion-reduce:transition-none active:scale-[0.98]",
            "disabled:cursor-not-allowed disabled:opacity-50",
            isChecked ? "border-primary bg-primary" : "border-transparent bg-outline",
            resolvedState === "error" && "border-error",
            resolvedState === "success" && "border-success",
            className,
          )}
```

```tsx
            className={cn(
              "inline-flex h-[22px] w-[22px] flex-none items-center justify-center rounded-full bg-surface-container-lowest",
              "transition-transform duration-200 ease-out motion-reduce:transition-none",
              isChecked ? "translate-x-[22px] rtl:-translate-x-[22px]" : "translate-x-[2px] rtl:-translate-x-[2px]",
            )}
```

Re-derive the file's Hallmark stamp (add one if missing; `switch.tsx` is not on the frozen unstamped list only if it already has one; check line 1).

- [ ] **Step 4: Run to verify it passes, plus the kit gates**

Run: `cd web && npx vitest run tests/unit/redesign/switch.test.ts tests/unit/hallmarkStamp.test.ts tests/unit/rtlSafety.test.ts tests/unit/checkNativeInvariants.test.ts && npm run check:native`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "fix(web): switch matches the redesign mock" -- web/src/components/ui/switch.tsx web/tests/unit/redesign/switch.test.ts
```

---

## Task 10: Student shell: the mock tab bar and rail (Home, Practice, Scan, Subjects, Me)

**Agent:** designer.

**Ruling (coordinator, 2026-11-15):** the approved mock (`h6.js` TAB6/DRAIL6) wins for the student nav. Phone tabs: Home, Practice, [Scan centre button "Scan a paper"], Subjects, Me, with no appended More cell. Desktop rail: Home, Practice, Subjects, Me, plus a "Scan a paper" button. Classes and every other current destination move to a "More" group in the sidebar (rail, tablet drawer and phone sheet), next to the Subjects tree; Home doors (L1) link them too. Nothing is lost.

- **Practice** goes to `/student/practice`. L4 builds that root. Until it lands, F1 mounts `/student/practice` as `PracticeEntry`, which redirects to the current practice entry, `/student/practice/<first subject code>` (Home if the student has no subject yet). L4 replaces that one route element with its hub.
- **Subjects** has no approved root screen. Interim: the Subjects tab opens the shell's navigation sheet, which holds the existing subject tree (and the More group). See Needs user decision 1.
- `/student/practice*` and `/student/flashcards*` count as the Practice section (tab and rail item active); `/student/subject/*` as Subjects; `/student/profile` as Me.

**Files:**
- Create: `web/src/portals/student/shellNav.ts` (pure), `web/src/portals/student/screens/PracticeEntry.tsx`
- Modify: `web/src/portals/student/shell.tsx` (tabs, sidebar items and groups, Scan button)
- Modify: `web/src/portals/student/index.tsx` (one lazy import, one `practice` route entry before `practice/:subjectCode`)
- Modify: `web/src/components/shell/PortalShell.tsx` (optional `moreTab` and `navTabId`/`navTabActive`)
- Modify: `web/src/components/ui/nav-shells.tsx:170-184` (emphasis span and label)
- Modify: `web/src/components/shell/icons.tsx` (add `cam`), `web/src/components/shell/shellStyles.ts` (add `SHELL_BUTTON_OUTLINE`)
- Modify: `web/src/index.css:452` (`--native-tab-emphasis-size: 56px`, comment updated)
- Modify: `web/tests/unit/studentShell.test.ts:53-55`, `web/tests/unit/navigation.test.ts:251-259` (skip the drawer tab, which has no route)
- Modify: `web/e2e/native-feel.spec.ts:225-237` (Assertion 6 taps the "Classes" tab; it becomes "Me" with `/student/profile`)
- Modify: `web/scripts/drift/checks-native.mjs`, `web/scripts/drift/checks-shell.mjs` (tab names, see Step 3)
- Test: `web/tests/unit/redesign/studentShellScan.test.ts`

**Interfaces:**
- Produces:
  - `STUDENT_BOTTOM_TABS: readonly { id: string; label: string; to?: string; end?: boolean; icon: Icon; opensNav?: true }[]` = Home (`/student`), Practice (`/student/practice`), Scan a paper (`/student/correct`, emphasis), Subjects (`opensNav`), Me (`/student/profile`). L4 no longer edits this list.
  - `shellNav.ts`: `STUDENT_PRACTICE_TO = "/student/practice"`, `isPracticeSection(path)`, `isSubjectsSection(path)`, `studentOverflowItems(items)`.
  - `PracticeEntry` (route element L4 replaces).
  - `PortalShellProps.moreTab?: boolean` (default true), `navTabId?: string`, `navTabActive?: boolean`.
  - `SHELL_BUTTON_OUTLINE` (string); `ShellIcon name="cam"`.

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/redesign/studentShellScan.test.ts`:

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { BottomNav } from "@/components/ui/nav-shells"
import { STUDENT_BOTTOM_TABS } from "@/portals/student"
import { isPracticeSection, isSubjectsSection, studentOverflowItems } from "@/portals/student/shellNav"

const SRC = join(fileURLToPath(new URL("../../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")

describe("student tab bar (mock h6.js TAB6)", () => {
  it("is Home, Practice, Scan, Subjects, Me, with Scan in the centre", () => {
    expect(STUDENT_BOTTOM_TABS.map((t) => t.label)).toEqual(["Home", "Practice", "Scan a paper", "Subjects", "Me"])
    expect(STUDENT_BOTTOM_TABS[2]).toMatchObject({ id: "scan", to: "/student/correct" })
    expect(STUDENT_BOTTOM_TABS.find((t) => t.id === "practice")?.to).toBe("/student/practice")
    expect(STUDENT_BOTTOM_TABS.find((t) => t.id === "subjects")).toMatchObject({ opensNav: true })
    expect(STUDENT_BOTTOM_TABS.find((t) => t.id === "subjects")?.to).toBeUndefined()
  })

  it("has no appended More cell; Subjects opens the navigation sheet", () => {
    const shell = read("portals/student/shell.tsx")
    expect(shell).toContain("moreTab={false}")
    expect(shell).toContain('navTabId="subjects"')
    const portal = read("components/shell/PortalShell.tsx")
    expect(portal).toMatch(/moreTab\?: boolean/)
    expect(portal).toMatch(/navTabId\?: string/)
  })

  it("Practice covers practice and flashcards; Subjects covers subject pages", () => {
    for (const p of ["/student/practice", "/student/practice/0580", "/student/practice/set/a1", "/student/flashcards/0580", "/student/flashcards/review/0580"])
      expect(isPracticeSection(p), p).toBe(true)
    expect(isPracticeSection("/student/practiced")).toBe(false)
    expect(isSubjectsSection("/student/subject/0580")).toBe(true)
    expect(isSubjectsSection("/student")).toBe(false)
  })

  it("every old sidebar destination except Overview lands in the More group", () => {
    const items = [{ to: "/student" }, { to: "/student/classes" }, { to: "/student/board" }]
    expect(studentOverflowItems(items)).toEqual([{ to: "/student/classes" }, { to: "/student/board" }])
    expect(read("portals/student/shell.tsx")).toMatch(/label: "More"/)
  })

  it("mounts /student/practice as the interim entry", () => {
    expect(read("portals/student/index.tsx")).toMatch(/path: "practice",\s*element: <PracticeEntry \/>/)
  })

  it("the raised tab is a soft Tide squircle with a visually hidden label", () => {
    const out = renderToStaticMarkup(
      createElement(MemoryRouter, null,
        createElement(BottomNav, {
          items: [{ id: "scan", label: "Scan a paper", to: "/student/correct", icon: createElement("svg") }],
          emphasisId: "scan",
        }),
      ),
    )
    expect(out).toMatch(/data-emphasis="true"[^>]*class="[^"]*\bh-14 w-14 rounded-tile bg-inverse-primary text-primary\b/)
    expect(out).toMatch(/class="lm-native-tab-label text-xs sr-only">Scan a paper</)
  })

  it("the rail foot and the tablet bar say Scan a paper with the camera, outlined", () => {
    const shell = readFileSync(join(SRC, "portals/student/shell.tsx"), "utf8")
    expect(shell).toContain("SHELL_BUTTON_OUTLINE")
    expect(shell).toContain('<ShellIcon name="cam" />')
    expect(shell).toContain("<span>Scan a paper</span>")
    expect(shell).toMatch(/scan\("me-2\.5 max-shell-sm:hidden shell-lg:hidden"\)/)
    expect(shell).not.toContain("Upload a paper")
  })
})
```

Edit `web/tests/unit/studentShell.test.ts:53-55`:

```ts
  it("uses the mock's tab bar: Home, Practice, Scan, Subjects, Me", () => {
    expect(STUDENT_BOTTOM_TABS.map((t) => t.label)).toEqual(["Home", "Practice", "Scan a paper", "Subjects", "Me"])
  })
```

Edit `web/tests/unit/navigation.test.ts:251-259` (the Subjects tab opens the sheet and has no route):

```ts
  it("every student tab with a route points at a mounted student route", () => {
    for (const tab of STUDENT_BOTTOM_TABS) {
      if (!tab.to) {
        expect(tab.opensNav, `${tab.label} has neither a route nor the sheet`).toBe(true)
        continue
      }
      expect(matchesSomeRoute(tab.to, studentRoutePaths), `${tab.to} is not a mounted student route`).toBe(true)
    }
  })
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npx vitest run tests/unit/redesign/studentShellScan.test.ts tests/unit/studentShell.test.ts tests/unit/navigation.test.ts`
Expected: FAIL (labels, `shellNav` missing, no `practice` route).

- [ ] **Step 3: Implement**

`web/src/components/shell/icons.tsx`, add to `PATHS` (the mock CAM on the 24-unit grid):

```ts
  cam: "M6 6.5h12a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3v-7a3 3 0 0 1 3-3z M12 9.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z M8.7 6.5l1.6-2.2h3.4l1.6 2.2",
```

`web/src/components/shell/shellStyles.ts`, add after `SHELL_BUTTON_TONAL`:

```ts
/** Mock DRAIL6 `.rscan.soft`: the outlined "Scan a paper" (rail foot, tablet bar). */
export const SHELL_BUTTON_OUTLINE = `${SHELL_BUTTON} bg-transparent text-primary shadow-[inset_0_0_0_1.5px_var(--color-primary)] hover:bg-primary-container`
```

`web/src/portals/student/shellNav.ts`:

```ts
/*
 * Pure student nav rules for the mock tab bar and rail (student-r2/h6.js TAB6/DRAIL6).
 */

/** The Practice tab's root. L4's hub replaces the interim PracticeEntry at this path. */
export const STUDENT_PRACTICE_TO = "/student/practice"

/** Practice and flashcards both light the Practice tab and rail item. */
export function isPracticeSection(path: string): boolean {
  return /^\/student\/(practice|flashcards)(\/|$)/.test(path)
}

/** Subject pages light the Subjects tab. */
export function isSubjectsSection(path: string): boolean {
  return /^\/student\/subject\/[^/]+/.test(path)
}

/** The old sidebar rows minus Overview (Home is a tab): they become the sidebar's More group. */
export function studentOverflowItems<T extends { to: string }>(items: readonly T[]): T[] {
  return items.filter((item) => item.to !== "/student")
}
```

`web/src/portals/student/screens/PracticeEntry.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Navigate } from "react-router-dom"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { useOverview } from "@/lib/hooks/useStudentApi"

/**
 * Interim Practice tab root (F1). There is no subject-free practice screen yet,
 * so this opens the current practice entry for the first subject, or Home when
 * the student has none. L4 replaces this route's element with the Practice hub.
 */
export function PracticeEntry() {
  const overview = useOverview()
  if (overview.isPending) return <RouteSkeleton />
  const first = overview.data?.subjects[0]?.code
  return <Navigate to={first ? `/student/practice/${encodeURIComponent(first)}` : "/student"} replace />
}
```

`web/src/portals/student/index.tsx`: add a lazy import next to the other practice screens and this entry directly before `practice/:subjectCode`:

```tsx
const PracticeEntry = lazy(() => import("./screens/PracticeEntry").then((m) => ({ default: m.PracticeEntry })))
```

```tsx
    // F1: the Practice tab's root. L4 swaps this element for the Practice hub.
    {
      path: "practice",
      element: <PracticeEntry />,
      handle: { title: "Practice", skeleton: "list" },
    },
```

`web/src/components/shell/PortalShell.tsx`: add to `PortalShellProps`:

```ts
  /** Append the shell's "More" cell (default true). The student bar has the mock's five tabs and reaches overflow through the navigation sheet. */
  moreTab?: boolean
  /** The bottom tab (by id) that opens the navigation sheet instead of a route (student Subjects, until it has a root screen). */
  navTabId?: string
  /** That tab's active state (its section is open). */
  navTabActive?: boolean
```

Destructure them (`moreTab = true`) and build the bar's items as:

```tsx
      <BottomNav
        items={[
          ...bottomTabs.map((tab): NavShellItem =>
            tab.id === navTabId
              ? { ...tab, to: undefined, onClick: () => setNavOpen(true), popup: { expanded: navOpen }, active: navTabActive }
              : tab,
          ),
          ...(moreTab
            ? [
                {
                  id: "more",
                  label: "More",
                  icon: <List size={22} aria-hidden="true" />,
                  // Native phones get the titled sheet; tablet and desktop keep the drawer.
                  onClick: () => (native ? setMoreOpen(true) : setNavOpen(true)),
                  popup: { expanded: native ? moreOpen : navOpen },
                },
              ]
            : []),
        ]}
```

The teacher shell passes neither prop and is unchanged.

`web/src/portals/student/shell.tsx`:
- Imports: `Camera`, `House`, `Notepad`, `SquaresFour`, `UserCircle` from `@phosphor-icons/react` (drop `ChalkboardTeacher` and `NotePencil` if unused); `SHELL_BUTTON_OUTLINE` instead of `SHELL_BUTTON_PRIMARY`; `ShellNavList` from `@/components/shell/ShellNavList`; `STUDENT_PRACTICE_TO`, `isPracticeSection`, `isSubjectsSection`, `studentOverflowItems` from `./shellNav`.
- Replace the tab list and its doc comment:

```tsx
/** The phone tabs, as the approved mock draws them (student-r2/h6.js TAB6): Home,
 * Practice, the raised Scan button, Subjects, Me. No appended More: overflow lives in
 * the navigation sheet, which the Subjects tab opens until Subjects has a root screen. */
export const STUDENT_BOTTOM_TABS: readonly { id: string; label: string; to?: string; end?: boolean; icon: Icon; opensNav?: true }[] = [
  { id: "home", label: "Home", to: "/student", end: true, icon: House },
  { id: "practice", label: "Practice", to: STUDENT_PRACTICE_TO, icon: Notepad },
  { id: "scan", label: "Scan a paper", to: "/student/correct", icon: Camera },
  { id: "subjects", label: "Subjects", icon: SquaresFour, opensNav: true },
  { id: "me", label: "Me", to: "/student/profile", icon: UserCircle },
]
```

- Sidebar rows (mock DRAIL6: Home, Practice, Subjects, Me). `items` are Home, Practice and Me; the Subjects tree group follows them, then a new More group with every other old row:

```tsx
  const practiceActive = isPracticeSection(pagePath)
  const primaryItems: NavShellItem[] = [
    { id: "/student", to: "/student", end: true, label: "Home", icon: <ShellIcon name="home" /> },
    { id: STUDENT_PRACTICE_TO, to: STUDENT_PRACTICE_TO, label: "Practice", icon: <ShellIcon name="practice" />, active: practiceActive || undefined },
    { id: "/student/profile", to: "/student/profile", label: "Me", icon: <ShellIcon name="user" /> },
  ]
  const moreItems = studentOverflowItems(navItems)
```

  `navItems` is the existing mapped `studentNavItems` (it keeps the settings-dialog `active` logic). Pass `items: primaryItems` and `groups: [subjectsGroup, { id: "more", label: "More", render: () => <ShellNavList items={moreItems} /> }]`, where `subjectsGroup` is the existing Subjects group unchanged.
- Replace `upload` with:

```tsx
  const scan = (className?: string) => (
    <Link to="/student/correct" viewTransition className={cn(SHELL_BUTTON_OUTLINE, className)} {...prefetchCorrectPaper}>
      <ShellIcon name="cam" />
      <span>Scan a paper</span>
    </Link>
  )
```

- `footerAction: scan(),`
- Top bar action: `{location.pathname === "/student/correct" ? null : scan("me-2.5 max-shell-sm:hidden shell-lg:hidden")}` (the rail has it from `shell-lg`, mock DRAIL6; tablet keeps it, mock TTOP).
- `titleLevel` uses `isTabRoot(pagePath, STUDENT_BOTTOM_TABS.flatMap((tab) => (tab.to ? [tab.to] : [])))`.
- Bottom tabs:

```tsx
      bottomTabs={STUDENT_BOTTOM_TABS.map(
        (tab): NavShellItem => ({
          id: tab.id,
          to: tab.to,
          end: tab.end,
          label: tab.label,
          icon: <tab.icon size={22} aria-hidden="true" />,
          activeIcon: <tab.icon size={22} weight="fill" aria-hidden="true" />,
          active: tab.id === "practice" && practiceActive ? true : undefined,
          prefetch: tab.id === "scan" ? prefetchCorrectPaper.onPointerEnter : undefined,
        }),
      )}
      bottomEmphasisId="scan"
      moreTab={false}
      navTabId="subjects"
      navTabActive={isSubjectsSection(pagePath)}
```

Check on a phone that the top bar's menu button and the Subjects tab both open the sheet, and that the sheet lists the Subjects tree and the More group (Your classes, Standings, Friends, Tutors, Sessions). The sheet hides the rail foot's Scan (the bar has it).

`web/src/components/ui/nav-shells.tsx`, the emphasis span and the label:

```tsx
                <span
                  data-emphasis={emphasis || undefined}
                  className={cn(
                    "lm-native-tab-icon relative flex items-center justify-center",
                    // Mock TAB6 `.scanc.soft`: a raised soft-Tide squircle, label visually hidden.
                    emphasis &&
                      "-mt-5 h-14 w-14 rounded-tile bg-inverse-primary text-primary shadow-[0_10px_18px_-12px_color-mix(in_oklch,var(--md-shadow)_45%,transparent)]",
                  )}
                >
```

```tsx
                <span className={cn("lm-native-tab-label text-xs", isActive && "font-medium", emphasis && "sr-only")}>{item.label}</span>
```

Update the `emphasisId` doc comment to "the student portal's Scan tab". `index.css:452`:

```css
  --native-tab-emphasis-size: 56px;         /* the raised Scan tab's squircle (nav-shells h-14 w-14, mock TAB6 .scanc) */
```

`web/e2e/native-feel.spec.ts` Assertion 6: replace both `nav.getByRole("link", { name: "Classes", exact: true })` with `nav.getByRole("link", { name: "Me", exact: true })` and both `/\/student\/classes$/` with `/\/student\/profile$/`.

Drift scripts (not a CI gate, but keep them runnable):
- `checks-native.mjs`: `tabTap(page, "Correct")` → `"Scan a paper"`; `tabTap(page, "Profile")` → `"Me"`; `tabTap(page, "Overview")` → `"Home"`; `tabTap(page, "Classes")` → `"Me"`. Every tab-bar-scoped `getByRole("link", { name: "Classes" })` (`nav.lm-native-tabbar`, or the `Primary` navigation, at 413, 428, 1478, 1501, 1827, 4576, 4757) → `"Me"` with the profile heading. Rows that click "Classes" in the sheet or sidebar keep working: "Your classes" now sits in the More group. List them with `grep -n '"Classes"\|"Profile"\|"Overview"\|"Correct"' web/scripts/drift/checks-native.mjs` and confirm each one.
- `checks-native.mjs:979`: `STUDENT_TAB_PATHS = ["/student", "/student/profile"]` (Practice redirects to a subject's practice page until L4, and Subjects is the sheet). Comment at 977-978 updated to match.
- `checks-native.mjs:571`: message `"pill overlaps the Scan tab"`.
- `checks-shell.mjs:323`: `{ name: "Scan a paper" }`, message `"sheet: Scan should be hidden (bottom bar has it)"`. `checks-shell.mjs:476` expects the fresh-load active sidebar row "Overview"; it becomes `"Home"`.

- [ ] **Step 4: Run to verify, plus every source-scanning test this touches**

Run: `cd web && npx vitest run tests/unit/redesign/studentShellScan.test.ts tests/unit/studentShell.test.ts tests/unit/navigation.test.ts tests/unit/nativeTabBar.test.ts tests/unit/nativeFrameCss.test.ts tests/unit/nativeAuditA.test.ts tests/unit/nativeMechanics.test.ts tests/unit/checkNativeInvariants.test.ts tests/unit/hallmarkStamp.test.ts tests/unit/design-tokens.test.ts tests/unit/utilityExistence.test.ts tests/unit/contrastRules.test.ts tests/unit/routeSkeleton.test.ts && npm run lint && npm run typecheck`
Expected: PASS. If `nativeMechanics` or `check:native` flags `nav-shells.tsx`, the emphasis classes are missing an `active:`; the link already carries `active:scale-[0.98]`. Then with the stack up: `npx playwright test e2e/native-feel.spec.ts e2e/student-journey.spec.ts`.

- [ ] **Step 5: Look at it, then commit**

Run `npm run dev`, sign in as a seeded student, check at 390 (Home, Practice, raised Scan, Subjects, Me; Scan's label hidden, accessible name "Scan a paper"; Practice opens the first subject's practice and stays lit there and on flashcards; Subjects opens the sheet with the subject tree and the More group), 1024 (top bar outline "Scan a paper", drawer with the same groups), 1280 (rail: Home, Practice, Me, Subjects tree, More group, outline "Scan a paper" at the foot, none in the bar). Then:

```bash
git commit -S -m "feat(web): student tab bar and rail follow the approved mock" -- web/src/portals/student/shell.tsx web/src/portals/student/shellNav.ts web/src/portals/student/screens/PracticeEntry.tsx web/src/portals/student/index.tsx web/src/components/shell/PortalShell.tsx web/src/components/ui/nav-shells.tsx web/src/components/shell/icons.tsx web/src/components/shell/shellStyles.ts web/src/index.css web/tests/unit/studentShell.test.ts web/tests/unit/navigation.test.ts web/tests/unit/redesign/studentShellScan.test.ts web/e2e/native-feel.spec.ts web/scripts/drift/checks-native.mjs web/scripts/drift/checks-shell.mjs
```

**Playwright drift scenes this changes** (re-run with the drift harness in Task 14 and re-justify; `approved` needs the user):

| Scene key | What changed |
|---|---|
| `student-populated-frame`, `@390`, `@768`, `-1024` | tab order and Scan squircle (390), top bar Scan outline (768, 1024), rail foot (1280) |
| `student-new-frame`, `@390`, `@768`, `-1024` | same |
| `student-subject-frame`, `@390`, `@768`, `-1024` | same |
| `student-notifications-frame`, `@390`, `@768`, `-1024` | same |
| `student-bell`, `@390`, `@768`, `-1024` | top bar and tab bar behind the panel |
| `student-account`, `@390`, `@768`, `-1024` | same |
| `student-drawer`, `student-drawer-home` | drawer foot shows "Scan a paper" outline (768); phone sheet still hides it |
| `student-settings-{profile,account,notifications,appearance,install}` and each `-1024` | rail foot and top bar under the scrim |
| `native-ios-root-top`, `native-ios-root-scrolled`, `native-ios-detail` | tab set and raised tab: justification text says "Overview, Correct, Classes, Profile, More" and must become "Home, Practice, Scan (raised), Subjects, Me", which now matches the mock's set |
| `native-android-root-top`, `native-android-root-scrolled`, `native-android-detail`, `native-android-412-root-top`, `native-android-412-root-scrolled` | same, plus the 56px emphasis box |
| checks `native-*-tab-label-weights`, `native-android-active-pill-centred-clear`, the tab-tap nav checks at `checks-native.mjs` 3988–4250, the "Classes" tab checks at 413–432, 1478–1501, 1827, 4576, 4757, `checks-shell.mjs:323` and `:476` | label strings and `STUDENT_TAB_PATHS` updated in this task; re-run to confirm green |
| sidebar rows in `student-*-frame` and settings scenes (all widths with a rail or drawer) | rows are Home, Practice, Me, the Subjects tree and a More group, where they were Overview, Your classes, Standings, Friends, Tutors, Sessions |

Teacher scenes are untouched (teacher has no emphasis tab and keeps `SHELL_BUTTON_PRIMARY`).

---

## Task 11: Parent shell model and ChildSwitcher

**Agent:** designer.

**Files:**
- Create: `web/src/portals/parent/shellModel.ts`, `web/src/portals/parent/ChildSwitcher.tsx`
- Test: `web/tests/unit/redesign/parentShellModel.test.ts`

**Interfaces:**
- Consumes: `useChildren()` (`@/lib/hooks/useParentApi`, `data.children: { childId: string; displayName: string }[]`), `Crumb` (`@/components/ui/breadcrumbs`).
- Produces:
  - `parentTabs(childId: string | null): { id: 'overview'|'topics'|'inbox'|'tutoring'; label: string; to: string; end?: boolean }[]`
  - `resolveChildId(param: string | null, childIds: readonly string[], last: string | null): string | null`
  - `parentShellTrail(path: string, o: { childId: string | null; hasChildList: boolean; subjectLabel: string | null }): Crumb[]`
  - `parentPageTitle(path: string, subjectLabel: string | null): string`
  - `switchChildPath(pathname: string, nextChildId: string): string`
  - `topicsActive(path: string): boolean`
  - `ChildSwitcher({ className?: string })`

- [ ] **Step 1: Write the failing test**

`web/tests/unit/redesign/parentShellModel.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { parentPageTitle, parentShellTrail, parentTabs, resolveChildId, switchChildPath, topicsActive } from "@/portals/parent/shellModel"

describe("parentTabs (mock pa.js ptab)", () => {
  it("four tabs for a child: Overview, Topics, Inbox, Tutoring", () => {
    expect(parentTabs("c1")).toEqual([
      { id: "overview", label: "Overview", to: "/parent/children/c1", end: true },
      { id: "topics", label: "Topics", to: "/parent/children/c1/topics", end: false },
      { id: "inbox", label: "Inbox", to: "/parent/notifications", end: false },
      { id: "tutoring", label: "Tutoring", to: "/parent/children/c1/tutoring", end: false },
    ])
  })
  it("without a child every child tab goes to the children list, exactly", () => {
    const tabs = parentTabs(null)
    expect(tabs.filter((t) => t.id !== "inbox").every((t) => t.to === "/parent" && t.end)).toBe(true)
  })
  it("encodes the id", () => {
    expect(parentTabs("a/b")[0].to).toBe("/parent/children/a%2Fb")
  })
})

describe("resolveChildId", () => {
  it("URL first, then the last child viewed, then the first child", () => {
    expect(resolveChildId("c2", ["c1", "c2"], "c1")).toBe("c2")
    expect(resolveChildId(null, ["c1", "c2"], "c2")).toBe("c2")
    expect(resolveChildId(null, ["c1", "c2"], "gone")).toBe("c1")
    expect(resolveChildId(null, [], null)).toBeNull()
  })
})

describe("parentShellTrail (ported from ParentTrail, index.tsx:178-225)", () => {
  const one = { childId: "c1", hasChildList: false, subjectLabel: null }
  const many = { ...one, hasChildList: true }
  it("overview: one crumb, so no trail row, unless there is a children list", () => {
    expect(parentShellTrail("/parent/children/c1", one)).toEqual([{ label: "Overview" }])
    expect(parentShellTrail("/parent/children/c1/", many)).toEqual([{ label: "Your children", to: "/parent" }, { label: "Overview" }])
  })
  it("topics and the old weaknesses path", () => {
    const want = [{ label: "Overview", to: "/parent/children/c1" }, { label: "Topics" }]
    expect(parentShellTrail("/parent/children/c1/topics", one)).toEqual(want)
    expect(parentShellTrail("/parent/children/c1/weaknesses", one)).toEqual(want)
  })
  it("tutoring, tutor access and a session", () => {
    expect(parentShellTrail("/parent/children/c1/tutor-access", one).map((c) => c.label)).toEqual(["Overview", "Tutoring", "Who they share with"])
    expect(parentShellTrail("/parent/children/c1/sessions/b9", one).map((c) => c.label)).toEqual(["Overview", "Tutoring", "Session"])
  })
  it("a subject uses its cached name, else the code, else This subject", () => {
    expect(parentShellTrail("/parent/children/c1/subjects/0625", { ...one, subjectLabel: "Physics" }).at(-1)).toEqual({ label: "Physics" })
    expect(parentShellTrail("/parent/children/c1/subjects/0625", one).at(-1)).toEqual({ label: "0625" })
  })
  it("no child route, no trail", () => {
    expect(parentShellTrail("/parent/notifications", { ...many, childId: null })).toEqual([])
  })
})

describe("parentPageTitle", () => {
  it.each([
    ["/parent", "Your children"],
    ["/parent/children/c1", "Overview"],
    ["/parent/children/c1/topics", "Topics to work on"],
    ["/parent/children/c1/weaknesses", "Topics to work on"],
    ["/parent/children/c1/tutoring", "Tutoring"],
    ["/parent/children/c1/tutor-access", "Who they share with"],
    ["/parent/children/c1/sessions/b9", "Session details"],
    ["/parent/notifications", "Notifications"],
    ["/parent/tutors", "Tutors"],
    ["/parent/tutors/t1", "Tutor profile"],
    ["/parent/tutors/t1/book", "Book a session"],
    ["/parent/nope", "Page not found"],
  ])("%s → %s", (path, title) => {
    expect(parentPageTitle(path, null)).toBe(title)
  })
  it("a subject page is titled by the subject", () => {
    expect(parentPageTitle("/parent/children/c1/subjects/0625", "Physics")).toBe("Physics")
    expect(parentPageTitle("/parent/children/c1/subjects/0625", null)).toBe("0625")
  })
})

describe("switchChildPath (index.tsx:120-124, plus topics)", () => {
  it("keeps the topics, weaknesses, tutoring and tutor-access tails", () => {
    expect(switchChildPath("/parent/children/c1/topics", "c2")).toBe("/parent/children/c2/topics")
    expect(switchChildPath("/parent/children/c1/weaknesses", "c2")).toBe("/parent/children/c2/weaknesses")
    expect(switchChildPath("/parent/children/c1/tutor-access", "c2")).toBe("/parent/children/c2/tutor-access")
  })
  it("anything else lands on the overview", () => {
    expect(switchChildPath("/parent/children/c1/subjects/0625", "c2")).toBe("/parent/children/c2")
  })
})

describe("topicsActive", () => {
  it("lights the Topics tab on both paths", () => {
    expect([topicsActive("/parent/children/c1/topics"), topicsActive("/parent/children/c1/weaknesses"), topicsActive("/parent/children/c1")]).toEqual([true, true, false])
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/unit/redesign/parentShellModel.test.ts`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

`web/src/portals/parent/shellModel.ts`:

```ts
import type { Crumb } from "@/components/ui/breadcrumbs"

/*
 * Pure parent shell logic (F1). The four tabs come from the approved parent mock
 * (student-r2/pa.js `ptab`); the trail is ParentTrail's rules, moved out of the
 * old header so the shared shell's top bar can render it.
 */

export type ParentTabId = "overview" | "topics" | "inbox" | "tutoring"

export interface ParentTab {
  id: ParentTabId
  label: string
  to: string
  end: boolean
}

const childBase = (childId: string) => `/parent/children/${encodeURIComponent(childId)}`

/** With no child (none linked yet, or still loading) the child tabs go to the children list, matched exactly. */
export function parentTabs(childId: string | null): ParentTab[] {
  const base = childId ? childBase(childId) : null
  return [
    { id: "overview", label: "Overview", to: base ?? "/parent", end: true },
    { id: "topics", label: "Topics", to: base ? `${base}/topics` : "/parent", end: !base },
    { id: "inbox", label: "Inbox", to: "/parent/notifications", end: false },
    { id: "tutoring", label: "Tutoring", to: base ? `${base}/tutoring` : "/parent", end: !base },
  ]
}

/** The child the tabs follow: the URL's, else the last one viewed, else the first linked child. */
export function resolveChildId(param: string | null, childIds: readonly string[], last: string | null): string | null {
  if (param) return param
  if (last && childIds.includes(last)) return last
  return childIds[0] ?? null
}

const clean = (path: string) => path.replace(/\/+$/, "") || "/"

export function topicsActive(path: string): boolean {
  return /\/(topics|weaknesses)$/.test(clean(path))
}

export function parentShellTrail(
  path: string,
  { childId, hasChildList, subjectLabel }: { childId: string | null; hasChildList: boolean; subjectLabel: string | null },
): Crumb[] {
  if (!childId) return []
  const p = clean(path)
  const overview = childBase(childId)
  const trail: Crumb[] = hasChildList ? [{ label: "Your children", to: "/parent" }] : []
  if (p === overview) trail.push({ label: "Overview" })
  else if (topicsActive(p)) trail.push({ label: "Overview", to: overview }, { label: "Topics" })
  else if (p.endsWith("/tutoring")) trail.push({ label: "Overview", to: overview }, { label: "Tutoring" })
  else if (p.endsWith("/tutor-access"))
    trail.push({ label: "Overview", to: overview }, { label: "Tutoring", to: `${overview}/tutoring` }, { label: "Who they share with" })
  else if (/\/sessions\/[^/]+$/.test(p))
    trail.push({ label: "Overview", to: overview }, { label: "Tutoring", to: `${overview}/tutoring` }, { label: "Session" })
  else if (/\/subjects\/([^/]+)$/.test(p)) {
    const code = decodeURIComponent(p.split("/").pop() ?? "")
    trail.push({ label: "Overview", to: overview }, { label: subjectLabel ?? (code || "This subject") })
  } else trail.push({ label: "Overview", to: overview })
  return trail
}

/** The top bar title; route handle titles where they exist, the subject's name on a subject page. */
export function parentPageTitle(path: string, subjectLabel: string | null): string {
  const p = clean(path)
  if (p === "/parent") return "Your children"
  if (p === "/parent/notifications") return "Notifications"
  if (p === "/parent/tutors") return "Tutors"
  if (/^\/parent\/tutors\/[^/]+\/book$/.test(p)) return "Book a session"
  if (/^\/parent\/tutors\/[^/]+$/.test(p)) return "Tutor profile"
  if (/^\/parent\/children\/[^/]+$/.test(p)) return "Overview"
  if (topicsActive(p)) return "Topics to work on"
  if (p.endsWith("/tutor-access")) return "Who they share with"
  if (p.endsWith("/tutoring")) return "Tutoring"
  if (/\/sessions\/[^/]+$/.test(p)) return "Session details"
  const subject = p.match(/\/subjects\/([^/]+)$/)
  if (subject) return subjectLabel ?? decodeURIComponent(subject[1])
  return "Page not found"
}

const KEPT_TAILS = ["/topics", "/weaknesses", "/tutoring", "/tutor-access"]

/** Switching child keeps the parent's place where the path still makes sense; a subject the other child does not take would 404, so it lands on the overview. */
export function switchChildPath(pathname: string, nextChildId: string): string {
  const tail = KEPT_TAILS.find((t) => clean(pathname).endsWith(t)) ?? ""
  return `${childBase(nextChildId)}${tail}`
}
```

`web/src/portals/parent/ChildSwitcher.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { CaretDown } from "@phosphor-icons/react"
import { useLocation, useNavigate, useParams } from "react-router-dom"
import { useChildren } from "@/lib/hooks/useParentApi"
import { cn } from "@/lib/utils"
import { switchChildPath } from "./shellModel"

const PILL =
  "relative inline-flex min-h-11 flex-none items-center gap-1.5 rounded-full bg-surface-container-lowest ps-1 pe-2.5 text-label text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)]"

function Initial({ name }: { name: string }) {
  return (
    <span aria-hidden="true" className="grid size-8 place-items-center rounded-full bg-primary-container font-display text-label text-primary">
      {name.trim().charAt(0).toUpperCase()}
    </span>
  )
}

/**
 * The parent child switcher (mock pa.js `kid`): an initial and the child's name.
 * Only on a child route. With one child it is a plain name pill, not a control;
 * with two or more a native select sits over the pill, so it is keyboard- and
 * screen-reader-complete and keeps the old switcher's tails (switchChildPath).
 */
export function ChildSwitcher({ className }: { className?: string }) {
  const { childId } = useParams<{ childId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { data } = useChildren()
  const children = data?.children ?? []
  const current = children.find((c) => c.childId === childId)
  if (!childId || !current) return null
  if (children.length < 2) {
    return (
      <span className={cn(PILL, className)}>
        <Initial name={current.displayName} />
        <span className="truncate">{current.displayName}</span>
      </span>
    )
  }
  return (
    <span className={cn(PILL, "cursor-pointer focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-primary", className)}>
      <Initial name={current.displayName} />
      <span aria-hidden="true" className="truncate">
        {current.displayName}
      </span>
      <CaretDown size={12} weight="bold" aria-hidden="true" />
      <select
        aria-label="Choose which child to view"
        value={childId}
        onChange={(event) => navigate(switchChildPath(location.pathname, event.target.value))}
        className="absolute inset-0 cursor-pointer appearance-none rounded-full opacity-0"
      >
        {children.map((child) => (
          <option key={child.childId} value={child.childId}>
            {child.displayName}
          </option>
        ))}
      </select>
    </span>
  )
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run tests/unit/redesign/parentShellModel.test.ts tests/unit/hallmarkStamp.test.ts tests/unit/contrastRules.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(web): parent shell model and child switcher" -- web/src/portals/parent/shellModel.ts web/src/portals/parent/ChildSwitcher.tsx web/tests/unit/redesign/parentShellModel.test.ts
```

---

## Task 12: ParentShell on PortalShell, Topics route

**Agent:** designer.

**Files:**
- Create: `web/src/portals/parent/shell.tsx`
- Modify: `web/src/portals/parent/index.tsx` (delete `ChildSwitcher`, `ParentTrail`, `UnreadNotificationsBadge`, `Header`, `ParentLayout` and their now-unused imports; `element: <ParentShell />`; add the `topics` route)
- Modify: `web/src/components/shell/PortalShell.tsx:38` (`portal: "student" | "teacher" | "parent"`)
- Modify: `web/src/components/shell/ShellSidebar.tsx` (optional `lead` slot)
- Modify source-scanning tests whose layout lists named `src/portals/parent/index.tsx` (the parent layout is now `PortalShell`, as student and teacher already are): `tests/unit/capabilityWiring.test.ts:71`, `brandLockup.test.ts:25`, `offlineBanner.test.ts:29`, `outletBoundary.test.ts:49`, `screenEntrance.test.ts:71`, `nativeMechanics.test.ts:327`. Remove that one entry from each list; add `// The parent layout is components/shell/PortalShell.tsx too (F1).` beside the existing student/teacher note.
- Modify: `web/e2e/parent-journey.spec.ts` only if a step depends on the old header (see Step 4).
- Test: `web/tests/unit/redesign/parentShell.test.ts`

**Interfaces:**
- Consumes: Task 11 model and `ChildSwitcher`; `PortalShell`, `ShellUserBlock`, `profileName`; `staffDestinationFor`, `PARENT_INBOX_EMPTY`, `STAFF_INBOX_ERROR`, `unreadBadgeLabel`; `useNotificationCounts`, `useProfile`, `useChildren`, `useCachedChildSubject`.
- Produces: `ParentShell()`; route `children/:childId/topics` rendering `Weaknesses` until L11 replaces it. `ShellSidebarProps.lead?: ReactNode`.

- [ ] **Step 1: Write the failing test**

`web/tests/unit/redesign/parentShell.test.ts`:

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { parentRoute } from "@/portals/parent"

const SRC = join(fileURLToPath(new URL("../../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")

describe("parent portal uses the shared shell", () => {
  it("the layout element is ParentShell, built on PortalShell", () => {
    expect(read("portals/parent/index.tsx")).toContain("element: <ParentShell />")
    const shell = read("portals/parent/shell.tsx")
    expect(shell).toContain('<PortalShell')
    expect(shell).toContain('portal="parent"')
    expect(shell).toContain("lead: <ChildSwitcher />")
    expect(shell).toContain('<ChildSwitcher className="shell-lg:hidden" />')
  })
  it("the old bespoke header is gone", () => {
    const index = read("portals/parent/index.tsx")
    for (const gone of ["function Header", "function ParentTrail", "function ChildSwitcher", "function ParentLayout"]) expect(index).not.toContain(gone)
  })
  it("mounts a Topics route that still shows Weaknesses, and keeps the old path", () => {
    const paths = (parentRoute.children ?? []).map((r) => r.path)
    expect(paths).toContain("children/:childId/topics")
    expect(paths).toContain("children/:childId/weaknesses")
    expect(paths.at(-1)).toBe("*")
  })
  it("the account menu links the Emails settings screen", () => {
    expect(read("portals/parent/shell.tsx")).toMatch(/\{ id: "emails", label: "Emails", to: "\/parent\/emails"/)
  })
  it("the shell hides its own offline banner on immersive routes", () => {
    expect(read("components/shell/PortalShell.tsx")).toMatch(/\{immersive \? null : \(\s*<OfflineBanner/)
  })
  it("ShellSidebar renders a lead slot under the wordmark", () => {
    const sidebar = read("components/shell/ShellSidebar.tsx")
    expect(sidebar).toMatch(/lead\?: ReactNode/)
    expect(sidebar.indexOf("{lead ?")).toBeLessThan(sidebar.indexOf("<ShellNavList"))
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/unit/redesign/parentShell.test.ts`
Expected: FAIL (`shell.tsx` missing).

- [ ] **Step 3: Implement**

`ShellSidebar.tsx`: add to `ShellSidebarProps`:

```ts
  /** Under the wordmark, above the nav list: the parent child switcher (mock pa.js rail2 .kid). */
  lead?: ReactNode
```

destructure `lead`, and render between the wordmark row and `<ShellNavList items={items} />`:

```tsx
      {lead ? <div className="flex px-0.5">{lead}</div> : null}
```

`PortalShell.tsx:38`: `portal: "student" | "teacher" | "parent"`; update the doc comment to "every student, teacher and parent page". In the same file, the offline banner skips immersive routes (`handle: { immersive: true }`, e.g. the practice run, which shows its own offline strip per L3), so two banners never show at once:

```tsx
          {immersive ? null : (
            <OfflineBanner
              onRetry={() =>
                void queryClient.refetchQueries({ type: "active", predicate: (query) => query.state.status === "error" })
              }
            />
          )}
```

`offlineBanner.test.ts` still finds `<OfflineBanner` inside `<main>`; run it in Step 4.

`web/src/portals/parent/shell.tsx`:

```tsx
/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useState } from "react"
import { useLocation, useParams } from "react-router-dom"
import { ChatCircleText, EnvelopeSimple, Gear, GraduationCap, House, TextAlignLeft, User, Users, Warning } from "@phosphor-icons/react"
import type { AccountLink } from "@/components/shell/AccountPanel"
import { ShellIcon } from "@/components/shell/icons"
import type { NotificationsPanelProps } from "@/components/shell/NotificationsPanel"
import { PortalShell } from "@/components/shell/PortalShell"
import { isTabRoot, titleLevelFor } from "@/components/shell/largeTitle"
import { profileName } from "@/components/shell/ShellAvatar"
import { ShellUserBlock } from "@/components/shell/ShellSidebar"
import type { NavShellItem } from "@/components/ui/nav-shells"
import { useProfile } from "@/lib/hooks/useMeApi"
import { useNotificationCounts } from "@/lib/hooks/useNotificationApi"
import { useCachedChildSubject, useChildren } from "@/lib/hooks/useParentApi"
import { PARENT_INBOX_EMPTY, STAFF_INBOX_ERROR, staffDestinationFor, unreadBadgeLabel } from "@/lib/staffInbox"
import { ChildSwitcher } from "./ChildSwitcher"
import { type ParentTabId, parentPageTitle, parentShellTrail, parentTabs, resolveChildId, topicsActive } from "./shellModel"

const SETTINGS_TO = "/settings/devices"
const INBOX_TO = "/parent/notifications"

const TAB_ICON: Record<ParentTabId, typeof House> = {
  overview: House,
  topics: TextAlignLeft,
  inbox: ChatCircleText,
  tutoring: User,
}

const PARENT_NOTIFICATIONS_PANEL: Omit<NotificationsPanelProps, "unread" | "triggerClassName"> = {
  destinationFor: (notification) => staffDestinationFor("parent", notification),
  iconFor: (type) => (type === "at_risk_alert" ? <Warning size={18} aria-hidden="true" /> : <ShellIcon name="bell" />),
  inboxTo: INBOX_TO,
  footerLinks: [{ to: INBOX_TO, label: "All notifications" }],
  emptyMessage: `${PARENT_INBOX_EMPTY.heading}. ${PARENT_INBOX_EMPTY.body}`,
  errorHeading: STAFF_INBOX_ERROR.heading,
}

const PARENT_ACCOUNT_LINKS: readonly AccountLink[] = [
  // The Emails settings screen (mock pa.js FM): weekly summaries per subject and right-away alerts. L11 mounts /parent/emails.
  { id: "emails", label: "Emails", to: "/parent/emails", icon: <EnvelopeSimple size={18} aria-hidden="true" /> },
  { id: "settings", label: "Settings", to: SETTINGS_TO, icon: <Gear size={18} aria-hidden="true" /> },
]

/**
 * The parent portal in the shared shell (F1; approved parent mock SB, pa.js):
 * a child switcher and four tabs (Overview, Topics, Inbox, Tutoring), the
 * switcher in the rail on desktop and in the top bar below it. No Binny.
 * The shell appends More, which holds Tutors and, with 2+ children, Your children.
 */
export function ParentShell() {
  const location = useLocation()
  const { childId: paramChild, code } = useParams<{ childId?: string; code?: string }>()
  const { data } = useChildren()
  const profile = useProfile()
  const unread = unreadBadgeLabel(useNotificationCounts().data)
  const children = data?.children ?? []
  const [lastChild, setLastChild] = useState<string | null>(null)
  useEffect(() => {
    if (paramChild) setLastChild(paramChild)
  }, [paramChild])
  const childId = resolveChildId(paramChild ?? null, children.map((c) => c.childId), lastChild)
  const subject = useCachedChildSubject(paramChild ?? "", code ?? "")
  const subjectLabel = subject?.subjectName ?? code ?? null
  const path = location.pathname
  const tabs = parentTabs(childId)
  const trail = parentShellTrail(path, { childId: paramChild ?? null, hasChildList: children.length > 1, subjectLabel })
  const titleLevel = titleLevelFor(trail, isTabRoot(path, tabs.map((t) => t.to)))

  const tabItems: NavShellItem[] = tabs.map((tab) => {
    const Glyph = TAB_ICON[tab.id]
    return {
      id: tab.id,
      to: tab.to,
      end: tab.end,
      label: tab.label,
      icon: <Glyph size={22} aria-hidden="true" />,
      activeIcon: <Glyph size={22} weight="fill" aria-hidden="true" />,
      badge: tab.id === "inbox" && unread ? unread : undefined,
      active: tab.id === "topics" && topicsActive(path) ? true : undefined,
    }
  })
  const sidebarItems: NavShellItem[] = [
    ...tabItems.map((item) => ({ ...item, icon: item.icon, activeIcon: undefined })),
    { id: "tutors", to: "/parent/tutors", label: "Tutors", icon: <GraduationCap size={18} aria-hidden="true" /> },
    ...(children.length > 1
      ? [{ id: "children", to: "/parent", end: true, label: "Your children", icon: <Users size={18} aria-hidden="true" /> }]
      : []),
  ]

  return (
    <PortalShell
      portal="parent"
      drawerTitle="Lemely"
      pending={false}
      sidebar={{
        navLabel: "Main",
        homeTo: "/parent",
        homeLabel: "Lemely, your children",
        items: sidebarItems,
        lead: <ChildSwitcher />,
        user: profile.data ? (
          <ShellUserBlock name={profileName(profile.data)} avatarUrl={profile.data.avatarUrl} detail={null} />
        ) : (
          <p className="px-0.5 text-body-sm text-on-surface-variant">{profile.isPending ? "Loading…" : "Signed in"}</p>
        ),
      }}
      topBar={{
        title: parentPageTitle(path, subjectLabel),
        trail,
        titleLevel,
        backFallback: childId ? tabs[0].to : "/parent",
        navLabel: "Open parent navigation",
        actions: <ChildSwitcher className="shell-lg:hidden" />,
        notifications: PARENT_NOTIFICATIONS_PANEL,
        settingsTo: SETTINGS_TO,
        account: { links: PARENT_ACCOUNT_LINKS, detail: null },
      }}
      bottomTabs={tabItems}
    />
  )
}
```

Check `useCachedChildSubject`'s return field name against `web/src/lib/hooks/useParentApi.ts` (the old `ParentTrail` read `subject?.subjectName`; keep whatever that reads). `ShellUserBlock`'s sidebar row icons are 18px in the rail; the tab items' 22px glyphs are fine there because `ShellNavList` sizes its own icon slot. If it does not, map sidebar icons to 18px with the same `Glyph`.

`web/src/portals/parent/index.tsx`:
- Remove `ChildSwitcher`, `ParentTrail`, `UnreadNotificationsBadge`, `Header`, `ParentLayout` and the long header comment block, and every import only they used (`Link`, `useLocation`, `useNavigate`, `useParams`, `useQueryClient`, `Bell`, `Gear`, `GraduationCap`, `SignOut`, `useAuth`, `useCachedChildSubject`, `useChildren`, `BrandLockup`, `OfflineBanner`, `Select`, `VerifyEmailBanner`, `BadgeSync`, `RouteSkeleton`, `ScreenOutlet`, `Breadcrumbs`, `Crumb`, `Chip`, `useNotificationCounts`, `unreadBadgeLabel`, `ErrorBoundary`, `portalErrorFallback`, `SkipLink`, `MAIN_CONTENT_ID`, `Suspense`).
- Add `import { ParentShell } from "./shell"` and set `element: <ParentShell />`.
- Insert after the `weaknesses` route:

```tsx
    // F1: the Topics tab. Shows the existing Weaknesses screen until L11 replaces it.
    {
      path: "children/:childId/topics",
      element: <Weaknesses />,
      handle: { title: "Topics to work on", skeleton: "page-header" },
    },
```

- Keep the file's Hallmark stamp, re-derived.

- [ ] **Step 4: Run every test that scans the parent layout, then the e2e journey**

Run: `cd web && npx vitest run tests/unit/redesign/parentShell.test.ts tests/unit/redesign/parentShellModel.test.ts tests/unit/capabilityWiring.test.ts tests/unit/brandLockup.test.ts tests/unit/offlineBanner.test.ts tests/unit/outletBoundary.test.ts tests/unit/screenEntrance.test.ts tests/unit/nativeMechanics.test.ts tests/unit/routeSkeleton.test.ts tests/unit/notFoundFallback.test.ts tests/unit/rtlSafety.test.ts tests/unit/utilityExistence.test.ts tests/unit/hallmarkStamp.test.ts tests/unit/staffInbox.test.ts tests/unit/parentTutoring.test.ts tests/unit/parentOutcome.test.ts && npm run lint && npm run typecheck && npm run check:copy`
Expected: PASS.

Then, with the local stack up: `cd web && npx playwright test e2e/parent-journey.spec.ts e2e/tutoring-parent.spec.ts e2e/staff-inbox.spec.ts`. Expected: PASS. The journey reads page headings and in-page links, which this task does not change. If a step clicked the old header (`Notifications`, `Tutors`, `Sign out` by link name), point it at the shell: the bell button "Notifications", the "Tutors" sidebar or More item, the account panel's "Sign out".

- [ ] **Step 5: Look at it, then commit**

`npm run dev`, sign in as the seeded parent: at 390 the tab bar shows Overview, Topics, Inbox, Tutoring, More with the child pill in the top bar; Topics opens `/parent/children/<id>/topics` showing the Weaknesses screen; More lists Tutors. At 1280 the rail shows the wordmark, the child pill, then the four items and Tutors. With a second linked child (any dev seed with two), the pill switches and keeps the tail. Then:

```bash
git commit -S -m "feat(web): parent portal on the shared shell with child switcher and four tabs" -- web/src/portals/parent/shell.tsx web/src/portals/parent/index.tsx web/src/components/shell/PortalShell.tsx web/src/components/shell/ShellSidebar.tsx web/tests/unit/redesign/parentShell.test.ts web/tests/unit/capabilityWiring.test.ts web/tests/unit/brandLockup.test.ts web/tests/unit/offlineBanner.test.ts web/tests/unit/outletBoundary.test.ts web/tests/unit/screenEntrance.test.ts web/tests/unit/nativeMechanics.test.ts
```

(Add `web/e2e/parent-journey.spec.ts` to the path list only if Step 4 changed it.) No drift scene covers the parent portal.

---

## Task 13: Kit gallery preview and the shell happy path

**Agent:** designer (gallery), test-engineer (e2e).

**Files:**
- Create: `web/dev-previews/redesign-kit.html`, `web/dev-previews/redesign-kit/main.tsx`, `web/dev-previews/redesign-kit/Gallery.tsx`, `web/e2e/redesign-shell.spec.ts`
- Modify: `web/vite.preview.config.ts` (one `rollupOptions.input` entry)

**Interfaces:**
- Consumes: every kit export; `readSeed`, `injectSession` (`web/e2e/seed.ts`), `watchConsole` (`web/e2e/console-errors.ts`).

- [ ] **Step 1: Write the Playwright happy path**

`web/e2e/redesign-shell.spec.ts`:

```ts
import { expect, test } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

test.describe("F1 shell additions", () => {
  test("student phone: Scan sits in the centre of the tab bar and opens the scan screen", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const errors = watchConsole(page)
    const student = readSeed().students.correctedPaper
    await page.goto("/login")
    await page.getByLabel("Email").fill(student.email)
    await page.getByLabel("Password").fill(student.password)
    await page.getByRole("button", { name: /sign in/i }).click()
    await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })
    const nav = page.getByRole("navigation", { name: "Primary" })
    const tabs = nav.locator(":scope > *")
    await expect(tabs).toHaveCount(5)
    for (const [i, name] of ["Home", "Practice", "Scan a paper", "Subjects", "Me"].entries()) await expect(tabs.nth(i)).toHaveAccessibleName(name)
    // Subjects opens the sheet with the subject tree and the More group.
    await nav.getByRole("button", { name: "Subjects" }).click()
    await expect(page.getByRole("dialog").getByRole("link", { name: "Your classes" })).toBeVisible()
    await page.keyboard.press("Escape")
    // Practice opens the current practice entry and stays lit.
    await nav.getByRole("link", { name: "Practice", exact: true }).click()
    await expect(page).toHaveURL(/\/student\/practice\/[^/]+$/, { timeout: 15_000 })
    await expect(nav.getByRole("link", { name: "Practice", exact: true })).toHaveAttribute("aria-current", "page")
    await tabs.nth(2).click()
    await expect(page).toHaveURL(/\/student\/correct$/)
    expect(errors).toEqual([])
  })

  test("student desktop: the rail is Home, Practice, Me, Subjects, More, and ends with Scan a paper", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    const student = readSeed().students.correctedPaper
    await page.goto("/login")
    await page.getByLabel("Email").fill(student.email)
    await page.getByLabel("Password").fill(student.password)
    await page.getByRole("button", { name: /sign in/i }).click()
    await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })
    const rail = page.getByRole("navigation", { name: "Main" })
    for (const name of ["Home", "Practice", "Me", "Your classes", "Scan a paper"]) await expect(rail.getByRole("link", { name, exact: true })).toBeVisible()
  })

  test("parent phone: four tabs plus More, Topics shows the weak topics screen", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const errors = watchConsole(page)
    const seed = readSeed()
    const child = seed.students.declining
    await injectSession(page, { accessToken: seed.parent.accessToken, userId: seed.parent.userId, role: "parent" })
    await page.goto("/parent")
    await expect(page).toHaveURL(new RegExp(`/parent/children/${child.userId}$`), { timeout: 15_000 })
    const nav = page.getByRole("navigation", { name: "Primary" })
    for (const name of ["Overview", "Topics", "Inbox", "Tutoring"]) await expect(nav.getByRole("link", { name, exact: true })).toBeVisible()
    await expect(nav.getByRole("button", { name: "More" })).toBeVisible()
    await expect(page.getByText(child.displayName).first()).toBeVisible()
    await nav.getByRole("link", { name: "Topics", exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/parent/children/${child.userId}/topics$`))
    await expect(page.getByText("What to work on next")).toBeVisible({ timeout: 15_000 })
    expect(errors).toEqual([])
  })

  test("parent desktop: the child switcher sits in the rail", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    const seed = readSeed()
    await injectSession(page, { accessToken: seed.parent.accessToken, userId: seed.parent.userId, role: "parent" })
    await page.goto("/parent")
    const rail = page.getByRole("navigation", { name: "Main" })
    await expect(rail.getByText(seed.students.declining.displayName)).toBeVisible({ timeout: 15_000 })
    await expect(rail.getByRole("link", { name: "Tutors" })).toBeVisible()
  })
})
```

- [ ] **Step 2: Run it**

Run: `cd web && npx playwright test e2e/redesign-shell.spec.ts`
Expected: PASS against the Task 10 and 12 code. If it fails, fix the shell, not the test, unless the selector is wrong.

- [ ] **Step 3: Build the kit gallery**

`web/dev-previews/redesign-kit.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="robots" content="noindex, nofollow" />
    <title>Redesign kit</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="./redesign-kit/main.tsx"></script>
  </body>
</html>
```

`web/dev-previews/redesign-kit/main.tsx`:

```tsx
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { MemoryRouter } from "react-router-dom"
import "../../src/index.css"
import { blockApiFetch } from "../harness"
import { Gallery } from "./Gallery"

blockApiFetch()

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MemoryRouter>
      <Gallery />
    </MemoryRouter>
  </StrictMode>,
)
```

`web/dev-previews/redesign-kit/Gallery.tsx`. One section per frame in the frame-to-state table, in a 390px column and a full-width column, light and dark via `?theme=dark` (set `document.documentElement.dataset.theme`):

```tsx
import type { ReactNode } from "react"
import { Cards, Exam, NotePencil, Target } from "@phosphor-icons/react"
import {
  Binny, BinnyLine, ComboChip, CountdownPill, GhostRows, GoldRing, H2Row, HairRow, HairRows, KeyRing,
  LevelBar, RankRow, StepsPath, Tile, TopicChips, Walkthrough, type BinnyMood,
} from "@/components/redesign"
import { Switch } from "@/components/ui/switch"

if (new URLSearchParams(location.search).get("theme") === "dark") document.documentElement.dataset.theme = "dark"

const NOW = new Date(2026, 10, 15)
const MOODS: BinnyMood[] = ["happy", "wink", "open", "thinking", "sad"]
const P4 = [
  { id: "a", label: "Oct", grade: "C", pct: 56, caption: "45/80" },
  { id: "b", label: "Jan", grade: "B", pct: 60, caption: "48/80" },
  { id: "c", label: "Feb", grade: "B", pct: 63, caption: "50/80" },
  { id: "d", label: "Apr", grade: "A", pct: 76, caption: "61/80" },
]
const TOPICS = [
  { topic: "Vectors", state: "work" as const, pct: 41 },
  { topic: "Algebra", state: "work" as const, pct: 58 },
  { topic: "Trigonometry", state: "getting" as const, pct: 62 },
  { topic: "Mensuration", state: "getting" as const, pct: 69 },
  { topic: "Functions", state: "getting" as const, pct: 71 },
  { topic: "Statistics", state: "getting" as const, pct: 74 },
  { topic: "Coordinate geometry", state: "secure" as const, pct: 77 },
  { topic: "Geometry", state: "secure" as const, pct: 80 },
  { topic: "Number", state: "secure" as const, pct: 82 },
  { topic: "Probability", state: "secure" as const, pct: 88 },
]

function Frame({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="grid gap-3 border-b border-outline-variant py-8">
      <h2 className="text-display-xs text-on-surface">{`${id} · ${title}`}</h2>
      <div className="flex flex-wrap items-start gap-8">
        <div className="grid w-[390px] gap-4 bg-surface p-4">{children}</div>
        <div className="grid min-w-0 flex-1 gap-4 bg-surface p-6">{children}</div>
      </div>
    </section>
  )
}

export function Gallery() {
  return (
    <main className="bg-surface-container px-6 text-on-surface">
      <Frame id="binny" title="moods (h.js BIN), idle">
        <div className="flex flex-wrap gap-4">{MOODS.map((m) => <Binny key={m} mood={m} size={96} />)}</div>
      </Frame>
      <Frame id="binny-motion" title="hop, pop, roam, none">
        <div className="flex flex-wrap items-end gap-6">
          <Binny mood="happy" motion="hop" />
          <Binny mood="happy" motion="pop" />
          <Binny mood="happy" motion="roam" />
          <Binny mood="open" motion="none" />
          <Binny mood="happy" size={40} headCrop />
        </div>
      </Frame>
      <Frame id="say2" title="BinnyLine (sjf.js say)">
        <BinnyLine mood="happy" line="7 marks to A*" />
      </Frame>
      <Frame id="ring4" title="GoldRing and KeyRing">
        <div className="flex items-center gap-6">
          <GoldRing parts={[0, 0, 0]} />
          <GoldRing parts={[1, 0.5, 0]} />
          <GoldRing parts={[1, 1, 1]} size={60} center="3/3" />
          <KeyRing value={0.48} tone="gold" center="7" label="Level 7" />
          <KeyRing value={0.62} tone="warn" center="62%" label="Confidence 62%" />
          <KeyRing value={0} tone="neutral" center="–" label="No score yet" />
        </div>
      </Frame>
      <Frame id="F_P" title="StepsPath full">
        <StepsPath papers={P4} goal="A*" goalPct={85} goalCaption="68/80 · A* line" goalNote="7 to go" onSelect={() => {}} />
      </Frame>
      <Frame id="S_P" title="StepsPath sparse">
        <StepsPath papers={P4.slice(3)} goal="A*" goalPct={85} goalCaption="68/80 · A* line" goalNote="7 to go" ghosts={3} />
      </Frame>
      <Frame id="Z_P" title="StepsPath first run">
        <StepsPath papers={[]} goal="A*" ghosts={4} />
      </Frame>
      <Frame id="rows" title="H2Row, HairRows">
        <H2Row title="More marks to win" link={{ label: "All topics", to: "/" }} />
        <HairRows aria-label="Marks to win">
          <HairRow title="Algebra" sub="Practise · 10 min" trailing={<b>+7</b>} to="/" />
          <HairRow title="Trigonometry" sub="Practise · 10 min" trailing={<b>+5</b>} to="/" />
          <HairRow title="Mensuration" sub="Practise · 10 min" trailing={<b>+4</b>} onClick={() => {}} selected />
        </HairRows>
      </Frame>
      <Frame id="SB" title="RankRow with bars, selected (pa.js)">
        <HairRows aria-label="Topics costing marks">
          <RankRow rank={1} title="Vectors" sub="Practised twice this week" marksLost={9} trend="better" assigned bar={1} />
          <RankRow rank={2} title="Algebra" sub="Nothing yet" marksLost={7} trend="worse" bar={0.78} selected onClick={() => {}} />
          <RankRow rank={3} title="Waves" sub="Flashcards" marksLost={4} trend="same" bar={0.44} />
        </HairRows>
      </Frame>
      <Frame id="tmap" title="TopicChips folded and unfolded">
        <TopicChips topics={TOPICS} foldSecure onSelect={() => {}} />
        <TopicChips topics={TOPICS} />
      </Frame>
      <Frame id="CF" title="Tiles (ph.js gridC) and the homework row">
        <Tile icon={NotePencil} title="Homework: Trigonometry" status="Due Friday · 12 questions" tone="tide" big onClick={() => {}} />
        <div className="grid grid-cols-2 gap-2.5">
          <Tile icon={Target} title="Practice set" status="Build your own · 10 min" tone="tide" to="/" />
          <Tile icon={Cards} title="Flashcards" status={<><b>26</b> due today</>} tone="violet" to="/" />
          <Tile icon={Exam} title="Past papers" status="Print or do timed" tone="mint" to="/" />
          <Tile icon={Target} title="Placement test" status="Find your level · 10 min" tone="gold" disabled />
        </div>
      </Frame>
      <Frame id="walk2" title="Walkthrough and GhostRows">
        <Walkthrough steps={[{ title: "Scan a Maths paper", body: "Any past paper you have tried." }, { title: "Lemely marks it", body: "Every question, in about two minutes." }, { title: "Your path appears" }]} />
        <GhostRows rows={3} withLeading />
      </Frame>
      <Frame id="game" title="ComboChip, LevelBar, CountdownPill, Switch">
        <div className="flex flex-wrap items-center gap-3">
          <ComboChip count={1} />
          <ComboChip count={3} />
          <CountdownPill examDate="2027-05-14" now={NOW} to="/" />
          <CountdownPill examDate="2026-12-01" now={NOW} subject="Physics" />
        </div>
        <LevelBar level={7} xp={240} nextXp={500} />
        <Switch label="Weekly Maths email" defaultChecked layout="row" />
        <Switch label="Something to look at" layout="row" />
      </Frame>
    </main>
  )
}
```

`web/vite.preview.config.ts`, add to `rollupOptions.input`:

```ts
        "redesign-kit": previewEntry("redesign-kit"),
```

- [ ] **Step 4: Verify the gallery builds and renders**

Run: `cd web && npm run build:kit && npm run typecheck`
Expected: build succeeds, `dist-previews/redesign-kit.html` exists. Then `npm run preview:kit` and open `http://localhost:5199/redesign-kit.html` (and `?theme=dark`): every frame renders with no console error, and with "Reduce motion" on in the OS every Binny is still.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "test(web): redesign kit gallery and shell happy path" -- web/dev-previews/redesign-kit.html web/dev-previews/redesign-kit web/vite.preview.config.ts web/e2e/redesign-shell.spec.ts
```

---

## Task 14: Fidelity screenshots, drift fixes, polish

**Agent:** designer (with the impeccable skill).

**Files:**
- Modify: only files this plan owns or edited, for drift fixes.
- Modify: `web/scripts/drift/justifications.json` (the `difference` text of the scenes listed under Task 10; leave `approved` for the user)

- [ ] **Step 1: Serve the mocks, the kit and the app**

```bash
cd .impeccable/mocks && python3 -m http.server 8765 &          # mocks at http://localhost:8765/
cd web && npm run preview:kit &                                 # kit at http://localhost:5199/redesign-kit.html
cd web && npm run dev                                           # app at http://127.0.0.1:5173 (with the local stack)
```

Bound every wait with `timeout` and stop the servers at the end.

- [ ] **Step 2: Take the side-by-side pairs at 390 and 1280**

With the Playwright MCP (or chrome-devtools MCP), capture each pair at 390×844 and 1280×900 into `reports/redesign-f1/`:

| Pair | Mock | App |
|---|---|---|
| Student tab bar | `student-r2/home4.html` frame `P5` | `/student` at 390 |
| Student rail | `student-r2/home4.html` frame `D5` | `/student` at 1280 |
| Student tablet bar | `student-r2/final.html` frame `F_T` | `/student/subject/<code>` at 1024 |
| Parent phone shell | `student-r2/parent-final.html` frame `FA` | `/parent/children/<id>/subjects/<code>` at 390 |
| Parent rail | `parent-final.html` frame `FDK` | same at 1280 |
| Kit: Binny, rings, steps, rows, chips, tiles, walkthrough, combo, level, pill, switch | frames per the frame-to-state table | `redesign-kit.html#<frame id>` |

- [ ] **Step 3: Fix the drift**

For each pair, list visible differences. Fix spacing, size, colour and motion drift in the kit or shell. Write every intentional difference (shell-wins items, the skeleton pulse, the More tab) into the PR's "Changes from the mock" list. A layout, flow or content change goes to the user first.

- [ ] **Step 4: Re-run the drift harness for the student scenes**

Run the drift checks per `web/scripts/drift/harness.mjs` usage for the scenes in Task 10's table. For each scene that now differs, rewrite its `difference` text to the new facts (tab set "Home, Practice, Scan, Subjects, Me" with no More cell, the 56px Tide squircle, the outline "Scan a paper", the sidebar's Home/Practice/Me rows plus the More group). Do not set `approved: "yes"` yourself; list those scenes in the PR for the user.

- [ ] **Step 5: `/impeccable polish`, then commit**

Run `/impeccable polish` on `web/src/components/redesign/`, `web/src/portals/parent/{shell.tsx,ChildSwitcher.tsx}` and the student shell edits. Re-run `cd web && npx vitest run tests/unit/redesign && npm run lint && npm run typecheck && npm run check:copy`. Re-derive each touched file's Hallmark stamp. Commit with explicit paths:

```bash
git commit -S -m "fix(web): redesign kit and shell fidelity pass" -- <every file changed in this task>
```

---

## Task 15: Keep-list check, old code, push and PR

**Agent:** the lane coordinator.

- [ ] **Step 1: Keep-list.** Walk every box in the Keep-list with evidence (a test name, a screenshot, or a manual check), and tick it in the PR body.

- [ ] **Step 2: Old code is gone.** Run `cd web && grep -n "function Header\|function ParentTrail\|UnreadNotificationsBadge\|Upload a paper" src/portals/parent/index.tsx src/portals/student/shell.tsx` and expect no output. No other old code: the kit is new, and stepper, chip and skeleton are unchanged.

- [ ] **Step 3: Placeholder scan.** `grep -rn "TODO\|FIXME\|test.skip\|\.only(" web/src/components/redesign web/src/portals/parent/shell.tsx web/src/portals/parent/shellModel.ts web/src/portals/parent/ChildSwitcher.tsx web/tests/unit/redesign web/e2e/redesign-shell.spec.ts` returns nothing.

- [ ] **Step 4: Final gates on the committed tree.** Derived from `.github/workflows/ci.yml` (web job): run, in order, `cd web && npm run typecheck && npx vitest run tests/unit/redesign tests/unit/studentShell.test.ts tests/unit/navigation.test.ts tests/unit/native*.test.ts tests/unit/checkNativeInvariants.test.ts tests/unit/hallmarkStamp.test.ts tests/unit/design-tokens.test.ts tests/unit/darkConsumers.test.ts tests/unit/contrastRules.test.ts tests/unit/utilityExistence.test.ts tests/unit/rtlSafety.test.ts tests/unit/capabilityWiring.test.ts tests/unit/brandLockup.test.ts tests/unit/offlineBanner.test.ts tests/unit/outletBoundary.test.ts tests/unit/screenEntrance.test.ts tests/unit/routeSkeleton.test.ts tests/unit/notFoundFallback.test.ts && npm run lint && npm run check:copy && npm run build`, then `PYTHONPATH=$PWD pre-commit run --files <all changed files>`. All green on the tree you push. The full unit suite runs in CI.

- [ ] **Step 5: Push and open the PR to `develop`.**

```bash
git push -u origin redesign/f1-ui-kit
gh pr create --base develop --title "feat(web): redesign F1 UI kit and shell additions" --body-file <PR body>
```

The PR body holds: the kit inventory, the keep-list with ticks, "Changes from the mock", the drift scenes needing the user's approval, the fidelity pairs from `reports/redesign-f1/`, and the "Needs user decision" items below. Then the Opus review, fixes, a green CI run and the merge.

---

## Needs user decision

1. **Subjects tab's interim target.** The tab set follows the mock by ruling, but Subjects has no approved root screen. F1's interim: the Subjects tab opens the shell's navigation sheet, which holds the existing subject tree (each subject, with its Practice, Flashcards and Study plan rows) and the More group. *Recommendation:* keep this until a Subjects list screen is designed; alternatives are opening the first subject's page directly (fast for one-subject students, hides the others) or the Home grade floor (L1).
   Related: Practice's interim target is `/student/practice` → the first subject's practice page (`PracticeEntry`), until L4's hub replaces that route element. The Me tab uses a Phosphor person glyph where the mock draws the avatar initial; L1 may swap in the avatar.
2. **Parent More tab.** The mock shows exactly four tabs; the shell appends More. *Recommendation:* keep More. It holds Tutors and, for parents with 2+ children, Your children, which have no other phone entry.
3. **Topics path.** The master contract says `/parent/:childId/topics`; every live parent route is `/parent/children/:childId/...`. *Recommendation:* `/parent/children/:childId/topics` (F1 ships this), with `/weaknesses` kept as a working alias until L11 turns it into a redirect. L11's plan recommends the same.
4. **Walkthrough icons.** The contract makes `icon` required, but every mock numbers its tips. *Recommendation:* numbers by default, `icon` optional (a widening, contract-compatible); lanes omit it to match the mocks.
5. **"Level bar" meaning.** The contract's `LevelBar(level, xp, nextXp)` is the XP bar (home, Me). The practice result's Work on → Getting there → Secure bar is a different component. *Recommendation:* F1 ships the XP `LevelBar`; L3 builds its own mastery bar as its plan already says.
6. **Violet tile tint.** Flashcards' tile tint (hue 300) has no Abyss token, and tokens are frozen. *Recommendation:* accept the one scoped literal in `redesign.css` (`.rd-tile[data-tone="violet"]`, light and dark), or map violet to `sea` (secondary-container) if no literal is wanted.
7. **Parent page width.** Parent screens move from a 960px centred column into the shell's page well. *Recommendation:* accept; L11 restyles the subject and topics screens to the mock, and the remaining parent screens (ChildOverview, Children, Notifications, tutoring) get a follow-up.
8. **Skeleton shimmer.** The mock's skeletons sweep a gradient; DESIGN.md §9.2 bans animating anything but transform and opacity. *Recommendation:* keep the kit's pulse.
9. **Android raised tab size.** `--native-tab-emphasis-size` goes from 44px to 56px to match the mock's Scan squircle. It is a native-frame layout variable, not an Abyss token. *Recommendation:* accept.
10. **Single child.** The old header hid the switcher with one child. F1 shows a static name pill instead, so the parent always sees whose data this is. *Recommendation:* accept.
11. **Emails link before L11.** The parent account menu links `/parent/emails`, which L11 mounts. If F1 merges first, the link lands on the portal's not-found page until then. *Recommendation:* merge F1 first anyway (L11 is in wave 3 but may start early); if the gap is unwanted, L11's route can be cherry-picked as a stub that renders the existing notification settings.
12. **Subject dot colours.** DESIGN.md says subjects are not colour-coded, but the approved mocks draw a coloured dot per subject. `SubjectDot` maps subjects onto existing tokens (Maths grade-A green, Physics primary, Add Maths grade-D, others hashed), always beside the subject name. *Recommendation:* accept, as the mocks are approved.

Dependencies beyond the master plan: F1 now owns the student tab list and sidebar rows (Practice tab, rail item, Practice-section rule for practice and flashcards). L4 no longer edits `STUDENT_BOTTOM_TABS` or adds a Practice nav item in `data.ts`; it replaces the `practice` route's element (`PracticeEntry`) with its hub. L1 owns Home doors to the More-group destinations and may rename the top bar title "Overview" to match the Home tab. L11 should build on the `children/:childId/topics` route and `ChildSwitcher` from F1, and owns turning `/weaknesses` into a redirect. L3 and L10 build their own mastery bar and count stepper; F1 does not export those.
