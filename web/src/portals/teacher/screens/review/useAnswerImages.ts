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
  /** The crop's fetch or decode failed (absent: treat as not failed). */
  cropFailed?: boolean
  /** The whole page's fetch or decode failed (absent: treat as not failed). */
  pageFailed?: boolean
}

/** What the "Whole page" frame shows. A failed page is "failed", never a
 * loading skeleton that cannot end. */
export function pageFrame(images: Pick<AnswerImages, "pageUrl" | "pageRequested" | "pageFailed">): "image" | "loading" | "failed" {
  if (images.pageUrl) return "image"
  return images.pageRequested && !images.pageFailed ? "loading" : "failed"
}

/**
 * The crop loads with the answer (I3: only when the item has a box). The
 * whole page is fetched only once the teacher asks for it, then kept for that
 * item. Any failure is absence: the panel falls back to the transcription, or
 * to "Couldn't show the page."
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
