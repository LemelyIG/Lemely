import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { MemoryRouter } from "react-router-dom"
import "./preview.css"
import { Directions } from "./Directions"

/*
 * DECISION D4.8, defaulted to option A on 2026-08-14 after its 30-minute
 * timeout elapsed with no reply.
 *
 * The design-directions gallery used to be a product route: `/student/
 * directions`, reachable by any signed-in student, rendering mock data, with
 * no nav entry after D1.1 removed it — invisible rather than gone. That is the
 * same shape as the component kit, which Phase 2 moved here behind its own
 * Vite entry precisely so the product could never ship it, and A is the answer
 * the project had already given once to the identical question.
 *
 * It gets a second HTML entry rather than a section inside the kit page. The
 * kit is a component reference and this is an argument about one screen's
 * treatment; stacking them would make each harder to read, and the kit's
 * `SECTIONS` nav has no honest heading for "a decision we already made".
 *
 * Run with `npm run preview:kit` and open `/directions.html`.
 *
 * `MemoryRouter` for the same reason `main.tsx` uses one: the gallery renders
 * `<Link>`s at real product routes that do not exist in this entry, so a
 * browser router would let a click navigate the preview to a blank page.
 */

const root = document.getElementById("root")
if (!root) throw new Error("preview root element is missing")

createRoot(root).render(
  <StrictMode>
    <MemoryRouter>
      <Directions />
    </MemoryRouter>
  </StrictMode>,
)
