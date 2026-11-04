import { binnyMood, deriveNextAction, todayList } from "@/portals/student/home/model"
import { FIXTURES, STATES, type StateId } from "./fixtures"
import { renderBinny } from "./binny-island"

type Variant = "a" | "b" | "c"
const CONTROLS = {
  state: STATES,
  theme: ["light", "dark"],
  motion: ["full", "reduce"],
  width: ["desktop", "mobile"],
} as const
type ControlName = keyof typeof CONTROLS

function readParams(): Record<ControlName, string> {
  const q = new URLSearchParams(location.search)
  const pick = (name: ControlName) => {
    const v = q.get(name)
    const allowed = CONTROLS[name] as readonly string[]
    return v && allowed.includes(v) ? v : allowed[0]
  }
  return { state: pick("state"), theme: pick("theme"), motion: pick("motion"), width: pick("width") }
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
    exams: facts.subjects.some((s) => s.nextExamOn !== null) ? "yes" : "no",
  })
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
  apply(root, variant, params)
}
