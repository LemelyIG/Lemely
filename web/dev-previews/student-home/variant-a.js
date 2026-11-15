/*
 * Variant A: interaction and motion. Preview-only.
 *
 * The page's final state is its default. When motion is allowed (no
 * prefers-reduced-motion and the preview's data-motion is not "reduce"), the
 * root gets .a-motion: CSS animations then wait on their first frame until the
 * section scrolls into view (.is-in) and run once. This script measures the
 * distances the markers travel, drives the exam tiles' selection and keyboard
 * movement, and gives Binny its small reactions (in words when motion is off).
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

/* ---------- measurements for slides and stone acknowledgements ---------- */
const JOURNEY_MS = 500

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
      /* Carry what the tile doesn't: the exam's place in the order, not its day count. */
      const nth = ["First", "Second", "Third", "Fourth", "Fifth"][tiles().indexOf(shown)] ?? "Next"
      const name = shown.querySelector(".a-xt-name")?.lastChild?.textContent.trim() ?? ""
      const date = shown.querySelector(".a-xt-date")?.textContent ?? ""
      subtitle.innerHTML = `${nth} exam: ${name}, <span class="a-mono">${date}</span>`
    }
  }
  if (focus) shown?.querySelector(".a-xt-sel")?.focus()
}

function resetExam() {
  const first = tiles()[0]
  if (first) selectExam(first.dataset.exam)
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

/* With reduced motion the jump is off, so the tap answers in words: the caption says
   "Hi, Mariam." for a moment, then the mood caption returns. */
const GREET_MS = 2400
let greetTimer = 0
function endGreet() {
  clearTimeout(greetTimer)
  greetTimer = 0
  for (const b of document.querySelectorAll(".ah-binny.is-greeting")) b.classList.remove("is-greeting")
}
function greet(tile) {
  const figure = tile.closest(".ah-binny")
  if (!figure) return
  endCheer()
  figure.classList.add("is-greeting")
  clearTimeout(greetTimer)
  greetTimer = setTimeout(endGreet, GREET_MS)
}

document.addEventListener("click", (e) => {
  const tile = e.target.closest(".ah-binny-tile")
  if (!tile) return
  if (!motionOn()) {
    greet(tile)
    return
  }
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
  const kept = !["streak-zero", "one-paper", "sparse3"].includes(root.dataset.state)
  if (!tile || !kept) return
  endGreet()
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

/* ---------- app shell: toolbar offset, popovers, dialogs, subjects, notifications ---------- */
const toolbar = document.querySelector(".sh-toolbar")
const side = document.getElementById("as-side")
const pops = [...document.querySelectorAll("details.as-pop")]
const dialogs = [...document.querySelectorAll("dialog.as-modal")]

// The preview toolbar is sticky above the shell; the sidebar and top bar stick below it.
if (toolbar) {
  const setTop = () => root.style.setProperty("--as-top", `${toolbar.offsetHeight}px`)
  new ResizeObserver(setTop).observe(toolbar)
  setTop()
}

// The floating bar lifts once the page scrolls under it.
const bar = document.querySelector(".as-bar")
const syncStuck = () => bar?.classList.toggle("is-stuck", window.scrollY > 0)
window.addEventListener("scroll", syncStuck, { passive: true })
syncStuck()

// Settings: a native modal dialog (the teacher's SettingsModal). Focus is trapped inside
// below, Esc closes, and closing returns focus to the gear. A click on the backdrop closes
// too. It opens on Profile; the rail's tabs show one section at a time. The account panel
// is a top-bar popover like the bell (see below), as on the teacher's top bar.
const themeSelect = document.querySelector('select[data-control="theme"]')
const darkMQ = window.matchMedia("(prefers-color-scheme: dark)")
let themeChoice = null
function syncThemeRadios() {
  const choice = themeChoice ?? root.dataset.theme
  for (const r of document.querySelectorAll('.as-seg input[name="theme"]')) r.checked = r.value === choice
}
function applyTheme(choice) {
  themeChoice = choice === "system" ? "system" : null
  const theme = choice === "system" ? (darkMQ.matches ? "dark" : "light") : choice
  if (themeSelect && themeSelect.value !== theme) {
    themeSelect.value = theme
    themeSelect.dispatchEvent(new Event("change"))
  }
}
document.addEventListener("click", (e) => {
  const opener = e.target.closest("[data-a-open]")
  if (!opener) return
  const dlg = document.getElementById(opener.dataset.aOpen)
  closePops()
  if (side?.matches(":popover-open")) side.hidePopover()
  if (dlg.id === "as-settings") {
    syncThemeRadios()
    showSettingsTab("profile")
  }
  dlg.showModal()
})
function showSettingsTab(id, { focus = false } = {}) {
  const dlg = document.getElementById("as-settings")
  for (const tab of dlg.querySelectorAll("[data-a-tab]")) {
    const on = tab.dataset.aTab === id
    if (on) tab.setAttribute("aria-current", "page")
    else tab.removeAttribute("aria-current")
    if (on && focus) tab.focus()
    if (on) tab.scrollIntoView({ block: "nearest", inline: "nearest" })
  }
  for (const panel of dlg.querySelectorAll("[data-a-panel]")) panel.hidden = panel.dataset.aPanel !== id
  dlg.querySelector(".as-set-scroll").scrollTop = 0
}
const settingsTabs = document.querySelector(".as-set-tabs")
settingsTabs?.addEventListener("click", (e) => {
  const tab = e.target.closest("[data-a-tab]")
  if (tab) showSettingsTab(tab.dataset.aTab)
})
// Arrow keys move between sections (up/down on the rail, left/right on the mobile strip).
settingsTabs?.addEventListener("keydown", (e) => {
  const keys = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }
  const tabs = [...settingsTabs.querySelectorAll("[data-a-tab]")]
  const i = tabs.indexOf(document.activeElement)
  if (i < 0) return
  let next = null
  if (e.key in keys) next = tabs[(i + keys[e.key] + tabs.length) % tabs.length]
  else if (e.key === "Home") next = tabs[0]
  else if (e.key === "End") next = tabs.at(-1)
  if (!next) return
  e.preventDefault()
  showSettingsTab(next.dataset.aTab, { focus: true })
})
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-a-close]")) e.target.closest("dialog")?.close()
})
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
for (const dlg of dialogs) {
  dlg.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return
    const items = [...dlg.querySelectorAll(FOCUSABLE)].filter((el) => el.checkVisibility())
    // Radio groups take one Tab stop: skip the unchecked radios.
    const stops = items.filter((el) => el.type !== "radio" || el.checked)
    const first = stops[0]
    const last = stops.at(-1)
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  })
  dlg.addEventListener("click", (e) => {
    if (e.target !== dlg) return
    const r = dlg.getBoundingClientRect()
    const inside = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom
    if (!inside) dlg.close()
  })
}
document.querySelector(".as-seg")?.addEventListener("change", (e) => applyTheme(e.target.value))
darkMQ.addEventListener("change", () => {
  if (themeChoice === "system") applyTheme("system")
})

// Top-bar popovers: one open at a time; outside click or Escape closes, and Escape
// returns focus to the trigger.
function closePops(except = null) {
  for (const d of pops) if (d !== except) d.open = false
}
for (const d of pops) {
  d.addEventListener("toggle", () => {
    if (!d.open) return
    closePops(d)
    if (side?.matches(":popover-open")) side.hidePopover()
  })
}
document.addEventListener("click", (e) => {
  if (!e.target.closest("details.as-pop")) closePops()
})
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return
  const open = pops.find((d) => d.open)
  if (!open) return
  open.open = false
  open.querySelector("summary").focus()
})

// At 1000px and below (the teacher's breakpoint) the sidebar is a popover: a drawer behind the top bar's menu button, or on
// mobile the "More" sheet. Once the full sidebar is back, an open popover closes.
const SIDEBAR_MIN = 1001
function closeSheetIfWide() {
  if (side?.matches(":popover-open") && root.clientWidth >= SIDEBAR_MIN) side.hidePopover()
}
window.addEventListener("resize", closeSheetIfWide)
// Opening moves focus into the sheet; closing (Esc, scrim, close button) hands it back
// to "More" through the popover API.
side?.addEventListener("toggle", (e) => {
  if (e.newState !== "open") return
  closePops()
  side.querySelector(".as-side-close")?.focus()
})

// Whether a shell element shows in a page state (mirrors the data-a-show/-hide CSS).
function inState(el, state) {
  const hide = el.dataset.aHide?.split(" ") ?? []
  const show = el.dataset.aShow?.split(" ")
  return !hide.includes(state) && (!show || show.includes(state))
}

// Subjects: a disclosure per subject. On each state, open the subject of today's
// session when it is enrolled, otherwise the first enrolled subject.
function setSubject(btn, open) {
  btn.setAttribute("aria-expanded", String(open))
  document.getElementById(btn.getAttribute("aria-controls")).hidden = !open
}
function resetSubjects() {
  const state = root.dataset.state
  const rows = [...document.querySelectorAll(".as-subjects > li")].filter((li) => li.querySelector(".as-subj") && inState(li, state))
  // Sparse states have no session today: open the first subject, the one with a paper.
  const pick = (state.startsWith("sparse") ? null : rows.find((li) => li.hasAttribute("data-current"))) ?? rows[0]
  for (const btn of document.querySelectorAll(".as-subj")) setSubject(btn, btn.closest("li") === pick)
}
document.querySelector(".as-subjects")?.addEventListener("click", (e) => {
  const btn = e.target.closest(".as-subj")
  if (btn) setSubject(btn, btn.getAttribute("aria-expanded") !== "true")
})

// Notifications: unread per state, a count on the bell, "Mark all read".
const bellSummary = document.querySelector(".as-pop-bell summary")
const bellDot = document.querySelector(".as-pop-bell .as-dot")
const markRead = document.querySelector("[data-a-markread]")
function setUnread(item, unread) {
  item.classList.toggle("is-unread", unread)
  item.querySelector(".as-unread-vh")?.remove()
  if (unread) item.insertAdjacentHTML("afterbegin", '<span class="a-vh as-unread-vh">Unread: </span>')
}
function syncCount() {
  const state = root.dataset.state
  const n = [...document.querySelectorAll(".as-items > li")].filter(
    (li) => inState(li, state) && li.querySelector(".as-item.is-unread"),
  ).length
  bellDot.hidden = n === 0
  bellSummary.setAttribute("aria-label", n ? `Notifications, ${n} unread` : "Notifications")
  markRead.disabled = n === 0
  markRead.hidden = state === "new"
}
function resetNotifications() {
  const state = root.dataset.state
  for (const li of document.querySelectorAll(".as-items > li")) {
    const when = li.dataset.unread?.split(" ") ?? []
    setUnread(li.querySelector(".as-item"), when.includes("always") || when.includes(state))
  }
  syncCount()
}
markRead?.addEventListener("click", () => {
  for (const item of document.querySelectorAll(".as-item.is-unread")) setUnread(item, false)
  syncCount()
  bellSummary.focus()
})

function resetShell() {
  closePops()
  for (const dlg of dialogs) if (dlg.open) dlg.close()
  if (side?.matches(":popover-open")) side.hidePopover()
  resetSubjects()
  resetNotifications()
  resetExamPick()
}

// Exams: the first dated exam starts picked. In sparse2 Physics has no date, so Maths leads.
function resetExamPick() {
  const code = root.dataset.state === "sparse2" ? "0580" : "0625"
  const radio = document.getElementById(`xs-many-${code}`)
  if (radio) radio.checked = true
}

/* ---------- wiring ---------- */
new MutationObserver((records) => {
  const names = new Set(records.map((r) => r.attributeName))
  if (names.has("data-motion")) {
    syncMotion()
    if (!motionOn()) runMarkingDemo()
  }
  if (names.has("data-state")) {
    runMarkingDemo()
    if (records.some((r) => r.attributeName === "data-state" && r.oldValue !== root.dataset.state)) resetShell()
  }
  if (names.has("data-width")) requestAnimationFrame(closeSheetIfWide)
  if (names.has("data-state") || names.has("data-width")) {
    endCheer()
    endGreet()
    requestAnimationFrame(() => {
      measure()
      resetExam()
      observeSections()
    })
  }
}).observe(root, { attributes: true, attributeOldValue: true, attributeFilter: ["data-motion", "data-state", "data-width"] })
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
resetShell()

/* ======================================================================================
   Native phone frame (brief 2026-11-08 §3, §6). Everything here acts only while the shell is
   phone-sized (721px and up keeps design A), and reads the platform from data-platform.
   ====================================================================================== */
const PHONE_MAX = 720
const platform = () => root.dataset.platform
/* No data-platform means `other`: design A keeps its own phone frame and none of this runs. */
const isPhone = () => Boolean(root.dataset.platform) && root.clientWidth <= PHONE_MAX
const col = document.querySelector(".as-col")
const largeTitle = document.querySelector("[data-a-lt]")
const barTitle = document.querySelector("[data-a-title]")
const tabBar = document.querySelector(".a-bottombar")
const ROOT_TITLE = barTitle?.textContent ?? "Overview"
/* A long pushed-page title, so the compact bar's truncation is on show. */
const DETAIL_TITLE = "0625 Physics · Paper 4 · May/June 2024"
const setParam = (name, value) => root.dispatchEvent(new CustomEvent("sh:param", { detail: { name, value } }))
const haptic = () => {
  if (platform() === "android") navigator.vibrate?.(10)
}

/* ---------- 1. collapse: one threshold, the large title's bottom crossing the bar ---------- */
function syncBar() {
  if (!bar) return
  if (!isPhone()) {
    bar.classList.remove("is-collapsed", "is-raised")
    return
  }
  root.style.setProperty("--pf-sy", `${window.scrollY}px`)
  if (root.dataset.page === "detail") {
    bar.classList.remove("is-collapsed")
    bar.classList.toggle("is-raised", window.scrollY > 0)
    return
  }
  const crossed = largeTitle ? largeTitle.getBoundingClientRect().bottom <= bar.getBoundingClientRect().bottom + 0.5 : false
  bar.classList.toggle("is-collapsed", crossed)
  bar.classList.toggle("is-raised", crossed)
}
let barFrame = 0
window.addEventListener(
  "scroll",
  () => {
    if (barFrame) return
    barFrame = requestAnimationFrame(() => {
      barFrame = 0
      syncBar()
    })
  },
  { passive: true },
)

function syncPage() {
  const detail = root.dataset.page === "detail"
  if (barTitle) barTitle.textContent = detail && isPhone() ? DETAIL_TITLE : ROOT_TITLE
  syncBar()
}
document.querySelector("[data-a-back]")?.addEventListener("click", () => {
  setParam("page", "root")
  window.scrollTo({ top: 0 })
})

/* ---------- 2. tab bar: tapping the active tab scrolls to top, again pops to the root ---------- */
tabBar?.addEventListener("click", (e) => {
  const tab = e.target.closest('a[aria-current="page"]')
  if (!tab || !isPhone()) return
  e.preventDefault()
  if (root.dataset.page === "detail") {
    setParam("page", "root")
    window.scrollTo({ top: 0 })
    return
  }
  window.scrollTo({ top: 0, behavior: motionOn() ? "smooth" : "auto" })
})

/* ---------- 3. bottom sheets: grabber, detents, drag to dismiss ---------- */
const settings = document.getElementById("as-settings")
const sheetOf = (el) => (el.matches("details") ? el.querySelector(".as-pop-panel") : el)
const sheetOpen = (el) => (el.matches("details, dialog") ? el.open : el.matches(":popover-open"))
const sheetHosts = [...pops, ...dialogs, side].filter(Boolean)
let active = null // { host, sheet, detents, detent }

function detentOffset(s, detent) {
  if (detent !== "medium") return 0
  const medium = window.innerHeight * 0.5
  return Math.max(0, s.offsetHeight - medium)
}
function setDetent(detent, { animate = true } = {}) {
  if (!active) return
  active.detent = detent
  const { sheet } = active
  sheet.classList.toggle("is-sheet-snapping", animate && motionOn())
  sheet.style.translate = `0 ${detentOffset(sheet, detent)}px`
  // Only top-layer sheets scale the page back: the bell and avatar panels live inside it.
  root.dataset.sheet = active.host.matches("details") ? "fit" : detent
  if (animate) haptic()
}
function openSheet(host) {
  if (!isPhone()) return
  const sheet = sheetOf(host)
  const detents = (host.dataset.detents ?? "fit").split(" ")
  active = { host, sheet, detents, detent: detents[0] }
  setDetent(detents[0], { animate: false })
}
function closeSheetState(host) {
  if (active?.host !== host) return
  active.sheet.style.translate = ""
  active.sheet.classList.remove("is-sheet-snapping")
  active = null
  delete root.dataset.sheet
}
function dismissSheet() {
  if (!active) return
  const { host, sheet } = active
  const finish = () => {
    if (host.matches("details")) host.open = false
    else if (host.matches("dialog")) host.close()
    else host.hidePopover()
  }
  if (!motionOn()) return finish()
  sheet.classList.add("is-sheet-snapping")
  sheet.style.translate = `0 ${sheet.offsetHeight}px`
  delete root.dataset.sheet
  sheet.addEventListener("transitionend", finish, { once: true })
  setTimeout(finish, 450) // in case the transition is skipped
}
for (const host of sheetHosts) {
  const sync = () => (sheetOpen(host) ? openSheet(host) : closeSheetState(host))
  if (host.matches("dialog")) new MutationObserver(sync).observe(host, { attributes: true, attributeFilter: ["open"] })
  else host.addEventListener("toggle", sync)
}
// The test and review hook: jump the open sheet to a detent.
window.__asSheetDetent = (d) => active?.detents.includes(d) && setDetent(d)

// A tap on the bell or avatar sheet's scrim (the details element's own ::before) closes it.
document.addEventListener("click", (e) => {
  if (isPhone() && e.target.matches?.("details.as-pop[open]")) dismissSheet()
})

// Drag from the grabber or the sheet's header. Down past a quarter of the sheet (or a fling)
// steps down a detent or dismisses; up steps to the large detent where there is one.
const DRAG_HANDLES = ".as-grab, .as-pop-head, .as-ident, .as-set-rail-head, .as-side-head"
let drag = null
document.addEventListener("pointerdown", (e) => {
  if (!active || !isPhone() || e.button > 0) return
  const handle = e.target.closest(DRAG_HANDLES)
  if (!handle || !active.sheet.contains(handle) || e.target.closest("button:not(.as-grab), a")) return
  const base = detentOffset(active.sheet, active.detent)
  drag = { id: e.pointerId, y0: e.clientY, base, dy: 0, samples: [[e.timeStamp, e.clientY]] }
  active.sheet.classList.remove("is-sheet-snapping")
  handle.setPointerCapture?.(e.pointerId)
})
document.addEventListener("pointermove", (e) => {
  if (!drag || e.pointerId !== drag.id) return
  let dy = e.clientY - drag.y0
  const canGrow = active.detent === "medium" && active.detents.includes("large")
  if (dy < 0 && !canGrow) dy /= 4 // rubber band past the top detent
  if (dy < 0 && canGrow) dy = Math.max(dy, -drag.base - 24)
  drag.dy = dy
  drag.samples = [...drag.samples, [e.timeStamp, e.clientY]].filter(([t]) => e.timeStamp - t <= 100)
  active.sheet.style.translate = `0 ${Math.max(drag.base + dy, -24)}px`
})
const endDrag = (e) => {
  if (!drag || e.pointerId !== drag.id) return
  const { dy, samples } = drag
  drag = null
  // Release velocity over the last 100ms of movement, in px per ms.
  const [t0, y0] = samples[0]
  const v = e.timeStamp - t0 > 0 ? (e.clientY - y0) / (e.timeStamp - t0) : 0
  const h = active.sheet.offsetHeight
  if (dy > h * 0.25 || v > 0.6) {
    if (active.detent === "large" && active.detents.includes("medium") && dy < h * 0.5 && v < 1.4) setDetent("medium")
    else dismissSheet()
  } else if ((dy < -40 || v < -0.6) && active.detents.includes("large")) setDetent("large")
  else setDetent(active.detent)
}
document.addEventListener("pointerup", endDrag)
document.addEventListener("pointercancel", endDrag)
// Scrolling the settings content at the medium detent expands the sheet, as on iOS.
settings?.querySelector(".as-set-scroll")?.addEventListener(
  "scroll",
  (e) => {
    if (active?.host === settings && active.detent === "medium" && e.target.scrollTop > 8) setDetent("large")
  },
  { passive: true },
)
// Keyboard: iOS ignores interactive-widget, so lift sheets above it by the visual viewport.
window.visualViewport?.addEventListener("resize", () => {
  const vv = window.visualViewport
  const kb = Math.max(0, window.innerHeight - vv.height - vv.offsetTop)
  root.style.setProperty("--pf-kb", `${Math.round(kb)}px`)
})

/* ---------- 5. press states: under 50ms, iOS dim (+ scale on buttons), Material ripple ---------- */
const TAPPABLE = 'a[href], button:not(:disabled), summary, label.mo-plant, .as-seg label, label.as-row'
const RELEASE_MS = 230
document.addEventListener("touchstart", () => {}, { passive: true }) // lets iOS Safari run :active
document.addEventListener(
  "pointerdown",
  (e) => {
    if (!isPhone() || e.button > 0) return
    let el = e.target.closest(TAPPABLE)
    if (!el || !root.contains(el) || el.closest(".ah-binny-tile, .sh-toolbar")) return
    // Material tabs: the state layer belongs on the active-indicator pill, not the whole column.
    if (platform() === "android" && el.closest(".a-bottombar")) el = el.querySelector(".as-ico") ?? el
    const r = el.getBoundingClientRect()
    el.style.setProperty("--pf-rx", `${e.clientX - r.left}px`)
    el.style.setProperty("--pf-ry", `${e.clientY - r.top}px`)
    el.classList.remove("is-release")
    el.classList.add("is-press")
    let lifted = false
    const lift = () => {
      if (lifted) return
      lifted = true
      el.classList.remove("is-press")
      el.classList.add("is-release")
      setTimeout(() => el.classList.remove("is-release"), RELEASE_MS)
      window.removeEventListener("pointerup", lift)
      window.removeEventListener("pointercancel", lift)
      window.removeEventListener("scroll", lift)
    }
    window.addEventListener("pointerup", lift)
    window.addEventListener("pointercancel", lift)
    window.addEventListener("scroll", lift, { passive: true })
  },
  { capture: true },
)

/* ---------- 6. pull to refresh on the tab root ---------- */
const PTR_MAX = 140
const ptrLive = document.querySelector("[data-a-ptr-live]")
let ptr = null
const tokenPx = (name) => parseFloat(getComputedStyle(root).getPropertyValue(name)) || 64
function setPull(px) {
  const threshold = tokenPx("--pf-ptr-threshold")
  col.style.setProperty("--pf-pull", `${px}px`)
  col.style.setProperty("--pf-pull-p", String(Math.min(1, px / threshold)))
}
function settlePull() {
  col.dataset.ptr = "settling"
  setPull(0)
  setTimeout(() => {
    if (col.dataset.ptr === "settling") delete col.dataset.ptr
  }, 400)
}
function refresh() {
  col.dataset.ptr = "refreshing"
  setPull(tokenPx("--pf-ptr-hold"))
  col.style.setProperty("--pf-pull-p", "1")
  haptic()
  setTimeout(() => {
    if (ptrLive) ptrLive.textContent = "Overview is up to date."
    settlePull()
  }, motionOn() ? 1200 : 600)
}
const canPull = () => isPhone() && root.dataset.page === "root" && !active && window.scrollY <= 0 && col.dataset.ptr !== "refreshing"
document.addEventListener(
  "touchstart",
  (e) => {
    if (!canPull() || e.touches.length !== 1 || !col.contains(e.target)) return
    ptr = { y0: e.touches[0].clientY, armed: false }
  },
  { passive: true },
)
document.addEventListener(
  "touchmove",
  (e) => {
    if (!ptr) return
    const dy = e.touches[0].clientY - ptr.y0
    if (dy <= 0 || window.scrollY > 0) {
      if (col.dataset.ptr === "pulling") settlePull()
      ptr = null
      return
    }
    e.preventDefault()
    col.dataset.ptr = "pulling"
    const pull = PTR_MAX * (1 - Math.exp(-dy / (PTR_MAX * 1.6))) // eases toward PTR_MAX
    setPull(pull)
    const over = pull >= tokenPx("--pf-ptr-threshold")
    if (over && !ptr.armed) haptic()
    ptr.armed = over
  },
  { passive: false },
)
document.addEventListener("touchend", () => {
  if (!ptr) return
  const { armed } = ptr
  ptr = null
  if (col.dataset.ptr !== "pulling") return
  if (armed) refresh()
  else settlePull()
})
// The review hook: show the indicator mid-pull (p 0-1), or run a refresh ("run").
window.__asPullDemo = (p = "run") => {
  if (p === "run") return refresh()
  col.dataset.ptr = "pulling"
  setPull(tokenPx("--pf-ptr-threshold") * p)
}

/* ---------- wiring ---------- */
function syncFrame() {
  if (!isPhone()) {
    if (active) closeSheetState(active.host)
    document.documentElement.style.removeProperty("overscroll-behavior-y")
  } else {
    // The page owns the pull: contain the root scroller so the browser's own refresh stays out.
    document.documentElement.style.overscrollBehaviorY = "contain"
  }
  syncPage()
}
new MutationObserver(syncFrame).observe(root, { attributes: true, attributeFilter: ["data-page", "data-platform", "data-width"] })
new ResizeObserver(syncFrame).observe(root)
syncFrame()
