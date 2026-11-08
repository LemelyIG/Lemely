import { createElement as h } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

/*
 * What `BarChart` hands Nivo when a caller adds no layout props. `leftMargin`, `rightMargin` and
 * `valueTickCount` were added for the money and margin screen; every other chart in the product
 * relies on these defaults staying exactly what they were.
 */

const s = vi.hoisted(() => ({ props: null as null | Record<string, any> }))
vi.mock("@nivo/bar", () => ({
  ResponsiveBar: (p: Record<string, unknown>) => {
    s.props = p
    return null
  },
}))
vi.mock("@/lib/nivoTheme", () => ({
  useNivoTheme: () => ({ theme: {}, tokens: {}, seriesColors: [], singleSeriesColor: "#000", ready: true }),
  useChartAnimation: () => false,
}))

import { BarChart, type BarChartProps } from "@/components/ui/bar-chart"

const decimals = [
  { label: "a", value: 1.5 },
  { label: "b", value: 3.25 },
]
const wholes = [
  { label: "a", value: 3 },
  { label: "b", value: 8 },
]

function render(over: Partial<BarChartProps> = {}) {
  renderToStaticMarkup(h(BarChart, { data: decimals, ariaLabel: "test chart", ...over }))
  return s.props as Record<string, any>
}

beforeEach(() => {
  s.props = null
})

describe("BarChart layout defaults", () => {
  it("keeps the margin {top 8, right 12, bottom 28, left 44} when no layout prop is passed", () => {
    expect(render().margin).toEqual({ top: 8, right: 12, bottom: 28, left: 44 })
  })

  it("widens the left margin to 56 for a left-axis legend", () => {
    expect(render({ axisLeftLegend: "Credits" }).margin).toEqual({ top: 8, right: 12, bottom: 28, left: 56 })
  })

  it("takes the bottom margin 44 for a bottom legend, as before", () => {
    expect(render({ axisBottomLegend: "Week" }).margin.bottom).toBe(44)
  })

  it("lets a caller set the left and right margins", () => {
    expect(render({ leftMargin: 104, rightMargin: 24 }).margin).toMatchObject({ left: 104, right: 24 })
  })
})

describe("BarChart value ticks", () => {
  const ticks = (over: Partial<BarChartProps> = {}) => {
    const p = render(over)
    return (p.layout === "horizontal" ? p.axisBottom : p.axisLeft).tickValues
  }

  it("asks for 4 ticks on non-integer data", () => {
    expect(ticks()).toBe(4)
  })

  it("uses the whole numbers themselves, at most five, for integer data with max 8", () => {
    expect(ticks({ data: wholes })).toEqual([0, 2, 4, 6, 8])
  })

  it("reads the horizontal value axis from the bottom", () => {
    expect(ticks({ horizontal: true })).toBe(4)
  })

  it("honours valueTickCount, and never drops below one tick", () => {
    expect(ticks({ valueTickCount: 2 })).toBe(2)
    expect(ticks({ data: wholes, valueTickCount: 2 })).toEqual([0, 4, 8])
    expect(ticks({ valueTickCount: 0 })).toBe(1)
    expect(ticks({ valueTickCount: -3 })).toBe(1)
    expect(ticks({ data: wholes, valueTickCount: 0 })).toEqual([0, 8])
  })
})
