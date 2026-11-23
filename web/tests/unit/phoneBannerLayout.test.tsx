import { createElement as h } from "react"
import { describe, expect, it } from "vitest"
import { PhoneBannerView } from "@/components/ui/phone-banner"
import { renderStatic } from "./support/billingRender"

/*
 * The strip's layout contract, pinned as classes (the measured x positions at 390 and 1280 are the
 * screenshots in the report):
 *  - the sentence keeps a width floor (`min-w-48`), so it never squeezes to a sliver beside the
 *    link and the dismiss button;
 *  - the strip is a grid of icon | text | actions. Below `sm` the actions sit in column 2 of the
 *    next row, so they start at the same x as the text (icon width plus gap, no magic number);
 *    from `sm` up they move to column 3 and share the text's row.
 */

const markup = renderStatic(h(PhoneBannerView, { to: "/settings/profile", onDismiss: () => undefined }))
const tag = (re: RegExp) => markup.match(re)?.[0] ?? ""

const root = tag(/<div role="status"[^>]*>/)
const text = tag(/<p [^>]*>/)
const actions = tag(/<div class="[^"]*col-start-2[^"]*">/)

describe("phone banner layout", () => {
  it("keeps a width floor on the sentence", () => {
    expect(text).toMatch(/\bmin-w-48\b/)
    expect(text).not.toMatch(/\bmin-w-0\b/)
  })

  it("is a grid: icon, text, then actions in the text's column below sm", () => {
    expect(root).toMatch(/\bgrid\b/)
    expect(root).not.toMatch(/\bflex-wrap\b/)
    expect(root).toMatch(/\bgrid-cols-\[auto_minmax\(0,1fr\)\]/)
    expect(root).toMatch(/\bsm:grid-cols-\[auto_minmax\(0,1fr\)_auto\]/)
    expect(actions).toMatch(/\bcol-start-2\b/)
  })

  it("moves the actions onto the text's row from sm up", () => {
    expect(actions).toMatch(/\bsm:col-start-3\b/)
  })

  it("holds the link and the dismiss button in that one actions element", () => {
    const inner = markup.slice(markup.indexOf(actions) + actions.length)
    expect(inner).toMatch(/^<a [^>]*>Add mobile number<\/a><button [^>]*aria-label="Dismiss the mobile reminder"/)
  })
})
