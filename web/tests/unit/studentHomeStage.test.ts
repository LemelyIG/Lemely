import { describe, expect, it } from "vitest"
import { pickStage, type StageVm } from "@/portals/student/home/model"
import { makeHome } from "./studentHomeFixture"
import { bubbleText, stageHtml } from "./support/homeBubble"

function stage(line: string): StageVm {
  return {
    key: "marking:u1",
    kind: "marking",
    mood: "thinking",
    motion: "idle",
    line,
    action: { label: "Watch it mark", to: "/student/correct" },
    dismissible: false,
  }
}

describe("HomeStage line", () => {
  it("renders every number in Mono and leaves the words alone", () => {
    const out = stageHtml(stage("8 of 14 marked"))
    expect(out).toContain('<span class="font-mono">8</span> of <span class="font-mono">14</span> marked')
  })

  it("keeps a question label whole and in Mono, never a sans Q beside a mono digit", () => {
    const reply = pickStage(makeHome({ moments: [{ kind: "teacherReply", reply: makeHome().teacherReplies[0]! }] }), new Set())
    expect(reply.line).toBe("Your teacher checked Q7")
    const out = stageHtml(reply)
    expect(out).toContain('checked <span class="font-mono">Q7</span></p>')
    expect(out).not.toContain('>7</span>')
    expect(stageHtml(stage("Q4b is next"))).toContain('<span class="font-mono">Q4b</span> is next')
    expect(stageHtml(stage("Q12 and 3 more"))).toContain('<span class="font-mono">Q12</span> and <span class="font-mono">3</span> more')
  })

  it("renders a line with no numbers as plain text", () => {
    const out = stageHtml(stage("Scan your next paper"))
    expect(out).toContain("Scan your next paper")
    expect(out).not.toContain("font-mono")
  })

  it("shows only the line in the bubble: a morning student gets no greeting there", () => {
    // 09:00 with no exam near is the one case that used to prefix "Morning, Mariam." (owner decision 2026-11-24).
    const morning = pickStage(makeHome({ nextExamOn: null, localHour: 9 }), new Set())
    expect(morning.kind).toBe("morning")
    expect(bubbleText(morning)).toBe("Win marks back")
    expect(stageHtml(morning)).not.toContain("Morning")
  })
})
