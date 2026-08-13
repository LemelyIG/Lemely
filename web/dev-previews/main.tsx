import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "./preview.css"
import { App } from "./App"

const root = document.getElementById("root")
if (!root) throw new Error("preview root element is missing")

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
