import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { MemoryRouter } from "react-router-dom"
import "../preview.css"
import { blockApiFetch } from "../harness"
import { Gallery } from "./Gallery"

blockApiFetch()

const root = document.getElementById("root")
if (!root) throw new Error("preview root element is missing")

createRoot(root).render(
  <StrictMode>
    <MemoryRouter>
      <Gallery />
    </MemoryRouter>
  </StrictMode>,
)
