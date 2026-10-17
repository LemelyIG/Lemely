import { PDFDocument } from "pdf-lib"
import { describe, expect, it } from "vitest"

import { assemblePagesToPdf } from "@/lib/pdf/assemblePages"

/*
 * Minimal, genuinely valid 4x4 fixtures (generated once via Pillow, base64
 * pinned here) rather than hand-rolled byte arrays — `pdf-lib`'s
 * `embedPng`/`embedJpg` parse real PNG/JPEG structure, and a fake header
 * would only prove this test can fool the decoder, not that the assembly
 * works against images a camera or a file picker would actually produce.
 */
const PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAFElEQVR4nGM8YWTEAANMDEgANwcAPDIBNLzWzv0AAAAASUVORK5CYII="
const JPEG_BASE64 =
  "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAAEAAQDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDyeiiivzw/sg//2Q=="

function base64ToBlob(base64: string, type: string): Blob {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0))
  return new Blob([bytes], { type })
}

describe("assemblePagesToPdf", () => {
  it("assembles a PNG and a JPEG page into one two-page PDF", async () => {
    const png = base64ToBlob(PNG_BASE64, "image/png")
    const jpeg = base64ToBlob(JPEG_BASE64, "image/jpeg")

    const file = await assemblePagesToPdf([png, jpeg])

    expect(file.type).toBe("application/pdf")
    expect(file.name).toBe("scan.pdf")

    const bytes = new Uint8Array(await file.arrayBuffer())
    const doc = await PDFDocument.load(bytes)
    expect(doc.getPageCount()).toBe(2)
  })

  it("honours a custom filename", async () => {
    const png = base64ToBlob(PNG_BASE64, "image/png")
    const file = await assemblePagesToPdf([png], { filename: "correction.pdf" })
    expect(file.name).toBe("correction.pdf")
  })

  it("assembles a single page", async () => {
    const jpeg = base64ToBlob(JPEG_BASE64, "image/jpeg")
    const file = await assemblePagesToPdf([jpeg])
    const bytes = new Uint8Array(await file.arrayBuffer())
    const doc = await PDFDocument.load(bytes)
    expect(doc.getPageCount()).toBe(1)
  })
})
