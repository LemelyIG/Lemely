import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"

import { appRoutes } from "@/routes"
import { dataHandlingRoute } from "@/portals/marketing"
import {
  dataHandlingClose,
  dataHandlingIntro,
  dataHandlingSections,
  notYetBuilt,
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
 *   2. The product changes and the page does not. The last panel says there is
 *      no way to delete an account or a scan. The day somebody builds one, that
 *      sentence becomes a lie told to exactly the reader who cares most, so the
 *      test below reads the backend rather than this page and fails when a
 *      deletion route appears.
 *
 * The second is the one worth the effort. This project's recurring finding is
 * that a comment describing an intention is not evidence the code has it, and a
 * page describing the backend is the same shape: it is true on the day it is
 * written and nothing notices when it stops being.
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

/** Every sentence a reader can see on the page, flattened. */
const allCopy = [
  ...Object.values(dataHandlingIntro),
  ...dataHandlingSections.flatMap((s) => [s.heading, s.body]),
  ...Object.values(notYetBuilt),
  dataHandlingClose,
].join("\n")

describe("the data page is public and reachable — P6.5", () => {
  it("mounts /data at the top level", () => {
    expect(appRoutes.map((r) => r.path)).toContain("/data")
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
    const route = appRoutes.find((r) => r.path === "/data")
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
    // A retention period is the single most common thing a page like this
    // states, and this product has no retention machinery at all: nothing in
    // `lemely/` purges, expires or anonymises anything. Naming a number of days
    // would be inventing the feature in prose.
    [/\b\d+\s*(days?|months?|years?)\b/i, "there is no retention rule to state"],
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
   * The panel says "Lemely has no account deletion and no way to remove a scan
   * you have uploaded". Both halves are asserted against the backend, and the
   * failure message is an instruction rather than a diff, because the right
   * response to this test going red is to celebrate and then edit the page.
   */
  it("still has no account-deletion route, as the page says", () => {
    const suspicious = declaredDeleteRoutes().filter((r) => /account|^\/me\/?$|^\/users?\//.test(r))
    expect(
      suspicious,
      "an account-deletion route now exists. That is good news, and it means the " +
        '"Not built yet" panel on /data is now false: update ' +
        "src/portals/marketing/dataHandling.ts before this ships.",
    ).toEqual([])
  })

  it("still has no upload-deletion route, as the page says", () => {
    const suspicious = declaredDeleteRoutes().filter((r) => /upload|scan|attempt/.test(r))
    expect(
      suspicious,
      "a scan or attempt can now be deleted. Update the \"Not built yet\" panel " +
        "on /data (src/portals/marketing/dataHandling.ts) to say so.",
    ).toEqual([])
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
