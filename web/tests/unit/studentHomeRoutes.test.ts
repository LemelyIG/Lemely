import { describe, expect, it } from "vitest"
import { flashcardsTarget, homeRoutes, planTarget, practiceTarget } from "@/portals/student/home/routes"
import { makeHome } from "./studentHomeFixture"

describe("home routes", () => {
  it("builds result links with the lost filter PaperResult already reads", () => {
    expect(homeRoutes.result("5")).toBe("/student/result/5")
    expect(homeRoutes.result("5", "lost")).toBe("/student/result/5?q=lost")
  })

  it("encodes the topic on practice links", () => {
    expect(homeRoutes.practiceTopic("0606", "Quadratic inequalities")).toBe(
      "/student/practice/0606?topic=Quadratic%20inequalities",
    )
  })

  it("sends practice to the top topic, then the first subject, then scan", () => {
    expect(practiceTarget(makeHome())).toBe("/student/practice/0580?topic=Vectors")
    expect(practiceTarget(makeHome({ winBack: [] }))).toBe("/student/practice/0580")
    expect(practiceTarget(makeHome({ winBack: [], floor: [] }))).toBe("/student/correct")
  })

  it("opens the plan of today's session subject first", () => {
    const home = makeHome({
      todaySessions: [{ sessionId: "s1", subjectCode: "0625", topic: "Waves", minutes: 10, done: false }],
    })
    expect(planTarget(home)).toBe("/student/plan/0625")
    expect(planTarget(makeHome())).toBe("/student/plan/0580")
    expect(planTarget(makeHome({ floor: [] }))).toBe("/student/correct")
  })

  it("opens flashcards for the top topic's subject", () => {
    expect(flashcardsTarget(makeHome())).toBe("/student/flashcards/0580")
  })
})
