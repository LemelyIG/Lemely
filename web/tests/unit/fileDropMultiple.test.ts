import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

import { stripComments } from "./support/jsxSource"

const ROOT = path.resolve(import.meta.dirname, "../../src")

function readSource(relativePath: string): string {
  return stripComments(readFileSync(path.join(ROOT, relativePath), "utf8"))
}

describe("Task 8 (B5b) · multi-file picker source wiring", () => {
  it("file-drop.tsx declares multiple and onFilesChange", () => {
    const source = readSource("components/ui/file-drop.tsx")
    expect(source).toContain("multiple")
    expect(source).toContain("onFilesChange")
  })

  it("CorrectPaper.tsx wires onFilesChange and assemblePagesToPdf from lib/pdf", () => {
    const source = readSource("portals/student/screens/CorrectPaper.tsx")
    expect(source).toContain("onFilesChange")
    expect(source).toContain('await import("@/lib/pdf/assemblePages")')
    expect(source).toContain("assemblePagesToPdf")
  })

  it("CameraCapture.tsx no longer defines its own assemblePagesToPdf and lazy-loads the scanner", () => {
    const source = readSource("components/CameraCapture.tsx")
    expect(source).not.toContain("async function assemblePagesToPdf")
    expect(source).toContain('import("@/lib/scanner")')
    expect(source).toContain("torchSupported")
  })
})
