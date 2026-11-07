import { describe, expect, it } from "vitest"
import { nextSettingsTabIndex, notificationsTriggerLabel, panelTimeLabel, titleRuns } from "@/components/shell/shellModel"

const NOW = new Date(2026, 10, 5, 10, 0) // Thu 5 Nov 2026, the preview fixtures' "now"

describe("notificationsTriggerLabel", () => {
  it("names the unread count when there is one", () => {
    expect(notificationsTriggerLabel("3")).toBe("Notifications, 3 unread")
    expect(notificationsTriggerLabel("99+")).toBe("Notifications, 99+ unread")
  })
  it("is plain when nothing is unread or the count is unknown", () => {
    expect(notificationsTriggerLabel(null)).toBe("Notifications")
  })
})

describe("panelTimeLabel (design A: 9:12, Wed, 27 Oct)", () => {
  it("shows the clock time for today, without a leading zero on the hour", () => {
    expect(panelTimeLabel(new Date(2026, 10, 5, 9, 12).toISOString(), NOW)).toBe("9:12")
    expect(panelTimeLabel(new Date(2026, 10, 5, 8, 4).toISOString(), NOW)).toBe("8:04")
  })
  it("shows the weekday within the last six days", () => {
    expect(panelTimeLabel(new Date(2026, 10, 4, 18, 0).toISOString(), NOW)).toBe("Wed")
    expect(panelTimeLabel(new Date(2026, 10, 2, 17, 0).toISOString(), NOW)).toBe("Mon")
    expect(panelTimeLabel(new Date(2026, 9, 30, 9, 0).toISOString(), NOW)).toBe("Fri")
  })
  it("shows day and month from a week back", () => {
    expect(panelTimeLabel(new Date(2026, 9, 29, 9, 0).toISOString(), NOW)).toBe("29 Oct")
    expect(panelTimeLabel(new Date(2026, 9, 27, 16, 0).toISOString(), NOW)).toBe("27 Oct")
  })
  it("is empty for an unparseable time rather than 'Invalid Date'", () => {
    expect(panelTimeLabel("not a date", NOW)).toBe("")
  })
})

describe("nextSettingsTabIndex (arrow keys on the settings tabs)", () => {
  it.each([
    [0, "ArrowDown", 5, 1],
    [0, "ArrowRight", 5, 1],
    [4, "ArrowDown", 5, 0],
    [0, "ArrowUp", 5, 4],
    [2, "ArrowLeft", 5, 1],
    [3, "Home", 5, 0],
    [1, "End", 5, 4],
  ])("from %i, %s over %i tabs goes to %i", (current, key, count, expected) => {
    expect(nextSettingsTabIndex(current, key, count)).toBe(expected)
  })
  it("ignores other keys and an unknown current tab", () => {
    expect(nextSettingsTabIndex(0, "Enter", 5)).toBeNull()
    expect(nextSettingsTabIndex(-1, "ArrowDown", 5)).toBeNull()
  })
  it.each(["altKey", "ctrlKey", "metaKey"])("ignores a %s-modified key", (mod) => {
    expect(nextSettingsTabIndex(0, "ArrowDown", 5, { [mod]: true })).toBeNull()
    expect(nextSettingsTabIndex(1, "Home", 5, { [mod]: true })).toBeNull()
  })
})

describe("titleRuns (design A sets codes and dates in the mono face)", () => {
  it("flags a day and month, not the weekday before it", () => {
    expect(titleRuns("Physics mock moved to Thu 12 Nov")).toEqual([
      { text: "Physics mock moved to Thu ", mono: false },
      { text: "12 Nov", mono: true },
    ])
  })
  it("flags a paper code at the start", () => {
    expect(titleRuns("0580/42 is marked")).toEqual([
      { text: "0580/42", mono: true },
      { text: " is marked", mono: false },
    ])
  })
  it("leaves plain titles whole", () => {
    expect(titleRuns("Welcome")).toEqual([{ text: "Welcome", mono: false }])
  })
})
