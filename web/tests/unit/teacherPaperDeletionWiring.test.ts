import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { functionBody, stripComments } from "./support/jsxSource"

/*
 * Source-text gates for teacher-console paper deletion (Task 17) and the
 * fixes its review asked for. Neither `Grading.tsx` nor the hooks are
 * mountable under this suite's DOM-less Node environment (D3.20) — same
 * reasoning `recentlyDeletedWiring.test.ts` (the student-side sibling of
 * this file) records for its own gates.
 *
 * What the first group specifically guards: a real keyboard-accessibility
 * regression the review caught. `DeletePaperControl` used to render *inside*
 * `PaperCard`'s own `role="button" tabIndex={0} onKeyDown={...}` open
 * target, wrapped in an `aria-hidden="true"` div meant to stop a portaled
 * modal click from bubbling into it. That structure had two independent
 * defects: a keydown on the focused delete `<button>` (a genuine DOM
 * descendant, not a portal) still bubbled to the card's own `onKeyDown` and
 * fired `onOpen()` too, and `aria-hidden="true"` hid an *interactive*
 * control from assistive tech regardless of whether it also hid the portal
 * (the portal's actual DOM subtree lives at `document.body`, so it hid
 * nothing of the modal — it hid the button instead, before the modal even
 * opened, since the wrapper was unconditionally rendered). The fix is
 * structural — the two controls are siblings now, neither nested in the
 * other — so these gates check the structure, not just the symptom.
 */

const ROOT = join(import.meta.dirname, "..", "..")

function readSource(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

describe("Grading.tsx — the delete control is not trapped inside the open control", () => {
  const source = readSource("src/portals/teacher/screens/Grading.tsx")

  it("PaperCard's open target carries no onKeyDown of its own", () => {
    // A real <button> needs none — native Enter/Space activation is exactly
    // what made the old manual onKeyDown (and the bubbling it caused)
    // unnecessary in the first place.
    const body = functionBody(source, "PaperCard")
    expect(body).not.toMatch(/onKeyDown/)
  })

  it("PaperCard's open target is a real <button>, not a role=\"button\" div", () => {
    const body = functionBody(source, "PaperCard")
    expect(body).toMatch(/<button\s/)
    expect(body).not.toMatch(/role="button"/)
  })

  it("the visible focus ring lives on the container, as a box-shadow, not an outline", () => {
    // Review finding, third pass: index.css's global `:focus-visible` rule
    // (~:776) sits outside any `@layer`, so it overrides every Tailwind
    // `focus-visible:outline-*` utility app-wide — an *inset* offset
    // (second pass) lost to it exactly as the outset one (first pass) did,
    // because the class string never controlled the computed outline to
    // begin with. A `box-shadow` ring on the container sidesteps the
    // global rule entirely (it sets `outline`, never `box-shadow`) without
    // editing that pre-existing, app-wide rule. Source text alone cannot
    // prove the ring is *visible* — see the "Fix 3" section of
    // .superpowers/sdd-deletion/task-17-report.md for the computed-style
    // proof (a real browser, tabbed via the keyboard, reading
    // getComputedStyle) — but it can prove the outline approach is gone
    // and the box-shadow approach is present.
    const body = functionBody(source, "PaperCard")
    expect(body).not.toMatch(/focus-visible:outline/)
    expect(body).toMatch(/has-\[\[data-open-trigger\]:focus-visible\]:ring-2/)
    expect(body).toMatch(/has-\[\[data-open-trigger\]:focus-visible\]:ring-focus-ring/)
  })

  it("the ring selector names the open button specifically, not any focused descendant", () => {
    // A bare `has-[:focus-visible]` would also fire when the delete
    // button (a sibling, but still a direct child of the same container)
    // is focused, stacking this ring on top of that button's own separate
    // one. `data-open-trigger` on the open button, referenced from the
    // container's selector, is what keeps the two rings from doubling up.
    const body = functionBody(source, "PaperCard")
    expect(body).toMatch(/data-open-trigger=""/)
  })

  it("carries a forced-colors outline for Windows High Contrast, where box-shadow does not render (WCAG 2.4.7)", () => {
    const body = functionBody(source, "PaperCard")
    expect(body).toMatch(/forced-colors:has-\[\[data-open-trigger\]:focus-visible\]:outline\b/)
    expect(body).toMatch(/forced-colors:has-\[\[data-open-trigger\]:focus-visible\]:outline-2/)
  })

  it("the hover lift lives on the container, not the clipped button, and is guarded for touch", () => {
    // Same review pass, Minor 1: `hover:-translate-y-0.5` on the button
    // shifted only the button's own content inside the container's fixed
    // frame — clipping the thumbnail's top edge and leaving a gap at the
    // bottom. `has-[:hover]` on the container moves the whole card as one
    // box instead, since a container's `overflow-hidden` clips its
    // children, never its own transform. `[@media(hover:hover)]` guards
    // it for touch — unlike the kit's own `hover:` utility, arbitrary
    // `has-[:hover]` carries no such guard by default, so a tap could
    // otherwise leave the card stuck lifted after the finger lifts.
    const body = functionBody(source, "PaperCard")
    expect(body).toMatch(/\[@media\(hover:hover\)\]:has-\[:hover\]:-translate-y-0\.5/)
    expect(body).not.toMatch(/\bhover:-translate-y-0\.5/)
  })

  it("DeletePaperControl renders after the open button closes, as its sibling", () => {
    // A crude but effective structural proof: if the delete control's own
    // render were still nested inside the open button's JSX, the button's
    // closing tag could not appear in the source before it.
    const body = functionBody(source, "PaperCard")
    const buttonCloseIndex = body.indexOf("</button>")
    const deleteControlIndex = body.indexOf("<DeletePaperControl")
    expect(buttonCloseIndex).toBeGreaterThan(-1)
    expect(deleteControlIndex).toBeGreaterThan(buttonCloseIndex)
  })

  it("DeletePaperControl's own render carries no aria-hidden on an interactive control", () => {
    const body = functionBody(source, "DeletePaperControl")
    expect(body).not.toMatch(/aria-hidden/)
  })

  it("DeletePaperControl's trigger needs no stopPropagation — it has no ancestor onClick to escape", () => {
    const body = functionBody(source, "DeletePaperControl")
    expect(body).not.toMatch(/stopPropagation/)
  })

  it("the delete trigger's tap target meets the 44px floor (BUILD/REDESIGN-MISSION.md)", () => {
    const body = functionBody(source, "DeletePaperControl")
    expect(body).toMatch(/min-w-11/)
    expect(body).toMatch(/min-h-11/)
  })

  it("names the real retention window rather than a vague 'for a while'", () => {
    const body = functionBody(source, "DeletePaperControl")
    expect(body).toMatch(/RETENTION_DAYS/)
    expect(body).not.toMatch(/for a while/)
  })
})

describe("useTeacherApi.ts — useDeleteTeacherPaper refreshes from the server", () => {
  const source = readSource("src/lib/hooks/useTeacherApi.ts")

  it("invalidates the console list's own query key rather than trusting an optimistic removal", () => {
    const body = functionBody(source, "useDeleteTeacherPaper")
    expect(body).toContain("invalidateQueries")
    expect(body).toMatch(/\["teacher", "papers"\]/)
  })

  it("also invalidates the deleted list, the surface the row moves to", () => {
    const body = functionBody(source, "useDeleteTeacherPaper")
    expect(body).toMatch(/deletedTeacherPapersKey/)
  })

  it("also invalidates the review queue, so a withdrawn item stops showing there", () => {
    const body = functionBody(source, "useDeleteTeacherPaper")
    expect(body).toMatch(/\["teacher", "review"\]/)
  })

  it("also invalidates the overview, so the 'Need your eyes' count stops being stale", () => {
    const body = functionBody(source, "useDeleteTeacherPaper")
    expect(body).toMatch(/\["teacher", "overview"\]/)
  })

  it("useRestoreTeacherPaper invalidates the same review-queue and overview surfaces", () => {
    const body = functionBody(source, "useRestoreTeacherPaper")
    expect(body).toMatch(/\["teacher", "review"\]/)
    expect(body).toMatch(/\["teacher", "overview"\]/)
  })
})

describe("unshare/reshare hooks — the review queue moves with them (R3)", () => {
  const source = readSource("src/lib/hooks/useTeacherApi.ts")

  it("useUnshareClassPaper invalidates the review queue prefix", () => {
    const body = functionBody(source, "useUnshareClassPaper")
    expect(body).toMatch(/\["teacher", "review"\]/)
  })

  it("useReshareClassPaper invalidates the review queue prefix", () => {
    const body = functionBody(source, "useReshareClassPaper")
    expect(body).toMatch(/\["teacher", "review"\]/)
  })

  it("neither hook invalidates the papers key separately — the class prefix already covers it", () => {
    const unshareBody = functionBody(source, "useUnshareClassPaper")
    const reshareBody = functionBody(source, "useReshareClassPaper")
    expect(unshareBody).not.toMatch(/"class", classId, "papers"/)
    expect(reshareBody).not.toMatch(/"class", classId, "papers"/)
  })
})

describe("reviewWithdrawn's showTeacherOnly prop — only the teacher mount passes it", () => {
  it("teacher/index.tsx passes showTeacherOnly", () => {
    const source = readSource("src/portals/teacher/index.tsx")
    expect(source).toContain("<NotificationSettingsSection showTeacherOnly />")
  })

  it("student/index.tsx does not", () => {
    const source = readSource("src/portals/student/index.tsx")
    expect(source).toContain("<NotificationSettingsSection />")
    expect(source).not.toMatch(/NotificationSettingsSection[^>]*showTeacherOnly/)
  })

  it("the top-level /settings/notifications lane (parent, admin) does not", () => {
    const source = readSource("src/portals/settings/NotificationSettings.tsx")
    expect(source).toContain("<NotificationSettingsSection />")
    const body = functionBody(source, "NotificationSettings")
    expect(body).not.toMatch(/showTeacherOnly/)
  })
})
