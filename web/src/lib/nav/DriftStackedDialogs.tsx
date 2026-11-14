import { useState } from "react"
import { Modal } from "@/components/ui/modal"

/*
 * Behaviour-harness page, present only in a drift build (`VITE_LEMELY_DRIFT=1`, see exposeRouter.ts):
 * `routes.tsx` adds it behind `DRIFT_BUILD`, a build-time constant, so a deployed build has neither the
 * route nor this file's code.
 *
 * No product screen stacks two dialogs and closes both in one handler, and that is the one case the
 * history stack's deferred unwind exists for. This page builds it, so a browser check can drive it.
 */
export default function DriftStackedDialogs() {
  const [lower, setLower] = useState(false)
  const [upper, setUpper] = useState(false)
  return (
    <main className="p-6">
      <h1 className="text-display-md">Stacked dialogs</h1>
      <button
        type="button"
        onClick={() => {
          setLower(true)
          setUpper(true)
        }}
      >
        Open both
      </button>
      <button
        type="button"
        onClick={() => {
          setLower(false)
          setUpper(false)
        }}
      >
        Close both
      </button>
      <Modal open={lower} onClose={() => setLower(false)} title="Lower dialog">
        <p>Lower</p>
      </Modal>
      <Modal open={upper} onClose={() => setUpper(false)} title="Upper dialog">
        <p>Upper</p>
      </Modal>
    </main>
  )
}
