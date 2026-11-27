import { useState } from "react"
import { useReviewItemImage } from "@/lib/hooks/useTeacherApi"

/** What the answer panel needs to show the scan, with no knowledge of how it was fetched. */
export interface AnswerImages {
  cropUrl: string | null
  onCropError: () => void
  pageUrl: string | null
  onPageError: () => void
  pageRequested: boolean
  requestPage: () => void
  /** The crop's fetch or decode failed. With no `cropUrl`, false means it is still loading. */
  cropFailed: boolean
  /** The whole page's fetch or decode failed. With no `pageUrl`, false means it is loading or not yet asked for. */
  pageFailed: boolean
}

/** What the "Whole page" frame shows. "idle" is a page nobody has asked for
 * yet (the panel asks for it), never "failed": the failure message appears only
 * once a request actually failed, and a failed page never sits on an endless
 * loading skeleton. */
export function pageFrame(images: Pick<AnswerImages, "pageUrl" | "pageRequested" | "pageFailed">): "image" | "loading" | "failed" | "idle" {
  if (images.pageUrl) return "image"
  if (images.pageFailed) return "failed"
  return images.pageRequested ? "loading" : "idle"
}

/**
 * The crop loads with the answer (I3: only when the item has a box). The
 * whole page is fetched only once the teacher asks for it, then kept for that
 * item. A failed fetch or decode is reported as `cropFailed` / `pageFailed`,
 * and the panel says so: "Couldn't show the scan." above Lemely's reading, or
 * "Couldn't show the page."
 */
export function useAnswerImages(itemId: string | undefined, hasScan: boolean): AnswerImages {
  const [pageFor, setPageFor] = useState<string | null>(null)
  const crop = useReviewItemImage(itemId, "crop", hasScan)
  const page = useReviewItemImage(itemId, "page", hasScan && pageFor === itemId)
  return {
    cropUrl: crop.url,
    onCropError: crop.onDecodeError,
    cropFailed: crop.failed,
    pageUrl: page.url,
    onPageError: page.onDecodeError,
    pageFailed: page.failed,
    pageRequested: pageFor === itemId,
    requestPage: () => {
      if (itemId) setPageFor(itemId)
    },
  }
}
