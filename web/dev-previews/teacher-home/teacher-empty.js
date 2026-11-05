// Teacher overview, empty state: the three onboarding steps advance as the teacher works through them.
// Prototype only. In the app, "Create a class" opens /teacher/first-class and the upload goes to the server.
const $ = (sel, root = document) => root.querySelector(sel)
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)]

const setup = $(".em-setup")
const steps = $$(".r-step", setup)
const note = $(".note", setup)
const prog = $(".em-prog", setup)
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches
let done = 0

function advance() {
  const step = steps[done]
  step.classList.remove("now")
  step.classList.add("done")
  done++
  note.textContent = done === steps.length ? "All set" : `${done} of ${steps.length} done`
  prog.style.setProperty("--p", String(done / steps.length))
  if (steps[done]) steps[done].classList.add("now")
  else setup.classList.add("all-done")
}

// A step that is not ready yet answers with a short nudge on the step that is.
function nudge() {
  const step = steps[done]
  step.classList.remove("nudge")
  void step.offsetWidth
  step.classList.add("nudge")
}

// The join code settles one character at a time, left to right.
function settle(el, code, then) {
  if (calm) return then()
  const chars = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
  let frame = 0
  const tick = () => {
    const fixed = Math.floor(frame / 3)
    el.textContent = [...code].map((c, i) => (i < fixed ? c : chars[(Math.random() * chars.length) | 0])).join("")
    frame++
    if (fixed < code.length) requestAnimationFrame(tick)
    else then()
  }
  tick()
}

function createClass() {
  if (done !== 0) return
  const prev = $(".r-prev", steps[0])
  prev.classList.add("made")
  $(".chip", prev).textContent = "Created"
  settle($(".code", prev), "K7M4QX", () => setTimeout(advance, calm ? 0 : 450))
}

function uploaded(files) {
  const pdfs = files.filter((f) => f.type === "application/pdf" || /\.pdf$/i.test(f.name))
  if (!pdfs.length) return
  if (done < 1) return nudge()
  if (done > 1) return
  $(".r-done", steps[1]).textContent = `${pdfs.length} ${pdfs.length === 1 ? "paper" : "papers"} uploaded`
  advance()
  mark(pdfs.length)
}

// Marking runs on the server; here the bar stands in for it.
function mark(total) {
  const step = steps[2]
  const bar = $(".r-run i", step)
  const label = $(".r-run .mono", step)
  step.classList.add("running")
  let n = 0
  label.textContent = `0 of ${total} marked`
  const timer = setInterval(() => {
    n = Math.min(total, n + Math.max(1, Math.round(total / 8)))
    bar.style.setProperty("--p", String(n / total))
    label.textContent = `${n} of ${total} marked`
    if (n === total) {
      clearInterval(timer)
      const flagged = Math.max(1, Math.round(total * 1.5))
      label.textContent = `${total} marked · ${flagged} ${flagged === 1 ? "answer" : "answers"} for you to check`
      step.classList.replace("running", "ready")
    }
  }, calm ? 60 : 380)
}

document.addEventListener("click", (e) => {
  const act = e.target.closest("[data-act]")
  if (act) {
    e.preventDefault()
    if (act.dataset.act === "create") createClass()
    else if (act.dataset.act === "upload") (done < 1 ? nudge() : $("#th-file").click())
    else if (act.dataset.act === "review" && steps[2].classList.contains("ready")) advance()
    return
  }
  const copy = e.target.closest(".r-copy")
  if (copy) {
    navigator.clipboard?.writeText(copy.dataset.code).catch(() => {})
    copy.textContent = "Copied"
    copy.classList.add("ok")
    setTimeout(() => {
      copy.textContent = "Copy"
      copy.classList.remove("ok")
    }, 1600)
  }
})

// Files arrive through the shared picker or a page-wide drop (both handled by teacher-home.js).
$("#th-file").addEventListener("change", (e) => uploaded([...e.target.files]))
window.addEventListener("drop", (e) => {
  if (e.dataTransfer?.files?.length) uploaded([...e.dataTransfer.files])
})
