import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { MemoryRouter } from "react-router-dom"
import "./preview.css"
import { App } from "./App"

const root = document.getElementById("root")
if (!root) throw new Error("preview root element is missing")

/*
 * `MemoryRouter`, added in P3.2 when the kit gained its first components that
 * render a `<Link>` (Breadcrumbs, GettingStarted). Memory rather than browser
 * history on purpose: the preview's links point at real product routes that do
 * not exist in this entry, so a browser router would let a click navigate the
 * preview to a blank page. In memory the click is a no-op that still exercises
 * the component's real markup, which is what the page is here to show.
 */
createRoot(root).render(
  <StrictMode>
    <MemoryRouter>
      <App />
    </MemoryRouter>
  </StrictMode>,
)
