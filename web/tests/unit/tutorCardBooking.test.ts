import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { cardBookingFor, directoryLinkFor } from "@/lib/tutoring/cardBooking"
import { parentTutorHref } from "@/lib/tutoring/parentTutoring"
import { safeNextPath } from "@/lib/nextPath"
import { postLoginTarget } from "@/lib/auth/postLoginTarget"
import { DIRECTORY_SIGNED_IN_LINE, DIRECTORY_SIGNED_IN_LINK_TEXT } from "@/lib/tutoring/discovery"

/*
 * G-16 / G-17: what the public card's booking action is for the reader who opens it.
 * `/login` is wrapped in `LoginRoute`, which sends any live session to its portal root
 * and drops `?next=`, so a signed-in student or parent who followed a shared card link
 * used to land on their home page and lose the tutor. The action now depends on the
 * session: signed out keeps `/login?next=`, a student goes straight to the booking
 * profile, a parent to the parent's page for the same tutor, anyone else is told plainly.
 */

const ID = "0b6a8d1e-52f3-4c1a-9a47-5d2f0e6c7b13"
const SRC = join(import.meta.dirname, "..", "..", "src")

describe("cardBookingFor", () => {
  it("keeps /login?next= for a signed-out reader, carrying the student's tutor page", () => {
    expect(cardBookingFor(null, ID)).toEqual({
      kind: "link",
      label: "Sign in to book",
      to: `/login?next=${encodeURIComponent(`/student/tutors/${ID}`)}`,
    })
    expect(cardBookingFor(undefined, ID).kind).toBe("link")
  })

  it("sends a student straight to the tutor's page in the student portal", () => {
    expect(cardBookingFor("student", ID)).toEqual({ kind: "link", label: "Book a session", to: `/student/tutors/${ID}` })
  })

  it("sends a parent to the parent's page for the same tutor", () => {
    expect(cardBookingFor("parent", ID)).toEqual({ kind: "link", label: "Book a session", to: parentTutorHref(ID) })
    expect(parentTutorHref(ID)).toBe(`/parent/tutors/${ID}`)
  })

  it("offers teachers and admins no booking link, and says why in a plain sentence", () => {
    for (const role of ["teacher", "school_admin", "platform_admin", "someone_new", ""]) {
      const out = cardBookingFor(role, ID)
      expect(out.kind, role).toBe("note")
      if (out.kind === "note") expect(out.sentence).toBe("Booking is for students and their parents.")
    }
  })

  it("builds a link only for a lowercase tutor id, whatever the session", () => {
    const bad = [
      ID.toUpperCase(),
      "not-a-uuid",
      "",
      `${ID}/../../x`,
      `${ID}?next=//evil.example`,
      "//evil.example",
      `${ID} `,
      "0B6A8D1E-52f3-4c1a-9a47-5d2f0e6c7b13",
    ]
    for (const role of [null, "student", "parent", "teacher"]) {
      for (const id of bad) expect(cardBookingFor(role, id), `${role}:${id}`).toEqual({ kind: "none" })
    }
  })

  it("only ever produces addresses safeNextPath accepts and the sign-in flow returns to", () => {
    const signedOut = cardBookingFor(null, ID)
    const student = cardBookingFor("student", ID)
    const parent = cardBookingFor("parent", ID)
    if (signedOut.kind !== "link" || student.kind !== "link" || parent.kind !== "link") throw new Error("expected links")
    const next = new URL(signedOut.to, "https://x.test").searchParams.get("next")
    expect(next).toBe(`/student/tutors/${ID}`)
    expect(safeNextPath(next)).toBe(next)
    expect(safeNextPath(student.to)).toBe(student.to)
    expect(safeNextPath(parent.to)).toBe(parent.to)
    // A student who signs in lands on the tutor; a parent on the parent's page for them.
    expect(postLoginTarget({ next, from: null, role: "student" })).toBe(student.to)
    expect(postLoginTarget({ next, from: null, role: "parent" })).toBe(parent.to)
  })
})

describe("directoryLinkFor", () => {
  it("is /login signed out, the role's own tutor directory for a student or parent, /login otherwise", () => {
    expect(directoryLinkFor(null)).toEqual({ signedIn: false, to: "/login" })
    expect(directoryLinkFor("student")).toEqual({ signedIn: true, to: "/student/tutors" })
    expect(directoryLinkFor("parent")).toEqual({ signedIn: true, to: "/parent/tutors" })
    expect(directoryLinkFor("teacher")).toEqual({ signedIn: false, to: "/login" })
  })
})

describe("G-16's signed-in sentence", () => {
  it("starts with its link text, because the screen slices one from the other", () => {
    expect(DIRECTORY_SIGNED_IN_LINE.startsWith(DIRECTORY_SIGNED_IN_LINK_TEXT)).toBe(true)
  })
})

describe("the screens use the session-aware helper", () => {
  const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "")
  const card = strip(readFileSync(join(SRC, "portals", "marketing", "tutors", "TutorPublicCard.tsx"), "utf8"))
  const directory = strip(readFileSync(join(SRC, "portals", "marketing", "tutors", "TutorDirectory.tsx"), "utf8"))

  it("G-17 reads the session and no longer hard-codes the sign-in link", () => {
    expect(card).toContain("useAuth()")
    expect(card).toContain("cardBookingFor(")
    expect(card).not.toContain("/login?next=")
  })

  it("G-16 reads the session for its one link", () => {
    expect(directory).toContain("useAuth()")
    expect(directory).toContain("directoryLinkFor(")
  })
})
