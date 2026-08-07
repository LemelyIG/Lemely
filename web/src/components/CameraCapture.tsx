import { useEffect, useRef, useState } from "react"
import { PDFDocument } from "pdf-lib"
import { Camera, Trash, X } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

/*
 * Multi-shot camera capture for the student "photograph a paper" flow.
 * Two phases:
 *   - "live": camera stream active, big preview, "Capture page" grabs the
 *     current frame. A live thumbnail strip runs underneath so the student
 *     can see what's been shot so far without leaving the viewfinder.
 *   - "reviewing": the camera stream is stopped (nothing left running while
 *     the student just looks at thumbnails) and they choose "Add another
 *     page" (re-opens the camera, appends further shots) or "Done" (assembles
 *     every captured page into one multi-page PDF via pdf-lib and hands the
 *     resulting File back to the caller).
 *
 * The same effect that requests the camera stream also releases it — on
 * phase change away from "live" *and* on unmount — so backing out mid-capture
 * never leaves the camera light on.
 */

interface CapturedPage {
  id: string
  blob: Blob
  url: string
}

export interface CameraCaptureProps {
  /** Called with the assembled multi-page PDF once the student presses Done. */
  onComplete: (file: File) => void
  /** Called when the student backs out of the capture flow entirely. */
  onCancel: () => void
  className?: string
}

/** Turn a getUserMedia rejection into a specific, actionable message. */
function describeCameraError(err: unknown): string {
  if (err instanceof DOMException) {
    switch (err.name) {
      case "NotAllowedError":
      case "PermissionDeniedError":
        return "Camera access was denied. Allow camera permission for this site in your browser settings, then try again."
      case "NotFoundError":
      case "OverconstrainedError":
        return "No camera was found on this device."
      case "NotReadableError":
      case "TrackStartError":
        return "The camera is already in use by another app. Close it and try again."
      case "SecurityError":
        return "Camera access requires a secure (HTTPS) connection."
      case "AbortError":
        return "Camera access was interrupted. Try again."
      default:
        return `Could not access the camera (${err.name}).`
    }
  }
  if (err instanceof Error) return err.message
  return "Could not access the camera."
}

/** Assemble captured page images into a single multi-page PDF via pdf-lib. */
async function assemblePagesToPdf(pages: CapturedPage[]): Promise<File> {
  const pdfDoc = await PDFDocument.create()
  for (const page of pages) {
    const bytes = new Uint8Array(await page.blob.arrayBuffer())
    const image = await pdfDoc.embedJpg(bytes)
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
  return new File([buffer], "scan.pdf", { type: "application/pdf" })
}

export function CameraCapture({ onComplete, onCancel, className }: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const pagesRef = useRef<CapturedPage[]>([])

  const [phase, setPhase] = useState<"live" | "reviewing">("live")
  const [starting, setStarting] = useState(true)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [retryToken, setRetryToken] = useState(0)
  const [pages, setPages] = useState<CapturedPage[]>([])
  const [assembling, setAssembling] = useState(false)
  const [assembleError, setAssembleError] = useState<string | null>(null)

  useEffect(() => {
    pagesRef.current = pages
  }, [pages])

  // Revoke every remaining object URL on final unmount, regardless of phase.
  useEffect(() => {
    return () => {
      pagesRef.current.forEach((p) => URL.revokeObjectURL(p.url))
    }
  }, [])

  // Acquire the camera stream while (and only while) phase === "live".
  // The cleanup here fires on phase change away from "live" AND on unmount,
  // so the camera is released whenever the live preview is not on screen.
  useEffect(() => {
    if (phase !== "live") return

    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setStarting(false)
      setCameraError(
        "Camera access isn't available here - this needs a secure (HTTPS) connection and a browser that supports getUserMedia.",
      )
      return
    }

    let cancelled = false
    setStarting(true)
    setCameraError(null)

    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" } })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
        }
        setStarting(false)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setStarting(false)
        setCameraError(describeCameraError(err))
      })

    return () => {
      cancelled = true
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
  }, [phase, retryToken])

  const capturePage = () => {
    const video = videoRef.current
    if (!video || !video.videoWidth || !video.videoHeight) return
    const canvas = document.createElement("canvas")
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    canvas.toBlob(
      (blob) => {
        if (!blob) return
        const id =
          typeof crypto !== "undefined" && "randomUUID" in crypto
            ? crypto.randomUUID()
            : `page-${Date.now()}-${Math.random()}`
        setPages((prev) => [...prev, { id, blob, url: URL.createObjectURL(blob) }])
      },
      "image/jpeg",
      0.92,
    )
  }

  const removePage = (id: string) => {
    setPages((prev) => {
      const target = prev.find((p) => p.id === id)
      if (target) URL.revokeObjectURL(target.url)
      return prev.filter((p) => p.id !== id)
    })
  }

  const finishCapture = () => {
    if (pages.length === 0) return
    setAssembleError(null)
    setPhase("reviewing")
  }

  const handleDone = async () => {
    if (pages.length === 0) return
    setAssembling(true)
    setAssembleError(null)
    try {
      const file = await assemblePagesToPdf(pages)
      onComplete(file)
    } catch (err) {
      setAssembleError(
        err instanceof Error
          ? err.message
          : "Could not assemble the scanned pages into a PDF.",
      )
    } finally {
      setAssembling(false)
    }
  }

  const thumbnailStrip = pages.length > 0 && (
    <div className="flex gap-2.5 overflow-x-auto lm-scroll pb-1">
      {pages.map((page, i) => (
        <div key={page.id} className="relative flex-none">
          <img
            src={page.url}
            alt={`Captured page ${i + 1}`}
            className="w-[74px] h-[98px] object-cover rounded-md border border-border"
          />
          <span className="absolute top-1 left-1 rounded-full bg-ink/70 text-accent-on text-3xs leading-none px-1.5 py-0.5">
            {i + 1}
          </span>
          <button
            type="button"
            onClick={() => removePage(page.id)}
            aria-label={`Remove page ${i + 1}`}
            className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-ink text-accent-on flex items-center justify-center cursor-pointer hover:bg-ink-hover"
          >
            <Trash size={11} weight="bold" />
          </button>
        </div>
      ))}
    </div>
  )

  return (
    <Card className={cn("p-[22px] flex flex-col gap-4", className)}>
      {phase === "live" ? (
        <>
          <div className="relative w-full aspect-[3/4] max-h-[420px] bg-ink rounded-md overflow-hidden flex items-center justify-center">
            {cameraError ? (
              <div className="text-dense-sm text-accent-on text-center px-6 leading-[1.5] text-pretty">
                {cameraError}
              </div>
            ) : (
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="w-full h-full object-cover"
              />
            )}
            {starting && !cameraError ? (
              <div className="absolute inset-0 flex items-center justify-center text-dense-sm text-accent-on/80">
                Starting camera...
              </div>
            ) : null}
          </div>

          <div className="flex items-center gap-2.5 flex-wrap">
            {cameraError ? (
              <Button
                variant="accent"
                size="md"
                onClick={() => setRetryToken((t) => t + 1)}
              >
                Try again
              </Button>
            ) : (
              <Button
                variant="accent"
                size="md"
                onClick={capturePage}
                disabled={starting}
              >
                <Camera size={16} weight="bold" />
                Capture page
              </Button>
            )}
            {pages.length > 0 && !cameraError ? (
              <Button variant="secondary" size="md" onClick={finishCapture}>
                Review {pages.length} page{pages.length === 1 ? "" : "s"}
              </Button>
            ) : null}
            <Button variant="ghost" size="md" onClick={onCancel}>
              <X size={16} />
              Cancel
            </Button>
          </div>

          {thumbnailStrip}
        </>
      ) : (
        <>
          <div className="text-dense font-medium">
            {pages.length} page{pages.length === 1 ? "" : "s"} captured
          </div>
          <div className="text-xs text-t3">
            Check every page before finishing - remove and reshoot anything
            blurry or cut off.
          </div>
          {thumbnailStrip}
          {assembleError ? (
            <div className="text-dense-sm text-accent leading-[1.5] text-pretty">
              {assembleError}
            </div>
          ) : null}
          <div className="flex items-center gap-2.5 flex-wrap">
            <Button
              variant="secondary"
              size="md"
              onClick={() => setPhase("live")}
              disabled={assembling}
            >
              <Camera size={16} weight="bold" />
              Add another page
            </Button>
            <Button
              variant="accent"
              size="md"
              onClick={handleDone}
              disabled={assembling || pages.length === 0}
            >
              {assembling ? "Assembling..." : "Done"}
            </Button>
            <Button variant="ghost" size="md" onClick={onCancel} disabled={assembling}>
              Cancel
            </Button>
          </div>
        </>
      )}
    </Card>
  )
}
