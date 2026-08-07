import fs from "node:fs"
import path from "node:path"
import type { Page } from "@playwright/test"
import { reportDir } from "./report-dir"

/**
 * Typed mirror of `scripts/seed_e2e.py`'s "Output contract" (see that
 * file's module docstring) — the one seeding path this suite, `audit.mjs`
 * and the whole P3.10 Playwright surface share. Kept in lockstep by hand
 * with the Python side; nothing generates one from the other.
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
