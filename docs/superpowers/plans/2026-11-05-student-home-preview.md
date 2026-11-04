# Student Home Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a static, live-editable dev preview of the three student home variants (A Today's page, B Exam runway, C Training log) on v5 tokens. It covers every state in the spec, and ends in an impeccable live session where the user picks a direction.

**Architecture:** The home's decision logic (next action, Binny mood, today list, streak strip) is written now as a pure TypeScript module in `web/src/portals/student/home/model.ts`. The later React port reuses it unchanged, and the preview imports it through the `@` alias. Each variant is one static HTML file whose markup is real and live-editable. A small controller reads the chosen demo state, runs the model, and sets `data-*` attributes on the root, and CSS uses those attributes to show the matching blocks. Binny is a React island that reuses the marketing `Binny` component.

**Tech Stack:** Vite (preview config `web/vite.preview.config.ts`), TypeScript, plain CSS with container queries, React 19 (Binny island only), Vitest (node environment), impeccable detector and live mode.

**Spec:** `docs/superpowers/specs/2026-11-05-student-home-design.md` (sections 3–7 and 9; section 9 steps 2–3 only).

## Global Constraints

- Visual authority: `DESIGN.md` on this branch (v5 Abyss). Use role tokens (`--md-*`, `--surface-*`, `--text-*`) and never raw colour values in variant CSS.
- Bricolage Grotesque only at 28px or larger, weight 800, tracking −0.03em to −0.05em.
- Marks, codes, percentages, dates and XP numbers in JetBrains Mono with tabular figures.
- Gold only for XP, streak and reward. Crimson only for lost marks and genuine errors; no crimson in any normal home state.
- Never Abyss on a dark surface: on dark the accent is Tide.
- Every grade chip shows its letter; A* is always green.
- Binny: at most one visible per screen (none in loading and error), never next to the logo.
- Logical CSS properties only (`margin-inline-start`, `padding-inline`, `inset-inline-end`, `text-align: start`).
- Tap targets at least 44px under `@media (pointer: coarse)`.
- All motion off under `prefers-reduced-motion: reduce` and under the preview's `data-motion="reduce"` toggle.
- Never write "cram", "hack", "easy A" or "guaranteed grade".
- No `border-left`/`border-right` over 1px as a coloured stripe, and no gradient text.
- Demo data is labelled "Demo data" on every preview page and never imported by `web/src/` code.
- Commits: signed (`git commit -S`), conventional with scope, path-scoped (`git commit -S -m "..." -- <paths>`). Before each commit run `env PATH="/home/sico/Code/Lemely/.venv/bin:/usr/local/bin:/usr/bin:/bin" /home/sico/Code/Lemely/.venv/bin/pre-commit run --files <paths>` from the worktree root and fix failures. Do not push.
- Tests: run only the touched test files (`npx vitest run <file>`), never the full suite.
- All `web/` commands run from `/home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web`.

## File Structure

| File | Responsibility |
|---|---|
| `web/src/portals/student/home/model.ts` (create) | Pure home logic: types, `deriveNextAction`, `todayList`, `binnyMood`, `streakStrip`, `localISODate`. No React, no fetch. |
| `web/tests/unit/studentHomeModel.test.ts` (create) | Truth tables for the model. |
| `web/dev-previews/student-home/tokens.css` (create) | v5 tokens, light on `:root`, dark on `[data-theme="dark"]`. |
| `web/dev-previews/student-home/fixtures.ts` (create) | Demo `HomeFacts` for each state and the expected action and mood. |
| `web/tests/unit/studentHomeFixtures.test.ts` (create) | Proves each fixture drives the state it claims. |
| `web/dev-previews/student-home/controller.ts` (create) | Toolbar, URL params, runs the model, sets root `data-*`, mounts Binny. |
| `web/dev-previews/student-home/binny-island.tsx` (create) | Renders the marketing `Binny` with a v5 mood mapped to a marketing mood. |
| `web/dev-previews/student-home/shell.css` (create) | Preview toolbar, frame, state switching rules shared by all variants. |
| `web/dev-previews/student-home.html` (create) | Index page linking the three variants. |
| `web/dev-previews/student-home-a.html` + `student-home/variant-a.css` (create) | Variant A markup and styles. |
| `web/dev-previews/student-home-b.html` + `student-home/variant-b.css` (create) | Variant B markup and styles. |
| `web/dev-previews/student-home-c.html` + `student-home/variant-c.css` (create) | Variant C markup and styles. |
| `web/vite.preview.config.ts` (modify, `input` object) | Register the four new HTML entries. |

---

### Task 1: Home model (pure logic)

**Files:**
- Create: `web/src/portals/student/home/model.ts`
- Test: `web/tests/unit/studentHomeModel.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces (exact exports, used by Tasks 2–6 and the later React port):
  - types `UpcomingSession`, `HomeSubject`, `WeakTopic`, `LatestResult`, `XpDay`, `HomeFacts`, `NextAction`, `NextActionKind`, `BinnyMood`, `StreakDay`, `NextActionOptions`
  - `GRADE_ORDER: readonly ["U","E","D","C","B","A","A*"]`
  - `localISODate(d: Date): string`
  - `deriveNextAction(facts: HomeFacts, opts?: NextActionOptions): NextAction`
  - `todayList(facts: HomeFacts, max?: number): NextAction[]`
  - `binnyMood(facts: HomeFacts): BinnyMood`
  - `streakStrip(calendar: readonly XpDay[], now: Date): StreakDay[]`

- [ ] **Step 1: Write the failing test**

Create `web/tests/unit/studentHomeModel.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  binnyMood,
  deriveNextAction,
  localISODate,
  streakStrip,
  todayList,
  type HomeFacts,
} from "@/portals/student/home/model"

// 2026-11-05 10:00 local time. Every date below is local, so the tests do not
// depend on the machine's time zone.
const NOW = new Date(2026, 10, 5, 10, 0)
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3_600_000).toISOString()

function facts(over: Partial<HomeFacts> = {}): HomeFacts {
  return {
    now: NOW,
    activeUpload: null,
    subjects: [
      { code: "0580", papers: 14, grade: "A", previousGrade: "B", nextExamOn: "2027-05-12" },
      { code: "0625", papers: 2, grade: "C", previousGrade: "D", nextExamOn: "2027-05-04" },
    ],
    upcomingSessions: [],
    weakTopics: [
      { topic: "Vectors", subjectCode: "0580", acc: 63 },
      { topic: "Waves", subjectCode: "0625", acc: 54 },
    ],
    latestResult: null,
    calendar: [],
    ...over,
  }
}

const session = (id: string, code: string, day: string) => ({
  sessionId: id,
  subjectCode: code,
  title: `Session ${id}`,
  minutes: 20,
  scheduledFor: day,
})

describe("localISODate", () => {
  it("formats the local calendar date with zero padding", () => {
    expect(localISODate(new Date(2026, 0, 3, 23, 59))).toBe("2026-01-03")
  })
})

describe("deriveNextAction", () => {
  it("1. marking in progress wins over everything", () => {
    const a = deriveNextAction(
      facts({ activeUpload: { paperLabel: "0580/42" }, upcomingSessions: [session("s1", "0580", "2026-11-05")] }),
    )
    expect(a).toEqual({ kind: "marking", paperLabel: "0580/42", to: "/student/correct" })
  })

  it("2. a session due today is next", () => {
    const a = deriveNextAction(facts({ upcomingSessions: [session("s1", "0606", "2026-11-05")] }))
    expect(a.kind).toBe("session")
    expect(a.to).toBe("/student/plan/0606/session/s1")
  })

  it("2. an overdue session counts as due", () => {
    expect(deriveNextAction(facts({ upcomingSessions: [session("s0", "0580", "2026-11-01")] })).kind).toBe("session")
  })

  it("2. a session scheduled for tomorrow is not due", () => {
    expect(deriveNextAction(facts({ upcomingSessions: [session("s2", "0580", "2026-11-06")] })).kind).toBe("practice")
  })

  it("3. no papers means the first-paper action", () => {
    const a = deriveNextAction(facts({ subjects: [], weakTopics: [] }))
    expect(a).toEqual({ kind: "first-paper", to: "/student/correct" })
  })

  it("3. subjects with zero papers also mean the first-paper action", () => {
    const subjects = [{ code: "0580", papers: 0, grade: "U", previousGrade: null, nextExamOn: null }]
    expect(deriveNextAction(facts({ subjects })).kind).toBe("first-paper")
  })

  it("4. otherwise the weakest topic is practised", () => {
    const a = deriveNextAction(facts())
    expect(a.kind).toBe("practice")
    if (a.kind === "practice") expect(a.topic.topic).toBe("Waves")
    expect(a.to).toBe("/student/practice/0625")
  })

  it("5. with no weak topics the fallback is correct another paper", () => {
    expect(deriveNextAction(facts({ weakTopics: [] }))).toEqual({ kind: "correct", to: "/student/correct" })
  })

  it("preferClosestExam picks the due session for the subject with the closest exam", () => {
    const f = facts({
      upcomingSessions: [session("s1", "0580", "2026-11-05"), session("s2", "0625", "2026-11-05")],
    })
    const closest = deriveNextAction(f, { preferClosestExam: true })
    const plain = deriveNextAction(f)
    expect(closest.kind === "session" ? closest.session.sessionId : null).toBe("s2")
    expect(plain.kind === "session" ? plain.session.sessionId : null).toBe("s1")
  })

  it("preferClosestExam picks practice in the subject with the closest exam", () => {
    const f = facts({
      weakTopics: [
        { topic: "Vectors", subjectCode: "0580", acc: 40 },
        { topic: "Waves", subjectCode: "0625", acc: 54 },
      ],
    })
    const a = deriveNextAction(f, { preferClosestExam: true })
    expect(a.kind === "practice" && a.topic.topic).toBe("Waves")
  })
})

describe("todayList", () => {
  it("starts with the same action deriveNextAction returns", () => {
    const cases: HomeFacts[] = [
      facts(),
      facts({ activeUpload: { paperLabel: "0580/42" } }),
      facts({ upcomingSessions: [session("s1", "0580", "2026-11-05")] }),
      facts({ subjects: [], weakTopics: [] }),
      facts({ weakTopics: [] }),
    ]
    for (const f of cases) expect(todayList(f)[0]).toEqual(deriveNextAction(f))
  })

  it("caps the list at three items", () => {
    const f = facts({
      activeUpload: { paperLabel: "0580/42" },
      upcomingSessions: [session("s1", "0580", "2026-11-05"), session("s2", "0625", "2026-11-04")],
    })
    expect(todayList(f).map((a) => a.kind)).toEqual(["marking", "session", "session"])
  })

  it("lists session, practice, correct for a typical day", () => {
    const f = facts({ upcomingSessions: [session("s1", "0580", "2026-11-05")] })
    expect(todayList(f).map((a) => a.kind)).toEqual(["session", "practice", "correct"])
  })

  it("a new student gets only the first-paper action", () => {
    expect(todayList(facts({ subjects: [], weakTopics: [] })).map((a) => a.kind)).toEqual(["first-paper"])
  })

  it("never offers a first paper while one is being marked", () => {
    const f = facts({ subjects: [], weakTopics: [], activeUpload: { paperLabel: "0580/42" } })
    expect(todayList(f).map((a) => a.kind)).toEqual(["marking"])
  })
})

describe("binnyMood", () => {
  it("marking in progress", () => {
    expect(binnyMood(facts({ activeUpload: { paperLabel: "0580/42" } }))).toBe("marking")
  })

  it("grade improved: result in the last 24 h above the previous grade", () => {
    const latestResult = { subjectCode: "0580", grade: "A", recordedAt: hoursAgo(16) }
    expect(binnyMood(facts({ latestResult }))).toBe("grade-improved")
  })

  it("paper marked: result in the last 24 h, same grade as before", () => {
    const subjects = [{ code: "0580", papers: 14, grade: "A", previousGrade: "A", nextExamOn: null }]
    const latestResult = { subjectCode: "0580", grade: "A", recordedAt: hoursAgo(2) }
    expect(binnyMood(facts({ subjects, latestResult }))).toBe("paper-marked")
  })

  it("paper marked: first paper in a subject has no previous grade", () => {
    const subjects = [{ code: "0580", papers: 1, grade: "B", previousGrade: null, nextExamOn: null }]
    const latestResult = { subjectCode: "0580", grade: "B", recordedAt: hoursAgo(2) }
    expect(binnyMood(facts({ subjects, latestResult }))).toBe("paper-marked")
  })

  it("a result older than 24 h no longer counts", () => {
    const latestResult = { subjectCode: "0580", grade: "A", recordedAt: hoursAgo(25) }
    expect(binnyMood(facts({ latestResult }))).toBe("idle")
  })

  it("streak kept: XP earned today", () => {
    expect(binnyMood(facts({ calendar: [{ day: "2026-11-05", xp: 30 }] }))).toBe("streak-kept")
  })

  it("zero XP today is not a kept streak", () => {
    expect(binnyMood(facts({ calendar: [{ day: "2026-11-05", xp: 0 }] }))).toBe("idle")
  })

  it("idle otherwise", () => {
    expect(binnyMood(facts({ calendar: [{ day: "2026-11-04", xp: 30 }] }))).toBe("idle")
  })
})

describe("streakStrip", () => {
  it("returns the last 7 local days, oldest first, with today last", () => {
    const strip = streakStrip([{ day: "2026-11-05", xp: 20 }, { day: "2026-11-01", xp: 5 }], NOW)
    expect(strip.map((d) => d.day)).toEqual([
      "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
    ])
    expect(strip.map((d) => d.earned)).toEqual([false, false, true, false, false, false, true])
    expect(strip[6].isToday).toBe(true)
    expect(strip.filter((d) => d.isToday)).toHaveLength(1)
  })

  it("days missing from the calendar have zero XP", () => {
    expect(streakStrip([], NOW).every((d) => d.xp === 0 && !d.earned)).toBe(true)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run tests/unit/studentHomeModel.test.ts`
Expected: FAIL, `Failed to resolve import "@/portals/student/home/model"`.

- [ ] **Step 3: Write the implementation**

Create `web/src/portals/student/home/model.ts`:

```ts
/*
 * Student home decision logic (spec 2026-11-05-student-home-design.md §3–4).
 * Pure functions only: no React, no fetching, no clock reads (`now` is passed
 * in), so every branch is a unit test. The dev preview and the React home
 * both call these, so the preview cannot drift from the product.
 */

export const GRADE_ORDER = ["U", "E", "D", "C", "B", "A", "A*"] as const

export interface UpcomingSession {
  sessionId: string
  subjectCode: string
  title: string
  minutes: number
  /** ISO date, YYYY-MM-DD. */
  scheduledFor: string
}

export interface HomeSubject {
  code: string
  papers: number
  grade: string
  previousGrade: string | null
  /** ISO date, YYYY-MM-DD. */
  nextExamOn: string | null
}

export interface WeakTopic {
  topic: string
  subjectCode: string
  /** Accuracy as a whole percentage, 0–100. */
  acc: number
}

export interface LatestResult {
  subjectCode: string
  grade: string
  /** UTC ISO-8601 timestamp. */
  recordedAt: string
}

export interface XpDay {
  /** ISO date, YYYY-MM-DD. */
  day: string
  xp: number
}

export interface HomeFacts {
  now: Date
  activeUpload: { paperLabel: string } | null
  subjects: readonly HomeSubject[]
  upcomingSessions: readonly UpcomingSession[]
  weakTopics: readonly WeakTopic[]
  latestResult: LatestResult | null
  calendar: readonly XpDay[]
}

export type NextAction =
  | { kind: "marking"; paperLabel: string; to: string }
  | { kind: "session"; session: UpcomingSession; to: string }
  | { kind: "first-paper"; to: string }
  | { kind: "practice"; topic: WeakTopic; to: string }
  | { kind: "correct"; to: string }

export type NextActionKind = NextAction["kind"]

export type BinnyMood = "marking" | "grade-improved" | "paper-marked" | "streak-kept" | "idle"

export interface StreakDay {
  day: string
  xp: number
  earned: boolean
  isToday: boolean
}

export interface NextActionOptions {
  /** Variant B: among due sessions and weak topics, prefer the subject with the closest exam. */
  preferClosestExam?: boolean
}

const CORRECT_ROUTE = "/student/correct"
const DAY_MS = 86_400_000
const NO_EXAM = "9999-12-31"

export function localISODate(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${d.getFullYear()}-${m}-${day}`
}

function hasPapers(f: HomeFacts): boolean {
  return f.subjects.some((s) => s.papers > 0)
}

function dueSessions(f: HomeFacts): UpcomingSession[] {
  const today = localISODate(f.now)
  return f.upcomingSessions.filter((s) => s.scheduledFor <= today)
}

function weakestFirst(f: HomeFacts): WeakTopic[] {
  return [...f.weakTopics].sort((a, b) => a.acc - b.acc)
}

function examDate(f: HomeFacts, code: string): string {
  return f.subjects.find((s) => s.code === code)?.nextExamOn ?? NO_EXAM
}

/** Stable sort, so items for the same subject keep their order. */
function byClosestExam<T>(f: HomeFacts, items: T[], codeOf: (item: T) => string): T[] {
  return [...items].sort((a, b) => examDate(f, codeOf(a)).localeCompare(examDate(f, codeOf(b))))
}

const markingAction = (paperLabel: string): NextAction => ({ kind: "marking", paperLabel, to: CORRECT_ROUTE })
const sessionAction = (s: UpcomingSession): NextAction => ({
  kind: "session",
  session: s,
  to: `/student/plan/${s.subjectCode}/session/${s.sessionId}`,
})
const practiceAction = (t: WeakTopic): NextAction => ({ kind: "practice", topic: t, to: `/student/practice/${t.subjectCode}` })
const FIRST_PAPER: NextAction = { kind: "first-paper", to: CORRECT_ROUTE }
const CORRECT_ANOTHER: NextAction = { kind: "correct", to: CORRECT_ROUTE }

export function deriveNextAction(f: HomeFacts, opts: NextActionOptions = {}): NextAction {
  if (f.activeUpload) return markingAction(f.activeUpload.paperLabel)
  let due = dueSessions(f)
  if (opts.preferClosestExam) due = byClosestExam(f, due, (s) => s.subjectCode)
  if (due.length > 0) return sessionAction(due[0])
  if (!hasPapers(f)) return FIRST_PAPER
  let weak = weakestFirst(f)
  if (opts.preferClosestExam) weak = byClosestExam(f, weak, (t) => t.subjectCode)
  if (weak.length > 0) return practiceAction(weak[0])
  return CORRECT_ANOTHER
}

/** Variant C's "today" list. Its first item always equals `deriveNextAction(f)`. */
export function todayList(f: HomeFacts, max = 3): NextAction[] {
  const out: NextAction[] = []
  if (f.activeUpload) out.push(markingAction(f.activeUpload.paperLabel))
  out.push(...dueSessions(f).map(sessionAction))
  if (!hasPapers(f)) {
    if (!f.activeUpload) out.push(FIRST_PAPER)
    return out.slice(0, max)
  }
  const weakest = weakestFirst(f)[0]
  if (weakest) out.push(practiceAction(weakest))
  out.push(CORRECT_ANOTHER)
  return out.slice(0, max)
}

function gradeRank(grade: string): number {
  return (GRADE_ORDER as readonly string[]).indexOf(grade)
}

export function binnyMood(f: HomeFacts): BinnyMood {
  if (f.activeUpload) return "marking"
  const r = f.latestResult
  if (r && f.now.getTime() - Date.parse(r.recordedAt) < DAY_MS) {
    const previous = f.subjects.find((s) => s.code === r.subjectCode)?.previousGrade ?? null
    if (previous !== null && gradeRank(previous) >= 0 && gradeRank(r.grade) > gradeRank(previous)) {
      return "grade-improved"
    }
    return "paper-marked"
  }
  const today = localISODate(f.now)
  if (f.calendar.some((d) => d.day === today && d.xp > 0)) return "streak-kept"
  return "idle"
}

export function streakStrip(calendar: readonly XpDay[], now: Date): StreakDay[] {
  const xpByDay = new Map(calendar.map((d) => [d.day, d.xp]))
  const today = localISODate(now)
  return Array.from({ length: 7 }, (_, i) => {
    const day = localISODate(new Date(now.getFullYear(), now.getMonth(), now.getDate() - (6 - i)))
    const xp = xpByDay.get(day) ?? 0
    return { day, xp, earned: xp > 0, isToday: day === today }
  })
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run tests/unit/studentHomeModel.test.ts`
Expected: PASS, all tests green.

- [ ] **Step 5: Prove the tests can fail**

Temporarily change `s.scheduledFor <= today` to `s.scheduledFor < today` in `dueSessions`. Run the same command. Expected: FAIL in "2. a session due today is next". Revert the change and re-run: PASS.

- [ ] **Step 6: Typecheck and lint**

Run: `npm run typecheck && npx oxlint src/portals/student/home tests/unit/studentHomeModel.test.ts`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
env PATH="/home/sico/Code/Lemely/.venv/bin:/usr/local/bin:/usr/bin:/bin" /home/sico/Code/Lemely/.venv/bin/pre-commit run --files web/src/portals/student/home/model.ts web/tests/unit/studentHomeModel.test.ts
git add web/src/portals/student/home/model.ts web/tests/unit/studentHomeModel.test.ts
git commit -S -m "feat(student): add pure home model for next action, Binny mood and streak strip" -- web/src/portals/student/home/model.ts web/tests/unit/studentHomeModel.test.ts
```

---

### Task 2: Preview scaffold (tokens, fixtures, controller, Binny island, index)

**Files:**
- Create: `web/dev-previews/student-home/tokens.css`
- Create: `web/dev-previews/student-home/fixtures.ts`
- Create: `web/dev-previews/student-home/controller.ts`
- Create: `web/dev-previews/student-home/binny-island.tsx`
- Create: `web/dev-previews/student-home/shell.css`
- Create: `web/dev-previews/student-home.html`
- Modify: `web/vite.preview.config.ts` (the `input` object)
- Test: `web/tests/unit/studentHomeFixtures.test.ts`

**Interfaces:**
- Consumes: everything Task 1 exports.
- Produces:
  - `STATES: readonly StateId[]` and `type StateId = "populated" | "new" | "one-paper" | "marking" | "no-plan" | "no-exams" | "streak-zero" | "loading" | "error"`
  - `FIXTURES: Record<StateId, { facts: HomeFacts; expected: { action: NextActionKind; mood: BinnyMood } }>`
  - `mountHome(variant: "a" | "b" | "c"): void` in `controller.ts`. Each variant page calls it.
  - Root element contract (every variant page): `<main id="sh-root" class="sh-root">`. The controller sets these attributes on it:
    `data-variant` (`a|b|c`), `data-state` (a `StateId`), `data-action` (a `NextActionKind`), `data-today` (space-separated kinds from `todayList`, for example `"session practice correct"`), `data-mood` (a `BinnyMood`), `data-theme` (`light|dark`), `data-motion` (`full|reduce`), `data-width` (`desktop|mobile`), `data-exams` (`yes|no`).
  - Binny slots: any element with `data-binny`. The controller mounts one island per slot.
  - Toolbar contract: `<nav class="sh-toolbar" aria-label="Preview controls">` containing `<select data-control="state">`, `<select data-control="theme">`, `<select data-control="motion">`, `<select data-control="width">`, and links `a[data-variant-link="a|b|c"]`. The controller fills the options, mirrors them into the URL (`?state=&theme=&motion=&width=`) and keeps the query string on variant links.

- [ ] **Step 1: Write the failing fixtures test**

Create `web/tests/unit/studentHomeFixtures.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { binnyMood, deriveNextAction } from "@/portals/student/home/model"
import { FIXTURES, STATES } from "../../dev-previews/student-home/fixtures"

describe("student home preview fixtures", () => {
  it("covers every spec state", () => {
    expect([...STATES].sort()).toEqual(
      ["error", "loading", "marking", "new", "no-exams", "no-plan", "one-paper", "populated", "streak-zero"],
    )
  })

  for (const id of STATES) {
    it(`${id} drives the action and mood it claims`, () => {
      const { facts, expected } = FIXTURES[id]
      expect(deriveNextAction(facts).kind).toBe(expected.action)
      expect(binnyMood(facts)).toBe(expected.mood)
    })
  }

  it("no-exams has no exam dates and populated has all of them", () => {
    expect(FIXTURES["no-exams"].facts.subjects.every((s) => s.nextExamOn === null)).toBe(true)
    expect(FIXTURES.populated.facts.subjects.every((s) => s.nextExamOn !== null)).toBe(true)
  })

  it("streak-zero has no XP today or yesterday", () => {
    const cal = FIXTURES["streak-zero"].facts.calendar
    expect(cal.some((d) => (d.day === "2026-11-05" || d.day === "2026-11-04") && d.xp > 0)).toBe(false)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/unit/studentHomeFixtures.test.ts`
Expected: FAIL, cannot resolve `../../dev-previews/student-home/fixtures`.

- [ ] **Step 3: Write the fixtures**

Create `web/dev-previews/student-home/fixtures.ts`. The display copy in the HTML (Tasks 3–5) must match these values.

```ts
/*
 * Demo data for the student home preview. Not product data: every page that
 * uses it says "Demo data". Real CAIE subject codes, plausible paper labels.
 * "Today" is fixed at 2026-11-05 10:00 local so states never drift.
 */
import type { BinnyMood, HomeFacts, NextActionKind, XpDay } from "@/portals/student/home/model"

export const STATES = [
  "populated", "new", "one-paper", "marking", "no-plan", "no-exams", "streak-zero", "loading", "error",
] as const
export type StateId = (typeof STATES)[number]

export const NOW = new Date(2026, 10, 5, 10, 0)

/** Nine-day streak ending today. */
const NINE_DAYS: XpDay[] = [
  { day: "2026-10-28", xp: 40 }, { day: "2026-10-29", xp: 25 }, { day: "2026-10-30", xp: 60 },
  { day: "2026-10-31", xp: 20 }, { day: "2026-11-01", xp: 35 }, { day: "2026-11-02", xp: 50 },
  { day: "2026-11-03", xp: 30 }, { day: "2026-11-04", xp: 120 }, { day: "2026-11-05", xp: 25 },
]

const populated: HomeFacts = {
  now: NOW,
  activeUpload: null,
  subjects: [
    { code: "0580", papers: 14, grade: "A", previousGrade: "B", nextExamOn: "2027-05-12" },
    { code: "0606", papers: 6, grade: "B", previousGrade: "B", nextExamOn: "2027-05-18" },
    { code: "0625", papers: 2, grade: "C", previousGrade: "D", nextExamOn: "2027-05-04" },
  ],
  upcomingSessions: [
    { sessionId: "s1", subjectCode: "0606", title: "Quadratic inequalities", minutes: 25, scheduledFor: "2026-11-05" },
    { sessionId: "s2", subjectCode: "0580", title: "Vectors", minutes: 20, scheduledFor: "2026-11-06" },
  ],
  weakTopics: [
    { topic: "Waves", subjectCode: "0625", acc: 54 },
    { topic: "Quadratic inequalities", subjectCode: "0606", acc: 58 },
    { topic: "Vectors", subjectCode: "0580", acc: 63 },
    { topic: "Moments", subjectCode: "0625", acc: 66 },
  ],
  // Yesterday 18:00, 16 h before NOW: grade A, up from B.
  latestResult: { subjectCode: "0580", grade: "A", recordedAt: new Date(2026, 10, 4, 18, 0).toISOString() },
  calendar: NINE_DAYS,
}

type Fixture = { facts: HomeFacts; expected: { action: NextActionKind; mood: BinnyMood } }

export const FIXTURES: Record<StateId, Fixture> = {
  populated: { facts: populated, expected: { action: "session", mood: "grade-improved" } },
  new: {
    facts: { now: NOW, activeUpload: null, subjects: [], upcomingSessions: [], weakTopics: [], latestResult: null, calendar: [] },
    expected: { action: "first-paper", mood: "idle" },
  },
  "one-paper": {
    facts: {
      now: NOW,
      activeUpload: null,
      subjects: [{ code: "0580", papers: 1, grade: "B", previousGrade: null, nextExamOn: "2027-05-12" }],
      upcomingSessions: [],
      weakTopics: [{ topic: "Vectors", subjectCode: "0580", acc: 50 }],
      latestResult: { subjectCode: "0580", grade: "B", recordedAt: new Date(2026, 10, 2, 17, 0).toISOString() },
      calendar: [{ day: "2026-11-02", xp: 50 }],
    },
    expected: { action: "practice", mood: "idle" },
  },
  marking: {
    facts: { ...populated, activeUpload: { paperLabel: "0625/42" } },
    expected: { action: "marking", mood: "marking" },
  },
  "no-plan": { facts: { ...populated, upcomingSessions: [] }, expected: { action: "practice", mood: "grade-improved" } },
  "no-exams": {
    facts: { ...populated, subjects: populated.subjects.map((s) => ({ ...s, nextExamOn: null })) },
    expected: { action: "session", mood: "grade-improved" },
  },
  "streak-zero": {
    facts: {
      ...populated,
      latestResult: { subjectCode: "0580", grade: "A", recordedAt: new Date(2026, 10, 1, 18, 0).toISOString() },
      calendar: NINE_DAYS.filter((d) => d.day <= "2026-11-03"),
    },
    expected: { action: "session", mood: "idle" },
  },
  // Loading and error render their own blocks; the facts only keep the
  // controller's code path uniform.
  loading: { facts: populated, expected: { action: "session", mood: "grade-improved" } },
  error: { facts: populated, expected: { action: "session", mood: "grade-improved" } },
}
```

- [ ] **Step 4: Run the fixtures test**

Run: `npx vitest run tests/unit/studentHomeFixtures.test.ts`
Expected: PASS. If `tsconfig.test.json` rejects the `dev-previews` import in `npm run typecheck` later, add `"dev-previews/student-home/fixtures.ts"` to that file's `include` array, and nothing else.

- [ ] **Step 5: Write tokens**

Create `web/dev-previews/student-home/tokens.css`:
1. Copy `web/dev-previews/teacher-home/tokens.css` verbatim. It is the v5 light scheme, and every name it defines stays.
2. Append a `.sh-root[data-theme="dark"] { … }` block that reassigns the same custom properties to the dark values from the `dark-*` entries in `DESIGN.md` frontmatter (lines 55–88): primary `#7fb8e0`, primary-hover `#9ccaea`, on-primary `#042f4f`, primary-container `oklch(0.34 0.07 242)`, on-primary-container `oklch(0.92 0.035 235)`, error `oklch(0.72 0.15 25)`, success and success text `oklch(0.72 0.12 150)`, surface `#130e10`, the surface ladder lowest→highest (`oklch(0.12 0.006 240)`, `oklch(0.19 0.01 240)`, `oklch(0.215 0.014 240)`, `oklch(0.25 0.018 240)`, `oklch(0.29 0.022 240)`), on-surface `oklch(0.95 0.006 240)`, on-surface-variant `oklch(0.77 0.015 240)`, outline `oklch(0.38 0.02 240)`, outline-variant `oklch(0.30 0.018 240)`, inverse-primary `#042f4f`. Then point the semantic aliases (`--surface-page`, `--surface-card`, `--surface-row`, `--text-body`, `--text-secondary`, `--border-*`, `--track`) at the dark roles, following DESIGN.md "Scheme mapping": page on surface, cards on surface-high with no outline, rows on surface-container.
3. Add `--sh-gold-text: oklch(0.20 0.019 80)` (text on gold, both schemes) and `--sh-grade-*` aliases pointing at `--grade-*`.

- [ ] **Step 6: Write the Binny island**

Create `web/dev-previews/student-home/binny-island.tsx`:

```tsx
import { createRoot, type Root } from "react-dom/client"
import { Binny, type BinnyMood as MarketingMood } from "@/portals/marketing/Binny"
import type { BinnyMood } from "@/portals/student/home/model"

/*
 * The marketing Binny has six FAQ expressions, not the eight v5 XP moments.
 * This mapping is preview-only. The React port draws the real v5 moods.
 */
const MOOD: Record<BinnyMood, MarketingMood> = {
  marking: "thinking",
  "grade-improved": "happy",
  "paper-marked": "open",
  "streak-kept": "wink",
  idle: "idle",
}

const roots = new WeakMap<Element, Root>()

export function renderBinny(slot: Element, mood: BinnyMood): void {
  let root = roots.get(slot)
  if (!root) {
    root = createRoot(slot)
    roots.set(slot, root)
  }
  root.render(<Binny mood={MOOD[mood]} />)
}
```

Before writing it, open `web/src/portals/marketing/Binny.tsx` and check the props. If `Binny` needs props beyond `mood` (for example a size or `className`), pass the smallest valid set here and note them in the commit message.

- [ ] **Step 7: Write the controller**

Create `web/dev-previews/student-home/controller.ts`:

```ts
import { binnyMood, deriveNextAction, todayList } from "@/portals/student/home/model"
import { FIXTURES, STATES, type StateId } from "./fixtures"
import { renderBinny } from "./binny-island"

type Variant = "a" | "b" | "c"
const CONTROLS = {
  state: STATES,
  theme: ["light", "dark"],
  motion: ["full", "reduce"],
  width: ["desktop", "mobile"],
} as const
type ControlName = keyof typeof CONTROLS

function readParams(): Record<ControlName, string> {
  const q = new URLSearchParams(location.search)
  const pick = (name: ControlName) => {
    const v = q.get(name)
    const allowed = CONTROLS[name] as readonly string[]
    return v && allowed.includes(v) ? v : allowed[0]
  }
  return { state: pick("state"), theme: pick("theme"), motion: pick("motion"), width: pick("width") }
}

function apply(root: HTMLElement, variant: Variant, params: Record<ControlName, string>): void {
  const { facts } = FIXTURES[params.state as StateId]
  const action = deriveNextAction(facts, { preferClosestExam: variant === "b" })
  const mood = binnyMood(facts)
  Object.assign(root.dataset, {
    variant,
    state: params.state,
    action: action.kind,
    today: todayList(facts).map((a) => a.kind).join(" "),
    mood,
    theme: params.theme,
    motion: params.motion,
    width: params.width,
    exams: facts.subjects.some((s) => s.nextExamOn !== null) ? "yes" : "no",
  })
  document.querySelectorAll("[data-binny]").forEach((slot) => renderBinny(slot, mood))
  const qs = new URLSearchParams(params).toString()
  history.replaceState(null, "", `${location.pathname}?${qs}`)
  document.querySelectorAll<HTMLAnchorElement>("a[data-variant-link]").forEach((a) => {
    a.href = `./student-home-${a.dataset.variantLink}.html?${qs}`
    a.setAttribute("aria-current", a.dataset.variantLink === variant ? "page" : "false")
  })
}

export function mountHome(variant: Variant): void {
  const root = document.getElementById("sh-root")
  if (!root) throw new Error("student home preview: #sh-root missing")
  const params = readParams()
  for (const name of Object.keys(CONTROLS) as ControlName[]) {
    const select = document.querySelector<HTMLSelectElement>(`select[data-control="${name}"]`)
    if (!select) continue
    select.replaceChildren(
      ...(CONTROLS[name] as readonly string[]).map((v) => new Option(v, v, false, v === params[name])),
    )
    select.addEventListener("change", () => {
      params[name] = select.value
      apply(root, variant, params)
    })
  }
  apply(root, variant, params)
}
```

- [ ] **Step 8: Write the shell CSS**

Create `web/dev-previews/student-home/shell.css`. It holds preview chrome and the shared show/hide rules only, no variant styling:

```css
/* Preview chrome and state switching shared by variants A, B and C. */
*, *::before, *::after { box-sizing: border-box }
body { margin: 0; -webkit-font-smoothing: antialiased; background: oklch(0.90 0.01 240) }

.sh-toolbar {
  position: sticky; inset-block-start: 0; z-index: 10;
  display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
  padding: 8px 16px; background: #130e10; color: #fff;
  font: 600 13px/1.4 var(--font-ui);
}
.sh-toolbar select { font: inherit; min-block-size: 32px }
.sh-toolbar a { color: #7fb8e0 }
.sh-toolbar a[aria-current="page"] { color: #fff; text-decoration: none; font-weight: 800 }
.sh-demo { margin-inline-start: auto; font-family: var(--font-mono); letter-spacing: 0.08em; text-transform: uppercase }

/* The frame is a size container, so variants style themselves with
   @container queries and "mobile" works in a desktop browser. */
.sh-root {
  container-type: inline-size; container-name: home;
  margin-inline: auto; min-block-size: 100vh;
  background: var(--surface-page); color: var(--text-body);
  font-family: var(--font-ui);
}
.sh-root[data-width="desktop"] { max-inline-size: 1280px }
.sh-root[data-width="mobile"] { max-inline-size: 390px }

/* Exactly one state block is visible at a time. */
.sh-root [data-when-state] { display: none }
.sh-root[data-state="loading"] [data-when-state~="loading"],
.sh-root[data-state="error"] [data-when-state~="error"],
.sh-root[data-state="new"] [data-when-state~="new"] { display: block }
.sh-root:not([data-state="loading"], [data-state="error"], [data-state="new"]) [data-when-state~="ready"] { display: block }

/* Hero: one block per next-action kind. */
.sh-root [data-when-action] { display: none }
.sh-root[data-action="marking"] [data-when-action="marking"],
.sh-root[data-action="session"] [data-when-action="session"],
.sh-root[data-action="first-paper"] [data-when-action="first-paper"],
.sh-root[data-action="practice"] [data-when-action="practice"],
.sh-root[data-action="correct"] [data-when-action="correct"] { display: block }

/* Variant C's today list: each item shows when its kind is in data-today. */
.sh-root [data-today-item] { display: none }
.sh-root[data-today~="marking"] [data-today-item="marking"],
.sh-root[data-today~="session"] [data-today-item="session"],
.sh-root[data-today~="practice"] [data-today-item="practice"],
.sh-root[data-today~="correct"] [data-today-item="correct"],
.sh-root[data-today~="first-paper"] [data-today-item="first-paper"] { display: flex }

/* Binny caption: one line per mood. */
.sh-root [data-when-mood] { display: none }
.sh-root[data-mood="marking"] [data-when-mood="marking"],
.sh-root[data-mood="grade-improved"] [data-when-mood="grade-improved"],
.sh-root[data-mood="paper-marked"] [data-when-mood="paper-marked"],
.sh-root[data-mood="streak-kept"] [data-when-mood="streak-kept"],
.sh-root[data-mood="idle"] [data-when-mood="idle"] { display: inline }

/* Streak block: earned streak versus zero streak. */
.sh-root [data-when-streak] { display: none }
.sh-root:not([data-state="streak-zero"]) [data-when-streak="kept"],
.sh-root[data-state="streak-zero"] [data-when-streak="zero"] { display: block }

/* Study plan, exam dates and the no-plan or one-paper differences. */
.sh-root[data-state="no-plan"] [data-needs="plan"],
.sh-root[data-exams="no"] [data-needs="exams"],
.sh-root[data-state="one-paper"] [data-needs="many-papers"] { display: none }
.sh-root [data-only-state] { display: none }
.sh-root[data-state="one-paper"] [data-only-state="one-paper"],
.sh-root[data-state="no-plan"] [data-only-state="no-plan"],
.sh-root[data-exams="no"] [data-only-state="no-exams"] { display: block }

.sh-root[data-motion="reduce"] *, .sh-root[data-motion="reduce"] *::before, .sh-root[data-motion="reduce"] *::after {
  animation: none !important; transition: none !important;
}
@media (prefers-reduced-motion: reduce) {
  .sh-root *, .sh-root *::before, .sh-root *::after { animation: none !important; transition: none !important }
}
```

- [ ] **Step 9: Write the index page and register entries**

Create `web/dev-previews/student-home.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="robots" content="noindex, nofollow" />
    <title>Student home variants</title>
    <link rel="stylesheet" href="./student-home/tokens.css" />
    <link rel="stylesheet" href="./student-home/shell.css" />
  </head>
  <body>
    <main class="sh-root" data-width="desktop" style="padding: 48px">
      <h1>Student home variants</h1>
      <p>Demo data. Spec: docs/superpowers/specs/2026-11-05-student-home-design.md</p>
      <ul>
        <li><a href="./student-home-a.html">A. Today's page</a></li>
        <li><a href="./student-home-b.html">B. Exam runway</a></li>
        <li><a href="./student-home-c.html">C. Training log</a></li>
      </ul>
    </main>
  </body>
</html>
```

In `web/vite.preview.config.ts`, replace the `input` line with:

```ts
      input: {
        index: previewEntry("index"),
        directions: previewEntry("directions"),
        "student-home": previewEntry("student-home"),
        "student-home-a": previewEntry("student-home-a"),
        "student-home-b": previewEntry("student-home-b"),
        "student-home-c": previewEntry("student-home-c"),
      },
```

Also add one sentence to that file's comment block: the student home variant pages are named entries for the same reason `directions.html` is.

- [ ] **Step 10: Verify and commit**

Run: `npx vitest run tests/unit/studentHomeFixtures.test.ts tests/unit/studentHomeModel.test.ts && npm run typecheck && npx oxlint dev-previews/student-home`
Expected: all pass. (`build:kit` is checked in Task 6, once the variant pages exist.)

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
env PATH="/home/sico/Code/Lemely/.venv/bin:/usr/local/bin:/usr/bin:/bin" /home/sico/Code/Lemely/.venv/bin/pre-commit run --files web/dev-previews/student-home/* web/dev-previews/student-home.html web/vite.preview.config.ts web/tests/unit/studentHomeFixtures.test.ts
git add web/dev-previews/student-home web/dev-previews/student-home.html web/vite.preview.config.ts web/tests/unit/studentHomeFixtures.test.ts
git commit -S -m "feat(web): scaffold student home preview with fixtures, controller and dark tokens" -- web/dev-previews/student-home web/dev-previews/student-home.html web/vite.preview.config.ts web/tests/unit/studentHomeFixtures.test.ts
```

(If Step 4 needed the `tsconfig.test.json` include, add that path to both the pre-commit `--files` list and the commit path list.)

---

### Variant tasks 3–5: shared brief

Tasks 3, 4 and 5 are design work with fixed structure and copy. Run them in parallel, one designer agent each, because their file sets do not overlap. Each designer:

1. Invokes the impeccable skill (`/home/sico/Code/Lemely/.claude/skills/impeccable`), reads its `reference/craft-floor.md` before editing, and reads this branch's `DESIGN.md` and the spec.
2. Owns only its own two files, `student-home-{x}.html` and `student-home/variant-{x}.css`, and commits with `git commit -S -- <those two paths>`. It must not touch `shell.css`, `controller.ts`, `fixtures.ts` or another variant's files. If one of those needs a change, it reports the change to the orchestrator instead of making it.
3. Uses this page skeleton, keeping every `data-*` hook from the Task 2 contract:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="robots" content="noindex, nofollow" />
    <title>Student home: variant X</title>
    <link rel="stylesheet" href="./student-home/tokens.css" />
    <link rel="stylesheet" href="./student-home/shell.css" />
    <link rel="stylesheet" href="./student-home/variant-x.css" />
    <script type="module">
      import "@fontsource-variable/bricolage-grotesque"
      import "@fontsource-variable/schibsted-grotesk"
      import "@fontsource-variable/jetbrains-mono"
      import { mountHome } from "./student-home/controller.ts"
      mountHome("x")
    </script>
  </head>
  <body>
    <nav class="sh-toolbar" aria-label="Preview controls">
      <a data-variant-link="a">A</a> <a data-variant-link="b">B</a> <a data-variant-link="c">C</a>
      <label>State <select data-control="state"></select></label>
      <label>Theme <select data-control="theme"></select></label>
      <label>Motion <select data-control="motion"></select></label>
      <label>Width <select data-control="width"></select></label>
      <span class="sh-demo">Demo data</span>
    </nav>
    <main id="sh-root" class="sh-root">
      <section data-when-state="loading" aria-busy="true"><!-- skeleton shapes for hero, reward block, ledger --></section>
      <section data-when-state="error" role="alert"><!-- error block --></section>
      <section data-when-state="new"><!-- new-student onboarding with Binny idle --></section>
      <div data-when-state="ready"><!-- the variant's composition --></div>
    </main>
  </body>
</html>
```

The HTML comments above mark where the variant's own markup goes. Replace every one of them with real markup; none may remain in the finished file.

4. Uses this exact copy, which matches `fixtures.ts`:

| Block | Copy |
|---|---|
| Greeting | "Good morning, Mariam." Kicker: "3 subjects, 22 papers corrected so far." |
| Hero `marking` | Eyebrow "Marking now · 0625". Title "0625/42 is being marked". Body "Lemely is reading your answers and checking each one against the official mark scheme." Button "See progress". |
| Hero `session` (A and C) | Eyebrow "Today's session · 0606". Title "Quadratic inequalities". Meta "25 min". Body "Next in your study plan for Additional Mathematics." Button "Start session". |
| Hero `session` (B) | Eyebrow "Closest exam first · 0606". Title, meta, body and button as above. (The 0625 exam is closer, but the only due session is 0606, so the result is the same.) |
| Hero `first-paper` | Title "Let's get your first paper marked". Body "Photograph or upload a paper you have already sat. Lemely finds the session and variant, pulls the official mark scheme, and marks it question by question." Button "Correct a paper". |
| Hero `practice` | Eyebrow "Practise next · 0625". Title "Waves". Meta "54% accuracy". Body "Your weakest topic right now. A short set shows whether it is improving." Button "Practise waves". In state `one-paper`, use eyebrow "Practise next · 0580", title "Vectors", meta "50% accuracy", button "Practise vectors". |
| Hero `correct` | Title "Ready for another paper?" Body "Each paper sharpens your predicted grade." Button "Correct a paper". |
| Binny captions | marking "Reading your answers." · grade-improved "A in 0580, up from B." · paper-marked "Your 0580/42 result is in." · streak-kept "Day 9. Streak kept." · idle "Ready when you are." |
| Level block | "Level 7". "2,340 XP". Progress "240 / 500 XP to level 8" (levelStart 2,100, next 2,600). |
| Streak kept | "9-day streak". "Longest 14 · 1 freeze". The 7-day strip shows 30 Oct to 5 Nov, all earned, with today marked. |
| Streak zero | "No streak yet this week." Body "Correct a paper, finish a session, take a quiz or review flashcards to start one." Strip: 30 Oct to 3 Nov earned, 4 and 5 Nov empty. |
| Subjects ledger | 0580 Mathematics · A (up from B) · 14 papers · exam in 188 days. 0606 Additional Mathematics · B (no change) · 6 papers · exam in 194 days. 0625 Physics · C (up from D) · estimated · 2 papers · exam in 180 days. Exam cells carry `data-needs="exams"`. In state `one-paper`, only 0580 · B · 1 paper, with no change shown (rows 2 and 3 carry `data-needs="many-papers"`). |
| Weak topics | Waves 0625 54% · Quadratic inequalities 0606 58% · Vectors 0580 63% · Moments 0625 66%. Each row links to `/student/practice/{code}`. |
| Latest result | "0580/42 · m/j 2024" · 61/80 · grade A · "See full marking". |
| No plan note (`data-only-state="no-plan"`) | "No study plan this week. Build one from your weak topics." Link "Build a plan". |
| No exams note (`data-only-state="no-exams"`) | "Add your exam dates to see how long you have for each subject." Link "Add exam dates". |
| Error | Heading "Couldn't load your overview." Body "Check your connection and try again." Button "Try again". |
| New student | Greeting "Good morning, there." plus the `first-paper` hero, Binny (idle), and a three-step list: "Correct your first paper" (now), "See where you stand" (later), "Get a study plan built from your own mistakes" (later). |

5. Meets these acceptance checks before committing:
   - `/home/sico/Code/Lemely/.claude/skills/impeccable/scripts/impeccable detect web/dev-previews/student-home-x.html web/dev-previews/student-home/variant-x.css` reports zero findings, or every remaining finding is justified in the commit body.
   - Start the preview with `npm run preview:kit` (background) and open the URL Vite prints, plus `/student-home-x.html`. Take screenshots of states `populated`, `new`, `marking`, `streak-zero` and `error`, each in light desktop, dark desktop and light mobile. Look at them and fix what is wrong before committing. Save them in `/home/sico/.claude/jobs/434df4f0/tmp/student-home/x/` (not committed).
   - Every state in the toolbar renders without empty gaps or overlapping blocks in both themes and both widths.
   - Text contrast is at least 4.5:1 (3:1 for 24px and larger) in both themes. Check gold-on-surface and Tide-on-dark specifically.
   - Exactly one Binny is visible in every state except `loading` and `error`, which show none.
   - No raw colour literals in `variant-x.css`: only `var(--…)` tokens. Check with `grep -nE "#[0-9a-fA-F]{3,8}|oklch\(|rgb\(" web/dev-previews/student-home/variant-x.css`, which must print nothing.
   - Layout changes at mobile width use `@container home (max-width: 760px)`, not viewport media queries.
   - No HTML comments marking unwritten markup remain.

---

### Task 3: Variant A, Today's page

**Files:**
- Create: `web/dev-previews/student-home-a.html`
- Create: `web/dev-previews/student-home/variant-a.css`

**Interfaces:**
- Consumes: Task 2 root and toolbar contract, `mountHome("a")`, the shared brief.
- Produces: a live-editable page at `/student-home-a.html`.

**Composition (spec §6 A):**
- Desktop: greeting header with the compact level and streak pill on its inline end. First row, a two-column grid of about 3:2: the hero card (all five `data-when-action` blocks inside it, with the `data-binny` slot at the card's inline end so Binny stands beside the action) and the reward block (level and XP in Bricolage display, the progress bar, and the streak block with both `data-when-streak` variants). Second row: the subjects ledger at full width. Third row: weak topics (mark rows) beside the latest result. The no-plan and no-exams notes sit directly under the hero.
- Mobile (container at most 760px): one column in this order: greeting, hero (Binny above the action text, at 96px or smaller), reward block, subjects, weak topics, latest result.
- Focal moment: the hero action button, the only filled primary button on the page.

- [ ] **Step 1:** Write `student-home-a.html` from the shared skeleton with variant A's markup and the shared copy.
- [ ] **Step 2:** Write `variant-a.css` with token-only values and container-query responsiveness.
- [ ] **Step 3:** Run every acceptance check in the shared brief, item 5. Fix and re-check until all pass.
- [ ] **Step 4:** Run pre-commit on the two files, then `git add` them and `git commit -S -m "feat(web): student home preview variant A, today's page" -- web/dev-previews/student-home-a.html web/dev-previews/student-home/variant-a.css`.

### Task 4: Variant B, Exam runway

**Files:**
- Create: `web/dev-previews/student-home-b.html`
- Create: `web/dev-previews/student-home/variant-b.css`

**Interfaces:**
- Consumes: Task 2 contract, `mountHome("b")` (which passes `preferClosestExam: true`), the shared brief.
- Produces: a live-editable page at `/student-home-b.html`.

**Composition (spec §6 B):**
- Header band: greeting, `data-binny` slot, level, and streak (both `data-when-streak` variants) in one horizontal band on `--surface-section`.
- Body: a runway with one lane per subject, ordered by exam date (0625 on 4 May, 0580 on 12 May, 0606 on 18 May). Each lane shows code and name, the grade chip with its change and "estimated" where it applies, days left in JetBrains Mono, and the subject's next session or weakest topic. A shared horizontal scale from today to the last exam places each exam as a marker. The hero action card sits above the runway.
- No exams (`data-exams="no"`): hide the runway and its scale (`data-needs="exams"` on the runway container), show the no-exams note, and fall back to variant A's order (hero, reward, subjects ledger, weak topics, latest result). That fallback ledger and weak-topics block are part of this page's markup.
- Mobile: lanes stack vertically. The scale becomes a vertical list of exams with days left, never a horizontally scrolling timeline.
- Focal moment: the closest exam lane plus the hero button.

- [ ] **Step 1:** Write `student-home-b.html`.
- [ ] **Step 2:** Write `variant-b.css`.
- [ ] **Step 3:** Run every acceptance check in the shared brief, item 5. Also check state `no-exams` in both widths.
- [ ] **Step 4:** Run pre-commit, then `git commit -S -m "feat(web): student home preview variant B, exam runway" -- web/dev-previews/student-home-b.html web/dev-previews/student-home/variant-b.css`.

### Task 5: Variant C, Training log

**Files:**
- Create: `web/dev-previews/student-home-c.html`
- Create: `web/dev-previews/student-home/variant-c.css`

**Interfaces:**
- Consumes: Task 2 contract (`data-today` and `data-today-item`), `mountHome("c")`, the shared brief.
- Produces: a live-editable page at `/student-home-c.html`.

**Composition (spec §6 C):**
- Hero: Binny large (the `data-binny` slot) with level and XP at display size, the progress bar, and the 7-day streak strip as the dominant row. Gold marks earned days only.
- "Today" list directly under it, one row per `data-today-item` (`marking`, `session`, `practice`, `correct`, `first-paper`), with each row's title, meta and link taken from the matching hero copy. Rows show and hide through `data-today`, so the list is never longer than 3. Keep the five `data-when-action` hero blocks out of this page: the list replaces them.
- Below: subjects ledger, weak topics, latest result, smaller than in A.
- Guardrail: this variant tests the loud extreme. No confetti, no emoji, no exclamation marks, no badge walls, no bright primaries. If the designer judges a requirement here unavoidably pastiche, they implement the quieter option and note it in the commit body.
- Mobile: Binny at 120px or smaller, then level, streak strip, today list, the rest.

- [ ] **Step 1:** Write `student-home-c.html`.
- [ ] **Step 2:** Write `variant-c.css`.
- [ ] **Step 3:** Run every acceptance check in the shared brief, item 5. Also check that `marking` shows `["marking","session","practice"]` items and `new` shows only `first-paper`.
- [ ] **Step 4:** Run pre-commit, then `git commit -S -m "feat(web): student home preview variant C, training log" -- web/dev-previews/student-home-c.html web/dev-previews/student-home/variant-c.css`.

---

### Task 6: Cross-variant verification

**Files:** none created. Fixes go back to the owning task's files.

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: evidence that all three pages build and pass the gates. This is the gate sweep and runs last.

- [ ] **Step 1: Build the preview bundle**

Run: `npm run build:kit`
Expected: success, with `student-home*.html` in the output list.

- [ ] **Step 2: Unit tests, typecheck, lint, copy gate**

Run: `npx vitest run tests/unit/studentHomeModel.test.ts tests/unit/studentHomeFixtures.test.ts && npm run typecheck && npx oxlint dev-previews/student-home src/portals/student/home && npm run check:copy`
Expected: all pass.

- [ ] **Step 3: Detector sweep at both widths**

With `npm run preview:kit` running (background), and `<url>` being the host and port Vite printed:

```bash
D=/home/sico/Code/Lemely/.claude/skills/impeccable/scripts/impeccable
for v in a b c; do
  $D detect "<url>/student-home-$v.html?state=populated"
  $D detect --viewport 390x844 "<url>/student-home-$v.html?state=populated&width=mobile"
  $D detect "<url>/student-home-$v.html?state=populated&theme=dark"
done
```

Expected: zero findings, or each finding justified in a variant commit body.

- [ ] **Step 4: Independent review**

Dispatch the `impeccable-finish-reviewer` agent with: the spec path, this plan path, the three page paths, the screenshot folder `/home/sico/.claude/jobs/434df4f0/tmp/student-home/`, and the instruction to review each variant against DESIGN.md and spec §4–7 and return ordered material fixes. Route each fix to the owning variant's files, re-run that variant's acceptance checks, and commit there. If any fix lands, re-run Steps 1–3.

---

### Task 7: Impeccable live session (user-driven)

**Files:** whatever live mode accepts, limited to `web/dev-previews/student-home-*.html` and `web/dev-previews/student-home/variant-*.css`.

**Interfaces:**
- Consumes: the verified preview from Task 6.
- Produces: the user's chosen variant with live refinements committed, and a one-line decision recorded in the spec.

- [ ] **Step 1:** Make sure `npm run preview:kit` is running and note its URL.
- [ ] **Step 2:** From the worktree, run `/home/sico/Code/Lemely/.claude/skills/impeccable/scripts/impeccable live --target web/dev-previews/student-home-a.html` and follow `reference/live.md` exactly: open the page, run `impeccable live-poll` as a background task, and handle each event. Every live request produces variants, never a direct source edit.
- [ ] **Step 3:** Tell the user the three URLs (`student-home-a.html`, `-b.html`, `-c.html` on the preview server) and that the toolbar switches state, theme, motion and width. Ask which variant to iterate on, and switch `--target` when they change pages.
- [ ] **Step 4:** After each accepted variant, run the owning variant's acceptance checks (shared brief, item 5) and commit with `git commit -S -m "design(web): live refinement of student home variant X" -- <paths>`.
- [ ] **Step 5:** When the user picks a final direction, append a "Decision" line to spec §6 naming the chosen variant and the date. Commit that with `docs(spec): record student home variant decision`. Then stop: the React port and backend fields get their own plan.
