import type { NewDeckMode } from "./newDeckView"

export interface NewDeckSeed {
  mode: NewDeckMode | null
  subjectCode: string
  topic: string | null
}

/** Placeholder: Task 11 replaces this with the new-deck sheet. */
export function NewDeckSheet(_props: { seed: NewDeckSeed | null; onClose: () => void; onStarted: (deckId: string) => void }) {
  return null
}
