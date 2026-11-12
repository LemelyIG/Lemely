import { PDFDocument } from "pdf-lib"

/*
 * Task 8 (B5b) · assemble captured/picked page images into one PDF.
 *
 * Moved out of `CameraCapture.tsx` (where it started as a camera-only
 * helper) so `CorrectPaper.tsx`'s multi-file picker can reuse the exact
 * same assembly for photos chosen from the file system, not only ones shot
 * through the camera flow — one implementation of "turn N page images into
 * a marking-ready PDF", not two that could drift.
 *
 * Runs in Node under Vitest as well as the browser: `pdf-lib` has no DOM
 * dependency, which is what lets `assemblePages.test.ts` exercise this
 * directly against synthetic PNG/JPEG fixtures (D3.20 — no jsdom here).
 */

export interface AssemblePagesOptions {
  filename?: string
}

/** Assembles JPEG or PNG page blobs into a single multi-page PDF, one page per image at its own pixel size. */
export async function assemblePagesToPdf(
  pages: readonly Blob[],
  options?: AssemblePagesOptions,
): Promise<File> {
  const filename = options?.filename ?? "scan.pdf"
  const pdfDoc = await PDFDocument.create()

  for (const page of pages) {
    const bytes = new Uint8Array(await page.arrayBuffer())
    const image = page.type === "image/png" ? await pdfDoc.embedPng(bytes) : await pdfDoc.embedJpg(bytes)
    const { width, height } = image.size()
    const pdfPage = pdfDoc.addPage([width, height])
    pdfPage.drawImage(image, { x: 0, y: 0, width, height })
  }

  const pdfBytes = await pdfDoc.save()
  // pdf-lib's Uint8Array is typed over ArrayBufferLike (may include
  // SharedArrayBuffer), which the DOM File/Blob constructors reject at the
  // type level. Copy into a plain ArrayBuffer-backed view first.
  const buffer = new ArrayBuffer(pdfBytes.byteLength)
  new Uint8Array(buffer).set(pdfBytes)
  return new File([buffer], filename, { type: "application/pdf" })
}
