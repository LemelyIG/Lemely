import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"

import { appRoutes, flattenRoutes } from "@/routes"
import { dataHandlingRoute } from "@/portals/marketing"
import {
  dataHandlingClose,
  dataHandlingIntro,
  dataHandlingSections,
  deletion,
  tutoringSections,
} from "@/portals/marketing/dataHandling"

/*
 * P6.5 / D6.8 · "How your data is handled", pinned.
 *
 * §5's Phase 6.5 list ends with "legal links". D6.8 chose one factual page and
 * no terms of service, on the reasoning that **facts about this product can be
 * derived from this repository and promises cannot**, and a policy is mostly
 * promises. That decision only holds if the page stays factual, so the two
 * things this file guards are the two ways it could stop being so:
 *
 *   1. The page acquires a promise. Reassurance is the natural register for a
 *      page about data, and every reassuring sentence available here would be
 *      an undertaking by an operator who does not exist in this code.
 *   2. The product changes and the page does not. Task 15 is the second kind of
 *      drift actually happening: the page used to say there was no way to
 *      delete a scan and no retention machinery, and paper deletion shipped
 *      underneath it, which made both sentences false. The `deletion` export
 *      that replaced the old "Not built yet" panel is checked below against
 *      `lemely/core/deletion.py`'s own retention constant, `lemely/web/purge.py`,
 *      `lemely/db/deletion_repo.py` and `lemely/db/xp_repo.py`, not just read
 *      for plausible wording, and the backend-route check that used to prove
 *      the opposite claim is now inverted to keep proving the current one:
 *      the day account deletion ships, that assertion goes red the same way
 *      the deletion one used to.
 *
 * This project's recurring finding is that a comment describing an intention
 * is not evidence the code has it, and a page describing the backend is the
 * same shape: it is true on the day it is written and nothing notices when it
 * stops being, which is why every fact below is checked against the module
 * that implements it rather than against the copy alone.
 */

const repoRoot = path.resolve(__dirname, "../../..")

/**
 * Is `name` anywhere in this route's element tree?
 *
 * Lifted in shape from `marketing.test.ts`, where it exists to ask "is this
 * route behind a guard" without rendering it. Kept as a local copy rather than
 * exported from there because a test helper shared between two spec files is a
 * dependency between two specs.
 */
function containsComponent(node: unknown, name: string): boolean {
  if (!node || typeof node !== "object") return false
  if (Array.isArray(node)) return node.some((n) => containsComponent(n, name))
  const el = node as { type?: unknown; props?: { children?: unknown } }
  const type = el.type as { name?: string; displayName?: string } | undefined
  if (type && (type.name === name || type.displayName === name)) return true
  return containsComponent(el.props?.children, name)
}

/** Every sentence in the six ordinary sections plus the intro and closer, without the deletion panel. */
const nonDeletionCopy = [
  ...Object.values(dataHandlingIntro),
  ...dataHandlingSections.flatMap((s) => [s.heading, s.body]),
  dataHandlingClose,
].join("\n")

/**
 * The tutoring marketplace sentences. Kept apart from `nonDeletionCopy` on
 * purpose: the "no retention number outside the deletion panel" test below
 * guards the six original sections, and the tutoring day counts are facts
 * pinned to Python constants in the last describe of this file.
 */
const tutoringCopy = tutoringSections.flatMap((s) => [s.heading, s.body]).join("\n")

/** Every sentence a reader can see on the page, flattened. */
const allCopy = [nonDeletionCopy, ...Object.values(deletion), tutoringCopy].join("\n")

describe("the data page is public and reachable — P6.5", () => {
  it("mounts /data at the top level", () => {
    expect(flattenRoutes(appRoutes).map((r) => r.path)).toContain("/data")
  })

  /*
   * The reader this page is for is the one deciding whether to upload a first
   * scan, and they do not have an account yet. A guard here would make the page
   * visible only to people who have already made the decision it exists to
   * inform. This is P4.9's defect (the marketing page behind a student-only
   * guard) asserted before it can happen a second time.
   */
  it("puts no auth guard on it", () => {
    /*
     * Walked as a route element tree, not grepped for in the source. The first
     * draft of this test read `index.tsx` as text and failed, because that file
     * says in a comment that it deliberately contains no `RequireAuth` — a
     * check that a *word* is absent cannot tell an implementation from a
     * sentence about one, which is a small instance of this project's own
     * recurring finding. Matching by component name also survives the guard
     * being wrapped in a Suspense or a frame, which is how P4.9's original
     * defect hid. Same technique as `marketing.test.ts`.
     */
    const route = flattenRoutes(appRoutes).find((r) => r.path === "/data")
    expect(route).toBeDefined()
    expect(containsComponent(route!.element, "RequireAuth")).toBe(false)
  })

  it("is linked from the marketing footer, so it is not an orphan route", () => {
    const source = fs.readFileSync(
      path.resolve(__dirname, "../../src/portals/marketing/index.tsx"),
      "utf8",
    )
    expect(source).toMatch(/to="\/data"/)
  })

  /*
   * One of only two routes in the product a signed-out reader can reach that is
   * not a sign-in form, so it is one of the few that a description is worth
   * writing for at all (see `lib/meta/documentMeta.ts`).
   */
  it("carries its own title and description", () => {
    const handle = dataHandlingRoute.handle as { title: string; description?: string }
    expect(handle.title).toBe("How your data is handled")
    expect(handle.description).toBeTruthy()
  })
})

describe("the page states facts, not promises — D6.8", () => {
  /*
   * Each pattern is a promise this page cannot make, not a word that reads
   * badly. The distinction matters because the fix for a failure here is never
   * to reword: it is to establish that the code does the thing, and then say
   * what it does.
   */
  const bannedPromises: [RegExp, string][] = [
    // The archetypal one. Nothing in this repository can support a claim about
    // the security of an operator's deployment, and this page has no operator.
    [/\bwe (will|would|never|do not|don't)\b/i, "a promise needs somebody to make it"],
    [/\byour data is (safe|secure|protected)\b/i, "unsupportable claim about a deployment"],
    [/\bguarantee/i, "a guarantee is an undertaking, not a behaviour"],
    [/\bcommitted?\s+to\b/i, "a commitment is an undertaking, not a behaviour"],
    [/\bwe (take|value|respect)\b/i, "the reassurance register, which says nothing"],
    // GDPR/CCPA language implies a legal analysis nobody in this repository has
    // done, and a controller nobody has named.
    [/\bGDPR\b|\bCCPA\b|\bdata controller\b/i, "no legal analysis backs this"],
    // §3.2 item 10, which applies to this page like any other UI copy.
    [/—/, "no em-dashes in UI copy"],
  ]

  it.each(bannedPromises)("makes no claim matching %s (%s)", (pattern) => {
    expect(allCopy).not.toMatch(pattern)
  })

  /*
   * A retention period used to be banned across the whole page, on the
   * reasoning that this product had no retention machinery at all and a
   * number of days would be inventing the feature in prose (D6.8). Paper
   * deletion (Task 1) made that reasoning true of six of the seven panels
   * and false of the seventh: `deletion` is now the one place a day count is
   * a fact rather than an invention, checked below against
   * `lemely/core/deletion.py`. Everywhere else, a stray "30 days" would still
   * be exactly the invented-feature failure this test existed to catch.
   */
  it("invents no retention number outside the deletion panel", () => {
    expect(nonDeletionCopy).not.toMatch(/\b\d+\s*(days?|months?|years?)\b/i)
  })

  /*
   * The positive half. A page that merely avoided promises could do so by
   * saying nothing, so these are the three facts the page exists to carry, and
   * the third is the one a reader is least likely to guess.
   */
  it("names where a scan is sent", () => {
    expect(allCopy).toMatch(/Google Gemini/)
  })

  it("says the file itself is sent, not just text taken from it", () => {
    // `lemely/io/answer_extraction.py` passes `file_paths=[scan_path]` and
    // `lemely/io/gemini.py` resolves that to `files.upload(file=fp)`. A reader
    // cannot tell which of the two happens from a phrase like "we use AI", and
    // it is the difference between their handwriting leaving the building and
    // a string doing so.
    expect(allCopy).toMatch(/file itself is sent/i)
  })

  it("says a parent sees only a student they are linked to", () => {
    expect(allCopy).toMatch(/only for a student they are linked to/i)
  })

  /*
   * PR 1B (client error reporting) added a real code path this page used to
   * say did not exist ("no code path sends any of this to anyone" used to be
   * unqualified). These pin the fourth fact the page now has to carry: that
   * a crash report exists, what it contains, where it goes, and that it
   * excludes the things a reader would most want excluded.
   */
  it("says a crash report is sent only when something breaks, not on an ordinary visit", () => {
    expect(allCopy).toMatch(/sent only when something breaks/i)
  })

  it("names where a crash report goes: Lemely's backend, then Google Cloud Logging", () => {
    expect(allCopy).toMatch(/Lemely's own backend/i)
    expect(allCopy).toMatch(/Google Cloud Logging/)
  })

  it("says a crash report does not include answers, marks or session data", () => {
    expect(allCopy).toMatch(/does not include your answers, your marks, or anything stored in your session/i)
    expect(allCopy).toMatch(/stored in your session/i)
    expect(allCopy).toMatch(/your marks/i)
  })
})

describe("the access it describes is the access the backend grants — #243", () => {
  /*
   * `teacher_paper_visible` (`lemely/db/teacher_paper_repo.py`) returns
   * `sa.true()` for platform_admin and every school-member teacher's papers
   * for school_admin; `ClassService` (`lemely/db/class_repo.py`) gives a
   * school_admin every class in their schools. A page that named only
   * class-scoped teachers was narrower than the code.
   */
  it("names the school administrator and the platform administrator", () => {
    const section = dataHandlingSections.find((s) => s.heading === "Who else can see your work")
    expect(section).toBeDefined()
    expect(section!.body).toMatch(/school administrator/i)
    expect(section!.body).toMatch(/platform administrator/i)
  })
})

describe("the page cannot silently outlive the product it describes — D6.8", () => {
  /**
   * Every `@router.delete` path declared by the backend.
   *
   * Read from the source rather than from a list kept here, for the same reason
   * the adapt gate imports its surface registry instead of restating it: a list
   * maintained by hand is a list that is missing the row somebody added today.
   */
  function declaredDeleteRoutes(): string[] {
    const dir = path.join(repoRoot, "lemely/web/routers")
    const out: string[] = []
    for (const file of fs.readdirSync(dir)) {
      if (!file.endsWith(".py")) continue
      const source = fs.readFileSync(path.join(dir, file), "utf8")
      for (const m of source.matchAll(/@router\.delete\(\s*\n?\s*"([^"]*)"/g)) out.push(m[1])
    }
    return out
  }

  it("finds the backend delete routes at all, so this file cannot pass vacuously", () => {
    // If the regex ever stops matching (a decorator reformatted, the routers
    // moved), every assertion below would pass by finding nothing. This is the
    // check that the check works.
    const routes = declaredDeleteRoutes()
    expect(routes.length).toBeGreaterThan(5)
    expect(routes).toContain("/devices/{device_id}")
  })

  /*
   * The page still names only paper deletion, not account deletion (§5's
   * `deletion` panel talks about a paper throughout and never claims an
   * account can be removed). Both halves of that distinction are asserted
   * against the backend, and the failure message is an instruction rather
   * than a diff, because the right response to this test going red is to
   * celebrate and then edit the page.
   */
  it("still has no account-deletion route, as the page implies by omission", () => {
    const suspicious = declaredDeleteRoutes().filter((r) => /account|^\/me\/?$|^\/users?\//.test(r))
    expect(
      suspicious,
      "an account-deletion route now exists. That is good news, and it means " +
        "the deletion panel on /data should say so: update " +
        "src/portals/marketing/dataHandling.ts before this ships.",
    ).toEqual([])
  })

  /*
   * Task 8 (paper deletion) built exactly the route the comment above warned
   * about: `DELETE /api/student/attempts/{attempt_id}` in
   * `lemely/web/routers/student_deletion.py`. This test used to assert no
   * such route existed and was inverted on Task 8's schedule; Task 15 is what
   * finally rewrote the panel copy to describe the route this test proves
   * exists.
   */
  it("now has the student deletion route in student_deletion.py", () => {
    const suspicious = declaredDeleteRoutes().filter((r) => /upload|scan|attempt/.test(r))
    expect(
      suspicious,
      "no scan/attempt deletion route was found in lemely/web/routers/*.py. " +
        "If student_deletion.py's DELETE route was renamed or moved, update " +
        "this test's expectation together with it.",
    ).not.toEqual([])

    const source = fs.readFileSync(
      path.join(repoRoot, "lemely/web/routers/student_deletion.py"),
      "utf8",
    )
    const routesInThatFile = Array.from(source.matchAll(/@router\.delete\(\s*\n?\s*"([^"]*)"/g)).map(
      (m) => m[1],
    )
    expect(routesInThatFile).toContain("/{attempt_id}")
  })

  /*
   * The page says a scan is stored in Google Cloud Storage and that an account
   * row holds no password. Both are properties of modules that could be
   * swapped without anybody thinking of this page, so they are named here.
   *
   * This guard has already earned itself once: the storage seam moved off
   * Supabase and this assertion is what caught the page still telling readers
   * their scans were kept there. Where someone's work is stored is a
   * disclosure, so the fix is always to correct the sentence, never to widen
   * the pattern until it passes.
   */
  it("still stores uploads through the Google Cloud Storage seam", () => {
    const source = fs.readFileSync(path.join(repoRoot, "lemely/io/storage.py"), "utf8")
    expect(source).toMatch(/Google Cloud Storage/)
    expect(allCopy).toMatch(/Google Cloud Storage/)
  })

  it("still keeps no password on the user row", () => {
    const source = fs.readFileSync(path.join(repoRoot, "lemely/db/models/users.py"), "utf8")
    expect(source).not.toMatch(/password/i)
    expect(allCopy).toMatch(/There is no password on it/)
  })
})

/*
 * Task 15: the disclosure page describes deletion truthfully.
 *
 * The plan's Step 1 draft asserted `dataHandlingSections` was a plain array
 * and, in the same draft, wrote `dataHandlingSections.deletion.hold` as if it
 * were not. The review amendment resolved that in favour of the array: the
 * "no way to delete" copy moved out of `dataHandlingSections` into its own
 * export from the start, and `deletion` replaces it, so every assertion here
 * reads `deletion` directly rather than a property that was never on the
 * array.
 */
describe("the disclosure page describes deletion truthfully — Task 15", () => {
  const serialised = JSON.stringify(dataHandlingSections) + JSON.stringify(deletion)

  it("no longer claims that nothing can be deleted", () => {
    expect(serialised).not.toContain("There is no way to delete any of this")
    expect(serialised).not.toContain("no retention machinery")
  })

  it("states the window, what goes, and what stays", () => {
    expect(serialised).toContain("30 days")
    expect(serialised).toMatch(/mark scheme/i) // kept (D2)
    expect(serialised).toMatch(/XP|streak/) // kept (D7)
  })

  it("describes the hold without naming a reason", () => {
    const hold = deletion.hold
    expect(hold).toMatch(/can't be deleted for up to 30 days/)
    expect(hold).not.toMatch(/plagiar|integrity|cheat|flag/i)
  })

  /*
   * `RETENTION_DAYS` in `lemely/core/deletion.py` is the one number behind
   * both the restore window and the integrity hold (its own module docstring
   * says so, deliberately, so the two can never drift apart). This page
   * cannot import a Python constant, so "30 days" here is a second literal
   * by construction; this test is what keeps it from silently drifting from
   * the first one if `RETENTION_DAYS` ever changes.
   */
  it("pins its 30-day window to RETENTION_DAYS, so the two cannot drift apart", () => {
    const source = fs.readFileSync(path.join(repoRoot, "lemely/core/deletion.py"), "utf8")
    const match = source.match(/^RETENTION_DAYS\s*=\s*(\d+)/m)
    expect(match, "RETENTION_DAYS not found in lemely/core/deletion.py").not.toBeNull()
    const days = match![1]
    expect(deletion.window).toContain(`${days} days`)
    expect(deletion.hold).toContain(`${days} days`)
  })

  it("says deletion covers every marking run of the scan (R7)", () => {
    expect(deletion.removes).toMatch(/every marking run/i)
  })

  it("names the teacher's review-withdrawn notification as a surviving record", () => {
    expect(deletion.keeps).toMatch(/review item was withdrawn/i)
  })

  it("says a teacher can delete their own console uploads on the same terms (R2)", () => {
    expect(deletion.window).toMatch(/grading console/i)
    expect(deletion.window).toMatch(/same 30-day terms/i)
  })

  it("says unsharing a paper from a class leaves the student's own copy untouched (D9)", () => {
    expect(deletion.window).toMatch(/unshare/i)
    expect(deletion.window).toMatch(/student's own copy is unchanged/i)
  })

  it("says a parent sees the student's live history and nothing about deletion", () => {
    expect(deletion.keeps).toMatch(/parent linked to the student/i)
    expect(deletion.keeps).toMatch(/nothing shown about a deletion/i)
  })

  /*
   * Task 17: the page's "a teacher who deletes a paper they uploaded through
   * the grading console works to the same 30-day terms" claim (Task 15) was
   * only true once Task 17's routes shipped. Same technique as the existing
   * student-deletion route guard above: read the Python router source
   * directly, so CI fails if the page ever promises a capability the code
   * lacks, rather than trusting a comment that says so.
   */
  it("has the teacher console delete/restore routes backing its grading-console claim", () => {
    expect(deletion.window).toMatch(/grading console/i)
    expect(deletion.window).toMatch(/same 30-day terms/i)

    const source = fs.readFileSync(
      path.join(repoRoot, "lemely/web/routers/teacher.py"),
      "utf8",
    )
    const deleteRoutes = Array.from(
      source.matchAll(/@router\.delete\(\s*\n?\s*"([^"]*)"/g),
    ).map((m) => m[1])
    const restoreRoutes = Array.from(
      source.matchAll(/@router\.post\(\s*\n?\s*"([^"]*)"/g),
    ).map((m) => m[1])
    expect(
      deleteRoutes,
      "no DELETE /papers/{paper_id} route found in lemely/web/routers/teacher.py — " +
        "either the route was renamed/moved, or the grading-console claim in " +
        "dataHandling.ts is no longer true and must be walked back.",
    ).toContain("/papers/{paper_id}")
    expect(
      restoreRoutes,
      "no POST /papers/{paper_id}/restore route found in lemely/web/routers/teacher.py.",
    ).toContain("/papers/{paper_id}/restore")
  })

  it("no longer imports the old notYetBuilt export", () => {
    const source = fs.readFileSync(
      path.resolve(__dirname, "../../src/portals/marketing/dataHandling.ts"),
      "utf8",
    )
    expect(source).not.toMatch(/\bnotYetBuilt\b/)
  })
})

/*
 * The tutoring marketplace sentences (SPEC section f, release groupings 1, 2 and 4,
 * plus reviews and reports from groupings 3 and 5).
 *
 * Same rule as every other panel: a sentence here is a statement about a named
 * module, and the module is named in a comment beside it. The tests below do
 * three things the copy alone cannot:
 *
 *   1. They read the source comment of each section and check that every file
 *      it cites exists, so a renamed module turns this red rather than leaving
 *      a comment that points at nothing.
 *   2. They pin each number in the copy to the Python constant behind it.
 *   3. They count what they scanned, so an empty array cannot pass.
 */
describe("the tutoring sentences carry a source and match the code: SPEC f", () => {
  const read = (p: string) => fs.readFileSync(path.join(repoRoot, p), "utf8")
  const section = (heading: string) => {
    const found = tutoringSections.find((s) => s.heading === heading)
    expect(found, `no tutoring section headed "${heading}"`).toBeDefined()
    return found!
  }

  /** `NAME: Final = 5` or `NAME: Final[int] = 5`. */
  const pyInt = (file: string, name: string): number => {
    const m = read(file).match(new RegExp(`^${name}\\s*(?::[^=\\n]+)?=\\s*(\\d+)\\s*(?:#.*)?$`, "m"))
    expect(m, `${name} not found in ${file}`).not.toBeNull()
    return Number(m![1])
  }
  /** `NAME: Final = timedelta(days=90)`: returns the whole number and its unit. */
  const pyDelta = (file: string, name: string): { n: number; unit: string } => {
    const m = read(file).match(
      new RegExp(`^${name}\\s*(?::[^=\\n]+)?=\\s*timedelta\\((hours|days)=(\\d+)\\)`, "m"),
    )
    expect(m, `${name} not found in ${file}`).not.toBeNull()
    return { n: Number(m![2]), unit: m![1] }
  }
  const pyDefault = (file: string, field: string): number => {
    const m = read(file).match(new RegExp(`${field}:\\s*int\\s*=\\s*Field\\(default=(\\d+)`))
    expect(m, `${field} default not found in ${file}`).not.toBeNull()
    return Number(m![1])
  }

  const EXPECTED_HEADINGS = [
    "Tutors on the public directory",
    "Documents a tutor uploads",
    "Booking a session",
    "Notes between a student and a tutor",
    "Emails about bookings",
    "Reviews of a tutor",
    "Parent links and class joins",
    "Sharing your progress with a tutor",
    "Past-student results and counting",
    "Reports and blocks",
    "Teachers who can see your progress through a class",
  ]

  it("has one section for each grouping, so it cannot pass by being empty", () => {
    expect(tutoringSections.map((s) => s.heading)).toEqual(EXPECTED_HEADINGS)
    for (const s of tutoringSections) expect(s.body.length).toBeGreaterThan(80)
  })

  /*
   * Walks the source text, not the module: a comment is not visible at runtime.
   * Each section's comment is the text between the previous section's closing
   * `},` and its own `body:`.
   */
  const sourceCommentsByHeading = (): Map<string, string> => {
    const source = fs.readFileSync(
      path.resolve(__dirname, "../../src/portals/marketing/dataHandling.ts"),
      "utf8",
    )
    const start = source.indexOf("export const tutoringSections")
    expect(start).toBeGreaterThan(-1)
    const end = source.indexOf("\n]\n", start)
    const block = source.slice(start, end)
    const out = new Map<string, string>()
    for (const m of block.matchAll(/heading:\s*"([^"]+)",([\s\S]*?)\n\s*body:/g)) {
      out.set(m[1], m[2])
    }
    return out
  }

  it("gives every section a comment that cites at least one file that exists", () => {
    const comments = sourceCommentsByHeading()
    expect(comments.size).toBe(EXPECTED_HEADINGS.length)
    let cited = 0
    for (const heading of EXPECTED_HEADINGS) {
      const comment = comments.get(heading) ?? ""
      const files = Array.from(
        comment.matchAll(/\b((?:lemely|web)\/[\w./-]+\.(?:py|ts|tsx))\b/g),
        (m) => m[1],
      )
      expect(files.length, `"${heading}" cites no source file`).toBeGreaterThan(0)
      for (const f of files) {
        expect(fs.existsSync(path.join(repoRoot, f)), `"${heading}" cites ${f}, which does not exist`).toBe(true)
        cited += 1
      }
    }
    expect(cited).toBeGreaterThanOrEqual(EXPECTED_HEADINGS.length)
  })

  it("uses neither of the two words the tutoring copy rule bans", () => {
    expect(tutoringCopy).not.toMatch(/\bimprovement\b/i)
    expect(tutoringCopy).not.toMatch(/\bverified\b/i)
  })

  it("promises no price, payment or fee handling", () => {
    expect(tutoringCopy).not.toMatch(/[$£]|\bEGP\b|\bpay(s|ment|ments)?\b/i)
  })

  it("says what 'documents seen' is not", () => {
    const body = section("Documents a tutor uploads").body
    expect(body).toMatch(/not an identity check/i)
    expect(body).toMatch(/criminal-records check/i)
  })

  it("pins the evidence limits to the code", () => {
    const body = section("Documents a tutor uploads").body
    const files = pyInt("lemely/db/tutor_evidence_repo.py", "MAX_EVIDENCE_FILES")
    expect(body).toContain(`${files} files`)
    expect(read("lemely/io/evidence_files.py")).toMatch(/^MAX_EVIDENCE_BYTES: Final = 10 \* 1024 \* 1024/m)
    expect(body).toContain("10 MiB")
    const ttl = pyDefault("lemely/runtime/config.py", "tutor_evidence_signed_url_ttl_seconds")
    expect(body).toContain(`${ttl} seconds`)
  })

  it("pins the 24-hour cancel cutoff to CANCEL_CUTOFF", () => {
    const { n, unit } = pyDelta("lemely/core/booking.py", "CANCEL_CUTOFF")
    expect({ n, unit }).toEqual({ n: 24, unit: "hours" })
    expect(section("Booking a session").body).toContain(`${n} ${unit}`)
  })

  it("pins the note window to NOTE_POST_GRACE", () => {
    const { n, unit } = pyDelta("lemely/core/booking.py", "NOTE_POST_GRACE")
    expect(section("Notes between a student and a tutor").body).toContain(`${n} ${unit}`)
  })

  it("pins the opt-out delay to the edge worker's PUBLIC_CACHE_TTL_SECONDS", () => {
    const ttl = Number(
      read("web/worker/robots.ts").match(/^export const PUBLIC_CACHE_TTL_SECONDS\s*=\s*(\d+)\s*;?\s*$/m)?.[1],
    )
    expect(Number.isInteger(ttl) && ttl > 0, "PUBLIC_CACHE_TTL_SECONDS not found in web/worker/robots.ts").toBe(true)
    // The page promises "within a minute", which holds only while the edge keeps a card at most 60 seconds.
    expect(ttl).toBeLessThanOrEqual(60)
    const heading = "Tutors on the public directory"
    expect(section(heading).body).toContain("within a minute")
    // The source comment beside the sentence quotes the same number.
    expect(sourceCommentsByHeading().get(heading)).toContain(`PUBLIC_CACHE_TTL_SECONDS\` (${ttl})`)
  })

  it("says linked parents can read notes and that staff read them only on a report", () => {
    const body = section("Notes between a student and a tutor").body
    expect(body).toMatch(/linked parents can read/i)
    expect(body).toMatch(/only when (someone|a note) (reports|is reported)/i)
    expect(body).toMatch(/logged/i)
  })

  it("pins the email cap and the mock-provider behaviour", () => {
    const body = section("Emails about bookings").body
    const cap = pyDefault("lemely/runtime/config.py", "email_daily_cap")
    expect(body).toContain(`${cap} a day`)
    expect(body).toMatch(/skipped/i)
    expect(body).toMatch(/not retried|never retried|once/i)
    expect(read("lemely/web/tutoring_email.py")).toMatch(/last_error='mock_provider'/)
  })

  it("pins the review rules to the rating constants", () => {
    const body = section("Reviews of a tutor").body
    const edit = pyDelta("lemely/core/tutor_ratings.py", "REVIEW_EDIT_WINDOW")
    expect(body).toContain(`${edit.n} ${edit.unit}`)
    expect(body).toMatch(/before .* (public|others see)/i)
    expect(body).toMatch(/A student/)
  })

  it("pins the parent cap to MAX_LINKED_PARENTS", () => {
    const body = section("Parent links and class joins").body
    const cap = pyInt("lemely/db/parent_repo.py", "MAX_LINKED_PARENTS")
    expect(body).toContain(`${cap} linked parents`)
  })

  it("says a student alone grants access, all subjects, derived data, and every look is logged", () => {
    const body = section("Sharing your progress with a tutor").body
    expect(body).toMatch(/only the student/i)
    expect(body).toMatch(/all subjects/i)
    expect(body).toMatch(/never see answer sheets/i)
    expect(body).toMatch(/every time a tutor looks/i)
    expect(body).toMatch(/linked parents can see who/i)
  })

  it("pins the outcome rules to the core constants", () => {
    const body = section("Past-student results and counting").body
    const k = pyInt("lemely/core/tutor_outcomes.py", "OUTCOME_K_MIN")
    expect(body).toContain(`${k} students`)
    const hold = pyDelta("lemely/core/tutor_outcomes.py", "OPT_CHANGE_HOLD")
    expect(body).toContain(`${hold.n} ${hold.unit}`)
    const during = pyDelta("lemely/core/tutor_outcomes.py", "DURING_WINDOW")
    expect(body).toContain(`${during.n} ${during.unit}`)
    expect(body).toMatch(/is counted unless they opt out/i)
    expect(body).toMatch(/automatic marking/i)
    expect(body).toMatch(/does not show what the tutor caused/i)
  })

  it("names the class-teacher path and the student's way out", () => {
    const body = section("Teachers who can see your progress through a class").body
    expect(body).toMatch(/class/i)
    expect(body).toMatch(/leave/i)
  })

  it("says reports are read by staff and blocks end sharing", () => {
    const body = section("Reports and blocks").body
    expect(body).toMatch(/report/i)
    expect(body).toMatch(/block/i)
    expect(body).toMatch(/sharing ends|ends sharing|ends the sharing/i)
  })
})
