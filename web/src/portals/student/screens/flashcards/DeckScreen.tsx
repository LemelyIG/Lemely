/* Hallmark · pre-emit critique: P4 H4 E3 S3 R5 V3 */
import { useEffect } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { DeckBody } from "./DeckBody"
import { isWide } from "./isWide"

/**
 * FV (phone and tablet). On desktop the deck lives in the shelf's side panel, so this redirects
 * there. Back is the shell's own control on this route (the trail is two deep), so none is drawn here.
 */
export function DeckScreen() {
  const { deckId = "" } = useParams<{ deckId: string }>()
  const navigate = useNavigate()
  useEffect(() => {
    if (isWide()) navigate(`/student/flashcards?deck=${deckId}`, { replace: true })
  }, [deckId, navigate])
  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col px-[18px] pb-24 pt-3.5">
      <DeckBody key={deckId} deckId={deckId} variant="page" onDeleted={() => navigate("/student/flashcards", { replace: true })} />
    </div>
  )
}
