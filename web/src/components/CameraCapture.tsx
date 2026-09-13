import { useEffect, useRef, useState } from "react"
import { Camera, Flashlight, Trash, X } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { assemblePagesToPdf } from "@/lib/pdf/assemblePages"
import { randomUuid } from "@/lib/uuid"
import { cn } from "@/lib/utils"
import { useWakeLock } from "@/lib/wakeLock"
import type * as Scanner from "@/lib/scanner"
import type { Quad } from "@/lib/scanner"

/*
 * Multi-shot camera capture for the student "photograph a paper" flow.
 * Two phases:
 *   - "live": camera stream active, big preview, "Capture page" grabs the
 *     current frame. A live thumbnail strip runs underneath so the student
 *     can see what's been shot so far without leaving the viewfinder.
 *   - "reviewing": the camera stream is stopped (nothing left running while
 *     the student just looks at thumbnails) and they choose "Add another
 *     page" (re-opens the camera, appends further shots) or "Done" (assembles
 *     every captured page into one multi-page PDF via `lib/pdf/assemblePages`
 *     and hands the resulting File back to the caller).
 *
 * The same effect that requests the camera stream also releases it — on
 * phase change away from "live" *and* on unmount — so backing out mid-capture
 * never leaves the camera light on.
 *
 * A4 review (HIGH) · `getUserMedia` must never fire without a user gesture
 * behind it. `autoStart` is required, with no default — permission-sensitive
 * enough that a caller forgetting it must be a compile error, not a silent
 * fail-open back to auto-starting. `true` when the mount is itself the
 * direct result of a tap (`CorrectPaper`'s "Camera" toggle and "Rescan");
 * `false` when the caller can mount this with NO such gesture (`CorrectPaper`'s
 * device-based default source); `started` then gates both the "live"-phase
 * acquisition effect and what the "live" phase renders, so a `false` mount
 * instead shows an explicit "Take a photo" prompt and the camera is
 * acquired only once the student taps it — itself now the gesture.
 *
 * Task 8 (B5b) · scanner quality. Once the stream is live and ready (not
 * `starting`, no `cameraError`), a second effect lazy-loads `@/lib/scanner`
 * (`import("@/lib/scanner")` — the hand-rolled Sobel/quad/homography pipeline
 * never ships in this component's own chunk; see DESIGN.md §15) and runs a
 * `requestAnimationFrame` loop that samples every 3rd frame into a 320px-wide
 * luma buffer, finds a document quad, and tracks frame-to-frame stability.
 * Three steady frames with a quad found auto-fire `capturePage()` exactly
 * once (`armedRef`), then re-arm once the new thumbnail lands. The quad, when
 * found, is also what `capturePage` warps the shot through
 * (`correctPerspective`) instead of keeping the raw skewed frame, and drawn
 * live as a `<polygon>` overlay (updated imperatively via a ref — not
 * component state — so 10+ analysed frames a second never re-render this
 * component). The torch button only appears once `torchSupported` says the
 * active video track actually has one.
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
  /** Whether to acquire the camera immediately on mount. Required, with no
   * default: `getUserMedia` is permission-sensitive enough that a caller
   * forgetting this prop must be a type error, not a silent fail-open back
   * to auto-starting (which is exactly the HIGH-severity bug this prop
   * exists to prevent — a future second call site is one omitted prop away
   * from reintroducing it). `true` when the mount is itself the direct
   * result of a tap (`CorrectPaper`'s "Camera" toggle, "Rescan"). `false`
   * when it can be mounted with no such gesture (`CorrectPaper`'s
   * device-based default source, `shouldAutoStartCamera`) — see the module
   * header. */
  autoStart: boolean
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
  /* P6.2. This returned `err.message` for a non-`DOMException` Error, which is
     a programming fault rather than a camera one — so the sentence a student
     read was whatever a library happened to throw. Every camera failure a
     browser actually reports is named above; anything else has no message worth
     showing, and the generic sentence is already right here. */
  return "Could not access the camera."
}

/**
 * Maps a quad in the analysis canvas's own pixel space onto the `<polygon>`
 * that overlays the displayed (object-cover-cropped) video element, and
 * writes it directly onto the DOM node — never through component state, so
 * this can run once per analysed frame without re-rendering the component.
 */
function updateOverlay(
  polygon: SVGPolygonElement | null,
  video: HTMLVideoElement | null,
  quad: Quad | null,
  analysisSize: { width: number; height: number },
) {
  if (!polygon) return
  if (!quad || !video || !video.videoWidth || !video.videoHeight) {
    polygon.setAttribute("points", "")
    return
  }
  const containerW = video.clientWidth
  const containerH = video.clientHeight
  if (!containerW || !containerH || !analysisSize.width || !analysisSize.height) {
    polygon.setAttribute("points", "")
    return
  }

  // object-cover: the video is scaled up to fully cover its box, then
  // centred and clipped — the same transform CSS applies visually.
  const coverScale = Math.max(containerW / video.videoWidth, containerH / video.videoHeight)
  const offsetX = (video.videoWidth * coverScale - containerW) / 2
  const offsetY = (video.videoHeight * coverScale - containerH) / 2
  const toVideoX = video.videoWidth / analysisSize.width
  const toVideoY = video.videoHeight / analysisSize.height

  const points = quad
    .map((point) => {
      const videoX = point.x * toVideoX
      const videoY = point.y * toVideoY
      const px = ((videoX * coverScale - offsetX) / containerW) * 100
      const py = ((videoY * coverScale - offsetY) / containerH) * 100
      return `${px},${py}`
    })
    .join(" ")
  polygon.setAttribute("points", points)
}

export function CameraCapture({
  onComplete,
  onCancel,
  className,
  autoStart,
}: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const overlayRef = useRef<SVGPolygonElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const pagesRef = useRef<CapturedPage[]>([])

  // Task 8 (B5b) scanner state — all refs, never React state: every one of
  // these is written up to ~10x/second from the rAF loop and must not drive
  // a render.
  const scannerRef = useRef<typeof Scanner | null>(null)
  const quadRef = useRef<Quad | null>(null)
  const analysisSizeRef = useRef({ width: 0, height: 0 })
  const prevLumaRef = useRef<Float32Array | null>(null)
  const deltasRef = useRef<number[]>([])
  // Whether the next "capture" stability decision is allowed to actually
  // fire `capturePage()`. Cleared the instant it fires, re-armed once the
  // resulting thumbnail lands (`pages` changes) — otherwise a still-steady
  // frame would auto-fire again on literally the next analysed frame.
  const armedRef = useRef(true)

  const [phase, setPhase] = useState<"live" | "reviewing">("live")
  // Whether the student has given the gesture `getUserMedia` needs — either
  // `autoStart` already supplied it (a tap elsewhere mounted this component)
  // or they have since tapped "Take a photo" below. Never reset back to
  // `false`: once given, the gesture covers "Add another page" too.
  const [started, setStarted] = useState(autoStart)
  const [starting, setStarting] = useState(true)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [retryToken, setRetryToken] = useState(0)
  const [pages, setPages] = useState<CapturedPage[]>([])
  const [assembling, setAssembling] = useState(false)
  const [assembleError, setAssembleError] = useState<string | null>(null)
  const [torchAvailable, setTorchAvailable] = useState(false)
  const [torchOn, setTorchOn] = useState(false)

  // Task 7 (B5a): held only while the live preview is actually on screen and
  // acquired (`started`) — a multi-page scan is the one flow here where the
  // screen sleeping mid-shoot loses real work (the stream stops and the
  // student has to re-open the camera). See the hook's own header for why
  // every failure here is silent.
  useWakeLock(phase === "live" && started)

  useEffect(() => {
    pagesRef.current = pages
    // A new thumbnail landed — re-arm auto-capture and drop the delta
    // window, so the frame that was steady enough to fire is not read
    // again as "still steady" against the just-captured page.
    armedRef.current = true
    deltasRef.current = []
  }, [pages])

  // Revoke every remaining object URL on final unmount, regardless of phase.
  useEffect(() => {
    return () => {
      pagesRef.current.forEach((p) => URL.revokeObjectURL(p.url))
    }
  }, [])

  // Acquire the camera stream while (and only while) phase === "live" AND
  // the student has given the gesture for it (`started` — see its own doc).
  // The cleanup here fires on phase change away from "live", on `started`
  // going false-to-true is a no-op cleanup (nothing was ever acquired), AND
  // on unmount, so the camera is released whenever the live preview is not
  // on screen.
  useEffect(() => {
    if (phase !== "live" || !started) return

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
  }, [phase, started, retryToken])

  const capturePage = () => {
    const video = videoRef.current
    if (!video || !video.videoWidth || !video.videoHeight) return
    const canvas = document.createElement("canvas")
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

    const scanner = scannerRef.current
    const quad = quadRef.current
    const analysisSize = analysisSizeRef.current
    if (scanner && quad && analysisSize.width && analysisSize.height) {
      // `quad` is in the analysis canvas's own (much smaller) coordinate
      // space — scale it up to this full-resolution capture canvas first.
      const scaleX = canvas.width / analysisSize.width
      const scaleY = canvas.height / analysisSize.height
      const fullQuad = quad.map((point) => ({
        x: point.x * scaleX,
        y: point.y * scaleY,
      })) as Quad
      try {
        const corrected = scanner.correctPerspective(ctx, canvas.width, canvas.height, fullQuad)
        ctx.putImageData(corrected, 0, 0)
      } catch {
        // Perspective correction is a nicety over the raw frame, not a
        // requirement — any failure (a degenerate quad, say) leaves the
        // raw `drawImage` frame already on the canvas untouched.
      }
    }

    canvas.toBlob(
      (blob) => {
        if (!blob) return
        setPages((prev) => [...prev, { id: randomUuid(), blob, url: URL.createObjectURL(blob) }])
      },
      "image/jpeg",
      0.92,
    )
  }

  // Read from the rAF loop below without putting `capturePage` itself in
  // that effect's dependency array — its identity changes every render
  // (it closes over `pages` state via `setPages`'s updater form, which it
  // doesn't actually need to), but the ref always has the latest version.
  const capturePageRef = useRef(capturePage)
  capturePageRef.current = capturePage

  // Task 8 (B5b) · frame-analysis loop: lazy-loads the scanner, then samples
  // every 3rd rAF tick into a 320px-wide luma buffer, updates the quad
  // overlay, and auto-fires a capture once the frame is steady. Runs only
  // once the stream is actually live (`!starting`, no `cameraError`) —
  // analysing a black "Starting camera..." frame would find nothing anyway.
  useEffect(() => {
    if (phase !== "live" || !started || starting || cameraError) return
    const video = videoRef.current
    if (!video) return
    // Captured once, up front: the cleanup below must not read `.current`
    // again (it may have changed to a different node's ref by the time
    // cleanup runs), and the overlay polygon is remounted only when this
    // same effect's dependencies change anyway.
    const polygon = overlayRef.current

    let cancelled = false
    let rafId = 0
    const analysisCanvas = document.createElement("canvas")

    import("@/lib/scanner").then((scanner) => {
      if (cancelled) return
      scannerRef.current = scanner

      const track = streamRef.current?.getVideoTracks()[0]
      setTorchAvailable(Boolean(track && scanner.torchSupported(track)))

      const analysisCtx = analysisCanvas.getContext("2d", { willReadFrequently: true })
      if (!analysisCtx) return

      let frameCount = 0
      const tick = () => {
        if (cancelled) return
        rafId = requestAnimationFrame(tick)
        frameCount += 1
        if (frameCount % 3 !== 0) return
        if (!video.videoWidth || !video.videoHeight) return

        const analysisWidth = Math.min(scanner.ANALYSIS_WIDTH, video.videoWidth)
        const analysisHeight = Math.max(
          1,
          Math.round((video.videoHeight * analysisWidth) / video.videoWidth),
        )
        if (analysisCanvas.width !== analysisWidth || analysisCanvas.height !== analysisHeight) {
          analysisCanvas.width = analysisWidth
          analysisCanvas.height = analysisHeight
        }
        analysisSizeRef.current = { width: analysisWidth, height: analysisHeight }
        analysisCtx.drawImage(video, 0, 0, analysisWidth, analysisHeight)

        const result = scanner.analyseFrame(
          analysisCtx,
          analysisWidth,
          analysisHeight,
          prevLumaRef.current,
        )
        prevLumaRef.current = result.luma
        quadRef.current = result.quad
        updateOverlay(polygon, video, result.quad, analysisSizeRef.current)

        if (!armedRef.current) return
        deltasRef.current = [...deltasRef.current, result.delta].slice(-8)
        if (scanner.stabilityDecision(deltasRef.current, result.quad !== null) === "capture") {
          armedRef.current = false
          capturePageRef.current()
        }
      }
      rafId = requestAnimationFrame(tick)
    })

    return () => {
      cancelled = true
      cancelAnimationFrame(rafId)
      prevLumaRef.current = null
      deltasRef.current = []
      quadRef.current = null
      analysisSizeRef.current = { width: 0, height: 0 }
      updateOverlay(polygon, null, null, { width: 0, height: 0 })
      setTorchAvailable(false)
      setTorchOn(false)
    }
  }, [phase, started, starting, cameraError])

  const toggleTorch = async () => {
    const scanner = scannerRef.current
    const track = streamRef.current?.getVideoTracks()[0]
    if (!scanner || !track) return
    const next = !torchOn
    const applied = await scanner.setTorch(track, next)
    if (applied) setTorchOn(next)
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
      const file = await assemblePagesToPdf(pages.map((page) => page.blob))
      onComplete(file)
    } catch {
      /* P6.2. This rendered `err.message`, which here is pdf-lib's, so a
         student who photographed their paper and pressed done could be told
         "Input image is not a JPEG" — machine text, about a file they never
         chose, at the end of the longest piece of work this screen asks for.
         The binding is dropped rather than left unread: nothing in this client
         logs, so an unused `err` would only be there to look thorough. */
      setAssembleError(
        "Could not assemble the scanned pages into a PDF. Try retaking the last page.",
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
          {/* P6.2: `start-1`, not `left-1`. §3.4's RTL rule, found the moment
              this file was added to `rtlSafety.test.ts` — it had never been in
              either gate list, which is the same "a file no gate reads"
              mechanism surface 10 named, on the camera half of the flagship
              flow. The page number belongs at the reading-start corner. */}
          <span className="absolute top-1 start-1 rounded-full bg-ink/70 text-accent-on text-3xs leading-none px-1.5 py-0.5">
            {i + 1}
          </span>
          <button
            type="button"
            onClick={() => removePage(page.id)}
            aria-label={`Remove page ${i + 1}`}
            className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-ink text-accent-on flex items-center justify-center cursor-pointer transition-colors hover:bg-ink-hover"
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
        !started ? (
          // Reached only when this mount had no gesture behind it
          // (`autoStart={false}`) — `getUserMedia` waits for this tap
          // instead of firing on mount. See the module header.
          <div className="flex flex-col items-center gap-4 py-10 text-center">
            <p className="text-dense-sm text-t3 max-w-[36ch] text-pretty">
              Lemely needs your camera to photograph the paper.
            </p>
            <div className="flex items-center gap-2.5 flex-wrap justify-center">
              <Button variant="accent" size="md" onClick={() => setStarted(true)}>
                <Camera size={16} weight="bold" />
                Take a photo
              </Button>
              <Button variant="ghost" size="md" onClick={onCancel}>
                <X size={16} />
                Cancel
              </Button>
            </div>
          </div>
        ) : (
        <>
          {/* Task 7 (B5a) · landscape guidance. This capture flow is a
              portrait 3:4 frame (see below); a coarse-pointer (phone/tablet)
              reader who rotates their device gets a viewfinder half its own
              width instead of a layout that reflows for it. Tailwind 4's
              built-in `landscape:` variant (a real `orientation` media
              query, not an arbitrary one) plus `pointer-coarse:` — a
              landscape *desktop* window, which has no orientation to fix,
              never sees this. */}
          <div
            role="status"
            className="hidden landscape:pointer-coarse:flex items-center gap-2 rounded-md bg-warn/10 px-3 py-2 text-dense-sm text-warn"
          >
            Turn your phone upright for the best scan.
          </div>

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
            {/* Task 8 (B5b) · document quad overlay — an empty `points`
                attribute (the default, set imperatively above) renders
                nothing; `pointer-events-none` keeps it from intercepting the
                "Capture page" tap below it. */}
            {!cameraError && !starting ? (
              <svg
                className="absolute inset-0 w-full h-full pointer-events-none"
                viewBox="0 0 100 100"
                preserveAspectRatio="none"
                aria-hidden="true"
              >
                <polygon
                  ref={overlayRef}
                  points=""
                  className="text-accent"
                  fill="currentColor"
                  fillOpacity={0.15}
                  stroke="currentColor"
                  strokeWidth={0.6}
                  vectorEffect="non-scaling-stroke"
                />
              </svg>
            ) : null}
            {torchAvailable ? (
              <button
                type="button"
                onClick={toggleTorch}
                aria-label={torchOn ? "Turn off torch" : "Turn on torch"}
                aria-pressed={torchOn}
                className={cn(
                  "absolute top-2.5 end-2.5 w-9 h-9 rounded-full flex items-center justify-center transition-colors",
                  torchOn ? "bg-accent text-accent-on" : "bg-ink/60 text-accent-on hover:bg-ink/75",
                )}
              >
                <Flashlight size={16} weight={torchOn ? "fill" : "regular"} />
              </button>
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
        )
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
            <div className="text-dense-sm text-accent-ink leading-[1.5] text-pretty">
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
