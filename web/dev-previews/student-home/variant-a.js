/*
 * Variant A: interaction and motion. Preview-only.
 *
 * The page's final state is its default. When motion is allowed (no
 * prefers-reduced-motion and the preview's data-motion is not "reduce"), the
 * root gets .a-motion: CSS animations then wait on their first frame until the
 * section scrolls into view (.is-in) and run once. This script measures the
 * distances the markers travel, drives the exam tiles' selection, keyboard
 * movement and count-down, and gives Binny its small reactions.
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
      if (e.target.classList.contains("a-exams")) countDown()
    }
  },
  { threshold: 0.2 },
)

function observeSections() {
  for (const s of document.querySelectorAll("[data-anim]")) {
    if (!s.classList.contains("is-in")) seen.observe(s)
  }
}

/* ---------- exams: select a countdown tile; the subtitle follows it ---------- */
const exams = document.querySelector(".a-exams")
const subtitle = document.getElementById("a-exams-sub")
const defaultSubtitle = subtitle ? subtitle.innerHTML : ""

function allowed(el) {
  const state = root.dataset.state
  if (el.matches('[data-only-state="one-paper"]')) return state === "one-paper"
  if (el.matches('[data-needs="many-papers"]')) return state !== "one-paper"
  return true
}

const tiles = () => (exams ? [...exams.querySelectorAll(".a-xt")].filter(allowed) : [])

function selectExam(code, { focus = false } = {}) {
  if (!exams) return
  let shown = null
  for (const t of exams.querySelectorAll(".a-xt")) {
    const on = t.dataset.exam === code && allowed(t)
    t.classList.toggle("is-sel", on)
    t.querySelector(".a-xt-sel")?.setAttribute("aria-pressed", String(on))
    if (on) shown = t
  }
  for (const p of exams.querySelectorAll(".a-xb-pin")) p.classList.toggle("is-sel", p.dataset.exam === code && allowed(p))
  const first = tiles()[0]
  if (subtitle) {
    if (!shown || !first || first === shown) {
      subtitle.innerHTML = defaultSubtitle
    } else {
      const days = shown.querySelector(".a-xt-n")?.dataset.n ?? ""
      const name = shown.querySelector(".a-xt-name")?.lastChild?.textContent.trim() ?? ""
      const date = shown.querySelector(".a-xt-date")?.textContent ?? ""
      subtitle.innerHTML = `<span class="a-mono">${days}</span> days to ${name} · <span class="a-mono">${date}</span>`
    }
  }
  if (focus) shown?.querySelector(".a-xt-sel")?.focus()
}

function resetExam() {
  const first = tiles()[0]
  if (first) selectExam(first.dataset.exam)
}

/* Day counts tick down from +10 to their value, once, as the tiles pop in. */
function countDown() {
  if (!motionOn() || !exams) return
  for (const [i, t] of tiles().entries()) {
    const n = t.querySelector(".a-xt-n")
    const target = Number(n.dataset.n)
    const start = performance.now() + 820 + i * 140
    const dur = 900
    n.textContent = String(target + 10)
    const step = (now) => {
      const k = Math.min(1, Math.max(0, (now - start) / dur))
      const eased = 1 - (1 - k) ** 3
      n.textContent = String(Math.round(target + 10 - 10 * eased))
      if (k < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }
}

if (exams) {
  exams.addEventListener("click", (e) => {
    const b = e.target.closest(".a-xt-sel")
    if (b) selectExam(b.dataset.exam)
  })
  exams.addEventListener("keydown", (e) => {
    const b = e.target.closest(".a-xt-sel")
    if (!b) return
    const forward = ["ArrowRight", "ArrowDown"]
    const back = ["ArrowLeft", "ArrowUp"]
    if (![...forward, ...back].includes(e.key)) return
    e.preventDefault()
    const group = tiles()
    const i = group.findIndex((t) => t.contains(b))
    const horizontal = e.key === "ArrowRight" || e.key === "ArrowLeft"
    const rtl = horizontal && getComputedStyle(b).direction === "rtl"
    const step = (forward.includes(e.key) ? 1 : -1) * (rtl ? -1 : 1)
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

/* The streak cheer: hovering the week, focusing the streak button or pressing it makes
   Binny cheer and say "Day 9. Streak kept." for a moment, then the mood caption returns. */
const week = document.querySelector('[data-when-state="ready"] .ah-week')
const CHEER_MS = 2400
let cheering = false
let cheerTimer = 0
function endCheer() {
  clearTimeout(cheerTimer)
  cheerTimer = 0
  const tile = binnyTile()
  if (!cheering || !tile) return
  cheering = false
  tile.closest(".ah-binny")?.classList.remove("is-cheering")
  renderBinny(tile, root.dataset.mood)
}
function cheer() {
  const tile = binnyTile()
  const kept = !["streak-zero", "one-paper"].includes(root.dataset.state)
  if (!tile || !kept) return
  if (!cheering) {
    cheering = true
    tile.closest(".ah-binny")?.classList.add("is-cheering")
    renderBinny(tile, "streak-kept")
  }
  if (motionOn()) {
    tile.classList.remove("is-cheer")
    void tile.offsetWidth
    tile.classList.add("is-cheer")
  }
  clearTimeout(cheerTimer)
  cheerTimer = setTimeout(endCheer, CHEER_MS)
}
if (week) {
  week.addEventListener("pointerenter", cheer)
  week.addEventListener("focusin", cheer)
  week.addEventListener("click", (e) => {
    if (e.target.closest(".ah-streak")) cheer()
  })
}

/* ---------- marking: walk the demo stages once, ending on "Marking question 7 of 12" ---------- */
const STAGE_MS = 1500
let stageTimers = []
function setStage(prog, n) {
  prog.dataset.stage = String(n)
  const bar = prog.querySelector(".a-prog-bar")
  const text = prog.querySelector(`[data-stage-text="${n}"]`)?.textContent.trim() ?? ""
  if (bar) {
    bar.setAttribute("aria-valuenow", n === 3 ? "7" : "0")
    bar.setAttribute("aria-valuetext", text)
  }
}
function runMarkingDemo() {
  for (const t of stageTimers) clearTimeout(t)
  stageTimers = []
  const prog = document.querySelector('[data-when-action="marking"] .a-prog')
  if (!prog) return
  if (!motionOn() || root.dataset.action !== "marking") {
    setStage(prog, 3)
    return
  }
  setStage(prog, 1)
  stageTimers.push(setTimeout(() => setStage(prog, 2), STAGE_MS))
  stageTimers.push(setTimeout(() => setStage(prog, 3), STAGE_MS * 2))
}

/* ---------- wiring ---------- */
new MutationObserver((records) => {
  const names = new Set(records.map((r) => r.attributeName))
  if (names.has("data-motion")) {
    syncMotion()
    if (!motionOn()) runMarkingDemo()
  }
  if (names.has("data-state")) runMarkingDemo()
  if (names.has("data-state") || names.has("data-width")) {
    endCheer()
    requestAnimationFrame(() => {
      measure()
      resetExam()
      observeSections()
    })
  }
}).observe(root, { attributes: true, attributeFilter: ["data-motion", "data-state", "data-width"] })
reduceMQ.addEventListener("change", () => {
  syncMotion()
  if (!motionOn()) runMarkingDemo()
})
window.addEventListener("resize", () => requestAnimationFrame(measure))

syncMotion()
measure()
resetExam()
observeSections()
runMarkingDemo()
