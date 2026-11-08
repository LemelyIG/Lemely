import { binnyMood, deriveNextAction, todayList } from "@/portals/student/home/model"
import { FIXTURES, STATES, type StateId } from "./fixtures"
import { renderBinny } from "./binny-island"

type Variant = "a" | "b" | "c"
const CONTROLS = {
  state: STATES,
  theme: ["light", "dark"],
  motion: ["full", "reduce"],
  width: ["desktop", "mobile"],
  /* Phone frame (design A, shell below 721px): which platform's native chrome to draw, and
     whether the page is a tab root (large title) or a pushed detail page (compact bar + back). */
  platform: ["ios", "android"],
  page: ["root", "detail"],
} as const
type ControlName = keyof typeof CONTROLS

function readParams(): Record<ControlName, string> {
  const q = new URLSearchParams(location.search)
  const pick = (name: ControlName) => {
    const v = q.get(name)
    const allowed = CONTROLS[name] as readonly string[]
    return v && allowed.includes(v) ? v : allowed[0]
  }
  return Object.fromEntries(
    (Object.keys(CONTROLS) as ControlName[]).map((name) => [name, pick(name)]),
  ) as Record<ControlName, string>
}

/* Progress card (Mistakes beaten) is the default. gstate names which authored data
   set it shows; "none" keeps the old Garden for states the card does not cover yet. */
const GSTATE: Partial<Record<StateId, string>> = {
  populated: "pop", "result-in": "pop", marking: "pop", "no-plan": "pop", "no-exams": "pop",
  "streak-zero": "pop", loading: "pop", error: "pop",
  new: "new", sparse0: "sp0", sparse1: "sp1", sparse2: "sp2",
}

function apply(root: HTMLElement, variant: Variant, params: Record<ControlName, string>): void {
  const { facts } = FIXTURES[params.state as StateId]
  const action = deriveNextAction(facts, { preferClosestExam: variant === "b" })
  const mood = binnyMood(facts)
  Object.assign(root.dataset, {
    variant,
    state: params.state,
    action: action.kind,
    today: todayList(facts).map((a) => a.kind).join(" "),
    mood,
    theme: params.theme,
    motion: params.motion,
    width: params.width,
    platform: params.platform,
    page: params.page,
    exams: facts.subjects.some((s) => s.nextExamOn !== null) ? "yes" : "no",
  })
  root.dataset.garden = "1"
  root.dataset.gstate = GSTATE[params.state as StateId] ?? "none"
  document.querySelectorAll("[data-binny]").forEach((slot) => renderBinny(slot, mood))
  const qs = new URLSearchParams(params).toString()
  history.replaceState(null, "", `${location.pathname}?${qs}`)
  document.querySelectorAll<HTMLAnchorElement>("a[data-variant-link]").forEach((a) => {
    a.href = `./student-home-${a.dataset.variantLink}.html?${qs}`
    a.setAttribute("aria-current", a.dataset.variantLink === variant ? "page" : "false")
  })
}

export function mountHome(variant: Variant): void {
  const root = document.getElementById("sh-root")
  if (!root) throw new Error("student home preview: #sh-root missing")
  const params = readParams()
  for (const name of Object.keys(CONTROLS) as ControlName[]) {
    const select = document.querySelector<HTMLSelectElement>(`select[data-control="${name}"]`)
    if (!select) continue
    select.replaceChildren(
      ...(CONTROLS[name] as readonly string[]).map((v) => new Option(v, v, false, v === params[name])),
    )
    select.addEventListener("change", () => {
      params[name] = select.value
      apply(root, variant, params)
    })
  }
  /* In-page controls (the phone frame's back button, a tap on the active tab) change a param
     the same way the toolbar does, so the URL and the toolbar stay in step. */
  root.addEventListener("sh:param", (e) => {
    const { name, value } = (e as CustomEvent<{ name: ControlName; value: string }>).detail
    if (!(CONTROLS[name] as readonly string[]).includes(value)) return
    params[name] = value
    const select = document.querySelector<HTMLSelectElement>(`select[data-control="${name}"]`)
    if (select) select.value = value
    apply(root, variant, params)
  })
  apply(root, variant, params)
}
