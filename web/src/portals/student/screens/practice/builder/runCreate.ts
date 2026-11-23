import type { CreatePracticeResponse, PracticeFilterSet } from "@/lib/practiceTypes"
import {
  applyCreateOutcome,
  beginCreate,
  createOutcome,
  draftToFilters,
  type BuilderDraft,
  type BuilderSession,
  type CreateDestination,
  type CreateOutcome,
  type CreateResult,
} from "./builderModel"

/** What the sheet lends `runCreate`: the mutation, the session setter and the side effects. */
export interface CreateIo {
  mutate: (filters: PracticeFilterSet) => Promise<CreatePracticeResponse>
  update: (change: (s: BuilderSession) => BuilderSession) => void
  invalidate: (queryKey: readonly string[]) => void
  toast: (title: string) => void
  navigate: (to: string) => void
  refetchPreview: () => void
}

/**
 * One attempt to make the set. The decision lives in `createOutcome`; this runs
 * the steps around it in order, so a test can drive it with fakes.
 */
export async function runCreate(io: CreateIo, draft: BuilderDraft, dest: CreateDestination, expected: number): Promise<CreateOutcome> {
  io.update(beginCreate)
  let result: CreateResult
  try {
    result = { ok: true, created: await io.mutate(draftToFilters(draft)) }
  } catch (error) {
    result = { ok: false, error }
  }
  const outcome = createOutcome(result, dest, expected)
  io.update((s) => applyCreateOutcome(s, outcome))
  if (outcome.kind === "created") {
    io.invalidate(outcome.invalidate)
    if (outcome.toast) io.toast(outcome.toast)
    io.navigate(outcome.to)
  } else if (outcome.kind === "failed") {
    io.refetchPreview()
  }
  return outcome
}
