import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { postLoginTarget } from "@/lib/auth/postLoginTarget"

/*
 * Packet B2a · where `Login.tsx` sends a reader after a successful sign-in.
 * `next` (an explicit `?next=`, e.g. from `RequireAuth`'s redirect or a
 * "sign in to continue" link) wins over `from`. Failing that, `from` — the
 * location `RequireAuth` was guarding when it bounced a dead session to
 * `/login` — is used instead. Both `next` and `from` are honoured only when
 * they are inside the role's own portal, so a teacher account signing back
 * in from a stale `/student/...` bookmark (or a crafted `next`/`from`) does
 * not land inside another role's portal. Both are re-validated through
 * `safeNextPath` here, same as every other reader of a `?next=`/
 * `state.from` value (`nextPath.ts`).
 */

describe("postLoginTarget", () => {
  it("next wins over everything else", () => {
    expect(
      postLoginTarget({ next: "/student/flashcards/abc", from: "/teacher", role: "student" }),
    ).toBe("/student/flashcards/abc")
  })

  it("falls back to from when next is absent, when from is inside the role's portal", () => {
    expect(
      postLoginTarget({ next: null, from: "/student/classes", role: "student" }),
    ).toBe("/student/classes")
  })

  it("ignores a from outside the role's portal and falls back to the portal home", () => {
    expect(
      postLoginTarget({ next: null, from: "/teacher/grading", role: "student" }),
    ).toBe("/student")
  })

  it("falls back to the portal home when neither next nor from is present", () => {
    expect(postLoginTarget({ next: null, from: undefined, role: "teacher" })).toBe("/teacher")
  })

  it("rejects an unsafe next (open-redirect shape) and falls back", () => {
    expect(
      postLoginTarget({ next: "//evil.example", from: null, role: "student" }),
    ).toBe("/student")
  })

  it("rejects a non-string from", () => {
    expect(
      postLoginTarget({ next: null, from: { pathname: "/student" }, role: "student" }),
    ).toBe("/student")
  })

  it("resolves the portal home per role", () => {
    expect(postLoginTarget({ next: null, from: null, role: "parent" })).toBe("/parent")
    expect(postLoginTarget({ next: null, from: null, role: "school_admin" })).toBe("/school")
    expect(postLoginTarget({ next: null, from: null, role: "platform_admin" })).toBe("/platform")
  })

  it("ignores a next outside the role's portal and falls back to the portal home", () => {
    expect(
      postLoginTarget({ next: "/platform/schools", from: null, role: "student" }),
    ).toBe("/student")
  })
})

/*
 * T27 · G-17's "Sign in to book" carries `?next=/student/tutors/{id}` because the public
 * page cannot know who will sign in. A parent lands on the parent's page for the same
 * tutor; the mapping lives in `postLoginTarget` itself, so these tests go through it.
 */
describe("postLoginTarget · a parent following G-17's 'Sign in to book'", () => {
  const ID = "0f8fad5b-d9cb-469f-a165-70867728950e"

  it("maps the student's tutor page to the parent's page for the same tutor", () => {
    expect(postLoginTarget({ next: `/student/tutors/${ID}`, from: undefined, role: "parent" })).toBe(
      `/parent/tutors/${ID}`,
    )
  })

  it("leaves a student's own tutor page alone", () => {
    expect(postLoginTarget({ next: `/student/tutors/${ID}`, from: undefined, role: "student" })).toBe(
      `/student/tutors/${ID}`,
    )
  })

  it("does not map the student's booking step: a parent lands on the parent home", () => {
    expect(postLoginTarget({ next: `/student/tutors/${ID}/book`, from: undefined, role: "parent" })).toBe("/parent")
  })

  it("does not map a segment that is not a tutor id", () => {
    expect(postLoginTarget({ next: "/student/tutors/not-a-uuid", from: undefined, role: "parent" })).toBe("/parent")
    expect(postLoginTarget({ next: "/student/tutors/..%2F..", from: undefined, role: "parent" })).toBe("/parent")
  })

  it("still rejects open-redirect shapes for a parent", () => {
    for (const next of [
      "//evil.example",
      `//evil.example/student/tutors/${ID}`,
      `https://evil.example/student/tutors/${ID}`,
      `/\\evil.example`,
    ]) {
      expect(postLoginTarget({ next, from: undefined, role: "parent" }), next).toBe("/parent")
    }
  })

  it("keeps the Login bundle small: the mapping sits in a module with no imports", () => {
    const WEB = join(import.meta.dirname, "..", "..")
    const target = readFileSync(join(WEB, "src/lib/auth/postLoginTarget.ts"), "utf8")
    expect(target).toMatch(/from "@\/lib\/tutoring\/parentNext"/)
    expect(target).not.toMatch(/tutoring\/(parentTutoring|accessView|sessionView)/)
    const mapping = readFileSync(join(WEB, "src/lib/tutoring/parentNext.ts"), "utf8")
    expect(mapping).not.toMatch(/^\s*import\b/m)
    expect(mapping).not.toMatch(/\bfrom\s+["']/)
  })
})
