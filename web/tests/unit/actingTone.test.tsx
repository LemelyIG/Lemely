import { createElement as h } from "react"
import { describe, expect, it, vi } from "vitest"
import { ActingBannerView } from "@/components/acting/acting-banner"
import { ShellTopBar } from "@/components/shell/ShellTopBar"
import { renderStatic } from "./support/billingRender"

/*
 * Acting mode is cued in primary (navy), never gold: gold is for what was earned, and "you are
 * working as someone else" is a fact about the session, not a reward. The cue is the ring round
 * the top bar, the "Working as" chip in it, and the banner above the content.
 *
 * Static markup is enough: these are class assertions on what the three pieces render, and the
 * ring must be inset because the phone bar is full-bleed and an outer ring is clipped by the
 * viewport edge.
 */

vi.mock("@/lib/hooks/useNotificationApi", () => ({ useNotificationCounts: () => ({ data: undefined }) }))
vi.mock("@/lib/nav/useOverlayState", () => ({ useOverlayState: () => [null, () => undefined] }))

const noop = () => undefined

function bar(actingAs?: string): string {
  return renderStatic(
    h(ShellTopBar, {
      title: "Classes",
      trail: [],
      onOpenNav: noop,
      navLabel: "Open teacher navigation",
      notifications: {} as never,
      settingsTo: "/teacher/settings",
      backFallback: "/teacher",
      account: {} as never,
      actingAs,
    }),
  )
}

/** The opening tag of the first element whose attributes match. */
function tagWith(markup: string, attr: string): string {
  const m = markup.match(new RegExp(`<[a-z]+[^>]*${attr}[^>]*>`))
  if (!m) throw new Error(`no element with ${attr} in ${markup.slice(0, 300)}`)
  return m[0]
}

const banner = () =>
  renderStatic(h(ActingBannerView, { leadName: "Mr Hassan", roleLabel: "Marker", lacks: null, onSwitchBack: noop }))

describe("acting top bar", () => {
  it("rings the bar inset, so a full-bleed phone bar does not clip it", () => {
    const classes = tagWith(bar("Mr Hassan"), 'data-acting="true"')
    expect(classes).toMatch(/\bring-2\b/)
    expect(classes).toMatch(/\bring-inset\b/)
  })

  it("draws the ring in primary, not tertiary (gold)", () => {
    const classes = tagWith(bar("Mr Hassan"), 'data-acting="true"')
    expect(classes).toMatch(/\bring-primary\b/)
    expect(classes).not.toMatch(/tertiary/)
  })

  it("draws no ring when not acting", () => {
    expect(bar()).not.toMatch(/data-acting=/)
    expect(bar()).not.toMatch(/\bring-2\b/)
  })

  it("shows the Working as chip in a primary container", () => {
    const chip = tagWith(bar("Mr Hassan"), 'data-testid="acting-chip"')
    expect(chip).toMatch(/\bbg-primary-container\b/)
    expect(chip).toMatch(/\btext-on-primary-container\b/)
    expect(chip).not.toMatch(/tertiary/)
  })
})

describe("acting banner", () => {
  it("sits on a primary container, with on-primary-container text, and no tertiary role", () => {
    const markup = banner()
    const root = tagWith(markup, 'data-testid="acting-banner"')
    expect(root).toMatch(/\bbg-primary-container\b/)
    expect(root).toMatch(/\btext-on-primary-container\b/)
    expect(markup).not.toMatch(/tertiary/)
  })
})
