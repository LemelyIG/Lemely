import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

vi.mock("@/components/redesign/motion", async (orig) => ({
  ...(await orig<typeof import("@/components/redesign/motion")>()),
  usePrefersReducedMotion: () => true,
}))

import { Binny } from "@/components/redesign/Binny"

describe("Binny under reduced motion", () => {
  it("keeps the roam zone (no layout shift) while Binny itself is static", () => {
    const out = renderToStaticMarkup(createElement(Binny, { mood: "happy", motion: "roam", roamDistance: 40 }))
    expect(out).toMatch(/^<span class="rd-binny-zone" style="--rd-roam:40px">/)
    expect(out).toMatch(/data-motion="none"/)
  })
  it("renders no zone for non-roam motion", () => {
    expect(renderToStaticMarkup(createElement(Binny, { mood: "happy", motion: "idle" }))).not.toContain("rd-binny-zone")
  })
})
