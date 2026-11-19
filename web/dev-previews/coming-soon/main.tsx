import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "./preview.css"
import "../../src/portals/marketing/brand-tokens.css"
import { blockApiFetch } from "../harness"
import { Preview } from "./Preview"

blockApiFetch()

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Preview />
  </StrictMode>,
)
