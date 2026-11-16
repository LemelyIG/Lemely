import { useState } from "react"
import { useReviewItemImage } from "@/lib/hooks/useTeacherApi"

/**
 * The crop loads with the answer (I3: only when the item has a box). The
 * whole page is fetched only once the teacher asks for it, then kept for that
 * item. Any failure is absence: the panel falls back to the transcription, or
 * to "Couldn't show the page."
 */
export function useAnswerImages(itemId: string | undefined, hasScan: boolean) {
  const [pageFor, setPageFor] = useState<string | null>(null)
  const crop = useReviewItemImage(itemId, "crop", hasScan)
  const page = useReviewItemImage(itemId, "page", hasScan && pageFor === itemId)
  return { crop, page, requestPage: () => itemId && setPageFor(itemId), pageRequested: pageFor === itemId }
}
