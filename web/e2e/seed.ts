import fs from "node:fs"
import path from "node:path"
import type { Page } from "@playwright/test"
import { reportDir } from "./report-dir"

/**
 * Typed mirror of `scripts/seed_e2e.py`'s "Output contract" (see that
 * file's module docstring) — the one seeding path this suite, `audit.mjs`
 * and the whole P3.10 Playwright surface share. Kept in lockstep by hand
 * with the Python side; nothing generates one from the other.
 *
 * That hand-lockstep is not self-enforcing, and `readSeed()` below is an
 * unchecked `as SeedContract` cast — so a field renamed on the Python side
 * types as `string` here and arrives as `undefined` at runtime, inside
 * whichever spec happened to touch it. `seed-contract.spec.ts` is the pin
 * that turns that into a single, named failure: it re-reads the same JSON
 * as `unknown` and asserts every field declared below is actually present
 * with the declared primitive type. **Add a field here and add it there.**
 */
export interface SeedAccount {
  userId: string
  email: string
  password: string
  displayName: string
  accessToken: string
}

export interface SeedStudent extends SeedAccount {
  expectedAtRiskReasons: string[]
  /** Only present on `students.correctedPaper`. */
  correctedPaperId?: string
}

export interface SeedContract {
  runTag: string
  generatedAt: string
  teacher: SeedAccount
  schoolAdmin: SeedAccount
  class: { classId: string; name: string; joinCode: string }
  students: {
    declining: SeedStudent
    inactive: SeedStudent
    control: SeedStudent
    correctedPaper: SeedStudent
  }
  parent: { userId: string; phone: string; accessToken: string; linkedStudent: string }
  reviewItem: {
    itemId: string
    attemptId: string
    /** A key into `students` — the seed currently sends `"inactive"`. */
    studentKey: keyof SeedContract["students"]
  }
  quiz: {
    quizId: string
    assignmentId: string
    submissionId: string
    /** A key into `students` — the seed currently sends `"control"`. */
    submittedBy: keyof SeedContract["students"]
    /**
     * `QuizMarkingStatus.value`, NOT always `"marked"`: the seed has a
     * documented marking-failure branch it deliberately does not fake, so
     * this is widened on purpose. Do not narrow it to a literal.
     */
    status: string
  }
  /** A teacher with no classes and no students — the empty-state account. */
  emptyTeacher: SeedAccount
  /** Unlike `parent`, this one carries **no** `linkedStudent`. */
  emptyParent: { userId: string; phone: string; accessToken: string }
  placement: {
    subjectCode: string
    paperNumber: number
    bankQuestionCount: number
    /**
     * Bare `SeedAccount`s, deliberately **not** `SeedStudent`s: these are
     * minted by `_signup_account` and carry no `expectedAtRiskReasons`.
     * `readSeed()`'s cast cannot catch that lie, so it is spelled out here.
     *
     * The four are separate accounts on purpose and must not be collapsed
     * into one — placement availability excludes a student's own prior
     * placement questions for the same subject, so reusing the `completed`
     * account to exercise the "available" screen reports the pool exhausted
     * on the very screen meant to show it available.
     */
    students: {
      unonboarded: SeedAccount
      available: SeedAccount
      inProgress: SeedAccount & {
        quizId: string
        assignmentId: string
        questionCount: number
      }
      completed: SeedAccount & {
        quizId: string
        assignmentId: string
        submissionId: string
        awardedMarks: number
        maximumMarks: number
      }
    }
  }
  practice: {
    subjectCode: string
    /** Bare `SeedAccount`s, as with `placement.students` above. */
    students: {
      active: SeedAccount & {
        unsubmittedAssignmentId: string
        markingAssignmentId: string
        markedAssignmentId: string
        deckId: string
      }
      settled: SeedAccount & { deckId: string }
      bare: SeedAccount
    }
  }
  /**
   * Carries **no student accounts**, by design rather than by omission: the
   * four S-24/S-25 states are held by accounts under `practice`/`placement`
   * (`practice.students.active` the populated week, `.settled` the persisted
   * `no_signal` refusal, `.bare` the ungenerated week, and
   * `placement.students.completed` the fully-completed one). A spec reaching
   * for `studyPlan.students` will find nothing.
   */
  studyPlan: {
    subjectCode: string
    activeSessionId: string
    activeSessionTopic: string
    activeSessionCount: number
    completedSessionCount: number
  }
}

/** Where `global-setup.ts` writes the seed contract and every spec reads it
 * back from. Lives under `reportDir()` (default the gitignored
 * `reports/.scratch`) rather than a temp dir so it survives exactly as long
 * as any other artifact of the run and is trivial to inspect by hand. */
export function seedFilePath(): string {
  return path.join(reportDir(), "e2e-seed.json")
}

/**
 * Read back the seed contract `global-setup.ts` (Playwright's `globalSetup`,
 * registered in `playwright.config.ts`) wrote once for this whole run.
 * Playwright does not share module state across worker processes — a cached
 * promise in a helper like this one would only ever populate the first
 * worker that called it — so every spec re-reads the same file rather than
 * re-seeding or caching in memory.
 */
export function readSeed(): SeedContract {
  const file = seedFilePath()
  if (!fs.existsSync(file)) {
    throw new Error(
      `No seed contract at ${file} — did global setup run? (see playwright.config.ts's ` +
        `"globalSetup" and web/e2e/global-setup.ts)`,
    )
  }
  return JSON.parse(fs.readFileSync(file, "utf-8")) as SeedContract
}

/**
 * Injects a real session (a genuine access token `scripts/seed_e2e.py`
 * minted through the actual `AuthService`, not a fabricated one) into
 * `localStorage` before the page's own scripts run, so the app treats it
 * exactly as it would a session produced by its own login UI — see
 * `web/src/lib/auth/storage.ts`'s `Session` shape. Mirrors
 * `web/scripts/audit.mjs::injectSession` (same shape, same
 * `refreshToken: null` — nothing in this suite lives long enough to need a
 * refresh, and `lib/api.ts` has no refresh-on-401 path that would care).
 *
 * Playwright's `addInitScript` is the equivalent of Puppeteer's
 * `evaluateOnNewDocument`, which `audit.mjs` uses for the same purpose; the
 * opaque-origin (`about:blank`) guard is carried over from that precedent
 * even though this suite never navigates anywhere that would hit it (no
 * Lighthouse pass here) — it's free and keeps the two implementations in
 * lockstep.
 */
export async function injectSession(
  page: Page,
  session: { accessToken: string; userId: string; role: string },
): Promise<void> {
  await page.addInitScript(
    (s) => {
      if (window.location.origin === "null") return
      window.localStorage.setItem("lemely.session", JSON.stringify(s))
    },
    { accessToken: session.accessToken, refreshToken: null, userId: session.userId, role: session.role },
  )
}
