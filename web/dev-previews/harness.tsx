/**
 * Preview harness for the Abyss component kit.
 *
 * REDESIGN-MISSION §5 Phase 2.6 requires every component in the kit to
 * implement all eight states (default / hover / focus-visible / active /
 * disabled / loading / error / success) and to have a preview page proving it.
 * This file is the scaffolding that page is built from; `App.tsx` beside it is
 * the page.
 *
 * Two of the eight states cannot be produced by a static render, because they
 * only exist while a pointer or the keyboard is interacting with the element:
 * `hover` and `active`. The honest thing is to say so rather than to fake them
 * with a class that merely looks like the hover style. So each state cell is
 * labelled with how it is produced:
 *
 *   - **prop**   the component genuinely is in that state (disabled, loading,
 *                error, success) and what you see is real
 *   - **live**   you must hover, focus or press the control to see it; the
 *                cell renders the ordinary component and says exactly what to do
 *
 * There is deliberately no third "forced" mode. One was built: a
 * `@custom-variant` pinning `hover`/`active` under a `data-force` wrapper, so a
 * static screenshot could capture them. It emitted zero CSS in this setup (the
 * reason is recorded in `preview.css`) and was removed rather than left in
 * place. A cell labelled as showing a hover state while actually rendering the
 * default state is worse than a cell that simply tells you to hover, because
 * the first one quietly passes review. Hover and active are verified with a
 * real pointer in the Phase 6 pass.
 *
 * This directory is NOT part of the app build. It is a separate Vite entry
 * (see `vite.preview.config.ts`) so that shipping the product never ships the
 * preview page, and so the preview cannot drift into being a real route.
 */

import { useEffect, useState, type ReactNode } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ApiError } from "@/lib/api"
import type { Profile } from "@/lib/meTypes"
import type { NotificationCounts, NotificationsPage } from "@/lib/notificationTypes"
import type { AtRiskStudent, ClassSummary, Overview } from "@/lib/teacherTypes"

/** The eight states every interactive component must implement. */
export const STATES = [
  "default",
  "hover",
  "focus-visible",
  "active",
  "disabled",
  "loading",
  "error",
  "success",
] as const

export type State = (typeof STATES)[number]

/** How a given state cell was produced. See the file header. */
export type Provenance = "prop" | "live"

const PROVENANCE_LABEL: Record<Provenance, string> = {
  prop: "real",
  live: "interact",
}

const PROVENANCE_TONE: Record<Provenance, string> = {
  prop: "bg-success-container text-on-success-container",
  live: "bg-primary-container text-on-primary-container",
}

/**
 * A single labelled state cell.
 *
 * The label is not decoration. A preview page whose cells are unlabelled is
 * how a component ends up shipping with a `disabled` style that was never
 * actually rendered in the disabled state, because the reviewer assumed the
 * cell was real when it was a mock.
 */
export function StateCell({
  state,
  provenance,
  note,
  wide,
  children,
}: {
  state: State
  provenance: Provenance
  note?: string
  /** Spans the whole grid row, for screen-sized components that are unreadable in a 260px cell. */
  wide?: boolean
  children: ReactNode
}) {
  return (
    <div className={`${wide ? "col-span-full " : ""}flex flex-col gap-3 rounded-card border border-outline-variant bg-surface-container-lowest p-4 dark:bg-surface-container-high`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-eyebrow text-on-surface-variant">{state}</span>
        <span
          className={`rounded-full px-2 py-0.5 text-eyebrow ${PROVENANCE_TONE[provenance]}`}
          title={
            provenance === "live"
              ? "Interact with this control to see the state"
              : "The component really is in this state"
          }
        >
          {PROVENANCE_LABEL[provenance]}
        </span>
      </div>
      <div className="flex min-h-16 flex-wrap items-center gap-3">{children}</div>
      {note ? <p className="text-body-sm text-on-surface-variant">{note}</p> : null}
    </div>
  )
}

/** One component's section: a title, an optional note, and its state grid. */
export function ComponentSection({
  name,
  summary,
  children,
}: {
  name: string
  summary: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-5 scroll-mt-24" id={slug(name)}>
      <header className="flex flex-col gap-2 border-s-2 border-outline ps-4">
        <h2 className="text-display-md text-on-surface">{name}</h2>
        <p className="text-body-md max-w-[65ch] text-on-surface-variant">{summary}</p>
      </header>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4">{children}</div>
    </section>
  )
}

/** A group of related component sections. */
export function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-section-sm scroll-mt-24" id={slug(title)}>
      <h1 className="text-display-lg text-on-surface">{title}</h1>
      {children}
    </div>
  )
}

export function slug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
}

/* ── Theme ────────────────────────────────────────────────────────────────── */

export type Theme = "light" | "dark"

/**
 * Sets `data-theme` on `<html>`, exactly as the app's `applyTheme` does, so
 * every `dark:` variant and every `--md-*` override the product uses is the
 * one this page shows. No `prefers-color-scheme` involvement.
 */
export function useThemeToggle(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  )
  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])
  return [theme, setTheme]
}

/* ── Contrast, computed from the live tokens ──────────────────────────────── */

/**
 * Resolves any CSS colour (the tokens are `oklch()`) to 8-bit sRGB by painting
 * one pixel on a canvas, then applies the WCAG 2.x relative-luminance formula.
 * Nothing here is typed in by hand: a ratio shown on the page is the ratio of
 * the colours the browser is painting in the current theme, recomputed when the
 * theme changes. `tests/test_design_tokens.py` is the CI pin; this is the
 * eyeball check against it.
 */
let probe: CanvasRenderingContext2D | null = null
function toRgb(css: string): [number, number, number] | null {
  probe ??= document.createElement("canvas").getContext("2d", { willReadFrequently: true })
  if (!probe) return null
  probe.clearRect(0, 0, 1, 1)
  probe.fillStyle = "#000"
  probe.fillStyle = css
  probe.fillRect(0, 0, 1, 1)
  const [r, g, b] = probe.getImageData(0, 0, 1, 1).data
  return [r!, g!, b!]
}

function luminance([r, g, b]: [number, number, number]): number {
  const lin = (c: number) => {
    const v = c / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

function tokenColour(token: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(token).trim()
}

/** WCAG contrast of `fg` over `bg`, each a CSS custom-property name such as `--md-on-surface`. */
export function contrastOf(fg: string, bg: string): number | null {
  const a = toRgb(tokenColour(fg))
  const b = toRgb(tokenColour(bg))
  if (!a || !b) return null
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}

/**
 * Measures the ratio after the theme attribute has been applied, and again on
 * any later change to `data-theme` on `<html>` (watched directly, so it stays
 * right however the theme was set). `theme` is kept as a dependency for the
 * toggle on this page.
 */
export function useContrast(fg: string, bg: string, theme: Theme): string {
  const [ratio, setRatio] = useState<string>("")
  useEffect(() => {
    let raf = 0
    const measure = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const c = contrastOf(fg, bg)
        setRatio(c === null ? "n/a" : `${c.toFixed(2)}:1`)
      })
    }
    measure()
    const observer = new MutationObserver(measure)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] })
    return () => {
      cancelAnimationFrame(raf)
      observer.disconnect()
    }
  }, [fg, bg, theme])
  return ratio
}

/* ── Seeded react-query for components that call hooks ────────────────────── */

/**
 * The teacher top-bar and home components read their data through react-query
 * hooks that call `request()`. The preview must never hit an API, so each cell
 * gets its own `QueryClient` pre-filled from a fixture:
 *
 *   - `data`    a `setQueryData` entry, so the hook resolves immediately
 *   - `errors`  a query forced into its error state (the hook's own `isError`)
 *   - neither   the hook is pending, which is its genuine loading state: the
 *               global fetch stub (see `blockApiFetch`) never answers, so it
 *               stays loading rather than failing against a missing server
 *
 * `retryOnMount: false` and an infinite `staleTime` stop react-query replacing
 * a seeded error or value with a fetch the moment the cell mounts. Pressing
 * "Try again" on a seeded error does fire the stubbed fetch, so the button
 * goes to its busy label and stays there; that is the one behaviour a preview
 * with no server cannot complete, and it is labelled where it appears.
 */
export type QuerySeed = {
  data?: ReadonlyArray<readonly [readonly unknown[], unknown]>
  errors?: ReadonlyArray<readonly [readonly unknown[], Error]>
}

function makeSeededClient(seed: QuerySeed): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity, retryOnMount: false, refetchOnWindowFocus: false },
    },
  })
  for (const [key, value] of seed.data ?? []) client.setQueryData([...key], value)
  for (const [key, error] of seed.errors ?? []) {
    client
      .getQueryCache()
      .build(client, { queryKey: [...key] })
      .setState({
        status: "error",
        error,
        errorUpdateCount: 1,
        errorUpdatedAt: Date.now(),
        fetchFailureCount: 1,
        fetchFailureReason: error,
      })
  }
  return client
}

export function Seeded({ seed, children }: { seed: QuerySeed; children: ReactNode }) {
  const [client] = useState(() => makeSeededClient(seed))
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

/** Makes every `/api` request hang instead of failing. Called once from `main.tsx`. */
export function blockApiFetch(): void {
  const real = window.fetch.bind(window)
  window.fetch = (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url
    if (new URL(url, window.location.href).pathname.startsWith("/api/")) return new Promise<Response>(() => {})
    return real(input, init)
  }
}

/* ── Fixtures: shapes mirror the wire types in src/lib ────────────────────── */

const ago = (ms: number) => new Date(Date.now() - ms).toISOString()
const HOUR = 3_600_000
const DAY = 24 * HOUR

export const FIXTURE_PROFILE: Profile = {
  displayName: "Hana Sabry",
  email: "h.sabry@example.school",
  role: "teacher",
  emailVerified: true,
  avatarUrl: null,
  timezone: "Africa/Cairo",
  timezoneIsExplicit: true,
}

export const FIXTURE_NOTIFICATIONS: NotificationsPage = {
  notifications: [
    { notificationId: "n1", type: "at_risk_alert", title: "Omar Fathy is on a falling trend", body: "Three papers in a row below his target.", payload: {}, createdAt: ago(2 * HOUR), readAt: null },
    { notificationId: "n2", type: "announcement", title: "Mock exam week starts Monday", body: "Papers 2 and 4 for Year 11.", payload: {}, createdAt: ago(DAY), readAt: null },
    { notificationId: "n3", type: "grade_ready", title: "12 papers marked for 11B", body: null, payload: {}, createdAt: ago(3 * DAY), readAt: ago(2 * DAY) },
  ],
}

export const FIXTURE_COUNTS: NotificationCounts = { unread: 2, total: 3, unreadByType: { at_risk_alert: 1, announcement: 1 } }

export const FIXTURE_CLASSES: ClassSummary[] = [
  { id: "c1", label: "Year 11 Physics", studentCount: 24, average: 71.4, subjectCode: "0625", subjectName: "Physics", schoolId: null, joinCode: "PHY-4K7Q", atRiskCount: 3, lastActivityAt: ago(2 * HOUR), topWeakness: "Electromagnetic induction", grade: "B", delta: 2.1, lastPaper: "P4", lastPaperAt: ago(2 * DAY), topWeaknessAccuracy: 0.42 },
  { id: "c2", label: "Year 10 Chemistry", studentCount: 28, average: 64.8, subjectCode: "0620", subjectName: "Chemistry", schoolId: null, joinCode: "CHM-9X2M", atRiskCount: 1, lastActivityAt: ago(DAY), topWeakness: "Rates of reaction", grade: "C", delta: -1.2, lastPaper: "P2", lastPaperAt: ago(5 * DAY), topWeaknessAccuracy: 0.55 },
  { id: "c3", label: "Year 11 Mathematics", studentCount: 22, average: 82.3, subjectCode: "0580", subjectName: "Mathematics", schoolId: null, joinCode: "MTH-2R8D", atRiskCount: 0, lastActivityAt: ago(3 * DAY), topWeakness: "Vectors", grade: "A*", delta: 0, lastPaper: "P4", lastPaperAt: ago(7 * DAY), topWeaknessAccuracy: 0.71 },
  { id: "c4", label: "Year 9 Biology", studentCount: 3, average: null, subjectCode: "0610", subjectName: "Biology", schoolId: null, joinCode: "BIO-6T1H", atRiskCount: null, lastActivityAt: null, topWeakness: null, grade: null, delta: null, lastPaper: null, lastPaperAt: null, topWeaknessAccuracy: null },
]

const flag = (summary: string, acknowledged = false) => ({
  reason: "falling_trend",
  summary,
  evidence: {},
  acknowledged: acknowledged ? { acknowledgedBy: "t1", acknowledgedAt: ago(DAY), note: null } : null,
})

export const FIXTURE_AT_RISK: AtRiskStudent[] = [
  { name: "Omar Fathy", grade: "D", delta: -6, weakTopic: "Electricity", previousGrade: "C", flags: [flag("Three papers in a row below target."), flag("No activity this week.")] },
  { name: "Salma Nabil", grade: "E", delta: -4, weakTopic: "Waves", previousGrade: "D", flags: [flag("Dropped a grade since the last paper.", true)] },
  { name: "Karim Adel", grade: "C", delta: -3, weakTopic: null, previousGrade: "B", flags: [flag("Marks falling over the last four papers.")] },
]

export const FIXTURE_OVERVIEW: Overview = {
  stats: [],
  atRisk: FIXTURE_AT_RISK,
  retention: [],
  recentActivity: [],
  paperCount: 64,
  pendingReviewCount: 14,
  reviewConfidenceBuckets: [1, 0, 1, 0, 2, 1, 2, 3, 3, 1],
  reviewEstimateMinutes: 5,
  reviewConfidenceThreshold: 0.9,
}

export const KEYS = {
  profile: ["me", "profile"],
  inbox: ["notifications"],
  counts: ["notifications", "counts"],
  classes: ["teacher", "classes"],
  overview: ["teacher", "overview"],
} as const

export const FAILURE = new ApiError(500, "The server could not be reached.")
