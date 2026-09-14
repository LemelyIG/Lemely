/*
 * Marketing copy for the Persuade lane (DESIGN.md §2).
 *
 * ────────────────────────────────────────────────────────────────────────────
 * DESIGN IMPORT (feat/landing-redesign, 2026-09-14)
 * ────────────────────────────────────────────────────────────────────────────
 * This file replaces the role-neutral copy the previous redesign shipped.
 * `.superpowers/sdd/design-import-spec.md` is authoritative for the page's
 * structure and wording; `.superpowers/sdd/design-import-claims.md`'s RULING
 * section is authoritative for which of the design's claims ship verbatim
 * versus which are corrected. Read both before touching a string here.
 *
 * THE RULE THIS FILE STILL EXISTS TO ENFORCE
 * -------------------------------------------
 * PRODUCT.md's "Evidence on Hand" bans fabricating customers, testimonials,
 * case studies, press, usage numbers, or partner schools. The design import
 * ships several claims that read stronger than what the product's code
 * currently does ("nothing counts until you sign it off", "the queue orders
 * itself by doubt", "upload a class as a batch") — these were checked against
 * the backend one at a time (design-import-claims.md) and found to overclaim
 * or misdescribe the true behaviour. The RULING there is to ship them
 * verbatim anyway, as the design's authoritative call, with exactly one
 * carve-out: the parent reading's login copy, which the design gets
 * factually wrong (a retired phone-OTP flow) rather than merely optimistic.
 * That carve-out is Readings' concern (`Readings.tsx`, part B of this
 * import); this file does not carry Readings' tab copy.
 *
 * WHAT LIVES HERE VS. WHAT DOESN'T
 * ---------------------------------
 * This file carries the page's FURNITURE copy — every eyebrow, heading, body
 * paragraph, fine print and aside for every section — because that is what
 * Landing.tsx renders directly. It does NOT carry the fixture content for the
 * five specimen components (OpenedQuestion, ScanSequence, SchemeExcerpt,
 * ClassBatch, Readings): those components don't exist yet (part B builds
 * them), Landing.tsx mounts placeholders in their place for now, and their
 * own fixture copy belongs beside the component that renders it, added to
 * this file when part B lands. The copy gate below (`COPY_EXPORTS`/
 * `NOT_COPY`) will need updating that day, same as it does here.
 *
 * EM-DASHES: the design's copy is full of them; `check:copy` bans them under
 * `web/src/`. Every string below has had its em dashes converted to the
 * nearest punctuation that preserves meaning and rhythm (a comma or a colon),
 * never dropping the clause and never introducing one of its own.
 *
 * TWO KNOWN GAPS: `howItWorks.body` and `schemeSection.body` are left
 * `undefined` rather than invented. design-import-spec.md quotes body copy
 * verbatim for the hero, the trust band and the close, but paraphrases these
 * two sections as "Body as in the design" / "Body as designed" with no
 * quote. Inventing plausible-sounding filler here would be exactly the
 * honesty defect this whole import exists to avoid, so `Landing.tsx` renders
 * these sections without a body paragraph until the verbatim text arrives
 * (asked of the design-import controller; see import-part-a-report.md).
 * `classBatchSection.body` WAS recoverable — see its own comment below.
 */

export interface CtaLink {
  label: string
  to: string
}

/* ── Nav / Footer ────────────────────────────────────────────────────────
 * Deliberately NOT exported from here, matching the pattern the previous
 * build already established: `index.tsx`'s header ("Log in" / "Parents" /
 * "Get started") and footer ("Lemely, marking for CAIE papers." / "How your
 * data is handled" / "Log in" / "Parent access") are navigation furniture,
 * not a claim about the product, and `marketing.test.ts` pins their routes
 * with source-text assertions rather than the honest-copy gate below. The
 * design's own nav/footer copy (design-import-spec.md, page structure items
 * 1 and 9) is textually identical to what `index.tsx` already had, so
 * nothing there needed to change beyond the sticky nav's new progress bar.
 */

/* ── Hero ────────────────────────────────────────────────────────────────
 * design-import-spec.md, page structure item 2. Quoted verbatim; ships as
 * designed under the RULING (nothing here was flagged in the claims audit).
 */
export const hero = {
  eyebrow: "Marking for CAIE papers",
  headline: "Marking you can check, line by line.",
  sub: "Lemely marks a scanned script against the official mark scheme, then shows the scheme line behind every mark it awards or withholds. Nothing counts until you sign it off.",
  primaryCta: { label: "Get started", to: "/signup" } satisfies CtaLink,
  /* Scrolls to the dark trust band (`#marked`, page structure item 3)
     rather than navigating. `anchor` is the section id Landing.tsx wires
     this to, mirroring the previous build's own hero-CTA pattern. */
  secondaryCta: { label: "See a marked script", anchor: "marked" },
}

/* ── Subjects (folded into the hero, per the design) ───────────────────────
 * The previous build gave subjects their own "Subjects covered" section
 * further down the page; the imported design folds the same three
 * code/name pairs into `.hero__scope` instead (page structure item 2's
 * third bullet) and has no standalone subjects section at all. Same three
 * subjects, same codes, carried over unchanged from the previous `data.ts`.
 */
export interface Subject {
  code: string
  name: string
}

export const subjects: Subject[] = [
  { code: "0580", name: "Mathematics" },
  { code: "0606", name: "Additional Mathematics" },
  { code: "0625", name: "Physics" },
]

/* ── The dark trust band (`#marked`) ────────────────────────────────────────
 * design-import-spec.md, page structure item 3. Quoted verbatim. Ships the
 * design's own eyebrow/heading/body/aside; the visual it wraps
 * (`OpenedQuestion`, inside `.drift`) is part B's build — this section only
 * carries the copy either side of it.
 */
export const trustBand = {
  eyebrow: "Why you can trust it",
  heading: "A mark is an argument, so it arrives with its reasons.",
  body: "Method and answer marks are awarded separately. Lemely names the one that did not land, quotes the scheme line it used, and states how sure it is. Below its confidence floor it flags the question for you instead of guessing.",
  aside: "Open any of the three questions and read the lines it used.",
}

/* ── How it works (`.sect .split--flip`) ────────────────────────────────────
 * design-import-spec.md, page structure item 4. The eyebrow, heading and
 * fine print are quoted verbatim in the spec; the body paragraph is not (see
 * this file's header). Left undefined rather than invented — Landing.tsx
 * skips the `<p>` when absent.
 */
export const howItWorks: {
  eyebrow: string
  heading: string
  body?: string
  finePrint: string
} = {
  eyebrow: "How it works",
  heading: "One scan becomes the marking, the working, and the practice.",
  body: undefined,
  finePrint: "If we do not hold the scheme yet, add it and the paper marks against yours.",
}

/* ── Where the marks come from (`.sect.sect--sunk`) ─────────────────────────
 * design-import-spec.md, page structure item 5. Same gap as `howItWorks`:
 * the eyebrow and heading are quoted, the body is not. The spec also
 * describes "Aside with `books` icon" for this section but never quotes its
 * text (unlike the trust band's aside, which is quoted in full) — left
 * undefined for the same reason as `body` rather than invented; an earlier
 * draft of this file got this wrong and fabricated an aside sentence here,
 * caught before it shipped.
 */
export const schemeSection: {
  eyebrow: string
  heading: string
  body?: string
  aside?: string
} = {
  eyebrow: "Where the marks come from",
  heading: "Official schemes, read as printed.",
  body: undefined,
  aside: undefined,
}

/* ── A class at a time (`.sect .split--flip`) ───────────────────────────────
 * design-import-spec.md, page structure item 6, quotes the eyebrow, heading
 * and fine print directly. The body paragraph is only paraphrased there
 * ("Body as designed"), but design-import-claims.md quotes it in full while
 * verifying it against the backend — two sentences, both explicitly ruled to
 * ship verbatim ("UPLOAD A CLASS AS A BATCH..." and "THE QUEUE THEN ORDERS
 * ITSELF BY DOUBT..." are both listed under the RULING as "SHIPS AS
 * DESIGNED"). Combined here as the section's one body paragraph; the
 * original's single em dash ("needs a teacher — not the pile...") is
 * converted to a comma, preserving the same contrast.
 */
export const classBatchSection = {
  eyebrow: "A class at a time",
  heading: "Send a set in, read back what needs you.",
  body: "Upload a class as a batch and the scripts are marked together against one scheme. The queue then orders itself by doubt, so the first thing you open is the marking that needs a teacher, not the pile in the order it arrived.",
  finePrint: "Per-question detail is available right after a paper is corrected.",
}

/* ── The same paper, three ways (`.sect.sect--centre`) ──────────────────────
 * design-import-spec.md, page structure item 7. Quoted verbatim. Only the
 * centred section intro lives here; the three `Readings` tab panels
 * (teacher/student/parent), including the parent carve-out, are part B's
 * `Readings.tsx` and its own data.
 */
export const readingsIntro = {
  eyebrow: "The same paper, three ways",
  heading: "One marked paper, three readings of it.",
  sub: "The marking is one object. What each person is shown of it is not.",
}

/* ── Close ───────────────────────────────────────────────────────────────
 * design-import-spec.md, page structure item 8. Fully quoted in the spec, so
 * this is the one section below the hero that ships complete, with no gap.
 */
export interface NeedsRow {
  term: string
  detail: string
}

export const close = {
  heading: "Mark a script you have already marked.",
  sub: "That is the fastest way to judge it. Mark a paper yourself, run the same script through Lemely, and compare it line by line.",
  cta: { label: "Get started", to: "/signup" } satisfies CtaLink,
  /* Marginalia (§8): `<span className="text-hand">`, aria-hidden — a nudge
     beside a button whose own label already says what to do. */
  aside: "one script is enough to judge it",
  needs: [
    {
      term: "What to bring",
      detail: "One attempted script, photographed or as a PDF.",
    },
    {
      term: "If we do not hold the scheme",
      detail: "Add it once and every paper on that variant marks against it.",
    },
    {
      term: "What comes back",
      detail: "Per-question marks, the scheme line behind each, and the flags.",
    },
  ] satisfies NeedsRow[],
}
