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
    pageUrl: page.url,
    onPageError: page.onDecodeError,
    pageRequested: pageFor === itemId,
    requestPage: () => {
      if (itemId) setPageFor(itemId)
    },
  }
}
