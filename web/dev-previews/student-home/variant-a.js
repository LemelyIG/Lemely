/*
 * Variant A: interaction and motion. Preview-only.
 *
 * The page's final state is its default. When motion is allowed (no
 * prefers-reduced-motion and the preview's data-motion is not "reduce"), the
 * root gets .a-motion: CSS animations then wait on their first frame until the
 * section scrolls into view (.is-in) and run once. This script measures the
 * distances the markers travel, drives the exam strip's selection and keyboard
 * movement, and gives Binny its small reactions.
 */
import { renderBinny } from "./binny-island"

const root = document.getElementById("sh-root")
const reduceMQ = window.matchMedia("(prefers-reduced-motion: reduce)")
const motionOn = () => !reduceMQ.matches && root.dataset.motion !== "reduce"

/* ---------- motion switch ---------- */
function syncMotion() {
  root.classList.toggle("a-motion", motionOn())
}

/* Progress of cubic-bezier(0.16, 1, 0.3, 1) as a function of time, inverted:
   returns the time fraction at which the eased progress first reaches `p`. */
function timeAtProgress(p) {
  const [x1, y1, x2, y2] = [0.16, 1, 0.3, 1]
  const bez = (t, a, b) => 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t ** 2 * b + t ** 3
  for (let i = 0; i <= 400; i++) {
    const t = i / 400
    if (bez(t, y1, y2) >= p) return bez(t, x1, x2)
  }
  return 1
}

/* ---------- measurements for slides and bounces ---------- */
const JOURNEY_MS = 1100

function measureJourneys() {
  for (const j of document.querySelectorAll(".a-journey")) {
    const me = j.querySelector(".a-j-me")
    const trail = j.querySelector(".a-j-trail")
    if (!me || !j.offsetWidth) continue
    if (!trail) {
      j.style.setProperty("--from", "0px")
      continue
    }
    const startX = trail.offsetLeft
    const nowX = me.offsetLeft
    j.style.setProperty("--from", `${startX - nowX}px`)
    for (const stone of j.querySelectorAll(".a-stone.is-passed")) {
      const x = stone.offsetLeft
      if (x < startX || nowX <= startX) {
        stone.dataset.pass = "0"
        continue
      }
      stone.dataset.pass = "1"
      const t = timeAtProgress((x - startX) / (nowX - startX))
      stone.style.setProperty("--bd", `${Math.round(t * JOURNEY_MS)}ms`)
    }
  }
}

function measureRuler() {
  for (const track of document.querySelectorAll(".a-lane-track")) {
    const marker = track.querySelector(".a-marker")
    const tail = track.querySelector(".a-tail")
    if (!marker || !track.offsetWidth) continue
    if (!tail) {
      track.style.setProperty("--from", "0px")
      continue
    }
    const start = tail.classList.contains("is-down") ? tail.offsetLeft + tail.offsetWidth : tail.offsetLeft
    track.style.setProperty("--from", `${start - marker.offsetLeft}px`)
  }
}

function measure() {
  measureJourneys()
  measureRuler()
}

/* ---------- run each section's motion once, when it comes into view ---------- */
const seen = new IntersectionObserver(
  (entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue
      e.target.classList.add("is-in")
      seen.unobserve(e.target)
    }
  },
  { threshold: 0.2 },
)

function observeSections() {
  for (const s of document.querySelectorAll("[data-anim]")) {
    if (!s.classList.contains("is-in")) seen.observe(s)
  }
}

/* ---------- exam strip: select an exam, show its card, follow it in the headline ---------- */
const exams = document.querySelector(".a-exams")
const headline = document.getElementById("a-exams-h")
const defaultHeadline = headline ? headline.innerHTML : ""

const visible = (el) => el.getClientRects().length > 0

function allowedCard(card) {
  const state = root.dataset.state
  if (card.matches('[data-only-state="one-paper"]')) return state === "one-paper"
  if (card.matches('[data-needs="many-papers"]')) return state !== "one-paper"
  return true
}

function markers(selector) {
  return [...exams.querySelectorAll(selector)].filter((b) => {
    const state = root.dataset.state
    if (b.matches('[data-needs="many-papers"]') && state === "one-paper") return false
    return true
  })
}

function selectExam(code, { focus = false, announce = true } = {}) {
  if (!exams) return
  for (const b of exams.querySelectorAll("[data-exam]:is(button)")) {
    const on = b.dataset.exam === code
    b.classList.toggle("is-sel", on)
    b.setAttribute("aria-pressed", String(on))
  }
  let shown = null
  for (const card of exams.querySelectorAll(".a-excard-in")) {
    const on = card.dataset.exam === code && allowedCard(card)
    card.classList.toggle("is-sel", on)
    card.classList.remove("is-opening")
    if (on) shown = card
  }
  if (shown && motionOn() && announce) {
    void shown.offsetWidth
    shown.classList.add("is-opening")
  }
  const first = markers(".a-ex")[0]
  if (headline) {
    if (!first || first.dataset.exam === code || !shown) {
      headline.innerHTML = defaultHeadline
    } else {
      const name = shown.querySelector(".a-exc-t b")?.textContent ?? ""
      const days = shown.querySelectorAll(".a-exc-m .a-mono")[1]?.textContent ?? ""
      headline.innerHTML = `<span class="a-mono">${days}</span> days to ${name}.`
    }
  }
  if (focus) {
    const target = [...exams.querySelectorAll(`[data-exam="${code}"]:is(button)`)].find(visible)
    target?.focus()
  }
}

function resetExam() {
  if (!exams) return
  const first = markers(".a-ex")[0]
  if (first) selectExam(first.dataset.exam, { announce: false })
}

if (exams) {
  exams.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-exam]")
    if (b) selectExam(b.dataset.exam)
  })
  exams.addEventListener("keydown", (e) => {
    const b = e.target.closest("button[data-exam]")
    if (!b) return
    const horizontal = b.classList.contains("a-ex")
    const next = horizontal ? "ArrowRight" : "ArrowDown"
    const prev = horizontal ? "ArrowLeft" : "ArrowUp"
    if (e.key !== next && e.key !== prev) return
    e.preventDefault()
    const group = markers(horizontal ? ".a-ex" : ".a-exlist-b")
    const i = group.indexOf(b)
    const step = (e.key === next) === (getComputedStyle(b).direction !== "rtl") ? 1 : -1
    const to = group[(i + step + group.length) % group.length]
    if (to) selectExam(to.dataset.exam, { focus: true })
  })
}

/* ---------- Binny: a jump on tap, a lean toward the action, a cheer for the streak ---------- */
function binnyTile() {
  return document.querySelector('[data-when-state="ready"] .ah-binny-tile')
}

document.addEventListener("click", (e) => {
  const tile = e.target.closest(".ah-binny-tile")
  if (!tile || !motionOn()) return
  tile.classList.remove("is-jump")
  void tile.offsetWidth
  tile.classList.add("is-jump")
})
document.addEventListener("animationend", (e) => {
  const tile = e.target.closest?.(".ah-binny-tile")
  if (tile) tile.classList.remove("is-jump", "is-cheer")
})

function lean(on) {
  const tile = binnyTile()
  if (tile) tile.classList.toggle("is-lean", on && motionOn())
}
for (const btn of document.querySelectorAll(".a-act-btn")) {
  btn.addEventListener("pointerenter", () => lean(true))
  btn.addEventListener("pointerleave", () => lean(false))
  btn.addEventListener("focus", () => lean(true))
  btn.addEventListener("blur", () => lean(false))
}

const week = document.querySelector('[data-when-state="ready"] .ah-week')
let cheering = false
function cheer(on) {
  const tile = binnyTile()
  const kept = !["streak-zero", "one-paper"].includes(root.dataset.state)
  if (!tile || !kept) return
  if (on && !cheering) {
    cheering = true
    renderBinny(tile, "streak-kept")
    if (motionOn()) {
      tile.classList.remove("is-cheer")
      void tile.offsetWidth
      tile.classList.add("is-cheer")
    }
  } else if (!on && cheering) {
    cheering = false
    renderBinny(tile, root.dataset.mood)
  }
}
if (week) {
  week.addEventListener("pointerenter", () => cheer(true))
  week.addEventListener("pointerleave", () => cheer(false))
  week.addEventListener("focusin", () => cheer(true))
  week.addEventListener("focusout", () => cheer(false))
}

/* ---------- wiring ---------- */
new MutationObserver((records) => {
  const names = new Set(records.map((r) => r.attributeName))
  if (names.has("data-motion")) syncMotion()
  if (names.has("data-state") || names.has("data-width")) {
    cheering = false
    requestAnimationFrame(() => {
      measure()
      resetExam()
      observeSections()
    })
  }
}).observe(root, { attributes: true, attributeFilter: ["data-motion", "data-state", "data-width"] })
reduceMQ.addEventListener("change", syncMotion)
window.addEventListener("resize", () => requestAnimationFrame(measure))

syncMotion()
measure()
resetExam()
observeSections()
