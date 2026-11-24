import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import type { PastPaper } from "@/lib/practiceHubTypes"

// Both files are thin shells over papersModel and papersFlow. These tests drive them
// through the data hooks (mocked) and a pass-through Sheet (Radix's portal renders
// nothing on the server), one frame per state: PP, PQ, plus the load and error states.
type Status = "pending" | "error" | "success"
const api = vi.hoisted(() => ({
  papersStatus: "success" as Status,
  papers: undefined as unknown,
  papersError: null as unknown,
  papersFetching: false,
  overviewStatus: "success" as Status,
  profileStatus: "success" as Status,
  subjects: [] as { code: string; name: string }[],
  levels: undefined as unknown,
  subjectLevel: null as string | null,
  creating: false,
  createError: null as unknown,
  retry: () => {},
  create: vi.fn(async () => ({ assignmentId: "a-9" })),
  navigate: vi.fn(),
  printClick: undefined as (() => void) | undefined,
}))

vi.mock("react-router-dom", async (importOriginal) => ({
  ...await importOriginal<typeof import("react-router-dom")>(),
  useNavigate: () => api.navigate,
}))
vi.mock("@/components/ui/button", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/ui/button")>()
  return {
    ...actual,
    Button: (props: React.ComponentProps<typeof actual.Button>) => {
      if (props.children === "Print paper") api.printClick = props.onClick as () => void
      return createElement(actual.Button, props)
    },
  }
})

vi.mock("@/components/ui/sheet", async () => {
  const { createElement: h } = await import("react")
  const part = (tag: string) => (p: { children?: ReactNode; nativeHeader?: ReactNode; className?: string }) =>
    h(tag, { className: p.className }, p.nativeHeader, p.children)
  return { Sheet: (p: { children?: ReactNode }) => p.children, SheetContent: part("section"), SheetTitle: part("h2") }
})
vi.mock("@/lib/hooks/usePracticeHubApi", () => ({
  usePastPapers: () => ({
    status: api.papersStatus,
    data: api.papers,
    error: api.papersError,
    refetch: api.retry,
    fetchStatus: "idle",
    isFetching: api.papersFetching,
  }),
  useCreateFromPaper: () => ({
    isPending: api.creating,
    isError: api.createError !== null,
    error: api.createError,
    mutateAsync: api.create,
  }),
}))
vi.mock("@/portals/student/screens/practice/hub/usePracticeHubData", () => ({
  usePracticeHubData: () => ({
    input: { overviewStatus: api.overviewStatus, profileStatus: api.profileStatus },
    builderSubjects: api.subjects,
    refetchAll: api.retry,
    refetching: false,
  }),
}))
vi.mock("@/lib/hooks/useReferenceApi", () => ({
  useReference: () => ({
    data: {
      qualificationLevels: api.levels,
      subjects: [{ code: "0580", name: "Maths", qualificationLevel: api.subjectLevel }],
    },
  }),
}))

const { PastPapers } = await import("@/portals/student/screens/practice/papers/PastPapers")
const { PastPaperSheet } = await import("@/portals/student/screens/practice/papers/PastPaperSheet")

const SRC = join(import.meta.dirname, "..", "..", "src", "portals", "student", "screens", "practice", "papers")

const paper = (over: Partial<PastPaper> = {}): PastPaper => ({
  paperId: "p42",
  code: "0580/42",
  subjectCode: "0580",
  paperNumber: 4,
  paperVariant: 2,
  sessionLabel: "May/June 2025",
  durationMinutes: 150,
  totalMarks: 80,
  questionCount: 18,
  awardedMarks: 52,
  maximumMarks: 80,
  ...over,
})

const PAPERS = [
  paper(),
  paper({ paperId: "p41", code: "0580/41", sessionLabel: "Oct/Nov 2024", paperVariant: 1, awardedMarks: null, maximumMarks: null }),
  paper({ paperId: "p22", code: "0580/22", sessionLabel: "May/June 2025", paperNumber: 2, durationMinutes: 90, totalMarks: 70, awardedMarks: 41, maximumMarks: 70 }),
  paper({ paperId: "p21", code: "0580/21", sessionLabel: "Oct/Nov 2024", paperNumber: 2, durationMinutes: 90, totalMarks: 70, awardedMarks: null, maximumMarks: null }),
]

const SUBJECTS = [
  { code: "0580", name: "Maths" },
  { code: "0625", name: "Physics" },
]

function page() {
  return renderToStaticMarkup(createElement(MemoryRouter, null, createElement(PastPapers)))
}
function sheet(p: PastPaper = paper()) {
  return renderToStaticMarkup(
    createElement(MemoryRouter, null, createElement(PastPaperSheet, { paper: p, subjectName: "Maths", subjectOrder: ["0580", "0625"], onClose: () => {} })),
  )
}

const count = (haystack: string, needle: string) => haystack.split(needle).length - 1
const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").replace(/&#x27;/g, "'").replace(/&quot;/g, '"')
/** The opening tag of the button whose own content contains `label`, or "" when there is none. */
const button = (html: string, label: string) =>
  html.match(new RegExp(`<button[^>]*>(?=(?:(?!</button>)[\\s\\S])*${label})`))?.[0] ?? ""
const isDisabled = (tag: string) => / disabled=""/.test(tag)

beforeEach(() => {
  api.papersStatus = "success"
  api.papers = { subjectCode: "0580", papers: PAPERS }
  api.papersError = null
  api.papersFetching = false
  api.overviewStatus = "success"
  api.profileStatus = "success"
  api.subjects = SUBJECTS
  api.levels = [{ value: "igcse", label: "Cambridge IGCSE" }]
  api.subjectLevel = "igcse"
  api.creating = false
  api.createError = null
  api.create.mockClear()
  api.navigate.mockClear()
  api.printClick = undefined
})

describe("PastPapers (PP): the list", () => {
  it("groups by paper number, the highest first, and names each group", () => {
    const out = page()
    expect(out.indexOf("Paper 4</h2>")).toBeGreaterThan(-1)
    expect(out.indexOf("Paper 4</h2>")).toBeLessThan(out.indexOf("Paper 2</h2>"))
    for (const title of ["0580/42 · May/June 2025", "0580/41 · Oct/Nov 2024", "0580/22 · May/June 2025", "0580/21 · Oct/Nov 2024"]) {
      expect(text(out)).toContain(title)
    }
  })

  it("sets the score of a done paper in Mono and gives an undone paper none", () => {
    const out = page()
    expect(out).toMatch(/font-mono[^>]*>52\/80</)
    expect(out).toMatch(/font-mono[^>]*>41\/70</)
    expect(count(out, "/80<") + count(out, "/70<")).toBe(2)
  })

  it("draws one chevron per row: the row's own, with no second one of ours", () => {
    const rows = page().match(/<button[^>]*>(?:(?!<\/button>)[\s\S])*<\/button>/g) ?? []
    const paperRows = rows.filter((r) => r.includes("0580/"))
    expect(paperRows).toHaveLength(4)
    for (const row of paperRows) expect(count(row, "<svg")).toBe(2) // the leading mark and the row's chevron
  })

  it("is one list per group, each named for assistive tech", () => {
    const out = page()
    expect(out).toMatch(/<ul[^>]*aria-label="Paper 4"/)
    expect(out).toMatch(/<ul[^>]*aria-label="Paper 2"/)
  })

  it("keeps the page title for assistive tech, once", () => {
    expect(count(page(), "<h1")).toBe(1)
    expect(page()).toMatch(/<h1[^>]*sr-only[^>]*>Past papers<\/h1>/)
  })

  it("lays two paper groups side by side on a wide screen", () => {
    expect(page()).toMatch(/lg:grid-cols-2/)
  })

  it("never writes an exclamation mark", () => {
    expect(text(page())).not.toContain("!")
  })
})

describe("PastPapers: the first line and the subject choice", () => {
  it("opens with the subject's qualification level", () => {
    const out = page()
    expect(text(out)).toContain("Cambridge IGCSE")
    // The subline comes before the subject choice.
    expect(out.indexOf("Cambridge IGCSE")).toBeLessThan(out.indexOf('role="radiogroup"'))
  })

  it("hides the line when the level is unknown, leaving no empty line behind", () => {
    const firstLine = (html: string) => html.slice(0, html.indexOf('role="radiogroup"'))
    expect(firstLine(page())).toContain("<p")
    api.subjectLevel = null
    expect(text(page())).not.toContain("Cambridge IGCSE")
    expect(firstLine(page())).not.toContain("<p")
    api.subjectLevel = "igcse"
    api.levels = []
    expect(text(page())).not.toContain("Cambridge IGCSE")
    expect(firstLine(page())).not.toContain("<p")
    api.levels = undefined
    expect(text(page())).not.toContain("Cambridge IGCSE")
    expect(firstLine(page())).not.toContain("<p")
  })

  it("offers the subjects as one radiogroup with the first checked", () => {
    const out = page()
    expect(count(out, 'role="radiogroup"')).toBe(1)
    expect(out).toMatch(/role="radio"[^>]*aria-checked="true"[^>]*>(?:(?!<\/button>)[\s\S])*Maths/)
  })

  it("has no subject choice with a single subject", () => {
    api.subjects = [SUBJECTS[0]]
    expect(page()).not.toContain('role="radiogroup"')
  })
})

describe("PastPapers: loading, error and empty", () => {
  it("shows ghost rows while the papers load, with the subject choice still there", () => {
    api.papersStatus = "pending"
    api.papers = undefined
    const out = page()
    expect(out).toContain('aria-label="Loading"')
    expect(out).toContain('role="radiogroup"')
    expect(out).not.toContain("</h2>")
  })

  it("shows ghost rows while the subjects load, and never an empty list for a blank subject", () => {
    api.subjects = []
    api.overviewStatus = "pending"
    api.papersStatus = "pending"
    api.papers = undefined
    const out = page()
    expect(out).toContain('aria-label="Loading"')
    expect(text(out)).not.toMatch(/No\s+papers/)
    expect(text(out)).not.toContain("No subjects yet")
  })

  it("says so, with a retry, when the subjects cannot load", () => {
    api.subjects = []
    api.overviewStatus = "error"
    const out = page()
    expect(text(out)).toContain("We couldn’t load your subjects")
    expect(button(out, "Try again")).not.toBe("")
  })

  it("says there are no subjects once it knows", () => {
    api.subjects = []
    expect(text(page())).toContain("No subjects yet")
  })

  it("names the failure and offers a retry when the papers cannot load and nothing is cached", () => {
    api.papersStatus = "error"
    api.papers = undefined
    api.papersError = new Error("boom")
    const out = page()
    expect(text(out)).toContain("We couldn’t load past papers")
    expect(button(out, "Try again")).not.toBe("")
    expect(out).not.toContain("0580/42")
  })

  it("keeps the cached list when a refresh fails, with a notice and a retry", () => {
    api.papersStatus = "error"
    api.papersError = new Error("boom")
    const out = page()
    expect(text(out)).toContain("0580/42 · May/June 2025")
    expect(text(out)).toContain("Couldn’t refresh past papers")
    expect(text(out)).toContain("Showing your last loaded list.")
    expect(text(out)).not.toContain("We couldn’t load past papers")
    expect(button(out, "Try again")).not.toBe("")
  })

  it("shows the refresh notice and retry alongside a cached empty list", () => {
    api.papersStatus = "error"
    api.papersError = new Error("boom")
    api.papers = { subjectCode: "0580", papers: [] }
    const out = page()
    expect(text(out)).toContain("No Maths papers to print yet")
    expect(text(out)).toContain("Couldn’t refresh past papers")
    expect(button(out, "Try again")).not.toBe("")
  })

  it("shows the retry working while the refresh is in flight", () => {
    api.papersStatus = "error"
    api.papersError = new Error("boom")
    api.papersFetching = true
    const retry = button(page(), "Try again")
    expect(isDisabled(retry)).toBe(true)
    expect(retry).toContain('aria-busy="true"')
    api.papersFetching = false
    const idle = button(page(), "Try again")
    expect(isDisabled(idle)).toBe(false)
    expect(idle).not.toContain("aria-busy")
  })

  it("does not show the refresh notice on a healthy list", () => {
    expect(text(page())).not.toContain("Couldn’t refresh")
  })

  it("is honest about a subject with no papers, and points to the others", () => {
    api.papers = { subjectCode: "0580", papers: [] }
    const out = text(page())
    expect(out).toContain("No Maths papers to print yet")
    expect(out).toContain("We're adding them. Try Physics for now.")
  })

  it("keeps the subject choice on the empty state, so the student can move on", () => {
    api.papers = { subjectCode: "0580", papers: [] }
    expect(page()).toContain('role="radiogroup"')
  })
})

describe("PastPaperSheet (PQ)", () => {
  it("prints the selected paper and navigates after creation", async () => {
    sheet()
    expect(api.printClick).toBeTypeOf("function")
    api.printClick?.()
    await vi.waitFor(() => expect(api.navigate).toHaveBeenCalledWith("/student/practice/print/a-9"))
    expect(api.create).toHaveBeenCalledWith({ paperId: "p42", timed: true })
  })

  it("names the paper and where it sits, with the subject dot and the marks", () => {
    const out = sheet()
    expect(out).toMatch(/<h2[^>]*>0580\/42 · May\/June 2025<\/h2>/)
    expect(text(out)).toContain("Maths · Paper 4 · 80 marks")
    expect(out).toMatch(/<i aria-hidden="true"[^>]*style="background:/)
  })

  it("keeps the spaces around the Mono digits in the sub line", () => {
    // The sub line is an inline-flex row, where each bare text run is its own item and loses its edge spaces.
    // So the whole line must be one child beside the dot, or it reads "Paper4·80marks".
    expect(sheet()).toMatch(/<\/i><span>Maths · Paper <span class="font-mono">4<\/span> · <span class="font-mono">80<\/span> marks<\/span>/)
  })

  it("offers timed first, pressed, and print second", () => {
    const out = sheet()
    expect(count(out, 'role="radio"')).toBe(2)
    expect(out).toMatch(/<div[^>]*role="radiogroup"[^>]*aria-label="How do you want to do it"/)
    expect(out).toMatch(/role="radio"[^>]*aria-checked="true"[^>]*>(?:(?!<\/button>)[\s\S])*Do it timed/)
    expect(out).toMatch(/role="radio"[^>]*aria-checked="false"[^>]*>(?:(?!<\/button>)[\s\S])*Just print it/)
    expect(text(out)).toContain("2 h 30 on paper, then type your answers in")
  })

  it("makes the pressed option the one tab stop, so arrows move within the group", () => {
    const out = sheet()
    expect(out).toMatch(/role="radio"[^>]*aria-checked="true"[^>]*tabindex="0"/)
    expect(out).toMatch(/role="radio"[^>]*aria-checked="false"[^>]*tabindex="-1"/)
  })

  it("sets the time and the question count in Mono", () => {
    const out = sheet()
    expect(out).toMatch(/font-mono[^>]*>80</)
    expect(out).toMatch(/font-mono[^>]*>18</)
  })

  it("offers only print when the paper has no clock", () => {
    const out = sheet(paper({ durationMinutes: null }))
    expect(count(out, 'role="radio"')).toBe(1)
    expect(out).toMatch(/aria-checked="true"[^>]*>(?:(?!<\/button>)[\s\S])*Just print it/)
    expect(text(out)).not.toContain("Do it timed")
  })

  it("prints with a ready button and the hint", () => {
    const out = sheet()
    expect(isDisabled(button(out, "Print paper"))).toBe(false)
    expect(text(out)).toContain("Prints 18 questions. Lemely marks the answers you type in.")
  })

  it("cannot print a paper with nothing to print, and says so", () => {
    const out = sheet(paper({ questionCount: 0 }))
    expect(isDisabled(button(out, "Print paper"))).toBe(true)
    expect(text(out)).toContain("We can’t print this one yet.")
    expect(text(out)).not.toContain("Prints 0 questions")
  })

  it("shows the busy button and locks it while the paper is made", () => {
    api.creating = true
    const out = sheet()
    expect(text(out)).toContain("Getting it ready…")
    expect(isDisabled(button(out, "Getting it ready"))).toBe(true)
  })

  it("shows an alert and keeps the retry open after an ordinary failure", () => {
    api.createError = new ApiError(500, "x")
    const out = sheet()
    expect(out).toMatch(/role="alert"[^>]*>\s*Couldn’t get this paper ready\. Try again\./)
    expect(isDisabled(button(out, "Print paper"))).toBe(false)
  })

  it("shows an alert and closes the retry after a 409, which retrying cannot fix", () => {
    api.createError = new ApiError(409, "none servable")
    const out = sheet()
    expect(out).toMatch(/role="alert"[^>]*>\s*We can’t print this one yet\./)
    expect(isDisabled(button(out, "Print paper"))).toBe(true)
  })

  it("has no alert before anything went wrong", () => {
    expect(sheet()).not.toContain('role="alert"')
  })

  it("never writes an exclamation mark", () => {
    expect(text(sheet())).not.toContain("!")
  })
})

describe("wiring that a server render cannot reach", () => {
  const sheetSrc = readFileSync(join(SRC, "PastPaperSheet.tsx"), "utf8")
  const pageSrc = readFileSync(join(SRC, "PastPapers.tsx"), "utf8")

  it("the sheet stays open while the paper is made", () => {
    expect(sheetSrc).toMatch(/onOpenChange=\{\(open\) => \{?[^}]*canDismissSheet\(pending\)/)
  })

  it("the sheet hands keyboard focus to the print button, or the chosen option, when a failure appears", () => {
    expect(sheetSrc).toMatch(/useEffect\(\(\) => \{\s*if \(failed\) \(retryable \? ctaRef : checkedRef\)\.current\?\.focus\(\)\s*\}, \[failed, retryable\]\)/)
  })

  it("the option group roves with the arrow keys", () => {
    expect(sheetSrc).toMatch(/onKeyDown=\{\(e\) => radioKeyDown\(e, /)
  })

  it("focus returns through the shared sheet, which records the row that opened it", () => {
    expect(sheetSrc).toMatch(/from "@\/components\/ui\/sheet"/)
    expect(sheetSrc).not.toMatch(/onCloseAutoFocus/)
    // The rows stay mounted behind the sheet, so the opener is still there to take focus back.
    expect(pageSrc).toMatch(/\{open \? <PastPaperSheet/)
  })

  it("the page reads its list through QueryState, over the gated query", () => {
    expect(pageSrc).toMatch(/import \{[^}]*\bQueryState\b[^}]*\} from "@\/components\/ui\/query-state"/)
    expect(pageSrc).toMatch(/<QueryState\b/)
    expect(pageSrc).toMatch(/gatePapersQuery\(/)
  })

  it("every file carries its Hallmark stamp", () => {
    for (const src of [sheetSrc, pageSrc]) expect(src).toMatch(/Hallmark · pre-emit critique: P[3-5] H[3-5] E[3-5] S[3-5] R[3-5] V[3-5]/)
  })
})
