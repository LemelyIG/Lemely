import type { EstimateRequest } from "@/lib/billingTypes"

/*
 * The estimate behind "Generate questions" prices what is still missing, not the whole quiz
 * (04 `EstimateRequestDTO.count` is 1 to 50 and has no quiz id). When the quiz already holds its
 * requested count nothing is missing, so there is no request to price: building one for a single
 * question would block, or quote, a job that costs nothing.
 */
export function generateQuizEstimateRequest(args: {
  enabled: boolean
  requestedCount: number | null
  includedCount: number
}): EstimateRequest | null {
  if (!args.enabled) return null
  if (args.requestedCount === null) return { action: "generate_quiz" }
  const missing = args.requestedCount - args.includedCount
  if (missing <= 0) return null
  return { action: "generate_quiz", count: Math.min(50, missing) }
}
