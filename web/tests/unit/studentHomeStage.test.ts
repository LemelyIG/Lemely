import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { HomeStage } from "@/portals/student/home/HomeStage"
import type { StageVm } from "@/portals/student/home/model"

function stage(line: string, greeting: string | null = null): StageVm {
  return {
    key: "marking:u1",
    kind: "marking",
    mood: "thinking",
    motion: "idle",
    greeting,
    line,
    action: { label: "Watch it mark", to: "/student/correct" },
    dismissible: false,
  }
}

function html(vm: StageVm): string {
  return renderToStaticMarkup(
    createElement(MemoryRouter, null, createElement(HomeStage, { stage: vm, onNotNow: () => {} })),
  )
}

describe("HomeStage line", () => {
  it("renders every number in Mono and leaves the words alone", () => {
    const out = html(stage("8 of 14 marked"))
    expect(out).toContain('<span class="font-mono">8</span> of <span class="font-mono">14</span> marked')
  })

  it("renders a line with no numbers as plain text", () => {
    const out = html(stage("Scan your next paper"))
    expect(out).toContain("Scan your next paper")
    expect(out).not.toContain("font-mono")
  })

  it("keeps the greeting before the line", () => {
    const out = html(stage("Win marks back", "Morning, Mariam."))
    expect(out).toContain("Morning, Mariam. </span>Win marks back")
  })
})
