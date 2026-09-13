import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * Packet B2a · source-text pins for the pieces of the navigation model that
 * are wiring, not pure logic, and so cannot be exercised under vitest's
 * Node/no-jsdom environment (D3.20): `Modal`/`NavDrawer` must go through the
 * shared history + scroll-lock primitives rather than reinventing
 * `document.body.style.overflow`, `<ScrollRestoration>` mounts exactly once
 * inside the router (never in `main.tsx`, which renders above
 * `RouterProvider` and so is outside any data-router route), and the
 * post-login return path is wired through `RequireAuth`/`Login.tsx`.
 */

const ROOT = path.join(import.meta.dirname, "..", "..")

function sourceOf(relative: string): string {
  return stripComments(fs.readFileSync(path.join(ROOT, relative), "utf8"))
}

describe("modal.tsx and nav-drawer.tsx use the shared history + scroll-lock primitives", () => {
  it.each(["src/components/ui/modal.tsx", "src/components/ui/nav-drawer.tsx"])(
    "%s imports useDialogHistory and lockScroll, and no longer sets body.style.overflow directly",
    (relative) => {
      const stripped = sourceOf(relative)
      expect(stripped).toContain("useDialogHistory")
      expect(stripped).toContain("lockScroll")
      expect(stripped).not.toContain("body.style.overflow")
    },
  )
})

describe("routes.tsx mounts RootOutlet as the single pathless layout route", () => {
  it("contains <RootOutlet exactly once, before the first route's path:", () => {
    const stripped = sourceOf("src/routes.tsx")
    const occurrences = stripped.match(/<RootOutlet/g) ?? []
    expect(occurrences).toHaveLength(1)

    const rootOutletAt = stripped.indexOf("<RootOutlet")
    const firstPathAt = stripped.indexOf("path:")
    expect(rootOutletAt).toBeGreaterThan(-1)
    expect(firstPathAt).toBeGreaterThan(-1)
    expect(rootOutletAt).toBeLessThan(firstPathAt)
  })
})

describe("ScrollRestoration is mounted once, inside the router, never in main.tsx", () => {
  it("root-outlet.tsx renders <ScrollRestoration", () => {
    expect(sourceOf("src/components/root-outlet.tsx")).toContain("<ScrollRestoration")
  })

  it("main.tsx does not — it renders above RouterProvider, outside any data-router route", () => {
    expect(sourceOf("src/main.tsx")).not.toContain("ScrollRestoration")
  })
})

describe("post-login return path", () => {
  it("RequireAuth.tsx carries state.from on its redirects", () => {
    expect(sourceOf("src/lib/auth/RequireAuth.tsx")).toContain("state={{ from")
  })

  it("Login.tsx imports and uses postLoginTarget", () => {
    const stripped = sourceOf("src/portals/auth/Login.tsx")
    expect(stripped).toContain("postLoginTarget")
    expect(stripped).toContain('import { postLoginTarget } from "@/lib/auth/postLoginTarget"')
  })
})

describe("student sub-screens render BackControl", () => {
  it("student/index.tsx's Header renders <BackControl", () => {
    expect(sourceOf("src/portals/student/index.tsx")).toContain("<BackControl")
  })
})
