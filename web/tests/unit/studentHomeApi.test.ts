import { beforeEach, describe, expect, it, vi } from "vitest"

const request = vi.fn()
vi.mock("@/lib/api", () => ({ request: (...args: unknown[]) => request(...args) }))

import { fetchStudentHome, STUDENT_HOME_PATH } from "@/lib/studentHomeApi"
import { homeRefetchInterval, MARKING_POLL_MS, STUDENT_HOME_KEY } from "@/lib/hooks/useStudentHomeApi"
import { makeHome } from "./studentHomeFixture"

describe("student home API", () => {
  beforeEach(() => request.mockReset())

  it("reads GET /student/home", async () => {
    request.mockResolvedValue(makeHome())
    await fetchStudentHome()
    expect(request).toHaveBeenCalledWith(STUDENT_HOME_PATH)
    expect(STUDENT_HOME_PATH).toBe("/student/home")
  })

  it("keys the query under student/home", () => {
    expect(STUDENT_HOME_KEY).toEqual(["student", "home"])
  })

  it("polls only while a paper is marking", () => {
    expect(homeRefetchInterval(undefined)).toBe(false)
    expect(homeRefetchInterval(makeHome())).toBe(false)
    const marking = makeHome({
      moments: [
        { kind: "marking", paperId: "u1", filename: null, startedAt: null, stale: false, questionsDone: null, questionsTotal: null },
      ],
    })
    expect(homeRefetchInterval(marking)).toBe(MARKING_POLL_MS)
  })
})
