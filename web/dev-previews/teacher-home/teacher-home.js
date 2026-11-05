// Teacher home behaviour: page-wide drag and drop for batch marking, top-bar popovers.
const $ = (sel, root = document) => root.querySelector(sel)
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)]

const MAX_FILES = 60
const card = $("#th-mark")
const zone = $("#th-zone")
const input = $("#th-file")
const veil = $("#th-veil")
const list = $("#th-files")
const note = $("#th-note")

let files = []
let timer = 0

const isPaper = (f) => f.type === "application/pdf" || /\.pdf$/i.test(f.name) || f.type.startsWith("image/")
const kb = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB")

function setState(state) {
  card.dataset.state = state
}

function accept(incoming) {
  const all = [...files, ...incoming]
  const papers = all.filter(isPaper)
  const skipped = all.length - papers.length
  const kept = papers.slice(0, MAX_FILES)
  const over = papers.length - kept.length
  files = kept
  if (!files.length) {
    note.textContent = skipped ? "Only PDFs and photos can be marked. Nothing was added." : ""
    note.hidden = !skipped
    return
  }
  const bits = []
  if (skipped) bits.push(`${skipped} not a PDF or photo, skipped`)
  if (over) bits.push(`${over} over the ${MAX_FILES} file limit, skipped`)
  note.textContent = bits.join(" · ")
  note.hidden = !bits.length
  renderQueue()
  setState("queued")
}

function renderQueue() {
  $("#th-count").textContent = `${files.length} ${files.length === 1 ? "paper" : "papers"} ready`
  list.replaceChildren(
    ...files.map((f) => {
      const li = document.createElement("li")
      const name = document.createElement("span")
      name.textContent = f.name
      const size = document.createElement("small")
      size.textContent = kb(f.size)
      li.append(name, size)
      return li
    }),
  )
}

function reset() {
  clearInterval(timer)
  files = []
  input.value = ""
  camera.value = ""
  note.hidden = true
  $("#th-bar").style.setProperty("--p", "0")
  setState("idle")
}

function start() {
  setState("marking")
  const total = files.length
  let done = 0
  $("#th-progress").textContent = `0 of ${total} marked`
  clearInterval(timer)
  timer = setInterval(() => {
    done = Math.min(total, done + Math.max(1, Math.round(total / 12)))
    $("#th-bar").style.setProperty("--p", String(done / total))
    $("#th-progress").textContent = `${done} of ${total} marked`
    if (done === total) {
      clearInterval(timer)
      setState("done")
      $("#th-done").textContent = `${total} ${total === 1 ? "paper" : "papers"} marked. Anything below 0.70 confidence is waiting in your review queue.`
    }
  }, 450)
}

// Choose files
const camera = $("#th-cam")
input.addEventListener("change", () => accept([...input.files]))
camera.addEventListener("change", () => accept([...camera.files]))

// Every upload entry point opens the picker. Not while a batch is marking; a finished batch starts fresh.
function pick(el) {
  if (card.dataset.state === "marking") return
  if (card.dataset.state === "done") reset()
  el.click()
}
;["#th-choose", "#th-upload", "#th-upload-side", "#th-fab"].forEach((id) => $(id).addEventListener("click", () => pick(input)))
$("#th-camera").addEventListener("click", () => pick(camera))
$("#th-start").addEventListener("click", start)
$$("[data-th-reset]").forEach((b) => b.addEventListener("click", reset))

// Page-wide drag and drop. The browser would otherwise navigate to a dropped file.
let depth = 0
const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files")

window.addEventListener("dragenter", (e) => {
  if (!hasFiles(e)) return
  e.preventDefault()
  depth++
  veil.hidden = false
  zone.classList.add("over")
})
window.addEventListener("dragover", (e) => {
  if (!hasFiles(e)) return
  e.preventDefault()
  e.dataTransfer.dropEffect = "copy"
})
window.addEventListener("dragleave", (e) => {
  if (!hasFiles(e)) return
  depth = Math.max(0, depth - 1)
  if (!depth) {
    veil.hidden = true
    zone.classList.remove("over")
  }
})
window.addEventListener("drop", (e) => {
  if (!hasFiles(e)) return
  e.preventDefault()
  depth = 0
  veil.hidden = true
  zone.classList.remove("over")
  if (card.dataset.state === "marking") return
  if (card.dataset.state === "done") reset()
  accept([...e.dataTransfer.files])
  card.scrollIntoView({ block: "nearest", behavior: "smooth" })
})

// Top-bar popovers: one open at a time, close on outside click or Escape.
const pops = $$("details.pop")
pops.forEach((d) =>
  d.addEventListener("toggle", () => {
    if (d.open) pops.filter((o) => o !== d).forEach((o) => (o.open = false))
  }),
)
document.addEventListener("click", (e) => {
  pops.forEach((d) => {
    if (d.open && !d.contains(e.target)) d.open = false
  })
})
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return
  pops.forEach((d) => {
    if (d.open) {
      d.open = false
      $("summary", d).focus()
    }
  })
})

// Groups row loops endlessly and only moves on input: clone the cards before and after the
// originals, start on the originals, and move scrollLeft by one set width whenever the row
// passes half a set to either side.
const groups = $(".groups")
if (groups) {
  const cards = [...groups.children]
  const copies = () =>
    cards.map((c) => {
      const k = c.cloneNode(true)
      k.setAttribute("aria-hidden", "true")
      k.setAttribute("inert", "")
      return k
    })
  const before = copies()
  before.forEach((k) => groups.insertBefore(k, cards[0]))
  copies().forEach((k) => groups.appendChild(k))
  const setWidth = () => cards[0].offsetLeft - before[0].offsetLeft
  const jump = (x) => {
    groups.style.scrollBehavior = "auto"
    groups.scrollLeft = x
    groups.style.scrollBehavior = ""
  }
  jump(setWidth())
  groups.addEventListener(
    "scroll",
    () => {
      const w = setWidth()
      const x = groups.scrollLeft
      if (x < w * 0.5) jump(x + w)
      else if (x > w * 1.5) jump(x - w)
    },
    { passive: true },
  )
}
