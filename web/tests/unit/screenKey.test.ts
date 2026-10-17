import { describe, expect, it } from "vitest"
import { createMemoryRouter, type Location } from "react-router-dom"
import { screenKey } from "@/lib/nav/screenKey"

/*
 * The `ScreenOutlet`/`ScreenFrame` remount bug, pinned against the real
 * router rather than against a description of it.
 *
 * `useDialogHistory` opens an overlay by pushing one history entry at the URL
 * the reader is already on. `react-router`'s `navigate()` funnels that through
 * `normalizeTo`, which reduces the `Location` it is handed to a path *string*
 * (`createPath`) before `createLocation` runs — and `createLocation`'s
 * `key: to && to.key || key || createKey()` can no longer see the original
 * key on a string, so it mints a fresh one. Same URL, new `location.key`.
 *
 * That made a wrapper keyed on `location.key` remount the entire screen
 * subtree the instant any overlay tried to open, destroying the `useState`
 * holding "this dialog is open" and so preventing screen-local dialogs from
 * ever appearing. `screenKey` is what the wrapper keys on instead.
 */

async function dialogHistoryPush(at: string): Promise<{ before: Location; after: Location }> {
  const router = createMemoryRouter([{ path: "*" }], { initialEntries: [at] })
  router.initialize()
  const before = router.state.location
  // Exactly what `useDialogHistory` does to open an overlay.
  await router.navigate(before, {
    state: { ...(before.state as Record<string, unknown> | null), lemelyDialog: true },
  })
  return { before, after: router.state.location }
}

describe("screenKey", () => {
  it("survives the history entry an overlay pushes at the current URL", async () => {
    const { before, after } = await dialogHistoryPush("/teacher/quizzes/7?tab=questions")

    // The router really does mint a fresh key for that same-URL push — this is
    // the mechanism the bug rode in on, asserted so the fix below means something.
    expect(after.key).not.toBe(before.key)
    expect(after.pathname).toBe(before.pathname)
    expect(after.search).toBe(before.search)

    expect(screenKey(after)).toBe(screenKey(before))
  })

  it("still changes when the reader actually navigates", () => {
    expect(screenKey({ pathname: "/teacher/quizzes", search: "" })).not.toBe(
      screenKey({ pathname: "/teacher/classes", search: "" }),
    )
  })

  it("distinguishes two screens that differ only by query string", () => {
    expect(screenKey({ pathname: "/teacher/review", search: "?class=3" })).not.toBe(
      screenKey({ pathname: "/teacher/review", search: "?class=4" }),
    )
  })
})
