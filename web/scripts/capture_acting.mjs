/*
 * Captures and axe-checks the "working as a lead teacher" states (paymob billing, phase 03
 * follow-up): the banner, the switcher, the gated screens, the refusal, the own-account note,
 * the dropped-choice notice, and the assistant invite on the join screen.
 *
 * Like `capture_surface.mjs`, this stubs `/api` at the network boundary and renders the built
 * `dist/`. Its images are evidence about LAYOUT and WORDING, not behaviour: the behaviour (the
 * header on the wire, the partitioned cache, the stale-membership reset) is proven in
 * `tests/unit/actingTeacher*.test.ts`. No live backend is touched, and the invented names and
 * numbers below are never shipped.
 *
 * It also records every `/api` request each state made with the acting header it carried, so the
 * "header on adopted routes only" rule can be read off a real browser run, not only a unit test.
 *
 * Usage:  node scripts/capture_acting.mjs [outDir]
 * Assumes `npm run build` has run. Serves `dist/` on its own port and stops only that server.
 */

import { createHash } from "node:crypto"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { chromium } from "@playwright/test"
import { assertPortFree, startPreview } from "./serve_guard.mjs"

const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const repoRoot = path.resolve(webDir, "..")
const PORT = 4331
const BASE = `http://127.0.0.1:${PORT}`
const outDir = path.resolve(process.argv[2] ?? path.join(repoRoot, ".superpowers/sdd/screens/p03-acting"))
const AXE = path.join(webDir, "node_modules/axe-core/axe.min.js")

const VIEWPORTS = [
  { name: "380", width: 380, height: 820 },
  { name: "768", width: 768, height: 1024 },
  { name: "1440", width: 1440, height: 1000 },
]

const HEADER = "x-lemely-acting-teacher"
const HASSAN = "11111111-1111-4111-8111-111111111111"
const AHMED = "22222222-2222-4222-8222-222222222222"

function fakeJwt(hoursAhead = 24) {
  const enc = (o) => Buffer.from(JSON.stringify(o)).toString("base64url")
  return `${enc({ alg: "none", typ: "JWT" })}.${enc({ sub: "capture-assistant", exp: Math.floor(Date.now() / 1000) + hoursAhead * 3600 })}.`
}

const SESSION = { accessToken: fakeJwt(), refreshToken: fakeJwt(72), userId: "capture-assistant", role: "teacher" }
const PROFILE = { userId: "capture-assistant", email: "sara.ali@example.com", displayName: "Sara Ali", role: "teacher" }

const MARKER = { memberId: "m1", teacherId: HASSAN, teacherName: "Mr Hassan", role: "marker", effectivePermissions: ["mark", "regrade", "view_results"], available: true }
const CO_TEACHER = { memberId: "m2", teacherId: AHMED, teacherName: "Ms Ahmed", role: "co_teacher", effectivePermissions: ["mark", "regrade", "generate_quiz", "manage_classes", "view_results", "manage_students", "view_usage"], available: true }
const SCHOOL = "33333333-3333-4333-8333-333333333333"
// A lead who holds school data: assistants cannot act for them right now.
const SCHOOL_LEAD = { memberId: "m3", teacherId: SCHOOL, teacherName: "Dr Nasr", role: "co_teacher", effectivePermissions: ["mark", "view_results"], available: false }
// A marker the lead gave no access to results.
const NO_VIEW = { ...MARKER, effectivePermissions: ["mark"] }

const cls = (id, label, n, code, join, avg) => ({ id, label, studentCount: n, average: avg, subjectCode: code, schoolId: null, joinCode: join, atRiskCount: 1, lastActivityAt: "2026-08-13T14:10:00Z", topWeakness: "Thermal physics" })

const CLASSES = {
  self: { classes: [cls("s1", "My Y9 Chemistry", 18, "0620", "CHEM9A", 61.4)] },
  [HASSAN]: { classes: [cls("c1", "Y11 Physics A", 24, "0625", "PHY11A", 64.2), cls("c2", "Y11 Physics B", 22, "0625", "PHY11B", 58.9), cls("c3", "Y10 Maths", 28, "0580", "MTH10", null)] },
  [AHMED]: { classes: [cls("a1", "Y12 Further Maths", 16, "0606", "FMA12A", 71.0)] },
}

const OVERVIEW = {
  stats: [
    { key: "Papers graded", value: "128", unit: "this term", foot: null, valueTone: "t1", footTone: "t2" },
    { key: "Need your eyes", value: "6", unit: "items", foot: "oldest waiting 2 days", valueTone: "err", footTone: "err" },
    { key: "Group mean", value: "64", unit: "%", foot: "up 3 since last paper", valueTone: "t1", footTone: "ok" },
    { key: "At risk", value: "2", unit: "students", foot: null, valueTone: "err", footTone: "t2" },
  ],
  atRisk: [
    {
      name: "Yusuf Rahman",
      grade: "D",
      delta: -7,
      weakTopic: "Thermal physics",
      flags: [{ reason: "declining_trend", summary: "Down 7 marks across the last three papers, all in thermal physics.", evidence: {}, acknowledged: null }],
    },
  ],
  retention: [],
  recentActivity: [
    { studentId: "s1", studentName: "Amina Farouk", subjectCode: "0625", percentage: 78, grade: "B", recordedAt: "2026-08-13T14:10:00Z", origin: "past_paper" },
    { studentId: "s2", studentName: "Yusuf Rahman", subjectCode: "0625", percentage: 41, grade: null, recordedAt: "2026-08-13T11:02:00Z", origin: "quiz" },
  ],
}

const QUIZZES = {
  quizzes: [
    { id: "q1", subjectCode: "0625", title: "Thermal physics check", status: "published", targetGrade: "B", includedTopics: ["Thermal physics"], poolSource: "past_papers", requestedCount: 10, timeLimitMinutes: 20, builderStep: 6, questionCount: 10 },
    { id: "q2", subjectCode: "0625", title: "Electricity starter", status: "draft", targetGrade: "C", includedTopics: ["Electricity"], poolSource: null, requestedCount: null, timeLimitMinutes: null, builderStep: 2, questionCount: 0 },
  ],
}

const DENIED = { detail: { code: "team_permission_denied", message: "You do not have permission to do this for that teacher." } }

const json = (route, body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })

/**
 * Each state: where to go, who is signed in, which lead (if any) the tab remembers, what the
 * membership list says, and anything to do before the shutter.
 */
const STATES = {
  "acting-home-marker": { route: "/teacher", memberships: [MARKER, CO_TEACHER], stored: HASSAN, expect: "Working as Mr Hassan" },
  "acting-classes-marker": { route: "/teacher/classes", memberships: [MARKER, CO_TEACHER], stored: HASSAN, expect: "Y11 Physics A", expectGone: "+ New class" },
  "acting-quizzes-marker": { route: "/teacher/quizzes", memberships: [MARKER, CO_TEACHER], stored: HASSAN, expect: "Thermal physics check", expectGone: "+ New quiz" },
  "acting-announcements-marker": { route: "/teacher/announcements", memberships: [MARKER, CO_TEACHER], stored: HASSAN, expect: "Your role on Mr Hassan's team doesn't allow this." },
  "acting-classes-co-teacher": { route: "/teacher/classes", memberships: [MARKER, CO_TEACHER], stored: AHMED, expect: "Y12 Further Maths", expectPresent: "+ New class" },
  "acting-lead-unavailable": { route: "/teacher", memberships: [MARKER, CO_TEACHER], stored: HASSAN, refuseClasses: { lead: HASSAN, code: "team_lead_unavailable" }, expect: "You can't work for Mr Hassan right now" },
  "acting-no-view": { route: "/teacher", memberships: [NO_VIEW, CO_TEACHER], stored: HASSAN, refuseClasses: { lead: HASSAN, code: "team_permission_denied" }, expect: "Your role can't view Mr Hassan's classes" },
  "refused-by-server": {
    route: "/teacher/classes",
    memberships: [MARKER, CO_TEACHER],
    stored: AHMED,
    // The role allows it on screen; the server says no (the lead changed the role a moment ago).
    deniedWrites: true,
    async act(page) {
      await page.getByRole("button", { name: "Delete" }).first().click()
      await page.getByRole("button", { name: "Delete class" }).click()
      await page.getByText("doesn't allow this").first().waitFor()
    },
  },
  "switcher-open": {
    route: "/teacher",
    memberships: [MARKER, CO_TEACHER],
    async act(page) {
      const aside = page.locator("aside").first()
      if (!(await aside.isVisible())) {
        await page.getByRole("button", { name: "Open teacher navigation" }).click()
        await page.waitForTimeout(500)
      }
      await page.getByRole("button", { name: /^Working as/ }).last().click()
      await page.getByRole("menu", { name: "Work as" }).waitFor()
    },
  },
  "own-account-team": { route: "/teacher/team", memberships: [MARKER, CO_TEACHER], stored: HASSAN, teamForbidden: true, expect: "This page is about your own account, not Mr Hassan's." },
  "own-account-billing": { route: "/teacher/billing", memberships: [MARKER, CO_TEACHER], stored: HASSAN, expect: "This page is about your own account, not Mr Hassan's." },
  // Looks the same as `own-account-team` on purpose: a lead who cannot be worked for must not take
  // the caller's own pages with them. Captured as evidence of that, exempt from the duplicate check.
  "own-account-while-unavailable": { route: "/teacher/team", memberships: [MARKER, CO_TEACHER], stored: HASSAN, teamForbidden: true, refuseClasses: { lead: HASSAN, code: "team_lead_unavailable" }, mayMatchOther: true, expect: "This page is about your own account, not Mr Hassan's." },
  "switcher-unavailable-lead": {
    route: "/teacher",
    memberships: [MARKER, SCHOOL_LEAD],
    async act(page) {
      const aside = page.locator("aside").first()
      if (!(await aside.isVisible())) {
        await page.getByRole("button", { name: "Open teacher navigation" }).click()
        await page.waitForTimeout(500)
      }
      await page.getByRole("button", { name: /^Working as/ }).last().click()
      await page.getByText("Not available right now").waitFor()
    },
  },
  "membership-unavailable-dropped": { route: "/teacher", memberships: [MARKER, SCHOOL_LEAD], stored: SCHOOL, expect: "Dr Nasr's team isn't available to you right now" },
  "membership-ended": { route: "/teacher", memberships: [CO_TEACHER], stored: HASSAN, expect: "Your access to that team has ended" },
  "checking-stored-choice": { route: "/teacher", memberships: [MARKER, CO_TEACHER], stored: HASSAN, holdMemberships: true },
  "no-memberships": { route: "/teacher/classes", memberships: [], expect: "My Y9 Chemistry", expectGone: "Working as" },
  "join-assistant-signed-out": { route: "/join/7HKPX2WCQY", memberships: [], signedOut: true, expect: "Mr Hassan invited you to assist on their team" },
  "join-assistant-teacher": { route: "/join/7HKPX2WCQY", memberships: [], expect: "Mr Hassan invited you to assist on their team" },
}

async function waitForServer(timeoutMs = 20000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(BASE)
      if (res.ok) return
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 300))
  }
  throw new Error(`vite preview did not answer on ${BASE}`)
}

async function stub(page, state, calls) {
  // Catch-all first, specific stubs after: Playwright matches the most recent route first.
  await page.route("**/api/**", (route) => json(route, {}))
  await page.route("**/api/**", async (route, request) => {
    const url = new URL(request.url())
    const headers = request.headers()
    const lead = headers[HEADER]
    calls.push({ method: request.method(), path: url.pathname.replace(/^\/api/, "") + url.search, actingHeader: lead ?? null })
    const key = lead ?? "self"
    const p = url.pathname.replace(/^\/api/, "")
    if (p === "/me/profile") return json(route, PROFILE)
    if (p === "/notifications/counts") return json(route, { unread: 0 })
    if (p === "/teacher/team/memberships") {
      if (state.holdMemberships) return // never answers: the "checking" screen
      return json(route, { memberships: state.memberships })
    }
    if (p.startsWith("/teacher/team/")) {
      return state.teamForbidden ? json(route, { detail: { code: "team_lead_only", message: "x" } }, 403) : json(route, {})
    }
    if (p === "/teacher/classes") {
      if (lead && state.refuseClasses && lead === state.refuseClasses.lead) {
        return json(route, { detail: { code: state.refuseClasses.code, message: "x" } }, 403)
      }
      return json(route, CLASSES[key] ?? CLASSES.self)
    }
    if (p === "/teacher/overview") return json(route, OVERVIEW)
    if (p === "/teacher/quizzes") return json(route, QUIZZES)
    if (p === "/teacher/announcements") return json(route, { announcements: [] })
    if (/^\/classes\/[^/]+$/.test(p) && request.method() === "DELETE" && state.deniedWrites) return json(route, DENIED, 403)
    if (p === "/invites/7HKPX2WCQY") return json(route, { role: "assistant", schoolName: null, className: null, teacherName: "Mr Hassan", childName: null })
    if (p.startsWith("/billing/")) return json(route, { detail: "stubbed" }, 500)
    return json(route, {})
  })
}

async function runAxe(page) {
  await page.addScriptTag({ path: AXE })
  return page.evaluate(async () => {
    // eslint-disable-next-line no-undef
    const r = await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] } })
    return r.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help, targets: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) }))
  })
}

async function main() {
  fs.mkdirSync(outDir, { recursive: true })
  await assertPortFree(BASE, PORT, "the acting capture")
  const server = startPreview(PORT, webDir)
  const consoleErrors = []
  const axeResults = {}
  const requestLog = {}
  try {
    await waitForServer()
    const browser = await chromium.launch()
    for (const vp of VIEWPORTS) {
      for (const [name, state] of Object.entries(STATES)) {
        const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 2, reducedMotion: "reduce" })
        await context.addInitScript(
          ([sess, key, stored]) => {
            if (sess === null) window.localStorage.removeItem(key)
            else window.localStorage.setItem(key, JSON.stringify(sess))
            window.localStorage.setItem("lemely.deviceId", "capture-device")
            if (stored) window.sessionStorage.setItem("lemely.acting-lead", stored)
          },
          [state.signedOut ? null : SESSION, "lemely.session", state.stored ?? null],
        )
        const page = await context.newPage()
        page.on("console", (msg) => {
          if (msg.type() === "error") consoleErrors.push(`[${vp.name}/${name}] ${msg.text()}`)
        })
        const calls = []
        await stub(page, state, calls)
        await page.goto(`${BASE}${state.route}`, { waitUntil: "domcontentloaded" })
        await page.waitForTimeout(state.holdMemberships ? 1200 : 1800)
        if (state.expect) await page.getByText(state.expect).filter({ visible: true }).first().waitFor({ timeout: 6000 })
        if (state.expectPresent) await page.getByText(state.expectPresent).filter({ visible: true }).first().waitFor({ timeout: 3000 })
        if (state.expectGone && (await page.getByText(state.expectGone).filter({ visible: true }).count()) > 0) {
          throw new Error(`${vp.name}/${name}: "${state.expectGone}" should not be on the page`)
        }
        if (state.act) await state.act(page)
        await page.waitForTimeout(300)

        const file = path.join(outDir, `${name}--${vp.name}.png`)
        await page.screenshot({ path: file, fullPage: !state.act })
        axeResults[`${name}--${vp.name}`] = await runAxe(page)
        requestLog[`${name}--${vp.name}`] = calls
        console.log(`captured ${path.relative(repoRoot, file)}  axe: ${axeResults[`${name}--${vp.name}`].length} violation(s)`)
        await context.close()
      }
    }
    await browser.close()
  } finally {
    await server.stop()
  }

  // Distinct states must produce distinct images, or a route mistake photographs one screen 13 times.
  const dupes = []
  for (const vp of VIEWPORTS) {
    const seen = new Map()
    for (const [name, state] of Object.entries(STATES)) {
      if (state.mayMatchOther) continue
      const digest = createHash("sha256").update(fs.readFileSync(path.join(outDir, `${name}--${vp.name}.png`))).digest("hex")
      if (seen.has(digest)) dupes.push(`${vp.name}: ${seen.get(digest)} == ${name}`)
      else seen.set(digest, name)
    }
  }
  fs.writeFileSync(path.join(outDir, "axe-results.json"), JSON.stringify(axeResults, null, 2) + "\n")
  fs.writeFileSync(path.join(outDir, "api-requests.json"), JSON.stringify(requestLog, null, 2) + "\n")
  fs.writeFileSync(path.join(outDir, "console-errors.txt"), consoleErrors.length ? consoleErrors.join("\n") + "\n" : "none\n")
  const total = Object.values(axeResults).reduce((n, v) => n + v.length, 0)
  console.log(`\naxe violations across ${Object.keys(axeResults).length} captures: ${total}`)
  console.log(consoleErrors.length ? `${consoleErrors.length} console error(s)` : "no console errors")
  if (dupes.length) throw new Error(`identical captures for states that must differ:\n  ${dupes.join("\n  ")}`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
