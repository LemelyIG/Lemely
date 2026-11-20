// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h, useState } from "react"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"
import { Modal } from "@/components/ui/modal"

/*
 * DOM component-test harness (opt-in). The web runner stays `environment:
 * "node"` (vitest.config.ts, D3.20); a file opts in to jsdom + Testing Library by:
 *   1. a first-line docblock `// @vitest-environment jsdom`
 *   2. `import "./support/dom-setup"` (cleanup, matchMedia/ResizeObserver stubs)
 *   3. a `.test.tsx` name (vitest.config.ts includes `tests/unit/**\/*.test.tsx`)
 * Use `userEvent.setup()` for interactions; jsdom has no layout, so assert focus,
 * effects and click flows, not geometry. Pixel/visual behaviour stays in Playwright.
 */

function Harness({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false)
  return h(
    "div",
    null,
    h("button", { onClick: () => setOpen(true) }, "Open"),
    h(
      Modal,
      {
        open,
        title: "Confirm",
        children: null,
        onClose: () => {
          onClose()
          setOpen(false)
        },
      },
      h("button", null, "Inside"),
    ),
  )
}

describe("Modal in jsdom", () => {
  it("moves focus in on open, closes on Escape, returns focus to the opener", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    // Modal pushes a history entry (useDialogHistory), so it needs a router.
    render(h(MemoryRouter, null, h(Harness, { onClose })))

    const opener = screen.getByRole("button", { name: "Open" })
    await user.click(opener)

    const dialog = await screen.findByRole("dialog", { name: "Confirm" })
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true))

    await user.keyboard("{Escape}")
    expect(onClose).toHaveBeenCalledTimes(1)

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(document.activeElement).toBe(opener)
  })
})
