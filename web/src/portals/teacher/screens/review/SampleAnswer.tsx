/* Hallmark · pre-emit critique: P4 H4 E4 S4 R3 V3 */
import { useState } from "react"
import { Modal } from "@/components/ui/modal"
import { AnswerPanel, type AnswerImages } from "./AnswerPanel"
import { initialMarkState } from "./markModel"
import { SAMPLE_VIEW } from "./sampleAnswerView"

/*
 * "See a sample answer" on the first-run queue (states-r1 RQ1). The mock draws the link but nothing
 * behind it, so this is the choice: the real answer panel, fed one made-up answer, in the shared
 * Modal. It is the exact screen the teacher meets on their first flagged answer, so what they learn
 * here is what they use. The content is static: no request, nothing saved. The sample is the mock's
 * own answer (RQ2 and the panel in t.js: density, 54 / 20, unit missing), with a made-up student.
 */

const noop = () => {}
// The sample has no scan to fetch, so the panel falls back to Lemely's reading of the answer.
const NO_IMAGES: AnswerImages = { cropUrl: null, onCropError: noop, pageUrl: null, onPageError: noop, pageRequested: false, requestPage: noop }

/** Practice, not a record: the ticks, the stepper and the note work, and Accept, Save or Dismiss only close it. */
export function SampleAnswerBody({ onDone }: { onDone: () => void }) {
  const [state, setState] = useState(() => initialMarkState(SAMPLE_VIEW.points, SAMPLE_VIEW.lemelyMarks, SAMPLE_VIEW.maximumMarks))
  const [note, setNote] = useState("")
  return (
    <AnswerPanel
      view={SAMPLE_VIEW}
      images={NO_IMAGES}
      marking={{ state, onChange: setState, note, onNote: setNote, onAccept: onDone, onDismiss: onDone }}
    />
  )
}

/** The Modal unmounts its body when closed, so each opening starts from Lemely's mark again. */
export function SampleAnswer({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose} size="lg" title="A sample answer" description="Made up, to show how checking works. Nothing here is saved.">
      <SampleAnswerBody onDone={onClose} />
    </Modal>
  )
}
